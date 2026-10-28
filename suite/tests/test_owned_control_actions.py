"""Native control policy boundaries; synthetic calls are not Windows evidence."""
import copy
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class CallerRedTests(unittest.TestCase):
    def test_base_clicks_original_save_menu_once_without_keyboard_shortcut(self):
        import windows_smoke as native
        from test_base_save_readiness import NativeBoundary
        b = NativeBoundary([lambda b: []])
        calls = []
        def legacy(*args, **kwargs): raise AssertionError('Opaque keyboard input reached')
        modules = b.modules(); modules['pywinauto.keyboard'] = NS(send_keys=legacy)
        def measured_click(*args, **kwargs): calls.append(('click', kwargs['purpose']))
        def counted(*args, **kwargs): raise AssertionError('Base Save must use its measured menu item')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'fixtures').mkdir()
            with patch.dict(sys.modules, modules), \
                 patch.object(native, 'click_owned_control', measured_click, create=True), \
                 patch.object(native, 'send_host_menu_shortcut', counted, create=True), \
                 patch.object(native, '_wait_base_save_controls', side_effect=RuntimeError('STOP_AFTER_TRIGGER')):
                try: native.save_new_base(b.api, b.process, 11, root/'fixtures', root, {})
                except BaseException as exc: error = str(exc)
        self.assertEqual(error, 'STOP_AFTER_TRIGGER', 'Base still uses opaque shortcut input')
        self.assertEqual(calls, [('click', 'FILE_MENU'), ('click', 'SAVE_MENU')])

    def test_lifecycle_preserves_file_click_and_ctrl_shift_s_without_opaque_keyboard(self):
        import lifecycle_smoke as life
        menu = NS(element_info=NS(name='파일', process_id=77), is_visible=lambda: True,
                  is_enabled=lambda: True, click_input=lambda: None)
        window = NS(descendants=lambda **kw: [menu])
        calls = []; process = NS(pid=77); api = NS(require_foreground=lambda hwnd: None)
        case = NS(api=api, process=process, record={})
        def legacy(*a, **k): raise AssertionError('Opaque keyboard input reached')
        with patch.dict(sys.modules, {'pywinauto': NS(Desktop=lambda **kw:NS(window=lambda **kw:NS(wrapper_object=lambda:window))),
                                      'pywinauto.keyboard': NS(send_keys=legacy)}), \
             patch.object(life.native, 'activate_owned_suite'), \
             patch.object(life.native, 'click_owned_control', side_effect=lambda *a,**k:calls.append(('click',k['purpose'])), create=True), \
             patch.object(life.native, 'send_host_menu_shortcut', side_effect=lambda *a,**k:calls.append(('shortcut',k['shortcut'])), create=True):
            error = None
            try: life.Case.shell_command(case, 11, '^+s')
            except BaseException as exc: error = str(exc)
        self.assertIsNone(error, 'Lifecycle still uses opaque host shortcut')
        self.assertEqual(calls, [('click', 'FILE_MENU'), ('shortcut', 'CTRL_SHIFT_S')])

    def test_exact_base_caption_uses_existing_native_filename_transaction(self):
        import lifecycle_smoke as life
        from test_lifecycle_smoke import LifecycleSmokeTests
        api, root, field, calls = LifecycleSmokeTests().picker_fixture()
        caption = 'OpenGeul Base — 다른 이름으로 저장'
        root.element_info.name = caption; api.title = lambda h: caption
        error = None; record = {}
        try: life.set_owned_picker_filename(api, 31, 100, 500, root, field,
                                           'D:\\owned\\New-OpenGeul-base.odb', record, expected_title=caption)
        except BaseException as exc: error = str(exc)
        self.assertIsNone(error, 'Exact Base dialog is not admitted to strict filename assignment')
        self.assertEqual(record['pickerFilenameInputs'][0]['after'], 'D:\\owned\\New-OpenGeul-base.odb')


class PolicyAvailabilityRed(unittest.TestCase):
    def test_control_policy_exists_before_foreign_or_unmeasured_effects_can_pass(self):
        self.assertTrue((E2E/'owned_control_actions.py').is_file(), 'Strict owned control action policy is missing')


class Clock:
    def __init__(self): self.now = 1.
    def __call__(self): return self.now


