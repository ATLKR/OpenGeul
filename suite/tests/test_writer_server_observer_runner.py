"""Synthetic top-level contracts. They never establish Windows readiness."""
import importlib
from pathlib import Path
import sys
import unittest
from dataclasses import replace
import contextlib
import io
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))


class Clock:
    frequency = 1000
    def __init__(self): self.value = 100000
    def read(self): return self.value


class RunnerContracts(unittest.TestCase):
    def module(self):
        try: return importlib.import_module('writer_server_observer_runner')
        except ModuleNotFoundError: self.fail('runner implementation absent')

    def test_preparation_has_one_original_55_60_interval(self):
        m = self.module(); clock = Clock(); budget = m.PreparationBudget.start(clock)
        self.assertEqual((budget.start_qpc, budget.cutoff_qpc, budget.deadline_qpc), (100000, 155000, 160000))
        clock.value = 154001
        self.assertEqual(budget.remaining_ms(observation=True), 999)
        self.assertEqual(budget.remaining_ms(observation=False), 5999)

    def test_preparation_exact_cutoff_stops_work_but_keeps_cleanup_reserve(self):
        m = self.module(); clock = Clock(); budget = m.PreparationBudget.start(clock); clock.value = 155000
        with self.assertRaises(m.RunnerFailure): budget.check(observation=True)
        self.assertEqual(budget.remaining_ms(observation=False), 5000)

    def test_preparation_exact_deadline_cannot_prove_cleanup(self):
        m = self.module(); clock = Clock(); budget = m.PreparationBudget.start(clock); clock.value = 160000
        with self.assertRaises(m.RunnerFailure): budget.check(observation=False)

    def test_preparation_clock_reversal_and_frequency_change_are_sticky(self):
        m = self.module()
        for changed in ('reverse', 'frequency'):
            clock = Clock(); budget = m.PreparationBudget.start(clock)
            if changed == 'reverse': clock.value -= 1
            else: clock.frequency += 1
            with self.subTest(mode=changed):
                with self.assertRaises(m.RunnerFailure): budget.check(observation=True)
                clock.value += 10; clock.frequency = 1000
                with self.assertRaises(m.RunnerFailure): budget.check(observation=False)

    def test_preparation_overflow_is_unknown(self):
        m = self.module(); clock = Clock(); clock.value = (1 << 63) - 1
        with self.assertRaises(m.RunnerFailure): m.PreparationBudget.start(clock)

    def test_preparation_cannot_rebase_its_original_deadline(self):
        m = self.module(); budget = m.PreparationBudget.start(Clock())
        with self.assertRaises(m.RunnerFailure): replace(budget, start_qpc=100001, cutoff_qpc=155001, deadline_qpc=160001)

    def test_admission_300_handoff_has_identical_final_a_and_first_p_origin(self):
        m=self.module();clock=Clock();reads=[]
        self.assertTrue(hasattr(m,'AdmissionBudget'),'separate admission budget absent')
        clock.read=lambda:reads.append(clock.value) or clock.value
        a=m.AdmissionBudget.start(clock);self.assertEqual(a.deadline_qpc,400000)
        clock.value=125000;proof=a.complete();count=len(reads)
        p=m.PreparationBudget.from_admission(proof)
        self.assertEqual(len(reads),count)
        self.assertEqual(p.start_qpc,proof.completed_qpc)
        self.assertEqual((p.cutoff_qpc,p.deadline_qpc),(180000,185000))
        self.assertIs(p._clock,a._clock)
        with self.assertRaises(m.RunnerFailure):m.PreparationBudget.from_admission(proof)

    def test_admission_cached_or_modified_proof_cannot_start_preparation(self):
        m=self.module();self.assertTrue(hasattr(m,'AdmissionBudget'),'separate admission budget absent')
        clock=Clock();a=m.AdmissionBudget.start(clock);proof=a.complete()
        with self.assertRaises(m.RunnerFailure):replace(proof,completed_qpc=proof.completed_qpc+1)
        with self.assertRaises(m.RunnerFailure):replace(a,deadline_qpc=a.deadline_qpc+1)
        with self.assertRaises(m.RunnerFailure):m.PreparationBudget.from_admission({'completed_qpc':100000})

    def test_admission_exact_deadline_or_changed_frequency_cannot_handoff(self):
        m=self.module()
        self.assertTrue(hasattr(m,'AdmissionBudget'),'separate admission budget absent')
        for mode in ('deadline','frequency','reverse'):
            clock=Clock();a=m.AdmissionBudget.start(clock)
            if mode=='deadline':clock.value=400000
            elif mode=='frequency':clock.frequency=1001
            else:clock.value=99999
            with self.subTest(mode=mode):
                with self.assertRaises(m.RunnerFailure):a.complete()

    def test_admission_budget_overflow_is_rejected(self):
        m=self.module();clock=Clock();clock.value=(1<<63)-100
        self.assertTrue(hasattr(m,'AdmissionBudget'),'separate admission budget absent')
        with self.assertRaises(m.RunnerFailure):m.AdmissionBudget.start(clock)

    def test_admission_cannot_be_copied_to_reset_handoff(self):
        m=self.module();a=m.AdmissionBudget.start(Clock());a.complete()
        with self.assertRaises(m.RunnerFailure):replace(a)

    def test_valid_admission_near_integer_limit_cannot_overflow_preparation(self):
        m=self.module();clock=Clock();clock.value=(1<<63)-300002
        a=m.AdmissionBudget.start(clock);clock.value=(1<<63)-20000;proof=a.complete()
        with self.assertRaises(m.RunnerFailure):m.PreparationBudget.from_admission(proof)

    def test_handoff_frequency_failure_is_exact_typed_sticky_and_one_attempt(self):
        m=self.module()
        for mode in ('changed','float','bool','getter'):
            class FrequencyClock:
                value=100000
                current=1 if mode=='bool' else 1000
                broken=False
                reads=0
                @property
                def frequency(self):
                    if self.broken:raise RuntimeError('synthetic clock getter')
                    return self.current
                def read(self):self.reads+=1;return self.value
            clock=FrequencyClock();a=m.AdmissionBudget.start(clock);proof=a.complete();reads=clock.reads
            if mode=='getter':clock.broken=True
            else:clock.current={'changed':1001,'float':1000.0,'bool':True}[mode]
            with self.subTest(mode=mode):
                failed=False
                try:m.PreparationBudget.from_admission(proof)
                except Exception:failed=True
                self.assertTrue(failed)
                clock.broken=False;clock.current=1 if mode=='bool' else 1000
                with self.assertRaises(m.RunnerFailure):m.PreparationBudget.from_admission(proof)
                self.assertTrue(proof._clock.invalid)
                self.assertEqual(clock.reads,reads)

    def test_runner_requires_actual_components_and_one_attempt(self):
        m = self.module()
        self.assertTrue(callable(getattr(m, 'DedicatedWriterRunner', None)))
        self.assertTrue(callable(getattr(m, 'NativeComponents', None)))
        self.assertTrue(callable(getattr(m, 'main', None)))

    def test_snapshot_unknown_key_and_private_identity_are_rejected(self):
        m = self.module()
        for bad in ({'schemaVersion': 1, 'pid': 1}, {'rows': [], 'Name': 'SYNTHETIC_SECRET_DO_NOT_EXPORT'}):
            with self.assertRaises(m.RunnerFailure): m.project_snapshot(bad)

    def test_final_report_has_only_closed_sections_and_false_acceptance(self):
        m = self.module(); report = m.empty_report()
        self.assertIs(report['normalAcceptance'], False)
        self.assertIs(report['originalClientAttributionUnknown'], True)
        self.assertEqual(report['caseCount'], 1)
        self.assertEqual(m.validate_public_report(report), report)
        for section in ('preparation', 'runtime', 'snapshot', 'msaa'):
            corrupt = m.empty_report(); corrupt[section]['secret'] = 'SYNTHETIC_SECRET_DO_NOT_EXPORT'
            with self.assertRaises(m.RunnerFailure): m.validate_public_report(corrupt)
        corrupt = m.empty_report(); corrupt['normalAcceptance'] = True
        with self.assertRaises(m.RunnerFailure): m.validate_public_report(corrupt)

    def test_valid_negative_helper_is_distinct_from_getter_not_attempted(self):
        m = self.module()
        result = m.project_msaa({'msaaVerified': False, 'helperExitObserved': True,
            'observation': {'verified': 0, 'stageCode': 2, 'hresult': 0, 'focusVariantType': 0,
                'focusCall': {'attempted': 0, 'returned': 0, 'hrObserved': 0, 'hr': 0, 'vtObserved': 0, 'rejectCode': 0}}})
        self.assertIs(result['getAccFocusAttempted'], False)
        self.assertIs(result['sOkObserved'], False); self.assertIs(result['msaaVerified'], False)

    def test_vt_empty_s_ok_is_preserved_without_acceptance(self):
        m = self.module()
        result = m.project_msaa({'msaaVerified': False, 'helperExitObserved': True,
            'observation': {'verified': 0, 'stageCode': 4, 'hresult': 0, 'focusVariantType': 0,
                'focusCall': {'attempted': 1, 'returned': 1, 'hrObserved': 1, 'hr': 0, 'vtObserved': 1, 'rejectCode': 3}}})
        self.assertIs(result['getAccFocusAttempted'], True); self.assertIs(result['getAccFocusReturned'], True)
        self.assertIs(result['sOkObserved'], True); self.assertIs(result['emptyVariantObserved'], True)
        self.assertIs(result['msaaVerified'], False); self.assertEqual(result['rejectCode'], 3)

    def test_missing_focus_call_is_unknown_not_initialized_s_ok(self):
        m = self.module(); result = m.project_msaa({'msaaVerified': False, 'observation': {'verified': 0, 'stageCode': 1, 'hresult': 0, 'focusVariantType': 0}})
        self.assertIsNone(result['getAccFocusAttempted']); self.assertIsNone(result['sOkObserved'])

    def test_msaa_unexpected_private_leaf_is_never_projected(self):
        m = self.module()
        with self.assertRaises(m.RunnerFailure):
            m.project_msaa({'msaaVerified': False, 'observation': {'Name': 'SYNTHETIC_SECRET_DO_NOT_EXPORT'}})

    def test_runtime_row_projection_rejects_unknown_private_fields(self):
        m = self.module()
        with self.assertRaises(m.RunnerFailure): m.project_rows([{'kind': 1, 'phase': 10, 'datum': 0, 'scopeOrdinal': 1, 'parentScopeOrdinal': 0, 'qpc': 100001, 'depth': 1, 'threadOrdinal': 1, 'eventOrdinal': 1, 'pid': 1}])

    def test_runtime_row_projection_preserves_only_closed_fields(self):
        m = self.module(); row = {'kind': 2, 'phase': 2, 'datum': 3, 'scopeOrdinal': 1, 'parentScopeOrdinal': 0, 'qpc': 100001, 'depth': 1, 'threadOrdinal': 1, 'eventOrdinal': 1}
        self.assertEqual(m.project_rows([row]), [row])

    def test_numeric_report_rejects_nested_raw_or_noninteger_values(self):
        m = self.module()
        for bad in ({'path': 'SYNTHETIC_SECRET_DO_NOT_EXPORT'}, {'schemaVersion': 1, 'preparation': {'rawError': 'SYNTHETIC_SECRET_DO_NOT_EXPORT'}}, {'schemaVersion': 1, 'stageCode': 1.25}):
            with self.subTest(field_count=len(bad)):
                with self.assertRaises(m.RunnerFailure): m.validate_public_report(bad)

    def test_main_argument_failure_is_numeric_and_never_echoes_input(self):
        m = self.module(); output=io.StringIO()
        with contextlib.redirect_stdout(output): result=m.main(['--unknown','SYNTHETIC_SECRET_DO_NOT_EXPORT'])
        self.assertEqual(result,1)
        self.assertNotIn('SYNTHETIC_SECRET_DO_NOT_EXPORT',output.getvalue())
        m.validate_public_report(json.loads(output.getvalue()))

    def test_original_raw_cleanup_and_reference_counts_are_preserved(self):
        m=self.module();observed={'verified':0,'stageCode':4,'hresult':0,'focusVariantType':0,
            'cleanupFailure':1,'cleanupHresult':2147500037,'ownerReleased':1,'referencesAcquired':2,
            'referencesReleased':2,'variantsCreated':2,'variantsCleared':2}
        value=m.project_msaa({'msaaVerified':False,'observation':observed})
        self.assertIs(value['cleanupFailure'],True)
        self.assertEqual(value['cleanupHresult'],2147500037)
        self.assertEqual(value['referencesReleased'],2)


if __name__ == '__main__': unittest.main()
