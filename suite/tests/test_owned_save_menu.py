"""Save-menu pointer contracts; native boundaries here are synthetic."""
import copy
import ctypes
import importlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_owned_control_actions as old

CAPTION='OpenGeul Base — 다른 이름으로 저장'

class SaveMenuTests(unittest.TestCase):
    def setUp(self):
        f=old.ControlPolicyTests('test_file_click_has_durable_intent_before_one_move_and_one_native_click');f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.policy=f.policy;self.probe=f.probe;self.clock=f.clock;self.process=f.process
        native_thread=getattr(self,'native_thread_id',9)
        for role in ('document','scope','foreground'):self.probe.value[role]['threadId']=native_thread
        self.probe.value['gui']['threadId']=native_thread
        file_snapshot=copy.deepcopy(self.probe.value)
        self.probe.value['control'].update(runtimeId=[42,30],nativeHwnd=0,name='저장',rectangle=[15,60,180,80])
        popup=copy.deepcopy(self.probe.value['document']);popup.update(hwnd=99,rootHwnd=99,ownerHwnd=11,rectangle=[10,50,200,200],className='WindowsForms10.Window')
        self.probe.value['scope']=popup
        self.probe.value['ancestry']=[dict(runtimeId=[42,30],pid=77,nativeHwnd=0,controlType='MenuItem'),dict(runtimeId=[42,99],pid=77,nativeHwnd=99,controlType='Menu'),*copy.deepcopy(file_snapshot['ancestry'])]
        self.probe.value['gui'].update(focusHwnd=11,focusRootHwnd=11)
        self.probe.value['focusAncestry']=[file_snapshot['ancestry'][-1]];self.probe.value['nativeFocusUnderMenu']=False
        self.probe.value['saveMenuBridge']=dict(fileElementEquals=True,documentElementEquals=True,fileIndex=2,menuBarIndex=3,menuIndex=1,nativeOwnerChain=[99,11],fileControl=copy.deepcopy(file_snapshot['control']),fileAncestry=copy.deepcopy(file_snapshot['ancestry']))
        self.probe.hit.update(point=[97,70],hitHwnd=99,rootHwnd=99)
        self.discover_calls=[]
        def discover(api,document,control,record,value):
            self.discover_calls.append(self.clock());return object()
        self.probe.discover_save_menu=discover
        self.file_receipt=dict(schemaVersion=1,kind='owned-shell-control-action',success=True,purpose='FILE_MENU',shortcut=None,documentHwnd=11,clickAttempts=1,inputCallAttempts=1,requestedInputs=2,insertedInputs=2,nativeInsertionCountVerified=True,originalProcess=copy.deepcopy(self.probe.identity),before=file_snapshot,startedAt=0.,deadline=5.,finishedAt=.9)
        engine=self.probe.engine
        self.record=dict(ownedControlActions=[self.file_receipt],attachments=[dict(hwnd=11,parent=55,child=56,officePid=88,officeCreationTime=engine['creationTime'],officeImage=engine['image'],liveProcessBinding=dict(pid=88,creationTime=engine['creationTime'],nativeImage=engine['image'],expectedImage=engine['image'],waitResult=258,handleValue=9876,nativeCreation=dict(fileTime=engine['creationTime'])))])
        def transition(*args,**kwargs):
            foreground=dict(hwnd=44,rootHwnd=44,pid=77,threadId=native_thread,ownerHwnd=11,className='#32770',title=CAPTION,visible=True,enabled=True)
            row=dict(at=self.clock(),window=copy.deepcopy(foreground),process=copy.deepcopy(self.probe.identity))
            return dict(accepted=True,transition='exact-owned-save-picker',observationCount=1,foreground=foreground,
                pickerReadiness=dict(schemaVersion=1,kind='same-owned-save-picker-readiness',deadline=self.record['ownedControlActions'][-1]['deadline'],pendingObservationCount=0,firstObservation=copy.deepcopy(row),lastObservation=copy.deepcopy(row),lastPendingObservation=None),
                newPicker=dict(nativeHwnd=44,pid=77,runtimeId=[42,44],name=CAPTION,controlType='Window',visible=True,enabled=True))
        self.probe.transition_snapshot=transition
        original_click=self.probe.click
        def click(receipt):
            receipt['inputStartedAt']=self.clock();original_click(receipt);receipt['inputFinishedAt']=self.clock();receipt['beforeClickCursorReadback']=list(receipt['chosenPhysicalPoint'])
        self.probe.click=click
        original_move=self.probe.move
        def move(point,receipt):original_move(point,receipt);receipt['pointerSetReturned']=True
        self.probe.move=move
    def run_save(self,**kwargs):
        return self.policy.click_owned_control(self.f.api,self.process,11,self.f.control,self.record,purpose='SAVE_MENU',caption=CAPTION,probe=self.probe,clock=self.clock,**kwargs)
    def test_root_focused_visible_dropdown_clicks_exact_save_once_without_keyboard(self):
        error=None;value=None
        try:value=self.run_save()
        except BaseException as exc:error=exc
        self.assertIsNone(error,'Root-focus WinForms dropdown must use its independently proven pointer recipient')
        self.assertTrue(value['success']);self.assertEqual(value['purpose'],'SAVE_MENU');self.assertIsNone(value['shortcut'])
        self.assertEqual((value['inputCallAttempts'],value['requestedInputs'],value['insertedInputs']),(1,2,2))
        self.assertEqual(self.probe.calls.count('click'),1);self.assertFalse(any(isinstance(c,tuple)and c[0]=='send'for c in self.probe.calls))
        self.assertEqual(self.discover_calls,[1.]);self.assertTrue(value['engineHandleClosed'])
    def test_home_prior_engine_generation_is_mandatory_before_discovery(self):
        self.record['attachments'][0]['officeCreationTime']+=1
        with self.assertRaises(AssertionError):self.run_save()
        self.assertEqual(self.discover_calls,[]);self.assertNotIn('move',self.probe.calls)
    def test_missing_home_live_witness_is_not_replaced_by_first_admission(self):
        self.record['attachments'][0].pop('liveProcessBinding')
        with self.assertRaises(AssertionError):self.run_save()
        self.assertEqual(self.discover_calls,[])
    def test_generic_new_base_explicitly_first_admits_held_engine(self):
        self.record.pop('attachments');self.record.update(windowHwnd=11,parentHwnd=55,childHwnd=56,officePid=88)
        error=None;value=None
        try:value=self.run_save()
        except BaseException as exc:error=exc
        self.assertIsNone(error,'Generated Base has no fabricated Home witness')
        self.assertEqual(value['engineAdmissionBasis'],'first-native-measurement')
    def test_file_click_identity_must_precede_save_action(self):
        self.file_receipt['before']['control']['runtimeId']=[42,999]
        with self.assertRaises(AssertionError):self.run_save()
        self.assertNotIn('move',self.probe.calls)
    def test_foreign_replaced_or_unknown_bridge_has_no_pointer_effect(self):
        changes=[('fileElementEquals',False),('documentElementEquals',False),('nativeOwnerChain',[99]),('fileIndex',0),('menuIndex',None)]
        for key,bad in changes:
            with self.subTest(key=key):
                original=copy.deepcopy(self.probe.value['saveMenuBridge']);self.probe.value['saveMenuBridge'][key]=bad
                with self.assertRaises(AssertionError):self.run_save()
                self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
                self.probe.value['saveMenuBridge']=original
    def test_popup_foreign_pid_thread_or_owner_has_zero_clicks(self):
        for key,bad in [('pid',123),('threadId',333),('ownerHwnd',123)]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.probe.value['scope']);self.probe.value['scope'][key]=bad
                with self.assertRaises(AssertionError):self.run_save()
                self.assertNotIn('click',self.probe.calls);self.probe.value['scope']=original
    def test_discovery_consumes_original_five_seconds(self):
        self.probe.discover_save_menu=lambda *a:(setattr(self.clock,'now',6.)or object())
        with self.assertRaises(AssertionError):self.run_save()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_intent_fsync_deadline_expiry_or_replacement_never_clicks(self):
        real=self.policy.os.fsync
        def expire(fd):real(fd);self.clock.now=6.
        with patch.object(self.policy.os,'fsync',side_effect=expire):
            with self.assertRaises(AssertionError):self.run_save()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)
    def test_unknown_mouse_native_return_is_not_retried(self):
        self.probe.fail='click'
        with self.assertRaises(OSError):self.run_save()
        self.assertEqual(self.probe.calls.count('click'),1)
        self.assertIsNone(self.record['ownedControlActions'][-1]['insertedInputs'])
    def test_cleanup_after_original_deadline_cannot_mark_success(self):
        def close(h):self.clock.now=6.;return True
        self.probe.close_engine=close
        with self.assertRaises(AssertionError):self.run_save()
        self.assertFalse(self.record['ownedControlActions'][-1]['success'])
    def test_known_partial_save_click_releases_only_its_own_mouse_down(self):
        from suite_window_activation import NativeActivationProbe, Point
        native=object.__new__(NativeActivationProbe);native.clock=self.clock;native.deadline=6.;native._call=lambda f,*a:f(*a)
        calls=[]
        def position(pointer):
            value=ctypes.cast(pointer,ctypes.POINTER(Point)).contents;value.x,value.y=97,70;return True
        def send(count,payload,size):calls.append((count,size));return 1
        native.user=NS(GetAsyncKeyState=lambda key:0,GetPhysicalCursorPos=position,GetSystemMetrics=lambda key:0,SendInput=send)
        self.probe.click=native.click
        with self.assertRaisesRegex(AssertionError,'partial'):self.run_save()
        value=self.record['ownedControlActions'][-1]
        self.assertEqual(calls,[(2,40),(1,40)]);self.assertEqual(value['inputCallAttempts'],1)
        self.assertEqual(value['ownedButtonRelease'],dict(requested=1,inserted=1));self.assertFalse(value['success'])
    def test_save_rectangle_escaping_popup_cannot_move_or_click(self):
        self.probe.value['control']['rectangle']=[0,60,180,80];self.probe.hit['point']=[90,70]
        with self.assertRaises(AssertionError):self.run_save()
        self.assertNotIn('move',self.probe.calls);self.assertNotIn('click',self.probe.calls)

