"""Atomic exact-source preparation and closed provenance for renderer candidates."""
from pathlib import Path
import copy,hashlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import renderer_font_candidates as subject
class RendererFontCandidatesTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.source=Path(self.temp.name);self.before={};self.after={}
  for name in subject.SOURCE_FILES:
   parts=[]
   for old,new in subject.REPLACEMENTS.get(name,()):parts.append(old)
   value=('\n'.join(parts)if parts else'// isolated readonly contract\n').encode();self.before[name]=value;after=value
   for old,new in subject.REPLACEMENTS.get(name,()):after=after.replace(old.encode(),new.encode())
   self.after[name]=after;p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
  self.inputs={n:hashlib.sha256(b).hexdigest()for n,b in self.before.items()};self.outputs={n:hashlib.sha256(b).hexdigest()for n,b in self.after.items()}
  for name,value in [('INPUT_SOURCE_SHA256',self.inputs),('OUTPUT_SOURCE_SHA256',self.outputs)]:
   p=patch.object(subject,name,value);p.start();self.addCleanup(p.stop)
 def test_apply_binds_all_readonly_dependencies_and_exact_output(self):
  proof=subject.apply(self.source);subject.validate_contract(proof,self.outputs,{subject.HELPER:subject.sha(ROOT/subject.HELPER)})
  for n,value in self.after.items():self.assertEqual((self.source/n).read_bytes(),value)
 def test_late_readonly_drift_never_partially_patches_adapters(self):
  readonly=subject.SOURCE_FILES[-1];(self.source/readonly).write_bytes(b'drift')
  with self.assertRaises(ValueError):subject.apply(self.source)
  for n in subject.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
 def test_missing_readonly_dependency_never_patches(self):
  (self.source/subject.SOURCE_FILES[-1]).unlink()
  with self.assertRaises(ValueError):subject.apply(self.source)
  for n in subject.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
 def test_duplicate_anchor_is_not_authorized_by_rehashed_input(self):
  n=next(iter(subject.REPLACEMENTS));old=subject.REPLACEMENTS[n][0][0].encode();p=self.source/n;raw=self.before[n]+old;p.write_bytes(raw)
  with patch.dict(subject.INPUT_SOURCE_SHA256,{n:hashlib.sha256(raw).hexdigest()}),self.assertRaises(ValueError):subject.apply(self.source)
  self.assertEqual(p.read_bytes(),raw)
 def test_symlink_is_rejected_before_adapter_writes(self):
  p=self.source/subject.SOURCE_FILES[-1];p.unlink();target=self.source/'retained';target.write_bytes(b'held');p.symlink_to(target)
  with self.assertRaises(ValueError):subject.apply(self.source)
  for n in subject.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
 def test_reapplication_never_refreshes_source_ownership(self):
  subject.apply(self.source)
  with self.assertRaises(ValueError):subject.apply(self.source)
 def test_coherently_rehashed_old_or_missing_proof_fails(self):
  proof=subject.apply(self.source)
  for bad in [None,{},dict(proof,extra=True),dict(proof,afterSha256=self.inputs)]:
   with self.subTest(kind=type(bad).__name__),self.assertRaises(ValueError):subject.validate_contract(bad,self.outputs,{subject.HELPER:subject.sha(ROOT/subject.HELPER)})
 def test_helper_and_every_prepared_dependency_are_required(self):
  proof=subject.apply(self.source)
  with self.assertRaises(ValueError):subject.validate_contract(proof,self.outputs,{})
  for n in subject.SOURCE_FILES:
   bad=dict(self.outputs);bad[n]='0'*64
   with self.subTest(source=n),self.assertRaises(ValueError):subject.validate_contract(proof,bad,{subject.HELPER:subject.sha(ROOT/subject.HELPER)})
 def test_prepare_and_consumer_require_the_same_public_proof(self):
  prepare=(ROOT/'scripts/prepare_upstream.py').read_text();consumer=(ROOT/'scripts/windows_components.py').read_text()
  self.assertIn('renderer_font_candidates_proof = apply_renderer_font_candidates(source)',prepare)
  self.assertIn("'rendererFontCandidates':renderer_font_candidates_proof",prepare)
  self.assertIn('set(renderer_font_candidates.SOURCE_FILES)',consumer)
  self.assertGreaterEqual(consumer.count('renderer_font_candidates.validate_contract'),2)
