"""Synthetic metadata and lifetime boundaries; never Windows menu input."""
import ctypes as C
import importlib.util
from pathlib import Path
import sys
import os
import weakref
from types import SimpleNamespace as NS
import unittest
import uuid

SOURCE=Path(__file__).resolve().parents[1]/'e2e/native_menu_msaa_hit.py'


def load_helper():
    if not SOURCE.is_file(): return None
    spec=importlib.util.spec_from_file_location('native_menu_msaa_hit_under_test',SOURCE)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


class Guid(C.Structure):
    _fields_=[('bytes',C.c_ubyte*16)]
    def __init__(self,value):
        super().__init__();C.memmove(C.addressof(self),uuid.UUID(value).bytes_le,16)


class WorkerGuid(Guid):
    """Only the worker models comtypes' CLSIDFromString text boundary."""
    def __init__(self,value):
        if (type(value) is not str or len(value)!=38 or value[0]!='{' or value[-1]!='}'
                or str(uuid.UUID(value))!=value[1:-1].lower()):
            raise ValueError('Synthetic worker CLSID format rejected')
        super().__init__(value)


def win32_guid_constructor(ole):
    """Bind only CLSIDFromString on the caller's stdcall WinDLL library."""
    class NativeGuid(C.Structure):
        _fields_=[('Data1',C.c_uint32),('Data2',C.c_uint16),('Data3',C.c_uint16),('Data4',C.c_ubyte*8)]
        def __init__(self,value):
            super().__init__()
            if type(value) is not str:raise ValueError('Native CLSID requires Unicode text')
            result=parse(value,C.byref(self))
            if type(result) is not int or result!=0:raise ValueError('Native CLSID parse failed')
    parse=ole.CLSIDFromString
    parse.argtypes,parse.restype=(C.c_wchar_p,C.POINTER(NativeGuid)),C.c_int32
    return NativeGuid


class Win32GuidFactoryTests(unittest.TestCase):
    def setUp(self):
        self.factory=globals().get('win32_guid_constructor')
        self.assertTrue(callable(self.factory),'The dependency-free Win32 CLSID constructor is missing')
        self.calls=[]
        class Parser:
            argtypes=restype=None
            result=0
            def __call__(parser,text,output):
                self.calls.append(1)
                if type(parser.result) is not int or parser.result!=0:return parser.result
                value=WorkerGuid(text)
                C.memmove(output,C.addressof(value),16)
                return 0
        self.parser=Parser()
        self.guid=self.factory(NS(CLSIDFromString=self.parser))

    def test_guid_layout_and_native_parser_declaration_are_exact(self):
        self.assertEqual(C.sizeof(self.guid),16)
        self.assertEqual(tuple(getattr(self.guid,name).offset for name in ('Data1','Data2','Data3','Data4')),(0,4,6,8))
        self.assertTrue(self.parser.argtypes==(C.c_wchar_p,C.POINTER(self.guid)))
        self.assertTrue(self.parser.restype is C.c_int32)
        self.assertEqual(self.calls,[])

    def test_both_worker_calls_use_the_same_dependency_free_constructor(self):
        fixture=WorkerTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.sdk.Guid=self.guid
        result=fixture.run_worker()
        self.assertEqual(result['localMatch'],1)
        self.assertEqual((result['patternAttempted'],result['queryAttempted']),(1,1))
        self.assertEqual(self.calls,[1,1]);self.assertEqual(result['cleanupError'],0)

    def test_failed_or_non_hresult_result_rejects_without_rendering_argument(self):
        value='{828055ad-355b-4435-86d5-3b51c14a9b1b}'
        for result in (-2147467259,1,None,True,False):
            self.parser.result=result
            with self.subTest(code=type(result).__name__),self.assertRaises(ValueError):self.guid(value)

    def test_non_unicode_argument_is_rejected_before_native_parser(self):
        class Private:
            def __str__(self):raise AssertionError('Argument text must not be read')
            def __repr__(self):raise AssertionError('Argument representation must not be read')
        with self.assertRaises(ValueError):self.guid(Private())
        self.assertEqual(self.calls,[])

    def test_windows_unit_body_uses_stdcall_loader_without_optional_comtypes(self):
        loads=[];original_import=__import__
        def load(name):
            self.assertTrue(name=='ole32');loads.append(1)
            return NS(CLSIDFromString=self.parser)
        def bounded_import(name,*args,**kwargs):
            if name=='comtypes' or name.startswith('comtypes.'):
                raise AssertionError('Unit-stage CLSID test must not require optional comtypes')
            return original_import(name,*args,**kwargs)
        case=WindowsClsidParserTests(methodName='test_worker_constructs_both_guids_with_actual_win32_parser_without_provider_or_input')
        self.addCleanup(case.doCleanups)
        from unittest.mock import patch
        with patch.object(C,'WinDLL',load,create=True),patch('builtins.__import__',bounded_import):
            case.test_worker_constructs_both_guids_with_actual_win32_parser_without_provider_or_input()
        self.assertEqual(loads,[1]);self.assertEqual(self.calls,[1,1])


class Payload(C.Union):
    _fields_=[('VT_I4',C.c_int32),('c_void_p',C.c_void_p),('words',C.c_uint64*2)]


class Variant(C.Structure):
    _anonymous_=()
    _fields_=[('vt',C.c_uint16),('reserved',C.c_uint16*3),('_',Payload)]
    @property
    def value(self): raise AssertionError('VARIANT payload conversion is forbidden')


