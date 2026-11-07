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
    Element._methods_=[method('GetCurrentPatternAs',(C.c_int32,C.POINTER(Guid),C.POINTER(C.c_void_p)),(1,1,10)),
        method('_get_CurrentControlType',(C.POINTER(C.c_int32),),(10,),idl=('propget',))]
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

    def test_control_type_getter_requires_exact_sdk_name_type_output_depth_and_direction(self):
        for damage in ('name','propget','signed','width','float','depth','void','direction','hresult'):
            with self.subTest(damage=damage):
                self.sdk=sdk_fixture();getter=self.sdk['element_interface']._methods_[1]
                if damage=='name':getter.name='CurrentControlType'
                elif damage=='propget':getter.idlflags=()
                elif damage=='signed':getter.argtypes=(C.POINTER(C.c_uint32),)
                elif damage=='width':getter.argtypes=(C.POINTER(C.c_int16),)
                elif damage=='float':getter.argtypes=(C.POINTER(C.c_float),)
                elif damage=='depth':getter.argtypes=(C.POINTER(C.POINTER(C.c_int32)),)
                elif damage=='void':getter.argtypes=(C.c_void_p,)
                elif damage=='direction':getter.paramflags=((1,'controlType'),)
                else:getter.restype=C.c_int64
                with self.assertRaises(ValueError):self.build()

    def test_accessible_iunknown_prefix_is_validated_independently_of_element(self):
        import copy
        for damage in ('query-guid','query-out','query-flags','release-width'):
            with self.subTest(damage=damage):
                self.sdk=sdk_fixture();accessible=self.sdk['accessible_interface']
                dispatch,unknown=accessible.__bases__[0],accessible.__bases__[0].__bases__[0]
                prefix=type('AccessibleUnknown',(),dict(_iid_=unknown._iid_,
                    _methods_=copy.deepcopy(unknown._methods_)))
                dispatch=type('AccessibleDispatch',(prefix,),dict(_iid_=dispatch._iid_,_methods_=dispatch._methods_))
                self.sdk['accessible_interface']=type('Accessible',(dispatch,),dict(
                    _iid_=accessible._iid_,_methods_=accessible._methods_))
                query,_,release=prefix._methods_
                if damage=='query-guid':query.argtypes=(Guid,C.POINTER(C.c_void_p))
                elif damage=='query-out':query.argtypes=(C.POINTER(Guid),C.c_void_p)
                elif damage=='query-flags':query.paramflags=((1,'iid'),(10,'out'))
                else:release.restype=C.c_uint64
                with self.assertRaises(ValueError):self.build()

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
    def worker(self,source,scope,sdk,deadline):
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

    def test_worker_receives_original_absolute_deadline(self):
        observed=[]
        def worker(*args):observed.append(args);return sdk_fixture_worker()
        self.kernel.worker=worker;lease=self.begin(14.25);lease.wait()
        self.assertEqual(len(observed[0]),4)
        self.assertEqual(observed[0][-1],14.25)

    def test_closed_worker_schema_rejects_extra_missing_negative_and_noninteger_values(self):
        for damage in ('extra','missing','negative','bool','wide'):
            with self.subTest(damage=damage):
                def worker(*args):
                    result=sdk_fixture_worker()
                    if damage=='extra':result['rawPointer']=123
                    elif damage=='missing':result.pop('falseShadowStatus',None)
                    else:result['falseShadowChildBits']={'negative':-1,'bool':True,'wide':2**32}[damage]
                    return result
                self.kernel=FakeKernel();self.kernel.worker=worker;lease=self.begin();result=lease.wait()
                self.assertEqual(result['workerException'],1)
                self.assertEqual(result['localKnown'],0)
                self.helper._active=None

    def test_inflight_shadow_keeps_same_address_acquisitions_source_sdk_and_handles_until_exit(self):
        self.exercise_inflight_shadow('accessible_query')

    def test_inflight_control_type_getter_keeps_source_sdk_and_owned_refs_until_exit(self):
        result=self.exercise_inflight_shadow('control_type')
        self.assertEqual(result['falseShadowOriginalControlTypeObserved'],1)
        self.assertEqual(result['falseShadowOriginalControlType'],50011)
        self.assertEqual(result['falseShadowRoundTripControlTypeObserved'],0)

    def test_inflight_original_repeat_keeps_both_acquisitions_and_retains_false_after_exit(self):
        for key,releases in [('accessible',[203,301,301,202,201,103,102,101]),
                ('accessible_query',[301,203,301,301,202,201,103,102,101])]:
            with self.subTest(call=key):
                self.setUp()
                result=self.exercise_inflight_shadow(key,ordinal=3,expected_releases=releases)
                self.assertEqual(result.get('falseShadowOriginalRepeatAttempted'),1 if key=='accessible' else 2)
                self.assertEqual(result.get('falseShadowOriginalRepeatObserved'),0)

    def exercise_inflight_shadow(self,blocked_key,ordinal=2,expected_releases=None):
        import threading
        entered=threading.Event();release=threading.Event();sdk=FakeCalls();sdk.wrong_file=True
        platform=FakePlatform();platform.clock=self.kernel.clock;original=sdk.call
        def call(key,pointer,*args):
            hr=original(key,pointer,*args)
            if key==blocked_key and sdk.calls.count(key)==ordinal:
                entered.set()
                if not release.wait(2):raise RuntimeError('Synthetic wait exhausted')
            return hr
        sdk.call=call;self.kernel.finished=False;threads=[]
        def start(callback):
            def entry():
                try:callback()
                finally:self.kernel.finished=True
            thread=threading.Thread(target=entry,daemon=True);threads.append(thread);thread.start()
            return (301,44,55)
        self.kernel.start=start
        self.kernel.worker=lambda source,scope,owned_sdk,deadline:self.helper.run_local_hit(
            source,scope,owned_sdk,platform,deadline)
        lease=self.helper.begin_msaa_hit(self.source,self.scope,sdk,15.,_kernel=self.kernel)
        try:
            self.assertTrue(entered.wait(1));self.assertEqual(sdk.releases,[])
            self.kernel.now=16.
            result=lease.wait();self.assertEqual((result['pending'],result['localKnown']),(1,0))
            self.assertEqual(self.kernel.closed,[]);self.assertIs(lease.source,self.source);self.assertIs(lease.sdk,sdk)
            self.assertEqual(self.begin().wait()['stageCode'],2)
            self.assertEqual(len(self.kernel.duplicates),2)
        finally:
            release.set()
            for thread in threads:thread.join(1)
        self.assertFalse(threads[0].is_alive())
        result=lease.retire(20.)
        self.assertEqual((result['pending'],result['localKnown'],result['localMatch']),(0,0,0))
        self.assertEqual(result['falseShadowStatus'],2)
        self.assertEqual(sdk.releases,expected_releases if expected_releases is not None else [301,301,202,201,103,102,101])
        self.assertEqual(sorted(self.kernel.closed),[120,121,301])
        self.assertIsNone(lease.source);self.assertIsNone(lease.sdk)
        return result

    def test_retirement_or_late_collection_downgrades_completed_shadow_status(self):
        for late in ('retire','collection','clear'):
            with self.subTest(late=late):
                self.kernel=FakeKernel()
                self.kernel.worker=lambda *args:dict(sdk_fixture_worker(),falseShadowStarted=1,
                    falseShadowStatus=1,falseShadowIdentityObserved=1,falseShadowCanonicalEqual=1,
                    falseShadowOriginalRepeatObserved=1,falseShadowOriginalRepeatCanonicalEqual=1,
                    localKnown=0,localMatch=0)
                lease=self.begin()
                if late=='collection':self.kernel.now=16.
                if late=='clear':
                    original=lease._clear
                    def clear():original();self.kernel.now=16.
                    lease._clear=clear
                result=lease.retire(20.) if late=='retire' else lease.wait()
                self.assertEqual((result['falseShadowStatus'],result['falseShadowCanonicalEqual']),(0 if late=='retire' else 2,1))
                self.assertEqual((result['falseShadowOriginalRepeatObserved'],result['falseShadowOriginalRepeatCanonicalEqual']),(1,1))
                self.assertEqual((result['localKnown'],result['localMatch']),(0,0))

    def test_unknown_retirement_cannot_keep_completed_shadow_status(self):
        self.kernel.worker=lambda *args:dict(sdk_fixture_worker(),falseShadowStarted=1,
            falseShadowStatus=1,falseShadowIdentityObserved=1,falseShadowCanonicalEqual=1,
            falseShadowOriginalRepeatObserved=1,falseShadowOriginalRepeatCanonicalEqual=1,
            localKnown=0,localMatch=0)
        lease=self.begin();self.kernel.close_failure=True;result=lease.wait()
        self.assertEqual((result['pending'],result['falseShadowStatus']),(1,0))
        self.assertEqual((result['falseShadowOriginalRepeatObserved'],result['falseShadowOriginalRepeatCanonicalEqual']),(1,1))
        self.assertEqual(result['falseShadowCanonicalEqual'],1)
        self.assertIs(lease.source,self.source)
        self.kernel.close_failure=False
        self.assertEqual(lease.retire(20.)['localKnown'],0)

    def test_expired_collection_with_failed_handle_close_keeps_expiry_status_and_source(self):
        for close_target in ('thread','process'):
            with self.subTest(close_target=close_target):
                self.kernel=FakeKernel()
                self.kernel.worker=lambda *args:dict(sdk_fixture_worker(),falseShadowStarted=1,
                    falseShadowStatus=1,falseShadowIdentityObserved=1,falseShadowCanonicalEqual=1,
                    localKnown=0,localMatch=0)
                lease=self.begin();sdk=lease.sdk;original=self.kernel.close
                self.kernel.now=16.
                self.kernel.close=lambda handle:False if (handle==301)==(close_target=='thread') else original(handle)
                try:
                    result=lease.wait()
                    self.assertEqual((result['pending'],result['stageCode'],result['falseShadowStatus']),(1,10,2))
                    self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
                    self.assertEqual((result['falseShadowIdentityObserved'],result['falseShadowCanonicalEqual']),(1,1))
                    self.assertIs(lease.source,self.source);self.assertIs(lease.sdk,sdk)
                    self.assertEqual(self.begin().wait()['stageCode'],2)
                finally:
                    self.kernel.close=original
                    retired=lease.retire(20.)
                self.assertEqual((retired['pending'],retired['localKnown'],retired['localMatch']),(0,0,0))

    def test_clock_failure_during_pending_downgrade_returns_incomplete_and_keeps_source(self):
        self.kernel.worker=lambda *args:dict(sdk_fixture_worker(),falseShadowStarted=1,
            falseShadowStatus=1,falseShadowIdentityObserved=1,falseShadowCanonicalEqual=1,
            localKnown=0,localMatch=0)
        lease=self.begin();clock=self.kernel.clock;close=self.kernel.close;sdk=lease.sdk
        def failed_clock():raise KeyboardInterrupt('Synthetic clock failure')
        def failed_close(handle):self.kernel.clock=failed_clock;return False
        self.kernel.close=failed_close
        try:
            result=lease.wait()
            self.assertEqual((result['pending'],result['falseShadowStatus']),(1,0))
            self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
            self.assertIs(lease.source,self.source);self.assertIs(lease.sdk,sdk)
        finally:
            self.kernel.clock=clock;self.kernel.close=close
        self.assertEqual(lease.retire(20.)['localKnown'],0)

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
        self.now=10.
    def clock(self):return self.now
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
        self.shadow_child=0;self.canonical=(301,301);self.control_types=(50011,50011)
        self.repeat_accessible=203;self.repeat_canonical=301
    def call(self,key,pointer,*args):
        self.calls.append(key)
        pointer=pointer.value if isinstance(pointer,C.c_void_p) else pointer
        if key=='release':
            self.releases.append(pointer)
            if self.release_throws:raise RuntimeError('Synthetic release failure')
            return 0
        if key=='pattern':args[2]._obj.value=201 if pointer==103 else 101
        elif key=='child_id':args[0]._obj.value=self.shadow_child if pointer==201 else self.child
        elif key=='accessible':
            args[0]._obj.value=202 if pointer==201 else self.repeat_accessible if self.calls.count(key)>1 else 102
        elif key=='accessible_query':
            args[1]._obj.value=self.repeat_canonical if pointer==203 else self.canonical[int(pointer==202)]
        elif key=='control_type':args[0]._obj.value=self.control_types[int(pointer==103)]
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
    def run_worker(self):return self.helper.run_local_hit(self.source,self.scope,self.sdk,self.platform,15.)

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
                    self.assertEqual(result['referencesReleased'],9)

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


