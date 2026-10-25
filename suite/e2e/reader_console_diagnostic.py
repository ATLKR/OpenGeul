"""One authorized packaged-reader console observation; never Office acceptance."""
import argparse
import ctypes
from ctypes import wintypes as W
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import time


def remaining(deadline,clock=time.monotonic):
    value=deadline-clock()
    if value<=0:raise TimeoutError('Original console diagnostic deadline expired')
    return value


def validate_handshake(row,started,deadline):
    assert type(row) is dict and set(row)=={'pid','tid','consoleHwnd','creationTime','observedAt','identityVerified'}
    for key in ('pid','tid','consoleHwnd','creationTime'):
        assert type(row[key]) is int and row[key]>=(0 if key=='consoleHwnd' else 1)
    assert type(row['observedAt']) in (int,float) and math.isfinite(row['observedAt'])
    assert started<=row['observedAt']<deadline and row['identityVerified'] is True


def observe_owned_console(api,hwnd,members,clock,deadline):
    remaining(deadline,clock)
    if not hwnd:return dict(hwnd=0,observedAt=clock(),associated=False)
    pid,tid=api.owner(hwnd)
    assert pid in members and tid>0, 'Console is not an admitted live Job member'
    generation=members[pid]['creationTime'];assert type(generation) is int and generation>0
    remaining(deadline,clock)
    visible=api.visible(hwnd)
    remaining(deadline,clock)
    assert api.owner(hwnd)==(pid,tid),'Console owner changed during observation'
    remaining(deadline,clock)
    return dict(hwnd=hwnd,pid=pid,tid=tid,creationTime=generation,visible=visible,observedAt=clock(),associated=True)


def execute(driver,*,clock=time.monotonic):
    started=clock();deadline=started+30;work_deadline=deadline-5
    report=dict(schemaVersion=1,acceptanceEligible=False,causalLinkProved=False,success=False,
        startedAt=started,deadline=deadline,workDeadline=work_deadline,foreground=[])
    launched=released=retired=False
    def foreground(phase):
        remaining(work_deadline,clock);hwnd=driver.foreground();remaining(work_deadline,clock)
        report['foreground'].append(dict(phase=phase,hwnd=hwnd,observedAt=clock()))
    try:
        foreground(0);remaining(work_deadline,clock)
        launched=True  # Constructor may partially create a Job before raising.
        driver.launch(deadline)
        handshake=driver.handshake(work_deadline);validate_handshake(handshake,started,work_deadline)
        assert handshake['observedAt']<=clock()
        report['handshake']=handshake;foreground(1)
        report['console']=driver.console(handshake,work_deadline)
        released=True;driver.release()
        retired=driver.retire(work_deadline);assert retired
        foreground(2)
        report['success']=True
    except Exception as exc:report['errorType']=type(exc).__name__
    finally:
        if launched and not retired:
            try:
                if not released:released=True;driver.release()
                remaining(work_deadline,clock)
                retired=driver.retire(work_deadline)
            except Exception:pass
            if not retired:
                report['forced']=True
                try:driver.terminate(deadline)
                except Exception as exc:report['cleanupErrorType']=type(exc).__name__
        if retired and not any(row['phase']==2 for row in report['foreground']):
            try:foreground(2)
            except Exception as exc:report['cleanupErrorType']=type(exc).__name__
        try:driver.close()
        except Exception as exc:report['cleanupErrorType']=type(exc).__name__
        report['finishedAt']=clock();report['retirementVerified']=retired
        if report.get('forced') or report.get('cleanupErrorType') or report['finishedAt']>=deadline:report['success']=False
    return report


