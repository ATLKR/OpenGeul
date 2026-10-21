"""Finite counted physical navigation for the original retained Calc editor.

This harness proves native insertion counts, not delivery or a document change.
The existing read-only A1 and edit-buffer barriers remain the delivery checks.
No layout, focus, model, modifier state or input deadline is repaired here.
"""
from __future__ import annotations

import ctypes as C
import json
import math
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace

from ascii_editor_input import Input, input_buffer
from suite_window_activation import NativeActivationProbe


US_LAYOUT = 0x04090409
MAX_RECEIPT_BYTES = 128 * 1024
ORDER = ('CTRL_HOME', 'F2', 'CTRL_END')
NEUTRAL_KEYS = (0x10, 0x11, 0x12, 0xa0, 0xa1, 0xa2, 0xa3, 0xa4, 0xa5,
                0x5b, 0x5c, 0x14, 0x91, 0x24, 0x23, 0x71, 0x75, 0x53, 0x57, 0x31, 0x09, 0x0d, 0x1b)
PRESETS = {'CTRL_HOME': ((0x1d, 0), (0x47, 1)), 'F2': ((0x3c, 0),),
           'CTRL_END': ((0x1d, 0), (0x4f, 1)), 'CTRL_F6': ((0x1d, 0), (0x40, 0)),
           'CTRL_S': ((0x1d, 0), (0x1f, 0)), 'CTRL_W': ((0x1d, 0), (0x11, 0)),
           'CTRL_1': ((0x1d, 0), (0x02, 0)), 'TAB': ((0x0f, 0),), 'ENTER': ((0x1c, 0),),
           'CTRL_SHIFT_S': ((0x1d, 0), (0x2a, 0), (0x1f, 0)), 'ESCAPE': ((0x01, 0),)}


def shortcut_events(shortcut):
    """An enum, never a general key parser or a caller-supplied scan plan."""
    if not isinstance(shortcut, str) or shortcut not in PRESETS:
        raise ValueError('Unsupported counted editor navigation shortcut')
    keys = PRESETS[shortcut]
    return ([dict(vk=0, scan=scan, flags=8 | extended) for scan, extended in keys]
            + [dict(vk=0, scan=scan, flags=10 | extended) for scan, extended in reversed(keys)])


def _owned_release(events, inserted):
    held = []
    for event in events[:inserted]:
        key = (event['scan'], event['flags'] & 1)
        if event['flags'] & 2:
            held.remove(key)
        else:
            assert key not in held, 'Repeated shortcut keydown is forbidden'
            held.append(key)
    return [dict(vk=0, scan=scan, flags=10 | extended) for scan, extended in reversed(held)]


def owned_release_events(events, inserted):
    """Release only a known serial prefix of one of the exact native plans."""
    assert isinstance(events, list) and any(events == shortcut_events(name) for name in PRESETS), 'Unknown shortcut scan plan'
    assert type(inserted) is int and 0 <= inserted <= len(events), 'Unknown shortcut inserted prefix'
    assert all(type(value) is int for event in events for value in event.values()), 'Untyped shortcut scan plan'
    return _owned_release(events, inserted)


def _error(exc):
    return type(exc).__name__ + ': ' + str(exc)[:1024]


def _same_image(left, right):
    return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()


def join_shortcut_generation(process, parent, child, engine):
    """Join a prior native generation only; never reuse its closed HANDLE."""
    key = (parent, child, engine['pid'])
    prior = getattr(process, 'opengeul_editor_shortcut_generations', {})
    assert isinstance(prior,dict) and len(prior)<=64, 'Shortcut generation ledger is not bounded'
    for slot in prior:
        assert isinstance(slot,tuple) and len(slot)==3 and all(type(value) is int and value>0 for value in slot), 'Invalid shortcut generation slot'
        assert slot[:2] != key[:2] or slot[2] == key[2], 'Earlier shortcut slot engine PID changed'
    if key not in prior: return None
    old = prior[key]
    assert (old[0], old[2]) == (engine['pid'], engine['creationTime']) and _same_image(old[1], engine['image']), 'Earlier shortcut engine generation changed'
    witness = process.opengeul_editor_shortcut_admissions[key]
    assert witness['generation'] == list(old), 'Earlier shortcut generation admission changed'
    return dict(witness,generation=list(old))


