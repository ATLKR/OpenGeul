"""Portable negative E2E-oracle checks; no physical Windows input is claimed."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

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
                 physicalAsciiMarker=self.api.MARKER,uncommittedBeforeSaveVerified=True,observerClosedBeforeSave=True)
        self.api.require_actions(row)
        for key,value in [('commitKeys',['{ENTER}']),('navigationKeys',['.uno:AcceptFormula']),
                          ('saveShortcutCount',2),('observerClosedBeforeSave',False)]:
            changed=dict(row);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_actions(changed)


if __name__=='__main__':unittest.main()
