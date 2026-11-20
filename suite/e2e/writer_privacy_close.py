"""One exact OS privacy close before the separate Writer diagnostic budget."""
import ctypes
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import math
import stat
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
ENTRY='suite/e2e/writer_privacy_close.py'
JOB='writer-server-observer'
REPORT='.work/writer-os-privacy-public/receipt.numeric.json'
CHILD='privacy-close-child.numeric.json'
CORE_CLASS='Windows.UI.Core.CoreWindow'
MAX_BYTES=8192
PUBLIC_ENV=('GITHUB_REPOSITORY_OWNER','GITHUB_TRIGGERING_ACTOR','WRITER_OBSERVER_ENABLED',
            'WRITER_OBSERVER_SUITE_HEAD','WRITER_OBSERVER_PHASE_SECONDS')

def need(value):
    if not value:raise ValueError('Writer privacy preparation rejected')

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module

def load_guard(root):return load_module('writer_privacy_admission',Path(root)/'suite/scripts/writer-server-observer-workflow.py')
def load_core(root):return load_module('writer_privacy_control',Path(root)/'e2e/native31_desktop_control.py')

def words(value):return [int(value[i:i+8],16) for i in range(0,40,8)]

def empty_record():
    return dict(schemaVersion=1,recordKindCode=1,diagnosticOnly=True,acceptanceEligible=False,
        normalAcceptance=False,hostReadyQualified=False,osBudgetSeconds=120,writerSeconds=None,
        sourceAdmitted=False,sourceCommitWords=None,targetCommitWords=None,runId=None,runAttempt=None,
        sourceFileCount=None,stageCode=0,errorCode=0,preparationPassed=False,observationPassed=False,
        observationStatusCode=0,foregroundRootOnly=True,foregroundHwnd=None,foregroundRootHwnd=None,
        foregroundPid=None,foregroundTid=None,foregroundClassCode=None,coreWindowObserved=None,
        processVerified=None,signatureVerified=None,titleReadAttempted=False,uiaAttempted=False,
        privacyValidated=None,queryHandlesReleased=None,closeRequests=0,messageDelivered=None,
        surfaceDismissed=None,observerPid=None,observerBirth=None,observerExitCode=None,
        naturalExit=None,jobRetiredNaturally=None,forcedOwnedCleanup=None,timedOut=None,
        keyboardInputs=0,pointerInputs=0,foregroundSetCalls=0,foreignKillCalls=0)

