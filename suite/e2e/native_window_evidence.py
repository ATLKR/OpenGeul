"""CI-only physical pointer preparation and read-only native window evidence.

No popup is exempted. Parking can reveal an auto-hide taskbar or its Explorer
tooltip; that desktop-state tradeoff is recorded, and the Office gate stays strict.
"""
import ctypes
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import traceback


POINTER_ACK_SECONDS = .25
POINTER_POLL_SECONDS = .01
MAX_POINTER_READBACKS = 26


class Point(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int32), ('y', ctypes.c_int32)]


class Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in ('left', 'top', 'right', 'bottom')]


class AppBarData(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint32), ('hWnd', ctypes.c_void_p),
                ('uCallbackMessage', ctypes.c_uint32), ('uEdge', ctypes.c_uint32),
                ('rc', Rect), ('lParam', ctypes.c_ssize_t)]


def _error(operation):
    return OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), operation + ' failed')


def _rect_list(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


class NativeWindowProbe:
    def __init__(self, user=None, shell=None, *, clock=time.monotonic, pause=time.sleep):
        self.clock, self.pause = clock, pause
        self.user = user if user is not None else ctypes.WinDLL('user32', use_last_error=True)
        self.shell = shell if shell is not None else ctypes.WinDLL('shell32', use_last_error=True)
        handle, boolean, dword = ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32
        signatures = {
            'SetThreadDpiAwarenessContext': ((handle,), handle),
            'GetThreadDpiAwarenessContext': ((), handle),
            'AreDpiAwarenessContextsEqual': ((handle, handle), boolean),
            'FindWindowW': ((ctypes.c_wchar_p, ctypes.c_wchar_p), handle),
            'GetPhysicalCursorPos': ((ctypes.POINTER(Point),), boolean),
            'SetPhysicalCursorPos': ((ctypes.c_int, ctypes.c_int), boolean),
            'WindowFromPhysicalPoint': ((Point,), handle),
            'GetWindowRect': ((handle, ctypes.POINTER(Rect)), boolean),
            'GetAncestor': ((handle, dword), handle),
            'GetWindow': ((handle, dword), handle),
            'GetWindowThreadProcessId': ((handle, ctypes.POINTER(dword)), dword),
            'GetClassNameW': ((handle, ctypes.c_wchar_p, ctypes.c_int), ctypes.c_int),
            'GetWindowTextW': ((handle, ctypes.c_wchar_p, ctypes.c_int), ctypes.c_int),
            'GetWindowLongPtrW': ((handle, ctypes.c_int), ctypes.c_ssize_t),
            'GetForegroundWindow': ((), handle),
            'IsWindow': ((handle,), boolean),
            'IsWindowVisible': ((handle,), boolean),
            'IsWindowEnabled': ((handle,), boolean),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.shell.SHAppBarMessage.argtypes = (dword, ctypes.POINTER(AppBarData))
        self.shell.SHAppBarMessage.restype = ctypes.c_size_t

    def _text(self, hwnd, class_name=False):
        buffer = ctypes.create_unicode_buffer(256 if class_name else 2048)
        function = self.user.GetClassNameW if class_name else self.user.GetWindowTextW
        getattr(ctypes, 'set_last_error', lambda value: None)(0)
        result = function(hwnd, buffer, len(buffer))
        if not result and (class_name or getattr(ctypes, 'get_last_error', lambda: 0)()):
            raise _error('GetClassNameW' if class_name else 'GetWindowTextW')
        return buffer.value

    def _identity(self, hwnd):
        pid = ctypes.c_uint32()
        tid = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not tid:
            raise _error('GetWindowThreadProcessId')
        return int(pid.value), int(tid)

    def _rect(self, hwnd):
        rect = Rect()
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise _error('GetWindowRect')
        return _rect_list(rect)

    def park_pointer(self, receipt, *, deadline=None):
        """Move once; observe acknowledgment without retrying the native move.

        No caller currently supplies a prelaunch deadline. The fixed 250ms
        post-return budget also covers fresh taskbar checks, final position and
        successful DPI restoration. An explicit earlier caller budget caps it.
        """
        started = self.clock()
        assert type(started) in (int, float) and math.isfinite(started)
        if deadline is not None:
            assert type(deadline) in (int, float) and math.isfinite(deadline) and started < deadline, 'Invalid or expired pointer deadline'
        active_deadline = deadline
        last_time = started
        receipt.update(startedAt=started, callerDeadline=deadline, pointerMoveAttempts=0,
                       physicalReadbacks=[], acknowledgmentSeconds=POINTER_ACK_SECONDS,
                       maxReadbackSamples=MAX_POINTER_READBACKS)

        def now():
            nonlocal last_time
            value = self.clock()
            assert type(value) in (int, float) and math.isfinite(value) and value >= last_time, 'Pointer clock changed'
            last_time = value
            return value

        def budget():
            observed = now()
            receipt.update(lastBudgetObservationAt=observed, activeDeadline=active_deadline)
            assert active_deadline is None or observed < active_deadline, 'Exact physical cursor acknowledgment deadline expired'
            return observed

        def position(phase, *, initial=False):
            row = dict(phase=phase, startedAt=budget(), nativeReturn=None, lastError=None, point=None)
            if initial:
                receipt['beforePhysicalQuery'] = row
            else:
                assert len(receipt['physicalReadbacks']) < MAX_POINTER_READBACKS, 'Physical cursor sample bound exceeded'
                receipt['physicalReadbacks'].append(row)
            point = Point()
            getattr(ctypes, 'set_last_error', lambda value: None)(0)
            try:
                returned = self.user.GetPhysicalCursorPos(ctypes.byref(point))
            except BaseException as exc:
                row.update(lastError=int(getattr(ctypes, 'get_last_error', lambda: 0)()),
                           finishedAt=now(), error=type(exc).__name__ + ': ' + str(exc))
                raise
            row.update(nativeReturn=int(returned), lastError=int(getattr(ctypes, 'get_last_error', lambda: 0)()),
                       bufferPoint=[point.x, point.y], finishedAt=now())
            if returned:
                row['point'] = [point.x, point.y]
                if not initial: receipt['readbackPhysicalPoint'] = row['point']
            else:
                row['error'] = 'GetPhysicalCursorPos failed'
                raise OSError(row['lastError'], row['error'])
            budget()  # A matching value returned after the deadline is not accepted.
            return row['point']

        primary = None
        budget()
        previous = self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PMv2.
        if not previous:
            raise _error('SetThreadDpiAwarenessContext')
        receipt.update(requestedDpiContext=-4, previousDpiContext=int(previous))
        try:
            taskbar = int(self.user.FindWindowW('Shell_TrayWnd', None) or 0)
            receipt['taskbarHwnd'] = taskbar
            assert taskbar and self.user.IsWindowVisible(taskbar), 'Visible primary system taskbar is required'
            receipt['taskbarClass'] = self._text(taskbar, True)
            assert receipt['taskbarClass'] == 'Shell_TrayWnd', 'System taskbar identity changed'
            receipt['taskbarPid'], receipt['taskbarTid'] = self._identity(taskbar)
            data = AppBarData()
            data.cbSize = ctypes.sizeof(data)
            if not self.shell.SHAppBarMessage(5, ctypes.byref(data)):  # ABM_GETTASKBARPOS.
                raise _error('SHAppBarMessage(ABM_GETTASKBARPOS)')
            bounds = _rect_list(data.rc)
            receipt['taskbarRect'] = bounds
            receipt['taskbarWindowRect'] = self._rect(taskbar)
            left, top, right, bottom = bounds
            assert left < right and top < bottom, 'System taskbar rectangle is empty'
            # One pixel inside the physical taskbar edge, independent of location.
            point = Point((left + right) // 2, bottom - 1) if right - left >= bottom - top \
                else Point(right - 1, (top + bottom) // 2)
            receipt['chosenPhysicalPoint'] = [point.x, point.y]
            receipt['beforePhysicalPoint'] = position('before-move', initial=True)
            move = receipt['pointerMove'] = dict(startedAt=budget(), nativeReturn=None, lastError=None)
            receipt['pointerMoveAttempts'] = 1
            getattr(ctypes, 'set_last_error', lambda value: None)(0)
            try:
                returned = self.user.SetPhysicalCursorPos(point.x, point.y)  # Exactly one native move.
            except BaseException as exc:
                move.update(lastError=int(getattr(ctypes, 'get_last_error', lambda: 0)()),
                            finishedAt=now(), error=type(exc).__name__ + ': ' + str(exc))
                raise
            move.update(nativeReturn=int(returned), lastError=int(getattr(ctypes, 'get_last_error', lambda: 0)()),
                        finishedAt=now())
            if not returned:
                raise OSError(move['lastError'], 'SetPhysicalCursorPos failed')
            budget()
            active_deadline = min(move['finishedAt'] + POINTER_ACK_SECONDS, deadline) if deadline is not None else move['finishedAt'] + POINTER_ACK_SECONDS
            receipt.update(acknowledgmentStartedAt=move['finishedAt'], readbackDeadline=active_deadline)
            # Reserve one of the 26 post-move samples for final confirmation.
            for index in range(MAX_POINTER_READBACKS - 1):
                observed = position('acknowledgment')
                if observed == receipt['chosenPhysicalPoint']:
                    receipt['acknowledgedAt'] = now()
                    break
                if index == MAX_POINTER_READBACKS - 2: break
                remaining = active_deadline - now()
                assert remaining > 0, 'Exact physical cursor readback failed before deadline'
                self.pause(min(POINTER_POLL_SECONDS, remaining))
            assert receipt['readbackPhysicalPoint'] == receipt['chosenPhysicalPoint'], 'Exact physical cursor readback failed'
            budget()
            fresh = receipt['freshTaskbar'] = dict(startedAt=now())
            fresh['hwnd'] = int(self.user.FindWindowW('Shell_TrayWnd', None) or 0)
            budget()
            assert fresh['hwnd'] == taskbar, 'Primary system taskbar changed'
            fresh['live'] = bool(self.user.IsWindow(taskbar))
            budget()
            fresh['visible'] = bool(self.user.IsWindowVisible(taskbar))
            budget()
            fresh['className'] = self._text(taskbar, True)
            budget()
            fresh['pid'], fresh['tid'] = self._identity(taskbar)
            budget()
            fresh['finishedAt'] = now()
            assert (fresh['live'] and fresh['visible'] and fresh['className'] == 'Shell_TrayWnd'
                    and (fresh['pid'], fresh['tid']) == (receipt['taskbarPid'], receipt['taskbarTid'])), 'System taskbar owner identity changed'
            hit = int(self.user.WindowFromPhysicalPoint(point) or 0)
            receipt['actualPointHwnd'] = hit
            budget()
            root = int(self.user.GetAncestor(hit, 2) or 0) if hit else 0  # GA_ROOT.
            receipt['actualRootHwnd'] = root
            budget()
            assert root == taskbar, 'Physical pointer is outside the verified taskbar'
            receipt['actualRootClass'] = self._text(root, True)
            budget()
            receipt['actualRootPid'], receipt['actualRootTid'] = self._identity(root)
            budget()
            assert (receipt['actualRootClass'] == 'Shell_TrayWnd' and
                    (receipt['actualRootPid'], receipt['actualRootTid']) == (receipt['taskbarPid'], receipt['taskbarTid'])), 'System taskbar process identity changed'
            assert position('final-confirmation') == receipt['chosenPhysicalPoint'], 'Final exact physical cursor readback failed'
            receipt['verifiedAt'] = budget()
        except BaseException as exc:
            primary = exc
            receipt['operationError'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            restore = receipt['dpiRestore'] = dict(startedAt=None, nativeReturn=None, lastError=None)
            restore_clock_error = None
            try:
                restore['startedAt'] = now()
            except BaseException as exc:
                # A broken clock must not prevent the mandatory native restore.
                restore_clock_error = exc
                restore['clockError'] = type(exc).__name__ + ': ' + str(exc)
            try:
                getattr(ctypes, 'set_last_error', lambda value: None)(0)
                restored = self.user.SetThreadDpiAwarenessContext(previous)
                restore.update(nativeReturn=int(restored or 0), lastError=int(getattr(ctypes, 'get_last_error', lambda: 0)()))
                receipt['restoreReturnedContext'] = int(restored or 0)
                observed = self.user.GetThreadDpiAwarenessContext()
                receipt['restoredDpiContext'] = int(observed or 0)
                receipt['dpiContextRestored'] = bool(restored and observed and
                    self.user.AreDpiAwarenessContextsEqual(observed, previous))
            except BaseException as exc:
                restore['error'] = type(exc).__name__ + ': ' + str(exc)
                raise
            finally:
                receipt['finishedAt'] = restore['finishedAt'] = now()
            if not receipt['dpiContextRestored']:
                raise _error('Restoring thread DPI context')
            if primary is None:
                if restore_clock_error is not None:
                    raise restore_clock_error
                budget()  # Cleanup can outlive failure, but cannot certify a late success.

    def _style(self, hwnd, offset):
        getattr(ctypes, 'set_last_error', lambda value: None)(0)
        value = self.user.GetWindowLongPtrW(hwnd, offset)
        if not value and getattr(ctypes, 'get_last_error', lambda: 0)():
            raise _error('GetWindowLongPtrW')
        return int(value) & 0xFFFFFFFF

    def _window(self, hwnd):
        row = {'hwnd': int(hwnd), 'queryErrors': []}
        def observe(name, operation):
            try:
                row[name] = operation()
            except Exception as exc:
                row[name] = None
                row['queryErrors'].append({'field': name, 'error': type(exc).__name__ + ': ' + str(exc)})
        observe('isWindow', lambda: bool(self.user.IsWindow(hwnd)))
        observe('pid', lambda: self._identity(hwnd)[0])
        observe('tid', lambda: self._identity(hwnd)[1])
        observe('title', lambda: self._text(hwnd))
        observe('className', lambda: self._text(hwnd, True))
        observe('visible', lambda: bool(self.user.IsWindowVisible(hwnd)))
        observe('enabled', lambda: bool(self.user.IsWindowEnabled(hwnd)))
        observe('rect', lambda: self._rect(hwnd))
        observe('style', lambda: self._style(hwnd, -16))
        observe('exStyle', lambda: self._style(hwnd, -20))
        observe('parentHwnd', lambda: int(self.user.GetAncestor(hwnd, 1) or 0))
        observe('ownerHwnd', lambda: int(self.user.GetWindow(hwnd, 4) or 0))
        observe('rootHwnd', lambda: int(self.user.GetAncestor(hwnd, 2) or 0))
        observe('rootOwnerHwnd', lambda: int(self.user.GetAncestor(hwnd, 3) or 0))
        return row

    def window_census(self, handles, office_pid):
        result = {'schemaVersion': 1, 'officePid': int(office_pid),
                  'utc': datetime.now(timezone.utc).isoformat(),
                  'enumeratedHwnds': [int(hwnd) for hwnd in handles], 'windows': []}
        try:
            result['foregroundHwnd'] = int(self.user.GetForegroundWindow() or 0)
        except Exception as exc:
            result['foregroundQueryError'] = type(exc).__name__ + ': ' + str(exc)
        for hwnd in handles[:256]:
            row = self._window(hwnd)
            row['ownerChain'] = []
            owner, seen = row.get('ownerHwnd'), {int(hwnd)}
            for _ in range(8):
                if not owner or owner in seen:
                    break
                seen.add(owner)
                node = self._window(owner)
                row['ownerChain'].append(node)
                owner = node.get('ownerHwnd')
            row['ownerChainIncomplete'] = bool(owner)
            result['windows'].append(row)
        result['omittedWindowCount'] = max(0, len(handles) - 256)
        return result


def prepare_launch_pointer(output, name, *, deadline=None):
    receipt = {'schemaVersion': 1, 'kind': 'physical-pointer-precondition',
               'success': False, 'utc': datetime.now(timezone.utc).isoformat()}
    try:
        NativeWindowProbe().park_pointer(receipt, deadline=deadline)
        receipt['success'] = True
    except Exception as exc:
        receipt.update(error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
        raise
    finally:
        with (Path(output) / (name + '-pointer.json')).open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return receipt
