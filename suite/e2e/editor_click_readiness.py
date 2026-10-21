"""One measured physical editor click inside the shared focus-entry deadline.

Foreground activation does not prove an editor point is exposed. Read-only
physical hit observations may wait for an occluder; no input is retried.
"""
from __future__ import annotations

import ctypes as C
import json
import math
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

from suite_window_activation import NativeActivationProbe, Point, Rect, Input

MAX_RECEIPT_BYTES = 128 * 1024
MAX_PREFLIGHT_ROWS = 102
DEADLINE_SCOPE = 'editor-setup-and-focus'


def _rectangle(value):
    assert isinstance(value, list) and len(value) == 4
    assert all(type(v) is int and -(2**31) <= v < 2**31 for v in value)
    assert value[0] < value[2] and value[1] < value[3], 'Empty physical editor rectangle'
    return value


def _inside(inner, outer):
    _rectangle(inner); _rectangle(outer)
    return outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]


def _frame_identity(frame, hwnd, parent, child, shell_pid, office_pid):
    suite, host, editor = (frame[key] for key in ('suite', 'parent', 'editor'))
    assert frame['parentWithinSuite'] is True and frame['editorWithinParent'] is True, 'Owned editor hierarchy changed'
    assert (suite['hwnd'], host['hwnd'], editor['hwnd']) == (hwnd, parent, child)
    assert (suite['pid'], host['pid'], editor['pid']) == (shell_pid, shell_pid, office_pid), 'Owned editor process changed'
    assert suite['cloaked'] == 0 and suite['iconic'] is False, 'Owned Suite is unavailable'
    assert all(row['rootHwnd'] == hwnd and row['visible'] is True and row['enabled'] is True
               and type(row['threadId']) is int and row['threadId'] > 0 for row in (suite, host, editor)), 'Owned editor window is unavailable'
    assert suite['threadId'] == host['threadId'], 'Owned host thread changed'
    assert _inside(host['clientScreenRect'], host['rectangle']), 'Owned host client geometry escaped its window'
    assert _inside(host['rectangle'], suite['rectangle']) and _inside(editor['rectangle'], host['clientScreenRect']), 'Owned editor geometry escaped its host'
    assert _inside(editor['clientScreenRect'], editor['rectangle']), 'Owned editor client geometry escaped its window'
    return tuple((row['hwnd'], row['pid'], row['threadId'], row['rootHwnd']) for row in (suite, host, editor))


def _hit_ready(hit, hwnd, child, office_pid, thread, point):
    assert hit['point'] == list(point) and type(hit['hitHwnd']) is int and hit['hitHwnd'] > 0
    assert type(hit['pid']) is int and hit['pid'] > 0 and type(hit['threadId']) is int and hit['threadId'] > 0
    if hit['withinEditor']:
        assert hit['withinEditor'] is True and hit['rootHwnd'] == hwnd and hit['pid'] == office_pid
        assert hit['threadId'] == thread and hit['visible'] is True and hit['enabled'] is True, 'Owned editor hit is unavailable'
        return True
    # A positive foreign/non-editor hit is pending only while the caller keeps
    # revalidating its original process/window identities and foreground.
    assert hit['withinEditor'] is False and hit['hitHwnd'] != child
    return False


