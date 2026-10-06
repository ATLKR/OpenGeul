import importlib.util
import json
from pathlib import Path
import sys,tempfile,unittest
class EvidenceTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'evidence.py'
        self.assertTrue(path.exists(),'Missing bounded CI evidence packer')
        spec=importlib.util.spec_from_file_location('ci_evidence',path)
        self.p=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.p)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'raw';self.src.mkdir();self.dest=self.root/'bounded'
        (self.src/'results.json').write_text('{"success":false,"tests":[]}')
    def put(self,name,data):
        p=self.src/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    def test_success_keeps_summaries_not_large_images(self):
        self.put('case/page.png',b'png'*10000)
        self.p.pack(self.src,self.dest,'success')
        self.assertTrue((self.dest/'results.json').exists());self.assertFalse((self.dest/'case/page.png').exists())
    def test_failure_keeps_bounded_visual_evidence(self):
        self.put('case/page.png',b'png'*1000)
        self.p.pack(self.src,self.dest,'failure');self.assertTrue((self.dest/'case/page.png').exists())
    def test_oversize_recorded_not_silently_uploaded(self):
        self.put('huge.png',b'x'*2000)
        result=self.p.pack(self.src,self.dest,'failure',limit=1024)
        self.assertTrue(any(x['path']=='huge.png' for x in result['omitted']))
        self.assertFalse((self.dest/'huge.png').exists())
    def test_fonts_keys_and_source_documents_never_copied(self):
        for name in ('a.ttf','b.woff2','key.pfx','original.hwpx','secret.pem'):
            self.put(name,b'data')
        self.p.pack(self.src,self.dest,'failure')
        for name in ('a.ttf','b.woff2','key.pfx','original.hwpx','secret.pem'):self.assertFalse((self.dest/name).exists())
    def test_disguised_font_is_rejected(self):
        self.put('font.txt',b'wOFF'+b'0'*100)
        with self.assertRaises(ValueError):self.p.pack(self.src,self.dest,'failure')
    def test_links_are_not_followed(self):
        target=self.root/'outside';target.write_text('private')
        (self.src/'link.txt').symlink_to(target)
        with self.assertRaises(ValueError):self.p.pack(self.src,self.dest,'failure')
    def test_existing_output_not_overwritten(self):
        self.dest.mkdir();(self.dest/'keep').write_text('mine')
        with self.assertRaises(ValueError):self.p.pack(self.src,self.dest,'failure')
        self.assertEqual((self.dest/'keep').read_text(),'mine')
    def test_no_raw_evidence_still_has_an_honest_report(self):
        self.p.pack(self.root/'missing',self.dest,'failure')
        report=json.loads((self.dest/'evidence-index.json').read_text())
        self.assertEqual(report['copied'],[]);self.assertEqual(report['status'],'failure')
    def test_failure_result_is_preserved_not_rewritten(self):
        data=(self.src/'results.json').read_bytes();self.p.pack(self.src,self.dest,'failure')
        self.assertEqual((self.dest/'results.json').read_bytes(),data)
    def test_failed_case_evidence_has_priority_over_successful_case(self):
        (self.src/'results.json').write_text('{"tests":[{"test":"suite.z_failed","status":"failed"}]}')
        self.put('a_success/large.png',b'a'*1500);self.put('z_failed/screen.png',b'b'*1500)
        self.p.pack(self.src,self.dest,'failure',limit=4096)
        self.assertTrue((self.dest/'z_failed/screen.png').exists())
    def test_success_and_failure_limits(self):
        self.assertEqual(self.p.LIMITS['success'],1024*1024)
        self.assertEqual(self.p.LIMITS['failure'],12*1024*1024)
    def test_missing_transport_input_is_not_zero_bytes(self):
        with self.assertRaises(ValueError):self.p.measure([self.root/'absent'],limit=1000)
    def test_build_size_guard_refuses_oversize_before_upload(self):
        self.put('a.bin',b'abc')
        with self.assertRaises(ValueError):self.p.measure([self.src],limit=2)
        self.assertEqual(self.p.measure([self.src],limit=100), (self.src/'results.json').stat().st_size+3)

if __name__=='__main__':unittest.main()
