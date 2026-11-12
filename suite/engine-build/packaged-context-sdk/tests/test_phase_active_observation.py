"""Synthetic active-loop evidence; no real process, command or SDK execution."""
import copy
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import supervisor
import ci_entry as entry
import run_sdk_gate as gate
from test_supervisor import Clock,KernelPort

FIELDS={'firstRootExitCodeBeforeCleanup','lastRootWaitBeforeCleanup','lastJobMemberCountBeforeCleanup'}
EMPTY={key:None for key in FIELDS}

class CountClock(Clock):
    def __init__(self):super().__init__();self.reads=0
    def __call__(self):self.reads+=1;return super().__call__()

class Port(KernelPort):
    def __init__(self,clock,mode):super().__init__(clock,mode);self.calls=[]
    def identity(self,*args):self.calls.append(1);return super().identity(*args)
    def state(self,*args):
        self.calls.append(2)
        if self.mode=='exit-error-descendant' and not self.terminated:return 0,2
        return super().state(*args)
    def member(self,*args):self.calls.append(3);return super().member(*args)
    def census(self,*args):
        self.calls.append(4)
        if self.mode=='exit-error-descendant' and not self.terminated:return (201,)
        if self.mode=='late-census' and not self.terminated:self.clock.value+=2.1;return ()
        if self.mode=='bad-census' and not self.terminated:return (201,201)
        return super().census(*args)

class ActiveLoopObservationTests(unittest.TestCase):
    def run_case(self,mode,observe):
        c=CountClock();p=Port(c,mode);sink={}
        env=supervisor.child_environment(r'C:\Windows',r'C:\Program Files',r'C:\Program Files (x86)',r'C:\owned')
        args=([r'C:\Windows\System32\cmd.exe','/d','/c','phase.cmd'],r'C:\owned',env,3.)
        kwargs={}
        if observe:
            self.assertIn('active_observation',inspect.signature(supervisor.Runner.run).parameters)
            kwargs['active_observation']=sink
        row=supervisor.Runner(p,clock=c,pause=c.pause).run(*args,**kwargs)
        return row,sink,p,c

    def test_first_root_error_precedes_forced_descendant_cleanup(self):
        row,sink,p,c=self.run_case('exit-error-descendant',True)
        self.assertEqual(sink,dict(firstRootExitCodeBeforeCleanup=2,lastRootWaitBeforeCleanup=0,lastJobMemberCountBeforeCleanup=1))
        self.assertFalse(row['completed']);self.assertEqual(row['failureCode'],10)
        self.assertTrue(row['forcedCleanup']);self.assertEqual(row['exitCode'],1)
        self.assertEqual(p.kills,1)

    def test_live_root_is_not_relabelled_from_final_cleanup(self):
        row,sink,p,c=self.run_case('hang',True)
        self.assertEqual(sink,dict(firstRootExitCodeBeforeCleanup=None,lastRootWaitBeforeCleanup=258,lastJobMemberCountBeforeCleanup=2))
        self.assertEqual(row['exitCode'],1);self.assertTrue(row['rootExitObserved'])

    def test_no_active_loop_remains_three_nulls(self):
        row,sink,p,c=self.run_case('failed',True)
        self.assertEqual(sink,EMPTY);self.assertTrue(row['forcedCleanup'])

    def test_state_survives_late_census_without_cleanup_backfill(self):
        row,sink,p,c=self.run_case('late-census',True)
        self.assertEqual(sink,dict(firstRootExitCodeBeforeCleanup=0,lastRootWaitBeforeCleanup=0,lastJobMemberCountBeforeCleanup=None))
        self.assertEqual(row['failureCode'],10)

    def test_invalid_census_does_not_become_known_count(self):
        row,sink,p,c=self.run_case('bad-census',True)
        self.assertEqual(sink['lastJobMemberCountBeforeCleanup'],None)
        self.assertEqual(row['failureCode'],7)

    def test_observation_adds_no_api_clock_or_result_changes(self):
        for mode in ('exit','error','descendant','hang','failed','generation','late-census','bad-census','exit-error-descendant'):
            with self.subTest(mode=mode):
                a,unused,pa,ca=self.run_case(mode,False)
                b,sink,pb,cb=self.run_case(mode,True)
                self.assertEqual(a,b);self.assertEqual(pa.calls,pb.calls);self.assertEqual(ca.reads,cb.reads)
                self.assertEqual(pa.events,pb.events);self.assertEqual(pa.closed,pb.closed)
                self.assertEqual(set(b),{'startedAt','deadline','finishedAt','completed','cleanupProved','forcedCleanup','rootExitObserved','jobEmptyObserved','identityRechecked','exitCode','pid','creation','failureCode','cancelled','handlesClosed'})
                self.assertEqual(set(sink),FIELDS)

    def test_untrusted_mapping_is_not_called_and_cannot_change_primary(self):
        self.assertIn('active_observation',inspect.signature(supervisor.Runner.run).parameters)
        class Poison(dict):
            def update(self,*args,**kwargs):raise AssertionError('SYNTHETIC')
            def __iter__(self):raise AssertionError('SYNTHETIC')
            def __bool__(self):raise AssertionError('SYNTHETIC')
        c=CountClock();p=Port(c,'error');sink=Poison()
        env=supervisor.child_environment(r'C:\Windows',r'C:\Program Files',r'C:\Program Files (x86)',r'C:\owned')
        row=supervisor.Runner(p,clock=c,pause=c.pause).run([r'C:\Windows\System32\cmd.exe'],r'C:\owned',env,3.,active_observation=sink)
        self.assertEqual(row['failureCode'],8);self.assertEqual(dict.__len__(sink),0)
        self.assertTrue(row['cleanupProved'])

