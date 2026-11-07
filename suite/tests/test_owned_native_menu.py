"""Real native-menu policy at bounded synthetic Windows/UIA boundaries."""
import copy
import ctypes as C
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

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


class ChromeBoundary:
    """Fresh synthetic COM wrappers; production UIA discovery stays real."""
    def __init__(self,module,root,clock,mode=None):
        self.module,self.clock,self.mode=module,clock,mode
        self.native=Probe(root,clock);self.compares=[];self.wrapper_count=0;self.focus_phase=False;self.submenu_open=False
        self.targets=('save','saveAs','open','close','new','new-hwp','home','exit','printPreview',
            'saveAll','saveCopy','new-writer','new-calc','new-impress','new-draw','new-math','new-base')
        class SafeArray(C.Structure):pass
        safe_pointer=C.POINTER(SafeArray);safe_pointer._itemtype_=C.c_int
        class Interface:pass
        Interface._methods_=[NS(name='GetRuntimeId',restype=C.c_int32,
            argtypes=(C.POINTER(safe_pointer),),paramflags=((10,'runtimeId'),),idlflags=(),doc=None)]
        self.interface=Interface
        boundary=self
        class Node:
            __com_interface__=Interface
            def __init__(self,key):
                self.key=key;boundary.wrapper_count+=1;self.wrapper=boundary.wrapper_count
            @property
            def CurrentControlType(self):return 50032 if self.key in ('peer','host') else 50010 if self.key=='bar' else 50011
            @property
            def CurrentName(self):
                return {'file':'파일','edit':'편집','bar':'','peer':'','host':''}.get(self.key,module.LABELS[self.key][0] if self.key in module.LABELS else '')
            @property
            def CurrentProcessId(self):return 77 if self.key=='host' else 999 if mode=='foreignPID' and self.key=='file' else 88
            @property
            def CurrentNativeWindowHandle(self):return 56 if self.key=='peer' else 11 if self.key=='host' else 0
            @property
            def CurrentIsOffscreen(self):return False
            @property
            def CurrentIsEnabled(self):return self.key not in ('saveAll','saveCopy')
            @property
            def CurrentBoundingRectangle(self):
                box=boundary.rectangle(self.key);return NS(left=box[0],top=box[1],right=box[2],bottom=box[3])
            def GetRuntimeId(self):
                if self.key in ('peer','host'):return [4,56 if self.key=='peer' else 11]
                if mode=='NoneRuntime':return None
                if mode=='malformedRuntime':return [True]
                if mode=='late':boundary.clock.now=6.
                if mode=='listRuntime':return []
                return ()
            def FindAll(self,scope,condition):return boundary.find(self.key,scope,condition)
        self.Node=Node
        client=NS(CompareElements=self.compare,ElementFromHandle=self.from_handle,
            ElementFromPoint=self.from_point,GetFocusedElement=self.focused,
            ControlViewWalker=NS(GetParentElement=self.parent),
            CreatePropertyCondition=lambda key,value:(key,value),
            CreateAndCondition=lambda a,b:('and',a,b))
        probe=object.__new__(module.NativeMenuProbe)
        probe.clock=clock;probe.deadline=clock()+5;probe.provider_client=None
        probe._hresult_type=C.c_int32;probe.interop=dict(versionTuple=[1,4,17],versionObserved=True)
        probe._identity_scope=None;probe._identity_refs={}
        probe.uia=NS(iuia=client,tree_scope={'children':2,'descendants':4},build_condition=probe._condition)
        class Point(C.Structure):_fields_=[('x',C.c_int32),('y',C.c_int32)]
        probe._point_type=Point
        probe.user=NS(WindowFromPhysicalPoint=lambda point:self.hit(point),
            GetWindowThreadProcessId=self.window_pid,GetAncestor=lambda hwnd,flag:99 if hwnd==99 else 11,
            IsChild=lambda parent,child:parent==56 and child==56,
            GetWindow=lambda hwnd,flag:56 if hwnd==99 else 0,GetPropW=lambda hwnd,name:1,
            GetAsyncKeyState=lambda key:0,GetForegroundWindow=lambda:11)
        for method in ('process_snapshot','open_engine','engine_snapshot','close_engine','enter_dpi','restore_dpi',
                       'move','editor_snapshot','outside_snapshot','outside_click'):
            setattr(probe,method,getattr(self.native,method))
        probe.click=self.click
        probe._keyboard=lambda:NS(send=self.send,release=lambda payload:len(payload),keyboard_snapshot=lambda thread:
            dict(targetLayout=0x04090409,currentThreadLayout=0x04090409,keysDown=[]))
        probe.attachment_snapshot=lambda binding:dict(valid=True,windows={'child':{'threadId':9}})
        probe.window_snapshot=self.window;probe.foreground=lambda:11
        probe.native_focus=lambda thread:dict(threadId=9,activeHwnd=11,focusHwnd=56,focusPid=88,focusRootHwnd=11,
            captureHwnd=0,menuOwnerHwnd=0,flags=0)
        self.probe=probe

    def rectangle(self,key):
        if key=='file':return [20,20,80,40]
        if key=='edit':return [90,20,150,40]
        if key=='blank':return [90,60,150,80]
        if key in ('peer','host','bar'):return [0,0,400,1000]
        index=self.targets.index(key);return [20,60+30*index,80,80+30*index]

    def find(self,key,scope,condition):
        assert scope in (2,4)
        if key=='peer':keys=(['bar','file'] if self.mode=='TopEditmissing' else ['bar','file','edit']) if scope==4 else ['bar']
        elif key=='host':keys=[]
        elif key=='bar':keys=['file'] if self.mode=='TopEditmissing' else ['file','edit']
        elif key=='file':
            keys=list(self.targets) if self.native.opened else []
            if self.mode in ('nestedNew','unboundIntermediate'):
                if not self.submenu_open:keys=[name for name in keys if name!='new-writer']
                elif self.mode=='unboundIntermediate':keys.append('blank')
        else:raise AssertionError('Unexpected synthetic UIA query')
        def matches(node,query):
            if query[0]=='and':return matches(node,query[1]) and matches(node,query[2])
            assert query[0] in (30003,30005)
            return (node.CurrentControlType if query[0]==30003 else node.CurrentName)==query[1]
        nodes=[node for node in [self.Node(key) for key in keys] if matches(node,condition)]
        return NS(Length=len(nodes),GetElement=lambda index:nodes[index])

    def compare(self,left,right):
        assert isinstance(left,self.Node) and isinstance(right,self.Node)
        if self.mode=='alwaysTrue':result=True
        elif self.mode=='NoneCompare':result=None
        elif self.mode=='invalidCompare':result=2**32
        elif self.mode=='freshFalse':result=left is right
        elif self.mode=='focusbothTRUE' and self.focus_phase and {left.key,right.key}=={'file','bar'}:result=True
        elif self.mode=='stale' and self.native.opened and left.key==right.key=='file':result=False
        else:result=left.key==right.key
        if self.mode=='integerCompare':result=2*int(result)
        self.compares.append((left.key,right.key,result));return result

    def from_handle(self,hwnd):
        assert hwnd in (11,56)
        return self.Node('host' if hwnd==11 else 'peer')

    def from_point(self,point):
        key=('edit' if point.x>=90 else 'file') if point.y<50 else self.targets[(point.y-70)//30]
        if self.mode=='pointFalse':key='edit'
        if self.mode=='wrongtarget' and key!='file':key='saveAs' if key=='save' else 'save'
        return self.Node(key)

    def focused(self):
        self.focus_phase=True
        return self.Node('file')

    def send(self,payload):
        events=tuple((item.payload.keyboard.wVk,item.payload.keyboard.wScan,item.payload.keyboard.dwFlags) for item in payload)
        plans={((0,0x38,8),(0,0x21,8),(0,0x21,10),(0,0x38,10)):'ALT_F',
            ((0,0x50,9),(0,0x50,11)):'DOWN',((0,0x01,8),(0,0x01,10)):'ESCAPE'}
        assert events in plans, 'Unexpected native-menu keyboard payload'
        shortcut=plans[events]
        self.clock.now+=.01;self.native.calls.append(('key',shortcut));self.native.opened=shortcut!='ESCAPE'
        return len(payload)

    def click(self,receipt):
        self.native.click(receipt)
        if self.mode in ('nestedNew','unboundIntermediate') and receipt['target']=='new':
            self.native.opened=True;self.submenu_open=True

    def parent(self,node):
        if self.mode in ('nestedNew','unboundIntermediate') and node.key=='new-writer':
            return self.Node('new' if self.mode=='nestedNew' else 'blank')
        key={'save':'file','file':'bar','edit':'bar','bar':'peer'}.get(node.key,'file' if node.key not in ('peer','host') else None)
        return self.Node(key) if key else None

    def hit(self,point):return 56 if point.y<50 else 99

    def window_pid(self,hwnd,pointer):
        pointer._obj.value=77 if hwnd==11 else 88
        return 7 if hwnd==11 else 9

    def window(self,hwnd):
        assert hwnd in (11,56,99)
        return dict(hwnd=hwnd,pid=77 if hwnd==11 else 88,rootHwnd=99 if hwnd==99 else 11,
            threadId=7 if hwnd==11 else 9,visible=True,enabled=True)


class OwnedNativeMenuTests(unittest.TestCase):
    def lazy_provider_boundary(self, *, provider_error=None):
        from types import ModuleType
        m,a,p,r,c,b=self.real_chrome_fixture();calls=[]
        class Function:
            def __init__(self,name):self.name=name
            def __call__(self,*args):calls.append(('win32',self.name));return 1
        user=NS(**{name:Function(name) for name in (
            'IsWindow','IsWindowVisible','IsWindowEnabled','IsIconic','GetAncestor','GetForegroundWindow',
            'GetWindowThreadProcessId','GetWindowRect','GetTitleBarInfo','WindowFromPhysicalPoint',
            'SetPhysicalCursorPos','GetPhysicalCursorPos','SetThreadDpiAwarenessContext',
            'GetThreadDpiAwarenessContext','AreDpiAwarenessContextsEqual','SendMessageTimeoutW',
            'GetAsyncKeyState','GetSystemMetrics','SendInput','GetWindow','GetWindowTextW',
            'GetClassNameW','IsChild','GetPropW','GetMenuBarInfo','GetGUIThreadInfo')})
        kernel=NS(**{name:Function(name) for name in ('GetProcessId','WaitForSingleObject','GetProcessTimes','QueryFullProcessImageNameW')})
        dwm=NS(DwmGetWindowAttribute=Function('DwmGetWindowAttribute'))
        class Provider:
            def __setattr__(self,name,value):
                if name in ('ConnectionTimeout','TransactionTimeout'):
                    calls.append(('set',name,value))
                    if provider_error is not None:raise provider_error
                object.__setattr__(self,name,value)
            def ElementFromHandle(self,hwnd):calls.append(('root',hwnd));return b.Node('peer')
            def CompareElements(self,left,right):calls.append(('compare',));return left is right
            def CreatePropertyCondition(self,key,value):calls.append(('condition',));return (key,value)
        provider=Provider();expected_interface=type('IUIAutomation2',(),{})
        module=ModuleType('comtypes');client=ModuleType('comtypes.client')
        module.__version__='1.4.17';module.HRESULT=C.c_int32;module.client=client
        def library(name):
            self.assertEqual(name,'UIAutomationCore.dll');calls.append(('module',));return NS(IUIAutomation2=expected_interface,tagPOINT=b.probe._point_type)
        def create(clsid,*,interface):
            self.assertEqual(clsid,m.NativeMenuProbe.CLIENT);self.assertIs(interface,expected_interface)
            calls.append(('create',));return provider
        client.GetModule=library;client.CreateObject=create
        context=patch.dict(sys.modules,{'comtypes':module,'comtypes.client':client})
        return m,a,p,r,c,b,calls,(user,kernel,dwm),context

    def test_constructor_and_initial_win32_failure_do_not_create_or_configure_uia(self):
        m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary()
        primary=RuntimeError('synthetic original native GUI query failure')
        def gui(*args):calls.append(('original-gui',));raise primary
        user.GetGUIThreadInfo=gui
        with context:
            probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
            self.assertEqual(calls,[],'Win32-only construction must not create a UIA client')
            with self.assertRaises(RuntimeError) as caught:probe._call(user.GetGUIThreadInfo,9,None)
            self.assertIs(caught.exception,primary);self.assertEqual(calls,[('original-gui',)])
            self.assertTrue(probe.close_provider())
            self.assertEqual(calls,[('original-gui',)],'Cleanup must not initialize the unused provider')

    def test_real_initial_editor_readiness_expires_without_initializing_uia_or_sending_input(self):
        class COMError(Exception):hresult=-2147024809
        m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary(provider_error=COMError())
        with context:
            probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
            native,queries=self.real_editor_probe(m,c,host_focus=11,engine_focus=11)
            probe.user=native.user;probe.foreground=native.foreground
            probe.user.GetPropW=lambda hwnd,name:1 if name==m.READY_PROPERTY else 55 if name.endswith('ParentHwnd') else 56
            probe.window_snapshot=lambda hwnd:dict(hwnd=11,pid=77,threadId=7,rootHwnd=11,visible=True,enabled=True)
            for name in ('process_snapshot','open_engine','engine_snapshot','close_engine','enter_dpi','restore_dpi'):
                setattr(probe,name,getattr(b.native,name))
            with patch.object(m.time,'sleep',side_effect=c.pause),self.assertRaises(AssertionError):
                m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
            value=r['nativeMenuActions'][-1];first,=value['editorObservations']
            self.assertGreater(first['sampleCount'],1);self.assertLessEqual(first['sampleCount'],101)
            self.assertEqual(value['deadline'],6.);self.assertGreaterEqual(c(),6.)
            self.assertTrue(queries);self.assertEqual(calls,[])
            self.assertEqual(value['pointers'],[]);self.assertEqual(value['keys'],[])
            self.assertTrue(value['providerClientReleased']);self.assertTrue(value['engineHandleReleased'])

    def test_first_actual_uia_query_creates_one_private_client_with_the_original_timeouts(self):
        m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary()
        with context:
            probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
            self.assertEqual(calls,[])
            first=probe._root(56);c.now=2.;second=probe._root(56)
            self.assertEqual((first.key,second.key),('peer','peer'))
            self.assertEqual(sum(row[0]=='create' for row in calls),1)
            self.assertEqual(sum(row[0]=='module' for row in calls),1)
            self.assertEqual([row[2] for row in calls if row[0]=='set'],[1249,1249,1249,1249,999,999])
            self.assertTrue(probe.provider_timeout_verified);self.assertTrue(probe.close_provider())
            count=len(calls);self.assertIsNone(probe.uia);self.assertIsNone(probe.provider_client)
            self.assertEqual(len(calls),count,'A closed provider cannot be recreated by observation')

    def test_uiaccess_first_entries_initialize_without_changing_runtime_or_comparison_guards(self):
        for operation in ('runtime','chrome','same','condition','find','bar'):
            with self.subTest(operation=operation):
                m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary()
                with context:
                    probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
                    self.assertEqual(calls,[])
                    node=b.Node('peer')
                    if operation=='runtime':self.assertEqual(probe._runtime(node)[0],[4,56])
                    elif operation=='chrome':self.assertEqual(probe._chrome(node)['pid'],88)
                    elif operation=='same':self.assertTrue(probe._same(node,node))
                    elif operation=='condition':self.assertEqual(probe._condition(control_type='MenuItem'),(30003,50011))
                    elif operation=='find':self.assertEqual(probe._find(b.Node('bar'),'file',scope='children').key,'file')
                    else:self.assertEqual(probe._discover_bar(node).key,'bar')
                    self.assertEqual(sum(row[0]=='create' for row in calls),1)
                    self.assertTrue(any(row[0]=='set' for row in calls));probe.close_provider()

    def test_expired_first_uia_query_and_cleanup_never_create_a_client(self):
        m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary()
        with context:
            probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
            self.assertEqual(calls,[]);c.now=6.
            with self.assertRaises(AssertionError):probe._root(56)
            self.assertEqual(calls,[]);probe.close_provider();self.assertEqual(calls,[])

    def test_first_uia_timeout_setter_failure_is_not_retried_or_hidden(self):
        class COMError(Exception):hresult=-2147024809
        primary=COMError()
        m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary(provider_error=primary)
        with context:
            probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
            self.assertEqual(calls,[])
            self.assertEqual(probe._call(user.GetGUIThreadInfo,9,None),1)
            with self.assertRaises(COMError) as caught:probe._root(56)
            self.assertIs(caught.exception,primary);self.assertFalse(any(row[0]=='root' for row in calls))
            before=len(calls)
            with self.assertRaises(AssertionError):probe._root(56)
            self.assertEqual(len(calls),before);self.assertTrue(probe.close_provider())

    def test_slow_lazy_provider_preparation_consumes_original_deadline_before_any_uia_target(self):
        for stage in ('GetModule','CreateObject'):
            with self.subTest(stage=stage):
                m,a,p,r,c,b,calls,(user,kernel,dwm),context=self.lazy_provider_boundary()
                with context:
                    probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm)
                    client=sys.modules['comtypes.client'];original=getattr(client,stage)
                    def slow(*args,**kwargs):
                        value=original(*args,**kwargs);c.now=6.;return value
                    setattr(client,stage,slow)
                    with self.assertRaises(AssertionError):probe._root(56)
                    self.assertFalse(any(row[0] in ('set','root') for row in calls))
                    self.assertIsNone(probe.provider_client);self.assertTrue(probe.close_provider())

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

    def real_chrome_fixture(self,mode=None):
        m,a,p,r,c,_=self.fixture();boundary=ChromeBoundary(m,p.opengeul_suite_root,c,mode)
        if mode=='generation':
            p.opengeul_native_menu_generations={(11,55,56,88):(boundary.native.engine['image'],200)}
            boundary.native.engine['creationTime']=201
        if mode=='metadatawrong':boundary.interface._methods_[0].paramflags=((2,'runtimeId'),)
        if mode=='metadataNone':boundary.interface._methods_=None
        return m,a,p,r,c,boundary

    def shell_bar_fixture(self,*,count=1,depth=3,mode=None,owner=77,visible=True,base=None):
        if base is None:m,a,p,r,c,b=self.real_chrome_fixture()
        else:
            m,a,p,r,c,_=base;b=ChromeBoundary(m,p.opengeul_suite_root,c)
        queries=[]
        class ShellNode(b.Node):
            def __init__(self,index,level=0):
                super().__init__('shell-'+str(index)+'-'+str(level));self.index,self.level=index,level
            def observed(self,key,value):
                queries.append((self.index,self.level,key))
                if mode=='late' and key=='nativeHwnd':c.now=6.
                if mode=='property-error' and key=='kind':raise RuntimeError('SYNTHETIC PRIVATE body')
                return value
            @property
            def CurrentProcessId(self):return self.observed('pid',owner)
            @property
            def CurrentIsOffscreen(self):return self.observed('offscreen',not visible)
            @property
            def CurrentControlType(self):
                return self.observed('kind',50010 if self.level==0 else 50032 if self.level==depth-1 else 50037)
            @property
            def CurrentNativeWindowHandle(self):return self.observed('nativeHwnd',11 if self.level==depth-1 else 0)
            @property
            def CurrentName(self):raise AssertionError('Diagnosis read an unknown label')
            @property
            def CurrentAutomationId(self):raise AssertionError('Diagnosis read an unknown automation ID')
            def GetRuntimeId(self):raise AssertionError('Diagnosis read an unrelated runtime ID')
        nodes=[ShellNode(index) for index in range(count)]
        original_find,original_parent,original_compare=b.find,b.parent,b.compare
        def find(key,scope,condition):
            if key!='host':return original_find(key,scope,condition)
            self.assertEqual((scope,condition),(4,(30003,50010)))
            return NS(Length=len(nodes),GetElement=lambda index:nodes[index])
        def parent(node):
            if not isinstance(node,ShellNode):return original_parent(node)
            queries.append((node.index,node.level,'parent'))
            if mode=='parent-error':raise RuntimeError('SYNTHETIC PRIVATE parent')
            return ShellNode(node.index,node.level+1) if node.level+1<depth else None
        def compare(left,right):
            if not isinstance(left,ShellNode):return original_compare(left,right)
            self.assertEqual(right.key,'bar');queries.append((left.index,left.level,'compare'))
            if mode=='compare-error':raise RuntimeError('SYNTHETIC PRIVATE compare')
            if mode=='compare-none':return None
            if mode=='compare-float':return 0.
            return 1 if mode=='engine-alias' else 0
        b.find=find;b.probe.uia.iuia.ControlViewWalker.GetParentElement=parent
        b.probe.uia.iuia.CompareElements=compare
        if mode=='root-malformed':b.probe.user.GetAncestor=lambda hwnd,flag:True
        return m,a,p,r,c,b,queries

    def failed_shell_bar_action(self,**options):
        m,a,p,r,c,b,queries=self.shell_bar_fixture(**options)
        with self.assertRaisesRegex(AssertionError,'Native menu not exclusive and ready'):
            m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
        action=r['nativeMenuActions'][0];snapshot=action['menuObservation']['snapshot']
        self.assertEqual(action['pointers'],[]);self.assertEqual(action['keys'],[])
        self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in b.native.calls))
        self.assertTrue(action['engineHandleReleased']);self.assertTrue(action['providerClientReleased'])
        self.assertFalse(action['success'])
        self.assertTrue('shellMenuObservation' in snapshot,'Counted shell bars need bounded numeric diagnosis')
        return m,action,snapshot,queries

    def test_counted_shell_bar_keeps_numeric_ancestry_without_admitting_native_input(self):
        m,action,snapshot,queries=self.failed_shell_bar_action()
        self.assertEqual(snapshot['shellMenuCount'],1)
        value=snapshot['shellMenuObservation'];self.assertEqual(value['observedCount'],1)
        self.assertEqual(value['statusCode'],1);self.assertFalse(value['truncated'])
        sample,=value['samples'];self.assertEqual(sample['errorCode'],0)
        self.assertIs(sample['sameAsEngineBar'],False)
        self.assertEqual(sample['comparisonCode'],2)
        self.assertEqual([row['controlType'] for row in sample['ancestors']],[50010,50037,50032])
        self.assertEqual([row['hwndAnchorCode'] for row in sample['ancestors']],[0,0,1])
        self.assertEqual([row['ownerRoleCode'] for row in sample['ancestors']],[1,1,1])
        self.assertEqual(queries.count((0,0,'pid')),1);self.assertEqual(queries.count((0,0,'offscreen')),1)
        def numeric(row):
            if isinstance(row,dict):return all(numeric(v) for v in row.values())
            if isinstance(row,list):return all(numeric(v) for v in row)
            return type(row) in (int,bool)
        self.assertTrue(numeric(value))
        import json
        raw=json.dumps(value).encode();self.assertLess(len(raw),128*1024)
        self.assertNotIn(b'SYNTHETIC PRIVATE',raw)

    def test_shell_diagnosis_caps_samples_without_changing_the_original_count(self):
        _,_,snapshot,queries=self.failed_shell_bar_action(count=7)
        value=snapshot['shellMenuObservation']
        self.assertEqual(snapshot['shellMenuCount'],7);self.assertEqual(value['observedCount'],7)
        self.assertEqual(value.get('sampleLimit'),2);self.assertEqual(value.get('ancestorLimit'),32)
        self.assertEqual(len(value['samples']),2);self.assertTrue(value['truncated'])
        self.assertEqual({index for index,_,key in queries if key=='compare'},{0,1})
        self.assertEqual({index for index,_,key in queries if key=='pid'},set(range(7)))
        self.assertFalse(any(index>=2 and key not in ('pid','offscreen') for index,_,key in queries))

    def test_shell_diagnosis_bounds_parent_walk_and_keeps_unknown_identity_closed(self):
        _,_,snapshot,queries=self.failed_shell_bar_action(depth=40)
        value=snapshot['shellMenuObservation'];sample,=value['samples']
        self.assertEqual(len(sample['ancestors']),32)
        self.assertEqual((value['statusCode'],sample['stageCode'],sample['errorCode']),(2,6,5))
        self.assertEqual(sum(key=='parent' for _,_,key in queries),32)

    def test_shell_diagnosis_errors_keep_original_guard_and_never_guess_comparison(self):
        cases=(('compare-error',1),('compare-none',1),('compare-float',1),
               ('property-error',2),('root-malformed',3),('parent-error',4),('late',2))
        for mode,code in cases:
            with self.subTest(mode=mode):
                _,action,snapshot,queries=self.failed_shell_bar_action(mode=mode)
                value=snapshot['shellMenuObservation'];sample,=value['samples']
                self.assertEqual(snapshot['shellMenuCount'],1)
                self.assertEqual((value['statusCode'],sample['errorCode']),(2,code))
                self.assertEqual(action['deadline'],action['startedAt']+5)
                if code==1:
                    self.assertEqual(sample['comparisonCode'],0)
                    self.assertFalse('sameAsEngineBar' in sample)
                if mode=='late':self.assertEqual(queries[-1],(0,0,'nativeHwnd'))
                import json
                self.assertNotIn('SYNTHETIC PRIVATE',json.dumps(value))

    def test_engine_bar_alias_diagnosis_does_not_remove_the_counted_shell_bar(self):
        _,_,snapshot,_=self.failed_shell_bar_action(mode='engine-alias')
        sample,=snapshot['shellMenuObservation']['samples']
        self.assertIs(sample['sameAsEngineBar'],True);self.assertEqual(sample['comparisonCode'],1)
        self.assertEqual(snapshot['shellMenuCount'],1)

    def test_noncounted_bars_get_no_additional_diagnostic_queries(self):
        for owner,visible in ((88,True),(77,False)):
            with self.subTest(owner=owner,visible=visible):
                m,a,p,r,c,b,queries=self.shell_bar_fixture(owner=owner,visible=visible)
                value=m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
                self.assertTrue(value['success']);m.require_native_menu_action(value,77,11,'save')
                self.assertTrue(all(key in ('pid','offscreen') for _,_,key in queries))
                snapshot=value['pointers'][0]['snapshots'][0]
                self.assertEqual(snapshot['shellMenuCount'],0)
                self.assertFalse('shellMenuObservation' in snapshot)

    def system_bar_fixture(self,mode=None,*,base=None):
        m,a,p,r,c,b,queries=self.shell_bar_fixture(base=base);node=type(b.find('host',4,(30003,50010)).GetElement(0))
        calls=[];system_point=(-10,-10) if mode=='negative-point' else (10,10)
        find_point=b.probe.uia.iuia.ElementFromPoint;compare=b.probe.uia.iuia.CompareElements
        hit=b.probe.user.WindowFromPhysicalPoint;parent=b.probe.uia.iuia.ControlViewWalker.GetParentElement
        def point_value(point):return (point.x,point.y)
        def from_point(point):
            if point_value(point)==system_point:
                calls.append('uia-point')
                return b.Node('file') if mode=='foreign-point' else node(1 if mode=='fresh-false' and calls.count('uia-point')>1 else 0)
            return find_point(point)
        def canonical(item):
            if isinstance(item,node):return 'host' if item.level==2 else ('title',item.index) if item.level==1 else ('system',item.index)
            return item.key
        def same(left,right):
            if isinstance(left,node) or isinstance(right,node):
                calls.append('compare')
                if mode=='bad-compare':return None
                if mode=='always-same':return True
                return int(canonical(left)==canonical(right))
            return compare(left,right)
        def menu_info(hwnd,object_id,item,pointer):
            self.assertEqual((hwnd,object_id,item),(11,-1,0));calls.append('menu-info')
            info=pointer._obj;self.assertEqual(info.cbSize,48)
            rect=(-20,-20,0,0) if mode=='negative-point' else (32768,0,32788,20) if mode=='overflow-point' else (0,0,20,20)
            info.rcBar.left,info.rcBar.top,info.rcBar.right,info.rcBar.bottom=rect
            info.hMenu=0 if mode=='no-menu' else 112 if mode=='stale-menu' and calls.count('menu-info')>1 else 111
            info.hwndMenu=0;info.flags=0;return 1
        def title_info(hwnd,pointer):
            self.assertEqual(hwnd,11);calls.append('title-info');info=pointer._obj
            self.assertEqual(info.cbSize,44)
            info.rectangle.left,info.rectangle.top,info.rectangle.right,info.rectangle.bottom=(20,0,400,20)
            if calls.count('title-info')>1:
                if mode=='generation':b.native.engine['creationTime']=201
                if mode=='focus-shift':b.probe.native_focus=lambda thread:dict(threadId=9,focusPid=77,focusRootHwnd=11,captureHwnd=0,menuOwnerHwnd=0,flags=0)
            info.states[0]=0;return 1
        def message(hwnd,msg,wparam,lparam,flags,milliseconds,pointer):
            self.assertEqual((hwnd,msg,wparam,flags),(11,0x84,0,3))
            self.assertTrue(1<=milliseconds<=200);calls.append('hit-test')
            if mode=='timeout':return 0
            pointer._obj.value=1 if mode=='client-hit' else 3;return 1
        def ancestors(item):
            if not isinstance(item,node):return parent(item)
            if mode=='pane' and item.level==0:
                return NS(CurrentControlType=50033,CurrentProcessId=77,CurrentNativeWindowHandle=55)
            return node(0,1) if item.level==0 else b.Node('host') if item.level==1 else None
        b.probe.user.GetMenuBarInfo=menu_info;b.probe.user.GetTitleBarInfo=title_info
        b.probe.user.GetThreadDpiAwarenessContext=lambda:-4
        b.probe.user.AreDpiAwarenessContextsEqual=lambda left,right:int(left==right)
        b.probe.user.SendMessageTimeoutW=message
        def physical(point):
            if point_value(point)!=system_point:return hit(point)
            if mode=='submillisecond':c.now=5.9995
            return 55 if mode=='physical-foreign' else 11
        b.probe.user.WindowFromPhysicalPoint=physical
        b.probe.uia.iuia.ElementFromPoint=from_point;b.probe.uia.iuia.CompareElements=same
        b.probe.uia.iuia.ControlViewWalker.GetParentElement=ancestors
        if mode=='alternating-focus':
            def focus():
                calls.append('focused');return b.Node('file' if calls.count('focused')%2 else 'bar')
            b.probe.uia.iuia.GetFocusedElement=focus
        return m,a,p,r,c,b,calls

    def test_independent_os_system_point_proof_keeps_raw_count_and_allows_only_that_bar(self):
        m,a,p,r,c,b,calls=self.system_bar_fixture()
        try:value=m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
        except AssertionError:self.fail('Complete independent OS system-menu proof must be classified')
        self.assertTrue(value['success']);m.require_native_menu_action(value,77,11,'save')
        for pointer in value['pointers']:
            for snapshot in pointer['snapshots']:
                self.assertEqual(snapshot['shellMenuCount'],1)
                proof=snapshot['shellMenuClassification']
                self.assertEqual((proof['verifiedSystemCount'],proof['clientCount'],proof['unknownCount']),(1,0,0))
                self.assertTrue(proof['proofs'][0]['pointBarEqualsCounted'])
        self.assertTrue('menu-info' in calls and 'hit-test' in calls and 'uia-point' in calls)

    def test_os_system_point_failures_never_exclude_a_bar_or_send_native_input(self):
        for mode in ('stale-menu','generation','no-menu','timeout','client-hit','foreign-point','fresh-false',
                     'bad-compare','always-same','pane','physical-foreign','overflow-point','submillisecond'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b,calls=self.system_bar_fixture(mode)
                with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
                action=r['nativeMenuActions'][0];self.assertEqual(action['pointers'],[]);self.assertEqual(action['keys'],[])
                snapshot=action['menuObservation']['snapshot'];value=snapshot['shellMenuClassification']
                self.assertEqual(snapshot['shellMenuCount'],1)
                self.assertEqual((value['verifiedSystemCount'],value['unknownCount']),(0,1))
                self.assertTrue(type(value['errorCode']) is int and 1<=value['errorCode']<=7)
                self.assertEqual(value['proofs'],[])
                if mode in ('overflow-point','submillisecond'):self.assertFalse('hit-test' in calls)
                self.assertTrue(action['engineHandleReleased']);self.assertTrue(action['providerClientReleased'])

    def test_os_system_point_negative_coordinates_roundtrip_without_caption_containment(self):
        m,a,p,r,c,b,_=self.system_bar_fixture('negative-point')
        value=m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
        self.assertTrue(value['success']);m.require_native_menu_action(value,77,11,'save')
        proof=value['pointers'][0]['snapshots'][0]['shellMenuClassification']['proofs'][0]
        self.assertEqual(proof['point'],[-10,-10]);self.assertEqual(proof['before']['captionRect'],[20,0,400,20])

    def test_focus_change_during_os_classification_is_rechecked_before_input(self):
        m,a,p,r,c,b,_=self.system_bar_fixture('focus-shift')
        with self.assertRaises(AssertionError):m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
        action=r['nativeMenuActions'][0];self.assertEqual(action['pointers'],[])
        snapshot=action['menuObservation']['snapshot']
        self.assertEqual(snapshot['shellMenuClassification']['verifiedSystemCount'],1)
        self.assertEqual(snapshot['gui']['focusPid'],77)

    def test_os_system_point_replay_rejects_missing_wrong_scope_and_incomplete_live_proof(self):
        m,a,p,r,c,b,_=self.system_bar_fixture();original=m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
        for mode in ('missing','scope','scope-bool','hit','metadata','alias','ancestor','unknown','typed-count','fresh'):
            with self.subTest(mode=mode):
                value=copy.deepcopy(original);snapshot=value['pointers'][0]['snapshots'][0]
                if mode=='missing':snapshot.pop('shellMenuClassification')
                else:
                    row=snapshot['shellMenuClassification'];proof=row['proofs'][0]
                    if mode=='scope':row['scope']['officeCreationTime']+=1
                    elif mode=='scope-bool':row['scope']['version']=True
                    elif mode=='hit':proof['physicalHit']['hitTest']=1
                    elif mode=='metadata':proof['after']['menuHandle']+=1
                    elif mode=='alias':proof['engineBarDifferent']=False
                    elif mode=='ancestor':proof['ancestry'][1][0]=50033
                    elif mode=='unknown':row['unknownCount']=1
                    elif mode=='typed-count':row['verifiedSystemCount']=True
                    elif mode=='fresh':proof['freshPointBarEqualsRetained']=False
                with self.assertRaises((AssertionError,KeyError)):m.require_native_menu_action(value,77,11,'save')

    def test_view_uses_its_fresh_scope_and_identical_os_point_rule(self):
        m,a,p,r,c,b,_=self.system_bar_fixture()
        origin=m.click_native_menu_action(a,p,11,r,'save',probe=b.probe,clock=c)
        r.update(module='writer',officeCreationTime=200,nativeArchiveGeneration=dict(pid=88,creationTime=200,image=b.native.engine['image']))
        m,a,p,r,c,b,_=self.system_bar_fixture(base=(m,a,p,r,c,b));c.now=2.;b.probe.deadline=7.;counter=[0]
        def prop(hwnd,name):
            if name==m.STATUS_PROPERTY:
                counter[0]+=1;return (1<<56)|(counter[0]<<28)|counter[0]
            return 1
        b.probe.user.GetPropW=prop
        value=m.observe_native_view(a,p,11,r,module='writer',preview=False,menu_visible=True,probe=b.probe,clock=c,pause=c.pause)
        self.assertTrue(value['success']);self.assertTrue(value['statusRpcProved'])
        scope=dict(version=1,binding=dict(document=11,parent=55,child=56,officePid=88),shellPid=77,
            shellCreationTime=100,officeCreationTime=200,startedAt=2.,deadline=7.)
        for sample in value['samples']:
            row=sample['state'];self.assertEqual(row['shellMenuCount'],1)
            self.assertEqual(row['shellMenuClassification']['scope'],scope)
            m._require_shell_menus(row,scope['binding'],77,scope)
            old=dict(scope,startedAt=origin['startedAt'],deadline=origin['deadline'])
            with self.assertRaises(AssertionError):m._require_shell_menus(row,scope['binding'],77,old)

    def test_fullscreen_without_engine_bar_anchor_stays_unknown(self):
        m,a,p,r,c,b,_=self.system_bar_fixture();binding=dict(document=11,parent=55,child=56,officePid=88)
        scope=dict(version=1,binding=binding,shellPid=77,shellCreationTime=100,officeCreationTime=200,startedAt=1.,deadline=6.)
        b.probe.bind_menu_classification(scope,lambda:None);find=b.find
        def hidden(key,tree,condition):
            if key=='peer' and condition==(30003,50010):return NS(Length=0,GetElement=lambda index:None)
            return find(key,tree,condition)
        b.find=hidden
        value=b.probe.view_snapshot(binding,'writer')
        self.assertEqual(value['nativeMenuBarCount'],0);self.assertEqual(value['shellMenuCount'],1)
        self.assertEqual(value['shellMenuClassification']['unknownCount'],1)
        self.assertEqual(value['shellMenuClassification']['errorCode'],2)
        with self.assertRaises(AssertionError):m._require_shell_menus(value,binding,77,scope)
        self.assertFalse(any(isinstance(x,tuple) and x[0] in ('click','key') for x in b.native.calls))

    def test_system_classification_refreshes_focus_identity_with_the_new_focus_chain(self):
        m,a,p,r,c,b,_=self.system_bar_fixture('alternating-focus')
        try:value=m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=b.probe,clock=c)
        except AssertionError:self.fail('Refreshed menu focus identity must match its refreshed chain')
        self.assertTrue(value['success']);m.require_native_menu_action(value,77,11)
        for item in value['keys'][1:]:self.assertEqual(item['before']['focusIdentity']['role'],'bar')

    def test_view_status_baseline_is_read_after_final_os_classification(self):
        m,a,p,r,c,b,calls=self.system_bar_fixture();binding=dict(document=11,parent=55,child=56,officePid=88)
        scope=dict(version=1,binding=binding,shellPid=77,shellCreationTime=100,officeCreationTime=200,startedAt=1.,deadline=6.)
        b.probe.bind_menu_classification(scope,lambda:None)
        def prop(hwnd,name):
            if name==m.STATUS_PROPERTY:
                number=2 if calls.count('title-info')>=2 else 1
                return (1<<56)|(number<<28)|number
            return 1
        b.probe.user.GetPropW=prop
        value=b.probe.view_snapshot(binding,'writer')
        self.assertEqual(m.decode_status_sequence(value['statusSequenceRaw']),dict(version=1,started=2,completed=2))

    def test_failed_save_hit_retains_primary_booleans_and_numeric_owned_ancestry(self):
        m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget')
        original_name=b.Node.CurrentName.fget;original_runtime=b.Node.GetRuntimeId
        def name(node):
            self.assertFalse(isinstance(getattr(b.probe,'_diagnostic_sink',None),dict),'Diagnostic read a chrome or document name')
            return original_name(node)
        def runtime(node):
            self.assertFalse(isinstance(getattr(b.probe,'_diagnostic_sink',None),dict),'Diagnostic read an unbound runtime ID')
            return original_runtime(node)
        b.Node.CurrentName=property(name);b.Node.GetRuntimeId=runtime
        with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
        action=r['nativeMenuActions'][0];ui=action['uiaInterop']
        self.assertTrue('pointObservation' in ui,'Failed Save hit needs its partial numeric context')
        point=ui['pointObservation'];self.assertEqual(point['targetCode'],2)
        self.assertIs(point['primary']['targetEqualsRetained'],True)
        self.assertIs(point['primary']['hitEqualsRetained'],False)
        self.assertTrue(point['failed']);self.assertEqual(point['target']['kindCode'],50011)
        self.assertEqual(point['diagnostic']['nodes'][0]['kindCode'],50011)
        self.assertLessEqual(len(point['diagnostic']['nodes']),8)
        self.assertEqual(point['diagnostic']['guiStatus'],2)
        self.assertEqual(point['diagnostic']['gui']['threadId'],9)
        self.assertEqual(point['diagnostic']['foreground'],dict(hwnd=11,pid=77,rootHwnd=11))
        self.assertEqual(action['pointers'][0]['insertedInputs'],2);self.assertEqual(action['keys'],[])
        self.assertTrue(action['providerClientReleased']);self.assertTrue(action['engineHandleReleased'])

    def test_root_com_failure_retains_numeric_hresult_without_exception_text(self):
        m,a,p,r,c,b=self.real_chrome_fixture()
        class COMError(Exception):
            hresult=-2147467259
            def __str__(self):raise AssertionError('Exception text must not be inspected')
        primary=COMError()
        def root(hwnd):raise primary
        b.probe.uia.iuia.ElementFromHandle=root
        with self.assertRaises(COMError) as caught:m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
        self.assertIs(caught.exception,primary)
        ui=r['nativeMenuActions'][0]['uiaInterop']
        self.assertTrue('primaryFailureCall' in ui,'Original COM API and HRESULT must survive cleanup')
        call=ui['primaryFailureCall'];self.assertEqual(call['apiCode'],1)
        self.assertTrue(call['calleeEntered']);self.assertFalse(call['callCompleted'])
        self.assertTrue(call['hresultObserved']);self.assertEqual(call['hresult'],-2147467259)

    def test_failed_save_point_preserves_existing_enabled_and_visible_metadata(self):
        m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');enabled=b.Node.CurrentIsEnabled.fget
        b.Node.CurrentIsEnabled=property(lambda node:False if node.key=='save' else enabled(node))
        with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
        target=r['nativeMenuActions'][0]['uiaInterop']['pointObservation']['target']
        self.assertTrue('enabled' in target and 'visible' in target,'Already-read target availability must survive the point guard')
        self.assertIs(target['enabled'],False);self.assertIs(target['visible'],True)

    def test_diagnostic_error_cannot_overwrite_the_primary_identity_failure(self):
        m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');original=b.Node.CurrentProcessId.fget
        class COMError(Exception):
            hresult=-2147467259
            def __str__(self):raise AssertionError('Exception text must not be inspected')
        def pid(node):
            if isinstance(getattr(b.probe,'_diagnostic_sink',None),dict) and node.key=='saveAs':raise COMError()
            return original(node)
        b.Node.CurrentProcessId=property(pid)
        with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
        ui=r['nativeMenuActions'][0]['uiaInterop'];point=ui['pointObservation'];diag=point['diagnostic']
        self.assertEqual(point['exceptionCode'],1);self.assertFalse(point['hresultObserved'])
        self.assertFalse(ui['primaryFailureCall']['hresultObserved'])
        self.assertTrue(ui['lastCall']==ui['primaryFailureCall'],'Diagnostic call replaced primary API context')
        self.assertEqual(diag['pointStatus'],3);self.assertTrue(diag['pointError']['hresultObserved'])
        self.assertEqual(diag['pointError']['hresult'],-2147467259)

    def test_foreign_point_has_no_parent_walk_and_stale_parent_keeps_original_failure(self):
        for mode in ('foreign','stale'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');parents=[]
                original=b.probe.uia.iuia.ControlViewWalker.GetParentElement
                if mode=='foreign':
                    class Foreign(b.Node):
                        CurrentProcessId=property(lambda node:999)
                        @property
                        def CurrentControlType(node):
                            self.assertFalse(isinstance(getattr(b.probe,'_diagnostic_sink',None),dict),'Foreign header read beyond PID')
                            return 50020
                    point=b.probe.uia.iuia.ElementFromPoint
                    b.probe.uia.iuia.ElementFromPoint=lambda pos:Foreign('saveAs') if pos.y>=50 else point(pos)
                def parent(node):
                    if isinstance(getattr(b.probe,'_diagnostic_sink',None),dict):parents.append(node.key);raise RuntimeError('synthetic stale provider')
                    return original(node)
                b.probe.uia.iuia.ControlViewWalker.GetParentElement=parent
                with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                diag=r['nativeMenuActions'][0]['uiaInterop']['pointObservation']['diagnostic']
                self.assertEqual(diag['pointStatus'],5 if mode=='foreign' else 3)
                self.assertEqual(diag['parentQueries'],0 if mode=='foreign' else 1)
                self.assertEqual(len(parents),0 if mode=='foreign' else 1)

    def test_near_or_exhausted_deadline_skips_all_new_failure_queries(self):
        for moment in (5.98,6.):
            with self.subTest(moment=moment):
                m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');compare=b.probe.uia.iuia.CompareElements
                def same(left,right):
                    value=compare(left,right)
                    if left.key=='saveAs' and right.key=='edit':c.now=moment
                    return value
                b.probe.uia.iuia.CompareElements=same
                with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                action=r['nativeMenuActions'][0];diag=action['uiaInterop']['failureContext']
                self.assertEqual((diag['guiStatus'],diag['pointStatus']),(1,1))
                self.assertEqual(diag['nodes'],[]);self.assertEqual(diag['parentQueries'],0)
                self.assertEqual(action['keys'],[]);self.assertEqual(len(action['pointers']),1)

    def test_failure_gui_admission_errors_block_all_additional_uia_queries(self):
        for mode in ('continuity','child','attachment','gui'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');queries=[]
                bind=b.probe.bind_menu_classification;window=b.probe.window_snapshot
                attachment=b.probe.attachment_snapshot;focus=b.probe.native_focus;uia_call=b.probe._uia_call
                def diagnostic():return isinstance(getattr(b.probe,'_diagnostic_sink',None),dict)
                def bind_scope(scope,continuity):
                    def guarded():
                        if diagnostic() and mode=='continuity':raise AssertionError('synthetic generation ended')
                        return continuity()
                    return bind(scope,guarded)
                def owned_window(hwnd):
                    row=window(hwnd)
                    if diagnostic() and mode=='child':row['pid']=999
                    return row
                def attached(binding):
                    if diagnostic() and mode=='attachment':return dict(valid=False)
                    return attachment(binding)
                def gui(thread):
                    if diagnostic() and mode=='gui':raise RuntimeError('synthetic unavailable GUI state')
                    return focus(thread)
                def observed_call(code,*args):
                    if diagnostic():queries.append(code)
                    return uia_call(code,*args)
                b.probe.bind_menu_classification=bind_scope;b.probe.window_snapshot=owned_window
                b.probe.attachment_snapshot=attached;b.probe.native_focus=gui;b.probe._uia_call=observed_call
                with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                action=r['nativeMenuActions'][0];ui=action['uiaInterop'];diag=ui['failureContext']
                self.assertEqual((diag['guiStatus'],diag['pointStatus']),(3,7))
                self.assertEqual(queries,[]);self.assertEqual((diag['parentQueries'],diag['nodes']),(0,[]))
                self.assertEqual(ui['pointObservation']['exceptionCode'],1)
                self.assertEqual(len(action['pointers']),1);self.assertEqual(action['keys'],[])

    def test_failure_parent_walk_marks_post_ownership_loss_or_budget_unavailable(self):
        for mode in ('continuity','attachment','budget','stable'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');walked=[]
                bind=b.probe.bind_menu_classification;attachment=b.probe.attachment_snapshot
                parent=b.probe.uia.iuia.ControlViewWalker.GetParentElement
                def bind_scope(scope,continuity):
                    def guarded():
                        if walked and mode=='continuity':raise AssertionError('synthetic generation ended during walk')
                        return continuity()
                    return bind(scope,guarded)
                def attached(binding):
                    if walked and mode=='attachment':return dict(valid=False)
                    return attachment(binding)
                def ancestors(node):
                    value=parent(node)
                    if isinstance(getattr(b.probe,'_diagnostic_sink',None),dict):
                        walked.append(node.key)
                        if mode=='budget':c.now=5.98
                    return value
                b.probe.bind_menu_classification=bind_scope;b.probe.attachment_snapshot=attached
                b.probe.uia.iuia.ControlViewWalker.GetParentElement=ancestors
                with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                action=r['nativeMenuActions'][0];ui=action['uiaInterop'];diag=ui['failureContext']
                self.assertTrue(walked);self.assertEqual(diag['guiStatus'],2)
                self.assertTrue('ownershipPostStatus' in diag,'Point context needs a final original-generation check')
                self.assertEqual(diag['ownershipPostStatus'],2 if mode=='stable' else 1 if mode=='budget' else 3)
                self.assertEqual(diag['ownershipPostVerified'],mode=='stable')
                self.assertEqual(ui['pointObservation']['exceptionCode'],1)
                self.assertTrue(ui['lastCall']==ui['primaryFailureCall'])
                self.assertEqual(len(action['pointers']),1);self.assertEqual(action['keys'],[])

    def discovery_observation(self, probe):
        self.assertIn('menuDiscovery',probe.interop,'Existing menu enumeration needs a numeric stage projection')
        row=probe.interop['menuDiscovery']
        self.assertEqual(set(row),set('schemaVersion queryKindCode targetCode candidateCount examinedCount visibleCount matchedCount observedMask scanComplete rejectCode'.split()))
        self.assertTrue(all(type(value) is int for value in row.values()))
        return row

    def test_menu_discovery_distinguishes_empty_bar_from_empty_file_without_extra_queries(self):
        for kind in (1,2):
            with self.subTest(queryKindCode=kind):
                m,_,_,_,_,b=self.real_chrome_fixture();p=b.probe;p._active_target='file';calls=[];original=p._uia_call
                p._uia_call=lambda code,*args:(calls.append(code),original(code,*args))[1]
                b.find=lambda *args:NS(Length=0,GetElement=lambda index:(_ for _ in ()).throw(AssertionError('No element may be read')))
                with self.assertRaises(m.NativeMenuPending):
                    if kind==1:p._discover_bar(b.Node('peer'))
                    else:p._find_labels(b.Node('bar'),m.LABELS['file'])
                row=self.discovery_observation(p)
                self.assertEqual(row,dict(schemaVersion=1,queryKindCode=kind,targetCode=1,candidateCount=0,
                    examinedCount=0,visibleCount=0,matchedCount=0,observedMask=9,scanComplete=1,rejectCode=kind))
                self.assertEqual(calls,[13,2,17]);self.assertEqual(b.native.calls,[])

    def test_menu_discovery_preserves_actual_selected_objects_on_normal_completion(self):
        for kind in (1,2):
            with self.subTest(queryKindCode=kind):
                m,_,_,_,_,b=self.real_chrome_fixture();p=b.probe;p._active_target='file'
                selected=p._discover_bar(b.Node('peer')) if kind==1 else p._find_labels(b.Node('bar'),m.LABELS['file'])
                self.assertEqual(selected.key,'bar' if kind==1 else 'file')
                row=self.discovery_observation(p)
                self.assertEqual((row['candidateCount'],row['examinedCount'],row['visibleCount'],row['matchedCount']),(1,1,1,1) if kind==1 else (2,2,2,1))
                self.assertEqual((row['observedMask'],row['scanComplete'],row['rejectCode']),(31,1,0))

    def test_menu_discovery_failed_count_query_does_not_claim_zero_candidates(self):
        m,_,_,_,_,b=self.real_chrome_fixture();p=b.probe;p._active_target='file'
        class COMError(Exception):
            hresult=-2146233083
            def __str__(self):raise AssertionError('Exception text must not be inspected')
        primary=COMError()
        def fail(*args):raise primary
        b.find=fail
        with self.assertRaises(COMError) as caught:p._discover_bar(b.Node('peer'))
        self.assertIs(caught.exception,primary);row=self.discovery_observation(p)
        self.assertEqual((row['candidateCount'],row['observedMask'],row['scanComplete'],row['rejectCode']),(0,0,0,0))
        self.assertFalse(p.interop['lastCall']['callCompleted']);self.assertTrue(p.interop['lastCall']['failed'])
        self.assertEqual(b.native.calls,[])

    def test_menu_discovery_partial_enumeration_keeps_exception_and_prefix_counts(self):
        m,_,_,_,_,b=self.real_chrome_fixture();p=b.probe;p._active_target='file';calls=[];original=p._uia_call
        p._uia_call=lambda code,*args:(calls.append(code),original(code,*args))[1]
        class COMError(Exception):
            hresult=-2146233083
            def __str__(self):raise AssertionError('Exception text must not be inspected')
        primary=COMError()
        def element(index):
            if index==1:raise primary
            return b.Node('file')
        b.find=lambda *args:NS(Length=2,GetElement=element)
        with self.assertRaises(COMError) as caught:p._find_labels(b.Node('bar'),m.LABELS['file'])
        self.assertIs(caught.exception,primary);row=self.discovery_observation(p)
        self.assertEqual((row['candidateCount'],row['examinedCount'],row['visibleCount'],row['matchedCount']),(2,1,1,1))
        self.assertEqual((row['observedMask'],row['scanComplete'],row['rejectCode']),(7,0,0))
        self.assertEqual(calls,[13,2,17,18,9,11,16,18]);self.assertEqual(b.native.calls,[])

    def test_menu_discovery_invisible_and_ambiguous_candidates_remain_rejected(self):
        for mode in ('invisible','ambiguous'):
            with self.subTest(mode=mode):
                m,_,_,_,_,b=self.real_chrome_fixture();p=b.probe;p._active_target='file'
                class Node(b.Node):
                    @property
                    def CurrentIsOffscreen(self):return mode=='invisible'
                    @property
                    def CurrentName(self):raise AssertionError('Bar discovery must not read names')
                b.find=lambda *args:NS(Length=2,GetElement=lambda index:Node('bar'))
                with self.assertRaises(m.NativeMenuPending if mode=='invisible' else AssertionError):p._discover_bar(b.Node('peer'))
                row=self.discovery_observation(p)
                self.assertEqual((row['candidateCount'],row['examinedCount'],row['scanComplete']),(2,2,1))
                self.assertEqual((row['visibleCount'],row['matchedCount'],row['rejectCode']),(0,0,1) if mode=='invisible' else (2,2,3))
                self.assertEqual(b.native.calls,[])

    def test_provider_setup_failure_or_slow_setter_is_distinct_from_callee_entry(self):
        for mode in ('error','slow'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b=self.real_chrome_fixture();client=b.probe.uia.iuia
                class COMError(Exception):
                    hresult=-2147467259
                    def __str__(self):raise AssertionError('Exception text must not be inspected')
                class Provider:
                    def __getattr__(self,name):return getattr(client,name)
                    @property
                    def ConnectionTimeout(self):return 1
                    @ConnectionTimeout.setter
                    def ConnectionTimeout(self,value):
                        if mode=='error':raise COMError()
                        c.now=6.
                provider=Provider();b.probe.provider_client=provider;b.probe.uia.iuia=provider
                with self.assertRaises(COMError if mode=='error' else AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                call=r['nativeMenuActions'][0]['uiaInterop']['primaryFailureCall']
                self.assertEqual((call['apiCode'],call['phaseCode'],call['providerStep']),(1,1,1))
                self.assertFalse(call['calleeEntered']);self.assertFalse(call['callCompleted'])
                self.assertEqual(call['hresultObserved'],mode=='error')

    def test_api_codes_distinguish_find_runtime_and_point_failures(self):
        for code in (2,3,4):
            with self.subTest(code=code):
                m,a,p,r,c,b=self.real_chrome_fixture()
                class COMError(Exception):
                    hresult=-2147467259
                    def __str__(self):raise AssertionError('Exception text must not be inspected')
                primary=COMError()
                def fail(*args):raise primary
                if code==2:b.find=fail
                elif code==3:b.Node.GetRuntimeId=fail
                else:b.probe.uia.iuia.ElementFromPoint=fail
                with self.assertRaises(COMError) as caught:m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                self.assertIs(caught.exception,primary)
                call=r['nativeMenuActions'][0]['uiaInterop']['primaryFailureCall']
                self.assertEqual(call['apiCode'],code);self.assertTrue(call['calleeEntered'])
                self.assertEqual(call['phaseCode'],2)

    def test_uncoded_native_provider_setup_failure_retains_last_call_before_propagation(self):
        m,a,p,r,c,b=self.real_chrome_fixture()
        class COMError(Exception):hresult=-2147467259
        class Provider:
            @property
            def ConnectionTimeout(self):return 1
            @ConnectionTimeout.setter
            def ConnectionTimeout(self,value):raise COMError()
        b.probe.provider_client=Provider()
        with self.assertRaises(COMError):b.probe._call(lambda:None)
        self.assertFalse('primaryFailureCall' in b.probe.interop,'An API error is not primary before it escapes the action')
        call=b.probe.interop['lastCall']
        self.assertEqual((call['apiCode'],call['phaseCode'],call['providerStep']),(0,1,1))
        self.assertFalse(call['calleeEntered']);self.assertTrue(call['hresultObserved'])

    def test_recovered_optional_shell_error_cannot_become_the_later_primary_failure(self):
        for mode in ('root','point','guard'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b,_=self.system_bar_fixture();optional=[];inside=[]
                observe=b.probe._shell_menu_observation;compare=b.probe.uia.iuia.CompareElements
                root=b.probe.uia.iuia.ElementFromHandle;point=b.probe.uia.iuia.ElementFromPoint
                class COMError(Exception):
                    def __init__(self,hresult):self.hresult=hresult
                    def __str__(self):raise AssertionError('Exception text must not be inspected')
                recovered=COMError(-2147467259);primary=COMError(-2147024891)
                def observation(*args):
                    inside.append(True)
                    try:return observe(*args)
                    finally:inside.pop()
                def comparison(left,right):
                    if inside and not optional:optional.append(True);raise recovered
                    return compare(left,right)
                def from_handle(hwnd):
                    if mode=='root' and b.probe._active_target=='save':raise primary
                    return root(hwnd)
                def from_point(pos):
                    if mode=='point' and b.probe._active_target=='save':raise primary
                    return point(pos)
                b.probe._shell_menu_observation=observation;b.probe.uia.iuia.CompareElements=comparison
                b.probe.uia.iuia.ElementFromHandle=from_handle;b.probe.uia.iuia.ElementFromPoint=from_point
                if mode=='guard':b.mode='wrongtarget'
                with self.assertRaises(AssertionError if mode=='guard' else COMError) as caught:
                    m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                action=r['nativeMenuActions'][0];ui=action['uiaInterop'];call=ui['primaryFailureCall']
                self.assertEqual(optional,[True]);self.assertEqual(action['pointers'][0]['snapshots'][0]['shellMenuObservation']['statusCode'],2)
                self.assertEqual(action['pointers'][0]['snapshots'][0]['shellMenuClassification']['verifiedSystemCount'],1)
                self.assertEqual(call['apiCode'],1 if mode=='root' else 4 if mode=='point' else 5)
                self.assertEqual(call['hresultObserved'],mode!='guard')
                self.assertEqual(call['failed'],mode!='guard')
                self.assertEqual(ui['primaryFailureFromApi'],mode!='guard')
                if mode!='guard':self.assertEqual(call['hresult'],-2147024891);self.assertIs(caught.exception,primary)
                self.assertEqual(len(action['pointers']),1);self.assertEqual(action['keys'],[])

    def test_failure_diagnostic_setter_errors_do_not_replace_the_guard_context(self):
        for mode in ('error','slow'):
            with self.subTest(mode=mode):
                m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');client=b.probe.uia.iuia
                class COMError(Exception):
                    hresult=-2147467259
                    def __str__(self):raise AssertionError('Exception text must not be inspected')
                class Provider:
                    connection=transaction=0
                    def __getattr__(self,name):return getattr(client,name)
                    @property
                    def ConnectionTimeout(self):return self.connection
                    @ConnectionTimeout.setter
                    def ConnectionTimeout(self,value):
                        if isinstance(getattr(b.probe,'_diagnostic_sink',None),dict):
                            if mode=='error':raise COMError()
                            c.now=6.
                        self.connection=value
                    @property
                    def TransactionTimeout(self):return self.transaction
                    @TransactionTimeout.setter
                    def TransactionTimeout(self,value):self.transaction=value
                provider=Provider();b.probe.provider_client=provider;b.probe.uia.iuia=provider
                with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                ui=r['nativeMenuActions'][0]['uiaInterop'];diag=ui['failureContext']
                self.assertFalse(ui['primaryFailureCall']['hresultObserved'])
                self.assertEqual(ui['primaryFailureCall']['apiCode'],5)
                self.assertEqual(diag['guiStatus'],3)
                self.assertEqual((diag['lastCall']['phaseCode'],diag['lastCall']['providerStep']),(1,1))
                self.assertFalse(diag['lastCall']['calleeEntered'])
                self.assertTrue(ui['lastCall']==ui['primaryFailureCall'])

    def test_failure_parent_cycle_stops_at_eight_without_changing_input_or_cap(self):
        m,a,p,r,c,b=self.real_chrome_fixture('wrongtarget');parent=b.probe.uia.iuia.ControlViewWalker.GetParentElement
        def cycle(node):
            return b.Node('saveAs') if isinstance(getattr(b.probe,'_diagnostic_sink',None),dict) else parent(node)
        b.probe.uia.iuia.ControlViewWalker.GetParentElement=cycle
        with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
        action=r['nativeMenuActions'][0];diag=action['uiaInterop']['failureContext']
        self.assertEqual((diag['pointStatus'],diag['parentQueries'],len(diag['nodes'])),(6,8,8))
        self.assertEqual(len(action['pointers']),1);self.assertEqual(action['keys'],[])
        self.assertLessEqual(len(__import__('json').dumps(action).encode()),m.CAP)

    def test_missing_malformed_or_throwing_hresult_never_becomes_observed_zero(self):
        for value in (None,True,1.5,2**40,'getter-error'):
            with self.subTest(value=value):
                m,a,p,r,c,b=self.real_chrome_fixture()
                class COMError(Exception):
                    @property
                    def hresult(self):
                        if value=='getter-error':raise RuntimeError('synthetic metadata failure')
                        return value
                    def __str__(self):raise AssertionError('Exception text must not be inspected')
                primary=COMError()
                def root(hwnd):raise primary
                b.probe.uia.iuia.ElementFromHandle=root
                with self.assertRaises(COMError) as caught:m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                self.assertIs(caught.exception,primary);call=r['nativeMenuActions'][0]['uiaInterop']['primaryFailureCall']
                self.assertFalse(call['hresultObserved']);self.assertFalse('hresult' in call)

    def test_real_chrome_empty_runtime_ids_require_actual_differential_identity(self):
        m,a,p,r,c,boundary=self.real_chrome_fixture()
        with patch.object(m.time,'sleep',side_effect=c.pause):
            value=m.click_native_menu_action(a,p,11,r,'save',probe=boundary.probe,clock=c)
        self.assertIs(m.require_native_menu_action(value,77,11,'save'),value)
        self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0]=='click'],
            [('click','file'),('click','save')])
        self.assertIn(('close',9),boundary.native.calls)

    def test_real_chrome_rejects_missing_or_nondifferential_identity_before_file_input(self):
        for mode in ('alwaysTrue','NoneCompare','invalidCompare','freshFalse','foreignPID','generation','TopEditmissing',
                     'metadatawrong','metadataNone','NoneRuntime','malformedRuntime','late','pointFalse'):
            with self.subTest(mode=mode):
                m,a,p,r,c,boundary=self.real_chrome_fixture(mode)
                with patch.object(m.time,'sleep',side_effect=c.pause),self.assertRaises((AssertionError,TypeError)):
                    m.click_native_menu_action(a,p,11,r,'save',probe=boundary.probe,clock=c)
                self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0] in ('click','key')],[])
                self.assertIn(('close',9),boundary.native.calls)
                self.assertTrue(r['nativeMenuActions'][-1]['engineHandleReleased'])

    def test_real_chrome_normal_win32_zero_nonzero_comparison_results_are_accepted(self):
        m,a,p,r,c,boundary=self.real_chrome_fixture('integerCompare')
        with patch.object(m.time,'sleep',side_effect=c.pause):
            value=m.click_native_menu_action(a,p,11,r,'save',probe=boundary.probe,clock=c)
        self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0]=='click'],
            [('click','file'),('click','save')])
        self.assertIs(m.require_native_menu_action(value,77,11,'save'),value)

    def test_real_chrome_nested_new_accepts_only_the_previously_bound_new_ancestor(self):
        for mode in ('nestedNew','unboundIntermediate'):
            with self.subTest(mode=mode):
                m,a,p,r,c,boundary=self.real_chrome_fixture(mode)
                with patch.object(m.time,'sleep',side_effect=c.pause):
                    if mode=='nestedNew':
                        value=m.click_native_menu_action(a,p,11,r,'new-writer',probe=boundary.probe,clock=c)
                        self.assertIs(m.require_native_menu_action(value,77,11,'new-writer'),value)
                    else:
                        with self.assertRaises(AssertionError):
                            m.click_native_menu_action(a,p,11,r,'new-writer',probe=boundary.probe,clock=c)
                expected=[('click','file'),('click','new')]+([('click','new-writer')] if mode=='nestedNew' else [])
                self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0]=='click'],expected)
                self.assertIn(('close',9),boundary.native.calls)

    def test_real_chrome_disabled_commands_use_save_only_as_escape_recipient(self):
        for gesture in ('disabled-saveAll','disabled-saveCopy'):
            with self.subTest(gesture=gesture):
                m,a,p,r,c,boundary=self.real_chrome_fixture()
                with patch.object(m.time,'sleep',side_effect=c.pause):
                    value=m.inspect_native_menu(a,p,11,r,gesture,probe=boundary.probe,clock=c)
                self.assertIs(value['disabledObserved'],True);self.assertIs(value['focusReturned'],True)
                self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0] in ('click','key')],
                    [('click','file'),('key','ESCAPE')])
                self.assertIs(m.require_native_menu_action(value,77,11),value)

    def test_real_chrome_wrong_target_stale_file_or_ambiguous_focus_stops_after_file(self):
        for mode in ('wrongtarget','stale','focusbothTRUE'):
            with self.subTest(mode=mode):
                m,a,p,r,c,boundary=self.real_chrome_fixture(mode)
                with patch.object(m.time,'sleep',side_effect=c.pause),self.assertRaises(AssertionError):
                    if mode=='focusbothTRUE':m.inspect_native_menu(a,p,11,r,'open-escape',probe=boundary.probe,clock=c)
                    else:m.click_native_menu_action(a,p,11,r,'save',probe=boundary.probe,clock=c)
                self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0] in ('click','key')],
                    [('click','file')])
                self.assertIn(('close',9),boundary.native.calls)

    def test_real_chrome_each_command_uses_its_own_fresh_empty_runtime_target(self):
        for command in ('open','saveAs','new-hwp','home','close'):
            with self.subTest(command=command):
                m,a,p,r,c,boundary=self.real_chrome_fixture('listRuntime')
                with patch.object(m.time,'sleep',side_effect=c.pause):
                    value=m.click_native_menu_action(a,p,11,r,command,probe=boundary.probe,clock=c)
                self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0]=='click'],
                    [('click','file'),('click',command)])
                self.assertIs(m.require_native_menu_action(value,77,11,command),value)

    def test_real_chrome_keyboard_uses_actual_focused_ancestry_and_production_admission(self):
        m,a,p,r,c,boundary=self.real_chrome_fixture()
        self.assertIs(boundary.probe.keyboard.__func__,m.NativeMenuProbe.keyboard)
        with patch.object(m.time,'sleep',side_effect=c.pause):
            value=m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=boundary.probe,clock=c)
        self.assertEqual([call for call in boundary.native.calls if isinstance(call,tuple) and call[0]=='key'],
            [('key','ALT_F'),('key','DOWN'),('key','ESCAPE')])
        self.assertIs(m.require_native_menu_action(value,77,11),value)

    def test_real_chrome_pointer_replay_rejects_missing_cross_scope_or_alias_proof(self):
        m,a,p,r,c,boundary=self.real_chrome_fixture()
        with patch.object(m.time,'sleep',side_effect=c.pause):
            original=m.click_native_menu_action(a,p,11,r,'save',probe=boundary.probe,clock=c)
        comparison_count=len(boundary.compares)
        for reason in ('missing-proof','scope','positive','alias','role','missing-runtime-observation',
                       'missing-hit-proof','hit-scope','hit-replaced','hit-alias'):
            with self.subTest(reason=reason):
                value=copy.deepcopy(original);snapshot=value['pointers'][0]['snapshots'][0]
                hit=value['pointers'][0]['hits'][0]
                if reason=='missing-proof':snapshot.pop('identityProof')
                elif reason=='scope':snapshot['identityProof']['scope']['officeCreationTime']+=1
                elif reason=='positive':snapshot['identityProof']['positive']['file']=False
                elif reason=='alias':snapshot['identityProof']['negative'][0][2]=True
                elif reason=='role':snapshot['control']['identity']['role']='bar'
                elif reason=='missing-runtime-observation':snapshot['control'].pop('runtimeObservation')
                elif reason=='missing-hit-proof':hit.pop('identityProof')
                elif reason=='hit-scope':hit['identityProof']['scope']['startedAt']+=.01
                elif reason=='hit-replaced':hit['identityProof']['hitEqualsRetained']=False
                else:hit['identityProof']['differentFrom']['bar']=True
                with self.assertRaises((AssertionError,KeyError)):m.require_native_menu_action(value,77,11,'save')
        self.assertEqual(len(boundary.compares),comparison_count,'Replay must not perform live UIA calls')

    def test_real_chrome_keyboard_replay_rejects_missing_admission_or_ambiguous_focus(self):
        m,a,p,r,c,boundary=self.real_chrome_fixture()
        with patch.object(m.time,'sleep',side_effect=c.pause):
            original=m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=boundary.probe,clock=c)
        comparison_count=len(boundary.compares)
        for reason in ('missing-admission','admission-scope','positive','alias','focus-both','focus-role','focus-path-role','focus-scope'):
            with self.subTest(reason=reason):
                value=copy.deepcopy(original);key=value['keys'][1]
                if reason=='missing-admission':key.pop('identityAdmission')
                elif reason=='admission-scope':key['identityAdmission']['scope']['operation']='open-escape'
                elif reason=='positive':key['identityAdmission']['positive']['file']=False
                elif reason=='alias':key['identityAdmission']['negative'][0][2]=True
                elif reason=='focus-both':key['before']['focusIdentity']['barEquals']=True
                elif reason=='focus-role':key['before']['focusIdentity']['role']='bar'
                elif reason=='focus-path-role':key['before']['focusMenuPath'][-1]['identity']['role']='target:save'
                else:key['before']['focusIdentity']['scope']['officeCreationTime']+=1
                with self.assertRaises((AssertionError,KeyError)):m.require_native_menu_action(value,77,11)
        self.assertEqual(len(boundary.compares),comparison_count,'Replay must not perform live UIA calls')
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
    def initial_focus_fixture(self):
        m,a,p,r,c,probe=self.fixture()
        original=probe.editor_snapshot
        def snapshot(binding):
            row=original(binding)
            row.update(nativeReady=1,document=dict(hwnd=11,pid=77,rootHwnd=11,threadId=7,visible=True,enabled=True),
                attachmentWindows={role:dict(hwnd=hwnd,pid=pid,threadId=thread,rootHwnd=11)
                    for role,hwnd,pid,thread in (('document',11,77,7),('parent',55,77,7),('child',56,88,9))},
                attachmentExports=[55,56])
            gui=dict(activeHwnd=11,focusHwnd=57,focusPid=88,focusRootHwnd=11,captureHwnd=0,menuOwnerHwnd=0,flags=0)
            row.update(hostGui=dict(gui,threadId=7),engineGui=dict(gui,threadId=9))
            return row
        probe.editor_snapshot=snapshot
        return m,a,p,r,c,probe
    def host_focus(self,row):
        row.update(focusPid=77,focusUnderOriginalChild=False)
        for name in ('hostGui','engineGui'):row[name].update(focusHwnd=11,focusPid=77)
        return row
    def test_initial_owned_host_focus_settles_without_input_and_keeps_original_deadline(self):
        m,a,p,r,c,probe=self.initial_focus_fixture();original=probe.editor_snapshot;reads=[]
        def snapshot(binding):
            reads.append(c());row=original(binding)
            if len(reads)<=2:return self.host_focus(row)
            return row
        probe.editor_snapshot=snapshot
        with patch.object(m.time,'sleep',side_effect=c.pause):
            value=m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=probe,clock=c)
        first=value['editorObservations'][0]
        self.assertEqual(first['sampleCount'],3)
        self.assertEqual(first['firstNumbers']['engineGui']['focusHwnd'],11)
        self.assertEqual(first['numbers']['engineGui']['focusHwnd'],57)
        self.assertEqual(first['firstNumbers']['editor'].get('nativeReady'),1)
        self.assertEqual(first['firstNumbers']['editor'].get('documentVisible'),1)
        self.assertEqual(first['firstNumbers']['editor'].get('documentEnabled'),1)
        self.assertEqual([row['phaseCode'] for row in value['editorObservations']],[1,2,3])
        self.assertEqual(value['deadline'],6.);self.assertLess(value['finishedAt'],6.)
        self.assertEqual([call for call in probe.calls if isinstance(call,tuple) and call[0] in ('click','key')],
            [('key','ALT_F'),('key','DOWN'),('key','ESCAPE')])
        self.assertIs(m.require_native_menu_action(value,77,11),value)
    def test_persistent_initial_host_focus_expires_with_bounded_numeric_evidence_and_no_input(self):
        m,a,p,r,c,probe=self.initial_focus_fixture();original=probe.editor_snapshot
        probe.editor_snapshot=lambda binding:self.host_focus(original(binding))
        with patch.object(m.time,'sleep',side_effect=c.pause),self.assertRaises(AssertionError):
            m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        value=r['nativeMenuActions'][-1];first,=value['editorObservations']
        self.assertEqual(value['deadline'],6.);self.assertGreaterEqual(c(),6.)
        self.assertGreater(first['sampleCount'],1);self.assertLessEqual(first['sampleCount'],101)
        self.numeric_leaves(first['firstNumbers']);self.numeric_leaves(first['numbers'])
        self.assertLess(len(__import__('json').dumps(value).encode()),128*1024)
        self.assertEqual(value['pointers'],[]);self.assertEqual(value['keys'],[])
        self.assertTrue(value['engineHandleReleased']);self.assertFalse(value['success'])
    def test_initial_settle_rejects_foreign_unknown_modal_and_mismatched_focus_immediately(self):
        changes=(lambda row:row['hostGui'].update(focusHwnd=55),
            lambda row:row['hostGui'].update(focusHwnd=0),lambda row:row['engineGui'].update(focusPid=999),
            lambda row:row['engineGui'].update(flags=4),lambda row:row['hostGui'].update(captureHwnd=55),
            lambda row:row['engineGui'].update(menuOwnerHwnd=56),lambda row:row['document'].update(enabled=False),
            lambda row:row['document'].update(visible=False),lambda row:row.update(nativeReady=0),
            lambda row:row.pop('hostGui'),lambda row:row.update(attachmentValid=False),
            lambda row:row.update(attachmentExports=[55,57]),lambda row:row['foreground'].update(hwnd=99),
            lambda row:row['engineGui'].update(threadId=7))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                m,a,p,r,c,probe=self.initial_focus_fixture();original=probe.editor_snapshot
                def snapshot(binding):
                    row=self.host_focus(original(binding));change(row);return row
                probe.editor_snapshot=snapshot
                with patch.object(m.time,'sleep',side_effect=c.pause),self.assertRaises(AssertionError):
                    m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
                self.assertEqual(c(),1.)
                self.assertEqual(r['nativeMenuActions'][-1]['pointers'],[])
                self.assertEqual(r['nativeMenuActions'][-1]['keys'],[])
    def test_initial_settle_rechecks_retained_generation_and_attachment_before_each_read(self):
        for changed in ('shell','engine','attachment','thread'):
            with self.subTest(changed=changed):
                m,a,p,r,c,probe=self.initial_focus_fixture();original=probe.editor_snapshot;reads=[]
                def snapshot(binding):
                    reads.append(1);row=self.host_focus(original(binding))
                    if changed=='thread' and len(reads)>1:row['attachmentWindows']['child']['threadId']=10
                    return row
                probe.editor_snapshot=snapshot
                def pause(seconds):
                    c.pause(seconds)
                    if changed=='shell':probe.shell['creationTime']=101
                    if changed=='engine':probe.engine['creationTime']=201
                    if changed=='attachment':a.attachment=lambda hwnd:(55,57,88)
                with patch.object(m.time,'sleep',side_effect=pause),self.assertRaises(AssertionError):
                    m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
                self.assertLessEqual(len(reads),2)
                self.assertEqual(r['nativeMenuActions'][-1]['pointers'],[])
                self.assertEqual(r['nativeMenuActions'][-1]['keys'],[])
    def test_later_editor_phases_never_settle_host_focus(self):
        for phase in (2,3):
            with self.subTest(phase=phase):
                m,a,p,r,c,probe=self.initial_focus_fixture();original=probe.editor_snapshot;reads=[];pauses=[]
                def snapshot(binding):
                    reads.append(1);row=original(binding)
                    return self.host_focus(row) if len(reads)==phase else row
                probe.editor_snapshot=snapshot
                with patch.object(m.time,'sleep',side_effect=lambda seconds:pauses.append(seconds)),self.assertRaises(AssertionError):
                    m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=probe,clock=c)
                self.assertEqual(pauses,[])
                self.assertEqual(r['nativeMenuActions'][-1]['observationPhase'],phase)
    def test_initial_settle_has_a_finite_query_count_even_if_the_clock_does_not_advance(self):
        m,a,p,r,c,probe=self.initial_focus_fixture();original=probe.editor_snapshot
        probe.editor_snapshot=lambda binding:self.host_focus(original(binding))
        with patch.object(m.time,'sleep',return_value=None),self.assertRaises(AssertionError):
            m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        first,=r['nativeMenuActions'][-1]['editorObservations']
        self.assertEqual(first['sampleCount'],101)
        self.assertEqual(r['nativeMenuActions'][-1]['pointers'],[])
        self.assertEqual(r['nativeMenuActions'][-1]['keys'],[])
    def real_editor_probe(self,m,clock,*,host_focus=0,engine_focus=57):
        probe=object.__new__(m.NativeMenuProbe);queries=[]
        pids={11:77,55:77,56:88,57:88};threads={11:7,55:7,56:9,57:9}
        def identity(hwnd,pointer):
            if pointer is not None:pointer._obj.value=pids.get(hwnd,0)
            return threads.get(hwnd,0)
        def gui(thread,pointer):
            queries.append(thread);state=pointer._obj
            state.active=11 if thread==7 else 56
            state.focus=host_focus if thread==7 else engine_focus
            state.capture=state.menuOwner=state.flags=0
            return 1
        probe.clock=clock;probe.deadline=clock()+5;probe.provider_client=None;probe.interop={}
        probe.user=NS(IsWindow=lambda hwnd:hwnd in pids,GetWindowThreadProcessId=identity,
            GetAncestor=lambda hwnd,kind:11 if hwnd in pids else 0,
            GetPropW=lambda hwnd,name:55 if name.endswith('ParentHwnd') else 56,
            IsChild=lambda parent,child:(parent,child) in ((11,55),(55,56),(56,57)),GetGUIThreadInfo=gui)
        probe.foreground=lambda:11
        probe.window_snapshot=lambda hwnd:dict(hwnd=11,pid=77,threadId=7,rootHwnd=11,
            forbiddenTitle='SYNTHETIC PRIVATE body must not be observed')
        return probe,queries
    def numeric_leaves(self,value):
        if isinstance(value,dict):
            for child in value.values():self.numeric_leaves(child)
        elif isinstance(value,list):
            for child in value:self.numeric_leaves(child)
        else:self.assertIs(type(value),int)
    def test_real_editor_keeps_original_host_and_engine_gui_observations_without_repair(self):
        m,a,p,r,c,stub=self.fixture();probe,queries=self.real_editor_probe(m,c)
        binding=dict(document=11,parent=55,child=56,officePid=88)
        default=probe.attachment_snapshot(binding)
        self.assertEqual(set(default),{'binding','windows','exported','valid','focusUnderOriginalChild'})
        self.assertEqual(queries,[7]);queries.clear()
        value=probe.editor_snapshot(binding)
        self.assertEqual(queries,[7,9], 'Observe each existing GUI thread exactly once')
        self.assertEqual((value['hostGui']['focusHwnd'],value['engineGui']['focusHwnd']),(0,57))
        self.assertIs(value['focusUnderOriginalChild'],False)
        self.assertEqual(value['focusPid'],88)
        self.assertEqual(value['attachmentWindows'],default['windows']);self.assertEqual(value['attachmentExports'],[55,56])
        with self.assertRaises(AssertionError):m._editor(value,binding,77)
        numbers=m._editor_numbers(value);self.numeric_leaves(numbers)
        self.assertNotIn('SYNTHETIC PRIVATE',str(numbers))
    def test_actual_editor_snapshot_settles_agreed_host_focus_without_creating_an_input_path(self):
        m,a,p,r,c,stub=self.fixture();probe,queries=self.real_editor_probe(m,c,host_focus=11,engine_focus=11)
        original_gui=probe.user.GetGUIThreadInfo
        def gui(thread,pointer):
            result=original_gui(thread,pointer)
            if c()>1:pointer._obj.focus=57
            return result
        probe.user.GetGUIThreadInfo=gui
        probe.user.GetPropW=lambda hwnd,name:1 if name==m.READY_PROPERTY else 55 if name.endswith('ParentHwnd') else 56
        probe.window_snapshot=lambda hwnd:dict(hwnd=11,pid=77,threadId=7,rootHwnd=11,visible=True,enabled=True)
        for name in ('process_snapshot','open_engine','engine_snapshot','close_engine','enter_dpi','restore_dpi'):
            setattr(probe,name,getattr(stub,name))
        reached=AssertionError('Synthetic fixed menu boundary')
        def menu_boundary(*args):raise reached
        probe.snapshot=menu_boundary
        with patch.object(m.time,'sleep',side_effect=c.pause),self.assertRaises(AssertionError) as caught:
            m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        self.assertIs(caught.exception,reached)
        first,=r['nativeMenuActions'][-1]['editorObservations']
        self.assertEqual((first['stageCode'],first['sampleCount']),(12,2))
        self.assertEqual(queries,[7,9,7,9])
        self.assertEqual(r['nativeMenuActions'][-1]['pointers'],[])
        self.assertEqual(r['nativeMenuActions'][-1]['keys'],[])
    def test_initial_real_editor_guard_records_stage_and_numeric_site_before_any_input(self):
        import numeric_notice
        m,a,p,r,c,stub=self.fixture();probe,queries=self.real_editor_probe(m,c)
        for name in ('process_snapshot','open_engine','engine_snapshot','close_engine','enter_dpi','restore_dpi'):
            setattr(probe,name,getattr(stub,name))
        try:m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        except AssertionError as caught:expected_failure=numeric_notice.capture_failure_code(caught)
        else:self.fail('The unchanged mixed-thread focus guard must reject the host focus')
        value=r['nativeMenuActions'][-1]
        self.assertEqual((value['observationStage'],value['observationPhase']),(11,1))
        observation,=value['editorObservations']
        self.assertEqual((observation['stageCode'],observation['phaseCode']),(11,1))
        self.assertEqual(observation['numbers']['hostGui']['focusHwnd'],0)
        self.assertEqual(observation['numbers']['engineGui']['focusHwnd'],57)
        self.numeric_leaves(observation['numbers']);self.assertEqual(queries,[7,9])
        self.assertEqual(value['pointers'],[]);self.assertEqual(value['keys'],[])
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
        self.assertEqual(value['numericFailure'],expected_failure)
        self.assertEqual(value['numericFailure']['fileCode'],numeric_notice.SOURCE_FILES['owned_native_menu.py'])
        self.assertGreater(value['numericFailure']['line'],0)
        self.assertNotIn('SYNTHETIC PRIVATE',str(value))
    def test_first_file_validation_failure_retains_original_snapshot_before_pointer_creation(self):
        import numeric_notice
        m,a,p,r,c,probe=self.fixture();probe.bad='foreign'
        try:m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        except AssertionError as caught:expected_failure=numeric_notice.capture_failure_code(caught)
        else:self.fail('The original File recipient guard must reject the foreign PID')
        value=r['nativeMenuActions'][-1];observation=value['menuObservation']
        self.assertEqual((value['observationStage'],observation['stageCode']),(22,22))
        self.assertEqual(observation['snapshot']['control']['pid'],999)
        self.assertEqual(observation['targetCode'],1)
        self.assertEqual(value['pointers'],[]);self.assertEqual(value['keys'],[])
        self.assertFalse(any(isinstance(row,tuple) and row[0] in ('click','key') for row in probe.calls))
        self.assertEqual(value['editorObservations'][0]['stageCode'],12)
        self.assertEqual(value['numericFailure'],expected_failure)
        self.assertEqual((value['numericFailure']['exceptionCode'],value['numericFailure']['fileCode']),(1,38))
        self.assertGreater(value['numericFailure']['line'],0)
        self.assertTrue(value['engineHandleReleased'])
    def test_initial_before_alt_f_and_final_editor_phases_preserve_existing_inputs(self):
        for fail_phase in (0,2,3):
            with self.subTest(fail_phase=fail_phase):
                m,a,p,r,c,probe=self.fixture();original=probe.editor_snapshot;seen=[]
                def snapshot(binding):
                    value=original(binding);seen.append(1)
                    if len(seen)==fail_phase:value['focusPid']=999
                    return value
                probe.editor_snapshot=snapshot
                if fail_phase:
                    with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=probe,clock=c)
                    value=r['nativeMenuActions'][-1]
                    self.assertEqual((value['observationStage'],value['observationPhase']),(11,fail_phase))
                else:
                    value=m.inspect_native_menu(a,p,11,r,'keyboard-escape',probe=probe,clock=c)
                    self.assertEqual([row['stageCode'] for row in value['editorObservations']],[12,12,12])
                self.assertEqual([row['phaseCode'] for row in value['editorObservations']],list(range(1,len(seen)+1)))
                keys=[row for row in probe.calls if isinstance(row,tuple) and row[0]=='key']
                self.assertEqual(keys,[] if fail_phase==2 else [('key','ALT_F'),('key','DOWN'),('key','ESCAPE')])
                self.assertFalse(any(isinstance(row,tuple) and row[0]=='click' for row in probe.calls))
                self.assertEqual(value['deadline'],6.)
                for row in value['editorObservations']:self.numeric_leaves(row['numbers'])
    def test_failure_diagnostics_cannot_replace_the_original_primary(self):
        import numeric_notice
        m,a,p,r,c,probe=self.fixture();primary=AssertionError('SYNTHETIC PRIVATE primary body')
        def snapshot(binding):raise primary
        probe.editor_snapshot=snapshot
        with patch.object(numeric_notice,'capture_failure_code',side_effect=RuntimeError('SYNTHETIC PRIVATE diagnostics')):
            with self.assertRaises(AssertionError) as raised:m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        self.assertIs(raised.exception,primary);value=r['nativeMenuActions'][-1]
        self.assertEqual(value['numericFailureCaptureFailed'],1)
        self.assertEqual((value['observationStage'],value['observationPhase']),(10,1))
        self.assertEqual(value['pointers'],[]);self.assertEqual(value['keys'],[])
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
        self.assertNotIn('SYNTHETIC PRIVATE',str(value))
        m,a,p,r,c,probe=self.fixture();probe.bad='editor-foreign';captured=[]
        def diagnostic_error(primary):
            captured.append(primary);raise RuntimeError('SYNTHETIC PRIVATE numeric diagnostic')
        with patch.object(m,'_editor_numbers',side_effect=ValueError('SYNTHETIC PRIVATE projection')), \
             patch.object(numeric_notice,'capture_failure_code',side_effect=diagnostic_error):
            with self.assertRaises(AssertionError) as raised:m.inspect_native_menu(a,p,11,r,'open-escape',probe=probe,clock=c)
        self.assertIs(raised.exception,captured[0]);value=r['nativeMenuActions'][-1]
        self.assertEqual(value['editorObservations'][0]['numbersCaptureFailed'],1)
        self.assertEqual(value['numericFailureCaptureFailed'],1)
        self.assertEqual((value['observationStage'],value['observationPhase']),(11,1))
        self.assertEqual(value['pointers'],[]);self.assertEqual(value['keys'],[])
        self.assertNotIn('SYNTHETIC PRIVATE',str(value))
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

    def test_hwp_launcher_chrome_is_distinct_from_office_home_and_new_document(self):
        m=self.feature();probe=object.__new__(m.NativeMenuProbe)
        probe._call=lambda function,*args:function(*args)
        probe.uia=NS(tree_scope={'descendants':4},build_condition=lambda **kwargs:kwargs)
        def root(labels):
            elements=[NS(CurrentControlType=50011,CurrentName=label,CurrentIsOffscreen=False) for label in labels]
            return NS(FindAll=lambda *args:NS(Length=len(elements),GetElement=lambda index:elements[index]))
        menu=root(['OpenGeul 한글 시작','OpenGeul 시작 화면'])
        self.assertEqual(probe._find(menu,'new-hwp').CurrentName,'OpenGeul 한글 시작')
        self.assertEqual(probe._find(menu,'home').CurrentName,'OpenGeul 시작 화면')
        for label in ('새 HWP 문서','OpenGeul 시작 화면','새 문서'):
            with self.subTest(label=label),self.assertRaises(m.NativeMenuPending):probe._find(root([label]),'new-hwp')
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