def sdk_fixture():
    def method(name,args=(),flags=(),restype=C.c_int32,idl=()):
        return NS(restype=restype,name=name,argtypes=args,
            paramflags=None if flags is None else tuple((value,'arg') for value in flags),
            idlflags=idl,doc=None)
    def pointer(interface):
        return type('ComPointer',(C.c_void_p,),{'__com_interface__':interface})
    class Unknown: pass
    Unknown._iid_=Guid('00000000-0000-0000-c000-000000000046')
    Unknown._methods_=[method('QueryInterface',[C.POINTER(Guid),C.POINTER(C.c_void_p)],None),
        method('AddRef',(),None,C.c_uint32),method('Release',(),None,C.c_uint32)]
    class Dispatch(Unknown): pass
    Dispatch._iid_=Guid('00020400-0000-0000-c000-000000000046')
    Dispatch._methods_=[method(name) for name in ('GetTypeInfoCount','GetTypeInfo','GetIDsOfNames','Invoke')]
    class Accessible(Dispatch): pass
    Accessible._iid_=Guid('618736e0-3c3d-11cf-810c-00aa00389b71')
    names=('get_accParent','get_accChildCount','get_accChild','get_accName','get_accValue',
        'get_accDescription','get_accRole','get_accState','get_accHelp','get_accHelpTopic',
        'get_accKeyboardShortcut','get_accFocus','get_accSelection','get_accDefaultAction',
        'accSelect','accLocation','accNavigate','accHitTest','accDoDefaultAction','put_accName','put_accValue')
    Accessible._methods_=[method(name) for name in names]
    Accessible._methods_[17]=method('accHitTest',(C.c_int32,C.c_int32,C.POINTER(Variant)),(1,1,10))
    class Element(Unknown): pass
    Element._iid_=Guid('d22108aa-8ac5-49a5-837b-37bbb3d7591e')
    Element._methods_=[method('GetCurrentPatternAs',(C.c_int32,C.POINTER(Guid),C.POINTER(C.c_void_p)),(1,1,10))]
    class Legacy(Unknown): pass
    Legacy._iid_=Guid('828055ad-355b-4435-86d5-3b51c14a9b1b')
    accptr=pointer(Accessible);elementptr=pointer(Element)
    Legacy._methods_=[method('_get_CurrentChildId',(C.POINTER(C.c_int32),),(10,),idl=('propget',)),
        method('GetIAccessible',(C.POINTER(accptr),),(10,))]
    class Client(Unknown): pass
    Client._iid_=Guid('30cbe57d-d9d0-452a-ab13-7ac5ac4825ee')
    Client._methods_=[method('ElementFromIAccessible',(accptr,C.c_int32,C.POINTER(elementptr)),(1,1,10)),
        method('CompareElements',(elementptr,elementptr,C.POINTER(C.c_int32)),(1,1,10))]
    return dict(client_interface=Client,element_interface=Element,legacy_interface=Legacy,
        accessible_interface=Accessible,guid_type=Guid,hresult_type=C.c_int32,variant_type=Variant,
        function_factory=C.CFUNCTYPE)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.helper=load_helper()
        self.assertIsNotNone(self.helper,'Owned MSAA point helper is missing')
        self.sdk=sdk_fixture()

    def build(self): return self.helper.SdkAbi(**self.sdk)

    def test_slots_include_iunknown_and_idispatch_without_duplicate_inherited_lists(self):
        abi=self.build()
        self.assertEqual(abi.slots['hit_test'],24)
        self.assertEqual(abi.slots['query'],0);self.assertEqual(abi.slots['release'],2)
        self.assertEqual(abi.slots['pattern'],3)
        self.assertEqual(abi.slots['child_id'],3)

    def test_iunknown_list_arguments_and_none_paramflags_are_supported(self):
        abi=self.build()
        self.assertEqual(abi.slots['release'],2)

    def test_custom_c_void_com_pointer_interface_is_checked(self):
        self.build()
        item=self.sdk['legacy_interface']._methods_[1]
        item.argtypes=(C.POINTER(C.c_void_p),)
        with self.assertRaises(ValueError):self.build()

    def test_wrong_iid_is_rejected_before_any_native_call(self):
        self.sdk['element_interface']._iid_=Guid('00000000-0000-0000-0000-000000000000')
        with self.assertRaises(ValueError):self.build()

    def test_hresult_bool_guid_depth_and_output_direction_are_exact(self):
        for change in ('hresult','bool16','guid_depth','out_flags','getter_name'):
            with self.subTest(change=change):
                self.sdk=sdk_fixture()
                if change=='hresult':self.sdk['legacy_interface']._methods_[0].restype=C.c_int16
                elif change=='bool16':self.sdk['client_interface']._methods_[1].argtypes=(
                    *self.sdk['client_interface']._methods_[1].argtypes[:2],C.POINTER(C.c_int16))
                elif change=='guid_depth':self.sdk['element_interface']._methods_[0].argtypes=(
                    C.c_int32,Guid,C.POINTER(C.c_void_p))
                elif change=='out_flags':self.sdk['legacy_interface']._methods_[1].paramflags=((1,'arg'),)
                else:self.sdk['legacy_interface']._methods_[0].name='CurrentChildId'
                with self.assertRaises(ValueError):self.build()

    def test_duplicate_method_and_wrong_variant_layout_are_rejected(self):
        self.sdk['legacy_interface']._methods_.append(self.sdk['legacy_interface']._methods_[1])
        with self.assertRaises(ValueError):self.build()
        self.sdk=sdk_fixture()
        class WrongVariant(C.Structure): _fields_=[('vt',C.c_uint16)]
        self.sdk['variant_type']=WrongVariant
        with self.assertRaises(ValueError):self.build()

    def test_float32_is_not_hresult_pattern_id_or_bool(self):
        for key in ('hresult','pattern','bool'):
            with self.subTest(key=key):
                self.sdk=sdk_fixture()
                if key=='hresult':self.sdk['element_interface']._methods_[0].restype=C.c_float
                elif key=='pattern':self.sdk['element_interface']._methods_[0].argtypes=(
                    C.c_float,*self.sdk['element_interface']._methods_[0].argtypes[1:])
                else:self.sdk['client_interface']._methods_[1].argtypes=(
                    *self.sdk['client_interface']._methods_[1].argtypes[:2],C.POINTER(C.c_float))
                with self.assertRaises(ValueError):self.build()

    def test_raw_hresult_return_does_not_use_hresult_checker(self):
        class HResult(C.c_int32):
            @staticmethod
            def _check_retval_(value):raise AssertionError('HRESULT checker must not run')
        for interface in ('element_interface','legacy_interface','client_interface','accessible_interface'):
            for method in self.sdk[interface]._methods_:
                if method.name!='Release':method.restype=HResult
        self.sdk['hresult_type']=HResult
        self.assertIs(self.build().signatures['pattern'][0],C.c_int32)

    def test_native_borrowed_refs_are_typed_and_nonnull_without_querying_them(self):
        abi=self.build()
        class DerivedClient(self.sdk['client_interface']):pass
        DerivedClient._iid_=Guid('00000000-0000-0000-0000-000000000001')
        def ref(interface,value):
            pointer=type('SourcePointer',(C.c_void_p,),{'__com_interface__':interface})
            return pointer(value)
        source=self.helper.MsaaHitSource(client=ref(DerivedClient,9),file=ref(self.sdk['element_interface'],1),
            fresh_target=ref(self.sdk['element_interface'],2),retained_target=ref(self.sdk['element_interface'],3),
            negative_refs=(ref(self.sdk['element_interface'],4),ref(self.sdk['element_interface'],5)),
            shell_handle=20,engine_handle=21)
        self.assertTrue(abi.matches_source(source))
        for value in (object(),C.c_void_p(9),ref(DerivedClient,0)):
            replacement=self.helper.MsaaHitSource(client=value,file=source.file,
                fresh_target=source.fresh_target,retained_target=source.retained_target,
                negative_refs=source.negative_refs,shell_handle=20,engine_handle=21)
            self.assertFalse(abi.matches_source(replacement))


