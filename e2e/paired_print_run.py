"""Explicit opt-in entry point; the ordinary eight-case print run is unchanged.

Run only in the existing owned Windows virtual-print job, after its normal
same-run package/WASM selection and once-only synthetic input generation.
No workflow, release, Store or source-qualification decision is made here.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys

from paired_print_contract import (Rejected, digest, expected_renderers,
                                   integer, require, run_comparison)
from paired_print_diagnostic import (LEGACY_HWP, LEGACY_PROVENANCE_SHA,
                                    CURRENT_WASM_GENERATOR, admit_current, legacy_assets)
from paired_print_windows import WindowsPort, fingerprint_file, read_json
from paired_print_collect import collect

_E2E = Path(__file__).absolute().parent
_SOURCE_FUNCTIONS = {
    str(_E2E / 'paired_print_run.py'): (1, {'run': 1, 'acquire_legacy': 2, 'bind_prepared': 3, 'bind_fixtures': 4, 'execute_pair': 5, 'main': 6}),
    str(_E2E / 'paired_print_windows.py'): (2, {'sampled_fonts': 10, '_safe': 11, 'read_regular': 12, '_parents': 13, 'fingerprint_file': 14, '__init__': 15, 'print_case': 16, 'validate_runtime': 17, 'is_ink_mismatch': 18, 'read_single_raster': 19, 'fingerprint_png': 20, 'requested_profile': 21, 'read_json': 22}),
    str(_E2E / 'paired_print_diagnostic.py'): (3, {'admit_current': 30, 'legacy_assets': 31, '__init__': 32, '_creation': 33, '_state': 34, '_census': 35, '__exit__': 36, 'wait_retired': 37, 'close': 38, 'invoke_print': 39, 'remember_primary': 40}),
    str(_E2E / 'paired_print_contract.py'): (4, {'require': 50, 'integer': 51, 'digest': 52, 'shape': 53, 'validate_expected': 54, 'run_comparison': 55, 'validate_observation': 56, 'validate_fonts': 57, 'validate_raster': 58}),
    str(_E2E / 'paired_print_collect.py'): (5, {'collect': 60, 'validate_report': 61, 'validate_profiles': 62, '_exact': 63}),
    str(_E2E / 'virtual_print.py'): (6, {'print_document': 70, 'system_dialog': 71, 'configure_media': 72, 'save_print_output': 73, 'stop_session': 74, 'wait': 75, 'print_output_wait': 76, 'capture_failure': 77, 'remember_operation': 78}),
    str(_E2E.parent / 'suite/prepare.py'): (7, {'check_asset': 80, 'download_locked': 81, 'extract_hwp_zip': 82}),
    str(_E2E / 'prepare_payload.py'): (8, {'prepare': 90, 'verify_checksums': 91, 'inventory': 92}),
    str(_E2E.parent / 'ci/paired_print_evidence.py'): (9, {'verify': 100, 'independent_expected': 101, 'check_legacy': 102}),
}


def _empty_failure():
    return {'schemaVersion': 1, 'kind': 'paired-print-failure-numeric', 'completed': False,
        'qualification': False, 'errorCode': 0, 'exceptionCode': 0, 'stageCode': 0,
        'knownRole': 0, 'fontCode': 0, 'fileSizeKnown': False, 'fileSize': 0,
        'linkCountKnown': False, 'linkCount': 0, 'frames': [], 'unknownFrames': 0, 'truncated': False}


def project_failure(error):
    """Existing traceback + explicitly stamped integers; never locals/args/queries."""
    result = _empty_failure()
    if not isinstance(error, BaseException):
        return result
    fields = BaseException.__getattribute__(error, '__dict__')
    code = fields.get('code')
    if type(code) is int and 1 <= code <= 33: result['errorCode'] = code
    result['exceptionCode'] = {Rejected: 1, ValueError: 2, AssertionError: 3, OSError: 4,
        TimeoutError: 5, FileNotFoundError: 6, PermissionError: 7, ModuleNotFoundError: 8,
        ImportError: 9, TypeError: 10, RuntimeError: 11}.get(type(error), 0)
    for field, target in (('pairedRole', 'knownRole'), ('pairedFontCode', 'fontCode')):
        value = fields.get(field)
        if type(value) is int and 1 <= value <= 2: result[target] = value
    values = fields.get('pairedFileStats')
    if type(values) is tuple and len(values) == 2:
        for value, target, cap in ((values[0], 'fileSize', 512 * 1024 * 1024), (values[1], 'linkCount', 65535)):
            if type(value) is int and 0 <= value <= cap:
                result[target], result[target + 'Known'] = value, True
    frame = BaseException.__getattribute__(error, '__traceback__')
    seen, functions = 0, set()
    while frame is not None and seen < 64:
        source = frame.tb_frame.f_code
        entry = _SOURCE_FUNCTIONS.get(source.co_filename)
        function = entry[1].get(source.co_name) if entry is not None else None
        if function is not None and type(frame.tb_lineno) is int and 1 <= frame.tb_lineno <= 20000:
            functions.add(function)
            if len(result['frames']) < 12:
                result['frames'].append({'fileCode': entry[0], 'functionCode': function, 'line': frame.tb_lineno})
            else: result['truncated'] = True
        else: result['unknownFrames'] += 1
        frame, seen = frame.tb_next, seen + 1
    result['truncated'] = result['truncated'] or frame is not None
    for stage, ids in ((6, {10}), (2, {2, 31, 80, 81, 82, 102}), (3, {90, 91, 92}),
                       (4, {3, 30, 101}), (5, {4}), (8, {60, 61, 62, 63, 100}),
                       (7, {16, 39, 55, 70}), (1, {1})):
        if functions & ids:
            result['stageCode'] = stage
            break
    return result


def acquire_legacy(canonical_hwp, cache, runtime, *, acquire=False, inputs=None):
    """Authentic existing Suite transport only; missing input refuses by default."""
    assets = legacy_assets(canonical_hwp)
    cache, runtime = Path(cache), Path(runtime)
    require(type(acquire) is bool and not runtime.exists() and not runtime.is_symlink(), 30)
    if inputs is None:
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / 'suite'))
        import prepare as inputs
    archive, provenance = cache / 'legacy-portable.zip', cache / 'legacy-provenance.json'
    for key, path in (('portable', archive), ('provenance', provenance)):
        if acquire:
            require(inputs.download_locked(assets[key], path) == path, 30)
        inputs.check_asset(assets[key], path)
    inputs.extract_hwp_zip(archive, runtime)
    # Catch mutation of the locked transport while it was being extracted.
    inputs.check_asset(assets['portable'], archive)
    require((runtime / 'OpenGeul.exe').is_file(), 30)
    return runtime / 'OpenGeul.exe'


def bind_fixtures(cases):
    from print_results import REQUIRED_CASES
    require(type(cases) is list and len(cases) == 8
            and all(type(c) is dict for c in cases), 31)
    require([c.get('name') for c in cases] == list(REQUIRED_CASES), 31)
    selected, pins = {}, []
    for code, name in ((1, 'table--300'), (6, 'basic-hwpx')):
        case = cases[code - 1]
        require(case['name'] == name and not case.get('cancel') and not case.get('range')
                and type(case.get('pages')) is list and len(case['pages']) == 1, 31)
        require(Path(case['path']).name == ('print-table--300.hwpx' if code == 1 else 'basic.hwpx'), 31)
        value = fingerprint_file(case['path'], 20 * 1024 * 1024)
        selected[code] = case
        pins.append({'caseCode': code, 'sha256': value['sha256'], 'bytes': value['bytes']})
    return selected, pins


def execute_pair(expected, fixtures, port, work, output, *, compare=run_comparison, collector=collect):
    report = compare(expected, fixtures, port)
    exported = collector(work, output, report, port.profile_observations)
    # Export succeeds even when the unchanged reviewed oracle failed. Preserve
    # its original object and failure status after the bounded evidence exists.
    port.raise_original_oracle()
    return exported


def bind_prepared(legacy, current, package, prepared, provenance_sha, *,
                  expected_source, run_id, attempt, expected_wasm_source):
    """Admit actual runtimes against external same-run pins and authentic 1.1.4."""
    from paired_print_contract import LEGACY_EDITOR, LEGACY_SOURCE, LEGACY_WASM, LEGACY_JS
    old = fingerprint_file(legacy)
    require((old['sha256'], old['bytes']) == (LEGACY_EDITOR, 36402688), 32)
    # The complete historical provenance was pinned before extraction; no value
    # from it selects a source, artifact or expected WASM fingerprint.
    current_fp = fingerprint_file(current)
    digest(provenance_sha)
    provenance_path = Path(package) / 'provenance.json'
    require(fingerprint_file(provenance_path, 512 * 1024)['sha256'] == provenance_sha, 32)
    value = read_json(provenance_path, 512 * 1024)
    require(type(prepared) is dict and set(prepared) == {
        'msix', 'portable', 'architecture', 'editorSha256', 'verifiedRuntimeFiles', 'runtimeManifestSha256'}, 32)
    require(prepared['architecture'] == 'x64' and prepared['editorSha256'] == current_fp['sha256'], 32)
    integer(prepared['verifiedRuntimeFiles'], 1, 10000)
    digest(prepared['runtimeManifestSha256'])
    require(type(prepared['msix']) is str and Path(prepared['msix']).name == prepared['msix']
            and value.get('package') == prepared['msix'], 32)
    require(fingerprint_file(Path(package) / prepared['msix'], 128 * 1024 * 1024)['sha256']
            == value.get('sha256'), 32)
    admitted = admit_current(value, expected_source=expected_source, run_id=run_id, attempt=attempt,
        expected_upstream=expected_wasm_source['upstream'], expected_wasm_source=expected_wasm_source,
        runtime_sha256=current_fp['sha256'], runtime_bytes=current_fp['bytes'])
    return expected_renderers(harness_source=expected_source, run_id=run_id, attempt=attempt,
        current_editor_sha256=admitted['editorSha256'], current_editor_bytes=admitted['editorBytes'],
        current_wasm_sha256=admitted['wasmSha256'], current_js_sha256=admitted['jsSha256'])


def run(args):
    require(os.name == 'nt' and args.run_paired_print is True, 33)
    digest(args.harness_source, 40)
    integer(args.run_id, 1)
    integer(args.run_attempt, 1)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'scripts'))
    from wasm_artifacts import expected, validate, FILES
    from virtual_print import build_cases
    from print_queue import require_host
    from prepare_payload import prepare
    require_host()
    wasm_source = expected()
    # Source declarations plus actual six same-job WASM input bytes. These are
    # build provenance, not proof of the WebView's effective module selection.
    validate(args.wasm)
    wasm = read_json(Path(args.wasm) / 'OPEN_GEUL_WASM.json')
    from paired_print_contract import shape
    shape(wasm, (*wasm_source, 'artifacts', 'generator'))
    require(wasm['generator'] == CURRENT_WASM_GENERATOR, 33)
    require(all(wasm.get(k) == v for k, v in wasm_source.items()), 33)
    require(type(wasm.get('artifacts')) is dict and set(wasm['artifacts']) == set(FILES), 33)
    used = 0
    for name in FILES:
        fp = fingerprint_file(Path(args.wasm) / name, 32 * 1024 * 1024)
        used += fp['bytes']
        require(used <= 32 * 1024 * 1024 and fp['sha256'] == wasm['artifacts'][name], 33)
    lock = read_json(root / 'suite/config/runtime.lock.json')
    legacy = acquire_legacy(lock['hwp'], args.legacy_cache, args.legacy_runtime,
                            acquire=args.acquire_legacy)
    # Existing prepare() validates MSIX structure plus every portable/MSIX byte.
    # Its informational stdout is outside this diagnostic's numeric protocol.
    with open(os.devnull, 'w') as sink, redirect_stdout(sink):
        prepared = prepare(Path(args.package), Path(args.current_runtime), 'x64')
    current = Path(args.current_runtime) / 'OpenGeul.exe'
    expected_pair = bind_prepared(legacy, current, args.package, prepared,
        args.current_provenance_sha256, expected_source=args.harness_source,
        run_id=args.run_id, attempt=args.run_attempt, expected_wasm_source=wasm_source)
    require(expected_pair['renderers'][1]['wasmSha256'] == wasm['artifacts']['rhwp_bg.wasm']
            and expected_pair['renderers'][1]['jsSha256'] == wasm['artifacts']['rhwp.js'], 33)
    # One generation by the original workflow, one hash binding, both roles use
    # these exact input paths and bytes. No role generates its own documents.
    cases, fixtures = bind_fixtures(build_cases(Path(args.inputs), Path(args.fixtures)))
    port = WindowsPort({1: legacy, 2: current}, cases, args.work)
    try:
        return execute_pair(expected_pair, fixtures, port, args.work, args.output)
    except BaseException as error:
        try:
            if 'pairedRole' not in BaseException.__getattribute__(error, '__dict__') and port.attempts:
                error.pairedRole = port.attempts[-1][0]
        except BaseException:pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-paired-print', action='store_true')
    parser.add_argument('--acquire-legacy', action='store_true')
    for name in ('legacy-cache', 'legacy-runtime', 'current-runtime', 'package', 'wasm',
                 'inputs', 'fixtures', 'work', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--current-provenance-sha256', required=True)
    parser.add_argument('--harness-source', required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--run-attempt', type=int, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:
        # No exception arguments, source path, URL, request, document or console.
        try: result = project_failure(error)
        except BaseException: result = _empty_failure()
        try: print(json.dumps(result, sort_keys=True))
        except BaseException: pass
        return 1
    print('{"completed":true,"qualification":false,"errorCode":0}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
