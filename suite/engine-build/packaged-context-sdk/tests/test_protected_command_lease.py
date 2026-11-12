"""Synthetic retained OS-command policy; no Windows or SDK execution."""
import copy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pe_bytes(machine=0x8664):
    b = bytearray(512); b[:2] = b'MZ'; struct.pack_into('<I', b, 0x3c, 128)
    b[128:132] = b'PE\0\0'; struct.pack_into('<H', b, 132, machine)
    struct.pack_into('<H', b, 150, 0x22); struct.pack_into('<H', b, 152, 0x20b)
    return bytes(b)


class Clock:
    def __init__(self):
        self.now = 1.0
    def __call__(self):
        return self.now


class Api:
    def __init__(self, clock):
        self.clock = clock; self.directory = r'C:\Windows\System32'; self.windows = r'C:\Windows'
        self.data = pe_bytes(); self.reparse = False; self.protected = True; self.inherit = False
        self.links = 2; self.modified = (10, 10); self.foreign_fresh = False; self.wrong_final = False
        self.opened = []; self.closed = []; self.live = set(); self.next = 100
        self.fail_open = False; self.fail_read = False; self.close_ok = True; self.read_seconds = 0
        self.budgets = []
    def set_deadline(self, deadline):
        self.budgets.append(deadline)
    def system_directory(self):
        return self.directory
    def windows_directory(self):
        return self.windows
    def no_reparse(self, path):
        return not self.reparse
    def is_protected(self, path):
        return self.protected
    def open(self, path):
        if self.fail_open:
            raise PermissionError(13, 'synthetic')
        self.next += 1; self.opened.append(self.next); self.live.add(self.next)
        return self.next
    def snapshot(self, handle):
        if handle not in self.live:
            raise ValueError('not_live')
        foreign = self.foreign_fresh and handle != self.opened[0]
        return {'identity': (1, bytes([2 if foreign else 1]) * 16),
            'finalPath': r'\\?\C:\Windows\System32\cmd.exe' if not self.wrong_final else r'\\?\D:\other\cmd.exe',
            'size': len(self.data), 'modified': self.modified, 'links': self.links,
            'regular': True, 'reparse': self.reparse, 'inheritable': self.inherit}
    def read(self, handle, expected_size):
        if self.fail_read:
            raise PermissionError(13, 'synthetic')
        self.clock.now += self.read_seconds
        return self.data
    def close(self, handle):
        self.closed.append(handle)
        if self.close_ok:
            self.live.remove(handle)
        return self.close_ok


