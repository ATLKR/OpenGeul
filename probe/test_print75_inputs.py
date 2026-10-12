"""Transport boundary controls; these tests never contact GitHub or run products."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('print75_inputs',Path(__file__).with_name('print75_inputs.py'))
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)

class Response(io.BytesIO):
    status=200

class TransportControls(unittest.TestCase):
    def test_exact_download_authenticates_only_official_api_and_rehashes_redirect_bytes(self):
        data=b'original synthetic zip';spec=(1,'fixed',len(data),hashlib.sha256(data).hexdigest(),64)
        seen=[]
        class Opener:
            def open(self,request,timeout):
                seen.append(request)
                if len(seen)==1:raise urllib.error.HTTPError(request.full_url,302,'redirect',
                    {'Location':'https://owned.blob.core.windows.net/container/archive?temporary=unprinted'},None)
                return Response(data)
        with tempfile.TemporaryDirectory() as temp,patch.dict(M.os.environ,{'GH_TOKEN':'synthetic-test-value'}),\
                patch.object(M.urllib.request,'build_opener',return_value=Opener()):
            path=Path(temp)/'original.zip';M.download(spec,path);self.assertEqual(path.read_bytes(),data)
        self.assertEqual(seen[0].get_header('Authorization'),'Bearer synthetic-test-value')
        self.assertIsNone(seen[1].get_header('Authorization'))

    def test_unapproved_redirect_has_no_second_request(self):
        calls=[]
        class Opener:
            def open(self,request,timeout):
                calls.append(request)
                raise urllib.error.HTTPError(request.full_url,302,'redirect',{'Location':'https://untrusted.invalid/x'},None)
        with tempfile.TemporaryDirectory() as temp,patch.dict(M.os.environ,{'GH_TOKEN':'synthetic-test-value'}),\
                patch.object(M.urllib.request,'build_opener',return_value=Opener()):
            with self.assertRaises(ValueError):M.download((1,'fixed',1,'0'*64,1),Path(temp)/'original.zip')
        self.assertEqual(len(calls),1)

    def test_size_or_digest_mismatch_never_passes(self):
        class Opener:
            def open(self,request,timeout):return Response(b'wrong')
        with tempfile.TemporaryDirectory() as temp,patch.dict(M.os.environ,{'GH_TOKEN':'synthetic-test-value'}),\
                patch.object(M.urllib.request,'build_opener',return_value=Opener()):
            with self.assertRaises(ValueError):M.download((1,'fixed',5,'0'*64,5),Path(temp)/'original.zip')

    def test_duplicate_json_metadata_is_rejected(self):
        with self.assertRaises(ValueError):M.json.loads('{"id":1,"id":2}',object_pairs_hook=M.unique)

if __name__=='__main__':unittest.main()
