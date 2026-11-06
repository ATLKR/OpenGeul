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
    def real_menu_keyboard(self,inserted):
        m=self.feature();probe=object.__new__(m.NativeMenuProbe);calls=[];clock=Clock()
        def rows(payload):
            return [dict(vk=item.payload.keyboard.wVk,scan=item.payload.keyboard.wScan,
                flags=item.payload.keyboard.dwFlags) for item in payload]
        def send(payload):calls.append(('send',rows(payload)));return inserted
        def release(payload):calls.append(('release',rows(payload)));return len(payload)
        backend=NS(send=send,release=release,keyboard_snapshot=lambda thread:
            dict(targetLayout=0x04090409,currentThreadLayout=0x04090409,keysDown=[]))
        probe.clock=clock;probe.deadline=clock()+5;probe.provider_client=None
        probe._keyboard=lambda:backend
        probe.user=NS(GetAsyncKeyState=lambda key:0)
        probe.attachment_snapshot=lambda binding:dict(windows={'child':{'threadId':9}})
        # Keep both inherited typed wrappers real: no fake release-plan admission.
        self.assertIs(probe.send.__func__,m.NativeControlProbe.send)
        self.assertIs(probe.release.__func__,m.NativeControlProbe.release)
        self.assertIs(probe.owned_release_events.__func__,m.NativeControlProbe.owned_release_events)
        return m,probe,calls
    def test_real_menu_keyboard_releases_each_partial_fixed_prefix_through_common_wrapper(self):
        cases=(('ALT_F',0,[]),('ALT_F',1,[(0x38,10)]),('ALT_F',2,[(0x21,10),(0x38,10)]),
            ('ALT_F',3,[(0x38,10)]),('DOWN',0,[]),('DOWN',1,[(0x50,11)]),
            ('ESCAPE',0,[]),('ESCAPE',1,[(0x01,10)]))
        for shortcut,inserted,expected in cases:
            with self.subTest(shortcut=shortcut,inserted=inserted):
                m,probe,calls=self.real_menu_keyboard(inserted);receipt={}
                with self.assertRaisesRegex(AssertionError,'Native menu key input was partial'):
                    probe.keyboard({},shortcut,receipt)
                self.assertEqual(receipt['inputCallAttempts'],1);self.assertEqual(receipt['insertedInputs'],inserted)
                self.assertEqual(sum(name=='send' for name,row in calls),1)
                released=[row for name,row in calls if name=='release']
                self.assertEqual(released,[[dict(vk=0,scan=scan,flags=flags) for scan,flags in expected]] if expected else [])
                self.assertEqual(receipt.get('ownedReleaseInserted',0),len(expected))
                self.assertEqual(probe.deadline,probe.clock()+5)
    def test_real_menu_keyboard_never_guesses_unknown_prefixes_or_retries(self):
        for shortcut,size in (('ALT_F',4),('DOWN',2),('ESCAPE',2)):
            for inserted in (None,True,-1,size+1,float(size),.5):
                with self.subTest(shortcut=shortcut,inserted=inserted):
                    m,probe,calls=self.real_menu_keyboard(inserted)
                    with self.assertRaises(AssertionError):probe.keyboard({},shortcut,{})
                    self.assertEqual([name for name,row in calls],['send'])
            m,probe,calls=self.real_menu_keyboard(size);receipt={}
            probe.keyboard({},shortcut,receipt)
            self.assertEqual([name for name,row in calls],['send'])
            self.assertEqual(receipt['insertedInputs'],size)
    def test_local_menu_release_does_not_expand_the_shared_shortcut_allowlist(self):
        from counted_editor_shortcuts import owned_release_events,shortcut_events
        m=self.feature()
        self.assertTrue(callable(getattr(m,'_menu_key_events',None)))
        self.assertTrue(callable(getattr(m,'_menu_release_events',None)))
        for shortcut in ('ALT_F','DOWN'):
            with self.subTest(shortcut=shortcut):
                with self.assertRaisesRegex(AssertionError,'Unknown shortcut scan plan'):
                    owned_release_events(m._menu_key_events(shortcut),1)
                with self.assertRaises(ValueError):shortcut_events(shortcut)
        for unknown in ('CTRL_F','ALT_F4','',None,True,[],{'scan':0x38}):
            with self.subTest(unknown=unknown):
                with self.assertRaises(AssertionError):m._menu_release_events(unknown,1)
    def test_print_preview_uses_the_same_two_physical_file_clicks_and_replays(self):
        m,a,p,r,c,probe=self.fixture()
        value=m.click_native_menu_action(a,p,11,r,'printPreview',probe=probe,clock=c)
        self.assertEqual([x[1] for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],['file','printPreview'])
        self.assertIs(m.require_native_menu_action(value,77,11,'printPreview'),value)
        self.assertEqual(m._label('인쇄 미리보기(~E)'),'인쇄 미리보기')

    def test_disabled_blank_calc_preview_is_failure_without_clicking_the_command(self):
        m,a,p,r,c,probe=self.fixture();original=probe.snapshot
        def snapshot(binding,target):
            value=original(binding,target)
            if target=='printPreview':value['control']['enabled']=False
            return value
        probe.snapshot=snapshot
        with self.assertRaises(AssertionError):
            m.click_native_menu_action(a,p,11,r,'printPreview',probe=probe,clock=c)
        self.assertEqual([x[1] for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],['file'])
        self.assertTrue(r['nativeMenuActions'][-1]['engineHandleReleased'])

    def test_core_file_commands_are_read_without_launch_or_storage_actions(self):
        m,a,p,r,c,probe=self.fixture()
        value=m.inspect_native_menu(a,p,11,r,'core-commands',probe=probe,clock=c)
        self.assertIs(value['coreCommandsVerified'],True)
        self.assertEqual(value['coreCommands'],['new-hwp','home','new','open','save','saveAs','close'])
        self.assertEqual(set(value['coreSnapshots']),set(value['coreCommands']))
        self.assertEqual([x for x in probe.calls if isinstance(x,tuple) and x[0]=='click'],[('click','file')])
        self.assertEqual([x for x in probe.calls if isinstance(x,tuple) and x[0]=='key'],[('key','ESCAPE')])
        self.assertIs(m.require_native_menu_action(value,77,11),value)

    def view_fixture(self):
        m,a,p,r,c,probe=self.fixture()
        m.click_native_menu_action(a,p,11,r,'save',probe=probe,clock=c)
        r.update(module='writer',nativeArchiveGeneration={k:probe.engine[k] for k in ('pid','creationTime','image')},officeCreationTime=200)
        view_start=c.now
        def snapshot(binding,module):
            c.now+=.001
            return dict(binding=dict(binding),editor=probe.editor_snapshot(binding),
                peerRoot=dict(pid=88,nativeHwnd=56,runtimeId=[4,56]),documentRoot=dict(pid=77,nativeHwnd=11,runtimeId=[4,11]),
                nativeReady=1,shellMenuCount=0,nativeMenuBarCount=1,previewIndicatorCount=1,
                statusSequenceRaw=self.pack_status(int((c.now-view_start)/.5),int((c.now-view_start)/.5)),
                previewIndicator=dict(pid=88,runtimeId=[8,4],controlType='Button',visible=True,enabled=True,
                    ancestryVerified=True,peerElementEquals=True,toolbarAncestorVerified=True))
        probe.view_snapshot=snapshot
        return m,a,p,r,c,probe

    def test_view_observation_holds_original_generation_for_three_seconds_without_input(self):
        m,a,p,r,c,probe=self.view_fixture();probe.calls=[]
        self.assertTrue(callable(getattr(m,'observe_native_view',None)))
        value=m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
        self.assertEqual(value['kind'],'owned-native-view-observation')
        self.assertTrue(value['success']);self.assertGreaterEqual(value['observedSeconds'],3)
        self.assertLess(value['finishedAt'],value['deadline'])
        self.assertLessEqual(value['deadline']-value['startedAt'],5)
        self.assertIs(value['statusRpcProved'],True);self.assertEqual(value['inputCallAttempts'],0)
        self.assertEqual(value['statusSequenceVersion'],1)
        self.assertGreater(value['lastTargetCompletedSequence'],value['firstTargetStartedSequence'])
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
        self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_view_observation_cannot_accept_foreign_focus_wrong_state_generation_or_late_read(self):
        for bad in ('foreign','preview','menu','ready','generation','late'):
            with self.subTest(bad=bad):
                m,a,p,r,c,probe=self.view_fixture();probe.calls=[]
                self.assertTrue(callable(getattr(m,'observe_native_view',None)))
                original=probe.view_snapshot
                def snapshot(binding,module):
                    row=original(binding,module)
                    if bad=='foreign':row['editor']['foreground']['pid']=999
                    elif bad=='preview':row['previewIndicatorCount']=0;row['previewIndicator']=None
                    elif bad=='menu':row['nativeMenuBarCount']=0
                    elif bad=='ready':row['nativeReady']=0
                    elif bad=='late':c.now+=5
                    return row
                probe.view_snapshot=snapshot
                if bad=='generation':probe.engine['creationTime']+=1
                with self.assertRaises(AssertionError):
                    m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
                self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))
                self.assertIn(('close',9),probe.calls)

    @staticmethod
    def pack_status(started,completed):return (1<<56)|(started<<28)|completed

    def test_status_codec_accepts_only_the_versioned_bounded_serial_sequences(self):
        m=self.feature();decode=getattr(m,'decode_status_sequence',None)
        self.assertTrue(callable(decode),'Status completion requires a strict shared numeric decoder')
        limit=(1<<28)-1
        for started,completed in ((0,0),(1,0),(1,1),(limit,limit-1),(limit,limit)):
            with self.subTest(started=started,completed=completed):
                self.assertEqual(decode(self.pack_status(started,completed)),dict(version=1,started=started,completed=completed))
        for raw in (None,True,0,-1,1<<63,2<<56,1.,'1',
                    self.pack_status(0,1),self.pack_status(3,1)):
            with self.subTest(raw=raw):
                with self.assertRaises(AssertionError):decode(raw)

    def test_stale_or_only_pre_target_inflight_completion_never_proves_polling(self):
        for inflight in (False,True):
            with self.subTest(inflight=inflight):
                m,a,p,r,c,probe=self.view_fixture();probe.calls=[];original=probe.view_snapshot;start=c.now
                def snapshot(binding,module):
                    row=original(binding,module)
                    row['statusSequenceRaw']=self.pack_status(5,4 if inflight and c.now-start<.3 else 5)
                    return row
                probe.view_snapshot=snapshot
                with self.assertRaises(AssertionError):
                    m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
                result=r['nativeViewObservations'][-1]
                self.assertFalse(result['statusRpcProved']);self.assertFalse(result['success'])
                self.assertEqual(result['firstTargetStartedSequence'],5)
                self.assertEqual(result['deadline'],start+5);self.assertGreaterEqual(result['finishedAt']-start,4.9)
                self.assertTrue(result['engineHandleReleased'])
                self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_post_target_request_must_finish_even_after_three_seconds_of_stable_mode(self):
        m,a,p,r,c,probe=self.view_fixture();probe.calls=[];original=probe.view_snapshot;start=c.now
        def snapshot(binding,module):
            row=original(binding,module);elapsed=c.now-start
            started=11 if elapsed>=3.4 else 10
            completed=9 if elapsed<.2 else 10 if elapsed<3.6 else 11
            row['statusSequenceRaw']=self.pack_status(started,completed)
            return row
        probe.view_snapshot=snapshot
        result=m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
        self.assertTrue(result['statusRpcProved']);self.assertEqual(result['statusSequenceVersion'],1)
        self.assertEqual(result['firstTargetStartedSequence'],10);self.assertEqual(result['lastTargetCompletedSequence'],11)
        self.assertGreaterEqual(result['finishedAt']-start,3.6);self.assertLess(result['finishedAt'],start+5)
        for sample in result['samples']:
            self.assertEqual(sample['statusSequence'],m.decode_status_sequence(sample['state']['statusSequenceRaw']))
        self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_mode_change_restarts_the_post_target_request_baseline(self):
        for finish_new_request in (False,True):
            with self.subTest(finish_new_request=finish_new_request):
                m,a,p,r,c,probe=self.view_fixture();probe.calls=[];original=probe.view_snapshot;start=c.now
                def snapshot(binding,module):
                    row=original(binding,module);elapsed=c.now-start
                    row=self.view_mode(row,not (.5<=elapsed<.8),True)
                    count=0 if elapsed<.3 else 2 if finish_new_request and elapsed>=1.2 else 1
                    row['statusSequenceRaw']=self.pack_status(count,count)
                    return row
                probe.view_snapshot=snapshot
                if finish_new_request:
                    result=m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
                    self.assertTrue(result['statusRpcProved']);self.assertEqual(result['lastTargetCompletedSequence'],2)
                else:
                    with self.assertRaises(AssertionError):
                        m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
                    result=r['nativeViewObservations'][-1];self.assertFalse(result['success']);self.assertFalse(result['statusRpcProved'])
                self.assertEqual(result['firstTargetStartedSequence'],1)
                self.assertGreaterEqual(result['settledAt']-start,.8);self.assertEqual(result['deadline'],start+5)
                self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_malformed_or_rolled_back_status_is_fatal_before_more_polling(self):
        cases=((None,), (True,), (0,), (2<<56,), (self.pack_status(3,1),),
            (self.pack_status(5,4),self.pack_status(4,4)),
            (self.pack_status(5,5),self.pack_status(5,4)))
        for raws in cases:
            with self.subTest(raws=raws):
                m,a,p,r,c,probe=self.view_fixture();probe.calls=[];original=probe.view_snapshot;seen=[];start=c.now
                def snapshot(binding,module):
                    row=original(binding,module);row['statusSequenceRaw']=raws[len(seen)];seen.append(1)
                    return self.view_mode(row,False,True)
                probe.view_snapshot=snapshot
                with self.assertRaises(AssertionError):
                    m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
                result=r['nativeViewObservations'][-1]
                self.assertEqual(len(seen),len(raws));self.assertTrue(result['engineHandleReleased'])
                self.assertEqual(result['deadline'],start+5)
                self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    @staticmethod
    def view_mode(row,preview,menu_visible):
        row['nativeMenuBarCount']=int(menu_visible)
        row['previewIndicatorCount']=int(preview)
        if not preview:row['previewIndicator']=None
        return row

    def test_async_view_settles_readonly_before_three_continuous_seconds(self):
        transitions=((True,True,False,True),(False,True,True,True),
                     (False,False,False,True),(False,True,False,False))
        for module in ('writer','calc'):
            for preview,visible,old_preview,old_visible in transitions:
                with self.subTest(module=module,preview=preview,visible=visible,old=(old_preview,old_visible)):
                    m,a,p,r,c,probe=self.view_fixture();r['module']=module;probe.calls=[]
                    original=probe.view_snapshot;start=c.now
                    def snapshot(binding,requested_module):
                        row=original(binding,requested_module)
                        target=c.now-start>=.4
                        return self.view_mode(row,preview if target else old_preview,visible if target else old_visible)
                    probe.view_snapshot=snapshot
                    result=m.observe_native_view(a,p,11,r,module=module,preview=preview,menu_visible=visible,
                        probe=probe,clock=c,pause=c.pause)
                    self.assertTrue(result['success']);self.assertGreaterEqual(result['observedSeconds'],3)
                    self.assertGreaterEqual(result['settledAt']-start,.4)
                    self.assertEqual(result['deadline'],start+5)
                    self.assertLess(result['finishedAt'],result['deadline'])
                    self.assertIs(result['samples'][0]['targetMatched'],False)
                    self.assertIs(result['samples'][-1]['targetMatched'],True)
                    self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_mode_never_ready_or_ready_near_deadline_cannot_renew_the_five_seconds(self):
        for target_after in (None,4.8):
            with self.subTest(target_after=target_after):
                m,a,p,r,c,probe=self.view_fixture();probe.calls=[];original=probe.view_snapshot;start=c.now
                def snapshot(binding,module):
                    row=original(binding,module)
                    return self.view_mode(row,target_after is not None and c.now-start>=target_after,True)
                probe.view_snapshot=snapshot
                with self.assertRaises(AssertionError):
                    m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
                result=r['nativeViewObservations'][-1]
                self.assertEqual(result['deadline'],start+5)
                self.assertGreaterEqual(result['finishedAt']-start,4.9)
                self.assertGreater(len(result['samples']),2)
                self.assertFalse(result['success']);self.assertTrue(result['engineHandleReleased'])
                self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_mode_lost_after_arrival_resets_only_the_hold_start(self):
        m,a,p,r,c,probe=self.view_fixture();original=probe.view_snapshot;start=c.now
        def snapshot(binding,module):
            row=original(binding,module);elapsed=c.now-start
            return self.view_mode(row,not (.4<=elapsed<.8),True)
        probe.view_snapshot=snapshot
        result=m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
        self.assertTrue(result['success']);self.assertGreaterEqual(result['settledAt']-start,.8)
        self.assertGreaterEqual(result['observedSeconds'],3)
        self.assertEqual(result['deadline'],start+5)
        self.assertTrue(any(row['targetMatched'] is False for row in result['samples']))

    def test_repeated_mode_flapping_fails_at_the_original_deadline(self):
        m,a,p,r,c,probe=self.view_fixture();original=probe.view_snapshot;start=c.now
        def snapshot(binding,module):
            row=original(binding,module)
            return self.view_mode(row,int((c.now-start)/.5)%2==0,True)
        probe.view_snapshot=snapshot
        with self.assertRaises(AssertionError):
            m.observe_native_view(a,p,11,r,module='writer',preview=True,probe=probe,clock=c,pause=c.pause)
        result=r['nativeViewObservations'][-1]
        self.assertEqual(result['deadline'],start+5)
        self.assertGreaterEqual(result['finishedAt']-start,4.9)
        self.assertFalse(result['success'])

    def test_settle_does_not_delay_fatal_first_owner_ready_or_ambiguity_failure(self):
        for reason in ('foreground','ready','bar-duplicate','preview-duplicate','peer','indicator-owner'):
            with self.subTest(reason=reason):
                m,a,p,r,c,probe=self.view_fixture();probe.calls=[];original=probe.view_snapshot;seen=[]
                def snapshot(binding,module):
                    row=original(binding,module);seen.append(1)
                    if reason=='foreground':row['editor']['foreground']['pid']=999
                    elif reason=='ready':row['nativeReady']=0
                    elif reason=='bar-duplicate':row['nativeMenuBarCount']=2
                    elif reason=='preview-duplicate':row['previewIndicatorCount']=2
                    elif reason=='peer':row['peerRoot']['nativeHwnd']=999
                    else:row['previewIndicator']['pid']=999
                    return row
                probe.view_snapshot=snapshot
                with self.assertRaises(AssertionError):
                    m.observe_native_view(a,p,11,r,module='writer',preview=False,probe=probe,clock=c,pause=c.pause)
                self.assertEqual(seen,[1]);self.assertTrue(r['nativeViewObservations'][-1]['engineHandleReleased'])
                self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in probe.calls))

    def test_real_view_probe_reads_only_fixed_chrome_and_verifies_its_owned_toolbar(self):
        m=self.feature();binding=dict(document=11,parent=55,child=56,officePid=88)
        calls=[]
        class Array:
            def __init__(self,rows):self.rows=rows
            @property
            def Length(self):return len(self.rows)
            def GetElement(self,index):return self.rows[index]
        def node(kind,handle,runtime,pid=88,name=None,parent=None):
            return NS(CurrentControlType=kind,CurrentNativeWindowHandle=handle,
                CurrentProcessId=pid,CurrentName=name,CurrentIsOffscreen=False,CurrentIsEnabled=True,
                CurrentBoundingRectangle=NS(left=0,top=0,right=100,bottom=20),
                GetRuntimeId=lambda:list(runtime),parent=parent)
        root=node(50032,56,[4,56]);bar=node(50010,0,[4,3],parent=root)
        toolbar=node(50021,70,[4,70],parent=root)
        button=node(50000,71,[4,71],name='미리보기 닫기',parent=toolbar)
        shell=node(50032,11,[4,11],pid=77)
        def find(scope,condition):
            calls.append((scope,condition))
            self.assertEqual(scope,4)
            if condition=={'control_type':'MenuBar'}:return Array([bar])
            self.assertEqual(condition.get('control_type'),'Button')
            self.assertIn(condition.get('name'),('미리보기 닫기','Close Preview'))
            return Array([button] if condition['name']=='미리보기 닫기' else [])
        root.FindAll=shell.FindAll=find
        probe=object.__new__(m.NativeMenuProbe);probe._call=lambda f,*args:f(*args)
        probe._root=lambda hwnd:root if hwnd==56 else shell
        probe.uia=NS(tree_scope={'descendants':4},build_condition=lambda **kwargs:kwargs,
            iuia=NS(CompareElements=lambda a,b:a is b,ControlViewWalker=NS(GetParentElement=lambda element:element.parent)))
        probe.window_snapshot=lambda hwnd:dict(pid=77)
        properties=[]
        def property_value(hwnd,name):
            properties.append((hwnd,name));self.assertEqual(hwnd,11)
            return self.pack_status(7,6) if name=='OpenGeul.Office.NativeMenuStatusV1' else 1
        probe.user=NS(GetPropW=property_value)
        probe.editor_snapshot=lambda b:dict(binding=dict(b))
        value=probe.view_snapshot(binding,'writer')
        self.assertEqual(value['nativeMenuBarCount'],1);self.assertEqual(value['shellMenuCount'],0)
        self.assertEqual(value['previewIndicatorCount'],1)
        self.assertEqual(value['statusSequenceRaw'],self.pack_status(7,6))
        self.assertEqual(properties,[(11,m.READY_PROPERTY),(11,m.STATUS_PROPERTY)])
        self.assertTrue(value['previewIndicator']['toolbarAncestorVerified'])
        self.assertNotIn('name',str(value))
        # Zero visible items must still come from the original peer, rather
        # than turning an unrelated empty UIA root into fullscreen evidence.
        button.CurrentIsOffscreen=True;bar.CurrentIsOffscreen=True
        root.CurrentNativeWindowHandle=999
        with self.assertRaises(AssertionError):probe.view_snapshot(binding,'writer')
        root.CurrentNativeWindowHandle=56
        button.CurrentIsOffscreen=False;bar.CurrentIsOffscreen=False
        for reason in ('foreign','not-toolbar','wrong-root'):
            with self.subTest(reason=reason):
                button.CurrentProcessId=999 if reason=='foreign' else 88
                toolbar.CurrentControlType=50033 if reason=='not-toolbar' else 50021
                toolbar.parent=NS(parent=None) if reason=='wrong-root' else root
                with self.assertRaises((AssertionError,AttributeError)):
                    probe.view_snapshot(binding,'writer')

    def test_public_menu_mnemonic_before_ellipsis_is_not_a_different_command(self):
        m=self.feature()
        for text,expected in (('열기(~O)...','열기…'),('다른 이름으로 저장(A)…','다른 이름으로 저장…'),('파일(F)','파일')):
            with self.subTest(text=text):self.assertEqual(m._label(text),expected)
