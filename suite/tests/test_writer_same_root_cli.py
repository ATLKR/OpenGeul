"""Explicit same-root diagnostic selection; no actual Windows/COM calls."""
from pathlib import Path
import copy,importlib.util,json,os,sys,tempfile,unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
E2E=Path(__file__).resolve().parents[1]/'e2e';sys.path.insert(0,str(E2E))
import writer_os_accessibility as probe
import writer_os_summary
import korean_ui_smoke as kui
spec=importlib.util.spec_from_file_location('writer_cli_public_abi',Path(__file__).with_name('test_writer_os_accessibility.py'));f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
spec=importlib.util.spec_from_file_location('writer_cli_gate',Path(__file__).resolve().parents[2]/'e2e/native31_suite_prepare.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class WriterSameRootCliTests(unittest.TestCase):
 def context(self,architecture='arm64'):
  sha='a'*40
  env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Windows',RUNNER_ARCH='ARM64'if architecture=='arm64'else'X64',GITHUB_REPOSITORY='ATLKR/OpenGeul',GITHUB_EVENT_NAME='push',GITHUB_JOB='windows-suite',GITHUB_REF=gate.BRANCH,GITHUB_WORKFLOW_REF=gate.WORKFLOW,GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='ATLKR',GITHUB_ACTOR_ID='65988341',GITHUB_SHA=sha,GITHUB_WORKFLOW_SHA=sha,GITHUB_RUN_ID='123')
  event=dict(repository=dict(full_name='ATLKR/OpenGeul',private=False,id=123),sender=dict(login='ATLKR',id=65988341,type='User'),ref=gate.BRANCH,deleted=False,after=sha)
  return env,event
 def request(self,suite,architecture='arm64',*,event=None,env=None):
  helper=getattr(kui,'_admit_writer_same_root',None);self.assertTrue(callable(helper),'Existing source context gate must precede launch')
  base_env,base_event=self.context(architecture);env=base_env if env is None else env;event=base_event if event is None else event
  with patch.object(gate,'read_event',return_value=event),patch.object(kui,'_writer_context_module',return_value=gate),patch.object(kui,'os',NS(name='nt',environ=env)):
   return helper(suite,architecture)
 def test_real_existing_context_gate_accepts_each_literal_architecture(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t)
   for arch in('arm64','x64'):
    (root/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1,architecture=arch)))
    binding=self.request(root,arch);self.assertTrue(binding['architecture']==arch and binding['runAttempt']=='1')
 def test_wrong_context_or_inventory_never_reaches_a_launch(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);(root/'suite-inventory.json').write_text('{"schemaVersion":1,"architecture":"arm64"}')
   env,event=self.context()
   bads=[dict(env,**{k:v})for k,v in(('GITHUB_RUN_ATTEMPT','2'),('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_ACTOR','other'),('GITHUB_REF','refs/heads/main'),('GITHUB_SHA','b'*40))]
   for bad in bads:
    with self.assertRaises(ValueError):self.request(root,env=bad)
   with self.assertRaises(ValueError):self.request(root,event=dict(event,after='b'*40))
   with self.assertRaises(ValueError):self.request(root,'x64')
 def main(self,root,flag=True,modules=None,extra=()):
  suite=root/'suite';fixtures=root/'fixtures';suite.mkdir();fixtures.mkdir();output=root/'out'
  argv=['fixed-synthetic','--suite',str(suite),'--fixtures',str(fixtures),'--output',str(output)]
  if flag:argv+=['--writer-same-root-diagnostic','arm64']
  if modules:argv+=['--modules',*modules]
  argv+=list(extra);seen=[]
  def run(*a,**kw):seen.append(kw);return dict(success=False)
  with patch.object(sys,'argv',argv),patch.object(kui,'os',NS(name='nt')),patch.object(kui,'run_modules',run):
   try:code=kui.main()
   except SystemExit:self.fail('Explicit public Writer diagnostic option must exist')
  return code,seen,output
 def test_public_optin_passes_bounded_selection_only_after_context_gate(self):
  events=[]
  with tempfile.TemporaryDirectory()as t,patch.object(kui,'_admit_writer_same_root',side_effect=lambda *a:events.append('admitted')):
   code,seen,_=self.main(Path(t));self.assertTrue(code==1 and events==['admitted'] and seen==[dict(probe_only=False,writer_regular_capture=True,writer_same_root_diagnostic=True)])
 def test_default_cli_preserves_original_call_shape_and_never_queries_context(self):
  with tempfile.TemporaryDirectory()as t,patch.object(kui,'_admit_writer_same_root',side_effect=AssertionError('No default context query')):
   code,seen,_=self.main(Path(t),False);self.assertTrue(code==1 and seen==[dict(probe_only=False)])
 def test_denied_context_precedes_output_creation_and_cohort_launch(self):
  helper=getattr(kui,'_admit_writer_same_root',None);self.assertTrue(callable(helper),'Admission seam must exist')
  with tempfile.TemporaryDirectory()as t,patch.object(kui,'_admit_writer_same_root',side_effect=ValueError('fixed denial')):
   root=Path(t)
   with self.assertRaises(ValueError):self.main(root)
   self.assertTrue(not(root/'out').exists())
 def test_nonwriter_or_probe_modes_cannot_request_extra_diagnostic(self):
  helper=getattr(kui,'_admit_writer_same_root',None);self.assertTrue(callable(helper),'Admission seam must exist')
  for modules,extra in((['calc'],()),(['writer'],('--probe-only',))):
   with tempfile.TemporaryDirectory()as t,patch.object(kui,'_admit_writer_same_root',side_effect=AssertionError('No wrong-mode admission')):
    with self.assertRaises(ValueError):self.main(Path(t),modules=modules,extra=extra)
 def test_hidden_child_overlong_deadline_is_rejected_before_uia_or_com(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);args=['fixed-synthetic','--writer-same-root-after-failure','--writer-msaa','--capture-child','123','--office-pid','200','--snapshot',str(root/'uia.json'),'--writer-office-creation-time','300','--writer-office-image',f.REQUEST['expectedImage'],'--writer-primary-checkpoint',str(root/'p.json'),'--writer-msaa-deadline','3601']
   seen=[]
   with patch.object(sys,'argv',args),patch.object(kui,'os',NS(name='nt')),patch.object(kui.time,'monotonic',lambda:1.),patch.object(kui,'capture_controls',side_effect=lambda*a:(seen.append(1)or dict(controlCount=0))),patch.object(kui.writer_access,'observe',side_effect=AssertionError('No overlong COM')):
    with self.assertRaises(ValueError):kui.main()
   self.assertTrue(not seen and not(root/'uia.json').exists())
 def test_known_diagnostic_cannot_certify_original_failure_or_aggregate(self):
  spec=importlib.util.spec_from_file_location('writer_cli_same_root',Path(__file__).with_name('test_writer_same_root_diagnostic.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);case=m.SameRootTests('runTest');case.setUp()
  with tempfile.TemporaryDirectory()as t:
   value=case.run_probe(Path(t)/'primary.json');self.assertTrue(value['postFailureDiagnostic']['known']==1 and value['verified']==0)
   with self.assertRaises(ValueError):probe.validate(dict(value,verified=1,stageCode=12),f.REQUEST)
   def run(*a,**kw):return dict(module=a[3],success=False,koreanUiVerified=True,tabbedUiVerified=True,writerOsAccessibility=value)
   with patch.object(kui,'run_case',run),patch.object(kui.native,'write_result',lambda*a:None):report=kui.run_modules(Path(t),Path(t),Path(t),['writer'],writer_regular_capture=True,writer_same_root_diagnostic=True)
   self.assertTrue(report['success']is False and report['tests'][0]['success']is False)
 def test_successful_original_focus_never_runs_postfailure_queries(self):
  raw=f.RawFixture();owner=f.Owner(f.REQUEST)
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';value=probe.observe(f.REQUEST,owner_factory=lambda r:owner,backend_factory=lambda g,r:probe.RawComBackend(g,r,bindings=raw.bindings),primary_checkpoint=p,post_failure_diagnostic=True,gui_deadline=5.,clock=lambda:1.)
   self.assertTrue(value['verified']==1 and 'postFailureDiagnostic'not in value and not p.exists())
   self.assertTrue(sum(c[0]=='focus'for c in raw.calls)==1 and sum(c[0]=='qs'for c in raw.calls)==2)
