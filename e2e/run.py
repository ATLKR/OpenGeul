"""Fail-closed UI entrypoint: exact manifest, actual helpers, JSON/JUnit and oracle checks."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from ui_contract import (
    EXPECTED_COUNTS, discovered_ids, exact_ids, helper_hashes,
    junit_bytes, manifest, validate_evidence,
)


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []; self.started = {}; self.status = {}

    def startTest(self, test):
        self.started[test.id()] = time.monotonic(); super().startTest(test)

    def addSuccess(self, test):
        self.status[test.id()] = ('passed', ''); super().addSuccess(test)

    def addFailure(self, test, err):
        self.status[test.id()] = ('failed', self._exc_info_to_string(err, test)); super().addFailure(test, err)

    def addError(self, test, err):
        self.status[test.id()] = ('error', self._exc_info_to_string(err, test)); super().addError(test, err)

    def addSkip(self, test, reason):
        self.status[test.id()] = ('skipped', reason); super().addSkip(test, reason)

    def stopTest(self, test):
        status, message = self.status.get(test.id(), ('error', 'No result recorded'))
        self.records.append({'test': test.id(), 'status': status,
            'seconds': round(time.monotonic()-self.started[test.id()], 3), 'message': message,
            'checks': getattr(test, 'supported_checks', {})})
        super().stopTest(test)


def main():
    output = Path(os.environ['E2E_OUTPUT']); output.mkdir(parents=True, exist_ok=True)
    mode = os.environ.get('E2E_MODE')
    root = Path(__file__).resolve().parents[1]
    payload = {'commit': os.environ.get('GITHUB_SHA'), 'runId': os.environ.get('GITHUB_RUN_ID'),
        'runAttempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'mode': mode,
        'browser': os.environ.get('E2E_BROWSER'), 'os': os.environ.get('RUNNER_OS'),
        'tests': [], 'expectedTests': EXPECTED_COUNTS.get(mode), 'success': False}
    try:
        cases = manifest(mode)
        before = helper_hashes(root)
        payload.update(caseIds=list(cases), helperSha256=before)
        from test_hop_followups import suite
        tests = suite()
        # Exact preflight prevents a deleted/renamed/replaced case from executing
        # a smaller suite and being normalized as a new expected count.
        exact_ids(discovered_ids(tests), mode)
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(tests)
        payload['tests'] = result.records
        payload['success'] = result.wasSuccessful() and not result.skipped and result.testsRun == EXPECTED_COUNTS[mode]
        xml = junit_bytes(result.records)
        validate_evidence(payload, xml, mode=mode, root=root, before=before)
    except Exception as error:
        payload.update(success=False, contractError=str(error))
        xml = junit_bytes(payload['tests'])
    (output/'junit.xml').write_bytes(xml)
    (output/'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    # Re-read the serialized evidence and actual helpers before returning a
    # successful mandatory step; an in-memory/hash-only receipt is insufficient.
    if payload['success']:
        try:
            validate_evidence(json.loads((output/'results.json').read_text(encoding='utf-8')),
                              (output/'junit.xml').read_bytes(), mode=mode, root=root, before=before)
        except Exception as error:
            payload.update(success=False, contractError=str(error))
            (output/'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(f"## {mode} / {payload['browser']} E2E\n"
                         f"Tests: {len(payload['tests'])}/{payload['expectedTests']}; success: {payload['success']}; "
                         f"contract: {payload.get('contractError', 'passed')}.\n")
    return 0 if payload['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
