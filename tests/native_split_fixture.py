"""네트워크·Windows 실행을 주장하지 않는 실제 ZIP/DER/PE 기반 조인 fixture."""
import base64
import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import native_wack_transport as transport
import release_pair as pair

SOURCE_CERT='MIIByzCCATSgAwIBAgIBATANBgkqhkiG9w0BAQsFADAfMR0wGwYDVQQDDBRPcGVuR2V1bCBEZXZlbG9wbWVudDAeFw0yNjEwMTIxMDAwMDBaFw0yNjEwMTMwOTAwMDBaMB8xHTAbBgNVBAMMFE9wZW5HZXVsIERldmVsb3BtZW50MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDTwewHzd7H4jvpdTlQjzKQ2IOhy6vUCs6Yzv562kufqChCoyil36tEdAzAVnHbIs4UDEpbc3TXLTxQygVl66hOoaPVk3o57bFnq0f5s41AguZ/Ae7fOusEQDyJ0yX3e2V/2l7J6hcxWIITPiZb8FCahPMNdsFVtBs7uQjPHgoSdQIDAQABoxcwFTATBgNVHSUEDDAKBggrBgEFBQcDAzANBgkqhkiG9w0BAQsFAAOBgQBU2OmrfT4UG80SoRLMw9FZLK10sWmZdOFXbVpiAPhfb9IS+1SJI4V/Sf0WT76IyYTnhDHem3CTlyV7IbZfKO4/uHI/iyIWJCLjn8aSMgabgQOcqry59C+Cix/No2NoNa0Qw4SPikrMFOCWHWbL1DvcBV+N8iiUAmGKFnzEogS7iw=='
STORE_CERT='MIIB6zCCAVSgAwIBAgIBAjANBgkqhkiG9w0BAQsFADAvMS0wKwYDVQQDDCREN0VFMDVENi1DMDkxLTRGQjEtQkFGOS1EQTRFNjg1MkRBOTcwHhcNMjYxMDEyMTAwMDAwWhcNMjYxMDEzMDkwMDAwWjAvMS0wKwYDVQQDDCREN0VFMDVENi1DMDkxLTRGQjEtQkFGOS1EQTRFNjg1MkRBOTcwgZ8wDQYJKoZIhvcNAQEBBQADgY0AMIGJAoGBALa0dXIDwCmr7abRBMm1OcnLXgTyl0F21XvHc0u1cDglvb6jhtRMCJNABtl2R1MMpzmZwHprWTQSBfd1b9xy9jSqnSUUveQDItBGTTbBomnJMPLg+VbzLGhaAOiVEbFeh/+l+msBjVleuBfvZdJcOrnD3/9yLeLtcb+bYOOVPuijAgMBAAGjFzAVMBMGA1UdJQQMMAoGCCsGAQUFBwMDMA0GCSqGSIb3DQEBCwUAA4GBAHvWIt5y89TewppFAbauGvcXjDFRJH3N6PlyqtbQ8cot4T+IGBRm2RfSmuwtMITjgHIHI5o8irHiZF7nnxJBRxH0/tQooYQrDn6XCP7IL8vWgQ+kmQKdbTm5UfBOyuovZHBexCsLXBHPOZOkZMvLpooIH2MpXEWSq628yhbeVQF2'


def bind_source(package,wack):
    provenance=json.loads((package/'provenance.json').read_bytes())
    binding={'repository':provenance['repository'],'commit':provenance['commit'],'runId':provenance['runId'],
        'runAttempt':provenance['windowsComponents']['runAttempt']}
    install=json.loads((wack/'install.json').read_bytes())
    _,install,join,_=make_split(package/provenance['package'],install,binding,'source',transport._files(package))
    (wack/'install.json').write_bytes(pair.encoded(install)+b'\n')
    context=json.loads((wack/'wack-context.json').read_bytes());context.update(inputPackageSha256=install['signedTestPackageSha256'],nativeSignedJoin=join)
    (wack/'wack-context.json').write_bytes(pair.encoded(context)+b'\n')


def archive(files):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w',compression=zipfile.ZIP_DEFLATED) as result:
        for name,data in sorted(files.items()):result.writestr(name,data)
    return raw.getvalue()


