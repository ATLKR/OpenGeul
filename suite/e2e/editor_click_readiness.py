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


def _frame_window_identity(frame, hwnd, parent, child, shell_pid, office_pid):
    suite, host, editor = (frame[key] for key in ('suite', 'parent', 'editor'))
    assert frame['parentWithinSuite'] is True and frame['editorWithinParent'] is True, 'Owned editor hierarchy changed'
    assert (suite['hwnd'], host['hwnd'], editor['hwnd']) == (hwnd, parent, child)
    assert (suite['pid'], host['pid'], editor['pid']) == (shell_pid, shell_pid, office_pid), 'Owned editor process changed'
    assert suite['cloaked'] == 0 and suite['iconic'] is False, 'Owned Suite is unavailable'
    assert all(row['rootHwnd'] == hwnd and row['visible'] is True and row['enabled'] is True
               and type(row['threadId']) is int and row['threadId'] > 0 for row in (suite, host, editor)), 'Owned editor window is unavailable'
    assert suite['threadId'] == host['threadId'], 'Owned host thread changed'
    for row in (host, editor):
        if 'sampleAfter' in row:
            after=row['sampleAfter']
            assert isinstance(after,dict) and set(after)==set(row)-{'sampleAfter'}, 'Invalid second native window sample'
            metadata=lambda sample:{key:value for key,value in sample.items() if key not in ('rectangle','clientScreenRect','sampleAfter')}
            assert metadata(row)==metadata(after), 'Owned editor identity changed during geometry sampling'
    return tuple((row['hwnd'], row['pid'], row['threadId'], row['rootHwnd']) for row in (suite, host, editor))


def _geometry_coherent(frame):
    coherent=True
    for key in ('parent','editor'):
        row=frame[key];after=row.get('sampleAfter',row)
        for name in ('rectangle','clientScreenRect'):
            _rectangle(row[name]);_rectangle(after[name])
            if row[name]!=after[name]:coherent=False
    return coherent


def _frame_identity(frame, hwnd, parent, child, shell_pid, office_pid):
    identity=_frame_window_identity(frame,hwnd,parent,child,shell_pid,office_pid)
    assert _geometry_coherent(frame), 'Owned editor native geometry sample is incoherent'
    suite,host,editor=(frame[key] for key in ('suite','parent','editor'))
    assert _inside(host['clientScreenRect'], host['rectangle']), 'Owned host client geometry escaped its window'
    assert _inside(host['rectangle'], suite['rectangle']) and _inside(editor['rectangle'], host['clientScreenRect']), 'Owned editor geometry escaped its host'
    assert _inside(editor['clientScreenRect'], editor['rectangle']), 'Owned editor client geometry escaped its window'
    return identity


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


def _frame_metadata(frame):
    geometry = {'suite': {'rectangle'}, 'parent': {'rectangle', 'clientScreenRect','sampleAfter'},
                'editor': {'rectangle', 'clientScreenRect','sampleAfter'}}
    return {key: ({k: v for k, v in value.items() if k not in geometry[key]}
                  if key in geometry else value) for key, value in frame.items()}


def _point_in_editor(point, frame):
    assert type(point) in (list, tuple) and len(point) == 2
    assert all(type(v) is int and -(2**31) <= v < 2**31 for v in point)
    left, top, right, bottom = _rectangle(frame['editor']['clientScreenRect'])
    assert left <= point[0] < right and top <= point[1] < bottom, 'Fixed physical point left the owned editor'


