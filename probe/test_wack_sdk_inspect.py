import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import struct
import sys

spec = importlib.util.spec_from_file_location('sdk', Path(__file__).with_name('wack_sdk_inspect.py'))
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)


class SdkInspectionControls(unittest.TestCase):
    def context(self):
        env = dict(sdk.EXPECTED_ENV, GITHUB_RUN_ID='123')
        event = {'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}, 'inputs': None}
        return env, event

    def test_only_fixed_public_manual_attempt_one_context(self):
        env, event = self.context()
        sdk.context(env, event)
        for key, value in [('GITHUB_REF', 'refs/heads/main'), ('GITHUB_ACTOR', 'someone'), ('GITHUB_RUN_ATTEMPT', '2')]:
            changed = dict(env, **{key: value})
            with self.assertRaises(ValueError):
                sdk.context(changed, event)
        with self.assertRaises(ValueError):
            sdk.context(env, {'repository': {'full_name': 'ATLKR/OpenGeul', 'private': True}, 'inputs': None})

    def test_nonempty_or_wrong_typed_inputs_are_rejected(self):
        env, event = self.context()
        for value in [{}, None]:
            sdk.context(env, dict(event, inputs=value))
        for value in [False, 0, [], '', {'x': 'y'}]:
            with self.assertRaises(ValueError):
                sdk.context(env, dict(event, inputs=value))

    def test_real_fixture_bytes_inventory_hits_and_original_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'kit'; root.mkdir()
            raw = b'MZ\x00CreateProcessW\x00' + 'BlockedExecutables'.encode('utf-16le')
            (root / 'microsoft.windows.softwarelogo.tests.dll').write_bytes(raw)
            (root / 'notes.txt').write_text('read-only fixture')
            output = Path(temp) / 'out'
            result = sdk.collect(root, output)
            rows = {r['path']: r for r in result['files']}
            self.assertIn('microsoft.windows.softwarelogo.tests.dll', rows)
            self.assertEqual(rows['microsoft.windows.softwarelogo.tests.dll']['sha256'], sdk.sha(raw))
            self.assertEqual((output / 'originals/microsoft.windows.softwarelogo.tests.dll').read_bytes(), raw)
            self.assertEqual({h['term'] for h in rows['microsoft.windows.softwarelogo.tests.dll']['hits']}, {'CreateProcessW', 'BlockedExecutable', 'BlockedExecutables'})
            self.assertEqual(rows['notes.txt']['size'], len(b'read-only fixture'))
            self.assertFalse((output / 'originals/notes.txt').exists())
            self.assertFalse(result['sdkCodeExecuted'])

    def test_outside_path_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'kit'; root.mkdir()
            outside = Path(temp) / 'outside.dll'; outside.write_bytes(b'outside')
            with self.assertRaises(ValueError):
                sdk.read_file(outside, root, lambda: 0, 10)

    def test_symlink_does_not_read_outside_kit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'kit'; root.mkdir()
            outside = Path(temp) / 'outside.dll'; outside.write_bytes(b'outside')
            try:
                (root / 'alias.dll').symlink_to(outside)
            except OSError:
                self.skipTest('host cannot create fixture symlinks')
            with self.assertRaises(ValueError):
                sdk.collect(root, Path(temp) / 'out')
            self.assertFalse((Path(temp) / 'out/originals/alias.dll').exists())

    def test_time_limit_stops_before_inventory_or_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'kit'; root.mkdir()
            (root / 'sdk.dll').write_bytes(b'MZ')
            clock = iter([0, sdk.SECONDS_LIMIT + 1])
            output = Path(temp) / 'out'
            with self.assertRaises(ValueError):
                sdk.collect(root, output, clock=lambda: next(clock))
            self.assertFalse((output / 'inventory.json').exists())

    def test_oversize_file_and_existing_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'kit'; root.mkdir()
            with (root / 'large.dll').open('wb') as f:
                f.truncate(sdk.FILE_LIMIT + 1)
            with self.assertRaises(ValueError):
                sdk.collect(root, Path(temp) / 'out')
            with self.assertRaises(ValueError):
                sdk.collect(root, root)

    def test_failure_receipt_never_contains_exception_details(self):
        marker = 'private/path?token=not-a-token'
        result = sdk.failure(ValueError(marker))
        self.assertNotIn(marker, json.dumps(result))
        self.assertEqual(result['exceptionType'], 'ValueError')

    def test_static_managed_header_and_truncated_pe_do_not_execute(self):
        raw = bytearray(512); raw[:2] = b'MZ'
        struct.pack_into('<I', raw, 60, 128); raw[128:132] = b'PE\0\0'
        struct.pack_into('<HHIIIHH', raw, 132, 0x14c, 1, 0, 0, 0, 224, 0)
        struct.pack_into('<H', raw, 152, 0x10b)
        struct.pack_into('<I', raw, 152 + 92, 16)
        struct.pack_into('<II', raw, 152 + 96 + 14 * 8, 4096, 72)
        self.assertTrue(sdk.pe_headers(raw)['managedClrHeaderPresent'])
        self.assertFalse(sdk.pe_headers(raw[:160])['pe'])

    def test_bounded_passive_capture_keeps_exact_stdout(self):
        raw, result = sdk.capture([sys.executable, '-c', "import sys; sys.stdout.buffer.write(b'passive metadata\\n')"])
        self.assertEqual(raw, b'passive metadata\n')
        self.assertEqual(result['stdoutSha256'], sdk.sha(raw))

    def test_passive_capture_rejects_overflow_and_timeout(self):
        with self.assertRaises(ValueError):
            sdk.capture([sys.executable, '-c', "print('x'*100000)"], cap=64)
        with self.assertRaises(ValueError):
            sdk.capture([sys.executable, '-c', 'import time; time.sleep(2)'], seconds=0.05)


if __name__ == '__main__':
    unittest.main()
