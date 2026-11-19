"""Synthetic HANDLE custody; no Windows API, native tool, or environment read."""
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('suspended_helper_tested',ROOT/'e2e/vs_bundled_clang_version.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)

class Ops:
    def __init__(self,fault=None,resume_count=1):
        self.events=[];self.handles=set();self.fds=set();self.inheritable=set();self.closed=[]
        self.next=100;self.fdnext=1000;self.phase={};self.fault=fault;self.raised=False
        self.primary=KeyboardInterrupt();self.resume_count=resume_count;self.suspended=True;self.returncode=None
        self.pipe_count=0;self.file_count=0;self.close_calls={};self.create_args=None
    def event(self,name):
        self.events.append(name)
        if name==self.fault and not self.raised:self.raised=True;raise self.primary
    def new(self):self.next+=4;self.handles.add(self.next);return self.next
    def open_nul(self):self.event('nul-open');self.fdnext+=1;self.fds.add(self.fdnext);return self.fdnext
    def fd_handle(self,fd):self.event('nul-handle');assert fd in self.fds;return fd+10000
    def duplicate(self,handle):
        self.event('dup');assert handle in self.handles or handle-10000 in self.fds
        result=self.new();self.inheritable.add(result);return result
    def pipe(self):self.pipe_count+=1;self.event('pipe'+str(self.pipe_count));return self.new(),self.new()
    def close(self,handle):
        self.close_calls[('handle',handle)]=self.close_calls.get(('handle',handle),0)+1
        self.event('close-handle');assert handle in self.handles
        self.handles.remove(handle);self.closed.append(handle)
    def close_fd(self,fd):
        self.close_calls[('fd',fd)]=self.close_calls.get(('fd',fd),0)+1
        self.event('close-fd');assert fd in self.fds;self.fds.remove(fd)
    def read_fd(self,handle):
        self.event('read-fd');assert handle in self.handles;self.handles.remove(handle)
        self.fdnext+=1;self.fds.add(self.fdnext);return self.fdnext
    def fileio(self,fd):
        self.file_count+=1;self.event('fileio'+str(self.file_count));assert fd in self.fds
        owner=self;data=io.BytesIO(b'LLD 22.1.7\n' if self.file_count==1 else b'')
        class Pipe:
            def read(self,size):owner.event('read');assert not owner.suspended;return data.read(size)
            def close(self):owner.event('stream-close')
        return Pipe()
    def startupinfo(self,**kw):self.event('startupinfo');return SimpleNamespace(**kw)
    def create(self,application,command,ps,ts,inherit,flags,env,cwd,startup):
        self.event('create')
        self.create_args=(application,command,ps,ts,inherit,flags,env,cwd,startup)
        handles=startup.lpAttributeList['handle_list']
        assert len(handles)==len(set(handles))==3 and set(handles)<=self.inheritable
        assert handles==[startup.hStdInput,startup.hStdOutput,startup.hStdError]
        self.hp,self.ht=self.new(),self.new();return self.hp,self.ht,71,72
    def resume(self,thread):
        self.event('resume');assert thread==self.ht and self.hp in self.handles
        if type(self.resume_count) is int and self.resume_count==1:self.suspended=False;self.returncode=0
        return self.resume_count
    def wait(self,handle,millis):self.event('wait');assert handle==self.hp and 0<=millis<=1000;return 258 if self.returncode is None else 0
    def exit_code(self,handle):self.event('exit-code');assert handle==self.hp;return self.returncode
    def terminate(self,handle,code):self.event('terminate');assert handle==self.hp and code==1;self.returncode=1

class SuspendedTests(unittest.TestCase):
    def argv(self):return [str(Path.cwd()/'VS/VC/Tools/Llvm/x64/bin/lld-link.exe'),'--version']
    def options(self):return dict(stdin=h.subprocess.DEVNULL,stdout=h.subprocess.PIPE,stderr=h.subprocess.PIPE,bufsize=0,creationflags=0,close_fds=True)
    def process(self,ops,**overrides):
        values=self.options();values.update(overrides)
        return h._SuspendedProcess(self.argv(),ops=ops,**values)
    def capture(self,ops,identity=None):
        argv=self.argv()
        if identity is None:
            def identity(process):
                ops.event('identity');assert ops.suspended and int(process._handle)==ops.hp
                return dict(pid=process.pid,creationTime=13,image=argv[0])
        def launch(*args,**kwargs):
            if hasattr(h,'_SuspendedProcess'):return h._SuspendedProcess(*args,ops=ops,**kwargs)
            class Legacy:
                pid=71;returncode=0
                stdout=io.BytesIO();stderr=io.BytesIO();_handle=SimpleNamespace(Close=lambda:None)
                def poll(self):return 0
                def wait(self,timeout):return 0
            ops.suspended=False
            return Legacy()
        return h.capture(argv,h.time.monotonic()+4,4096,popen=launch,identity=identity)
    def test_fast_exit_witness_precedes_resume_and_drain(self):
        ops=Ops();result,out,err=self.capture(ops)
        self.assertFalse(result['captureError']);self.assertTrue(result['naturalExit']);self.assertTrue(result['handlesClosed'])
        self.assertEqual(out,b'LLD 22.1.7\n');self.assertEqual(err,b'')
        self.assertLess(ops.events.index('identity'),ops.events.index('resume'))
        self.assertLess(ops.events.index('resume'),ops.events.index('read'))
        self.assertEqual(ops.events.count('resume'),1);self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
        self.assertTrue(all(n==1 for n in ops.close_calls.values()))
    def test_create_has_exact_application_inherited_finite_env_and_std_only(self):
        ops=Ops();process=self.process(ops);a=ops.create_args
        self.assertEqual(a[0],self.argv()[0]);self.assertEqual(a[1],h.subprocess.list2cmdline(self.argv()))
        self.assertEqual(a[2:8],(None,None,True,4,None,None))
        self.assertEqual(a[8].dwFlags,0x100);self.assertEqual(len(a[8].lpAttributeList['handle_list']),3)
        self.assertEqual(ops.handles,{ops.hp,ops.ht});self.assertEqual(len(ops.fds),2)
        process.kill();process.wait(timeout=1);process._handle.Close()
        self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
    def test_constructor_failure_prefixes_preserve_primary_and_close_owned_only(self):
        for fault in ('nul-open','nul-handle','dup','pipe1','pipe2','read-fd','fileio1','fileio2','startupinfo','create'):
            with self.subTest(fault=fault):
                ops=Ops(fault=fault)
                with self.assertRaises(KeyboardInterrupt) as caught:self.process(ops)
                self.assertIs(caught.exception,ops.primary);self.assertNotIn('resume',ops.events)
                self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
                self.assertTrue(all(n==1 for n in ops.close_calls.values()))
    def test_child_only_close_failure_after_create_retires_original_suspended_handles(self):
        ops=Ops();original=ops.create
        def create(*args):
            value=original(*args);ops.fault='close-handle';return value
        ops.create=create
        with self.assertRaises(KeyboardInterrupt) as caught:self.process(ops)
        self.assertIs(caught.exception,ops.primary);self.assertIn('terminate',ops.events);self.assertIn('wait',ops.events)
        self.assertNotIn('resume',ops.events);self.assertTrue(all(n==1 for n in ops.close_calls.values()))
    def test_resume_count_other_than_one_is_rejected_and_original_process_retired(self):
        for count in (0,2,0xffffffff,True):
            with self.subTest(count=count):
                ops=Ops(resume_count=count);result,_,_=self.capture(ops)
                self.assertTrue(result['captureError']);self.assertFalse(result['naturalExit']);self.assertTrue(result['handlesClosed'])
                self.assertEqual(ops.events.count('resume'),1);self.assertIn('terminate',ops.events)
                self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
    def test_resume_cancellation_preserves_failure_and_cleans_all(self):
        ops=Ops(fault='resume');result,_,_=self.capture(ops)
        self.assertTrue(result['captureError']);self.assertTrue(result['handlesClosed']);self.assertEqual(ops.events.count('resume'),1)
        self.assertIn('terminate',ops.events);self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
    def test_image_and_creation_guard_failures_never_resume(self):
        for boundary in ('image','creation'):
            with self.subTest(boundary=boundary):
                ops=Ops()
                def identity(process):
                    ops.event('identity')
                    if boundary=='creation':raise OSError(31,'synthetic')
                    return dict(pid=process.pid,creationTime=13,image='foreign.exe')
                result,_,_=self.capture(ops,identity)
                self.assertTrue(result['captureError']);self.assertTrue(result['handlesClosed']);self.assertNotIn('resume',ops.events)
                self.assertIn('terminate',ops.events);self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
    def test_repeat_resume_and_close_do_not_repeat_native_calls(self):
        ops=Ops();process=self.process(ops);process.resume_original()
        with self.assertRaises(AssertionError):process.resume_original()
        process.wait(timeout=1);process._handle.Close();process._handle.Close()
        self.assertEqual(ops.events.count('resume'),1);self.assertTrue(all(n==1 for n in ops.close_calls.values()))
    def test_caller_handle_or_launch_flag_variants_fail_before_allocation(self):
        for options in (dict(stdin=0),dict(stdout=0),dict(stderr=0),dict(creationflags=4),dict(close_fds=False),dict(bufsize=1)):
            with self.subTest(options=tuple(options)):
                ops=Ops()
                with self.assertRaises(AssertionError):self.process(ops,**options)
                self.assertEqual(ops.events,[])

    def test_cleanup_poll_cancellation_preserves_primary_and_retires_original(self):
        ops=Ops(fault='wait')
        def identity(_):raise ValueError('synthetic identity')
        with self.assertRaises(KeyboardInterrupt) as caught:self.capture(ops,identity)
        self.assertIs(caught.exception,ops.primary);self.assertNotIn('resume',ops.events)
        self.assertIn('terminate',ops.events);self.assertEqual(ops.returncode,1)
        self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
        self.assertTrue(all(n==1 for n in ops.close_calls.values()))

    def test_duplicate_child_handle_is_rejected_without_double_close(self):
        ops=Ops();original=ops.duplicate;calls=[]
        def duplicate(handle):
            calls.append(handle)
            return handle if len(calls)==2 else original(handle)
        ops.duplicate=duplicate
        with self.assertRaises(AssertionError):self.process(ops)
        self.assertNotIn('create',ops.events);self.assertNotIn('resume',ops.events)
        self.assertTrue(all(n==1 for n in ops.close_calls.values()))
        self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())

    def test_cleanup_error_never_relabels_original_identity_failure_as_success(self):
        ops=Ops()
        class Original(ValueError):
            def __str__(self):raise AssertionError('No error text')
            def __repr__(self):raise AssertionError('No error repr')
        def identity(_):ops.fault='close-fd';raise Original()
        result,_,_=self.capture(ops,identity)
        self.assertTrue(result['captureError']);self.assertFalse(result['handlesClosed'])
        self.assertEqual(result['captureObservation']['exceptionKindCode'],3)
        self.assertNotIn('resume',ops.events);self.assertTrue(all(n==1 for n in ops.close_calls.values()))

    def test_expired_original_deadline_never_resumes(self):
        ops=Ops();ticks=iter((100.,100.,104.));argv=self.argv()
        result,_,_=h.capture(argv,104.,4096,clock=lambda:next(ticks),
            popen=lambda *a,**kw:h._SuspendedProcess(*a,ops=ops,**kw),
            identity=lambda process:dict(pid=process.pid,creationTime=13,image=argv[0]))
        self.assertTrue(result['captureError']);self.assertTrue(result['handlesClosed'])
        self.assertNotIn('resume',ops.events);self.assertIn('terminate',ops.events)
        self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())

    def test_invalid_returned_pid_is_rejected_before_resume(self):
        ops=Ops();original=ops.create
        def create(*args):
            hp,ht,_,tid=original(*args);return hp,ht,0,tid
        ops.create=create
        with self.assertRaises(AssertionError):self.process(ops)
        self.assertNotIn('resume',ops.events);self.assertIn('terminate',ops.events)
        self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())

    def test_native_bridge_uses_typed_resume_and_inheritable_std_whitelist(self):
        import ctypes
        from ctypes import wintypes
        import io as iomodule
        for failing_resume in (False,True):
            with self.subTest(failing=failing_resume):
                ops=Ops();dll=[]
                class Resume:
                    def __call__(self,thread):
                        if failing_resume:return 0xffffffff
                        return ops.resume(thread)
                native_resume=Resume()
                def duplicate(source,handle,target,access,inherit,flags):
                    self.assertEqual((source,target,access,inherit,flags),(1,1,0,True,2))
                    return ops.duplicate(handle)
                api=SimpleNamespace(CreatePipe=lambda a,b:ops.pipe(),GetCurrentProcess=lambda:1,
                    DuplicateHandle=duplicate,DUPLICATE_SAME_ACCESS=2,CreateProcess=ops.create,
                    CloseHandle=ops.close,WaitForSingleObject=ops.wait,GetExitCodeProcess=ops.exit_code,
                    TerminateProcess=ops.terminate)
                crt=SimpleNamespace(get_osfhandle=ops.fd_handle,open_osfhandle=lambda handle,flags:ops.read_fd(handle))
                def load(name,**options):
                    dll.append((name,options));return SimpleNamespace(ResumeThread=native_resume)
                def fileio(fd,mode,*,closefd):
                    self.assertEqual((mode,closefd),('rb',False));return ops.fileio(fd)
                with patch.dict(h.sys.modules,{'_winapi':api,'msvcrt':crt}),\
                     patch.object(ctypes,'WinDLL',load,create=True),\
                     patch.object(ctypes,'WinError',lambda _:OSError(31),create=True),\
                     patch.object(ctypes,'get_last_error',lambda:31,create=True),\
                     patch.object(h.os,'O_BINARY',0,create=True),\
                     patch.object(h.os,'open',lambda *_:ops.open_nul()),\
                     patch.object(h.os,'close',ops.close_fd),\
                     patch.object(iomodule,'FileIO',fileio),\
                     patch.object(h.subprocess,'STARTUPINFO',ops.startupinfo,create=True),\
                     patch.object(h.os,'environ',SimpleNamespace()):
                    with patch.object(h.os,'name','nt'):native=h._suspended_ops()
                    self.assertEqual(native_resume.argtypes,(wintypes.HANDLE,));self.assertIs(native_resume.restype,wintypes.DWORD)
                    self.assertEqual(dll,[('kernel32',{'use_last_error':True})])
                    argv=self.argv()
                    result,_,_=h.capture(argv,h.time.monotonic()+4,4096,
                        popen=lambda *a,**kw:h._SuspendedProcess(*a,ops=native,**kw),
                        identity=lambda process:dict(pid=process.pid,creationTime=13,image=argv[0]))
                self.assertEqual(result['captureError'],failing_resume);self.assertTrue(result['handlesClosed'])
                self.assertEqual(ops.create_args[4:8],(True,4,None,None))
                self.assertEqual(ops.handles,set());self.assertEqual(ops.fds,set())
                self.assertTrue(all(n==1 for n in ops.close_calls.values()))
