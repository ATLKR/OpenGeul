"""Read-only Source81 candidate transport and a separately bound SDK diagnostic.

No process environment is rewritten. No native install or final qualification
marker is created. All production helpers and WACK rules remain unchanged.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'e2e')]
import native_wack_transport as native
from prepare_payload import inventory,stream_hash
from releasekit import pe_machine
from windows_components import identity

SOURCE={'repository':'ATLKR/OpenGeul','commit':'a785d3d33537ecedef325043346dc81425001dae','runId':'38265944818','runAttempt':'1'}
REPO_ID=1405493151
BRANCH='diagnostic/same-signed-arm-sdk-source81'
IMPORTER_SHA='327ee797d69c11eb1cf1c87116897061e9299754afa73586155662413a5b9f74'
SIGNED_SHA='e477c40740196bbced7cb123e57ab25c4edd0314dc6c9a0a5f933686a7f8f985'
CER_SHA='ae780af23ac64716a2a8bc346e6079e5d9d7e163801baef718fac47366e9f4e2'
PENDING_SHA='17e44ee6c0ef1ca72f9c873b14f10b405744d26158e96466de5bb50741c4e696'
PINS={
 'source':{'id':11757161844,'name':'opengeul-windows-arm64-38265944818','bytes':57753494,'sha256':'46c6035d56e2918639f622446c4e38ca0cac605436e6fc71da6daa82280b6f56','jobId':114884415734,'job':'build-arm64'},
 'native':{'id':11758025535,'name':'opengeul-native-signed-arm64-38265944818-1','bytes':28686770,'sha256':'f4e1b91a050594637c1f77f176a4ca5ab21bdb6e60fe0cd04651007c5f773bd5','jobId':114889805534,'job':'msix-native-arm64'},
 'pending':{'id':11756814149,'name':'msix-install-arm64-38265944818','bytes':53783,'sha256':'c86a48d43a6998f62d59f1201f70af2fe4d149d1b6444609e883ababf5d47b27','jobId':114891635105,'job':'msix-install-arm64'},
}
require=native.require


def save(path,value):
    require(not path.exists(),'Existing diagnostic evidence cannot be overwritten')
    path.write_bytes(native.pair.encoded(value)+b'\n')


def execution(backend,env):
    actual=identity(env)
    require(env.get('GITHUB_ACTIONS')=='true' and env.get('RUNNER_ENVIRONMENT')=='github-hosted'
        and env.get('GITHUB_JOB')=='msix-install-arm64' and env.get('GITHUB_REF')=='refs/heads/'+BRANCH
        and actual['runId']!=SOURCE['runId'] and actual['commit']!=SOURCE['commit'] and actual['runAttempt']=='1',
        'A real, separately bound hosted diagnostic execution is required')
    run,proof=native._metadata(backend,'actions/runs/'+actual['runId'])
    require(run.get('id')==int(actual['runId']) and run.get('head_sha')==actual['commit'] and run.get('run_attempt')==1
        and run.get('head_branch')==BRANCH and run.get('event')=='workflow_dispatch' and run.get('path')=='.github/workflows/msix.yml'
        and run.get('status')=='in_progress' and run.get('conclusion') is None,'Current diagnostic API execution mismatch')
    for field in ('repository','head_repository'):
        require(run.get(field,{}).get('id')==REPO_ID and run[field].get('full_name')==SOURCE['repository']
            and run[field].get('private') is False,'Current diagnostic repository/fork mismatch')
    jobs,jobs_proof=native._metadata(backend,f'actions/runs/{actual["runId"]}/attempts/1/jobs?per_page=100')
    rows=native.qa_download._page(jobs,'jobs')
    selected=[row for row in rows if row.get('name')=='동일 서명 ARM64 stock SDK 진단']
    require(len(selected)==1,'Exact diagnostic job missing/duplicate')
    job=native._job(selected[0],actual,selected[0]['name'],completed=False)
    return {'binding':actual,'job':job,'runApi':proof,'jobsApi':jobs_proof}


def extract(raw,output,expected,cap):
    require(not output.exists(),'Existing diagnostic input directory')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows=archive.infolist();require({row.filename for row in rows}==set(expected) and len(rows)==len(expected)
            and sum(row.file_size for row in rows)<=cap,'Exact diagnostic original archive inventory/size mismatch')
        seen=set()
        for row in rows:
            kind=stat.S_IFMT(row.external_attr>>16)
            require(not row.is_dir() and row.filename.casefold() not in seen and kind in (0,stat.S_IFREG)
                and not row.flag_bits&1 and not row.external_attr&0x400 and '/' not in row.filename and '\\' not in row.filename,
                'Diagnostic original archive alias/path/special file')
            seen.add(row.filename.casefold())
        require(archive.testzip() is None,'Diagnostic original CRC failure');output.mkdir()
        for row in rows:
            with archive.open(row) as stream:data=stream.read(row.file_size+1)
            require(len(data)==row.file_size,'Original member byte length mismatch');(output/row.filename).write_bytes(data)


def candidate(backend,directory):
    directory.mkdir(parents=True,exist_ok=False)
    run,run_proof=native._metadata(backend,'actions/runs/'+SOURCE['runId'])
    require(run.get('id')==int(SOURCE['runId']) and run.get('head_sha')==SOURCE['commit'] and run.get('run_attempt')==1
        and run.get('head_branch')=='main' and run.get('event')=='push' and run.get('path')=='.github/workflows/msix.yml'
        and run.get('status')=='completed' and run.get('conclusion')=='failure',
        'The original Source81 remains a failed whole run; only its actual successful native candidate is diagnostic input')
    for field in ('repository','head_repository'):
        require(run.get(field,{}).get('id')==REPO_ID and run[field].get('full_name')==SOURCE['repository']
            and run[field].get('private') is False,'Original Source81 repository/fork mismatch')
    jobs,jobs_proof=native._metadata(backend,f'actions/runs/{SOURCE["runId"]}/attempts/1/jobs?per_page=100')
    rows=native.qa_download._page(jobs,'jobs');origins={};raws={}
    for role,pin in PINS.items():
        matches=[row for row in rows if row.get('id')==pin['jobId']]
        require(len(matches)==1,'Pinned original producer job missing/duplicate');job=matches[0]
        if role!='pending':native._job(job,SOURCE,pin['job'])
        else:
            require(job.get('name')==pin['job'] and job.get('run_id')==int(SOURCE['runId'])
                and job.get('head_sha')==SOURCE['commit'] and job.get('run_attempt')==1
                and job.get('status')=='completed' and job.get('conclusion')=='failure',
                'Source81 original SDK failure must remain recorded as failure')
        meta,proof=native._metadata(backend,'actions/artifacts/'+str(pin['id']))
        require(meta.get('id')==pin['id'] and meta.get('name')==pin['name'] and meta.get('size_in_bytes')==pin['bytes']
            and meta.get('digest')=='sha256:'+pin['sha256'] and meta.get('expired') is False,'Pinned original API digest/name/size/expiry mismatch')
        owner=meta.get('workflow_run',{})
        require(owner.get('id')==int(SOURCE['runId']) and owner.get('head_sha')==SOURCE['commit']
            and owner.get('repository_id')==REPO_ID and owner.get('head_repository_id')==REPO_ID and owner.get('head_branch')=='main',
            'Pinned original artifact repository/head/run mismatch')
        if role!='pending':native.artifact(meta,SOURCE,run,job,pin['name'],native.MAX_ZIP)
        else:
            require(native.timestamp(job['started_at'])<=native.timestamp(meta['created_at'])<=native.timestamp(meta['updated_at'])
                <=native.timestamp(job['completed_at'])<native.timestamp(meta['expires_at']),'Original failed SDK artifact time mismatch')
        raw=backend.zip(pin['id'])
        require(len(raw)==pin['bytes'] and hashlib.sha256(raw).hexdigest()==pin['sha256'],'Pinned original ZIP server size/hash mismatch')
        raws[role]=raw;origins[role]={'metadata':proof,'job':job,'artifact':meta,'zipSha256':pin['sha256'],'zipBytes':len(raw)}
    source=directory/'package';transport=directory/'native-input';failed=directory/'original-sdk-failure'
    extract(raws['source'],source,{'AppxManifest.xml','OpenGeul_1.1.3.0_arm64_development-unsigned.msix','OpenGeul_1.1.3_windows-arm64_unsigned-portable.zip','provenance.json','rhwp-help.txt','SHA256SUMS.txt'},native.MAX_EXPANDED)
    native.extract(raws['native'],transport)
    extract(raws['pending'],failed,{'evidence-index.json','installed-launch.json','installed-cli.json','pending-native.json'},native.JSON_CAP*4)
    return validate_inputs(source,transport,failed,origins,run_proof,jobs_proof,directory/'evidence')


def validate_inputs(source,transport,failed,origins,run_proof,jobs_proof,evidence):
    require({path.name for path in transport.iterdir()}==native.FILES,'Original native transport must remain exact3')
    require({path.name for path in failed.iterdir()}=={'evidence-index.json','installed-launch.json','installed-cli.json','pending-native.json'},
        'Original Source81 failed SDK evidence must remain exact4')
    provenance=native._json(source/'provenance.json');native.qa_download.verify_checksums(source)
    require(provenance['repository']==SOURCE['repository'] and provenance['commit']==SOURCE['commit'] and provenance['runId']==SOURCE['runId']
        and provenance['windowsComponents']['runAttempt']=='1' and provenance['architecture']=='arm64' and provenance['unsigned'] is True
        and provenance['storeCertified'] is False,'Original Source6 provenance mismatch')
    unsigned=source/provenance['package'];manifest=(source/'AppxManifest.xml').read_bytes()
    package_identity=dict(ET.fromstring(manifest).find('{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity').attrib)
    require(package_identity['ProcessorArchitecture']=='arm64' and b'\r' not in manifest,'Actual ARM manifest/LF mismatch')
    runtime=native.runtime(unsigned)
    with zipfile.ZipFile(unsigned) as msix,zipfile.ZipFile(next(source.glob('*portable.zip'))) as portable:
        members=inventory(portable);require(set(members)==set(runtime),'Entire portable/unsigned runtime inventory mismatch')
        require(msix.read('AppxManifest.xml')==manifest,'Manifest external/package bytes mismatch')
        for name,row in members.items():
            with portable.open(row) as stream:digest=stream_hash(stream)
            require(runtime[name]=={'bytes':row.file_size,'sha256':digest},'Every portable/unsigned runtime byte must match')
        for name in ('OpenGeul.exe','Tools/rhwp.exe'):
            with msix.open(name) as stream:pe_machine(stream.read(4096),'arm64')
    record=native._json(transport/'native-install.json');signed=native._native_core(record,unsigned,SOURCE,package_identity)
    producer,_=native._producer_proof(record,SOURCE,'source')
    require(signed==SIGNED_SHA==native.sha(transport/'test-only.msix') and record['runtime']==native.signed_parity(unsigned,transport/'test-only.msix')==runtime,
        'The historical native candidate and every signed runtime byte must be identical')
    require(native.sha(transport/'test.cer')==CER_SHA and all(record['certificate'][key]==value for key,value in native.certificate((transport/'test.cer').read_bytes()).items()),
        'The original public CER/signature metadata must be identical')
    require(native.timestamp(record['certificate']['notBefore'])<=datetime.now(timezone.utc)<native.timestamp(record['certificate']['notAfter']),
        'The original 24-hour public certificate is no longer valid; do not re-sign')
    pending=native._json(failed/'pending-native.json')
    require(native.sha(failed/'pending-native.json')==PENDING_SHA and pending['native']==record and pending['signedSha256']==SIGNED_SHA
        and pending['unsignedSha256']==native.sha(unsigned) and pending['packageIdentity']==package_identity,'The original failed SDK pending receipt does not match this candidate')
    native._origin_proof(pending['origin'],record,SOURCE,'source')
    for role,key in [('source','unsigned'),('native','native')]:
        require(native._metadata_proof(pending['origin'][key]['metadata'])==origins[role]['artifact'],'Original retained and actual fresh API metadata differ')
    require(producer['job']['id']==PINS['native']['jobId'] and producer['unsigned']['producer']['id']==PINS['source']['jobId']
        and pending['origin']['consumer']['id']==PINS['pending']['jobId'],'Historical producer identities differ')
    evidence.mkdir()
    for name in ('pending-native.json','installed-launch.json','installed-cli.json'):
        data=(failed/name).read_bytes()
        if name!='pending-native.json':require(data==base64.b64decode(record['originalEvidence'][name]['rawBase64'],validate=True),'Historical raw native evidence byte mismatch')
        (evidence/name).write_bytes(data)
    result={'formatVersion':1,'scope':'Pinned historical Source81 candidate transport only; no current native/whole qualification',
        'originalCandidateBinding':SOURCE,'source81WholeConclusion':'failure','originalSdkConclusion':'failure','origins':origins,
        'sourceRunApi':run_proof,'sourceJobsApi':jobs_proof,'signedSha256':SIGNED_SHA,'certificateSha256':CER_SHA,
        'nativeJsonSha256':native.sha(transport/'native-install.json'),'originalPendingSha256':PENDING_SHA,'runtimeFilesIncludingManifest':len(runtime),
        'allUnsignedSignedPortableRuntimeBytesIdentical':True,'originalNativeCleanup':record['cleanup'],
        'paths':{'package':str(source.resolve()),'native':str(transport.resolve()),'evidence':str(evidence.resolve())},
        'wholeSourceQualified':False,'storeSubmitted':False}
    save(evidence/'diagnostic-input.json',result);return result


def prepare(directory):
    env=dict(os.environ);require(native.sha(ROOT/'e2e/msix-wack-import.ps1')==IMPORTER_SHA,'Corrected production importer changed')
    backend=native.GitHub();current=execution(backend,env);proof=candidate(backend,directory)
    save(Path(proof['paths']['evidence'])/'diagnostic-execution.json',current)
    require(dict(os.environ)==env,'Diagnostic transport altered real process environment')


def verify(directory):
    require(native.sha(ROOT/'e2e/msix-wack-import.ps1')==IMPORTER_SHA,'Pinned corrected importer changed during the diagnostic')
    evidence=directory/'evidence';pin=native._json(evidence/'diagnostic-input.json');current=native._json(evidence/'diagnostic-execution.json')
    require(current.get('binding')==identity(os.environ) and current['binding']['runId']!=SOURCE['runId']
        and current['binding']['commit']!=SOURCE['commit'] and os.environ.get('GITHUB_JOB')=='msix-install-arm64',
        'Retained diagnostic execution is not this real job/run/head/attempt')
    run=native._metadata_proof(current['runApi']);jobs=native.qa_download._page(native._metadata_proof(current['jobsApi']),'jobs')
    require(run.get('id')==int(current['binding']['runId']) and run.get('head_sha')==current['binding']['commit'] and run.get('run_attempt')==1
        and run.get('head_branch')==BRANCH and run.get('event')=='workflow_dispatch' and run.get('path')=='.github/workflows/msix.yml'
        and run.get('status')=='in_progress' and run.get('conclusion') is None,'Retained actual diagnostic run API mismatch')
    for field in ('repository','head_repository'):
        require(run.get(field,{}).get('id')==REPO_ID and run[field].get('full_name')==SOURCE['repository']
            and run[field].get('private') is False,'Retained diagnostic API repository/fork mismatch')
    selected=[job for job in jobs if job.get('id')==current['job']['id']]
    require(len(selected)==1 and native._job(selected[0],current['binding'],'동일 서명 ARM64 stock SDK 진단',completed=False)==current['job'],
        'Retained actual diagnostic producer job/API mismatch')
    wrapper=native._json(evidence/'same-signed-sdk-diagnostic.json');pending=native._json(evidence/'pending-native.json')
    checks=('success','processEnvironmentUnchanged','githubEnvironmentUnchanged','signedInputUnchanged','publicCertificateUnchanged',
        'originalPendingUnchanged','trustedCertificateAbsent','originalInstalledEvidenceUnchanged','unsignedOriginalUnchanged','installJsonAbsent',
        'sourceBindingDiffersFromDiagnostic','sdkSliceTempRemoved','executionScriptRootMatchesProduction')
    require(all(wrapper.get(key) is True for key in checks) and wrapper.get('exactSignedInputSha256')==SIGNED_SHA
        and wrapper.get('certificateSha256')==CER_SHA and wrapper.get('originalPendingSha256')==PENDING_SHA
        and wrapper.get('productionImporterSha256')==IMPORTER_SHA and wrapper.get('originalSourceBinding')==SOURCE
        and wrapper.get('diagnosticBinding')==current['binding'] and wrapper.get('actualDiagnosticJob')=='msix-install-arm64'
        and wrapper.get('qualificationFinalized') is False and wrapper.get('wholeSourceQualified') is False and wrapper.get('storeCertified') is False,
        'The exact importer block/environment/cleanup did not pass')
    ast=native._json(evidence/'importer-ast-slice.json');production=(ROOT/'e2e/msix-wack-import.ps1').read_text(encoding='utf-8')
    require(ast.get('productionSha256')==IMPORTER_SHA and ast.get('slicePreservedVerbatim') is True
        and all(ast.get(key) is False for key in ('productionRoleGuardExecuted','validateInputExecuted','finalizeExecuted')),
        'The diagnostic executed producer/current-run/finalizer code')
    require({row['name'] for row in ast['functions']}=={'Assert-OpenGeulSelectedUnsignedPackage','ConvertTo-OpenGeulUtcSecond','Get-OpenGeulNativePublicCertificate'}
        and len(ast['functions'])==3,'Pinned production functions changed')
    for row in ast['functions']+[ast['slice']]:
        name=('importer-fn-'+row['name']+'.ps1.txt') if 'name' in row else 'importer-sdk-slice.ps1.txt'
        raw=(evidence/name).read_bytes();require(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
            and raw==production[row['startOffset']:row['endOffset']].encode('utf-8'),'Production AST slice/function bytes changed')
    require(wrapper.get('executedSliceSha256')==ast['slice']['sha256'],'Executed production SDK slice differs')
    require(wrapper.get('executionMechanism')=='exclusive-dot-source-in-original-e2e'
        and wrapper.get('executedSliceFileSha256')==ast['slice']['sha256']
        and type(wrapper.get('executedSliceFileBytes')) is int and wrapper['executedSliceFileBytes']==ast['slice']['bytes'],
        'The exact original SDK script context/temp byte proof differs')
    require(not (evidence/'install.json').exists(),'A diagnostic must never create a production qualification marker')
    controller=native._json(evidence/'sdk-controller.json')
    tool=native._controller(controller,current['binding'],'source',pending['native'],{'consumer':current['job']})
    summary=native._json(evidence/'wack.json');context=native._json(evidence/'wack-context.json')
    expected=pending['packageIdentity'];actual=native.pair.inspect(evidence/'wack.xml',expected['Name'],expected['Version'],summary['exitCode'])
    require(summary==actual and summary['passed'] is True and summary['status']=='passed' and summary['exitCode']==0,
        'Unmodified complete required/optional SDK report must pass exactly')
    require(context['invocationMode']=='documented-appxpackagepath' and context['inputPackageSha256']==SIGNED_SHA
        and type(context['runnerSessionId']) is int and context['runnerSessionId']>0 and context['runnerSessionId']==context['wackSessionId'],
        'Real SDK exact signed package input/desktop session mismatch')
    report=ET.fromstring((evidence/'wack.xml').read_bytes());tests=report.findall('.//TEST')
    required=sum(row.get('OPTIONAL')!='TRUE' for row in tests);optional=len(tests)-required
    embedded=report.findall('./APPLICATIONS/Installed_Programs/Program[@Source="AppxPackage"]/Indicators/WindowsStoreAppManifestIndicators/PackageManifest/Package/Identity')
    require((required,optional)==(13,11) and report.get('VERSION')==tool['version'] and report.get('TOOLSET_ARCHITECTURE')=='x64'
        and report.get('APP_TYPE')=='Centennial' and report.get('PARTIAL_RUN')=='FALSE' and report.get('OVERALL_RESULT')=='PASS'
        and len(embedded)==1 and dict(embedded[0].attrib)==expected
        and all(len(row.findall('RESULT'))==1 and row.findtext('RESULT')=='PASS' for row in tests),
        'Actual raw SDK required13/optional11/version/ARM identity/full PASS mismatch')
    require(native.sha(directory/'native-input/test-only.msix')==SIGNED_SHA and native.sha(directory/'native-input/test.cer')==CER_SHA
        and native.sha(evidence/'pending-native.json')==PENDING_SHA,'SDK diagnostic changed pinned original input bytes')
    result={'formatVersion':1,'scope':'Stock x64 SDK diagnostic of the SAME signed historical Source81 ARM candidate only',
        'originalCandidateBinding':SOURCE,'actualDiagnosticExecution':current,'source81WholeConclusion':'failure',
        'source81OriginalSdkConclusion':'failure','source81OriginalWackExecuted':False,'sameSignedMsixSha256':SIGNED_SHA,
        'certificateSha256':CER_SHA,'importerSha256':IMPORTER_SHA,'requiredPassed':required,'optionalPassed':optional,
        'rawXmlSha256':native.sha(evidence/'wack.xml'),'sdkVersion':tool['version'],'actualSdkController':controller,
        'runtimeFilesIncludingManifest':pin['runtimeFilesIncludingManifest'],'exactInputBytesUnchanged':True,'cleanupPassed':True,
        'realEnvironmentUnchanged':True,'diagnosticSdkPassed':True,'wholeSourceQualified':False,'storeSubmitted':False,'storeCertified':False}
    save(evidence/'diagnostic-result.json',result)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','verify'));parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();prepare(args.directory) if args.action=='prepare' else verify(args.directory)
    print('동일 원서명 ARM 후보의 진단 범위를 검증했습니다. 전체 릴리스 자격·Store 인증 결과는 아닙니다.')


if __name__=='__main__':main()
