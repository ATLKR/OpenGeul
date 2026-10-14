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
    def test_independent_mcp_receipt_survives_failed_gui_diagnostics_cap(self):
        producer=(Path(__file__).resolve().parents[2]/'e2e/mcp_worker.py').read_text()
        self.assertIn("args.out/'mcp-result.json'",producer)
        self.assertIn('mcp/mcp-result.json',self.p.PRIORITY_PATHS)
        receipt=json.dumps({'passed':False,'caseCount':6,'phase':'hwp_doc_save',
            'cases':[{'name':'case-'+str(i),'responseSha256':'a'*64,'checks':{'passed':True}}
                     for i in range(6)]}).encode()
        self.put('mcp/mcp-result.json',receipt)
        self.put('a_failed/events.json',b'x'*1500)
        self.put('a_failed/screen.png',b'x'*1500)
        (self.src/'results.json').write_text('{"tests":[{"test":"suite.a_failed","status":"failed"}]}')
        report=self.p.pack(self.src,self.dest,'failure',limit=4096)
        self.assertEqual((self.dest/'mcp/mcp-result.json').read_bytes(),receipt)
        self.assertEqual(report['status'],'failure')
    def test_partial_valid16_receipt_survives_failure_cap_without_overriding_gui(self):
        receipt=json.dumps({'passed':False,'cases':[{'id':'hwp-read','status':'failed','responseSha256':'a'*64} for _ in range(8)]}).encode()
        self.put('structured-cli-mcp/structured-result.json',receipt)
        self.put('a_failed/events.json',b'x'*1500)
        self.put('a_failed/screen.png',b'x'*1500)
        original=b'{"tests":[{"test":"suite.a_failed","status":"failed"}]}'
        (self.src/'results.json').write_bytes(original)
        report=self.p.pack(self.src,self.dest,'failure',limit=4096)
        self.assertTrue((self.dest/'structured-cli-mcp/structured-result.json').is_file(),'The actual partial valid16 receipt must survive the cap')
        self.assertEqual((self.dest/'structured-cli-mcp/structured-result.json').read_bytes(),receipt)
        self.assertEqual((self.dest/'results.json').read_bytes(),original)
        self.assertEqual(report['status'],'failure')
        self.assertNotIn('structured-cli-mcp/structured-result.json',self.p.OUTCOME_PATHS)
    def test_failed_structured_pdf_survives_gui_cap_without_rewriting_original_receipts(self):
        receipt=b'{"passed":false,"cases":[{"id":"hwp-render","status":"failed"},{"id":"hwpx-render","status":"failed"}]}'
        original=b'{"tests":[{"test":"suite.a_failed","status":"failed"}]}'
        pdf=b'%PDF-1.7\n'+b'owned synthetic PDF bytes\n'*55+b'%%EOF\n'
        self.put('structured-cli-mcp/structured-result.json',receipt)
        self.put('structured-cli-mcp/artifacts/hwp-render/3.pdf',pdf)
        self.put('structured-cli-mcp/artifacts/hwpx-render/3.pdf',pdf)
        self.put('a_failed/events.json',b'x'*1800)
        self.put('a_failed/screen.png',b'x'*1800)
        for name in ('input.hwp','input.hwpx','font.ttf','key.pem'):
            self.put('structured-cli-mcp/artifacts/hwp-render/'+name,b'owned excluded input')
        (self.src/'results.json').write_bytes(original)
        report=self.p.pack(self.src,self.dest,'failure',limit=8192)
        for case in ('hwp-render','hwpx-render'):
            self.assertTrue((self.dest/'structured-cli-mcp/artifacts'/case/'3.pdf').is_file(),
                            'The failed public PDF was starved by bulky GUI diagnostics')
            self.assertEqual((self.dest/'structured-cli-mcp/artifacts'/case/'3.pdf').read_bytes(),pdf,
                             'The failed public PDF bytes must precede bulky GUI diagnostics')
        self.assertEqual((self.dest/'structured-cli-mcp/structured-result.json').read_bytes(),receipt)
        self.assertEqual((self.dest/'results.json').read_bytes(),original)
        self.assertEqual(report['status'],'failure')
        copied=[row['path'] for row in report['copied']]
        self.assertLess(copied.index('structured-cli-mcp/structured-result.json'),copied.index('structured-cli-mcp/artifacts/hwp-render/3.pdf'))
        self.assertFalse((self.dest/'a_failed/events.json').exists())
        self.assertFalse((self.dest/'a_failed/screen.png').exists())
        self.assertNotIn('structured-cli-mcp/structured-result.json',self.p.OUTCOME_PATHS)
        for name in ('input.hwp','input.hwpx','font.ttf','key.pem'):
            self.assertFalse((self.dest/'structured-cli-mcp/artifacts/hwp-render'/name).exists())
    def test_structured_pdf_priority_does_not_change_success_visual_exclusion(self):
        self.put('structured-cli-mcp/structured-result.json',b'{"passed":false,"cases":[{"id":"hwp-render","status":"failed"}]}')
        self.put('structured-cli-mcp/artifacts/hwp-render/3.pdf',b'%PDF-1.7\nowned\n%%EOF\n')
        report=self.p.pack(self.src,self.dest,'success')
        self.assertEqual(report['status'],'success')
        self.assertFalse((self.dest/'structured-cli-mcp/artifacts/hwp-render/3.pdf').exists())
        self.assertTrue((self.dest/'structured-cli-mcp/structured-result.json').is_file())
    def test_unrelated_or_nonfailed_structured_case_does_not_promote_pdf(self):
        for case,status in (('hwp-read','failed'),('hwp-render','passed'),('unknown-render','failed')):
            with self.subTest(case=case,status=status):
                receipt=json.dumps({'cases':[{'id':case,'status':status}]}).encode()
                self.put('structured-cli-mcp/structured-result.json',receipt)
                self.put('structured-cli-mcp/artifacts/'+case+'/3.pdf',b'%PDF-1.7\n'+b'x'*1500+b'\n%%EOF\n')
                self.put('a_failed/events.json',b'x'*1800)
                self.put('a_failed/screen.png',b'x'*1800)
                (self.src/'results.json').write_text('{"tests":[{"test":"suite.a_failed","status":"failed"}]}')
                target=self.root/('bounded-'+case+'-'+status)
                report=self.p.pack(self.src,target,'failure',limit=8192)
                self.assertFalse((target/'structured-cli-mcp/artifacts'/case/'3.pdf').exists())
                self.assertEqual(report['status'],'failure')
    def test_structured_receipt_priority_reader_is_bounded_and_nonoutcome(self):
        for label,receipt in (
                ('oversize',b'{"cases":[{"id":"hwp-render","status":"failed"}],"padding":"'+b'x'*(2*1024*1024)+b'"}'),
                ('malformed',b'not JSON'),
                ('wrong-type',b'{"cases":"hwp-render"}')):
            with self.subTest(label=label):
                self.put('structured-cli-mcp/structured-result.json',receipt)
                self.put('structured-cli-mcp/artifacts/hwp-render/3.pdf',b'%PDF-1.7\n'+b'x'*1500+b'\n%%EOF\n')
                self.put('a_failed/events.json',b'x'*1800)
                self.put('a_failed/screen.png',b'x'*1800)
                original=b'{"tests":[{"test":"suite.a_failed","status":"failed"}]}'
                (self.src/'results.json').write_bytes(original)
                target=self.root/('bounded-'+label)
                report=self.p.pack(self.src,target,'failure',limit=8192)
                self.assertFalse((target/'structured-cli-mcp/artifacts/hwp-render/3.pdf').exists())
                self.assertEqual((target/'results.json').read_bytes(),original)
                self.assertEqual(report['status'],'failure')
    def test_failed_case_evidence_has_priority_over_successful_case(self):
        (self.src/'results.json').write_text('{"tests":[{"test":"suite.z_failed","status":"failed"}]}')
        self.put('a_success/large.png',b'a'*1500);self.put('z_failed/screen.png',b'b'*1500)
        self.p.pack(self.src,self.dest,'failure',limit=4096)
        self.assertTrue((self.dest/'z_failed/screen.png').exists())
    def test_password_outcomes_and_provenance_survive_success_cap(self):
        names=('results.json','junit.xml','identity.json','fixture-manifest.json','fixture-verification.json')
        for name in names:
            data=json.dumps({'tests':[],'padding':'x'*(16*1024)}).encode() if name.endswith('.json') else b'<testsuite>'+b' '*(16*1024)+b'</testsuite>'
            self.put('password-native/'+name,data)
        self.put('password-native/a_success/events.json',b'a'*(900*1024))
        self.p.pack(self.src,self.dest,'success')
        for name in names:self.assertTrue((self.dest/'password-native'/name).is_file(),name)
    def test_nested_password_failure_is_prioritized_within_its_suite(self):
        self.put('password-native/results.json',b'{"tests":[{"test":"suite.z_failed","status":"failed"}]}')
        self.put('password-native/a_success/screen.png',b'a'*1500)
        self.put('password-native/z_failed/screen.png',b'b'*1500)
        self.p.pack(self.src,self.dest,'failure',limit=4096)
        self.assertTrue((self.dest/'password-native/z_failed/screen.png').exists())
        self.assertFalse((self.dest/'password-native/a_success/screen.png').exists())
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