def validate_record(row):
    need(type(row) is dict and set(row)==set(empty_record()))
    for key,value in [('schemaVersion',1),('osBudgetSeconds',120)]:need(type(row[key]) is int and row[key]==value)
    for key in ('diagnosticOnly','foregroundRootOnly'):need(row[key] is True)
    for key in ('acceptanceEligible','normalAcceptance','hostReadyQualified'):need(row[key] is False)
    for key in ('sourceAdmitted','preparationPassed','observationPassed'):need(type(row[key]) is bool)
    for key in ('coreWindowObserved','processVerified','signatureVerified','titleReadAttempted','uiaAttempted',
        'privacyValidated','queryHandlesReleased','messageDelivered','surfaceDismissed','naturalExit',
        'jobRetiredNaturally','forcedOwnedCleanup','timedOut'):
        need(row[key] is None or type(row[key]) is bool)
    for key in ('keyboardInputs','pointerInputs','foregroundSetCalls','foreignKillCalls'):
        need(type(row[key]) is int and row[key]==0)
    for key,low,high in [('recordKindCode',1,2),('stageCode',0,20),('errorCode',0,9),
        ('observationStatusCode',0,2)]:need(type(row[key]) is int and low<=row[key]<=high)
    for key in ('sourceCommitWords','targetCommitWords'):
        value=row[key];need(value is None or type(value) is list and len(value)==5 and all(type(x) is int and 0<=x<2**32 for x in value))
    for key,bits in [('runId',64),('sourceFileCount',32),('foregroundHwnd',64),('foregroundRootHwnd',64),
        ('foregroundPid',32),('foregroundTid',32),('observerPid',32),('observerBirth',64)]:
        need(row[key] is None or type(row[key]) is int and 0<row[key]<2**bits)
    need(row['runAttempt'] is None or type(row['runAttempt']) is int and row['runAttempt']==1)
    need(row['writerSeconds'] is None or type(row['writerSeconds']) is int and row['writerSeconds'] in (55,60))
    need(row['foregroundClassCode'] is None or type(row['foregroundClassCode']) is int and row['foregroundClassCode'] in (0,5))
    need(row['closeRequests'] is None or type(row['closeRequests']) is int and row['closeRequests'] in (0,1))
    need(row['observerExitCode'] is None or type(row['observerExitCode']) is int and 0<=row['observerExitCode']<2**32)
    if row['sourceAdmitted']:
        need(all(row[key] is not None for key in ('sourceCommitWords','targetCommitWords','runId','runAttempt','sourceFileCount','writerSeconds')))
    if row['titleReadAttempted'] is True or row['uiaAttempted'] is True:
        need(row['processVerified'] is True and row['signatureVerified'] is True)
    if row['observationPassed']:
        need(row['sourceAdmitted'] and row['queryHandlesReleased'] is not False)
        if row['observationStatusCode']==1:
            need(row['coreWindowObserved'] is False and row['closeRequests']==0 and row['titleReadAttempted'] is False and row['uiaAttempted'] is False)
        else:
            need(row['observationStatusCode']==2 and row['processVerified'] is True and row['signatureVerified'] is True
                and row['privacyValidated'] is True and row['queryHandlesReleased'] is True
                and row['closeRequests']==1 and row['messageDelivered'] is True and row['surfaceDismissed'] is True)
    if row['preparationPassed']:
        need(row['recordKindCode']==1 and row['observationPassed'] and row['naturalExit'] is True
            and row['jobRetiredNaturally'] is True and row['forcedOwnedCleanup'] is False
            and row['timedOut'] is False and row['observerExitCode']==0 and row['errorCode']==0)
    return row

def merge_observer(base,owned,child,*,source_verified):
    row=dict(base);row['recordKindCode']=1
    for source,target in [('naturalExit','naturalExit'),('jobRetiredNaturally','jobRetiredNaturally'),
        ('forced','forcedOwnedCleanup'),('timedOut','timedOut')]:
        value=owned.get(source);row[target]=value if type(value) is bool else None
    code=owned.get('exitCode');row['observerExitCode']=code if type(code) is int and 0<=code<2**32 else None
    identity=owned.get('observer')
    identity=identity if type(identity) is dict else {}
    pid,birth=identity.get('processId'),identity.get('createdFileTime')
    row['observerPid']=pid if type(pid) is int and 0<pid<2**32 else None
    row['observerBirth']=birth if type(birth) is int and 0<birth<2**64 else None
    # A missing/invalid child can have acted. Never infer zero messages or reads.
    uncertain=('foregroundHwnd','foregroundRootHwnd','foregroundPid','foregroundTid','foregroundClassCode',
        'coreWindowObserved','processVerified','signatureVerified','titleReadAttempted','uiaAttempted',
        'privacyValidated','queryHandlesReleased','closeRequests','messageDelivered','surfaceDismissed')
    for key in uncertain:row[key]=None
    row.update(observationPassed=False,observationStatusCode=0,preparationPassed=False,
        errorCode=2 if row['timedOut'] is True else 5,stageCode=11)
    valid=False
    try:
        validate_record(child)
        need(child['recordKindCode']==2 and row['observerPid'] is not None and row['observerBirth'] is not None)
        for key in ('sourceCommitWords','targetCommitWords','runId','runAttempt','writerSeconds','sourceFileCount','observerPid','observerBirth'):
            need(child[key]==row[key])
        for key in (*uncertain,'observationPassed','observationStatusCode','stageCode','errorCode'):row[key]=child[key]
        valid=True
    except (ValueError,TypeError,KeyError):pass
    good=(valid and source_verified is True and owned.get('success') is True
        and row['naturalExit'] is True and row['jobRetiredNaturally'] is True
        and row['forcedOwnedCleanup'] is False and row['timedOut'] is False
        and row['observerExitCode']==0 and row['observationPassed'] and row['errorCode']==0)
    row['preparationPassed']=good
    if source_verified is False:row.update(errorCode=1,stageCode=12)
    return validate_record(row)

