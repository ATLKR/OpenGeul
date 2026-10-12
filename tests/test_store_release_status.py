import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import store_release_status as status
except ImportError:
    status = None
from store_package import STORE_APP_ID, STORE_IDENTITY


class StoreReleaseStatusTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(status, '공개 Store 버전 관측기가 없습니다')
        self.public = {'formatVersion': 1, 'appId': STORE_APP_ID, 'status': 'Published',
                       'version': '1.1.1.0', 'storeUrl': 'https://apps.microsoft.com/detail/' + STORE_APP_ID,
                       'submissionId': '1152921505702042424'}
        self.app = {'id': STORE_APP_ID, 'packageIdentityName': STORE_IDENTITY['name'],
                    'publisherName': STORE_IDENTITY['publisher'],
                    'lastPublishedApplicationSubmission': {'id': self.public['submissionId'], 'status': None},
                    'pendingApplicationSubmission': {'id': '99', 'status': 'Certification'}}
        self.submission = {'id': self.public['submissionId'], 'status': 'Published', 'targetPublishMode': 'Manual',
                           'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'US': 'Base', 'ZZ': 'NotAvailable'}},
                           'applicationPackages': [{'version': '1.1.1.0', 'architecture': 'X64', 'fileStatus': 'Uploaded'}],
                           'fileUploadUrl': 'https://private.invalid/?sig=SECRET_SIGNED_URL',
                           'listings': {'PRIVATE_LISTING': {}}}

    def test_published_reference_ignores_pending_and_private_fields(self):
        self.assertEqual(status.metadata_from_store(self.app, self.submission), self.public)
        self.assertNotIn('SECRET', status.encode_metadata(status.metadata_from_store(self.app, self.submission)).decode())
        self.assertEqual(set(self.public), set(status.decode_metadata(status.encode_metadata(self.public))))

    def test_nonpublished_or_mismatching_reference_never_promotes(self):
        for state in ('Certification', 'Release', 'PendingPublication', 'Publishing', 'PendingCommit'):
            with self.subTest(state=state):
                candidate = copy.deepcopy(self.submission); candidate['status'] = state
                with self.assertRaises(ValueError): status.metadata_from_store(self.app, candidate)
        for change in ({'lastPublishedApplicationSubmission': None}, {'lastPublishedApplicationSubmission': {'id': '99'}},
                       {'lastPublishedApplicationSubmission': {'id': self.public['submissionId'], 'status': 'Release'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                status.metadata_from_store({**self.app, **change}, self.submission)

    def test_identity_manual_free_x64_and_uploaded_fail_closed(self):
        cases = [('app', 'id', 'OTHER'), ('app', 'publisherName', 'OTHER'), ('app', 'packageIdentityName', 'OTHER'),
                 ('submission', 'id', '99'), ('submission', 'targetPublishMode', 'Immediate'),
                 ('submission', 'targetPublishMode', 'SpecificDate')]
        for group, key, value in cases:
            app, submission = copy.deepcopy(self.app), copy.deepcopy(self.submission)
            (app if group == 'app' else submission)[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                status.metadata_from_store(app, submission)
        for pricing in ({'priceId': 'Tier1', 'marketSpecificPricings': {}}, {'priceId': 'Free'},
                        {'priceId': 'Free', 'marketSpecificPricings': {'US': 'Tier1'}},
                        {'priceId': 'Free', 'marketSpecificPricings': {'US': {'priceId': 'Free'}}}):
            with self.subTest(pricing=pricing), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'pricing': pricing})
        for package in ({'version': '1.1.1.0', 'architecture': 'x86', 'fileStatus': 'Uploaded'},
                        {'version': '1.1.1.0', 'architecture': 'X64', 'fileStatus': 'PendingUpload'},
                        {'version': '1.1.1.0', 'architecture': 'X64', 'fileStatus': 'PendingDelete'}):
            with self.subTest(package=package), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': [package]})

    def test_multiple_packages_require_one_unambiguous_public_version(self):
        packages = [copy.deepcopy(self.submission['applicationPackages'][0]) for _ in range(2)]
        packages[1]['architecture'] = 'ARM64'
        self.assertEqual(status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': packages}), self.public)
        packages = copy.deepcopy(packages); packages[1]['version'] = '1.1.2.0'
        for value in ([], packages, packages * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': value})

    def test_dual_published_packages_normalize_only_ascii_case_without_expanding_public_schema(self):
        expected = {**self.public, 'version': '1.1.3.0', 'submissionId': '123'}
        app = {**self.app, 'lastPublishedApplicationSubmission': {'id': '123', 'status': 'Published'}}
        for architectures in (('X64', 'ARM64'), ('x64', 'arm64'), ('Arm64', 'x64'), ('aRm64', 'X64')):
            with self.subTest(architectures=architectures):
                submission = {**self.submission, 'id': '123', 'applicationPackages': [
                    {'version': '1.1.3.0', 'architecture': architecture, 'fileStatus': 'Uploaded'}
                    for architecture in architectures]}
                original = copy.deepcopy(submission)
                result = status.metadata_from_store(app, submission)
                self.assertEqual(result, expected)
                self.assertEqual(set(result), {'formatVersion', 'appId', 'status', 'version', 'storeUrl', 'submissionId'})
                self.assertEqual(status.decode_metadata(status.encode_metadata(result)), expected)
                self.assertEqual(submission, original)

    def test_arm64_without_x64_is_not_a_supported_published_package_set(self):
        package = {**self.submission['applicationPackages'][0], 'architecture': 'ARM64'}
        with self.assertRaises(ValueError):
            status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': [package]})

    def test_duplicate_architectures_are_rejected_after_case_normalization(self):
        for architectures in (('X64', 'x64'), ('ARM64', 'arm64'), ('x64', 'ARM64', 'X64'),
                              ('arm64', 'X64', 'ARM64')):
            packages = [{**self.submission['applicationPackages'][0], 'architecture': architecture}
                        for architecture in architectures]
            with self.subTest(architectures=architectures), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': packages})

    def test_dual_packages_reject_unknown_non_ascii_missing_and_nonstring_architectures(self):
        for architecture in ('ARM', 'arm32', 'ARM64EC', 'neutral', 'x86', 'AMD64', '', ' X64', 'arm64 ',
                             'ARM64\n', 'Ｘ64', 'ａｒｍ64', 'x₆₄', None, True, False, 64, [], {}):
            bad = {**self.submission['applicationPackages'][0], 'architecture': architecture}
            with self.subTest(architecture=architecture), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': [
                    self.submission['applicationPackages'][0], bad]})
        for package in ({'version': '1.1.1.0', 'fileStatus': 'Uploaded'}, None, True, 'ARM64'):
            with self.subTest(package=package), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': [
                    self.submission['applicationPackages'][0], package]})

    def test_dual_packages_require_each_package_to_be_uploaded(self):
        for file_status in ('PendingUpload', 'PendingDelete', 'UploadFailed', 'uploaded', None, True):
            for invalid_index in (0, 1):
                packages = [{**self.submission['applicationPackages'][0], 'architecture': architecture}
                            for architecture in ('x64', 'arm64')]
                packages[invalid_index]['fileStatus'] = file_status
                with self.subTest(file_status=file_status, invalid_index=invalid_index), self.assertRaises(ValueError):
                    status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': packages})

    def test_dual_packages_require_one_canonical_four_u16_version(self):
        for version in ('0.0.0.0', '65535.65535.65535.65535'):
            packages = [{'version': version, 'architecture': architecture, 'fileStatus': 'Uploaded'}
                        for architecture in ('x64', 'arm64')]
            self.assertEqual(status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': packages}),
                             {**self.public, 'version': version})
        for version in ('1.1.2.0', '01.1.1.0', '1.1.1', '1.1.1.65536', '1.1.1.-1', '１.1.1.0',
                        '1.1.1.0\n', None, True, 1110):
            packages = [copy.deepcopy(self.submission['applicationPackages'][0]),
                        {'version': version, 'architecture': 'arm64', 'fileStatus': 'Uploaded'}]
            with self.subTest(version=version), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**self.submission, 'applicationPackages': packages})

    def test_dual_packages_still_require_the_owned_published_submission(self):
        submission = {**self.submission, 'applicationPackages': [
            {**self.submission['applicationPackages'][0], 'architecture': architecture}
            for architecture in ('x64', 'arm64')]}
        for change in ({'id': '99'}, {'id': True}, {'status': 'Certification'}, {'status': 'Release'},
                       {'status': 'PendingPublication'}, {'targetPublishMode': 'Immediate'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                status.metadata_from_store(self.app, {**submission, **change})
        for change in ({'id': 'OTHER'}, {'publisherName': 'OTHER'},
                       {'lastPublishedApplicationSubmission': {'id': '99', 'status': 'Published'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                status.metadata_from_store({**self.app, **change}, submission)

    def test_invalid_dual_observation_cannot_update_public_metadata(self):
        duplicate = [copy.deepcopy(self.submission['applicationPackages'][0]) for _ in range(2)]
        class Opener:
            def __init__(self): self.calls = []
            def open(inner, request, timeout):
                inner.calls.append(request.get_method())
                data = self.app if len(inner.calls) == 1 else {**self.submission, 'applicationPackages': duplicate}
                response = io.BytesIO(json.dumps(data).encode()); response.status = 200
                return response
        opener = Opener()
        with patch.object(status, 'require_environment'), patch.object(status, 'authenticate', return_value=(opener, 'TEST_ONLY')), \
                patch.object(status, 'github') as github:
            with self.assertRaises(ValueError): status.refresh()
            github.assert_not_called()
        self.assertEqual(opener.calls, ['GET', 'GET'])

    def test_public_schema_rejects_boolean_extra_duplicate_bad_unicode_and_oversize(self):
        for change in ({'formatVersion': True}, {'formatVersion': 2}, {'schemaVersion': 1}, {'status': 'Release'},
                       {'appId': 'OTHER'}, {'storeUrl': 'https://evil.invalid/'}, {'submissionId': 12},
                       {'submissionId': '0'}, {'submissionId': '1' * 26}, {'token': 'SECRET'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                status.validate_metadata({**self.public, **change})
        for version in ('1.2.3', '01.2.3.4', '1.2.3.65536', '1.2.3.-1', '1.2.3.4\n', '１.2.3.4', '1.2.3.4<script>'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                status.validate_metadata({**self.public, 'version': version})
        for raw in (b'\xff', b'{}' + b' ' * 8192, b'{"formatVersion":1,"formatVersion":1}',
                    b'{"formatVersion":NaN}', b'[]'):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError): status.decode_metadata(raw)

    def test_observer_uses_exact_two_gets_and_bounded_response(self):
        class Opener:
            def __init__(self, values): self.values = list(values); self.calls = []
            def open(self, request, timeout):
                self.calls.append((request.full_url, request.get_method(), timeout))
                response = io.BytesIO(self.values.pop(0)); response.status = 200
                return response
        opener = Opener([json.dumps(self.app).encode(), json.dumps(self.submission).encode()])
        self.assertEqual(status.observe(opener, 'PRIVATE_TOKEN'), self.public)
        base = 'https://manage.devcenter.microsoft.com/v1.0/my/applications/' + STORE_APP_ID
        self.assertEqual(opener.calls, [(base, 'GET', 30), (base + '/submissions/' + self.public['submissionId'], 'GET', 30)])
        for raw in (b'{}' + b' ' * (1024 * 1024), b'{"id":1,"id":2}', b'not json'):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError): status.observe(Opener([raw]), 'SECRET')
        app = {**self.app, 'lastPublishedApplicationSubmission': {'id': '../foreign?sig=SECRET'}}
        opener = Opener([json.dumps(app).encode()])
        with self.assertRaises(ValueError): status.observe(opener, 'SECRET')
        self.assertEqual(len(opener.calls), 1)

    def contents(self, data=None):
        return {'type': 'file', 'path': 'website/store-release.json', 'sha': 'a' * 40,
                'encoding': 'base64', 'content': base64.b64encode(data or status.encode_metadata(self.public)).decode()}

    def test_unchanged_metadata_does_not_commit(self):
        calls = []
        def github(method, path, data=None): calls.append((method, path, data)); return self.contents()
        self.assertFalse(status.synchronize(self.public, github))
        self.assertEqual(calls, [('GET', 'contents/website/store-release.json?ref=main', None)])

    def test_new_public_version_updates_one_file_with_expected_sha(self):
        candidate = {**self.public, 'version': '1.1.3.0', 'submissionId': '123'}
        calls = []
        def github(method, path, data=None):
            calls.append((method, path, data))
            if method == 'GET': return self.contents()
            return {'content': {'path': 'website/store-release.json', 'sha': 'b' * 40}}
        self.assertTrue(status.synchronize(candidate, github))
        self.assertEqual([call[:2] for call in calls], [('GET', 'contents/website/store-release.json?ref=main'),
                                                      ('PUT', 'contents/website/store-release.json')])
        data = calls[1][2]
        self.assertEqual(data['branch'], 'main'); self.assertEqual(data['sha'], 'a' * 40)
        self.assertEqual(status.decode_metadata(base64.b64decode(data['content'], validate=True)), candidate)
        self.assertEqual(set(data), {'branch', 'sha', 'content', 'message'})

    def test_regression_or_foreign_contents_never_writes(self):
        bad = [self.contents(status.encode_metadata({**self.public, 'version': '1.2.0.0'})),
               {**self.contents(), 'path': 'README.md'}, {**self.contents(), 'type': 'symlink'},
               {**self.contents(), 'sha': 'OTHER'}, {**self.contents(), 'content': 'invalid!'},
               self.contents(b'{}'), self.contents(b' ' * 8193)]
        for contents in bad:
            calls = []
            def github(method, path, data=None): calls.append(method); return contents
            with self.subTest(contents=contents), self.assertRaises(ValueError): status.synchronize(self.public, github)
            self.assertEqual(calls, ['GET'])

    def test_failed_cas_is_not_retried_and_never_logs_raw_api_error(self):
        calls = []
        def github(method, path, data=None):
            calls.append(method)
            if method == 'GET': return self.contents()
            raise ValueError('GitHub 메타데이터 갱신에 실패했습니다')
        with self.assertRaises(ValueError): status.synchronize({**self.public, 'version': '1.1.2.0'}, github)
        self.assertEqual(calls, ['GET', 'PUT'])
        completed = type('Response', (), {'returncode': 1, 'stdout': b'', 'stderr': b'PRIVATE_TOKEN https://secret.invalid/?sig=SECRET'})()
        with patch.object(status.subprocess, 'run', return_value=completed):
            with self.assertRaises(ValueError) as error: status.github('PUT', 'contents/website/store-release.json', {})
        self.assertNotIn('SECRET', str(error.exception)); self.assertNotIn('secret.invalid', str(error.exception))

    def test_environment_guard_precedes_auth_or_contents_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            path.write_text(json.dumps({'repository': {'private': False, 'full_name': 'ATLKR/OpenGeul'}}))
            env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_REF': 'refs/heads/main',
                   'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_EVENT_PATH': str(path)}
            with patch.dict(os.environ, env, clear=True): status.require_environment()
            for key, value in [('GITHUB_REPOSITORY', 'fork/OpenGeul'), ('GITHUB_REF', 'refs/heads/other'),
                               ('GITHUB_EVENT_NAME', 'push')]:
                with self.subTest(key=key), patch.dict(os.environ, {**env, key: value}, clear=True), \
                        patch.object(status, 'authenticate') as auth, patch.object(status, 'github') as gh:
                    with self.assertRaises(ValueError): status.refresh()
                    auth.assert_not_called(); gh.assert_not_called()
            path.write_text(json.dumps({'repository': {'private': True, 'full_name': 'ATLKR/OpenGeul'}}))
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError): status.require_environment()

    def test_svg_is_derived_from_validated_version_not_raw_response(self):
        svg = status.badge_svg(self.public).decode('utf-8')
        self.assertIn('1.1.1.0', svg); self.assertIn('Store 공개 버전', svg)
        self.assertNotIn('SECRET', svg); self.assertNotIn('<script', svg)
        with self.assertRaises(ValueError): status.badge_svg({**self.public, 'version': '<script>'})

    def test_hourly_workflow_is_owned_main_only_and_cannot_submit_or_publish(self):
        sys.path.insert(0, str(ROOT / 'ci'))
        from policy import audit, load_workflow
        workflow = load_workflow(ROOT / '.github/workflows/store-status.yml')
        self.assertTrue(audit(workflow))
        self.assertEqual(set(workflow['on']), {'schedule', 'workflow_dispatch'})
        self.assertEqual(workflow['on']['schedule'][0]['cron'], '17 * * * *')
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        self.assertEqual(set(workflow['jobs']), {'observe'})
        job = workflow['jobs']['observe']
        self.assertIn("github.repository == 'ATLKR/OpenGeul'", job['if'])
        self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        self.assertEqual(job['permissions'], {'contents': 'write'})
        commands = [step['run'] for step in job['steps'] if 'run' in step]
        self.assertEqual(commands, ['python scripts/store_release_status.py'])
        self.assertEqual(job['steps'][0]['with']['persist-credentials'], 'false')

    def test_redirects_and_non200_responses_are_rejected(self):
        from transport_cleanup import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid/?sig=SECRET'))
        class Opener:
            def open(self, request, timeout):
                response = io.BytesIO(json.dumps(self.app).encode()); response.status = 201
                return response
            app = self.app
        with self.assertRaises(ValueError): status.observe(Opener(), 'SECRET')

    def test_failed_observation_never_reads_or_updates_github(self):
        with patch.object(status, 'require_environment'), patch.object(status, 'authenticate', return_value=(object(), 'SECRET')), \
                patch.object(status, 'observe', side_effect=ValueError('일치하는 공개 제출이 없습니다')), \
                patch.object(status, 'github') as github:
            with self.assertRaises(ValueError): status.refresh()
            github.assert_not_called()


if __name__ == '__main__': unittest.main()
