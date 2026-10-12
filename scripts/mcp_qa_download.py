"""검증된 Source 패키지의 같은 실행·아키텍처 MCP QA 원본만 내려받는다."""
from __future__ import annotations
import argparse
import contextlib
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'e2e')]
import mcp_fixtures as qa
import release_pair
import store_package
import store_qualification
from buildkit import DEV_IDENTITY, manifest
from prepare_payload import prepare, verify_checksums
from windows_arch import component_artifact_name, require_architecture
from windows_components import identity

REPOSITORY = 'ATLKR/OpenGeul'
MAX_ZIP = 16*1024*1024
MAX_METADATA = 2*1024*1024


def require(value, message):
    if not value: raise ValueError(message)


class GitHub:
    """고정 저장소 GET만 허용하고 stdout/stderr를 크기·시간 상한 안에서 수집한다."""
    def _bytes(self, path, cap):
        require(re.fullmatch(r'(?:actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*/jobs\?per_page=100|/artifacts\?per_page=100)?|actions/artifacts/[1-9][0-9]*(?:/zip)?|commits/(?:[0-9a-f]{40}|v[1-9][0-9]*\.[0-9]+\.[0-9]+(?:-dev\.[1-9][0-9]*\.[1-9][0-9]*)?))', path),
                '허용하지 않은 GitHub GET 경로입니다')
        command = ['gh','api','--method','GET',f'repos/{REPOSITORY}/{path}']
        process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        output = bytearray(); overflow = threading.Event()
        def drain(stream, destination, limit):
            try:
                for block in iter(lambda: stream.read(64*1024), b''):
                    if destination is not None:
                        left = limit-len(destination); destination.extend(block[:left])
                        if len(block)>left:
                            overflow.set()
                            try: process.kill()
                            except OSError: pass
                    else:
                        limit -= len(block)
                        if limit<0:
                            overflow.set()
                            try: process.kill()
                            except OSError: pass
            finally: stream.close()
        workers = [threading.Thread(target=drain,args=(process.stdout,output,cap),daemon=True),
                   threading.Thread(target=drain,args=(process.stderr,None,64*1024),daemon=True)]
        for worker in workers: worker.start()
        try:
            process.wait(timeout=120 if path.endswith('/zip') else 30)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(); raise ValueError('GitHub GET 제한 시간을 초과했습니다') from None
        finally:
            for worker in workers: worker.join(timeout=5)
        require(process.returncode==0 and not overflow.is_set() and all(not w.is_alive() for w in workers),
                'GitHub GET에 실패했습니다. 응답·stderr·인증 정보는 출력하지 않습니다')
        require(0<len(output)<=cap,'GitHub GET 응답 크기가 올바르지 않습니다')
        return bytes(output)

    def get(self, path): return qa.strict_json(self._bytes(path,MAX_METADATA))
    def zip(self, artifact_id): return self._bytes('actions/artifacts/'+str(artifact_id)+'/zip',MAX_ZIP)


def _boundary(output, inputs):
    output = qa.safe_path(output); origin = output.with_name(output.name+'-origin')
    qa.safe_path(origin)
    require(output.parent.is_dir() and not output.exists() and not origin.exists(),
            '기존 QA 출력·원본 receipt를 덮어쓰지 않습니다')
    for raw in inputs:
        path = qa.safe_path(raw)
        require(all(item!=path and item not in path.parents and path not in item.parents for item in (output,origin)),
                'QA 출력은 입력 디렉터리와 겹칠 수 없습니다')
    return output,origin


def _binding(provenance):
    attempt = provenance['windowsComponents']['runAttempt']
    binding = {'repository':provenance['repository'],'sourceCommit':provenance['commit'],
               'sourceRun':provenance['runId'],'runAttempt':attempt}
    qa.identity(binding); wasm = provenance['sourceParity']['wasmRebuild']; qa.wasm_proof(wasm)
    return binding,wasm