class FalseShadowTests(unittest.TestCase):
    setUp=WorkerTests.setUp
    run_worker=WorkerTests.run_worker

    def prepare(self):
        self.sdk=FakeCalls();self.platform=FakePlatform();self.sdk.wrong_file=True

    def assert_primary_false(self,result):
        self.assertEqual(tuple(result[key] for key in ('workerStage','fileRoundTrip',
            'localKnown','localMatch','hit_testAttempted','variantAttempted')),(4,0,0,0,0,0))
        self.assertEqual(tuple(result[key] for key in ('compareAttempted','compareCompleted',
            'compareHresult','firstCompareRawObserved','firstCompareRawBits')),(1,1,0,1,0))
        self.assertEqual((result['patternAttempted'],result['child_idAttempted'],
            result['accessibleAttempted'],result['queryAttempted']),(1,1,1,0))

    def test_false_roundtrip_keeps_five_identity_calls_separate_from_scalar_and_original_repeat_calls(self):
        self.prepare();result=self.run_worker();self.assert_primary_false(result)
        self.assertEqual(tuple(result.get(key) for key in ('falseShadowVersion',
            'falseShadowStarted','falseShadowStatus','falseShadowStep','falseShadowAttempted',
            'falseShadowCompleted','falseShadowLastHresult')),(1,1,1,5,5,5,0))
        self.assertEqual(self.sdk.calls[:10],['pattern','child_id','accessible','from_accessible',
            'compare','pattern','child_id','accessible','accessible_query','accessible_query'])
        self.assertEqual(self.sdk.calls[10:12],['control_type','control_type'])
        self.assertEqual(self.sdk.calls[12:14],['accessible','accessible_query'])
        self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(9,9))
        self.assertEqual(self.sdk.releases,[301,203,301,301,202,201,103,102,101])
        self.assertEqual((result['falseShadowGuardBefore'],result['falseShadowGuardAfter']),(1,1))

    def test_shadow_queries_exact_msaa_pair_with_unknown_iid_without_exporting_addresses(self):
        self.prepare();self.sdk.canonical=(0x123456789abc,0x123456789abc)
        original=self.sdk.call;queries=[]
        def call(key,pointer,*args):
            if key=='pattern' and pointer==103:
                self.assertEqual(args[0],10018)
                self.assertEqual(C.string_at(args[1],16),uuid.UUID('828055ad-355b-4435-86d5-3b51c14a9b1b').bytes_le)
            if key=='accessible_query':
                self.assertEqual(C.string_at(args[0],16),uuid.UUID('00000000-0000-0000-c000-000000000046').bytes_le)
                self.assertEqual(self.sdk.releases,[]);queries.append(pointer)
            return original(key,pointer,*args)
        self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
        self.assertEqual(queries,[102,202,203])
        self.assertEqual(result['falseShadowCanonicalEqual'],1)
        self.assertTrue(all(type(value) is int and 0<=value<=0xffffffff for value in result.values()))
        self.assertNotIn(0x123456789abc,result.values())
        self.assertEqual(self.sdk.releases[2:4],[0x123456789abc,0x123456789abc])

    def test_canonical_identity_and_signed_child_are_observations_only(self):
        for canonical,child,want in (((301,301),0,(1,1)),((301,302),0,(0,1)),
                ((301,301),-1,(1,0)),((301,302),7,(0,0))):
            with self.subTest(canonicalEqual=want[0],childEqual=want[1]):
                self.prepare();self.sdk.canonical=canonical;self.sdk.shadow_child=child
                result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(result.get('falseShadowIdentityObserved'),1)
                self.assertEqual((result['falseShadowCanonicalEqual'],result['falseShadowChildEqual']),want)
                self.assertEqual((result['falseShadowChildObserved'],result['falseShadowChildBits']),(1,child&0xffffffff))
                self.assertEqual(result['workerCleanup'],1)

    def test_true_noncanonical_true_failed_compare_and_earlier_failure_do_not_start_shadow(self):
        for reason in ('true','noncanonical','compare-failed','earlier-failed'):
            with self.subTest(reason=reason):
                self.sdk=FakeCalls();self.platform=FakePlatform();original=self.sdk.call
                if reason=='compare-failed':self.sdk.fail['compare']=-2147467259
                if reason=='earlier-failed':self.sdk.fail['accessible']=-2147467259
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if reason=='noncanonical' and key=='compare' and args[1] in (1,2,3):args[2]._obj.value=-1
                    return hr
                self.sdk.call=call;result=self.run_worker()
                self.assertEqual((result.get('falseShadowStarted'),result.get('falseShadowStatus')),(0,0))
                self.assertNotIn('accessible_query',self.sdk.calls)

    def test_each_shadow_hresult_null_and_exception_registers_every_nonnull_output(self):
        for step in range(1,6):
            for failure in ('hresult','exception','null'):
                if failure=='null' and step==2:continue
                with self.subTest(step=step,failure=failure):
                    self.prepare();original=self.sdk.call;seen=[]
                    def call(key,pointer,*args):
                        hr=original(key,pointer,*args)
                        if key!='release' and len(self.sdk.calls)>5:
                            seen.append(key)
                            if len(seen)==step:
                                if failure=='exception':raise KeyboardInterrupt('Synthetic private exception')
                                if failure=='null':args[-1]._obj.value=None
                                else:return -2147467259
                        return hr
                    self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                    self.assertEqual(result.get('falseShadowStatus'),{'hresult':4,'null':5,'exception':6}[failure])
                    self.assertEqual(result['falseShadowStep'],step)
                    self.assertEqual(result['falseShadowAttempted'],step)
                    self.assertEqual(result['falseShadowCompleted'],step-int(failure=='exception'))
                    self.assertEqual(result['falseShadowIdentityObserved'],0)
                    acquired=3+sum(index!=2 for index in range(1,step+1))-int(failure=='null')
                    self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(acquired,acquired))
                    self.assertEqual(self.sdk.releases,list(reversed([101,102,103]+
                        [value for index,value in ((1,201),(3,202),(4,301),(5,301))
                            if index<=step and not (failure=='null' and index==step)])))
                    self.assertEqual(result['workerCleanup'],int(failure!='exception'))
                    self.assertTrue(all(type(value) is int and 0<=value<=0xffffffff for value in result.values()))
                    self.assertNotIn('Synthetic private',str(result))

    def test_original_deadline_stops_call_admission_at_entry_or_after_each_call(self):
        for cutoff in range(6):
            with self.subTest(cutoff=cutoff):
                self.prepare();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key!='release' and len(self.sdk.calls)==5+cutoff:self.platform.now=15.
                    return hr
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(result.get('falseShadowStatus'),2)
                self.assertEqual((result['falseShadowAttempted'],result['falseShadowCompleted']),(cutoff,cutoff))
                self.assertEqual(result['falseShadowIdentityObserved'],0)
                self.assertEqual(result['workerCleanup'],1)

    def test_process_guard_at_every_admission_and_return_stops_further_calls(self):
        # Initial worker guard is 1; shadow entry is 2, then before/after
        # five identity, two scalar and two repeat calls; final guard is 21.
        for cutoff in range(2,22):
            with self.subTest(guard=cutoff):
                self.prepare();checks=[]
                def guard():checks.append(1);return len(checks)<cutoff
                self.platform.guard=guard;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(result.get('falseShadowStatus'),3)
                self.assertEqual(result['falseShadowAttempted'],min(5,max(0,(cutoff-2)//2)))
                self.assertEqual(result['falseShadowGuardAfter'],0)
                self.assertEqual(result['workerCleanup'],1)

    def test_cleanup_failure_never_promotes_even_canonical_agreement(self):
        self.prepare();self.sdk.release_throws=True;result=self.run_worker();self.assert_primary_false(result)
        self.assertEqual(result.get('falseShadowCanonicalEqual'),1)
        self.assertEqual((result['cleanupError'],result['workerCleanup']),(1,0))

    def test_time_expiring_in_guard_prevents_each_call_and_final_completion(self):
        for cutoff in (2,3,5,7,9,11,13,15,17,19,21):
            with self.subTest(guard=cutoff):
                self.prepare();checks=[]
                def guard():
                    checks.append(1)
                    if len(checks)==cutoff:self.platform.now=15.
                    return True
                self.platform.guard=guard;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(result['falseShadowStatus'],2)
                self.assertEqual(result['falseShadowAttempted'],min(5,max(0,(cutoff-2)//2)))
                self.assertEqual(result['falseShadowGuardAfter'],0)

    def test_cleanup_returning_after_deadline_retains_bits_but_never_completed_status(self):
        self.prepare();original=self.sdk.call
        def call(key,pointer,*args):
            hr=original(key,pointer,*args)
            if key=='release':self.platform.now=15.
            return hr
        self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
        self.assertEqual(result['falseShadowStatus'],2)
        self.assertEqual((result['falseShadowIdentityObserved'],result['falseShadowCanonicalEqual']),(1,1))
        self.assertEqual(result['workerCleanup'],1)

    def test_shadow_noninteger_hresult_is_unobserved_exception_with_owned_output_cleanup(self):
        for malformed in (None,True,False):
            with self.subTest(kind=type(malformed).__name__):
                self.prepare();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    return malformed if key=='pattern' and pointer==103 else hr
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual((result['falseShadowStatus'],result['falseShadowAttempted'],
                    result['falseShadowCompleted']),(6,1,0))
                self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(4,4))
                self.assertEqual((result['cleanupError'],result['workerCleanup']),(1,0))

    def test_canonical_agreement_still_fails_actual_caller_before_save_input(self):
        import test_owned_native_menu as boundaries
        self.prepare();provider=self.run_worker()
        self.assertEqual((provider['falseShadowCanonicalEqual'],provider['falseShadowChildEqual']),(1,1))
        self.assertEqual((provider['falseShadowOriginalControlType'],provider['falseShadowRoundTripControlType']),(50011,50011))
        self.assertEqual((provider['falseShadowOriginalControlTypeObserved'],provider['falseShadowRoundTripControlTypeObserved']),(1,1))
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,boundary=owner.real_chrome_fixture();probe=boundary.probe
        original=probe.point_snapshot;exposures=[];fresh=[]
        probe._native_point_profile=True
        probe._require_provider_creator=lambda:dict(threadId=123,mta=True,sameThread=True)
        probe._popup_exposure=lambda *args:exposures.append(1) or dict(hwnd=99)
        probe._begin_point_lease=lambda *args:NS(wait=lambda:provider,pending=False)
        original_fresh=probe._fresh_proof
        def fresh_proof(*args):
            if exposures:fresh.append(1)
            return original_fresh(*args)
        probe._fresh_proof=fresh_proof
        actual=NS(CurrentControlType=50033,CurrentProcessId=88,CurrentNativeWindowHandle=99)
        def point(scope,coordinates,control):
            target=control.element_info._element
            if target.key=='file':return original(scope,coordinates,control)
            return probe._provider_local_point(coordinates,target,actual)
        probe.point_snapshot=point
        with self.assertRaisesRegex(AssertionError,'native menu provider point is unknown'):
            module.click_native_menu_action(api,process,11,record,'save',probe=probe,clock=clock)
        self.assertEqual([row for row in boundary.native.calls if isinstance(row,tuple) and row[0]=='click'],[('click','file')])
        self.assertEqual(exposures,[1]);self.assertEqual(fresh,[])
        self.assertIs(probe.interop['providerLocalResult'],provider)
        self.assertFalse(record['nativeMenuActions'][-1]['success'])


class ControlTypeTests(unittest.TestCase):
    setUp=WorkerTests.setUp
    run_worker=WorkerTests.run_worker
    prepare=FalseShadowTests.prepare
    assert_primary_false=FalseShadowTests.assert_primary_false

    def test_exact_original_and_bridge_scalar_observations_add_no_refs_and_do_not_promote_false(self):
        for values in ((50011,50011),(50011,50033),(-1,-2**31)):
            with self.subTest(same=values[0]==values[1]):
                self.prepare();self.sdk.control_types=values;original=self.sdk.call;inputs=[]
                def call(key,pointer,*args):
                    if key=='control_type':
                        self.assertIs(type(args[0]._obj),C.c_int32)
                        self.assertEqual(self.sdk.releases,[]);inputs.append(pointer)
                    return original(key,pointer,*args)
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(inputs,[1,103])
                for side,value in zip(('Original','RoundTrip'),values):
                    prefix='falseShadow'+side+'ControlType'
                    self.assertEqual(tuple(result.get(prefix+suffix) for suffix in
                        ('Observed','','Hresult')),(1,value&0xffffffff,0))
                self.assertEqual(self.sdk.calls[10:12],['control_type','control_type'])
                self.assertEqual((result['falseShadowAttempted'],result['falseShadowCompleted'],
                    result['falseShadowStep'],result['falseShadowStatus']),(5,5,5,1))
                self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(9,9))
                self.assertEqual(self.sdk.releases,[301,203,301,301,202,201,103,102,101])
                self.assertTrue(all(type(value) is int and 0<=value<=0xffffffff for value in result.values()))

    def test_untriggered_failed_compare_and_early_shadow_failure_leave_control_types_unknown(self):
        for reason in ('true','compare','pattern','shadow'):
            with self.subTest(reason=reason):
                self.prepare()
                if reason=='true':self.sdk.wrong_file=False
                elif reason=='shadow':self.sdk.fail['accessible_query']=-2147467259
                else:self.sdk.fail[reason]=-2147467259
                result=self.run_worker();self.assertNotIn('control_type',self.sdk.calls)
                for side in ('Original','RoundTrip'):
                    prefix='falseShadow'+side+'ControlType'
                    self.assertEqual(tuple(result.get(prefix+suffix) for suffix in
                        ('Observed','','Hresult')),(0,0,0))

    def test_each_getter_failed_hresult_or_exception_keeps_written_value_unobserved(self):
        for ordinal in (1,2):
            for failure in ('hresult','s-false','exception','noninteger'):
                with self.subTest(ordinal=ordinal,failure=failure):
                    self.prepare();original=self.sdk.call
                    def call(key,pointer,*args):
                        hr=original(key,pointer,*args)
                        if key=='control_type' and self.sdk.calls.count(key)==ordinal:
                            if failure=='exception':raise KeyboardInterrupt('Synthetic private control value')
                            return {'hresult':-2147467259,'s-false':1,'noninteger':True}[failure]
                        return hr
                    self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                    self.assertEqual(result.get('falseShadowStatus'),4 if failure in ('hresult','s-false') else 6)
                    side='Original' if ordinal==1 else 'RoundTrip';prefix='falseShadow'+side+'ControlType'
                    self.assertEqual((result[prefix+'Observed'],result[prefix]),(0,0))
                    self.assertEqual(result[prefix+'Hresult'],{'hresult':0x80004005,'s-false':1}.get(failure,0))
                    self.assertEqual(self.sdk.calls.count('control_type'),ordinal)
                    self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(7,7))
                    self.assertEqual(result['cleanupError'],int(failure in ('exception','noninteger')))
                    self.assertNotIn('Synthetic private',str(result))

    def test_late_getter_output_is_unknown_and_next_getter_never_starts(self):
        for ordinal in (1,2):
            with self.subTest(ordinal=ordinal):
                self.prepare();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key=='control_type' and self.sdk.calls.count(key)==ordinal:self.platform.now=15.
                    return hr
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(result['falseShadowStatus'],2)
                self.assertEqual(self.sdk.calls.count('control_type'),ordinal)
                for index,side in enumerate(('Original','RoundTrip'),1):
                    prefix='falseShadow'+side+'ControlType'
                    self.assertEqual(result[prefix+'Observed'],int(index<ordinal))
                    self.assertEqual(result[prefix],50011 if index<ordinal else 0)
                self.assertEqual(result['workerCleanup'],1)

    def test_process_and_clock_guards_cover_both_getters_and_final_observations(self):
        for cutoff in range(13,18):
            for reason in ('process','deadline'):
                with self.subTest(cutoff=cutoff,reason=reason):
                    self.prepare();checks=[]
                    def guard():
                        checks.append(1)
                        if reason=='deadline' and len(checks)==cutoff:self.platform.now=15.
                        return reason!='process' or len(checks)<cutoff
                    self.platform.guard=guard;result=self.run_worker();self.assert_primary_false(result)
                    self.assertEqual(result['falseShadowStatus'],3 if reason=='process' else 2)
                    self.assertEqual(self.sdk.calls.count('control_type'),min(2,(cutoff-12)//2))
                    self.assertEqual(result['falseShadowGuardAfter'],0)
                    self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(7,7))


class OriginalRepeatTests(unittest.TestCase):
    setUp=WorkerTests.setUp
    run_worker=WorkerTests.run_worker
    prepare=FalseShadowTests.prepare
    assert_primary_false=FalseShadowTests.assert_primary_false
    prefix='falseShadowOriginalRepeat'

    def test_repeat_uses_original_pattern_and_live_canonical_reference_without_promoting_false(self):
        for repeated,want in ((301,1),(302,0),(0x123456789abc,0)):
            with self.subTest(equal=want):
                self.prepare();self.sdk.canonical=(301,302);self.sdk.repeat_canonical=repeated
                original=self.sdk.call;inputs=[]
                def call(key,pointer,*args):
                    if (key=='accessible' and self.sdk.calls.count(key)==2 or
                            key=='accessible_query' and self.sdk.calls.count(key)==2):
                        self.assertEqual(self.sdk.releases,[]);inputs.append((key,pointer))
                        if key=='accessible_query':
                            self.assertEqual(C.string_at(args[0],16),uuid.UUID('00000000-0000-0000-c000-000000000046').bytes_le)
                    return original(key,pointer,*args)
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual(inputs,[('accessible',101),('accessible_query',203)])
                self.assertEqual(tuple(result.get(self.prefix+suffix) for suffix in
                    ('Attempted','Completed','LastHresult','Observed','CanonicalEqual')),(2,2,0,1,want))
                self.assertEqual(self.sdk.calls[12:14],['accessible','accessible_query'])
                self.assertEqual((result['falseShadowAttempted'],result['falseShadowCompleted'],
                    result['falseShadowStep'],result['falseShadowStatus']),(5,5,5,1))
                self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(9,9))
                self.assertEqual(self.sdk.releases,[repeated,203,302,301,202,201,103,102,101])
                self.assertTrue(all(type(value) is int and 0<=value<=0xffffffff for value in result.values()))
                self.assertNotIn(0x123456789abc,result.values())

    def test_aliased_accessible_and_unknown_outputs_still_own_separate_references(self):
        self.prepare();self.sdk.repeat_accessible=102;result=self.run_worker();self.assert_primary_false(result)
        self.assertEqual(result.get(self.prefix+'CanonicalEqual'),1)
        self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(9,9))
        self.assertEqual(self.sdk.releases,[301,102,301,301,202,201,103,102,101])

    def test_untriggered_failed_compare_or_earlier_shadow_failure_never_repeats_original_pattern(self):
        for reason in ('true','noncanonical','compare','primary','shadow','scalar'):
            with self.subTest(reason=reason):
                self.prepare();original=self.sdk.call
                if reason in ('true','noncanonical'):self.sdk.wrong_file=False
                elif reason=='compare':self.sdk.fail['compare']=-2147467259
                elif reason=='primary':self.sdk.fail['accessible']=-2147467259
                elif reason=='shadow':self.sdk.fail['accessible_query']=-2147467259
                elif reason=='scalar':self.sdk.fail['control_type']=-2147467259
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if reason=='noncanonical' and key=='compare' and args[1] in (1,2,3):args[2]._obj.value=-1
                    return hr
                self.sdk.call=call;result=self.run_worker()
                self.assertEqual(tuple(result.get(self.prefix+suffix) for suffix in
                    ('Attempted','Completed','LastHresult','Observed','CanonicalEqual')),(0,0,0,0,0))
                self.assertLess(self.sdk.calls.count('accessible'),3)

    def test_each_repeat_failure_registers_nonnull_outputs_without_observing_equality(self):
        for ordinal in (1,2):
            for failure in ('hresult','s-false','null','exception','noninteger'):
                with self.subTest(ordinal=ordinal,failure=failure):
                    self.prepare();original=self.sdk.call
                    def call(key,pointer,*args):
                        hr=original(key,pointer,*args)
                        selected=(key=='accessible' and self.sdk.calls.count(key)==3 or
                            key=='accessible_query' and self.sdk.calls.count(key)==3)
                        if selected and (key=='accessible')==(ordinal==1):
                            if failure=='exception':raise KeyboardInterrupt('Synthetic repeat failure')
                            if failure=='null':args[-1]._obj.value=None
                            else:return {'hresult':-2147467259,'s-false':1,'noninteger':True}[failure]
                        return hr
                    self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                    self.assertEqual(result.get(self.prefix+'Attempted'),ordinal)
                    self.assertEqual(result.get(self.prefix+'Completed'),ordinal-int(failure in ('exception','noninteger')))
                    self.assertEqual(result.get(self.prefix+'LastHresult'),{'hresult':0x80004005,'s-false':1}.get(failure,0))
                    self.assertEqual((result.get(self.prefix+'Observed'),result.get(self.prefix+'CanonicalEqual')),(0,0))
                    self.assertEqual(result['falseShadowStatus'],{'hresult':4,'s-false':4,'null':5,'exception':6,'noninteger':6}[failure])
                    acquired=[101,102,103,201,202,301,301]+[203,301][:ordinal]
                    if failure=='null':acquired.pop()
                    self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(len(acquired),len(acquired)))
                    self.assertEqual(self.sdk.releases,list(reversed(acquired)))
                    self.assertEqual(result['workerCleanup'],int(failure not in ('exception','noninteger')))

    def test_new_pair_obeys_original_process_and_clock_guards_at_each_boundary(self):
        for cutoff in range(17,22):
            for reason in ('process','deadline'):
                with self.subTest(cutoff=cutoff,reason=reason):
                    self.prepare();checks=[]
                    def guard():
                        checks.append(1)
                        if reason=='deadline' and len(checks)==cutoff:self.platform.now=15.
                        return reason!='process' or len(checks)<cutoff
                    self.platform.guard=guard;result=self.run_worker();self.assert_primary_false(result)
                    calls=min(2,(cutoff-16)//2)
                    self.assertEqual((result.get(self.prefix+'Attempted'),result.get(self.prefix+'Completed')),(calls,calls))
                    self.assertEqual(result.get(self.prefix+'Observed'),int(cutoff==21))
                    self.assertEqual(result['falseShadowStatus'],3 if reason=='process' else 2)
                    self.assertEqual(result['falseShadowGuardAfter'],0)
                    self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(7+calls,7+calls))

    def test_late_repeat_call_output_is_released_without_observing_equality(self):
        for ordinal in (1,2):
            with self.subTest(ordinal=ordinal):
                self.prepare();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if (key=='accessible' and self.sdk.calls.count(key)==3 and ordinal==1 or
                            key=='accessible_query' and self.sdk.calls.count(key)==3 and ordinal==2):self.platform.now=15.
                    return hr
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual((result.get(self.prefix+'Attempted'),result.get(self.prefix+'Completed')),(ordinal,ordinal))
                self.assertEqual(result.get(self.prefix+'Observed'),0)
                self.assertEqual(result['falseShadowStatus'],2);self.assertEqual(result['workerCleanup'],1)
                self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(7+ordinal,7+ordinal))

    def test_repeat_equality_bits_survive_late_cleanup_but_never_certify_completion(self):
        for failure in ('expired','cleanup'):
            with self.subTest(failure=failure):
                self.prepare();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key=='release' and failure=='expired':self.platform.now=15.
                    if key=='release' and failure=='cleanup':raise RuntimeError('Synthetic cleanup failure')
                    return hr
                self.sdk.call=call;result=self.run_worker();self.assert_primary_false(result)
                self.assertEqual((result.get(self.prefix+'Observed'),result.get(self.prefix+'CanonicalEqual')),(1,1))
                self.assertFalse(result['falseShadowStatus']==1 and result['workerCleanup']==1)
                self.assertEqual(result['workerCleanup'],int(failure!='cleanup'))
                if failure=='cleanup':
                    self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(9,0))
                    self.assertEqual(len(self.sdk.releases),9)


