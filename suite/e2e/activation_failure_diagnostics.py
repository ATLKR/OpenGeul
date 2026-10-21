"""Bounded failure-time native observations; never an activation/readiness gate.

The 0.5-second cooperative deadline stops queries, not mandatory HANDLE release.
No OS-call preemption or historical window/process identity is implied.
"""
from __future__ import annotations
import ctypes as C
import json
import os
import time

SECONDS = .5
MAX_BYTES = 16 * 1024
QUERY_ACCESS = 0x00101000  # PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE.


class Rect(C.Structure):
    _fields_ = [('left', C.c_int32), ('top', C.c_int32), ('right', C.c_int32), ('bottom', C.c_int32)]


class FileTime(C.Structure):
    _fields_ = [('low', C.c_uint32), ('high', C.c_uint32)]


class GuiThreadInfo(C.Structure):
    _fields_ = [('cbSize', C.c_uint32), ('flags', C.c_uint32),
                ('hwndActive', C.c_void_p), ('hwndFocus', C.c_void_p),
                ('hwndCapture', C.c_void_p), ('hwndMenuOwner', C.c_void_p),
                ('hwndMoveSize', C.c_void_p), ('hwndCaret', C.c_void_p), ('rcCaret', Rect)]


def _identity(value):
    result = {key: value[key] for key in ('hwnd', 'rootHwnd', 'pid', 'threadId', 'isWindow')}
    assert result['isWindow'] is True
    assert all(type(result[k]) is int and 0 < result[k] < 2**64 for k in ('hwnd', 'rootHwnd'))
    assert all(type(result[k]) is int and 0 < result[k] < 2**32 for k in ('pid', 'threadId'))
    return result


