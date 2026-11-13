import copy
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
from unittest import mock
from contextlib import ExitStack
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
E2E=ROOT/'e2e'
ASSETS=ROOT/'tests/ime_command3_finalization_cases'

def load():
    path=E2E/'ime_command3_finalization.py'
    assert path.is_file(),'fixed numeric reader missing'
    spec=importlib.util.spec_from_file_location('candidate_finalization',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.m=load();self.config=self.m.config(state_bytes=596896,pid=10,tid=20,hwnd=30,root=40,created=50,epoch=(60,70))
        self.section=self.m.Section();self.section.config=self.config
        self.section.claimedMask=self.section.publishedMask=7
        for i,row in enumerate(self.section.rows,1):
            row.sequence=row.stage=i;row.pid=10;row.tid=20;row.ackAtStart=2
            row.withinBefore=row.withinAfter=1;row.targetHwnd=30;row.rootHwnd=40
            row.focusBefore=row.focusAfter=30;row.himc=80;row.layout=68289554
            row.startedCounter=100+i*10;row.finishedCounter=105+i*10
            row.deadlineCounter=1000;row.counterFrequency=100
            row.contextPresent=row.conversionSucceeded=row.open=row.releaseAttempts=row.releaseSucceeded=1
            row.conversion=1;row.sentence=8
        self.source='a'*64
    def receipt(self):return self.m.decode(self.section,expected=self.config,expected_source=self.source,expected_budget=(1000,100),ack_before=3,ack_after=3)
    def check(self,data):return self.m.require_receipt(data,expected=self.config,expected_source=self.source,expected_budget=(1000,100))
    def test_complete_numeric_three_rows(self):
        r=self.check(self.receipt());self.assertEqual(r['publishedMask'],7);self.assertFalse(r['acceptanceEligible']);self.assertFalse(r['causalAttributionProved'])
    def test_exact_layout(self):
        self.assertEqual((ctypes.sizeof(self.m.Config),ctypes.sizeof(self.m.Row),ctypes.sizeof(self.m.Section)),(80,144,528))
    def test_source_pin_is_external(self):
        r=self.receipt();r['sourceSha256']='b'*64
        with self.assertRaises(AssertionError):self.check(r)
    def test_unknown_keys_reject(self):
        r=self.receipt();r['unproved']=True
        with self.assertRaises(AssertionError):self.check(r)
    def test_unknown_version_reject(self):
        r=self.receipt();r['schemaVersion']=2
        with self.assertRaises(AssertionError):self.check(r)
    def test_section_reserved_is_not_ignored(self):
        self.section.reserved=1
        with self.assertRaises(AssertionError):self.receipt()
    def test_owner_epoch_and_size_are_exact(self):
        for field in ('pid','tid','targetHwnd','rootHwnd','creationTime','epochLow','epochHigh','mappingBytes','sectionOffset'):
            r=self.receipt();r['config'][field]+=1
            with self.assertRaises(AssertionError):self.check(r)
    def test_bool_and_out_of_range_numeric_reject(self):
        for v in (True,-1,2**64,1.0):
            r=self.receipt();r['rows'][0]['himc']=v
            with self.assertRaises(AssertionError):self.check(r)
    def test_stage_duplicate_order_and_foreign_reject(self):
        for key,value in (('sequence',2),('stage',2),('pid',11),('tid',21),('targetHwnd',31),('rootHwnd',41)):
            r=self.receipt();r['rows'][0][key]=value
            with self.assertRaises(AssertionError):self.check(r)
    def test_partial_masks_stay_diagnostic(self):
        self.section.publishedMask=1;self.section.claimedMask=3
        for r in self.section.rows[1:]:ctypes.memset(ctypes.addressof(r),0,ctypes.sizeof(r))
        r=self.check(self.receipt());self.assertEqual(r['statusCode'],2);self.assertEqual(len(r['rows']),1)
    def test_unstable_ack_rejects_without_inventing_rows(self):
        with self.assertRaises(AssertionError):self.m.decode(self.section,expected=self.config,expected_source=self.source,expected_budget=(1000,100),ack_before=2,ack_after=3)
    def test_failure_row_is_not_success(self):
        self.section.rows[1].status=4;self.section.rows[1].conversionSucceeded=0
        r=self.check(self.receipt());self.assertEqual(r['rows'][1]['status'],4);self.assertFalse(r['acceptanceEligible'])
    def test_success_requires_exact_context_release_and_original_focus(self):
        for field,value in (('contextPresent',0),('conversionSucceeded',0),('releaseAttempts',0),('releaseSucceeded',0),('focusAfter',31),('withinAfter',0)):
            r=self.receipt();r['rows'][0][field]=value
            with self.assertRaises(AssertionError):self.check(r)
    def test_counter_regression_and_false_completion_reject(self):
        r=self.receipt();r['rows'][0]['finishedCounter']=1
        with self.assertRaises(AssertionError):self.check(r)
        r=self.receipt();r['publishedMask']=5
        with self.assertRaises(AssertionError):self.check(r)
    def test_original_budget_is_not_selected_from_record(self):
        r=self.receipt();r['rows'][0]['deadlineCounter']=1001
        with self.assertRaises(AssertionError):self.check(r)
        r=self.receipt();r['rows'][0]['counterFrequency']=101
        with self.assertRaises(AssertionError):self.check(r)
        r=self.receipt();r['rows'][0]['finishedCounter']=1001
        with self.assertRaises(AssertionError):self.check(r)
    def test_no_raw_or_input_fields(self):
        r=self.receipt();self.assertTrue(all(type(v)is int for row in r['rows']for v in row.values()))
        self.assertEqual(set(r),{'schemaVersion','kind','sourceSha256','config','claimedMask','publishedMask','rejected','ackBefore','ackAfter','statusCode','rows','acceptanceEligible','causalAttributionProved'})

class AllocationTests(unittest.TestCase):
    def test_existing_linked_mapping_refuses_before_map_or_write(self):
        m=load()
        class Port:
            maps=0;closes=0
            def create(self,name,size):return 1,True
            def map(self,name,size):self.maps+=1;raise AssertionError
            def close(self,h):self.closes+=1;return True
        p=Port()
        with self.assertRaises(m.Unavailable):m.allocate('synthetic',100,p)
        self.assertEqual((p.maps,p.closes),(0,1))
    def test_exclusive_handle_closed_and_view_not_leaked(self):
        m=load()
        class View:
            closed=False
            def close(self):self.closed=True
        class Port:
            closes=0;view=View()
            def create(self,name,size):return 1,False
            def map(self,name,size):return self.view
            def close(self,h):self.closes+=1;return True
        p=Port();self.assertIs(m.allocate('synthetic',100,p),p.view);self.assertEqual(p.closes,1)

class NativeTests(unittest.TestCase):
    def test_real_portable_policy(self):self.compile_case('native_policy.cpp')
    def compile_case(self,name):
        import os,shutil,contextlib
        with tempfile.TemporaryDirectory(prefix='opengeul-finalization-')as folder:
            owned=Path(folder).resolve();source=owned/name;source.write_bytes((ASSETS/name).read_bytes())
            for item in('ime_command3_finalization.h','ime_command3_finalization_windows.h'):(owned/item).write_bytes((E2E/item).read_bytes())
            text=helper().OBSERVER_SOURCE
            start=text.index('        if(finalizationEnabled) {');end=text.index('\n        if(shared && shared->notificationConfig.enabled)',start)
            (owned/'native_connect.inc').write_text(text[start:end]+'\n')
            start=text.index('extern "C" __declspec(dllexport) unsigned int NativeMappingSize()')
            end=text.index('\nextern "C"',text.index('return before==after&&before==result->publishedMask',start))
            (owned/'native_read.inc').write_text(text[start:end]+'\n')
            if os.name=='nt':
                import test_native_crt_probe as support
                owned=support._serializer_path(owned);source=owned/name
                with open(os.devnull,'w')as sink,contextlib.redirect_stdout(sink):
                    exe,_=support._compile_windows_serializer(owned,source,support._serializer_windows_plan())
                environment=support._serializer_environment()
            else:
                compiler=next((value for name in('c++','g++','clang++')if(value:=shutil.which(name))),None)
                self.assertIsNotNone(compiler,'Existing C++ compiler required; no qualification skip')
                exe=owned/'policy';environment={'PATH':os.defpath}
                result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Wshadow','-Werror','-I',str(owned),str(source),'-o',str(exe)],env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
                self.assertEqual(result.returncode,0,'Synthetic native fixture compile exit')
            result=subprocess.run([str(exe)],env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            try:self.assertEqual(result.returncode,0,'Synthetic native fixture exit')
            finally:
                from native_executable_cleanup import remove_completed_image
                remove_completed_image(owned,exe,result)
    def test_actual_windows_sampling_adapter_pairs_context(self):self.compile_case('native_adapter.cpp')
    def test_actual_mapping_negotiation_and_export(self):self.compile_case('native_negotiation.cpp')

class WiringTests(unittest.TestCase):
    def test_source_stages_preserve_original_command_body(self):
        import ast
        candidate=(E2E/'korean_ime_smoke.py').read_text()
        def source(s):
            for node in ast.parse(s).body:
                if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='OBSERVER_SOURCE'for t in node.targets):return ast.literal_eval(node.value)
        new=source(candidate)
        for n in(1,2,3):self.assertEqual(new.count('if(sequence==3)capture_finalization('+str(n)+',sequence,limits);'),1)
        start='static void command(HWND hwnd, UINT sequence) {';end='// Optional TSF reads'
        body=new[new.index(start):new.index(end)]
        import re
        body=re.sub(r'    if\(sequence==3\)capture_finalization\([123],sequence,limits\);\n','',body)
        self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),'d074a5a2fbf9490aab2f5f73ae3b409c9588dfabfc1f3199bbb1c2e9dba7fefa')
    def test_state_prefix_and_original_exports_unchanged(self):
        import ast
        candidate=(E2E/'korean_ime_smoke.py').read_text()
        parsed=ast.parse(candidate)
        state=next(n for n in parsed.body if isinstance(n,ast.ClassDef)and n.name=='NativeState')
        self.assertEqual(hashlib.sha256(ast.get_source_segment(candidate,state).encode()).hexdigest(),'9ef1300525a45e52ccdcbb1bfe998c1a7f66e0f11502bbbfe3b168d884cc1b01')
        self.assertIn('NativeMappingSize',candidate)
    def test_new_cli_is_explicit_and_no_mode_setter_added(self):
        s=(E2E/'korean_ime_smoke.py').read_text()
        self.assertIn("parser.add_argument('--capture-command3-finalization',action='store_true')",s)
        self.assertIn('capture_command3_finalization=False',s)
    def test_compiler_token_rendering_is_exact(self):
        m=load();self.assertTrue(hasattr(m,'render_source'),'fixed numeric rendering missing')
        cfg=m.config(state_bytes=596896,pid=10,tid=20,hwnd=30,root=40,created=50,epoch=(60,70))
        text=' '.join('__FINALIZATION_'+k+'__'for k in('ENABLED','PID','TID','HWND','ROOT','CREATED','EPOCH_LOW','EPOCH_HIGH'))
        self.assertEqual(m.render_source(text,cfg),'1ull 10ull 20ull 30ull 40ull 50ull 60ull 70ull')
        self.assertEqual(m.render_source(text,None),' '.join(['0ull']*8))
        with self.assertRaises(AssertionError):m.render_source('__FINALIZATION_UNKNOWN__',cfg)
    def test_connected_observer_rechecks_negotiated_binding_before_dispatch(self):
        s=(E2E/'korean_ime_smoke.py').read_text()
        part=s[s.index('static bool connect() {'):s.index('static ITfInputProcessorProfileMgr* profiles()')]
        self.assertIn('&& (!finalizationEnabled || opengeul_ime::finalization::MappingBound(shared,finalizationShared,expectedFinalization))',part)

