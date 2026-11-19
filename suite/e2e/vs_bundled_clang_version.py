"""One read-only tool query inside the caller's original owned diagnostic Job.

Only fixed numeric fields leave RAM. Discovery may return one validated VS path
to the private coordinator file; raw process output is never written or printed.
"""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
# capture-observation:begin imports
import types
# capture-observation:end imports

VERSION_CAP, STDERR_CAP = 4096, 4096
RESULT_KEYS = {'schemaVersion','kindCode','resultCode','exitCode','major','minor','selectedRoot',
               'stdoutBytes','stderrBytes','timedOut','outputCapReached','pid','creationTime',
               'imageMatched','naturalExit','handlesClosed'}
# capture-observation:begin schema
RESULT_KEYS=RESULT_KEYS|{'captureObservation','discoveryParseStage'}
# capture-observation:end schema

def parse_version(raw,kind):
    assert type(raw) is bytes and len(raw) <= VERSION_CAP and b'\0' not in raw
    assert type(kind) is int and kind in (1,2)
    line = raw.split(b'\n',1)[0].rstrip(b'\r')
    prefix = rb'(?:clang|clang-cl) version ' if kind == 1 else rb'LLD '
    match = re.fullmatch(prefix+rb'([0-9]{1,3})\.([0-9]{1,3})(?:\.[0-9]{1,3})?(?:[ \t]+[^\r\n]{0,1024})?',line)
    assert match is not None, 'Unrecognized fixed version prefix'
    major,minor = map(int,match.group(1,2))
    assert 0 < major <= 999 and 0 <= minor <= 999
    return major,minor

def _identity(process,api=None):
    assert os.name == 'nt' or api is not None, 'Windows-only process witness'
    if api is None:
        worker = str(Path(__file__).resolve().parents[1]/'worker')
        sys.path.insert(0,worker)
        try:
            from native_windows import ProcessDiagnosticsApi
        finally:
            sys.path.remove(worker)
        api=ProcessDiagnosticsApi()
    value = api.identity(int(process._handle))
    assert type(process.pid) is int and process.pid>0
    assert type(value['creationTime']) is int and 0 < value['creationTime'] <= 0xffffffffffffffff
    return dict(value,pid=process.pid)

# capture-observation:begin helpers
def capture_observation():
    return dict(observedMask=0,phaseCode=0,exceptionKindCode=0,winerror=0,errno=0,
                sourceFileCode=0,sourceLine=0)


def validate_capture_observation(value):
    assert type(value) is dict and set(value)=={'observedMask','phaseCode','exceptionKindCode',
        'winerror','errno','sourceFileCode','sourceLine'}
    for key,low,high in (('observedMask',0,31),('phaseCode',0,8),('exceptionKindCode',0,6),
            ('winerror',0,0xffffffff),('errno',-0x80000000,0x7fffffff),
            ('sourceFileCode',0,2),('sourceLine',0,65535)):
        assert type(value[key]) is int and low<=value[key]<=high
    mask=value['observedMask']
    assert bool(mask&1)==(value['phaseCode']>0)
    assert bool(mask&2)==(value['exceptionKindCode']>0)
    assert not mask&30 or mask&1
    assert not mask&28 or mask&2
    assert mask&4 or value['winerror']==0
    assert mask&8 or value['errno']==0
    if mask&16:assert value['sourceFileCode']>0 and value['sourceLine']>0
    else:assert value['sourceFileCode']==value['sourceLine']==0


_CAPTURE_SOURCE_FILES=(os.path.normcase(str(Path(__file__))),
    os.path.normcase(str(Path(__file__).parent.parent/'worker/native_windows.py')))


