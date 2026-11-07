"""Replay of a separate native popup/MSAA point proof, never Windows evidence."""
import copy
import unittest

import test_owned_native_menu as boundaries


def canonical_provider_point(snapshot,*,target,hit=None,scope_id=1):
    """A complete synthetic mode-2 point from an actual owned-menu snapshot."""
    scope=copy.deepcopy(snapshot['identityProof']['scope']);binding=scope['binding']
    role='target:'+target;roles=list(snapshot['identityProof']['roles'])
    negatives=[name for name in roles if name!=role]+['global-point']
    rect=snapshot['control']['rectangle'];point=[(rect[0]+rect[2])//2,(rect[1]+rect[3])//2]
    popup=snapshot['popup'];pid=binding['officePid'];hwnd=popup['hwnd']
    provider=dict(schemaVersion=2,workerSchemaVersion=2,diagnosticOnly=1,acceptanceEligible=0,
        providerLocalOnly=1,globalHitSubstituted=0,synthetic=0,scopeId=scope_id,stageCode=13,
        nativeAttempted=1,nativeExit=1,threadClosed=1,processesClosed=1,localKnown=1,localMatch=1,
        workerCleanup=1,workerException=0,pending=0,workerMta=1,comInitialized=1,
        comUninitialized=1,dpiEntered=1,dpiRestored=1,physicalDpiVerified=1,
        processBefore=1,processAfter=1,referencesAcquired=16,referencesReleased=16,
        variantAttempted=1,variantCleared=1,variantCleanupHresult=0,variantType=9,cleanupError=0,
        canonicalStatus=1,bindingCount=4,selfCount=4,filePairEqual=1,fileOriginalRepeatEqual=1,
        targetPairEqual=1,targetDifferentFromFile=1,hitMatchesTarget=1,fileUiPositive=1,
        targetUiPositive=1,negativeCount=len(negatives),negativeRejected=len(negatives),workerStage=8,
        controllerPid=33,threadId=124,threadBirth=300,threadIdentity=1,callbackIdentity=1,
        exitCodeObserved=1,nativeExitCode=0)
    counts=dict(pattern=4,child_id=4,accessible=5,accessible_query=6,control_type=4,
        hit_test=1,query=1,compare=2+len(negatives))
    for name,count in counts.items():
        provider.update({name+'Attempted':count,name+'Completed':count,name+'Hresult':0})
    exposed=dict(classCode=1,hwnd=hwnd,pid=pid,threadId=popup['threadId'],rootHwnd=hwnd,
        style=0x80000000,extendedStyle=0x80,rectangle=[0,45,258,1000],point=point,
        ownerChain=copy.deepcopy(popup['ownerChain']),foreground=binding['document'],
        ownershipBefore=True,ownershipAfter=True)
    proof=dict(schemaVersion=2,method='owned-popup-and-msaa-canonical-hit-v2',scope=scope,
        role=role,sourceScopeId=scope_id,negativeRoles=negatives,provider=provider,before=exposed,
        after=copy.deepcopy(exposed),sourceFresh=copy.deepcopy(snapshot['identityProof']),
        fresh=copy.deepcopy(snapshot['identityProof']),creator=dict(threadId=123,mta=True,sameThread=True),
        globalPoint=dict(kindCode=50033,pid=pid,nativeHwnd=hwnd),sourceScope=dict(scope_id=scope_id,
            engine_pid=pid,engine_birth=scope['officeCreationTime'],shell_pid=scope['shellPid'],
            shell_birth=scope['shellCreationTime'],parent_hwnd=binding['parent'],child_hwnd=binding['child'],
            x=point[0],y=point[1]))
    result=copy.deepcopy(hit) if hit is not None else dict(point=point,hitHwnd=hwnd,pid=pid,rootHwnd=hwnd)
    result.update(pointMethod=proof['method'],providerLocalProof=proof,uiaMatches=False,withinControl=False,
        identityProof=dict(scope=copy.deepcopy(scope),role=role,targetEqualsRetained=True,
            hitEqualsRetained=False,differentFrom={name:False for name in roles if name!=role}))
    return result


class NativeMenuPointProofTests(unittest.TestCase):
    def fixture(self):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,boundary=owner.real_chrome_fixture()
        value=module.click_native_menu_action(api,process,11,record,'save',probe=boundary.probe,clock=clock)
        item=value['pointers'][-1];snapshot=item['snapshots'][1];hit=copy.deepcopy(item['hits'][0])
        role='target:save';roles=list(snapshot['identityProof']['roles'])
        negatives=[name for name in roles if name!=role]+['global-point']
        provider=dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,providerLocalOnly=1,
            globalHitSubstituted=0,synthetic=0,scopeId=1,stageCode=13,nativeAttempted=1,
            nativeExit=1,threadClosed=1,processesClosed=1,localKnown=1,localMatch=1,
            workerCleanup=1,workerException=0,pending=0,workerMta=1,comInitialized=1,
            comUninitialized=1,dpiEntered=1,dpiRestored=1,processBefore=1,processAfter=1,
            referencesAcquired=5,referencesReleased=5,variantAttempted=1,variantCleared=1,
            variantCleanupHresult=0,variantType=9,childIdZero=1,fileRoundTrip=1,
            targetFreshPositive=1,targetRetainedPositive=1,negativeCount=len(negatives),
            negativeRejected=len(negatives),cleanupError=0,physicalDpiVerified=1,workerStage=8,
            controllerPid=33,threadId=124,threadBirth=300,threadIdentity=1,callbackIdentity=1,
            exitCodeObserved=1,nativeExitCode=0)
        for name in ('pattern','child_id','accessible','from_accessible','hit_test','query','compare'):
            provider.update({name+'Attempted':1,name+'Completed':1,name+'Hresult':0})
        provider.update(from_accessibleAttempted=2,from_accessibleCompleted=2,
            compareAttempted=len(negatives)+3,compareCompleted=len(negatives)+3)
        popup=dict(classCode=1,hwnd=99,pid=88,threadId=9,rootHwnd=99,style=0x80000000,
            extendedStyle=0x80,rectangle=[0,45,258,689],point=list(hit['point']),ownerChain=[99,56],
            foreground=11,ownershipBefore=True,ownershipAfter=True)
        proof=dict(schemaVersion=1,method='owned-popup-and-msaa-hit',scope=copy.deepcopy(snapshot['identityProof']['scope']),
            role=role,sourceScopeId=1,negativeRoles=negatives,provider=provider,before=popup,
            after=copy.deepcopy(popup),fresh=copy.deepcopy(snapshot['identityProof']),
            creator=dict(threadId=123,mta=True,sameThread=True),
            globalPoint=dict(kindCode=50033,pid=88,nativeHwnd=99))
        proof['sourceScope']=dict(scope_id=1,engine_pid=88,engine_birth=200,shell_pid=77,shell_birth=100,
            parent_hwnd=55,child_hwnd=56,x=hit['point'][0],y=hit['point'][1])
        hit.update(pointMethod=proof['method'],providerLocalProof=proof,uiaMatches=False,withinControl=False)
        hit['identityProof']['hitEqualsRetained']=False
        return module,value,snapshot,hit

    def test_distinct_method_preserves_original_global_false(self):
        module,value,snapshot,hit=self.fixture()
        module._require_point(hit,snapshot,'save')
        self.assertFalse(hit['uiaMatches']);self.assertFalse(hit['identityProof']['hitEqualsRetained'])
        self.assertEqual(hit['providerLocalProof']['provider']['globalHitSubstituted'],0)

    def test_observed_target_snapshot_replays_the_separate_point_before_any_keyboard_input(self):
        module,value,snapshot,hit=self.fixture();snapshot['targetPointProof']=hit
        module._validate(snapshot,value['binding'],77,'save')
        hit['providerLocalProof']['provider']['localMatch']=0
        with self.assertRaises(AssertionError):module._validate(snapshot,value['binding'],77,'save')

    def test_native_exit_cleanup_lateness_and_synthetic_evidence_cannot_qualify(self):
        for key,value in (('nativeExit',0),('threadClosed',0),('processesClosed',0),('pending',1),
                ('workerCleanup',0),('workerException',1),('stageCode',11),('synthetic',1),
                ('globalHitSubstituted',1),('localKnown',0),('variantCleared',0),('dpiRestored',0),
                ('physicalDpiVerified',0),('threadIdentity',0),('callbackIdentity',0),('exitCodeObserved',0),
                ('nativeExitCode',1),('controllerPid',0),('threadBirth',0),('workerStage',7)):
            with self.subTest(key=key):
                module,record,snapshot,hit=self.fixture();hit['providerLocalProof']['provider'][key]=value
                with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')

    def test_wrong_scope_role_creator_negative_count_or_hresult_is_rejected(self):
        for damage in ('scope','source-scope','source-point','role','creator','mta','negative','negative-count','hresult','references','compare-count'):
            with self.subTest(damage=damage):
                module,record,snapshot,hit=self.fixture();proof=hit['providerLocalProof'];provider=proof['provider']
                if damage=='scope':proof['scope']['startedAt']+=.01
                elif damage=='source-scope':proof['sourceScope']['engine_birth']+=1
                elif damage=='source-point':proof['sourceScope']['x']+=1
                elif damage=='role':proof['role']='target:open'
                elif damage=='creator':proof['creator']['sameThread']=False
                elif damage=='mta':proof['creator']['mta']=False
                elif damage=='negative':proof['negativeRoles'][-1]='file'
                elif damage=='negative-count':provider['negativeRejected']-=1
                elif damage=='hresult':provider['hit_testHresult']=0x80004005
                elif damage=='references':provider['referencesReleased']-=1
                else:provider['compareCompleted']-=1
                with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')

    def test_changed_physical_popup_or_post_fresh_identity_is_rejected(self):
        for damage in ('class','style','owner','hwnd','rect','after','fresh'):
            with self.subTest(damage=damage):
                module,record,snapshot,hit=self.fixture();proof=hit['providerLocalProof'];popup=proof['before']
                if damage=='class':popup['classCode']=0
                elif damage=='style':popup['extendedStyle']=0
                elif damage=='owner':popup['ownerChain']=[99,123]
                elif damage=='hwnd':popup['hwnd']=100
                elif damage=='rect':popup['rectangle']=[0,0,1,1]
                elif damage=='after':proof['after']['threadId']=10
                else:proof['fresh']['positive']['file']=False
                with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')

    def test_global_proof_and_file_target_cannot_be_relabelled(self):
        for damage in ('global-true','target-false','negative-true','file-target','missing'):
            with self.subTest(damage=damage):
                module,record,snapshot,hit=self.fixture()
                if damage=='global-true':hit['uiaMatches']=True
                elif damage=='target-false':hit['identityProof']['targetEqualsRetained']=False
                elif damage=='negative-true':hit['identityProof']['differentFrom']['file']=True
                elif damage=='missing':del hit['providerLocalProof']
                with self.assertRaises((AssertionError,KeyError)):
                    module._require_point(hit,snapshot,'file' if damage=='file-target' else 'save')