class CanonicalCalls:
    Guid=WorkerGuid;Variant=Variant
    def __init__(self):
        self.calls=[];self.releases=[];self.patterns={1:101,11:111,2:102,3:103}
        self.accessibles={101:201,111:211,102:202,103:203}
        self.identities={201:301,211:301,202:302,203:302,221:301,222:302}
        self.children={};self.types={};self.failure_at=0;self.hresult=0
        self.variant_type=9;self.variant_pointer=401;self.repeat_count=0
        self.false_positive=False;self.true_negative=False
    def call(self,key,pointer,*args):
        pointer=pointer.value if isinstance(pointer,C.c_void_p) else pointer
        if key=='release':self.releases.append(pointer);return 0
        self.calls.append((key,pointer))
        if key=='pattern':
            assert args[0]==10018
            assert C.string_at(args[1],16)==uuid.UUID('828055ad-355b-4435-86d5-3b51c14a9b1b').bytes_le
            args[2]._obj.value=self.patterns[pointer]
        elif key=='child_id':args[0]._obj.value=self.children.get(pointer,0)
        elif key=='accessible':
            if pointer==101:self.repeat_count+=1
            args[0]._obj.value=221 if pointer==101 and self.repeat_count>1 else self.accessibles[pointer]
        elif key=='accessible_query':
            assert C.string_at(args[0],16)==uuid.UUID('00000000-0000-0000-c000-000000000046').bytes_le
            args[1]._obj.value=self.identities[pointer]
        elif key=='control_type':args[0]._obj.value=self.types.get(pointer,50011)
        elif key=='hit_test':
            assert pointer==201 and args[:2]==(14,15)
            args[2]._obj.vt=self.variant_type;args[2]._obj._.c_void_p=self.variant_pointer
        elif key=='query':
            assert pointer==401 and C.string_at(args[0],16)==uuid.UUID('618736e0-3c3d-11cf-810c-00aa00389b71').bytes_le
            args[1]._obj.value=222
        elif key=='compare':
            first,second=args[:2]
            args[2]._obj.value=int(not self.false_positive if (first,second) in ((1,11),(2,3)) else self.true_negative)
        else:raise AssertionError('Unexpected canonical API; inverse calls are forbidden')
        return self.hresult if len(self.calls)==self.failure_at else 0


