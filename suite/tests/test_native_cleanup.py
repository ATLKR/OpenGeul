"""Owned process boundaries only; no actual Windows shutdown is claimed."""
from contextlib import redirect_stderr
import importlib
import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
native = importlib.import_module('native')
windows = importlib.import_module('native_windows')


class Job:
    """Real witness code observes a timed launcher and children through this API."""
    def __init__(self, ends=(.2, 1.4), codes=None, *, recovery=True):
        self.now = 0.
        self.ends = dict(zip((10, 20, 30), ends))
        self.starts = {pid: 0. for pid in self.ends}
        self.codes = codes or {pid: 0 for pid in self.ends}
        self.recovery = recovery
        self.calls = []
        self.closed = False
        self.profile_removed = False
        self.query_failure = False
        self.state_failure = False
        self.handle_close_failure = False

    def job_pids(self, job, *, record=None):
        self.calls.append(('census', job, self.now))
        if self.query_failure:
            raise windows.JobCensusError('census denied')
        pids = [pid for pid in self.ends if self.starts[pid] <= self.now < self.ends[pid]]
        if record is not None:
            record(dict(kind='private-job-process-census', classification='complete', jobHandleValue=job,
                        calls=[dict(result=True, assigned=len(pids), count=len(pids), pids=pids)]))
        return pids

    def open_owned(self, pid, job):
        self.calls.append(('retain', pid, job, self.now))
        assert pid in self.job_pids(job)
        return pid + 100

    def identity(self, handle):
        pid = handle - 100
        return dict(image='C:/Office/program/soffice.' + ('exe' if pid == 10 else 'bin'),
                    creationTime=134366967797539287 + pid)

    def state(self, handle):
        if self.state_failure:
            raise OSError('member state denied')
        pid = handle - 100
        alive = self.now < self.ends[pid]
        # Exit code zero while unsignaled is intentionally possible in a race.
        return dict(alive=alive, waitResult=258 if alive else 0, exitCode=self.codes[pid],
                    exitCodeHex=f'0x{self.codes[pid]:08x}', getExitCodeProcessResult=True)

    def wait_for(self, handle, milliseconds):
        self.calls.append(('wait', handle, milliseconds, self.now))
        pid = handle - 100
        self.now = min(max(self.now, self.ends[pid]), self.now + milliseconds / 1000.)
        return 0 if self.now >= self.ends[pid] else 258

    def close(self, handle):
        self.calls.append(('member-close', handle))
        if self.handle_close_failure:
            raise OSError('member handle close denied')

    def sleep(self, seconds):
        self.now += seconds

    def process(self):
        job = self
        class Process(windows.OwnedOfficeProcess):
            def __init__(self):
                self.job, self.handle, self.pid = 99, 110, 10
            def open_diagnostic_witnesses(self):
                return windows.JobProcessWitnesses(self.job, api=job)
            def poll(self):
                return job.codes[10] if job.now >= job.ends[10] else None
            def wait(self, timeout):
                if job.now < job.ends[10]:
                    raise subprocess.TimeoutExpired('owned launcher', timeout)
                return job.codes[10]
            def terminate(self):
                job.calls.append(('force', self.job, job.now))
                if job.recovery:
                    for pid in job.ends:
                        if job.now < job.ends[pid]:
                            job.ends[pid], job.codes[pid] = job.now + .1, 1
            def close(self):
                assert not job.job_pids(self.job), 'Job closed while owned child remained alive'
                job.calls.append(('job-close', self.job, job.now))
                job.closed = True
        return Process()

    def backend(self):
        backend = native.UnoBackend(Path('C:/Office'))
        backend.process = self.process()
        backend.desktop = NS(terminate=lambda: self.calls.append(('desktop-terminate', self.now)) or True)
        def remove_profile():
            assert not self.job_pids(99), 'Profile deleted while owned child remained alive'
            self.calls.append(('profile-remove', self.now))
            self.profile_removed = True
        backend.profile = NS(name='C:/private-profile', cleanup=remove_profile)
        return backend

    def run_cleanup(self, backend):
        with patch.object(native.time, 'monotonic', lambda: self.now), \
                patch.object(native.time, 'sleep', self.sleep), redirect_stderr(io.StringIO()):
            return backend.cleanup()


