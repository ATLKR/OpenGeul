"""Measured engine-owned menus; the WinForms menu proof remains separate.

Only fixed chrome labels are matched. Unknown labels and document contents are
not retained. Native insertion counts never prove command delivery or storage.
"""
from __future__ import annotations
import copy
import ctypes as C
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import time
from types import SimpleNamespace

from owned_control_actions import CAP, GuiThreadInfo, NativeControlProbe, _original_attachment
from suite_window_activation import NativeActivationProbe

READY_PROPERTY='OpenGeul.Office.NativeMenuReady'
LABELS={'file':('파일','File'),'save':('저장','Save'),
    'saveAs':('다른 이름으로 저장…','Save As…'),'open':('열기…','Open…'),
    'close':('닫기','Close'),'new':('새로 만들기','새 문서','New'),
    'new-writer':('텍스트 문서','Text Document'),'new-calc':('스프레드시트','Spreadsheet'),
    'new-impress':('프레젠테이션','Presentation'),'new-draw':('그리기','Drawing'),
    'new-math':('수식','Formula'),'new-base':('데이터베이스','Database'),
    'new-hwp':('새 HWP 문서',),'home':('OpenGeul 시작 화면',),
    'exit':('끝내기','종료','Exit','Quit'),
    'saveAll':('모두 저장','모든 문서 저장','Save All'),
    'saveCopy':('복사본 저장…','복사본 저장','Save a Copy…','Save a Copy')}
COMMANDS=tuple(k for k in LABELS if k not in ('file','new','saveAll','saveCopy'))
GESTURES=('open-escape','open-outside','keyboard-escape','disabled-saveAll','disabled-saveCopy')
KEY_COUNTS={'ALT_F':4,'DOWN':2,'ESCAPE':2}


class NativeMenuPending(AssertionError):pass


def native_menu_active(api,process,document):
    """A routing hint only. A positive result still requires actual UI proof."""
    getter=getattr(api.user,'GetPropW',None)
    return bool(getter is not None and process.poll() is None and getter(document,READY_PROPERTY)==1)


def _int(value):assert type(value) is int and value>0


def _label(value):
    value=value.replace('~','').replace('&','').strip().replace('...','…')
    return re.sub(r'\s*\([A-Za-z]\)(?=…?$)','',value).strip()


def _image(value):
    assert type(value) is str and 0<len(value)<=4096
    path=PureWindowsPath(value) if PureWindowsPath(value).drive else PurePosixPath(value)
    assert path.is_absolute() and '..' not in path.parts
    return path


def _keyboard_recipient(snapshot,binding,shell_pid):
    _validate(snapshot,binding,shell_pid,'save')
    gui=snapshot['gui']
    if _menu_key_owner(gui,snapshot['popup'],binding['child']):return
    chain=snapshot.get('focusMenuPath',[])
    assert snapshot.get('focusMenuElementEquals') is True and 0<len(chain)<=32
    assert all(row['pid']==binding['officePid'] and row['runtimeId'] for row in chain)
    allowed=[snapshot['ancestry'][snapshot[k]]['runtimeId'] for k in ('fileIndex','barIndex')]
    assert chain[-1]['runtimeId'] in allowed and chain[-1]['controlType'] in ('MenuItem','MenuBar'), 'Native menu lacks its keyboard recipient'


def _menu_key_owner(gui,popup,child):
    return bool(popup and (gui['captureHwnd']==popup['hwnd'] or
        gui['menuOwnerHwnd'] in (child,popup['hwnd']) and type(gui.get('flags')) is int and gui['flags']&0x1c))