def admit(guard,root,env,event,*,platform,budget=None):
    # The unchanged static source verifier has its own fixed thirty-second bound.
    if budget is not None:budget.remaining(33)
    fixed={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
           'RUNNER_ARCH':'ARM64','GITHUB_JOB':JOB,'GITHUB_RUN_ATTEMPT':'1'}
    need(platform=='nt' and all(env.get(k)==v for k,v in fixed.items()))
    guard.require_push_context(env,event)
    count,seconds=guard.verify_request_source(root,env['GITHUB_SHA'],event)
    if budget is not None:budget.remaining(3)
    need(type(count) is int and count>0 and type(seconds) is int and seconds in (55,60))
    run=env.get('GITHUB_RUN_ID');need(type(run) is str and re.fullmatch('[1-9][0-9]{0,19}',run) is not None and int(run)<2**64)
    return dict(sourceAdmitted=True,sourceCommitWords=words(env['GITHUB_SHA']),
        targetCommitWords=words(event['before']),sourceFileCount=count,writerSeconds=seconds,runId=int(run),runAttempt=1)

def child_environment(core,env):
    result=core.child_environment(env)
    for key in ('GITHUB_SHA',*PUBLIC_ENV):
        if key in env:result[key]=env[key]
    return result

def control_binding(core,guard):
    return core.ControlBinding('refs/heads/'+guard.BRANCH,guard.WORKFLOW,JOB,ENTRY,
        (ENTRY,'.github/workflows/office-suite.yml','suite/scripts/writer-server-observer-workflow.py',guard.REQUEST))

def _plain(path):
    leaf=None
    for item in (path,*path.parents):
        info=item.lstat();need(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400)
        if leaf is None:leaf=info
    return leaf

def write_record(path,row):
    validate_record(row);raw=json.dumps(row,separators=(',',':'),allow_nan=False).encode('ascii')+b'\n'
    need(len(raw)<=MAX_BYTES);_plain(path.parent)
    with path.open('xb') as stream:stream.write(raw)

def read_record(path):
    def identity(info):return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns
    def pairs(items):
        result={}
        for key,value in items:need(key not in result);result[key]=value
        return result
    def reject(_):raise ValueError('Numeric receipt rejected')
    selected=_plain(path);need(stat.S_ISREG(selected.st_mode) and selected.st_nlink==1 and 0<selected.st_size<=MAX_BYTES)
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());need(identity(before)==identity(selected))
        raw=stream.read(MAX_BYTES+1);need(len(raw)==before.st_size and len(raw)<=MAX_BYTES and stream.read(1)==b'')
        after=os.fstat(stream.fileno());current=_plain(path)
        need(identity(selected)==identity(before)==identity(after)==identity(current))
    return validate_record(json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=reject))

class NumericEvidence:
    """Original close evidence API, with values discarded before serialization."""
    def __init__(self,evidence,record):self.original,self.path,self.record=evidence,evidence.path,record
    def write(self,name,value):
        # Names are fixed source stages; the potentially sensitive value is not encoded.
        need(type(name) is str and re.fullmatch('[a-z0-9-]{1,64}',name) is not None)
        self.original.write(name,{'schemaVersion':1,'diagnosticOnly':True,'acceptanceEligible':False})
        if name=='p23-close-result' and type(value) is dict:
            for source,target in [('messageDelivered','messageDelivered'),('surfaceDismissed','surfaceDismissed')]:
                if type(value.get(source)) is bool:self.record[target]=value[source]