def source_context(package, env):
    package = qa.safe_path(package); provenance = release_pair.read_json(package/'provenance.json')
    require(set(provenance)==release_pair.PROVENANCE_KEYS,'원본 Source provenance 필드가 다릅니다')
    architecture = require_architecture(provenance['architecture'])
    current = identity(os.environ if env is None else env)
    components = provenance['windowsComponents']
    require(isinstance(components,dict) and set(components)=={'formatVersion','repository','commit','runId','runAttempt','sourceContractSha256','components'}
            and type(components['formatVersion']) is int and components['formatVersion']==1
            and all(components.get(key)==value for key,value in current.items()),'현재 Source 실행의 패키지가 아닙니다')
    require(all(provenance.get(key)==current[key] for key in ('repository','commit','runId'))
            and provenance['unsigned'] is True and provenance['storeCertified'] is False,
            '다른 Source 또는 서명·인증된 패키지입니다')
    version = release_pair.read_json(ROOT/'config/product.json')['version']
    require(provenance['version']==version and provenance['upstream']==release_pair.read_json(ROOT/'config/upstream.lock.json'),
            '현재 버전·업스트림과 다른 패키지입니다')
    require(isinstance(provenance['sourceParity'],dict) and provenance['sourceParity'].get('version')==version
            and provenance['sourceParity'].get('source')=='OpenGeul distribution overlays'
            and release_pair.digest(components['sourceContractSha256'])==components['sourceContractSha256'],
            'Source 준비 ledger·컴파일 소스 해시가 다릅니다')
    names = release_pair._names(package,provenance)
    require(len(names)==6 and {p.name for p in package.iterdir()}==names,'Source 원본은 정확히 6파일이어야 합니다')
    release_pair.budget(list(package.iterdir()),release_pair.ARCH_LIMIT)
    sums = verify_checksums(package)
    require(provenance['sha256']==sums[provenance['package']],'Source MSIX 원본 해시가 다릅니다')
    with tempfile.TemporaryDirectory(prefix='opengeul-mcp-source-') as temporary:
        with contextlib.redirect_stdout(io.StringIO()):
            result = prepare(package,Path(temporary)/'runtime',architecture=architecture)
    require(result['msix']==provenance['package'],'검증한 원본 MSIX 이름이 다릅니다')
    with zipfile.ZipFile(package/provenance['package']) as archive:
        expected_manifest = manifest(DEV_IDENTITY,version,architecture).encode('utf-8')
        require(archive.read('AppxManifest.xml')==(package/'AppxManifest.xml').read_bytes()==expected_manifest,
                '원본 MSIX 신원·manifest가 다릅니다')
        require(type(provenance['members']) is int and provenance['members']==len(archive.infolist()),'원본 MSIX 멤버 수가 다릅니다')
        require(set(components['components'])=={'editor','cli'},'두 제품 구성 요소 원본이 필요합니다')
        for role,runtime in (('editor','OpenGeul.exe'),('cli','Tools/rhwp.exe')):
            record = components['components'][role]
            require(isinstance(record,dict) and set(record)=={'artifactName','runAttempt','provenanceSha256','runtime','size','sha256'}
                    and record['artifactName']==component_artifact_name(role,current['runId'],architecture)
                    and record['runtime']==runtime and isinstance(record['runAttempt'],str)
                    and re.fullmatch('[1-9][0-9]*',record['runAttempt']) and int(record['runAttempt'])<=int(current['runAttempt']),
                    '구성 요소 아키텍처·실행·원본이 다릅니다')
            require(release_pair.digest(record['provenanceSha256'])==record['provenanceSha256']
                    and release_pair.digest(record['sha256'])==record['sha256']
                    and type(record['size']) is int and record['size']==archive.getinfo(runtime).file_size,
                    '구성 요소 크기·해시가 다릅니다')
            with archive.open(runtime) as stream:
                require(release_pair.stream_hash(stream)==record['sha256'],'MSIX 제품 바이트와 구성 요소 원본이 다릅니다')
    binding,wasm = _binding(provenance)
    return binding,wasm,architecture


