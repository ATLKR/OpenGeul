"""One independently retained engine object; no input, process repair, or exit wait.

Imports are inert. The actual provider owns its DLL function objects and all
ctypes structures. Public/replay boundaries carry only JSON values.
"""
from __future__ import annotations
import copy
import ctypes as C
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time

from native_cleanup_receipt import load_cleanup_receipt, validate_cleanup_receipt

MAX_ARCHIVES = 256
MAX_SIDECARS = 256
MAX_ROOT_ENTRIES = 512
MAX_DESCRIPTORS = 8 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_SHUTDOWN = 256 * 1024
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_MEMBERS = 128
MAX_TREE_ENTRIES = 256
MAX_PROOF = 16 * 1024 * 1024
PROOF_SECONDS = 15
RUN_KEYS = {'sourceCommit','sourceRun','runAttempt','job','repository','architecture'}
NATIVE_KEYS = {'shellPid','officePid','suiteHwnd','parentHwnd','childHwnd','rootHwnd',
               'shellCreationTime','officeCreationTime','expectedImage'}


def _need(condition, message):
    if not condition: raise AssertionError(message)

def _int(value, low=0, high=0xffffffffffffffff):
    return type(value) is int and low <= value <= high

def _time(value):
    _need(type(value) in (int,float) and math.isfinite(value) and value >= 0, 'Invalid retirement time')
    return value

def _image(value):
    _need(isinstance(value,str) and value and '\0' not in value and ntpath.isabs(value), 'Invalid absolute native image')
    return ntpath.normcase(ntpath.normpath(value))

def _error(exc): return type(exc).__name__ + ': ' + str(exc)[:2048]

def _json(raw, cap):
    _need(type(raw) is bytes and 0 < len(raw) <= cap, 'Descriptor byte cap exceeded or empty')
    def pairs(items):
        row={}
        for k,v in items:
            _need(k not in row,'Duplicate descriptor JSON key');row[k]=v
        return row
    def constant(value): raise AssertionError('Nonfinite descriptor JSON')
    result=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant)
    _need(type(result) is dict,'Descriptor must be an object')
    return result

def _descriptor(raw):
    return dict(rawUtf8=raw.decode('utf-8'),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def _raw(row, cap):
    _need(type(row) is dict and set(row)=={'rawUtf8','bytes','sha256'},'Invalid raw descriptor schema')
    _need(isinstance(row['rawUtf8'],str) and _int(row['bytes'],1,cap),'Invalid raw descriptor length')
    raw=row['rawUtf8'].encode('utf-8')
    _need(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'Raw descriptor bytes/hash changed')
    return raw

def _native(row):
    _need(type(row) is dict and set(row)==NATIVE_KEYS,'Native binding schema changed')
    for key in NATIVE_KEYS-{'expectedImage'}:
        _need(_int(row[key],1,0xffffffff if key.endswith('Pid') else 0xffffffffffffffff),'Invalid native integer '+key)
    _need(row['rootHwnd']==row['suiteHwnd'] and row['officePid']!=row['shellPid'],'Invalid original native ownership')
    _need(_image(row['expectedImage']).endswith('\\office\\program\\soffice.bin'),'Packaged original engine path differs')
    _need(row['officeCreationTime']>=row['shellCreationTime'],'Original engine predates shell');return row

def _same_native(a,b):
    _native(a);_native(b)
    _need(all(a[k]==b[k] for k in NATIVE_KEYS-{'expectedImage'}) and _image(a['expectedImage'])==_image(b['expectedImage']),
          'Original native binding changed')

def _run(row):
    _need(type(row) is dict and set(row)==RUN_KEYS,'Actual run binding schema differs')
    _need(re.fullmatch('[0-9a-f]{40}',row['sourceCommit'] or '') and row['sourceCommit']!='0'*40,'Invalid consumer source')
    for key in ('sourceRun','runAttempt'):
        _need(type(row[key]) is str and re.fullmatch('[1-9][0-9]{0,19}',row[key]) and int(row[key])<=0xffffffffffffffff,'Invalid run identity')
    _need(row['job']=='windows-suite' and row['repository']=='ATLKR/OpenGeul' and row['architecture'] in ('x64','arm64'),'Wrong actual Suite run')
    return row

def _package(raw, run):
    p=_json(raw,MAX_MANIFEST)
    _need(type(p.get('schemaVersion')) is int and p['schemaVersion']==1 and p.get('productName')=='OpenGeul Office'
          and p.get('sourceCommit')==run['sourceCommit'] and p.get('architecture')==run['architecture']
          and isinstance(p.get('sourceArchiveSha256'),str) and re.fullmatch('[0-9a-f]{64}',p['sourceArchiveSha256']),
          'Packaged consumer identity differs')
    return p

def _open(row, n, old):
    _need(type(row) is dict and set(row)=={'handleValue','pid','access','inherit'},'Invalid extra handle schema')
    _need(_int(row['handleValue'],1) and row['handleValue']!=old and _int(row['pid'],1,0xffffffff)
          and row['pid']==n['officePid'] and type(row['access']) is int and row['access']==0x101000
          and type(row['inherit']) is bool and row['inherit'] is False,'Retirement handle admission differs')
    return row['handleValue']

def _last_error(row):
    _need(_int(row.get('lastError'),0,0xffffffff),'Invalid raw native lastError')

def _process_times(raw, creation):
    _need(type(raw) is dict and set(raw)=={'creation','exit','kernel','user'},'Raw process FILETIME groups differ')
    for words in raw.values():
        _need(type(words) is dict and set(words)=={'low','high'} and
              all(_int(v,0,0xffffffff) for v in words.values()),'Raw FILETIME words differ')
    words=raw['creation']
    _need((words['high']<<32)|words['low']==creation,'Raw creation FILETIME differs from original generation')

def _profile(row):
    from writer_model_reader import _profile_decoded_path, _profile_canonical_path
    _need(type(row) is dict and set(row)=={'profileUrl','canonicalPath','volumeSerialNumber','fileIndexHigh','fileIndexLow'},'Original profile projection differs')
    _profile_decoded_path(row['profileUrl']);canonical=_profile_canonical_path(row['canonicalPath'])
    _need(_image(canonical)==row['canonicalPath'],'Original canonical profile is not normalized')
    _need(all(_int(row[key],0,0xffffffff) for key in ('volumeSerialNumber','fileIndexHigh','fileIndexLow'))
          and (row['fileIndexHigh'] or row['fileIndexLow']),'Original profile native FileID differs')
    return row

def _outside_profile(root, profile):
    from writer_model_reader import _path
    _profile(profile);_image(root);value=_path(root);original=profile['canonicalPath'].rstrip('\\')
    _need(len(root)<=32767 and not value.startswith('\\\\') and value!=original
          and not value.startswith(original+'\\'),'Diagnostics root is inside original profile')

def _source_profile(record, native, setup_deadline, admission_started):
    from writer_model_reader import canonical_profile_projection, require_profile_directory_witness
    context=record['imeSemanticContext']
    _need(context.get('kind')=='ime-semantic-editing-context' and context.get('phase')=='post'
          and context.get('success') is True and context.get('module')==record['module']
          and context.get('expectedNative')==native and context.get('setupDeadline')==setup_deadline,
          'Original profile does not come from the qualified POST context')
    _same_native(context['expectedNative'],native)
    _need(_time(context['finishedAt'])<=admission_started<setup_deadline
          and _time(context['finishedAt'])<_time(context['readerDeadline'])<=setup_deadline,'Original profile context deadline differs')
    observation=context['observation'];binding=observation['bindingBefore']
    _need(all(binding.get(k)==v and type(binding.get(k)) is type(v) for k,v in native.items()),'Original profile context native binding differs')
    raw=observation['nativeSnapshots']['controllerBefore'];directory=raw['profileDirectory']
    require_profile_directory_witness(directory['witness'],raw['profileUrl'],directory['recheck'])
    return canonical_profile_projection(directory['witness'],raw['profileUrl'])

def _live(row, *, pid, handle, creation, image):
    _need(type(row) is dict,'Missing live process observation')
    for key in ('pid','handleValue','creationTime','waitResult'):
        _need(_int(row.get(key),1 if key!='waitResult' else 0),'Invalid live native integer '+key)
    _need((row['pid'],row['handleValue'],row['creationTime'],row['waitResult'])==(pid,handle,creation,258)
          and _image(row.get('image'))==_image(image),'Retained live generation changed')


def _plain(path):
    path=Path(path)
    for part in (path,*path.parents):
        info=part.lstat()
        _need(not stat.S_ISLNK(info.st_mode) and not (getattr(info,'st_file_attributes',0)&0x400),'Linked/reparse retirement evidence')
    return path

def _local(path):
    path=Path(path)
    _need(path.is_absolute() and '..' not in path.parts and not str(path).startswith(('\\\\','//')),'Local absolute evidence path required')
    return _plain(path).resolve()

def _read(path, cap, check, *, allow_empty=False):
    check();path=_plain(path);before=path.stat()
    _need(stat.S_ISREG(before.st_mode) and (0 if allow_empty else 1) <= before.st_size <= cap,'Descriptor size/type cap exceeded')
    with path.open('rb') as stream: raw=stream.read(cap+1)
    after=path.stat();check()
    _need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
          and len(raw)==before.st_size,'Descriptor changed during read')
    _need(len(raw)<=cap,'Read exceeded descriptor cap');return raw


