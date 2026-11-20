"""Same retained MSAA root, after committed original failure; synthetic ABI only."""
from pathlib import Path
import copy,importlib.util,json,sys,tempfile,unittest
from unittest.mock import patch
E2E=Path(__file__).resolve().parents[1]/'e2e';sys.path.insert(0,str(E2E))
import writer_os_accessibility as probe
import writer_os_summary as summary
spec=importlib.util.spec_from_file_location('same_root_public_abi_fixture',Path(__file__).with_name('test_writer_os_accessibility.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
class SameRootTests(unittest.TestCase):
 def setUp(self):self.raw=f.RawFixture();self.raw.focus_vt=0;self.owner=f.Owner(f.REQUEST);self.now=1.;self.backend=None
 def run_probe(self,path,*,enabled=True,late_state=False,state_error=False,deadline=5.):
  def factory(guard,record):
   self.backend=probe.RawComBackend(guard,record,bindings=self.raw.bindings)
   original=self.backend._invoke
   def invoke(pointer,slot,result,args,*values):
    if slot==14 and state_error:return -2147467259
    value=original(pointer,slot,result,args,*values)
    if slot==14 and late_state:self.now=5.
    return value
   self.backend._invoke=invoke;return self.backend
  try:return probe.observe(f.REQUEST,owner_factory=lambda r:self.owner,backend_factory=factory,gui_deadline=deadline,clock=lambda:self.now,primary_checkpoint=path,post_failure_diagnostic=enabled)
  except TypeError:self.fail('Same-root post-failure diagnostic seam must exist')
 def balanced(self):
  self.assertTrue(not self.raw.text_reads and not self.raw.bad_releases and all(v==0 for v in self.raw.ledger.values()))
 def check_first(self,value):
  self.assertTrue(value['verified']==0 and value['stageCode']==4 and value['focusVariantType']==0 and value['focusCall']['rejectCode']==3 and value['hresult']==0)
  self.assertTrue(self.raw.calls.count(('focus',))==1 and sum(c[0]=='root'for c in self.raw.calls)==1)
  self.balanced()
 def diagnostic(self,value):
  self.assertTrue('postFailureDiagnostic'in value,'Separate closed diagnostic is required');return value['postFailureDiagnostic']
 def test_same_root_state_and_query_support_are_separate_from_original_rejection(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['observedMask']==7 and d['known']==1 and d['rootState']==4 and d['ia2Supported']==d['textSupported']==1)
   self.assertTrue(('state','root',3,0)in self.raw.calls and d['ownerBefore']==d['ownerAfter']==1)
   self.assertTrue(len(json.dumps(value,separators=(',',':')).encode())<=4096)
 def test_no_checkpoint_means_no_extra_call(self):
  value=self.run_probe(None);self.check_first(value)
  self.assertTrue(not any(c[0]in('state','qs')for c in self.raw.calls))
 def test_existing_checkpoint_blocks_postfailure_without_changing_original(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';p.write_bytes(b'previous-owned-sentinel');value=self.run_probe(p);self.check_first(value)
   self.assertTrue(p.read_bytes()==b'previous-owned-sentinel' and not any(c[0]in('state','qs')for c in self.raw.calls))
 def test_text_query_failure_is_unknown_and_cannot_change_primary_hresult(self):
  self.raw.supported.remove('text')
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['observedMask']==3 and d['known']==0 and d['stopCode']==5 and d['hresultObserved']==1 and d['hresult']==0x80004002)
 def test_state_failure_does_not_query_interfaces_or_replace_original_failure(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json',state_error=True);self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['observedMask']==0 and d['stopCode']==3 and d['hresult']==0x80004005 and not any(c[0]=='qs'for c in self.raw.calls))
 def test_late_state_return_is_unknown_and_stops_all_later_queries(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json',late_state=True);self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['observedMask']==0 and d['stopCode']==6 and d['known']==0 and not any(c[0]=='qs'for c in self.raw.calls))
 def test_owner_change_cannot_rewrite_original_stage_or_continue_query(self):
  original=probe.commit_primary_checkpoint
  def commit(*a,**kw):
   result=original(*a,**kw);self.owner.fail_at=self.owner.checks+1;return result
  with tempfile.TemporaryDirectory()as t,patch.object(probe,'commit_primary_checkpoint',commit):
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['observedMask']==0 and d['stopCode']==2 and not any(c[0]in('state','qs')for c in self.raw.calls))
 def test_disabled_mode_preserves_legacy_probe_without_extra_calls(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json',enabled=False);self.check_first(value)
   self.assertTrue('postFailureDiagnostic'not in value and not any(c[0]in('state','qs')for c in self.raw.calls))
 def test_pure_summary_keeps_original_failure_and_rejects_forged_diagnostic(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value)
   record=dict(case='korean-ui-writer',module='writer',success=False,stage='writer-os-focus',writerOsAccessibility=value,**{k:value[k]for k in('officePid','officeCreationTime','childHwnd')})
   self.assertTrue(summary.project(record)is not None)
   bad=copy.deepcopy(value);bad['postFailureDiagnostic']['ownerAfter']=0
   with self.assertRaises(ValueError):probe.validate(bad,f.REQUEST)
   record['writerOsAccessibility']=bad;self.assertTrue(summary.project(record)is None)

 def test_late_checkpoint_close_prevents_every_diagnostic_call(self):
  import os
  original=os.close
  def close(fd):original(fd);self.now=5.
  with tempfile.TemporaryDirectory()as t,patch.object(probe.os,'close',close):
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value)
   self.assertTrue('postFailureDiagnostic'not in value and not any(c[0]in('state','qs')for c in self.raw.calls))
 def test_post_diagnostic_owner_after_failure_is_unknown_and_first_stage_is_retained(self):
  # The final full owner check occurs after both interface queries.
  real_check=self.owner.check
  def check(*a,**kw):
   if kw.get('full') and sum(c[0]=='qs'for c in self.raw.calls)==2:raise probe.ProbeFailure()
   return real_check(*a,**kw)
  self.owner.check=check
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['observedMask']==7 and d['ownerAfter']==d['known']==0 and d['stopCode']==2)
 def test_unknown_extra_fields_booleans_wrong_owner_or_forged_masks_are_rejected(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.run_probe(Path(t)/'primary.json');self.check_first(value)
  changes=(('documentText',1),('rootState',True),('officeCreationTime',301),('observedMask',5),('attemptedMask',3),('deadlineMicros',1000000),('known',0))
  for key,number in changes:
   bad=copy.deepcopy(value);bad['postFailureDiagnostic'][key]=number
   with self.assertRaises(ValueError):probe.validate(bad,f.REQUEST)
 def test_submicrosecond_remaining_time_never_becomes_a_known_observation(self):
  real=self.raw.bindings
  original_factory=probe.RawComBackend.state
  def state(backend,root):
   result=original_factory(backend,root);self.now=5.00000005;return result
  with tempfile.TemporaryDirectory()as t,patch.object(probe.RawComBackend,'state',state):
   value=self.run_probe(Path(t)/'primary.json',deadline=5.0000001);self.check_first(value);d=self.diagnostic(value)
   self.assertTrue(d['known']==0 and d['stopCode']==6)

class WiringTests(unittest.TestCase):
 def setUp(self):
  import korean_ui_smoke as kui
  self.kui=kui;kui._WRITER_CAPTURE_PENDING.clear()
  spec=importlib.util.spec_from_file_location('same_root_checkpoint_fixture',Path(__file__).with_name('test_writer_primary_checkpoint.py'))
  self.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.c)
  self.fixture=self.c.CheckpointTests('runTest');self.fixture.setUp();self.commands=[]
 def capture(self,root,*,enabled,forced=False,pending=False):
  destination=root/'uia.json';destination.write_text('{"controlCount":0}')
  def core(command,**kw):
   self.commands.append(command);p=Path(command[command.index('--writer-primary-checkpoint')+1]);deadline=kw['deadline']
   probe.commit_primary_checkpoint(p,self.fixture.primary,f.REQUEST,deadline=deadline,clock=lambda:1.)
   raw=f.RawFixture();raw.focus_vt=0;owner=f.Owner(f.REQUEST)
   # A second owned synthetic checkpoint binds exactly the same original facts.
   value=probe.observe(f.REQUEST,owner_factory=lambda r:owner,backend_factory=lambda g,r:probe.RawComBackend(g,r,bindings=raw.bindings),gui_deadline=deadline,clock=lambda:1.,primary_checkpoint=p.with_name('synthetic-final.json'),post_failure_diagnostic=True)
   return dict(retired=int(not pending),pendingRetained=int(pending),naturalExit=int(not forced),statusCode=3 if forced or pending else 2,exitCode=1 if forced else 0),b'1\n'+json.dumps(value,separators=(',',':')).encode()+b'\n'
  with patch.object(self.kui,'_capture_writer_regular_file',core),patch.object(self.kui.time,'monotonic',lambda:1.):
   try:return self.kui.capture_writer_regular_checkpoint(123,200,destination,writer_request=dict(f.REQUEST),same_root_diagnostic=enabled)
   except TypeError:self.fail('Separate bounded parent opt-in must exist')
 def test_explicit_parent_optin_adds_only_hidden_diagnostic_flag_and_preserves_primary(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.capture(Path(t),enabled=True)
   self.assertTrue(self.commands[0].count('--writer-same-root-after-failure')==1)
   self.assertTrue(value['writerPrimaryCheckpoint']['postDiagnosticObserved']==1 and value['writerOsAccessibility']['verified']==0)
 def test_default_parent_does_not_authorize_hidden_diagnostic(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.capture(Path(t),enabled=False)
   self.assertTrue('--writer-same-root-after-failure'not in self.commands[0])
   self.assertTrue(value['writerPrimaryCheckpoint']['postDiagnosticObserved']==0 and 'postFailureDiagnostic'not in value['writerOsAccessibility'])
 def test_forced_retirement_recovers_only_first_checkpoint_and_unknown_diagnostic(self):
  with tempfile.TemporaryDirectory()as t:
   value=self.capture(Path(t),enabled=True,forced=True)
   self.assertTrue(value['writerOsAccessibility']==self.fixture.primary and value['writerPrimaryCheckpoint']['postDiagnosticObserved']==0)
 def test_pending_optin_reads_no_snapshot_or_checkpoint(self):
  with tempfile.TemporaryDirectory()as t,patch.object(probe,'read_primary_checkpoint',side_effect=AssertionError('No pending checkpoint read')),patch.object(Path,'read_text',side_effect=AssertionError('No pending snapshot read')):
   with self.assertRaises(self.kui.WriterCapturePending):self.capture(Path(t),enabled=True,pending=True)
 def test_library_requires_bounded_parent_before_enabling_extra_calls(self):
  with patch.object(self.kui.native,'require_engine_fixture',side_effect=AssertionError('No launch')):
   for function,args in((self.kui.run_case,(Path('/synthetic'),)*3+('writer',)),(self.kui.run_modules,(Path('/synthetic'),)*3+(['writer'],))):
    try:
     with self.assertRaises(ValueError):function(*args,writer_same_root_diagnostic=True)
    except TypeError:self.fail('Library opt-in must fail closed before launch')
 def test_cli_flag_cannot_authorize_unbounded_only_or_missing_checkpoint(self):
  with tempfile.TemporaryDirectory()as t:
   base=['fixed-synthetic','--writer-same-root-after-failure']
   for args in(base,base+['--writer-msaa-only','--writer-msaa-deadline','5','--writer-primary-checkpoint',str(Path(t)/'p.json')],base+['--writer-msaa','--writer-msaa-deadline','5']):
    try:
     with patch.object(sys,'argv',args),self.assertRaises(ValueError):self.kui.main()
    except SystemExit:self.fail('Hidden diagnostic CLI must be explicitly validated')
 def test_run_modules_passes_same_optin_only_for_owned_writer_bounded_case(self):
  seen=[]
  def run(*args,**kw):
   seen.append((args[3],kw));return dict(module=args[3],success=False,koreanUiVerified=False,tabbedUiVerified=False)
  with tempfile.TemporaryDirectory()as t,patch.object(self.kui,'run_case',run),patch.object(self.kui.native,'write_result',lambda*a:None):
   try:self.kui.run_modules(Path(t),Path(t),Path(t),['writer','calc'],writer_regular_capture=True,writer_same_root_diagnostic=True)
   except TypeError:self.fail('Explicit bounded cohort opt-in must exist')
  self.assertTrue(seen[0][1].get('writer_same_root_diagnostic')is True and seen[0][1].get('writer_regular_capture')is True and 'writer_same_root_diagnostic'not in seen[1][1])
