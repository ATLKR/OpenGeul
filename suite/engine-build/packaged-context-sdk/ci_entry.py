"""Pinned source-only CI envelope. No package/application/servicing entry point."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import types
import uuid

REF='refs/heads/work/opengeul-office-package-context-sdk'
KEYS=('GITHUB_ACTIONS','GITHUB_REPOSITORY','GITHUB_REPOSITORY_ID','GITHUB_REPOSITORY_OWNER',
 'GITHUB_ACTOR','GITHUB_ACTOR_ID','GITHUB_TRIGGERING_ACTOR','GITHUB_EVENT_NAME','GITHUB_REF',
 'GITHUB_RUN_ATTEMPT','GITHUB_RUN_ID','GITHUB_SHA','GITHUB_WORKFLOW_SHA','GITHUB_WORKFLOW_REF',
 'GITHUB_JOB','SDK_REPOSITORY_PRIVATE','SDK_REPOSITORY_FORK','SDK_MATRIX_RUNNER','RUNNER_OS','RUNNER_ARCH')

class CiFailure(RuntimeError):
    def __init__(self,code=1):self.code=int(code);super().__init__('sdk_ci_rejected')
    def __repr__(self):return '<CiFailure>'

def failure_observation(error,stage):
    """Closed codes only; never error text, arguments, filename or environment."""
    if type(stage) is not int or not 0<=stage<=13:raise CiFailure(1)
    root=Path(__file__).absolute().parent
    candidates=(('supervisor','GateFailure',2),('owned_job_win32','NativeCallError',3),('approved_launch','ApprovalFailure',4))
    kind=1 if type(error) is CiFailure else 5 if isinstance(error,OSError) else 0
    if kind==0:
        for module_name,class_name,code in candidates:
            module=sys.modules.get(module_name)
            if type(module) is not types.ModuleType:continue
            values=module.__dict__
            if values.get('__file__')==str(root/(module_name+'.py')) and values.get(class_name) is type(error):kind=code;break
    def integer(value,low=0,high=65535):return value if type(value) is int and low<=value<=high else None
    value={'stageCode':stage,'exceptionKnown':kind!=0,'exceptionTypeCode':kind,'nativeCode':None,
      'errno':None,'winerror':None,'filesystemCode':None,'fileRoleCode':None,'observedLinkCount':None,
      'sourceFrames':[],'sourceLocationKnown':False,'sourceFramesTruncated':False}
    if kind in (1,2,3,4):value['nativeCode']=integer(getattr(error,'code',None))
    if kind==3:
        module=sys.modules.get('owned_job_win32');code=getattr(error,'code',None)
        if type(module) is types.ModuleType and type(code) is module.__dict__.get('FailureCode'):value['nativeCode']=int(code)
    if kind==2:
        value['filesystemCode']=integer(getattr(error,'filesystem_code',None),1,5)
        value['fileRoleCode']=integer(getattr(error,'file_role_code',None),1,3)
        value['observedLinkCount']=integer(getattr(error,'observed_link_count',None),0,1048576)
    if kind==5:
        value['errno']=integer(error.errno,-2147483648,4294967295)
        value['winerror']=integer(getattr(error,'winerror',None),-2147483648,4294967295)
    names=('ci_entry.py','toolchain.py','supervisor.py','owned_job_win32.py','approved_launch.py','run_sdk_gate.py')
    paths={os.path.normcase(str(root/name)):index for index,name in enumerate(names,1)}
    tb=error.__traceback__;frames=[]
    while tb is not None:
        code=paths.get(os.path.normcase(tb.tb_frame.f_code.co_filename))
        if code is not None and type(tb.tb_lineno) is int and 0<tb.tb_lineno<=100000:frames.append({'fileCode':code,'line':tb.tb_lineno})
        tb=tb.tb_next
    value['sourceLocationKnown']=bool(frames);value['sourceFramesTruncated']=len(frames)>8;value['sourceFrames']=frames[-8:]
    return value

def require_context(env,architecture):
    if type(env) is not dict or set(env)!=set(KEYS) or architecture not in ('x64','arm64'):raise CiFailure(1)
    exact={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_ID':'1405493151',
      'GITHUB_REPOSITORY_OWNER':'ATLKR','GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341','GITHUB_TRIGGERING_ACTOR':'ATLKR',
      'GITHUB_EVENT_NAME':'push','GITHUB_REF':REF,'GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'packaged-context-sdk',
      'SDK_REPOSITORY_PRIVATE':'false','SDK_REPOSITORY_FORK':'false','RUNNER_OS':'Windows',
      'RUNNER_ARCH':'X64' if architecture=='x64' else 'ARM64',
      'SDK_MATRIX_RUNNER':'windows-2025' if architecture=='x64' else 'windows-11-arm',
      'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/office-suite.yml@'+REF}
    if any(env.get(k)!=v for k,v in exact.items()):raise CiFailure(1)
    head=env.get('GITHUB_SHA');run=env.get('GITHUB_RUN_ID')
    if type(head) is not str or not re.fullmatch('[0-9a-f]{40}',head) or env.get('GITHUB_WORKFLOW_SHA')!=head or type(run) is not str or not re.fullmatch('[1-9][0-9]{0,18}',run):raise CiFailure(1)
    return {'repositoryId':1405493151,'runId':int(run),'runAttempt':1,'sourceCommit':head,
      'architectureCode':0x8664 if architecture=='x64' else 0xaa64,'runnerCode':1 if architecture=='x64' else 2}

def _regular(path,directory=False):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise CiFailure(2)
    for q in (p,*p.parents):
        s=q.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise CiFailure(2)
    s=p.stat()
    if directory:
        if not stat.S_ISDIR(s.st_mode):raise CiFailure(2)
    elif not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise CiFailure(2)
    return p

def _read(path,limit):
    p=_regular(path);a=p.stat()
    if not 0<a.st_size<=limit:raise CiFailure(2)
    with p.open('rb') as f:b=f.read(limit+1);z=os.fstat(f.fileno())
    c=_regular(p).stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink)
    if len(b)>limit or identity(a)!=identity(z) or identity(z)!=identity(c):raise CiFailure(2)
    return b

def check_checkout(repo,binding):
    repo=_regular(repo,True)
    if _read(repo/'.git/HEAD',128)!=(binding['sourceCommit']+'\n').encode('ascii'):raise CiFailure(2)
    return True

class EnvelopeRunner:
    def __new__(cls,*args,**kwargs):
        # Exact existing private-Job state machine, a fixed enclosing role only.
        # Compiler phases instantiate the unchanged30-second base Runner.
        from supervisor import Runner
        class Envelope(Runner):
            MAX_SECONDS=180
            MAX_ARGUMENTS=24
        return Envelope(*args,**kwargs)

def create_public_directory(repo,runner):
    if runner not in ('windows-2025','windows-11-arm'):raise CiFailure(2)
    p=Path(repo)/'.work/packaged-context-sdk-public'/runner
    if p.exists() or p.is_symlink():raise CiFailure(2)
    p.parent.mkdir(parents=True,exist_ok=True);_regular(p.parent,True);p.mkdir()
    return p

def _integer(value,maximum=0x7fffffffffffffff):return type(value) is int and 0<=value<=maximum
def _sha(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def _number(value):return type(value) in (int,float) and math.isfinite(value)

def validate_helper_failure_observation(value,stage):
    """Validate the existing pure observer packet; never interpret exception text."""
    if value is None:return None
    keys={'stageCode','exceptionKnown','exceptionTypeCode','nativeCode','errno','winerror','filesystemCode',
      'fileRoleCode','observedLinkCount','sourceFrames','sourceLocationKnown','sourceFramesTruncated'}
    if type(value) is not dict or set(value)!=keys or type(stage) is not int or not 1<=stage<=7:raise CiFailure(4)
    if type(value['stageCode']) is not int or value['stageCode']!=stage:raise CiFailure(4)
    if type(value['exceptionKnown']) is not bool or not _integer(value['exceptionTypeCode'],5) or value['exceptionKnown']!=(value['exceptionTypeCode']!=0):raise CiFailure(4)
    for key,low,high in (('nativeCode',0,65535),('errno',-2147483648,4294967295),('winerror',-2147483648,4294967295),
      ('filesystemCode',1,5),('fileRoleCode',1,3),('observedLinkCount',0,1048576)):
        item=value[key]
        if item is not None and (type(item) is not int or not low<=item<=high):raise CiFailure(4)
    kind=value['exceptionTypeCode']
    if kind not in (1,2,3,4) and value['nativeCode'] is not None:raise CiFailure(4)
    if kind!=5 and any(value[key] is not None for key in ('errno','winerror')):raise CiFailure(4)
    if kind!=2 and any(value[key] is not None for key in ('filesystemCode','fileRoleCode','observedLinkCount')):raise CiFailure(4)
    frames=value['sourceFrames']
    if type(frames) is not list or len(frames)>8:raise CiFailure(4)
    for row in frames:
        if type(row) is not dict or set(row)!={'fileCode','line'} or type(row['fileCode']) is not int or not 1<=row['fileCode']<=6 or type(row['line']) is not int or not 1<=row['line']<=100000:raise CiFailure(4)
    if type(value['sourceLocationKnown']) is not bool or value['sourceLocationKnown']!=bool(frames) or type(value['sourceFramesTruncated']) is not bool:raise CiFailure(4)
    if value['sourceFramesTruncated'] and len(frames)!=8:raise CiFailure(4)
    return {**value,'sourceFrames':[dict(row) for row in frames]}

def validate_sdk_candidate_observation(value,stage=None):
    """Only a candidate's first blocked member is recorded; never an SDK inventory."""
    if value is None:return None
    if type(value) is not dict or set(value)!={'operations','failures','failureCount','truncated'}:raise CiFailure(4)
    operations=value['operations'];failures=value['failures'];count=value['failureCount']
    if type(operations) is not list or len(operations)>2 or type(failures) is not list or len(failures)>4 or not _integer(count,2147483647) or type(value['truncated']) is not bool:raise CiFailure(4)
    if len(failures)!=min(4,count) or value['truncated']!=(count>len(failures)):raise CiFailure(4)
    known={}
    for index,row in enumerate(operations,1):
        if type(row) is not dict or set(row)!={'operationCode','enumerationKnown','candidateCount'} or type(row['operationCode']) is not int or row['operationCode']!=index or type(row['enumerationKnown']) is not bool:raise CiFailure(4)
        if row['enumerationKnown']:
            if not _integer(row['candidateCount'],2147483647):raise CiFailure(4)
            known[index]=row['candidateCount']
        elif row['candidateCount'] is not None:raise CiFailure(4)
        if stage is not None and (type(stage) is not int or stage<(1 if index==1 else 6)):raise CiFailure(4)
    if count>sum(known.values()):raise CiFailure(4)
    output=[]
    for row in failures:
        if type(row) is not dict or set(row)!={'operationCode','version','memberSlot','reason'}:raise CiFailure(4)
        operation=row['operationCode'];version=row['version'];slot=row['memberSlot']
        if type(operation) is not int or operation not in known or known[operation]<1:raise CiFailure(4)
        if type(version) is not list or len(version)!=4 or any(type(v) is not int for v in version) or version[:2]!=[10,0] or not 0<=version[2]<=999999 or not 0<=version[3]<=99999:raise CiFailure(4)
        if slot is not None and (type(slot) is not int or not 1<=slot<=16):raise CiFailure(4)
        reason=validate_helper_failure_observation(row['reason'],1 if operation==1 else 6)
        if reason is None:raise CiFailure(4)
        output.append({'operationCode':operation,'version':list(version),'memberSlot':slot,'reason':reason})
    return {'operations':[dict(row) for row in operations],'failures':output,'failureCount':count,'truncated':value['truncated']}

