"""External transports exercise the actual recovery/write state machine."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_store_adoption as fixtures
semantic = fixtures.semantic
PENDING, PUBLISHED = fixtures.PENDING, fixtures.PUBLISHED
import store_submit as writer

OLD_RUN = '38307171848'
OLD_HEAD = '82369eef2d3e89f66255da6514554acbd33032dc'
OLD_PAIR = {'x64': '76cbf587c649aea14f83bbbd717a85f505c3586781a7927400a4949ddeb379f5',
    'arm64': '31a2dfb8e3b42f2e41b10f7ef542f4accb353e6d9c639c5638c02d4d808f2299'}
SOURCE_PAIR = {'x64': '2901fbc514dbc868083c8bb50b8a0eedd4bbc0c9cf703a96062de8da9f8d3655',
    'arm64': 'fd5af011629f4026a3c276d932d9453c38f1ac6d9d590163b03be81030ed2ace'}
NEW_ID = '1152921505702100999'

class StoreRecoveryTests(unittest.TestCase):
    write_event = fixtures.StoreAdoptionTests.write_event
    verified = fixtures.StoreAdoptionTests.verified
    upload = fixtures.StoreAdoptionTests.upload
    perform = fixtures.StoreAdoptionTests.perform
    mutations = fixtures.StoreAdoptionTests.mutations
    rejected = fixtures.StoreAdoptionTests.rejected

    def setUp(self):
        fixtures.StoreAdoptionTests.setUp(self)
        self.baseline['packageDeliveryOptions'] = {'isMandatoryUpdate': False}
        self.pending['packageDeliveryOptions'] = {'isMandatoryUpdate': False}
        self.approved_hash = semantic(self.pending)
        for arch, sha in SOURCE_PAIR.items(): self.details['architectures'][arch]['sourceMsixSha256'] = sha
        state = {'app_id': writer.STORE_APP_ID, 'phase': 'draft_ready', 'tag': 'v1.1.3',
            'source_sha': self.details['sourceCommit'], 'release_id': str(self.details['sourceReleaseId']),
            'run_id': self.details['sourceRunId'], 'submission_id': PENDING, 'baseline_id': PUBLISHED,
            'source_asset_fingerprint_sha256': self.details['sourceAssetFingerprintSha256'],
            'source_msix_sha256_by_arch': copy.deepcopy(SOURCE_PAIR),
            'store_msix_sha256_by_arch': copy.deepcopy(OLD_PAIR), 'adopted_pending_id': PENDING,
            'adopted_draft_semantic_sha256': self.approved_hash,
            'adopted_latest_draft_semantic_sha256': self.approved_hash,
            'adopted_baseline_semantic_sha256': semantic(self.baseline)}
        self.issue['body'] = writer._journal_body(state)
        self.event['inputs'] = {'adopt_pending_submission': 'false',
            'recover_pending_submission': 'true', 'adoption_draft_sha256': self.approved_hash}
        self.write_event()
        writer.os.environ.update(STORE_ADOPT_PENDING='false', STORE_RECOVER_PENDING='true',
            STORE_ADOPTION_DRAFT_SHA256=self.approved_hash)
        self.prior_run = dict(copy.deepcopy(self.run), id=int(OLD_RUN), run_number=52,
            head_sha=OLD_HEAD, status='completed', conclusion='failure')
        self.prior_jobs = [dict(copy.deepcopy(job), run_id=int(OLD_RUN), run_attempt=1,
            head_sha=OLD_HEAD, id=100+i) for i, job in enumerate(self.jobs)]
        self.prior_jobs.append({'id':115007617322, 'name':'submit', 'run_id':int(OLD_RUN),
            'run_attempt':1, 'head_sha':OLD_HEAD, 'status':'completed', 'conclusion':'failure'})
        self.log_bytes = b'2026-10-12T21:06:29.7273485Z ##[error]Store PUT failed with HTTP 409\n'
        for active in (patch.object(writer, 'RECOVERY_DRAFT_SHA256', self.approved_hash, create=True),
            patch.object(writer, 'RECOVERY_FAILURE_LOG_SHA256', hashlib.sha256(self.log_bytes).hexdigest(), create=True),
            patch.object(writer.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,self.log_bytes,b''))):
            active.start(); self.addCleanup(active.stop)
        self.delete_mode = self.create_mode = None
        self.after_delete_hook = None
        self.before_delete_hook = None

    def github(self, method, path, data=None, *, pages=False):
        if path == 'actions/runs/' + OLD_RUN: return copy.deepcopy(self.prior_run)
        if path.startswith('actions/runs/' + OLD_RUN + '/jobs'):
            return [{'jobs':copy.deepcopy(self.prior_jobs)}]
        return fixtures.StoreAdoptionTests.github(self, method, path, data, pages=pages)

    def store(self, opener, token, method, path, data=None):
        if method == 'DELETE':
            self.calls.append(('store',method,path))
            self.assertEqual(path,'submissions/'+PENDING)
            if self.delete_mode == 'timeout': raise writer.StoreError('DELETE',None)
            if self.delete_mode == 'conflict': raise writer.StoreError('DELETE',409)
            if self.delete_mode == 'body': return 200,b'not-empty'
            self.app['pendingApplicationSubmission'] = None
            if self.after_delete_hook: self.after_delete_hook()
            return 204,b''
        if method == 'POST' and path == 'submissions':
            self.calls.append(('store',method,path))
            if self.create_mode == 'timeout': raise writer.StoreError('POST',None)
            sid = PUBLISHED if self.create_mode == 'published' else PENDING if self.create_mode == 'old' else NEW_ID
            self.pending = dict(copy.deepcopy(self.baseline),id=sid,status='PendingCommit')
            self.app['pendingApplicationSubmission']={'id':sid}
            return 201,copy.deepcopy(self.pending)
        if method=='GET' and path=='submissions/'+PENDING and self.app['pendingApplicationSubmission'] is None:
            self.calls.append(('store',method,path))
            if self.delete_mode=='readable': return 200,copy.deepcopy(self.pending)
            if self.delete_mode=='read403': raise writer.StoreError('GET',403)
            raise writer.StoreError('GET',404)
        if self.pending['id'] != PENDING and path.startswith('submissions/'+self.pending['id']):
            result=fixtures.StoreAdoptionTests.store(self,opener,token,method,path.replace(self.pending['id'],PENDING,1),data)
            self.calls[-1]=('store',method,path)
            return result
        return fixtures.StoreAdoptionTests.store(self,opener,token,method,path,data)

    def test_exact_failed_clone_is_deleted_once_then_new_current_pair_submitted(self):
        with patch.object(writer.subprocess,'run',return_value=subprocess.CompletedProcess([],0,self.log_bytes,b'')) as loader:
            try: result=self.perform()
            except writer.SubmissionBlocked: result=None
        self.assertEqual(loader.call_args.args[0],['gh','api','--allow-escape-sequences','--method','GET',
            'repos/ATLKR/OpenGeul/actions/jobs/115007617322/logs'])
        self.assertIs(loader.call_args.kwargs['capture_output'],True)
        self.assertIs(loader.call_args.kwargs['check'],True)
        self.assertEqual(loader.call_args.kwargs['timeout'],120)
        self.assertIsNotNone(result, 'Fresh five-gate qualification must recover the exact known 409 clone')
        self.assertEqual(result['submission_id'],NEW_ID)
        writes=[(c[1],c[2])for c in self.mutations()if c[0]=='store']
        self.assertEqual(writes,[('DELETE','submissions/'+PENDING),('POST','submissions'),
            ('PUT','submissions/'+NEW_ID),('POST','submissions/'+NEW_ID+'/commit')])
        state=writer._journal_state(self.issue['body'])
        self.assertNotIn('adopted_pending_id',state)
        self.assertEqual(state['recovered_clone']['submission_id'],PENDING)
        self.assertEqual(state['recovered_clone']['store_msix_sha256_by_arch'],OLD_PAIR)
        self.assertEqual(state['store_msix_sha256_by_arch'],writer._pair_identity(self.details)['store_msix_sha256_by_arch'])
        self.assertEqual(self.baseline['status'],'Published')

    def test_default_off_keeps_existing_different_pair_guard(self):
        writer.os.environ['STORE_RECOVER_PENDING']='false'; self.rejected()

    def test_unknown_delete_is_durable_and_retry_writes_nothing(self):
        self.delete_mode='timeout'
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'],'delete_attempted')
        self.calls.clear()
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(),[])

    def test_same_sid_or_published_create_ack_is_never_updated(self):
        for mode in ('old','published'):
            with self.subTest(mode=mode):
                self.setUp(); self.create_mode=mode
                with self.assertRaises(writer.SubmissionBlocked): self.perform()
                self.assertEqual(writer._journal_state(self.issue['body'])['phase'],'create_attempted')
                self.assertFalse(any(c[0]=='store' and c[1]=='PUT' for c in self.calls))

    def test_mandatory_or_unknown_type_and_changed_semantic_block_before_delete(self):
        for value in (True,None,'false',0):
            with self.subTest(value=value):
                self.setUp(); self.pending['packageDeliveryOptions']['isMandatoryUpdate']=value
                self.rejected()

    def test_processing_published_or_conflicting_journal_are_preserved(self):
        for status in ('Published','PreProcessing','CommitStarted','None'):
            with self.subTest(status=status):
                self.setUp(); self.pending['status']=status; self.rejected()

    def test_prior52_failure_and_five_gates_are_required(self):
        for altered in ('run','submit','gate','log'):
            with self.subTest(altered=altered):
                self.setUp()
                if altered=='run': self.prior_run['conclusion']='success'
                elif altered=='submit': self.prior_jobs[-1]['id']=1
                elif altered=='gate': self.prior_jobs[0]['conclusion']='failure'
                else: self.log_bytes=b'not the proven 409'
                with patch.object(writer.subprocess,'run',return_value=subprocess.CompletedProcess([],0,self.log_bytes,b'')):
                    self.rejected()

    def test_delete_ack_then_refs_and_exact404_are_required(self):
        for mode in ('body','conflict','readable','read403'):
            with self.subTest(mode=mode):
                self.setUp(); self.delete_mode=mode
                with self.assertRaises(writer.SubmissionBlocked): self.perform()
                self.assertFalse(any(c[0]=='store' and c[1]=='POST' for c in self.calls))
                self.assertEqual(writer._journal_state(self.issue['body'])['phase'],'delete_attempted')

    def test_new_baseline_or_pending_after_delete_blocks_post(self):
        self.after_delete_hook=lambda:self.app.update(pendingApplicationSubmission={'id':'12345'})
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertFalse(any(c[0]=='store' and c[1]=='POST' for c in self.calls))

    def test_unknown_create_does_not_repeat_delete_or_post(self):
        self.create_mode='timeout'
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'],'create_attempted')
        self.calls.clear()
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(),[])

    def test_missing_new_upload_destination_preserves_new_sid(self):
        self.upload_destination=None
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertFalse(any(c[0]=='upload' or c[0]=='store'and'/commit'in c[2] for c in self.calls))
        self.assertEqual(writer._journal_state(self.issue['body'])['submission_id'],NEW_ID)

    def test_recovery_input_and_actual_dispatch_owner_are_required(self):
        for mutation in ('flag','owner','hash','dual','dual-event','foreign'):
            with self.subTest(mutation=mutation):
                self.setUp()
                if mutation=='flag': self.event['inputs']['recover_pending_submission']='false'
                if mutation=='owner': self.run['triggering_actor']['id']=1
                if mutation=='hash': self.event['inputs']['adoption_draft_sha256']='0'*64
                if mutation=='dual': writer.os.environ['STORE_ADOPT_PENDING']='true'
                if mutation=='dual-event': self.event['inputs']['adopt_pending_submission']='true'
                if mutation=='foreign': self.event['repository']['full_name']='other/OpenGeul'
                self.write_event(); self.rejected()

    def test_mutation_during_delete_intent_cas_blocks_delete(self):
        original = self.github
        def github(method,path,data=None,*,pages=False):
            answer=original(method,path,data,pages=pages)
            if method=='PATCH' and path=='issues/20' and writer._journal_state(answer['body'])['phase']=='delete_attempted':
                self.pending['notesForCertification'] += '\nconcurrent edit'
            return answer
        with patch.object(writer,'_gh',side_effect=github): self.rejected()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'],'delete_attempted')

    def test_changed_or_unknown_baseline_mandatory_value_blocks_delete(self):
        self.baseline['packageDeliveryOptions']['isMandatoryUpdate']=None
        self.rejected()

    def test_confirmed_recovery_does_not_delete_new_draft_on_commit_retry(self):
        self.commit_timeout=True
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(writer._journal_state(self.issue['body'])['phase'],'commit_attempted')
        self.calls.clear(); self.commit_timeout=False
        with self.assertRaises(writer.SubmissionBlocked): self.perform()
        self.assertEqual(self.mutations(),[])

    def test_invalid_listing_plan_is_rejected_before_deletion(self):
        with patch.object(writer,'apply_korean_listing',side_effect=ValueError('invalid locale plan')):
            self.rejected()

    def test_invalid_published_architecture_template_is_rejected_before_deletion(self):
        with patch.object(writer,'_published_architectures',side_effect=writer.SubmissionBlocked('unknown architecture')):
            self.rejected()


    def test_existing_clone_with_new_upload_destination_is_preserved(self):
        self.pending['fileUploadUrl']='opaque-new-upload-location'
        self.rejected()


class RecoveryErrorDiagnosticsTests(unittest.TestCase):
    def test_http409_only_reports_bounded_hash_and_known_reason_enum(self):
        body=json.dumps({'code':'UnsupportedFeature','message':'secret-secret https://private.blob.core.windows.net/?sig=private'}).encode()
        class Opener:
            def open(self,*args,**kwargs): raise urllib.error.HTTPError('private',409,'private',{},io.BytesIO(body))
        with self.assertRaises(writer.StoreError) as caught:
            writer._request(Opener(),'token-secret','DELETE','submissions/'+PENDING)
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(getattr(caught.exception,'response_sha256',None),hashlib.sha256(body).hexdigest())
        self.assertEqual(getattr(caught.exception,'reason_code',None),'UnsupportedFeature')
        self.assertNotIn('secret',str(caught.exception)); self.assertNotIn('https',str(caught.exception))

    def test_unknown_error_code_is_never_echoed_and_large_body_is_marked_partial(self):
        body=b'{"code":"token-secret"}'+b' '*100000
        class Opener:
            def open(self,*args,**kwargs): raise urllib.error.HTTPError('private',409,'private',{},io.BytesIO(body))
        with self.assertRaises(writer.StoreError) as caught:
            writer._request(Opener(),'token-secret','DELETE','submissions/'+PENDING)
        self.assertIsNone(getattr(caught.exception,'reason_code','missing'))
        self.assertIs(getattr(caught.exception,'response_truncated',None),True)
        self.assertNotIn('token-secret',str(caught.exception))


if __name__=='__main__': unittest.main()
