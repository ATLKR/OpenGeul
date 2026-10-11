"""실제 Request/HTTPError 객체를 쓰되 네트워크 대신 고정 응답 스트림을 주입한다."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import archive_next as subject
from test_archive_next import Evidence


class Response(io.BytesIO):
    def __init__(self, raw, status=200): super().__init__(raw);self.status=status;self.limits=[]
    def read(self, size=-1): self.limits.append(size);return super().read(size)


class Opener:
    def __init__(self, *responses): self.responses=list(responses);self.calls=[]
    def open(self, request, timeout):
        self.calls.append((request,timeout))
        value=self.responses.pop(0)
        if isinstance(value,Exception): raise value
        return value


class TransportBoundaryControls(unittest.TestCase):
    def setUp(self): self.e=Evidence();self.addCleanup(self.e.temp.cleanup)
    def make(self,*responses):
        opener=Opener(*responses)
        return subject.Transport('offline-fake-token',self.e.c,opener),opener
    def redirect(self,url='https://results.blob.core.windows.net/artifact.zip?sig=offline-fake-signature',code=302):
        return HTTPError('https://api.github.com/fixed',code,'offline',{'Location':url},None)
    def context(self):
        return {'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'ATLKR/OpenGeul',
            'GITHUB_ACTOR':'ATLKR','GITHUB_TRIGGERING_ACTOR':'ATLKR','GITHUB_EVENT_NAME':'workflow_dispatch',
            'GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'999999','GITHUB_REF':'refs/heads/diagnostic/archive-next-conditional',
            'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/archive-next-conditional',
            'GH_TOKEN':'offline-fake-token','GITHUB_TOKEN':'offline-fake-token'}

    def test_unknown_pins_refuse_even_network_adapter_construction(self):
        c=json.loads((Path(__file__).parent/'archive-next-unset-fixture.json').read_text());opener=Opener()
        with self.assertRaises(ValueError): subject.Transport('offline-fake-token',c,opener)
        self.assertEqual(opener.calls,[])

    def test_main_still_refuses_unset_pins_if_authorization_is_accidentally_enabled(self):
        pending=Path(__file__).parent/'archive-next-unset-fixture.json'
        raw=pending.read_bytes();opener=Opener()
        with patch.object(subject,'ROOT_EXECUTION_AUTHORIZED',True), \
                patch.object(subject,'CONTRACT',pending), \
                patch.object(subject,'CONTRACT_SHA256',subject.digest(raw)), \
                patch.object(subject.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(ValueError): subject.main()
        self.assertEqual(opener.calls,[])

    def test_context_requires_public_manual_ref_actor_attempt_and_token_match(self):
        env=self.context();event={'repository':{'full_name':'ATLKR/OpenGeul','private':False},'inputs':{}}
        subject.context(env,event)
        for key,value in [('GITHUB_REF','refs/heads/main'),('GITHUB_ACTOR','other'),('GITHUB_RUN_ATTEMPT','2'),
                ('GITHUB_EVENT_NAME','push'),('GITHUB_WORKFLOW_REF','other'),('GH_TOKEN','different')]:
            with self.subTest(key=key):
                bad=dict(env);bad[key]=value
                with self.assertRaises(ValueError): subject.context(bad,event)
        for bad in [{'repository':{'full_name':'ATLKR/OpenGeul','private':True}},
                    dict(event,inputs={'submit_to_store':True})]:
            with self.assertRaises(ValueError): subject.context(env,bad)

    def test_fixed_metadata_get_uses_official_host_auth_and_timeout(self):
        response=Response(b'{"id":101}');transport,opener=self.make(response)
        self.assertEqual(transport('GET','repos/ATLKR/OpenGeul/actions/runs/101'),{'id':101})
        request,timeout=opener.calls[0]
        self.assertEqual(request.full_url,'https://api.github.com/repos/ATLKR/OpenGeul/actions/runs/101')
        self.assertEqual(request.get_method(),'GET')
        self.assertEqual(request.get_header('Authorization'),'Bearer offline-fake-token')
        self.assertEqual(timeout,60);self.assertEqual(response.limits,[2*1024*1024+1])

    def test_other_routes_methods_pages_hosts_and_source_asset_writes_refuse(self):
        transport,opener=self.make()
        for method,path,data in [('DELETE','repos/ATLKR/OpenGeul/releases/202',None),
                ('PATCH','repos/ATLKR/OpenGeul/releases/202',b'{}'),
                ('GET','repos/ATLKR/OpenGeul/actions/runs/999',None),
                ('GET','repos/ATLKR/OpenGeul/releases/201/assets?per_page=100&page=11',None),
                ('GET','repos/ATLKR/OpenGeul/releases/201/assets?per_page=100&page=01',None),
                ('GET','https://api.github.com.evil.invalid/repos/ATLKR/OpenGeul/releases/201',None),
                ('POST','https://uploads.github.com/repos/ATLKR/OpenGeul/releases/201/assets?name=AppxManifest.xml',b'original manifest')]:
            with self.subTest(path=path):
                with self.assertRaises(ValueError): transport(method,path,data)
        self.assertEqual(opener.calls,[])

    def test_upload_accepts_only_exact_missing_original_route_and_bytes(self):
        path='https://uploads.github.com/repos/ATLKR/OpenGeul/releases/202/assets?name=AppxManifest.xml'
        transport,opener=self.make(Response(b'{"id":1000}',201))
        self.assertEqual(transport('POST',path,self.e.files['AppxManifest.xml']),{'id':1000})
        request,_=opener.calls[0];self.assertEqual(request.data,b'original manifest');self.assertEqual(request.get_method(),'POST')
        for bad in [b'changed manifest',None]:
            with self.assertRaises(ValueError): transport('POST',path,bad)
        self.assertEqual(len(opener.calls),1)

    def test_only_fixed_archive_tag_404_is_nullable(self):
        tag='repos/ATLKR/OpenGeul/git/ref/tags/'+self.e.c['archiveTag']
        transport,opener=self.make(HTTPError('https://api.github.com/fixed',404,'offline',{},None))
        self.assertIsNone(transport('GET',tag))
        transport,_=self.make(HTTPError('https://api.github.com/fixed',404,'offline',{},None))
        with self.assertRaises(RuntimeError): transport('GET','repos/ATLKR/OpenGeul/releases/202')

    def test_json_cap_duplicate_keys_wrong_status_and_error_text_are_redacted(self):
        for response in [Response(b'x'*(2*1024*1024+1)),Response(b'{"id":1,"id":2}'),
                         Response(b'{}',201),RuntimeError('offline-fake-token ?sig=offline-fake-signature')]:
            with self.subTest(response=type(response).__name__):
                transport,opener=self.make(response)
                with self.assertRaises(RuntimeError) as caught: transport('GET','repos/ATLKR/OpenGeul/releases/202')
                self.assertNotIn('offline-fake-token',str(caught.exception));self.assertNotIn('sig=',str(caught.exception))
                self.assertEqual(len(opener.calls),1)

    def test_artifact_redirect_drops_auth_and_bounds_hash_verified_original_zip(self):
        response=Response(self.e.raw);transport,opener=self.make(self.redirect(),response)
        self.assertEqual(transport.download({'id':301}),self.e.raw)
        first,second=[request for request,_ in opener.calls]
        self.assertEqual(first.full_url,'https://api.github.com/repos/ATLKR/OpenGeul/actions/artifacts/301/zip')
        self.assertEqual(first.get_header('Authorization'),'Bearer offline-fake-token')
        self.assertIsNone(second.get_header('Authorization'))
        self.assertIsNone(second.get_header('Cookie'))
        self.assertEqual(response.limits,[len(self.e.raw)+1])
        self.assertTrue(all(timeout==60 for _,timeout in opener.calls))

    def test_untrusted_redirect_and_second_redirect_never_forward_token(self):
        urls=['http://results.blob.core.windows.net/a','https://evil.invalid/a',
            'https://blob.core.windows.net.evil.invalid/a','https://user@results.blob.core.windows.net/a',
            'https://results.blob.core.windows.net:444/a','https://results.blob.core.windows.net/a#fragment']
        for url in urls:
            transport,opener=self.make(self.redirect(url))
            with self.assertRaises(RuntimeError): transport.download({'id':301})
            self.assertEqual(len(opener.calls),1)
        transport,opener=self.make(self.redirect(),self.redirect('https://evil.invalid/a'))
        with self.assertRaises(RuntimeError): transport.download({'id':301})
        self.assertEqual(len(opener.calls),2);self.assertIsNone(opener.calls[1][0].get_header('Authorization'))

    def test_wrong_artifact_id_and_zip_size_hash_or_status_refuse_without_retry(self):
        transport,opener=self.make()
        with self.assertRaises(ValueError): transport.download({'id':999})
        self.assertEqual(opener.calls,[])
        for response in [Response(self.e.raw+b'extra'),Response(self.e.raw[:-1]),
                         Response(b'x'*len(self.e.raw)),Response(self.e.raw,201)]:
            transport,opener=self.make(self.redirect(),response)
            with self.assertRaises(RuntimeError) as caught: transport.download({'id':301})
            self.assertNotIn('sig=',str(caught.exception));self.assertEqual(len(opener.calls),2)

    def test_redirect_handler_does_not_follow_any_location(self):
        handler=subject.NoRedirect()
        self.assertIsNone(handler.redirect_request(None,None,302,'offline',{},'https://evil.invalid'))


if __name__=='__main__': unittest.main()
