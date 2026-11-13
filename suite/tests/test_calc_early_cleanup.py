"""Failure-only cleanup boundaries; fake actors do not qualify Windows UIA."""
import copy
import ctypes
import hashlib
import importlib
import json
import os
import time
import uuid
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
sys.path.insert(0,str(Path(__file__).resolve().parent))


class EarlyCleanupTests(unittest.TestCase):
    def setUp(self):
        self.m=importlib.import_module('calc_early_cleanup')
        self.record=dict(case='calc-active-cell-save',kind='physical-uncommitted-calc-save',module='calc',
            success=False,stage='launch',navigationKeys=[],commitKeys=[],saveShortcutCount=0)

    def test_exact_early_boundary_requires_explicit_never_started_and_no_input(self):
        self.m.require_early(self.record,True,None)
        mutations=[dict(success=True),dict(stage='physical-edit-without-enter'),dict(navigationKeys=['^{HOME}']),
            dict(commitKeys=['{ENTER}']),dict(saveShortcutCount=1),dict(physicalAsciiMarker='x'),
            dict(editorFocusReadiness={'clickAttempts':1,'controlF6Attempts':0}),
            dict(editorFocusReadinessRecords=[{'clickAttempts':0,'controlF6Attempts':1}])]
        for change in mutations:
            with self.subTest(change=change),self.assertRaises((AssertionError,ValueError)):
                self.m.require_early(dict(self.record,**change),True,None)
        for flag,observer in [(False,None),(None,None),(1,None),(True,{}),(True,{'physicalCleanupSucceeded':True})]:
            with self.subTest(flag=flag,observer=observer),self.assertRaises((AssertionError,ValueError)):
                self.m.require_early(self.record,flag,observer)

    def test_strict_json_rejects_duplicate_nonfinite_and_size(self):
        for data in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}',b'[]',b' '*70000):
            with self.assertRaises((AssertionError,ValueError)):
                self.m.read_json(data)
        self.assertEqual(134370086799550953,self.m.read_json(b'{"generation":134370086799550953}')['generation'])

    def test_actor_normal_and_timeout_require_death_before_return(self):
        for hung in (False,True):
            clock=[0.];events=[]
            class Actor:
                def snapshot(self):return {'pids':[9] if hung and 'terminate' not in events else [],'waitResult':258 if hung and 'terminate' not in events else 0,'exitCode':1 if hung else 0}
                def terminate(self):events.append('terminate')
                def close(self):events.append('close')
            def sleep(n):clock[0]+=n
            result=self.m.await_actor(Actor(),5.,10.,clock=lambda:clock[0],sleep=sleep)
            self.assertTrue(result['deathProved']);self.assertEqual(hung,result['forced'])
            self.assertEqual(hung,result['timedOut']);self.assertEqual('close',events[-1])
            if hung:self.assertEqual(['terminate','close'],events)

    def test_actor_unproved_death_retains_handles_and_blocks_fallback(self):
        clock=[0.];events=[]
        class Actor:
            def snapshot(self):return dict(pids=[9],waitResult=258,exitCode=259)
            def terminate(self):events.append('terminate')
            def close(self):events.append('close')
        r=self.m.await_actor(Actor(),1.,2.,clock=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n))
        self.assertFalse(r['deathProved']);self.assertNotIn('close',events)
        self.assertFalse(r['fallbackAllowed'])

    def test_proved_dead_actor_with_partial_handle_release_keeps_explicit_owner(self):
        class Actor:
            def snapshot(self):return dict(pids=[],waitResult=0,exitCode=0)
            def close(self):raise OSError('one original handle close failed')
        actor=Actor()
        with patch.object(self.m,'_RETAINED_ACTORS',[]) as retained:
            result=self.m.await_actor(actor,1,2,clock=lambda:0)
            self.assertTrue(result['deathProved'])
            self.assertFalse(result.get('handlesReleased',True))
            self.assertEqual([actor],retained)
            self.assertTrue(result['errors'])

    def test_inflight_invoke_cannot_be_reported_zero_or_normal_after_actor_timeout(self):
        for intent in (False,True):
            r=self.m.invoke_outcome(dict(deathProved=True,forced=True,timedOut=True,exitCode=1),
                {'invokeIntent':True} if intent else None,None)
            self.assertIsNone(r['invocationsPerformed']);self.assertFalse(r['normal'])
            self.assertEqual(intent,r['invokeIntentRetained'])

    def test_natural_actor_requires_exact_original_final_receipt(self):
        r=self.m.invoke_outcome(dict(deathProved=True,forced=False,timedOut=False,exitCode=0),
            {'invokeIntent':True,'invokeAttempts':1},{'success':True,'invokeReturned':True,'invokeAttempts':1})
        self.assertTrue(r['normal']);self.assertEqual(1,r['invocationsPerformed'])
        for final in (None,{},dict(success=True,invokeReturned=True,invokeAttempts=2)):
            self.assertFalse(self.m.invoke_outcome(dict(deathProved=True,forced=False,timedOut=False,exitCode=0),None,final)['normal'])

    def test_pre_resume_containment_and_original_handles_survive_partial_launch(self):
        actor=importlib.import_module('calc_failure_actor')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
        import native_windows as structs
        for fail in (None,'create','assign','membership','identity','resume'):
            with self.subTest(fail=fail):
                calls=[];state={'dead':False,'assigned':False}
                def create(*args):
                    calls.append('create-suspended')
                    self.assertEqual(0x08000004,args[5]);self.assertFalse(args[4])
                    if fail=='create':return False
                    info=args[-1]._obj;info.hProcess=11;info.hThread=12;info.dwProcessId=9
                    return True
                def assign(job,handle):
                    calls.append('assign');self.assertEqual((13,11),(job,handle))
                    state['assigned']=fail!='assign';return state['assigned']
                def member(handle,job,out):
                    calls.append('membership');out._obj.value=fail!='membership';return True
                def resume(thread):
                    calls.append('resume');self.assertTrue(state['assigned'])
                    return 0xffffffff if fail=='resume' else 1
                def terminate(*args):calls.append('terminate-job');state['dead']=True;return True
                def kill(*args):calls.append('kill-original-suspended');state['dead']=True;return True
                def close(handle):calls.append('close-'+str(handle));return True
                kernel=NS(CreateJobObjectW=lambda *a:13,SetInformationJobObject=lambda *a:True,
                    CreateProcessW=create,AssignProcessToJobObject=assign,
                    ResumeThread=resume,CloseHandle=close,TerminateJobObject=terminate,TerminateProcess=kill)
                class Api:
                    is_in_job=staticmethod(member)
                    def identity(self,h):
                        calls.append('identity')
                        if fail=='identity':raise ValueError('bad identity')
                        return dict(image=sys.executable,creationTime=9007199254741007)
                    def job_pids(self,j,record=None):
                        pids=[9] if state['assigned'] and not state['dead'] else []
                        if record:record(dict(classification='complete',pids=pids))
                        return pids
                    def state(self,h):return dict(waitResult=0 if state['dead'] else 258,exitCode=1 if state['dead'] else 259)
                module=NS(ProcessDiagnosticsApi=Api,windows_dll=lambda n:kernel,bind=lambda k,n,a,r:getattr(k,n),
                    ProcessInfo=structs.ProcessInfo,StartupInfo=structs.StartupInfo)
                # ctypes.WinError is Windows-only; errors are nevertheless retained, never resumed.
                with patch.object(actor,'native_module',return_value=module):p=actor.ActorProcess([sys.executable,'-B','actor.py'],Path.cwd())
                if fail:
                    self.assertIsNotNone(p.launch['launchError'])
                    if fail!='resume':self.assertNotIn('resume',calls)
                else:
                    self.assertEqual(['create-suspended','assign','membership','identity','resume'],calls)
                    self.assertEqual((11,12,13),(p.handle,p.thread,p.job))
                p.terminate();p.close()
                self.assertEqual(['close-12','close-11','close-13'] if fail!='create' else ['close-13'],calls[-(3 if fail!='create' else 1):])
                if fail=='assign':self.assertIn('kill-original-suspended',calls);self.assertNotIn('terminate-job',calls)

    def test_request_exact_bytes_sources_paths_and_integer_types(self):
        actor=importlib.import_module('calc_failure_actor')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();folder=root/('failure-cleanup-'+'a'*32);folder.mkdir()
            value=dict(schemaVersion=1,kind='failed-calc-discard-actor',nonce='a'*32,case=self.record['case'],
                deadline=20.,suite=str(root/'suite'),fixture=str(root/'fixtures/OpenGeul-calc.xlsx'),fixtureSha256='b'*64,
                fixtureBytes=10,shellPid=7,shellCreation=9007199254741007,enginePid=8,engineCreation=9007199254741008,
                hwnd=10,parent=15,child=20,command=[str(root/'suite/OpenGeul.Office.exe'),'--module','calc','--file',str(root/'fixtures/OpenGeul-calc.xlsx')],
                record=self.record,sourcePins=self.m.source_pins())
            path=folder/'request.json'
            def read(row):
                raw=json.dumps(row).encode();path.write_bytes(raw)
                with patch.object(actor.time,'monotonic',return_value=0.):return actor.load_request(path,hashlib.sha256(raw).hexdigest(),'a'*32)
            self.assertEqual(value,read(value))
            for change in (dict(shellCreation=True),dict(nonce='c'*32),dict(fixture=str(root/'foreign.xlsx')),
                           dict(command=[]),dict(sourcePins={}),dict(deadline=61.),dict(extra=True)):
                with self.subTest(change=change),self.assertRaises((AssertionError,KeyError,ValueError)):read(dict(value,**change))
            raw=path.read_bytes()
            with self.assertRaises(AssertionError):actor.load_request(path,'0'*64,'a'*32)


