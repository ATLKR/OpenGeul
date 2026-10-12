"""QA 입력 전송의 출처·원본 보존 경계를 검사한다(제품·암호 실행 아님)."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'e2e'),str(ROOT/'scripts'),str(ROOT/'tests')]
from test_hwpx_oracle import package
from wasm_artifacts import expected,FILES

class McpFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.basic=self.root/'inputs';self.password=self.root/'password'
        self.basic.mkdir();self.password.mkdir();self.output=self.root/'output'
        self.binding={'repository':'ATLKR/OpenGeul','sourceCommit':'a'*40,'sourceRun':'12','runAttempt':'2'}
        self.wasm={**expected(),'artifacts':{name:hashlib.sha256(name.encode()).hexdigest() for name in FILES},'generator':'wasm-pack 0.14.0 --target web --release --no-opt'}
        self.wasm_file=self.root/'wasm.json';self.write(self.wasm_file,self.wasm)
        basic=package('OpenGeul fixture 한글 가나다 &amp; &lt;xml&gt; Ω 123')
        (self.basic/'basic.hwpx').write_bytes(basic);(self.password/'prior.hwpx').write_bytes(basic)
        rows=[]
        for first in ('hwp','hwpx'):
            for second in ('hwp','hwpx'):
                name=f'{first}-reopened-plain.{second}';data=b'unit-only synthetic transport data' if second=='hwp' else package('OpenGeul owned encrypted native QA 2026-10-11 — 한글 &amp; &lt;xml&gt; Ω 123')
                (self.password/name).write_bytes(data);rows.append({'inputFormat':first,'outputFormat':second,'path':name,**self.record(data)})
        encryption={'hwp':{'container':'CFB','headerBytes':256,'majorVersion':5,'encrypted':True,'compressed':True,'encryptVersion':4},
                    'hwpx':{'container':'ZIP','algorithm':'ODF AES-256-CBC','kdf':'PBKDF2','keyBytes':32,'iterations':1024,'saltBytes':16,'ivBytes':16,'checksum':'SHA-256-1K','encryptedParts':['Contents/header.xml','Contents/section0.xml','Preview/PrvText.txt','Preview/PrvImage.png','settings.xml']}}
        fixtures=[]
        for format in ('hwp','hwpx'):
            name='protected.'+format;data=('unit-only ciphertext transport '+format).encode();(self.password/name).write_bytes(data)
            fixtures.append({'format':format,'path':name,**self.record(data),'normalOpenRejected':True,'wrongPasswordRejected':True,'correctPasswordTextVerified':True,'normalError':'유효하지 않은 파일: 비밀번호가 필요한 암호 문서입니다 (parse_document_with_password 또는 parse_hwp_with_password 로 비밀번호를 전달하세요)','wrongError':'유효하지 않은 파일: '+('암호 오류' if format=='hwp' else 'HWPX 오류')+': 비밀번호가 일치하지 않거나 암호화 데이터가 손상되었습니다','pageCount':1,'encryption':encryption[format]})
        prior={'container':'ZIP','encrypted':False,'text':'OpenGeul fixture 한글 가나다 & <xml> Ω 123','sections':1}
        self.manifest={'schemaVersion':1,'password':'OpenGeul-native-123456','expectedText':'OpenGeul owned encrypted native QA 2026-10-11 — 한글 & <xml> Ω 123','priorExpectedText':prior['text'],'priorPath':'prior.hwpx','prior':self.record(basic),'fixtures':fixtures,'roundtrips':rows,'engine':{'wasmSha256':self.wasm['artifacts']['rhwp_bg.wasm'],'jsSha256':self.wasm['artifacts']['rhwp.js'],'provenance':self.wasm,'qualification':'final-source-bound'},'generation':{'source':'Public WASM createEmpty/createBlankDocument/insertText/password export APIs','textOwnership':'Task-authored content generated via the library bundled blank template; no user document, external sample, or font program input','generatorSha256':self.digest(ROOT/'e2e/password/generate-password-fixtures.mjs'),'verifierSha256':self.digest(ROOT/'e2e/password/verify-password-fixtures.py'),'priorInspection':prior},'independentVerification':{'passed':True,'path':'independent-verification.json'}}
        verification={'fixtures':encryption,'plaintextRoundtrips':[{'inputFormat':r['inputFormat'],'outputFormat':r['outputFormat'],'inspection':{'container':'CFB','headerBytes':256,'majorVersion':5,'encrypted':False,'compressed':True,'encryptVersion':0} if r['outputFormat']=='hwp' else {'container':'ZIP','encrypted':False,'text':self.manifest['expectedText'],'sections':1}} for r in rows],'prior':prior}
        self.write(self.password/'manifest.json',self.manifest);self.write(self.password/'independent-verification.json',verification)
    def digest(self,path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def record(self,data):return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    def write(self,path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def module(self):
        path=ROOT/'e2e/mcp_fixtures.py';self.assertTrue(path.is_file(),'같은 소스 실행의 QA 전송 검증기가 필요합니다')
        spec=importlib.util.spec_from_file_location('mcp_fixtures_tested',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def stage(self):return self.module().stage(self.basic,self.password,self.wasm_file,self.output,self.binding)
    def test_original_files_preserved_and_verified_with_exact_source_wasm(self):
        proof=self.stage();m=self.module();self.assertEqual(len(proof['files']),11)
        self.assertEqual((self.output/'password-fixtures/manifest.json').read_bytes(),(self.password/'manifest.json').read_bytes())
        self.assertTrue(m.verify(self.output,self.binding,self.wasm)['publicQaOnly'])
        self.assertFalse(proof['fullSourceQualified'])
    def test_arm_qa_uses_distinct_producer_artifact_and_requires_same_architecture(self):
        m=self.module();proof=m.stage(self.basic,self.password,self.wasm_file,self.output,self.binding,architecture='arm64')
        self.assertEqual(proof['artifactName'],'opengeul-mcp-fixtures-arm64-12')
        self.assertEqual(proof['producerJobName'],'native-e2e (windows-11-arm)')
        self.assertTrue(m.verify(self.output,self.binding,self.wasm,architecture='arm64')['publicQaOnly'])
        with self.assertRaises(ValueError):m.verify(self.output,self.binding,self.wasm,architecture='x64')
    def test_unknown_architecture_blocks_before_output(self):
        with self.assertRaises(ValueError):self.module().stage(self.basic,self.password,self.wasm_file,self.output,self.binding,architecture='neutral')
        self.assertFalse(self.output.exists())
    def test_foreign_commit_run_attempt_repository_are_rejected(self):
        self.stage();m=self.module()
        for key,value in [('sourceCommit','b'*40),('sourceRun','13'),('runAttempt','3'),('repository','other/OpenGeul')]:
            with self.subTest(key=key),self.assertRaises(ValueError):m.verify(self.output,{**self.binding,key:value},self.wasm)
    def test_wrong_canonical_wasm_proof_is_rejected(self):
        self.stage();wrong=copy.deepcopy(self.wasm);wrong['artifacts']['rhwp_bg.wasm']='0'*64
        with self.assertRaises(ValueError):self.module().verify(self.output,self.binding,wrong)
    def test_ciphertext_and_transport_manifest_tampering_are_rejected(self):
        self.stage();(self.output/'password-fixtures/protected.hwp').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.module().verify(self.output,self.binding,self.wasm)
    def test_paths_or_duplicate_format_block_before_output(self):
        for change in ({'path':'../secret.hwp'},{'format':'hwpx'}):
            changed=copy.deepcopy(self.manifest);changed['fixtures'][0].update(change);self.write(self.password/'manifest.json',changed)
            with self.assertRaises(ValueError):self.stage()
            self.assertFalse(self.output.exists())
    def test_real_secret_or_unknown_metadata_is_never_staged(self):
        for change in ({'password':'personal-secret'},{'authToken':'personal-secret'},{'expectedText':'personal document'}):
            self.write(self.password/'manifest.json',{**self.manifest,**change})
            with self.assertRaises(ValueError):self.stage()
            self.assertFalse(self.output.exists())
    def test_extra_file_and_case_alias_rejected(self):
        for name in ('private.txt','MANIFEST.JSON'):
            path=self.password/name;path.write_bytes(b'private')
            with self.assertRaises(ValueError):self.stage()
            self.assertFalse(self.output.exists());path.unlink()
    def test_basic_case_alias_and_total_cap_reject_before_output(self):
        alias=self.basic/'BASIC.HWPX';alias.write_bytes((self.basic/'basic.hwpx').read_bytes())
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(self.output.exists());alias.unlink();m=self.module()
        with patch.object(m,'MAX_BYTES',32),self.assertRaises(ValueError):m.stage(self.basic,self.password,self.wasm_file,self.output,self.binding)
        self.assertFalse(self.output.exists())
    def test_symlink_input_or_output_ancestor_rejected(self):
        path=self.password/'protected.hwp';original=path.read_bytes();path.unlink();path.symlink_to(self.basic/'basic.hwpx')
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(self.output.exists());path.unlink();path.write_bytes(original)
        parent=self.root/'link';parent.symlink_to(self.basic,target_is_directory=True)
        with self.assertRaises(ValueError):self.module().stage(self.basic,self.password,self.wasm_file,parent/'out',self.binding)
    def test_existing_or_overlapping_output_rejected_before_copy(self):
        self.output.mkdir()
        with self.assertRaises(ValueError):self.stage()
        self.assertEqual(list(self.output.iterdir()),[])
        with self.assertRaises(ValueError):self.module().stage(self.basic,self.password,self.wasm_file,self.password/'out',self.binding)
    def test_dot_dot_output_alias_cannot_write_inside_original_inputs(self):
        other=self.root/'other';other.mkdir();aliased=other/'..'/self.password.name/'qa-output'
        with self.assertRaises(ValueError):self.module().stage(self.basic,self.password,self.wasm_file,aliased,self.binding)
        self.assertFalse((self.password/'qa-output').exists())
    def test_bounded_file_size_checked_before_read_or_copy(self):
        m=self.module();path=self.password/'protected.hwp'
        with path.open('wb') as stream:stream.truncate(m.MAX_FILE+1)
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(self.output.exists())
    def test_duplicate_json_keys_and_bool_schema_rejected(self):
        (self.password/'manifest.json').write_text('{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaises(ValueError):self.stage()
        changed={**self.manifest,'schemaVersion':True};self.write(self.password/'manifest.json',changed)
        with self.assertRaises(ValueError):self.stage()
    def test_independent_verification_and_basic_original_must_match(self):
        self.write(self.password/'independent-verification.json',{'fixtures':{}})
        with self.assertRaises(ValueError):self.stage()
        self.assertFalse(self.output.exists())
    def test_copy_changed_after_validation_never_publishes_output(self):
        m=self.module();original=m.shutil.copyfile
        def corrupt(source,target):
            result=original(source,target)
            if Path(source).name=='protected.hwp':Path(target).write_bytes(b'changed while copying')
            return result
        with patch.object(m.shutil,'copyfile',corrupt),self.assertRaises(ValueError):m.stage(self.basic,self.password,self.wasm_file,self.output,self.binding)
        self.assertFalse(self.output.exists())

if __name__=='__main__':unittest.main()
