"""Class enums and PID-value equality describe only the current captured guard."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from suite.tests.test_focus_summary import initial_record
from suite.tests import test_numeric_notice as numeric_tests

SCRIPT=Path(__file__).resolve().parents[1]/'e2e/foreground_summary.py'
sys.path.insert(0,str(SCRIPT.parent))


def implementation():
    assert SCRIPT.is_file(),'Closed existing-foreground projection is required'
    spec=importlib.util.spec_from_file_location('foreground_summary_under_test',SCRIPT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def foreign_record():
    record=initial_record()
    for edge,classname in (('before','ConsoleWindowClass'),('after','#32770')):
        record['imeKeyboardSession']['lastGuardObservation']['scope'][edge]['foreground']=dict(
            hwnd=123,pid=999,threadId=99,rootHwnd=123,isWindow=True,className=classname)
    return record


class ForegroundSummaryTests(unittest.TestCase):
    def test_pure_enum_projection_preserves_absent_unknown_and_pid_value_equality(self):
        m=implementation();record=foreign_record();original=copy.deepcopy(record)
        self.assertEqual(m.project(record),[1,3,1])
        self.assertEqual(record,original)
        scope=record['imeKeyboardSession']['lastGuardObservation']['scope']
        scope['after']['foreground']['pid']=998
        self.assertEqual(m.project(record),[1,3,0])
        scope['before']['foreground'].pop('className')
        scope['after']['foreground']['className']='SYNTHETIC PRIVATE class name'
        self.assertEqual(m.project(record),[None,0,0])
        scope['before']['foreground']=dict(hwnd=0,pid=0,threadId=0,rootHwnd=0,isWindow=False)
        self.assertEqual(m.project(record),[None,0,None])

    def test_only_exact_static_class_literals_match_and_weird_types_are_rejected(self):
        m=implementation()
        for classname in ('consolewindowclass','ConsoleWindowClass PRIVATE',
                'WindowsForms10.Window.8.app.0.PRIVATE', '', 'SYNTHETIC PRIVATE'):
            record=foreign_record()
            record['imeKeyboardSession']['lastGuardObservation']['scope']['before']['foreground']['className']=classname
            self.assertEqual(m.project(record),[0,3,1])
        class Poison:
            def __str__(self):raise AssertionError('Private representation read')
            def __eq__(self,other):raise AssertionError('Private comparison read')
        for classname in (None,True,1,[],{},Poison(),'x'*256):
            record=foreign_record()
            record['imeKeyboardSession']['lastGuardObservation']['scope']['before']['foreground']['className']=classname
            self.assertIsNone(m.project(record))

    def test_stale_guard_generation_source_and_nonfailure_are_never_projected(self):
        m=implementation()
        for damage in ('frames','source','generation','handle','deadline','pid','module','architecture'):
            record=foreign_record();keyboard=record['imeKeyboardSession']
            if damage=='frames':record['numericFailureFrames']=[[1,389]]
            elif damage=='source':record['readiness']['source']['sourceRun']='bad'
            elif damage=='generation':keyboard['lastGuardObservation']['engine']['creationTime']+=1
            elif damage=='handle':keyboard['lastGuardObservation']['engine']['handleValue']+=1
            elif damage=='deadline':keyboard['setupDeadline']+=1
            elif damage=='pid':keyboard['lastGuardObservation']['scope']['after']['foreground']['pid']=True
            elif damage=='module':record['module']='writer'
            else:record['architecture']='x64'
            with self.subTest(damage=damage):self.assertIsNone(m.project(record))

    def test_no_api_clock_process_or_private_payload_observation(self):
        m=implementation();record=foreign_record()
        class Poison:
            def __str__(self):raise AssertionError('Private representation read')
            def __bool__(self):raise AssertionError('Private boolean read')
        for name in ('error','traceback','title','file','keyTokens','events','savedText'):record[name]=Poison()
        with patch('os.stat',side_effect=AssertionError('Filesystem query')), \
             patch('subprocess.Popen',side_effect=AssertionError('Process creation')), \
             patch('subprocess.run',side_effect=AssertionError('Process query')), \
             patch('time.monotonic',side_effect=AssertionError('Clock query')):
            self.assertEqual(m.project(record),[1,3,1])


class ForegroundNumericTests(unittest.TestCase):
    setUp=numeric_tests.NumericNoticeTests.setUp
    messages=numeric_tests.NumericNoticeTests.messages
    decode=numeric_tests.NumericNoticeTests.decode
    trace_report=numeric_tests.NumericNoticeTests.trace_report
    frozen_case_wire=numeric_tests.NumericNoticeTests.frozen_case_wire

    def test_v5_requires_exact_arm_calc_optin_and_keeps_default_v4(self):
        record=foreign_record();self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        baseline=self.n.project_case_notice('ime-calc',record,environ=self.env)
        self.assertEqual(baseline['schemaVersion'],4)
        self.env['OPENGEUL_SUITE_FOREGROUND_NOTICE']='1'
        value=self.n.project_case_notice('ime-calc',record,environ=self.env)
        self.assertEqual(value['schemaVersion'],5);self.assertEqual(value['foreground'],[1,3,1])
        self.assertEqual({k:v for k,v in value.items() if k not in ('schemaVersion','foreground')},
            {k:v for k,v in baseline.items() if k!='schemaVersion'})
        for flag in ('0','true',' 1',1,None):
            env=dict(self.env,OPENGEUL_SUITE_FOREGROUND_NOTICE=flag)
            self.assertEqual(self.n.project_case_notice('ime-calc',record,environ=env),baseline)
        for scope in ('1','3','10'):
            env=dict(self.env,OPENGEUL_SUITE_NOTICE_SCOPE=scope)
            self.assertNotIn('foreground',self.n.project_case_notice('ime-calc',record,environ=env))
        changed=copy.deepcopy(record);changed['architecture']='x64'
        changed['readiness']['nativeMachine']=0x8664;changed['readiness']['source']['architecture']='x64'
        env=dict(self.env,RUNNER_ARCH='X64',OPENGEUL_SUITE_NOTICE_SCOPE='3')
        self.assertEqual(self.n.project_case_notice('ime-calc',changed,environ=env)['schemaVersion'],4)
        changed=copy.deepcopy(record);changed['readiness']['source']['sourceRun']='124'
        self.assertNotIn('foreground',self.n.project_case_notice('ime-calc',changed,environ=self.env))
        changed=copy.deepcopy(record);changed['module']='writer';changed['case']='ime-writer';changed['kind']='native-korean-ime'
        changed['imeKeyboardSession']['module']='writer'
        env=dict(self.env,OPENGEUL_SUITE_NOTICE_SCOPE='3')
        self.assertEqual(self.n.project_case_notice('ime-writer',changed,environ=env)['schemaVersion'],4)

    def test_decoder_is_closed_and_no_optin_final_emitter_cannot_publish_new_fields(self):
        self.env.update(OPENGEUL_SUITE_NOTICE_SCOPE='9',OPENGEUL_SUITE_FOREGROUND_NOTICE='1')
        snapshot=self.n.capture_calc_snapshot(foreign_record(),environ=self.env)
        report=self.trace_report();report['numericCaseSnapshot']=json.loads(json.dumps(snapshot))
        self.assertEqual(self.emitter.emit_calc_report(report),1)
        value=self.decode(self.messages()[0]);self.assertEqual(value['schemaVersion'],5)
        for foreground in ([1,3], [1,3,1,0], [True,3,1], [99,3,1], ['PRIVATE',3,1],
                [1,3,True], [1,3,2], [1,3,None], {'class':1}):
            with self.subTest(foreground=foreground),self.assertRaises(ValueError):
                self.decode(json.dumps(value|dict(foreground=foreground)))
        for change in (dict(scopeCode=3),dict(architecture=0x8664),dict(caseCode=17,moduleCode=1),
                dict(schemaVersion=4),dict(title='PRIVATE')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.n.decode_notice(json.dumps(value|change),'a'*40,123)
        message=self.messages()[0]
        with self.assertRaises(ValueError):self.decode(message[:-1]+',"foreground":[1,3,1]}')
        for relations,same in (([2,3],1),([2,2],0),([3,3],0),([5,2],1),([4,5],1)):
            changed=copy.deepcopy(value);changed['focus'][:2]=relations;changed['foreground'][2]=same
            with self.subTest(relations=relations,same=same),self.assertRaises(ValueError):self.decode(json.dumps(changed))
        self.env.pop('OPENGEUL_SUITE_FOREGROUND_NOTICE');self.stream=io.StringIO()
        self.emitter=self.n.NoticeEmitter(environ=self.env,stream=self.stream)
        self.assertEqual(self.emitter.emit_calc_report(report),1)
        downgraded=self.decode(self.messages()[0]);self.assertEqual(downgraded['schemaVersion'],4)
        self.assertNotIn('foreground',downgraded);self.assertEqual(downgraded['focus'],value['focus'])
        for damage in ('source','run'):
            report=copy.deepcopy(report)
            report['numericCaseSnapshot']['sourceCommit' if damage=='source' else 'runId']='b'*40 if damage=='source' else 124
            with self.subTest(damage=damage):self.assertEqual(self.emitter.emit_calc_report(report),0)

    def test_absent_class_and_unobserved_pid_are_preserved_through_wire(self):
        self.env.update(OPENGEUL_SUITE_NOTICE_SCOPE='9',OPENGEUL_SUITE_FOREGROUND_NOTICE='1')
        record=foreign_record();scope=record['imeKeyboardSession']['lastGuardObservation']['scope']
        scope['before']['foreground']=dict(hwnd=0,pid=0,threadId=0,rootHwnd=0,isWindow=False)
        scope['after']['foreground']['className']='SYNTHETIC PRIVATE'
        self.assertTrue(self.emitter.emit_case_notice('ime-calc',record))
        value=self.decode(self.messages()[0]);self.assertEqual(value['foreground'],[None,0,None])
        self.assertNotIn('SYNTHETIC PRIVATE',self.messages()[0])
        with self.assertRaises(ValueError):self.decode(json.dumps(value|dict(foreground=[None,0,0])))

    def test_maximum_legal_v5_fits_original_two_kibibytes(self):
        value=self.frozen_case_wire(2)
        value.update(schemaVersion=5,runId=2**63-1,scopeCode=9,moduleCode=2,caseCode=18,
            stageCode=self.n.STAGES['verify-post-prefix-editing-context'],exceptionCode=12,
            fileCode=26,line=10000000,ownedFrames=[[26,10000000]]*8,
            fieldPresenceMask=(1<<51)-1,focus=[5,5,2,120,1],foreground=[19,19,1])
        for key,kind,_ in self.n._FIELDS:
            value['observations'][key]=1 if kind in ('bool','flag') else (2**64-1 if kind=='u64' else 0xffffffff)
        value['observations'].update(imeCompositionOrdinal=8,imeCompositionStartEventCount=0xffffffff)
        for focus,foreground in (([5,5,2,120,1],[19,19,1]),([0,1,2,120,1],[None,None,None])):
            value.update(focus=focus,foreground=foreground)
            message=json.dumps(value,separators=(',',':'))
            self.assertLessEqual(len(message.encode()),2048)
            self.n.decode_notice(message,'a'*40,2**63-1,expected_scope=9)

    def test_actual_initial_calc_guard_snapshot_cleanup_report_reload_and_final_emit(self):
        import test_ime_keyboard_session as keyboard_tests
        self.env.update(OPENGEUL_SUITE_NOTICE_SCOPE='9',OPENGEUL_SUITE_FOREGROUND_NOTICE='1',
            OPENGEUL_SUITE_CALC_TRACE_NOTICE='1')
        fixtures=keyboard_tests.IMEKeyboardSessionTests()
        with tempfile.TemporaryDirectory() as directory:
            session,process,binding,api,clock,probe,record=fixtures.fixture(directory,module='calc')
            try:
                session.start();session.focus_editor(6.);fixtures.ready(session)
                record.update(case='ime-calc',kind='calc-save-dispatch-diagnostic',imePolicyVersion=4,
                    architecture='arm64',shellPid=process.pid,stage='focus-editor',
                    imeSetupBudget=dict(startedAt=1.,deadline=10.),readiness=foreign_record()['readiness'])
                original_scope=probe.scope_snapshot
                def foreign_scope(*args):
                    scope=original_scope(*args)
                    for edge,classname in (('before','ConsoleWindowClass'),('after','#32770')):
                        scope[edge]['foreground']=dict(hwnd=123,isWindow=True,pid=999,
                            threadId=99,rootHwnd=123,className=classname)
                    return scope
                probe.scope_snapshot=foreign_scope
                try:session.require_calc_navigation_initial_target()
                except AssertionError as exc:
                    primary=exc;record['numericFailure']=self.n.capture_failure_code(exc)
                    record['numericFailureFrames']=self.n.capture_failure_frames(exc)
                else:self.fail('Foreign foreground was admitted')
                self.assertNotIn('calcNavigationContext',record);self.assertNotIn('imeSemanticContext',record)
                before=self.n.capture_calc_snapshot(record,environ=self.env)
                self.assertEqual(before['focus'],[5,5,0,121,0]);self.assertEqual(before['foreground'],[1,3,1])
                last_guard=record['imeKeyboardSession']['lastGuardObservation']
                session.close(primary)
                self.assertIs(record['imeKeyboardSession']['lastGuardObservation'],last_guard)
                record.update(error='SYNTHETIC PRIVATE',traceback='SYNTHETIC PRIVATE',
                    calcDispatchDiagnostic=self.trace_report()['diagnostic'])
                # Exercise the production artifact projection using the same explicit
                # opt-in as the controller, after its original HANDLE cleanup.
                import korean_ime_smoke as ime
                with patch.dict(ime.os.environ,self.env,clear=True):report=ime.calc_dispatch_report(record)
                report.update(runBinding=dict(sourceCommit='a'*40,runId='123',runAttempt='1',architecture='arm64'),success=False)
                report=json.loads(json.dumps(report))
                self.assertEqual(self.emitter.emit_calc_report(report),2)
                closed=self.decode(self.messages()[0]);self.assertEqual(closed['schemaVersion'],5)
                self.assertEqual(closed['focus'],[5,5,0,121,0]);self.assertEqual(closed['foreground'],[1,3,1])
                self.assertEqual(closed['observations']['engineHandleReleased'],1)
                self.assertNotIn('SYNTHETIC PRIVATE',json.dumps(report));self.assertNotIn('ConsoleWindowClass',json.dumps(report))
                self.assertEqual(len(self.messages()),2)
                trace=self.decode(self.messages()[1],title=self.n.TRACE_TITLE)
                self.assertEqual(trace['schemaVersion'],1);self.assertNotIn('foreground',trace)
            finally:
                session.close(RuntimeError('Synthetic bounded test disposal'));fixtures.doCleanups()

    def test_only_existing_arm_calc_workflow_step_opts_in(self):
        from suite.tests.test_calc_matrix_workflow import WORKFLOW,workflow_steps,field
        selected=[step for step in workflow_steps() if 'OPENGEUL_SUITE_FOREGROUND_NOTICE' in step]
        self.assertEqual([field(step,'id') for step in selected],['calc-dispatch-diagnostic'])
        self.assertIn("OPENGEUL_SUITE_FOREGROUND_NOTICE: '1'",selected[0])
        self.assertIn("matrix.architecture == 'arm64'",selected[0])
        self.assertNotIn('OPENGEUL_SUITE_FOREGROUND_NOTICE',WORKFLOW.read_text().split('jobs:')[0])


if __name__=='__main__':unittest.main()