def _manifest(raw):
    m=_json(raw,MAX_MANIFEST)
    _need(type(m.get('schemaVersion')) is int and m['schemaVersion']==1 and m.get('kind')=='owned-office-native-diagnostics'
          and m.get('archiveComplete') is True,'Incomplete/unknown native archive')
    _need(_int(m.get('launcherPid'),1,0xffffffff) and _int(m.get('workerPid'),1,0xffffffff),'Invalid archive launcher/worker')
    _image(m.get('ownedProfile'))
    rows=m.get('files');_need(type(rows) is list and 1<=len(rows)<=MAX_MEMBERS,'Archive member count exceeds bound')
    names=set()
    for r in rows:
        _need(type(r) is dict and set(r)=={'path','bytes','sha256'},'Archive member schema differs')
        name=r['path'];_need(type(name) is str and name and '\\' not in name and ':' not in name and '\0' not in name,'Unsafe archive member')
        p=PurePosixPath(name)
        _need(not p.is_absolute() and '..' not in p.parts and p.as_posix()==name and name!='manifest.json' and name not in names,'Unsafe/duplicate archive member')
        _need(p.suffix.lower() not in ('.dmp','.mdmp'),'Native crash dump found')
        names.add(name);_need(_int(r['bytes'],0,MAX_ARCHIVE) and re.fullmatch('[0-9a-f]{64}',r['sha256'] or ''),'Invalid archive member pin')
    _need('shutdown.json' in names,'Missing shutdown descriptor')
    return m

def _candidate(manifest_raw, shutdown_raw):
    m=_manifest(manifest_raw);s=load_cleanup_receipt(shutdown_raw)
    member,=[r for r in m['files'] if r['path']=='shutdown.json']
    _need(member['bytes']==len(shutdown_raw) and member['sha256']==hashlib.sha256(shutdown_raw).hexdigest(),'Shutdown differs from manifest')
    _need(type(s.get('schemaVersion')) is int and s['schemaVersion']==1 and s.get('kind')=='owned-office-job-cleanup','Unknown shutdown descriptor')
    _need(type(s.get('launcherPid')) is int and s['launcherPid']==m['launcherPid'] and _int(s.get('jobHandleValue'),1),'Shutdown owner differs')
    identities=[]
    for group in ('initialMembers','finalMembers'):
        rows=s.get(group);_need(type(rows) is list and 1<=len(rows)<=128,'Incomplete candidate member identities')
        engine=[];seen=set()
        for r in rows:
            _need(type(r) is dict and not any('error' in k.lower() for k in r),'Unknown candidate identity')
            for k in ('pid','creationTime','handleValue'):_need(_int(r.get(k),1,0xffffffff if k=='pid' else 0xffffffffffffffff),'Invalid candidate native integer')
            _need(r['pid'] not in seen,'Duplicate candidate PID');seen.add(r['pid'])
            _need(type(r.get('alive')) is bool and type(r.get('waitResult')) is int and r['waitResult']==(258 if r['alive'] else 0)
                  and r.get('getExitCodeProcessResult') is True and _int(r.get('exitCode'),0,0xffffffff),'Incomplete candidate process state')
            image=_image(r.get('image'))
            if image.endswith('\\program\\soffice.bin'):engine.append((r['pid'],r['creationTime'],image,r['handleValue']))
        _need(len(engine)==1,'Ambiguous candidate engine identity');identities.append(engine[0])
    _need(identities[0]==identities[1] and _image(s.get('expectedEngineImage'))==identities[0][2],'Candidate engine changed or incomplete')
    return m,s,identities[0][:3]


