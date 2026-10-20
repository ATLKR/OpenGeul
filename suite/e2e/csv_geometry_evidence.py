"""CI-only read-only geometry around the single CSV post-getter image read.

All Win32 queries run inside the existing finite capture child. This is an
observation receipt, never a paint, clipping, fit, or visible-grid certificate.
"""
import ctypes
import hashlib
import json
from pathlib import Path

from native_window_evidence import Point, Rect, AppBarData, _error, _rect_list

PNG_NAME = 'home-open-calc-csv-calc-post-getter.png'
SIDECAR_NAME = 'home-open-calc-csv-calc-post-getter-geometry.json'
MAX_JSON_BYTES = 64 * 1024


class MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint32), ('rcMonitor', Rect),
                ('rcWork', Rect), ('dwFlags', ctypes.c_uint32)]


class WindowPlacement(ctypes.Structure):
    _fields_ = [('length', ctypes.c_uint32), ('flags', ctypes.c_uint32),
                ('showCmd', ctypes.c_uint32), ('ptMinPosition', Point),
                ('ptMaxPosition', Point), ('rcNormalPosition', Rect)]


def _message(exc):
    return (type(exc).__name__ + ': ' + str(exc))[:512]


def receipt_bytes(receipt):
    raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + '\n').encode('utf-8')
    assert len(raw) <= MAX_JSON_BYTES, 'Geometry receipt exceeds 64KiB'
    return raw


def _unlinked(path):
    for item in (path, *path.parents):
        assert not item.is_symlink() and not getattr(item, 'is_junction', lambda: False)(), 'Linked geometry path'
        if item.exists():
            assert not getattr(item.stat(), 'st_file_attributes', 0) & 0x400, 'Reparse geometry path'


def _output_paths(path):
    path = Path(path)
    assert path.name == PNG_NAME and path.is_absolute(), 'Only the fixed CSV PNG is allowed'
    _unlinked(path)
    assert path.parent.is_dir() and not path.exists(), 'Never overwrite a capture PNG'
    sidecar = path.with_name(SIDECAR_NAME)
    _unlinked(sidecar)
    assert path.resolve().parent == path.parent.resolve() == sidecar.resolve().parent
    # Exclusive creation below rejects existing files (including hard-link aliases).
    return path, sidecar


