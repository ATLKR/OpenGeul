import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import store_submit as submitter
except ImportError:
    submitter = None
from buildkit import DEV_IDENTITY, manifest
from store_package import STORE_APP_ID, STORE_IDENTITY, REQUIRED_JOBS
import store_listing


def historical_verify(tag, directory):
    """이전 단일 x64 프로토콜의 상태기계 검사. 실제 CLI에는 이 경로가 없다."""
    version = submitter._version(tag)
    if submitter.os.getenv('GITHUB_REF') != 'refs/heads/main':
        raise submitter.SubmissionBlocked('Historical workflow ref changed')
    source = directory.parent / '.work/store-source'
    submitter.verify_checksums(directory); submitter.verify_checksums(source)
    details = json.loads((directory / 'store-provenance.json').read_bytes())
    original = json.loads((source / 'provenance.json').read_bytes())
    if (original != json.loads((directory / 'source-provenance.json').read_bytes())
            or details['sourceMsixSha256'] != original['sha256']):
        raise submitter.SubmissionBlocked('Historical source changed')
    run = submitter._gh('GET', 'actions/runs/' + original['runId'])
    if run.get('event') != 'push' or run.get('head_branch') != tag:
        raise submitter.SubmissionBlocked('Historical stable source required')
    jobs = [job for page in submitter._gh('GET', f'actions/runs/{original["runId"]}/jobs?per_page=100', pages=True) for job in page['jobs']]
    submitter.authorize_release(tag, original, run, submitter._gh('GET', 'commits/' + tag)['sha'], jobs)
    if (submitter.verify_msix(source / original['package'])['sha256'] != original['sha256']
            or submitter.verify_msix(directory / details['package'])['sha256'] != details['sha256']
            or submitter.verify_repackage(source / original['package'], directory / details['package'], tag[1:]) != details['runtimeSha256']):
        raise submitter.SubmissionBlocked('Historical runtime changed')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr(details['package'], (directory / details['package']).read_bytes())
    return details, version, buffer.getvalue()


