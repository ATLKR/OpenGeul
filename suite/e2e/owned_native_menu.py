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
STATUS_PROPERTY='OpenGeul.Office.NativeMenuStatusV1'
LABELS={'file':('파일','File'),'save':('저장','Save'),
    'saveAs':('다른 이름으로 저장…','Save As…'),'open':('열기…','Open…'),
    'close':('닫기','Close'),'new':('새로 만들기','새 문서','New'),
    'new-writer':('텍스트 문서','Text Document'),'new-calc':('스프레드시트','Spreadsheet'),
    'new-impress':('프레젠테이션','Presentation'),'new-draw':('그리기','Drawing'),
    'new-math':('수식','Formula'),'new-base':('데이터베이스','Database'),
    'new-hwp':('OpenGeul 한글 시작',),'home':('OpenGeul 시작 화면',),
    'exit':('끝내기','종료','Exit','Quit'),
    'printPreview':('인쇄 미리보기','Print Preview'),
    'saveAll':('모두 저장','모든 문서 저장','Save All'),
    'saveCopy':('복사본 저장…','복사본 저장','Save a Copy…','Save a Copy')}
COMMANDS=tuple(k for k in LABELS if k not in ('file','new','saveAll','saveCopy'))
GESTURES=('open-escape','open-outside','keyboard-escape','disabled-saveAll','disabled-saveCopy','core-commands')
CORE_COMMANDS=('new-hwp','home','new','open','save','saveAs','close')
KEY_COUNTS={'ALT_F':4,'DOWN':2,'ESCAPE':2}
IDENTITY_METHOD='retained-uia-comparison'
EDIT_CONTRAST=('편집','Edit')
IDENTITY_ROLES=('file','bar','peer','contrast-edit')+tuple('target:'+name for name in LABELS if name!='file')


class NativeMenuPending(AssertionError):pass


def _menu_key_events(shortcut):
    plans={'ALT_F':((0x38,0),(0x21,0)),'DOWN':((0x50,1),),'ESCAPE':((0x01,0),)}
    assert type(shortcut) is str and shortcut in plans, 'Unknown native menu shortcut'
    keys=plans[shortcut]
    return ([dict(vk=0,scan=scan,flags=8|extended) for scan,extended in keys]
        +[dict(vk=0,scan=scan,flags=10|extended) for scan,extended in reversed(keys)])


def _menu_release_events(shortcut,inserted):
    # Admit only this local enum's fixed plan before using the shared pure leaf.
    # The public counted-editor PRESETS allowlist remains unchanged.
    from counted_editor_shortcuts import _owned_release
    events=_menu_key_events(shortcut)
    assert type(inserted) is int and 0<=inserted<=len(events), 'Unknown native menu inserted prefix'
    return _owned_release(events,inserted)


def decode_status_sequence(raw):
    """Decode only the opt-in shell's positive, versioned numeric counters."""
    assert type(raw) is int and 0<raw<1<<63 and raw>>56==1, 'Invalid native status sequence version'
    mask=(1<<28)-1;started=(raw>>28)&mask;completed=raw&mask
    assert completed<=started<=completed+1, 'Invalid native status sequence ordering'
    return dict(version=1,started=started,completed=completed)


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


def _scope_targets(scope):
    operation=scope['operation']
    if scope['gesture']:
        if operation=='core-commands':return {'file',*CORE_COMMANDS}
        if operation.startswith('disabled-'):return {'file','save',operation[len('disabled-'):]}
        return {'file','save'}
    return {'file',operation}|({'new'} if operation.startswith('new-') and operation!='new-hwp' else set())


def _target_role(target):return 'file' if target=='file' else 'target:'+target


def _scope_anchor(scope,binding,shell_pid):
    assert type(scope) is dict and set(scope)=={'version','binding','shellPid','shellCreationTime',
        'officeCreationTime','startedAt','deadline','operation','gesture'}
    assert type(scope['version']) is int and scope['version']==1 and scope['binding']==binding
    assert type(scope['shellPid']) is int and scope['shellPid']==shell_pid
    for key in ('shellCreationTime','officeCreationTime'):_int(scope[key])
    assert scope['officeCreationTime']>=scope['shellCreationTime']
    assert type(scope['gesture']) is bool and scope['operation'] in (GESTURES if scope['gesture'] else COMMANDS)
    start,end=scope['startedAt'],scope['deadline']
    assert all(type(n) in (int,float) and math.isfinite(n) for n in (start,end)) and start<end<=start+5
    return (tuple(binding[k] for k in ('document','parent','child','officePid')),shell_pid,
        scope['shellCreationTime'],scope['officeCreationTime'],start,end,scope['operation'],scope['gesture'])


def _comparison_proof(proof,binding,shell_pid,target):
    assert type(proof) is dict and set(proof)=={'scope','roles','positive','negative'}
    scope=proof['scope'];anchor=_scope_anchor(scope,binding,shell_pid)
    assert target in _scope_targets(scope)
    roles=proof['roles'];assert type(roles) is list and 4<=len(roles)<=4+len(LABELS)
    assert len(set(roles))==len(roles)
    allowed={'file','bar','peer','contrast-edit'}|{_target_role(name) for name in _scope_targets(scope)}
    assert set(roles)<=allowed and {'file','bar','peer','contrast-edit',_target_role(target)}<=set(roles)
    assert type(proof['positive']) is dict and set(proof['positive'])==set(roles)
    assert all(value is True for value in proof['positive'].values())
    expected={(left,right) for i,left in enumerate(roles) for right in roles[i+1:]}
    negative=proof['negative'];assert type(negative) is list and len(negative)==len(expected)
    assert all(type(row) is list and len(row)==3 and row[2] is False for row in negative)
    assert len({(row[0],row[1]) for row in negative})==len(negative)
    assert {(row[0],row[1]) for row in negative}==expected
    return anchor


