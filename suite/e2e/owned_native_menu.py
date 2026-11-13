"""Measured engine-owned menus; the WinForms menu proof remains separate.

Only fixed chrome labels are matched. Unknown labels and document contents are
not retained. Native insertion counts never prove command delivery or storage.
"""
from __future__ import annotations
import copy
import ctypes as C
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import time
from types import SimpleNamespace

from owned_control_actions import CAP, GuiThreadInfo, NativeControlProbe, _original_attachment
from suite_window_activation import NativeActivationProbe, Rect

_OWNED_WINDLL_TYPE=getattr(C,'WinDLL',None)
_OWNED_ACTIVATION_INIT=NativeActivationProbe.__init__
_OWNED_CFUNC_CALL=C._CFuncPtr.__call__
_NATIVE_USER_EXPORTS=('IsWindow','IsWindowVisible','IsWindowEnabled','IsIconic','GetAncestor',
    'GetForegroundWindow','GetWindowThreadProcessId','GetWindowRect','GetTitleBarInfo',
    'WindowFromPhysicalPoint','SetPhysicalCursorPos','GetPhysicalCursorPos','SetThreadDpiAwarenessContext',
    'GetThreadDpiAwarenessContext','AreDpiAwarenessContextsEqual','SendMessageTimeoutW','GetAsyncKeyState',
    'GetSystemMetrics','SendInput')
_NATIVE_KERNEL_EXPORTS=('GetProcessId','WaitForSingleObject','GetProcessTimes','QueryFullProcessImageNameW')


class MenuBarInfo(C.Structure):
    _fields_=[('cbSize',C.c_uint32),('rcBar',Rect),('hMenu',C.c_void_p),
              ('hwndMenu',C.c_void_p),('flags',C.c_uint32)]

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

# Fixed callsites only, never an assertion about the COM object's identity.
# 0 unobserved; 1 retained-File chrome; 2 physical-File ancestry query;
# 3/4 legacy global-point/target chrome; 5/6 diagnostic target/global-point;
# 7 point target chrome; 8 failure ancestry; 9 focused ancestry;
# 10/11 snapshot first target candidate/following ancestor; 12 repeated target;
# 13/14 view peer/shell roots; 15/16 view target/ancestor;
# 17/18 source-qualified global-point/target chrome.
_GETTER_SITE_CODES=frozenset(range(19))
_GETTER_SITE_UNSET=object()


def _getter_call_site(probe,code,function,*args):
    previous=getattr(probe,'_getter_site_code',_GETTER_SITE_UNSET)
    probe._getter_site_code=code
    try:return function(*args)
    finally:
        if previous is _GETTER_SITE_UNSET:probe.__dict__.pop('_getter_site_code',None)
        else:probe._getter_site_code=previous


class NativeMenuPending(AssertionError):pass


class NativeIdentityDiagnosticTerminal(AssertionError):
    """A selected diagnostic ended; no target input or observation retry."""


def _identity_diagnostic_packet(packet):
    """Closed numeric mode3 packet; a positive is rejected, never corrected."""
    from native_menu_msaa_hit import _record_v3
    expected=_record_v3(None,False)
    assert type(packet) is dict and packet.keys()==expected.keys()
    assert all(type(n) is int and 0<=n<(1<<64 if key=='threadBirth' else 1<<32)
        for key,n in packet.items())
    assert packet['schemaVersion']==packet['workerSchemaVersion']==3
    assert packet['diagnosticOnly']==packet['providerLocalOnly']==1
    assert packet['acceptanceEligible']==packet['localKnown']==packet['localMatch']==packet['globalHitSubstituted']==packet['synthetic']==0
    assert packet['diagnosticComplete'] in (0,1) and packet['pending'] in (0,1)
    return copy.deepcopy(packet)


def _identity_diagnostic_control():
    return dict(schemaVersion=3,diagnosticProfile=3,diagnosticOnly=1,acceptanceEligible=0,
        localKnown=0,localMatch=0,leaseAttempted=0,pending=0,postScopeVerified=0,
        diagnosticComplete=0,terminalCode=1)


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
    if hit.get('pointMethod')=='owned-popup-and-msaa-hit':
        _require_provider_point(hit,snapshot,target);return
    if hit.get('pointMethod')=='owned-popup-and-msaa-canonical-hit-v2':
        _require_provider_point_v2(hit,snapshot,target);return
    if 'identityProof' not in snapshot:return
    proof=hit['identityProof'];scope=snapshot['identityProof']['scope'];role=_target_role(target)
    assert proof['scope']==scope and proof['role']==role
    assert proof['targetEqualsRetained'] is proof['hitEqualsRetained'] is True
    different=proof['differentFrom']
    assert type(different) is dict and set(different)==set(snapshot['identityProof']['roles'])-{role}
    assert all(value is False for value in different.values())


def _require_point(hit,snapshot,target,*,source_admission=None,now=None):
    method=hit.get('pointMethod','global-uia')
    if source_admission is not None:
        if method=='owned-popup-and-source-qualified-ia2-hit-v4':
            _require_source_point_v4(hit,snapshot,target,source_admission,now=now);return
        assert method=='global-uia', 'Source selection cannot consume a legacy local point'
        assert 'providerLocalProof' not in hit and 'pointObservedAt' not in hit, 'A local source point cannot be relabeled global'
    assert method in ('global-uia','owned-popup-and-msaa-hit','owned-popup-and-msaa-canonical-hit-v2'), 'Unknown native point proof method'
    if method=='global-uia':assert hit['withinControl'] is hit['uiaMatches'] is True, 'Native menu point is obstructed'
    _hit_identity(hit,snapshot,target)


def _require_provider_point(hit,snapshot,target):
    """Replay a distinct local proof without turning the global FALSE to TRUE."""
    assert target!='file' and 'identityProof' in snapshot
    assert hit['uiaMatches'] is False
    original=hit['identityProof'];scope=snapshot['identityProof']['scope'];role=_target_role(target)
    assert original['scope']==scope and original['role']==role
    assert original['targetEqualsRetained'] is True and original['hitEqualsRetained'] is False
    roles=snapshot['identityProof']['roles'];negatives=[name for name in roles if name!=role]
    assert set(original['differentFrom'])==set(negatives)
    assert all(value is False for value in original['differentFrom'].values())
    proof=hit['providerLocalProof'];assert proof['schemaVersion']==1
    assert proof['method']=='owned-popup-and-msaa-hit' and proof['scope']==scope and proof['role']==role
    assert proof['negativeRoles']==negatives+['global-point']
    assert type(proof['sourceScopeId']) is int and proof['sourceScopeId']>0
    creator=proof['creator'];_int(creator['threadId'])
    assert creator['mta'] is creator['sameThread'] is True
    provider=proof['provider'];assert type(provider) is dict and all(type(value) is int for value in provider.values())
    assert provider['scopeId']==proof['sourceScopeId'] and provider['stageCode']==13
    ones=('schemaVersion','diagnosticOnly','providerLocalOnly','nativeAttempted','nativeExit','threadClosed',
        'processesClosed','localKnown','localMatch','workerCleanup','workerMta','comInitialized',
        'comUninitialized','dpiEntered','dpiRestored','processBefore','processAfter','variantAttempted',
        'variantCleared','childIdZero','fileRoundTrip','targetFreshPositive','targetRetainedPositive',
        'physicalDpiVerified','threadIdentity','callbackIdentity','exitCodeObserved')
    zeros=('acceptanceEligible','globalHitSubstituted','synthetic','workerException','pending',
        'variantCleanupHresult','cleanupError','nativeExitCode')
    assert all(provider[key]==1 for key in ones) and all(provider[key]==0 for key in zeros)
    for key in ('controllerPid','threadId','threadBirth'):_int(provider[key])
    assert provider['workerStage']==8 and provider['threadId']!=creator['threadId']
    assert provider['controllerPid'] not in (scope['shellPid'],scope['binding']['officePid'])
    assert provider['variantType']==9 and provider['referencesAcquired']==provider['referencesReleased']>=5
    assert provider['negativeCount']==provider['negativeRejected']==len(negatives)+1
    for name in ('pattern','child_id','accessible','from_accessible','hit_test','query','compare'):
        assert provider[name+'Attempted']==provider[name+'Completed']>=1 and provider[name+'Hresult']==0
    assert provider['compareCompleted']==len(negatives)+4 and provider['from_accessibleCompleted']==2
    binding=scope['binding'];before=proof['before'];assert before==proof['after']
    assert proof['sourceScope']==dict(scope_id=proof['sourceScopeId'],engine_pid=binding['officePid'],
        engine_birth=scope['officeCreationTime'],shell_pid=scope['shellPid'],shell_birth=scope['shellCreationTime'],
        parent_hwnd=binding['parent'],child_hwnd=binding['child'],x=hit['point'][0],y=hit['point'][1])
    popup=snapshot['popup'];assert popup is not None
    assert before['classCode']==1 and before['ownershipBefore'] is before['ownershipAfter'] is True
    assert before['hwnd']==before['rootHwnd']==hit['hitHwnd']==hit['rootHwnd']==popup['hwnd']
    assert before['pid']==hit['pid']==binding['officePid'] and before['threadId']==popup['threadId']
    assert before['ownerChain']==popup['ownerChain'] and before['ownerChain'][-1] in (binding['child'],binding['document'])
    assert before['style']&0x80000000 and not before['style']&0x40000000 and before['extendedStyle']&0x80
    assert before['foreground'] in (binding['document'],popup['hwnd']) and before['point']==hit['point']
    rect=before['rectangle'];target_rect=snapshot['control']['rectangle'];point=hit['point']
    assert all(type(n) is int for n in (*rect,*target_rect,*point))
    assert rect[0]<=target_rect[0]<=point[0]<target_rect[2]<=rect[2]
    assert rect[1]<=target_rect[1]<=point[1]<target_rect[3]<=rect[3]
    assert proof['globalPoint']==dict(kindCode=50033,pid=binding['officePid'],nativeHwnd=popup['hwnd'])
    _comparison_proof(proof['fresh'],binding,scope['shellPid'],target)
    assert proof['fresh']['scope']==scope


def _require_provider_point_v2(hit,snapshot,target):
    """Replay exact native object/SELF hit identity; never rewrite global FALSE."""
    from native_menu_msaa_hit import _record,worker_record_v2,MsaaHitScope
    assert target!='file' and 'identityProof' in snapshot and hit['uiaMatches'] is False
    scope=snapshot['identityProof']['scope'];binding=scope['binding'];role=_target_role(target)
    original=hit['identityProof'];roles=snapshot['identityProof']['roles']
    negatives=[name for name in roles if name!=role]
    assert original['scope']==scope and original['role']==role
    assert original['targetEqualsRetained'] is True and original['hitEqualsRetained'] is False
    assert type(original['differentFrom']) is dict and set(original['differentFrom'])==set(negatives)
    assert all(value is False for value in original['differentFrom'].values())
    proof=hit['providerLocalProof']
    assert type(proof) is dict and set(proof)==set(('schemaVersion method scope role sourceScopeId '
        'sourceScope negativeRoles provider before after sourceFresh fresh creator globalPoint').split())
    assert type(proof['schemaVersion']) is int and proof['schemaVersion']==2
    assert proof['method']=='owned-popup-and-msaa-canonical-hit-v2' and proof['scope']==scope and proof['role']==role
    assert proof['negativeRoles']==negatives+['global-point']
    assert type(proof['sourceScopeId']) is int and 0<proof['sourceScopeId']<=32
    creator=proof['creator'];assert type(creator) is dict and set(creator)=={'threadId','mta','sameThread'}
    _int(creator['threadId']);assert creator['threadId']<2**32
    assert creator['mta'] is creator['sameThread'] is True
    provider=proof['provider'];expected=_record(None,False,profile_version=2)
    assert type(provider) is dict and provider.keys()==expected.keys()
    assert all(type(value) is int and 0<=value<2**64 for value in provider.values())
    assert all(provider[key]<2**32 for key in worker_record_v2())
    assert provider['schemaVersion']==provider['workerSchemaVersion']==2
    assert provider['scopeId']==proof['sourceScopeId'] and provider['stageCode']==13
    ones=('diagnosticOnly','providerLocalOnly','nativeAttempted','nativeExit','threadClosed',
        'processesClosed','localKnown','localMatch','workerCleanup','workerMta','comInitialized',
        'comUninitialized','dpiEntered','dpiRestored','processBefore','processAfter','variantAttempted',
        'variantCleared','physicalDpiVerified','threadIdentity','callbackIdentity','exitCodeObserved',
        'canonicalStatus','filePairEqual','fileOriginalRepeatEqual','targetPairEqual',
        'targetDifferentFromFile','hitMatchesTarget','fileUiPositive','targetUiPositive')
    zeros=('acceptanceEligible','globalHitSubstituted','synthetic','workerException','pending',
        'variantCleanupHresult','cleanupError','nativeExitCode')
    assert all(provider[key]==1 for key in ones) and all(provider[key]==0 for key in zeros)
    for key in ('controllerPid','threadId','threadBirth'):_int(provider[key])
    assert provider['controllerPid']<2**32 and provider['threadId']<2**32
    assert provider['workerStage']==8 and provider['threadId']!=creator['threadId']
    assert provider['controllerPid'] not in (scope['shellPid'],binding['officePid'])
    assert provider['bindingCount']==provider['selfCount']==4 and provider['variantType']==9
    assert provider['referencesAcquired']==provider['referencesReleased']==16
    count=len(negatives)+1
    assert 2<=count<=16
    assert provider['negativeCount']==provider['negativeRejected']==count
    calls=dict(pattern=4,child_id=4,accessible=5,accessible_query=6,control_type=4,
        hit_test=1,query=1,compare=2+count)
    for name,number in calls.items():
        assert provider[name+'Attempted']==provider[name+'Completed']==number and provider[name+'Hresult']==0
    before=proof['before'];assert type(before) is dict and before==proof['after']
    assert set(before)==set(('classCode hwnd pid threadId rootHwnd style extendedStyle rectangle '
        'point ownerChain foreground ownershipBefore ownershipAfter').split())
    source_scope=proof['sourceScope'];assert type(source_scope) is dict
    assert source_scope==dict(scope_id=proof['sourceScopeId'],engine_pid=binding['officePid'],
        engine_birth=scope['officeCreationTime'],shell_pid=scope['shellPid'],shell_birth=scope['shellCreationTime'],
        parent_hwnd=binding['parent'],child_hwnd=binding['child'],x=hit['point'][0],y=hit['point'][1])
    assert MsaaHitScope(**source_scope).valid()
    popup=snapshot['popup'];assert popup is not None
    for key in ('classCode','pid','threadId'):
        _int(before[key]);assert before[key]<2**32
    for key in ('hwnd','rootHwnd','foreground'):
        _int(before[key]);assert before[key]<2**64
    assert before['classCode']==1 and before['ownershipBefore'] is before['ownershipAfter'] is True
    assert before['hwnd']==before['rootHwnd']==hit['hitHwnd']==hit['rootHwnd']==popup['hwnd']
    assert before['pid']==hit['pid']==binding['officePid'] and before['threadId']==popup['threadId']
    owners=before['ownerChain'];assert type(owners) is list and 2<=len(owners)<=16
    assert all(type(n) is int and n>0 for n in owners) and len(set(owners))==len(owners)
    assert owners==popup['ownerChain'] and owners[0]==popup['hwnd'] and owners[-1] in (binding['child'],binding['document'])
    assert all(type(before[key]) is int and 0<=before[key]<2**32 for key in ('style','extendedStyle'))
    assert before['style']&0x80000000 and not before['style']&0x40000000 and before['extendedStyle']&0x80
    assert before['foreground'] in (binding['document'],popup['hwnd']) and before['point']==hit['point']
    rect=before['rectangle'];target_rect=snapshot['control']['rectangle'];point=hit['point']
    assert len(rect)==len(target_rect)==4 and len(point)==2
    assert all(type(n) is int for n in (*rect,*target_rect,*point))
    assert rect[0]<=target_rect[0]<=point[0]<target_rect[2]<=rect[2]
    assert rect[1]<=target_rect[1]<=point[1]<target_rect[3]<=rect[3]
    assert proof['globalPoint']==dict(kindCode=50033,pid=binding['officePid'],nativeHwnd=popup['hwnd'])
    for field in ('sourceFresh','fresh'):
        fresh=proof[field];_comparison_proof(fresh,binding,scope['shellPid'],target)
        assert fresh['scope']==scope and fresh['roles']==roles


def _keyboard_recipient(snapshot,binding,shell_pid,*,menu_scope=None,source_admission=None,point_at=None):
    _validate(snapshot,binding,shell_pid,'save',menu_scope=menu_scope,source_admission=source_admission,point_at=point_at)
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


def _menu_scope(binding,shell,engine,start,deadline):
    return dict(version=1,binding=dict(binding),shellPid=shell['pid'],shellCreationTime=shell['creationTime'],
        officeCreationTime=engine['creationTime'],startedAt=start,deadline=deadline)


