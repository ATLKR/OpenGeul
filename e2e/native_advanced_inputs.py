"""Admit the current successful WASM producer's owned inputs before native GUI tests.

Only advanced-owned is published. Native Rust fixtures and the GUI contract stay
unchanged; downloading or checking inputs is never product execution evidence.
"""
from __future__ import annotations
import argparse,hashlib,io,json,os
from pathlib import Path,PurePosixPath
import re,stat,sys,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'e2e')]
import mcp_qa_download as download
import mcp_fixtures as qa
import ui_contract
import wasm_artifacts
from advanced_edit_oracle import inspect_advanced_hwpx

MAX_ZIP=16*1024*1024
MAX_BROWSER_EXPANDED=32*1024*1024
MAX_ADVANCED=1024*1024
ADVANCED_NAMES=frozenset('owned-'+n+'.hwpx' for n in ('blank','equation','field-filled','field-guide','grid','merged','nested','notes','page','shape','split','textbox'))
ADVANCED_FILES=ADVANCED_NAMES|{'provenance.json','loadability.json'}
NATIVE_NAMES=frozenset(('basic.hwp','basic.hwpx','blank.hwp','blank.hwpx','invalid.hwpx','missing-font.hwp','missing-font.hwpx','paragraphs.hwpx','unicode.hwp','unicode.hwpx'))
BASELINE_FILES=({'e2e-fixtures/'+n for n in NATIVE_NAMES}|{'structured-fixtures/'+n for n in ('structured.hwp','structured.hwpx','checkerboard.png','generation.json')}|{'structured-input-binding.json'})
BROWSER_BASELINE=NATIVE_NAMES|{'paragraphs.hwp'}
DIST_STATIC=frozenset(('index.html','favicon.ico','opengeul.ico','images/icon_small_ko.svg','images/icon_small_ko_dark.svg'))
DIST_DYNAMIC=(r'assets/dist-js-[A-Za-z0-9_-]{8}\.js',r'assets/event-[A-Za-z0-9_-]{8}\.js',
    r'assets/index-[A-Za-z0-9_-]{8}\.js',r'assets/index-[A-Za-z0-9_-]{8}\.css',
    r'assets/rhwp_bg-[A-Za-z0-9_-]{8}\.wasm',r'assets/webviewWindow-[A-Za-z0-9_-]{8}\.js')
STAGES=frozenset(('boundary','native-boundary','native-source','native-input-binding','local-wasm','source-run',
    'wasm-producer','artifact-list','browser-archive','wasm-archive','original-wasm','owned-inputs',
    'native-baseline','publish-owned','publish-receipt'))

def need(value,message):
    if not value:raise ValueError(message)