def _ownership_header(raw):
    """Bounded ownership routing; this never qualifies an incomplete archive."""
    m=_json(raw,MAX_MANIFEST)
    _need(type(m.get('schemaVersion')) is int and m['schemaVersion']==1
          and m.get('kind')=='owned-office-native-diagnostics'
          and type(m.get('archiveComplete')) is bool,'Unknown archive ownership header')
    _need(_int(m.get('launcherPid'),1,0xffffffff) and _int(m.get('workerPid'),1,0xffffffff),'Invalid archive ownership PID')
    profile=m.get('ownedProfile')
    _need(type(profile) is str and '\0' not in profile and len(profile)<=32767
          and re.fullmatch('[A-Za-z]:',ntpath.splitdrive(profile)[0])
          and ntpath.isabs(profile) and len(profile)>3 and ntpath.normpath(profile)==profile,
          'Archive profile must be an unaliased local absolute path')
    for part in profile[3:].split('\\'):
        _need(part and part[-1] not in '. ' and not any(c in '<>:"|?*~' or ord(c)<32 for c in part)
              and not re.fullmatch(r'(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])',
                                   part.split('.')[0].rstrip(' ').upper()),
              'Ambiguous Win32 archive profile component')
    _need(type(m.get('files')) is list and len(m['files'])<=MAX_MEMBERS,'Archive ownership member cap exceeded')
    return m,_image(profile)


def _unrelated_incomplete(manifest_raw, events_raw, admission):
    m,profile=_ownership_header(manifest_raw)
    _need(m['archiveComplete'] is False and m['files']==[]
          and profile!=admission['originalProfile']['canonicalPath'],
          'Incomplete original or ambiguous archive cannot be excluded')
    _need(type(events_raw) is bytes and 0<len(events_raw)<=MAX_SHUTDOWN,'Unrelated journal descriptor cap exceeded')
    lines=events_raw.splitlines();_need(lines,'Missing unrelated native observations')
    expected=_image(admission['native']['expectedImage']);launcher_image=expected[:-4]+'.exe'
    target=(admission['native']['officePid'],admission['native']['officeCreationTime'],expected)
    identity=launcher_identity=None
    for index,line in enumerate(lines):
        event=_json(line,MAX_SHUTDOWN)
        _need(type(event.get('phase')) is str and 1<=len(event['phase'])<=128
              and (index!=0 or event['phase']=='before-ui-bootstrap')
              and 'processQueryError' not in event,'Unknown unrelated journal observation')
        rows=event.get('processes');_need(type(rows) is list and 1<=len(rows)<=128,'Unrelated process observation cap exceeded')
        seen=set();engines=[];launchers=[]
        for row in rows:
            _need(type(row) is dict and not any('error' in key.lower() for key in row),'Unknown unrelated native identity')
            _need(_int(row.get('pid'),1,0xffffffff) and _int(row.get('creationTime'),1)
                  and row['pid'] not in seen,'Invalid/duplicate unrelated process identity');seen.add(row['pid'])
            _need(type(row.get('alive')) is bool and type(row.get('waitResult')) is int
                  and row['waitResult']==(258 if row['alive'] else 0)
                  and row.get('getExitCodeProcessResult') is True and _int(row.get('exitCode'),0,0xffffffff),
                  'Incomplete unrelated native process state')
            image=_image(row.get('image'));observed=(row['pid'],row['creationTime'],image)
            if image.endswith('\\program\\soffice.bin'):engines.append(observed)
            if row['pid']==m['launcherPid']:launchers.append(observed)
        _need(len(engines)==len(launchers)==1 and engines[0][2]==expected and launchers[0][2]==launcher_image,
              'Unrelated launcher/engine source join differs')
        if identity is None:identity,launcher_identity=engines[0],launchers[0]
        _need(engines[0]==identity and launchers[0]==launcher_identity and identity!=target,
              'Original or changed engine cannot be excluded by a profile label')
    return profile,identity


class _FileTime(C.Structure):
    _fields_=[('low',C.c_uint32),('high',C.c_uint32)]


