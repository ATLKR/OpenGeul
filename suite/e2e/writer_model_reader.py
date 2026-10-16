"""Bounded E2E-only getter of the original owned Writer model.

The controller makes no UNO calls. An unchanged suspended->private-job->resume
launcher contains every helper call, including pipe resolution. This reader has
no document creation, loading, input, dispatch, focus, save or close capability.
Portable raw-receipt validators below do not query Windows or the filesystem.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import time
import traceback
from urllib.parse import unquote, urlsplit

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 1024 * 1024
OPERATIONS = ['resolve-existing-owned-frame','Text.getString','isModified','verify-retained-generation']
PROCESS_KEYS = ('pid','creationTime','image','handleValue','waitResult','exitCode')

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_accessibility import private_pipe as _parse_private_pipe


def _path(value):
    assert isinstance(value,str) and value, 'Missing absolute native path'
    path=PureWindowsPath(value)
    if path.is_absolute():
        assert '..' not in path.parts
        return str(path).casefold()
    path=PurePosixPath(value)
    assert path.is_absolute() and '..' not in path.parts, 'Relative native path'
    return str(path)


def _join(root,relative):
    p=PureWindowsPath(str(root))
    return str(p/relative) if p.is_absolute() else str(PurePosixPath(str(root))/relative)


def _positive(value):
    assert type(value) is int and value>0, 'Missing positive native identifier'
    return value


def _finite(value):
    assert type(value) in (int,float) and math.isfinite(value) and value>=0, 'Invalid controller monotonic time'
    return value


def _pipe(arguments):
    # Same public pinned parser as the existing accessibility harness.
    assert isinstance(arguments,list) and 1<=len(arguments)<=64 and all(isinstance(x,str) for x in arguments)
    return _parse_private_pipe(arguments)


def _profile(arguments):
    values=[v[len('-env:UserInstallation='):] for v in arguments if v.startswith('-env:UserInstallation=')]
    assert len(values)==1,'Expected one private Office profile'
    value=values[0];uri=urlsplit(value)
    assert uri.scheme=='file' and not uri.netloc and not uri.query and not uri.fragment
    path=unquote(uri.path)
    assert path.startswith('/') and '..' not in PurePosixPath(path).parts and '\\' not in path
    return value


def office_profile_url(arguments):
    """Parse the single original profile URL from native Windows argv, without I/O."""
    return _profile(arguments)


def _require_binding(binding,suite_root):
    assert isinstance(binding,dict), 'Missing original Writer binding'
    for key in ('shellPid','shellCreationTime','officePid','officeCreationTime','suiteHwnd','parentHwnd','childHwnd','rootHwnd'):_positive(binding.get(key))
    assert binding['shellPid']!=binding['officePid'] and binding['rootHwnd']==binding['suiteHwnd']
    assert len({binding['suiteHwnd'],binding['parentHwnd'],binding['childHwnd']})==3
    assert _path(binding.get('expectedImage'))==_path(_join(suite_root,'Office/program/soffice.bin'))
    assert isinstance(binding.get('privatePipe'),str) and re.fullmatch(r'OpenGeul_[0-9a-f]{32}',binding['privatePipe'])


def _require_native(raw,binding,suite_root):
    _require_binding(binding,suite_root)
    assert isinstance(raw,dict), 'Missing raw retained native snapshot'
    for name,pid,created,image in (
        ('shell',binding['shellPid'],binding['shellCreationTime'],_join(suite_root,'OpenGeul.Office.exe')),
        ('office',binding['officePid'],binding['officeCreationTime'],binding['expectedImage'])):
        row=raw.get(name,{})
        assert row.get('pid')==pid and type(row.get('pid')) is int
        assert row.get('creationTime')==created and type(created) is int and created>0
        _positive(row.get('handleValue'))
        assert _path(row.get('image'))==_path(image), 'Retained executable changed'
        assert type(row.get('waitResult')) is int and type(row.get('exitCode')) is int
        assert row['waitResult']==258 and row['exitCode']==259, 'Original process is no longer alive'
    windows=raw.get('windows',{})
    for name,hwnd,pid in (('suite',binding['suiteHwnd'],binding['shellPid']),
                          ('parent',binding['parentHwnd'],binding['shellPid']),
                          ('child',binding['childHwnd'],binding['officePid'])):
        row=windows.get(name,{})
        assert row.get('isWindow') is True and row.get('hwnd')==hwnd and row.get('pid')==pid
        assert row.get('rootHwnd')==binding['suiteHwnd'], 'Window left original Suite root'
    assert windows['suite']['parentHwnd']==0
    assert windows['parent']['parentHwnd']==binding['suiteHwnd'], 'Original panel parent changed'
    assert windows['child']['parentHwnd']==binding['parentHwnd'], 'Original editor parent changed'
    assert windows.get('exportedParentHwnd')==binding['parentHwnd'] and windows.get('exportedChildHwnd')==binding['childHwnd']
    assert raw.get('privatePipe')==binding['privatePipe']==_pipe(raw.get('officeCommandLine')), 'Original private pipe changed'
    assert raw.get('profileUrl')==_profile(raw['officeCommandLine']), 'Private profile URL is missing'


def _require_pair(before,after,binding,suite_root):
    _require_native(before,binding,suite_root);_require_native(after,binding,suite_root)
    for name in ('shell','office'):
        assert before[name]['handleValue']==after[name]['handleValue'], 'Retained process HANDLE was replaced'
    assert before['officeCommandLine']==after['officeCommandLine'] and before['profileUrl']==after['profileUrl'], 'Original Office command/profile changed'


def _require_uno(raw,binding):
    assert isinstance(raw,dict) and type(raw.get('frameCount')) is int and 1<=raw['frameCount']<=8
    frames=raw.get('frames')
    assert isinstance(frames,list) and len(frames)==raw['frameCount']
    assert all(type(r.get('index')) is int for r in frames) and [r.get('index') for r in frames]==list(range(raw['frameCount'])), 'Frame enumeration is incomplete'
    matches=[r for r in frames if r.get('containerHwnd')==binding['childHwnd']]
    assert len(matches)==1 and type(raw.get('matchedFrameIndex')) is int and raw.get('matchedFrameIndex')==matches[0]['index'], 'Original native frame is ambiguous or foreign'
    retained=raw.get('retained',{})
    for name in ('frame','controller','model'):
        value=binding[name+'Identity']
        assert isinstance(value,str) and value.startswith('pyuno object ') and len(value)<=4096, 'Identity must come from retained live PyUNO object'
        assert retained.get(name)==value
    eq=raw.get('equalities',{})
    assert set(eq)=={'frame','controller','model','controllerFrame','modelController'} and all(v is True for v in eq.values()), 'Original live UNO links changed'
    assert raw.get('modelService')=='com.sun.star.text.TextDocument' and raw.get('documentUrl')==binding['documentUrl'], 'Foreign Writer model or URL'


def _reader_member(row,binding,suite_root,alive):
    assert isinstance(row,dict) and row.get('inOwnedJob') is True and row.get('isInJobApiSucceeded') is True
    _positive(row.get('jobHandleValue'))
    assert _positive(row.get('pid')) not in (binding['shellPid'],binding['officePid'])
    _positive(row.get('creationTime'));_positive(row.get('handleValue'))
    root=_path(_join(suite_root,'Office/program'))
    image=_path(row.get('image'))
    assert image.startswith(root+('\\' if '\\' in root else '/'))
    tail=image[len(root)+1:].replace('\\','/')
    assert tail=='python.exe' or re.fullmatch(r'python-core-3\.13\.15/bin/python\.exe',tail), 'Reader job contains a foreign executable'
    assert type(row.get('waitResult')) is int and type(row.get('exitCode')) is int
    assert row.get('waitResult')==(258 if alive else 0) and row.get('exitCode')==(259 if alive else 0), 'Reader did not exit normally' if not alive else 'Reader is not alive'


def _require_launch(receipt,job=None):
    assert isinstance(receipt,dict) and receipt.get('firstFailure') is None, 'Missing or failed actual helper launch APIs'
    steps=receipt.get('steps')
    assert isinstance(steps,list) and [r.get('api') for r in steps]==[
        'CreateJobObjectW','CreateProcessW','AssignProcessToJobObject','ResumeThread','CloseHandle']
    assert all(type(row.get('lastError')) is int and 0<=row['lastError']<=0xffffffff for row in steps), 'Raw helper launch LastError is missing'
    created,process,assigned,resumed,closed=steps
    job_handle=_positive(created.get('handleValue'))
    if job is not None:assert job_handle==job
    assert process.get('result') is True and type(process.get('creationFlags')) is int and process['creationFlags']==0x08000404
    assert process.get('inheritHandles') is False and isinstance(process.get('application'),str) and isinstance(process.get('command'),str)
    assert 0<len(process['command'])<=32767
    pid=_positive(process.get('pid'));_positive(process.get('threadId'))
    process_handle=_positive(process.get('processHandleValue'));thread_handle=_positive(process.get('threadHandleValue'))
    assert assigned.get('result') is True and assigned.get('jobHandleValue')==job_handle and assigned.get('processHandleValue')==process_handle
    assert type(resumed.get('previousSuspendCount')) is int and resumed['previousSuspendCount']==1 and resumed.get('threadHandleValue')==thread_handle
    assert closed.get('result') is True and closed.get('handleValue')==thread_handle, 'Initial helper thread HANDLE was not closed'
    return pid,process_handle,job_handle


def require_owned_observation(observation,binding,suite_root):
    """Replay raw original-generation/frame evidence, with no native calls or I/O."""
    assert isinstance(observation,dict) and observation.get('kind')=='existing-owned-writer-body'
    assert observation.get('bindingBefore')==binding==observation.get('bindingAfter')
    for key in ('retainedProcessHandle','readOnlyObservation','sameFrameControllerModelVerified','readCallCleanupSucceeded','readerStillRetained'):
        assert observation.get(key) is True, 'Incomplete read-only observation: '+key
    assert observation.get('handleSignaled') is False and observation.get('operations')==OPERATIONS
    native=observation.get('nativeSnapshots',{})
    for prefix in ('controller','helper'):
        _require_pair(native.get(prefix+'Before'),native.get(prefix+'After'),binding,suite_root)
    assert native['controllerBefore']['officeCommandLine']==native['helperBefore']['officeCommandLine'], 'Helper resolved another private transport/profile'
    uno=observation.get('unoSnapshots',{})
    _require_uno(uno.get('before'),binding);_require_uno(uno.get('after'),binding)
    _reader_member(observation.get('readerProcess'),binding,suite_root,True)
    _require_launch(observation.get('helperLaunch'),observation['readerProcess']['jobHandleValue'])
    assert _path(observation['helperLaunch']['steps'][1]['application'])==_path(_join(suite_root,'Office/program/python.exe'))
    observed=observation.get('pythonIdentity',{}).get('observed',{})
    assert _path(observation['readerProcess']['image'])==_path(observed.get('processImage')), 'Actual reader process does not match the packaged Python observation'
    return observation


def require_reader_cleanup(cleanup,binding,deadline):
    """Replay final helper quiescence separately from every still-retained read."""
    assert isinstance(cleanup,dict) and cleanup.get('kind')=='owned-writer-reader-cleanup'
    assert cleanup.get('binding')==binding and cleanup.get('cleanupSucceeded') is True
    assert cleanup.get('deadline')==deadline and _finite(cleanup.get('startedAt'))<=_finite(cleanup.get('finishedAt'))<=_finite(deadline)
    assert cleanup.get('terminated') is False and cleanup.get('errors')==[] and cleanup.get('finalJobPids')==[]
    # Infer only a lexical root, never resolve a recorded Windows path on Linux.
    image=binding['expectedImage'];p=PureWindowsPath(image)
    root=str(p.parents[2]) if p.is_absolute() else str(PurePosixPath(image).parents[2])
    _require_pair(cleanup.get('nativeBefore'),cleanup.get('nativeAfter'),binding,root)
    members=cleanup.get('readerMembers')
    assert isinstance(members,list) and members and len(members)<=128
    assert len({r.get('pid') for r in members})==len(members)
    for member in members:_reader_member(member,binding,root,False)
    ack=cleanup.get('releaseAcknowledgement',{})
    assert ack.get('action')=='release' and ack.get('proxiesReleased') is True
    assert ack.get('readerPid') in {r['pid'] for r in members}
    job=_positive(cleanup.get('jobHandleValue'))
    launch_pid,launch_handle,_=_require_launch(cleanup.get('helperLaunch'),job)
    assert _path(cleanup['helperLaunch']['steps'][1]['application'])==_path(_join(root,'Office/program/python.exe'))
    assert launch_pid in {r['pid'] for r in members}
    assert all(r['jobHandleValue']==job for r in members)
    closures=cleanup.get('handleClosures')
    assert isinstance(closures,list) and all(r.get('result') is True for r in closures)
    expected={('job',job),('shell',cleanup['nativeAfter']['shell']['handleValue']),('office',cleanup['nativeAfter']['office']['handleValue'])}
    expected|={('member',r['handleValue']) for r in members}
    actual={(r.get('kind'),r.get('handleValue')) for r in closures}
    assert len(actual)==len(closures) and expected<=actual and [(r.get('handleValue')) for r in closures if r.get('kind')=='process']==[launch_handle], 'Missing actual owned HANDLE closure'
    return cleanup


class ReaderBackendError(AssertionError):
    def __init__(self,raw):
        self.raw=raw
        super().__init__('Owned Writer reader failed: '+str(raw.get('error')))


def _require_reply(raw,sequence,action):
    assert isinstance(raw,dict) and raw.get('sequence')==sequence and raw.get('action')==action, 'Foreign or stale reader reply'
    if raw.get('ok') is not True:raise ReaderBackendError(raw)
    return raw


def _safe_file(path,existing=True):
    path=Path(path)
    for parent in (path.parent,*path.parent.parents):
        metadata=parent.lstat()
        assert stat.S_ISDIR(metadata.st_mode) and not parent.is_symlink() and not (getattr(metadata,'st_file_attributes',0)&0x400), 'Reader transport directory is linked'
    if existing:
        metadata=path.lstat()
        assert stat.S_ISREG(metadata.st_mode) and not path.is_symlink() and not (getattr(metadata,'st_file_attributes',0)&0x400), 'Reader transport file is linked'
        assert metadata.st_size<=MAX_JSON_BYTES, 'Reader transport exceeded its finite byte limit'
    else:assert not path.exists() and not path.is_symlink(), 'Reader transport name was reused'


def _atomic_json(path,value):
    path=Path(path);_safe_file(path,False)
    data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
    assert len(data)<=MAX_JSON_BYTES, 'Reader transport exceeded its finite byte limit'
    temp=path.with_name(path.name+'.tmp');_safe_file(temp,False)
    with temp.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    assert not path.exists();os.replace(temp,path)


def _read_json(path):
    path=Path(path);_safe_file(path)
    with path.open('rb') as stream:data=stream.read(MAX_JSON_BYTES+1)
    assert len(data)<=MAX_JSON_BYTES
    _safe_file(path)
    return json.loads(data.decode('utf-8'))


def _worker_native():
    directory=Path(__file__).resolve().parents[1]/'worker'
    sys.path.insert(0,str(directory))
    try:
        spec=importlib.util.spec_from_file_location('_writer_reader_owned_native',directory/'native_windows.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    finally:sys.path.remove(str(directory))


def _clear_last_error():
    clear=getattr(ctypes,'set_last_error',None)
    if clear:clear(0)


def _last_error():
    get=getattr(ctypes,'get_last_error',None)
    return int(get()) if get else 0


def _launch_owned(native,argv,cwd):
    """Observe constructor APIs without changing the shared product implementation."""
    original_bind=native.bind;receipt={'steps':[],'firstFailure':None};active=True
    watched={'CreateJobObjectW','CreateProcessW','AssignProcessToJobObject','ResumeThread','CloseHandle'}
    def observed_bind(dll,name,args,result):
        function=original_bind(dll,name,args,result)
        if name not in watched:return function
        def observed(*values):
            _clear_last_error()
            value=function(*values);last_error=_last_error()
            if active:
                row={'api':name,'lastError':last_error}
                if name=='CreateJobObjectW':row['handleValue']=int(value or 0)
                elif name=='CreateProcessW':
                    info=values[-1]._obj
                    row.update(result=bool(value),creationFlags=int(values[5]),application=str(values[0]),command=values[1].value,inheritHandles=bool(values[4]),
                        pid=int(info.dwProcessId),threadId=int(info.dwThreadId),
                        processHandleValue=int(info.hProcess or 0),threadHandleValue=int(info.hThread or 0))
                elif name=='AssignProcessToJobObject':row.update(result=bool(value),jobHandleValue=int(values[0]),processHandleValue=int(values[1]))
                elif name=='ResumeThread':row.update(previousSuspendCount=int(value),threadHandleValue=int(values[0]))
                else:row.update(result=bool(value),handleValue=int(values[0]))
                receipt['steps'].append(row)
                failed=(value==0xffffffff) if name=='ResumeThread' else not bool(value)
                if failed and receipt['firstFailure'] is None:receipt['firstFailure']=dict(row)
            return value
        return observed
    native.bind=observed_bind
    try:return native.OwnedOfficeProcess(argv,cwd),receipt
    except BaseException as exc:exc.helper_launch=receipt;raise
    finally:active=False;native.bind=original_bind


class _NativeAnchor:
    """Read-only handles retained once; PID recycling cannot replace them."""
    def __init__(self,config):
        from startup_smoke import EngineProcessWitness
        from windows_smoke import Windows
        self.config=config;self.processes={};self.api=Windows();self.native=_worker_native();self.diagnostics=self.native.ProcessDiagnosticsApi()
        self.get_parent=self.native.bind(self.api.user,'GetParent',[W.HWND],W.HWND)
        try:
            expected_shell_creation=_positive(config['expected_shell_creation'])
            shell=EngineProcessWitness(config['shell_pid']);self.processes['shell']=shell
            identity=self.diagnostics.identity(shell.handle)
            shell_raw=dict(identity,pid=config['shell_pid'],handleValue=int(shell.handle),
                waitResult=int(self.diagnostics.wait_for(shell.handle,0)),exitCode=shell.code())
            self.last_snapshot={'shell':shell_raw}
            assert identity['creationTime']==shell.creation_time==expected_shell_creation, 'Original Popen shell generation changed before Office/UNO capture'
            assert _path(identity['image'])==_path(_join(config['suite'],'OpenGeul.Office.exe')) and shell_raw['waitResult']==258 and shell_raw['exitCode']==259
            self.processes['office']=EngineProcessWitness(config['office_pid'])
            first=self.snapshot()
            self.base=dict(shellPid=config['shell_pid'],shellCreationTime=first['shell']['creationTime'],
                officePid=config['office_pid'],officeCreationTime=first['office']['creationTime'],
                expectedImage=str(Path(config['suite'])/'Office/program/soffice.bin'),suiteHwnd=config['suite_hwnd'],
                parentHwnd=config['parent_hwnd'],childHwnd=config['child_hwnd'],rootHwnd=config['suite_hwnd'],privatePipe=first['privatePipe'])
            _require_native(first,self.base,str(config['suite']))
            if 'expected_native_binding' in config:
                assert self.base==config['expected_native_binding'], 'Helper opened a different native generation before UNO resolution'
                assert first['officeCommandLine']==config['expected_office_command_line'], 'Helper observed a changed private transport/profile before UNO resolution'
        except BaseException as exc:
            exc.native_snapshot=getattr(self,'last_snapshot',None)
            try:
                exc.native_handle_closures=self.close()
                if not all(row['result'] for row in exc.native_handle_closures):exc.add_note('Read-only native HANDLE CloseHandle returned false')
            except BaseException as cleanup_error:exc.add_note('Read-only native handle cleanup failed: '+str(cleanup_error))
            raise

    def snapshot(self):
        from native_accessibility import _command_line
        raw={};self.last_snapshot=raw
        for name,process in self.processes.items():
            identity=self.diagnostics.identity(process.handle)
            waited=int(self.diagnostics.wait_for(process.handle,0))
            if waited not in (0,258):raise ctypes.WinError(ctypes.get_last_error())
            raw[name]=dict(identity,pid=self.config[name+'_pid'],handleValue=int(process.handle),waitResult=waited,exitCode=process.code())
        windows={}
        for name in ('suite','parent','child'):
            hwnd=self.config[name+'_hwnd']
            windows[name]=dict(hwnd=hwnd,isWindow=bool(self.api.user.IsWindow(hwnd)),pid=self.api.pid(hwnd),
                parentHwnd=int(self.get_parent(hwnd) or 0),rootHwnd=int(self.api.user.GetAncestor(hwnd,2) or 0))
        windows.update(exportedParentHwnd=int(self.api.user.GetPropW(self.config['suite_hwnd'],'OpenGeul.Office.ParentHwnd') or 0),
            exportedChildHwnd=int(self.api.user.GetPropW(self.config['suite_hwnd'],'OpenGeul.Office.ChildHwnd') or 0))
        raw.update(windows=windows,officeCommandLine=_command_line(self.processes['office']))
        raw['privatePipe']=_pipe(raw['officeCommandLine']);raw['profileUrl']=_profile(raw['officeCommandLine'])
        if hasattr(self,'base'):_require_native(raw,self.base,str(self.config['suite']))
        return raw

    def close(self):
        result=[]
        for name,process in self.processes.items():
            if process.handle:
                handle=int(process.handle);ok=bool(process.close_handle(process.handle));process.handle=None
                result.append(dict(kind=name,handleValue=handle,result=ok))
        return result


def _native_anchor(config):return _NativeAnchor(config)


class _UnoReader:
    """Retain real original UNO objects and compare links around Text.getString."""
    def __init__(self,config,anchor):
        import uno
        local=uno.getComponentContext()
        resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
        self.context=resolver.resolve('uno:pipe,name='+anchor.base['privatePipe']+';urp;StarOffice.ComponentContext')
        self.desktop=self.context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',self.context)
        self.config=config;self.frame,self.controller,self.model=self._current()
        self.retained={k:repr(getattr(self,k)) for k in ('frame','controller','model')}
        self.snapshot()

    def _enumerate(self):
        frames=self.desktop.getFrames();count=frames.getCount()
        assert type(count) is int and 1<=count<=8, 'Original engine frame count exceeded bound'
        rows=[];matches=[]
        for index in range(count):
            frame=frames.getByIndex(index);peer=frame.getContainerWindow()
            hwnd=int(peer.getWindowHandle((),1)) if peer is not None else 0
            rows.append(dict(index=index,containerHwnd=hwnd))
            if hwnd==self.config['child_hwnd']:matches.append((index,frame))
        self.last_frames=rows
        assert len(matches)==1, 'Original frame is missing or ambiguous'
        return rows,matches[0]

    def _current(self):
        _,(_,frame)=self._enumerate();controller=frame.getController()
        assert controller is not None,'Original frame has no controller'
        model=controller.getModel();assert model is not None,'Original controller has no model'
        return frame,controller,model

    def snapshot(self):
        rows,(index,frame)=self._enumerate();controller=frame.getController();model=controller.getModel()
        raw=dict(frameCount=len(rows),frames=rows,matchedFrameIndex=index,retained=dict(self.retained),
            equalities=dict(frame=frame==self.frame,controller=controller==self.controller,model=model==self.model,
                controllerFrame=self.controller.getFrame()==self.frame,modelController=self.model.getCurrentController()==self.controller),
            documentUrl=self.model.getURL(),modelService='com.sun.star.text.TextDocument' if self.model.supportsService('com.sun.star.text.TextDocument') else '')
        expected=dict(childHwnd=self.config['child_hwnd'],documentUrl=self.config['expected_url'],
            **{k+'Identity':v for k,v in self.retained.items()})
        self.last_snapshot=raw
        _require_uno(raw,expected)
        return raw

    def read(self):
        before=self.snapshot();body=self.model.getText().getString();modified=self.model.isModified();after=self.snapshot()
        assert isinstance(body,str) and len(body.encode('utf-8'))<=MAX_BODY_BYTES, 'Writer body exceeded getter bound'
        assert type(modified) is bool
        return dict(bodyText=body,isModified=modified,unoSnapshots=dict(before=before,after=after))

    def release(self):
        # Drop client proxies only. Never call close/dispose on the live document.
        self.model=self.controller=self.frame=self.desktop=self.context=None


class OwnedWriterReader:
    def __init__(self,suite,output,*,shell_pid,expected_shell_creation,suite_hwnd,parent_hwnd,child_hwnd,office_pid,expected_url,clock=time.monotonic):
        self.config=dict(suite=str(suite),shell_pid=shell_pid,expected_shell_creation=expected_shell_creation,suite_hwnd=suite_hwnd,parent_hwnd=parent_hwnd,
            child_hwnd=child_hwnd,office_pid=office_pid,expected_url=expected_url)
        self.suite=Path(suite);self.output=Path(output);self.clock=clock;self.binding=None
        self.deadline=None;self.anchor=None;self.process=None;self.diagnostics=None;self.members={}
        self.sequence=0;self.closed=False;self.failed=False;self.last_observation=None;self.first_error=None;self.forced=False;self.auxiliary_errors=[];self.attempted_observation=None;self.helper_launch=None

    def _remaining(self,deadline):
        _finite(deadline)
        if self.deadline is None:self.deadline=deadline
        assert deadline==self.deadline,'Reader absolute deadline cannot be reset'
        remaining=deadline-self.clock()
        if remaining<=0:raise TimeoutError('Original Writer reader absolute deadline expired')
        return remaining

    def _member_snapshots(self):
        for pid in self.diagnostics.job_pids(self.process.job):
            assert pid not in (self.config['shell_pid'],self.config['office_pid']), 'Editor unexpectedly belongs to observation job'
            if pid not in self.members:
                handle=self.diagnostics.open_owned(pid,self.process.job)
                try:self.members[pid]=(handle,self.diagnostics.identity(handle))
                except BaseException:
                    try:
                        closed=bool(self.diagnostics.close_handle(handle))
                        self.auxiliary_errors.append(dict(stage='failed-member-identity-handle-close',handleValue=int(handle),result=closed))
                    except BaseException as later:self.auxiliary_errors.append(dict(stage='failed-member-identity-handle-close',handleValue=int(handle),type=type(later).__name__,message=str(later)))
                    raise
        rows=[]
        for pid,(handle,identity) in self.members.items():
            member=W.BOOL()
            succeeded=bool(self.diagnostics.is_in_job(handle,self.process.job,ctypes.byref(member)))
            if not succeeded:raise ctypes.WinError(ctypes.get_last_error())
            assert member.value,'Retained helper left its private job'
            state=self.diagnostics.state(handle)
            rows.append(dict(identity,pid=pid,handleValue=int(handle),waitResult=258 if state['alive'] else 0,
                exitCode=state['exitCode'],inOwnedJob=bool(member.value),isInJobApiSucceeded=succeeded,jobHandleValue=int(self.process.job)))
        return rows

    def _rpc(self,action,deadline):
        self._remaining(deadline)
        sequence=self.sequence;self.sequence+=1
        request=dict(sequence=sequence,action=action)
        _atomic_json(self.output/f'request-{sequence:03d}.json',request)
        path=self.output/f'reply-{sequence:03d}.json'
        while True:
            remaining=self._remaining(deadline)
            self._member_snapshots()
            if path.exists():return _require_reply(_read_json(path),sequence,action)
            if self.process.poll() is not None:raise AssertionError('Owned reader exited before its reply')
            time.sleep(min(.01,remaining))

    def start(self,deadline):
        self._remaining(deadline)
        assert not self.closed and not self.failed and self.process is None,'Reader cannot restart'
        try:
            self.output.mkdir(parents=True,exist_ok=False)
            self.anchor=_native_anchor(self.config)
            self._remaining(deadline)
            helper_config=dict(self.config,expected_native_binding=dict(self.anchor.base),expected_office_command_line=self.anchor.snapshot()['officeCommandLine'])
            _atomic_json(self.output/'configuration.json',helper_config)
            native=_worker_native();self.diagnostics=native.ProcessDiagnosticsApi()
            argv=[str(self.suite/'Office/program/python.exe'),str(Path(__file__).resolve()),'--helper',str(self.output)]
            self.process,self.helper_launch=_launch_owned(native,argv,self.suite/'Office/program')
            _require_launch(self.helper_launch,int(self.process.job))
            self._remaining(deadline)
            return self._read(deadline,'start')
        except BaseException as exc:
            self._record_failure(exc);raise

    def _record_failure(self,exc):
        self.failed=True
        if self.first_error is None:
            self.first_error=dict(type=type(exc).__name__,message=str(exc),winerror=getattr(exc,'winerror',None),traceback=traceback.format_exc(),
                attemptedObservation=self.attempted_observation,nativeSnapshot=getattr(self.anchor,'last_snapshot',getattr(exc,'native_snapshot',None)),
                nativeHandleClosures=getattr(exc,'native_handle_closures',None),helperLaunch=self.helper_launch or getattr(exc,'helper_launch',None))
            try:
                if self.output.exists():_atomic_json(self.output/'failure.json',self.first_error)
            except BaseException as later:self.auxiliary_errors.append(dict(stage='retain-primary-error',type=type(later).__name__,message=str(later)))
        if isinstance(exc,TimeoutError) and self.process is not None and not self.forced:
            try:self.process.terminate();self.forced=True
            except BaseException as later:self.auxiliary_errors.append(dict(stage='terminate-owned-helper-job',type=type(later).__name__,message=str(later)))

    def _read(self,deadline,action):
        started=self.clock();before=self.anchor.snapshot();reply=self._rpc(action,deadline)
        from writer_style_smoke import require_packaged_python
        result=reply['observation'];self.attempted_observation=result
        identity=require_packaged_python(self.suite,result['pythonIdentity']['observed'])
        assert identity==result['pythonIdentity'],'Helper Python identity changed between actual file checks'
        member=[r for r in self._member_snapshots() if r['pid']==reply.get('readerPid')]
        assert len(member)==1,'Actual reader PID was not retained in the private job'
        assert _path(member[0]['image'])==_path(identity['observed']['processImage'])
        result.update(readerProcess=member[0],readStartedAt=started,helperLaunch=self.helper_launch)
        result['nativeSnapshots'].update(controllerBefore=before,controllerAfter=self.anchor.snapshot())
        result['readFinishedAt']=self.clock()
        derived=dict(self.anchor.base,**{k+'Identity':v for k,v in result['unoSnapshots']['before']['retained'].items()},documentUrl=self.config['expected_url'])
        if self.binding is None:self.binding=derived
        assert derived==self.binding,'Original Writer binding changed'
        result.update(bindingBefore=dict(self.binding),bindingAfter=dict(self.binding))
        require_owned_observation(result,self.binding,str(self.suite));self._remaining(deadline)
        _atomic_json(self.output/f'observation-{self.sequence-1:03d}.json',result)
        self._remaining(deadline)
        self.last_observation=result
        return result

    def read(self,deadline):
        try:
            self._remaining(deadline)
            assert self.process is not None and not self.closed and not self.failed,'Reader context is not retained'
            assert self.sequence<=120, 'Reader exceeded its finite request count'
            return self._read(deadline,'read')
        except BaseException as exc:self._record_failure(exc);raise

    def close(self,deadline):
        assert deadline==self.deadline and not self.closed,'Reader cleanup must use original deadline once'
        cleanup=dict(kind='owned-writer-reader-cleanup',binding=self.binding,cleanupSucceeded=False,startedAt=self.clock(),deadline=deadline,
            terminated=self.forced,helperLaunch=self.helper_launch,releaseAcknowledgement=None,readerMembers=[],finalJobPids=None,jobHandleValue=int(self.process.job) if self.process else 0,
            nativeBefore=None,nativeAfter=None,handleClosures=[],errors=list(self.auxiliary_errors))
        def error(exc):cleanup['errors'].append(dict(type=type(exc).__name__,message=str(exc),winerror=getattr(exc,'winerror',None)))
        try:
            self._remaining(deadline)
            assert not self.forced, 'Reader job required forced cleanup'
            if self.anchor:cleanup['nativeBefore']=self.anchor.snapshot()
            if self.process:
                ack=self._rpc('release',deadline);cleanup['releaseAcknowledgement']=dict(action='release',readerPid=ack['readerPid'],proxiesReleased=ack['proxiesReleased'])
                while True:
                    remaining=self._remaining(deadline)
                    rows=self._member_snapshots();pids=self.diagnostics.job_pids(self.process.job)
                    if rows and not pids and all(r['waitResult']==0 for r in rows):
                        cleanup.update(readerMembers=rows,finalJobPids=pids);break
                    time.sleep(min(.01,remaining))
            if self.anchor:cleanup['nativeAfter']=self.anchor.snapshot()
        except BaseException as exc:
            error(exc)
            if self.process:
                try:
                    # Only this private helper job is terminated. Never the engine.
                    if not self.forced:self.process.terminate();self.forced=True
                    cleanup['terminated']=self.forced
                    cleanup['readerMembers']=self._member_snapshots();cleanup['finalJobPids']=self.diagnostics.job_pids(self.process.job)
                except BaseException as later:error(later)
        finally:
            for pid,(handle,identity) in self.members.items():
                try:cleanup['handleClosures'].append(dict(kind='member',handleValue=int(handle),result=bool(self.diagnostics.close_handle(handle))))
                except BaseException as exc:error(exc)
            self.members.clear()
            if self.process:
                original=self.process.close_handle
                process_handle=int(self.process.handle);job_handle=int(self.process.job)
                def close_recorded(handle):
                    result=original(handle);cleanup['handleClosures'].append(dict(kind='process' if int(handle)==process_handle else 'job',handleValue=int(handle),result=bool(result)));return result
                self.process.close_handle=close_recorded
                try:self.process.close()
                except BaseException as exc:error(exc)
            if self.anchor:
                try:cleanup['handleClosures']+=self.anchor.close()
                except BaseException as exc:error(exc)
            self.closed=True;cleanup['finishedAt']=self.clock()
            cleanup['cleanupSucceeded']=not cleanup['errors'] and not cleanup['terminated'] and cleanup['finishedAt']<=deadline
            if cleanup['cleanupSucceeded']:
                try:require_reader_cleanup(cleanup,self.binding,deadline)
                except BaseException as exc:error(exc);cleanup['cleanupSucceeded']=False
            if self.output.exists():
                try:_atomic_json(self.output/'cleanup.json',cleanup)
                except BaseException as exc:error(exc);cleanup['cleanupSucceeded']=False
        return cleanup


def _qpc():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    counter,frequency=ctypes.c_longlong(),ctypes.c_longlong()
    query=kernel.QueryPerformanceCounter;query.argtypes=[ctypes.POINTER(ctypes.c_longlong)];query.restype=W.BOOL
    freq=kernel.QueryPerformanceFrequency;freq.argtypes=[ctypes.POINTER(ctypes.c_longlong)];freq.restype=W.BOOL
    if not query(ctypes.byref(counter)) or not freq(ctypes.byref(frequency)):raise ctypes.WinError(ctypes.get_last_error())
    assert counter.value>=0 and frequency.value>0
    return int(counter.value),int(frequency.value)


def _helper(directory):
    directory=Path(directory);config=_read_json(directory/'configuration.json')
    anchor=reader=None;sequence=0;failed=False
    try:
        while sequence<123:
            path=directory/f'request-{sequence:03d}.json'
            if not path.exists():time.sleep(.005);continue
            request=_read_json(path);action=request.get('action')
            reply=dict(sequence=sequence,action=action,readerPid=os.getpid(),ok=False);observation=None
            try:
                assert request.get('sequence')==sequence and action in ('start','read','release')
                if action=='release':
                    if reader:reader.release();reader=None
                    closures=anchor.close() if anchor else []
                    assert all(c['result'] is True for c in closures), 'Helper native observer HANDLE cleanup failed'
                    anchor=None
                    reply.update(ok=True,proxiesReleased=True,observerHandleClosures=closures)
                else:
                    assert not failed,'Failed reader cannot resume'
                    if action=='start':
                        assert reader is None and sequence==0
                        anchor=_native_anchor(config);reader=_UnoReader(config,anchor)
                    else:assert reader is not None
                    from writer_style_smoke import observe_packaged_python,require_packaged_python
                    identity=require_packaged_python(Path(config['suite']),observe_packaged_python())
                    ticks,frequency=_qpc()
                    before=anchor.snapshot();observation=reader.read();after=anchor.snapshot()
                    finished_ticks,finished_frequency=_qpc();assert finished_frequency==frequency
                    observation['helperQpc']=dict(startedTicks=ticks,finishedTicks=finished_ticks,frequency=frequency)
                    observation.update(kind='existing-owned-writer-body',pythonIdentity=identity,nativeSnapshots=dict(helperBefore=before,helperAfter=after),
                        retainedProcessHandle=True,handleSignaled=False,readOnlyObservation=True,sameFrameControllerModelVerified=True,
                        readCallCleanupSucceeded=True,readerStillRetained=True,operations=list(OPERATIONS))
                    reply.update(ok=True,observation=observation)
            except BaseException as exc:
                failed=True;reply['error']=dict(type=type(exc).__name__,message=str(exc),winerror=getattr(exc,'winerror',None),traceback=traceback.format_exc(),
                    attemptedObservation=observation,nativeSnapshot=getattr(anchor,'last_snapshot',getattr(exc,'native_snapshot',None)),
                    unoSnapshot=getattr(reader,'last_snapshot',None),frameEnumeration=getattr(reader,'last_frames',None),nativeHandleClosures=getattr(exc,'native_handle_closures',None))
            _atomic_json(directory/f'reply-{sequence:03d}.json',reply);sequence+=1
            if action=='release':return 0 if reply['ok'] else 1
    finally:
        if reader:reader.release()
        if anchor:anchor.close()
    return 1


if __name__=='__main__':
    assert len(sys.argv)==3 and sys.argv[1]=='--helper'
    raise SystemExit(_helper(sys.argv[2]))