class NativeCleanupTests(unittest.TestCase):
    def test_delayed_launcher_and_child_exit_normally_before_profile_and_job_release(self):
        job = Job()
        backend = job.backend()
        proof = job.run_cleanup(backend)
        self.assertIsInstance(proof, dict, 'Cleanup needs an explicit owned-job proof')
        self.assertIs(proof['success'], True)
        self.assertIs(proof['forcedTermination'], False)
        self.assertIs(proof['jobEmptyVerified'], True)
        self.assertEqual(proof['finalJobPids'], [])
        self.assertEqual([row['exitCode'] for row in proof['finalMembers']], [0, 0])
        self.assertTrue(all(row['waitResult'] == 0 for row in proof['finalMembers']))
        self.assertEqual(proof['lastJobCensus']['calls'][-1]['pids'], [])
        self.assertGreaterEqual(job.now, 1.4)
        self.assertTrue(job.closed and job.profile_removed)
        self.assertFalse(any(row[0] == 'force' for row in job.calls))
        first_request = next(i for i,row in enumerate(job.calls) if row[0] == 'desktop-terminate')
        self.assertEqual({row[1] for row in job.calls[:first_request] if row[0] == 'retain'}, {10,20})

    def test_exited_launcher_does_not_hide_live_child_or_zero_exit_code_race(self):
        job = Job(ends=(0., 2.))
        proof = job.run_cleanup(job.backend())
        self.assertIsInstance(proof, dict)
        self.assertTrue(proof['success'])
        self.assertGreaterEqual(job.now, 2.)
        self.assertFalse(any(row[0] == 'force' for row in job.calls))

    def test_new_child_is_retained_and_waited_under_same_grace_deadline(self):
        job = Job(ends=(.2, 1.4, 2.8))
        job.starts[30] = .5
        proof = job.run_cleanup(job.backend())
        self.assertIsInstance(proof, dict)
        self.assertTrue(proof['success'])
        self.assertEqual({row['pid'] for row in proof['finalMembers']}, {10,20,30})
        self.assertGreaterEqual(job.now, 2.8)

    def test_hung_child_forces_only_own_job_after_grace_and_stays_failed_after_recovery(self):
        job = Job(ends=(.1, 100.))
        backend = job.backend()
        proof = job.run_cleanup(backend)
        self.assertIsInstance(proof, dict)
        self.assertFalse(proof['success'])
        self.assertTrue(proof['forcedTermination'])
        self.assertTrue(proof['jobEmptyVerified'])
        force = [row for row in job.calls if row[0] == 'force']
        self.assertEqual(len(force), 1)
        self.assertEqual(force[0][1], 99)
        self.assertGreaterEqual(force[0][2], proof['gracefulBudgetSeconds'])
        self.assertTrue(job.closed and job.profile_removed)
        # A second cleanup must preserve the original failed qualification.
        self.assertFalse(job.run_cleanup(backend)['success'])

    def test_unproved_recovery_retains_profile_job_and_all_witnesses(self):
        job = Job(ends=(.1, 100.), recovery=False)
        backend = job.backend()
        proof = job.run_cleanup(backend)
        self.assertIsInstance(proof, dict)
        self.assertFalse(proof['success'])
        self.assertFalse(proof['jobEmptyVerified'])
        self.assertFalse(job.closed or job.profile_removed)
        self.assertIsNotNone(backend.process)
        self.assertIsNotNone(backend.profile)
        self.assertFalse(any(row[0] == 'member-close' for row in job.calls))

    def test_dead_nonzero_child_is_failure_with_safe_resource_cleanup(self):
        job = Job(codes={10:0,20:0xC0000005})
        proof = job.run_cleanup(job.backend())
        self.assertIsInstance(proof, dict)
        self.assertFalse(proof['success'])
        self.assertTrue(proof['jobEmptyVerified'])
        self.assertFalse(proof['forcedTermination'])
        self.assertTrue(job.closed and job.profile_removed)
        self.assertEqual(proof['finalMembers'][-1]['exitCode'], 0xC0000005)

    def test_already_empty_job_cannot_qualify_an_unobserved_engine_exit(self):
        for ends in ((0.,0.),(.2,0.)):
            with self.subTest(ends=ends):
                job = Job(ends=ends)
                proof = job.run_cleanup(job.backend())
                self.assertFalse(proof['success'], 'An empty job cannot reconstruct the disappeared engine exit code')
                self.assertTrue(proof['jobEmptyVerified'])
                self.assertTrue(job.closed and job.profile_removed)
                self.assertIn('engine', str(proof['errors']).lower())

    def test_identity_failure_survives_secondary_close_failure_and_retains_handle(self):
        original, secondary = OSError('original identity query failure'), OSError('secondary close failure')
        blocked = [True]
        def fail_identity(handle):
            raise original
        def close(handle):
            if blocked[0]:
                raise secondary
        api = NS(job_pids=lambda job:[77], open_owned=lambda pid,job:123,
                 identity=fail_identity, close=close)
        witness = windows.JobProcessWitnesses(99, api=api)
        rows = witness.snapshot()
        self.assertIn('original identity query failure', rows[0]['error']['message'])
        self.assertIn('secondary close failure', str(rows[0]))
        self.assertEqual(witness.failed_members[77][0], 123)
        blocked[0] = False
        witness.close()
        self.assertFalse(witness.failed_members)

    def test_member_query_and_census_failures_never_authorize_profile_or_job_release(self):
        for failure in ('query_failure','state_failure'):
            with self.subTest(failure=failure):
                job = Job(recovery=False)
                setattr(job, failure, True)
                backend = job.backend()
                proof = job.run_cleanup(backend)
                self.assertIsInstance(proof, dict)
                self.assertFalse(proof['success'])
                self.assertTrue(proof['errors'])
                self.assertFalse(job.closed or job.profile_removed)
                self.assertTrue(all(row[2] >= proof['gracefulBudgetSeconds']
                                    for row in job.calls if row[0] == 'force'))

    def test_desktop_exception_and_handle_close_failure_remain_visible_after_death(self):
        for failure in ('desktop','handle'):
            with self.subTest(failure=failure):
                job = Job()
                backend = job.backend()
                if failure == 'desktop':
                    original = RuntimeError('original desktop termination failure')
                    backend.desktop = NS(terminate=lambda: (_ for _ in ()).throw(original))
                else:
                    job.handle_close_failure = True
                proof = job.run_cleanup(backend)
                self.assertIsInstance(proof, dict)
                self.assertFalse(proof['success'])
                self.assertIn('original desktop termination failure' if failure == 'desktop' else 'member handle close denied',
                              str(proof['errors']))


