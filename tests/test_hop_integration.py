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
        self.assertIn("expected=16 if os.environ.get('E2E_MODE')=='native' else 10",text)
        workflow=load_workflow(ROOT/'.github/workflows/msix.yml')
        self.assertEqual(workflow['jobs']['release']['needs'], [
            'wasm', 'build', 'build-arm64', 'native-e2e', 'native-e2e-arm64',
            'browser-e2e', 'msix-install', 'msix-install-arm64',
            'virtual-print', 'virtual-print-arm64',
        ])
    def test_backport_attribution_is_shipped_with_license_notices(self):
        text=(ROOT/'THIRD_PARTY_NOTICES.md').read_text()
        self.assertIn('FMsongX2',text)
        self.assertIn('f9bbe8dc66172a1959af1e388e6c28a5b597c5a6',text)
if __name__=='__main__':unittest.main()
