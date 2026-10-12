"""Read frozen Source81 originals for an isolated print diagnostic only."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE='a785d3d33537ecedef325043346dc81425001dae'
RUN=38265944818
REPO='ATLKR/OpenGeul'
BRANCH='diagnostic/owned-print-preview-75'
SPECS={
    'package':(11757161844,'opengeul-windows-arm64-38265944818',57753494,'46c6035d56e2918639f622446c4e38ca0cac605436e6fc71da6daa82280b6f56',128*1024*1024),
    'inputs':(11757056420,'opengeul-e2e-inputs-arm64-38265944818',47701,'0985d2a5499be8b2893f607cd7c17406fdd62edac71de984c89b8ecad92d629e',8*1024*1024),
    'wasm-input':(11754374640,'opengeul-wasm-38265944818',4829693,'bb4421cba91a008b02d60f30425e00190b87019055dc57bace35ce8ce6aeaf83',16*1024*1024),
}
PRODUCERS={'wasm':114868560960,'windows-cli-arm64':114871185808,
           'windows-editor-arm64':114871185902,'build-arm64':114884415734}
EXES={'OpenGeul.exe':(30629376,'dd0f42cb096177a69365872f6a08f263be091552c8762cccfc220d3b2a58917f'),
      'Tools/rhwp.exe':(29163520,'76f03f9d72d13de29ed4b302bf86fff77713d5e6a09b7b00597966ddb3d7be93')}
PROVENANCE_SHA='6eb8ec975bad93adda72258d1a74af7c8525417a3c48a46b4007c4daec2e4acf'
CONTRACT_SHA='cd02ff38d80aa09264894a3740ff08b34089aa7641a87456e1b9fc2152de7b20'

def require(value,message):
    if not value:raise ValueError(message)

def unique(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'Duplicate JSON key');out[key]=value
    return out

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

def gh_json(path):
    result=subprocess.run(['gh','api',path],capture_output=True,timeout=60)
    require(result.returncode==0 and len(result.stdout)<=2*1024*1024,'Official metadata GET failed or exceeded cap')
    return json.loads(result.stdout,object_pairs_hook=unique)

def pages(path,key):
    records=[]
    for page in range(1,11):
        value=gh_json(path+f'?per_page=100&page={page}');batch=value.get(key)
        require(type(value.get('total_count')) is int and 0<=value['total_count']<=1000,
                'Metadata count exceeds cap')
        require(isinstance(batch,list) and len(batch)<=100,'Invalid metadata page')
        records.extend(batch)
        if len(records)==value['total_count']:return records
        require(len(records)<value['total_count'] and batch,'Incomplete metadata collection')
    raise ValueError('Metadata pagination exceeds cap')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def download(spec,destination):
    """Authenticate only api.github.com; redirects remain internal and unlogged."""
    artifact_id,_,size,expected,_=spec
    require(not destination.exists(),'Original ZIP path already exists')
    token=os.environ.get('GH_TOKEN');require(bool(token),'GitHub job token is unavailable')
    opener=urllib.request.build_opener(NoRedirect())
    url=f'https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip'
    for hop in range(6):
        parts=urllib.parse.urlsplit(url)
        require(parts.scheme=='https' and parts.port in (None,443) and not parts.username and not parts.password,
                'Artifact redirect is not HTTPS')
        host=(parts.hostname or '').lower()
        require(host=='api.github.com' or any(host.endswith(suffix) for suffix in
                ('.blob.core.windows.net','.githubusercontent.com','.actions.githubusercontent.com')),
                'Artifact redirect host is outside the fixed transport allowlist')
        headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
        if host=='api.github.com':headers['Authorization']='Bearer '+token
        try:response=opener.open(urllib.request.Request(url,headers=headers),timeout=120)
        except urllib.error.HTTPError as error:
            if error.code in (301,302,303,307,308):
                location=error.headers.get('Location');error.close()
                require(type(location) is str and len(location)<=16384,'Artifact redirect is missing or excessive')
                url=urllib.parse.urljoin(url,location);continue
            error.close();raise ValueError('Original artifact HTTP request failed') from None
        with response,destination.open('xb') as stream:
            require(response.status==200,'Original artifact HTTP status differs')
            total=0
            while block:=response.read(1024*1024):
                total+=len(block);require(total<=size and total<=64*1024*1024,'Original ZIP exceeds exact size cap')
                stream.write(block)
        require(destination.stat().st_size==size and digest(destination)==expected,'Original ZIP size or digest differs')
        return
    raise ValueError('Artifact redirect count exceeds cap')

def extract(path,output,limit,inventory):
    require(not output.exists(),'Extraction path already exists')
    with zipfile.ZipFile(path) as archive:
        require(sum(item.file_size for item in archive.infolist())<=limit,'Artifact expansion exceeds fixed cap')
        members=inventory(archive)
        require(archive.testzip() is None,'Original artifact CRC differs')
        output.mkdir()
        for name,item in members.items():
            target=output.joinpath(*name.split('/'));target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(item) as source,target.open('xb') as dest:shutil.copyfileobj(source,dest)
    return {name:{'bytes':(output/name).stat().st_size,'sha256':digest(output/name)} for name in members}

def prepare():
    receipt_dir=ROOT/'diagnostic-receipt';receipt_dir.mkdir(exist_ok=True)
    proof={'formatVersion':1,'diagnosticOnly':True,'sourceQualified':False,'qualifiedPackage':False,
           'physicalPrinterQualified':False,'fullWackQualified':False,'compiledProductSource':SOURCE,
           'compiledProductRun':str(RUN),'compiledProductAttempt':1,
           'candidateHelperHead':os.environ.get('GITHUB_SHA'),'runId':os.environ.get('GITHUB_RUN_ID'),
           'runAttempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'job':os.environ.get('GITHUB_JOB'),
           'architecture':'arm64','mode':'original-eight-case-owned-preview-diagnostic'}
    stage='context'
    try:
        require(os.environ.get('GITHUB_REPOSITORY')==REPO and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH
                and os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and os.environ.get('GITHUB_ACTOR')=='ATLKR'
                and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','Diagnostic context differs')
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        require(head==proof['candidateHelperHead'] and len(head)==40 and head!=SOURCE,'Candidate helper checkout differs')
        reader=ROOT/'source-reader'
        require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=reader,text=True).strip()==SOURCE,
                'Immutable Source81 reader differs')
        sys.path[:0]=[str(reader/'e2e'),str(reader/'scripts')]
        from prepare_payload import inventory,prepare as runtime_prepare
        import wasm_artifacts
        stage='producer-metadata'
        run=gh_json(f'repos/{REPO}/actions/runs/{RUN}')
        require(run['id']==RUN and run['head_sha']==SOURCE and run['run_attempt']==1 and run['run_number']==81
                and run['event']=='push' and run['head_branch']=='main' and run['path']=='.github/workflows/msix.yml'
                and run['status']=='completed' and run['conclusion']=='failure'
                and run['repository']['full_name']==REPO and run['repository']['private'] is False,
                'Failed Source81 identity differs')
        repo_id=run['repository']['id'];require(run['head_repository']['id']==repo_id,'Source head repository differs')
        jobs=pages(f'repos/{REPO}/actions/runs/{RUN}/attempts/1/jobs','jobs')
        for name,pid in PRODUCERS.items():
            rows=[job for job in jobs if job.get('id')==pid]
            require(len(rows)==1 and rows[0]['name']==name and rows[0]['run_id']==RUN
                    and rows[0]['head_sha']==SOURCE and rows[0]['run_attempt']==1
                    and rows[0]['status']=='completed' and rows[0]['conclusion']=='success','Compiled producer did not succeed')
        artifacts=pages(f'repos/{REPO}/actions/runs/{RUN}/artifacts','artifacts')
        (receipt_dir/'source-run.api.json').write_text(json.dumps(run,indent=2),encoding='utf-8')
        (receipt_dir/'source-jobs.api.json').write_text(json.dumps(jobs,indent=2),encoding='utf-8')
        (receipt_dir/'source-artifacts.api.json').write_text(json.dumps(artifacts,indent=2),encoding='utf-8')
        proof['inputs']={}
        for role,spec in SPECS.items():
            stage='original-'+role
            matches=[a for a in artifacts if a.get('id')==spec[0]]
            require(len(matches)==1,'Pinned artifact is missing or ambiguous');item=matches[0];origin=item['workflow_run']
            require(item['name']==spec[1] and item['size_in_bytes']==spec[2] and item['digest']=='sha256:'+spec[3]
                    and item['expired'] is False and origin['id']==RUN and origin['head_sha']==SOURCE
                    and origin['repository_id']==repo_id and origin['head_repository_id']==repo_id
                    and origin['head_branch']=='main','Pinned artifact provenance differs')
            original=ROOT/(role+'-original.zip');download(spec,original)
            files=extract(original,ROOT/role,spec[4],inventory)
            proof['inputs'][role]={'artifactId':spec[0],'artifactName':spec[1],'zipBytes':spec[2],
                                   'zipSha256':spec[3],'files':files}
        stage='immutable-runtime-validation'
        require(digest(ROOT/'package/provenance.json')==PROVENANCE_SHA,'Source81 provenance bytes differ')
        provenance=json.loads((ROOT/'package/provenance.json').read_text(encoding='utf-8-sig'),object_pairs_hook=unique)
        require(provenance['commit']==SOURCE and provenance['runId']==str(RUN) and provenance['version']=='1.1.3'
                and provenance['architecture']=='arm64'
                and provenance['windowsComponents']['sourceContractSha256']==CONTRACT_SHA,'Compiled source contract differs')
        prepared=runtime_prepare(ROOT/'package',ROOT/'runtime','arm64')
        require(prepared['verifiedRuntimeFiles']==1566 and prepared['runtimeManifestSha256']==
                'ee38527c14da2e5c0ad3bf8d82892f53ff6e0290263d8d3cd041817c183a432e',
                'Complete runtime file inventory differs')
        for name,(size,sha) in EXES.items():
            require((ROOT/'runtime'/name).stat().st_size==size and digest(ROOT/'runtime'/name)==sha,'Compiled PE bytes differ')
        wasm_artifacts.validate(ROOT/'wasm-input')
        manifest=json.loads((ROOT/'wasm-input/OPEN_GEUL_WASM.json').read_text(encoding='utf-8-sig'),object_pairs_hook=unique)
        require(manifest==provenance['sourceParity']['wasmRebuild'],'Fixture WASM and compiled runtime origin differs')
        require(len(proof['inputs']['inputs']['files'])==10 and (ROOT/'inputs/e2e-fixtures/basic.hwpx').is_file()
                and (ROOT/'inputs/e2e-fixtures/basic.hwp').is_file(),'Original native fixture inventory differs')
        proof.update({'sourceContractSha256':CONTRACT_SHA,'completeRuntime':prepared,'runtimeExecutables':EXES,
                      'immutableValidatorHashes':{name:digest(reader/name) for name in
                          ('e2e/prepare_payload.py','scripts/windows_components.py','scripts/releasekit.py','scripts/wasm_artifacts.py')},
                      'candidateHelperHashes':{name:digest(ROOT/name) for name in
                          ('e2e/print_focus.py','e2e/preview_settings.py','e2e/virtual_print.py')},'inputValidationPassed':True})
    except BaseException as error:
        proof.update({'inputValidationPassed':False,'failureStage':stage,'errorType':type(error).__name__})
        raise ValueError('Frozen diagnostic input validation failed at '+stage) from None
    finally:
        (receipt_dir/'source-receipt.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    try:prepare()
    except BaseException as error:
        print('Diagnostic stopped:',type(error).__name__,str(error) if type(error) is ValueError and str(error).startswith('Frozen diagnostic') else 'bounded input-validation failure')
        raise SystemExit(1)
