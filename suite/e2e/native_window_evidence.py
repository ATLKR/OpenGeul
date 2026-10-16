"""CI-only physical pointer preparation and read-only native window evidence.

No popup is exempted. Parking can reveal an auto-hide taskbar or its Explorer
tooltip; that desktop-state tradeoff is recorded, and the Office gate stays strict.
"""
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import traceback


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
    def __init__(self, user=None, shell=None):
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

    def park_pointer(self, receipt):
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
            before = Point()
            if not self.user.GetPhysicalCursorPos(ctypes.byref(before)):
                raise _error('GetPhysicalCursorPos')
            receipt['beforePhysicalPoint'] = [before.x, before.y]
            if not self.user.SetPhysicalCursorPos(point.x, point.y):
                raise _error('SetPhysicalCursorPos')
            readback = Point()
            if not self.user.GetPhysicalCursorPos(ctypes.byref(readback)):
                raise _error('GetPhysicalCursorPos')
            receipt['readbackPhysicalPoint'] = [readback.x, readback.y]
            assert receipt['readbackPhysicalPoint'] == receipt['chosenPhysicalPoint'], 'Exact physical cursor readback failed'
            hit = int(self.user.WindowFromPhysicalPoint(point) or 0)
            receipt['actualPointHwnd'] = hit
            root = int(self.user.GetAncestor(hit, 2) or 0) if hit else 0  # GA_ROOT.
            receipt['actualRootHwnd'] = root
            assert root == taskbar and self._text(root, True) == 'Shell_TrayWnd', 'Physical pointer is outside the verified taskbar'
            assert self._identity(root)[0] == receipt['taskbarPid'], 'System taskbar process identity changed'
        finally:
            restored = self.user.SetThreadDpiAwarenessContext(previous)
            receipt['restoreReturnedContext'] = int(restored or 0)
            observed = self.user.GetThreadDpiAwarenessContext()
            receipt['restoredDpiContext'] = int(observed or 0)
            receipt['dpiContextRestored'] = bool(restored and observed and
                self.user.AreDpiAwarenessContextsEqual(observed, previous))
            if not receipt['dpiContextRestored']:
                raise _error('Restoring thread DPI context')

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


def prepare_launch_pointer(output, name):
    receipt = {'schemaVersion': 1, 'kind': 'physical-pointer-precondition',
               'success': False, 'utc': datetime.now(timezone.utc).isoformat()}
    try:
        NativeWindowProbe().park_pointer(receipt)
        receipt['success'] = True
    except Exception as exc:
        receipt.update(error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
        raise
    finally:
        with (Path(output) / (name + '-pointer.json')).open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return receipt
