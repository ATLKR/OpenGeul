"""Read-only, allowlisted observations for the existing hosted Suite unit process."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
MAX_RECEIPT_BYTES = 64 * 1024
ENVIRONMENT_NAMES = (
    'OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE', 'OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY',
    'OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY', 'OPENGEUL_FIREBIRD_SOURCE_ARCHIVE',
    'OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES', 'OPENGEUL_LIBREOFFICE_PYTHON_PATCHES',
    'OPENGEUL_LIBREOFFICE_ATL_SOURCE', 'OPENGEUL_LIBREOFFICE_MESON_SOURCE',
    'OPENGEUL_MDDS_SOURCE_ARCHIVE',
)
WHICH_NAMES = ('cc', 'gcc', 'c++', 'g++', 'patch', 'autoconf')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def collect(phase, *, env=None, source_root=ROOT, cwd=None, executable=None,
            version=None, os_name=None, is_file=None, which=None, git_runner=None):
    require(phase in ('before', 'after'), 'Expected before or after phase')
    env = os.environ if env is None else env
    os_name = os.name if os_name is None else os_name
    fixed = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
                 GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_JOB='windows-suite')
    require(os_name == 'nt' and all(env.get(k) == v for k, v in fixed.items()),
            'Actual hosted Windows Suite context required')
    require(env.get('RUNNER_ARCH') in ('X64', 'ARM64'), 'Expected native Suite runner label')
    commit = env.get('GITHUB_SHA')
    require(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit), 'Source SHA required')
    identity = {}
    for field, key in (('runId', 'GITHUB_RUN_ID'), ('runAttempt', 'GITHUB_RUN_ATTEMPT')):
        value = env.get(key)
        require(type(value) is str and re.fullmatch('[1-9][0-9]{0,19}', value), 'Canonical ' + key + ' required')
        identity[field] = int(value)
    root = Path(source_root).resolve()
    cwd = Path.cwd() if cwd is None else Path(cwd)
    require(cwd.resolve() == root, 'Unit cwd must equal the checked-out source root')
    run = subprocess.run if git_runner is None else git_runner
    result = run(['git', '-C', str(root), 'rev-parse', 'HEAD', 'HEAD^{tree}'],
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=5)
    require(type(result.stdout) is bytes and len(result.stdout) <= 1024
            and type(result.stderr) is bytes and len(result.stderr) <= 4096, 'Git receipt exceeded its bound')
    source = result.stdout.decode('ascii').splitlines()
    require(len(source) == 2 and source[0] == commit
            and re.fullmatch('[0-9a-f]{40}', source[1]), 'Actual Git HEAD/tree binding differs')
    environment = {name: env.get(name) for name in ENVIRONMENT_NAMES}
    require(all(value is None or type(value) is str for value in environment.values()),
            'Allowlisted environment values must be original strings or null')
    file_query = (lambda path: path.is_file()) if is_file is None else is_file
    capability = {}
    paths = dict(make='/usr/bin/make', bash='/bin/bash')
    for name, path in paths.items():
        value = file_query(Path(path))
        require(type(value) is bool, 'Path capability must be an exact boolean')
        capability[name] = value
    find = shutil.which if which is None else which
    tools = {name: find(name) for name in WHICH_NAMES}
    require(all(value is None or type(value) is str for value in tools.values()),
            'which observations must be original paths or null')
    capability.update(compiler=bool(tools['cc'] or tools['gcc']), cxx=bool(tools['c++'] or tools['g++']),
                      patch=bool(tools['patch']), autoconf=bool(tools['autoconf']))
    return dict(schemaVersion=1, kind='suite-unit-capabilities', phase=phase,
                capturedUtc=datetime.now(timezone.utc).isoformat(), readOnly=True,
                sourceQualified=False, productExecuted=False, repository='ATLKR/OpenGeul', job='windows-suite',
                sourceCommit=source[0], sourceTree=source[1], sourceRoot=str(root), **identity,
                architecture=env['RUNNER_ARCH'].lower(), osName=os_name, cwd=str(cwd.resolve()),
                interpreter=dict(executable=sys.executable if executable is None else executable,
                                 version=sys.version if version is None else version),
                environment=environment, pathQueries=paths, which=tools, capabilities=capability)


def write_receipt(output, receipt):
    require(receipt.get('phase') in ('before', 'after'), 'Expected before or after phase')
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    require(len(raw) <= MAX_RECEIPT_BYTES, 'Capability receipt exceeds 64 KiB')
    output = Path(output).absolute()
    for path in (output, *output.parents):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                    and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'Output ancestors must be plain directories')
    output.mkdir(parents=True, exist_ok=True)
    target = output / (receipt['phase'] + '.json')
    with target.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=('before', 'after'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        path = write_receipt(args.output, collect(args.phase))
        print(json.dumps(dict(phase=args.phase, path=str(path), readOnly=True)))
        return 0
    except Exception as error:
        print('Suite unit capability receipt failed: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
