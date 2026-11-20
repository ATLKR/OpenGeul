"""One fresh Escape admission; all native boundaries remain synthetic here."""
import copy
import unittest

import test_owned_native_menu as boundaries
import test_native_menu_point_profile as profiles


class OpenEscapeObservationTests(unittest.TestCase):
    def context(self, mode=None, *, simple=False):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest')
        self.addCleanup(owner.doCleanups)
        values=owner.fixture() if simple else owner.real_chrome_fixture(mode)
        module,api,process,record,clock,last=values
        probe=last if simple else last.probe
        observations=[];snapshot=probe.snapshot
        def observed(binding,target):
            row=snapshot(binding,target)
            observations.append((target,row))
            return row
        probe.snapshot=observed
        return module,api,process,record,clock,last,probe,observations

    def test_open_escape_uses_only_the_fresh_keyboard_save_snapshot(self):
        m,api,p,record,clock,b,probe,observations=self.context()
        action=m.inspect_native_menu(api,p,11,record,'open-escape',probe=probe,clock=clock)
        saves=[row for target,row in observations if target=='save']
        self.assertEqual(len(saves),1)
        key,=action['keys']
        self.assertIs(key['before'],saves[0])
        self.assertEqual(key['shortcut'],'ESCAPE')
        self.assertEqual([x for x in b.native.calls if isinstance(x,tuple) and x[0] in ('click','key')],
            [('click','file'),('key','ESCAPE')])
        self.assertEqual(action['deadline'],action['startedAt']+5)
        self.assertTrue(action['focusReturned'])
        self.assertIs(m.require_native_menu_action(action,77,11,'open-escape'),action)

    def test_other_gestures_keep_their_existing_save_observations(self):
        for operation,want in (('open-outside',1),('keyboard-escape',3),
                ('core-commands',2),('disabled-saveAll',1),('disabled-saveCopy',1)):
            with self.subTest(operation=operation):
                m,api,p,record,clock,b,probe,observations=self.context()
                action=m.inspect_native_menu(api,p,11,record,operation,probe=probe,clock=clock)
                self.assertEqual(sum(target=='save' for target,_ in observations),want)
                self.assertTrue(action['focusReturned'])
                self.assertIs(m.require_native_menu_action(action,77,11,operation),action)

    def test_profile3_keeps_its_observation_and_never_sends_escape(self):
        m,api,p,record,clock,probe,_,observations=self.context(simple=True)
        p.opengeul_native_menu_identity_diagnostic=3
        p.opengeul_native_menu_point_profile=True
        p.opengeul_native_menu_point_profile_version=2
        probe._native_point_profile=True;probe._native_point_profile_version=2
        probe._native_identity_diagnostic=3
        with self.assertRaises(m.NativeIdentityDiagnosticTerminal):
            m.inspect_native_menu(api,p,11,record,'open-escape',probe=probe,clock=clock)
        self.assertEqual(sum(target=='save' for target,_ in observations),1)
        self.assertEqual([x for x in probe.calls if isinstance(x,tuple) and x[0] in ('click','key')],
            [('click','file')])
        self.assertEqual(record['nativeMenuActions'][0]['keys'],[])
        self.assertFalse(record['nativeMenuActions'][0]['success'])

    def test_fresh_keyboard_snapshot_rejects_foreign_popup_and_recipient(self):
        for damage in ('pid','owner','hidden','focus'):
            with self.subTest(damage=damage):
                m,api,p,record,clock,b,probe,_=self.context()
                snapshot=probe.snapshot
                def changed(binding,target):
                    row=snapshot(binding,target)
                    if target=='save':
                        if damage=='pid':row['control']['pid']=999
                        elif damage=='owner':row['popup']['ownerChain']=[99,1234]
                        elif damage=='hidden':row['popup']['visible']=False
                        else:row['gui']['focusRootHwnd']=1234
                    return row
                probe.snapshot=changed
                with self.assertRaises(AssertionError):
                    m.inspect_native_menu(api,p,11,record,'open-escape',probe=probe,clock=clock)
                self.assertEqual([x for x in b.native.calls if isinstance(x,tuple) and x[0] in ('click','key')],
                    [('click','file')])

    def test_stale_file_or_wrong_target_still_stops_before_escape(self):
        for mode in ('stale','wrongtarget'):
            with self.subTest(mode=mode):
                m,api,p,record,clock,b,probe,_=self.context(mode)
                with self.assertRaises(AssertionError):
                    m.inspect_native_menu(api,p,11,record,'open-escape',probe=probe,clock=clock)
                self.assertEqual([x for x in b.native.calls if isinstance(x,tuple) and x[0] in ('click','key')],
                    [('click','file')])

    def test_generation_change_after_file_click_blocks_the_keyboard_snapshot(self):
        m,api,p,record,clock,b,probe,observations=self.context()
        click=probe.click
        def changed(receipt):
            click(receipt)
            if receipt['target']=='file':b.native.engine['creationTime']+=1
        probe.click=changed
        with self.assertRaises(AssertionError):
            m.inspect_native_menu(api,p,11,record,'open-escape',probe=probe,clock=clock)
        self.assertEqual(sum(target=='save' for target,_ in observations),0)
        self.assertEqual([x for x in b.native.calls if isinstance(x,tuple) and x[0] in ('click','key')],
            [('click','file')])


class SourceOpenEscapeObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_native_menu_source_selection import SourceMenuSelectionTests
        cls.gate=SourceMenuSelectionTests(methodName='runTest')
        cls.gate.setUp();cls.addClassCleanup(cls.gate.doCleanups)
        cls.prepared=cls.gate.prepared();cls.selection=cls.gate.selected(cls.prepared)

    def context(self,**options):
        return profiles._source_qualified_action_context(self,self.prepared.admission,self.selection,**options)

    def test_mode4_open_escape_keeps_one_fresh_scope_and_exact_input_consumption(self):
        context=self.context();action=context.run('open-escape',True)
        self.assertEqual(len(context.runs),1)
        self.assertEqual(action.get('sourcePointSnapshots',[]),[])
        self.assertEqual([(x['sourceScopeId'],x['useCode']) for x in action['pointUses']],[(1,1),(1,4)])
        key,=action['keys'];proof=key['before']['targetPointProof']['providerLocalProof']
        self.assertEqual(proof['sourceScopeId'],1)
        self.assertEqual(proof['provider'],context.runs[0].packet)
        self.assertIs(context.runs[0].source.fresh_target,context.runs[0].fresh_refs['target:save'])
        keyboard,=[x for x in context.native_inputs if x['kind']=='keyboard']
        self.assertEqual(keyboard['deadline'],proof['effectiveDeadline'])
        self.assertLess(key['inputStartedAt'],proof['effectiveDeadline'])
        self.assertEqual((context.probe.deadline,context.keyboard.deadline,action['deadline']),(6.,6.,6.))
        self.assertIs(context.module.require_native_menu_action(action,77,11,'open-escape',
            source_admission=self.prepared.admission),action)

    def test_mode4_replay_rejects_expired_foreign_or_unjoined_keyboard_proof(self):
        context=self.context();action=context.run('open-escape',True)
        native_count=len(context.native_inputs)
        for damage in ('expired','foreign','scope','missing-point','missing-use','old-packet'):
            with self.subTest(damage=damage):
                changed=copy.deepcopy(action);key=changed['keys'][0]
                proof=key['before']['targetPointProof']['providerLocalProof']
                if damage=='expired':key['inputStartedAt']=proof['effectiveDeadline']
                elif damage=='foreign':proof['before']['pid']=999
                elif damage=='scope':proof['sourceScopeId']=3
                elif damage=='missing-point':del key['before']['targetPointProof']
                elif damage=='missing-use':changed['pointUses'].pop()
                else:proof['provider']['sourceBound']=0
                with self.assertRaises((AssertionError,KeyError)):
                    context.module.require_native_menu_action(changed,77,11,'open-escape',
                        source_admission=self.prepared.admission)
        self.assertEqual(len(context.native_inputs),native_count)

    def test_mode4_near_budget_observes_once_without_extending_five_seconds(self):
        context=self.context(call_step=.012);click=context.probe.click
        def near_deadline(receipt):
            click(receipt)
            if receipt['target']=='file':context.clock.now=4.95
        context.probe.click=near_deadline
        action=context.run('open-escape',True)
        self.assertEqual(len(context.runs),1)
        self.assertTrue(action['success'])
        self.assertEqual(action['deadline'],6.)
        key,=action['keys']
        self.assertLess(key['inputStartedAt'],key['before']['targetPointProof']['providerLocalProof']['effectiveDeadline'])
        self.assertLess(action['finishedAt'],6.)

    def test_mode4_final_key_guard_still_expires_before_sendinput(self):
        context=self.context();context.expire_keyboard=True
        with self.assertRaises(AssertionError):context.run('open-escape',True)
        self.assertEqual(len(context.runs),1)
        self.assertFalse(any(x['kind']=='keyboard' for x in context.native_inputs))
        self.assertEqual((context.probe.deadline,context.keyboard.deadline),(6.,6.))

    def test_mode4_pending_first_key_point_blocks_all_later_queries_and_input(self):
        context=self.context();context.pending_on=1
        try:
            with self.assertRaises(AssertionError):context.run('open-escape',True)
            self.assertEqual(len(context.runs),1)
            self.assertEqual(context.post_pending_queries,0)
            self.assertEqual([x['kind'] for x in context.native_inputs],['mouse'])
        finally:
            if context.runs:context.runs[-1].lease.pending=False

    def test_mode4_missing_popup_is_rejected_without_observation_retry_or_escape(self):
        context=self.context();click=context.probe.click
        def missing_popup(receipt):
            click(receipt)
            if receipt['target']=='file':context.boundary.native.opened=False
        context.probe.click=missing_popup
        with self.assertRaises(context.module.NativeMenuPending):context.run('open-escape',True)
        self.assertEqual(context.runs,[])
        self.assertFalse(any(x['kind']=='keyboard' for x in context.native_inputs))
        self.assertEqual(context.probe.deadline,6.)

    def test_mode4_late_fresh_snapshot_cannot_authorize_escape(self):
        context=self.context();snapshot=context.probe.snapshot
        def late(binding,target):
            row=snapshot(binding,target)
            if target=='save':context.clock.now=6.
            return row
        context.probe.snapshot=late
        with self.assertRaises(AssertionError):context.run('open-escape',True)
        self.assertFalse(any(x['kind']=='keyboard' for x in context.native_inputs))
        self.assertEqual(context.probe.deadline,6.)


if __name__=='__main__':unittest.main()
