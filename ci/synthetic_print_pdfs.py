"""완료한 공개 CI의 고정 합성 인쇄 PDF 7개만 별도로 하루 보존한다.

일반 증거 whitelist·인쇄 검사·기준 mask를 바꾸지 않으며 문서/키/PNG를 수집하지 않는다.
이 manifest는 원본 전송 증거이고 Source/Store 검증 완료를 뜻하지 않는다.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,stat,sys,tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from windows_components import regular,sha,pe_machine
from wasm_artifacts import FILES as WASM_FILES,expected as wasm_expected
CASES=('table--300','table-0','table-600','multipage','basic-hwp','basic-hwpx','page-range','cancel')
FIXTURES={
 'table--300':'print-fixtures/print-table--300.hwpx','table-0':'print-fixtures/print-table-0.hwpx',
 'table-600':'print-fixtures/print-table-600.hwpx','multipage':'print-fixtures/print-multipage.hwpx',
 'page-range':'print-fixtures/print-multipage.hwpx','basic-hwp':'inputs/e2e-fixtures/basic.hwp',
 'basic-hwpx':'inputs/e2e-fixtures/basic.hwpx','cancel':'inputs/e2e-fixtures/basic.hwpx'}
LIMIT=8*1024*1024
JSON_CAP=128*1024

def require(value,message):
 if not value:raise ValueError(message)

def read(path,cap):
 regular(path);require(0<path.stat().st_size<=cap,'합성 증거 파일 크기 상한')
 data=path.read_bytes();require(0<len(data)<=cap,'합성 증거 읽기 크기 상한');return data

def read_json(path):
 def pairs(items):
  result={}
  for key,value in items:require(key not in result,'중복 JSON 키');result[key]=value
  return result
 raw=read(path,JSON_CAP)
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('비정규 JSON 숫자'))),hashlib.sha256(raw).hexdigest()

def context(workspace,env,os_name):
 require(os_name in ('windows-2022','windows-2025','windows-11-arm'),'허용하지 않은 인쇄 실행기')
 info=workspace.lstat();require(stat.S_ISDIR(info.st_mode) and not workspace.is_symlink() and not getattr(info,'st_file_attributes',0)&0x400,'실행 workspace 링크 금지')
 require(Path(env.get('GITHUB_WORKSPACE',''))==workspace,'현재 실행 workspace 불일치')
 require(env.get('GITHUB_REPOSITORY')=='ATLKR/OpenGeul' and env.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch'),'현재 소유 공개 Source 실행만 수집')
 event,_=read_json(Path(env['GITHUB_EVENT_PATH']));require(event.get('repository',{}).get('private') is False and event['repository'].get('full_name')=='ATLKR/OpenGeul','명시적인 현재 공개 저장소 이벤트 필요')
 require(re.fullmatch('[0-9a-f]{40}',env.get('GITHUB_SHA','')) and all(re.fullmatch('[1-9][0-9]*',env.get(k,'')) for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT')),'현재 소스·실행·시도 형식')
 require(re.fullmatch(r'refs/(heads|tags)/[A-Za-z0-9._/-]{1,180}',env.get('GITHUB_REF','')),'현재 Source ref 형식')
 arm=os_name=='windows-11-arm';job='virtual-print-arm64' if arm else 'virtual-print';require(env.get('GITHUB_JOB')==job,'현재 인쇄 작업·아키텍처 불일치')
 return {'repository':env['GITHUB_REPOSITORY'],'sourceCommit':env['GITHUB_SHA'],'sourceRun':env['GITHUB_RUN_ID'],'runAttempt':env['GITHUB_RUN_ATTEMPT'],'event':env['GITHUB_EVENT_NAME'],'ref':env['GITHUB_REF'],'job':job,'os':os_name,'architecture':'arm64' if arm else 'x64'}

def fixed_wasm(workspace):
 folder=workspace/'wasm-input';value,metadata_hash=read_json(folder/'OPEN_GEUL_WASM.json')
 require(set(value)=={'upstream','namespaceHelper','namespacePatcher','artifacts','generator'} and all(value.get(k)==v for k,v in wasm_expected().items()),'현재 pin·namespace 소스의 WASM provenance 필요')
 require(value['generator']=='wasm-pack 0.14.0 --target web --release --no-opt' and type(value['artifacts']) is dict and set(value['artifacts'])==set(WASM_FILES),'기존 WASM 생성 명령·파일6개 필요')
 used=0
 for name in WASM_FILES:
  path=folder/name;regular(path);size=path.stat().st_size;used+=size
  require(0<size<=32*1024*1024 and used<=32*1024*1024 and sha(path)==value['artifacts'][name],'현재 실제 WASM 파일6개 hash·상한 일치 필요')
 with (folder/'rhwp_bg.wasm').open('rb') as stream:require(stream.read(8)==b'\0asm\1\0\0\0','실제 WASM 형식 필요')
 package,_=read_json(folder/'package.json');require(package.get('version')==value['upstream']['rhwp']['version'],'실제 WASM 버전 일치 필요')
 return {'metadataSha256':metadata_hash,**value}

def collect(workspace,env,os_name):
 workspace=Path(workspace);binding=context(workspace,env,os_name);source=workspace/'print-evidence';destination=workspace/'synthetic-pdf-evidence'
 require(not destination.exists() and not destination.is_symlink(),'기존 합성 PDF 증거 덮어쓰기 금지')
 executable=workspace/'runtime/OpenGeul.exe';regular(executable);editor_size=executable.stat().st_size;require(0<editor_size<=96*1024*1024,'실제 편집기 크기 상한');editor_sha=sha(executable)
 with executable.open('rb') as stream:pe_machine(stream.read(4096),binding['architecture'])
 wasm=fixed_wasm(workspace)
 summary,summary_hash=read_json(source/'summary.json')
 require(all(type(summary.get(k)) is int for k in ('tests','failures','skipped')) and (summary.get('tests'),summary.get('failures'),summary.get('skipped'))==(8,0,0),'원래 8개 인쇄 사례 전체 성공 필요')
 rows=summary.get('results');require(type(rows) is list and len(rows)==8 and {r.get('name') for r in rows}==set(CASES) and all(r.get('passed') is True for r in rows),'알려진 인쇄 사례 8개 각각 실제 PASS 필요')
 junit_raw=read(source/'junit.xml',JSON_CAP);xml=ET.fromstring(junit_raw)
 require(xml.tag=='testsuite' and xml.attrib=={'name':'virtual-print','tests':'8','failures':'0','skipped':'0'} and len(xml)==8 and {r.attrib.get('name') for r in xml}==set(CASES) and all(r.tag=='testcase' and len(r)==0 for r in xml),'원래 JUnit 인쇄 사례 전체 성공 일치 필요')
 machine=0xaa64 if binding['architecture']=='arm64' else 0x8664;pdfs=[];cancel=None;used=0
 native_helper=sha(ROOT/'e2e/native_architecture.py');editor_hashes=set()
 for case in CASES:
  folder=source/case;runtime,runtime_hash=read_json(folder/'session/runtime.json');preserved,preserved_hash=read_json(folder/'source-preservation.json');result,result_hash=read_json(folder/'result.json')
  native=runtime.get('nativeArchitecture',{});require(all(type(native.get(k)) is int for k in ('processMachine','peMachine','nativeMachine')) and native.get('helperSha256')==native_helper and (native.get('sourceCommit'),native.get('sourceRun'),native.get('runAttempt'),native.get('architecture'),native.get('processMachine'),native.get('peMachine'),native.get('nativeMachine'))==(binding['sourceCommit'],binding['sourceRun'],binding['runAttempt'],binding['architecture'],0,machine,machine) and native.get('native') is True and runtime.get('mode')=='native','현재 source/run/a1 네이티브 인쇄 실행 필요')
  require(type(native.get('processId')) is int and native['processId']>0 and native.get('runningAtInspection') is True and native.get('sha256')==runtime.get('executableSha256')==editor_sha and type(native.get('bytes')) is int and native['bytes']==editor_size and type(native.get('imagePath')) is str and Path(native['imagePath']).resolve()==executable.resolve(),'현재 실제 제품 경로·실행 PID·bytes·fingerprint 일치 필요');editor_hashes.add(native['sha256'])
  fixture=workspace/FIXTURES[case];regular(fixture);require(0<fixture.stat().st_size<=LIMIT,'합성 입력 크기 상한');fixture_hash=sha(fixture);case_source=folder/fixture.name;regular(case_source);require(case_source.stat().st_size==fixture.stat().st_size and sha(case_source)==fixture_hash,'현재 사례 원본 복사와 생성 합성 입력 불일치')
  require(preserved.get('unchanged') is True and preserved.get('before')==preserved.get('after')==runtime.get('fixtureSha256')==result.get('sourceSha256')==fixture_hash,'고정 생성 합성 입력·원본 보존·실행 hash 일치 필요')
  metadata={'runtimeSha256':runtime_hash,'sourcePreservationSha256':preserved_hash,'resultSha256':result_hash}
  pdf=folder/'printed.pdf'
  if case=='cancel':
   require(not pdf.exists() and not pdf.is_symlink() and result.get('cancelled') is True and result.get('jobs')==[],'취소 사례는 실제 PDF·스풀 산출물이 없어야 함')
   cancel={'case':case,'pdfAbsent':True,'sourceSha256':fixture_hash,**metadata};continue
  inspection,inspection_hash=read_json(folder/'pdf-check/inspection.json');checks=inspection.get('checks');pages=2 if case=='multipage' else 1
  require(inspection.get('mode')=='reviewed-raster-fingerprint' and type(checks) is list and len(checks)==pages and [r.get('page') for r in checks]==list(range(1,pages+1)),'기존 전체 페이지 원본 검사 기록 필요')
  require(all(result.get(key)==inspection.get(key) for key in ('sha256','mode','checks')),'기존 PDF 결과·검사 원본 일치 필요')
  data=read(pdf,LIMIT);require(data.startswith(b'%PDF-') and data.rstrip().endswith(b'%%EOF'),'완성된 PDF 원본 형식 필요');fingerprint=hashlib.sha256(data).hexdigest()
  require(inspection.get('sha256')==fingerprint,'원본 PDF 바이트가 기존 검사 SHA와 달라짐')
  used+=len(data);require(used<=LIMIT-64*1024,'합성 PDF 전체 8 MiB 상한')
  pdfs.append({'case':case,'path':case+'/printed.pdf','bytes':len(data),'sha256':fingerprint,'pages':pages,'sourceSha256':fixture_hash,'fixturePath':FIXTURES[case],'editorSha256':native['sha256'],'inspectionSha256':inspection_hash,**metadata})
 require(len(editor_hashes)==1 and len(pdfs)==7 and sum(r['pages'] for r in pdfs)==8 and cancel is not None,'원래 PDF7개·인쇄8페이지·취소1개 필요')
 manifest={'formatVersion':1,**binding,'scope':'공개 CI의 고정 생성 합성 인쇄 PDF 원본만; 문서/키/PNG/폰트 원파일 수집 없음','limitBytes':LIMIT,'pdfCount':7,'printedPages':8,'caseCount':8,'pdfs':pdfs,'cancel':cancel,'summarySha256':summary_hash,'junitSha256':hashlib.sha256(junit_raw).hexdigest(),'wasmSource':wasm,'generatorSourceHashes':{name:sha(ROOT/name) for name in ('e2e/generate-fixtures.rs','e2e/table_height.mjs','e2e/table_height_fixtures.py','e2e/print_fixtures.py','e2e/verify_print_fixtures.mjs')},'fixtureGenerationEvidenceScope':'기존 Source 작업의 고정 생성 경로·현재 generator 소스·현재 WASM6·실제 입력/사례 복사 hash 결합; 별도 per-input 생성 provenance는 원 workflow에 없고 새로 주장하지 않음','collectorSha256':sha(Path(__file__)),'nativeArchitectureHelperSha256':native_helper,'sourceQualified':False,'storeCertified':False}
 manifest_raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8');require(len(manifest_raw)<=64*1024 and used+len(manifest_raw)<=LIMIT,'manifest 포함 전체 8 MiB 상한')
 stage=Path(tempfile.mkdtemp(prefix='.synthetic-pdf-',dir=workspace))
 try:
  for row in pdfs:
   pdf=source/row['path'];data=read(pdf,LIMIT);require(len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'복사 직전 PDF 원본 변경')
   target=stage/row['path'];target.parent.mkdir(parents=True);target.write_bytes(data);require(sha(target)==row['sha256'],'보존한 PDF 원본 hash 불일치')
  (stage/'manifest.json').write_bytes(manifest_raw);stage.rename(destination)
 finally:
  if stage.exists():shutil.rmtree(stage)
 return manifest

def main():
 p=argparse.ArgumentParser();p.add_argument('--os',required=True,choices=['windows-2022','windows-2025','windows-11-arm']);a=p.parse_args()
 require(Path(os.environ.get('GITHUB_WORKSPACE',''))==ROOT,'현재 checkout에서만 합성 PDF 수집')
 result=collect(ROOT,os.environ,a.os);print('합성 PDF 원본:',result['pdfCount'],'개 /',result['printedPages'],'페이지 / 전체 8 MiB 이내; 검증 상태는 별도 유지')
if __name__=='__main__':main()