class InvokeActorTests(unittest.TestCase):
    def setUp(self):
        self.actor=importlib.import_module('calc_failure_actor')
        import test_generated_calc_close as fixtures
        self.fixture=fixtures.GeneratedCalcCloseTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.Desktop,self.accessible,self.buttons=self.fixture.boundary();f=self.fixture
        f.prompt=True;self.invokes=[];self.outputs=[];self.guards=0
        for index,b in enumerate(self.buttons):
            b.element_info.control_id=100+index;b.element_info.runtime_id=[42,30,100+index]
            b.iface_invoke=NS(Invoke=lambda:self.invokes.append('discard'))
        f.windows.user.GetDlgCtrlID=lambda h:101
        self.guard=NS(request=dict(deadline=100.,shellPid=7,hwnd=10),api=f.windows,check=self.check)
        import lifecycle_smoke as lifecycle
        for p in (patch.dict(sys.modules,{'pywinauto':NS(Desktop=self.Desktop)}),
                  patch.object(lifecycle,'require_dialog_button_ancestry',return_value=[{'controlType':'Button','nativeHandle':1},{'controlType':'Window'}]),
                  patch.object(lifecycle,'dialog_uia_identity',return_value={'pid':7}),
                  patch.object(self.actor.time,'monotonic',return_value=0.)):
            p.start();self.addCleanup(p.stop)
    def check(self):self.guards+=1
    def emit(self,name,value):self.outputs.append((name,value))
    def test_exact_original_discard_one_invoke_no_focus_or_physical_input(self):
        self.fixture.windows.require_foreground=lambda *a:self.fail('foreground forbidden')
        for b in self.buttons:b.click_input=lambda:self.fail('physical input forbidden')
        result=self.actor.invoke_one(self.guard,self.emit)
        self.assertTrue(result['success']);self.assertEqual(['discard'],self.invokes)
        self.assertEqual(['20-prompt.json','30-invoke-intent.json'],[n for n,_ in self.outputs])
        self.assertGreaterEqual(self.guards,5)
    def test_foreign_ambiguous_missing_pattern_or_changed_id_never_invokes(self):
        for reason in ('foreign','ambiguous','pattern','changed-id','changed-generation','changed-after-intent'):
            with self.subTest(reason=reason):
                self.setUp()
                f=self.fixture
                if reason=='foreign':f.pid=lambda h:999 if h==30 else 7
                elif reason=='ambiguous':f.windows.windows=lambda p:[30,31];f.owner=lambda h,k:10
                elif reason=='pattern':self.buttons[1].iface_invoke=NS()
                elif reason=='changed-id':f.windows.user.GetDlgCtrlID=lambda h:999
                elif reason=='changed-generation':self.guard.check=lambda:(_ for _ in ()).throw(AssertionError('generation drift'))
                else:
                    def emit(name,value):
                        self.outputs.append((name,value))
                        if name=='30-invoke-intent.json':self.buttons[1].element_info.runtime_id=[42,99]
                    self.emit=emit
                with self.assertRaises(AssertionError):self.actor.invoke_one(self.guard,self.emit)
                self.assertEqual([],self.invokes)
    def test_invoke_throws_after_intent_without_retry(self):
        def invoke():self.invokes.append('attempt');raise RuntimeError('provider failed after dispatch')
        self.buttons[1].iface_invoke.Invoke=invoke
        with self.assertRaisesRegex(RuntimeError,'after dispatch'):self.actor.invoke_one(self.guard,self.emit)
        self.assertEqual(['attempt'],self.invokes);self.assertEqual('30-invoke-intent.json',self.outputs[-1][0])


