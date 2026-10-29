"""Portable negative E2E-oracle checks; no physical Windows input is claimed."""
import copy
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

# Existing shared test fixtures use top-level imports under discovery; include
# their exact directory for explicit suite.tests.* invocation as well.
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
from test_calc_model_barrier import workbook


class CalcSaveSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api=None
        source=Path(__file__).resolve().parents[1]/'e2e/calc_save_smoke.py'
        if source.is_file():
            spec=importlib.util.spec_from_file_location('calc_save_smoke_under_test',source)
            cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def setUp(self):
        self.assertIsNotNone(self.api,'RED: a separate physical no-Enter CtrlS case is required')
        self.base=self.api.read_cells(workbook())
        self.expected=self.base['a1Text']+self.api.MARKER

    def test_final_file_requires_exact_edit_and_all_neighbor_formula_semantics(self):
        self.api.require_grid(self.api.read_cells(workbook(a1=self.expected)),self.base,self.expected)
        for raw in [workbook(),workbook(a1=self.expected+self.api.MARKER),
                    workbook(a1=self.expected,b1='18'),workbook(a1=self.expected,formula='SUM(B1:B1)')]:
            with self.subTest(raw=raw),self.assertRaises(AssertionError):
                self.api.require_grid(self.api.read_cells(raw),self.base,self.expected)

    def test_exact_readonly_before_save_must_still_be_original_uncommitted_model(self):
        row=dict(self.base,isModified=False)
        self.api.require_uncommitted_cells(row,self.base)
        for key,value in [('a1Text',self.expected),('isModified',True),('b1Value',True),
                          ('d1Formula','=42'),('d1Value',41)]:
            changed=dict(row);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):
                self.api.require_uncommitted_cells(changed,self.base)

    def test_native_save_trace_requires_one_original_intercept_and_one_successful_transaction(self):
        rows=[dict(event='suite.nativeDispatch',stage='received',sequence=1,workerPid=10,traceId='a'*32,
                   details=dict(receiptSequence=1,command='save',nativeCommand='.uno:Save')),
              dict(event='suite.workerSave',stage='request.begin',sequence=2,workerPid=10,traceId='a'*32,details=dict(requestId=5)),
              dict(event='suite.calcNativeSave',stage='begin',sequence=3,workerPid=10,traceId='a'*32,details=dict(nativeCommand='.uno:Save')),
              dict(event='suite.calcNativeSave',stage='end',sequence=4,workerPid=10,traceId='a'*32,
                   details=dict(nativeCommand='.uno:Save',dispatchState=1,dispatchResult=True)),
              dict(event='suite.workerSave',stage='request.end',sequence=5,workerPid=10,traceId='a'*32,details=dict(requestId=5,ok=True))]
        self.api.require_save_trace(rows,'a'*32)
        for mutate in [lambda x:x.pop(0),lambda x:x.append(copy.deepcopy(x[0])),
                       lambda x:x[3]['details'].update(dispatchResult=False),
                       lambda x:x[3]['details'].update(dispatchResult=1),
                       lambda x:x[2].update(workerPid=99),
                       lambda x:x[4]['details'].update(requestId=8),
                       lambda x:x.reverse()]:
            changed=copy.deepcopy(rows);mutate(changed)
            with self.subTest(change=changed),self.assertRaises(AssertionError):self.api.require_save_trace(changed,'a'*32)

    def test_real_worker_diagnostics_schema_matches_new_route_oracle(self):
        import importlib,os,tempfile
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
        traces=importlib.import_module('save_diagnostics');router=importlib.import_module('dispatch')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
                'OPENGEUL_SUITE_DIAGNOSTICS':folder,'OPENGEUL_SUITE_SAVE_TRACE_ID':'a'*32}), \
                patch.object(traces,'_trace',traces.SaveTrace()):
            router.DispatchRouter(lambda c:None).dispatch(NS(Complete='.uno:Save'),())
            traces.trace_request('request.begin',7)
            traces.trace_calc_save('begin','.uno:Save')
            traces.trace_calc_save('end','.uno:Save',state=1,result=True)
            traces.trace_request('request.end',7,ok=True)
            rows=[json.loads(line) for f in Path(folder).glob('worker-save-*.jsonl') for line in f.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(7,self.api.require_save_trace(rows,'a'*32)['requestId'])

    def test_host_token_and_request_are_bound_to_actual_shell_not_inherited_environment(self):
        stages=['command.received','command.handler.enter','request.begin','command.handler.return','request.written','request.reply']
        rows=[dict(event='suite.workerSave',component='host',stage=stage,processId=22,traceId='b'*32,sequence=i+1,
                   details=dict(commandSequence=3,**(dict(command='save') if stage.startswith('command.') else
                       dict(requestId=7,**({'ok':True} if stage=='request.reply' else {})))))
              for i,stage in enumerate(stages)]
        self.assertEqual(dict(traceId='b'*32,requestId=7,commandSequence=3),self.api.require_host_trace(rows,22))
        for mutate in [lambda x:x[1].update(processId=99),lambda x:x[1].update(traceId='c'*32),
                       lambda x:x[2]['details'].update(requestId=9),lambda x:x.append(copy.deepcopy(x[0]))]:
            changed=copy.deepcopy(rows);mutate(changed)
            with self.assertRaises(AssertionError):self.api.require_host_trace(changed,22)

    def test_reopen_waits_for_all_owned_job_descendants_after_launcher_exit(self):
        from types import SimpleNamespace as NS
        groups=iter([[11],[12],[]]);ticks=iter([0.,.1,.2,.3,.4,.5])
        helper=NS(job=51,poll=lambda:0,terminate=lambda:self.fail('Completed helper must not be terminated'))
        probe=NS(job_pids=lambda job:next(groups));record={}
        self.assertEqual(0,self.api.await_reopen_job(helper,probe,record,clock=lambda:next(ticks),pause=lambda n:None))
        self.assertEqual([[11],[12],[]],[r['pids'] for r in record['jobSamples']])

    def test_reopen_timeout_terminates_only_owned_job_and_cannot_pass(self):
        from types import SimpleNamespace as NS
        calls=[];ticks=iter([0.,91.]);groups=iter([[11],[]])
        helper=NS(job=51,poll=lambda:None,terminate=lambda:calls.append('owned-job'))
        probe=NS(job_pids=lambda job:next(groups));record={}
        with self.assertRaises(TimeoutError):
            self.api.await_reopen_job(helper,probe,record,clock=lambda:next(ticks),pause=lambda n:None)
        self.assertEqual(['owned-job'],calls)
        self.assertTrue(record['terminated'])

    def test_action_contract_forbids_enter_accept_formula_or_multiple_save(self):
        row=dict(navigationKeys=['^{HOME}','{F2}','^{END}'],commitKeys=[],saveShortcutCount=1,
                 physicalAsciiMarker=self.api.MARKER,uncommittedBeforeSaveVerified=True,observerClosedBeforeSave=True,
                 pendingInputTextVerified=True)
        self.api.require_actions(row)
        for key,value in [('commitKeys',['{ENTER}']),('navigationKeys',['.uno:AcceptFormula']),
                          ('saveShortcutCount',2),('observerClosedBeforeSave',False),('pendingInputTextVerified',False)]:
            changed=dict(row);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_actions(changed)

    def pending_rows(self):
        from test_calc_pending_input import PendingInputTests
        fixture=PendingInputTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        reader=fixture.reader();absent=reader.read()
        fixture.paragraph.text=self.base['a1Text'];edit=fixture.present(reader)
        fixture.paragraph.text=self.expected;pending=reader.read()
        selection=dict(readOnly=True,source='retained-controller.getSelection',range=dict(sheet=0,startColumn=0,startRow=0,endColumn=0,endRow=0))
        def row(ui):return dict(self.base,isModified=False,pendingInput=ui,calcSelection=copy.deepcopy(selection),bindingBefore={'childHwnd':456})
        return [row(absent),row(edit),row(pending)]

    def type_pending(self,rows):
        from types import SimpleNamespace as NS
        self.assertTrue(callable(getattr(self.api,'type_pending_a1',None)),
                        'Physical Calc edit lacks exact owned selection/buffer receipt')
        events=[];iterator=iter(rows);record={}
        def read(deadline):events.append(('read',deadline));return next(iterator)
        value=self.api.type_pending_a1(NS(read=read),self.base,self.api.MARKER,record,12.,
            navigate=lambda keys:events.append(('keys',keys)),require_focus=lambda:events.append(('focus-getter',)),
            type_marker=lambda:events.append(('ascii-once',)))
        return value,events,record

    def test_physical_edit_observes_a1_then_baseline_buffer_before_ascii_without_committing(self):
        self.assertTrue(callable(getattr(self.api,'type_pending_a1',None)),
                        'Physical Calc edit lacks exact owned selection/buffer receipt')
        rows=self.pending_rows();value,events,record=self.type_pending(rows)
        self.assertEqual(value,tuple(rows))
        self.assertEqual([event for event in events if event[0] in ('keys','read','ascii-once')],
            [('keys','^{HOME}'),('read',12.),('keys','{F2}^{END}'),('read',12.),('ascii-once',),('read',12.)])
        self.assertEqual(record['navigationKeys'],['^{HOME}','{F2}','^{END}'])
        self.assertTrue(record['pendingInputTextVerified'])

    def test_wrong_a1_selection_stops_before_f2_and_missing_or_wrong_buffer_stops_before_ascii(self):
        self.assertTrue(callable(getattr(self.api,'type_pending_a1',None)),
                        'Physical Calc edit lacks exact owned selection/buffer receipt')
        from types import SimpleNamespace as NS
        for stage in ('selection','missing-editor','baseline-text','suffix','model-accepted'):
            rows=self.pending_rows();events=[];record={};iterator=iter(rows)
            if stage=='selection':rows[0]['calcSelection']['range']['startRow']=rows[0]['calcSelection']['range']['endRow']=7
            elif stage=='missing-editor':rows[1]['pendingInput']=copy.deepcopy(rows[0]['pendingInput'])
            elif stage=='baseline-text':rows[1]['pendingInput']['editor']['text']='wrong'
            elif stage=='suffix':rows[2]['pendingInput']['editor']['text']+='x'
            else:rows[2]['isModified']=True
            with self.subTest(stage=stage),self.assertRaises(AssertionError):
                self.api.type_pending_a1(NS(read=lambda deadline:next(iterator)),self.base,self.api.MARKER,record,12.,
                    navigate=lambda keys:events.append(keys),require_focus=lambda:None,type_marker=lambda:events.append('ascii'))
            if stage=='selection':self.assertEqual(events,['^{HOME}'])
            elif stage in ('missing-editor','baseline-text'):self.assertNotIn('ascii',events)
            else:self.assertEqual(events.count('ascii'),1)

    def test_pending_input_replay_joins_exact_ui_text_to_ordered_owned_model_receipts(self):
        from test_calc_model_barrier import observation
        from test_writer_model_barrier import synthetic_frame,original_shell_fixture
        import writer_model_reader as reader
        from test_calc_initial_selection_program import program_observation
        self.assertTrue(callable(getattr(self.api,'require_pending_input_observations',None)))
        basic=self.pending_rows()
        with tempfile.TemporaryDirectory() as directory:
            frame=synthetic_frame(Path(directory)/'Suite','unused')
            frame.binding['documentUrl']='file:///C:/owned.xlsx'
            rows=[]
            for index,part in enumerate([basic[0],*basic]):
                row=observation(frame,self.base['a1Text'],1+index*.2,1.1+index*.2,False)
                # Synthetic QPC samples bracket this request's selection proof;
                # the existing monotonic samples and deadline stay unchanged.
                started_ns=1_000_000_000+index*200_000_000
                finished_ns=1_100_000_000+index*200_000_000
                row.update(controllerQpc=dict(startedNs=started_ns,finishedNs=finished_ns),
                    helperQpc=dict(startedTicks=started_ns+10_000_000,
                        finishedTicks=finished_ns-10_000_000,frequency=1_000_000_000))
                ui=copy.deepcopy(part['pendingInput']);ui['childHwnd']=frame.binding['childHwnd']
                row.update(kind='existing-owned-calc-pending-input',operations=list(reader.CALC_PENDING_OPERATIONS),
                    calcSelection=copy.deepcopy(part['calcSelection']),pendingInput=ui)
                program_observation(row,index)
                rows.append(row)
            context=dict(suite=frame.suite,inventory=frame.inventory,inventory_sha256=frame.inventory_sha256,
                original_shell=original_shell_fixture(frame.binding,frame.suite),expected_url=frame.binding['documentUrl'],deadline=12.)
            self.api.require_pending_input_observations(*rows,self.base,self.api.MARKER,**context)
            for mutate in (lambda r:r[1]['calcSelection']['range'].update(startRow=7,endRow=7),
                           lambda r:r[3]['pendingInput']['editor'].update(text=self.expected+'suffix'),
                           lambda r:r[3]['bindingAfter'].update(officeCreationTime=999),
                           lambda r:r[3].update(readStartedAt=.5),
                           lambda r:r[3].pop('controllerQpc'),
                           lambda r:r[3].pop('helperQpc'),
                           lambda r:r[3].update(controllerQpc=copy.deepcopy(r[2]['controllerQpc'])),
                           lambda r:r[3].update(helperQpc=copy.deepcopy(r[2]['helperQpc'])),
                           lambda r:program_observation(r[0],1),
                           lambda r:program_observation(r[1],0),
                           lambda r:r[2]['calcSelectionPhase'].update(requestSequence=1),
                           lambda r:r[3]['calcSelectionPhase'].update(requestSequence=True),
                           lambda r:r[3]['calcSelectionPhase'].update(program=reader.CALC_PENDING_GETTER_CONTRACT),
                           lambda r:r[1].update(calcInitialSelection=copy.deepcopy(r[0]['calcInitialSelection'])),
                           lambda r:r[0]['calcInitialSelection']['shapeWitness'].update(postCount=1),
                           lambda r:r[0]['calcInitialSelection']['shapeWitness'].update(controllerId=999),
                           lambda r:r[0].update(isModified=True)):
                changed=copy.deepcopy(rows);mutate(changed)
                with self.subTest(mutate=mutate),self.assertRaises(AssertionError):
                    self.api.require_pending_input_observations(*changed,self.base,self.api.MARKER,**context)

    def test_lost_focus_or_capture_after_reader_start_prevents_navigation_input(self):
        from types import SimpleNamespace as NS
        events=[]
        def refuse():raise AssertionError('Owned input focus/capture changed')
        with self.assertRaisesRegex(AssertionError,'focus/capture'):
            self.api.type_pending_a1(NS(read=lambda deadline:self.fail('No getter after rejected input guard')),
                self.base,self.api.MARKER,{},12.,navigate=lambda keys:events.append(keys),
                require_focus=refuse,type_marker=lambda:events.append('ascii'))
        self.assertEqual(events,[])


class CalcSaveEntryFailureTests(unittest.TestCase):
    def entry(self):
        source=Path(__file__).resolve().parents[1]/'e2e/calc_save_smoke.py'
        tree=ast.parse(source.read_text(encoding='utf-8'),filename=str(source))
        self.assertIsInstance(tree.body[-1],ast.If)
        return compile(ast.Module(body=[tree.body[-1]],type_ignores=[]),str(source),'exec')

    def environment(self):
        return dict(OPENGEUL_SUITE_NUMERIC_NOTICE='1',OPENGEUL_SUITE_NOTICE_SCOPE='13',
            GITHUB_ACTIONS='true',GITHUB_REPOSITORY='ATLKR/OpenGeul',GITHUB_JOB='windows-suite',
            GITHUB_EVENT_NAME='push',GITHUB_REF='refs/heads/work/opengeul-office-arm64',
            GITHUB_ACTOR='ATLKR',GITHUB_ACTOR_ID='65988341',GITHUB_RUN_ID='123',
            GITHUB_RUN_ATTEMPT='1',GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,RUNNER_ARCH='ARM64')

    def execute(self,entry,main):
        exec(entry,dict(__name__='__main__',main=main,CASE='calc-active-cell-save'))

    def test_uncaught_setup_emits_one_closed_scope13_notice_without_reading_exception_text(self):
        import numeric_notice
        class NoTextError(Exception):
            def __str__(self): raise AssertionError('Do not format the original exception')
            def __getattr__(self,name): raise AssertionError('Do not read exception properties')
        primary=NoTextError();calls=[]
        def main():calls.append('main');raise primary
        entry=self.entry();stream=io.StringIO()
        emitter=numeric_notice.NoticeEmitter(environ=self.environment(),stream=stream)
        with patch.dict(os.environ,self.environment(),clear=True),patch.object(numeric_notice,'_EMITTER',emitter), \
             patch('subprocess.run',side_effect=AssertionError('No new process')), \
             patch('time.monotonic',side_effect=AssertionError('No new clock')), \
             patch.object(Path,'read_text',side_effect=AssertionError('No new evidence read')):
            with self.assertRaises(NoTextError) as caught:self.execute(entry,main)
        self.assertIs(caught.exception,primary)
        self.assertEqual(calls,['main'])
        notices=stream.getvalue().strip().splitlines()
        self.assertEqual(len(notices),1)
        payload=notices[0].split('::',2)[2]
        decoded=numeric_notice.decode_notice(payload,'a'*40,123,expected_scope=13)
        self.assertEqual((decoded['schemaVersion'],decoded['caseCode'],decoded['moduleCode'],
            decoded['stageCode'],decoded['exceptionCode'],decoded['fileCode']),(2,60,2,3,0,33))
        self.assertEqual(decoded['ownedFrames'],[[33,decoded['line']]])
        self.assertGreater(decoded['line'],0)
        self.assertEqual(decoded['fieldPresenceMask'] & 15,0)  # No observed shell/engine identities.
        for name in ('shellPid','enginePid','officeCreationTime','shellCreationTime'):
            self.assertEqual(decoded['observations'][name],0)

    def test_normal_main_return_zero_or_one_keeps_exit_code_without_an_additional_notice(self):
        import numeric_notice
        entry=self.entry()
        for code in (0,1):
            calls=[];stream=io.StringIO()
            def main():calls.append('main');return code
            emitter=numeric_notice.NoticeEmitter(environ=self.environment(),stream=stream)
            with self.subTest(code=code),patch.dict(os.environ,self.environment(),clear=True), \
                 patch.object(numeric_notice,'_EMITTER',emitter):
                with self.assertRaises(SystemExit) as caught:self.execute(entry,main)
                self.assertEqual(caught.exception.code,code)
                self.assertEqual(stream.getvalue(),'');self.assertEqual(calls,['main'])

    def test_metadata_baseexceptions_cannot_replace_the_original_uncaught_setup_exception(self):
        import numeric_notice
        entry=self.entry()
        for method in ('capture_failure_code','capture_failure_frames','emit_case_notice'):
            primary=RuntimeError('synthetic original setup failure');calls=[]
            def main():calls.append('main');raise primary
            with self.subTest(method=method),patch.dict(os.environ,self.environment(),clear=True), \
                 patch.object(numeric_notice,method,side_effect=KeyboardInterrupt()):
                with self.assertRaises(RuntimeError) as caught:self.execute(entry,main)
                self.assertIs(caught.exception,primary);self.assertEqual(calls,['main'])

    def test_disabled_context_keeps_original_exception_without_public_output(self):
        import numeric_notice
        entry=self.entry();primary=ValueError('synthetic setup failure');stream=io.StringIO()
        def main():raise primary
        with patch.dict(os.environ,{},clear=True),patch.object(numeric_notice,'_EMITTER',
                numeric_notice.NoticeEmitter(environ={},stream=stream)):
            with self.assertRaises(ValueError) as caught:self.execute(entry,main)
        self.assertIs(caught.exception,primary);self.assertEqual(stream.getvalue(),'')


if __name__=='__main__':unittest.main()