def _capture_exception_numbers(error):
    value=capture_observation()
    actual=type(error)
    kind=(1 if issubclass(actual,AssertionError) else 2 if issubclass(actual,OSError)
        else 3 if issubclass(actual,ValueError) else 4 if issubclass(actual,TypeError)
        else 5 if issubclass(actual,Exception) else 6)
    value.update(observedMask=2,exceptionKindCode=kind)
    if issubclass(actual,OSError):
        for name,bit,low,high in (('winerror',4,0,0xffffffff),('errno',8,-0x80000000,0x7fffffff)):
            member=OSError.__dict__.get(name)
            if (type(member) is not types.MemberDescriptorType or member.__objclass__ is not OSError
                    or member.__name__!=name):continue
            try:number=member.__get__(error,OSError)
            except BaseException:continue
            if type(number) is int and low<=number<=high:
                value[name]=number;value['observedMask']|=bit
    try:
        cursor=BaseException.__traceback__.__get__(error);source=(0,0)
        for _ in range(16):
            if cursor is None:break
            if type(cursor) is not types.TracebackType:raise TypeError()
            filename=cursor.tb_frame.f_code.co_filename;line=cursor.tb_lineno
            if type(filename) is str and type(line) is int and 0<line<=65535:
                normalized=os.path.normcase(filename)
                if normalized in _CAPTURE_SOURCE_FILES:source=(_CAPTURE_SOURCE_FILES.index(normalized)+1,line)
            cursor=cursor.tb_next
        if cursor is None and source[0]:
            value.update(sourceFileCode=source[0],sourceLine=source[1]);value['observedMask']|=16
    except BaseException:pass
    return value


def _capture_observe(result,phase,error=None):
    # Same-thread, fixed cached facts only. Unknown observation cannot replace
    # the original return/exception or add an OS call, clock read or cleanup.
    try:
        if result['captureObservation']['observedMask']&2:return
        value=_capture_exception_numbers(error) if error is not None else capture_observation()
        value.update(phaseCode=phase,observedMask=value['observedMask']|1)
        validate_capture_observation(value)
        result['captureObservation']=value
    except BaseException:pass


# capture-observation:end helpers
# suspended-witness:begin launcher
def _suspended_ops():
    assert os.name=='nt' and sys.version_info[:2]==(3,12), 'CPython 3.12 Windows launcher required'
    import _winapi
    import ctypes
    from ctypes import wintypes
    import io
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    native_resume=kernel.ResumeThread
    native_resume.argtypes=(wintypes.HANDLE,)
    native_resume.restype=wintypes.DWORD
    def resume(thread):
        previous=native_resume(thread)
        if previous==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
        return previous
    def duplicate(handle):
        current=_winapi.GetCurrentProcess()
        return _winapi.DuplicateHandle(current,handle,current,0,True,_winapi.DUPLICATE_SAME_ACCESS)
    # None inherits the already finite helper environment; no mapping is read.
    return types.SimpleNamespace(pipe=lambda:_winapi.CreatePipe(None,0),duplicate=duplicate,
        open_nul=lambda:os.open(os.devnull,os.O_RDONLY|os.O_BINARY),fd_handle=msvcrt.get_osfhandle,
        close_fd=os.close,read_fd=lambda handle:msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY),
        fileio=lambda fd:io.FileIO(fd,'rb',closefd=False),startupinfo=subprocess.STARTUPINFO,
        create=_winapi.CreateProcess,close=_winapi.CloseHandle,wait=_winapi.WaitForSingleObject,
        exit_code=_winapi.GetExitCodeProcess,terminate=_winapi.TerminateProcess,resume=resume)


