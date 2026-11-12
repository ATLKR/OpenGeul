import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(REPO))
REF='refs/heads/work/opengeul-office-package-context-sdk'

def environment(arch='x64'):
    head='a'*40
    return {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_REPOSITORY_ID':'1405493151',
      'GITHUB_REPOSITORY_OWNER':'ATLKR','GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341','GITHUB_TRIGGERING_ACTOR':'ATLKR',
      'GITHUB_EVENT_NAME':'push','GITHUB_REF':REF,'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'123',
      'GITHUB_SHA':head,'GITHUB_WORKFLOW_SHA':head,
      'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/office-suite.yml@'+REF,
      'GITHUB_JOB':'packaged-context-sdk','SDK_REPOSITORY_PRIVATE':'false','SDK_REPOSITORY_FORK':'false',
      'SDK_MATRIX_RUNNER':'windows-2025' if arch=='x64' else 'windows-11-arm',
      'RUNNER_OS':'Windows','RUNNER_ARCH':'X64' if arch=='x64' else 'ARM64'}

def condition(text,**overrides):
    values={'repository':'ATLKR/OpenGeul','repository_id':'1405493151','repository_owner':'ATLKR','actor':'ATLKR',
      'actor_id':'65988341','triggering_actor':'ATLKR','event_name':'push','ref':REF,'run_attempt':1,
      'private':False,'fork':False,**overrides}
    names={name:'github.'+name for name in values if name not in ('private','fork')}
    names.update(private='github.event.repository.private',fork='github.event.repository.fork')
    text=text.strip().removeprefix('${{').removesuffix('}}').strip()
    for name,source in sorted(names.items(),key=lambda p:len(p[1]),reverse=True):text=text.replace(source,name)
    text=text.replace('&&',' and ').replace('||',' or ').replace('false','False').replace('true','True')
    tree=ast.parse(text,mode='eval')
    allowed=(ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)
    if any(not isinstance(n,allowed) for n in ast.walk(tree)):raise AssertionError('unreviewed selector grammar')
    return bool(eval(compile(tree,'closed-job-selector','eval'),{'__builtins__':{}},values))

def success_fixture():
    value={'schemaVersion':1,'kind':'packaged-context-sdk-negative-gate','stage':7,'failureCode':0,
      'architectureCode':0x8664,'approvedCodeManifestSha256':'1'*64,'phaseResults':[],
      'compilerVersion':'14.44.35207','installationVersion':'17.14.19','sdkVersion':'10.0.26100.0',
      'startedAt':0.,'deadline':180.,'finishedAt':8.,'vswhereSha256':'2'*64,'devcmdSha256':'3'*64}
    for name in ('sdkGatePassed','actualWindowsExecuted','nativeSdkCompiled','nativeLinked','negativeSmokePassed','frozenV2Preserved','workRootCreated','codeApprovalVerified'):value[name]=True
    for name in ('actualPackageObservation','qualification','canService','originalHelperHandleKnown','packagedHelperLauncherImplemented','watchdogVerified','synchronousOsCallPreemptionVerified','osImplicitEffectsKnown','pure40TestsRerun','lease6TestsRerun'):value[name]=False
    for name in ('controller','commandProcessor','compiler','linker','portObject','smokeObject','executable'):
        value[name]={'machine':0x8664,'bytes':512,'sha256':'4'*64}
    for name,count in (('sdkInputs',16),('compileInputs',4)):
        value[name]=[{'slot':i,'bytes':100,'sha256':'5'*64} for i in range(1,count+1)]
    for i in range(5):
        value['phaseResults'].append({'startedAt':float(i),'deadline':float(i+30),'finishedAt':float(i+1),
          'completed':True,'cleanupProved':True,'forcedCleanup':False,'rootExitObserved':True,'jobEmptyObserved':True,
          'identityRechecked':True,'exitCode':0,'pid':i+1,'creation':i+10,'failureCode':0,'cancelled':False,'handlesClosed':4})
    return value

