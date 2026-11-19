"""Synthetic-only bundled-tool observation contracts; no Windows tool execution."""
import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'e2e'))
SPEC = importlib.util.spec_from_file_location('bundled_probe_tested',ROOT/'e2e/vs_bundled_clang_probe.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

def stable_ast_dump(node,*,dump=None):
    dump=ast.dump if dump is None else dump
    options={'include_attributes':False}
    if 'show_empty' in inspect.signature(dump).parameters:options['show_empty']=True
    return dump(node,**options)

def executable(machine=0x8664):
    value=bytearray(64+24+112)
    value[:2]=b'MZ'
    struct.pack_into('<I',value,60,64)
    value[64:68]=b'PE\0\0'
    struct.pack_into('<HHIIIHH',value,68,machine,1,0,0,0,112,2)
    struct.pack_into('<H',value,88,0x20b)
    return bytes(value)

class Clock:
    value=100.
    def __call__(self):return self.value
    def sleep(self,seconds):self.value+=seconds

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bundled-probe-synthetic-',dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.windows=self.root/'Windows';(self.windows/'System32').mkdir(parents=True)
        (self.windows/'System32/cmd.exe').write_bytes(executable())
        self.suite=self.root/'Suite';self.suite.mkdir()
        self.host=self.root/'python.exe';self.host.write_bytes(executable())
        self.vswhere=self.root/'programs/Microsoft Visual Studio/Installer/vswhere.exe'
        self.vswhere.parent.mkdir(parents=True);self.vswhere.write_bytes(b'fixed discovery fixture')
        self.install=self.root/'VS'
        build=self.install/'VC/Auxiliary/Build';build.mkdir(parents=True)
        (build/'vcvarsall.bat').write_bytes(b'fixed vcvars fixture')
        (build/'Microsoft.VCToolsVersion.default.txt').write_bytes(b'14.51.36231\n')
        self.tools=self.install/'VC/Tools/Llvm/x64/bin';self.tools.mkdir(parents=True)
        for name in ('clang-cl.exe','lld-link.exe'):(self.tools/name).write_bytes(executable())
        self.source=self.root/'source';self.source.mkdir()
        for name in m.prep.SOURCES:(self.source/name).write_bytes(('synthetic '+name).encode())
        self.output=self.root/'private';self.report=self.root/'public/report.numeric.json'
        self.clock=Clock();self.calls=[];self.versions=[(22,1),(22,1)]
        self.after_query=None;self.bad_stage=False;self.helper_mutation=None
        self.runtime=SimpleNamespace(processes=[],pending_handles=lambda:0)
        for p in (patch.object(m.prep,'SOURCE_ROOT',self.source),
                  patch.object(m.prep.time,'monotonic',self.clock),
                  patch.object(m.prep.time,'sleep',self.clock.sleep),
                  patch.object(m.prep.native_arch,'observe_native_architecture',return_value=dict(processMachine=0,nativeMachine=0x8664,processArchitecture='x64',nativeArchitecture='x64')),
                  patch.object(m,'_run_stage',side_effect=self.stage),
                  patch.object(m.sys,'executable',str(self.host)),
                  patch.object(os,'environ',{'COMSPEC':str(self.windows/'System32/cmd.exe')})):
            p.start();self.addCleanup(p.stop)

    def stage(self,runtime,folder,stage,script,budget,receipt,arguments):
        budget.now()
        request=json.loads(Path(arguments[2]).read_bytes())
        self.calls.append(request)
        kind=request['kindCode']
        row=dict(stage=stage,identity=dict(pid=80+kind,creationTime=134395652231767531),
                 queryCount=1,natural=not self.bad_stage,handlesClosed=not self.bad_stage,cleanupErrors=[],
                 samples=[dict(querySucceeded=True,returnLength=48,activeProcesses=int(self.bad_stage),
                               totalProcesses=3,terminatedProcesses=0,rawHex=(bytes(36)+struct.pack('<III',3,int(self.bad_stage),0)).hex(),
                               root=dict(waitResult=0,exitCode=0))])
        receipt['stages'].append(row)
        if self.bad_stage:raise AssertionError('synthetic unretired Job')
        major,minor=self.versions[kind-1] if kind else (None,None)
        value=dict(schemaVersion=1,kindCode=kind,resultCode=0,exitCode=0,major=major,minor=minor,
                   selectedRoot=str(self.install) if kind==0 else None,stdoutBytes=64,stderrBytes=0,
                   timedOut=False,outputCapReached=False,pid=180+kind,creationTime=134395652231767531,
                   imageMatched=True,naturalExit=True,handlesClosed=True,captureObservation=m.helper_module.capture_observation(),
                   discoveryParseStage=5 if kind==0 else 0)
        if self.helper_mutation:self.helper_mutation(value,kind)
        Path(arguments[3]).write_text(json.dumps(value))
        if self.after_query:self.after_query(kind)

    def run_probe(self,**kwargs):
        return m.run_probe(self.output,self.report,suite=self.suite,windows=self.windows,vswhere=self.vswhere,
            host_python=self.host,expected_suite_source_commit='2fb399913b60617e7e1a7270e93378de787a609d',
            runtime_factory=lambda environment:self.runtime,**kwargs)

    def test_two_version_calls_once_and_diagnostic_never_accepts(self):
        value=self.run_probe()
        self.assertEqual(value['resultCode'],0)
        self.assertEqual([x['kindCode'] for x in self.calls],[0,1,2])
        self.assertEqual(value['discoveryRequests'],1)
        self.assertEqual(value['versionRequestsTotal'],2)
        self.assertTrue(value['diagnosticOnly'])
        self.assertFalse(value['acceptance'])
        self.assertFalse(value['productionQualified'])
        self.assertTrue(value['observedComplete'])
        self.assertTrue(value['majorSupported'])
        self.assertFalse(value['productionBudgetChanged'])
        self.assertEqual((value['workLimitMs'],value['totalLimitMs']),(27000,30000))
        self.assertTrue(value['sourcePinsBeforeAfterEqual'])
        self.assertTrue(all(x['pinsEqual'] and x['statJoinMatched'] and x['naturalJob'] and x['jobEmpty'] and x['handlesClosed'] for x in value['tools']))
        self.assertEqual(json.loads(self.report.read_bytes()),value)
        m.validate_report(value)

    def test_old_major_is_observation_without_fallback(self):
        self.versions=[(21,1),(21,1)]
        value=self.run_probe()
        self.assertEqual(value['resultCode'],7)
        self.assertEqual([x['kindCode'] for x in self.calls],[0,1,2])
        self.assertFalse(value['majorSupported'])
        self.assertTrue(value['observedComplete'])
        self.assertFalse(value['majorSupported'])

    def test_missing_compiler_does_not_run_an_alternative(self):
        (self.tools/'clang-cl.exe').unlink()
        value=self.run_probe()
        self.assertEqual(value['resultCode'],3)
        self.assertEqual([x['kindCode'] for x in self.calls],[0,2])
        self.assertEqual(value['versionRequestsTotal'],1)
        self.assertTrue(value['tools'][0]['knownUnavailable'])
        self.assertTrue(value['tools'][1]['majorSupported'])
        self.assertTrue(value['observedComplete'])

    def test_missing_linker_preserves_supported_compiler_observation(self):
        (self.tools/'lld-link.exe').unlink()
        value=self.run_probe()
        self.assertEqual(value['resultCode'],3)
        self.assertEqual([x['kindCode'] for x in self.calls],[0,1])
        self.assertTrue(value['tools'][0]['majorSupported'])
        self.assertTrue(value['tools'][1]['knownUnavailable'])
        self.assertIsNone(value['tools'][1]['majorSupported'])
        self.assertIsNone(value['majorSupported'])
        self.assertFalse(value['productionQualified'])

    def test_foreign_machine_is_rejected_before_version(self):
        (self.tools/'clang-cl.exe').write_bytes(executable(0xaa64))
        value=self.run_probe()
        self.assertEqual(value['resultCode'],4)
        self.assertEqual([x['kindCode'] for x in self.calls],[0,2])

    def test_changed_tool_invalidates_observation(self):
        def change(kind):
            if kind==2:
                path=self.tools/'clang-cl.exe';path.write_bytes(path.read_bytes()+b'x')
        self.after_query=change
        self.assertEqual(self.run_probe()['resultCode'],8)

    def test_changed_source_invalidates_observation(self):
        def change(kind):
            if kind==2:(self.source/m.prep.SOURCES[0]).write_bytes(b'changed synthetic source')
        self.after_query=change
        self.assertEqual(self.run_probe()['resultCode'],11)

    def test_root_exit_does_not_replace_job_empty(self):
        self.bad_stage=True
        value=self.run_probe()
        self.assertEqual(value['resultCode'],5)
        self.assertFalse(value['stages'][0]['jobEmpty'])

    def test_deadline_is_not_reset_between_version_calls(self):
        def late(kind):
            if kind==1:self.clock.value=127.
        self.after_query=late
        value=self.run_probe()
        self.assertEqual(value['resultCode'],9)
        self.assertEqual([x['kindCode'] for x in self.calls],[0,1])
        self.assertEqual(value['versionRequestsTotal'],1)
        self.assertIsNone(value['tools'][1]['majorSupported'])

    def test_helper_result_cannot_supply_unbounded_or_boolean_version(self):
        self.helper_mutation=lambda value,kind:value.update(major=True) if kind else None
        self.assertEqual(self.run_probe()['resultCode'],6)

    def test_report_rejects_strings_and_acceptance(self):
        value=self.run_probe()
        for mutant in ('string','acceptance','extra'):
            bad=copy.deepcopy(value)
            if mutant=='string':bad['tools'][0]['major']='22'
            elif mutant=='acceptance':bad['acceptance']=True
            else:bad['rawOutput']='forbidden'
            with self.subTest(mutant=mutant),self.assertRaises(AssertionError):m.validate_report(bad)

    def test_version_parser_projects_only_major_minor(self):
        h=m.helper_module
        self.assertEqual(h.parse_version(b'clang version 22.1.7 (synthetic public metadata)\nTarget: x86_64\n',1),(22,1))
        self.assertEqual(h.parse_version(b'LLD 23.1.6\n',2),(23,1))
        for raw in (b'other 22.1',b'clang version -22.1',b'clang version 1000.1',b'clang version 22.1\0',b'x'*4097):
            with self.subTest(rawKind=len(raw)),self.assertRaises(AssertionError):h.parse_version(raw,1)

    def test_environment_is_explicit_and_does_not_copy_real_mapping(self):
        class Sentinel(dict):
            def copy(self):raise AssertionError('real copy')
            def keys(self):raise AssertionError('real keys')
            def items(self):raise AssertionError('real items')
            def __iter__(self):raise AssertionError('real iteration')
            def get(self,*_):raise AssertionError('real get')
        temp=self.root/'temp';temp.mkdir()
        with patch.object(os,'environ',Sentinel()):
            value=m.finite_environment(self.windows,temp)
        self.assertEqual(set(value),{'COMSPEC','SystemRoot','WINDIR','PATH','TEMP','TMP','PYTHONUTF8','PYTHONDONTWRITEBYTECODE'})
        self.assertEqual(value['PATH'],str(self.windows/'System32'))

    def cached(self):
        folder=self.root/'cached';folder.mkdir()
        (folder/'discovery.stdout').write_bytes(str(self.install).encode())
        selection,_=m.prep._msvc_selection(self.install,'x64',lambda:None)
        raw=bytes(36)+struct.pack('<III',2,0,0)
        proof=dict(kind='ascii-message-observer-preparation',architecture='x64',
            sourcePins={name:m.prep._pin(self.source/name) for name in m.prep.SOURCES},
            stages=[dict(queryCount=1,natural=True,handlesClosed=True,cleanupErrors=[],
                identity=dict(pid=91,creationTime=134395652231767531),
                samples=[dict(querySucceeded=True,returnLength=48,rawHex=raw.hex(),
                    activeProcesses=0,totalProcesses=2,terminatedProcesses=0,root=dict(waitResult=0,exitCode=0))])],
            compiler=dict(mode='msvc',selection=selection))
        path=folder/'preparation.json';path.write_text(json.dumps(proof))
        return path

    def test_cached_exact_selection_does_not_query_vs_again(self):
        value=self.run_probe(cached_preparation=self.cached())
        self.assertEqual(value['resultCode'],0)
        self.assertEqual([x['kindCode'] for x in self.calls],[1,2])
        self.assertEqual([x['stageCode'] for x in value['stages']],[1,2])
        self.assertEqual(value['discoveryRequests'],0)
        self.assertTrue(value['cacheUsed'])

    def test_invalid_cache_does_not_fall_back_to_fresh_discovery(self):
        cached=self.cached();value=json.loads(cached.read_bytes());value['compiler']['selection']['toolsetVersion']='14.99.99999';cached.write_text(json.dumps(value))
        value=self.run_probe(cached_preparation=cached)
        self.assertEqual(value['resultCode'],13)
        self.assertEqual(self.calls,[])

    def test_arm_host_does_not_start_diagnostic_job(self):
        observed=dict(processMachine=0,nativeMachine=0xaa64,processArchitecture='arm64',nativeArchitecture='arm64')
        with patch.object(m.prep.native_arch,'observe_native_architecture',return_value=observed):
            value=self.run_probe()
        self.assertEqual(value['resultCode'],1)
        self.assertEqual(self.calls,[])

    def test_handle_close_failure_is_not_a_compatible_observation(self):
        self.runtime.pending_handles=lambda:1
        value=self.run_probe()
        self.assertEqual(value['resultCode'],10)
        self.assertEqual(value['pendingHandleCount'],1)
        self.assertFalse(value['majorSupported'])

    def test_partial_sha_nulls_and_before_pin_lies_are_rejected(self):
        value=self.run_probe()
        for mutation in ('null','before','after'):
            bad=copy.deepcopy(value)
            if mutation=='null':bad['tools'][0]['sha256Words'][0]=None
            elif mutation=='before':bad['tools'][0]['beforePinned']=False
            else:bad['tools'][0]['afterPinned']=False
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):m.validate_report(bad)

    def test_probe_never_writes_inside_product_payload(self):
        self.output=self.suite/'forbidden'
        with self.assertRaises(AssertionError):self.run_probe()
        self.assertEqual(self.calls,[])
        self.assertFalse(self.output.exists())

    def test_failed_version_preserves_child_exit_and_post_pins(self):
        def fail(value,kind):
            if kind==1:value.update(resultCode=4,exitCode=17,major=None,minor=None)
        self.helper_mutation=fail
        value=self.run_probe()
        self.assertEqual(value['resultCode'],5)
        self.assertEqual(value['tools'][0]['versionExit'],17)
        self.assertTrue(value['tools'][0]['naturalJob'])
        self.assertTrue(all(x['afterPinned'] and x['pinsEqual'] for x in value['tools']))
        self.assertEqual([x['kindCode'] for x in self.calls],[0,1,2])

    def test_nonzero_version_and_changed_file_keep_primary_and_secondary(self):
        def fail(value,kind):
            if kind==1:value.update(resultCode=4,exitCode=17,major=None,minor=None)
        def change(kind):
            if kind==1:
                path=self.tools/'lld-link.exe';path.write_bytes(path.read_bytes()+b'x')
        self.helper_mutation=fail;self.after_query=change
        value=self.run_probe()
        self.assertEqual(value['resultCode'],5)
        self.assertEqual(value['postPinResultCode'],8)
        self.assertEqual(value['tools'][0]['versionExit'],17)

    def test_invalid_cached_wait_result_is_not_natural_exit(self):
        cached=self.cached();value=json.loads(cached.read_bytes());value['stages'][0]['samples'][0]['root']['waitResult']=258;cached.write_text(json.dumps(value))
        self.assertEqual(self.run_probe(cached_preparation=cached)['resultCode'],13)
        self.assertEqual(self.calls,[])

    def test_reserved_result_codes_are_rejected(self):
        value=self.run_probe()
        for key,code in (('resultCode',12),('resultCode',14),('postPinResultCode',1)):
            bad=copy.deepcopy(value);bad[key]=code
            with self.subTest(key=key,code=code),self.assertRaises(AssertionError):m.validate_report(bad)

    def test_report_cli_revalidates_without_a_native_query(self):
        value=self.run_probe();before=len(self.calls)
        self.assertEqual(m.main(['--validate-report',str(self.report)]),0)
        self.assertEqual(len(self.calls),before)
        value['acceptance']=True;self.report.write_text(json.dumps(value))
        self.assertEqual(m.main(['--validate-report',str(self.report)]),1)
        self.assertEqual(len(self.calls),before)

    def test_new_runtime_passes_only_the_explicit_environment(self):
        runtime=m._Runtime.__new__(m._Runtime)
        environment=m.finite_environment(self.windows,self.root)
        runtime.environment=environment;runtime.processes=[]
        received=[];process=SimpleNamespace(handle=41,job=61)
        runtime.native=SimpleNamespace(OwnedOfficeProcess=lambda argv,cwd,**kwargs:(received.append(kwargs) or process))
        self.assertIs(runtime.start([environment['COMSPEC'],'/d','/c','synthetic.cmd'],self.root),process)
        self.assertEqual(received,[{'environment':environment}])
        self.assertEqual(runtime.pending_handles(),2)

    def test_real_stage_and_helper_compose_with_only_native_capture_faked(self):
        case=self
        class Runtime:
            def __init__(self):self.processes=[]
            def start(self,argv,folder):
                self.assert_command(argv)
                request_path,result_path=Path(argv[6]),Path(argv[7])
                def captured(command,deadline,cap):
                    kind=json.loads(request_path.read_bytes())['kindCode']
                    output=str(case.install).encode()+b'\n' if kind==0 else b'clang version 22.1.7\n' if kind==1 else b'LLD 22.1.7\n'
                    return dict(exitCode=0,pid=180+kind,creationTime=134395652231767531,
                        imageMatched=True,naturalExit=True,handlesClosed=True,timedOut=False,
                        outputCapReached=False,captureError=False,captureObservation=m.helper_module.capture_observation()),output,b''
                actual_query=m.helper_module.query
                with patch.object(m.helper_module,'query',side_effect=lambda request:actual_query(request,capture_call=captured)):
                    case.assertEqual(m.helper_module.main(['--request',str(request_path),'--result',str(result_path)]),0)
                process=SimpleNamespace(handle=40,job=60,pid=80)
                process.terminate=lambda:None
                def close():process.handle=process.job=None
                process.close=close
                self.processes.append(process)
                return process
            def assert_command(self,argv):
                case.assertEqual(argv[:3],[str(case.windows/'System32/cmd.exe'),'/d','/c'])
                case.assertIn(argv[3],('discover.cmd','compile.cmd'))
                case.assertEqual(len(argv),8)
            def identity(self,process):return dict(pid=process.pid,creationTime=134395652231767531,processHandle=40,jobHandle=60)
            def root(self,process):return dict(waitResult=0,exitCode=0)
            def census(self,process):
                return dict(querySucceeded=True,lastError=0,returnLength=48,activeProcesses=0,
                    totalProcesses=3,terminatedProcesses=0,rawHex=(bytes(36)+struct.pack('<III',3,0,0)).hex())
            def pending_handles(self):return sum(bool(getattr(p,n)) for p in self.processes for n in ('handle','job'))
        self.runtime=Runtime()
        with patch.object(m,'_run_stage',m.prep._run_stage):value=self.run_probe()
        self.assertEqual(value['resultCode'],0)
        self.assertEqual(len(self.runtime.processes),3)
        self.assertTrue(all(x['natural'] and x['jobEmpty'] and x['handlesClosed'] for x in value['stages']))
        self.assertFalse(value['productionQualified'])


    def test_inner_helper_failure_keeps_result_and_projects_capture_numbers(self):
        def fail(value,kind):
            if kind==2:
                value.update(resultCode=7,exitCode=None,pid=None,creationTime=None,imageMatched=False,naturalExit=False,handlesClosed=True)
        self.helper_mutation=fail
        value=self.run_probe()
        self.assertEqual((value['resultCode'],value['failureStageCode']),(5,6))
        self.assertEqual(value['tools'][1]['helperResultCode'],7)
        self.assertEqual(value['tools'][1]['captureObservation'],m.helper_module.capture_observation())
        self.assertTrue(value['tools'][1]['naturalJob']);self.assertTrue(value['tools'][1]['jobEmpty'])
        self.assertIsNone(value['majorSupported']);self.assertFalse(value['productionQualified'])

    def test_public_report_strictly_validates_optional_capture_observation(self):
        value=self.run_probe()
        self.assertEqual(value['tools'][0]['helperResultCode'],0)
        m.validate_report(value)
        for mutation in ('helper-bool','helper-range','extra','mask-bool','unknown-mask','invented-source'):
            changed=copy.deepcopy(value);tool=changed['tools'][0]
            if mutation=='helper-bool':tool['helperResultCode']=True
            elif mutation=='helper-range':tool['helperResultCode']=9
            elif mutation=='extra':tool['captureObservation']['extra']=0
            elif mutation=='mask-bool':tool['captureObservation']['observedMask']=True
            elif mutation=='unknown-mask':tool['captureObservation']['observedMask']=32
            else:tool['captureObservation']['sourceLine']=175
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):m.validate_report(changed)

    def test_closed_source_validator_binds_only_the_pure_capture_validator(self):
        value=self.run_probe();before=len(self.calls)
        helper_tree=ast.parse((ROOT/'e2e/vs_bundled_clang_version.py').read_text())
        helper_function=next(node for node in helper_tree.body if isinstance(node,ast.FunctionDef)
            and node.name=='validate_capture_observation')
        pure={}
        exec(compile(ast.Module(body=[helper_function],type_ignores=[]),'<fixed capture validator>','exec'),pure)
        tree=ast.parse((ROOT/'e2e/vs_bundled_clang_probe.py').read_text())
        nodes=[node for node in tree.body if isinstance(node,ast.Assign) and len(node.targets)==1
            and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('TOP_KEYS','TOOL_KEYS','STAGE_KEYS')]
        self.assertEqual(len(nodes),3)
        nodes.append(next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='validate_report'))
        space=dict(json=json,prep=SimpleNamespace(QUERY_CAP=4096),
            helper_module=SimpleNamespace(validate_capture_observation=pure['validate_capture_observation']))
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<fixed report validator>','exec'),space)
        space['validate_report'](value)
        changed=copy.deepcopy(value);changed['tools'][0]['captureObservation']['sourceLine']=175
        with self.assertRaises(AssertionError):space['validate_report'](changed)
        self.assertEqual(len(self.calls),before)

    def test_fresh_discovery_failures_keep_original_codes_and_helper_observation(self):
        for helper_code,result_code in ((7,5),(8,6)):
            with self.subTest(helperCode=helper_code):
                self.output=self.root/('discovery-failure-'+str(helper_code))
                self.report=self.root/('discovery-failure-'+str(helper_code)+'.numeric.json')
                def fail(value,kind):
                    if kind==0:
                        value.update(resultCode=helper_code,selectedRoot=None,discoveryParseStage=0 if helper_code==7 else 1)
                        if helper_code==7:
                            value.update(exitCode=None,pid=None,creationTime=None,imageMatched=False,naturalExit=False,stdoutBytes=0)
                            value['captureObservation'].update(observedMask=3,phaseCode=2,exceptionKindCode=2)
                self.helper_mutation=fail
                value=self.run_probe()
                self.assertEqual((value['resultCode'],value['failureStageCode']),(result_code,3))
                self.assertEqual(value['discoveryRequests'],1);self.assertFalse(value['cacheUsed'])
                self.assertEqual(value['discoveryHelperResultCode'],helper_code)
                expected=m.helper_module.capture_observation()
                if helper_code==7:expected.update(observedMask=3,phaseCode=2,exceptionKindCode=2)
                self.assertEqual(value['discoveryCaptureObservation'],expected)
                self.assertEqual(value['versionRequestsTotal'],0)
                self.assertFalse(value['productionQualified']);m.validate_report(value)

    def test_cached_discovery_has_unknown_helper_fields_without_fresh_query(self):
        value=self.run_probe(cached_preparation=self.cached())
        self.assertEqual([row['kindCode'] for row in self.calls],[1,2])
        self.assertEqual(value['discoveryRequests'],0);self.assertTrue(value['cacheUsed'])
        self.assertIsNone(value['discoveryHelperResultCode'])
        self.assertEqual(value['discoveryCaptureObservation'],m.helper_module.capture_observation())
        for mutation in ('invented-result','invented-observation'):
            changed=copy.deepcopy(value)
            if mutation=='invented-result':changed['discoveryHelperResultCode']=0
            else:changed['discoveryCaptureObservation'].update(observedMask=1,phaseCode=8)
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):m.validate_report(changed)

    def test_helper_success_cannot_forge_capture_exception_or_failed_query_flags(self):
        value=self.run_probe()
        for mutation in ('exception','exit','natural','closed','discovery-exception'):
            changed=copy.deepcopy(value);tool=changed['tools'][0]
            if mutation=='discovery-exception':
                changed['discoveryCaptureObservation'].update(observedMask=3,phaseCode=2,exceptionKindCode=2)
            elif mutation=='exception':tool['captureObservation'].update(observedMask=3,phaseCode=2,exceptionKindCode=2)
            else:
                changed.update(resultCode=5,failureStageCode=5,majorSupported=None)
                tool.update(resultCode=5,majorSupported=None)
                if mutation=='exit':tool['versionExit']=17
                else:
                    tool['queryNaturalExit' if mutation=='natural' else 'queryHandleClosed']=False
                    tool['observedComplete']=False;changed['observedComplete']=False
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):m.validate_report(changed)
        self.output=self.root/'forged-helper-private';self.report=self.root/'forged-helper.numeric.json'
        self.helper_mutation=lambda row,kind:row['captureObservation'].update(observedMask=3,phaseCode=2,exceptionKindCode=2) if kind==1 else None
        rejected=self.run_probe()
        self.assertEqual(rejected['resultCode'],6)
        self.assertIsNone(rejected['tools'][0]['helperResultCode'])

    def test_discovery_query_zero_bytes_are_observed_and_cached_fields_stay_unknown(self):
        def empty(value,kind):
            if kind==0:value.update(resultCode=8,selectedRoot=None,stdoutBytes=0,stderrBytes=0,discoveryParseStage=1)
        self.helper_mutation=empty
        value=self.run_probe()
        self.assertEqual((value['resultCode'],value['failureStageCode']),(6,3))
        self.assertEqual(value['discoveryParseStage'],1)
        self.assertEqual(value['discoveryQuery'],dict(stdoutBytes=0,stderrBytes=0,exitCode=0,
            imageMatched=True,naturalExit=True,handlesClosed=True,pid=180,creationTime=134395652231767531))
        self.helper_mutation=None;self.output=self.root/'cached-followup';self.report=self.root/'cached-followup.json'
        cached=self.run_probe(cached_preparation=self.cached())
        self.assertIsNone(cached['discoveryQuery']);self.assertIsNone(cached['discoveryParseStage'])
        self.assertIsNone(cached['discoveryHelperResultCode']);self.assertEqual(cached['discoveryRequests'],0)
        for key in ('discoveryQuery','discoveryParseStage'):
            changed=copy.deepcopy(cached);changed[key]=value[key]
            with self.subTest(key=key),self.assertRaises(AssertionError):m.validate_report(changed)

    def test_discovery_query_schema_and_parse_success_correlations_fail_closed(self):
        value=self.run_probe();self.assertEqual(value['resultCode'],0)
        self.assertEqual(value['discoveryParseStage'],5)
        for mutation in ('stage-zero','stage-boolean','stage-incomplete','exception','bytes-boolean','bytes-zero',
                'bytes-over-bound','extra','exit','image','natural','closed','pid','birth','parse-failure-complete'):
            changed=copy.deepcopy(value);query=changed['discoveryQuery']
            if mutation=='stage-zero':changed['discoveryParseStage']=0
            elif mutation=='stage-boolean':changed['discoveryParseStage']=True
            elif mutation=='stage-incomplete':changed['discoveryParseStage']=3
            elif mutation=='exception':changed['discoveryCaptureObservation'].update(observedMask=3,phaseCode=2,exceptionKindCode=2)
            elif mutation=='bytes-boolean':query['stdoutBytes']=True
            elif mutation=='bytes-zero':query['stdoutBytes']=0
            elif mutation=='bytes-over-bound':query['stderrBytes']=4097
            elif mutation=='extra':query['rawRoot']='synthetic forbidden extra'
            elif mutation=='exit':query['exitCode']=17
            elif mutation in ('image','natural','closed'):query[{'image':'imageMatched','natural':'naturalExit','closed':'handlesClosed'}[mutation]]=False
            elif mutation=='pid':query['pid']=None
            elif mutation=='birth':query['creationTime']=None
            else:changed.update(resultCode=6,failureStageCode=3,discoveryHelperResultCode=8)
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):m.validate_report(changed)