class _SuspendedProcess:
    """One original process/thread pair; CRT read FDs remain owned here."""
    def __init__(self,argv,*,stdin,stdout,stderr,bufsize,creationflags,close_fds,ops=None):
        assert type(argv) is list and 0<len(argv)<=16
        assert all(type(v) is str and 0<len(v)<=4096 and '\0' not in v for v in argv)
        assert Path(argv[0]).is_absolute()
        assert stdin==subprocess.DEVNULL and stdout==stderr==subprocess.PIPE
        assert type(bufsize) is int and bufsize==0 and type(creationflags) is int and creationflags==0 and close_fds is True
        self._ops=_suspended_ops() if ops is None else ops
        self._raw=[];self._fds=[];self._streams=[];self._process_handle=None;self._thread_handle=None
        self._close_started=False;self._close_error=None;self._resume_attempted=False
        self._termination_attempted=False;self._retirement_wait_attempted=False
        self._handle=self;self.returncode=None
        try:
            nul=self._ops.open_nul();self._fds.append(nul)
            child_in=self._ops.duplicate(self._ops.fd_handle(nul));self._own_handles(child_in)
            self._fds.remove(nul);self._ops.close_fd(nul)
            readers=[];children=[child_in]
            for _ in range(2):
                reader,writer=self._ops.pipe();self._own_handles(reader,writer)
                child=self._ops.duplicate(writer);self._own_handles(child);children.append(child)
                self._raw.remove(writer);self._ops.close(writer)
                fd=self._ops.read_fd(reader);self._raw.remove(reader);self._fds.append(fd)
                stream=self._ops.fileio(fd);self._streams.append(stream);readers.append(stream)
            self.stdout,self.stderr=readers
            assert len(set(children))==3
            startup=self._ops.startupinfo(dwFlags=0x100,hStdInput=children[0],hStdOutput=children[1],hStdError=children[2],
                lpAttributeList={'handle_list':list(children)})
            # CREATE_SUSPENDED only. The current private Job is inherited; no breakaway.
            hp,ht,pid,tid=self._ops.create(argv[0],subprocess.list2cmdline(argv),None,None,True,4,None,None,startup)
            self._process_handle,self._thread_handle=hp,ht;self._own_handles(hp,ht)
            assert all(type(v) is int and v>0 for v in (hp,ht,pid,tid)) and hp!=ht
            self.pid=pid
            for child in children:
                self._raw.remove(child);self._ops.close(child)
        except BaseException:
            if self._process_handle is not None:
                self._termination_attempted=True
                try:self._ops.terminate(self._process_handle,1)
                except BaseException:pass
                self._retirement_wait_attempted=True
                try:assert self._ops.wait(self._process_handle,1000)==0
                except BaseException:pass
            try:self.Close()
            except BaseException:pass
            raise

    def _own_handles(self,*handles):
        previous=set(self._raw)
        valid=all(type(handle) is int and handle>0 for handle in handles)
        for handle in handles:
            if type(handle) is int and handle>0 and handle not in self._raw:self._raw.append(handle)
        assert valid and len(set(handles))==len(handles) and not previous.intersection(handles)

    def __int__(self):
        assert not self._close_started and self._process_handle is not None
        return self._process_handle

    def resume_original(self):
        assert not self._resume_attempted and not self._close_started
        self._resume_attempted=True
        previous=self._ops.resume(self._thread_handle)
        assert type(previous) is int and previous==1, 'Original thread suspend count differs'

    def poll(self):
        if self.returncode is None:
            waited=self._ops.wait(int(self),0)
            assert type(waited) is int and waited in (0,258)
            if waited==0:self.returncode=self._ops.exit_code(int(self))
        return self.returncode

    def wait(self,timeout):
        assert type(timeout) in (int,float) and math.isfinite(timeout) and 0<=timeout<=1.
        if self._termination_attempted:self._retirement_wait_attempted=True
        if self.returncode is None:
            waited=self._ops.wait(int(self),int(timeout*1000))
            if waited==258:raise subprocess.TimeoutExpired('native-query',timeout)
            assert type(waited) is int and waited==0
            self.returncode=self._ops.exit_code(int(self))
        return self.returncode

    def kill(self):
        self._termination_attempted=True
        try:self._ops.terminate(int(self),1)
        except PermissionError:
            result=self._ops.exit_code(int(self))
            if result==259:raise
            self.returncode=result

    def Close(self):
        if self._close_started:
            if self._close_error is not None:raise self._close_error
            return
        self._close_started=True;errors=[]
        if self._process_handle is not None and self.returncode is None:
            if not self._termination_attempted:
                self._termination_attempted=True
                try:self._ops.terminate(self._process_handle,1)
                except BaseException as error:errors.append(error)
            if not self._retirement_wait_attempted:
                self._retirement_wait_attempted=True
                try:assert self._ops.wait(self._process_handle,1000)==0
                except BaseException as error:errors.append(error)
        for stream in self._streams:
            try:stream.close()
            except BaseException as error:errors.append(error)
        for fd in self._fds:
            try:self._ops.close_fd(fd)
            except BaseException as error:errors.append(error)
        for handle in reversed(self._raw):
            try:self._ops.close(handle)
            except BaseException as error:errors.append(error)
        self._streams.clear();self._fds.clear();self._raw.clear()
        if errors:self._close_error=errors[0];raise self._close_error
# suspended-witness:end launcher

