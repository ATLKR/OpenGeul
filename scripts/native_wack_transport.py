"""ARM 네이티브 설치와 x64 SDK를 같은 테스트 서명 바이트로 엄격하게 연결한다.

공개 CER와 단기 테스트 MSIX만 전송한다. 개인 키, 재서명, SDK 변경은 허용하지 않는다.
Source22/StoreRaw12에는 API·서명·전체 런타임 결합을 기존 JSON 안에 보존한다.
"""
from __future__ import annotations
import argparse
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'e2e')]
import mcp_qa_download as qa_download
import mcp_fixtures as qa
import release_pair as pair
from prepare_payload import PACKAGING_ONLY, inventory, stream_hash
from windows_components import identity, regular, sha

FILES={'native-install.json','test-only.msix','test.cer'}
MAX_ZIP=96*1024*1024
MAX_EXPANDED=96*1024*1024
JSON_CAP=512*1024
REPO='ATLKR/OpenGeul'
SOURCE_NATIVE='msix-native-arm64'
STORE_NATIVE='store-native-arm64'


def require(value,message):
    if not value:raise ValueError(message)


def timestamp(value):
    return qa_download._time(value)


def _json(path):return pair.read_json(path)


def _bytes_hash(data):return hashlib.sha256(data).hexdigest()


def runtime(path):
    regular(path);require(0<path.stat().st_size<=MAX_ZIP,'MSIX 크기 상한 초과')
    with zipfile.ZipFile(path) as archive:
        members=inventory(archive)
        result={}
        for name,member in members.items():
            if name in PACKAGING_ONLY|{'AppxSignature.p7x'}:continue
            with archive.open(member) as stream:result[name]={'bytes':member.file_size,'sha256':stream_hash(stream)}
        return result


def signed_parity(unsigned,signed):
    with zipfile.ZipFile(unsigned) as archive:
        require('AppxSignature.p7x' not in inventory(archive),'서명된 원본은 허용하지 않습니다')
    with zipfile.ZipFile(signed) as archive:
        entries=inventory(archive)
        require('AppxSignature.p7x' in entries and entries['AppxSignature.p7x'].file_size>0,'테스트 서명이 없습니다')
    original=runtime(unsigned);require(runtime(signed)==original,'서명 후 manifest/전체 런타임 바이트가 변경되었습니다')
    require(sha(unsigned)!=sha(signed),'원본과 서명 후보가 같습니다')
    return original


def _tlv(data):
    require(isinstance(data,bytes) and 2<=len(data)<=16*1024,'공개 인증서 DER 크기 오류')
    result=[];position=0
    while position<len(data):
        require(position+2<=len(data),'인증서 DER 잘림')
        tag=data[position];length=data[position+1];position+=2
        require(tag&31!=31,'지원하지 않는 인증서 DER tag')
        if length&128:
            count=length&127;require(1<=count<=3 and position+count<=len(data),'DER 길이 오류')
            raw=data[position:position+count];require(raw[0]!=0,'비정규 DER 길이')
            length=int.from_bytes(raw,'big');position+=count;require(length>=128,'비정규 DER 길이')
        require(position+length<=len(data),'인증서 DER 잘림')
        result.append((tag,data[position:position+length]));position+=length
    return result


def _name(raw):
    attributes=[]
    for tag,value in _tlv(raw):
        require(tag==0x31,'인증서 subject DER 오류')
        for entry,content in _tlv(value):
            values=_tlv(content);require(entry==0x30 and len(values)==2 and values[0][0]==6,'인증서 subject 오류')
            require(values[0][1]==bytes.fromhex('550403') and values[1][0] in (12,19),'고정 CN 인증서가 필요합니다')
            attributes.append(values[1][1].decode('utf-8'))
    require(len(attributes)==1,'단일 CN 테스트 인증서가 필요합니다')
    return 'CN='+attributes[0]


def certificate(data):
    outer=_tlv(data);require(len(outer)==1 and outer[0][0]==0x30,'공개 X509 DER 인증서가 필요합니다')
    cert=_tlv(outer[0][1]);require(len(cert)==3 and [item[0] for item in cert]==[0x30,0x30,3],
                                '공개 X509 Certificate 구조가 필요합니다. 개인 키는 허용하지 않습니다')
    body=_tlv(cert[0][1]);offset=1 if body[0][0]==0xa0 else 0
    require(len(body)>=offset+6,'공개 X509 본문 잘림')
    validity=_tlv(body[offset+3][1]);require(body[offset+3][0]==0x30 and len(validity)==2,'인증서 유효기간 오류')
    dates=[]
    for tag,value in validity:
        require(tag in (23,24),'인증서 시각 오류')
        dates.append(datetime.strptime(value.decode('ascii'),'%y%m%d%H%M%SZ' if tag==23 else '%Y%m%d%H%M%SZ').replace(tzinfo=timezone.utc))
    require(timedelta(0)<dates[1]-dates[0]<=timedelta(days=1),'테스트 인증서는 하루 이내여야 합니다')
    subject=_name(body[offset+4][1]);issuer=_name(body[offset+2][1]);require(subject==issuer,'자체 서명 테스트 인증서가 필요합니다')
    eku=[]
    for tag,content in body[offset+6:]:
        if tag!=0xa3:continue
        extension_sequence=_tlv(content);require(len(extension_sequence)==1 and extension_sequence[0][0]==0x30,'인증서 확장 오류')
        for entry,raw in _tlv(extension_sequence[0][1]):
            fields=_tlv(raw);require(entry==0x30 and len(fields) in (2,3) and fields[0][0]==6 and fields[-1][0]==4,'인증서 확장 오류')
            if fields[0][1]==bytes.fromhex('551d25'):
                seq=_tlv(fields[-1][1]);require(len(seq)==1 and seq[0][0]==0x30,'인증서 EKU 오류')
                eku.extend(value for kind,value in _tlv(seq[0][1]) if kind==6)
    require(eku==[bytes.fromhex('2b06010505070303')],'CodeSigning 전용 공개 인증서가 필요합니다')
    return {'derBase64':base64.b64encode(data).decode('ascii'),'sha256':_bytes_hash(data),
        'thumbprint':hashlib.sha1(data).hexdigest().upper(),'subject':subject,
        'notBefore':dates[0].strftime('%Y-%m-%dT%H:%M:%SZ'),'notAfter':dates[1].strftime('%Y-%m-%dT%H:%M:%SZ'),
        'codeSigning':True,'publicOnly':True}


