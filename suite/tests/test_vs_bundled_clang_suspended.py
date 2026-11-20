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

# compile-qualification:begin tests
class NegativeCompileTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        import struct
        import tempfile
        self.assertTrue(callable(getattr(h,'compile_query',None)), 'negative compile boundary missing')
        self.assertTrue(callable(getattr(h,'validate_compile_result',None)), 'numeric compile validator missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(strict=True);self.source=self.root/'negative.cpp';self.obj=self.root/'negative.obj'
        self.source.write_bytes(h.NEGATIVE_SOURCE)
        self.tool=self.root/'VS/VC/Tools/Llvm/x64/bin/clang-cl.exe';self.tool.parent.mkdir(parents=True)
        raw=bytearray(4096);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,64);raw[64:68]=b'PE\0\0'
        struct.pack_into('<HHIIIHH',raw,68,0x8664,1,0,0,0,240,2)
        struct.pack_into('<H',raw,88,0x20b);struct.pack_into('<I',raw,196,16)
        self.tool.write_bytes(raw)
        spec=importlib.util.spec_from_file_location('negative_compile_native_tools',ROOT/'e2e/native_compiler_tools.py')
        self.tools=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.tools)
        self.native=dict(processMachine=0,nativeMachine=0x8664,processArchitecture='x64',nativeArchitecture='x64')
        spec=importlib.util.spec_from_file_location('negative_compile_native_arch',ROOT/'e2e/native_suite_architecture.py')
        self.arch=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.arch)
        modules=patch.dict(h.sys.modules,{'native_compiler_tools':self.tools,'native_suite_architecture':self.arch})
        modules.start();self.addCleanup(modules.stop)
        observed=patch.object(self.arch,'observe_native_architecture',lambda:dict(self.native))
        observed.start();self.addCleanup(observed.stop)
        self.hash=lambda data:hashlib.sha256(data).hexdigest()
        self.request=dict(schemaVersion=1,kindCode=3,tool=str(self.tool),source=str(self.source),object=str(self.obj),
            deadline=104.,sourcePin=dict(bytes=len(h.NEGATIVE_SOURCE),sha256=self.hash(h.NEGATIVE_SOURCE)),
            toolPin=dict(path=str(self.tool),bytes=len(raw),sha256=self.hash(raw),machine=0x8664))
        self.calls=[];self.output=b'';self.error=b'synthetic negative diagnostics'
        self.observed=dict(exitCode=1,pid=71,creationTime=13,imageMatched=True,naturalExit=True,handlesClosed=True,
            timedOut=False,outputCapReached=False,captureError=False,captureObservation=h.capture_observation())
        self.after=None
    def capture(self,argv,deadline,cap):
        self.calls.append((argv,deadline,cap))
        if self.after:self.after()
        return dict(self.observed),self.output,self.error
    def query(self,request=None,clock=lambda:100.):
        return h.compile_query(self.request if request is None else request,capture_call=self.capture,clock=clock)
    def test_exact_pinned_negative_has_fixed_arguments_and_numeric_only_result(self):
        result=self.query();h.validate_compile_result(result)
        self.assertEqual(result['resultCode'],0);self.assertEqual(result['kindCode'],3)
        self.assertEqual(self.calls,[([str(self.tool),'--no-default-config','--target=x86_64-pc-windows-msvc',
            '/nologo','/c','/O2','/MT','/EHsc','/std:c++17','/W4','/WX','/utf-8',str(self.source),'/Fo'+str(self.obj)],104.,4096)])
        self.assertEqual(result['stderrBytes'],len(self.error));self.assertFalse(self.obj.exists())
        self.assertEqual(set(result),h.COMPILE_RESULT_KEYS)
        def numeric(value):
            if type(value) is dict:return all(numeric(v) for v in value.values())
            return value is None or type(value) in (int,bool)
        self.assertTrue(numeric(result))
    def test_bad_request_source_or_tool_pin_never_captures(self):
        import copy
        variants=[]
        for field,value in (('kindCode',True),('schemaVersion',True),('deadline',True),('deadline',100.),('deadline',float('inf'))):
            bad=copy.deepcopy(self.request);bad[field]=value;variants.append(bad)
        for field in ('sourcePin','toolPin'):
            bad=copy.deepcopy(self.request);bad[field]['sha256']='0'*64;variants.append(bad)
            bad=copy.deepcopy(self.request);bad[field]['bytes']=True;variants.append(bad)
        bad=copy.deepcopy(self.request);bad['extra']=0;variants.append(bad)
        bad=copy.deepcopy(self.request);bad['sourcePin']['extra']=0;variants.append(bad)
        for bad in variants:
            with self.subTest(index=len(self.calls)):
                result=self.query(bad);self.assertEqual(result['resultCode'],1);h.validate_compile_result(result)
        self.assertEqual(self.calls,[])
    def test_foreign_controller_or_forged_foreign_executable_never_captures(self):
        import struct
        self.native['processMachine']=0x8664
        self.assertEqual(self.query()['resultCode'],1)
        self.native['processMachine']=0
        raw=bytearray(self.tool.read_bytes());struct.pack_into('<H',raw,68,0xaa64);self.tool.write_bytes(raw)
        self.request['toolPin']['sha256']=self.hash(raw)
        self.assertEqual(self.query()['resultCode'],1);self.assertEqual(self.calls,[])
    def test_wrong_names_existing_object_and_linked_source_never_capture(self):
        import copy
        for field,value in (('source',str(self.source.with_name('other.cpp'))),('object',str(self.obj.with_name('other.obj'))),
                ('object',str(self.root/'nested/negative.obj')),('tool',str(self.tool.with_name('lld-link.exe')))):
            bad=copy.deepcopy(self.request);bad[field]=value;self.assertEqual(self.query(bad)['resultCode'],1)
        self.obj.write_bytes(b'existing');self.assertEqual(self.query()['resultCode'],1);self.obj.unlink()
        original=self.source.read_bytes();self.source.unlink();self.source.symlink_to(self.tool)
        self.assertEqual(self.query()['resultCode'],1);self.source.unlink();self.source.write_bytes(original)
        self.assertEqual(self.calls,[])
    def test_deadline_expiring_during_pins_never_captures(self):
        ticks=iter((100.,100.,100.,104.))
        result=self.query(clock=lambda:next(ticks,104.))
        self.assertEqual(result['resultCode'],1);self.assertEqual(self.calls,[])
    def test_capture_must_be_nonzero_natural_closed_and_untruncated(self):
        for mutation,code in ((dict(exitCode=0),4),(dict(timedOut=True),2),(dict(outputCapReached=True),3),
                (dict(captureError=True),7),(dict(imageMatched=False),7),(dict(naturalExit=False),7),(dict(handlesClosed=False),7)):
            with self.subTest(code=code):
                original=dict(self.observed);self.observed.update(mutation)
                result=self.query();self.assertEqual(result['resultCode'],code);h.validate_compile_result(result)
                self.observed=original
    def test_post_capture_source_drift_and_created_object_cannot_qualify(self):
        self.after=lambda:self.source.write_bytes(b'changed')
        result=self.query();self.assertEqual(result['resultCode'],5);self.assertFalse(result['sourcePinsBeforeAfterEqual'])
        self.source.write_bytes(h.NEGATIVE_SOURCE);self.after=lambda:self.obj.write_bytes(b'new output')
        result=self.query();self.assertEqual(result['resultCode'],5);self.assertFalse(result['objectAbsent'])
    def test_post_capture_tool_drift_cannot_qualify(self):
        self.after=lambda:self.tool.write_bytes(self.tool.read_bytes()+b'changed')
        result=self.query();self.assertEqual(result['resultCode'],5);self.assertFalse(result['toolPinsBeforeAfterEqual'])
    def test_pure_validator_rejects_accepted_zero_exit_and_missing_custody(self):
        import copy
        result=self.query()
        for field,value in (('exitCode',0),('exitCode',True),('naturalExit',False),('handlesClosed',False),
                ('sourcePinsBeforeAfterEqual',False),('toolPinsBeforeAfterEqual',False),('objectAbsent',False),('stdoutBytes','private')):
            bad=copy.deepcopy(result);bad[field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):h.validate_compile_result(bad)
    def test_compile_main_records_numeric_preflight_rejection_with_outer_zero(self):
        import contextlib
        request=self.root/'request.json';result=self.root/'result.json'
        request.write_text(h.json.dumps(dict(self.request,kindCode=2)))
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=h.compile_main(['--compile-request',str(request),'--result',str(result)])
        self.assertEqual(code,0);value=h.json.loads(result.read_bytes());h.validate_compile_result(value)
        self.assertEqual(value['resultCode'],1);self.assertEqual(out.getvalue(),err.getvalue());self.assertEqual(out.getvalue(),'')
        self.assertEqual(h.compile_main(['--compile-request',str(request),'--unexpected',str(result)]),1)
    def test_unc_genuine_file_aliases_never_reach_capture(self):
        import copy
        unc=lambda path:'/'+str(path)
        variants=[]
        request=copy.deepcopy(self.request);request['tool']=unc(self.tool);request['toolPin']['path']=unc(self.tool);variants.append(request)
        request=copy.deepcopy(self.request);request['source']=unc(self.source);request['object']=unc(self.obj);variants.append(request)
        # Linux resolves //tmp to /tmp. Preserve the canonical UNC spelling as
        # Windows does, while the fixture still addresses the genuine files.
        with patch.object(h.Path,'resolve',lambda path,*args,**kwargs:path):
            for request in variants:
                result=self.query(request)
                self.unc_result_code=result['resultCode'];self.unc_capture_attempts=len(self.calls)
                self.assertEqual(result['resultCode'],1)
        self.assertEqual(self.calls,[])
    def test_compile_main_rejects_unc_request_and_result_before_file_access(self):
        request=self.root/'unc-request.json';result=self.root/'unc-result.json'
        request.write_text(h.json.dumps(dict(self.request,kindCode=2)))
        with patch.object(h.Path,'resolve',lambda path,*args,**kwargs:path):
            code=h.compile_main(['--compile-request','/'+str(request),'--result','/'+str(result)])
        self.unc_main_exit=code
        self.assertEqual(code,1);self.assertFalse(result.exists());self.assertEqual(self.calls,[])
# compile-qualification:end tests