def capture(argv,deadline,stdout_cap,*,popen=_SuspendedProcess,identity=_identity,clock=time.monotonic):
    result = dict(exitCode=None,pid=None,creationTime=None,imageMatched=False,naturalExit=False,
                  handlesClosed=False,timedOut=False,outputCapReached=False,captureError=False)
    # capture-observation:begin capture-init
    result['captureObservation']=capture_observation()
    capture_phase=1
    # capture-observation:end capture-init
    out,err = bytearray(),bytearray()
    process = None
    readers = []
    reached = threading.Event()
    failed = threading.Event()
    end = min(deadline,clock()+5.)
    if clock() >= end:
        result['timedOut'] = True
        # capture-observation:begin capture-expired
        _capture_observe(result,capture_phase)
        # capture-observation:end capture-expired
        return result,bytes(out),bytes(err)
    def drain(pipe,target,cap):
        try:
            while len(target) < cap:
                part = pipe.read(min(1024,cap-len(target)))
                if not part:
                    return
                target.extend(part)
            reached.set()
        except BaseException:
            failed.set()
        finally:
            pipe.close()
    try:
        process = popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        bufsize=0,creationflags=0,close_fds=True)
        # capture-observation:begin after-launch
        capture_phase=2
        # capture-observation:end after-launch
        witness = identity(process)
        # capture-observation:begin after-identity
        capture_phase=3
        # capture-observation:end after-identity
        result.update(pid=witness['pid'],creationTime=witness['creationTime'],
                      imageMatched=Path(witness['image']) == Path(argv[0]))
        # capture-observation:begin after-witness
        capture_phase=4
        # capture-observation:end after-witness
        assert result['imageMatched'], 'Queried child image differs'
        # suspended-witness:begin resume
        if type(process) is _SuspendedProcess:
            assert clock()<end, 'Query expired before original thread resume'
            process.resume_original()
        # suspended-witness:end resume
        for pipe,target,cap in ((process.stdout,out,stdout_cap),(process.stderr,err,STDERR_CAP)):
            reader = threading.Thread(target=drain,args=(pipe,target,cap),daemon=True)
            reader.start()
            readers.append(reader)
        # capture-observation:begin before-sampling
        capture_phase=5
        # capture-observation:end before-sampling
        while process.poll() is None:
            if reached.is_set() or failed.is_set():
                break
            remaining = end-clock()
            if remaining <= 0:
                result['timedOut'] = True
                break
            try:
                process.wait(timeout=min(.02,remaining))
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            process.kill()  # Original Popen HANDLE only; inherited Job is never reclassified.
        else:
            result['naturalExit'] = True
        # capture-observation:begin before-wait
        capture_phase=6
        # capture-observation:end before-wait
        process.wait(timeout=1.)
        result['exitCode'] = process.returncode
        for reader in readers:
            reader.join(timeout=.2)
        result['outputCapReached'] = reached.is_set()
        result['captureError'] = failed.is_set() or any(r.is_alive() for r in readers)
    except BaseException as capture_error:
        result['captureError'] = True
        # capture-observation:begin main-exception
        _capture_observe(result,capture_phase,capture_error)
        # capture-observation:end main-exception
    finally:
        if process is not None:
            # suspended-witness:begin cleanup
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=1.)
                for reader in readers:
                    reader.join(timeout=.2)
            finally:
                # capture-observation:begin cleanup-phase
                capture_phase=7
                # capture-observation:end cleanup-phase
                try:
                    # suspended-witness:begin close-primary
                    try:
                        process.stdout.close()
                        process.stderr.close()
                    except BaseException:
                        try:process._handle.Close()
                        except BaseException:pass
                        raise
                    process._handle.Close()
                    # suspended-witness:end close-primary
                    result['handlesClosed'] = True
                except BaseException as capture_error:
                    result['captureError'] = True
                    # capture-observation:begin cleanup-exception
                    _capture_observe(result,capture_phase,capture_error)
                    # capture-observation:end cleanup-exception
            # suspended-witness:end cleanup
    # capture-observation:begin capture-return
    _capture_observe(result,8)
    # capture-observation:end capture-return
    return result,bytes(out),bytes(err)