def _job(job,binding,name,*,completed=True):
    require(isinstance(job,dict) and type(job.get('id')) is int and job['id']>0 and job.get('name')==name
        and type(job.get('run_id')) is int and str(job['run_id'])==binding['runId']
        and type(job.get('run_attempt')) is int and str(job['run_attempt'])==binding['runAttempt']
        and job.get('head_sha')==binding['commit'],'생산자/소비자 job 역할·실행·head·시도 불일치')
    timestamp(job.get('started_at'))
    if completed:
        require(job.get('status')=='completed' and job.get('conclusion')=='success'
            and timestamp(job['started_at'])<=timestamp(job.get('completed_at')),'실제 성공한 생산자가 필요합니다')
    else:require(job.get('status')=='in_progress' and job.get('conclusion') is None,'현재 실행 중인 생산자/소비자만 허용합니다')
    return {key:job.get(key) for key in ('id','name','run_id','run_attempt','head_sha','status','conclusion','started_at','completed_at')}


def artifact(value,binding,run,producer,name,cap):
    role=(STORE_NATIVE if name.startswith('opengeul-store-native-signed-') else SOURCE_NATIVE) if 'native-signed' in name else ('package' if name.startswith('opengeul-store-') else 'build-arm64')
    _job(producer,binding,role)
    require(isinstance(value,dict) and type(value.get('id')) is int and value['id']>0 and value.get('name')==name
        and type(value.get('size_in_bytes')) is int and 0<value['size_in_bytes']<=cap
        and value.get('expired') is False and re.fullmatch('sha256:[0-9a-f]{64}',str(value.get('digest',''))),'artifact 이름·크기·digest·만료 불일치')
    owner=value.get('workflow_run',{})
    require(type(owner.get('id')) is int and str(owner['id'])==binding['runId'] and owner.get('head_sha')==binding['commit'],
            '다른 실행·head의 artifact')
    for field,expected in [('head_branch',run.get('head_branch')),('repository_id',run['repository'].get('id')),
                           ('head_repository_id',run['head_repository'].get('id'))]:
        if field in owner:require(owner[field]==expected,'artifact 저장소·branch 연결 불일치')
    created=timestamp(value.get('created_at'));updated=timestamp(value.get('updated_at'))
    require(timestamp(run['run_started_at'])<=timestamp(producer['started_at'])<=created<=updated<=timestamp(producer['completed_at']),
            '현재 성공 생산자 시각 구간 밖의 artifact')
    require(updated<timestamp(value.get('expires_at'))<=created+timedelta(days=1,minutes=5),
            '전송 artifact 보존 기간은 하루 이내여야 합니다')
    return {key:value[key] for key in ('id','name','size_in_bytes','digest','expired','created_at','updated_at','expires_at')}|{'workflow_run':dict(owner)}


def extract(raw,output):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_ZIP,'전송 ZIP 크기 초과');require(not output.exists(),'기존 전송 출력 덮어쓰기 금지')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist();require(len(entries)==3 and sum(e.file_size for e in entries)<=MAX_EXPANDED,'전송 ZIP은 제한된 정확히 3파일이어야 합니다')
        seen=set()
        for entry in entries:
            kind=stat.S_IFMT(entry.external_attr>>16)
            require(entry.filename in FILES and entry.filename.casefold() not in seen and not entry.is_dir()
                and kind in (0,stat.S_IFREG) and not entry.flag_bits&1 and not entry.external_attr&0x400
                and 0<entry.file_size<=(JSON_CAP if entry.filename.endswith('.json') else 16*1024 if entry.filename.endswith('.cer') else MAX_ZIP),
                '전송 ZIP 경로·별칭·특수 파일·확장 상한 위반')
            seen.add(entry.filename.casefold())
        require(archive.testzip() is None,'전송 ZIP CRC 불일치');output.mkdir()
        for entry in entries:
            with archive.open(entry) as stream:data=stream.read(entry.file_size+1)
            require(len(data)==entry.file_size,'전송 ZIP 실제 길이 불일치');(output/entry.filename).write_bytes(data)


class GitHub(qa_download.GitHub):
    def metadata(self,path):
        raw=self._bytes(path,qa_download.MAX_METADATA)
        return qa.strict_json(raw),{'rawBase64':base64.b64encode(raw).decode('ascii'),
            'bytes':len(raw),'sha256':_bytes_hash(raw)}
    def zip(self,artifact_id):return self._bytes('actions/artifacts/'+str(artifact_id)+'/zip',MAX_ZIP)


def _metadata(backend,path):
    if hasattr(backend,'metadata'):return backend.metadata(path)
    value=backend.get(path);raw=pair.encoded(value)
    return value,{'rawBase64':base64.b64encode(raw).decode('ascii'),'bytes':len(raw),'sha256':_bytes_hash(raw)}


