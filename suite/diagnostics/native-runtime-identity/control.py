"""Finite identity diagnostic adapters. Never run Office or whole-engine admission."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tarfile

DATA = Path(__file__).resolve().parent
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
FALLBACK = '680(Build:1)'
NAMES = ('version.ini', 'setup.ini')
ACCEPTED = ('authentic-no-git', 'authentic-parent', 'authentic-developer', 'fixture-core', 'fixture-empty')
REJECTED = ('unknown-40hex', 'wrong-fallback', 'wrong-config', 'wrong-source-hash',
            'wrong-source-size', 'wrong-source-version', 'wrong-source-core', 'wrong-source-url',
            'mixed', 'missing-version', 'duplicate-buildid', 'missing-buildid', 'wrong-section',
            'stage-reference-hash', 'stage-reference-size', 'stage-row-hash',
            'stage-missing-row', 'stage-duplicate-row', 'stage-wrong-member')
CASES = ACCEPTED + REJECTED
FLAGS = dict(diagnosticOnly=True, fullEngineQualified=False, baseQualified=False,
             runtimeExecuted=False, officeReplacementCertified=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def descriptor(path):
    regular(path)
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=digest(raw))


def regular(path, directory=False):
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'Linked control path: ' + str(ancestor))
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            'Control requires a regular ' + ('directory: ' if directory else 'file: ') + str(path))


def write(path, raw):
    regular(path.parent, directory=True)
    with path.open('xb') as stream:
        stream.write(raw)


def save(path, value):
    write(path, (json.dumps(value, indent=2) + '\n').encode())


def load(path):
    regular(path)
    return json.loads(path.read_bytes())


def source():
    return load(DATA / 'source.json')


def check(raw, pin, label):
    require(len(raw) == pin['bytes'] and digest(raw) == pin['sha256'], 'Source pin mismatch: ' + label)


def fragments_from_members(members):
    result = {}
    for row in source()['members']:
        raw = members[row['member']]
        check(raw, row, row['member'])
        lines = raw.splitlines(keepends=True)
        for fragment in row['fragments']:
            selected = b''.join(b''.join(lines[a-1:b]) for a, b in fragment['physicalLfRanges'])
            check(selected, fragment, fragment['path'])
            require(selected == (DATA / fragment['path']).read_bytes(), 'Committed fragment drift')
            result[fragment['path']] = selected
    return result


def authenticate_extract(archive, source_root, output):
    """Read only exact regular members; never call tar extract or follow archive links."""
    regular(archive)
    pin = source()['archive']
    require(archive.stat().st_size == pin['bytes'], 'Actual full source archive size mismatch')
    h = hashlib.sha256()
    with archive.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    require(h.hexdigest() == pin['sha256'], 'Actual full source archive SHA256 mismatch')
    regular(source_root, directory=True)
    require(not any(source_root.iterdir()), 'Fresh empty no-Git source namespace required')
    expected = {row['member']: row for row in source()['members']}
    members = {}
    # Streaming traversal detects duplicate selected names and avoids an unbounded member table.
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            if member.name not in expected:
                continue
            row = expected[member.name]
            require(member.name not in members and member.isfile() and not member.issym()
                    and not member.islnk() and member.size == row['bytes'], 'Unsafe/duplicate source member')
            handle = stream.extractfile(member)
            require(handle is not None, 'Missing source member stream')
            with handle:
                raw = handle.read(row['bytes'] + 1)
            check(raw, row, member.name)
            relative = Path(*member.name.split('/')[1:])
            target = source_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target, raw)
            members[member.name] = raw
    require(set(members) == set(expected), 'Authenticated selected source member missing')
    fragments = fragments_from_members(members)
    for name, raw in fragments.items():
        write(output / name, raw)
    save(output / 'source-extraction.json', dict(archive=descriptor(archive),
         members=[dict(member=name, **descriptor(source_root / Path(*name.split('/')[1:])))
                  for name in members], fragments=[descriptor(output / name) for name in fragments],
         extraction='Exact regular selected members only; no archive links or generic extraction', **FLAGS))
    return fragments


def configuration(fragments):
    text = fragments['version-declaration.ac'].decode()
    match = re.fullmatch(r'AC_INIT\(\[LibreOffice\],\[(\d+)\.(\d+)\.(\d+)\.(\d+)\],\[\],\[\],\[http://documentfoundation.org/\]\)\n', text)
    require(match is not None, 'Authentic version declaration changed')
    values = dict(zip(('LIBO_VERSION_MAJOR', 'LIBO_VERSION_MINOR', 'LIBO_VERSION_MICRO', 'LIBO_VERSION_PATCH'), match.groups()))
    values['LIBO_VERSION_SUFFIX'] = ''
    require('.'.join(match.groups()) == '26.8.1.1', 'Control version changed')
    return values


def render_fragments(fragments, output, unix_output, unix_parent, unix_source, *, cygwin=True):
    for value in (unix_output, unix_parent, unix_source):
        # Authentic upstream interpolates unquoted SRCDIR. Refuse unsafe paths instead of changing it.
        require(re.fullmatch(r'/[A-Za-z0-9_./:-]+', value) is not None, 'Authentic control needs shell-safe POSIX paths')
    config = configuration(fragments)
    save(output / 'configuration.json', config)
    items = []
    text = fragments['installed-profile-items.scp'].decode()
    for name, body in re.findall(r'^ProfileItem (\w+)\n(.*?)^End\n', text, re.M | re.S):
        item = dict(re.findall(r'^\s*(Section|Key|Value) = "([^"\n]*)";', body, re.M))
        require(item in (dict(Section='Version', Key='buildid', Value='<buildid>'),
                         dict(Section='Bootstrap', Key='buildid', Value='<buildid>')), 'Unexpected authentic ProfileItem')
        items.append(dict(name=name, **item))
    require(len(items) == 2 and {i['Section'] for i in items} == {'Version', 'Bootstrap'}, 'Both authentic ProfileItems required')
    save(output / 'installer-input.json', dict(configuration=config, profileItems=items,
         environment=dict(config, PRODUCTNAME='LibreOfficeDev', PRODUCTVERSION='26.8', OOO_VENDOR='The Document Foundation'),
         boundary='Control input derived from authentic AC_INIT. Product/vendor/languages are finite adapter inputs, not configure output.'))
    perl = b'''use strict; use warnings; use JSON::PP;
my ($input_path,$output)=@ARGV;
open my $in,'<:raw',$input_path or die $!;
my $input; { local $/; $input=decode_json(<$in>); } close $in;
my $environment=$input->{'environment'};
''' + fragments['environment-build.pl'] + b'''$installer::globals::buildid=$environment->{'LIBO_VERSION_PATCH'};
''' + fragments['replace-setup-variables.pl'] + fragments['sorting-profile.pl'] + fragments['windows-lineends.pl'] + b'''
my $languages='en-US_ko_qtz';
my @items=@{$input->{'profileItems'}};
my %variables=(PRODUCTNAME=>$environment->{'PRODUCTNAME'},PRODUCTVERSION=>$environment->{'PRODUCTVERSION'},LIBO_VERSION_MAJOR=>$environment->{'LIBO_VERSION_MAJOR'});
replace_setup_variables(\\@items,\\$languages,\\%variables);
my $immediate_child_status_word=$?;
for my $item (@items) {
    my @file=('['.$item->{'Section'}.']'."\\n",$item->{'Key'}.'='.$item->{'Value'}."\\n");
    my $sorted=sorting_profile(\\@file);
    include_windows_lineends($sorted);
    my $name=$item->{'Section'} eq 'Version' ? 'version.ini' : 'setup.ini';
    open my $out,'>:raw',"$output/$name" or die $!;
    print {$out} join('',@$sorted); close $out or die $!;
}
print encode_json({immediateChildStatusWord=>$immediate_child_status_word,perlPlatform=>$^O,
    boundary=>'Status word immediately after authentic replacement; separate Git probes do not intercept nested Git.'})."\\n";
'''
    write(output / 'installed-control.pl', perl)
    # Empty scheduler/trace macros and explicit rc suffix are adapter bindings only.
    make = ('.DEFAULT_GOAL := control\nSHELL := /bin/sh\n'
            f'SRCDIR := {unix_parent}\ngb_CustomTarget_workdir := {unix_output}/developer\n'
            'gb_Helper_get_rcfile = $(1).ini\nPRODUCTNAME := LibreOfficeDev\n'
            f'LIBO_VERSION_MAJOR := {config["LIBO_VERSION_MAJOR"]}\n'
            'OOO_VENDOR := The Document Foundation\nOS := WNT\n'
            'setup := $(gb_CustomTarget_workdir)/instsetoo_native/setup/setup.ini\n'
            'version := $(gb_CustomTarget_workdir)/instsetoo_native/setup/version.ini\n'
            '.PHONY: control\ncontrol: $(setup) $(version)\n')
    write(output / 'developer-control.mk', make.encode() + fragments['developer-setup.mk'] + b'\n' + fragments['developer-version.mk'])
    for case in ('no-git', 'parent'):
        (output / ('installed-' + case)).mkdir()
    (output / 'developer/instsetoo_native/setup').mkdir(parents=True)
    commands = []
    tools = 'git perl make bash cygpath' if cygwin else 'git perl make bash'
    shell = ['set -euo pipefail', 'export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',
             f'for tool in {tools}; do type -a "$tool"; resolved=$(command -v "$tool"); /usr/bin/readlink -f -- "$resolved"; /usr/bin/sha256sum -- "$resolved"; done',
             'git --version', 'perl -v', 'make --version', f'cd {shlex.quote(unix_output)}',
             # Each expected child failure is retained while this owned shell exits normally.
             'capture() { name=$1; shift; set +e; "$@" > "$name.stdout.raw" 2> "$name.stderr.raw"; child_status=$?; set -e; printf \'{"exitCode":%s}\\n\' "$child_status" > "$name.status.json"; }']
    for case, directory in (('no-git', unix_source), ('parent', unix_parent)):
        for label, argv in (
            ('rev-parse', ['git', '-C', directory, 'rev-parse', '--show-toplevel']),
            ('installed-git', ['git', '-C', directory, 'log', '-n', '1', '--pretty=format:%H']),
            ('developer-git', ['git', 'log', '-1', '--format=%H'])):
            name = case + '-' + label
            cwd = directory if label == 'developer-git' else unix_output
            shell.append('cd ' + shlex.quote(cwd))
            shell.append('capture ' + shlex.quote(unix_output + '/' + name) + ' ' + shlex.join(argv))
            commands.append(dict(name=name, argv=argv, cwd=cwd,
                literalUpstreamExpression=('git -C $ENV{\'SRCDIR\'} log -n 1 --pretty=format:"%H"' if label == 'installed-git'
                    else 'cd $(SRCDIR) && git log -1 --format=%H' if label == 'developer-git' else None),
                separateProbe=True, interceptsNestedGit=False))
        shell.extend(['cd ' + shlex.quote(unix_output), 'export SRCDIR=' + shlex.quote(directory),
                      'export OOO_VENDOR=' + shlex.quote('The Document Foundation'),
                      'capture perl-' + case + ' /usr/bin/perl installed-control.pl installer-input.json installed-' + case])
        commands.append(dict(name='perl-' + case, argv=['/usr/bin/perl', 'installed-control.pl', 'installer-input.json', 'installed-' + case], cwd=unix_output, sourceDirectory=directory))
    shell.extend(['capture developer-make /usr/bin/make --no-builtin-rules --no-builtin-variables --no-print-directory -f developer-control.mk', 'exit 0'])
    commands.append(dict(name='developer-make', argv=['/usr/bin/make', '--no-builtin-rules', '--no-builtin-variables', '--no-print-directory', '-f', 'developer-control.mk'], cwd=unix_output))
    write(output / 'generate-control.sh', ('\n'.join(shell) + '\n').encode())
    save(output / 'generation-commands.json', dict(commands=commands, sourceDirectory=unix_source,
         parentDirectory=unix_parent, boundary='Raw Git probes are distinct invocations. Perl retains its raw stdout/stderr/status and immediate post-call child status separately.', **FLAGS))


def render(args):
    require(not any(name.upper().startswith('GIT_') for name in os.environ), 'Inherited Git environment forbidden')
    args.output.mkdir()
    fragments = authenticate_extract(args.archive, args.source_root, args.output)
    render_fragments(fragments, args.output, args.unix_output, args.unix_parent, args.unix_source)


def read_id(path, section):
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    require(re.findall(r'^\[([^\]\r\n]+)\]', text, re.M) == [section], 'Generated section differs')
    ids = re.findall(r'^buildid=([^\r\n]*)', text, re.M)
    require(len(ids) == 1, 'Generated buildid differs')
    return ids[0]


def verify_generation(generated, parent, require_cygwin=True):
    require(re.fullmatch('[0-9a-f]{40}', parent) is not None, 'Actual diagnostic parent SHA required')
    records = []
    for case in ('no-git', 'parent'):
        for label in ('rev-parse', 'installed-git', 'developer-git'):
            name = case + '-' + label
            status = load(generated / (name + '.status.json'))['exitCode']
            stdout = (generated / (name + '.stdout.raw')).read_bytes()
            stderr = (generated / (name + '.stderr.raw')).read_bytes()
            require(type(status) is int, 'Child status must be an exact integer')
            if case == 'no-git':
                require(status != 0 and stdout == b'' and stderr, 'Actual no-Git command must fail with empty stdout')
            else:
                require(status == 0, 'Known actual parent Git command failed')
                if label != 'rev-parse':
                    require(stdout.rstrip(b'\r\n') == parent.encode(), 'Actual Git parent differs')
            records.append(dict(name=name, exitCode=status, stdout=descriptor(generated / (name + '.stdout.raw')),
                                stderr=descriptor(generated / (name + '.stderr.raw')), separateProbe=True, interceptsNestedGit=False))
        require(load(generated / ('perl-' + case + '.status.json'))['exitCode'] == 0, 'Authentic Perl failed')
        perl = json.loads((generated / ('perl-' + case + '.stdout.raw')).read_bytes())
        word = perl['immediateChildStatusWord']
        require(type(word) is int and (word != 0 if case == 'no-git' else word == 0), 'Immediate Perl child status differs')
        if require_cygwin:
            require('cygwin' in perl['perlPlatform'].lower(), 'Actual Cygwin Perl required')
        for name, section in zip(NAMES, ('Version', 'Bootstrap')):
            path = generated / ('installed-' + case) / name
            require(read_id(path, section) == (FALLBACK if case == 'no-git' else parent), 'Authentic installed buildid differs')
            raw = path.read_bytes()
            require(raw.count(b'\r\n') == 2 and raw.count(b'\n') == 2, 'Authentic installed fragment must retain CRLF')
        records.append(dict(name='perl-' + case, **perl))
    require(load(generated / 'developer-make.status.json')['exitCode'] == 0, 'Authentic developer Make failed')
    for name, section in zip(NAMES, ('Version', 'Bootstrap')):
        require(read_id(generated / 'developer/instsetoo_native/setup' / name, section) == parent, 'Authentic developer identity differs')
    return records


def verify_retained_source(generated):
    """The selected no-Git source bytes must remain unchanged after generation."""
    extraction = load(generated / 'source-extraction.json')
    for row in extraction['members']:
        actual = descriptor(Path(row['path']))
        require(actual['bytes'] == row['bytes'] and actual['sha256'] == row['sha256'], 'Selected no-Git source changed during control')
    for row in extraction['fragments']:
        actual = descriptor(Path(row['path']))
        require(actual == row, 'Retained authentic fragment changed during control')
    return dict(membersVerified=len(extraction['members']), fragmentsVerified=len(extraction['fragments']), unchanged=True)


def pin():
    archive = source()['archive']
    return dict(url=archive['url'], size=archive['bytes'], sha256=archive['sha256'], version='26.8.1.1', coreCommit=CORE)


def make_cases(generated, output, parent, require_cygwin=True):
    observations = verify_generation(generated, parent, require_cygwin)
    retained_source = verify_retained_source(generated) if require_cygwin else None
    output.mkdir()
    config = load(generated / 'configuration.json')
    for case in CASES:
        root = output / case
        runtime = root / 'runtime'
        evidence = root / 'evidence'
        (runtime / 'program').mkdir(parents=True)
        evidence.mkdir()
        (root / 'input').mkdir()
        source_pair = generated / ('installed-parent' if case == 'authentic-parent' else
                      'developer/instsetoo_native/setup' if case == 'authentic-developer' else 'installed-no-git')
        pair = {name: (source_pair / name).read_bytes() for name in NAMES}
        values = {'fixture-core': CORE, 'fixture-empty': '', 'unknown-40hex': '1'*40, 'wrong-fallback': '681(Build:1)'}
        if case in values:
            pair = {name: raw.replace(FALLBACK.encode(), values[case].encode()) for name, raw in pair.items()}
        if case == 'mixed':
            pair['setup.ini'] = pair['setup.ini'].replace(FALLBACK.encode(), parent.encode())
        if case == 'missing-version':
            del pair['version.ini']
        if case == 'duplicate-buildid':
            pair['version.ini'] += b'buildid=680(Build:1)\r\n'
        if case == 'missing-buildid':
            pair['version.ini'] = b'[Version]\r\nVendor=control-fixture\r\n'
        if case == 'wrong-section':
            pair['version.ini'] = pair['version.ini'].replace(b'[Version]', b'[Wrong]')
        rows = []
        for name, raw in pair.items():
            write(runtime / 'program' / name, raw)
            write(root / 'input' / name, raw)
            rows.append(dict(path='program/' + name, archivePath='fixture-main.zip',
                 archiveMember='fixture-wrapper/program/' + name, bytes=len(raw), sha256=digest(raw)))
        stage = dict(schemaVersion=1, kind='source-built-installed-runtime-stage', passed=True,
            runtimeRoot=str(runtime), configuredProduct='LibreOfficeDev', configuredVersion='26.8.1.1',
            archives=[dict(kind='main', path='fixture-main.zip', wrapperRoot='fixture-wrapper')], files=rows,
            controlFixture=True, historicalNative29Map=False, fixtureBoundary=source()['boundary'])
        if case == 'stage-row-hash':
            rows[0]['sha256'] = '0'*64
        if case == 'stage-missing-row':
            rows.pop()
        if case == 'stage-duplicate-row':
            rows.append(copy.deepcopy(rows[0]))
        if case == 'stage-wrong-member':
            rows[0]['archiveMember'] = 'other-wrapper/' + rows[0]['path']
        stage_path = evidence / 'installed-runtime-stage.json'
        save(stage_path, stage)
        summary = dict(passed=True, runtimeRoot=str(runtime), receipt=descriptor(stage_path))
        if case == 'stage-reference-hash':
            summary['receipt']['sha256'] = '0'*64
        if case == 'stage-reference-size':
            summary['receipt']['bytes'] += 1
        source_pin = pin()
        changed_config = copy.deepcopy(config)
        if case == 'wrong-config':
            changed_config['LIBO_VERSION_PATCH'] = '2'
        changes = {'wrong-source-hash': ('sha256', '0'*64), 'wrong-source-size': ('size', 302435509),
                   'wrong-source-version': ('version', '26.8.1.2'), 'wrong-source-core': ('coreCommit', '2'*40),
                   'wrong-source-url': ('url', pin()['url'] + '?wrong=1')}
        if case in changes:
            key, value = changes[case]
            source_pin[key] = value
        save(root / 'case.json', dict(case=case, expectedAccepted=case in ACCEPTED,
             sourceCommit=parent, sourcePin=source_pin, configuration=changed_config,
             installedRuntimeStage=summary, runtimeRoot=str(runtime), evidenceDirectory=str(evidence),
             inputFiles={name: descriptor(root / 'input' / name) for name in pair},
             fixtureProvenance=dict(controlFixture=True, stageMap='Tiny synthetic map, no main archive exists',
                 profilePair=('Authentic installed no-Git buildid fragments' if case == 'authentic-no-git' else
                              'Authentic installed actual-parent buildid fragments' if case == 'authentic-parent' else
                              'Authentic Make developer setup/version' if case == 'authentic-developer' else
                              'Explicit mutation or supported-mode fixture derived from authentic no-Git fragments'),
                 historicalOriginalIniBytes=False), **FLAGS))
    save(output / 'generation-verification.json', dict(observations=observations, retainedSource=retained_source, **FLAGS))


def import_consumer():
    manifest = source()['consumer']
    snapshot = DATA / manifest['root']
    for row in manifest['files']:
        check((snapshot / row['path']).read_bytes(), row, row['path'])
    require(not any(name == 'suite' or name.startswith('suite.') for name in sys.modules), 'Consumer process already imported another suite')
    sys.path.insert(0, str(snapshot))
    module = importlib.import_module('suite.prepare')
    crt = importlib.import_module('suite.crt')
    imports = []
    for actual, relative in ((module, 'suite/prepare.py'), (crt, 'suite/crt.py')):
        require(Path(actual.__file__).resolve() == (snapshot / relative).resolve(), 'Exact consumer snapshot was not imported first')
        imports.append(descriptor(Path(actual.__file__)))
    return module._source_build_identity, imports


def consumer_mutations(proof):
    result = []
    for name in ('false-mode', 'false-derivation', 'false-descriptor', 'false-final',
                 'false-stage-reference', 'false-config', 'false-source', 'mixed-originals'):
        changed = copy.deepcopy(proof)
        identity = changed['runtimeBuildIdentity']
        if name == 'false-mode':
            identity['identityMode'] = 'actual-parent'
        elif name == 'false-derivation':
            identity['installedFallbackDerivation']['normalizedBuild'] = '681'
        elif name == 'false-descriptor':
            identity['originals']['program/setup.ini']['sha256'] = '0'*64
        elif name == 'false-final':
            identity['finalVerification']['files']['program/setup.ini']['buildid'] = '1'*40
        elif name == 'false-stage-reference':
            identity['stageReceipt']['sha256'] = '0'*64
        elif name == 'false-config':
            changed['configuration']['LIBO_VERSION_MAJOR'] = '27'
        elif name == 'false-source':
            changed['sourcePin']['url'] += '?wrong=1'
            identity['sourceArchiveUrl'] = changed['sourcePin']['url']
        else:
            identity['files']['program/setup.ini']['originalBuildId'] = '1'*40
        result.append((name, changed))
    return result


def audit(cases, output):
    validate, imports = import_consumer()
    # Production generation records this full member receipt; local ordinary
    # fragment guards do not pretend to have extracted the full real archive.
    generated = cases.parent / 'generated'
    retained_source = verify_retained_source(generated) if (generated / 'source-extraction.json').exists() else None
    results = []
    for case in CASES:
        root = cases / case
        spec = load(root / 'case.json')
        producer = load(root / 'producer-result.json')
        require(producer['accepted'] is spec['expectedAccepted'], 'Producer unexpected case result: ' + case)
        require(producer['diagnosticOnly'] is True, 'Missing fixture boundary')
        diagnostic = load(root / 'evidence/runtime-build-identity-diagnostic.json')
        require(diagnostic['passed'] is spec['expectedAccepted'], 'Producer diagnostic mismatch')
        before_after = []
        for name in NAMES:
            input_path = root / 'input' / name
            runtime = root / 'runtime/program' / name
            retained = root / 'evidence' / ('original-runtime-' + name)
            if input_path.exists():
                raw = input_path.read_bytes()
                require(retained.read_bytes() == raw, 'Producer did not retain exact raw original')
                require(diagnostic['files']['program/' + name]['status'] == 'retained', 'Raw snapshot status differs')
                if not spec['expectedAccepted']:
                    require(runtime.read_bytes() == raw, 'Rejected producer changed runtime bytes')
                before_after.append(dict(name=name, before=descriptor(input_path), after=descriptor(runtime), retained=descriptor(retained)))
            else:
                require(not runtime.exists() and not retained.exists() and
                    diagnostic['files']['program/' + name]['status'] == 'rejected', 'Missing input handling differs')
                before_after.append(dict(name=name, missingBeforeAndAfter=True))
        entry = dict(case=case, producerAccepted=producer['accepted'], expectedAccepted=spec['expectedAccepted'],
                     evidence=descriptor(root / 'evidence/runtime-build-identity-diagnostic.json'),
                     files=before_after, fixtureProvenance=spec['fixtureProvenance'], **FLAGS)
        if spec['expectedAccepted']:
            proof = load(root / 'identity-control-proof.json')
            identity = validate(proof, CORE)  # Only this pure exact-C API, never whole engine admission.
            for name, section in zip(NAMES, ('Version', 'Bootstrap')):
                require(read_id(root / 'runtime/program' / name, section) == CORE, 'Final real runtime ID differs')
                require(descriptor(root / 'runtime/program' / name)['sha256'] == identity['files']['program/' + name]['sha256'], 'Final real runtime bytes differ')
            entry.update(consumerAccepted=True, identityMode=identity['identityMode'], compactProof=descriptor(root / 'identity-control-proof.json'))
            if case == 'authentic-no-git':
                mutations = []
                for name, changed in consumer_mutations(proof):
                    try:
                        validate(changed, CORE)
                    except ValueError as error:
                        mutations.append(dict(case=name, rejected=True, error=str(error), fixtureOnly=True))
                    else:
                        raise ValueError('Consumer accepted mutation: ' + name)
                entry['consumerMutations'] = mutations
        else:
            require(not (root / 'identity-control-proof.json').exists(), 'Rejected fixture emitted accepted proof')
            expected_errors = {
                'wrong-source-hash': 'Authenticated input SHA256 mismatch',
                'wrong-source-size': 'Authenticated input size mismatch',
                'wrong-source-version': 'Installed stage receipt does not bind',
                'wrong-source-core': 'Installed fallback requires the exact authenticated source',
                'wrong-source-url': 'Installed fallback requires the exact authenticated source',
                'wrong-config': 'Installed fallback configuration mismatch',
                'mixed': 'Original runtime identities use mixed identity modes',
                'missing-version': 'Both original identity files must be retained',
                'duplicate-buildid': 'section/key is missing or ambiguous',
                'missing-buildid': 'section/key is missing or ambiguous',
                'wrong-section': 'section/key is missing or ambiguous',
                'stage-reference-hash': 'Authenticated input SHA256 mismatch',
                'stage-reference-size': 'Authenticated input size mismatch',
            }
            expected = ('Original identity bytes differ from unique main-archive mapping'
                        if case.startswith('stage-') and case not in expected_errors else
                        expected_errors.get(case, 'Generated runtime buildid is unrelated'))
            require(expected in producer.get('error', ''), 'Rejection did not exercise intended predicate: ' + case)
            entry['rejection'] = producer['error']
        results.append(entry)
    save(output, dict(schemaVersion=1, kind='native30-finite-identity-contract-replay', passed=True,
         consumer=dict(commit=source()['consumer']['commit'], tree=source()['consumer']['tree'], imports=imports,
                       api='suite.prepare._source_build_identity only', snapshotFirstOnSysPath=True),
         caseCount=len(results), acceptedCount=len(ACCEPTED), rejectedCount=len(REJECTED), results=results,
         retainedSource=retained_source, proofBoundary=source()['boundary'], **FLAGS))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('render')
    for name in ('archive', 'source-root', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    for name in ('unix-output', 'unix-parent', 'unix-source'):
        p.add_argument('--' + name, required=True)
    p = sub.add_parser('cases')
    p.add_argument('--generated', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--parent', required=True)
    p = sub.add_parser('audit')
    p.add_argument('--cases', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('host')
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'render':
        render(args)
    elif args.command == 'cases':
        make_cases(args.generated, args.output, args.parent)
    elif args.command == 'audit':
        audit(args.cases, args.output)
    else:
        import ctypes
        import platform
        from ctypes import wintypes
        require(sys.platform == 'win32', 'Actual native Windows Python required')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.IsWow64Process2.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.WORD))
        kernel.IsWow64Process2.restype = wintypes.BOOL
        process_machine, native_machine = wintypes.WORD(), wintypes.WORD()
        require(kernel.IsWow64Process2(kernel.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine)), 'Python IsWow64Process2 failed')
        require(process_machine.value == 0 and native_machine.value == 0xaa64, 'Actual unemulated ARM64 Python required')
        save(args.output, dict(executable=descriptor(Path(sys.executable)), pid=os.getpid(), version=sys.version,
             processMachine=process_machine.value, nativeMachine=native_machine.value,
             platform=platform.platform(), isolated=bool(sys.flags.isolated), **FLAGS))


if __name__ == '__main__':
    main()
