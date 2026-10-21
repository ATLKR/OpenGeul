"""Native-boundary lifecycle fakes; these do not qualify an actual Windows run."""
import ctypes
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('job_retirement_control', ROOT / 'e2e/native31_desktop_control.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class NativeLifecycle:
    def __init__(self, active=(2, 1, 0), *, wait=True, exit_code=0,
                 wait_seconds=0, query_seconds=0, close_failure=None, terminate=False):
        self.now = 100.0
        self.active = iter(active)
        self.last_active = 1
        self.wait_result, self.exit_result = wait, exit_code
        self.wait_seconds, self.query_seconds = wait_seconds, query_seconds
        self.close_failure, self.terminate_failure = close_failure, terminate
        self.calls, self.query_sizes = [], []
        self.kernel = SimpleNamespace()
        actions = {
            'CreateJobObjectW': lambda *_: 99,
            'SetInformationJobObject': lambda *_: 1,
            'AssignProcessToJobObject': lambda *_: 1,
            'QueryInformationJobObject': self.query,
            'TerminateJobObject': lambda *_: 0 if self.terminate_failure else 1,
            'TerminateProcess': lambda *_: 1,
            'ResumeThread': lambda *_: 1,
            'WaitForSingleObject': self.wait,
            'GetExitCodeProcess': self.exit_code,
            'CloseHandle': self.close,
        }
        class Function:
            def __init__(self, name, action): self.name, self.action = name, action
            def __call__(inner, *args):
                self.calls.append((inner.name, args))
                return inner.action(*args)
        for name, action in actions.items():
            setattr(self.kernel, name, Function(name, action))

    def query(self, job, kind, data, size, returned):
        self.query_sizes.append(size)
        self.now += self.query_seconds
        value = next(self.active, self.last_active)
        if value == 'failure': return 0
        if value == 'exception': raise OSError('accounting transport failed')
        self.last_active = value
        for key, val in dict(userTime=111, kernelTime=222, periodUserTime=33,
                             periodKernelTime=44, faults=5, total=11,
                             active=value, terminated=7).items():
            setattr(data._obj, key, val)
        return 1

    def wait(self, *_):
        self.now += self.wait_seconds
        return 0 if self.wait_result else 258

    def exit_code(self, _, output):
        output._obj.value = self.exit_result
        return 1

    def close(self, handle):
        if self.close_failure == ('raise', handle): raise OSError('handle release failed')
        return int(handle != self.close_failure)

    def sleep(self, seconds): self.now += seconds
    def names(self): return [name for name, _ in self.calls]

    def run(self):
        budget = m.Budget(120, clock=lambda: self.now)
        image = dict(imageBytes=1, imageSha256='a' * 64, peMachine=0xAA64)
        identity = dict(processId=45, createdFileTime=133999999999999999,
                        processMachine=0, nativeMachine=0xAA64, sessionId=1,
                        imagePath=m.sys.executable, exitCode=259)
        probe = SimpleNamespace(kernel=self.kernel, process_identity=lambda *_: identity)
        def create(*_):
            self.calls.append(('CreateProcess', ()))
            return 77, 78, 45, 46
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict('sys.modules', {'_winapi': SimpleNamespace(CreateProcess=create)}), \
             patch.object(m.subprocess, 'STARTUPINFO', create=True, return_value=object()), \
             patch.object(m, 'image_receipt', return_value=image), \
             patch.object(m.time, 'sleep', side_effect=self.sleep), \
             patch.object(m.ctypes, 'get_last_error', create=True, return_value=5):
            out = m.Evidence.create(Path(temp) / 'capture', Path(temp))
            owner = m.OwnedObserver(probe, {}, [m.sys.executable, 'observer.py'], budget,
                                    {'sessionId': 1, 'executable': image, 'sourceFiles': {}})
            result = m.run_owned(owner, budget, out)
            retained = json.loads((out.path / '90-owned-lifecycle.json').read_text())
        return result, retained, budget


class JobRetirementContracts(unittest.TestCase):
    def assert_closed_once(self, fake):
        self.assertEqual([args[0] for name, args in fake.calls if name == 'CloseHandle'], [78, 77, 99])
        for name in ('CreateProcess', 'AssignProcessToJobObject', 'ResumeThread', 'WaitForSingleObject'):
            self.assertEqual(fake.names().count(name), 1)
        self.assertNotIn('TerminateProcess', fake.names())

    def test_signaled_root_waits_read_only_until_owned_job_naturally_retires(self):
        fake = NativeLifecycle()
        result, retained, budget = fake.run()
        self.assertTrue(result['success'], result)
        self.assertTrue(result['naturalExit'])
        self.assertTrue(result['jobRetiredNaturally'])
        self.assertFalse(result['forced'])
        self.assertEqual(retained, result)
        self.assertEqual([row['activeProcesses'] for row in result['jobRetirement']['samples']], [2, 1, 0])
        self.assertEqual(result['jobRetirement']['sampleCount'], 3)
        self.assertEqual(budget.deadline, 220.0)
        self.assertNotIn('TerminateJobObject', fake.names())
        self.assert_closed_once(fake)

    def test_persistent_nonzero_reaches_original_reserve_and_forces_owned_cleanup(self):
        fake = NativeLifecycle(active=(1,))
        result, _, budget = fake.run()
        self.assertTrue(result['timedOut'], result)
        self.assertFalse(result['success'])
        self.assertFalse(result['jobRetiredNaturally'])
        self.assertTrue(result['forced'])
        self.assertEqual(fake.names().count('TerminateJobObject'), 1)
        self.assertLessEqual(fake.now, budget.deadline - 3)
        self.assertEqual(result['jobRetirement']['samples'][-1]['activeProcesses'], 1)
        self.assert_closed_once(fake)

    def test_query_failure_is_retained_and_never_retried_or_qualified(self):
        fake = NativeLifecycle(active=('failure',))
        result, _, _ = fake.run()
        self.assertEqual(fake.names().count('QueryInformationJobObject'), 1)
        self.assertFalse(result['success'])
        self.assertTrue(result['forced'])
        row = result['jobRetirement']['samples'][0]
        self.assertFalse(row['querySucceeded'])
        self.assertEqual(row['queryResult'], 0)
        self.assertEqual(row['lastError'], 5)
        self.assertIsNone(row['activeProcesses'])
        self.assert_closed_once(fake)

    def test_expired_before_first_retirement_query_still_terminates_and_closes(self):
        fake = NativeLifecycle(active=(0,), wait_seconds=117)
        result, _, _ = fake.run()
        self.assertFalse(result['success'], result)
        self.assertTrue(result['timedOut'])
        self.assertTrue(result['forced'])
        self.assertEqual(fake.names().count('QueryInformationJobObject'), 0)
        self.assertEqual(result['jobRetirement']['sampleCount'], 0)
        self.assert_closed_once(fake)

    def test_raised_query_failure_is_preserved_without_another_native_query(self):
        fake = NativeLifecycle(active=('exception',))
        result, retained, _ = fake.run()
        self.assertFalse(result['success'])
        self.assertTrue(result['forced'])
        self.assertEqual(fake.names().count('QueryInformationJobObject'), 1)
        row = result['jobRetirement']['samples'][0]
        self.assertIsNone(row['querySucceeded'])
        self.assertEqual(row['failure'], result['failure'])
        self.assertEqual(row['failure']['message'], 'accounting transport failed')
        self.assertEqual(retained, result)
        self.assert_closed_once(fake)

    def test_zero_returned_after_reserve_is_not_accepted(self):
        fake = NativeLifecycle(active=(0,), query_seconds=117)
        result, _, _ = fake.run()
        self.assertFalse(result['success'], result)
        self.assertTrue(result['timedOut'])
        self.assertFalse(result['jobRetiredNaturally'])
        self.assertTrue(result['forced'])
        self.assertEqual(result['jobRetirement']['samples'][0]['activeProcesses'], 0)
        self.assert_closed_once(fake)

    def test_nonzero_root_exit_remains_failure_after_natural_job_retirement(self):
        fake = NativeLifecycle(active=(1, 0), exit_code=7)
        result, _, _ = fake.run()
        self.assertIn('Observer returned diagnostic failure', result['failure']['message'])
        self.assertFalse(result['success'])
        self.assertTrue(result['jobRetiredNaturally'])
        self.assertFalse(result['forced'])
        self.assertNotIn('TerminateJobObject', fake.names())
        self.assert_closed_once(fake)

    def test_raw_accounting_uses_fixed_windows_abi_and_bounded_first_last_rows(self):
        fake = NativeLifecycle(active=tuple([1] * 70 + [0]))
        result, _, _ = fake.run()
        self.assertTrue(result['success'], result)
        receipt = result['jobRetirement']
        self.assertEqual(receipt['sampleCount'], 71)
        self.assertEqual(len(receipt['samples']), 64)
        self.assertEqual(receipt['samplesDropped'], 7)
        self.assertEqual(set(fake.query_sizes), {48})
        first, last = receipt['samples'][0], receipt['samples'][-1]
        self.assertEqual(first['totalUserTime100ns'], 111)
        self.assertEqual(first['totalKernelTime100ns'], 222)
        self.assertEqual(first['totalProcesses'], 11)
        self.assertEqual(first['totalTerminatedProcesses'], 7)
        self.assertEqual(last['activeProcesses'], 0)
        self.assertLess(first['finishedMonotonic'], last['finishedMonotonic'])
        self.assertTrue(all(row['remainingSeconds'] > 3 for row in receipt['samples']))
        self.assertLess(len(json.dumps(result)), 64 * 1024)
        self.assert_closed_once(fake)

    def test_root_timeout_preserves_forced_path_and_raw_cleanup_outcomes(self):
        fake = NativeLifecycle(wait=False)
        result, _, _ = fake.run()
        self.assertTrue(result['forced'])
        self.assertTrue(result['timedOut'])
        self.assertFalse(result['naturalExit'])
        self.assertIn('jobRetiredNaturally', result)
        self.assertFalse(result['jobRetiredNaturally'])
        self.assertEqual(result['jobRetirement']['sampleCount'], 0)
        self.assertEqual([r['operation'] for r in result['ownedCleanupOutcomes']],
                         ['TerminateJobObject', 'CloseHandle', 'CloseHandle', 'CloseHandle'])
        self.assertTrue(all(r['succeeded'] for r in result['ownedCleanupOutcomes']))
        self.assert_closed_once(fake)

    def test_first_handle_close_failure_still_releases_remaining_handles(self):
        fake = NativeLifecycle(active=(0,), close_failure=78)
        result, _, _ = fake.run()
        self.assertFalse(result['success'])
        self.assertIn('cleanupFailure', result)
        self.assertIn('ownedCleanupOutcomes', result)
        outcomes = result['ownedCleanupOutcomes']
        self.assertEqual([r['succeeded'] for r in outcomes], [False, True, True])
        self.assertEqual(outcomes[0]['lastError'], 5)
        self.assert_closed_once(fake)

    def test_termination_failure_is_retained_and_does_not_skip_handle_closes(self):
        fake = NativeLifecycle(wait=False, terminate=True)
        result, _, _ = fake.run()
        self.assertFalse(result['success'])
        self.assertTrue(result['forced'])
        self.assertIn('ownedCleanupOutcomes', result)
        self.assertFalse(result['ownedCleanupOutcomes'][0]['succeeded'])
        self.assertEqual(result['ownedCleanupOutcomes'][0]['lastError'], 5)
        self.assertIn('cleanupFailure', result)
        self.assert_closed_once(fake)

    def test_raised_close_failure_is_retained_and_other_owned_handles_are_released(self):
        fake = NativeLifecycle(active=(0,), close_failure=('raise', 78))
        result, retained, _ = fake.run()
        self.assertFalse(result['success'])
        self.assertIn('cleanupFailure', result)
        outcomes = result['ownedCleanupOutcomes']
        self.assertEqual([row['handle'] for row in outcomes], [78, 77, 99])
        self.assertEqual(outcomes[0]['failure']['message'], 'handle release failed')
        self.assertIsNone(outcomes[0]['nativeResult'])
        self.assertEqual([row['succeeded'] for row in outcomes], [False, True, True])
        self.assertEqual(retained, result)
        self.assert_closed_once(fake)


if __name__ == '__main__': unittest.main()
