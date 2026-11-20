"""Normal release transport budgets; synthetic REST only, no actual DELETE."""
from pathlib import Path
import copy,importlib.util,sys,unittest
from unittest.mock import patch
CI=Path(__file__).resolve().parents[1];sys.path.insert(0,str(CI))
spec=importlib.util.spec_from_file_location('normal_cleanup_public_fixture',Path(__file__).with_name('test_transport_cleanup.py'));f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
MIB=1024*1024
OBSERVED={'opengeul-windows-x64-55':111553816,'opengeul-windows-arm64-55':104472912}
class NormalTransportBudgetTests(unittest.TestCase):
 def setUp(self):
  self.fixture=f.TransportCleanupTests('runTest');self.fixture.setUp();self.m=self.fixture.m
  network_guard=patch.object(self.m.urllib.request,'build_opener',side_effect=AssertionError('No real API or DELETE'))
  self.network=network_guard.start();self.addCleanup(network_guard.stop)
 def items(self):
  rows=copy.deepcopy(self.fixture.artifacts)
  for a in rows:
   if a['name']in OBSERVED:a['size_in_bytes']=OBSERVED[a['name']]
  return rows
 def accepted(self,rows):
  try:return self.fixture.plan(items=rows)
  except ValueError:return None
 def test_observed_normal_arch_sizes_are_admitted_in_complete_successful_publishing_plan(self):
  selected=self.accepted(self.items());self.assertTrue(selected is not None and [a['id']for a in selected]==list(range(1,12)))
  self.assertTrue({a['name']:a['size_in_bytes']for a in selected if a['name']in OBSERVED}==OBSERVED)
 def test_shared_normal_cap_and_existing_one_mib_outer_overhead_have_exact_boundary(self):
  from normal_distribution_budget import ARCH_LIMIT
  self.assertTrue(ARCH_LIMIT==128*MIB)
  for name in OBSERVED:
   rows=self.items();a=next(a for a in rows if a['name']==name);a['size_in_bytes']=ARCH_LIMIT+MIB
   self.assertTrue(self.accepted(rows)is not None)
   a['size_in_bytes']+=1;calls=[]
   with self.assertRaises(ValueError):self.m.execute(self.fixture.context,self.fixture.needs,self.fixture.api_fixture(calls,rows))
   self.assertTrue(not any(method=='DELETE'for method,path in calls))
 def test_only_two_package_limits_follow_shared_arch_budget(self):
  from normal_distribution_budget import ARCH_LIMIT
  expected={'opengeul-wasm':32,'opengeul-browser-inputs':64,'opengeul-e2e-inputs':16,'opengeul-windows-x64':ARCH_LIMIT//MIB,'opengeul-editor-component':64,'opengeul-cli-component':32,'opengeul-e2e-inputs-arm64':16,'opengeul-windows-arm64':ARCH_LIMIT//MIB,'opengeul-editor-component-arm64':64,'opengeul-cli-component-arm64':32,'opengeul-native-signed-arm64':96}
  self.assertTrue(self.m.LIMITS==expected)
  for prefix,cap in expected.items():
   if prefix in self.m.PACKAGES:continue
   a=self.fixture.artifact(88,prefix+'-55'+('-1'if prefix=='opengeul-native-signed-arm64'else''));a['size_in_bytes']=(cap+1)*MIB
   self.m.validate_artifact(self.fixture.context,a);a['size_in_bytes']+=1
   with self.assertRaises(ValueError):self.m.validate_artifact(self.fixture.context,a)
 def test_pr_preserves_both_normal_packages_even_when_they_exceed_old_cap(self):
  self.fixture.context.update(event='pull_request',ref='refs/pull/6/merge');self.fixture.run['event']='pull_request';self.fixture.needs['release']['result']='skipped'
  rows=self.items();selected=self.fixture.plan(items=rows)
  self.assertTrue([a['id']for a in selected]==[1,2,3,5,6,7,9,10,11])
  calls=[];self.m.execute(self.fixture.context,self.fixture.needs,self.fixture.api_fixture(calls,rows))
  deleted={int(path.rsplit('/',1)[1])for method,path in calls if method=='DELETE'}
  self.assertTrue(deleted=={1,2,3,5,6,7,9,10,11}and not deleted&{4,8});self.assertTrue(self.network.call_count==0)
 def test_observed_normal_batch_still_rechecks_every_identity_before_first_simulated_delete(self):
  calls=[];rows=self.items();ids={a['id']for a in rows if a['id']!=99}
  def api(method,path):
   calls.append((method,path))
   if path.endswith('/runs/55'):return self.fixture.run
   if '?per_page'in path:return self.fixture.listing(rows)
   if method=='GET':return next(a for a in rows if path.endswith('/'+str(a['id'])))
   rechecked={int(p.rsplit('/',1)[1])for m,p in calls if m=='GET'and'/artifacts/'in p}
   self.assertTrue(rechecked==ids);return None
  result=self.m.execute(self.fixture.context,self.fixture.needs,api)
  self.assertTrue(len(result['deleted'])==11 and self.network.call_count==0)
 def test_package_digest_or_owner_change_during_predelete_recheck_retains_whole_batch(self):
  for key,value in(('digest','sha256:changed'),('workflow_run',{'id':56,'head_sha':'a'*40}),('id',777),('size_in_bytes',100)):
   rows=self.items();calls=[]
   def changed(a):return dict(a,**{key:value})if a['name']=='opengeul-windows-arm64-55'else a
   with self.assertRaises(ValueError):self.m.execute(self.fixture.context,self.fixture.needs,self.fixture.api_fixture(calls,rows,changed))
   self.assertTrue(not any(m=='DELETE'for m,p in calls)and self.network.call_count==0)
