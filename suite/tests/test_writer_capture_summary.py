"""Project an original strict rejection without replaying or repairing input."""
import ast
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace as NS
import unittest
from unittest import mock

import numeric_notice as notice
import capture_readiness as capture_gate
import test_scenario_editor_shortcuts as scenarios


E2E = Path(__file__).resolve().parents[1] / 'e2e'
SOURCE = E2E / 'writer_capture_summary.py'
spec = importlib.util.spec_from_file_location('writer_capture_summary_tested', SOURCE) if SOURCE.is_file() else None
summary = importlib.util.module_from_spec(spec) if spec else None
if spec: spec.loader.exec_module(summary)


class CaptureQueries:
    def __init__(self, capture=33, thread=44):
        self.capture, self.thread, self.calls = capture, thread, []
    def GetForegroundWindow(self): self.calls.append('foreground'); return 11
    def GetAncestor(self, hwnd, flag): self.calls.append('root'); return 11
    def GetWindowThreadProcessId(self, hwnd, pointer): self.calls.append('thread'); return self.thread
    def GetGUIThreadInfo(self, thread, pointer):
        self.calls.append('gui')
        row = pointer._obj
        row.flags, row.hwndActive, row.hwndFocus, row.hwndCapture = 0, 11, 33, self.capture
        return True
    def IsChild(self, parent, child): self.calls.append('child'); return parent == 22 and child == 33


def environment():
    from test_numeric_notice import environment as base
    return dict(base(), RUNNER_ARCH='X64', OPENGEUL_SUITE_NOTICE_SCOPE='5')