class GeometryProbe:
    def __init__(self, user=None, shell=None):
        self.user = user if user is not None else ctypes.WinDLL('user32', use_last_error=True)
        self.shell = shell if shell is not None else ctypes.WinDLL('shell32', use_last_error=True)
        handle, boolean, uint = ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32
        signatures = {
            'SetThreadDpiAwarenessContext': ((handle,), handle),
            'GetThreadDpiAwarenessContext': ((), handle),
            'AreDpiAwarenessContextsEqual': ((handle, handle), boolean),
            'IsWindow': ((handle,), boolean), 'IsWindowVisible': ((handle,), boolean),
            'GetWindowThreadProcessId': ((handle, ctypes.POINTER(uint)), uint),
            'GetParent': ((handle,), handle), 'GetAncestor': ((handle, uint), handle),
            'IsChild': ((handle, handle), boolean),
            'GetPropW': ((handle, ctypes.c_wchar_p), handle),
            'GetWindowRect': ((handle, ctypes.POINTER(Rect)), boolean),
            'GetClientRect': ((handle, ctypes.POINTER(Rect)), boolean),
            'ClientToScreen': ((handle, ctypes.POINTER(Point)), boolean),
            'MonitorFromWindow': ((handle, uint), handle),
            'GetMonitorInfoW': ((handle, ctypes.POINTER(MonitorInfo)), boolean),
            'GetDpiForWindow': ((handle,), uint),
            'GetWindowPlacement': ((handle, ctypes.POINTER(WindowPlacement)), boolean),
            'GetPhysicalCursorPos': ((ctypes.POINTER(Point),), boolean),
            'FindWindowW': ((ctypes.c_wchar_p, ctypes.c_wchar_p), handle),
            'GetClassNameW': ((handle, ctypes.c_wchar_p, ctypes.c_int32), ctypes.c_int32),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.shell.SHAppBarMessage.argtypes = (uint, ctypes.POINTER(AppBarData))
        self.shell.SHAppBarMessage.restype = ctypes.c_size_t

    def enter(self, receipt):
        scope = receipt['dpiScope']
        previous = self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        if not previous:
            raise _error('SetThreadDpiAwarenessContext(PMv2)')
        scope['previousContext'] = int(previous)
        # Store the token before verification, so even a verification failure restores.
        self.previous = previous
        observed = self.user.GetThreadDpiAwarenessContext()
        scope['observedContext'] = int(observed or 0)
        assert observed and self.user.AreDpiAwarenessContextsEqual(observed, ctypes.c_void_p(-4)), 'PMv2 scope was not established'
        scope['verified'] = True

    def restore(self, receipt):
        scope = receipt['dpiScope']
        previous = getattr(self, 'previous', None)
        if previous is None:
            return
        returned = self.user.SetThreadDpiAwarenessContext(previous)
        scope['restoreReturnedContext'] = int(returned or 0)
        observed = self.user.GetThreadDpiAwarenessContext()
        scope['restoredContext'] = int(observed or 0)
        scope['restored'] = bool(returned and observed and self.user.AreDpiAwarenessContextsEqual(observed, previous))
        assert scope['restored'], 'Thread DPI context restoration failed'

    def identity(self, hwnd):
        assert self.user.IsWindow(hwnd), 'Expected HWND is no longer a window'
        pid = ctypes.c_uint32()
        tid = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not tid or not pid.value:
            raise _error('GetWindowThreadProcessId')
        root = self.user.GetAncestor(hwnd, 2)
        if not root:
            raise _error('GetAncestor(GA_ROOT)')
        return dict(pid=int(pid.value), tid=int(tid), parentHwnd=int(self.user.GetParent(hwnd) or 0), rootHwnd=int(root))

    def rect(self, hwnd, client=False):
        value = Rect()
        operation = 'GetClientRect' if client else 'GetWindowRect'
        if not getattr(self.user, operation)(hwnd, ctypes.byref(value)):
            raise _error(operation)
        return _rect_list(value)

    def client_screen(self, hwnd, rect):
        first, last = Point(*rect[:2]), Point(*rect[2:])
        for point in (first, last):
            if not self.user.ClientToScreen(hwnd, ctypes.byref(point)):
                raise _error('ClientToScreen')
        return [first.x, first.y, last.x, last.y]

    def monitor(self, hwnd):
        handle = self.user.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST, no desktop inference.
        if not handle:
            raise _error('MonitorFromWindow')
        info = MonitorInfo(); info.cbSize = ctypes.sizeof(info)
        if not self.user.GetMonitorInfoW(handle, ctypes.byref(info)):
            raise _error('GetMonitorInfoW')
        return dict(handle=int(handle), rect=_rect_list(info.rcMonitor), workRect=_rect_list(info.rcWork), flags=int(info.dwFlags))

    def placement(self, hwnd):
        value = WindowPlacement(); value.length = ctypes.sizeof(value)
        if not self.user.GetWindowPlacement(hwnd, ctypes.byref(value)):
            raise _error('GetWindowPlacement')
        return dict(flags=int(value.flags), showCmd=int(value.showCmd),
                    minPosition=[value.ptMinPosition.x, value.ptMinPosition.y],
                    maxPosition=[value.ptMaxPosition.x, value.ptMaxPosition.y], normalRect=_rect_list(value.rcNormalPosition))

    def window(self, hwnd, row):
        first = self.identity(hwnd); row.update(first)
        row['visible'] = bool(self.user.IsWindowVisible(hwnd))
        row['windowRect'] = self.rect(hwnd)
        row['clientRect'] = self.rect(hwnd, True)
        row['clientScreenRect'] = self.client_screen(hwnd, row['clientRect'])
        row['monitor'] = self.monitor(hwnd)
        row['dpi'] = int(self.user.GetDpiForWindow(hwnd))
        assert row['dpi'] > 0, 'GetDpiForWindow failed'
        row['placement'] = self.placement(hwnd)
        row['identityAfter'] = self.identity(hwnd)
        assert first == row['identityAfter'], 'Window identity/hierarchy raced during geometry query'
        # A changed rectangle invalidates a mixed-coordinate row, rather than
        # presenting it as a coherent geometry snapshot.
        assert row['windowRect'] == self.rect(hwnd) and row['clientRect'] == self.rect(hwnd, True), 'Window geometry raced during query'

    def snapshot(self, expected, snapshot):
        snapshot.update(complete=False, windows=[], errors=[])
        checks = ((expected['windowHwnd'], expected['shellPid'], 0, 'suite'),
                  (expected['parentHwnd'], expected['shellPid'], expected['windowHwnd'], 'host'),
                  (expected['childHwnd'], expected['officePid'], expected['parentHwnd'], 'child'))
        for hwnd, pid, parent, role in checks:
            row = dict(hwnd=hwnd, role=role, complete=False)
            snapshot['windows'].append(row)
            try:
                self.window(hwnd, row)
                assert row['pid'] == pid and row['parentHwnd'] == parent and row['rootHwnd'] == expected['windowHwnd'], 'Expected window PID/parent/root changed'
                row['complete'] = True
            except Exception as exc:
                row['error'] = _message(exc)
                snapshot['errors'].append(dict(field=role, error=_message(exc)))
        def observe(name, operation):
            try: snapshot[name] = operation()
            except Exception as exc: snapshot['errors'].append(dict(field=name, error=_message(exc)))
        def attachment():
            suite, host, child = (expected[key] for key in ('windowHwnd', 'parentHwnd', 'childHwnd'))
            actual = dict(parentHwnd=int(self.user.GetPropW(suite, 'OpenGeul.Office.ParentHwnd') or 0),
                          childHwnd=int(self.user.GetPropW(suite, 'OpenGeul.Office.ChildHwnd') or 0),
                          suiteContainsHost=bool(self.user.IsChild(suite, host)), hostContainsChild=bool(self.user.IsChild(host, child)))
            snapshot['attachment'] = actual
            assert actual == dict(parentHwnd=host, childHwnd=child, suiteContainsHost=True, hostContainsChild=True), 'Retained attachment mapping changed'
            return actual
        observe('attachment', attachment)
        def cursor():
            value = Point()
            if not self.user.GetPhysicalCursorPos(ctypes.byref(value)):
                raise _error('GetPhysicalCursorPos')
            return [value.x, value.y]
        observe('physicalCursor', cursor)
        def taskbar():
            hwnd = int(self.user.FindWindowW('Shell_TrayWnd', None) or 0)
            row = dict(hwnd=hwnd, complete=False); snapshot['taskbar'] = row
            assert hwnd, 'Primary Shell_TrayWnd missing'
            self.window(hwnd, row)
            buffer = ctypes.create_unicode_buffer(256)
            if not self.user.GetClassNameW(hwnd, buffer, len(buffer)):
                raise _error('GetClassNameW(Shell_TrayWnd)')
            row['className'] = buffer.value
            assert buffer.value == 'Shell_TrayWnd', 'Primary taskbar identity changed'
            data = AppBarData(); data.cbSize = ctypes.sizeof(data); data.hWnd = hwnd
            if not self.shell.SHAppBarMessage(5, ctypes.byref(data)):
                raise _error('SHAppBarMessage(ABM_GETTASKBARPOS)')
            row['appBarPosition'] = dict(hwnd=int(data.hWnd or 0), edge=int(data.uEdge), rect=_rect_list(data.rc))
            # ABM_GETSTATE returns flags; zero is a valid state, and this
            # message documents no separate GetLastError failure channel.
            state = int(self.shell.SHAppBarMessage(4, ctypes.byref(data)))
            row['appBarState'] = dict(raw=state, autoHide=bool(state & 1), alwaysOnTop=bool(state & 2))
            assert self.identity(hwnd) == row['identityAfter'] and int(self.user.FindWindowW('Shell_TrayWnd', None) or 0) == hwnd, 'Primary taskbar identity raced'
            row['complete'] = True
            return row
        observe('taskbar', taskbar)
        snapshot['complete'] = not snapshot['errors']
        assert snapshot['complete'], 'Required geometry snapshot is incomplete'


def _require_binding(expected):
    keys = ('shellPid', 'shellCreationTime', 'shellHandleValue', 'officePid', 'officeCreationTime',
            'officeHandleValue', 'windowHwnd', 'parentHwnd', 'childHwnd')
    assert set(expected) == set(keys) and all(type(expected[k]) is int and expected[k] > 0 for k in keys)
    assert all(expected[k] <= 0xFFFFFFFF for k in ('shellPid', 'officePid'))
    assert all(expected[k] <= 0xFFFFFFFFFFFFFFFF for k in keys if k not in ('shellPid', 'officePid'))
    assert expected['shellPid'] != expected['officePid']
    assert len({expected[k] for k in ('windowHwnd', 'parentHwnd', 'childHwnd')}) == 3


def capture_with_geometry(window, expected, path, probe=None):
    """Keep the exact default capture_as_image/save path and bytes, once only.

    The caller imports/initializes pywinauto before this function. Its DPI setup
    must finish before saving a thread scope token. The parent retains original
    process handles and checks their creation identities on both capture edges.
    """
    _require_binding(expected)
    path, sidecar = _output_paths(path)
    receipt = dict(schemaVersion=1, kind='owned-csv-post-getter-geometry', complete=False,
                   coordinateSystem='physical-screen-PMv2', expectedBinding=dict(expected),
                   coordinateNotes=dict(clientRect='client-local physical units',
                       windowPlacement='raw GetWindowPlacement coordinates; normalRect is workspace coordinates for top-level non-tool windows'),
                   captureConsistencyVerified=False,
                   captureCount=0, errors=[], cleanupErrors=[],
                   gridVisibleVerified=False, paintCompleteVerified=False, visualReviewRequired=True,
                   dpiScope=dict(requestedContext=-4, verified=False, restored=False))
    primary = cleanup = None
    # Reserve once before any native query; even a killed child leaves an
    # explicitly incomplete receipt. Never replace a pre-existing sidecar.
    with sidecar.open('xb') as stream:
        def retain():
            raw = receipt_bytes(receipt)
            stream.seek(0); stream.write(raw); stream.truncate(); stream.flush()
        retain()
        try:
            probe = probe if probe is not None else GeometryProbe()
            assert int(window.handle) == expected['windowHwnd'] and int(window.process_id()) == expected['shellPid']
            assert window.is_visible()
            probe.enter(receipt)
            receipt['nativeWrapperRectangle'] = None
            try:
                rectangle = window.rectangle()
                receipt['nativeWrapperRectangle'] = [int(getattr(rectangle, key)) for key in ('left', 'top', 'right', 'bottom')]
            except Exception as exc:
                receipt['nativeWrapperRectangleError'] = _message(exc)
            receipt['nativeWrapperRectangleSource'] = 'wrapper.rectangle query before capture; capture_as_image default rectangle remains unchanged'
            receipt['before'] = {}
            probe.snapshot(expected, receipt['before'])
            receipt['captureCount'] = 1
            image = window.capture_as_image()
            assert image is not None
            receipt['after'] = {}
            after_error = None
            try:
                probe.snapshot(expected, receipt['after'])
            except Exception as exc:
                after_error = exc
            try:
                # Retain the one original image even if post-read geometry fails.
                with path.open('xb') as image_stream:
                    image.save(image_stream, format='PNG')
                size = path.stat().st_size
                assert 0 < size <= 32 * 1024 * 1024
                receipt['png'] = dict(width=int(image.width), height=int(image.height), bytes=size,
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            except Exception as exc:
                if after_error is None: raise
                receipt['cleanupErrors'].append(dict(field='retainOriginalPng', error=_message(exc)))
            if after_error is not None: raise after_error
            before, after = receipt['before'], receipt['after']
            assert before['windows'] == after['windows'], 'Target geometry/identity changed across image read'
            assert before['attachment'] == after['attachment'], 'Attachment changed across image read'
            assert (before['taskbar']['hwnd'], before['taskbar']['identityAfter']) == (after['taskbar']['hwnd'], after['taskbar']['identityAfter']), 'Taskbar identity changed across image read'
            receipt['captureConsistencyVerified'] = True
            receipt['complete'] = True
        except Exception as exc:
            primary = exc
            receipt['errors'].append(dict(field='capture', error=_message(exc)))
        finally:
            try:
                if probe is not None: probe.restore(receipt)
            except Exception as exc:
                cleanup = exc
                receipt['cleanupErrors'].append(dict(field='dpiScope', error=_message(exc)))
            if primary is not None or cleanup is not None:
                receipt['complete'] = False
            try: retain()
            except Exception as exc:
                # Do not mask the primary capture or cleanup failure. The initial
                # bounded incomplete receipt remains if final serialization fails.
                if primary is None and cleanup is None: cleanup = exc
        if primary is not None: raise primary
        if cleanup is not None: raise cleanup
    return receipt


def _native_fields(value, fields):
    assert type(value) is dict and all(field in value for field in fields), 'Required native facts are missing'


def _native_int(value, *, bits=32, signed=False, positive=False):
    assert type(value) is int, 'Native integer must not be a bool or float'
    lower = -(1 << (bits - 1)) if signed else 0
    upper = (1 << (bits - int(signed))) - 1
    assert lower <= value <= upper and (not positive or value > 0), 'Native integer is outside its Win32 range'


def _native_coordinates(value, count):
    assert type(value) is list and len(value) == count, 'Native coordinate array has the wrong shape'
    for coordinate in value:
        _native_int(coordinate, signed=True)


def _native_identity(value):
    _native_fields(value, ('pid', 'tid', 'parentHwnd', 'rootHwnd'))
    for field in ('pid', 'tid'):
        _native_int(value[field], positive=True)
    pointer_bits = ctypes.sizeof(ctypes.c_void_p) * 8
    _native_int(value['parentHwnd'], bits=pointer_bits)
    _native_int(value['rootHwnd'], bits=pointer_bits, positive=True)


def _native_window(row):
    _native_fields(row, ('hwnd', 'complete', 'pid', 'tid', 'parentHwnd', 'rootHwnd', 'identityAfter',
                         'visible', 'windowRect', 'clientRect', 'clientScreenRect', 'monitor', 'dpi', 'placement'))
    assert row['complete'] is True and 'error' not in row
    _native_int(row['hwnd'], bits=ctypes.sizeof(ctypes.c_void_p) * 8, positive=True)
    _native_identity(row)
    _native_identity(row['identityAfter'])
    assert row['identityAfter'] == {field: row[field] for field in ('pid', 'tid', 'parentHwnd', 'rootHwnd')}, 'Native identity/hierarchy changed within a row'
    assert type(row['visible']) is bool
    for field in ('windowRect', 'clientRect', 'clientScreenRect'):
        _native_coordinates(row[field], 4)
    monitor = row['monitor']
    _native_fields(monitor, ('handle', 'rect', 'workRect', 'flags'))
    _native_int(monitor['handle'], bits=ctypes.sizeof(ctypes.c_void_p) * 8, positive=True)
    _native_int(monitor['flags'])
    for field in ('rect', 'workRect'):
        _native_coordinates(monitor[field], 4)
    _native_int(row['dpi'], positive=True)
    placement = row['placement']
    _native_fields(placement, ('flags', 'showCmd', 'minPosition', 'maxPosition', 'normalRect'))
    for field in ('flags', 'showCmd'):
        _native_int(placement[field])
    for field in ('minPosition', 'maxPosition'):
        _native_coordinates(placement[field], 2)
    _native_coordinates(placement['normalRect'], 4)


def _native_snapshot(snapshot, expected):
    _native_fields(snapshot, ('complete', 'errors', 'windows', 'attachment', 'physicalCursor', 'taskbar'))
    assert snapshot['complete'] is True and snapshot['errors'] == []
    windows = snapshot['windows']
    assert type(windows) is list and len(windows) == 3, 'Exactly three target windows are required'
    checks = ((expected['windowHwnd'], expected['shellPid'], 0, 'suite'),
              (expected['parentHwnd'], expected['shellPid'], expected['windowHwnd'], 'host'),
              (expected['childHwnd'], expected['officePid'], expected['parentHwnd'], 'child'))
    for row, (hwnd, pid, parent, role) in zip(windows, checks):
        _native_window(row)
        _native_fields(row, ('role',))
        assert (row['hwnd'], row['pid'], row['parentHwnd'], row['rootHwnd'], row['role']) == \
            (hwnd, pid, parent, expected['windowHwnd'], role), 'Native target binding or ancestry changed'
    attachment = snapshot['attachment']
    _native_fields(attachment, ('parentHwnd', 'childHwnd', 'suiteContainsHost', 'hostContainsChild'))
    for field in ('parentHwnd', 'childHwnd'):
        _native_int(attachment[field], bits=ctypes.sizeof(ctypes.c_void_p) * 8, positive=True)
        assert attachment[field] == expected[field]
    assert attachment['suiteContainsHost'] is True and attachment['hostContainsChild'] is True
    _native_coordinates(snapshot['physicalCursor'], 2)
    taskbar = snapshot['taskbar']
    _native_window(taskbar)
    _native_fields(taskbar, ('className', 'appBarPosition', 'appBarState'))
    assert taskbar['className'] == 'Shell_TrayWnd' and taskbar['hwnd'] not in {row['hwnd'] for row in windows}
    assert taskbar['parentHwnd'] == 0 and taskbar['rootHwnd'] == taskbar['hwnd'], 'Primary taskbar must be its own top-level root'
    position = taskbar['appBarPosition']
    _native_fields(position, ('hwnd', 'edge', 'rect'))
    _native_int(position['hwnd'], bits=ctypes.sizeof(ctypes.c_void_p) * 8, positive=True)
    assert position['hwnd'] == taskbar['hwnd']
    _native_int(position['edge'])
    assert position['edge'] <= 3
    _native_coordinates(position['rect'], 4)
    state = taskbar['appBarState']
    _native_fields(state, ('raw', 'autoHide', 'alwaysOnTop'))
    _native_int(state['raw'], bits=ctypes.sizeof(ctypes.c_void_p) * 8)
    assert type(state['autoHide']) is type(state['alwaysOnTop']) is bool
    assert state['autoHide'] == bool(state['raw'] & 1) and state['alwaysOnTop'] == bool(state['raw'] & 2)


def require_geometry_sidecar(png_path, expected, png):
    """Admit fresh required evidence without changing legacy checkpoint replay."""
    _require_binding(expected)
    png_path = Path(png_path)
    assert png_path.is_absolute() and png_path.name == PNG_NAME
    _unlinked(png_path)
    path = png_path.with_name(SIDECAR_NAME)
    _unlinked(path)
    assert path.is_file() and 0 < path.stat().st_size <= MAX_JSON_BYTES
    raw = path.read_bytes()
    assert len(raw) <= MAX_JSON_BYTES
    value = json.loads(raw)
    assert type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['kind'] == 'owned-csv-post-getter-geometry'
    assert value['complete'] is True and value['captureConsistencyVerified'] is True
    _require_binding(value['expectedBinding'])
    assert value['expectedBinding'] == expected and value['errors'] == value['cleanupErrors'] == []
    assert value['dpiScope']['verified'] is True and value['dpiScope']['restored'] is True
    assert type(value['captureCount']) is int and value['captureCount'] == 1
    assert value['coordinateSystem'] == 'physical-screen-PMv2'
    assert value['paintCompleteVerified'] is value['gridVisibleVerified'] is False and value['visualReviewRequired'] is True
    assert value['png'] == png
    for edge in ('before', 'after'):
        _native_snapshot(value[edge], expected)
    before, after = value['before'], value['after']
    assert before['windows'] == after['windows'], 'Native target geometry/identity changed across image read'
    assert before['attachment'] == after['attachment'], 'Native attachment changed across image read'
    assert (before['taskbar']['hwnd'], before['taskbar']['identityAfter']) == \
        (after['taskbar']['hwnd'], after['taskbar']['identityAfter']), 'Native taskbar identity changed across image read'
    return value