class ProtocolEvidence(NumericEvidence):
    def write(self,name,value):
        host_keys=('sessionId','windowsDirectory','windowsVersion','imageOS','imageVersion','desktop','windowStation')
        if name=='10-controller':
            selected=dict(value);selected['host']={key:value['host'][key] for key in host_keys}
            self.original.write(name,selected)
        elif name=='31-observer-host':
            # Original PreparationSession.identity_source compares this exact self receipt.
            process_keys=('processId','createdFileTime','sessionId','processMachine','nativeMachine','exitCode','imagePath')
            need(type(value['process']) is dict and set(value['process'])==set(process_keys))
            selected={key:value[key] for key in (*host_keys,'processId')}
            selected['process']={key:value['process'][key] for key in process_keys}
            self.original.write(name,selected)
        elif name=='32-observer-context':
            self.original.write(name,value)
        elif name=='21-observer-bound':
            need(type(value) is dict)
            selected={key:value[key] for key in ('processId','createdFileTime','assignedBeforeResume',
                'processMachine','nativeMachine','sessionId','imageBytes','imageSha256','peMachine','sourceFiles') if key in value}
            need(type(selected.get('processId')) is int and selected['processId']>0
                and type(selected.get('createdFileTime')) is int and selected['createdFileTime']>0
                and selected.get('assignedBeforeResume') is True)
            self.original.write(name,selected)
        else:super().write(name,value)

def _numeric_foreground(core,probe,record):
    hwnd=int(probe.user.GetForegroundWindow() or 0);need(hwnd>0)
    root=int(probe.user.GetAncestor(hwnd,2) or 0);need(root>0)
    pid=core.W.DWORD();tid=int(probe.user.GetWindowThreadProcessId(root,ctypes.byref(pid)))
    need(tid>0 and pid.value>0 and bool(probe.user.IsWindow(root)))
    name=probe.text_value(root,True)  # Class only; never WindowText/Name.
    code=5 if name==CORE_CLASS else 0
    record.update(foregroundHwnd=hwnd,foregroundRootHwnd=root,foregroundPid=int(pid.value),
                  foregroundTid=tid,foregroundClassCode=code,coreWindowObserved=code==5)
    return hwnd,root,int(pid.value),tid,code

