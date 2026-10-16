"""Portable raw ownership/frame replay and bounded-reader contracts; no live UNO."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/writer_model_reader.py'


def native_fixture(binding, suite_root):
    """Producer-shaped raw observations. Synthetic API values are not live proof."""
    root = str(suite_root).replace('\\', '/').rstrip('/')
    def process(pid, creation, image, handle):
        return dict(pid=pid, creationTime=creation, image=image, handleValue=handle,
                    waitResult=258, exitCode=259)
    windows = dict(exportedParentHwnd=binding['parentHwnd'], exportedChildHwnd=binding['childHwnd'])
    for name, hwnd, pid, parent in (
        ('suite',binding['suiteHwnd'],binding['shellPid'],0),
        ('parent',binding['parentHwnd'],binding['shellPid'],binding['suiteHwnd']),
        ('child',binding['childHwnd'],binding['officePid'],binding['parentHwnd'])):
        windows[name] = dict(hwnd=hwnd,pid=pid,parentHwnd=parent,rootHwnd=binding['suiteHwnd'],isWindow=True)
    snapshot = dict(shell=process(binding['shellPid'],binding['shellCreationTime'],root+'/OpenGeul.Office.exe',101),
        office=process(binding['officePid'],binding['officeCreationTime'],binding['expectedImage'],102),
        windows=windows,privatePipe=binding['privatePipe'],officeCommandLine=['soffice.bin','--invisible','--accept=pipe,name='+binding['privatePipe']+';urp;StarOffice.ServiceManager','-env:UserInstallation=file:///C:/private-profile'],profileUrl='file:///C:/private-profile')
    helper=copy.deepcopy(snapshot); helper['shell']['handleValue']=201;helper['office']['handleValue']=202
    retained={name:binding[name+'Identity'] for name in ('frame','controller','model')}
    uno=dict(frameCount=1,frames=[dict(index=0,containerHwnd=binding['childHwnd'])],matchedFrameIndex=0,
        retained=retained,equalities={k:True for k in ('frame','controller','model','controllerFrame','modelController')},
        documentUrl=binding['documentUrl'],modelService='com.sun.star.text.TextDocument')
    return dict(nativeSnapshots=dict(controllerBefore=copy.deepcopy(snapshot),controllerAfter=copy.deepcopy(snapshot),
        helperBefore=copy.deepcopy(helper),helperAfter=copy.deepcopy(helper)),
        unoSnapshots=dict(before=copy.deepcopy(uno),after=copy.deepcopy(uno)),
        readerProcess=dict(process(99,333,root+'/Office/program/python-core-3.13.15/bin/python.exe',301),inOwnedJob=True,isInJobApiSucceeded=True,jobHandleValue=401),
        helperLaunch=dict(firstFailure=None,steps=[dict(api='CreateJobObjectW',handleValue=401,lastError=0),
            dict(api='CreateProcessW',result=True,creationFlags=0x08000404,application=root+'/Office/program/python.exe',command='packaged-python reader.py --helper owned-output',inheritHandles=False,lastError=0,pid=98,threadId=198,processHandleValue=302,threadHandleValue=303),
            dict(api='AssignProcessToJobObject',result=True,lastError=0,jobHandleValue=401,processHandleValue=302),
            dict(api='ResumeThread',lastError=0,previousSuspendCount=1,threadHandleValue=303),dict(api='CloseHandle',result=True,lastError=0,handleValue=303)]))


def cleanup_fixture(binding,suite_root):
    raw=native_fixture(binding,suite_root)
    member=copy.deepcopy(raw['readerProcess']);member.update(waitResult=0,exitCode=0)
    return dict(kind='owned-writer-reader-cleanup',binding=copy.deepcopy(binding),cleanupSucceeded=True,
        startedAt=1.0,finishedAt=1.1,deadline=12.0,terminated=False,
        releaseAcknowledgement=dict(action='release',readerPid=99,proxiesReleased=True),
        readerMembers=[member,dict(copy.deepcopy(member),pid=98,handleValue=304)],finalJobPids=[],jobHandleValue=401,helperLaunch=raw['helperLaunch'],
        nativeBefore=raw['nativeSnapshots']['controllerBefore'],nativeAfter=raw['nativeSnapshots']['controllerAfter'],
        handleClosures=[dict(kind='member',handleValue=301,result=True),dict(kind='member',handleValue=304,result=True),dict(kind='process',handleValue=302,result=True),
            dict(kind='job',handleValue=401,result=True),dict(kind='shell',handleValue=101,result=True),
            dict(kind='office',handleValue=102,result=True)],errors=[])


def binding_fixture():
    return dict(shellPid=77,shellCreationTime=111,officePid=88,officeCreationTime=222,
        expectedImage='C:/Suite/Office/program/soffice.bin',suiteHwnd=11,parentHwnd=12,childHwnd=22,rootHwnd=11,
        privatePipe='OpenGeul_'+'a'*32,frameIdentity='pyuno object (XFrame)0x1234',
        controllerIdentity='pyuno object (XController)0x2345',modelIdentity='pyuno object (XModel)0x3456',
        documentUrl='file:///C:/owned.docx')


def observation_fixture(binding,suite_root='C:/Suite'):
    result=dict(kind='existing-owned-writer-body',bindingBefore=copy.deepcopy(binding),bindingAfter=copy.deepcopy(binding),
        retainedProcessHandle=True,handleSignaled=False,readOnlyObservation=True,sameFrameControllerModelVerified=True,
        readCallCleanupSucceeded=True,readerStillRetained=True,bodyText='baseline\n',
        operations=['resolve-existing-owned-frame','Text.getString','isModified','verify-retained-generation'])
    result.update(native_fixture(binding,suite_root))
    result['pythonIdentity']={'observed':{'processImage':result['readerProcess']['image']}}
    return result


class ReaderContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert SOURCE.is_file(),'RED: bounded owned Writer model reader is required'
        spec=importlib.util.spec_from_file_location('reader_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def setUp(self):
        self.binding=binding_fixture();self.value=observation_fixture(self.binding)

    def test_portable_windows_identity_and_real_raw_shapes(self):
        with patch.object(Path,'resolve',side_effect=AssertionError('pure replay performed IO')):
            self.api.require_owned_observation(self.value,self.binding,'C:/Suite')
            self.api.require_reader_cleanup(cleanup_fixture(self.binding,'C:/Suite'),self.binding,12.0)

    def test_scalar_flags_cannot_replace_raw_observations(self):
        self.value.pop('nativeSnapshots')
        with self.assertRaises(AssertionError):self.api.require_owned_observation(self.value,self.binding,'C:/Suite')

    def test_changed_retained_generation_and_handle_rejected(self):
        for key,value in [('creationTime',999),('handleValue',999),('waitResult',0),('exitCode',0),('image','C:/foreign.exe')]:
            changed=copy.deepcopy(self.value);changed['nativeSnapshots']['controllerAfter']['office'][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_owned_observation(changed,self.binding,'C:/Suite')

    def test_foreign_hwnd_parent_root_or_export_rejected(self):
        for location,key,value in [('child','pid',99),('child','parentHwnd',44),('parent','rootHwnd',44),('suite','isWindow',False)]:
            changed=copy.deepcopy(self.value);changed['nativeSnapshots']['helperAfter']['windows'][location][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_owned_observation(changed,self.binding,'C:/Suite')
        self.value['nativeSnapshots']['controllerBefore']['windows']['exportedChildHwnd']=44
        with self.assertRaises(AssertionError):self.api.require_owned_observation(self.value,self.binding,'C:/Suite')

    def test_duplicate_or_foreign_frame_and_broken_model_links_rejected(self):
        for change in ('duplicate','foreign','identity','url','controllerFrame','modelController'):
            changed=copy.deepcopy(self.value);u=changed['unoSnapshots']['after']
            if change=='duplicate':u['frames'].append(dict(index=1,containerHwnd=22));u['frameCount']=2
            elif change=='foreign':u['frames'][0]['containerHwnd']=44
            elif change=='identity':u['retained']['model']='invented-serial'
            elif change=='url':u['documentUrl']='file:///C:/foreign.docx'
            else:u['equalities'][change]=False
            with self.subTest(change=change),self.assertRaises(AssertionError):self.api.require_owned_observation(changed,self.binding,'C:/Suite')

    def test_reader_must_be_real_packaged_job_member_not_editor(self):
        for key,value in [('inOwnedJob',False),('pid',88),('image','C:/foreign/python.exe'),('waitResult',0)]:
            changed=copy.deepcopy(self.value);changed['readerProcess'][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_owned_observation(changed,self.binding,'C:/Suite')

    def test_cleanup_requires_normal_allmember_exit_and_actual_handle_closures(self):
        for change in ('crash','alive','job','ack','forced','close','deadline','missing'):
            c=cleanup_fixture(self.binding,'C:/Suite')
            if change=='crash':c['readerMembers'][0]['exitCode']=0xc0000005
            elif change=='alive':c['readerMembers'][0]['waitResult']=258
            elif change=='job':c['finalJobPids']=[99]
            elif change=='ack':c['releaseAcknowledgement']['proxiesReleased']=False
            elif change=='forced':c['terminated']=True
            elif change=='close':c['handleClosures'][0]['result']=False
            elif change=='deadline':c['finishedAt']=12.001
            elif change=='missing':c['handleClosures'].pop()
            with self.subTest(change=change),self.assertRaises(AssertionError):self.api.require_reader_cleanup(c,self.binding,12.0)

    def test_constructor_has_no_windows_filesystem_or_uno_side_effect(self):
        with patch.object(self.api,'_native_anchor',side_effect=AssertionError('eager native query')):
            r=self.api.OwnedWriterReader(Path('C:/Suite'),Path('C:/out'),shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
                child_hwnd=22,office_pid=88,expected_url='')
        self.assertIsNone(r.binding)

    def test_absolute_deadline_cannot_be_reset_and_expiry_does_not_open_editor(self):
        r=self.api.OwnedWriterReader(Path('C:/Suite'),Path('C:/out'),shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
            child_hwnd=22,office_pid=88,expected_url='',clock=lambda:12.0)
        with patch.object(self.api,'_native_anchor',side_effect=AssertionError('deadline was ignored')):
            with self.assertRaises(TimeoutError):r.start(12.0)
        with self.assertRaises(AssertionError):r.read(24.0)

    def test_atomic_bounded_transport_rejects_existing_link_oversize_and_foreign_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'request.json'
            self.api._atomic_json(path,dict(sequence=0,action='read'))
            self.assertEqual(self.api._read_json(path)['sequence'],0)
            with self.assertRaises(AssertionError):self.api._atomic_json(path,{})
            path.write_bytes(b'x'*(self.api.MAX_JSON_BYTES+1))
            with self.assertRaises(AssertionError):self.api._read_json(path)
            link=root/'link';link.write_text('{}')
            original_is_symlink=Path.is_symlink
            with patch.object(Path,'is_symlink',lambda p:p==link or original_is_symlink(p)):
                with self.assertRaises(AssertionError):self.api._read_json(link)
        with self.assertRaises(AssertionError):self.api._require_reply(dict(sequence=1,action='read',ok=True),0,'read')

    def test_backend_error_is_fatal_and_preserves_original_raw(self):
        raw=dict(sequence=0,action='read',ok=False,error=dict(type='DisposedException',message='original'))
        with self.assertRaises(self.api.ReaderBackendError) as caught:self.api._require_reply(raw,0,'read')
        self.assertEqual(caught.exception.raw,raw)


class RuntimeBoundaryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('reader_runtime_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def test_actual_uno_getter_checks_retained_links_before_and_after_without_mutation(self):
        from types import SimpleNamespace
        api=self.api;binding=binding_fixture();events=[]
        class Model:
            def __repr__(self):return binding['modelIdentity']
            def getURL(self):events.append('url');return binding['documentUrl']
            def supportsService(self,name):return name=='com.sun.star.text.TextDocument'
            def getCurrentController(self):return controller
            def getText(self):events.append('getText');return SimpleNamespace(getString=lambda:events.append('getString') or 'original')
            def isModified(self):events.append('isModified');return True
        model=Model()
        class Controller:
            def __repr__(self):return binding['controllerIdentity']
            def getFrame(self):return frame
            def getModel(self):return model
        controller=Controller()
        class Frame:
            def __repr__(self):return binding['frameIdentity']
            def getController(self):return controller
            def getContainerWindow(self):return SimpleNamespace(getWindowHandle=lambda args,system:22)
        frame=Frame()
        reader=api._UnoReader.__new__(api._UnoReader)
        reader.config=dict(child_hwnd=22,expected_url=binding['documentUrl'])
        reader.desktop=SimpleNamespace(getFrames=lambda:SimpleNamespace(getCount=lambda:1,getByIndex=lambda index:frame))
        reader.frame=frame;reader.controller=controller;reader.model=model
        reader.retained={k:binding[k+'Identity'] for k in ('frame','controller','model')}
        evidence=reader.read()
        self.assertEqual(evidence['bodyText'],'original')
        self.assertEqual(events,['url','getText','getString','isModified','url'])
        model.getURL=lambda:'file:///C:/foreign.docx';events.clear()
        with self.assertRaises(AssertionError):reader.read()
        self.assertEqual(events,[], 'Foreign original-model binding must fail before reading body')
        reader.release();self.assertIsNone(reader.model)

    def test_native_query_failure_closes_only_original_readonly_handles(self):
        from types import SimpleNamespace
        events=[];api=self.api
        class Witness:
            def __init__(self,pid):self.handle=pid;self.creation_time=pid
            def close_handle(self,handle):events.append(('close',handle));return True
            def code(self):return 259
        class Diagnostics:
            def identity(self,handle):raise OSError('original QueryFullProcessImageNameW failure')
        config=dict(suite='C:/Suite',shell_pid=77,expected_shell_creation=111,office_pid=88,suite_hwnd=11,parent_hwnd=12,child_hwnd=22)
        modules={'startup_smoke':SimpleNamespace(EngineProcessWitness=Witness),
                 'windows_smoke':SimpleNamespace(Windows=lambda:SimpleNamespace(user=object()))}
        native=SimpleNamespace(ProcessDiagnosticsApi=Diagnostics,bind=lambda *args:None)
        with patch.dict('sys.modules',modules),patch.object(api,'_worker_native',lambda:native):
            with self.assertRaisesRegex(OSError,'original Query'):api._native_anchor(config)
        self.assertEqual(events,[('close',77)])

    def test_recycled_original_shell_pid_rejected_before_office_or_uno_open(self):
        from types import SimpleNamespace
        api=self.api;events=[]
        class Witness:
            def __init__(self,pid):events.append(('open',pid));self.handle=pid;self.creation_time=999
            def close_handle(self,handle):events.append(('close',handle));return True
            def code(self):return 259
        class Diagnostics:
            def identity(self,handle):return dict(image='C:/Suite/OpenGeul.Office.exe',creationTime=999)
            def wait_for(self,handle,milliseconds):return 258
        config=dict(suite='C:/Suite',shell_pid=77,expected_shell_creation=111,office_pid=88,suite_hwnd=11,parent_hwnd=12,child_hwnd=22)
        modules={'startup_smoke':SimpleNamespace(EngineProcessWitness=Witness),'windows_smoke':SimpleNamespace(Windows=lambda:SimpleNamespace(user=object()))}
        native=SimpleNamespace(ProcessDiagnosticsApi=Diagnostics,bind=lambda *args:None)
        with patch.dict('sys.modules',modules),patch.object(api,'_worker_native',lambda:native):
            with self.assertRaisesRegex(AssertionError,'Original Popen shell generation'):api._native_anchor(config)
        self.assertEqual(events,[('open',77),('close',77)])

    def test_owned_job_file_rpc_retains_same_model_then_closes_all_helpers_before_editor(self):
        from types import SimpleNamespace
        api=self.api;binding=binding_fixture();raw=native_fixture(binding,'C:/Suite');events=[];active=True
        class Anchor:
            base={k:v for k,v in binding.items() if k not in ('frameIdentity','controllerIdentity','modelIdentity','documentUrl')}
            def snapshot(self):events.append('native-observe');return copy.deepcopy(raw['nativeSnapshots']['controllerBefore'])
            def close(self):events.append('native-release');return [dict(kind=k,handleValue=v,result=True) for k,v in [('shell',101),('office',102)]]
        class Job:
            def __init__(self,argv,cwd):
                self.job=401;self.handle=302;self.pid=98;self.close_handle=lambda h:events.append(('close',h)) or True
                events.append(('suspended-job-resume',argv[0]))
            def poll(self):return None
            def terminate(self):events.append('terminate-reader-job')
            def close(self):
                self.close_handle(self.handle);self.close_handle(self.job);self.handle=self.job=None
        class Diagnostics:
            def job_pids(self,job):return [98,99] if active else []
            def open_owned(self,pid,job):events.append(('open-private-member',pid,job));return pid+300
            def identity(self,handle):return dict(image='C:/Suite/Office/program/'+('python.exe' if handle==398 else 'python-core-3.13.15/bin/python.exe'),creationTime=handle)
            def is_in_job(self,handle,job,result):result._obj.value=True;return True
            def state(self,handle):return dict(alive=active,exitCode=259 if active else 0)
            def close_handle(self,handle):events.append(('close',handle));return True
        def atomic(path,value):
            nonlocal active
            original(path,value)
            if path.name.startswith('request-'):
                action=value['action'];reply=dict(sequence=value['sequence'],action=action,ok=True,readerPid=99)
                if action=='release':active=False;reply['proxiesReleased']=True;events.append('proxies-released')
                else:
                    obs=observation_fixture(binding);obs['nativeSnapshots']={k:v for k,v in obs['nativeSnapshots'].items() if k.startswith('helper')}
                    obs['pythonIdentity']={'observed':{'processImage':'C:/Suite/Office/program/python-core-3.13.15/bin/python.exe'}}
                    reply['observation']=obs
                original(path.parent/f"reply-{value['sequence']:03d}.json",reply)
        original=api._atomic_json
        native=SimpleNamespace(ProcessDiagnosticsApi=Diagnostics,OwnedOfficeProcess=Job)
        style=SimpleNamespace(require_packaged_python=lambda suite,observed:dict(observed=observed))
        with tempfile.TemporaryDirectory() as directory,patch.object(api,'_native_anchor',lambda c:Anchor()), \
             patch.object(api,'_worker_native',lambda:native),patch.object(api,'_launch_owned',lambda n,a,c:(Job(a,c),raw['helperLaunch'])),patch.object(api,'_atomic_json',atomic),patch.dict('sys.modules',{'writer_style_smoke':style}):
            r=api.OwnedWriterReader(Path('C:/Suite'),Path(directory)/'fresh',shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
                child_hwnd=22,office_pid=88,expected_url=binding['documentUrl'],clock=lambda:1.0)
            first=r.start(12.0);second=r.read(12.0);cleanup=r.close(12.0)
            self.assertEqual(first['bindingBefore'],second['bindingAfter']);self.assertTrue(cleanup['cleanupSucceeded'])
            self.assertNotIn('terminate-reader-job',events)
            self.assertLess(events.index('proxies-released'),events.index('native-release'))
            self.assertEqual({r['pid'] for r in cleanup['readerMembers']},{98,99})
            self.assertTrue((Path(directory)/'fresh/cleanup.json').is_file())

    def test_hung_helper_timeout_terminates_only_private_job_and_never_resets_budget(self):
        from types import SimpleNamespace
        api=self.api;events=[];clock=[1.0]
        r=api.OwnedWriterReader(Path('C:/Suite'),Path('C:/unused'),shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
            child_hwnd=22,office_pid=88,expected_url='',clock=lambda:clock[0])
        r.deadline=12.0;r.process=SimpleNamespace(terminate=lambda:events.append('private-helper-job'))
        clock[0]=12.001
        with self.assertRaises(TimeoutError):
            try:r._remaining(12.0)
            except TimeoutError as exc:
                with patch.object(Path,'exists',return_value=False):r._record_failure(exc)
                raise
        self.assertEqual(events,['private-helper-job']);self.assertTrue(r.forced)
        self.assertEqual(r.first_error['type'],'TimeoutError')
        with self.assertRaises(AssertionError):r._remaining(24.0)


class AdditionalFailureContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('reader_failure_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def test_profile_transport_unique_and_exact_command_join(self):
        api=self.api;binding=binding_fixture();value=observation_fixture(binding)
        for which in ('profile-duplicate','accept-duplicate','foreignprofile','foreignpipe','remoteprofile'):
            changed=copy.deepcopy(value);raw=changed['nativeSnapshots']['helperAfter'];argv=raw['officeCommandLine']
            if which=='profile-duplicate':argv.append(argv[-1])
            elif which=='accept-duplicate':argv.append(argv[-2])
            elif which=='foreignprofile':argv[-1]='-env:UserInstallation=file:///C:/other';raw['profileUrl']='file:///C:/other'
            elif which=='foreignpipe':argv[-2]=argv[-2].replace('a'*32,'b'*32)
            else:argv[-1]='-env:UserInstallation=file://foreign/profile';raw['profileUrl']='file://foreign/profile'
            with self.subTest(which=which),self.assertRaises(AssertionError):api.require_owned_observation(changed,binding,'C:/Suite')
        self.assertEqual(api.office_profile_url(value['nativeSnapshots']['controllerBefore']['officeCommandLine']),'file:///C:/private-profile')

    def test_actual_unchanged_owned_constructor_launch_order_and_failed_thread_close_receipt(self):
        from types import SimpleNamespace
        api=self.api
        for close_ok in (True,False):
            last_error=[0];native=api._worker_native()
            class Function:
                def __init__(self,fn):self.fn=fn
                def __call__(self,*args):return self.fn(*args)
            def created(*args):
                info=args[-1]._obj;info.hProcess=302;info.hThread=303;info.dwProcessId=98;info.dwThreadId=198
                return True
            def close(handle):
                if handle==303 and not close_ok:last_error[0]=6;return False
                return True
            kernel=SimpleNamespace(CreateJobObjectW=Function(lambda *args:401),CreateProcessW=Function(created),
                AssignProcessToJobObject=Function(lambda *args:True),ResumeThread=Function(lambda *args:1),
                CloseHandle=Function(close),GetExitCodeProcess=Function(lambda *args:True),WaitForSingleObject=Function(lambda *args:0),
                TerminateJobObject=Function(lambda *args:True),TerminateProcess=Function(lambda *args:True))
            original=native.bind
            with patch.object(native,'windows_dll',lambda name:kernel),patch.object(api,'_last_error',lambda:last_error[0]), \
                 patch.object(api,'_clear_last_error',lambda:last_error.__setitem__(0,0)):
                process,receipt=api._launch_owned(native,['C:/Suite/Office/program/python.exe','reader.py','--helper','owned-output'],Path('C:/Suite'))
                self.assertIs(native.bind,original)
                self.assertEqual([r['api'] for r in receipt['steps']],['CreateJobObjectW','CreateProcessW','AssignProcessToJobObject','ResumeThread','CloseHandle'])
                self.assertNotIn('environment',str(receipt).lower())
                if close_ok:api._require_launch(receipt,401)
                else:
                    self.assertEqual(receipt['firstFailure']['lastError'],6)
                    with self.assertRaises(AssertionError):api._require_launch(receipt,401)
                frozen=copy.deepcopy(receipt);process.close();self.assertEqual(receipt,frozen)

    def test_error_retention_or_job_termination_failure_cannot_replace_first_timeout(self):
        from types import SimpleNamespace
        api=self.api
        r=api.OwnedWriterReader(Path('C:/Suite'),Path('C:/unused'),shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
            child_hwnd=22,office_pid=88,expected_url='',clock=lambda:12.01)
        r.process=SimpleNamespace(terminate=lambda:(_ for _ in ()).throw(OSError('terminate failed')))
        r.attempted_observation={'raw':'kept'}
        with patch.object(Path,'exists',return_value=True),patch.object(api,'_atomic_json',side_effect=OSError('write failed')):
            r._record_failure(TimeoutError('original deadline'))
        self.assertEqual(r.first_error['type'],'TimeoutError');self.assertEqual(r.first_error['attemptedObservation'],{'raw':'kept'})
        self.assertEqual([v['stage'] for v in r.auxiliary_errors],['retain-primary-error','terminate-owned-helper-job'])

    def test_boolean_native_status_and_unpinned_helper_version_rejected(self):
        api=self.api;binding=binding_fixture()
        cleanup=cleanup_fixture(binding,'C:/Suite');cleanup['readerMembers'][0]['exitCode']=False
        with self.assertRaises(AssertionError):api.require_reader_cleanup(cleanup,binding,12.0)
        obs=observation_fixture(binding);obs['readerProcess']['image']='C:/Suite/Office/program/python-core-3.13.99/bin/python.exe'
        with self.assertRaises(AssertionError):api.require_owned_observation(obs,binding,'C:/Suite')


if __name__=='__main__':unittest.main()