class FakeKernel:
    synthetic=True
    def __init__(self):
        self.now=10.;self.mta=True;self.finished=True;self.exit_code=0
        self.duplicate_failure=False;self.close_failure=False;self.start_failure=False
        self.identity_failure=False;self.worker_failure=False;self.callback=None
        self.callback_identity_failure=False;self.controller_pid=500
        self.closed=[];self.duplicates=[];self.callback_before_return=True
    def clock(self):return self.now
    def apartment(self):return self.mta
    def duplicate(self,handle,pid,birth):
        if self.duplicate_failure:raise RuntimeError('Synthetic duplicate failure')
        duplicate=handle+100;self.duplicates.append(duplicate);return duplicate
    def check_process(self,handle,pid,birth):return not self.identity_failure
    def start(self,callback):
        if self.start_failure:raise RuntimeError('Synthetic startup failure')
        self.callback=callback
        if self.callback_before_return:callback()
        return (301,44,55)
    def thread_identity(self,handle,tid,birth):return not self.identity_failure
    def callback_identity(self,handle,tid,birth):return not self.callback_identity_failure and (tid,birth)==(44,55)
    def wait(self,handle,milliseconds):
        self.now+=.001
        return self.finished
    def exit(self,handle):return self.exit_code
    def close(self,handle):
        self.closed.append(handle)
        return not self.close_failure
    def worker(self,source,scope,sdk):
        if self.worker_failure:raise RuntimeError('Synthetic worker failure')
        return sdk_fixture_worker()
    def boundary_worker(self):return load_helper().run_native_boundary(FakePlatform())


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.helper=load_helper();self.assertTrue(hasattr(self.helper,'begin_msaa_hit'))
        self.kernel=FakeKernel()
        self.scope=self.helper.MsaaHitScope(scope_id=7,engine_pid=8,engine_birth=9,
            shell_pid=10,shell_birth=11,parent_hwnd=12,child_hwnd=13,x=14,y=15)
        self.source=self.helper.MsaaHitSource(client=object(),file=object(),
            fresh_target=object(),retained_target=object(),negative_refs=(object(),object()),
            shell_handle=20,engine_handle=21)

    def begin(self,deadline=15):
        return self.helper.begin_msaa_hit(self.source,self.scope,object(),deadline,_kernel=self.kernel)

    def tearDown(self):
        if not self.helper:return
        capsule=getattr(self.helper,'_active',None)
        if capsule:
            self.kernel.finished=True
            if self.kernel.callback:self.kernel.callback()
            self.kernel.close_failure=False;self.kernel.identity_failure=False
            capsule.retire(20)

    def test_callback_before_start_returns_keeps_refs_and_actual_exit_witness(self):
        lease=self.begin();result=lease.wait()
        self.assertEqual(result['localMatch'],1)
        self.assertEqual(result['nativeExit'],1);self.assertEqual(result['threadClosed'],1)
        self.assertEqual(result['acceptanceEligible'],0)
        self.assertEqual(sorted(self.kernel.closed),[120,121,301])
        self.assertNotIn(20,self.kernel.closed);self.assertNotIn(21,self.kernel.closed)
        self.assertFalse(lease.pending)

    def test_sta_or_expired_deadline_does_not_duplicate_or_start(self):
        for reason in ('sta','expired'):
            with self.subTest(reason=reason):
                self.kernel.mta=reason!='sta'
                lease=self.begin(9 if reason=='expired' else 15)
                self.assertEqual(lease.wait()['localKnown'],0)
                self.assertEqual(self.kernel.duplicates,[])
                self.assertIsNone(self.kernel.callback)

    def test_done_does_not_mean_native_exit_and_one_pending_blocks_new_scope(self):
        self.kernel.finished=False
        lease=self.begin();result=lease.wait()
        self.assertEqual(result['localMatch'],0);self.assertTrue(lease.pending)
        self.assertEqual(self.kernel.closed,[])
        second=self.begin();self.assertEqual(second.wait()['stageCode'],2)
        self.assertEqual(len(self.kernel.duplicates),2)
        self.kernel.finished=True
        retired=lease.retire(20)
        self.assertEqual(retired['localMatch'],0)
        self.assertFalse(lease.pending)

    def test_late_or_nonzero_exit_cannot_become_known(self):
        for reason in ('late','exit'):
            with self.subTest(reason=reason):
                self.kernel=FakeKernel()
                if reason=='exit':self.kernel.exit_code=86
                lease=self.begin()
                if reason=='late':self.kernel.now=16
                result=lease.wait()
                self.assertEqual(result['localMatch'],0)
                self.assertEqual(result['localKnown'],0)

    def test_final_reference_retirement_cannot_make_a_late_result_known(self):
        lease=self.begin();original=lease._clear
        def late():original();self.kernel.now=16
        lease._clear=late
        self.assertEqual(lease.wait()['localKnown'],0)

    def test_duplicate_and_start_errors_release_only_owned_handles(self):
        for reason in ('duplicate','start'):
            with self.subTest(reason=reason):
                self.kernel=FakeKernel();setattr(self.kernel,reason+'_failure',True)
                result=self.begin().wait()
                self.assertEqual(result['localMatch'],0)
                self.assertNotIn(20,self.kernel.closed);self.assertNotIn(21,self.kernel.closed)
                self.assertEqual(len(self.kernel.closed),0 if reason=='duplicate' else 2)

    def test_cleanup_failure_blocks_success_and_keeps_capsule(self):
        lease=self.begin();self.kernel.close_failure=True
        result=lease.wait()
        self.assertEqual(result['localKnown'],0);self.assertTrue(lease.pending)
        self.kernel.close_failure=False
        self.assertFalse(lease.retire(20)['pending'])

    def test_baseexception_in_worker_is_fenced_and_cannot_qualify(self):
        self.kernel.worker=lambda *args:(_ for _ in ()).throw(KeyboardInterrupt())
        lease=self.begin();result=lease.wait()
        self.assertEqual(result['localKnown'],0)
        self.assertEqual(result['workerException'],1)

    def test_worker_cleanup_unknown_retains_capsule_even_after_native_exit(self):
        self.kernel.worker=lambda *args:dict(sdk_fixture_worker(),localKnown=0,localMatch=0,workerCleanup=0)
        lease=self.begin();result=lease.wait()
        self.assertEqual(result['localMatch'],0)
        self.assertTrue(lease.pending)
        self.assertTrue(lease.retire(20)['pending'])

    def test_process_close_error_cannot_hide_unknown_worker_cleanup_on_retire(self):
        self.kernel.worker=lambda *args:dict(sdk_fixture_worker(),localKnown=0,localMatch=0,workerCleanup=0)
        original=self.kernel.close
        def close(handle):return False if handle in (120,121) else original(handle)
        self.kernel.close=close
        lease=self.begin();self.assertTrue(lease.wait()['pending'])
        self.kernel.close=original
        self.assertTrue(lease.retire(20)['pending'])

    def test_exception_after_process_close_never_retries_potentially_reused_handle(self):
        original=self.kernel.close;attempts=[]
        def close(handle):
            attempts.append(handle);result=original(handle)
            if handle==120:raise KeyboardInterrupt()
            return result
        self.kernel.close=close
        lease=self.begin();self.assertTrue(lease.wait()['pending'])
        self.kernel.close=original;lease.retire(20)
        self.assertTrue(lease.pending)
        self.assertEqual(self.kernel.closed.count(120),1)

    def test_exception_after_thread_close_never_retries_potentially_reused_handle(self):
        original=self.kernel.close
        def close(handle):
            result=original(handle)
            if handle==301:raise KeyboardInterrupt()
            return result
        self.kernel.close=close
        lease=self.begin();self.assertTrue(lease.wait()['pending'])
        self.kernel.close=original;lease.retire(20)
        self.assertTrue(lease.pending);self.assertEqual(self.kernel.closed.count(301),1)

    def test_production_launch_is_disabled_until_finalization_fence_is_integrated(self):
        result=self.helper.begin_msaa_hit(self.source,self.scope,object(),15).wait()
        self.assertEqual(result['stageCode'],1)
        self.assertEqual(result['nativeAttempted'],0)

    def test_unobservable_start_keeps_source_and_owned_duplicate_handles(self):
        self.kernel.start_failure=True;self.kernel.start_uncertain=True
        lease=self.begin();result=lease.wait()
        self.assertTrue(lease.pending);self.assertEqual(result['localMatch'],0)
        self.assertIs(lease.source,self.source);self.assertEqual(self.kernel.closed,[])

    def test_identity_change_during_start_cannot_accept_or_release_live_callback(self):
        self.kernel.callback_before_return=False
        lease=self.begin();self.kernel.identity_failure=True
        result=lease.wait()
        self.assertTrue(lease.pending);self.assertEqual(result['localMatch'],0)
        self.assertEqual(self.kernel.closed,[])

    def test_output_schema_is_closed_and_always_contains_worker_failures(self):
        result=self.begin().wait()
        self.assertTrue(set(self.helper.worker_record())<=result.keys())
        self.assertTrue(all(type(value) is int for value in result.values()))
        self.assertEqual(result['globalHitSubstituted'],0)
        self.assertEqual((result['controllerPid'],result['threadId'],result['threadBirth']),(500,44,55))
        self.assertEqual((result['threadIdentity'],result['callbackIdentity'],result['exitCodeObserved']),(1,1,1))

    def test_native_callback_tid_birth_must_match_the_actual_thread(self):
        self.kernel.callback_identity_failure=True
        result=self.begin().wait()
        self.assertEqual(result['callbackIdentity'],0)
        self.assertEqual(result['localMatch'],0)

    def test_pending_capsule_keeps_full_provider_alive_until_actual_exit(self):
        class Provider:pass
        provider=Provider();reference=weakref.ref(provider)
        self.source=self.helper.MsaaHitSource(client=object(),file=object(),fresh_target=object(),
            retained_target=object(),negative_refs=(object(),object()),shell_handle=20,
            engine_handle=21,keepalive=(provider,))
        self.kernel.finished=False
        lease=self.begin();self.source=None;del provider
        self.assertIsNotNone(reference());self.assertTrue(lease.wait()['pending'])
        self.kernel.finished=True;lease.retire(20)
        self.assertIsNone(reference())

    def test_explicit_fence_registration_is_required_and_never_called_by_configuration(self):
        called=[]
        with self.assertRaises(ValueError):self.helper.configure_native_launch(pending_fence=None)
        callback=lambda:called.append(1)
        self.helper.configure_native_launch(pending_fence=callback)
        self.assertTrue(self.helper.NATIVE_LAUNCH_ENABLED);self.assertEqual(called,[])
        self.helper.configure_native_launch(pending_fence=callback)
        with self.assertRaises(ValueError):
            self.helper.configure_native_launch(pending_fence=lambda:None)
        self.assertEqual(called,[])