def project_helper_phases(rows):
    """Returned records only. Unknown exit/identity sentinels become explicit null."""
    keys={'startedAt','deadline','finishedAt','completed','cleanupProved','forcedCleanup','rootExitObserved','jobEmptyObserved',
      'identityRechecked','exitCode','pid','creation','failureCode','cancelled','handlesClosed'}
    if type(rows) is not list or len(rows)>5:raise CiFailure(4)
    result=[]
    for row in rows:
        if type(row) is not dict or set(row)!=keys:raise CiFailure(4)
        for key in ('completed','cleanupProved','forcedCleanup','rootExitObserved','jobEmptyObserved','identityRechecked','cancelled'):
            if type(row[key]) is not bool:raise CiFailure(4)
        if any(not _number(row[key]) for key in ('startedAt','deadline','finishedAt')) or not row['startedAt']<row['deadline'] or row['deadline']-row['startedAt']>30.000001:raise CiFailure(4)
        if not _integer(row['exitCode'],0xffffffff) or not _integer(row['pid'],0xffffffff) or not _integer(row['creation']) or not _integer(row['failureCode'],31) or not _integer(row['handlesClosed'],4):raise CiFailure(4)
        if bool(row['pid'])!=bool(row['creation']):raise CiFailure(4)
        result.append({**row,'exitCode':row['exitCode'] if row['rootExitObserved'] else None,
          'pid':row['pid'] or None,'creation':row['creation'] or None})
    return result