class NativeRetirementProvider:
    """Own function objects/structure ABI; never accepts another module's struct."""
    def __init__(self, *, kernel=None, deadline=None, clock=time.monotonic):
        _need(C.sizeof(C.c_void_p)==8 and C.sizeof(_FileTime)==8 and _FileTime.high.offset==4,'Retirement Windows64 ABI differs')
        _need(kernel is not None or os.name=='nt','Actual Windows provider required')
        _need(deadline is not None or kernel is not None,'Actual provider requires original deadline')
        self.clock,self.deadline=clock,deadline
        self.kernel=kernel if kernel is not None else C.WinDLL('kernel32',use_last_error=True)
        H,D,B=C.c_void_p,C.c_uint32,C.c_int32
        for name,args,result in [('OpenProcess',(D,B,D),H),('GetProcessId',(H,),D),('WaitForSingleObject',(H,D),D),
            ('GetProcessTimes',(H,*(C.POINTER(_FileTime),)*4),B),('QueryFullProcessImageNameW',(H,D,C.c_wchar_p,C.POINTER(D)),B),
            ('GetExitCodeProcess',(H,C.POINTER(D)),B),('CloseHandle',(H,),B)]:
            function=getattr(self.kernel,name);function.argtypes,function.restype=args,result
    def set_deadline(self,deadline):
        _time(deadline);self.deadline=deadline
    def _budget(self):
        _need(self.deadline is not None and _time(self.clock())<self.deadline,'Retirement provider deadline expired')
    def _call(self,function,*args):
        self._budget();value=function(*args);self._budget();return value
    def open(self,pid):
        self._budget()
        # Hand ownership to the lease before its post-OpenProcess clock guard.
        handle=self.kernel.OpenProcess(0x101000,False,pid)
        _need(handle,'Retirement OpenProcess failed')
        return dict(handleValue=int(handle),pid=pid,access=0x101000,inherit=False)
    def _times(self,handle):
        times=[_FileTime() for _ in range(4)]
        ok=bool(self._call(self.kernel.GetProcessTimes,handle,*(C.byref(v) for v in times)))
        _need(ok,'Retirement GetProcessTimes failed')
        raw={name:dict(low=int(v.low),high=int(v.high)) for name,v in zip(('creation','exit','kernel','user'),times)}
        return raw,(int(times[0].high)<<32)|int(times[0].low)
    def live(self,handle):
        pid=int(self._call(self.kernel.GetProcessId,handle));wait=int(self._call(self.kernel.WaitForSingleObject,handle,0));raw,creation=self._times(handle)
        size=C.c_uint32(32768);image=C.create_unicode_buffer(size.value)
        _need(self._call(self.kernel.QueryFullProcessImageNameW,handle,0,image,C.byref(size)) and 0<size.value<32768,'Retirement live image query failed')
        return dict(pid=pid,handleValue=handle,waitResult=wait,creationTime=creation,image=str(Path(image.value).resolve()),processTimes=raw)
    def wait_zero(self,handle):
        self._budget()
        # Retain the one raw process observation even when the call returns late.
        # The lease checks its unchanged deadline immediately after retaining it.
        value=int(self.kernel.WaitForSingleObject(handle,0))
        return dict(api='WaitForSingleObject',handleValue=handle,timeoutMilliseconds=0,result=value,lastError=int(getattr(C,'get_last_error',lambda:0)()))
    def wait_cleanup(self,handle,milliseconds):
        # Mandatory teardown only; caller owns the existing shared exit deadline.
        _need(_int(milliseconds,0,5000),'Invalid cleanup wait')
        value=int(self.kernel.WaitForSingleObject(handle,milliseconds))
        return dict(api='WaitForSingleObject',handleValue=handle,timeoutMilliseconds=milliseconds,
                    result=value,lastError=int(getattr(C,'get_last_error',lambda:0)()))
    def exited(self,handle):
        pid=int(self._call(self.kernel.GetProcessId,handle));raw,creation=self._times(handle);code=C.c_uint32()
        ok=bool(self._call(self.kernel.GetExitCodeProcess,handle,C.byref(code)))
        return dict(pid=pid,handleValue=handle,creationTime=creation,processTimes=raw,getProcessIdResult=pid,
            getProcessTimesResult=True,getExitCodeProcessResult=ok,exitCode=int(code.value),lastError=int(getattr(C,'get_last_error',lambda:0)()))
    def close(self,handle):
        ok=bool(self.kernel.CloseHandle(handle))
        return dict(api='CloseHandle',handleValue=handle,result=ok,lastError=int(getattr(C,'get_last_error',lambda:0)()))


def require_ime_retirement_admission(proof, *, expected_native, expected_run, expected_case, expected_source, expected_original_profile,
                                     require_held=True):
    _need(type(proof) is dict and type(proof.get('schemaVersion')) is int and proof['schemaVersion']==1
          and proof.get('kind')=='owned-ime-engine-retirement','Retirement schema differs')
    _need(type(require_held) is bool,'Admission lifetime mode must be explicit Boolean')
    if require_held:
        _need(proof.get('success') is False and proof.get('cleanupErrors')==[]
              and not any(key in proof for key in ('close','proofPhase','error')),
              'Original retirement handle is no longer pending and held')
    a=proof.get('admission');_need(type(a) is dict,'Original retirement admission missing')
    _profile(expected_original_profile);_profile(a['originalProfile'])
    _need(a['originalProfile']==expected_original_profile,'Original profile differs from independent source context')
    _outside_profile(a['diagnosticsRoot'],expected_original_profile)
    _same_native(a['native'],expected_native);_run(a['runBinding']);_run(expected_run)
    _need(a['runBinding']==expected_run and a['runBinding']['sourceCommit']==expected_source,'Retirement source/run differs')
    _need(a['case']==expected_case and re.fullmatch('ime-(writer|calc|impress)',expected_case or ''),'Retirement case differs')
    _package(_raw(a['package'],MAX_MANIFEST),expected_run)
    n=a['native'];h=a['open']['handleValue'];old=a['keyboardEngine']['handleValue']
    _need(_int(old,1),'Original keyboard handle missing');_open(a['open'],n,old)
    for row in (a['keyboardEngine'],a['beforeEngine'],a['afterEngine']):
        _live(row,pid=n['officePid'],handle=old,creation=n['officeCreationTime'],image=n['expectedImage'])
    _live(a['extraEngine'],pid=n['officePid'],handle=h,creation=n['officeCreationTime'],image=n['expectedImage'])
    _process_times(a['extraEngine']['processTimes'],n['officeCreationTime'])
    suite_image=ntpath.join(ntpath.dirname(ntpath.dirname(ntpath.dirname(_image(n['expectedImage'])))),'OpenGeul.Office.exe')
    for row in (a['originalShell'],a['beforeShell'],a['afterShell']):
        _live(row,pid=n['shellPid'],handle=a['originalShell']['handleValue'],creation=n['shellCreationTime'],image=suite_image)
    _need(_int(a['editorTid'],1,0xffffffff) and _int(a['focusHwnd'],1),'Original editor thread/focus missing')
    start,finish,deadline=map(_time,(a['startedAt'],a['finishedAt'],a['setupDeadline']))
    _need(start<=finish<deadline and deadline<=start+60,'Admission exceeded original setup')
    return a


