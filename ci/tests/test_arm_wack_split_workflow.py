"""ARM native proof and stock x64 SDK scans are both release requirements."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from policy import load_workflow
from store_package import REQUIRED_JOBS
ROOT = Path(__file__).resolve().parents[2]
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'


class ArmWackSplitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = load_workflow(ROOT / '.github/workflows/msix.yml')['jobs']
        self.store = load_workflow(ROOT / '.github/workflows/store-package.yml')['jobs']

    def commands(self, job):
        return '\n'.join(s.get('run', '') for s in job['steps'])

    def assert_transport(self, job, command, name):
        steps = job['steps']
        publish = [(i,s) for i,s in enumerate(steps) if command in s.get('run', '')]
        self.assertEqual(len(publish), 1)
        index, step = publish[0]
        self.assertEqual(step['env'], {'GH_TOKEN': '${{ github.token }}'})
        self.assertNotIn('if', step)
        uploads = [(i,s) for i,s in enumerate(steps) if s.get('with', {}).get('name') == name]
        self.assertEqual(len(uploads), 1)
        upload_index, upload = uploads[0]
        self.assertLess(index, upload_index)
        self.assertEqual(upload['uses'], UPLOAD)
        self.assertNotIn('if', upload)
        self.assertEqual(upload['with']['path'].splitlines(),
                         ['native-transport/native-install.json','native-transport/test-only.msix','native-transport/test.cer'])
        self.assertEqual(str(upload['with']['retention-days']), '1')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertNotIn('include-hidden-files', upload['with'])
        self.assertNotIn('overwrite', upload['with'])
        self.assertNotIn('.pfx', str(job))
        self.assertNotIn('STORE_CLIENT_SECRET', str(job))

    def test_source_native_and_sdk_are_distinct_mandatory_gates(self):
        self.assertEqual(len(REQUIRED_JOBS), 21)
        self.assertIn('msix-native-arm64', REQUIRED_JOBS)
        native = self.source['msix-native-arm64']; sdk = self.source['msix-install-arm64']
        self.assertEqual(native['runs-on'], 'windows-11-arm')
        self.assertEqual(set(native['needs']), {'build-arm64','native-e2e-arm64'})
        self.assertIn('-NativeOnly -TransportDirectory native-transport', self.commands(native))
        self.assertIn('-Architecture arm64', self.commands(native))
        self.assertNotIn('msix-wack-import.ps1', self.commands(native))
        self.assertEqual(sdk['runs-on'], 'windows-2025')
        self.assertEqual(set(sdk['needs']), {'build-arm64','msix-native-arm64'})
        self.assertIn('scripts/native_wack_transport.py download-source --package-directory package --output native-input', self.commands(sdk))
        self.assertIn('./e2e/msix-wack-import.ps1 -PackageDirectory package -NativeDirectory native-input -OutputDirectory evidence', self.commands(sdk))
        self.assertNotIn('msix-install.ps1', self.commands(sdk))
        self.assertNotIn('runner-ready.py', self.commands(sdk))
        for final in ('release','cleanup-transports'):
            self.assertIn('msix-native-arm64', self.source[final]['needs'])
        self.assert_transport(native, 'scripts/native_wack_transport.py publish-source --package-directory package --evidence evidence --transport native-transport',
                              'opengeul-native-signed-arm64-${{ github.run_id }}-${{ github.run_attempt }}')

    def test_store_sdk_stays_on_x64_and_all_five_jobs_precede_submission(self):
        self.assertIn('store-native-arm64', self.store)
        native = self.store['store-native-arm64']; sdk = self.store['store-wack']
        self.assertEqual(native['runs-on'], 'windows-11-arm')
        self.assertEqual(native['env'], {'ARCHITECTURE':'arm64'})
        self.assertEqual(native['needs'], ['package'])
        self.assertIn('-NativeOnly -TransportDirectory native-transport', self.commands(native))
        self.assertEqual(sdk['runs-on'], 'windows-2025')
        self.assertEqual(sdk['strategy']['matrix'], {'architecture':['x64','arm64']})
        self.assertEqual(sdk['name'], 'Store WACK (${{ matrix.architecture }})')
        self.assertEqual(set(sdk['needs']), {'package','store-native-arm64'})
        self.assertEqual(sdk['env'], {'ARCHITECTURE':'${{ matrix.architecture }}'})
        self.assertNotIn('runner-ready.py', self.commands(sdk))
        download = next(s for s in sdk['steps'] if 'native_wack_transport.py download-store' in s.get('run', ''))
        self.assertEqual(download['if'], "env.ARCHITECTURE == 'arm64'")
        self.assertEqual(download['env'], {'GH_TOKEN':'${{ github.token }}'})
        self.assertIn('scripts/native_wack_transport.py download-store --store-directory store-output --output native-input', download['run'])
        self.assertIn('./e2e/msix-wack-import.ps1 -PackageDirectory package-wack -NativeDirectory native-input -OutputDirectory installed', self.commands(sdk))
        for final in ('qualify','submit'):
            self.assertIn('store-native-arm64', self.store[final]['needs'])
            self.assertIn("needs['store-native-arm64'].result == 'success'", self.store[final]['if'])
        self.assert_transport(native, 'scripts/native_wack_transport.py publish-store --store-directory store-output --evidence installed --transport native-transport',
                              'opengeul-store-native-signed-arm64-${{ github.run_id }}-${{ github.run_attempt }}')


if __name__ == '__main__': unittest.main()
