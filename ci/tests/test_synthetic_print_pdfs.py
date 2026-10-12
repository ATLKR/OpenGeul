"""Synthetic-only transport must reject unsafe, mismatched or incomplete originals."""
import hashlib,importlib.util,json,os,struct
from pathlib import Path
import tempfile,types,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
CASES=('table--300','table-0','table-600','multipage','basic-hwp','basic-hwpx','page-range','cancel')
FIXTURE={'table--300':'print-fixtures/print-table--300.hwpx','table-0':'print-fixtures/print-table-0.hwpx','table-600':'print-fixtures/print-table-600.hwpx','multipage':'print-fixtures/print-multipage.hwpx','page-range':'print-fixtures/print-multipage.hwpx','basic-hwp':'inputs/e2e-fixtures/basic.hwp','basic-hwpx':'inputs/e2e-fixtures/basic.hwpx','cancel':'inputs/e2e-fixtures/basic.hwpx'}
def digest(raw):return hashlib.sha256(raw).hexdigest()
class SyntheticPrintPdfTests(unittest.TestCase):
 def setUp(self):
  path=ROOT/'ci/synthetic_print_pdfs.py';self.assertTrue(path.exists(),'Missing closed-path synthetic PDF collector')
  spec=importlib.util.spec_from_file_location('synthetic_print_pdfs',path);self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.dest=self.root/'synthetic-pdf-evidence'
  self.env={'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'42','GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/main','GITHUB_JOB':'virtual-print','GITHUB_WORKSPACE':str(self.root),'GITHUB_EVENT_PATH':str(self.root/'event.json')}
  self.gui=bytearray(512);self.gui[:2]=b'MZ';struct.pack_into('<I',self.gui,60,128);self.gui[128:132]=b'PE\0\0';struct.pack_into('<H',self.gui,132,0x8664);self.put('runtime/OpenGeul.exe',self.gui);self.gui_hash=digest(self.gui)
  import wasm_artifacts
  expected=wasm_artifacts.expected();wasm={name:(b'\0asm\1\0\0\0' if name=='rhwp_bg.wasm' else b'synthetic '+name.encode()) for name in wasm_artifacts.FILES}
  wasm['package.json']=json.dumps({'version':expected['upstream']['rhwp']['version']}).encode()
  for name,data in wasm.items():self.put('wasm-input/'+name,data)
  self.metadata('wasm-input/OPEN_GEUL_WASM.json',{**expected,'artifacts':{name:digest(data) for name,data in wasm.items()},'generator':'wasm-pack 0.14.0 --target web --release --no-opt'})
  self.put('event.json',json.dumps({'repository':{'private':False,'full_name':'ATLKR/OpenGeul'}}).encode());self.metadata('print-evidence/summary.json',{'tests':8,'failures':0,'skipped':0,'results':[{'name':c,'passed':True} for c in CASES]})
  self.put('print-evidence/junit.xml',('<testsuite name="virtual-print" tests="8" failures="0" skipped="0">'+''.join('<testcase name="'+c+'" />' for c in CASES)+'</testsuite>').encode())
  for case in CASES:
   fixture=('synthetic '+FIXTURE[case]).encode();self.put(FIXTURE[case],fixture);h=digest(fixture);base='print-evidence/'+case+'/';self.put(base+Path(FIXTURE[case]).name,fixture)
   runtime={'mode':'native','fixtureSha256':h,'nativeArchitecture':{'sourceCommit':'a'*40,'sourceRun':'42','runAttempt':'1','architecture':'x64','processMachine':0,'nativeMachine':0x8664,'peMachine':0x8664,'native':True,'sha256':self.gui_hash,'bytes':len(self.gui),'processId':123,'runningAtInspection':True,'imagePath':str(self.root/'runtime/OpenGeul.exe'),'helperSha256':digest((ROOT/'e2e/native_architecture.py').read_bytes())},'executableSha256':self.gui_hash}
   self.metadata(base+'session/runtime.json',runtime);self.metadata(base+'source-preservation.json',{'before':h,'after':h,'unchanged':True})
   if case=='cancel':self.metadata(base+'result.json',{'cancelled':True,'jobs':[],'sourceSha256':h});continue
   pdf=b'%PDF-1.7\n'+case.encode()+b'\n%%EOF\n';self.put(base+'printed.pdf',pdf);n=2 if case=='multipage' else 1
   inspection={'sha256':digest(pdf),'mode':'reviewed-raster-fingerprint','checks':[{'page':i+1} for i in range(n)]};self.metadata(base+'pdf-check/inspection.json',inspection);self.metadata(base+'result.json',{**inspection,'sourceSha256':h})
 def put(self,name,data):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
 def metadata(self,name,value):return self.put(name,(json.dumps(value)+'\n').encode())
 def change(self,name,key,value):
  p=self.root/name;data=json.loads(p.read_bytes());data[key]=value;self.metadata(name,data)
 def collect(self):return self.m.collect(self.root,self.env,'windows-2022')
 def rejected(self):
  with self.assertRaises((ValueError,FileNotFoundError)):self.collect()
  self.assertFalse(self.dest.exists(),'rejected data must never become upload-ready')
 def test_preserves_exact_seven_original_pdfs_and_one_bounded_manifest(self):
  manifest=self.collect();files=sorted(p.relative_to(self.dest).as_posix() for p in self.dest.rglob('*') if p.is_file())
  self.assertEqual(files,sorted([c+'/printed.pdf' for c in CASES if c!='cancel']+['manifest.json']))
  self.assertEqual(manifest['printedPages'],8);self.assertEqual(manifest['pdfCount'],7);self.assertFalse(manifest['sourceQualified']);self.assertFalse(manifest['storeCertified'])
  for row in manifest['pdfs']:
   original=(self.root/'print-evidence'/row['path']).read_bytes();copied=(self.dest/row['path']).read_bytes();self.assertEqual(copied,original);self.assertEqual(row['sha256'],digest(original));self.assertEqual(row['bytes'],len(original))
  self.assertLessEqual(sum(p.stat().st_size for p in self.dest.rglob('*') if p.is_file()),8*1024*1024)
 def test_missing_expected_pdf_never_becomes_success(self):
  (self.root/'print-evidence/table-0/printed.pdf').unlink();self.rejected()
 def test_pdf_bytes_changed_after_original_inspection_are_rejected(self):
  self.put('print-evidence/table-0/printed.pdf',b'%PDF-1.7\nchanged\n%%EOF\n');self.rejected()
 def test_cancel_pdf_is_rejected(self):
  self.put('print-evidence/cancel/printed.pdf',b'%PDF-1.7\n%%EOF\n');self.rejected()
 def test_old_head_runtime_is_rejected(self):
  name='print-evidence/table-0/session/runtime.json';p=self.root/name;d=json.loads(p.read_bytes());d['nativeArchitecture']['sourceCommit']='c'*40;self.metadata(name,d);self.rejected()
 def test_old_run_or_attempt_runtime_is_rejected(self):
  for key,value in [('sourceRun','41'),('runAttempt','2')]:
   with self.subTest(key=key):
    name='print-evidence/table-0/session/runtime.json';p=self.root/name;d=json.loads(p.read_bytes());original=d['nativeArchitecture'][key];d['nativeArchitecture'][key]=value;self.metadata(name,d);self.rejected();d['nativeArchitecture'][key]=original;self.metadata(name,d)
 def test_actual_gui_payload_must_match_recorded_runtime(self):
  changed=bytearray(self.gui);changed[-1]=1;self.put('runtime/OpenGeul.exe',changed);self.rejected()
 def test_dead_or_boolean_pid_native_proof_is_rejected(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['processId']=True;self.metadata(name,d);self.rejected()
 def test_runtime_image_path_must_be_the_actual_fixed_product(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['imagePath']=str(self.root/'another/OpenGeul.exe');self.metadata(name,d);self.rejected()
 def test_runtime_image_bytes_must_match_actual_product_size(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['bytes']+=1;self.metadata(name,d);self.rejected()
 def test_case_source_copy_must_still_equal_original_generated_input(self):
  self.put('print-evidence/table-0/print-table-0.hwpx',b'changed case original');self.rejected()
 def test_wasm_actual_bytes_must_match_current_source_provenance(self):
  self.put('wasm-input/rhwp.js',b'changed engine');self.rejected()
 def test_wasm_upstream_pin_must_match_checked_out_source(self):
  name='wasm-input/OPEN_GEUL_WASM.json';d=json.loads((self.root/name).read_bytes());d['namespaceHelper']='c'*64;self.metadata(name,d);self.rejected()
 def test_generated_fixture_bytes_must_match_preservation_and_runtime(self):
  self.put(FIXTURE['table-0'],b'changed user document');self.rejected()
 def test_source_preservation_must_confirm_unchanged(self):
  self.change('print-evidence/table-0/source-preservation.json','unchanged',False);self.rejected()
 def test_unknown_or_duplicated_suite_case_is_rejected(self):
  d=json.loads((self.root/'print-evidence/summary.json').read_bytes());d['results'][0]['name']='arbitrary-user-doc';self.metadata('print-evidence/summary.json',d);self.rejected()
 def test_failed_or_skipped_suite_is_rejected(self):
  self.change('print-evidence/summary.json','failures',1);self.rejected()
 def test_symlink_pdf_is_rejected(self):
  p=self.root/'print-evidence/table-0/printed.pdf';data=p.read_bytes();p.unlink();outside=self.put('private.pdf',data);p.symlink_to(outside);self.rejected()
 def test_symlink_case_ancestor_is_rejected(self):
  p=self.root/'print-evidence/table-0';outside=self.root/'private-case';p.rename(outside);p.symlink_to(outside,target_is_directory=True);self.rejected()
 def test_windows_reparse_pdf_is_rejected_before_copy(self):
  target=self.root/'print-evidence/table-0/printed.pdf';original=Path.lstat
  def lstat(path,*args,**kwargs):
   info=original(path,*args,**kwargs)
   if path==target:return types.SimpleNamespace(st_mode=info.st_mode,st_file_attributes=0x400)
   return info
  with patch.object(Path,'lstat',lstat):self.rejected()
 def test_total_original_pdf_bytes_are_bounded_before_upload(self):
  for case in ('table--300','table-0','table-600'):
   name='print-evidence/'+case+'/';raw=b'%PDF-1.7\n'+b'x'*(3*1024*1024)+b'\n%%EOF\n';self.put(name+'printed.pdf',raw)
   for rel in ('result.json','pdf-check/inspection.json'):self.change(name+rel,'sha256',digest(raw))
  self.rejected()
 def test_private_or_other_repository_event_is_rejected(self):
  self.metadata('event.json',{'repository':{'private':True,'full_name':'ATLKR/OpenGeul'}});self.rejected()
 def test_fork_repository_context_is_rejected(self):
  self.env['GITHUB_REPOSITORY']='someone/OpenGeul';self.rejected()
 def test_different_editor_bytes_between_cases_are_rejected(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['sha256']='c'*64;d['executableSha256']='c'*64;self.metadata(name,d);self.rejected()
 def test_old_native_helper_hash_is_rejected(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['helperSha256']='c'*64;self.metadata(name,d);self.rejected()
 def test_boolean_native_machine_is_not_integer_zero(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['processMachine']=False;self.metadata(name,d);self.rejected()
 def test_arm64_transport_binds_arm_job_os_and_native_proofs(self):
  self.env['GITHUB_JOB']='virtual-print-arm64';struct.pack_into('<H',self.gui,132,0xaa64);self.put('runtime/OpenGeul.exe',self.gui);self.gui_hash=digest(self.gui)
  for case in CASES:
   name='print-evidence/'+case+'/session/runtime.json';d=json.loads((self.root/name).read_bytes());n=d['nativeArchitecture'];n['architecture']='arm64';n['nativeMachine']=n['peMachine']=0xaa64;n['sha256']=d['executableSha256']=self.gui_hash;self.metadata(name,d)
  manifest=self.m.collect(self.root,self.env,'windows-11-arm');self.assertEqual((manifest['architecture'],manifest['job'],manifest['os']),('arm64','virtual-print-arm64','windows-11-arm'));self.assertEqual(manifest['pdfCount'],7)
 def test_wrong_native_architecture_is_rejected(self):
  name='print-evidence/table-0/session/runtime.json';d=json.loads((self.root/name).read_bytes());d['nativeArchitecture']['processMachine']=0x8664;self.metadata(name,d);self.rejected()
 def test_unrelated_pdf_documents_fonts_keys_and_png_are_never_collected(self):
  for name in ('unrelated/private.pdf','user.hwpx','secret.pfx','font.ttf','screen.png'):self.put('print-evidence/'+name,b'private')
  self.collect();self.assertEqual(len([p for p in self.dest.rglob('*') if p.is_file()]),8)
 def test_existing_destination_is_not_overwritten(self):
  self.dest.mkdir();(self.dest/'mine').write_text('keep');self.rejected_existing()
 def rejected_existing(self):
  with self.assertRaises(ValueError):self.collect()
  self.assertEqual((self.dest/'mine').read_text(),'keep')
if __name__=='__main__':unittest.main()

class SyntheticPrintPdfWorkflowTests(unittest.TestCase):
 def test_existing_three_print_jobs_have_strict_separate_pdf_uploads(self):
  import sys
  sys.path.insert(0,str(ROOT/'ci'));from policy import load_workflow
  workflow=load_workflow(ROOT/'.github/workflows/msix.yml')
  for job,os_label in [('virtual-print','${{ matrix.os }}'),('virtual-print-arm64','windows-11-arm')]:
   with self.subTest(job=job):
    steps=workflow['jobs'][job]['steps'];collect=[(i,s) for i,s in enumerate(steps) if s.get('id')=='synthetic-pdfs'];upload=[(i,s) for i,s in enumerate(steps) if s.get('id')=='synthetic-pdfs-evidence']
    self.assertEqual(len(collect),1);self.assertEqual(len(upload),1);ci,c=collect[0];ui,u=upload[0]
    actual=next(i for i,s in enumerate(steps) if 'e2e/virtual_print.py ' in s.get('run',''))
    self.assertLess(actual,ci);self.assertLess(ci,ui)
    self.assertEqual(c['run'],'python ci/synthetic_print_pdfs.py --os '+os_label)
    self.assertEqual(c['if'],"success() && github.repository == 'ATLKR/OpenGeul' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')")
    self.assertEqual(u['if'],"always() && steps.synthetic-pdfs.outcome == 'success'")
    self.assertEqual(u['with'],{'name':'opengeul-synthetic-print-pdfs-'+os_label+'-${{ github.run_id }}-${{ github.run_attempt }}','path':'synthetic-pdf-evidence/','retention-days':'1','if-no-files-found':'error','compression-level':'9'})
    self.assertNotIn('continue-on-error',c);self.assertNotIn('continue-on-error',u)