def record(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def read(path,cap):
    path=qa.safe_path(path);state=path.stat()
    need(stat.S_ISREG(state.st_mode) and 0<state.st_size<=cap,'Input must be a bounded regular file')
    with path.open('rb')as stream:raw=stream.read(cap+1)
    need(len(raw)==state.st_size and len(raw)<=cap,'Input changed while reading')
    return raw

def snapshot(folder,*,staged=False):
    folder=qa.safe_path(folder);need(folder.is_dir(),'Native input root is missing')
    files={}
    for p in folder.rglob('*'):
        qa.safe_path(p)
        if p.is_dir():continue
        name=p.relative_to(folder).as_posix()
        if staged and name.startswith('e2e-fixtures/advanced-owned/'):continue
        files[name]=record(read(p,4*1024*1024))
        need(len(files)<=15,'Unexpected native input file')
    need(set(files)==BASELINE_FILES and sum(r['bytes']for r in files.values())<=16*1024*1024,
         'Native input must retain its exact fifteen-file transport')
    return files

def artifact(value,name,binding,run,producer,pr):
    need(type(value)is dict and type(value.get('id'))is int and value['id']>0
        and value.get('name')==name and type(value.get('size_in_bytes'))is int
        and 0<value['size_in_bytes']<=MAX_ZIP and value.get('expired')is False
        and type(value.get('digest'))is str and re.fullmatch(r'sha256:[0-9a-f]{64}',value['digest'])
        and type(value.get('workflow_run'))is dict and type(value['workflow_run'].get('id'))is int
        and str(value['workflow_run']['id'])==binding['sourceRun']
        and value['workflow_run'].get('head_sha')==(pr['apiHeadCommit']if pr else binding['sourceCommit']),
        'Artifact identity, source run or server digest differs')
    created=download._time(value.get('created_at'));updated=download._time(value.get('updated_at'))
    need(download._time(run['run_started_at'])<=download._time(producer['started_at'])<=created<=updated<=download._time(producer['completed_at']),
         'Artifact is outside the current successful producer attempt')
    return {k:value[k]for k in ('id','name','size_in_bytes','digest','expired','created_at','updated_at','workflow_run')}

def fetch(name,binding,run,producer,artifacts,backend,pr):
    matches=[r for r in artifacts if r.get('name')==name];need(len(matches)==1,'Current artifact is missing or ambiguous')
    selected=artifact(matches[0],name,binding,run,producer,pr)
    fixed=artifact(backend.get('actions/artifacts/'+str(selected['id'])),name,binding,run,producer,pr)
    need(fixed==selected,'Artifact changed before download')
    raw=backend.zip(selected['id'])
    need(type(raw)is bytes and 0<len(raw)<=MAX_ZIP and len(raw)==selected['size_in_bytes']
         and 'sha256:'+hashlib.sha256(raw).hexdigest()==selected['digest'],'Original ZIP size or server SHA256 differs')
    after=artifact(backend.get('actions/artifacts/'+str(selected['id'])),name,binding,run,producer,pr)
    need(after==selected,'Artifact changed after download')
    return raw,selected

def zip_members(raw,*,browser):
    z=zipfile.ZipFile(io.BytesIO(raw));entries=z.infolist();cap=MAX_BROWSER_EXPANDED if browser else 32*1024*1024
    need(len(entries)==(36 if browser else 7) and sum(e.file_size for e in entries)<=cap,'Unexpected ZIP inventory or expansion size')
    aliases=set();names=set()
    for e in entries:
        name=e.filename;parts=name.split('/');kind=stat.S_IFMT(e.external_attr>>16)
        need(len(name)<=1024 and not any(p in ('','.','..')for p in parts) and '\\'not in name and ':'not in name
            and not PurePosixPath(name).is_absolute() and name.casefold()not in aliases and not e.is_dir()
            and kind in (0,stat.S_IFREG) and not e.flag_bits&1 and not e.external_attr&0x400
            and 0<e.file_size<=16*1024*1024,'Unsafe, duplicate or oversized ZIP member')
        aliases.add(name.casefold());names.add(name)
    if browser:
        selected={'e2e-fixtures/advanced-owned/'+n for n in ADVANCED_FILES}
        baselines={'e2e-fixtures/'+n for n in BROWSER_BASELINE}
        prefix='hop/apps/studio-host/dist/';dist={n[len(prefix):]for n in names if n.startswith(prefix)}
        need(selected|baselines<=names and len(dist)==11 and DIST_STATIC<=dist,'Unknown browser input inventory')
        dynamic=dist-DIST_STATIC
        need(len(dynamic)==6 and all(sum(bool(re.fullmatch(pattern,n))for n in dynamic)==1 for pattern in DIST_DYNAMIC)
             and names==selected|baselines|{prefix+n for n in dist},'Unknown browser distribution member')
    else:need(names==set(wasm_artifacts.FILES)|{'OPEN_GEUL_WASM.json'},'WASM input must have exactly six payload files and its manifest')
    need(z.testzip()is None,'Original ZIP CRC differs')
    return z

def advanced_payload(z,wasm,parity):
    prefix='e2e-fixtures/advanced-owned/'
    files={n:z.read(prefix+n)for n in ADVANCED_FILES}
    need(sum(len(v)for v in files.values())<=MAX_ADVANCED and all(0<len(v)<=128*1024 for v in files.values()),'Owned advanced input size exceeds its bound')
    p=qa.strict_json(files['provenance.json']);need(type(p)is dict and set(p)=={'purpose','vendorWasmSha256','generated','frontendSource','nestedAuthoring'},'Owned provenance fields differ')
    need(p['purpose']=='Owned synthetic inputs; no GUI claim' and p['vendorWasmSha256']==wasm['artifacts']['rhwp_bg.wasm'],'Owned input WASM differs from the current runtime source')
    need(type(p['generated'])is dict and set(p['generated'])==ADVANCED_NAMES and all(p['generated'][n]==record(files[n])['sha256']for n in ADVANCED_NAMES),'Owned input hashes or twelve-case inventory differ')
    ui_contract.validate_frontend_source(p['frontendSource'],ui_contract.helper_hashes(ROOT))
    need(p['frontendSource']['equationDialogFocus']==parity.get('equationDialogFocus'),'Native editor source and input frontend source differ')
    nested=p['nestedAuthoring'];need(type(nested)is dict and nested=={'from':'owned-grid.hwpx','sourceSha256':p['generated']['owned-grid.hwpx'],'method':'owned XML nesting; no personal corpus','outerWidthHU':48000,'outerRowsHU':[18000,6000],'innerWidthHU':18000,'innerRowsHU':[4000,4000]},'Nested input ownership differs')
    loaded=qa.strict_json(files['loadability.json'])
    need(type(loaded)is dict and set(loaded)=={'allOwnedHwpxLoadedByPreparedWasm','method','names'}
         and loaded['allOwnedHwpxLoadedByPreparedWasm']is True and loaded['method']=='constructor only; no GUI claim'
         and type(loaded['names'])is list and len(loaded['names'])==12 and set(loaded['names'])==ADVANCED_NAMES,'Producer loadability inventory differs')
    for n in ADVANCED_NAMES:
        with zipfile.ZipFile(io.BytesIO(files[n]))as inner:
            rows=inner.infolist();need(len(rows)<=128 and sum(r.file_size for r in rows)<=4*1024*1024
                and all(r.file_size<=2*1024*1024 for r in rows)and inner.testzip()is None,'Owned HWPX expansion or CRC differs')
        inspect_advanced_hwpx(files[n])
    return files,p['frontendSource']

def stage(package,wasm,fixtures,receipt,*,backend=None,env=None):
    progress={'stage':'native-boundary'}
    try:return admit(package,wasm,fixtures,receipt,backend=backend,env=env,progress=progress)
    except Exception as error:
        try:error._native_input_stage=progress['stage']
        except Exception:pass
        raise

def admit(package,wasm,fixtures,receipt,*,backend,env,progress):
    package=qa.safe_path(package);wasm=qa.safe_path(wasm);fixtures=qa.safe_path(fixtures);receipt=qa.safe_path(receipt)
    destination=qa.safe_path(fixtures/'advanced-owned')
    need(fixtures.name=='e2e-fixtures' and fixtures.is_dir() and not destination.exists() and not receipt.exists(),
         'Owned destination or receipt already exists, or native fixtures are missing')
    need(not any(p==receipt or p in receipt.parents or receipt in p.parents for p in (package,wasm,fixtures.parent)),
         'Receipt overlaps original inputs')
    baseline=snapshot(fixtures.parent)
    progress['stage']='native-source'
    binding,expected_wasm,architecture=download.source_context(package,env)
    package_provenance=download.release_pair.read_json(package/'provenance.json');parity=package_provenance['sourceParity']
    progress['stage']='native-input-binding'
    native_input=qa.json_file(fixtures.parent/'structured-input-binding.json')
    components=package_provenance['windowsComponents']
    need(type(native_input)is dict and all(native_input.get(k)==v for k,v in binding.items())
         and native_input.get('architecture')==architecture
         and native_input.get('sourceContractSha256')==components['sourceContractSha256']
         and native_input.get('editorProvenanceSha256')==components['components']['editor']['provenanceSha256'],
         'Original native input and native editor source commitments differ')
    progress['stage']='local-wasm'
    need({p.name for p in wasm.iterdir()}==set(wasm_artifacts.FILES)|{'OPEN_GEUL_WASM.json'},'Local WASM inventory differs')
    local={n:read(wasm/n,16*1024*1024)for n in (*wasm_artifacts.FILES,'OPEN_GEUL_WASM.json')}
    need(qa.strict_json(local['OPEN_GEUL_WASM.json'])==expected_wasm,'Local WASM manifest differs from the native runtime source')
    qa.wasm_proof(expected_wasm)
    need(all(record(local[n])['sha256']==expected_wasm['artifacts'][n]for n in wasm_artifacts.FILES),'Local six WASM payload hashes differ')
    backend=download.GitHub()if backend is None else backend
    progress['stage']='source-run'
    run,jobs,pr=download._run_jobs(binding,backend,env=env,allow_pr=True)
    progress['stage']='wasm-producer'
    producers=[j for j in jobs if j.get('name')=='wasm'];need(len(producers)==1,'A single successful WASM producer is required')
    producer=producers[0]
    need(producer.get('status')=='completed' and producer.get('conclusion')=='success'
        and type(producer.get('run_id'))is int and str(producer['run_id'])==binding['sourceRun']
        and type(producer.get('run_attempt'))is int and str(producer['run_attempt'])==binding['runAttempt']
        and producer.get('head_sha')==(pr['apiHeadCommit']if pr else binding['sourceCommit']),'WASM producer source, attempt or result differs')
    progress['stage']='artifact-list'
    artifacts=download._page(backend.get('actions/runs/'+binding['sourceRun']+'/artifacts?per_page=100'),'artifacts')
    progress['stage']='browser-archive'
    browser_raw,browser_origin=fetch('opengeul-browser-inputs-'+binding['sourceRun'],binding,run,producer,artifacts,backend,pr)
    progress['stage']='wasm-archive'
    wasm_raw,wasm_origin=fetch('opengeul-wasm-'+binding['sourceRun'],binding,run,producer,artifacts,backend,pr)
    progress['stage']='original-wasm'
    with zip_members(wasm_raw,browser=False)as wz:
        need(all(wz.read(n)==raw for n,raw in local.items()),'Original same-run WASM bytes differ from the current local six and manifest')
    progress['stage']='owned-inputs'
    with zip_members(browser_raw,browser=True)as bz:files,frontend=advanced_payload(bz,expected_wasm,parity)
    progress['stage']='native-baseline'
    need(snapshot(fixtures.parent)==baseline,'Native baseline changed during admission')
    proof={'formatVersion':1,**binding,'architecture':architecture,'producer':{k:producer[k]for k in ('id','name','run_id','run_attempt','head_sha','status','conclusion','started_at','completed_at')},
        'browserArtifact':browser_origin,'wasmArtifact':wasm_origin,'bothOriginalServerSha256AndFullCrcVerified':True,
        'bothArtifactMetadataBeforeAndAfterVerified':True,'localWasmSixAndManifestOriginalBytesVerified':True,
        'nativeSourceContractSha256':components['sourceContractSha256'],
        'nativeEditorSha256':components['components']['editor']['sha256'],
        'nativeEditorOriginalProvenanceSha256':components['components']['editor']['provenanceSha256'],
        'nativeInputTransportSha256':record(read(fixtures.parent/'structured-input-binding.json',64*1024))['sha256'],
        'frontendSource':frontend,'baselineBefore':baseline,'baselineAfter':baseline,
        'copiedFiles':{n:record(v)for n,v in sorted(files.items())},'independentTwelveHwpxXmlInspected':True,
        'helperSha256':record(read(Path(__file__),1024*1024))['sha256'],'productExecuted':False,'sourceQualified':False}
    if pr is not None:proof['pullRequestBinding']=pr
    data=(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode();need(len(data)<=64*1024,'Staging receipt exceeds its bound')
    progress['stage']='publish-owned'
    with tempfile.TemporaryDirectory(prefix='.opengeul-native-advanced-',dir=fixtures.parent)as tmp:
        folder=Path(tmp)/'advanced-owned';folder.mkdir()
        for n,raw in files.items():
            with (folder/n).open('xb')as stream:stream.write(raw)
        need({n:record(read(folder/n,128*1024))for n in files}==proof['copiedFiles'],'Staged owned bytes differ')
        need(snapshot_without_temporary(fixtures.parent,Path(tmp))==baseline,'Native baseline changed before publication')
        need(not destination.exists()and not receipt.exists(),'Owned destination was created during admission')
        download._move_new(folder,destination)
    need(snapshot(fixtures.parent,staged=True)==baseline,'Native baseline changed after publication')
    need({p.name:record(read(p,128*1024))for p in destination.iterdir()}==proof['copiedFiles'],'Published owned bytes differ')
    progress['stage']='publish-receipt'
    receipt.parent.mkdir(parents=True,exist_ok=True)
    with receipt.open('xb')as stream:stream.write(data)
    return proof

def snapshot_without_temporary(folder,temporary):
    # The only excluded directory is the unique helper-owned staging directory.
    files={}
    for p in folder.rglob('*'):
        if p==temporary or temporary in p.parents:continue
        qa.safe_path(p)
        if p.is_dir():continue
        files[p.relative_to(folder).as_posix()]=record(read(p,4*1024*1024))
    need(set(files)==BASELINE_FILES,'Native baseline inventory changed during staging')
    return files

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('package','wasm','fixtures','receipt'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();stage(a.package,a.wasm,a.fixtures,a.receipt)
    print('Current-run owned advanced inputs staged; native baseline unchanged; GUI execution remains unqualified.')

def diagnostic(error):
    # Existing backend classification admits only fixed enums and bounded numbers.
    safe=download._diagnostic(error)
    stage=getattr(error,'_native_input_stage',None)
    return {'formatVersion':1,'stage':stage if type(stage)is str and stage in STAGES else 'boundary',
            'code':safe['code'],'exceptionKind':safe['exceptionKind']}

def emit_failure(error):
    try:
        raw=json.dumps(diagnostic(error),separators=(',',':'))+'\n'
        if len(raw.encode())<=1024:sys.stderr.write(raw)
    except Exception:pass  # Diagnostic failure cannot replace the original admission failure.

if __name__=='__main__':
    try:main()
    except Exception as error:
        # Never expose API response text, credentials, raw paths or arbitrary exception strings.
        emit_failure(error)
        raise SystemExit('Native advanced input admission failed; original inputs and mandatory GUI contract remain required.')from None
