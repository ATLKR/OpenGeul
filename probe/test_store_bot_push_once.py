"""실제 네트워크 없이 고정 저장소/내용/CAS/단일 쓰기와 실패 기록을 검증한다."""
import base64
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bot_once', Path(__file__).with_name('store_bot_push_once.py'))
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)
META = {'formatVersion': 1, 'appId': '9PJH0T3PHRMF', 'status': 'Published',
        'version': '1.1.1.0', 'storeUrl': 'https://apps.microsoft.com/detail/9PJH0T3PHRMF',
        'submissionId': '1152921505702042424'}
RAW = (json.dumps(META, ensure_ascii=False, indent=2) + '\n').encode()
OLD_BLOB = '84458dd0b22b02f3128c44119afad4f07fe851d2'  # Git hash-object 원문 fixture
NEW_BLOB = '724225a71c582333f771c53a9fceeadf9e755541'  # Git hash-object LF 추가 fixture
NEW_BYTES_SHA = '834865fe11700807860205094904d44646cbf81371a5a5dbf6d82aaea0186ad7'
HEAD = '1' * 40
NEW_HEAD = '2' * 40
PREFIX = 'repos/ATLKR/OpenGeul/'
REF = PREFIX + 'git/ref/heads/main'
FILE = PREFIX + 'contents/website/store-release.json'


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


class MemoryRepository:
    def __init__(self, raw=RAW):
        self.raw, self.head = raw, HEAD
        self.calls = []
        self.path = 'website/store-release.json'
        self.reported_blob = None
        self.fail_put = False
        self.commit_fault = None
        self.before_put_head = None
        self.concurrent_raw = None

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == 'GET' and path == REF:
            # 세 번째 main 읽기 전에 다른 writer가 head를 바꾸는 상황.
            reads = sum(p == REF for _, p, _ in self.calls)
            if self.before_put_head and reads == 2:
                self.head = self.before_put_head
            return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': self.head}}
        if method == 'GET' and path == FILE + '?ref=main':
            return {'type': 'file', 'path': self.path, 'encoding': 'base64', 'size': len(self.raw),
                    'sha': self.reported_blob or blob(self.raw),
                    'content': base64.b64encode(self.raw).decode()}
        if method == 'PUT' and path == FILE:
            if self.fail_put:
                raise ValueError('controlled PUT rejection')
            if self.concurrent_raw is not None:
                self.raw = self.concurrent_raw
            if body['sha'] != blob(self.raw):
                raise ValueError('CAS conflict')
            self.parent = self.head
            self.raw = base64.b64decode(body['content'], validate=True)
            self.head = NEW_HEAD
            return {'content': {'path': self.path, 'sha': blob(self.raw)},
                    'commit': {'sha': NEW_HEAD, 'parents': [{'sha': self.parent}]}}
        if method == 'GET' and path == PREFIX + 'commits/' + NEW_HEAD:
            value = {'sha': NEW_HEAD, 'parents': [{'sha': self.parent}],
                     'files': [{'filename': 'website/store-release.json', 'status': 'modified',
                                'sha': blob(self.raw)}]}
            if self.commit_fault:
                self.commit_fault(value)
            return value
        raise AssertionError('unexpected API route: ' + method + ' ' + path)

    @property
    def puts(self):
        return [c for c in self.calls if c[0] == 'PUT']


class OnePushControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        event = Path(self.tmp.name) / 'event.json'
        event.write_text(json.dumps({'repository': {'private': False, 'full_name': 'ATLKR/OpenGeul'}}))
        self.env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul',
                    'GITHUB_REF': 'refs/heads/diagnostic/store-bot-push-once',
                    'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/store-bot-push-once',
                    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_EVENT_PATH': str(event),
                    'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                    'GITHUB_TOKEN': 'offline-test-token', 'GH_TOKEN': 'offline-test-token'}
        self.pin(RAW)

    def pin(self, raw):
        p = patch.multiple(bot, EXPECTED_MAIN_SHA=HEAD, EXPECTED_BLOB_SHA=blob(raw),
                           EXPECTED_BYTES_SHA256=hashlib.sha256(raw).hexdigest())
        p.start()
        self.addCleanup(p.stop)

    def reject(self, repo, env=None):
        receipt = {}
        with self.assertRaises(ValueError):
            bot.execute(repo.request, env or self.env, receipt)
        return receipt

    def test_success_preserves_all_values_and_appends_exactly_one_lf_with_one_put(self):
        repo, receipt = MemoryRepository(), {}
        result = bot.execute(repo.request, self.env, receipt)
        self.assertEqual(repo.raw, RAW + b'\n')
        self.assertEqual(json.loads(repo.raw), META)
        self.assertEqual(len(repo.puts), 1)
        self.assertEqual(repo.puts[0][1], FILE)
        self.assertEqual(repo.puts[0][2]['sha'], OLD_BLOB)
        self.assertEqual(repo.puts[0][2]['branch'], 'main')
        self.assertEqual(result['commitSha'], NEW_HEAD)
        self.assertEqual(result['newBlobSha'], NEW_BLOB)
        self.assertEqual(result['newBytesSha256'], NEW_BYTES_SHA)
        self.assertTrue(result['onePathVerified'])
        self.assertFalse(result['cloudflareBuildVerified'])

    def test_unfilled_any_pin_refuses_even_api_reads(self):
        for name in ['EXPECTED_MAIN_SHA', 'EXPECTED_BLOB_SHA', 'EXPECTED_BYTES_SHA256']:
            with self.subTest(name=name), patch.object(bot, name, 'ROOT_FILL_THIS_PIN'):
                repo = MemoryRepository()
                self.reject(repo)
                self.assertEqual(repo.calls, [])

    def test_other_repository_ref_event_workflow_or_token_has_zero_api_calls(self):
        changes = [('GITHUB_REPOSITORY', 'other/OpenGeul'), ('GITHUB_REF', 'refs/heads/main'),
                   ('GITHUB_EVENT_NAME', 'schedule'), ('GITHUB_RUN_ATTEMPT', '2'),
                   ('GITHUB_WORKFLOW_REF', 'other/workflow.yml'), ('GH_TOKEN', 'different-token'),
                   ('GITHUB_TOKEN', ''), ('GITHUB_RUN_ID', 'invalid')]
        for key, value in changes:
            with self.subTest(key=key):
                repo = MemoryRepository()
                self.reject(repo, {**self.env, key: value})
                self.assertEqual(repo.calls, [])

    def test_private_or_different_public_event_has_zero_api_calls(self):
        event = Path(self.env['GITHUB_EVENT_PATH'])
        for value in [{'private': True, 'full_name': 'ATLKR/OpenGeul'},
                      {'private': False, 'full_name': 'other/OpenGeul'},
                      {'private': 'false', 'full_name': 'ATLKR/OpenGeul'}]:
            event.write_text(json.dumps({'repository': value}))
            repo = MemoryRepository()
            self.reject(repo)
            self.assertEqual(repo.calls, [])

    def test_main_head_mismatch_stops_before_any_put(self):
        repo = MemoryRepository()
        repo.head = '3' * 40
        self.reject(repo)
        self.assertEqual(repo.puts, [])

    def test_file_identity_blob_pin_and_byte_pin_each_block_before_put(self):
        for kind in ['path', 'blob', 'bytes']:
            with self.subTest(kind=kind):
                repo = MemoryRepository()
                if kind == 'path':
                    repo.path = 'website/index.html'
                elif kind == 'blob':
                    repo.reported_blob = '3' * 40
                else:
                    repo.raw += b'\n'
                    with patch.object(bot, 'EXPECTED_BLOB_SHA', blob(repo.raw)):
                        self.reject(repo)
                        self.assertEqual(repo.puts, [])
                    continue
                self.reject(repo)
                self.assertEqual(repo.puts, [])

    def test_changed_publication_values_or_extra_fields_block_even_when_hashes_match(self):
        mutations = [{'version': '1.1.2.0'}, {'submissionId': '1152921505702042425'},
                     {'status': 'Certification'}, {'appId': 'OTHERPRODUCT'}, {'extra': 'new'},
                     {'formatVersion': True}]
        for changes in mutations:
            with self.subTest(changes=changes):
                raw = (json.dumps({**META, **changes}) + '\n').encode()
                self.pin(raw)
                repo = MemoryRepository(raw)
                self.reject(repo)
                self.assertEqual(repo.puts, [])

    def test_duplicate_fields_and_oversized_json_block_before_put(self):
        for raw in [RAW.replace(b'"formatVersion": 1,', b'"formatVersion": 1, "formatVersion": 1,'),
                    RAW + b' ' * 8192]:
            self.pin(raw)
            repo = MemoryRepository(raw)
            self.reject(repo)
            self.assertEqual(repo.puts, [])

    def test_fresh_head_change_stops_before_put(self):
        repo = MemoryRepository()
        repo.before_put_head = '3' * 40
        self.reject(repo)
        self.assertEqual(repo.puts, [])

    def test_put_failure_is_attempted_once_and_not_reported_as_verified(self):
        repo = MemoryRepository()
        repo.fail_put = True
        receipt = self.reject(repo)
        self.assertEqual(len(repo.puts), 1)
        self.assertTrue(receipt['putAttempted'])
        self.assertFalse(receipt['onePathVerified'])
        self.assertNotEqual(receipt.get('status'), 'success')
        self.assertEqual(repo.raw, RAW)

    def test_concurrent_file_change_at_put_is_preserved_by_cas_and_never_retried(self):
        repo = MemoryRepository()
        repo.concurrent_raw = RAW + b'  \n'
        receipt = self.reject(repo)
        self.assertEqual(len(repo.puts), 1)
        self.assertEqual(repo.raw, repo.concurrent_raw)
        self.assertTrue(receipt['putAttempted'])
        self.assertFalse(receipt['putResponseReceived'])
        self.assertFalse(receipt['onePathVerified'])

    def test_wrong_commit_parent_path_or_new_blob_cannot_claim_success_or_retry(self):
        faults = [lambda r: r['parents'][0].update(sha='3' * 40),
                  lambda r: r['files'][0].update(filename='website/index.html'),
                  lambda r: r['files'].append({'filename': 'other.txt', 'sha': '3' * 40}),
                  lambda r: r['files'][0].update(sha='3' * 40)]
        for fault in faults:
            with self.subTest(fault=fault):
                repo = MemoryRepository()
                repo.commit_fault = fault
                receipt = self.reject(repo)
                self.assertEqual(len(repo.puts), 1)
                self.assertFalse(receipt['onePathVerified'])
                self.assertEqual(receipt['commitSha'], NEW_HEAD)

    def test_second_dispatch_after_success_refuses_additional_put(self):
        repo = MemoryRepository()
        bot.execute(repo.request, self.env, {})
        self.reject(repo)
        self.assertEqual(len(repo.puts), 1)
        self.assertEqual(repo.raw, RAW + b'\n')

    def test_api_wrapper_refuses_any_other_host_route_method_before_subprocess(self):
        with patch.object(bot, 'subprocess', create=True) as process:
            for method, path in [('DELETE', FILE), ('PUT', PREFIX + 'contents/website/index.html'),
                                 ('GET', 'https://example.invalid/signed?secret=value')]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    bot.github(method, path)
            process.run.assert_not_called()

    def test_cli_failure_receipt_and_log_exclude_exception_token_and_signed_url(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bot, 'RECEIPT_PATH', Path(folder) / 'receipt.json', create=True):
            secret = 'secret-token https://example.invalid/signed?secret=value'
            with patch.object(bot, 'execute', side_effect=RuntimeError(secret)), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(bot.main(), 1)
            text = output.getvalue() + (Path(folder) / 'receipt.json').read_text()
            self.assertNotIn(secret, text)
            self.assertNotIn('signed?', text)
            self.assertNotIn('secret-token', text)


if __name__ == '__main__':
    unittest.main()
