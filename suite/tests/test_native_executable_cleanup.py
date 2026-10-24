"""Post-exit cleanup is bounded and only admits the exact completed fixture image."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import native_executable_cleanup as cleanup


class NativeExecutableCleanupTests(unittest.TestCase):
    def test_scheduler_overshoot_never_retries_unlink_after_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); exe = root/'probe.exe'; exe.write_bytes(b'owned fixture')
            denied = PermissionError('original image release denial'); denied.winerror = 5
            times = [0.0]
            with patch.object(Path, 'unlink', side_effect=denied) as unlink:
                with self.assertRaises(PermissionError) as caught:
                    cleanup.remove_completed_image(root, exe, subprocess.CompletedProcess([str(exe)], 0),
                        clock=lambda: times[0], sleep=lambda seconds: times.__setitem__(0, 2.1))
                self.assertIs(caught.exception, denied)
                self.assertEqual(unlink.call_count, 1)

    def test_observed_windows_image_release_retries_only_exact_file_after_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); exe = root/'probe.exe'; exe.write_bytes(b'owned fixture')
            completed = subprocess.CompletedProcess([str(exe)], 0)
            denied = PermissionError('image release pending'); denied.winerror = 5
            unlink = Path.unlink; attempts = []; times = [0.0]
            def remove(path):
                attempts.append(path)
                if len(attempts) < 3: raise denied
                unlink(path)
            with patch.object(Path, 'unlink', remove):
                cleanup.remove_completed_image(root, exe, completed, clock=lambda: times[0],
                    sleep=lambda seconds: times.__setitem__(0, times[0]+seconds))
            self.assertEqual(attempts, [exe]*3)
            self.assertFalse(exe.exists())

    def test_persistent_denial_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); exe = root/'probe.exe'; exe.write_bytes(b'owned fixture')
            denied = PermissionError('persistent denial'); denied.winerror = 32
            times = [0.0]
            with patch.object(Path, 'unlink', side_effect=denied) as unlink:
                with self.assertRaises(PermissionError):
                    cleanup.remove_completed_image(root, exe, subprocess.CompletedProcess([str(exe)], 7),
                        clock=lambda: times[0], sleep=lambda seconds: times.__setitem__(0, times[0]+seconds))
            self.assertLessEqual(times[0], 2.01)
            self.assertLessEqual(unlink.call_count, 41)
            self.assertTrue(exe.exists())

    def test_no_retry_for_other_errors_or_unverified_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); exe = root/'probe.exe'; exe.write_bytes(b'owned fixture')
            for result in (subprocess.CompletedProcess([str(exe)], None), subprocess.CompletedProcess(['other.exe'], 0)):
                with patch.object(Path, 'unlink') as unlink:
                    with self.assertRaises(AssertionError): cleanup.remove_completed_image(root, exe, result)
                    unlink.assert_not_called()
            with patch.object(Path, 'unlink', side_effect=PermissionError('POSIX denial')) as unlink:
                with self.assertRaises(PermissionError):
                    cleanup.remove_completed_image(root, exe, subprocess.CompletedProcess([str(exe)], 0))
                self.assertEqual(unlink.call_count, 1)

    def test_replaced_image_is_rejected_before_second_unlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); exe = root/'probe.exe'; exe.write_bytes(b'owned fixture')
            replacement = root/'other.exe'; replacement.write_bytes(b'different fixture')
            denied = PermissionError('image release pending'); denied.winerror = 5
            def replace(seconds): replacement.replace(exe)
            with patch.object(Path, 'unlink', side_effect=denied) as unlink:
                with self.assertRaisesRegex(AssertionError, 'identity changed'):
                    cleanup.remove_completed_image(root, exe, subprocess.CompletedProcess([str(exe)], 0), sleep=replace)
                self.assertEqual(unlink.call_count, 1)


if __name__ == '__main__': unittest.main()
