"""같은 ARM 설치 바이트·공개 인증서·생산자 API 결합의 실패 경계를 검증한다."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'e2e'), str(ROOT/'tests')]
import native_wack_transport as transport
import native_split_fixture
import test_release_pair as pair_fixture

CERT = 'MIIByzCCATSgAwIBAgIBATANBgkqhkiG9w0BAQsFADAfMR0wGwYDVQQDDBRPcGVuR2V1bCBEZXZlbG9wbWVudDAeFw0yNjEwMTIxMDAwMDBaFw0yNjEwMTMwOTAwMDBaMB8xHTAbBgNVBAMMFE9wZW5HZXVsIERldmVsb3BtZW50MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDTwewHzd7H4jvpdTlQjzKQ2IOhy6vUCs6Yzv562kufqChCoyil36tEdAzAVnHbIs4UDEpbc3TXLTxQygVl66hOoaPVk3o57bFnq0f5s41AguZ/Ae7fOusEQDyJ0yX3e2V/2l7J6hcxWIITPiZb8FCahPMNdsFVtBs7uQjPHgoSdQIDAQABoxcwFTATBgNVHSUEDDAKBggrBgEFBQcDAzANBgkqhkiG9w0BAQsFAAOBgQBU2OmrfT4UG80SoRLMw9FZLK10sWmZdOFXbVpiAPhfb9IS+1SJI4V/Sf0WT76IyYTnhDHem3CTlyV7IbZfKO4/uHI/iyIWJCLjn8aSMgabgQOcqry59C+Cix/No2NoNa0Qw4SPikrMFOCWHWbL1DvcBV+N8iiUAmGKFnzEogS7iw=='


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binding = {'repository':'ATLKR/OpenGeul','commit':'a'*40,'runId':'123','runAttempt':'1'}
        self.run = {'id':123,'run_attempt':1,'head_sha':'a'*40,'path':'.github/workflows/msix.yml',
            'event':'push','head_branch':'main','status':'in_progress','conclusion':None,
            'run_started_at':'2026-10-12T10:00:00Z',
            'repository':{'id':12345,'full_name':'ATLKR/OpenGeul','private':False},
            'head_repository':{'id':12345,'full_name':'ATLKR/OpenGeul','private':False}}
        self.job = {'id':456,'name':'msix-native-arm64','run_id':123,'run_attempt':1,'head_sha':'a'*40,
            'status':'completed','conclusion':'success','started_at':'2026-10-12T10:01:00Z','completed_at':'2026-10-12T10:03:00Z'}
        self.artifact = {'id':789,'name':'opengeul-native-signed-arm64-123-1','size_in_bytes':100,
            'digest':'sha256:'+'b'*64,'expired':False,'created_at':'2026-10-12T10:02:00Z','updated_at':'2026-10-12T10:02:01Z','expires_at':'2026-10-13T10:02:00Z',
            'workflow_run':{'id':123,'head_sha':'a'*40,'head_branch':'main','repository_id':12345,'head_repository_id':12345}}

    def test_selected_artifact_requires_current_producer_role_and_attempt(self):
        transport.artifact(self.artifact,self.binding,self.run,self.job,self.artifact['name'],transport.MAX_ZIP)
        for change in ({'name':'msix-install-arm64'},{'run_id':124},{'run_attempt':2},{'head_sha':'c'*40},
                       {'status':'completed','conclusion':'skipped'},{'completed_at':'2026-10-12T10:01:30Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                transport.artifact(self.artifact,self.binding,self.run,{**self.job,**change},self.artifact['name'],transport.MAX_ZIP)
        for field,value in [('head_sha','c'*40),('repository_id',999),('head_repository_id',999),('head_branch','fork')]:
            wrong=copy.deepcopy(self.artifact);wrong['workflow_run'][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                transport.artifact(wrong,self.binding,self.run,self.job,self.artifact['name'],transport.MAX_ZIP)

    def test_missing_or_reverse_expiry_never_becomes_an_invented_one_day_window(self):
        for expire in (None,'2026-10-12T10:01:00Z','2026-10-14T10:02:00Z'):
            value=dict(self.artifact)
            if expire is None:value.pop('expires_at')
            else:value['expires_at']=expire
            with self.subTest(expire=expire),self.assertRaises(ValueError):
                transport.artifact(value,self.binding,self.run,self.job,self.artifact['name'],transport.MAX_ZIP)

    def test_signed_msix_can_only_add_packaging_signature_not_change_any_runtime_byte(self):
        files={'AppxManifest.xml':b'<Package/>','OpenGeul.exe':b'MZ editor','Tools/rhwp.exe':b'MZ cli','assets/a.txt':b'font'}
        unsigned=self.root/'unsigned.msix';signed=self.root/'signed.msix'
        def write(path,values):
            with zipfile.ZipFile(path,'w') as z:
                for name,data in values.items():z.writestr(name,data)
        write(unsigned,{**files,'AppxBlockMap.xml':b'old','[Content_Types].xml':b'old'})
        write(signed,{**files,'AppxBlockMap.xml':b'new','[Content_Types].xml':b'new','AppxSignature.p7x':b'signature'})
        self.assertEqual(transport.signed_parity(unsigned,signed),transport.runtime(unsigned))
        for name in files:
            altered={**files,name:files[name]+b'swap','AppxSignature.p7x':b'signature'};write(signed,altered)
            with self.subTest(name=name), self.assertRaises(ValueError):transport.signed_parity(unsigned,signed)
        write(signed,files)
        with self.assertRaises(ValueError):transport.signed_parity(unsigned,signed)

    def test_public_certificate_bytes_subject_eku_and_one_day_lifetime_are_recomputed(self):
        raw=base64.b64decode(CERT);info=transport.certificate(raw)
        self.assertEqual(info['subject'],'CN=OpenGeul Development')
        self.assertEqual(info['thumbprint'],hashlib.sha1(raw).hexdigest().upper())
        self.assertEqual(info['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertTrue(info['publicOnly']);self.assertTrue(info['codeSigning'])
        for wrong in (b'private key',raw[:-1],raw+b'key'):
            with self.subTest(raw=wrong[:10]), self.assertRaises(ValueError):transport.certificate(wrong)

    def test_transport_zip_exact_three_files_never_accepts_pfx_alias_or_expansion(self):
        def archive(files):
            result=io.BytesIO()
            with zipfile.ZipFile(result,'w') as z:
                for name,data in files:z.writestr(name,data)
            return result.getvalue()
        files=[('native-install.json',b'{}'),('test-only.msix',b'MSIX'),('test.cer',base64.b64decode(CERT))]
        for i,wrong in enumerate((files+[('test.pfx',b'secret')],files+[('TEST.CER',b'alias')],files[:-1],
                                 [('prefix/'+n,b) for n,b in files])):
            with self.subTest(case=i),self.assertRaises(ValueError):transport.extract(archive(wrong),self.root/str(i))
        transport.extract(archive(files),self.root/'good')
        self.assertEqual({p.name for p in (self.root/'good').iterdir()},transport.FILES)


class NativeJoinTests(unittest.TestCase):
    def setUp(self):
        self.fixture=pair_fixture.ReleasePairTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.directory=self.fixture.packages['arm64'];self.root=self.fixture.root
        self.unsigned=next(self.directory.glob('*.msix'))
        self.binding={'repository':'ATLKR/OpenGeul','commit':'a'*40,'runId':'1234','runAttempt':'2'}
        install=json.loads((self.fixture.wacks['arm64']/'install.json').read_bytes())
        self.files=transport._files(self.directory)
        self.split,self.installation,self.join,self.raw=native_split_fixture.make_split(self.unsigned,install,self.binding,'source',self.files)
        self.native=self.split['native'];self.origin=self.split['origin']
        with zipfile.ZipFile(self.unsigned) as package:
            import xml.etree.ElementTree as ET
            self.package_identity=dict(ET.fromstring(package.read('AppxManifest.xml')).find('{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity').attrib)
        self.env={**self.fixture.env,'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_JOB':'msix-install-arm64','GITHUB_REF':'refs/heads/main'}
        current={'repository':'ATLKR/OpenGeul','commit':'a'*40,'runId':'1234','runAttempt':'2'}
        self.context={'invocationMode':'documented-appxpackagepath','inputPackageSha256':self.installation['signedTestPackageSha256'],
            'runnerSessionId':1,'wackSessionId':1,'nativeSignedJoin':self.join}
        self.candidate=self.root/'candidate';self.candidate.mkdir()
        transport.extract(self.raw['native'],self.candidate/'input')
        self.candidate=self.candidate/'input'
        (self.candidate/'origin.json').write_bytes(transport.pair.encoded(self.origin)+b'\n')
        self.output=self.root/'final'
        self.unsigned_context=(current,self.unsigned,self.package_identity,self.files)

    def verify(self,installation=None,context=None):
        return transport.verify_split(self.installation if installation is None else installation,
            self.context if context is None else context,self.unsigned,self.package_identity,self.binding,'source',self.files)

    def test_actual_mcp_native_webview_runtime_and_both_artifact_raw_api_maps_join(self):
        self.verify()
        self.assertEqual(self.installation['mcp']['workerIsolation']['batchRecords'],64)
        self.assertEqual(self.native['launch']['nativeArchitecture']['nativeMachine'],0xaa64)
        self.assertEqual(self.split['controller']['tool']['nativeMachine'],0x8664)

    def test_native_missing_failure_old_head_mixed_attempt_and_rehashed_context_are_rejected(self):
        mutators=[lambda d:d.pop('armNativeSplit'),
            lambda d:d['armNativeSplit']['native'].update(success=False),
            lambda d:d['armNativeSplit']['native']['binding'].update(commit='b'*40),
            lambda d:d['armNativeSplit']['origin']['native']['producer'].update(run_attempt=1),
            lambda d:d['armNativeSplit']['origin']['native']['producer'].update(conclusion='skipped'),
            lambda d:d['armNativeSplit']['controller']['tool'].update(processMachine=0xaa64),
            lambda d:d['armNativeSplit']['controller']['tool'].update(path='\\\\remote\\share\\Program Files (x86)\\Windows Kits\\10\\App Certification Kit\\appcert.exe'),
            lambda d:d['armNativeSplit']['controller']['tool'].update(productVersion='10.0.26100.9999'),
            lambda d:d['armNativeSplit']['native'].update(password='never transport a private credential'),
            lambda d:d['armNativeSplit']['native']['cleanup'].update(privateKeyRemoved=False),
            lambda d:d['armNativeSplit']['native']['runtime']['OpenGeul.exe'].update(sha256='0'*64),
            lambda d:d['armNativeSplit']['controller']['signedSignature'].update(thumbprint='0'*40)]
        for mutate in mutators:
            value=copy.deepcopy(self.installation);mutate(value)
            context=copy.deepcopy(self.context)
            if 'armNativeSplit' in value:context['nativeSignedJoin']=transport._context_join(value['armNativeSplit'])
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.verify(value,context)

    def test_retained_failed_cancelled_or_missing_run_phase_is_rejected_even_when_rehashed(self):
        for status,conclusion in [('completed','failure'),('completed','cancelled'),(None,None),('in_progress','success')]:
            value=copy.deepcopy(self.native);value['producer']['run'].update(status=status,conclusion=conclusion)
            with self.subTest(status=status,conclusion=conclusion),self.assertRaises(ValueError):
                transport._producer_proof(value,self.binding,'source')

    def test_current_api_download_validates_exact_original_zips_before_exposing_input(self):
        raw=self.raw;origin=self.origin
        class Backend:
            def get(_,path):
                if path=='actions/runs/1234':return raw['run']
                if path.endswith('/jobs?per_page=100'):return {'total_count':3,'jobs':raw['jobs']}
                if path.endswith('/artifacts?per_page=100'):return {'total_count':2,'artifacts':[origin['unsigned']['artifact'],origin['native']['artifact']]}
                return origin['unsigned']['artifact'] if path=='actions/artifacts/100' else origin['native']['artifact']
            def zip(_,artifact_id):return raw['unsigned'] if artifact_id==100 else raw['native']
        with patch.object(transport,'_unsigned',return_value=self.unsigned_context):
            result=transport.download('source',self.directory,self.root/'download',backend=Backend(),env=self.env)
        self.assertEqual(result,self.origin)
        self.assertEqual({p.name for p in (self.root/'download').iterdir()},transport.FILES|{'origin.json'})
        for key in ('native','unsigned'):
            swapped=dict(raw);swapped[key]=raw[key]+b'byte swap'
            class Swapped(Backend):
                def zip(_,artifact_id):return swapped['unsigned'] if artifact_id==100 else swapped['native']
            destination=self.root/('bad-'+key)
            with patch.object(transport,'_unsigned',return_value=self.unsigned_context),self.assertRaises(ValueError):
                transport.download('source',self.directory,destination,backend=Swapped(),env=self.env)
            self.assertFalse(destination.exists())

    def prepare_output(self):
        with patch.object(transport,'_unsigned',return_value=self.unsigned_context):
            transport.validate_input(self.directory,self.candidate,self.output,env=self.env)
        for name in ('wack.xml','wack.json','wack-context.json'):
            (self.output/name).write_bytes((self.fixture.wacks['arm64']/name).read_bytes())
        context=json.loads((self.output/'wack-context.json').read_bytes())
        context['inputPackageSha256']=self.installation['signedTestPackageSha256']
        (self.output/'wack-context.json').write_bytes(transport.pair.encoded(context))
        (self.output/'sdk-controller.json').write_bytes(transport.pair.encoded(self.split['controller']))

    def finalize(self):
        with patch.object(transport,'_unsigned',return_value=self.unsigned_context):
            return transport.finalize(self.directory,self.candidate,self.output,self.output/'sdk-controller.json',env=self.env)

    def test_native_only_never_creates_final_success_and_original_required_optional_xml_creates_marker_once(self):
        self.prepare_output();self.assertFalse((self.output/'install.json').exists())
        result=self.finalize();self.assertEqual(result,self.installation)
        for name in ('installed-launch.json','installed-cli.json'):
            self.assertEqual((self.output/name).read_bytes(),base64.b64decode(self.native['originalEvidence'][name]['rawBase64']))
        self.verify(result,json.loads((self.output/'wack-context.json').read_bytes()))
        with self.assertRaises(ValueError):self.finalize()

    def test_production_ps_native_writer_json_passes_the_actual_python_core(self):
        powershell=Path('/workspace/OpenGeul-ci-build-progress/.work/powershell746/bin/pwsh')
        if not powershell.is_file():self.skipTest('PowerShell runtime unavailable')
        raw=copy.deepcopy(self.native);raw.pop('runtime');raw.pop('producer')
        record=self.root/'ps-record.json';record.write_bytes(transport.pair.encoded(raw))
        output=self.root/'ps-emitted';output.mkdir()
        (output/'test-only.msix').write_bytes(self.raw['signed']);(output/'test.cer').write_bytes(self.raw['certificate'])
        script=self.root/'emit-native.ps1'
        script.write_text(r'''
param([string]$Source,[string]$Record,[string]$Output)
$ErrorActionPreference='Stop';$tokens=$null;$errors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failure'}
$function=$tree.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Write-OpenGeulNativeResult'},$true)
Invoke-Expression $function.Extent.Text
$value=Get-Content -LiteralPath $Record -Raw | ConvertFrom-Json -AsHashtable
Write-OpenGeulNativeResult -TransportDirectory $Output -Record $value
''',encoding='utf-8')
        result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),
            '-Source',str(ROOT/'e2e/msix-install.ps1'),'-Record',str(record),'-Output',str(output)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        emitted=transport._json(output/'native-install.json')
        self.assertEqual(emitted,raw)
        self.assertEqual(transport._native_core(emitted,self.unsigned,self.binding,self.package_identity),self.installation['signedTestPackageSha256'])

    def test_sdk_partial_optional_warning_input_swap_missing_raw_and_wrong_version_leave_no_final_marker(self):
        self.prepare_output();original={p.name:p.read_bytes() for p in self.output.iterdir()}
        cases=[('wack.xml',lambda b:b.replace(b'PARTIAL_RUN="FALSE"',b'PARTIAL_RUN="TRUE"')),
            ('wack.xml',lambda b:b.replace(b'<RESULT>PASS</RESULT>',b'<RESULT>WARNING</RESULT>')),
            ('wack.xml',lambda b:b.replace(b'10.0.26100.8249',b'10.0.26100.9999')),
            ('wack-context.json',lambda b:b.replace(self.installation['signedTestPackageSha256'].encode(),b'0'*64)),
            ('wack.xml',lambda b:None)]
        for filename,mutate in cases:
            for name,data in original.items():(self.output/name).write_bytes(data)
            changed=mutate(original[filename])
            if changed is None:(self.output/filename).unlink()
            else:(self.output/filename).write_bytes(changed)
            with self.subTest(file=filename),self.assertRaises((ValueError,FileNotFoundError)):self.finalize()
            self.assertFalse((self.output/'install.json').exists())


if __name__=='__main__':unittest.main()
