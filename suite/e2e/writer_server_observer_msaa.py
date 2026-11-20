"""Original-QPC watchdog for one creation-owned numeric MSAA helper.

No communicate(), blocking process wait, thread join, PID cleanup reopen or COM
call executes in this parent. This does not prove native calls are preemptible.
"""
from dataclasses import dataclass
from enum import IntEnum
import json
import os
from pathlib import Path
import stat
import time

from writer_server_observer_lifecycle import WatchdogProof,DiagnosticFailure,FailureCode
from writer_server_observer_win32 import OwnedLaunch
from writer_server_observer_capture import Descriptor
import writer_server_observer_msaa_helper as helper


class Code(IntEnum):
    PREPARE=1
    LAUNCH=2
    IDENTITY=3
    CUTOFF=4
    DEADLINE=5
    RESULT=6
    CLEANUP=7
    OWNERSHIP=8
    STATE=9


class WatchdogError(RuntimeError):
    def __init__(self,code):
        self.code=Code(code)
        super().__init__('Writer MSAA watchdog failure code '+str(int(self.code)))


def need(value,code):
    if not value:raise WatchdogError(code)


@dataclass(frozen=True,slots=True,repr=False)
class HostRuntime:
    host_python:Path
    helper_script:Path
    windows:Path
    temp:Path
    office_program:Path
    def __repr__(self):return '<HostRuntime private>'
    @classmethod
    def validated(cls,host_python,helper_script,windows,temp,office_program):
        try:
            paths=tuple(Path(v) for v in (host_python,helper_script,windows,temp,office_program))
            need(all(p.is_absolute() and not p.is_symlink() and p.resolve(strict=True)==p for p in paths),Code.PREPARE)
            python,script,windows,temp,office=paths
            need(python.is_file() and script.is_file() and all(p.is_dir() for p in (windows,temp,office,windows/'System32')),Code.PREPARE)
            need(all((script.parent/name).is_file() and not (script.parent/name).is_symlink()
                and (script.parent/name).resolve(strict=True)==script.parent/name
                for name in ('writer_os_accessibility.py','writer_os_summary.py','startup_smoke.py','windows_smoke.py')),Code.PREPARE)
            guard=script.parent.parent/'payload.py'
            need(guard.is_file() and not guard.is_symlink() and guard.resolve(strict=True)==guard,Code.PREPARE)
            need(not python.is_relative_to(office),Code.PREPARE)
            return cls(python,script,windows,temp,office)
        except Exception:raise WatchdogError(Code.PREPARE) from None


def build_host_environment(read_value,runtime,descriptor):
    try:
        need(type(runtime) is HostRuntime and type(descriptor) is Descriptor,Code.PREPARE)
        values={}
        for name in ('SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA'):
            value=read_value(name)
            need(type(value) is str and value and '\0' not in value and ';' not in value,Code.PREPARE)
            path=Path(value)
            need(path.is_absolute() and path.is_dir() and not path.is_symlink(),Code.PREPARE)
            values[name]=path.resolve(strict=True)
        need(values['SystemRoot']==values['WINDIR']==runtime.windows,Code.PREPARE)
        need(all(values[name].is_relative_to(values['USERPROFILE']) for name in ('APPDATA','LOCALAPPDATA')),Code.PREPARE)
        result={name:str(values[name]) for name in ('SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA')}
        result['TEMP']=result['TMP']=str(runtime.temp)
        result['PATH']=';'.join(map(str,(runtime.host_python.parent,runtime.windows/'System32',runtime.windows)))
        result['OPENGEUL_WRITER_SERVER_OBSERVER']=descriptor.environment_value()
        return result
    except Exception:raise WatchdogError(Code.PREPARE) from None


def decode_result(data,request):
    try:
        need(type(data) is bytes and 0<len(data)<=4096 and b'\0' not in data,Code.RESULT)
        return helper.validate_public(json.loads(data.decode('utf-8'),object_pairs_hook=helper.unique),request)
    except Exception:raise WatchdogError(Code.RESULT) from None


@dataclass(frozen=True,slots=True,repr=False)
class HelperWitness:
    handle:int
    pid:int
    birth:int
    def __repr__(self):return '<HelperWitness private>'


@dataclass(frozen=True,slots=True,repr=False)
class PendingHelperLease:
    kind_code:int
    handle:object
    original_witness:object
    expected_identity:object
    _owner:object
    def __repr__(self):return '<PendingHelperLease private>'