def _validate(snapshot,binding,shell_pid,target,*,enabled=True):
    assert snapshot['binding']==binding and snapshot['attachmentValid'] is True
    assert snapshot['nativeReady']==1 and snapshot['shellMenuCount']==0, 'Native menu not exclusive and ready'
    doc=snapshot['document'];assert (doc['hwnd'],doc['pid'],doc['rootHwnd'])==(binding['document'],shell_pid,binding['document'])
    _int(doc['threadId'])
    assert doc['visible'] is doc['enabled'] is True
    control=snapshot['control'];chain=snapshot['ancestry']
    assert 3<=len(chain)<=32 and all(r['pid']==binding['officePid'] for r in chain), 'Foreign native menu ancestry'
    assert control['pid']==binding['officePid'] and control['controlType']=='MenuItem'
    assert control['visible'] is True and control['enabled'] is enabled and control['runtimeId']
    assert chain[0]==control and snapshot['fileElementEquals'] is snapshot['peerElementEquals'] is True
    file,bar,peer=(snapshot[k] for k in ('fileIndex','barIndex','peerIndex'))
    assert all(type(i) is int for i in (file,bar,peer)) and 0<=file<bar<peer==len(chain)-1
    assert chain[bar]['controlType']=='MenuBar' and chain[peer]['nativeHwnd']==binding['child']
    assert chain[file]['controlType']=='MenuItem'
    rect=control['rectangle'];assert len(rect)==4 and all(type(x) is int for x in rect) and rect[0]<rect[2] and rect[1]<rect[3]
    popup=snapshot['popup']
    if target!='file':
        assert popup and popup['pid']==binding['officePid'] and popup['hwnd']==popup['rootHwnd']
        assert popup['visible'] is popup['enabled'] is True
        owners=popup['ownerChain'];assert 2<=len(owners)<=16 and owners[0]==popup['hwnd']
        assert owners[-1] in (binding['child'],binding['document']) and len(set(owners))==len(owners), 'Native popup escaped original peer'
    fg=snapshot['foreground'];allowed={binding['document']}
    if popup:allowed.add(popup['hwnd'])
    assert fg['hwnd']==fg['rootHwnd'] and fg['hwnd'] in allowed
    assert fg['pid']==(shell_pid if fg['hwnd']==binding['document'] else binding['officePid'])
    gui=snapshot['gui'];assert gui['threadId']>0 and gui['focusPid']==binding['officePid']
    assert gui['focusRootHwnd'] in allowed and gui['captureOwned'] is gui['menuOwnerOwned'] is True
    return (tuple(control['runtimeId']),control['nativeHwnd'],tuple(rect),
            tuple(chain[file]['runtimeId']),tuple(chain[bar]['runtimeId']),binding['child'],doc['threadId'],gui['threadId'])


def _editor(snapshot,binding,shell_pid):
    assert snapshot['binding']==binding and snapshot['attachmentValid'] is True
    assert snapshot['focusPid']==binding['officePid'] and snapshot['focusRootHwnd']==binding['document']
    assert snapshot['focusUnderOriginalChild'] is True and snapshot['menuClosed'] is True
    assert snapshot['captureHwnd']==snapshot['menuOwnerHwnd']==0, 'Menu did not return original editor focus'
    fg=snapshot['foreground'];assert (fg['hwnd'],fg['rootHwnd'],fg['pid'])==(binding['document'],binding['document'],shell_pid), 'Original editor is not the foreground recipient'


