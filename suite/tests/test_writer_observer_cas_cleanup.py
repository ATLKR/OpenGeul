"""Exercise CAS fixture cleanup after confirmed exit and a transient image lock."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_writer_server_observer_capture import (
    mod, test_compare_exchange_export_old_value_with_fake_windows_primitive as exercise)


class CasFixtureCleanupTests(unittest.TestCase):
    def test_completed_cas_image_is_released_before_temporary_directory_cleanup(self):
        original_temp = tempfile.TemporaryDirectory
        original_run = subprocess.run
        original_unlink = os.unlink
        original_rmtree = shutil.rmtree
        temporary = []
        roots = {}
        completed = set()
        attempts = []

        def tracked_temp(*args, **kwargs):
            result = original_temp(*args, **kwargs)
            root = Path(result.name)
            info = root.stat()
            roots[root] = (info.st_dev, info.st_ino)
            temporary.append(result)
            return result

        def tracked_run(args, *positional, **kwargs):
            result = original_run(args, *positional, **kwargs)
            if len(args) == 1 and result.returncode == 0:
                image = Path(args[0])
                if not image.exists() and image.with_suffix('.exe').exists():
                    image = image.with_suffix('.exe')
                completed.add(image)
            return result

        def directory_cleanup(root, *args, **kwargs):
            for image in completed:
                if image.parent == Path(root):
                    self.assertFalse(image.exists(),
                        'Completed CAS image must be released before directory cleanup')
            return original_rmtree(root, *args, **kwargs)

        def delayed_unlink(path, *, dir_fd=None):
            path = Path(path)
            if dir_fd is None:
                image = path
            else:
                parent = os.fstat(dir_fd)
                matches = [root for root, identity in roots.items()
                           if identity == (parent.st_dev, parent.st_ino)]
                image = matches[0] / path if len(matches) == 1 else path
            if image in completed:
                info = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
                self.assertTrue(stat.S_ISREG(info.st_mode))
                self.assertIn(image.parent, roots)
                attempts.append(image)
                if len(attempts) < 3:
                    error = PermissionError('Synthetic completed-image release pending')
                    error.winerror = 5
                    raise error
            return original_unlink(path, dir_fd=dir_fd)

        try:
            with patch.object(tempfile, 'TemporaryDirectory', tracked_temp), \
                 patch.object(subprocess, 'run', tracked_run), patch.object(os, 'unlink', delayed_unlink), \
                 patch.object(shutil, 'rmtree', directory_cleanup):
                try:
                    exercise(mod(), '')
                except PermissionError:
                    self.fail('CAS fixture did not release its completed image before directory cleanup')
            self.assertEqual(len(attempts), 3)
            self.assertEqual(len(set(attempts)), 1)
            self.assertFalse(attempts[0].exists())
        finally:
            for result in reversed(temporary):
                result.cleanup()


if __name__ == '__main__':
    unittest.main()