def validate_phase_active_observations(rows,count):
    """Ordinal-joined pre-cleanup facts only; no compilation/exit authority."""
    keys={'firstRootExitCodeBeforeCleanup','lastRootWaitBeforeCleanup','lastJobMemberCountBeforeCleanup'}
    if type(count) is not int or not 0<=count<=5:raise CiFailure(4)
    if rows is None:return None
    if type(rows) is not list or len(rows)!=count:raise CiFailure(4)
    result=[]
    for row in rows:
        if row is None:result.append(None);continue
        if type(row) is not dict or set(row)!=keys:raise CiFailure(4)
        exit_code=row['firstRootExitCodeBeforeCleanup'];wait=row['lastRootWaitBeforeCleanup'];members=row['lastJobMemberCountBeforeCleanup']
        if exit_code is not None and (not _integer(exit_code,0xffffffff) or exit_code==259):raise CiFailure(4)
        if wait is not None and (type(wait) is not int or wait not in (0,258)):raise CiFailure(4)
        if members is not None and not _integer(members,128):raise CiFailure(4)
        if (exit_code is not None)!=(wait==0) or (members is not None and wait is None):raise CiFailure(4)
        result.append(dict(row))
    return result

def validate_sdk_report(value,architecture,manifest_sha,deadline,expected_inputs=None):
    from run_sdk_gate import empty_receipt
    from toolchain import validate_command_observation
    keys=set(empty_receipt())|{'architectureCode','controller','commandProcessor','vswhereSha256','compiler','linker',
      'compilerVersion','installationVersion','devcmdSha256','sdkVersion','sdkInputs','compileInputs','portObject',
      'smokeObject','executable','startedAt','deadline','finishedAt','approvedCodeManifestSha256','cancelled'}
    if type(value) is not dict or set(value)-keys or value.get('kind')!='packaged-context-sdk-negative-gate' or type(value.get('schemaVersion')) is not int or value['schemaVersion']!=2:raise CiFailure(4)
    if not _integer(value.get('stage'),7) or not _integer(value.get('failureCode'),31):raise CiFailure(4)
    validate_helper_failure_observation(value.get('failureObservation'),value['stage'])
    validate_sdk_candidate_observation(value.get('sdkCandidateObservation'),value['stage'])
    for key,item in empty_receipt().items():
        if type(item) is bool and type(value.get(key)) is not bool:raise CiFailure(4)
    false=('actualPackageObservation','qualification','canService','originalHelperHandleKnown','packagedHelperLauncherImplemented',
      'watchdogVerified','synchronousOsCallPreemptionVerified','osImplicitEffectsKnown','pure40TestsRerun','lease6TestsRerun')
    if any(value.get(k) is not False for k in false) or value.get('approvedCodeManifestSha256')!=manifest_sha:raise CiFailure(4)
    expected=0x8664 if architecture=='x64' else 0xaa64
    if 'cancelled' in value and type(value['cancelled']) is not bool:raise CiFailure(4)
    if 'architectureCode' in value and (type(value['architectureCode']) is not int or value['architectureCode']!=expected):raise CiFailure(4)
    for name in ('controller','commandProcessor','compiler','linker','portObject','smokeObject','executable'):
        if name in value:
            p=value[name]
            if type(p) is not dict or set(p)!={'machine','bytes','sha256'} or p['machine']!=expected or not _integer(p['bytes'],128*1024*1024) or p['bytes']==0 or not _sha(p['sha256']):raise CiFailure(4)
    for name in ('vswhereSha256','devcmdSha256'):
        if name in value and not _sha(value[name]):raise CiFailure(4)
    for name in ('compilerVersion','installationVersion','sdkVersion'):
        if name in value and (type(value[name]) is not str or not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,6}){1,3}',value[name])):raise CiFailure(4)
    for name,maximum in (('sdkInputs',16),('compileInputs',4)):
        if name in value:
            rows=value[name]
            if type(rows) is not list or len(rows)!=maximum:raise CiFailure(4)
            for index,row in enumerate(rows,1):
                if type(row) is not dict or set(row)!={'slot','bytes','sha256'} or type(row['slot']) is not int or row['slot']!=index or not _integer(row['bytes'],128*1024*1024) or row['bytes']==0 or not _sha(row['sha256']):raise CiFailure(4)
    if any(k in value and (not _number(value[k]) or value[k]>deadline) for k in ('startedAt','deadline','finishedAt')):raise CiFailure(4)
    rows=value.get('phaseResults')
    if type(rows) is not list or len(rows)>5:raise CiFailure(4)
    if 'phaseActiveObservations' not in value:raise CiFailure(4)
    validate_phase_active_observations(value['phaseActiveObservations'],len(rows))
    rowkeys={'startedAt','deadline','finishedAt','completed','cleanupProved','forcedCleanup','rootExitObserved','jobEmptyObserved',
      'identityRechecked','exitCode','pid','creation','failureCode','cancelled','handlesClosed'}
    for row in rows:
        if type(row) is not dict or set(row)!=rowkeys:raise CiFailure(4)
        for key in ('completed','cleanupProved','forcedCleanup','rootExitObserved','jobEmptyObserved','identityRechecked','cancelled'):
            if type(row[key]) is not bool:raise CiFailure(4)
        if any(not _number(row[k]) for k in ('startedAt','deadline','finishedAt')) or not row['startedAt']<row['deadline']<=deadline or row['deadline']-row['startedAt']>30.000001:raise CiFailure(4)
        if any(not _integer(row[k]) for k in ('exitCode','pid','creation','failureCode','handlesClosed')):raise CiFailure(4)
    if value['sdkGatePassed']:
        try:validate_command_observation(value.get('commandProcessorBinding'),require_closed=True)
        except BaseException:raise CiFailure(4) from None
        true=('actualWindowsExecuted','nativeSdkCompiled','nativeLinked','negativeSmokePassed','frozenV2Preserved','workRootCreated','codeApprovalVerified')
        if value['stage']!=7 or value['failureCode']!=0 or any(value[k] is not True for k in true) or len(rows)!=5 or value.get('architectureCode')!=expected:raise CiFailure(4)
        required={'controller','commandProcessor','compiler','linker','portObject','smokeObject','executable',
          'compilerVersion','installationVersion','sdkVersion','sdkInputs','compileInputs','vswhereSha256','devcmdSha256',
          'startedAt','deadline','finishedAt'}
        if not required<=set(value) or expected_inputs is None or value['compileInputs']!=expected_inputs or not value['startedAt']<=value['finishedAt']<=value['deadline']<=deadline:raise CiFailure(4)
        if len({(row['pid'],row['creation']) for row in rows})!=5:raise CiFailure(4)
        previous=value['startedAt']
        for row in rows:
            if any(not row[k] for k in ('completed','cleanupProved','rootExitObserved','jobEmptyObserved','identityRechecked')) or row['forcedCleanup'] or row['cancelled'] or row['exitCode'] or row['failureCode'] or row['handlesClosed']!=4 or not row['pid'] or not row['creation'] or row['startedAt']<previous or not row['startedAt']<=row['finishedAt']<=row['deadline']:raise CiFailure(4)
            previous=row['finishedAt']
    if value.get('commandProcessorBinding') is not None:
        try:validate_command_observation(value['commandProcessorBinding'])
        except BaseException:raise CiFailure(4) from None
    return value

