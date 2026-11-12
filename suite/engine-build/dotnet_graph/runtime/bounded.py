"""Diagnostic-only finite private-job controller. Never emits commands or exceptions."""
from __future__ import annotations
import json
from pathlib import Path
import time

class ProbeFailure(RuntimeError):
    def __init__(self, code=1):
        self.code=int(code)
        super().__init__('dotnet_graph_failure')

ENV_KEYS=frozenset(('SystemRoot','WINDIR','PATH','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP',
 'DOTNET_CLI_HOME','DOTNET_CLI_TELEMETRY_OPTOUT','DOTNET_NOLOGO','DOTNET_SKIP_FIRST_TIME_EXPERIENCE',
 'DOTNET_MULTILEVEL_LOOKUP','DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_ADD_GLOBAL_TOOLS_TO_PATH','MSBUILDDISABLENODEREUSE','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH',
 'NUGET_SCRATCH','NUGET_PLUGIN_PATHS','NUGET_CREDENTIALPROVIDERS_PATH','NUGET_PLUGINS_CACHE_PATH'))

ENV_FALSE_KEYS=frozenset(('DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_ADD_GLOBAL_TOOLS_TO_PATH'))

def phase_deadline(now, overall, seconds=60):
    if type(seconds) not in (int,float) or not 0<seconds<=60 or not now<overall:raise ProbeFailure(2)
    end=min(overall,now+seconds)
    if end-now<=1:raise ProbeFailure(2)
    return end

def child_environment(root,system_root,dotnet_dir):
    root=Path(root)
    dirs={n:root/n for n in ('profile','appdata','local','temp','cli','packages','http','scratch','empty-plugins','plugin-cache')}
    for p in dirs.values():p.mkdir(parents=True,exist_ok=True)
    return {'SystemRoot':str(system_root),'WINDIR':str(system_root),
      'PATH':str(dotnet_dir)+';'+str(system_root)+r'\System32',
      'USERPROFILE':str(dirs['profile']),'APPDATA':str(dirs['appdata']),'LOCALAPPDATA':str(dirs['local']),
      'TEMP':str(dirs['temp']),'TMP':str(dirs['temp']),'DOTNET_CLI_HOME':str(dirs['cli']),
      'DOTNET_CLI_TELEMETRY_OPTOUT':'1','DOTNET_NOLOGO':'1','DOTNET_SKIP_FIRST_TIME_EXPERIENCE':'1',
      'DOTNET_MULTILEVEL_LOOKUP':'0','DOTNET_GENERATE_ASPNET_CERTIFICATE':'false',
      'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH':'false','MSBUILDDISABLENODEREUSE':'1',
      'NUGET_PACKAGES':str(dirs['packages']),'NUGET_HTTP_CACHE_PATH':str(dirs['http']),
      'NUGET_SCRATCH':str(dirs['scratch']),'NUGET_PLUGIN_PATHS':'',
      'NUGET_CREDENTIALPROVIDERS_PATH':'',
      'NUGET_PLUGINS_CACHE_PATH':str(dirs['plugin-cache'])}

def numeric_logger(value,phase):
    arrays={'projectStarted','projectFinished','cscStarted','cscFinished','cscSucceeded','targetPathSeen','targetPathMatched','targetPathForeign','targetPathUnknown'}
    scalar={'schemaVersion','phase','rootProjectCode','known','loggerFailed','overflow','buildStarted','buildFinished','buildSucceeded','copyLocalKnown','copyLocalSeen','errorCount','cs2012Count','otherErrorCount'}
    if type(value) is not dict or set(value)!=arrays|scalar:raise ProbeFailure(3)
    if any(type(value[k]) is not int or not 0<=value[k]<=65535 for k in scalar):raise ProbeFailure(3)
    if value['schemaVersion']!=1 or value['phase']!=phase or not 1<=value['rootProjectCode']<=6:raise ProbeFailure(3)
    if any(value[k] not in (0,1) for k in ('known','loggerFailed','overflow','buildSucceeded','copyLocalKnown')):raise ProbeFailure(3)
    for k in arrays:
        a=value[k]
        if type(a) is not list or len(a)!=7 or any(type(n) is not int or not 0<=n<=65535 for n in a):raise ProbeFailure(3)
    return value

def json_numeric(path,limit=16384):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or not 0<p.stat().st_size<=limit:raise ProbeFailure(3)
    with p.open('rb') as f:b=f.read(limit+1)
    if len(b)>limit:raise ProbeFailure(3)
    try:return json.loads(b)
    except BaseException:raise ProbeFailure(3) from None

