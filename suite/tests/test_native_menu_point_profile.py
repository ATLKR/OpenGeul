"""Opt-in point profile lifetime boundaries; native calls remain synthetic."""
import copy
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


if __name__=='__main__':unittest.main()
