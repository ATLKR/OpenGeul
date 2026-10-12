"""Probe native preinstalled Python with real stdlib-only imports and tests."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'e2e'), str(ROOT/'ci'), str(ROOT/'tests')]
OUTPUT = ROOT/'native-python-proof'
MODULES = ('buildkit','releasekit','windows_components','prepare_upstream','prepare_hwpx',
           'prepare_native_tests','font_test_contract','wasm_artifacts','build_progress')
TEST_MODULES = ('test_buildkit','test_windows_components','test_native_architecture',
                'test_prepare_native_tests','test_cross_platform_fingerprint')


def observe_owned_fixture():
    from test_windows_components import WindowsComponentsTests
    case = WindowsComponentsTests('test_caps_are_checked_at_capture_and_join')
    case.setUp()
    try:
        source = case.source()
        path = source/'third_party/rhwp/rhwp-studio/src/engine/input-handler-text.ts'
        raw = path.read_bytes()
        normalized = path.read_text(encoding='utf-8').encode('utf-8')
        ledger = json.loads((source/'.opengeul-overlay.json').read_bytes())['compositionFix']
        return {'scope':'owned synthetic test fixture only; no product document',
                'containsCrLf':b'\r\n' in raw, 'rawSha256':hashlib.sha256(raw).hexdigest(),
                'normalizedTextSha256':hashlib.sha256(normalized).hexdigest(),
                'ledgerAfterSha256':ledger['afterSha256'],
                'rawEqualsNormalized':raw == normalized,
                'ledgerMatchesNormalizedText':ledger['afterSha256'] == hashlib.sha256(normalized).hexdigest()}
    finally:
        case.doCleanups()


def main():
    if OUTPUT.exists():
        raise ValueError('existing-proof')
    OUTPUT.mkdir()
    if sys.version_info[:2] != (3,12) or sys.flags.utf8_mode != 1:
        raise ValueError('Python-3.12-and-production-UTF8-required')
    from native_architecture import WindowsProbe, verify_host
    from releasekit import pe_machine
    with Path(sys.executable).open('rb') as stream:
        executable_machine = pe_machine(stream.read(1024*1024), 'arm64')
    process = WindowsProbe().inspect(os.getpid())
    host = verify_host('arm64')
    if process['processMachine'] != 0 or process['nativeMachine'] != 0xAA64 or executable_machine != 0xAA64:
        raise ValueError('native-ARM-interpreter-required')
    imports = {}
    for name in MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        imports[name] = {'source':path.relative_to(ROOT).as_posix(),
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    expected = 'e16fcaf8c8b0eee13fe0d6f6a60248506fc1fc128bfa2f7bd0220beb05661726'
    if imports['build_progress']['sha256'] != expected:
        raise ValueError('original-resource-policy-changed')
    fixture_observation = observe_owned_fixture()
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    proof = {
        'scope':'native Python cache, stdlib imports and unit compatibility only',
        'repository':os.environ['GITHUB_REPOSITORY'], 'head':os.environ['GITHUB_SHA'],
        'runId':os.environ['GITHUB_RUN_ID'], 'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
        'pythonVersion':list(sys.version_info[:3]), 'executable':sys.executable,
        'utf8Mode':sys.flags.utf8_mode,
        'processMachine':process['processMachine'], 'nativeOsMachine':process['nativeMachine'],
        'executablePeMachine':executable_machine, 'nativeHostVerified':host,
        'imports':imports, 'testModules':list(TEST_MODULES), 'testsRun':result.testsRun,
        'ownedSyntheticCompositionFixtureObservation':fixture_observation,
        'testFailures':len(result.failures), 'testErrors':len(result.errors),
        'testSkipped':len(result.skipped),
        'testsSucceeded':result.wasSuccessful(), 'testSeconds':time.monotonic()-started,
        'productCompiles':0, 'wackRuns':0, 'installedPackages':0, 'storeApiCalls':0,
        'sourceQualified':False, 'wackQualified':False, 'storeQualified':False,
    }
    raw = json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n'
    if len(raw.encode('utf-8')) > 16*1024:
        raise ValueError('proof-too-large')
    (OUTPUT/'native-python-stdlib-compatibility.json').write_text(raw, encoding='utf-8')
    if not result.wasSuccessful() or result.skipped:
        raise SystemExit(1)


if __name__=='__main__':main()