def canonical_action_fixture(owner,*,operation='save',gesture=False):
    """Full owned action with synthetic v2 points, never actual Windows proof."""
    import test_native_menu_point_proof as receipts
    policy=OwnedNativeMenuTests(methodName='runTest');owner.addCleanup(policy.doCleanups)
    module,api,process,record,clock,boundary=policy.real_chrome_fixture()
    call=module.inspect_native_menu if gesture else module.click_native_menu_action
    value=call(api,process,11,record,operation,probe=boundary.probe,clock=clock)
    sequence=0
    def local(snapshot,target,hit=None):
        nonlocal sequence
        sequence+=1
        return receipts.canonical_provider_point(snapshot,target=target,hit=hit,scope_id=sequence)
    for item in value['pointers']:
        target=item['target']
        if target in ('file','outside'):continue
        for index,hit in enumerate(item['hits']):
            item['hits'][index]=local(item['snapshots'][index+1],target,hit)
        for snapshot in item['snapshots']:
            snapshot['targetPointProof']=local(snapshot,target)
    for key in value['keys']:
        snapshot=key['before'];identity=snapshot.get('control',{}).get('identity')
        if identity is not None and identity['role'].startswith('target:'):
            target=identity['role'][len('target:'):];snapshot['targetPointProof']=local(snapshot,target)
    for target,snapshot in value.get('coreSnapshots',{}).items():
        if target!='file':snapshot['targetPointProof']=local(snapshot,target)
    if 'disabledSnapshot' in value:
        target=operation[len('disabled-'):]
        value['disabledSnapshot']['targetPointProof']=local(value['disabledSnapshot'],target)
    module.require_native_menu_action(value,77,11,operation)
    return module,value


