"""Store 네트워크 대신 고정 응답을 넣어 GET 경계와 정보 노출을 검증한다."""
from pathlib import Path
import importlib.util, io, json, os, sys, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e')]
legacy = os.environ.get('LEGACY_PENDING_OBSERVER')
if legacy:
    spec = importlib.util.spec_from_file_location('pending_observer', legacy)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
else:
    import store_pending_observe as helper

APP = {'id': '9PJH0T3PHRMF', 'packageIdentityName': '57904TaewonLiodLim.OpenGeul',
       'pendingApplicationSubmission': {'id': '246'}, 'lastPublishedApplicationSubmission': {'id': '123'}}
def submission(sid, status):
    return {'id': sid, 'status': status, 'targetPublishMode': 'Immediate',
            'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'KR': 'Base'}},
            'listings': {'ko-kr': {'baseListing': {'description': '한국어 설명 SECRET_TEXT'}}},
            'applicationPackages': [{'version': '1.1.3.0', 'architecture': 'Arm64', 'fileStatus': 'Uploaded'}],
            'fileUploadUrl': 'https://blob.example/path?sig=SECRET_SAS'}

class Opener:
    def __init__(self, values): self.values = values; self.calls = []
    def open(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url, timeout))
        value = self.values[len(self.calls) - 1]
        return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())