class ClosedSessionCleanupTests(unittest.TestCase):
    def session(self, proof=None, cleanup_error=None, modified=False):
        api = importlib.import_module('session')
        calls = []
        def cleanup():
            calls.append('cleanup')
            if cleanup_error is not None:
                raise cleanup_error
            return proof
        backend = NS(status=lambda: dict(modified=modified, title='Owned document'),
                     close=lambda discard: calls.append(('close', discard)), cleanup=cleanup)
        session = api.DocumentSession(Path('C:/Office'), {})
        session.backend, session.state, session.module = backend, 'attached', 'writer'
        return session, backend, calls

    def test_confirmed_model_close_with_cleanup_failure_never_claims_live_document(self):
        session, backend, calls = self.session(cleanup_error=RuntimeError('job still alive'))
        result = session.dispatch('close', {})
        self.assertEqual(result['closed'], True)
        self.assertEqual(result['closeCancelled'], False)
        self.assertEqual(result['cleanupVerified'], False)
        self.assertIn('job still alive', result['cleanupError'])
        self.assertEqual(session.state, 'closed')
        self.assertIs(session.backend, backend)
        self.assertEqual(calls, [('close', False), 'cleanup'])
        with self.assertRaises(importlib.import_module('session').WorkerError):
            session.dispatch('status', {})

    def test_forced_or_unproved_cleanup_is_warning_even_when_cleanup_returns_normally(self):
        for proof in (None, {}, dict(success=True, gracefulQualified=True, forcedTermination=True,
                                    jobEmptyVerified=True, resourcesReleased=True),
                      dict(success=False, gracefulQualified=False, forcedTermination=False,
                           jobEmptyVerified=False, resourcesReleased=False)):
            with self.subTest(proof=proof):
                session, backend, calls = self.session(proof=proof)
                result = session.dispatch('close', {})
                self.assertTrue(result['closed'])
                self.assertFalse(result['cleanupVerified'])
                self.assertTrue(result['cleanupError'])
                self.assertEqual(session.state, 'closed')

    def test_verified_close_can_release_backend_and_shutdown_normally(self):
        proof = dict(success=True, gracefulQualified=True, forcedTermination=False,
                     jobEmptyVerified=True, resourcesReleased=True)
        session, backend, calls = self.session(proof=proof)
        result = session.dispatch('close', {})
        self.assertTrue(result['closed'] and result['cleanupVerified'])
        self.assertNotIn('cleanupError', result)
        self.assertIsNone(session.backend)
        self.assertTrue(session.dispatch('shutdown', {})['shutdown'])
        self.assertEqual(calls.count('cleanup'), 1)

    def test_shutdown_retries_only_retained_backend_and_preserves_failed_proof(self):
        proof = dict(success=False, gracefulQualified=False, forcedTermination=True,
                     jobEmptyVerified=False, resourcesReleased=False)
        session, backend, calls = self.session(proof=proof)
        session.dispatch('close', {})
        result = session.dispatch('shutdown', {})
        self.assertFalse(result['cleanupVerified'])
        self.assertFalse(result['shutdown'])
        self.assertIs(session.backend, backend)
        self.assertEqual(session.state, 'closed')
        self.assertEqual(calls.count('cleanup'), 2)

    def test_cancel_and_preclose_failure_keep_original_attached_state(self):
        session, backend, calls = self.session(modified=True)
        self.assertEqual(session.dispatch('close', {}), dict(closed=False, closeCancelled=True))
        self.assertEqual(session.state, 'attached')
        self.assertEqual(calls, [])
        original = RuntimeError('model close veto')
        def fail(discard):
            raise original
        backend.close = fail
        with self.assertRaises(importlib.import_module('session').WorkerError) as caught:
            session.dispatch('close', dict(discard=True))
        self.assertIs(caught.exception.__cause__, original)
        self.assertEqual(session.state, 'attached')
        self.assertEqual(calls, [])

    def test_status_failure_does_not_run_close_or_cleanup(self):
        session, backend, calls = self.session()
        original = RuntimeError('status transport failed')
        backend.status = lambda: (_ for _ in ()).throw(original)
        with self.assertRaises(RuntimeError) as caught:
            session.dispatch('close', {})
        self.assertIs(caught.exception, original)
        self.assertEqual(session.state, 'attached')
        self.assertEqual(calls, [])

    def test_failed_attach_retains_unproved_cleanup_for_owned_shutdown_retry(self):
        api = importlib.import_module('session')
        original = api.WorkerError('connect_timeout', 'original attach failure')
        calls = []
        def attach(*args):
            raise original
        backend = NS(attach=attach, cleanup=lambda: calls.append('cleanup') or dict(
            success=False, gracefulQualified=False, forcedTermination=True,
            jobEmptyVerified=False, resourcesReleased=False))
        modules = dict(writer=dict(factory='private:factory/swriter'))
        session = api.DocumentSession(Path('C:/Office'), modules, backend_factory=lambda runtime: backend)
        args = dict(parentHwnd=1,module='writer',width=1,height=1)
        with self.assertRaises(api.WorkerError) as caught:
            session.dispatch('attach', args)
        self.assertIs(caught.exception, original)
        self.assertIs(session.backend, backend)
        self.assertEqual(session.state, 'closed')
        with self.assertRaises(api.WorkerError) as caught:
            session.dispatch('attach', args)
        self.assertEqual(caught.exception.code, 'cleanup_pending')
        self.assertFalse(session.dispatch('shutdown', {})['shutdown'])
        self.assertEqual(calls, ['cleanup','cleanup'])