def require_geometry_settlement(evidence, *, hwnd, parent, child, shell_pid, office_pid):
    """Replay only observed rounds; receipt readiness flags never waive a guard."""
    ledger = evidence['geometrySettlement']
    assert type(ledger) is dict and set(ledger) == {'point','initialFrame','deadline','rows','pollCount','pendingCount','ready','settledFrame','readyAt'}
    initial, hit, point = evidence['qualifiedFrame'], evidence['qualifiedHit'], evidence['chosenPhysicalPoint']
    identity = _frame_identity(initial, hwnd, parent, child, shell_pid, office_pid)
    samples=evidence['samplingCoherence']
    assert set(samples)=={'deadline','rows'} and samples['deadline']==evidence['deadline']
    assert type(samples['rows']) is list
    previous_sample=evidence['startedAt']
    for sample in samples['rows']:
        assert set(sample)=={'startedAt','finishedAt','frame'}
        assert all(type(sample[key]) in (int,float) and math.isfinite(sample[key]) for key in ('startedAt','finishedAt'))
        assert previous_sample<=sample['startedAt']<=sample['finishedAt']<evidence['deadline']
        previous_sample=sample['finishedAt'];frame=sample['frame']
        assert _frame_window_identity(frame,hwnd,parent,child,shell_pid,office_pid)==identity
        assert _frame_metadata(frame)==_frame_metadata(initial), 'Owned editor sampling metadata changed'
        assert not _geometry_coherent(frame), 'Pending native sample has no measured geometry disagreement'
    rectangle = initial['editor']['clientScreenRect']
    assert point == [(rectangle[0]+rectangle[2])//2, (rectangle[1]+rectangle[3])//2]
    assert ledger['point'] == point and ledger['initialFrame'] == initial and ledger['deadline'] == evidence['deadline']
    assert ledger['ready'] is True and type(ledger['pollCount']) is int and type(ledger['pendingCount']) is int
    rows = ledger['rows']
    assert type(rows) is list and 0 < len(rows) == ledger['pollCount'] and len(rows)+len(evidence['preflight'])+len(samples['rows']) <= MAX_PREFLIGHT_ROWS
    assert ledger['pendingCount'] == len(rows)-1
    previous = evidence['startedAt']
    for index, row in enumerate(rows):
        assert set(row) == {'startedAt','beforeFrame','hit','afterFrame','cursorReadback','finishedAt','classification'}
        assert all(type(row[k]) in (int,float) and math.isfinite(row[k]) for k in ('startedAt','finishedAt'))
        assert previous <= row['startedAt'] <= row['finishedAt'] < evidence['deadline']
        previous = row['finishedAt']
        for name in ('beforeFrame','afterFrame'):
            frame = row[name]
            assert _frame_identity(frame, hwnd, parent, child, shell_pid, office_pid) == identity
            assert _frame_metadata(frame) == _frame_metadata(initial), 'Owned editor non-geometry state changed'
            _point_in_editor(point, frame)
        assert row['hit'] == hit and _hit_ready(row['hit'], hwnd, child, office_pid, identity[2][2], point), 'Fixed-point editor hit changed'
        assert row['cursorReadback'] == point and all(type(v) is int for v in row['cursorReadback']), 'Physical editor cursor changed'
        coherent = row['beforeFrame'] == row['afterFrame']
        assert coherent == (index == len(rows)-1), 'Unexpected coherent/pending geometry history'
        assert row['classification'] == ('coherent' if coherent else 'geometry-pending')
    assert ledger['settledFrame'] == rows[-1]['afterFrame']
    assert type(ledger['readyAt']) in (int,float) and math.isfinite(ledger['readyAt'])
    assert previous <= ledger['readyAt'] < evidence['deadline']
    raw = (json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()
    assert len(raw) <= MAX_RECEIPT_BYTES, 'Owned editor click receipt exceeds finite limit'
    return ledger['settledFrame']


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

    def capture(row, key, value):
        row[key] = value
        raw = (json.dumps(evidence, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()
        if len(raw) > MAX_RECEIPT_BYTES:
            del row[key]
            row['omittedObservation'] = key
            raise AssertionError('Owned editor click receipt exceeds finite limit')

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
                        sharedFocusStartedAt=started, sharedDeadlineSeconds=seconds,
                        samplingCoherence=dict(deadline=deadline,rows=[]))
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

        def history_size():
            return (len(evidence['preflight'])+len(evidence.get('geometrySettlement',{}).get('rows',[]))
                +len(evidence.get('samplingCoherence',{}).get('rows',[])))

        def observe(row=None, key=None):
            while True:
                budget();sample_started=clock()
                assert probe.process_snapshot(process) == shell, 'Original Suite generation changed'
                budget(); assert probe.engine_snapshot(handle) == engine, 'Owned engine generation changed'
                budget(); frame = probe.editor_snapshot(hwnd, parent, child)
                if row is not None: capture(row, key, frame)
                assert _frame_window_identity(frame, hwnd, parent, child, process.pid, office_pid) == identity, 'Owned editor window identity changed'
                budget(); assert probe.foreground() == hwnd, 'Owned editor foreground changed'
                budget(); require_foreground(hwnd)
                if _geometry_coherent(frame):
                    _frame_identity(frame,hwnd,parent,child,process.pid,office_pid)
                    return frame
                assert _frame_metadata(frame)==_frame_metadata(initial), 'Owned editor sampling metadata changed'
                assert history_size()<MAX_PREFLIGHT_ROWS, 'Owned editor shared geometry history exceeded'
                samples=evidence.setdefault('samplingCoherence',dict(deadline=deadline,rows=[]))
                sample=dict(startedAt=sample_started,finishedAt=clock())
                samples['rows'].append(sample);capture(sample,'frame',frame)
                budget();pause(min(.05,max(0,deadline-clock())))

        qualified = False
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
            assert history_size() < MAX_PREFLIGHT_ROWS, 'Owned editor preflight history exceeded'
            evidence['preflight'].append(row)
            ready = _hit_ready(hit, hwnd, child, office_pid, identity[2][2], point)
            assert ready or not qualified, 'Owned editor hit changed before pointer intent'
            if ready:
                qualified = True
                actual = observe()
                assert _frame_metadata(actual) == _frame_metadata(frame), 'Owned editor non-geometry state changed'
                if actual == frame: break
            budget(); pause(min(.05, max(0, deadline - clock())))
        evidence['chosenPhysicalPoint'] = list(point); evidence['qualifiedHit'] = hit
        evidence['qualifiedFrame'] = frame
        evidence['pointerMoveIntent'] = True; retain('pointer-intent')
        budget(); probe.move(point, evidence)
        assert evidence['pointerReadback'] == list(point), 'Physical editor pointer readback differs'
        ledger = dict(point=list(point), initialFrame=frame, deadline=deadline,
                      rows=[], pollCount=0, pendingCount=0, ready=False)
        evidence['geometrySettlement'] = ledger
        while True:
            budget()
            assert history_size() < MAX_PREFLIGHT_ROWS, 'Owned editor shared geometry history exceeded'
            row = dict(startedAt=clock()); ledger['rows'].append(row); ledger['pollCount'] += 1
            before = observe(row, 'beforeFrame')
            assert _frame_metadata(before) == _frame_metadata(frame), 'Owned editor non-geometry state changed'
            _point_in_editor(point, before)
            budget(); fresh = probe.editor_hit(child, point); capture(row, 'hit', fresh); budget()
            assert fresh == hit and _hit_ready(fresh, hwnd, child, office_pid, identity[2][2], point), 'Owned editor hit changed after pointer move'
            actual = observe(row, 'afterFrame')
            assert _frame_metadata(actual) == _frame_metadata(frame), 'Owned editor non-geometry state changed'
            _point_in_editor(point, actual)
            budget(); cursor = probe.pointer(); capture(row, 'cursorReadback', cursor); budget()
            assert cursor == list(point) and all(type(v) is int for v in cursor), 'Physical editor cursor changed'
            row['finishedAt'] = clock(); budget()
            coherent = before == actual
            row['classification'] = 'coherent' if coherent else 'geometry-pending'
            if coherent:
                ledger.update(ready=True, settledFrame=actual, readyAt=clock())
                budget()
                frame = require_geometry_settlement(evidence, hwnd=hwnd, parent=parent, child=child,
                    shell_pid=process.pid, office_pid=office_pid)
                budget(); evidence['beforeClickHit'] = fresh
                break
            ledger['pendingCount'] += 1
            budget(); pause(min(.05, max(0, deadline-clock())))
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

    def pointer(self):
        position = Point()
        self._required(self._call(self.user.GetPhysicalCursorPos, C.byref(position)), 'GetPhysicalCursorPos(owned editor)')
        return [int(position.x), int(position.y)]

    def close_engine(self, handle, receipt):
        # HANDLE release remains mandatory after the shared deadline expires.
        receipt['engineHandleReleased'] = bool(self.kernel.CloseHandle(handle))
        self._required(receipt['engineHandleReleased'], 'CloseHandle(owned editor)')

    def _child_window_sample(self, hwnd):
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

    def _child_window(self, hwnd):
        # Independent getters can straddle a resize. Preserve both observations;
        # only the caller with retained process identities may wait and reobserve.
        before=self._child_window_sample(hwnd)
        after=self._child_window_sample(hwnd)
        if before!=after:before['sampleAfter']=after
        return before

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