def _metadata_proof(proof):
    require(isinstance(proof,dict) and set(proof)=={'rawBase64','bytes','sha256'},'API 원문 proof 필드 오류')
    raw=base64.b64decode(proof['rawBase64'],validate=True)
    require(type(proof['bytes']) is int and 0<len(raw)==proof['bytes']<=qa_download.MAX_METADATA
        and _bytes_hash(raw)==proof['sha256'],'API 원문 byte/hash 불일치')
    return qa.strict_json(raw)


def _run(binding,scope,backend,env):
    require(env.get('GITHUB_ACTIONS')=='true' and env.get('RUNNER_ENVIRONMENT')=='github-hosted'
        and identity(env)==binding,'현재 공개 hosted CI 실행만 허용합니다')
    run=backend.get('actions/runs/'+binding['runId'])
    path='.github/workflows/msix.yml' if scope=='source' else '.github/workflows/store-package.yml'
    require(isinstance(run,dict) and type(run.get('id')) is int and str(run['id'])==binding['runId']
        and type(run.get('run_attempt')) is int and str(run['run_attempt'])==binding['runAttempt']
        and run.get('path')==path and run.get('event') in (('push','pull_request','workflow_dispatch') if scope=='source' else ('workflow_dispatch',))
        and (run.get('status')=='in_progress' and run.get('conclusion') is None
             or run.get('status')=='completed' and run.get('conclusion')=='success'),'현재 source/store 실행이 아닙니다')
    for field in ('repository','head_repository'):
        repo=run.get(field,{})
        require(repo.get('full_name')==REPO and repo.get('private') is False and type(repo.get('id')) is int and repo['id']>0,
                '공개 고정 저장소 API 실행이 필요합니다')
    require(run['repository']['id']==run['head_repository']['id'],'fork 실행은 허용하지 않습니다')
    pr=None
    if run['event']=='pull_request':
        pr=qa_download._pr_binding({'repository':binding['repository'],'sourceCommit':binding['commit'],
            'sourceRun':binding['runId'],'runAttempt':binding['runAttempt']},run,backend,env)
        require(pr['headRepositoryId']==pr['baseRepositoryId']==run['repository']['id'],'fork PR은 허용하지 않습니다')
    else:require(run.get('head_sha')==binding['commit'],'현재 checkout/API head 불일치')
    if scope=='store':require(run.get('head_branch')=='main' and env.get('GITHUB_REF')=='refs/heads/main','현재 main Store 실행이 필요합니다')
    timestamp(run.get('run_started_at'))
    jobs=qa_download._page(backend.get(f'actions/runs/{binding["runId"]}/attempts/{binding["runAttempt"]}/jobs?per_page=100'),'jobs')
    return run,jobs,pr


def _api_binding(binding,run):return dict(binding,commit=run['head_sha'])


def _one_job(jobs,binding,name,*,completed=True):
    rows=[job for job in jobs if job.get('name')==name];require(len(rows)==1,'단일 정확한 생산자/소비자 job이 필요합니다')
    return _job(rows[0],binding,name,completed=completed)


def _files(directory):
    paths=list(directory.iterdir());pair.budget(paths,MAX_EXPANDED)
    return {path.name:{'bytes':path.stat().st_size,'sha256':sha(path)} for path in paths}


def _unsigned(scope,directory,env):
    require(scope in ('source','store'),'알 수 없는 실행 scope')
    directory=qa.safe_path(directory);current=identity(env)
    if scope=='source':
        _,_,architecture=qa_download.source_context(directory,env)
        require(architecture=='arm64','ARM64 Source6 원본이 필요합니다')
        msix=directory/_json(directory/'provenance.json')['package']
    else:
        import store_qualification
        details,_=store_qualification._store(directory,env);msix=directory/details['architectures']['arm64']['package']
    with zipfile.ZipFile(msix) as archive:
        node=ET.fromstring(archive.read('AppxManifest.xml')).find('{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity')
        require(node is not None,'실제 MSIX 신원 없음')
        package_identity={key:node.get(key) for key in ('Name','Publisher','Version','ProcessorArchitecture')}
    require(package_identity['ProcessorArchitecture']=='arm64','ARM64 후보만 연결합니다')
    return current,msix,package_identity,_files(directory)


def _selected(backend,binding,run,jobs,name,role):
    api_binding=_api_binding(binding,run);producer=_one_job(jobs,api_binding,role)
    listing=qa_download._page(backend.get('actions/runs/'+binding['runId']+'/artifacts?per_page=100'),'artifacts')
    rows=[value for value in listing if value.get('name')==name];require(len(rows)==1,'전송 artifact 이름이 누락/중복되었습니다')
    chosen=artifact(rows[0],api_binding,run,producer,name,MAX_ZIP)
    actual,rawproof=_metadata(backend,'actions/artifacts/'+str(chosen['id']))
    fixed=artifact(actual,api_binding,run,producer,name,MAX_ZIP)
    require(chosen==fixed,'선택한 artifact가 다운로드 전에 변경되었습니다')
    raw=backend.zip(chosen['id'])
    require(isinstance(raw,bytes) and len(raw)==chosen['size_in_bytes'] and 0<len(raw)<=MAX_ZIP
        and 'sha256:'+_bytes_hash(raw)==chosen['digest'],'원 ZIP 실제 bytes/server SHA256 불일치')
    return raw,{'artifact':chosen,'metadata':rawproof,'producer':producer}