def observe_candidate(core,probe,budget,evidence,record,*,expected=None,source_check=None):
    record['stageCode']=2;budget.remaining(16)
    numeric=_numeric_foreground(core,probe,record)
    hwnd,root,pid,tid,code=numeric
    if code!=5:
        need(expected is None);record['observationStatusCode']=1
        return None
    need(hwnd==root)
    if expected is not None:
        need(root==expected['hwnd'] and pid==expected['window']['processId'] and tid==expected['window']['threadId'])
    handle=probe.kernel.OpenProcess(0x1000,False,pid);need(handle)
    primary=None
    try:
        record['stageCode']=3;process=probe.process_identity(handle,pid)
        need(type(process.get('createdFileTime')) is int and process['createdFileTime']>0
            and process['sessionId']==probe.session_id() and process['processMachine']==0
            and process['nativeMachine']==0xAA64 and process['exitCode']==259
            and ntpath.normcase(process['imagePath'])==ntpath.normcase(ntpath.join(probe.windows_directory(),'System32','WWAHost.exe')))
        if expected is not None:
            need(all(process[k]==expected['process'][k] for k in ('processId','createdFileTime','sessionId','processMachine','nativeMachine','imagePath')))
        record['processVerified']=True;record['stageCode']=4
        process.update(core.image_receipt(process['imagePath'],budget))
        need(process['imageBytes']>0 and re.fullmatch('[0-9a-f]{64}',process['imageSha256']) is not None)
        record['stageCode']=5;signatures=core.signatures([process['imagePath']],budget)
        need(type(signatures) is list and len(signatures)==1);signature=signatures[0]
        need(type(signature) is dict and signature['status']=='Valid' and signature['publisherMicrosoft'] is True
            and re.search(r'(?:^|,\s*)CN=Microsoft Windows(?:,|$)',signature['subject'])
            and re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)',signature['subject']))
        process['signature']=signature;record['signatureVerified']=True
        if expected is not None:need(process==expected['process'])
        def recheck():
            current=probe.startup_process_state(handle,pid)
            need(all(current[k]==process[k] for k in ('createdFileTime','sessionId','processMachine','nativeMachine','exitCode')))
            value=core.W.DWORD();thread=int(probe.user.GetWindowThreadProcessId(root,ctypes.byref(value)))
            need(int(probe.user.GetForegroundWindow() or 0)==root and int(probe.user.GetAncestor(root,2) or 0)==root
                and int(value.value)==pid and thread==tid and bool(probe.user.IsWindow(root)))
        recheck();budget.remaining(16)
        record['stageCode']=6
        if source_check is not None:source_check()
        budget.remaining(16)
        prefix='os-initial-target' if expected is None else 'os-refreshed-target'
        with core.physical_queries(probe,evidence,prefix):
            budget.remaining(16);recheck()
            record['titleReadAttempted']=True;target=probe.target(root)
            need(target['hwnd']==root and target['processId']==pid and target['threadId']==tid
                and target['rootHwnd']==root and target['className']==CORE_CLASS and target['visible'] is True and target['enabled'] is True)
            if expected is not None:need({k:target[k] for k in core.privacy_preparation_module().WINDOW_FIELDS}==expected['window'])
        # Preserve the original helper's boundary: initialize COM/UIA after PMv2 restore.
        budget.remaining(16);recheck();record['stageCode']=7;record['uiaAttempted']=True;tree=probe.strict_uia(root)
        need(type(tree) is dict and 'error' not in tree)
        core.validate_diagnostic_uia(tree,root)
        window={k:target[k] for k in core.privacy_preparation_module().WINDOW_FIELDS}
        observed={'foreground':window,'processes':[process],'uia':[tree]}
        candidate=core.legacy.privacy_candidate(observed,probe.session_id(),probe.windows_directory())
        with core.physical_queries(probe,evidence,prefix+'-recheck'):
            budget.remaining(16);recheck();need(probe.target(root)==target);recheck()
            if source_check is not None:source_check()
            budget.remaining(16);recheck()
        record['privacyValidated']=True
        if expected is not None:evidence.write('p18-fresh-recheck',None)
        return candidate
    except BaseException as error:
        primary=error;raise
    finally:
        released=bool(probe.kernel.CloseHandle(handle));record['queryHandlesReleased']=released
        if not released and primary is None:raise ValueError('Query handle release failed')

def close_candidate(core,privacy,session,candidate,record):
    need(session.close_requests==0 and candidate.get('kind')=='WWAHost.exe' and candidate.get('operation')=='WM_CLOSE')
    class SelectedAdapter(privacy.PrivacyAdapter):
        def current(self,hwnd):
            need(hwnd==self.candidate['hwnd'])
            value=observe_candidate(core,self.probe,self.budget,self.out,record,
                expected=self.candidate,source_check=self.session.identity_source)
            need(value is not None)
            return {'foreground':value['window'],'processes':[value['process']],'uia':[value['uia']]}
    adapter=SelectedAdapter(session,candidate);record['stageCode']=8
    try:
        session.budget.remaining(16)
        result=core.legacy.WindowsProbe.close_verified(adapter,candidate)
        record.update(messageDelivered=result['messageDelivered'],surfaceDismissed=result['surfaceDismissed'])
        need(result['messageRequests']==session.close_requests==1 and result['messageDelivered']
            and result['surfaceDismissed'] and not result['ownershipChangedAfterSend']
            and result['postSendErrorType'] is None and result['afterHandleReleaseState']
            and result['afterHandleReleaseState']['surfaceDismissed'] and not adapter.cleanup_failures)
        record['queryHandlesReleased']=True;record['observationStatusCode']=2
    finally:
        record['closeRequests']=session.close_requests
        if adapter.cleanup_failures:record['queryHandlesReleased']=False

