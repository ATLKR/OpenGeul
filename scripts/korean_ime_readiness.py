"""Fail-closed hosted Korean setup policy. Preparation never qualifies product input."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import datetime
import hashlib
import math
import stat
import time

CAPABILITY='Language.Basic~~~ko-KR~0.0.1.0'
SCOPE='current-user configured; target HWND/thread unverified'
GUID=r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}'

def need(condition,message):
    if not condition:raise ValueError(message)

def host_binding(env,expected_head,actual_head,*,platform):
    required={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
              'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_RUN_ATTEMPT':'1'}
    need(platform=='nt' and all(env.get(k)==v for k,v in required.items()),'Hosted Windows Source binding is required')
    need(isinstance(expected_head,str) and re.fullmatch('[0-9a-f]{40}',expected_head)
         and expected_head==actual_head==env.get('GITHUB_SHA'),'Actual checkout/Source SHA mismatch')
    need(re.fullmatch('[1-9][0-9]{0,19}',env.get('GITHUB_RUN_ID','')),'Invalid actual Source run')
    job=env.get('GITHUB_JOB');arch=env.get('E2E_ARCHITECTURE')
    need((job,arch) in (('native-e2e','x64'),('native-e2e-arm64','arm64')),'Actual native Source job/architecture is required')
    return {'sourceCommit':expected_head,'sourceRun':env['GITHUB_RUN_ID'],'runAttempt':'1',
            'repository':'ATLKR/OpenGeul','job':job,'architecture':arch}

def validate_record(row,binding):
    fields={'formatVersion','source','nativeMachine','controllerMachine','systemDirectory','capabilityName',
            'capabilityBefore','capabilityAfter','restartNeeded','userLanguageConfigured','defaultInputTip',
            'configuredInputTips','profile','profileScope','productInputVerified','sourceQualified'}
    need(isinstance(row,dict) and set(row)==fields and type(row['formatVersion']) is int
         and row['formatVersion']==1 and row['source']==binding,'Readiness record/source contract mismatch')
    expected_machine={'x64':0x8664,'arm64':0xAA64}.get(binding.get('architecture'))
    need(type(row['nativeMachine']) is int and row['nativeMachine']==expected_machine
         and type(row['controllerMachine']) is int
         and row['controllerMachine'] in ((0,0x8664) if expected_machine==0xAA64 else (0,)),
         'Actual OS native/controller architecture mismatch')
    need(row['capabilityName']==CAPABILITY and row['capabilityBefore'] in ('NotPresent','Installed')
         and row['capabilityAfter']=='Installed' and row['restartNeeded'] is False,'Korean capability is not actually ready without a restart')
    need(row['userLanguageConfigured'] is True and isinstance(row['configuredInputTips'],list)
         and 1<=len(row['configuredInputTips'])<=64,'Current-user Korean language/profile is missing')
    p=row['profile'];pfields={'inputTip','providerClsid','profileGuid','languageId','registered','registryView','component'}
    need(isinstance(p,dict) and set(p)==pfields,'Actual registered Korean profile is missing')
    tip=p['inputTip'];match=re.fullmatch('0412:('+GUID+')('+GUID+')',tip) if isinstance(tip,str) else None
    need(match is not None and match.group(1).upper()==str(p['providerClsid']).upper()
         and match.group(2).upper()==str(p['profileGuid']).upper() and p['languageId']==0x0412
         and p['registered'] is True and p['registryView']=='Registry64'
         and tip==row['defaultInputTip'] and tip in row['configuredInputTips'],'Input tip does not bind the actual native registered provider/profile')
    c=p['component'];cfields={'path','bytes','sha256','machine','signatureStatus','signerSubject'}
    need(isinstance(c,dict) and set(c)==cfields,'Actual Microsoft profile component is missing')
    directory=PureWindowsPath(row['systemDirectory']) if isinstance(row['systemDirectory'],str) else PureWindowsPath()
    path=PureWindowsPath(c['path']) if isinstance(c['path'],str) else PureWindowsPath()
    need(directory.is_absolute() and re.fullmatch('[A-Za-z]:',directory.drive) and path.is_absolute()
         and path.drive.lower()==directory.drive.lower() and '..' not in path.parts
         and path.is_relative_to(directory) and path.suffix.lower() in ('.dll','.ime'),'Profile component is outside the actual native system directory')
    need(type(c['bytes']) is int and 0<c['bytes']<=64*1024*1024 and re.fullmatch('[0-9a-f]{64}',c.get('sha256',''))
         and type(c['machine']) is int and c['machine']==expected_machine,'Profile component bytes/native PE identity mismatch')
    need(c['signatureStatus']=='Valid' and isinstance(c['signerSubject'],str)
         and re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)',c['signerSubject']),'Profile component is not genuinely Microsoft-signed')
    need(row['profileScope']==SCOPE and row['productInputVerified'] is False and row['sourceQualified'] is False,
         'Setup/controller observations cannot qualify actual target app input')
    return dict(row)


# Diagnostic projections never supply readiness, retry servicing, or retain raw
# Windows log text. The parent owns their separate five-second process budget.
DIAGNOSTIC_TAIL_BYTES=65536
DIAGNOSTIC_LINES=512
DIAGNOSTIC_RECORDS=64
DIAGNOSTIC_JSON_BYTES=32768
_STAMP=re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d{1,7})?),\s+(Info|Warning|Error)\s+(DISM|CBS)\b',re.I)
# Only explicit structured fields qualify. A slash, question mark, or equals
# sign before PID/session/HRESULT belongs to unknown text, including URLs.
# Retain invalid token values in the match so they cannot disappear and let a
# CBS record fall back to an otherwise joined session.
_FIELD_LEAD=r'(?<![^\s,\[(;])'
_FIELD_VALUE=r'([^\s,\];)]+)'
_BODY_PREFIX=re.compile(r'^(?:[A-Za-z][A-Za-z0-9 ._-]{0,80}:\s+)?(?:PID|Session)\s*[=:]',re.I)
_PID=re.compile(_FIELD_LEAD+r'PID\s*[=:]\s*'+_FIELD_VALUE,re.I)
_SESSION=re.compile(_FIELD_LEAD+r'Session\s*[=:]\s*'+_FIELD_VALUE,re.I)
_HRESULT=re.compile(_FIELD_LEAD+r'(?:HRESULT|hr)\s*[=:]\s*'+_FIELD_VALUE,re.I)
_FIELD_MARKERS={name:re.compile(_FIELD_LEAD+label+r'\s*[=:]',re.I) for name,label in
                [('pid','PID'),('session','Session'),('hresult','(?:HRESULT|hr)')]}

def diagnostic_budget(elapsed,attempted,worker_live):
    return 5000 if (type(elapsed) in (int,float) and math.isfinite(elapsed)
                   and 540<=elapsed<=570 and attempted is False and worker_live is True) else 0

def parse_diagnostic_tail(raw,kind,worker_pid,started,observed,*,sessions=()):
    need(kind in ('dism','cbs') and type(worker_pid) is int and 0<worker_pid<2**32,
         'diagnostic_binding_unavailable')
    need(type(raw) is bytes and type(started) in (int,float) and type(observed) in (int,float)
         and math.isfinite(started) and math.isfinite(observed) and started<=observed,
         'diagnostic_binding_unavailable')
    need(type(sessions) in (list,tuple) and len(sessions)<=DIAGNOSTIC_RECORDS
         and all(isinstance(s,str) and re.fullmatch(r'[0-9]{1,20}_[0-9]{1,20}',s) for s in sessions),
         'diagnostic_binding_unavailable')
    truncated=len(raw)>DIAGNOSTIC_TAIL_BYTES
    raw=raw[-DIAGNOSTIC_TAIL_BYTES:]
    # First rejection counts describe only these bounded host-tail lines, not
    # servicing activity attributable to the worker or a servicing root cause.
    gate_counts={'line_too_long':0,'format_unmatched':0,'timestamp_invalid':0,
        'outside_worker_window':0,'field_marker_mismatch':0,'pid_rejected':0,
        'session_rejected':0,'ownership_unjoined':0,'hresult_rejected':0,
        'no_event_fields':0,'record_retained':0,'record_limit_reached':0}
    result={'status':'correlation_unavailable','logKind':kind,'bytesRead':len(raw),
            'tailSha256':hashlib.sha256(raw).hexdigest(),'linesExamined':0,'records':[],
            'sessions':[],'gateCounts':gate_counts,'productInputVerified':False,'sourceQualified':False}
    try:
        if raw.startswith(b'\xff\xfe'):encoding='utf-16-le';bom=raw[:2]
        elif raw.startswith(b'\xfe\xff'):encoding='utf-16-be';bom=raw[:2]
        elif raw.startswith(b'\xef\xbb\xbf'):encoding='utf-8';bom=raw[:3]
        else:encoding='utf-8';bom=b''
        text=raw[len(bom):].decode(encoding)
    except UnicodeError:
        result['status']='encoding_unavailable';return result
    lines=[(line.rstrip('\r\n'),(bom if index==0 else b'')+line.encode(encoding))
           for index,line in enumerate(text.splitlines(keepends=True))]
    if truncated:lines=lines[1:]
    if not text.endswith(('\n','\r')):lines=lines[:-1]
    lines=lines[-DIAGNOSTIC_LINES:]
    result['linesExamined']=len(lines)
    joined=set(sessions)
    for line,line_bytes in lines:
        if len(line)>4096:
            gate_counts['line_too_long']+=1;continue
        stamp=_STAMP.match(line)
        if stamp is None or stamp[3].casefold()!=kind:
            gate_counts['format_unmatched']+=1;continue
        if _BODY_PREFIX.match(line[stamp.end():].lstrip()) is None:
            gate_counts['format_unmatched']+=1;continue
        try:epoch=datetime.datetime.fromisoformat(stamp[1].replace(',','.')).timestamp()
        except (ValueError,OverflowError,OSError):
            gate_counts['timestamp_invalid']+=1;continue
        if not started<=epoch<=observed:
            gate_counts['outside_worker_window']+=1;continue
        pids=_PID.findall(line)
        session_values=_SESSION.findall(line)
        hresult_values=_HRESULT.findall(line)
        # A dangling or malformed field must not disappear and turn a record
        # into an apparently clean PID/session attribution.
        fields={'pid':pids,'session':session_values,'hresult':hresult_values}
        if any(len(_FIELD_MARKERS[name].findall(line))!=len(values) for name,values in fields.items()):
            gate_counts['field_marker_mismatch']+=1;continue
        # Ambiguous or expressly foreign PID records can never inherit a CBS
        # session, even when that session was observed for our worker elsewhere.
        if pids and (len(pids)!=1 or re.fullmatch('[1-9][0-9]{0,9}',pids[0]) is None
                     or int(pids[0])!=worker_pid):
            gate_counts['pid_rejected']+=1;continue
        if session_values and (len(session_values)!=1 or re.fullmatch(r'[0-9]{1,20}_[0-9]{1,20}',session_values[0]) is None):
            gate_counts['session_rejected']+=1;continue
        session=session_values[0] if session_values else None
        bound_pid=bool(pids)
        if not bound_pid and not (kind=='cbs' and session is not None and session in joined):
            gate_counts['ownership_unjoined']+=1;continue
        if hresult_values and (len(hresult_values)!=1 or re.fullmatch('0x[0-9a-f]{8}',hresult_values[0],re.I) is None):
            gate_counts['hresult_rejected']+=1;continue
        hresult=hresult_values[0] if hresult_values else None
        if hresult is None and session is None:
            gate_counts['no_event_fields']+=1;continue
        if session is not None and bound_pid:joined.add(session)
        record={'timestamp':stamp[1],'timestampKind':'source-local-time',
                'eventCode':'hresult' if hresult is not None else 'session_join',
                'workerPid':worker_pid,'lineSha256':hashlib.sha256(line_bytes).hexdigest()}
        if session is not None:record['session']=session
        if hresult is not None:record['hresult']=hresult.lower()
        if len(result['records'])<DIAGNOSTIC_RECORDS:
            result['records'].append(record);gate_counts['record_retained']+=1
        else:
            gate_counts['record_limit_reached']+=1;result['status']='records_truncated';break
    result['sessions']=sorted(joined)[:DIAGNOSTIC_RECORDS]
    if result['records'] and result['status']!='records_truncated':result['status']='available'
    need(len(json.dumps(result,separators=(',',':')).encode())<=DIAGNOSTIC_JSON_BYTES,'diagnostic_size_unavailable')
    return result

def _no_reparse_components(path):
    for ancestor in (path,*path.parents):
        info=os.lstat(ancestor)
        need(not stat.S_ISLNK(info.st_mode) and not (getattr(info,'st_file_attributes',0)&0x400),
             'diagnostic_path_unavailable')

def _open_read_only_log(path):
    if os.name!='nt':return os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    # Do not follow a raced final reparse point. Verify the actual resolved
    # handle path as well, so a raced ancestor cannot redirect the observation.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel.CreateFileW;create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
        wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];create.restype=wintypes.HANDLE
    close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    final=kernel.GetFinalPathNameByHandleW;final.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD];final.restype=wintypes.DWORD
    handle=create(str(path),0x80000000,7,None,3,0x02000000,0)
    need(handle not in (None,ctypes.c_void_p(-1).value),'diagnostic_read_unavailable')
    try:
        buffer=ctypes.create_unicode_buffer(32768);count=final(handle,buffer,len(buffer),0)
        need(0<count<len(buffer),'diagnostic_path_unavailable')
        actual=buffer.value
        if actual.startswith('\\\\?\\'):actual=actual[4:]
        need(PureWindowsPath(actual)==PureWindowsPath(str(path)),'diagnostic_path_unavailable')
        fd=msvcrt.open_osfhandle(int(handle),os.O_RDONLY|os.O_BINARY)
        handle=None
        return fd
    finally:
        if handle is not None:close(handle)

def read_diagnostic_tail(path,*,limit=DIAGNOSTIC_TAIL_BYTES):
    need(type(limit) is int and 0<limit<=DIAGNOSTIC_TAIL_BYTES,'diagnostic_size_unavailable')
    path=Path(path).absolute();fd=None
    try:
        _no_reparse_components(path)
        before_path=os.stat(path,follow_symlinks=False)
        fd=_open_read_only_log(path);before=os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and (before.st_dev,before.st_ino)==(before_path.st_dev,before_path.st_ino),
             'diagnostic_path_unavailable')
        offset=max(0,before.st_size-limit);length=min(limit,before.st_size)
        os.lseek(fd,offset,os.SEEK_SET);raw=os.read(fd,length)
        os.lseek(fd,offset,os.SEEK_SET);again=os.read(fd,length)
        after=os.fstat(fd);after_path=os.stat(path,follow_symlinks=False)
        _no_reparse_components(path)
        need(len(raw)==length and raw==again and after.st_size>=before.st_size
             and (after.st_dev,after.st_ino)==(before.st_dev,before.st_ino)
             ==(after_path.st_dev,after_path.st_ino),'diagnostic_changed_unavailable')
        return {'raw':raw,'offset':offset,'observedLength':before.st_size,
                'tailSha256':hashlib.sha256(raw).hexdigest()}
    except (OSError,ValueError):raise ValueError('diagnostic_read_unavailable') from None
    finally:
        if fd is not None:os.close(fd)

def validate_diagnostic_context(host,observed,binding,pid,created,script_sha,worker):
    need(type(pid) is int and 0<pid<2**32 and type(created) is int and created>0
         and isinstance(script_sha,str) and re.fullmatch('[0-9a-f]{64}',script_sha),
         'diagnostic_binding_unavailable')
    for row in (host,observed):
        need(isinstance(row,dict) and row.get('source')==binding and type(row.get('workerPid')) is int and row.get('workerPid')==pid
             and row.get('scriptSha256')==script_sha,'diagnostic_binding_unavailable')
    need(host.get('productInputVerified') is False and host.get('sourceQualified') is False
         and observed.get('stage')=='install-entry' and type(observed.get('elapsedSeconds')) is int
         and observed['elapsedSeconds']>=0,'diagnostic_binding_unavailable')
    need(isinstance(worker,dict) and type(worker.get('pid')) is int and worker.get('pid')==pid
         and type(worker.get('createdFiletime')) is int and worker.get('createdFiletime')==created
         and worker.get('running') is True,'diagnostic_worker_unavailable')

def _windows_worker(pid):
    import ctypes
    from ctypes import wintypes
    need(os.name=='nt','diagnostic_platform_unavailable')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    opened=kernel.OpenProcess;opened.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];opened.restype=wintypes.HANDLE
    close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    times=kernel.GetProcessTimes;times.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];times.restype=wintypes.BOOL
    exit_code=kernel.GetExitCodeProcess;exit_code.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];exit_code.restype=wintypes.BOOL
    handle=opened(0x1000,False,pid)
    need(bool(handle),'diagnostic_worker_unavailable')
    try:
        values=[wintypes.FILETIME() for _ in range(4)];code=wintypes.DWORD()
        need(bool(times(handle,*[ctypes.byref(v) for v in values])) and bool(exit_code(handle,ctypes.byref(code))),
             'diagnostic_worker_unavailable')
        return {'pid':pid,'createdFiletime':(values[0].dwHighDateTime<<32)|values[0].dwLowDateTime,
                'running':code.value==259}
    finally:close(handle)

def _diagnostic_windows_root(system_directory):
    import ctypes
    from ctypes import wintypes
    need(os.name=='nt' and isinstance(system_directory,str),'diagnostic_platform_unavailable')
    directory=PureWindowsPath(system_directory)
    need(directory.is_absolute() and re.fullmatch('[A-Za-z]:',directory.drive)
         and '..' not in directory.parts and directory.name.casefold()=='system32',
         'diagnostic_path_unavailable')
    get=ctypes.WinDLL('kernel32',use_last_error=True).GetWindowsDirectoryW
    get.argtypes=[wintypes.LPWSTR,wintypes.UINT];get.restype=wintypes.UINT
    buffer=ctypes.create_unicode_buffer(32768);count=get(buffer,len(buffer))
    need(0<count<len(buffer) and PureWindowsPath(buffer.value)==directory.parent,
         'diagnostic_path_unavailable')
    root=Path(buffer.value);_no_reparse_components(root)
    return root

def _diagnostic_json(path):
    sample=read_diagnostic_tail(path,limit=DIAGNOSTIC_JSON_BYTES)
    need(sample['offset']==0,'diagnostic_size_unavailable')
    value=json.loads(sample['raw'])
    need(isinstance(value,dict),'diagnostic_binding_unavailable')
    return value

def collect_servicing_diagnostics(root,observation_root,binding,pid,created):
    need(os.name=='nt','diagnostic_platform_unavailable')
    observation_root=Path(observation_root).absolute()
    need(observation_root.is_relative_to(root),'diagnostic_path_unavailable')
    _no_reparse_components(observation_root)
    helper=root/'scripts/ensure-korean-ime.ps1'
    script_sha=hashlib.sha256(helper.read_bytes()).hexdigest()
    policy_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    host=_diagnostic_json(observation_root/'host-observation.json')
    observed=_diagnostic_json(observation_root/'servicing-observation.json')
    validate_diagnostic_context(host,observed,binding,pid,created,script_sha,_windows_worker(pid))
    windows=_diagnostic_windows_root(host.get('systemDirectory'))
    started=(created-116444736000000000)/10000000
    observed_time=time.time();sessions=[];logs=[]
    for kind,parts in [('dism',('Logs','DISM','dism.log')),('cbs',('Logs','CBS','CBS.log'))]:
        try:
            sample=read_diagnostic_tail(windows.joinpath(*parts))
            raw=sample['raw']
            # A tail cut in mid-line or UTF-16 codepoint cannot invent a record.
            if sample['offset']:
                newline=raw.find(b'\n')
                raw=raw[newline+1:] if newline>=0 else b''
            row=parse_diagnostic_tail(raw,kind,pid,started,observed_time,sessions=sessions)
            row['tailSha256']=sample['tailSha256'];row['offset']=sample['offset']
            row['bytesRead']=len(sample['raw']);row['observedLength']=sample['observedLength']
            if kind=='dism':sessions=row['sessions']
        except (OSError,ValueError):
            row={'logKind':kind,'status':'read_unavailable','records':[],
                 'productInputVerified':False,'sourceQualified':False}
        logs.append(row)
    validate_diagnostic_context(_diagnostic_json(observation_root/'host-observation.json'),
        _diagnostic_json(observation_root/'servicing-observation.json'),binding,pid,created,
        hashlib.sha256(helper.read_bytes()).hexdigest(),_windows_worker(pid))
    need(hashlib.sha256(helper.read_bytes()).hexdigest()==script_sha
         and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==policy_sha,'diagnostic_binding_unavailable')
    value={'formatVersion':1,'source':binding,'workerPid':pid,'workerCreatedFiletime':created,
           'scriptSha256':script_sha,'policySha256':policy_sha,'status':'diagnostic_only',
           'logs':logs,'productInputVerified':False,'sourceQualified':False}
    raw=json.dumps(value,separators=(',',':'),sort_keys=True).encode()
    need(len(raw)<=DIAGNOSTIC_JSON_BYTES,'diagnostic_size_unavailable')
    output=observation_root/'servicing-diagnostics.json'
    _no_reparse_components(observation_root)
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    except BaseException:
        # Retain partial owned output as failure evidence, never call it ready.
        raise

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--expected-source',required=True)
    parser.add_argument('--source-root',default='.');parser.add_argument('--guard',action='store_true')
    parser.add_argument('--record',type=Path)
    parser.add_argument('--collect-servicing-diagnostics',action='store_true')
    parser.add_argument('--observation-root',type=Path);parser.add_argument('--worker-pid',type=int)
    parser.add_argument('--worker-created-filetime',type=int);args=parser.parse_args()
    root=Path(args.source_root).resolve()
    actual=subprocess.run(['git','rev-parse','HEAD'],cwd=root,check=True,capture_output=True,text=True,timeout=10).stdout.strip()
    binding=host_binding(os.environ,args.expected_source,actual,platform=os.name)
    if args.collect_servicing_diagnostics:
        need(not args.guard and args.record is None and args.observation_root is not None,
             'diagnostic_binding_unavailable')
        collect_servicing_diagnostics(root,args.observation_root,binding,args.worker_pid,args.worker_created_filetime)
        return
    if args.guard:print(json.dumps(binding,separators=(',',':')));return
    need(args.record is not None,'Actual readiness record is required')
    record=args.record.resolve();need(record.is_relative_to(root) and record.stat().st_size<=32768,'Readiness record path/size is outside its bound')
    validate_record(json.loads(record.read_bytes()),binding)
    print('Actual Korean hosted setup validated; target HWND/thread input remains unqualified.')

if __name__=='__main__':
    if '--collect-servicing-diagnostics' in __import__('sys').argv:
        # The parent retains only finite status/exit code. No raw exceptions,
        # command lines, Windows log text or environment values leave this child.
        try:main()
        except BaseException:raise SystemExit(1) from None
    else:main()
