"""Real native-menu policy at bounded synthetic Windows/UIA boundaries."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
SOURCE=Path(__file__).resolve().parents[1]/'e2e/owned_native_menu.py'


class Clock:
    now=1.
    def __call__(self):return self.now
    def pause(self,value):self.now+=value


class Probe:
    def __init__(self,root,clock):
        self.root,self.clock=root,clock;self.opened=False;self.calls=[];self.bad=None
        self.shell=dict(pid=77,handleValue=8,creationTime=100,image=str(root/'OpenGeul.Office.exe'),waitResult=258)
        self.engine=dict(pid=88,creationTime=200,image=str(root/'Office/program/soffice.bin'),waitResult=258)
    def process_snapshot(self,p):return copy.deepcopy(self.shell)
    def open_engine(self,pid):self.calls.append(('open',pid));return 9
    def engine_snapshot(self,h):return copy.deepcopy(self.engine)
    def close_engine(self,h):self.calls.append(('close',h));return self.bad!='release'
    def enter_dpi(self,r):r.update(verified=True,previousContext=1);self.calls.append('dpi-enter')
    def restore_dpi(self,r):r['restored']=True;self.calls.append('dpi-restore')
    def snapshot(self,binding,command):
        self.current_control=command
        control=dict(runtimeId=[4,1 if command=='file' else 2],pid=88,nativeHwnd=56 if command=='file' else 99,
            controlType='MenuItem',visible=True,enabled=True,rectangle=[20,20,80,40])
        if command in ('saveAll','saveCopy'):control['enabled']=False
        file=dict(control,runtimeId=[4,1],nativeHwnd=56,enabled=True)
        bar=dict(control,runtimeId=[4,3],controlType='MenuBar',nativeHwnd=56)
        peer=dict(control,runtimeId=[4,4],controlType='Window',nativeHwnd=56)
        chain=[file,bar,peer] if command=='file' else [control,file,bar,peer]
        popup=None if command=='file' else dict(hwnd=99,pid=88,rootHwnd=99,threadId=9,
            visible=True,enabled=True,ownerChain=[99,56])
        row=dict(binding=dict(binding),attachmentValid=True,nativeReady=1,shellMenuCount=0,
            document=dict(hwnd=11,pid=77,rootHwnd=11,threadId=7,visible=True,enabled=True),
            control=control,ancestry=chain,fileIndex=0 if command=='file' else 1,
            barIndex=1 if command=='file' else 2,peerIndex=len(chain)-1,fileElementEquals=True,peerElementEquals=True,
            popup=popup,foreground=dict(hwnd=11,pid=77,rootHwnd=11),
            gui=dict(threadId=9,focusPid=88,focusRootHwnd=11,captureHwnd=0 if not self.opened else 99,
                     menuOwnerHwnd=0 if not self.opened else 99,flags=4 if self.opened else 0,captureOwned=True,menuOwnerOwned=True))
        if self.bad=='foreign':row['control']['pid']=999
        if self.bad=='duplicate':row['shellMenuCount']=1
        if self.bad=='ancestry':row['fileElementEquals']=False
        if self.bad=='popup' and popup:popup['ownerChain']=[99,1234]
        if self.bad=='capture':row['gui']['captureOwned']=False
        if self.bad=='late':self.clock.now=6.
        return row
    def point_snapshot(self,scope,point,control):
        return dict(point=list(point),hitHwnd=56 if control=='file' else 99,pid=88,
            rootHwnd=11 if control=='file' else 99,withinControl=True,uiaMatches=self.bad!='hit')
    def move(self,point,r):self.clock.now+=.01;r.update(pointerReadback=list(point),pointerMoveAttempts=1)
    def click(self,r):
        self.clock.now+=.01
        self.calls.append(('click',r['target']));r.update(inputCallAttempts=1,requestedInputs=2,insertedInputs=2,clickCompleted=True,beforeClickCursorReadback=r['chosenPhysicalPoint'])
        if self.bad=='partial':r.update(insertedInputs=1,ownedButtonRelease={'requested':1,'inserted':1});raise AssertionError('partial')
        self.opened=r['target']=='file'
    def editor_snapshot(self,binding):return dict(binding=dict(binding),attachmentValid=True,
        foreground=dict(hwnd=12 if self.bad=='editor-foreign' else 11,rootHwnd=12 if self.bad=='editor-foreign' else 11,pid=999 if self.bad=='editor-foreign' else 77),
        focusPid=88,focusRootHwnd=11,focusUnderOriginalChild=True,captureHwnd=0,menuOwnerHwnd=0,menuClosed=not self.opened)
    def keyboard(self,binding,shortcut,r):
        self.clock.now+=.01
        self.calls.append(('key',shortcut));self.opened=shortcut!='ESCAPE';r.update(inputCallAttempts=1,requestedInputs=4 if shortcut=='ALT_F' else 2,insertedInputs=4 if shortcut=='ALT_F' else 2)
        if self.bad=='foreign-after-down' and shortcut=='DOWN':self.bad='foreign'
    def outside_snapshot(self,binding):return dict(point=[200,10],hitHwnd=11,pid=77,rootHwnd=11,hitTest=2)
    def outside_click(self,binding,r):self.calls.append('outside');self.opened=False;r.update(requestedInputs=2,insertedInputs=2)


class OwnedNativeMenuTests(unittest.TestCase):
    def feature(self):
        self.assertTrue(SOURCE.is_file(),'A separate engine-owned native menu policy is required')
        spec=importlib.util.spec_from_file_location('tested_owned_native_menu',SOURCE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def fixture(self):
        m=self.feature();temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);out=root/'evidence';out.mkdir();clock=Clock();probe=Probe(root,clock)
        process=NS(pid=77,_handle=8,args=[str(root/'OpenGeul.Office.exe')],poll=lambda:None,
            opengeul_suite_root=root,opengeul_evidence_output=out,opengeul_evidence_case='blank-writer')
        api=NS(attachment=lambda h:(55,56,88),user=NS(GetPropW=lambda h,n:1))
        record=dict(windowHwnd=11,parentHwnd=55,childHwnd=56,officePid=88)
        return m,api,process,record,clock,probe
    def test_two_exact_clicks_keep_distinct_shell_engine_and_original_budget(self):
        m,a,p,r,c,probe=self.fixture();value=m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        self.assertTrue(value['success']);self.assertFalse(value['deliveryProved'])
        self.assertEqual(value['kind'],'owned-native-menu-action');self.assertEqual(value['deadline'],6.)
        self.assertEqual([x for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],[('click','file'),('click','save')])
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
    def test_foreign_stale_or_duplicate_menu_cannot_receive_any_input(self):
        for bad in ('foreign','duplicate','ancestry','capture','hit','late'):
            with self.subTest(bad=bad):
                m,a,p,r,c,probe=self.fixture();probe.bad=bad
                with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
                self.assertFalse(any(isinstance(x,tuple) and x[0]=='click' for x in probe.calls))
                self.assertIn(('close',9),probe.calls)
    def test_popup_requires_the_original_peer_owner_bridge(self):
        m,a,p,r,c,probe=self.fixture();probe.bad='popup'
        with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        self.assertEqual([x for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],[('click','file')])
    def test_reused_engine_pid_generation_is_rejected_without_reopening_input(self):
        m,a,p,r,c,probe=self.fixture();m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        probe.engine['creationTime']=201;probe.calls=[]
        with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        self.assertFalse(any(isinstance(x,tuple) and x[0]=='click' for x in probe.calls))
    def test_partial_mouse_input_does_not_retry_and_always_releases_handle(self):
        m,a,p,r,c,probe=self.fixture();probe.bad='partial'
        with self.assertRaisesRegex(AssertionError,'partial'):m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        self.assertEqual(sum(isinstance(x,tuple) and x[0]=='click' for x in probe.calls),1)
        self.assertTrue(r['nativeMenuActions'][-1]['engineHandleReleased'])
    def test_escape_outside_and_keyboard_sequences_require_focus_return(self):
        for gesture in ('open-escape','open-outside','keyboard-escape'):
            with self.subTest(gesture=gesture):
                m,a,p,r,c,probe=self.fixture();value=m.inspect_native_menu(a,p,11,r,gesture,probe=probe,clock=c)
                self.assertTrue(value['success']);self.assertTrue(value['focusReturned'])
                self.assertEqual(value['deadline'],6.)
    def test_failed_handle_release_cannot_mark_action_successful(self):
        m,a,p,r,c,probe=self.fixture();probe.bad='release'
        with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        self.assertFalse(r['nativeMenuActions'][-1]['success'])
    def test_hwp_home_and_app_exit_are_distinct_direct_file_commands(self):
        for command in ('new-hwp','home','exit'):
            with self.subTest(command=command):
                m,a,p,r,c,probe=self.fixture()
                value=m.click_native_menu_action(a,p,11,r,command,probe=probe,clock=c)
                self.assertEqual(value['command'],command)
                self.assertEqual([x[1] for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],['file',command])
    def test_disabled_saveall_and_copy_are_observed_without_clicking_them(self):
        for command in ('saveAll','saveCopy'):
            with self.subTest(command=command):
                m,a,p,r,c,probe=self.fixture()
                value=m.inspect_native_menu(a,p,11,r,'disabled-'+command,probe=probe,clock=c)
                self.assertTrue(value['disabledObserved']);self.assertTrue(value['focusReturned'])
                self.assertEqual([x[1] for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],['file'])
                with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,command,probe=probe,clock=c)
    def test_keyboard_focus_change_stops_before_escape(self):
        m,a,p,r,c,probe=self.fixture();probe.bad='foreign-after-down'
        with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=probe,clock=c)
        self.assertEqual([x for x in probe.calls if isinstance(x,tuple) and x[0]=='key'],[('key','ALT_F'),('key','DOWN')])
    def test_inactive_threads_remembered_focus_is_not_editor_return(self):
        m,a,p,r,c,probe=self.fixture();probe.bad='editor-foreign'
        with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        self.assertFalse(any(isinstance(x,tuple) and x[0]=='click' for x in probe.calls))
    def test_native_discovery_requests_only_menu_chrome_not_document_descendants(self):
        m=self.feature();probe=object.__new__(m.NativeMenuProbe);calls=[]
        probe._call=lambda f,*args:f(*args)
        probe.uia=NS(tree_scope={'descendants':4,'children':2},
            build_condition=lambda **kw:kw['control_type'])
        class Array:
            def __init__(self,rows):self.rows=rows
            @property
            def Length(self):return len(self.rows)
            def GetElement(self,i):return self.rows[i]
        item=NS(CurrentControlType=50011,CurrentName='파일',CurrentIsOffscreen=False)
        def children(scope,condition):
            calls.append(('bar',scope,condition));self.assertEqual((scope,condition),(2,'MenuItem'));return Array([item])
        bar=NS(CurrentIsOffscreen=False,FindAll=children)
        def descendants(scope,condition):
            calls.append(('peer',scope,condition));self.assertEqual((scope,condition),(4,'MenuBar'));return Array([bar])
        self.assertTrue(callable(getattr(probe,'discover_file',None)), 'File discovery must first retain its MenuBar')
        self.assertIs(probe.discover_file(NS(FindAll=descendants)),item)
        self.assertEqual(calls,[('peer',4,'MenuBar'),('bar',2,'MenuItem')])
    def test_replay_rejects_another_document_engine_or_physical_target(self):
        m,a,p,r,c,probe=self.fixture();original=m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        self.assertIs(m.require_native_menu_action(original,77,11,'save'),original)
        for change in ('document','engine-pid','engine-image','engine-birth','hit-root','center'):
            with self.subTest(change=change):
                value=copy.deepcopy(original);expected=11
                if change=='document':value['documentHwnd']=expected=12
                elif change=='engine-pid':value['originalEngine']['pid']=99
                elif change=='engine-image':value['originalEngine']['image']='/foreign/soffice.bin'
                elif change=='engine-birth':value['originalEngine']['creationTime']=0
                elif change=='hit-root':value['pointers'][0]['hits'][0]['rootHwnd']=999
                else:
                    pointer=value['pointers'][0];point=[21,21]
                    for field in ('chosenPhysicalPoint','pointerReadback','beforeClickCursorReadback'):pointer[field]=point
                    for hit in pointer['hits']:hit['point']=point
                with self.assertRaises(AssertionError):m.require_native_menu_action(value,77,expected,'save')
    def test_keyboard_replay_requires_each_original_native_recipient(self):
        m,a,p,r,c,probe=self.fixture();value=m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=probe,clock=c)
        self.assertIs(m.require_native_menu_action(value,77,11),value)
        value['keys'][1].pop('before',None)
        with self.assertRaises((AssertionError,KeyError)):m.require_native_menu_action(value,77,11)
    def test_native_keyboard_rejects_preheld_new_menu_keys(self):
        for key in (0x46,0x28):
            with self.subTest(key=key):
                m=self.feature();probe=object.__new__(m.NativeMenuProbe);calls=[]
                probe._call=lambda f,*args:f(*args);probe.clock=Clock()
                probe.user=NS(GetAsyncKeyState=lambda value:0x8000 if value==key else 0)
                probe.attachment_snapshot=lambda binding:dict(windows={'child':{'threadId':9}})
                probe.keyboard_snapshot=lambda thread:dict(targetLayout=0x04090409,currentThreadLayout=0x04090409,keysDown=[])
                probe.send=lambda payload:calls.append('send') or len(payload)
                with self.assertRaises(AssertionError):probe.keyboard({},'ALT_F',{})
                self.assertEqual(calls,[])
    def test_public_menu_mnemonic_before_ellipsis_is_not_a_different_command(self):
        m=self.feature()
        for text,expected in (('열기(~O)...','열기…'),('다른 이름으로 저장(A)…','다른 이름으로 저장…'),('파일(F)','파일')):
            with self.subTest(text=text):self.assertEqual(m._label(text),expected)
