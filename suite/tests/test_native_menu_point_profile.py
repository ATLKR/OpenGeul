"""Opt-in point profile lifetime boundaries; native calls remain synthetic."""
import copy
import ctypes as C
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import test_owned_native_menu as boundaries
import test_native_menu_point_proof as receipts


class NativeMenuPointProfileTests(unittest.TestCase):
    def test_private_client_creation_measures_mta_before_create_and_again_after_it(self):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,boundary,calls,(user,kernel,dwm),context=owner.lazy_provider_boundary()
        with context:
            probe=module.NativeMenuProbe(clock()+5,clock,user=user,kernel=kernel,dwm=dwm,native_point_profile=True)
            def apartment():calls.append(('mta',));return 123,True
            probe._mta_snapshot=apartment;probe._root(56)
        creation=calls.index(('create',));mta=[index for index,row in enumerate(calls) if row==('mta',)]
        self.assertEqual(len(mta),2);self.assertLess(mta[0],creation);self.assertLess(creation,mta[1])

    def fixture(self):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,boundary=owner.real_chrome_fixture()
        probe=boundary.probe;binding=dict(document=11,parent=55,child=56,officePid=88)
        probe.begin_identity_scope(binding,boundary.native.shell,boundary.native.engine,1.,6.,'save',False)
        probe.bind_menu_classification(module._menu_scope(binding,boundary.native.shell,boundary.native.engine,1.,6.),lambda:None)
        probe.snapshot(binding,'file');boundary.native.opened=True
        probe.snapshot(binding,'save')
        probe._native_point_profile=True;probe._physical_file_refresh=True
        probe._provider_creator=dict(threadId=123,mta=True)
        probe._mta_snapshot=lambda:(123,True)
        probe._point_source=dict(shellHandle=8,engineHandle=9)
        proof_owner=receipts.NativeMenuPointProofTests(methodName='runTest');self.addCleanup(proof_owner.doCleanups)
        _,_,_,hit=proof_owner.fixture();provider=copy.deepcopy(hit['providerLocalProof']['provider'])
        import native_menu_msaa_hit as helper
        state=NS(pending=False,waited=False,post_query=False)
        lease=NS(scope=helper.MsaaHitScope(1,88,200,77,100,55,56,50,70),pending=False)
        def wait():state.waited=True;lease.pending=state.pending;return copy.deepcopy(provider)
        lease.wait=wait
        calls=[]
        def begin(file,target,negative,scope_id,point):
            calls.append((file.key,target.key,[node.key for node in negative],scope_id,list(point)))
            return lease
        probe._begin_point_lease=begin
        original=probe.window_snapshot
        probe.window_snapshot=lambda hwnd:dict(original(hwnd),rectangle=[0,45,258,689] if hwnd==99 else [0,0,800,900],iconic=False,cloaked=0)
        def class_name(hwnd,buffer,size):buffer.value='SALTMPSUBFRAME';return len(buffer.value)
        probe.user.GetClassNameW=class_name
        probe.user.GetWindowLongW=lambda hwnd,index:0x80000000 if index==-16 else 0x80
        class Pane(boundary.Node):
            @property
            def CurrentControlType(self):return 50033
            @property
            def CurrentNativeWindowHandle(self):return 99
        return module,probe,boundary,binding,state,lease,calls,Pane('popup')

    def test_provider_creation_is_mta_and_bound_to_original_creator_thread(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        probe._provider_creator=None
        probe._admit_provider_creator()
        self.assertEqual(probe._provider_creator,dict(threadId=123,mta=True))
        self.assertEqual(probe._require_provider_creator(),dict(threadId=123,mta=True,sameThread=True))
        for current in ((123,False),(124,True)):
            probe._mta_snapshot=lambda:current
            with self.assertRaises(AssertionError):probe._require_provider_creator()

    def test_invalid_initial_mta_or_duplicate_creator_cannot_admit(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        with self.assertRaises(AssertionError):probe._admit_provider_creator()
        probe._provider_creator=None;probe._mta_snapshot=lambda:(123,False)
        with self.assertRaises(AssertionError):probe._admit_provider_creator()
        self.assertIsNone(probe._provider_creator)

    def test_local_proof_rechecks_live_popup_and_fresh_target_after_native_exit(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        result=probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)
        self.assertTrue(state.waited)
        self.assertEqual(result['before'],result['after'])
        self.assertEqual(result['sourceScope']['x'],50)
        self.assertEqual(calls[0][0:2],('file','save'))
        self.assertEqual(calls[0][2],['file','bar','peer','edit','popup'])
        self.assertTrue(all(result['fresh']['positive'].values()))

    def test_pending_worker_blocks_post_com_queries_and_provider_reference_release(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture();state.pending=True
        def fresh(target):state.post_query=True;raise AssertionError('Unexpected post COM call')
        probe._fresh_proof=fresh
        with self.assertRaises(AssertionError):probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)
        self.assertFalse(state.post_query)
        original=probe._uia
        self.assertFalse(probe.close_provider())
        self.assertIs(probe._uia,original)
        self.assertTrue(probe.interop['providerRetainedForPending'])

    def test_failed_or_late_local_result_never_starts_post_provider_work(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        lease.wait=lambda:dict(localKnown=0,localMatch=0,pending=0)
        probe._fresh_proof=lambda target:self.fail('Failed local call started post COM work')
        with self.assertRaises(AssertionError):probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)

    def test_started_global_lease_survives_base_exception_before_probe_assignment(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        import native_menu_msaa_hit as helper
        def begin(*args):raise KeyboardInterrupt()
        probe._begin_point_lease=begin;lease.pending=True
        with patch.object(helper,'pending_msaa_hit',return_value=lease):
            with self.assertRaises(KeyboardInterrupt):probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)
            probe._msaa_lease=None;original=probe._uia
            probe.observe_failure_context(binding)
            self.assertEqual(probe.interop['failureContext'],dict(providerPending=1,providerQueriesSuppressed=1))
            self.assertFalse(probe.close_provider());self.assertIs(probe._uia,original)


class NativeMenuCanonicalProfileTests(unittest.TestCase):
    fixture=NativeMenuPointProfileTests.fixture

    def test_fresh_discovery_returns_the_same_observed_mapping_and_preserves_old_dict_api(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        self.assertTrue(callable(getattr(probe,'_fresh_proof_with_refs',None)))
        proof,fresh=probe._fresh_proof_with_refs('save')
        self.assertEqual(set(fresh),set(probe._identity_refs))
        self.assertTrue(all(proof['positive'].values()))
        self.assertIsNot(fresh['file'],probe._identity_refs['file'])
        self.assertIsNot(fresh['target:save'],probe._identity_refs['target:save'])
        self.assertEqual(type(probe._fresh_proof('save')),dict)

    def test_v2_lease_receives_actual_fresh_refs_before_wait_and_post_fresh_after_exit(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        self.assertTrue(callable(getattr(probe,'_fresh_proof_with_refs',None)))
        probe._native_point_profile_version=2;observed=[]
        snapshot=probe.snapshot(binding,'save')
        provider=receipts.canonical_provider_point(snapshot,target='save')['providerLocalProof']['provider']
        original=probe._fresh_proof_with_refs
        def fresh(target):
            self.assertFalse(state.waited)
            result=original(target);observed.append(result);return result
        probe._fresh_proof_with_refs=fresh
        def begin(file,target,negative,scope_id,point,*,fresh_refs=None):
            self.assertIs(fresh_refs,observed[0][1]);self.assertEqual(target.key,'save')
            self.assertIsNot(fresh_refs['file'],probe._identity_refs['file'])
            self.assertIsNot(fresh_refs['target:save'],probe._identity_refs['target:save'])
            return lease
        def wait():state.waited=True;return copy.deepcopy(provider)
        probe._begin_point_lease=begin;lease.wait=wait
        # The old dict-only API is separately observed after the worker exit.
        probe._fresh_proof=lambda target:copy.deepcopy(snapshot['identityProof']) if state.waited else self.fail('Post proof preceded native exit')
        result=probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)
        self.assertEqual(result['schemaVersion'],2)
        self.assertEqual(result['method'],'owned-popup-and-msaa-canonical-hit-v2')
        self.assertEqual(result['sourceFresh'],observed[0][0]);self.assertTrue(state.waited)
        self.assertEqual(result['before'],result['after'])

    def test_wrong_current_target_or_pending_v2_result_cannot_start_post_queries(self):
        for damage in ('target','pending','unknown'):
            with self.subTest(damage=damage):
                module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
                self.assertTrue(callable(getattr(probe,'_fresh_proof_with_refs',None)))
                probe._native_point_profile_version=2;started=[]
                original=probe._fresh_proof_with_refs
                def fresh(target):
                    proof,refs=original(target)
                    if damage=='target':refs['target:save']=boundary.Node('open')
                    return proof,refs
                probe._fresh_proof_with_refs=fresh
                def begin(*args,**kwargs):started.append(1);return lease
                probe._begin_point_lease=begin
                lease.pending=damage=='pending'
                lease.wait=lambda:dict(localKnown=0 if damage=='unknown' else 1,localMatch=1,
                    nativeExit=1,threadClosed=1,processesClosed=1,workerCleanup=1,stageCode=13)
                probe._fresh_proof=lambda target:self.fail('Unknown/pending result started post provider work')
                with self.assertRaises(AssertionError):
                    probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)
                self.assertEqual(len(started),int(damage!='target'))

    def test_real_adapter_constructs_typed_v2_source_with_independently_observed_refs(self):
        import sys
        import inspect
        from types import ModuleType
        import native_menu_msaa_hit as helper
        import test_native_menu_msaa_hit as metadata
        self.assertTrue(hasattr(helper,'MsaaHitSourceV2'))
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        probe._begin_point_lease=module.NativeMenuProbe._begin_point_lease.__get__(probe,type(probe))
        self.assertIn('fresh_refs',inspect.signature(probe._begin_point_lease).parameters)
        probe._native_point_profile_version=2
        sdk=metadata.sdk_fixture()
        library=NS(IUIAutomation=sdk['client_interface'],IUIAutomationElement=sdk['element_interface'],
            IUIAutomationLegacyIAccessiblePattern=sdk['legacy_interface'])
        def ref(interface,value):
            return type('NativeBorrowed',(C.c_void_p,),{'__com_interface__':interface})(value)
        client=ref(sdk['client_interface'],500);retained_file=ref(sdk['element_interface'],501)
        fresh_file=ref(sdk['element_interface'],502);retained_target=ref(sdk['element_interface'],503)
        fresh_target=ref(sdk['element_interface'],504)
        negative=[ref(sdk['element_interface'],value) for value in (505,506,507)]
        fresh_refs={'file':fresh_file,'target:save':fresh_target}
        probe.provider_client=client;probe._uia_library=library
        probe._identity_refs={'file':retained_file,'target:save':retained_target}
        comtypes=ModuleType('comtypes');comtypes.GUID=sdk['guid_type'];comtypes.HRESULT=sdk['hresult_type']
        automation=ModuleType('comtypes.automation');automation.VARIANT=sdk['variant_type']
        captured=[]
        def begin(source,scope,binder,deadline,*,native_enabled=False,profile_version=1):
            captured.append((source,scope,binder,deadline,native_enabled,profile_version));return lease
        with patch.dict(sys.modules,{'comtypes':comtypes,'comtypes.automation':automation}), \
                patch.object(module.C,'WINFUNCTYPE',C.CFUNCTYPE,create=True),patch.object(helper,'begin_msaa_hit',side_effect=begin):
            actual=probe._begin_point_lease(retained_file,fresh_target,negative,7,[50,70],fresh_refs=fresh_refs)
        self.assertIs(actual,lease);source,scope,binder,deadline,enabled,version=captured[0]
        self.assertIs(type(source),helper.MsaaHitSourceV2)
        self.assertIs(source.retained_file,retained_file);self.assertIs(source.fresh_file,fresh_file)
        self.assertIs(source.fresh_target,fresh_target);self.assertIs(source.retained_target,retained_target)
        self.assertEqual(source.negative_refs,tuple(negative));self.assertIs(source.keepalive[0],probe)
        self.assertIs(source.keepalive[1],fresh_refs);self.assertTrue(binder.matches_source(source))
        self.assertEqual((scope.scope_id,scope.engine_pid,scope.engine_birth,scope.shell_pid,scope.shell_birth,
            scope.parent_hwnd,scope.child_hwnd,scope.x,scope.y),(7,88,200,77,100,55,56,50,70))
        self.assertEqual((deadline,enabled,version),(6.,True,2))

    def test_wrong_worker_mode_is_rejected_before_post_provider_queries(self):
        for relabel in (False,True):
            with self.subTest(relabel=relabel):
                module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
                probe._native_point_profile_version=2;post=[]
                old=receipts.NativeMenuPointProofTests(methodName='runTest');self.addCleanup(old.doCleanups)
                provider=copy.deepcopy(old.fixture()[3]['providerLocalProof']['provider'])
                if relabel:provider['schemaVersion']=2
                lease.wait=lambda:provider
                probe._begin_point_lease=lambda *args,**kwargs:lease
                original=probe._fresh_proof
                probe._fresh_proof=lambda target:post.append(1) or original(target)
                with self.assertRaises(AssertionError):
                    probe._provider_local_point([50,70],probe.current_control.element_info._element,pane)
                self.assertEqual(post,[])


class NativeIdentityDiagnosticTests(unittest.TestCase):
    fixture=NativeMenuPointProfileTests.fixture

    def diagnostic(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        probe._native_identity_diagnostic=3
        import native_menu_msaa_hit as helper
        packet=helper._record_v3(None,False)
        packet.update(diagnosticComplete=1,nativeExit=1,threadClosed=1,processesClosed=1,
            workerCleanup=1,stageCode=13,threadBirth=1<<48,scopeId=1,negativeCount=5,negativeRejected=5)
        started=[]
        def wait():state.waited=True;return copy.deepcopy(packet)
        lease.wait=wait
        def begin(*args,**kwargs):started.append((args,kwargs));return lease
        probe._begin_identity_diagnostic_lease=begin
        return module,probe,boundary,binding,state,lease,calls,pane,packet,started

    def test_diagnostic_constructor_is_a_separate_closed_zero_or_three_opt_in(self):
        import inspect
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,boundary,calls,(user,kernel,dwm),context=owner.lazy_provider_boundary()
        self.assertIn('native_identity_diagnostic',inspect.signature(module.NativeMenuProbe).parameters)
        with context:
            for value in (1,2,True,False,'3',None):
                with self.subTest(value=value),self.assertRaises(AssertionError):
                    module.NativeMenuProbe(clock()+5,clock,user=user,kernel=kernel,dwm=dwm,
                        native_point_profile=True,native_point_profile_version=2,native_identity_diagnostic=value)
            probe=module.NativeMenuProbe(clock()+5,clock,user=user,kernel=kernel,dwm=dwm,
                native_point_profile=True,native_point_profile_version=2,native_identity_diagnostic=3)
            self.assertEqual(probe._native_identity_diagnostic,3);self.assertEqual(calls,[])

    def test_global_true_diagnostic_is_terminal_without_positive_provider_fallback(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        self.assertTrue(hasattr(module,'NativeIdentityDiagnosticTerminal'))
        probe._native_identity_diagnostic=3
        probe._provider_local_point=lambda *args:self.fail('Diagnostic reached a positive provider worker')
        probe._observe_identity_diagnostic=lambda *args:self.fail('A global TRUE source cannot begin the fixed Pane diagnostic')
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            probe.point_snapshot(99,[50,70],probe.current_control)
        self.assertEqual(calls,[])
        self.assertEqual(probe.interop['identityDiagnosticControl']['terminalCode'],5)
        probe._uia_call=lambda *args:self.fail('Terminal diagnostic started another provider query')
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            probe.point_snapshot(99,[50,70],probe.current_control)
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):probe.snapshot(binding,'save')

    def test_run_cannot_send_escape_or_target_input_when_a_diagnostic_observer_returns(self):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,probe=owner.fixture()
        self.assertTrue(hasattr(module,'NativeIdentityDiagnosticTerminal'))
        process.opengeul_native_menu_identity_diagnostic=3
        process.opengeul_native_menu_point_profile=True;process.opengeul_native_menu_point_profile_version=2
        probe._native_point_profile=True;probe._native_point_profile_version=2;probe._native_identity_diagnostic=3
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            module.inspect_native_menu(api,process,11,record,'open-escape',probe=probe,clock=clock)
        self.assertEqual([row for row in probe.calls if type(row) is tuple and row[0] in ('click','key')],[('click','file')])
        self.assertEqual(record['nativeMenuActions'][-1]['keys'],[])
        self.assertFalse(record['nativeMenuActions'][-1]['success'])
        first=list(probe.calls)
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            module.inspect_native_menu(api,process,11,record,'open-escape',probe=probe,clock=clock)
        self.assertEqual([row for row in probe.calls[len(first):] if type(row) is tuple and row[0] in ('click','key')],[])

    def test_complete_read_is_terminal_with_real_fresh_refs_one_lease_and_no_positive_claim(self):
        module,probe,boundary,binding,state,lease,calls,pane,packet,started=self.diagnostic()
        fresh_calls=[];original=probe._fresh_proof_with_refs
        def fresh(target):
            result=original(target);fresh_calls.append((probe.clock(),probe.deadline,result));return result
        probe._fresh_proof_with_refs=fresh
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            probe._observe_identity_diagnostic([50,70],probe.current_control.element_info._element,pane)
        self.assertEqual(len(started),1)
        args,kwargs=started[0]
        self.assertIs(args[0],fresh_calls[0][2][1])
        self.assertIsNot(args[0]['file'],probe._identity_refs['file'])
        self.assertIsNot(args[0]['target:save'],probe._identity_refs['target:save'])
        self.assertEqual((kwargs['captured_at'],kwargs['action_deadline'],fresh_calls[0][1]),(1.,6.,2.5))
        self.assertEqual((kwargs['exposure']['hwnd'],kwargs['exposure']['threadId'],kwargs['exposure']['ownerChain']),(99,9,[99,56]))
        self.assertEqual(probe.deadline,6.)
        self.assertEqual(probe.interop['identityDiagnosticControl']['diagnosticComplete'],1)
        self.assertEqual(probe.interop['identityDiagnosticControl']['postScopeVerified'],1)
        self.assertEqual(probe.interop['identityDiagnosticResult']['threadBirth'],1<<48)
        self.assertEqual((packet['localKnown'],packet['localMatch']),(0,0))
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            probe._observe_identity_diagnostic([50,70],probe.current_control.element_info._element,pane)
        self.assertEqual(len(started),1)

    def test_pending_late_failed_wrong_mode_and_positive_packets_start_no_post_queries(self):
        for damage in ('pending','late','failed','mode','positive','synthetic','extra','scope','negative'):
            with self.subTest(damage=damage):
                module,probe,boundary,binding,state,lease,calls,pane,packet,started=self.diagnostic()
                post=[]
                probe._fresh_proof=lambda target:post.append(1)
                provider_boundary_calls=NS(count=0)
                for name in ('_popup_exposure','_call','_uia_call'):
                    original=getattr(probe,name)
                    def boundary_call(*args,_original=original,**kwargs):
                        if state.waited:provider_boundary_calls.count+=1
                        return _original(*args,**kwargs)
                    setattr(probe,name,boundary_call)
                if damage=='pending':lease.pending=True;packet['pending']=1
                elif damage=='failed':packet['diagnosticComplete']=0
                elif damage=='mode':packet['workerSchemaVersion']=2
                elif damage=='positive':packet['localKnown']=1
                elif damage=='synthetic':packet['synthetic']=1
                elif damage=='extra':packet['other']=1
                elif damage=='scope':packet['scopeId']=2
                elif damage=='negative':packet['negativeCount']=4
                def wait():
                    if damage=='late':boundary.clock.now=2.5
                    state.waited=True
                    return copy.deepcopy(packet)
                lease.wait=wait
                with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
                    probe._observe_identity_diagnostic([50,70],probe.current_control.element_info._element,pane)
                self.assertEqual(post,[])
                self.assertTrue(state.waited)
                self.assertEqual(provider_boundary_calls.count,0)
                self.assertEqual(probe.interop['identityDiagnosticControl']['diagnosticComplete'],0)
                if damage in ('mode','positive','synthetic','extra','scope','negative'):
                    self.assertNotIn('identityDiagnosticResult',probe.interop)
                self.assertEqual(probe.deadline,6.)

    def test_source_discovery_consumes_age_before_the_only_lease_is_admitted(self):
        module,probe,boundary,binding,state,lease,calls,pane,packet,started=self.diagnostic()
        original=probe._fresh_proof_with_refs
        def fresh(target):
            value=original(target);boundary.clock.now=2.5;return value
        probe._fresh_proof_with_refs=fresh
        with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
            probe._observe_identity_diagnostic([50,70],probe.current_control.element_info._element,pane)
        self.assertEqual(started,[]);self.assertFalse(state.waited)
        self.assertEqual(probe.deadline,6.)

    def test_nonfile_early_failure_and_missing_retained_scope_are_terminal(self):
        for damage in ('early','scope'):
            with self.subTest(damage=damage):
                module,probe,boundary,binding,state,lease,calls,pane,packet,started=self.diagnostic()
                if damage=='early':probe._chrome=lambda target:(_ for _ in ()).throw(ValueError('synthetic'))
                else:probe._uses_comparison=False
                with self.assertRaises(module.NativeIdentityDiagnosticTerminal):
                    probe.point_snapshot(99,[50,70],probe.current_control)
                self.assertEqual(started,[])

    def test_actual_profile_three_adapter_constructs_typed_source_without_using_positive_begin(self):
        import sys
        from types import ModuleType
        import native_menu_msaa_hit as helper
        import test_native_menu_msaa_hit as metadata
        module,probe,boundary,binding,state,lease,calls,pane,packet,started=self.diagnostic()
        probe._begin_identity_diagnostic_lease=module.NativeMenuProbe._begin_identity_diagnostic_lease.__get__(probe,type(probe))
        sdk=metadata.sdk_fixture()
        library=NS(IUIAutomation=sdk['client_interface'],IUIAutomationElement=sdk['element_interface'],
            IUIAutomationLegacyIAccessiblePattern=sdk['legacy_interface'])
        def ref(interface,value):return type('Borrowed',(C.c_void_p,),{'__com_interface__':interface})(value)
        refs=[ref(sdk['element_interface'],value) for value in range(501,508)]
        retained_file,fresh_file,retained_target,fresh_target,*negative=refs
        probe.provider_client=ref(sdk['client_interface'],500);probe._uia_library=library
        probe._identity_refs={'file':retained_file,'target:save':retained_target}
        fresh_refs={'file':fresh_file,'target:save':fresh_target}
        comtypes=ModuleType('comtypes');comtypes.GUID=sdk['guid_type'];comtypes.HRESULT=sdk['hresult_type']
        automation=ModuleType('comtypes.automation');automation.VARIANT=sdk['variant_type']
        captured=[]
        def begin(source,scope,binder,deadline,*,native_enabled=False):
            captured.append((source,scope,binder,deadline,native_enabled));return lease
        with patch.dict(sys.modules,{'comtypes':comtypes,'comtypes.automation':automation}), \
                patch.object(module.C,'WINFUNCTYPE',C.CFUNCTYPE,create=True), \
                patch.object(helper,'begin_ia2_diagnostic',side_effect=begin), \
                patch.object(helper,'begin_msaa_hit',side_effect=AssertionError('Positive entry is forbidden')):
            result=probe._begin_identity_diagnostic_lease(fresh_refs,negative,7,[50,70],captured_at=1.,action_deadline=6.,
                exposure=dict(hwnd=99,threadId=9,ownerChain=[99,56]))
        self.assertIs(result,lease);source,scope,binder,deadline,enabled=captured[0]
        self.assertIs(type(source),helper.MsaaHitSourceV3);self.assertTrue(binder.matches_source(source))
        self.assertIs(source.retained_file,retained_file);self.assertIs(source.fresh_file,fresh_file)
        self.assertIs(source.fresh_target,fresh_target);self.assertIs(source.retained_target,retained_target)
        self.assertIs(source.keepalive[0],probe);self.assertIs(source.keepalive[1],fresh_refs)
        self.assertEqual(source.negative_refs,tuple(negative))
        self.assertEqual((source.captured_at,source.action_deadline,source.document_hwnd,source.popup_hwnd,source.popup_thread,source.owner_chain),
            (1.,6.,11,99,9,(99,56)))
        self.assertEqual((deadline,enabled),(6.,True))

    def test_original_file_foreground_failure_retains_the_same_single_getter_value(self):
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        seen=[]
        probe.foreground=lambda:seen.append(1) or 12345
        with self.assertRaises(AssertionError):probe._physical_base()
        self.assertEqual(seen,[1])
        self.assertEqual(probe.interop['graphRefresh']['foregroundHwnd'],12345)


class NativeApartmentGuardTests(unittest.TestCase):
    def native_probe(self,*,thread_id=123,kind=1,hresult=0,clock_values=()):
        module=boundaries.OwnedNativeMenuTests(methodName='runTest').feature()
        native_calls=[];provider_calls=[];values=iter(clock_values)
        class Provider:
            def __setattr__(self,name,value):
                provider_calls.append(('set',name));object.__setattr__(self,name,value)
            def __getattribute__(self,name):
                provider_calls.append(('get',name));return object.__getattribute__(self,name)
        def apartment(kind_out,qualifier_out):
            native_calls.append('apartment')
            C.cast(kind_out,C.POINTER(C.c_int32))[0]=kind
            C.cast(qualifier_out,C.POINTER(C.c_int32))[0]=0
            return hresult
        def thread():native_calls.append('thread');return thread_id
        probe=object.__new__(module.NativeMenuProbe)
        probe.clock=lambda:next(values,1.);probe.deadline=6.;probe.interop={}
        probe.provider_client=Provider();probe.kernel=NS(GetCurrentThreadId=thread)
        probe._provider_creator=dict(threadId=123,mta=True)
        context=patch.object(module.C,'WinDLL',return_value=NS(CoGetApartmentType=apartment),create=True)
        return probe,native_calls,provider_calls,apartment,thread,context

    def test_wrong_thread_or_sta_is_rejected_without_touching_provider(self):
        for thread_id,kind in ((124,1),(123,0)):
            with self.subTest(thread_id=thread_id,kind=kind):
                probe,native,provider,apartment,thread,context=self.native_probe(thread_id=thread_id,kind=kind)
                with context,self.assertRaises(AssertionError):probe._require_provider_creator()
                self.assertEqual(native,['apartment','thread'])
                self.assertEqual(provider,[],'The native creator guard must precede all provider access')
                self.assertEqual(probe._provider_creator,dict(threadId=123,mta=True))

    def test_matching_mta_preserves_typed_native_result_without_provider_access(self):
        probe,native,provider,apartment,thread,context=self.native_probe()
        with context:result=probe._require_provider_creator()
        self.assertEqual(result,dict(threadId=123,mta=True,sameThread=True))
        self.assertEqual(native,['apartment','thread']);self.assertEqual(provider,[])
        self.assertEqual(apartment.argtypes,(C.POINTER(C.c_int32),C.POINTER(C.c_int32)))
        self.assertIs(apartment.restype,C.c_int32)
        self.assertEqual(thread.argtypes,());self.assertIs(thread.restype,C.c_uint32)

    def test_original_deadline_bounds_both_native_calls_without_provider_access(self):
        cases=(((6.,),[],'deadline expired'),
            ((1.,6.),['apartment'],'exceeded original deadline'),
            ((1.,1.,6.),['apartment'],'deadline expired'),
            ((1.,1.,1.,6.),['apartment','thread'],'exceeded original deadline'))
        for values,expected,message in cases:
            with self.subTest(clock_values=values):
                probe,native,provider,apartment,thread,context=self.native_probe(clock_values=values)
                with context,self.assertRaisesRegex(AssertionError,message):probe._mta_snapshot()
                self.assertEqual(native,expected);self.assertEqual(provider,[])

    def test_failed_apartment_hresult_remains_unavailable_without_provider_access(self):
        probe,native,provider,apartment,thread,context=self.native_probe(hresult=-2147467259)
        with context:result=probe._mta_snapshot()
        self.assertEqual(result,(123,False))
        self.assertEqual(native,['apartment','thread']);self.assertEqual(provider,[])


if __name__=='__main__':unittest.main()