class PendingObserveTests(unittest.TestCase):
    def observe(self, opener, *args):
        try: return helper.observe(opener, 'SECRET_OAUTH', *args)
        except (ValueError, TypeError) as error: self.fail('필요한 현재 pending/baseline GET 동작이 없음: '+type(error).__name__)

    def test_reads_actual_pending_and_published_ids_with_get_only(self):
        opener = Opener([APP, submission('246', 'PendingCommit'), submission('123', 'Published')])
        result = self.observe(opener)
        self.assertEqual(opener.calls, [('GET', helper.BASE, 30), ('GET', helper.BASE+'/submissions/246', 30), ('GET', helper.BASE+'/submissions/123', 30)])
        self.assertEqual(result.get('pendingSubmission', {}).get('id'), '246')
        self.assertEqual(result.get('publishedSubmission', {}).get('id'), '123')
        self.assertFalse(result.get('automationJournalOwnershipAsserted', True))

    def test_response_output_contains_no_secret_url_or_listing_raw(self):
        opener = Opener([APP, submission('246', 'PendingCommit'), submission('123', 'Published')])
        result = self.observe(opener)
        encoded = json.dumps(result)
        for text in ('SECRET_', 'https://', 'fileUploadUrl', '한국어 설명'):
            self.assertNotIn(text, encoded)
        self.assertEqual(result.get('pendingSubmission', {}).get('packages'), [{'version':'1.1.3.0','architecture':'arm64','fileStatus':'Uploaded'}])
        self.assertTrue(result.get('pendingSubmission', {}).get('freeBasePrice'))

    def test_listing_change_changes_fingerprint_without_exposing_text(self):
        first = submission('246', 'PendingCommit'); second = submission('246', 'PendingCommit')
        second['listings']['ko-kr']['baseListing']['description'] = '다른 설명 SECRET_SECOND'
        results = [self.observe(Opener([APP, value, submission('123', 'Published')])) for value in (first, second)]
        self.assertNotEqual(results[0].get('pendingSubmission', {}).get('draftContentSha256'), results[1].get('pendingSubmission', {}).get('draftContentSha256'))

    def test_mandatory_flag_reports_only_actual_boolean_and_preserves_missing(self):
        for value in (None, False, True):
            pending=submission('246','PendingCommit')
            if value is not None: pending['packageDeliveryOptions']={'isMandatoryUpdate':value,'unrelated':'SECRET_DELIVERY'}
            result=self.observe(Opener([APP,pending,submission('123','Published')]))
            self.assertIs(result['pendingSubmission']['mandatoryUpdate'],value)
            self.assertNotIn('SECRET_DELIVERY',json.dumps(result))
        for value in ('false',0,1,[],{}):
            pending=submission('246','PendingCommit');pending['packageDeliveryOptions']={'isMandatoryUpdate':value}
            opener=Opener([APP,pending])
            with self.assertRaises(ValueError): helper.observe(opener,'SECRET_OAUTH')
            self.assertEqual(len(opener.calls),2)

    def test_sensitive_upload_url_is_excluded_from_fingerprint(self):
        first = submission('246', 'PendingCommit'); second = submission('246', 'PendingCommit')
        second['fileUploadUrl'] = 'https://other.example/?sig=SECRET_CHANGED'
        results = [self.observe(Opener([APP, value, submission('123', 'Published')])) for value in (first, second)]
        self.assertEqual(results[0].get('pendingSubmission', {}).get('draftContentSha256'), results[1].get('pendingSubmission', {}).get('draftContentSha256'))

    def test_semantic_hash_ignores_only_five_top_level_fields(self):
        original=submission('246','PendingCommit')
        changed={**original,'id':'999','status':'Certification','statusDetails':{'message':'SECRET_STATUS'},
                 'friendlyName':'SECRET_FRIENDLY','fileUploadUrl':'https://other.example/?sig=SECRET_SAS'}
        self.assertEqual(helper.draft_semantic_fingerprint(original),helper.draft_semantic_fingerprint(changed))
        for key,value in [('targetPublishMode','Manual'),('targetPublishDate','2026-10-15T00:00:00Z'),
                          ('notesForCertification','한국어 검토 안내 https://example.net/notes')]:
            with self.subTest(key=key):
                self.assertNotEqual(helper.draft_semantic_fingerprint(original),helper.draft_semantic_fingerprint({**original,key:value}))

    def test_no_redirect_auth_opener_blocks_external_destination(self):
        from transport_cleanup import NoRedirect
        import urllib.error, urllib.request
        import http.server, threading
        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302); self.send_header('Location','https://other.example/?sig=SECRET_SAS'); self.end_headers()
            def log_message(self,*args): pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port),headers={'Authorization':'Bearer SECRET_OAUTH'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.build_opener(NoRedirect()).open(request,timeout=2)
            self.assertEqual(error.exception.code,302)
        finally: server.shutdown();server.server_close();thread.join(timeout=2)

    def test_pending_upload_fields_are_observed_as_null_but_uploaded_requires_both(self):
        pending=submission('246','PendingCommit')
        pending['applicationPackages']=[{'fileStatus':'PendingUpload'}]
        result=self.observe(Opener([APP,pending,submission('123','Published')]))
        self.assertEqual(result['pendingSubmission']['packages'],[{'version':None,'architecture':None,'fileStatus':'PendingUpload'}])
        pending['applicationPackages']=[{'fileStatus':'Uploaded'}]
        opener=Opener([APP,pending])
        with self.assertRaises(ValueError): helper.observe(opener,'SECRET_OAUTH')
        self.assertEqual(len(opener.calls),2)

    def test_wrong_app_stops_before_submission_get(self):
        opener = Opener([{**APP, 'id': 'OTHER'}])
        with self.assertRaises(ValueError): helper.observe(opener, 'SECRET_OAUTH')
        self.assertEqual(len(opener.calls), 1)

    def test_wrong_pending_detail_or_expected_id_stops_before_baseline_get(self):
        opener = Opener([APP, submission('999', 'PendingCommit')])
        with self.assertRaises(ValueError): helper.observe(opener, 'SECRET_OAUTH')
        self.assertEqual(len(opener.calls), 2)
        opener = Opener([APP])
        with self.assertRaises(ValueError): helper.observe(opener, 'SECRET_OAUTH', '999')
        self.assertEqual(len(opener.calls), 1)

    def test_no_pending_and_duplicate_or_oversize_json(self):
        opener = Opener([{**APP, 'pendingApplicationSubmission': None}, submission('123', 'Published')])
        result = self.observe(opener)
        self.assertIsNone(result.get('pendingSubmission'))
        self.assertEqual(len(opener.calls), 2)
        for value in (b'{"id":"a","id":"b"}', b' ' * (1024*1024+1)):
            with self.subTest(bytes=len(value)):
                with self.assertRaises(ValueError): helper.observe(Opener([value]), 'SECRET_OAUTH')

if __name__ == '__main__': unittest.main()
