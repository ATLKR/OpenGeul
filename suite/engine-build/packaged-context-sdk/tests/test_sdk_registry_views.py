"""Exact modern32/modern64/legacy64 registry-view contract; synthetic only."""
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
    def __init__(self, registry, slot):
        self.registry, self.slot = registry, slot
    def __enter__(self):
        return self
    def __exit__(self, *ignored):
        self.registry.closed += 1


class ViewRegistry:
    HKEY_LOCAL_MACHINE = 1
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200
    REG_SZ = 1
    def __init__(self, modern32=None, modern64=None, legacy64=None):
        self.rows = (modern32, modern64, legacy64)
        self.opened, self.queried, self.closed = [], [], 0
    def OpenKey(self, hive, key, reserved, flags):
        if hive != self.HKEY_LOCAL_MACHINE or reserved != 0:
            raise ValueError('unexpected_registry_arguments')
        slots = {(MODERN, self.KEY_READ | self.KEY_WOW64_32KEY): 1,
            (MODERN, self.KEY_READ | self.KEY_WOW64_64KEY): 2,
            (LEGACY, self.KEY_READ | self.KEY_WOW64_64KEY): 3}
        slot = slots.get((key, flags))
        if slot is None:
            raise ValueError('unknown_registry_slot')
        self.opened.append(slot)
        row = self.rows[slot - 1]
        if row is None:
            raise missing()
        if isinstance(row, BaseException):
            raise row
        return Key(self, slot)
    def QueryValueEx(self, key, name):
        if name != ('InstallationFolder' if key.slot == 3 else 'KitsRoot10'):
            raise ValueError('unknown_registry_value')
        self.queried.append(key.slot)
        row = self.rows[key.slot - 1]
        if row == 'value-missing':
            raise missing()
        return row if type(row) is tuple else (row, self.REG_SZ)


class SdkRegistryViewTests(unittest.TestCase):
    def api(self):
        import toolchain
        return toolchain
    def test_modern32_only_registration_is_supported(self):
        m = self.api(); registry = ViewRegistry(r'D:\SDK\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'D:\SDK\10')
        self.assertEqual(registry.opened, [1, 2, 3])
        self.assertEqual(registry.closed, 1)
    def test_modern64_only_registration_is_supported(self):
        m = self.api(); registry = ViewRegistry(None, r'D:\SDK\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'D:\SDK\10')
        self.assertEqual(registry.opened, [1, 2, 3])
    def test_original_legacy64_only_contract_is_preserved(self):
        m = self.api(); registry = ViewRegistry(None, None, r'D:\SDK\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'D:\SDK\10')
        self.assertEqual(registry.opened, [1, 2, 3])
    def test_all_present_views_must_name_the_same_windows_root(self):
        m = self.api(); registry = ViewRegistry(r'D:\SDK\10' + '\\', r'd:\sdk\10', r'D:\Sdk\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'D:\SDK\10')
        self.assertEqual(registry.closed, 3)
        for roots in ((r'D:\SDK\10', r'E:\SDK\10', None),
                (r'D:\SDK\10', None, r'E:\SDK\10'), (None, r'D:\SDK\10', r'E:\SDK\10')):
            with self.assertRaises(m.GateFailure) as caught:
                m.sdk_registry_root(ViewRegistry(*roots))
            self.assertEqual(caught.exception.code, 13)
    def test_denied_view_never_becomes_optional_or_uses_later_slots(self):
        m = self.api()
        for slot in (1, 2, 3):
            denied = PermissionError(13, 'synthetic'); denied.winerror = 5
            roots = [r'D:\SDK\10'] * 3; roots[slot - 1] = denied
            registry = ViewRegistry(*roots)
            with self.assertRaises(PermissionError):
                m.sdk_registry_root(registry)
            self.assertEqual(registry.opened, list(range(1, slot + 1)))
    def test_malformed_modern32_is_not_hidden_by_valid_other_roots(self):
        m = self.api()
        for value in ((r'D:\SDK\10', 2), (r'D:\SDK\10', True), (11, 1), r'D:\%SYNTHETIC%'):
            registry = ViewRegistry(value, r'D:\SDK\10', r'D:\SDK\10')
            with self.assertRaises(m.GateFailure):
                m.sdk_registry_root(registry)
            self.assertEqual(registry.opened, [1])
    def test_only_exact_error_two_is_optional_in_modern32(self):
        m = self.api()
        for error in (missing(3), OSError(5, 'synthetic')):
            registry = ViewRegistry(error, r'D:\SDK\10', r'D:\SDK\10')
            with self.assertRaises(type(error)):
                m.sdk_registry_root(registry)
            self.assertEqual(registry.opened, [1])
    def test_all_eight_missing_shapes_remain_inside_existing_report_code_bound(self):
        m = self.api()
        import ci_entry
        from run_sdk_gate import empty_receipt
        for mask in range(8):
            roots = ['value-missing' if mask & bit else None for bit in (4, 2, 1)]
            registry = ViewRegistry(*roots)
            with self.assertRaises(m.GateFailure) as caught:
                m.sdk_registry_root(registry)
            self.assertEqual(caught.exception.code, 24 + mask)
            self.assertTrue(24 <= caught.exception.code <= 31)
            report = empty_receipt(); report['failureCode'] = caught.exception.code
            report['approvedCodeManifestSha256'] = '1' * 64
            self.assertTrue(ci_entry.validate_sdk_report(report, 'x64', '1' * 64, 10.0) is report)
            self.assertEqual(registry.opened, [1, 2, 3])
    def test_no_unlisted_legacy32_or_registry_enumeration_is_needed(self):
        m = self.api(); registry = ViewRegistry(r'D:\SDK\10', r'D:\SDK\10', r'D:\SDK\10')
        self.assertTrue(m.sdk_registry_root(registry) == r'D:\SDK\10')
        self.assertEqual(registry.opened, [1, 2, 3])
        self.assertEqual(registry.queried, [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