def _time(value):
    require(isinstance(value,str) and len(value)<=32 and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z',value),
            'GitHub 시각 증거가 올바르지 않습니다')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def _page(value, key):
    require(isinstance(value,dict) and type(value.get('total_count')) is int
            and 0<=value['total_count']<=100 and isinstance(value.get(key),list)
            and len(value[key])==value['total_count'],'GitHub 단일 페이지 증거가 누락되거나 한도를 초과했습니다')
    return value[key]


def _pr_binding(binding, run, backend, env):
    """현재 PR의 실제 checkout merge만 API head와 연결한다. Source SHA를 바꾸지 않는다."""
    require(env.get('GITHUB_EVENT_NAME')=='pull_request'
            and all(env.get(key)==binding[value] for key,value in (
                ('GITHUB_REPOSITORY','repository'),('GITHUB_SHA','sourceCommit'),
                ('GITHUB_RUN_ID','sourceRun'),('GITHUB_RUN_ATTEMPT','runAttempt'))),
            'PR 연결은 현재 pull_request 실행에서만 허용합니다')
    ref=env.get('GITHUB_REF')
    require(isinstance(ref,str),'현재 PR merge ref는 문자열이어야 합니다')
    match=re.fullmatch(r'refs/pull/([1-9][0-9]{0,19})/merge',ref)
    require(match is not None,'현재 PR merge ref가 필요합니다')
    path=env.get('GITHUB_EVENT_PATH')
    require(isinstance(path,str) and 0<len(path)<=32768,'현재 bounded PR event가 필요합니다')
    event=qa.strict_json(qa.read(Path(path),MAX_METADATA))
    def obj(value):
        require(isinstance(value,dict),'PR 신원 객체가 필요합니다');return value
    def positive(value):
        require(type(value) is int and 0<value<2**63,'PR/repository ID가 올바르지 않습니다');return value
    event=obj(event);pr=obj(event.get('pull_request'));repo=obj(event.get('repository'))
    number=positive(pr.get('number'));pr_id=positive(pr.get('id'));repo_id=positive(repo.get('id'))
    require(type(event.get('number')) is int and event['number']==number==int(match[1])
            and repo.get('full_name')==REPOSITORY and repo.get('private') is False
            and type(run['repository'].get('id')) is int and run['repository']['id']==repo_id,
            '현재 PR 번호/owned repository가 다릅니다')
    rows=run.get('pull_requests')
    require(isinstance(rows,list) and len(rows)==1,'현재 실행의 단일 PR API association이 필요합니다')
    associated=obj(rows[0])
    require(type(associated.get('id')) is int and associated['id']==pr_id
            and type(associated.get('number')) is int and associated['number']==number,'실행 API의 PR 신원이 다릅니다')
    observed={}
    for role,env_ref in (('base','GITHUB_BASE_REF'),('head','GITHUB_HEAD_REF')):
        actual=obj(pr.get(role));linked=obj(associated.get(role));side_repo=obj(actual.get('repo'))
        linked_repo=obj(linked.get('repo'));side_id=positive(side_repo.get('id'))
        value=actual.get('sha');branch=actual.get('ref')
        require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value)
                and isinstance(branch,str) and 0<len(branch)<=255 and not any(ord(c)<32 for c in branch)
                and linked.get('sha')==value and linked.get('ref')==branch and env.get(env_ref)==branch
                and type(linked_repo.get('id')) is int and linked_repo['id']==side_id
                and side_repo.get('private') is False,'현재 PR head/base SHA·ref·repository가 다릅니다')
        if role=='base':
            require(side_id==repo_id and side_repo.get('full_name')==REPOSITORY,'PR base는 고정 owned repository여야 합니다')
        observed[role]=(value,branch,side_id)
    require(run.get('head_sha')==observed['head'][0] and run.get('head_branch')==observed['head'][1],
            'PR 실행 API head/ref가 현재 event와 다릅니다')
    merge=obj(backend.get('commits/'+binding['sourceCommit']));parents=merge.get('parents')
    require(merge.get('sha')==binding['sourceCommit'] and isinstance(parents,list) and len(parents)==2
            and all(isinstance(row,dict) for row in parents)
            and [row.get('sha') for row in parents]==[observed['base'][0],observed['head'][0]],
            '실제 checkout merge의 두 부모가 현재 PR base/head와 다릅니다')
    return {'number':number,'id':pr_id,'mergeCommit':binding['sourceCommit'],'apiHeadCommit':observed['head'][0],
            'baseCommit':observed['base'][0],'headRepositoryId':observed['head'][2],'baseRepositoryId':observed['base'][2]}