class NativeMenuPointModeTests(unittest.TestCase):
    def owner(self):
        owner=OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups);return owner

    def test_constructor_mode_two_requires_explicit_opt_in_before_any_provider_work(self):
        import inspect
        owner=self.owner();m,a,p,r,c,b,calls,(user,kernel,dwm),context=owner.lazy_provider_boundary()
        self.assertIn('native_point_profile_version',inspect.signature(m.NativeMenuProbe).parameters)
        with context:
            with self.assertRaises(AssertionError):
                m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm,native_point_profile_version=2)
            probe=m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm,
                native_point_profile=True,native_point_profile_version=2)
            self.assertEqual(probe._native_point_profile_version,2);self.assertEqual(calls,[])
            probe.close_provider()

    def test_unknown_or_noninteger_constructor_modes_cannot_initialize_provider(self):
        owner=self.owner();m,a,p,r,c,b,calls,(user,kernel,dwm),context=owner.lazy_provider_boundary()
        import inspect
        self.assertIn('native_point_profile_version',inspect.signature(m.NativeMenuProbe).parameters)
        with context:
            for version in (0,3,True,False,'2',None):
                with self.subTest(version=version),self.assertRaises(AssertionError):
                    m.NativeMenuProbe(c()+5,c,user=user,kernel=kernel,dwm=dwm,
                        native_point_profile=True,native_point_profile_version=version)
            self.assertEqual(calls,[])

    def test_invalid_process_profile_stops_before_any_pointer_or_keyboard_input(self):
        for version in (0,3,True,'2',None):
            with self.subTest(version=version):
                owner=self.owner();m,a,p,r,c,b=owner.real_chrome_fixture()
                p.opengeul_native_menu_point_profile=True;p.opengeul_native_menu_point_profile_version=version
                with self.assertRaises(AssertionError):m.inspect_native_menu(a,p,11,r,'open-escape',probe=b.probe,clock=c)
                self.assertEqual(r['nativeMenuActions'][-1]['pointers'],[])
                self.assertEqual(r['nativeMenuActions'][-1]['keys'],[])


class SourceSelectedMenuCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_native_menu_source_selection import SourceMenuSelectionTests
        cls.selected_fixture=SourceMenuSelectionTests(methodName='test_prepares_actual_bare_gate_context_and_freezes_contexts')
        cls.selected_fixture.setUp();cls.addClassCleanup(cls.selected_fixture.doCleanups)
        cls.prepared=cls.selected_fixture.prepared();cls.selection=cls.selected_fixture.selected(cls.prepared)

    def selected_case(self):
        owner=OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,probe=owner.fixture()
        root=self.prepared.admission.suite_root
        process.opengeul_suite_root=root;process.args=[str(root/'OpenGeul.Office.exe')]
        process.opengeul_source_menu_selection=self.selection
        probe.source_selection=self.selection;probe._native_point_profile=True;probe._native_point_profile_version=4
        probe._native_identity_diagnostic=0
        probe.shell['image']=str(root/'OpenGeul.Office.exe')
        probe.engine.update(image=str(root/'Office/program/soffice.bin'),handleValue=9)
        return module,api,process,record,clock,probe

    def test_source_selected_core_has_explicit_authority_and_generation_seams(self):
        import inspect
        owner=OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,*_=owner.real_chrome_fixture()
        self.assertIn('source_selection',inspect.signature(module.NativeMenuProbe).parameters)
        self.assertIn('source_admission',inspect.signature(module.require_native_menu_action).parameters)
        for name in ('require_source_qualified_native_menu_action','_source_admission_summary','_bind_source_generation'):
            self.assertTrue(callable(getattr(module,name,None)),name)

    def test_selected_action_rechecks_once_and_binds_actual_generation_before_input(self):
        import native_menu_source_selection as selected
        module,api,process,record,clock,probe=self.selected_case()
        with patch.object(selected.time,'monotonic',clock),patch.object(selected,'selected_native_menu_probe',wraps=selected.selected_native_menu_probe) as entry:
            action=module.click_native_menu_action(api,process,11,record,'save',probe=probe,clock=clock)
        self.assertEqual(entry.call_count,1)
        self.assertIn('sourceMenu',action)
        self.assertEqual(action['sourceMenu']['admission'],module._source_admission_summary(self.prepared.admission))
        self.assertEqual(action['sourceMenu']['generation'],dict(document=11,parent=55,child=56,officePid=88,
            shellPid=77,shellCreationTime=100,shellHandleValue=8,engineCreationTime=200,engineHandleValue=9))
        self.assertIs(module.require_native_menu_action(action,77,11,'save',source_admission=self.prepared.admission),action)
        with self.assertRaises(AssertionError):module.require_native_menu_action(action,77,11,'save')
        with self.assertRaises(ValueError):module.require_native_menu_action(action,77,11,'save',source_admission=action['sourceMenu']['admission'])

    def test_selected_generation_or_supplied_context_mismatch_cannot_send_input(self):
        import native_menu_source_selection as selected
        for mismatch in ('probe','suite','handle'):
            with self.subTest(mismatch=mismatch):
                module,api,process,record,clock,probe=self.selected_case()
                if mismatch=='probe':probe.source_selection=None
                elif mismatch=='suite':probe.shell['image']=str(process.opengeul_evidence_output/'OpenGeul.Office.exe')
                else:probe.engine['handleValue']=10
                with patch.object(selected.time,'monotonic',clock),self.assertRaises((AssertionError,ValueError)):
                    module.click_native_menu_action(api,process,11,record,'save',probe=probe,clock=clock)
                self.assertFalse(any(row[0]=='click' for row in probe.calls if type(row) is tuple))

    def test_native_view_checks_the_actual_selection_before_historical_origin_replay(self):
        import native_menu_source_selection as selected
        module,api,process,record,clock,probe=self.selected_case();record['module']='writer'
        with patch.object(selected.time,'monotonic',clock):
            module.click_native_menu_action(api,process,11,record,'printPreview',probe=probe,clock=clock)
        outcome=None
        with patch.object(selected,'selected_native_menu_probe',side_effect=ValueError('Synthetic selected view entry')) as entry:
            try:module.observe_native_view(api,process,11,record,module='writer',preview=True,probe=probe,clock=clock)
            except BaseException as exc:outcome=type(exc)
        self.assertIs(outcome,ValueError)
        self.assertEqual(entry.call_count,1)

    def test_source_admission_failure_starts_no_failure_provider_queries(self):
        import native_menu_source_selection as selected
        module,api,process,record,clock,probe=self.selected_case();queries=[]
        probe.capture_primary_failure=lambda _error:queries.append(1)
        probe.observe_failure_context=lambda _binding:queries.append(2)
        with patch.object(selected,'selected_native_menu_probe',side_effect=ValueError('Synthetic rejected source')):
            with self.assertRaises(ValueError):
                module.click_native_menu_action(api,process,11,record,'save',probe=probe,clock=clock)
        self.assertEqual(queries,[])
        self.assertEqual(record['nativeMenuActions'][-1]['pointers'],[])
        self.assertEqual(record['nativeMenuActions'][-1]['keys'],[])

    def test_global_source_action_rejects_untyped_header_or_unjoined_use(self):
        import native_menu_source_selection as selected
        module,api,process,record,clock,probe=self.selected_case()
        with patch.object(selected.time,'monotonic',clock):
            action=module.click_native_menu_action(api,process,11,record,'save',probe=probe,clock=clock)
        changes=(lambda p:p['sourceMenu']['generation'].update(document=True),
            lambda p:p['sourceMenu']['generation'].update(document=11.),
            lambda p:p.update(startedAt=True),lambda p:p.update(sourcePointSnapshots=()),
            lambda p:p['pointUses'].append(dict(sourceScopeId=1,at=p['startedAt'],useCode=1)))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                changed=copy.deepcopy(action);change(changed)
                with self.assertRaises(AssertionError):
                    module.require_native_menu_action(changed,77,11,'save',source_admission=self.prepared.admission)
