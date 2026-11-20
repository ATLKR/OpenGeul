"""Local contracts with typed fake APIs; not authentic Windows qualification."""
import copy
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
fixture=load('readonly_contract_fixtures',ROOT/'tests/test_native31_desktop_control.py')
m=fixture.m
ACTION=ROOT/'e2e/native31_privacy_prepare.py'
p=load('privacy_actions',ACTION) if ACTION.exists() else None

class PreparationContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(p,'Explicit privacy-only action adapter is missing')
        old=fixture.ControlContracts();old.setUp()
        self.env=old.env;self.event=old.event;self.checkout=old.checkout;self.native=old.native
        self.observed=old.privacy_fixture()
        self.observed['processes'][0].update(exitCode=259,peMachine=0xAA64)
        self.observed['uia'][0]['nodes'].append(dict(name='Description '*40,controlType=50020,
            automationId='',className='',processId=200,enabled=True,offscreen=False))
        self.candidate=m.legacy.privacy_candidate(self.observed,1,r'C:\Windows')
        self.classification=m.classify(self.observed,1,r'C:\Windows',complete=True,stable=True)

    def prepare_env(self):
        self.env.update(GITHUB_JOB='prepare',GITHUB_REF=m.PREPARE_BRANCH,GITHUB_WORKFLOW_REF=m.PREPARE_WORKFLOW)
        self.event['ref']=m.PREPARE_BRANCH

    def test_mode_requires_exact_new_context_and_rejects_cross_mode(self):
        with self.assertRaises(ValueError):m.validate_context(self.env,self.event,self.checkout,self.native,'nt',prepare_privacy=True)
        self.prepare_env()
        with self.assertRaises(ValueError):m.validate_context(self.env,self.event,self.checkout,self.native,'nt')
        result=m.validate_context(self.env,self.event,self.checkout,self.native,'nt',prepare_privacy=True)
        self.assertEqual(result['job'],'prepare');self.assertEqual(result['workflowRef'],m.PREPARE_WORKFLOW)
        for key,bad in [('GITHUB_JOB','observe'),('GITHUB_WORKFLOW_SHA','f'*40),('GITHUB_ACTOR','other'),('GITHUB_RUN_ATTEMPT','2')]:
            old=self.env[key];self.env[key]=bad
            with self.assertRaises(ValueError):m.validate_context(self.env,self.event,self.checkout,self.native,'nt',prepare_privacy=True)
            self.env[key]=old
        self.native['processMachine']=0x8664
        with self.assertRaises(ValueError):m.validate_context(self.env,self.event,self.checkout,self.native,'nt',prepare_privacy=True)

    def test_prepare_flags_do_not_claim_readonly_or_product_readiness(self):
        flags=m.flags(prepare_privacy=True)
        self.assertFalse(flags['readOnly']);self.assertEqual(flags['consentActions'],[])
        for key in ('readiness','hostReadyQualified','productQualified','productExecuted','privacyPreparationQualified','physicalTaskbarGatePassed'):
            self.assertFalse(flags[key])
        self.assertTrue(m.flags()['readOnly']);self.assertEqual(m.flags()['actions'],[])

    def test_source_receipt_includes_action_new_workflow_and_original_gate(self):
        for path in ('e2e/native31_privacy_prepare.py','.github/workflows/office-native31-privacy-prepare.yml',
                     'suite/e2e/native_window_evidence.py'):
            self.assertIn(path,m.SOURCE_FILES)

    def test_workflow_is_exact_and_gate_source_is_original(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/office-native31-privacy-prepare.yml').read_text())
        self.assertEqual(workflow['on'],{'push':{'branches':['work/opengeul-office-native31-privacy-prepare']}})
        job=workflow['jobs']['prepare'];self.assertEqual(job['runs-on'],'windows-11-arm')
        self.assertEqual(job['timeout-minutes'],10);self.assertEqual(job['if'],'github.event.repository.private == false')
        self.assertIn('--prepare-privacy',job['steps'][-2]['run'])
        self.assertEqual(job['steps'][-1]['with']['name'],'opengeul-native31-privacy-preparation-${{ github.run_id }}-${{ github.run_attempt }}')
        self.assertEqual(job['steps'][-1]['with']['retention-days'],1)
        from ci.policy import audit
        audit(workflow)

    def test_only_privacy_kind_can_enter_close(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
            session=p.PreparationSession(m,object(),evidence,m.Budget(),{},self.classification)
            bad=copy.deepcopy(self.candidate);bad['kind']='SearchHost.exe'
            with self.assertRaises(ValueError):session.close(bad)
            self.assertEqual(session.actions,[])

    def test_absence_skips_close_and_runs_original_pointer_once(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
            absence={**m.flags(),'status':'privacy-absent-observed'}
            session=p.PreparationSession(m,object(),evidence,m.Budget(),{},absence)
            calls=[]
            with patch.object(session,'post_state',side_effect=lambda:calls.append('post')), \
                 patch.object(session,'pointer',side_effect=lambda:calls.append('pointer') or session.summary(qualified=True)), \
                 patch.object(session,'close',side_effect=AssertionError('absence must not close')):
                result=session.run()
            self.assertEqual(calls,['post','pointer']);self.assertEqual(result['closeRequests'],0)

    def test_mismatch_fails_with_zero_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
            session=p.PreparationSession(m,object(),evidence,m.Budget(),{}, {'status':'unknown'})
            with self.assertRaises(ValueError):session.run()
            self.assertEqual(session.actions,[])
            failure=json.loads((evidence.path/'p49-preparation.json').read_text())
            self.assertFalse(failure['privacyPreparationQualified']);self.assertEqual(failure['consentActions'],[])


pointer_fixture=load('original_pointer_contract_fixtures',ROOT/'suite/tests/test_native_window_evidence.py')

class ActionContracts(unittest.TestCase):
    setUp = PreparationContracts.setUp
    def session(self, folder, *, outcome='destroyed', drift=None, cleanup=False):
        observed=copy.deepcopy(self.observed); window=observed['foreground']; process=observed['processes'][0]
        raw={k:v for k,v in process.items() if k not in ('imageBytes','imageSha256','peMachine','signature')}
        user=pointer_fixture.Library(); kernel=pointer_fixture.Library(); dwm=pointer_fixture.Library()
        sent=[]; closed=[]; user.SetThreadDpiAwarenessContext.action=lambda *args:1
        user.GetThreadDpiAwarenessContext.action=lambda:1;user.AreDpiAwarenessContextsEqual.action=lambda *args:True
        user.GetForegroundWindow.action=lambda:0 if sent and outcome in ('destroyed','hidden','cloaked') else 12
        user.IsWindow.action=lambda hwnd:not(sent and outcome=='destroyed')
        user.IsWindowVisible.action=lambda hwnd:not(sent and outcome=='hidden')
        def pid(hwnd,value):
            value._obj.value=999 if sent and outcome=='owner' else 200
            return 201
        user.GetWindowThreadProcessId.action=pid
        user.GetWindowTextW.action=lambda hwnd,buffer,size:setattr(buffer,'value',window['title']) or len(window['title'])
        user.GetClassNameW.action=lambda hwnd,buffer,size:setattr(buffer,'value',window['className']) or len(window['className'])
        def times(handle,created,*args):
            created._obj.dwLowDateTime=process['createdFileTime'] & 0xffffffff
            created._obj.dwHighDateTime=process['createdFileTime'] >> 32
            return 1
        kernel.GetProcessTimes.action=times
        def machine(handle,pm,nm): pm._obj.value=0;nm._obj.value=0xAA64;return 1
        kernel.IsWow64Process2.action=machine;kernel.OpenProcess.action=lambda *args:77
        kernel.CloseHandle.action=lambda handle:closed.append(handle) or not cleanup
        def cloak(hwnd,attribute,value,size):
            value._obj.value=int(bool(sent and outcome=='cloaked'))
            return -1 if sent and outcome=='dwm' else 0
        dwm.DwmGetWindowAttribute.action=cloak
        evidence=m.Evidence.create(Path(folder)/'capture',Path(folder),max_files=72)
        def send(*args):
            self.assertTrue((evidence.path/'p21-close-intent.json').is_file())
            self.assertTrue((evidence.path/'p18-fresh-recheck.json').is_file())
            sent.append(args)
            return outcome!='delivery'
        user.SendMessageTimeoutW.action=send
        target={**window,'style':0,'exStyle':0,'rootHwnd':12,'ownerHwnd':0,'ownerAbsent':True}
        state={k:process[k] for k in ('createdFileTime','sessionId','processMachine','nativeMachine','exitCode')}
        probe=SimpleNamespace(user=user,kernel=kernel,dwm=dwm,
            session_id=lambda:1,windows_directory=lambda:r'C:\Windows',
            census=lambda:({'foregroundHwnd':12,'windows':[copy.deepcopy(window)],'truncated':False},[],True),
            target=lambda hwnd:copy.deepcopy(target),window=lambda hwnd:copy.deepcopy(window),
            process_identity=lambda handle,pid:copy.deepcopy(raw),
            startup_process_state=lambda handle,pid:copy.deepcopy(state),
            strict_uia=lambda hwnd:copy.deepcopy(observed['uia'][0]),
            text_value=lambda hwnd,cls=False,**kw:window['className' if cls else 'title'])
        if drift:drift(probe,observed,raw,state)
        session=p.PreparationSession(m,probe,evidence,m.Budget(),{},self.classification)
        session.identity_source=lambda:{'source':{'test':'unchanged'},'host':{'test':'unchanged'}}
        return session,observed,process,sent,closed

    def image_patches(self,process):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(m,'image_receipt',return_value={k:process[k] for k in ('imageBytes','imageSha256','peMachine')}))
        stack.enter_context(patch.object(m,'signatures',return_value=[process['signature']]))
        return stack

    def test_full_fresh_schema_and_long_names_reach_one_unchanged_close(self):
        for outcome in ('destroyed','hidden','cloaked'):
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as temp:
                session,observed,process,sent,closed=self.session(temp,outcome=outcome)
                with self.image_patches(process):result=session.close(self.candidate)
                self.assertTrue(result['surfaceDismissed']);self.assertEqual(len(sent),1)
                self.assertEqual(sent[0][1:6],(0x10,0,0,2,3000));self.assertEqual(session.inputs,0)
                fresh=json.loads((session.evidence.path/'p18-fresh-recheck.json').read_text())['observation']
                self.assertEqual(fresh,observed);self.assertGreater(len(fresh['uia'][0]['nodes'][-1]['name']),256)
                self.assertEqual(fresh['processes'][0]['exitCode'],259);self.assertEqual(fresh['processes'][0]['peMachine'],0xAA64)
                with self.assertRaises(ValueError):session.close(self.candidate)
                self.assertEqual(len(sent),1);self.assertGreaterEqual(len(closed),2)

    def test_fresh_mismatches_and_incomplete_data_send_nothing(self):
        changes=[lambda p,o,r,s:r.update(createdFileTime=1),lambda p,o,r,s:r.update(sessionId=2),
            lambda p,o,r,s:r.update(exitCode=0),lambda p,o,r,s:s.update(nativeMachine=0x8664),
            lambda p,o,r,s:o['uia'][0].update(truncated=True),lambda p,o,r,s:o['uia'][0].update(nodes=[]),
            lambda p,o,r,s:o['uia'][0]['nodes'][0].update(processId=999),
            lambda p,o,r,s:o['foreground'].update(title='Other'),
            lambda p,o,r,s:setattr(p,'target',lambda hwnd:{**o['foreground'],'title':'raced'}),
            lambda p,o,r,s:o['processes'][0].update(imageSha256='d'*64),
            lambda p,o,r,s:o['processes'][0]['signature'].update(status='Invalid',publisherMicrosoft=False)]
        for change in changes:
            with self.subTest(change=changes.index(change)),tempfile.TemporaryDirectory() as temp:
                session,observed,process,sent,closed=self.session(temp,drift=change)
                with self.image_patches(process),self.assertRaises((ValueError,KeyError)):session.close(self.candidate)
                self.assertEqual(sent,[]);self.assertEqual(session.actions,[])
                self.assertTrue((session.evidence.path/'p24-close-cleanup.json').exists())

    def test_delivery_visible_owner_or_query_failure_never_qualifies_or_retries(self):
        for outcome in ('visible','owner','dwm','delivery'):
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as temp:
                session,observed,process,sent,closed=self.session(temp,outcome=outcome)
                clock=iter(range(0,2000,20))
                session.budget=SimpleNamespace(deadline=120,remaining=lambda *args:100)
                with self.image_patches(process),patch.object(m.legacy.time,'monotonic',side_effect=lambda:next(clock)), \
                     patch.object(m.legacy.time,'sleep'),self.assertRaises(ValueError):session.close(self.candidate)
                self.assertEqual(len(sent),1);self.assertFalse(session.summary()['privacyPreparationQualified'])
                self.assertFalse(session.pointer_passed);self.assertEqual(session.inputs,0)
                self.assertTrue((session.evidence.path/'p22-close-delivery.json').exists())

    def test_original_pointer_gate_real_function_once_success_foreign_and_missing(self):
        for outcome,count in [('success',1),('foreign',1),('missing',0)]:
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as temp:
                native=pointer_fixture.NativeWindowEvidenceTests();native.setUp()
                # Assign fields, not structure classes: the original module is freshly imported.
                def appbar(message,data):
                    data._obj.rc.left=0;data._obj.rc.top=1040;data._obj.rc.right=1920;data._obj.rc.bottom=1080;return 1
                native.shell.SHAppBarMessage.action=appbar
                if outcome=='foreign':native.user.GetAncestor.action=lambda *args:777
                if outcome=='missing':native.user.FindWindowW.action=lambda *args:0
                evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
                session=p.PreparationSession(m,object(),evidence,m.Budget(),{},self.classification)
                session.identity_source=lambda:{}
                with patch.object(ctypes,'WinDLL',side_effect=lambda name,**kwargs:native.user if name=='user32' else native.shell,create=True):
                    if outcome=='success':
                        result=session.pointer();self.assertTrue(result['privacyPreparationQualified'])
                    else:
                        with self.assertRaises(AssertionError):session.pointer()
                self.assertEqual(len(native.user.SetPhysicalCursorPos.calls),count)
                self.assertEqual(session.inputs,count);self.assertEqual(session.pointer_invocations,1)
                self.assertEqual(session.pointer_passed,outcome=='success');self.assertEqual(native.context[0],native.previous)
                with self.assertRaises(ValueError):session.pointer()
                receipt=json.loads((evidence.path/'p42-pointer-result.json').read_text())
                self.assertEqual(receipt['inputsPerformed'],count)

    def test_incomplete_pointer_intent_is_unknown_and_unqualified(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
            evidence.write('p40-pointer-intent',{'operation':'physical-taskbar-gate','invocations':1})
            result=p.preparation_receipt(m,evidence)
            self.assertIsNone(result['inputsPerformed']);self.assertFalse(result['privacyPreparationQualified'])
            self.assertEqual(result['physicalPointerGateInvocations'],1)

    def test_finalized_original_pointer_receipt_recovers_count_after_observer_death(self):
        for before,count in [(False,0),(True,1)]:
            with self.subTest(before=before),tempfile.TemporaryDirectory() as temp:
                evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
                evidence.write('p40-pointer-intent',{'operation':'physical-taskbar-gate','invocations':1})
                receipt={'success':False}
                if before:receipt['beforePhysicalPoint']=[12,34]
                evidence.write('p41-original-pointer',receipt)
                result=p.preparation_receipt(m,evidence)
                self.assertEqual(result['inputsPerformed'],count)
                self.assertFalse(result['privacyPreparationQualified'])

    def test_primary_and_handle_cleanup_failure_remain_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            session,observed,process,sent,closed=self.session(temp,cleanup=True,drift=lambda p,o,r,s:r.update(sessionId=2))
            with self.image_patches(process),self.assertRaisesRegex(ValueError,'session mismatch') as raised:session.close(self.candidate)
            self.assertEqual(sent,[])
            self.assertIn('Fresh process handle close failed',str(raised.exception.cleanup_failures))
            receipt=json.loads((session.evidence.path/'p24-close-cleanup.json').read_text())
            self.assertIn('session mismatch',receipt['primaryFailure']['message']);self.assertTrue(receipt['cleanupFailures'])

    def test_controller_failure_clears_qualification_but_keeps_performed_actions(self):
        for failure in ({'forced':True}, {'timedOut':True}, {'cleanupFailure':{'type':'OSError'}}, {'success':False}):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as temp:
                evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
                evidence.write('p49-preparation',{**m.flags(prepare_privacy=True),'privacyPreparationQualified':True,
                    'physicalTaskbarGatePassed':True,'physicalPointerGateInvocations':1,'inputsPerformed':1,
                    'actions':[{'operation':'physical-taskbar-gate'}]})
                result={**m.flags(prepare_privacy=True),'success':True,'naturalExit':True,'exitCode':0,'forced':False,'timedOut':False,**failure}
                p.finalize_preparation(m,evidence,result)
                self.assertFalse(result['success']);self.assertFalse(result['privacyPreparationQualified'])
                self.assertEqual(result['inputsPerformed'],1);self.assertTrue(result['physicalTaskbarGatePassed'])


    def test_complete_capture_close_or_absence_post_state_and_original_gate(self):
        for privacy in (True,False):
            with self.subTest(privacy=privacy),tempfile.TemporaryDirectory() as temp:
                session,observed,process,sent,closed=self.session(temp)
                probe=session.probe;evidence=session.evidence
                if not privacy:
                    observed['foreground'].update(title='Program Manager',className='Progman')
                    observed['uia'][0]['nodes']=[dict(name='Desktop',controlType=50033,automationId='',className='',processId=200,enabled=True,offscreen=False)]
                    probe.target=lambda hwnd:{**observed['foreground'],'style':0,'exStyle':0,'rootHwnd':12,'ownerHwnd':0,'ownerAbsent':True}
                host=dict(processId=45,processMachine=0,nativeMachine=0xAA64,sessionId=1,windowsDirectory=r'C:\Windows',
                    windowsVersion=[10,0,1,2,''],imageOS='test',imageVersion='test',desktop='Default',windowStation='WinSta0',process={'createdFileTime':100})
                probe.identity=lambda:copy.deepcopy(host)
                post_window={**observed['foreground'],'hwnd':99,'processId':300,'threadId':301,'title':'Program Manager','className':'Progman'}
                old_census,old_target=probe.census,probe.target
                def full_census():
                    value,errors,ok=({'foregroundHwnd':99,'windows':[post_window],'truncated':False},[],True) if sent else old_census()
                    value=copy.deepcopy(value);row=value['windows'][0]
                    value['windows'].extend({**row,'hwnd':1000+i,'visible':False} for i in range(255))
                    return value,errors,ok
                probe.census=full_census
                probe.target=lambda hwnd:({**post_window,'style':0,'exStyle':0,'rootHwnd':99,'ownerHwnd':0,'ownerAbsent':True} if sent else old_target(hwnd))
                probe.taskbar=lambda:dict(actualPointHwnd=99 if sent else 12,actualRootHwnd=99 if sent else 12,taskbarHwnd=99 if sent else 12)
                source={**self.checkout,'files':{'test':'a'*64}}
                self.env.update(GITHUB_JOB='prepare',GITHUB_REF=m.PREPARE_BRANCH,GITHUB_WORKFLOW_REF=m.PREPARE_WORKFLOW)
                self.event['ref']=m.PREPARE_BRANCH
                event=Path(temp)/'event.json';event.write_text(json.dumps(self.event))
                controller={'host':host,'sourceFiles':source['files'],'eventSha256':m.legacy.bounded_object(event)[1]}
                evidence.write('10-controller',controller);evidence.write('21-observer-bound',{'processId':45,'createdFileTime':100})
                session.controller=controller
                session.identity_source=p.PreparationSession.identity_source.__get__(session)
                screen=SimpleNamespace(width=100,height=100,save=lambda stream,format:stream.write(b'fake-bounded-screen'))
                native=pointer_fixture.NativeWindowEvidenceTests();native.setUp()
                def appbar(message,data):
                    data._obj.rc.left=0;data._obj.rc.top=1040;data._obj.rc.right=1920;data._obj.rc.bottom=1080;return 1
                native.shell.SHAppBarMessage.action=appbar
                validate=m.validate_context
                with self.image_patches(process),patch.object(os,'environ',{**self.env,'GITHUB_EVENT_PATH':str(event)}), \
                     patch.dict('sys.modules',{'PIL':SimpleNamespace(ImageGrab=SimpleNamespace(grab=lambda all_screens:screen))}), \
                     patch.object(m,'source_receipt',return_value=source), \
                     patch.object(m,'validate_context',side_effect=lambda env,event,checkout,identity,platform,**kw:validate(env,event,checkout,identity,'nt',**kw)), \
                     patch.object(ctypes,'WinDLL',side_effect=lambda name,**kwargs:native.user if name=='user32' else native.shell,create=True):
                    session.classification=m.capture(probe,evidence,session.budget,controller,prepare_privacy=True)
                    result=session.run()
                self.assertTrue(result['privacyPreparationQualified']);self.assertTrue(result['physicalTaskbarGatePassed'])
                self.assertEqual(len(json.loads((evidence.path/'33-window-census.json').read_text())['windows']),256)
                self.assertEqual(len(json.loads((evidence.path/'p31-post-census.json').read_text())['windows']),256)
                if privacy:self.assertEqual(len(json.loads((evidence.path/'p11-fresh-native.json').read_text())['census']['windows']),256)
                self.assertEqual(result['closeRequests'],int(privacy));self.assertEqual(len(sent),int(privacy))
                self.assertEqual(result['inputsPerformed'],1);self.assertEqual(result['consentActions'],[])
                for name in ('80-classification','p31-post-census','p32-post-hit','p35-post-screen-after',
                             'p37-post-source-host','p41-original-pointer','p46-final-source-host','p49-preparation'):
                    self.assertTrue((evidence.path/(name+'.json')).is_file(),name)
                self.assertLessEqual(len(list(evidence.path.iterdir()))+6+9+2,72) # remaining controller records + 3 process owners + second UIA

    def test_close_deadline_exhaustion_before_send_retains_failure_without_request(self):
        with tempfile.TemporaryDirectory() as temp:
            session,observed,process,sent,closed=self.session(temp)
            calls=[]
            def remaining(reserve=0):
                calls.append(reserve)
                if len(calls)==4:raise TimeoutError('original deadline exhausted at send boundary')
                return 100
            session.budget=SimpleNamespace(deadline=120,remaining=remaining)
            with self.image_patches(process),self.assertRaises(TimeoutError):session.close(self.candidate)
            self.assertEqual(sent,[]);self.assertEqual(session.actions,[])
            receipt=json.loads((session.evidence.path/'p24-close-cleanup.json').read_text())
            self.assertEqual(receipt['primaryFailure']['type'],'TimeoutError')

    def test_post_send_primary_timeout_survives_legacy_catch_and_handle_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            session,observed,process,sent,closed=self.session(temp,outcome='visible')
            def state(handle,pid):
                if sent:raise TimeoutError('original deadline exhausted while confirming dismissal')
                return {k:process[k] for k in ('createdFileTime','sessionId','processMachine','nativeMachine','exitCode')}
            session.probe.startup_process_state=state
            session.probe.kernel.CloseHandle.action=lambda handle:not bool(sent)
            with self.image_patches(process),self.assertRaisesRegex(TimeoutError,'confirming dismissal') as raised:session.close(self.candidate)
            self.assertEqual(len(sent),1);self.assertTrue(raised.exception.cleanup_failures)
            self.assertTrue((session.evidence.path/'p23-close-result.json').exists())


    def test_owned_timeout_keeps_unknown_input_and_only_terminates_diagnostic_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
            evidence.write('p40-pointer-intent',{'operation':'physical-taskbar-gate','invocations':1})
            calls=[]
            owner=SimpleNamespace(created=True,create_suspended=lambda:calls.append('create'),assign=lambda:calls.append('assign'),
                identity=lambda:{'processId':45},resume=lambda:calls.append('resume'),wait=lambda seconds:False,
                terminate_owned=lambda:calls.append('terminate-owned'),close=lambda:calls.append('close'),cleanup_outcomes=[])
            budget=m.Budget();deadline=budget.deadline
            result=m.run_owned(owner,budget,evidence,prepare_privacy=True)
            p.finalize_preparation(m,evidence,result)
            self.assertEqual(calls,['create','assign','resume','terminate-owned','close'])
            self.assertTrue(result['forced']);self.assertTrue(result['timedOut']);self.assertFalse(result['success'])
            self.assertFalse(result['privacyPreparationQualified']);self.assertIsNone(result['inputsPerformed'])
            self.assertEqual(budget.deadline,deadline);self.assertEqual(result['consentActions'],[])

    def test_observer_failure_preserves_pointer_intent_unknown_count(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
            evidence.write('10-controller',{})
            def fail():
                evidence.write('p40-pointer-intent',{'operation':'physical-taskbar-gate','invocations':1})
                raise TimeoutError('owned observer budget exhausted')
            class Session:
                def __init__(self,*args):pass
                run=staticmethod(fail)
            action=SimpleNamespace(PreparationSession=Session,preparation_receipt=p.preparation_receipt)
            with patch.object(m,'Probe'),patch.object(m,'capture',return_value=self.classification), \
                 patch.object(m,'privacy_preparation_module',return_value=action),patch.dict('sys.modules',{m.__name__:m}):
                code=m.observer(SimpleNamespace(output=evidence.path,deadline=m.Budget().deadline,prepare_privacy=True))
            self.assertEqual(code,1)
            receipt=json.loads((evidence.path/'89-observer-failure.json').read_text())
            self.assertTrue(receipt['timedOut']);self.assertIsNone(receipt['inputsPerformed'])
            self.assertEqual(receipt['physicalPointerGateInvocations'],1);self.assertFalse(receipt['privacyPreparationQualified'])

    def test_interrupted_final_receipts_keep_unknown_or_recover_original_evidence(self):
        for original in ('partial','complete'):
            with self.subTest(original=original),tempfile.TemporaryDirectory() as temp:
                evidence=m.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72)
                evidence.write('p40-pointer-intent',{'operation':'physical-taskbar-gate','invocations':1})
                (evidence.path/'p49-preparation.json').write_text('{')
                (evidence.path/'p41-original-pointer.json').write_text('{' if original=='partial' else json.dumps({'success':False,'beforePhysicalPoint':[12,34]}))
                result=p.preparation_receipt(m,evidence)
                self.assertEqual(result['inputsPerformed'],None if original=='partial' else 1)
                self.assertFalse(result['privacyPreparationQualified']);self.assertIn('preparationReceiptFailure',result)

class ChromeReadRaceContracts(unittest.TestCase):
    setUp=PreparationContracts.setUp
    session=ActionContracts.session
    image_patches=ActionContracts.image_patches

    def race_session(self, folder, *, api=1, code=1400, length=0, terminal='gone', before_send=False,
                     delivered=True, cleanup=False):
        session,observed,process,sent,closed=self.session(folder,outcome='visible')
        probe=session.probe; state={'alive':True,'fault':False,'error':0,'strictReads':0}
        probe.text_value=m.Probe.text_value.__get__(probe)
        probe.user.IsWindow.action=lambda hwnd:state['alive']
        probe.user.GetForegroundWindow.action=lambda:12 if not state['fault'] or terminal=='foreground' else 99
        probe.user.IsWindowVisible.action=lambda hwnd:not(state['fault'] and terminal=='hidden')
        old_cloak=probe.dwm.DwmGetWindowAttribute.action
        def cloak(hwnd,attribute,value,size):
            if state['fault'] and terminal=='cloaked':value._obj.value=1;return 0
            return old_cloak(hwnd,attribute,value,size)
        probe.dwm.DwmGetWindowAttribute.action=cloak
        old_pid=probe.user.GetWindowThreadProcessId.action
        def pid(hwnd,out):
            if state['fault'] and terminal=='reused':out._obj.value=999;return 202
            return old_pid(hwnd,out)
        probe.user.GetWindowThreadProcessId.action=pid
        old_state=probe.startup_process_state
        def held(handle,pid):
            value=old_state(handle,pid)
            if state['fault']:
                if terminal=='generation':value['createdFileTime']+=1
                if terminal=='native':value['nativeMachine']=0x8664
                if terminal=='session':value['sessionId']+=1
            return value
        probe.startup_process_state=held
        def text(which):
            def read(hwnd,buffer,size):
                if size==258:state['strictReads']+=1
                if size==258 and which==api and not state['fault'] and (sent or before_send):
                    state['fault']=True;state['error']=code
                    if terminal in ('gone','foreground','generation','native','session','deadline','native-error','reappear'):
                        state['alive']=False
                    if 'onFault' in state:state['onFault']()
                    return length
                buffer.value=observed['foreground']['className' if which==2 else 'title']
                return len(buffer.value)
            return read
        probe.user.GetWindowTextW.action=text(1);probe.user.GetClassNameW.action=text(2)
        native_send=probe.user.SendMessageTimeoutW.action
        probe.user.SendMessageTimeoutW.action=lambda *args:bool(native_send(*args) and delivered)
        native_close=probe.kernel.CloseHandle.action
        def close(handle):
            value=native_close(handle)
            if state['fault'] and terminal=='reappear':state['alive']=True
            return value and not(cleanup and bool(sent))
        probe.kernel.CloseHandle.action=close
        if terminal=='deadline':
            session.budget=SimpleNamespace(deadline=120,remaining=lambda *args:
                (_ for _ in ()).throw(TimeoutError('original deadline exhausted')) if state['fault'] else 100)
        if terminal=='native-error':
            probe.user.IsWindow.action=lambda hwnd:(_ for _ in ()).throw(OSError('native observation failed')) if state['fault'] else True
        return session,process,sent,closed,state

    def last_errors(self,state):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(ctypes,'set_last_error',side_effect=lambda value:state.update(error=value),create=True))
        stack.enter_context(patch.object(ctypes,'get_last_error',side_effect=lambda:state['error'],create=True))
        return stack

    def test_actual_getter_marks_only_native_length_error_guard_and_preserves_observation(self):
        for api in (1,2):
            with self.subTest(api=api):
                state={'error':0};user=pointer_fixture.Library();probe=SimpleNamespace(user=user)
                def read(hwnd,buffer,size):state['error']=1400;return 0
                (user.GetWindowTextW if api==1 else user.GetClassNameW).action=read
                observation={}
                with self.last_errors(state),self.assertRaisesRegex(ValueError,'Window text unavailable/truncated') as raised:
                    m.Probe.text_value(probe,12,api==2,observation=observation)
                self.assertEqual(observation,{'apiCode':api,'length':0,'lastError':1400})
                self.assertEqual(raised.exception.native31_chrome_read,observation)
                self.assertIsNot(raised.exception.native31_chrome_read,observation)
                self.assertNotIn('details',m.error_record(raised.exception))

    def test_live_then_invalid_hwnd_then_destroyed_preserves_error_and_one_close(self):
        for api in (1,2):
            with self.subTest(api=api),tempfile.TemporaryDirectory() as temp:
                session,process,sent,closed,state=self.race_session(temp,api=api)
                deadline=session.budget.deadline
                original=m.legacy.WindowsProbe.window_state
                with self.last_errors(state),self.image_patches(process),patch.object(m.legacy.WindowsProbe,'window_state',wraps=original) as observations:
                    result=session.close(self.candidate)
                self.assertEqual(observations.call_count,4) # before/send-poll/one terminal/post-release
                self.assertTrue(result['surfaceDismissed']);self.assertIsNone(result['postSendErrorType'])
                self.assertEqual(result['dismissalKind'],'destroyed');self.assertEqual(len(sent),1)
                self.assertEqual(result['afterHandleReleaseState']['dismissalKind'],'destroyed')
                self.assertEqual(closed,[77,77]);self.assertEqual(session.budget.deadline,deadline)
                record=result['postCloseTextRecheck']
                self.assertEqual(record['attempted'],1);self.assertEqual(record['recovered'],1)
                self.assertEqual(record['chromeRead'],{'apiCode':api,'length':0,'lastError':1400})
                self.assertEqual(record['originalFailure']['type'],'ValueError')
                self.assertEqual(record,session.summary()['postCloseTextRecheck'])
                self.assertEqual(record,json.loads((session.evidence.path/'p25-post-close-text-recheck.json').read_text()))
                self.assertEqual(session.inputs,0);self.assertEqual(session.pointer_invocations,0)
                self.assertFalse(session.summary()['privacyPreparationQualified'])
                with self.assertRaises(ValueError):session.close(self.candidate)
                self.assertEqual(len(sent),1)

    def test_before_send_or_unconfirmed_delivery_cannot_recheck(self):
        for before,delivered in ((True,True),(False,False)):
            with self.subTest(before=before,delivered=delivered),tempfile.TemporaryDirectory() as temp:
                session,process,sent,closed,state=self.race_session(temp,before_send=before,delivered=delivered)
                with self.last_errors(state),self.image_patches(process),self.assertRaisesRegex(ValueError,'Window text unavailable/truncated'):
                    session.close(self.candidate)
                self.assertEqual(len(sent),int(not before))
                record=session.summary()['postCloseTextRecheck']
                self.assertEqual((record['attempted'],record['recovered']),(0,0))
                self.assertEqual(session.inputs,0)

    def test_live_reuse_generation_foreground_deadline_and_native_failure_remain_failures(self):
        for terminal in ('live','hidden','cloaked','reused','generation','native','session','foreground','deadline','native-error'):
            with self.subTest(terminal=terminal),tempfile.TemporaryDirectory() as temp:
                session,process,sent,closed,state=self.race_session(temp,terminal=terminal)
                original=m.legacy.WindowsProbe.window_state;terminal_states=[]
                def observe(adapter,candidate,handle):
                    value=original(adapter,candidate,handle)
                    if state['fault']:
                        terminal_states.append({key:value[key] for key in ('windowExists','cloakedBits','dismissalKind')})
                    return value
                with self.last_errors(state),self.image_patches(process), \
                     patch.object(m.legacy.WindowsProbe,'window_state',side_effect=observe), \
                     self.assertRaisesRegex(ValueError,'Window text unavailable/truncated'):
                    session.close(self.candidate)
                record=session.summary()['postCloseTextRecheck']
                self.assertEqual((record['attempted'],record['recovered']),(1,0))
                self.assertEqual(record['originalFailure']['type'],'ValueError')
                self.assertEqual(len(sent),1);self.assertEqual(session.inputs,0)
                self.assertFalse(session.summary()['privacyPreparationQualified'])
                if terminal=='cloaked':
                    self.assertEqual(terminal_states[0],{'windowExists':True,'cloakedBits':1,'dismissalKind':'cloaked'})

    def test_other_error_length_or_unmarked_mismatch_is_not_recovered(self):
        for code,length in ((5,0),(0,257),(1400,1)):
            with self.subTest(code=code,length=length),tempfile.TemporaryDirectory() as temp:
                session,process,sent,closed,state=self.race_session(temp,code=code,length=length)
                with self.last_errors(state),self.image_patches(process),self.assertRaises(ValueError):session.close(self.candidate)
                self.assertEqual(session.summary()['postCloseTextRecheck']['attempted'],0)
                self.assertEqual(len(sent),1)
        with tempfile.TemporaryDirectory() as temp:
            session,observed,process,sent,closed=self.session(temp,outcome='visible')
            def mismatch(hwnd,cls=False,**kw):return 'synthetic mismatch' if sent else observed['foreground']['className' if cls else 'title']
            session.probe.text_value=mismatch
            with self.image_patches(process),self.assertRaisesRegex(ValueError,'Privacy window text raced/truncated'):session.close(self.candidate)
            self.assertNotIn('postCloseTextRecheck',session.summary());self.assertEqual(len(sent),1)

    def test_cleanup_and_post_release_confirmation_still_block_close(self):
        for terminal,cleanup in (('gone',True),('reappear',False)):
            with self.subTest(terminal=terminal,cleanup=cleanup),tempfile.TemporaryDirectory() as temp:
                session,process,sent,closed,state=self.race_session(temp,terminal=terminal,cleanup=cleanup)
                with self.last_errors(state),self.image_patches(process),self.assertRaises(ValueError):session.close(self.candidate)
                self.assertEqual(session.summary()['postCloseTextRecheck']['recovered'],1)
                self.assertEqual(len(sent),1);self.assertFalse(session.summary()['privacyPreparationQualified'])

    def test_getter_invocation_and_later_text_validation_never_receive_recovery_marker(self):
        user=pointer_fixture.Library();probe=SimpleNamespace(user=user);state={'error':0}
        def invalid_text(hwnd,buffer,size):buffer.value='synthetic\ninvalid';return len(buffer.value)
        for action,kind in ((lambda *args:(_ for _ in ()).throw(OSError('native read failed')),OSError),
                            (invalid_text,ValueError)):
            user.GetWindowTextW.action=action;observation={}
            with self.last_errors(state),self.assertRaises(kind) as raised:
                m.Probe.text_value(probe,12,observation=observation)
            self.assertFalse(hasattr(raised.exception,'native31_chrome_read'))
            if kind is OSError:self.assertEqual(observation,{'apiCode':1,'length':None,'lastError':None})
        user.GetWindowTextW.action=lambda *args:state.update(error=1400) or 0
        with self.last_errors(state),self.assertRaises(ValueError) as raised:m.Probe.text_value(probe,12)
        self.assertFalse(hasattr(raised.exception,'native31_chrome_read'))

    def test_original_candidate_or_retained_handle_change_cannot_start_terminal_observation(self):
        for mutation in ('handle','candidate'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as temp:
                session,process,sent,closed,state=self.race_session(temp)
                adapters=[];init=p.PrivacyAdapter.__init__
                def remember(adapter,*args):init(adapter,*args);adapters.append(adapter)
                def change():
                    if mutation=='handle':adapters[0].held=88
                    else:self.candidate['window']['threadId']+=1
                state['onFault']=change
                original=m.legacy.WindowsProbe.window_state
                with self.last_errors(state),self.image_patches(process),patch.object(p.PrivacyAdapter,'__init__',remember), \
                     patch.object(m.legacy.WindowsProbe,'window_state',wraps=original) as observations, \
                     self.assertRaisesRegex(ValueError,'Window text unavailable/truncated'):
                    session.close(self.candidate)
                self.assertEqual(observations.call_count,3) # terminal admission refused
                self.assertEqual(session.summary()['postCloseTextRecheck']['attempted'],0)
                self.assertEqual(len(sent),1)

    def test_generation_change_after_terminal_query_preserves_first_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            session,process,sent,closed,state=self.race_session(temp)
            original=session.probe.startup_process_state;after=[]
            def held(handle,pid):
                value=original(handle,pid)
                if state['fault']:
                    after.append(1)
                    if len(after)==2:value['createdFileTime']+=1
                return value
            session.probe.startup_process_state=held
            with self.last_errors(state),self.image_patches(process),self.assertRaisesRegex(ValueError,'Window text unavailable/truncated'):
                session.close(self.candidate)
            record=session.summary()['postCloseTextRecheck']
            self.assertEqual((record['heldBefore'],record['heldAfter'],record['recovered']),(1,0,0))
            self.assertEqual(len(sent),1);self.assertEqual(session.inputs,0)

    def test_terminal_receipt_failure_blocks_recovered_state(self):
        with tempfile.TemporaryDirectory() as temp:
            session,process,sent,closed,state=self.race_session(temp)
            write=session.evidence.write
            def fail(name,value):
                if name=='p25-post-close-text-recheck':raise OSError('synthetic evidence failure')
                return write(name,value)
            with self.last_errors(state),self.image_patches(process),patch.object(session.evidence,'write',side_effect=fail), \
                 self.assertRaisesRegex(ValueError,'Window text unavailable/truncated') as raised:
                session.close(self.candidate)
            self.assertEqual(session.summary()['postCloseTextRecheck']['recovered'],0)
            self.assertTrue(raised.exception.cleanup_failures)
            self.assertEqual(len(sent),1);self.assertFalse(session.summary()['privacyPreparationQualified'])

if __name__=='__main__':unittest.main()
