"""Installed metadata support; no registry writes or Windows execution."""
import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODERN = r'SOFTWARE\Microsoft\Windows Kits\Installed Roots'
LEGACY = r'SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0'


def missing(code=2):
    error = FileNotFoundError(2, 'synthetic')
    error.winerror = code
    return error


class Key:
    def __init__(self, owner, slot):
        self.owner, self.slot = owner, slot
    def __enter__(self):
        return self
    def __exit__(self, *ignored):
        self.owner.closed += 1


class Registry:
    HKEY_LOCAL_MACHINE = 1
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200
    REG_SZ = 1
    def __init__(self, modern=None, legacy=None):
        self.rows = {(MODERN, self.KEY_WOW64_32KEY): modern,
            (MODERN, self.KEY_WOW64_64KEY): modern, (LEGACY, self.KEY_WOW64_64KEY): legacy}
        self.opened, self.queried, self.closed = [], [], 0
    def OpenKey(self, hive, key, reserved, flags):
        if hive != 1 or reserved != 0 or flags not in (self.KEY_READ | self.KEY_WOW64_64KEY, self.KEY_READ | self.KEY_WOW64_32KEY):
            raise ValueError('wrong_registry_view')
        slot = (key, flags & (self.KEY_WOW64_32KEY | self.KEY_WOW64_64KEY))
        if slot not in self.rows:
            raise ValueError('unknown_registry_slot')
        self.opened.append(slot)
        row = self.rows[slot]
        if row is None:
            raise missing()
        if isinstance(row, BaseException):
            raise row
        return Key(self, slot)
    def QueryValueEx(self, key, name):
        expected = 'KitsRoot10' if key.slot[0] == MODERN else 'InstallationFolder'
        if name != expected:
            raise ValueError('unknown_registry_value')
        self.queried.append(key.slot)
        row = self.rows[key.slot]
        if row == 'value-missing':
            raise missing()
        return row if type(row) is tuple else (row, self.REG_SZ)


class SdkRegistryTests(unittest.TestCase):
    def api(self):
        import toolchain
        self.assertTrue(hasattr(toolchain, 'sdk_registry_root'), 'finite SDK registry resolver required')
        return toolchain
    def test_modern_registered_root_survives_legacy_key_absence(self):
        m = self.api(); registry = Registry(r'C:\SDK\10' + '\\')
        self.assertTrue(m.sdk_registry_root(registry) == r'C:\SDK\10')
        self.assertEqual(len(registry.opened), 3)
        self.assertEqual(registry.closed, 2)
    def test_legacy_registered_root_survives_only_exact_modern_absence(self):
        m = self.api(); registry = Registry(None, r'D:\SDK\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'D:\SDK\10')
        self.assertEqual(registry.closed, 1)
    def test_matching_case_and_trailing_separator_are_the_same_windows_root(self):
        m = self.api(); registry = Registry(r'C:\SDK\10' + '\\', r'c:\sdk\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'C:\SDK\10')
        self.assertEqual(registry.closed, 3)
    def test_conflicting_registered_roots_fail_closed(self):
        m = self.api(); registry = Registry(r'C:\SDK\10', r'D:\SDK\10')
        with self.assertRaises(m.GateFailure) as caught:
            m.sdk_registry_root(registry)
        self.assertEqual(caught.exception.code, 13)
    def test_all_missing_key_value_combinations_have_closed_failure_codes(self):
        m = self.api()
        for first, second, expected in ((None, None, 24), (None, 'value-missing', 25),
                ('value-missing', None, 30), ('value-missing', 'value-missing', 31)):
            with self.subTest(code=expected):
                registry = Registry(first, second)
                with self.assertRaises(m.GateFailure) as caught:
                    m.sdk_registry_root(registry)
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(registry.closed, 2 * int(first is not None) + int(second is not None))
    def test_access_denial_never_tries_an_alternate_root(self):
        m = self.api()
        denied = PermissionError(13, 'synthetic'); denied.winerror = 5
        registry = Registry(denied, r'D:\SDK\10')
        with self.assertRaises(PermissionError):
            m.sdk_registry_root(registry)
        self.assertEqual(len(registry.opened), 1)
        registry = Registry(r'C:\SDK\10', denied)
        with self.assertRaises(PermissionError):
            m.sdk_registry_root(registry)
        self.assertEqual(len(registry.opened), 3)
    def test_other_file_errors_are_not_treated_as_absence(self):
        m = self.api()
        for error in (missing(3), OSError(5, 'synthetic')):
            registry = Registry(error, r'D:\SDK\10')
            with self.assertRaises(type(error)):
                m.sdk_registry_root(registry)
            self.assertEqual(len(registry.opened), 1)
    def test_malformed_or_expandable_or_injected_path_does_not_fall_back(self):
        m = self.api()
        for value in ((r'C:\SDK\10', 2), (r'C:\SDK\10', True), (17, 1), r'C:\SDK\%SYNTHETIC%', r'\\host\share', r'C:\SDK\..\10'):
            registry = Registry(value, r'D:\SDK\10')
            with self.assertRaises(m.GateFailure):
                m.sdk_registry_root(registry)
            self.assertEqual(len(registry.opened), 1)
            self.assertEqual(registry.closed, 1)
    def test_live_discovery_uses_the_finite_resolver_without_path_guessing(self):
        m = self.api()
        tree = ast.parse((ROOT / 'toolchain.py').read_bytes())
        method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'system_locations')
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == 'sdk_registry_root']
        self.assertEqual(len(calls), 1)
        self.assertTrue(isinstance(calls[0].args[0], ast.Name) and calls[0].args[0].id == 'winreg')


if __name__ == '__main__':
    unittest.main()
