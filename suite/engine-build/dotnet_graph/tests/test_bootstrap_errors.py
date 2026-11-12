"""Synthetic byte-only bootstrap error observation; never runs an SDK."""
import importlib
import importlib.util
from pathlib import Path
import sys
import ctypes as C
import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class ErrorCodeScannerTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.bootstrap_errors'),
                             'Explicit bootstrap numeric capture is required')
        return importlib.import_module('runtime.bootstrap_errors')

    def scanner(self, **options):
        return self.module().ErrorCodes(**options)

    def test_strict_closed_families_are_counted_without_returning_messages(self):
        s=self.scanner()
        s.feed(0,b'error NU1301: SYNTHETIC_OPAQUE\nerror MSB4126: SYNTHETIC_OPAQUE\n')
        s.feed(s.offset,b'error NETSDK1004: SYNTHETIC_OPAQUE\nerror CS2012: SYNTHETIC_OPAQUE\n')
        v=s.finish()
        self.assertEqual(v['codes'],[[1,1301,1],[2,4126,1],[3,1004,1],[4,2012,1]])
        self.assertTrue(v['complete']);self.assertFalse(v['unknown']);self.assertFalse(v['overflow'])
        self.assertNotIn('SYNTHETIC_OPAQUE',str(v))
        self.assertNotIn('SYNTHETIC_OPAQUE',repr(s))

    def test_every_chunk_split_and_overlap_carry_counts_each_token_once(self):
        raw=b'owned: error NU1301: SYNTHETIC_OPAQUE\nerror NU1301: SYNTHETIC_OPAQUE\n'
        for split in range(len(raw)+1):
            s=self.scanner();s.feed(0,raw[:split]);s.feed(split,raw[split:])
            self.assertEqual(s.finish()['codes'],[[1,1301,2]])

    def test_replayed_or_out_of_order_chunk_is_rejected(self):
        s=self.scanner();s.feed(0,b'error NU1301: ')
        with self.assertRaises(ValueError):s.feed(0,b'error NU1301: ')
        self.assertTrue(s.finish()['unknown'])

    def test_messages_urls_nonascii_and_prefix_substrings_are_not_codes(self):
        s=self.scanner();raw=b'SYNTHETIC_OPAQUE https://example.invalid/private\xff terror NU1301: \nERROR CS1001: \n'
        s.feed(0,raw);v=s.finish()
        self.assertEqual(v['codes'],[]);self.assertFalse(v['unknown'])
        self.assertTrue(v['complete'])

    def test_unknown_family_malformed_code_or_unfinished_token_is_explicit_unknown(self):
        for raw in [b'error XYZ1301: ',b'error NUx: ',b'error CS0: ',b'error CS1234567: ',b'error NU13']:
            s=self.scanner();s.feed(0,raw)
            self.assertTrue(s.finish()['unknown'])

    def test_total_byte_code_and_occurrence_caps_are_closed(self):
        for options,raw in [({'max_bytes':8},b'error NU1301: '),
                            ({'max_codes':1},b'error NU1301: x\nerror CS1001: x\n'),
                            ({'max_count':1},b'error NU1301: x\nerror NU1301: x\n')]:
            s=self.scanner(**options)
            with self.assertRaises(ValueError):s.feed(0,raw)
            self.assertTrue(s.finish()['overflow'])

    def test_streams_cannot_join_partial_error_tokens(self):
        a=self.scanner();b=self.scanner();a.feed(0,b'error NU');b.feed(0,b'1301: ')
        self.assertEqual(a.finish()['codes'],[]);self.assertEqual(b.finish()['codes'],[])
        self.assertTrue(a.finish()['unknown'])

    def test_empty_complete_capture_does_not_claim_a_known_failure_cause(self):
        s=self.scanner();v=s.finish()
        self.assertEqual(v['codes'],[]);self.assertTrue(v['complete']);self.assertFalse(v['codeObserved'])

    def test_nonbyte_or_boolean_offset_input_fails_without_repr(self):
        for offset,data in [(False,b''),(0,'SYNTHETIC_OPAQUE'),(-1,b'')]:
            s=self.scanner()
            with self.assertRaises(ValueError):s.feed(offset,data)


