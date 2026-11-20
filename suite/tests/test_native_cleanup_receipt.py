"""Pure replay of actual worker cleanup receipts, captured through its fake Win32 API.

fixtures/owned-office-shutdown.json uses UnoBackend.cleanup, JobProcessWitnesses,
and ProcessDiagnosticsApi.job_pids from the product producer. No Windows run is
claimed: its timed fake API supplies the launcher/child and raw class-3 census.
"""
import copy
import json
from pathlib import Path
import unittest

from suite.e2e.native_cleanup_receipt import load_cleanup_receipt, validate_cleanup_receipt


FIXTURES = Path(__file__).parent / 'fixtures/owned-office-shutdown.json'
EXPECTED = 'C:/Office/program/soffice.bin'


def receipt(name='graceful'):
    return json.loads(FIXTURES.read_text(encoding='utf-8'))[name]


class NativeCleanupReceiptTests(unittest.TestCase):
    def validate(self, record):
        return validate_cleanup_receipt(record, expected_engine_image=EXPECTED, launcher_pid=10)

    def test_real_producer_graceful_receipt_and_windows_image_spelling(self):
        proof = receipt()
        before = copy.deepcopy(proof)
        self.assertIs(self.validate(proof), proof)
        self.assertEqual(before, proof, 'Replay must preserve the raw failure/success evidence')
        proof['expectedEngineImage'] = 'c:\\OFFICE\\program\\SOFFICE.BIN'
        self.validate(proof)

    def test_actual_forced_nonzero_and_unproved_producer_outputs_fail(self):
        for name in ('forced', 'nonzero', 'unproved'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(receipt(name))

    def test_summary_flags_do_not_override_raw_forced_nonzero_or_unproved_output(self):
        for name in ('forced', 'nonzero', 'unproved'):
            proof = receipt(name)
            proof.update(success=True, gracefulQualified=True, forcedTermination=False,
                         jobEmptyVerified=True, deathProved=True, resourcesReleased=True,
                         profileRetained=False, errors=[])
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(proof)

    def test_required_flags_and_resources_cannot_be_omitted_or_coerced(self):
        for key in ('success', 'gracefulQualified', 'jobEmptyVerified', 'deathProved',
                    'resourcesReleased', 'forcedTermination', 'profileRetained',
                    'terminateRequested', 'terminateResult', 'errors'):
            for value in (None, 0, 1, 'true'):
                proof = receipt(); proof[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.validate(proof)

    def test_identity_handle_image_and_raw_exit_observations_are_joined(self):
        mutations = [
            lambda p:p.update(expectedEngineImage='C:/foreign/program/soffice.bin'),
            lambda p:p.update(launcherPid=11), lambda p:p.update(launcherHandleValue=None),
            lambda p:p.update(launcherWaitResult=258), lambda p:p.update(launcherExitCode=False),
            lambda p:p.update(initialMembers=[]), lambda p:p.update(finalMembers=[]),
            lambda p:p['finalMembers'][0].update(creationTime=123),
            lambda p:p['finalMembers'][0].update(handleValue=999),
            lambda p:p['finalMembers'][0].update(image='C:/foreign/soffice.exe'),
            lambda p:p['finalMembers'][0].update(alive=True),
            lambda p:p['finalMembers'][0].update(waitResult=258),
            lambda p:p['finalMembers'][0].update(waitResult=False),
            lambda p:p['finalMembers'][0].update(exitCode=0xc0000005),
            lambda p:p['finalMembers'][0].update(exitCodeHex='0xc0000005'),
            lambda p:p['finalMembers'][0].update(getExitCodeProcessResult=False),
            lambda p:p['finalMembers'][0].update(error={}),
            lambda p:p['finalMembers'].append(copy.deepcopy(p['finalMembers'][0])),
            lambda p:p['initialMembers'][0].update(creationTime=True),
            lambda p:p.update(jobHandleValue=0),
        ]
        for index, mutate in enumerate(mutations):
            proof = receipt(); mutate(proof)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(proof)

    def test_new_owned_child_can_extend_retained_final_members(self):
        proof = receipt()
        extra = copy.deepcopy(proof['finalMembers'][-1])
        extra.update(pid=30, creationTime=extra['creationTime']+10, handleValue=130)
        proof['finalMembers'].append(extra)
        self.validate(proof)

    def test_engine_must_be_observed_alive_before_shutdown(self):
        proof = receipt()
        for row in proof['initialMembers']:
            row.update(alive=False, waitResult=0, exitCode=0, exitCodeHex='0x00000000')
        with self.assertRaises(ValueError):
            self.validate(proof)

    def test_complete_empty_final_raw_job_census_is_mandatory(self):
        mutations = [
            lambda p:p.update(lastJobCensus=None), lambda p:p.update(finalJobPids=[20]),
            lambda p:p['lastJobCensus'].update(jobHandleValue=100),
            lambda p:p['lastJobCensus'].update(api='EnumProcesses'),
            lambda p:p['lastJobCensus'].update(bufferBytes=1024),
            lambda p:p['lastJobCensus'].update(classification='incomplete'),
            lambda p:p['lastJobCensus'].update(error={}),
            lambda p:p['lastJobCensus'].update(calls=[]),
            lambda p:p['lastJobCensus']['calls'][-1].update(result=False),
            lambda p:p['lastJobCensus']['calls'][-1].update(assigned=1),
            lambda p:p['lastJobCensus']['calls'][-1].update(returnLength=7),
            lambda p:p['lastJobCensus']['calls'][-1].update(count=False),
            lambda p:p['lastJobCensus']['calls'][-1].update(pids=[20]),
            lambda p:p['lastJobCensus'].update(finishedAt=99.),
            lambda p:p.update(gracefulBudgetSeconds=50),
            lambda p:p.update(recoveryWaitStartedAt=1.),
            lambda p:p.update(elapsedSeconds=float('nan')),
        ]
        for index, mutate in enumerate(mutations):
            proof = receipt(); mutate(proof)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.validate(proof)

    def test_bounded_json_loader_rejects_duplicate_keys_nonfinite_and_nonobject(self):
        for raw in (b'{"success":true,"success":false}', b'{"time":NaN}',
                    b'[]', b'x'*(256*1024+1), b'\xff'):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError):
                load_cleanup_receipt(raw)
        self.assertEqual(load_cleanup_receipt(json.dumps(receipt()).encode()), receipt())


if __name__ == '__main__':
    unittest.main()