def helper():
    for p in(ROOT.parent,ROOT,ROOT/'scripts',ROOT/'e2e',ROOT/'tests'):
        if str(p)not in sys.path:sys.path.insert(0,str(p))
    spec=importlib.util.spec_from_file_location('candidate_ime_helper',E2E/'korean_ime_smoke.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class ConstructorTests(unittest.TestCase):
    def attempt(self,bad_size=False,source_error=False):
        m=helper();count={'allocate':0,'hooks':0,'closed':0,'source':0}
        class Call:
            def __init__(self,value=1):self.value=value
            def __call__(self,*a):return self.value
        class Library:
            def __init__(self):
                self.StateSize=Call(ctypes.sizeof(m.NativeState));self.NativeMappingSize=Call(ctypes.sizeof(m.NativeState)+ctypes.sizeof(m.finalization.Section)+(8 if bad_size else 0))
            def __getattr__(self,k):v=Call();setattr(self,k,v);return v
        class User:
            def __getattr__(self,k):v=Call(20 if k=='GetWindowThreadProcessId'else 1);setattr(self,k,v);return v
        class Api:
            user=User()
            def pid(self,hwnd):return 10
        class Buffer(bytearray):
            def close(self):count['closed']+=1
        def allocate(name,size,port):count['allocate']+=1;return Buffer(size)
        def source(path):
            count['source']+=1
            if source_error:raise m.finalization.Unavailable(4)
            return 'a'*64
        def hooks(self,deadline):count['hooks']+=1
        with mock.patch.object(m.native_arch,'observe_native_architecture',return_value={}),mock.patch.object(m.native_arch,'validate_native_architecture',return_value={}),mock.patch.object(m.native_arch,'observe_owned_process',return_value={}),mock.patch.object(m.native_arch,'require_native_pe'),mock.patch.object(m,'compile_observer',return_value=Path('synthetic.dll')),mock.patch.object(m.ctypes,'WinDLL',return_value=Library(),create=True),mock.patch.object(m.finalization,'allocate',side_effect=allocate),mock.patch.object(m.finalization,'NativeMappingPort',return_value=object()),mock.patch.object(m.finalization,'source_identity',side_effect=source),mock.patch.object(m.CompositionObserver,'_install_hooks',hooks):
            try:
                o=m.CompositionObserver(Api(),40,30,30,10,Path('synthetic'),{},command3_binding={'creationTime':50})
            except BaseException:return count,False
            o.close();return count,True
    def test_wrong_native_size_before_allocation_or_write(self):
        count,ok=self.attempt(bad_size=True);self.assertFalse(ok);self.assertEqual(count['allocate'],0);self.assertEqual(count['hooks'],0)
    def test_full_mapping_has_no_retained_tail_view(self):
        count,ok=self.attempt();self.assertTrue(ok);self.assertEqual(count,{'allocate':1,'hooks':1,'closed':1,'source':1})
    def test_source_identity_failure_allocates_no_view_or_hooks(self):
        count,ok=self.attempt(source_error=True);self.assertFalse(ok);self.assertEqual(count['allocate'],0);self.assertEqual(count['closed'],0);self.assertEqual(count['hooks'],0)

class DiagnosticOnlyFollowupTests(unittest.TestCase):
    KIND='native-ime-command3-finalization-diagnostic'

    def ime(self):
        import korean_ime_smoke
        return korean_ime_smoke

    def case_result(self,*,enabled=True,failed=False):
        import test_ime_case_phases as phases
        fixture=phases.IMECasePhaseTests();self.addCleanup(fixture.doCleanups)
        original=phases.ime.case
        def selected(suite,fixtures,output,readiness,module,extension,*,prepared_library,diagnose_navigation=False):
            return original(suite,fixtures,output,readiness,module,extension,
                prepared_library=prepared_library,diagnose_navigation=diagnose_navigation,
                capture_command3_finalization=enabled)
        with mock.patch.object(os,'environ',{'FINALIZATION_TEST_ONLY':'1'}),mock.patch.object(phases.ime,'case',side_effect=selected):
            return fixture.run_case('writer',fail_mode=failed)

    def paths(self,architecture):
        owned=tempfile.TemporaryDirectory();self.addCleanup(owned.cleanup)
        root=Path(owned.name).resolve();suite=root/'Suite';suite.mkdir();fixtures=root/'fixtures';fixtures.mkdir()
        readiness=root/'readiness.json';readiness.write_text('{}',encoding='utf-8')
        (suite/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1,architecture=architecture)),encoding='utf-8')
        return root,suite,fixtures,readiness,root/'output'

    def context(self,root,architecture):
        branch='refs/heads/work/opengeul-office-arm64'
        values=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Windows',
            RUNNER_ARCH='ARM64'if architecture=='arm64'else'X64',GITHUB_REPOSITORY='ATLKR/OpenGeul',
            GITHUB_EVENT_NAME='push',GITHUB_JOB='windows-suite',GITHUB_REF=branch,
            GITHUB_WORKFLOW_REF='ATLKR/OpenGeul/.github/workflows/office-suite.yml@'+branch,
            GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='ATLKR',GITHUB_ACTOR_ID='65988341',
            GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='12345')
        event=dict(repository=dict(full_name='ATLKR/OpenGeul',private=False,id=1),
            sender=dict(login='ATLKR',id=65988341,type='User'),ref=branch,deleted=False,after='a'*40)
        event_path=root/'event.json';values['GITHUB_EVENT_PATH']=str(event_path)
        return values,event,event_path

    def main_result(self,*,architecture='x64',capture=True,environment_change=None,event_change=None,normal_result=False):
        ime=self.ime();root,suite,fixtures,readiness,output=self.paths(architecture)
        environment,event,event_path=self.context(root,architecture)
        if environment_change is not None:environment_change(environment)
        if event_change is not None:event_change(event)
        event_path.write_text(json.dumps(event),encoding='utf-8')
        calls=[];prepared=object()
        def admit(suite_arg,architecture_arg,requested):
            self.assertTrue(suite_arg==suite and architecture_arg==architecture and requested is None)
            calls.append('reader-admission');return None
        def prepare(folder,*,architecture):
            calls.append('prepare');return prepared
        def single(suite_arg,fixtures_arg,output_arg,readiness_arg,module,extension,*,prepared_library,
                   capture_command3_finalization=False):
            self.assertTrue(prepared_library is prepared)
            calls.append(('case',module,capture_command3_finalization))
            if normal_result or not capture_command3_finalization:
                return dict(kind='native-korean-ime',success=True,imeVerified=True)
            return dict(kind=self.KIND,success=True,imeVerified=False,acceptanceEligible=False,caseImeOraclesPassed=True)
        def legacy(suite_arg,fixtures_arg,output_arg,readiness_arg,module,extension,*,prepared_library):
            return single(suite_arg,fixtures_arg,output_arg,readiness_arg,module,extension,prepared_library=prepared_library)
        arguments=['--suite',str(suite),'--fixtures',str(fixtures),'--readiness',str(readiness),'--output',str(output)]
        if capture:arguments+=['--capture-command3-finalization']
        with ExitStack()as stack:
            for patcher in(
                mock.patch.object(os,'environ',environment),
                mock.patch.object(ime,'os',SimpleNamespace(name='nt',environ=environment)),
                mock.patch.object(ime._payload_guard,'_reject_writer_observer'),
                mock.patch.object(ime.native_arch,'observe_native_architecture',return_value={}),
                mock.patch.object(ime.native_arch,'validate_native_architecture',return_value={}),
                mock.patch.object(ime,'_admit_source_reader',side_effect=admit),
                mock.patch.object(ime,'require_readiness',return_value={}),
                mock.patch.object(ime.ascii_input,'prepare_observer',side_effect=prepare),
                mock.patch.object(ime,'case',side_effect=single if capture else legacy)):
                stack.enter_context(patcher)
            returned=None;error=None
            try:returned=ime.main(arguments)
            except Exception as failure:error=failure
        report_path=output/'results.json'
        report=json.loads(report_path.read_text())if report_path.is_file()else None
        return returned,error,report,calls,output

    def test_optin_actual_case_preserves_oracles_but_cannot_claim_ime_acceptance(self):
        calls,record,result,error=self.case_result()
        self.assertTrue(error is None,'Synthetic case unexpectedly failed')
        self.assertTrue(result is record)
        self.assertEqual(record['kind'],self.KIND)
        self.assertIs(record['caseImeOraclesPassed'],True)
        self.assertIs(record['imeVerified'],False);self.assertIs(record['acceptanceEligible'],False)
        self.assertIs(record['success'],True)
        self.assertIn(('command',4),calls);self.assertIn('retirement-close',calls)

    def test_optin_actual_failure_stays_diagnostic_and_preserves_cleanup(self):
        calls,record,result,error=self.case_result(failed=True)
        self.assertTrue(type(error)is AssertionError,'Original native command failure changed')
        self.assertEqual(record['kind'],self.KIND)
        self.assertIs(record['caseImeOraclesPassed'],False)
        self.assertIs(record['imeVerified'],False);self.assertIs(record['acceptanceEligible'],False)
        self.assertIs(record['success'],False)
        self.assertIn('observer-close',calls);self.assertIn('keyboard-close',calls)

    def test_normal_actual_case_remains_the_original_ime_oracle(self):
        _,record,result,error=self.case_result(enabled=False)
        self.assertTrue(error is None,'Default synthetic case unexpectedly failed')
        self.assertIs(result,record);self.assertEqual(record['kind'],'native-korean-ime')
        self.assertIs(record['success'],True);self.assertIs(record['imeVerified'],True)
        self.assertNotIn('caseImeOraclesPassed',record);self.assertNotIn('acceptanceEligible',record)

    def test_owner_push_optin_report_is_bound_and_diagnostic_for_each_architecture(self):
        for architecture in('x64','arm64'):
            with self.subTest(architecture=architecture):
                returned,error,report,calls,_=self.main_result(architecture=architecture)
                self.assertTrue(error is None,'Admitted synthetic diagnostic unexpectedly failed')
                self.assertEqual(returned,0);self.assertEqual(report['kind'],self.KIND)
                self.assertIs(report['acceptanceEligible'],False);self.assertIs(report['imeVerified'],False)
                self.assertIs(report['caseImeOraclesPassed'],True)
                self.assertEqual(report['runBinding'],dict(sourceCommit='a'*40,runId='12345',runAttempt='1',
                    architecture=architecture,repository='ATLKR/OpenGeul',ref='refs/heads/work/opengeul-office-arm64',
                    workflowRef='ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/work/opengeul-office-arm64',
                    job='windows-suite',event='push'))
                self.assertEqual([row for row in calls if type(row)is tuple],
                    [('case',module,True)for module in('writer','calc','impress')])

    def test_rejected_owner_source_run_attempt_and_event_never_prepare_or_write(self):
        environment_changes=[lambda e:e.update(GITHUB_ACTOR='other'),lambda e:e.update(GITHUB_RUN_ATTEMPT='2'),
            lambda e:e.update(GITHUB_EVENT_NAME='workflow_dispatch'),lambda e:e.update(GITHUB_WORKFLOW_SHA='b'*40),
            lambda e:e.update(GITHUB_RUN_ID='0'),lambda e:e.update(GITHUB_REF='refs/heads/main')]
        event_changes=[lambda e:e.update(after='b'*40),lambda e:e['sender'].update(id=1),
            lambda e:e['repository'].update(private=True)]
        for architecture in('x64','arm64'):
            for index,change in enumerate(environment_changes):
                with self.subTest(architecture=architecture,context=index):
                    _,error,report,calls,output=self.main_result(architecture=architecture,environment_change=change)
                    self.assertTrue(type(error)is ValueError,'Unadmitted diagnostic was not rejected')
                    self.assertTrue(report is None);self.assertEqual(calls,[]);self.assertFalse(output.exists())
            for index,change in enumerate(event_changes):
                with self.subTest(architecture=architecture,event=index):
                    _,error,report,calls,output=self.main_result(architecture=architecture,event_change=change)
                    self.assertTrue(type(error)is ValueError,'Unadmitted event was not rejected')
                    self.assertTrue(report is None);self.assertEqual(calls,[]);self.assertFalse(output.exists())

    def test_optin_cannot_publish_plain_normal_success_rows(self):
        _,error,report,_,_=self.main_result(normal_result=True)
        self.assertTrue(type(error)is AssertionError,'Normal acceptance rows bypassed the diagnostic boundary')
        self.assertTrue(report is None)

    def test_default_main_keeps_normal_three_case_acceptance_without_ci_admission(self):
        returned,error,report,_,_=self.main_result(capture=False,environment_change=lambda e:e.clear())
        self.assertTrue(error is None,'Default cohort unexpectedly required diagnostic admission')
        self.assertEqual(returned,0);self.assertEqual(report['kind'],'native-korean-ime')
        self.assertIs(report['success'],True);self.assertIs(report['imeVerified'],True)
        self.assertEqual(report['passedCaseCount'],3)
        self.assertNotIn('runBinding',report);self.assertNotIn('acceptanceEligible',report)


if __name__=='__main__':unittest.main()