def _run_jobs(binding, backend, *, env=None, allow_pr=False):
    run_id = binding['sourceRun']; attempt = int(binding['runAttempt'])
    run = backend.get('actions/runs/'+run_id)
    require(isinstance(run,dict) and type(run.get('id')) is int and str(run['id'])==run_id
            and type(run.get('run_attempt')) is int and run['run_attempt']==attempt
            and run.get('repository',{}).get('full_name')==REPOSITORY and run['repository'].get('private') is False
            and run.get('path')=='.github/workflows/msix.yml' and run.get('event') in ('push','pull_request','workflow_dispatch')
            and (run.get('status')=='in_progress' and run.get('conclusion') is None
                 or run.get('status')=='completed' and run.get('conclusion')=='success'),
            '실제 Source GitHub 실행·시도·workflow·결과가 다릅니다')
    pr=None
    if run['event']=='pull_request':
        require(allow_pr,'Store QA는 PR Source를 재사용하지 않습니다')
        pr=_pr_binding(binding,run,backend,os.environ if env is None else env)
    else:
        require(run.get('head_sha')==binding['sourceCommit'],'Source API와 checkout SHA가 다릅니다')
    _time(run.get('run_started_at'))
    jobs = _page(backend.get(f'actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100'),'jobs')
    return run,jobs,pr


def _artifact(value, binding, architecture, run, producer, pr=None):
    suffix = '-arm64' if architecture=='arm64' else ''
    require(isinstance(value,dict) and type(value.get('id')) is int and value['id']>0
            and value.get('name')=='opengeul-mcp-fixtures'+suffix+'-'+binding['sourceRun']
            and type(value.get('size_in_bytes')) is int and 0<value['size_in_bytes']<=MAX_ZIP
            and value.get('expired') is False and isinstance(value.get('digest'),str)
            and re.fullmatch('sha256:[0-9a-f]{64}',value['digest'])
            and type(value.get('workflow_run',{}).get('id')) is int
            and str(value['workflow_run']['id'])==binding['sourceRun']
            and value['workflow_run'].get('head_sha')==(pr['apiHeadCommit'] if pr else binding['sourceCommit']),
            '다른 실행·아키텍처·digest의 QA artifact입니다')
    created = _time(value.get('created_at')); updated = _time(value.get('updated_at'))
    require(_time(run['run_started_at'])<=_time(producer['started_at'])<=created<=updated<=_time(producer['completed_at']),
            'QA artifact가 현재 attempt의 성공 생산자 실행 구간에 속하지 않습니다')
    return {key:value[key] for key in ('id','name','size_in_bytes','digest','expired','created_at','updated_at')} | {
        'workflow_run':{'id':value['workflow_run']['id'],'head_sha':value['workflow_run']['head_sha']}}


def _extract(raw, folder):
    import zipfile
    wanted = qa.PAYLOAD_FILES|{qa.MANIFEST}; aliases = set(); files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist(); require(len(entries)==12,'QA ZIP은 정확한 12파일이어야 합니다')
        require(sum(e.file_size for e in entries)<=qa.MAX_BYTES,'QA ZIP 확장 크기 한도를 초과했습니다')
        for entry in entries:
            name = entry.filename; kind = stat.S_IFMT(entry.external_attr>>16)
            require(name in wanted and name.casefold() not in aliases and not entry.is_dir()
                    and kind in (0,stat.S_IFREG) and not entry.flag_bits&1
                    and not entry.external_attr&0x400 and 0<entry.file_size<=(qa.MAX_JSON if name.endswith('.json') else qa.MAX_FILE),
                    'QA ZIP에 알 수 없는 경로·별칭·특수 파일이 있습니다')
            aliases.add(name.casefold());files[name]=entry
        require(set(files)==wanted,'QA ZIP 원본 목록이 다릅니다')
        folder.mkdir()
        for name,entry in files.items():
            destination=folder/name;destination.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as stream: data=stream.read(entry.file_size+1)
            require(len(data)==entry.file_size,'QA ZIP 원본 길이가 다릅니다')
            with destination.open('xb') as stream: stream.write(data)