def make_split(unsigned,installation,binding,scope,files):
    installation=dict(installation);installation.pop('armNativeSplit',None)
    with zipfile.ZipFile(unsigned) as z:package={name:z.read(name) for name in z.namelist()}
    raw_signed=archive(package|{'AppxSignature.p7x':b'fixture public signature, not actual Windows signing'})
    signed_sha=hashlib.sha256(raw_signed).hexdigest()
    identity=ET.fromstring(package['AppxManifest.xml']).find('{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity')
    full_name=installation['packageFullName'];helper=pair.ROOT/'e2e/native_architecture.py';helper_sha=hashlib.sha256(helper.read_bytes()).hexdigest()
    hashes=transport.runtime(unsigned)
    native_gui={'architecture':'arm64','processId':200,'imagePath':f'C:\\Program Files\\WindowsApps\\{full_name}\\OpenGeul.exe',
        'peMachine':0xaa64,'processMachine':0,'nativeMachine':0xaa64,'native':True,'runningAtInspection':True,
        'packageFullName':full_name,'sha256':hashes['OpenGeul.exe']['sha256'],'bytes':hashes['OpenGeul.exe']['bytes'],
        'helperSha256':helper_sha,'sourceCommit':binding['commit'],'sourceRun':binding['runId'],'runAttempt':binding['runAttempt']}
    native_gui['webview2Native']={'rootProcessId':200,'architecture':'arm64','helperSha256':helper_sha,
        'processes':[{'processId':201,'parentProcessId':200,'imagePath':'C:\\Edge\\msedgewebview2.exe','peMachine':0xaa64,
            'processMachine':0,'nativeMachine':0xaa64,'sha256':'8'*64,'bytes':256,'runningAtInspection':True}]}
    launch={'success':True,'architecture':'arm64','processId':200,'packageFullName':full_name,'executable':native_gui['imagePath'],
        'windowTitle':'OpenGeul','nativeArchitecture':native_gui}
    native_cli={key:value for key,value in native_gui.items() if key!='webview2Native'}
    native_cli.update(processId=202,imagePath=f'C:\\Program Files\\WindowsApps\\{full_name}\\Tools\\rhwp.exe',
        sha256=hashes['Tools/rhwp.exe']['sha256'],bytes=hashes['Tools/rhwp.exe']['bytes'],runningAtInspection=False)
    cli={'success':True,'packageFullName':full_name,'exitCode':0,'helpBytes':10,'helpSha256':hashlib.sha256(b'rhwp help\n').hexdigest(),
        'nativeArchitecture':native_cli,'mcp':installation['mcp']}
    installation=dict(installation,architecture='arm64',uninstalled=True,fileTypes=['.hwp','.hwpx'],signedTestPackageSha256=signed_sha,
        scope='ARM64 native install fixture; SDK result is a separate mandatory gate')
    cert_raw=base64.b64decode(SOURCE_CERT if scope=='source' else STORE_CERT);cert=transport.certificate(cert_raw)
    cert.update(signatureStatus='Valid',signerThumbprint=cert['thumbprint'])
    run={'id':int(binding['runId']),'run_attempt':int(binding['runAttempt']),'head_sha':binding['commit'],
        'head_branch':'main','path':'.github/workflows/msix.yml' if scope=='source' else '.github/workflows/store-package.yml',
        'event':'push' if scope=='source' else 'workflow_dispatch','status':'in_progress','conclusion':None,'run_started_at':'2026-10-12T10:00:00Z',
        'repository':{'id':1,'full_name':'ATLKR/OpenGeul','private':False},'head_repository':{'id':1,'full_name':'ATLKR/OpenGeul','private':False}}
    def job(name,jid,start,end=None):
        return {'id':jid,'name':name,'run_id':run['id'],'run_attempt':run['run_attempt'],'head_sha':binding['commit'],
            'started_at':start,'completed_at':end,'status':'completed' if end else 'in_progress','conclusion':'success' if end else None}
    source_job=job('build-arm64' if scope=='source' else 'package',10,'2026-10-12T10:00:01Z','2026-10-12T10:01:00Z')
    native_job=job('msix-native-arm64' if scope=='source' else 'store-native-arm64',20,'2026-10-12T10:01:01Z')
    completed_native=job(native_job['name'],20,native_job['started_at'],'2026-10-12T10:05:00Z')
    consumer=job('msix-install-arm64' if scope=='source' else 'Store WACK (arm64)',30,'2026-10-12T10:06:00Z')
    def metadata(name,aid,raw,created):
        value={'id':aid,'name':name,'size_in_bytes':len(raw),'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),'expired':False,
            'created_at':created,'updated_at':created,'expires_at':created.replace('2026-10-12','2026-10-13'),'workflow_run':{'id':run['id'],'head_sha':binding['commit'],'head_branch':'main',
                'repository_id':1,'head_repository_id':1}}
        api=pair.encoded(value)
        proof={'rawBase64':base64.b64encode(api).decode(),'bytes':len(api),'sha256':hashlib.sha256(api).hexdigest()}
        return value,proof
    unsigned_raw=archive({name:(unsigned.parent/name).read_bytes() for name in files})
    source_name=('opengeul-windows-arm64-' if scope=='source' else 'opengeul-store-')+binding['runId']
    source_meta,source_raw=metadata(source_name,100,unsigned_raw,'2026-10-12T10:00:30Z')
    source_origin={'artifact':source_meta,'metadata':source_raw,'producer':source_job}
    native={'formatVersion':1,'success':True,'scope':'native-arm64-install-only','binding':binding,'completedAt':'2026-10-12T10:04:00Z',
        'installation':installation,'launch':launch,'cli':cli,'certificate':cert,
        'cleanup':dict.fromkeys(('candidateUninstalled','unsignedUnchanged','privateKeyRemoved','trustedCertificateRemoved','frameworksRemoved'),True),
        'runtime':hashes,'producer':{'scope':scope,'run':run,'job':native_job,'unsigned':source_origin,'unsignedFiles':files}}
    native['originalEvidence']={}
    for name,value in [('installed-launch.json',launch),('installed-cli.json',cli)]:
        raw=pair.encoded(value)+b'\n';native['originalEvidence'][name]={'rawBase64':base64.b64encode(raw).decode(),
            'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    native_json=pair.encoded(native)+b'\n';native_raw=archive({'native-install.json':native_json,'test-only.msix':raw_signed,'test.cer':cert_raw})
    native_name=('opengeul-native-signed-arm64-' if scope=='source' else 'opengeul-store-native-signed-arm64-')+binding['runId']+'-'+binding['runAttempt']
    native_meta,native_metadata_raw=metadata(native_name,200,native_raw,'2026-10-12T10:04:30Z')
    origin={'formatVersion':1,'scope':scope,'binding':binding,'native':{'artifact':native_meta,'metadata':native_metadata_raw,'producer':completed_native},
        'unsigned':source_origin,'consumer':consumer,'nativeJsonSha256':hashlib.sha256(native_json).hexdigest()}
    controller={'binding':binding,'job':'msix-install-arm64' if scope=='source' else 'store-wack','observedAt':'2026-10-12T10:07:00Z',
        'host':{'architecture':'x64','nativeMachine':0x8664,'controller':{'processId':10,'processMachine':0,'architecture':'x64','native':True}},
        'tool':{'path':'C:\\Program Files (x86)\\Windows Kits\\10\\App Certification Kit\\appcert.exe','sha256':'4'*64,'bytes':50088,
            'version':'10.0.26100.8249','fileVersion':'10.0.26100.8249 (WinBuild.160101.0800)','productVersion':'10.0.26100.8249',
            'signatureStatus':'Valid','signer':'Microsoft Corporation',
            'signerSubject':'CN=Microsoft Windows, O=Microsoft Corporation','peMachine':0x8664,'processMachine':0,'nativeMachine':0x8664,
            'processId':300,'ordinaryExit':True,'helpExitCode':-1},
        'signedSignature':{'status':'Valid','thumbprint':cert['thumbprint'],'certificateSha256':cert['sha256']}}
    split={'formatVersion':1,'scope':scope,'binding':binding,'native':native,'origin':origin,'controller':controller}
    return split,dict(installation,armNativeSplit=split),transport._context_join(split),{
        'unsigned':unsigned_raw,'native':native_raw,'signed':raw_signed,'certificate':cert_raw,'jobs':[source_job,completed_native,consumer],'run':run}
