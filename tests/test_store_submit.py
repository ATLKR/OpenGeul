import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
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


class StoreSubmitTests(unittest.TestCase):
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
                   'WebView2Loader.dll': b'loader', 'Notices/OpenGeul-LICENSE.txt': b'MIT'}
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
        self.assertEqual(self.new['listings'], self.baseline['listings'])
        self.assertEqual(self.new['targetPublishMode'], 'Manual')
        self.assertIn('Keep human notes', self.new['notesForCertification'])

    def test_free_replacement_preserves_unavailable_markets(self):
        self.baseline['pricing']['marketSpecificPricings'].update(
            KR='Free', CN='NotAvailable', RU='NotAvailable')
        original = copy.deepcopy(self.baseline)
        self.assertEqual(self.perform()['status'], 'PreProcessing')
        self.assertEqual(self.new['pricing'], original['pricing'])
        self.assertEqual(self.baseline, original)

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


if __name__ == '__main__': unittest.main()
