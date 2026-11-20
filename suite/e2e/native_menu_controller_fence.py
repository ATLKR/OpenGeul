"""Opt-in failure fence for this native-menu controller's unretired callback.

The caller closes failure evidence and tries its existing owned cleanup first.
This fence supplies neither graceful cleanup nor process-exit proof. Even self
TerminateProcess may remain pending on I/O; the fallback can run DLL detach.
No other E2E caller enables the native callback through importing this module.
"""
from __future__ import annotations

import atexit
import ctypes
import os
import sys


EXIT_CODE = 86
_installed = None


class FenceUnavailable(RuntimeError):
    pass


class _ControllerFence:
    __slots__ = ('_pending', '_terminate', '_process', '_fallback')

    def __init__(self, pending, terminate, process, fallback):
        self._pending, self._terminate = pending, terminate
        self._process, self._fallback = process, fallback

    def finish(self):
        """Return only when this registry proves no unretired native capsule."""
        try:
            lease = self._pending()
            if lease is None:
                return
            pending = lease.pending
            if type(pending) is bool and not pending:
                return
        except BaseException:
            pass  # Unknown retirement must not open ordinary COM/Python teardown.
        try:
            self._terminate(self._process, EXIT_CODE)
        except BaseException:
            pass
        # Successful self-termination cannot return. Failure or any unexpected
        # return still avoids Python finalization. The bound CRT fallback does
        # not promise a wall-clock limit or DLL cleanup safety.
        self._fallback(EXIT_CODE)


def install(pending_msaa_hit, *, enabled=False):
    """Register once after comtypes import, before enabling this CLI's helper.

    No PID or externally supplied process handle is accepted. The pending hook
    belongs to the controller's explicitly enabled native callback registry.
    The caller retires a lease within its existing cleanup deadline; neither
    the explicit finish nor the atexit backup waits, releases COM, or writes.
    """
    global _installed
    if enabled is False:
        return None
    if enabled is not True:
        raise FenceUnavailable('Native menu controller fence requires explicit enable')
    if _installed is not None:
        if _installed._pending is pending_msaa_hit:
            return _installed
        raise FenceUnavailable('Native menu controller fence already belongs to another registry')
    comtypes = sys.modules.get('comtypes')
    if (os.name != 'nt' or not __debug__ or not callable(pending_msaa_hit)
            or comtypes is None or not callable(getattr(comtypes, '_shutdown', None))
            or getattr(getattr(comtypes, '__spec__', None), '_initializing', False)):
        raise FenceUnavailable('Native menu controller fence prerequisites are unavailable')
    try:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        current = kernel.GetCurrentProcess
        current.argtypes, current.restype = (), ctypes.c_void_p
        terminate = kernel.TerminateProcess
        terminate.argtypes, terminate.restype = (ctypes.c_void_p, ctypes.c_uint32), ctypes.c_int32
        process = current()
        if type(process) is not int or process == 0 or not callable(os._exit):
            raise FenceUnavailable()
        fence = _ControllerFence(pending_msaa_hit, terminate, process, os._exit)
        atexit.register(fence.finish)
    except BaseException:
        raise FenceUnavailable('Native menu controller fence installation failed') from None
    _installed = fence
    return fence
