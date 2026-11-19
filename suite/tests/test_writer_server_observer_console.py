"""Synthetic native-file and original-process leases, never Windows evidence."""
import copy
import importlib
import json
from pathlib import Path, PureWindowsPath
import tempfile
from types import SimpleNamespace
import unittest

from test_writer_model_reader import console_host_fixture
from test_writer_server_observer_lifecycle import Clock
import test_writer_server_observer_cohort as cohort_fixture
from test_writer_server_observer_runner_composition import setup, runner


class FileApi:
    def __init__(self):
        self.witness, self.value = console_host_fixture()
        self.blocks = [b'os-host-fixture', b'']; self.closed = []; self.fail_close = False; self.change = False; self.info_calls = 0
    def system_directory(self): return copy.deepcopy(self.witness['systemDirectoryQuery'])
    def open(self, path): self.path = path; return 501
    def info(self, handle):
        self.info_calls += 1
        value = copy.deepcopy(self.value)
        if self.change and self.info_calls > 1: value['fileIndexLow'] += 1
        return value
    def read(self, handle, count): return self.blocks.pop(0)
    def close_handle(self, handle): self.closed.append(handle); return not self.fail_close


class Console(unittest.TestCase):
    def setUp(self): runner._PENDING_CASES.clear(); runner._CASE_STARTED = False
    def tearDown(self): runner._PENDING_CASES.clear(); runner._CASE_STARTED = False
    def module(self):
        try: return importlib.import_module('writer_server_observer_console')
        except ModuleNotFoundError: self.fail('Dedicated console lease absent')
    def prepared(self):
        m = self.module(); api = FileApi(); lease = m.ConsoleProfile(file_api=api)
        budget = runner.PreparationBudget.start(Clock())
        lease.prepare(SimpleNamespace(windows=PureWindowsPath('C:/Windows')), budget)
        return lease, api, budget

    def test_original_system_file_contract_is_reused_and_rechecked(self):
        lease, api, budget = self.prepared()
        self.assertTrue(lease.matches(PureWindowsPath('C:/Windows/System32/conhost.exe'), budget))
        self.assertFalse(lease.matches(PureWindowsPath('C:/other/conhost.exe'), budget))
        api.change = True
        with self.assertRaises(Exception): lease.verify_file(budget)
        self.assertTrue(lease.close_file(budget)); self.assertEqual(api.closed, [501])

    def test_failed_file_close_keeps_original_handle_and_is_never_retried(self):
        lease, api, budget = self.prepared(); api.fail_close = True
        self.assertFalse(lease.close_file(budget))
        self.assertEqual(lease.pending_count(), 1)
        self.assertFalse(lease.close_file(budget)); self.assertEqual(api.closed, [501])

    def test_file_prepare_rollback_failure_keeps_the_original_failed_close_handle(self):
        m = self.module(); api = FileApi(); api.change = True; api.fail_close = True
        lease = m.ConsoleProfile(file_api=api); budget = runner.PreparationBudget.start(Clock())
        with self.assertRaises(Exception): lease.prepare(SimpleNamespace(windows=PureWindowsPath('C:/Windows')), budget)
        self.assertEqual(lease.pending_count(), 1)
        self.assertFalse(lease.close_file(budget)); self.assertEqual(api.closed, [501])

    def test_wrong_native_system_directory_does_not_enable_the_profile(self):
        m = self.module(); api = FileApi(); lease = m.ConsoleProfile(file_api=api)
        budget = runner.PreparationBudget.start(Clock())
        with self.assertRaises(Exception): lease.prepare(SimpleNamespace(windows=PureWindowsPath('D:/Windows')), budget)
        self.assertTrue(lease.close_file(budget)); self.assertEqual(api.closed, [501])

    def composed(self, folder):
        m = self.module(); obj, inputs, c, _ = setup(folder); file_api = FileApi()
        class NativeFilePort(m.ConsoleProfile):
            def prepare(self, layout, budget):
                super().prepare(SimpleNamespace(windows=PureWindowsPath('C:/Windows')), budget)
                # This portable port maps only the OS path representation;
                # actual native file identity/hash policy above remains real.
                self._path = layout.windows / 'System32' / 'conhost.exe'
        profile = NativeFilePort(file_api=file_api)
        obj = runner.DedicatedWriterRunner(c, read_value=obj.read_value, pause=obj.pause, nonce=71,
            console_profile=profile)
        aux = inputs.windows / 'System32' / 'conhost.exe'; aux.touch()
        c.api.images[303] = aux
        original_identity, original_member, original_state, original_open, original_census = (
            c.api.identity, c.api.member, c.api.state, c.api.open_initial_member, c.api.census)
        opens = []
        def identity(handle): return (501, 511) if handle == 303 else original_identity(handle)
        def member(handle, job): return job == 1000 if handle == 303 else original_member(handle, job)
        def state(handle): return ((0, 0) if c.api.dead else (258, 259)) if handle == 303 else original_state(handle)
        def opened(pid, job):
            opens.append(pid)
            return 303 if pid == 501 else original_open(pid, job)
        c.api.identity, c.api.member, c.api.state, c.api.open_initial_member = identity, member, state, opened
        c.api.census = lambda job: ((101, 301, 501, 401) if not c.api.dead else ()) if job == 1000 else original_census(job)
        return obj, inputs, c, profile, file_api, opens

    def test_exact_aux_uses_one_original_handle_and_never_becomes_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder)
            report = obj.execute(inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertEqual(opens.count(501), 1)
        self.assertEqual(c.api.calls.count('close-303'), 1)
        self.assertEqual(report['preparation']['classificationAuxiliaryCount'], 1)
        self.assertTrue(report['preparation']['consoleAuxiliaryExitObserved'])
        self.assertTrue(report['preparation']['consoleJobEmptyObserved'])
        self.assertTrue(report['preparation']['consoleFileReleased'])
        self.assertEqual(report['preparation']['consolePendingHandleCount'], 0)
        self.assertEqual(report['runtime']['external_release_attempted_count'], 3)
        self.assertTrue(report['runtime']['remote_retired'])
        self.assertIs(profile.auxiliary, profile.cohort.auxiliary)
        self.assertNotEqual(profile.cohort.original_engine.pid, profile.auxiliary.pid)
        self.assertFalse(report['normalAcceptance']); self.assertFalse(report['acceptanceEligible'])

    def test_strict_default_still_rejects_that_same_system_image(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder)
            obj.console_profile = None
            report = obj.execute(inputs)
        self.assertEqual(report['failureCode'], 6)
        self.assertEqual(report['preparation']['classificationReasonCode'], 6)
        self.assertNotIn('helper-launch', c.api.calls)

    def test_other_unknown_image_is_not_adopted_by_the_optional_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder)
            foreign = inputs.windows / 'System32' / 'other.exe'; foreign.touch(); c.api.images[303] = foreign
            report = obj.execute(inputs)
        self.assertEqual(report['failureCode'], 6)
        self.assertIsNone(profile.auxiliary)
        self.assertTrue(report['preparation']['consoleFileReleased'])

    def test_aux_file_close_failure_is_pending_and_cannot_report_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder); api.fail_close = True
            report = obj.execute(inputs)
        self.assertTrue(report['captureIncomplete'])
        self.assertGreater(report['pendingRetainedCount'], 0)
        self.assertFalse(report['preparation']['consoleFileReleased'])
        self.assertEqual(report['preparation']['consolePendingHandleCount'], 1)
        self.assertEqual(api.closed, [501])

    def test_cohort_auxiliary_exit_and_job_empty_must_join_the_same_deadline(self):
        m = self.module(); import writer_server_observer_cohort as cohort_module
        kernel, launch, _ = cohort_fixture.CohortContracts().fixture(cohort_module)
        aux = object(); kernel.identities[aux] = (4, 14); kernel.live.add(aux); kernel.listed += (4,)
        original = cohort_module.RetainedProcess(aux, 4, 14)
        cohort = cohort_module.RetainedCohort(kernel, launch, expected_worker=kernel.identity(kernel.handles[1]),
            expected_engine=kernel.identity(kernel.handles[2]), auxiliary=original,
            expected_members=tuple(kernel.identities.values()), require_all_exit=True)
        cohort.admit(); kernel.live = {aux}
        clock, budget = cohort_fixture.CohortContracts().budget(); calls = []
        def pause(seconds): calls.append(1); clock.value += 1; kernel.live.clear()
        proof = cohort.confirm_original_exit(budget, sleeper=pause)
        self.assertTrue(calls); self.assertTrue(proof.remote_retired)
        self.assertTrue(proof.members_exited); self.assertTrue(proof.job_empty)
        self.assertTrue(cohort.release_local().complete)

    def test_aux_generation_or_extra_census_never_enters_the_cohort(self):
        self.module(); import writer_server_observer_cohort as cm
        for changed in (False, True):
            kernel, launch, _ = cohort_fixture.CohortContracts().fixture(cm)
            aux = object(); kernel.identities[aux] = (4, 14); kernel.live.add(aux); kernel.listed += (4,)
            cohort = cm.RetainedCohort(kernel, launch, expected_worker=kernel.identity(kernel.handles[1]),
                expected_engine=kernel.identity(kernel.handles[2]), auxiliary=cm.RetainedProcess(aux, 4, 14),
                expected_members=tuple(kernel.identities.values()), require_all_exit=True)
            if changed: kernel.identities[aux] = (4, 99)
            else:
                extra = object(); kernel.identities[extra] = (5, 15); kernel.live.add(extra); kernel.listed += (5,)
            with self.subTest(changed=changed), self.assertRaises(cm.DiagnosticFailure): cohort.admit()

    def test_optional_aux_without_the_exact_classified_census_is_rejected(self):
        self.module(); import writer_server_observer_cohort as cm
        kernel, launch, _ = cohort_fixture.CohortContracts().fixture(cm)
        aux = object(); kernel.identities[aux] = (4, 14); kernel.live.add(aux); kernel.listed += (4,)
        cohort = cm.RetainedCohort(kernel, launch, expected_worker=kernel.identity(kernel.handles[1]),
            expected_engine=kernel.identity(kernel.handles[2]), auxiliary=cm.RetainedProcess(aux, 4, 14))
        with self.assertRaises(cm.DiagnosticFailure): cohort.admit()

    def test_file_identity_change_after_attach_cannot_reach_the_original_call(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder)
            original = c.prep.focus_snapshot
            def focus(*args, **kwargs):
                result = original(*args, **kwargs); api.change = True; return result
            c.prep.focus_snapshot = focus
            report = obj.execute(inputs)
        self.assertIsNot(report['runtime']['original_call_attempted'], True)
        self.assertTrue(report['captureIncomplete'])

    def test_a_second_exact_console_member_is_rejected_and_never_replaces_the_first(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder)
            identity, member, state, opened = c.api.identity, c.api.member, c.api.state, c.api.open_initial_member
            c.api.images[304] = c.api.images[303]
            c.api.identity = lambda h: (601, 611) if h == 304 else identity(h)
            c.api.member = lambda h, j: j == 1000 if h == 304 else member(h, j)
            c.api.state = lambda h: ((0, 0) if c.api.dead else (258, 259)) if h == 304 else state(h)
            c.api.open_initial_member = lambda p, j: 304 if p == 601 else opened(p, j)
            original = c.api.census
            c.api.census = lambda j: (101, 301, 501, 601, 401) if j == 1000 and not c.api.dead else original(j)
            report = obj.execute(inputs)
        self.assertEqual(report['failureCode'], 6)
        self.assertEqual(profile.auxiliary.pid, 501)
        self.assertEqual(c.api.calls.count('close-304'), 1)
        self.assertEqual(c.api.calls.count('close-303'), 1)
        self.assertNotIn('helper-launch', c.api.calls)

    def test_aux_process_close_failure_preserves_the_same_original_pending_handle(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder); c.api.fail_close = 303
            report = obj.execute(inputs)
        self.assertTrue(report['captureIncomplete'])
        self.assertGreater(report['pendingRetainedCount'], 0)
        self.assertEqual(report['preparation']['consolePendingHandleCount'], 1)
        self.assertTrue(report['preparation']['consoleAuxiliaryExitObserved'])
        self.assertEqual(opens.count(501), 1)
        self.assertEqual(c.api.calls.count('close-303'), 1)

    def test_aux_cannot_extend_the_original_deadline_after_engine_exit(self):
        self.module(); import writer_server_observer_cohort as cm
        kernel, launch, _ = cohort_fixture.CohortContracts().fixture(cm)
        aux = object(); kernel.identities[aux] = (4, 14); kernel.live.add(aux); kernel.listed += (4,)
        cohort = cm.RetainedCohort(kernel, launch, expected_worker=kernel.identity(kernel.handles[1]),
            expected_engine=kernel.identity(kernel.handles[2]), auxiliary=cm.RetainedProcess(aux, 4, 14),
            expected_members=tuple(kernel.identities.values()), require_all_exit=True)
        cohort.admit(); kernel.live = {aux}; clock, budget = cohort_fixture.CohortContracts().budget()
        def pause(seconds): clock.value += 1000
        proof = cohort.confirm_original_exit(budget, sleeper=pause)
        self.assertFalse(proof.within_deadline); self.assertFalse(proof.job_empty)
        released = cohort.release_local()
        self.assertFalse(released.complete); self.assertGreater(released.pending_retained_count, 0)

    def test_iteration_cap_preserves_the_last_normal_auxiliary_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, api, opens = self.composed(folder)
            original = c.api.census
            c.api.census = lambda job: ((101, 301, 501) if not c.api.dead else ()) if job == 1000 else original(job)
            obj.pause = lambda seconds: None
            try: report = obj.execute(inputs)
            except runner.RunnerFailure: self.fail('Original iteration-cap report unavailable')
        self.assertEqual(report['failureCode'], 6)
        self.assertEqual(report['preparation']['classificationReasonCode'], 10)
        self.assertEqual(report['preparation']['classificationAttemptCount'], 4096)
        self.assertEqual(report['preparation']['classificationAuxiliaryCount'], 1)
        self.assertEqual(report['preparation']['classificationAuxiliaryCurrent'], 1)
        self.assertEqual(report['preparation']['classificationCount'], 2)
        self.assertTrue(report['captureIncomplete'])
        self.assertTrue(report['preparation']['cleanupComplete'])

    def late_file_close_report(self, folder):
        obj, inputs, c, profile, api, opens = self.composed(folder)
        def controller_failure(): raise RuntimeError()
        c.api.retain_current_controller = controller_failure
        original = api.close_handle
        def late(handle):
            result = original(handle); c.clock.value += 61000; return result
        api.close_handle = late
        return obj.execute(inputs)

    def test_successful_native_file_close_after_budget_keeps_zero_handles_but_pending_failure(self):
        with tempfile.TemporaryDirectory() as folder: report = self.late_file_close_report(folder)
        self.assertIs(report['preparation']['consoleFileReleased'], False)
        self.assertEqual(report['preparation']['consolePendingHandleCount'], 0)
        self.assertGreater(report['pendingRetainedCount'], 0)
        self.assertTrue(report['captureIncomplete'])
        self.assertIs(report['preparation']['cleanupComplete'], False)
        self.assertIs(runner.validate_public_report(report), report)

    def test_unreleased_file_cannot_report_complete_cleanup_or_no_global_pending_failure(self):
        with tempfile.TemporaryDirectory() as folder: good = self.late_file_close_report(folder)
        for changed in ('pendingRetainedCount', 'cleanupComplete'):
            report = json.loads(json.dumps(good))
            if changed == 'pendingRetainedCount': report[changed] = 0
            else: report['preparation'][changed] = True
            with self.subTest(field_code=int(changed == 'cleanupComplete')):
                with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(report)


if __name__ == '__main__': unittest.main()
