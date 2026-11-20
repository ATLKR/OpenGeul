"""Closed numeric checkpoint before optional same-root diagnostics; synthetic only."""
import copy,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
E2E=Path(__file__).resolve().parents[1]/'e2e';sys.path.insert(0,str(E2E))
import writer_os_accessibility as probe
spec=importlib.util.spec_from_file_location('writer_checkpoint_public_fixture',Path(__file__).with_name('test_writer_os_accessibility.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
class CheckpointTests(unittest.TestCase):
 def setUp(self):
  self.owner=fixture.Owner(fixture.REQUEST);self.raw=fixture.RawFixture();self.raw.focus_vt=0;self.primary=None
  class Backend(probe.RawComBackend):
   def focus(inner,root):
    try:return super().focus(root)
    except probe.ProbeFailure:
     self.primary=copy.deepcopy(inner.record);raise
  self.final=probe.observe(fixture.REQUEST,owner_factory=lambda r:self.owner,backend_factory=lambda g,r:Backend(g,r,bindings=self.raw.bindings))
  self.assertTrue(self.primary is not None,'Synthetic original failure must exist')
 def api(self,name):
  f=getattr(probe,name,None);self.assertTrue(callable(f),'Checkpoint API must exist');return f
 def write(self,path,clock=lambda:1.):
  return self.api('commit_primary_checkpoint')(path,self.primary,fixture.REQUEST,deadline=5.,clock=clock)
 def read(self,path):return self.api('read_primary_checkpoint')(path,fixture.REQUEST,deadline=5.)
 def test_original_failure_roundtrips_before_cleanup_without_claiming_cleanup_or_qualification(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';self.assertTrue(self.write(p));x=self.read(p)
   self.assertTrue(x['primary']==self.primary,'Original numeric failure changed')
   self.assertTrue(x['cleanupObserved']==x['acceptanceEligible']==0)
   self.assertTrue(x['primary']['referencesReleased']==0 and self.final['referencesReleased']>0)
   self.assertTrue(self.raw.calls.count(('focus',))==1 and not self.raw.text_reads)
 def test_existing_target_is_never_overwritten(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';p.write_bytes(b'previous-owned-sentinel')
   with self.assertRaises((OSError,ValueError)):self.write(p)
   self.assertTrue(p.read_bytes()==b'previous-owned-sentinel')
 def test_owner_mismatch_or_poison_field_is_rejected_without_rendering_it(self):
  class Poison:
   def __repr__(self):raise AssertionError('No repr')
   def __str__(self):raise AssertionError('No str')
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json'
   for key,value in(('officePid',201),('rootRole',Poison()),('documentText',Poison())):
    bad=copy.deepcopy(self.primary);bad[key]=value
    with self.assertRaises(ValueError):self.api('commit_primary_checkpoint')(p,bad,fixture.REQUEST,deadline=5.,clock=lambda:1.)
    self.assertTrue(not p.exists())
 def test_expired_budget_cannot_publish_or_allow_extra_com(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json'
   with self.assertRaises(ValueError):self.write(p,clock=lambda:5.)
   self.assertTrue(not p.exists())
 def test_late_close_does_not_authorize_postfailure_but_preserves_original_checkpoint(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';now=[1.];original=os.close
   def close(fd):original(fd);now[0]=5.
   with patch.object(probe.os,'close',close):
    with self.assertRaises(ValueError):self.write(p,clock=lambda:now[0])
   self.assertTrue(self.read(p)['primary']==self.primary)
 def test_partial_duplicate_or_unknown_checkpoint_is_rejected(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';self.write(p);raw=p.read_bytes()
   for data in(raw[:-1],raw+b'x',raw.replace(b'"schemaVersion":1',b'"schemaVersion":1,"schemaVersion":1',1),raw.replace(b'"cleanupObserved":0',b'"cleanupObserved":1',1)):
    p.write_bytes(data)
    with self.assertRaises(ValueError):self.read(p)
 def test_regressed_clock_after_close_cannot_authorize_postfailure(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';times=iter((1.,.5))
   with self.assertRaises(ValueError):self.write(p,clock=lambda:next(times))
 def test_partial_write_is_not_a_checkpoint(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json'
   with patch.object(probe.os,'write',lambda fd,data:len(data)-1):
    with self.assertRaises(ValueError):self.write(p)
   with self.assertRaises(ValueError):self.read(p)
 def test_symlink_parent_or_target_is_not_admitted(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);actual=root/'actual';actual.mkdir();linked=root/'linked';linked.symlink_to(actual,target_is_directory=True)
   with self.assertRaises(ValueError):self.write(linked/'primary.json')
   source=actual/'source.json';self.write(source);target=actual/'linked.json';target.symlink_to(source)
   with self.assertRaises(ValueError):self.read(target)
 def test_read_rejects_another_owner_and_original_deadline(self):
  with tempfile.TemporaryDirectory()as t:
   p=Path(t)/'primary.json';self.write(p)
   with self.assertRaises(ValueError):self.api('read_primary_checkpoint')(p,dict(fixture.REQUEST,officeCreationTime=301),deadline=5.)
   with self.assertRaises(ValueError):self.api('read_primary_checkpoint')(p,fixture.REQUEST,deadline=6.)
 def test_second_focus_via_original_method_would_overwrite_first_result(self):
  record=probe.failure(fixture.REQUEST,4);raw=fixture.RawFixture();raw.focus_vt=0;b=probe.RawComBackend(lambda:None,record,bindings=raw.bindings)
  root=b.root(fixture.REQUEST['childHwnd'])
  try:
   with self.assertRaises(probe.ProbeFailure):b.focus(root)
   initial=copy.deepcopy(record['focusCall']);raw.focus_vt=3;b.focus(root)
   self.assertTrue(record['focusVariantType']==3 and record['focusCall']!=initial,'Naive focus reuse must be shown unsafe')
  finally:b.close()

 def test_collector_checkpoint_never_adds_or_replaces_a_com_call(self):
  with tempfile.TemporaryDirectory()as t:
   raw=fixture.RawFixture();raw.focus_vt=0;owner=fixture.Owner(fixture.REQUEST);path=Path(t)/'primary.json'
   try:
    value=probe.observe(fixture.REQUEST,owner_factory=lambda r:owner,backend_factory=lambda g,r:probe.RawComBackend(g,r,bindings=raw.bindings),gui_deadline=5.,clock=lambda:1.,primary_checkpoint=path)
   except TypeError:self.fail('Collector checkpoint seam must exist')
   self.assertTrue(value==self.final and path.exists())
   self.assertTrue(raw.calls.count(('focus',))==1 and not any(x[0]in('state','qs')for x in raw.calls) and not raw.text_reads)


class RegularCaptureTests(unittest.TestCase):
 def setUp(self):
  import korean_ui_smoke as kui
  self.kui=kui;self.events=[];self.now=0.;self.child=None
  if hasattr(kui,'_WRITER_CAPTURE_PENDING'):kui._WRITER_CAPTURE_PENDING.clear()
 def api(self):
  f=getattr(self.kui,'_capture_writer_regular_file',None);self.assertTrue(callable(f),'Bounded regular-file adapter must exist');return f
 def fake(self,*,natural=False,exit_after_kill=False,swap=False,poll_error=False,late_close=False,close_during_poll=False):
  events=self.events;test=self
  class Handle(int):
   closed=False
   def __new__(cls):return int.__new__(cls,111)
   def Close(h):
    h.closed=True
    events.append('close-handle')
    if late_close:test.now=2.
  class Child:
   pid=100;returncode=None
   def __init__(self):self._handle=Handle();self.original=self._handle;self.killed=False
   def poll(self):
    events.append('poll')
    if poll_error:raise RuntimeError()
    if swap:self._handle=Handle()
    if close_during_poll:self._handle.closed=True
    if natural or self.killed and exit_after_kill:self.returncode=0 if natural else 1
    return self.returncode
   def kill(self):events.append('terminate');self.killed=True
   def communicate(self,*a,**kw):raise AssertionError('No pipe reader')
   def __enter__(self):raise AssertionError('No Popen context')
   def __exit__(self,*a):raise AssertionError('No context wait')
  def spawn(command,**kw):
   self.launch_kwargs=kw
   self.assertTrue(kw['stdout']is not self.kui.subprocess.PIPE and kw['stderr']==self.kui.subprocess.DEVNULL and kw['shell']is False)
   kw['stdout'].write(b'1\n{}');kw['stdout'].flush();test.child=Child();return test.child
  return spawn
 def run_capture(self,spawn):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);windows=root/'windows';(windows/'System32').mkdir(parents=True);profile=root/'profile';profile.mkdir();(profile/'Roaming').mkdir();(profile/'Local').mkdir()
   values={'SystemRoot':str(windows),'WINDIR':str(windows),'USERPROFILE':str(profile),'APPDATA':str(profile/'Roaming'),'LOCALAPPDATA':str(profile/'Local')}
   class OpaqueEnvironment:
    def get(inner,key,default=None):
     if key not in values:raise AssertionError('Unexpected environment lookup')
     return values[key]
    def __iter__(inner):raise AssertionError('No environment enumeration')
    def copy(inner):raise AssertionError('No environment copy')
    def __repr__(inner):raise AssertionError('No environment repr')
   self.environment=OpaqueEnvironment()
   with patch.object(self.kui,'os',SimpleNamespace(name='nt',environ=self.environment)),patch.object(self.kui.subprocess,'Popen',spawn):
    return self.api()(['fixed-synthetic-writer'],deadline=1.,checkpoint_folder=root,clock=lambda:self.now,pause=self.pause)
 def pause(self,seconds):self.now+=1.
 def cleanup_fake_pending(self):
  for p in getattr(self.kui,'_WRITER_CAPTURE_PENDING',[]):
   if p.get('stdout')is not None:p['stdout'].close()
  if hasattr(self.kui,'_WRITER_CAPTURE_PENDING'):self.kui._WRITER_CAPTURE_PENDING.clear()
 def test_natural_exit_reads_regular_file_only_after_retirement(self):
  try:
   proof,raw=self.run_capture(self.fake(natural=True))
   self.assertTrue(raw==b'1\n{}' and proof['retired']==1 and proof['stdoutRead']==1 and proof['creationHandleClosed']==1)
   self.assertTrue(self.events==['poll','close-handle'])
  finally:self.cleanup_fake_pending()
 def test_deadline_requests_original_handle_termination_then_zero_poll_without_wait(self):
  try:
   proof,raw=self.run_capture(self.fake())
   self.assertTrue(raw is None and proof['terminateRequested']==1 and proof['retired']==0 and proof['pendingRetained']==1 and proof['stdoutRead']==0)
   self.assertTrue(self.events==['poll','terminate','poll'])
   self.assertTrue(len(self.kui._WRITER_CAPTURE_PENDING)==1 and self.kui._WRITER_CAPTURE_PENDING[0]['handle']is self.child.original)
  finally:self.cleanup_fake_pending()
 def test_forced_retirement_never_reads_partial_stdout_as_normal_result(self):
  try:
   proof,raw=self.run_capture(self.fake(exit_after_kill=True))
   self.assertTrue(raw is None and proof['retired']==1 and proof['stdoutRead']==0 and proof['creationHandleClosed']==1)
  finally:self.cleanup_fake_pending()
 def test_changed_creation_handle_prevents_termination_of_any_other_process(self):
  try:
   proof,raw=self.run_capture(self.fake(swap=True))
   self.assertTrue(raw is None and proof['pendingRetained']==1 and proof['terminateRequested']==0 and 'terminate'not in self.events and 'close-handle'not in self.events)
  finally:self.cleanup_fake_pending()
 def test_poll_failure_retains_owned_resources_without_rendering_exception(self):
  try:
   proof,raw=self.run_capture(self.fake(poll_error=True))
   self.assertTrue(raw is None and proof['pendingRetained']==1 and 'close-handle'not in self.events)
  finally:self.cleanup_fake_pending()
 def test_pending_capsule_prevents_another_launch(self):
  try:
   self.run_capture(self.fake());events=list(self.events);proof,raw=self.run_capture(lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Second launch forbidden')))
   self.assertTrue(proof['pendingRetained']==1 and raw is None and self.events==events)
  finally:self.cleanup_fake_pending()

 def test_handle_change_during_natural_poll_cannot_publish_stdout(self):
  try:
   proof,raw=self.run_capture(self.fake(natural=True,swap=True))
   self.assertTrue(raw is None and proof['pendingRetained']==1 and proof['stdoutRead']==0)
  finally:self.cleanup_fake_pending()
 def test_late_handle_close_cannot_report_completion_within_deadline(self):
  try:
   proof,raw=self.run_capture(self.fake(natural=True,late_close=True))
   self.assertTrue(raw is None and proof['withinOriginalDeadline']==0 and proof['statusCode']!=2)
  finally:self.cleanup_fake_pending()
 def test_constructor_failure_retains_sink_and_unknown_launch_without_pid_guess(self):
  try:
   class NoText(Exception):
    def __str__(self):raise AssertionError('No error text')
    def __repr__(self):raise AssertionError('No error repr')
   def spawn(*a,**kw):raise NoText()
   proof,raw=self.run_capture(spawn)
   self.assertTrue(raw is None and proof['pendingRetained']==1 and proof['creationHandleKnown']==0 and proof['terminateRequested']==0)
   self.assertTrue(self.kui._WRITER_CAPTURE_PENDING[0]['process']is None)
  finally:self.cleanup_fake_pending()

 def test_child_environment_is_explicit_nonsecret_and_no_console_or_stdin_is_inherited(self):
  try:
   proof,raw=self.run_capture(self.fake(natural=True));kw=self.launch_kwargs
   self.assertTrue(type(kw.get('env'))is dict and kw['env']is not self.environment)
   self.assertTrue(kw.get('stdin')==self.kui.subprocess.DEVNULL and kw.get('creationflags')==0x08000000)
   self.assertTrue(set(kw['env'])=={'SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP','PATH','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE','PYTHONUTF8','PYTHONIOENCODING'})
  finally:self.cleanup_fake_pending()
 def test_same_python_handle_object_closed_midpoll_cannot_authorize_terminate(self):
  try:
   proof,raw=self.run_capture(self.fake(close_during_poll=True))
   self.assertTrue(raw is None and proof['terminateRequested']==0 and proof['pendingRetained']==1 and 'terminate'not in self.events)
  finally:self.cleanup_fake_pending()

 def test_maximum_closed_body_with_windows_crlf_framing_is_transportable(self):
  original_spawn=self.fake(natural=True)
  def spawn(command,**kw):
   p=original_spawn(command,**kw);kw['stdout'].seek(0);kw['stdout'].truncate();kw['stdout'].write(b'1\r\n'+b'0'*4096+b'\r\n');kw['stdout'].flush();return p
  try:
   proof,raw=self.run_capture(spawn)
   self.assertTrue(proof['stdoutRead']==1 and raw is not None and len(raw)==4101)
  finally:self.cleanup_fake_pending()


class RegularParentAndFenceTests(unittest.TestCase):
 def setUp(self):
  CheckpointTests.setUp(self);import korean_ui_smoke as kui;self.kui=kui
  if hasattr(kui,'_WRITER_CAPTURE_PENDING'):kui._WRITER_CAPTURE_PENDING.clear()
 def capture(self,destination,proof,raw):
  f=getattr(self.kui,'capture_writer_regular_checkpoint',None)
  self.assertTrue(callable(f),'Regular parent integration seam must exist')
  def core(command,**kw):
   self.assertTrue(kw['deadline']==46. and float(command[command.index('--writer-msaa-deadline')+1])==46.)
   self.primary_for(command,kw['deadline']);return dict(proof),raw
  with patch.object(self.kui,'_capture_writer_regular_file',core),patch.object(self.kui.time,'monotonic',lambda:1.):
   return f(123,200,destination,writer_request=dict(fixture.REQUEST))
 def primary_for(self,command,deadline):
  index=command.index('--writer-primary-checkpoint');path=Path(command[index+1]);probe.commit_primary_checkpoint(path,self.primary,fixture.REQUEST,deadline=deadline,clock=lambda:1.)
 def test_natural_crlf_numeric_result_uses_original_record(self):
  with tempfile.TemporaryDirectory()as t:
   destination=Path(t)/'os.json';destination.write_text('{"controlCount":0}')
   raw=b'1\r\n'+json.dumps(self.final,separators=(',',':')).encode()+b'\r\n'
   x=self.capture(destination,dict(retired=1,naturalExit=1,statusCode=2,exitCode=0,pendingRetained=0),raw)
   self.assertTrue(x['writerOsAccessibility']==self.final and x['writerPrimaryCheckpoint']['primaryPreserved']==0)
 def test_confirmed_forced_retirement_recovers_only_primary_checkpoint(self):
  with tempfile.TemporaryDirectory()as t:
   destination=Path(t)/'os.json';destination.write_text('{"controlCount":0}')
   x=self.capture(destination,dict(retired=1,naturalExit=0,statusCode=3,exitCode=1,pendingRetained=0),None)
   self.assertTrue(x['writerOsAccessibility']==self.primary and x['writerPrimaryCheckpoint']['primaryPreserved']==1 and x['writerPrimaryCheckpoint']['cleanupObserved']==x['writerPrimaryCheckpoint']['postDiagnosticObserved']==0)
 def test_pending_does_not_read_checkpoint_or_ui_snapshot(self):
  with tempfile.TemporaryDirectory()as t:
   destination=Path(t)/'os.json'
   def forbidden(*a,**kw):raise AssertionError('Pending file cannot be read')
   pending=getattr(self.kui,'WriterCapturePending',None);self.assertTrue(isinstance(pending,type),'Pending signal must exist')
   with patch.object(probe,'read_primary_checkpoint',forbidden),patch.object(Path,'read_text',forbidden):
    with self.assertRaises(pending):self.capture(destination,dict(retired=0,naturalExit=0,statusCode=3,pendingRetained=1),None)
 def test_pending_registry_prevents_run_modules_launch_even_before_first_case(self):
  with tempfile.TemporaryDirectory()as t:
   self.kui._WRITER_CAPTURE_PENDING.append({'ownedSyntheticCapsule':True})
   calls=[]
   try:
    with patch.object(self.kui,'run_case',lambda *a,**kw:(calls.append(1)or dict(module=a[3],success=False,koreanUiVerified=False,tabbedUiVerified=False))),patch.object(self.kui.native,'write_result',lambda *a:None):
     report=self.kui.run_modules(Path(t),Path(t),Path(t),['writer','calc'])
    self.assertTrue(not calls and report['success']is False and report.get('writerProbePending')==1)
   finally:self.kui._WRITER_CAPTURE_PENDING.clear()
 def test_pending_from_first_case_prevents_every_later_module(self):
  with tempfile.TemporaryDirectory()as t:
   pending=getattr(self.kui,'WriterCapturePending',None);self.assertTrue(isinstance(pending,type),'Pending signal must exist');calls=[]
   def run(*a,**kw):calls.append(a[3]);raise pending()
   with patch.object(self.kui,'run_case',run),patch.object(self.kui.native,'write_result',lambda *a:None):
    report=self.kui.run_modules(Path(t),Path(t),Path(t),['writer','calc','impress'])
   self.assertTrue(calls==['writer'] and report['success']is False and report.get('writerProbePending')==1)
 def test_default_run_modules_does_not_pass_new_kwargs_to_legacy_case(self):
  with tempfile.TemporaryDirectory()as t:
   calls=[]
   def run(suite,fixtures,output,module,*,probe_only=False):calls.append(module);return dict(module=module,success=True,koreanUiVerified=True,tabbedUiVerified=True)
   with patch.object(self.kui,'run_case',run),patch.object(self.kui.native,'write_result',lambda *a:None):
    report=self.kui.run_modules(Path(t),Path(t),Path(t),['calc'])
   self.assertTrue(calls==['calc'] and report['success']is True)

 def test_checkpoint_first_failure_cannot_be_replaced_by_a_later_success(self):
  good_raw=fixture.RawFixture();owner=fixture.Owner(fixture.REQUEST)
  good=probe.observe(fixture.REQUEST,owner_factory=lambda r:owner,backend_factory=lambda g,r:probe.RawComBackend(g,r,bindings=good_raw.bindings))
  self.assertTrue(good['verified']==1)
  with tempfile.TemporaryDirectory()as t:
   destination=Path(t)/'os.json';destination.write_text('{"controlCount":0}')
   raw=b'1\r\n'+json.dumps(good,separators=(',',':')).encode()+b'\r\n'
   value=self.capture(destination,dict(retired=1,naturalExit=1,statusCode=2,exitCode=0,pendingRetained=0),raw)
   self.assertTrue(value['writerOsAccessibility']==self.primary and value['writerPrimaryCheckpoint']['primaryPreserved']==1)

 def test_actual_run_case_pending_precedes_native_com_and_reaches_owned_cleanup(self):
  spec=importlib.util.spec_from_file_location('writer_primary_legacy_kui_fixture',Path(__file__).with_name('test_korean_ui_smoke.py'))
  existing=importlib.util.module_from_spec(spec);spec.loader.exec_module(existing)
  old=existing.WriterOsIntegrationTests('runTest');old.setUp();refs=[];original=self.kui.run_case
  def pending(*a,**kw):
   refs.append((self.kui.accessible.capture_bounded,self.kui.native.close_document))
   raise self.kui.WriterCapturePending()
  def run(*a,**kw):return original(*a,**kw,writer_regular_capture=True)
  with patch.object(self.kui,'run_case',run),patch.object(self.kui,'capture_writer_regular_checkpoint',pending):
   with self.assertRaises(self.kui.WriterCapturePending)as caught:old.run_writer()
  self.assertTrue(caught.exception.record['writerProbePending']==1 and caught.exception.record['success']is False)
  self.assertTrue(refs and refs[0][0].call_count==refs[0][1].call_count==0)
  self.assertTrue(caught.exception.record['officeExitedAfterCleanup']is True)
 def test_pending_fence_covers_direct_case_and_each_existing_probe_launch_entry(self):
  pending=self.kui.WriterCapturePending;calls=[];blocked=0;capsule={'ownedSyntheticCapsule':True};self.kui._WRITER_CAPTURE_PENDING.append(capsule)
  def forbidden(*a,**kw):calls.append(1);raise AssertionError('Pending cohort cannot launch')
  try:
   with patch.object(self.kui.subprocess,'run',forbidden),patch.object(self.kui.subprocess,'Popen',forbidden),patch.object(self.kui.native,'require_engine_fixture',forbidden):
    actions=(lambda:self.kui.run_case(Path('/synthetic'),Path('/synthetic'),Path('/synthetic'),'writer'),lambda:self.kui.capture_bounded(123,200,Path('/synthetic/output'),writer_request=dict(fixture.REQUEST)),lambda:self.kui.capture_writer_msaa_after_native(dict(fixture.REQUEST),5.),lambda:self.kui.capture_writer_root_diagnostic(dict(fixture.REQUEST),5.))
    for action in actions:
     try:action()
     except pending:blocked+=1
     except BaseException:pass
   self.assertTrue(blocked==4 and not calls and self.kui._WRITER_CAPTURE_PENDING==[capsule])
  finally:self.kui._WRITER_CAPTURE_PENDING.clear()

 def test_regular_missing_or_partial_checkpoint_keeps_original_timeout_unknown(self):
  for content in(None,b'{'):
   with tempfile.TemporaryDirectory()as t:
    destination=Path(t)/'os.json';destination.write_text('{"controlCount":0}')
    def core(command,**kw):
     self.assertTrue(kw['deadline']==46.)
     checkpoint=Path(command[command.index('--writer-primary-checkpoint')+1])
     if content is not None:checkpoint.write_bytes(content)
     return dict(retired=1,naturalExit=0,statusCode=3,exitCode=1,pendingRetained=0),None
    with patch.object(self.kui,'_capture_writer_regular_file',core),patch.object(self.kui.time,'monotonic',lambda:1.):
     value=self.kui.capture_writer_regular_checkpoint(123,200,destination,writer_request=dict(fixture.REQUEST))
    self.assertTrue(value['writerOsAccessibility']['verified']==0 and value['writerOsAccessibility']['stageCode']==14)
    self.assertTrue(value['writerPrimaryCheckpoint']['primaryPreserved']==value['writerPrimaryCheckpoint']['postDiagnosticObserved']==0)
 def test_regular_owner_tuple_is_joined_before_any_launch_or_directory_creation(self):
  with tempfile.TemporaryDirectory()as t:
   destination=Path(t)/'os.json'
   def forbidden(*a,**kw):raise AssertionError('No launch before exact owner join')
   with patch.object(self.kui.subprocess,'Popen',forbidden),patch.object(self.kui,'_capture_writer_regular_file',forbidden):
    with self.assertRaises(ValueError):self.kui.capture_writer_regular_checkpoint(124,200,destination,writer_request=dict(fixture.REQUEST))
   self.assertTrue(not list(Path(t).iterdir()))
