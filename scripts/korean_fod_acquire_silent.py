"""Silent, source-pinned HWP prerequisite acquisition; never IME readiness."""
from __future__ import annotations
import os
import sys

HELPER_SHA256 = '50ee6a3939f5fb01507fbc405196d63e07fa5f846a022e9f35e847fd40b9ab35'


def _nul_handles():
    fd = os.open(os.devnull, os.O_RDWR)
    try:
        for target in (0, 1, 2):
            os.dup2(fd, target)
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            set_handle = ctypes.WinDLL('kernel32', use_last_error=True).SetStdHandle
            set_handle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
            set_handle.restype = wintypes.BOOL
            for code, target in ((-10, 0), (-11, 1), (-12, 2)):
                if not set_handle(code & 0xffffffff, msvcrt.get_osfhandle(target)):
                    raise OSError()
    finally:
        if fd > 2:
            os.close(fd)


def main(argv=None):
    try:
        _nul_handles()
        # No helper import or helper-controlled output precedes NUL custody.
        import hashlib
        import importlib.util
        from pathlib import Path
        args = sys.argv[1:] if argv is None else argv
        if len(args) != 2:
            return 1
        helper, output = (Path(value).absolute() for value in args)
        for path in (helper, output):
            for item in (path, *path.parents):
                if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                    return 1
        if not helper.is_file() or helper.stat().st_size > 65536:
            return 1
        if hashlib.sha256(helper.read_bytes()).hexdigest() != HELPER_SHA256:
            return 1
        spec = importlib.util.spec_from_file_location('_opengeul_hwp_fod_source', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.acquire(output)
        return 0 if type(result) is dict and result.get('success') is True else 1
    except BaseException:
        # Never inspect/format exception text, arguments, locals or environment.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
