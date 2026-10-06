import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
try:
    from webview_debug import ScopedDebugOverride, debug_arguments
except ImportError:
    ScopedDebugOverride = None
    debug_arguments = None

class Registry:
    def __init__(self): self.values = {}; self.writes = []; self.fail_on = None
    def read(self, category, app):
        if (category,app) not in self.values: raise FileNotFoundError()
        return self.values[category,app]
    def write(self, category, app, value):
        if category == self.fail_on: raise OSError('injected registry failure')
        self.values[category,app] = value; self.writes.append((category, app, value))
    def delete(self, category, app): del self.values[category,app]

class DebugOverrideTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ScopedDebugOverride, 'scoped debug override is not implemented')
        self.reg = Registry()
    def test_sets_only_exact_app_and_restores_after_use(self):
        scope=ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=True)
        with scope:
            self.assertEqual({key[1] for key in self.reg.values},{'OpenGeul.exe'})
            self.assertEqual(self.reg.values['AdditionalBrowserArguments','OpenGeul.exe'], '--remote-debugging-address=127.0.0.1 --remote-debugging-port=51234')
            self.assertEqual(self.reg.values['UserDataFolder','OpenGeul.exe'],'C:/Temp/isolated')
        self.assertFalse(self.reg.values)
    def test_refuses_outside_disposable_runner(self):
        with self.assertRaisesRegex(RuntimeError,'runner'):
            with ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=False): pass
        self.assertFalse(self.reg.writes)
    def test_refuses_existing_override_before_any_mutation(self):
        self.reg.values['UserDataFolder','OpenGeul.exe']='existing user data'
        with self.assertRaisesRegex(RuntimeError,'existing'):
            with ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=True):pass
        self.assertEqual(self.reg.values,{('UserDataFolder','OpenGeul.exe'):'existing user data'})
        self.assertFalse(self.reg.writes)
    def test_failed_second_write_removes_first_write(self):
        self.reg.fail_on='UserDataFolder'
        with self.assertRaises(OSError):
            with ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=True): pass
        self.assertFalse(self.reg.values)
    def test_restores_on_test_failure(self):
        with self.assertRaises(ValueError):
            with ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=True):raise ValueError('test failed')
        self.assertFalse(self.reg.values)
    def test_does_not_delete_a_foreign_change(self):
        scope=ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=True)
        scope.__enter__();self.reg.values['UserDataFolder','OpenGeul.exe']='foreign'
        with self.assertRaisesRegex(RuntimeError,'changed'): scope.close()
        self.assertEqual(self.reg.values,{('UserDataFolder','OpenGeul.exe'):'foreign'})
    def test_refuses_wildcard_or_other_application(self):
        for name in ['*','Other.exe','C:/OpenGeul.exe']:
            with self.subTest(name=name),self.assertRaises(ValueError):
                ScopedDebugOverride(self.reg,name,51234,'C:/Temp/isolated',runner=True)
        self.assertFalse(self.reg.writes)
    def test_rejects_bad_port(self):
        for port in [0,80,-1,65536,'9222; --no-sandbox',True]:
            with self.subTest(port=port),self.assertRaises(ValueError): debug_arguments(port)
    def test_cleanup_is_idempotent(self):
        scope=ScopedDebugOverride(self.reg,'OpenGeul.exe',51234,'C:/Temp/isolated',runner=True)
        scope.__enter__();scope.close();scope.close();self.assertFalse(self.reg.values)

if __name__=='__main__':unittest.main()