class SaveNativeTransitionTests(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('owned_save_menu');self.clock=old.Clock()
        self.probe=object.__new__(self.module.NativeSaveMenuProbe);self.probe.clock=self.clock;self.probe.deadline=6.
        self.probe._call=lambda f,*a:f(*a);self.process=NS(pid=77)
        self.doc=dict(hwnd=11,pid=77,threadId=9,rootHwnd=11,ownerHwnd=0,visible=True,enabled=True,iconic=False,cloaked=0)
        self.picker=dict(hwnd=44,pid=77,threadId=9,rootHwnd=44,ownerHwnd=11,className='#32770',title=CAPTION,visible=True,enabled=True)
        self.foregrounds=[11,44];self.current=11;self.observations=[]
        def foreground():self.current=self.foregrounds.pop(0)if self.foregrounds else self.current;return self.current
        self.probe.foreground=foreground;self.probe._window=lambda h:copy.deepcopy(self.doc if h==11 else self.picker)
        self.probe.user=NS(IsWindow=lambda h:True)
        self.probe.desktop=NS(window=lambda **kw:NS(wrapper_object=lambda:NS(element_info=NS(_element=object()))))
        self.probe._raw=lambda element:dict(nativeHwnd=44,pid=77,runtimeId=[42,44],controlType='Window',name=CAPTION,visible=True,enabled=True)
        self.context=dict(document=copy.deepcopy(self.doc),scope=dict(hwnd=99,ownerHwnd=11),originalProcess={})
        self.probe.process_snapshot=lambda p:{}
        self.probe.target_snapshot=lambda *a:(_ for _ in()).throw(AssertionError('Original Save UIA queried after click'))
    def transition(self,evidence):
        with patch.dict(sys.modules,{'pywinauto':NS(Desktop=lambda **k:self.probe.desktop)}):
            return self.probe.transition_snapshot(None,self.process,11,0,CAPTION,'SAVE_MENU',object(),context=self.context,evidence=evidence)
    def test_invalidated_save_item_is_not_requeried_before_exact_owned_picker(self):
        error=None;value=None
        with patch.object(time,'sleep',side_effect=lambda s:setattr(self.clock,'now',self.clock()+s)):
            try:value=self.transition({})
            except BaseException as exc:error=exc
        self.assertIsNone(error,'Save transition must observe native owner/picker without reusing destroyed Save UIA')
        self.assertEqual(value['transition'],'exact-owned-save-picker');self.assertEqual(value['newPicker']['nativeHwnd'],44)
    def test_foreign_picker_foreground_is_rejected_with_raw_identity(self):
        self.foregrounds=[44];self.picker['pid']=88;evidence={}
        with self.assertRaises(AssertionError):self.transition(evidence)
        self.assertEqual(evidence['foreground']['pid'],88);self.assertIsNot(evidence.get('accepted'),True)
    def test_rejected_foreground_retains_document_transitions_and_original_thread_state(self):
        self.foregrounds=[11,11,44];self.picker.update(pid=88,visible=False);evidence={};queries=[]
        self.probe.native_focus=lambda tid:queries.append(tid)or dict(threadId=tid,activeHwnd=55,focusHwnd=55)
        def pause(seconds):self.clock.now+=seconds;self.doc['enabled']=False
        with patch.object(time,'sleep',side_effect=pause):
            with self.assertRaisesRegex(AssertionError,'Foreign foreground'):self.transition(evidence)
        self.assertEqual(queries,[9]);self.assertEqual(evidence['originalThreadGui']['activeHwnd'],55)
        history=evidence['transitionHistory']
        self.assertEqual([row['document']['enabled'] for row in history],[True,False,False])
        self.assertEqual([row['foreground']['pid'] for row in history],[77,77,88])
        self.assertEqual(history[-1]['observationNumber'],3);self.assertFalse(evidence['accepted'])
        self.assertTrue(all('title' not in row['foreground'] and 'title' not in row['document'] for row in history))
        self.assertNotIn('newPicker',evidence)
    def test_rejection_diagnostic_error_preserves_ownership_failure(self):
        self.foregrounds=[44];self.picker['pid']=88;evidence={}
        self.probe.native_focus=lambda tid:(_ for _ in()).throw(OSError('thread unavailable'))
        with self.assertRaisesRegex(AssertionError,'Foreign foreground'):self.transition(evidence)
        self.assertEqual(evidence['originalThreadGuiError'],'OSError: thread unavailable')
        self.assertFalse(evidence['accepted']);self.assertEqual(evidence['observationCount'],1)
    def test_rejection_diagnostic_does_not_query_after_original_deadline(self):
        self.foregrounds=[44];self.picker['pid']=88;evidence={};queries=[]
        window=self.probe._window
        def observe(hwnd):
            value=window(hwnd)
            if hwnd==44:self.clock.now=6.
            return value
        self.probe._window=observe;self.probe.native_focus=lambda tid:queries.append(tid)
        with self.assertRaisesRegex(AssertionError,'Foreign foreground'):self.transition(evidence)
        self.assertEqual(queries,[]);self.assertIn('deadline',evidence['originalThreadGuiError'])
    def test_transition_history_is_bounded_and_keeps_first_and_rejected_states(self):
        self.foregrounds=[11]*30+[44];self.picker['pid']=88;evidence={}
        self.probe.native_focus=lambda tid:dict(threadId=tid)
        def pause(seconds):self.clock.now+=seconds;self.doc['enabled']=not self.doc['enabled']
        with patch.object(time,'sleep',side_effect=pause):
            with self.assertRaisesRegex(AssertionError,'Foreign foreground'):self.transition(evidence)
        self.assertEqual(len(evidence['transitionHistory']),16)
        self.assertEqual(evidence['droppedTransitionCount'],15)
        self.assertEqual(evidence['transitionHistory'][0]['observationNumber'],1)
        self.assertEqual(evidence['transitionHistory'][-1]['observationNumber'],31)
        self.assertEqual(evidence['transitionHistory'][-1]['foreground']['pid'],88)
    def test_save_picker_arrival_after_original_deadline_cannot_pass(self):
        self.foregrounds=[44]
        def raw(element):self.clock.now=6.;return dict(nativeHwnd=44,pid=77,runtimeId=[42,44],controlType='Window',name=CAPTION,visible=True,enabled=True)
        self.probe._raw=raw
        with self.assertRaisesRegex(AssertionError,'deadline'):self.transition({})

    def test_first_owned_picker_pending_flags_settle_on_same_candidate(self):
        for flag in ('visible','enabled'):
            with self.subTest(flag=flag):
                self.setUp();self.foregrounds=[44];self.picker[flag]=False;pauses=[];queries=[];raw=self.probe._raw
                self.probe._raw=lambda element:(queries.append(self.clock())or raw(element))
                def pause(seconds):
                    self.assertEqual(queries,[]);pauses.append(seconds);self.clock.now+=seconds;self.picker[flag]=True
                error=None;value={}
                with patch.object(time,'sleep',side_effect=pause):
                    try:value=self.transition({})
                    except BaseException as exc:error=exc
                self.assertIsNone(error,'A first exact owned but unready picker must be observed within the original budget')
                self.assertTrue(value['accepted']);self.assertEqual(pauses,[.01]);self.assertEqual(len(queries),1)
                witness=value['pickerReadiness'];self.assertEqual(witness['pendingObservationCount'],1)
                self.assertIs(witness['firstObservation']['window'][flag],False);self.assertIs(witness['lastObservation']['window'][flag],True)
                self.assertEqual(witness['deadline'],6.);self.assertEqual(value['observationCount'],2)
    def test_same_hidden_picker_expires_under_original_deadline(self):
        self.foregrounds=[44];self.picker['visible']=False;evidence={};pauses=[]
        def pause(seconds):pauses.append(seconds);self.clock.now+=seconds
        with patch.object(time,'sleep',side_effect=pause):
            with self.assertRaisesRegex(AssertionError,'deadline|bound'):self.transition(evidence)
        self.assertLessEqual(self.clock(),6.);self.assertLessEqual(evidence['observationCount'],501)
        self.assertIsNot(evidence.get('accepted'),True);self.assertNotIn('newPicker',evidence)
        self.assertTrue(pauses);self.assertTrue(all(0<s<=.01 for s in pauses))
    def test_pending_candidate_does_not_renew_original_finite_observation_limit(self):
        self.foregrounds=[44];self.picker['visible']=False;evidence={};pauses=[]
        with patch.object(time,'sleep',side_effect=lambda seconds:pauses.append(seconds)):
            with self.assertRaisesRegex(AssertionError,'bound'):self.transition(evidence)
        self.assertEqual(evidence['observationCount'],501);self.assertEqual(self.clock(),1.)
        self.assertEqual(len(evidence['transitionHistory']),1);self.assertEqual(evidence['droppedTransitionCount'],0)
        self.assertEqual(len(pauses),501);self.assertTrue(all(s==.01 for s in pauses))
    def test_pinned_candidate_replacement_foreign_or_generation_never_becomes_ready(self):
        mutations={'hwnd':55,'pid':88,'threadId':10,'rootHwnd':99,'ownerHwnd':22,'className':'Other','title':'Other','visible':None,'generation':None,'original-document':None}
        for key,bad in mutations.items():
            with self.subTest(key=key):
                self.setUp();self.foregrounds=[44];self.picker['visible']=False;evidence={}
                def pause(seconds):
                    self.clock.now+=seconds;self.picker['visible']=True
                    if key=='generation':self.probe.process_snapshot=lambda p:{'changed':True}
                    elif key=='original-document':self.current=11
                    else:
                        self.picker[key]=bad
                        if key=='hwnd':self.picker['rootHwnd']=bad;self.current=bad
                with patch.object(time,'sleep',side_effect=pause):
                    with self.assertRaises(AssertionError):self.transition(evidence)
                self.assertIn('pickerReadiness',evidence,'First valid hidden candidate must be retained before the later rejected observation')
                self.assertEqual(evidence['pickerReadiness']['firstObservation']['window']['hwnd'],44)
                self.assertIsNot(evidence.get('accepted'),True);self.assertNotIn('newPicker',evidence)
    def test_missing_pinned_candidate_preserves_original_query_failure(self):
        self.foregrounds=[44];self.picker['visible']=False;evidence={}
        def pause(seconds):
            self.clock.now+=seconds
            self.probe._window=lambda hwnd:(_ for _ in()).throw(OSError('original picker no longer live'))if hwnd==44 else copy.deepcopy(self.doc)
        with patch.object(time,'sleep',side_effect=pause):
            with self.assertRaisesRegex(OSError,'no longer live'):self.transition(evidence)
        self.assertIn('pickerReadiness',evidence);self.assertIsNot(evidence.get('accepted'),True)
    def test_hidden_picker_settlement_keeps_final_ui_a_readiness_strict(self):
        self.foregrounds=[44];self.picker['visible']=False;evidence={}
        self.probe._raw=lambda element:dict(nativeHwnd=44,pid=77,runtimeId=[42,44],controlType='Window',name=CAPTION,visible=False,enabled=True)
        def pause(seconds):self.clock.now+=seconds;self.picker['visible']=True
        with patch.object(time,'sleep',side_effect=pause):
            with self.assertRaises(AssertionError):self.transition(evidence)
        self.assertIn('pickerReadiness',evidence);self.assertEqual(evidence['newPicker']['visible'],False);self.assertIsNot(evidence.get('accepted'),True)

class SaveReplayTests(unittest.TestCase):
    def setUp(self):
        self.f=SaveMenuTests('test_root_focused_visible_dropdown_clicks_exact_save_once_without_keyboard');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.module=importlib.import_module('owned_save_menu');self.action=copy.deepcopy(self.f.run_save())
        self.readiness=dict(ready=True,shellPid=77,documentHwnd=11,dialogHwnd=44,caption=CAPTION,uiaRootRuntimeId=[42,44],startedAt=2.,finishedAt=2.1,trigger='owned-save-menu-pointer',fileMenuClicks=1,saveMenuClicks=1,saveShortcuts=0)
        self.readiness['saveMenuAction']=copy.deepcopy(self.action)
    def test_exact_menu_receipt_replays_without_claiming_keyboard_delivery(self):
        self.assertIs(self.module.require_save_menu_action(self.action,77,11,CAPTION,self.readiness),self.action)
    def test_boolean_counts_and_changed_picker_thread_or_ui_a_identity_cannot_replay(self):
        mutations={'count':lambda a:a.update(clickAttempts=True),'moves':lambda a:a.update(pointerMoveAttempts=2),'thread':lambda a:a['after']['foreground'].update(threadId=10),'disabled':lambda a:a['after']['foreground'].update(enabled=False),'uia-name':lambda a:a['after']['newPicker'].update(name='another picker')}
        for label,mutate in mutations.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(self.action);mutate(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,self.readiness)
    def test_late_cleanup_wrong_prefix_or_keyboard_claim_cannot_replay(self):
        for label,mutate in {'late':lambda a:a.update(finishedAt=a['deadline']),'shortcut':lambda a:a.update(shortcut='CTRL_S'),'witness':lambda a:a['originalEngineWitness'].update(creationTime=1)}.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(self.action);mutate(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,self.readiness)
    def test_physical_hits_cursor_geometry_and_native_types_are_replayed(self):
        mutations={'hit-pid':lambda a:a['afterClickIntentHit'].update(pid=88),'hit-uia':lambda a:a['afterClickIntentHit'].update(uiaMatches=False),'readback':lambda a:a.update(pointerReadback=[0,0]),'native-float':lambda a:a['before']['scope'].update(hwnd=99.0,rootHwnd=99.0),'runtime-float':lambda a:a['before']['control'].update(runtimeId=[42.,30]),'geometry':lambda a:a['before']['control'].update(rectangle=[0,60,180,80])}
        for label,mutate in mutations.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(self.action);mutate(changed);ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_new_control_picker_attachment_and_anchor_native_id_types_are_exact(self):
        mutations={
            'control-pid':lambda a:[a[k]['control'].update(pid=77.)for k in ('before','afterMoveIntent','beforeClick','afterClickIntent')],
            'picker-hwnd':lambda a:a['after']['foreground'].update(hwnd=44.),
            'picker-root':lambda a:a['after']['foreground'].update(rootHwnd=44.),
            'picker-pid':lambda a:a['after']['foreground'].update(pid=77.),
            'picker-thread':lambda a:a['after']['foreground'].update(threadId=9.),
            'picker-owner':lambda a:a['after']['foreground'].update(ownerHwnd=11.),
            'uia-hwnd':lambda a:a['after']['newPicker'].update(nativeHwnd=44.),
            'uia-pid':lambda a:a['after']['newPicker'].update(pid=77.),
            'uia-runtime':lambda a:a['after']['newPicker'].update(runtimeId=[42.,44]),
            'attachment-document':lambda a:a['originalAttachment'].update(document=11.),
            'attachment-parent':lambda a:a['originalAttachment'].update(parent=55.),
            'attachment-child':lambda a:a['originalAttachment'].update(child=56.),
            'attachment-pid':lambda a:a['originalAttachment'].update(officePid=88.),
            'witness-pid':lambda a:a['originalEngineWitness'].update(pid=88.),
            'witness-creation':lambda a:a['originalEngineWitness'].update(creationTime=float(a['originalEngineWitness']['creationTime'])),
            'file-anchor-document':lambda a:a['saveMenuFileAnchor']['document'].update(hwnd=11.),
            'file-anchor-ancestry':lambda a:a['saveMenuFileAnchor']['ancestry'][0].update(pid=77.),
        }
        for label,mutate in mutations.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(self.action);mutate(changed);ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_raw_save_control_and_complete_file_chain_join_the_retained_copies(self):
        for label,key,value in [('menu-bar-runtime','runtimeId',[42,1234]),('save-native-hwnd','nativeHwnd',1234),('save-control-type','controlType','Button')]:
            with self.subTest(label=label):
                changed=copy.deepcopy(self.action)
                for phase in ('before','afterMoveIntent','beforeClick','afterClickIntent'):
                    index=changed[phase]['saveMenuBridge']['menuBarIndex']if label=='menu-bar-runtime'else 0
                    changed[phase]['ancestry'][index][key]=value
                ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_generic_optional_prior_witness_is_typed_and_joined_when_present(self):
        generic=copy.deepcopy(self.action);generic['engineAdmissionBasis']='first-native-measurement'
        ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(generic)
        self.assertIs(self.module.require_save_menu_action(generic,77,11,CAPTION,ready),generic)
        for label,mutate in {
            'pid-float':lambda w:w.update(pid=float(w['pid'])),
            'creation-float':lambda w:w.update(creationTime=float(w['creationTime'])),
            'changed-pid':lambda w:w.update(pid=w['pid']+1),
            'changed-creation':lambda w:w.update(creationTime=w['creationTime']+1),
            'changed-image':lambda w:w.update(image=w['image']+'.replaced'),
        }.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(generic);mutate(changed['originalEngineWitness']);ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_first_last_picker_witness_identity_generation_and_budget_are_replayed(self):
        action=copy.deepcopy(self.action);action.update(inputStartedAt=1.,inputFinishedAt=1.)
        row=dict(at=1.,window=copy.deepcopy(action['after']['foreground']),process=copy.deepcopy(action['originalProcess']))
        action['after'].update(observationCount=1,pickerReadiness=dict(schemaVersion=1,kind='same-owned-save-picker-readiness',deadline=action['deadline'],pendingObservationCount=0,firstObservation=copy.deepcopy(row),lastObservation=copy.deepcopy(row),lastPendingObservation=None))
        mutations={
            'first-hwnd':lambda w:w['firstObservation']['window'].update(hwnd=99),
            'first-pid-type':lambda w:w['firstObservation']['window'].update(pid=77.),
            'first-thread':lambda w:w['firstObservation']['window'].update(threadId=99),
            'last-window':lambda w:w['lastObservation']['window'].update(ownerHwnd=99),
            'first-generation':lambda w:w['firstObservation']['process'].update(creationTime=1),
            'first-generation-type':lambda w:w['firstObservation']['process'].update(creationTime=float(w['firstObservation']['process']['creationTime'])),
            'started-before-input':lambda w:w['firstObservation'].update(at=.5),
            'renewed-budget':lambda w:w.update(deadline=7.),
            'boolean-count':lambda w:w.update(pendingObservationCount=False),
            'ready-first-claims-pending':lambda w:w.update(pendingObservationCount=1),
        }
        for label,mutate in mutations.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(action);mutate(changed['after']['pickerReadiness']);ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_last_pending_witness_is_not_ready_replaced_or_unbound(self):
        action=copy.deepcopy(self.action);action.update(inputStartedAt=1.,inputFinishedAt=1.)
        ready_row=dict(at=1.,window=copy.deepcopy(action['after']['foreground']),process=copy.deepcopy(action['originalProcess']))
        pending=copy.deepcopy(ready_row);pending['window']['visible']=False
        action['after'].update(observationCount=2,pickerReadiness=dict(schemaVersion=1,kind='same-owned-save-picker-readiness',deadline=action['deadline'],pendingObservationCount=1,firstObservation=copy.deepcopy(pending),lastObservation=copy.deepcopy(ready_row),lastPendingObservation=copy.deepcopy(pending)))
        ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(action)
        self.assertIs(self.module.require_save_menu_action(action,77,11,CAPTION,ready),action)
        for label,mutate in {
            'ready':lambda w:w['window'].update(visible=True),
            'replacement':lambda w:w['window'].update(hwnd=99,rootHwnd=99),
            'generation':lambda w:w['process'].update(creationTime=1),
        }.items():
            with self.subTest(label=label):
                changed=copy.deepcopy(action);mutate(changed['after']['pickerReadiness']['lastPendingObservation']);ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_zero_pending_requires_the_same_complete_first_and_last_observation(self):
        for label in ('time','rectangle'):
            with self.subTest(label=label):
                changed=copy.deepcopy(self.action)
                if label=='time':
                    changed['finishedAt']=1.1;changed['after']['pickerReadiness']['lastObservation']['at']=1.05
                else:changed['after']['pickerReadiness']['firstObservation']['window']['rectangle']=[0,0,100,100]
                ready=copy.deepcopy(self.readiness);ready['saveMenuAction']=copy.deepcopy(changed)
                with self.assertRaises(AssertionError):self.module.require_save_menu_action(changed,77,11,CAPTION,ready)
    def test_embedded_pointer_action_must_equal_original_raw_action(self):
        changed=copy.deepcopy(self.readiness);changed['saveMenuAction']['receiptStem']='another-action'
        with self.assertRaises(AssertionError):self.module.require_save_menu_action(self.action,77,11,CAPTION,changed)

class SaveNativeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('owned_save_menu');self.clock=old.Clock();self.p=object.__new__(self.module.NativeSaveMenuProbe);self.p.clock=self.clock;self.p.deadline=6.
        def call(function,*args):
            assert self.clock()<6.,'query deadline';value=function(*args);assert self.clock()<6.,'query deadline';return value
        self.p._call=call;self.compares=[]
        def node(identity,kind,name,hwnd,parent=None,box=(15,60,180,80)):
            return NS(CurrentNativeWindowHandle=hwnd,CurrentBoundingRectangle=NS(**dict(zip(('left','top','right','bottom'),box))),CurrentControlType=kind,GetRuntimeId=lambda:[42,identity],CurrentName=name,CurrentAutomationId='',CurrentProcessId=77,CurrentIsOffscreen=False,CurrentIsEnabled=True,parent=parent)
        self.root=node(11,50032,'Base',11,box=(0,0,900,700));self.bar=node(21,50010,'MenuBar',21,self.root);self.file=node(20,50011,'파일',None,self.bar,box=(10,30,50,50));self.menu=node(99,50009,'파일',99,self.file);self.save=node(30,50011,'저장',None,self.menu)
        self.candidates=[self.save]
        self.file.FindAll=lambda scope,condition:NS(Length=len(self.candidates),GetElement=lambda index:self.candidates[index])
        def compare(a,b):self.compares.append((a,b));return a is b
        self.p.uia=NS(ia=None,iuia=NS(CompareElements=compare,ControlViewWalker=NS(GetParentElement=lambda node:node.parent)),tree_scope={'descendants':4},true_condition=object())
        self.p.desktop=NS(window=lambda **k:NS(wrapper_object=lambda:NS(element_info=NS(_element=self.root))))
        doc=dict(hwnd=11,pid=77,threadId=9,rootHwnd=11,visible=True,enabled=True,iconic=False,cloaked=0,rectangle=[0,0,900,700],ownerHwnd=0)
        popup=dict(doc,hwnd=99,rootHwnd=99,rectangle=[10,50,200,200],ownerHwnd=11)
        self.windows={11:doc,99:popup,777:dict(doc,hwnd=777,pid=88,threadId=88,rootHwnd=777)}
        self.owner=11;self.p.user=NS(GetWindow=lambda hwnd,flag:self.owner if hwnd==99 else 0)
        self.p._window=lambda hwnd:copy.deepcopy(self.windows[hwnd]);self.p.foreground=lambda:11
        self.p.native_focus=lambda thread:dict(threadId=9,activeHwnd=11,focusHwnd=11,focusPid=77,focusRootHwnd=11,captureHwnd=0,menuOwnerHwnd=0,flags=0)
        self.p.point_snapshot=lambda scope,point,control:dict(point=point,hitHwnd=99,pid=77,rootHwnd=99,withinControl=True,uiaMatches=True)
        file_props=self.p._raw(self.file)
        ancestry=[{k:self.p._raw(node)[k]for k in ('runtimeId','pid','nativeHwnd','controlType')}for node in (self.file,self.bar,self.root)]
        self.anchor=dict(index=0,control=file_props,ancestry=ancestry,document=doc);self.receipt=dict(saveMenuFileAnchor=self.anchor)
        self.wrapper=NS(element_info=NS(_element=self.file))
    def observe(self):
        control=self.p.discover_save_menu(None,11,self.wrapper,{},self.receipt)
        value=self.p.target_snapshot(None,11,control,0,'SAVE_MENU')
        return self.module.require_save_menu_target(value,11,77,CAPTION,self.anchor)
    def test_real_provider_walk_joins_original_file_document_and_native_popup(self):
        value=self.observe();self.assertEqual(value['scope']['hwnd'],99)
        self.assertTrue(any(a is self.file and b is self.file for a,b in self.compares))
        self.assertEqual(value['saveMenuBridge']['nativeOwnerChain'],[99,11])
    def test_same_runtime_file_replacement_is_rejected_by_compare_elements(self):
        replacement=copy.copy(self.file);self.menu.parent=replacement
        with self.assertRaises(AssertionError):self.observe()
    def test_missing_actual_menu_file_bridge_is_not_inferred_from_pid(self):
        self.save.parent=self.bar
        with self.assertRaises(AssertionError):self.observe()
    def test_duplicate_disabled_exact_save_is_still_ambiguous(self):
        duplicate=copy.copy(self.save);duplicate.CurrentIsEnabled=False;self.candidates.append(duplicate)
        with self.assertRaisesRegex(AssertionError,'one Save'):self.observe()
    def test_native_popup_foreign_owner_thread_is_rejected(self):
        self.owner=777
        with self.assertRaises(AssertionError):self.observe()
    def test_provider_discovery_finishing_after_original_deadline_fails(self):
        self.file.FindAll=lambda *a:(setattr(self.clock,'now',6.)or NS(Length=1))
        with self.assertRaisesRegex(AssertionError,'deadline'):self.observe()

if __name__=='__main__':unittest.main()