class ControlProbe:
    def __init__(self, process, clock):
        self.clock = clock; self.calls = []; self.process = process
        self.identity = dict(pid=77, handleValue=1234, image=str((process.opengeul_suite_root/'OpenGeul.Office.exe').resolve()),
                             creationTime=134370148289625043, waitResult=258)
        doc = dict(hwnd=11, pid=77, threadId=9, rootHwnd=11, visible=True, enabled=True,
                   iconic=False, cloaked=0, rectangle=[0,0,900,700], ownerHwnd=0, title='OpenGeul Writer', className='Form')
        self.value = dict(document=doc, scope=copy.deepcopy(doc),
            control=dict(runtimeId=[42,20], pid=77, nativeHwnd=20, automationId='', controlType='MenuItem',
                         name='파일', visible=True, enabled=True, rectangle=[10,30,50,50]),
            ancestry=[dict(runtimeId=[42,20],pid=77,nativeHwnd=20,controlType='MenuItem'),
                      dict(runtimeId=[42,21],pid=77,nativeHwnd=21,controlType='MenuBar'),
                      dict(runtimeId=[42,11],pid=77,nativeHwnd=11,controlType='Window')],
            focusAncestry=[dict(runtimeId=[42,20],pid=77,nativeHwnd=20,controlType='MenuItem'),
                           dict(runtimeId=[42,21],pid=77,nativeHwnd=21,controlType='MenuBar'),
                           dict(runtimeId=[42,11],pid=77,nativeHwnd=11,controlType='Window')],
            nativeFocusUnderMenu=True,
            gui=dict(threadId=9,activeHwnd=11,focusHwnd=20,focusPid=77,focusRootHwnd=11,
                     captureHwnd=0,menuOwnerHwnd=0,flags=0),
            foreground=copy.deepcopy(doc), foregroundOwnerChain=[11])
        self.hit = dict(point=[30,40],hitHwnd=20,pid=77,rootHwnd=11,withinControl=True,uiaMatches=True)
        self.keys = dict(targetLayout=0x04090409,currentThreadLayout=0x04090409,keysDown=[],
                         capsLockOn=False,scrollLockOn=False,numLockOn=True)
        self.inserted = None; self.fail = None; self.after_move = None; self.after_input = None
        self.engine=dict(pid=88,handleValue=2345,image=str((process.opengeul_suite_root/'Office/program/soffice.bin').resolve()),creationTime=134370148305653808,waitResult=258)
    def enter_dpi(self,r): r.update(previousContext=18,verified=True); self.calls.append('dpi-enter')
    def restore_dpi(self,r): r['restored']=self.fail!='restore'; self.calls.append('dpi-restore')
    def process_snapshot(self,p): return copy.deepcopy(self.identity)
    def target_snapshot(self,*args,**kwargs): return copy.deepcopy(self.value)
    def point_snapshot(self,*args): return copy.deepcopy(self.hit)
    def move(self,point,r):
        self.calls.append('move');r.update(pointerMoveAttempts=1,pointerReadback=list(point))
        if self.after_move:self.after_move(self)
    def click(self,r):
        self.calls.append('click');r.update(inputCallAttempts=1,insertedInputs=None,clickCompleted=False)
        if self.fail=='click':raise OSError('click insertion unknown')
        r.update(insertedInputs=2,clickCompleted=True)
        if self.after_input:self.after_input(self)
    def keyboard_snapshot(self,thread): return copy.deepcopy(self.keys)
    def keyboard_plan(self,shortcut):
        scans={'CTRL_S':[0x1d,0x1f],'CTRL_SHIFT_S':[0x1d,0x2a,0x1f],'ESCAPE':[1]}[shortcut]
        events=[dict(vk=0,scan=s,flags=8) for s in scans]+[dict(vk=0,scan=s,flags=10) for s in reversed(scans)]
        return events,events
    def send(self,payload):
        self.calls.append(('send',copy.deepcopy(payload)))
        if self.fail=='send':raise OSError('native return unavailable')
        if self.after_input:self.after_input(self)
        return len(payload) if self.inserted is None else self.inserted
    def owned_release_events(self,events,inserted):
        from counted_editor_shortcuts import owned_release_events
        return owned_release_events(events,inserted)
    def release(self,events):
        self.calls.append(('release',copy.deepcopy(events)))
        if self.fail=='release':raise OSError('owned release failed')
        return len(events)
    def transition_snapshot(self,*args,**kwargs):return dict(originalDocumentAlive=True,originalDialogAlive=False,accepted=True)
    def open_engine(self,pid):self.calls.append(('open-engine',pid));return 2345
    def engine_snapshot(self,handle):return copy.deepcopy(self.engine)
    def close_engine(self,handle):self.calls.append(('close-engine',handle));return self.fail!='close-engine'
    def attachment_snapshot(self,binding):return dict(binding=dict(binding),valid=True,focusUnderOriginalChild=True)


class ControlPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((E2E/'owned_control_actions.py').is_file(), 'Strict owned control action policy is missing')
        spec=importlib.util.spec_from_file_location('actual_owned_control_actions',E2E/'owned_control_actions.py')
        self.policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.policy)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.process=NS(pid=77,_handle=1234,args=[str(self.root/'OpenGeul.Office.exe')],
            opengeul_suite_root=self.root,opengeul_evidence_output=self.root,opengeul_evidence_case='tile-base')
        self.clock=Clock();self.probe=ControlProbe(self.process,self.clock);self.api=object();self.control=object();self.record={}
    def click(self,**kw):
        return self.policy.click_owned_control(self.api,self.process,11,self.control,self.record,
            purpose='FILE_MENU',probe=self.probe,clock=self.clock,**kw)
    def shortcut(self,**kw):
        self.record.setdefault('attachments',[dict(hwnd=11,parent=55,child=56,officePid=88)])
        return self.policy.send_host_menu_shortcut(self.api,self.process,11,self.control,self.record,
            shortcut='CTRL_S',caption='OpenGeul Writer — 다른 이름으로 저장',probe=self.probe,clock=self.clock,**kw)
    def test_file_click_has_durable_intent_before_one_move_and_one_native_click(self):
        def inspect(probe):
            paths=list(self.root.glob('*click-intent.json'));self.assertEqual(len(paths),1)
            self.assertEqual(json.loads(paths[0].read_bytes())['clickAttempts'],1)
        self.probe.after_input=inspect
        value=self.click();self.assertTrue(value['success'])
        self.assertEqual(self.probe.calls,['dpi-enter','move','click','dpi-restore'])
        self.assertEqual(value['chosenPhysicalPoint'],[30,40]);self.assertEqual(value['insertedInputs'],2)
    def test_foreign_or_mismatched_physical_hit_has_zero_effects(self):
        for field,bad in [('pid',88),('rootHwnd',99),('withinControl',False),('uiaMatches',False)]:
            with self.subTest(field=field):
                self.probe.hit[field]=bad
                with self.assertRaises(AssertionError):self.click()
                self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
                self.probe.hit.update(pid=77,rootHwnd=11,withinControl=True,uiaMatches=True)
                self.record={};self.process.opengeul_control_sequence=getattr(self.process,'opengeul_control_sequence',0)
    def test_geometry_or_generation_drift_after_move_never_clicks(self):
        self.probe.after_move=lambda p:p.value['control']['rectangle'].__setitem__(2,51)
        with self.assertRaises(AssertionError):self.click()
        self.assertEqual(self.probe.calls,['dpi-enter','move','dpi-restore'])
    def test_expired_move_callback_never_reaches_click_and_still_restores_dpi(self):
        self.probe.after_move=lambda p:setattr(self.clock,'now',20.)
        with self.assertRaises(AssertionError):self.click()
        self.assertNotIn('click',self.probe.calls);self.assertEqual(self.probe.calls[-1],'dpi-restore')
    def test_unknown_mouse_insertion_is_not_retried(self):
        self.probe.fail='click'
        with self.assertRaisesRegex(OSError,'unknown'):self.click()
        self.assertEqual(self.probe.calls.count('click'),1);self.assertEqual(self.probe.calls[-1],'dpi-restore')
        self.assertIsNone(self.record['ownedControlActions'][0]['insertedInputs'])
    def test_same_pid_popup_without_original_owner_chain_or_menu_focus_is_rejected(self):
        self.probe.value['foreground']['hwnd']=99;self.probe.value['foreground']['rootHwnd']=99
        self.probe.value['foregroundOwnerChain']=[99]
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_original_owned_menu_popup_requires_both_owner_and_native_menu_owner(self):
        self.probe.value['foreground'].update(hwnd=99,rootHwnd=99,ownerHwnd=11)
        self.probe.value['foregroundOwnerChain']=[99,11]
        self.probe.value['gui'].update(activeHwnd=11,focusHwnd=20,menuOwnerHwnd=11,flags=4)
        value=self.shortcut();self.assertTrue(value['success'])
        self.assertEqual(len([c for c in self.probe.calls if isinstance(c,tuple) and c[0]=='send']),1)
    def test_counted_shortcut_retains_before_effect_and_after_count(self):
        def inspect(probe):self.assertEqual(len(list(self.root.glob('*input-intent.json'))),1)
        self.probe.after_input=inspect
        value=self.shortcut();self.assertEqual(value['requestedInputs'],4);self.assertEqual(value['insertedInputs'],4)
        self.assertTrue(value['nativeInsertionCountVerified']);self.assertFalse(value['atomicRecipientDeliveryProved'])
    def test_held_modifier_or_wrong_layout_causes_no_keyboard_effect(self):
        self.probe.keys['keysDown']=[0x11]
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_known_partial_shortcut_releases_only_owned_prefix_even_after_deadline(self):
        self.probe.inserted=1;self.probe.after_input=lambda p:setattr(self.clock,'now',20.)
        with self.assertRaises(AssertionError):self.shortcut()
        releases=[c for c in self.probe.calls if isinstance(c,tuple) and c[0]=='release']
        self.assertEqual(releases,[('release',[dict(vk=0,scan=0x1d,flags=10)])])
    def test_unknown_shortcut_return_has_no_speculative_modifier_release(self):
        self.probe.fail='send'
        with self.assertRaisesRegex(OSError,'unavailable'):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='release' for c in self.probe.calls))
    def test_original_popen_generation_mismatch_blocks_every_effect(self):
        self.process.opengeul_control_binding=(77,1234,str(self.root/'OpenGeul.Office.exe'),1,258)
        with self.assertRaises(AssertionError):self.click()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_dpi_restore_failure_fails_qualified_click(self):
        self.probe.fail='restore'
        with self.assertRaises(AssertionError):self.click()
        self.assertFalse(self.record['ownedControlActions'][0]['success'])
    def dialog(self, purpose='SAVE_BUTTON'):
        scope=copy.deepcopy(self.probe.value['scope']);scope.update(hwnd=44,rootHwnd=44,ownerHwnd=11,
            title='OpenGeul Base — 다른 이름으로 저장',className='#32770',rectangle=[0,0,400,300])
        self.probe.value.update(scope=scope,foreground=copy.deepcopy(scope),foregroundOwnerChain=[44,11])
        self.probe.value['document']['enabled']=False
        self.probe.value['control'].update(nativeHwnd=102,automationId='1',controlType='Button',name='Save',runtimeId=[42,102])
        self.probe.value['ancestry']=[dict(runtimeId=[42,102],pid=77,nativeHwnd=102),dict(runtimeId=[42,44],pid=77,nativeHwnd=44)]
        self.probe.value['gui'].update(activeHwnd=44,focusHwnd=101,focusRootHwnd=44,focusPid=77)
        self.probe.hit.update(hitHwnd=102,rootHwnd=44)
        self.readiness=dict(ready=True,shellPid=77,documentHwnd=11,dialogHwnd=44,caption=scope['title'],uiaRootRuntimeId=[42,44],
            wrapperBindings=[dict(properties=dict(runtimeId=[42,101],nativeHwnd=101)),dict(properties=dict(runtimeId=[42,102],nativeHwnd=102))])
    def save(self):
        return self.policy.click_owned_control(self.api,self.process,11,self.control,self.record,purpose='SAVE_BUTTON',
            dialog=44,caption=self.readiness['caption'],readiness=self.readiness,probe=self.probe,clock=self.clock)
    def test_save_click_binds_exact_dialog_owner_runtime_and_button_before_one_effect(self):
        self.dialog();value=self.save();self.assertTrue(value['success']);self.assertEqual(value['clickAttempts'],1)
    def test_dialog_owner_or_root_replacement_blocks_all_input(self):
        for mode in ('owner','root-runtime','button-runtime'):
            with self.subTest(mode=mode):
                self.dialog()
                if mode=='owner':self.probe.value['scope']['ownerHwnd']=99
                elif mode=='root-runtime':self.readiness['uiaRootRuntimeId']=[42,99]
                else:self.readiness['wrapperBindings'][1]['properties']['runtimeId']=[42,999]
                with self.assertRaises(AssertionError):self.save()
                self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_release_error_preserves_original_partial_insertion_failure(self):
        self.probe.inserted=1;self.probe.fail='release'
        error=None
        try:self.shortcut()
        except BaseException as exc:error=exc
        self.assertIsInstance(error,AssertionError,'Owned release replaced the original partial insertion failure')
        self.assertIn('partial',str(error))
        self.assertIn('ownedKeyRelease',self.record['ownedControlActions'][0])
        self.assertIn('error',self.record['ownedControlActions'][0]['ownedKeyRelease'])
    def test_original_dialog_destruction_is_an_allowed_post_action_transition(self):
        probe,context=self.native_dialog_probe([False])
        value=self.native_dialog_transition(probe,context)
        self.assertTrue(value['accepted']);self.assertEqual(value['transition'],'original-owned-dialog-destroyed')
    def test_raw_uia_provider_strings_are_bounded_before_retention_or_effects(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a)
        element=NS(CurrentNativeWindowHandle=20,CurrentBoundingRectangle=NS(left=0,top=0,right=40,bottom=20),
            CurrentControlType=50011,GetRuntimeId=lambda:[42,20],CurrentName='파일',CurrentAutomationId='x'*257,
            CurrentProcessId=77,CurrentIsOffscreen=False,CurrentIsEnabled=True)
        with self.assertRaises(AssertionError):probe._raw(element)
    def native_dialog_probe(self, states):
        self.probe=ControlProbe(self.process,self.clock)
        self.dialog()
        probe=object.__new__(self.policy.NativeControlProbe)
        probe.clock=self.clock;probe.deadline=self.clock()+5
        pending=iter(states);probe.user=NS(IsWindow=lambda hwnd:True if hwnd==11 else next(pending))
        probe.process_snapshot=lambda process:copy.deepcopy(self.probe.identity)
        probe._window=lambda hwnd:copy.deepcopy(self.probe.value['document' if hwnd==11 else 'scope'])
        probe.target_snapshot=lambda *a:(_ for _ in ()).throw(AssertionError('Retained child UIA was queried after input'))
        context=dict(document={k:self.probe.value['document'][k] for k in ('hwnd','pid','threadId','rootHwnd','rectangle')},
            scope={k:self.probe.value['scope'][k] for k in ('hwnd','pid','threadId','rootHwnd','ownerHwnd','rectangle')},
            originalProcess=copy.deepcopy(self.probe.identity),attachment=None)
        return probe,context
    def native_dialog_transition(self, probe, context, evidence=None):
        return probe.transition_snapshot(None,self.process,11,44,self.readiness['caption'],'SAVE_BUTTON',object(),
            context=context,evidence=evidence)
    def disappearing_class_probe(self, states):
        probe,context=self.native_dialog_probe(states)
        original_window=probe._window
        probe.window_snapshot=original_window
        probe.user.GetWindowTextW=lambda hwnd,buffer,size:0
        probe.user.GetClassNameW=lambda hwnd,buffer,size:0
        probe._window=lambda hwnd:(original_window(hwnd) if hwnd==11
            else self.policy.NativeControlProbe._window(probe,hwnd))
        return probe,context
    def test_dialog_destruction_between_liveness_and_class_read_is_revalidated(self):
        probe,context=self.disappearing_class_probe([True,False]);evidence={}
        value=self.native_dialog_transition(probe,context,evidence)
        self.assertTrue(value['accepted']);self.assertEqual(value['transition'],'original-owned-dialog-destroyed')
        self.assertTrue(value['dialogClassQueryDisappearance'])
        self.assertFalse(value['originalDialogAlive'])
    def test_class_query_failure_on_still_live_dialog_is_not_a_transition(self):
        probe,context=self.disappearing_class_probe([True,True]);evidence={}
        with self.assertRaises(AssertionError):self.native_dialog_transition(probe,context,evidence)
        self.assertIsNot(evidence.get('accepted'),True)
    def test_class_query_disappearance_still_requires_original_process_and_deadline(self):
        for failure in ('process','deadline'):
            with self.subTest(failure=failure):
                self.clock.now=1.;probe,context=self.disappearing_class_probe([True,False]);evidence={};calls=[]
                def identity(process):
                    calls.append(1);value=copy.deepcopy(self.probe.identity)
                    if len(calls)>1:
                        if failure=='process':value['creationTime']+=1
                        else:self.clock.now=probe.deadline
                    return value
                probe.process_snapshot=identity
                with self.assertRaises(AssertionError):self.native_dialog_transition(probe,context,evidence)
                self.assertIsNot(evidence.get('accepted'),True)
    def test_stale_child_uia_is_never_queried_while_native_dialog_destruction_is_pending(self):
        probe,context=self.native_dialog_probe([True,False]);error=None;value={}
        try:value=self.native_dialog_transition(probe,context)
        except BaseException as exc:error=exc
        self.assertIsNone(error,'Native dialog observation touched the invalidated child provider')
        self.assertTrue(value['accepted']);self.assertEqual(value['transition'],'original-owned-dialog-destroyed')
        self.assertEqual(value['dialogObservationCount'],2)
        self.assertEqual(value['lastLiveDialog']['ownerHwnd'],11)
    def test_native_dialog_never_destroyed_remains_failed_under_the_original_action_deadline(self):
        probe,context=self.native_dialog_probe([True]*10);self.probe.transition_snapshot=probe.transition_snapshot
        def wait(seconds):self.clock.now+=2.5
        with patch.object(self.policy.time,'sleep',side_effect=wait):
            with self.assertRaisesRegex(AssertionError,'deadline'):self.save()
        value=self.record['ownedControlActions'][0]
        self.assertFalse(value['success']);self.assertEqual(value['inputCallAttempts'],1)
        self.assertEqual(value['insertedInputs'],2);self.assertEqual(self.probe.calls.count('click'),1)
        self.assertEqual(value['deadline'],6.);self.assertTrue(value['dpiScope']['restored'])
    def test_native_dialog_death_at_or_after_deadline_cannot_be_accepted(self):
        for at in (6.,7.):
            with self.subTest(at=at):
                self.clock.now=1.;probe,context=self.native_dialog_probe([False]);evidence={}
                def is_window(hwnd):
                    if hwnd==44:self.clock.now=at;return False
                    return True
                probe.user.IsWindow=is_window
                with self.assertRaisesRegex(AssertionError,'deadline'):self.native_dialog_transition(probe,context,evidence)
                self.assertIsNot(evidence.get('accepted'),True)
    def test_pending_native_dialog_replacement_is_rejected_before_eventual_destruction(self):
        for field,bad in [('pid',88),('threadId',99),('rootHwnd',99),('ownerHwnd',99),('className','Other'),('title','Other')]:
            with self.subTest(field=field):
                probe,context=self.native_dialog_probe([True,False]);self.probe.value['scope'][field]=bad;evidence={}
                with self.assertRaisesRegex(AssertionError,'dialog.*identity|dialog.*changed'):
                    self.native_dialog_transition(probe,context,evidence)
                self.assertIsNot(evidence.get('accepted'),True)
    def test_pending_dialog_rechecks_original_process_generation_before_acceptance(self):
        probe,context=self.native_dialog_probe([True,False]);calls=[]
        def identity(process):
            calls.append(1);value=copy.deepcopy(self.probe.identity)
            if len(calls)>1:value['creationTime']+=1
            return value
        probe.process_snapshot=identity;evidence={}
        with self.assertRaisesRegex(AssertionError,'process.*changed'):
            self.native_dialog_transition(probe,context,evidence)
        self.assertIsNot(evidence.get('accepted'),True)
    def test_pending_dialog_rechecks_original_document_identity_before_acceptance(self):
        probe,context=self.native_dialog_probe([True,False]);calls=[]
        def window(hwnd):
            row=copy.deepcopy(self.probe.value['document' if hwnd==11 else 'scope'])
            if hwnd==11:
                calls.append(1)
                if len(calls)>1:row['threadId']+=1
            return row
        probe._window=window;evidence={}
        with self.assertRaisesRegex(AssertionError,'document.*identity'):
            self.native_dialog_transition(probe,context,evidence)
        self.assertIsNot(evidence.get('accepted'),True)
    def test_native_query_failure_does_not_turn_into_a_destroyed_dialog_transition(self):
        probe,context=self.native_dialog_probe([True,False]);evidence={}
        def window(hwnd):raise OSError('native query unavailable')
        probe._window=window
        with self.assertRaisesRegex(OSError,'unavailable'):self.native_dialog_transition(probe,context,evidence)
        self.assertIsNot(evidence.get('accepted'),True)
    def raw_element(self, value):
        return NS(CurrentNativeWindowHandle=value,CurrentBoundingRectangle=NS(left=0,top=0,right=40,bottom=20),
            CurrentControlType=50011,GetRuntimeId=lambda:[42,20],CurrentName='파일',CurrentAutomationId='',
            CurrentProcessId=77,CurrentIsOffscreen=False,CurrentIsEnabled=True)
    def test_successful_null_uia_hwnd_is_the_only_noninteger_normalization(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a);value=None;error=None
        try:value=probe._raw(self.raw_element(None))
        except BaseException as exc:error=exc
        self.assertIsNone(error,'Documented successful UIA_HWND null must normalize to zero')
        self.assertEqual(value['nativeHwnd'],0);self.assertIsNone(value['nativeHwndRaw'])
        self.assertEqual(value['nativeHwndRawType'],'NoneType')
    def test_invalid_uia_hwnd_types_and_ranges_fail_with_raw_diagnostics(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a)
        for value in (True,False,0.,1.,'0','1',-(2**31)-1,2**32,[],object()):
            with self.subTest(type=type(value).__name__,value=repr(value)):
                with self.assertRaisesRegex(AssertionError,'CurrentNativeWindowHandle.*type=.*value='):
                    probe._raw(self.raw_element(value))
    def test_signed_and_zero_uia_hwnd_values_preserve_the_exact_successful_raw_integer(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a)
        for raw in (0,20,-1,-(2**31),2**32-1):
            with self.subTest(raw=raw):
                value=probe._raw(self.raw_element(raw));self.assertEqual(value['nativeHwnd'],raw&0xffffffff)
                self.assertIn('nativeHwndRaw',value,'Successful raw native handle value was discarded')
                self.assertIs(type(value['nativeHwndRaw']),int);self.assertEqual(value['nativeHwndRaw'],raw)
                self.assertEqual(value['nativeHwndRawType'],'int')
    def test_uia_hwnd_property_exception_is_not_normalized_to_null(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a)
        class Failed:
            @property
            def CurrentNativeWindowHandle(self):raise OSError('UIA property failed')
        with self.assertRaisesRegex(OSError,'UIA property failed'):probe._raw(Failed())
    def test_pointer_intent_write_cannot_hide_a_new_physical_obstruction(self):
        with patch.object(self.policy.os,'fsync',side_effect=lambda fd:self.probe.hit.update(uiaMatches=False)):
            with self.assertRaises(AssertionError):self.click()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_click_intent_write_is_followed_by_fresh_exact_target_guard(self):
        count=0
        def retain(fd):
            nonlocal count
            count+=1
            if count==2:self.probe.value['control']['runtimeId']=[42,999]
        with patch.object(self.policy.os,'fsync',side_effect=retain):
            with self.assertRaises(AssertionError):self.click()
        self.assertNotIn('click',self.probe.calls)
    def test_keyboard_intent_write_is_followed_by_fresh_native_key_state_guard(self):
        with patch.object(self.policy.os,'fsync',side_effect=lambda fd:self.probe.keys.update(keysDown=[0x11])):
            with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_partial_input_releases_known_keys_despite_recovery_retention_failure(self):
        self.probe.inserted=1;writes=0
        def retain(fd):
            nonlocal writes
            writes+=1
            if writes>=2:raise OSError('recovery receipt unavailable')
        error=None
        with patch.object(self.policy.os,'fsync',side_effect=retain):
            try:self.shortcut()
            except BaseException as exc:error=exc
        self.assertIsInstance(error,AssertionError,'Retention replaced native partial failure')
        self.assertIn('partial',str(error))
        self.assertEqual(len([c for c in self.probe.calls if isinstance(c,tuple) and c[0]=='release']),1)
        intent=json.loads(next(self.root.glob('*input-intent.json')).read_bytes())
        self.assertIn('releasePlans',intent)
    def test_short_owned_release_return_is_recorded_as_secondary_failure(self):
        self.probe.inserted=1;self.probe.release=lambda payload:0
        with self.assertRaisesRegex(AssertionError,'partial'):self.shortcut()
        recovery=self.record['ownedControlActions'][0]['ownedKeyRelease']
        self.assertIn('error',recovery)
    def test_virtual_save_button_keeps_exact_uia_identity_and_physical_hit_requirement(self):
        self.dialog();self.probe.value['control']['nativeHwnd']=0
        self.probe.value['ancestry'][0]['nativeHwnd']=0;self.readiness['wrapperBindings'][1]['properties']['nativeHwnd']=0
        error=None
        try:value=self.save()
        except BaseException as exc:error=exc
        self.assertIsNone(error,'An exact native-owned UIA virtual Button was rejected only for its null HWND')
        self.assertTrue(value['success'])
    def test_plain_host_focus_without_menu_ancestry_cannot_admit_shortcut(self):
        self.probe.value['focusAncestry']=[dict(runtimeId=[42,55],pid=77,nativeHwnd=55,controlType='Edit')]
        self.probe.value['nativeFocusUnderMenu']=False
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_file_pointer_may_acquire_shell_focus_from_owned_embedded_editor(self):
        self.probe.value['gui'].update(focusPid=88,focusHwnd=56)
        self.probe.value['focusAncestry']=[];self.probe.value['nativeFocusUnderMenu']=False
        self.assertTrue(self.click()['success'])
    def null_native_focus(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a)
        def query(thread,pointer):
            self.assertEqual(thread,9)
            pointer._obj.active=11
            return True  # Successful native query; the original host thread has no focus HWND.
        probe.user=NS(GetGUIThreadInfo=query,
            GetWindowThreadProcessId=lambda *a:(_ for _ in()).throw(AssertionError('Null focus cannot name a process')),
            GetAncestor=lambda *a:(_ for _ in()).throw(AssertionError('Null focus cannot name a root')))
        return probe.native_focus(9)
    def test_file_pointer_uses_measured_recipient_when_successful_host_query_has_null_focus(self):
        gui=self.null_native_focus()
        self.assertEqual((gui['focusHwnd'],gui['focusPid'],gui['focusRootHwnd']),(0,0,0))
        self.probe.value.update(gui=gui,focusAncestry=[],nativeFocusUnderMenu=False)
        result=self.click()
        self.assertTrue(result['success'])
        self.assertEqual(self.probe.calls,['dpi-enter','move','click','dpi-restore'])
        self.assertEqual((result['clickAttempts'],result['inputCallAttempts'],result['requestedInputs'],result['insertedInputs']),(1,1,2,2))
        self.assertEqual(result['deadline'],6.)
    def test_null_focus_does_not_admit_host_keyboard_or_popup_routes(self):
        self.probe.value['gui']=self.null_native_focus()
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(call,tuple) and call[0]=='send' for call in self.probe.calls))
        self.probe.calls.clear();self.record={}
        self.probe.value['foreground'].update(hwnd=99,rootHwnd=99,ownerHwnd=11)
        self.probe.value['foregroundOwnerChain']=[99,11]
        self.probe.value['gui'].update(menuOwnerHwnd=11,flags=4)
        with self.assertRaises(AssertionError):self.click()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_null_focus_does_not_admit_owned_picker_button(self):
        self.dialog();self.probe.value['gui'].update(focusHwnd=0,focusPid=0,focusRootHwnd=0)
        with self.assertRaises(AssertionError):self.save()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_null_file_pointer_rejects_mixed_boolean_or_negative_focus_metadata(self):
        for focus,pid,root in ((None,0,0),(False,0,0),(0,False,0),(0,0,False),
                               (0,77,0),(0,0,11),(0,0,99),(-1,0,0)):
            with self.subTest(focus=focus,pid=pid,root=root):
                self.probe.value['gui']=self.null_native_focus()
                self.probe.value['gui'].update(focusHwnd=focus,focusPid=pid,focusRootHwnd=root)
                self.probe.calls.clear();self.record={}
                with self.assertRaises((AssertionError,TypeError)):self.click()
                self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_null_file_pointer_keeps_original_foreground_active_capture_and_hit_guards(self):
        original=copy.deepcopy(self.probe.value);hit=copy.deepcopy(self.probe.hit)
        mutations=(lambda:self.probe.value['foreground'].update(pid=88),
            lambda:self.probe.value['foreground'].update(rootHwnd=99),
            lambda:self.probe.value['foreground'].update(threadId=10),
            lambda:self.probe.value['gui'].update(activeHwnd=99),
            lambda:self.probe.value['gui'].update(captureHwnd=99),
            lambda:self.probe.hit.update(uiaMatches=False),
            lambda:self.probe.value['ancestry'][0].update(pid=88))
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                self.probe.value=copy.deepcopy(original);self.probe.hit=copy.deepcopy(hit)
                self.probe.value['gui']=self.null_native_focus();self.probe.calls.clear();self.record={}
                mutation()
                with self.assertRaises(AssertionError):self.click()
                self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_exact_new_picker_does_not_requery_invalidated_original_file_wrapper(self):
        probe=object.__new__(self.policy.NativeControlProbe)
        probe.user=NS(IsWindow=lambda h:True);probe._call=lambda f,*a:f(*a)
        probe.foreground=lambda:44
        probe._window=lambda h:dict(hwnd=h,pid=77,ownerHwnd=11 if h==44 else 0,
            className='#32770' if h==44 else 'Form',title='OpenGeul Writer — 다른 이름으로 저장' if h==44 else 'Writer')
        probe.target_snapshot=lambda *a:(_ for _ in ()).throw(AssertionError('Old File wrapper must not be queried'))
        element=NS(CurrentNativeWindowHandle=44,CurrentBoundingRectangle=NS(left=0,top=0,right=400,bottom=300),
            CurrentControlType=50032,GetRuntimeId=lambda:[42,44],CurrentName='OpenGeul Writer — 다른 이름으로 저장',
            CurrentAutomationId='',CurrentProcessId=77,CurrentIsOffscreen=False,CurrentIsEnabled=True)
        wrapper=NS(element_info=NS(_element=element))
        desktop=lambda **k:NS(window=lambda **k:NS(wrapper_object=lambda:wrapper))
        with patch.dict(sys.modules,{'pywinauto':NS(Desktop=desktop)}):
            result=probe.transition_snapshot(None,self.process,11,0,'OpenGeul Writer — 다른 이름으로 저장','FILE_MENU',object())
        self.assertTrue(result['accepted']);self.assertEqual(result['transition'],'exact-owned-save-picker')
    def test_failed_native_focus_guard_retains_actual_bounded_foreground_context(self):
        self.probe.value['foreground'].update(hwnd=918350,rootHwnd=918350,title='Observed native title',className='Observed class')
        with self.assertRaises(AssertionError):self.shortcut()
        raw=json.loads(next(self.root.glob('*result.json')).read_bytes())
        self.assertEqual(raw['lastObservation']['foreground']['hwnd'],918350)
        self.assertEqual(raw['lastObservation']['foreground']['title'],'Observed native title')
        self.assertEqual(raw['lastObservation']['shellCreationTime'],134370148289625043)
    def test_owned_popup_from_another_thread_cannot_admit_host_shortcut(self):
        self.probe.value['foreground'].update(hwnd=99,rootHwnd=99,ownerHwnd=11,threadId=10)
        self.probe.value['foregroundOwnerChain']=[99,11]
        self.probe.value['gui'].update(menuOwnerHwnd=11,flags=4)
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_consumed_menu_admits_only_frozen_original_attachment_editor_focus(self):
        probe=object.__new__(self.policy.NativeControlProbe);probe._call=lambda f,*a:f(*a)
        probe.user=NS(IsWindow=lambda h:True);probe.foreground=lambda:11
        doc=copy.deepcopy(self.probe.value['document']);probe._window=lambda h:copy.deepcopy(doc)
        probe.native_focus=lambda thread:dict(activeHwnd=11,focusHwnd=56,focusPid=88,focusRootHwnd=11,captureHwnd=0,menuOwnerHwnd=0,flags=0,threadId=9)
        attachment=dict(document=11,parent=55,child=56,officePid=88)
        probe.attachment_snapshot=lambda a:dict(binding=dict(a),valid=True,focusUnderOriginalChild=True)
        probe.target_snapshot=lambda *a:(_ for _ in ()).throw(AssertionError('Consumed menu must not need old File focus'))
        context=dict(document={k:doc[k] for k in ('hwnd','pid','threadId','rootHwnd','rectangle')},attachment=attachment)
        result=probe.transition_snapshot(None,self.process,11,0,'OpenGeul Writer — 다른 이름으로 저장','FILE_MENU',object(),context=context)
        self.assertTrue(result['accepted']);self.assertEqual(result['transition'],'consumed-menu-original-editor-return')
        probe.attachment_snapshot=lambda a:dict(binding=dict(a),valid=True,focusUnderOriginalChild=False)
        with self.assertRaises(AssertionError):
            probe.transition_snapshot(None,self.process,11,0,'OpenGeul Writer — 다른 이름으로 저장','FILE_MENU',object(),context=context)
    def test_declared_host_and_dialog_purposes_cannot_be_swapped(self):
        self.dialog();self.readiness['caption']='OpenGeul Office에서 문서 열기'
        self.probe.value['scope']['title']=self.readiness['caption'];self.probe.value['foreground']['title']=self.readiness['caption']
        with self.assertRaises(AssertionError):self.save()
        self.assertNotIn('move',self.probe.calls)
    def attachment(self):self.record['attachments']=[dict(hwnd=11,parent=55,child=56,officePid=88)]
    def test_attachment_without_prior_reader_still_requires_live_packaged_engine_generation(self):
        self.attachment();self.probe.engine['image']=str(self.root/'foreign.exe')
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertIn(('open-engine',88),self.probe.calls);self.assertIn(('close-engine',2345),self.probe.calls)
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_attachment_engine_is_pinned_and_closed_even_when_action_exceeds_deadline(self):
        self.attachment();self.probe.after_input=lambda p:setattr(self.clock,'now',20.)
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertEqual(len([c for c in self.probe.calls if c==('close-engine',2345)]),1)
        self.assertTrue(self.record['ownedControlActions'][0]['engineHandleClosed'])
    def test_available_earlier_engine_generation_is_an_additional_mandatory_join(self):
        self.attachment();self.process.opengeul_editor_click_generations={(55,56,88):(88,self.probe.engine['image'],1)}
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertIn(('close-engine',2345),self.probe.calls)
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_original_attachment_is_frozen_before_input_and_survives_record_mutation(self):
        self.attachment();contexts=[]
        self.probe.after_input=lambda p:self.record['attachments'][0].update(child=999)
        self.probe.transition_snapshot=lambda *a,**k:(contexts.append(copy.deepcopy(k['context'])) or dict(accepted=True))
        self.assertTrue(self.shortcut()['success'])
        self.assertEqual(contexts[0]['attachment']['child'],56)
        self.assertIn(('close-engine',2345),self.probe.calls)
    def test_owned_open_dialog_escape_uses_one_counted_two_event_plan(self):
        self.dialog();caption='OpenGeul Office에서 문서 열기'
        self.readiness['caption']=caption;self.probe.value['scope']['title']=caption;self.probe.value['foreground']['title']=caption
        self.probe.value['control'].update(nativeHwnd=101,runtimeId=[42,101],controlType='Edit',automationId='1148')
        self.probe.value['ancestry'][0].update(nativeHwnd=101,runtimeId=[42,101])
        result=self.policy.send_owned_dialog_escape(self.api,self.process,11,self.control,self.record,dialog=44,
            caption=caption,readiness=self.readiness,probe=self.probe,clock=self.clock)
        self.assertTrue(result['success']);self.assertEqual(result['insertedInputs'],2)
        self.assertEqual(len([c for c in self.probe.calls if isinstance(c,tuple) and c[0]=='send']),1)
    def test_native_gui_thread_layout_preserves_win64_pointer_width(self):
        self.assertEqual(ctypes.sizeof(self.policy.GuiThreadInfo),72)
        self.assertEqual(self.policy.GuiThreadInfo.active.offset,8)
    def test_host_shortcut_requires_original_attachment_and_engine_birth_after_shell(self):
        with self.assertRaises(AssertionError):
            self.policy.send_host_menu_shortcut(self.api,self.process,11,self.control,self.record,shortcut='CTRL_S',
                caption='OpenGeul Writer — 다른 이름으로 저장',probe=self.probe,clock=self.clock)
        self.attachment();self.probe.engine['creationTime']=1
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='send' for c in self.probe.calls))
    def test_failed_post_action_transition_retains_its_actual_native_snapshot(self):
        def fail(*args,**kw):
            kw['evidence'].update(foreground=dict(hwnd=918350,pid=77,title='Actual observed title',className='Actual class'))
            raise AssertionError('Unexpected exact native transition')
        self.probe.transition_snapshot=fail
        with self.assertRaises(AssertionError):self.click()
        receipt=json.loads(next(self.root.glob('*result.json')).read_bytes())
        self.assertEqual(receipt['after']['foreground']['hwnd'],918350)
    def test_later_host_action_cannot_rebaseline_first_admitted_engine_generation(self):
        self.assertTrue(self.shortcut()['success'])
        self.probe.engine['creationTime']+=1
        with self.assertRaises(AssertionError):self.shortcut()
        self.assertEqual(len([c for c in self.probe.calls if isinstance(c,tuple) and c[0]=='send']),1)
    def test_native_fixture_images_remain_canonical_when_temp_name_has_an_alias(self):
        # A real existing parent/.. alias works on Windows without symlink
        # privileges and exercises the same resolve/native-image boundary.
        parent=self.root/'alias-parent';parent.mkdir()
        alias=parent/'..';self.assertNotEqual(alias,alias.resolve())
        nested=type(self)('test_file_click_has_durable_intent_before_one_move_and_one_native_click')
        temporary=NS(name=str(alias),cleanup=lambda:None)
        try:
            with patch.object(tempfile,'TemporaryDirectory',return_value=temporary):nested.setUp()
            self.assertTrue(nested.click()['success'])
            self.assertTrue(nested.shortcut()['success'])
            self.assertEqual(nested.probe.identity['image'],str((alias/'OpenGeul.Office.exe').resolve()))
            self.assertEqual(nested.probe.engine['image'],str((alias/'Office/program/soffice.bin').resolve()))
        finally:nested.doCleanups()


if __name__ == '__main__': unittest.main()
