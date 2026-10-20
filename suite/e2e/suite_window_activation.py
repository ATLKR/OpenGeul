"""One guarded physical activation of an original owned Suite caption.

The launch pointer precondition and editor input readiness are separate. This
helper neither clears desktop surfaces nor retries an activation input.
"""
from __future__ import annotations

import json
import ctypes as C
import math
from pathlib import Path
import re
import sys
import time


def caption_candidates(window, caption):
    """Derive bounded candidates from measured caption geometry, never chrome guesses."""
    for rectangle in (window, caption):
        assert len(rectangle) == 4 and all(type(v) is int for v in rectangle)
        assert rectangle[0] < rectangle[2] and rectangle[1] < rectangle[3], 'Empty caption geometry'
    left, top = max(window[0], caption[0]), max(window[1], caption[1])
    right, bottom = min(window[2], caption[2]), min(window[3], caption[3])
    assert left < right and top < bottom, 'No measured caption area'
    points = [(left + (right - left) * part // 4, top + (bottom - top) // 2) for part in (1, 2, 3)]
    # WM_NCHITTEST carries signed16 screen coordinates in LPARAM.
    assert all(-32768 <= value <= 32767 for point in points for value in point), 'Caption exceeds native hit-test range'
    return list(dict.fromkeys(points))


def _same_process(value, expected):
    assert value == expected, 'Original Suite process HANDLE/image/generation changed'


def _owned_window(value, hwnd, pid):
    assert (value['hwnd'], value['pid'], value['rootHwnd']) == (hwnd, pid, hwnd), 'Owned Suite window identity changed'
    assert value['threadId'] > 0 and value['visible'] is True and value['enabled'] is True
    assert value['cloaked'] == 0 and value['iconic'] is False, 'Owned Suite window is not physically available'
    rectangle = value['rectangle']
    assert len(rectangle) == 4 and rectangle[0] < rectangle[2] and rectangle[1] < rectangle[3]


def _caption_hit(value, hwnd, pid, point):
    return (value['point'] == list(point) and value['hitHwnd'] == value['rootHwnd'] == hwnd
            and value['pid'] == pid and value['hitTest'] == 2)  # HTCAPTION.


def activate_suite_window(require_foreground, process, hwnd, record, *, probe=None,
                          clock=time.monotonic, pause=time.sleep, seconds=5):
    """Retain intent before effects; one caption click followed only by observation."""
    assert type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 10
    started = clock(); deadline = started + seconds
    evidence = dict(schemaVersion=1, kind='owned-suite-window-activation', ready=False,
                    suiteHwnd=hwnd, shellPid=process.pid, startedAt=started, deadline=deadline,
                    clickAttempts=0, clickCompleted=False, pointerMoveAttempts=0,
                    requestedInputs=0, insertedInputs=None, inputCallAttempts=0,
                    inputCountBasis='native button call not attempted',
                    candidates=[], foregroundSamples=[], dpiScope={})
    record.setdefault('windowActivations', []).append(evidence)
    primary = None; output = stem = None

    def budget():
        assert clock() < deadline, 'Owned Suite activation deadline expired'

    def retain(phase):
        budget()
        path = output / (stem + '-' + phase + '.json')
        assert not path.exists() and not path.is_symlink(), 'Activation receipt already exists'
        raw = (json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
        assert len(raw) <= 128 * 1024, 'Activation receipt exceeds its finite bound'
        with path.open('xb') as stream: stream.write(raw)

    try:
        output = Path(process.opengeul_evidence_output)
        suite = Path(process.opengeul_suite_root)
        name = process.opengeul_evidence_case
        assert output.is_absolute() and output.is_dir() and suite.is_absolute()
        for part in (output, *output.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)()
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name)
        expected_image = str((suite / 'OpenGeul.Office.exe').resolve())
        assert isinstance(process.args, (list, tuple)) and str(Path(process.args[0]).resolve()) == expected_image
        assert type(process.pid) is int and process.pid > 0 and int(process._handle) > 0
        sequence = getattr(process, 'opengeul_activation_sequence', 0)
        assert type(sequence) is int and 0 <= sequence < 64, 'Owned Suite activation count exceeded'
        process.opengeul_activation_sequence = sequence + 1
        stem = name + '-window-activation-' + format(sequence, '03d')
        evidence['receiptStem'] = stem
        probe = probe if probe is not None else NativeActivationProbe(deadline, clock)
        budget(); probe.enter_dpi(evidence['dpiScope'])
        assert evidence['dpiScope']['verified'] is True
        budget(); original = probe.process_snapshot(process)
        assert (original['pid'], original['handleValue'], original['image'], original['waitResult']) == \
            (process.pid, int(process._handle), expected_image, 258), 'Original Suite Popen binding is invalid'
        assert type(original['creationTime']) is int and original['creationTime'] > 0
        binding = (original['pid'], original['handleValue'], original['image'], original['creationTime'], original['waitResult'])
        previous = getattr(process, 'opengeul_activation_binding', binding)
        assert previous == binding, 'Original Suite activation generation changed'
        process.opengeul_activation_binding = binding
        evidence['originalProcess'] = original

        def observe():
            budget(); _same_process(probe.process_snapshot(process), original)
            budget(); value = probe.window_snapshot(hwnd)
            _owned_window(value, hwnd, process.pid)
            return value

        before = observe(); evidence['windowBefore'] = before
        budget(); foreground = probe.foreground(); evidence['foregroundSamples'].append(foreground)
        if foreground != hwnd:
            budget(); caption = probe.caption(hwnd); evidence['caption'] = caption
            assert caption['state'] & (1 | 0x8000 | 0x10000) == 0, 'Caption is unavailable'
            selected = None
            for point in caption_candidates(before['rectangle'], caption['rectangle']):
                budget(); hit = probe.point_snapshot(hwnd, point); evidence['candidates'].append(hit)
                if _caption_hit(hit, hwnd, process.pid, point): selected = point; break
            assert selected is not None, 'No exposed owned caption point is available'
            assert observe() == before, 'Owned Suite geometry changed before activation'
            evidence['chosenPhysicalPoint'] = list(selected)
            evidence['pointerMoveIntent'] = True
            retain('pointer-intent')
            budget(); probe.move(selected, evidence)
            assert evidence['pointerReadback'] == list(selected), 'Physical caption pointer readback differs'
            assert observe() == before, 'Owned Suite geometry changed before caption input'
            budget(); hit = probe.point_snapshot(hwnd, selected); evidence['beforeClickHit'] = hit
            assert _caption_hit(hit, hwnd, process.pid, selected), 'Owned caption hit changed before input'
            evidence['clickAttempts'] = 1; evidence['requestedInputs'] = 2
            retain('click-intent')
            budget(); probe.click(evidence)
            assert evidence['clickCompleted'] is True and evidence['insertedInputs'] == 2
            while True:
                observe()
                budget(); foreground = probe.foreground(); evidence['foregroundSamples'].append(foreground)
                if foreground == hwnd: break
                assert len(evidence['foregroundSamples']) < 102 and clock() < deadline, 'Owned Suite foreground was not established'
                pause(min(.1, max(0, deadline - clock())))
                assert clock() < deadline, 'Owned Suite foreground was not established before deadline'
        observe(); budget(); require_foreground(hwnd)
        evidence['ready'] = True
    except BaseException as exc:
        primary = exc
        evidence.update(ready=False, error=type(exc).__name__ + ': ' + str(exc)[:1024])
        raise
    finally:
        if probe is not None and evidence['dpiScope'].get('previousContext'):
            try:
                probe.restore_dpi(evidence['dpiScope'])
                assert evidence['dpiScope']['restored'] is True
            except BaseException as exc:
                evidence['ready'] = False
                evidence['dpiRestoreError'] = type(exc).__name__ + ': ' + str(exc)[:1024]
                if primary is None: primary = exc
        evidence['finishedAt'] = clock()
        if evidence['ready'] and evidence['finishedAt'] > deadline:
            evidence.update(ready=False, error='Owned Suite activation completed after deadline')
            if primary is None: primary = AssertionError(evidence['error'])
        if output is not None and stem is not None:
            try:
                # Final retention must also run after an expired action budget.
                path = output / (stem + '-result.json')
                raw = (json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
                assert len(raw) <= 128 * 1024
                with path.open('xb') as stream: stream.write(raw)
            except BaseException as exc:
                evidence['ready'] = False
                evidence['retentionError'] = type(exc).__name__ + ': ' + str(exc)[:1024]
                if primary is None: primary = exc
        if primary is not None and not sys.exc_info()[0]: raise primary
    return evidence


class Point(C.Structure):
    _fields_ = [('x', C.c_int32), ('y', C.c_int32)]


class Rect(C.Structure):
    _fields_ = [('left', C.c_int32), ('top', C.c_int32), ('right', C.c_int32), ('bottom', C.c_int32)]


class TitleBarInfo(C.Structure):
    _fields_ = [('cbSize', C.c_uint32), ('rectangle', Rect), ('states', C.c_uint32 * 6)]


class FileTime(C.Structure):
    _fields_ = [('low', C.c_uint32), ('high', C.c_uint32)]


class MouseInput(C.Structure):
    _fields_ = [('dx', C.c_int32), ('dy', C.c_int32), ('mouseData', C.c_uint32),
                ('flags', C.c_uint32), ('time', C.c_uint32), ('extraInfo', C.c_size_t)]


class InputData(C.Union):
    _fields_ = [('mouse', MouseInput)]


class Input(C.Structure):
    _fields_ = [('type', C.c_uint32), ('data', InputData)]


def _rect(rectangle):
    return [int(getattr(rectangle, field)) for field in ('left', 'top', 'right', 'bottom')]


class NativeActivationProbe:
    """Bounded pointer-width-correct native calls; no focus-changing API."""
    def __init__(self, deadline, clock, *, user=None, kernel=None, dwm=None):
        assert C.sizeof(C.c_void_p) == 8, 'Owned activation requires the Windows64 ABI'
        self.deadline, self.clock = deadline, clock
        self.user = user if user is not None else C.WinDLL('user32', use_last_error=True)
        self.kernel = kernel if kernel is not None else C.WinDLL('kernel32', use_last_error=True)
        self.dwm = dwm if dwm is not None else C.WinDLL('dwmapi', use_last_error=True)
        H, D, B = C.c_void_p, C.c_uint32, C.c_int32
        signatures = {
            'IsWindow': ((H,), B), 'IsWindowVisible': ((H,), B), 'IsWindowEnabled': ((H,), B),
            'IsIconic': ((H,), B), 'GetAncestor': ((H, D), H), 'GetForegroundWindow': ((), H),
            'GetWindowThreadProcessId': ((H, C.POINTER(D)), D),
            'GetWindowRect': ((H, C.POINTER(Rect)), B), 'GetTitleBarInfo': ((H, C.POINTER(TitleBarInfo)), B),
            'WindowFromPhysicalPoint': ((Point,), H), 'SetPhysicalCursorPos': ((B, B), B),
            'GetPhysicalCursorPos': ((C.POINTER(Point),), B),
            'SetThreadDpiAwarenessContext': ((H,), H), 'GetThreadDpiAwarenessContext': ((), H),
            'AreDpiAwarenessContextsEqual': ((H, H), B),
            'SendMessageTimeoutW': ((H, D, C.c_size_t, C.c_ssize_t, D, D, C.POINTER(C.c_size_t)), C.c_ssize_t),
            'GetAsyncKeyState': ((C.c_int,), C.c_int16), 'GetSystemMetrics': ((C.c_int,), B),
            'SendInput': ((D, C.POINTER(Input), C.c_int), D),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name); function.argtypes, function.restype = args, result
        for name, args, result in (
            ('GetProcessId', (H,), D), ('WaitForSingleObject', (H, D), D),
            ('GetProcessTimes', (H, *(C.POINTER(FileTime),) * 4), B),
            ('QueryFullProcessImageNameW', (H, D, C.c_wchar_p, C.POINTER(D)), B),
        ):
            function = getattr(self.kernel, name); function.argtypes, function.restype = args, result
        self.dwm.DwmGetWindowAttribute.argtypes = (H, D, H, D)
        self.dwm.DwmGetWindowAttribute.restype = C.c_int32

    def _call(self, function, *args):
        assert self.clock() < self.deadline, 'Owned activation native query deadline expired'
        value = function(*args)
        assert self.clock() < self.deadline, 'Owned activation native query exceeded deadline'
        return value

    @staticmethod
    def _required(value, operation):
        if not value: raise OSError(getattr(C, 'get_last_error', lambda: 0)(), operation + ' failed')
        return value

    def enter_dpi(self, receipt):
        assert self.clock() < self.deadline, 'Owned activation DPI entry deadline expired'
        previous = self.user.SetThreadDpiAwarenessContext(-4)
        self._required(previous, 'SetThreadDpiAwarenessContext')
        receipt.update(requestedContext=-4, previousContext=int(previous), verified=False, restored=False)
        assert self.clock() < self.deadline, 'Owned activation DPI entry exceeded deadline'
        observed = self._call(self.user.GetThreadDpiAwarenessContext)
        receipt['observedContext'] = int(observed or 0)
        receipt['verified'] = bool(observed and self._call(self.user.AreDpiAwarenessContextsEqual, observed, -4))
        assert receipt['verified'], 'Physical DPI context was not verified'

    def restore_dpi(self, receipt):
        # Restoration is mandatory even if the input/query deadline expired.
        returned = self.user.SetThreadDpiAwarenessContext(receipt['previousContext'])
        observed = self.user.GetThreadDpiAwarenessContext()
        receipt.update(restoreReturnedContext=int(returned or 0), restoredContext=int(observed or 0),
                       restored=bool(returned and observed and self.user.AreDpiAwarenessContextsEqual(observed, receipt['previousContext'])))
        assert receipt['restored'], 'Restoring physical DPI context failed'

    def process_snapshot(self, process):
        handle = int(process._handle)
        pid = int(self._call(self.kernel.GetProcessId, handle))
        self._required(pid, 'GetProcessId(original Popen HANDLE)')
        wait = int(self._call(self.kernel.WaitForSingleObject, handle, 0))
        times = [FileTime() for _ in range(4)]
        self._required(self._call(self.kernel.GetProcessTimes, handle, *(C.byref(value) for value in times)), 'GetProcessTimes')
        size = C.c_uint32(4096); image = C.create_unicode_buffer(size.value)
        self._required(self._call(self.kernel.QueryFullProcessImageNameW, handle, 0, image, C.byref(size)), 'QueryFullProcessImageNameW')
        assert 0 < size.value < 4096 and image.value
        return dict(pid=pid, handleValue=handle, creationTime=(int(times[0].high) << 32) | int(times[0].low),
                    image=str(Path(image.value).resolve()), waitResult=wait)

    def window_snapshot(self, hwnd):
        self._required(self._call(self.user.IsWindow, hwnd), 'IsWindow')
        pid = C.c_uint32(); thread = int(self._call(self.user.GetWindowThreadProcessId, hwnd, C.byref(pid)))
        self._required(thread, 'GetWindowThreadProcessId')
        rectangle = Rect(); self._required(self._call(self.user.GetWindowRect, hwnd, C.byref(rectangle)), 'GetWindowRect')
        cloaked = C.c_uint32()
        hr = int(self._call(self.dwm.DwmGetWindowAttribute, hwnd, 14, C.byref(cloaked), C.sizeof(cloaked)))
        if hr != 0: raise OSError(hr, 'DwmGetWindowAttribute(CLOAKED) failed')
        return dict(hwnd=int(hwnd), pid=int(pid.value), threadId=thread,
                    rootHwnd=int(self._call(self.user.GetAncestor, hwnd, 2) or 0),
                    visible=bool(self._call(self.user.IsWindowVisible, hwnd)),
                    enabled=bool(self._call(self.user.IsWindowEnabled, hwnd)),
                    iconic=bool(self._call(self.user.IsIconic, hwnd)), cloaked=int(cloaked.value), rectangle=_rect(rectangle))

    def foreground(self):
        hwnd = self._call(self.user.GetForegroundWindow)
        return int(self._call(self.user.GetAncestor, hwnd, 2) or 0) if hwnd else 0

    def caption(self, hwnd):
        value = TitleBarInfo(cbSize=C.sizeof(TitleBarInfo))
        self._required(self._call(self.user.GetTitleBarInfo, hwnd, C.byref(value)), 'GetTitleBarInfo')
        return dict(rectangle=_rect(value.rectangle), state=int(value.states[0]))

    def point_snapshot(self, hwnd, point):
        hit = int(self._call(self.user.WindowFromPhysicalPoint, Point(*point)) or 0)
        root = int(self._call(self.user.GetAncestor, hit, 2) or 0) if hit else 0
        pid = C.c_uint32()
        if hit: self._required(self._call(self.user.GetWindowThreadProcessId, hit, C.byref(pid)), 'Physical hit identity')
        result = dict(point=list(point), hitHwnd=hit, rootHwnd=root, pid=int(pid.value), hitTest=None)
        if hit == root == hwnd:
            reply = C.c_size_t()
            packed = (point[0] & 0xffff) | ((point[1] & 0xffff) << 16)
            milliseconds = max(1, min(200, int((self.deadline - self.clock()) * 1000)))
            self._required(self._call(self.user.SendMessageTimeoutW, hwnd, 0x0084, 0, packed, 0x0003,
                                     milliseconds, C.byref(reply)), 'Bounded WM_NCHITTEST')
            result['hitTest'] = int(C.c_ssize_t(reply.value).value)
        return result

    def move(self, point, receipt):
        assert self.clock() < self.deadline, 'Physical caption pointer deadline expired'
        receipt['pointerMoveAttempts'] = 1
        receipt['pointerSetReturned'] = bool(self.user.SetPhysicalCursorPos(*point))
        self._required(receipt['pointerSetReturned'], 'SetPhysicalCursorPos')
        position = Point()
        self._required(self._call(self.user.GetPhysicalCursorPos, C.byref(position)), 'GetPhysicalCursorPos')
        receipt['pointerReadback'] = [int(position.x), int(position.y)]

    def click(self, receipt):
        receipt.update(clickCompleted=False, inputCallAttempts=0, insertedInputs=None,
                       inputCountBasis='native button call not attempted')
        assert not any(self._call(self.user.GetAsyncKeyState, key) & 0x8000 for key in (1, 2, 4, 5, 6)), 'A physical mouse button is already held'
        position = Point()
        self._required(self._call(self.user.GetPhysicalCursorPos, C.byref(position)), 'Before-click physical cursor')
        assert [int(position.x), int(position.y)] == receipt['chosenPhysicalPoint'], 'Physical cursor changed before caption click'
        swapped = bool(self._call(self.user.GetSystemMetrics, 23))
        down, up = (0x0008, 0x0010) if swapped else (0x0002, 0x0004)
        receipt.update(primaryButton='right' if swapped else 'left', requestedInputs=2)
        payload = (Input * 2)(Input(type=0, data=InputData(mouse=MouseInput(flags=down))),
                              Input(type=0, data=InputData(mouse=MouseInput(flags=up))))
        assert self.clock() < self.deadline, 'Owned caption input deadline expired'
        receipt['inputCallAttempts'] = 1
        receipt['inputCountBasis'] = 'native button call attempted; return unavailable'
        # One serial button down/up call; no wrapper focus method is reachable.
        inserted = int(self.user.SendInput(2, payload, C.sizeof(Input)))
        receipt.update(insertedInputs=inserted, inputCountBasis='SendInput return value', clickCompleted=inserted == 2)
        if inserted == 1:
            release = dict(requested=1, inserted=None); receipt['ownedButtonRelease'] = release
            prefix = (Input * 1)(Input(type=0, data=InputData(mouse=MouseInput(flags=up))))
            try: release['inserted'] = int(self.user.SendInput(1, prefix, C.sizeof(Input)))
            except BaseException as exc: release['error'] = type(exc).__name__ + ': ' + str(exc)[:1024]
        assert inserted == 2, 'Owned caption click had partial native insertion'
        assert self.clock() < self.deadline, 'Owned caption input completed after deadline'