class ActiveObservationProtocolTests(unittest.TestCase):
    def validator(self):
        self.assertTrue(hasattr(entry,'validate_phase_active_observations'))
        return entry.validate_phase_active_observations

    def test_exact_ordinal_join_and_no_sample_are_explicit(self):
        validate=self.validator();a=copy.deepcopy(EMPTY)
        b=dict(firstRootExitCodeBeforeCleanup=2,lastRootWaitBeforeCleanup=0,lastJobMemberCountBeforeCleanup=1)
        source=[a,b]
        value=validate(source,2);self.assertEqual(value,source);self.assertIsNot(value,source)
        self.assertIsNot(value[0],source[0])
        self.assertEqual(validate([None],1),[None])
        self.assertIsNone(validate(None,1))

    def test_unknown_types_ranges_keys_and_ordinal_mismatch_reject(self):
        validate=self.validator()
        bad=[True,{},[EMPTY]*6,[EMPTY,EMPTY],['SYNTHETIC'],[{**EMPTY,'unknown':0}]]
        for key,values in (("firstRootExitCodeBeforeCleanup",(True,-1,2**32,259,0.0)),("lastRootWaitBeforeCleanup",(False,1,257,259,258.0)),("lastJobMemberCountBeforeCleanup",(True,-1,129,0.0))):
            bad.extend([[{**EMPTY,key:value}] for value in values])
        for value in bad:
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(entry.CiFailure):validate(value,1)

    def test_packet_cannot_grant_sdk_or_product_success(self):
        raw=gate.empty_receipt();raw.update(stage=3,failureCode=10,phaseResults=[],phaseActiveObservations=[],approvedCodeManifestSha256='1'*64)
        value=entry.public_report({},None,raw,failure=5)
        self.assertEqual(value['schemaVersion'],6);self.assertEqual(value['helperPreCleanup'],[])
        self.assertFalse(value['sdkGatePassed']);self.assertFalse(value['nativeSdkCompiled'])
        self.assertFalse(value['qualification']);self.assertFalse(value['canService'])

    def test_current_raw_protocol_requires_observation_packet(self):
        self.assertEqual(gate.empty_receipt()['schemaVersion'],2)
        self.assertEqual(gate.empty_receipt()['phaseActiveObservations'],[])

    def test_public_packet_unknown_when_no_helper_returned(self):
        value=entry.public_report({},None,None,failure=5)
        self.assertEqual(value['schemaVersion'],6)
        self.assertIsNone(value['helperPreCleanup'])

    def test_current_raw_cannot_downgrade_or_omit_new_packet(self):
        import test_ci_wiring as fixtures
        raw=fixtures.success_fixture()
        for delta in ('old','missing','ordinal'):
            value=copy.deepcopy(raw)
            if delta=='old':value['schemaVersion']=1
            elif delta=='missing':del value['phaseActiveObservations']
            else:value['phaseActiveObservations'].pop()
            with self.subTest(delta=delta),self.assertRaises(entry.CiFailure):
                entry.validate_sdk_report(value,'x64','1'*64,180.,raw['compileInputs'])

    def test_diagnostic_validator_failure_keeps_original_result_and_cleanup(self):
        import test_command_lease_wiring as wiring
        for failure in (RuntimeError('SYNTHETIC'),MemoryError()):
            with mock.patch.object(entry,'validate_phase_active_observations',side_effect=failure):
                events,lease,raw=wiring.CommandLeaseWiringTests().helper()
            self.assertTrue(raw['sdkGatePassed']);self.assertEqual(lease.close_count,1)
            self.assertIsNone(raw['phaseActiveObservations'])
            self.assertEqual(len(raw['phaseResults']),5)

    def test_returned_phase_and_packet_survive_original_post_lease_failure(self):
        import test_command_lease_wiring as wiring
        original=wiring.Lease.verify
        def verify(lease,*,deadline=None):
            if any(row[0]=='run'for row in lease.events):raise supervisor.GateFailure(10)
            return original(lease,deadline=deadline)
        with mock.patch.object(wiring.Lease,'verify',verify),mock.patch.object(entry,'validate_phase_active_observations',side_effect=MemoryError()):
            events,lease,raw=wiring.CommandLeaseWiringTests().helper()
        self.assertEqual(raw['failureCode'],10);self.assertEqual(lease.close_count,1)
        self.assertFalse(raw['sdkGatePassed']);self.assertEqual(len(raw['phaseResults']),1)
        self.assertIsNone(raw['phaseActiveObservations'])

    def test_diagnostic_storage_failure_cannot_replace_returned_command_result(self):
        import test_command_lease_wiring as wiring
        class FailingAppend(list):
            def append(self,value):raise MemoryError()
        class FailingAssign(list):
            def __setitem__(self,index,value):raise MemoryError()
        original=gate.empty_receipt
        for cls in (FailingAppend,FailingAssign):
            def receipt():
                value=original();value['phaseActiveObservations']=cls();return value
            with mock.patch.object(gate,'empty_receipt',receipt):
                events,lease,raw=wiring.CommandLeaseWiringTests().helper()
            self.assertTrue(raw['sdkGatePassed']);self.assertEqual(lease.close_count,1)
            self.assertEqual(len(raw['phaseResults']),5);self.assertIsNone(raw['phaseActiveObservations'])

    def test_diagnostic_storage_failure_cannot_skip_original_post_lease_failure(self):
        import test_command_lease_wiring as wiring
        class FailingAppend(list):
            def append(self,value):raise MemoryError()
        original=gate.empty_receipt;original_verify=wiring.Lease.verify
        def receipt():
            value=original();value['phaseActiveObservations']=FailingAppend();return value
        def verify(lease,*,deadline=None):
            if any(row[0]=='run'for row in lease.events):raise supervisor.GateFailure(10)
            return original_verify(lease,deadline=deadline)
        with mock.patch.object(gate,'empty_receipt',receipt),mock.patch.object(wiring.Lease,'verify',verify):
            events,lease,raw=wiring.CommandLeaseWiringTests().helper()
        self.assertEqual(raw['failureCode'],10);self.assertEqual(lease.close_count,1)
        self.assertEqual(len(raw['phaseResults']),1);self.assertIsNone(raw['phaseActiveObservations'])

    def test_native_stdio_and_source13_are_unchanged(self):
        import hashlib
        self.assertEqual(hashlib.sha256((ROOT/'owned_job_win32.py').read_bytes()).hexdigest(),'1e2ae98c59e7fb552548f876c6a13566e082eced74f154ee15061715ae8ebb1c')
        import toolchain
        self.assertTrue(toolchain.verify_bundle(ROOT/'frozen-v2'))

    def test_independent_powershell_reader_matches_closed_packets(self):
        import yaml
        w=yaml.safe_load((ROOT.parents[2]/'.github/workflows/office-suite.yml').read_bytes())
        source=next(row['run']for row in w['jobs']['packaged-context-sdk']['steps']if row.get('id')=='sdk-compile')
        start=source.index('&{\nparam($a,$n,$b)')
        end=source.index('} $report.helperPreCleanup $report.helperPhaseResults.Count $report.sdkReportKnown',start)
        end+=len('} $report.helperPreCleanup $report.helperPhaseResults.Count $report.sdkReportKnown')
        fragment=source[start:end]
        cases=[([copy.deepcopy(EMPTY)],1,True,True),([None],1,True,True),([],0,True,True),(None,0,False,True),(None,1,True,True),([EMPTY],1,False,False),
          ([dict(firstRootExitCodeBeforeCleanup=2,lastRootWaitBeforeCleanup=0,lastJobMemberCountBeforeCleanup=1)],1,True,True),
          ([dict(firstRootExitCodeBeforeCleanup=None,lastRootWaitBeforeCleanup=258,lastJobMemberCountBeforeCleanup=128)],1,True,True),
          ([dict(firstRootExitCodeBeforeCleanup=0,lastRootWaitBeforeCleanup=0,lastJobMemberCountBeforeCleanup=None)],1,True,True)]
        bad=[True,{},[EMPTY,EMPTY],['SYNTHETIC'],[{**EMPTY,'unknown':0}]]
        for key,values in (('firstRootExitCodeBeforeCleanup',(True,-1,2**32,259,0.0)),('lastRootWaitBeforeCleanup',(False,1,257,259,258.0)),('lastJobMemberCountBeforeCleanup',(True,-1,129,0.0))):
            bad.extend([[{**EMPTY,key:v}]for v in values])
        cases.extend((rows,1,True,False)for rows in bad)
        encoded=json.dumps([{'rows':rows,'count':count,'known':known,'accepted':accepted}for rows,count,known,accepted in cases],separators=(',',':'),allow_nan=False)
        code="$ErrorActionPreference='Stop'\n$cases=ConvertFrom-Json @'\n"+encoded+"\n'@\n$ordinal=0\nforeach($case in $cases){\n$ordinal++\n$report=[pscustomobject]@{helperPreCleanup=$case.rows;helperPhaseResults=[object[]]::new([int]$case.count);sdkReportKnown=$case.known}\n$accepted=$true\ntry{\n"+fragment+"\n}catch{$accepted=$false}\nif($accepted -ne $case.accepted){exit ([int]$ordinal)}\n}\nexit 0\n"
        shell=shutil.which('pwsh');self.assertIsNotNone(shell,'Existing PowerShell required')
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);script=root/'closed-reader.ps1';script.write_text(code)
            environment={'PATH':str(Path(shell).parent)+os.pathsep+'/usr/bin'+os.pathsep+'/bin',
              'XDG_CACHE_HOME':str(root/'cache'),'XDG_CONFIG_HOME':str(root/'config'),'XDG_DATA_HOME':str(root/'data')}
            if os.name=='nt':environment['SystemRoot']=r'C:\Windows'
            result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(script)],env=environment,
              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        self.assertEqual(result.returncode,0)

if __name__=='__main__':unittest.main()
