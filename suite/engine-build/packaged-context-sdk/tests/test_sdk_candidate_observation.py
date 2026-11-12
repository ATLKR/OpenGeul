"""Actual temporary SDK member reads; synthetic data only, no Windows SDK/API."""
import copy,hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import toolchain as tools
import ci_entry as entry
import test_ci_wiring as fixtures


def observation():return {'operations':[],'failures':[],'failureCount':0,'truncated':False}


def reason(stage=1):
 return {'stageCode':stage,'exceptionKnown':True,'exceptionTypeCode':2,'nativeCode':2,'errno':None,'winerror':None,
   'filesystemCode':4,'fileRoleCode':None,'observedLinkCount':2,'sourceFrames':[{'fileCode':2,'line':37}],
   'sourceLocationKnown':True,'sourceFramesTruncated':False}


def sample():
 return {'operations':[{'operationCode':1,'enumerationKnown':True,'candidateCount':2}],
   'failures':[{'operationCode':1,'version':[10,0,26100,0],'memberSlot':8,'reason':reason()}],
   'failureCount':1,'truncated':False}


class SdkCandidateReadObservationTests(unittest.TestCase):
 def sdk(self,root,version,*,arch='x64'):
  for rel in tools.sdk_members(version,arch):
   p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixed-public-sdk-test')
 def block(self,root,version,slot,*,arch='x64',missing=False):
  p=root/tools.sdk_members(version,arch)[slot-1]
  if missing:p.unlink()
  else:(p.parent/('owned-alias-'+str(slot))).hardlink_to(p)
 def select(self,root,obs,*,operation=1):return tools.installed_sdk(root,'x64',observations=obs,operation=operation)
 def test_default_selection_dictionary_and_hashes_are_unchanged(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);self.sdk(root,'10.0.26100.0');a=tools.installed_sdk(root,'x64')
   self.assertEqual(set(a),{'root','version','files'});self.assertEqual(len(a['files']),16)
   self.assertEqual(a['files'][0]['sha256'],hashlib.sha256(b'fixed-public-sdk-test').hexdigest())
 def test_actual_hardlink_first_slot_reason_does_not_trigger_remaining_reads(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);version='10.0.26100.0';self.sdk(root,version);self.block(root,version,8);obs=observation();reads=[];original=tools.read
   def read(path,*a):reads.append(Path(path).relative_to(root).as_posix());return original(path,*a)
   with mock.patch.object(tools,'read',read),self.assertRaises(tools.GateFailure)as caught:self.select(root,obs)
   self.assertEqual(caught.exception.code,12);self.assertEqual(reads,list(tools.sdk_members(version,'x64')[:8]))
   self.assertEqual(obs['failureCount'],1);row=obs['failures'][0]
   self.assertEqual(row['memberSlot'],8);self.assertEqual(row['version'],[10,0,26100,0])
   self.assertEqual(row['reason']['filesystemCode'],4);self.assertEqual(row['reason']['observedLinkCount'],2)
   self.assertEqual(row['reason']['nativeCode'],2);self.assertTrue(row['reason']['sourceLocationKnown'])
   self.assertTrue(all(x['fileCode']==2 for x in row['reason']['sourceFrames']))
   self.assertIsNotNone(entry.validate_sdk_candidate_observation(obs))
 def test_actual_missing_member_records_os_reason_and_aggregate_remains12(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);self.sdk(root,'10.0.26100.0');self.block(root,'10.0.26100.0',16,missing=True);obs=observation()
   with self.assertRaises(tools.GateFailure)as caught:self.select(root,obs)
   self.assertEqual(caught.exception.code,12);row=obs['failures'][0]
   self.assertEqual(row['memberSlot'],16);self.assertEqual(row['reason']['exceptionTypeCode'],5);self.assertEqual(row['reason']['errno'],2)
   self.assertIsNone(row['reason']['nativeCode']);self.assertIsNone(row['reason']['filesystemCode'])
 def test_actual_older_complete_version_still_wins_after_newest_rejection(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);self.sdk(root,'10.0.26100.0');self.sdk(root,'10.0.22621.0');self.block(root,'10.0.26100.0',3)
   obs=observation();value=self.select(root,obs);baseline=tools.installed_sdk(root,'x64')
   self.assertEqual(value,baseline);self.assertEqual(value['version'],'10.0.22621.0');self.assertEqual(len(value['files']),16)
   self.assertEqual(obs['operations'],[{'operationCode':1,'enumerationKnown':True,'candidateCount':2}])
   self.assertEqual(obs['failureCount'],1);self.assertFalse(obs['truncated'])
 def test_truncation_keeps_fallback_scanning_and_catches_first_failure_only(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);versions=['10.0.'+str(26100+i)+'.0'for i in range(6)]
   for ver in versions:self.sdk(root,ver);self.block(root,ver,1)
   obs=observation();reads=[];original=tools.read
   def read(path,*a):reads.append(Path(path).relative_to(root).as_posix());return original(path,*a)
   with mock.patch.object(tools,'read',read),self.assertRaises(tools.GateFailure)as caught:self.select(root,obs)
   self.assertEqual(caught.exception.code,12);self.assertEqual(len(reads),6)
   self.assertEqual(obs['failureCount'],6);self.assertEqual(len(obs['failures']),4);self.assertTrue(obs['truncated'])
   self.assertEqual([r['version'][2]for r in obs['failures']],[26105,26104,26103,26102])
   self.assertEqual(obs['operations'][0]['candidateCount'],6);entry.validate_sdk_candidate_observation(obs)
 def test_zero_matching_versions_is_known_enumeration_without_candidate_failures(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);(root/'Include').mkdir();obs=observation()
   with self.assertRaises(tools.GateFailure)as caught:self.select(root,obs)
   self.assertEqual(caught.exception.code,12);self.assertEqual(obs['operations'],[{'operationCode':1,'enumerationKnown':True,'candidateCount':0}])
   self.assertEqual(obs['failureCount'],0);self.assertEqual(obs['failures'],[]);self.assertFalse(obs['truncated'])
 def test_root_failure_keeps_enumeration_unknown_without_fake_zero_candidates(self):
  with tempfile.TemporaryDirectory()as td:
   obs=observation()
   with self.assertRaises(OSError):self.select(Path(td)/'not-created',obs)
   self.assertEqual(obs['operations'],[{'operationCode':1,'enumerationKnown':False,'candidateCount':None}])
   self.assertEqual(obs['failureCount'],0);self.assertEqual(obs['failures'],[])
 def test_second_fixed_call_is_separate_and_uses_original_stage6(self):
  with tempfile.TemporaryDirectory()as td:
   root=Path(td);self.sdk(root,'10.0.26100.0');obs=observation();self.select(root,obs)
   self.block(root,'10.0.26100.0',2)
   with self.assertRaises(tools.GateFailure):self.select(root,obs,operation=2)
   self.assertEqual([x['operationCode']for x in obs['operations']],[1,2]);self.assertEqual(obs['failures'][0]['operationCode'],2)
   self.assertEqual(obs['failures'][0]['reason']['stageCode'],6);entry.validate_sdk_candidate_observation(obs)


