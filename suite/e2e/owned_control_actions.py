"""One measured input to an original Suite menu or exact owned native picker.

Insertion counts do not prove an atomic recipient. Existing dialog/model barriers
remain the effect checks. No focus repair, foreign-window action or retry exists.
"""
from __future__ import annotations
import ctypes as C
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from suite_window_activation import NativeActivationProbe, Point, Rect

CAP = 128 * 1024
PURPOSES = ('FILE_MENU', 'SAVE_MENU', 'OPEN_BUTTON', 'SAVE_BUTTON', 'DIALOG_ESCAPE')
PICKERS = ('OpenGeul Office에서 문서 열기', 'OpenGeul Writer — 다른 이름으로 저장',
           'OpenGeul Base — 다른 이름으로 저장')


def _integer(value, positive=True):
    assert type(value) is int and (value > 0 if positive else value >= 0)
    return value


def _rectangle(value):
    assert isinstance(value, list) and len(value) == 4
    assert all(type(x) is int and -(2**31) <= x < 2**31 for x in value)
    assert value[0] < value[2] and value[1] < value[3], 'Empty owned control rectangle'
    return value


def _inside(inner, outer):
    _rectangle(inner); _rectangle(outer)
    return outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]


def _window(row, hwnd, pid, *, enabled=True):
    assert (row['hwnd'], row['pid'], row['rootHwnd']) == (hwnd, pid, hwnd), 'Owned control window identity changed'
    _integer(row['threadId']); _rectangle(row['rectangle'])
    assert row['visible'] is True and row['iconic'] is False and row['cloaked'] == 0
    if enabled: assert row['enabled'] is True, 'Owned input scope is disabled'


def _menu_focus(value, document, pid):
    foreground, gui = value['foreground'], value['gui']
    root = foreground['rootHwnd']
    assert foreground['pid'] == pid and foreground['hwnd'] == root
    assert foreground['threadId']==value['scope']['threadId'], 'Foreground popup belongs to another native thread'
    if root == document:
        assert gui['activeHwnd'] == document, 'Original document is not active'
        assert gui['focusPid'] == pid and gui['focusRootHwnd'] == document, 'Host-menu focus escaped original document'
        if not (gui['menuOwnerHwnd'] == document and gui['flags'] & 0x1c):
            menu_ids=[row['runtimeId'] for row in value['ancestry']
                      if row.get('controlType') in ('MenuItem','MenuBar')]
            focused=value['focusAncestry']
            assert focused and all(row['pid']==pid for row in focused)
            assert any(row['runtimeId'] in menu_ids for row in focused), 'Native focus lacks retained File/MenuBar ancestry'
            assert value['nativeFocusUnderMenu'] is True, 'Native focus is outside retained menu controls'
    else:
        chain = value['foregroundOwnerChain']
        assert 1 < len(chain) <= 16 and chain[0] == root and chain[-1] == document and len(set(chain)) == len(chain), 'Popup lacks original document owner chain'
        assert gui['menuOwnerHwnd'] == document and gui['flags'] & 0x1c, 'Owned popup lacks native menu focus'
        assert gui['focusPid'] == pid and gui['focusRootHwnd'] in (document, root), 'Menu focus belongs to another window'
    assert gui['captureHwnd'] in (0, root, gui['menuOwnerHwnd']), 'Unexpected native input capture'


def _target(value, purpose, document, pid, dialog, caption, readiness, *, operation='keyboard'):
    assert purpose in PURPOSES
    doc, scope, control, gui = (value[key] for key in ('document', 'scope', 'control', 'gui'))
    _window(doc, document, pid, enabled=not bool(dialog))
    _window(scope, dialog or document, pid)
    assert gui['threadId'] == scope['threadId'] and type(gui['flags']) is int
    assert gui['focusHwnd'] > 0, 'Owned input has no native focus'
    assert control['pid'] == pid and control['runtimeId'] and all(type(v) is int for v in control['runtimeId'])
    assert control['visible'] is True and control['enabled'] is True
    assert _inside(control['rectangle'], scope['rectangle']), 'UIA control rectangle escaped owned scope'
    ancestry = value['ancestry']
    assert 1 <= len(ancestry) <= 32 and all(row['pid'] == pid and row['runtimeId'] for row in ancestry)
    assert ancestry[0]['runtimeId'] == control['runtimeId'] and ancestry[-1]['nativeHwnd'] == (dialog or document), 'Control ancestry names another original scope'
    if purpose == 'FILE_MENU':
        assert not dialog and control['controlType'] == 'MenuItem' and control['name'] == '파일'
        if operation == 'pointer' and value['foreground']['hwnd'] == document:
            # The initial File click acquires host focus from its embedded
            # editor. Its recipient is the separately matched physical UIA
            # control, not whichever editor currently owns keyboard focus.
            assert gui['activeHwnd'] == document and gui['focusRootHwnd'] == document
            assert gui['captureHwnd'] == 0, 'Unexpected capture before File control click'
        else:
            _menu_focus(value, document, pid)
    else:
        assert dialog != document and caption in PICKERS and scope['ownerHwnd'] == document
        assert (purpose in ('OPEN_BUTTON','DIALOG_ESCAPE') and caption==PICKERS[0]) or (purpose=='SAVE_BUTTON' and caption in PICKERS[1:]), 'Picker purpose and caption differ'
        assert scope['className'] == '#32770' and scope['title'] == caption
        assert value['foreground']['hwnd'] == dialog and gui['activeHwnd'] == dialog
        assert gui['focusPid'] == pid and gui['focusRootHwnd'] == dialog and not gui['captureHwnd'] and not gui['menuOwnerHwnd']
        assert isinstance(readiness, dict) and readiness['ready'] is True
        assert (readiness['shellPid'], readiness['documentHwnd'], readiness['dialogHwnd'], readiness['caption']) == (pid, document, dialog, caption)
        assert ancestry[-1]['runtimeId'] == readiness['uiaRootRuntimeId'], 'Original dialog UIA root was replaced'
        index = 0 if purpose == 'DIALOG_ESCAPE' else 1
        frozen = readiness['wrapperBindings'][index]['properties']
        expected = '1148' if caption == PICKERS[0] else '1001'
        assert control['automationId'] == (expected if purpose == 'DIALOG_ESCAPE' else '1')
        assert control['controlType'] == ('Edit' if purpose == 'DIALOG_ESCAPE' else 'Button')
        assert control['runtimeId'] == frozen['runtimeId'] and control['nativeHwnd'] == frozen['nativeHwnd']
        if purpose == 'DIALOG_ESCAPE':
            assert control['nativeHwnd'] > 0, 'Picker Edit requires its exact native control'
    return dict(document={k:doc[k] for k in ('hwnd','pid','threadId','rootHwnd','rectangle')},
                scope={k:scope[k] for k in ('hwnd','pid','threadId','rootHwnd','ownerHwnd','rectangle')},
                control=control, ancestry=ancestry)