def query(request,*,capture_call=capture):
    assert type(request) is dict and set(request) == {'schemaVersion','kindCode','tool','deadline'}
    assert type(request['schemaVersion']) is int and request['schemaVersion'] == 1
    kind = request['kindCode']
    assert type(kind) is int and kind in (0,1,2)
    tool = request['tool']
    assert type(tool) is str and Path(tool).is_absolute() and len(tool) <= 4096
    path=Path(tool)
    if kind:
        assert tuple(part.casefold() for part in path.parts[-6:])==('vc','tools','llvm','x64','bin',('clang-cl.exe','lld-link.exe')[kind-1])
    else:
        assert path.name.casefold()=='vswhere.exe'
        assert tuple(part.casefold() for part in path.parts[-3:-1])==('microsoft visual studio','installer')
    assert type(request['deadline']) in (int,float) and math.isfinite(request['deadline'])
    assert request['deadline']-time.monotonic() <= 30.
    argv = [tool,'--version'] if kind else [tool,'-utf8','-latest','-products','*','-requires',
            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath']
    observed,out,err = capture_call(argv,request['deadline'],32768 if kind == 0 else VERSION_CAP)
    result = dict(schemaVersion=1,kindCode=kind,resultCode=0,exitCode=observed['exitCode'],major=None,minor=None,
                  selectedRoot=None,stdoutBytes=len(out),stderrBytes=len(err),timedOut=observed['timedOut'],
                  outputCapReached=observed['outputCapReached'],pid=observed['pid'],creationTime=observed['creationTime'],
                  imageMatched=observed['imageMatched'],naturalExit=observed['naturalExit'],handlesClosed=observed['handlesClosed'])
    # capture-observation:begin query-projection
    validate_capture_observation(observed['captureObservation'])
    result['captureObservation']=observed['captureObservation']
    # capture-observation:end query-projection
    # discovery-observation:begin parse-init
    discovery_stage=0
    # discovery-observation:end parse-init
    if observed['timedOut']:result['resultCode'] = 2
    elif observed['outputCapReached']:result['resultCode'] = 3
    elif observed['captureError'] or not all(observed[k] for k in ('imageMatched','naturalExit','handlesClosed')):result['resultCode'] = 7
    elif observed['exitCode'] != 0:result['resultCode'] = 4
    else:
        try:
            if kind:
                result['major'],result['minor'] = parse_version(out,kind)
            else:
                # discovery-observation:begin parse-length
                discovery_stage=1
                # discovery-observation:end parse-length
                assert 0 < len(out) <= 4096 and b'\0' not in out
                # discovery-observation:begin parse-decode
                discovery_stage=2
                # discovery-observation:end parse-decode
                root = out.decode('utf-8-sig').strip()
                # discovery-observation:begin parse-crlf
                discovery_stage=3
                # The truthy local stamp runs only after both original CR/LF short circuits.
                # discovery-observation:end parse-crlf
                assert '\n' not in root and '\r' not in root and (discovery_stage:=4) and Path(root).is_absolute()
                result['selectedRoot'] = root
                # discovery-observation:begin parse-complete
                discovery_stage=5
                # discovery-observation:end parse-complete
        except BaseException:
            result['resultCode'] = 5 if kind else 8
    # discovery-observation:begin parse-return
    result['discoveryParseStage']=discovery_stage
    # discovery-observation:end parse-return
    return result

def main(argv=None):
    # No argparse error message can echo an unexpected path or query output.
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4 or args[0] != '--request' or args[2] != '--result':return 1
    try:
        request_path,result_path = Path(args[1]),Path(args[3])
        assert request_path.is_absolute() and result_path.is_absolute()
        assert request_path.is_file() and 0 < request_path.stat().st_size <= 8192
        with request_path.open('rb') as stream:raw=stream.read(8192)
        assert len(raw)==request_path.stat().st_size<=8192
        request = json.loads(raw)
        result = query(request)
        blob = (json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode('ascii')
        assert set(result) == RESULT_KEYS and len(blob) <= 8192
        with result_path.open('xb') as stream:stream.write(blob)
        return 0  # Observations, including missing/old versions, carry numeric failure only.
    except BaseException:
        return 1

# compile-qualification:begin helpers
NEGATIVE_SOURCE=b'#error OPENGeul compiler qualification negative\n'
COMPILE_RESULT_KEYS={'schemaVersion','kindCode','resultCode','exitCode','stdoutBytes','stderrBytes',
    'timedOut','outputCapReached','pid','creationTime','imageMatched','naturalExit','handlesClosed',
    'captureObservation','sourcePinsBeforeAfterEqual','toolPinsBeforeAfterEqual','objectAbsent'}

def validate_compile_result(value):
    assert type(value) is dict and set(value)==COMPILE_RESULT_KEYS
    assert type(value['schemaVersion']) is int and value['schemaVersion']==1
    assert type(value['kindCode']) is int and value['kindCode']==3
    assert type(value['resultCode']) is int and value['resultCode'] in (0,1,2,3,4,5,7)
    assert value['exitCode'] is None or type(value['exitCode']) is int and -0x80000000<=value['exitCode']<=0xffffffff
    for key in ('stdoutBytes','stderrBytes'):
        assert type(value[key]) is int and 0<=value[key]<=VERSION_CAP
    for key in ('timedOut','outputCapReached','imageMatched','naturalExit','handlesClosed',
                'sourcePinsBeforeAfterEqual','toolPinsBeforeAfterEqual','objectAbsent'):
        assert type(value[key]) is bool
    for key,maximum in (('pid',0xffffffff),('creationTime',0xffffffffffffffff)):
        assert value[key] is None or type(value[key]) is int and 0<value[key]<=maximum
    validate_capture_observation(value['captureObservation'])
    if value['resultCode']==1:
        assert value['exitCode'] is value['pid'] is value['creationTime'] is None
        assert value['stdoutBytes']==value['stderrBytes']==0
        assert value['captureObservation']['observedMask']==0
    if value['resultCode']==0:
        assert type(value['exitCode']) is int and value['exitCode']!=0
        assert value['pid'] is not None and value['creationTime'] is not None
        assert all(value[key] is True for key in ('imageMatched','naturalExit','handlesClosed',
            'sourcePinsBeforeAfterEqual','toolPinsBeforeAfterEqual','objectAbsent'))
        assert value['timedOut'] is value['outputCapReached'] is False
        assert not value['captureObservation']['observedMask']&2

def compile_query(request,*,capture_call=capture,clock=time.monotonic):
    import hashlib
    import stat
    result=dict(schemaVersion=1,kindCode=3,resultCode=1,exitCode=None,stdoutBytes=0,stderrBytes=0,
        timedOut=False,outputCapReached=False,pid=None,creationTime=None,imageMatched=False,
        naturalExit=False,handlesClosed=False,captureObservation=capture_observation(),
        sourcePinsBeforeAfterEqual=False,toolPinsBeforeAfterEqual=False,objectAbsent=False)
    try:
        assert type(request) is dict and set(request)=={'schemaVersion','kindCode','tool','source','object','deadline','sourcePin','toolPin'}
        assert type(request['schemaVersion']) is int and request['schemaVersion']==1
        assert type(request['kindCode']) is int and request['kindCode']==3
        deadline=request['deadline']
        assert type(deadline) in (int,float) and math.isfinite(deadline)
        last=clock();assert type(last) in (int,float) and math.isfinite(last) and 0<deadline-last<=30.
        def check():
            nonlocal last
            now=clock();assert type(now) in (int,float) and math.isfinite(now) and last<=now<deadline
            last=now
        def absolute(value):
            assert type(value) is str and 0<len(value)<=4093 and not any(c in value for c in '\0\r\n')
            assert not value.replace('\\','/').startswith('//')
            path=Path(value);assert path.is_absolute() and path.parent.is_dir()
            assert path.parent.resolve(strict=True)==path.parent
            for part in (path,*path.parents):
                assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)()
                if part.exists():assert not getattr(part.lstat(),'st_file_attributes',0)&0x400
            return path
        tool,source,obj=(absolute(request[key]) for key in ('tool','source','object'))
        assert tuple(part.casefold() for part in tool.parts[-6:])==('vc','tools','llvm','x64','bin','clang-cl.exe')
        assert source.name=='negative.cpp' and obj.name=='negative.obj' and obj.parent==source.parent
        assert not obj.exists() and not obj.is_symlink()
        from native_compiler_tools import pin_native_tool,validate_tool_pin
        import native_suite_architecture as native_arch
        native_arch.validate_native_architecture(native_arch.observe_native_architecture(),'x64')
        validate_tool_pin(request['toolPin'],'x64','clang-cl.exe')
        assert request['toolPin']['path']==str(tool)
        expected=request['sourcePin']
        assert type(expected) is dict and set(expected)=={'bytes','sha256'}
        assert type(expected['bytes']) is int and expected['bytes']==len(NEGATIVE_SOURCE)
        assert type(expected['sha256']) is str and expected['sha256']==hashlib.sha256(NEGATIVE_SOURCE).hexdigest()
        def source_pin():
            check();absolute(str(source));before=source.stat();assert stat.S_ISREG(before.st_mode)
            assert before.st_size==len(NEGATIVE_SOURCE)
            with source.open('rb') as stream:
                held=os.fstat(stream.fileno());raw=stream.read(len(NEGATIVE_SOURCE)+1);after=os.fstat(stream.fileno())
            current=source.stat();identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
            assert identity(before)==identity(current) and identity(held)==identity(after)
            assert (before.st_dev,before.st_ino,before.st_size)==(held.st_dev,held.st_ino,held.st_size)
            assert raw==NEGATIVE_SOURCE
            value=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());check();return value
        def tool_pin():
            facts={};value=pin_native_tool(tool,'x64',check=check,facts=facts)
            assert all(facts['pathBefore'][key]==facts['fdBefore'][key] for key in ('st_dev','st_ino','st_size'))
            return value,facts
        before_source=source_pin();assert before_source==expected
        before_tool,before_facts=tool_pin();assert before_tool==request['toolPin'];check()
    except BaseException:
        validate_compile_result(result);return result
    result['resultCode']=7
    try:
        argv=[str(tool),'--no-default-config','--target=x86_64-pc-windows-msvc','/nologo','/c','/O2','/MT',
            '/EHsc','/std:c++17','/W4','/WX','/utf-8',str(source),'/Fo'+str(obj)]
        observed,out,err=capture_call(argv,deadline,VERSION_CAP)
        assert type(out) is bytes and type(err) is bytes and len(out)<=VERSION_CAP and len(err)<=STDERR_CAP
        assert type(observed['captureError']) is bool
        projected=dict(result,**{key:observed[key] for key in ('exitCode','pid','creationTime','timedOut',
            'outputCapReached','imageMatched','naturalExit','handlesClosed','captureObservation')},stdoutBytes=len(out),stderrBytes=len(err))
        validate_compile_result(projected);result=projected
        if observed['timedOut']:result['resultCode']=2
        elif observed['outputCapReached']:result['resultCode']=3
        elif (observed['captureError'] or observed['captureObservation']['observedMask']&2
                or not all(observed[key] for key in ('imageMatched','naturalExit','handlesClosed'))
                or observed['pid'] is None or observed['creationTime'] is None or observed['exitCode'] is None):result['resultCode']=7
        else:result['resultCode']=0 if observed['exitCode']!=0 else 4
    except BaseException:
        result['resultCode']=7
    try:result['sourcePinsBeforeAfterEqual']=source_pin()==before_source
    except BaseException:pass
    try:
        after_tool,after_facts=tool_pin()
        result['toolPinsBeforeAfterEqual']=after_tool==before_tool and after_facts==before_facts
    except BaseException:pass
    try:
        check();absolute(str(obj));result['objectAbsent']=not obj.exists() and not obj.is_symlink();check()
    except BaseException:pass
    if result['resultCode']==0 and not all(result[key] for key in ('sourcePinsBeforeAfterEqual','toolPinsBeforeAfterEqual','objectAbsent')):
        result['resultCode']=5
    validate_compile_result(result);return result