def _unsigned_archive(raw,files):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist();require(len(entries)==len(files) and sum(row.file_size for row in entries)<=MAX_EXPANDED,'원본 ZIP 파일 수/확장 크기 불일치')
        seen=set()
        for entry in entries:
            kind=stat.S_IFMT(entry.external_attr>>16)
            require(entry.filename in files and entry.filename.casefold() not in seen and not entry.is_dir()
                and kind in (0,stat.S_IFREG) and not entry.flag_bits&1 and not entry.external_attr&0x400,
                '원본 ZIP 별칭·특수 파일·경로 불일치')
            seen.add(entry.filename.casefold())
            with archive.open(entry) as stream:digest=stream_hash(stream)
            require(files[entry.filename]=={'bytes':entry.file_size,'sha256':digest},'원본 ZIP과 선택한 unsigned 바이트가 다릅니다')
        require(archive.testzip() is None,'원본 ZIP CRC 불일치')


def _native_core(native,unsigned,binding,package_identity):
    fields={'formatVersion','success','scope','binding','completedAt','installation','launch','cli','cleanup','certificate','originalEvidence'}
    require(isinstance(native,dict) and set(native) in (fields,fields|{'runtime','producer'}),'알 수 없는/누락 native 전송 필드')
    require(type(native.get('formatVersion')) is int and native['formatVersion']==1 and native.get('success') is True and native.get('scope')=='native-arm64-install-only'
        and native.get('binding')==binding,'현재 ARM 네이티브 scope/source binding 필요')
    timestamp(native.get('completedAt'))
    cleanup=native.get('cleanup')
    require(isinstance(cleanup,dict) and set(cleanup)=={'candidateUninstalled','unsignedUnchanged','privateKeyRemoved','trustedCertificateRemoved','frameworksRemoved'}
        and all(value is True for value in cleanup.values()),'실제 candidate/key/trust/framework 제거가 완료되지 않았습니다')
    installation=native.get('installation');require(isinstance(installation,dict) and installation.get('success') is True
        and installation.get('architecture')=='arm64' and installation.get('uninstalled') is True
        and pair.digest(installation.get('originalSha256'))==sha(unsigned),'실제 설치 원본/성공/제거 불일치')
    require(set(installation)=={'success','architecture','packageFullName','publisher','fileTypes','originalSha256','signedTestPackageSha256','mcp','scope','uninstalled'}
        and isinstance(installation['scope'],str) and 0<len(installation['scope'])<=1024,'native installation의 고정 공개 필드 필요')
    signed=pair.digest(installation.get('signedTestPackageSha256'));require(signed!=sha(unsigned),'다른 test-signed 바이트가 필요합니다')
    full_name=f'{package_identity["Name"]}_{package_identity["Version"]}_arm64__{pair._publisher_id(package_identity["Publisher"])}'
    require(installation.get('publisher')==package_identity['Publisher'] and installation.get('packageFullName')==full_name,'native installed identity 불일치')
    cert=native.get('certificate');require(isinstance(cert,dict),'공개 인증서 증거 없음')
    raw=base64.b64decode(cert.get('derBase64',''),validate=True);actual=certificate(raw)
    require(cert==actual|{'signatureStatus':'Valid','signerThumbprint':actual['thumbprint']} and actual['subject']==package_identity['Publisher'],
            '공개 DER/설치 서명자/신원/유효기간 증거 불일치')
    import store_qualification
    originals=native.get('originalEvidence')
    require(isinstance(originals,dict) and set(originals)=={'installed-launch.json','installed-cli.json'},'native raw GUI/CLI byte 원문 필요')
    for filename,key in [('installed-launch.json','launch'),('installed-cli.json','cli')]:
        require(_metadata_proof(originals[filename])==native.get(key),'native GUI/CLI 원 byte JSON/해시 불일치')
    with tempfile.TemporaryDirectory(prefix='opengeul-native-proof-') as temporary:
        evidence=Path(temporary)
        for name,value in [('install.json',installation),('installed-launch.json',native.get('launch')),('installed-cli.json',native.get('cli'))]:
            (evidence/name).write_bytes(pair.encoded(value))
        hashes={name:item['sha256'] for name,item in runtime(unsigned).items()}
        store_qualification._native(evidence,{'_directory':str(unsigned.parent),'architectures':{'arm64':{'package':unsigned.name,'runtimeSha256':hashes}}},binding,'arm64')
    return signed


def _native_producer(scope,job):
    expected=SOURCE_NATIVE if scope=='source' else STORE_NATIVE
    require(job==expected,'현재 native ARM 생산자 job만 게시할 수 있습니다');return expected


def publish(scope,directory,evidence,transport,*,backend=None,env=None):
    env=os.environ if env is None else env;backend=GitHub() if backend is None else backend
    binding,unsigned,package_identity,files=_unsigned(scope,directory,env)
    require(env.get('GITHUB_ACTIONS')=='true' and env.get('RUNNER_ENVIRONMENT')=='github-hosted','공개 hosted CI만 허용합니다')
    role=_native_producer(scope,env.get('GITHUB_JOB'));transport=qa.safe_path(transport)
    require(transport.is_dir() and _files(transport).keys()==FILES,'native 전송은 정확히 3파일이어야 합니다')
    pair._separate(transport,directory,evidence)
    record=_json(transport/'native-install.json');require('producer' not in record and 'runtime' not in record,'이미 게시된 native record는 재사용하지 않습니다')
    _native_core(record,unsigned,binding,package_identity)
    for filename,key in [('installed-launch.json','launch'),('installed-cli.json','cli')]:
        require(_json(evidence/filename)==record[key],'native transport와 설치 원문이 다릅니다')
    require(certificate((transport/'test.cer').read_bytes())=={key:record['certificate'][key] for key in certificate((transport/'test.cer').read_bytes())},'공개 CER bytes가 다릅니다')
    require(sha(transport/'test-only.msix')==pair.digest(record['installation']['signedTestPackageSha256']),'실제 설치한 signed bytes가 아닙니다')
    record['runtime']=signed_parity(unsigned,transport/'test-only.msix')
    run,jobs,pr=_run(binding,scope,backend,env);api_binding=_api_binding(binding,run)
    native_job=_one_job(jobs,api_binding,role,completed=False)
    name=('opengeul-windows-arm64-' if scope=='source' else 'opengeul-store-')+binding['runId']
    raw,source=_selected(backend,binding,run,jobs,name,'build-arm64' if scope=='source' else 'package');_unsigned_archive(raw,files)
    record['producer']={'scope':scope,'run':run,'job':native_job,'unsigned':source,'unsignedFiles':files}
    if pr is not None:record['producer']['pullRequestBinding']=pr
    data=pair.encoded(record)+b'\n';require(len(data)<=JSON_CAP,'native record 크기 한도 초과')
    path=transport/'native-install.json';old=sha(path);stage=transport/'.native-install.json.tmp'
    require(not stage.exists(),'native 임시 출력 중복');stage.write_bytes(data)
    require(sha(path)==old,'게시 중 native record 변경');os.replace(stage,path)
    return record


