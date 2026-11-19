"""Synthetic real-controller/SDK comparison observation; no Windows COM or input."""
import copy
import ctypes as C
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch
import test_owned_native_menu as boundaries
import test_native_menu_msaa_hit as metadata

class RetainedNativeCompareTests(unittest.TestCase):
    def fixture(self, *, profile=True, raw_bool=0, raw_hr=0):
        owner=boundaries.OwnedNativeMenuTests('runTest');self.addCleanup(owner.doCleanups)
        m,api,process,record,clock,b=owner.real_chrome_fixture()
        abi=importlib.import_module('native_menu_msaa_hit')
        spec=metadata.sdk_fixture()
        spec['element_interface']._methods_.append(b.interface._methods_[0])
        sdk=abi.SdkAbi(**spec);state=dict(rawCalls=0,inRole=False,thread=17,rawBool=raw_bool,rawHr=raw_hr)
        proto=C.CFUNCTYPE(C.c_int32,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p)
        def native(this,left,right,out):
            state['rawCalls']+=1
            self.assertEqual(left,right)
            C.cast(out,C.POINTER(C.c_int32))[0]=state['rawBool']
            callback=state.get('afterRaw')
            if callback:callback()
            return state['rawHr']
        callback=proto(native);slot=sdk.slots['compare']
        table=(C.c_void_p*(slot+1))();table[slot]=C.cast(callback,C.c_void_p).value
        obj=(C.c_void_p*1)(C.cast(table,C.c_void_p).value)
        client_type=type('SyntheticClient',(C.c_void_p,),{'__com_interface__':spec['client_interface']})
        client=client_type(C.addressof(obj))
        for name,value in vars(b.probe.uia.iuia).items():setattr(client,name,value)
        original_node=b.Node
        class Node(C.c_void_p,original_node):
            __com_interface__=spec['element_interface']
            def __init__(self,key):
                C.c_void_p.__init__(self,4096+16*(b.wrapper_count+1));original_node.__init__(self,key)
        b.Node=Node
        high=b.compare
        def compare(left,right):
            if state['inRole'] and left is right and left.key=='file':
                if 'throwHigh' in state:raise state['throwHigh']
                return False
            return high(left,right)
        client.CompareElements=compare
        probe=b.probe;probe.uia.iuia=client;probe.provider_client=client
        probe._uia_library=NS(IUIAutomation=spec['client_interface'],IUIAutomationElement=spec['element_interface'],
            IUIAutomationLegacyIAccessiblePattern=spec['legacy_interface'])
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        def apartment(kind,qualifier):
            kind._obj.value=1;qualifier._obj.value=0;return 0
        ole=NS(CoGetApartmentType=Function(apartment))
        probe.kernel=NS(GetCurrentThreadId=Function(lambda:state['thread']))
        probe.foreground=m.NativeActivationProbe.foreground.__get__(probe)
        probe.last_foreground_snapshot=dict(rawHwnd=11,rootHwnd=11)
        self.enterContext(patch.object(C,'WinDLL',lambda name:ole,create=True))
        self.enterContext(patch.object(C,'WINFUNCTYPE',C.CFUNCTYPE,create=True))
        com=ModuleType('comtypes');com.GUID=spec['guid_type'];com.HRESULT=spec['hresult_type']
        automation=ModuleType('comtypes.automation');automation.VARIANT=spec['variant_type']
        self.enterContext(patch.dict(sys.modules,{'comtypes':com,'comtypes.automation':automation}))
        probe._native_point_profile=profile;probe._native_point_profile_version=1;probe._native_identity_diagnostic=0
        if profile:
            process.opengeul_native_menu_point_profile=True
            probe._admit_provider_creator()
        b.native.engine['handleValue']=9
        original_role=probe._role
        def role(element):
            state['inRole']=True
            try:return original_role(element)
            finally:state['inRole']=False
        probe._role=role
        state['keepalive']=(callback,table,obj,client,Node,abi,spec)
        return m,api,process,record,clock,b,state

    def run_failure(self,fixture, before_collect=None):
        m,api,process,record,clock,b,state=fixture
        observer=None
        try:observer=importlib.import_module('native_menu_self_compare_observer')
        except ModuleNotFoundError:pass
        saved={}
        if observer is not None:
            original=observer.collect
            def collecting(probe,left,right):
                saved['primary']=sys.exception()
                saved['interop']=dict(probe.interop)
                saved['lastCall']=copy.deepcopy(probe.interop.get('lastCall'))
                saved['roleRows']=copy.deepcopy(probe.interop.get('lastRoleComparisons'))
                saved['attrs']={n:(n in vars(probe),vars(probe).get(n)) for n in
                    ('_diagnostic_sink','_observed_call','_last_call_exception','provider_timeout_verified','last_foreground_snapshot')}
                saved['exceptionState']=(saved['primary'].__cause__,saved['primary'].__context__,saved['primary'].__suppress_context__)
                cleanup=before_collect(fixture) if before_collect else None
                try:value=original(probe,left,right)
                finally:
                    if callable(cleanup):cleanup()
                for n,(present,old) in saved['attrs'].items():
                    self.assertEqual(n in vars(probe),present)
                    if present:self.assertIs(vars(probe)[n],old)
                self.assertEqual(probe.interop.get('lastCall'),saved['lastCall'])
                self.assertEqual(probe.interop.get('lastRoleComparisons'),saved['roleRows'])
                for k,old in saved['interop'].items():self.assertIs(probe.interop[k],old)
                return value
            self.enterContext(patch.object(observer,'collect',collecting))
        caught=None
        try:m.click_native_menu_action(api,process,11,record,'save',probe=b.probe,clock=clock)
        except BaseException as error:caught=error
        self.assertIs(type(caught),AssertionError)
        self.assertEqual(caught.args,('Retained native menu self comparison failed',))
        if saved:
            self.assertIs(caught,saved['primary'])
            self.assertEqual((caught.__cause__,caught.__context__,caught.__suppress_context__),saved['exceptionState'])
        self.assertEqual([x for x in b.native.calls if type(x) is tuple and x[0] in ('click','key')],[])
        self.assertIn(('close',9),b.native.calls);self.assertIn('dpi-restore',b.native.calls)
        action=record['nativeMenuActions'][-1]
        self.assertIs(action['success'],False);self.assertIs(action['engineHandleReleased'],True)
        self.assertIn('retainedSelfNativeObservation',b.probe.interop,
            'C2 must retain a closed observation or explicit unknown without changing its failure')
        return b.probe.interop['retainedSelfNativeObservation'],state,action

    def test_raw_success_false_and_true_never_change_the_original_failure(self):
        for value in (0,1):
            with self.subTest(value=value):
                observation,state,action=self.run_failure(self.fixture(raw_bool=value))
                self.assertEqual(state['rawCalls'],1)
                self.assertEqual(observation['statusCode'],1)
                self.assertEqual(observation['observedMask']&12,12)
                self.assertEqual(observation['outBoolBits'],value)
                self.assertEqual(observation['acceptanceEligible'],0)

    def test_normal_profile_is_explicit_unknown_and_never_synthesizes_prerequisites(self):
        fixture=self.fixture(profile=False)
        observation,state,action=self.run_failure(fixture)
        self.assertEqual(state['rawCalls'],0);self.assertEqual(observation['observedMask'],0)
        self.assertNotIn('_provider_creator',vars(fixture[5].probe))
        self.assertNotIn('_point_source',vars(fixture[5].probe))

    def test_wrong_thread_expiry_pending_foreign_binding_and_handle_make_no_raw_call(self):
        def wrong_thread(f):f[6]['thread']=18
        def expired(f):f[4].now=6.
        def pending(f):
            change=patch.object(f[6]['keepalive'][-2],'_active',NS(pending=True))
            change.start();return change.stop
        def foreign_binding(f):f[1].attachment=lambda hwnd:(55,56,999)
        def foreign_handle(f):f[5].probe._point_source['engineHandle']=10
        for change in (wrong_thread,expired,pending,foreign_binding,foreign_handle):
            with self.subTest(change=change.__name__):
                observation,state,action=self.run_failure(self.fixture(),change)
                self.assertEqual(state['rawCalls'],0)
                self.assertEqual(observation['nativeAttempted'],0)
                self.assertNotEqual(observation['statusCode'],1)

    def test_unsupported_sdk_flags_or_bool_width_make_no_raw_call(self):
        for damage in ('flags','width'):
            def change(f):
                item=f[6]['keepalive'][-1]['client_interface']._methods_[-1]
                if damage=='flags':item.paramflags=((1,'a'),(1,'b'),(2,'c'))
                else:item.argtypes=(*item.argtypes[:2],C.POINTER(C.c_int16))
            with self.subTest(damage=damage):
                observation,state,action=self.run_failure(self.fixture(),change)
                self.assertEqual(state['rawCalls'],0);self.assertNotEqual(observation['statusCode'],1)

    def test_failed_native_hresult_does_not_label_initial_out_as_false(self):
        observation,state,action=self.run_failure(self.fixture(raw_hr=-2147467259))
        self.assertEqual(state['rawCalls'],1)
        self.assertTrue(observation['observedMask']&4)
        self.assertFalse(observation['observedMask']&8)
        self.assertEqual(observation['hresultBits'],2147500037)
        self.assertEqual(observation['acceptanceEligible'],0)

    def test_expiry_after_native_return_preserves_prefix_without_completing_observation(self):
        fixture=self.fixture();fixture[6]['afterRaw']=lambda:setattr(fixture[4],'now',6.)
        observation,state,action=self.run_failure(fixture)
        self.assertEqual(state['rawCalls'],1);self.assertNotEqual(observation['statusCode'],1)
        self.assertEqual(observation['acceptanceEligible'],0)

    def test_setup_failure_and_late_foreign_owner_never_replace_the_primary(self):
        def bad_setup(f):
            def failed():raise TypeError('Synthetic setup failure')
            change=patch.object(f[5].probe,'_provider_timeout',side_effect=failed)
            change.start();return change.stop
        observation,state,action=self.run_failure(self.fixture(),bad_setup)
        self.assertEqual(state['rawCalls'],0);self.assertEqual(observation['nativeAttempted'],0)
        fixture=self.fixture();fixture[6]['afterRaw']=lambda:setattr(fixture[1],'attachment',lambda h:(55,56,999))
        observation,state,action=self.run_failure(fixture)
        self.assertEqual(state['rawCalls'],1);self.assertNotEqual(observation['statusCode'],1)

    def test_throwing_original_com_call_never_enters_c2_or_raw_observation(self):
        fixture=self.fixture();m,api,process,record,clock,b,state=fixture
        class Failure(Exception):
            def __str__(self):raise AssertionError('Exception text read')
            def __repr__(self):raise AssertionError('Exception representation read')
        primary=Failure();state['throwHigh']=primary
        caught=None
        try:m.click_native_menu_action(api,process,11,record,'save',probe=b.probe,clock=clock)
        except BaseException as error:caught=error
        self.assertIs(caught,primary);self.assertEqual(state['rawCalls'],0)
        self.assertNotIn('retainedSelfNativeObservation',b.probe.interop)

    def test_existing_diagnostic_sink_does_not_start_or_publish_another_observation(self):
        fixture=self.fixture();m,api,process,record,clock,b,state=fixture
        observer=importlib.import_module('native_menu_self_compare_observer')
        b.probe._diagnostic_sink={}
        with patch.object(observer,'collect',wraps=observer.collect) as collect:
            with self.assertRaisesRegex(AssertionError,'Retained native menu self comparison failed'):
                m.click_native_menu_action(api,process,11,record,'save',probe=b.probe,clock=clock)
        self.assertEqual(collect.call_count,0)
        self.assertEqual(state['rawCalls'],0)
        self.assertNotIn('retainedSelfNativeObservation',b.probe.interop)

    def test_collector_cannot_initialize_or_recreate_a_uia_client(self):
        def no_initialization(f):
            change=patch.object(f[5].probe,'_ensure_provider',side_effect=AssertionError('Unexpected provider initialization'))
            change.start();return change.stop
        observation,state,action=self.run_failure(self.fixture(),no_initialization)
        self.assertEqual(state['rawCalls'],1)
        self.assertEqual(observation['statusCode'],1)

if __name__=='__main__':unittest.main()
