"""Keep the original complete-step oracle while admitting one exact addendum."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))
sys.path.insert(0, str(Path(__file__).parent))
import test_arm64_workflow as arm
import test_workflow_wiring as wiring


class PairedFailureLegacyContractTests(unittest.TestCase):
    def arm_case(self, change=None):
        case = arm.Arm64WorkflowTests('test_original_native_and_print_steps_cases_and_artifacts_remain_exact')
        case.setUp()
        if change is not None: change(case.jobs['virtual-print']['steps'])
        return case

    def wire_case(self, change=None):
        case = wiring.WiringTests('test_diagnostics_are_bounded_before_upload')
        data = case.load()
        if change is not None: change(data['jobs']['virtual-print']['steps'])
        case.load = lambda: data
        return case

    def test_exact_addendum_preserves_original_hashes_without_mutating_input(self):
        case = self.arm_case()
        before = copy.deepcopy(case.jobs)
        case.test_original_native_and_print_steps_cases_and_artifacts_remain_exact()
        self.assertEqual(case.jobs, before)
        self.wire_case().test_diagnostics_are_bounded_before_upload()

    def test_legacy_original_tail_still_uses_the_same_hash_oracle(self):
        def legacy(steps):
            self.assertEqual([s['id'] for s in steps[-2:]], ['paired-failure-admit', 'paired-failure-evidence'])
            del steps[-2:]
            steps[-3]['run'] = steps[-3]['run'].replace(' --failure-numeric-sidecar', '', 1)
        self.arm_case(legacy).test_original_native_and_print_steps_cases_and_artifacts_remain_exact()
        self.wire_case(legacy).test_diagnostics_are_bounded_before_upload()

    def test_original_core_command_upload_and_native_step_mutants_still_fail(self):
        mutations = [lambda steps: next(s for s in steps if s.get('id') == 'normal-print').update(run='python unreviewed.py'),
            lambda steps: next(s for s in steps if s.get('with', {}).get('path') == 'bounded-evidence/')['with'].update(path='unbounded/'),
            lambda steps: next(s for s in steps if s.get('id') == 'normal-print').update(**{'continue-on-error': True})]
        for code, mutate in enumerate(mutations):
            with self.subTest(caseNumber=code), self.assertRaises(AssertionError):
                self.arm_case(mutate).test_original_native_and_print_steps_cases_and_artifacts_remain_exact()
        case = self.arm_case()
        checkout = next(s for s in case.jobs['native-e2e']['steps'] if s.get('uses', '').startswith('actions/checkout@'))
        checkout.setdefault('with', {})['fetch-depth'] = '999'
        with self.assertRaises(AssertionError):
            case.test_original_native_and_print_steps_cases_and_artifacts_remain_exact()

    def test_missing_duplicate_or_changed_optin_cannot_be_normalized(self):
        def change(steps, code):
            step = next(s for s in steps if s.get('id') == 'paired-print')
            flag = ' --failure-numeric-sidecar'
            step['run'] = step['run'].replace(flag, '' if code == 0 else flag + flag if code == 1 else ' --other-sidecar', 1)
        for code in range(3):
            with self.subTest(caseNumber=code), self.assertRaises(AssertionError):
                self.arm_case(lambda steps: change(steps, code)).test_original_native_and_print_steps_cases_and_artifacts_remain_exact()

    def test_changed_new_tail_or_unknown_upload_never_uses_general_exemption(self):
        def unknown(steps):
            extra = copy.deepcopy(steps[-1])
            extra['id'] = 'unreviewed-numeric-upload'
            steps.append(extra)
        def extra_path(steps):
            steps[-1]['with']['path'] += '\npaired-private-attempts/'
        for code, mutate in enumerate((unknown, extra_path)):
            with self.subTest(caseNumber=code):
                with self.assertRaises(AssertionError):
                    self.arm_case(mutate).test_original_native_and_print_steps_cases_and_artifacts_remain_exact()
                with self.assertRaises(AssertionError):
                    self.wire_case(mutate).test_diagnostics_are_bounded_before_upload()

    def test_missing_admit_or_strict_scope_is_rejected_by_both_original_gates(self):
        def missing_admit(steps):
            steps[:] = [s for s in steps if s.get('id') != 'paired-failure-admit']
        def loose_upload(steps):
            steps[-1]['if'] = steps[-1]['if'].replace(" && steps.paired-failure-admit.outcome == 'success'", '')
        def loose_admit(steps):
            steps[-2]['if'] = steps[-2]['if'].replace(" && github.event.pull_request.draft == true", '')
        for code, mutate in enumerate((missing_admit, loose_upload, loose_admit)):
            with self.subTest(caseNumber=code):
                with self.assertRaises(AssertionError):
                    self.arm_case(mutate).test_original_native_and_print_steps_cases_and_artifacts_remain_exact()
                with self.assertRaises(AssertionError):
                    self.wire_case(mutate).test_diagnostics_are_bounded_before_upload()


if __name__ == '__main__': unittest.main()
