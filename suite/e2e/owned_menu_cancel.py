"""One measured Cancel pointer in the shell prompt of a native Home/Exit.

No ID is assumed for TaskDialog's custom button. Only fixed chrome names are
queried; document names, contents and arbitrary UIA names are not retained.
"""
from __future__ import annotations
import copy
import ctypes as C
import math
from pathlib import Path
import time
from types import SimpleNamespace

from owned_control_actions import NativeWindowClassUnavailable
from owned_native_menu import NativeMenuProbe,require_native_menu_action,retain_native_menu_receipt
from generated_calc_close import _require_native_titlebar_close

HEADING='변경 내용을 저장하시겠습니까?'
NOTICE='저장하지 않음을 선택하면 변경 내용이 사라집니다.'
BUTTONS=('저장','저장하지 않음','취소')
CAPTIONS=tuple('OpenGeul '+name for name in ('Writer','Calc','Impress','Draw','Math','Base'))


def _positive(value):assert type(value) is int and 0<value<2**64


def _runtime(value):
    assert type(value) is list and 0<len(value)<=64
    assert all(type(x) is int and -(2**31)<=x<2**31 for x in value)


def _identity(value):
    for key in ('pid','creationTime'):_positive(value[key])
    assert type(value['waitResult']) is int and value['waitResult']==258
    assert type(value['image']) is str and value['image']
    return value['pid'],value['creationTime'],value['image'].casefold(),value['waitResult']


def _target(row,binding,shell_pid,document,dialog,caption,original_document):
    assert row['binding']==binding and row['attachmentValid'] is True
    doc,modal,root,button,gui=(row[k] for k in ('document','dialog','root','control','gui'))
    for value in (doc,modal):
        for key in ('hwnd','pid','threadId','rootHwnd'):_positive(value[key])
    assert all(doc[k]==original_document[k] for k in ('hwnd','pid','threadId','rootHwnd'))
    assert (doc['hwnd'],doc['pid'],doc['rootHwnd'])==(document,shell_pid,document)
    assert doc['visible'] is True and doc['enabled'] is False, 'Original document must be disabled by its modal prompt'
    assert (modal['hwnd'],modal['rootHwnd'],modal['pid'],modal['ownerHwnd'],modal['threadId'])==(dialog,dialog,shell_pid,document,doc['threadId'])
    assert modal['visible'] is modal['enabled'] is True and modal['className']=='#32770' and modal['title']==caption
    assert row['headingMatches'] is True and row['cancelMatches'] is True
    assert type(row['headingCount']) is type(row['cancelCount']) is int and row['headingCount']==row['cancelCount']==1
    assert row['promptSchemaVerified'] is True and row['noticeMatches'] is True
    assert type(row['noticeCount']) is int and row['noticeCount']==1
    assert type(row['promptButtonCount']) is int and row['promptButtonCount']==3
    assert row['clientChoicesVerified'] is True
    assert type(row['nonclientCloseCount']) is int and row['nonclientCloseCount'] in (0,1)
    assert type(row['promptTotalButtonCount']) is int and row['promptTotalButtonCount']==3+row['nonclientCloseCount']
    if row['nonclientCloseCount']:
        proof=row['nonclientCloseProof'];assert proof['rootElementEquals'] is True
        assert proof['fixedNameMatches'] is proof['blankAutomationId'] is proof['blankClassName'] is True
        assert all(part['processId']==shell_pid for part in proof['ancestry'])
        _require_native_titlebar_close(SimpleNamespace(element_info=SimpleNamespace(name='Close',automation_id='',class_name='')),
            proof['ancestry'],dialog)
    else:assert row['nonclientCloseProof'] is None
    assert root['nativeHwnd']==dialog and root['pid']==shell_pid and root['controlType']=='Window'
    assert root['visible'] is root['enabled'] is True;_runtime(root['runtimeId'])
    assert button['controlType']=='Button' and button['pid']==shell_pid
    assert button['visible'] is button['enabled'] is True;_runtime(button['runtimeId'])
    assert type(button['nativeHwnd']) is int and button['nativeHwnd']>=0
    ancestry=row['ancestry'];assert 2<=len(ancestry)<=32 and ancestry[0]==button and ancestry[-1]==root
    assert all(item['pid']==shell_pid for item in ancestry) and row['rootElementEquals'] is True
    for item in ancestry:_runtime(item['runtimeId'])
    rectangle=button['rectangle'];outer=modal['rectangle']
    assert len(rectangle)==len(outer)==4 and all(type(n) is int for n in rectangle+outer)
    assert outer[0]<=rectangle[0]<rectangle[2]<=outer[2] and outer[1]<=rectangle[1]<rectangle[3]<=outer[3]
    assert (row['foreground']['hwnd'],row['foreground']['rootHwnd'],row['foreground']['pid'])==(dialog,dialog,shell_pid)
    assert gui['threadId']==doc['threadId'] and gui['activeHwnd']==dialog
    assert gui['focusHwnd']>0 and gui['focusPid']==shell_pid and gui['focusRootHwnd']==dialog
    assert type(gui['flags']) is int and not gui['flags']&0x1e
    assert gui['captureHwnd']==gui['menuOwnerHwnd']==0, 'Cancel prompt has menu or capture activity'
    return (tuple(root['runtimeId']),tuple(button['runtimeId']),button['nativeHwnd'],tuple(rectangle),
            modal['threadId'],tuple(tuple(item['runtimeId']) for item in ancestry))