def sdk_fixture_worker():
    helper=load_helper()
    return dict(helper.worker_record(),localKnown=1,localMatch=1,workerCleanup=1)


class FakePlatform:
    def __init__(self):
        self.mta=True;self.dpi=True;self.restore=True;self.com_hr=0
        self.owns=True;self.clears=[];self.uninitializes=0;self.clear_hr=0
    def initialize(self):return self.com_hr
    def apartment(self):return self.mta
    def uninitialize(self):self.uninitializes+=1
    def guard(self):return self.owns
    def enter_dpi(self):return 88 if self.dpi else 0
    def physical_dpi(self):return self.dpi
    def leave_dpi(self,token):return token==88 and self.restore
    def clear_variant(self,value):
        self.clears.append(value._.c_void_p)
        if not self.clear_hr:value.vt=0;value._.c_void_p=None
        return self.clear_hr


class FakeCalls:
    Guid=WorkerGuid;Variant=Variant
    def __init__(self):
        self.releases=[];self.calls=[];self.fail={};self.child=0;self.variant_type=9
        self.wrong_file=False;self.wrong_target=False;self.negative_true=False
        self.release_throws=False
    def call(self,key,pointer,*args):
        self.calls.append(key)
        pointer=pointer.value if isinstance(pointer,C.c_void_p) else pointer
        if key=='release':
            self.releases.append(pointer)
            if self.release_throws:raise RuntimeError('Synthetic release failure')
            return 0
        if key=='pattern':args[2]._obj.value=101
        elif key=='child_id':args[0]._obj.value=self.child
        elif key=='accessible':args[0]._obj.value=102
        elif key=='from_accessible':args[2]._obj.value=103 if args[0]==102 else 105
        elif key=='query':args[1]._obj.value=104
        elif key=='hit_test':
            args[2]._obj.vt=self.variant_type;args[2]._obj._.c_void_p=106
        elif key=='compare':
            first,second=args[:2]
            if first==103:value=not self.wrong_file and second==1
            elif second in (2,3):value=not self.wrong_target
            else:value=self.negative_true
            args[2]._obj.value=int(value)
        return self.fail.get(key,0)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.helper=load_helper();self.assertTrue(hasattr(self.helper,'run_local_hit'))
        self.sdk=FakeCalls();self.platform=FakePlatform()
        self.source=self.helper.MsaaHitSource(client=9,file=1,fresh_target=2,
            retained_target=3,negative_refs=(4,5),shell_handle=20,engine_handle=21)
        self.scope=self.helper.MsaaHitScope(7,8,9,10,11,12,13,14,15)
    def run_worker(self):return self.helper.run_local_hit(self.source,self.scope,self.sdk,self.platform)

    def test_first_file_compare_records_encoding_without_restricting_bool_truth(self):
        fields=('firstCompareRawObserved','firstCompareRawBits','firstCompareIsZeroOrOne')
        for raw in (0,1,-1,2,-2**31,2**31-1):
            with self.subTest(raw=raw):
                self.sdk=FakeCalls();self.platform=FakePlatform();original=self.sdk.call
                def call(key,pointer,*args):
                    result=original(key,pointer,*args)
                    if key=='compare' and self.sdk.calls.count('compare')==1:args[2]._obj.value=raw
                    return result
                self.sdk.call=call;result=self.run_worker()
                self.assertEqual(tuple(result.get(key) for key in fields),(1,raw&0xffffffff,int(raw in (0,1))))
                self.assertEqual(self.sdk.calls[:5],['pattern','child_id','accessible','from_accessible','compare'])
                self.assertEqual(result['localMatch'],int(raw!=0))
                self.assertEqual(result['workerCleanup'],1);self.assertEqual(result['cleanupError'],0)
                self.assertEqual(result['referencesAcquired'],result['referencesReleased'])
                if raw==0:
                    self.assertEqual(result['compareAttempted'],1);self.assertEqual(result['hit_testAttempted'],0)
                    self.assertEqual(result['referencesReleased'],3)

    def test_first_file_compare_is_not_overwritten_by_later_target_or_negative_comparisons(self):
        for wrong_target in (False,True):
            self.sdk=FakeCalls();self.platform=FakePlatform();self.sdk.wrong_target=wrong_target
            result=self.run_worker()
            self.assertEqual(tuple(result.get(key) for key in
                ('firstCompareRawObserved','firstCompareRawBits','firstCompareIsZeroOrOne')),(1,1,1))
            self.assertGreater(result['compareCompleted'],1)
            self.assertEqual(result['localMatch'],int(not wrong_target))
            self.assertEqual(result['referencesAcquired'],result['referencesReleased'])

    def test_first_compare_hresult_failure_is_unobserved_even_when_output_was_written(self):
        self.sdk.fail['compare']=-2147467259
        result=self.run_worker()
        self.assertEqual(tuple(result.get(key) for key in
            ('firstCompareRawObserved','firstCompareRawBits','firstCompareIsZeroOrOne')),(0,0,0))
        self.assertEqual((result['compareAttempted'],result['compareCompleted']),(1,1))
        self.assertEqual(result['compareHresult'],0x80004005)
        self.assertEqual(result['localMatch'],0);self.assertEqual(result['workerCleanup'],1)
        self.assertEqual(result['referencesAcquired'],result['referencesReleased'])

    def test_failure_before_first_file_compare_leaves_all_three_fields_zero(self):
        self.sdk.fail['pattern']=-2147467259
        result=self.run_worker()
        self.assertEqual(tuple(result.get(key) for key in
            ('firstCompareRawObserved','firstCompareRawBits','firstCompareIsZeroOrOne')),(0,0,0))
        self.assertEqual(result['compareAttempted'],0);self.assertEqual(result['localMatch'],0)
        self.assertEqual(result['referencesAcquired'],result['referencesReleased'])

    def test_every_positive_comparison_accepts_all_nonzero_bool32_encodings(self):
        for raw in (1,-1,2,-2**31,2**31-1):
            with self.subTest(raw=raw):
                self.sdk=FakeCalls();self.platform=FakePlatform();original=self.sdk.call
                def call(key,pointer,*args):
                    result=original(key,pointer,*args)
                    if key=='compare' and args[1] in (1,2,3):args[2]._obj.value=raw
                    return result
                self.sdk.call=call;result=self.run_worker()
                self.assertEqual(result['localMatch'],1)
                self.assertEqual(result['targetFreshPositive'],1);self.assertEqual(result['targetRetainedPositive'],1)
                self.assertEqual(result['negativeCount'],result['negativeRejected'])
                self.assertEqual(result['referencesAcquired'],result['referencesReleased'])
                self.assertEqual(result['workerCleanup'],1)

    def test_each_positive_zero_and_each_negative_nonzero_still_reject(self):
        cases=[(ordinal,0) for ordinal in (1,2,3)]
        cases += [(ordinal,raw) for ordinal in (4,5) for raw in (1,-1,2,-2**31,2**31-1)]
        for ordinal,raw in cases:
            with self.subTest(ordinal=ordinal,raw=raw):
                self.sdk=FakeCalls();self.platform=FakePlatform();original=self.sdk.call
                def call(key,pointer,*args):
                    result=original(key,pointer,*args)
                    if key=='compare' and self.sdk.calls.count('compare')==ordinal:args[2]._obj.value=raw
                    return result
                self.sdk.call=call;result=self.run_worker()
                self.assertEqual(result['localMatch'],0);self.assertEqual(result['workerCleanup'],1)
                self.assertEqual(result['compareCompleted'],ordinal)
                self.assertEqual(result['referencesAcquired'],result['referencesReleased'])

    def test_nonzero_bool_true_does_not_hide_cleanup_failure(self):
        self.sdk.release_throws=True;original=self.sdk.call
        def call(key,pointer,*args):
            result=original(key,pointer,*args)
            if key=='compare' and args[1] in (1,2,3):args[2]._obj.value=-1
            return result
        self.sdk.call=call;result=self.run_worker()
        self.assertEqual(result['workerStage'],7)
        self.assertEqual(result['cleanupError'],1);self.assertEqual(result['workerCleanup'],0)
        self.assertEqual(result['localKnown'],0);self.assertEqual(result['localMatch'],0)

    def test_worker_clsid_constructor_rejects_bare_uuid_that_metadata_fixture_accepts(self):
        value=self.helper._IIDS['legacy']
        self.assertEqual(C.sizeof(Guid(value)),16)
        with self.assertRaises(ValueError):WorkerGuid(value)
        self.assertEqual(C.sizeof(WorkerGuid('{'+value+'}')),16)

    def test_both_worker_clsid_constructions_pass_the_strict_native_format_boundary(self):
        result=self.run_worker()
        self.assertEqual(result['localMatch'],1)
        self.assertEqual((result['patternAttempted'],result['queryAttempted']),(1,1))
        self.assertEqual(result['cleanupError'],0);self.assertEqual(result['workerCleanup'],1)

    def test_exact_file_roundtrip_target_positives_and_every_negative(self):
        result=self.run_worker()
        self.assertEqual(result['localMatch'],1);self.assertEqual(result['negativeCount'],2)
        self.assertEqual(result['referencesAcquired'],5)
        self.assertEqual(result['referencesReleased'],5)
        self.assertEqual(self.platform.clears,[106]);self.assertEqual(self.platform.uninitializes,1)
        self.assertFalse(any(value in (1,2,3,4,5,9) for value in self.sdk.releases))

    def test_failure_plus_nonnull_out_is_released_at_every_acquisition(self):
        for operation,acquired in (('pattern',1),('accessible',2),('from_accessible',3),('query',4)):
            with self.subTest(operation=operation):
                self.sdk=FakeCalls();self.platform=FakePlatform();self.sdk.fail[operation]=-2147467259
                result=self.run_worker()
                self.assertEqual(result['localMatch'],0)
                self.assertEqual(result['referencesAcquired'],acquired)
                self.assertEqual(result['referencesReleased'],acquired)
                self.assertEqual(result[operation+'Hresult'],0x80004005)

    def test_childid_wrong_file_wrong_target_or_negative_equality_fail_closed(self):
        for failure in ('child','wrong_file','wrong_target','negative_true'):
            with self.subTest(failure=failure):
                self.sdk=FakeCalls();self.platform=FakePlatform()
                setattr(self.sdk,failure,7 if failure=='child' else True)
                result=self.run_worker()
                self.assertEqual(result['localMatch'],0)
                self.assertEqual(result['workerCleanup'],1)

    def test_failed_hit_with_dispatch_variant_is_always_cleared(self):
        self.sdk.fail['hit_test']=-2147467259
        result=self.run_worker()
        self.assertEqual(result['localMatch'],0);self.assertEqual(self.platform.clears,[106])

    def test_unexpected_variant_is_not_read_as_text_and_is_cleared(self):
        self.sdk.variant_type=8
        result=self.run_worker()
        self.assertEqual(result['localMatch'],0);self.assertEqual(self.platform.clears,[106])

    def test_cleanup_errors_or_changed_mta_dpi_owner_make_proof_unknown(self):
        for failure in ('mta','dpi','restore','owns','clear_hr','release_throws'):
            with self.subTest(failure=failure):
                self.sdk=FakeCalls();self.platform=FakePlatform()
                if failure=='release_throws':self.sdk.release_throws=True
                else:setattr(self.platform,failure,-2147467259 if failure=='clear_hr' else False)
                result=self.run_worker()
                self.assertEqual(result['localMatch'],0)
                self.assertEqual(result['localKnown'],0)

    def test_s_false_cominit_still_balances_one_uninitialize(self):
        self.platform.com_hr=1
        self.assertEqual(self.run_worker()['localMatch'],1)
        self.assertEqual(self.platform.uninitializes,1)

    def test_cominit_failed_does_not_uninitialize_or_touch_provider(self):
        self.platform.com_hr=-2147417850
        self.assertEqual(self.run_worker()['localMatch'],0)
        self.assertEqual(self.platform.uninitializes,0);self.assertEqual(self.sdk.calls,[])

    def test_failed_physical_dpi_verification_still_restores_context(self):
        self.platform.physical_dpi=lambda:False
        result=self.run_worker()
        self.assertEqual(result['dpiEntered'],1);self.assertEqual(result['dpiRestored'],1)
        self.assertEqual(result['localMatch'],0);self.assertEqual(self.sdk.calls,[])

    def test_focus_or_source_change_after_com_calls_cannot_qualify(self):
        calls=[]
        def guard():calls.append(1);return len(calls)==1
        self.platform.guard=guard
        result=self.run_worker()
        self.assertEqual(result['processBefore'],1);self.assertEqual(result['processAfter'],0)
        self.assertEqual(result['localMatch'],0);self.assertEqual(result['workerCleanup'],1)

    def test_unexpected_exception_around_initialization_marks_cleanup_unknown(self):
        def initialize():raise KeyboardInterrupt()
        self.platform.initialize=initialize
        result=self.run_worker()
        self.assertEqual(result['localMatch'],0);self.assertEqual(result['workerCleanup'],0)


