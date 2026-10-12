"""같은 소스 실행의 공개 QA 원본만 MCP 설치 시험으로 전송한다.

생성기·암호 알고리즘을 바꾸지 않는다. GitHub artifact의 서버 SHA/현재 attempt/
성공 job/API 권한 검증은 호출자가 먼저 수행해야 하며 release 자산은 추가하지 않는다.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'e2e'),str(ROOT/'scripts')]
from mcp_worker import password_inputs,strict_json,NORMAL_TEXT
from hwpx_oracle import inspect_hwpx
from wasm_artifacts import expected as wasm_expected,FILES as WASM_FILES

MAX_BYTES=16*1024*1024
MAX_FILE=4*1024*1024
MAX_JSON=64*1024
PASSWORD='OpenGeul-native-123456'  # 공개 합성 QA 값. 개인 암호는 거부한다.
TEXT='OpenGeul owned encrypted native QA 2026-10-11 — 한글 & <xml> Ω 123'
PASSWORD_FILES=frozenset(['manifest.json','independent-verification.json','prior.hwpx','protected.hwp','protected.hwpx']+
                         [f'{a}-reopened-plain.{b}' for a in ('hwp','hwpx') for b in ('hwp','hwpx')])
PAYLOAD_FILES=frozenset({'e2e-fixtures/basic.hwpx','wasm-provenance.json'}|
                        {'password-fixtures/'+name for name in PASSWORD_FILES})
MANIFEST='MCP_FIXTURES.json'

def require(condition,message):
    if not condition:raise ValueError(message)

def safe_path(path):
    path=Path(path)
    require('..' not in path.parts,'QA 경로의 상위 디렉터리 별칭을 허용하지 않습니다')
    path=path.absolute()
    for part in (path,*path.parents):
        if part.exists() or part.is_symlink():
            state=part.lstat()
            require(not stat.S_ISLNK(state.st_mode) and not getattr(state,'st_file_attributes',0)&0x400,
                    'QA 입력·출력의 symlink/reparse를 허용하지 않습니다')
    return path

def read(path,limit=MAX_FILE):
    path=safe_path(path);state=path.stat()
    require(stat.S_ISREG(state.st_mode) and 0<state.st_size<=limit,'QA 원본은 크기가 제한된 일반 파일이어야 합니다')
    with path.open('rb') as stream:data=stream.read(limit+1)
    require(len(data)==state.st_size and len(data)<=limit,'QA 원본이 읽는 동안 변경되었습니다')
    return data

def record(data):return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def sha(path):return hashlib.sha256(read(path)).hexdigest()
def json_file(path):return strict_json(read(path,MAX_JSON))
def exact(value,keys):require(isinstance(value,dict) and set(value)==set(keys),'QA JSON 스키마에 알 수 없는 필드가 있습니다')
def hash_record(value):
    exact(value,('bytes','sha256'))
    require(type(value['bytes']) is int and 0<value['bytes']<=MAX_FILE
            and isinstance(value['sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['sha256']),'QA 파일 SHA/크기가 올바르지 않습니다')

def identity(binding):
    exact(binding,('repository','sourceCommit','sourceRun','runAttempt'))
    require(binding['repository']=='ATLKR/OpenGeul' and isinstance(binding['sourceCommit'],str)
            and re.fullmatch('[0-9a-f]{40}',binding['sourceCommit'])
            and all(isinstance(binding[k],str) and re.fullmatch('[1-9][0-9]{0,19}',binding[k]) for k in ('sourceRun','runAttempt')),
            'QA source/run/attempt 바인딩이 없습니다')

def wasm_proof(value):
    exact(value,('upstream','namespaceHelper','namespacePatcher','artifacts','generator'))
    require(all(value[k]==v for k,v in wasm_expected().items())
            and value['generator']=='wasm-pack 0.14.0 --target web --release --no-opt','QA WASM 출처가 현재 소스와 다릅니다')
    exact(value['artifacts'],WASM_FILES)
    require(all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in value['artifacts'].values()),'QA WASM 파일 SHA가 올바르지 않습니다')

def encryption(format):
    if format=='hwp':return {'container':'CFB','headerBytes':256,'majorVersion':5,'encrypted':True,'compressed':True,'encryptVersion':4}
    return {'container':'ZIP','algorithm':'ODF AES-256-CBC','kdf':'PBKDF2','keyBytes':32,'iterations':1024,'saltBytes':16,'ivBytes':16,'checksum':'SHA-256-1K','encryptedParts':['Contents/header.xml','Contents/section0.xml','Preview/PrvText.txt','Preview/PrvImage.png','settings.xml']}

def profile(basic,password,wasm):
    """원래 생성 manifest를 유지하고 알려진 공개 QA 값·모든 파일 해시를 확인한다."""
    value=json_file(password/'manifest.json')
    exact(value,('schemaVersion','password','expectedText','priorExpectedText','priorPath','prior','fixtures','roundtrips','engine','generation','independentVerification'))
    require(type(value['schemaVersion']) is int and value['schemaVersion']==1 and value['password']==PASSWORD
            and value['expectedText']==TEXT and value['priorExpectedText']==NORMAL_TEXT and value['priorPath']=='prior.hwpx',
            '개인 문서·개인 암호를 QA artifact에 포함하지 않습니다')
    prior={'container':'ZIP','encrypted':False,'text':NORMAL_TEXT,'sections':1}
    generation=value['generation'];exact(generation,('source','textOwnership','generatorSha256','verifierSha256','priorInspection'))
    require(generation['source']=='Public WASM createEmpty/createBlankDocument/insertText/password export APIs'
            and generation['textOwnership']=='Task-authored content generated via the library bundled blank template; no user document, external sample, or font program input'
            and generation['priorInspection']==prior,'QA 생성기의 공개 합성 입력 계약이 다릅니다')
    exact(value['engine'],('wasmSha256','jsSha256','provenance','qualification'))
    require(value['engine']['provenance']==wasm,'원본 QA 생성 WASM과 최종 소스 WASM이 다릅니다')
    require(value['independentVerification']=={'passed':True,'path':'independent-verification.json'},'독립 검증이 완료된 원본 QA 입력이 필요합니다')
    # 기존 MCP password guard의 upstream/helper/generator/verifier/암호 파일 검증을 그대로 재사용한다.
    password_inputs(password)
    hash_record(value['prior']);require(record(read(password/'prior.hwpx'))==value['prior'],'QA prior 원본 바이트가 다릅니다')
    require(read(basic)==read(password/'prior.hwpx') and inspect_hwpx(read(basic),max_bytes=MAX_FILE)['text']==NORMAL_TEXT,
            '기본 합성 문서와 암호 생성기의 원본 prior 문서가 다릅니다')
    require(isinstance(value['fixtures'],list) and len(value['fixtures'])==2,'암호 원본 두 형식이 필요합니다')
    for row in value['fixtures']:
        exact(row,('format','path','sha256','bytes','normalOpenRejected','wrongPasswordRejected','correctPasswordTextVerified','normalError','wrongError','pageCount','encryption'))
        format=row['format'];require(format in ('hwp','hwpx') and row['path']=='protected.'+format,'암호 QA 파일 이름이 다릅니다')
        hash_record({k:row[k] for k in ('bytes','sha256')})
        require(type(row['pageCount']) is int and row['pageCount']==1 and row['encryption']==encryption(format)
                and row['normalError']=='유효하지 않은 파일: 비밀번호가 필요한 암호 문서입니다 (parse_document_with_password 또는 parse_hwp_with_password 로 비밀번호를 전달하세요)'
                and row['wrongError']=='유효하지 않은 파일: '+('암호 오류' if format=='hwp' else 'HWPX 오류')+': 비밀번호가 일치하지 않거나 암호화 데이터가 손상되었습니다',
                '암호 QA metadata는 원래 공개 생성기의 고정 결과여야 합니다')
    rows=value['roundtrips'];require(isinstance(rows,list) and len(rows)==4,'QA 평문 왕복 네 파일이 필요합니다');seen=set();inspections=[]
    for row in rows:
        exact(row,('inputFormat','outputFormat','path','bytes','sha256'));a,b=row['inputFormat'],row['outputFormat']
        require(a in ('hwp','hwpx') and b in ('hwp','hwpx') and (a,b) not in seen and row['path']==f'{a}-reopened-plain.{b}',
                'QA 평문 왕복 파일 경로·형식이 다릅니다');seen.add((a,b));hash_record({k:row[k] for k in ('bytes','sha256')})
        require(record(read(password/row['path']))=={k:row[k] for k in ('bytes','sha256')},'QA 왕복 원본 바이트가 다릅니다')
        if b=='hwpx':require(inspect_hwpx(read(password/row['path']),max_bytes=MAX_FILE)['text']==TEXT,'QA 평문은 공개 합성 문서여야 합니다')
        inspection={'container':'CFB','headerBytes':256,'majorVersion':5,'encrypted':False,'compressed':True,'encryptVersion':0} if b=='hwp' else {'container':'ZIP','encrypted':False,'text':TEXT,'sections':1}
        inspections.append({'inputFormat':a,'outputFormat':b,'inspection':inspection})
    require(json_file(password/'independent-verification.json')=={'fixtures':{a:encryption(a) for a in ('hwp','hwpx')},'plaintextRoundtrips':inspections,'prior':prior},
            '원본 독립 검증 metadata가 암호·왕복 QA 입력과 다릅니다')

def inventory(folder,names):
    folder=safe_path(folder);require(folder.is_dir(),'QA 원본 디렉터리가 없습니다')
    files={};directories=set()
    for path in folder.rglob('*'):
        safe_path(path);relative=path.relative_to(folder).as_posix()
        if path.is_dir():directories.add(relative);continue
        require(relative in names and path.is_file(),'QA 파일 목록에 허용되지 않은 파일이 있습니다')
        files[relative]=path
    require(set(files)==set(names) and directories<={'e2e-fixtures','password-fixtures'},'QA 원본 파일 목록이 정확하지 않습니다')
    require(sum(path.stat().st_size for path in files.values())<=MAX_BYTES,'QA 원본 총 크기 상한을 초과했습니다')
    return files

def verify(folder,binding,wasm):
    identity(binding);wasm_proof(wasm);files=inventory(folder,PAYLOAD_FILES|{MANIFEST});proof=json_file(files[MANIFEST])
    exact(proof,('formatVersion','repository','sourceCommit','sourceRun','runAttempt','artifactName','producerJobName','helperSha256','publicQaOnly','fullSourceQualified','files'))
    require(type(proof['formatVersion']) is int and proof['formatVersion']==1
            and all(proof[k]==v for k,v in binding.items()) and proof['artifactName']=='opengeul-mcp-fixtures-'+binding['sourceRun']
            and proof['producerJobName']=='native-e2e (windows-2025)' and proof['helperSha256']==sha(Path(__file__))
            and proof['publicQaOnly'] is True and proof['fullSourceQualified'] is False,'QA 전송 source/job/attempt 계약이 다릅니다')
    exact(proof['files'],PAYLOAD_FILES)
    for name,expected_record in proof['files'].items():
        hash_record(expected_record);require(record(read(files[name],MAX_JSON if name.endswith('.json') else MAX_FILE))==expected_record,'QA 전송 원본 SHA/크기가 다릅니다')
    actual_wasm=json_file(files['wasm-provenance.json']);require(actual_wasm==wasm,'QA artifact WASM과 최종 package의 출처가 다릅니다')
    profile(files['e2e-fixtures/basic.hwpx'],folder/'password-fixtures',wasm)
    return proof

def stage(fixtures,password,wasm_manifest,output,binding):
    identity(binding);output=safe_path(output);fixtures=safe_path(fixtures);password=safe_path(password);wasm_manifest=safe_path(wasm_manifest)
    require(not output.exists() and all(output not in path.parents and path not in output.parents and output!=path for path in (fixtures,password,wasm_manifest)),
            'QA 기존 출력·원본 안·원본 위에는 쓰지 않습니다')
    require(output.parent.is_dir(),'QA 출력 부모 디렉터리가 필요합니다')
    original=inventory(password,PASSWORD_FILES);require(fixtures.is_dir(),'QA 기본 입력 디렉터리가 없습니다')
    basic_names=[path.name for path in fixtures.iterdir() if path.name.casefold()=='basic.hwpx']
    require(basic_names==['basic.hwpx'],'QA 기본 파일은 정확한 basename 하나여야 합니다');basic=fixtures/'basic.hwpx'
    files={'e2e-fixtures/basic.hwpx':basic,'wasm-provenance.json':wasm_manifest,**{'password-fixtures/'+name:path for name,path in original.items()}}
    captured={name:record(read(path,MAX_JSON if name.endswith('.json') else MAX_FILE)) for name,path in files.items()}
    require(sum(r['bytes'] for r in captured.values())<=MAX_BYTES,'QA 원본 총 크기 상한을 초과했습니다')
    wasm=json_file(wasm_manifest);wasm_proof(wasm);profile(basic,password,wasm)
    proof={'formatVersion':1,**binding,'artifactName':'opengeul-mcp-fixtures-'+binding['sourceRun'],'producerJobName':'native-e2e (windows-2025)',
           'helperSha256':sha(Path(__file__)),'publicQaOnly':True,'fullSourceQualified':False,'files':captured}
    with tempfile.TemporaryDirectory(prefix='.opengeul-mcp-qa-',dir=output.parent) as temporary:
        staged=Path(temporary)/'payload';staged.mkdir()
        for name,path in files.items():
            target=staged/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        (staged/MANIFEST).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        verify(staged,binding,wasm);require(not output.exists(),'QA 출력이 검증 중 생성되어 덮어쓰지 않습니다');staged.rename(output)
    return proof

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='mode',required=True)
    s=sub.add_parser('stage');s.add_argument('--fixtures',type=Path,required=True);s.add_argument('--password-fixtures',type=Path,required=True);s.add_argument('--output',type=Path,required=True)
    v=sub.add_parser('verify');v.add_argument('folder',type=Path)
    for item in (s,v):
        item.add_argument('--wasm-provenance',type=Path,required=True);item.add_argument('--source-commit',required=True);item.add_argument('--source-run',required=True);item.add_argument('--source-attempt',required=True)
    a=p.parse_args();binding={'repository':'ATLKR/OpenGeul','sourceCommit':a.source_commit,'sourceRun':a.source_run,'runAttempt':a.source_attempt}
    if a.mode=='stage':
        require(os.getenv('GITHUB_REPOSITORY')==binding['repository'] and os.getenv('GITHUB_SHA')==binding['sourceCommit']
                and os.getenv('GITHUB_RUN_ID')==binding['sourceRun'] and os.getenv('GITHUB_RUN_ATTEMPT')==binding['runAttempt']
                and os.getenv('GITHUB_JOB')=='native-e2e' and os.getenv('RUNNER_OS')=='Windows' and os.getenv('RUNNER_ARCH')=='X64',
                'native-e2e windows-2025 성공 단계의 현재 실행만 QA 원본을 준비합니다')
        proof=stage(a.fixtures,a.password_fixtures,a.wasm_provenance,a.output,binding)
    else:proof=verify(a.folder,binding,json_file(a.wasm_provenance))
    print(json.dumps({'passed':True,'sourceCommit':proof['sourceCommit'],'sourceRun':proof['sourceRun'],'runAttempt':proof['runAttempt'],'files':len(proof['files']),'publicQaOnly':True,'fullSourceQualified':False}))

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('같은 소스 실행의 공개 MCP QA 원본 검증에 실패했습니다. 기존 입력은 보존합니다.') from None
