"""Missing focus is a noninput admission state, never an input recipient."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_scenario_editor_shortcuts as fixtures


class InitialFocusAdmissionTests(unittest.TestCase):
    def fixture(self,directory):
        helper=fixtures.ScenarioEditorShortcutsTests()
        value=helper.fixture(directory);p,b,api,clock,probe,record,attachment=value
        original=probe.scope_snapshot;probe.focus=0;host_reads=[]
        def scope(api,binding):
            row=original(api,binding)
            if probe.focus==0:
                row['focus']=dict(hwnd=0,isWindow=False,pid=0,threadId=0,rootHwnd=0,className='')
                row['focusWithinEditor']=False
            return row
        probe.scope_snapshot=scope
        def host(hwnd):
            self.assertEqual(hwnd,11);host_reads.append(hwnd)
            return copy.deepcopy(original(api,b)['before']['suite'])
        api._focus_window=host;api.require_editor_focus=lambda *args:probe.focus
        api.editor_focus_snapshot=lambda *args:probe.scope_snapshot(api,b)
        api.pid=lambda hwnd:88
        probe.host_reads=host_reads
        return helper,value

    def test_initial_missing_focus_admits_no_recipient_then_one_click_and_strict_ctrl_f6(self):
        from windows_smoke import prepare_editor_focus
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory);p,b,api,clock,probe,record,_=f;clicks=[]
            with helper.session(f,'PENDING_CALC_ENTRY') as session:
                row=session.receipt['admissionSnapshot']
                self.assertEqual(row['scope']['focus']['hwnd'],0)
                self.assertIsNone(row['focusKeyboard'])
                witness=row['initialMissingFocusAdmission']
                self.assertEqual(witness['kind'],'owned-initial-admission-without-focus')
                self.assertIsNone(witness['inputRecipientHwnd'])
                self.assertFalse(witness['physicalInputAllowed'])
                self.assertEqual(witness['hostKeyboardThreadId'],45)
                self.assertEqual(witness['hostBefore'],witness['hostAfter'])
                def click():clicks.append('click');probe.focus=22
                prepare_editor_focus(api,11,22,77,88,record,click,lambda:session.press('CTRL_F6'))
                session.editor_ready(record['editorFocusReadiness'])
            self.assertEqual(clicks,['click']);self.assertEqual(len(probe.sent),1)
            self.assertEqual([a['shortcut'] for a in session.receipt['actions']],['CTRL_F6'])
            self.assertNotIn(('keyboard',0),probe.calls)
            self.assertTrue(session.receipt['success']);self.assertTrue(session.receipt['engineHandleReleased'])

    def test_zero_focus_before_actual_ctrl_f6_remains_fatal_without_insertion(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory)
            with self.assertRaisesRegex(AssertionError,'owned root or editor focus'):
                with helper.session(f,'PENDING_CALC_ENTRY') as session:
                    session.receipt['allowMissingFocus']=True
                    session.press('CTRL_F6')
            self.assertEqual(f[4].sent,[]);self.assertTrue(session.receipt['engineHandleReleased'])
            self.assertNotIn(('keyboard',0),f[4].calls)

    def test_initial_mode_cannot_be_reused_after_session_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory)
            with self.assertRaises(AssertionError):
                with helper.session(f,'PENDING_CALC_ENTRY') as session:
                    session._initial_admission_guard()
            self.assertEqual(f[4].sent,[])

    def test_foreign_foreground_or_changed_ancestry_or_zero_editor_thread_never_admits(self):
        for mode in ('foreign','ancestry','editor-thread','owned-child-foreground'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                helper,f=self.fixture(directory);probe=f[4]
                if mode=='foreign':probe.foreground=99
                elif mode=='ancestry':probe.ancestry=False
                elif mode=='editor-thread':probe.thread=0
                else:probe.foreground=22
                with self.assertRaises(AssertionError):
                    with helper.session(f,'PENDING_CALC_ENTRY'):self.fail('Unsafe missing focus admitted')
                self.assertEqual(probe.sent,[])
                self.assertNotIn(('keyboard',0),probe.calls)

    def test_nonzero_foreign_focus_cannot_select_initial_missing_focus_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory);probe=f[4];probe.focus=99
            with self.assertRaises(AssertionError):
                with helper.session(f,'PENDING_CALC_ENTRY'):self.fail('Foreign focus admitted')
            self.assertEqual(probe.host_reads,[]);self.assertEqual(probe.sent,[])

    def test_missing_focus_requires_exact_native_integer_zero_and_false_liveness(self):
        variants=[(key,value) for key in ('hwnd','pid','threadId','rootHwnd') for value in (False,0.)]
        variants.append(('isWindow',0))
        for key,value in variants:
            with self.subTest(key=key,type=type(value).__name__),tempfile.TemporaryDirectory() as directory:
                helper,f=self.fixture(directory);probe=f[4];original=probe.scope_snapshot
                def scope(api,binding):
                    row=original(api,binding);row['focus'][key]=value;return row
                probe.scope_snapshot=scope
                with self.assertRaises(AssertionError):
                    with helper.session(f,'PENDING_CALC_ENTRY'):pass
                self.assertEqual(probe.host_reads,[]);self.assertEqual(probe.sent,[])

    def test_typed_initial_witness_does_not_accept_boolean_schema_or_host_thread(self):
        for key in ('schemaVersion','hostKeyboardThreadId'):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as directory:
                helper,f=self.fixture(directory);probe=f[4];api=f[2]
                if key=='hostKeyboardThreadId':
                    original_scope=probe.scope_snapshot;original_host=api._focus_window
                    def scope(api,binding):
                        row=original_scope(api,binding)
                        for edge in ('before','after'):
                            row[edge]['suite']['threadId']=row[edge]['foreground']['threadId']=1
                        return row
                    def host(hwnd):row=original_host(hwnd);row['threadId']=1;return row
                    probe.scope_snapshot=scope;api._focus_window=host
                session=helper.session(f,'PENDING_CALC_ENTRY');original=session._observe_owned_guard
                def observe(**kwargs):
                    row=original(**kwargs);row['initialMissingFocusAdmission'][key]=True;return row
                session._observe_owned_guard=observe
                entered=[]
                with self.assertRaises(AssertionError):
                    with session:entered.append(True)
                self.assertEqual(entered,[])
                self.assertEqual(probe.sent,[])

    def test_host_thread_identity_change_rejects_without_a_keyboard_input(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory);api=f[2];original=api._focus_window;reads=[]
            def host(hwnd):
                row=original(hwnd);reads.append(row)
                if len(reads)==2:row['threadId']+=1
                return row
            api._focus_window=host
            with self.assertRaises(AssertionError):
                with helper.session(f,'PENDING_CALC_ENTRY'):self.fail('Changed host thread admitted')
            self.assertEqual(f[4].sent,[])

    def test_generation_change_during_host_keyboard_sample_is_not_admitted(self):
        for process in ('shell','engine'):
            with self.subTest(process=process),tempfile.TemporaryDirectory() as directory:
                helper,f=self.fixture(directory);probe=f[4];original=probe.keyboard_snapshot
                def keyboard(thread):
                    row=original(thread)
                    if thread==45:getattr(probe,process)['creationTime']+=1
                    return row
                probe.keyboard_snapshot=keyboard
                with self.assertRaises(AssertionError):
                    with helper.session(f,'PENDING_CALC_ENTRY'):self.fail('Changed generation admitted')
                self.assertEqual(probe.sent,[])

    def test_explicit_host_keyboard_must_have_original_us_layout_and_neutral_keys(self):
        for mode in ('layout','keys','caps'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                helper,f=self.fixture(directory);probe=f[4];original=probe.keyboard_snapshot
                def keyboard(thread):
                    row=original(thread)
                    if thread==45:
                        if mode=='layout':row['targetLayout']=0x04120412
                        elif mode=='keys':row['keysDown']=[0x11]
                        else:row['capsLockOn']=True
                    return row
                probe.keyboard_snapshot=keyboard
                with self.assertRaises(AssertionError):
                    with helper.session(f,'PENDING_CALC_ENTRY'):self.fail('Unsafe host keyboard admitted')
                self.assertEqual(probe.sent,[])

    def test_known_owned_capture_can_settle_only_under_original_entry_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory);probe=f[4];original=probe.scope_snapshot;pending=[True]
            def scope(api,binding):
                row=original(api,binding)
                if pending[0]:row['capture']=copy.deepcopy(row['parent'])
                return row
            probe.scope_snapshot=scope
            def pause(seconds):f[3].now+=seconds;pending[0]=False
            with patch('time.sleep',side_effect=pause):
                with self.assertRaisesRegex(AssertionError,'complete'):
                    with helper.session(f,'PENDING_CALC_ENTRY') as session:
                        self.assertEqual(session.receipt['captureReadiness']['pollCount'],1)
                        self.assertEqual(session.receipt['deadline'],6.)
            self.assertEqual(probe.sent,[])

    def test_foreign_capture_is_not_a_pending_admission_state(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory);probe=f[4];original=probe.scope_snapshot
            def scope(api,binding):
                row=original(api,binding);row['capture']=dict(hwnd=99,isWindow=True,pid=99,threadId=99,rootHwnd=99)
                return row
            probe.scope_snapshot=scope
            with self.assertRaises(AssertionError):
                with helper.session(f,'PENDING_CALC_ENTRY'):self.fail('Foreign capture admitted')
            self.assertEqual(probe.sent,[])

    def test_late_host_sample_preserves_original_deadline_and_releases_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            helper,f=self.fixture(directory);api=f[2];original=api._focus_window
            def late(hwnd):row=original(hwnd);f[3].now=6.;return row
            api._focus_window=late
            with self.assertRaisesRegex(AssertionError,'deadline'):
                with helper.session(f,'PENDING_CALC_ENTRY') as session:self.fail('Late sample admitted')
            self.assertEqual(f[4].sent,[])
            self.assertEqual(sum(call==('close',2**41) for call in f[4].calls),1)


if __name__=='__main__':unittest.main()