def _error(exc): return type(exc).__name__ + ': ' + str(exc)[:1024]


def _original_attachment(record,process,document):
    rows=[row for row in record.get('attachments',[]) if row['hwnd']==document]
    if record.get('windowHwnd')==document and 'parentHwnd' in record:
        rows.append(dict(hwnd=document,parent=record['parentHwnd'],child=record['childHwnd'],officePid=record['officePid']))
    if not rows:return None,None
    bindings=[dict(document=document,parent=row['parent'],child=row['child'],officePid=row['officePid']) for row in rows]
    assert all(row==bindings[0] for row in bindings), 'Original attachment is ambiguous'
    binding=bindings[0]
    assert all(type(v) is int and v>0 for v in binding.values()) and binding['officePid']!=process.pid
    witnesses=[]
    for receipt in record.get('writerModelCompletions',[]):
        candidate=receipt.get('beforeInput',{}).get('bindingBefore',{})
        if candidate.get('suiteHwnd')==document:
            assert (candidate['parentHwnd'],candidate['childHwnd'],candidate['officePid'])==(binding['parent'],binding['child'],binding['officePid'])
            witnesses.append(dict(pid=binding['officePid'],image=candidate['expectedImage'],creationTime=candidate['officeCreationTime']))
    candidate=getattr(process,'opengeul_editor_click_generations',{}).get((binding['parent'],binding['child'],binding['officePid']))
    if candidate is not None:witnesses.append(dict(pid=candidate[0],image=candidate[1],creationTime=candidate[2]))
    assert not witnesses or all(row==witnesses[0] for row in witnesses), 'Available original engine generations differ'
    return binding,witnesses[0] if witnesses else None