class RawCallTests(unittest.TestCase):
    def test_native_duplicate_stays_unacknowledged_until_lease_adopts_it(self):
        helper=load_helper();kernel=helper.WindowsKernel.__new__(helper.WindowsKernel)
        def duplicate(current,handle,target,out,access,inherit,options):
            out._obj.value=120;return 1
        kernel.kernel=NS(GetCurrentProcess=lambda:999,DuplicateHandle=duplicate)
        kernel.processes={};kernel.duplicate_unknown=False
        handle=kernel.duplicate(20,10,11)
        self.assertEqual(handle,120);self.assertTrue(kernel.duplicate_unknown)
        kernel.adopt_duplicate(handle)
        self.assertFalse(kernel.duplicate_unknown)

    def test_failed_hresult_is_returned_numerically_and_does_not_touch_variant_value(self):
        helper=load_helper();abi=helper.SdkAbi(**sdk_fixture())
        observed=[]
        prototype=C.CFUNCTYPE(C.c_int32,C.c_void_p,C.c_int32,C.c_void_p,C.c_void_p)
        @prototype
        def pattern(this,pattern_id,iid,out):
            observed.append(pattern_id)
            C.cast(out,C.POINTER(C.c_void_p))[0]=101
            return -2147467259
        table=(C.c_void_p*4)();table[abi.slots['pattern']]=C.cast(pattern,C.c_void_p).value
        instance=C.pointer(C.cast(table,C.POINTER(C.c_void_p)))
        output=C.c_void_p();guid=Guid('828055ad-355b-4435-86d5-3b51c14a9b1b')
        hr=abi.call('pattern',instance,10018,C.byref(guid),C.byref(output))
        self.assertEqual(hr&0xffffffff,0x80004005)
        self.assertEqual(output.value,101);self.assertEqual(observed,[10018])


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.helper=load_helper();self.assertTrue(hasattr(self.helper,'verify_native_thread_boundary'))
        self.kernel=FakeKernel()
    def verify(self,deadline=15):
        return self.helper.verify_native_thread_boundary(deadline,_kernel=self.kernel)
    def tearDown(self):
        capsule=getattr(self.helper,'_active',None)
        if capsule:
            self.kernel.finished=True;self.kernel.close_failure=False
            if self.kernel.callback:self.kernel.callback()
            capsule.retire(20)
    def test_actual_exit_witness_is_distinct_from_provider_and_acceptance(self):
        result=self.verify()
        self.assertEqual(result['nativeBoundaryPassed'],1)
        self.assertEqual(result['nativeBoundaryOnly'],1)
        self.assertEqual(result['localMatch'],0);self.assertEqual(result['acceptanceEligible'],0)
        self.assertEqual(self.kernel.closed,[301]);self.assertIsNone(self.helper.pending_msaa_hit())
    def test_unknown_exit_retains_registered_capsule_and_blocks_next_scope(self):
        self.kernel.finished=False
        self.assertEqual(self.verify()['nativeBoundaryPassed'],0)
        capsule=self.helper.pending_msaa_hit();self.assertIsNotNone(capsule)
        self.assertEqual(self.verify()['stageCode'],2)
        self.kernel.finished=True
        self.assertEqual(capsule.retire(20)['nativeBoundaryPassed'],0)
    def test_late_start_or_mta_failure_never_pass(self):
        self.kernel.mta=False
        self.assertEqual(self.verify()['nativeBoundaryPassed'],0)
        self.assertIsNone(self.kernel.callback)
        self.kernel.mta=True
        original=self.kernel.start
        def late(callback):
            result=original(callback);self.kernel.now=16;return result
        self.kernel.start=late
        self.assertEqual(self.verify()['nativeBoundaryPassed'],0)
    def test_default_never_starts_without_controller_finalization_fence(self):
        self.assertEqual(self.helper.verify_native_thread_boundary(15)['nativeAttempted'],0)

    def test_failed_physical_dpi_verification_cannot_pass_from_cleanup_alone(self):
        platform=FakePlatform();platform.physical_dpi=lambda:False
        self.kernel.boundary_worker=lambda:self.helper.run_native_boundary(platform)
        result=self.verify()
        self.assertEqual(result['workerCleanup'],1)
        self.assertEqual(result['nativeBoundaryPassed'],0)

    def test_registry_is_reserved_before_native_binding_can_reenter(self):
        self.helper.configure_native_launch(pending_fence=lambda:None)
        nested=[];self.kernel.finished=False
        def factory():
            nested.append(self.verify())
            return self.kernel
        self.helper.WindowsKernel=factory
        result=self.helper.verify_native_thread_boundary(15)
        self.assertEqual(nested[0]['stageCode'],2)
        self.assertEqual(result['pending'],1)


