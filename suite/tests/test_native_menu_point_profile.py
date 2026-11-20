"""Opt-in point profile lifetime boundaries; native calls remain synthetic."""
import copy
import ctypes as C
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import test_owned_native_menu as boundaries
import test_native_menu_point_proof as receipts


def _source_qualified_action_context(owner,admission,selection,*,started_at=1.,call_step=.001):
    """Actual source policy with fresh SDK work at each synthetic native boundary."""
    import native_menu_msaa_hit as helper
    import test_native_menu_msaa_hit as metadata
    policy=boundaries.OwnedNativeMenuTests(methodName='runTest');owner.addCleanup(policy.doCleanups)
    module,api,process,record,clock,boundary=policy.real_chrome_fixture()
    root=admission.suite_root;probe=boundary.probe;clock.now=started_at;probe.deadline=started_at+5
    process.opengeul_suite_root=root;process.args=[str(root/'OpenGeul.Office.exe')]
    process.opengeul_source_menu_selection=selection
    probe.source_selection=selection;probe._native_point_profile=True;probe._native_point_profile_version=4
    probe._native_identity_diagnostic=0;probe._physical_file_refresh=True
    probe._provider_creator=dict(threadId=123,mta=True);probe._mta_snapshot=lambda:(123,True)
    boundary.native.shell['image']=str(root/'OpenGeul.Office.exe')
    boundary.native.engine.update(image=str(root/'Office/program/soffice.bin'),handleValue=9)
    window=probe.window_snapshot
    probe.window_snapshot=lambda hwnd:dict(window(hwnd),rectangle=[0,45,258,1000] if hwnd==99 else [0,0,800,1100],iconic=False,cloaked=0)
    def class_name(hwnd,buffer,size):buffer.value='SALTMPSUBFRAME';return len(buffer.value)
    probe.user.GetClassNameW=class_name
    probe.user.GetWindowLongW=lambda hwnd,index:0x80000000 if index==-16 else 0x80
    class Pane(boundary.Node):
        @property
        def CurrentControlType(self):return 50033
        @property
        def CurrentNativeWindowHandle(self):return 99
    original_from_point=boundary.from_point
    probe.uia.iuia.ElementFromPoint=lambda point:original_from_point(point) if point.y<50 else Pane('popup')
    state=NS(module=module,api=api,process=process,record=record,clock=clock,probe=probe,boundary=boundary,
        admission=admission,selection=selection,runs=[],call_step=call_step,call_steps={},pending_on=0,
        pending_returned=False,post_pending_queries=0,cursor=[50,30],current_receipt=None,
        native_inputs=[],partial_target=None,expire_cursor_target=None,expire_keyboard=False,
        partial_keyboard=False,expire_after_partial=False)
    for name in ('_call','_uia_call','_popup_exposure','_fresh_proof_with_refs'):
        original=getattr(probe,name)
        def guarded(*args,_original=original,**kwargs):
            if state.pending_returned:state.post_pending_queries+=1
            return _original(*args,**kwargs)
        setattr(probe,name,guarded)
    def begin(fresh_refs,negative,scope_id,point,*,admission,captured_at,action_deadline,exposure):
        role=module._target_role(probe._active_target)
        token={id(probe._identity_refs['file']):1,id(fresh_refs['file']):11,
            id(fresh_refs[role]):2,id(probe._identity_refs[role]):3}
        for value in negative:
            if id(value) not in token:token[id(value)]=100+len(token)
        class ScopedCalls(metadata.Ia2DiagnosticCalls):
            def call(self,key,pointer,*args):
                if isinstance(pointer,boundary.Node):pointer=token[id(pointer)]
                if key=='compare':args=(token[id(args[0])],token[id(args[1])],args[2])
                if key=='hit_test':
                    value=pointer.value if isinstance(pointer,C.c_void_p) else pointer
                    assert value==201 and args[:2]==tuple(point)
                    self.calls.append((key,value));args[2]._obj.vt=9;args[2]._obj._.c_void_p=401;hr=0
                else:hr=super().call(key,pointer,*args)
                if key!='release':clock.now+=state.call_steps.get(scope_id,state.call_step)
                return hr
        sdk=ScopedCalls();sdk.identities.update({203:303,222:322})
        sdk.tuples={pointer:(value[0],56) for pointer,value in sdk.tuples.items()}
        platform=metadata.FakePlatform();platform.clock=clock
        platform.window_domain=lambda hwnd,source,scope:1 if hwnd==scope.child_hwnd else 0
        scope=probe._identity_scope;binding=scope['binding']
        request=helper.MsaaHitScope(scope_id,binding['officePid'],scope['officeCreationTime'],scope['shellPid'],
            scope['shellCreationTime'],binding['parent'],binding['child'],*point)
        source=helper.MsaaHitSourceV4(9,probe._identity_refs['file'],fresh_refs['file'],fresh_refs[role],
            probe._identity_refs[role],tuple(negative),probe._point_source['shellHandle'],
            probe._point_source['engineHandle'],(probe,fresh_refs,admission),captured_at,action_deadline,
            binding['document'],exposure['hwnd'],exposure['threadId'],tuple(exposure['ownerChain']),admission,admission.admission_sha256)
        worker=helper.run_source_qualified_ia2_point_v4(source,request,sdk,platform,action_deadline)
        packet=helper._record_v4(request,False);packet.update(worker)
        packet.update(stageCode=13,nativeAttempted=1,nativeExit=1,threadClosed=1,processesClosed=1,
            controllerPid=500,threadId=124,threadBirth=300+scope_id,threadIdentity=1,callbackIdentity=1,
            exitCodeObserved=1,nativeExitCode=0)
        lease=NS(scope=request,pending=scope_id==state.pending_on,source=source)
        if lease.pending:packet['pending']=1
        def wait():
            state.pending_returned=lease.pending
            return copy.deepcopy(packet)
        lease.wait=wait
        state.runs.append(NS(source=source,fresh_refs=fresh_refs,sdk=sdk,worker=worker,packet=packet,lease=lease))
        return lease
    probe._begin_source_qualified_ia2_point_v4=begin
    move=probe.move
    def moved(point,receipt):move(point,receipt);state.cursor=list(point)
    probe.move=moved
    def position(out):
        out._obj.x,out._obj.y=state.cursor
        if state.expire_cursor_target==probe._active_target:clock.now=probe.deadline
        return 1
    def inserted(count,payload,size):
        receipt=state.current_receipt;target=receipt['target'] if receipt else probe._active_target
        state.native_inputs.append(dict(kind='mouse',count=count,at=clock(),deadline=probe.deadline,target=target))
        if count==1:return 1  # Existing owned-prefix release, not a second click.
        assert count==2
        boundary.native.calls.append(('click',target));clock.now+=.01
        if state.partial_target==target:
            if state.expire_after_partial:clock.now=probe.deadline
            return 1
        boundary.native.opened=target in ('file','new')
        return 2
    probe.user.GetPhysicalCursorPos=position;probe.user.GetSystemMetrics=lambda code:0;probe.user.SendInput=inserted
    def clicked(receipt):
        state.current_receipt=receipt
        try:return module.NativeMenuProbe.click(probe,receipt)
        finally:state.current_receipt=None
    probe.click=clicked
    from counted_editor_shortcuts import NativeShortcutProbe
    class Keyboard(NativeShortcutProbe):
        def send(self,payload):
            if state.expire_keyboard:clock.now=self.deadline
            return super().send(payload)
    keyboard=Keyboard.__new__(Keyboard);keyboard.clock=clock;keyboard.deadline=started_at+5
    def key_inserted(count,payload,size):
        state.native_inputs.append(dict(kind='keyboard',count=count,at=clock(),deadline=keyboard.deadline,target=probe._active_target))
        if count==1:return 1
        returned=boundary.send(payload)
        return 1 if state.partial_keyboard else returned
    keyboard.user=NS(SendInput=key_inserted,GetKeyboardLayout=lambda thread:0x04090409,
        GetKeyState=lambda key:0,GetAsyncKeyState=lambda key:0)
    probe.keyboard_probe=keyboard;del probe._keyboard;state.keyboard=keyboard
    def run(operation='save',gesture=False):
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock):
            return (module.inspect_native_menu if gesture else module.click_native_menu_action)(api,process,11,record,
                operation,probe=probe,clock=clock)
    state.run=run
    owner._source_qualified_contexts=getattr(owner,'_source_qualified_contexts',[])+[state]
    return state


