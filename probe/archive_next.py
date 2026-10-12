"""고정 Store 원본 보관 준비. 미확정 핀 또는 root 실행 허가 없이는 요청하지 않는다."""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import quote
import zipfile

ROOT_EXECUTION_AUTHORIZED = True
CONTRACT_SHA256 = '90fd369abf27d054bea5c955eb840476dd0a4f72d7e7253b484f42a9fdd0f900'
CONTRACT = Path(__file__).with_name('archive-next-contract.json')
PLAN = Path(__file__).with_name('archive-next-plan.json')
BASE = Path(__file__).resolve().parents[1]
ROOT = 'repos/ATLKR/OpenGeul/'
LIMIT = 96 * 1024 * 1024
PROTECTED = {'scripts/buildkit.py', 'scripts/releasekit.py', 'scripts/store_package.py',
             'e2e/prepare_payload.py', '.github/workflows/store-package.yml', 'e2e/store_screenshot.py'}
SOURCE_JOBS = {'preflight','wasm','windows-editor','windows-cli','build','release','msix-install',
    'native-e2e (windows-2022)','native-e2e (windows-2025)','virtual-print (windows-2022)',
    'virtual-print (windows-2025)','browser-e2e (chromium)','browser-e2e (firefox)',
    'browser-e2e (webkit)','cleanup-transports'}


def require(value):
    if not value: raise ValueError('고정 보관 계약 또는 증거가 일치하지 않습니다')