def _failure(error):
    return 2 if isinstance(error,TimeoutError) else 3 if isinstance(error,OSError) else 1 if isinstance(error,ValueError) else 4

def run_observer(core,guard,env,event,root,output,deadline,*,platform):
    budget=core.Budget(deadline=deadline);row=empty_record();row['recordKindCode']=2
    session=None
    try:
        row['stageCode']=1;row.update(admit(guard,root,env,event,platform=platform,budget=budget));budget.remaining(16)
        binding=control_binding(core,guard)
        original=core.Evidence(output,max_files=core.PREPARE_MAX_FILES);evidence=ProtocolEvidence(original,row)
        controller,_=core.legacy.bounded_object(output/'10-controller.json')
        probe=core.Probe();identity=probe.identity();core.same_host(controller['host'],identity)
        bound,_=core.legacy.bounded_object(output/'21-observer-bound.json')
        need(identity['processId']==bound['processId'] and identity['process']['createdFileTime']==bound['createdFileTime']
            and bound['assignedBeforeResume'] is True)
        source=core.bound_source(budget,binding)
        actual_event,digest=core.legacy.bounded_object(env['GITHUB_EVENT_PATH'])
        need(actual_event==event and digest==controller['eventSha256'] and source['files']==controller['sourceFiles'])
        context=core.validate_context(env,event,source,identity,platform,prepare_privacy=True,binding=binding)
        evidence.write('31-observer-host',identity)
        evidence.write('32-observer-context',{**context,'source':source,'eventSha256':digest})
        row.update(observerPid=identity['processId'],observerBirth=identity['process']['createdFileTime'])
        privacy=core.privacy_preparation_module();numeric=NumericEvidence(original,row)
        session=privacy.PreparationSession(core,probe,numeric,budget,controller,{},
            source_receipt=lambda current:core.bound_source(current,binding))
        candidate=observe_candidate(core,probe,budget,numeric,row,source_check=session.identity_source)
        if candidate is not None:close_candidate(core,privacy,session,candidate,row)
        budget.remaining(3);need(core.bound_hashes(binding)==controller['sourceFiles'])
        need(admit(guard,root,env,event,platform=platform,budget=budget)['sourceCommitWords']==row['sourceCommitWords'])
        budget.remaining(3);row['observationPassed']=True
    except BaseException as error:row['errorCode']=_failure(error)
    finally:
        if session is not None:row['closeRequests']=session.close_requests
        write_record(output/CHILD,row)
    return row