class CanonicalV2Tests(unittest.TestCase):
    def setUp(self):
        self.helper=load_helper();self.assertTrue(hasattr(self.helper,'MsaaHitSourceV2'))
        self.sdk=CanonicalCalls();self.platform=FakePlatform()
        self.source=self.helper.MsaaHitSourceV2(9,1,11,2,3,(4,5,6),20,21,(self.sdk,))
        self.scope=self.helper.MsaaHitScope(7,8,9,10,11,12,13,14,15)
    def run_worker(self):return self.helper.run_canonical_hit(self.source,self.scope,self.sdk,self.platform,15.)
    def assert_unknown(self,result):
        self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
        self.assertNotIn('from_accessible',[key for key,_ in self.sdk.calls])
        self.assertEqual(result['referencesAcquired'],result['referencesReleased'])

    def test_positive_binds_four_distinct_elements_then_hits_exact_target_with_sixteen_owned_refs(self):
        result=self.run_worker()
        self.assertEqual((result['localKnown'],result['localMatch'],result['canonicalStatus'],result['workerSchemaVersion']),(1,1,1,2))
        counts={'pattern':4,'child_id':4,'accessible':5,'accessible_query':6,'control_type':4,'hit_test':1,'query':1,'compare':5}
        for name,count in counts.items():
            self.assertEqual((result[name+'Attempted'],result[name+'Completed'],result[name+'Hresult']),(count,count,0))
        self.assertEqual(len(self.sdk.calls),30)
        self.assertEqual([pointer for key,pointer in self.sdk.calls if key=='pattern'],[1,11,2,3])
        self.assertEqual([pointer for key,pointer in self.sdk.calls if key=='accessible'],[101,111,102,103,101])
        self.assertEqual(self.sdk.releases,[302,222,301,221,302,203,103,302,202,102,301,211,111,301,201,101])
        self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(16,16))
        self.assertEqual((result['bindingCount'],result['selfCount'],result['negativeCount'],result['negativeRejected']),(4,4,3,3))
        for key in ('filePairEqual','fileOriginalRepeatEqual','targetPairEqual','targetDifferentFromFile','hitMatchesTarget','fileUiPositive','targetUiPositive','workerCleanup'):
            self.assertEqual(result[key],1)
        self.assertEqual(self.platform.clears,[401]);self.assertEqual(self.platform.uninitializes,1)
        self.assertTrue(all(type(v) is int and 0<=v<=0xffffffff for v in result.values()))
        self.assertNotIn('fileRoundTrip',result);self.assertNotIn('falseShadowStatus',result)

    def test_every_pair_repeat_and_hit_mismatch_is_unknown_without_inverse_fallback(self):
        for pointer,value in ((211,311),(221,321),(203,303),(202,301),(222,301)):
            with self.subTest(binding=pointer):
                self.setUp();self.sdk.identities[pointer]=value;result=self.run_worker();self.assert_unknown(result)
                self.assertEqual(result['canonicalStatus'],7)
        for field in ('false_positive','true_negative'):
            with self.subTest(comparison=field):
                self.setUp();setattr(self.sdk,field,True);self.assert_unknown(self.run_worker())
        self.setUp();self.sdk.identities.update({202:301,203:301})
        result=self.run_worker();self.assert_unknown(result)
        self.assertEqual((result['targetPairEqual'],result['targetDifferentFromFile'],result['hit_testAttempted']),(1,0,0))

    def test_all_four_child_self_and_menuitem_roles_are_mandatory(self):
        for pointer in (101,111,102,103):
            for child in (-1,1):
                with self.subTest(pattern=pointer,child=child):
                    self.setUp();self.sdk.children[pointer]=child;result=self.run_worker();self.assert_unknown(result)
                    self.assertEqual(result['canonicalStatus'],5)
        for pointer in (1,11,2,3):
            with self.subTest(element=pointer):
                self.setUp();self.sdk.types[pointer]=50010;result=self.run_worker();self.assert_unknown(result)
                self.assertEqual(result['canonicalStatus'],5)

    def test_only_dispatch_nonnull_hit_shape_can_reach_exact_target_query(self):
        for kind,pointer in ((0,0),(3,401),(9,0),(8,401)):
            with self.subTest(kind=kind,pointer=pointer):
                self.setUp();self.sdk.variant_type=kind;self.sdk.variant_pointer=pointer
                result=self.run_worker();self.assert_unknown(result)
                self.assertEqual(result['queryAttempted'],0);self.assertEqual(result['variantCleared'],1)

    def test_failed_hresult_at_every_call_releases_all_written_refs_and_variant(self):
        for ordinal in range(1,31):
            for hresult in (-2147467259,1):
                with self.subTest(call=ordinal,hresult=hresult):
                    self.setUp();self.sdk.failure_at=ordinal;self.sdk.hresult=hresult
                    result=self.run_worker();self.assert_unknown(result)
                    self.assertEqual(len(self.sdk.calls),ordinal);self.assertEqual(result['canonicalStatus'],4)
                    self.assertEqual(result['variantAttempted'],result['variantCleared'])

    def test_null_out_at_each_owned_acquisition_stops_and_never_releases_borrowed_refs(self):
        for ordinal in (1,3,4,6,8,9,11,13,14,16,18,19,21,22,24,25):
            with self.subTest(call=ordinal):
                self.setUp();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key!='release' and len(self.sdk.calls)==ordinal:args[-1]._obj.value=None
                    return hr
                self.sdk.call=call;result=self.run_worker();self.assert_unknown(result)
                self.assertEqual(len(self.sdk.calls),ordinal);self.assertEqual(result['canonicalStatus'],5)
                self.assertFalse(set(self.sdk.releases)&{1,11,2,3,4,5,6,9,20,21,401})

    def test_process_and_clock_guard_before_and_after_every_call_admit_no_later_work(self):
        # Worker entry guard1, every call before/after2..61, final guard62.
        for boundary in range(1,63):
            for failure in ('process','deadline'):
                with self.subTest(boundary=boundary,failure=failure):
                    self.setUp();checks=[]
                    def guard():
                        checks.append(1)
                        if len(checks)==boundary and failure=='deadline':self.platform.now=15.
                        return failure!='process' or len(checks)<boundary
                    self.platform.guard=guard;result=self.run_worker();self.assert_unknown(result)
                    self.assertEqual(result['canonicalStatus'],3 if failure=='process' else 2)
                    self.assertEqual(len(self.sdk.calls),min(30,max(0,(boundary-1)//2)))

    def test_cleanup_failure_or_late_release_never_certifies_canonical_success(self):
        for failure in ('release','late','variant','dpi','uninitialize'):
            with self.subTest(cleanup=failure):
                self.setUp();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key=='release' and failure=='release':raise RuntimeError('Synthetic release failure')
                    if key=='release' and failure=='late':self.platform.now=15.
                    return hr
                self.sdk.call=call
                if failure=='variant':self.platform.clear_hr=-2147467259
                if failure=='dpi':self.platform.restore=False
                if failure=='uninitialize':self.platform.uninitialize=lambda:(_ for _ in ()).throw(RuntimeError('Synthetic COM cleanup'))
                result=self.run_worker();self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
                self.assertEqual(len(self.sdk.releases),16)
                self.assertEqual(result['canonicalStatus'],2 if failure=='late' else 8)

    def test_closed_source_and_explicit_modes_reject_before_any_native_work(self):
        self.assertTrue(self.source.valid())
        for mode in (0,3,True,False,2.,'2',None):
            with self.subTest(mode=mode):
                kernel=FakeKernel()
                with self.assertRaises(ValueError):self.helper.begin_msaa_hit(self.source,self.scope,self.sdk,15.,profile_version=mode,_kernel=kernel)
                self.assertEqual(kernel.duplicates,[]);self.assertIsNone(kernel.callback)
        for source,mode in ((self.source,1),(self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21),2)):
            kernel=FakeKernel();lease=self.helper.begin_msaa_hit(source,self.scope,self.sdk,15.,profile_version=mode,_kernel=kernel)
            self.assertEqual(lease.record['stageCode'],3);self.assertEqual(kernel.duplicates,[])

    def test_wrong_native_source_mode_is_rejected_before_windows_kernel_construction(self):
        from unittest.mock import patch
        initialized=[];v1=self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21)
        with patch.object(self.helper,'NATIVE_LAUNCH_ENABLED',True), \
                patch.object(self.helper,'WindowsKernel',side_effect=lambda:initialized.append(1) or FakeKernel()):
            for source,mode in ((self.source,1),(v1,2)):
                result=self.helper.begin_msaa_hit(source,self.scope,self.sdk,15.,native_enabled=True,profile_version=mode)
                self.assertEqual(result.record['stageCode'],3)
        self.assertEqual(initialized,[])

    def test_native_dispatch_and_closed_v2_lease_keep_v1_worker_and_registry_separate(self):
        kernel=FakeKernel();platform=self.platform;platform.clock=kernel.clock
        kernel.worker=lambda source,scope,sdk,deadline:self.helper.run_canonical_hit(source,scope,sdk,platform,deadline)
        lease=self.helper.begin_msaa_hit(self.source,self.scope,self.sdk,15.,profile_version=2,_kernel=kernel)
        result=lease.wait()
        self.assertEqual((result['schemaVersion'],result['workerSchemaVersion'],result['stageCode'],result['localMatch']),(2,2,13,1))
        self.assertEqual(set(result),set(self.helper._record(None,False,profile_version=2)))
        self.assertIsNone(self.helper.pending_msaa_hit())
        kernel=FakeKernel();kernel.finished=False
        v1=self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21)
        first=self.helper.begin_msaa_hit(v1,self.scope,self.sdk,15.,_kernel=kernel)
        second=self.helper.begin_msaa_hit(self.source,self.scope,self.sdk,15.,profile_version=2,_kernel=FakeKernel())
        self.assertEqual(second.record['stageCode'],2);self.assertIs(self.helper.pending_msaa_hit(),first)
        kernel.finished=True;first.retire(20.)
        self.assertIsNone(self.helper.pending_msaa_hit())

    def test_v2_sdk_checks_every_borrowed_element_and_closed_source_shape_without_com(self):
        from dataclasses import replace
        metadata=sdk_fixture();abi=self.helper.SdkAbi(**metadata)
        def ref(interface,value):return type('Borrowed',(C.c_void_p,),{'__com_interface__':interface})(value)
        client=ref(metadata['client_interface'],9)
        elements=[ref(metadata['element_interface'],n) for n in (1,11,2,3,4,5,6)]
        source=self.helper.MsaaHitSourceV2(client,*elements[:4],tuple(elements[4:]),20,21,(self.sdk,))
        self.assertTrue(abi.matches_source(source))
        for field in ('client','retained_file','fresh_file','fresh_target','retained_target'):
            for value in (None,C.c_void_p(123)):
                with self.subTest(field=field,typed=value is not None):self.assertFalse(abi.matches_source(replace(source,**{field:value})))
        for value in ((elements[4],C.c_void_p(123)),(elements[4],None),[],(),(elements[4],)):
            self.assertFalse(abi.matches_source(replace(source,negative_refs=value)))
        for change in ({'keepalive':()},{'keepalive':(None,)},{'shell_handle':True},{'engine_handle':0}):
            self.assertFalse(replace(source,**change).valid())

    def test_actual_kernel_dispatch_selects_before_worker_and_rejects_unknown_source(self):
        from unittest.mock import patch
        calls=[];kernel=self.helper.WindowsKernel.__new__(self.helper.WindowsKernel)
        v1=self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21)
        with patch.object(self.helper,'run_local_hit',side_effect=lambda *args:calls.append(1) or 1), \
                patch.object(self.helper,'run_canonical_hit',side_effect=lambda *args:calls.append(2) or 2):
            self.assertEqual(kernel.worker(self.source,self.scope,self.sdk,15.),2)
            self.assertEqual(kernel.worker(v1,self.scope,self.sdk,15.),1)
            with self.assertRaises(ValueError):kernel.worker(object(),self.scope,self.sdk,15.)
        self.assertEqual(calls,[2,1])

    def test_v2_worker_closed_record_rejects_added_missing_and_non_uint_fields(self):
        for damage in ('extra','missing','bool','negative','wide'):
            with self.subTest(packet=damage):
                self.setUp();kernel=FakeKernel()
                def worker(*args):
                    record=self.helper.worker_record_v2()
                    if damage=='extra':record['unexpected']=0
                    elif damage=='missing':record.pop('filePairEqual')
                    else:record['filePairEqual']={'bool':True,'negative':-1,'wide':2**32}[damage]
                    return record
                kernel.worker=worker
                lease=self.helper.begin_msaa_hit(self.source,self.scope,self.sdk,15.,profile_version=2,_kernel=kernel)
                result=lease.wait()
                self.assertEqual((result['schemaVersion'],result['workerException'],result['pending'],result['localMatch']),(2,1,1,0))
                self.assertIs(lease.source,self.source)
                self.helper._active=None  # Synthetic completed callback; no native refs existed.

    def test_aliased_pattern_and_accessible_acquisitions_are_never_deduplicated(self):
        self.sdk.patterns[11]=101;result=self.run_worker()
        self.assertEqual((result['localMatch'],result['referencesAcquired'],result['referencesReleased']),(1,16,16))
        self.assertEqual(self.sdk.releases,[302,222,301,221,302,203,103,302,202,102,301,221,101,301,201,101])

    def test_malformed_or_exceptional_com_returns_still_release_written_owned_outputs(self):
        for ordinal in range(1,31):
            for failure in ('noninteger','exception'):
                with self.subTest(call=ordinal,failure=failure):
                    self.setUp();original=self.sdk.call
                    def call(key,pointer,*args):
                        hr=original(key,pointer,*args)
                        if key!='release' and len(self.sdk.calls)==ordinal:
                            if failure=='exception':raise KeyboardInterrupt('Synthetic canonical API failure')
                            return True
                        return hr
                    self.sdk.call=call;result=self.run_worker();self.assert_unknown(result)
                    self.assertEqual((result['canonicalStatus'],result['workerCleanup'],result['cleanupError']),(6,0,1))
                    self.assertEqual(len(self.sdk.calls),ordinal)
                    self.assertEqual(result['variantAttempted'],result['variantCleared'])

    def test_expired_entry_or_initialization_cannot_admit_dpi_or_provider_work(self):
        for phase in ('entry','initialize'):
            with self.subTest(phase=phase):
                self.setUp();events=[];initialize=self.platform.initialize
                def init():
                    events.append('initialize')
                    if phase=='initialize':self.platform.now=15.
                    return initialize()
                self.platform.initialize=init
                self.platform.enter_dpi=lambda:events.append('dpi') or 88
                if phase=='entry':self.platform.now=15.
                result=self.run_worker();self.assert_unknown(result)
                self.assertEqual(events,[] if phase=='entry' else ['initialize'])

    def test_deadline_after_each_local_phase_never_admits_a_later_phase(self):
        for phase,expected in (('apartment',['initialize','apartment']),
                ('dpi',['initialize','apartment','dpi']),
                ('physical',['initialize','apartment','dpi','physical'])):
            with self.subTest(phase=phase):
                self.setUp();events=[]
                def step(name,value):
                    events.append(name)
                    if name==phase:self.platform.now=15.
                    return value
                self.platform.initialize=lambda:step('initialize',0)
                self.platform.apartment=lambda:step('apartment',True)
                self.platform.enter_dpi=lambda:step('dpi',88)
                self.platform.physical_dpi=lambda:step('physical',True)
                self.platform.guard=lambda:step('guard',True)
                result=self.run_worker();self.assert_unknown(result)
                self.assertEqual(events,expected);self.assertEqual(result['canonicalStatus'],2)

    def test_late_or_untrusted_v2_collection_clears_match_and_never_relabels_mode_one(self):
        for failure in ('late','retire','process','exit','callback','packet'):
            with self.subTest(collection=failure):
                self.setUp();kernel=FakeKernel();self.platform.clock=kernel.clock
                kernel.worker=lambda source,scope,sdk,deadline:self.helper.run_canonical_hit(source,scope,sdk,self.platform,deadline)
                if failure=='packet':kernel.worker=lambda *args:dict(sdk_fixture_worker(),schemaVersion=2)
                lease=self.helper.begin_msaa_hit(self.source,self.scope,self.sdk,15.,profile_version=2,_kernel=kernel)
                if failure=='late':kernel.now=16.
                if failure=='process':kernel.check_process=lambda *args:False
                if failure=='exit':kernel.exit_code=7
                if failure=='callback':kernel.callback_identity_failure=True
                result=lease.retire(20.) if failure=='retire' else lease.wait()
                self.assertEqual((result['schemaVersion'],result['localKnown'],result['localMatch']),(2,0,0))
                self.assertNotEqual(result['stageCode'],13)
                if failure=='packet':self.assertEqual((result['workerException'],result['pending']),(1,1))

    def test_inflight_hit_holds_source_sdk_and_all_owned_refs_until_callback_exit(self):
        import threading
        for ordinal,count in ((23,14),(25,16)):
            with self.subTest(call=ordinal):
                self.setUp();entered=threading.Event();release=threading.Event();kernel=FakeKernel()
                kernel.finished=False;self.platform.clock=kernel.clock;original=self.sdk.call;threads=[]
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key!='release' and len(self.sdk.calls)==ordinal:
                        entered.set()
                        if not release.wait(2):raise RuntimeError('Synthetic canonical callback wait')
                    return hr
                self.sdk.call=call
                def start(callback):
                    def entry():
                        try:callback()
                        finally:kernel.finished=True
                    thread=threading.Thread(target=entry,daemon=True);threads.append(thread);thread.start()
                    return 301,44,55
                kernel.start=start
                kernel.worker=lambda source,scope,sdk,deadline:self.helper.run_canonical_hit(source,scope,sdk,self.platform,deadline)
                lease=self.helper.begin_msaa_hit(self.source,self.scope,self.sdk,15.,profile_version=2,_kernel=kernel)
                try:
                    self.assertTrue(entered.wait(1));self.assertEqual(self.sdk.releases,[])
                    kernel.now=16.;result=lease.wait()
                    self.assertEqual((result['pending'],result['localKnown']),(1,0))
                    self.assertIs(lease.source,self.source);self.assertIs(lease.sdk,self.sdk)
                    self.assertEqual(kernel.closed,[])
                    v1=self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21)
                    self.assertEqual(self.helper.begin_msaa_hit(v1,self.scope,self.sdk,17.,_kernel=FakeKernel()).record['stageCode'],2)
                finally:
                    release.set()
                    for thread in threads:thread.join(1)
                self.assertFalse(threads[0].is_alive());result=lease.retire(20.)
                self.assertEqual((result['pending'],result['localKnown'],result['localMatch'],result['canonicalStatus']),(0,0,0,2))
                self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(count,count))
                self.assertEqual((result['nativeExit'],result['workerCleanup'],result['variantCleared']),(1,1,1))
                self.assertIsNone(lease.source);self.assertIsNone(lease.sdk)


