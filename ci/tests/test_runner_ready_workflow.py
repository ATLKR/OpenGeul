"""ARM GUI 실행 전 준비 실패는 제품 실행을 막고 원본 관찰은 제한하여 보존한다."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy import load_workflow

ROOT = Path(__file__).resolve().parents[2]
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
ARM_JOBS = ('native-e2e-arm64', 'virtual-print-arm64', 'msix-native-arm64')


class RunnerReadyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = load_workflow(ROOT/'.github/workflows/msix.yml')['jobs']
        self.store = load_workflow(ROOT/'.github/workflows/store-package.yml')['jobs']

    def ready(self, job):
        steps = job['steps']
        found = [(i, step) for i, step in enumerate(steps) if step.get('id') == 'runner-ready']
        self.assertEqual(len(found), 1)
        return steps, *found[0]

    def test_source_arm_preparation_follows_dependencies_and_precedes_every_product_gui(self):
        products = {'native-e2e-arm64': 'e2e/check_webview2_missing.py',
                    'virtual-print-arm64': 'e2e/virtual_print.py',
                    'msix-native-arm64': './e2e/msix-install.ps1'}
        for name in ARM_JOBS:
            with self.subTest(job=name):
                steps, index, ready = self.ready(self.source[name])
                self.assertEqual(self.source[name]['runs-on'], 'windows-11-arm')
                self.assertTrue(any('pip install -r e2e/requirements.txt' in s.get('run', '') or
                                    'pip install -r e2e/print-requirements.txt' in s.get('run', '')
                                    for s in steps[:index]))
                product = next(i for i, s in enumerate(steps) if products[name] in s.get('run', ''))
                self.assertLess(index, product)
                self.assertNotIn('if', ready)
                self.assertNotIn('continue-on-error', ready)
                self.assertNotIn('if', steps[product])
                self.assertNotIn('continue-on-error', steps[product])
                self.assertEqual(ready['shell'], 'pwsh')
                self.assertIn("$PSNativeCommandUseErrorActionPreference=$true", ready['run'])
                self.assertIn('python e2e/runner-ready.py --prepare --output runner-ready', ready['run'])

    def test_no_x64_sdk_job_runs_arm_readiness_and_store_native_job_is_exact(self):
        for name, job in self.source.items():
            if name not in ARM_JOBS:
                self.assertNotIn('e2e/runner-ready.py', '\n'.join(s.get('run', '') for s in job.get('steps', [])))
        native=self.store['store-native-arm64']
        steps, index, ready = self.ready(native)
        self.assertNotIn('if', ready)
        dependency = [i for i, s in enumerate(steps) if s.get('id') == 'runner-ready-tools']
        self.assertEqual(len(dependency), 1);self.assertLess(dependency[0], index)
        self.assertNotIn('if', steps[dependency[0]])
        self.assertIn('python -m pip install -r e2e/requirements.txt', steps[dependency[0]]['run'])
        product = next(i for i, s in enumerate(steps) if './e2e/msix-install.ps1' in s.get('run', ''))
        self.assertLess(index, product);self.assertNotIn('if', steps[product])
        self.assertNotIn('continue-on-error', steps[product])
        self.assertNotIn('runner-ready.py', str(self.store['store-wack']))

    def test_original_before_after_png_json_and_result_use_raw_hard_cap_and_attempt_unique_upload(self):
        jobs = [(name, self.source[name]) for name in ARM_JOBS] + [('store-native-arm64', self.store['store-native-arm64'])]
        for name, job in jobs:
            with self.subTest(job=name):
                steps, ready_index, _ = self.ready(job)
                checks = [(i, s) for i, s in enumerate(steps) if s.get('id') == 'runner-ready-size']
                uploads = [(i, s) for i, s in enumerate(steps) if s.get('id') == 'runner-ready-evidence']
                self.assertEqual(len(checks), 1); self.assertEqual(len(uploads), 1)
                cap_index, cap = checks[0]; upload_index, upload = uploads[0]
                self.assertLess(ready_index, cap_index); self.assertLess(cap_index, upload_index)
                self.assertIn('always()', cap['if'])
                self.assertIn("steps.runner-ready.outcome != 'skipped'", cap['if'])
                self.assertEqual(cap['run'], 'python ci/evidence.py size --limit-mib 16 runner-ready')
                self.assertNotIn('continue-on-error', cap)
                self.assertIn('always()', upload['if'])
                self.assertIn("steps.runner-ready-size.outcome == 'success'", upload['if'])
                self.assertEqual(upload['uses'], UPLOAD)
                options = upload['with']
                self.assertEqual(options['path'], 'runner-ready/')
                self.assertEqual(str(options['retention-days']), '1')
                self.assertEqual(options['if-no-files-found'], 'error')
                self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', options['name'])
                self.assertNotIn('overwrite', options); self.assertNotIn('include-hidden-files', options)

    def test_ready_helpers_do_not_receive_tokens_or_bypass_binding_environment(self):
        for job in [self.source[name] for name in ARM_JOBS] + [self.store['store-native-arm64']]:
            for step in job['steps']:
                if step.get('id', '').startswith('runner-ready'):
                    self.assertNotIn('env', step)
                    self.assertNotIn('GH_TOKEN', step.get('run', ''))
                    self.assertNotIn('GITHUB_', step.get('run', ''))
                    self.assertNotIn('continue-on-error', step)

    def test_source_release_cleanup_and_store_full_wack_gates_are_not_bypassed(self):
        required = {'wasm','build','build-arm64','native-e2e','native-e2e-arm64','browser-e2e',
                    'msix-install','msix-native-arm64','msix-install-arm64','virtual-print','virtual-print-arm64'}
        self.assertEqual(set(self.source['release']['needs']), required)
        self.assertTrue(required <= set(self.source['cleanup-transports']['needs']))
        self.assertEqual(self.store['store-wack']['strategy']['matrix']['architecture'], ['x64','arm64'])
        self.assertEqual(set(self.store['qualify']['needs']), {'package','store-native-arm64','store-wack'})
        self.assertEqual(set(self.store['submit']['needs']), {'package','store-native-arm64','store-wack','qualify'})
        for name in ARM_JOBS:
            self.assertNotIn('continue-on-error', self.source[name])
        self.assertIn('-ExpectedCliSha256 $cliSha', '\n'.join(s.get('run', '') for s in self.store['store-native-arm64']['steps']))
        self.assertIn('scripts/store_qualification.py collect', '\n'.join(s.get('run', '') for s in self.store['store-wack']['steps']))


if __name__ == '__main__': unittest.main()
