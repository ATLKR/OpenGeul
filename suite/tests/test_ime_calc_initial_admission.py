"""Real focused keyboard and production case argument evaluation, no Windows I/O."""
import ast
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
import korean_ime_smoke as ime
import ime_calc_navigation
import lifecycle_smoke
import test_ime_calc_navigation as navigation_fixtures
import test_ime_keyboard_session as keyboard_fixtures
import test_korean_ime_smoke as policy_fixtures


class CalcInitialAdmissionTests(unittest.TestCase):
    def session(self, directory):
        fixture = navigation_fixtures.KeyboardNavigationTests()
        self.addCleanup(fixture.doCleanups)
        return fixture.session(directory)

    def shell_observer(self, session, data, order, *, change=None):
        def observe(process, suite, evidence):
            self.assertIs(process, session.process)
            self.assertEqual(Path(suite), data.frame.suite)
            self.assertEqual(session.phase, 'focused')
            order.append('retained-shell')
            evidence.update(copy.deepcopy(data.shell))
            if change is not None: change(evidence)
            return evidence['nativeCreation']['fileTime']
        return observe

    def case_navigation(self, session, data, factory, order, *, change=None):
        # Execute the exact original case branch, including argument evaluation.
        # Keep the real keyboard, retained helper, native shell replay and reader
        # policy. Only native Popen observation and reader RPC are boundaries.
        tree = ast.parse((E2E / 'korean_ime_smoke.py').read_text())
        case = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'case')
        branches = [node for node in ast.walk(case) if isinstance(node, ast.If)
                    and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                            and call.func.attr == 'navigate_calc' for call in ast.walk(ast.Module(body=node.body, type_ignores=[])))]
        self.assertEqual(len(branches), 1)
        code = compile(ast.Module(body=[branches[0]], type_ignores=[]), str(E2E / 'korean_ime_smoke.py'), 'exec')
        namespace = dict(ime.__dict__, module='calc', keyboard=session, suite=data.frame.suite,
                         source=data.source, original_bytes=data.original, process=session.process)
        observer = self.shell_observer(session, data, order, change=change)
        with patch.object(lifecycle_smoke, 'retained_writer_shell', side_effect=observer):
            with patch.object(ime_calc_navigation, 'OwnedModelReader', side_effect=factory):
                exec(code, namespace)

    def test_real_case_argument_admission_then_strict_a1_release_f2_end_and_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            session, data, probe, record, factory, order = self.session(directory)
            self.case_navigation(session, data, factory, order)
            self.assertEqual(order, ['retained-shell','start0','CTRL_HOME','read1','release2','F2','CTRL_END'])
            self.assertEqual(session.phase, 'navigated')
            self.assertTrue(record['calcNavigationContext']['success'])
            self.assertEqual(record['calcNavigationContext']['afterCtrlHome']['calcSelection']['range'],
                             dict(sheet=0,startColumn=0,startRow=0,endColumn=0,endRow=0))
            self.assertEqual([row['shortcut'] for row in session.receipt['actions']],
                             ['CTRL_F6','CTRL_HOME','F2','CTRL_END'])
            semantics = keyboard_fixtures.IMEKeyboardSessionTests(); self.addCleanup(semantics.doCleanups)
            semantics.semantic(session, 'pre'); order.append('PRE-cleanup')
            session.api.user = SimpleNamespace(GetKeyboardLayout=lambda tid: 0x04090409)
            record.update(editorTid=session.tid, keyboardFocusHwnd=session.focus)
            def send(prefix):
                session.require_prefix_ready(); order.append('prefix')
                receipt = policy_fixtures.KoreanImePolicyTests().ascii_receipt('calc')
                self.assertEqual(receipt['text'], prefix)
                for action in receipt['actions']:
                    for side in ('before','after'):
                        action[side].update(focusHwnd=session.focus,editorThreadId=session.tid)
                record['asciiEditorInputs'] = [receipt]
            ime.prepare_ascii_prefix(session, 'calc', record, send)
            self.assertEqual(order[-2:], ['PRE-cleanup','prefix'])
            self.assertEqual(record['asciiPrefix'], ' ime-opengeul-calc:')
            self.assertEqual(len(probe.sent), 4)
            session.close(RuntimeError('bounded pre-composition integration ends here'))

    def test_initial_shell_read_has_two_existing_fresh_guards_and_no_action_or_phase_change(self):
        with tempfile.TemporaryDirectory() as directory:
            session, data, probe, record, factory, order = self.session(directory)
            before = len(probe.calls)
            with patch.object(lifecycle_smoke,'retained_writer_shell',side_effect=self.shell_observer(session,data,order)):
                evidence = ime.retained_setup_shell(session.process,data.frame.suite,session,calc_navigation_initial=True)
            self.assertEqual(evidence, data.shell)
            self.assertEqual(session.phase, 'focused')
            self.assertEqual(len(session.receipt['actions']), 1)
            self.assertEqual(len(probe.sent), 1)
            self.assertNotIn('calcNavigationContext', record)
            self.assertEqual(probe.calls[before:].count('shell'), 2)
            self.assertEqual(sum(isinstance(call,tuple) and call[0]=='engine' for call in probe.calls[before:]), 2)
            self.assertEqual(sum(isinstance(call,tuple) and call[0]=='keyboard' for call in probe.calls[before:]), 2)
            session.close(RuntimeError('read-only admission slice ends here'))

    def test_generic_target_and_input_modes_do_not_gain_focused_authority(self):
        for operation in ('require_target','require_prefix_ready','setup_complete','navigate'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                session, data, probe, record, factory, order = self.session(directory)
                with self.assertRaises(AssertionError): getattr(session,operation)()
                self.assertEqual(len(probe.sent), 1)
                self.assertEqual(session.phase, 'focused')
                self.assertNotIn('calcNavigationContext', record)
                session.close()

    def test_read_admission_selector_is_exact_bool_and_default_target_remains_strict(self):
        for selector in (False, 1, None, 'true'):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as directory:
                session,data,probe,record,factory,order=self.session(directory)
                with patch.object(lifecycle_smoke,'retained_writer_shell') as observe:
                    with self.assertRaises(AssertionError) as caught:
                        ime.retained_setup_shell(session.process,data.frame.suite,session,
                                                 calc_navigation_initial=selector)
                observe.assert_not_called(); self.assertEqual(session.phase,'focused')
                self.assertEqual(len(probe.sent),1); session.close(caught.exception)

    def test_initial_read_admission_rejects_wrong_module_phase_existing_context_and_ack_drift(self):
        changes = [lambda s: setattr(s,'module','writer'), lambda s: setattr(s,'phase','navigated'),
            lambda s: setattr(s,'phase','calc-navigation-initial'),lambda s:setattr(s,'phase','semantic-pre-ready'),
            lambda s:setattr(s,'phase','composition'), lambda s:setattr(s,'deadline',s.deadline+1),
            lambda s:s.receipt.pop('editorReadinessAcknowledgedAt'),
            lambda s:s.receipt.update(editorReadinessAcknowledgedAt=float('nan')),
            lambda s:s.receipt['actions'].append(copy.deepcopy(s.receipt['actions'][0])),
            lambda s:s.receipt['actions'][0].update(shortcut='F2'),
            lambda s:s.receipt['actions'][0].update(insertedInputs=3),
            lambda s:s.receipt['actions'][0].update(inputCallAttempts=2),
            lambda s:setattr(s,'calc_navigation',{}),lambda s:setattr(s,'calc_navigation_times',(1.,9.)),
            lambda s:setattr(s,'calc_navigation_url','file:///other.xlsx'),
            lambda s:s.record.update(calcNavigationContext={}),
            lambda s:s.receipt.update(calcNavigationReadiness={})]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                session, data, probe, record, factory, order = self.session(directory)
                change(session); before = list(probe.sent)
                with patch.object(lifecycle_smoke,'retained_writer_shell') as observe:
                    with self.assertRaises(AssertionError):
                        ime.retained_setup_shell(session.process,data.frame.suite,session,calc_navigation_initial=True)
                observe.assert_not_called(); self.assertEqual(probe.sent, before)
                session.close()

    def test_native_guard_or_held_shell_join_failure_precedes_reader_and_ctrlhome(self):
        for failure in ('birth','focus','first-shell-handle','between-guards'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                session, data, probe, record, factory, order = self.session(directory)
                change = None
                if failure=='birth': probe.engine['creationTime'] += 1
                elif failure=='focus': probe.focus = 999
                elif failure=='first-shell-handle': change=lambda evidence:evidence.update(handleValue=123)
                else: change=lambda evidence:probe.engine.update(creationTime=probe.engine['creationTime']+1)
                with self.assertRaises(AssertionError) as caught: self.case_navigation(session,data,factory,order,change=change)
                self.assertNotIn('start0',order); self.assertNotIn('CTRL_HOME',order)
                self.assertEqual(len(probe.sent),1); self.assertNotIn('calcNavigationContext',record)
                session.close(caught.exception)

    def test_actual_case_retains_a1_and_release_failures_without_f2_or_prefix(self):
        for failure in ('a1','release'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                session,data,probe,record,factory,order=self.session(directory)
                if failure=='a1':data.selected=data.row(1,5,7)
                else:data.cleanup['physicalCleanupSucceeded']=False
                with self.assertRaises(AssertionError):self.case_navigation(session,data,factory,order)
                self.assertEqual(order,['retained-shell','start0','CTRL_HOME','read1','release2'])
                self.assertFalse(record['calcNavigationContext']['success'])
                self.assertEqual([a['shortcut'] for a in session.receipt['actions']],['CTRL_F6','CTRL_HOME'])
                self.assertNotIn('asciiPrefix',record);session.close()


if __name__ == '__main__': unittest.main()