def _move_new(source, destination):
    """기존 빈 디렉터리도 바꾸지 않는 호스트의 원자적 rename을 사용한다."""
    if os.name=='nt':
        source.rename(destination)  # Windows rename은 기존 목적지에서 실패한다.
    elif sys.platform.startswith('linux'):
        import ctypes
        libc=ctypes.CDLL(None,use_errno=True)
        function=getattr(libc,'renameat2',None)
        require(function is not None,'원자적 no-replace 게시를 지원하지 않는 호스트입니다')
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        function.restype=ctypes.c_int
        if function(-100,os.fsencode(source),-100,os.fsencode(destination),1)!=0:
            raise OSError(ctypes.get_errno(),'QA 기존 목적지를 대체하지 않습니다')
    else:
        raise ValueError('원자적 no-replace 게시를 지원하지 않는 호스트입니다')


def _fetch(binding, wasm, architecture, output, origin, backend, run, jobs, pr=None):
    producer_name = 'native-e2e (windows-11-arm)' if architecture=='arm64' else 'native-e2e (windows-2025)'
    candidates = [job for job in jobs if job.get('name')==producer_name]
    require(len(candidates)==1,'해당 QA 생산자의 성공 job이 정확히 하나여야 합니다')
    producer=candidates[0]
    require(producer.get('status')=='completed' and producer.get('conclusion')=='success'
            and type(producer.get('run_id')) is int and str(producer['run_id'])==binding['sourceRun']
            and type(producer.get('run_attempt')) is int and str(producer['run_attempt'])==binding['runAttempt']
            and producer.get('head_sha')==(pr['apiHeadCommit'] if pr else binding['sourceCommit']),'QA 생산자 결과·실행·attempt가 다릅니다')
    name='opengeul-mcp-fixtures'+('-arm64' if architecture=='arm64' else '')+'-'+binding['sourceRun']
    matches=[item for item in _page(backend.get('actions/runs/'+binding['sourceRun']+'/artifacts?per_page=100'),'artifacts') if item.get('name')==name]
    require(len(matches)==1,'QA artifact 이름이 없거나 중복되어 재선택하지 않습니다')
    selected=_artifact(matches[0],binding,architecture,run,producer,pr)
    fixed=_artifact(backend.get('actions/artifacts/'+str(selected['id'])),binding,architecture,run,producer,pr)
    require(fixed==selected,'선택한 QA artifact가 다운로드 전에 변경되었습니다')
    raw=backend.zip(selected['id'])
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_ZIP and len(raw)==selected['size_in_bytes']
            and 'sha256:'+hashlib.sha256(raw).hexdigest()==selected['digest'],'QA ZIP 실제 크기·서버 SHA256이 다릅니다')
    with tempfile.TemporaryDirectory(prefix='.opengeul-mcp-download-',dir=output.parent) as temporary:
        base=Path(temporary);payload=base/'payload';_extract(raw,payload)
        qa.verify(payload,binding,wasm,architecture=architecture)
        proof=base/'origin';proof.mkdir();(proof/'original.zip').write_bytes(raw)
        receipt={'formatVersion':1,**binding,'architecture':architecture,'artifact':selected,
            'run':{key:run.get(key) for key in ('id','head_sha','run_attempt','path','event','status','conclusion','run_started_at')},
            'producer':{key:producer.get(key) for key in ('id','name','run_id','run_attempt','head_sha','status','conclusion','started_at','completed_at')},
            'originalZip':{'name':'original.zip','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
            'fixtureManifestSha256':qa.sha(payload/qa.MANIFEST),'helperSha256':qa.sha(Path(qa.__file__)),
            'publicQaOnly':True,'fullSourceQualified':False,'verifiedFiles':12}
        if pr is not None:receipt['pullRequestBinding']=pr
        data=(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        require(len(data)<=qa.MAX_JSON,'QA origin receipt 크기 상한을 초과했습니다')
        (proof/'receipt.json').write_bytes(data)
        require(not output.exists() and not origin.exists(),'QA 출력·origin이 검증 중 생성되어 덮어쓰지 않습니다')
        _move_new(proof,origin)
        # 다음 게시가 실패해도 검증된 원 ZIP/receipt를 보존한다. 공개 경로를
        # 삭제하지 않으므로 다른 호출이 만든 목적지·교체된 디렉터리는 안전하다.
        _move_new(payload,output)
    return receipt


def download_source(package_directory, output, *, backend=None, env=None):
    output,origin=_boundary(output,(package_directory,))
    binding,wasm,architecture=source_context(Path(package_directory),env)
    backend=GitHub() if backend is None else backend;run,jobs,pr=_run_jobs(binding,backend,env=env,allow_pr=True)
    return _fetch(binding,wasm,architecture,output,origin,backend,run,jobs,pr)


def download_store(store_directory, source_directory, architecture, output, *, backend=None, env=None):
    architecture=require_architecture(architecture)
    output,origin=_boundary(output,(store_directory,source_directory))
    source_directory=qa.safe_path(source_directory);store_directory=qa.safe_path(store_directory)
    pair=release_pair.verify_pair(source_directory)
    details,_=store_qualification._store(store_directory,env)
    require(pair==release_pair.read_json(store_directory/'source-provenance.json')
            and release_pair.source_fingerprint(source_directory)==details['sourceAssetFingerprintSha256'],
            'Store가 검증한 실제 Source22 원본과 다릅니다')
    for arch in ('x64','arm64'):
        source=pair['architectures'][arch];entry=details['architectures'][arch]
        hashes=store_package.verify_repackage(source_directory/source['assets'][source['provenance']['package']],
                      store_directory/entry['package'],details['version'],arch)
        require(hashes==entry['runtimeSha256'],'Store runtime이 실제 Source 제품 바이트와 다릅니다')
    provenance=pair['architectures'][architecture]['provenance'];binding,wasm=_binding(provenance)
    require(binding=={'repository':pair['repository'],'sourceCommit':pair['commit'],'sourceRun':pair['runId'],'runAttempt':pair['runAttempt']},
            '선택 아키텍처와 공통 Source 실행이 다릅니다')
    backend=GitHub() if backend is None else backend;run,jobs,_=_run_jobs(binding,backend,env=env)
    tag=details['sourceRelease'].rsplit('/',1)[1]
    tag_sha=backend.get('commits/'+tag).get('sha')
    store_package.authorize_release(tag,pair,run,tag_sha,jobs)
    return _fetch(binding,wasm,architecture,output,origin,backend,run,jobs)


def main():
    parser=argparse.ArgumentParser(description='같은 실행·아키텍처의 공개 MCP QA 원본만 검증하여 받습니다')
    commands=parser.add_subparsers(dest='mode',required=True)
    source=commands.add_parser('source');source.add_argument('--package-directory',type=Path,required=True)
    store=commands.add_parser('store');store.add_argument('--store-directory',type=Path,required=True)
    store.add_argument('--source-directory',type=Path,required=True);store.add_argument('--architecture',choices=('x64','arm64'),required=True)
    for command in (source,store):command.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    receipt=(download_source(args.package_directory,args.output) if args.mode=='source' else
             download_store(args.store_directory,args.source_directory,args.architecture,args.output))
    print(json.dumps({'passed':True,'sourceCommit':receipt['sourceCommit'],'sourceRun':receipt['sourceRun'],
                      'runAttempt':receipt['runAttempt'],'architecture':receipt['architecture'],'verifiedFiles':12,'fullSourceQualified':False}))


if __name__=='__main__':
    try: main()
    except Exception: raise SystemExit('같은 실행의 MCP QA 다운로드 검증에 실패했습니다. 응답·인증 정보는 출력하지 않습니다.') from None
