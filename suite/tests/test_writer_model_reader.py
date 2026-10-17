"""Portable raw ownership/frame replay and bounded-reader contracts; no live UNO."""
import copy
import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/writer_model_reader.py'


def profile_directory_fixture(profile_url='file:///C:/private-profile',handle=601,canonical_path=None):
    """Synthetic native DIRECTORY proof, not an inferred short-name expansion."""
    from pathlib import PureWindowsPath
    from urllib.parse import unquote,urlsplit
    decoded=str(PureWindowsPath(unquote(urlsplit(profile_url).path)[1:]))
    canonical=str(PureWindowsPath(canonical_path or decoded))
    info=dict(fileAttributes=16,creationTime=101,lastAccessTime=102,lastWriteTime=103,volumeSerialNumber=104,
        size=4096,numberOfLinks=1,fileIndexHigh=0,fileIndexLow=105,fileType=1,finalPath='\\\\?\\'+canonical)
    witness=dict(schemaVersion=1,kind='native-owned-profile-directory',profileUrl=profile_url,decodedPath=decoded,
        canonicalPath=canonical,handleValue=handle,desiredAccess=128,shareMode=7,openFlags=0x02000000,openedInfo=copy.deepcopy(info))
    return dict(witness=witness,recheck=copy.deepcopy(info))