def _producer_proof(record,binding,scope):
    proof=record.get('producer');require(isinstance(proof,dict) and proof.get('scope')==scope,'native 생산자 scope 증거 없음')
    run=proof.get('run');require(isinstance(run,dict) and str(run.get('id'))==binding['runId'] and str(run.get('run_attempt'))==binding['runAttempt'],
        'native 생산자 API run/attempt 불일치')
    require(run.get('status')=='in_progress' and run.get('conclusion') is None
        or run.get('status')=='completed' and run.get('conclusion')=='success','native 생산자 API 실행 상태/결론 불일치')
    require(run.get('path')==('.github/workflows/msix.yml' if scope=='source' else '.github/workflows/store-package.yml'),'native 생산자 workflow 불일치')
    for field in ('repository','head_repository'):
        require(run.get(field,{}).get('full_name')==REPO and run[field].get('private') is False
            and type(run[field].get('id')) is int and run[field]['id']>0,'native 생산자 owned API repository 없음')
    require(run['repository']['id']==run['head_repository']['id'],'native 생산자 fork repository')
    if run.get('event')=='pull_request':
        pr=proof.get('pullRequestBinding');require(scope=='source' and isinstance(pr,dict) and pr.get('mergeCommit')==binding['commit']
            and pr.get('apiHeadCommit')==run.get('head_sha') and pr.get('headRepositoryId')==pr.get('baseRepositoryId')==run['repository']['id'],
            '현재 owned PR merge/API head proof 필요')
    else:require(run.get('head_sha')==binding['commit'] and run.get('event') in (('push','workflow_dispatch') if scope=='source' else ('workflow_dispatch',)),
                 'native 생산자 checkout/API head 불일치')
    if scope=='store':require(run.get('head_branch')=='main','main Store 생산자만 허용합니다')
    api_binding=_api_binding(binding,run);role=SOURCE_NATIVE if scope=='source' else STORE_NATIVE
    _job(proof.get('job'),api_binding,role,completed=False)
    unsigned=proof.get('unsigned');require(isinstance(unsigned,dict),'unsigned API proof 없음')
    original=_metadata_proof(unsigned.get('metadata'))
    name=('opengeul-windows-arm64-' if scope=='source' else 'opengeul-store-')+binding['runId']
    require(artifact(original,api_binding,run,unsigned.get('producer'),name,MAX_ZIP)==unsigned.get('artifact'),'unsigned API metadata 원문 불일치')
    return proof,run


def download(scope,directory,output,*,backend=None,env=None):
    env=os.environ if env is None else env;backend=GitHub() if backend is None else backend
    binding,unsigned,package_identity,files=_unsigned(scope,directory,env);output=qa.safe_path(output)
    pair._fresh(output);pair._separate(output,directory);require(output.parent.is_dir(),'전송 출력 부모가 필요합니다')
    run,jobs,_=_run(binding,scope,backend,env);api_binding=_api_binding(binding,run)
    role=SOURCE_NATIVE if scope=='source' else STORE_NATIVE
    native_name=('opengeul-native-signed-arm64-' if scope=='source' else 'opengeul-store-native-signed-arm64-')+binding['runId']+'-'+binding['runAttempt']
    raw,native_origin=_selected(backend,binding,run,jobs,native_name,role)
    unsigned_name=('opengeul-windows-arm64-' if scope=='source' else 'opengeul-store-')+binding['runId']
    source_raw,source_origin=_selected(backend,binding,run,jobs,unsigned_name,'build-arm64' if scope=='source' else 'package');_unsigned_archive(source_raw,files)
    consumer_name='msix-install-arm64' if scope=='source' else 'Store WACK (arm64)'
    require(env.get('GITHUB_JOB')==('msix-install-arm64' if scope=='source' else 'store-wack'),'다른 SDK 소비자 job입니다')
    consumer=_one_job(jobs,api_binding,consumer_name,completed=False)
    with tempfile.TemporaryDirectory(prefix='.opengeul-native-download-',dir=output.parent) as temporary:
        stage=Path(temporary)/'payload';extract(raw,stage);record=_json(stage/'native-install.json')
        _native_core(record,unsigned,binding,package_identity);proof,old_run=_producer_proof(record,binding,scope)
        require(all(old_run.get(key)==run.get(key) for key in ('id','run_attempt','head_sha','path','event','run_started_at','repository','head_repository')),
                'native 생산자와 소비자가 다른 실행입니다')
        require(proof['unsigned']['artifact']==source_origin['artifact'] and proof['unsigned']['producer']==source_origin['producer']
            and _metadata_proof(proof['unsigned']['metadata'])==_metadata_proof(source_origin['metadata']) and proof['unsignedFiles']==files,
            'native 설치와 SDK 소비자가 다른 unsigned 원본을 사용했습니다')
        native_job=native_origin['producer']
        require(all(proof['job'].get(key)==native_job.get(key) for key in ('id','name','run_id','run_attempt','head_sha','started_at')),
                'native artifact가 실제 native 생산자의 출력이 아닙니다')
        actual_runtime=signed_parity(unsigned,stage/'test-only.msix')
        require(record.get('runtime')==actual_runtime and sha(stage/'test-only.msix')==pair.digest(record['installation']['signedTestPackageSha256']),
                'native signed 입력/전체 runtime 불일치')
        cert=certificate((stage/'test.cer').read_bytes());require(all(record['certificate'].get(key)==value for key,value in cert.items()),'전송 public CER와 native signer가 다릅니다')
        before=timestamp(record['certificate']['notBefore']);after=timestamp(record['certificate']['notAfter'])
        completed=timestamp(record['completedAt'])
        require(timestamp(native_job['started_at'])<=completed<=timestamp(native_origin['artifact']['created_at'])
            <=timestamp(native_job['completed_at'])<=timestamp(consumer['started_at']) and before<=completed<after,
            'native/SDK 검사 시각/생산자 구간이 동일 인증서 증거와 다릅니다')
        origin={'formatVersion':1,'scope':scope,'binding':binding,'native':native_origin,'unsigned':source_origin,
            'consumer':consumer,'nativeJsonSha256':sha(stage/'native-install.json')}
        (stage/'origin.json').write_bytes(pair.encoded(origin)+b'\n');qa_download._move_new(stage,output)
    return origin