def public_report(binding,outer,raw,*,failure=0,observation=None,command_binding=None):
    command_ok=False
    if command_binding is not None:
        from toolchain import validate_command_observation
        validate_command_observation(command_binding)
        try:validate_command_observation(command_binding,require_closed=True);command_ok=True
        except BaseException:command_ok=False
    helper_code=None;helper_phases=None;helper_observation=None;sdk_candidates=None;active_observations=None
    if raw is not None:
        helper_code=raw['failureCode']
        if not _integer(helper_code,31):raise CiFailure(4)
        helper_phases=project_helper_phases(raw['phaseResults'])
        if 'phaseActiveObservations' not in raw:raise CiFailure(4)
        active_observations=validate_phase_active_observations(raw['phaseActiveObservations'],len(helper_phases))
        helper_observation=validate_helper_failure_observation(raw.get('failureObservation'),raw['stage'])
        sdk_candidates=validate_sdk_candidate_observation(raw.get('sdkCandidateObservation'),raw['stage'])
    return {'schemaVersion':6,'kind':'packaged-context-sdk-ci','binding':binding,'failureCode':failure,'failureObservation':observation,
      'commandProcessorBinding':command_binding,
      'helperFailureCode':helper_code,'helperPhaseResults':helper_phases,'helperFailureObservation':helper_observation,
      'helperSdkCandidateObservation':sdk_candidates,
      'helperPreCleanup':active_observations,
      'sdkReportKnown':raw is not None,'sdkStage':None if raw is None else raw['stage'],
      'sdkGatePassed':bool(raw and outer and raw['sdkGatePassed'] and outer['completed'] and failure==0 and command_ok),
      'nativeSdkCompiled':None if raw is None else raw['nativeSdkCompiled'],
      'nativeLinked':None if raw is None else raw['nativeLinked'],'negativeSmokePassed':None if raw is None else raw['negativeSmokePassed'],
      'qualification':False,'canService':False,'actualPackageObservation':False,'osImplicitEffectsKnown':False,
      'watchdogVerified':False,'externalMonitorCandidateImplemented':True,
      'envelopeKnown':outer is not None,'envelopeCompleted':None if outer is None else outer['completed'],
      'envelopeCleanupProved':None if outer is None else outer['cleanupProved'],
      'envelopeForcedCleanup':None if outer is None else outer['forcedCleanup'],
      'envelopeExitCode':None if outer is None else outer['exitCode'],
      'approvedCodeManifestSha256':None if raw is None else raw['approvedCodeManifestSha256'],
      'compiledEvidence':None if raw is None else {k:raw.get(k) for k in ('portObject','smokeObject','executable','compiler','linker')}}

