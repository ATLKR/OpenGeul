import copy
import sys
from pathlib import Path
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import ci_entry as entry
import test_ci_wiring as fixtures
import test_command_lease_wiring as wiring


def observation(stage=1):
    return {'stageCode':stage,'exceptionKnown':True,'exceptionTypeCode':2,'nativeCode':12,
      'errno':None,'winerror':None,'filesystemCode':None,'fileRoleCode':None,'observedLinkCount':None,
      'sourceFrames':[{'fileCode':6,'line':94}],'sourceLocationKnown':True,'sourceFramesTruncated':False}


def failed_raw():
    import run_sdk_gate
    value=run_sdk_gate.empty_receipt()
    value.update(stage=1,failureCode=12,approvedCodeManifestSha256='1'*64,failureObservation=observation())
    return value


def phase():
    return {'startedAt':1.,'deadline':16.,'finishedAt':17.,'completed':False,'cleanupProved':False,
      'forcedCleanup':False,'rootExitObserved':False,'jobEmptyObserved':False,'identityRechecked':False,
      'exitCode':0,'pid':0,'creation':0,'failureCode':10,'cancelled':False,'handlesClosed':0}


class HelperFailureObservationTests(unittest.TestCase):
    def test_unobserved_private_report_keeps_every_helper_field_null(self):
        value=entry.public_report({},None,None,failure=5)
        self.assertEqual(value['schemaVersion'],5)
        for key in ('helperFailureCode','helperPhaseResults','helperFailureObservation'):
            self.assertIsNone(value[key])
        self.assertIsNone(value['nativeSdkCompiled']);self.assertFalse(value['sdkReportKnown'])

    def test_known_helper_failure_is_separate_from_outer_failure(self):
        raw=failed_raw();outer_observation=entry.failure_observation(entry.CiFailure(5),12)
        value=entry.public_report({},None,raw,failure=5,observation=outer_observation)
        self.assertEqual(value['failureCode'],5);self.assertEqual(value['failureObservation'],outer_observation)
        self.assertEqual(value['helperFailureCode'],12);self.assertEqual(value['helperFailureObservation'],observation())
        self.assertEqual(value['helperPhaseResults'],[]);self.assertFalse(value['nativeSdkCompiled'])
        self.assertFalse(value['sdkGatePassed']);self.assertFalse(value['qualification'])

    def test_partial_returned_phase_preserves_unknown_exit_identity_and_late_finish(self):
        raw=failed_raw();raw['phaseResults']=[phase()];before=copy.deepcopy(raw)
        value=entry.public_report({},None,raw,failure=5)
        result=value['helperPhaseResults'][0]
        self.assertIsNone(result['exitCode']);self.assertIsNone(result['pid']);self.assertIsNone(result['creation'])
        self.assertEqual(result['finishedAt'],17.);self.assertFalse(result['completed'])
        self.assertEqual(raw,before);self.assertFalse(value['nativeSdkCompiled'])
        self.assertNotIn('attempts',value);self.assertEqual(value['helperFailureCode'],12)

    def test_observed_nonzero_phase_identity_and_exit_zero_remain_observations(self):
        raw=failed_raw();row=phase();row.update(rootExitObserved=True,exitCode=0,pid=123,creation=456)
        raw['phaseResults']=[row]
        value=entry.public_report({},None,raw,failure=5)
        self.assertEqual(value['helperPhaseResults'][0]['exitCode'],0)
        self.assertEqual(value['helperPhaseResults'][0]['pid'],123)
        self.assertFalse(value['nativeSdkCompiled']);self.assertFalse(value['negativeSmokePassed'])

    def test_helper_observation_rejects_open_fields_invalid_types_and_stage(self):
        mutations=[{'message':'SYNTHETIC'},{'path':'SYNTHETIC'},{'stageCode':2},{'stageCode':True},
          {'exceptionTypeCode':True},{'exceptionKnown':False},{'sourceFrames':[{'fileCode':7,'line':1}]},
          {'sourceFrames':[{'fileCode':6,'line':0}]},{'sourceLocationKnown':False},
          {'sourceFrames':[{'fileCode':6,'line':1,'path':'SYNTHETIC'}]}, {'winerror':2.0},
          {'nativeCode':-1},{'fileRoleCode':4},{'observedLinkCount':1048577},
          {'filesystemCode':0},{'sourceFramesTruncated':0}]
        for delta in mutations:
            with self.subTest(case=mutations.index(delta)):
                raw=failed_raw();raw['failureObservation'].update(delta)
                with self.assertRaises(entry.CiFailure):entry.public_report({},None,raw,failure=5)
                with self.assertRaises(entry.CiFailure):entry.validate_sdk_report(raw,'x64','1'*64,180.)

    def test_helper_packet_cannot_claim_codes_for_an_unrelated_exception_class(self):
        for delta in ({'exceptionTypeCode':0,'exceptionKnown':False},
          {'errno':2},{'winerror':2},{'exceptionTypeCode':1,'filesystemCode':4},
          {'exceptionTypeCode':3,'fileRoleCode':2},{'exceptionTypeCode':4,'observedLinkCount':2},
          {'sourceFramesTruncated':True}):
            raw=failed_raw();raw['failureObservation'].update(delta)
            with self.subTest(case=list(delta)),self.assertRaises(entry.CiFailure):entry.public_report({},None,raw,failure=5)

    def test_phase_projection_rejects_arbitrary_fields_ranges_and_nonfinite(self):
        changes=[{'argv':'SYNTHETIC'},{'failureCode':32},{'handlesClosed':5},{'completed':1},
          {'exitCode':-1},{'pid':True},{'creation':2**63},{'startedAt':float('nan')},
          {'deadline':32.},{'rootExitObserved':True,'pid':1,'creation':0}, {'pid':1,'creation':0}]
        for index,delta in enumerate(changes):
            with self.subTest(case=index):
                raw=failed_raw();raw['phaseResults']=[{**phase(),**delta}]
                with self.assertRaises(entry.CiFailure):entry.public_report({},None,raw,failure=5)
        raw=failed_raw();raw['phaseResults']=[phase()]*6
        with self.assertRaises(entry.CiFailure):entry.public_report({},None,raw,failure=5)

    def test_helper_code_cannot_be_boolean_out_of_range_or_unvalidated(self):
        for replacement in (True,-1,32,'12'):
            raw=failed_raw();raw['failureCode']=replacement
            with self.assertRaises(entry.CiFailure):entry.public_report({},None,raw,failure=5)

    def test_helper_actual_except_captures_only_existing_source_frames(self):
        import run_sdk_gate as gate
        import approved_launch
        from supervisor import GateFailure
        context=types.SimpleNamespace(manifest_sha256='1'*64)
        with mock.patch.object(approved_launch,'require_admission',return_value=context), \
          mock.patch.object(gate,'sys',types.SimpleNamespace(platform='win32')), \
          mock.patch.object(gate.tools,'verify_bundle',return_value={}), \
          mock.patch.object(gate,'_owned_root',side_effect=GateFailure(12)):
            raw=gate.execute('x64',ROOT/'frozen-v2',ROOT/'not-created')
        self.assertEqual(raw['failureCode'],12);self.assertEqual(raw['stage'],1)
        value=raw['failureObservation'];self.assertEqual(value['exceptionTypeCode'],2)
        self.assertEqual(value['nativeCode'],12);self.assertEqual(value['stageCode'],1)
        self.assertTrue(value['sourceLocationKnown'])
        self.assertEqual({row['fileCode'] for row in value['sourceFrames']},{6})
        self.assertFalse(raw['workRootCreated']);self.assertEqual(raw['phaseResults'],[])

    def test_actual_cancelled_runner_keeps_no_returned_phases_and_closes_lease(self):
        fixture=wiring.CommandLeaseWiringTests()
        events,lease,raw=fixture.helper(cancel=True)
        self.assertEqual(lease.close_count,1);self.assertTrue(raw['cancelled'])
        self.assertEqual(raw['phaseResults'],[]);self.assertIsNotNone(raw['failureObservation'])
        value=entry.public_report({},None,raw,failure=5)
        self.assertEqual(value['helperPhaseResults'],[]);self.assertFalse(value['nativeSdkCompiled'])
        self.assertFalse(value['sdkGatePassed'])

    def test_full_numeric_helper_projection_remains_inside_existing_public_size_cap(self):
        import json
        raw=fixtures.success_fixture();raw['sdkGatePassed']=False;raw['failureObservation']=observation(7)
        raw['failureObservation']['sourceFrames']=[{'fileCode':6,'line':100000} for unused in range(8)]
        raw['failureObservation']['sourceFramesTruncated']=True
        outer={'completed':False,'cleanupProved':True,'forcedCleanup':False,'exitCode':2}
        report=entry.public_report(entry.require_context(fixtures.environment(),'x64'),outer,raw,failure=5,
          observation=entry.failure_observation(entry.CiFailure(5),12),command_binding=wiring.binding())
        self.assertLess(len(json.dumps(report,separators=(',',':')).encode()),8192)
        self.assertFalse(report['sdkGatePassed']);self.assertFalse(report['qualification'])

    def test_workflow_embeds_the_exact_powershell_schema_exercised_by_regression(self):
        import hashlib,re,textwrap,yaml
        workflow=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-suite.yml').read_bytes())
        script=next(step['run'] for step in workflow['jobs']['packaged-context-sdk']['steps'] if step.get('id')=='sdk-compile')
        lines=script.splitlines();start=next(i for i,line in enumerate(lines) if line.strip()=='# Pure schema-4 fragment. The caller supplies the already-parsed $report.')
        end=next(i for i in range(start,len(lines)) if lines[i].strip()=='} $report')
        fragment=textwrap.dedent('\n'.join(lines[start:end+1]))+'\n'
        self.assertEqual(hashlib.sha256(fragment.encode()).hexdigest(),'4a502fc4e1de30691442e3cb2f923274052db4523d335c58c68ef5e7cb343dae')
        keys=re.search(r"\$keys = @\(([^\n]+)\)",script).group(1)
        self.assertEqual(set(re.findall(r"'([^']+)'",keys)),set(entry.public_report({},None,None)))
        self.assertIn('$report.schemaVersion -ne 5 -or',script)
        self.assertNotIn('$report.schemaVersion -ne 3 -or',script)

    def test_actual_success_still_requires_every_existing_private_gate(self):
        raw=fixtures.success_fixture()
        raw['failureObservation']=None
        self.assertIs(entry.validate_sdk_report(raw,'x64','1'*64,180.,raw['compileInputs']),raw)
        raw['nativeSdkCompiled']=False
        with self.assertRaises(entry.CiFailure):entry.validate_sdk_report(raw,'x64','1'*64,180.,raw['compileInputs'])

if __name__=='__main__':unittest.main()