class StoreSubmitTests(unittest.TestCase):
    historical = True
    def setUp(self):
        self.assertIsNotNone(submitter, 'The Store submission command is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'store-output'
        self.source = self.root / '.work/store-source'
        self.source.mkdir(parents=True)
        self.directory.mkdir()
        self.sha = 'a' * 40
        self.tag = 'v1.1.3'
        pe = bytearray(256)
        pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
        pe[128:132] = b'PE\0\0'; pe[132:134] = (0x8664).to_bytes(2, 'little')
        runtime = {'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                   'WebView2Loader.dll': bytes(pe) + b'loader', 'Notices/OpenGeul-LICENSE.txt': b'MIT'}
        original = self.source / 'original.msix'
        packaged = self.directory / 'OpenGeul_1.1.3.0_x64_store-unsigned.msix'
        for path, identity in [(original, DEV_IDENTITY), (packaged, STORE_IDENTITY)]:
            with zipfile.ZipFile(path, 'w') as archive:
                for name, value in runtime.items(): archive.writestr(name, value)
                archive.writestr('AppxManifest.xml', manifest(identity, '1.1.3'))
                archive.writestr('AppxBlockMap.xml', b'<BlockMap/>')
                archive.writestr('[Content_Types].xml', b'<Types/>')
        with zipfile.ZipFile(self.source / 'original-portable.zip', 'w') as archive:
            for name, value in runtime.items(): archive.writestr(name, value)
            archive.writestr('AppxManifest.xml', manifest(DEV_IDENTITY, '1.1.3'))
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        self.provenance = {'repository': 'ATLKR/OpenGeul', 'version': '1.1.3',
                           'commit': self.sha, 'runId': '123', 'package': original.name,
                           'sha256': original_hash}
        original_json = json.dumps(self.provenance).encode()
        (self.source / 'provenance.json').write_bytes(original_json)
        (self.directory / 'source-provenance.json').write_bytes(original_json)
        (self.directory / 'AppxManifest.xml').write_text(manifest(STORE_IDENTITY, '1.1.3'), encoding='utf-8', newline='\n')
        self.details = {'storeAppId': STORE_APP_ID, 'identity': STORE_IDENTITY,
                        'version': '1.1.3', 'sourceReleaseId': 5,
                        'sourceRelease': 'https://github.com/ATLKR/OpenGeul/releases/tag/v1.1.3',
                        'sourceCommit': self.sha, 'sourceRunId': '123',
                        'sourceMsixSha256': original_hash, 'package': packaged.name,
                        'sha256': hashlib.sha256(packaged.read_bytes()).hexdigest(),
                        'runtimeSha256': {name: hashlib.sha256(value).hexdigest() for name, value in runtime.items()},
                        'unsigned': True, 'storeCertified': False}
        self.write_details()
        self.checksums(self.source)
        self.calls = []
        self.issues = []
        self.bot = {'login': 'github-actions[bot]', 'type': 'Bot', 'id': 41898282}
        self.outsider = {'login': 'outsider', 'type': 'User', 'id': 12345}
        self.untrusted_issue_response = None
        self.tags = [[{'name': self.tag}]]
        self.app = {'id': STORE_APP_ID, 'packageIdentityName': STORE_IDENTITY['name'],
                    'publisherName': STORE_IDENTITY['publisher'],
                    'lastPublishedApplicationSubmission': {'id': '10'},
                    'pendingApplicationSubmission': {'id': '20'}}
        self.baseline = {'id': '10', 'status': 'Published',
                         'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'US': 'Base'}},
                         'listings': {'ko-kr': {'baseListing': {'title': 'OpenGeul', 'images': []}}},
                         'targetPublishMode': 'Manual', 'notesForCertification': 'Keep human notes',
                         'applicationPackages': [{'id': '11', 'fileName': 'old.msix', 'fileStatus': 'Uploaded',
                                                  'version': '1.1.2.0', 'architecture': 'X64',
                                                  'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None'}]}
        self.pending = {**copy.deepcopy(self.baseline), 'id': '20', 'status': 'PendingCommit'}
        self.delete_mode = 'success'
        self.commit_mode = 'success'
        self.upload_mode = 'success'
        self.create_mode = 'success'
        self.put_packages_mode = 'success'
        self.get_packages_mode = 'success'
        self.before_delete_version = None
        self.new = None
        self.run = {'id': 123, 'head_sha': self.sha, 'head_branch': self.tag,
                    'run_number': 40, 'run_attempt': 1, 'repository': {'full_name': 'ATLKR/OpenGeul'},
                    'event': 'push', 'path': '.github/workflows/msix.yml',
                    'status': 'completed', 'conclusion': 'success'}
        self.patches = [patch.object(submitter, '_gh', side_effect=self.github),
                        patch.object(submitter, '_request', side_effect=self.store),
                        patch.object(submitter, '_upload', side_effect=self.upload),
                        patch.object(submitter, 'authenticate', return_value=(object(), 'TOP_SECRET')),
                        patch.object(submitter.time, 'sleep'),
                        patch.dict(submitter.os.environ, {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul',
                                                         'GITHUB_REF': 'refs/heads/main',
                                                         'GITHUB_RUN_ID': '456'}, clear=False)]
        for active in self.patches:
            active.start(); self.addCleanup(active.stop)
        if self.historical:
            adapter = patch.object(submitter, '_verify', side_effect=historical_verify)
            adapter.start(); self.addCleanup(adapter.stop)
            self.historical_adapter = adapter

    def checksums(self, directory):
        (directory / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in sorted(directory.iterdir()) if path.name != 'SHA256SUMS.txt'))

    def write_details(self):
        (self.directory / 'store-provenance.json').write_text(json.dumps(self.details))
        self.checksums(self.directory)

    def github(self, method, path, data=None, *, pages=False):
        self.calls.append(('github', method, path))
        if path.startswith('issues'):
            if path.startswith('issues?'): return [copy.deepcopy(self.issues)]
            if method == 'POST':
                item = {'number': max((issue['number'] for issue in self.issues), default=0) + 1,
                        'title': data['title'], 'body': data['body'], 'user': copy.deepcopy(self.bot)}
                self.issues.append(item)
            else:
                item = next(issue for issue in self.issues if issue['number'] == int(path.split('/')[1]))
                if method == 'PATCH': item.update(data)
            result = copy.deepcopy(item)
            if (method == self.untrusted_issue_response
                    or self.untrusted_issue_response == 'GET_AFTER_PATCH' and method == 'GET'
                    and any(call[0:2] == ('github', 'PATCH') for call in self.calls)):
                result['user'] = copy.deepcopy(self.outsider)
            return result
        if path.startswith('tags?'): return self.tags
        if path == 'releases/tags/v1.1.3': return {'id': 5, 'draft': False, 'tag_name': self.tag}
        if path == 'commits/v1.1.3': return {'sha': self.sha}
        if path == 'actions/runs/123': return self.run
        if path.startswith('actions/runs/123/jobs'): return [{'jobs': [{'name': name, 'conclusion': 'success'} for name in REQUIRED_JOBS]}]
        raise AssertionError((method, path))

    def store(self, opener, token, method, path, data=None):
        self.calls.append(('store', method, path))
        if path == '' and method == 'GET': return 200, copy.deepcopy(self.app)
        if method == 'DELETE':
            if self.delete_mode == 'refused': raise submitter.StoreError('delete', 409)
            if self.delete_mode == 'missing': raise submitter.StoreError('delete', 404)
            if self.delete_mode == 'timeout':
                self.app['pendingApplicationSubmission'] = None
                raise submitter.StoreError('delete', None)
            if self.delete_mode == 'nonempty': return 200, b'null'
            if self.delete_mode != 'stale': self.app['pendingApplicationSubmission'] = None
            return 200, b''
        if path == 'submissions/10': return 200, copy.deepcopy(self.baseline)
        if path in ('submissions/20', 'submissions/20/status'):
            if self.app['pendingApplicationSubmission'] is None: raise submitter.StoreError('get', 404)
            if self.before_delete_version and sum(call == ('store', 'GET', path) for call in self.calls) >= 2:
                self.pending['applicationPackages'][0]['version'] = self.before_delete_version
            return 200, copy.deepcopy(self.pending)
        if method == 'POST' and path == 'submissions':
            self.new = {**copy.deepcopy(self.baseline), 'id': '30', 'status': 'PendingCommit',
                        'fileUploadUrl': 'https://storetest.blob.core.windows.net/ingestion/id?sig=SAS_SECRET'}
            self.app['pendingApplicationSubmission'] = {'id': '30'}
            if self.create_mode == 'timeout': raise submitter.StoreError('create', None)
            return 201, copy.deepcopy(self.new)
        if path == 'submissions/30' and method == 'PUT':
            self.new.update(copy.deepcopy(data))
            result = copy.deepcopy(self.new)
            self.change_packages(result, self.put_packages_mode)
            return 200, result
        if path == 'submissions/30/commit':
            self.new['status'] = {'unknown': 'PendingCommit', 'failed': 'CommitFailed'}.get(self.commit_mode, 'PreProcessing')
            if self.commit_mode != 'unknown':
                for package in self.new['applicationPackages']:
                    if package['fileStatus'] == 'PendingUpload':
                        package.update(version='1.1.3.0', architecture='X64', fileStatus='Uploaded')
            if self.commit_mode in ('timeout', 'unknown'): raise submitter.StoreError('commit', None)
            return 200, {'status': 'CommitStarted'}
        if path in ('submissions/30', 'submissions/30/status'):
            result = copy.deepcopy(self.new)
            if path == 'submissions/30': self.change_packages(result, self.get_packages_mode)
            return 200, result
        raise AssertionError((method, path))

    def change_packages(self, result, mode):
        packages = result['applicationPackages']
        if mode == 'old_only': result['applicationPackages'] = copy.deepcopy(self.baseline['applicationPackages'])
        if mode == 'old_uploaded': packages[0]['fileStatus'] = 'Uploaded'
        if mode == 'wrong_target': packages[-1]['fileName'] = 'other.msix'
        if mode == 'target_uploaded': packages[-1]['fileStatus'] = 'Uploaded'
        if mode == 'missing_directx': packages[-1].pop('minimumDirectXVersion')
        if mode == 'missing_ram': packages[-1].pop('minimumSystemRam')
        if mode == 'duplicate_target': packages.append(copy.deepcopy(packages[-1]))
        if mode == 'server_fields':
            packages[-1].update(id='31', architecture='X64', version='1.1.3.0')
            packages.reverse()

    def upload(self, opener, url, body):
        self.calls.append(('store', 'UPLOAD', 'blob'))
        if self.upload_mode == 'timeout': raise submitter.StoreError('upload', None)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(archive.namelist(), ['OpenGeul_1.1.3.0_x64_store-unsigned.msix'])
        return None

    def perform(self):
        with patch('sys.stdout', new=io.StringIO()):
            return submitter.submit(self.tag, self.directory)

    def mutations(self):
        return [method for service, method, path in self.calls if service == 'store' and method != 'GET']

    def test_replacement_requires_ack_and_fresh_absence(self):
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT', 'UPLOAD', 'POST'])
        self.assertEqual(self.new['pricing'], self.baseline['pricing'])
        self.assertEqual(self.new['listings'], store_listing.apply_korean_listing(self.baseline)['listings'])
        self.assertEqual(self.new['targetPublishMode'], 'Immediate')
        self.assertIn('Keep human notes', self.new['notesForCertification'])

    def test_actual_entrypoint_rejects_original_single_x64_release(self):
        self.historical_adapter.stop()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_korean_listing_updates_all_existing_locales_and_preserves_baseline(self):
        self.baseline['listings']['en-us'] = {
            'baseListing': {'title': 'OpenGeul', 'description': 'Old English text',
                            'images': [{'id': 'existing', 'fileStatus': 'Uploaded'}]},
            'platformOverrides': {'Windows81': {'description': 'Preserved'}}}
        original = copy.deepcopy(self.baseline)
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.baseline, original)
        self.assertEqual(self.new['listings'], store_listing.apply_korean_listing(original)['listings'])
        self.assertEqual(self.new['pricing'], original['pricing'])
        self.assertEqual(self.new['targetPublishMode'], 'Immediate')

    def test_invalid_korean_listing_plan_preserves_existing_pending_before_mutation(self):
        invalid = self.root / 'invalid-listing.json'
        invalid.write_text('{"description":"English-only"}', encoding='utf-8')
        original = copy.deepcopy(self.pending)
        with patch.object(store_listing, 'CONFIG', invalid):
            with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.pending, original)

    def test_missing_korean_listing_preserves_pending_before_mutation(self):
        self.baseline['listings'] = {'en-us': {'baseListing': {'title': 'OpenGeul'}}}
        original = copy.deepcopy(self.pending)
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])
        self.assertEqual(self.pending, original)

    def test_free_replacement_preserves_unavailable_markets(self):
        self.baseline['pricing']['marketSpecificPricings'].update(
            KR='Free', CN='NotAvailable', RU='NotAvailable')
        original = copy.deepcopy(self.baseline)
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.new['pricing'], original['pricing'])
        self.assertEqual(self.baseline, original)

    def test_unknown_publication_template_never_mutates_store(self):
        for mode in ('SpecificDate', None, 'unknown'):
            with self.subTest(mode=mode):
                self.calls.clear(); self.issues.clear()
                self.baseline['targetPublishMode'] = mode
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), [])

    def test_changed_publication_mode_ack_never_uploads_or_commits(self):
        def changed_ack(*args, **kwargs):
            status, result = self.store(*args, **kwargs)
            if args[2:4] == ('PUT', 'submissions/30'):
                result['targetPublishMode'] = 'Manual'
            return status, result

        with patch.object(submitter, '_request', side_effect=changed_ack):
            with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT'])

    def test_changed_publication_mode_after_upload_never_commits(self):
        def changed_readback(*args, **kwargs):
            status, result = self.store(*args, **kwargs)
            if args[2:4] == ('GET', 'submissions/30'):
                result['targetPublishMode'] = 'Manual'
            return status, result

        with patch.object(submitter, '_request', side_effect=changed_readback):
            with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT', 'UPLOAD'])

    def test_existing_processing_request_requires_immediate_publication(self):
        self.perform(); self.calls.clear()
        self.new['targetPublishMode'] = 'Manual'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_paid_or_unknown_market_prices_never_mutate_store(self):
        for value in ('Tier2', 'unknown', None, {'priceId': 'Free'}):
            with self.subTest(value=value):
                self.calls.clear(); self.issues.clear()
                self.baseline['pricing']['marketSpecificPricings']['KR'] = value
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), [])

    def test_changed_unavailable_market_ack_never_uploads_or_commits(self):
        self.baseline['pricing']['marketSpecificPricings']['CN'] = 'NotAvailable'

        def changed_ack(*args, **kwargs):
            status, result = self.store(*args, **kwargs)
            if args[2:4] == ('PUT', 'submissions/30'):
                result['pricing']['marketSpecificPricings']['CN'] = 'Base'
            return status, result

        with patch.object(submitter, '_request', side_effect=changed_ack):
            with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT'])

    def test_wrong_put_package_acknowledgment_never_uploads_or_commits(self):
        for mode in ('old_only', 'old_uploaded', 'wrong_target', 'target_uploaded',
                     'missing_directx', 'missing_ram', 'duplicate_target'):
            with self.subTest(mode=mode):
                self.calls.clear(); self.issues.clear()
                self.app['pendingApplicationSubmission'] = {'id': '20'}
                self.put_packages_mode = mode
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT'])

    def test_wrong_fresh_package_readback_never_commits(self):
        self.get_packages_mode = 'old_only'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT', 'UPLOAD'])

    def test_put_package_acknowledgment_allows_server_fields_and_reordering(self):
        self.put_packages_mode = self.get_packages_mode = 'server_fields'
        self.assertEqual(self.perform()['status'], 'PreProcessing')

    def test_delete_refusal_missing_timeout_and_stale_readback_never_create(self):
        for mode in ('refused', 'missing', 'timeout', 'stale', 'nonempty'):
            with self.subTest(mode=mode):
                self.calls.clear(); self.issues.clear()
                self.app['pendingApplicationSubmission'] = {'id': '20'}
                self.delete_mode = mode
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), ['DELETE'])

    def test_unacknowledged_delete_blocks_next_tag_even_when_pending_absent(self):
        self.delete_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.calls.clear(); self.delete_mode = 'success'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_first_manual_submission_is_preserved(self):
        self.app['lastPublishedApplicationSubmission'] = None
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_newer_stable_tag_blocks_older_queued_submission_numerically(self):
        self.tags = [[{'name': 'v1.1.10'}, {'name': 'v1.1.9-dev.41.1'}]]
        self.assertEqual(self.perform()['outcome'], 'superseded')
        self.assertEqual(self.mutations(), [])

    def test_duplicate_processing_request_does_not_replace(self):
        self.perform(); self.calls.clear()
        self.assertEqual(self.perform()['outcome'], 'already_requested')
        self.assertEqual(self.mutations(), [])

    def test_lost_commit_response_recovers_only_from_same_id_status(self):
        self.commit_mode = 'timeout'
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.mutations().count('POST'), 2)

    def test_paid_market_override_blocks_before_delete(self):
        self.baseline['pricing']['marketSpecificPricings']['US'] = 'Tier2'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_tampered_provenance_blocks_before_delete(self):
        self.details['runtimeSha256']['WebView2Loader.dll'] = '0' * 64
        self.write_details()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_development_tag_or_main_source_cannot_submit(self):
        for tag, branch in [('v1.1.3-dev.40.1', 'main'), ('v1.1.3', 'main')]:
            with self.subTest(tag=tag):
                self.tag = tag; self.run['head_branch'] = branch
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), [])

    def test_matching_draft_resumes_without_delete_or_create_after_upload_failure(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.upload_mode = 'success'; self.calls.clear()
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.mutations(), ['PUT', 'UPLOAD', 'POST'])
        self.assertEqual(sum(package['fileName'].startswith('OpenGeul_1.1.3') for package in self.new['applicationPackages']), 1)
        self.assertEqual(self.new['applicationPackages'][0]['version'], '1.1.2.0')

    def test_retry_uses_published_template_instead_of_damaged_draft(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.new['applicationPackages'][0].pop('architecture')
        self.new['notesForCertification'] = 'Changed draft notes'
        self.upload_mode = 'success'; self.calls.clear()
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.mutations(), ['PUT', 'UPLOAD', 'POST'])
        self.assertIn('Keep human notes', self.new['notesForCertification'])

    def test_same_version_unowned_pending_is_preserved(self):
        self.pending['applicationPackages'][0]['version'] = '1.1.3.0'
        self.assertEqual(self.perform()['outcome'], 'superseded')
        self.assertEqual(self.mutations(), [])

    def test_matching_accepted_request_requires_actual_target_package_version(self):
        self.perform(); self.calls.clear()
        self.new['applicationPackages'][-1]['version'] = '1.1.2.0'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_known_commit_failure_resolves_journal_but_warns_same_candidate(self):
        self.commit_mode = 'failed'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        state = submitter._journal_state(self.issues[0]['body'])
        self.assertEqual((state['phase'], state['status']), ('submitted', 'CommitFailed'))
        self.calls.clear()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])
        self.assertIn('https://github.com/ATLKR/OpenGeul/actions/runs/456', self.issues[0]['body'])
        self.assertIn('https://github.com/ATLKR/OpenGeul/releases/tag/v1.1.3', self.issues[0]['body'])

    def test_known_failed_older_commit_can_be_replaced_after_delete_proof(self):
        self.baseline['applicationPackages'][0]['version'] = '1.1.1.0'
        self.pending['status'] = 'CommitFailed'
        state = {'app_id': STORE_APP_ID, 'phase': 'commit_attempted', 'submission_id': '20', 'tag': 'v1.1.2'}
        self.issues.append({'number': 1, 'title': submitter.TITLE, 'body': submitter._journal_body(state),
                            'user': copy.deepcopy(self.bot)})
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.mutations(), ['DELETE', 'POST', 'PUT', 'UPLOAD', 'POST'])

    def test_recorded_draft_disappearance_cannot_create_without_delete_proof(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.app['pendingApplicationSubmission'] = None
        self.calls.clear(); self.upload_mode = 'success'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_unknown_create_response_blocks_all_following_writes(self):
        self.create_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.calls.clear(); self.create_mode = 'success'
        self.app['pendingApplicationSubmission'] = None
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_unknown_commit_response_is_not_retried_by_rerun(self):
        self.commit_mode = 'unknown'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.calls.clear()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_newer_pending_package_appearing_before_delete_is_preserved(self):
        self.before_delete_version = '1.1.10.0'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_unsupported_published_package_is_checked_before_deletion(self):
        self.baseline['applicationPackages'][0]['architecture'] = 'ARM64'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_json_null_delete_body_is_not_an_empty_acknowledgment(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, limit): return b'null'
        class Opener:
            def open(self, request, timeout): return Response()
        self.patches[1].stop()
        status, body = submitter._request(Opener(), 'TOP_SECRET', 'DELETE', 'submissions/20')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'null', 'Only a physically empty DELETE response acknowledges deletion')

    def test_outsider_precreated_same_title_issue_is_ignored(self):
        state = {'app_id': STORE_APP_ID, 'phase': 'delete_attempted', 'deleted_id': '20'}
        self.issues.append({'number': 1, 'title': submitter.TITLE, 'body': submitter._journal_body(state),
                            'user': copy.deepcopy(self.outsider)})
        outsider_body = self.issues[0]['body']
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.issues[0]['body'], outsider_body)
        self.assertEqual(self.issues[1]['user'], self.bot)

    def test_outsider_reset_body_cannot_clear_trusted_unresolved_attempt(self):
        state = {'app_id': STORE_APP_ID, 'phase': 'idle'}
        outsider = {'number': 1, 'title': submitter.TITLE, 'body': submitter._journal_body(state),
                    'user': copy.deepcopy(self.outsider)}
        self.issues.append(outsider)
        self.delete_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['DELETE'])
        self.assertEqual(submitter._journal_state(self.issues[1]['body'])['phase'], 'delete_attempted')
        outsider['body'] = submitter._journal_body(state)
        self.calls.clear(); self.delete_mode = 'success'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])
        self.assertEqual(submitter._journal_state(self.issues[1]['body'])['phase'], 'delete_attempted')

    def test_multiple_trusted_journals_remain_blocking(self):
        state = {'app_id': STORE_APP_ID, 'phase': 'idle'}
        for number in (1, 2):
            self.issues.append({'number': number, 'title': submitter.TITLE, 'body': submitter._journal_body(state),
                                'user': copy.deepcopy(self.bot)})
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_untrusted_issue_acknowledgment_never_authorizes_store_write(self):
        for method in ('POST', 'GET', 'PATCH', 'GET_AFTER_PATCH'):
            with self.subTest(method=method):
                self.calls.clear(); self.issues.clear()
                self.app['pendingApplicationSubmission'] = {'id': '20'}
                self.untrusted_issue_response = method
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), [])

    def test_lookalike_bot_author_does_not_reset_the_journal(self):
        state = {'app_id': STORE_APP_ID, 'phase': 'delete_attempted', 'deleted_id': '20'}
        for field, value in (('id', 1), ('type', 'User'), ('login', 'other[bot]')):
            with self.subTest(field=field):
                self.calls.clear(); self.issues.clear()
                self.app['pendingApplicationSubmission'] = {'id': '20'}
                author = dict(self.bot, **{field: value})
                self.issues.append({'number': 1, 'title': submitter.TITLE, 'body': submitter._journal_body(state),
                                    'user': author})
                self.assertEqual(self.perform()['status'], 'PreProcessing')
                self.assertEqual(self.issues[1]['user'], self.bot)