class HelperTests(unittest.TestCase):
    def setUp(self):self.helper=m.helper_module

    def observed(self):
        return dict(exitCode=0,pid=71,creationTime=134395652231767531,imageMatched=True,naturalExit=True,
                    handlesClosed=True,timedOut=False,outputCapReached=False,captureError=False,
                    captureObservation=self.helper.capture_observation())

    def test_private_query_drops_unselected_version_text(self):
        request=dict(schemaVersion=1,kindCode=1,tool=str(Path.cwd()/'VS/VC/Tools/Llvm/x64/bin/clang-cl.exe'),deadline=m.time.monotonic()+4)
        value=self.helper.query(request,capture_call=lambda *_:(self.observed(),b'clang version 22.1.7\nInstalledDir: synthetic-unselected\n',b'synthetic-stderr'))
        self.assertEqual((value['major'],value['minor']),(22,1))
        self.assertNotIn('synthetic-unselected',json.dumps(value))
        self.assertNotIn('synthetic-stderr',json.dumps(value))
        self.assertEqual(set(value),self.helper.RESULT_KEYS)

    def test_query_nonzero_exit_is_preserved(self):
        observed=self.observed();observed['exitCode']=17
        value=self.helper.query(dict(schemaVersion=1,kindCode=2,tool=str(Path.cwd()/'VS/VC/Tools/Llvm/x64/bin/lld-link.exe'),deadline=m.time.monotonic()+4),
            capture_call=lambda *_:(observed,b'LLD 22.1.7\n',b''))
        self.assertEqual((value['resultCode'],value['exitCode']),(4,17))
        self.assertIsNone(value['major'])

    def test_original_popen_identity_matches_existing_native_api_shape(self):
        calls=[]
        api=SimpleNamespace(identity=lambda handle:(calls.append(handle) or dict(image='synthetic.exe',creationTime=134395652231767531)))
        value=self.helper._identity(SimpleNamespace(pid=71,_handle=99),api=api)
        self.assertEqual(calls,[99])
        self.assertEqual(value['pid'],71)

    def process(self,out=b'',err=b'',running=False,close_error=False):
        import io
        class Pipe:
            def __init__(self,value):self.stream=io.BytesIO(value);self.consumed=0
            def read(self,n):
                data=self.stream.read(n);self.consumed+=len(data);return data
            def close(self):self.stream.close()
        class Handle:
            def Close(self):
                if close_error:raise OSError('synthetic close failure')
        class Process:
            pid=71
            def __init__(self):
                self.stdout=Pipe(out);self.stderr=Pipe(err);self._handle=Handle();self.returncode=None if running else 0;self.kills=0
            def poll(self):return self.returncode
            def wait(self,timeout):
                if self.returncode is None:raise __import__('subprocess').TimeoutExpired('synthetic',timeout)
                return self.returncode
            def kill(self):self.kills+=1;self.returncode=1
        return Process()

    def capture(self,process,**kwargs):
        return self.helper.capture(['synthetic.exe','--version'],m.time.monotonic()+4,4096,
            popen=lambda *a,**k:process,identity=lambda _:dict(pid=71,creationTime=134395652231767531,image='synthetic.exe'),**kwargs)

    def test_stdout_limit_is_enforced_before_an_extra_byte(self):
        process=self.process(out=b'x'*4097)
        result,out,err=self.capture(process)
        self.assertEqual(len(out),4096)
        self.assertEqual(process.stdout.consumed,4096)
        self.assertTrue(result['outputCapReached'])

    def test_stderr_limit_is_enforced_before_an_extra_byte(self):
        process=self.process(err=b'x'*4097)
        result,out,err=self.capture(process)
        self.assertEqual(len(err),4096)
        self.assertEqual(process.stderr.consumed,4096)
        self.assertTrue(result['outputCapReached'])

    def test_process_handle_close_failure_is_not_reported_closed(self):
        result,_,_=self.capture(self.process(close_error=True))
        self.assertTrue(result['captureError'])
        self.assertFalse(result['handlesClosed'])

    def test_unknown_executable_name_is_rejected_before_capture(self):
        calls=[]
        request=dict(schemaVersion=1,kindCode=1,tool=str(Path.cwd()/'unrelated.exe'),deadline=m.time.monotonic()+4)
        with self.assertRaises(AssertionError):self.helper.query(request,capture_call=lambda *_:calls.append(1))
        self.assertEqual(calls,[])

    def test_timeout_terminates_only_the_original_process_once(self):
        process=self.process(running=True)
        class StepClock:
            value=100.
            def __call__(self):self.value+=.05;return self.value
        result,_,_=self.helper.capture(['synthetic.exe','--version'],100.25,4096,
            popen=lambda *a,**k:process,identity=lambda _:dict(pid=71,creationTime=134395652231767531,image='synthetic.exe'),clock=StepClock())
        self.assertTrue(result['timedOut'])
        self.assertFalse(result['naturalExit'])
        self.assertEqual(process.kills,1)
        self.assertTrue(result['handlesClosed'])


    def test_capture_identity_failure_keeps_fixed_source_and_hostile_exception_numeric(self):
        for boundary,line in (('image',173),('times',177)):
            with self.subTest(boundary=boundary):
                seen=[]
                class HostileOSError(OSError):
                    def __str__(self):seen.append('str');raise AssertionError('No exception text')
                    def __repr__(self):seen.append('repr');raise AssertionError('No exception repr')
                error=HostileOSError(5,'synthetic private text');error.winerror=6
                native_source=ROOT/'worker/native_windows.py'
                native_class=next(node for node in ast.parse(native_source.read_text()).body
                    if isinstance(node,ast.ClassDef) and node.name=='ProcessDiagnosticsApi')
                import ctypes
                from ctypes import wintypes
                space={'ctypes':ctypes,'wt':wintypes}
                exec(compile(ast.Module(body=[native_class],type_ignores=[]),str(native_source),'exec'),space)
                native=SimpleNamespace(ctypes=ctypes,ProcessDiagnosticsApi=space['ProcessDiagnosticsApi'])
                api=native.ProcessDiagnosticsApi.__new__(native.ProcessDiagnosticsApi)
                api.query_image=lambda *_:boundary!='image'
                api.get_times=lambda *_:False
                process=self.process()
                class Handle:
                    def __int__(self):return 99
                    def Close(self):pass
                process._handle=Handle()
                with patch.object(native.ctypes,'WinError',return_value=error,create=True),patch.object(native.ctypes,'get_last_error',return_value=6,create=True):
                    result,out,err=self.helper.capture(['synthetic.exe','--version'],m.time.monotonic()+4,4096,
                        popen=lambda *a,**k:process,identity=lambda child:self.helper._identity(child,api=api))
                value=self.helper.query(dict(schemaVersion=1,kindCode=2,
                    tool=str(Path.cwd()/'VS/VC/Tools/Llvm/x64/bin/lld-link.exe'),deadline=m.time.monotonic()+4),
                    capture_call=lambda *_:(result,out,err))
                self.assertEqual(value['resultCode'],7)
                self.assertIsNone(value['pid']);self.assertIsNone(value['creationTime'])
                self.assertFalse(value['naturalExit']);self.assertTrue(value['handlesClosed'])
                observation=value['captureObservation'];self.helper.validate_capture_observation(observation)
                native_winerror=OSError.__dict__.get('winerror')
                winerror_known=type(native_winerror) is types.MemberDescriptorType
                self.assertEqual(observation,dict(observedMask=31 if winerror_known else 27,phaseCode=2,exceptionKindCode=2,
                    winerror=6 if winerror_known else 0,errno=5,sourceFileCode=2,sourceLine=line))
                self.assertEqual(seen,[])

    def test_capture_observation_default_and_strict_unknown_mask(self):
        empty=self.helper.capture_observation()
        self.assertEqual(empty,dict(observedMask=0,phaseCode=0,exceptionKindCode=0,
            winerror=0,errno=0,sourceFileCode=0,sourceLine=0))
        self.helper.validate_capture_observation(empty)
        mutations=(dict(extra=0),dict(observedMask=True),dict(observedMask=32),dict(phaseCode=1),
            dict(exceptionKindCode=1),dict(observedMask=4,winerror=5),
            dict(observedMask=3,phaseCode=2,exceptionKindCode=2,errno=1),
            dict(observedMask=19,phaseCode=2,exceptionKindCode=2,sourceFileCode=3,sourceLine=175),
            dict(observedMask=19,phaseCode=2,exceptionKindCode=2,sourceFileCode=2,sourceLine=0),
            dict(observedMask=19,phaseCode=2,exceptionKindCode=2,sourceFileCode=2,sourceLine=65536),
            dict(observedMask=7,phaseCode=2,exceptionKindCode=2,winerror=True),
            dict(observedMask=11,phaseCode=2,exceptionKindCode=2,errno=2**31))
        for mutation in mutations:
            with self.subTest(mutation=tuple(mutation)):
                changed=dict(empty);changed.update(mutation)
                with self.assertRaises(AssertionError):self.helper.validate_capture_observation(changed)

    def original_capture_source(self):
        source=(ROOT/'e2e/vs_bundled_clang_version.py').read_text()
        discovery=r'(?ms)^[ \t]*# discovery-observation:begin ([a-z-]+)\n.*?^[ \t]*# discovery-observation:end \1\n'
        names=re.findall(r'(?m)^\s*# discovery-observation:begin ([a-z-]+)$',source)
        if names:
            self.assertEqual(set(names),{'parse-init','parse-length','parse-decode','parse-crlf','parse-complete','parse-return'})
            self.assertEqual(len(names),6)
            source=re.sub(discovery,'',source).replace("{'captureObservation','discoveryParseStage'}","{'captureObservation'}").replace('and (discovery_stage:=4) and Path(root).is_absolute()','and Path(root).is_absolute()')
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),'d866d10b5d9f523086fe238859c27b7b0dcbe21616566c62fbbe55cca00f2422')
        pattern=r'(?ms)^[ \t]*# capture-observation:begin ([a-z-]+)\n.*?^[ \t]*# capture-observation:end \1\n'
        names=re.findall(r'(?m)^\s*# capture-observation:begin ([a-z-]+)$',source)
        self.assertEqual(set(names),{'imports','schema','helpers','capture-init','capture-expired',
            'after-launch','after-identity','after-witness','before-sampling','before-wait',
            'main-exception','cleanup-phase','cleanup-exception','capture-return','query-projection'})
        self.assertEqual(len(names),15)
        original=re.sub(pattern,'',source).replace('except BaseException as capture_error:', 'except BaseException:')
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),'e9acc73c7e6cc3b1ae0873be8e0b856ea8519d2f558be336445613c61b25d0e1')
        return original

    def test_capture_source_reverse_and_original_calls_results_remain_exact(self):
        namespace={'__name__':'fixed_original_bundled_version','__file__':str(ROOT/'e2e/vs_bundled_clang_version.py')}
        exec(compile(self.original_capture_source(),namespace['__file__'],'exec'),namespace)
        original=SimpleNamespace(**namespace)
        def attempt(module,scenario):
            import io
            calls=[]
            class Pipe:
                def __init__(self,name):self.name=name;self.data=io.BytesIO(b'LLD 22.1.7\n' if name=='stdout' else b'')
                def read(self,n):calls.append(('read',self.name,n));return self.data.read(n)
                def close(self):calls.append(('close',self.name))
            class Handle:
                def Close(self):
                    calls.append(('close','handle'))
                    if scenario=='close-error':raise OSError(6,'synthetic')
            class Process:
                pid=71
                def __init__(self):self.stdout=Pipe('stdout');self.stderr=Pipe('stderr');self._handle=Handle();self.returncode=None if scenario=='timeout' else 0
                def poll(self):calls.append(('poll',));return self.returncode
                def wait(self,timeout):
                    calls.append(('wait',timeout))
                    if self.returncode is None:raise subprocess.TimeoutExpired('synthetic',timeout)
                    return self.returncode
                def kill(self):calls.append(('kill',));self.returncode=1
            process=Process()
            class Thread:
                def __init__(self,target,args,daemon):self.target=target;self.args=args;calls.append(('thread',int(daemon)))
                def start(self):calls.append(('start',));self.target(*self.args)
                def join(self,timeout):calls.append(('join',timeout))
                def is_alive(self):calls.append(('alive',));return False
            class Clock:
                value=100.
                def __call__(self):calls.append(('clock',));self.value+=.05;return self.value
            def identity(_):
                calls.append(('identity',))
                if scenario=='identity-error':raise OSError(5,'synthetic')
                return dict(pid=71,creationTime=134395652231767531,image='synthetic.exe')
            def popen(*_,**options):
                calls.append(('popen',options['creationflags'],int(options['close_fds']),options['bufsize']))
                return process
            with patch.object(module.threading,'Thread',Thread):
                value,out,err=module.capture(['synthetic.exe','--version'],100.25 if scenario=='timeout' else 104.,4096,
                    popen=popen,identity=identity,clock=Clock())
            value=dict(value);value.pop('captureObservation',None)
            return value,out,err,calls
        for scenario in ('success','identity-error','timeout','close-error'):
            with self.subTest(scenario=scenario):self.assertEqual(attempt(original,scenario),attempt(self.helper,scenario))
        changed=self.original_capture_source().replace('process.kill()','process.terminate()',1)
        self.assertNotEqual(hashlib.sha256(changed.encode()).hexdigest(),'e9acc73c7e6cc3b1ae0873be8e0b856ea8519d2f558be336445613c61b25d0e1')

    def test_capture_observation_failure_cannot_replace_original_result_or_exception(self):
        failure=KeyboardInterrupt()
        process=self.process()
        def identity(_):raise OSError(5,'synthetic')
        with patch.object(self.helper,'_capture_exception_numbers',side_effect=failure):
            result,out,err=self.helper.capture(['synthetic.exe','--version'],m.time.monotonic()+4,4096,
                popen=lambda *a,**k:process,identity=identity)
        self.assertTrue(result['captureError']);self.assertTrue(result['handlesClosed'])
        self.assertIsNone(result['pid']);self.assertEqual(result['captureObservation']['observedMask']&2,0)
        escaped=KeyboardInterrupt()
        class Child:
            def poll(self):raise escaped
        for module in (self.helper,):
            with self.assertRaises(KeyboardInterrupt) as caught:
                module.capture(['synthetic.exe'],m.time.monotonic()+4,4096,popen=lambda *a,**k:Child(),identity=identity)
            self.assertIs(caught.exception,escaped)

    def test_capture_untrusted_numbers_and_clipped_trace_stay_unknown(self):
        class Hostile(OSError):
            def __str__(self):raise AssertionError('No exception text')
            def __repr__(self):raise AssertionError('No exception repr')
        for clipped in (False,True):
            with self.subTest(clipped=clipped):
                error=Hostile(5,'synthetic private text');error.winerror='synthetic private value';error.errno=True
                def nested(depth):
                    if depth:return nested(depth-1)
                    raise error
                result,_,_=self.helper.capture(['synthetic.exe'],m.time.monotonic()+4,4096,
                    popen=lambda *a,**k:self.process(),identity=lambda _:nested(20 if clipped else 0))
                observation=result['captureObservation'];self.helper.validate_capture_observation(observation)
                self.assertEqual(observation['observedMask']&12,0)
                self.assertEqual((observation['winerror'],observation['errno']),(0,0))
                if clipped:self.assertEqual((observation['sourceFileCode'],observation['sourceLine']),(0,0))
                else:self.assertEqual(observation['sourceFileCode'],1)
                self.assertTrue(result['captureError']);self.assertIsNone(result['pid'])
                self.assertNotIn('synthetic private',json.dumps(observation))

    def test_cached_exception_reads_never_execute_class_attribute_or_property_getters(self):
        calls=[]
        class Properties(OSError):
            def __getattribute__(self,name):
                if name=='__class__':calls.append(name);raise RuntimeError('forbidden class getter')
                return super().__getattribute__(name)
            @property
            def winerror(self):calls.append('property-winerror');raise RuntimeError('forbidden property')
            @property
            def errno(self):calls.append('property-errno');raise RuntimeError('forbidden property')
            def __str__(self):calls.append('str');raise RuntimeError('forbidden text')
            def __repr__(self):calls.append('repr');raise RuntimeError('forbidden text')
        class Attributes(OSError):
            def __getattribute__(self,name):
                if name in ('__class__','winerror','errno'):
                    calls.append(name);raise RuntimeError('forbidden instance getter')
                return super().__getattribute__(name)
            def __str__(self):calls.append('str');raise RuntimeError('forbidden text')
            def __repr__(self):calls.append('repr');raise RuntimeError('forbidden text')
        class Other(BaseException):
            def __getattribute__(self,name):
                if name in ('__class__','winerror','errno'):
                    calls.append(name);raise RuntimeError('forbidden instance getter')
                return super().__getattribute__(name)
        for error,kind in ((Properties(5,'synthetic'),2),(Attributes(5,'synthetic'),2),(Other(),6)):
            with self.subTest(kind=kind):
                calls.clear();process=self.process()
                def identity(_):raise error
                value,out,err=self.helper.capture(['synthetic.exe'],m.time.monotonic()+4,4096,
                    popen=lambda *a,**k:process,identity=identity)
                self.assertEqual(calls,[])
                self.assertTrue(value['captureError']);self.assertTrue(value['handlesClosed'])
                observation=value['captureObservation'];self.helper.validate_capture_observation(observation)
                self.assertEqual(observation['exceptionKindCode'],kind)
                self.assertEqual(observation['phaseCode'],2)
                if kind==2:self.assertEqual(observation['errno'],5)
                else:self.assertEqual(observation['observedMask']&12,0)

    def test_discovery_parse_stages_preserve_predicate_calls_and_assertion_args(self):
        space={'__name__':'original_discovery_query','__file__':str(ROOT/'e2e/vs_bundled_clang_version.py')}
        exec(compile(self.original_capture_source(),space['__file__'],'exec'),space)
        original=SimpleNamespace(**space)
        def attempt(module,case):
            calls=[];assertions=[];sentinel=RuntimeError();sentinel_seen=[]
            class RootText(str):
                def strip(self):calls.append('strip');return self
                def __contains__(self,item):calls.append('lf' if item=='\n' else 'cr');return str.__contains__(self,item)
            class Output(bytes):
                def __len__(self):calls.append('length');return bytes.__len__(self)
                def __contains__(self,item):calls.append('nul');return bytes.__contains__(self,item)
                def decode(self,encoding):
                    self_encoding=encoding;calls.append('decode');self_test=self_encoding=='utf-8-sig'
                    if not self_test:raise AssertionError()
                    if case=='utf8':raise UnicodeDecodeError('utf-8',b'\xff',0,1,'synthetic')
                    return RootText('/VS\nextra' if case=='lf' else '/VS\rextra' if case=='cr' else 'relative' if case=='relative' else '/VS')
            payload=b'' if case=='empty' else b'x'*4097 if case=='large' else b'x\0' if case=='nul' else b'x'
            out=Output(payload)
            def paths(value):
                if type(value) is RootText:
                    calls.append('path')
                    if case=='path-error':raise sentinel
                    def absolute():calls.append('absolute');return case!='relative'
                    return SimpleNamespace(is_absolute=absolute)
                return Path(value)
            def trace(frame,event,arg):
                if event=='exception' and frame.f_code is module.query.__code__:
                    if arg[0] is AssertionError:assertions.append(BaseException.args.__get__(arg[1]))
                    if arg[1] is sentinel:sentinel_seen.append(True)
                return trace
            globals_map=module.query.__globals__;before_path=globals_map['Path'];previous=sys.gettrace()
            globals_map['Path']=paths
            try:
                sys.settrace(trace)
                request=dict(schemaVersion=1,kindCode=0,tool=str(Path.cwd()/'programs/Microsoft Visual Studio/Installer/vswhere.exe'),deadline=m.time.monotonic()+4)
                value=module.query(request,capture_call=lambda *_:(self.observed(),out,b''))
            finally:sys.settrace(previous);globals_map['Path']=before_path
            for args in assertions:self.assertEqual(args,())
            return value,calls,assertions,sentinel_seen
        stages={'empty':1,'large':1,'nul':1,'utf8':2,'lf':3,'cr':3,'relative':4,'path-error':4,'success':5}
        for case,stage in stages.items():
            with self.subTest(case=case):
                before,old_calls,old_args,old_sentinel=attempt(original,case)
                after,new_calls,new_args,new_sentinel=attempt(self.helper,case)
                self.assertEqual(after['discoveryParseStage'],stage)
                core=dict(after);core.pop('captureObservation');core.pop('discoveryParseStage')
                self.assertEqual(core,before);self.assertEqual(new_calls,old_calls)
                self.assertEqual(new_args,old_args);self.assertEqual(new_sentinel,old_sentinel)
                if case=='lf':self.assertNotIn('cr',new_calls);self.assertNotIn('path',new_calls)
                if case=='cr':self.assertNotIn('path',new_calls)
        version=self.helper.query(dict(schemaVersion=1,kindCode=2,tool=str(Path.cwd()/'VS/VC/Tools/Llvm/x64/bin/lld-link.exe'),deadline=m.time.monotonic()+4),
            capture_call=lambda *_:(self.observed(),b'LLD 22.1.7\n',b''))
        self.assertEqual(version['discoveryParseStage'],0)