class PreparationHookTests(unittest.TestCase):
    def test_calc_preparation_uses_retained_transaction_without_readonly_status_mutation(self):
        backend = native.UnoBackend(Path('C:/Office'))
        backend.module_factory = 'private:factory/scalc'
        backend.calc_save = object()
        backend.status = lambda: self.fail('Calc preparation must use the explicit native preparation helper')
        result = dict(modified=True, nativeModified=False, title='Calc')
        with patch('calc_close.prepare_calc_close', return_value=result) as prepare:
            self.assertIs(backend.prepare_close(), result)
            prepare.assert_called_once_with(backend.calc_save)
        backend.calc_save = None
        with patch('calc_close.prepare_calc_close') as prepare, self.assertRaises(native.WorkerError):
            backend.prepare_close()
        prepare.assert_not_called()

    def test_other_modules_prepare_by_readonly_status_only(self):
        for factory in ('swriter','simpress','sdraw','smath','sdatabase'):
            with self.subTest(factory=factory):
                backend = native.UnoBackend(Path('C:/Office'))
                backend.module_factory = 'private:factory/' + factory
                result = dict(modified=False, title=factory)
                with patch.object(backend, 'status', return_value=result) as status, \
                        patch('calc_close.prepare_calc_close') as calc:
                    self.assertIs(backend.prepare_close(), result)
                    status.assert_called_once_with()
                    calc.assert_not_called()

    def test_explicit_prepare_rpc_preserves_new_base_save_as_guard_and_periodic_status_is_readonly(self):
        session, backend, calls = ClosedSessionCleanupTests().session()
        backend.prepare_close = lambda: calls.append('prepare') or dict(modified=False, title='Base')
        session.module = 'base'
        session.handles = dict(parentHwnd=11, childHwnd=12)
        self.assertTrue(session.dispatch('status', {})['modified'])
        self.assertEqual(calls, [])
        result = session.dispatch('prepare-close', {})
        self.assertTrue(result['modified'])
        self.assertEqual((result['parentHwnd'],result['childHwnd']), (11,12))
        self.assertEqual(calls, ['prepare'])
        calls.clear()
        # A separate explicit discard does not accept input again.
        session.dispatch('close', dict(discard=True))
        self.assertEqual(calls, [('close',True),'cleanup'])

    def test_prepare_failure_leaves_original_model_attached_and_no_cleanup(self):
        session, backend, calls = ClosedSessionCleanupTests().session()
        original = RuntimeError('native prepare ownership failed')
        backend.prepare_close = lambda: (_ for _ in ()).throw(original)
        with self.assertRaises(RuntimeError) as caught:
            session.dispatch('prepare-close', {})
        self.assertIs(caught.exception, original)
        self.assertEqual(session.state, 'attached')
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