def console_host_fixture():
    data=b'os-host-fixture'
    info=dict(fileAttributes=32,creationTime=101,lastAccessTime=102,lastWriteTime=103,volumeSerialNumber=104,
        size=len(data),numberOfLinks=2,fileIndexHigh=0,fileIndexLow=105,fileType=1,finalPath='C:/Windows/System32/conhost.exe')
    witness=dict(schemaVersion=1,systemDirectoryQuery=dict(api='GetSystemDirectoryW',capacity=32768,returnedLength=19,path='C:/Windows/System32'),
        path='C:/Windows/System32/conhost.exe',handleValue=501,desiredAccess=0x80000000,shareMode=1,openFlags=0x200080,
        fileInfoBefore=copy.deepcopy(info),fileInfoAfterHash=copy.deepcopy(info),bytesHashed=len(data),sha256=hashlib.sha256(data).hexdigest())
    return witness,copy.deepcopy(info)


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
        windows=windows,privatePipe=binding['privatePipe'],officeCommandLine=['soffice.bin','--invisible','--accept=pipe,name='+binding['privatePipe']+';urp;StarOffice.ServiceManager','-env:UserInstallation=file:///C:/private-profile'],profileUrl='file:///C:/private-profile',profileDirectory=profile_directory_fixture())
    helper=copy.deepcopy(snapshot); helper['shell']['handleValue']=201;helper['office']['handleValue']=202
    helper['profileDirectory']['witness']['handleValue']=602
    retained={name:binding[name+'Identity'] for name in ('frame','controller','model')}
    uno=dict(frameCount=1,frames=[dict(index=0,containerHwnd=binding['childHwnd'])],matchedFrameIndex=0,
        retained=retained,equalities={k:True for k in ('frame','controller','model','controllerFrame','modelController')},
        documentUrl=binding['documentUrl'],modelService='com.sun.star.text.TextDocument',
        proxyIdentity=dict(helperPid=99,localContextId=700,proxyTypeId=701,proxyTypeName='pyuno',proxyTypeModule='builtins',
            retainedIds={k:int(binding[k+'Identity'].split('0x')[-1],16) for k in ('frame','controller','model')},
            typeMatches={k:True for k in ('frame','controller','model')}))
    console,recheck=console_host_fixture()
    return dict(systemConsoleHost=console,systemConsoleHostRecheck=recheck,nativeSnapshots=dict(controllerBefore=copy.deepcopy(snapshot),controllerAfter=copy.deepcopy(snapshot),
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
    return dict(kind='owned-writer-reader-cleanup',binding=copy.deepcopy(binding),cleanupSucceeded=True,physicalCleanupSucceeded=True,contextQualified=True,
        startedAt=1.0,finishedAt=1.1,deadline=12.0,terminated=False,
        releaseAcknowledgement=dict(action='release',readerPid=99,proxiesReleased=True,
            profileDirectory=copy.deepcopy(raw['nativeSnapshots']['helperBefore']['profileDirectory']),
            observerHandleClosures=[dict(kind=kind,handleValue=value,result=True) for kind,value in [('shell',201),('office',202),('profile-directory',602)]]),
        readerMembers=[member,dict(copy.deepcopy(member),pid=98,handleValue=304,image=str(suite_root).replace('\\','/').rstrip('/')+'/Office/program/python.exe')],finalJobPids=[],jobHandleValue=401,helperLaunch=raw['helperLaunch'],
        systemConsoleHost=raw['systemConsoleHost'],systemConsoleHostRecheck=raw['systemConsoleHostRecheck'],
        nativeBefore=raw['nativeSnapshots']['controllerBefore'],nativeAfter=raw['nativeSnapshots']['controllerAfter'],
        handleClosures=[dict(kind='member',handleValue=301,result=True),dict(kind='member',handleValue=304,result=True),dict(kind='process',handleValue=302,result=True),
            dict(kind='job',handleValue=401,result=True),dict(kind='shell',handleValue=101,result=True),
            dict(kind='office',handleValue=102,result=True),dict(kind='profile-directory',handleValue=601,result=True),dict(kind='system-console-file',handleValue=501,result=True)],errors=[])


def binding_fixture():
    return dict(shellPid=77,shellCreationTime=111,officePid=88,officeCreationTime=222,
        expectedImage='C:/Suite/Office/program/soffice.bin',suiteHwnd=11,parentHwnd=12,childHwnd=22,rootHwnd=11,
        privatePipe='OpenGeul_'+'a'*32,frameIdentity='pyuno-proxy:0x1234',
        controllerIdentity='pyuno-proxy:0x2345',modelIdentity='pyuno-proxy:0x3456',
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
        uno,events,objects=WindowsReaderFailureFixContracts().make_uno()
        with patch.dict('sys.modules',{'uno':uno}):
            reader=self.api._UnoReader(dict(child_hwnd=22,expected_url='file:///C:/owned.docx'),SimpleNamespace(base={'privatePipe':'OpenGeul_'+'a'*32}))
            self.assertEqual(reader.read()['bodyText'],'unchanged body')
        self.assertEqual(events,['getText','getString'])
        reader.config['expected_url']='file:///C:/foreign.docx';events.clear()
        with self.assertRaises(AssertionError):reader.read()
        self.assertEqual(events,[]);reader.release();self.assertIsNone(reader.model)

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
            def close(self):events.append('native-release');return [dict(kind=k,handleValue=v,result=True) for k,v in [('shell',101),('office',102),('profile-directory',601)]]
        class Console:
            def __init__(self,*args):self.witness=copy.deepcopy(raw['systemConsoleHost'])
            def recheck(self):return copy.deepcopy(raw['systemConsoleHostRecheck'])
            def close(self):return dict(kind='system-console-file',handleValue=501,result=True)
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
                if action=='release':
                    active=False;reply.update(cleanup_fixture(binding,'C:/Suite')['releaseAcknowledgement']);events.append('proxies-released')
                else:
                    obs=observation_fixture(binding);obs['nativeSnapshots']={k:v for k,v in obs['nativeSnapshots'].items() if k.startswith('helper')}
                    obs['pythonIdentity']={'observed':{'processImage':'C:/Suite/Office/program/python-core-3.13.15/bin/python.exe'}}
                    reply['observation']=obs
                original(path.parent/f"reply-{value['sequence']:03d}.json",reply)
        original=api._atomic_json
        native=SimpleNamespace(ProcessDiagnosticsApi=Diagnostics,OwnedOfficeProcess=Job)
        style=SimpleNamespace(require_packaged_python=lambda suite,observed:dict(observed=observed))
        with tempfile.TemporaryDirectory() as directory,patch.object(api,'_native_anchor',lambda c:Anchor()), \
             patch.object(api,'_worker_native',lambda:native),patch.object(api,'_SystemConsoleHost',Console),patch.object(api,'_launch_owned',lambda n,a,c:(Job(a,c),raw['helperLaunch'])),patch.object(api,'_atomic_json',atomic),patch.dict('sys.modules',{'writer_style_smoke':style}):
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



class WindowsReaderFailureFixContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('reader_windows_fix_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def make_uno(self,bad_url=False,foreign_model=False):
        from types import SimpleNamespace
        events=[];objects={}
        class pyuno:
            def __init__(self,name):self.name=name
            def __repr__(self):raise AssertionError('deep repr is display only and must never be invoked')
            def __eq__(self,other):return type(other) is pyuno and self.name==other.name
            def __getattr__(self,name):return methods[self.name][name]
        for name in ('local','remote','desktop','resolver','frame','controller','model','frames','peer','text'):objects[name]=pyuno(name)
        service=SimpleNamespace(createInstanceWithContext=lambda name,context:objects['resolver' if name.endswith('UnoUrlResolver') else 'desktop'])
        methods={
            'local':{'ServiceManager':service},'remote':{'ServiceManager':service},
            'resolver':{'resolve':lambda url:objects['remote']},
            'desktop':{'getFrames':lambda:objects['frames']},
            'frames':{'getCount':lambda:1,'getByIndex':lambda index:objects['frame']},
            'frame':{'getContainerWindow':lambda:objects['peer'],'getController':lambda:objects['controller']},
            'peer':{'getWindowHandle':lambda args,system:22},
            'controller':{'getFrame':lambda:objects['frame'],'getModel':lambda:SimpleNamespace() if foreign_model else objects['model']},
            'model':{'getCurrentController':lambda:objects['controller'],'getURL':lambda:'file:///C:/foreign.docx' if bad_url else 'file:///C:/owned.docx',
                     'supportsService':lambda name:name=='com.sun.star.text.TextDocument','getText':lambda:events.append('getText') or objects['text'],
                     'isModified':lambda:True},
            'text':{'getString':lambda:events.append('getString') or 'unchanged body'}}
        return SimpleNamespace(getComponentContext=lambda:objects['local']),events,objects

    def test_actual_constructor_uses_retained_proxy_identity_without_display_repr(self):
        from types import SimpleNamespace
        uno,events,objects=self.make_uno()
        with patch.dict('sys.modules',{'uno':uno}):
            reader=self.api._UnoReader(dict(child_hwnd=22,expected_url='file:///C:/owned.docx'),SimpleNamespace(base={'privatePipe':'OpenGeul_'+'a'*32}))
            body=reader.read()
        self.assertEqual(body['bodyText'],'unchanged body');self.assertEqual(events,['getText','getString'])
        for role in ('frame','controller','model'):
            self.assertEqual(reader.retained[role],'pyuno-proxy:0x'+format(id(objects[role]),'x'))
        reader.release();self.assertIsNone(reader.local_context)

    def test_constructor_failure_preserves_actual_type_frame_snapshot_and_releases_proxies(self):
        from types import SimpleNamespace
        for foreign in (False,True):
            uno,events,objects=self.make_uno(bad_url=not foreign,foreign_model=foreign)
            with patch.dict('sys.modules',{'uno':uno}):
                with self.assertRaises(AssertionError) as caught:
                    self.api._UnoReader(dict(child_hwnd=22,expected_url='file:///C:/owned.docx'),SimpleNamespace(base={'privatePipe':'OpenGeul_'+'a'*32}))
            error=caught.exception
            self.assertEqual(error.uno_diagnostic['frameEnumeration'],[{'index':0,'containerHwnd':22}])
            self.assertIn('model',error.uno_diagnostic['proxyTypes'])
            self.assertTrue(error.observer_proxies_released)
            self.assertEqual(events,[], 'Constructor rejection must happen before body getter')

    def test_mixed_private_job_allows_only_frozen_system_console_and_never_as_reader(self):
        api=self.api;binding=binding_fixture();cleanup=cleanup_fixture(binding,'C:/Suite')
        console=dict(copy.deepcopy(cleanup['readerMembers'][0]),pid=100,creationTime=335,handleValue=305,image=cleanup['systemConsoleHost']['path'])
        cleanup['readerMembers'].append(console);cleanup['handleClosures'].append(dict(kind='member',handleValue=305,result=True))
        api.require_reader_cleanup(cleanup,binding,12.0)
        for change in ('foreign','second','foreignjob','crash','reader','witnesspath','witnesshash','fileid','size'):
            value=copy.deepcopy(cleanup)
            if change=='foreign':value['readerMembers'][-1]['image']='C:/foreign/conhost.exe'
            elif change=='second':value['readerMembers'].append(dict(console,pid=101,handleValue=306));value['handleClosures'].append(dict(kind='member',handleValue=306,result=True))
            elif change=='foreignjob':value['readerMembers'][-1]['inOwnedJob']=False
            elif change=='crash':value['readerMembers'][-1]['exitCode']=0xc0000005
            elif change=='reader':value['releaseAcknowledgement']['readerPid']=100
            elif change=='witnesspath':value['systemConsoleHost']['path']='C:/foreign/conhost.exe'
            elif change=='witnesshash':value['systemConsoleHost']['sha256']='not-a-hash'
            elif change=='fileid':value['systemConsoleHostRecheck']['fileIndexLow']+=1
            elif change=='size':value['systemConsoleHostRecheck']['size']+=1
            with self.subTest(change=change),self.assertRaises(AssertionError):api.require_reader_cleanup(value,binding,12.0)

    def test_unc_system_directory_and_boolean_schema_do_not_qualify_as_local_os_witness(self):
        api=self.api
        for directory in ('//server/share/Windows/System32','//?/C:/Windows/System32','C:/Windows/../System32','C:/Windows/System32\x00'):
            witness,current=console_host_fixture();witness['systemDirectoryQuery'].update(path=directory,returnedLength=len(directory.encode('utf-16-le'))//2)
            witness['path']=str(__import__('pathlib').PureWindowsPath(directory)/'conhost.exe')
            for key in ('fileInfoBefore','fileInfoAfterHash'):witness[key]['finalPath']=witness['path']
            with self.subTest(directory=directory),self.assertRaises(AssertionError):api.require_console_host_witness(witness)
        witness,current=console_host_fixture();witness['schemaVersion']=True
        with self.assertRaises(AssertionError):api.require_console_host_witness(witness)

    def test_unc_query_rejected_before_opening_any_file(self):
        from types import SimpleNamespace
        directory='//server/share/Windows/System32';events=[]
        api=SimpleNamespace(system_directory=lambda:dict(api='GetSystemDirectoryW',capacity=32768,returnedLength=len(directory),path=directory),
            open=lambda path:events.append('opened') or 501)
        with self.assertRaises(AssertionError):self.api._SystemConsoleHost(12.0,lambda:1.0,api)
        self.assertEqual(events,[])

    def test_access_time_is_raw_metadata_and_not_frozen_content_identity(self):
        witness,current=console_host_fixture();current['lastAccessTime']+=999
        self.api.require_console_host_witness(witness,current)

    def test_same_handle_os_file_hash_once_then_recheck_and_close(self):
        api=self.api;witness,info=console_host_fixture();events=[]
        class FileApi:
            def __init__(self):self.blocks=[b'os-host-fixture',b'']
            def system_directory(self):events.append('GetSystemDirectoryW');return copy.deepcopy(witness['systemDirectoryQuery'])
            def open(self,path):events.append(('open',path));return 501
            def info(self,handle):events.append(('info',handle));return copy.deepcopy(info)
            def read(self,handle,count):events.append(('read',handle));return self.blocks.pop(0)
            def close_handle(self,handle):events.append(('close',handle));return True
        native=FileApi();retained=api._SystemConsoleHost(12.0,lambda:1.0,native)
        retained.recheck();retained.recheck();self.assertEqual(len([e for e in events if isinstance(e,tuple) and e[0]=='read']),2)
        self.assertEqual(retained.witness['sha256'],witness['sha256']);self.assertTrue(retained.close()['result'])
        self.assertEqual(events[0],'GetSystemDirectoryW');self.assertEqual(events[-1],('close',501))
        self.assertEqual(__import__('ctypes').sizeof(api._FileInformation),52)

    def test_os_file_changed_during_hash_or_deadline_is_fatal_and_closes_only_its_handle(self):
        api=self.api;witness,info=console_host_fixture();closed=[]
        class FileApi:
            count=0
            def system_directory(self):return copy.deepcopy(witness['systemDirectoryQuery'])
            def open(self,path):return 501
            def info(self,handle):
                self.count+=1;value=copy.deepcopy(info)
                if self.count>1:value['fileIndexLow']+=1
                return value
            def read(self,handle,count):return b'os-host-fixture' if self.count==1 and not hasattr(self,'read_once') and not setattr(self,'read_once',True) else b''
            def close_handle(self,handle):closed.append(handle);return True
        with self.assertRaises(AssertionError):api._SystemConsoleHost(12.0,lambda:1.0,FileApi())
        self.assertEqual(closed,[501])
        with self.assertRaises(TimeoutError):api._SystemConsoleHost(12.0,lambda:12.0,FileApi())



class ConstructorAndAncillaryEvidenceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('reader_ctor_evidence_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def test_actual_helper_forwards_constructor_failure_metadata_before_assignment_and_stays_failed(self):
        from types import SimpleNamespace
        api=self.api;uno,events,objects=WindowsReaderFailureFixContracts().make_uno(bad_url=True)
        original=uno.getComponentContext
        uno.getComponentContext=lambda:events.append('resolve-local-context') or original()
        identity={'observed':{'source':'synthetic-seven-role-boundary'}}
        style=SimpleNamespace(observe_packaged_python=lambda:events.append('python-identity-before-resolution') or identity['observed'],
            require_packaged_python=lambda suite,observed:identity)
        anchor=SimpleNamespace(base={'privatePipe':'OpenGeul_'+'a'*32},last_snapshot={'owned':'native'},
            profile=SimpleNamespace(snapshot=lambda:profile_directory_fixture(handle=602)),
            close=lambda:[dict(kind='shell',handleValue=201,result=True),dict(kind='office',handleValue=202,result=True),dict(kind='profile-directory',handleValue=602,result=True)])
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'uno':uno,'writer_style_smoke':style}),patch.object(api,'_native_anchor',lambda config:anchor):
            output=Path(directory)
            api._atomic_json(output/'configuration.json',dict(suite='C:/Suite',child_hwnd=22,expected_url='file:///C:/owned.docx'))
            for sequence,action in enumerate(('start','read','release')):api._atomic_json(output/f'request-{sequence:03d}.json',dict(sequence=sequence,action=action))
            self.assertEqual(api._helper(output),0)
            error=api._read_json(output/'reply-000.json')['error']
            self.assertEqual(error['frameEnumeration'],[{'index':0,'containerHwnd':22}]);self.assertEqual(error['unoSnapshot']['documentUrl'],'file:///C:/foreign.docx')
            self.assertTrue(error['observerProxiesReleased']);self.assertEqual(error['pythonIdentity'],identity)
            self.assertTrue(error['unoDiagnostic']['proxyTypes']['model']['sameAsLocalType'])
            self.assertFalse(api._read_json(output/'reply-001.json')['ok'])
            self.assertTrue(api._read_json(output/'reply-002.json')['proxiesReleased'])
        self.assertEqual(events[:2],['python-identity-before-resolution','resolve-local-context']);self.assertNotIn('getText',events)

    def _clean_failed_context(self,established=False):
        from types import SimpleNamespace
        api=self.api;binding=binding_fixture();cleanup=cleanup_fixture(binding,'C:/Suite')
        console=dict(copy.deepcopy(cleanup['readerMembers'][0]),pid=100,creationTime=335,handleValue=305,image=cleanup['systemConsoleHost']['path'])
        members=cleanup['readerMembers']+[console]
        class Job:
            handle=302;job=401;pid=98
            def close_handle(self,handle):return True
            def close(self):self.close_handle(self.handle);self.close_handle(self.job);self.handle=self.job=None
            def terminate(self):raise AssertionError('Clean failed constructor must not terminate editor or helper')
        with tempfile.TemporaryDirectory() as directory:
            reader=api.OwnedWriterReader(Path('C:/Suite'),Path(directory),shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
                child_hwnd=22,office_pid=88,expected_url=binding['documentUrl'],clock=lambda:1.0)
            reader.deadline=12.0;reader.process=Job();reader.helper_launch=cleanup['helperLaunch']
            if established:reader.binding=copy.deepcopy(binding)
            try:raise OSError('original observer read failure' if established else 'original constructor failure')
            except OSError as original:reader._record_failure(original)
            base={k:v for k,v in binding.items() if k not in ('frameIdentity','controllerIdentity','modelIdentity','documentUrl')}
            reader.anchor=SimpleNamespace(base=base,snapshot=lambda:copy.deepcopy(cleanup['nativeBefore']),close=lambda:[r for r in cleanup['handleClosures'] if r['kind'] in ('shell','office','profile-directory')])
            reader.console=SimpleNamespace(witness=cleanup['systemConsoleHost'],recheck=lambda:copy.deepcopy(cleanup['systemConsoleHostRecheck']),close=lambda:dict(kind='system-console-file',handleValue=501,result=True))
            reader.diagnostics=SimpleNamespace(job_pids=lambda job:[],close_handle=lambda handle:True)
            reader.members={r['pid']:(r['handleValue'],dict(image=r['image'],creationTime=r['creationTime'])) for r in members}
            with patch.object(reader,'_rpc',lambda action,deadline:copy.deepcopy(cleanup['releaseAcknowledgement'])),patch.object(reader,'_member_snapshots',lambda:copy.deepcopy(members)):
                result=reader.close(12.0)
            self.assertTrue(result['physicalCleanupSucceeded']);self.assertFalse(result['contextQualified']);self.assertFalse(result['cleanupSucceeded'])
            self.assertEqual(result['errors'],[]);self.assertEqual(result['binding'],binding if established else None)
            self.assertEqual(reader.first_error['message'],'original observer read failure' if established else 'original constructor failure')

    def test_constructor_failure_can_clean_mixed_job_without_invented_model_binding_or_typeerror(self):
        self._clean_failed_context()

    def test_failed_established_reader_context_cannot_qualify_after_successful_physical_cleanup(self):
        self._clean_failed_context(established=True)

    def test_launcher_ack_cannot_borrow_core_version_token_from_suite_ancestor(self):
        root='C:/python-core-3.13.15/Suite';binding=dict(binding_fixture(),expectedImage=root+'/Office/program/soffice.bin')
        cleanup=cleanup_fixture(binding,root)
        self.api.require_reader_cleanup(cleanup,binding,12.0)
        cleanup['releaseAcknowledgement']['readerPid']=98
        with self.assertRaises(AssertionError):self.api.require_reader_cleanup(cleanup,binding,12.0)

    def test_proxy_type_or_retained_id_substitutions_cannot_pass_portable_native_replay(self):
        api=self.api;binding=binding_fixture()
        for field in ('typeMatches','retainedIds','proxyTypeName','helperPid'):
            obs=observation_fixture(binding);proxy=obs['unoSnapshots']['after']['proxyIdentity']
            if field=='typeMatches':proxy[field]['model']=False
            elif field=='retainedIds':proxy[field]['model']+=1
            elif field=='proxyTypeName':proxy[field]='lookalike'
            else:proxy[field]=100
            with self.subTest(field=field),self.assertRaises(AssertionError):api.require_owned_observation(obs,binding,'C:/Suite')


class NativeProfileDirectoryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('native_profile_reader_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def require_api(self):
        self.assertTrue(callable(getattr(self.api,'require_profile_directory_witness',None)),
            'Native original-argv canonical DIRECTORY witness is required')
        return self.api

    def test_raw_short_profile_url_uses_native_long_directory_identity_without_filesystem_replay(self):
        api=self.require_api()
        short='file:///C:/Users/RUNNER~1/AppData/Local/Temp/OpenGeul-office-mp2w7dlo'
        long='C:/Users/runneradmin/AppData/Local/Temp/OpenGeul-office-mp2w7dlo'
        raw=profile_directory_fixture(short,canonical_path=long)
        with patch.object(Path,'resolve',side_effect=AssertionError('Portable profile replay must not resolve aliases')):
            api.require_profile_directory_witness(raw['witness'],short,raw['recheck'])
            value=api.canonical_profile_projection(raw['witness'],short)
        self.assertEqual(value,dict(profileUrl=short,canonicalPath=long.replace('/','\\').casefold(),
            volumeSerialNumber=104,fileIndexHigh=0,fileIndexLow=105))
        self.assertIn('RUNNER~1',raw['witness']['decodedPath'])

    def test_mutable_directory_metadata_is_not_profile_identity(self):
        api=self.require_api();raw=profile_directory_fixture()
        for field in ('size','lastAccessTime','lastWriteTime','creationTime','numberOfLinks'):
            raw['recheck'][field]+=999
        api.require_profile_directory_witness(raw['witness'],raw['witness']['profileUrl'],raw['recheck'])

    def test_foreign_profile_url_canonical_path_volume_fileid_or_file_not_directory_rejected(self):
        api=self.require_api();original=profile_directory_fixture()
        for field in ('profileUrl','decodedPath','canonicalPath','volumeSerialNumber','fileIndexLow','fileAttributes'):
            raw=copy.deepcopy(original)
            if field=='profileUrl':raw['witness'][field]='file:///C:/foreign-profile'
            elif field=='decodedPath':raw['witness'][field]='C:\\foreign-profile'
            elif field=='canonicalPath':raw['witness'][field]='C:\\foreign-profile'
            elif field=='fileAttributes':raw['recheck'][field]=32
            else:raw['recheck'][field]+=1
            with self.subTest(field=field),self.assertRaises(AssertionError):
                api.require_profile_directory_witness(raw['witness'],original['witness']['profileUrl'],raw['recheck'])

    def test_nonlocal_or_malformed_profile_uri_fails_before_any_directory_open(self):
        api=self.require_api()
        from types import SimpleNamespace
        events=[];native=SimpleNamespace(open=lambda path:events.append(path) or 601)
        for url in ('file://remote/share/profile','file:///tmp/profile','file:///C:/private/../other',
                    'file:///C:/private%00profile','file:///C:/private%5Cprofile','file:///C:/profile?query','file:///C:/profile#fragment'):
            with self.subTest(url=url),self.assertRaises(AssertionError):api._NativeProfileDirectory(url,12.0,lambda:1.0,native)
        self.assertEqual(events,[])

    def test_native_snapshot_requires_each_retained_profile_and_matching_controller_helper_identity(self):
        api=self.require_api();binding=binding_fixture();original=observation_fixture(binding)
        for change in ('missing','handle','foreign-directory'):
            value=copy.deepcopy(original)
            if change=='missing':value['nativeSnapshots']['helperAfter'].pop('profileDirectory')
            elif change=='handle':value['nativeSnapshots']['controllerAfter']['profileDirectory']['witness']['handleValue']+=1
            else:
                for edge in ('Before','After'):
                    raw=value['nativeSnapshots']['helper'+edge]['profileDirectory']
                    for info in (raw['witness']['openedInfo'],raw['recheck']):info['fileIndexLow']+=1
            with self.subTest(change=change),self.assertRaises(AssertionError):api.require_owned_observation(value,binding,'C:/Suite')

    def test_cleanup_requires_actual_controller_and_helper_directory_handle_closures(self):
        api=self.require_api();binding=binding_fixture()
        for origin in ('controller','helper','missing-helper-proof'):
            cleanup=cleanup_fixture(binding,'C:/Suite')
            if origin=='missing-helper-proof':cleanup['releaseAcknowledgement'].pop('profileDirectory')
            else:
                rows=cleanup['handleClosures'] if origin=='controller' else cleanup['releaseAcknowledgement']['observerHandleClosures']
                next(row for row in rows if row['kind']=='profile-directory')['result']=False
            with self.subTest(origin=origin),self.assertRaises(AssertionError):api.require_reader_cleanup(cleanup,binding,12.0)

    def test_actual_typed_directory_api_keeps_same_64bit_handle_without_reading_directory_data(self):
        api=self.require_api()
        self.assertTrue(callable(getattr(api,'_NativeProfileDirectory',None)), 'Retained typed native DIRECTORY acquisition is required')
        import ctypes
        from types import SimpleNamespace
        short='file:///C:/Users/RUNNER~1/Temp/OpenGeul-office-owned'
        raw=profile_directory_fixture(short,canonical_path='C:/Users/runneradmin/Temp/OpenGeul-office-owned')
        events=[];handle=0x123456789
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        def opened(path,access,share,security,disposition,flags,template):
            self.assertEqual((path,access,share,disposition,flags),(raw['witness']['decodedPath'],128,7,3,0x02000000))
            events.append(('open',path));return handle
        def info(value,target):
            self.assertEqual(value,handle);row=target._obj;row.attributes=16;row.volume=104;row.indexLow=105
            row.creation.low=101;row.write.low=len(events)+200;row.access.low=300;row.sizeLow=4096;row.links=1
            events.append(('info',value));return True
        def final(value,buffer,capacity,flags):
            self.assertEqual((value,capacity,flags),(handle,32768,0));buffer.value=raw['recheck']['finalPath'];return len(buffer.value)
        kernel=SimpleNamespace(CreateFileW=Function(opened),GetFileInformationByHandle=Function(info),
            GetFinalPathNameByHandleW=Function(final),GetFileType=Function(lambda value:1),
            CloseHandle=Function(lambda value:events.append(('close',value)) or True),
            ReadFile=Function(lambda *args:(_ for _ in ()).throw(AssertionError('Directory data must never be read'))),
            GetSystemDirectoryW=Function(lambda *args:(_ for _ in ()).throw(AssertionError('Profile path must come from original argv'))))
        with patch.object(ctypes,'WinDLL',lambda *args,**kwargs:kernel,create=True):
            directory=api._NativeProfileDirectory(short,12.0,lambda:1.0)
            first=directory.snapshot();second=directory.snapshot();closed=directory.close()
        self.assertEqual(first['witness'],second['witness']);self.assertEqual(first['witness']['handleValue'],handle)
        self.assertNotEqual(first['recheck']['lastWriteTime'],second['recheck']['lastWriteTime'])
        self.assertTrue(closed['result']);self.assertEqual(closed['kind'],'profile-directory');self.assertEqual(events[-1],('close',handle))
        self.assertEqual(kernel.CreateFileW.restype,api.W.HANDLE);self.assertEqual(ctypes.sizeof(api._FileInformation),52)

    def test_typed_directory_query_failure_preserves_original_error_and_actual_failed_close(self):
        api=self.require_api()
        import ctypes
        from types import SimpleNamespace
        events=[];last=[0];handle=0x123456789
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        def failed_info(*args):last[0]=5;return False
        def failed_close(value):events.append(('close',value));last[0]=6;return False
        kernel=SimpleNamespace(CreateFileW=Function(lambda *args:handle),GetFileInformationByHandle=Function(failed_info),
            GetFinalPathNameByHandleW=Function(lambda *args:0),GetFileType=Function(lambda *args:1),
            CloseHandle=Function(failed_close),ReadFile=Function(lambda *args:False),GetSystemDirectoryW=Function(lambda *args:0))
        with patch.object(ctypes,'WinDLL',lambda *args,**kwargs:kernel,create=True), \
             patch.object(ctypes,'WinError',lambda value:OSError(value,'original native query failure'),create=True), \
             patch.object(ctypes,'get_last_error',lambda:last[0],create=True),patch.object(api,'_clear_last_error',lambda:last.__setitem__(0,0)):
            with self.assertRaises(OSError) as caught:api._NativeProfileDirectory('file:///C:/private-profile',12.0,lambda:1.0)
        self.assertEqual(caught.exception.errno,5)
        self.assertEqual(caught.exception.profile_directory_closure,dict(kind='profile-directory',handleValue=handle,result=False,lastError=6))
        self.assertEqual(events,[('close',handle)])

    def test_profile_directory_recheck_cannot_reset_deadline_or_reopen_expired_handle(self):
        api=self.require_api()
        from types import SimpleNamespace
        raw=profile_directory_fixture();clock=[1.0];events=[]
        native=SimpleNamespace(open=lambda path:events.append('open') or 601,
            info=lambda handle:events.append('info') or copy.deepcopy(raw['recheck']),close_handle=lambda handle:events.append('close') or True)
        retained=api._NativeProfileDirectory(raw['witness']['profileUrl'],12.0,lambda:clock[0],native)
        clock[0]=12.0
        with self.assertRaises(TimeoutError):retained.snapshot()
        self.assertEqual(events,['open','info']);retained.close();self.assertEqual(events,['open','info','close'])

    def test_actual_native_anchor_retains_profile_opened_from_original_office_argv(self):
        api=self.require_api()
        from types import SimpleNamespace
        import time
        import native_accessibility
        events=[];binding=binding_fixture();raw=native_fixture(binding,'C:/Suite')['nativeSnapshots']['controllerBefore']
        short='file:///C:/Users/RUNNER~1/Temp/OpenGeul-office-owned'
        profile=profile_directory_fixture(short,canonical_path='C:/Users/runneradmin/Temp/OpenGeul-office-owned')
        arguments=raw['officeCommandLine'][:-1]+['-env:UserInstallation='+short]
        class Witness:
            def __init__(self,pid):self.pid=pid;self.handle=pid+1000;self.creation_time=111 if pid==77 else 222
            def code(self):return 259
            def close_handle(self,handle):events.append(('process-close',handle));return True
        class Diagnostics:
            def identity(self,handle):return dict(image='C:/Suite/'+('OpenGeul.Office.exe' if handle==1077 else 'Office/program/soffice.bin'),creationTime=111 if handle==1077 else 222)
            def wait_for(self,*args):return 258
        user=SimpleNamespace(IsWindow=lambda hwnd:True,GetAncestor=lambda hwnd,flag:11,
            GetPropW=lambda hwnd,name:12 if name.endswith('ParentHwnd') else 22)
        windows=SimpleNamespace(user=user,pid=lambda hwnd:88 if hwnd==22 else 77)
        native=SimpleNamespace(ProcessDiagnosticsApi=Diagnostics,bind=lambda *args:lambda hwnd:{11:0,12:11,22:12}[hwnd])
        file_api=SimpleNamespace(open=lambda path:events.append(('directory-open',path)) or 601,
            info=lambda handle:copy.deepcopy(profile['recheck']),close_handle=lambda handle:events.append(('directory-close',handle)) or True)
        real_profile=api._NativeProfileDirectory
        config=dict(suite='C:/Suite',shell_pid=77,expected_shell_creation=111,office_pid=88,suite_hwnd=11,parent_hwnd=12,child_hwnd=22,readerDeadline=time.monotonic()+12)
        modules={'startup_smoke':SimpleNamespace(EngineProcessWitness=Witness),'windows_smoke':SimpleNamespace(Windows=lambda:windows)}
        with patch.dict('sys.modules',modules),patch.object(api,'_worker_native',lambda:native), \
             patch.object(native_accessibility,'_command_line',lambda process:list(arguments)), \
             patch.object(api,'_NativeProfileDirectory',lambda url,deadline:real_profile(url,deadline,api=file_api)):
            anchor=api._native_anchor(config);first=anchor.snapshot();second=anchor.snapshot();closures=anchor.close()
        self.assertEqual(first['profileDirectory']['witness'],second['profileDirectory']['witness'])
        self.assertEqual(first['profileUrl'],short);self.assertEqual(first['profileDirectory']['witness']['canonicalPath'],profile['witness']['canonicalPath'])
        self.assertEqual(events[0],('directory-open',profile['witness']['decodedPath']))
        self.assertEqual([row['kind'] for row in closures],['profile-directory','shell','office'])
        self.assertEqual(sum(event[0]=='directory-open' for event in events),1)


if __name__=='__main__':unittest.main()