class LegacyEnvironmentTests(unittest.TestCase):
    def functions(self):
        tree=ast.parse((ROOT/'worker/native_windows.py').read_text())
        ctor=next(n for n in next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='OwnedOfficeProcess').body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
        canon=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='canonicalize_temp_environment')
        return ctor,canon

    def test_none_branch_and_canonicalizer_ast_remain_exact(self):
        ctor,canon=self.functions()
        self.assertEqual(hashlib.sha256(stable_ast_dump(canon).encode()).hexdigest(),'2fbdfa279c5688c7422f60e9d102eee26a46746a273b8385776137e8c58990b6')
        self.assertEqual([x.arg for x in ctor.args.kwonlyargs],['environment'])
        self.assertIsNone(ctor.args.kw_defaults[0].value)
        self.assertIsInstance(ctor.body[0].value,ast.IfExp)
        original=copy.deepcopy(ctor)
        original.args.kwonlyargs=[];original.args.kw_defaults=[]
        original.body[0].value=original.body[0].value.body
        self.assertEqual(hashlib.sha256(stable_ast_dump(original).encode()).hexdigest(),'b8e06408e66a877411af87c1d60f7faf650add3541ae6ae1f00959ad7ef23ea5')

    def test_provided_empty_and_nonempty_dict_never_access_real_environ(self):
        ctor,canon=self.functions()
        class ForbiddenOs:
            @property
            def environ(self):raise AssertionError('real environment attribute accessed')
        namespace={'os':ForbiddenOs(),'Path':Path}
        exec(compile(ast.Module(body=[canon],type_ignores=[]),'<synthetic canonicalizer>','exec'),namespace)
        expression=compile(ast.Expression(body=ctor.body[0].value),'<synthetic environment branch>','eval')
        for supplied in ({},{'synthetic':'only'}):
            namespace['environment']=supplied
            self.assertEqual(eval(expression,namespace),supplied)
        result=namespace['canonicalize_temp_environment']({'TEMP':'synthetic','TMP':'synthetic2'},resolver=lambda value:'canonical/'+value)
        self.assertEqual(result,{'TEMP':'canonical/synthetic','TMP':'canonical/synthetic2'})

    def test_dump_support_and_no_support_branches(self):
        calls=[]
        def classic(node,*,include_attributes=True):calls.append(('classic',include_attributes));return 'fixed'
        def modern(node,*,include_attributes=True,show_empty=False):calls.append(('modern',include_attributes,show_empty));return 'fixed'
        self.assertEqual(stable_ast_dump(ast.Constant(value=1),dump=classic),'fixed')
        self.assertEqual(stable_ast_dump(ast.Constant(value=1),dump=modern),'fixed')
        self.assertEqual(calls,[('classic',False),('modern',False,True)])

    def test_constructor_semantic_mutations_still_fail_frozen_hash(self):
        ctor,_=self.functions()
        original=copy.deepcopy(ctor)
        original.args.kwonlyargs=[];original.args.kw_defaults=[]
        original.body[0].value=original.body[0].value.body
        expected='b8e06408e66a877411af87c1d60f7faf650add3541ae6ae1f00959ad7ef23ea5'
        for mutation in ('inherit','flags'):
            changed=copy.deepcopy(original)
            create=next(n for n in ast.walk(changed) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='create')
            if mutation=='inherit':create.args[4]=ast.Constant(value=True)
            else:create.args[5]=ast.Constant(value=0)
            with self.subTest(mutation=mutation):
                self.assertNotEqual(hashlib.sha256(stable_ast_dump(changed).encode()).hexdigest(),expected)

class ReviewedNormalWorkflowTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'tests/reviewed_normal_workflow.py'
        spec=importlib.util.spec_from_file_location('bundled_probe_original_oracle',path)
        self.oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.oracle)
        raw=(ROOT/'tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'191eb38642ecdc5d885815cea9567c70cdd49c7950d325403e143db113b62e2c')
        self.expected=json.loads(raw)['normalJobTextSha256']
        candidate=(ROOT.parent/'.github/workflows/office-suite.yml').read_text()
        self.normal=candidate.split('jobs:\n',1)[1].split('\n  writer-server-observer:',1)[0]

    def test_exact_three_steps_preserve_original_normal_oracle(self):
        value=self.oracle.original_normal_oracle_text(self.normal)
        self.assertEqual(hashlib.sha256(value.encode()).hexdigest(),self.expected)
        stripped=self.oracle._without_bundled_clang_probe(self.normal)
        self.assertEqual(hashlib.sha256(self.oracle.original_normal_oracle_text(stripped).encode()).hexdigest(),self.expected)

    def test_changed_original_and_probe_steps_stay_rejected(self):
        tail=self.normal[self.normal.index(self.oracle.BUNDLED_CLANG_PROBE_START):]
        without=self.normal[:self.normal.index(self.oracle.BUNDLED_CLANG_PROBE_START)]
        mutations=(
            self.normal.replace('runner: windows-2025','runner: synthetic-runner',1),
            self.normal.replace('      id: calc-save\n','      id: calc-save\n      continue-on-error: true\n',1),
            self.normal.replace('--output .work/suite-calc-save @sourceReaderArgs','--output .work/suite-calc-save --skip @sourceReaderArgs',1),
            self.normal.replace('path: .work/suite-bundled-clang-probe-public/report.numeric.json','path: .work/suite-bundled-clang-probe-private/',1),
            self.normal.replace(self.oracle.BUNDLED_CLANG_PROBE_START,self.oracle.BUNDLED_CLANG_PROBE_START+'      permissions: write-all\n',1),
            self.normal.replace(self.oracle.BUNDLED_CLANG_PROBE_START,self.oracle.BUNDLED_CLANG_PROBE_START*2,1),
            without.replace('    - name: Enter 없이 실제 Calc Ctrl+S·저장·독립 재열기\n',tail+'    - name: Enter 없이 실제 Calc Ctrl+S·저장·독립 재열기\n',1),
            self.normal+'    - name: Unexpected step after the reviewed diagnostic tail\n      run: exit 0\n',
            self.normal.replace(self.oracle.BUNDLED_CLANG_PROBE_START,self.oracle.BUNDLED_CLANG_PROBE_START+'      continue-on-error: true\n',1),
        )
        for index,changed in enumerate(mutations):
            with self.subTest(mutation=index):
                self.assertNotEqual(changed,self.normal)
                try:value=self.oracle.original_normal_oracle_text(changed)
                except ValueError:continue
                self.assertNotEqual(hashlib.sha256(value.encode()).hexdigest(),self.expected)


    def policy(self):
        spec=importlib.util.spec_from_file_location('bundled_probe_actual_ci_policy',ROOT.parent/'ci/policy.py')
        policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
        return policy

    def test_actual_office_workflow_passes_unmodified_ci_policy(self):
        policy=self.policy()
        workflow=policy.load_workflow(ROOT.parent/'.github/workflows/office-suite.yml')
        try:accepted=policy.audit(workflow,workflow_path='.github/workflows/office-suite.yml')
        except ValueError as error:self.fail(str(error))
        self.assertIs(accepted,True)

    def test_observation_is_the_final_three_steps_without_failure_suppression(self):
        policy=self.policy()
        steps=policy.load_workflow(ROOT.parent/'.github/workflows/office-suite.yml')['jobs']['windows-suite']['steps']
        self.assertEqual([step['name'] for step in steps[-4:]],[
            '모든 검증을 통과한 Suite 개발 패키지 전달',
            'Observe the selected VS bundled Clang pair without changing acceptance',
            'Validate the closed bundled Clang observation before upload',
            'Preserve only the closed bundled Clang numeric observation'])
        self.assertTrue(all('continue-on-error' not in step for step in steps[-3:]))

    def test_observation_reuses_exact_calc_discovery_cache_without_fresh_fallback(self):
        workflow=(ROOT.parent/'.github/workflows/office-suite.yml').read_text()
        policy=self.policy()
        steps=policy.load_workflow(ROOT.parent/'.github/workflows/office-suite.yml')['jobs']['windows-suite']['steps']
        command=steps[-3]['run']
        option=" --cached-preparation ([IO.Path]::GetFullPath('.work/suite-calc-save/ascii-message-observer/preparation.json'))"
        self.assertEqual(steps[-3]['id'],'bundled-clang-probe')
        self.assertEqual(workflow.count('--cached-preparation'),1)
        self.assertEqual(command.count(option),1)
        for changed in (self.normal.replace(option,'',1),
                        self.normal.replace(option,option+option,1),
                        self.normal.replace(option,option.replace('suite-calc-save','foreign-preparation'),1)):
            self.assertNotEqual(changed,self.normal)
            with self.assertRaisesRegex(ValueError,'Reviewed bundled Clang observation delta differs'):
                self.oracle.original_normal_oracle_text(changed)
        # Exercise the existing cache rejection contract rather than duplicating
        # its runtime model. A bad cache must start no fresh discovery/tool query.
        cached=ProbeTests('test_invalid_cache_does_not_fall_back_to_fresh_discovery')
        self.addCleanup(cached.doCleanups)
        cached.setUp()
        cached.test_invalid_cache_does_not_fall_back_to_fresh_discovery()

    def test_exact_tail_removal_restores_independent_full_workflow_hash(self):
        workflow=(ROOT.parent/'.github/workflows/office-suite.yml').read_text()
        def restored_hash(text):
            pinned=' comtypes==1.5.0'
            exact_installs=(
                '    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n'
                '      shell: pwsh\n'
                '      run: |\n'
                '        python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n'
                "        if ($LASTEXITCODE -ne 0) { throw 'Native UI test prerequisites failed.' }\n",
                "        if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'reader-console-diagnostic') {\n"
                '          python -m pip install pywinauto==0.6.9 comtypes==1.5.0\n'
                "          if ($LASTEXITCODE -ne 0) { throw 'Native UI test prerequisites failed.' }\n"
                '        }\n',
            )
            if text.count(pinned)!=2:raise ValueError('Reviewed UI dependency pin differs')
            for exact in exact_installs:
                if text.count(exact)!=1:raise ValueError('Reviewed UI dependency pin differs')
                text=text.replace(exact,exact.replace(pinned,'',1),1)
            before,body=text.split('jobs:\n',1)
            normal,after=body.split('\n  writer-server-observer:',1)
            restored=before+'jobs:\n'+self.oracle._without_bundled_clang_probe(normal)+'\n  writer-server-observer:'+after
            return hashlib.sha256(restored.encode()).hexdigest()
        expected='1c2331d324d18ce60286c2c24726079481a3745c010f22130916b1846efab982'
        pinned=' comtypes==1.5.0'
        install='python -m pip install pywinauto==0.6.9'+pinned
        pin_mutants=(
            workflow.replace(pinned,'',1),
            workflow.replace('          '+install,'          '+install.replace(pinned,''),1),
            workflow.replace(pinned,' comtypes==1.4.17',1),
            workflow.replace(pinned,pinned+pinned,1),
            workflow.replace(pinned,pinned+' --pre',1),
            workflow.replace("if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'reader-console-diagnostic')", "if ($env:OPENGEUL_SUITE_RUN_MODE -ceq 'acceptance')",1),
            workflow.replace('    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n','    - name: Different dependency route\n',1),
            workflow.replace('    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n',
                '    - name: Extra dependency route\n      run: '+install+'\n    - name: 실제 한국어 IME와 네이티브 UI 검사 준비\n',1),
        )
        for index,changed in enumerate(pin_mutants):
            with self.subTest(pin_mutation=index):
                self.assertNotEqual(changed,workflow)
                with self.assertRaises(ValueError):restored_hash(changed)
        self.assertEqual(restored_hash(workflow),expected)
        for before,after in (
                ('  contents: read','  contents: write'),
                ('  OPENGEUL_SUITE_RUN_MODE: acceptance','  OPENGEUL_SUITE_RUN_MODE: synthetic'),
                ('runner: windows-2025','runner: synthetic-runner'),
                ('      id: calc-save\n','      id: calc-save\n      continue-on-error: true\n'),
                ('--output .work/suite-calc-save @sourceReaderArgs','--output .work/suite-calc-save --skip @sourceReaderArgs'),
                ("success() && steps.home-routes.outcome == 'success'","success() || steps.home-routes.outcome == 'success'")):
            with self.subTest(mutation=before):
                changed=workflow.replace(before,after,1);self.assertNotEqual(changed,workflow)
                try:digest=restored_hash(changed)
                except ValueError:continue
                self.assertNotEqual(digest,expected)

    def test_actual_policy_keeps_rejecting_probe_failure_suppression(self):
        policy=self.policy()
        workflow=policy.load_workflow(ROOT.parent/'.github/workflows/office-suite.yml')
        steps=workflow['jobs']['windows-suite']['steps']
        ids={'bundled-clang-probe','bundled-clang-report'}
        indices=[index for index,step in enumerate(steps) if step.get('id') in ids or
            step.get('name')=='Preserve only the closed bundled Clang numeric observation']
        self.assertEqual(len(indices),3)
        for index in indices:
            mutated=copy.deepcopy(workflow)
            mutated['jobs']['windows-suite']['steps'][index]['continue-on-error']='true'
            with self.subTest(step=index),self.assertRaises(ValueError):
                policy.audit(mutated,workflow_path='.github/workflows/office-suite.yml')

if __name__=='__main__':unittest.main()