class WindowsMetadata:
    def __init__(self):
        from writer_model_reader import _worker_native
        native=_worker_native();self.user=ctypes.WinDLL('user32',use_last_error=True);self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.foreground=native.bind(self.user,'GetForegroundWindow',[],W.HWND)
        self.console=native.bind(self.kernel,'GetConsoleWindow',[],W.HWND)
        self.visible=native.bind(self.user,'IsWindowVisible',[W.HWND],W.BOOL)
        self.thread=native.bind(self.user,'GetWindowThreadProcessId',[W.HWND,ctypes.POINTER(W.DWORD)],W.DWORD)
        self.pid=native.bind(self.kernel,'GetCurrentProcessId',[],W.DWORD)
        self.tid=native.bind(self.kernel,'GetCurrentThreadId',[],W.DWORD)
    def owner(self,hwnd):
        pid=W.DWORD();tid=int(self.thread(hwnd,ctypes.byref(pid)));return int(pid.value),tid


def read_small(path):
    assert path.is_file() and not path.is_symlink()
    with path.open('rb') as stream:raw=stream.read(4097)
    assert len(raw)<=4096
    return json.loads(raw)


def helper(directory):
    from writer_model_reader import _atomic_json
    from writer_style_smoke import observe_packaged_python,require_packaged_python
    directory=Path(directory);config=read_small(directory/'configuration.json');deadline=config['workDeadline']
    remaining(deadline)
    require_packaged_python(Path(config['suite']),observe_packaged_python())
    remaining(deadline);api=WindowsMetadata()
    from writer_model_reader import _worker_native
    generation=_worker_native().ProcessDiagnosticsApi().identity(ctypes.c_void_p(-1).value)['creationTime']
    remaining(deadline)
    # GetConsoleWindow establishes association. Only the controller may query
    # visibility, after joining the console owner to retained private-Job handles.
    row=dict(pid=int(api.pid()),tid=int(api.tid()),consoleHwnd=int(api.console() or 0),
        creationTime=generation,observedAt=time.monotonic(),identityVerified=True)
    remaining(deadline);_atomic_json(directory/'handshake.json',row)
    while not (directory/'release').is_file():time.sleep(min(.01,remaining(deadline)))
    remaining(deadline)
    return 0