def click_editor_once(require_foreground, process, hwnd, parent, child, office_pid, record,
                      *, probe=None, clock=time.monotonic, pause=time.sleep):
    """The single editor setup click; shares prepare_editor_focus's entry budget."""
    evidence = dict(schemaVersion=1, kind='owned-editor-physical-click', ready=False,
        suiteHwnd=hwnd, parentHwnd=parent, childHwnd=child, shellPid=process.pid,
        officePid=office_pid, clickAttempts=0, clickCompleted=False, pointerMoveAttempts=0,
        requestedInputs=0, insertedInputs=None, inputCallAttempts=0,
        inputCountBasis='native button call not attempted', dpiScope={}, preflight=[],
        engineHandleReleased=False,
        inputDeliveryLimit='SendInput insertion is not an atomic routing acknowledgement; strict post-Ctrl+F6 native focus remains mandatory.')
    record.setdefault('editorClicks', []).append(evidence)
    primary = None; handle = None; output = stem = None; deadline = None

    def budget():
        assert clock() < deadline, 'Owned editor shared entry deadline expired'

    def retain(phase):
        budget()
        raw = (json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
        assert len(raw) <= MAX_RECEIPT_BYTES, 'Owned editor click receipt exceeds finite limit'
        with (output / (stem + '-' + phase + '.json')).open('xb') as stream: stream.write(raw)

    try:
        focus = record['editorFocusReadiness']
        assert focus['schemaVersion'] == 1 and focus['kind'] == 'owned-editor-focus-readiness'
        assert focus['ready'] is False and focus['clickAttempts'] == 1 and focus['clickCompleted'] is False
        assert (focus['suiteHwnd'], focus['childHwnd'], focus['shellPid'], focus['officePid']) == (hwnd, child, process.pid, office_pid)
        assert focus['deadlineScope'] == DEADLINE_SCOPE, 'Editor callback has no shared entry deadline'
        started, deadline, seconds = (focus[key] for key in ('startedAt', 'deadline', 'deadlineSeconds'))
        assert all(type(v) in (int, float) and math.isfinite(v) for v in (started, deadline, seconds))
        assert 0 < seconds <= 10 and deadline == started + seconds
        assert started <= clock() < deadline, 'Owned editor callback entry deadline expired'
        evidence.update(startedAt=clock(), deadline=deadline, deadlineScope=DEADLINE_SCOPE,
                        sharedFocusStartedAt=started, sharedDeadlineSeconds=seconds)
        output = Path(process.opengeul_evidence_output); suite = Path(process.opengeul_suite_root)
        assert output.is_absolute() and output.is_dir() and suite.is_absolute()
        for part in (output, *output.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)()
        name = process.opengeul_evidence_case
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name)
        expected_shell = str((suite / 'OpenGeul.Office.exe').resolve())
        expected_engine = str((suite / 'Office/program/soffice.bin').resolve())
        assert isinstance(process.args, (list, tuple)) and str(Path(process.args[0]).resolve()) == expected_shell
        assert type(process.pid) is int and process.pid > 0 and int(process._handle) > 0
        assert type(office_pid) is int and office_pid > 0
        sequence = getattr(process, 'opengeul_editor_click_sequence', 0)
        assert type(sequence) is int and 0 <= sequence < 64, 'Owned editor click count exceeded'
        process.opengeul_editor_click_sequence = sequence + 1
        stem = name + '-editor-click-' + format(sequence, '03d'); evidence['receiptStem'] = stem
        probe = probe if probe is not None else NativeEditorClickProbe(deadline, clock)
        budget(); probe.enter_dpi(evidence['dpiScope']); assert evidence['dpiScope']['verified'] is True
        budget(); shell = probe.process_snapshot(process)
        shell_binding = tuple(shell[key] for key in ('pid', 'handleValue', 'image', 'creationTime', 'waitResult'))
        assert shell_binding == process.opengeul_activation_binding, 'Original Suite activation generation changed'
        assert (shell['pid'], shell['handleValue'], shell['image'], shell['waitResult']) == (process.pid, int(process._handle), expected_shell, 258)
        assert type(shell['creationTime']) is int and shell['creationTime'] > 0
        evidence['originalShell'] = shell
        budget(); initial = probe.editor_snapshot(hwnd, parent, child)
        identity = _frame_identity(initial, hwnd, parent, child, process.pid, office_pid)
        evidence['initialFrame'] = initial
        budget(); handle = probe.open_engine(office_pid)
        evidence['engineHandleValue'] = handle; evidence['engineHandleAdmittedAt'] = clock()
        evidence['engineAdmissionBasis'] = 'New retained HANDLE admitted for this pre-click observation; not a backdated launch identity.'
        budget(); engine = probe.engine_snapshot(handle)
        assert (engine['pid'], engine['handleValue'], engine['image'], engine['waitResult']) == (office_pid, handle, expected_engine, 258), 'Owned engine process binding changed'
        assert type(engine['creationTime']) is int and engine['creationTime'] > 0, 'Owned engine generation is invalid'
        assert engine['creationTime'] >= shell['creationTime'], 'Owned engine generation predates the original Suite'
        key = (parent, child, office_pid)
        generations = getattr(process, 'opengeul_editor_click_generations', {})
        engine_generation = (engine['pid'], engine['image'], engine['creationTime'])
        assert generations.get(key, engine_generation) == engine_generation, 'Owned editor engine generation changed'
        generations[key] = engine_generation; process.opengeul_editor_click_generations = generations
        evidence['originalEngine'] = engine

        def observe():
            budget(); assert probe.process_snapshot(process) == shell, 'Original Suite generation changed'
            budget(); assert probe.engine_snapshot(handle) == engine, 'Owned engine generation changed'
            budget(); frame = probe.editor_snapshot(hwnd, parent, child)
            assert _frame_identity(frame, hwnd, parent, child, process.pid, office_pid) == identity, 'Owned editor window identity changed'
            budget(); assert probe.foreground() == hwnd, 'Owned editor foreground changed'
            budget(); require_foreground(hwnd)
            return frame

        while True:
            frame = observe(); rectangle = frame['editor']['clientScreenRect']
            point = ((rectangle[0] + rectangle[2]) // 2, (rectangle[1] + rectangle[3]) // 2)
            budget(); hit = probe.editor_hit(child, point)
            row = dict(elapsedSeconds=clock() - started, point=list(point), hit=hit,
                shellProcess=[shell[k] for k in ('pid', 'handleValue', 'creationTime', 'waitResult')],
                engineProcess=[engine[k] for k in ('pid', 'handleValue', 'creationTime', 'waitResult')],
                originalImagesRevalidated=True,
                geometry={key: frame[key]['rectangle'] for key in ('suite', 'parent', 'editor')},
                editorClientScreenRect=rectangle)
            assert len(evidence['preflight']) < MAX_PREFLIGHT_ROWS, 'Owned editor preflight history exceeded'
            evidence['preflight'].append(row)
            if _hit_ready(hit, hwnd, child, office_pid, identity[2][2], point): break
            budget(); pause(min(.05, max(0, deadline - clock())))
        evidence['chosenPhysicalPoint'] = list(point); evidence['qualifiedHit'] = hit
        evidence['qualifiedFrame'] = frame
        assert observe() == frame, 'Owned editor geometry changed before pointer intent'
        evidence['pointerMoveIntent'] = True; retain('pointer-intent')
        budget(); probe.move(point, evidence)
        assert evidence['pointerReadback'] == list(point), 'Physical editor pointer readback differs'
        assert observe() == frame, 'Owned editor geometry changed after pointer move'
        budget(); fresh = probe.editor_hit(child, point); evidence['beforeClickHit'] = fresh
        assert fresh == hit and _hit_ready(fresh, hwnd, child, office_pid, identity[2][2], point), 'Owned editor hit changed after pointer move'
        # Recheck both process generations and geometry after the physical hit.
        assert observe() == frame, 'Owned editor geometry changed before button input'
        evidence['clickAttempts'] = 1; evidence['requestedInputs'] = 2; retain('click-intent')
        budget(); probe.click(evidence)
        assert evidence['clickCompleted'] is True and evidence['insertedInputs'] == 2
        observe(); budget(); evidence['ready'] = True
    except BaseException as exc:
        primary = exc; evidence.update(ready=False, error=type(exc).__name__ + ': ' + str(exc)[:1024])
        raise
    finally:
        if handle is not None:
            try: probe.close_engine(handle, evidence)
            except BaseException as exc:
                pending = getattr(process, 'opengeul_editor_click_pending_handles', {})
                pending[handle] = probe; process.opengeul_editor_click_pending_handles = pending
                evidence.update(ready=False, engineHandleCloseError=type(exc).__name__ + ': ' + str(exc)[:1024])
                if primary is None: primary = exc
        if probe is not None and evidence['dpiScope'].get('previousContext'):
            try: probe.restore_dpi(evidence['dpiScope']); assert evidence['dpiScope']['restored'] is True
            except BaseException as exc:
                evidence.update(ready=False, dpiRestoreError=type(exc).__name__ + ': ' + str(exc)[:1024])
                if primary is None: primary = exc
        evidence['finishedAt'] = clock()
        if evidence['ready'] and evidence['finishedAt'] > deadline:
            evidence.update(ready=False, error='Owned editor click completed after shared deadline')
            if primary is None: primary = AssertionError(evidence['error'])
        if output is not None and stem is not None:
            try:
                raw = (json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
                assert len(raw) <= MAX_RECEIPT_BYTES, 'Owned editor click receipt exceeds finite limit'
                with (output / (stem + '-result.json')).open('xb') as stream: stream.write(raw)
            except BaseException as exc:
                evidence.update(ready=False, retentionError=type(exc).__name__ + ': ' + str(exc)[:1024])
                if primary is None: primary = exc
        if primary is not None and not sys.exc_info()[0]: raise primary
    return evidence


class NativeEditorClickProbe(NativeActivationProbe):
    """Retained engine HANDLE and physical child hit; no focus-changing API."""
    def __init__(self, deadline, clock, *, user=None, kernel=None, dwm=None):
        super().__init__(deadline, clock, user=user, kernel=kernel, dwm=dwm)
        H, B = C.c_void_p, C.c_int32
        for name, args, result in (
            ('IsChild', (H, H), B), ('GetClientRect', (H, C.POINTER(Rect)), B),
            ('ClientToScreen', (H, C.POINTER(Point)), B)):
            fn = getattr(self.user, name); fn.argtypes, fn.restype = args, result
        self.kernel.OpenProcess.argtypes = (C.c_uint32, B, C.c_uint32)
        self.kernel.OpenProcess.restype = H
        self.kernel.CloseHandle.argtypes = (H,); self.kernel.CloseHandle.restype = B

    def open_engine(self, pid):
        assert self.clock() < self.deadline, 'Engine HANDLE admission deadline expired'
        # Return the admitted handle before the policy's next budget check, so
        # a slow successful OpenProcess is still closed by its finally block.
        return int(self._required(self.kernel.OpenProcess(0x00101000, False, pid), 'OpenProcess(owned editor)'))

    def engine_snapshot(self, handle):
        return self.process_snapshot(SimpleNamespace(_handle=handle))

    def close_engine(self, handle, receipt):
        # HANDLE release remains mandatory after the shared deadline expires.
        receipt['engineHandleReleased'] = bool(self.kernel.CloseHandle(handle))
        self._required(receipt['engineHandleReleased'], 'CloseHandle(owned editor)')

    def _child_window(self, hwnd):
        self._required(self._call(self.user.IsWindow, hwnd), 'IsWindow(owned editor)')
        pid = C.c_uint32(); thread = int(self._call(self.user.GetWindowThreadProcessId, hwnd, C.byref(pid)))
        self._required(thread, 'GetWindowThreadProcessId(owned editor)')
        rect = Rect(); self._required(self._call(self.user.GetWindowRect, hwnd, C.byref(rect)), 'GetWindowRect(owned editor)')
        client = Rect(); self._required(self._call(self.user.GetClientRect, hwnd, C.byref(client)), 'GetClientRect(owned editor)')
        first, last = Point(client.left, client.top), Point(client.right, client.bottom)
        self._required(self._call(self.user.ClientToScreen, hwnd, C.byref(first)), 'ClientToScreen(first editor corner)')
        self._required(self._call(self.user.ClientToScreen, hwnd, C.byref(last)), 'ClientToScreen(last editor corner)')
        return dict(hwnd=int(hwnd), pid=int(pid.value), threadId=thread,
            rootHwnd=int(self._call(self.user.GetAncestor, hwnd, 2) or 0),
            visible=bool(self._call(self.user.IsWindowVisible, hwnd)), enabled=bool(self._call(self.user.IsWindowEnabled, hwnd)),
            rectangle=[rect.left, rect.top, rect.right, rect.bottom],
            clientScreenRect=[first.x, first.y, last.x, last.y])

    def editor_snapshot(self, hwnd, parent, child):
        return dict(suite=self.window_snapshot(hwnd), parent=self._child_window(parent), editor=self._child_window(child),
            parentWithinSuite=bool(self._call(self.user.IsChild, hwnd, parent)),
            editorWithinParent=bool(self._call(self.user.IsChild, parent, child)))

    def editor_hit(self, child, point):
        hit = int(self._call(self.user.WindowFromPhysicalPoint, Point(*point)) or 0)
        self._required(hit, 'WindowFromPhysicalPoint(editor)')
        pid = C.c_uint32(); thread = int(self._call(self.user.GetWindowThreadProcessId, hit, C.byref(pid)))
        self._required(thread, 'GetWindowThreadProcessId(editor hit)')
        return dict(point=list(point), hitHwnd=hit, pid=int(pid.value), threadId=thread,
            rootHwnd=int(self._call(self.user.GetAncestor, hit, 2) or 0),
            withinEditor=bool(hit == child or self._call(self.user.IsChild, child, hit)),
            visible=bool(self._call(self.user.IsWindowVisible, hit)), enabled=bool(self._call(self.user.IsWindowEnabled, hit)))