def source_qualified_action_fixture(owner,admission,selection,operation='save',gesture=False,*,started_at=1.,call_step=.001):
    state=_source_qualified_action_context(owner,admission,selection,started_at=started_at,call_step=call_step)
    return state.module,state.run(operation,gesture)


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


class NativeSourceQualifiedPointV4Tests(unittest.TestCase):
    fixture=NativeMenuPointProfileTests.fixture

    @classmethod
    def setUpClass(cls):
        import sys
        from suite.tests.test_native_menu_source_admission import SourceMenuAdmissionTests
        cls.gate=SourceMenuAdmissionTests(methodName='test_admits_real_validators_and_freezes_closed_binary_summary')
        cls.gate.setUp()
        cls.admission=cls.gate.admit()
        cls.previous_source_module=sys.modules.get('native_menu_source_admission')
        sys.modules['native_menu_source_admission']=cls.gate.implementation()

    @classmethod
    def tearDownClass(cls):
        import sys
        if cls.previous_source_module is None:sys.modules.pop('native_menu_source_admission',None)
        else:sys.modules['native_menu_source_admission']=cls.previous_source_module
        cls.gate.doCleanups()

    def test_source_qualified_controller_has_separate_live_adapter_and_closed_validator(self):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module=owner.fixture()[0]
        for name in ('_begin_source_qualified_ia2_point_v4','_provider_local_point_v4'):
            self.assertTrue(callable(getattr(module.NativeMenuProbe,name,None)),name)
        self.assertTrue(callable(getattr(module,'_require_provider_point_v4',None)))

    def source_fixture(self):
        import native_menu_msaa_hit as helper
        import test_native_menu_msaa_hit as metadata
        module,probe,boundary,binding,state,lease,calls,pane=self.fixture()
        self.assertTrue(callable(getattr(probe,'_provider_local_point_v4',None)))
        sdk=metadata.Ia2DiagnosticCalls();sdk.identities.update({203:303,222:322})
        platform=metadata.FakePlatform();platform.window_domain=lambda *args:1
        source=helper.MsaaHitSourceV4(9,1,11,2,3,(4,5,6,7,8),20,21,(sdk,),10.,15.,30,31,40,(31,13),
            self.admission,self.admission.admission_sha256)
        worker=helper.run_source_qualified_ia2_point_v4(source,helper.MsaaHitScope(1,8,9,10,11,12,13,14,15),sdk,platform,15.)
        self.assertEqual(worker['pointCandidate'],1)
        packet=helper._record_v4(None,False);packet.update(worker)
        packet.update(scopeId=1,nativeAttempted=1,nativeExit=1,threadClosed=1,processesClosed=1,
            stageCode=13,controllerPid=500,threadId=44,threadBirth=1<<48,
            threadIdentity=1,callbackIdentity=1,exitCodeObserved=1,nativeExitCode=0)
        started=[]
        def begin(fresh_refs,negative,scope_id,point,**kwargs):
            started.append((fresh_refs,negative,scope_id,point,kwargs))
            lease.scope=helper.MsaaHitScope(scope_id,88,200,77,100,55,56,*point)
            packet['scopeId']=scope_id
            return lease
        def wait():state.waited=True;return copy.deepcopy(packet)
        lease.wait=wait;probe._begin_source_qualified_ia2_point_v4=begin
        return module,probe,boundary,binding,state,lease,pane,packet,started

    def observe(self,fixture):
        module,probe,boundary,binding,state,lease,pane,packet,started=fixture
        return probe._provider_local_point_v4([50,70],probe.current_control.element_info._element,pane,
            admission=self.admission)

    def test_new_live_point_keeps_raw_false_and_canonical_zeros_and_joins_actual_source_digest(self):
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        result=self.observe(f)
        self.assertEqual(result['schemaVersion'],4)
        self.assertEqual(result['method'],'owned-popup-and-source-qualified-ia2-hit-v4')
        self.assertEqual(result['finalPointVerified'],1)
        self.assertEqual(result['sourceAdmissionSha256'],self.admission.admission_sha256)
        self.assertEqual(result['primaryComparison']['rawMatchesTarget'],False)
        self.assertEqual(tuple(result['provider'][k] for k in ('filePairEqual','targetPairEqual','hitMatchesTarget')),(0,0,0))
        self.assertEqual((result['provider']['localKnown'],result['provider']['localMatch'],result['provider']['acceptanceEligible']),(0,0,0))
        self.assertIs(started[0][4]['admission'],self.admission)
        self.assertIsNot(started[0][0]['file'],probe._identity_refs['file'])
        self.assertEqual((result['capturedAt'],result['effectiveDeadline'],probe.deadline),(1.,2.5,6.))
        module._require_provider_point_v4(result,binding,77,'save',admission_sha256=self.admission.admission_sha256,now=1.)

    def test_failed_pending_late_wrong_source_and_wrong_schema_start_no_post_queries(self):
        for damage in ('pending','late','candidate','mode','positive','synthetic','extra','scope','negative','digest','exit','cleanup'):
            with self.subTest(damage=damage):
                f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
                post=[];counter=NS(count=0)
                for name in ('_call','_uia_call','_popup_exposure'):
                    original=getattr(probe,name)
                    def guarded(*args,_original=original,**kwargs):
                        if state.waited:counter.count+=1
                        return _original(*args,**kwargs)
                    setattr(probe,name,guarded)
                probe._fresh_proof=lambda target:post.append(1)
                if damage=='pending':lease.pending=True;packet['pending']=1
                elif damage=='candidate':packet['pointCandidate']=0
                elif damage=='mode':packet['workerSchemaVersion']=3
                elif damage=='positive':packet['localKnown']=1
                elif damage=='synthetic':packet['synthetic']=1
                elif damage=='extra':packet['other']=0
                elif damage=='scope':packet['scopeId']=2
                elif damage=='negative':packet['negativeCount']=4
                elif damage=='digest':packet['admissionDigest0']^=1
                elif damage=='exit':packet['nativeExitCode']=1
                elif damage=='cleanup':packet['workerCleanup']=0
                def wait():
                    if damage=='late':boundary.clock.now=2.5
                    state.waited=True
                    if damage=='scope':return dict(packet,scopeId=2)
                    return copy.deepcopy(packet)
                lease.wait=wait
                with self.assertRaises(AssertionError):self.observe(f)
                self.assertEqual((post,counter.count),([],0))
                self.assertEqual(probe.deadline,6.)

    def test_global_true_invalid_source_creator_and_expired_discovery_never_start_lease(self):
        for damage in ('global','source','creator','discovery'):
            with self.subTest(damage=damage):
                f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
                admission=self.admission
                if damage=='global':pane=probe.current_control.element_info._element
                elif damage=='source':admission=NS(admission_sha256=self.admission.admission_sha256)
                elif damage=='creator':probe._mta_snapshot=lambda:(999,True)
                else:
                    original=probe._fresh_proof_with_refs
                    def fresh(target):
                        result=original(target);boundary.clock.now=2.5;return result
                    probe._fresh_proof_with_refs=fresh
                with self.assertRaises((AssertionError,ValueError)):
                    probe._provider_local_point_v4([50,70],probe.current_control.element_info._element,pane,admission=admission)
                self.assertEqual(started,[]);self.assertEqual(probe.deadline,6.)

    def test_five_direct_measurements_have_distinct_fresh_sources_and_one_original_action_deadline(self):
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        proofs=[]
        for index in range(5):
            state.waited=False;boundary.clock.now=1.+index*.6
            proofs.append(self.observe(f));self.assertEqual(probe.deadline,6.)
        self.assertEqual([p['sourceScopeId'] for p in proofs],[1,2,3,4,5])
        self.assertEqual(len({id(row[0]) for row in started}),5)
        self.assertEqual(len({id(row[0]['file']) for row in started}),5)
        self.assertEqual([row[4]['action_deadline'] for row in started],[6.]*5)
        for proof in proofs:self.assertEqual(proof['effectiveDeadline'],min(6.,proof['capturedAt']+1.5))
        with self.assertRaises(AssertionError):
            module._require_provider_point_v4(proofs[0],binding,77,'save',admission_sha256=self.admission.admission_sha256,now=3.4)
        module._require_provider_point_v4(proofs[-1],binding,77,'save',admission_sha256=self.admission.admission_sha256,now=3.4)

    def test_existing_pending_predecessor_blocks_every_new_measurement_before_provider_query(self):
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        probe._provider_pending=lambda:True;queries=[]
        probe._require_provider_creator=lambda:queries.append(1)
        with self.assertRaises(AssertionError):self.observe(f)
        self.assertEqual((queries,started),([],[]))

    def test_closed_replay_rejects_type_scope_geometry_raw_false_source_and_expiry_tampering(self):
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        original=self.observe(f)
        mutations=(lambda p:p.update(schemaVersion=True),lambda p:p.update(extra=0),
            lambda p:p.update(finalPointVerified=0),lambda p:p.update(sourceAdmissionSha256='0'*64),
            lambda p:p.update(effectiveDeadline=3.),lambda p:p.update(capturedAt=0.),
            lambda p:p['primaryComparison'].update(rawMatchesTarget=True),
            lambda p:p['primaryComparison']['differentFrom'].update(file=True),
            lambda p:p.update(targetRectangle=[0,0,1,1]),
            lambda p:p['sourceScope'].update(engine_birth=201),
            lambda p:p['provider'].update(pointCandidate=0),
            lambda p:p['provider'].update(admissionDigest7=0))
        for index,change in enumerate(mutations):
            with self.subTest(case=index):
                changed=copy.deepcopy(original);change(changed)
                with self.assertRaises(AssertionError):
                    module._require_provider_point_v4(changed,binding,77,'save',admission_sha256=self.admission.admission_sha256,now=1.)
        with self.assertRaises(AssertionError):
            module._require_provider_point_v4(original,binding,77,'save',admission_sha256=self.admission.admission_sha256,now=2.5)

    def test_actual_adapter_uses_typed_source_four_exact_live_refs_and_only_the_new_entry(self):
        import sys
        from types import ModuleType
        import native_menu_msaa_hit as helper
        import test_native_menu_msaa_hit as metadata
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        probe._begin_source_qualified_ia2_point_v4=module.NativeMenuProbe._begin_source_qualified_ia2_point_v4.__get__(probe,type(probe))
        sdk=metadata.sdk_fixture()
        probe._uia_library=NS(IUIAutomation=sdk['client_interface'],IUIAutomationElement=sdk['element_interface'],
            IUIAutomationLegacyIAccessiblePattern=sdk['legacy_interface'])
        def ref(interface,value):return type('BorrowedV4',(C.c_void_p,),{'__com_interface__':interface})(value)
        retained_file,fresh_file,retained_target,fresh_target,*negative=[ref(sdk['element_interface'],value) for value in range(501,508)]
        probe.provider_client=ref(sdk['client_interface'],500)
        probe._identity_refs={'file':retained_file,'target:save':retained_target}
        refs={'file':fresh_file,'target:save':fresh_target}
        comtypes=ModuleType('comtypes');comtypes.GUID=sdk['guid_type'];comtypes.HRESULT=sdk['hresult_type']
        automation=ModuleType('comtypes.automation');automation.VARIANT=sdk['variant_type']
        captured=[]
        def begin(source,scope,binder,deadline,*,native_enabled=False):
            captured.append((source,scope,binder,deadline,native_enabled));return lease
        with patch.dict(sys.modules,{'comtypes':comtypes,'comtypes.automation':automation}), \
                patch.object(module.C,'WINFUNCTYPE',C.CFUNCTYPE,create=True), \
                patch.object(helper,'begin_source_qualified_ia2_point',side_effect=begin), \
                patch.object(helper,'begin_ia2_diagnostic',side_effect=AssertionError('Mode3 cannot authorize mode4')), \
                patch.object(helper,'begin_msaa_hit',side_effect=AssertionError('Old positive entry cannot authorize mode4')):
            actual=probe._begin_source_qualified_ia2_point_v4(refs,negative,7,[50,70],admission=self.admission,
                captured_at=1.,action_deadline=6.,exposure=dict(hwnd=99,threadId=9,ownerChain=[99,56]))
        self.assertIs(actual,lease);source,scope,binder,deadline,enabled=captured[0]
        self.assertIs(type(source),helper.MsaaHitSourceV4);self.assertTrue(binder.matches_source(source))
        self.assertIs(source.retained_file,retained_file);self.assertIs(source.fresh_file,fresh_file)
        self.assertIs(source.fresh_target,fresh_target);self.assertIs(source.retained_target,retained_target)
        self.assertIs(source.admission,self.admission);self.assertIs(source.keepalive[0],probe)
        self.assertIs(source.keepalive[1],refs);self.assertIs(source.keepalive[2],self.admission)
        self.assertEqual(source.admission_sha256,self.admission.admission_sha256)
        self.assertEqual((scope.scope_id,scope.engine_pid,scope.engine_birth,scope.shell_pid,scope.shell_birth,
            scope.parent_hwnd,scope.child_hwnd,scope.x,scope.y),(7,88,200,77,100,55,56,50,70))
        self.assertEqual((deadline,enabled),(6.,True))

    def test_global_point_numbers_are_exact_integers_in_the_closed_v4_proof(self):
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        original=self.observe(f)
        for key in ('kindCode','pid','nativeHwnd'):
            with self.subTest(field=key):
                changed=copy.deepcopy(original);changed['globalPoint'][key]=float(changed['globalPoint'][key])
                with self.assertRaises(AssertionError):
                    module._require_provider_point_v4(changed,binding,77,'save',admission_sha256=self.admission.admission_sha256,now=1.)

    def global_handle_fixture(self,raw,popup):
        f=self.source_fixture();module,probe,boundary,binding,state,lease,pane,packet,started=f
        class Pane(boundary.Node):
            @property
            def CurrentControlType(self):return 50033
            @property
            def CurrentNativeWindowHandle(self):return raw
        pane=Pane('popup')
        original=probe._popup_exposure
        def exposure(*args):
            value=original(*args)
            value.update(hwnd=popup,rootHwnd=popup,ownerChain=[popup,*value['ownerChain'][1:]])
            return value
        probe._popup_exposure=exposure
        return module,probe,boundary,binding,state,lease,pane,packet,started

    def test_signed_global_hwnd_preserves_raw_and_normalizes_exact_32bit_values(self):
        for raw,normalized in ((-(1<<31),1<<31),(-(1<<31)+99,(1<<31)+99),(-1,(1<<32)-1),((1<<31)+99,(1<<31)+99)):
            with self.subTest(raw_negative=raw<0):
                f=self.global_handle_fixture(raw,normalized)
                result=self.observe(f)
                self.assertIn('nativeHwndRaw',result['globalPoint'])
                self.assertEqual(result['globalPoint']['nativeHwndRaw'],raw)
                self.assertEqual(result['globalPoint']['nativeHwnd'],normalized)
                self.assertEqual(result['before']['hwnd'],normalized)
                self.assertEqual(result['finalPointVerified'],1)

    def test_invalid_global_hwnd_raw_value_stops_before_any_lease(self):
        for raw,popup in ((True,1),(99.,99),(None,99),(0,99),((1<<32)+99,99),(-(1<<31)-1,(1<<31)-1),(-2147483549.,(1<<31)+99)):
            with self.subTest(kind=type(raw).__name__):
                f=self.global_handle_fixture(raw,popup)
                with self.assertRaises(AssertionError):self.observe(f)
                self.assertEqual(f[-1],[])
                self.assertFalse(f[4].waited)

    def test_closed_v4_replay_requires_exact_raw_type_range_and_normalized_hwnd_join(self):
        f=self.global_handle_fixture(-(1<<31)+99,(1<<31)+99)
        module,probe,boundary,binding,state,lease,pane,packet,started=f
        original=self.observe(f)
        changes=(lambda p:p['globalPoint'].pop('nativeHwndRaw'),
            lambda p:p['globalPoint'].update(nativeHwndRaw=True),
            lambda p:p['globalPoint'].update(nativeHwndRaw=float(-(1<<31)+99)),
            lambda p:p['globalPoint'].update(nativeHwndRaw=-(1<<31)-1),
            lambda p:p['globalPoint'].update(nativeHwndRaw=(1<<32)+99),
            lambda p:p['globalPoint'].update(nativeHwndRaw=0),
            lambda p:p['globalPoint'].update(nativeHwnd=(1<<31)+100))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                changed=copy.deepcopy(original);change(changed)
                with self.assertRaises(AssertionError):
                    module._require_provider_point_v4(changed,binding,77,'save',admission_sha256=self.admission.admission_sha256,now=1.)


class SourceQualifiedLiveMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_native_menu_source_selection import SourceMenuSelectionTests
        cls.gate=SourceMenuSelectionTests(methodName='test_prepares_actual_bare_gate_context_and_freezes_contexts')
        cls.gate.setUp();cls.addClassCleanup(cls.gate.doCleanups)
        cls.prepared=cls.gate.prepared();cls.selection=cls.gate.selected(cls.prepared)

    def context(self,**options):
        return _source_qualified_action_context(self,self.prepared.admission,self.selection,**options)

    def action(self,**options):
        return source_qualified_action_fixture(self,self.prepared.admission,self.selection,**options)

    def points(self,action):
        item=action['pointers'][-1]
        for snapshot in item['snapshots']:self.assertIn('targetPointProof',snapshot)
        return [item['snapshots'][0]['targetPointProof'],item['snapshots'][1]['targetPointProof'],
            item['hits'][0],item['snapshots'][2]['targetPointProof'],item['hits'][1]]

    def test_actual_local_dispatch_keeps_five_independent_fresh_worker_measurements(self):
        module,action=self.action();context=self._source_qualified_contexts[-1]
        points=self.points(action);self.assertEqual(len(context.runs),5)
        self.assertEqual([point['providerLocalProof']['sourceScopeId'] for point in points],[1,2,3,4,5])
        self.assertEqual(len({id(run.fresh_refs) for run in context.runs}),5)
        self.assertEqual(len({id(run.source.fresh_file) for run in context.runs}),5)
        self.assertEqual(len({id(run.sdk) for run in context.runs}),5)
        for point,run in zip(points,context.runs):
            self.assertIs(run.source.fresh_file,run.fresh_refs['file'])
            self.assertIs(run.source.fresh_target,run.fresh_refs['target:save'])
            self.assertIs(run.source.admission,self.prepared.admission)
            self.assertEqual(point['pointMethod'],'owned-popup-and-source-qualified-ia2-hit-v4')
            self.assertIs(point['uiaMatches'],False);self.assertIn('pointObservedAt',point)
            self.assertEqual(len(run.sdk.calls),51+run.worker['negativeCount'])
            self.assertEqual(run.worker['referencesAcquired'],26)
            self.assertEqual(run.sdk.releases,list(reversed(run.sdk.owned_outputs)))
            self.assertEqual(run.worker['localKnown'],0);self.assertEqual(run.worker['localMatch'],0)
        self.assertEqual([(use['sourceScopeId'],use['useCode']) for use in action['pointUses']],
            [(1,1),(2,1),(3,2),(4,1),(5,2),(5,3)])
        self.assertIs(module.require_native_menu_action(action,77,11,'save',source_admission=self.prepared.admission),action)

    def test_current_pointer_uses_last_hit_after_the_prior_snapshot_age_has_expired(self):
        context=self.context(call_step=.006);context.call_steps[5]=.024
        action=context.run();points=self.points(action)
        first=points[0]['providerLocalProof'];previous=points[3]['providerLocalProof'];last=points[4]['providerLocalProof']
        self.assertGreater(last['capturedAt'],first['capturedAt']+1.0)
        self.assertGreater(action['pointers'][-1]['inputStartedAt'],first['capturedAt']+1.5)
        self.assertGreater(action['pointers'][-1]['inputStartedAt'],previous['effectiveDeadline'])
        self.assertLess(action['pointers'][-1]['inputStartedAt'],last['effectiveDeadline'])
        self.assertEqual(action['pointUses'][-1]['sourceScopeId'],5)
        actual=[row for row in context.native_inputs if row['kind']=='mouse' and row['target']=='save']
        self.assertEqual(len(actual),1);self.assertEqual(actual[0]['deadline'],last['effectiveDeadline'])
        self.assertEqual(context.probe.deadline,action['deadline'])

    def test_expiry_at_the_actual_base_click_guard_prevents_save_sendinput(self):
        context=self.context();context.expire_cursor_target='save'
        with self.assertRaises(AssertionError):context.run()
        self.assertFalse(any(row['target']=='save' for row in context.native_inputs))
        self.assertEqual([row['target'] for row in context.native_inputs],['file'])
        self.assertEqual(context.probe.deadline,6.)

    def test_partial_save_click_keeps_owned_prefix_release_even_after_point_expiry(self):
        context=self.context();context.partial_target='save';context.expire_after_partial=True
        with self.assertRaises(AssertionError):context.run()
        rows=[row for row in context.native_inputs if row['target']=='save']
        self.assertEqual([row['count'] for row in rows],[2,1])
        value=context.record['nativeMenuActions'][-1]['pointers'][-1]
        self.assertEqual(value['insertedInputs'],1);self.assertEqual(value['ownedButtonRelease']['inserted'],1)
        self.assertEqual(context.probe.deadline,6.)

    def test_cached_keyboard_clamp_and_restore_uses_the_current_snapshot_only(self):
        context=self.context();action=context.run('open-escape',True)
        row=action['keys'][-1];point=row['before']['targetPointProof'];proof=point['providerLocalProof']
        calls=[item for item in context.native_inputs if item['kind']=='keyboard']
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['deadline'],proof['effectiveDeadline'])
        self.assertLess(row['inputStartedAt'],proof['effectiveDeadline'])
        self.assertEqual(action['pointUses'][-1]['sourceScopeId'],proof['sourceScopeId'])
        self.assertEqual(action['pointUses'][-1]['useCode'],4)
        self.assertEqual((context.probe.deadline,context.keyboard.deadline),(6.,6.))

    def test_cached_keyboard_final_guard_expires_without_native_key_input(self):
        context=self.context();context.expire_keyboard=True
        with self.assertRaises(AssertionError):context.run('open-escape',True)
        self.assertFalse(any(row['kind']=='keyboard' for row in context.native_inputs))
        self.assertEqual((context.probe.deadline,context.keyboard.deadline),(6.,6.))

    def test_started_pending_point_suppresses_later_provider_work_and_target_input(self):
        context=self.context();context.pending_on=3
        with self.assertRaises(AssertionError):context.run()
        self.assertEqual(len(context.runs),3);self.assertEqual(context.post_pending_queries,0)
        self.assertEqual([row['target'] for row in context.native_inputs],['file'])
        self.assertIs(context.probe._msaa_lease,context.runs[-1].lease)
        self.assertIsNotNone(context.probe._uia)
        # No native callback was launched; this synthetic uncertainty is retained only for the assertion.
        context.runs[-1].lease.pending=False


if __name__=='__main__':unittest.main()
