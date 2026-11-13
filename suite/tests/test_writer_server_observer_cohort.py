"""Synthetic kernel seam: verifies coordinator rules, never Windows success."""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from test_writer_server_observer_lifecycle import Clock


class Kernel:
    def __init__(self):
        self.job = object(); self.handles = tuple(object() for _ in range(3))
        self.identities = {h: (n + 1, n + 11) for n, h in enumerate(self.handles)}
        self.live = set(self.handles); self.listed = tuple(n + 1 for n in range(3))
        self.foreign = set(); self.close_fail = set(); self.denied = False
        self.state_error = False; self.job_empty_only = False; self.open_count = 0
        self.controller = object(); self.controller_identity = (99, 199)
        self.closed = set()
        self.launch_local_ok = True
        self.terminations = 0

    def identity(self, handle): return self.controller_identity if handle is self.controller else self.identities[handle]
    def state(self, handle):
        if self.state_error: raise OSError()
        if handle is self.controller: return (258, 259)
        return (258, 259) if handle in self.live else (0, 0)
    def member(self, handle, job): return job is self.job and handle not in self.foreign
    def census(self, job):
        if job is not self.job: raise OSError()
        if self.job_empty_only: return ()
        return tuple(p for h, (p, _) in self.identities.items() if h in self.live and p in self.listed)
    def open_initial_member(self, pid, job):
        self.open_count += 1
        return next(h for h, v in self.identities.items() if v[0] == pid)
    def terminate_job(self, job):
        self.terminations += 1
        if self.denied: raise PermissionError()
        self.live.clear(); return True
    def close(self, handle):
        if handle in self.close_fail or handle in self.closed: return False
        self.closed.add(handle)
        return True
    def release_launch_local(self, launch): return self.launch_local_ok


