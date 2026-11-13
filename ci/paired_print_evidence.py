"""Read-only admission of the separate nonqualifying paired-print allowlist.

No transport, process adoption, printing, reference update or release decision.
The expected checkout/run/attempt come from the owning workflow, not a receipt.
"""
import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'e2e'), str(ROOT / 'scripts')]
from paired_print_contract import (LEGACY_EDITOR, digest, expected_renderers, integer,
    require, shape, validate_fixtures, validate_fonts)
from paired_print_diagnostic import CURRENT_WASM_GENERATOR, WASM_FILES, admit_current, legacy_assets
from paired_print_windows import (fingerprint_file, fingerprint_png, is_ink_mismatch,
    read_json, read_regular, sampled_fonts)
from paired_print_collect import _exact, validate_profiles, validate_report
from prepare_payload import verify_checksums
from wasm_artifacts import expected as wasm_expected
from print_raster import inspect_print_pdf
from paired_print_run import project_failure, _empty_failure

FILE_CAP = 8 * 1024 * 1024
TOTAL_CAP = 48 * 1024 * 1024
CASES = ((1, 'table--300', 'print-fixtures/print-table--300.hwpx'),
         (6, 'basic-hwpx', 'inputs/e2e-fixtures/basic.hwpx'))


def check_legacy(workspace):
    """Reuse the exact canonical Suite checker; no download or alternate input."""
    sys.path.insert(0, str(ROOT / 'suite'))
    from prepare import check_asset
    assets = legacy_assets(read_json(ROOT / 'suite/config/runtime.lock.json')['hwp'])
    for key, name in (('portable', 'legacy-portable.zip'), ('provenance', 'legacy-provenance.json')):
        check_asset(assets[key], workspace / 'paired-locked-inputs' / name)
    old = fingerprint_file(workspace / 'paired-legacy-runtime/OpenGeul.exe')
    require((old['sha256'], old['bytes']) == (LEGACY_EDITOR, 36402688), 32)


def independent_expected(workspace, source, run_id, attempt):
    """Join actual same-job inputs against expected source; never choose from report."""
    digest(source, 40)
    integer(run_id, 1)
    integer(attempt, 1)
    check_legacy(workspace)
    package = workspace / 'package'
    checksums = verify_checksums(package)
    provenance = read_json(package / 'provenance.json', 512 * 1024)
    current = fingerprint_file(workspace / 'paired-current-runtime/OpenGeul.exe')
    wanted = wasm_expected()
    admitted = admit_current(provenance, expected_source=source, run_id=run_id, attempt=attempt,
        expected_upstream=wanted['upstream'], expected_wasm_source=wanted,
        runtime_sha256=current['sha256'], runtime_bytes=current['bytes'])
    require(checksums.get(provenance['package']) == provenance['sha256'], 32)
    wasm = read_json(workspace / 'wasm-input/OPEN_GEUL_WASM.json')
    shape(wasm, (*wanted, 'artifacts', 'generator'))
    require(all(wasm[key] == value for key, value in wanted.items())
            and wasm['generator'] == CURRENT_WASM_GENERATOR, 33)
    shape(wasm['artifacts'], WASM_FILES)
    used = 0
    for name in WASM_FILES:
        data, _ = read_regular(workspace / 'wasm-input' / name, 32 * 1024 * 1024)
        used += len(data)
        require(used <= 32 * 1024 * 1024
                and hashlib.sha256(data).hexdigest() == wasm['artifacts'][name], 33)
        if name == 'rhwp_bg.wasm':
            require(data[:8] == b'\0asm\1\0\0\0', 33)
    require(read_json(workspace / 'wasm-input/package.json')['version'] == wanted['upstream']['rhwp']['version'], 33)
    require(wasm['artifacts']['rhwp_bg.wasm'] == admitted['wasmSha256']
            and wasm['artifacts']['rhwp.js'] == admitted['jsSha256'], 33)
    expected = expected_renderers(harness_source=source, run_id=run_id, attempt=attempt,
        current_editor_sha256=current['sha256'], current_editor_bytes=current['bytes'],
        current_wasm_sha256=admitted['wasmSha256'], current_js_sha256=admitted['jsSha256'])
    fixtures = []
    for code, _, path in CASES:
        fp = fingerprint_file(workspace / path, 20 * 1024 * 1024)
        fixtures.append({'caseCode': code, 'sha256': fp['sha256'], 'bytes': fp['bytes']})
    return expected, validate_fixtures(fixtures)