class _Lease:
    def __init__(self, keyboard, shell, suite, name, record, deadline, run, root, original_profile, clock, provider):
        self.keyboard,self.shell,self.suite,self.name,self.record=keyboard,shell,suite,name,record
        self.setup_deadline,self.run,self.root,self.clock=deadline,copy.deepcopy(run),root,clock
        self.original_profile=copy.deepcopy(original_profile)
        self.provider=provider if provider is not None else NativeRetirementProvider(deadline=deadline,clock=clock)
        self.handle=None;self.close_attempted=False;self.started=False;self.frozen=None;self.deadline=None
        self.proof=dict(schemaVersion=1,kind='owned-ime-engine-retirement',success=False,cleanupErrors=[])
        _need('imeEngineRetirement' not in record,'Retirement admission cannot repeat');record['imeEngineRetirement']=self.proof
    def check(self):
        now=_time(self.clock());limit=self.deadline if self.deadline is not None else self.setup_deadline
        _need(now<limit,'Retirement original deadline expired');return now
    def admit(self):
        try:
            start=self.check();k=self.keyboard;n=copy.deepcopy(k.binding);_native(n)
            _need(k.process is self.shell and k.record is self.record and self.record.get('imeKeyboardSession') is k.receipt,'Original keyboard/Popen object differs')
            _need(k.phase=='composition' and k.setup_deadline==self.setup_deadline and k.receipt.get('engineHandleReleased') is False,'Original keyboard handle no longer live')
            _need(self.shell.pid==n['shellPid'] and int(self.shell._handle)==k.shell['handleValue'] and self.shell.returncode is None,'Original Popen changed before admission')
            _need(self.name==getattr(self.shell,'opengeul_evidence_case',None)=='ime-'+self.record['module'],'Actual launch case differs')
            _need(Path(self.shell.opengeul_suite_root).resolve()==self.suite,'Original suite launch differs')
            _run(self.run);_need(self.run==self.record['readiness']['source'],'Run differs from original readiness')
            mapping={'sourceCommit':'GITHUB_SHA','sourceRun':'GITHUB_RUN_ID','runAttempt':'GITHUB_RUN_ATTEMPT','job':'GITHUB_JOB','repository':'GITHUB_REPOSITORY'}
            _need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_OS')=='Windows'
                  and all(self.run[k]==os.environ.get(v) for k,v in mapping.items()),'Actual hosted source/run environment differs')
            _need(self.run['architecture']==self.record['architecture'],'Actual architecture differs')
            self.suite=_local(self.suite);self.root=_local(self.root)
            _need(self.root==_local(os.environ.get('OPENGEUL_SUITE_DIAGNOSTICS','')),'Shared original diagnostic root differs')
            _need(self.root!=self.suite and self.suite not in self.root.parents,'Diagnostics escaped owned evidence')
            _profile(self.original_profile)
            _need(_source_profile(self.record,n,self.setup_deadline,start)==self.original_profile,'Original source profile argument differs')
            _outside_profile(str(self.root),self.original_profile)
            package=_read(self.suite/'suite-provenance.json',MAX_MANIFEST,self.check);_package(package,self.run)
            before=k.require_target();self.check()
            opened=self.provider.open(n['officePid']);self.handle=opened.get('handleValue')
            _need(_int(self.handle,1),'Retirement handle missing');self.check()
            extra=self.provider.live(self.handle);self.check();after=k.require_target();self.check()
            a=dict(native=n,runBinding=copy.deepcopy(self.run),case=self.name,package=_descriptor(package),open=opened,
                keyboardEngine=copy.deepcopy(k.engine),originalShell=copy.deepcopy(k.shell),beforeEngine=before['engine'],afterEngine=after['engine'],
                beforeShell=before['shell'],afterShell=after['shell'],extraEngine=extra,editorTid=k.tid,focusHwnd=k.focus,
                originalProfile=copy.deepcopy(self.original_profile),diagnosticsRoot=str(self.root),
                startedAt=start,finishedAt=self.check(),setupDeadline=self.setup_deadline)
            self.proof['admission']=copy.deepcopy(a)
            require_ime_retirement_admission(self.proof,expected_native=n,expected_run=self.run,expected_case=self.name,expected_source=self.run['sourceCommit'],expected_original_profile=self.original_profile)
            self.frozen=copy.deepcopy(a);return self
        except BaseException as exc:
            self.proof['error']=_error(exc);self.close(exc);raise
    def close(self, primary=None):
        if self.handle is None or self.close_attempted:return
        self.close_attempted=True;row=dict(attempts=1,handleValue=self.handle,result=False)
        self.proof['close']=row
        try:
            native=self.provider.close(self.handle);row.update(native)
            _need(type(native) is dict and native.get('api')=='CloseHandle' and native.get('handleValue')==self.handle
                  and native.get('result') is True,'Retirement CloseHandle failed')
            row['finishedAt']=_time(self.clock())
            if self.deadline is not None:_need(row['finishedAt']<self.deadline,'Retirement CloseHandle exceeded deadline')
        except BaseException as exc:
            self.proof['cleanupErrors'].append(_error(exc));self.proof['success']=False
            if primary is None:raise
    def cleanup_failed(self, primary, *, run=None):
        """Forced failure disposal, separate from successful retirement evidence."""
        row=dict(kind='owned-ime-failure-teardown',gracefulShutdownVerified=False,
                 engineExitConfirmed=False,handleReleased=False,targets=[])
        self.record['imeFailureCleanup']=row
        self.record['success']=False
        try:
            _need(primary is not None and not self.close_attempted and self.handle is not None,
                  'Failure teardown requires an original open lease and primary failure')
            _need(not getattr(self,'failure_cleanup_started',False),'Failure teardown cannot retry')
            self.failure_cleanup_started=True
            a=self.frozen
            _need(type(a) is dict and self.proof.get('admission')==a
                  and self.record.get('imeEngineRetirement') is self.proof,'Failure teardown admission changed')
            _need(self.keyboard.process is self.shell and self.keyboard.record is self.record,
                  'Failure teardown original objects changed')
            _same_native(self.keyboard.binding,a['native'])
            _need(self.shell.pid==a['originalShell']['pid'] and int(self.shell._handle)==a['originalShell']['handleValue']
                  and self.handle==a['open']['handleValue'],'Failure teardown original handles changed')
            started=_time(self.clock());deadline=started+15
            row.update(commandBudgetStartedAt=started,commandBudgetDeadline=deadline,commandBudgetSeconds=15)
            self.provider.set_deadline(deadline)
            def budget():
                left=deadline-_time(self.clock());_need(left>0,'Failure cleanup command deadline expired');return left
            def identity(actual,original):
                _need(type(actual) is dict and actual.get('waitResult') in (0,258)
                      and all(actual.get(k)==original[k] for k in ('pid','handleValue','creationTime'))
                      and _image(actual.get('image'))==_image(original['image']),
                      'Failure cleanup retained identity changed')
            budget();shell=self.provider.live(int(self.shell._handle));budget();identity(shell,a['originalShell'])
            engine=self.provider.live(self.handle);budget();identity(engine,a['extraEngine'])
            row.update(shellIdentity=shell,engineIdentity=engine)
            targets=[v['pid'] for v in (shell,engine) if v['waitResult']==258]
            _need(len(targets)==len(set(targets)),'Duplicate failure cleanup targets');row['targets']=targets
            if targets:
                command=['taskkill.exe']
                for pid in targets:command.extend(['/PID',str(pid)])
                command.extend(['/T','/F'])
                remaining=budget();row.update(forceRequested=True,commandTimeoutSeconds=remaining)
                (run or subprocess.run)(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=remaining)
                row['commandExitCode']=0;row['commandReturnedAt']=_time(self.clock());budget()
                exit_started=_time(self.clock());exit_deadline=exit_started+5
                row.update(exitWaitStartedAt=exit_started,exitWaitDeadline=exit_deadline,exitWaitBudgetSeconds=5)
                code=self.shell.poll()
                if code is None:
                    left=exit_deadline-_time(self.clock());_need(left>0,'Shared exit allowance exhausted')
                    code=self.shell.wait(timeout=left)
                row['shellExitCode']=code
                _need(type(code) is int and _time(self.clock())<=exit_deadline,'Shell exit exceeded shared allowance')
                milliseconds=max(0,min(5000,math.floor((exit_deadline-_time(self.clock()))*1000)))
            else:
                row.update(forceRequested=False,shellExitCode=self.shell.poll())
                exit_deadline=None;milliseconds=0
            wait=self.provider.wait_cleanup(self.handle,milliseconds);returned=_time(self.clock())
            row.update(engineWait=wait,engineWaitReturnedAt=returned)
            _need(type(wait) is dict and wait.get('api')=='WaitForSingleObject'
                  and wait.get('handleValue')==self.handle and wait.get('timeoutMilliseconds')==milliseconds
                  and type(wait.get('result')) is int and wait['result']==0
                  and (exit_deadline is None or returned<=exit_deadline),'Original engine exit unconfirmed')
            row['engineExitConfirmed']=True
        except BaseException as exc:
            row['error']=_error(exc)
            if isinstance(exc,subprocess.CalledProcessError):row['commandExitCode']=exc.returncode
            self.record.setdefault('cleanupError',_error(exc))
        finally:
            # Never replaces the original composition exception, including release failure.
            self.close(primary)
            row['handleReleased']=self.proof.get('close',{}).get('result') is True
            if not row['handleReleased']:
                row['releaseError']='Original engine handle release unconfirmed'
                self.record.setdefault('cleanupError',row['releaseError'])

    def _archives(self):
        self.check();entries=[]
        for p in self.root.iterdir():
            entries.append(p);_need(len(entries)<=MAX_ROOT_ENTRIES,'Shared root entry cap exceeded');self.check()
        archives=[];sidecars=[]
        for p in sorted(entries):
            _plain(p);info=p.stat();self.check()
            if re.fullmatch('[0-9a-f]{32}',p.name):
                _need(stat.S_ISDIR(info.st_mode),'UUID archive is not a directory');archives.append(p)
            else:
                match=re.fullmatch('worker-save-([1-9][0-9]*)-([0-9a-f]{32})\\.jsonl',p.name)
                _need(match and int(match[1])<=0xffffffff and stat.S_ISREG(info.st_mode) and 1<=info.st_size<=1048576,'Unexpected root sidecar/shape/size')
                sidecars.append(dict(name=p.name,bytes=info.st_size))
            _need(len(archives)<=MAX_ARCHIVES and len(sidecars)<=MAX_SIDECARS,'Shared root archive/sidecar cap exceeded')
        rows=[];unrelated=[];matches=[];total=0;n=self.frozen['native'];target=(n['officePid'],n['officeCreationTime'],_image(n['expectedImage']))
        for folder in archives:
            manifest=_read(folder/'manifest.json',min(MAX_MANIFEST,MAX_DESCRIPTORS-total),self.check);total+=len(manifest)
            header,profile=_ownership_header(manifest)
            if header['archiveComplete'] is False and profile!=self.frozen['originalProfile']['canonicalPath']:
                events=_read(folder/'events.jsonl',min(MAX_SHUTDOWN,MAX_DESCRIPTORS-total),self.check);total+=len(events)
                profile,identity=_unrelated_incomplete(manifest,events,self.frozen)
                unrelated.append(dict(uuid=folder.name,manifest=_descriptor(manifest),events=_descriptor(events),
                    profile=profile,engine=dict(pid=identity[0],creationTime=identity[1],image=identity[2])))
                continue
            shutdown=_read(folder/'shutdown.json',min(MAX_SHUTDOWN,MAX_DESCRIPTORS-total),self.check);total+=len(shutdown)
            m,s,identity=_candidate(manifest,shutdown)
            row=dict(uuid=folder.name,manifest=_descriptor(manifest),shutdown=_descriptor(shutdown),engine=dict(pid=identity[0],creationTime=identity[1],image=identity[2]))
            rows.append(row)
            if identity==target:
                _need(profile==self.frozen['originalProfile']['canonicalPath'],'Original archive profile differs')
                matches.append((folder,m,s,row))
        _need(len(matches)==1,'Exactly one original engine archive is required')
        folder,m,s,row=matches[0];validate_cleanup_receipt(s,expected_engine_image=n['expectedImage'],launcher_pid=m['launcherPid'])
        wanted={r['path']:r for r in m['files']};actual={};pending=[folder];count=0;content=0
        while pending:
            for p in pending.pop().iterdir():
                count+=1;_need(count<=MAX_TREE_ENTRIES,'Selected archive tree cap exceeded');_plain(p);info=p.stat();self.check()
                if stat.S_ISDIR(info.st_mode):pending.append(p);continue
                _need(stat.S_ISREG(info.st_mode),'Nonregular selected archive member')
                name=p.relative_to(folder).as_posix();_need(name in wanted or name in ('manifest.json','events.jsonl'),'Unlisted selected archive member')
                _need(len(actual)<MAX_MEMBERS,'Selected actual member count exceeds cap')
                content+=info.st_size;_need(content<=MAX_ARCHIVE,'Selected archive byte cap exceeded')
                raw=_read(p,min(MAX_ARCHIVE,info.st_size),self.check,allow_empty=True)
                _need(p.suffix.lower() not in ('.dmp','.mdmp') and not raw.startswith(b'MDMP'),'Native crash dump found')
                value=dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());actual[name]=value
                if name in wanted:_need(value==wanted[name],'Selected archive member hash/length differs')
                if name=='manifest.json':_need(raw==_raw(row['manifest'],MAX_MANIFEST),'Selected manifest changed')
        _need(set(wanted)|{'manifest.json'}<=set(actual)<=set(wanted)|{'manifest.json','events.jsonl'},'Selected archive member missing')
        self.proof['scan']=dict(rootEntries=sorted(p.name for p in entries),sidecars=sidecars,candidates=rows,
            unrelatedIncomplete=unrelated,descriptorBytes=total)
        self.proof['archive']=dict(uuid=folder.name,manifest=row['manifest'],shutdown=row['shutdown'],members=sorted(actual.values(),key=lambda v:v['path']),totalBytes=content)
    def verify_after_close_home(self, *, close_returned_at):
        _need(not self.started and not self.close_attempted,'Retirement proof cannot repeat or reopen');self.started=True
        primary=None
        try:
            started=_time(self.clock());self.deadline=started+PROOF_SECONDS
            if hasattr(self.provider,'set_deadline'):self.provider.set_deadline(self.deadline)
            phase=dict(startedAt=started,deadline=self.deadline,closeReturnedAt=close_returned_at);self.proof['proofPhase']=phase
            # FIRST PROCESS observation. Only clocks and in-memory bookkeeping precede it.
            phase['wait']=self.provider.wait_zero(self.handle);phase['waitFinishedAt']=_time(self.clock())
            wait=phase['wait'];_need(type(wait) is dict and wait.get('api')=='WaitForSingleObject' and wait.get('handleValue')==self.handle
                and type(wait.get('timeoutMilliseconds')) is int and wait['timeoutMilliseconds']==0 and type(wait.get('result')) is int
                and wait['result']==0,'Original engine first Wait0 was not signaled')
            self.check();_need(_time(close_returned_at)<=started,'Invalid post-close ordering')
            _need(self.record.get('imeEngineRetirement') is self.proof and self.proof.get('admission')==self.frozen,'Original admission object changed')
            _need(type(self.shell.returncode) is int and self.shell.returncode==0 and self.shell.pid==self.frozen['native']['shellPid']
                and int(self.shell._handle)==self.frozen['originalShell']['handleValue'],'Original Popen did not close normally')
            self.proof['shellExitCode']=self.shell.returncode
            self.proof['exit']=self.provider.exited(self.handle);self.check();_require_exit(self.proof['exit'],self.frozen)
            self._archives();self.check()
        except BaseException as exc:
            primary=exc;self.proof['error']=_error(exc);raise
        finally:
            try:self.close(primary)
            except BaseException as exc:
                self.proof['error']=_error(exc);raise
        self.check();self.proof['finishedAt']=_time(self.clock());self.proof['success']=True
        try:
            _need(len(json.dumps(self.proof,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())<=MAX_PROOF,'Retirement proof JSON cap exceeded')
            self.check()
            result=require_ime_engine_retirement(self.proof,expected_native=self.frozen['native'],expected_run=self.run,expected_case=self.name,expected_source=self.run['sourceCommit'],expected_original_profile=self.original_profile)
            self.proof['finishedAt']=self.check()
            return result
        except BaseException as exc:
            self.proof['success']=False;self.proof['error']=_error(exc);raise


def _require_exit(row,a):
    n=a['native'];h=a['open']['handleValue'];_last_error(row)
    _need(type(row) is dict and _int(row.get('pid'),1,0xffffffff) and _int(row.get('creationTime'),1)
          and _int(row.get('handleValue'),1) and (row['pid'],row['creationTime'],row['handleValue'])==(n['officePid'],n['officeCreationTime'],h),'Original retained exit generation differs')
    _need(type(row.get('getProcessIdResult')) is int and row['getProcessIdResult']==n['officePid'] and row.get('getProcessTimesResult') is True
          and row.get('getExitCodeProcessResult') is True and type(row.get('exitCode')) is int and row['exitCode']==0,'Original engine exit was not native zero')
    _process_times(row['processTimes'],n['officeCreationTime'])


def require_ime_engine_retirement(proof, *, expected_native, expected_run, expected_case, expected_source, expected_original_profile):
    a=require_ime_retirement_admission(proof,expected_native=expected_native,expected_run=expected_run,expected_case=expected_case,expected_source=expected_source,expected_original_profile=expected_original_profile,require_held=False)
    _need(proof.get('success') is True and 'error' not in proof and proof.get('cleanupErrors')==[]
          and type(proof.get('shellExitCode')) is int and proof['shellExitCode']==0,'Retirement did not complete naturally')
    p=proof['proofPhase'];start,end,deadline=map(_time,(p['startedAt'],proof['finishedAt'],p['deadline']))
    _need(a['finishedAt']<=_time(p['closeReturnedAt'])<=start<=_time(p['waitFinishedAt'])<=end<deadline and deadline==start+15,'Retirement timing/deadline differs')
    h=a['open']['handleValue'];wait=p['wait'];_last_error(wait);_need(type(wait) is dict and wait.get('api')=='WaitForSingleObject' and _int(wait.get('handleValue'),1)
        and wait['handleValue']==h and type(wait.get('result')) is int and wait['result']==0 and type(wait.get('timeoutMilliseconds')) is int and wait['timeoutMilliseconds']==0,'First retained process wait differs')
    _require_exit(proof['exit'],a)
    close=proof['close'];_last_error(close);_need(type(close.get('attempts')) is int and close['attempts']==1 and close.get('api')=='CloseHandle' and _int(close.get('handleValue'),1)
        and close['handleValue']==h and close.get('result') is True and start<=_time(close['finishedAt'])<=end,'Retirement handle release is missing or late')
    scan=proof['scan'];names=scan['rootEntries'];_need(type(names) is list and len(names)<=512 and names==sorted(set(names)),'Incomplete/unbounded root enumeration')
    candidates=scan['candidates'];sidecars=scan['sidecars'];unrelated=scan.get('unrelatedIncomplete',[])
    _need(type(candidates) is list and type(unrelated) is list and len(candidates)+len(unrelated)<=MAX_ARCHIVES
          and type(sidecars) is list and len(sidecars)<=MAX_SIDECARS,'Root descriptor count exceeds cap')
    classified=[]
    for side in sidecars:
        match=re.fullmatch('worker-save-([1-9][0-9]*)-[0-9a-f]{32}\\.jsonl',side['name'])
        _need(match and int(match[1])<=0xffffffff and _int(side['bytes'],1,1048576),'Unapproved save sidecar');classified.append(side['name'])
    total=0;matches=[];target=(a['native']['officePid'],a['native']['officeCreationTime'],_image(a['native']['expectedImage']))
    for row in candidates:
        _need(re.fullmatch('[0-9a-f]{32}',row['uuid'] or ''),'Invalid archive UUID');classified.append(row['uuid'])
        mr,sr=_raw(row['manifest'],MAX_MANIFEST),_raw(row['shutdown'],MAX_SHUTDOWN);total+=len(mr)+len(sr);_need(total<=MAX_DESCRIPTORS,'Descriptor aggregate cap exceeded')
        _,profile=_ownership_header(mr)
        m,s,identity=_candidate(mr,sr);projection=row['engine']
        _need(type(projection) is dict and set(projection)=={'pid','creationTime','image'} and _int(projection['pid'],1,0xffffffff)
              and _int(projection['creationTime'],1) and projection==dict(pid=identity[0],creationTime=identity[1],image=identity[2]),'Candidate engine projection changed')
        if identity==target:
            _need(profile==a['originalProfile']['canonicalPath'],'Original archive profile differs')
            matches.append((row,m,s))
    for row in unrelated:
        _need(type(row) is dict and set(row)=={'uuid','manifest','events','profile','engine'}
              and re.fullmatch('[0-9a-f]{32}',row['uuid'] or ''),'Invalid unrelated incomplete archive row')
        classified.append(row['uuid'])
        mr,er=_raw(row['manifest'],MAX_MANIFEST),_raw(row['events'],MAX_SHUTDOWN);total+=len(mr)+len(er)
        _need(total<=MAX_DESCRIPTORS,'Descriptor aggregate cap exceeded')
        profile,identity=_unrelated_incomplete(mr,er,a);projection=row['engine']
        _need(row['profile']==profile and type(projection) is dict and set(projection)=={'pid','creationTime','image'}
              and _int(projection['pid'],1,0xffffffff) and _int(projection['creationTime'],1)
              and projection==dict(pid=identity[0],creationTime=identity[1],image=identity[2]),
              'Unrelated archive ownership projection changed')
    _need(sorted(classified)==names and len(classified)==len(set(classified)) and type(scan['descriptorBytes']) is int and scan['descriptorBytes']==total,'Root scan incomplete or count forged')
    _need(len(matches)==1,'Exactly one original archive required');row,m,s=matches[0];archive=proof['archive']
    _need(archive['uuid']==row['uuid'] and archive['manifest']==row['manifest'] and archive['shutdown']==row['shutdown'],'Selected archive differs from exact candidate')
    validate_cleanup_receipt(s,expected_engine_image=a['native']['expectedImage'],launcher_pid=m['launcherPid'])
    members=archive['members'];_need(type(members) is list and len(members)<=MAX_MEMBERS,'Selected members unbounded')
    actual={}
    for v in members:
        _need(type(v) is dict and set(v)=={'path','bytes','sha256'} and v['path'] not in actual and _int(v['bytes'],0,MAX_ARCHIVE)
            and re.fullmatch('[0-9a-f]{64}',v['sha256'] or ''),'Invalid selected member observation');actual[v['path']]=v
    wanted={v['path']:v for v in m['files']};_need(set(wanted)|{'manifest.json'}<=set(actual)<=set(wanted)|{'manifest.json','events.jsonl'},'Selected members incomplete/unlisted')
    _need(all(actual[k]==v for k,v in wanted.items()),'Selected observed file pins differ')
    _need(actual['manifest.json']==dict(path='manifest.json',bytes=row['manifest']['bytes'],sha256=row['manifest']['sha256']),'Raw manifest identity differs')
    content=sum(v['bytes'] for v in members);_need(type(archive['totalBytes']) is int and content==archive['totalBytes'] and content<=MAX_ARCHIVE,'Selected byte total differs')
    _need(len(json.dumps(proof,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())<=MAX_PROOF,'Retirement proof JSON cap exceeded')
    return proof


def admit_ime_retirement(*, keyboard, original_shell, suite, case_name, record, setup_deadline,
                         run_binding, diagnostics_root, original_profile, clock=time.monotonic, provider=None):
    _time(setup_deadline)
    return _Lease(keyboard,original_shell,Path(suite),case_name,record,setup_deadline,run_binding,
                  Path(diagnostics_root),original_profile,clock,provider).admit()
