"""같은 실행 QA ZIP의 서버 SHA·성공 생산자·attempt·안전한 추출 경계를 확인한다."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'e2e'), str(ROOT/'tests')]
import mcp_fixtures
import test_mcp_fixtures
import test_store_package
import release_pair
import store_package
from buildkit import manifest


class Backend:
    def __init__(self, owner): self.owner = owner; self.calls = []
    def get(self, path):
        self.calls.append(path)
        return copy.deepcopy(self.owner.responses[path])
    def zip(self, artifact_id):
        self.calls.append(('zip', artifact_id)); return self.owner.archive


class McpQaDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.output = self.root/'mcp-qa'
        self.qa = test_mcp_fixtures.McpFixtureTests('runTest'); self.qa.setUp(); self.addCleanup(self.qa.doCleanups)
        self.binding = {**self.qa.binding, 'sourceRun': '123', 'runAttempt': '1'}
        mcp_fixtures.stage(self.qa.basic, self.qa.password, self.qa.wasm_file,
                           self.qa.output, self.binding)
        self.env = {'GITHUB_REPOSITORY':'ATLKR/OpenGeul', 'GITHUB_SHA':'a'*40,
                    'GITHUB_RUN_ID':'123', 'GITHUB_RUN_ATTEMPT':'1'}
        maker = test_store_package.StorePackageTests('runTest')
        original = maker.dual_release_directory(self.root/'source-fixture')
        self.package = original.parent/'x64'
        for arch in ('x64','arm64'):
            folder = original.parent/arch
            path = folder/'provenance.json'; value = json.loads(path.read_bytes())
            value['sourceParity']['wasmRebuild'] = self.qa.wasm
            path.write_text(json.dumps(value)+'\n'); maker.checksum_directory(folder)
        self.run = {'id':123,'run_number':29,'run_attempt':1,'head_sha':'a'*40,
            'repository':{'full_name':'ATLKR/OpenGeul','private':False},
            'head_repository':{'full_name':'ATLKR/OpenGeul','private':False},
            'path':'.github/workflows/msix.yml','event':'push','status':'in_progress',
            'conclusion':None,'run_started_at':'2026-10-12T00:00:00Z'}
        self.job = {'id':45,'name':'native-e2e (windows-2025)','run_id':123,'run_attempt':1,
            'head_sha':'a'*40,'status':'completed','conclusion':'success',
            'started_at':'2026-10-12T00:01:00Z','completed_at':'2026-10-12T00:03:00Z'}
        self.archive = self.make_zip()
        self.artifact = {'id':67,'name':'opengeul-mcp-fixtures-123','size_in_bytes':len(self.archive),
            'digest':'sha256:'+hashlib.sha256(self.archive).hexdigest(),'expired':False,
            'created_at':'2026-10-12T00:02:00Z','updated_at':'2026-10-12T00:02:01Z',
            'workflow_run':{'id':123,'head_sha':'a'*40}}
        self.responses = {}; self.refresh(); self.backend = Backend(self)

    def refresh(self):
        self.responses['actions/runs/123'] = self.run
        self.responses['actions/runs/123/attempts/1/jobs?per_page=100'] = {'total_count':1,'jobs':[self.job]}
        self.responses['actions/runs/123/artifacts?per_page=100'] = {'total_count':1,'artifacts':[self.artifact]}
        self.responses['actions/artifacts/67'] = self.artifact

    def make_zip(self, extra=None, *, transform=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.qa.output.rglob('*')):
                if path.is_file():
                    name = path.relative_to(self.qa.output).as_posix()
                    archive.writestr(transform(name) if transform else name,path.read_bytes())
            if extra: archive.writestr(*extra)
        return output.getvalue()

    def module(self):
        path = ROOT/'scripts/mcp_qa_download.py'
        self.assertTrue(path.is_file(),'같은 실행 artifact 다운로드 wrapper가 필요합니다')
        spec = importlib.util.spec_from_file_location('mcp_qa_download_tested',path)
        value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value

    def download(self):
        return self.module().download_source(self.package,self.output,backend=self.backend,env=self.env)

    def pr_context(self):
        """실제 PR API head와 checkout merge가 다른, 현재 열린 PR의 합성 API 형태."""
        base,head='c'*40,'b'*40
        repo={'id':100,'full_name':'ATLKR/OpenGeul','private':False}
        event={'repository':repo,'number':19,'pull_request':{'id':1900,'number':19,
            'base':{'sha':base,'ref':'main','repo':repo},
            'head':{'sha':head,'ref':'codex/pr-candidate','repo':repo}}}
        self.event_path=self.root/'event.json';self.event_path.write_text(json.dumps(event))
        self.env.update(GITHUB_EVENT_NAME='pull_request',GITHUB_REF='refs/pull/19/merge',
            GITHUB_HEAD_REF='codex/pr-candidate',GITHUB_BASE_REF='main',GITHUB_EVENT_PATH=str(self.event_path))
        self.run.update(event='pull_request',head_sha=head,head_branch='codex/pr-candidate',pull_requests=[{
            'id':1900,'number':19,'base':{'sha':base,'ref':'main','repo':{'id':100}},
            'head':{'sha':head,'ref':'codex/pr-candidate','repo':{'id':100}}}])
        self.run['repository']['id']=100
        self.job['head_sha']=head;self.artifact['workflow_run']['head_sha']=head;self.refresh()
        self.responses['commits/'+'a'*40]={'sha':'a'*40,'parents':[{'sha':base},{'sha':head}]}
        return event

    def rejected(self):
        with self.assertRaises(ValueError): self.download()
        self.assertFalse(self.output.exists()); self.assertFalse(self.output.with_name('mcp-qa-origin').exists())

    def test_in_progress_source_uses_real_package_parity_and_unmocked_fixture_verify(self):
        self.download()
        self.assertTrue(mcp_fixtures.verify(self.output,self.binding,self.qa.wasm)['publicQaOnly'])
        origin = self.output.with_name('mcp-qa-origin')
        self.assertEqual((origin/'original.zip').read_bytes(),self.archive)
        receipt = json.loads((origin/'receipt.json').read_bytes())
        self.assertEqual(receipt['originalZip']['sha256'],hashlib.sha256(self.archive).hexdigest())
        self.assertEqual(receipt['artifact']['id'],67)
        self.assertEqual({p.relative_to(self.output).as_posix() for p in self.output.rglob('*') if p.is_file()},
                         mcp_fixtures.PAYLOAD_FILES|{mcp_fixtures.MANIFEST})

    def test_current_pr_merge_preserves_source_sha_and_separately_proves_api_head(self):
        self.pr_context();self.download()
        self.assertTrue(mcp_fixtures.verify(self.output,self.binding,self.qa.wasm)['publicQaOnly'])
        receipt=json.loads((self.output.with_name('mcp-qa-origin')/'receipt.json').read_bytes())
        self.assertEqual(receipt['sourceCommit'],'a'*40);self.assertEqual(receipt['run']['head_sha'],'b'*40)
        self.assertEqual(receipt['pullRequestBinding'],{'number':19,'id':1900,'mergeCommit':'a'*40,
            'apiHeadCommit':'b'*40,'baseCommit':'c'*40,'headRepositoryId':100,'baseRepositoryId':100})

    def test_arm64_public_fork_pr_retains_merge_identity_and_its_own_qa_producer(self):
        event=self.pr_context();event['pull_request']['head']['repo']={**event['pull_request']['head']['repo'],
            'id':101,'full_name':'contributor/OpenGeul'}
        self.event_path.write_text(json.dumps(event));self.run['pull_requests'][0]['head']['repo']['id']=101
        self.job['name']='native-e2e (windows-11-arm)';self.artifact['name']='opengeul-mcp-fixtures-arm64-123'
        self.qa.output.rename(self.qa.output.with_name('old'))
        mcp_fixtures.stage(self.qa.basic,self.qa.password,self.qa.wasm_file,self.qa.output,self.binding,architecture='arm64')
        self.archive=self.make_zip();self.artifact.update(size_in_bytes=len(self.archive),digest='sha256:'+hashlib.sha256(self.archive).hexdigest());self.refresh()
        self.module().download_source(self.package.with_name('arm64'),self.output,backend=self.backend,env=self.env)
        self.assertTrue(mcp_fixtures.verify(self.output,self.binding,self.qa.wasm,architecture='arm64')['publicQaOnly'])
        receipt=json.loads((self.output.with_name('mcp-qa-origin')/'receipt.json').read_bytes())
        self.assertEqual(receipt['sourceCommit'],'a'*40);self.assertEqual(receipt['pullRequestBinding']['headRepositoryId'],101)

    def test_pr_merge_requires_exact_two_ordered_parent_shas(self):
        self.pr_context();path='commits/'+'a'*40
        for commit in ({'sha':'a'*40,'parents':[{'sha':'b'*40},{'sha':'c'*40}]},
                {'sha':'a'*40,'parents':[{'sha':'c'*40}]},
                {'sha':'a'*40,'parents':[{'sha':'c'*40},{'sha':'b'*40},{'sha':'d'*40}]},
                {'sha':'a'*40,'parents':[{'sha':'d'*40},{'sha':'b'*40}]},
                {'sha':'d'*40,'parents':[{'sha':'c'*40},{'sha':'b'*40}]}):
            with self.subTest(commit=commit):self.responses[path]=commit;self.rejected()

    def test_pr_requires_current_single_association_and_head_base_ref_repositories(self):
        self.pr_context();original=copy.deepcopy(self.run)
        changes=[lambda r:r.update(pull_requests=[]),lambda r:r['pull_requests'].append(copy.deepcopy(r['pull_requests'][0])),
            lambda r:r['pull_requests'][0].update(number=20),lambda r:r['pull_requests'][0].update(id=True),
            lambda r:r['pull_requests'][0]['head'].update(sha='d'*40),
            lambda r:r['pull_requests'][0]['base'].update(sha='d'*40),
            lambda r:r['pull_requests'][0]['base']['repo'].update(id=101),
            lambda r:r['pull_requests'][0]['head']['repo'].update(id=101),
            lambda r:r['repository'].update(id=101),
            lambda r:r.update(head_branch='foreign')]
        for change in changes:
            with self.subTest(change=change):
                self.run=copy.deepcopy(original);change(self.run);self.refresh();self.rejected()

    def test_pr_requires_exact_current_execution_environment_and_event(self):
        self.pr_context();original=dict(self.env)
        for key,value in [('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/pull/20/merge'),
                ('GITHUB_REF','refs/pull/19/head'),('GITHUB_REF',True),('GITHUB_HEAD_REF','foreign'),('GITHUB_BASE_REF','other'),
                ('GITHUB_SHA','d'*40),('GITHUB_RUN_ID','999'),('GITHUB_RUN_ATTEMPT','2')]:
            with self.subTest(key=key):self.env=dict(original,**{key:value});self.rejected()
        self.env=original
        event=json.loads(self.event_path.read_bytes());event['pull_request']['base']['repo']['private']=True
        self.event_path.write_text(json.dumps(event));self.rejected()

    def test_pr_api_job_and_artifact_cannot_claim_unproven_merge_or_foreign_head(self):
        self.pr_context();self.job['head_sha']='a'*40;self.refresh();self.rejected()
        self.job['head_sha']='b'*40;self.artifact['workflow_run']['head_sha']='a'*40;self.refresh();self.rejected()

    def test_pr_event_duplicate_bool_oversize_and_symlink_are_rejected(self):
        event=self.pr_context();original=self.event_path.read_bytes()
        controls=[b'{"number":19,"number":19}',b' '*(2*1024*1024+1)]
        event['pull_request']['number']=True;controls.append(json.dumps(event).encode())
        for raw in controls:
            with self.subTest(raw=raw[:20]):self.event_path.write_bytes(raw);self.rejected()
        self.event_path.write_bytes(original);link=self.root/'event-link.json';link.symlink_to(self.event_path)
        self.env['GITHUB_EVENT_PATH']=str(link);self.rejected()

    def test_push_cannot_use_pr_mapping_to_accept_a_different_api_head(self):
        self.pr_context();self.run.update(event='push');self.refresh();self.rejected()

    def test_store_source_cannot_use_pr_merge_mapping(self):
        store,source,env=self.store_inputs();self.pr_context()
        with self.assertRaises(ValueError):
            self.module().download_store(store,source,'x64',self.output,backend=self.backend,env=env)
        self.assertFalse(self.output.exists());self.assertFalse(self.output.with_name('mcp-qa-origin').exists())

    def test_server_digest_and_downloaded_size_must_match_before_extract(self):
        for changes in ({'digest':'sha256:'+'0'*64},{'size_in_bytes':len(self.archive)+1},
                        {'digest':None},{'size_in_bytes':16*1024*1024+1}):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.artifact); self.artifact.update(changes); self.refresh()
                self.rejected(); self.artifact = original

    def test_source_and_artifact_commit_run_attempt_workflow_and_repo_are_exact(self):
        for changes in ({'head_sha':'b'*40},{'run_attempt':2},{'path':'.github/workflows/other.yml'},
                        {'repository':{'full_name':'else/OpenGeul','private':False}},
                        {'repository':{'full_name':'ATLKR/OpenGeul','private':True}},
                        {'status':'completed','conclusion':'failure'}):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.run); self.run.update(changes); self.refresh()
                self.rejected(); self.run = original
        self.artifact['workflow_run']['head_sha'] = 'b'*40; self.refresh(); self.rejected()

    def test_failed_foreign_duplicate_or_prior_attempt_producer_is_rejected(self):
        for changes in ({'conclusion':'failure'},{'run_attempt':2},{'head_sha':'b'*40},
                        {'name':'native-e2e (windows-2022)'},{'status':'in_progress'}):
            with self.subTest(changes=changes):
                original = copy.deepcopy(self.job); self.job.update(changes); self.refresh()
                self.rejected(); self.job = original
        self.refresh(); self.responses['actions/runs/123/attempts/1/jobs?per_page=100']={'total_count':2,'jobs':[self.job,self.job]}
        self.rejected()

    def test_old_artifact_duplicate_name_or_changed_fixed_id_is_rejected(self):
        self.artifact['created_at']='2026-10-11T00:02:00Z'; self.refresh(); self.rejected()
        self.artifact['created_at']='2026-10-12T00:02:00Z'; self.refresh()
        self.responses['actions/runs/123/artifacts?per_page=100']={'total_count':2,'artifacts':[self.artifact,self.artifact]};self.rejected()
        self.refresh(); self.responses['actions/artifacts/67']={**self.artifact,'digest':'sha256:'+'0'*64};self.rejected()

    def test_archive_rejects_extra_case_alias_traversal_backslash_and_symlink(self):
        link=zipfile.ZipInfo('unknown');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        controls=[self.make_zip(extra=('private.txt',b'not a QA input')),
                  self.make_zip(extra=('mcp_fixtures.json',b'alias')),
                  self.make_zip(transform=lambda n:'../'+n if n=='MCP_FIXTURES.json' else n),
                  self.make_zip(transform=lambda n:n.replace('/','\\')),
                  self.make_zip(extra=(link,b'outside'))]
        for archive in controls:
            with self.subTest(zipSha=hashlib.sha256(archive).hexdigest()):
                self.archive=archive;self.artifact.update(size_in_bytes=len(archive),digest='sha256:'+hashlib.sha256(archive).hexdigest());self.refresh();self.rejected()

    def test_existing_origin_output_and_input_overlap_preserved_before_network(self):
        for output in (self.package/'qa',self.package.parent,self.output):
            if output==self.output:output.mkdir()
            with self.subTest(output=output.name),self.assertRaises(ValueError):
                self.module().download_source(self.package,output,backend=self.backend,env=self.env)
            self.assertEqual(self.backend.calls,[])
        self.output.rmdir();origin=self.output.with_name('mcp-qa-origin');origin.mkdir();(origin/'keep').write_bytes(b'prior')
        with self.assertRaises(ValueError): self.download()
        self.assertFalse(self.output.exists());self.assertEqual((origin/'keep').read_bytes(),b'prior')

    def test_arm64_requires_its_actual_producer_artifact_and_manifest(self):
        self.job['name']='native-e2e (windows-11-arm)';self.artifact['name']='opengeul-mcp-fixtures-arm64-123';self.refresh()
        self.rejected()
        self.qa.output.rename(self.qa.output.with_name('old'))
        mcp_fixtures.stage(self.qa.basic,self.qa.password,self.qa.wasm_file,self.qa.output,self.binding,architecture='arm64')
        self.archive=self.make_zip();self.artifact.update(size_in_bytes=len(self.archive),digest='sha256:'+hashlib.sha256(self.archive).hexdigest());self.refresh()
        arm=self.package.with_name('arm64')
        self.module().download_source(arm,self.output,backend=self.backend,env=self.env)
        self.assertEqual(mcp_fixtures.verify(self.output,self.binding,self.qa.wasm,architecture='arm64')['architecture'],'arm64')

    def test_package_tampering_is_rejected_before_github(self):
        (self.package/'AppxManifest.xml').write_bytes(b'changed')
        self.rejected();self.assertEqual(self.backend.calls,[])

    def test_foreign_wasm_fixture_is_rejected_despite_valid_server_zip_digest(self):
        path=self.qa.output/'MCP_FIXTURES.json';proof=json.loads(path.read_bytes());proof['sourceCommit']='b'*40
        path.write_text(json.dumps(proof)+'\n');self.archive=self.make_zip()
        self.artifact.update(size_in_bytes=len(self.archive),digest='sha256:'+hashlib.sha256(self.archive).hexdigest());self.refresh();self.rejected()

    def test_opaque_extra_manifest_fields_and_expansion_are_rejected(self):
        path=self.qa.output/'MCP_FIXTURES.json';original=path.read_bytes()
        proof=json.loads(original);proof['unknown']='unreviewed';path.write_text(json.dumps(proof)+'\n')
        self.archive=self.make_zip();self.artifact.update(size_in_bytes=len(self.archive),digest='sha256:'+hashlib.sha256(self.archive).hexdigest());self.refresh();self.rejected()
        path.write_bytes(original);large=self.qa.output/'password-fixtures/protected.hwp'
        large.write_bytes(b'x'*(mcp_fixtures.MAX_FILE+1));self.archive=self.make_zip()
        self.artifact.update(size_in_bytes=len(self.archive),digest='sha256:'+hashlib.sha256(self.archive).hexdigest());self.refresh();self.rejected()

    def store_inputs(self):
        source=self.root/'source-pair';base=self.package.parent
        import native_split_fixture
        native_split_fixture.bind_source(base/'arm64',base/'wack-arm64')
        pair=release_pair.assemble(base/'x64',base/'arm64',base/'wack-x64',base/'wack-arm64',source,env=self.env)
        store=self.root/'store-output';store.mkdir();entries={}
        for arch in ('x64','arm64'):
            source_record=pair['architectures'][arch];prov=source_record['provenance']
            source_msix=source/source_record['assets'][prov['package']]
            name=f'OpenGeul_{pair["version"]}.0_{arch}_store-unsigned.msix';manifest_name='AppxManifest-'+arch+'.xml'
            xml=manifest(store_package.STORE_IDENTITY,pair['version'],arch).encode()
            with zipfile.ZipFile(source_msix) as original,zipfile.ZipFile(store/name,'w') as target:
                for member in original.infolist():target.writestr(member,xml if member.filename=='AppxManifest.xml' else original.read(member))
            (store/manifest_name).write_bytes(xml)
            hashes=store_package.verify_repackage(source_msix,store/name,pair['version'],arch)
            entries[arch]={'sourceMsix':prov['package'],'sourceMsixSha256':prov['sha256'],
                'package':name,'sha256':hashlib.sha256((store/name).read_bytes()).hexdigest(),
                'manifest':manifest_name,'runtimeSha256':hashes}
        details={'formatVersion':2,'storeAppId':store_package.STORE_APP_ID,'identity':store_package.STORE_IDENTITY,
            'version':pair['version'],'sourceRelease':f'https://github.com/ATLKR/OpenGeul/releases/tag/v{pair["version"]}-dev.29.1',
            'sourceReleaseId':99,'sourceCommit':pair['commit'],'sourceRunId':pair['runId'],'sourceRunAttempt':pair['runAttempt'],
            'sourceAssetFingerprintSha256':release_pair.source_fingerprint(source),'repackageCommit':'b'*40,
            'repackageRunId':'999','architectures':entries,'unsigned':True,'storeCertified':False}
        (store/'source-provenance.json').write_bytes((source/'provenance.json').read_bytes())
        (store/'store-provenance.json').write_text(json.dumps(details)+'\n')
        test_store_package.StorePackageTests('runTest').checksum_directory(store)
        env={**self.env,'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'999'}
        self.run.update(status='completed',conclusion='success');self.refresh()
        jobs=[{**self.job,'id':index+100,'name':name} for index,name in enumerate(sorted(store_package.REQUIRED_JOBS))]
        self.responses['actions/runs/123/attempts/1/jobs?per_page=100']={'total_count':len(jobs),'jobs':jobs}
        self.responses[f'commits/v{pair["version"]}-dev.29.1']={'sha':'a'*40}
        return store,source,env

    def test_store_uses_full_pair_real_repackage_and_all_source_gates(self):
        store,source,env=self.store_inputs()
        receipt=self.module().download_store(store,source,'x64',self.output,backend=self.backend,env=env)
        self.assertEqual(receipt['sourceCommit'],'a'*40)
        self.assertTrue(mcp_fixtures.verify(self.output,self.binding,self.qa.wasm)['publicQaOnly'])

    def test_store_rejects_incomplete_source_missing_gate_tag_and_wrong_source_bytes(self):
        store,source,env=self.store_inputs();module=self.module()
        original=copy.deepcopy(self.responses)
        for change in ('in-progress','missing-gate','wrong-tag','old-attempt'):
            self.responses=copy.deepcopy(original)
            if change=='in-progress':self.responses['actions/runs/123'].update(status='in_progress',conclusion=None)
            elif change=='missing-gate':self.responses['actions/runs/123/attempts/1/jobs?per_page=100']['jobs'][0]['conclusion']='failure'
            elif change=='wrong-tag':
                key=next(name for name in self.responses if name.startswith('commits/'));self.responses[key]['sha']='b'*40
            else:self.responses['actions/runs/123'].update(run_attempt=2)
            with self.subTest(change=change),self.assertRaises(ValueError):
                module.download_store(store,source,'x64',self.output,backend=self.backend,env=env)
            self.assertFalse(self.output.exists());self.assertFalse(self.output.with_name('mcp-qa-origin').exists())
        self.responses=copy.deepcopy(original);(source/'provenance.json').write_bytes(b'changed')
        self.backend.calls=[]
        with self.assertRaises(ValueError):module.download_store(store,source,'x64',self.output,backend=self.backend,env=env)
        self.assertEqual(self.backend.calls,[])

    def test_receipt_omits_urls_tokens_document_content_and_unknown_server_metadata(self):
        secret='sensitive-test-value';self.run.update(token=secret,url='https://example.invalid/'+secret)
        self.artifact.update(archive_download_url='https://example.invalid/'+secret,token=secret)
        self.refresh();self.download()
        raw=(self.output.with_name('mcp-qa-origin')/'receipt.json').read_bytes()
        self.assertNotIn(secret.encode(),raw);self.assertNotIn(self.qa.manifest['password'].encode(),raw)
        self.assertNotIn(self.qa.manifest['expectedText'].encode(),raw);self.assertLess(len(raw),64*1024)

    def test_transport_get_is_bounded_and_stderr_is_never_returned_or_logged(self):
        module=self.module();backend=module.GitHub()
        class Child:
            returncode=0
            def __init__(self,*args,**kwargs):self.stdout=io.BytesIO(b'x'*33);self.stderr=io.BytesIO(b'secret-response')
            def wait(self,timeout=None):return 0
            def kill(self):self.returncode=-9
        with patch.object(module.subprocess,'Popen',Child),self.assertRaises(ValueError) as caught:
            backend._bytes('actions/runs/123',32)
        self.assertNotIn('secret-response',str(caught.exception))
        with self.assertRaises(ValueError):backend._bytes('releases/123',32)

    def test_destination_created_at_publish_is_never_replaced(self):
        module=self.module();original=module._move_new;origin=self.output.with_name('mcp-qa-origin');created=[]
        def race(path,destination):
            if Path(destination)==origin:
                origin.mkdir();created.append(origin.stat().st_ino)
            return original(path,destination)
        with patch.object(module,'_move_new',race),self.assertRaises(FileExistsError):
            module.download_source(self.package,self.output,backend=self.backend,env=self.env)
        self.assertEqual(origin.stat().st_ino,created[0]);self.assertEqual(list(origin.iterdir()),[])
        self.assertFalse(self.output.exists())

    def test_payload_publication_race_preserves_existing_output_and_verified_origin(self):
        module=self.module();original=module._move_new;created=[]
        def race(path,destination):
            if Path(destination)==self.output:
                self.output.mkdir();created.append(self.output.stat().st_ino)
            return original(path,destination)
        with patch.object(module,'_move_new',race),self.assertRaises(FileExistsError):
            module.download_source(self.package,self.output,backend=self.backend,env=self.env)
        self.assertEqual(self.output.stat().st_ino,created[0]);self.assertEqual(list(self.output.iterdir()),[])
        origin=self.output.with_name('mcp-qa-origin')
        self.assertEqual({p.name for p in origin.iterdir()},{'original.zip','receipt.json'})
        self.assertEqual((origin/'original.zip').read_bytes(),self.archive)


if __name__=='__main__':unittest.main()
