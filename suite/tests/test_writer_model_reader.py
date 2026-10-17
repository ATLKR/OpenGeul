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
    value=dict(kind='owned-writer-reader-cleanup',binding=copy.deepcopy(binding),cleanupSucceeded=True,physicalCleanupSucceeded=True,contextQualified=True,
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
    for index,row in enumerate(value['readerMembers']):state_sample_fixture(row,index)
    value.update(state_receipt_fixture(value['readerMembers']))
    return value


def state_sample_fixture(row,index):
    at=1.01+index*.001;handle=row['handleValue']
    row.update(sampleIndex=index,phase='release',sampleStartedAt=at,sampleFinishedAt=at,
        membershipCall=dict(api='IsProcessInJob',handleValue=handle,jobHandleValue=row['jobHandleValue'],result=True,inOwnedJob=True,lastError=0,observedAt=at),
        stateCalls=[dict(api='WaitForSingleObject',handleValue=handle,timeoutMilliseconds=0,result=row['waitResult'],lastError=0,observedAt=at),
            dict(api='GetExitCodeProcess',handleValue=handle,result=True,exitCode=row['exitCode'],lastError=0,observedAt=at)])
    return row


def state_receipt_fixture(rows):
    identities=[];samples=[]
    for row in rows:
        identity={key:row[key] for key in ('pid','creationTime','image','handleValue','jobHandleValue')}
        if identity not in identities:identities.append(identity)
        m=row['membershipCall'];w,e=row['stateCalls']
        samples.append(dict(index=row['sampleIndex'],member=identities.index(identity),phase=row['phase'],times=[row['sampleStartedAt'],row['sampleFinishedAt']],
            calls=[[m['api'],m['observedAt'],m['result'],m['inOwnedJob'],m['lastError']],
                [w['api'],w['observedAt'],w['result'],w['lastError']],[e['api'],e['observedAt'],e['result'],e['exitCode'],e['lastError']]]))
    return dict(memberStateIdentities=identities,memberStateSamples=samples)


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

    def _exit_script(self,pairs,*,release=True,job_stays=False,close_ok=True):
        """Actual controller/RPC/typed diagnostics, with only Windows DLL/file peers faked."""
        from types import SimpleNamespace
        api=self.api;binding=binding_fixture();fixture=cleanup_fixture(binding,'C:/Suite')
        members=copy.deepcopy(fixture['readerMembers'])
        members.append(dict(copy.deepcopy(members[0]),pid=100,handleValue=305,image=fixture['systemConsoleHost']['path']))
        script={row['handleValue']:list(pairs) for row in members};current={};events=[];clock=[1.0];last=[0];forced=[False]
        class Function:
            def __init__(self,function):self.function=function
            def __call__(self,*args):return self.function(*args)
        def wait(handle,milliseconds):
            self.assertEqual(milliseconds,0);events.append(('wait',handle))
            pair=(0,1) if forced[0] else script[handle].pop(0) if len(script[handle])>1 else script[handle][0]
            current[handle]=pair;last[0]=6 if pair[0]==0xffffffff else 0;return pair[0]
        def get_exit(handle,output):
            events.append(('exit',handle));code=current[handle][1]
            if code is None:last[0]=5;return False
            output._obj.value=code;last[0]=0;return True
        def membership(handle,job,output):output._obj.value=True;return True
        dll=SimpleNamespace(**{name:Function(lambda *args:True) for name in ('QueryInformationJobObject','OpenProcess','QueryFullProcessImageNameW','GetProcessTimes','CloseHandle')},
            IsProcessInJob=Function(membership),WaitForSingleObject=Function(wait),GetExitCodeProcess=Function(get_exit))
        native=api._worker_native()
        with patch.object(native,'windows_dll',lambda name:dll):diagnostics=native.ProcessDiagnosticsApi()
        diagnostics.job_pids=lambda job: [r['pid'] for r in members] if job_stays or any(current.get(r['handleValue'],(258,259))[0]==258 for r in members) else []
        self.assertEqual(diagnostics.wait_for.argtypes,[native.wt.HANDLE,native.wt.DWORD])
        self.assertEqual(diagnostics.get_exit.restype,native.wt.BOOL)
        class Job:
            job=401;handle=302;pid=98
            def poll(self):return None
            def terminate(self):forced[0]=True;events.append('terminate-owned-job')
            def close_handle(self,handle):events.append(('close',handle));return close_ok
            def close(self):self.close_handle(self.handle);self.close_handle(self.job);self.handle=self.job=None
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        reader=api.OwnedWriterReader(Path('C:/Suite'),Path(temporary.name),shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,child_hwnd=22,office_pid=88,expected_url=binding['documentUrl'],clock=lambda:clock[0])
        reader.deadline=12.0;reader.binding=binding;reader.process=Job();reader.diagnostics=diagnostics;reader.helper_launch=fixture['helperLaunch']
        reader.members={row['pid']:(row['handleValue'],{key:row[key] for key in ('creationTime','image')}) for row in members}
        reader.anchor=SimpleNamespace(base={key:value for key,value in binding.items() if key not in ('frameIdentity','controllerIdentity','modelIdentity','documentUrl')},
            snapshot=lambda:copy.deepcopy(fixture['nativeBefore']),close=lambda:[copy.deepcopy(row) for row in fixture['handleClosures'] if row['kind'] in ('shell','office','profile-directory')])
        reader.console=SimpleNamespace(witness=fixture['systemConsoleHost'],recheck=lambda:copy.deepcopy(fixture['systemConsoleHostRecheck']),close=lambda:dict(kind='system-console-file',handleValue=501,result=True))
        original=api._atomic_json
        def atomic(path,value):
            original(path,value)
            if path.name.startswith('request-'):
                ack=dict(fixture['releaseAcknowledgement'],ok=True,sequence=value['sequence'])
                original(path.parent/f"reply-{value['sequence']:03d}.json",ack)
        def sleep(seconds):clock[0]+=seconds
        with patch.object(api,'_atomic_json',atomic),patch.object(api.time,'sleep',sleep),patch.object(api,'_clear_last_error',lambda:last.__setitem__(0,0)),patch.object(api,'_last_error',lambda:last[0]),patch.object(api.ctypes,'WinError',lambda code:OSError(code,'fake native API failure'),create=True):
            if release:result=reader.close(12.0)
            else:
                try:reader._member_snapshots();result=None
                except BaseException as exc:result=exc
        return result,reader,events

    def test_release_transition_needs_fresh_signaled_zero_for_all_same_handles(self):
        cleanup,reader,events=self._exit_script([(258,0),(0,0)])
        self.assertTrue(cleanup['cleanupSucceeded'],cleanup['errors'])
        self.assertNotIn('terminate-owned-job',events)
        samples=[self.api._expand_member_sample(s,cleanup['memberStateIdentities']) for s in cleanup['memberStateSamples']];self.assertEqual(len(samples),6)
        self.assertEqual([(row['waitResult'],row['exitCode']) for row in samples],[(258,0)]*3+[(0,0)]*3)
        for row in cleanup['readerMembers']:
            first=next(r for r in samples if r['pid']==row['pid']);self.assertEqual(first['handleValue'],row['handleValue'])
            self.assertEqual([c['api'] for c in row['stateCalls']],['WaitForSingleObject','GetExitCodeProcess'])
        self.api.require_reader_cleanup(cleanup,self.binding,12.0)

    def test_read_transition_remains_failure_and_preserves_original_pair(self):
        failure,reader,events=self._exit_script([(258,0)],release=False)
        self.assertIsInstance(failure,AssertionError)
        self.assertEqual((reader.member_state_samples[0]['waitResult'],reader.member_state_samples[0]['exitCode']),(258,0))

    def test_exit_api_failures_and_crash_keep_first_raw_sample_during_forced_cleanup(self):
        for pair in ((258,0xc0000005),(0,259),(0xffffffff,0),(258,None)):
            with self.subTest(pair=pair):
                cleanup,reader,events=self._exit_script([pair])
                self.assertFalse(cleanup['cleanupSucceeded']);self.assertIn('terminate-owned-job',events)
                first=cleanup['memberStateSamples'][0];calls=first['calls']
                self.assertEqual(calls[1][2],pair[0])
                if pair[1] is None:
                    self.assertFalse(calls[2][2]);self.assertEqual(calls[2][4],5)
                    self.assertIsNone(calls[2][3])
                if pair[0]==0xffffffff:self.assertEqual(calls[1][3],6)
                elif pair[1] is not None:self.assertEqual(calls[2][3],pair[1])
                self.assertEqual(reader.member_state_samples[0]['sampleIndex'],first['index'])
                self.assertGreaterEqual(len(cleanup['errors']),2)

    def test_exit_pending_and_nonempty_job_cannot_extend_original_budget(self):
        for pair,job_stays in (((258,0),False),((0,0),True)):
            with self.subTest(pair=pair,job_stays=job_stays):
                cleanup,reader,events=self._exit_script([pair],job_stays=job_stays)
                self.assertFalse(cleanup['cleanupSucceeded']);self.assertTrue(cleanup['terminated'])
                self.assertEqual(reader.deadline,12.0);self.assertGreaterEqual(cleanup['finishedAt'],12.0)
                self.assertLessEqual(len(cleanup['memberStateSamples']),4096)

    def test_cleanup_replay_requires_final_raw_pair_and_same_retained_sample(self):
        for change in ('missing','handle','wait','exit','bool','order','time','generation','pending-read'):
            value=cleanup_fixture(self.binding,'C:/Suite');row=value['readerMembers'][0]
            if change=='missing':value.pop('memberStateSamples')
            elif change=='handle':row['stateCalls'][0]['handleValue']=999
            elif change=='wait':row['stateCalls'][0]['result']=258
            elif change=='exit':row['stateCalls'][1]['exitCode']=3
            elif change=='bool':row['stateCalls'][1]['result']=1
            elif change=='order':row['stateCalls'].reverse()
            elif change=='time':row['stateCalls'][1]['observedAt']=0
            elif change=='generation':value['memberStateIdentities'][0]['creationTime']+=1
            else:
                early=copy.deepcopy(value['memberStateSamples'][0]);early.update(phase='read');early['calls'][1][2]=258
                value['memberStateSamples'].insert(0,early)
                for index,sample in enumerate(value['memberStateSamples']):sample['index']=index
                for row in value['readerMembers']:row['sampleIndex']+=1
            with self.subTest(change=change),self.assertRaises(AssertionError):self.api.require_reader_cleanup(value,self.binding,12.0)

    def test_individual_sample_cap_fails_before_next_native_call(self):
        result,reader,events=self._exit_script([(258,259)],release=False)
        sample=reader.member_state_samples[0]
        reader.member_state_samples=[sample]*4096
        before=len(events)
        with self.assertRaisesRegex(AssertionError,'sample bound'):reader._member_snapshots()
        self.assertEqual(len(events),before)

    def test_maximum_individual_history_fits_original_transport_bound(self):
        value=cleanup_fixture(self.binding,'C:/Suite');rows=[]
        for index in range(4096):
            row=copy.deepcopy(value['readerMembers'][index%2]);state_sample_fixture(row,index)
            rows.append(row)
        value['readerMembers']=rows[-2:];value.update(self.api._member_samples_receipt(rows));value['finishedAt']=6.0
        self.api.require_reader_cleanup(value,self.binding,12.0)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bounded.json';self.api._atomic_json(path,value)
            self.assertLess(path.stat().st_size,2*1024*1024)
            self.assertEqual(self.api._read_json(path),value)

    def test_state_identity_table_cannot_hide_an_unobserved_member(self):
        value=cleanup_fixture(self.binding,'C:/Suite')
        value['memberStateIdentities'].append(dict(value['memberStateIdentities'][0],pid=101,handleValue=306))
        with self.assertRaises(AssertionError):self.api.require_reader_cleanup(value,self.binding,12.0)

    def test_release_pending_sample_cannot_be_backdated_into_read_phase(self):
        value=cleanup_fixture(self.binding,'C:/Suite')
        early=copy.deepcopy(value['readerMembers'][0]);state_sample_fixture(early,0)
        early.update(sampleStartedAt=.9,sampleFinishedAt=.9,waitResult=258,exitCode=0)
        early['membershipCall']['observedAt']=.9
        for call in early['stateCalls']:call['observedAt']=.9
        early['stateCalls'][0]['result']=258
        for row in value['readerMembers']:row['sampleIndex']+=1
        value.update(state_receipt_fixture([early]+value['readerMembers']))
        with self.assertRaises(AssertionError):self.api.require_reader_cleanup(value,self.binding,12.0)

    def test_release_reply_published_during_exit_poll_is_rechecked_exactly(self):
        from types import SimpleNamespace
        api=self.api
        for variant in ('valid','missing','wrong-sequence','wrong-action','error','read'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as directory:
                output=Path(directory);action='read' if variant=='read' else 'release'
                reply=dict(cleanup_fixture(self.binding,'C:/Suite')['releaseAcknowledgement'],sequence=0,ok=True)
                reply['action']=action
                if variant=='wrong-sequence':reply['sequence']=1
                elif variant=='wrong-action':reply['action']='read'
                elif variant=='error':reply.update(ok=False,error='original helper error')
                reader=api.OwnedWriterReader(Path('C:/Suite'),output,shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,child_hwnd=22,office_pid=88,expected_url=self.binding['documentUrl'],clock=lambda:1.0)
                reader.deadline=12.0;polls=[]
                def poll():
                    polls.append('poll')
                    if variant!='missing':api._atomic_json(output/'reply-000.json',reply)
                    return 0
                reader.process=SimpleNamespace(poll=poll)
                with patch.object(reader,'_member_snapshots',lambda **kwargs:[]),patch.object(api.time,'sleep',side_effect=AssertionError('Exit reply recheck must not add a wait')):
                    if variant=='valid':self.assertEqual(reader._rpc(action,12.0),reply)
                    else:
                        with self.assertRaises(AssertionError):reader._rpc(action,12.0)
                self.assertEqual(polls,['poll']);self.assertEqual(reader.deadline,12.0)
                self.assertEqual(api._read_json(output/'request-000.json'),dict(sequence=0,action=action))
                self.assertFalse((output/'request-001.json').exists())

    def test_terminal_retained_process_cannot_revive_in_raw_history(self):
        for revived_exit in (259,0):
            value=cleanup_fixture(self.binding,'C:/Suite');core,launcher=value['readerMembers'];rows=[]
            for index,(original,wait,exit_code) in enumerate(((core,0,0),(core,258,revived_exit),(core,0,0),(launcher,0,0))):
                row=dict(copy.deepcopy(original),waitResult=wait,exitCode=exit_code);state_sample_fixture(row,index);rows.append(row)
            value['readerMembers']=rows[-2:];value.update(state_receipt_fixture(rows))
            with self.subTest(revived_exit=revived_exit),self.assertRaises(AssertionError):self.api.require_reader_cleanup(value,self.binding,12.0)

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
            def wait_for(self,handle,milliseconds):return 258 if active else 0
            def get_exit(self,handle,output):output._obj.value=259 if active else 0;return True
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
        state_sample_fixture(console,2)
        cleanup['readerMembers'].append(console);cleanup['handleClosures'].append(dict(kind='member',handleValue=305,result=True))
        cleanup.update(state_receipt_fixture(cleanup['readerMembers']))
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
        state_sample_fixture(console,2)
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
            for row in members:
                row['sampleStartedAt']=row['sampleFinishedAt']=1.0
                row['membershipCall']['observedAt']=1.0
                for call in row['stateCalls']:call['observedAt']=1.0
            reader.member_state_samples=copy.deepcopy(members)
            with patch.object(reader,'_rpc',lambda action,deadline:copy.deepcopy(cleanup['releaseAcknowledgement'])),patch.object(reader,'_member_snapshots',lambda **kwargs:copy.deepcopy(members)):
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


class ExplicitOwnedModelContracts(unittest.TestCase):
    """Calc uses an explicit getter contract; synthetic peers are not Windows proof."""
    SERVICE='com.sun.star.sheet.SpreadsheetDocument'
    GETTERS='calc-a1-b1-c1-d1-v1'
    OPS=['resolve-existing-owned-frame','Sheet0.A1.getString','Sheet0.B1.getValue',
         'Sheet0.C1.getValue','Sheet0.D1.getFormula','Sheet0.D1.getValue','isModified','verify-retained-generation']

    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('explicit_owned_model_contract',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def require_api(self):
        for name in ('OwnedModelReader','require_owned_model_observation','require_model_reader_cleanup'):
            self.assertTrue(callable(getattr(self.api,name,None)), 'Missing explicit owned model API: '+name)
        return self.api

    def kwargs(self):
        return dict(expected_service=self.SERVICE,getter_contract=self.GETTERS)

    def calc_observation(self):
        binding=binding_fixture();binding['documentUrl']='file:///C:/owned.xlsx'
        value=observation_fixture(binding);value.pop('bodyText')
        value.update(kind='existing-owned-calc-cells',operations=list(self.OPS),sheetIndex=0,
            a1Text='Engine-OpenGeul-calc 한글UI-OpenGeul-calc',b1Value=17.0,c1Value=25.0,
            d1Formula='=SUM(B1:C1)',d1Value=42.0,isModified=True)
        for row in value['unoSnapshots'].values():row['modelService']=self.SERVICE
        return binding,value

    def make_calc_uno(self):
        from types import SimpleNamespace
        uno,events,objects=WindowsReaderFailureFixContracts().make_uno()
        values={'A1':'Engine-OpenGeul-calc 한글UI-OpenGeul-calc','B1':17.0,'C1':25.0,'D1':42.0}
        def cell(name):
            self.assertIn(name,values)
            return SimpleNamespace(getString=lambda:events.append(name+'.getString') or values[name],
                getValue=lambda:events.append(name+'.getValue') or values[name],
                getFormula=lambda:events.append(name+'.getFormula') or '=SUM(B1:C1)')
        sheet=SimpleNamespace(getCellRangeByName=cell)
        def sheet_at(index):
            self.assertEqual(index,0);events.append('sheet-0');return sheet
        objects['model'].getSheets=lambda:SimpleNamespace(getByIndex=sheet_at)
        objects['model'].supportsService=lambda name:name==self.SERVICE
        objects['model'].isModified=lambda:events.append('isModified') or True
        objects['model'].getURL=lambda:'file:///C:/owned.xlsx'
        return uno,events,objects

    def test_explicit_contract_rejects_missing_unknown_or_mixed_pair_before_native_access(self):
        api=self.require_api()
        native=dict(shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
            child_hwnd=22,office_pid=88,expected_url='file:///C:/owned.xlsx')
        with tempfile.TemporaryDirectory() as directory,patch.object(api,'_native_anchor',side_effect=AssertionError('must not open native state')):
            output=Path(directory)/'uncreated'
            for pair in ({},dict(expected_service=self.SERVICE),dict(getter_contract=self.GETTERS),
                         dict(expected_service=self.SERVICE,getter_contract='writer-body-v1'),
                         dict(expected_service='com.sun.star.text.TextDocument',getter_contract=self.GETTERS),
                         dict(expected_service=self.SERVICE,getter_contract='arbitrary-getter'),
                         dict(expected_service=None,getter_contract=None)):
                with self.subTest(pair=pair),self.assertRaises((AssertionError,TypeError)):
                    api.OwnedModelReader(Path('C:/Suite'),output,**native,**pair)
            reader=api.OwnedModelReader(Path('C:/Suite'),output,**native,**self.kwargs())
            self.assertIsNone(reader.process);self.assertFalse(output.exists())
            writer=api.OwnedWriterReader(Path('C:/Suite'),output,**native)
            self.assertNotIn('expected_service',writer.config);self.assertNotIn('getter_contract',writer.config)

    def test_calc_raw_validator_never_selects_contract_from_producer_fields(self):
        api=self.require_api();binding,value=self.calc_observation();original=copy.deepcopy(value)
        self.assertIs(api.require_owned_model_observation(value,binding,'C:/Suite',**self.kwargs()),value)
        self.assertEqual(value,original)
        with self.assertRaises(AssertionError):api.require_owned_observation(value,binding,'C:/Suite')
        with self.assertRaises(AssertionError):
            api.require_owned_model_observation(value,binding,'C:/Suite',expected_service='com.sun.star.text.TextDocument',getter_contract='writer-body-v1')
        for mutate in (
            lambda v:v.update(kind='existing-owned-writer-body'),
            lambda v:v.update(operations=list(api.OPERATIONS)),
            lambda v:v['unoSnapshots']['after'].update(modelService='com.sun.star.text.TextDocument'),
            lambda v:v['unoSnapshots']['before'].update(documentUrl='file:///C:/foreign.xlsx'),
            lambda v:v['nativeSnapshots']['helperAfter']['office'].update(creationTime=999),
            lambda v:v['nativeSnapshots']['helperAfter']['profileDirectory']['recheck'].update(fileIndexLow=999),
            lambda v:v['unoSnapshots']['after']['equalities'].update(modelController=False)):
            altered=copy.deepcopy(value);mutate(altered)
            with self.subTest(value=altered),self.assertRaises(AssertionError):
                api.require_owned_model_observation(altered,binding,'C:/Suite',**self.kwargs())
        writer_binding=binding_fixture();writer=observation_fixture(writer_binding);saved=copy.deepcopy(writer)
        api.require_owned_model_observation(writer,writer_binding,'C:/Suite',
            expected_service='com.sun.star.text.TextDocument',getter_contract='writer-body-v1')
        self.assertEqual(writer,saved)

    def test_explicit_contract_drift_before_start_opens_no_native_handles_or_output(self):
        api=self.require_api()
        with tempfile.TemporaryDirectory() as directory,patch.object(api,'_native_anchor',side_effect=AssertionError('native handle opened')) as native:
            output=Path(directory)/'uncreated'
            reader=api.OwnedModelReader(Path('C:/Suite'),output,shell_pid=77,expected_shell_creation=111,
                suite_hwnd=11,parent_hwnd=12,child_hwnd=22,office_pid=88,expected_url='file:///C:/owned.xlsx',clock=lambda:1.0,**self.kwargs())
            reader.config['getter_contract']='writer-body-v1'
            with self.assertRaises(AssertionError):reader.start(12.0)
            native.assert_not_called();self.assertFalse(output.exists());self.assertIsNone(reader.process)

    def test_calc_getter_schema_rejects_unbounded_nonfinite_boolean_or_wrong_sheet_values(self):
        api=self.require_api();binding,value=self.calc_observation()
        for key,replacement in (('a1Text',None),('a1Text','x'*(api.MAX_BODY_BYTES+1)),
                ('sheetIndex',True),('sheetIndex',1),('b1Value',True),('c1Value',float('nan')),
                ('d1Value',float('inf')),('d1Formula',None),('isModified',1)):
            altered=copy.deepcopy(value);altered[key]=replacement
            with self.subTest(key=key,replacement=type(replacement).__name__),self.assertRaises(AssertionError):
                api.require_owned_model_observation(altered,binding,'C:/Suite',**self.kwargs())

    def test_actual_calc_helper_reads_only_fixed_model_cells_and_keeps_retained_proxy_identity(self):
        from types import SimpleNamespace
        api=self.require_api();uno,events,objects=self.make_calc_uno()
        anchor=SimpleNamespace(base={'privatePipe':'OpenGeul_'+'a'*32},
            snapshot=lambda:{'native':'retained'},profile=SimpleNamespace(snapshot=lambda:profile_directory_fixture(handle=602)),
            close=lambda:[dict(kind=k,handleValue=h,result=True) for k,h in [('shell',201),('office',202),('profile-directory',602)]])
        identity={'observed':{'boundary':'synthetic-seven-role-identity'}}
        style=SimpleNamespace(observe_packaged_python=lambda:identity['observed'],require_packaged_python=lambda suite,observed:identity)
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'uno':uno,'writer_style_smoke':style}), \
             patch.object(api,'_native_anchor',lambda config:anchor),patch.object(api,'_qpc',lambda:(100,1000)):
            output=Path(directory)
            api._atomic_json(output/'configuration.json',dict(suite='C:/Suite',child_hwnd=22,expected_url='file:///C:/owned.xlsx',**self.kwargs()))
            for sequence,action in enumerate(('start','read','release')):
                api._atomic_json(output/f'request-{sequence:03d}.json',dict(sequence=sequence,action=action))
            self.assertEqual(api._helper(output,explicit_model=True),0)
            first=api._read_json(output/'reply-000.json')['observation'];second=api._read_json(output/'reply-001.json')['observation']
            self.assertEqual(first['kind'],'existing-owned-calc-cells');self.assertEqual(first['operations'],self.OPS)
            self.assertNotIn('bodyText',first);self.assertEqual(first['sheetIndex'],0)
            self.assertEqual([first[k] for k in ('a1Text','b1Value','c1Value','d1Formula','d1Value','isModified')],
                ['Engine-OpenGeul-calc 한글UI-OpenGeul-calc',17.0,25.0,'=SUM(B1:C1)',42.0,True])
            self.assertEqual(first['unoSnapshots']['before']['proxyIdentity'],second['unoSnapshots']['after']['proxyIdentity'])
            self.assertEqual(set(first['unoSnapshots']['before']['proxyIdentity']['retainedIds']),{'frame','controller','model'})
            self.assertTrue(api._read_json(output/'reply-002.json')['proxiesReleased'])
        self.assertEqual(events,2*['sheet-0','A1.getString','B1.getValue','C1.getValue','D1.getFormula','D1.getValue','isModified'])

    def test_explicit_helper_rejects_bad_contract_or_service_before_cell_getter(self):
        from types import SimpleNamespace
        api=self.require_api();uno,events,objects=self.make_calc_uno()
        anchor=SimpleNamespace(base={'privatePipe':'OpenGeul_'+'a'*32},last_snapshot={},close=lambda:[],profile=None)
        identity={'observed':{}}
        style=SimpleNamespace(observe_packaged_python=lambda:{},require_packaged_python=lambda *args:identity)
        for config in (dict(expected_service=self.SERVICE),dict(expected_service=self.SERVICE,getter_contract='writer-body-v1')):
            with tempfile.TemporaryDirectory() as directory,patch.object(api,'_native_anchor',side_effect=AssertionError('native access before contract rejection')):
                output=Path(directory);api._atomic_json(output/'configuration.json',dict(suite='C:/Suite',**config))
                with self.assertRaises((AssertionError,KeyError)):api._helper(output,explicit_model=True)
        objects['model'].supportsService=lambda name:False
        with tempfile.TemporaryDirectory() as directory,patch.dict('sys.modules',{'uno':uno,'writer_style_smoke':style}),patch.object(api,'_native_anchor',lambda config:anchor):
            output=Path(directory);api._atomic_json(output/'configuration.json',dict(suite='C:/Suite',child_hwnd=22,expected_url='file:///C:/owned.xlsx',**self.kwargs()))
            for sequence,action in enumerate(('start','release')):api._atomic_json(output/f'request-{sequence:03d}.json',dict(sequence=sequence,action=action))
            self.assertEqual(api._helper(output,explicit_model=True),0)
            self.assertFalse(api._read_json(output/'reply-000.json')['ok'])
        self.assertEqual(events,[])

    def test_calc_cleanup_reuses_exact_physical_quiescence_without_writer_fallback(self):
        api=self.require_api();binding,_=self.calc_observation();value=cleanup_fixture(binding,'C:/Suite')
        value['kind']='owned-calc-reader-cleanup'
        self.assertIs(api.require_model_reader_cleanup(value,binding,12.0,**self.kwargs()),value)
        with self.assertRaises(AssertionError):api.require_reader_cleanup(value,binding,12.0)
        for mutate in (lambda c:c.update(finalJobPids=[99]),lambda c:c.update(terminated=True),
                       lambda c:c['releaseAcknowledgement']['observerHandleClosures'].pop(),
                       lambda c:c['memberStateIdentities'][0].update(handleValue=999),
                       lambda c:c['memberStateSamples'][0]['calls'][2].__setitem__(3,1)):
            altered=copy.deepcopy(value);mutate(altered)
            with self.subTest(value=altered),self.assertRaises(AssertionError):
                api.require_model_reader_cleanup(altered,binding,12.0,**self.kwargs())

    def test_explicit_calc_controller_retains_one_job_and_releases_before_return(self):
        from types import SimpleNamespace
        api=self.require_api();binding,raw=self.calc_observation();events=[];active=True
        clean=cleanup_fixture(binding,'C:/Suite')
        class Anchor:
            base={k:v for k,v in binding.items() if k not in ('frameIdentity','controllerIdentity','modelIdentity','documentUrl')}
            def snapshot(self):return copy.deepcopy(raw['nativeSnapshots']['controllerBefore'])
            def close(self):events.append('native-release');return [dict(kind=k,handleValue=v,result=True) for k,v in [('shell',101),('office',102),('profile-directory',601)]]
        class Console:
            def __init__(self,*args):self.witness=copy.deepcopy(raw['systemConsoleHost'])
            def recheck(self):return copy.deepcopy(raw['systemConsoleHostRecheck'])
            def close(self):return dict(kind='system-console-file',handleValue=501,result=True)
        class Job:
            def __init__(self):self.job=401;self.handle=302;self.pid=98;self.close_handle=lambda handle:True
            def poll(self):return None
            def terminate(self):raise AssertionError('Normal Calc observer must never be terminated')
            def close(self):self.close_handle(self.handle);self.close_handle(self.job);self.handle=self.job=None
        class Diagnostics:
            def job_pids(self,job):return [98,99] if active else []
            def open_owned(self,pid,job):return pid+300
            def identity(self,handle):return dict(image='C:/Suite/Office/program/'+('python.exe' if handle==398 else 'python-core-3.13.15/bin/python.exe'),creationTime=handle)
            def is_in_job(self,handle,job,result):result._obj.value=True;return True
            def wait_for(self,handle,milliseconds):return 258 if active else 0
            def get_exit(self,handle,output):output._obj.value=259 if active else 0;return True
            def close_handle(self,handle):return True
        original=api._atomic_json
        def atomic(path,value):
            nonlocal active
            original(path,value)
            if path.name.startswith('request-'):
                action=value['action'];reply=dict(sequence=value['sequence'],action=action,ok=True,readerPid=99)
                if action=='release':
                    active=False;reply.update(clean['releaseAcknowledgement']);events.append('proxies-released')
                else:
                    obs=copy.deepcopy(raw);obs['nativeSnapshots']={k:v for k,v in obs['nativeSnapshots'].items() if k.startswith('helper')}
                    obs['pythonIdentity']={'observed':{'processImage':raw['readerProcess']['image']}}
                    reply['observation']=obs
                original(path.parent/f"reply-{value['sequence']:03d}.json",reply)
        def launch(native,argv,cwd):
            self.assertEqual(argv[2],'--model-helper');events.append('launch-private-job')
            config=api._read_json(Path(argv[3])/'configuration.json')
            self.assertEqual((config['expected_service'],config['getter_contract']),(self.SERVICE,self.GETTERS))
            return Job(),raw['helperLaunch']
        native=SimpleNamespace(ProcessDiagnosticsApi=Diagnostics)
        style=SimpleNamespace(require_packaged_python=lambda suite,observed:dict(observed=observed))
        with tempfile.TemporaryDirectory() as directory,patch.object(api,'_native_anchor',lambda config:Anchor()), \
             patch.object(api,'_worker_native',lambda:native),patch.object(api,'_SystemConsoleHost',Console), \
             patch.object(api,'_launch_owned',launch),patch.object(api,'_atomic_json',atomic),patch.dict('sys.modules',{'writer_style_smoke':style}):
            reader=api.OwnedModelReader(Path('C:/Suite'),Path(directory)/'fresh',shell_pid=77,expected_shell_creation=111,
                suite_hwnd=11,parent_hwnd=12,child_hwnd=22,office_pid=88,expected_url=binding['documentUrl'],clock=lambda:1.0,**self.kwargs())
            first=reader.start(12.0);second=reader.read(12.0);cleanup=reader.close(12.0)
            api.require_model_reader_cleanup(cleanup,reader.binding,12.0,**self.kwargs())
            self.assertEqual(first['bindingBefore'],second['bindingAfter'])
            self.assertEqual(cleanup['kind'],'owned-calc-reader-cleanup');self.assertTrue(cleanup['cleanupSucceeded'])
            self.assertEqual(sum(event=='launch-private-job' for event in events),1)
            self.assertLess(events.index('proxies-released'),events.index('native-release'))
            with self.assertRaises(AssertionError):reader.read(13.0)


if __name__=='__main__':unittest.main()