class ProtectedCommandLeaseTests(unittest.TestCase):
    def api(self):
        import toolchain
        self.assertTrue(hasattr(toolchain, '_CommandLease'), 'command lease required')
        return toolchain
    def make(self, *, machine=0x8664):
        m = self.api(); clock = Clock(); api = Api(clock); api.data = pe_bytes(machine)
        lease = m._CommandLease('x64' if machine == 0x8664 else 'arm64', 180.0, api, clock=clock)
        return m, clock, api, lease
    def test_stable_os_selected_two_link_command_requires_every_binding(self):
        m, clock, api, lease = self.make()
        self.assertTrue(lease.path == r'C:\Windows\System32\cmd.exe')
        self.assertEqual(lease.record, {'machine': 0x8664, 'bytes': 512, 'sha256': hashlib.sha256(api.data).hexdigest()})
        self.assertEqual(len(api.live), 1)
        self.assertEqual(lease.verify(), lease.record)
        self.assertTrue(lease.close()); self.assertTrue(lease.close())
        self.assertEqual(len(api.live), 0); self.assertEqual(len(api.closed), len(set(api.closed)))
        receipt = lease.observation()
        self.assertTrue(receipt['wrpProtected'] and receipt['closed'] and receipt['handleIdentityStable'])
        self.assertTrue(receipt['protectionClassificationOnly']); self.assertFalse(receipt['signatureVerified'])
        self.assertEqual(receipt['linkCount'], 2)
    def test_stable_single_link_and_native_arm64_are_supported(self):
        m = self.api()
        for machine in (0x8664, 0xaa64):
            clock = Clock(); api = Api(clock); api.links = 1; api.data = pe_bytes(machine)
            lease = m._CommandLease('x64' if machine == 0x8664 else 'arm64', 180.0, api, clock=clock)
            self.assertEqual(lease.record['machine'], machine); self.assertTrue(lease.close())
    def test_generic_hardlinked_source_and_tools_remain_forbidden(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'command.exe'; p.write_bytes(pe_bytes())
            alias = Path(td) / 'alias.exe'; alias.hardlink_to(p)
            with self.assertRaises(m.GateFailure):
                m.pe(p, 0x8664)
    def test_unprotected_unknown_or_nonboolean_classification_rejects_before_open(self):
        m = self.api()
        for value in (False, None, 1):
            clock = Clock(); api = Api(clock); api.protected = value
            with self.assertRaises(m.GateFailure):
                m._CommandLease('x64', 180.0, api, clock=clock)
            self.assertEqual(api.opened, [])
    def test_system_directory_disagreement_and_path_injection_are_rejected(self):
        m = self.api()
        for directory in (r'D:\owned', r'C:\Windows\..\System32', r'\\host\share', r'C:\%SYNTHETIC%'):
            clock = Clock(); api = Api(clock); api.directory = directory
            with self.assertRaises(m.GateFailure):
                m._CommandLease('x64', 180.0, api, clock=clock)
            self.assertEqual(api.opened, [])
    def test_reparse_or_inheritable_or_foreign_final_path_rejects_and_closes(self):
        m = self.api()
        for field in ('reparse', 'inherit', 'wrong_final'):
            clock = Clock(); api = Api(clock); setattr(api, field, True)
            with self.assertRaises(m.GateFailure):
                m._CommandLease('x64', 180.0, api, clock=clock)
            self.assertFalse(api.live); self.assertEqual(len(api.closed), len(set(api.closed)))
    def test_foreign_fresh_identity_never_matches_retained_handle_by_path(self):
        m = self.api(); clock = Clock(); api = Api(clock); api.foreign_fresh = True
        with self.assertRaises(m.GateFailure):
            m._CommandLease('x64', 180.0, api, clock=clock)
        self.assertFalse(api.live); self.assertEqual(len(api.closed), 2)
    def test_post_admission_identity_path_metadata_link_and_bytes_changes_reject(self):
        for field, value in (('foreign_fresh', True), ('wrong_final', True), ('modified', (11, 11)),
                ('links', 3), ('data', pe_bytes() + b'\0'), ('data', pe_bytes()[:-1] + b'1')):
            m, clock, api, lease = self.make(); setattr(api, field, value)
            try:
                with self.assertRaises(m.GateFailure):
                    lease.verify()
                self.assertFalse(lease.observation()['handleIdentityStable'])
            finally:
                self.assertTrue(lease.close())
            self.assertFalse(api.live); self.assertEqual(len(api.closed), len(set(api.closed)))
    def test_wrong_native_pe_machine_or_corrupt_pe_rejects_without_leak(self):
        m = self.api()
        for data in (pe_bytes(0xaa64), b'MZ' + b'\0' * 510):
            clock = Clock(); api = Api(clock); api.data = data
            with self.assertRaises(m.GateFailure):
                m._CommandLease('x64', 180.0, api, clock=clock)
            self.assertFalse(api.live)
    def test_failed_open_and_failed_read_never_retry_with_broader_rights(self):
        m = self.api()
        for field in ('fail_open', 'fail_read'):
            clock = Clock(); api = Api(clock); setattr(api, field, True)
            with self.assertRaises(m.GateFailure):
                m._CommandLease('x64', 180.0, api, clock=clock)
            self.assertLessEqual(len(api.opened), 1); self.assertFalse(api.live)
    def test_expiry_after_open_or_read_closes_the_retained_handle_once(self):
        m = self.api(); clock = Clock(); api = Api(clock); api.read_seconds = 180.0
        with self.assertRaises(m.GateFailure):
            m._CommandLease('x64', 180.0, api, clock=clock)
        self.assertFalse(api.live); self.assertEqual(len(api.closed), 1)
    def test_phase_budget_cannot_extend_the_original_or_expired_deadline(self):
        m, clock, api, lease = self.make()
        for deadline in (181.0, 1.0, float('nan'), True):
            with self.assertRaises(m.GateFailure):
                lease.verify(deadline=deadline)
        self.assertTrue(lease.close())
    def test_expired_factory_refuses_before_constructing_the_native_adapter(self):
        m=self.api()
        with mock.patch.object(m.time,'monotonic',return_value=181.0),mock.patch.object(m,'_Win32CommandApi') as constructor:
            with self.assertRaises(m.GateFailure):m.acquire_command('x64',180.0)
            self.assertFalse(constructor.called)
    def test_shorter_phase_budget_is_sent_before_adapter_calls(self):
        m,clock,api,lease=self.make();api.budgets.clear()
        try:
            lease.verify(deadline=30.0)
            self.assertTrue(bool(api.budgets));self.assertEqual(set(api.budgets),{30.0})
        finally:self.assertTrue(lease.close())
    def test_close_failure_is_not_retried_or_reported_as_closed(self):
        m, clock, api, lease = self.make(); api.close_ok = False
        before = len(api.closed)
        self.assertFalse(lease.close()); self.assertFalse(lease.close())
        self.assertEqual(len(api.closed), before + 1); self.assertFalse(lease.observation()['closed'])
    def test_cancelled_read_closes_fresh_and_retained_handles_without_double_close(self):
        m, clock, api, lease = self.make()
        def cancel(*args):
            raise KeyboardInterrupt()
        api.read = cancel
        try:
            with self.assertRaises(KeyboardInterrupt):
                lease.verify()
        finally:
            self.assertTrue(lease.close())
        self.assertFalse(api.live); self.assertEqual(len(api.closed), len(set(api.closed)))


if __name__ == '__main__':
    unittest.main()