class NativeMenuCanonicalPointProofTests(unittest.TestCase):
    def fixture(self):
        previous=NativeMenuPointProofTests(methodName='runTest');self.addCleanup(previous.doCleanups)
        module,value,snapshot,hit=previous.fixture()
        return module,value,snapshot,canonical_provider_point(snapshot,target='save',hit=hit)

    def test_complete_v2_proof_replays_without_changing_global_false(self):
        module,value,snapshot,hit=self.fixture();module._require_point(hit,snapshot,'save')
        self.assertFalse(hit['uiaMatches']);self.assertFalse(hit['identityProof']['hitEqualsRetained'])
        self.assertNotIn('fileRoundTrip',hit['providerLocalProof']['provider'])

    def test_closed_v2_packet_rejects_extra_missing_noninteger_or_relabelled_v1(self):
        for damage in ('extra','missing','bool','negative','v1'):
            with self.subTest(damage=damage):
                module,value,snapshot,hit=self.fixture();provider=hit['providerLocalProof']['provider']
                if damage=='extra':provider['unreviewed']=1
                elif damage=='missing':del provider['fileOriginalRepeatEqual']
                elif damage=='bool':provider['filePairEqual']=True
                elif damage=='negative':provider['canonicalStatus']=-1
                else:
                    old=NativeMenuPointProofTests(methodName='runTest');self.addCleanup(old.doCleanups)
                    provider=old.fixture()[3]['providerLocalProof']['provider'];provider['schemaVersion']=2
                    hit['providerLocalProof']['provider']=provider
                with self.assertRaises((AssertionError,KeyError)):module._require_point(hit,snapshot,'save')

    def test_every_native_pair_positive_cleanup_and_original_budget_predicate_is_required(self):
        flags=('bindingCount','selfCount','filePairEqual','fileOriginalRepeatEqual','targetPairEqual',
            'targetDifferentFromFile','hitMatchesTarget','fileUiPositive','targetUiPositive','canonicalStatus',
            'nativeExit','workerCleanup','variantCleared','threadClosed','processesClosed','localKnown',
            'physicalDpiVerified','threadIdentity','callbackIdentity','exitCodeObserved')
        for field in flags:
            with self.subTest(field=field):
                module,value,snapshot,hit=self.fixture();hit['providerLocalProof']['provider'][field]=0
                with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')
        for field,value in (('pending',1),('synthetic',1),('workerException',1),('nativeExitCode',1),
                ('stageCode',11),('workerStage',7),('variantType',3),('referencesReleased',15),
                ('referencesAcquired',17),('workerSchemaVersion',1),('globalHitSubstituted',1)):
            with self.subTest(field=field):
                module,record,snapshot,hit=self.fixture();hit['providerLocalProof']['provider'][field]=value
                with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')

    def test_all_exact_operation_counts_and_hresult_are_replayed(self):
        for name in ('pattern','child_id','accessible','accessible_query','control_type','hit_test','query','compare'):
            for suffix in ('Attempted','Completed','Hresult'):
                with self.subTest(operation=name,suffix=suffix):
                    module,value,snapshot,hit=self.fixture();provider=hit['providerLocalProof']['provider']
                    provider[name+suffix]+=1
                    with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')

    def test_source_fresh_post_fresh_creator_and_popup_remain_joined_to_original_scope(self):
        for damage in ('sourceFresh','fresh','scope','source-scope','source-point','creator','role',
                'negative','negative-count','popup','source-extra','outer-extra','schema','method'):
            with self.subTest(damage=damage):
                module,value,snapshot,hit=self.fixture();proof=hit['providerLocalProof']
                if damage in ('sourceFresh','fresh'):proof[damage]['positive']['file']=False
                elif damage=='scope':proof['scope']['startedAt']+=.01
                elif damage=='source-scope':proof['sourceScope']['engine_birth']+=1
                elif damage=='source-point':proof['sourceScope']['x']+=1
                elif damage=='creator':proof['creator']['sameThread']=False
                elif damage=='role':proof['role']='target:open'
                elif damage=='negative':proof['negativeRoles'].pop()
                elif damage=='negative-count':proof['provider']['negativeRejected']-=1
                elif damage=='popup':proof['after']['threadId']+=1
                elif damage=='source-extra':proof['sourceScope']['other']=1
                elif damage=='outer-extra':proof['other']=1
                elif damage=='schema':proof['schemaVersion']=1
                else:proof['method']='owned-popup-and-msaa-hit'
                with self.assertRaises((AssertionError,KeyError)):module._require_point(hit,snapshot,'save')

    def test_global_true_file_target_or_wrong_method_never_becomes_v2_point(self):
        for damage in ('global-true','file','unknown','v1-method'):
            with self.subTest(damage=damage):
                module,value,snapshot,hit=self.fixture()
                if damage=='global-true':hit['uiaMatches']=True
                elif damage=='unknown':hit['pointMethod']='unreviewed-canonical'
                elif damage=='v1-method':hit['pointMethod']='owned-popup-and-msaa-hit'
                with self.assertRaises((AssertionError,KeyError)):module._require_point(hit,snapshot,'file' if damage=='file' else 'save')

    def test_snapshot_and_full_action_replay_reject_corrupted_v2_positive(self):
        module,value,snapshot,hit=self.fixture();snapshot['targetPointProof']=hit
        module._validate(snapshot,value['binding'],77,'save')
        hit['providerLocalProof']['provider']['hitMatchesTarget']=0
        with self.assertRaises(AssertionError):module._validate(snapshot,value['binding'],77,'save')
        module,action=boundaries.canonical_action_fixture(self)
        module.require_native_menu_action(action,77,11,'save')
        action['pointers'][-1]['hits'][1]['providerLocalProof']['provider']['targetPairEqual']=0
        with self.assertRaises(AssertionError):module.require_native_menu_action(action,77,11,'save')

    def test_v2_native_numbers_cannot_be_boolean_float_or_outside_original_scope_domain(self):
        for damage in ('class-bool','pid-float','thread-bool','source-bool','source-float'):
            with self.subTest(damage=damage):
                module,value,snapshot,hit=self.fixture();proof=hit['providerLocalProof']
                if damage=='class-bool':proof['before']['classCode']=True;proof['after']=copy.deepcopy(proof['before'])
                elif damage=='pid-float':proof['before']['pid']=float(proof['before']['pid']);proof['after']=copy.deepcopy(proof['before'])
                elif damage=='thread-bool':proof['before']['threadId']=True;proof['after']=copy.deepcopy(proof['before'])
                elif damage=='source-bool':proof['sourceScope']['scope_id']=True
                else:proof['sourceScope']['engine_birth']=float(proof['sourceScope']['engine_birth'])
                with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')


class SourceQualifiedHistoricalPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_native_menu_source_selection import SourceMenuSelectionTests
        cls.gate=SourceMenuSelectionTests(methodName='test_prepares_actual_bare_gate_context_and_freezes_contexts')
        cls.gate.setUp();cls.addClassCleanup(cls.gate.doCleanups)
        cls.prepared=cls.gate.prepared();cls.selection=cls.gate.selected(cls.prepared)

    def fixture(self,operation='save',gesture=False):
        from test_native_menu_point_profile import source_qualified_action_fixture
        module,action=source_qualified_action_fixture(self,self.prepared.admission,self.selection,operation,gesture)
        if action['pointers']:return module,action,action['pointers'][-1]['snapshots'][-1],action['pointers'][-1]['hits'][-1]
        snapshot=action['keys'][-1]['before']
        return module,action,snapshot,snapshot['targetPointProof']

    def require(self,module,action):
        return module.require_native_menu_action(action,77,11,'save',source_admission=self.prepared.admission)

    def test_historical_replay_uses_recorded_consumption_without_querying_live_time(self):
        from unittest.mock import patch
        module,action,snapshot,hit=self.fixture()
        with patch.object(module.time,'monotonic',side_effect=AssertionError('Historical replay queried live time')):
            self.assertIs(self.require(module,action),action)
        with self.assertRaises(AssertionError):
            module._require_point(hit,snapshot,'save',source_admission=self.prepared.admission,now=100.)

    def test_serial_measurements_cannot_reverse_observation_time_and_sort_the_use_ledger(self):
        module,action,snapshot,hit=self.fixture()
        first,second=[row['targetPointProof'] for row in action['pointers'][-1]['snapshots'][:2]]
        times=[(row['pointObservedAt'],row['providerLocalProof']['capturedAt'],row['providerLocalProof']['effectiveDeadline']) for row in (first,second)]
        for row,values in zip((first,second),reversed(times)):
            row['pointObservedAt']=values[0]
            row['providerLocalProof'].update(capturedAt=values[1],effectiveDeadline=values[2])
        for use in action['pointUses']:
            if use['sourceScopeId'] in (1,2):use['at']=(first,second)[use['sourceScopeId']-1]['pointObservedAt']
        action['pointUses'].sort(key=lambda row:(row['at'],row['sourceScopeId'],row['useCode']))
        with self.assertRaises(AssertionError):self.require(module,action)

    def test_actual_admission_is_required_and_default_old_policy_cannot_accept_four(self):
        module,action,snapshot,hit=self.fixture()
        with self.assertRaises(AssertionError):module.require_native_menu_action(action,77,11,'save')
        with self.assertRaises((AssertionError,ValueError)):
            module.require_native_menu_action(action,77,11,'save',source_admission=action['sourceMenu']['admission'])
        with self.assertRaises(AssertionError):module._require_point(hit,snapshot,'save')
        with self.assertRaises(AssertionError):
            module._require_point(hit,snapshot,'save',source_admission=self.prepared.admission)

    def test_public_four_replay_rejects_other_modes_raw_false_and_native_schema_tampering(self):
        module,original,snapshot,hit=self.fixture()
        mutations=(lambda hit:hit.update(pointMethod='owned-popup-and-msaa-canonical-hit-v2'),
            lambda hit:(hit.update(pointMethod='global-uia',uiaMatches=True,withinControl=True),hit['identityProof'].update(hitEqualsRetained=True)),
            lambda hit:hit.update(uiaMatches=True),lambda hit:hit['identityProof'].update(hitEqualsRetained=True),
            lambda hit:hit['providerLocalProof'].update(schemaVersion=3),
            lambda hit:hit['providerLocalProof']['provider'].update(workerSchemaVersion=3),
            lambda hit:hit['providerLocalProof']['provider'].update(nativeExit=0),
            lambda hit:hit['providerLocalProof']['provider'].update(pending=1),
            lambda hit:hit['providerLocalProof']['globalPoint'].update(nativeHwndRaw=99.),
            lambda hit:hit['providerLocalProof'].update(sourceAdmissionSha256='0'*64))
        for index,change in enumerate(mutations):
            with self.subTest(case=index):
                action=copy.deepcopy(original);change(action['pointers'][-1]['hits'][-1])
                with self.assertRaises((AssertionError,ValueError)):self.require(module,action)

    def test_point_uses_join_completion_expiry_real_input_and_finite_typed_scope(self):
        module,original,snapshot,hit=self.fixture()
        mutations=(lambda action:action['pointUses'][-1].update(at=hit['providerLocalProof']['capturedAt']),
            lambda action:action['pointUses'][-1].update(sourceScopeId=True),
            lambda action:action['pointUses'][-1].update(useCode=2),
            lambda action:action['pointUses'][-1].update(at=float('nan')),
            lambda action:action['pointers'][-1].update(inputStartedAt=hit['providerLocalProof']['effectiveDeadline']),
            lambda action:action['pointers'][-1]['hits'][-1].update(pointObservedAt=hit['providerLocalProof']['effectiveDeadline']),
            lambda action:action['pointUses'].pop(),
            lambda action:action.update(pointUses=[copy.deepcopy(action['pointUses'][0]) for _ in range(129)]))
        for index,change in enumerate(mutations):
            with self.subTest(case=index):
                action=copy.deepcopy(original);change(action)
                with self.assertRaises((AssertionError,ValueError)):self.require(module,action)

    def test_duplicate_fifth_site_cannot_pass_by_relabeling_the_use_and_latest_worker(self):
        module,action,snapshot,hit=self.fixture()
        item=action['pointers'][-1];item['hits'][-1]=copy.deepcopy(item['hits'][0])
        for use in action['pointUses']:
            if use['sourceScopeId']==5:use['sourceScopeId']=3
        action['uiaInterop']['providerLocalResult']=copy.deepcopy(item['hits'][0]['providerLocalProof']['provider'])
        with self.assertRaises(AssertionError):self.require(module,action)

    def test_closed_header_binds_actual_source_root_original_generation_and_summary(self):
        module,original,snapshot,hit=self.fixture()
        mutations=(lambda action:action['sourceMenu']['admission'].update(admissionSha256='0'*64),
            lambda action:action['sourceMenu']['generation'].update(shellHandleValue=9),
            lambda action:action['sourceMenu']['generation'].update(engineHandleValue=10),
            lambda action:action['originalEngine'].update(image=str(self.prepared.admission.suite_root/'wrong.bin')),
            lambda action:action['sourceMenu'].update(extra=1),
            lambda action:action['sourceMenu'].update(pointProfileVersion=3),
            lambda action:action.update(sourcePointSnapshots=[copy.deepcopy(action['pointers'][-1]['snapshots'][0])]))
        for index,change in enumerate(mutations):
            with self.subTest(case=index):
                action=copy.deepcopy(original);change(action)
                with self.assertRaises((AssertionError,ValueError)):self.require(module,action)

    def test_missing_or_late_actual_input_finish_cannot_be_replayed_as_success(self):
        module,original,snapshot,hit=self.fixture()
        for missing in (True,False):
            with self.subTest(missing=missing):
                action=copy.deepcopy(original);pointer=action['pointers'][-1]
                if missing:pointer.pop('inputFinishedAt')
                else:pointer['inputFinishedAt']=hit['providerLocalProof']['effectiveDeadline']
                with self.assertRaises((AssertionError,KeyError,ValueError)):self.require(module,action)

    def test_keyboard_before_snapshot_cannot_reuse_the_previous_key_source_site(self):
        module,action,snapshot,hit=self.fixture('keyboard-escape',True)
        self.assertIs(module.require_native_menu_action(action,77,11,'keyboard-escape',source_admission=self.prepared.admission),action)
        keys=action['keys'];self.assertEqual([key['shortcut'] for key in keys],['ALT_F','DOWN','ESCAPE'])
        earlier=keys[1]['before']['targetPointProof']['providerLocalProof']['sourceScopeId']
        later=keys[2]['before']['targetPointProof']['providerLocalProof']['sourceScopeId']
        self.assertNotEqual(earlier,later)
        keys[2]['before']=copy.deepcopy(keys[1]['before'])
        for use in action['pointUses']:
            if use['sourceScopeId']==later:use['sourceScopeId']=earlier
        action['uiaInterop']['providerLocalResult']=copy.deepcopy(keys[1]['before']['targetPointProof']['providerLocalProof']['provider'])
        with self.assertRaises(AssertionError):
            module.require_native_menu_action(action,77,11,'keyboard-escape',source_admission=self.prepared.admission)


if __name__=='__main__':unittest.main()
