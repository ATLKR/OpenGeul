"""Selected OS privacy verification only; all native behavior is synthetic."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
import test_native31_privacy_prepare as existing

SOURCE=ROOT/'suite/e2e/writer_privacy_close.py'
m=None
if SOURCE.is_file():
    spec=importlib.util.spec_from_file_location('writer_privacy_close_tested',SOURCE)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PrivacyGateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(m,'Fixed privacy-close entry is absent')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        data=existing.PreparationContracts('runTest');data.setUp()
        self.contract=existing.ActionContracts('runTest')
        self.contract.observed=data.observed;self.contract.classification=data.classification
        self.session,self.observed,self.process,self.sent,self.closed=self.contract.session(self.temp.name)
        self.probe=self.session.probe;self.core=existing.m;self.privacy=existing.p
        self.probe.user.GetAncestor.action=lambda hwnd,flag:12
        self.state=m.empty_record();self.session.evidence=m.NumericEvidence(self.session.evidence,self.state)
        self.title_reads=0;self.uia_reads=0
        target=self.probe.target;uia=self.probe.strict_uia
        def selected_target(hwnd):self.title_reads+=1;return target(hwnd)
        def selected_uia(hwnd):self.uia_reads+=1;return uia(hwnd)
        self.probe.target=selected_target;self.probe.strict_uia=selected_uia
        self.images=self.contract.image_patches(self.process);self.images.__enter__();self.addCleanup(self.images.__exit__,None,None,None)

    def observe(self,expected=None):
        return m.observe_candidate(self.core,self.probe,self.session.budget,self.session.evidence,
            self.state,expected=expected,source_check=self.session.identity_source)

    def test_verified_non_core_foreground_never_reads_title_uia_or_closes(self):
        self.probe.text_value=lambda *args,**kwargs:'Synthetic.NonCoreClass'
        self.assertIsNone(self.observe())
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))
        self.assertIs(self.state['coreWindowObserved'],False)

    def test_unknown_core_owner_is_rejected_before_title_or_uia(self):
        original=self.probe.process_identity
        self.probe.process_identity=lambda *args:dict(original(*args),imagePath=r'C:\Other\WWAHost.exe')
        with self.assertRaises(ValueError):self.observe()
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_missing_signature_rejects_before_title_or_uia(self):
        with mock.patch.object(self.core,'signatures',return_value=[dict(self.process['signature'],status='NotSigned')]):
            with self.assertRaises(ValueError):self.observe()
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_wrong_session_native_or_birth_rejects_before_title_or_uia(self):
        original=self.probe.process_identity
        for field,value in [('sessionId',2),('processMachine',0x8664),('nativeMachine',0x8664),('createdFileTime',0)]:
            self.probe.process_identity=lambda *args,k=field,v=value:dict(original(*args),**{k:v})
            with self.subTest(),self.assertRaises(ValueError):self.observe()
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_foreground_change_is_rejected_before_title_or_uia(self):
        calls=[]
        self.probe.user.GetForegroundWindow.action=lambda:12 if not calls else 99
        original=self.core.signatures
        def changed(*args):calls.append(1);return original(*args)
        with mock.patch.object(self.core,'signatures',side_effect=changed):
            with self.assertRaises(ValueError):self.observe()
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_source_check_race_is_rechecked_before_title_or_uia(self):
        changed=[];original=self.probe.startup_process_state
        self.probe.startup_process_state=lambda *args:dict(original(*args),createdFileTime=self.process['createdFileTime']+bool(changed))
        self.session.identity_source=lambda:changed.append(1)
        with self.assertRaises(ValueError):self.observe()
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_first_source_check_expiry_has_no_title_or_uia_read(self):
        self.session.identity_source=lambda:setattr(self.session.budget,'deadline',0)
        with self.assertRaises(TimeoutError):self.observe()
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_final_source_check_cannot_consume_the_send_and_cleanup_reserve(self):
        calls=[]
        def source_check():
            calls.append(1)
            if len(calls)==2:self.session.budget.deadline=0
        self.session.identity_source=source_check
        with self.assertRaises(TimeoutError):self.observe()
        self.assertEqual(len(self.sent),0)

    def test_exact_privacy_candidate_is_validated_after_owner_gate(self):
        candidate=self.observe()
        self.assertEqual(candidate['kind'],'WWAHost.exe')
        self.assertEqual((self.title_reads,self.uia_reads),(2,1))
        self.assertIs(self.state['signatureVerified'],True);self.assertIs(self.state['privacyValidated'],True)
        self.assertEqual(len(self.sent),0)

    def test_uia_error_does_not_read_its_raw_message_or_close(self):
        class Poison:
            def __str__(self):raise AssertionError()
            def __repr__(self):raise AssertionError()
        self.probe.strict_uia=lambda hwnd:dict(hwnd=hwnd,error={'message':Poison()},nodes=[],truncated=False)
        with self.assertRaises(ValueError):self.observe()
        self.assertEqual(len(self.sent),0)

    def test_non_privacy_uia_context_is_rejected_without_close(self):
        self.probe.strict_uia=lambda hwnd:dict(self.observed['uia'][0],nodes=[])
        with self.assertRaises(ValueError):self.observe()
        self.assertEqual(len(self.sent),0)

    def test_reused_pid_generation_fails_before_a_new_title_or_uia_read(self):
        candidate=self.observe();self.title_reads=self.uia_reads=0
        original=self.probe.process_identity
        self.probe.process_identity=lambda *args:dict(original(*args),createdFileTime=self.process['createdFileTime']+1)
        with self.assertRaises(ValueError):self.observe(candidate)
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_original_close_is_one_message_and_cannot_run_twice(self):
        candidate=self.observe()
        m.close_candidate(self.core,self.privacy,self.session,candidate,self.state)
        self.assertEqual(len(self.sent),1);self.assertEqual(self.state['closeRequests'],1)
        self.assertIs(self.state['surfaceDismissed'],True)
        with self.assertRaises(ValueError):m.close_candidate(self.core,self.privacy,self.session,candidate,self.state)
        self.assertEqual(len(self.sent),1)

    def test_changed_generation_before_close_rejects_with_zero_messages(self):
        candidate=self.observe();original=self.probe.process_identity
        self.probe.process_identity=lambda *args:dict(original(*args),createdFileTime=self.process['createdFileTime']+1)
        with self.assertRaises(ValueError):m.close_candidate(self.core,self.privacy,self.session,candidate,self.state)
        self.assertEqual(len(self.sent),0)

    def test_partial_close_and_query_handle_cleanup_cannot_pass(self):
        self.probe.user.SendMessageTimeoutW.action=lambda *args:self.sent.append(args) or False
        self.probe.user.IsWindow.action=lambda hwnd:False if self.sent else True
        candidate=self.observe()
        with self.assertRaises(ValueError):m.close_candidate(self.core,self.privacy,self.session,candidate,self.state)
        self.assertEqual(len(self.sent),1)

    def test_raw_uia_paths_and_poison_values_are_not_serialized(self):
        class Poison:
            def __str__(self):raise AssertionError()
            def __repr__(self):raise AssertionError()
        self.session.evidence.write('p18-fresh-recheck',Poison())
        raw=b''.join(path.read_bytes() for path in self.session.evidence.path.glob('*.json'))
        for forbidden in (b'Windows Setup',b'Microsoft account',b'C:\\Windows',b'Description'):
            self.assertNotIn(forbidden,raw)

    def test_uia_initializes_only_after_original_physical_query_token_is_restored(self):
        from contextlib import contextmanager
        original_queries=self.core.physical_queries;original_uia=self.probe.strict_uia
        depth=[]
        @contextmanager
        def tracked(*args,**kwargs):
            with original_queries(*args,**kwargs):
                depth.append(1)
                try:yield
                finally:depth.pop()
        def uia(hwnd):
            self.assertEqual(len(depth),0)
            return original_uia(hwnd)
        self.probe.strict_uia=uia
        with mock.patch.object(self.core,'physical_queries',side_effect=tracked):
            self.assertIsNotNone(self.observe())
        self.assertEqual(depth,[]);self.assertEqual(len(self.sent),0)

class AdmissionAndSchemaTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(m,'Fixed privacy-close entry is absent')

    def test_receipt_is_fixed_numeric_and_never_product_acceptance(self):
        row=m.empty_record();self.assertIs(m.validate_record(row),row)
        self.assertIs(row['acceptanceEligible'],False);self.assertIs(row['hostReadyQualified'],False)
        self.assertEqual(row['osBudgetSeconds'],120)

    def test_unknown_keys_bool_numbers_and_success_without_retirement_are_rejected(self):
        for change in ({'extra':'SYNTHETIC-PRIVATE'},{'closeRequests':True},{'preparationPassed':True},
                       {'keyboardInputs':1},{'pointerInputs':1},{'foregroundSetCalls':1},{'foreignKillCalls':1}):
            row=m.empty_record();row.update(change)
            with self.subTest(),self.assertRaises(ValueError):m.validate_record(row)

    def test_raw_environment_is_not_copied_and_source_metadata_is_not_rewritten(self):
        class Synthetic:
            def __init__(self,**values):self.values=values
            def get(self,key,default=None):return self.values.get(key,default)
            def __getitem__(self,key):return self.values[key]
            def __contains__(self,key):return key in self.values
            def copy(self):raise AssertionError()
            def __iter__(self):raise AssertionError()
            def items(self):raise AssertionError()
            def keys(self):raise AssertionError()
        env=Synthetic(PATH='synthetic',GITHUB_SHA='a'*40,GITHUB_TRIGGERING_ACTOR='ATLKR',GH_TOKEN='SYNTHETIC-DO-NOT-COPY')
        child=m.child_environment(existing.m,env)
        self.assertEqual(child['GITHUB_SHA'],'a'*40);self.assertEqual(child['GITHUB_TRIGGERING_ACTOR'],'ATLKR')
        self.assertNotIn('GH_TOKEN',child);self.assertNotIn('GITHUB_JOB',child)

    def test_source_admission_uses_real_push_guard_and_exact_parent_marker_guard(self):
        guard=m.load_guard(ROOT)
        env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','RUNNER_ARCH':'ARM64',
            'GITHUB_JOB':'writer-server-observer','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_OWNER':'ATLKR',
            'GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341','GITHUB_TRIGGERING_ACTOR':'ATLKR',
            'GITHUB_EVENT_NAME':'push','GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':'refs/heads/'+guard.BRANCH,
            'GITHUB_WORKFLOW_REF':guard.WORKFLOW,'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_RUN_ID':'123'}
        event={'repository':{'full_name':'ATLKR/OpenGeul','id':1405493151,'private':False},
            'sender':{'login':'ATLKR','id':65988341,'type':'User'},'ref':'refs/heads/'+guard.BRANCH,
            'before':'b'*40,'after':'a'*40,'created':False,'deleted':False,'forced':False,
            'commits':[{'id':'a'*40}],'head_commit':{'id':'a'*40,'message':guard.MARKER}}
        with mock.patch.object(guard,'verify_request_source',return_value=(10,55)):
            row=m.admit(guard,ROOT,env,event,platform='nt');self.assertEqual(row['writerSeconds'],55)
            for field,value in [('GITHUB_JOB','windows-suite'),('GITHUB_RUN_ATTEMPT','2'),('GITHUB_EVENT_NAME','workflow_dispatch')]:
                changed=dict(env);changed[field]=value
                with self.subTest(),self.assertRaises((ValueError,guard.Rejected)):m.admit(guard,ROOT,changed,event,platform='nt')
            altered=copy.deepcopy(event);altered['head_commit']['message']='not-marker'
            with self.assertRaises((ValueError,guard.Rejected)):m.admit(guard,ROOT,env,altered,platform='nt')
        with mock.patch.object(guard,'verify_request_source',side_effect=guard.Rejected()):
            with self.assertRaises((ValueError,guard.Rejected)):m.admit(guard,ROOT,env,event,platform='nt')

    def test_static_source_admission_cannot_start_without_original_deadline_reserve(self):
        guard=m.load_guard(ROOT)
        budget=existing.m.Budget(deadline=32,clock=lambda:0)
        class Env:
            def get(self,*args):raise AssertionError()
        # Thirty-second fixed source admission plus the existing three-second cleanup reserve.
        with mock.patch.object(guard,'verify_request_source') as verifier:
            with self.assertRaises(TimeoutError):m.admit(guard,ROOT,Env(),{},platform='nt',budget=budget)
            verifier.assert_not_called()
    def test_every_runtime_source_admission_uses_the_same_original_budget(self):
        import ast
        tree=ast.parse(SOURCE.read_text())
        calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='admit']
        self.assertEqual(len(calls),5)
        for call in calls:
            with self.subTest():self.assertIn('budget',{key.arg for key in call.keywords})

REVIEWED_OS_BLOCK="    - name: Prepare only the existing pinned Windows privacy UIA dependencies\n      id: writer-os-privacy-dependencies\n      timeout-minutes: 2\n      shell: pwsh\n      run: |\n        python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n        if ($LASTEXITCODE -ne 0) { throw 'Pinned privacy UIA prerequisites are unavailable; preparation is blocked.' }\n    - name: Close only an exactly verified OS privacy window before Writer launch\n      id: writer-os-privacy-close\n      if: success()\n      timeout-minutes: 3\n      shell: pwsh\n      run: |\n        # Separate OS preparation120s; original Writer observation55/60s is unchanged.\n        $env:NATIVE31_PWSH = (Get-Command pwsh -ErrorAction Stop).Source\n        python -B suite/e2e/writer_privacy_close.py prepare\n        if ($LASTEXITCODE -ne 0) { throw 'Exact OS privacy preparation failed; Writer launch is blocked.' }\n    - name: Validate the closed OS privacy preparation receipt\n      id: writer-os-privacy-validate\n      if: always() && !cancelled() && steps.writer-os-privacy-close.outcome != 'skipped'\n      shell: pwsh\n      run: |\n        python -B suite/e2e/writer_privacy_close.py validate\n        if ($LASTEXITCODE -ne 0) { throw 'OS privacy numeric receipt is unavailable or invalid.' }\n    - name: Retain only the separate OS privacy numeric receipt\n      id: writer-os-privacy-upload\n      if: always() && !cancelled() && steps.writer-os-privacy-validate.outcome == 'success'\n      uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n      with:\n        name: opengeul-writer-os-privacy-arm64-${{ github.run_id }}-${{ github.run_attempt }}\n        path: .work/writer-os-privacy-public/receipt.numeric.json\n        retention-days: 1\n        if-no-files-found: error\n"

class WorkflowContracts(unittest.TestCase):
    def test_os_preparation_is_before_launch_and_collects_only_its_own_small_receipt(self):
        import yaml
        source=(ROOT/'.github/workflows/office-suite.yml').read_text();steps=yaml.safe_load(source)['jobs']['writer-server-observer']['steps']
        by_id={step.get('id'):step for step in steps if step.get('id')}
        self.assertIn('writer-os-privacy-close',by_id)
        self.assertIn('writer-os-privacy-validate',by_id);self.assertIn('writer-os-privacy-upload',by_id)
        order=[step.get('id') for step in steps]
        self.assertLess(order.index('writer-os-privacy-upload'),order.index('writer-context'))
        self.assertLess(order.index('writer-os-privacy-upload'),order.index('atomic-prepare'))
        self.assertNotIn('steps.writer-context',by_id['writer-os-privacy-close'].get('if',''))
        self.assertNotIn('steps.writer-context',by_id['writer-os-privacy-validate'].get('if',''))
        self.assertNotIn('always()',by_id['writer-os-privacy-close'].get('if',''))
        self.assertEqual(by_id['writer-os-privacy-upload']['with']['path'],'.work/writer-os-privacy-public/receipt.numeric.json')
        self.assertIn("steps.writer-os-privacy-validate.outcome == 'success'",by_id['writer-os-privacy-upload']['if'])
        self.assertNotIn('if',by_id['atomic-prepare']);self.assertNotIn('if',by_id['writer-observe'])
        for name in ('writer-os-privacy-close','writer-os-privacy-validate','writer-os-privacy-upload'):
            self.assertNotIn('continue-on-error',by_id[name])

    def test_exact_reviewed_inverse_restores_the_whole_original_workflow(self):
        block=REVIEWED_OS_BLOCK
        source=(ROOT/'.github/workflows/office-suite.yml').read_text()
        self.assertEqual(source.count(block),1)
        original=source.replace(block,'',1)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
            '8bfbe6b0f07ad6c17a268665526dc0922d12641b9fbc08d37c0595197d1f65c2')
        for changed in (source.replace('OS preparation120s','OS preparation121s',1),
                        source.replace('retention-days: 1','retention-days: 2',1)):
            with self.subTest():
                self.assertTrue(changed.count(block)!=1 or hashlib.sha256(changed.replace(block,'',1).encode()).hexdigest()!=
                    '8bfbe6b0f07ad6c17a268665526dc0922d12641b9fbc08d37c0595197d1f65c2')
    def test_existing_four_member_artifact_and_windows_signature_path_are_preserved(self):
        import yaml
        steps=yaml.safe_load((ROOT/'.github/workflows/office-suite.yml').read_text())['jobs']['writer-server-observer']['steps']
        by_id={step.get('id'):step for step in steps if step.get('id')}
        self.assertEqual(by_id['writer-upload']['with']['path'].splitlines(),[
            '.work/writer-observer-public/context.numeric.json','.work/writer-observer-public/report.numeric.json',
            '.work/writer-observer-public/compiler-phase.numeric.json','.work/writer-observer-public/observe-phase.numeric.json'])
        self.assertIn("$env:NATIVE31_PWSH = (Get-Command pwsh -ErrorAction Stop).Source",by_id['writer-os-privacy-close']['run'])
    def test_actual_repository_free_runner_policy_accepts_the_dedicated_workflow(self):
        from ci.policy import audit,load_workflow
        self.assertIs(audit(load_workflow(ROOT/'.github/workflows/office-suite.yml'),workflow_path='.github/workflows/office-suite.yml'),True)

    def test_privacy_uia_uses_only_the_two_existing_normal_pinned_dependencies_before_prepare(self):
        import yaml
        source=yaml.safe_load((ROOT/'.github/workflows/office-suite.yml').read_text())
        steps=source['jobs']['writer-server-observer']['steps']
        by_id={step.get('id'):step for step in steps if step.get('id')}
        order=[step.get('id') for step in steps]
        self.assertLess(order.index('writer-os-privacy-dependencies'),order.index('writer-os-privacy-close'))
        dependency=by_id['writer-os-privacy-dependencies']
        self.assertEqual(dependency['timeout-minutes'],2)
        self.assertIn('python -m pip install pywinauto==0.6.9 comtypes==1.5.0',dependency['run'])
        self.assertNotIn('continue-on-error',dependency)
        existing=[step.get('run','') for step in source['jobs']['windows-suite']['steps']]
        self.assertTrue(any('python -m pip install pywinauto==0.6.9 comtypes==1.5.0' in cmd for cmd in existing))

class ControllerReceiptTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(m,'Fixed privacy-close entry is absent')
    def fixture(self):
        base=m.empty_record();base.update(sourceAdmitted=True,sourceCommitWords=[1]*5,targetCommitWords=[2]*5,
            runId=123,runAttempt=1,sourceFileCount=10,writerSeconds=55)
        child=copy.deepcopy(base);child.update(recordKindCode=2,observationPassed=True,observationStatusCode=1,
            coreWindowObserved=False,observerPid=999,observerBirth=888)
        owned=dict(success=True,naturalExit=True,jobRetiredNaturally=True,forced=False,timedOut=False,
            exitCode=0,observer={'processId':999,'createdFileTime':888})
        return base,child,owned
    def merge(self,base,owned,child,verified=True):
        self.assertTrue(callable(getattr(m,'merge_observer',None)))
        return m.merge_observer(base,owned,child,source_verified=verified)
    def test_success_requires_original_owned_retirement_and_same_source_child(self):
        base,child,owned=self.fixture();row=self.merge(base,owned,child)
        self.assertIs(row['preparationPassed'],True);m.validate_record(row)
        for field,value in [('success',False),('jobRetiredNaturally',False),('forced',True),('timedOut',True),('naturalExit',None)]:
            changed=dict(owned);changed[field]=value
            with self.subTest():self.assertIs(self.merge(base,changed,child)['preparationPassed'],False)
    def test_timeout_without_child_receipt_preserves_unknown_action_counts(self):
        base,child,owned=self.fixture();owned.update(success=False,timedOut=True,forced=True)
        row=self.merge(base,owned,None)
        self.assertIs(row['preparationPassed'],False);self.assertIsNone(row['closeRequests'])
        self.assertIsNone(row['titleReadAttempted']);self.assertIsNone(row['uiaAttempted']);m.validate_record(row)
    def test_source_or_observer_generation_mismatch_never_borrows_child_success(self):
        for change in [('sourceCommitWords',[3]*5),('targetCommitWords',[3]*5),('observerBirth',889),('writerSeconds',60)]:
            base,child,owned=self.fixture();child[change[0]]=change[1]
            with self.subTest():
                row=self.merge(base,owned,child);self.assertIs(row['preparationPassed'],False);self.assertIsNone(row['closeRequests'])
        base,child,owned=self.fixture();self.assertIs(self.merge(base,owned,child,False)['preparationPassed'],False)
    def test_a_known_child_guard_failure_keeps_its_zero_close_and_failure_stage(self):
        base,child,owned=self.fixture();child.update(observationPassed=False,observationStatusCode=0,errorCode=1,stageCode=3)
        owned.update(success=False,exitCode=1)
        row=self.merge(base,owned,child)
        self.assertEqual((row['stageCode'],row['errorCode'],row['closeRequests']),(3,1,0))
        self.assertIs(row['preparationPassed'],False)

class EntryProtocolTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(m,'Fixed privacy-close entry is absent')
    def test_closed_file_roundtrip_and_duplicate_or_foreign_keys_are_rejected(self):
        self.assertTrue(callable(getattr(m,'read_record',None)));self.assertTrue(callable(getattr(m,'write_record',None)))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'receipt.numeric.json';m.write_record(path,m.empty_record())
            self.assertEqual(m.read_record(path),m.empty_record())
            with self.assertRaises(FileExistsError):m.write_record(path,m.empty_record())
            for raw in (b'\xff',b' '*8193,b'{"schemaVersion":1,"schemaVersion":1}',b'{"message":"SYNTHETIC-PRIVATE"}'):
                path.write_bytes(raw)
                with self.subTest(),self.assertRaises(ValueError):m.read_record(path)
    def test_validation_cli_reads_only_the_fixed_report_without_runtime_or_env(self):
        self.assertTrue(callable(getattr(m,'main',None)))
        class Poison:
            def get(self,*args):raise AssertionError()
            def __iter__(self):raise AssertionError()
            def copy(self):raise AssertionError()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/m.REPORT;path.parent.mkdir(parents=True)
            m.write_record(path,m.empty_record())
            with mock.patch.object(m,'ROOT',root),mock.patch.object(os,'environ',Poison()),mock.patch.object(m,'load_core',side_effect=AssertionError):
                self.assertEqual(m.main(['validate']),0)
    def test_controller_uses_original_owned_custody_and_does_not_launch_on_bad_job(self):
        self.assertTrue(callable(getattr(m,'run_controller',None)))
        self.assertTrue(callable(getattr(m,'control_binding',None)))
        guard=m.load_guard(ROOT);binding=m.control_binding(existing.m,guard)
        self.assertEqual((binding.ref,binding.workflow,binding.job,binding.observer_entry),
            ('refs/heads/'+guard.BRANCH,guard.WORKFLOW,'writer-server-observer',m.ENTRY))
        class ForbiddenCore:
            def Probe(self):raise AssertionError()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises((ValueError,guard.Rejected)):
                m.run_controller(ForbiddenCore(),guard,{}, {},Path(folder),deadline=1,platform='nt')
    def test_host_protocol_keeps_required_handshake_without_process_or_environment_dump(self):
        data=dict(sessionId=1,windowsDirectory='synthetic',windowsVersion=[10,0,1],imageOS='synthetic',
                  imageVersion='synthetic',desktop='Default',windowStation='WinSta0',processId=999,
                  process=dict(processId=999,createdFileTime=888,sessionId=1,processMachine=0,
                      nativeMachine=0xAA64,exitCode=259,imagePath=r'C:\Python\python.exe'))
        class Poison:
            def __str__(self):raise AssertionError()
            def __repr__(self):raise AssertionError()
        with tempfile.TemporaryDirectory() as folder:
            original=existing.m.Evidence.create(Path(folder)/'owned',Path(folder),max_files=72)
            sink=m.ProtocolEvidence(original,m.empty_record())
            try:sink.write('31-observer-host',{**data,'argv':Poison(),'environment':Poison()})
            except Exception:self.fail('Unneeded host data reached serialization')
            self.assertEqual(json.loads((original.path/'31-observer-host.json').read_text()),data)

class OwnedControllerTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(m,'Fixed privacy-close entry is absent')
    def invoke(self,mode='ok'):
        guard=m.load_guard(ROOT);real=existing.m
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        (root/m.ENTRY).parent.mkdir(parents=True);(root/m.ENTRY).write_text('# synthetic entry\n')
        env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','RUNNER_ARCH':'ARM64',
            'GITHUB_JOB':'writer-server-observer','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_OWNER':'ATLKR',
            'GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341','GITHUB_TRIGGERING_ACTOR':'ATLKR',
            'GITHUB_EVENT_NAME':'push','GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':'refs/heads/'+guard.BRANCH,
            'GITHUB_WORKFLOW_REF':guard.WORKFLOW,'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,
            'GITHUB_RUN_ID':'123','RUNNER_TEMP':str(root)}
        event={'repository':{'full_name':'ATLKR/OpenGeul','id':1405493151,'private':False},
            'sender':{'login':'ATLKR','id':65988341,'type':'User'},'ref':'refs/heads/'+guard.BRANCH,
            'before':'b'*40,'after':'a'*40,'created':False,'deleted':False,'forced':False,
            'commits':[{'id':'a'*40}],'head_commit':{'id':'a'*40,'message':guard.MARKER}}
        event_path=root/'event.json';event_path.write_text(json.dumps(event));env['GITHUB_EVENT_PATH']=str(event_path)
        source_files={'fixed.py':'d'*64};source=dict(head='a'*40,tree='c'*40,dirty=False,files=source_files)
        host=dict(processId=45,processMachine=0,nativeMachine=0xAA64,sessionId=1,windowsDirectory=r'C:\Windows',
            windowsVersion=[10,0,26100],imageOS='synthetic',imageVersion='synthetic',desktop='Default',windowStation='WinSta0',
            process={'createdFileTime':111})
        calls=[];seen_argv=[];budgets=[];hash_reads=[]
        class Poison:
            def __str__(self):raise AssertionError()
            def __repr__(self):raise AssertionError()
        class Owner:
            created=False
            def __init__(self,*args):
                self.cleanup_outcomes=[];self.argv=args[2];self.output=Path(self.argv[-1]);seen_argv.append(self.argv)
            def create_suspended(self):calls.append('create');self.created=True
            def assign(self):calls.append('assign')
            def identity(self):
                return dict(processId=999,createdFileTime=888,assignedBeforeResume=True,sourceFiles=source_files,
                    argv=Poison(),environment=Poison())
            def resume(self):
                calls.append('resume')
                if mode=='timeout':return
                context=real.validate_context(env,event,source,host,'nt',prepare_privacy=True,binding=m.control_binding(real,guard))
                (self.output/'32-observer-context.json').write_text(json.dumps({**context,'source':source,
                    'eventSha256':real.legacy.bounded_object(event_path)[1]}))
                row=m.empty_record();row.update(m.admit(guard,root,env,event,platform='nt'))
                row.update(recordKindCode=2,observerPid=999,observerBirth=888,observationPassed=True,
                    observationStatusCode=1,coreWindowObserved=False)
                m.write_record(self.output/m.CHILD,row)
            def wait(self,seconds):calls.append('wait');return mode!='timeout'
            def exit_code(self):return 0
            def descendants_empty(self):return True
            def accounting(self):return dict(querySucceeded=True,activeProcesses=0)
            def terminate_owned(self):calls.append('terminate')
            def close(self):calls.append('close')
        class Core:
            def __getattr__(self,name):return getattr(real,name)
            def Probe(self):return type('Host',(),{'identity':lambda self:copy.deepcopy(host)})()
            def Budget(self,*args,**kwargs):
                value=real.Budget(*args,**kwargs);budgets.append(value);return value
            def bound_hashes(self,binding):
                hash_reads.append(1)
                if mode=='late-final-hash' and len(hash_reads)>1:budgets[0].deadline=0
                return source_files
            def image_receipt(self,*args):return dict(peMachine=0xAA64,imageBytes=10,imageSha256='d'*64)
            def run_owned(self,*args,**kwargs):
                value=real.run_owned(*args,**kwargs)
                if mode=='after-owned-error':raise OSError()
                return value
            OwnedObserver=Owner
        core=Core()
        with mock.patch.object(guard,'verify_request_source',return_value=(10,55)):
            row=m.run_controller(core,guard,env,event,root,deadline=time.monotonic()+120,platform='nt')
        return row,calls,seen_argv,root
    def test_real_run_owned_gates_success_and_protocol_never_serializes_argv_or_environment(self):
        row,calls,argv,root=self.invoke()
        self.assertIs(row['preparationPassed'],True)
        self.assertEqual(calls,['create','assign','resume','wait','close'])
        self.assertEqual(argv[0][1:4],['-B',str(root/m.ENTRY),'--observer'])
        bound=json.loads(next(root.glob('writer-os-privacy-*/21-observer-bound.json')).read_text())
        self.assertNotIn('argv',bound);self.assertNotIn('environment',bound)
        self.assertEqual((bound['processId'],bound['createdFileTime']),(999,888))
    def test_real_owned_timeout_cannot_continue_with_zero_assumed_actions(self):
        row,calls,argv,root=self.invoke('timeout')
        self.assertIs(row['preparationPassed'],False);self.assertIsNone(row['closeRequests'])
        self.assertIs(row['timedOut'],True);self.assertIn('terminate',calls);self.assertEqual(calls[-1],'close')
    def test_post_custody_error_preserves_unknown_actions_instead_of_default_zero(self):
        try:row,calls,argv,root=self.invoke('after-owned-error')
        except Exception:self.fail('Post-custody failure lost the bounded numeric record')
        self.assertIs(row['preparationPassed'],False);self.assertIsNone(row['closeRequests'])
        self.assertEqual(calls[-1],'close');m.validate_record(row)


    def test_late_final_source_read_cannot_publish_preparation_success(self):
        row,calls,argv,root=self.invoke('late-final-hash')
        self.assertIs(row['preparationPassed'],False)
        self.assertEqual(calls[-1],'close');self.assertIs(row['naturalExit'],True)

class ObserverHandshakeTests(unittest.TestCase):
    setUp=PrivacyGateTests.setUp
    def invoke(self,mode='privacy'):
        guard=m.load_guard(ROOT);real=existing.m;probe=self.probe
        env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','RUNNER_ARCH':'ARM64',
            'GITHUB_JOB':'writer-server-observer','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_OWNER':'ATLKR',
            'GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341','GITHUB_TRIGGERING_ACTOR':'ATLKR',
            'GITHUB_EVENT_NAME':'push','GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':'refs/heads/'+guard.BRANCH,
            'GITHUB_WORKFLOW_REF':guard.WORKFLOW,'GITHUB_SHA':'a'*40,'GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_RUN_ID':'123'}
        event={'repository':{'full_name':'ATLKR/OpenGeul','id':1405493151,'private':False},
            'sender':{'login':'ATLKR','id':65988341,'type':'User'},'ref':'refs/heads/'+guard.BRANCH,
            'before':'b'*40,'after':'a'*40,'created':False,'deleted':False,'forced':False,
            'commits':[{'id':'a'*40}],'head_commit':{'id':'a'*40,'message':guard.MARKER}}
        output=self.session.evidence.path;event_path=Path(self.temp.name)/'event.json'
        event_path.write_text(json.dumps(event));env['GITHUB_EVENT_PATH']=str(event_path)
        source=dict(head='a'*40,tree='c'*40,dirty=False,files={'fixed.py':'d'*64})
        process=dict(processId=999,createdFileTime=888,sessionId=1,processMachine=0,nativeMachine=0xAA64,
            exitCode=259,imagePath=r'C:\Python\python.exe')
        host=dict(processId=999,processMachine=0,nativeMachine=0xAA64,sessionId=1,windowsDirectory=r'C:\Windows',
            windowsVersion=[10,0,26100],imageOS='synthetic',imageVersion='synthetic',desktop='Default',windowStation='WinSta0',process=process)
        probe.identity=lambda:copy.deepcopy(host)
        protocol=m.ProtocolEvidence(self.session.evidence.original,m.empty_record())
        context=real.validate_context(env,event,source,host,'nt',prepare_privacy=True,binding=m.control_binding(real,guard))
        protocol.write('10-controller',{**context,'host':host,'sourceFiles':source['files'],
            'eventSha256':real.legacy.bounded_object(event_path)[1]})
        protocol.write('21-observer-bound',dict(processId=999,createdFileTime=889 if mode=='bad-observer' else 888,
            assignedBeforeResume=True,sourceFiles=source['files']))
        if mode=='non-core':probe.text_value=lambda *args,**kwargs:'Synthetic.NonCoreClass'
        if mode=='unknown-core':
            old=probe.process_identity
            probe.process_identity=lambda *args:dict(old(*args),imagePath=r'C:\Other\WWAHost.exe')
        class Core:
            def __getattr__(self,name):return getattr(real,name)
            def Probe(self):return probe
            def bound_source(self,*args):
                return real.bound_source(*args) if mode=='generated-output' else copy.deepcopy(source)
            def bound_hashes(self,*args):return source['files']
        def git_read(args,budget):
            if args==['rev-parse','HEAD']:return source['head']
            if args==['rev-parse','HEAD^{tree}']:return source['tree']
            if args==['status','--porcelain=v1','--untracked-files=all','--ignored']:return '!! .work/'
            raise AssertionError()
        with mock.patch.object(guard,'verify_request_source',return_value=(10,55)), \
             mock.patch.object(real,'git_read',side_effect=git_read),mock.patch.object(real,'source_hashes',return_value=source['files']):
            row=m.run_observer(Core(),guard,env,event,ROOT,output,time.monotonic()+120,platform='nt')
        self.assertEqual(row,m.read_record(output/m.CHILD))
        return row,output
    def test_real_observer_source_host_and_self_identity_allow_one_original_close(self):
        row,output=self.invoke()
        self.assertIs(row['observationPassed'],True);self.assertEqual(row['closeRequests'],1)
        self.assertEqual((row['observerPid'],row['observerBirth']),(999,888))
        self.assertEqual(len(self.sent),1);self.assertIs(row['queryHandlesReleased'],True)
        for path in output.glob('*.json'):
            raw=path.read_text()
            self.assertNotIn(self.observed['foreground']['title'],raw)
            self.assertNotIn(self.observed['uia'][0]['nodes'][-1]['name'],raw)
            self.assertNotIn('"argv"',raw);self.assertNotIn('"environment"',raw)
    def test_real_observer_unknown_core_fails_before_title_uia_and_close(self):
        row,output=self.invoke('unknown-core')
        self.assertIs(row['observationPassed'],False);self.assertEqual((row['stageCode'],row['errorCode']),(3,1))
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0));self.assertEqual(row['closeRequests'],0)
    def test_real_observer_non_core_uses_no_privacy_title_or_uia(self):
        row,output=self.invoke('non-core')
        self.assertIs(row['observationPassed'],True);self.assertEqual(row['observationStatusCode'],1)
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))
    def test_original_observer_self_generation_mismatch_has_no_target_reads(self):
        row,output=self.invoke('bad-observer')
        self.assertIs(row['observationPassed'],False);self.assertEqual(row['errorCode'],1)
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))

    def test_actual_source_contract_still_rejects_existing_generated_work(self):
        row,output=self.invoke('generated-output')
        self.assertIs(row['observationPassed'],False)
        self.assertEqual(row['closeRequests'],0)
        self.assertEqual((self.title_reads,self.uia_reads,len(self.sent)),(0,0,0))


class SourceOrderingTests(unittest.TestCase):
    def test_public_output_is_created_only_after_both_original_source_boundaries(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);calls=[];guard=SimpleNamespace(_json=lambda *args:{})
            def controller(*args,**kwargs):
                self.assertFalse((root/'.work').exists())
                calls.append(1)
                return m.empty_record()
            with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'os',SimpleNamespace(name='nt',
                environ={'GITHUB_JOB':m.JOB,'GITHUB_EVENT_PATH':'synthetic'})), \
                mock.patch.object(m,'load_guard',return_value=guard),mock.patch.object(m,'load_core',return_value=object()), \
                mock.patch.object(m,'run_controller',side_effect=controller):
                self.assertEqual(m.main(['prepare']),1)
            self.assertEqual(calls,[1]);self.assertEqual(m.read_record(root/m.REPORT),m.empty_record())
