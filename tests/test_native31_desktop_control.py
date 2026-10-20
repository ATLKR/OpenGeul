"""Local contract tests; fake APIs are NOT authentic Windows desktop proof."""
import copy
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'e2e/native31_desktop_control.py'
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('native31', SCRIPT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
else:
    m = None



class FakeDpiAPI:
    def __init__(self, fail_restore=False):
        self.default=1;self.context=None;self.fail_restore=fail_restore;self.third_party_during_override=False
    def GetThreadDpiAwarenessContext(self):return self.default if self.context is None else self.context
    def SetThreadDpiAwarenessContext(self,value):
        value=getattr(value,'value',value)
        if value>=2**63:value-=2**64
        previous=100+self.default if self.context is None else self.context
        if value==-4:self.context=-4;return previous
        if self.fail_restore or value!=100+self.default:return 0
        self.context=None;return previous
    def AreDpiAwarenessContextsEqual(self,left,right):
        def effective(value):
            value=getattr(value,'value',value)
            if value>=2**63:value-=2**64
            return value-100 if value>=100 else value
        return effective(left)==effective(right)
    def GetForegroundWindow(self):return 12
    def initialize_third_party(self):
        self.third_party_during_override=self.third_party_during_override or self.context is not None
        self.default=2

class ControlContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(m, 'Dedicated read-only control is not implemented')
        self.env = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
            RUNNER_ARCH='ARM64', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_EVENT_NAME='push',
            GITHUB_JOB='observe', GITHUB_REF=m.BRANCH, GITHUB_WORKFLOW_REF=m.WORKFLOW,
            GITHUB_SHA='a'*40, GITHUB_WORKFLOW_SHA='a'*40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1',
            GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341')
        self.event = dict(repository=dict(full_name='ATLKR/OpenGeul', id=123, private=False),
            sender=dict(login='ATLKR', id=65988341, type='User'), ref=m.BRANCH, deleted=False, after='a'*40)
        self.checkout = dict(head='a'*40, tree='b'*40, dirty=False)
        self.native = dict(processId=45, processMachine=0, nativeMachine=0xAA64, sessionId=1)

    def validate(self):
        return m.validate_context(self.env, self.event, self.checkout, self.native, 'nt')

    def test_exact_context(self):
        self.assertEqual(self.validate()['sourceCommit'], 'a'*40)

    def test_reject_context_drift(self):
        for key, bad in dict(GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_JOB='windows-suite',
                GITHUB_REF='refs/heads/main', GITHUB_WORKFLOW_REF='wrong', GITHUB_SHA='c'*40,
                GITHUB_WORKFLOW_SHA='c'*40, GITHUB_RUN_ATTEMPT='2', GITHUB_RUN_ID='0',
                RUNNER_OS='Linux', RUNNER_ARCH='X64', GITHUB_ACTOR='other',
                GITHUB_ACTOR_ID='1', RUNNER_ENVIRONMENT='self-hosted').items():
            with self.subTest(key=key):
                old = self.env[key]; self.env[key] = bad
                with self.assertRaises(ValueError): self.validate()
                self.env[key] = old
        for key, bad in [('ref','bad'),('deleted',True),('after','b'*40)]:
            old=self.event[key]; self.event[key]=bad
            with self.assertRaises(ValueError): self.validate()
            self.event[key]=old
        self.event['repository']['private']=True
        with self.assertRaises(ValueError): self.validate()

    def test_checkout_native_session_boundaries(self):
        for mapping, key, value in [(self.checkout,'dirty',True),(self.checkout,'head','d'*40),
                (self.native,'processMachine',0x8664),(self.native,'nativeMachine',0x8664),
                (self.native,'sessionId',None)]:
            old=mapping[key]; mapping[key]=value
            with self.assertRaises(ValueError): self.validate()
            mapping[key]=old
        with self.assertRaises(ValueError): m.validate_context(self.env,self.event,self.checkout,self.native,'posix')
        with self.assertRaises(ValueError): m.same_host({'sessionId':1},{'sessionId':2})

    def test_fresh_output_and_incremental_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'capture'; out=m.Evidence.create(path,Path(temp))
            out.write('00-start',{'a':1})
            with self.assertRaises(FileExistsError): out.write('00-start',{'a':2})
            with self.assertRaises(ValueError): out.write('bad',{'a':'x'*(256*1024)})
            self.assertEqual(json.loads((path/'00-start.json').read_text()),{'a':1})
            with self.assertRaises(ValueError): m.Evidence.create(path,Path(temp))
            with self.assertRaises(ValueError): m.Evidence.create(Path(temp)/'x'/'..'/'alias',Path(temp))
            with self.assertRaises(ValueError): m.Evidence.create(Path(temp).parent/'outside',Path(temp))
            link=Path(temp)/'alias'; link.symlink_to(path,target_is_directory=True)
            with self.assertRaises(ValueError): m.Evidence.create(link/'other',Path(temp))

    def test_taskbar_point_uses_original_formula(self):
        self.assertEqual(m.parking_point([0,720,1024,768]),[512,767])
        self.assertEqual(m.parking_point([0,0,48,768]),[47,384])
        with self.assertRaises(ValueError): m.parking_point([0,0,0,4])

    def test_complete_absence_and_incomplete_attempt(self):
        observed=self.privacy_fixture()
        observed['foreground'].update(title='Program Manager',className='Progman')
        observed['uia'][0]['nodes']=[dict(name='Desktop',controlType=50033,automationId='',className='',processId=200,enabled=True,offscreen=False)]
        result=m.classify(observed,1,'C:\\Windows',complete=True,stable=True)
        self.assertEqual(result['status'],'privacy-absent-observed')
        self.assertEqual(result['actions'],[])
        self.assertFalse(result['readiness']); self.assertFalse(result['hostReadyQualified'])
        for complete,stable in [(False,True),(True,False)]:
            with self.assertRaises(ValueError): m.classify(observed,1,'C:\\Windows',complete=complete,stable=stable)
        observed['foreground'].update(title='Microsoft account',className='Windows.UI.Core.CoreWindow',processId=99)
        with self.assertRaises(ValueError): m.classify(observed,1,'C:\\Windows',complete=True,stable=True)

    def test_budget_is_never_renewed(self):
        clock=[10.0]; budget=m.Budget(120,clock=lambda:clock[0])
        self.assertEqual(budget.deadline,130)
        clock[0]=129; self.assertEqual(budget.remaining(),1)
        clock[0]=131
        with self.assertRaises(TimeoutError): budget.remaining()
        self.assertEqual(budget.deadline,130)

    def test_owned_lifecycle_normal_timeout_and_launch_failure(self):
        class Owner:
            def __init__(self, mode): self.mode=mode; self.calls=[]; self.created=False
            def create_suspended(self):
                self.calls.append('create'); self.created=True
                if self.mode=='launch': raise OSError('launch failed')
            def assign(self): self.calls.append('assign')
            def identity(self): self.calls.append('identity'); return {'pid':3}
            def resume(self): self.calls.append('resume')
            def wait(self, seconds): self.calls.append('wait'); return self.mode!='timeout'
            def exit_code(self): return 0
            def descendants_empty(self): return True
            def terminate_owned(self): self.calls.append('terminate')
            def close(self): self.calls.append('close')
        for mode in ['normal','timeout','launch']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                out=m.Evidence.create(Path(temp)/'capture',Path(temp)); owner=Owner(mode)
                result=m.run_owned(owner,m.Budget(120),out)
                self.assertEqual(owner.calls[-1],'close')
                self.assertEqual(result['forced'],mode!='normal')
                self.assertEqual(result['timedOut'],mode=='timeout')
                self.assertFalse(result['readiness'])
                if mode=='normal': self.assertEqual(owner.calls,['create','assign','identity','resume','wait','close'])
                else: self.assertIn('terminate',owner.calls)
                self.assertTrue((out.path/'20-observer-launch.json').exists())


    def privacy_fixture(self):
        nodes = []
        for name, kind, aid in [('Choose privacy settings for your device',50033,''),
                ('Windows Setup',50006,''),(m.legacy.PRIVACY_FOOTER,50033,''),
                ('Next, tab through all privacy settings to continue',50000,'OobeSettingsAcceptButton')]:
            nodes.append(dict(name=name,controlType=kind,automationId=aid,className='',processId=200,enabled=True,offscreen=False))
        return {'foreground': dict(hwnd=12,processId=200,threadId=201,title='Microsoft account',
                    className='Windows.UI.Core.CoreWindow',visible=True,enabled=True,rectangle=[0,0,100,100]),
                'processes':[dict(processId=200,imagePath='C:\\Windows\\System32\\WWAHost.exe',imageBytes=1000,
                    imageSha256='b'*64,createdFileTime=133999999999999999,sessionId=1,processMachine=0,nativeMachine=0xAA64,
                    signature=dict(status='Valid',subject='CN=Microsoft Windows, O=Microsoft Corporation',issuer='test',
                                   thumbprint='c'*40,publisherMicrosoft=True))],
                'uia':[dict(hwnd=12,nodes=nodes,truncated=False)]}

    def test_exact_positive_classifier_is_diagnostic_only(self):
        observed=self.privacy_fixture()
        result=m.classify(observed,1,'C:\\Windows',complete=True,stable=True)
        self.assertEqual(result['status'],'privacy-match')
        self.assertEqual(result['candidate'],m.legacy.privacy_candidate(observed,1,'C:\\Windows'))
        self.assertEqual(result['actions'],[])
        for key in ('readiness','hostReadyQualified','productQualified','productExecuted'):
            self.assertIs(result[key],False)
        self.assertEqual(result['candidate']['process']['createdFileTime'],133999999999999999)

    def test_positive_denies_truncation_unavailable_foreign_owner_and_session(self):
        base=self.privacy_fixture()
        cases=[]
        for key,value in [('truncated',True),('error',{'type':'COMError','hresult':'0x1'})]:
            sample=copy.deepcopy(base); sample['uia'][0][key]=value; cases.append(sample)
        for key,value in [('createdFileTime',0),('sessionId',2),('processMachine',0x8664),('imageSha256','')]:
            sample=copy.deepcopy(base); sample['processes'][0][key]=value; cases.append(sample)
        sample=copy.deepcopy(base); sample['uia'][0]['nodes'][0]['processId']=201; cases.append(sample)
        sample=copy.deepcopy(base); sample['processes'][0]['signature']['status']='Unavailable'; cases.append(sample)
        for sample in cases:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                m.classify(sample,1,'C:\\Windows',complete=True,stable=True)

    def test_incomplete_nonprivacy_cannot_claim_absence(self):
        sample=self.privacy_fixture(); sample['foreground'].update(title='Program Manager',className='Progman')
        sample['uia'][0]['nodes']=[dict(name='Desktop',controlType=50033,automationId='',className='',processId=200,enabled=True,offscreen=False)]
        for key,value in [('truncated',True),('error',{'type':'COMError','hresult':'0x1'})]:
            bad=copy.deepcopy(sample); bad['uia'][0][key]=value
            with self.assertRaises(ValueError): m.classify(bad,1,'C:\\Windows',complete=True,stable=True)

    def test_census_propagates_native_failure_and_preserves_first_target(self):
        probe=object.__new__(m.Probe)
        foreground=0x123456789
        probe.user=SimpleNamespace(GetForegroundWindow=lambda:foreground,
            EnumWindows=lambda callback,_: all(callback(hwnd,0) for hwnd in range(1,70)))
        probe.callback=lambda callback: callback
        probe.window=lambda hwnd: {'hwnd':hwnd}
        census,errors,ok=probe.census()
        self.assertEqual(census['windows'][0]['hwnd'],foreground)
        self.assertEqual(len(census['windows']),64); self.assertTrue(census['truncated']); self.assertFalse(ok)
        probe.window=lambda hwnd: {'hwnd':hwnd} if hwnd==foreground else (_ for _ in ()).throw(OSError('denied'))
        census,errors,ok=probe.census()
        self.assertFalse(ok); self.assertEqual(errors[0]['type'],'OSError')
        self.assertEqual(census['windows'],[{'hwnd':foreground}])

    def test_read_only_taskbar_records_foreign_root_without_input(self):
        class Function:
            def __init__(self, action): self.action=action
            def __call__(self,*args): return self.action(*args)
        probe=object.__new__(m.Probe); points=[]
        def appbar(message, data):
            self.assertEqual(message,5)
            data._obj.rc.left,data._obj.rc.top,data._obj.rc.right,data._obj.rc.bottom=0,720,1024,768
            return 1
        probe.shell=SimpleNamespace(SHAppBarMessage=Function(appbar))
        probe.user=SimpleNamespace(FindWindowW=lambda *_:11,
            WindowFromPhysicalPoint=lambda point: points.append([point.x,point.y]) or 22,
            GetAncestor=lambda hwnd,flag:33)
        probe.target=lambda hwnd: dict(hwnd=hwnd,className='Shell_TrayWnd',visible=True)
        result=probe.taskbar()
        self.assertEqual(points,[[512,767]])
        self.assertEqual(result['actualPointHwnd'],22); self.assertEqual(result['actualRootHwnd'],33)
        self.assertFalse(result['pointerMoved']); self.assertFalse(result['rootEqualsTaskbar'])

    def test_image_reads_are_bounded_and_exact(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sample.exe'; data=bytearray(512); data[:2]=b'MZ'
            data[60:64]=(128).to_bytes(4,'little'); data[128:134]=b'PE\0\0'+(0xAA64).to_bytes(2,'little')
            path.write_bytes(data)
            receipt=m.image_receipt(path,m.Budget())
            self.assertEqual(receipt['peMachine'],0xAA64); self.assertEqual(receipt['imageBytes'],512)
            with patch.object(m,'MAX_IMAGE',511), self.assertRaises(ValueError): m.image_receipt(path,m.Budget())
            path.write_bytes(b'bad')
            with self.assertRaises(ValueError): m.image_receipt(path,m.Budget())

    def test_evidence_file_count_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            out=m.Evidence.create(Path(temp)/'capture',Path(temp))
            with patch.object(m,'MAX_FILES',2):
                out.write('one',{}); out.write('two',{})
                with self.assertRaises(ValueError): out.write('three',{})
            self.assertEqual(len(list(out.path.iterdir())),2)

    def test_child_environment_excludes_credentials_and_python_injection(self):
        env=m.child_environment({'GITHUB_TOKEN':'secret','PYTHONPATH':'attacker','PYTHONSTARTUP':'attacker',
            'GITHUB_SHA':'a'*40,'PATH':'safe','SYSTEMROOT':'C:\\Windows'})
        self.assertEqual(env,{'GITHUB_SHA':'a'*40,'PATH':'safe','SYSTEMROOT':'C:\\Windows',
                              'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'})

    def test_fixed_workflow_contract(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/office-native31-desktop-control.yml').read_text())
        self.assertEqual(workflow['on'],{'push':{'branches':[m.BRANCH.removeprefix('refs/heads/')]}})
        job=workflow['jobs']['observe']
        self.assertEqual(job['runs-on'],'windows-11-arm'); self.assertEqual(job['timeout-minutes'],10)
        self.assertEqual(job['if'],'github.event.repository.private == false')
        upload=job['steps'][-1]
        self.assertEqual(upload['if'],'always()'); self.assertEqual(upload['with']['if-no-files-found'],'error')
        self.assertEqual(upload['with']['retention-days'],1)
        self.assertEqual(upload['with']['name'],'opengeul-native31-desktop-control-${{ github.run_id }}-${{ github.run_attempt }}')
        from ci.policy import audit, ACTIONS
        audit(workflow)
        for step in job['steps']:
            if 'uses' in step:
                action,sha=step['uses'].split('@'); self.assertEqual(ACTIONS[action],sha)


    def test_capture_preserves_raw_evidence_before_uia_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output=m.Evidence.create(folder/'capture',folder)
            image=folder/'target.exe'; data=bytearray(512); data[:2]=b'MZ'; data[60:64]=(128).to_bytes(4,'little')
            data[128:134]=b'PE\0\0'+(0xAA64).to_bytes(2,'little'); image.write_bytes(data)
            event=folder/'event.json'; event.write_text(json.dumps(self.event))
            host=dict(processId=45,processMachine=0,nativeMachine=0xAA64,sessionId=1,windowsDirectory='C:\\Windows',
                windowsVersion=[10,0,1,2,''],imageOS='test',imageVersion='test',desktop='Default',windowStation='WinSta0',
                process={'createdFileTime':100})
            output.write('21-observer-bound',{'processId':45,'createdFileTime':100})
            context={**self.checkout,'files':{'test':'a'*64}}
            controller={'host':host,'sourceFiles':context['files'],'eventSha256':m.legacy.bounded_object(event)[1]}
            window=dict(hwnd=12,processId=200,threadId=201,title='Program Manager',className='Progman',
                        visible=True,enabled=True,rectangle=[0,0,100,100])
            taskbar=dict(actualPointHwnd=12,actualRootHwnd=12,taskbarHwnd=12)
            closed=[]
            probe=SimpleNamespace(identity=lambda:host,
                user=SimpleNamespace(SetThreadDpiAwarenessContext=lambda context:1,
                    GetThreadDpiAwarenessContext=lambda:1,AreDpiAwarenessContextsEqual=lambda *args:True),
                kernel=SimpleNamespace(OpenProcess=lambda *args:77,CloseHandle=lambda handle:closed.append(handle) or True),
                census=lambda:({'foregroundHwnd':12,'windows':[window],'truncated':False},[],True),
                taskbar=lambda:taskbar,target=lambda hwnd:window,
                process_identity=lambda handle,pid:dict(processId=pid,createdFileTime=133999999999999999,
                    sessionId=1,processMachine=0,nativeMachine=0xAA64,imagePath=str(image),exitCode=259),
                strict_uia=lambda hwnd: (_ for _ in ()).throw(TimeoutError('simulated COM hang boundary')))
            real_validate=m.validate_context
            screen=SimpleNamespace(width=100,height=100,save=lambda stream,format:stream.write(b'fake-bounded-screen'))
            with patch.dict(os.environ,{**self.env,'GITHUB_EVENT_PATH':str(event)}), \
                 patch.dict('sys.modules',{'PIL':SimpleNamespace(ImageGrab=SimpleNamespace(grab=lambda all_screens:screen))}), \
                 patch.object(m,'source_receipt',return_value=context), \
                 patch.object(m,'signatures',return_value=[{'status':'Valid'}]), \
                 patch.object(m,'validate_context',side_effect=lambda env,event,checkout,native,platform: real_validate(env,event,checkout,native,'nt')):
                with self.assertRaises(TimeoutError): m.capture(probe,output,m.Budget(),controller)
            for name in ('31-observer-host','33-window-census','34-physical-hit','35-target-windows',
                         '41-process-0-raw','42-process-0-image','44-processes-complete','50-uia-0-before','85-observer-cleanup'):
                self.assertTrue((output.path/(name+'.json')).exists(),name)
            self.assertFalse((output.path/'80-classification.json').exists())
            self.assertEqual(closed,[77])
            raw=json.loads((output.path/'41-process-0-raw.json').read_text())
            self.assertEqual(raw['createdFileTime'],133999999999999999)


    def complete_capture_fixture(self, *, privacy, target_changes=None, uia_error=False, dpi_api=None, close_failure=False, hit_drifts=False):
        """Run real observer/capture/classifier using local fake native boundaries."""
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); output=m.Evidence.create(folder/'capture',folder)
            event=folder/'event.json'; event.write_text(json.dumps(self.event))
            sample=self.privacy_fixture()
            if not privacy:
                sample['foreground'].update(title='Program Manager',className='Progman')
                sample['uia'][0]['nodes']=[dict(name='Desktop',controlType=50033,automationId='',
                    className='',processId=200,enabled=True,offscreen=False)]
            census_window=copy.deepcopy(sample['foreground'])
            target={**copy.deepcopy(census_window),'style':0x10000000,'exStyle':0,'rootHwnd':12,'ownerHwnd':0,'ownerAbsent':True}
            target.update(target_changes or {})
            host=dict(processId=45,processMachine=0,nativeMachine=0xAA64,sessionId=1,windowsDirectory=r'C:\Windows',
                windowsVersion=[10,0,1,2,''],imageOS='test',imageVersion='test',desktop='Default',windowStation='WinSta0',
                process={'createdFileTime':100})
            context={**self.checkout,'files':{'test':'a'*64}}
            output.write('10-controller',{'host':host,'sourceFiles':context['files'],
                                         'eventSha256':m.legacy.bounded_object(event)[1]})
            output.write('21-observer-bound',{'processId':45,'createdFileTime':100})
            process=copy.deepcopy(sample['processes'][0]); signature=process.pop('signature')
            image={key:process.pop(key) for key in ('imageBytes','imageSha256')}; image['peMachine']=0xAA64
            process['exitCode']=259
            taskbar=dict(actualPointHwnd=12,actualRootHwnd=12,taskbarHwnd=12)
            closed=[]; hit_calls=[]
            def hit_query():
                hit_calls.append(1); value=copy.deepcopy(taskbar)
                if hit_drifts and len(hit_calls)==2: value['actualRootHwnd']=99
                return value
            def uia_query(hwnd):
                if dpi_api: dpi_api.initialize_third_party()
                tree=copy.deepcopy(sample['uia'][0])
                if uia_error:
                    tree['error']={'type':'ValueError','message':'original UIA name failure','hresult':None,
                        'stage':'property','nodeIndex':1,'property':'CurrentName','field':'name',
                        'raw':{'pythonType':'NoneType','value':None,'valueAvailable':True}}
                return tree
            probe=SimpleNamespace(identity=lambda:copy.deepcopy(host),
                user=SimpleNamespace(SetThreadDpiAwarenessContext=lambda context:1,
                    GetThreadDpiAwarenessContext=lambda:1,AreDpiAwarenessContextsEqual=lambda *args:True,
                    GetForegroundWindow=lambda:12),
                kernel=SimpleNamespace(OpenProcess=lambda *args:77,CloseHandle=lambda handle:closed.append(handle) or not close_failure),
                census=lambda:({'foregroundHwnd':12,'windows':[copy.deepcopy(census_window)],'truncated':False},[],True),
                taskbar=hit_query,target=lambda hwnd:copy.deepcopy(target),
                process_identity=lambda handle,pid:copy.deepcopy(process),
                strict_uia=uia_query)
            if dpi_api: probe.user=dpi_api
            screen=SimpleNamespace(width=100,height=100,
                save=lambda stream,format:stream.write(b'\x89PNG\r\n\x1a\nlocal-fake-screen'))
            pil=SimpleNamespace(ImageGrab=SimpleNamespace(grab=lambda all_screens:screen))
            real_validate=m.validate_context
            with patch.dict(os.environ,{**self.env,'GITHUB_EVENT_PATH':str(event)}), \
                 patch.dict('sys.modules',{'PIL':pil}), \
                 patch.object(m,'Probe',return_value=probe), \
                 patch.object(m,'source_receipt',side_effect=lambda budget:copy.deepcopy(context)), \
                 patch.object(m,'image_receipt',return_value=image), \
                 patch.object(m,'signatures',return_value=[signature]), \
                 patch.object(m,'validate_context',side_effect=lambda env,event,checkout,native,platform: real_validate(env,event,checkout,native,'nt')):
                exit_code=m.observer(SimpleNamespace(deadline=m.time.monotonic()+120,output=output.path))
            records={path.stem:json.loads(path.read_text()) for path in output.path.glob('*.json')}
            records['_screenExists']=(output.path/'foreground-desktop.png').is_file()
            records['_hitCalls']=len(hit_calls)
            return exit_code,records,closed,census_window

    def test_capture_census_to_target_metadata_race_fails_with_raw_evidence(self):
        for change in ({'title':'Microsoft account'},{'className':'Windows.UI.Core.CoreWindow'},
                       {'visible':False},{'enabled':False},{'rectangle':[0,0,101,100]}):
            with self.subTest(change=change):
                exit_code,records,closed,census=self.complete_capture_fixture(privacy=False,target_changes=change)
                self.assertEqual(exit_code,1)
                self.assertNotIn('80-classification',records)
                self.assertIn('Census-to-target foreground metadata raced',records['89-observer-failure']['failure']['message'])
                self.assertFalse(records['89-observer-failure']['readiness'])
                self.assertEqual(records['89-observer-failure']['actions'],[])
                self.assertEqual(records['33-window-census']['windows'][0],census)
                target=records['35-target-windows']['targets'][0]
                for key in ('hwnd','processId','threadId'): self.assertEqual(target[key],census[key])
                for key,value in change.items(): self.assertEqual(target[key],value)
                self.assertIn('31-observer-host',records); self.assertIn('34-physical-hit',records)
                self.assertEqual(records['85-observer-cleanup']['errors'],[])

    def test_complete_capture_unchanged_positive_uses_legacy_foreground_schema(self):
        exit_code,records,closed,census=self.complete_capture_fixture(privacy=True)
        self.assertEqual(exit_code,0)
        self.assertEqual(records['80-classification']['status'],'privacy-match')
        self.assertEqual(records['70-raw-observation']['foreground'],census)
        self.assertEqual(records['80-classification']['candidate']['window'],census)
        self.assertEqual(records['35-target-windows']['targets'],records['71-identity-recheck']['targets'])
        self.assertIn('style',records['35-target-windows']['targets'][0])
        self.assertNotIn('style',records['70-raw-observation']['foreground'])
        self.assertIn('81-source-recheck',records); self.assertEqual(closed,[77])
        self.assertEqual(records['80-classification']['actions'],[])
        self.assertFalse(records['80-classification']['readiness'])

    def test_complete_capture_unchanged_absence_preserves_raw_and_rechecked_identity(self):
        exit_code,records,closed,census=self.complete_capture_fixture(privacy=False)
        self.assertEqual(exit_code,0)
        self.assertEqual(records['80-classification']['status'],'privacy-absent-observed')
        self.assertEqual(records['70-raw-observation']['foreground'],census)
        self.assertEqual(records['35-target-windows']['targets'],records['71-identity-recheck']['targets'])
        self.assertIn('61-screen-after',records); self.assertIn('81-source-recheck',records)
        self.assertEqual(closed,[77]); self.assertEqual(records['80-classification']['actions'],[])
        self.assertFalse(records['80-classification']['hostReadyQualified'])

    def test_owned_failure_boundaries_always_close_and_never_succeed_forced(self):
        for stage in ('assign','identity','resume','exit','account','close'):
            calls=[]
            class Owner:
                created=False
                def create_suspended(self): self.created=True; calls.append('create')
                def invoke(self,name,value=None):
                    calls.append(name)
                    if stage==name: raise OSError(name)
                    return value
                def assign(self): self.invoke('assign')
                def identity(self): return self.invoke('identity',{'pid':3})
                def resume(self): self.invoke('resume')
                def wait(self,seconds): return True
                def exit_code(self): return self.invoke('exit',0)
                def descendants_empty(self): return self.invoke('account',True)
                def terminate_owned(self): calls.append('terminate')
                def close(self): self.invoke('close')
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                output=m.Evidence.create(Path(temp)/'capture',Path(temp))
                result=m.run_owned(Owner(),m.Budget(),output)
                self.assertFalse(result['success']); self.assertFalse(result['readiness'])
                self.assertIn('close',calls)
                if stage!='close': self.assertIn('terminate',calls); self.assertTrue(result['forced'])
                self.assertTrue((output.path/'90-owned-lifecycle.json').exists())


    def test_native_owner_creates_suspended_and_assigns_kill_job_before_resume(self):
        calls=[]
        class Function:
            def __init__(self,name,action): self.name,self.action=name,action
            def __call__(self,*args): calls.append(self.name); return self.action(*args)
        kernel=SimpleNamespace()
        actions={
            'CreateJobObjectW':lambda *args:99,
            'SetInformationJobObject':lambda job,kind,data,size: self.assertEqual(data._obj.basic.flags,0x2000) or 1,
            'QueryInformationJobObject':lambda job,kind,data,size,returned: setattr(data._obj,'active',0) or 1,
            'AssignProcessToJobObject':lambda job,process: self.assertEqual((job,process),(99,77)) or 1,
            'TerminateJobObject':lambda *args:1,'TerminateProcess':lambda *args:1,
            'ResumeThread':lambda thread: self.assertEqual(thread,78) or 1,
            'WaitForSingleObject':lambda process,ms:0,
            'GetExitCodeProcess':lambda process,code: setattr(code._obj,'value',0) or 1,
            'CloseHandle':lambda handle:1}
        for name,action in actions.items(): setattr(kernel,name,Function(name,action))
        identity=dict(processId=45,createdFileTime=133999999999999999,processMachine=0,nativeMachine=0xAA64,
                      sessionId=1,imagePath=m.sys.executable,exitCode=259)
        probe=SimpleNamespace(kernel=kernel,process_identity=lambda handle,pid:identity)
        executable=dict(imageBytes=1,imageSha256='a'*64,peMachine=0xAA64)
        def create(exe,command,process_security,thread_security,inherit,creation,env,cwd,startup):
            calls.append('CreateProcess')
            self.assertFalse(inherit); self.assertTrue(creation & 4); self.assertFalse(creation & 0x01000000)
            self.assertEqual(env,{'fixed':'value'})
            return 77,78,45,46
        with patch.dict('sys.modules',{'_winapi':SimpleNamespace(CreateProcess=create)}), \
             patch.object(m.subprocess,'STARTUPINFO',create=True,return_value=object()), \
             patch.object(m,'image_receipt',return_value=executable):
            owner=m.OwnedObserver(probe,{'fixed':'value'},[m.sys.executable,'fixed.py'],m.Budget(),
                                  {'sessionId':1,'executable':executable,'sourceFiles':{}})
            owner.create_suspended(); owner.assign(); receipt=owner.identity(); owner.resume()
            self.assertTrue(owner.wait(3)); self.assertEqual(owner.exit_code(),0); self.assertTrue(owner.descendants_empty())
            owner.close()
        self.assertLess(calls.index('AssignProcessToJobObject'),calls.index('ResumeThread'))
        self.assertEqual(calls.count('CloseHandle'),3)
        self.assertNotIn('TerminateProcess',calls); self.assertNotIn('TerminateJobObject',calls)
        self.assertTrue(receipt['assignedBeforeResume']); self.assertEqual(receipt['processHandle'],77)


    def test_observer_timeout_receipt_reports_forced_owned_subprocess_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            output=m.Evidence.create(Path(temp)/'capture',Path(temp)); output.write('10-controller',{})
            args=SimpleNamespace(deadline=m.time.monotonic()+120,output=output.path)
            with patch.object(m,'Probe',return_value=object()), \
                 patch.object(m,'capture',side_effect=m.subprocess.TimeoutExpired(['fixed-git-diagnostic'],1)):
                self.assertEqual(m.observer(args),1)
            failure=json.loads((output.path/'89-observer-failure.json').read_text())
            self.assertTrue(failure['forced']); self.assertTrue(failure['timedOut'])
            self.assertFalse(failure['readiness']); self.assertEqual(failure['actions'],[])


    def collect_fake_uia(self, nodes):
        properties={'name':'CurrentName','controlType':'CurrentControlType','automationId':'CurrentAutomationId',
                    'className':'CurrentClassName','processId':'CurrentProcessId','enabled':'CurrentIsEnabled','offscreen':'CurrentIsOffscreen'}
        elements=[SimpleNamespace(**{properties[key]:value for key,value in node.items()}) for node in nodes]
        def sibling(element):
            index=next(i for i,item in enumerate(elements) if item is element)
            return elements[index+1] if index+1<len(elements) else None
        walker=SimpleNamespace(GetFirstChildElement=lambda element:elements[1] if element is elements[0] and len(elements)>1 else None,
                               GetNextSiblingElement=sibling)
        api=SimpleNamespace(iuia=SimpleNamespace(ElementFromHandle=lambda hwnd:elements[0],ControlViewWalker=walker))
        with patch.dict('sys.modules',{'pywinauto.uia_defines':SimpleNamespace(IUIA=lambda:api)}):
            return m.Probe.strict_uia(object.__new__(m.Probe),12)

    def test_diagnostic_uia_full_long_multiline_name_preserves_exact_classifier(self):
        sample=self.privacy_fixture()
        incidental=copy.deepcopy(sample['uia'][0]['nodes'][0])
        incidental['name']='설명'*1000+'\r\n\t'+'x'*45
        self.assertEqual(len(incidental['name']),2048)
        sample['uia'][0]=self.collect_fake_uia(sample['uia'][0]['nodes']+[incidental])
        self.assertNotIn('error',sample['uia'][0])
        self.assertEqual(sample['uia'][0]['nodes'][-1]['name'],incidental['name'])
        self.assertEqual(m.classify(sample,1,r'C:\Windows',complete=True,stable=True)['status'],'privacy-match')
        sample['uia'][0]['nodes'][0]['name']+='\n'
        with self.assertRaises(ValueError):m.classify(sample,1,r'C:\Windows',complete=True,stable=True)

    def test_diagnostic_uia_invalid_property_retains_raw_offender(self):
        for field,value in [('name','x'*2049),('name',None),('name',17),('name','bad\x00value'),
                            ('name','bad\x7fvalue'),('automationId','a'*257),('className','bad\nclass')]:
            with self.subTest(field=field,value_type=type(value).__name__):
                node=copy.deepcopy(self.privacy_fixture()['uia'][0]['nodes'][0]);node[field]=value
                tree=self.collect_fake_uia([node])
                self.assertIn('error',tree)
                error=tree['error'];self.assertIn('field',error)
                self.assertEqual(error['field'],field);self.assertEqual(error['nodeIndex'],0)
                self.assertTrue(error['message']);self.assertIn('hresult',error)
                self.assertEqual(error['raw']['pythonType'],type(value).__name__)
                self.assertEqual(error['raw']['value'],value[:2048] if isinstance(value,str) else value)
                if isinstance(value,str):self.assertEqual(error['raw']['length'],len(value))
                self.assertLessEqual(len(json.dumps(tree,ensure_ascii=False).encode()),256*1024)

    def test_diagnostic_uia_node_and_json_truncation_cannot_classify(self):
        node=copy.deepcopy(self.privacy_fixture()['uia'][0]['nodes'][0])
        tree=self.collect_fake_uia([copy.deepcopy(node) for _ in range(65)])
        self.assertTrue(tree['truncated']);self.assertLessEqual(len(tree['nodes']),64)
        node['name']='😀'*2048
        tree=self.collect_fake_uia([copy.deepcopy(node) for _ in range(64)])
        self.assertIn('error',tree)
        self.assertLessEqual(len(json.dumps(tree,ensure_ascii=False,indent=2).encode()),256*1024)


    def test_uia_worst_case_offender_and_partial_node_stay_inside_json_cap(self):
        node=copy.deepcopy(self.privacy_fixture()['uia'][0]['nodes'][0])
        node.update(name='😀'*2048,automationId='😀'*256,className='😀'*256)
        offender=copy.deepcopy(node);offender['className']='😀'*2049
        tree=self.collect_fake_uia([copy.deepcopy(node) for _ in range(7)]+[offender])
        self.assertIn('error',tree)
        self.assertLessEqual(len(m.encoded_json(tree)),m.MAX_JSON)
        self.assertIn(tree['error']['stage'],('property','node-json-bound'))
        self.assertIn('partialNode',tree)

    def test_uia_getter_exception_retains_hresult_position_and_partial_node(self):
        class Element:
            CurrentName='Name already read'
            CurrentControlType=50033
            @property
            def CurrentAutomationId(self):
                exc=OSError('COM property denied');exc.hresult=-2147467259;raise exc
        api=SimpleNamespace(iuia=SimpleNamespace(ElementFromHandle=lambda hwnd:Element(),ControlViewWalker=object()))
        with patch.dict('sys.modules',{'pywinauto.uia_defines':SimpleNamespace(IUIA=lambda:api)}):
            tree=m.Probe.strict_uia(object.__new__(m.Probe),12)
        self.assertEqual(tree['error']['property'],'CurrentAutomationId')
        self.assertEqual(tree['error']['nodeIndex'],0)
        self.assertEqual(tree['error']['type'],'OSError')
        self.assertEqual(tree['error']['message'],'COM property denied')
        self.assertEqual(tree['error']['hresult'],'0x80004005')
        self.assertFalse(tree['error']['raw']['valueAvailable'])
        self.assertEqual(tree['partialNode'],{'name':'Name already read','controlType':50033})

    def test_capture_png_and_primary_uia_failure_survive_cleanup_failure(self):
        exit_code,records,closed,_=self.complete_capture_fixture(privacy=True,uia_error=True,close_failure=True)
        self.assertEqual(exit_code,1);self.assertTrue(records['_screenExists'])
        self.assertIn('61-screen-after',records)
        failure=records['89-observer-failure']['failure']
        self.assertIn('original UIA name failure',failure['message'])
        self.assertEqual(failure['details']['uiaFailure']['property'],'CurrentName')
        self.assertTrue(failure['cleanupFailures'])
        self.assertEqual(records['85-observer-cleanup']['queryHandlesClosed'],0)
        self.assertEqual(records['85-observer-cleanup']['primaryFailure']['message'],failure['message'])
        self.assertNotIn('80-classification',records)
        self.assertEqual(records['89-observer-failure']['actions'],[])

    def test_capture_restores_each_physical_phase_before_third_party_dpi_init(self):
        dpi=FakeDpiAPI()
        exit_code,records,closed,_=self.complete_capture_fixture(privacy=True,dpi_api=dpi)
        self.assertEqual(exit_code,0)
        self.assertFalse(dpi.third_party_during_override)
        transactions=[records[name] for name in sorted(records) if name.endswith('-dpi')]
        self.assertEqual(len(transactions),3)
        self.assertTrue(all(record['restored'] for record in transactions))
        self.assertEqual([record['initialContext'] for record in transactions],[1,1,2])


    def test_capture_compares_retained_hit_without_reread_to_green(self):
        code,records,closed,_=self.complete_capture_fixture(privacy=True,hit_drifts=True)
        self.assertEqual(code,1)
        self.assertEqual(records['71-identity-recheck']['physicalHit']['actualRootHwnd'],99)
        self.assertEqual(records['_hitCalls'],2)
        self.assertNotIn('80-classification',records)


    def test_capture_restore_failure_alone_remains_nonzero(self):
        code,records,closed,_=self.complete_capture_fixture(privacy=True,dpi_api=FakeDpiAPI(fail_restore=True))
        self.assertEqual(code,1)
        self.assertFalse(records['36-native-dpi']['restored'])
        self.assertTrue(records['89-observer-failure']['failure']['cleanupFailures'])
        self.assertNotIn('80-classification',records)
        self.assertEqual(records['89-observer-failure']['actions'],[])

    def test_physical_transaction_preserves_primary_and_failed_restore(self):
        self.assertTrue(hasattr(m,'physical_queries'),'Scoped PMv2 transaction is missing')
        with tempfile.TemporaryDirectory() as temp:
            output=m.Evidence.create(Path(temp)/'capture',Path(temp));dpi=FakeDpiAPI(fail_restore=True)
            with self.assertRaisesRegex(ValueError,'primary query failure') as caught:
                with m.physical_queries(SimpleNamespace(user=dpi),output,'test-dpi'):
                    raise ValueError('primary query failure')
            record=json.loads((output.path/'test-dpi.json').read_text())
            self.assertFalse(record['restored']);self.assertIsNotNone(record['restoreFailure'])
            self.assertTrue(m.error_record(caught.exception)['cleanupFailures'])

    def test_no_mutating_product_or_desktop_calls(self):
        source=SCRIPT.read_text()
        for forbidden in ['.prepare(','.observe(','.park_pointer(','.close_verified(','.focus_probe(',
                'SetPhysicalCursorPos(', 'SendInput(', 'SendMessageTimeoutW(', 'OwnedOfficeProcess',
                'TerminateProcess(pid', 'taskkill', 'reg.exe']:
            self.assertNotIn(forbidden,source)

if __name__=='__main__': unittest.main()
