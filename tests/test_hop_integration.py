"""Keep reviewed HOP fixes in both shipped frontends and every release gate."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class HopIntegrationTests(unittest.TestCase):
    def test_windows_build_applies_the_reviewed_fixes_before_building(self):
        text=(ROOT/'scripts/build-msix.ps1').read_text()
        self.assertIn('python scripts/prepare_hop_fixes.py $source',text)
        self.assertLess(text.index('python scripts/prepare_hop_fixes.py $source'),text.index('pnpm run build:studio'))
        self.assertIn('--loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs',text)
    def test_browser_build_applies_and_tests_the_same_fixes(self):
        text=(ROOT/'scripts/build-wasm.sh').read_text()
        self.assertIn('python scripts/prepare_hop_fixes.py .work/hop',text)
        self.assertLess(text.index('python scripts/prepare_hop_fixes.py .work/hop'),text.index('pnpm run build:studio'))
        self.assertIn('--loader ./tests/hop/loader.mjs --test tests/hop/*.test.mjs',text)
    def test_release_tests_include_followups_without_dropping_baseline(self):
        text=(ROOT/'e2e/run.py').read_text()
        self.assertIn('from test_hop_followups import suite',text)
        self.assertIn('required=required_methods(mode)',text)
        self.assertIn('coverage_ok(mode,result.records)',text)
        workflow=(ROOT/'.github/workflows/msix.yml').read_text()
        self.assertIn('needs: [wasm, build, native-e2e, browser-e2e, msix-install, virtual-print]',workflow)
    def test_backport_attribution_is_shipped_with_license_notices(self):
        text=(ROOT/'THIRD_PARTY_NOTICES.md').read_text()
        self.assertIn('FMsongX2',text)
        self.assertIn('f9bbe8dc66172a1959af1e388e6c28a5b597c5a6',text)
if __name__=='__main__':unittest.main()