class NativeDriver:
    def __init__(self,suite,directory):
        preflight=time.monotonic()+30
        from writer_model_reader import _worker_native,_SystemConsoleHost
        from writer_style_smoke import _packaged_identity_file
        self.suite=suite;self.directory=directory;self.process=self.witnesses=None;self.launched=False
        self.native=_worker_native();self.api=WindowsMetadata();self.console_file=None
        try:
            remaining(preflight)
            _,raw=_packaged_identity_file(suite,'suite-inventory.json');inventory=json.loads(raw)
            assert inventory['architecture']=='arm64'
            cores=[name for name in inventory['files'] if re.fullmatch(r'Office/program/python-core-\d+\.\d+\.\d+/bin/python\.exe',name)]
            assert len(cores)==1
            self.images={}
            for role,relative in ((1,'Office/program/python.exe'),(2,cores[0])):
                remaining(preflight);actual,_=_packaged_identity_file(suite,relative)
                assert {k:actual[k] for k in ('size','sha256')}==inventory['files'][relative]
                self.images[os.path.normcase(str(suite/relative))]=role
            self.console_file=_SystemConsoleHost(preflight,time.monotonic)
            self.images[os.path.normcase(self.console_file.witness['path'])]=3
            remaining(preflight);directory.mkdir(parents=True,exist_ok=False)
        except BaseException:
            self.close();raise
    def foreground(self):return int(self.api.foreground() or 0)
    def launch(self,deadline):
        from writer_model_reader import _launch_owned,_require_launch,_atomic_json
        assert not self.launched;self.launched=True;self.deadline=deadline
        self.started=deadline-30
        _atomic_json(self.directory/'configuration.json',dict(suite=str(self.suite),workDeadline=deadline-5))
        argv=[str(self.suite/'Office/program/python.exe'),str(Path(__file__).with_name('writer_model_reader.py')),'--console-probe',str(self.directory)]
        self.process,launch=_launch_owned(self.native,argv,self.suite/'Office/program')
        self.witnesses=self.process.open_diagnostic_witnesses()
        _require_launch(launch,int(self.process.job))
        remaining(deadline-5)
    def members(self,deadline,*,alive=True):
        remaining(deadline);rows=self.witnesses.retained_snapshot();remaining(deadline)
        assert 1<=len(rows)<=3
        result={};roles=[]
        for row in rows:
            role=self.images.get(os.path.normcase(row['image']));assert role is not None
            roles.append(role)
            handle,identity=self.witnesses.members[row['pid']]
            # The same retained handle must still attest the original generation.
            current=self.witnesses.api.identity(handle);remaining(deadline)
            assert current['creationTime']==identity['creationTime'] and current['image']==identity['image']
            assert row['alive'] is alive and row['waitResult']==(258 if alive else 0)
            if not alive:assert row['exitCode']==0
            result[row['pid']]=dict(creationTime=row['creationTime'],role=role)
        assert len(roles)==len(set(roles)) and 1 in roles
        self.console_file.recheck();remaining(deadline)
        return result
    def handshake(self,deadline):
        path=self.directory/'handshake.json'
        while True:
            members=self.members(deadline)
            if path.exists():
                row=read_small(path);validate_handshake(row,self.started,deadline)
                assert row['pid'] in members and members[row['pid']]['role']==2
                assert row['creationTime']==members[row['pid']]['creationTime']
                self.helper_generation=row['creationTime'];self.helper_pid=row['pid']
                return row
            assert self.process.poll() is None
            time.sleep(min(.01,remaining(deadline)))
    def console(self,row,deadline):
        members=self.members(deadline)
        assert members[self.helper_pid]['creationTime']==self.helper_generation
        # Only the admitted console-host generation may own the associated HWND.
        consoles={pid:r for pid,r in members.items() if r['role']==3}
        result=observe_owned_console(self.api,row['consoleHwnd'],consoles,time.monotonic,deadline)
        after=self.members(deadline);assert after==members
        return result
    def release(self):
        with (self.directory/'release').open('x'):pass
    def retire(self,deadline):
        if not self.process:return True
        while True:
            remaining(deadline)
            rows=self.witnesses.retained_snapshot();remaining(deadline)
            pids=self.witnesses.api.job_pids(self.process.job);remaining(deadline)
            if not pids and rows and all(r['waitResult']==0 for r in rows):
                self.members(deadline,alive=False)
                return self.process.poll()==0
            time.sleep(min(.01,remaining(deadline)))
    def terminate(self,deadline):
        if not self.process:return
        remaining(deadline);self.process.terminate()
        while self.witnesses.api.job_pids(self.process.job):time.sleep(min(.01,remaining(deadline)))
        remaining(deadline)
    def close(self):
        errors=[]
        for resource in (self.witnesses,self.process,self.console_file):
            if resource:
                try:
                    closure=resource.close()
                    if resource is self.console_file:assert closure.get('result') is True, 'Console file HANDLE closure failed'
                except Exception as exc:errors.append(exc)
        if errors:raise errors[0]


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--suite',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv);assert os.name=='nt' and __debug__
    spec=importlib.util.spec_from_file_location('console_ci_admission',Path(__file__).resolve().parents[2]/'e2e/native31_suite_prepare.py')
    admission=importlib.util.module_from_spec(spec);spec.loader.exec_module(admission)
    binding=admission.validate_context(os.environ,admission.read_event(),'arm64',os.name)
    report=dict(schemaVersion=1,success=False,acceptanceEligible=False,causalLinkProved=False,runBinding=binding)
    try:
        from ascii_message_preparation import _absolute
        args.suite=_absolute(args.suite.absolute());args.output=_absolute(args.output.absolute())
        driver=NativeDriver(args.suite,args.output/'private')
        report.update(execute(driver))
    except Exception as exc:report['errorType']=type(exc).__name__
    finally:
        args.output.mkdir(parents=True,exist_ok=True)
        with (args.output/'receipt.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2,allow_nan=False)
    return 0 if report['success'] else 1

if __name__=='__main__':raise SystemExit(main())