def _require_shell_menus(snapshot,binding,shell_pid,scope=None):
    count=snapshot['shellMenuCount'];assert type(count) is int and 0<=count<=64
    if count==0:return
    value=snapshot.get('shellMenuClassification',{})
    assert type(scope) is dict and value.get('scope')==scope, 'Native menu not exclusive and ready'
    seen=value['scope'];assert type(seen['version']) is int and seen['version']==1
    for key in ('shellPid','shellCreationTime','officeCreationTime'):_int(seen[key])
    assert all(type(n) is int and n>0 for n in seen['binding'].values())
    assert all(type(seen[k]) in (int,float) and math.isfinite(seen[k]) for k in ('startedAt','deadline'))
    assert scope['binding']==binding and scope['shellPid']==shell_pid and scope['version']==1
    for key in ('shellCreationTime','officeCreationTime'):_int(scope[key])
    assert scope['officeCreationTime']>=scope['shellCreationTime']
    assert all(type(scope[k]) in (int,float) and math.isfinite(scope[k]) for k in ('startedAt','deadline'))
    assert scope['startedAt']<scope['deadline']<=scope['startedAt']+5
    assert all(type(value.get(k)) is int for k in ('totalCount','verifiedSystemCount','clientCount','unknownCount','errorCode'))
    assert value['totalCount']==count and value['verifiedSystemCount']==count==1 and value['clientCount']==value['unknownCount']==value['errorCode']==0, 'Native menu not exclusive and ready'
    proof,=value['proofs'];assert proof['before']==proof['after']
    data=proof['before'];assert set(data)=={'menuRect','captionRect','captionState','menuHandle','submenuHwnd','menuFlags'}
    for key in ('menuRect','captionRect'):
        rect=data[key];assert type(rect) is list and len(rect)==4 and all(type(n) is int and -(2**31)<=n<2**31 for n in rect)
        assert rect[0]<rect[2] and rect[1]<rect[3]
    for key in ('menuHandle','submenuHwnd','menuFlags','captionState'):
        assert type(data[key]) is int and 0<=data[key]<2**(32 if key in ('menuFlags','captionState') else 64)
    assert data['menuHandle']>0 and not data['captionState']&0x18001
    rect=data['menuRect'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
    assert proof['point']==point and all(-(2**15)<=n<2**15 for n in point)
    hit=proof['physicalHit'];assert hit['point']==point
    assert (hit['hitHwnd'],hit['rootHwnd'],hit['pid'],hit['hitTest'])==(binding['document'],binding['document'],shell_pid,3)
    _int(proof['harnessPid']);assert proof['harnessPid']!=shell_pid
    flags=('pointBarEqualsCounted','freshPointBarEqualsRetained','engineBarDifferent','shellRootDifferent',
        'rootStable','ownershipBefore','ownershipAfter','physicalDpiVerified')
    assert all(proof.get(k) is True for k in flags)
    chain=proof['ancestry'];assert type(chain) is list and 3<=len(chain)<=32
    assert all(type(row) is list and len(row)==3 and all(type(n) is int for n in row) for row in chain)
    assert all(row[1]==shell_pid and row[2] in (0,binding['document']) for row in chain)
    bar=proof['barIndex'];assert type(bar) is int and 0<=bar<len(chain)
    assert all(row[0] in (50000,50011) for row in chain[:bar])
    assert [row[0] for row in chain[bar:]]==[50010,50037,50032] and chain[-1][2]==binding['document']


def _validate(snapshot,binding,shell_pid,target,*,enabled=True,menu_scope=None,source_admission=None,point_at=None):
    assert snapshot['binding']==binding and snapshot['attachmentValid'] is True
    assert snapshot['nativeReady']==1, 'Native menu not exclusive and ready'
    _require_shell_menus(snapshot,binding,shell_pid,menu_scope)
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
    if 'targetPointProof' in snapshot:
        hit=snapshot['targetPointProof'];assert target!='file' and popup
        assert hit['point']==[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        assert hit['pid']==binding['officePid'] and hit['rootHwnd']==popup['hwnd']
        _require_point(hit,snapshot,target,source_admission=source_admission,now=point_at)
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
    handle=None;primary=None;source_admission=None;diagnostic=getattr(process,'opengeul_native_menu_identity_diagnostic',0)
    def budget():assert clock()<deadline, 'Original native menu deadline expired'
    def retain():retain_native_menu_receipt(process,value)
    try:
        budget()
        assert type(diagnostic) is int and diagnostic in (0,3), 'Unknown native identity diagnostic'
        if diagnostic:
            value.update(diagnosticProfile=3,diagnosticOnly=1,acceptanceEligible=0)
            assert gesture and operation=='open-escape', 'The diagnostic has one fixed first gesture'
            assert not getattr(process,'opengeul_native_menu_identity_diagnostic_started',False), 'The diagnostic cannot repeat'
            process.opengeul_native_menu_identity_diagnostic_started=True
        profile=getattr(process,'opengeul_native_menu_point_profile',False) is True
        version=getattr(process,'opengeul_native_menu_point_profile_version',1) if profile else 1
        assert type(version) is int and version in (1,2), 'Unknown native point profile version'
        assert not diagnostic or profile and version==2, 'The diagnostic needs the existing retained-ref guards'
        selection=getattr(process,'opengeul_source_menu_selection',None)
        if selection is not None:
            assert not diagnostic and not profile, 'Source selection cannot mix diagnostic or legacy profiles'
            profile=True;version=4
        if profile:
            from native_menu_msaa_hit import pending_msaa_hit
            assert pending_msaa_hit() is None, 'An original native provider callback is still unretired'
        from native_menu_source_selection import selected_native_menu_probe
        def build(selected):
            if selected is not None:
                return NativeMenuProbe(deadline,clock,interop=value.setdefault('uiaInterop',{}),source_selection=selected)
            return NativeMenuProbe(deadline,clock,interop=value.setdefault('uiaInterop',{}),
                native_point_profile=profile,native_point_profile_version=version,native_identity_diagnostic=diagnostic)
        probe=selected_native_menu_probe(process,deadline,clock,build=build,supplied=probe)
        if profile:
            assert getattr(probe,'_native_point_profile_version',1)==version, 'Native point profile changed before admission'
            if version==2:assert getattr(probe,'_native_point_profile',False) is True
            assert getattr(probe,'_native_identity_diagnostic',0)==diagnostic, 'Native identity diagnostic changed before admission'
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
        _bind_source_generation(probe,process,suite,binding,shell,engine,handle,value)
        if selection is not None:source_admission=selection.prepared.admission
        if profile:probe._point_source=dict(shellHandle=int(process._handle),engineHandle=handle)
        begin_identity=getattr(probe,'begin_identity_scope',None)
        if begin_identity:
            value['elementIdentityScope']=begin_identity(binding,shell,engine,start,deadline,operation,gesture)
            value['uiaInterop']=probe.interop
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        def continuity():
            budget();assert probe.process_snapshot(process)==shell
            assert probe.engine_snapshot(handle)==engine, 'Original native engine changed during input admission'
            assert api.attachment(document)==(parent,child,pid)
        menu_scope=_menu_scope(binding,shell,engine,start,deadline)
        bind_menu=getattr(probe,'bind_menu_classification',None)
        if bind_menu:bind_menu(menu_scope,continuity)
        def observe(target,*,enabled=True):
            while True:
                measured=dict(stageCode=20,targetCode=tuple(LABELS).index(target)+1)
                value.update(menuObservation=measured,observationStage=20,observationPhase=0)
                continuity()
                measured['stageCode']=21;value['observationStage']=21
                try:row=probe.snapshot(binding,target)
                except NativeMenuPending:
                    if source_admission is not None:raise
                    if diagnostic:raise NativeIdentityDiagnosticTerminal('Diagnostic source was not ready') from None
                    budget();time.sleep(min(.01,max(0,deadline-clock())));continue
                measured.update(stageCode=22,snapshot=row);value['observationStage']=22
                _require_shell_menus(row,binding,process.pid,menu_scope)
                continuity()
                observed=clock()
                _validate(row,binding,process.pid,target,enabled=enabled,menu_scope=menu_scope,
                    source_admission=source_admission,point_at=observed)
                if source_admission is not None and 'targetPointProof' in row:
                    _source_point_use(probe,row['targetPointProof'],1,row['targetPointProof']['pointObservedAt'])
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
            assert not diagnostic or target=='file', 'A diagnostic cannot send target input'
            row=observe(target);anchor=_validate(row,binding,process.pid,target,menu_scope=menu_scope,
                source_admission=source_admission,point_at=clock())
            rect=row['control']['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
            item=dict(target=target,chosenPhysicalPoint=point,snapshots=[row],hits=[])
            value['pointers'].append(item)
            def check():
                snap=observe(target);assert _validate(snap,binding,process.pid,target,menu_scope=menu_scope,
                    source_admission=source_admission,point_at=clock())==anchor
                item['snapshots'].append(snap)
                scope=snap['popup']['hwnd'] if snap['popup'] else document
                hit=probe.point_snapshot(scope,point,probe.current_control);item['hits'].append(hit)
                assert hit['point']==point and hit['pid']==pid and hit['rootHwnd']==scope
                _require_point(hit,snap,target,source_admission=source_admission,now=clock())
                if source_admission is not None:_source_point_use(probe,hit,2,hit.get('pointObservedAt'))
            check();retain();probe.move(point,item);assert item['pointerReadback']==point
            check();retain();continuity();_arm_source_input(probe,item,item['hits'][-1:],3);probe.click(item);budget()
            assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
            assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==2
        def keyboard(shortcut):
            assert not diagnostic, 'A diagnostic cannot send menu keys'
            if shortcut=='ALT_F':
                before=observe('file');editor_before=editor(2)
            else:
                before=observe('save');_keyboard_recipient(before,binding,process.pid,menu_scope=menu_scope,
                    source_admission=source_admission,point_at=clock());editor_before=None
            continuity();item=dict(shortcut=shortcut,before=before,editorBefore=editor_before);value['keys'].append(item);retain()
            _arm_source_input(probe,item,[before.get('targetPointProof')],4)
            probe.keyboard(binding,shortcut,item);budget()
            if 'identityProof' in before:
                _comparison_proof(item['identityAdmission'],binding,process.pid,'file' if shortcut=='ALT_F' else 'save')
                assert item['identityAdmission']['scope']==value['elementIdentityScope']
            assert all(type(item[k]) is int for k in ('inputCallAttempts','requestedInputs','insertedInputs'))
            assert item['inputCallAttempts']==1 and item['requestedInputs']==item['insertedInputs']==KEY_COUNTS[shortcut]
        if gesture:editor(1)
        def discarded_observe(target):
            row=observe(target)
            if source_admission is not None and 'targetPointProof' in row:
                retained=value.setdefault('sourcePointSnapshots',[]);assert len(retained)<32;retained.append(row)
        if operation=='keyboard-escape':
            keyboard('ALT_F');discarded_observe('save');keyboard('DOWN');keyboard('ESCAPE')
        else:
            pointer('file')
            if gesture:
                if operation=='core-commands':
                    value.update(coreCommands=list(CORE_COMMANDS),coreSnapshots={target:observe(target) for target in CORE_COMMANDS},coreCommandsVerified=True)
                elif operation.startswith('disabled-'):
                    target=operation[len('disabled-'):]
                    value.update(disabledSnapshot=observe(target,enabled=False),disabledObserved=True)
                elif operation!='open-escape' or diagnostic:
                    discarded_observe('save')
                    if diagnostic:raise NativeIdentityDiagnosticTerminal('Diagnostic point returned without its terminal marker')
                if operation=='open-outside':
                    continuity();hit=probe.outside_snapshot(binding)
                    assert hit['pid']==process.pid and hit['rootHwnd']==document and hit['hitHwnd']==document and hit['hitTest']==2
                    item=dict(target='outside',chosenPhysicalPoint=hit['point'],nativeBefore=hit);value['pointers'].append(item)
                    retain();_arm_source_input(probe,item,[],3);probe.outside_click(binding,item);budget();assert item['requestedInputs']==item['insertedInputs']==2
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
            capture=getattr(probe,'capture_primary_failure',None)
            if capture and not diagnostic and getattr(process,'opengeul_source_menu_selection',None) is None and getattr(probe,'source_selection',None) is None:capture(exc)
        except BaseException:value['numericPrimaryCaptureFailed']=1
        try:
            import numeric_notice
            value['numericFailure']=numeric_notice.capture_failure_code(exc)
        except BaseException:value['numericFailureCaptureFailed']=1
        try:value['numericFailureFrames']=numeric_notice.capture_failure_frames(exc)
        except BaseException:value['numericFailureFramesCaptureFailed']=1
        try:
            observer=getattr(probe,'observe_failure_context',None)
            if observer and not diagnostic and getattr(process,'opengeul_source_menu_selection',None) is None and getattr(probe,'source_selection',None) is None:observer(value.get('binding'))
        except BaseException:value['numericContextCaptureFailed']=1
        if diagnostic and not isinstance(exc,NativeIdentityDiagnosticTerminal):
            raise NativeIdentityDiagnosticTerminal('Diagnostic source ended before input') from None
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


def _require_native_menu_action_record(value,shell_pid,document,command=None,*,source_admission=None):
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
    menu_scope=_menu_scope(binding,shell,engine,value['startedAt'],value['deadline'])
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
                replay_scope(value['coreSnapshots'][target]);_validate(value['coreSnapshots'][target],binding,shell_pid,target,menu_scope=menu_scope,
                    source_admission=source_admission,point_at=_replay_point_at(value['coreSnapshots'][target],source_admission))
        if operation.startswith('disabled-'):
            assert value['disabledObserved'] is True
            replay_scope(value['disabledSnapshot'])
            _validate(value['disabledSnapshot'],value['binding'],shell_pid,operation[len('disabled-'):],enabled=False,menu_scope=menu_scope,
                source_admission=source_admission,point_at=_replay_point_at(value['disabledSnapshot'],source_admission))
    else:
        assert operation in COMMANDS
        expected=['file']+(['new'] if operation.startswith('new-') and operation!='new-hwp' else [])+[operation];keys=[]
    assert [item['target'] for item in value['pointers']]==expected
    assert [item['shortcut'] for item in value['keys']]==keys
    for item in value['keys']:
        replay_scope(item['before'])
        if item['shortcut']=='ALT_F':
            _validate(item['before'],binding,shell_pid,'file',menu_scope=menu_scope,
                source_admission=source_admission,point_at=_replay_point_at(item['before'],source_admission));_editor(item['editorBefore'],binding,shell_pid)
        else:_keyboard_recipient(item['before'],binding,shell_pid,menu_scope=menu_scope,
            source_admission=source_admission,point_at=_replay_point_at(item['before'],source_admission))
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
        anchors=[_validate(s,value['binding'],shell_pid,item['target'],menu_scope=menu_scope,
            source_admission=source_admission,point_at=_replay_point_at(s,source_admission)) for s in item['snapshots']]
        assert len(anchors)==3 and all(a==anchors[0] for a in anchors)
        assert len(item['hits'])==2 and all(h['point']==item['chosenPhysicalPoint'] and h['pid']==value['binding']['officePid'] for h in item['hits'])
        assert item['pointerReadback']==item['beforeClickCursorReadback']==item['chosenPhysicalPoint']
        rect=item['snapshots'][0]['control']['rectangle']
        assert item['chosenPhysicalPoint']==[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        for hit,snapshot in zip(item['hits'],item['snapshots'][1:]):
            _require_point(hit,snapshot,item['target'],source_admission=source_admission,
                now=hit.get('pointObservedAt') if source_admission is not None else None)
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
        budget()
        from native_menu_source_selection import selected_native_menu_probe
        probe=selected_native_menu_probe(process,deadline,clock,
            build=lambda selected:NativeMenuProbe(deadline,clock,**({} if selected is None else {'source_selection':selected})),supplied=probe)
        selection=getattr(probe,'source_selection',None)
        origins=record.get('nativeMenuActions',[])
        assert type(origins) is list and 0<len(origins)<=128
        origin=origins[-1]
        if selection is None:require_native_menu_action(origin,process.pid,document)
        else:require_native_menu_action(origin,process.pid,document,source_admission=selection.prepared.admission)
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
        candidate=probe.open_engine(binding['officePid']);_int(candidate);handle=candidate
        current_engine=None
        def continuity():
            nonlocal current_engine
            budget();assert process.poll() is None and probe.process_snapshot(process)==shell
            engine=probe.engine_snapshot(handle);current_engine=engine
            assert all(engine[key]==old[key] for key in ('pid','creationTime','image','waitResult'))
            assert engine['waitResult']==258 and api.attachment(document)==(binding['parent'],binding['child'],binding['officePid'])
        continuity();value.update(originIndex=len(origins)-1,binding=binding,originalProcess=copy.deepcopy(shell),
            originalEngine=copy.deepcopy(old),engineHandleValue=handle)
        _bind_source_generation(probe,process,suite,binding,shell,current_engine,handle,value)
        menu_scope=_menu_scope(binding,shell,old,start,deadline)
        bind_menu=getattr(probe,'bind_menu_classification',None)
        if bind_menu:bind_menu(menu_scope,continuity)
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        first=None;previous_status=None
        while True:
            continuity();row=probe.view_snapshot(binding,module)
            _require_shell_menus(row,binding,process.pid,menu_scope);budget()
            continuity()
            assert row['binding']==binding and row['nativeReady']==1
            _require_shell_menus(row,binding,process.pid,menu_scope)
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
    def __init__(self,deadline,clock,*,interop=None,native_point_profile=False,native_point_profile_version=1,native_identity_diagnostic=0,source_selection=None,**libraries):
        self.source_selection=source_selection
        if source_selection is not None:
            from native_menu_source_selection import _require_selection
            _require_selection(source_selection)
            assert native_point_profile is False and type(native_point_profile_version) is int and native_point_profile_version==1 and type(native_identity_diagnostic) is int and native_identity_diagnostic==0, 'Source selection cannot mix legacy point profiles'
            native_point_profile=True;native_point_profile_version=4
        assert type(native_point_profile) is bool
        assert type(native_point_profile_version) is int and native_point_profile_version in ((1,2,4) if source_selection is not None else (1,2))
        assert native_point_profile_version==1 or native_point_profile
        assert type(native_identity_diagnostic) is int and native_identity_diagnostic in (0,3)
        assert not native_identity_diagnostic or native_point_profile and native_point_profile_version==2
        self._native_identity_diagnostic=native_identity_diagnostic
        self._native_point_profile_version=native_point_profile_version
        self._native_point_profile=self._physical_file_refresh=native_point_profile
        self._provider_creator=None;self._msaa_lease=None
        self.provider_client=None
        self._uia=None;self._provider_started=self._provider_closed=False
        self.interop={} if interop is None else interop
        self._identity_scope=None;self._identity_refs={};self._uses_comparison=False
        creator=NativeActivationProbe.__init__;loader=getattr(C,'WinDLL',None)
        creator(self,deadline,clock,**libraries)
        H,D,B=C.c_void_p,C.c_uint32,C.c_int32
        signatures=[('GetWindow',(H,D),H),('GetWindowTextW',(H,C.c_wchar_p,B),B),
            ('GetClassNameW',(H,C.c_wchar_p,B),B),('IsChild',(H,H),B),('GetPropW',(H,C.c_wchar_p),H),
            ('GetMenuBarInfo',(H,B,B,C.POINTER(MenuBarInfo)),B),
            ('GetGUIThreadInfo',(D,C.POINTER(GuiThreadInfo)),B)]
        for name,args,result in signatures:
            function=getattr(self.user,name);function.argtypes,function.restype=args,result
        self._native_exports=()
        if (creator is _OWNED_ACTIVATION_INIT and loader is not None and loader is _OWNED_WINDLL_TYPE
                and getattr(C,'WinDLL',None) is loader):
            entries=[]
            for role,dll,names in (('user','user32',_NATIVE_USER_EXPORTS+tuple(row[0] for row in signatures)),
                                   ('kernel','kernel32',_NATIVE_KERNEL_EXPORTS),
                                   ('dwm','dwmapi',('DwmGetWindowAttribute',))):
                library=vars(self).get(role)
                if libraries.get(role) is not None or type(library) is not _OWNED_WINDLL_TYPE:continue
                cached=vars(library);pointer=cached.get('_FuncPtr')
                if type(cached.get('_name')) is not str or cached['_name']!=dll:continue
                for name in names:
                    function=cached.get(name)
                    try:
                        owners=function._objects;args=function.argtypes;result=function.restype;flags=function._flags_
                        if (type(function) is not pointer or pointer.__call__ is not _OWNED_CFUNC_CALL
                                or type(owners) is not dict or owners.get('0') is not library
                                or type(args) is not tuple or type(getattr(function,'__name__',None)) is not str or function.__name__!=name
                                or type(flags) is not int or flags!=(loader._func_flags_|C._FUNCFLAG_USE_LASTERROR)
                                or getattr(function,'errcheck',None) is not None):continue
                    except Exception:continue
                    entries.append((role,library,dll,name,function,pointer,owners,args,result,flags))
            self._native_exports=tuple(entries)
        self.keyboard_probe=None
    def _native_timeout_exempt(self,function,context):
        if type(context) is not dict or type(context.get('apiCode')) is not int or context['apiCode']!=0:return False
        if _OWNED_WINDLL_TYPE is None or getattr(C,'WinDLL',None) is not _OWNED_WINDLL_TYPE:return False
        for role,library,dll,name,admitted,pointer,owners,args,result,flags in getattr(self,'_native_exports',()):
            if function is not admitted:continue
            try:
                cached=vars(library)
                return (vars(self).get(role) is library and type(library) is _OWNED_WINDLL_TYPE
                    and type(cached.get('_name')) is str and cached['_name']==dll and cached.get('_FuncPtr') is pointer and cached.get(name) is function
                    and type(function) is pointer and pointer.__call__ is _OWNED_CFUNC_CALL
                    and function._objects is owners and owners.get('0') is library
                    and function.argtypes is args and function.restype is result and type(function._flags_) is int and function._flags_==flags
                    and type(getattr(function,'__name__',None)) is str and function.__name__==name and getattr(function,'errcheck',None) is None)
            except Exception:return False
        return False
    @property
    def uia(self):
        if not getattr(self,'_provider_closed',False):self._ensure_provider()
        return getattr(self,'_uia',None)
    @uia.setter
    def uia(self,value):self._uia=value
    def _ensure_provider(self):
        if getattr(self,'_uia',None) is not None:return
        assert not getattr(self,'_provider_started',False) and not getattr(self,'_provider_closed',False), 'Private native UIA initialization cannot repeat'
        assert self.clock()<self.deadline, 'Native UIA initialization exceeded the original deadline'
        self._provider_started=True
        try:
            import comtypes.client
            self._hresult_type=comtypes.HRESULT
            installed=getattr(comtypes,'__version__',None)
            match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)',installed) if type(installed) is str else None
            observed=[int(n) for n in match.groups()] if match else []
            self.interop.update(versionTuple=observed,versionObserved=bool(match and all(n<=65535 for n in observed)))
            library=self._call(comtypes.client.GetModule,'UIAutomationCore.dll')
            interface=library.IUIAutomation2
            if self._native_point_profile:
                self._uia_library=library
                self._admit_provider_creator()
            self.provider_client=self._call(lambda:comtypes.client.CreateObject(self.CLIENT,interface=interface))
            self._provider_timeout()
            if self._native_point_profile:self._require_provider_creator()
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
        sink=getattr(self,'_diagnostic_sink',None)
        (sink if isinstance(sink,dict) else self.interop)['lastComparison']=observation
        raw=self._uia_call(5,self.uia.iuia.CompareElements,left,right)
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
        self._ensure_provider()
        interop=getattr(self,'interop',None)
        if interop is None:self.interop=interop={}
        observation=dict(versionTuple=copy.deepcopy(interop.get('versionTuple',[])),
            versionObserved=interop.get('versionObserved') is True,declaration=self._declaration(element),
            callSucceeded=False,rawTypeCode=0,length=None,elementTypeCodes=[],empty=False,signed32Valid=False)
        interop['lastRuntimeObservation']=observation
        raw=self._uia_call(3,element.GetRuntimeId);observation['callSucceeded']=True
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
        if getattr(self,'_physical_file_refresh',False) and 'contrast-edit' in self._identity_refs:
            return self._physical_base()
        root=self._root(self._identity_scope['binding']['child'])
        bar=self._discover_bar(root)
        return dict(peer=root,bar=bar,file=self._find(bar,'file',scope='children'),
            **{'contrast-edit':self._find_labels(bar,EDIT_CONTRAST,scope='children')})
    def _physical_base(self):
        """Refresh through an exposed File header, never retained-peer self proof.

        Initial ElementFromHandle admission is still required. A global fresh
        point must identify that retained File, and its live parents must reach
        the original bar and peer. This is not a retry after a provider timeout.
        """
        from suite_window_activation import Point
        binding=self._identity_scope['binding'];refs=self._identity_refs
        assert {'file','bar','peer','contrast-edit'}<=set(refs)
        observation=dict(method='physical-file-header-parent-walk',point=[],physicalHit={},
            fileEqualsRetained=False,differentFrom={},ancestry=[],ownershipBefore=False,ownershipAfter=False)
        self.interop['graphRefresh']=observation
        context,continuity=self._menu_classification_context
        assert context['binding']==binding and context['shellPid']==self._identity_scope['shellPid']
        def owned():
            continuity()
            attachment=self.attachment_snapshot(binding);assert attachment['valid'] is True
            child=self.window_snapshot(binding['child'])
            assert (child['pid'],child['rootHwnd'])==(binding['officePid'],binding['document'])
            assert child['visible'] is child['enabled'] is True
            assert type(child['threadId']) is int and child['threadId']>0
            assert attachment['windows']['child']['threadId']==child['threadId']
            foreground=self.foreground();observation['foregroundHwnd']=foreground
            if foreground!=binding['document']:
                try:self._observe_physical_foreground_mismatch(binding,attachment,child,foreground,observation)
                except BaseException:observation['foregroundMismatchCaptureFailed']=1
            assert foreground==binding['document'], 'Physical File header requires its original foreground document'
            return child
        before=owned();observation['ownershipBefore']=True
        # File header geometry does not consume its native HWND.
        file_row=_getter_call_site(self,1,self._chrome,refs['file'],False)
        assert file_row['pid']==binding['officePid'] and file_row['controlType']=='MenuItem'
        assert file_row['visible'] is file_row['enabled'] is True
        rect=file_row['rectangle'];assert len(rect)==4 and all(type(n) is int for n in rect)
        assert rect[0]<rect[2] and rect[1]<rect[3]
        point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2];observation['point']=point
        hit=int(self._call(self.user.WindowFromPhysicalPoint,Point(*point)) or 0)
        assert hit==binding['child'], 'The physical File header is covered'
        pid=C.c_uint32();thread=self._call(self.user.GetWindowThreadProcessId,hit,C.byref(pid))
        root=int(self._call(self.user.GetAncestor,hit,2) or 0)
        observation['physicalHit']=dict(hwnd=hit,pid=int(pid.value),threadId=thread,rootHwnd=root)
        assert (pid.value,thread,root)==(binding['officePid'],before['threadId'],binding['document'])
        fresh_file=self._uia_call(4,self.uia.iuia.ElementFromPoint,self._point_type(*point))
        observation['fileEqualsRetained']=self._same(fresh_file,refs['file'])
        assert observation['fileEqualsRetained'] is True, 'Global File header identity changed'
        for role,ref in refs.items():
            if role=='file':continue
            same=self._same(fresh_file,ref);observation['differentFrom'][role]=same
            assert same is False, 'Global File header aliases another role'
        cursor=fresh_file;fresh_bar=fresh_peer=None
        for index in range(32):
            kind=self._uia_call(9,lambda:cursor.CurrentControlType)
            owner=self._uia_call(8,lambda:cursor.CurrentProcessId)
            raw=_getter_call_site(self,2,self._uia_call,7,lambda:cursor.CurrentNativeWindowHandle)
            assert type(kind) is type(owner) is int and owner==binding['officePid']
            assert raw is None or type(raw) is int and -(2**31)<=raw<2**32
            hwnd=0 if raw is None else raw&0xffffffff
            observation['ancestry'].append(dict(kindCode=kind,pid=owner,nativeHwnd=hwnd))
            if index==0:assert kind==50011
            elif fresh_bar is None:
                assert kind==50010 and self._same(cursor,refs['bar'])
                fresh_bar=cursor
            elif hwnd==binding['child']:
                assert self._same(cursor,refs['peer']), 'Fresh File ancestry reached a different peer'
                fresh_peer=cursor;break
            else:
                assert kind not in (50011,50010) and hwnd==0, 'Unexpected native File ancestry'
            cursor=self._uia_call(6,self.uia.iuia.ControlViewWalker.GetParentElement,cursor)
            assert cursor, 'Fresh File ancestry is detached'
        assert fresh_bar is not None and fresh_peer is not None, 'Fresh File ancestry exceeded its finite bound'
        fresh=dict(file=fresh_file,bar=fresh_bar,peer=fresh_peer,
            **{'contrast-edit':self._find_labels(fresh_bar,EDIT_CONTRAST,scope='children')})
        assert owned()==before, 'Original File window generation changed'
        observation['ownershipAfter']=True
        return fresh
    def _observe_physical_foreground_mismatch(self,binding,attachment,child,foreground,observation):
        """One numeric native observation; it never qualifies or permits a popup."""
        value=dict(schemaVersion=1,statusCode=0,knownPartial=1,popupQualified=0,
            bindingBefore=0,bindingAfter=0,foregroundSame=0,foreground={},
            ownerStopCode=0,owners=[],engineGui={},stageCode=0)
        observation['foregroundMismatch']=value
        def budget():
            if self._provider_pending() or self.deadline-self.clock()<=.05:raise TimeoutError()
        def read(function,*args):
            budget()
            # Native-only: do not configure UIA timeouts or overwrite its call record.
            try:result=NativeActivationProbe._call(self,function,*args)
            except BaseException:
                budget()
                raise
            budget();return result
        def window(hwnd):
            self._required(read(self.user.IsWindow,hwnd),'Diagnostic window')
            pid=C.c_uint32();tid=int(read(self.user.GetWindowThreadProcessId,hwnd,C.byref(pid)))
            self._required(tid,'Diagnostic window thread')
            root=int(read(self.user.GetAncestor,hwnd,2) or 0)
            self._required(root,'Diagnostic window root')
            return dict(hwnd=hwnd,pid=int(pid.value),threadId=tid,rootHwnd=root)
        try:
            budget();value['stageCode']=1
            assert attachment['valid'] is True and attachment['binding']==binding
            expected=attachment['windows']
            assert (child['pid'],child['threadId'],child['rootHwnd'])==(binding['officePid'],expected['child']['threadId'],binding['document'])
            for role in ('document','parent','child'):
                row=expected[role]
                assert row['hwnd']==binding[role] and row['rootHwnd']==binding['document']
                assert all(type(row[k]) is int and row[k]>0 for k in ('hwnd','pid','threadId','rootHwnd'))
            assert expected['document']['pid']==expected['parent']['pid']==self._identity_scope['shellPid']
            value['bindingBefore']=1
            value['stageCode']=2
            raw=int(read(self.user.GetForegroundWindow) or 0)
            root=int(read(self.user.GetAncestor,raw,2) or 0) if raw else 0
            value['foreground']=dict(rawHwnd=raw,rootHwnd=root)
            if root!=foreground:value['statusCode']=5;return
            value['stageCode']=3;cursor=root;seen=set()
            for _ in range(16):
                if not cursor:value['ownerStopCode']=1;break
                if cursor in (binding['child'],binding['document']):value['ownerStopCode']=2;break
                if cursor in seen:value['ownerStopCode']=3;break
                seen.add(cursor);row=window(cursor);value['owners'].append(row)
                row['ownerHwnd']=int(read(self.user.GetWindow,cursor,4) or 0)
                if row['pid']!=binding['officePid']:value['ownerStopCode']=5;break
                cursor=row['ownerHwnd']
            else:value['ownerStopCode']=4
            value['stageCode']=4
            state=GuiThreadInfo(cbSize=C.sizeof(GuiThreadInfo))
            self._required(read(self.user.GetGUIThreadInfo,child['threadId'],C.byref(state)),'Diagnostic engine GUI')
            focus=int(state.focus or 0);pid=C.c_uint32()
            if focus:self._required(read(self.user.GetWindowThreadProcessId,focus,C.byref(pid)),'Diagnostic focus thread')
            value['engineGui']=dict(threadId=child['threadId'],activeHwnd=int(state.active or 0),
                focusHwnd=focus,focusPid=int(pid.value),
                focusRootHwnd=int(read(self.user.GetAncestor,focus,2) or 0) if focus else 0,
                captureHwnd=int(state.capture or 0),menuOwnerHwnd=int(state.menuOwner or 0),flags=int(state.flags))
            value['stageCode']=5
            for role in ('document','parent','child'):
                assert window(binding[role])==expected[role]
            exported=[int(read(self.user.GetPropW,binding['document'],'OpenGeul.Office.'+name+'Hwnd') or 0) for name in ('Parent','Child')]
            assert exported==[binding['parent'],binding['child']]
            assert read(self.user.IsChild,binding['document'],binding['parent']) and read(self.user.IsChild,binding['parent'],binding['child'])
            value['bindingAfter']=1;value['stageCode']=6
            after=int(read(self.user.GetForegroundWindow) or 0)
            after_root=int(read(self.user.GetAncestor,after,2) or 0) if after else 0
            value['foregroundSame']=int((after,after_root)==(raw,root))
            if not value['foregroundSame']:value['statusCode']=5;return
            value.update(statusCode=2,knownPartial=int(value['ownerStopCode']!=2))
        except TimeoutError:value['statusCode']=1
        except BaseException:value['statusCode']=4 if value['stageCode'] in (1,5) else 3
    def _fresh_proof_with_refs(self,target):
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
        return proof,fresh
    def _fresh_proof(self,target):
        return self._fresh_proof_with_refs(target)[0]
    def _observe_call_totals(self,group,code,started,finished,failed,entered,completed):
        """Optional fixed numeric aggregates; no clock read or admission consequence.

        API intervals include provider setup; provider intervals overlap them and
        must not be added to API totals. A throwing callee has no existing final
        clock read, so its timedCount stays zero rather than inventing a duration.
        """
        try:
            if group=='apiCalls':
                code=code.get('apiCode') if type(code) is dict else 0
                if type(code) is not int or not 0<=code<=18:return
            elif group=='providerSteps':
                if type(code) is not int or not 1<=code<=4:return
            elif group!='providerSetup' or type(code) is not int or code!=0:return
            def row(number):
                return dict(code=number,callCount=0,enteredCount=0,completedCount=0,
                    failedCount=0,timedCount=0,elapsedInclusiveMicros=0,clipped=0)
            sink=getattr(self,'_diagnostic_sink',None)
            target=sink if isinstance(sink,dict) else self.interop
            totals=target.setdefault('callTotals',dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,
                apiIncludesProviderSetup=1,intervalsOverlap=1,apiCalls=[],providerSetup=row(0),providerSteps=[]))
            if type(totals) is not dict:return
            if group=='providerSetup':current=totals[group]
            else:
                rows=totals[group];limit=19 if group=='apiCalls' else 4
                if type(rows) is not list or len(rows)>limit:return
                if any(type(item) is not dict or type(item.get('code')) is not int for item in rows):return
                found=[item for item in rows if item['code']==code]
                if len(found)>1:return
                if found:current=found[0]
                else:
                    if len(rows)==limit:return
                    current=row(code);rows.append(current);rows.sort(key=lambda item:item['code'])
            keys=('callCount','enteredCount','completedCount','failedCount','timedCount')
            if (type(current) is not dict or any(type(current.get(key)) is not int or not 0<=current[key]<=65535 for key in keys)
                    or type(current.get('elapsedInclusiveMicros')) is not int or not 0<=current['elapsedInclusiveMicros']<=5000000
                    or type(current.get('clipped')) is not int or current['clipped'] not in (0,1)):return
            timed=False;micros=0;clipped=current['clipped']
            try:
                if (type(started) in (int,float) and type(finished) in (int,float)
                        and math.isfinite(started) and math.isfinite(finished)):
                    duration=finished-started
                    if math.isfinite(duration) and duration>=0:
                        timed=True;micros=5000000 if duration>=5 else int(duration*1000000)
                        clipped|=int(duration>5)
            except (OverflowError,ValueError):pass
            for key,increment in zip(keys,(1,int(bool(entered)),int(bool(completed)),int(bool(failed)),int(timed))):
                value=current[key]+increment;clipped|=int(value>65535);current[key]=min(value,65535)
            value=current['elapsedInclusiveMicros']+micros
            current.update(elapsedInclusiveMicros=min(value,5000000),clipped=clipped|int(value>5000000))
        except BaseException:pass  # Observation must not replace a result or primary exception.
    def _provider_timeout(self):
        started=self.clock();remaining=self.deadline-started;finished=None;failed=True
        try:
            # Connection and transaction timeouts can both be consumed by a request.
            # Reserve half the remaining time for readback, validation and cleanup.
            milliseconds=int((remaining*1000-1)//4)
            # Only values already computed/read by this exact call are diagnostic.
            # Mask bits1/2 cover remaining/request;4/8 cover typed readbacks.
            budget=None;context=getattr(self,'_observed_call',None)
            if isinstance(context,dict):
                try:
                    budget=dict(schemaVersion=1,remainingMicros=int(remaining*1000000),requestedMs=milliseconds,
                        connectionReadbackMs=0,transactionReadbackMs=0,observedMask=3,verifiedMask=0,setupComplete=0)
                    context['providerBudget']=budget
                except Exception:budget=None
            assert 1<=milliseconds<=1250, 'Native UIA provider query budget expired'
            for index,name in enumerate(('ConnectionTimeout','TransactionTimeout')):
                step_started=self.clock()
                assert step_started<self.deadline, 'Native UIA timeout setup deadline expired'
                context=getattr(self,'_observed_call',None)
                if isinstance(context,dict):context['providerStep']=index*2+1
                step_finished=None;step_failed=True;completed=False
                try:
                    setattr(self.provider_client,name,milliseconds);completed=True
                    step_finished=self.clock()
                    assert step_finished<self.deadline, 'Native UIA timeout setter exceeded deadline'
                    step_failed=False
                finally:self._observe_call_totals('providerSteps',index*2+1,step_started,step_finished,step_failed,True,completed)
                if isinstance(context,dict):context['providerStep']=index*2+2
                step_started=step_finished;step_finished=None;step_failed=True;completed=False
                try:
                    observed=getattr(self.provider_client,name);completed=True
                    if budget is not None and type(observed) is int:
                        budget['connectionReadbackMs' if index==0 else 'transactionReadbackMs']=observed
                        budget['observedMask']|=4<<index
                    step_finished=self.clock()
                    assert step_finished<self.deadline, 'Native UIA timeout readback exceeded deadline'
                    assert type(observed) is int and observed==milliseconds, 'Native UIA provider timeout was not accepted'
                    if budget is not None:budget['verifiedMask']|=1<<index
                    step_failed=False
                finally:self._observe_call_totals('providerSteps',index*2+2,step_started,step_finished,step_failed,True,completed)
            finished=self.clock()
            assert 2*milliseconds<(self.deadline-finished)*1000, \
                'Native UIA timeout setup exhausted the original query budget'
            self.provider_timeout_verified=True
            if budget is not None:budget['setupComplete']=1
            failed=False
        finally:
            # completedCount here means all property operations returned and the
            # existing final clock was reached, not that setup passed its guards.
            self._observe_call_totals('providerSetup',0,started,finished,failed,True,finished is not None)
    def _call(self,function,*args):
        previous=getattr(self,'_observed_call',None);sink=getattr(self,'_diagnostic_sink',None)
        context=previous if isinstance(previous,dict) else self._call_record(0)
        native_only=(previous is None or type(previous) is dict) and self._native_timeout_exempt(function,context)
        if native_only and context is previous:context=self._call_record(0)
        self._observed_call=context
        started=finished=None;failed=True;entered=completed=False
        try:
            if not isinstance(sink,dict):self._last_call_exception=None
            if context is not None:
                try:(sink if isinstance(sink,dict) else self.interop)['lastCall']=context
                except BaseException:pass
            started=self.clock()
            assert started<self.deadline, 'Native menu query deadline expired'
            if context is not None:context['phaseCode']=1
            if getattr(self,'provider_client',None) is not None and not (native_only and self._native_timeout_exempt(function,context)):self._provider_timeout()
            if function is getattr(getattr(self,'user',None),'SendMessageTimeoutW',None):
                assert type(args[5]) is int and 1<=args[5]<=int((self.deadline-self.clock())*1000), 'Owned hit-test wait exceeds remaining query budget'
            if context is not None:context.update(phaseCode=2,calleeEntered=True)
            entered=True;value=function(*args);completed=True
            if context is not None:context.update(phaseCode=3,callCompleted=True)
            finished=self.clock()
            assert finished<self.deadline, 'Native menu query exceeded original deadline'
            if context is not None:context['phaseCode']=4
            failed=False
            return value
        except BaseException as exc:
            if context is not None:
                context.update(failed=True,**self._exception_numbers(exc))
                try:(sink if isinstance(sink,dict) else self.interop)['lastCall']=context
                except BaseException:pass
            if not isinstance(sink,dict):self._last_call_exception=exc
            raise
        finally:
            self._observed_call=previous
            self._observe_call_totals('apiCalls',context,started,finished,failed,entered,completed)
    def _call_record(self,code):
        target=getattr(self,'_active_target',None)
        record=dict(apiCode=code,targetCode=tuple(LABELS).index(target)+1 if target in LABELS else 0,
            phaseCode=0,providerStep=0,calleeEntered=False,callCompleted=False,failed=False,hresultObserved=False)
        if code==7:
            site=getattr(self,'_getter_site_code',0)
            record['getterSiteCode']=site if type(site) is int and site in _GETTER_SITE_CODES else 0
        return record
    @staticmethod
    def _exception_numbers(exc):
        result=dict(exceptionCode=1 if isinstance(exc,AssertionError) else 2 if type(exc).__name__=='COMError' else 3,hresultObserved=False)
        try:
            value=getattr(exc,'hresult',None)
            if type(value) is int and -(2**31)<=value<2**32:
                result.update(hresultObserved=True,hresult=value if value<2**31 else value-2**32)
        except BaseException:pass
        return result
    def _uia_call(self,code,function,*args):
        self._ensure_provider()
        previous=getattr(self,'_observed_call',None);self._observed_call=self._call_record(code)
        try:return self._call(function,*args)
        finally:self._observed_call=previous
    def capture_primary_failure(self,exc):
        # A caught optional query error is not the exception escaping this action.
        self.interop['primaryFailureCall']=copy.deepcopy(self.interop.get('lastCall',{}))
        self.interop['primaryFailureFromApi']=getattr(self,'_last_call_exception',None) is exc
        self.interop['primaryFailure']=self._exception_numbers(exc)
    def close_provider(self):
        if self._provider_pending():
            self.interop['providerRetainedForPending']=True
            return False  # The global capsule keeps this whole original probe.
        # Drop all owned element/client references. No shared client was changed.
        self._provider_closed=True
        for name in ('file_element','menu_bar_element','peer_element','current_control','_retained','uia','provider_client','_identity_refs','_menu_classification_context','_failure_point','_diagnostic_sink','_observed_call','_last_call_exception'):
            if hasattr(self,name):setattr(self,name,None)
        return True
    def _provider_pending(self):
        # Startup registers globally before returning the lease to this probe.
        # A BaseException in that handoff must not permit COM calls or release.
        try:
            lease=getattr(self,'_msaa_lease',None)
            if lease is not None and lease.pending is not False:return True
            if getattr(self,'_native_point_profile',False):
                from native_menu_msaa_hit import pending_msaa_hit
                if pending_msaa_hit() is not None:return True
            return False
        except BaseException:return True
    def _condition(self,*,control_type,name=None):
        kinds={'MenuBar':50010,'MenuItem':50011,'Text':50020,'Button':50000,'ToolBar':50021}
        assert control_type in kinds and (name is None or type(name) is str and len(name)<=256)
        condition=self._uia_call(13,self.uia.iuia.CreatePropertyCondition,30003,kinds[control_type])
        if name is not None:
            label=self._uia_call(13,self.uia.iuia.CreatePropertyCondition,30005,name)
            condition=self._uia_call(14,self.uia.iuia.CreateAndCondition,condition,label)
        return condition
    def _root(self,hwnd):
        self._ensure_provider()
        return self._uia_call(1,self.uia.iuia.ElementFromHandle,hwnd)
    def _mta_snapshot(self):
        ole=C.WinDLL('ole32');function=ole.CoGetApartmentType
        function.argtypes,function.restype=(C.POINTER(C.c_int32),C.POINTER(C.c_int32)),C.c_int32
        kind=C.c_int32(-1);qualifier=C.c_int32(-1)
        # The creator guard must not configure or query the COM client it guards.
        assert self.clock()<self.deadline, 'Native menu query deadline expired'
        hr=function(C.byref(kind),C.byref(qualifier))
        assert self.clock()<self.deadline, 'Native menu query exceeded original deadline'
        thread=self.kernel.GetCurrentThreadId;thread.argtypes,thread.restype=(),C.c_uint32
        assert self.clock()<self.deadline, 'Native menu query deadline expired'
        thread_id=thread()
        assert self.clock()<self.deadline, 'Native menu query exceeded original deadline'
        return thread_id,hr==0 and kind.value==1
    def _admit_provider_creator(self):
        assert getattr(self,'_provider_creator',None) is None, 'The private client creator cannot change'
        thread,mta=self._mta_snapshot()
        assert type(thread) is int and thread>0 and mta is True, 'The private client must originate in this MTA'
        self._provider_creator=dict(threadId=thread,mta=True)
        self.interop['providerCreator']=dict(self._provider_creator)
    def _require_provider_creator(self):
        original=self._provider_creator;thread,mta=self._mta_snapshot()
        assert original and original['mta'] is mta is True and original['threadId']==thread
        return dict(original,sameThread=True)
    def _begin_point_lease(self,file,target,negative,scope_id,point,*,fresh_refs=None):
        version=getattr(self,'_native_point_profile_version',1)
        assert type(version) is int and version in (1,2)
        assert getattr(self,'_native_point_profile',False) is True
        role=_target_role(self._active_target)
        if version==2:
            assert type(fresh_refs) is dict and set(fresh_refs)==set(self._identity_refs)
            assert file is self._identity_refs['file'] and target is fresh_refs[role]
        else:assert fresh_refs is None
        from native_menu_msaa_hit import SdkAbi,MsaaHitScope,MsaaHitSource,MsaaHitSourceV2,begin_msaa_hit
        from comtypes import GUID,HRESULT
        from comtypes.automation import VARIANT
        library=self._uia_library;legacy=library.IUIAutomationLegacyIAccessiblePattern
        method=next(item for item in vars(legacy)['_methods_'] if item.name=='GetIAccessible')
        accessible=method.argtypes[0]._type_.__com_interface__
        sdk=SdkAbi(client_interface=library.IUIAutomation,element_interface=library.IUIAutomationElement,
            legacy_interface=legacy,accessible_interface=accessible,guid_type=GUID,hresult_type=HRESULT,
            variant_type=VARIANT,function_factory=C.WINFUNCTYPE)
        scope=self._identity_scope;binding=scope['binding']
        if version==2:
            source=MsaaHitSourceV2(self.provider_client,file,fresh_refs['file'],fresh_refs[role],
                self._identity_refs[role],tuple(negative),self._point_source['shellHandle'],
                self._point_source['engineHandle'],keepalive=(self,fresh_refs))
        else:
            source=MsaaHitSource(self.provider_client,file,target,self._identity_refs[role],tuple(negative),
                self._point_source['shellHandle'],self._point_source['engineHandle'],keepalive=(self,))
        request=MsaaHitScope(scope_id,binding['officePid'],scope['officeCreationTime'],scope['shellPid'],
            scope['shellCreationTime'],binding['parent'],binding['child'],*point)
        return begin_msaa_hit(source,request,sdk,self.deadline,native_enabled=True,profile_version=version)
    def _provider_local_point(self,point,target,actual):
        from dataclasses import asdict
        assert getattr(self,'_native_point_profile',False) is True and self._active_target!='file'
        version=getattr(self,'_native_point_profile_version',1)
        assert type(version) is int and version in (1,2)
        creator=self._require_provider_creator();scope=self._identity_scope;binding=scope['binding']
        role=_target_role(self._active_target)
        global_point=dict(kindCode=self._uia_call(9,lambda:actual.CurrentControlType),
            pid=self._uia_call(8,lambda:actual.CurrentProcessId),nativeHwnd=_getter_call_site(self,3,self._uia_call,7,lambda:actual.CurrentNativeWindowHandle))
        assert global_point['kindCode']==50033 and global_point['pid']==binding['officePid']
        rectangle=_getter_call_site(self,4,self._chrome,target)['rectangle'];before=self._popup_exposure(binding,point,rectangle)
        assert global_point['nativeHwnd']==before['hwnd']
        source_fresh=fresh_refs=None
        if version==2:
            source_fresh,fresh_refs=self._fresh_proof_with_refs(self._active_target)
            assert self._same(target,fresh_refs[role]), 'Current native target differs from independently fresh target'
        roles=[key for key in self._identity_refs if key!=role]
        negative=[self._identity_refs[key] for key in roles]+[actual]
        sequence=getattr(self,'_point_sequence',0)+1;assert sequence<=32;self._point_sequence=sequence
        if version==2:
            lease=self._begin_point_lease(self._identity_refs['file'],fresh_refs[role],negative,sequence,point,fresh_refs=fresh_refs)
        else:lease=self._begin_point_lease(self.file_element,target,negative,sequence,point)
        self._msaa_lease=lease
        provider=lease.wait()
        self.interop['providerLocalResult']=provider
        assert not lease.pending, 'The native menu provider call is unretired'
        if version==2:
            from native_menu_msaa_hit import _record
            assert type(provider) is dict and provider.keys()==_record(None,False,profile_version=2).keys()
            assert type(provider.get('schemaVersion')) is int and provider['schemaVersion']==2
            assert type(provider.get('workerSchemaVersion')) is int and provider['workerSchemaVersion']==2
        assert provider['localKnown']==provider['localMatch']==1, 'The native menu provider point is unknown'
        assert provider['nativeExit']==provider['threadClosed']==provider['processesClosed']==provider['workerCleanup']==1
        assert provider['stageCode']==13 and self.clock()<self.deadline
        assert self._require_provider_creator()==creator
        after=self._popup_exposure(binding,point,rectangle);assert before==after
        fresh=self._fresh_proof(self._active_target)
        result=dict(schemaVersion=version,method='owned-popup-and-msaa-hit' if version==1 else 'owned-popup-and-msaa-canonical-hit-v2',scope=copy.deepcopy(scope),role=role,
            sourceScopeId=sequence,sourceScope=asdict(lease.scope),negativeRoles=roles+['global-point'],
            provider=provider,before=before,after=after,fresh=fresh,creator=creator,globalPoint=global_point)
        if version==2:result['sourceFresh']=source_fresh
        return result
    def _begin_identity_diagnostic_lease(self,fresh_refs,negative,scope_id,point,*,captured_at,action_deadline,exposure):
        """Separate profile3 source; never passes mode3 to a positive factory."""
        assert getattr(self,'_native_identity_diagnostic',0)==3
        assert type(fresh_refs) is dict and set(fresh_refs)==set(self._identity_refs)
        from native_menu_msaa_hit import Ia2SdkAbi,MsaaHitScope,MsaaHitSourceV3,begin_ia2_diagnostic
        from comtypes import GUID,HRESULT
        from comtypes.automation import VARIANT
        library=self._uia_library;legacy=library.IUIAutomationLegacyIAccessiblePattern
        method=next(item for item in vars(legacy)['_methods_'] if item.name=='GetIAccessible')
        accessible=method.argtypes[0]._type_.__com_interface__
        sdk=Ia2SdkAbi(client_interface=library.IUIAutomation,element_interface=library.IUIAutomationElement,
            legacy_interface=legacy,accessible_interface=accessible,guid_type=GUID,hresult_type=HRESULT,
            variant_type=VARIANT,function_factory=C.WINFUNCTYPE)
        scope=self._identity_scope;binding=scope['binding'];role=_target_role(self._active_target)
        source=MsaaHitSourceV3(self.provider_client,self._identity_refs['file'],fresh_refs['file'],
            fresh_refs[role],self._identity_refs[role],tuple(negative),self._point_source['shellHandle'],
            self._point_source['engineHandle'],(self,fresh_refs),captured_at,action_deadline,
            binding['document'],exposure['hwnd'],exposure['threadId'],tuple(exposure['ownerChain']))
        request=MsaaHitScope(scope_id,binding['officePid'],scope['officeCreationTime'],scope['shellPid'],
            scope['shellCreationTime'],binding['parent'],binding['child'],*point)
        return begin_ia2_diagnostic(source,request,sdk,action_deadline,native_enabled=True)
    def _observe_identity_diagnostic(self,point,target,actual):
        """One bounded read observation; every branch is terminal and nonaccepting."""
        control=_identity_diagnostic_control()
        self.interop['identityDiagnosticControl']=control
        action_deadline=self.deadline
        try:
            assert getattr(self,'_native_identity_diagnostic',0)==3 and self._active_target=='save'
            assert not getattr(self,'_identity_diagnostic_attempted',False), 'A diagnostic lease cannot repeat'
            self._identity_diagnostic_attempted=True
            assert not self._provider_pending(), 'A previous callback remains unretired'
            creator=self._require_provider_creator();scope=self._identity_scope;binding=scope['binding']
            assert self._uia_call(9,lambda:actual.CurrentControlType)==50033
            assert self._uia_call(8,lambda:actual.CurrentProcessId)==binding['officePid']
            rectangle=_getter_call_site(self,5,self._chrome,target)['rectangle'];before=self._popup_exposure(binding,point,rectangle)
            assert _getter_call_site(self,6,self._uia_call,7,lambda:actual.CurrentNativeWindowHandle)==before['hwnd']
            # Discovery consumes this same narrowed expiry; it is never reset.
            captured_at=self.clock();effective=min(action_deadline,captured_at+1.5)
            self.deadline=effective
            source_fresh,fresh_refs=self._fresh_proof_with_refs(self._active_target)
            assert self.clock()<effective
            role=_target_role(self._active_target)
            assert self._same(target,fresh_refs[role]), 'Current diagnostic target differs from the fresh binding'
            negative=[ref for key,ref in self._identity_refs.items() if key!=role]+[actual]
            sequence=getattr(self,'_point_sequence',0)+1;assert sequence<=32;self._point_sequence=sequence
            control.update(leaseAttempted=1,terminalCode=2)
            lease=self._begin_identity_diagnostic_lease(fresh_refs,negative,sequence,point,
                captured_at=captured_at,action_deadline=action_deadline,exposure=before)
            self._msaa_lease=lease
            packet=lease.wait()
            retained=_identity_diagnostic_packet(packet)
            assert packet['scopeId']==sequence, 'Diagnostic packet belongs to another source'
            if packet['diagnosticComplete']==1:
                assert packet['negativeCount']==packet['negativeRejected']==len(negative)
            self.interop['identityDiagnosticResult']=retained
            control['pending']=int(lease.pending is not False)
            assert lease.pending is False and packet['pending']==0
            assert self.clock()<effective, 'The diagnostic source age expired'
            if packet['diagnosticComplete']!=1:return
            assert all(packet[key]==1 for key in ('nativeExit','threadClosed','processesClosed','workerCleanup'))
            assert packet['stageCode']==13
            assert self._require_provider_creator()==creator
            after=self._popup_exposure(binding,point,rectangle);assert before==after
            self._fresh_proof(self._active_target)
            assert self.clock()<effective
            control.update(postScopeVerified=1,diagnosticComplete=1,terminalCode=3)
        except BaseException:
            control['terminalCode']=4
        finally:
            self.deadline=action_deadline
            # This marker is distinct from the observation retry exception.
            raise NativeIdentityDiagnosticTerminal('Read-only identity diagnostic ended') from None
    def _popup_exposure(self,binding,point,target_rect):
        """The exact pinned VCL popup at a physical point, not target identity.

        core bf6ef266 vcl/inc/win/saldata.hxx and win/window/salframe.cxx:
        undecorated menu floaters use SALTMPSUBFRAME/WS_POPUP/TOOLWINDOW.
        An unknown class is represented only by a failed fixed class code.
        """
        from suite_window_activation import Point
        scope,continuity=self._menu_classification_context
        assert scope['binding']==binding
        continuity()
        assert self.attachment_snapshot(binding)['valid'] is True
        child=self.window_snapshot(binding['child'])
        assert (child['pid'],child['rootHwnd'])==(binding['officePid'],binding['document'])
        hit=int(self._call(self.user.WindowFromPhysicalPoint,Point(*point)) or 0)
        assert hit and hit not in (binding['document'],binding['parent'],binding['child'])
        popup=self.window_snapshot(hit)
        assert (popup['pid'],popup['rootHwnd'],popup['threadId'])==(binding['officePid'],hit,child['threadId'])
        assert popup['visible'] is popup['enabled'] is True
        assert popup['iconic'] is False and popup['cloaked']==0
        rect=popup['rectangle']
        assert len(rect)==len(target_rect)==4 and all(type(n) is int for n in (*rect,*target_rect,*point))
        assert rect[0]<=target_rect[0]<target_rect[2]<=rect[2]
        assert rect[1]<=target_rect[1]<target_rect[3]<=rect[3]
        assert target_rect[0]<=point[0]<target_rect[2] and target_rect[1]<=point[1]<target_rect[3]
        name=C.create_unicode_buffer(64)
        count=self._call(self.user.GetClassNameW,hit,name,len(name))
        class_code=int(type(count) is int and 0<count<len(name) and name.value=='SALTMPSUBFRAME')
        assert class_code==1, 'Physical menu popup class is unconfirmed'
        function=self.user.GetWindowLongW
        function.argtypes,function.restype=(C.c_void_p,C.c_int32),C.c_int32
        style=self._call(function,hit,-16)&0xffffffff
        extended=self._call(function,hit,-20)&0xffffffff
        assert style&0x80000000 and not style&0x40000000 and extended&0x80
        owners=self._owners(hit,binding)
        assert 2<=len(owners)<=16 and owners[0]==hit and owners[-1] in (binding['child'],binding['document'])
        foreground=self.foreground();assert foreground in (binding['document'],hit)
        gui=self.native_focus(child['threadId'])
        assert gui['focusPid']==binding['officePid'] and gui['focusRootHwnd'] in (binding['document'],hit)
        assert gui['captureHwnd'] in (0,binding['child'],hit) and gui['menuOwnerHwnd'] in (0,binding['child'],hit)
        continuity();assert self.attachment_snapshot(binding)['valid'] is True
        assert self.window_snapshot(binding['child'])==child and self.window_snapshot(hit)==popup
        assert self.foreground()==foreground
        return dict(classCode=class_code,hwnd=hit,pid=popup['pid'],threadId=popup['threadId'],
            rootHwnd=hit,style=style,extendedStyle=extended,rectangle=list(rect),point=list(point),
            ownerChain=owners,foreground=foreground,ownershipBefore=True,ownershipAfter=True)
    def point_snapshot(self,scope,point,control):
        from suite_window_activation import Point
        admission=_source_bound_admission(self) if getattr(self,'source_selection',None) is not None else None
        observation=dict(targetCode=tuple(LABELS).index(self._active_target)+1,stageCode=1,
            point=list(point),failed=False,primary={})
        try:self.interop['pointObservation']=observation
        except BaseException:pass
        actual=target=original=None
        diagnostic=getattr(self,'_native_identity_diagnostic',0)==3 and self._active_target!='file'
        if diagnostic:
            if getattr(self,'_identity_diagnostic_point_seen',False):
                raise NativeIdentityDiagnosticTerminal('The diagnostic point cannot be observed again')
            self._identity_diagnostic_point_seen=True
            self.interop['identityDiagnosticControl']=_identity_diagnostic_control()
        try:
            hit=int(self._call(self.user.WindowFromPhysicalPoint,Point(*point)) or 0);pid=C.c_uint32()
            if hit:self._required(self._call(self.user.GetWindowThreadProcessId,hit,C.byref(pid)),'Physical native menu hit PID')
            observation['stageCode']=2
            target=control.element_info._element;row=_getter_call_site(self,7,self._chrome,target);handle=row['nativeHwnd']
            kinds={'Button':50000,'MenuBar':50010,'MenuItem':50011,'ToolBar':50021,'Window':50032}
            observation['target']=dict(kindCode=kinds.get(row['controlType'],0),pid=row['pid'],nativeHwnd=handle,
                rectangle=list(row['rectangle']),enabled=row['enabled'],visible=row['visible'])
            observation['stageCode']=3
            actual=self._uia_call(4,self.uia.iuia.ElementFromPoint,self._point_type(*point))
            observation['stageCode']=4
            match=self._same(target,actual);observation['primary']['rawMatchesTarget']=match
            observation['stageCode']=5
            result=dict(point=list(point),hitHwnd=hit,pid=int(pid.value),
                rootHwnd=int(self._call(self.user.GetAncestor,hit,2) or 0) if hit else 0,
                withinControl=bool(hit and (hit==handle or handle and self._call(self.user.IsChild,handle,hit) or not handle and match)),uiaMatches=match)
            observation.update(nativeHitHwnd=result['hitHwnd'],nativeHitPid=result['pid'],nativeRootHwnd=result['rootHwnd'])
            if getattr(self,'_uses_comparison',False):
                role=_target_role(self._active_target);original=self._identity_refs[role]
                proof=dict(scope=copy.deepcopy(self._identity_scope),role=role,differentFrom={});result['identityProof']=proof
                observation['stageCode']=6
                proof['targetEqualsRetained']=self._same(target,original)
                observation['primary']['targetEqualsRetained']=proof['targetEqualsRetained']
                observation['stageCode']=7
                proof['hitEqualsRetained']=self._same(actual,original)
                observation['primary']['hitEqualsRetained']=proof['hitEqualsRetained']
                observation['stageCode']=8;observation['primary']['differentFrom']=[]
                for key,ref in self._identity_refs.items():
                    if key==role:continue
                    proof['differentFrom'][key]=self._same(actual,ref)
                    observation['primary']['differentFrom'].append([IDENTITY_ROLES.index(key)+1,proof['differentFrom'][key]])
                observation['stageCode']=9
                if diagnostic:
                    if (match is False and proof['targetEqualsRetained'] is True and proof['hitEqualsRetained'] is False
                            and all(value is False for value in proof['differentFrom'].values())):
                        self._observe_identity_diagnostic(point,target,actual)
                    self.interop['identityDiagnosticControl']['terminalCode']=5
                    raise NativeIdentityDiagnosticTerminal('The fixed diagnostic source is unavailable')
                if (getattr(self,'_native_point_profile',False) and self._active_target!='file' and
                        match is False and proof['targetEqualsRetained'] is True and proof['hitEqualsRetained'] is False and
                        all(value is False for value in proof['differentFrom'].values())):
                    version=getattr(self,'_native_point_profile_version',1)
                    assert type(version) is int and version in (1,2,4)
                    if version==4:
                        assert admission is not None
                        result['pointMethod']='owned-popup-and-source-qualified-ia2-hit-v4'
                        result['providerLocalProof']=self._provider_local_point_v4(point,target,actual,admission=admission)
                        result['pointObservedAt']=self.clock()
                    else:
                        result['pointMethod']='owned-popup-and-msaa-hit' if version==1 else 'owned-popup-and-msaa-canonical-hit-v2'
                        result['providerLocalProof']=self._provider_local_point(point,target,actual)
                else:assert result['identityProof']['targetEqualsRetained'] is result['identityProof']['hitEqualsRetained'] is True
                observation['stageCode']=10
                assert all(value is False for value in result['identityProof']['differentFrom'].values())
            observation['stageCode']=11
            if diagnostic:raise NativeIdentityDiagnosticTerminal('The diagnostic has no retained identity scope')
            return result
        except BaseException as exc:
            observation.update(failed=True,**self._exception_numbers(exc))
            self._failure_point=(actual,original if original is not None else target)
            try:
                if diagnostic or admission is not None:raise NativeIdentityDiagnosticTerminal('Late failure observations are suppressed')
                self.capture_primary_failure(exc)
                observation['primaryCall']=copy.deepcopy(self.interop.get('primaryFailureCall',{}))
                observation['primaryComparison']=copy.deepcopy(self.interop.get('lastComparison',{}))
            except BaseException:pass
            if diagnostic and not isinstance(exc,NativeIdentityDiagnosticTerminal):
                raise NativeIdentityDiagnosticTerminal('Diagnostic point failed before input') from None
            raise
    def observe_failure_context(self,binding):
        if getattr(self,'_native_identity_diagnostic',0)==3:
            self.interop['failureContext']=dict(diagnosticProfile=3,providerQueriesSuppressed=1)
            return
        if getattr(self,'_failure_context_recorded',False):return
        self._failure_context_recorded=True
        if self._provider_pending():
            self.interop['failureContext']=dict(providerPending=1,providerQueriesSuppressed=1)
            return
        diagnostic=dict(guiStatus=0,pointStatus=0,parentQueries=0,nodes=[],
            ownershipPostStatus=0,ownershipPostVerified=False)
        self.interop['failureContext']=diagnostic
        point=self.interop.get('pointObservation')
        if isinstance(point,dict) and point.get('failed') is True:point['diagnostic']=diagnostic
        if self.deadline-self.clock()<=.05:
            diagnostic.update(guiStatus=1,pointStatus=1);return
        previous=getattr(self,'_diagnostic_sink',None);self._diagnostic_sink=diagnostic
        def budget():assert self.deadline-self.clock()>.05, 'Failure observation reserve exhausted'
        def ownership():
            budget();scope,continuity=self._menu_classification_context
            assert scope['binding']==binding;continuity()
            child=self.window_snapshot(binding['child'])
            assert (child['hwnd'],child['pid'],child['rootHwnd'])==(binding['child'],binding['officePid'],binding['document'])
            _int(child['threadId']);assert self.attachment_snapshot(binding)['valid'] is True
            return child
        try:
            try:
                child=ownership()
                budget();gui=self.native_focus(child['threadId'])
                diagnostic['gui']={k:gui[k] for k in ('threadId','activeHwnd','focusHwnd','focusPid','focusRootHwnd','captureHwnd','menuOwnerHwnd','flags') if type(gui.get(k)) is int and 0<=gui[k]<2**64}
                budget();foreground=int(self._call(self.user.GetForegroundWindow) or 0);pid=C.c_uint32()
                if foreground:self._required(self._call(self.user.GetWindowThreadProcessId,foreground,C.byref(pid)),'Failure foreground PID')
                diagnostic['foreground']=dict(hwnd=foreground,pid=int(pid.value),rootHwnd=int(self._call(self.user.GetAncestor,foreground,2) or 0) if foreground else 0)
                ownership();diagnostic['guiStatus']=2
            except BaseException as exc:
                diagnostic.update(guiStatus=3,pointStatus=7,guiError=self._exception_numbers(exc));return
            cursor,original=getattr(self,'_failure_point',(None,None))
            if cursor is None or original is None:diagnostic['pointStatus']=4;return
            try:
                for _ in range(8):
                    budget();row={};diagnostic['nodes'].append(row)
                    pid=self._uia_call(8,lambda:cursor.CurrentProcessId);assert type(pid) is int and 0<pid<2**32;row['pid']=pid
                    if pid!=binding['officePid']:diagnostic['pointStatus']=5;return
                    budget();row['kindCode']=self._uia_call(9,lambda:cursor.CurrentControlType)
                    budget();raw=_getter_call_site(self,8,self._uia_call,7,lambda:cursor.CurrentNativeWindowHandle)
                    assert raw is None or type(raw) is int and -(2**31)<=raw<2**32
                    row['nativeHwnd']=0 if raw is None else raw&0xffffffff
                    budget();box=self._uia_call(10,lambda:cursor.CurrentBoundingRectangle)
                    rectangle=[getattr(box,k) for k in ('left','top','right','bottom')]
                    assert type(row['kindCode']) is int and 0<=row['kindCode']<2**16
                    assert all(type(n) is int and -(2**31)<=n<2**31 for n in rectangle);row['rectangle']=rectangle
                    budget();row['equalsRetainedTarget']=self._same(cursor,original)
                    if row['equalsRetainedTarget']:diagnostic['pointStatus']=2;return
                    budget();diagnostic['parentQueries']+=1
                    cursor=self._uia_call(6,self.uia.iuia.ControlViewWalker.GetParentElement,cursor)
                    if not cursor:diagnostic['pointStatus']=2;return
                diagnostic['pointStatus']=6
            except BaseException as exc:diagnostic.update(pointStatus=3,pointError=self._exception_numbers(exc))
            finally:
                if self.deadline-self.clock()<=.05:diagnostic['ownershipPostStatus']=1
                else:
                    try:
                        ownership();diagnostic.update(ownershipPostStatus=2,ownershipPostVerified=True)
                    except BaseException as exc:
                        diagnostic.update(ownershipPostStatus=3,ownershipPostError=self._exception_numbers(exc))
        finally:self._diagnostic_sink=previous
    def _chrome(self,element,include_native_hwnd=True):
        # Ancestor names can contain a document title; query identity only.
        def get(name):
            codes={'CurrentNativeWindowHandle':7,'CurrentProcessId':8,'CurrentControlType':9,
                'CurrentBoundingRectangle':10,'CurrentIsOffscreen':11,'CurrentIsEnabled':12}
            return self._uia_call(codes[name],lambda:getattr(element,name))
        window={}
        if include_native_hwnd:
            handle=get('CurrentNativeWindowHandle')
            assert handle is None or type(handle) is int and -(2**31)<=handle<2**32
            window['nativeHwnd']=0 if handle is None else handle&0xffffffff
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
            **window,
            controlType={50000:'Button',50010:'MenuBar',50011:'MenuItem',50021:'ToolBar',50032:'Window'}.get(kind,str(kind)),
            visible=not bool(get('CurrentIsOffscreen')),enabled=bool(get('CurrentIsEnabled')),
            rectangle=[int(getattr(box,key)) for key in ('left','top','right','bottom')])
        if identity is not None:result['identity']=identity
        return result
    def _find_labels(self,root,labels,*,scope='descendants'):
        target=getattr(self,'_active_target',None)
        row=dict(schemaVersion=1,queryKindCode=2,targetCode=tuple(LABELS).index(target)+1 if target in LABELS else 0,
            candidateCount=0,examinedCount=0,visibleCount=0,matchedCount=0,observedMask=0,scanComplete=0,rejectCode=0)
        try:
            sink=getattr(self,'_diagnostic_sink',None)
            (sink if isinstance(sink,dict) else self.interop)['menuDiscovery']=row
        except Exception:row=None
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuItem'))
        found=self._uia_call(2,root.FindAll,self.uia.tree_scope[scope],condition)
        count=int(self._uia_call(17,lambda:found.Length));assert 0<=count<=512
        if row is not None:row.update(candidateCount=count,observedMask=1)
        matches=[]
        for i in range(count):
            element=self._uia_call(18,found.GetElement,i)
            if row is not None:row['examinedCount']=i+1
            if int(self._uia_call(9,lambda:element.CurrentControlType))!=50011:continue
            if self._uia_call(11,lambda:element.CurrentIsOffscreen):
                if row is not None:row['observedMask']|=2
                continue
            if row is not None:row['visibleCount']+=1;row['observedMask']|=2
            name=str(self._uia_call(16,lambda:element.CurrentName));assert len(name)<=256
            if _label(name) in labels:matches.append(element)
            if row is not None:row['matchedCount']=len(matches);row['observedMask']|=4
        if row is not None:row.update(scanComplete=1,observedMask=row['observedMask']|8,rejectCode=4 if len(matches)>1 else 0)
        assert len(matches)<=1, 'Native chrome target is ambiguous'
        if not matches:
            if row is not None:row['rejectCode']=2
            raise NativeMenuPending('Native chrome target not visible yet')
        if row is not None:row['observedMask']|=16
        return matches[0]
    def _find(self,root,target,*,scope='descendants'):
        assert target in LABELS
        return self._find_labels(root,LABELS[target],scope=scope)
    def _discover_bar(self,root):
        # Ask UIA for chrome only. Never materialize document paragraphs/cells.
        target=getattr(self,'_active_target',None)
        row=dict(schemaVersion=1,queryKindCode=1,targetCode=tuple(LABELS).index(target)+1 if target in LABELS else 0,
            candidateCount=0,examinedCount=0,visibleCount=0,matchedCount=0,observedMask=0,scanComplete=0,rejectCode=0)
        try:
            sink=getattr(self,'_diagnostic_sink',None)
            (sink if isinstance(sink,dict) else self.interop)['menuDiscovery']=row
        except Exception:row=None
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuBar'))
        found=self._uia_call(2,root.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._uia_call(17,lambda:found.Length));assert 0<=count<=8
        if row is not None:row.update(candidateCount=count,observedMask=1)
        bars=[]
        for index in range(count):
            bar=self._uia_call(18,found.GetElement,index)
            if row is not None:row['examinedCount']=index+1
            if not self._uia_call(11,lambda:bar.CurrentIsOffscreen):bars.append(bar)
            if row is not None:row.update(visibleCount=len(bars),matchedCount=len(bars),observedMask=row['observedMask']|6)
        if row is not None:row.update(scanComplete=1,observedMask=row['observedMask']|8,rejectCode=3 if len(bars)>1 else 0)
        assert len(bars)<=1, 'Native menubar is ambiguous'
        if not bars:
            if row is not None:row['rejectCode']=1
            raise NativeMenuPending('Native menubar not visible yet')
        if row is not None:row['observedMask']|=16
        return bars[0]
    def discover_file(self,root):
        self.menu_bar_element=self._discover_bar(root)
        return self._find(self.menu_bar_element,'file',scope='children')
    def _focused_menu(self,chain,file_index,bar_index):
        if getattr(self,'source_selection',None) is not None and getattr(self,'_uses_comparison',False):
            return self._source_focused_ancestry(chain,file_index,bar_index)
        diagnostic=None;entry=None
        try:
            diagnostic=dict(schemaVersion=1,phaseCode=1,failed=0,getFocusedReturned=0,parentReturned=0,rows=[])
            self.interop['focusedWalk']=diagnostic
        except BaseException:diagnostic=None
        def note(target,**numbers):
            try:
                if target is not None:target.update(numbers)
            except BaseException:pass
        def returned(target,row):
            try:
                if target is None:return
                kinds={'Button':50000,'MenuBar':50010,'MenuItem':50011,'ToolBar':50021,'Window':50032}
                pid=row.get('pid');kind=kinds.get(row.get('controlType'))
                if kind is None and type(row.get('controlType')) is str and re.fullmatch(r'[0-9]{1,5}',row['controlType']):kind=int(row['controlType'])
                if type(pid) is int and 0<pid<2**32:target.update(pid=pid,observedMask=target['observedMask']|1)
                if type(kind) is int and 0<kind<2**16:target.update(kindCode=kind,observedMask=target['observedMask']|2)
                for name,bit in (('visible',4),('enabled',8)):
                    if type(row.get(name)) is bool:target.update({name:int(row[name]),'observedMask':target['observedMask']|bit})
            except BaseException:pass
        try:
            result=[];cursor=self._uia_call(15,self.uia.iuia.GetFocusedElement);matched=False
            note(diagnostic,getFocusedReturned=1)
            comparison=getattr(self,'_uses_comparison',False)
            self._focus_identity=None
            allowed={tuple(chain[file_index]['runtimeId']),tuple(chain[bar_index]['runtimeId'])}
            for depth in range(32):
                if not cursor:break
                entry=None
                try:
                    if diagnostic is not None:
                        entry=dict(depth=depth,referencePhaseCode=1 if depth==0 else 2,failed=0,
                            observedMask=0,pid=0,kindCode=0,visible=0,enabled=0)
                        diagnostic['rows'].append(entry)
                except BaseException:entry=None
                note(diagnostic,phaseCode=2)
                if comparison:
                    try:row=_getter_call_site(self,9,self._chrome,cursor)
                    except BaseException as primary:
                        try:
                            previous_boundary=self.interop.get('focusedBoundary')
                            self._observe_failed_focus_cursor(cursor,depth,primary)
                            if self.interop.get('focusedBoundary') is not previous_boundary:
                                self._observe_failed_focus_new(cursor,depth,primary)
                        except BaseException:pass
                        raise
                    result.append(row);returned(entry,row)
                    note(diagnostic,phaseCode=3)
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
                    returned(entry,result[-1])
                if not comparison and tuple(runtime) in allowed:
                    # Resolve runtime IDs back to the retained live menu objects.
                    for ancestor in (self.file_element,self.menu_bar_element):
                        if self._same(cursor,ancestor):matched=True
                    break
                note(diagnostic,phaseCode=4)
                cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor)
                note(diagnostic,parentReturned=depth+1)
            note(diagnostic,phaseCode=5)
            return result,matched
        except BaseException:
            note(diagnostic,failed=1);note(entry,failed=1)
            raise
    def _source_focus_owned(self,popup):
        """Read-only original generation/foreground fence, never activation."""
        _source_bound_admission(self)
        scope,continuity=self._menu_classification_context
        binding=self._identity_scope['binding']
        assert scope['binding']==binding and scope['shellPid']==self._identity_scope['shellPid']
        continuity()
        attachment=self.attachment_snapshot(binding);assert attachment['valid'] is True
        child=self.window_snapshot(binding['child'])
        assert (child['hwnd'],child['pid'],child['rootHwnd'])==(binding['child'],binding['officePid'],binding['document'])
        assert child['visible'] is child['enabled'] is True
        assert type(child['threadId']) is int and child['threadId']>0
        assert attachment['windows']['child']['threadId']==child['threadId']
        assert type(popup) is dict and popup['pid']==binding['officePid']
        current=self.window_snapshot(popup['hwnd'])
        assert all(current[key]==popup[key] for key in ('hwnd','pid','rootHwnd','threadId','rectangle'))
        assert current['visible'] is current['enabled'] is True
        assert self._owners(popup['hwnd'],binding)==popup['ownerChain']
        foreground=self.foreground();assert foreground in (binding['document'],popup['hwnd'])
        return dict(childHwnd=child['hwnd'],childPid=child['pid'],childRootHwnd=child['rootHwnd'],
            childThreadId=child['threadId'],foreground=foreground,popupHwnd=popup['hwnd'],
            popupThreadId=popup['threadId'],popupRectangle=list(popup['rectangle']),ownerChain=list(popup['ownerChain']))
    def _source_focused_ancestry(self,chain,file_index,bar_index):
        """Observe unretained MenuItems; only original retained File/bar authorizes keys.

        No exception fallback, role synthesis, input, timeout cache or fresh budget.
        Every parent edge and the initial focus is independently reacquired.
        """
        popup=self._source_focus_popup;before=self._source_focus_owned(popup)
        cursor=self._uia_call(15,self.uia.iuia.GetFocusedElement);assert cursor
        initial=cursor;fresh=self._uia_call(15,self.uia.iuia.GetFocusedElement)
        assert fresh and self._same(cursor,fresh), 'Source focus changed before ancestry observation'
        proof=dict(schemaVersion=1,scope=copy.deepcopy(self._identity_scope),before=before,after=None,
            focusFreshEquals=True,focusEndEquals=False,rows=[],edges=[],terminalRole=None)
        result=[];seen=[];unknown=False;self._focus_identity=None
        refs=self._identity_refs
        assert {'file','bar','peer','contrast-edit'}<=set(refs)<=set(IDENTITY_ROLES)
        for depth in range(32):
            runtime,observation=self._runtime(cursor)
            assert observation['versionObserved'] is observation['declaration']['verified'] is True
            matches={role:self._same(cursor,original) for role,original in refs.items()}
            roles=[role for role,same in matches.items() if same]
            assert len(roles)<=1 and (not roles or roles[0]!='contrast-edit'), 'Source focus roles alias'
            distinct=[self._same(cursor,prior) for prior in seen]
            assert all(value is False for value in distinct), 'Source focus ancestry cycles'
            role=roles[0] if roles else None
            if role is not None:
                assert role in ('file','bar') or role.startswith('target:'), 'Source focus did not reach its retained menu'
                row=_getter_call_site(self,9,self._chrome,cursor)
                assert row['pid']==self._identity_scope['binding']['officePid'] and row['visible'] is row['enabled'] is True
                result.append(row)
            else:
                # Unretained MenuItems are read-only ancestry observations with
                # either verified empty or bounded signed-int runtime IDs. A valid
                # ID does not grant a retained role or input target identity.
                pid=self._uia_call(8,lambda:cursor.CurrentProcessId)
                assert type(pid) is int and pid==self._identity_scope['binding']['officePid']
                kind=self._uia_call(9,lambda:cursor.CurrentControlType);assert type(kind) is int and kind==50011
                offscreen=self._uia_call(11,lambda:cursor.CurrentIsOffscreen)
                enabled=self._uia_call(12,lambda:cursor.CurrentIsEnabled)
                assert all(type(value) is bool or type(value) is int and value in (0,1) for value in (offscreen,enabled))
                assert not bool(offscreen) and bool(enabled)
                hwnd=self._uia_call(7,lambda:cursor.CurrentNativeWindowHandle)
                assert hwnd is None or type(hwnd) is int and -(1<<31)<=hwnd<1<<32
                hwnd=0 if hwnd is None else hwnd&0xffffffff
                assert hwnd in (0,popup['hwnd'])
                box=self._uia_call(10,lambda:cursor.CurrentBoundingRectangle)
                rect=[getattr(box,key) for key in ('left','top','right','bottom')]
                assert all(type(number) is int and -(1<<31)<=number<1<<31 for number in rect)
                outer=popup['rectangle']
                try:
                    assert outer[0]<=rect[0]<rect[2]<=outer[2] and outer[1]<=rect[1]<rect[3]<=outer[3]
                except AssertionError:
                    try:
                        self.interop['sourceFocusBoundsFailure']=dict(sourceCode=38,guardSiteCode=1,depth=depth,
                            focus=dict(pid=pid,kindCode=kind,nativeHwnd=hwnd,rectangle=list(rect)),
                            popup=dict(pid=popup['pid'],hwnd=popup['hwnd'],rectangle=list(outer)),
                            entryFence=copy.deepcopy(before),
                            scope=dict(binding={key:self._identity_scope['binding'][key]
                                for key in ('document','parent','child','officePid')},
                                shellPid=self._identity_scope['shellPid'],
                                shellCreationTime=self._identity_scope['shellCreationTime'],
                                officeCreationTime=self._identity_scope['officeCreationTime']))
                    except BaseException:pass
                    raise
                row=dict(runtimeId=list(runtime),runtimeObservation=observation,pid=pid,kindCode=kind,nativeHwnd=hwnd,
                    visible=True,enabled=True,rectangle=rect)
                unknown=True
            proof['rows'].append(dict(observation=copy.deepcopy(row),retainedRole=role,differentFrom=matches,
                differentFromPrior=distinct))
            if role in ('file','bar'):
                assert self._same(cursor,self.file_element if role=='file' else self.menu_bar_element)
                self._focus_identity=dict(scope=copy.deepcopy(self._identity_scope),role=role,
                    fileEquals=role=='file',barEquals=role=='bar',retainedEquals=True)
                proof['terminalRole']=role
                fresh=self._uia_call(15,self.uia.iuia.GetFocusedElement)
                assert fresh and self._same(initial,fresh), 'Source focus changed during ancestry observation'
                proof['focusEndEquals']=True;proof['after']=self._source_focus_owned(popup)
                assert proof['after']==proof['before']
                self._source_focus_proof=proof
                self._source_focus_branch=2 if unknown else 1
                return result,True
            assert depth<31, 'Source focus ancestry exceeded bound'
            parent=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert parent
            repeated=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor)
            assert repeated and self._same(parent,repeated), 'Source focus parent changed'
            negatives=[self._same(parent,prior) for prior in (*seen,cursor)]
            assert all(value is False for value in negatives), 'Source focus parent cycles'
            proof['edges'].append(dict(parentFreshEquals=True,differentFromEarlier=negatives))
            seen.append(cursor);cursor=parent
        raise AssertionError('Source focus did not reach its retained menu')
    def _observe_failed_focus_cursor(self,cursor,depth,primary):
        """Separate numeric facts after the unchanged retained-role rejection.

        No identity retry, fresh element, role admission, window lookup or input.
        Existing per-call provider timeouts/checks use the same action deadline;
        they are not a claim that a synchronous COM call can be preempted.
        """
        value=None;saved=None;missing=object()
        try:
            if (type(primary) is not AssertionError or len(primary.args)!=1 or type(primary.args[0]) is not str
                or primary.args[0]!='Native menu identity is unknown or ambiguous'
                or getattr(self,'_native_identity_diagnostic',0)!=0 or type(depth) is not int or not 0<=depth<32):return
            runtime=self.interop.get('lastRuntimeObservation');rows=self.interop.get('lastRoleComparisons')
            refs=getattr(self,'_identity_refs',None)
            if (type(runtime) is not dict or runtime.get('callSucceeded') is not True or runtime.get('empty') is not True
                or runtime.get('length')!=0 or runtime.get('signed32Valid') is not True
                or runtime.get('versionObserved') is not True or type(runtime.get('declaration')) is not dict
                or runtime['declaration'].get('verified') is not True or type(refs) is not dict
                or not 4<=len(refs)<=len(IDENTITY_ROLES) or type(rows) is not list or len(rows)!=len(refs)
                or any(type(row) is not dict or row.get('areSame') is not False
                    or type(row.get('roleCode')) is not int or not 1<=row['roleCode']<=len(IDENTITY_ROLES) for row in rows)):return
            value=dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,phaseCode=1,statusCode=0,
                depth=depth,failed=0,complete=0,observedMask=0,ownerMatchesOriginalEngine=None,
                kindCode=None,visible=None,enabled=None,remainingMicrosAtEntry=None)
            self.interop['focusedBoundary']=value
            scope=getattr(self,'_identity_scope',None)
            expected=scope.get('binding',{}).get('officePid') if type(scope) is dict else None
            upper=scope.get('deadline') if type(scope) is dict else None
            deadline=self.deadline
            if (type(expected) is not int or not 0<expected<2**32 or type(deadline) not in (int,float)
                or type(upper) not in (int,float) or not math.isfinite(deadline) or not math.isfinite(upper)
                or deadline>upper or getattr(self,'_provider_closed',False)
                or getattr(self,'_uia',None) is None or getattr(self,'provider_client',None) is None
                or self._uia.iuia is not self.provider_client):value['statusCode']=4;return
            def budget():
                if self.deadline!=deadline:value['statusCode']=2;return False
                now=self.clock()
                remaining=deadline-now if type(now) in (int,float) and math.isfinite(now) else 0
                if not 0<remaining<=5 or not 1<=int((remaining*1000-1)//4)<=1250:
                    value['statusCode']=2;return False
                if value['remainingMicrosAtEntry'] is None:value['remainingMicrosAtEntry']=int(remaining*1000000)
                if self._provider_pending():value['statusCode']=3;return False
                return True
            if not budget():return
            # _call already isolates lastCall and exception recording when this
            # separate sink is present. Restore exact original context/flags.
            saved=[(name,getattr(self,name,missing)) for name in
                ('_diagnostic_sink','_observed_call','_last_call_exception','provider_timeout_verified')]
            self._diagnostic_sink=value;self._observed_call=None
            value['phaseCode']=2
            pid=self._uia_call(8,lambda:cursor.CurrentProcessId)
            if type(pid) is not int or not 0<pid<2**32:value.update(statusCode=6,failed=1);return
            value.update(ownerMatchesOriginalEngine=pid==expected,observedMask=1)
            if pid!=expected:value['statusCode']=5;return
            if not budget():return
            value['phaseCode']=3
            kind=self._uia_call(9,lambda:cursor.CurrentControlType)
            if type(kind) is not int or not 50000<=kind<=50040:value.update(statusCode=6,failed=1);return
            value.update(kindCode=kind,observedMask=3)
            for phase,name,key,bit in ((4,'CurrentIsOffscreen','visible',4),(5,'CurrentIsEnabled','enabled',8)):
                if not budget():return
                value['phaseCode']=phase
                raw=self._uia_call(11 if phase==4 else 12,lambda:getattr(cursor,name))
                if type(raw) is not bool and not (type(raw) is int and raw in (0,1)):
                    value.update(statusCode=6,failed=1);return
                value[key]=int(not raw) if key=='visible' else int(raw)
                value['observedMask']|=bit
            if budget():value.update(phaseCode=6,statusCode=1,complete=1)
        except BaseException:
            if value is not None:value.update(statusCode=7,failed=1)
        finally:
            if saved is not None:
                for name,old in saved:
                    try:
                        if old is missing:self.__dict__.pop(name,None)
                        else:setattr(self,name,old)
                    except BaseException:pass
    def _observe_failed_focus_new(self,cursor,depth,primary):
        """Observe fixed New comparisons; never admit focus or replace failure."""
        value=None;saved=None;missing=object()
        class Halt(Exception):pass
        try:
            boundary=self.interop.get('focusedBoundary')
            if (type(primary) is not AssertionError or primary.args!=('Native menu identity is unknown or ambiguous',)
                or getattr(self,'_native_identity_diagnostic',0)!=0 or type(depth) is not int or depth!=0
                or type(boundary) is not dict or boundary.get('depth')!=depth
                or boundary.get('complete')!=1 or boundary.get('ownerMatchesOriginalEngine') is not True
                or boundary.get('kindCode')!=50011 or boundary.get('visible')!=1 or boundary.get('enabled')!=1):return
            value=dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,conclusionCode=0,
                statusCode=0,phaseCode=1,failed=0,complete=0,remainingMicrosAtEntry=None,
                continuityBefore=0,continuityAfter=0,windowBindingUnchanged=None,
                firstFind={},freshFind={},focusEqualsCandidate=None,freshEqualsCandidate=None,
                negativeComparisons=[],directParentEqualsFile=None)
            self.interop['focusedNewComparison']=value
            scope=getattr(self,'_identity_scope',None);context=getattr(self,'_menu_classification_context',None)
            refs=getattr(self,'_identity_refs',None);base=('file','bar','peer','contrast-edit','target:save')
            keys=('version','binding','shellPid','shellCreationTime','officeCreationTime','startedAt','deadline')
            if (type(scope) is not dict or scope.get('operation')!='keyboard-escape' or scope.get('gesture') is not True
                or type(context) is not tuple or len(context)!=2 or type(context[0]) is not dict
                or set(context[0])!=set(keys) or not callable(context[1])
                or any(context[0][key]!=scope.get(key) for key in keys)
                or type(refs) is not dict or set(refs)!=set(base)
                or getattr(self,'_provider_closed',False) or getattr(self,'_uia',None) is None
                or getattr(self,'provider_client',None) is None or self._uia.iuia is not self.provider_client):
                value['statusCode']=4;return
            deadline=self.deadline;binding=scope['binding'];continuity=context[1]
            if (type(binding) is not dict or set(binding)!={'document','parent','child','officePid'}
                or any(type(n) is not int or n<=0 for n in binding.values())
                or any(type(scope.get(k)) is not int or scope[k]<=0 for k in
                    ('version','shellPid','shellCreationTime','officeCreationTime'))
                or scope['version']!=1 or scope['officeCreationTime']<scope['shellCreationTime']
                or scope['shellPid']==binding['officePid']
                or any(type(scope.get(k)) not in (int,float) or not math.isfinite(scope[k]) for k in ('startedAt','deadline'))
                or not scope['startedAt']<scope['deadline']<=scope['startedAt']+5 or deadline!=scope['deadline']):
                value['statusCode']=4;return
            original_scope=dict(scope,binding=dict(binding));original_refs=dict(refs)
            original_menu_scope=dict(context[0],binding=dict(binding))
            def stop(code):
                value['statusCode']=code;raise Halt()
            def budget():
                if self.deadline!=deadline:stop(2)
                now=self.clock()
                if type(now) not in (int,float) or not math.isfinite(now):stop(2)
                remaining=deadline-now
                if not 0<remaining<=5 or not 1<=int((remaining*1000-1)//4)<=1250:stop(2)
                if value['remainingMicrosAtEntry'] is None:value['remainingMicrosAtEntry']=int(remaining*1000000)
                if self._provider_pending():stop(3)
            def checked(function,*args):
                budget();result=function(*args);budget();return result
            def read(code,function,*args):return checked(self._uia_call,code,function,*args)
            def same(left,right):return checked(self._same,left,right)
            def windows():
                attachment=checked(self.attachment_snapshot,binding)
                if (type(attachment) is not dict or attachment.get('binding')!=binding or attachment.get('valid') is not True
                    or attachment.get('exported')!=[binding['parent'],binding['child']]):stop(4)
                rows=attachment.get('windows')
                if type(rows) is not dict or set(rows)!={'document','parent','child'}:stop(4)
                result=[]
                for role in ('document','parent','child'):
                    row=rows[role];pid=binding['officePid'] if role=='child' else scope['shellPid']
                    if (type(row) is not dict or set(row)!={'hwnd','pid','threadId','rootHwnd'}
                        or any(type(n) is not int or n<=0 for n in row.values())
                        or (row['hwnd'],row['pid'],row['rootHwnd'])!=(binding[role],pid,binding['document'])):stop(4)
                    result.append(tuple(row[k] for k in ('hwnd','pid','threadId','rootHwnd')))
                return result
            def find(packet):
                packet.update(candidateCount=0,examinedCount=0,visibleCount=0,matchedCount=0,scanComplete=0)
                client=self._uia.iuia
                condition=read(13,client.CreatePropertyCondition,30003,50011)
                found=read(2,refs['file'].FindAll,self._uia.tree_scope['descendants'],condition)
                count=read(17,lambda:found.Length)
                if type(count) is not int or not 0<=count<=512:stop(6)
                packet['candidateCount']=count;matches=[]
                for index in range(count):
                    element=read(18,found.GetElement,index);packet['examinedCount']=index+1
                    pid=read(8,lambda:element.CurrentProcessId)
                    if type(pid) is not int or pid!=binding['officePid']:stop(5)
                    kind=read(9,lambda:element.CurrentControlType)
                    if type(kind) is not int or kind!=50011:stop(6)
                    offscreen=read(11,lambda:element.CurrentIsOffscreen)
                    if type(offscreen) is not bool and not (type(offscreen) is int and offscreen in (0,1)):stop(6)
                    if offscreen:continue
                    packet['visibleCount']+=1
                    name=read(16,lambda:element.CurrentName)
                    if type(name) is not str or len(name)>256:stop(6)
                    if _label(name) in LABELS['new']:matches.append(element)
                    packet['matchedCount']=len(matches)
                packet['scanComplete']=1
                if len(matches)!=1:stop(6)
                enabled=read(12,lambda:matches[0].CurrentIsEnabled)
                if enabled is not True and not (type(enabled) is int and enabled==1):stop(6)
                return matches[0]
            budget()
            saved=[(name,getattr(self,name,missing)) for name in
                ('_diagnostic_sink','_observed_call','_last_call_exception','provider_timeout_verified')]
            self._diagnostic_sink=value;self._observed_call=None
            value['phaseCode']=2;checked(continuity);before=windows();value['continuityBefore']=1
            value['phaseCode']=3;candidate=find(value['firstFind'])
            value['phaseCode']=4;value['focusEqualsCandidate']=same(cursor,candidate)
            if not value['focusEqualsCandidate']:stop(6)
            value['phaseCode']=5;fresh=find(value['freshFind'])
            value['freshEqualsCandidate']=same(fresh,candidate)
            if not value['freshEqualsCandidate']:stop(6)
            for index,role in enumerate(base,1):
                equal=same(fresh,refs[role]);value['negativeComparisons'].append(dict(roleCode=index,areSame=equal))
                if equal:stop(6)
            value['phaseCode']=6;walker=read(0,lambda:self._uia.iuia.ControlViewWalker)
            parent=read(6,walker.GetParentElement,fresh)
            value['directParentEqualsFile']=same(parent,refs['file']) if parent else False
            if not value['directParentEqualsFile']:stop(6)
            value['phaseCode']=7;checked(continuity)
            value['windowBindingUnchanged']=windows()==before
            if not value['windowBindingUnchanged']:stop(4)
            current_context=self._menu_classification_context
            if (self._identity_scope!=original_scope or type(current_context) is not tuple or len(current_context)!=2
                or current_context[0]!=original_menu_scope or current_context[1] is not continuity
                or set(self._identity_refs)!=set(original_refs)
                or any(self._identity_refs[k] is not v for k,v in original_refs.items())):stop(4)
            budget();value.update(phaseCode=8,statusCode=1,continuityAfter=1,complete=1)
        except Halt:pass
        except BaseException:
            if value is not None:
                try:value.update(statusCode=7,failed=1,complete=0)
                except BaseException:pass
        finally:
            if saved is not None:
                for name,old in saved:
                    try:
                        if old is missing:self.__dict__.pop(name,None)
                        else:setattr(self,name,old)
                    except BaseException:pass

    def _owners(self,hwnd,binding):
        rows=[]
        while hwnd:
            assert hwnd not in rows and len(rows)<16;rows.append(hwnd)
            if hwnd in (binding['child'],binding['document']):break
            row=self.window_snapshot(hwnd);assert row['pid']==binding['officePid']
            hwnd=int(self._call(self.user.GetWindow,hwnd,4) or 0)
        return rows
    def _shell_menu_observation(self,count,samples,binding,shell_pid):
        # These are already-rejected visible shell bars, never admission hints.
        result=dict(schemaVersion=1,observedCount=count,statusCode=1,
            sampleLimit=2,ancestorLimit=32,truncated=count>len(samples),samples=[])
        def anchor(hwnd):
            return 0 if not hwnd else 1 if hwnd==binding['document'] else 2 if hwnd==binding['parent'] else 3 if hwnd==binding['child'] else 4
        for index,bar,owner in samples:
            sample=dict(index=index,stageCode=1,errorCode=0,comparisonCode=0,ancestors=[])
            result['samples'].append(sample)
            try:
                same=self._same(bar,self.menu_bar_element)
                sample.update(sameAsEngineBar=same,comparisonCode=1 if same else 2)
                cursor=bar
                for depth in range(32):
                    sample['stageCode']=2
                    pid=owner if depth==0 else self._call(lambda:cursor.CurrentProcessId)
                    kind=self._call(lambda:cursor.CurrentControlType)
                    raw=self._call(lambda:cursor.CurrentNativeWindowHandle)
                    assert type(pid) is int and 0<pid<2**32
                    assert type(kind) is int and 0<=kind<2**16
                    assert raw is None or type(raw) is int and -(2**31)<=raw<2**32
                    hwnd=0 if raw is None else raw&0xffffffff
                    sample['stageCode']=3
                    raw_root=self._call(self.user.GetAncestor,hwnd,2) if hwnd else None
                    assert raw_root is None or type(raw_root) is int and 0<=raw_root<2**64
                    root=raw_root or 0
                    sample['ancestors'].append(dict(controlType=kind,ownerPid=pid,
                        ownerRoleCode=1 if pid==shell_pid else 2 if pid==binding['officePid'] else 3,
                        nativeHwnd=hwnd,hwndAnchorCode=anchor(hwnd),rootHwnd=root,rootAnchorCode=anchor(root)))
                    if hwnd==binding['document']:
                        sample['stageCode']=5;break
                    sample['stageCode']=4
                    cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor)
                    if not cursor:
                        sample['stageCode']=5;break
                else:sample.update(stageCode=6,errorCode=5)
            except BaseException:
                # Fixed codes only; the original count failure remains primary.
                sample['errorCode']=sample['stageCode']
            if sample['errorCode']:
                result['statusCode']=2;break
        return result
    def bind_menu_classification(self,scope,continuity):
        assert scope['deadline']==self.deadline and callable(continuity)
        self._menu_classification_context=(copy.deepcopy(scope),continuity)
    def _classify_shell_menus(self,count,samples,binding,shell,engine_bar):
        result=dict(scope={},totalCount=count,verifiedSystemCount=0,clientCount=0,
            unknownCount=count,errorCode=1,proofs=[])
        try:
            scope,continuity=self._menu_classification_context
            assert scope['binding']==binding and scope['shellPid']==self._call(lambda:shell.CurrentProcessId)
            result['scope']=copy.deepcopy(scope)
            assert count==1 and len(samples)==1
            result['errorCode']=2
            assert engine_bar is not None
            assert self._call(lambda:engine_bar.CurrentProcessId)==binding['officePid']
            assert self._call(lambda:engine_bar.CurrentControlType)==50010
            def ownership():
                continuity();window=self.window_snapshot(binding['document']);attachment=self.attachment_snapshot(binding)
                assert (window['hwnd'],window['pid'],window['rootHwnd'])==(binding['document'],scope['shellPid'],binding['document'])
                assert window['visible'] is window['enabled'] is True and attachment['valid'] is True
                assert scope['shellPid']!=os.getpid()
            def metadata():
                info=MenuBarInfo(cbSize=C.sizeof(MenuBarInfo));assert C.sizeof(MenuBarInfo)==48
                returned=self._call(self.user.GetMenuBarInfo,binding['document'],-1,0,C.byref(info))
                assert type(returned) is int and returned!=0
                title=self.caption(binding['document'])
                return dict(menuRect=[int(getattr(info.rcBar,k)) for k in ('left','top','right','bottom')],
                    captionRect=title['rectangle'],captionState=title['state'],menuHandle=int(info.hMenu or 0),
                    submenuHwnd=int(info.hwndMenu or 0),menuFlags=int(info.flags))
            ownership();result['errorCode']=3
            context=self._call(self.user.GetThreadDpiAwarenessContext)
            dpi=self._call(self.user.AreDpiAwarenessContextsEqual,context,-4)
            assert type(dpi) in (int,bool) and bool(dpi)
            before=metadata();rect=before['menuRect'];assert rect[0]<rect[2] and rect[1]<rect[3]
            assert before['menuHandle']>0 and not before['captionState']&0x18001
            point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
            assert all(-(2**15)<=n<2**15 for n in point)
            result['errorCode']=4
            assert (self.deadline-self.clock())*1000>=1
            hit=NativeActivationProbe.point_snapshot(self,binding['document'],point)
            assert (hit['hitHwnd'],hit['rootHwnd'],hit['pid'],hit['hitTest'])==(binding['document'],binding['document'],scope['shellPid'],3)
            result['errorCode']=5
            counted=samples[0][1]
            def point_bar():
                cursor=self._call(self.uia.iuia.ElementFromPoint,self._point_type(*point));chain=[];bar=None;bar_index=None
                for _ in range(32):
                    kind=self._call(lambda:cursor.CurrentControlType);pid=self._call(lambda:cursor.CurrentProcessId)
                    raw=self._call(lambda:cursor.CurrentNativeWindowHandle)
                    assert type(kind) is type(pid) is int and pid==scope['shellPid']
                    assert raw is None or type(raw) is int and -(2**31)<=raw<2**32
                    hwnd=0 if raw is None else raw&0xffffffff
                    assert hwnd in (0,binding['document']) and kind in (50000,50011,50010,50037,50032)
                    chain.append([kind,pid,hwnd])
                    if kind==50010:assert bar is None;bar=cursor;bar_index=len(chain)-1
                    if self._same(cursor,shell):
                        assert kind==50032 and hwnd==binding['document'] and bar is not None
                        assert [row[0] for row in chain[bar_index:]]==[50010,50037,50032]
                        return bar,chain,bar_index
                    cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
                raise AssertionError('Owned system point ancestry limit')
            bar,chain,bar_index=point_bar()
            assert self._same(bar,counted) and not self._same(bar,engine_bar) and not self._same(bar,shell)
            fresh,_,_=point_bar();assert self._same(fresh,bar)
            result['errorCode']=6
            after=metadata();assert before==after
            assert self._same(self._root(binding['document']),shell)
            ownership()
            proof=dict(before=before,after=after,point=point,physicalHit=hit,harnessPid=os.getpid(),
                pointBarEqualsCounted=True,freshPointBarEqualsRetained=True,engineBarDifferent=True,shellRootDifferent=True,
                rootStable=True,ownershipBefore=True,ownershipAfter=True,physicalDpiVerified=True,ancestry=chain,barIndex=bar_index)
            result.update(verifiedSystemCount=1,unknownCount=0,errorCode=0,proofs=[proof])
            _require_shell_menus(dict(shellMenuCount=count,shellMenuClassification=result),binding,scope['shellPid'],scope)
        except BaseException:
            if result['errorCode']==0:result['errorCode']=7
            result.update(verifiedSystemCount=0,unknownCount=count,proofs=[])
        return result
    def snapshot(self,binding,target):
        if (getattr(self,'_native_identity_diagnostic',0)==3 and target!='file'
                and getattr(self,'_identity_diagnostic_point_seen',False)):
            raise NativeIdentityDiagnosticTerminal('The diagnostic source cannot be rediscovered')
        doc=binding['document'];child=binding['child'];pid=binding['officePid']
        self._active_target=target
        physical=(getattr(self,'_physical_file_refresh',False) and hasattr(self,'file_element') and
            'contrast-edit' in self._identity_refs)
        fresh=self._physical_base() if physical else None
        root=fresh['peer'] if fresh else self._root(child)
        if not hasattr(self,'file_element'):self.file_element=self.discover_file(root)
        if getattr(self,'_identity_scope',None) is not None:
            for role,element in (('file',self.file_element),('bar',self.menu_bar_element),('peer',root)):
                self._bind_ref(role,element)
        query_file=fresh['file'] if fresh else self.file_element
        element=query_file if target=='file' else self._find(query_file,target)
        if getattr(self,'_identity_scope',None) is not None:self._bind_ref(_target_role(target),element)
        self.current_control=type('NativeMenuControl',(),{'element_info':type('Info',(),{'_element':element})()})()
        chain=[];cursor=element;file_index=bar_index=None;file_equal=peer_equal=False
        for _ in range(32):
            row=_getter_call_site(self,10 if not chain else 11,self._chrome,cursor);chain.append(row);index=len(chain)-1
            if self._same(cursor,self.file_element):file_index=index;file_equal=True
            if row['controlType']=='MenuBar' and file_index is not None and bar_index is None:
                if getattr(self,'_uses_comparison',False):assert self._same(cursor,self.menu_bar_element), 'Native menubar differs from the retained original'
                bar_index=index
            if self._same(cursor,root):peer_equal=True;break
            cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
        else:raise AssertionError('Native menu ancestry exceeded bound')
        control=_getter_call_site(self,12,self._chrome,element);rect=control['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
        proof=self._fresh_proof(target) if getattr(self,'_uses_comparison',False) else None
        popup=None;target_point=None
        if target!='file':
            hit=self.point_snapshot(doc,point,self.current_control);popup=self.window_snapshot(hit['rootHwnd'])
            popup['ownerChain']=self._owners(popup['hwnd'],binding)
            if hit.get('pointMethod') in ('owned-popup-and-msaa-hit','owned-popup-and-msaa-canonical-hit-v2','owned-popup-and-source-qualified-ia2-hit-v4'):target_point=hit
        attachment=self.attachment_snapshot(binding);document=self.window_snapshot(doc)
        thread=attachment['windows']['child']['threadId'];gui=self.native_focus(thread)
        permitted={0,child}
        if popup:permitted.add(popup['hwnd'])
        gui.update(captureOwned=gui['captureHwnd'] in permitted,menuOwnerOwned=gui['menuOwnerHwnd'] in permitted)
        if getattr(self,'source_selection',None) is not None:self._source_focus_popup=popup
        focused,matched=(self._focused_menu(chain,file_index,bar_index) if target!='file' and not _menu_key_owner(gui,popup,child) and file_index is not None and bar_index is not None else ([],False))
        fg=self.window_snapshot(self.foreground())
        shell=self._root(doc)
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuBar'))
        bars=self._call(shell.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._call(lambda:bars.Length));assert 0<=count<=64
        duplicates=0;shell_samples=[]
        for index in range(count):
            bar=self._call(bars.GetElement,index)
            owner=self._call(lambda:bar.CurrentProcessId)
            visible=not self._call(lambda:bar.CurrentIsOffscreen)
            duplicates+=int(owner==document['pid'] and visible)
            if owner==document['pid'] and visible and len(shell_samples)<2:shell_samples.append((index,bar,owner))
        result=dict(binding=dict(binding),attachmentValid=attachment['valid'],nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
            shellMenuCount=duplicates,document=document,control=control,ancestry=chain,fileIndex=file_index,
            barIndex=bar_index,peerIndex=len(chain)-1,fileElementEquals=file_equal,peerElementEquals=peer_equal,
            popup=popup,foreground=fg,gui=gui,focusMenuPath=focused,focusMenuElementEquals=matched)
        if proof is not None:
            result.update(identityProof=proof,barElementEquals=True,focusIdentity=getattr(self,'_focus_identity',None))
        if target_point is not None:result['targetPointProof']=target_point
        if duplicates:
            result['shellMenuObservation']=self._shell_menu_observation(duplicates,shell_samples,binding,document['pid'])
            result['shellMenuClassification']=self._classify_shell_menus(duplicates,shell_samples,binding,shell,self.menu_bar_element)
            if result['shellMenuClassification']['verifiedSystemCount']:
                attachment=self.attachment_snapshot(binding);gui=self.native_focus(attachment['windows']['child']['threadId'])
                gui.update(captureOwned=gui['captureHwnd'] in permitted,menuOwnerOwned=gui['menuOwnerHwnd'] in permitted)
                focused,matched=(self._focused_menu(chain,file_index,bar_index) if target!='file' and not _menu_key_owner(gui,popup,child) and file_index is not None and bar_index is not None else ([],False))
                result.update(attachmentValid=attachment['valid'],document=self.window_snapshot(doc),
                    nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
                    foreground=self.window_snapshot(self.foreground()),gui=gui,focusMenuPath=focused,focusMenuElementEquals=matched)
                if proof is not None:result['focusIdentity']=getattr(self,'_focus_identity',None) if matched else None
        return result
    def view_snapshot(self,binding,module):
        assert module in ('writer','calc')
        root=self._root(binding['child']);doc=binding['document']
        peer_identity=_getter_call_site(self,13,self._chrome,root)
        assert (peer_identity['pid'],peer_identity['nativeHwnd'])==(binding['officePid'],binding['child']), 'Native view UIA root is outside the original peer'
        editor=self.editor_snapshot(binding)
        condition=self._call(lambda:self.uia.build_condition(control_type='MenuBar'))
        native_anchors=[]
        def menu_count(parent,pid):
            found=self._call(parent.FindAll,self.uia.tree_scope['descendants'],condition)
            count=int(self._call(lambda:found.Length));assert 0<=count<=8
            visible=0
            for index in range(count):
                element=self._call(found.GetElement,index)
                assert int(self._call(lambda:element.CurrentProcessId))==pid
                native_anchors.append(element)
                visible+=int(not self._call(lambda:element.CurrentIsOffscreen))
            assert visible<=1
            return visible
        native_bars=menu_count(root,binding['officePid'])
        shell=self._root(doc);document_identity=_getter_call_site(self,14,self._chrome,shell)
        assert (document_identity['pid'],document_identity['nativeHwnd'])==(self.window_snapshot(doc)['pid'],doc), 'Native view UIA host root changed'
        found=self._call(shell.FindAll,self.uia.tree_scope['descendants'],condition)
        count=int(self._call(lambda:found.Length));assert 0<=count<=64
        shell_bars=0;shell_samples=[];shell_pid=self.window_snapshot(doc)['pid']
        for index in range(count):
            bar=self._call(found.GetElement,index)
            owner=self._call(lambda:bar.CurrentProcessId)
            if owner==shell_pid:
                visible=not self._call(lambda:bar.CurrentIsOffscreen)
                shell_bars+=int(visible)
                if visible and len(shell_samples)<2:shell_samples.append((index,bar,owner))
        indicators=[];held=[]
        for label in ('미리보기 닫기','Close Preview'):
            condition=self._call(lambda:self.uia.build_condition(control_type='Button',name=label))
            found=self._call(root.FindAll,self.uia.tree_scope['descendants'],condition)
            count=int(self._call(lambda:found.Length));assert 0<=count<=2
            for index in range(count):
                element=self._call(found.GetElement,index)
                row=_getter_call_site(self,15,self._chrome,element)
                if not row['visible']:continue
                assert self._call(lambda:element.CurrentName)==label
                chain=[];cursor=element;same=False
                for _ in range(32):
                    held.append(cursor);part=_getter_call_site(self,16,self._chrome,cursor);chain.append(part)
                    assert part['pid']==binding['officePid']
                    if self._call(self.uia.iuia.CompareElements,cursor,root):same=True;break
                    cursor=self._call(self.uia.iuia.ControlViewWalker.GetParentElement,cursor);assert cursor
                assert same and chain[-1]['nativeHwnd']==binding['child']
                assert chain[0]['controlType']=='Button' and any(part['controlType']=='ToolBar' for part in chain[1:-1])
                indicators.append(dict(row,ancestryVerified=True,peerElementEquals=True,
                    toolbarAncestorVerified=True,ancestry=chain))
        assert len(indicators)<=1, 'Native preview indicator is ambiguous'
        self._retained=tuple(held)
        result=dict(binding=dict(binding),editor=editor,peerRoot=peer_identity,documentRoot=document_identity,
            nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
            statusSequenceRaw=self._call(self.user.GetPropW,doc,STATUS_PROPERTY),
            shellMenuCount=shell_bars,nativeMenuBarCount=native_bars,
            previewIndicatorCount=len(indicators),previewIndicator=indicators[0] if indicators else None)
        if shell_bars:
            result['shellMenuClassification']=self._classify_shell_menus(shell_bars,shell_samples,binding,shell,native_anchors[0] if len(native_anchors)==1 else None)
            if result['shellMenuClassification']['verifiedSystemCount']:
                result.update(editor=self.editor_snapshot(binding),
                    nativeReady=int(self._call(self.user.GetPropW,doc,READY_PROPERTY) or 0),
                    statusSequenceRaw=self._call(self.user.GetPropW,doc,STATUS_PROPERTY))
        return result
    def editor_snapshot(self,binding):
        attachment=self.attachment_snapshot(binding,include_gui=True);thread=attachment['windows']['child']['threadId'];gui=self.native_focus(thread)
        return dict(binding=dict(binding),attachmentValid=attachment['valid'],focusPid=gui['focusPid'],
            document=self.window_snapshot(binding['document']),nativeReady=int(self._call(self.user.GetPropW,binding['document'],READY_PROPERTY) or 0),
            foreground=self.window_snapshot(self.foreground()),
            focusRootHwnd=gui['focusRootHwnd'],focusUnderOriginalChild=attachment['focusUnderOriginalChild'],
            captureHwnd=gui['captureHwnd'],menuOwnerHwnd=gui['menuOwnerHwnd'],menuClosed=not gui['captureHwnd'] and not gui['menuOwnerHwnd'],
            hostGui=attachment['hostGui'],engineGui=gui,attachmentWindows=attachment['windows'],attachmentExports=attachment['exported'])
    def _source_input_deadline(self):
        points=getattr(self,'_source_input_points',[])
        admission=_source_bound_admission(self,require_scope=bool(points))
        from native_menu_msaa_hit import pending_msaa_hit
        assert pending_msaa_hit() is None, 'A provider callback remains unretired before input'
        expiry=self.deadline
        for hit in points:
            proof=hit['providerLocalProof'];scope=proof['scope']
            assert scope==self._identity_scope
            _require_provider_point_v4(proof,scope['binding'],scope['shellPid'],self._active_target,
                admission_sha256=admission.admission_sha256,now=self.clock())
            expiry=min(expiry,proof['effectiveDeadline'])
        return expiry

    def click(self,receipt):
        if getattr(self,'source_selection',None) is None:return super().click(receipt)
        original=self.deadline;points=getattr(self,'_source_input_points',[])
        assert not points or receipt is self._source_input_receipt
        self.deadline=self._source_input_deadline()
        try:return super().click(receipt)
        finally:
            self.deadline=original
            if points and receipt.get('inputCallAttempts')==1:
                for hit in points:_source_point_use(self,hit,3,receipt['inputStartedAt'])

    def _source_send(self,payload):
        if getattr(self,'source_selection',None) is None:return super().send(payload)
        original=self.deadline;points=getattr(self,'_source_input_points',[])
        self.deadline=self._source_input_deadline()
        keyboard=None;keyboard_deadline=None
        try:
            keyboard=self._keyboard();keyboard_deadline=keyboard.deadline
            keyboard.deadline=min(keyboard_deadline,self.deadline)
            receipt=getattr(self,'_source_input_receipt',None)
            at=self.clock();assert at<keyboard.deadline
            if receipt is not None:receipt.update(inputStartedAt=at,inputCallAttempts=1)
            result=super().send(payload)
            if points:
                for hit in points:_source_point_use(self,hit,4,at)
            return result
        finally:
            self.deadline=original
            if keyboard is not None:keyboard.deadline=keyboard_deadline

    def keyboard(self,binding,shortcut,receipt):
        from ascii_editor_input import input_buffer
        events=_menu_key_events(shortcut)
        thread=self.attachment_snapshot(binding)['windows']['child']['threadId'];state=self.keyboard_snapshot(thread)
        assert state['targetLayout']==state['currentThreadLayout']==0x04090409 and not state['keysDown']
        held=[key for key in (1,2,4,5,6,0x46,0x28) if self._call(self.user.GetAsyncKeyState,key)&0x8000]
        assert not held, 'A native menu navigation key is already pressed'
        receipt['keyboardBefore']=dict(state,additionalMenuKeysDown=held)
        receipt.update(requestedInputs=len(events),inputCallAttempts=0 if getattr(self,'source_selection',None) is not None else 1,insertedInputs=None)
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

    def _begin_source_qualified_ia2_point_v4(self,fresh_refs,negative,scope_id,point,*,admission,captured_at,action_deadline,exposure):
        """New typed source and entry; no existing packet or diagnostic is input."""
        from native_menu_msaa_hit import (SourceQualifiedIa2SdkAbi,MsaaHitScope,MsaaHitSourceV4,
            begin_source_qualified_ia2_point,_admission_words_v4)
        assert getattr(self,'_native_identity_diagnostic',0)==0
        assert type(fresh_refs) is dict and set(fresh_refs)==set(self._identity_refs)
        digest=admission.admission_sha256;_admission_words_v4(admission,digest)
        from comtypes import GUID,HRESULT
        from comtypes.automation import VARIANT
        library=self._uia_library;legacy=library.IUIAutomationLegacyIAccessiblePattern
        method=next(item for item in vars(legacy)['_methods_'] if item.name=='GetIAccessible')
        accessible=method.argtypes[0]._type_.__com_interface__
        sdk=SourceQualifiedIa2SdkAbi(client_interface=library.IUIAutomation,element_interface=library.IUIAutomationElement,
            legacy_interface=legacy,accessible_interface=accessible,guid_type=GUID,hresult_type=HRESULT,
            variant_type=VARIANT,function_factory=C.WINFUNCTYPE)
        scope=self._identity_scope;binding=scope['binding'];role=_target_role(self._active_target)
        source=MsaaHitSourceV4(self.provider_client,self._identity_refs['file'],fresh_refs['file'],
            fresh_refs[role],self._identity_refs[role],tuple(negative),self._point_source['shellHandle'],
            self._point_source['engineHandle'],(self,fresh_refs,admission),captured_at,action_deadline,
            binding['document'],exposure['hwnd'],exposure['threadId'],tuple(exposure['ownerChain']),admission,digest)
        request=MsaaHitScope(scope_id,binding['officePid'],scope['officeCreationTime'],scope['shellPid'],
            scope['shellCreationTime'],binding['parent'],binding['child'],*point)
        return begin_source_qualified_ia2_point(source,request,sdk,action_deadline,native_enabled=True)

    def _provider_local_point_v4(self,point,target,actual,*,admission):
        """One new source-qualified measurement; Task3 owns explicit selection."""
        from dataclasses import asdict
        from native_menu_msaa_hit import _admission_words_v4
        action_deadline=self.deadline
        try:
            assert not self._provider_pending(), 'A previous callback remains unretired'
            assert getattr(self,'_native_identity_diagnostic',0)==0 and self._active_target!='file'
            digest=admission.admission_sha256;_admission_words_v4(admission,digest)
            creator=self._require_provider_creator();scope=self._identity_scope;binding=scope['binding']
            _scope_anchor(scope,binding,scope['shellPid'])
            assert scope['deadline']==action_deadline and self.clock()<action_deadline
            role=_target_role(self._active_target);assert role in self._identity_refs
            comparison=dict(rawMatchesTarget=self._same(target,actual),
                targetEqualsRetained=self._same(target,self._identity_refs[role]),
                hitEqualsRetained=self._same(actual,self._identity_refs[role]),
                differentFrom={key:self._same(actual,ref) for key,ref in self._identity_refs.items() if key!=role})
            assert comparison['rawMatchesTarget'] is comparison['hitEqualsRetained'] is False
            assert comparison['targetEqualsRetained'] is True and all(value is False for value in comparison['differentFrom'].values())
            global_point=dict(kindCode=self._uia_call(9,lambda:actual.CurrentControlType),
                pid=self._uia_call(8,lambda:actual.CurrentProcessId),nativeHwndRaw=_getter_call_site(self,17,self._uia_call,7,lambda:actual.CurrentNativeWindowHandle))
            assert all(type(value) is int for value in global_point.values())
            raw=global_point['nativeHwndRaw'];assert -(1<<31)<=raw<1<<32
            global_point['nativeHwnd']=raw&0xffffffff if raw<0 else raw
            assert global_point['kindCode']==50033 and global_point['pid']==binding['officePid']
            rectangle=_getter_call_site(self,18,self._chrome,target)['rectangle'];before=self._popup_exposure(binding,point,rectangle)
            assert global_point['nativeHwnd']==before['hwnd']
            captured_at=self.clock();effective=min(action_deadline,captured_at+1.5)
            self.deadline=effective
            source_fresh,fresh_refs=self._fresh_proof_with_refs(self._active_target)
            assert self.clock()<effective
            assert self._same(target,fresh_refs[role]), 'Current source-qualified target differs from fresh target'
            roles=[key for key in self._identity_refs if key!=role]
            negative=[self._identity_refs[key] for key in roles]+[actual]
            sequence=getattr(self,'_point_sequence',0)+1;assert sequence<=32;self._point_sequence=sequence
            lease=self._begin_source_qualified_ia2_point_v4(fresh_refs,negative,sequence,point,admission=admission,
                captured_at=captured_at,action_deadline=action_deadline,exposure=before)
            self._msaa_lease=lease
            packet=lease.wait()
            # No fresh provider read is admissible until original retirement is known.
            assert lease.pending is False
            provider=_source_qualified_packet_v4(packet,scope,creator,sequence,len(negative),digest)
            assert self.clock()<effective, 'Source-qualified point source age expired'
            self.interop['providerLocalResult']=provider
            assert self._require_provider_creator()==creator
            after=self._popup_exposure(binding,point,rectangle);assert before==after
            fresh=self._fresh_proof(self._active_target)
            assert self.clock()<effective
            result=dict(schemaVersion=4,method='owned-popup-and-source-qualified-ia2-hit-v4',
                scope=copy.deepcopy(scope),role=role,sourceScopeId=sequence,sourceScope=asdict(lease.scope),
                negativeRoles=roles+['global-point'],provider=provider,before=before,after=after,
                sourceFresh=source_fresh,fresh=fresh,creator=creator,globalPoint=global_point,
                sourceAdmissionSha256=digest,capturedAt=captured_at,effectiveDeadline=effective,
                finalPointVerified=1,targetRectangle=list(rectangle),primaryComparison=comparison)
            _require_provider_point_v4(result,binding,scope['shellPid'],self._active_target,
                admission_sha256=digest,now=self.clock())
            return result
        finally:self.deadline=action_deadline


def _source_qualified_packet_v4(packet,scope,creator,scope_id,negative_count,admission_sha256):
    """Validate the complete numeric capsule before any post-worker provider read."""
    from native_menu_msaa_hit import _record_v4,worker_record_v4,_valid_v4_worker
    assert type(packet) is dict and packet.keys()==_record_v4(None,False).keys()
    assert all(type(value) is int and 0<=value<(1<<64 if key=='threadBirth' else 1<<32)
        for key,value in packet.items())
    assert packet['schemaVersion']==packet['workerSchemaVersion']==4
    assert packet['scopeId']==scope_id and packet['stageCode']==13
    assert packet['pointCandidate']==packet['sourceBound']==1
    worker={key:packet[key] for key in worker_record_v4()}
    assert _valid_v4_worker(worker,negative_count,admission_sha256)
    ones=('providerLocalOnly','nativeAttempted','nativeExit','threadClosed','processesClosed',
        'workerCleanup','threadIdentity','callbackIdentity','exitCodeObserved')
    zeros=('diagnosticOnly','acceptanceEligible','globalHitSubstituted','synthetic','workerException',
        'pending','localKnown','localMatch','nativeExitCode')
    assert all(packet[key]==1 for key in ones) and all(packet[key]==0 for key in zeros)
    for key in ('controllerPid','threadId','threadBirth'):_int(packet[key])
    assert packet['controllerPid'] not in (scope['shellPid'],scope['binding']['officePid'])
    assert packet['threadId']!=creator['threadId']
    return copy.deepcopy(packet)


def _require_provider_point_v4(proof,binding,shell_pid,target,*,admission_sha256,now):
    """Replay only this new source-bound point; old global FALSE remains FALSE."""
    from native_menu_msaa_hit import MsaaHitScope
    assert target!='file'
    expected=set(('schemaVersion method scope role sourceScopeId sourceScope negativeRoles provider '
        'before after sourceFresh fresh creator globalPoint sourceAdmissionSha256 capturedAt '
        'effectiveDeadline finalPointVerified targetRectangle primaryComparison').split())
    assert type(proof) is dict and set(proof)==expected
    assert type(proof['schemaVersion']) is int and proof['schemaVersion']==4
    assert proof['method']=='owned-popup-and-source-qualified-ia2-hit-v4'
    assert type(proof['finalPointVerified']) is int and proof['finalPointVerified']==1
    assert type(admission_sha256) is str and len(admission_sha256)==64
    assert all(c in '0123456789abcdef' for c in admission_sha256)
    assert proof['sourceAdmissionSha256']==admission_sha256
    scope=proof['scope'];_scope_anchor(scope,binding,shell_pid);role=_target_role(target)
    assert target in _scope_targets(scope) and proof['role']==role
    captured,expiry=proof['capturedAt'],proof['effectiveDeadline']
    assert all(type(value) in (int,float) and math.isfinite(value) for value in (captured,expiry,now))
    assert scope['startedAt']<=captured<scope['deadline']
    assert expiry==min(scope['deadline'],captured+1.5) and captured<=now<expiry
    assert type(proof['sourceScopeId']) is int and 0<proof['sourceScopeId']<=32
    for field in ('sourceFresh','fresh'):
        _comparison_proof(proof[field],binding,shell_pid,target)
        assert proof[field]['scope']==scope
    roles=proof['sourceFresh']['roles'];assert proof['fresh']['roles']==roles
    negatives=[name for name in roles if name!=role]
    assert proof['negativeRoles']==negatives+['global-point']
    primary=proof['primaryComparison']
    assert type(primary) is dict and set(primary)=={'rawMatchesTarget','targetEqualsRetained','hitEqualsRetained','differentFrom'}
    assert primary['rawMatchesTarget'] is primary['hitEqualsRetained'] is False
    assert primary['targetEqualsRetained'] is True
    assert type(primary['differentFrom']) is dict and set(primary['differentFrom'])==set(negatives)
    assert all(value is False for value in primary['differentFrom'].values())
    creator=proof['creator'];assert type(creator) is dict and set(creator)=={'threadId','mta','sameThread'}
    _int(creator['threadId']);assert creator['threadId']<1<<32
    assert creator['mta'] is creator['sameThread'] is True
    _source_qualified_packet_v4(proof['provider'],scope,creator,proof['sourceScopeId'],len(negatives)+1,admission_sha256)
    before=proof['before'];assert type(before) is dict and before==proof['after']
    assert set(before)==set(('classCode hwnd pid threadId rootHwnd style extendedStyle rectangle point '
        'ownerChain foreground ownershipBefore ownershipAfter').split())
    assert before['classCode']==1 and before['ownershipBefore'] is before['ownershipAfter'] is True
    for key in ('classCode','pid','threadId'):
        _int(before[key]);assert before[key]<1<<32
    for key in ('hwnd','rootHwnd','foreground'):
        _int(before[key]);assert before[key]<1<<64
    assert before['hwnd']==before['rootHwnd'] and before['pid']==binding['officePid']
    owners=before['ownerChain'];assert type(owners) is list and 2<=len(owners)<=16
    assert all(type(value) is int and 0<value<1<<64 for value in owners) and len(set(owners))==len(owners)
    assert owners[0]==before['hwnd'] and owners[-1] in (binding['child'],binding['document'])
    assert all(type(before[key]) is int and 0<=before[key]<1<<32 for key in ('style','extendedStyle'))
    assert before['style']&0x80000000 and not before['style']&0x40000000 and before['extendedStyle']&0x80
    assert before['foreground'] in (binding['document'],before['hwnd'])
    rect=before['rectangle'];target_rect=proof['targetRectangle'];point=before['point']
    assert all(type(row) is list for row in (rect,target_rect,point))
    assert len(rect)==len(target_rect)==4 and len(point)==2
    assert all(type(value) is int and -(1<<31)<=value<1<<31 for value in (*rect,*target_rect,*point))
    assert rect[0]<=target_rect[0]<=point[0]<target_rect[2]<=rect[2]
    assert rect[1]<=target_rect[1]<=point[1]<target_rect[3]<=rect[3]
    source_scope=proof['sourceScope'];assert type(source_scope) is dict
    assert source_scope==dict(scope_id=proof['sourceScopeId'],engine_pid=binding['officePid'],
        engine_birth=scope['officeCreationTime'],shell_pid=shell_pid,shell_birth=scope['shellCreationTime'],
        parent_hwnd=binding['parent'],child_hwnd=binding['child'],x=point[0],y=point[1])
    assert MsaaHitScope(**source_scope).valid()
    global_point=proof['globalPoint']
    assert type(global_point) is dict and set(global_point)=={'kindCode','pid','nativeHwndRaw','nativeHwnd'}
    assert all(type(value) is int for value in global_point.values())
    raw=global_point['nativeHwndRaw'];assert -(1<<31)<=raw<1<<32
    assert global_point['nativeHwnd']==(raw&0xffffffff if raw<0 else raw)
    assert global_point==dict(kindCode=50033,pid=binding['officePid'],nativeHwndRaw=raw,nativeHwnd=before['hwnd'])
    return proof


def _source_admission_summary(admission):
    """Only the actual sealed Gate supplies a source replay authority."""
    from native_menu_msaa_hit import _admission_words_v4
    from native_menu_source_admission import SourceMenuAdmission
    if type(admission) is not SourceMenuAdmission:raise ValueError('An actual source menu admission is required')
    _admission_words_v4(admission,admission.admission_sha256)
    result=dict(admission.summary())
    result['providers']=[dict(item) for item in result['providers']]
    return result


def _source_generation(binding,shell,engine,handle):
    result=dict(document=binding['document'],parent=binding['parent'],child=binding['child'],
        officePid=binding['officePid'],shellPid=shell['pid'],shellCreationTime=shell['creationTime'],
        shellHandleValue=shell['handleValue'],engineCreationTime=engine['creationTime'],engineHandleValue=handle)
    assert all(type(number) is int and 0<number<1<<64 for number in result.values())
    assert result['officePid']<1<<32 and result['shellPid']<1<<32 and result['officePid']!=result['shellPid']
    assert result['engineCreationTime']>=result['shellCreationTime']
    return result


def _bind_source_generation(probe,process,suite,binding,shell,engine,handle,receipt):
    selection=getattr(probe,'source_selection',None)
    assert selection is getattr(process,'opengeul_source_menu_selection',None), 'Source probe/process selection changed'
    if selection is None:return
    from native_menu_source_selection import _require_selection
    _require_selection(selection)
    admission=selection.prepared.admission;summary=_source_admission_summary(admission)
    root=Path(admission.suite_root)
    assert Path(suite).resolve()==root and Path(process.opengeul_suite_root).resolve()==root
    assert Path(shell['image']).resolve()==root/'OpenGeul.Office.exe'
    assert Path(engine['image']).resolve()==root/'Office/program/soffice.bin'
    assert shell['pid']==process.pid and shell['handleValue']==int(process._handle)
    assert engine['pid']==binding['officePid'] and engine['handleValue']==handle
    assert shell['waitResult']==engine['waitResult']==258
    generation=_source_generation(binding,shell,engine,handle)
    probe._source_generation_binding=copy.deepcopy(generation)
    probe._source_process=process;probe._source_bound_selection=selection
    # Keep the inherited legacy send wrapper exactly intact. Only a successfully
    # bound source-selected instance installs the extra expiry admission.
    source_send=getattr(probe,'_source_send',None)
    if source_send is not None:probe.send=source_send
    receipt['sourceMenu']=dict(schemaVersion=1,pointProfileVersion=4,focusProtocolVersion=1,admission=summary,generation=generation)
    # Each newly generated source snapshot carries the current mandatory focus
    # protocol, including snapshots that need no focused-ancestry walk. Removing
    # the new proof cannot silently select a historical retained-only contract.
    original=getattr(probe,'_source_snapshot_original',None)
    if original is None:
        original=probe.snapshot;probe._source_snapshot_original=original
    scope=_menu_scope(binding,shell,engine,receipt['startedAt'],receipt['deadline'])
    def snapshot(*args,**kwargs):
        probe._source_focus_proof=None;probe._source_focus_branch=0
        measured=original(*args,**kwargs)
        focused=measured.get('focusMenuElementEquals') is True
        branch=getattr(probe,'_source_focus_branch',0)
        # Any compared focused path must have been produced by the closed walker.
        assert not focused or branch in (1,2)
        measured['sourceFocus']=dict(protocolVersion=1,admissionSha256=summary['admissionSha256'],
            scope=copy.deepcopy(scope),branchCode=branch,proof=copy.deepcopy(probe._source_focus_proof))
        return measured
    probe.snapshot=snapshot
    receipt['pointUses']=[]
    probe._source_point_uses=receipt['pointUses'];probe._source_input_points=[];probe._source_input_receipt=None


def _require_source_header(value,admission):
    summary=_source_admission_summary(admission);header=value['sourceMenu']
    assert type(header) is dict and set(header)=={'schemaVersion','pointProfileVersion','focusProtocolVersion','admission','generation'}
    assert type(header['schemaVersion']) is int and header['schemaVersion']==1
    assert type(header['pointProfileVersion']) is int and header['pointProfileVersion']==4
    assert type(header['focusProtocolVersion']) is int and header['focusProtocolVersion']==1
    assert json.dumps(header['admission'],sort_keys=True,separators=(',',':'),ensure_ascii=True)==json.dumps(summary,sort_keys=True,separators=(',',':'),ensure_ascii=True)
    shell,engine=value['originalProcess'],value['originalEngine']
    root=Path(admission.suite_root)
    assert Path(shell['image']).resolve()==root/'OpenGeul.Office.exe'
    assert Path(engine['image']).resolve()==root/'Office/program/soffice.bin'
    expected=_source_generation(value['binding'],shell,engine,value['engineHandleValue'])
    assert type(header['generation']) is dict and set(header['generation'])==set(expected)
    assert all(type(number) is int for number in header['generation'].values()) and header['generation']==expected
    uses=value['pointUses'];assert type(uses) is list and len(uses)<=128
    assert all(type(value[key]) in (int,float) and math.isfinite(value[key]) for key in ('startedAt','deadline','finishedAt'))
    pending=[value];count=0
    while pending:
        node=pending.pop();count+=1;assert count<=1_000_000
        if type(node) is dict:
            if 'pointMethod' in node:assert node['pointMethod'] in ('global-uia','owned-popup-and-source-qualified-ia2-hit-v4')
            if 'workerSchemaVersion' in node:assert type(node['workerSchemaVersion']) is int and node['workerSchemaVersion']==4
            assert 'identityDiagnosticResult' not in node and 'identityDiagnosticControl' not in node
            pending.extend(node.values())
        elif type(node) is list:pending.extend(node)
    return summary


def _require_source_focus_snapshot(snapshot,value,admission):
    marker=snapshot['sourceFocus']
    assert type(marker) is dict and set(marker)=={'protocolVersion','admissionSha256','scope','branchCode','proof'}
    assert type(marker['protocolVersion']) is int and marker['protocolVersion']==1
    assert marker['admissionSha256']==admission.admission_sha256
    binding=value['binding'];shell_pid=value['shellPid']
    scope=_menu_scope(binding,value['originalProcess'],value['originalEngine'],value['startedAt'],value['deadline'])
    assert marker['scope']==scope
    branch=marker['branchCode'];assert type(branch) is int and branch in (0,1,2)
    if branch==0:
        assert marker['proof'] is None and snapshot.get('focusMenuPath',[])==[]
        assert snapshot.get('focusMenuElementEquals',False) is False
        return
    identity=snapshot['identityProof'];_comparison_proof(identity,binding,shell_pid,'file')
    proof=marker['proof']
    assert type(proof) is dict and set(proof)=={'schemaVersion','scope','before','after','focusFreshEquals','focusEndEquals','rows','edges','terminalRole'}
    assert type(proof['schemaVersion']) is int and proof['schemaVersion']==1
    assert proof['scope']==identity['scope']==value['elementIdentityScope']
    assert proof['focusFreshEquals'] is proof['focusEndEquals'] is True
    before=proof['before'];popup=snapshot['popup'];assert popup is not None
    fields={'childHwnd','childPid','childRootHwnd','childThreadId','foreground','popupHwnd','popupThreadId','popupRectangle','ownerChain'}
    assert type(before) is dict and set(before)==fields and proof['after']==before
    for key in fields-{'popupRectangle','ownerChain'}:_int(before[key])
    assert before['childHwnd']==binding['child'] and before['childPid']==binding['officePid']
    assert before['childRootHwnd']==binding['document']
    assert before['childThreadId']==popup['threadId']==before['popupThreadId']
    assert before['foreground']==snapshot['foreground']['hwnd'] and before['foreground'] in (binding['document'],popup['hwnd'])
    assert before['popupHwnd']==popup['hwnd'] and before['ownerChain']==popup['ownerChain']
    assert before['popupRectangle']==popup['rectangle']
    outer=before['popupRectangle'];assert type(outer) is list and len(outer)==4
    assert all(type(n) is int and -(1<<31)<=n<1<<31 for n in outer)
    assert outer[0]<outer[2] and outer[1]<outer[3]
    rows=proof['rows'];edges=proof['edges']
    assert type(rows) is list and 0<len(rows)<=32 and type(edges) is list and len(edges)==len(rows)-1
    retained=[];unknown=0;roles=identity['roles']
    for index,item in enumerate(rows):
        assert type(item) is dict and set(item)=={'observation','retainedRole','differentFrom','differentFromPrior'}
        comparisons=item['differentFrom'];role=item['retainedRole'];row=item['observation']
        assert type(comparisons) is dict and set(comparisons)==set(roles)
        assert all(type(same) is bool for same in comparisons.values())
        previous=item['differentFromPrior']
        assert type(previous) is list and len(previous)==index and all(same is False for same in previous)
        assert type(row) is dict and type(row['pid']) is int and row['pid']==binding['officePid']
        assert row['visible'] is row['enabled'] is True
        if role is None:
            unknown+=1;assert all(same is False for same in comparisons.values())
            assert set(row)=={'runtimeId','runtimeObservation','pid','kindCode','nativeHwnd','visible','enabled','rectangle'}
            runtime=row['runtimeId']
            assert type(runtime) is list and len(runtime)<=64
            assert all(type(n) is int and -(1<<31)<=n<1<<31 for n in runtime)
            assert type(row['kindCode']) is int and row['kindCode']==50011
            observed=row['runtimeObservation']
            assert observed['callSucceeded'] is observed['signed32Valid'] is observed['versionObserved'] is True
            assert observed['empty'] is (not runtime)
            assert type(observed['rawTypeCode']) is int and observed['rawTypeCode'] in (1,2)
            assert type(observed['length']) is int and observed['length']==len(runtime)
            types=observed['elementTypeCodes']
            assert type(types) is list and len(types)==len(runtime) and all(type(n) is int and n==1 for n in types)
            version=observed['versionTuple']
            assert type(version) is list and len(version)==3 and all(type(n) is int and 0<=n<=65535 for n in version)
            declaration=observed['declaration'];assert declaration['verified'] is True
            assert all(declaration[key] is True for key in ('interfaceKnown','methodUnique','hresultDeclared',
                'singleOutArgument','outFlag','retvalFlag','exactFlags','safeArrayInt32'))
            assert declaration['hresultValueObserved'] is declaration['safeArrayPointerObserved'] is declaration['safeArrayDimensionsObserved'] is False
            assert type(row['nativeHwnd']) is int and row['nativeHwnd'] in (0,popup['hwnd'])
            rect=row['rectangle'];assert type(rect) is list and len(rect)==4
            assert all(type(n) is int and -(1<<31)<=n<1<<31 for n in rect)
            assert outer[0]<=rect[0]<rect[2]<=outer[2] and outer[1]<=rect[1]<rect[3]<=outer[3]
        else:
            assert type(role) is str and (role in ('file','bar') or role.startswith('target:')) and role in roles
            assert all(same is (name==role) for name,same in comparisons.items())
            _element_anchor(row,identity,binding,shell_pid)
            if not row['runtimeId']:assert row['identity']['role']==role
            retained.append(row)
        if index<len(edges):
            edge=edges[index]
            assert type(edge) is dict and set(edge)=={'parentFreshEquals','differentFromEarlier'}
            assert edge['parentFreshEquals'] is True
            negatives=edge['differentFromEarlier']
            assert type(negatives) is list and len(negatives)==index+1 and all(same is False for same in negatives)
    assert (unknown==0 if branch==1 else unknown>0)
    assert retained==snapshot['focusMenuPath'] and snapshot['focusMenuElementEquals'] is True
    assert rows[-1]['retainedRole']==proof['terminalRole']==snapshot['focusIdentity']['role']
    assert proof['terminalRole'] in ('file','bar')


def _require_source_focus_protocol(value,admission):
    pending=[value];count=0;snapshots=0
    while pending:
        node=pending.pop();count+=1;assert count<=1_000_000
        if type(node) is dict:
            if {'binding','control','ancestry','attachmentValid','gui'}<=set(node):
                _require_source_focus_snapshot(node,value,admission);snapshots+=1
            pending.extend(node.values())
        elif type(node) is list:pending.extend(node)
    assert snapshots>0


def require_source_qualified_native_menu_action(value,shell_pid,document,*,admission,command=None):
    _require_source_header(value,admission)
    _require_source_focus_protocol(value,admission)
    # Only this public actual-object check supplies authority. The shared record
    # validator itself proves structural/history consistency, never source trust.
    result=_require_native_menu_action_record(value,shell_pid,document,command,source_admission=admission)
    _require_source_point_uses(value,admission)
    return result


def require_native_menu_action(value,shell_pid,document,command=None,*,source_admission=None):
    if source_admission is not None:
        return require_source_qualified_native_menu_action(value,shell_pid,document,
            admission=source_admission,command=command)
    assert 'sourceMenu' not in value, 'Source-qualified menu replay requires the actual Gate'
    return _require_native_menu_action_record(value,shell_pid,document,command)


def _source_bound_admission(probe,*,require_scope=True):
    selection=probe.source_selection
    from native_menu_source_selection import _require_selection
    _require_selection(selection)
    assert selection is probe._source_bound_selection
    process=probe._source_process;generation=probe._source_generation_binding
    assert process.opengeul_source_menu_selection is selection and process.poll() is None
    assert (process.pid,int(process._handle))==(generation['shellPid'],generation['shellHandleValue'])
    if not require_scope:return selection.prepared.admission
    scope=probe._identity_scope;binding=scope['binding']
    assert all(binding[key]==generation[key] for key in ('document','parent','child','officePid'))
    assert scope['shellPid']==generation['shellPid'] and scope['shellCreationTime']==generation['shellCreationTime']
    assert scope['officeCreationTime']==generation['engineCreationTime']
    assert probe._point_source==dict(shellHandle=generation['shellHandleValue'],engineHandle=generation['engineHandleValue'])
    return selection.prepared.admission


def _replay_point_at(snapshot,admission):
    if admission is None:return None
    return snapshot.get('targetPointProof',{}).get('pointObservedAt')


def _require_source_point_v4(hit,snapshot,target,admission,*,now):
    digest=_source_admission_summary(admission)['admissionSha256']
    assert target!='file' and hit['uiaMatches'] is False
    proof=hit['providerLocalProof'];scope=snapshot['identityProof']['scope']
    binding=scope['binding'];shell_pid=scope['shellPid']
    _require_provider_point_v4(proof,binding,shell_pid,target,admission_sha256=digest,now=now)
    assert proof['scope']==scope and proof['targetRectangle']==snapshot['control']['rectangle']
    original=hit['identityProof'];role=_target_role(target)
    assert original['scope']==scope and original['role']==role
    assert original['targetEqualsRetained'] is True and original['hitEqualsRetained'] is False
    assert original['differentFrom']==proof['primaryComparison']['differentFrom']
    assert all(value is False for value in original['differentFrom'].values())
    popup=snapshot['popup'];before=proof['before']
    assert before['hwnd']==before['rootHwnd']==hit['hitHwnd']==hit['rootHwnd']==popup['hwnd']
    assert before['pid']==hit['pid']==binding['officePid'] and before['threadId']==popup['threadId']
    assert before['ownerChain']==popup['ownerChain'] and before['point']==hit['point']
    observed=hit['pointObservedAt']
    assert type(observed) in (int,float) and math.isfinite(observed)
    assert proof['capturedAt']<=observed<=now<proof['effectiveDeadline']


def _source_point_use(probe,hit,code,at):
    if hit is None or hit.get('pointMethod')!='owned-popup-and-source-qualified-ia2-hit-v4':return
    uses=probe._source_point_uses;assert len(uses)<128
    uses.append(dict(sourceScopeId=hit['providerLocalProof']['sourceScopeId'],at=at,useCode=code))


def _arm_source_input(probe,receipt,points,uses):
    if getattr(probe,'source_selection',None) is None:return
    probe._source_input_points=[hit for hit in points if hit is not None and hit.get('pointMethod')=='owned-popup-and-source-qualified-ia2-hit-v4']
    assert len(probe._source_input_points)<=1
    probe._source_input_receipt=receipt;probe._source_input_use_code=uses


def _require_source_point_uses(value,admission):
    """Replay recorded observations and consumption; no current provider or clock."""
    points={};expected=[]
    def add(hit,snapshot,target,code):
        if hit is None or hit.get('pointMethod')!='owned-popup-and-source-qualified-ia2-hit-v4':return None
        at=hit['pointObservedAt'];_require_source_point_v4(hit,snapshot,target,admission,now=at)
        identity=hit['providerLocalProof']['sourceScopeId']
        assert identity not in points, 'A source measurement was reused for a new semantic site'
        points[identity]=hit;expected.append(dict(sourceScopeId=identity,at=at,useCode=code))
        return identity
    for item in value['pointers']:
        if item['target']=='outside':continue
        snapshots=item['snapshots'];hits=item['hits'];target=item['target']
        add(snapshots[0].get('targetPointProof'),snapshots[0],target,1)
        last=None
        for snapshot,hit in zip(snapshots[1:],hits):
            add(snapshot.get('targetPointProof'),snapshot,target,1)
            last=add(hit,snapshot,target,2)
        if last is not None:
            at=item['inputStartedAt'];proof=points[last]['providerLocalProof']
            finished=item['inputFinishedAt']
            assert type(finished) in (int,float) and math.isfinite(finished)
            assert at<=finished<proof['effectiveDeadline'] and finished<=value['finishedAt']
            assert proof['capturedAt']<=at<proof['effectiveDeadline']
            expected.append(dict(sourceScopeId=last,at=at,useCode=3))
    # Snapshot-only gestures occur after pointer preparation and before keys.
    observations=[]
    if value.get('coreCommandsVerified') is True:
        observations.extend((target,value['coreSnapshots'][target]) for target in CORE_COMMANDS)
    if value.get('disabledObserved') is True:
        observations.append((value['command'][len('disabled-'):],value['disabledSnapshot']))
    for target,snapshot in observations:add(snapshot.get('targetPointProof'),snapshot,target,1)
    extras=value.get('sourcePointSnapshots',[])
    assert type(extras) is list and len(extras)<=1
    assert not extras or value['gesture'] is True and value['command'] in ('open-escape','open-outside','keyboard-escape')
    for snapshot in extras:
        hit=snapshot.get('targetPointProof');assert hit is not None
        identity=hit['providerLocalProof']['sourceScopeId']
        assert identity not in points, 'Stored source observation duplicates a semantic site'
        assert snapshot['identityProof']['scope']==value['elementIdentityScope']
        role=hit['identityProof']['role'];assert role=='target:save'
        _validate(snapshot,value['binding'],value['shellPid'],role[len('target:'):],
            menu_scope=_menu_scope(value['binding'],value['originalProcess'],value['originalEngine'],value['startedAt'],value['deadline']),
            source_admission=admission,point_at=hit['pointObservedAt'])
        add(hit,snapshot,role[len('target:'):],1)
    for item in value['keys']:
        snapshot=item['before'];hit=snapshot.get('targetPointProof')
        if hit is None:continue
        identity=hit['providerLocalProof']['sourceScopeId']
        add(hit,snapshot,'save',1)
        at=item['inputStartedAt'];proof=hit['providerLocalProof']
        assert proof['capturedAt']<=at<proof['effectiveDeadline']
        expected.append(dict(sourceScopeId=identity,at=at,useCode=4))
    uses=value['pointUses']
    assert all(type(row) is dict and set(row)=={'sourceScopeId','at','useCode'} and
        type(row['sourceScopeId']) is int and type(row['useCode']) is int and
        type(row['at']) in (int,float) and math.isfinite(row['at']) for row in uses)
    # Replay the producer order; sorting observations by an attacker-supplied
    # time would erase the serial fresh-discovery boundary.
    assert uses==expected
    assert list(points)==list(range(1,len(points)+1)), 'Independent source sites changed order'
    assert all(value['startedAt']<=row['at']<value['finishedAt'] for row in uses)
    previous=value['startedAt'];seen=set()
    for row in uses:
        identity=row['sourceScopeId']
        if identity not in seen:
            assert points[identity]['providerLocalProof']['capturedAt']>=previous
            seen.add(identity)
        assert row['at']>=previous;previous=row['at']
