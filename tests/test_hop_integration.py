"""Keep reviewed HOP fixes in both shipped frontends and every release gate."""
from pathlib import Path
import unittest
from ci.policy import load_workflow
ROOT=Path(__file__).resolve().parents[1]

class HopIntegrationTests(unittest.TestCase):
    def test_windows_build_tests_upstream_behavior_before_building(self):
        text=(ROOT/'scripts/build-msix.ps1').read_text()
        self.assertNotIn('prepare_hop_fixes',text)
        self.assertIn('--loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs',text)
    def test_browser_build_tests_the_same_upstream_behavior(self):
        text=(ROOT/'scripts/build-wasm.sh').read_text()
        self.assertNotIn('prepare_hop_fixes',text)
        self.assertIn('--loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs',text)
    def test_release_tests_include_followups_without_dropping_baseline(self):
        text=(ROOT/'e2e/run.py').read_text()
        self.assertIn('from test_hop_followups import suite',text)
        self.assertIn('exact_ids(discovered_ids(tests), mode)',text)
        self.assertIn('validate_evidence(payload, xml',text)
        self.assertIn("(output/'junit.xml').read_bytes()",text)
        workflow=load_workflow(ROOT/'.github/workflows/msix.yml')
        self.assertEqual(workflow['jobs']['release']['needs'], [
            'wasm', 'build', 'build-arm64', 'native-e2e', 'native-e2e-arm64',
            'browser-e2e', 'msix-install', 'msix-native-arm64', 'msix-install-arm64',
            'virtual-print', 'virtual-print-arm64',
        ])
        for name in ('native-e2e', 'native-e2e-arm64', 'browser-e2e'):
            steps = workflow['jobs'][name]['steps']
            runners = [step for step in steps if 'python e2e/run.py' in step.get('run', '')]
            self.assertEqual(len(runners), 1, name)
            self.assertNotIn('if', runners[0], name)
            self.assertNotIn('continue-on-error', runners[0], name)
            invocation = [line.strip() for line in runners[0]['run'].splitlines() if 'python e2e/run.py' in line]
            self.assertEqual(invocation, ['python e2e/run.py'], name)
            self.assertTrue(any('e2e/requirements.txt' in step.get('run', '') for step in steps), name)
        self.assertIn('pypdfium2==5.8.0', (ROOT/'e2e/requirements.txt').read_text())
    def test_backport_attribution_is_shipped_with_license_notices(self):
        text=(ROOT/'THIRD_PARTY_NOTICES.md').read_text()
        self.assertIn('FMsongX2',text)
        self.assertIn('f9bbe8dc66172a1959af1e388e6c28a5b597c5a6',text)
    def test_preflight_requires_ui_contract_and_oracle_dependencies_at_e2e_pins(self):
        required = {'PyYAML==6.0.3', 'Pillow==12.3.0', 'playwright==1.55.0',
                    'pypdfium2==5.8.0', 'reportlab==4.4.9'}
        declared = [line.strip() for line in (ROOT/'ci/requirements.txt').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(set(declared), required)
        self.assertEqual(len(declared), len(required))
        ui = (ROOT/'e2e/requirements.txt').read_text().splitlines()
        printing = (ROOT/'e2e/print-requirements.txt').read_text().splitlines()
        for dependency in ('Pillow==12.3.0', 'playwright==1.55.0', 'pypdfium2==5.8.0'):
            self.assertIn(dependency, ui)
        for dependency in ('pypdfium2==5.8.0', 'reportlab==4.4.9'):
            self.assertIn(dependency, printing)
if __name__=='__main__':unittest.main()