class SdkCandidatePacketTests(unittest.TestCase):
 def test_none_and_closed_packet_copy_without_mutating_original(self):
  self.assertIsNone(entry.validate_sdk_candidate_observation(None));data=sample();before=copy.deepcopy(data)
  result=entry.validate_sdk_candidate_observation(data);self.assertEqual(result,before);self.assertIsNot(result,data)
  self.assertIsNot(result['failures'][0]['reason'],data['failures'][0]['reason'])
 def test_closed_fields_types_slots_and_reason_reject_arbitrary_metadata(self):
  variants=[]
  for key,value in(('path','SYNTHETIC'),('failureCount',True),('truncated',1),('failureCount',0),('truncated',True)):
   v=sample();v[key]=value;variants.append(v)
  for key,value in(('memberSlot',0),('memberSlot',17),('memberSlot',True),('operationCode',2),('version',[10,0,26100]),('version',[10,0,True,0]),('version',[11,0,26100,0]),('version',[10,0,1000000,0]),('message','SYNTHETIC')):
   v=sample();v['failures'][0][key]=value;variants.append(v)
  for key,value in(('enumerationKnown',False),('candidateCount',None),('candidateCount',True),('operationCode',2),('extra','SYNTHETIC')):
   v=sample();v['operations'][0][key]=value;variants.append(v)
  v=sample();v['failures'][0]['reason']['stageCode']=6;variants.append(v)
  v=sample();v['failures'][0]['reason']['sourceFrames'][0]['fileCode']=7;variants.append(v)
  for index,value in enumerate(variants):
   with self.subTest(case=index),self.assertRaises(entry.CiFailure):entry.validate_sdk_candidate_observation(value)
 def test_exact_tested_schema5_powershell_guard_and_closed_field_are_embedded(self):
  import textwrap,yaml
  wf=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-suite.yml').read_bytes())
  script=next(row['run']for row in wf['jobs']['packaged-context-sdk']['steps']if row.get('id')=='sdk-compile')
  lines=script.splitlines();start=next(i for i,line in enumerate(lines)if line.strip()=='# Schema5: bounded SDK candidate first-failure observations, never an inventory.')
  end=next(i for i in range(start,len(lines))if lines[i].strip()=='} $report')
  block=textwrap.dedent('\n'.join(lines[start:end+1]))+'\n'
  self.assertEqual(hashlib.sha256(block.encode()).hexdigest(),'1ec7404c97d973ee7b800ce10585a595780218f406cb257af556c3cd371ef082')
  self.assertIn("'helperSdkCandidateObservation'",script);self.assertIn('$report.schemaVersion -ne 6 -or',script)
 def test_unobserved_private_report_keeps_new_field_null_and_schema5(self):
  report=entry.public_report({},None,None,failure=5);self.assertEqual(report['schemaVersion'],6)
  self.assertIsNone(report['helperSdkCandidateObservation']);self.assertIsNone(report['helperPhaseResults'])
 def test_raw_candidate_failure_does_not_change_original_success_conditions(self):
  raw=fixtures.success_fixture();raw['sdkCandidateObservation']=sample()
  self.assertIs(entry.validate_sdk_report(raw,'x64','1'*64,180.,raw['compileInputs']),raw)
  outer={'completed':True,'cleanupProved':True,'forcedCleanup':False,'exitCode':0}
  report=entry.public_report(entry.require_context(fixtures.environment(),'x64'),outer,raw,command_binding=raw['commandProcessorBinding'])
  self.assertTrue(report['sdkGatePassed']);self.assertEqual(report['helperSdkCandidateObservation'],sample())
  self.assertFalse(report['qualification']);self.assertFalse(report['canService'])
 def test_stage6_failed_recheck_with_five_completed_phases_and_both_max_observers_fits8192(self):
  raw=fixtures.success_fixture();diag=sample();diag['operations'].append({'operationCode':2,'enumerationKnown':True,'candidateCount':2147483647})
  diag['operations'][0]['candidateCount']=2147483647;diag['failureCount']=2147483647;diag['truncated']=True
  failure=copy.deepcopy(diag['failures'][0]);failure.update(operationCode=2,version=[10,0,999999,99999],memberSlot=16)
  failure['reason']['stageCode']=6;failure['reason']['sourceFrames']=[{'fileCode':6,'line':100000}for _ in range(8)];failure['reason']['sourceFramesTruncated']=True
  diag['failures']=[copy.deepcopy(failure)for _ in range(4)]
  observed=copy.deepcopy(failure['reason']);observed.update(nativeCode=12,filesystemCode=None,observedLinkCount=None)
  raw.update(sdkGatePassed=False,stage=6,failureCode=12,failureObservation=observed,sdkCandidateObservation=diag)
  raw['phaseActiveObservations']=[{'firstRootExitCodeBeforeCleanup':4294967295,'lastRootWaitBeforeCleanup':0,'lastJobMemberCountBeforeCleanup':128}for _ in range(5)]
  outer={'completed':False,'cleanupProved':True,'forcedCleanup':False,'exitCode':2}
  top=entry.failure_observation(entry.CiFailure(5),12);top.update(sourceFrames=[{'fileCode':6,'line':100000}for _ in range(8)],sourceLocationKnown=True,sourceFramesTruncated=True)
  report=entry.public_report(entry.require_context(fixtures.environment(),'x64'),outer,raw,failure=5,observation=top,command_binding=raw['commandProcessorBinding'])
  self.assertLessEqual(len(json.dumps(report,separators=(',',':')).encode()),8192)
  self.assertLessEqual(len(json.dumps(raw,separators=(',',':')).encode()),16384)
  self.assertFalse(report['sdkGatePassed']);self.assertTrue(report['nativeSdkCompiled']);self.assertTrue(report['nativeLinked'])
  self.assertEqual(len(report['helperPhaseResults']),5);self.assertEqual(report['helperFailureCode'],12)
 def test_worst_shape_full_success_and_truncated_failures_stay_below8192(self):
  raw=fixtures.success_fixture();diag=sample();diag['failureCount']=2147483647;diag['truncated']=True
  failure=copy.deepcopy(diag['failures'][0]);failure['version']=[10,0,999999,99999]
  failure['reason']['sourceFrames']=[{'fileCode':6,'line':100000}for _ in range(8)];failure['reason']['sourceFramesTruncated']=True
  diag['failures']=[copy.deepcopy(failure)for _ in range(4)];diag['operations'][0]['candidateCount']=2147483647
  raw['sdkCandidateObservation']=diag;outer={'completed':True,'cleanupProved':True,'forcedCleanup':False,'exitCode':0}
  value=entry.public_report(entry.require_context(fixtures.environment(),'x64'),outer,raw,command_binding=raw['commandProcessorBinding'])
  self.assertLessEqual(len(json.dumps(value,separators=(',',':')).encode()),8192);self.assertTrue(value['sdkGatePassed'])
  raw.update(sdkGatePassed=False,stage=1,failureCode=12,nativeSdkCompiled=False,nativeLinked=False,negativeSmokePassed=False)
  value=entry.public_report({},None,raw,failure=5);self.assertLessEqual(len(json.dumps(value,separators=(',',':')).encode()),8192)
  self.assertFalse(value['sdkGatePassed']);self.assertFalse(value['nativeSdkCompiled'])

if __name__=='__main__':unittest.main()
