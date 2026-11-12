"""Finite SDK-only private-job supervisor; no environment or output capture."""
from __future__ import annotations
import math
import ntpath
import time

class GateFailure(RuntimeError):
    def __init__(self,code=2):
        self.code=int(code)
        super().__init__('sdk_gate_rejected')
    def __repr__(self):return '<GateFailure>'

ENV_KEYS=frozenset(('SystemRoot','WINDIR','SystemDrive','ComSpec','PATH','TEMP','TMP',
 'USERPROFILE','APPDATA','LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)','ProgramW6432',
 'VSCMD_SKIP_SENDTELEMETRY','RUNNER_TEMP'))

def win_path(value):
    if (type(value) is not str or len(value)>1024 or len(value)<3 or not value[0].isascii()
        or not value[0].isalpha() or value[1:3]!=':\\' or any(ord(c)<32 or ord(c)==127 or c in '%!&|<>^"/`' for c in value)
        or ':' in value[2:]):raise GateFailure(2)
    for part in value[3:].split('\\'):
        if not part or part in ('.','..') or part.endswith(('.', ' ')):raise GateFailure(2)
    return value

def child_environment(system_root,program_files,program_files_x86,owned_root):
    for value in (system_root,program_files,program_files_x86,owned_root):win_path(value)
    return {'SystemRoot':system_root,'WINDIR':system_root,'SystemDrive':system_root[:2],
      'ComSpec':system_root+r'\System32\cmd.exe','PATH':system_root+r'\System32',
      'TEMP':owned_root+r'\temp','TMP':owned_root+r'\temp','USERPROFILE':owned_root+r'\profile',
      'APPDATA':owned_root+r'\appdata','LOCALAPPDATA':owned_root+r'\local',
      'ProgramFiles':program_files,'ProgramFiles(x86)':program_files_x86,'ProgramW6432':program_files,
      'VSCMD_SKIP_SENDTELEMETRY':'1','RUNNER_TEMP':ntpath.dirname(owned_root)}

def environment_valid(value):
    return (type(value) is dict and set(value)==ENV_KEYS
      and all(type(v) is str and '\0' not in v and len(v)<=2048 for v in value.values())
      and value['VSCMD_SKIP_SENDTELEMETRY']=='1')

def phase_deadline(now,overall,seconds):
    if (type(now) not in (int,float) or type(overall) not in (int,float)
        or type(seconds) not in (int,float) or not all(math.isfinite(v) for v in (now,overall,seconds))
        or not 0<seconds<=30 or not now<overall or min(overall,now+seconds)-now<=1):raise GateFailure(2)
    return min(overall,now+seconds)