class WriterCaptureSummaryTests(unittest.TestCase):
    def fixture(self, folder, *, capture=33, thread=44, producer=True, timeout=None,monotonic_step=0):
        f = scenarios.ScenarioEditorShortcutsTests.fixture(self, folder)
        process, binding, api, clock, probe, record, attachment = f
        from windows_smoke import Windows, prepare_editor_focus
        queries = CaptureQueries(capture, thread)
        api.user = queries
        api.evidence_output, api.evidence_case = Path(folder).resolve(), 'writer-heading1'
        api.require_foreground = lambda hwnd: Windows.require_foreground(api, hwnd)
        api.require_editor_focus = lambda hwnd, child: Windows.require_editor_focus(api, hwnd, child)
        api.editor_focus_snapshot = lambda *args: probe.scope_snapshot(api, binding)
        record.update(case='writer-heading1', module='writer', kind='native-writer-style', architecture='x64',
            success=False, shellPid=77, officePid=88, officeCreationTime=binding['officeCreationTime'],
            windowHwnd=11, parentHwnd=12, childHwnd=22)
        caught, before_projection = [], []
        def capture_failure(output, name, value, exc):
            caught.append(exc)
            value.update(success=False, numericFailure=notice.capture_failure_code(exc),
                numericFailureFrames=notice.capture_failure_frames(exc))
            before_projection[:] = queries.calls
        def factory(*args):
            session=scenarios.scenario.FirstAdmissionEditorSession(*args, probe=probe, clock=clock)
            retain=session._retain;original_scope=probe.scope_snapshot
            def retained(phase):
                retain(phase)
                if timeout and phase=='input-intent' and session.receipt['actions'][-1]['shortcut']=='CTRL_HOME':
                    if timeout=='before':
                        reads=[]
                        def edge_clock():
                            reads.append(1)
                            if len(reads)>=2:clock.now=session.deadline
                            return clock()
                        session.clock=edge_clock
                    else:
                        def pending(api,binding):
                            row=original_scope(api,binding);row['capture']=copy.deepcopy(row['parent']);return row
                        probe.scope_snapshot=pending
            session._retain=retained
            return session
        proxy = NS(FirstAdmissionEditorSession=factory, prepare_editor_focus=prepare_editor_focus,
            click_owned_editor=lambda *args: None, capture_failure=capture_failure)
        tree = ast.parse((E2E / 'writer_style_smoke.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_gui')
        original = next(n for n in function.body if isinstance(n, ast.Try))
        block = next(n for n in original.body if isinstance(n, ast.With))
        handler = original.handlers if producer else [ast.ExceptHandler(type=ast.Name(id='Exception', ctx=ast.Load()),
            name='exc', body=[ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id='native', ctx=ast.Load()),
                attr='capture_failure', ctx=ast.Load()), args=[ast.Name(id='output', ctx=ast.Load()),
                ast.Name(id='CASE', ctx=ast.Load()), ast.Name(id='record', ctx=ast.Load()),
                ast.Name(id='exc', ctx=ast.Load())], keywords=[]))])]
        module = ast.fix_missing_locations(ast.Module(body=[ast.Try(body=[block], handlers=handler,
            orelse=[], finalbody=[])], type_ignores=[]))
        scope = dict(native=proxy, api=api, process=process, hwnd=11, parent=12, child=22, pid=88,
            record=record, entry_deadline=6., time=NS(monotonic=clock), output=Path(folder), CASE='writer-heading1')
        def sampled_clock():clock.now+=monotonic_step;return clock()
        with mock.patch('time.monotonic', sampled_clock),mock.patch('time.sleep',side_effect=lambda seconds:setattr(clock,'now',clock.now+seconds)):
            exec(compile(module, str(E2E / 'writer_style_smoke.py'), 'exec'), scope)
        self.assertEqual(len(caught), 1)
        self.assertTrue(hasattr(caught[0], 'opengeul_capture_invocation' if timeout else 'opengeul_focus_rejection'), str(caught[0]))
        self.assertEqual(queries.calls, before_projection, 'Supplemental projection made another native query')
        if not timeout:self.assertEqual(len(queries.calls) - queries.calls.index('thread'), 3)
        else:self.assertNotIn('gui',queries.calls)
        self.assertEqual([a['shortcut'] for a in record['editorShortcutSessions'][-1]['actions']], ['CTRL_F6', 'CTRL_HOME'])
        self.assertEqual([row[0] for row in probe.sent], [4] if timeout else [4,4], 'Original input was repeated or CTRL_1 was sent')
        self.assertEqual(sum(call == ('close', 2**41) for call in probe.calls), 1)
        self.assertTrue(record['editorShortcutSessions'][-1]['engineHandleReleased'])
        return record, caught[0]

    def test_actual_readiness_caller_and_callee_clock_samples_do_not_need_equal_deadlines(self):
        with tempfile.TemporaryDirectory() as folder:
            record,primary=self.fixture(folder,timeout='before',producer=False,monotonic_step=.00001)
            readiness=record['editorFocusReadiness'];session=record['editorShortcutSessions'][0]
            self.assertGreater(readiness['deadline'],session['entryDeadline'])
            self.assertEqual(readiness['deadline'],readiness['startedAt']+readiness['deadlineSeconds'])
            self.assertIsNotNone(summary.project_timeout(record,primary))

    def test_original_writer_timeout_has_current_bound_v7_without_sending_home(self):
        for mode,expected in (('before',[47,1,0,0,0,0,1]),('pending',[63,1,1,1,1,3,1])):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                record,primary=self.fixture(folder,timeout=mode)
                self.assertEqual(record.get('numericCaptureGateSnapshot'),expected)
                self.assertIs(primary.opengeul_capture_invocation,capture_gate.current_capture_invocation(record['editorShortcutSessions'][0]))
                self.assertNotIn('numericCaptureSnapshot',record)
                value=notice.project_case_notice('writer-heading1',record,environ=environment())
                self.assertEqual(value['schemaVersion'],7)
                self.assertEqual(value['captureGate'],expected)
                stream=io.StringIO();emitter=notice.NoticeEmitter(environ=environment(),stream=stream)
                self.assertTrue(emitter.emit_case_notice('writer-heading1',record))
                self.assertEqual(len(stream.getvalue().splitlines()),1)
                decoded=notice.decode_notice(stream.getvalue().split('::',2)[-1].strip(),'a'*40,123)
                self.assertEqual(decoded['captureGate'],expected)

    def test_timeout_projection_rejects_stale_primary_mutated_binding_and_unobserved_fields(self):
        for mutate in (lambda r,p:capture_gate._diagnostic_start(r['editorShortcutSessions'][0],p.opengeul_capture_invocation['deadline']),
            lambda r,p:r.update(officeCreationTime=r['officeCreationTime']+1),
            lambda r,p:p.opengeul_capture_invocation.update(lastCheckedAt=float('nan')),
            lambda r,p:p.opengeul_capture_invocation.update(lastCheckedAt=r['editorShortcutSessions'][0]['finishedAt']+1),
            lambda r,p:r['editorShortcutSessions'][0]['actions'][-1].update(inputCallAttempts=1),
            lambda r,p:r['editorShortcutSessions'][0]['actions'][-1].update(beforeInsertion={}),
            lambda r,p:r['editorFocusReadiness'].update(kind='other-proof'),
            lambda r,p:r['editorShortcutSessions'][0]['phases'][0]['proof'].update(focusHwnd=999),
            lambda r,p:r['numericFailureFrames'].pop(),
            lambda r,p:p.opengeul_capture_observation['engine'].update(creationTime=1),
            lambda r,p:p.opengeul_capture_observation['keyboard'].update(keysDown=[17]),
            lambda r,p:p.opengeul_capture_observation['focusKeyboard'].update(numLockOn=False)):
            with tempfile.TemporaryDirectory() as folder:
                record,primary=self.fixture(folder,timeout='pending',producer=False)
                mutate(record,primary)
                self.assertIsNone(summary.project_timeout(record,primary))

    def test_cleanup_cannot_reuse_a_projection_after_current_slot_or_scope_changes(self):
        for mutate in (lambda r:capture_gate._diagnostic_start(r['editorShortcutSessions'][0],0),
            lambda r:capture_gate.current_capture_invocation(r['editorShortcutSessions'][0]).update(lastCheckedAt=float('inf')),
            lambda r:r['editorShortcutSessions'][0]['lastGuardObservation']['engine'].update(creationTime=1)):
            with tempfile.TemporaryDirectory() as folder:
                record,_=self.fixture(folder,timeout='pending')
                self.assertEqual(notice.project_case_notice('writer-heading1',record,environ=environment())['schemaVersion'],7)
                mutate(record)
                self.assertEqual(notice.project_case_notice('writer-heading1',record,environ=environment())['schemaVersion'],2)

    def test_cleanup_cannot_coherently_mutate_vector_and_current_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            record,_=self.fixture(folder,timeout='pending')
            record['numericCaptureGateSnapshot'][1]=5
            capture_gate.current_capture_invocation(record['editorShortcutSessions'][0])['timeoutPhase']=5
            self.assertEqual(notice.project_case_notice('writer-heading1',record,environ=environment())['schemaVersion'],2)

    def test_v7_wire_is_closed_and_cannot_claim_observation_without_presence(self):
        with tempfile.TemporaryDirectory() as folder:
            record,_=self.fixture(folder,timeout='pending')
            stream=io.StringIO();notice.NoticeEmitter(environ=environment(),stream=stream).emit_case_notice('writer-heading1',record)
            value=json.loads(stream.getvalue().split('::',2)[-1])
            mutations=[lambda v:v.update(captureGate=[47,1,1,1,1,3,0]),
                lambda v:v.update(captureGate=[63,2,1,1,0,3,0]),
                lambda v:v.update(captureGate=[63,4,1,1,1,3,0]),
                lambda v:v.update(captureGate=[63,5,1,1,0,3,0]),
                lambda v:v.update(captureGate=[47,1,0,0,0,1,0]),
                lambda v:v.update(captureGate=[63,1,True,1,1,3,0]),
                lambda v:v.update(captureGate=[63,1,1,1,1,6,0]),
                lambda v:v.update(caseCode=3,moduleCode=2),lambda v:v.update(fileCode=1),
                lambda v:v.update(ownedFrames=v['ownedFrames'][1:]),lambda v:v.update(capture=[15,1,1,2,0])]
            for mutate in mutations:
                changed=copy.deepcopy(value);mutate(changed)
                with self.subTest(mutate=mutate),self.assertRaises(ValueError):notice.decode_notice(json.dumps(changed),'a'*40,123)

    def test_timeout_projection_ignores_private_values_and_rejects_foreign_getters(self):
        class NoTouch:
            touched=False
            def __eq__(self,other):self.touched=True;raise AssertionError('Foreign equality ran')
            def __bool__(self):self.touched=True;raise AssertionError('Foreign boolean ran')
            def __str__(self):self.touched=True;raise AssertionError('Private value formatted')
        with tempfile.TemporaryDirectory() as folder:
            record,primary=self.fixture(folder,timeout='pending',producer=False)
            opaque=NoTouch();primary.args=(opaque,)
            record['privateDocument']=opaque
            record['editorShortcutSessions'][0]['originalEngine']['image']=opaque
            self.assertEqual(summary.project_timeout(record,primary),[63,1,1,1,1,3,1])
            self.assertFalse(opaque.touched)
            record['editorShortcutSessions'][0]['expectedProgram']=opaque
            self.assertIsNone(summary.project_timeout(record,primary))
            self.assertFalse(opaque.touched)

    def test_timeout_exception_association_is_bounded_and_not_serialized_in_the_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            record,primary=self.fixture(folder,timeout='before',producer=False)
            for unused in range(33):self.assertIsNotNone(summary.project_timeout(record,primary))
            self.assertEqual(len(summary._TIMEOUT_PROJECTIONS),32)
            raw=json.dumps(record['editorShortcutSessions'][0])
            self.assertNotIn('captureInvocation',raw)
            self.assertNotIn('timeoutPhase',raw)
            self.assertNotIn('lastCheckedAt',raw)

    def test_original_writer_handler_emits_bound_transition_without_repairing_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            record, primary = self.fixture(folder)
            self.assertEqual(record.get('numericCaptureSnapshot'), [15, 1, 1, 2, 1],
                'Original post-guard rejection has no closed capture transition')
            self.assertIs(type(primary), AssertionError)
            self.assertFalse(record['success'])
            session = record['editorShortcutSessions'][-1]
            self.assertEqual(session['deadline'], session['inputDeadline'])
            self.assertEqual(session['actions'][-1]['after']['scope']['capture']['hwnd'], 0)
            self.assertEqual(primary.opengeul_focus_rejection['rawGuiThreadInfo']['hwndCapture'], 33)

    def test_projection_only_compares_raw_handles_and_does_not_claim_capture_owner(self):
        self.assertIsNotNone(summary, 'Closed Writer capture projector is missing')
        for capture, relation in ((22, 1), (33, 2), (12, 3), (11, 4), (2**48 + 9, 5)):
            with self.subTest(capture=capture), tempfile.TemporaryDirectory() as folder:
                record, primary = self.fixture(folder, capture=capture, thread=45, producer=False)
                self.assertEqual(summary.project(record, primary), [15, 1, 0, relation, 1])

    def test_stale_other_case_generation_or_partial_input_cannot_gain_a_transition(self):
        self.assertIsNotNone(summary, 'Closed Writer capture projector is missing')
        with tempfile.TemporaryDirectory() as folder:
            original, primary = self.fixture(folder, producer=False)
            mutations = [lambda r: r.update(case='ime-writer'), lambda r: r.update(stage='save-via-suite-menu'),
                lambda r: r.update(officeCreationTime=r['officeCreationTime'] + 1),
                lambda r: r['editorShortcutSessions'].append(copy.deepcopy(r['editorShortcutSessions'][-1])),
                lambda r: r['editorShortcutSessions'][-1].update(program='GUI_WRITER'),
                lambda r: r['editorShortcutSessions'][-1]['actions'][-1].update(shortcut='CTRL_1'),
                lambda r: r['editorShortcutSessions'][-1]['actions'][0].update(shortcut='CTRL_HOME'),
                lambda r: r['editorShortcutSessions'][-1]['actions'][-1].update(inputCallAttempts=2),
                lambda r: r['editorShortcutSessions'][-1]['actions'][-1].update(insertedInputs=3),
                lambda r: r['editorShortcutSessions'][-1]['actions'][-1]['after']['scope']['capture'].update(hwnd=33),
                lambda r: r['editorShortcutSessions'][-1]['actions'][-1]['after']['engine'].update(creationTime=1),
                lambda r: r['numericFailure'].update(line=r['numericFailure']['line'] + 1),
                lambda r: r['numericFailureFrames'].pop()]
            for mutate in mutations:
                value = copy.deepcopy(original); mutate(value)
                with self.subTest(mutation=mutate): self.assertIsNone(summary.project(value, primary))

    def test_session_finish_time_is_optional_and_never_labels_the_rejection_time(self):
        self.assertIsNotNone(summary, 'Closed Writer capture projector is missing')
        with tempfile.TemporaryDirectory() as folder:
            record, primary = self.fixture(folder, producer=False)
            session = record['editorShortcutSessions'][-1]
            session['finishedAt'] = session['deadline'] + .01
            self.assertEqual(summary.project(record, primary), [15, 1, 1, 2, 0])
            del session['finishedAt']
            self.assertEqual(summary.project(record, primary), [7, 1, 1, 2, 0])

    def test_projection_does_not_format_messages_or_invoke_foreign_getters(self):
        self.assertIsNotNone(summary, 'Closed Writer capture projector is missing')
        class NoTouch:
            touched = False
            def __bool__(self): self.touched = True; raise AssertionError('Foreign getter ran')
            def __str__(self): self.touched = True; raise AssertionError('Private value formatted')
            def __eq__(self, other): self.touched = True; raise AssertionError('Foreign equality ran')
            def __getitem__(self, key): self.touched = True; raise AssertionError('Foreign getter ran')
        with tempfile.TemporaryDirectory() as folder:
            record, primary = self.fixture(folder, producer=False)
            opaque = NoTouch(); primary.args = (opaque,)
            record['privateDocument'] = opaque
            record['editorShortcutSessions'][-1]['originalEngine']['image'] = opaque
            record['editorShortcutSessions'][-1]['actions'][-1]['after']['engine']['image'] = opaque
            self.assertEqual(summary.project(record, primary), [15, 1, 1, 2, 1])
            self.assertFalse(opaque.touched)
            record['editorShortcutSessions'][-1]['actions'][-1]['after']['scope']['focus']['isWindow'] = opaque
            self.assertIsNone(summary.project(record, primary))
            self.assertFalse(opaque.touched, 'Malformed metadata invoked a foreign getter')
            record['editorShortcutSessions'][-1]['actions'][-1]['after']['scope']['focus']['isWindow'] = True
            record['editorShortcutSessions'][-1]['actions'][-1]['after']['scope']['before'] = opaque
            self.assertIsNone(summary.project(record, primary))
            self.assertFalse(opaque.touched, 'Malformed scope invoked a foreign getter')

    def test_secondary_projection_failure_keeps_original_failure_and_cleanup(self):
        def broken(*args): raise OSError('Supplemental projection unavailable')
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(sys.modules, {'writer_capture_summary': NS(project=broken,project_timeout=broken)}):
            record, primary = self.fixture(folder)
            self.assertFalse(record['success'])
            self.assertIs(type(primary), AssertionError)
            self.assertNotIn('numericCaptureSnapshot', record)

    def test_secondary_timeout_projection_base_exception_preserves_original_primary(self):
        def broken(*args):raise KeyboardInterrupt('Synthetic supplemental failure')
        with tempfile.TemporaryDirectory() as folder,mock.patch.dict(sys.modules,
                {'writer_capture_summary':NS(project=lambda *args:None,project_timeout=broken)}):
            record,primary=self.fixture(folder,timeout='before')
            self.assertIs(type(primary),AssertionError)
            self.assertNotIn('numericCaptureGateSnapshot',record)

    def test_notice_v6_is_one_closed_writer_case_and_preserves_legacy_v2(self):
        with tempfile.TemporaryDirectory() as folder:
            record, _ = self.fixture(folder)
            record['bodyText'] = 'PRIVATE_SENTINEL'
            stream = io.StringIO(); emitter = notice.NoticeEmitter(environ=environment(), stream=stream)
            self.assertTrue(emitter.emit_case_notice('writer-heading1', record))
            raw = stream.getvalue().split('::', 2)[-1].strip()
            value = notice.decode_notice(raw, 'a' * 40, 123)
            self.assertEqual(value['schemaVersion'], 6)
            self.assertEqual(value['capture'], [15, 1, 1, 2, 1])
            self.assertEqual(len(stream.getvalue().splitlines()), 1)
            self.assertNotIn('PRIVATE_SENTINEL', raw)
            self.assertNotIn('hwndCapture', raw)
            del record['numericCaptureSnapshot']
            self.assertEqual(notice.project_case_notice('writer-heading1', record, environ=environment())['schemaVersion'], 2)

    def test_v6_rejects_malformed_masks_types_context_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            record, _ = self.fixture(folder)
            value = notice.project_case_notice('writer-heading1', record, environ=environment())
            self.assertEqual(value['schemaVersion'], 6, 'Capture extension is not selected')
            mutations = [lambda v: v.update(scopeCode=3), lambda v: v.update(caseCode=notice.CASES['ime-writer'][0]),
                lambda v: v.update(stageCode=notice.STAGES['focus-editor']),
                lambda v: v.update(capture=[15, True, 1, 2, 1]), lambda v: v.update(capture=[15, 0, 1, 2, 1]),
                lambda v: v.update(capture=[16, 1, 1, 2, 1]), lambda v: v.update(capture=[7, 1, 1, 2, 1]),
                lambda v: v.update(capture=[15, 1, 1, 6, 1]), lambda v: v.update(capture=[15, 1, 1, 2]),
                lambda v: v.update(raw='PRIVATE_SENTINEL')]
            for mutate in mutations:
                changed = copy.deepcopy(value); mutate(changed)
                with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                    notice.decode_notice(json.dumps(changed), 'a' * 40, 123)

    def test_native_cleanup_source_id_is_appended_and_bound_to_its_actual_module(self):
        self.assertEqual(notice.SOURCE_FILES.get('native_cleanup_receipt.py'), 32)
        expected = {name: code for name, code in notice.SOURCE_FILES.items() if code <= 31}
        self.assertEqual(len(expected), 31)
        from native_cleanup_receipt import load_cleanup_receipt
        try: load_cleanup_receipt(b'{"duplicate":1,"duplicate":2}')
        except Exception as exc:
            code = notice.capture_failure_code(exc)
            self.assertEqual(code['fileCode'], 32)
        else: self.fail('Malformed cleanup receipt was accepted')
        scope = {}
        exec(compile('def fail():\n raise ValueError("synthetic")\n', '/foreign/native_cleanup_receipt.py', 'exec'), scope)
        try: scope['fail']()
        except ValueError as exc: self.assertEqual(notice.capture_failure_code(exc)['fileCode'], 0)
