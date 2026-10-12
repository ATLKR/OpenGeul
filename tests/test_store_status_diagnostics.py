"""Bounded external responses verify GET-only and diagnostic redaction."""
import copy, io, json, os
from pathlib import Path
import sys, unittest, urllib.error, urllib.request
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import store_status_diagnostics as d
class Response(io.BytesIO):
    status=200
class Opener:
    def __init__(self,values): self.values=values;self.calls=[]
    def open(self,request,timeout):
        self.calls.append((request.get_method(),request.full_url,timeout,request.data))
        value=self.values[len(self.calls)-1]
        if isinstance(value,Exception):raise value
        return Response(value if isinstance(value,bytes)else json.dumps(value).encode())
class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.app={'id':'9PJH0T3PHRMF','packageIdentityName':'57904TaewonLiodLim.OpenGeul',
          'pendingApplicationSubmission':{'id':d.PENDING},'lastPublishedApplicationSubmission':{'id':d.PUBLISHED}}
        self.pending={'id':d.PENDING,'status':'PendingCommit','statusDetails':{'errors':[{'code':'InvalidParameter','details':'The submission parameter is invalid.'}],'warnings':[]},'listings':{'private':'DO_NOT_EMIT'}}
        self.published={'id':d.PUBLISHED,'status':'Published','statusDetails':None}
        self.status={'status':'PendingCommit','statusDetails':{'errors':[],'warnings':[{'code':'Warning','message':'Metadata warning.'}]}}
    def values(self):return [copy.deepcopy(v)for v in(self.app,self.pending,self.published,self.status)]
    def test_exact_four_gets_and_only_status_diagnostic_projection(self):
        o=Opener(self.values());r=d.observe(o,'OAUTH_SECRET')
        self.assertEqual([x[:2]for x in o.calls],[('GET',d.BASE),('GET',d.BASE+'/submissions/'+d.PENDING),('GET',d.BASE+'/submissions/'+d.PUBLISHED),('GET',d.BASE+'/submissions/'+d.PENDING+'/status')])
        self.assertTrue(all(x[3]is None for x in o.calls));self.assertEqual(r['pending']['details']['errors'][0]['code'],'InvalidParameter')
        self.assertEqual(r['pendingStatus']['details']['warnings'][0]['message'],'Metadata warning.')
        self.assertNotIn('DO_NOT_EMIT',json.dumps(r));self.assertIs(r['storeMutationsAttempted'],False)
    def test_urls_auth_known_secrets_encoded_forms_and_controls_are_redacted(self):
        import base64
        secret='CLIENT_PRIVATE_SECRET';message='\x1b[31mFailure https://storage.example/path?sig=SAS_PRIVATE Bearer OAUTH_SECRET client_secret='+secret+' '+base64.b64encode(secret.encode()).decode()+' \x00'
        self.pending['statusDetails']['errors'][0]['details']=message
        r=d.observe(Opener(self.values()),'OAUTH_SECRET',[secret]);s=json.dumps(r)
        for value in(secret,'OAUTH_SECRET','SAS_PRIVATE','https://','\u001b','\u0000',base64.b64encode(secret.encode()).decode()):self.assertNotIn(value,s)
    def test_foreign_refs_or_detail_ids_stop_before_later_gets(self):
        for field in('app','pending','published'):
            with self.subTest(field=field):
                values=self.values()
                if field=='app':values[0]['pendingApplicationSubmission']['id']='123'
                else:values[1 if field=='pending'else 2]['id']='123'
                o=Opener(values)
                with self.assertRaises(ValueError):d.observe(o,'OAUTH_SECRET')
                self.assertLess(len(o.calls),4)
    def test_duplicate_json_nonfinite_and_response_size_are_rejected(self):
        for raw in(b'{"id":"one","id":"two"}',b'{"value":NaN}',b' '* (1024*1024+1)):
            with self.subTest(rawBytes=len(raw)):
                o=Opener([raw])
                with self.assertRaises(ValueError):d.observe(o,'OAUTH_SECRET')
                self.assertEqual(len(o.calls),1)
    def test_http_error_only_records_safe_projected_message_and_response_hash(self):
        body=json.dumps({'error':{'code':'InvalidParameter','message':'Invalid parameter https://private/?sig=SAS_PRIVATE Bearer OAUTH_SECRET'}}).encode()
        o=Opener(self.values()[:3]+[urllib.error.HTTPError('https://private',400,'private',{},io.BytesIO(body))])
        with self.assertRaises(d.GetFailure)as caught:d.observe(o,'OAUTH_SECRET')
        diagnostic=caught.exception.diagnostic;self.assertEqual(diagnostic['httpStatus'],400)
        self.assertNotIn('OAUTH_SECRET',json.dumps(diagnostic));self.assertNotIn('https://',json.dumps(diagnostic));self.assertNotIn('SAS_PRIVATE',json.dumps(diagnostic))
    def test_message_and_items_are_bounded_with_omission_metadata(self):
        self.status['statusDetails']['warnings']=[{'code':'LongWarning','message':'가'*3000}for _ in range(40)]
        r=d.observe(Opener(self.values()),'OAUTH_SECRET');q=r['pendingStatus']['details']['warnings'];self.assertEqual(len(q),16)
        self.assertTrue(all(len(x['message'].encode())<=1024 and x['messageTruncated']for x in q));self.assertEqual(r['pendingStatus']['details']['warningsOmitted'],24)
    def test_no_redirect_authentication_transport_blocks_other_destinations(self):
        from check_store_api import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'Found',{},'https://other/?sig=SAS_PRIVATE'))
    def test_unknown_raw_error_fields_and_code_tokens_are_not_emitted(self):
        self.pending['statusDetails']['errors']=[{'code':'OAUTH_SECRET','message':'safe detail','raw':'DO_NOT_EMIT','fileUploadUrl':'https://private/?sig=SAS_PRIVATE'}]
        r=d.observe(Opener(self.values()),'OAUTH_SECRET');self.assertIsNone(r['pending']['details']['errors'][0]['code'])
        self.assertNotIn('DO_NOT_EMIT',json.dumps(r));self.assertNotIn('SAS_PRIVATE',json.dumps(r))
if __name__=='__main__':unittest.main()