def verify(workspace, source, run_id, attempt, *, font_reader=sampled_fonts):
    workspace = Path(workspace).absolute()
    expected, fixtures = independent_expected(workspace, source, run_id, attempt)
    folder = workspace / 'paired-print-evidence'
    metadata_before = fingerprint_file(folder / 'comparison.numeric.json', 128 * 1024)
    metadata = read_json(folder / 'comparison.numeric.json')
    require(fingerprint_file(folder / 'comparison.numeric.json', 128 * 1024) == metadata_before, 26)
    shape(metadata, ('schemaVersion', 'kind', 'comparison', 'requestedProfileScope',
        'requestedProfiles', 'actualSelectedProfileKnown', 'actualSelectedFontIdentityKnown',
        'actualLoadedWasmIdentityKnown', 'capturedCohortOnly', 'qualification', 'files'))
    require(type(metadata['schemaVersion']) is int and metadata['schemaVersion'] == 1
            and metadata['kind'] == 'paired-print-allowlist'
            and metadata['requestedProfileScope'] == 'requested-owned-profile', 26)
    for key in ('actualSelectedProfileKnown', 'actualSelectedFontIdentityKnown',
                'actualLoadedWasmIdentityKnown', 'qualification'):
        require(metadata[key] is False, 26)
    require(metadata['capturedCohortOnly'] is True, 26)
    report = validate_report(metadata['comparison'])
    _exact({key: report[key] for key in expected}, expected)
    _exact(report['fixtures'], fixtures)
    validate_profiles(metadata['requestedProfiles'])
    _exact(validate_fonts(font_reader()), report['fontEnvironment'])
    names = [f'role-{role}-case-{code}.{suffix}' for role in (1, 2)
             for code, _, _ in CASES for suffix in ('pdf', 'png')]
    require(type(metadata['files']) is list and len(metadata['files']) == 8, 26)
    require({p.name for p in folder.iterdir()} == {*names, 'comparison.numeric.json'}, 26)
    used = fingerprint_file(folder / 'comparison.numeric.json', 128 * 1024)['bytes']
    inspections = workspace / 'paired-print-verifier-private'
    require(not inspections.exists() and not inspections.is_symlink(), 26)
    inspections.mkdir()
    for index, row in enumerate(metadata['files']):
        shape(row, ('name', 'bytes', 'sha256'))
        require(row['name'] == names[index], 26)
        integer(row['bytes'], 1, FILE_CAP)
        digest(row['sha256'])
        path = folder / row['name']
        data, _ = read_regular(path, FILE_CAP)
        used += len(data)
        require(used <= TOTAL_CAP and len(data) == row['bytes']
                and hashlib.sha256(data).hexdigest() == row['sha256'], 26)
        observation = report['observations'][index // 2]
        suffix = 'pdf' if index % 2 == 0 else 'png'
        require(observation[suffix + 'Bytes'] == len(data)
                and observation[suffix + 'Sha256'] == row['sha256'], 26)
        if suffix == 'png':
            require(fingerprint_png(data) == observation['raster'], 26)
            continue
        case = CASES[(index // 2) % 2][1]
        target = inspections / f'role-{observation["roleCode"]}-case-{observation["caseCode"]}'
        passed = True
        try:
            result = inspect_print_pdf(path, {'pages': [{'size_pt': [595.28, 841.86]}]}, target, case)
            require(len(result['checks']) == 1 and result['sha256'] == row['sha256'], 26)
            actual = {key: result['checks'][0][key] for key in observation['raster']}
        except ValueError as error:
            if not is_ink_mismatch(error):
                raise
            passed = False
            actual = read_json(target / 'page-1-mismatch.json')['actual']
        require(passed is observation['originalOraclePassed'] and actual == observation['raster'], 26)
        after = fingerprint_file(path, FILE_CAP)
        require(after['sha256'] == row['sha256'] and after['bytes'] == row['bytes'], 26)
    # Stable actual material is checked again after replay. No report selects an
    # expected source, runtime, run, attempt, fixture or WASM identity.
    _exact(independent_expected(workspace, source, run_id, attempt), (expected, fixtures))
    _exact(validate_fonts(font_reader()), report['fontEnvironment'])
    require(fingerprint_file(folder / 'comparison.numeric.json', 128 * 1024) == metadata_before, 26)
    return {'schemaVersion': 1, 'kind': 'paired-print-upload-admission', 'admitted': True,
            'files': 9, 'bytes': used, 'observations': 4,
            'sourceQualified': False, 'acceptanceEligible': False, 'qualification': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--expected-run', type=int, required=True)
    parser.add_argument('--expected-attempt', type=int, required=True)
    args = parser.parse_args()
    try:
        result = verify(ROOT, args.expected_source, args.expected_run, args.expected_attempt)
    except Exception as error:
        import json
        try: result = project_failure(error)
        except BaseException: result = _empty_failure()
        result['admitted'] = False
        try: print(json.dumps(result, sort_keys=True))
        except BaseException: pass
        return 1
    import json
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
