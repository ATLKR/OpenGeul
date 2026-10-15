"""Same-run owned advanced INPUT admission; never executes Windows or product UI."""
from pathlib import Path
import contextlib,copy,hashlib,importlib.util,io,json,os,shutil,stat,subprocess,sys,tempfile,unittest,zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'e2e'),str(ROOT/'tests')]
import test_mcp_qa_download,test_store_package,test_ui_contract
import ui_contract,wasm_artifacts

class Backend:
    def __init__(self,owner):self.owner=owner;self.calls=[]
    def get(self,path):self.calls.append(path);return copy.deepcopy(self.owner.responses[path])
    def zip(self,artifact_id):self.calls.append(('zip',artifact_id));return self.owner.archives[artifact_id]

class NativeAdvancedInputTests(unittest.TestCase):
    def setUp(self):
        self.context=test_mcp_qa_download.McpQaDownloadTests('runTest');self.context.setUp();self.addCleanup(self.context.doCleanups)
        self.root=self.context.root;self.package=self.context.package;self.env=self.context.env
        self.fixture_root=self.root/'native-inputs';self.fixtures=self.fixture_root/'e2e-fixtures';self.fixtures.mkdir(parents=True)
        for name in ('basic.hwp','basic.hwpx','blank.hwp','blank.hwpx','unicode.hwp','unicode.hwpx','missing-font.hwpx','missing-font.hwp','invalid.hwpx','paragraphs.hwpx'):
            (self.fixtures/name).write_bytes(('owned native baseline '+name).encode())
        for name in ('structured.hwp','structured.hwpx','checkerboard.png','generation.json'):
            p=self.fixture_root/'structured-fixtures'/name;p.parent.mkdir(exist_ok=True);p.write_bytes(name.encode())
        (self.fixture_root/'structured-input-binding.json').write_text('{}')
        self.baseline=self.inventory(self.fixture_root);self.assertEqual(len(self.baseline),15)
        self.receipt=self.root/'evidence/native-advanced-inputs.json'
        self.wasm=self.root/'wasm-input';self.wasm.mkdir()
        self.wasm_files={n:(b'\0asm\1\0\0\0' if n=='rhwp_bg.wasm' else json.dumps({'version':wasm_artifacts.expected()['upstream']['rhwp']['version']}).encode() if n=='package.json' else ('owned '+n).encode())for n in wasm_artifacts.FILES}
        self.wasm_proof={**wasm_artifacts.expected(),'artifacts':{n:hashlib.sha256(v).hexdigest()for n,v in self.wasm_files.items()},'generator':'wasm-pack 0.14.0 --target web --release --no-opt'}
        self.wasm_files['OPEN_GEUL_WASM.json']=(json.dumps(self.wasm_proof,indent=2)+'\n').encode()
        for n,v in self.wasm_files.items():(self.wasm/n).write_bytes(v)
        p=self.package/'provenance.json';prov=json.loads(p.read_bytes());prov['sourceParity'].update(wasmRebuild=self.wasm_proof,equationDialogFocus=test_ui_contract.frontend_binding()['equationDialogFocus']);p.write_text(json.dumps(prov)+'\n');test_store_package.StorePackageTests().checksum_directory(self.package)
        self.transport={**{k:self.env[e]for k,e in [('repository','GITHUB_REPOSITORY'),('sourceCommit','GITHUB_SHA'),('sourceRun','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]},'architecture':'x64','sourceContractSha256':prov['windowsComponents']['sourceContractSha256'],'editorProvenanceSha256':prov['windowsComponents']['components']['editor']['provenanceSha256']}
        (self.fixture_root/'structured-input-binding.json').write_text(json.dumps(self.transport));self.baseline=self.inventory(self.fixture_root)
        self.advanced={p.name:p.read_bytes()for p in (ROOT/'tests/fixtures/advanced-owned').iterdir()if p.is_file()}
        provenance=json.loads(self.advanced['provenance.json']);provenance.pop('sourceLoadability',None);provenance['frontendSource']=test_ui_contract.frontend_binding();provenance['vendorWasmSha256']=self.wasm_proof['artifacts']['rhwp_bg.wasm'];self.advanced['provenance.json']=(json.dumps(provenance)+'\n').encode()
        self.assertEqual(len(self.advanced),14)
        self.browser={**{'e2e-fixtures/advanced-owned/'+n:v for n,v in self.advanced.items()},
            **{'e2e-fixtures/'+n:b'owned unused baseline'for n in ('basic.hwp','basic.hwpx','blank.hwp','blank.hwpx','invalid.hwpx','missing-font.hwp','missing-font.hwpx','paragraphs.hwp','paragraphs.hwpx','unicode.hwp','unicode.hwpx')},
            **{'hop/apps/studio-host/dist/'+n:b'owned unused browser dist'for n in ('index.html','favicon.ico','opengeul.ico','images/icon_small_ko.svg','images/icon_small_ko_dark.svg','assets/index-abcdef12.js','assets/index-abcdef12.css','assets/dist-js-abcdef12.js','assets/event-abcdef12.js','assets/rhwp_bg-abcdef12.wasm','assets/webviewWindow-abcdef12.js')}}
        self.run=copy.deepcopy(self.context.run);self.producer={**self.context.job,'name':'wasm'}
        self.archives={67:self.zip(self.browser),68:self.zip(self.wasm_files)}
        self.artifacts={i:{**self.context.artifact,'id':i,'name':('opengeul-browser-inputs-'if i==67 else 'opengeul-wasm-')+'123'}for i in self.archives}
        self.responses={};self.refresh();self.backend=Backend(self)

    @staticmethod
    def inventory(folder):return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()for p in folder.rglob('*')if p.is_file()}
    @staticmethod
    def zip(files):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED)as z:
            for n,v in files.items():z.writestr(n,v)
        return out.getvalue()
    def refresh(self):
        for i,raw in self.archives.items():self.artifacts[i].update(size_in_bytes=len(raw),digest='sha256:'+hashlib.sha256(raw).hexdigest())
        self.responses={'actions/runs/123':self.run,'actions/runs/123/attempts/1/jobs?per_page=100':{'total_count':1,'jobs':[self.producer]},'actions/runs/123/artifacts?per_page=100':{'total_count':2,'artifacts':list(self.artifacts.values())},**{'actions/artifacts/'+str(i):a for i,a in self.artifacts.items()}}
    def module(self):
        p=ROOT/'e2e/native_advanced_inputs.py';self.assertTrue(p.is_file(),'Native jobs need verified same-run advanced input staging before the unchanged GUI consumer')
        spec=importlib.util.spec_from_file_location('native_advanced_inputs_tested',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def stage(self):return self.module().stage(self.package,self.wasm,self.fixtures,self.receipt,backend=self.backend,env=self.env)
    def rejected(self):
        with self.assertRaises((ValueError,OSError,zipfile.BadZipFile)):self.stage()
        self.assertEqual(self.inventory(self.fixture_root),self.baseline);self.assertFalse(self.receipt.exists())

    def test_native_fifteen_file_producer_then_same_run_advanced_subtree_feeds_unchanged_consumer(self):
        with self.assertRaisesRegex(ValueError,'input provenance is missing'):ui_contract.frontend_source_binding(self.fixtures,ROOT)
        receipt=self.stage()
        self.assertEqual(ui_contract.frontend_source_binding(self.fixtures,ROOT),test_ui_contract.frontend_binding())
        after=self.inventory(self.fixture_root);self.assertEqual({k:after[k]for k in self.baseline},self.baseline)
        self.assertEqual(len(after),29);self.assertEqual(receipt['copiedFiles'],{n:{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()}for n,v in self.advanced.items()})
        self.assertFalse(receipt['productExecuted']);self.assertFalse(receipt['sourceQualified'])
        code="import sys;sys.path.insert(0,"+repr(str(ROOT/'e2e'))+");from test_hop_followups import suite;from ui_contract import exact_ids,discovered_ids;ids=discovered_ids(suite());exact_ids(ids,'native');print(len(ids))"
        discovery=subprocess.run([sys.executable,'-c',code],env={**os.environ,'E2E_MODE':'native','E2E_FIXTURES':str(self.fixtures),'E2E_OUTPUT':str(self.root/'gui-output'),'E2E_EXE':str(self.root/'not-executed.exe')},capture_output=True,text=True,timeout=30)
        self.assertEqual(discovery.returncode,0,discovery.stderr);self.assertEqual(discovery.stdout.strip(),'42')
        self.assertEqual(len(ui_contract.manifest('native')),42)

    def test_wrong_head_run_attempt_and_successful_wasm_producer_are_rejected(self):
        mutations=[lambda:self.run.update(head_sha='b'*40),lambda:self.run.update(id=124),lambda:self.run.update(run_attempt=2),lambda:self.producer.update(conclusion='failure'),lambda:self.producer.update(run_attempt=2),lambda:self.producer.update(head_sha='b'*40),lambda:self.producer.update(name='browser-e2e (chromium)')]
        for change in mutations:
            with self.subTest(change=change):
                run,producer=copy.deepcopy(self.run),copy.deepcopy(self.producer);change();self.refresh();self.rejected();self.run,self.producer=run,producer

    def test_artifact_identity_creation_window_server_digest_and_before_after_metadata_are_required(self):
        for role in (67,68):
            for key,value in [('name','other-123'),('expired',True),('created_at','2026-10-11T00:00:00Z'),('workflow_run',{'id':124,'head_sha':'a'*40}),('digest','sha256:'+'0'*64)]:
                with self.subTest(role=role,key=key):
                    old=copy.deepcopy(self.artifacts[role]);self.refresh();self.artifacts[role][key]=value;self.rejected();self.artifacts[role]=old
        self.refresh();owner=self
        class Changed(Backend):
            def get(self,path):
                value=super().get(path)
                if path=='actions/artifacts/67':value['updated_at']='2026-10-12T00:02:02Z'
                return value
        self.backend=Changed(owner);self.rejected()

    def test_payload_helper_wasm_xml_and_hash_mismatches_are_rejected_without_baseline_changes(self):
        for change in ('helper','frontend-source','generated-hash','wasm','zip','xml','extra','missing'):
            with self.subTest(change=change):
                files=copy.deepcopy(self.advanced);p=json.loads(files['provenance.json'])
                if change=='helper':p['frontendSource']['helperSha256']['scripts/equation_dialog_focus.py']='0'*64
                elif change=='frontend-source':p['frontendSource']['preparedFiles'][next(iter(p['frontendSource']['preparedFiles']))]='0'*64
                elif change=='generated-hash':p['generated']['owned-blank.hwpx']='0'*64
                elif change=='wasm':p['vendorWasmSha256']='0'*64
                elif change=='zip':
                    files['owned-blank.hwpx']=b'not a ZIP';p['generated']['owned-blank.hwpx']=hashlib.sha256(files['owned-blank.hwpx']).hexdigest()
                elif change=='xml':
                    with zipfile.ZipFile(io.BytesIO(files['owned-blank.hwpx']))as z:parts={n:z.read(n)for n in z.namelist()}
                    section=ET.fromstring(parts['Contents/section0.xml']);section.tag='{urn:wrong}sec';parts['Contents/section0.xml']=ET.tostring(section);files['owned-blank.hwpx']=self.zip(parts);p['generated']['owned-blank.hwpx']=hashlib.sha256(files['owned-blank.hwpx']).hexdigest()
                elif change=='extra':files['foreign.txt']=b'foreign'
                else:files.pop('owned-equation.hwpx')
                files['provenance.json']=json.dumps(p).encode();other={n:v for n,v in self.browser.items()if not n.startswith('e2e-fixtures/advanced-owned/')};self.archives[67]=self.zip({**other,**{'e2e-fixtures/advanced-owned/'+n:v for n,v in files.items()}});self.refresh();self.rejected()

    def test_local_wasm_six_and_package_frontend_source_must_match(self):
        (self.wasm/'rhwp.js').write_bytes(b'changed');self.rejected();(self.wasm/'rhwp.js').write_bytes(self.wasm_files['rhwp.js'])
        p=self.package/'provenance.json';v=json.loads(p.read_bytes());v['sourceParity']['equationDialogFocus']['helperSha256']='0'*64;p.write_text(json.dumps(v));test_store_package.StorePackageTests().checksum_directory(self.package);self.rejected()

    def test_native_input_runtime_source_and_editor_commitments_cannot_be_replaced(self):
        path=self.fixture_root/'structured-input-binding.json'
        for key,value in [('sourceCommit','b'*40),('sourceRun','124'),('runAttempt','2'),('architecture','arm64'),('sourceContractSha256','0'*64),('editorProvenanceSha256','0'*64)]:
            with self.subTest(key=key):
                row={**self.transport,key:value};path.write_text(json.dumps(row));self.baseline=self.inventory(self.fixture_root);self.rejected()

    def test_metadata_is_fixed_again_after_the_actual_archive_read(self):
        owner=self
        class ChangedAfter(Backend):
            def get(self,path):
                value=super().get(path)
                if path=='actions/artifacts/67'and ('zip',67)in self.calls:value['updated_at']='2026-10-12T00:02:02Z'
                return value
        self.backend=ChangedAfter(owner);self.rejected();self.assertIn(('zip',67),self.backend.calls)

    def test_failed_admission_retains_finite_stage_without_exception_or_response_text(self):
        self.run['head_sha']='b'*40;self.refresh();module=self.module()
        with self.assertRaises(ValueError)as caught:module.stage(self.package,self.wasm,self.fixtures,self.receipt,backend=self.backend,env=self.env)
        self.assertEqual(getattr(caught.exception,'_native_input_stage',None),'source-run')
        self.assertEqual(module.diagnostic(caught.exception)['stage'],'source-run')
        error=ValueError('SECRET raw response https://private.invalid/token')
        error._native_input_stage='SECRET raw stage'
        output=io.StringIO()
        with contextlib.redirect_stderr(output):module.emit_failure(error)
        raw=output.getvalue();row=json.loads(raw)
        self.assertEqual(row['stage'],'boundary');self.assertEqual(row['code'],'validation');self.assertNotIn('SECRET',raw);self.assertNotIn('http',raw);self.assertLessEqual(len(raw.encode()),1024)
        self.assertEqual(self.inventory(self.fixture_root),self.baseline);self.assertFalse(self.receipt.exists())

    def test_single_page_api_inventory_cannot_hide_a_truncated_run(self):
        self.responses['actions/runs/123/artifacts?per_page=100']['total_count']=101;self.rejected()

    def test_original_crc_and_nonregular_archive_members_are_rejected(self):
        stored=io.BytesIO()
        with zipfile.ZipFile(stored,'w',zipfile.ZIP_STORED)as z:
            for n,v in self.browser.items():z.writestr(n,v)
        raw=bytearray(stored.getvalue())
        with zipfile.ZipFile(io.BytesIO(raw))as z:
            entry=z.infolist()[0];at=entry.header_offset+30+len(entry.filename.encode())+len(entry.extra)
        raw[at]^=1;self.archives[67]=bytes(raw);self.refresh();self.rejected()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w')as z:
            for n,v in self.browser.items():
                info=zipfile.ZipInfo(n)
                if n.endswith('/provenance.json'):info.external_attr=(stat.S_IFLNK|0o777)<<16
                z.writestr(info,v)
        self.archives[67]=out.getvalue();self.refresh();self.rejected()

    def test_unsafe_unknown_members_symlink_destination_and_existing_destination_are_refused(self):
        for name in ('../escape','e2e-fixtures/advanced-owned/../escape','foreign.txt','e2e-fixtures/advanced-owned/FOREIGN.HWPX'):
            with self.subTest(name=name):self.archives[67]=self.zip({**self.browser,name:b'foreign'});self.refresh();self.rejected()
        self.archives[67]=self.zip(self.browser);self.refresh();dest=self.fixtures/'advanced-owned';dest.mkdir();self.baseline=self.inventory(self.fixture_root);self.rejected();dest.rmdir()
        external=self.root/'external';external.mkdir();dest.symlink_to(external,target_is_directory=True)
        try:self.rejected()
        finally:dest.unlink()

if __name__=='__main__':unittest.main()