def _element_anchor(row,proof,binding,shell_pid):
    runtime=row['runtimeId']
    assert type(runtime) is list and len(runtime)<=64
    assert all(type(n) is int and -(2**31)<=n<2**31 for n in runtime)
    if runtime:
        assert row.get('runtimeIdAvailable',True) is True
        return ('runtime-id',tuple(runtime))
    assert row.get('runtimeIdAvailable') is False and type(proof) is dict
    identity=row['identity'];assert set(identity)=={'method','scope','role'} and identity['method']==IDENTITY_METHOD
    assert identity['scope']==proof['scope'] and identity['role'] in proof['roles'] and identity['role']!='contrast-edit'
    observation=row['runtimeObservation']
    assert observation['rawTypeCode'] in (1,2) and observation['length']==0
    assert observation['empty'] is observation['signed32Valid'] is observation['callSucceeded'] is True
    assert observation['elementTypeCodes']==[] and observation['declaration']['verified'] is True
    assert observation['versionObserved'] is True and type(observation['versionTuple']) is list and len(observation['versionTuple'])==3
    assert all(type(n) is int and 0<=n<=65535 for n in observation['versionTuple'])
    declaration=observation['declaration']
    assert all(declaration[key] is True for key in ('interfaceKnown','methodUnique','hresultDeclared',
        'singleOutArgument','outFlag','retvalFlag','exactFlags','safeArrayInt32'))
    assert declaration['hresultValueObserved'] is declaration['safeArrayPointerObserved'] is declaration['safeArrayDimensionsObserved'] is False
    return (IDENTITY_METHOD,_scope_anchor(proof['scope'],binding,shell_pid),identity['role'])


def _hit_identity(hit,snapshot,target):
    if 'identityProof' not in snapshot:return
    proof=hit['identityProof'];scope=snapshot['identityProof']['scope'];role=_target_role(target)
    assert proof['scope']==scope and proof['role']==role
    assert proof['targetEqualsRetained'] is proof['hitEqualsRetained'] is True
    different=proof['differentFrom']
    assert type(different) is dict and set(different)==set(snapshot['identityProof']['roles'])-{role}
    assert all(value is False for value in different.values())


def _keyboard_recipient(snapshot,binding,shell_pid):
    _validate(snapshot,binding,shell_pid,'save')
    gui=snapshot['gui']
    if _menu_key_owner(gui,snapshot['popup'],binding['child']):return
    chain=snapshot.get('focusMenuPath',[])
    assert snapshot.get('focusMenuElementEquals') is True and 0<len(chain)<=32
    assert all(row['pid']==binding['officePid'] for row in chain)
    if 'identityProof' in snapshot:
        proof=snapshot['identityProof'];terminal=snapshot['focusIdentity']
        anchors=[_element_anchor(row,proof,binding,shell_pid) for row in chain]
        assert terminal['scope']==proof['scope'] and terminal['role'] in ('file','bar')
        assert terminal['fileEquals'] is (terminal['role']=='file') and terminal['barEquals'] is (terminal['role']=='bar')
        assert chain[-1]['controlType']==('MenuItem' if terminal['role']=='file' else 'MenuBar')
        assert terminal['retainedEquals'] is True
        index=snapshot['fileIndex'] if terminal['role']=='file' else snapshot['barIndex']
        assert anchors[-1]==_element_anchor(snapshot['ancestry'][index],proof,binding,shell_pid), 'Keyboard focus differs from the retained native menu recipient'
        return
    assert all(row['runtimeId'] for row in chain)
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
    assert control['visible'] is True and control['enabled'] is enabled
    assert chain[0]==control and snapshot['fileElementEquals'] is snapshot['peerElementEquals'] is True
    file,bar,peer=(snapshot[k] for k in ('fileIndex','barIndex','peerIndex'))
    assert all(type(i) is int for i in (file,bar,peer)) and 0<=file<bar<peer==len(chain)-1
    assert chain[bar]['controlType']=='MenuBar' and chain[peer]['nativeHwnd']==binding['child']
    assert chain[file]['controlType']=='MenuItem'
    proof=snapshot.get('identityProof')
    if proof is not None:
        _comparison_proof(proof,binding,shell_pid,target)
        assert snapshot['barElementEquals'] is True
        assert (file==0) is (target=='file')
        if not control['runtimeId']:assert control['identity']['role']==_target_role(target)
    anchors=[_element_anchor(row,proof,binding,shell_pid) for row in chain]
    for index,row in enumerate(chain):
        if not row['runtimeId']:
            role=row['identity']['role']
            expected='file' if index==file else 'bar' if index==bar else _target_role(target) if index==0 else 'target:new'
            assert role==expected
            if index not in (0,file,bar):
                assert role=='target:new' and target.startswith('new-') and target!='new-hwp', 'Only the previously retained New item may be an empty-ID intermediate ancestor'
    assert chain[peer]['runtimeId'], 'Original UIA peer root still requires its runtime ID'
    control_anchor=_element_anchor(control,proof,binding,shell_pid)
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
    return (control_anchor,control['nativeHwnd'],tuple(rect),
            anchors[file],anchors[bar],binding['child'],doc['threadId'],gui['threadId'])


def _editor(snapshot,binding,shell_pid):
    assert snapshot['binding']==binding and snapshot['attachmentValid'] is True
    assert snapshot['focusPid']==binding['officePid'] and snapshot['focusRootHwnd']==binding['document']
    assert snapshot['focusUnderOriginalChild'] is True and snapshot['menuClosed'] is True
    assert snapshot['captureHwnd']==snapshot['menuOwnerHwnd']==0, 'Menu did not return original editor focus'
    fg=snapshot['foreground'];assert (fg['hwnd'],fg['rootHwnd'],fg['pid'])==(binding['document'],binding['document'],shell_pid), 'Original editor is not the foreground recipient'


def _initial_host_focus_pending(row,binding,shell_pid):
    """Only the exact, idle original host may await natural editor focus."""
    assert row['binding']==binding and row['attachmentValid'] is True
    assert row['nativeReady']==1 and type(row['nativeReady']) is int
    assert row['attachmentExports']==[binding['parent'],binding['child']]
    windows=row['attachmentWindows']
    for role,pid in (('document',shell_pid),('parent',shell_pid),('child',binding['officePid'])):
        value=windows[role]
        assert (value['hwnd'],value['pid'],value['rootHwnd'])==(binding[role],pid,binding['document'])
        assert type(value['threadId']) is int and value['threadId']>0
    assert windows['document']['threadId']==windows['parent']['threadId']
    doc=row['document']
    assert all(doc[key]==windows['document'][key] for key in ('hwnd','pid','rootHwnd','threadId'))
    assert doc['visible'] is True and doc['enabled'] is True
    fg=row['foreground']
    assert (fg['hwnd'],fg['rootHwnd'],fg['pid'])==(binding['document'],binding['document'],shell_pid)
    host,engine=row['hostGui'],row['engineGui']
    assert host['threadId']==windows['document']['threadId'] and engine['threadId']==windows['child']['threadId']
    assert host['focusHwnd']==engine['focusHwnd'] and host['focusHwnd'] in (binding['document'],binding['parent'])
    for gui in (host,engine):
        assert all(type(gui[key]) is int and 0<=gui[key]<2**64 for key in (
            'activeHwnd','focusHwnd','focusPid','focusRootHwnd','captureHwnd','menuOwnerHwnd','flags'))
        assert gui['focusPid']==shell_pid and gui['focusRootHwnd']==binding['document']
        assert gui['activeHwnd'] in (binding['document'],binding['parent'],binding['child'])
        assert type(gui['flags']) is int and gui['flags']>=0 and gui['flags']&0x1e==0
        assert gui['captureHwnd']==gui['menuOwnerHwnd']==0
    assert row['focusPid']==shell_pid and row['focusRootHwnd']==binding['document']
    assert row['focusUnderOriginalChild'] is False and row['menuClosed'] is True
    assert row['captureHwnd']==row['menuOwnerHwnd']==0


