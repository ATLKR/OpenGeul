"""Test-only release of one completed native fixture image, never a directory retry."""
from pathlib import Path
import stat
import subprocess
import time


def remove_completed_image(root, executable, completed, *, clock=time.monotonic, sleep=time.sleep):
    root, executable = Path(root), Path(executable)
    assert root.is_absolute() and root.is_dir() and not root.is_symlink(), 'Owned fixture root required'
    assert executable.parent == root and executable.name not in ('', '.', '..'), 'Exact owned fixture image required'
    assert isinstance(completed, subprocess.CompletedProcess) and type(completed.returncode) is int, 'Completed child exit required'
    assert completed.args == [str(executable)], 'Completed child image differs'
    root_stat = root.lstat()
    root_identity = (root_stat.st_dev, root_stat.st_ino)

    def identity():
        directory = root.lstat()
        assert stat.S_ISDIR(directory.st_mode) and not getattr(directory, 'st_file_attributes', 0) & 0x400, 'Linked fixture root rejected'
        assert (directory.st_dev, directory.st_ino) == root_identity, 'Owned fixture root identity changed'
        value = executable.lstat()
        assert stat.S_ISREG(value.st_mode) and not getattr(value, 'st_file_attributes', 0) & 0x400, 'Linked fixture image rejected'
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    original = identity()
    deadline = clock() + 2.0
    last_denial = None
    for attempt in range(41):
        if attempt and clock() >= deadline:
            raise last_denial
        assert identity() == original, 'Completed fixture image identity changed'
        if attempt and clock() >= deadline:
            raise last_denial
        try:
            executable.unlink()
            return
        except PermissionError as error:
            # Windows may briefly retain the image section after confirmed process exit.
            # No chmod, broad rmtree retry, error suppression or retry on other errors.
            remaining = deadline - clock()
            if getattr(error, 'winerror', None) not in (5, 32) or remaining <= 0 or attempt == 40:
                raise
            last_denial = error
            sleep(min(0.05, remaining))
