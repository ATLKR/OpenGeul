"""Finite scenario input contracts; real policy with a measured native boundary double."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

import test_counted_editor_shortcuts as coretests

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/scenario_editor_shortcuts.py'
if SOURCE.is_file():
    SPEC = importlib.util.spec_from_file_location('scenario_shortcuts_tested', SOURCE)
    scenario = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(scenario)
else:
    scenario = None


class ScenarioEditorShortcutsTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(scenario, 'Missing distinct finite first-admission editor policy')
    def fixture(self, directory, program='GUI_WRITER'):
        p, b, api, clock, probe, record = coretests.CountedEditorShortcutsTests.fixture(self, directory)
        api.pid = lambda hwnd: 88
        attachment = dict(hwnd=b['suiteHwnd'], parent=b['parentHwnd'], child=b['childHwnd'], officePid=b['officePid'])
        return p, b, api, clock, probe, record, attachment
    def session(self, fixture, program='WRITER_STYLE', marker=None):
        p, b, api, clock, probe, record, attachment = fixture
        return scenario.FirstAdmissionEditorSession(api, p, attachment, program, record, 6., marker=marker, probe=probe, clock=clock)
    def ready(self, fixture):
        from windows_smoke import prepare_editor_focus
        p, b, api, clock, probe, record, _ = fixture
        api.editor_focus_snapshot = lambda *args: probe.scope_snapshot(api, b)
        with self.session(fixture) as session:
            prepare_editor_focus(api, 11, 22, 77, 88, record, lambda: None, lambda: session.press('CTRL_F6'))
            session.editor_ready(record['editorFocusReadiness'])
            session.press('CTRL_HOME'); session.press('CTRL_1')
        return session
    def ascii_receipt(self, text):
        from ascii_editor_input import ascii_actions, input_buffer
        snapshot = dict(editorThreadId=44, focusHwnd=33, targetLayout=0x04090409, currentThreadLayout=0x04090409,
                        keysDown=[], capsLockOn=False, foregroundVerified=True, editorFocusVerified=True)
        return dict(schemaVersion=1, text=text, inputMethod='SendInput-scancode', unicodeInputUsed=False,
                    documentHwnd=11, childHwnd=22, inputSize=40, pauseSeconds=.04, success=True,
                    actions=[dict(**row, before=snapshot, after=snapshot, bufferHex=bytes(input_buffer(row['events'])).hex(),
                                  requested=len(row['events']), inserted=len(row['events'])) for row in ascii_actions(text)])
    def enter_ready(self, session, fixture):
        from windows_smoke import prepare_editor_focus
        p, b, api, clock, probe, record, _ = fixture
        api.editor_focus_snapshot = lambda *args: probe.scope_snapshot(api, b)
        prepare_editor_focus(api, 11, 22, 77, 88, record, lambda: None, lambda: session.press('CTRL_F6'))
        session.editor_ready(record['editorFocusReadiness'])
    def test_style_first_admits_native_generation_without_reader_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory); session = self.ready(f)
            receipt = session.receipt
            self.assertTrue(receipt['success']); self.assertNotIn('expectedBinding', receipt)
            self.assertIn('first', receipt['engineAdmissionBasis'])
            self.assertEqual([a['shortcut'] for a in receipt['actions']], ['CTRL_F6', 'CTRL_HOME', 'CTRL_1'])
            self.assertEqual(sum(c == ('open', 88) for c in f[4].calls), 1)
            self.assertEqual(sum(c == ('close', 2**41) for c in f[4].calls), 1)
            self.assertEqual(receipt['originalEngine']['creationTime'], 134370146624845933)

    def test_first_admission_generation_must_join_later_reader_bound_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory); self.ready(f)
            p, b, api, clock, probe, record, _ = f
            b['officeCreationTime'] += 1; probe.engine['creationTime'] += 1
            before = len(probe.sent)
            with self.assertRaisesRegex(AssertionError, 'shortcut.*generation|generation.*shortcut'):
                with scenario.ReaderBoundEditorCommand(api,p,b,'CTRL_S',record,10.,probe=probe,clock=clock) as command:
                    command.press()
            self.assertEqual(len(probe.sent),before)

    def test_pending_entry_has_one_ctrl_f6_and_readiness_without_navigation_or_typing(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            with self.session(f,'PENDING_CALC_ENTRY') as session: self.enter_ready(session,f)
            self.assertEqual([a['shortcut'] for a in session.receipt['actions']],['CTRL_F6'])
    def test_closed_programs_reject_unknown_repeated_or_out_of_order_keys(self):
        for key in ('CTRL_S', 'CTRL_END', '^s', 'ESCAPE'):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                with self.assertRaisesRegex(AssertionError, 'program'):
                    with self.session(f) as session: session.press(key)
                self.assertEqual(f[4].sent, [])
    def test_wrong_attachment_or_activation_generation_prevents_input(self):
        for mutate in (lambda f: f[6].update(parent=999), lambda f: setattr(f[0], 'opengeul_activation_binding', ('wrong',))):
            with tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); mutate(f)
                with self.assertRaises(AssertionError):
                    with self.session(f): self.fail('Invalid attachment admitted')
                self.assertEqual(f[4].sent, [])
    def test_engine_older_than_original_shell_is_not_a_first_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            f=self.fixture(directory);f[4].engine['creationTime']=f[4].shell['creationTime']-1
            with self.assertRaisesRegex(AssertionError,'predates|older'):
                with self.session(f):self.fail('An engine predating original shell was admitted')
            self.assertEqual(f[4].sent,[])
    def test_ctrl_f6_allows_owned_setup_focus_but_navigation_requires_actual_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory); probe = f[4]
            original_scope = probe.scope_snapshot
            def root_scope(api, binding):
                row = original_scope(api, binding)
                if probe.focus == 11:
                    row['focus'] = copy.deepcopy(row['before']['suite']); row['focusWithinEditor'] = False
                return row
            probe.scope_snapshot = root_scope; probe.focus = 11
            with self.assertRaisesRegex(AssertionError, 'readiness'):
                with self.session(f) as session:
                    session.press('CTRL_F6')
                    session.editor_ready(dict(ready=True))
            self.assertEqual(len(probe.sent), 1)
    def test_ctrl_f6_admits_only_host_to_exact_original_child_during_durable_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            f=self.fixture(directory);probe=f[4];probe.focus=11;original_scope=probe.scope_snapshot
            def scope(api,binding):
                row=original_scope(api,binding)
                if probe.focus==11:row['focus']=copy.deepcopy(row['before']['suite']);row['focusWithinEditor']=False
                return row
            probe.scope_snapshot=scope;f[2].require_editor_focus=lambda *args:probe.focus
            with self.session(f,'PENDING_CALC_ENTRY') as session:
                retain=session._retain
                def transition(stage):
                    retain(stage)
                    if stage=='input-intent':probe.focus=22
                session._retain=transition;self.enter_ready(session,f)
            action=session.receipt['actions'][0]
            self.assertEqual((action['before']['scope']['focus']['hwnd'],action['beforeInsertion']['scope']['focus']['hwnd']),(11,22))
            self.assertEqual(action['inputCallAttempts'],1);self.assertEqual(action['insertedInputs'],4)
            self.assertEqual(len(probe.sent),1)
    def test_first_admission_capture_settles_before_its_single_original_ctrl_f6(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            f=self.fixture(directory);probe=f[4];original=probe.scope_snapshot;reads=[]
            def scope(api,binding):
                row=original(api,binding);reads.append(row)
                if len(reads)==1:row['capture']=copy.deepcopy(row['parent'])
                return row
            probe.scope_snapshot=scope
            with patch('time.sleep',side_effect=lambda seconds:setattr(f[3],'now',f[3].now+seconds)):
                with self.session(f,'PENDING_CALC_ENTRY') as session:self.enter_ready(session,f)
            self.assertEqual(len(probe.sent),1)
            self.assertEqual(session.receipt['captureReadiness']['pollCount'],1)
    def test_ctrl_f6_drift_does_not_admit_editor_to_host_or_host_to_other_editor_descendant(self):
        for first,last in ((33,11),(11,33)):
            with self.subTest(first=first,last=last),tempfile.TemporaryDirectory() as directory:
                f=self.fixture(directory);probe=f[4];probe.focus=first;original=probe.scope_snapshot
                def scope(api,binding):
                    row=original(api,binding)
                    if probe.focus==11:row['focus']=copy.deepcopy(row['before']['suite']);row['focusWithinEditor']=False
                    return row
                probe.scope_snapshot=scope
                with self.assertRaisesRegex(AssertionError,'Focus changed'):
                    with self.session(f,'PENDING_CALC_ENTRY') as session:
                        retain=session._retain
                        def transition(stage):
                            retain(stage)
                            if stage=='input-intent':probe.focus=last
                        session._retain=transition;session.press('CTRL_F6')
                self.assertEqual(probe.sent,[])
    def test_ascii_phase_requires_exact_counted_receipt_before_save(self):
        for mutation in (lambda r: r.update(text='other'), lambda r: r['actions'][0].update(inserted=0)):
            with tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); marker = 'UI-OpenGeul-writer'
                with self.assertRaises(AssertionError):
                    with self.session(f, 'GUI_WRITER', marker) as session:
                        self.enter_ready(session, f); session.press('CTRL_END')
                        receipt = self.ascii_receipt(marker); mutation(receipt); session.typed(receipt)
                self.assertEqual([a['shortcut'] for a in session.receipt['actions']], ['CTRL_F6', 'CTRL_END'])
    def test_writer_and_impress_exact_programs_preserve_single_save(self):
        for module, navigation in [('writer', ['CTRL_END']), ('impress', ['TAB', 'F2', 'CTRL_END'])]:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); marker = 'UI-OpenGeul-' + module
                with self.session(f, 'GUI_' + module.upper(), marker) as session:
                    self.enter_ready(session, f)
                    for preset in navigation: session.press(preset)
                    receipt = self.ascii_receipt(marker); f[5].setdefault('asciiEditorInputs', []).append(receipt)
                    session.typed(receipt); session.save_phase(31.); session.press('CTRL_S')
                self.assertEqual([a['shortcut'] for a in session.receipt['actions']], ['CTRL_F6', *navigation, 'CTRL_S'])
                self.assertEqual(session.receipt['saveDeadline'], 31.)
                self.assertEqual(f[4].deadline, 31.)
    def test_partial_and_unknown_inputs_stop_and_only_release_known_owned_prefix(self):
        for count, releases in ((2, 1), (None, 0), (OSError('unknown return'), 0)):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); f[4].counts = [count]
                with self.assertRaises(BaseException):
                    with self.session(f) as session: session.press('CTRL_F6')
                self.assertEqual(sum(isinstance(c, tuple) and c[0] == 'release' for c in f[4].calls), releases)
                self.assertFalse(session.receipt['success']); self.assertTrue(session.receipt['engineHandleReleased'])
    def test_entry_deadline_and_foreign_keys_are_not_repaired(self):
        for mutate in (lambda f: setattr(f[3], 'now', 6.), lambda f: setattr(f[4], 'keys_down', [0x11]),
                       lambda f: setattr(f[4], 'layout', 0x04120412)):
            with tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); mutate(f)
                with self.assertRaises(AssertionError):
                    with self.session(f): self.fail('Unsafe entry admitted')
                self.assertEqual(f[4].sent, [])
    def test_native_intent_retention_generation_change_blocks_event(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            with self.assertRaisesRegex(AssertionError, 'generation'):
                with self.session(f) as session:
                    retain = session._retain
                    def changed(phase):
                        retain(phase)
                        if phase == 'input-intent': f[4].engine['creationTime'] += 1
                    session._retain = changed; session.press('CTRL_F6')
            self.assertEqual(f[4].sent, [])
    def test_incomplete_program_fails_and_unknown_program_is_not_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            with self.assertRaisesRegex(AssertionError, 'complete'):
                with self.session(f) as session: session.press('CTRL_F6')
            with self.assertRaises((AssertionError, ValueError)): self.session(f, 'ARBITRARY_PROGRAM')
    def test_pending_commands_are_distinct_mandatory_reader_bound_and_never_enter(self):
        for preset in ('CTRL_S', 'CTRL_W'):
            with self.subTest(preset=preset), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); p, b, api, clock, probe, record, _ = f
                with scenario.ReaderBoundEditorCommand(api, p, b, preset, record, 10., probe=probe, clock=clock) as command:
                    command.press()
                self.assertEqual([a['shortcut'] for a in command.receipt['actions']], [preset])
                self.assertEqual(command.receipt['expectedBinding'], b)
                self.assertFalse(command.receipt['deliveryVerified'])
                self.assertEqual(len(probe.sent), 1)

    def model_context(self, fixture, *, error=None):
        expectation = dict(binding=copy.deepcopy(fixture[1]), startedAt=1., deadline=13.)
        plan = NS(binding=fixture[1], started_at=1., deadline=13., receipt=lambda: copy.deepcopy(expectation))
        context = NS(plan=plan, reader=object(), deadline=13., receipt={})
        def complete(actual):
            self.assertIs(actual, plan)
            if error: raise error
            context.reader = None
            context.receipt.update(success=True, state='complete', deadline=13., expectation=plan.receipt())
        context.complete = Mock(side_effect=complete)
        return context, plan

    def test_calc_preserves_original_model_deadline_single_enter_completion_and_save_order(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory); marker = 'UI-OpenGeul-calc'; context, plan = self.model_context(f)
            with self.session(f, 'GUI_CALC', marker) as session:
                self.enter_ready(session, f); session.join_model(context, plan)
                self.assertEqual(session.deadline, plan.deadline)
                for preset in ('CTRL_HOME', 'F2', 'CTRL_END'): session.press(preset)
                receipt = self.ascii_receipt(marker); f[5].setdefault('asciiEditorInputs', []).append(receipt)
                session.typed(receipt); session.press('ENTER'); session.complete_model(context, plan)
                session.save_phase(31.); session.press('CTRL_S')
            context.complete.assert_called_once_with(plan)
            self.assertEqual([a['shortcut'] for a in session.receipt['actions']], ['CTRL_F6', 'CTRL_HOME', 'F2', 'CTRL_END', 'ENTER', 'CTRL_S'])
            self.assertEqual([p['step'] for p in session.receipt['phases']], ['EDITOR_READY', 'MODEL_STARTED', 'ASCII', 'MODEL_COMPLETE', 'SAVE_PHASE'])

    def test_calc_model_begin_spends_original_twelve_seconds_without_temporary_input_cap(self):
        for returned_at in (7.,14.):
            with self.subTest(returned_at=returned_at),tempfile.TemporaryDirectory() as directory:
                f=self.fixture(directory);marker='UI-OpenGeul-calc';context,plan=self.model_context(f)
                def run():
                    with self.session(f,'GUI_CALC',marker) as session:
                        self.enter_ready(session,f)
                        f[3].now=returned_at  # The unchanged reader begin started at1, deadline13.
                        session.join_model(context,plan)
                        self.assertEqual(session.deadline,13.)
                        for preset in ('CTRL_HOME','F2','CTRL_END'):session.press(preset)
                        receipt=self.ascii_receipt(marker);f[5].setdefault('asciiEditorInputs',[]).append(receipt)
                        session.typed(receipt);session.press('ENTER');session.complete_model(context,plan)
                        session.save_phase(returned_at+30);session.press('CTRL_S')
                if returned_at==7.:run()
                else:
                    with self.assertRaisesRegex(AssertionError,'deadline'):run()
                    self.assertEqual(len(f[4].sent),1)

    def test_lifecycle_invokes_original_complete_once_and_preserves_original_failure_object(self):
        for error in (None, RuntimeError('original exact body/newline model failure')):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory); marker = '-LIFECYCLE-NEW-'; context, plan = self.model_context(f, error=error)
                def run():
                    with self.session(f, 'LIFECYCLE_WRITER', marker) as session:
                        session.join_model(context, plan); self.enter_ready(session, f)
                        self.assertEqual(session.deadline, 13.)
                        session.press('CTRL_END')
                        receipt = self.ascii_receipt(marker); f[5].setdefault('asciiEditorInputs', []).append(receipt)
                        session.typed(receipt); session.complete_model(context, plan)
                if error:
                    with self.assertRaises(RuntimeError) as raised: run()
                    self.assertIs(raised.exception, error)
                else: run()
                context.complete.assert_called_once_with(plan)
                self.assertEqual(len(f[4].sent), 2)

    def test_close_owned_foreign_document_is_not_original_prompt_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory); p, b, api, clock, probe, record, _ = f
            probe.after_send = lambda: setattr(probe, 'foreground', 999)
            api.user = NS(GetWindow=lambda hwnd, relation: 0)
            api._focus_window = lambda hwnd: dict(hwnd=hwnd, isWindow=True, pid=77, rootHwnd=hwnd)
            with self.assertRaisesRegex(AssertionError, 'original|owned'):
                with scenario.ReaderBoundEditorCommand(api, p, b, 'CTRL_W', record, 10., probe=probe, clock=clock) as command:
                    command.press()
            self.assertEqual(len(probe.sent), 1)


if __name__ == '__main__': unittest.main()
