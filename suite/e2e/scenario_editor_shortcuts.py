"""Closed editor input programs with distinct first and prior-reader admission.

Counts establish transport insertion. Existing focus, ASCII, model, prompt and
durable-file validators establish their own delivery postconditions unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time

from ascii_editor_input import input_buffer, require_ascii_receipt
from counted_editor_shortcuts import (CountedEditorShortcuts, NativeShortcutProbe,
    US_LAYOUT, owned_release_events, shortcut_events, _same_image)
from counted_editor_shortcuts import admit_shortcut_generation, join_shortcut_generation


PROGRAMS = {
    'GUI_WRITER': ('CTRL_F6', 'EDITOR_READY', 'CTRL_END', 'ASCII', 'SAVE_PHASE', 'CTRL_S'),
    'GUI_CALC': ('CTRL_F6', 'EDITOR_READY', 'MODEL_STARTED', 'CTRL_HOME', 'F2', 'CTRL_END',
                 'ASCII', 'ENTER', 'MODEL_COMPLETE', 'SAVE_PHASE', 'CTRL_S'),
    'GUI_IMPRESS': ('CTRL_F6', 'EDITOR_READY', 'TAB', 'F2', 'CTRL_END', 'ASCII', 'SAVE_PHASE', 'CTRL_S'),
    'WRITER_STYLE': ('CTRL_F6', 'EDITOR_READY', 'CTRL_HOME', 'CTRL_1'),
    'PENDING_CALC_ENTRY': ('CTRL_F6', 'EDITOR_READY'),
    'LIFECYCLE_WRITER': ('MODEL_STARTED', 'CTRL_F6', 'EDITOR_READY', 'CTRL_END', 'ASCII', 'MODEL_COMPLETE'),
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _insert_once(owner, shortcut, before, after):
    """One enum transaction; callers supply fixed policy methods, never key text."""
    owner._budget(); events = shortcut_events(shortcut)
    action = dict(shortcut=shortcut, events=events, bufferHex=bytes(input_buffer(events)).hex(),
        requestedInputs=len(events), insertedInputs=None, inputCallAttempts=0,
        inputCountBasis='probe.send not entered', before=before())
    action['knownPrefixReleasePlans'] = {str(n): dict(events=owned_release_events(events, n),
        bufferHex=bytes(input_buffer(owned_release_events(events, n))).hex()) for n in range(len(events))}
    owner.receipt['actions'].append(action)
    owner._retain('input-intent'); owner._budget()
    action['beforeInsertion'] = before()
    initial, current = action['before']['scope'], action['beforeInsertion']['scope']
    unchanged = current['focus']['hwnd'] == initial['focus']['hwnd']
    b = owner.binding
    entered_exact_child = (isinstance(owner, FirstAdmissionEditorSession) and shortcut == 'CTRL_F6'
        and initial['focus']['hwnd'] in (b['suiteHwnd'], b['parentHwnd'])
        and initial['focus']['pid'] == b['shellPid']
        and initial['focus']['threadId'] == initial['before']['suite']['threadId']
        and current['focus']['hwnd'] == b['childHwnd'] and current['focusWithinEditor'] is True
        and current['focus']['pid'] == b['officePid'] and current['focus']['threadId'] == owner.thread)
    assert unchanged or entered_exact_child, 'Focus changed while retaining input intent'
    action['focusIntentTransition'] = 'unchanged' if unchanged else 'owned-host-to-exact-original-editor-child'
    action.update(inputCallAttempts=1, inputCountBasis='probe.send entered; OS entry/return unavailable')
    value = owner.probe.send(input_buffer(events))
    if type(value) is not int or not 0 <= value <= len(events):
        action['invalidNativeReturn'] = repr(value)[:128]
        raise AssertionError('Shortcut native insertion count is unknown')
    action.update(insertedInputs=value, inputCountBasis='SendInput return value')
    if value != len(events):
        owner._release_prefix(action, value)
        raise AssertionError('Shortcut had partial native insertion')
    owner._budget(); action['after'] = after()
    action['finishedAt'] = owner.clock()
    owner._retain('input-result'); owner._budget()


class FirstAdmissionEditorSession(CountedEditorShortcuts):
    """Own a first native HANDLE admission, without inventing a reader witness.

    Only storage, prefix recovery and mandatory cleanup are inherited. Admission,
    program order and phase guards are distinct from reader-bound Calc input.
    """
    navigate = None

    def __init__(self, api, process, attachment, program, record, entry_deadline,
                 *, marker=None, probe=None, clock=time.monotonic):
        assert isinstance(program, str) and program in PROGRAMS, 'Unknown editor program'
        assert type(entry_deadline) in (int, float) and math.isfinite(entry_deadline)
        assert entry_deadline <= clock() + 5, 'Editor entry cannot widen the shared five-second deadline'
        assert set(attachment) == {'hwnd', 'parent', 'child', 'officePid'}, 'Exact original attachment is required'
        assert all(type(value) is int and value > 0 for value in attachment.values())
        if program.startswith('GUI_'):
            assert marker == 'UI-OpenGeul-' + program[4:].lower(), 'Wrong exact GUI marker'
        elif program == 'LIFECYCLE_WRITER':
            from lifecycle_smoke import ASCII_EDITOR_MARKERS
            assert marker in tuple(text for group in ASCII_EDITOR_MARKERS.values() for text in group), 'Unknown original lifecycle marker'
        else:
            assert marker is None, 'Style program cannot type a marker'
        self.api, self.process, self.attachment = api, process, dict(attachment)
        self.program, self.marker, self.record = program, marker, record
        self.deadline = self.entry_deadline = entry_deadline
        self.probe, self.clock = probe, clock
        self.handle = self.original_shell = self.original_engine = None
        self.thread = self.lock_state = None
        self.active = self.finished = False; self.failed_error = None
        self.output = self.stem = None
        self.index = 0; self.model_context = self.model_plan = None
        self.receipt = dict(schemaVersion=1, kind='first-admission-scenario-editor-shortcuts',
            success=False, deliveryVerified=False, program=program, expectedProgram=list(PROGRAMS[program]),
            startedAt=clock(), entryDeadline=entry_deadline, deadline=entry_deadline,
            attachment=dict(attachment), actions=[], phases=[], cleanupErrors=[], engineHandleReleased=False,
            inputCountBasis='Native counts establish insertion; unchanged caller validators establish delivery')
        record.setdefault('editorShortcutSessions', []).append(self.receipt)

    def _prepare(self):
        p = self.process; a = self.attachment
        self._budget()
        self.output = Path(p.opengeul_evidence_output); suite = Path(p.opengeul_suite_root)
        assert self.output.is_absolute() and self.output.is_dir() and suite.is_absolute()
        for part in (self.output, *self.output.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked shortcut evidence path'
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}', p.opengeul_evidence_case)
        assert isinstance(p.args, (list, tuple)) and _same_image(p.args[0], suite / 'OpenGeul.Office.exe')
        assert type(p.pid) is int and p.pid > 0 and int(p._handle) > 0
        sequence = getattr(p, 'opengeul_shortcut_sequence', 0)
        assert type(sequence) is int and 0 <= sequence < 64
        p.opengeul_shortcut_sequence = sequence + 1
        self.stem = p.opengeul_evidence_case + '-editor-shortcuts-' + format(sequence, '03d')
        self.receipt['receiptStem'] = self.stem
        if self.probe is None: self.probe = NativeShortcutProbe(self.deadline, self.clock)
        self._budget(); shell = self.probe.process_snapshot(p)
        expected = (p.pid, int(p._handle), str((suite / 'OpenGeul.Office.exe').resolve()), shell['creationTime'], 258)
        assert type(shell['creationTime']) is int and shell['creationTime'] > 0
        assert (shell['pid'], shell['handleValue'], shell['image'], shell['creationTime'], shell['waitResult']) == expected, 'Original shell HANDLE/image/generation changed'
        assert p.opengeul_activation_binding == expected, 'Original activation generation is required'
        self.original_shell = shell
        self._budget(); self.handle = self.probe.open_engine(a['officePid'])
        assert type(self.handle) is int and self.handle > 0, 'Engine HANDLE first admission failed'
        self.receipt['engineHandleAdmittedAt'] = self.clock()
        self.receipt['engineAdmissionBasis'] = 'first measured native query+sync HANDLE admission; no earlier reader witness claimed'
        self._budget(); engine = self.probe.engine_snapshot(self.handle)
        assert (engine['pid'], engine['handleValue'], engine['waitResult']) == (a['officePid'], self.handle, 258), 'Engine first admission identity changed'
        assert type(engine['creationTime']) is int and engine['creationTime'] > 0
        assert engine['creationTime'] >= shell['creationTime'], 'Engine first admission predates original shell'
        assert _same_image(engine['image'], suite / 'Office/program/soffice.bin'), 'Engine first admission image changed'
        self.receipt['priorShortcutGeneration'] = join_shortcut_generation(p,a['parent'],a['child'],engine)
        prior = getattr(p, 'opengeul_editor_click_generations', {})
        key = (a['parent'], a['child'], a['officePid'])
        if key in prior:
            old = prior[key]
            assert (old[0], old[2]) == (engine['pid'], engine['creationTime']) and _same_image(old[1], engine['image']), 'Earlier click engine generation changed'
        self.receipt['earlierClickGenerationJoined'] = key in prior
        self.original_engine = engine
        # This is an explicitly native scope descriptor, not a model-reader binding.
        self.binding = dict(shellPid=p.pid, shellCreationTime=shell['creationTime'], officePid=engine['pid'],
            officeCreationTime=engine['creationTime'], expectedImage=engine['image'], suiteHwnd=a['hwnd'],
            parentHwnd=a['parent'], childHwnd=a['child'], rootHwnd=a['hwnd'])
        self.receipt.update(originalShell=shell, originalEngine=engine)
        self.receipt['admissionSnapshot'] = self._owned_guard()
        self.receipt['firstShortcutAdmission'] = admit_shortcut_generation(p,a['parent'],a['child'],engine,self.receipt['engineHandleAdmittedAt'])
        self._retain('admission'); self._budget()

    def _observe_owned_guard(self):
        row = super()._observe_guard()
        self._budget(); row['focusKeyboard'] = self.probe.keyboard_snapshot(row['scope']['focus']['threadId'])
        return row

    def _validate_owned_guard(self, row, editor_required):
        from windows_smoke import _editor_focus_snapshot_ready
        b = self.binding; shell, engine, scope, keyboard, focus_keyboard = (row[key] for key in ('shell','engine','scope','keyboard','focusKeyboard'))
        assert shell == self.original_shell, 'Retained original shell generation changed'
        assert engine == self.original_engine, 'Retained original engine HANDLE/generation changed'
        thread = scope['before']['editor']['threadId']
        if self.thread is None: self.thread = thread
        assert thread == self.thread, 'Owned editor input thread changed'
        _editor_focus_snapshot_ready(scope, b['suiteHwnd'], b['childHwnd'], b['shellPid'], b['officePid'], self.thread)
        parent = scope['parent']
        assert (parent['hwnd'], parent['pid'], parent['rootHwnd'], parent['isWindow']) == (b['parentHwnd'], b['shellPid'], b['suiteHwnd'], True), 'Owned editor parent changed'
        assert all(scope[key] is True for key in ('suiteOwnsParent', 'parentOwnsChild', 'parentVisible', 'parentEnabled', 'childVisible', 'childEnabled')), 'Owned editor ancestry is not available'
        focus = scope['focus']
        assert focus['hwnd'] and focus['isWindow'] and focus['rootHwnd'] == b['suiteHwnd'] and focus['pid'] in (b['shellPid'], b['officePid']), 'Input requires owned root or editor focus'
        if editor_required:
            assert scope['focusWithinEditor'] is True and focus['pid'] == b['officePid'], 'Strict editor readiness is required before navigation'
        self._budget(); self.api.require_foreground(b['suiteHwnd'])
        for observed in (keyboard, focus_keyboard):
            assert observed['targetLayout'] == observed['currentThreadLayout'] == US_LAYOUT, 'Shortcut requires exact English US layout'
            assert observed['keysDown'] == [], 'Shortcut requires neutral modifier and navigation keys'
            assert observed['capsLockOn'] is False and observed['scrollLockOn'] is False, 'Shortcut lock state is not neutral'
        locks = tuple(keyboard[key] for key in ('capsLockOn', 'scrollLockOn', 'numLockOn'))
        assert all(type(value) is bool for value in locks)
        if self.lock_state is None: self.lock_state = locks
        assert locks == self.lock_state and tuple(focus_keyboard[key] for key in ('capsLockOn', 'scrollLockOn', 'numLockOn')) == locks, 'Native lock state changed'
        self._budget()

    def _capture_guard(self, editor_required):
        from capture_readiness import settle_owned_capture
        result = settle_owned_capture(self._observe_owned_guard,
            lambda row:self._validate_owned_guard(row,editor_required),self.receipt,self.binding,self.deadline,clock=self.clock)
        if editor_required:
            from windows_smoke import _editor_focus_snapshot_ready
            b = self.binding
            focus = _editor_focus_snapshot_ready(result['scope'],b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'],self.thread)
            assert focus and focus == result['scope']['focus']['hwnd'], 'Strict editor readiness requires the guarded scope'
            self._budget()
        return result

    def _owned_guard(self):
        return self._capture_guard(False)

    def _guard(self):
        return self._capture_guard(True)

    def _expected(self, step):
        assert self.active and not self.finished, 'Editor program is not active'
        if self.failed_error is not None: raise self.failed_error
        assert self.index < len(PROGRAMS[self.program]) and PROGRAMS[self.program][self.index] == step, 'Unexpected or repeated editor program step'

    def _phase(self, step, proof):
        self.receipt['phases'].append(dict(step=step, at=self.clock(), proof=proof))
        self.index += 1
        self._retain('phase-' + str(self.index) + '-' + step.lower())
        self._budget()

    def press(self, shortcut):
        try:
            self._expected(shortcut)
            guard = self._owned_guard if shortcut == 'CTRL_F6' else self._guard
            _insert_once(self, shortcut, guard, guard)
            self.index += 1
        except BaseException as exc:
            if self.failed_error is None: self.failed_error = exc
            raise self.failed_error

    def editor_ready(self, evidence):
        try:
            self._expected('EDITOR_READY')
            from windows_smoke import require_editor_focus_readiness
            b = self.binding
            assert any(row is evidence for row in self.record.get('editorFocusReadinessRecords', [])), 'Original readiness receipt is required'
            require_editor_focus_readiness(evidence, b['suiteHwnd'], b['childHwnd'], b['shellPid'], b['officePid'])
            assert self.clock() < self.entry_deadline, 'Shared editor entry deadline expired'
            observed = self._guard()
            self.deadline = (self.entry_deadline if self.program == 'PENDING_CALC_ENTRY' else
                             self.model_plan.deadline if self.model_plan is not None else self.clock() + 5)
            self.probe.deadline = self.deadline; self.receipt.update(inputDeadline=self.deadline,deadline=self.deadline)
            self._phase('EDITOR_READY', dict(focusHwnd=evidence['focusHwnd'], snapshot=observed))
        except BaseException as exc:
            if self.failed_error is None: self.failed_error = exc
            raise self.failed_error

    def join_model(self, context, plan):
        try:
            self._expected('MODEL_STARTED')
            if self.program == 'GUI_CALC':
                # begin() remains in its original caller position and owns its
                # original twelve seconds, including private reader startup.
                # Charge its start to the preceding input phase, not its end.
                ready=self.receipt['phases'][-1]
                assert ready['step']=='EDITOR_READY' and ready['at']<=plan.started_at<self.deadline, 'Calc model begin started outside its original input phase'
            else:
                self._budget()
            assert context.plan is plan and context.reader is not None and context.deadline == plan.deadline, 'Original active model plan is required'
            b = plan.binding
            for key in self.binding:
                assert b[key] == self.binding[key], 'Original model plan native binding changed'
            assert plan.started_at <= self.clock() < plan.deadline <= plan.started_at + 12, 'Original model deadline changed'
            self.model_context, self.model_plan = context, plan
            if self.program == 'GUI_CALC': self.deadline = plan.deadline
            else: self.deadline = min(self.entry_deadline, plan.deadline)
            self.probe.deadline = self.deadline
            self.receipt['deadline'] = self.deadline
            self._guard() if self.program == 'GUI_CALC' else self._owned_guard()
            self._phase('MODEL_STARTED', dict(deadline=plan.deadline, expectationSha256=_digest(plan.receipt())))
        except BaseException as exc:
            if self.failed_error is None: self.failed_error = exc
            raise self.failed_error

    def typed(self, evidence):
        try:
            self._expected('ASCII'); self._guard()
            assert any(row is evidence for row in self.record.get('asciiEditorInputs', [])), 'Original counted ASCII receipt is required'
            require_ascii_receipt(evidence, self.marker, self.binding['suiteHwnd'], self.binding['childHwnd'])
            self._phase('ASCII', dict(text=self.marker, receiptSha256=_digest(evidence)))
        except BaseException as exc:
            if self.failed_error is None: self.failed_error = exc
            raise self.failed_error

    def complete_model(self, context, plan):
        try:
            self._expected('MODEL_COMPLETE'); self._guard()
            assert context is self.model_context and plan is self.model_plan and context.plan is plan, 'Original model context/plan changed'
            result = context.complete(plan)  # Existing complete validators and normal cleanup run exactly once.
            self._budget()
            sealed = context.receipt
            assert context.reader is None and sealed['success'] is True and sealed['state'] == 'complete', 'Existing model validator did not seal normal cleanup'
            assert sealed['expectation'] == plan.receipt() and sealed['deadline'] == plan.deadline
            self._phase('MODEL_COMPLETE', dict(deadline=plan.deadline, receiptSha256=_digest(sealed)))
            return result
        except BaseException as exc:
            if self.failed_error is None: self.failed_error = exc
            raise self.failed_error

    def save_phase(self, deadline):
        try:
            self._expected('SAVE_PHASE'); self._budget()
            assert type(deadline) in (int, float) and math.isfinite(deadline) and self.clock() < deadline <= self.clock() + 30, 'Original thirty-second save deadline required'
            self.deadline = deadline; self.probe.deadline = deadline
            self.receipt.update(saveDeadline=deadline,deadline=deadline)
            self._phase('SAVE_PHASE', dict(deadline=deadline, sameEngineHandle=self.handle))
        except BaseException as exc:
            if self.failed_error is None: self.failed_error = exc
            raise self.failed_error

    def __exit__(self, kind, value, traceback):
        primary = self.failed_error if self.failed_error is not None else value
        if primary is None and self.index != len(PROGRAMS[self.program]):
            primary = AssertionError('Original editor program is not complete')
        error = self._finish(primary)
        if error is not None and error is not value: raise error
        return False


class ReaderBoundEditorCommand(CountedEditorShortcuts):
    """One save/close command after the original reader's validated release."""
    navigate = None

    def __init__(self, api, process, binding, shortcut, record, deadline, **options):
        assert shortcut in ('CTRL_S', 'CTRL_W'), 'Unsupported reader-bound editor command'
        clock=options.get('clock',time.monotonic)
        assert type(deadline) in (int,float) and math.isfinite(deadline) and deadline <= clock()+(30 if shortcut=='CTRL_S' else 20), 'Original editor command deadline widened'
        super().__init__(api, process, binding, record, deadline, **options)
        self.shortcut = shortcut
        self.receipt.update(kind='reader-bound-single-editor-command', command=shortcut, deliveryVerified=False)

    def _after_close(self):
        # Closing can legitimately disable/destroy the editor and create an
        # owned prompt. Raw post-input observations must not demand live editor
        # focus; the unchanged exact owned prompt validator follows this call.
        self._budget(); shell = self.probe.process_snapshot(self.process)
        self._budget(); engine = self.probe.engine_snapshot(self.handle)
        assert shell == self.original_shell and engine == self.original_engine, 'Original close command generations changed'
        self._budget(); scope = self.probe.scope_snapshot(self.api, self.binding)
        chains = []
        for edge in ('before', 'after'):
            foreground = scope[edge]['foreground']
            assert foreground['isWindow'] and foreground['pid'] in (self.process.pid, self.binding['officePid']), 'Close command lost owned foreground'
            root = foreground['rootHwnd']; chain = []
            while root != self.binding['suiteHwnd']:
                assert root and len(chain) < 8 and root not in [row['hwnd'] for row in chain], 'Close foreground is not owned by the original document'
                self._budget(); node = self.api._focus_window(root)
                assert node['isWindow'] and node['pid'] == self.process.pid and node['rootHwnd'] == root, 'Close prompt owner is not an original shell window'
                chain.append(node)
                self._budget(); root = int(self.api.user.GetWindow(root, 4) or 0)
            chains.append(chain)
        keyboard = self.probe.keyboard_snapshot(self.thread)
        assert keyboard['targetLayout'] == keyboard['currentThreadLayout'] == US_LAYOUT and keyboard['keysDown'] == [], 'Close command left nonneutral keyboard state'
        assert tuple(keyboard[key] for key in ('capsLockOn', 'scrollLockOn', 'numLockOn')) == self.lock_state, 'Close command lock state changed'
        self._budget()
        return dict(shell=shell, engine=engine, scope=scope, foregroundOwnerChains=chains, keyboard=keyboard,
                    deliveryBasis='Existing exact owned prompt policy must admit transition')

    def press(self):
        assert self.active and not self.finished, 'Reader-bound editor command is not active'
        if self.failed_error is not None: raise self.failed_error
        try:
            assert not self.receipt['actions'], 'Original editor command cannot repeat'
            _insert_once(self, self.shortcut, self._guard, self._after_close if self.shortcut == 'CTRL_W' else self._guard)
        except BaseException as exc:
            self.failed_error = exc; raise

    def __exit__(self, kind, value, traceback):
        primary = self.failed_error if self.failed_error is not None else value
        if primary is None and len(self.receipt['actions']) != 1:
            primary = AssertionError('Original single editor command is not complete')
        error = self._finish(primary)
        if error is not None and error is not value: raise error
        return False