def _perform(api, process, document, control, record, *, purpose, dialog=0, caption=None,
             readiness=None, shortcut=None, probe=None, clock=time.monotonic, seconds=5):
    assert type(seconds) in (int,float) and math.isfinite(seconds) and 0 < seconds <= 5
    assert purpose in PURPOSES and (shortcut is None or shortcut in ('CTRL_S','CTRL_SHIFT_S','ESCAPE'))
    if shortcut is None:assert purpose in ('FILE_MENU','SAVE_MENU','OPEN_BUTTON','SAVE_BUTTON')
    elif purpose=='FILE_MENU':assert shortcut in ('CTRL_S','CTRL_SHIFT_S') and caption in PICKERS[1:]
    else:assert purpose=='DIALOG_ESCAPE' and shortcut=='ESCAPE' and caption==PICKERS[0]
    started=clock(); deadline=started+seconds
    value=dict(schemaVersion=1,kind='owned-shell-control-action',success=False,purpose=purpose,
        documentHwnd=document,dialogHwnd=dialog,caption=caption,shortcut=shortcut,
        startedAt=started,deadline=deadline,clickAttempts=0,pointerMoveAttempts=0,
        inputCallAttempts=0,requestedInputs=0,insertedInputs=None,
        nativeInsertionCountVerified=False,atomicRecipientDeliveryProved=False,dpiScope={})
    record.setdefault('ownedControlActions',[]).append(value)
    output=stem=None; primary=None; engine_handle=None; original_engine=None
    def budget(): assert clock() < deadline, 'Owned control action deadline expired'
    def retain(phase):
        raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
        assert len(raw)<=CAP, 'Control action receipt exceeds bound'
        with (output/(stem+'-'+phase+'.json')).open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    try:
        budget(); output=Path(process.opengeul_evidence_output); suite=Path(process.opengeul_suite_root)
        assert output.is_absolute() and output.is_dir() and suite.is_absolute()
        for part in (output,*output.parents): assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)()
        name=process.opengeul_evidence_case; assert re.fullmatch('[A-Za-z0-9_-]{1,100}',name)
        sequence=getattr(process,'opengeul_control_sequence',0); assert type(sequence) is int and 0<=sequence<128
        process.opengeul_control_sequence=sequence+1; stem=name+'-owned-control-'+format(sequence,'03d'); value['receiptStem']=stem
        expected=str((suite/'OpenGeul.Office.exe').resolve())
        assert isinstance(process.args,(list,tuple)) and str(Path(process.args[0]).resolve())==expected
        if probe is None and purpose=='SAVE_MENU':
            from owned_save_menu import NativeSaveMenuProbe
            probe=NativeSaveMenuProbe(deadline,clock)
        probe=probe if probe is not None else NativeControlProbe(deadline,clock)
        budget(); original=probe.process_snapshot(process)
        assert (original['pid'],original['handleValue'],original['image'],original['waitResult'])==(process.pid,int(process._handle),expected,258)
        _integer(original['creationTime'])
        binding=tuple(original[k] for k in ('pid','handleValue','image','creationTime','waitResult'))
        assert getattr(process,'opengeul_control_binding',binding)==binding, 'Original control Popen generation changed'
        assert getattr(process,'opengeul_activation_binding',binding)==binding, 'Activation/control Popen generation differs'
        process.opengeul_control_binding=binding; value['originalProcess']=original
        attachment=witness=None
        if purpose=='SAVE_MENU' or purpose=='FILE_MENU' and shortcut is not None:
            attachment,witness=_original_attachment(record,process,document)
            assert attachment is not None, 'Host-menu shortcut requires its original attachment'
        if purpose=='SAVE_MENU':
            from owned_save_menu import file_click_anchor, home_engine_witness, require_save_menu_target
            value['saveMenuFileAnchor']=file_click_anchor(record,document,original,started)
            home_witness,basis=home_engine_witness(record,document,attachment)
            assert witness is None or home_witness is None or witness==home_witness, 'Existing original engine witnesses differ'
            witness=home_witness if home_witness is not None else witness
            value['engineAdmissionBasis']=basis
        value.update(originalAttachment=attachment,originalEngineWitness=witness,priorEngineGenerationWitnessJoined=False)
        if attachment is not None:
            engine_handle=probe.open_engine(attachment['officePid']);value['engineHandle']=engine_handle
            budget();original_engine=probe.engine_snapshot(engine_handle)
            assert original_engine['pid']==attachment['officePid'] and original_engine['waitResult']==258
            assert str(Path(original_engine['image']).resolve()).casefold()==str((suite/'Office/program/soffice.bin').resolve()).casefold(), 'Host attachment is not the packaged engine'
            assert type(original_engine['creationTime']) is int and original_engine['creationTime']>=original['creationTime'], 'Engine predates original Suite shell'
            if witness is not None:
                _integer(witness['creationTime'])
                assert original_engine['pid']==witness['pid'] and original_engine['image'].casefold()==witness['image'].casefold() and original_engine['creationTime']==witness['creationTime'], 'Earlier original engine generation differs'
            value.update(originalEngine=original_engine,engineAdmittedAt=clock(),priorEngineGenerationWitnessJoined=witness is not None)
            from counted_editor_shortcuts import join_shortcut_generation,admit_shortcut_generation
            value['priorShortcutGeneration']=join_shortcut_generation(process,attachment['parent'],attachment['child'],original_engine)
        if 'originalShell' in record:
            shell=record['originalShell']; assert (shell['pid'],shell['handleValue'],shell['nativeCreation']['fileTime'])==(process.pid,int(process._handle),original['creationTime'])
        def original_context():
            budget(); assert probe.process_snapshot(process)==original, 'Original control process changed'
            if engine_handle is not None:
                assert probe.engine_snapshot(engine_handle)==original_engine, 'Original attachment engine generation changed'
                join_shortcut_generation(process,attachment['parent'],attachment['child'],original_engine)
            if attachment is not None:
                value['lastAttachmentObservation']=probe.attachment_snapshot(attachment)
                assert value['lastAttachmentObservation']['binding']==attachment and value['lastAttachmentObservation']['valid'] is True, 'Original attachment ancestry changed'
        def observe():
            original_context()
            budget()
            if purpose=='FILE_MENU' and shortcut is None:
                snap=probe.target_snapshot(api,document,control,dialog,purpose,operation='pointer')
            else:
                snap=probe.target_snapshot(api,document,control,dialog,purpose)
            snap['shellCreationTime']=original['creationTime']
            snap['foregroundProcessGeneration']=(original if snap['foreground']['pid']==process.pid else None)
            value['lastObservation']=snap
            budget()
            if purpose=='SAVE_MENU':
                anchor=require_save_menu_target(snap,document,process.pid,caption,value['saveMenuFileAnchor'])
            else:
                anchor=_target(snap,purpose,document,process.pid,dialog,caption,readiness,
                               operation='pointer' if shortcut is None else 'keyboard')
            return snap,anchor
        if shortcut is None:
            budget(); probe.enter_dpi(value['dpiScope']); assert value['dpiScope']['verified'] is True
        if purpose=='SAVE_MENU':
            original_context();budget()
            control=probe.discover_save_menu(api,document,control,record,value)
            budget();original_context()
        before,anchor=observe(); value['before']=before
        if engine_handle is not None:
            value['shortcutGenerationAdmission']=admit_shortcut_generation(process,attachment['parent'],attachment['child'],original_engine,value['engineAdmittedAt'])
        if shortcut is None:
            rect=before['control']['rectangle']; point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
            value['chosenPhysicalPoint']=point
            def hit():
                target_scope=before['scope']['hwnd'] if purpose=='SAVE_MENU' else dialog or document
                budget(); row=probe.point_snapshot(target_scope,point,control)
                assert row['point']==point and row['pid']==process.pid and row['rootHwnd']==target_scope
                assert row['withinControl'] is True and row['uiaMatches'] is True, 'Measured control point is obstructed'
                return row
            value['beforeMoveHit']=hit(); value['pointerMoveIntent']=True; retain('pointer-intent')
            fresh,observed=observe(); assert observed==anchor, 'Control changed during pointer intent retention'
            value['afterMoveIntent']=fresh; value['afterMoveIntentHit']=hit()
            budget(); probe.move(point,value); budget()
            assert value['pointerReadback']==point, 'Physical control cursor readback differs'
            current,observed=observe(); assert observed==anchor, 'Owned control identity or geometry changed'
            value['beforeClick']=current; value['beforeClickHit']=hit()
            value.update(clickAttempts=1,requestedInputs=2); retain('click-intent')
            fresh,observed=observe(); assert observed==anchor, 'Control changed during click intent retention'
            value['afterClickIntent']=fresh; value['afterClickIntentHit']=hit(); budget()
            probe.click(value); budget()
            assert value['clickCompleted'] is True and value['insertedInputs']==2
            value['nativeInsertionCountVerified']=True
        else:
            assert (purpose=='FILE_MENU' and shortcut in ('CTRL_S','CTRL_SHIFT_S')) or (purpose=='DIALOG_ESCAPE' and shortcut=='ESCAPE')
            keyboard=probe.keyboard_snapshot(before['gui']['threadId']); value['keyboardBefore']=keyboard
            assert keyboard['targetLayout']==keyboard['currentThreadLayout']==0x04090409, 'Exact US layout required for counted host shortcut'
            assert keyboard['keysDown']==[], 'Host shortcut cannot repair held physical keys'
            events,payload=probe.keyboard_plan(shortcut); value.update(events=events,requestedInputs=len(events))
            value['releasePlans']=[dict(inserted=n,events=probe.owned_release_events(events,n)) for n in range(len(events)+1)]
            current,observed=observe(); assert observed==anchor, 'Shortcut target changed before input'
            assert probe.keyboard_snapshot(before['gui']['threadId'])==keyboard, 'Host keyboard state changed'
            value['beforeInput']=current; value['inputIntent']=True; retain('input-intent')
            fresh,observed=observe(); assert observed==anchor, 'Shortcut target changed during intent retention'
            assert probe.keyboard_snapshot(before['gui']['threadId'])==keyboard, 'Host keyboard state changed during intent retention'
            value['afterInputIntent']=fresh; budget()
            value['inputCallAttempts']=1; value['inputCountBasis']='native adapter entered; OS entry/return unknown'
            inserted=probe.send(payload)
            assert type(inserted) is int and 0<=inserted<=len(events), 'Invalid native insertion count'
            value.update(insertedInputs=inserted,inputCountBasis='SendInput return value')
            if inserted<len(events):
                partial=AssertionError('Counted host shortcut had partial native insertion')
                owned=value['releasePlans'][inserted]['events']
                if owned:
                    recovery=dict(events=owned,requested=len(owned),inserted=None);value['ownedKeyRelease']=recovery
                    try: retain('release-intent')
                    except BaseException as later: recovery['retentionError']=_error(later)
                    try:
                        released=probe.release(owned)
                        assert type(released) is int and 0<=released<=len(owned), 'Invalid owned key release count'
                        recovery['inserted']=released
                        assert released==len(owned), 'Owned key release had partial native insertion'
                    except BaseException as later: recovery['error']=_error(later)
                raise partial
            budget(); value['nativeInsertionCountVerified']=True
        original_context()
        value['after']={}
        value['after']=probe.transition_snapshot(api,process,document,dialog,caption,purpose,control,
            context=dict(document=anchor['document'],scope=anchor['scope'],originalProcess=original,
                         attachment=attachment),evidence=value['after'])
        original_context()
        budget(); assert value['after']['accepted'] is True, 'Unexpected control transition after input'
        value['success']=True
    except BaseException as exc:
        primary=exc; value.update(success=False,error=_error(exc)); raise
    finally:
        if engine_handle is not None:
            try:
                closed=probe.close_engine(engine_handle);value['engineHandleClosed']=closed
                assert closed is True, 'Closing original engine witness HANDLE failed'
            except BaseException as exc:
                value.update(success=False,engineHandleCloseError=_error(exc))
                if primary is None:primary=exc
        if probe is not None and value['dpiScope'].get('previousContext'):
            try:
                probe.restore_dpi(value['dpiScope']); assert value['dpiScope']['restored'] is True
            except BaseException as exc:
                value.update(success=False,dpiRestoreError=_error(exc))
                if primary is None: primary=exc
        value['finishedAt']=clock()
        if value['success'] and (value['finishedAt']>=deadline if purpose=='SAVE_MENU' else value['finishedAt']>deadline):
            value.update(success=False,error='Owned control completed after deadline')
            if primary is None: primary=AssertionError(value['error'])
        if output is not None and stem is not None:
            try: retain('result')
            except BaseException as exc:
                value.update(success=False,retentionError=_error(exc))
                if primary is None: primary=exc
        if primary is not None and not sys.exc_info()[0]: raise primary
    return value


