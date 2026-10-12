"""제품 MCP stdio와 소유한 별도 Windows 작업자의 실패 격리를 검증한다.

제품 test API를 추가하지 않는다. artifact에는 암호·환경·요청 원문 대신
응답 해시와 합성 문서에 대한 검증 결과만 기록한다.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'e2e'),str(ROOT/'scripts')]
from native_architecture import WindowsProbe, verify_executable, verify_host, verify_process
from windows_arch import require_architecture
MAX_FRAME=2*1024*1024
MALFORMED_PATHS=[None,[],[1],'a.hwpx']
FIXED_CLSID='c6c4d247-b4f0-563d-a649-4765796e3164'
GUID=re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')

def require(condition,message):
    if not condition:raise ValueError(message)

def strict_json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            require(key not in result,'JSON 키가 중복됩니다');result[key]=value
        return result
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('비정규 JSON 숫자입니다')))
    except (UnicodeError,json.JSONDecodeError) as error:raise ValueError('순수 UTF-8 JSON 프레임이 아닙니다') from error

class McpClient:
    """읽기·쓰기는 daemon thread로 제한하고 대기 중단 시 자신의 서버만 정리한다."""
    def __init__(self,command,*,cwd=None,timeout=30,max_frame=MAX_FRAME):
        require(isinstance(command,list) and command and all(isinstance(x,str) for x in command),'MCP 실행 인자가 올바르지 않습니다')
        require(0<timeout<=120 and type(max_frame) is int and 512<=max_frame<=MAX_FRAME,'MCP 통신 제한이 올바르지 않습니다')
        self.command=tuple(command);self.timeout=timeout;self.max_frame=max_frame
        self.pending=None;self.sequence=0;self.frames_received=0;self.frames_sent=0
        self.reads=queue.Queue(maxsize=16);self.writes=queue.Queue(maxsize=1);self.closed=False
        self.process=subprocess.Popen(command,cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.reader=threading.Thread(target=self._read,daemon=True);self.writer=threading.Thread(target=self._write,daemon=True)
        self.reader.start();self.writer.start()
    def _read(self):
        try:
            while not self.closed:
                raw=self.process.stdout.readline(self.max_frame+1)
                if not raw:self.reads.put(ValueError('MCP 응답 전에 EOF를 받았습니다'),timeout=self.timeout);return
                if len(raw)>self.max_frame or not raw.endswith(b'\n'):
                    self.reads.put(ValueError('MCP 응답 프레임 크기를 초과했습니다'),timeout=self.timeout);return
                self.reads.put(raw,timeout=self.timeout)
        except Exception:
            try:self.reads.put_nowait(ValueError('MCP 응답 스트림을 읽을 수 없습니다'))
            except queue.Full:pass
    def _write(self):
        while not self.closed:
            try:task=self.writes.get(timeout=.1)
            except queue.Empty:continue
            raw,done=task
            try:self.process.stdin.write(raw);self.process.stdin.flush();done.put(None)
            except Exception:done.put(ValueError('MCP 요청 스트림을 쓸 수 없습니다'))
    def _send(self,message):
        raw=(json.dumps(message,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        require(len(raw)<=self.max_frame,'MCP 요청 프레임 크기를 초과했습니다')
        done=queue.Queue(maxsize=1)
        try:self.writes.put((raw,done),timeout=self.timeout);failure=done.get(timeout=self.timeout)
        except queue.Empty:raise TimeoutError('MCP 요청 전송 제한 시간을 초과했습니다') from None
        if failure:raise failure
        self.frames_sent+=1
    def notify(self,method,params=None):
        require(self.pending is None,'대기 중인 MCP 요청을 바꾸지 않습니다')
        self._send({'jsonrpc':'2.0','method':method,'params':params or {}})
    def begin(self,method,params=None):
        require(not self.closed and self.pending is None,'대기 중인 MCP 요청을 바꾸지 않습니다')
        require(isinstance(method,str) and isinstance(params or {},dict),'MCP 요청 모양이 올바르지 않습니다')
        token=self.sequence+1
        self._send({'jsonrpc':'2.0','id':token,'method':method,'params':params or {}})
        self.sequence=token;self.pending=token;return token
    def finish(self,token):
        require(type(token) is int and token==self.pending,'대기 중인 MCP 요청 ID가 다릅니다')
        try:raw=self.reads.get(timeout=self.timeout)
        except queue.Empty:raise TimeoutError('MCP 응답 제한 시간을 초과했습니다') from None
        if isinstance(raw,Exception):raise raw
        response=strict_json(raw)
        require(isinstance(response,dict) and response.get('jsonrpc')=='2.0' and type(response.get('id')) is int
                and response['id']==token and ('result' in response)^('error' in response),'MCP 응답 ID 또는 모양이 다릅니다')
        self.pending=None;self.frames_received+=1;return response
    def request(self,method,params=None):return self.finish(self.begin(method,params))
    def close(self):
        if self.closed:return
        self.closed=True
        if self.process.poll() is None:
            self.process.kill();self.process.wait(timeout=10)
        for stream in (self.process.stdin,self.process.stdout):
            try:stream.close()
            except OSError:pass
        self.reader.join(timeout=.5);self.writer.join(timeout=.5)

def tool_records(response):
    result=response.get('result')
    require(isinstance(result,dict) and result.get('isError') is False,'MCP 도구가 성공한 결과를 반환하지 않았습니다')
    content=result.get('content')
    require(isinstance(content,list) and len(content)==1 and content[0].get('type')=='text'
            and isinstance(content[0].get('text'),str),'MCP 도구 JSON content가 올바르지 않습니다')
    text=content[0]['text']
    try:rows=[strict_json(text)]
    except ValueError:rows=[strict_json(line) for line in text.splitlines() if line.strip()]
    require(rows and all(isinstance(row,dict) for row in rows),'MCP 결과가 JSON 객체 또는 NDJSON이 아닙니다')
    if 'structuredContent' in result:require(len(rows)==1 and result['structuredContent']==rows[0],'MCP 구조화 결과와 text JSON이 다릅니다')
    return rows

def result_receipt(name,response,checks):
    raw=json.dumps(response,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    require(isinstance(checks,dict) and all(type(value) in (bool,int) for value in checks.values()),'검증 결과에는 공개 계수·판정만 허용합니다')
    return {'name':name,'responseSha256':hashlib.sha256(raw).hexdigest(),'responseBytes':len(raw),'requestId':response.get('id'),'checks':checks}

def qualify_worker(record,server,executable,expected_hash,architecture,*,context,package_full_name=None):
    """SCM parent PID 대신 고유 실행 경로·생성 시각·native 관측을 결합한다."""
    architecture=require_architecture(architecture);executable=Path(executable)
    require(context in ('portable','installed') and executable.is_absolute() and executable.is_file()
            and not executable.is_symlink(),'소유 작업자의 실제 실행 경로가 필요합니다')
    require(type(record.get('processId')) is int and record['processId']>0
            and record['processId']!=server['processId'],'MCP 서버를 작업자로 종료하지 않습니다')
    require(type(record.get('createdFileTime')) is int and type(server.get('createdFileTime')) is int
            and record['createdFileTime']>=server['createdFileTime']>0,'작업자 생성 시각이 시험 세션보다 이릅니다')
    require(isinstance(record.get('imagePath'),str) and Path(record['imagePath']).is_absolute()
            and Path(record['imagePath']).resolve()==executable.resolve()
            and re.fullmatch('[0-9a-f]{64}',expected_hash) and record.get('sha256')==expected_hash,
            '다른 실행 파일 또는 바이트의 작업자를 사용하지 않습니다')
    machine={'x64':0x8664,'arm64':0xAA64}[architecture]
    require(record.get('architecture')==architecture and record.get('native') is True
            and record.get('runningAtInspection') is True
            and all(type(record.get(key)) is int for key in ('peMachine','processMachine','nativeMachine'))
            and record['peMachine']==record['nativeMachine']==machine and record['processMachine']==0,
            '작업자가 기대한 native architecture로 실행되지 않습니다')
    for field,pattern in (('sourceCommit','[0-9a-f]{40}'),('sourceRun','[1-9][0-9]{0,19}'),('runAttempt','[1-9][0-9]{0,19}')):
        require(isinstance(server.get(field),str) and re.fullmatch(pattern,server[field])
                and record.get(field)==server[field],'작업자 실행의 source/run/attempt가 다릅니다')
    arguments=record.get('argv')
    require(isinstance(arguments,list) and len(arguments) in (4,5) and all(isinstance(x,str) for x in arguments)
            and Path(arguments[0]).resolve()==executable.resolve() and arguments[1:3]==['--opengeul-com-worker','--clsid']
            and GUID.fullmatch(arguments[3]) and (len(arguments)==4 or arguments[4]=='-Embedding'),
            '작업자 argv가 고정 COM bootstrap 계약과 다릅니다')
    clsid=arguments[3]
    if context=='portable':
        require(clsid!=FIXED_CLSID and record.get('packageFullName') is None,'private portable 작업자가 packaged COM 경로를 사용합니다')
    else:
        require(isinstance(package_full_name,str) and package_full_name and clsid==FIXED_CLSID
                and record.get('packageFullName')==package_full_name,'설치 작업자의 실제 package identity가 다릅니다')
    return {**{key:record[key] for key in ('processId','createdFileTime','imagePath','sha256','architecture',
              'peMachine','processMachine','nativeMachine','packageFullName','sourceCommit','sourceRun','runAttempt')},
            'classId':clsid,'native':True,'binding':'실제 경로·바이트·생성 시각·고정 bootstrap; SCM ancestry를 사용하지 않음'}

class WorkerWatch:
    def __init__(self,server,executable,expected_hash,architecture,*,context,package_full_name=None):
        self.server,self.executable,self.expected_hash=server,Path(executable),expected_hash
        self.architecture,self.context,self.package_full_name=architecture,context,package_full_name
        self.probe=WindowsProbe();api=self.probe.api
        api.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
        api.GetProcessTimes.restype=wintypes.BOOL
        api.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];api.TerminateProcess.restype=wintypes.BOOL
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];api.WaitForSingleObject.restype=wintypes.DWORD
    def created(self,handle):
        values=[wintypes.FILETIME() for _ in range(4)]
        require(self.probe.api.GetProcessTimes(handle,*[ctypes.byref(value) for value in values]),'실제 process 생성 시각을 확인할 수 없습니다')
        return (values[0].dwHighDateTime<<32)|values[0].dwLowDateTime
    def arguments(self,pid):
        # 이미지 경로가 이미 확인된 한 PID만 CIM에서 읽는다. raw stderr/command line을 출력하지 않는다.
        command=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' -ErrorAction Stop; $p.CommandLine | ConvertTo-Json -Compress"
        output=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command',command],stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,check=True).stdout
        require(len(output)<=64*1024,'작업자 command line 관측 크기를 초과했습니다')
        text=strict_json(output.decode('utf-8-sig'));require(isinstance(text,str),'작업자 bootstrap command line이 없습니다')
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.CommandLineToArgvW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype=ctypes.POINTER(wintypes.LPWSTR)
        self.probe.api.LocalFree.argtypes=[wintypes.HLOCAL];self.probe.api.LocalFree.restype=wintypes.HLOCAL
        count=ctypes.c_int();array=shell.CommandLineToArgvW(text,ctypes.byref(count))
        require(bool(array) and 0<count.value<=16,'작업자 bootstrap argv를 읽을 수 없습니다')
        try:return [array[index] for index in range(count.value)]
        finally:self.probe.api.LocalFree(ctypes.cast(array,wintypes.HLOCAL))
    def inspect(self,pid,handle=None):
        own=handle is None
        if own:handle=self.probe.api.OpenProcess(0x1000,False,pid)
        require(handle,'소유 후보 process handle을 열 수 없습니다')
        try:
            raw=self.probe.inspect(pid,handle)
            require(Path(raw['imagePath']).resolve()==self.executable.resolve(),'다른 이미지 경로의 process입니다')
            proof=verify_process(pid,self.executable,self.architecture,handle=handle,
                                 package_full_name=self.package_full_name,probe=self.probe)
            proof['createdFileTime']=self.created(handle);proof['argv']=self.arguments(pid)
            return qualify_worker(proof,self.server,self.executable,self.expected_hash,self.architecture,
                                  context=self.context,package_full_name=self.package_full_name)
        finally:
            if own:self.probe.api.CloseHandle(handle)
    def wait(self,client,timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            require(client.process.poll() is None,'MCP 서버가 작업자 관측 중 종료됐습니다')
            found=[]
            for row in self.probe.processes():
                if row['processId']==self.server['processId'] or row['executableName'].lower()!=self.executable.name.lower():continue
                try:found.append(self.inspect(row['processId']))
                except (ValueError,OSError,subprocess.SubprocessError):continue
            require(len(found)<=1,'소유 작업자의 PID가 여러 개여서 종료 대상을 고를 수 없습니다')
            if found:return found[0]
            if not client.reads.empty():raise ValueError('작업자가 관측되기 전에 MCP 도구가 끝났습니다')
            time.sleep(.1)
        raise TimeoutError('소유한 실제 작업자를 제한 시간 안에 관측하지 못했습니다')
    def terminate(self,record):
        require(self.context=='portable','설치된 공유 COM class의 process를 강제 종료하지 않습니다')
        handle=self.probe.api.OpenProcess(0x1000|0x100000|1,False,record['processId'])
        require(handle,'소유 작업자 종료 handle을 열 수 없습니다')
        try:
            current=self.inspect(record['processId'],handle)
            require(current==record,'작업자 PID 또는 실행 identity가 종료 전에 바뀌었습니다')
            require(self.probe.api.TerminateProcess(handle,57005),'소유 작업자 강제 종료에 실패했습니다')
            require(self.probe.api.WaitForSingleObject(handle,10000)==0,'소유 작업자 종료를 확인하지 못했습니다')
        finally:self.probe.api.CloseHandle(handle)

def direct_cli(command,*,cwd,stdin=None,expected_code=0):
    require(expected_code in (0,1,3),'허용하지 않은 CLI 판정 종료 코드입니다')
    result=subprocess.run(command,cwd=cwd,input=stdin if stdin is not None else b'',stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,timeout=60)
    require(result.returncode==expected_code and 0<len(result.stdout)<=MAX_FRAME,'CLI 종료 코드 또는 JSON 출력 크기가 다릅니다')
    text=result.stdout.decode('utf-8')
    try:rows=[strict_json(text)]
    except ValueError:rows=[strict_json(line) for line in text.splitlines() if line.strip()]
    require(rows and all(isinstance(row,dict) for row in rows),'CLI 결과가 순수 JSON/NDJSON이 아닙니다')
    return {'exitCode':result.returncode,'records':rows,'stdoutSha256':hashlib.sha256(result.stdout).hexdigest(),'stdoutBytes':len(result.stdout)}

def fault_recovery(client,watch,stress_path):
    """소유 worker만 종료하고 동일 MCP 서버의 다음 호출로 격리를 확인한다."""
    server_pid=client.process.pid
    token=client.begin('tools/call',{'name':'hwp_batch','arguments':{'subcommand':'info','paths':[str(stress_path)]*2048,'threads':1}})
    worker=watch.wait(client)
    require(type(worker.get('processId')) is int and worker['processId']>0 and worker['processId']!=server_pid,
            'MCP 서버 또는 불확실한 PID를 작업자로 종료하지 않습니다')
    watch.terminate(worker)
    response=client.finish(token)
    require(client.process.poll() is None and client.process.pid==server_pid,'작업자 실패가 MCP 서버를 종료했습니다')
    ping=client.request('ping');require(ping.get('result')=={},'작업자 실패 후 MCP ping이 정상 응답하지 않습니다')
    follow=client.request('tools/call',{'name':'hwp_info','arguments':{'path':str(stress_path)}})
    rows=tool_records(follow)
    require(len(rows)==1 and type(rows[0].get('pageCount')) is int and rows[0]['pageCount']>0,
            '작업자 실패 후 새 MCP 도구 호출이 정상 문서를 읽지 못했습니다')
    return {'serverProcessId':server_pid,'worker':worker,'sameServerAlive':True,'nextToolCallPassed':True,
            'forcedTermination':True,'faultResponse':result_receipt('owned-worker-forced-crash',response,{'returned':True}),
            'followupResponse':result_receipt('fault-followup-info',follow,{'pageCountPositive':True})}

NORMAL_TEXT='OpenGeul fixture 한글 가나다 & <xml> Ω 123'
WRITE_MARKER='OpenGeul MCP 쓰기 검증'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def document_text(record):
    pages=record.get('pages')
    require(isinstance(pages,list) and pages,'실제 문서 text pages가 없습니다')
    require(all(isinstance(page,dict) and isinstance(page.get('text'),str) for page in pages),'문서 text JSON 계약이 다릅니다')
    return '\n'.join(page['text'] for page in pages)

def stress_document(source,output):
    """원본은 보존하고 fault 관측 전용의 큰 합성 HWPX 복사본을 만든다."""
    import copy,xml.etree.ElementTree as ET,zipfile
    from prepare_payload import inventory
    require(not output.exists(),'기존 stress fixture를 덮어쓰지 않습니다')
    with zipfile.ZipFile(source) as original:
        entries=inventory(original);require('Contents/section0.xml' in entries,'합성 문서 section0이 없습니다')
        section=ET.fromstring(original.read(entries['Contents/section0.xml']))
        paragraphs=[node for node in section if node.tag.rsplit('}',1)[-1]=='p']
        require(paragraphs,'합성 문서의 기본 문단이 없습니다')
        for index in range(1500):
            paragraph=copy.deepcopy(paragraphs[0]);paragraph.set('id',str(100000+index));section.append(paragraph)
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,entry in entries.items():
                archive.writestr(name,ET.tostring(section,encoding='utf-8',xml_declaration=True) if name=='Contents/section0.xml' else original.read(entry),compress_type=entry.compress_type)
    from hwpx_oracle import inspect_hwpx
    proof=inspect_hwpx(output);require(proof['text'].count('OpenGeul fixture')>=1500,'stress 합성 문서의 독립 XML 검증에 실패했습니다')
    return {'sha256':sha(output),'bytes':output.stat().st_size,'addedSyntheticParagraphs':1500,'scope':'원본·인쇄 기준과 별개의 작업자 강제 종료용 합성 복사본'}

def password_inputs(folder):
    require(folder.is_dir() and not folder.is_symlink(),'원본 암호 fixture 디렉터리가 필요합니다')
    manifest_path=folder/'manifest.json';require(manifest_path.is_file() and manifest_path.stat().st_size<=64*1024,'bounded 암호 fixture manifest가 필요합니다')
    manifest=strict_json(manifest_path.read_bytes())
    require(manifest.get('engine',{}).get('qualification')=='final-source-bound' and manifest.get('independentVerification',{}).get('passed') is True,
            '소스가 묶인 독립 검증 암호 fixture가 필요합니다')
    provenance=manifest['engine']['provenance'];lock=strict_json((ROOT/'config/upstream.lock.json').read_bytes())
    require(provenance.get('upstream')==lock and provenance.get('namespaceHelper')==sha(ROOT/'overlay/hwpx_namespaces.rs')
            and provenance.get('namespacePatcher')==sha(ROOT/'scripts/patch_namespaces.py'),'암호 fixture engine의 현재 소스 출처가 다릅니다')
    require(manifest['engine']['wasmSha256']==provenance['artifacts']['rhwp_bg.wasm']
            and manifest['engine']['jsSha256']==provenance['artifacts']['rhwp.js'],'암호 fixture WASM/JS 출처가 다릅니다')
    require(manifest['generation']['generatorSha256']==sha(ROOT/'e2e/password/generate-password-fixtures.mjs')
            and manifest['generation']['verifierSha256']==sha(ROOT/'e2e/password/verify-password-fixtures.py'),'암호 fixture 생성기·독립 검증기가 다릅니다')
    password=manifest.get('password');require(isinstance(password,str) and 0<len(password)<=4096 and '\r' not in password and '\n' not in password,
                                           '암호 stdin fixture 계약이 다릅니다')
    fixtures=[];formats=set()
    for entry in manifest['fixtures']:
        name=entry['path'];require(isinstance(name,str) and Path(name).name==name and '/' not in name and '\\' not in name,'암호 fixture는 basename이어야 합니다')
        path=folder/name
        require(entry['format'] in ('hwp','hwpx') and entry['format'] not in formats and path.is_file() and not path.is_symlink()
                and path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256'],'암호 fixture의 원본 바이트가 다릅니다')
        require(all(entry.get(key) is True for key in ('normalOpenRejected','wrongPasswordRejected','correctPasswordTextVerified')),
                '암호 fixture normal/wrong/correct 독립 제어가 빠졌습니다')
        formats.add(entry['format']);fixtures.append((entry['format'],path,entry['sha256']))
    require(formats=={'hwp','hwpx'},'두 암호 형식 fixture가 필요합니다')
    return manifest,fixtures,password

def run_cases(client,executable,work,fixtures,*,password_folder,watch,context,progress=None):
    """공개 원본 도구 이름/인자만 사용한다; 모든 쓰기는 소유 합성 복사본이다."""
    progress={} if progress is None else progress
    records=progress.setdefault('cases',[])
    def remember(name,response,checks):
        records.append(result_receipt(name,response,checks));progress['caseCount']=len(records);progress['lastCompletedCase']=name
    def tool(name,arguments):
        progress['phase']=name
        return client.request('tools/call',{'name':name,'arguments':arguments})
    initialized=client.request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'OpenGeul qualification','version':'1'}})
    info=initialized.get('result',{});lock=strict_json((ROOT/'config/upstream.lock.json').read_bytes())
    require(info.get('protocolVersion')=='2025-06-18' and info.get('serverInfo',{}).get('name')=='rhwp'
            and info['serverInfo'].get('version')==lock['rhwp']['version'],'실제 rhwp MCP 초기화 계약이 다릅니다')
    remember('initialize',initialized,{'protocolPassed':True});client.notify('notifications/initialized')
    ping=client.request('ping');require(ping.get('result')=={},'실제 MCP ping이 다릅니다');remember('ping',ping,{'passed':True})
    listed=client.request('tools/list');tools=listed.get('result',{}).get('tools')
    require(isinstance(tools,list) and len(tools)<=2000,'MCP 도구 목록 크기가 다릅니다')
    names=[tool.get('name') for tool in tools]
    required={'hwp_info','hwp_export_text','hwp_replace_text','hwp_batch','hwp_ir_diff'}
    require(all(isinstance(name,str) for name in names) and len(set(names))==len(names) and required<=set(names),'원본 MCP 도구 정의가 누락·중복되었습니다')
    remember('tools-list',listed,{'toolsListed':len(names),'requiredToolsPresent':True})
    source=work/'normal.hwpx';shutil.copyfile(fixtures/'basic.hwpx',source);before=sha(source)
    read=tool('hwp_export_text',{'path':str(source)});require(NORMAL_TEXT in document_text(tool_records(read)[0]),'MCP 문서 읽기가 원본 합성 text와 다릅니다')
    remember('normal-read',read,{'sourceTextMatched':True})
    output=work/'edited.hwpx';changed=tool('hwp_replace_text',{'path':str(source),'find':'OpenGeul fixture','replace':WRITE_MARKER,'output':str(output)})
    data=tool_records(changed)[0];require(type(data.get('replacedCount')) is int and data['replacedCount']>0 and output.is_file(),'MCP 문서 쓰기가 산출물을 만들지 못했습니다')
    from hwpx_oracle import inspect_hwpx
    require(WRITE_MARKER in inspect_hwpx(output)['text'] and sha(source)==before,'MCP 출력의 독립 XML 또는 원본 보존 검증에 실패했습니다')
    remember('normal-write',changed,{'independentXmlPassed':True,'sourceUnchanged':True,'replacedCount':data['replacedCount']})
    difference=tool('hwp_ir_diff',{'a':str(source),'b':str(output)});diff=tool_records(difference)[0]
    require(diff.get('identical') is False and type(diff.get('diffCount')) is int and diff['diffCount']>0,'MCP IR 차이 판정이 사라졌습니다')
    direct=direct_cli([str(executable),'ir-diff',str(source),str(output),'--json'],cwd=work,expected_code=3)
    require(direct['records'][0]==diff,'MCP가 실제 CLI exit3 JSON을 바꿨습니다')
    remember('ir-diff-code3',difference,{'cliExitCode':3,'sameJson':True})
    missing=work/'missing.hwpx';paths=[str(source),str(missing)]
    partial=tool('hwp_batch',{'subcommand':'info','paths':paths,'threads':1});batch=tool_records(partial)
    direct=direct_cli([str(executable),'batch','info','--json','--threads','1'],cwd=work,stdin=('\n'.join(paths)+'\n').encode('utf-8'),expected_code=1)
    require(len(batch)==2 and sum('error' in row for row in batch)==1 and batch==direct['records'],'MCP가 batch 부분 실패의 NDJSON을 잃었습니다')
    remember('batch-partial-code1',partial,{'cliExitCode':1,'records':2,'sameNdjson':True})
    for index,value in enumerate(MALFORMED_PATHS):
        bad=tool('hwp_batch',{'subcommand':'info','paths':value})
        require(bad.get('result',{}).get('isError') is True,'malformed paths가 worker 실행 전 오류로 거부되지 않았습니다')
        require(client.request('ping').get('result')=={},'malformed paths 이후 MCP stdin이 교착됐습니다')
        remember('malformed-paths-'+str(index),bad,{'rejected':True,'serverResponsive':True})
    manifest,encrypted,password=password_inputs(password_folder)
    for format,path,expected_hash in encrypted:
        for label,secret in (('missing',None),('wrong','OpenGeul-wrong-123456'),('correct',password)):
            arguments={'path':str(path)}
            if secret is not None:arguments['password']=secret
            response=tool('hwp_export_text',arguments)
            if label=='correct':require(manifest['expectedText'] in document_text(tool_records(response)[0]),'MCP 암호 문서의 실제 text가 다릅니다')
            else:require(response.get('result',{}).get('isError') is True,'틀리거나 누락된 암호가 성공으로 처리됐습니다')
            require(sha(path)==expected_hash,'MCP가 원본 ciphertext를 변경했습니다')
            remember('password-'+format+'-'+label,response,{'expectedResultPassed':True,'ciphertextUnchanged':True})
    stress=work/'stress.hwpx';stress_proof=stress_document(source,stress)
    if context=='portable':fault=fault_recovery(client,watch,stress)
    else:
        token=client.begin('tools/call',{'name':'hwp_batch','arguments':{'subcommand':'info','paths':[str(stress)]*64,'threads':1}})
        worker=watch.wait(client);response=client.finish(token);require(len(tool_records(response))==64,'설치 MCP worker의 batch 결과가 다릅니다')
        fault={'worker':worker,'sameServerAlive':client.process.poll() is None,'forcedTermination':False,
               'scope':'설치 fixed COM class의 native/package identity 관측; 공유 process 강제 종료 없음'}
    require(sha(source)==before,'MCP suite가 원본 합성 입력을 변경했습니다')
    return {'cases':records,'caseCount':len(records),'stressFixture':stress_proof,'workerIsolation':fault,
            'framesSent':client.frames_sent,'framesReceived':client.frames_received,'passed':True}

def current_binding():
    require(os.name=='nt' and os.getenv('GITHUB_ACTIONS')=='true' and os.getenv('RUNNER_ENVIRONMENT')=='github-hosted'
            and os.getenv('GITHUB_REPOSITORY')=='ATLKR/OpenGeul','실제 공개 저장소 Windows hosted CI에서만 제품 MCP를 검사합니다')
    result={key:os.getenv(name) for key,name in (('sourceCommit','GITHUB_SHA'),('sourceRun','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT'))}
    require(re.fullmatch('[0-9a-f]{40}',result['sourceCommit'] or '') and all(re.fullmatch('[1-9][0-9]{0,19}',result[key] or '') for key in ('sourceRun','runAttempt')),
            '실제 source/run/attempt 바인딩이 없습니다')
    return result

def private_runtime(executable,output):
    require(executable.name.lower()=='rhwp.exe' and executable.parent.name=='Tools','검증한 제품 Tools/rhwp.exe가 필요합니다')
    source=executable.parent.parent;paths=[];total=0
    for path in source.rglob('*'):
        require(not path.is_symlink() and not getattr(path.lstat(),'st_file_attributes',0)&0x400,'runtime symlink/reparse를 복사하지 않습니다')
        if path.is_file():
            total+=path.stat().st_size;paths.append(path)
            require(len(paths)<=10000 and total<=96*1024*1024,'private runtime 복사 상한을 초과했습니다')
    require(not output.exists() and not output.is_symlink(),'private runtime을 덮어쓰지 않습니다')
    shutil.copytree(source,output)
    return output/'Tools/rhwp.exe'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--architecture',choices=('x64','arm64'),default='x64')
    parser.add_argument('--fixtures',type=Path,required=True);parser.add_argument('--password-fixtures',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--context',choices=('portable','installed'),default='portable');parser.add_argument('--package-full-name')
    args=parser.parse_args();binding=current_binding();executable=args.exe.resolve()
    require(args.exe.is_file() and not args.exe.is_symlink() and re.fullmatch('[0-9a-f]{64}',args.expected_sha256)
            and sha(executable)==args.expected_sha256,'원본 제품 CLI의 byte identity가 다릅니다')
    verify_executable(executable,args.architecture);verify_host(args.architecture)
    require(args.fixtures.is_dir() and not args.fixtures.is_symlink() and (args.fixtures/'basic.hwpx').is_file(),'같은 실행의 원본 합성 fixture가 필요합니다')
    password_inputs(args.password_fixtures)
    require(not args.out.exists() and not args.out.is_symlink(),'기존 MCP 증거를 덮어쓰지 않습니다')
    if args.context=='installed':require(isinstance(args.package_full_name,str) and args.package_full_name,'설치 package identity가 필요합니다')
    else:require(args.package_full_name is None,'portable 시험으로 package activation을 주장하지 않습니다')
    import tempfile
    proof={'formatVersion':1,'cases':[],'caseCount':0,**binding,'architecture':args.architecture,'context':args.context,'productSha256':args.expected_sha256,
           'helperSha256':sha(Path(__file__)),'nativeArchitectureHelperSha256':sha(ROOT/'e2e/native_architecture.py'),
           'fullSourceQualified':False,'storeCertified':False,'scope':'실제 MCP stdio·합성 문서·native COM worker; 전체 도구·개인 문서·Store 인증을 주장하지 않음',
           'passed':False,'limits':{'frameBytes':MAX_FRAME,'runtimeBytes':96*1024*1024,'requestTimeoutSeconds':30}}
    args.out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='opengeul-mcp-'+uuid.uuid4().hex+'-') as temporary:
        work=Path(temporary)
        if args.context=='portable':executable=private_runtime(executable,work/'runtime')
        client=None
        try:
            client=McpClient([str(executable),'mcp-serve'],cwd=work)
            native=verify_process(client.process.pid,executable,args.architecture,handle=int(client.process._handle),package_full_name=args.package_full_name)
            watch=WorkerWatch(native,executable,args.expected_sha256,args.architecture,context=args.context,package_full_name=args.package_full_name)
            native['createdFileTime']=watch.created(int(client.process._handle));proof['serverNativeArchitecture']=native
            proof.update(run_cases(client,executable,work,args.fixtures.resolve(),password_folder=args.password_fixtures.resolve(),watch=watch,context=args.context,progress=proof))
        finally:
            if client:client.close()
            (args.out/'mcp-result.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    require(proof['passed'],'실제 MCP qualification이 완료되지 않았습니다')
    print(json.dumps({'passed':True,'architecture':args.architecture,'context':args.context,'caseCount':proof['caseCount'],'fullSourceQualified':False},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('실제 MCP 작업자 검증에 실패했습니다. bounded 결과·기존 원본은 보존합니다.') from None
