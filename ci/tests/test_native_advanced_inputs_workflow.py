"""Require source-bound advanced inputs before the unchanged native GUI suite."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STAGE = ('python e2e/native_advanced_inputs.py --package package --wasm wasm-input '
         '--fixtures inputs/e2e-fixtures --receipt evidence/native-advanced-inputs.json')


class NativeAdvancedInputsWorkflowTests(unittest.TestCase):
    def test_both_native_jobs_require_advanced_inputs_before_the_gui_suite(self):
        jobs = yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())['jobs']
        for name in ('native-e2e', 'native-e2e-arm64'):
            with self.subTest(job=name):
                steps = jobs[name]['steps']
                staging = [(i, step) for i, step in enumerate(steps)
                           if 'e2e/native_advanced_inputs.py' in step.get('run', '')]
                self.assertEqual(len(staging), 1, 'Advanced native inputs must be staged exactly once')
                index, step = staging[0]
                self.assertEqual(step['run'].strip(), STAGE)
                self.assertEqual(step['shell'], 'pwsh')
                self.assertNotIn('if', step)
                self.assertNotIn('continue-on-error', step)
                gui = [(i, step) for i, step in enumerate(steps)
                       if 'python e2e/run.py' in step.get('run', '')]
                self.assertEqual(len(gui), 1)
                self.assertLess(index, gui[0][0])
                invocation = [line.strip() for line in gui[0][1]['run'].splitlines()
                              if 'python e2e/run.py' in line]
                self.assertEqual(invocation, ['python e2e/run.py'])
                self.assertNotIn('if', gui[0][1])
                self.assertNotIn('continue-on-error', gui[0][1])

    def test_staging_token_is_step_scoped_and_no_browser_download_is_duplicated(self):
        workflow = yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())
        self.assertNotIn('GH_TOKEN', workflow.get('env', {}))
        for name in ('native-e2e', 'native-e2e-arm64'):
            with self.subTest(job=name):
                job = workflow['jobs'][name]
                self.assertNotIn('GH_TOKEN', job.get('env', {}))
                staging = [step for step in job['steps']
                           if 'e2e/native_advanced_inputs.py' in step.get('run', '')]
                self.assertEqual(len(staging), 1)
                self.assertEqual(staging[0]['env'], {'GH_TOKEN': '${{ github.token }}'})
                commands = '\n'.join(step.get('run', '') for step in job['steps'])
                downloads = [line.strip() for line in commands.splitlines()
                             if line.strip().startswith('gh run download ')]
                self.assertEqual(len(downloads), 3, 'The helper owns the additional strict browser-input download')


if __name__ == '__main__':
    unittest.main()