class Runner:
    """One original deadline for all roots and descendants, including cleanup."""
    def __init__(self,api,*,clock=time.monotonic,pause=time.sleep):
        self.api=api;self.clock=clock;self.pause=pause
    def run(self,specs,deadline,*,bootstrap_capture=False):
        start=self.clock()
        if (not 1<deadline-start<=60 or not 1<=len(specs)<=2 or type(bootstrap_capture) is not bool
                or (bootstrap_capture and len(specs)!=1)):raise ProbeFailure(2)
        controller=None;owned=[];failed=False;forced=False;clean=True;rows=[]
        def native(name,*args,**kwargs):
            if self.clock()>=deadline:raise ProbeFailure(2)
            return getattr(self.api,name)(*args,**kwargs)
        result={'startedAt':start,'deadline':deadline,'completed':False,'cleanupProved':False,'forcedCleanup':False,'children':rows,'siblingOverlapObserved':False,'rootExitedWithLiveDescendantObserved':False}
        try:
            controller,identity=native('retain_current_controller')
            binding=(controller,identity,object())
            for argv,cwd,environment in specs:
                if type(environment) is not dict or set(environment)!=ENV_KEYS or any(type(v) is not str or '\0' in v for v in environment.values()) or any(environment[k]!='false' for k in ENV_FALSE_KEYS):raise ProbeFailure(4)
                if self.clock()>=deadline-1:raise ProbeFailure(2)
                launch=self.api.launch_captured if bootstrap_capture else self.api.launch
                job=launch(argv,str(cwd),environment,controller_binding=binding)
                owned.append(job)
                row={'pid':0,'creation':0,'exitCode':0,'exitObserved':False,'launchFailureCode':int(job.failure_code),'identityRechecked':False};rows.append(row)
                if job.identity:row.update(pid=job.identity[0],creation=job.identity[1])
                if job.failed or job.uncertain or not (job.pre_resume_verified and job.creation_job_membership and job.local_cleanup_complete):failed=True
            while not failed and self.clock()<deadline-1:
                done=True;active=0
                for job,row in zip(owned,rows):
                    if native('identity',job.host)!=job.identity:failed=True;break
                    row['identityRechecked']=True
                    if bootstrap_capture and not native('drain_capture',job,deadline-1,self.clock):failed=True;break
                    wait,code=native('state',job.host)
                    if wait==258 and not native('member',job.host,job.job):failed=True;break
                    if wait==0:row.update(exitCode=code,exitObserved=True)
                    elif wait!=258:failed=True;break
                    else:active+=1
                    pids=native('census',job.job)
                    if len(pids)>128:failed=True;break
                    if wait==0 and code==0 and self.clock()<deadline-1 and any(pid!=job.identity[0] for pid in pids):
                        result['rootExitedWithLiveDescendantObserved']=True
                    done=done and wait==0 and not pids
                if len(owned)==2 and active==2:result['siblingOverlapObserved']=True
                if done and not failed:
                    if bootstrap_capture and not all(native('drain_capture',job,deadline-1,self.clock,final=True) for job in owned):failed=True;break
                    result['completed']=True;break
                self.pause(min(.02,max(0.,deadline-1-self.clock())))
        except BaseException as error:
            failed=True
            retained=getattr(error,'retained_handle',None)
            if controller is None and retained is not None:controller=retained
        finally:
            for job,row in zip(owned,rows):
                try:
                    live=bool(job.job and native('census',job.job))
                    state=native('state',job.host) if job.host else (0,0)
                    if live or state[0]==258:
                        result['completed']=False;forced=True
                        if self.clock()>=deadline or not job.job or not native('terminate_job',job.job):clean=False
                    while self.clock()<deadline:
                        state=native('state',job.host) if job.host else (0,0)
                        live=bool(job.job and native('census',job.job))
                        if state[0]==0 and not live:
                            row.update(exitCode=state[1],exitObserved=bool(job.host));break
                        self.pause(min(.01,max(0.,deadline-self.clock())))
                    if self.clock()>=deadline:clean=False
                    else:
                        state=native('state',job.host) if job.host else (0,0)
                        if state[0]!=0 or (job.job and native('census',job.job)):clean=False
                except BaseException:clean=False
                if hasattr(self.api,'release_launch_local'):
                    try:
                        if self.clock()>=deadline or not self.api.release_launch_local(job):clean=False
                    except BaseException:clean=False
                if bootstrap_capture:
                    try:
                        if not self.api.close_capture(job):clean=False
                        from .bootstrap_errors import validate_capture
                        row['bootstrapErrorCodes']=validate_capture(self.api.capture_result(job))
                        if not row['bootstrapErrorCodes']['complete']:failed=True
                    except BaseException:clean=False;failed=True
                for name in ('thread','host','job'):
                    h=getattr(job,name,None)
                    if h:
                        try:
                            if not self.api.close(h):clean=False
                            else:setattr(job,name,None)
                        except BaseException:clean=False
            if controller:
                try:
                    if not self.api.close(controller):clean=False
                except BaseException:clean=False
            result.update(finishedAt=self.clock(),forcedCleanup=forced,cleanupProved=clean and self.clock()<=deadline)
            result['completed']=bool(result['completed'] and not failed and not forced and result['cleanupProved'])
        return result
