"""One current-source CSV Home observation; human review of the raw PNG is pending.

The genuine canonical21 fixture baseline and all shared Home ownership, getter,
close and archive gates remain mandatory. This diagnostic never qualifies the
full Home matrix or asserts that spreadsheet cells have painted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home_routing_smoke as home

REPO = Path(__file__).resolve().parents[2]
CSV_SPEC = dict(case='home-open-calc-csv', kind='open', module='calc', extension='csv')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def select_csv_spec(plan):
    matches = [row for row in plan if row.get('case') == CSV_SPEC['case']]
    assert len(matches) == 1, 'Exactly one fixed CSV row is required'
    spec, = matches
    assert spec == CSV_SPEC, 'Only the unchanged fixed CSV Home Open row is allowed'
    return dict(spec)


def prepare_output(suite, features, output):
    paths = [Path(p) for p in (suite, features, output)]
    for path in paths:
        home._unlinked(path)
        assert not str(path).startswith(('\\\\', '//')), 'Only local paths are allowed'
    suite, features, output = [p.resolve() for p in paths]
    assert suite.is_dir() and features.is_dir()
    for left, right in ((suite, features), (suite, output), (features, output)):
        assert left != right and left not in right.parents and right not in left.parents, 'Diagnostic paths overlap'
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures').mkdir()
    (output / 'diagnostics').mkdir()
    return suite, features, output


def source_join(suite, repo=REPO, proof=None):
    """Join current harness/host sources and packaged worker bytes to Git ZIP."""
    proof = proof if proof is not None else {}
    proof.update(schemaVersion=1, kind='csv-control-current-source-join', success=False, sourceFiles=[], packageFiles=[])
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True, encoding='utf-8', timeout=30).strip()
    def digest(raw):
        return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    commit = git('rev-parse', 'HEAD')
    proof.update(sourceCommit=commit, sourceTree=git('rev-parse', 'HEAD^{tree}'))
    assert not git('status', '--porcelain', '--untracked-files=normal'), 'Current source must be clean and committed'
    assert os.environ.get('GITHUB_SHA', commit) == commit, 'Workflow source differs from checkout'
    def relevant(name):
        return bool(name and not name.endswith('/') and
            (name.startswith(('suite/e2e/', 'suite/worker/', 'suite/shell/', 'suite/config/')) or
             name in ('suite/package.py', 'suite/payload.py', '.github/workflows/office-csv-postgetter-control.yml')))
    expected_members = sorted(name for name in git('ls-tree', '-r', '--name-only', '-z', commit).split('\0') if relevant(name))
    inventory = json.loads((suite / 'suite-inventory.json').read_bytes())
    provenance = json.loads((suite / 'suite-provenance.json').read_bytes())
    assert inventory['architecture'] == provenance['architecture'] == 'x64'
    assert provenance['sourceCommit'] == commit, 'Suite package belongs to another source commit'
    package_names = ['suite-inventory.json', 'suite-provenance.json', 'runtime-branding.json',
                     'Sources/OpenGeul-Office-source.zip', 'OpenGeul.Office.exe', 'OpenGeul.Office.dll']
    package_names += sorted(p.relative_to(suite).as_posix() for p in (suite / 'worker').rglob('*') if p.is_file())
    for name in package_names:
        path = suite / name
        home._unlinked(path)
        row = dict(path=name, **digest(path.read_bytes()))
        proof['packageFiles'].append(row)
        if name != 'suite-inventory.json':
            assert inventory['files'][name] == dict(size=row['bytes'], sha256=row['sha256']), 'Package byte/inventory mismatch: ' + name
    archive_path = suite / 'Sources/OpenGeul-Office-source.zip'
    assert digest(archive_path.read_bytes())['sha256'] == provenance['sourceArchiveSha256']
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.comment == commit.encode('ascii'), 'Corresponding-source ZIP commit differs'
        names = archive.namelist()
        assert len(names) == len(set(names)), 'Duplicate corresponding-source members'
        selected = sorted(name for name in names if relevant(name))
        proof['sourceMembers'] = dict(expected=expected_members, actual=selected,
            missing=sorted(set(expected_members) - set(selected)), unexpected=sorted(set(selected) - set(expected_members)))
        assert selected == expected_members, 'Corresponding-source member set differs from committed HEAD'
        assert {'suite/e2e/csv_postgetter_control.py', 'suite/e2e/home_routing_smoke.py', 'suite/payload.py',
                '.github/workflows/office-csv-postgetter-control.yml'} <= set(selected)
        assert any(n.startswith('suite/shell/') for n in selected)
        assert any(n.startswith('suite/worker/') and n.endswith('.py') for n in selected)
        expected_workers = {n.removeprefix('suite/') for n in selected if n.startswith('suite/worker/') and not n.endswith('.md')}
        assert expected_workers == {n for n in package_names if n.startswith('worker/')}, 'Packaged worker file set differs from current source ZIP'
        for name in selected:
            path = repo / name
            home._unlinked(path)
            assert path.resolve().is_relative_to(repo.resolve())
            raw = archive.read(name)
            row = dict(path=name, **digest(raw))
            proof['sourceFiles'].append(row)
            assert path.read_bytes() == raw, 'Executing/source checkout bytes differ from ZIP: ' + name
            if name.startswith('suite/worker/') and not name.endswith('.md'):
                target = suite / name.removeprefix('suite/')
                home._unlinked(target)
                assert target.read_bytes() == raw, 'Packaged worker differs from current source ZIP: ' + name
                row['packagePath'] = target.relative_to(suite).as_posix()
    proof['success'] = True
    return proof


def verify_png(output, receipt):
    from PIL import Image
    assert receipt['image'] == CSV_SPEC['case'] + '-calc-post-getter.png'
    path = output / receipt['image']
    home._unlinked(path)
    assert 0 < path.stat().st_size <= 32 * 1024 * 1024
    raw = path.read_bytes()
    assert len(raw) == receipt['bytes'] and hashlib.sha256(raw).hexdigest() == receipt['sha256'], 'Original PNG bytes changed'
    with Image.open(path) as image:
        assert image.format == 'PNG' and image.size == (receipt['width'], receipt['height'])
        assert 0 < image.width <= 20000 and 0 < image.height <= 20000 and image.width * image.height <= 16_000_000
        image.verify()
    return dict(image=receipt['image'], bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                width=receipt['width'], height=receipt['height'], originalBytesRehashed=True)


def record_failure(output, record, exc):
    failure = dict(error=type(exc).__name__ + ': ' + str(exc),
                   traceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    if not record.get('error'):
        home.native.capture_failure(output, CSV_SPEC['case'], record, exc)
    record.update(success=False, controlFailure=failure)
    return failure


def run_control(suite, features, output):
    record = dict(CSV_SPEC, success=False, cleanClose=False, forcedCleanup=False)
    joins = dict(schemaVersion=1, kind='csv-control-current-source-join', success=False)
    integrity = dict(schemaVersion=1, kind='home-native-archive-integrity', success=False)
    run_error = png = None
    try:
        source_join(suite, REPO, joins)
        from suite.payload import verify_payload
        verify_payload(suite, json.loads((suite / 'suite-inventory.json').read_bytes()))
        joins['completePayloadVerifiedBefore'] = True
        write_json(output / 'source-join.json', joins)
        inputs = home.load_feature_inputs(suite, features)
        spec = select_csv_spec(home.build_plan())
        record.update(spec)
        home.HomeCase(suite, output, spec, inputs, {}, record).run()
        home.require_case_result(record, suite)
        assert home.load_feature_inputs(suite, features) == inputs, 'Canonical feature baseline changed'
        png = verify_png(output, home.require_csv_post_getter_screenshot(record))
        after = source_join(suite)
        assert after == {k: v for k, v in joins.items() if k != 'completePayloadVerifiedBefore'}, 'Current source/package joins changed during observation'
    except BaseException as exc:
        run_error = record_failure(output, record, exc)
        if joins.get('success') is not True:
            joins.update(run_error)
    try:
        integrity = home.verify_native_archives(suite, output / 'diagnostics', [record])
        assert len(record.get('attachments', [])) == integrity['completeArchives'] == integrity['qualifiedShutdowns'] == 1
        assert integrity['crashDumps'] == 0 and integrity['success'] is True
    except BaseException as exc:
        integrity.update(success=False, error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
    try:
        home.native.write_result(output, CSV_SPEC['case'], record)
    except BaseException as exc:
        record.update(success=False, recordWriteError=type(exc).__name__ + ': ' + str(exc))
    write_json(output / 'source-join.json', joins)
    write_json(output / 'native-integrity.json', integrity)
    success = (run_error is None and record['success'] is True and record['cleanClose'] is True and
               record['forcedCleanup'] is False and integrity['success'] is True and png is not None)
    report = dict(schemaVersion=1, kind='csv-postgetter-focused-control', success=success,
                  suite=str(suite), features=str(features), expectedCaseCount=1, completedCaseCount=1,
                  passedCaseCount=int(success), cases=[record], sourceJoin=joins, nativeIntegrity=integrity,
                  originalPng=png, finalQualificationReplacement=False, humanVisualReviewPending=True,
                  gridVisibleVerified=False, paintCompleteVerified=False)
    if run_error is not None:
        report['runError'] = run_error
    write_json(output / 'csv-postgetter-control.json', report)
    return report


def main():
    if not __debug__:
        raise RuntimeError('CSV diagnostic requires native assertions enabled')
    if os.name != 'nt':
        raise RuntimeError('Actual Windows native GUI execution is required')
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'features', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    from native_suite_architecture import observe_native_architecture, validate_native_architecture
    validate_native_architecture(observe_native_architecture(), 'x64')
    suite, features, output = prepare_output(args.suite, args.features, args.output)
    # Direct script execution also needs the repository package on sys.path.
    sys.path.insert(0, str(REPO))
    report = run_control(suite, features, output)
    print('CSV diagnostic: ' + ('passed; raw PNG awaits human review' if report['success'] else 'FAILED'), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