class CohortContracts(unittest.TestCase):
    def module(self):
        try: return importlib.import_module('writer_server_observer_cohort')
        except ModuleNotFoundError: self.fail('cohort implementation absent')

    def fixture(self, m):
        kernel = Kernel(); h = kernel.handles
        launch = SimpleNamespace(job=kernel.job, host=h[0], thread=object(), identity=kernel.identity(h[0]),
            failed=False, resumed=True, uncertain=False, creation_job_membership=True, pre_resume_verified=True,
            controller_handle=kernel.controller, controller_identity=kernel.controller_identity, nonce=object())
        cohort = m.RetainedCohort(kernel, launch,
            expected_worker=kernel.identity(h[1]), expected_engine=kernel.identity(h[2]))
        return kernel, launch, cohort

    def budget(self):
        from writer_server_observer_lifecycle import OriginalWriterBudget
        clock = Clock(); return clock, OriginalWriterBudget.start(clock)

    def test_admission_requires_every_original_member_in_same_job(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m)
        kernel.foreign.add(kernel.handles[2])
        with self.assertRaises(m.DiagnosticFailure): cohort.admit()
        self.assertFalse(cohort.admitted)

    def test_unowned_generation_cannot_be_substituted(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        kernel.identities[kernel.handles[2]] = (3, 999)
        with self.assertRaises(m.DiagnosticFailure): cohort.verify()

    def test_uncertain_or_not_creation_assigned_launch_never_arms(self):
        m = self.module()
        for key in ('uncertain', 'failed', 'creation_job_membership', 'pre_resume_verified', 'resumed'):
            kernel, launch, cohort = self.fixture(m)
            setattr(launch, key, key in ('uncertain', 'failed'))
            with self.subTest(flag=key):
                with self.assertRaises(m.DiagnosticFailure): cohort.admit()

    def test_extra_census_member_requires_an_original_retained_handle(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m)
        original = kernel.census
        kernel.census = lambda job: original(job) + (999,)
        with self.assertRaises(m.DiagnosticFailure): cohort.admit()

    def test_pre_arm_live_generation_is_rechecked_without_reopening(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); opened = kernel.open_count
        cohort.verify(); cohort.verify()
        self.assertEqual(kernel.open_count, opened)

    def test_same_original_exit_before_deadline_can_confirm_retirement(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        clock, budget = self.budget(); clock.value = 125001
        cohort.dispose_owned(); proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertTrue(proof.remote_retired); self.assertTrue(proof.engine_exit_observed)
        self.assertTrue(proof.job_empty); self.assertTrue(proof.members_exited)

    def test_exit_at_deadline_is_unknown_even_when_job_is_empty(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        clock, budget = self.budget(); clock.value = 130000; cohort.dispose_owned()
        proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertFalse(proof.remote_retired); self.assertFalse(proof.within_deadline)

    def test_engine_birth_change_after_kill_request_is_not_exit_proof(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); cohort.dispose_owned()
        kernel.identities[kernel.handles[2]] = (3, 999)
        _, budget = self.budget(); proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertFalse(proof.remote_retired)

    def test_shell_exit_and_empty_census_do_not_replace_engine_exit(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        kernel.live = {kernel.handles[2]}; kernel.job_empty_only = True
        clock, budget = self.budget()
        def sleep(seconds): clock.value += max(1, int(seconds * clock.frequency))
        proof = cohort.confirm_original_exit(budget, sleeper=sleep)
        self.assertFalse(proof.remote_retired); self.assertFalse(proof.engine_exit_observed)

    def test_failed_wait_or_exit_code_is_unknown(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); kernel.state_error = True
        _, budget = self.budget(); proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertFalse(proof.remote_retired)

    def test_cleanup_permission_failure_preserves_original_witness(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); kernel.denied = True
        with self.assertRaises(m.DiagnosticFailure): cohort.dispose_owned()
        result = cohort.release_local()
        self.assertGreater(result.pending_retained_count, 0)
        self.assertFalse(result.complete)

    def test_release_failure_does_not_skip_other_local_handles(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); cohort.dispose_owned()
        _, budget = self.budget(); cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        kernel.close_fail.add(kernel.handles[1]); result = cohort.release_local()
        self.assertEqual(result.failed_count, 1)
        self.assertGreaterEqual(result.closed_count, 3)

    def test_retirement_never_reopens_a_pid(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); opened = kernel.open_count
        cohort.dispose_owned(); _, budget = self.budget(); cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertEqual(kernel.open_count, opened)

    def test_cohort_repr_never_contains_private_identity(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m)
        self.assertEqual(repr(cohort), '<RetainedCohort private>')

    def test_original_controller_birth_cannot_be_replaced(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        kernel.controller_identity = (99, 999)
        with self.assertRaises(m.DiagnosticFailure): cohort.verify()

    def test_private_session_nonce_cannot_be_swapped(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); launch.nonce = object()
        with self.assertRaises(m.DiagnosticFailure): cohort.verify()

    def test_engine_exit_does_not_claim_other_members_have_retired(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        kernel.live.remove(kernel.handles[2]); _, budget = self.budget()
        proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertTrue(proof.remote_retired); self.assertFalse(proof.members_exited)
        released = cohort.release_local()
        self.assertFalse(released.complete); self.assertGreater(released.pending_retained_count, 0)

    def test_successful_local_handles_are_not_closed_twice(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); cohort.dispose_owned()
        _, budget = self.budget(); cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        first = cohort.release_local(); second = cohort.release_local()
        self.assertTrue(first.complete); self.assertTrue(second.complete)
        self.assertEqual(second.closed_count, 0); self.assertEqual(second.failed_count, 0)

    def test_partial_attribute_or_stdio_release_failure_stays_incomplete(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); cohort.dispose_owned()
        _, budget = self.budget(); cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        kernel.launch_local_ok = False
        released = cohort.release_local()
        self.assertFalse(released.complete); self.assertGreater(released.failed_count, 0)
        self.assertGreater(released.closed_count, 0)

    def test_closed_job_is_never_submitted_for_disposal_again(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); cohort.dispose_owned()
        _, budget = self.budget(); cohort.confirm_original_exit(budget, sleeper=lambda _: None); cohort.release_local()
        before = kernel.terminations
        try: cohort.dispose_owned()
        except m.DiagnosticFailure: pass
        self.assertEqual(kernel.terminations, before)

    def test_original_engine_role_is_read_only_after_admission(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        with self.assertRaises(AttributeError): cohort.original_engine = cohort._members[launch.identity[0]]

    def test_changed_internal_engine_role_cannot_retire_the_original(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit()
        host = cohort._members[launch.identity[0]]
        # Fault injection models an accidental role assignment in the adapter.
        try: cohort.original_engine = host
        except AttributeError: object.__setattr__(cohort, '_original_engine', host)
        kernel.live.remove(kernel.handles[0]); _, budget = self.budget()
        proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertFalse(proof.remote_retired)

    def test_local_release_is_terminal_for_retirement_observation(self):
        m = self.module(); kernel, launch, cohort = self.fixture(m); cohort.admit(); cohort.dispose_owned()
        _, budget = self.budget(); cohort.confirm_original_exit(budget, sleeper=lambda _: None); cohort.release_local()
        proof = cohort.confirm_original_exit(budget, sleeper=lambda _: None)
        self.assertFalse(proof.remote_retired)


if __name__ == '__main__': unittest.main()