def compile_main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if len(args)!=4 or args[0]!='--compile-request' or args[2]!='--result':return 1
    try:
        assert all(type(value) is str and not value.replace('\\','/').startswith('//') for value in (args[1],args[3]))
        request_path,result_path=Path(args[1]),Path(args[3])
        assert request_path.is_absolute() and result_path.is_absolute() and request_path.parent==result_path.parent
        for path in (request_path,result_path):
            assert path.parent.resolve(strict=True)==path.parent
            for part in (path,*path.parents):
                assert not part.is_symlink() and not getattr(part,'is_junction',lambda:False)()
                if part.exists():assert not getattr(part.lstat(),'st_file_attributes',0)&0x400
        assert request_path.is_file() and 0<request_path.stat().st_size<=8192
        assert not result_path.exists()
        with request_path.open('rb') as stream:raw=stream.read(8193)
        assert len(raw)==request_path.stat().st_size<=8192
        result=compile_query(json.loads(raw));validate_compile_result(result)
        blob=(json.dumps(result,sort_keys=True,allow_nan=False)+'\n').encode('ascii');assert len(blob)<=8192
        with result_path.open('xb') as stream:stream.write(blob)
        return 0
    except BaseException:return 1
# compile-qualification:end helpers

# compile-qualification:begin entry
if __name__ == '__main__':
    raise SystemExit(compile_main() if sys.argv[1:2]==['--compile-request'] else main())
# compile-qualification:end entry
