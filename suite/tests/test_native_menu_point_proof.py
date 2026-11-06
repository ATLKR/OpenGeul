"""Replay of a separate native popup/MSAA point proof, never Windows evidence."""
import copy
import unittest

import test_owned_native_menu as boundaries


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


if __name__=='__main__':unittest.main()