class PipeCaptureTests(unittest.TestCase):
    def module(self):
        m=importlib.import_module('runtime.bootstrap_errors')
        self.assertTrue(hasattr(m,'BootstrapApi'),'Opt-in typed pipe API is required')
        return m

    def api(self):
        m=self.module();from runtime import sdk_win32 as w
        kernel=PipeKernel(w);api=object.__new__(m.BootstrapApi)
        api._last_error=lambda:kernel.error
        api._update=kernel.base_update;api._create=kernel.base_create
        api._close=kernel.close;api._handle_info=kernel.handle_info
        api._bind_capture(kernel)
        return m,w,kernel,api

    def prepare(self,api,w):
        cap=api._new_capture((99,(700,701),object()))
        api._capture_active=cap
        job=(w.H*1)(11);nul=(w.H*1)(10)
        api._update(1,0,0x2000D,C.byref(job),C.sizeof(job),None,None)
        api._update(1,0,0x20002,C.byref(nul),C.sizeof(nul),None,None)
        return cap

    def owned(self,cap):
        return NS(bootstrap_capture=cap,stdio=None,_attribute_initialized=False,
            attributes_released=True,_attribute_address=None,_buffers=[],stdio_released=True,
            local_cleanup_complete=True,host=70,job=11,identity=(700,701))

    def create(self,api,w):
        startup=w.StartupInfoEx();startup.startup.cb=C.sizeof(startup);startup.startup.flags=0x100
        startup.startup.stdin=startup.startup.stdout=startup.startup.stderr=10
        return api._create(None,None,None,None,True,0x08080404,None,None,C.byref(startup),None)

    def test_parent_reads_are_noninheritable_and_only_exact_writes_enter_startup(self):
        m,w,k,api=self.api();cap=self.prepare(api,w)
        self.assertEqual(k.inherited_list,[10,102,104])
        self.assertTrue(all(not k.inherited[h] for h in cap.reads))
        startup=w.StartupInfoEx();startup.startup.cb=C.sizeof(startup);startup.startup.flags=0x100
        startup.startup.stdin=startup.startup.stdout=startup.startup.stderr=10
        api._create(None,None,None,None,True,0x08080404,None,None,C.byref(startup),None)
        self.assertEqual(k.startup_handles,[10,102,104]);self.assertEqual(k.creation_flags,0x08080404)
        owned=self.owned(cap);self.assertTrue(api.release_launch_local(owned))
        self.assertEqual(set(k.closed),{102,104})
        self.assertTrue(api.close_capture(owned));self.assertEqual(set(k.closed),{101,102,103,104})

    def test_unreviewed_pointer_shapes_do_not_enter_the_typed_launch_seam(self):
        m,w,k,api=self.api();api._capture_active=api._new_capture((99,(700,701),object()))
        pointer=C.pointer(w.H(11))
        with self.assertRaises(w.NativeCallError):api._update(1,0,0x2000D,pointer,C.sizeof(w.H),None,None)

    def test_empty_available_never_calls_blocking_read_or_waits_for_eof(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap)
        api.release_launch_local(owned);k.broken=False
        self.assertTrue(api.drain_capture(owned,9.,lambda:1.))
        self.assertEqual(k.read_calls,0)
        self.assertFalse(api.drain_capture(owned,9.,lambda:1.,final=True))
        self.assertTrue(api.close_capture(owned))

    def test_stdout_and_stderr_are_separate_and_finish_as_closed_numbers(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap)
        self.create(api,w)
        k.data[101]=b'error NU1301: SYNTHETIC_OPAQUE\n';k.data[103]=b'error CS2012: SYNTHETIC_OPAQUE\n'
        api.release_launch_local(owned);self.assertTrue(api.drain_capture(owned,9.,lambda:1.,final=True))
        self.assertTrue(api.close_capture(owned));v=api.capture_result(owned)
        self.assertEqual(v['streams'][0]['codes'],[[1,1301,1]])
        self.assertEqual(v['streams'][1]['codes'],[[4,2012,1]])
        self.assertTrue(v['complete']);self.assertTrue(v['handlesClosed'])
        self.assertNotIn('SYNTHETIC_OPAQUE',str(v))

    def test_partial_pipe_creation_closes_every_acquired_handle(self):
        for fail_call in (1,2):
            m,w,k,api=self.api();k.fail_pipe=fail_call
            with self.assertRaises(w.NativeCallError):self.prepare(api,w)
            owned=self.owned(api._capture_active)
            api.release_launch_local(owned);self.assertTrue(api.close_capture(owned))
            self.assertEqual(set(k.closed),set(k.created))
            self.assertEqual(len(k.closed),len(set(k.closed)))

    def test_deadline_api_fault_and_close_failure_remain_explicit_failure(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap)
        api.release_launch_local(owned)
        self.assertFalse(api.drain_capture(owned,1.,lambda:1.))
        self.assertTrue(api.close_capture(owned));self.assertFalse(api.capture_result(owned)['complete'])
        m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap)
        api.release_launch_local(owned);k.peek_fault=True
        self.assertFalse(api.drain_capture(owned,9.,lambda:1.))
        k.close_failure=101;self.assertFalse(api.close_capture(owned))
        self.assertFalse(api.capture_result(owned)['handlesClosed'])

    def test_capture_record_rejects_unknown_fields_and_boolean_numeric_values(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);self.create(api,w);owned=self.owned(cap)
        api.release_launch_local(owned);api.drain_capture(owned,9.,lambda:1.,final=True);api.close_capture(owned)
        value=api.capture_result(owned);self.assertIs(m.validate_capture(value),value)
        for field,item in [('failureCode',False),('raw','SYNTHETIC_OPAQUE')]:
            with self.assertRaises(ValueError):m.validate_capture({**value,field:item})
        with self.assertRaises(ValueError):m.validate_capture({**value,'complete':False})

    def test_second_create_or_changed_flags_cannot_start_another_process(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);self.create(api,w)
        with self.assertRaises(w.NativeCallError):self.create(api,w)
        m,w,k,api=self.api();cap=self.prepare(api,w)
        s=w.StartupInfoEx();s.startup.cb=C.sizeof(s);s.startup.flags=0x100
        s.startup.stdin=s.startup.stdout=s.startup.stderr=10
        with self.assertRaises(w.NativeCallError):api._create(None,None,None,None,True,0,None,None,C.byref(s),None)
        self.assertFalse(cap.startup)

    def test_parent_read_inheritance_failure_is_rejected_and_released(self):
        m,w,k,api=self.api();api._set_inherit=lambda *args:True
        with self.assertRaises(w.NativeCallError):self.prepare(api,w)
        owned=self.owned(api._capture_active);api.release_launch_local(owned);api.close_capture(owned)
        self.assertEqual(set(k.closed),set(k.created))

    def test_attribute_delete_failure_keeps_the_extended_handle_list_storage_alive(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap)
        owned._attribute_initialized=True;owned._attribute_address=1
        def failed(address):raise RuntimeError('synthetic-delete-failure')
        api._delete=failed
        self.assertFalse(api.release_launch_local(owned))
        self.assertTrue(bool(cap.buffers),'A live attribute list must retain its supplied handle array')
        api._delete=lambda address:None
        self.assertTrue(api.release_launch_local(owned));self.assertFalse(cap.buffers)
        self.assertTrue(api.close_capture(owned))

    def test_zero_or_oversized_read_is_not_accepted_as_a_drain(self):
        for size in (0,999999):
            m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap);k.data[101]=b'owned'
            def read(handle,buffer,requested,count,overlapped):
                C.cast(count,C.POINTER(w.U32))[0]=size;return True
            api._read_pipe=read
            self.assertFalse(api.drain_capture(owned,9.,lambda:1.));api.close_capture(owned)
            self.assertFalse(api.capture_result(owned)['complete'])

    def test_native_call_returning_after_deadline_cannot_be_success(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap);k.data[101]=b'owned'
        clock=[1.];original=api._read_pipe
        def late(*args):
            result=original(*args);clock[0]=9.;return result
        api._read_pipe=late
        self.assertFalse(api.drain_capture(owned,9.,lambda:clock[0]));api.close_capture(owned)
        self.assertEqual(api.capture_result(owned)['failureCode'],1)

    def test_unknown_code_and_total_pipe_byte_overflow_remain_closed(self):
        for data,can_continue in [(b'error UNKNOWN12: SYNTHETIC_OPAQUE\n',True),(b'x'*(1024*1024+1),False)]:
            m,w,k,api=self.api();cap=self.prepare(api,w);owned=self.owned(cap);k.data[101]=data
            self.assertEqual(api.drain_capture(owned,9.,lambda:1.),can_continue);api.close_capture(owned)
            self.assertFalse(api.capture_result(owned)['complete'])

    def test_unknown_or_duplicate_numeric_code_records_are_rejected(self):
        m,w,k,api=self.api();cap=self.prepare(api,w);self.create(api,w);owned=self.owned(cap)
        api.release_launch_local(owned);api.drain_capture(owned,9.,lambda:1.,final=True);api.close_capture(owned)
        for rows in [[[False,1301,1]],[[9,1301,1]],[[1,1301,1],[1,1301,1]],[[1,1301,'SYNTHETIC_OPAQUE']]]:
            value=copy.deepcopy(api.capture_result(owned));value['streams'][0]['codes']=rows;value['streams'][0]['codeObserved']=True
            with self.assertRaises(ValueError):m.validate_capture(value)


