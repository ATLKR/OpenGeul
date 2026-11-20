"""Reviewed input reads preserve Windows creation and change-time semantics."""
import contextlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import frontend_dependencies as frontend


class FrontendStatIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'synthetic-reviewed-input.json'
        self.raw = b'{"synthetic":true}\n'
        self.path.write_bytes(self.raw)

    @contextlib.contextmanager
    def windows_metadata(self, *, open_change=None, after_change=None, final_change=None,
                         missing_birth=False):
        path_stat, path_lstat, fd_stat = Path.stat, Path.lstat, os.fstat
        calls = 0

        def metadata(info, changes=None, *, handle=False):
            names = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_nlink')
            result = {name: getattr(info, name) for name in names}
            result.update(st_ctime_ns=2000 if handle else 1000, st_file_attributes=0)
            if not missing_birth:
                result['st_birthtime_ns'] = 1000
            result.update(changes or {})
            return SimpleNamespace(**result)

        def stat(path, *args, **kwargs):
            value = path_stat(path, *args, **kwargs)
            return metadata(value) if path == self.path else value

        def lstat(path, *args, **kwargs):
            value = path_lstat(path, *args, **kwargs)
            return metadata(value, final_change) if path == self.path else value

        def fstat(fd):
            nonlocal calls
            calls += 1
            return metadata(fd_stat(fd), open_change if calls == 1 else after_change, handle=True)

        with mock.patch.object(frontend.os, 'name', 'nt'), \
             mock.patch.object(Path, 'stat', stat), mock.patch.object(Path, 'lstat', lstat), \
             mock.patch.object(frontend.os, 'fstat', fstat):
            yield

    def test_same_file_with_distinct_windows_creation_and_change_times_is_read(self):
        with self.windows_metadata():
            try:
                result = frontend._read(self.path)
            except ValueError:
                self.fail('An unchanged file must allow distinct Windows creation and change times')
            self.assertEqual(result, self.raw)

    def test_windows_birth_time_is_required(self):
        with self.windows_metadata(missing_birth=True), self.assertRaises(ValueError):
            frontend._read(self.path)

    def test_open_handle_change_time_must_remain_stable(self):
        with self.windows_metadata(after_change={'st_ctime_ns': 2001}), self.assertRaises(ValueError):
            frontend._read(self.path)

    def test_path_change_time_must_remain_stable(self):
        with self.windows_metadata(final_change={'st_ctime_ns': 1001}), self.assertRaises(ValueError):
            frontend._read(self.path)

    def test_cross_api_identity_mismatches_are_rejected(self):
        info = self.path.stat()
        changes = {'st_dev': info.st_dev + 1, 'st_ino': info.st_ino + 1,
                   'st_size': info.st_size + 1, 'st_mtime_ns': info.st_mtime_ns + 1,
                   'st_nlink': 2, 'st_birthtime_ns': 1001}
        for name, value in changes.items():
            with self.subTest(field=name), self.windows_metadata(open_change={name: value}), \
                 self.assertRaises(ValueError):
                frontend._read(self.path)

    def test_handle_and_final_path_identity_must_remain_stable(self):
        info = self.path.stat()
        for field, value in {'st_ino': info.st_ino + 1, 'st_mtime_ns': info.st_mtime_ns + 1,
                             'st_birthtime_ns': 1001, 'st_nlink': 2}.items():
            for phase in ('after_change', 'final_change'):
                with self.subTest(field=field, phase=phase), \
                     self.windows_metadata(**{phase: {field: value}}), self.assertRaises(ValueError):
                    frontend._read(self.path)

    def test_actual_private_file_is_read_after_timestamp_update(self):
        os.utime(self.path, ns=(1600000000000000000, 1600000000000000000))
        self.assertEqual(frontend._read(self.path), self.raw)


if __name__ == '__main__':
    unittest.main()