def cancel_native_menu_prompt(api,process,document,record,dialog,caption,*,probe=None,clock=time.monotonic,seconds=5):
    assert caption in CAPTIONS and type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=5
    _positive(document);_positive(dialog);assert dialog!=document
    start=clock();deadline=start+seconds
    value=dict(schemaVersion=1,kind='owned-shell-menu-cancel',success=False,purpose='MENU_CANCEL',
        documentHwnd=document,dialogHwnd=dialog,shellPid=process.pid,caption=caption,
        startedAt=start,deadline=deadline,dpiScope={},snapshots=[],hits=[],
        inputCallAttempts=0,requestedInputs=0,insertedInputs=None,engineHandleReleased=False)
    previous=record.setdefault('nativeMenuPromptCancels',[]);previous.append(value)
    handle=None;primary=None
    def budget():assert clock()<deadline, 'Original native-menu Cancel deadline expired'
    try:
        budget();origins=record.get('nativeMenuActions',[])
        assert type(origins) is list and 0<len(origins)<=128, 'Cancel requires its original native menu trigger'
        index=len(origins)-1;origin=origins[index]
        assert origin['command'] in ('home','exit') and origin['gesture'] is False, 'Unrelated native menu trigger'
        require_native_menu_action(origin,process.pid,document,origin['command'])
        assert origin['finishedAt']<=start, 'Cancel precedes its native menu trigger'
        assert all(row.get('originIndex')!=index for row in previous[:-1]), 'Native menu prompt trigger already consumed'
        value.update(originIndex=index,nativeMenuTrigger=copy.deepcopy(origin),binding=copy.deepcopy(origin['binding']))
        binding=value['binding'];shell=origin['originalProcess'];engine=origin['originalEngine']
        original_doc=origin['pointers'][0]['snapshots'][0]['document']
        assert process.pid==shell['pid'] and int(process._handle)==shell['handleValue']
        suite=Path(process.opengeul_suite_root).resolve()
        assert Path(shell['image']).resolve()==suite/'OpenGeul.Office.exe'
        assert Path(engine['image']).resolve()==suite/'Office/program/soffice.bin'
        probe=probe or NativeMenuCancelProbe(deadline,clock,document,dialog,caption)
        observed_shell=probe.process_snapshot(process)
        assert _identity(observed_shell)==_identity(shell) and observed_shell['handleValue']==shell['handleValue'], 'Original menu shell generation changed'
        handle=probe.open_engine(binding['officePid']);current_engine=probe.engine_snapshot(handle)
        assert _identity(current_engine)==_identity(engine), 'Original menu engine generation changed'
        value.update(originalProcess=copy.deepcopy(shell),originalEngine=copy.deepcopy(engine),engineHandleValue=handle)
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        def continuity():
            budget();now=probe.process_snapshot(process)
            assert _identity(now)==_identity(shell) and now['handleValue']==shell['handleValue']
            assert _identity(probe.engine_snapshot(handle))==_identity(engine)
            assert api.attachment(document)==(binding['parent'],binding['child'],binding['officePid'])
        def observe():
            continuity();row=probe.snapshot(api,document,dialog,caption);budget()
            anchor=_target(row,binding,process.pid,document,dialog,caption,original_doc)
            value['snapshots'].append(row);return row,anchor
        row,anchor=observe();rect=row['control']['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        value['chosenPhysicalPoint']=point
        def check():
            fresh,actual=observe();assert actual==anchor, 'Original Cancel UIA recipient changed'
            hit=probe.point_snapshot(dialog,point,probe.current_control);value['hits'].append(hit)
            assert hit['point']==point and (hit['pid'],hit['rootHwnd'])==(process.pid,dialog)
            assert hit['withinControl'] is hit['uiaMatches'] is True, 'Original Cancel point is obstructed'
        check();retain_native_menu_receipt(process,value)
        probe.move(point,value);assert value['pointerReadback']==point
        check();retain_native_menu_receipt(process,value);continuity();probe.click(value);budget()
        assert all(type(value[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
        assert value['inputCallAttempts']==1 and value['requestedInputs']==value['insertedInputs']==2
        assert value['beforeClickCursorReadback']==point
        context=dict(originalProcess=shell,document=row['document'],scope=row['dialog'])
        value['after']=probe.transition_snapshot(api,process,document,dialog,caption,'MENU_CANCEL',probe.current_control,
            context=context,evidence={})
        assert value['after']['accepted'] is True and value['after']['transition']=='original-owned-dialog-destroyed'
        assert value['after']['originalDialogAlive'] is False and value['after']['originalDocumentAlive'] is True
        continuity();value['inputVerified']=True
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
        try:retain_native_menu_receipt(process,value)
        except BaseException:
            value['success']=False
            if primary is None:raise
        if primary is None:assert value['success'], 'Native-menu Cancel cleanup or original deadline failed'
    return value


class NativeMenuCancelProbe(NativeMenuProbe):
    def __init__(self,deadline,clock,document,dialog,caption):
        super().__init__(deadline,clock)
        self.document,self.dialog,self.expected_caption=document,dialog,caption
    def _window(self,hwnd):
        row=self.window_snapshot(hwnd)
        row['ownerHwnd']=int(self._call(self.user.GetWindow,hwnd,4) or 0)
        if hwnd==self.document:return row  # Never read or retain the document title.
        assert hwnd==self.dialog
        title=C.create_unicode_buffer(257);kind=C.create_unicode_buffer(257)
        count=int(self._call(self.user.GetWindowTextW,hwnd,title,len(title)))
        size=int(self._call(self.user.GetClassNameW,hwnd,kind,len(kind)))
        if size==0:raise NativeWindowClassUnavailable(hwnd)
        assert 0<=count<256 and 0<size<256
        row.update(title=self.expected_caption if title.value==self.expected_caption else None,
                   className='#32770' if kind.value=='#32770' else None)
        return row
    def _chrome(self,element):
        handle=self._call(lambda:element.CurrentNativeWindowHandle)
        assert handle is None or type(handle) is int and -(2**31)<=handle<2**32
        box=self._call(lambda:element.CurrentBoundingRectangle)
        kinds={50000:'Button',50020:'Text',50032:'Window',50037:'TitleBar'}
        return dict(nativeHwnd=0 if handle is None else handle&0xffffffff,
            runtimeId=list(self._call(element.GetRuntimeId)),pid=int(self._call(lambda:element.CurrentProcessId)),
            controlType=kinds.get(int(self._call(lambda:element.CurrentControlType)),'other'),
            rectangle=[int(getattr(box,k)) for k in ('left','top','right','bottom')],
            visible=not bool(self._call(lambda:element.CurrentIsOffscreen)),enabled=bool(self._call(lambda:element.CurrentIsEnabled)))
    def _one(self,root,kind,name):
        condition=self._call(lambda:self.uia.build_condition(control_type=kind,name=name))
        found=self._call(root.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._call(lambda:found.Length));assert count==1, 'Fixed prompt chrome must be unique'
        return self._call(found.GetElement,0),count
    def _prompt_schema(self,root):
        # Count only Button controls; never enumerate their arbitrary names.
        condition=self._call(lambda:self.uia.build_condition(control_type='Button'))
        buttons=self._call(root.FindAll,self.uia.tree_scope['descendants'],condition)
        button_count=int(self._call(lambda:buttons.Length))
        assert button_count in (len(BUTTONS),len(BUTTONS)+1), 'Close prompt button inventory changed'
        pid=self._chrome(root)['pid'];held=[];fixed={};counts={}
        for kind,name in (('Text',HEADING),('Text',NOTICE),*(('Button',label) for label in BUTTONS)):
            element,count=self._one(root,kind,name);held.append(element)
            assert self._call(lambda:element.CurrentName)==name, 'Fixed close prompt label changed'
            chrome=self._chrome(element)
            assert chrome['pid']==pid and chrome['controlType']==kind and chrome['visible'] is True
            if kind=='Button':
                assert chrome['enabled'] is True, 'Close prompt button is disabled'
                held.extend(self._client_choice(element,root,pid))
            fixed[name]=element;counts[name]=count
        proof=None
        if button_count==len(BUTTONS)+1:
            proof,nonclient=self._nonclient_close(root,pid);held.extend(nonclient)
        return dict(promptSchemaVerified=True,noticeMatches=True,noticeCount=counts[NOTICE],
            promptButtonCount=len(BUTTONS),promptTotalButtonCount=button_count,
            nonclientCloseCount=int(proof is not None),nonclientCloseProof=proof,clientChoicesVerified=True,
            headingMatches=True,headingCount=counts[HEADING],
            cancelMatches=True,cancelCount=counts['취소'],headingElement=fixed[HEADING],
            cancelElement=fixed['취소'],retainedElements=tuple(held))
    def _client_choice(self,button,root,pid):
        # Fixed labels must remain native client controls of this exact dialog.
        chrome=self._chrome(button);_positive(chrome['nativeHwnd'])
        native=self.window_snapshot(chrome['nativeHwnd'])
        assert native['pid']==pid and native['rootHwnd']==self.dialog
        assert self._call(self.user.IsChild,self.dialog,chrome['nativeHwnd'])
        held=[];cursor=button
        for _ in range(32):
            assert cursor;held.append(cursor);row=self._chrome(cursor);_runtime(row['runtimeId'])
            assert row['pid']==pid and row['controlType']!='TitleBar', 'Close choice is not an owned client control'
            if self._call(self.uia.iuia.CompareElements,cursor,root):
                assert row['controlType']=='Window' and row['nativeHwnd']==self.dialog
                return held
            cursor=self._call(self.uia.iuia.RawViewWalker.GetParentElement,cursor)
        raise AssertionError('Close choice ancestry exceeded its finite bound')
    def _nonclient_close(self,root,pid):
        # Query only the known Close label; no arbitrary button names are read.
        button,_=self._one(root,'Button','Close')
        assert self._call(lambda:button.CurrentName)=='Close'
        assert self._call(lambda:button.CurrentAutomationId)==''
        assert self._call(lambda:button.CurrentClassName)==''
        held=[];path=[];cursor=button;same=False
        for _ in range(3):
            assert cursor;held.append(cursor);row=self._chrome(cursor);_runtime(row['runtimeId'])
            assert row['pid']==pid and row['visible'] is row['enabled'] is True
            path.append(dict(nativeHandle=row['nativeHwnd'],processId=row['pid'],
                runtimeId=row['runtimeId'],controlType=row['controlType']))
            if self._call(self.uia.iuia.CompareElements,cursor,root):same=True;break
            cursor=self._call(self.uia.iuia.RawViewWalker.GetParentElement,cursor)
        assert same, 'Nonclient Close ancestry does not reach the exact prompt root'
        _require_native_titlebar_close(SimpleNamespace(element_info=SimpleNamespace(name='Close',automation_id='',class_name='')),path,self.dialog)
        return dict(rootElementEquals=True,fixedNameMatches=True,blankAutomationId=True,
            blankClassName=True,ancestry=path),held
    def snapshot(self,api,document,dialog,caption):
        doc=self._window(document);modal=self._window(dialog)
        assert modal['pid']==doc['pid'] and modal['ownerHwnd']==document
        assert modal['title']==caption and modal['className']=='#32770'
        root=self._root(dialog)
        schema=self._prompt_schema(root);button=schema['cancelElement']
        root_row=self._chrome(root);chain=[];cursor=button;held=[];same=False
        for _ in range(32):
            held.append(cursor);chain.append(self._chrome(cursor))
            if self._call(self.uia.iuia.CompareElements,cursor,root):same=True;break
            cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
        else:raise AssertionError('Cancel ancestry exceeded its finite bound')
        self._retained=(root,*schema['retainedElements'],*held)
        self.current_control=SimpleNamespace(element_info=SimpleNamespace(_element=button))
        if chain[0]['nativeHwnd']:
            native=self.window_snapshot(chain[0]['nativeHwnd'])
            assert native['pid']==doc['pid'] and native['rootHwnd']==dialog
            assert self._call(self.user.IsChild,dialog,native['hwnd'])
        parent,child,pid=api.attachment(document)
        binding=dict(document=document,parent=parent,child=child,officePid=pid)
        attachment=self.attachment_snapshot(binding)
        return dict(document=doc,dialog=modal,root=root_row,control=chain[0],ancestry=chain,
            rootElementEquals=same,**{key:schema[key] for key in ('headingMatches','cancelMatches',
                'headingCount','cancelCount','promptSchemaVerified','noticeMatches','noticeCount','promptButtonCount',
                'promptTotalButtonCount','nonclientCloseCount','nonclientCloseProof','clientChoicesVerified')},
            binding=binding,attachmentValid=attachment['valid'],
            gui=self.native_focus(doc['threadId']),foreground=self.window_snapshot(self.foreground()))