class ControllerCaptureTests(unittest.TestCase):
    def test_windows_pipe_preflight_is_required_before_any_capture_can_be_trusted(self):
        from runtime import controller
        self.assertTrue(hasattr(controller,'bootstrap_pipe_preflight'),
                        'The explicit capture mode requires its own actual-Windows pipe preflight')

    def test_preflight_requires_separate_expected_codes_and_complete_cleanup(self):
        from runtime import controller
        stream=lambda rows:{'complete':True,'unknown':False,'overflow':False,'codeObserved':bool(rows),'codes':rows,'unknownShapes':[]}
        capture={'schemaVersion':1,'complete':True,'failureCode':0,'streams':[stream([[1,900001,1]]),stream([[4,900002,1]])],
            'handlesClosed':True,'parentReadsNoninheritable':True,'exactChildHandleList':True,'startupObserved':True}
        positive={'completed':True,'cleanupProved':True,'forcedCleanup':False,'children':[
            {'exitObserved':True,'exitCode':0,'identityRechecked':True,'bootstrapErrorCodes':capture}]}
        calls=[]
        class Spy:
            value=positive
            def __init__(self,api):pass
            def run(self,specs,deadline,**options):calls.append(options);return self.value
        with patch.object(controller,'Runner',Spy):
            self.assertIs(controller.bootstrap_pipe_preflight(object(),Path('/owned'),{},10**12),positive)
            self.assertEqual(calls,[{'bootstrap_capture':True}])
            bad=copy.deepcopy(positive);bad['children'][0]['bootstrapErrorCodes']['streams'].reverse();Spy.value=bad
            with self.assertRaises(controller.ProbeFailure):controller.bootstrap_pipe_preflight(object(),Path('/owned'),{},10**12)
            bad=copy.deepcopy(positive);bad['cleanupProved']=False;Spy.value=bad
            with self.assertRaises(controller.ProbeFailure):controller.bootstrap_pipe_preflight(object(),Path('/owned'),{},10**12)

    def test_default_probe_run_does_not_enable_capture_and_opt_in_is_explicit(self):
        from runtime import controller
        for enabled in (False,True):
            calls=[]
            class Spy:
                def __init__(self,api):pass
                def run(self,specs,deadline,**options):
                    calls.append(options);return {'completed':True,'children':[{'exitCode':0}]}
            p=object.__new__(controller.Probe);p.phase=0;p.overall=10**12;p.host=Path('owned.exe')
            p.environment={};p.api=object();p.report={'phases':[]};p.bootstrap_capture=enabled
            with patch.object(controller,'Runner',Spy):p.run(['restore','owned.sln'],Path('/owned'),bootstrap=True)
            self.assertEqual(calls,[{'bootstrap_capture':True}] if enabled else [{}])

    def test_held_descendant_original_deadline_and_capture_failure_stay_fail_closed(self):
        from runtime import bounded
        import test_runtime as legacy
        class Api(legacy.FakeApi):
            def launch_captured(self,*args,**kwargs):return self.launch(*args,**kwargs)
            def drain_capture(self,*args,**kwargs):return True
            def close_capture(self,job):return True
            def capture_result(self,job):
                row={'complete':True,'unknown':False,'overflow':False,'codeObserved':False,'codes':[],'unknownShapes':[]}
                return {'schemaVersion':1,'complete':True,'failureCode':0,'streams':[row,dict(row)],
                    'handlesClosed':True,'parentReadsNoninheritable':True,'exactChildHandleList':True,'startupObserved':True}
        clock=legacy.Clock();api=Api(clock,True,True)
        value=bounded.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],'owned',legacy.explicit_environment(bounded))],3.,bootstrap_capture=True)
        self.assertFalse(value['completed']);self.assertTrue(value['cleanupProved'])
        self.assertTrue(value['forcedCleanup']);self.assertLessEqual(clock.now,3.)
        self.assertEqual(api.closed,{11,12,13,99})