class PreparedMsaaHelper:
    def __init__(self,runtime,api,controller_binding,descriptor,owner_request,read_value,result_root):
        self._runtime,self._api,self._controller_binding,self._descriptor=runtime,api,controller_binding,descriptor
        self._request,self._read_value,self._root=owner_request,read_value,Path(result_root)
        self._prepared=self._attempted=False
        self._environment=self._result=self._owned=self._original=None
        self._observation=None;self._errors=[];self._cleanup_errors=[]
        self._termination_requested=False;self._termination_returned=None
        self._exit_observed=False;self._exit_qpc=None;self._identity_matches=None
        self._exit_code=None;self._closed=False;self._budget_values=None
        self._retained_host_handle=self._retained_host_identity=None
        self._pending=[];self._cleanup_complete=False

    def __repr__(self):return '<PreparedMsaaHelper private>'

    def _error(self,code):
        if int(code) not in self._errors:self._errors.append(int(code))

    def prepare(self):
        need(not self._prepared and self._result is None and not self._closed,Code.STATE)
        try:
            need(type(self._runtime) is HostRuntime and type(self._descriptor) is Descriptor,Code.PREPARE)
            helper.raw._request(self._request)
            self._request={key:self._request[key] for key in ('officePid','officeCreationTime','childHwnd','expectedImage')}
            binding=self._controller_binding
            need(type(binding) is tuple and len(binding)==3 and type(binding[0]) is int and binding[0]>0
                and binding[1]==(self._descriptor.controller_pid,self._descriptor.controller_birth)
                and binding[2]==self._descriptor.nonce,Code.PREPARE)
            need(self._root.is_absolute() and self._root.parent.is_dir()
                and self._root.parent.resolve(strict=True)==self._root.parent,Code.PREPARE)
            self._root.mkdir(exist_ok=False)
            self._result=self._root/'numeric-result.json'
            self._environment=build_host_environment(self._read_value,self._runtime,self._descriptor)
            self._prepared=True
            return self
        except Exception:raise WatchdogError(Code.PREPARE) from None

    def _check(self,budget,observation):
        values=(budget.start_qpc,budget.cutoff_qpc,budget.deadline_qpc,budget.frequency)
        if self._budget_values is None:self._budget_values=values
        need(values==self._budget_values and all(type(x) is int for x in values)
            and 0<values[0]<values[1]<values[2] and values[3]>0
            and values[2]-values[0]<=30*values[3] and values[1]==values[2]-5*values[3],Code.DEADLINE)
        value=budget.check(observation=observation)
        need(type(value) is int and values[0]<=value<(values[1] if observation else values[2]),Code.CUTOFF if observation else Code.DEADLINE)
        return value

    def _native_exit(self,budget,*,observation):
        self._check(budget,observation)
        need(self._original is not None,Code.IDENTITY)
        identity=self._api.identity(self._original.handle)
        self._identity_matches=identity==(self._original.pid,self._original.birth)
        need(self._identity_matches,Code.IDENTITY)
        state=self._api.state(self._original.handle)
        need(type(state) is tuple and len(state)==2 and all(type(v) is int for v in state)
            and state[0] in (0,258) and 0<=state[1]<=0xffffffff,Code.IDENTITY)
        now=self._check(budget,observation)
        if state[0]==0:
            self._exit_observed=True;self._exit_code=state[1];self._exit_qpc=now
            return True
        need(self._api.member(self._original.handle,self._owned.job) is True,Code.OWNERSHIP)
        return False

    def _terminate(self):
        if self._termination_requested or self._owned is None or not self._owned.job:return
        self._termination_requested=True
        try:self._termination_returned=self._api.terminate_job(self._owned.job) is True
        except Exception:self._termination_returned=False
        if not self._termination_returned:self._error(Code.CLEANUP)

    def _read_result(self):
        descriptor=None
        try:
            path=self._result
            info=path.lstat()
            need(stat.S_ISREG(info.st_mode) and not path.is_symlink() and path.resolve(strict=True)==path
                and 0<info.st_size<=4096,Code.RESULT)
            descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0))
            actual=os.fstat(descriptor)
            need((info.st_dev,info.st_ino,info.st_size)==(actual.st_dev,actual.st_ino,actual.st_size),Code.RESULT)
            data=os.read(descriptor,4097)
            need(len(data)==info.st_size,Code.RESULT)
            return decode_result(data,self._request)
        finally:
            if descriptor is not None:
                try:os.close(descriptor)
                except BaseException:
                    self._cleanup_errors.append(5)
                    self._pending.append(PendingHelperLease(5,descriptor,None,None,self))

    def invoke_original(self,budget,*,pause=time.sleep):
        need(self._prepared and not self._attempted and not self._closed,Code.STATE)
        self._attempted=True
        completed=timed_out=partial=False
        try:
            self._check(budget,True)
            private_json=json.dumps(self._request,separators=(',',':'),ensure_ascii=True)
            argv=[str(self._runtime.host_python),'-E','-s',str(self._runtime.helper_script),
                '--result',str(self._result),'--owner-json',private_json]
            self._owned=self._api.launch(argv,str(self._runtime.helper_script.parent),self._environment,
                controller_binding=self._controller_binding)
            owned=self._owned
            if type(owned) is OwnedLaunch and type(owned.host) is int and owned.host>0:
                self._retained_host_handle=owned.host
                self._retained_host_identity=owned.identity
            need(type(owned) is OwnedLaunch and type(owned.host) is int and owned.host>0
                and type(owned.job) is int and owned.job>0,Code.LAUNCH)
            identity=self._api.identity(owned.host)
            self._identity_matches=(type(identity) is tuple and len(identity)==2 and identity==owned.identity
                and all(type(v) is int and v>0 for v in identity))
            need(self._identity_matches,Code.IDENTITY)
            need(owned.creation_job_membership is True,Code.OWNERSHIP)
            # Keep the original creation-retained host even if resume or another
            # later launch phase failed; it still owns cleanup exit authority.
            self._original=HelperWitness(owned.host,*identity)
            need(not owned.failed and not owned.uncertain and owned.resumed is True
                and owned.creation_job_membership is True and owned.pre_resume_verified is True
                and owned.local_cleanup_complete is True,Code.LAUNCH)
            while not self._native_exit(budget,observation=True):
                pause(min(.005,budget.remaining_ms(observation=True)/1000))
            need(self._exit_code==0,Code.RESULT)
            census=self._api.census(owned.job)
            need(type(census) is tuple and not census,Code.OWNERSHIP)
            decoded=self._read_result();self._check(budget,True)
            self._observation=decoded['observation']
            completed=True
        except BaseException as exc:
            partial=True
            try:
                now=budget.check(observation=False)
                timed_out=now>=budget.cutoff_qpc
            except DiagnosticFailure as clock_error:
                timed_out=clock_error.code==FailureCode.LATE
            except BaseException:
                timed_out=False
            self._error(exc.code if isinstance(exc,WatchdogError) else Code.CUTOFF if timed_out else Code.RESULT)
            if self._owned is not None:
                self._terminate()
                # Only the original retained helper HANDLE can prove its exit.
                # A failed/partial launch has no admitted witness; no PID reopen.
                while self._original is not None and not self._exit_observed:
                    try:
                        if self._native_exit(budget,observation=False):break
                        pause(min(.005,budget.remaining_ms(observation=False)/1000))
                    except BaseException:
                        self._error(Code.DEADLINE);break
        finally:
            self.close_local()
        if not self._cleanup_complete:partial=True;completed=False
        if self._errors:completed=False
        return WatchdogProof(budget=budget,cutoff_qpc=budget.cutoff_qpc,
            original_helper=self._original,exit_helper=self._original if self._exit_observed else None,
            helper_identity_matches=self._identity_matches is True,helper_exit_observed=self._exit_observed,
            helper_exit_qpc=self._exit_qpc,completed=completed,timed_out=timed_out,partial=partial)

    def close_local(self):
        if self._closed:return
        self._closed=True
        owned=self._owned
        if owned is None:
            self._cleanup_complete=True
            return
        try:
            launch_local_ok=self._api.release_launch_local(owned) is True
        except BaseException:launch_local_ok=False
        if not launch_local_ok:
            self._cleanup_errors.append(4)
            self._pending.append(PendingHelperLease(4,None,None,None,self))
        for code,name in ((1,'thread'),(2,'host'),(3,'job')):
            handle=self._retained_host_handle if name=='host' else getattr(owned,name,None)
            if handle is None:continue
            if name=='host' and not (self._exit_observed and self._identity_matches is True
                and self._original is not None and self._original.handle==handle):
                # Keep the original process HANDLE and creation identity reachable.
                # KILL_ON_CLOSE, a deadline, or a PID lookup cannot replace it.
                self._pending.append(PendingHelperLease(code,handle,self._original,self._retained_host_identity,self))
                continue
            try:okay=self._api.close(handle) is True
            except BaseException:okay=False
            if not okay:
                self._cleanup_errors.append(code)
                self._pending.append(PendingHelperLease(code,handle,
                    self._original if name=='host' else None,
                    self._retained_host_identity if name=='host' else None,self))
            else:setattr(owned,name,None)
        self._cleanup_complete=(not self._pending and not self._cleanup_errors
            and not (owned.uncertain and not self._exit_observed))

    def pending_leases(self):
        """Private retained resources only. No query, retry, new budget or reopen.

        The caller must hold these leases and stop before another case while
        any remain. A lease anchors this owner/API/creation evidence in memory.
        """
        return tuple(self._pending)

    def numeric_result(self):
        observation=None
        if self._observation is not None:
            observation=helper.public_shape({'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,
                'bodyReturned':1,'observation':self._observation})['observation']
        return {'schemaVersion':1,'msaaVerified':bool(observation['verified']) if observation is not None else None,
            'observation':observation,'helperIdentityMatches':self._identity_matches,
            'helperExitObserved':self._exit_observed,'helperExitQpc':self._exit_qpc,
            'helperExitCode':self._exit_code,'terminationRequested':self._termination_requested,
            'terminationReturned':self._termination_returned,'errors':list(self._errors),
            'cleanupErrors':list(self._cleanup_errors),'normalAcceptance':0,'fullEngineQualified':0,
            'pendingRetainedCount':len(self._pending),'cleanupComplete':self._cleanup_complete,
            'acceptanceEligible':False,'hardDeadlineEnforcementVerified':False,
            'parentCleanupPidReopens':0,'childOriginalReadOnlyAdmissionPathReused':True,
            'childOwnerAdmissionVerified':bool(observation['ownerBefore']) if observation is not None else None}
