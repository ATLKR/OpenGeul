"""Exercise the bounded diagnostic with external responses and no network calls."""
import copy
import hashlib
import importlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import store_pending_observe as observer


class Response(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.status = status
        self.read_limits = []

    def read(self, size=-1):
        self.read_limits.append(size)
        return super().read(size)


class Opener:
    def __init__(self, values, directory):
        self.values = values
        self.directory = directory
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        if request.get_method() == 'DELETE':
            intent = json.loads((self.directory / 'pre-delete-intent.json').read_text())
            if not intent['deleteCallPlanned']:
                raise AssertionError('DELETE occurred without a persisted local intent')
        value = self.values[len(self.calls) - 1]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value)


class DeleteDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('store_delete_diagnostic'),
                             'The bounded one-DELETE diagnostic implementation is missing')
        self.d = importlib.import_module('store_delete_diagnostic')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'evidence'
        self.app = {'id': observer.APP_ID, 'packageIdentityName': observer.IDENTITY,
                    'pendingApplicationSubmission': {'id': self.d.PENDING},
                    'lastPublishedApplicationSubmission': {'id': self.d.PUBLISHED}}
        self.pending = {'id': self.d.PENDING, 'status': 'PendingCommit',
                        'targetPublishMode': 'Manual',
                        'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'KR': 'Base'}},
                        'packageDeliveryOptions': {'isMandatoryUpdate': False},
                        'applicationPackages': [{'architecture': 'X64', 'version': '1.1.1.0',
                                                 'fileStatus': 'Uploaded'}],
                        'listings': {'private': 'PRIVATE_LISTING'}, 'fileUploadUrl': None}
        self.published = {**copy.deepcopy(self.pending), 'id': self.d.PUBLISHED, 'status': 'Published'}
        self.journal = copy.deepcopy(self.d.EXPECTED_JOURNAL)
        self.hash_patch = patch.object(self.d, 'SEMANTIC_SHA', observer.draft_semantic_fingerprint(self.pending))
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)

    def values(self, deletion=None):
        return [copy.deepcopy(self.app), copy.deepcopy(self.pending), copy.deepcopy(self.published),
                deletion or self.error({'error': {'code': 'InvalidParameter', 'message': 'Invalid submission parameter.'}})]

    def error(self, value, status=400):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return urllib.error.HTTPError('https://private.example/', status, 'PRIVATE_REASON', {}, io.BytesIO(raw))

    def run_probe(self, values=None, journal=None):
        opener = Opener(values if values is not None else self.values(), self.directory)
        result = self.d.probe(opener, 'OAUTH_SECRET', self.journal if journal is None else journal,
                              self.directory, ['CLIENT_SECRET', 'GH_SECRET'])
        return opener, result

    def test_one_empty_body_delete_after_exact_gets_and_persisted_intent(self):
        opener, result = self.run_probe()
        self.assertEqual([(r.get_method(), r.full_url) for r in opener.calls],
                         [('GET', self.d.BASE), ('GET', self.d.BASE + '/submissions/' + self.d.PENDING),
                          ('GET', self.d.BASE + '/submissions/' + self.d.PUBLISHED),
                          ('DELETE', self.d.BASE + '/submissions/' + self.d.PENDING)])
        self.assertIsNone(opener.calls[-1].data)
        self.assertEqual(opener.calls[-1].get_header('Content-type'), 'application/json')
        self.assertEqual(result['outcome'], 'delete-rejected')
        self.assertEqual(result['deleteResponse']['httpStatus'], 400)
        self.assertIs(result['deletionAcknowledged'], False)
        self.assertIs(result['journalMutationPerformed'], False)
        self.assertTrue((self.directory / 'delete-diagnostic.json').is_file())
        self.assertNotIn('PRIVATE_LISTING', json.dumps(result))

    def test_swapped_refs_or_detail_ids_prevent_delete(self):
        for index in range(3):
            with self.subTest(index=index):
                values = self.values()
                if index == 0:
                    values[index]['pendingApplicationSubmission']['id'] = self.d.PUBLISHED
                else:
                    values[index]['id'] = '123'
                self.directory = Path(self.temp.name) / ('swapped-' + str(index))
                opener, result = self.run_probe(values)
                self.assertFalse(any(r.get_method() != 'GET' for r in opener.calls))
                self.assertEqual(result['outcome'], 'guard-rejected')

    def test_changed_baseline_content_prevents_delete(self):
        values = self.values()
        values[2]['listings']['private'] = 'CHANGED_CONTENT'
        opener, result = self.run_probe(values)
        self.assertEqual(len(opener.calls), 3)
        self.assertFalse(result['storeMutationsAttempted'])

    def test_upload_destination_or_unknown_mandatory_flag_prevents_delete(self):
        for role in (1, 2):
            for field in ('fileUploadUrl', 'packageDeliveryOptions'):
                with self.subTest(role=role, field=field):
                    values = self.values()
                    values[role][field] = 'https://private/?sig=SAS_SECRET' if field == 'fileUploadUrl' else {}
                    self.directory = Path(self.temp.name) / (str(role) + '-' + field)
                    opener, result = self.run_probe(values)
                    self.assertFalse(any(r.get_method() == 'DELETE' for r in opener.calls))
                    self.assertEqual(result['outcome'], 'guard-rejected')

    def test_journal_phase_or_old_claim_change_prevents_all_store_calls(self):
        for key, value in (('phase', 'draft_ready'), ('deleted_id', self.d.PUBLISHED),
                           ('source_sha', '0' * 40), ('adopted_pending_id', '123')):
            with self.subTest(key=key):
                self.directory = Path(self.temp.name) / key
                journal = {**self.journal, key: value}
                opener, result = self.run_probe(journal=journal)
                self.assertEqual(opener.calls, [])
                self.assertEqual(result['outcome'], 'guard-rejected')

    def test_duplicate_nonfinite_or_malformed_get_json_prevents_delete(self):
        for index, raw in enumerate((b'{"id":"one","id":"two"}', b'{"x":NaN}', b'{')):
            with self.subTest(index=index):
                self.directory = Path(self.temp.name) / ('bad-json-' + str(index))
                opener, result = self.run_probe([raw])
                self.assertEqual(len(opener.calls), 1)
                self.assertEqual(result['outcome'], 'guard-rejected')

    def test_existing_local_intent_prevents_a_second_invocation(self):
        self.run_probe()
        opener = Opener(self.values(), self.directory)
        with self.assertRaises(ValueError):
            self.d.probe(opener, 'OAUTH_SECRET', self.journal, self.directory)
        self.assertEqual(opener.calls, [])

    def test_error_top_nested_messages_and_secrets_are_projected_safely(self):
        import base64
        body = {'code': 'InvalidParameter', 'message': 'Invalid parameter.',
                'error': {'code': 'Conflict', 'message': 'CLIENT_SECRET https://private/?sig=SAS_SECRET Bearer OAUTH_SECRET ' + base64.b64encode(b'GH_SECRET').decode()},
                'errors': [{'code': 'NestedCode', 'message': 'Nested explanation.'}],
                'private': 'PRIVATE_RAW_FIELD'}
        _, result = self.run_probe(self.values(self.error(body)))
        encoded = json.dumps(result)
        for value in ('CLIENT_SECRET', 'OAUTH_SECRET', 'GH_SECRET', 'SAS_SECRET', 'https://', 'PRIVATE_RAW_FIELD'):
            self.assertNotIn(value, encoded)
        self.assertEqual([v['code'] for v in result['deleteResponse']['errors']],
                         ['InvalidParameter', 'Conflict', 'NestedCode'])

    def test_response_cap_retains_prefix_hash_and_no_partial_projection(self):
        raw = b'X' * (64 * 1024 + 100)
        error = self.error(raw)
        _, result = self.run_probe(self.values(error))
        receipt = result['deleteResponse']
        self.assertEqual(receipt['responseBytesCaptured'], 64 * 1024)
        self.assertTrue(receipt['responseTruncated'])
        self.assertEqual(receipt['responseSha256'], hashlib.sha256(raw[:64 * 1024]).hexdigest())
        self.assertEqual(receipt['errors'], [])
        self.assertEqual(receipt['projection'], 'truncated')

    def test_malformed_or_duplicate_error_body_keeps_status_and_hash_without_raw_body(self):
        for index, raw in enumerate((b'PRIVATE_RAW_BODY', b'{"message":"one","message":"PRIVATE_RAW_BODY"}')):
            with self.subTest(index=index):
                self.directory = Path(self.temp.name) / ('bad-error-' + str(index))
                _, result = self.run_probe(self.values(self.error(raw)))
                receipt = result['deleteResponse']
                self.assertEqual(receipt['httpStatus'], 400)
                self.assertEqual(receipt['responseSha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(receipt['errors'], [])
                self.assertNotIn('PRIVATE_RAW_BODY', json.dumps(result))

    def test_unknown_transport_outcome_stops_without_retry(self):
        opener, result = self.run_probe(self.values(TimeoutError('PRIVATE_TIMEOUT')))
        self.assertEqual(len(opener.calls), 4)
        self.assertEqual(result['outcome'], 'delete-unacknowledged')
        self.assertIsNone(result['deleteResponse']['httpStatus'])
        self.assertNotIn('PRIVATE_TIMEOUT', json.dumps(result))

    def test_nonempty_success_is_not_acknowledged_or_followed_by_gets(self):
        opener, result = self.run_probe(self.values(Response(b'null', 200)))
        self.assertEqual(len(opener.calls), 4)
        self.assertEqual(result['outcome'], 'delete-unacknowledged')
        self.assertFalse(result['deletionAcknowledged'])

    def test_success_requires_no_pending_old_404_and_unchanged_published(self):
        values = self.values(Response(b'', 204)) + [
            {**self.app, 'pendingApplicationSubmission': None}, self.error(b'', 404), self.published]
        opener, result = self.run_probe(values)
        self.assertEqual([r.get_method() for r in opener.calls], ['GET', 'GET', 'GET', 'DELETE', 'GET', 'GET', 'GET'])
        self.assertEqual(result['outcome'], 'delete-acknowledged-and-reconciled')
        self.assertTrue(result['deletionAcknowledged'])
        self.assertTrue(result['deletionReconciled'])
        self.assertFalse(result['journalMutationPerformed'])
        self.assertEqual(self.journal['phase'], 'delete_attempted')

    def test_success_followed_by_wrong_or_missing_references_stays_unreconciled(self):
        for app in ({**self.app}, {key: value for key, value in self.app.items() if key != 'pendingApplicationSubmission'}):
            self.directory = Path(self.temp.name) / ('present' if 'pendingApplicationSubmission' in app else 'missing')
            opener, result = self.run_probe(self.values(Response(b'', 204)) + [app])
            self.assertEqual(len(opener.calls), 5)
            self.assertTrue(result['deletionAcknowledged'])
            self.assertFalse(result['deletionReconciled'])

    def test_workflow_scope_blocks_rerun_actor_ref_or_confirmation_change(self):
        env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REF': self.d.REF, 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_ACTOR': 'ATLKR',
               'GITHUB_JOB': 'delete-diagnostic', 'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/store-package.yml@' + self.d.REF,
               'GITHUB_SHA': '1' * 40, 'GITHUB_RUN_ID': '123', 'DELETE_PENDING_ID': self.d.PENDING}
        with patch.dict('os.environ', env, clear=True):
            self.d.workflow_scope()
        for key, value in (('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_ACTOR', 'other'),
                           ('GITHUB_REF', 'refs/heads/main'), ('DELETE_PENDING_ID', self.d.PUBLISHED)):
            with self.subTest(key=key), patch.dict('os.environ', {**env, key: value}, clear=True):
                with self.assertRaises(ValueError):
                    self.d.workflow_scope()

    def test_issue_read_checks_exact_owner_and_strict_journal_json(self):
        issue = {'number': 20, 'id': 5819766913, 'title': 'OpenGeul Store submission state (' + self.d.APP_ID + ')',
                 'state': 'open', 'html_url': 'https://github.com/ATLKR/OpenGeul/issues/20',
                 'url': 'https://api.github.com/repos/ATLKR/OpenGeul/issues/20',
                 'user': {'login': 'github-actions[bot]', 'type': 'Bot', 'id': 41898282},
                 'body': 'warning text\n<!-- opengeul-store-state\n' + json.dumps(self.journal) + '\n-->\n'}
        self.assertEqual(self.d.parse_journal(json.dumps(issue).encode()), self.journal)
        for key, value in (('number', 21), ('user', {**issue['user'], 'login': 'other'}),
                           ('body', '<!-- opengeul-store-state\n{"phase":"delete_attempted","phase":"idle"}\n-->')):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.d.parse_journal(json.dumps({**issue, key: value}).encode())

    def test_only_first_exact_head_dispatch_passes_run_history_guard(self):
        run = {'id': 123, 'head_sha': '1' * 40, 'head_branch': 'diagnostic/store-delete-reason-113',
               'event': 'workflow_dispatch', 'path': '.github/workflows/store-package.yml', 'run_attempt': 1,
               'actor': {'login': 'ATLKR', 'type': 'User'}, 'triggering_actor': {'login': 'ATLKR', 'type': 'User'},
               'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}}
        env = {'GITHUB_SHA': '1' * 40, 'GITHUB_RUN_ID': '123'}
        with patch.dict('os.environ', env):
            self.d.check_runs(json.dumps({'total_count': 1, 'workflow_runs': [run]}).encode())
            for runs, count in (([run, {**run, 'id': 124}], 2), ([{**run, 'id': 124}], 1),
                                ([{**run, 'triggering_actor': {'login': 'other', 'type': 'User'}}], 1),
                                ([run], 100)):
                with self.subTest(count=count, runs=len(runs)):
                    with self.assertRaises(ValueError):
                        self.d.check_runs(json.dumps({'total_count': count, 'workflow_runs': runs}).encode())

    def test_quoted_credentials_lowercase_escaped_secrets_and_nested_codes_are_redacted(self):
        import urllib.parse
        secret = 'CLIENT/PRIVATE?VALUE'
        body = {'error': {'code': 'OwnershipConflict', 'message': 'client_secret="RETURNED_SECRET" {"access_token":"RETURNED_TOKEN"} ' + urllib.parse.quote(secret, safe='').lower(),
                          'innererror': {'code': 'DashboardOwned', 'details': {'private': 'PRIVATE_FIELD'}}}}
        opener = Opener(self.values(self.error(body)), self.directory)
        result = self.d.probe(opener, 'OAUTH_SECRET', self.journal, self.directory, [secret])
        text = json.dumps(result)
        for value in ('RETURNED_SECRET', 'RETURNED_TOKEN', 'client%2fprivate%3fvalue', 'PRIVATE_FIELD'):
            self.assertNotIn(value, text)
        self.assertEqual([v['code'] for v in result['deleteResponse']['errors']], ['OwnershipConflict', 'DashboardOwned'])

    def test_body_read_failure_keeps_http_status_without_retry(self):
        class Unreadable(Response):
            def read(self, size=-1):
                raise TimeoutError('PRIVATE_READ_ERROR')
        opener, result = self.run_probe(self.values(Unreadable(b'', 204)))
        self.assertEqual(len(opener.calls), 4)
        self.assertEqual(result['deleteResponse']['httpStatus'], 204)
        self.assertTrue(result['deleteResponse']['responseBodyUnavailable'])
        self.assertFalse(result['deletionAcknowledged'])

    def test_projection_has_depth_item_and_utf8_message_budgets(self):
        body = {'errors': [{'code': 'LongError', 'message': '\x1b[31m\x00\u202e' + '가' * 400} for _ in range(20)]}
        _, result = self.run_probe(self.values(self.error(body)))
        errors = result['deleteResponse']['errors']
        self.assertEqual(len(errors), 16)
        self.assertTrue(all(len(v['message'].encode()) <= 1024 and v['messageTruncated'] for v in errors))
        self.assertNotIn('\\u202e', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