class CiContracts(unittest.TestCase):
    def api(self):
        self.assertTrue((ROOT/'ci_entry.py').is_file(),'fixed CI entry required')
        import ci_entry
        return ci_entry
    def test_context_requires_exact_public_owner_push_ref_attempt_and_source(self):
        m=self.api()
        for arch in ('x64','arm64'):self.assertEqual(m.require_context(environment(arch),arch)['sourceCommit'],'a'*40)
        cases=[('GITHUB_REPOSITORY','OTHER/OpenGeul'),('GITHUB_REPOSITORY_ID','1'),('GITHUB_REPOSITORY_OWNER','OTHER'),
          ('GITHUB_ACTOR','OTHER'),('GITHUB_ACTOR_ID','1'),('GITHUB_TRIGGERING_ACTOR','OTHER'),('GITHUB_ACTIONS','false'),
          ('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/heads/main'),('GITHUB_RUN_ATTEMPT','2'),
          ('GITHUB_SHA','f'*39),('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_JOB','windows-suite'),('SDK_REPOSITORY_PRIVATE','true'),
          ('SDK_REPOSITORY_FORK','true'),('SDK_MATRIX_RUNNER','windows-2022'),('RUNNER_ARCH','ARM64'),('RUNNER_OS','Linux')]
        for index,(key,value) in enumerate(cases):
            with self.subTest(case=index),self.assertRaises(m.CiFailure):m.require_context({**environment(),key:value},'x64')
    def test_checkout_head_is_exact_detached_commit_without_git_process(self):
        m=self.api();binding=m.require_context(environment(),'x64')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'.git').mkdir();p=root/'.git/HEAD';p.write_text('a'*40+'\n')
            self.assertTrue(m.check_checkout(root,binding))
            for value in ('b'*40+'\n','ref: refs/heads/main\n'):
                p.write_text(value)
                with self.assertRaises(m.CiFailure):m.check_checkout(root,binding)
    def test_outer_envelope_does_not_extend_compiler_child_deadline(self):
        m=self.api();from supervisor import Runner,child_environment
        from test_supervisor import Clock,KernelPort
        c=Clock();p=KernelPort(c);env=child_environment(r'C:\Windows',r'C:\Program Files',r'C:\Program Files (x86)',r'C:\owned')
        args=[r'C:\Windows\System32\cmd.exe','/d','/c','phase.cmd']
        r=Runner(p,clock=c,pause=c.pause).run(args,r'C:\owned',env,31.)
        self.assertFalse(r['completed']);self.assertEqual(p.launches,0)
        r=m.EnvelopeRunner(p,clock=c,pause=c.pause).run(args,r'C:\owned',env,180.)
        self.assertTrue(r['completed'])
        long_args=[args[0]]+['fixed']*20
        r=m.EnvelopeRunner(p,clock=c,pause=c.pause).run(long_args,r'C:\owned',env,180.)
        self.assertTrue(r['completed'])
    def test_gate_uses_the_original_outer_window_without_restart(self):
        self.api();import run_sdk_gate
        self.assertEqual(run_sdk_gate.overall_window(100.,90.,270.),(90.,270.))
        self.assertEqual(run_sdk_gate.overall_window(100.,None,None),(100.,280.))
        for args in ((100.,90.,271.),(100.,101.,281.),(300.,90.,270.)):
            with self.assertRaises(run_sdk_gate.GateFailure):run_sdk_gate.overall_window(*args)
    def test_numeric_artifact_rejects_unknown_raw_fields_and_true_authority(self):
        m=self.api()
        for value in ({'rawOutput':'SYNTHETIC'},{'qualification':True},{'canService':True}):
            with self.assertRaises(m.CiFailure):m.validate_sdk_report(value,'x64','1'*64,180.)
    def test_missing_sdk_report_stays_unknown_and_never_becomes_pass(self):
        m=self.api();binding=m.require_context(environment(),'x64')
        result=m.public_report(binding,None,None,failure=1)
        self.assertFalse(result['sdkGatePassed']);self.assertFalse(result['sdkReportKnown'])
        self.assertIsNone(result['sdkStage']);self.assertFalse(result['qualification']);self.assertFalse(result['canService'])
    def test_success_without_actual_pe_coff_and_source_input_records_is_rejected(self):
        m=self.api()
        value={'schemaVersion':1,'kind':'packaged-context-sdk-negative-gate','stage':7,'failureCode':0,
          'architectureCode':0x8664,'approvedCodeManifestSha256':'1'*64,'phaseResults':[]}
        for name in ('sdkGatePassed','actualWindowsExecuted','nativeSdkCompiled','nativeLinked','negativeSmokePassed','frozenV2Preserved','workRootCreated','codeApprovalVerified'):value[name]=True
        for name in ('actualPackageObservation','qualification','canService','originalHelperHandleKnown','packagedHelperLauncherImplemented','watchdogVerified','synchronousOsCallPreemptionVerified','osImplicitEffectsKnown','pure40TestsRerun','lease6TestsRerun'):value[name]=False
        for index in range(5):
            value['phaseResults'].append({'startedAt':float(index),'deadline':float(index+30),'finishedAt':float(index+1),
              'completed':True,'cleanupProved':True,'forcedCleanup':False,'rootExitObserved':True,'jobEmptyObserved':True,
              'identityRechecked':True,'exitCode':0,'pid':index+1,'creation':index+10,'failureCode':0,'cancelled':False,'handlesClosed':4})
        with self.assertRaises(m.CiFailure):m.validate_sdk_report(value,'x64','1'*64,180.)
    def test_complete_data_contract_is_projected_without_raw_paths_or_authority(self):
        m=self.api();raw=success_fixture();inputs=copy.deepcopy(raw['compileInputs'])
        self.assertIs(m.validate_sdk_report(raw,'x64','1'*64,180.,inputs),raw)
        outer={'completed':True,'cleanupProved':True,'forcedCleanup':False,'exitCode':0}
        report=m.public_report(m.require_context(environment(),'x64'),outer,raw)
        self.assertTrue(report['sdkGatePassed']);self.assertFalse(report['qualification']);self.assertFalse(report['canService'])
        self.assertEqual(set(report['compiledEvidence']),{'portObject','smokeObject','executable','compiler','linker'})
    def test_changed_source_input_architecture_identity_or_authority_cannot_pass(self):
        m=self.api();base=success_fixture();inputs=copy.deepcopy(base['compileInputs'])
        variants=[]
        for name in ('qualification','canService','actualPackageObservation'):
            v=copy.deepcopy(base);v[name]=True;variants.append(v)
        v=copy.deepcopy(base);v['compileInputs'][0]['sha256']='6'*64;variants.append(v)
        v=copy.deepcopy(base);v['portObject']['machine']=0xaa64;variants.append(v)
        v=copy.deepcopy(base);v['phaseResults'][1]['pid']=1;v['phaseResults'][1]['creation']=10;variants.append(v)
        v=copy.deepcopy(base);v['cancelled']='SYNTHETIC';variants.append(v)
        for index,value in enumerate(variants):
            with self.subTest(case=index),self.assertRaises(m.CiFailure):m.validate_sdk_report(value,'x64','1'*64,180.,inputs)
    def test_preexisting_public_directory_is_preserved_and_not_adopted(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=m.create_public_directory(root,'windows-2025');marker=p/'preserved';marker.write_bytes(b'synthetic')
            with self.assertRaises(m.CiFailure):m.create_public_directory(root,'windows-2025')
            self.assertEqual(marker.read_bytes(),b'synthetic')

class WorkflowContracts(unittest.TestCase):
    def workflows(self):
        old=yaml.safe_load((ROOT/'tests/fixtures/office-suite.before.yml').read_bytes())
        new=yaml.safe_load((REPO/'.github/workflows/office-suite.yml').read_bytes())
        self.assertIn('packaged-context-sdk',new['jobs'],'new diagnostic job required')
        return old,new
    def test_only_exact_diag_push_ref_is_added_and_writer_job_is_unchanged(self):
        old,new=self.workflows()
        self.assertEqual(new['on']['push']['branches'],old['on']['push']['branches']+[REF.removeprefix('refs/heads/')])
        self.assertEqual(new['on']['workflow_dispatch'],old['on']['workflow_dispatch'])
        self.assertEqual(new['jobs']['writer-server-observer'],old['jobs']['writer-server-observer'])
        self.assertEqual(new['permissions'],old['permissions']);self.assertEqual(new['env'],old['env'])
    def test_normal_job_body_preserved_and_old_refs_keep_identical_behavior(self):
        old,new=self.workflows();a=copy.deepcopy(old['jobs']['windows-suite']);b=copy.deepcopy(new['jobs']['windows-suite'])
        ai=a.pop('if');bi=b.pop('if');self.assertEqual(a,b)
        self.assertFalse(condition(bi,ref=REF))
        for ref in ('refs/heads/work/opengeul-office-suite','refs/heads/work/opengeul-office-arm64',
                    'refs/heads/work/opengeul-office-native-writer-observer','refs/heads/main'):
            for private in (False,True):self.assertEqual(condition(ai,ref=ref,private=private),condition(bi,ref=ref,private=private))
    def test_exact_job_selector_rejects_foreign_private_fork_manual_pr_and_rerun(self):
        old,new=self.workflows();selector=new['jobs']['packaged-context-sdk']['if']
        self.assertTrue(condition(selector))
        for change in ({'repository':'OTHER/OpenGeul'},{'repository_id':'1'},{'repository_owner':'OTHER'},{'actor':'OTHER'},
          {'actor_id':'1'},{'triggering_actor':'OTHER'},{'private':True},{'fork':True},{'event_name':'workflow_dispatch'},
          {'event_name':'pull_request'},{'run_attempt':2},{'ref':'refs/heads/main'}):
            self.assertFalse(condition(selector,**change))
    def test_existing_policy_accepts_static_runner_matrix_and_no_failure_suppression(self):
        old,new=self.workflows();spec=importlib.util.spec_from_file_location('sdk_ci_policy',REPO/'ci/policy.py')
        policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
        self.assertTrue(policy.audit(new,workflow_path='.github/workflows/office-suite.yml'))
        job=new['jobs']['packaged-context-sdk']
        self.assertEqual(job['strategy']['matrix'],{'os':['windows-2025','windows-11-arm']})
        self.assertFalse(job.get('continue-on-error',False))
        self.assertTrue(all(not step.get('continue-on-error',False) for step in job['steps']))
    def test_artifact_is_one_fixed_numeric_file_and_never_executable_or_private_tree(self):
        old,new=self.workflows();job=new['jobs']['packaged-context-sdk']
        uploads=[s for s in job['steps'] if s.get('uses','').startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads),1)
        self.assertEqual(uploads[0]['with']['path'],'.work/packaged-context-sdk-public/${{ matrix.os }}/report.numeric.json')
        self.assertEqual(uploads[0]['with']['retention-days'],1)
