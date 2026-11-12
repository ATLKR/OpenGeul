"""Current-v5 replay rejects missing/modified/downlabeled evidence; fixtures only."""
import copy
import ctypes
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime
import test_korean_ime_smoke as historical
class ProfileLanguageConsumerTests(unittest.TestCase):
    def setUp(self):self.expected_source=ime.profile_policy_source_sha256()
    def legacy(self):return historical.KoreanImePolicyTests().record()
    def modern(self,*,changed=False):
        record=self.legacy();record['imePolicyVersion']=5;record['imePolicySourceSha256']=self.expected_source
        for command in record['imeCommands']:
            command['policyVersion']=5;command['nativeSnapshotBytes']=ctypes.sizeof(ime.NativeState)
            language={name:0 for name,_ in ime.NativeProfileLanguageRecord._fields_};command['profileLanguage']=language
            if command['command'] in (1,4):
                number=command['command'];language.update(schemaVersion=1,command=number,complete=1,originalLanguage=0x409,
                    observedBefore=0x409,interfaceAttempts=1,getterAttempts=1 if number==1 else 2,observedMask=3 if number==1 else 19)
                if number==4:
                    language['observedAfterHkl']=0x409
                    if changed:language.update(observedBefore=0x412,observedAfterChange=0x409,changeAttempts=1,getterAttempts=3,observedMask=31)
        return record
    def replay(self,record):return ime.require_tsf_pipeline(record,expected_source=self.expected_source)
    def test_current_default_replays_both_conditional_and_unchanged_language_paths(self):
        for changed in (False,True):
            self.replay(self.modern(changed=changed))
    def test_missing_any_current_language_evidence_is_rejected(self):
        for index in range(4):
            record=self.modern();record['imeCommands'][index].pop('profileLanguage')
            with self.subTest(command=index+1),self.assertRaises((AssertionError,KeyError)):self.replay(record)
    def test_modified_restore_capture_or_fabricated_nonlanguage_command_is_rejected(self):
        for index,field,value in ((0,'originalLanguage',0x412),(0,'observedBefore',0x412),(3,'complete',0),
                (3,'getAfterHklHresult',-2147024809),(3,'observedAfterHkl',0x412),(3,'changeAttempts',True),(1,'changeAttempts',1)):
            record=self.modern();record['imeCommands'][index]['profileLanguage'][field]=value
            with self.subTest(command=index+1,field=field),self.assertRaises(AssertionError):self.replay(record)
    def test_current_evidence_cannot_downlabel_all_versions_and_remove_new_markers(self):
        record=self.modern();record['imePolicyVersion']=4;record.pop('imePolicySourceSha256')
        for row in record['imeCommands']:
            row['policyVersion']=4;row.pop('nativeSnapshotBytes');row.pop('profileLanguage')
        with self.assertRaises(AssertionError):self.replay(record)
    def test_historical_success_requires_explicit_external_policy_selection(self):
        record=self.legacy()
        with self.assertRaises(AssertionError):ime.require_tsf_pipeline(record)
        ime.require_tsf_pipeline(record,expected_policy=4)
        record['imeCommands'][0]['profileLanguage']={}
        with self.assertRaises(AssertionError):ime.require_tsf_pipeline(record,expected_policy=4)
    def test_source_or_snapshot_identity_cannot_be_selected_from_the_receipt(self):
        for mutate in (lambda r:r.pop('imePolicySourceSha256'),lambda r:r.update(imePolicySourceSha256='0'*64),
                lambda r:r['imeCommands'][2].update(policyVersion=4),lambda r:r['imeCommands'][2].update(nativeSnapshotBytes=596824)):
            record=self.modern();mutate(record)
            with self.assertRaises(AssertionError):self.replay(record)
        record=self.modern();record['imePolicySourceSha256']='0'*64
        with self.assertRaises(AssertionError):ime.require_tsf_pipeline(record,expected_source='0'*64)
    def test_language_proof_does_not_mask_existing_hkl_profile_or_typed_failures(self):
        for mutate in (lambda r:r['imeCommands'][3].update(activateProfileHresult=-2147024809),
                lambda r:r['imeCommands'][3].update(layout=0x04120412),lambda r:r['imeCommands'][3].update(activeLanguage=0x0412),
                lambda r:r['imeCommands'][3]['threadMode'].update(afterConversion=99)):
            record=self.modern();mutate(record)
            with self.assertRaises(AssertionError):self.replay(record)
    def test_current_source_expectation_is_independent_and_exact(self):
        record=self.modern()
        with self.assertRaises(AssertionError):ime.require_tsf_pipeline(record,expected_source='f'*64)
        self.assertNotEqual(self.expected_source,'f'*64)
if __name__=='__main__':unittest.main()
