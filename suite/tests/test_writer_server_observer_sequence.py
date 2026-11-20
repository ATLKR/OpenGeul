"""Sequencing tests use explicit external-side-effect doubles, not Windows."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import writer_server_observer_lifecycle as m
from writer_server_observer_cohort import RetainedExitEvidence, LocalRelease
from test_writer_server_observer_lifecycle import Clock


class Capture:
    def __init__(self, budget, fail): self.budget, self.fail = budget, fail
    def step(self, name):
        if name == self.fail: raise RuntimeError('SYNTHETIC_SECRET_DO_NOT_REPORT')
    def create(self): self.step('create')
    def arm_once(self, owner, verify_original): verify_original(); self.step('arm')
    def disable(self):
        self.step('disable')
        return {'admissionClosed': True, 'captureGateClosed': self.fail != 'bad-disable', 'activeCount': 0, 'errors': []}
    def snapshot(self):
        self.step('snapshot')
        if self.fail in ('complete-snapshot', 'bad-cleanup', 'bad-disable'):
            return {'schemaVersion': 1, 'captureIncomplete': False, 'originalBindingMatches': True,
                'admissionClosed': True, 'captureGateClosed': True, 'activeCount': 0, 'decoderErrors': []}
        return {}
    def join_retirement(self, original, evidence):
        self.step('join')
        return {'remoteRetired': 1, 'normalClose': False, 'originalWitnessMatches': True, 'observedWithinDeadline': True, 'errorCode': 0}
    def close_local(self, primary=None):
        self.step('capture-close')
        return {'unmapSucceeded': True, 'mappingHandleClosed': self.fail != 'bad-cleanup',
            'libraryReleased': True, 'cleanupErrors': [], 'disableErrors': [], 'primaryPreserved': primary is not None}


class Cohort:
    def __init__(self, fail): self.original_engine, self.fail, self.disposals = object(), fail, 0
    def verify(self, budget=None):
        if self.fail == 'verify': raise m.DiagnosticFailure(m.FailureCode.OWNERSHIP)
        if budget: budget.check(observation=True)
        return True
    def dispose_owned(self):
        self.disposals += 1
        if self.fail == 'dispose': raise PermissionError()
        return True
    def confirm_original_exit(self, budget):
        if self.fail == 'confirm': raise OSError()
        value = budget.check(observation=False)
        return RetainedExitEvidence(self.original_engine, True, True, True, True, True, True, value, True, 0)
    def release_local(self):
        if self.fail == 'cohort-close': raise OSError()
        return LocalRelease(1, 0, 0, True)


class SequenceContracts(unittest.TestCase):
    def execute(self, fail=None, callback=None, proof_kind=None):
        clock = Clock(); session = m.RuntimeSession(clock); cohort = Cohort(fail)
        owner = SimpleNamespace(original_engine=cohort.original_engine)
        method = getattr(session, 'execute', None)
        self.assertTrue(callable(method), 'lifecycle sequencing implementation absent')
        def original(budget):
            if callback: callback(clock, budget)
            elif fail == 'call': raise RuntimeError('SYNTHETIC_SECRET_DO_NOT_REPORT')
            if proof_kind:
                witness = object()
                if not hasattr(m, 'WatchdogProof'): self.fail('watchdog proof contract absent')
                return m.WatchdogProof(budget=budget, cutoff_qpc=budget.cutoff_qpc,
                    original_helper=witness, exit_helper=witness,
                    helper_identity_matches=True, helper_exit_observed=True,
                    helper_exit_qpc=clock.value, completed=True,
                    timed_out=proof_kind == 'timeout', partial=proof_kind == 'partial')
        result = method(cohort=cohort, owner=owner, capture_factory=lambda budget: Capture(budget, fail),
            verify_original=lambda: True, original_call=original,
            external_releases=(lambda: (_ for _ in ()).throw(OSError()) if fail == 'external-close' else None,))
        return result

    def test_normal_sequence_records_observations_but_never_acceptance(self):
        r = self.execute()
        self.assertTrue(r.original_call_returned); self.assertTrue(r.remote_retired)
        self.assertFalse(r.acceptance_eligible); self.assertFalse(r.whole_original_interval_covered)
        self.assertFalse(r.hard_deadline_enforcement_verified)

    def test_snapshot_failure_does_not_skip_dispose_exit_or_release(self):
        r = self.execute('snapshot')
        self.assertTrue(r.dispose_attempted); self.assertTrue(r.exit_confirmation_attempted)
        self.assertTrue(r.capture_release_attempted); self.assertTrue(r.cohort_release_attempted)

    def test_disable_failure_does_not_skip_snapshot_or_other_cleanup(self):
        r = self.execute('disable')
        self.assertTrue(r.snapshot_attempted); self.assertTrue(r.dispose_attempted)
        self.assertTrue(r.cohort_release_attempted)

    def test_create_failure_still_runs_finally_on_inert_capture_object(self):
        r = self.execute('create')
        self.assertFalse(r.original_call_attempted); self.assertTrue(r.disable_attempted)
        self.assertTrue(r.capture_release_attempted); self.assertTrue(r.cohort_release_attempted)

    def test_arm_failure_never_starts_original_call(self):
        r = self.execute('arm')
        self.assertFalse(r.original_call_attempted); self.assertTrue(r.dispose_attempted)

    def test_original_call_exception_still_closes_all_owned_stages(self):
        r = self.execute('call')
        self.assertTrue(r.original_call_attempted); self.assertFalse(r.original_call_returned)
        self.assertTrue(r.dispose_attempted); self.assertTrue(r.capture_release_attempted)

    def test_pre_s_failure_has_no_new_runtime_budget_and_no_remote_success(self):
        r = self.execute('verify')
        self.assertFalse(r.runtime_started); self.assertFalse(r.original_call_attempted)
        self.assertFalse(r.remote_retired); self.assertTrue(r.dispose_attempted)
        self.assertTrue(r.cohort_release_attempted)

    def test_late_original_return_cannot_be_accepted(self):
        r = self.execute(callback=lambda clock, budget: setattr(clock, 'value', budget.deadline_qpc + 1))
        self.assertTrue(r.original_call_returned); self.assertFalse(r.original_call_within_cutoff)
        self.assertFalse(r.remote_retired); self.assertTrue(r.cohort_release_attempted)

    def test_cleanup_permission_failure_is_not_retirement(self):
        r = self.execute('dispose')
        self.assertFalse(r.dispose_completed); self.assertTrue(r.exit_confirmation_attempted)
        self.assertTrue(r.cohort_release_attempted)

    def test_exit_observation_failure_remains_unknown(self):
        r = self.execute('confirm')
        self.assertFalse(r.remote_retired); self.assertTrue(r.capture_release_attempted)

    def test_each_local_release_is_independent(self):
        for failure in ('capture-close', 'cohort-close', 'external-close', 'join'):
            with self.subTest(stage=failure):
                r = self.execute(failure)
                self.assertTrue(r.capture_release_attempted); self.assertTrue(r.cohort_release_attempted)
                self.assertEqual(r.external_release_attempted_count, 1)

    def test_numeric_report_does_not_export_exception_or_private_binding(self):
        r = self.execute('call'); report = r.numeric_projection()
        self.assertTrue(all(type(v) in (bool, int, type(None)) for v in report.values()))
        self.assertTrue(all(not any(s in k.lower() for s in ('handle','nonce','pid','hwnd','birth','text','value','name')) for k in report))

    def test_missing_watchdog_proof_is_always_incomplete(self):
        r = self.execute()
        self.assertTrue(r.capture_incomplete); self.assertFalse(r.watchdog_verified)

    def test_partial_or_timed_out_helper_proof_cannot_authorize_capture(self):
        for kind in ('partial', 'timeout'):
            with self.subTest(kind=kind):
                r = self.execute(proof_kind=kind)
                self.assertTrue(r.capture_incomplete); self.assertFalse(r.watchdog_verified)

    def test_valid_watchdog_proof_is_separate_from_server_snapshot(self):
        r = self.execute(proof_kind='valid')
        self.assertTrue(r.watchdog_verified)
        self.assertTrue(r.capture_incomplete)  # The external snapshot is still unknown.

    def test_complete_numeric_capture_needs_all_independent_receipts(self):
        r = self.execute('complete-snapshot', proof_kind='valid')
        self.assertFalse(r.capture_incomplete); self.assertTrue(r.capture_release_completed)
        self.assertFalse(r.acceptance_eligible); self.assertFalse(r.hard_deadline_enforcement_verified)

    def test_false_numeric_cleanup_receipt_is_not_success(self):
        r = self.execute('bad-cleanup', proof_kind='valid')
        self.assertTrue(r.capture_incomplete); self.assertFalse(r.capture_release_completed)
        self.assertTrue(r.cohort_release_attempted)

    def test_false_disabled_gate_is_not_closed_success(self):
        r = self.execute('bad-disable', proof_kind='valid')
        self.assertTrue(r.capture_incomplete); self.assertFalse(r.disable_completed)
        self.assertTrue(r.snapshot_attempted)

    def test_forced_retirement_is_never_normal_ui_close(self):
        r = self.execute()
        self.assertTrue(r.remote_retired)
        self.assertIs(getattr(r, 'forced_disposal_requested', None), True)
        self.assertIs(getattr(r, 'normal_close_verified', None), False)

    def test_second_execute_never_runs_finally_again(self):
        clock = Clock(); session = m.RuntimeSession(clock); cohort = Cohort(None)
        owner = SimpleNamespace(original_engine=cohort.original_engine)
        args = dict(cohort=cohort, owner=owner, capture_factory=lambda b: Capture(b, None),
            verify_original=lambda: True, original_call=lambda b: None)
        session.execute(**args); before = cohort.disposals
        try: session.execute(**args)
        except m.DiagnosticFailure: pass
        self.assertEqual(cohort.disposals, before)

    def test_primary_exception_is_preserved_for_actual_capture_close(self):
        r = self.execute('call')
        self.assertTrue(r.capture_release_completed)

    def test_unbounded_external_release_input_is_never_iterated(self):
        class Unbounded:
            def __iter__(self): raise RuntimeError('Synthetic unbounded release input')
        session = m.RuntimeSession(Clock()); cohort = Cohort(None)
        try:
            receipt = session.execute(cohort=cohort, owner=SimpleNamespace(original_engine=cohort.original_engine),
                capture_factory=lambda b: Capture(b, None), verify_original=lambda: True,
                original_call=lambda b: None, external_releases=Unbounded())
        except Exception: self.fail('Unbounded cleanup input escaped numeric failure boundary')
        self.assertTrue(receipt.capture_incomplete); self.assertTrue(receipt.cohort_release_attempted)
        self.assertEqual(receipt.external_release_attempted_count, 0)


if __name__ == '__main__': unittest.main()