def collect_failure_diagnostics(suite_hwnd, shell_pid, owned_thread_id, last_foreign_root,
                                *, clock=time.monotonic, probe=None):
    """Observe at most current/last foreign roots and the original owned thread."""
    started = clock(); deadline = started + SECONDS
    result = dict(schemaVersion=1, kind='activation-failure-native-diagnostics',
        actionOutcomeUnaffected=True, startedAt=started, deadline=deadline, budgetSeconds=SECONDS,
        deadlineExpired=False, foreignWindows=[], guiThreads=[], errors=[],
        suiteHwnd=suite_hwnd, shellPid=shell_pid, ownedThreadId=owned_thread_id,
        lastObservedForeignRoot=last_foreign_root,
        identityLimit='Failure-time observations and newly admitted HANDLE generations cannot identify historical HWND samples or prove the earlier click recipient.',
        budgetLimit='Cooperative query deadline; no hard OS-call preemption. HANDLE release remains mandatory after expiry.')
    handles = {}; stopped = False

    def budget():
        nonlocal stopped
        if clock() >= deadline:
            stopped = True; result['deadlineExpired'] = True
            raise TimeoutError('Failure diagnostic observation deadline expired')

    def error(operation, exc):
        if len(result['errors']) < 16:
            try: message = str(exc)
            except BaseException: message = '<unprintable diagnostic exception>'
            result['errors'].append(dict(operation=operation[:64], error=(type(exc).__name__ + ': ' + message)[:160]))

    def query(operation, action):
        budget(); value = action(); budget(); return value

    try:
        budget(); probe = probe if probe is not None else NativeFailureProbe(deadline, clock)
        current = query('foreground', probe.foreground)
        result['foregroundNow'] = dict(rawHwnd=int(current['rawHwnd']), rootHwnd=int(current['rootHwnd']))
        roots = []
        for root in (current['rootHwnd'], last_foreign_root):
            if type(root) is int and 0 < root < 2**64 and root != suite_hwnd and root not in roots:
                roots.append(root)
        for root in roots[:2]:
            row = dict(hwnd=root, status='unavailable', processAssociation='unknown')
            result['foreignWindows'].append(row)
            try:
                first = _identity(query('window-identity', lambda: probe.identity(root)))
                assert first['hwnd'] == first['rootHwnd'] == root
                row.update(first); row['status'] = 'observed'; row['observedAt'] = clock()
                caption = query('window-caption', lambda: probe.caption(root))
                row.update(className=str(caption['className'])[:128], title=str(caption.get('title', ''))[:256],
                           titleState=str(caption.get('titleState', 'native-other-process-caption'))[:64])
            except TimeoutError: raise
            except Exception as exc: error('window-' + str(root), exc)
        tids = []
        for tid in [owned_thread_id, *(row.get('threadId') for row in result['foreignWindows'])]:
            if type(tid) is int and 0 < tid < 2**32 and tid not in tids: tids.append(tid)
        for tid in tids[:3]:
            try:
                native = query('gui-thread', lambda: probe.gui_thread(tid))
                row = {key: int(native[key]) for key in ('threadId', 'flags', 'hwndActive', 'hwndFocus',
                    'hwndCapture', 'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret')}
                assert row['threadId'] == tid
                row['flagsDecoded'] = dict(inMoveSize=bool(row['flags'] & 2), inMenuMode=bool(row['flags'] & 4),
                    systemMenuMode=bool(row['flags'] & 8), popupMenuMode=bool(row['flags'] & 16))
                result['guiThreads'].append(row)
            except TimeoutError: raise
            except Exception as exc: error('gui-thread-' + str(tid), exc)
        for row in result['foreignWindows']:
            if row['status'] != 'observed': continue
            pid = row['pid']
            try:
                if pid not in handles:
                    budget(); handle = probe.open_process(pid)
                    # Register a successfully returned HANDLE before checking time.
                    handles[pid] = dict(handleValue=handle, pid=pid, admittedAt=clock(), released=False,
                        requestedAccess=QUERY_ACCESS, admissionBasis='New failure-time observation only.')
                    row['process'] = handles[pid]
                    budget()
                    value = query('process-snapshot', lambda: probe.process(handle))
                    stored = handles[pid]
                    stored.update(creationTime=int(value['creationTime']), image=str(value['image'])[:512],
                        imageTruncated=len(str(value['image'])) > 512, waitResult=int(value['waitResult']),
                        observedPid=int(value['pid']))
                    assert value['handleValue'] == handle and value['pid'] == pid and 0 < stored['creationTime'] < 2**64
                    stored['liveGenerationObserved'] = stored['waitResult'] == 258
                row['process'] = handles[pid]
            except TimeoutError: raise
            except Exception as exc:
                if pid in handles: row['process'] = handles[pid]
                error('process-' + str(pid), exc)
            try:
                after = _identity(query('window-identity-after', lambda: probe.identity(row['hwnd'])))
                row['identityAfter'] = after
                if any(after[key] != row[key] for key in ('hwnd', 'rootHwnd', 'pid', 'threadId', 'isWindow')):
                    row['status'] = 'racy'
                elif row.get('process', {}).get('liveGenerationObserved'):
                    row['processAssociation'] = 'matches-window-at-diagnostic-samples'
            except TimeoutError: raise
            except Exception as exc: row['status'] = 'unavailable'; error('window-after-' + str(row['hwnd']), exc)
    except BaseException as exc:
        if isinstance(exc, TimeoutError):
            stopped = True; result['deadlineExpired'] = True
        error('collector', exc)
    finally:
        for stored in handles.values():
            try:
                stored['released'] = bool(probe.close_process(stored['handleValue']))
                if not stored['released']: error('close-handle', OSError('CloseHandle failed'))
            except BaseException as exc: error('close-handle', exc)
        result['finishedAt'] = clock()
        result['withinBudget'] = result['finishedAt'] < deadline and not stopped
        # This also covers expiry during mandatory release without further reads.
        result['deadlineExpired'] = result['deadlineExpired'] or result['finishedAt'] >= deadline
    raw = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        # A hostile/unusual native string cannot suppress the original failure receipt.
        result = {key: result[key] for key in ('schemaVersion', 'kind', 'startedAt', 'deadline', 'budgetSeconds',
            'finishedAt', 'withinBudget', 'deadlineExpired', 'actionOutcomeUnaffected', 'identityLimit', 'budgetLimit')}
        result.update(truncatedForSize=True, foreignWindows=[], guiThreads=[], errors=[])
    return result