def _origin_proof(origin,native,binding,scope):
    require(isinstance(origin,dict) and set(origin)=={'formatVersion','scope','binding','native','unsigned','consumer','nativeJsonSha256'}
        and type(origin['formatVersion']) is int and origin['formatVersion']==1 and origin['scope']==scope and origin['binding']==binding,
        'native 다운로드 origin 형식/현재 binding 불일치')
    require(origin['nativeJsonSha256']==_bytes_hash(pair.encoded(native)+b'\n'),'다운로드한 native 원 JSON SHA256 불일치')
    producer,run=_producer_proof(native,binding,scope);api_binding=_api_binding(binding,run)
    native_origin=origin.get('native');require(isinstance(native_origin,dict),'성공 native artifact 원문 없음')
    value=_metadata_proof(native_origin.get('metadata'))
    name=('opengeul-native-signed-arm64-' if scope=='source' else 'opengeul-store-native-signed-arm64-')+binding['runId']+'-'+binding['runAttempt']
    require(artifact(value,api_binding,run,native_origin.get('producer'),name,MAX_ZIP)==native_origin.get('artifact'),
            'native artifact API 원문/생산자/digest 불일치')
    completed_job=native_origin['producer'];old_job=producer['job']
    require(all(old_job.get(key)==completed_job.get(key) for key in ('id','name','run_id','run_attempt','head_sha','started_at')),
            '설치한 native 생산자와 SDK가 받은 native 생산자가 다릅니다')
    unsigned=origin.get('unsigned');require(isinstance(unsigned,dict),'SDK unsigned 원문 없음')
    unsigned_value=_metadata_proof(unsigned.get('metadata'))
    unsigned_name=('opengeul-windows-arm64-' if scope=='source' else 'opengeul-store-')+binding['runId']
    require(artifact(unsigned_value,api_binding,run,unsigned.get('producer'),unsigned_name,MAX_ZIP)==unsigned.get('artifact')
        and unsigned['artifact']==producer['unsigned']['artifact'] and unsigned['producer']==producer['unsigned']['producer']
        and _metadata_proof(unsigned['metadata'])==_metadata_proof(producer['unsigned']['metadata']),
        '두 소비자가 같은 원본 MSIX 생산자를 사용하지 않았습니다')
    consumer_name='msix-install-arm64' if scope=='source' else 'Store WACK (arm64)'
    consumer=_job(origin.get('consumer'),api_binding,consumer_name,completed=False)
    require(len({completed_job['id'],unsigned['producer']['id'],consumer['id']})==3
        and native_origin['artifact']['id']!=unsigned['artifact']['id'],'native/build/SDK job과 두 artifact 신원은 각각 달라야 합니다')
    completed=timestamp(native['completedAt'])
    require(timestamp(unsigned['producer']['completed_at'])<=timestamp(completed_job['started_at'])<=completed<=timestamp(native_origin['artifact']['created_at'])
        <=timestamp(completed_job['completed_at'])<=timestamp(consumer['started_at']),
        '성공 native 생산자/SDK 소비자 시각 연결 불일치')
    return producer


