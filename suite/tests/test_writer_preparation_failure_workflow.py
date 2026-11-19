import copy
import hashlib
import json
from pathlib import Path
import unittest

from ci.policy import load_workflow

BASE = Path(__file__).resolve().parents[2]
SCOPE = ("always() && !cancelled() && steps.writer-context.outcome == 'success' && steps.writer-stage.outcome == 'success'"
         " && steps.atomic-prepare.outcome == 'failure' && steps.writer-observe.outcome == 'skipped'")
BASELINE_SHA256 = '7d7364d900d40fe0f1cadba3dae2fda70192386b4fe71bc932e67d20612d94ea'


class PreparationFailureWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow(BASE / '.github/workflows/office-suite.yml')
        self.job = self.workflow['jobs']['writer-server-observer']
        self.steps = self.job['steps']
        self.byid = {s['id']: s for s in self.steps if 'id' in s}

    def test_only_atomic_diagnostic_selects_caller_profile(self):
        run = self.byid['atomic-prepare']['run']
        self.assertEqual(run.count('--failure-origin-profile budget-deadline-caller-v1'), 1)
        self.assertIn('--seconds 45', run)
        self.assertNotIn('--failure-origin-profile', self.byid['writer-observe']['run'])

    def test_preparation_only_validation_is_separate_from_original_report(self):
        step = self.byid.get('writer-preparation-failure-validate')
        self.assertIsNotNone(step)
        self.assertEqual(step['if'], SCOPE)
        self.assertEqual(step['run'], 'python -B suite/scripts/writer-server-observer-workflow.py validate-preparation-failure --context .work/writer-observer-public/context.numeric.json --compiler-phase .work/writer-observer-public/compiler-phase.numeric.json --output .work/writer-preparation-failure-public')
        self.assertEqual(self.byid['writer-report']['if'], "always() && steps.writer-observe.outcome != 'skipped'")

    def test_failure_upload_has_only_two_closed_staged_json_members(self):
        step = self.byid.get('writer-preparation-failure-upload')
        self.assertIsNotNone(step)
        self.assertEqual(step['if'], SCOPE + " && steps.writer-preparation-failure-validate.outcome == 'success'")
        self.assertEqual(step['uses'], 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02')
        self.assertEqual(step['with']['path'].splitlines(), [
            '.work/writer-preparation-failure-public/context.numeric.json',
            '.work/writer-preparation-failure-public/compiler-phase.numeric.json'])
        self.assertEqual(step['with']['retention-days'], '1')
        self.assertEqual(step['with']['if-no-files-found'], 'error')
        self.assertNotIn('continue-on-error', step)

    def test_all_original_normal_and_writer_gates_are_unchanged(self):
        original = copy.deepcopy(self.workflow)
        original['jobs']['writer-server-observer']['steps'] = [s for s in original['jobs']['writer-server-observer']['steps']
            if s.get('id') not in ('writer-preparation-failure-validate', 'writer-preparation-failure-upload')]
        for step in original['jobs']['writer-server-observer']['steps']:
            if step.get('id') == 'atomic-prepare':
                step['run'] = step['run'].replace(' --failure-origin-profile budget-deadline-caller-v1', '')
        actual = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, BASELINE_SHA256)


if __name__ == '__main__': unittest.main()
