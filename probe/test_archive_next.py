"""오프라인 API 기록·원본 ZIP·실제 Git 객체로 전송 경계를 검사한다."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import archive_next as subject


def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class Evidence:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Offline evidence')
        self.git('config', 'user.email', 'offline@example.invalid')
        template = json.loads((Path(__file__).parent / 'archive-next-contract.json').read_text())
        for path in template['protectedFiles']:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'protected original\n')
        (self.root / 'website').mkdir()
        (self.root / 'website/index.html').write_bytes(b'original qualified link\n')
        self.source = self.commit('source')
        (self.root / 'website/index.html').write_bytes(b'approved subsequent link\n')
        self.store = self.commit('website-only')
        diff = [{'path': 'website/index.html', 'beforeSha256': sha(b'original qualified link\n'),
                 'afterSha256': sha(b'approved subsequent link\n')}]
        self.c = dict(repository='ATLKR/OpenGeul', sourceCommit=self.source,
            sourceRunId=101, sourceRunNumber=999, sourceRunAttempt=1, sourceReleaseId=201,
            sourceTag='v9.8.7-dev.999.1', storeExecutionCommit=self.store,
            storeRunId=102, storeRunAttempt=1, storeArtifactId=301,
            archiveReleaseId=202, archiveTag='store-package-9.8.7-dev.999.1',
            approvedWebsiteDiff=diff, approvedWebsiteDiffSha256=sha(canonical(diff)),
            protectedFiles={p: sha(b'protected original\n') for p in template['protectedFiles']})
        runtime = {'OpenGeul.exe': sha(b'original GUI'), 'Tools/rhwp.exe': sha(b'original CLI')}
        self.c.update(runtimeSnapshotSha256=sha(canonical(runtime)), guiSha256=runtime['OpenGeul.exe'])
        self.files = {'AppxManifest.xml': b'original manifest', 'OpenGeul-editor.png': b'original image',
            'OpenGeul_9.8.7.0_x64_store-unsigned.msix': b'original MSIX', 'SHA256SUMS.txt': b'original checksums',
            'source-provenance.json': canonical({'repository': 'ATLKR/OpenGeul', 'commit': self.source, 'runId': '101'}),
            'store-provenance.json': canonical({'sourceCommit': self.source, 'sourceRunId': '101',
                'sourceReleaseId': 201, 'repackageCommit': self.store, 'repackageRunId': '102',
                'runtimeSha256': runtime, 'unsigned': True, 'storeCertified': False}),
            'screenshot-provenance.json': canonical({'sourceCommit': self.source, 'runId': '102',
                'executableSha256': runtime['OpenGeul.exe']})}
        self.c['sourceProvenanceSha256'] = sha(self.files['source-provenance.json'])
        self.c['assets'] = {n: {'size': len(d), 'sha256': sha(d)} for n, d in self.files.items()}
        self.raw = self.zip(self.files)
        self.c.update(storeArtifactBytes=len(self.raw), storeArtifactSha256=sha(self.raw))
        self.source_assets = [{'id': 500+i, 'name': f'original-source-{i}', 'size': 5,
            'state': 'uploaded', 'digest': 'sha256:'+sha(bytes([i]))} for i in range(6)]
        self.c['sourceAssetSnapshotSha256'] = sha(canonical(sorted(self.source_assets, key=lambda r: r['name'])))
        self.plan = canonical({'repository': 'ATLKR/OpenGeul', 'archiveTag': self.c['archiveTag'],
            'targetCommit': self.source, 'sourceRunId': 101, 'storeRunId': 102, 'storeArtifactId': 301,
            'sourceReleaseId': 201, 'sourceAssetSnapshotSha256': self.c['sourceAssetSnapshotSha256'],
            'assets': self.c['assets'], 'decision': 'reuse-draft'})
        self.c['preparedPlanSha256'] = sha(self.plan)
        self.calls = []
        self.present = []
        self.edit = lambda method, path, value: value

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root).decode().strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    @staticmethod
    def zip(files):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            for name, raw in files.items(): z.writestr(name, raw)
        return data.getvalue()

    def row(self, name):
        return {'id': 1000+len(self.present), 'name': name, 'state': 'uploaded',
                'size': self.c['assets'][name]['size'], 'digest': 'sha256:'+self.c['assets'][name]['sha256']}

    def api(self, method, path, data=None):
        self.calls.append((method, path))
        prefix = 'repos/ATLKR/OpenGeul/'
        if method == 'POST':
            name = path.split('?name=')[1]
            assert name in self.files and data == self.files[name]
            value = self.row(name)
            self.present.append(value)
        elif path.startswith(prefix+'actions/runs/'):
            run_id = int(path[len(prefix+'actions/runs/'):].split('/')[0])
            source = run_id == 101
            head = self.source if source else self.store
            if '/jobs?' in path:
                names = subject.SOURCE_JOBS if source else {'package', 'verify-api'}
                jobs = [{'id': 2000+i, 'name': n, 'run_id': run_id, 'run_attempt': 1,
                         'head_sha': head, 'status': 'completed', 'conclusion': 'success'} for i, n in enumerate(sorted(names))]
                value = {'total_count': len(jobs), 'jobs': jobs}
            else:
                value = {'id': run_id, 'run_number': 999 if source else 5, 'run_attempt': 1,
                    'head_sha': head, 'head_branch': 'main', 'path': '.github/workflows/'+('msix.yml' if source else 'store-package.yml'),
                    'event': 'push' if source else 'workflow_dispatch', 'status': 'completed',
                    'conclusion': 'success', 'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}}
        elif path == prefix+'actions/artifacts/301':
            value = {'id': 301, 'expired': False, 'name': 'opengeul-store-102',
                'size_in_bytes': len(self.raw), 'digest': 'sha256:'+sha(self.raw),
                'workflow_run': {'id': 102, 'head_sha': self.store, 'head_branch': 'main'}}
        elif path.startswith(prefix+'releases/201/assets?'): value = copy.deepcopy(self.source_assets)
        elif path.startswith(prefix+'releases/202/assets?'): value = copy.deepcopy(self.present)
        elif path == prefix+'releases/201':
            value = {'id': 201, 'tag_name': self.c['sourceTag'], 'draft': False, 'prerelease': True}
        elif path == prefix+'releases/202':
            value = {'id': 202, 'tag_name': self.c['archiveTag'], 'target_commitish': self.source, 'draft': True, 'prerelease': True}
        elif path == prefix+'commits/'+self.c['sourceTag']: value = {'sha': self.source}
        elif path == prefix+'git/ref/tags/'+self.c['archiveTag']: value = None
        else: raise AssertionError('unexpected endpoint '+path)
        return self.edit(method, path, value)

    def download(self, artifact):
        self.calls.append(('DOWNLOAD', str(artifact['id'])))
        return self.raw

    def transfer(self, contract=None, plan=None):
        return subject.transfer(self.api, self.download, self.root, contract or self.c, self.plan if plan is None else plan)


class ArchiveBoundaryControls(unittest.TestCase):
    def setUp(self): self.e = Evidence(); self.addCleanup(self.e.temp.cleanup)

    def assert_no_post(self): self.assertFalse(any(m == 'POST' for m, _ in self.e.calls))

    def test_actual_unset_contract_refuses_before_any_transport(self):
        pending = json.loads((Path(__file__).parent/'archive-next-unset-fixture.json').read_text())
        with self.assertRaises(ValueError): self.e.transfer(pending)
        self.assertEqual(self.e.calls, [])

    def test_cli_root_authorization_is_required_before_contract_file_read(self):
        with patch.object(subject, 'CONTRACT', self.e.root/'does-not-exist.json'):
            with self.assertRaises(ValueError): subject.main()

    def test_nested_unset_hash_or_bool_id_refuses_before_any_transport(self):
        for change in [lambda c: c['assets']['AppxManifest.xml'].update(sha256='UNSET'),
                       lambda c: c.update(sourceReleaseId=True), lambda c: c.update(archiveReleaseId=201)]:
            with self.subTest(change=change):
                c=copy.deepcopy(self.e.c);change(c)
                with self.assertRaises(ValueError): self.e.transfer(c)
                self.assertEqual(self.e.calls, [])

    def test_distinct_heads_approved_git_diff_original_seven_and_draft_stop(self):
        result = self.e.transfer()
        self.assertEqual(result.get('published'), False)
        self.assertEqual(result.get('sourceQualified'), False)
        self.assertEqual(len(self.e.present), 7)
        self.assertEqual(len([m for m,_ in self.e.calls if m == 'POST']), 7)
        self.assertEqual({m for m,_ in self.e.calls}, {'GET','DOWNLOAD','POST'})

    def test_existing_matching_assets_are_kept_without_clobber(self):
        name='AppxManifest.xml';self.e.present.append(self.e.row(name))
        self.e.transfer()
        self.assertEqual(len([m for m,_ in self.e.calls if m == 'POST']), 6)
        self.assertFalse(any(m=='POST' and p.endswith('='+name) for m,p in self.e.calls))

    def test_source_and_store_jobs_bind_their_own_distinct_heads(self):
        for run_id, wrong in [(101,self.e.store),(102,self.e.source)]:
            with self.subTest(run=run_id):
                def change(m,p,v):
                    if f'/runs/{run_id}/' in p and '/jobs?' in p: v['jobs'][0]['head_sha']=wrong
                    return v
                self.e.edit=change
                with self.assertRaises(ValueError): self.e.transfer()
                self.assert_no_post()

    def test_missing_failed_duplicate_source_jobs_and_overall_failure_reject(self):
        for kind in ['missing','failed','duplicate','overall']:
            with self.subTest(kind=kind):
                def change(m,p,v):
                    if '/runs/101/' in p and '/jobs?' in p:
                        if kind=='missing': v['jobs'].pop();v['total_count']-=1
                        if kind=='failed': v['jobs'][0]['conclusion']='failure'
                        if kind=='duplicate': v['jobs'].append(copy.deepcopy(v['jobs'][0]));v['total_count']+=1
                    if p.endswith('/runs/101') and kind=='overall': v['conclusion']='failure'
                    return v
                self.e.edit=change
                with self.assertRaises(ValueError): self.e.transfer()
                self.assert_no_post()

    def test_store_artifact_using_source_head_or_other_run_rejects(self):
        for key,value in [('head_sha',self.e.source),('id',101)]:
            with self.subTest(key=key):
                def change(m,p,v):
                    if p.endswith('/artifacts/301'): v['workflow_run'][key]=value
                    return v
                self.e.edit=change
                with self.assertRaises(ValueError): self.e.transfer()
                self.assert_no_post()

    def test_nonancestor_or_nonwebsite_or_renamed_path_rejects_before_api(self):
        for kind in ['nonancestor','docs','rename']:
            with self.subTest(kind=kind):
                c=copy.deepcopy(self.e.c)
                if kind=='nonancestor': c['sourceCommit'],c['storeExecutionCommit']=self.e.store,self.e.source
                if kind=='docs':
                    (self.e.root/'docs').mkdir(exist_ok=True);(self.e.root/'docs/new.md').write_bytes(b'doc')
                    c['storeExecutionCommit']=self.e.commit('unapproved docs')
                if kind=='rename':
                    (self.e.root/'website/index.html').rename(self.e.root/'website/renamed.html')
                    c['storeExecutionCommit']=self.e.commit('rename')
                with self.assertRaises(ValueError): subject.validate_git(self.e.root,c)

    def test_incomplete_approved_diff_or_wrong_before_after_hash_rejects(self):
        for diff in [[],[dict(self.e.c['approvedWebsiteDiff'][0], afterSha256='0'*64)]]:
            c=copy.deepcopy(self.e.c);c['approvedWebsiteDiff']=diff;c['approvedWebsiteDiffSha256']=sha(canonical(diff))
            with self.assertRaises(ValueError): subject.validate_git(self.e.root,c)

    def test_source_validator_or_capture_workflow_hash_drift_rejects(self):
        for path in ['scripts/store_package.py','.github/workflows/store-package.yml','e2e/store_screenshot.py']:
            c=copy.deepcopy(self.e.c);c['protectedFiles'][path]='0'*64
            with self.assertRaises(ValueError): subject.validate_git(self.e.root,c)

    def test_source_repackage_swaps_and_screenshot_runtime_mismatch_reject(self):
        for name,field,value in [('source-provenance.json','commit',self.e.store),
                ('store-provenance.json','repackageCommit',self.e.source),
                ('screenshot-provenance.json','executableSha256','0'*64)]:
            files=copy.deepcopy(self.e.files);record=json.loads(files[name]);record[field]=value;files[name]=canonical(record)
            with self.assertRaises(ValueError): subject.provenance(files,self.e.c)

    def test_original_zip_duplicate_extra_path_hash_and_runtime_drift_reject(self):
        for kind in ['extra','hash','zipdigest','runtime','duplicate']:
            files=copy.deepcopy(self.e.files);c=copy.deepcopy(self.e.c)
            if kind=='extra': files['../escape']=b'bad'
            if kind=='hash': files['AppxManifest.xml']+=b'changed'
            if kind=='runtime':
                d=json.loads(files['store-provenance.json']);d['runtimeSha256']['OpenGeul.exe']='0'*64;files['store-provenance.json']=canonical(d)
                c['assets']['store-provenance.json']={'size':len(files['store-provenance.json']),'sha256':sha(files['store-provenance.json'])}
            raw=self.e.zip(files)
            if kind=='zipdigest': raw+=b'changed original ZIP'
            if kind=='duplicate':
                stream=io.BytesIO(raw)
                with zipfile.ZipFile(stream,'a') as archive:
                    with self.assertWarns(UserWarning): archive.writestr('AppxManifest.xml',files['AppxManifest.xml'])
                raw=stream.getvalue()
            if kind!='zipdigest': c.update(storeArtifactBytes=len(raw),storeArtifactSha256=sha(raw))
            with self.assertRaises(ValueError): subject.original_payload(raw,c)

    def test_plan_hash_or_original_asset_plan_mismatch_refuses_before_api(self):
        with self.assertRaises(ValueError): self.e.transfer(plan=self.e.plan+b' ')
        self.assertEqual(self.e.calls,[])
        c=copy.deepcopy(self.e.c);plan=json.loads(self.e.plan);plan['assets']['AppxManifest.xml']['sha256']='0'*64
        raw=canonical(plan);c['preparedPlanSha256']=sha(raw)
        with self.assertRaises(ValueError): self.e.transfer(c,raw)
        self.assertEqual(self.e.calls,[])

    def test_published_archive_wrong_target_or_collision_never_uploads(self):
        for kind in ['published','target','collision']:
            def change(m,p,v):
                if p.endswith('/releases/202'):
                    if kind=='published': v['draft']=False
                    if kind=='target': v['target_commitish']=self.e.store
                if '/releases/202/assets?' in p and kind=='collision': v=[dict(self.e.row('AppxManifest.xml'),digest='sha256:'+'0'*64)]
                return v
            self.e.edit=change
            with self.assertRaises(ValueError): self.e.transfer()
            self.assert_no_post()

    def test_source_asset_mutation_blocks_remaining_uploads(self):
        def change(m,p,v):
            if '/releases/201/assets?' in p and self.e.present: v[0]['digest']='sha256:'+'0'*64
            return v
        self.e.edit=change
        with self.assertRaises(ValueError): self.e.transfer()
        self.assertEqual(len(self.e.present),1)

    def test_ambiguous_upload_and_server_digest_failure_do_not_retry(self):
        for kind in ['exception','serverdigest']:
            with self.subTest(kind=kind):
                self.e.present=[];self.e.calls=[]
                def change(m,p,v):
                    if m=='POST':
                        if kind=='exception': raise RuntimeError('ambiguous transport')
                        v['digest']='sha256:'+'0'*64
                    return v
                self.e.edit=change
                with self.assertRaises((ValueError,RuntimeError)): self.e.transfer()
                self.assertEqual(len([m for m,_ in self.e.calls if m=='POST']),1)


if __name__ == '__main__': unittest.main()
