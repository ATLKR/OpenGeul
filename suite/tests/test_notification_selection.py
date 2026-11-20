"""Only one original, fully joined notification stack reaches file-only symbols."""
import importlib.util
from pathlib import Path
import unittest
import test_ime_notification_caller as fixture

class NotificationSelectionTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'scripts/matched_plugin_diagnostic.py'
        spec=importlib.util.spec_from_file_location('notification_selection',path);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
    def report(self):
        m,c,row,kw=fixture.NotificationDecodeTests().fixture()
        c.plugin.enabled=1;kw['expected_config']=bytes(c);row.frames[0].moduleId=14;row.frames[0].rva=0x1104
        row.pluginStatus=1;row.pluginStarted=31;row.pluginFinished=32
        caller=m.decode(c,row,**kw)
        native={'officePid':31,'officeCreationTime':555,'childHwnd':51,'expectedImage':'engine.exe'}
        shell={'pid':71,'handleValue':111,'creationTime':222,'image':'shell.exe','waitResult':258}
        engine={'pid':31,'handleValue':122,'creationTime':555,'image':'engine.exe','waitResult':258}
        binding={'sourceCommit':'a'*40,'runId':'7','runAttempt':'1','architecture':'arm64','repository':'ATLKR/OpenGeul','job':'windows-suite'}
        admitted=dict(binding);admitted['sourceRun']=admitted.pop('runId')
        admission={'native':native,'originalShell':shell,'extraEngine':engine,'focusHwnd':51,'editorTid':41,'runBinding':admitted}
        cleanup={'engineExitConfirmed':True,'handleReleased':True,'gracefulShutdownVerified':False,'shellIdentity':shell,'engineIdentity':engine,
          'targets':[71,31],'commandExitCode':0,'commandBudgetStartedAt':1.,'commandBudgetDeadline':16.,'commandReturnedAt':2.,
          'exitWaitStartedAt':2.,'exitWaitDeadline':7.,'shellExitCode':1,'engineWaitReturnedAt':2.2,
          'engineWait':{'api':'WaitForSingleObject','handleValue':122,'result':0,'timeoutMilliseconds':5000}}
        case={'case':'ime-calc','kind':'native-ime-mode-diagnostic','success':False,'stage':'physical-dubeolsik-composition',
              'keyboardFocusHwnd':51,'editorTid':41,'imeKeyboardSession':{'expectedNative':native,'engineHandleReleased':True},
              'imeEngineRetirement':{'admission':admission,'success':False},'imeFailureCleanup':cleanup,
              'imeMessageDiagnostics':kw['messages'],'imeModeDiagnostics':dict(kw['modes'],notificationCaller=caller,deadlineCounter=100,counterFrequency=1000),
              'imeCommands':[dict(command=3,**kw['command3'])]}
        return {'kind':'native-ime-mode-diagnostic','architecture':'arm64','acceptanceEligible':False,'notificationCallerEnabled':True,
                'expectedCaseCount':1,'tests':[case],'runBinding':binding,
                'pluginFileOrigin':{'verified':True,'released':True,'dllSha256':'b'*64,'matchedIdentity':{'guid':'c'*36,'age':1}}}
    def test_exact_first_case_is_joined_without_runtime_setter_claim(self):
        self.assertTrue(hasattr(self.m,'select_notification'),'notification selector absent')
        selected=self.m.select_notification(self.report())
        self.assertEqual(selected['status'],'selected');self.assertEqual(selected['rvas'],[0x1104])
        self.assertFalse(selected['runtimeCallerProved'])
    def test_partial_foreign_changed_generation_or_unconfirmed_cleanup_rejects(self):
        self.assertTrue(hasattr(self.m,'select_notification'),'notification selector absent')
        for change in (lambda c:c['imeFailureCleanup'].update(engineExitConfirmed=False),
                       lambda c:c['imeFailureCleanup'].update(engineWaitReturnedAt=8.),
                       lambda c:c['imeModeDiagnostics']['notificationCaller'].update(engineCreationTime=556),
                       lambda c:c['imeMessageDiagnostics']['events'][0].update(pid=32),
                       lambda c:c['imeModeDiagnostics']['notificationCaller']['frames'][1].update(rva=99)):
            r=self.report();change(r['tests'][0])
            with self.assertRaises(AssertionError):self.m.select_notification(r)
    def test_deferred_or_nonreproduced_result_never_requests_symbol_queries(self):
        self.assertTrue(hasattr(self.m,'select_notification'),'notification selector absent')
        r=self.report();r['tests'][0]['imeModeDiagnostics']['notificationCaller']['hookSentByCurrentThread']=False
        self.assertEqual(self.m.select_notification(r)['status'],'inconclusive-other-thread-delivery')
        r=self.report();r['tests'][0]['imeModeDiagnostics']['notificationCaller']['status']='not-triggered'
        self.assertNotEqual(self.m.select_notification(r)['status'],'selected')

    def test_relative_notification_cli_uses_existing_isolated_resolver(self):
        import contextlib,json,sys,tempfile
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        import ascii_message_preparation as shared
        report=self.report();binding=report['runBinding']
        admission=NS(validate_context=lambda *a:binding,read_event=lambda:{})
        spec=NS(loader=NS(exec_module=lambda m:None));calls=[]
        def run(pair,*,mode,rvas):
            calls.append((mode,rvas))
            return {'success':True,'resolution':{'dllSha256':'b'*64,'identity':report['pluginFileOrigin']['matchedIdentity'],
                    'frames':[{'returnRva':0x1104,'tag':'frame-input-context'}]}}
        worker=NS(shared=shared,run=run)
        with tempfile.TemporaryDirectory() as d,contextlib.chdir(d):
            path=Path('.work/mode/results.json');path.parent.mkdir(parents=True);path.write_text(json.dumps(report));output=Path('.work/out.json')
            with patch.object(self.m,'os',NS(name='nt',environ={})),patch.object(self.m.importlib.util,'spec_from_file_location',return_value=spec),patch.object(self.m.importlib.util,'module_from_spec',return_value=admission),patch.dict(sys.modules,{'plugin_symbol_worker':worker}):
                code=self.m.main(['--mode','resolve','--pair',str(Path('pair').absolute()),'--notification',str(path),'--output',str(output)])
            self.assertEqual(code,0);self.assertEqual(calls,[('resolve',[0x1104])]);retained=json.loads(output.read_text())
            self.assertFalse(retained['runtimeCallerProved']);self.assertFalse(retained['acceptanceEligible'])