def run_controller(core,guard,env,event,root,*,deadline,platform):
    # Reject a different caller before any native process/probe can be created.
    need(platform=='nt' and env.get('GITHUB_JOB')==JOB and env.get('GITHUB_ACTIONS')=='true')
    budget=core.Budget(deadline=deadline);row=empty_record();row['stageCode']=1
    row.update(admit(guard,root,env,event,platform=platform,budget=budget));budget.remaining(16)
    binding=control_binding(core,guard)
    temporary=Path(env['RUNNER_TEMP']);output=temporary/('writer-os-privacy-'+str(row['runId'])+'-1')
    original=core.Evidence.create(output,temporary,max_files=core.PREPARE_MAX_FILES);evidence=ProtocolEvidence(original,row)
    probe=core.Probe();host=probe.identity();source_files=core.bound_hashes(binding)
    context=core.validate_execution(env,event,host,platform,prepare_privacy=True,binding=binding)
    actual_event,digest=core.legacy.bounded_object(env['GITHUB_EVENT_PATH']);need(actual_event==event)
    executable=core.image_receipt(sys.executable,budget);need(executable['peMachine']==0xAA64)
    evidence.write('10-controller',{**context,'host':host,'sourceFiles':source_files,'executable':executable,
        'eventSha256':digest,'deadlineMonotonic':budget.deadline})
    entry=core.unaliased(root/ENTRY);need(entry.is_file() and entry.is_relative_to(root))
    argv=[sys.executable,'-B',str(entry),'--observer','--deadline',str(budget.deadline),'--output',str(output)]
    owned=core.OwnedObserver(probe,child_environment(core,env),argv,budget,
        {'sessionId':host['sessionId'],'executable':executable,'sourceFiles':source_files})
    try:result=core.run_owned(owned,budget,evidence,prepare_privacy=True)
    except BaseException as error:
        unknown=merge_observer(row,{},None,source_verified=None);unknown['errorCode']=_failure(error)
        return validate_record(unknown)
    child=None;verified=False
    try:child=read_record(output/CHILD)
    except (ValueError,OSError):pass
    try:
        budget.remaining();after=admit(guard,root,env,event,platform=platform,budget=budget)
        need(all(after[key]==row[key] for key in after) and core.bound_hashes(binding)==source_files)
        observed,_=core.legacy.bounded_object(output/'32-observer-context.json')
        core.validate_context(env,event,observed['source'],host,platform,prepare_privacy=True,binding=binding)
        need(observed['eventSha256']==digest and observed['source']['files']==source_files)
        budget.remaining(3);verified=True
    except Exception:pass
    return merge_observer(row,result,child,source_verified=verified)

def main(arguments=None):
    args=sys.argv[1:] if arguments is None else arguments
    if args==['validate']:
        try:read_record(ROOT/REPORT);return 0
        except BaseException:return 1
    if args==['prepare']:
        deadline=time.monotonic()+120;row=empty_record();row['stageCode']=1
        try:
            _plain(ROOT)
            need(os.name=='nt' and os.environ.get('GITHUB_JOB')==JOB)
            guard=load_guard(ROOT);core=load_core(ROOT)
            event=guard._json(os.environ.get('GITHUB_EVENT_PATH'),1048576)
            row=run_controller(core,guard,os.environ,event,ROOT,deadline=deadline,platform=os.name)
        except BaseException as error:row['errorCode']=_failure(error)
        try:
            # Keep the unchanged source clean check before all generated checkout output.
            public=(ROOT/REPORT).parent
            if not public.parent.exists():public.parent.mkdir()
            _plain(public.parent);public.mkdir()
            write_record(ROOT/REPORT,row)
        except BaseException:return 1
        return 0 if row['preparationPassed'] else 1
    if len(args)==5 and args[0]=='--observer' and args[1]=='--deadline' and args[3]=='--output':
        try:
            deadline=float(args[2]);need(math.isfinite(deadline))
            need(os.name=='nt' and os.environ.get('GITHUB_JOB')==JOB)
            guard=load_guard(ROOT);core=load_core(ROOT);output=Path(args[4])
            event=guard._json(os.environ.get('GITHUB_EVENT_PATH'),1048576)
            budget=core.Budget(deadline=deadline)
            admitted=admit(guard,ROOT,os.environ,event,platform=os.name,budget=budget)
            expected=Path(os.environ['RUNNER_TEMP'])/('writer-os-privacy-'+str(admitted['runId'])+'-1')
            need(output==expected)
            row=run_observer(core,guard,os.environ,event,ROOT,output,deadline,platform=os.name)
            return 0 if row['observationPassed'] and row['errorCode']==0 else 1
        except BaseException:return 1
    return 1

if __name__=='__main__':raise SystemExit(main())
