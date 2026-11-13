"""Real post-input/session policy with native boundary doubles; no Windows proof."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import owned_control_actions as policy
import lifecycle_smoke as life
from test_owned_control_actions import Clock, ControlProbe
import test_scenario_editor_shortcuts as scenario_tests

scenario = scenario_tests.scenario


CAPTION = 'OpenGeul Writer — 다른 이름으로 저장'


class PostShortcutPickerTests(unittest.TestCase):
    def fixture(self, directory):
        process = NS(pid=77, _handle=1234, args=[str(Path(directory)/'OpenGeul.Office.exe')],
            opengeul_suite_root=Path(directory), opengeul_evidence_output=Path(directory),
            opengeul_evidence_case='save-transition')
        clock = Clock(); boundary = ControlProbe(process, clock)
        native = object.__new__(policy.NativeControlProbe)
        native.clock, native.deadline = clock, 6.
        native.user = NS(IsWindow=lambda hwnd: True)
        native.foreground = lambda: 11
        before = copy.deepcopy(boundary.value)
        after = copy.deepcopy(before)
        after['document']['enabled'] = after['scope']['enabled'] = False
        dialog = dict(before['document'], hwnd=44, rootHwnd=44, ownerHwnd=11,
            className='#32770', title=CAPTION)
        after.update(foreground=dialog, foregroundOwnerChain=[44,11])
        after['gui'].update(activeHwnd=44, focusHwnd=101, focusPid=77, focusRootHwnd=44, flags=1)
        state = NS(after=False, freshReads=0, uiaReads=0, onUia=lambda: None)
        native.foreground = lambda: 44 if state.after else 11
        native._window = lambda hwnd: copy.deepcopy(
            after['foreground'] if hwnd==44 else after['document'] if state.after else before['document'])
        native.native_focus = lambda thread: copy.deepcopy(after['gui'] if state.after else before['gui'])
        native.process_snapshot = lambda proc: copy.deepcopy(boundary.identity)
        def snapshot(*args):
            state.after = True; state.freshReads += 1
            return copy.deepcopy(after)
        native.target_snapshot = snapshot
        root = dict(nativeHwnd=44, pid=77, runtimeId=[42,44], controlType='Window',
            name=CAPTION, visible=True, enabled=True)
        def raw(element):
            state.uiaReads += 1; state.onUia()
            return copy.deepcopy(root)
        native._raw = raw
        desktop = lambda **kw: NS(window=lambda **kw: NS(wrapper_object=lambda: NS(element_info=NS(_element=object()))))
        boundary.transition_snapshot = native.transition_snapshot
        record = dict(attachments=[dict(hwnd=11,parent=55,child=56,officePid=88)])
        return process, clock, boundary, native, after, root, state, desktop, record

    def run_shortcut(self, fixture):
        process, clock, boundary, native, after, root, state, desktop, record = fixture
        with patch.dict(sys.modules, {'pywinauto': NS(Desktop=desktop)}):
            return policy.send_host_menu_shortcut(object(), process, 11, object(), record,
                shortcut='CTRL_S', caption=CAPTION, probe=boundary, clock=clock)

    def test_new_picker_between_foreground_and_full_snapshot_keeps_one_real_shortcut(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory); error = None; value = None
            try: value = self.run_shortcut(f)
            except BaseException as exc: error = exc
            self.assertIsNone(error, 'A newly visible exact owned modal was treated as a disabled input target')
            self.assertTrue(value['success']); self.assertEqual(value['after']['transition'], 'exact-owned-save-picker')
            self.assertEqual((value['inputCallAttempts'],value['requestedInputs'],value['insertedInputs']), (1,4,4))
            self.assertEqual(sum(isinstance(x,tuple) and x[0]=='send' for x in f[2].calls), 1)
            self.assertEqual(value['deadline'],6.); self.assertFalse(value['atomicRecipientDeliveryProved'])
            self.assertEqual(f[6].freshReads,1); self.assertEqual(f[6].uiaReads,1)
            self.assertTrue(value['engineHandleClosed']); self.assertEqual(value['dpiScope'],{})

    def test_foreign_replacement_wrong_native_focus_and_capture_never_accept_modal(self):
        changes = [('foreground','pid',88),('foreground','threadId',10),('foreground','ownerHwnd',99),
            ('foreground','rootHwnd',99),('foreground','title','Other'),('foreground','className','Other'),
            ('foreground','visible',False),('foreground','enabled',False),('document','threadId',10),
            ('gui','threadId',10),('gui','focusPid',88),('gui','focusRootHwnd',99),
            ('gui','activeHwnd',99),('gui','captureHwnd',99),('gui','menuOwnerHwnd',11),('gui','flags',4)]
        for section,key,value in changes:
            with self.subTest(section=section,key=key), tempfile.TemporaryDirectory() as directory:
                f=self.fixture(directory);f[4][section][key]=value
                with self.assertRaises(AssertionError):self.run_shortcut(f)
                action=f[8]['ownedControlActions'][0]
                self.assertFalse(action['success']);self.assertIsNot(action['after'].get('accepted'),True)
                self.assertEqual(action['inputCallAttempts'],1);self.assertEqual(action['insertedInputs'],4)

    def test_wrong_uia_root_or_hidden_modal_never_accepts_native_only_match(self):
        for key,value in [('nativeHwnd',45),('pid',88),('runtimeId',[]),('controlType','MenuBar'),
                          ('name','Other'),('visible',False),('enabled',False)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as directory:
                f=self.fixture(directory);f[5][key]=value
                with self.assertRaises(AssertionError):self.run_shortcut(f)
                self.assertFalse(f[8]['ownedControlActions'][0]['success'])

    def test_post_uia_owner_generation_and_deadline_drift_remain_fatal_without_retry(self):
        for change in ('owner','generation','deadline'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                f=self.fixture(directory)
                def drift():
                    if change=='owner':f[4]['foreground']['ownerHwnd']=99
                    elif change=='generation':f[2].identity['creationTime']+=1
                    else:f[1].now=6.
                f[6].onUia=drift
                with self.assertRaises(AssertionError):self.run_shortcut(f)
                self.assertFalse(f[8]['ownedControlActions'][0]['success'])
                self.assertEqual(sum(isinstance(x,tuple) and x[0]=='send' for x in f[2].calls),1)


class LifecycleGuardBoundaryTests(unittest.TestCase):
    def run_edit(self, directory, *, after_ready=None):
        fixture_owner=scenario_tests.ScenarioEditorShortcutsTests();f=fixture_owner.fixture(directory)
        process,binding,api,clock,probe,record,attachment=f
        record['attachments']=[attachment];context,plan=fixture_owner.model_context(f)
        context.begin=lambda marker:plan;context.abort=Mock();api.title=lambda hwnd:'* Writer'
        # Repeating the one-shot GUI query is distinct from the real session's
        # fresh full original-generation/capture/layout guard used below.
        api.require_editor_focus=Mock(side_effect=AssertionError('bare focus query raced with capture'))
        api.editor_focus_snapshot=lambda *args:probe.scope_snapshot(api,binding)
        case=object.__new__(life.Case);case.api=api;case.process=process;case.record=record
        case.prepared_library={'kind':'test-only-prepared'};case._writer_model_context=lambda *args:context
        sessions=[];typed=[]
        def factory(api,process,attachment,program,record,deadline,*,marker):
            session=scenario.FirstAdmissionEditorSession(api,process,attachment,program,record,deadline,
                marker=marker,probe=probe,clock=clock);sessions.append(session)
            ready=session.editor_ready
            def observed(evidence):
                ready(evidence)
                if after_ready:after_ready(probe)
            session.editor_ready=observed;return session
        def ascii_input(*args,**kwargs):
            self.assertEqual(kwargs['pause'],.025);self.assertEqual(kwargs['deadline'],plan.deadline)
            typed.append(1);receipt=fixture_owner.ascii_receipt('-LIFECYCLE-NEW-')
            record.setdefault('asciiEditorInputs',[]).append(receipt);return receipt
        desktop=lambda **kw:NS(window=lambda **kw:NS(wrapper_object=lambda:NS()))
        with patch.dict(sys.modules,{'pywinauto':NS(Desktop=desktop)}), \
             patch.object(life.time,'monotonic',clock), \
             patch.object(life.native,'activate_owned_suite',lambda *args:None), \
             patch.object(life.native,'click_owned_editor',lambda *args:None), \
             patch.object(life.native,'FirstAdmissionEditorSession',factory), \
             patch.object(life.native.ascii_input,'type_ascii',ascii_input):
            error=None
            try:case.edit(11,22,'-LIFECYCLE-NEW-')
            except BaseException as exc:error=exc
        return f,context,plan,sessions,typed,error

    def test_edit_uses_real_full_session_guards_without_duplicate_bare_focus_query(self):
        with tempfile.TemporaryDirectory() as directory:
            f,context,plan,sessions,typed,error=self.run_edit(directory)
            self.assertIsNone(error, 'Lifecycle repeated the incoherent one-shot query instead of its following strict phase guard')
            self.assertEqual([a['shortcut'] for a in sessions[0].receipt['actions']],['CTRL_F6','CTRL_END'])
            self.assertEqual(typed,[1]);context.complete.assert_called_once_with(plan)
            f[2].require_editor_focus.assert_not_called();self.assertEqual(sessions[0].deadline,13.)

    def test_next_real_navigation_guard_still_rejects_new_foreign_foreground(self):
        with tempfile.TemporaryDirectory() as directory:
            f,context,plan,sessions,typed,error=self.run_edit(directory,
                after_ready=lambda probe:setattr(probe,'foreground',999))
            self.assertIsInstance(error,AssertionError);self.assertNotIn('bare focus',str(error))
            self.assertEqual(len(f[4].sent),1);self.assertEqual(typed,[]);context.complete.assert_not_called()
            self.assertFalse(sessions[0].receipt['success']);self.assertTrue(sessions[0].receipt['engineHandleReleased'])

    def test_next_real_navigation_guard_still_rejects_new_foreign_capture(self):
        def captured(probe):
            original=probe.scope_snapshot
            def scope(api,binding):
                row=original(api,binding)
                row['capture']=dict(hwnd=999,isWindow=True,pid=99,threadId=99,rootHwnd=999,className='Foreign')
                return row
            probe.scope_snapshot=scope
        with tempfile.TemporaryDirectory() as directory:
            f,context,plan,sessions,typed,error=self.run_edit(directory,after_ready=captured)
            self.assertIsInstance(error,AssertionError);self.assertNotIn('bare focus',str(error))
            self.assertEqual(len(f[4].sent),1);self.assertEqual(typed,[]);context.complete.assert_not_called()
            self.assertFalse(sessions[0].receipt['success']);self.assertTrue(sessions[0].receipt['engineHandleReleased'])