def _controller(controller,binding,scope,native,origin):
    require(isinstance(controller,dict) and controller.get('binding')==binding
        and controller.get('job')==('msix-install-arm64' if scope=='source' else 'store-wack'),'현재 SDK controller binding 필요')
    host=controller.get('host');require(isinstance(host,dict) and host.get('architecture')=='x64'
        and type(host.get('nativeMachine')) is int and host['nativeMachine']==0x8664,'실제 x64 WACK 호스트 필요')
    process=host.get('controller',{});require(type(process.get('processId')) is int and process['processId']>0
        and type(process.get('processMachine')) is int and process['processMachine']==0 and process.get('native') is True
        and process.get('architecture')=='x64','SDK controller가 실제 x64 native process가 아닙니다')
    tool=controller.get('tool');require(isinstance(tool,dict),'실제 stock WACK tool 관측 없음')
    require(tool.get('signatureStatus')=='Valid' and tool.get('signer')=='Microsoft Corporation'
        and isinstance(tool.get('signerSubject'),str) and re.search(r'(^|,\s*)O=Microsoft Corporation(,|$)',tool['signerSubject']),
        '정식 Microsoft WACK 서명자 필요')
    require(all(type(tool.get(key)) is int and tool[key]==value for key,value in [('peMachine',0x8664),('processMachine',0),('nativeMachine',0x8664)])
        and type(tool.get('processId')) is int and tool['processId']>0 and tool.get('ordinaryExit') is True
        and type(tool.get('helpExitCode')) is int,'stock SDK 실행 개체가 x64 native로 정상 종료하지 않았습니다')
    require(type(tool.get('bytes')) is int and tool['bytes']>0 and pair.digest(tool.get('sha256'))==tool['sha256']
        and isinstance(tool.get('version'),str) and re.fullmatch(r'10\.0\.[1-9][0-9]*\.[0-9]+',tool['version']),
        'SDK 실제 파일 hash/version/bytes 오류')
    require(tool.get('productVersion')==tool['version'] and isinstance(tool.get('fileVersion'),str)
        and len(tool['fileVersion'])<=256 and tool['fileVersion'].split(' ',1)[0]==tool['version'],
        '보존된 실제 SDK FileVersion/ProductVersion과 숫자 버전 불일치')
    from pathlib import PureWindowsPath
    path=PureWindowsPath(tool.get('path',''))
    require(path.is_absolute() and re.fullmatch('[A-Za-z]:',path.drive) and path.root=='\\' and tuple(part.casefold() for part in path.parts[1:])==
        ('program files (x86)','windows kits','10','app certification kit','appcert.exe'),'기본 stock WACK 경로가 아닙니다')
    cert=native['certificate'];signature=controller.get('signedSignature')
    require(signature=={'status':'Valid','thumbprint':cert['thumbprint'],'certificateSha256':cert['sha256']},
            'native 설치와 WACK 입력의 실제 Authenticode 서명자가 다릅니다')
    observed=timestamp(controller.get('observedAt'))
    require(timestamp(origin['consumer']['started_at'])<=observed and timestamp(cert['notBefore'])<=timestamp(native['completedAt'])<=observed<timestamp(cert['notAfter']),
            '실제 SDK/설치 시각이 인증서 유효기간 밖입니다')
    return tool


def _input(directory,native_directory,env):
    native_directory=qa.safe_path(native_directory)
    require(native_directory.is_dir() and {p.name for p in native_directory.iterdir()}==FILES|{'origin.json'},'검증된 native 전송 원본 exact4 필요')
    origin=_json(native_directory/'origin.json');scope=origin.get('scope')
    require(env.get('GITHUB_ACTIONS')=='true' and env.get('RUNNER_ENVIRONMENT')=='github-hosted'
        and env.get('GITHUB_JOB')==('msix-install-arm64' if scope=='source' else 'store-wack'),
        '현재 공개 hosted SDK 소비자만 입력을 검증할 수 있습니다')
    binding,unsigned,package_identity,files=_unsigned(scope,directory,env)
    native=_json(native_directory/'native-install.json');_native_core(native,unsigned,binding,package_identity)
    proof=_origin_proof(origin,native,binding,scope)
    require(proof['unsignedFiles']==files and native.get('runtime')==signed_parity(unsigned,native_directory/'test-only.msix')
        and sha(native_directory/'test-only.msix')==pair.digest(native['installation']['signedTestPackageSha256']),
        'SDK 입력 signed SHA/원본 파일/전체 runtime 불일치')
    require(all(native['certificate'].get(key)==value for key,value in certificate((native_directory/'test.cer').read_bytes()).items()),
            'SDK CER와 native 서명자가 다릅니다')
    return {'formatVersion':1,'native':native,'origin':origin,'packageIdentity':package_identity,
        'unsignedSha256':sha(unsigned),'signedSha256':sha(native_directory/'test-only.msix')},unsigned


def validate_input(directory,native_directory,output,*,env=None):
    env=os.environ if env is None else env;pending,_=_input(directory,native_directory,env)
    pair._fresh(output);pair._separate(output,directory,native_directory);output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.opengeul-wack-input-',dir=output.parent) as temporary:
        stage=Path(temporary)/'output';stage.mkdir()
        for name,value in [('pending-native.json',pending),('installed-launch.json',pending['native']['launch']),('installed-cli.json',pending['native']['cli'])]:
            data=(pair.encoded(value)+b'\n' if name=='pending-native.json' else
                  base64.b64decode(pending['native']['originalEvidence'][name]['rawBase64'],validate=True))
            (stage/name).write_bytes(data)
        qa_download._move_new(stage,output)
    return pending


def _context_join(split):
    return {'formatVersion':1,'binding':split['binding'],'nativeArtifactId':split['origin']['native']['artifact']['id'],
        'unsignedArtifactId':split['origin']['unsigned']['artifact']['id'],'nativeJsonSha256':split['origin']['nativeJsonSha256'],
        'controllerSha256':_bytes_hash(pair.encoded(split['controller'])),'splitSha256':_bytes_hash(pair.encoded(split))}


