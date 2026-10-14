"""Fail-closed preparation policy for independent HWPX expected persistence."""
from pathlib import Path
import copy,hashlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import hwpx_persistence_verification as policy
class PersistencePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.source=Path(self.temp.name)
        self.before={};self.after={}
        for name in policy.SOURCE_FILES:
            if name in policy.REPLACEMENTS:
                parts=[];generated=[]
                for old,new in policy.REPLACEMENTS[name]:
                    if not any(old in prior for prior in generated):parts.append(old)
                    generated.append(new)
                value='\n'.join(parts).encode()
            elif name.endswith('/section.rs'):value=policy.OWNER_POLICY.encode()+b'\n'
            else:value=b'// owned isolated dependency\n'
            self.before[name]=value;after=value
            for old,new in policy.REPLACEMENTS.get(name,()):after=after.replace(old.encode(),new.encode())
            self.after[name]=after;path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        self.before_map={n:hashlib.sha256(v).hexdigest() for n,v in self.before.items()};self.after_map={n:hashlib.sha256(v).hexdigest() for n,v in self.after.items()}
        for name,value in [('INPUT_SOURCE_SHA256',self.before_map),('OUTPUT_SOURCE_SHA256',self.after_map)]:
            c=patch.object(policy,name,value);c.start();self.addCleanup(c.stop)
        self.helpers={policy.HELPER:policy.sha(ROOT/policy.HELPER)}
    def test_exact_product_source_dependencies_and_proof(self):
        result=policy.apply(self.source);self.assertEqual(result,{'beforeSha256':self.before_map,'afterSha256':self.after_map,'helperSha256':self.helpers[policy.HELPER]});policy.validate_contract(result,self.after_map,self.helpers)
        for n,v in self.after.items():self.assertEqual((self.source/n).read_bytes(),v)
    def test_late_dependency_drift_never_partially_patches_product(self):
        name=next(n for n in reversed(policy.SOURCE_FILES) if n not in policy.REPLACEMENTS);(self.source/name).write_bytes(self.before[name]+b'// drift')
        with self.assertRaises(ValueError):policy.apply(self.source)
        for n in policy.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
    def test_missing_dependency_never_partially_patches_product(self):
        name=next(n for n in reversed(policy.SOURCE_FILES) if n not in policy.REPLACEMENTS);(self.source/name).unlink()
        with self.assertRaises(ValueError):policy.apply(self.source)
        for n in policy.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
    def test_duplicate_verified_product_anchor_is_rejected(self):
        name=next(iter(policy.REPLACEMENTS));old,new=policy.REPLACEMENTS[name][0];raw=self.before[name]+old.encode();(self.source/name).write_bytes(raw)
        changed=dict(self.before_map);changed[name]=hashlib.sha256(raw).hexdigest()
        with patch.object(policy,'INPUT_SOURCE_SHA256',changed),self.assertRaises(ValueError):policy.apply(self.source)
        self.assertEqual((self.source/name).read_bytes(),raw)
    def test_reapplication_cannot_refresh_the_before_pin(self):
        policy.apply(self.source)
        with self.assertRaises(ValueError):policy.apply(self.source)
        for n,v in self.after.items():self.assertEqual((self.source/n).read_bytes(),v)
    def test_symlink_dependency_does_not_change_any_source(self):
        name=next(n for n in reversed(policy.SOURCE_FILES) if n not in policy.REPLACEMENTS);p=self.source/name;p.unlink();target=self.source/'held.rs';target.write_bytes(self.before[name]);p.symlink_to(target)
        with self.assertRaises(ValueError):policy.apply(self.source)
        self.assertEqual(target.read_bytes(),self.before[name])
        for n in policy.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
    def test_coherent_old_source_and_proof_are_rejected(self):
        result=policy.apply(self.source);result['afterSha256']=dict(self.before_map)
        with self.assertRaises(ValueError):policy.validate_contract(result,self.before_map,self.helpers)
    def test_proof_schema_current_source_and_helper_fail_closed(self):
        result=policy.apply(self.source);cases=[]
        for key in result:
            bad=copy.deepcopy(result);bad.pop(key);cases.append(bad)
        bad=copy.deepcopy(result);bad['extra']=True;cases.append(bad)
        for key in ['beforeSha256','afterSha256']:
            for name in policy.SOURCE_FILES:
                bad=copy.deepcopy(result);bad[key][name]='0'*64;cases.append(bad)
        bad=copy.deepcopy(result);bad['helperSha256']='0'*64;cases.append(bad)
        for bad in cases:
            with self.subTest(proof=bad),self.assertRaises(ValueError):policy.validate_contract(bad,self.after_map,self.helpers)
        for sources,helpers in [({},self.helpers),(self.after_map,{})]:
            with self.assertRaises(ValueError):policy.validate_contract(result,sources,helpers)
    def test_existing_writer_predicate_is_a_required_dependency(self):
        name='third_party/rhwp/src/serializer/hwpx/section.rs';raw=self.before[name].replace(b'!imported_stored_origin',b'imported_stored_origin');(self.source/name).write_bytes(raw)
        before=dict(self.before_map);after=dict(self.after_map);before[name]=after[name]=hashlib.sha256(raw).hexdigest()
        with patch.object(policy,'INPUT_SOURCE_SHA256',before),patch.object(policy,'OUTPUT_SOURCE_SHA256',after),self.assertRaises(ValueError):policy.apply(self.source)
        for n in policy.REPLACEMENTS:self.assertEqual((self.source/n).read_bytes(),self.before[n])
if __name__=='__main__':unittest.main()