class CompleteEarlyPathTests(unittest.TestCase):
    def setUp(self):
        import test_calc_failure_cleanup as fixture
        self.boundary=fixture.CalcFailureCleanupTests();self.boundary.setUp();self.addCleanup(self.boundary.doCleanups)
        self.m=importlib.import_module('calc_early_cleanup');self.actor=importlib.import_module('calc_failure_actor')
        self.f=self.boundary.fixture;f=self.f
        f.record.update(stage='launch',error='original SetForegroundWindow failure')
        f.process.opengeul_evidence_output=f.root
        self.events=[]
        original=f.windows.request_close
        def close(hwnd,pid):
            original(hwnd,pid)
            if hwnd==40:f.exit_code=0
        f.windows.request_close=close;f.windows.home=lambda p:40
        self.proof=self.boundary.proof
        diag=f.root/'diagnostics'/('b'*32);diag.mkdir(parents=True)
        raw=json.loads((Path(__file__).parent/'fixtures/owned-office-shutdown.json').read_bytes())['graceful']
        raw['expectedEngineImage']=str(f.suite/'Office/program/soffice.bin')
        for key in ('initialMembers','finalMembers'):
            for row in raw[key]:
                if row['image'].lower().endswith('soffice.bin'):
                    row.update(image=raw['expectedEngineImage'],pid=8,creationTime=self.proof.engine.creation)
        data=json.dumps(raw).encode();(diag/'shutdown.json').write_bytes(data)
        manifest=dict(schemaVersion=1,kind='owned-office-native-diagnostics',archiveComplete=True,launcherPid=raw['launcherPid'],
            files=[dict(path='shutdown.json',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())])
        (diag/'manifest.json').write_text(json.dumps(manifest));self.diag=diag

    def finish(self,mode='normal',mutation=None):
        test=self;f=self.f
        class Actor:
            def __init__(self,argv,cwd):
                request=json.loads((cwd/'request.json').read_bytes());self.launch={'launchError':None,'modelOnly':True}
                base=dict(nonce=request['nonce'],case=request['case'],requestSha256=hashlib.sha256((cwd/'request.json').read_bytes()).hexdigest())
                discard=dict(dialogHwnd=30,buttonHwnd=31,controlId=101,runtimeId=[42,31],shellPid=7)
                rows={'10-bound.json':dict(shellCreation=request['shellCreation'],engineCreation=request['engineCreation'],shellHandleValue=7,engineHandleValue=8),
                    '20-prompt.json':dict(discard=discard,observation=dict(ready=True,dialogHwnd=30,ownerHwnd=10,shellPid=7)),
                    '30-invoke-intent.json':dict(invokeIntent=True,invokeAttempts=1,discard=discard),
                    '99-result.json':dict(success=True,invokeReturned=True,invokeAttempts=1,discard=discard)}
                if mode!='normal':rows.pop('99-result.json')
                if mutation:mutation(rows)
                for name,row in rows.items():test.m.write_original(cwd/name,dict(row,**base))
                if mode=='normal':f.live.discard(20);f.live.discard(10)
            def snapshot(self):return dict(pids=[],waitResult=0,exitCode=0)
            def terminate(self):test.events.append('actor-kill')
            def close(self):test.events.append('actor-close')
        def awaited(actor,*args):
            test.events.append('actor-join')
            return dict(deathProved=mode!='unproved',fallbackAllowed=mode!='unproved',forced=True,timedOut=True,exitCode=1,errors=[])
        def fallback(process,record):
            self.assertIsNotNone(self.proof.shell.handle);self.assertIsNotNone(self.proof.engine.handle)
            self.events.append('legacy-fallback');f.exit_code=1
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.actor,'ActorProcess',Actor))
            stack.enter_context(patch('windows_smoke.stop_owned_test_process',side_effect=fallback))
            if mode!='normal':stack.enter_context(patch.object(self.m,'await_actor',side_effect=awaited))
            self.boundary.api.finish_pre_input_cleanup(f.windows,f.process,f.record,self.proof,None,observer_never_started=True)
        return f.record['failureCleanup']

    def test_full_normal_failure_cleanup_requires_original_archive_and_retained_deaths(self):
        r=self.finish()
        self.assertTrue(r['success'],r);self.assertFalse(self.f.record['success'])
        self.assertFalse(r['productShutdownQualified']);self.assertTrue(r['workerArchive']['complete'])
        self.assertEqual([(10,7),(40,7)],self.f.closes);self.assertEqual(['actor-close'],self.events)
        self.assertEqual(1,r['documentCloseMessageCount']);self.assertEqual(1,r['homeCloseMessageCount'])
        self.assertTrue(r['homeCloseIntent']['originalShellLive'])
        self.assertEqual('original SetForegroundWindow failure',self.f.record['error'])
        self.assertTrue(r['productHandlesReleased'])
        stored=json.loads(Path(r['parentReceiptPath']).read_bytes());self.assertTrue(stored['productHandlesReleased'])

    def test_timeout_partial_invoke_is_unknown_and_no_later_gui_action_precedes_owned_fallback(self):
        r=self.finish('timeout')
        self.assertFalse(r['success']);self.assertIsNone(r['invoke']['invocationsPerformed'])
        self.assertEqual([(10,7)],self.f.closes)
        self.assertEqual(['actor-join','legacy-fallback'],self.events)
        with self.assertRaisesRegex(AssertionError,'no later GUI'):self.m.require_launch_permitted()
        self.assertIsNone(r['legacyRecovery']['forced']);self.assertFalse(r['legacyRecovery']['descendantsDeathProved'])
        self.assertTrue(r['productHandlesReleased'])

    def test_actor_death_unproved_blocks_fallback_and_retains_product_handles(self):
        r=self.finish('unproved')
        self.assertFalse(r['success']);self.assertEqual(['actor-join'],self.events)
        self.assertTrue(r['productWitnessesRetained']);self.assertFalse(r['productHandlesReleased'])
        self.assertEqual([(10,7)],self.f.closes)

    def test_incomplete_archive_or_changed_actor_identity_never_qualifies_cleanup(self):
        manifest=json.loads((self.diag/'manifest.json').read_bytes());manifest['archiveComplete']=False
        (self.diag/'manifest.json').write_text(json.dumps(manifest))
        r=self.finish();self.assertFalse(r['success']);self.assertNotIn('workerArchive',r)
        self.assertFalse(self.f.record['success'])

    def test_actor_missing_original_intent_cannot_be_inferred_from_success(self):
        r=self.finish(mutation=lambda rows:rows.pop('30-invoke-intent.json'))
        self.assertFalse(r['success']);self.assertIsNone(r['invoke']['invocationsPerformed'])
        self.assertEqual([(10,7)],self.f.closes)

    def test_late_actor_generation_drift_rejects_normal_result(self):
        r=self.finish(mutation=lambda rows:rows['10-bound.json'].update(engineCreation=1))
        self.assertFalse(r['success']);self.assertEqual([(10,7)],self.f.closes)

    def test_original_raw_events_journal_is_retained_and_admitted(self):
        (self.diag/'events.jsonl').write_bytes(b'{"event":"original"}\n')
        r=self.finish()
        self.assertTrue(r['success'],r)

    def test_archive_member_alias_is_rejected(self):
        p=self.diag/'manifest.json';manifest=json.loads(p.read_bytes())
        manifest['files'][0]['path']='./shutdown.json';p.write_bytes(json.dumps(manifest).encode())
        r=self.finish();self.assertFalse(r['success'],r)

    def test_changed_home_identity_is_rejected(self):
        homes=iter([40,41]);self.f.windows.home=lambda process:next(homes)
        r=self.finish();self.assertFalse(r['success'],r)
        self.assertEqual([(10,7)],self.f.closes)

    def test_unlisted_archive_file_rejects_complete_cleanup(self):
        (self.diag/'unlisted.txt').write_bytes(b'unlisted original')
        r=self.finish()
        self.assertFalse(r['success'],r)
        self.assertNotIn('workerArchive',r)
        self.assertTrue((self.diag/'unlisted.txt').is_file())

    def test_dead_original_shell_cannot_authorize_home_close(self):
        def dead_home(process):
            self.f.exit_code=0
            return 40
        self.f.windows.home=dead_home
        r=self.finish()
        self.assertFalse(r['success'],r)
        self.assertEqual([(10,7)],self.f.closes)

    def test_expired_deadline_prevents_initial_document_close(self):
        clock=[0.]
        pins=self.m.source_pins
        def slow_pins():
            value=pins();clock[0]=61.;return value
        with patch.object(self.m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(self.m,'source_pins',side_effect=slow_pins):
            r=self.finish()
        self.assertFalse(r['success'],r)
        self.assertEqual([],self.f.closes)

    def test_expired_home_action_reserve_prevents_home_close(self):
        clock=[0.]
        def slow_home(process):clock[0]=39.;return 40
        self.f.windows.home=slow_home
        wait=self.m.await_actor
        with patch.object(self.m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(self.m,'await_actor',side_effect=lambda a,d,r:wait(a,d,r,clock=lambda:clock[0])):r=self.finish()
        self.assertFalse(r['success'],r)
        self.assertEqual([(10,7)],self.f.closes)

    def test_actor_native_guard_rechecks_fixture_generations_and_window_lineage(self):
        import lifecycle_smoke
        f=self.f
        guard=self.actor.Guard.__new__(self.actor.Guard)
        guard.request=dict(deadline=100.,shellPid=7,enginePid=8,suite=str(f.suite),fixture=str(f.source),
            fixtureBytes=len(f.data),fixtureSha256=f.digest,hwnd=10,parent=15,child=20)
        guard.shell,guard.engine=self.proof.shell,self.proof.engine
        guard.api,guard.lifecycle=f.windows,lifecycle_smoke
        pid=f.windows.pid;f.windows.pid=lambda h:7 if h in (10,15) else 8
        with patch.object(self.actor.time,'monotonic',return_value=0.):
            guard.check()
            for reason in ('fixture','generation','parent','root','dead'):
                with self.subTest(reason=reason):
                    old_child=f.windows.user.IsChild;old_root=f.windows.user.GetAncestor
                    if reason=='fixture':f.source.write_bytes(b'changed')
                    elif reason=='generation':self.boundary.generations[8]+=1
                    elif reason=='parent':f.windows.user.IsChild=lambda *a:False
                    elif reason=='root':f.windows.user.GetAncestor=lambda *a:99
                    else:f.live.discard(20)
                    with self.assertRaises(AssertionError):guard.check()
                    f.source.write_bytes(f.data);self.boundary.generations[8]=self.proof.engine.creation
                    f.windows.user.IsChild=old_child;f.windows.user.GetAncestor=old_root;f.live.add(20)
        f.windows.pid=pid


@unittest.skipUnless(os.name == 'nt', 'Real Win32 helper containment requires Windows; model tests are separate')
class NativeBenignActorTests(unittest.TestCase):
    """Exact production helper lifecycle, with no Office, UIA or GUI actions."""
    def exercise(self, hanging):
        from calc_failure_actor import ActorProcess
        from calc_early_cleanup import await_actor
        with tempfile.TemporaryDirectory(prefix='opengeul-benign-actor-') as directory:
            root=Path(directory);marker=root/'started.txt';nonce=uuid.uuid4().hex
            code='import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_bytes(sys.argv[2].encode("ascii")); '
            code+='time.sleep(60)' if hanging else 'sys.exit(0)'
            started=time.monotonic()
            actor=ActorProcess([sys.executable,'-I','-S','-c',code,str(marker),nonce],root)
            result=await_actor(actor,started+10,started+15)
            receipt=dict(kind='real-win32-benign-actor-lifecycle',hanging=hanging,
                launch=actor.launch,result=result,elapsedSeconds=time.monotonic()-started)
            raw=json.dumps(receipt,allow_nan=False,separators=(',',':'))
            self.assertLess(len(raw.encode()),8192)
            print('OPEN_GEUL_BENIGN_ACTOR '+raw,flush=True)
            self.assertIsNone(actor.launch['launchError'],receipt)
            self.assertTrue(actor.assigned);self.assertTrue(actor.resumed)
            calls=actor.launch['calls'];names=[row['api'] for row in calls]
            self.assertLess(names.index('AssignProcessToJobObject'),names.index('ResumeThread'))
            self.assertLess(names.index('IsProcessInJob'),names.index('ResumeThread'))
            self.assertEqual(0x08000004,next(r for r in calls if r['api']=='CreateProcessW')['flags'])
            self.assertTrue(next(r for r in calls if r['api']=='IsProcessInJob')['inJob'])
            self.assertEqual(1,next(r for r in calls if r['api']=='ResumeThread')['previousSuspendCount'])
            self.assertGreater(actor.launch['pid'],0)
            self.assertGreater(actor.launch['identity']['creationTime'],0)
            for key in ('processHandleValue','threadHandleValue','jobHandleValue'):self.assertGreater(actor.launch[key],0)
            self.assertEqual(nonce.encode(),marker.read_bytes())
            self.assertTrue(result['deathProved']);self.assertTrue(result['handlesReleased'])
            self.assertEqual([],result['final']['pids']);self.assertEqual(0,result['final']['waitResult'])
            self.assertEqual([],result['errors']);self.assertEqual(hanging,result['forced'])
            self.assertEqual(hanging,result['timedOut']);self.assertEqual(1 if hanging else 0,result['exitCode'])
            self.assertIsNone(actor.handle);self.assertIsNone(actor.thread);self.assertIsNone(actor.job)

    def test_real_windows_benign_actor_natural_exit(self):self.exercise(False)

    def test_real_windows_benign_actor_timeout_kills_only_owned_job(self):self.exercise(True)


if __name__=='__main__':unittest.main()