def verify_split(installation,context,unsigned,package_identity,binding,scope,files=None):
    split=installation.get('armNativeSplit')
    require(isinstance(split,dict) and set(split)=={'formatVersion','scope','binding','native','origin','controller'}
        and type(split.get('formatVersion')) is int and split['formatVersion']==1 and split.get('scope')==scope
        and split.get('binding')==binding,'ARM64 native/SDK 필수 증거 결합이 없습니다')
    native=split['native'];_native_core(native,unsigned,binding,package_identity)
    proof=_origin_proof(split['origin'],native,binding,scope);_controller(split['controller'],binding,scope,native,split['origin'])
    require(native.get('runtime')==runtime(unsigned),'native 설치와 현재 원본 전체 runtime byte map 불일치')
    if files is not None:require(proof['unsignedFiles']==files,'현재 원본 artifact 전체 파일 byte map 불일치')
    require(context.get('nativeSignedJoin')==_context_join(split),'설치/SDK context의 native 서명 결합이 다릅니다')
    original=dict(installation);original.pop('armNativeSplit',None)
    require(original==native['installation'],'최종 설치 성공이 실제 native 설치 원문에서 나오지 않았습니다')
    return split


def finalize(directory,native_directory,output,controller_path,*,env=None):
    env=os.environ if env is None else env;pending,unsigned=_input(directory,native_directory,env)
    require(_json(output/'pending-native.json')==pending,'검사 전 native 원문이 바뀌었습니다')
    for filename,key in [('installed-launch.json','launch'),('installed-cli.json','cli')]:
        raw=(output/filename).read_bytes();proof=pending['native']['originalEvidence'][filename]
        require(_json(output/filename)==pending['native'][key] and len(raw)==proof['bytes'] and _bytes_hash(raw)==proof['sha256'],
                '설치 GUI/CLI 원 byte가 변경되었습니다')
    controller=_json(controller_path);scope=pending['origin']['scope'];binding=pending['native']['binding']
    tool=_controller(controller,binding,scope,pending['native'],pending['origin'])
    context=_json(output/'wack-context.json');summary=_json(output/'wack.json')
    identity_node=pending['packageIdentity']
    require(context.get('invocationMode')=='documented-appxpackagepath' and pair.digest(context.get('inputPackageSha256'))==pending['signedSha256'],
            'WACK가 실제 설치된 signed 바이트를 검사하지 않았습니다')
    require(type(context.get('runnerSessionId')) is int and context['runnerSessionId']>0
        and type(context.get('wackSessionId')) is int and context['wackSessionId']==context['runnerSessionId'],'같은 실제 desktop session SDK 증거 필요')
    require(type(summary.get('exitCode')) is int and summary['exitCode']==0,'WACK 실행이 실패했습니다')
    actual=pair.inspect(output/'wack.xml',identity_node['Name'],identity_node['Version'],summary['exitCode'])
    require(actual==summary and actual['passed'] is True and actual['status']=='passed','원래 SDK XML 필수/선택 전체 PASS 필요')
    report=ET.fromstring((output/'wack.xml').read_bytes());require(report.get('VERSION')==tool['version'],'실제 SDK 도구 버전과 raw XML 버전 불일치')
    embedded=report.findall('./APPLICATIONS/Installed_Programs/Program[@Source="AppxPackage"]/Indicators/WindowsStoreAppManifestIndicators/PackageManifest/Package/Identity')
    require(len(embedded)==1 and dict(embedded[0].attrib)==identity_node,'SDK XML 실제 ARM package 신원 불일치')
    split={'formatVersion':1,'scope':scope,'binding':binding,'native':pending['native'],'origin':pending['origin'],'controller':controller}
    context=dict(context,nativeSignedJoin=_context_join(split));installation=dict(pending['native']['installation'],armNativeSplit=split)
    verify_split(installation,context,unsigned,identity_node,binding,scope,_files(directory))
    require(not (output/'install.json').exists(),'최종 설치 성공 원문 재사용 금지')
    install_data=pair.encoded(installation)+b'\n';context_data=pair.encoded(context)+b'\n'
    require(len(install_data)<=JSON_CAP and len(context_data)<=JSON_CAP,'최종 증거 JSON 크기 한도 초과')
    # 검증이 모두 끝난 뒤에만 final marker를 만든다. native-only는 final install이 없다.
    (output/'wack-context.json').write_bytes(context_data)
    with (output/'install.json').open('xb') as destination:destination.write(install_data)
    return installation


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    for scope in ('source','store'):
        for action in ('publish','download'):
            command=commands.add_parser(action+'-'+scope)
            command.add_argument('--'+('package-directory' if scope=='source' else 'store-directory'),dest='directory',type=Path,required=True)
            if action=='publish':
                command.add_argument('--evidence',type=Path,required=True);command.add_argument('--transport',type=Path,required=True)
            else:command.add_argument('--output',type=Path,required=True)
    for action in ('validate-input','finalize'):
        command=commands.add_parser(action);command.add_argument('--package-directory',type=Path,required=True)
        command.add_argument('--native-directory',type=Path,required=True);command.add_argument('--output-directory',type=Path,required=True)
        if action=='finalize':command.add_argument('--controller',type=Path,required=True)
    args=parser.parse_args()
    if args.command.startswith('publish-'):publish(args.command.split('-')[1],args.directory,args.evidence,args.transport)
    elif args.command.startswith('download-'):download(args.command.split('-')[1],args.directory,args.output)
    elif args.command=='validate-input':validate_input(args.package_directory,args.native_directory,args.output_directory)
    else:finalize(args.package_directory,args.native_directory,args.output_directory,args.controller)
    print('같은 ARM native 설치 바이트와 정식 SDK 결합을 검증했습니다. Store 인증 결과는 아닙니다.')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('ARM native/SDK 증거 결합 검증에 실패했습니다. 응답·인증 정보는 출력하지 않습니다.') from None
