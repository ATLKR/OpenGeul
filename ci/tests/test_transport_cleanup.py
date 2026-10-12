"""Bounded same-run deletion: synthetic REST responses, no network or real deletes."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
PATH=Path(__file__).resolve().parents[1]/'transport_cleanup.py'
WORKERS=('windows-editor','windows-cli','windows-editor-arm64','windows-cli-arm64')
PREFIXES=('opengeul-wasm','opengeul-browser-inputs','opengeul-e2e-inputs','opengeul-windows-x64',
          'opengeul-editor-component','opengeul-cli-component','opengeul-e2e-inputs-arm64',
          'opengeul-windows-arm64','opengeul-editor-component-arm64','opengeul-cli-component-arm64','opengeul-native-signed-arm64')

class TransportCleanupTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.is_file(),'Missing success-only transport lifecycle implementation')
        spec=importlib.util.spec_from_file_location('transport_cleanup',PATH)
        self.m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.m;spec.loader.exec_module(self.m)
        self.env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'ATLKR/OpenGeul',
                  'GITHUB_RUN_ID':'55','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,'GITHUB_EVENT_NAME':'push',
                  'GITHUB_REF':'refs/heads/main','GITHUB_ACTOR':'ATLKR','CI_MODE':'full'}
        self.event={'repository':{'full_name':'ATLKR/OpenGeul','private':False}}
        self.context=self.m.context(self.env,self.event)
        self.needs={n:{'result':'success'} for n in (*self.m.GATES,*WORKERS,'build-arm64','msix-install-arm64','msix-native-arm64')}
        self.run={'id':55,'run_attempt':1,'head_sha':'a'*40,'event':'push','path':'.github/workflows/msix.yml',
                  'repository':self.event['repository'],'head_repository':self.event['repository']}
        self.artifacts=[self.artifact(i+1,p+'-55'+('-1' if p=='opengeul-native-signed-arm64' else '')) for i,p in enumerate(PREFIXES)]
        self.artifacts += [self.artifact(99,'virtual-print-windows-2025-55')]
    def artifact(self,id,name):
        return {'id':id,'name':name,'size_in_bytes':100,'expired':False,'workflow_run':{'id':55,'head_sha':'a'*40}}
    def listing(self,items=None):
        items=self.artifacts if items is None else items
        return {'total_count':len(items),'artifacts':items}
    def plan(self,items=None,run=None,needs=None):
        return self.m.plan(self.context,self.needs if needs is None else needs,self.run if run is None else run,self.listing(items))
    def api_fixture(self,calls,items=None,changed=None):
        items=self.artifacts if items is None else items
        def api(method,path):
            calls.append((method,path))
            if path.endswith('/runs/55'):return self.run
            if '?per_page' in path:return self.listing(items)
            if method=='GET':
                artifact=next(a for a in items if path.endswith('/'+str(a['id'])))
                return changed(artifact) if changed else artifact
            return None
        return api
    def test_successful_publication_removes_only_eleven_bounded_transport_files(self):
        self.assertEqual([a['id'] for a in self.plan()],list(range(1,12)))
    def test_signed_native_missing_or_changed_prevents_the_whole_cleanup_batch(self):
        self.assertIn('msix-native-arm64', self.m.GATES)
        self.assertEqual(len(self.plan()), 11)
        for change in ('missing','expired','oversized','old_head','old_run','old_attempt'):
            with self.subTest(change=change):
                items=copy.deepcopy(self.artifacts);candidate=next(a for a in items if a['name']=='opengeul-native-signed-arm64-55-1')
                if change=='missing': items.remove(candidate)
                elif change=='expired': candidate['expired']=True
                elif change=='oversized': candidate['size_in_bytes']=97*1024**2+1
                elif change=='old_head': candidate['workflow_run']['head_sha']='b'*40
                elif change=='old_run': candidate['workflow_run']['id']=54
                else: candidate['name']='opengeul-native-signed-arm64-55-2'
                calls=[]
                with self.assertRaises(ValueError): self.m.execute(self.context,self.needs,self.api_fixture(calls,items))
                self.assertFalse(any(method=='DELETE' for method,path in calls))

    def test_windows_producer_results_are_required_before_any_api_call(self):
        for name in WORKERS:
            for state in ('failure','cancelled','skipped',None):
                with self.subTest(name=name,state=state):
                    needs=copy.deepcopy(self.needs);needs[name]['result']=state
                    result=self.m.execute(self.context,needs,lambda *a:self.fail('Failed producer must not call API'))
                    self.assertEqual(result['deleted'],[])
            with self.subTest(name=name,state='missing'):
                needs={k:v for k,v in self.needs.items() if k!=name}
                with self.assertRaises(ValueError):
                    self.m.execute(self.context,needs,lambda *a:self.fail('Missing producer must not call API'))
    def test_missing_component_prevents_the_whole_batch_from_being_deleted(self):
        for name in ('opengeul-editor-component-55','opengeul-cli-component-55','opengeul-editor-component-arm64-55','opengeul-cli-component-arm64-55'):
            with self.subTest(name=name):
                calls=[];items=[a for a in self.artifacts if a['name']!=name]
                with self.assertRaises(ValueError):
                    self.m.execute(self.context,self.needs,self.api_fixture(calls,items))
                self.assertFalse(any(m=='DELETE' for m,p in calls))
    def test_invalid_component_prevents_deleting_valid_earlier_transports(self):
        for name in ('opengeul-editor-component-55','opengeul-cli-component-55','opengeul-editor-component-arm64-55','opengeul-cli-component-arm64-55'):
            for field,value in (('workflow_run',{'id':56,'head_sha':'a'*40}),
                                ('workflow_run',{'id':55,'head_sha':'b'*40}),('expired',True),
                                ('size_in_bytes',1024**3)):
                with self.subTest(name=name,field=field,value=value):
                    calls=[];items=copy.deepcopy(self.artifacts)
                    next(a for a in items if a['name']==name)[field]=value
                    with self.assertRaises(ValueError):
                        self.m.execute(self.context,self.needs,self.api_fixture(calls,items))
                    self.assertFalse(any(m=='DELETE' for m,p in calls))
    def test_last_component_revalidation_failure_prevents_all_deletes(self):
        calls=[]
        def changed(artifact):
            if artifact['name']=='opengeul-cli-component-55':
                return {**artifact,'digest':'sha256:changed'}
            return artifact
        with self.assertRaises(ValueError):
            self.m.execute(self.context,self.needs,self.api_fixture(calls,changed=changed))
        self.assertTrue(any(p.endswith('/artifacts/5') for m,p in calls if m=='GET'))
        self.assertTrue(any(p.endswith('/artifacts/6') for m,p in calls if m=='GET'))
        self.assertFalse(any(m=='DELETE' for m,p in calls))
    def test_last_arm_component_revalidation_failure_prevents_all_deletes(self):
        calls=[]
        def changed(artifact):
            return {**artifact,'digest':'sha256:changed'} if artifact['name']=='opengeul-cli-component-arm64-55' else artifact
        with self.assertRaises(ValueError):
            self.m.execute(self.context,self.needs,self.api_fixture(calls,changed=changed))
        self.assertTrue(any(p.endswith('/artifacts/10') for m,p in calls if m=='GET'))
        self.assertFalse(any(m=='DELETE' for m,p in calls))
    def test_ambiguous_component_identity_prevents_all_deletes(self):
        component=next(a for a in self.artifacts if a['name']=='opengeul-cli-component-55')
        for duplicate in ({**component,'id':88},{**component,'name':'opengeul-editor-component-55'}):
            with self.subTest(duplicate=duplicate):
                calls=[]
                with self.assertRaises(ValueError):
                    self.m.execute(self.context,self.needs,self.api_fixture(calls,self.artifacts+[duplicate]))
                self.assertFalse(any(m=='DELETE' for m,p in calls))
    def test_component_size_caps_include_only_the_existing_archive_overhead(self):
        for name,cap in (('opengeul-editor-component-55',64),('opengeul-cli-component-55',32),
                         ('opengeul-editor-component-arm64-55',64),('opengeul-cli-component-arm64-55',32)):
            with self.subTest(name=name):
                artifact=self.artifact(88,name);artifact['size_in_bytes']=(cap+1)*1024**2
                self.m.validate_artifact(self.context,artifact)
                artifact['size_in_bytes']+=1
                with self.assertRaises(ValueError):self.m.validate_artifact(self.context,artifact)
    def test_evidence_and_unrelated_names_are_never_deleted(self):
        self.artifacts.extend([self.artifact(90,'custom-result'),self.artifact(91,'opengeul-wasm-54')])
        self.assertEqual(len(self.plan()),11)
    def test_failure_of_each_gate_preserves_all_artifacts(self):
        for name in self.needs:
            with self.subTest(name=name):
                needs=copy.deepcopy(self.needs);needs[name]['result']='failure'
                self.assertEqual(self.plan(needs=needs),[])
    def test_separate_arm64_native_and_print_failures_never_call_delete(self):
        for name in ('native-e2e-arm64','virtual-print-arm64','msix-native-arm64'):
            self.assertIn(name,self.m.GATES)
            for status in ('failure','skipped','cancelled'):
                with self.subTest(job=name,status=status):
                    needs=copy.deepcopy(self.needs);needs[name]['result']=status;calls=[]
                    self.m.execute(self.context,needs,self.api_fixture(calls))
                    self.assertEqual(calls,[])
    def test_cancelled_pending_or_skipped_required_gate_preserves(self):
        for status in ('cancelled','queued','in_progress','skipped',None):
            needs=copy.deepcopy(self.needs);needs['virtual-print']['result']=status
            self.assertEqual(self.plan(needs=needs),[])
    def test_missing_or_extra_gate_is_not_success(self):
        for needs in ({k:v for k,v in self.needs.items() if k!='virtual-print'}, {**self.needs,'new':{'result':'success'}}):
            with self.assertRaises(ValueError):self.plan(needs=needs)
    def test_pr_keeps_candidate_package(self):
        self.context.update(event='pull_request',ref='refs/pull/6/merge');self.run['event']='pull_request'
        self.needs['release']['result']='skipped'
        self.assertEqual([a['id'] for a in self.plan()],[1,2,3,5,6,7,9,10,11])
    def test_main_release_skipped_is_not_a_cleanup_success(self):
        self.needs['release']['result']='skipped';self.assertEqual(self.plan(),[])
    def test_scheduled_full_run_keeps_unpublished_package(self):
        self.context['event']='schedule';self.run['event']='schedule';self.needs['release']['result']='skipped'
        self.assertEqual(len(self.plan()),9)
    def test_engine_removes_only_browser_transport(self):
        self.context.update(event='workflow_dispatch',mode='engine');self.run['event']='workflow_dispatch'
        for name in (*WORKERS,'build','build-arm64','native-e2e','native-e2e-arm64','virtual-print','virtual-print-arm64','msix-install','msix-install-arm64','msix-native-arm64','release'):self.needs[name]['result']='skipped'
        self.assertEqual([a['id'] for a in self.plan()],[2])
    def test_engine_cannot_ignore_failed_windows_job(self):
        self.context.update(event='workflow_dispatch',mode='engine');self.run['event']='workflow_dispatch'
        for name in (*WORKERS,'build','build-arm64','native-e2e','native-e2e-arm64','virtual-print','virtual-print-arm64','msix-install','msix-install-arm64','msix-native-arm64','release'):self.needs[name]['result']='skipped'
        for name in (*WORKERS,'build','build-arm64','msix-install-arm64'):
            with self.subTest(name=name):
                needs=copy.deepcopy(self.needs);needs[name]['result']='failure'
                self.assertEqual(self.plan(needs=needs),[])
    def test_checks_stage_creates_no_cleanup(self):
        self.context.update(event='workflow_dispatch',mode='checks');self.run['event']='workflow_dispatch'
        self.assertEqual(self.plan(),[])
    def test_private_foreign_and_unknown_visibility_are_rejected(self):
        for change in ({'private':True},{'private':None},{'full_name':'other/repo'}):
            event=copy.deepcopy(self.event);event['repository'].update(change)
            with self.assertRaises(ValueError):self.m.context(self.env,event)
    def test_workstations_reruns_and_nonstandard_hosts_are_rejected(self):
        for key,value in [('GITHUB_ACTIONS','false'),('RUNNER_ENVIRONMENT','self-hosted'),('GITHUB_RUN_ATTEMPT','2')]:
            with self.assertRaises(ValueError):self.m.context({**self.env,key:value},self.event)
    def test_fork_and_dependabot_cannot_receive_cleanup_authority(self):
        event=copy.deepcopy(self.event);event['pull_request']={'head':{'sha':'b'*40,'repo':{'full_name':'fork/OpenGeul'}}}
        with self.assertRaises(ValueError):self.m.context({**self.env,'GITHUB_EVENT_NAME':'pull_request'},event)
        with self.assertRaises(ValueError):self.m.context({**self.env,'GITHUB_ACTOR':'dependabot[bot]'},self.event)
    def test_pr_head_binding_uses_head_not_synthetic_merge_sha(self):
        event=copy.deepcopy(self.event);event['pull_request']={'head':{'sha':'b'*40,'repo':self.event['repository']}}
        ctx=self.m.context({**self.env,'GITHUB_EVENT_NAME':'pull_request'},event);self.assertEqual(ctx['sha'],'b'*40)
    def test_pull_request_cannot_select_lighter_mode(self):
        event=copy.deepcopy(self.event);event['inputs']={'mode':'engine'};event['pull_request']={'head':{'sha':'b'*40,'repo':self.event['repository']}}
        with self.assertRaises(ValueError):self.m.context({**self.env,'GITHUB_EVENT_NAME':'pull_request','CI_MODE':'engine'},event)
    def test_malformed_run_identifier_cannot_be_an_api_path(self):
        for value in ('0','55/../../releases','55?x=y','-1',''):
            with self.assertRaises(ValueError):self.m.context({**self.env,'GITHUB_RUN_ID':value},self.event)
    def test_wrong_run_sha_attempt_or_workflow_rejected(self):
        for key,value in [('id',56),('head_sha','b'*40),('run_attempt',2),('path','.github/workflows/other.yml'),('event','workflow_dispatch')]:
            with self.assertRaises(ValueError):self.plan(run={**self.run,key:value})
    def test_foreign_run_repository_rejected(self):
        for key in ('repository','head_repository'):
            with self.assertRaises(ValueError):self.plan(run={**self.run,key:{'full_name':'other/repo','private':False}})
    def test_incomplete_or_oversized_listing_is_never_partially_deleted(self):
        for total in (0,99,101):
            with self.assertRaises(ValueError):self.m.plan(self.context,self.needs,self.run,{'total_count':total,'artifacts':self.artifacts})
    def test_missing_required_transport_preserves_all(self):
        with self.assertRaises(ValueError):self.plan(items=self.artifacts[1:])
    def test_duplicate_names_or_identifiers_rejected(self):
        for item in ({**self.artifacts[0],'id':88},{**self.artifacts[0],'name':'opengeul-browser-inputs-55'}):
            with self.assertRaises(ValueError):self.plan(items=self.artifacts+[item])
    def test_wrong_artifact_owner_or_sha_rejected(self):
        for owner in ({'id':56,'head_sha':'a'*40},{'id':55,'head_sha':'b'*40},{}):
            items=copy.deepcopy(self.artifacts);items[0]['workflow_run']=owner
            with self.assertRaises(ValueError):self.plan(items=items)
    def test_expired_invalid_id_or_oversized_artifacts_rejected(self):
        for key,value in [('expired',True),('id',False),('size_in_bytes',-1),('size_in_bytes',1024**3)]:
            items=copy.deepcopy(self.artifacts);items[0][key]=value
            with self.assertRaises(ValueError):self.plan(items=items)
    def test_revalidation_failure_causes_zero_deletes(self):
        calls=[]
        def api(method,path):
            calls.append((method,path))
            if path.endswith('/runs/55'):return self.run
            if '?per_page' in path:return self.listing()
            if method=='GET':return {**self.artifacts[0],'workflow_run':{'id':777,'head_sha':'a'*40}}
            self.fail('Deletion occurred before every selected artifact was revalidated')
        with self.assertRaises(ValueError):self.m.execute(self.context,self.needs,api)
        self.assertFalse(any(m=='DELETE' for m,p in calls))
    def test_only_api_returned_ids_are_deleted_after_all_rechecks(self):
        calls=[]
        def api(method,path):
            calls.append((method,path))
            if path.endswith('/runs/55'):return self.run
            if '?per_page' in path:return self.listing()
            if method=='GET':return next(a for a in self.artifacts if path.endswith('/'+str(a['id'])))
            self.assertGreaterEqual(sum(m=='GET' for m,p in calls),13)
            return None
        result=self.m.execute(self.context,self.needs,api)
        self.assertEqual(result['deletedBytes'],1100)
        self.assertEqual([p.rsplit('/',1)[1] for m,p in calls if m=='DELETE'],[str(i) for i in range(1,12)])
    def test_failed_run_does_not_even_call_api(self):
        self.needs['virtual-print']['result']='failure'
        self.assertEqual(self.m.execute(self.context,self.needs,lambda *a:self.fail('API should not be called'))['deletedBytes'],0)

if __name__=='__main__':unittest.main()