def retain_native_menu_receipt(process,value):
    raw=(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()
    assert len(raw)<=CAP, 'Native menu receipt exceeded finite bound'
    output=Path(process.opengeul_evidence_output);assert output.is_absolute() and output.is_dir()
    assert all(not part.is_symlink() and not getattr(part,'is_junction',lambda:False)() for part in (output,*output.parents))
    name=process.opengeul_evidence_case;assert re.fullmatch('[A-Za-z0-9_-]{1,100}',name)
    seq=getattr(process,'opengeul_native_menu_sequence',0);assert type(seq) is int and 0<=seq<128
    process.opengeul_native_menu_sequence=seq+1
    with (output/(name+'-native-menu-'+format(seq,'03d')+'.json')).open('xb') as stream:stream.write(raw)


def _run(api,process,document,record,operation,*,gesture=False,probe=None,clock=time.monotonic,seconds=5):
    assert operation in (GESTURES if gesture else COMMANDS)
    assert type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=5
    start=clock();deadline=start+seconds
    value=dict(schemaVersion=1,kind='owned-native-menu-action',command=operation,gesture=gesture,
        success=False,deliveryProved=False,documentHwnd=document,shellPid=process.pid,
        startedAt=start,deadline=deadline,pointers=[],keys=[],dpiScope={},engineHandleReleased=False)
    record.setdefault('nativeMenuActions',[]).append(value)
    handle=None;primary=None
    def budget():assert clock()<deadline, 'Original native menu deadline expired'
    def retain():retain_native_menu_receipt(process,value)
    try:
        budget();probe=probe or NativeMenuProbe(deadline,clock)
        assert native_menu_active(api,process,document), 'Native-only document menu is not ready'
        suite=Path(process.opengeul_suite_root).resolve()
        shell=probe.process_snapshot(process)
        assert shell['pid']==process.pid and shell['handleValue']==int(process._handle) and shell['waitResult']==258
        assert Path(shell['image']).resolve()==suite/'OpenGeul.Office.exe';_int(shell['creationTime'])
        parent,child,pid=api.attachment(document)
        binding=dict(document=document,parent=parent,child=child,officePid=pid)
        assert all(type(x) is int and x>0 for x in binding.values()) and pid!=process.pid
        existing,witness=_original_attachment(record,process,document)
        assert existing is None or existing==binding, 'Native menu attachment differs from original'
        from owned_save_menu import home_engine_witness
        home_witness,home_basis=home_engine_witness(record,document,binding)
        assert witness is None or home_witness is None or witness==home_witness
        witness=home_witness or witness
        candidate=probe.open_engine(pid);_int(candidate);handle=candidate;engine=probe.engine_snapshot(handle)
        assert engine['pid']==pid and engine['waitResult']==258 and engine['creationTime']>=shell['creationTime']
        assert Path(engine['image']).resolve()==suite/'Office/program/soffice.bin'
        if witness:assert all(str(engine[k]).casefold()==str(witness[k]).casefold() for k in ('pid','image','creationTime'))
        prior=getattr(process,'opengeul_native_menu_generations',{})
        key=(document,parent,child,pid);identity=(engine['image'],engine['creationTime'])
        assert key not in prior or prior[key]==identity, 'Original native menu engine generation changed'
        assert len(prior)<128 or key in prior;prior[key]=identity;process.opengeul_native_menu_generations=prior
        value.update(binding=binding,originalProcess=shell,originalEngine=engine,engineHandleValue=handle,
            engineAdmissionBasis=home_basis if home_witness else 'existing-retained-witness' if witness else 'first-native-measurement')
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        def continuity():
            budget();assert probe.process_snapshot(process)==shell
            assert probe.engine_snapshot(handle)==engine, 'Original native engine changed during input admission'
            assert api.attachment(document)==(parent,child,pid)
        def observe(target,*,enabled=True):
            while True:
                continuity()
                try:row=probe.snapshot(binding,target)
                except NativeMenuPending:
                    budget();time.sleep(min(.01,max(0,deadline-clock())));continue
                _validate(row,binding,process.pid,target,enabled=enabled);return row
        def pointer(target):
            row=observe(target);anchor=_validate(row,binding,process.pid,target)
            rect=row['control']['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
            item=dict(target=target,chosenPhysicalPoint=point,snapshots=[row],hits=[])
            value['pointers'].append(item)
            def check():
                snap=observe(target);assert _validate(snap,binding,process.pid,target)==anchor
                item['snapshots'].append(snap)
                scope=snap['popup']['hwnd'] if snap['popup'] else document
                hit=probe.point_snapshot(scope,point,probe.current_control);item['hits'].append(hit)
                assert hit['point']==point and hit['pid']==pid and hit['rootHwnd']==scope
                assert hit['withinControl'] is hit['uiaMatches'] is True, 'Native menu point is obstructed'
            check();retain();probe.move(point,item);assert item['pointerReadback']==point
            check();retain();continuity();probe.click(item);budget()
            assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
            assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==2
        def keyboard(shortcut):
            if shortcut=='ALT_F':
                before=observe('file');editor=probe.editor_snapshot(binding);_editor(editor,binding,process.pid)
            else:
                before=observe('save');_keyboard_recipient(before,binding,process.pid);editor=None
            continuity();item=dict(shortcut=shortcut,before=before,editorBefore=editor);value['keys'].append(item);retain()
            probe.keyboard(binding,shortcut,item);budget()
            assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
            assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==KEY_COUNTS[shortcut]
        if gesture:_editor(probe.editor_snapshot(binding),binding,process.pid)
        if operation=='keyboard-escape':
            keyboard('ALT_F');observe('save');keyboard('DOWN');keyboard('ESCAPE')
        else:
            pointer('file')
            if gesture:
                if operation.startswith('disabled-'):
                    target=operation[len('disabled-'):]
                    value.update(disabledSnapshot=observe(target,enabled=False),disabledObserved=True)
                else:observe('save')
                if operation=='open-outside':
                    continuity();hit=probe.outside_snapshot(binding)
                    assert hit['pid']==process.pid and hit['rootHwnd']==document and hit['hitHwnd']==document and hit['hitTest']==2
                    item=dict(target='outside',chosenPhysicalPoint=hit['point'],nativeBefore=hit);value['pointers'].append(item)
                    retain();probe.outside_click(binding,item);budget();assert item['requestedInputs']==item['insertedInputs']==2
                else:keyboard('ESCAPE')
            else:
                if operation.startswith('new-') and operation!='new-hwp':pointer('new')
                pointer(operation)
        if gesture:
            continuity();focus=probe.editor_snapshot(binding);_editor(focus,binding,process.pid)
            value.update(focusReturned=True,focusAfter=focus)
        value['inputVerified']=True;budget()
    except BaseException as exc:
        primary=exc;value['failureType']=type(exc).__name__;raise
    finally:
        errors=[]
        if handle is not None:
            try:value['engineHandleReleased']=probe.close_engine(handle);assert value['engineHandleReleased'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        if value['dpiScope'].get('previousContext') is not None:
            try:probe.restore_dpi(value['dpiScope']);assert value['dpiScope']['restored'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        close_provider=getattr(probe,'close_provider',None)
        if close_provider:
            try:value['providerClientReleased']=close_provider();assert value['providerClientReleased'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        value.update(cleanupErrors=errors,finishedAt=clock())
        value['success']=primary is None and not errors and value.get('inputVerified') is True and value['finishedAt']<deadline
        try:retain()
        except BaseException as exc:
            value['success']=False
            if primary is None:raise
        if primary is None:assert value['success'], 'Native menu cleanup or original deadline failed'
    return value


def click_native_menu_action(api,process,document,record,command,**options):
    return _run(api,process,document,record,command,**options)


def inspect_native_menu(api,process,document,record,gesture,**options):
    return _run(api,process,document,record,gesture,gesture=True,**options)


def require_native_menu_action(value,shell_pid,document,command=None):
    assert type(value) is dict
    assert len(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode())<=CAP
    assert value['kind']=='owned-native-menu-action' and value['schemaVersion']==1
    assert value['success'] is True and value['deliveryProved'] is False and value['shellPid']==shell_pid and value['documentHwnd']==document
    assert value['engineHandleReleased'] is True and value['dpiScope']['restored'] is True and not value['cleanupErrors']
    assert value['startedAt']<value['finishedAt']<value['deadline']<=value['startedAt']+5
    if command is not None:assert value['command']==command
    binding=value['binding'];assert binding['document']==document and binding['officePid']!=shell_pid
    for number in binding.values():_int(number)
    shell,engine=value['originalProcess'],value['originalEngine']
    assert shell['pid']==shell_pid and engine['pid']==binding['officePid']
    for row in (shell,engine):
        _int(row['pid']);_int(row['creationTime']);assert type(row['waitResult']) is int and row['waitResult']==258
    _int(shell['handleValue']);_int(value['engineHandleValue'])
    assert engine['creationTime']>=shell['creationTime']
    shell_image=_image(shell['image']);engine_image=_image(engine['image'])
    assert shell_image.name.casefold()=='opengeul.office.exe'
    assert str(engine_image).casefold()==str(shell_image.parent/'Office'/'program'/'soffice.bin').casefold()
    operation=value['command']
    assert type(value['gesture']) is bool
    if value['gesture']:
        assert operation in GESTURES and value['focusReturned'] is True
        _editor(value['focusAfter'],value['binding'],shell_pid)
        expected=[] if operation=='keyboard-escape' else ['file']+(['outside'] if operation=='open-outside' else [])
        keys=['ALT_F','DOWN','ESCAPE'] if operation=='keyboard-escape' else [] if operation=='open-outside' else ['ESCAPE']
        if operation.startswith('disabled-'):
            assert value['disabledObserved'] is True
            _validate(value['disabledSnapshot'],value['binding'],shell_pid,operation[len('disabled-'):],enabled=False)
    else:
        assert operation in COMMANDS
        expected=['file']+(['new'] if operation.startswith('new-') and operation!='new-hwp' else [])+[operation];keys=[]
    assert [item['target'] for item in value['pointers']]==expected
    assert [item['shortcut'] for item in value['keys']]==keys
    for item in value['keys']:
        if item['shortcut']=='ALT_F':
            _validate(item['before'],binding,shell_pid,'file');_editor(item['editorBefore'],binding,shell_pid)
        else:_keyboard_recipient(item['before'],binding,shell_pid)
        assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
        assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==KEY_COUNTS[item['shortcut']]
    for item in value['pointers']:
        if item['target']=='outside':
            hit=item['nativeBefore'];assert (hit['hitHwnd'],hit['pid'],hit['rootHwnd'],hit['hitTest'])==(document,shell_pid,document,2)
            assert hit['point']==item['chosenPhysicalPoint'] and item['requestedInputs']==item['insertedInputs']==2
            continue
        anchors=[_validate(s,value['binding'],shell_pid,item['target']) for s in item['snapshots']]
        assert len(anchors)==3 and all(a==anchors[0] for a in anchors)
        assert len(item['hits'])==2 and all(h['point']==item['chosenPhysicalPoint'] and h['pid']==value['binding']['officePid'] and h['withinControl'] is h['uiaMatches'] is True for h in item['hits'])
        assert item['pointerReadback']==item['beforeClickCursorReadback']==item['chosenPhysicalPoint']
        rect=item['snapshots'][0]['control']['rectangle']
        assert item['chosenPhysicalPoint']==[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        for hit,snapshot in zip(item['hits'],item['snapshots'][1:]):
            assert hit['hitHwnd']>0 and hit['rootHwnd']==(snapshot['popup']['hwnd'] if snapshot['popup'] else document)
        assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
        assert item['inputCallAttempts']==1 and item['insertedInputs']==item['requestedInputs']==2
    return value


def detached_native_menu_action(value):
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    assert len(raw.encode())<=CAP
    return json.loads(raw)


class NativeMenuProbe(NativeControlProbe):
    # CUIAutomation8 is the documented Windows 8+ IUIAutomation2 implementation.
    # A private client avoids changing pywinauto's shared UIA singleton settings.
    CLIENT='{e22ad333-b25f-460c-83d0-0581107395c9}'
    def __init__(self,deadline,clock,**libraries):
        self.provider_client=None
        NativeActivationProbe.__init__(self,deadline,clock,**libraries)
        H,D,B=C.c_void_p,C.c_uint32,C.c_int32
        for name,args,result in [('GetWindow',(H,D),H),('GetWindowTextW',(H,C.c_wchar_p,B),B),
            ('GetClassNameW',(H,C.c_wchar_p,B),B),('IsChild',(H,H),B),('GetPropW',(H,C.c_wchar_p),H),
            ('GetGUIThreadInfo',(D,C.POINTER(GuiThreadInfo)),B)]:
            function=getattr(self.user,name);function.argtypes,function.restype=args,result
        self.keyboard_probe=None
        try:
            import comtypes.client
            library=self._call(comtypes.client.GetModule,'UIAutomationCore.dll')
            interface=library.IUIAutomation2
            self.provider_client=self._call(lambda:comtypes.client.CreateObject(self.CLIENT,interface=interface))
            self._provider_timeout()
            self.uia=SimpleNamespace(iuia=self.provider_client,
                tree_scope={'children':2,'descendants':4},build_condition=self._condition)
            self._point_type=library.tagPOINT
        except BaseException:
            self.close_provider();raise
    def _provider_timeout(self):
        remaining=self.deadline-self.clock()
        # Connection and transaction timeouts can both be consumed by a request.
        # Reserve half the remaining time for readback, validation and cleanup.
        milliseconds=int((remaining*1000-1)//4)
        assert 1<=milliseconds<=1250, 'Native UIA provider query budget expired'
        for name in ('ConnectionTimeout','TransactionTimeout'):
            assert self.clock()<self.deadline, 'Native UIA timeout setup deadline expired'
            setattr(self.provider_client,name,milliseconds)
            assert self.clock()<self.deadline, 'Native UIA timeout setter exceeded deadline'
            observed=getattr(self.provider_client,name)
            assert self.clock()<self.deadline, 'Native UIA timeout readback exceeded deadline'
            assert type(observed) is int and observed==milliseconds, 'Native UIA provider timeout was not accepted'
        assert 2*milliseconds<(self.deadline-self.clock())*1000, \
            'Native UIA timeout setup exhausted the original query budget'
        self.provider_timeout_verified=True
    def _call(self,function,*args):
        assert self.clock()<self.deadline, 'Native menu query deadline expired'
        if getattr(self,'provider_client',None) is not None:self._provider_timeout()
        value=function(*args)
        assert self.clock()<self.deadline, 'Native menu query exceeded original deadline'
        return value
    def close_provider(self):
        # Drop all owned element/client references. No shared client was changed.
        for name in ('file_element','menu_bar_element','current_control','_retained','uia','provider_client'):
            if hasattr(self,name):setattr(self,name,None)
        return True
    def _condition(self,*,control_type,name=None):
        kinds={'MenuBar':50010,'MenuItem':50011,'Text':50020,'Button':50000}
        assert control_type in kinds and (name is None or type(name) is str and len(name)<=256)
        condition=self._call(self.uia.iuia.CreatePropertyCondition,30003,kinds[control_type])
        if name is not None:
            label=self._call(self.uia.iuia.CreatePropertyCondition,30005,name)
            condition=self._call(self.uia.iuia.CreateAndCondition,condition,label)
        return condition
    def _root(self,hwnd):return self._call(self.uia.iuia.ElementFromHandle,hwnd)
    def point_snapshot(self,scope,point,control):
        from suite_window_activation import Point
        hit=int(self._call(self.user.WindowFromPhysicalPoint,Point(*point)) or 0);pid=C.c_uint32()
        if hit:self._required(self._call(self.user.GetWindowThreadProcessId,hit,C.byref(pid)),'Physical native menu hit PID')
        target=control.element_info._element;handle=self._chrome(target)['nativeHwnd']
        actual=self._call(self.uia.iuia.ElementFromPoint,self._point_type(*point))
        match=bool(self._call(self.uia.iuia.CompareElements,target,actual))
        return dict(point=list(point),hitHwnd=hit,pid=int(pid.value),
            rootHwnd=int(self._call(self.user.GetAncestor,hit,2) or 0) if hit else 0,
            withinControl=bool(hit and (hit==handle or handle and self._call(self.user.IsChild,handle,hit) or not handle and match)),uiaMatches=match)
    def _chrome(self,element):
        # Ancestor names can contain a document title; query identity only.
        def get(name):return self._call(lambda:getattr(element,name))
        handle=get('CurrentNativeWindowHandle')
        assert handle is None or type(handle) is int and -(2**31)<=handle<2**32
        runtime=list(self._call(element.GetRuntimeId))
        assert 0<len(runtime)<=64 and all(type(n) is int and -(2**31)<=n<2**31 for n in runtime)
        box=get('CurrentBoundingRectangle');kind=int(get('CurrentControlType'))
        return dict(runtimeId=runtime,pid=int(get('CurrentProcessId')),
            nativeHwnd=0 if handle is None else handle&0xffffffff,
            controlType={50000:'Button',50010:'MenuBar',50011:'MenuItem',50032:'Window'}.get(kind,str(kind)),
            visible=not bool(get('CurrentIsOffscreen')),enabled=bool(get('CurrentIsEnabled')),
            rectangle=[int(getattr(box,key)) for key in ('left','top','right','bottom')])
    def _find(self,root,target,*,scope='descendants'):
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuItem'))
        found=self._call(root.FindAll,self.uia.tree_scope[scope],condition)
        count=int(self._call(lambda:found.Length));assert 0<=count<=512
        matches=[]
        for i in range(count):
            element=self._call(found.GetElement,i)
            if int(self._call(lambda:element.CurrentControlType))!=50011:continue
            if self._call(lambda:element.CurrentIsOffscreen):continue
            name=str(self._call(lambda:element.CurrentName));assert len(name)<=256
            if _label(name) in LABELS[target]:matches.append(element)
        assert len(matches)<=1, 'Native chrome target is ambiguous'
        if not matches:raise NativeMenuPending('Native chrome target not visible yet')
        return matches[0]
    def discover_file(self,root):
        # Ask UIA for chrome only. Never materialize document paragraphs/cells.
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuBar'))
        found=self._call(root.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._call(lambda:found.Length));assert 0<=count<=8
        bars=[]
        for index in range(count):
            bar=self._call(found.GetElement,index)
            if not self._call(lambda:bar.CurrentIsOffscreen):bars.append(bar)
        assert len(bars)<=1, 'Native menubar is ambiguous'
        if not bars:raise NativeMenuPending('Native menubar not visible yet')
        self.menu_bar_element=bars[0]
        return self._find(bars[0],'file',scope='children')
    def _focused_menu(self,chain,file_index,bar_index):
        result=[];cursor=self._call(self.uia.iuia.GetFocusedElement);matched=False
        allowed={tuple(chain[file_index]['runtimeId']),tuple(chain[bar_index]['runtimeId'])}
        for _ in range(32):
            if not cursor:break
            runtime=list(self._call(cursor.GetRuntimeId))
            kind=int(self._call(lambda:cursor.CurrentControlType))
            result.append(dict(runtimeId=runtime,pid=int(self._call(lambda:cursor.CurrentProcessId)),controlType={50010:'MenuBar',50011:'MenuItem'}.get(kind,str(kind))))
            if tuple(runtime) in allowed:
                # Resolve runtime IDs back to the retained live menu objects.
                for ancestor in (self.file_element,self.menu_bar_element):
                    if self._call(self.uia.iuia.CompareElements,cursor,ancestor):matched=True
                break
            cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor)
        return result,matched
    def _owners(self,hwnd,binding):
        rows=[]
        while hwnd:
            assert hwnd not in rows and len(rows)<16;rows.append(hwnd)
            if hwnd in (binding['child'],binding['document']):break
            row=self.window_snapshot(hwnd);assert row['pid']==binding['officePid']
            hwnd=int(self._call(self.user.GetWindow,hwnd,4) or 0)
        return rows
    def snapshot(self,binding,target):
        doc=binding['document'];child=binding['child'];pid=binding['officePid']
        root=self._root(child)
        if not hasattr(self,'file_element'):self.file_element=self.discover_file(root)
        element=self.file_element if target=='file' else self._find(self.file_element,target)
        self.current_control=type('NativeMenuControl',(),{'element_info':type('Info',(),{'_element':element})()})()
        chain=[];cursor=element;file_index=bar_index=None;file_equal=peer_equal=False
        for _ in range(32):
            row=self._chrome(cursor);chain.append(row);index=len(chain)-1
            if self._call(self.uia.iuia.CompareElements,cursor,self.file_element):file_index=index;file_equal=True
            if row['controlType']=='MenuBar' and file_index is not None and bar_index is None:bar_index=index
            if self._call(self.uia.iuia.CompareElements,cursor,root):peer_equal=True;break
            cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
        else:raise AssertionError('Native menu ancestry exceeded bound')
        control=self._chrome(element);rect=control['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        popup=None
        if target!='file':
            hit=self.point_snapshot(doc,point,self.current_control);popup=self.window_snapshot(hit['rootHwnd'])
            popup['ownerChain']=self._owners(popup['hwnd'],binding)
        attachment=self.attachment_snapshot(binding);document=self.window_snapshot(doc)
        thread=attachment['windows']['child']['threadId'];gui=self.native_focus(thread)
        permitted={0,child}
        if popup:permitted.add(popup['hwnd'])
        gui.update(captureOwned=gui['captureHwnd'] in permitted,menuOwnerOwned=gui['menuOwnerHwnd'] in permitted)
        focused,matched=(self._focused_menu(chain,file_index,bar_index) if target!='file' and not _menu_key_owner(gui,popup,child) and file_index is not None and bar_index is not None else ([],False))
        fg=self.window_snapshot(self.foreground())
        shell=self._root(doc)
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuBar'))
        bars=self._call(shell.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._call(lambda:bars.Length));assert 0<=count<=64
        duplicates=0
        for index in range(count):
            bar=self._call(bars.GetElement,index)
            owner=self._call(lambda:bar.CurrentProcessId)
            visible=not self._call(lambda:bar.CurrentIsOffscreen)
            duplicates+=int(owner==document['pid'] and visible)
        return dict(binding=dict(binding),attachmentValid=attachment['valid'],nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
            shellMenuCount=duplicates,document=document,control=control,ancestry=chain,fileIndex=file_index,
            barIndex=bar_index,peerIndex=len(chain)-1,fileElementEquals=file_equal,peerElementEquals=peer_equal,
            popup=popup,foreground=fg,gui=gui,focusMenuPath=focused,focusMenuElementEquals=matched)
    def editor_snapshot(self,binding):
        attachment=self.attachment_snapshot(binding);thread=attachment['windows']['child']['threadId'];gui=self.native_focus(thread)
        return dict(binding=dict(binding),attachmentValid=attachment['valid'],focusPid=gui['focusPid'],
            foreground=self.window_snapshot(self.foreground()),
            focusRootHwnd=gui['focusRootHwnd'],focusUnderOriginalChild=attachment['focusUnderOriginalChild'],
            captureHwnd=gui['captureHwnd'],menuOwnerHwnd=gui['menuOwnerHwnd'],menuClosed=not gui['captureHwnd'] and not gui['menuOwnerHwnd'])
    def keyboard(self,binding,shortcut,receipt):
        from ascii_editor_input import input_buffer
        plans={'ALT_F':((0x38,0),(0x21,0)),'DOWN':((0x50,1),),'ESCAPE':((0x01,0),)}
        assert shortcut in plans
        thread=self.attachment_snapshot(binding)['windows']['child']['threadId'];state=self.keyboard_snapshot(thread)
        assert state['targetLayout']==state['currentThreadLayout']==0x04090409 and not state['keysDown']
        held=[key for key in (1,2,4,5,6,0x46,0x28) if self._call(self.user.GetAsyncKeyState,key)&0x8000]
        assert not held, 'A native menu navigation key is already pressed'
        receipt['keyboardBefore']=dict(state,additionalMenuKeysDown=held)
        keys=plans[shortcut];events=([dict(vk=0,scan=s,flags=8|x) for s,x in keys]+[dict(vk=0,scan=s,flags=10|x) for s,x in reversed(keys)])
        receipt.update(requestedInputs=len(events),inputCallAttempts=1,insertedInputs=None)
        inserted=self.send(input_buffer(events));receipt['insertedInputs']=inserted
        if inserted!=len(events):
            assert type(inserted) is int and 0<=inserted<len(events)
            release=self.owned_release_events(events,inserted)
            if release:receipt['ownedReleaseInserted']=self.release(release)
        assert inserted==len(events), 'Native menu key input was partial'
    def outside_snapshot(self,binding):
        rect=self.caption(binding['document'])['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        return NativeActivationProbe.point_snapshot(self,binding['document'],point)
    def outside_click(self,binding,receipt):
        before=self.outside_snapshot(binding);point=before['point'];assert before['hitTest']==2 and before['rootHwnd']==binding['document']
        assert receipt['chosenPhysicalPoint']==point, 'Original outside-menu caption point changed'
        self.move(point,receipt)
        after=self.outside_snapshot(binding);assert after==before
        self.click(receipt)