class NativeFailureProbe:
    """Native read-only foreign metadata; query-only retained process witnesses."""
    def __init__(self, deadline, clock, *, user=None, kernel=None):
        assert C.sizeof(C.c_void_p) == 8 and C.sizeof(GuiThreadInfo) == 72
        self.deadline, self.clock = deadline, clock
        self.user = user if user is not None else C.WinDLL('user32', use_last_error=True)
        self.kernel = kernel if kernel is not None else C.WinDLL('kernel32', use_last_error=True)
        H, D, B = C.c_void_p, C.c_uint32, C.c_int32
        for name, args, result in (
            ('GetForegroundWindow', (), H), ('GetAncestor', (H, D), H), ('IsWindow', (H,), B),
            ('GetWindowThreadProcessId', (H, C.POINTER(D)), D),
            ('GetClassNameW', (H, C.c_wchar_p, C.c_int), C.c_int),
            ('GetWindowTextW', (H, C.c_wchar_p, C.c_int), C.c_int),
            ('GetGUIThreadInfo', (D, C.POINTER(GuiThreadInfo)), B)):
            function = getattr(self.user, name); function.argtypes, function.restype = args, result
        for name, args, result in (
            ('OpenProcess', (D, B, D), H), ('CloseHandle', (H,), B), ('GetProcessId', (H,), D),
            ('WaitForSingleObject', (H, D), D), ('GetProcessTimes', (H, *(C.POINTER(FileTime),) * 4), B),
            ('QueryFullProcessImageNameW', (H, D, C.c_wchar_p, C.POINTER(D)), B)):
            function = getattr(self.kernel, name); function.argtypes, function.restype = args, result

    def _call(self, function, *args):
        if self.clock() >= self.deadline: raise TimeoutError('Native diagnostic query deadline expired')
        value = function(*args)
        if self.clock() >= self.deadline: raise TimeoutError('Native diagnostic query exceeded deadline')
        return value

    @staticmethod
    def _required(value, operation):
        if not value: raise OSError(getattr(C, 'get_last_error', lambda: 0)(), operation + ' failed')
        return value

    def foreground(self):
        raw = int(self._call(self.user.GetForegroundWindow) or 0)
        return dict(rawHwnd=raw, rootHwnd=int(self._call(self.user.GetAncestor, raw, 2) or 0) if raw else 0)

    def identity(self, hwnd):
        self._required(self._call(self.user.IsWindow, hwnd), 'IsWindow(diagnostic)')
        pid = C.c_uint32(); tid = int(self._call(self.user.GetWindowThreadProcessId, hwnd, C.byref(pid)))
        self._required(tid, 'GetWindowThreadProcessId(diagnostic)')
        return dict(hwnd=hwnd, rootHwnd=int(self._call(self.user.GetAncestor, hwnd, 2) or 0),
                    pid=int(pid.value), threadId=tid, isWindow=True)

    def caption(self, hwnd):
        pid = C.c_uint32(); self._required(self._call(self.user.GetWindowThreadProcessId, hwnd, C.byref(pid)), 'Caption PID')
        caption = C.create_unicode_buffer(256); name = C.create_unicode_buffer(128)
        self._required(self._call(self.user.GetClassNameW, hwnd, name, len(name)), 'GetClassNameW(diagnostic)')
        if pid.value == os.getpid():
            return dict(className=name.value, title='', titleState='skipped-same-observer-process')
        # Foreign top-level caption retrieval does not send WM_GETTEXT to that process.
        self._call(self.user.GetWindowTextW, hwnd, caption, len(caption))
        return dict(className=name.value, title=caption.value, titleState='native-other-process-caption')

    def gui_thread(self, tid):
        value = GuiThreadInfo(cbSize=C.sizeof(GuiThreadInfo))
        self._required(self._call(self.user.GetGUIThreadInfo, tid, C.byref(value)), 'GetGUIThreadInfo(diagnostic)')
        return dict(threadId=tid, flags=int(value.flags), **{key: int(getattr(value, key) or 0) for key in
            ('hwndActive', 'hwndFocus', 'hwndCapture', 'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret')})

    def open_process(self, pid):
        if self.clock() >= self.deadline: raise TimeoutError('Diagnostic HANDLE admission deadline expired')
        # Return before checking elapsed time so the caller can always close it.
        return int(self._required(self.kernel.OpenProcess(QUERY_ACCESS, False, pid), 'OpenProcess(diagnostic)'))

    def process(self, handle):
        pid = int(self._call(self.kernel.GetProcessId, handle)); self._required(pid, 'GetProcessId(diagnostic)')
        wait = int(self._call(self.kernel.WaitForSingleObject, handle, 0))
        times = [FileTime() for _ in range(4)]
        self._required(self._call(self.kernel.GetProcessTimes, handle, *(C.byref(t) for t in times)), 'GetProcessTimes(diagnostic)')
        size = C.c_uint32(4096); image = C.create_unicode_buffer(size.value)
        self._required(self._call(self.kernel.QueryFullProcessImageNameW, handle, 0, image, C.byref(size)), 'QueryFullProcessImageNameW(diagnostic)')
        assert 0 < size.value < 4096 and image.value
        return dict(pid=pid, handleValue=handle, waitResult=wait, image=image.value,
            creationTime=(int(times[0].high) << 32) | int(times[0].low))

    def close_process(self, handle):
        # Mandatory release is outside the observation deadline.
        return bool(self.kernel.CloseHandle(handle))