def digest(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
def hexadecimal(value, size=64): return isinstance(value, str) and re.fullmatch('[0-9a-f]{'+str(size)+'}', value)


def ready(c):
    require(isinstance(c, dict) and 'UNSET' not in json.dumps(c) and c.get('repository') == 'ATLKR/OpenGeul')
    for key in ('sourceCommit', 'storeExecutionCommit'): require(hexadecimal(c.get(key), 40))
    for key in ('sourceRunId','sourceRunNumber','sourceRunAttempt','sourceReleaseId','storeRunId',
                'storeRunAttempt','storeArtifactId','storeArtifactBytes','archiveReleaseId'):
        require(type(c.get(key)) is int and c[key] > 0)
    require(c['sourceRunAttempt'] == c['storeRunAttempt'] == 1 and c['sourceReleaseId'] != c['archiveReleaseId'])
    require(isinstance(c.get('sourceTag'),str)
        and re.fullmatch(r'v[1-9][0-9]*\.[0-9]+\.[0-9]+-dev\.'+str(c['sourceRunNumber'])+r'\.1', c['sourceTag'])
        and c['archiveTag'] == 'store-package-'+c['sourceTag'][1:])
    for key in ('sourceAssetSnapshotSha256','preparedPlanSha256','runtimeSnapshotSha256','guiSha256',
                'sourceProvenanceSha256','storeArtifactSha256','approvedWebsiteDiffSha256'):
        require(hexadecimal(c.get(key)))
    require(set(c['protectedFiles']) == PROTECTED and all(hexadecimal(v) for v in c['protectedFiles'].values()))
    names=set(c['assets']);fixed={'AppxManifest.xml','OpenGeul-editor.png','SHA256SUMS.txt',
        'screenshot-provenance.json','source-provenance.json','store-provenance.json'}
    require(len(names) == 7 and fixed < names)
    package=next(iter(names-fixed))
    require(package=='OpenGeul_'+c['sourceTag'][1:].split('-dev.')[0]+'.0_x64_store-unsigned.msix')
    require(all(type(v['size']) is int and 0 < v['size'] <= LIMIT and hexadecimal(v['sha256']) for v in c['assets'].values()))
    require(sum(v['size'] for v in c['assets'].values()) <= LIMIT and c['storeArtifactBytes'] <= LIMIT+1024*1024)
    require(isinstance(c['approvedWebsiteDiff'], list) and digest(canonical(c['approvedWebsiteDiff'])) == c['approvedWebsiteDiffSha256'])


def git(root, *args):
    result=subprocess.run(['git', *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    require(result.returncode == 0 and len(result.stdout) <= 2*1024*1024)
    return result.stdout


def validate_git(root, c):
    before, after=c['sourceCommit'],c['storeExecutionCommit']
    git(root, 'merge-base', '--is-ancestor', before, after)
    rows=git(root, 'diff', '--no-renames', '--name-status', '-z', before, after).split(b'\0')
    require(rows[-1] == b'' and (len(rows)-1)%2 == 0)
    expected=c['approvedWebsiteDiff'];require(digest(canonical(expected)) == c['approvedWebsiteDiffSha256'])
    observed=[]
    for index in range(0,len(rows)-1,2):
        status,path=rows[index:index+2];path=path.decode('utf-8')
        require(status == b'M' and re.fullmatch(r'website/[A-Za-z0-9_./-]+',path)
                and all(p not in ('','.', '..') for p in path.split('/')))
        observed.append({'path':path,'beforeSha256':digest(git(root,'show',before+':'+path)),
                         'afterSha256':digest(git(root,'show',after+':'+path))})
    require(observed == sorted(expected,key=lambda row:row['path']))
    require(set(c['protectedFiles']) == PROTECTED)
    for path,sha in c['protectedFiles'].items():
        require(digest(git(root,'show',before+':'+path)) == sha
                and digest(git(root,'show',after+':'+path)) == sha)


def listing(api, path, key=None):
    rows=[];total=None
    for page in range(1,11):
        result=api('GET',ROOT+path+f'?per_page=100&page={page}');batch=result[key] if key else result
        require(isinstance(batch,list) and len(batch)<=100)
        if key:
            require(type(result.get('total_count')) is int)
            if total is None: total=result['total_count']
            require(total == result['total_count'])
        rows.extend(batch)
        if len(batch)<100:
            require(total is None or total==len(rows));require(len({r['id'] for r in rows}) == len(rows))
            return rows
    raise ValueError('완전한 페이지 목록을 확인할 수 없습니다')


def run_jobs(api,c,which):
    source=which=='source';prefix='source' if source else 'store'
    run_id=c[prefix+'RunId'];attempt=c[prefix+'RunAttempt'];head=c['sourceCommit' if source else 'storeExecutionCommit']
    run=api('GET',ROOT+f'actions/runs/{run_id}')
    require(run.get('id')==run_id and run.get('run_attempt')==attempt and run.get('head_sha')==head
        and run.get('head_branch')=='main' and run.get('path')=='.github/workflows/'+('msix.yml' if source else 'store-package.yml')
        and run.get('event')==('push' if source else 'workflow_dispatch') and run.get('status')=='completed'
        and run.get('conclusion')=='success' and run.get('repository',{}).get('full_name')=='ATLKR/OpenGeul'
        and run['repository'].get('private') is False)
    if source: require(run.get('run_number')==c['sourceRunNumber'])
    jobs=listing(api,f'actions/runs/{run_id}/attempts/{attempt}/jobs','jobs')
    for name in SOURCE_JOBS if source else {'package','verify-api'}:
        found=[j for j in jobs if j.get('name')==name];require(len(found)==1);j=found[0]
        require(j.get('run_id')==run_id and j.get('head_sha')==head and j.get('run_attempt',1)==attempt
                and j.get('status')=='completed' and j.get('conclusion')=='success')
    return run


def provenance(files,c):
    source=json.loads(files['source-provenance.json']);store=json.loads(files['store-provenance.json'])
    shot=json.loads(files['screenshot-provenance.json'])
    require(digest(files['source-provenance.json'])==c['sourceProvenanceSha256']
        and source.get('repository')=='ATLKR/OpenGeul' and source.get('commit')==c['sourceCommit']
        and source.get('runId')==str(c['sourceRunId']))
    require(store.get('sourceCommit')==c['sourceCommit'] and store.get('sourceRunId')==str(c['sourceRunId'])
        and store.get('sourceReleaseId')==c['sourceReleaseId'] and store.get('repackageCommit')==c['storeExecutionCommit']
        and store.get('repackageRunId')==str(c['storeRunId']) and store.get('unsigned') is True
        and store.get('storeCertified') is False and digest(canonical(store.get('runtimeSha256')))==c['runtimeSnapshotSha256']
        and store['runtimeSha256'].get('OpenGeul.exe')==c['guiSha256'])
    require(shot.get('sourceCommit')==c['sourceCommit'] and shot.get('runId')==str(c['storeRunId'])
            and shot.get('executableSha256')==c['guiSha256'])


def original_payload(raw,c):
    require(len(raw)==c['storeArtifactBytes'] and digest(raw)==c['storeArtifactSha256'])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=z.infolist();require(len(entries)==7 and {e.filename for e in entries}==set(c['assets']))
        for e in entries:
            require(not e.is_dir() and not stat.S_ISLNK(e.external_attr>>16) and not e.flag_bits&1
                    and e.file_size==c['assets'][e.filename]['size'])
        files={e.filename:z.read(e) for e in entries}
    for name,raw in files.items(): require(len(raw)==c['assets'][name]['size'] and digest(raw)==c['assets'][name]['sha256'])
    provenance(files,c)
    return files


def asset(row,name,c):
    require(name in c['assets'] and row.get('name')==name and type(row.get('id')) is int and row['id']>0
        and row.get('state')=='uploaded' and row.get('size')==c['assets'][name]['size']
        and row.get('digest')=='sha256:'+c['assets'][name]['sha256'])


def source_assets(api,c):
    release=api('GET',ROOT+f'releases/{c["sourceReleaseId"]}')
    require(release.get('id')==c['sourceReleaseId'] and release.get('tag_name')==c['sourceTag']
            and release.get('draft') is False and release.get('prerelease') is True)
    require(api('GET',ROOT+'commits/'+c['sourceTag']).get('sha')==c['sourceCommit'])
    rows=listing(api,f'releases/{c["sourceReleaseId"]}/assets')
    stable=[{k:r[k] for k in ('id','name','size','state','digest')} for r in rows]
    require(len(rows)==6 and digest(canonical(sorted(stable,key=lambda r:r['name'])))==c['sourceAssetSnapshotSha256'])


def archive_state(api,c):
    release=api('GET',ROOT+f'releases/{c["archiveReleaseId"]}')
    require(release.get('id')==c['archiveReleaseId'] and release.get('tag_name')==c['archiveTag']
        and release.get('draft') is True and release.get('prerelease') is True
        and release.get('target_commitish')==c['sourceCommit'])
    ref=api('GET',ROOT+'git/ref/tags/'+c['archiveTag'])
    if ref is not None: require(ref.get('object',{}).get('type')=='commit' and ref['object'].get('sha')==c['sourceCommit'])
    rows=listing(api,f'releases/{c["archiveReleaseId"]}/assets')
    require(len(rows)<=7 and len({r['name'] for r in rows})==len(rows))
    for row in rows: asset(row,row['name'],c)
    return rows


def transfer(api,download,root,c,plan_raw):
    ready(c)
    require(digest(plan_raw)==c['preparedPlanSha256']);plan=json.loads(plan_raw)
    expected={'repository':c['repository'],'archiveTag':c['archiveTag'],'targetCommit':c['sourceCommit'],
        'sourceRunId':c['sourceRunId'],'storeRunId':c['storeRunId'],'storeArtifactId':c['storeArtifactId'],
        'sourceReleaseId':c['sourceReleaseId'],'sourceAssetSnapshotSha256':c['sourceAssetSnapshotSha256'],'assets':c['assets']}
    require(all(plan.get(k)==v for k,v in expected.items()) and plan.get('decision') in ('create-draft','reuse-draft'))
    validate_git(root,c)
    run_jobs(api,c,'source');run_jobs(api,c,'store')
    a=api('GET',ROOT+f'actions/artifacts/{c["storeArtifactId"]}')
    require(a.get('id')==c['storeArtifactId'] and a.get('expired') is False
        and a.get('name')==f'opengeul-store-{c["storeRunId"]}' and a.get('size_in_bytes')==c['storeArtifactBytes']
        and a.get('digest')=='sha256:'+c['storeArtifactSha256'] and a.get('workflow_run',{}).get('id')==c['storeRunId']
        and a['workflow_run'].get('head_sha')==c['storeExecutionCommit'] and a['workflow_run'].get('head_branch')=='main')
    files=original_payload(download(a),c)
    source_assets(api,c);archive_state(api,c)
    for name in sorted(files):
        source_assets(api,c);present={r['name'] for r in archive_state(api,c)}
        if name not in present:
            require(digest(files[name])==c['assets'][name]['sha256'])
            path='https://uploads.github.com/'+ROOT+f'releases/{c["archiveReleaseId"]}/assets?name='+quote(name,safe='')
            asset(api('POST',path,files[name]),name,c)
    source_assets(api,c);run_jobs(api,c,'source');run_jobs(api,c,'store')
    rows=archive_state(api,c);require(len(rows)==7)
    return {'archiveId':c['archiveReleaseId'],'published':False,'sourceQualified':False,
            'diagnosticOnly':True,'assets':[{k:r[k] for k in ('id','name','size','state','digest')} for r in rows]}


def main():
    require(ROOT_EXECUTION_AUTHORIZED and hexadecimal(CONTRACT_SHA256))
    raw=CONTRACT.read_bytes();require(len(raw)<=64*1024 and digest(raw)==CONTRACT_SHA256)
    c=strict_json(raw);ready(c)
    event_raw=Path(os.environ['GITHUB_EVENT_PATH']).read_bytes();require(len(event_raw)<=2*1024*1024)
    context(os.environ,strict_json(event_raw))
    plan=PLAN.read_bytes();require(len(plan)<=2*1024*1024)
    for path in PROTECTED- {'.github/workflows/store-package.yml'}:
        require(digest((BASE/path).read_bytes())==c['protectedFiles'][path])
    transport=Transport(os.environ['GH_TOKEN'],c)
    return transfer(transport,transport.download,BASE,c,plan)


def context(env,event):
    expected={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'ATLKR/OpenGeul',
        'GITHUB_ACTOR':'ATLKR','GITHUB_TRIGGERING_ACTOR':'ATLKR','GITHUB_EVENT_NAME':'workflow_dispatch',
        'GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':'refs/heads/diagnostic/archive-next-conditional',
        'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/archive-next-conditional'}
    require(all(env.get(k)==v for k,v in expected.items())
        and re.fullmatch('[1-9][0-9]*',env.get('GITHUB_RUN_ID',''))
        and env.get('GH_TOKEN') and env.get('GITHUB_TOKEN')
        and hmac.compare_digest(env['GH_TOKEN'],env['GITHUB_TOKEN']))
    require(isinstance(event,dict) and event.get('repository',{}).get('full_name')=='ATLKR/OpenGeul'
            and event['repository'].get('private') is False and event.get('inputs',{})=={})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args): return None


def strict_json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs: require(key not in result);result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique)


class Transport:
    def __init__(self,token,c,opener=None):
        ready(c);require(isinstance(token,str) and token and '\n' not in token and '\r' not in token)
        self.c=c;self.token=token;self.opener=opener or urllib.request.build_opener(NoRedirect)
        self.ref=ROOT+'git/ref/tags/'+c['archiveTag']
        self.gets={ROOT+'commits/'+c['sourceTag'],self.ref,ROOT+f'actions/artifacts/{c["storeArtifactId"]}'}
        for which in ('source','store'):
            run=c[which+'RunId'];attempt=c[which+'RunAttempt'];self.gets.add(ROOT+f'actions/runs/{run}')
            for page in range(1,11): self.gets.add(ROOT+f'actions/runs/{run}/attempts/{attempt}/jobs?per_page=100&page={page}')
        for release in (c['sourceReleaseId'],c['archiveReleaseId']):
            self.gets.add(ROOT+f'releases/{release}')
            for page in range(1,11): self.gets.add(ROOT+f'releases/{release}/assets?per_page=100&page={page}')
        self.uploads={'https://uploads.github.com/'+ROOT+f'releases/{c["archiveReleaseId"]}/assets?name='+quote(n,safe=''):n for n in c['assets']}

    def request(self,url,data=None,method='GET',authenticated=True):
        headers={'User-Agent':'OpenGeul-fixed-archive','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
        if authenticated: headers['Authorization']='Bearer '+self.token
        if data is not None: headers['Content-Type']='application/octet-stream'
        return urllib.request.Request(url,data=data,method=method,headers=headers)

    def __call__(self,method,path,data=None):
        require(method=='GET' and path in self.gets and data is None or method=='POST' and path in self.uploads)
        if method=='POST':
            expected=self.c['assets'][self.uploads[path]]
            require(type(data) is bytes and len(data)==expected['size'] and digest(data)==expected['sha256'])
        url=path if method=='POST' else 'https://api.github.com/'+path
        try:
            with self.opener.open(self.request(url,data,method),timeout=60) as response:
                require(response.status==(201 if method=='POST' else 200))
                raw=response.read(2*1024*1024+1);require(len(raw)<=2*1024*1024)
                return strict_json(raw)
        except urllib.error.HTTPError as error:
            if method=='GET' and path==self.ref and error.code==404: return None
            raise RuntimeError('고정 보관 API 요청에 실패했습니다') from None
        except Exception:
            raise RuntimeError('고정 보관 API 요청에 실패했습니다') from None

    def download(self,artifact):
        require(artifact.get('id')==self.c['storeArtifactId'])
        try:
            url='https://api.github.com/'+ROOT+f'actions/artifacts/{self.c["storeArtifactId"]}/zip'
            try:
                with self.opener.open(self.request(url),timeout=60): require(False)
            except urllib.error.HTTPError as error:
                require(error.code==302);location=error.headers.get('Location','')
            parsed=urllib.parse.urlsplit(location)
            require(len(location)<=8192 and not any(ord(ch)<32 for ch in location) and parsed.scheme=='https'
                and parsed.hostname and parsed.hostname.endswith('.blob.core.windows.net')
                and parsed.port in (None,443) and not parsed.username and not parsed.password and not parsed.fragment)
            with self.opener.open(self.request(location,authenticated=False),timeout=60) as response:
                require(response.status==200);raw=response.read(self.c['storeArtifactBytes']+1)
                require(len(raw)==self.c['storeArtifactBytes'] and digest(raw)==self.c['storeArtifactSha256'])
                return raw
        except Exception:
            raise RuntimeError('고정 원본 artifact 전송에 실패했습니다') from None


def failure_details(error):
    """원문·locals·외부 경로 없이 이 파일의 실패 위치만 기록한다."""
    allowed = {'ValueError', 'RuntimeError', 'KeyError', 'FileNotFoundError',
        'PermissionError', 'UnicodeDecodeError', 'JSONDecodeError', 'BadZipFile',
        'TimeoutExpired', 'OSError'}
    name = type(error).__name__
    frames = []
    trace = error.__traceback__
    while trace is not None and len(frames) < 12:
        code = trace.tb_frame.f_code
        if code.co_filename == __file__ and re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', code.co_name):
            frames.append({'function': code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    return {'exceptionType': name if name in allowed else 'Exception', 'frames': frames}


def context_diagnostics(env, event):
    """정책을 변경하지 않고 고정 키의 일치 여부와 입력 형태만 보고한다."""
    expected={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'ATLKR/OpenGeul',
        'GITHUB_ACTOR':'ATLKR','GITHUB_TRIGGERING_ACTOR':'ATLKR','GITHUB_EVENT_NAME':'workflow_dispatch',
        'GITHUB_RUN_ATTEMPT':'1','GITHUB_REF':'refs/heads/diagnostic/archive-next-conditional',
        'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/archive-next-conditional'}
    event = event if isinstance(event, dict) else {}
    repository = event.get('repository')
    repository = repository if isinstance(repository, dict) else {}
    shape = ('missing' if 'inputs' not in event else 'null' if event['inputs'] is None else
        'empty_object' if isinstance(event['inputs'], dict) and not event['inputs'] else
        'nonempty_object' if isinstance(event['inputs'], dict) else 'other')
    return {'environmentMatches': {key: env.get(key) == value for key, value in expected.items()},
        'runIdValid': bool(re.fullmatch('[1-9][0-9]*', env.get('GITHUB_RUN_ID', ''))),
        'tokensMatch': bool(env.get('GH_TOKEN') and env.get('GITHUB_TOKEN')
            and hmac.compare_digest(env['GH_TOKEN'], env['GITHUB_TOKEN'])),
        'repositoryMatches': repository.get('full_name') == 'ATLKR/OpenGeul',
        'repositoryPublic': repository.get('private') is False, 'inputsShape': shape}


def failure_receipt(error):
    result = {'status': 'failed', 'published': False, 'sourceQualified': False,
        'diagnosticOnly': True, 'failure': failure_details(error)}
    try:
        with Path(os.environ['GITHUB_EVENT_PATH']).open('rb') as stream:
            raw = stream.read(2*1024*1024+1)
        require(len(raw) <= 2*1024*1024)
        result['context'] = context_diagnostics(os.environ, strict_json(raw))
    except Exception:
        result['contextUnavailable'] = True
    return result


if __name__=='__main__':
    try:
        result=main()
        Path('archive-next-transfer-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        result = failure_receipt(error)
        Path('archive-next-transfer-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False),file=sys.stderr)
        print('보관 전송 준비 상태: 미확정 핀 또는 미연결 실행 경로로 거부했습니다.',file=sys.stderr)
        sys.exit(1)
