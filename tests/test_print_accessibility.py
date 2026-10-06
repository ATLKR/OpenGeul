import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
from webview_debug import debug_arguments,ScopedDebugOverride
class AccessibilityArgumentTests(unittest.TestCase):
    def test_default_remains_unchanged(self):
        self.assertNotIn('accessibility',debug_arguments(9231))
    def test_exact_supported_flag_is_opt_in(self):
        self.assertEqual(debug_arguments(9231,accessibility=True),debug_arguments(9231)+' --force-renderer-accessibility=complete')
    def test_machine_and_process_overrides_match(self):
        scope=ScopedDebugOverride(None,'OpenGeul.exe',9231,'C:/temp/profile',runner=True,accessibility=True)
        self.assertEqual(scope.values[0][1],debug_arguments(9231,accessibility=True))
    def test_arbitrary_flags_are_rejected(self):
        with self.assertRaises(ValueError):debug_arguments(9231,accessibility='--no-sandbox')