def click_owned_control(api,process,document,control,record,*,purpose,dialog=0,caption=None,readiness=None,**options):
    return _perform(api,process,document,control,record,purpose=purpose,dialog=dialog,caption=caption,readiness=readiness,**options)


def send_host_menu_shortcut(api,process,document,control,record,*,shortcut,caption,**options):
    return _perform(api,process,document,control,record,purpose='FILE_MENU',shortcut=shortcut,caption=caption,**options)


def send_owned_dialog_escape(api,process,document,control,record,*,dialog,caption,readiness,**options):
    return _perform(api,process,document,control,record,purpose='DIALOG_ESCAPE',dialog=dialog,caption=caption,
                    readiness=readiness,shortcut='ESCAPE',**options)


class GuiThreadInfo(C.Structure):
    _fields_=[('cbSize',C.c_uint32),('flags',C.c_uint32),('active',C.c_void_p),('focus',C.c_void_p),
              ('capture',C.c_void_p),('menuOwner',C.c_void_p),('moveSize',C.c_void_p),('caret',C.c_void_p),('rectangle',Rect)]


class NativeControlProbe(NativeActivationProbe):
    def __init__(self,deadline,clock,**libraries):
        super().__init__(deadline,clock,**libraries)
        # Initialize the UIA backend before a caller enters its PMv2 scope.
        from pywinauto import Desktop
        from pywinauto.uia_defines import IUIA
        self.desktop=self._call(lambda:Desktop(backend='uia'));self.uia=self._call(IUIA)
        H,D,B=C.c_void_p,C.c_uint32,C.c_int32
        for name,args,result in [('GetWindow',(H,D),H),('GetWindowTextW',(H,C.c_wchar_p,B),B),
            ('GetClassNameW',(H,C.c_wchar_p,B),B),('IsChild',(H,H),B),('GetPropW',(H,C.c_wchar_p),H),('GetGUIThreadInfo',(D,C.POINTER(GuiThreadInfo)),B)]:
            f=getattr(self.user,name);f.argtypes,f.restype=args,result
        self.keyboard_probe=None
    def _keyboard(self):
        if self.keyboard_probe is None:
            from counted_editor_shortcuts import NativeShortcutProbe
            self.keyboard_probe=NativeShortcutProbe(self.deadline,self.clock)
        return self.keyboard_probe
    def keyboard_snapshot(self,thread):return self._keyboard().keyboard_snapshot(thread)
    def keyboard_plan(self,shortcut):
        from counted_editor_shortcuts import shortcut_events,input_buffer
        events=shortcut_events(shortcut);return events,input_buffer(events)
    def send(self,payload):return self._keyboard().send(payload)
    def open_engine(self,pid):return self._keyboard().open_engine(pid)
    def engine_snapshot(self,handle):return self._keyboard().engine_snapshot(handle)
    def close_engine(self,handle):return self._keyboard().close_engine(handle)
    def owned_release_events(self,events,inserted):
        from counted_editor_shortcuts import owned_release_events
        return owned_release_events(events,inserted)
    def release(self,events):
        from counted_editor_shortcuts import input_buffer
        return self._keyboard().release(input_buffer(events))
    def _window(self,hwnd):
        row=self.window_snapshot(hwnd);title=C.create_unicode_buffer(257);kind=C.create_unicode_buffer(257)
        count=int(self._call(self.user.GetWindowTextW,hwnd,title,len(title)));assert count<256, 'Window title exceeds retained bound'
        size=int(self._call(self.user.GetClassNameW,hwnd,kind,len(kind)));assert 0<size<256
        row.update(ownerHwnd=int(self._call(self.user.GetWindow,hwnd,4) or 0),title=title.value,className=kind.value)
        return row
    def _owner_chain(self,hwnd,document):
        result=[]
        while hwnd:
            assert len(result)<16 and hwnd not in result, 'Native owner chain exceeded bound'
            result.append(hwnd)
            if hwnd==document:break
            hwnd=int(self._call(self.user.GetWindow,hwnd,4) or 0)
        return result
    def _raw(self,element):
        def get(name):return self._call(lambda:getattr(element,name))
        raw=get('CurrentNativeWindowHandle')
        # UIA_HWND is void*: a successful comtypes null result is None.
        # No exception, arbitrary falsy value or integer-like object is a null.
        assert raw is None or type(raw) is int and -(2**31)<=raw<2**32, \
            'Invalid CurrentNativeWindowHandle: type='+type(raw).__name__+' value='+repr(raw)[:160]
        handle=0 if raw is None else raw&0xffffffff
        box=get('CurrentBoundingRectangle');rectangle=[int(getattr(box,k)) for k in ('left','top','right','bottom')]
        kinds={50000:'Button',50004:'Edit',50011:'MenuItem',50032:'Window',50010:'MenuBar'}
        kind=int(get('CurrentControlType'));runtime=list(self._call(element.GetRuntimeId));name=str(get('CurrentName'))
        automation=str(get('CurrentAutomationId'))
        assert len(name)<=256 and len(automation)<=256 and 0<len(runtime)<=64
        assert all(type(v) is int and -(2**31)<=v<2**31 for v in runtime)
        return dict(runtimeId=runtime,pid=int(get('CurrentProcessId')),nativeHwnd=handle,
                    nativeHwndRaw=raw,nativeHwndRawType=type(raw).__name__,
                    automationId=automation,controlType=kinds.get(kind,str(kind)),name=name,
                    visible=not bool(get('CurrentIsOffscreen')),enabled=bool(get('CurrentIsEnabled')),rectangle=rectangle)
    def _focused_identity(self,element):
        """Only the four identity properties consumed by the focused walk."""
        def get(name):return self._call(lambda:getattr(element,name))
        def invalid(field,value,detail):
            raise AssertionError('Invalid focused identity '+field+': type='+type(value).__name__[:64]+' '+detail)
        raw=get('CurrentNativeWindowHandle')
        if not (raw is None or type(raw) is int and -(2**31)<=raw<2**32):
            invalid('nativeHwnd',raw,'expected null or signed32/uint32')
        pid=get('CurrentProcessId')
        if not (type(pid) is int and 0<pid<2**32):
            invalid('pid',pid,'expected positive DWORD')
        kind=get('CurrentControlType')
        if not (type(kind) is int and 0<kind<2**31):
            invalid('controlType',kind,'expected positive signed32 CONTROLTYPEID')
        runtime=self._call(lambda:element.GetRuntimeId())
        if type(runtime) not in (list,tuple):
            invalid('runtimeId',runtime,'expected bounded list/tuple')
        if not 0<len(runtime)<=64:
            invalid('runtimeId',runtime,'length='+str(len(runtime))+' expected1..64')
        for index,value in enumerate(runtime):
            if not (type(value) is int and -(2**31)<=value<2**31):
                invalid('runtimeId['+str(index)+']',value,'expected signed32')
        kinds={50000:'Button',50004:'Edit',50011:'MenuItem',50032:'Window',50010:'MenuBar'}
        return dict(runtimeId=list(runtime),pid=pid,nativeHwnd=0 if raw is None else raw&0xffffffff,
                    controlType=kinds.get(kind,str(kind)))
    def native_focus(self,thread):
        state=GuiThreadInfo(cbSize=C.sizeof(GuiThreadInfo));self._required(self._call(self.user.GetGUIThreadInfo,thread,C.byref(state)),'GetGUIThreadInfo(original control thread)')
        focus=int(state.focus or 0);pid=C.c_uint32()
        if focus:self._required(self._call(self.user.GetWindowThreadProcessId,focus,C.byref(pid)),'Owned control focus PID')
        return dict(threadId=thread,activeHwnd=int(state.active or 0),focusHwnd=focus,focusPid=int(pid.value),
            focusRootHwnd=int(self._call(self.user.GetAncestor,focus,2) or 0) if focus else 0,
            captureHwnd=int(state.capture or 0),menuOwnerHwnd=int(state.menuOwner or 0),flags=int(state.flags))
    def attachment_snapshot(self,binding):
        rows={}
        for role in ('document','parent','child'):
            hwnd=binding[role];self._required(self._call(self.user.IsWindow,hwnd),'Original attachment '+role)
            pid=C.c_uint32();thread=int(self._call(self.user.GetWindowThreadProcessId,hwnd,C.byref(pid)))
            rows[role]=dict(hwnd=hwnd,pid=int(pid.value),threadId=thread,rootHwnd=int(self._call(self.user.GetAncestor,hwnd,2) or 0))
        doc,parent,child=(binding[k] for k in ('document','parent','child'))
        exported=[int(self._call(self.user.GetPropW,doc,'OpenGeul.Office.'+key+'Hwnd') or 0) for key in ('Parent','Child')]
        gui=self.native_focus(rows['document']['threadId']);focus=gui['focusHwnd']
        valid=(rows['parent']['pid']==rows['document']['pid'] and rows['child']['pid']==binding['officePid']
            and all(row['threadId']>0 and row['rootHwnd']==doc for row in rows.values()) and exported==[parent,child]
            and bool(self._call(self.user.IsChild,doc,parent)) and bool(self._call(self.user.IsChild,parent,child)))
        return dict(binding=dict(binding),windows=rows,exported=exported,valid=bool(valid),
            focusUnderOriginalChild=bool(focus and (focus==child or self._call(self.user.IsChild,child,focus))))
    def target_snapshot(self,api,document,control,dialog,purpose,*,operation='keyboard'):
        assert operation in ('pointer','keyboard'), 'Unsupported owned control snapshot operation'
        uia=self.uia;element=self._call(lambda:control.element_info._element)
        scope=dialog or document;root=self._call(lambda:self.desktop.window(handle=scope).wrapper_object().element_info._element)
        props=self._raw(element);ancestry=[];cursor=element
        for _ in range(32):
            row=self._raw(cursor);ancestry.append({k:row[k] for k in ('runtimeId','pid','nativeHwnd','controlType')})
            if self._call(uia.iuia.CompareElements,cursor,root):break
            cursor=self._call(uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor, 'Control ancestry ended outside original scope'
        else:raise AssertionError('Control UIA ancestry exceeded bound')
        doc=self._window(document);scope_row=self._window(scope);fg=self.foreground();foreground=self._window(fg)
        gui=self.native_focus(scope_row['threadId']);focus=gui['focusHwnd']
        focused=[];focus_basis='unqueried-original-file-pointer'
        # This exact _target pointer branch uses native focus and the measured
        # File recipient. It does not consume the currently focused UIA tree.
        if not (operation=='pointer' and purpose=='FILE_MENU' and not dialog and foreground['hwnd']==document):
            focus_basis='strict-focused-identity-walk'
            cursor=self._call(uia.iuia.GetFocusedElement)
            for _ in range(32):
                if not cursor:break
                row=self._focused_identity(cursor);focused.append(row)
                if self._call(uia.iuia.CompareElements,cursor,root):break
                cursor=self._call(uia.iuia.ControlViewWalker.GetParentElement,cursor)
        menu_handles=[row['nativeHwnd'] for row in ancestry if row['controlType'] in ('MenuItem','MenuBar') and row['nativeHwnd']]
        under=any(focus==handle or bool(self._call(self.user.IsChild,handle,focus)) for handle in menu_handles) if focus else False
        return dict(document=doc,scope=scope_row,control=props,ancestry=ancestry,gui=gui,foreground=foreground,
                    foregroundOwnerChain=self._owner_chain(fg,document),focusAncestry=focused,
                    focusAncestryBasis=focus_basis,nativeFocusUnderMenu=under)
    def point_snapshot(self,scope,point,control):
        hit=int(self._call(self.user.WindowFromPhysicalPoint,Point(*point)) or 0);pid=C.c_uint32()
        if hit:self._required(self._call(self.user.GetWindowThreadProcessId,hit,C.byref(pid)),'Physical control hit PID')
        target=self._call(lambda:control.element_info._element);handle=self._raw(target)['nativeHwnd']
        actual=self._call(lambda:self.desktop.from_point(*point).element_info._element)
        match=bool(self._call(self.uia.iuia.CompareElements,target,actual))
        return dict(point=list(point),hitHwnd=hit,pid=int(pid.value),rootHwnd=int(self._call(self.user.GetAncestor,hit,2) or 0) if hit else 0,
                    withinControl=bool(hit and (hit==handle or handle and self._call(self.user.IsChild,handle,hit) or not handle and match)),uiaMatches=match)
    def transition_snapshot(self,api,process,document,dialog,caption,purpose,control,*,context=None,evidence=None):
        if dialog:
            # Input may tear down a child UIA provider before IsWindow(dialog)
            # becomes false. Observe the native original, never that child.
            assert context is not None and 'originalProcess' in context and 'scope' in context
            result=evidence if evidence is not None else {}
            result.update(accepted=False,dialogObservationCount=0)
            def original():
                snapshot=self._call(self.process_snapshot,process);result['lastOriginalProcess']=snapshot
                assert snapshot==context['originalProcess'], 'Original dialog process generation changed'
                alive=bool(self._call(self.user.IsWindow,document));result['originalDocumentAlive']=alive
                assert alive, 'Original control document disappeared'
                row=self._call(self._window,document);result['lastOriginalDocument']=row
                assert row['pid']==process.pid and all(row[k]==context['document'][k]
                    for k in ('hwnd','pid','threadId','rootHwnd')), 'Original document native identity changed'
            while True:
                original();result['dialogObservationCount']+=1
                alive=bool(self._call(self.user.IsWindow,dialog));result['originalDialogAlive']=alive
                if not alive:
                    original()
                    assert self.clock()<self.deadline, 'Owned dialog transition deadline expired'
                    result.update(accepted=True,transition='original-owned-dialog-destroyed');return result
                row=self._call(self._window,dialog);result['lastLiveDialog']=row
                frozen=context['scope']
                assert all(row[k]==frozen[k] for k in ('hwnd','pid','threadId','rootHwnd','ownerHwnd')) \
                    and row['hwnd']==dialog and row['pid']==process.pid and row['ownerHwnd']==document \
                    and row['className']=='#32770' and row['title']==caption, 'Original native dialog identity changed'
                remaining=self.deadline-self.clock()
                assert remaining>0, 'Owned dialog transition deadline expired'
                self._call(time.sleep,min(.01,remaining))
        doc_alive=bool(self._call(self.user.IsWindow,document));dialog_alive=bool(dialog and self._call(self.user.IsWindow,dialog))
        result=evidence if evidence is not None else {}
        result.update(originalDocumentAlive=doc_alive,originalDialogAlive=dialog_alive,accepted=False)
        doc=self._window(document)
        assert doc_alive and doc['pid']==process.pid, 'Original control document disappeared'
        if context is not None:
            assert all(doc[k]==context['document'][k] for k in ('hwnd','pid','threadId','rootHwnd')), 'Original document native identity changed'
        # A valid modal may invalidate the old File wrapper. Recognize the
        # exact declared transition from native identity before touching it.
        if not dialog and caption in PICKERS[1:]:
            fg=self._window(self.foreground());result['foreground']=fg
            if fg['hwnd']!=document and fg['ownerHwnd']==document and fg['pid']==process.pid and fg['className']=='#32770' and fg['title']==caption:
                from pywinauto import Desktop
                element=self._call(lambda:Desktop(backend='uia').window(handle=fg['hwnd']).wrapper_object().element_info._element)
                info=self._raw(element)
                assert info['nativeHwnd']==fg['hwnd'] and info['pid']==process.pid and info['runtimeId']
                assert info['controlType']=='Window' and info['name']==caption and info['visible'] is True and info['enabled'] is True
                result['newPicker']=info
                result.update(accepted=True,transition='exact-owned-save-picker');return result
            if fg['hwnd']==document and context is not None and context.get('attachment') is not None:
                gui=self.native_focus(doc['threadId']);attachment=context['attachment']
                if gui['focusPid']==attachment['officePid']:
                    observed=self.attachment_snapshot(attachment);result.update(gui=gui,attachment=observed)
                    assert observed['valid'] is True and observed['binding']==attachment and observed['focusUnderOriginalChild'] is True, 'Save returned to another attachment'
                    assert gui['activeHwnd']==document and gui['focusRootHwnd']==document and not gui['captureHwnd'] and not gui['menuOwnerHwnd'], 'Consumed menu focus escaped original document'
                    result.update(accepted=True,transition='consumed-menu-original-editor-return');return result
        if purpose=='FILE_MENU' and caption is None:
            snap=self.target_snapshot(api,document,control,dialog,purpose,operation='pointer')
        else:
            snap=self.target_snapshot(api,document,control,dialog,purpose)
        result['native']=snap
        if purpose=='FILE_MENU' and not dialog and caption in PICKERS[1:]:
            foreground=snap['foreground']
            if foreground['hwnd']!=document and foreground['className']=='#32770' and foreground['title']==caption:
                # The modal can appear after the first foreground read. The
                # old File target is no longer an enabled input recipient.
                # Verify the declared transition, never relax its pre-input guard.
                assert context is not None and context.get('originalProcess') is not None
                def verify_picker(row):
                    doc,fg,gui=(row[key] for key in ('document','foreground','gui'))
                    _window(doc,document,process.pid,enabled=False)
                    assert all(doc[key]==context['document'][key] for key in ('hwnd','pid','threadId','rootHwnd')), 'Original picker document identity changed'
                    assert doc['enabled'] is False, 'Owned modal did not disable its original document'
                    _window(fg,fg['hwnd'],process.pid)
                    assert fg['hwnd']!=document and fg['ownerHwnd']==document and fg['threadId']==doc['threadId'], 'New picker owner or thread differs'
                    assert fg['className']=='#32770' and fg['title']==caption, 'Declared picker identity changed'
                    assert gui['threadId']==doc['threadId'] and gui['activeHwnd']==fg['hwnd'], 'Declared picker is not active on the original thread'
                    assert gui['focusHwnd']>0 and gui['focusPid']==process.pid and gui['focusRootHwnd']==fg['hwnd'], 'Declared picker focus escaped'
                    assert type(gui['flags']) is int and not gui['flags'] & 0x1e and not gui['captureHwnd'] and not gui['menuOwnerHwnd'], 'Declared picker has menu or capture activity'
                verify_picker(snap)
                result['pickerProcessBefore']=self._call(self.process_snapshot,process)
                assert result['pickerProcessBefore']==context['originalProcess'], 'Original picker process generation changed'
                from pywinauto import Desktop
                element=self._call(lambda:Desktop(backend='uia').window(handle=foreground['hwnd']).wrapper_object().element_info._element)
                info=self._raw(element);result['newPicker']=info
                assert info['nativeHwnd']==foreground['hwnd'] and info['pid']==process.pid and info['runtimeId']
                assert info['controlType']=='Window' and info['name']==caption and info['visible'] is True and info['enabled'] is True
                doc=self._call(self._window,document)
                fg=self._call(self._window,self._call(self.foreground))
                after=dict(document=doc,foreground=fg,gui=self._call(self.native_focus,doc['threadId']))
                result['pickerNativeAfter']=after
                verify_picker(after)
                assert all(fg[key]==foreground[key] for key in ('hwnd','pid','threadId','rootHwnd','ownerHwnd')), 'Declared picker was replaced during UIA verification'
                result['pickerProcessAfter']=self._call(self.process_snapshot,process)
                assert result['pickerProcessAfter']==context['originalProcess'], 'Original picker process generation changed'
                result.update(accepted=True,transition='exact-owned-save-picker');return result
        if purpose=='FILE_MENU':_target(snap,purpose,document,process.pid,dialog,caption,None,
                                     operation='keyboard' if caption else 'pointer')
        else:
            # Pre-action exact UIA/readiness identity is retained. If still
            # alive, require the original native dialog foreground and owner.
            assert snap['scope']['ownerHwnd']==document and snap['scope']['title']==caption and snap['scope']['className']=='#32770'
            assert snap['foreground']['hwnd']==dialog and snap['gui']['focusRootHwnd']==dialog
        result.update(accepted=True,transition='same-original-control-scope');return result