class NativeFunction:
    def __init__(self,call):self.call=call
    def __call__(self,*args):return self.call(*args)


class PipeKernel:
    def __init__(self,w):
        self.w=w;self.error=0;self.next=100;self.inherited={10:True};self.closed=[];self.created=[]
        self.data={};self.broken=True;self.read_calls=0;self.pipe_calls=0;self.fail_pipe=0
        self.peek_fault=False;self.close_failure=0;self.inherited_list=[]
        self.CreatePipe=NativeFunction(self.pipe);self.SetHandleInformation=NativeFunction(self.set_info)
        self.PeekNamedPipe=NativeFunction(self.peek);self.ReadFile=NativeFunction(self.read)

    def pipe(self,r,w,security,size):
        self.pipe_calls+=1
        for p in (r,w):
            self.next+=1;C.cast(p,C.POINTER(self.w.H))[0]=self.next
            self.inherited[self.next]=True;self.created.append(self.next)
        self.data[self.next-1]=b''
        return self.pipe_calls!=self.fail_pipe
    def set_info(self,h,mask,flags):self.inherited[int(h)]=bool(flags&1);return True
    def handle_info(self,h,flags):C.cast(flags,C.POINTER(self.w.U32))[0]=int(self.inherited.get(int(h),False));return True
    def close(self,h):
        if int(h)==self.close_failure:return False
        self.closed.append(int(h));return True
    def base_update(self,attributes,flags,kind,value,size,previous,result):
        if kind==0x20002:self.inherited_list=[int(C.cast(value,C.POINTER(self.w.H))[i]) for i in range(size//C.sizeof(self.w.H))]
        return True
    def base_create(self,*args):
        s=C.cast(args[8],C.POINTER(self.w.StartupInfoEx)).contents.startup
        self.startup_handles=[int(s.stdin),int(s.stdout),int(s.stderr)];self.creation_flags=args[5];return True
    def peek(self,h,buffer,size,read,available,left):
        if self.peek_fault:self.error=5;return False
        data=self.data[int(h)]
        if not data and self.broken:self.error=109;return False
        C.cast(available,C.POINTER(self.w.U32))[0]=len(data);return True
    def read(self,h,buffer,size,count,overlapped):
        self.read_calls+=1;data=self.data[int(h)][:size];self.data[int(h)]=self.data[int(h)][size:]
        C.memmove(buffer,data,len(data));C.cast(count,C.POINTER(self.w.U32))[0]=len(data);return True


if __name__=='__main__':unittest.main()