class RawCallTests(unittest.TestCase):
    def test_control_type_raw_binding_writes_signed_int32_and_returns_plain_numeric_hresult(self):
        helper=load_helper();abi=helper.SdkAbi(**sdk_fixture());observed=[]
        prototype=C.CFUNCTYPE(C.c_int32,C.c_void_p,C.c_void_p)
        @prototype
        def getter(this,out):
            observed.append(1);C.cast(out,C.POINTER(C.c_int32))[0]=-2**31
            return -2147467259
        table=(C.c_void_p*(abi.slots['control_type']+1))()
        table[abi.slots['control_type']]=C.cast(getter,C.c_void_p).value
        instance=C.pointer(C.cast(table,C.POINTER(C.c_void_p)));output=C.c_int32()
        hr=abi.call('control_type',instance,C.byref(output))
        self.assertEqual((hr,output.value),(-2147467259,-2**31))
        self.assertEqual(observed,[1])

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
        self.assertEqual(abi.slots['accessible_query'],0)
        self.assertEqual(abi.slots['accessible_release'],2)
        self.assertIs(abi.signatures['control_type'][0],C.c_int32)


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


class Ia2DiagnosticCalls(CanonicalCalls):
    """Distinct native acquisitions; no names, values or external environment."""
    def __init__(self):
        super().__init__()
        self.identities[211]=311  # Same scoped File tuple, different COM wrapper.
        self.services={value:value+1000 for value in (201,211,202,203,222)}
        self.ia2={value:value+2000 for value in self.services.values()}
        self.tuples={self.ia2[self.services[value]]:(-11 if value in (201,211) else -22,13)
                     for value in self.services}
        self.owned_outputs=[];self.after=None;self.null_at=0
        self.exception_at=0;self.noninteger_at=0
        self.getter_reads={};self.recheck_changes={}

    def call(self,key,pointer,*args):
        value=pointer.value if isinstance(pointer,C.c_void_p) else pointer
        if key=='release':return super().call(key,pointer,*args)
        if key in ('service_query','ia2_query','unique_id','window_handle'):
            self.calls.append((key,value))
            if key=='service_query':
                assert C.string_at(args[0],16)==uuid.UUID('6d5140c1-7436-11ce-8034-00aa006009fa').bytes_le
                args[1]._obj.value=self.services[value]
            elif key=='ia2_query':
                assert C.string_at(args[0],16)==uuid.UUID('618736e0-3c3d-11cf-810c-00aa00389b71').bytes_le
                assert C.string_at(args[1],16)==uuid.UUID('e89f726e-c4f4-4c19-bb19-b647d7fa8478').bytes_le
                args[2]._obj.value=self.ia2[value]
            else:
                ordinal=self.getter_reads.get((value,key),0)+1
                self.getter_reads[value,key]=ordinal
                datum=self.tuples[value][int(key=='window_handle')]
                if ordinal>1:datum=self.recheck_changes.get((value,key),datum)
                args[0]._obj.value=datum
            hr=self.hresult if len(self.calls)==self.failure_at else 0
        else:hr=super().call(key,pointer,*args)
        ordinal=len(self.calls)
        if ordinal==self.null_at:args[-1]._obj.value=None
        if key in ('pattern','accessible','accessible_query','query','service_query','ia2_query'):
            output=args[-1]._obj.value
            if output:self.owned_outputs.append(output)
        if self.after:self.after(key,ordinal)
        if ordinal==self.exception_at:raise KeyboardInterrupt('Synthetic IA2 call exception')
        if ordinal==self.noninteger_at:return True
        return hr