@unittest.skipUnless(os.name=='nt','Actual Windows SDK metadata only')
class WindowsMetadataTests(unittest.TestCase):
    def test_existing_generated_sdk_matches_used_raw_signatures(self):
        try:
            from comtypes import GUID,HRESULT
            from comtypes.automation import VARIANT
            from comtypes.gen import UIAutomationClient as UIA
        except ImportError:
            self.skipTest('Existing generated UIAutomationClient metadata unavailable')
        legacy=UIA.IUIAutomationLegacyIAccessiblePattern
        method=next(item for item in vars(legacy)['_methods_'] if item.name=='GetIAccessible')
        accessible=method.argtypes[0]._type_.__com_interface__
        abi=load_helper().SdkAbi(client_interface=UIA.IUIAutomation,
            element_interface=UIA.IUIAutomationElement,legacy_interface=legacy,
            accessible_interface=accessible,guid_type=GUID,hresult_type=HRESULT,
            variant_type=VARIANT,function_factory=C.WINFUNCTYPE)
        self.assertEqual(abi.slots['hit_test'],24)


@unittest.skipUnless(os.name=='nt','Actual Windows CLSIDFromString parser only; no input')
class WindowsClsidParserTests(unittest.TestCase):
    def test_worker_constructs_both_guids_with_actual_win32_parser_without_provider_or_input(self):
        fixture=WorkerTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.sdk.Guid=win32_guid_constructor(C.WinDLL('ole32'))
        result=fixture.run_worker()
        self.assertEqual(result['localMatch'],1)
        self.assertEqual((result['patternAttempted'],result['queryAttempted']),(1,1))
        self.assertEqual(result['cleanupError'],0);self.assertEqual(result['workerCleanup'],1)


@unittest.skipUnless(os.name=='nt','Actual Windows native thread only')
class WindowsNativeThreadTests(unittest.TestCase):
    def test_input_free_native_start_has_owned_handle_and_callback_birth_witness(self):
        # Use the canonical CLI module, whose explicit/atexit self-only fence can
        # see this lease. A fresh private test import has no lifecycle fence.
        helper=sys.modules.get('native_menu_msaa_hit')
        if helper is None or not helper.NATIVE_LAUNCH_ENABLED:
            self.skipTest('Controller finalization fence has not enabled native launch')
        self.assertIsNone(helper.pending_msaa_hit())
        result=helper.verify_native_thread_boundary(helper.time.monotonic()+5)
        self.assertEqual(result['nativeBoundaryPassed'],1)
        self.assertEqual(result['localMatch'],0);self.assertIsNone(helper.pending_msaa_hit())


if __name__=='__main__':unittest.main()