def admit_shortcut_generation(process, parent, child, engine, admitted_at):
    """Record an explicit first native admission time, without reader claims."""
    prior = join_shortcut_generation(process, parent, child, engine)
    if prior is not None: return prior
    assert type(admitted_at) in (int, float) and math.isfinite(admitted_at)
    generation = (engine['pid'], engine['image'], engine['creationTime'])
    key = (parent, child, engine['pid'])
    if not hasattr(process, 'opengeul_editor_shortcut_generations'):
        process.opengeul_editor_shortcut_generations = {}
        process.opengeul_editor_shortcut_admissions = {}
    assert len(process.opengeul_editor_shortcut_generations)<64, 'Shortcut generation ledger exceeded its bound'
    witness = dict(generation=list(generation), firstAdmittedAt=admitted_at,
                   basis='first measured native shortcut HANDLE admission; no earlier reader proof claimed')
    process.opengeul_editor_shortcut_generations[key] = generation
    process.opengeul_editor_shortcut_admissions[key] = witness
    return dict(witness,generation=list(generation))


class CountedEditorShortcuts:
    """Retain one admitted engine HANDLE through the three original chords.

    ``binding`` is the earlier original model-reader binding. Opening our own
    query+sync HANDLE does not backdate its admission or borrow a closed click
    HANDLE. An optional earlier click generation is an additional exact join.
    """
    def __init__(self, api, process, binding, record, deadline, *, probe=None, clock=time.monotonic):
        assert type(deadline) in (int, float) and math.isfinite(deadline), 'Invalid shortcut deadline'
        self.api, self.process, self.binding = api, process, dict(binding)
        self.record, self.deadline, self.probe, self.clock = record, deadline, probe, clock
        self.handle = None; self.original_shell = self.original_engine = None
        self.thread = None; self.lock_state = None; self.active = self.finished = False
        self.failed_error = None
        self.output = self.stem = None
        self.receipt = dict(schemaVersion=1, kind='owned-counted-editor-navigation',
                            success=False, startedAt=clock(), deadline=deadline,
                            expectedBinding=dict(binding), actions=[], cleanupErrors=[],
                            engineHandleReleased=False, inputCountBasis='SendInput return counts; delivery requires original model barriers')
        record.setdefault('editorShortcutSessions', []).append(self.receipt)

    def _budget(self):
        assert self.clock() < self.deadline, 'Counted editor shortcut deadline expired'

    def _retain(self, phase):
        assert self.output is not None and self.stem is not None
        raw = (json.dumps(self.receipt, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
        assert len(raw) <= MAX_RECEIPT_BYTES, 'Counted shortcut receipt exceeds its finite bound'
        suffix = phase if phase in ('admission', 'session-result') else f'{len(self.receipt["actions"])-1:02d}-' + phase
        with (self.output / (self.stem + '-' + suffix + '.json')).open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())

    def _prepare(self):
        p, b = self.process, self.binding
        self._budget()
        self.output = Path(p.opengeul_evidence_output)
        suite = Path(p.opengeul_suite_root)
        assert self.output.is_absolute() and self.output.is_dir() and suite.is_absolute()
        for part in (self.output, *self.output.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked shortcut evidence path'
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}', p.opengeul_evidence_case)
        assert isinstance(p.args, (list, tuple)) and _same_image(p.args[0], suite / 'OpenGeul.Office.exe')
        assert type(p.pid) is int and p.pid > 0 and int(p._handle) > 0
        assert b['shellPid'] == p.pid and b['suiteHwnd'] == b['rootHwnd']
        for key in ('shellCreationTime', 'officePid', 'officeCreationTime', 'suiteHwnd', 'parentHwnd', 'childHwnd'):
            assert type(b[key]) is int and b[key] > 0, 'Invalid original reader native binding'
        assert _same_image(b['expectedImage'], suite / 'Office/program/soffice.bin'), 'Original reader engine image differs'
        sequence = getattr(p, 'opengeul_shortcut_sequence', 0)
        assert type(sequence) is int and 0 <= sequence < 64, 'Counted shortcut session limit exceeded'
        p.opengeul_shortcut_sequence = sequence + 1
        self.stem = p.opengeul_evidence_case + '-editor-shortcuts-' + format(sequence, '03d')
        self.receipt['receiptStem'] = self.stem
        if self.probe is None: self.probe = NativeShortcutProbe(self.deadline, self.clock)
        self._budget(); shell = self.probe.process_snapshot(p)
        expected = (p.pid, int(p._handle), str((suite / 'OpenGeul.Office.exe').resolve()), b['shellCreationTime'], 258)
        assert (shell['pid'], shell['handleValue'], shell['image'], shell['creationTime'], shell['waitResult']) == expected, 'Original shell HANDLE/image/generation changed'
        assert p.opengeul_activation_binding == expected, 'Original activation generation is required'
        self.original_shell = shell
        self._budget()
        # Retain a returned HANDLE before checking elapsed time, so even a late
        # successful OpenProcess is closed in the mandatory failure path.
        self.handle = self.probe.open_engine(b['officePid'])
        assert type(self.handle) is int and self.handle > 0, 'Engine HANDLE admission failed'
        self.receipt['engineHandleAdmittedAt'] = self.clock()
        self.receipt['engineAdmissionBasis'] = 'new query+sync HANDLE joined to earlier original reader binding'
        self._budget(); engine = self.probe.engine_snapshot(self.handle)
        assert (engine['pid'], engine['handleValue'], engine['creationTime'], engine['waitResult']) == \
            (b['officePid'], self.handle, b['officeCreationTime'], 258), 'Original reader engine generation changed'
        assert _same_image(engine['image'], b['expectedImage']), 'Original reader engine image changed'
        self.receipt['priorShortcutGeneration'] = join_shortcut_generation(p,b['parentHwnd'],b['childHwnd'],engine)
        prior = getattr(p, 'opengeul_editor_click_generations', {})
        key = (b['parentHwnd'], b['childHwnd'], b['officePid'])
        if key in prior:
            old = prior[key]
            assert (old[0], old[2]) == (engine['pid'], engine['creationTime']) and _same_image(old[1], engine['image']), 'Earlier click engine generation changed'
            self.receipt['earlierClickGenerationJoined'] = True
        else:
            self.receipt['earlierClickGenerationJoined'] = False
        self.original_engine = engine
        self.receipt.update(originalShell=shell, originalEngine=engine)
        self.receipt['admissionSnapshot'] = self._guard()
        self._retain('admission')
        self._budget()

    def _guard(self):
        from windows_smoke import _editor_focus_snapshot_ready
        self._budget(); p, b = self.process, self.binding
        shell = self.probe.process_snapshot(p)
        self._budget(); engine = self.probe.engine_snapshot(self.handle)
        assert shell == self.original_shell, 'Retained original shell generation changed'
        assert engine == self.original_engine, 'Retained original engine HANDLE/generation changed'
        self._budget(); scope = self.probe.scope_snapshot(self.api, b)
        thread = scope['before']['editor']['threadId']
        if self.thread is None: self.thread = thread
        assert thread == self.thread, 'Owned editor input thread changed'
        focus = _editor_focus_snapshot_ready(scope, b['suiteHwnd'], b['childHwnd'], b['shellPid'], b['officePid'], self.thread)
        assert focus, 'Strict owned editor focus is not ready'
        parent = scope['parent']
        assert (parent['hwnd'], parent['pid'], parent['rootHwnd'], parent['isWindow']) == \
            (b['parentHwnd'], b['shellPid'], b['suiteHwnd'], True), 'Owned editor parent changed'
        assert all(scope[key] is True for key in ('suiteOwnsParent', 'parentOwnsChild', 'parentVisible',
                                                  'parentEnabled', 'childVisible', 'childEnabled')), 'Owned editor ancestry is not available'
        self._budget(); self.api.require_foreground(b['suiteHwnd'])
        assert self.api.require_editor_focus(b['suiteHwnd'], b['childHwnd']) == focus, 'Strict editor focus changed before shortcut'
        self._budget(); keyboard = self.probe.keyboard_snapshot(self.thread)
        assert keyboard['targetLayout'] == keyboard['currentThreadLayout'] == US_LAYOUT, 'Shortcut requires exact English US layout'
        assert keyboard['keysDown'] == [], 'Shortcut requires neutral modifier and navigation keys'
        assert keyboard['capsLockOn'] is False and keyboard['scrollLockOn'] is False, 'Shortcut lock state is not neutral'
        locks = tuple(keyboard[key] for key in ('capsLockOn', 'scrollLockOn', 'numLockOn'))
        assert all(type(value) is bool for value in locks), 'Invalid native lock observation'
        if self.lock_state is None: self.lock_state = locks
        assert locks == self.lock_state, 'Native lock state changed during shortcut sequence'
        self._budget()
        return dict(shell=shell, engine=engine, scope=scope, keyboard=keyboard)

    def __enter__(self):
        assert not self.active and not self.finished, 'Counted shortcut session cannot restart'
        try:
            self._prepare(); self.active = True
            return self
        except BaseException as exc:
            self._finish(exc)
            raise

    def _release_prefix(self, action, inserted):
        events = owned_release_events(action['events'], inserted)
        if not events: return
        # Every possible known-prefix release buffer was retained with the
        # original durable input intent, before any keydown could be inserted.
        release = action['ownedKeyUp'] = dict(events=events, bufferHex=bytes(input_buffer(events)).hex(),
                                             requestedInputs=len(events), insertedInputs=None)
        try:
            value = self.probe.release(input_buffer(events))
            assert type(value) is int and 0 <= value <= len(events), 'Unknown owned key-up return'
            release['insertedInputs'] = value
            assert value == len(events), 'Owned shortcut key-up cleanup was partial'
        except BaseException as exc:
            release['error'] = _error(exc)

    def _press(self, shortcut):
        index = len(self.receipt['actions'])
        assert index < len(ORDER) and shortcut == ORDER[index], 'Unexpected or repeated navigation shortcut'
        self._budget(); events = shortcut_events(shortcut)
        action = dict(shortcut=shortcut, events=events, bufferHex=bytes(input_buffer(events)).hex(),
                      requestedInputs=len(events), insertedInputs=None, inputCallAttempts=0,
                      inputCountBasis='native shortcut call not attempted', before=self._guard())
        action['knownPrefixReleasePlans'] = {str(n): dict(events=owned_release_events(events, n),
            bufferHex=bytes(input_buffer(owned_release_events(events, n))).hex()) for n in range(len(events))}
        self.receipt['actions'].append(action)
        self._retain('input-intent'); self._budget()
        action['beforeInsertion'] = self._guard()
        assert action['beforeInsertion']['scope']['focus']['hwnd'] == action['before']['scope']['focus']['hwnd'], 'Editor focus changed while retaining shortcut intent'
        action['inputCallAttempts'] = 1
        action['inputCountBasis'] = 'native shortcut call attempted; return unavailable'
        value = self.probe.send(input_buffer(events))
        if type(value) is not int or not 0 <= value <= len(events):
            action['invalidNativeReturn'] = repr(value)[:128]
            raise AssertionError('Shortcut native insertion count is unknown')
        action.update(insertedInputs=value, inputCountBasis='SendInput return value')
        if value != len(events):
            self._release_prefix(action, value)
            raise AssertionError('Shortcut had partial native insertion')
        self._budget(); action['after'] = self._guard()
        action['finishedAt'] = self.clock()
        self._retain('input-result'); self._budget()

    def navigate(self, keys):
        assert self.active and not self.finished, 'Counted shortcut session is not active'
        if self.failed_error is not None: raise self.failed_error
        try:
            expected = '^{HOME}' if not self.receipt['actions'] else '{F2}^{END}'
            assert keys == expected, 'Unexpected or repeated navigation callback'
            for shortcut in (('CTRL_HOME',) if keys == '^{HOME}' else ('F2', 'CTRL_END')):
                self._press(shortcut)
        except BaseException as exc:
            self.failed_error = exc
            raise

    def _finish(self, primary):
        if self.finished: return
        self.finished = True; self.active = False
        if primary is not None: self.receipt['error'] = _error(primary)
        if self.handle is not None:
            try:
                assert self.probe.close_engine(self.handle) is True, 'Original engine HANDLE close failed'
                self.receipt['engineHandleReleased'] = True
            except BaseException as exc:
                self.receipt['cleanupErrors'].append(_error(exc))
                if primary is None: primary = exc
        self.receipt['finishedAt'] = self.clock()
        self.receipt['success'] = primary is None and self.receipt['finishedAt'] <= self.deadline
        if primary is None and not self.receipt['success']:
            primary = AssertionError('Counted editor shortcut session exceeded deadline')
        try:
            if self.output is not None and self.stem is not None: self._retain('session-result')
        except BaseException as exc:
            self.receipt['success'] = False
            self.receipt['retentionError'] = _error(exc)
            if primary is None: primary = exc
        return primary

    def __exit__(self, kind, value, traceback):
        primary = self.failed_error if self.failed_error is not None else value
        if primary is None and tuple(a['shortcut'] for a in self.receipt['actions']) != ORDER:
            primary = AssertionError('Original navigation sequence is not complete')
        error = self._finish(primary)
        if error is not None and error is not value: raise error
        return False


class NativeShortcutProbe(NativeActivationProbe):
    """Typed Windows64 observations and counted input; never changes focus/HKL."""
    def __init__(self, deadline, clock, **libraries):
        super().__init__(deadline, clock, **libraries)
        H, D, B = C.c_void_p, C.c_uint32, C.c_int32
        for name, args, result in (
            ('OpenProcess', (D, B, D), H), ('CloseHandle', (H,), B),
        ):
            function = getattr(self.kernel, name); function.argtypes, function.restype = args, result
        for name, args, result in (
            ('GetKeyboardLayout', (D,), H), ('GetKeyState', (C.c_int,), C.c_int16),
            ('IsChild', (H, H), B), ('SendInput', (D, C.POINTER(Input), C.c_int), D),
        ):
            function = getattr(self.user, name); function.argtypes, function.restype = args, result
        assert C.sizeof(Input) == 40 and Input.payload.offset == 8, 'Shortcut Win64 INPUT ABI changed'

    def open_engine(self, pid):
        assert self.clock() < self.deadline, 'Engine admission deadline expired'
        handle = self.kernel.OpenProcess(0x00101000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE.
        self._required(handle, 'OpenProcess(original editor engine)')
        return int(handle)

    def engine_snapshot(self, handle):
        return self.process_snapshot(SimpleNamespace(_handle=handle))

    def scope_snapshot(self, api, binding):
        result = api.editor_focus_snapshot(binding['suiteHwnd'], binding['childHwnd'], binding['shellPid'], binding['officePid'])
        result['parent'] = api._focus_window(binding['parentHwnd'])
        for key, parent, child in (('suiteOwnsParent', binding['suiteHwnd'], binding['parentHwnd']),
                                   ('parentOwnsChild', binding['parentHwnd'], binding['childHwnd'])):
            result[key] = bool(self._call(self.user.IsChild, parent, child))
        for role, hwnd in (('parent', binding['parentHwnd']), ('child', binding['childHwnd'])):
            result[role+'Visible'] = bool(self._call(self.user.IsWindowVisible, hwnd))
            result[role+'Enabled'] = bool(self._call(self.user.IsWindowEnabled, hwnd))
        return result

    def keyboard_snapshot(self, thread):
        return dict(targetLayout=int(self._call(self.user.GetKeyboardLayout, thread) or 0),
                    currentThreadLayout=int(self._call(self.user.GetKeyboardLayout, 0) or 0),
                    keysDown=[key for key in NEUTRAL_KEYS if self._call(self.user.GetAsyncKeyState, key) & 0x8000],
                    capsLockOn=bool(self._call(self.user.GetKeyState, 0x14) & 1),
                    scrollLockOn=bool(self._call(self.user.GetKeyState, 0x91) & 1),
                    numLockOn=bool(self._call(self.user.GetKeyState, 0x90) & 1))

    def send(self, payload):
        assert self.clock() < self.deadline, 'Shortcut native input deadline expired'
        return int(self.user.SendInput(len(payload), payload, C.sizeof(Input)))

    def release(self, payload):
        # Only the known inserted prefix's own key-ups may outlive the budget.
        return int(self.user.SendInput(len(payload), payload, C.sizeof(Input)))

    def close_engine(self, handle):
        # HANDLE release is mandatory even after timeout or failed native input.
        return bool(self.kernel.CloseHandle(handle))