class Ia2DiagnosticV3Tests(unittest.TestCase):
    def setUp(self):
        self.helper=load_helper();self.sdk=Ia2DiagnosticCalls();self.platform=FakePlatform()
        self.platform.window_domain=lambda hwnd,source,scope:1 if hwnd==13 else 0
        self.scope=self.helper.MsaaHitScope(7,8,9,10,11,12,13,14,15)

    def source(self,**changes):
        values=dict(client=9,retained_file=1,fresh_file=11,fresh_target=2,retained_target=3,
            negative_refs=(4,5,6),shell_handle=20,engine_handle=21,keepalive=(self.sdk,),
            captured_at=10.,action_deadline=15.,document_hwnd=30,popup_hwnd=31,
            popup_thread=40,owner_chain=(31,13))
        values.update(changes)
        return self.helper.MsaaHitSourceV3(**values)

    def run_worker(self,source=None):
        return self.helper.run_ia2_diagnostic(source or self.source(),self.scope,self.sdk,self.platform,15.)

    def assert_non_accepting(self,result):
        self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
        self.assertEqual(result['workerSchemaVersion'],3)
        self.assertTrue(all(type(value) is int and 0<=value<=0xffffffff for value in result.values()))
        self.assertNotIn('from_accessible',[key for key,_ in self.sdk.calls])
        self.assertEqual(self.sdk.releases,list(reversed(self.sdk.owned_outputs)))

    def test_profile_three_has_a_separate_non_accepting_entry_and_source(self):
        helper=load_helper()
        for name in ('Ia2SdkAbi','MsaaHitSourceV3','worker_record_v3','_record_v3',
                     'run_ia2_diagnostic','begin_ia2_diagnostic'):
            self.assertTrue(callable(getattr(helper,name,None)),name)

    def test_canonical_mismatch_is_measured_with_exact_full_call_and_reference_budget(self):
        result=self.run_worker();self.assert_non_accepting(result)
        self.assertEqual((result['diagnosticComplete'],result['ia2Status']),(1,1))
        self.assertEqual((result['referencesAcquired'],result['referencesReleased']),(26,26))
        self.assertEqual(len(self.sdk.calls),54)
        counts=dict(compare=5,pattern=4,child_id=4,accessible=5,accessible_query=6,
            control_type=4,hit_test=1,query=1,service_query=5,ia2_query=5,unique_id=7,window_handle=7)
        for operation,count in counts.items():
            self.assertEqual((result[operation+'Attempted'],result[operation+'Completed'],result[operation+'Hresult']),(count,count,0))
        self.assertEqual(self.sdk.calls[:5],[('compare',9)]*5)
        self.assertEqual([value for key,value in self.sdk.calls if key=='pattern'],[1,11,2,3])
        self.assertEqual([value for key,value in self.sdk.calls if key=='accessible'],[101,111,102,103,101])
        self.assertEqual((result['filePairObserved'],result['filePairEqual']),(1,0))
        for key in ('fileOriginalRepeatObserved','fileOriginalRepeatEqual','targetPairObserved','targetPairEqual',
                    'targetDifferentFromFileObserved','targetDifferentFromFile','hitMatchesTargetObserved','hitMatchesTarget',
                    'fileTupleEqual','targetTupleEqual','targetDifferentFilesTuple','hitMatchesTargetsTuple',
                    'hitDifferentFilesTuple','fileAnchorStable','targetAnchorStable','tupleComparisonsObserved'):
            self.assertEqual(result[key],1,key)
        self.assertEqual((result['ia2TupleCount'],result['uidZeroCount'],result['uidNegativeCount']),(5,0,5))
        self.assertEqual((result['variantAttempted'],result['variantCleared'],self.platform.clears),(1,1,[401]))
        for raw in (201,211,302,311,3201,3211,13,0xfffffff5):self.assertNotIn(raw,result.values())

    def test_every_canonical_disagreement_remains_observable_and_never_enables_input(self):
        for pointer,identity in ((221,331),(203,333),(202,301),(222,341)):
            with self.subTest(pointerCode=pointer):
                self.setUp();self.sdk.identities[pointer]=identity
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],len(self.sdk.calls)),(1,54))

    def test_valid_signed_zero_and_positive_unique_ids_are_not_support_filters(self):
        for uid,zero,negative in ((0,5,0),(2**31-1,0,0),(-2**31,0,5)):
            with self.subTest(signCode=(uid>0)-(uid<0)):
                self.setUp();self.sdk.tuples={key:(uid,hwnd) for key,(_,hwnd) in self.sdk.tuples.items()}
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],result['uidZeroCount'],result['uidNegativeCount']),(1,zero,negative))
                self.assertEqual(result['targetDifferentFilesTuple'],0)

    def test_tuple_and_anchor_changes_are_facts_without_canonical_promotion(self):
        for accessible,changed in ((211,(-33,13)),(203,(-44,13)),(222,(-11,13))):
            with self.subTest(accessibleCode=accessible):
                self.setUp();self.sdk.tuples[self.sdk.ia2[self.sdk.services[accessible]]]=changed
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual(result['diagnosticComplete'],1)
        for accessible in (201,202):
            with self.subTest(anchorCode=accessible):
                self.setUp();ia2=self.sdk.ia2[self.sdk.services[accessible]]
                self.sdk.recheck_changes[ia2,'unique_id']=-99
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual(result['fileAnchorStable' if accessible==201 else 'targetAnchorStable'],0)

    def test_uia_positive_false_or_negative_collision_stops_before_native_extraction(self):
        for reason in ('file','target','negative'):
            with self.subTest(reason=reason):
                self.setUp();original=self.sdk.call
                def call(key,pointer,*args):
                    hr=original(key,pointer,*args)
                    if key=='compare' and ((reason=='file' and args[:2]==(1,11)) or
                            (reason=='target' and args[:2]==(2,3))):args[-1]._obj.value=0
                    if key=='compare' and reason=='negative' and args[1]==4:args[-1]._obj.value=1
                    return hr
                self.sdk.call=call;result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],result['patternAttempted']),(0,0))

    def test_non_self_children_bad_menuitem_and_bad_variants_never_continue(self):
        for key,value in [('child',1),('child',-1),('kind',50033),('variant',0),('variant',3),('variant',13),('dispatch',0)]:
            with self.subTest(kind=key,value=value):
                self.setUp()
                if key=='child':self.sdk.children[111]=value
                elif key=='kind':self.sdk.types[11]=value
                elif key=='variant':self.sdk.variant_type=value
                else:self.sdk.variant_pointer=value
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual(result['diagnosticComplete'],0)
                if key in ('variant','dispatch'):self.assertEqual(result['variantCleared'],1)

    def test_nonnull_failed_outputs_and_nulls_are_owned_and_stop_at_each_operation(self):
        baseline=self.run_worker();calls=list(self.sdk.calls)
        outputs={'pattern','accessible','accessible_query','query','service_query','ia2_query'}
        for ordinal,(key,_) in enumerate(calls,1):
            if key not in outputs:continue
            for failure in ('failed','sfalse','null','exception','noninteger'):
                with self.subTest(ordinal=ordinal,failure=failure):
                    self.setUp()
                    if failure in ('failed','sfalse'):
                        self.sdk.failure_at=ordinal;self.sdk.hresult=-2147467259 if failure=='failed' else 1
                    else:setattr(self.sdk,{'null':'null_at','exception':'exception_at','noninteger':'noninteger_at'}[failure],ordinal)
                    result=self.run_worker();self.assert_non_accepting(result)
                    self.assertEqual((result['diagnosticComplete'],len(self.sdk.calls)),(0,ordinal))
                    self.assertEqual(result['referencesAcquired'],len(self.sdk.owned_outputs))

    def test_every_provider_return_deadline_and_process_loss_prevents_next_provider_call(self):
        for ordinal in range(1,55):
            for reason in ('deadline','process'):
                with self.subTest(ordinal=ordinal,reason=reason):
                    self.setUp()
                    def after(key,number):
                        if number==ordinal:
                            if reason=='deadline':self.platform.now=11.5
                            else:self.platform.owns=False
                    self.sdk.after=after;result=self.run_worker();self.assert_non_accepting(result)
                    self.assertEqual((result['diagnosticComplete'],len(self.sdk.calls)),(0,ordinal))

    def test_each_original_guard_boundary_stops_calls_and_preserves_owned_cleanup(self):
        checks=[];self.platform.guard=lambda:checks.append(len(self.sdk.calls)) or True
        result=self.run_worker();self.assertEqual(result['diagnosticComplete'],1)
        for stop,expected_calls in enumerate(checks,1):
            with self.subTest(boundary=stop):
                self.setUp();seen=[]
                def guard():seen.append(1);return len(seen)<stop
                self.platform.guard=guard;result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],len(self.sdk.calls)),(0,expected_calls))

    def test_unsupported_or_foreign_window_domain_stops_without_exporting_the_handle(self):
        for hwnd in (0,0x123456789abc):
            with self.subTest(isNull=int(hwnd==0)):
                self.setUp();self.sdk.tuples[3201]=(-11,hwnd)
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],result['ia2TupleCount']),(0,0))
                if hwnd:self.assertNotIn(hwnd,result.values())

    def test_late_or_failed_cleanup_keeps_facts_but_never_completes(self):
        for failure in ('late','process','release','variant','dpi','uninitialize'):
            with self.subTest(failure=failure):
                self.setUp();original=self.sdk.call
                if failure in ('late','process','release'):
                    def call(key,pointer,*args):
                        hr=original(key,pointer,*args)
                        if key=='release':
                            if failure=='late':self.platform.now=11.5
                            elif failure=='process':self.platform.owns=False
                            else:raise RuntimeError('Synthetic IA2 release failure')
                        return hr
                    self.sdk.call=call
                elif failure=='variant':self.platform.clear_hr=-2147467259
                elif failure=='dpi':self.platform.restore=False
                else:self.platform.uninitialize=lambda:(_ for _ in ()).throw(RuntimeError('Synthetic cleanup failure'))
                result=self.run_worker();self.assert_non_accepting(result)
                self.assertEqual(result['diagnosticComplete'],0)
                self.assertEqual(result['tupleComparisonsObserved'],1)

    def test_freshness_includes_discovery_and_never_resets_the_action_deadline(self):
        for changes,now in ((dict(captured_at=8.),10.),(dict(action_deadline=10.5),10.5),
                            (dict(captured_at=10.),11.5),(dict(captured_at=10.1),10.)):
            with self.subTest(sourceExpired=int(now>=10.5)):
                self.setUp();self.platform.now=now
                result=self.run_worker(self.source(**changes));self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],len(self.sdk.calls)),(0,0))

    def test_aliased_owned_interfaces_are_released_once_for_each_acquisition(self):
        self.sdk.patterns[11]=101
        self.sdk.services={key:1201 for key in self.sdk.services}
        self.sdk.services[221]=1201
        self.sdk.ia2={1201:3201};self.sdk.tuples={3201:(0,13)}
        result=self.run_worker();self.assert_non_accepting(result)
        self.assertEqual((result['diagnosticComplete'],result['referencesAcquired'],len(self.sdk.releases)),(1,26,26))

    def test_sdk_metadata_derives_getter_slots_and_closed_pinned_declaration(self):
        abi=self.helper.Ia2SdkAbi(**sdk_fixture())
        self.assertEqual((abi.slots['unique_id'],abi.slots['window_handle'],abi.slots['ia2_query'],abi.slots['service_query']),(41,42,3,0))
        for key in ('unique_id','window_handle','ia2_query','service_query'):
            self.assertIs(abi.signatures[key][0],C.c_int32)
        self.assertEqual(abi.signatures['unique_id'][1],(C.POINTER(C.c_int32),))
        self.assertEqual(abi.signatures['window_handle'][1],(C.POINTER(C.c_void_p),))
        metadata=self.helper._IA2_METADATA
        for changed in (None,(),metadata[:-1],(*metadata,'unknown')):
            if changed is None:continue
            with self.subTest(shape=len(changed)),self.assertRaises(ValueError):
                self.helper.Ia2SdkAbi(**sdk_fixture(),_metadata=changed)
        for damaged in ('prefix','HRESULT','GUID'):
            args=sdk_fixture()
            if damaged=='prefix':args['accessible_interface']._methods_[0].name='unrecognized_accParent'
            elif damaged=='HRESULT':args['hresult_type']=C.c_int64
            else:args['guid_type']=C.c_int32
            with self.subTest(damaged=damaged),self.assertRaises(ValueError):self.helper.Ia2SdkAbi(**args)

    def test_content_iid_prefix_order_getter_and_service_metadata_all_fail_before_address_binding(self):
        metadata=self.helper._IA2_METADATA
        def replaced(index,value):return metadata[:index]+(value,)+metadata[index+1:]
        variants=[replaced(0,'https://example.invalid/other.idl'),replaced(1,True),replaced(1,30917),
            replaced(2,'0'*64),replaced(3,'00000000-0000-0000-c000-000000000046'),
            replaced(4,'IAccessibleEx'),replaced(5,'IUnknown'),replaced(6,metadata[6][:-1]),
            replaced(7,metadata[7][:-1]),replaced(7,metadata[7][::-1])]
        for index in (0,1):
            original=metadata[8][index]
            for part,value in ((0,'otherGetter'),(1,'method'),(2,('in','retval')),
                               (3,'HRESULT64'),(4,'LONG64*' if index==0 else 'HWND**')):
                getter=original[:part]+(value,)+original[part+1:]
                family=metadata[8][:index]+(getter,)+metadata[8][index+1:]
                variants.append(replaced(8,family))
        for part,value in ((0,'00000000-0000-0000-c000-000000000046'),
                           (1,('QueryInterface','AddRef','QueryService','Release')),
                           (2,('GUID','GUID*','void**')),(3,(1,1,1))):
            service=metadata[9][:part]+(value,)+metadata[9][part+1:]
            variants.append(replaced(9,service))
        for ordinal,changed in enumerate(variants):
            with self.subTest(case=ordinal):
                calls=[];arguments=sdk_fixture()
                arguments['function_factory']=lambda *args:calls.append(1)
                with self.assertRaises(ValueError):self.helper.Ia2SdkAbi(**arguments,_metadata=changed)
                self.assertEqual(calls,[])

    def test_mutating_unused_sdk_inherited_order_is_not_treated_as_a_getter_slot_hint(self):
        for index in range(21):
            with self.subTest(entry=index):
                args=sdk_fixture();methods=args['accessible_interface']._methods_
                methods[index].name='wrongPrefixEntry'
                with self.assertRaises(ValueError):self.helper.Ia2SdkAbi(**args)

    def test_actual_raw_typed_getters_write_only_the_declared_outputs(self):
        abi=self.helper.Ia2SdkAbi(**sdk_fixture());observed=[]
        for operation,kind,value in (('unique_id',C.c_int32,-2**31),('window_handle',C.c_void_p,0x123456789abc)):
            prototype=C.CFUNCTYPE(C.c_int32,C.c_void_p,C.c_void_p)
            @prototype
            def getter(this,out):
                observed.append(operation);C.cast(out,C.POINTER(kind))[0]=value;return -2147467259
            table=(C.c_void_p*46)();table[abi.slots[operation]]=C.cast(getter,C.c_void_p).value
            instance=C.pointer(C.cast(table,C.POINTER(C.c_void_p)));output=kind()
            self.assertEqual(abi.call(operation,instance,C.byref(output)),-2147467259)
            self.assertEqual(output.value,value)
        self.assertEqual(observed,['unique_id','window_handle'])

    def test_actual_raw_query_service_uses_both_exact_iids_and_separately_owned_output(self):
        abi=self.helper.Ia2SdkAbi(**sdk_fixture());observed=[]
        prototype=C.CFUNCTYPE(C.c_int32,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p)
        @prototype
        def query(this,service,interface,out):
            observed.append((C.string_at(service,16),C.string_at(interface,16)))
            C.cast(out,C.POINTER(C.c_void_p))[0]=0x123456789abc
            return -2147467259
        table=(C.c_void_p*4)();table[abi.slots['ia2_query']]=C.cast(query,C.c_void_p).value
        instance=C.pointer(C.cast(table,C.POINTER(C.c_void_p)));output=C.c_void_p()
        service=Guid('618736e0-3c3d-11cf-810c-00aa00389b71')
        interface=Guid('e89f726e-c4f4-4c19-bb19-b647d7fa8478')
        self.assertEqual(abi.call('ia2_query',instance,C.byref(service),C.byref(interface),C.byref(output)),-2147467259)
        self.assertEqual(output.value,0x123456789abc)
        self.assertEqual(observed,[(uuid.UUID('618736e0-3c3d-11cf-810c-00aa00389b71').bytes_le,
            uuid.UUID('e89f726e-c4f4-4c19-bb19-b647d7fa8478').bytes_le)])

    def test_sdk_borrowed_source_checks_real_interfaces_and_never_relabels_v2(self):
        from dataclasses import replace
        metadata=sdk_fixture();abi=self.helper.Ia2SdkAbi(**metadata)
        def ref(interface,value):return type('Borrowed',(C.c_void_p,),{'__com_interface__':interface})(value)
        client=ref(metadata['client_interface'],9)
        elements=[ref(metadata['element_interface'],number) for number in (1,11,2,3,4,5,6)]
        source=self.source(client=client,retained_file=elements[0],fresh_file=elements[1],fresh_target=elements[2],
            retained_target=elements[3],negative_refs=tuple(elements[4:]))
        self.assertTrue(abi.matches_source(source))
        for field in ('client','retained_file','fresh_file','fresh_target','retained_target'):
            self.assertFalse(abi.matches_source(replace(source,**{field:C.c_void_p(99)})))
        for value in ((),(elements[4],),[elements[4],elements[5]],(None,elements[4])):
            self.assertFalse(abi.matches_source(replace(source,negative_refs=value)))
        with self.assertRaises(ValueError):
            self.helper.begin_msaa_hit(source,self.scope,abi,15.,profile_version=3,_kernel=FakeKernel())

    def test_diagnostic_lease_uses_shared_registry_and_strict_non_positive_worker_packet(self):
        for damage in ('none','positiveKnown','positiveMatch','v1','v2','extra','missing','bool'):
            with self.subTest(packet=damage):
                self.setUp();kernel=FakeKernel()
                def worker(*args):
                    record=self.run_worker()
                    if damage=='positiveKnown':record['localKnown']=1
                    elif damage=='positiveMatch':record['localMatch']=1
                    elif damage=='v1':return self.helper.worker_record()
                    elif damage=='v2':return self.helper.worker_record_v2()
                    elif damage=='extra':record['unexpected']=0
                    elif damage=='missing':record.pop('ia2Status')
                    elif damage=='bool':record['diagnosticComplete']=True
                    return record
                kernel.worker=worker
                lease=self.helper.begin_ia2_diagnostic(self.source(),self.scope,self.sdk,15.,_kernel=kernel)
                result=lease.wait()
                self.assertEqual((result['schemaVersion'],result['localKnown'],result['localMatch'],result['diagnosticOnly'],result['acceptanceEligible']),(3,0,0,1,0))
                self.assertEqual(result['workerException'],int(damage!='none'))
                if lease.pending:self.helper._active=None  # All synthetic callbacks returned; no native refs.

    def test_pending_late_and_unknown_native_exit_never_admit_another_profile(self):
        kernel=FakeKernel();kernel.finished=False
        kernel.worker=lambda *args:self.run_worker()
        lease=self.helper.begin_ia2_diagnostic(self.source(),self.scope,self.sdk,15.,_kernel=kernel)
        result=lease.wait();self.assertEqual((result['pending'],result['diagnosticComplete']),(1,0))
        self.assertIs(lease.source.keepalive[0],self.sdk)
        old=self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21)
        second=self.helper.begin_msaa_hit(old,self.scope,self.sdk,15.,_kernel=FakeKernel())
        self.assertEqual(second.record['stageCode'],2)
        kernel.finished=True;kernel.now=12.
        result=lease.retire(20.)
        self.assertEqual((result['pending'],result['localKnown'],result['localMatch'],result['diagnosticComplete']),(0,0,0,0))
        self.assertIsNone(lease.source);self.assertIsNone(self.helper.pending_msaa_hit())

    def test_begin_requires_original_deadline_and_fresh_captured_source_before_native_start(self):
        for deadline,changes in ((14.,{}),(15.,dict(captured_at=8.)),(15.,dict(captured_at=11.))):
            with self.subTest(deadline=deadline):
                kernel=FakeKernel();lease=self.helper.begin_ia2_diagnostic(self.source(**changes),self.scope,self.sdk,deadline,_kernel=kernel)
                self.assertEqual(lease.record['nativeAttempted'],0)
                self.assertEqual(kernel.duplicates,[])
                self.assertIsNone(kernel.callback)

    def test_diagnostic_kernel_dispatch_cannot_call_either_positive_worker(self):
        from unittest.mock import patch
        kernel=self.helper.Ia2WindowsKernel.__new__(self.helper.Ia2WindowsKernel);calls=[]
        with patch.object(self.helper,'run_ia2_diagnostic',side_effect=lambda *args:calls.append(3) or 3), \
                patch.object(self.helper,'run_local_hit',side_effect=AssertionError('v1 diagnostic fallback')), \
                patch.object(self.helper,'run_canonical_hit',side_effect=AssertionError('v2 diagnostic fallback')):
            self.assertEqual(kernel.worker(self.source(),self.scope,self.sdk,11.5),3)
            for source in (self.helper.MsaaHitSource(9,1,2,3,(4,5),20,21),
                           self.helper.MsaaHitSourceV2(9,1,11,2,3,(4,5),20,21,(self.sdk,)),object()):
                with self.assertRaises(ValueError):kernel.worker(source,self.scope,self.sdk,11.5)
        self.assertEqual(calls,[3])

    def test_source_lifetime_and_window_context_are_closed_before_any_provider_call(self):
        changes=[dict(keepalive=()),dict(shell_handle=True),dict(engine_handle=0),
            dict(captured_at=True),dict(action_deadline=float('inf')),
            dict(document_hwnd=0),dict(popup_hwnd=True),dict(popup_thread=0),
            dict(owner_chain=[]),dict(owner_chain=(99,13)),dict(owner_chain=(31,99))]
        for ordinal,change in enumerate(changes):
            with self.subTest(case=ordinal):
                self.setUp();result=self.run_worker(self.source(**change));self.assert_non_accepting(result)
                self.assertEqual((result['diagnosticComplete'],len(self.sdk.calls)),(0,0))

    def test_collection_after_expiry_nonzero_exit_or_callback_mismatch_never_completes(self):
        for reason in ('late','process','exit','callback','retire'):
            with self.subTest(reason=reason):
                self.setUp();kernel=FakeKernel()
                kernel.worker=lambda *args:self.run_worker()
                lease=self.helper.begin_ia2_diagnostic(self.source(),self.scope,self.sdk,15.,_kernel=kernel)
                if reason=='late':kernel.now=11.5
                elif reason=='process':kernel.identity_failure=True
                elif reason=='exit':kernel.exit_code=86
                elif reason=='callback':kernel.callback_identity_failure=True
                result=lease.retire(20.) if reason=='retire' else lease.wait()
                self.assertEqual((result['localKnown'],result['localMatch'],result['diagnosticComplete']),(0,0,0))
                if lease.pending:self.helper._active=None  # Synchronous synthetic callback is already finished.

    def test_native_launch_stays_disabled_without_the_existing_controller_fence(self):
        self.assertFalse(self.helper.NATIVE_LAUNCH_ENABLED)
        lease=self.helper.begin_ia2_diagnostic(self.source(),self.scope,object(),15.,native_enabled=True)
        self.assertEqual((lease.record['nativeAttempted'],lease.record['schemaVersion'],lease.record['diagnosticComplete']),(0,3,0))
        self.assertIsNone(self.helper.pending_msaa_hit())

    def numeric_kernel(self):
        kernel=self.helper.Ia2WindowsKernel.__new__(self.helper.Ia2WindowsKernel)
        kernel.processes={120:(10,11),121:(8,9)}
        kernel.check_process=lambda handle,pid,birth:True
        kernel._diagnostic_source=self.source(owner_chain=(31,33,13));kernel._diagnostic_scope=self.scope
        class Point(C.Structure):_fields_=[('x',C.c_int32),('y',C.c_int32)]
        class Rect(C.Structure):_fields_=[('left',C.c_int32),('top',C.c_int32),('right',C.c_int32),('bottom',C.c_int32)]
        class Gui(C.Structure):
            _fields_=[('cbSize',C.c_uint32),('flags',C.c_uint32),
                *((name,C.c_void_p) for name in ('active','focus','capture','menu','move','caret')),('caretRect',Rect)]
        kernel.Point=Point;kernel.Gui=Gui
        state=dict(processes={30:(50,10),12:(50,10),13:(40,8),31:(40,8),32:(40,8),33:(40,8)},
            parent=12,root=30,owners={31:33,33:13},foreground=31,physical=31,
            focus=32,focusRoot=31,capture=0,menu=31,visible=True,enabled=True,iconic=False,gui=True)
        def process(hwnd,out):
            thread,pid=state['processes'].get(hwnd,(0,0));out._obj.value=pid;return thread
        def gui(thread,out):
            if thread!=40 or not state['gui']:return 0
            self.assertEqual(out._obj.cbSize,C.sizeof(Gui))
            out._obj.focus=state['focus'];out._obj.capture=state['capture'];out._obj.menu=state['menu']
            return 1
        kernel.user=NS(IsWindow=lambda hwnd:int(hwnd in state['processes']),
            IsWindowVisible=lambda hwnd:state['visible'],IsWindowEnabled=lambda hwnd:state['enabled'],
            IsIconic=lambda hwnd:state['iconic'],GetWindowThreadProcessId=process,
            GetParent=lambda hwnd:state['parent'],
            GetAncestor=lambda hwnd,flag:state['focusRoot'] if hwnd==state['focus'] else state['root'],
            GetWindow=lambda hwnd,flag:state['owners'].get(hwnd,0),
            GetForegroundWindow=lambda:state['foreground'],
            WindowFromPhysicalPoint=lambda point:state['physical'] if (point.x,point.y)==(14,15) else 0,
            GetGUIThreadInfo=gui)
        return kernel,state

    def test_actual_native_guard_rechecks_original_physical_popup_and_process_window_contract(self):
        kernel,state=self.numeric_kernel();self.assertTrue(kernel.guard())
        mutations=[lambda s:s.update(parent=99),lambda s:s.update(root=99),
            lambda s:s['owners'].update({31:99}),lambda s:s.update(foreground=99),
            lambda s:s.update(physical=13),lambda s:s.update(focus=99),
            lambda s:s.update(focusRoot=99),lambda s:s.update(capture=99),lambda s:s.update(menu=99),
            lambda s:s.update(visible=False),lambda s:s.update(enabled=False),
            lambda s:s.update(iconic=True),lambda s:s.update(gui=False),
            lambda s:s['processes'].update({31:(41,8)}),lambda s:s['processes'].update({13:(40,9)}),
            lambda s:s['processes'].update({30:(50,8)}),lambda s:s['processes'].update({12:(50,8)}),
            lambda s:s['processes'].update({32:(40,10)}),lambda s:s['processes'].pop(33),
            lambda s:s['processes'].update({33:(40,99)})]
        for ordinal,mutate in enumerate(mutations):
            with self.subTest(boundary=ordinal):
                kernel,state=self.numeric_kernel();mutate(state);self.assertFalse(kernel.guard())
        kernel,state=self.numeric_kernel();kernel.check_process=lambda *args:False
        self.assertFalse(kernel.guard())

    def test_actual_native_window_domain_is_a_closed_enum_with_no_foreign_owner_fallback(self):
        kernel,state=self.numeric_kernel();source=kernel._diagnostic_source
        self.assertEqual([kernel.window_domain(hwnd,source,self.scope) for hwnd in (13,31,12,30,33,99)],
                         [1,2,3,4,5,0])
        state['foreground']=99
        self.assertEqual(kernel.window_domain(13,source,self.scope),0)

    def test_complete_worker_packets_cannot_forge_consistent_but_incomplete_call_or_reference_counts(self):
        for damage in ('bindingCall','ownedReference'):
            with self.subTest(packet=damage):
                self.setUp();kernel=FakeKernel();valid=self.run_worker()
                self.assertEqual(valid['diagnosticComplete'],1)
                def worker(*args):
                    record=dict(valid)
                    if damage=='bindingCall':record.update(patternAttempted=3,patternCompleted=3)
                    else:record.update(referencesAcquired=25,referencesReleased=25)
                    return record
                kernel.worker=worker
                lease=self.helper.begin_ia2_diagnostic(self.source(),self.scope,self.sdk,15.,_kernel=kernel)
                result=lease.wait()
                self.assertEqual((result['workerException'],result['diagnosticComplete'],result['pending']),(1,0,1))
                self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
                self.helper._active=None  # Synchronous synthetic worker already returned; no native callback.

    def test_complete_worker_packets_reject_out_of_range_boolean_observations(self):
        for field in ('filePairEqual','targetTupleEqual','fileAnchorStable','tupleComparisonsObserved'):
            with self.subTest(field=field):
                self.setUp();kernel=FakeKernel();valid=self.run_worker()
                self.assertEqual(valid['diagnosticComplete'],1)
                kernel.worker=lambda *args:dict(valid,**{field:2})
                lease=self.helper.begin_ia2_diagnostic(self.source(),self.scope,self.sdk,15.,_kernel=kernel)
                result=lease.wait()
                self.assertEqual((result['workerException'],result['diagnosticComplete'],result['pending']),(1,0,1))
                self.assertEqual((result['localKnown'],result['localMatch']),(0,0))
                self.helper._active=None  # Finished synthetic callback, no native thread or references.


if __name__=='__main__':unittest.main()