class DualStoreSubmitTests(unittest.TestCase):
    """실제 두 PE/MSIX/portable/Source WACK와 로컬 Partner Center 상태기계."""
    historical = False
    checksums = StoreSubmitTests.checksums
    write_details = StoreSubmitTests.write_details
    perform = StoreSubmitTests.perform
    mutations = StoreSubmitTests.mutations
    change_packages = StoreSubmitTests.change_packages

    def setUp(self):
        StoreSubmitTests.setUp(self)
        spec = importlib.util.spec_from_file_location('submit_package_fixture', ROOT / 'tests/test_store_package.py')
        fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        pair = fixture.StorePackageTests().dual_release_directory(self.root / 'pair-fixture')
        shutil.rmtree(self.source); shutil.copytree(pair, self.source)
        for path in self.directory.iterdir(): path.unlink()
        self.provenance = json.loads((self.source / 'provenance.json').read_bytes())
        self.details = {'formatVersion': 2, 'storeAppId': STORE_APP_ID, 'identity': dict(STORE_IDENTITY),
            'version': '1.1.3', 'sourceReleaseId': 5, 'sourceRelease': 'https://github.com/ATLKR/OpenGeul/releases/tag/v1.1.3',
            'sourceCommit': self.sha, 'sourceRunId': '123', 'sourceRunAttempt': '1',
            'repackageCommit': 'b' * 40, 'repackageRunId': '456', 'architectures': {},
            'unsigned': True, 'storeCertified': False}
        import release_pair
        self.details['sourceAssetFingerprintSha256'] = release_pair.source_fingerprint(self.source)
        for arch in ('x64', 'arm64'):
            original = self.provenance['architectures'][arch]['provenance']
            with zipfile.ZipFile(self.source / original['package']) as archive:
                files = {name: archive.read(name) for name in archive.namelist()}
            raw = manifest(STORE_IDENTITY, '1.1.3', arch).encode(); files['AppxManifest.xml'] = raw
            name = f'OpenGeul_1.1.3.0_{arch}_store-unsigned.msix'
            with zipfile.ZipFile(self.directory / name, 'w') as archive:
                for member, content in files.items(): archive.writestr(member, content)
            manifest_name = 'AppxManifest-' + arch + '.xml'; (self.directory / manifest_name).write_bytes(raw)
            self.details['architectures'][arch] = {'sourceMsix': original['package'], 'sourceMsixSha256': original['sha256'],
                'package': name, 'sha256': hashlib.sha256((self.directory / name).read_bytes()).hexdigest(), 'manifest': manifest_name,
                'runtimeSha256': {member: hashlib.sha256(content).hexdigest() for member, content in files.items()
                    if member not in {'AppxManifest.xml', 'AppxBlockMap.xml', '[Content_Types].xml'}}}
        (self.directory / 'source-provenance.json').write_bytes((self.source / 'provenance.json').read_bytes())
        self.write_details()
        self.proof = {'formatVersion': 1, 'repository': 'ATLKR/OpenGeul',
            **{key: self.details[key] for key in ('sourceCommit','sourceRunId','sourceRunAttempt','sourceReleaseId','sourceAssetFingerprintSha256','repackageCommit','repackageRunId')},
            'storeRunAttempt': '2', 'storeCertified': False,
            'architectures': {arch: {'architecture': arch, 'fullWackPassed': True,
                'originalMsix': entry['package'], 'originalMsixSha256': entry['sha256'], 'storeCertified': False}
                for arch, entry in self.details['architectures'].items()}}
        # WACK/설치 검사기는 별도 실제 raw12 fixture 검사로 검증된다. 여기서는 해당 경계의 결과를 고정한다.
        self.inspector = patch.object(submitter, '_inspect_qualified', side_effect=lambda *args: copy.deepcopy(self.proof), create=True)
        self.inspect_mock = self.inspector.start(); self.addCleanup(self.inspector.stop)
        self.env = patch.dict(submitter.os.environ, {'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ATTEMPT': '2',
            'GITHUB_ACTOR': 'github-actions[bot]'}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        self.source_jobs = [{'name': name, 'status': 'completed', 'conclusion': 'success',
            'run_id': 123, 'run_attempt': 1, 'head_sha': self.sha} for name in REQUIRED_JOBS]
        self.store_run = {'id': 456, 'head_sha': 'b' * 40, 'head_branch': 'main', 'run_attempt': 2,
            'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}, 'event': 'workflow_dispatch',
            'path': '.github/workflows/store-package.yml', 'status': 'in_progress', 'conclusion': None,
            'actor': copy.deepcopy(self.bot), 'triggering_actor': copy.deepcopy(self.bot)}
        self.store_jobs = [{'name': name, 'status': 'completed', 'conclusion': 'success',
            'run_id': 456, 'run_attempt': 2, 'head_sha': 'b' * 40}
            for name in ('package','Store WACK (windows-2025)','Store WACK (windows-11-arm)','qualify')]
        self.release = {'id': 5, 'draft': False, 'tag_name': self.tag,
            'assets': [{'id': i + 100, 'name': p.name, 'size': p.stat().st_size, 'state': 'uploaded',
                'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()} for i,p in enumerate(sorted(self.source.iterdir()))]}
        self.app['pendingApplicationSubmission'] = None
        self.post_commit_mode = 'success'

    def github(self, method, path, data=None, *, pages=False):
        if path == 'releases/tags/v1.1.3':
            self.calls.append(('github', method, path)); return copy.deepcopy(self.release)
        if path.startswith('actions/runs/123/jobs'):
            self.calls.append(('github', method, path)); return [{'jobs': copy.deepcopy(self.source_jobs)}]
        if path == 'actions/runs/456':
            self.calls.append(('github', method, path)); return copy.deepcopy(self.store_run)
        if path.startswith('actions/runs/456/jobs'):
            self.calls.append(('github', method, path)); return [{'jobs': copy.deepcopy(self.store_jobs)}]
        return StoreSubmitTests.github(self, method, path, data, pages=pages)

    def store(self, opener, token, method, path, data=None):
        if method == 'PUT': self.put_metadata = copy.deepcopy(data)
        status, result = StoreSubmitTests.store(self, opener, token, method, path, data)
        if method == 'POST' and path.endswith('/commit'):
            for arch, entry in self.details['architectures'].items():
                for package in self.new['applicationPackages']:
                    if package.get('fileName') == entry['package']:
                        package.update(architecture=arch.upper(), version='1.1.3.0', fileStatus='Uploaded')
            if self.post_commit_mode == 'no_sdk_fields':
                for package in self.new['applicationPackages']:
                    if package.get('fileStatus') != 'PendingDelete':
                        package.pop('version', None); package.pop('architecture', None)
            if self.post_commit_mode == 'one_package': self.new['applicationPackages'] = self.new['applicationPackages'][:-1]
            if self.post_commit_mode == 'mixed_version': self.new['applicationPackages'][-1]['version'] = '1.1.4.0'
            if self.post_commit_mode == 'wrong_arch': self.new['applicationPackages'][-1]['architecture'] = 'X64'
            if self.post_commit_mode == 'pricing': self.new['pricing']['priceId'] = 'Tier1'
            if self.post_commit_mode == 'listings': self.new['listings'] = {}
            if self.post_commit_mode == 'manual': self.new['targetPublishMode'] = 'Manual'
            if self.post_commit_mode == 'status': self.new['status'] = 'CertificationFailed'
            if self.post_commit_mode == 'failed_after_poll': self.new['status'] = 'PreProcessing'
        if method == 'GET' and path == 'submissions/30' and result.get('status') in submitter.ACCEPTED:
            if self.post_commit_mode == 'failed_after_poll': result['status'] = 'CertificationFailed'
        return status, result

    def upload(self, opener, url, body):
        self.calls.append(('store','UPLOAD','blob'))
        if self.upload_mode == 'timeout': raise submitter.StoreError('upload', None)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(set(archive.namelist()), {e['package'] for e in self.details['architectures'].values()})
            self.assertEqual(len(archive.infolist()), 2)
            for item in archive.infolist():
                self.assertEqual(item.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.read(item), (self.directory / item.filename).read_bytes())

    def rejected(self):
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_pair_upload_and_writable_metadata_preserve_opaque_template(self):
        self.baseline['listings']['ko-kr']['opaque'] = {'keep': ['human']}
        self.baseline['pricing']['marketSpecificPricings']['KR'] = 'NotAvailable'
        result = self.perform(); self.assertEqual(result['outcome'], 'requested')
        self.assertEqual(self.mutations(), ['POST','PUT','UPLOAD','POST'])
        self.inspect_mock.assert_called_once()
        for package in self.new['applicationPackages']:
            if package['fileStatus'] != 'PendingDelete':
                self.assertIn(package['fileName'], [e['package'] for e in self.details['architectures'].values()])
        self.assertEqual(self.new['pricing'], self.baseline['pricing'])
        self.assertEqual(self.new['listings']['ko-kr']['opaque'], {'keep': ['human']})
        uploaded = [p for p in self.put_metadata['applicationPackages'] if p['fileStatus'] == 'PendingUpload']
        self.assertEqual(len(uploaded), 2)
        for package in uploaded:
            self.assertEqual(set(package), {'fileName','fileStatus','minimumDirectXVersion','minimumSystemRam'})

    def test_new_pair_automatically_publishes_after_certification(self):
        original = copy.deepcopy(self.baseline)
        self.assertEqual(self.perform()['outcome'], 'requested')
        self.assertEqual(self.put_metadata['targetPublishMode'], 'Immediate')
        self.assertEqual(self.new['targetPublishMode'], 'Immediate')
        self.assertEqual(self.baseline, original)
        self.assertEqual(self.new['pricing'], original['pricing'])
        self.assertEqual(self.new['listings'], store_listing.apply_korean_listing(original)['listings'])

    def test_published_immediate_baseline_can_supply_next_pair(self):
        self.baseline['targetPublishMode'] = 'Immediate'
        original = copy.deepcopy(self.baseline)
        self.assertEqual(self.perform()['outcome'], 'requested')
        self.assertEqual(self.new['targetPublishMode'], 'Immediate')
        self.assertEqual(self.baseline, original)

    def test_owned_manual_editable_pair_switches_same_sid_without_recreation(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.new['targetPublishMode'] = 'Manual'
        self.calls.clear(); self.upload_mode = 'success'
        result = self.perform()
        self.assertEqual(result['submission_id'], '30')
        self.assertEqual(self.mutations(), ['PUT','UPLOAD','POST'])
        self.assertEqual(self.new['targetPublishMode'], 'Immediate')

    def test_owned_manual_noneditable_pair_is_preserved_without_mutation(self):
        self.perform(); self.new['targetPublishMode'] = 'Manual'
        for status in ('CommitStarted','PreProcessing','Certification','Release','PendingPublication','Publishing'):
            with self.subTest(status=status):
                self.new['status'] = status; original = copy.deepcopy(self.new)
                self.calls.clear()
                with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                self.assertEqual(self.mutations(), [])
                self.assertEqual(self.new, original)
                self.assertNotIn(('store','GET','submissions/30/status'), self.calls)

    def test_manual_unknown_commit_resume_does_not_repeat_or_convert_writes(self):
        self.commit_mode = 'unknown'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.new['targetPublishMode'] = 'Manual'; self.calls.clear()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])
        self.assertNotIn(('store','GET','submissions/30/status'), self.calls)
        self.assertEqual(submitter._journal_state(self.issues[0]['body'])['phase'], 'commit_attempted')

    def test_older_manual_processing_journal_never_authorizes_replacement(self):
        for phase in ('submitted','commit_attempted'):
            for status in ('CommitStarted','PreProcessing','Certification','Release','PendingPublication','Publishing'):
                with self.subTest(phase=phase,status=status):
                    self.calls.clear(); self.issues.clear()
                    self.app['pendingApplicationSubmission'] = {'id':'20'}
                    self.pending['status'] = status
                    state = {'app_id':STORE_APP_ID,'phase':phase,'submission_id':'20','tag':'v1.1.2','status':status}
                    self.issues.append({'number':1,'title':submitter.TITLE,
                        'body':submitter._journal_body(state),'user':copy.deepcopy(self.bot)})
                    original = copy.deepcopy(self.pending)
                    with self.assertRaises(submitter.SubmissionBlocked): self.perform()
                    self.assertEqual(self.mutations(), [])
                    self.assertEqual(self.pending, original)
                    saved = submitter._journal_state(self.issues[0]['body'])
                    for key in ('phase','submission_id','tag','status'):
                        self.assertEqual(saved[key],state[key])
                    self.assertNotIn(('store','GET','submissions/20/status'),self.calls)

    def test_pair_manual_put_ack_stops_before_upload_or_commit(self):
        def changed_ack(*args, **kwargs):
            status, result = self.store(*args, **kwargs)
            if args[2:4] == ('PUT','submissions/30'): result['targetPublishMode'] = 'Manual'
            return status, result
        with patch.object(submitter, '_request', side_effect=changed_ack):
            with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['POST','PUT'])

    def test_pair_manual_fresh_draft_stops_before_commit(self):
        def changed_readback(*args, **kwargs):
            status, result = self.store(*args, **kwargs)
            if args[2:4] == ('GET','submissions/30'): result['targetPublishMode'] = 'Manual'
            return status, result
        with patch.object(submitter, '_request', side_effect=changed_readback):
            with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['POST','PUT','UPLOAD'])

    def test_owned_editable_pair_with_unknown_publish_mode_is_preserved(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.new['targetPublishMode'] = 'SpecificDate'; self.calls.clear(); self.upload_mode = 'success'
        self.rejected()

    def test_external_verifier_rejects_historical_single_source(self):
        self.provenance.pop('formatVersion'); (self.directory / 'source-provenance.json').write_text(json.dumps(self.provenance)); self.checksums(self.directory)
        self.rejected()

    def test_source_release_must_be_whole_canonical_push_same_attempt_and_assets(self):
        for change in ('event','branch','status','attempt','asset'):
            with self.subTest(change=change):
                old_run = copy.deepcopy(self.run); old_release = copy.deepcopy(self.release)
                if change == 'event': self.run['event'] = 'workflow_dispatch'
                if change == 'branch': self.run['head_branch'] = 'main'
                if change == 'status': self.run['conclusion'] = 'failure'
                if change == 'attempt': self.run['run_attempt'] = 2
                if change == 'asset': self.release['assets'][0]['digest'] = 'sha256:' + '0'*64
                self.rejected(); self.run = old_run; self.release = old_release

    def test_source_requires_both_arm_jobs_exact_unique_success(self):
        for change in ('missing','duplicate','failure','other_head','other_attempt'):
            with self.subTest(change=change):
                old = copy.deepcopy(self.source_jobs)
                arm = next(j for j in self.source_jobs if j['name'] == 'msix-install-arm64')
                if change == 'missing': self.source_jobs.remove(arm)
                if change == 'duplicate': self.source_jobs.append(copy.deepcopy(arm))
                if change == 'failure': arm['conclusion'] = 'failure'
                if change == 'other_head': arm['head_sha'] = 'c'*40
                if change == 'other_attempt': arm['run_attempt'] = 2
                self.rejected(); self.source_jobs = old

    def test_current_store_workflow_identity_actors_and_four_jobs_gate(self):
        for change in ('event','ref','path','sha','attempt','repo','actor','trigger','bot_id','missing','duplicate','job_attempt'):
            with self.subTest(change=change):
                old = copy.deepcopy(self.store_run); jobs = copy.deepcopy(self.store_jobs)
                fields = {'event':('event','push'),'ref':('head_branch','other'),'path':('path','.github/workflows/msix.yml'),
                    'sha':('head_sha','c'*40),'attempt':('run_attempt',1)}
                if change in fields: self.store_run[fields[change][0]] = fields[change][1]
                if change == 'repo': self.store_run['repository']['private'] = True
                if change == 'actor': self.store_run['actor'] = {'login':'other','type':'User','id':1}
                if change == 'trigger': self.store_run['triggering_actor'] = {'login':'other','type':'User','id':1}
                if change == 'bot_id': self.store_run['actor']['id'] = 1
                if change == 'missing': self.store_jobs.pop()
                if change == 'duplicate': self.store_jobs.append(copy.deepcopy(self.store_jobs[0]))
                if change == 'job_attempt': self.store_jobs[-1]['run_attempt'] = 1
                self.rejected(); self.store_run = old; self.store_jobs = jobs

    def test_both_store_identity_full_wack_receipt_is_required(self):
        for change in ('missing','failed','other_source','other_store','other_attempt','hash'):
            with self.subTest(change=change):
                old = copy.deepcopy(self.proof)
                if change == 'missing': self.proof['architectures'].pop('arm64')
                if change == 'failed': self.proof['architectures']['arm64']['fullWackPassed'] = False
                if change == 'other_source': self.proof['sourceCommit'] = 'c'*40
                if change == 'other_store': self.proof['repackageCommit'] = 'c'*40
                if change == 'other_attempt': self.proof['storeRunAttempt'] = '1'
                if change == 'hash': self.proof['architectures']['arm64']['originalMsixSha256'] = '0'*64
                self.rejected(); self.proof = old

    def test_pair_marker_and_journal_bind_both_source_and_store_hashes(self):
        self.perform(); state = submitter._journal_state(self.issues[0]['body'])
        self.assertEqual(state['source_asset_fingerprint_sha256'], self.details['sourceAssetFingerprintSha256'])
        self.assertEqual(state['source_msix_sha256_by_arch'], {a:e['sourceMsixSha256'] for a,e in self.details['architectures'].items()})
        self.assertEqual(state['store_msix_sha256_by_arch'], {a:e['sha256'] for a,e in self.details['architectures'].items()})
        marker = json.loads(submitter._marker(self.details)[len(submitter.MARKER):])
        self.assertEqual(marker['sourceAssetFingerprintSha256'], self.details['sourceAssetFingerprintSha256'])
        self.assertEqual(set(marker['architectures']), {'x64','arm64'})

    def test_unknown_pending_draft_is_preserved(self):
        self.app['pendingApplicationSubmission'] = {'id':'20'}; self.rejected()

    def test_paired_upload_retry_requires_full_journal_ownership(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        state = submitter._journal_state(self.issues[0]['body']); state['source_msix_sha256_by_arch']['arm64'] = '0'*64
        self.issues[0]['body'] = submitter._journal_body(state)
        self.new['notesForCertification'] = 'human removed marker'
        self.calls.clear(); self.upload_mode = 'success'
        self.rejected()

    def test_paired_retry_resumes_same_draft_only(self):
        self.upload_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.calls.clear(); self.upload_mode = 'success'
        self.assertEqual(self.perform()['outcome'], 'requested')
        self.assertEqual(self.mutations(), ['PUT','UPLOAD','POST'])

    def test_already_requested_requires_both_exact_versions(self):
        self.perform(); self.calls.clear()
        self.new['applicationPackages'].pop()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_commit_unknown_never_repeats_and_pair_recovery_detects_tamper(self):
        self.commit_mode = 'unknown'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        state = submitter._journal_state(self.issues[0]['body'])
        state['store_msix_sha256_by_arch']['arm64'] = '0'*64; self.issues[0]['body'] = submitter._journal_body(state)
        self.calls.clear(); self.commit_mode = 'success'
        self.rejected()

    def readback_rejected(self, mode):
        self.post_commit_mode = mode
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations().count('POST'), 2)
        self.assertEqual(self.mutations().count('UPLOAD'), 1)
        self.calls.clear()
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_commit_readback_cannot_drop_arm64(self): self.readback_rejected('one_package')
    def test_commit_readback_cannot_mix_versions(self): self.readback_rejected('mixed_version')
    def test_commit_readback_cannot_duplicate_architecture(self): self.readback_rejected('wrong_arch')
    def test_commit_readback_preserves_pricing(self): self.readback_rejected('pricing')
    def test_commit_readback_preserves_listings(self): self.readback_rejected('listings')
    def test_commit_readback_preserves_immediate_control(self): self.readback_rejected('manual')
    def test_failure_between_status_poll_and_readback_remains_blocking(self): self.readback_rejected('failed_after_poll')

    def test_legacy_single_hash_journal_never_owns_current_pair(self):
        state = {'app_id':STORE_APP_ID,'phase':'draft_ready','submission_id':'20','tag':self.tag,
            'source_sha':self.sha,'release_id':'5','run_id':'123',
            'source_msix_sha256':self.details['architectures']['x64']['sourceMsixSha256']}
        self.issues.append({'number':1,'title':submitter.TITLE,'body':submitter._journal_body(state),'user':copy.deepcopy(self.bot)})
        self.app['pendingApplicationSubmission'] = {'id':'20'}; self.rejected()

    def test_owned_older_legacy_failed_submission_can_be_replaced_once(self):
        self.app['pendingApplicationSubmission'] = {'id':'20'}; self.pending['status'] = 'CommitFailed'
        state = {'app_id':STORE_APP_ID,'phase':'submitted','submission_id':'20','tag':'v1.1.2','status':'CommitFailed'}
        self.issues.append({'number':1,'title':submitter.TITLE,'body':submitter._journal_body(state),'user':copy.deepcopy(self.bot)})
        self.assertEqual(self.perform()['outcome'], 'requested')
        self.assertEqual(self.mutations(), ['DELETE','POST','PUT','UPLOAD','POST'])

    def test_published_dual_baseline_accepts_ascii_case_same_version_only(self):
        arm = copy.deepcopy(self.baseline['applicationPackages'][0]); arm.update(fileName='old-arm.msix',architecture='aRm64')
        self.baseline['applicationPackages'].append(arm)
        self.assertEqual(self.perform()['outcome'], 'requested')

    def test_published_dual_baseline_mixed_versions_is_preserved(self):
        arm = copy.deepcopy(self.baseline['applicationPackages'][0]); arm.update(fileName='old-arm.msix',architecture='ARM64',version='1.1.1.0')
        self.baseline['applicationPackages'].append(arm); self.rejected()

    def test_manual_actor_atlkr_and_bot_original_rerun_are_allowed(self):
        self.store_run['triggering_actor'] = {'login':'ATLKR','type':'User','id':1}
        self.assertEqual(self.perform()['outcome'], 'requested')

    def test_source_optional_full_wack_failure_blocks_external_verifier(self):
        xml = self.source / 'wack-arm64.xml'; xml.write_text(xml.read_text().replace('OVERALL_RESULT="PASS"','OVERALL_RESULT="FAIL"'))
        self.checksums(self.source)
        self.rejected()

    def test_missing_arm64_package_or_runtime_replacement_never_uploads(self):
        entry = self.details['architectures']['arm64']; path = self.directory / entry['package']
        with zipfile.ZipFile(path) as archive: files = {n:archive.read(n) for n in archive.namelist()}
        files['Tools/rhwp.exe'] += b'changed'
        with zipfile.ZipFile(path,'w') as archive:
            for n,raw in files.items(): archive.writestr(n,raw)
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.proof['architectures']['arm64']['originalMsixSha256'] = entry['sha256']; self.write_details()
        self.rejected()

    def test_unknown_create_outcome_never_repeats_writes(self):
        self.create_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.calls.clear(); self.create_mode = 'success'; self.app['pendingApplicationSubmission'] = None
        self.rejected()

    def test_owned_delete_timeout_never_creates_or_repeats_deletion(self):
        self.app['pendingApplicationSubmission'] = {'id':'20'}; self.pending['status'] = 'CommitFailed'
        state = {'app_id':STORE_APP_ID,'phase':'submitted','submission_id':'20','tag':'v1.1.2','status':'CommitFailed'}
        self.issues.append({'number':1,'title':submitter.TITLE,'body':submitter._journal_body(state),'user':copy.deepcopy(self.bot)})
        self.delete_mode = 'timeout'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), ['DELETE'])
        self.calls.clear(); self.delete_mode = 'success'; self.rejected()

    def test_unknown_commit_recovers_same_id_without_duplicate_commit(self):
        self.commit_mode = 'unknown'
        with self.assertRaises(submitter.SubmissionBlocked): self.perform()
        self.new['status'] = 'PreProcessing'; self.calls.clear()
        self.assertEqual(self.perform()['outcome'], 'already_requested')
        self.assertEqual(self.mutations(), [])

    def test_preprocessing_without_sdk_version_is_honest_and_does_not_repeat_commit(self):
        self.post_commit_mode = 'no_sdk_fields'
        result = self.perform()
        self.assertEqual(result['outcome'], 'requested')
        self.assertEqual(result['packageMetadataObserved'], False)
        self.calls.clear()
        retry = self.perform(); self.assertEqual(retry['outcome'], 'already_requested')
        self.assertEqual(retry['packageMetadataObserved'], False)
        self.assertEqual(self.mutations(), [])


if __name__ == '__main__': unittest.main()