def _code(root,expected_bootstrap,expected_manifest):
    raw=_read(root/'approved_launch.py',1024*1024)
    if not _sha(expected_bootstrap) or hashlib.sha256(raw).hexdigest()!=expected_bootstrap:raise CiFailure(3)
    if 'approved_launch' in sys.modules:raise CiFailure(3)
    spec=importlib.util.spec_from_file_location('approved_launch',root/'approved_launch.py')
    module=importlib.util.module_from_spec(spec);sys.modules['approved_launch']=module;spec.loader.exec_module(module)
    context=module.admit_code(root,root/'approved-sdk-code.json',expected_manifest)
    sys.path.insert(0,str(root));return context

class Parser(argparse.ArgumentParser):
    def error(self,message):raise CiFailure(1)

def main(argv=None):
    start=time.monotonic();deadline=start+180.;outer=None;raw=None;binding=None;public=None;failure=0;stage=0;observation=None;command_lease=None
    try:
        stage=1
        if not sys.flags.isolated or not sys.dont_write_bytecode:raise CiFailure(1)
        p=Parser(add_help=False);p.add_argument('--architecture',choices=('x64','arm64'),required=True)
        p.add_argument('--expected-entry-sha256',required=True);p.add_argument('--expected-bootstrap-sha256',required=True)
        p.add_argument('--expected-approved-manifest-sha256',required=True);args=p.parse_args(argv)
        root=Path(__file__).absolute().parent;repo=root.parents[2];stage=2
        if not _sha(args.expected_entry_sha256) or hashlib.sha256(_read(Path(__file__).absolute(),1024*1024)).hexdigest()!=args.expected_entry_sha256:raise CiFailure(3)
        stage=3;env={name:os.environ.get(name) for name in KEYS};binding=require_context(env,args.architecture)
        if Path(os.environ.get('GITHUB_WORKSPACE',''))!=repo:raise CiFailure(2)
        check_checkout(repo,binding)
        stage=4;public=create_public_directory(repo,env['SDK_MATRIX_RUNNER'])
        stage=5;context=_code(root,args.expected_bootstrap_sha256,args.expected_approved_manifest_sha256)
        stage=6
        if sys.platform!='win32' or sys.version_info[:2]!=(3,12):raise CiFailure(11)
        import toolchain
        from owned_job_win32 import NativeApi
        from supervisor import child_environment
        stage=7;toolchain.verify_bundle(root/'frozen-v2')
        expected_inputs=[]
        for index,name in enumerate(('context_observer.hpp','context_observer_windows.cpp','sdk_smoke.hpp','windows_sdk_smoke.cpp'),1):
            b=toolchain.read(root/'frozen-v2'/name,1024*1024) if index<=2 else context.read_approved(name)
            expected_inputs.append({'slot':index,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
        stage=8;locations=toolchain.system_locations(args.architecture,deadline=deadline);command_lease=locations['commandLease']
        stage=9;temp=_regular(os.environ.get('RUNNER_TEMP',''),True)
        work=temp/('opengeul-sdk-gate-'+uuid.uuid4().hex)
        envelope=temp/('opengeul-sdk-envelope-'+uuid.uuid4().hex);envelope.mkdir()
        for name in ('temp','profile','appdata','local'):(envelope/name).mkdir()
        child_env=child_environment(locations['system'],locations['programFiles'],locations['programFilesX86'],str(envelope))
        command=[sys.executable,'-I','-B',str(root/'approved_launch.py'),'--approved-manifest',str(root/'approved-sdk-code.json'),
          '--expected-approved-manifest-sha256',args.expected_approved_manifest_sha256,'--diagnostic-sdk-only','--architecture',args.architecture,
          '--source-bundle',str(root/'frozen-v2'),'--work-root',str(work),'--output',str(work/'sdk-gate.numeric.json'),
          '--overall-start',repr(start),'--overall-deadline',repr(deadline)]
        remaining=deadline-time.monotonic()
        if remaining<=1:raise CiFailure(10)
        stage=10;command_lease.verify(deadline=deadline)
        outer=EnvelopeRunner(NativeApi()).run(command,str(repo),child_env,deadline)
        command_lease.verify(deadline=deadline)
        stage=11
        path=work/'sdk-gate.numeric.json'
        if path.exists():raw=validate_sdk_report(json.loads(_read(path,16384)),args.architecture,args.expected_approved_manifest_sha256,deadline,expected_inputs)
        stage=12;context.require_root(root);check_checkout(repo,binding)
        if not outer['completed'] or raw is None or not raw['sdkGatePassed']:raise CiFailure(5)
        stage=13
    except BaseException as error:
        failure=error.code if isinstance(error,CiFailure) else 31
        observation=failure_observation(error,stage)
    finally:
        if command_lease is not None and not command_lease.close():failure=31
        if time.monotonic()>deadline:failure=10
        if public is not None and public.is_dir():
            report=public_report(binding,outer,raw,failure=failure,observation=observation,
              command_binding=None if command_lease is None else command_lease.observation())
            encoded=json.dumps(report,sort_keys=True,separators=(',',':')).encode()+b'\n'
            if len(encoded)<=8192:
                try:
                    with (public/'report.numeric.json').open('xb') as stream:stream.write(encoded)
                except BaseException:failure=31
            else:failure=31
    return 0 if failure==0 else 1

if __name__=='__main__':raise SystemExit(main())
