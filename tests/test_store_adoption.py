"""Store API transport fakes exercise the real submission state machine.

The existing Store tests and an independent immutable-original replay verify
the package qualification boundary. These tests supply that verified result;
they do not claim to execute WACK, MSIX or a real Store request.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import store_submit as writer
from store_package import STORE_APP_ID, STORE_IDENTITY

PENDING = '1152921505702100805'
PUBLISHED = '1152921505702042424'
SOURCE = '859f676167b258a7a6a57ecdfcb0e224338de01a'
FINGERPRINT = 'fa5e0d0857d7e5d3331c731d408cea0aad9656f55ae25e68b70c4504c01cd11e'
EXCLUDED = {'id', 'status', 'statusDetails', 'fileUploadUrl', 'friendlyName'}

def semantic(value):
    data = {k: v for k, v in value.items() if k not in EXCLUDED}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()

class StoreAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.actor = {'login': 'ATLKR', 'type': 'User', 'id': 65988341}
        self.bot = {'login': 'github-actions[bot]', 'type': 'Bot', 'id': 41898282}
        self.details = {'formatVersion': 2, 'storeAppId': STORE_APP_ID,
            'identity': copy.deepcopy(STORE_IDENTITY), 'version': '1.1.3',
            'sourceCommit': SOURCE, 'sourceRunId': '38294374822',
            'sourceRunAttempt': '1', 'sourceReleaseId': 410953892,
            'sourceAssetFingerprintSha256': FINGERPRINT,
            'repackageCommit': 'b' * 40, 'repackageRunId': '999',
            'architectures': {arch: {'package': f'OpenGeul_1.1.3.0_{arch}_store-unsigned.msix',
                'sourceMsixSha256': str(i) * 64, 'sha256': str(i + 2) * 64}
                for i, arch in enumerate(('x64', 'arm64'), 1)}}
        self.app = {'id': STORE_APP_ID, 'packageIdentityName': STORE_IDENTITY['name'],
            'publisherName': STORE_IDENTITY['publisher'],
            'pendingApplicationSubmission': {'id': PENDING},
            'lastPublishedApplicationSubmission': {'id': PUBLISHED}}
        self.baseline = {'id': PUBLISHED, 'status': 'Published',
            'targetPublishMode': 'Manual',
            'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'US': 'Base'}},
            'listings': {'ko-kr': {'baseListing': {'title': 'OpenGeul', 'images': []}}},
            'notesForCertification': '사람이 작성한 기존 메모',
            'applicationPackages': [{'id': '11', 'fileName': 'old.msix',
                'fileStatus': 'Uploaded', 'version': '1.1.1.0', 'architecture': 'X64',
                'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None'}]}
        self.pending = dict(copy.deepcopy(self.baseline), id=PENDING,
            status='PendingCommit')
        self.approved_hash = semantic(self.pending)
        self.issue = {'number': 20, 'title': writer.TITLE,
            'body': writer._journal_body({'app_id': STORE_APP_ID, 'phase': 'idle'}),
            'user': copy.deepcopy(self.bot)}
        self.run = {'id': 999, 'head_sha': 'b' * 40, 'head_branch': 'main',
            'run_attempt': 1, 'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False},
            'event': 'workflow_dispatch', 'path': '.github/workflows/store-package.yml',
            'status': 'in_progress', 'conclusion': None,
            'actor': copy.deepcopy(self.actor), 'triggering_actor': copy.deepcopy(self.actor)}
        self.jobs = [{'name': name, 'status': 'completed', 'conclusion': 'success',
            'run_id': 999, 'run_attempt': 1, 'head_sha': 'b' * 40} for name in
            ('package', 'store-native-arm64', 'Store WACK (x64)', 'Store WACK (arm64)', 'qualify')]
        self.event = {'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False},
            'sender': copy.deepcopy(self.actor),
            'inputs': {'adopt_pending_submission': 'true',
                'adoption_draft_sha256': self.approved_hash}}
        self.event_path = self.root / 'event.json'
        self.write_event()
        self.env = {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_EVENT_PATH': str(self.event_path),
            'GITHUB_ACTOR': 'ATLKR', 'GITHUB_SHA': 'b' * 40,
            'GITHUB_RUN_ID': '999', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_JOB': 'submit',
            'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/main',
            'STORE_ADOPT_PENDING': 'true', 'STORE_ADOPTION_DRAFT_SHA256': self.approved_hash}
        self.calls = []
        self.put_count = self.commit_count = 0
        self.put_receipts = []
        self.change_after_claim = None
        self.commit_timeout = False
        self.upload_timeout = False
        self.put_timeout = False
        self.upload_destination = 'opaque-upload-location'
        self.put_ack_change = None
        self.journal_race = False
        for active in (patch.dict(writer.os.environ, self.env, clear=True),
            patch.object(writer, '_verify', side_effect=self.verified),
            patch.object(writer, '_gh', side_effect=self.github),
            patch.object(writer, '_request', side_effect=self.store),
            patch.object(writer, '_upload', side_effect=self.upload),
            patch.object(writer, 'authenticate', return_value=(object(), 'synthetic')),
            patch.object(writer.time, 'sleep')):
            active.start(); self.addCleanup(active.stop)

    def write_event(self):
        self.event_path.write_text(json.dumps(self.event), encoding='utf-8')

    def verified(self, tag, directory):
        self.calls.append(('qualification', tag))
        return copy.deepcopy(self.details), (1, 1, 3), b'exact-qualified-package-pair'

    def github(self, method, path, data=None, *, pages=False):
        self.calls.append(('github', method, path))
        if path.startswith('issues?'): return [[copy.deepcopy(self.issue)]]
        if path == 'issues/20':
            if (method == 'GET' and self.journal_race
                    and sum(c == ('github', 'GET', 'issues/20') for c in self.calls) == 2):
                self.issue['body'] = writer._journal_body({'app_id': STORE_APP_ID,
                    'phase': 'create_attempted'})
            if method == 'PATCH':
                self.issue.update(copy.deepcopy(data))
                phase = writer._journal_state(self.issue['body'])['phase']
                if phase == 'draft_ready' and self.change_after_claim:
                    self.change_after_claim()
            return copy.deepcopy(self.issue)
        if path.startswith('tags?'): return [[{'name': 'v1.1.3'}]]
        if path == 'actions/runs/999': return copy.deepcopy(self.run)
        if path.startswith('actions/runs/999/jobs'): return [{'jobs': copy.deepcopy(self.jobs)}]
        raise AssertionError((method, path))

    def store(self, opener, token, method, path, data=None):
        self.calls.append(('store', method, path))
        if method == 'GET':
            if path == '': return 200, copy.deepcopy(self.app)
            if path == 'submissions/' + self.baseline['id']: return 200, copy.deepcopy(self.baseline)
            if path in ('submissions/' + PENDING, 'submissions/' + PENDING + '/status'):
                return 200, copy.deepcopy(self.pending)
        if method == 'PUT' and path == 'submissions/' + PENDING:
            self.put_count += 1
            self.pending.update(copy.deepcopy(data))
            if self.upload_destination is not None:
                self.pending['fileUploadUrl'] = self.upload_destination
            self.put_receipts.append(copy.deepcopy(self.pending))
            if self.put_timeout: raise writer.StoreError('PUT', None)
            result = copy.deepcopy(self.pending)
            if self.put_ack_change: self.put_ack_change(result)
            return 200, result
        if method == 'POST' and path == 'submissions/' + PENDING + '/commit':
            self.commit_count += 1
            if self.commit_timeout: raise writer.StoreError('commit', None)
            self.pending['status'] = 'PreProcessing'
            for item in self.pending['applicationPackages']:
                if item['fileStatus'] == 'PendingUpload':
                    item.update(fileStatus='Uploaded', version='1.1.3.0',
                        architecture='ARM64' if '_arm64_' in item['fileName'] else 'X64')
            return 200, {'status': 'CommitStarted'}
        raise AssertionError('Unexpected Store mutation: ' + method + ' ' + path)

    def upload(self, opener, location, body):
        self.calls.append(('upload', location, body))
        if self.upload_timeout: raise writer.StoreError('upload', None)

    def perform(self):
        return writer.submit('v1.1.3', self.root)

    def mutations(self):
        return [call for call in self.calls if call[0] == 'upload'
            or call[0] == 'store' and call[1] != 'GET']

    def rejected(self):
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(), [])

    def test_explicit_manual_root_adopts_only_approved_existing_sid(self):
        try: result = self.perform()
        except writer.SubmissionBlocked: result = None
        self.assertIsNotNone(result, 'An explicit approved PendingCommit draft should use the same SID')
        self.assertEqual(result['submission_id'], PENDING)
        self.assertEqual([(c[1], c[2]) for c in self.mutations() if c[0] == 'store'],
            [('PUT', 'submissions/' + PENDING), ('POST', 'submissions/' + PENDING + '/commit')])
        self.assertEqual([c[1:] for c in self.mutations() if c[0] == 'upload'],
            [('opaque-upload-location', b'exact-qualified-package-pair')])
        state = writer._journal_state(self.issue['body'])
        self.assertEqual(state['submission_id'], PENDING)
        self.assertEqual(state['baseline_id'], PUBLISHED)
        self.assertEqual(state['source_sha'], SOURCE)
        self.assertEqual(self.pending['targetPublishMode'], 'Immediate')
        self.assertEqual(self.pending['pricing']['priceId'], 'Free')
        self.assertEqual(self.baseline['status'], 'Published')

    def test_acknowledged_adoption_metadata_fingerprint_is_persisted(self):
        self.upload_timeout = True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        state = writer._journal_state(self.issue['body'])
        self.assertEqual(state.get('adopted_latest_draft_semantic_sha256'),
            semantic(self.put_receipts[0]), 'A known metadata acknowledgment must bind retry content')

    def test_future_acknowledged_release_does_not_inherit_one_time_adoption_scope(self):
        self.perform()
        journal = {'number': '20', 'state': writer._journal_state(self.issue['body'])}
        later = copy.deepcopy(self.details); later['version'] = '1.1.4'
        try:
            writer._save(journal, 'create_attempted', later,
                baseline_id=PENDING, submission_id=None)
            advanced = True
        except writer.SubmissionBlocked: advanced = False
        self.assertTrue(advanced, 'An acknowledged later release must not inherit the one-time SID scope')
        state = writer._journal_state(self.issue['body'])
        self.assertEqual(state['tag'], 'v1.1.4')
        self.assertFalse(any(k.startswith('adopted_') or k.startswith('adoption_') for k in state))

    def test_retry_cannot_bypass_adopted_content_guard_by_disabling_flag(self):
        self.upload_timeout = True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.pending['notesForCertification'] += '\n다른 편집'
        self.upload_timeout = False
        self.calls.clear()
        writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.rejected()

    def test_default_off_preserves_unowned_draft(self):
        writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.rejected()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'], 'idle')

    def test_only_exact_actual_owner_and_dispatch_inputs_can_adopt(self):
        for key in ('actor', 'triggering_actor'):
            original = copy.deepcopy(self.run[key])
            self.run[key] = copy.deepcopy(self.bot)
            self.rejected(); self.run[key] = original
        self.event['sender']['id'] = 1
        self.write_event(); self.rejected()

    def test_event_flag_and_hash_must_match_the_explicit_environment(self):
        for flag in ('false', 1, None):
            self.event['inputs']['adopt_pending_submission'] = flag
            self.write_event(); self.rejected()
        self.event['inputs']['adopt_pending_submission'] = 'true'
        self.event['inputs']['adoption_draft_sha256'] = '0' * 64
        self.write_event(); self.rejected()

    def test_actual_event_duplicate_keys_are_rejected(self):
        self.event_path.write_text('{"inputs":{},"inputs":{}}')
        self.rejected()

    def test_empty_or_malformed_approval_hash_is_not_a_blanket_bypass(self):
        for value in ('', 'a' * 63, 'G' * 64):
            writer.os.environ['STORE_ADOPTION_DRAFT_SHA256'] = value
            self.rejected()

    def test_approved_source87_scope_is_exact(self):
        for key in ('sourceCommit', 'sourceRunId', 'sourceRunAttempt',
                    'sourceReleaseId', 'sourceAssetFingerprintSha256', 'version'):
            original = self.details[key]
            self.details[key] = 'foreign'
            self.rejected(); self.details[key] = original

    def test_source_package_qualification_failure_prevents_all_store_writes(self):
        with patch.object(writer, '_verify', side_effect=writer.SubmissionBlocked('unqualified')):
            self.rejected()

    def test_all_five_current_store_gates_still_must_succeed(self):
        for row in self.jobs:
            row['conclusion'] = 'failure'
            self.rejected(); row['conclusion'] = 'success'

    def test_different_application_or_pending_sid_is_preserved(self):
        self.app['publisherName'] = 'other publisher'
        self.rejected()
        self.app['publisherName'] = STORE_IDENTITY['publisher']
        for sid in ('12345', None, PUBLISHED):
            self.app['pendingApplicationSubmission'] = {'id': sid} if sid else None
            self.rejected()

    def test_different_published_baseline_is_preserved(self):
        self.app['lastPublishedApplicationSubmission'] = {'id': '12345'}
        self.baseline['id'] = '12345'
        self.rejected()

    def test_noneditable_statuses_are_never_adopted(self):
        for status in ('Published', 'PreProcessing', 'CommitStarted', 'CommitFailed', None, 'unknown'):
            self.pending['status'] = status
            self.rejected()

    def test_pending_must_also_be_free(self):
        self.pending['pricing']['priceId'] = 'Tier1'
        self.approved_hash = semantic(self.pending)
        self.event['inputs']['adoption_draft_sha256'] = self.approved_hash
        self.write_event(); writer.os.environ['STORE_ADOPTION_DRAFT_SHA256'] = self.approved_hash
        self.rejected()

    def test_pending_semantic_change_before_claim_stops_without_put(self):
        self.pending['notesForCertification'] += '변경'
        self.rejected()

    def test_changed_draft_after_journal_claim_stops_before_first_put(self):
        self.change_after_claim = lambda: self.pending.update(notesForCertification='다른 편집')
        self.rejected()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'], 'draft_ready')

    def test_changed_pending_reference_after_claim_never_creates_replacement(self):
        self.change_after_claim = lambda: self.app.update(pendingApplicationSubmission=None)
        self.rejected()

    def test_changed_published_baseline_after_claim_stops_before_put(self):
        self.change_after_claim = lambda: self.baseline.update(notesForCertification='다른 baseline')
        self.rejected()

    def test_uncertain_mutation_phases_are_not_reset_to_owned_draft(self):
        for phase in ('create_attempted', 'delete_attempted', 'commit_attempted'):
            state = {'app_id': STORE_APP_ID, 'phase': phase}
            if phase == 'commit_attempted': state['submission_id'] = PENDING
            self.issue['body'] = writer._journal_body(state)
            self.rejected()
            self.assertEqual(writer._journal_state(self.issue['body'])['phase'], phase)

    def test_other_owned_sid_cannot_be_reassigned(self):
        self.issue['body'] = writer._journal_body({'app_id': STORE_APP_ID,
            'phase': 'draft_ready', 'submission_id': '12345'})
        self.rejected()

    def test_journal_change_before_handoff_cannot_be_overwritten(self):
        self.journal_race = True
        self.rejected()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'], 'create_attempted')

    def test_foreign_job_or_workflow_cannot_enable_adoption(self):
        writer.os.environ['GITHUB_JOB'] = 'package'
        self.rejected()

    def test_forged_persisted_pair_cannot_resume_with_flag_false(self):
        self.upload_timeout = True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        state = writer._journal_state(self.issue['body'])
        state['store_msix_sha256_by_arch']['arm64'] = '0' * 64
        self.issue['body'] = writer._journal_body(state)
        self.calls.clear(); writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.rejected()

    def test_known_upload_timeout_resumes_only_same_owned_pair_and_content(self):
        self.upload_timeout = True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.upload_timeout = False; self.calls.clear()
        writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.assertEqual(self.perform()['submission_id'], PENDING)
        self.assertTrue(all(call[2].startswith('submissions/' + PENDING)
            for call in self.mutations() if call[0] == 'store'))

    def test_unacknowledged_put_never_guesses_new_fingerprint_or_repeats_write(self):
        self.put_timeout = True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        state = writer._journal_state(self.issue['body'])
        self.assertEqual(state['adopted_latest_draft_semantic_sha256'], self.approved_hash)
        self.calls.clear(); self.put_timeout = False
        writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.rejected()

    def test_missing_upload_destination_preserves_confirmed_sid_for_reconciliation(self):
        self.upload_destination = None
        with self.assertRaisesRegex(writer.SubmissionBlocked, 'no upload destination'):
            self.perform()
        self.assertEqual([(x[1], x[2]) for x in self.mutations() if x[0] == 'store'],
            [('PUT', 'submissions/' + PENDING)])
        self.assertFalse(any(x[0] == 'upload' for x in self.calls))
        state = writer._journal_state(self.issue['body'])
        self.assertTrue(state['adoption_upload_destination_missing'])
        self.assertEqual(state['submission_id'], PENDING)
        self.calls.clear(); writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.rejected()

    def test_wrong_put_acknowledgment_never_uploads_or_commits(self):
        self.put_ack_change = lambda result: result.update(id='12345')
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(self.put_count, 1)
        self.assertFalse(any(x[0] == 'upload' for x in self.calls))
        self.assertEqual(self.commit_count, 0)

    def test_unknown_commit_is_read_only_on_resume_and_never_recommitted(self):
        self.commit_timeout = True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'], 'commit_attempted')
        self.assertEqual(self.commit_count, 1)
        self.calls.clear(); writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        self.rejected()
        self.assertEqual(self.commit_count, 1)
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'], 'commit_attempted')

    def test_confirmed_processing_with_stale_pending_readback_never_rewrites(self):
        def stale_draft(opener, token, method, path, data=None):
            status, result = self.store(opener, token, method, path, data)
            if (method == 'GET' and path == 'submissions/' + PENDING
                    and self.commit_count):
                result['status'] = 'PendingCommit'
            return status, result
        with patch.object(writer, '_request', side_effect=stale_draft):
            with self.assertRaises(writer.SubmissionBlocked): self.perform()
            state = writer._journal_state(self.issue['body'])
            self.assertEqual((state['phase'], state['status']), ('submitted', 'PreProcessing'))
            self.assertEqual(self.put_count, 1)
            self.calls.clear(); writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
            self.rejected()
            self.assertEqual(self.put_count, 1)
            self.assertEqual(self.commit_count, 1)

    def test_confirmed_processing_can_record_known_failure_without_writes(self):
        self.perform()
        self.pending['status'] = 'CertificationFailed'
        self.calls.clear(); writer.os.environ['STORE_ADOPT_PENDING'] = 'false'
        with self.assertRaisesRegex(writer.SubmissionBlocked,
                'Store processing stopped in CertificationFailed'):
            self.perform()
        self.assertEqual(self.mutations(), [])
        state = writer._journal_state(self.issue['body'])
        self.assertEqual((state['phase'], state['status']), ('submitted', 'CertificationFailed'))
    def test_semantic_hash_uses_exact_observer_algorithm_and_mutable_content(self):
        self.assertEqual(writer.draft_semantic_sha256(self.pending), semantic(self.pending))
        other = copy.deepcopy(self.pending)
        for key in EXCLUDED: other[key] = 'server-only-change'
        self.assertEqual(writer.draft_semantic_sha256(other), self.approved_hash)
        for key, value in (('notesForCertification', '변경'), ('targetPublishMode', 'Immediate'),
                           ('futureMutableField', {'date': None, 'text': 'é'})):
            other = copy.deepcopy(self.pending); other[key] = value
            self.assertNotEqual(writer.draft_semantic_sha256(other), self.approved_hash)
        with self.assertRaises(writer.SubmissionBlocked):
            writer.draft_semantic_sha256({'invalid': float('nan')})

if __name__ == '__main__': unittest.main()