def _editor_numbers(snapshot):
    """Project already observed fixed native fields; no new query or raw text."""
    def fields(value,names):
        return {key:value[key] for key in names if type(value) is dict and
            type(value.get(key)) is int and 0<=value[key]<2**64}
    gui=('threadId','activeHwnd','focusHwnd','focusPid','focusRootHwnd','captureHwnd','menuOwnerHwnd','flags')
    window=('hwnd','pid','threadId','rootHwnd')
    attachment=dict(binding=fields(snapshot.get('binding'),('document','parent','child','officePid')),
        windows={role:fields(snapshot.get('attachmentWindows',{}).get(role),window)
            for role in ('document','parent','child')})
    for source,target in (('attachmentValid','valid'),('focusUnderOriginalChild','focusUnderOriginalChild')):
        if type(snapshot.get(source)) is bool:attachment[target]=int(snapshot[source])
    exported=snapshot.get('attachmentExports')
    if type(exported) is list and len(exported)==2 and all(type(n) is int and 0<=n<2**64 for n in exported):
        attachment['exported']=list(exported)
    state=fields(snapshot,('focusPid','focusRootHwnd','captureHwnd','menuOwnerHwnd'))
    if type(snapshot.get('menuClosed')) is bool:state['menuClosed']=int(snapshot['menuClosed'])
    if type(snapshot.get('nativeReady')) is int and 0<=snapshot['nativeReady']<2**64:state['nativeReady']=snapshot['nativeReady']
    for source,target in (('visible','documentVisible'),('enabled','documentEnabled')):
        flag=snapshot.get('document',{}).get(source)
        if type(flag) is bool:state[target]=int(flag)
    return dict(hostGui=fields(snapshot.get('hostGui'),gui),engineGui=fields(snapshot.get('engineGui'),gui),
        foreground=fields(snapshot.get('foreground'),window),attachment=attachment,editor=state)


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
        budget()
        if probe is None:probe=NativeMenuProbe(deadline,clock,interop=value.setdefault('uiaInterop',{}))
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
        begin_identity=getattr(probe,'begin_identity_scope',None)
        if begin_identity:
            value['elementIdentityScope']=begin_identity(binding,shell,engine,start,deadline,operation,gesture)
            value['uiaInterop']=probe.interop
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        def continuity():
            budget();assert probe.process_snapshot(process)==shell
            assert probe.engine_snapshot(handle)==engine, 'Original native engine changed during input admission'
            assert api.attachment(document)==(parent,child,pid)
        def observe(target,*,enabled=True):
            while True:
                measured=dict(stageCode=20,targetCode=tuple(LABELS).index(target)+1)
                value.update(menuObservation=measured,observationStage=20,observationPhase=0)
                continuity()
                measured['stageCode']=21;value['observationStage']=21
                try:row=probe.snapshot(binding,target)
                except NativeMenuPending:
                    budget();time.sleep(min(.01,max(0,deadline-clock())));continue
                measured.update(stageCode=22,snapshot=row);value['observationStage']=22
                _validate(row,binding,process.pid,target,enabled=enabled)
                if 'identityProof' in row:assert row['identityProof']['scope']==value['elementIdentityScope']
                measured['stageCode']=23;value['observationStage']=23
                return row
        def editor(phase):
            measured=dict(phaseCode=phase,stageCode=10)
            value.setdefault('editorObservations',[]).append(measured)
            value.update(observationStage=10,observationPhase=phase)
            initial_windows=None
            while True:
                if phase==1:
                    continuity()
                    assert native_menu_active(api,process,document), 'Original native menu readiness changed'
                    assert measured.get('sampleCount',0)<101, 'Initial editor focus observation exceeded finite bound'
                row=probe.editor_snapshot(binding)
                measured['stageCode']=11;value['observationStage']=11
                measured['sampleCount']=measured.get('sampleCount',0)+1
                try:
                    measured['numbers']=_editor_numbers(row)
                    if phase==1:measured.setdefault('firstNumbers',measured['numbers'])
                except BaseException:measured['numbersCaptureFailed']=1
                if initial_windows is not None:
                    assert row['attachmentWindows']==initial_windows, 'Original editor threads changed during initial focus observation'
                try:_editor(row,binding,process.pid)
                except AssertionError:
                    if phase!=1:raise
                    pending=True
                    try:_initial_host_focus_pending(row,binding,process.pid)
                    except (AssertionError,KeyError,TypeError):pending=False
                    if not pending:raise
                    if initial_windows is None:initial_windows=copy.deepcopy(row['attachmentWindows'])
                    budget();time.sleep(min(.05,max(0,deadline-clock())));budget()
                    continue
                if phase==1:continuity()
                break
            measured['stageCode']=12;value['observationStage']=12
            return row
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
                _hit_identity(hit,snap,target)
            check();retain();probe.move(point,item);assert item['pointerReadback']==point
            check();retain();continuity();probe.click(item);budget()
            assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
            assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==2
        def keyboard(shortcut):
            if shortcut=='ALT_F':
                before=observe('file');editor_before=editor(2)
            else:
                before=observe('save');_keyboard_recipient(before,binding,process.pid);editor_before=None
            continuity();item=dict(shortcut=shortcut,before=before,editorBefore=editor_before);value['keys'].append(item);retain()
            probe.keyboard(binding,shortcut,item);budget()
            if 'identityProof' in before:
                _comparison_proof(item['identityAdmission'],binding,process.pid,'file' if shortcut=='ALT_F' else 'save')
                assert item['identityAdmission']['scope']==value['elementIdentityScope']
            assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
            assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==KEY_COUNTS[shortcut]
        if gesture:editor(1)
        if operation=='keyboard-escape':
            keyboard('ALT_F');observe('save');keyboard('DOWN');keyboard('ESCAPE')
        else:
            pointer('file')
            if gesture:
                if operation=='core-commands':
                    value.update(coreCommands=list(CORE_COMMANDS),coreSnapshots={target:observe(target) for target in CORE_COMMANDS},coreCommandsVerified=True)
                elif operation.startswith('disabled-'):
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
            continuity();focus=editor(3)
            value.update(focusReturned=True,focusAfter=focus)
        value['inputVerified']=True;budget()
    except BaseException as exc:
        primary=exc;value['failureType']=type(exc).__name__
        try:
            import numeric_notice
            value['numericFailure']=numeric_notice.capture_failure_code(exc)
        except BaseException:value['numericFailureCaptureFailed']=1
        raise
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
    expected_scope=dict(version=1,binding=binding,shellPid=shell_pid,shellCreationTime=shell['creationTime'],
        officeCreationTime=engine['creationTime'],startedAt=value['startedAt'],deadline=value['deadline'],
        operation=operation,gesture=value['gesture'])
    def replay_scope(snapshot):
        if 'identityProof' in snapshot:
            assert value['elementIdentityScope']==snapshot['identityProof']['scope']==expected_scope
    assert type(value['gesture']) is bool
    if value['gesture']:
        assert operation in GESTURES and value['focusReturned'] is True
        _editor(value['focusAfter'],value['binding'],shell_pid)
        expected=[] if operation=='keyboard-escape' else ['file']+(['outside'] if operation=='open-outside' else [])
        keys=['ALT_F','DOWN','ESCAPE'] if operation=='keyboard-escape' else [] if operation=='open-outside' else ['ESCAPE']
        if operation=='core-commands':
            assert value['coreCommandsVerified'] is True and value['coreCommands']==list(CORE_COMMANDS)
            assert set(value['coreSnapshots'])==set(CORE_COMMANDS)
            for target in CORE_COMMANDS:
                replay_scope(value['coreSnapshots'][target]);_validate(value['coreSnapshots'][target],binding,shell_pid,target)
        if operation.startswith('disabled-'):
            assert value['disabledObserved'] is True
            replay_scope(value['disabledSnapshot'])
            _validate(value['disabledSnapshot'],value['binding'],shell_pid,operation[len('disabled-'):],enabled=False)
    else:
        assert operation in COMMANDS
        expected=['file']+(['new'] if operation.startswith('new-') and operation!='new-hwp' else [])+[operation];keys=[]
    assert [item['target'] for item in value['pointers']]==expected
    assert [item['shortcut'] for item in value['keys']]==keys
    for item in value['keys']:
        replay_scope(item['before'])
        if item['shortcut']=='ALT_F':
            _validate(item['before'],binding,shell_pid,'file');_editor(item['editorBefore'],binding,shell_pid)
        else:_keyboard_recipient(item['before'],binding,shell_pid)
        if 'identityProof' in item['before']:
            target='file' if item['shortcut']=='ALT_F' else 'save'
            _comparison_proof(item['identityAdmission'],binding,shell_pid,target)
            assert item['identityAdmission']['scope']==expected_scope
        assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
        assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==KEY_COUNTS[item['shortcut']]
    for item in value['pointers']:
        if item['target']=='outside':
            hit=item['nativeBefore'];assert (hit['hitHwnd'],hit['pid'],hit['rootHwnd'],hit['hitTest'])==(document,shell_pid,document,2)
            assert hit['point']==item['chosenPhysicalPoint'] and item['requestedInputs']==item['insertedInputs']==2
            continue
        for snapshot in item['snapshots']:replay_scope(snapshot)
        anchors=[_validate(s,value['binding'],shell_pid,item['target']) for s in item['snapshots']]
        assert len(anchors)==3 and all(a==anchors[0] for a in anchors)
        assert len(item['hits'])==2 and all(h['point']==item['chosenPhysicalPoint'] and h['pid']==value['binding']['officePid'] and h['withinControl'] is h['uiaMatches'] is True for h in item['hits'])
        assert item['pointerReadback']==item['beforeClickCursorReadback']==item['chosenPhysicalPoint']
        rect=item['snapshots'][0]['control']['rectangle']
        assert item['chosenPhysicalPoint']==[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        for hit,snapshot in zip(item['hits'],item['snapshots'][1:]):
            _hit_identity(hit,snapshot,item['target'])
            assert hit['hitHwnd']>0 and hit['rootHwnd']==(snapshot['popup']['hwnd'] if snapshot['popup'] else document)
        assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
        assert item['inputCallAttempts']==1 and item['insertedInputs']==item['requestedInputs']==2
    return value


def detached_native_menu_action(value):
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    assert len(raw.encode())<=CAP
    return json.loads(raw)


def observe_native_view(api,process,document,record,*,module,preview,menu_visible=True,
                        hold_seconds=3,seconds=5,probe=None,clock=time.monotonic,pause=time.sleep):
    """Read fixed chrome on the retained original frame; never dispatch or type.

    The target mode must survive continuously for three seconds after settling,
    within the original deadline. A status request started after the first target
    sample must also complete; finishing an earlier in-flight request cannot count.
    """
    assert module in ('writer','calc') and record.get('module')==module
    assert type(preview) is type(menu_visible) is bool
    assert type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=5
    assert type(hold_seconds) in (int,float) and math.isfinite(hold_seconds) and 3<=hold_seconds<seconds
    start=clock();deadline=start+seconds
    value=dict(schemaVersion=1,kind='owned-native-view-observation',module=module,preview=preview,
        menuVisible=menu_visible,holdSeconds=hold_seconds,startedAt=start,deadline=deadline,success=False,
        statusRpcProved=False,inputCallAttempts=0,samples=[],dpiScope={},engineHandleReleased=False)
    record.setdefault('nativeViewObservations',[]).append(value)
    handle=None;primary=None
    def budget():assert clock()<deadline, 'Original native view observation deadline expired'
    try:
        budget();origins=record.get('nativeMenuActions',[])
        assert type(origins) is list and 0<len(origins)<=128
        origin=origins[-1];require_native_menu_action(origin,process.pid,document)
        assert origin['finishedAt']<=start
        binding=copy.deepcopy(origin['binding']);shell=origin['originalProcess'];old=origin['originalEngine']
        suite=Path(process.opengeul_suite_root).resolve()
        generation=record.get('nativeArchiveGeneration')
        assert type(generation) is dict and set(generation)=={'pid','creationTime','image'}
        assert generation['pid']==record['officePid']==binding['officePid']==old['pid']
        assert type(generation['pid']) is int and type(generation['creationTime']) is int
        assert generation['creationTime']==record['officeCreationTime']==old['creationTime']
        assert Path(generation['image']).resolve()==Path(old['image']).resolve()==suite/'Office/program/soffice.bin'
        assert shell['pid']==process.pid and shell['handleValue']==int(process._handle)
        assert Path(shell['image']).resolve()==suite/'OpenGeul.Office.exe'
        probe=probe or NativeMenuProbe(deadline,clock)
        candidate=probe.open_engine(binding['officePid']);_int(candidate);handle=candidate
        def continuity():
            budget();assert process.poll() is None and probe.process_snapshot(process)==shell
            engine=probe.engine_snapshot(handle)
            assert all(engine[key]==old[key] for key in ('pid','creationTime','image','waitResult'))
            assert engine['waitResult']==258 and api.attachment(document)==(binding['parent'],binding['child'],binding['officePid'])
        continuity();value.update(originIndex=len(origins)-1,binding=binding,originalProcess=copy.deepcopy(shell),
            originalEngine=copy.deepcopy(old),engineHandleValue=handle)
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        first=None;previous_status=None
        while True:
            continuity();row=probe.view_snapshot(binding,module);budget()
            assert row['binding']==binding and row['nativeReady']==1 and row['shellMenuCount']==0
            _editor(row['editor'],binding,process.pid)
            for name,pid,hwnd in (('peerRoot',binding['officePid'],binding['child']),('documentRoot',process.pid,document)):
                identity=row[name]
                assert (identity['pid'],identity['nativeHwnd'])==(pid,hwnd)
                assert type(identity['runtimeId']) is list and 0<len(identity['runtimeId'])<=64
                assert all(type(n) is int and -(2**31)<=n<2**31 for n in identity['runtimeId'])
            bars=row['nativeMenuBarCount'];assert type(bars) is int and 0<=bars<=1
            count=row['previewIndicatorCount'];assert type(count) is int and 0<=count<=1
            if count:
                indicator=row['previewIndicator'];assert indicator['pid']==binding['officePid']
                assert indicator['controlType']=='Button' and indicator['visible'] is indicator['enabled'] is True
                assert indicator['ancestryVerified'] is indicator['peerElementEquals'] is indicator['toolbarAncestorVerified'] is True
                assert 0<len(indicator['runtimeId'])<=64
            else:assert row['previewIndicator'] is None
            status=decode_status_sequence(row['statusSequenceRaw'])
            if previous_status is not None:
                assert all(status[key]>=previous_status[key] for key in ('started','completed')), 'Native status sequence rolled back'
            previous_status=status
            now=clock();matched=bars==int(menu_visible) and count==int(preview)
            if matched:
                if first is None:
                    first=now;value['firstTargetStartedSequence']=status['started']
                value['lastTargetCompletedSequence']=status['completed']
                value['statusRpcProved']=status['completed']>value['firstTargetStartedSequence']
            else:
                first=None;value['statusRpcProved']=False
                value.pop('firstTargetStartedSequence',None);value.pop('lastTargetCompletedSequence',None)
            value['statusSequenceVersion']=status['version']
            assert len(value['samples'])<64, 'Native view observation sample bound exceeded'
            value['samples'].append(dict(observedAt=now,targetMatched=matched,statusSequence=status,state=row))
            value['settledAt']=first
            value['observedSeconds']=now-first if first is not None else 0
            if first is not None and now-first>=hold_seconds and value['statusRpcProved']:break
            remaining=deadline-clock();assert remaining>0
            delay=min(.1,remaining)
            if first is not None and now-first<hold_seconds:delay=min(delay,hold_seconds-(now-first))
            pause(delay)
            budget()
        continuity();value['readVerified']=True
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
        close=getattr(probe,'close_provider',None)
        if close:
            try:value['providerClientReleased']=close();assert value['providerClientReleased'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        value.update(cleanupErrors=errors,finishedAt=clock())
        value['success']=primary is None and not errors and value.get('readVerified') is True and value['finishedAt']<deadline
        try:retain_native_menu_receipt(process,value)
        except BaseException:
            value['success']=False
            if primary is None:raise
        if primary is None:assert value['success'], 'Native view observation cleanup or original deadline failed'
    return value


class NativeMenuProbe(NativeControlProbe):
    # CUIAutomation8 is the documented Windows 8+ IUIAutomation2 implementation.
    # A private client avoids changing pywinauto's shared UIA singleton settings.
    CLIENT='{e22ad333-b25f-460c-83d0-0581107395c9}'
    def __init__(self,deadline,clock,*,interop=None,**libraries):
        self.provider_client=None
        self.interop={} if interop is None else interop
        self._identity_scope=None;self._identity_refs={};self._uses_comparison=False
        NativeActivationProbe.__init__(self,deadline,clock,**libraries)
        H,D,B=C.c_void_p,C.c_uint32,C.c_int32
        for name,args,result in [('GetWindow',(H,D),H),('GetWindowTextW',(H,C.c_wchar_p,B),B),
            ('GetClassNameW',(H,C.c_wchar_p,B),B),('IsChild',(H,H),B),('GetPropW',(H,C.c_wchar_p),H),
            ('GetGUIThreadInfo',(D,C.POINTER(GuiThreadInfo)),B)]:
            function=getattr(self.user,name);function.argtypes,function.restype=args,result
        self.keyboard_probe=None
        try:
            import comtypes.client
            self._hresult_type=comtypes.HRESULT
            installed=getattr(comtypes,'__version__',None)
            match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)',installed) if type(installed) is str else None
            observed=[int(n) for n in match.groups()] if match else []
            self.interop.update(versionTuple=observed,versionObserved=bool(match and all(n<=65535 for n in observed)))
            library=self._call(comtypes.client.GetModule,'UIAutomationCore.dll')
            interface=library.IUIAutomation2
            self.provider_client=self._call(lambda:comtypes.client.CreateObject(self.CLIENT,interface=interface))
            self._provider_timeout()
            self.uia=SimpleNamespace(iuia=self.provider_client,
                tree_scope={'children':2,'descendants':4},build_condition=self._condition)
            self._point_type=library.tagPOINT
        except BaseException:
            self.close_provider();raise
    def begin_identity_scope(self,binding,shell,engine,start,deadline,operation,gesture):
        assert getattr(self,'_identity_scope',None) is None, 'A native identity scope cannot be replaced'
        self._identity_scope=dict(version=1,binding=dict(binding),shellPid=shell['pid'],
            shellCreationTime=shell['creationTime'],officeCreationTime=engine['creationTime'],
            startedAt=start,deadline=deadline,operation=operation,gesture=gesture)
        _scope_anchor(self._identity_scope,binding,shell['pid'])
        self._identity_refs={};self._uses_comparison=False
        return copy.deepcopy(self._identity_scope)
    def _same(self,left,right):
        observation=dict(callReturned=False,returnTypeCode=0,areSameObserved=False)
        self.interop['lastComparison']=observation
        raw=self._call(self.uia.iuia.CompareElements,left,right)
        observation.update(callReturned=True,returnTypeCode=1 if type(raw) is bool else 2 if type(raw) is int else 3 if raw is None else 4)
        assert type(raw) is bool or type(raw) is int and -(2**31)<=raw<2**31, 'Native UIA comparison returned an invalid BOOL'
        observation.update(areSameObserved=True,areSame=bool(raw))
        return bool(raw)
    def _declaration(self,element):
        result=dict(interfaceKnown=False,methodUnique=False,hresultDeclared=False,singleOutArgument=False,
            outFlag=False,retvalFlag=False,exactFlags=False,safeArrayInt32=False,verified=False,
            hresultValueObserved=False,safeArrayPointerObserved=False,safeArrayDimensionsObserved=False)
        try:
            interface=getattr(type(element),'__com_interface__',None)
            result['interfaceKnown']=isinstance(interface,type)
            methods=[spec for base in interface.__mro__ for spec in vars(base).get('_methods_',()) if spec.name=='GetRuntimeId'] if result['interfaceKnown'] else []
            result['methodUnique']=len(methods)==1
            if len(methods)==1:
                spec=methods[0];result['hresultDeclared']=getattr(self,'_hresult_type',None) is not None and spec.restype is self._hresult_type
                args,flags=spec.argtypes,spec.paramflags
                result['singleOutArgument']=len(args)==len(flags)==1
                if result['singleOutArgument']:
                    bits=flags[0][0];result['outFlag']=type(bits) is int and bool(bits&2)
                    result['retvalFlag']=type(bits) is int and bool(bits&8)
                    result['exactFlags']=type(bits) is int and bits==10
                    array=getattr(args[0],'_type_',None)
                    result['safeArrayInt32']=(getattr(array,'_itemtype_',None) is C.c_int and
                        C.sizeof(C.c_int)==4 and args[0] is C.POINTER(array))
            result['verified']=all(result[key] is True for key in ('interfaceKnown','methodUnique','hresultDeclared',
                'singleOutArgument','outFlag','retvalFlag','exactFlags','safeArrayInt32'))
        except Exception:pass  # Unconfirmed metadata never authorizes the empty-ID channel.
        return result
    def _runtime(self,element):
        interop=getattr(self,'interop',None)
        if interop is None:self.interop=interop={}
        observation=dict(versionTuple=copy.deepcopy(interop.get('versionTuple',[])),
            versionObserved=interop.get('versionObserved') is True,declaration=self._declaration(element),
            callSucceeded=False,rawTypeCode=0,length=None,elementTypeCodes=[],empty=False,signed32Valid=False)
        interop['lastRuntimeObservation']=observation
        raw=self._call(element.GetRuntimeId);observation['callSucceeded']=True
        observation['rawTypeCode']=1 if type(raw) is list else 2 if type(raw) is tuple else 3 if raw is None else 4
        if type(raw) in (list,tuple):
            observation.update(length=len(raw),empty=len(raw)==0,
                elementTypeCodes=[1 if type(n) is int else 2 if type(n) is bool else 3 if type(n) is float else 4 for n in raw[:64]],
                signed32Valid=len(raw)<=64 and all(type(n) is int and -(2**31)<=n<2**31 for n in raw))
        assert type(raw) in (list,tuple) and observation['signed32Valid'], 'Native runtime ID has an invalid marshalled shape'
        return list(raw),copy.deepcopy(observation)
    def _bind_ref(self,role,element):
        refs=self._identity_refs
        if role in refs:assert self._same(element,refs[role]), 'Retained native menu element changed'
        else:refs[role]=element
        return refs[role]
    def _role(self,element):
        rows=[];self.interop['lastRoleComparisons']=rows;matches=[]
        for role,original in self._identity_refs.items():
            same=self._same(element,original);rows.append(dict(roleCode=IDENTITY_ROLES.index(role)+1,areSame=same))
            if same:matches.append(role)
        assert len(matches)==1 and matches[0]!='contrast-edit', 'Native menu identity is unknown or ambiguous'
        return matches[0]
    def _fresh_base(self):
        root=self._root(self._identity_scope['binding']['child'])
        bar=self._discover_bar(root)
        return dict(peer=root,bar=bar,file=self._find(bar,'file',scope='children'),
            **{'contrast-edit':self._find_labels(bar,EDIT_CONTRAST,scope='children')})
    def _fresh_proof(self,target):
        assert self._identity_scope is not None and target in _scope_targets(self._identity_scope)
        fresh=self._fresh_base()
        if 'contrast-edit' not in self._identity_refs:
            self._bind_ref('contrast-edit',fresh['contrast-edit']);fresh=self._fresh_base()
        for role in self._identity_refs:
            if role.startswith('target:'):fresh[role]=self._find(fresh['file'],role[len('target:'):])
        assert set(fresh)==set(self._identity_refs)
        for role,element in fresh.items():
            assert self._call(lambda:element.CurrentProcessId)==self._identity_scope['binding']['officePid'], 'Fresh menu element belongs to another process'
        positive={role:self._same(fresh[role],original) for role,original in self._identity_refs.items()}
        roles=list(self._identity_refs)
        negative=[[left,right,self._same(fresh[left],fresh[right])] for index,left in enumerate(roles) for right in roles[index+1:]]
        proof=dict(scope=copy.deepcopy(self._identity_scope),roles=roles,positive=positive,negative=negative)
        _comparison_proof(proof,self._identity_scope['binding'],self._identity_scope['shellPid'],target)
        return proof
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
        for name in ('file_element','menu_bar_element','peer_element','current_control','_retained','uia','provider_client','_identity_refs'):
            if hasattr(self,name):setattr(self,name,None)
        return True
    def _condition(self,*,control_type,name=None):
        kinds={'MenuBar':50010,'MenuItem':50011,'Text':50020,'Button':50000,'ToolBar':50021}
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
        match=self._same(target,actual)
        result=dict(point=list(point),hitHwnd=hit,pid=int(pid.value),
            rootHwnd=int(self._call(self.user.GetAncestor,hit,2) or 0) if hit else 0,
            withinControl=bool(hit and (hit==handle or handle and self._call(self.user.IsChild,handle,hit) or not handle and match)),uiaMatches=match)
        if getattr(self,'_uses_comparison',False):
            role=_target_role(self._active_target);original=self._identity_refs[role]
            result['identityProof']=dict(scope=copy.deepcopy(self._identity_scope),role=role,
                targetEqualsRetained=self._same(target,original),hitEqualsRetained=self._same(actual,original),
                differentFrom={key:self._same(actual,ref) for key,ref in self._identity_refs.items() if key!=role})
            assert result['identityProof']['targetEqualsRetained'] is result['identityProof']['hitEqualsRetained'] is True
            assert all(value is False for value in result['identityProof']['differentFrom'].values())
        return result
    def _chrome(self,element):
        # Ancestor names can contain a document title; query identity only.
        def get(name):return self._call(lambda:getattr(element,name))
        handle=get('CurrentNativeWindowHandle')
        assert handle is None or type(handle) is int and -(2**31)<=handle<2**32
        runtime,observation=self._runtime(element)
        identity=None
        if not runtime:
            assert getattr(self,'_identity_scope',None) is not None, 'Runtime-free identity is limited to the current native menu action'
            assert observation['declaration']['verified'] is observation['versionObserved'] is True, 'Native runtime-ID declaration or version is unconfirmed'
            role=self._role(element)
            assert role in ('file','bar') or role.startswith('target:'), 'Only retained native menu roles may lack runtime IDs'
            self._uses_comparison=True
            identity=dict(method=IDENTITY_METHOD,scope=copy.deepcopy(self._identity_scope),role=role)
        box=get('CurrentBoundingRectangle');kind=int(get('CurrentControlType'))
        result=dict(runtimeId=runtime,runtimeIdAvailable=bool(runtime),runtimeObservation=observation,pid=int(get('CurrentProcessId')),
            nativeHwnd=0 if handle is None else handle&0xffffffff,
            controlType={50000:'Button',50010:'MenuBar',50011:'MenuItem',50021:'ToolBar',50032:'Window'}.get(kind,str(kind)),
            visible=not bool(get('CurrentIsOffscreen')),enabled=bool(get('CurrentIsEnabled')),
            rectangle=[int(getattr(box,key)) for key in ('left','top','right','bottom')])
        if identity is not None:result['identity']=identity
        return result
    def _find_labels(self,root,labels,*,scope='descendants'):
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuItem'))
        found=self._call(root.FindAll,self.uia.tree_scope[scope],condition)
        count=int(self._call(lambda:found.Length));assert 0<=count<=512
        matches=[]
        for i in range(count):
            element=self._call(found.GetElement,i)
            if int(self._call(lambda:element.CurrentControlType))!=50011:continue
            if self._call(lambda:element.CurrentIsOffscreen):continue
            name=str(self._call(lambda:element.CurrentName));assert len(name)<=256
            if _label(name) in labels:matches.append(element)
        assert len(matches)<=1, 'Native chrome target is ambiguous'
        if not matches:raise NativeMenuPending('Native chrome target not visible yet')
        return matches[0]
    def _find(self,root,target,*,scope='descendants'):
        assert target in LABELS
        return self._find_labels(root,LABELS[target],scope=scope)
    def _discover_bar(self,root):
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
        return bars[0]
    def discover_file(self,root):
        self.menu_bar_element=self._discover_bar(root)
        return self._find(self.menu_bar_element,'file',scope='children')
    def _focused_menu(self,chain,file_index,bar_index):
        result=[];cursor=self._call(self.uia.iuia.GetFocusedElement);matched=False
        comparison=getattr(self,'_uses_comparison',False)
        self._focus_identity=None
        allowed={tuple(chain[file_index]['runtimeId']),tuple(chain[bar_index]['runtimeId'])}
        for _ in range(32):
            if not cursor:break
            if comparison:
                row=self._chrome(cursor);result.append(row)
                file_same=self._same(cursor,self.file_element);bar_same=self._same(cursor,self.menu_bar_element)
                assert not (file_same and bar_same), 'Focused native menu roles alias'
                if file_same or bar_same:
                    role='file' if file_same else 'bar'
                    self._focus_identity=dict(scope=copy.deepcopy(self._identity_scope),role=role,
                        fileEquals=file_same,barEquals=bar_same,retainedEquals=True)
                    matched=True;break
            else:
                runtime,observation=self._runtime(cursor)
                assert runtime, 'Unbound focus ancestors still require runtime IDs'
                kind=int(self._call(lambda:cursor.CurrentControlType))
                result.append(dict(runtimeId=runtime,pid=int(self._call(lambda:cursor.CurrentProcessId)),controlType={50010:'MenuBar',50011:'MenuItem'}.get(kind,str(kind))))
            if not comparison and tuple(runtime) in allowed:
                # Resolve runtime IDs back to the retained live menu objects.
                for ancestor in (self.file_element,self.menu_bar_element):
                    if self._same(cursor,ancestor):matched=True
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
        self._active_target=target
        root=self._root(child)
        if not hasattr(self,'file_element'):self.file_element=self.discover_file(root)
        if getattr(self,'_identity_scope',None) is not None:
            for role,element in (('file',self.file_element),('bar',self.menu_bar_element),('peer',root)):
                self._bind_ref(role,element)
        element=self.file_element if target=='file' else self._find(self.file_element,target)
        if getattr(self,'_identity_scope',None) is not None:self._bind_ref(_target_role(target),element)
        self.current_control=type('NativeMenuControl',(),{'element_info':type('Info',(),{'_element':element})()})()
        chain=[];cursor=element;file_index=bar_index=None;file_equal=peer_equal=False
        for _ in range(32):
            row=self._chrome(cursor);chain.append(row);index=len(chain)-1
            if self._same(cursor,self.file_element):file_index=index;file_equal=True
            if row['controlType']=='MenuBar' and file_index is not None and bar_index is None:
                if getattr(self,'_uses_comparison',False):assert self._same(cursor,self.menu_bar_element), 'Native menubar differs from the retained original'
                bar_index=index
            if self._same(cursor,root):peer_equal=True;break
            cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
        else:raise AssertionError('Native menu ancestry exceeded bound')
        control=self._chrome(element);rect=control['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        proof=self._fresh_proof(target) if getattr(self,'_uses_comparison',False) else None
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
        result=dict(binding=dict(binding),attachmentValid=attachment['valid'],nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
            shellMenuCount=duplicates,document=document,control=control,ancestry=chain,fileIndex=file_index,
            barIndex=bar_index,peerIndex=len(chain)-1,fileElementEquals=file_equal,peerElementEquals=peer_equal,
            popup=popup,foreground=fg,gui=gui,focusMenuPath=focused,focusMenuElementEquals=matched)
        if proof is not None:
            result.update(identityProof=proof,barElementEquals=True,focusIdentity=getattr(self,'_focus_identity',None))
        return result
    def view_snapshot(self,binding,module):
        assert module in ('writer','calc')
        root=self._root(binding['child']);doc=binding['document']
        peer_identity=self._chrome(root)
        assert (peer_identity['pid'],peer_identity['nativeHwnd'])==(binding['officePid'],binding['child']), 'Native view UIA root is outside the original peer'
        editor=self.editor_snapshot(binding)
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuBar'))
        def menu_count(parent,pid):
            found=self._call(parent.FindAll,self.uia.tree_scope['descendants'],condition)
            count=int(self._call(lambda:found.Length));assert 0<=count<=8
            visible=0
            for index in range(count):
                element=self._call(found.GetElement,index)
                assert int(self._call(lambda:element.CurrentProcessId))==pid
                visible+=int(not self._call(lambda:element.CurrentIsOffscreen))
            assert visible<=1
            return visible
        native_bars=menu_count(root,binding['officePid'])
        shell=self._root(doc);document_identity=self._chrome(shell)
        assert (document_identity['pid'],document_identity['nativeHwnd'])==(self.window_snapshot(doc)['pid'],doc), 'Native view UIA host root changed'
        found=self._call(shell.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._call(lambda:found.Length));assert 0<=count<=64
        shell_bars=0;shell_pid=self.window_snapshot(doc)['pid']
        for index in range(count):
            bar=self._call(found.GetElement,index)
            if self._call(lambda:bar.CurrentProcessId)==shell_pid:
                shell_bars+=int(not self._call(lambda:bar.CurrentIsOffscreen))
        indicators=[];held=[]
        for label in ('미리보기 닫기','Close Preview'):
            condition=self._call(lambda:self.uia.build_condition(control_type='Button',name=label))
            found=self._call(root.FindAll,self.uia.tree_scope['descendants'],condition)
            count=int(self._call(lambda:found.Length));assert 0<=count<=2
            for index in range(count):
                element=self._call(found.GetElement,index)
                row=self._chrome(element)
                if not row['visible']:continue
                assert self._call(lambda:element.CurrentName)==label
                chain=[];cursor=element;same=False
                for _ in range(32):
                    held.append(cursor);part=self._chrome(cursor);chain.append(part)
                    assert part['pid']==binding['officePid']
                    if self._call(self.uia.iuia.CompareElements,cursor,root):same=True;break
                    cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
                assert same and chain[-1]['nativeHwnd']==binding['child']
                assert chain[0]['controlType']=='Button' and any(part['controlType']=='ToolBar' for part in chain[1:-1])
                indicators.append(dict(row,ancestryVerified=True,peerElementEquals=True,
                    toolbarAncestorVerified=True,ancestry=chain))
        assert len(indicators)<=1, 'Native preview indicator is ambiguous'
        self._retained=tuple(held)
        return dict(binding=dict(binding),editor=editor,peerRoot=peer_identity,documentRoot=document_identity,
            nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
            statusSequenceRaw=self._call(self.user.GetPropW,doc,STATUS_PROPERTY),
            shellMenuCount=shell_bars,nativeMenuBarCount=native_bars,
            previewIndicatorCount=len(indicators),previewIndicator=indicators[0] if indicators else None)
    def editor_snapshot(self,binding):
        attachment=self.attachment_snapshot(binding,include_gui=True);thread=attachment['windows']['child']['threadId'];gui=self.native_focus(thread)
        return dict(binding=dict(binding),attachmentValid=attachment['valid'],focusPid=gui['focusPid'],
            document=self.window_snapshot(binding['document']),nativeReady=int(self._call(self.user.GetPropW,binding['document'],READY_PROPERTY) or 0),
            foreground=self.window_snapshot(self.foreground()),
            focusRootHwnd=gui['focusRootHwnd'],focusUnderOriginalChild=attachment['focusUnderOriginalChild'],
            captureHwnd=gui['captureHwnd'],menuOwnerHwnd=gui['menuOwnerHwnd'],menuClosed=not gui['captureHwnd'] and not gui['menuOwnerHwnd'],
            hostGui=attachment['hostGui'],engineGui=gui,attachmentWindows=attachment['windows'],attachmentExports=attachment['exported'])
    def keyboard(self,binding,shortcut,receipt):
        from ascii_editor_input import input_buffer
        events=_menu_key_events(shortcut)
        thread=self.attachment_snapshot(binding)['windows']['child']['threadId'];state=self.keyboard_snapshot(thread)
        assert state['targetLayout']==state['currentThreadLayout']==0x04090409 and not state['keysDown']
        held=[key for key in (1,2,4,5,6,0x46,0x28) if self._call(self.user.GetAsyncKeyState,key)&0x8000]
        assert not held, 'A native menu navigation key is already pressed'
        receipt['keyboardBefore']=dict(state,additionalMenuKeysDown=held)
        receipt.update(requestedInputs=len(events),inputCallAttempts=1,insertedInputs=None)
        if getattr(self,'_uses_comparison',False):receipt['identityAdmission']=self._fresh_proof(self._active_target)
        inserted=self.send(input_buffer(events));receipt['insertedInputs']=inserted
        assert type(inserted) is int and 0<=inserted<=len(events), 'Unknown native menu inserted prefix'
        if inserted!=len(events):
            release=_menu_release_events(shortcut,inserted)
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