class Runner:
    """The absolute phase deadline includes a one-second cleanup reserve.

    Win32 operations have before/after checks; synchronous OS-call preemption is
    not claimed. Only private Job termination and retained handles are used.
    """
    MAX_SECONDS=30
    MAX_ARGUMENTS=16
    def __init__(self,api,*,clock=time.monotonic,pause=time.sleep):
        self.api=api;self.clock=clock;self.pause=pause
    def run(self,argv,cwd,environment,deadline,*,active_observation=None):
        start=self.clock();controller=None;job=None;failed=False;forced=False;clean=True
        r={'startedAt':start,'deadline':deadline,'finishedAt':start,'completed':False,
          'cleanupProved':False,'forcedCleanup':False,'rootExitObserved':False,'jobEmptyObserved':False,
          'identityRechecked':False,'exitCode':0,'pid':0,'creation':0,'failureCode':0,
          'cancelled':False,'handlesClosed':0}
        # Separate diagnostic facts, never a completion/input authority. No API or
        # clock reads are added. Exact plain dictionaries exclude writer callbacks.
        sink=active_observation if type(active_observation) is dict and not active_observation else None
        first_exit=None
        def observe(**values):
            if sink is not None:
                try:sink.update(values)
                except Exception:pass
        def call(name,*args,**kwargs):
            if self.clock()>=deadline-1:raise GateFailure(10)
            value=getattr(self.api,name)(*args,**kwargs)
            if self.clock()>=deadline-1:raise GateFailure(10)
            return value
        try:
            observe(firstRootExitCodeBeforeCleanup=None,lastRootWaitBeforeCleanup=None,lastJobMemberCountBeforeCleanup=None)
            if not environment_valid(environment):raise GateFailure(4)
            if (type(argv) not in (list,tuple) or not argv or len(argv)>self.MAX_ARGUMENTS
                or any(type(a) is not str or '\0' in a or len(a)>4096 for a in argv)
                or not ntpath.isabs(argv[0]) or type(cwd) is not str or not ntpath.isabs(cwd)
                or type(deadline) not in (float,int) or not math.isfinite(deadline)
                or not 1<deadline-start<=self.MAX_SECONDS):raise GateFailure(2)
            # Retain even if the post-call clock check fails.
            controller,identity=self.api.retain_current_controller()
            if self.clock()>=deadline-1:raise GateFailure(10)
            binding=(controller,identity,object())
            job=self.api.launch(argv,cwd,environment,controller_binding=binding)
            if job.identity:r['pid'],r['creation']=job.identity
            if (self.clock()>=deadline-1 or job.failed or job.uncertain or not job.identity
                or not job.pre_resume_verified or not job.creation_job_membership
                or not job.local_cleanup_complete):raise GateFailure(5)
            while self.clock()<deadline-1:
                if call('identity',job.host)!=job.identity:raise GateFailure(6)
                r['identityRechecked']=True
                state,code=call('state',job.host)
                if state not in (0,258) or (state==0 and code==259):raise GateFailure(7)
                if type(state) is int and type(code) is int and 0<=code<=0xffffffff:
                    observe(lastRootWaitBeforeCleanup=state)
                    if state==0 and first_exit is None:
                        first_exit=code;observe(firstRootExitCodeBeforeCleanup=code)
                if state==258 and not call('member',job.host,job.job):raise GateFailure(6)
                pids=call('census',job.job)
                if type(pids) is not tuple or len(pids)>128 or any(type(p) is not int or not 0<p<=0xffffffff for p in pids) or len(set(pids))!=len(pids):raise GateFailure(7)
                observe(lastJobMemberCountBeforeCleanup=len(pids))
                if state==0:r.update(rootExitObserved=True,exitCode=code)
                if state==0 and not pids:
                    r['jobEmptyObserved']=True
                    if code!=0:raise GateFailure(8)
                    r['completed']=True;break
                self.pause(min(.01,max(0.,deadline-1-self.clock())))
            if not r['completed']:raise GateFailure(10)
        except BaseException as error:
            failed=True;r['failureCode']=error.code if isinstance(error,GateFailure) else 31
            r['cancelled']=isinstance(error,(KeyboardInterrupt,SystemExit))
            if controller is None:controller=getattr(error,'retained_handle',None)
        finally:
            if job is not None:
                state=None;pids=None
                try:
                    state=self.api.state(job.host) if job.host else (0,0)
                    pids=self.api.census(job.job) if job.job else ()
                except BaseException:clean=False
                if state is None or pids is None or state[0]!=0 or pids:
                    r['completed']=False;forced=True
                    try:
                        if self.clock()>=deadline or not job.job or not self.api.terminate_job(job.job):clean=False
                    except BaseException:clean=False
                proved=False
                while self.clock()<deadline:
                    try:
                        state=self.api.state(job.host) if job.host else (0,0)
                        pids=self.api.census(job.job) if job.job else ()
                        if state[0]==0 and state[1]!=259 and not pids:
                            r.update(rootExitObserved=bool(job.host),jobEmptyObserved=True,exitCode=state[1]);proved=True;break
                    except BaseException:break
                    self.pause(min(.01,max(0.,deadline-self.clock())))
                if not proved:clean=False
                try:
                    if not self.api.release_launch_local(job):clean=False
                except BaseException:clean=False
                for name in ('thread','host','job'):
                    handle=getattr(job,name,None)
                    if handle:
                        try:
                            if self.api.close(handle):setattr(job,name,None);r['handlesClosed']+=1
                            else:clean=False
                        except BaseException:clean=False
            if controller:
                try:
                    if self.api.close(controller):r['handlesClosed']+=1
                    else:clean=False
                except BaseException:clean=False
            r['finishedAt']=self.clock();r['forcedCleanup']=forced
            r['cleanupProved']=clean and self.clock()<=deadline
            r['completed']=bool(r['completed'] and not failed and not forced and r['cleanupProved'])
        return r
