"""Metadata profile selection never supplies a new qualified engine fixture."""
import copy
from dataclasses import FrozenInstanceError
import importlib
from pathlib import Path
import sys
from types import MappingProxyType
from unittest.mock import patch
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from suite import source_contracts as contracts
from suite.e2e import native_menu_source_admission as gate
from suite.tests import test_native_menu_source_admission as admission_fixtures

def runtime(pin):
 return dict(format='source-built-zip',version=pin['version'],sourceCoreCommit=pin['coreCommit'],
             sourceUrl=pin['url'],sourceSha256=pin['sha256'])

class ConsumerSourceMenuProfileTests(unittest.TestCase):
 def test_runtime_metadata_selects_only_two_closed_source_profiles(self):
  for pin,expected in ((contracts.LEGACY_SOURCE,contracts.LEGACY),(contracts.NEW_SOURCE,contracts.NEW)):
   self.assertIs(gate._runtime_source_contract(runtime(pin)),expected)
   self.assertFalse(expected.qualifies_runtime)
 def test_cross_profile_runtime_metadata_never_selects_a_profile(self):
  baseline=runtime(contracts.NEW_SOURCE)
  for key,old in (('version',contracts.LEGACY_SOURCE['version']),('sourceCoreCommit',contracts.LEGACY_SOURCE['coreCommit']),
                  ('sourceUrl',contracts.LEGACY_SOURCE['url']),('sourceSha256',contracts.LEGACY_SOURCE['sha256']),
                  ('format','msi')):
   changed=dict(baseline);changed[key]=old
   with self.assertRaises(ValueError):gate._runtime_source_contract(changed)
 def test_boolean_and_nonstring_runtime_metadata_are_not_source_profiles(self):
  for key in ('version','sourceCoreCommit','sourceUrl','sourceSha256'):
   for value in (True,None,17):
    changed=runtime(contracts.NEW_SOURCE);changed[key]=value
    with self.assertRaises(ValueError):gate._runtime_source_contract(changed)
 def test_legacy_real_admission_retains_its_authenticated_contract(self):
  fixture=admission_fixtures.SourceMenuAdmissionTests(methodName='test_admits_real_validators_and_freezes_closed_binary_summary')
  fixture.setUp();self.addCleanup(fixture.doCleanups)
  admitted=fixture.admit()
  self.assertIs(admitted.source_contract(),contracts.LEGACY)
  self.assertFalse(admitted.source_contract().qualifies_runtime)
  with self.assertRaises(FrozenInstanceError):admitted._source_contract=contracts.NEW
 def test_changing_the_closed_summary_does_not_change_the_admitted_profile(self):
  fixture=admission_fixtures.SourceMenuAdmissionTests(methodName='test_admits_real_validators_and_freezes_closed_binary_summary')
  fixture.setUp();self.addCleanup(fixture.doCleanups)
  admitted=fixture.admit()
  summary=dict(admitted.summary());summary['sourceCoreCommit']=contracts.NEW.core
  object.__setattr__(admitted,'_summary',MappingProxyType(summary))
  with self.assertRaises(ValueError):admitted.source_contract()
  with self.assertRaises(ValueError):admitted.summary()
 def test_msaa_words_require_the_same_authenticated_profile(self):
  fixture=admission_fixtures.SourceMenuAdmissionTests(methodName='test_admits_real_validators_and_freezes_closed_binary_summary')
  fixture.setUp();self.addCleanup(fixture.doCleanups)
  admitted=fixture.admit()
  from suite.e2e.native_menu_msaa_hit import _admission_words_v4
  with patch.dict(sys.modules,{'native_menu_source_admission':gate}):
   self.assertEqual(len(_admission_words_v4(admitted,admitted.admission_sha256)),8)
   with patch.object(gate.SourceMenuAdmission,'source_contract',side_effect=ValueError('Profile unavailable')):
    with self.assertRaises(ValueError):_admission_words_v4(admitted,admitted.admission_sha256)
 def test_new_metadata_cannot_bypass_the_complete_source_recipe_validator(self):
  pin=dict(contracts.NEW_SOURCE)
  for architecture in ('arm64','x64'):
   expected=contracts.new_source_only_expectations(pin,architecture)
   proof=dict(sourcePin=pin,winAccFocusOrderSourcePatch=dict(expected.winacc_fields,sourceFiles=copy.deepcopy(gate._PATCH_FILES)))
   with patch.object(gate.prepare,'_source_new_recipe',side_effect=ValueError('source-only-validator-called'),create=True) as validator:
    with self.assertRaisesRegex(ValueError,'^source-only-validator-called$'):
     gate._recipe_identity(proof,runtime(pin),architecture)
    validator.assert_called_once_with(proof,architecture)
 def test_new_recipe_core_cannot_be_replaced_by_legacy_source_metadata(self):
  pin=dict(contracts.NEW_SOURCE);expected=contracts.new_source_only_expectations(pin,'arm64')
  proof=dict(sourcePin=dict(contracts.LEGACY_SOURCE),winAccFocusOrderSourcePatch=dict(expected.winacc_fields,sourceFiles=copy.deepcopy(gate._PATCH_FILES)))
  with patch.object(gate.prepare,'_source_new_recipe',create=True) as validator:
   with self.assertRaises(ValueError):gate._recipe_identity(proof,runtime(pin),'arm64')
   validator.assert_not_called()
 def test_source_only_recipe_digest_never_becomes_runtime_admission(self):
  from suite.tests.test_prepare_source_profile_v2 import PrepareSourceProfileV2Tests
  helper=PrepareSourceProfileV2Tests('runTest')
  for architecture in ('arm64','x64'):
   proof=helper.source_only(architecture)
   metadata=runtime(contracts.NEW_SOURCE)
   metadata['sourceBuild']=dict(patchManifestSha256=proof['sourcePortManifestSha256'])
   digest=gate._recipe_identity(proof,metadata,architecture)
   self.assertRegex(digest,'^[0-9a-f]{64}$')
   with self.assertRaises(ValueError):gate.prepare.validate_source_build_lock(metadata,architecture=architecture)
   self.assertNotIn('artifact',proof);self.assertNotIn('Full',proof.values())
   mutated=copy.deepcopy(proof);mutated['flexFatalCompatibilitySourcePatch']['afterSha256']='0'*64
   with self.assertRaises(ValueError):gate._recipe_identity(mutated,metadata,architecture)
 def test_new_source_only_metadata_cannot_replace_external_runtime_pins(self):
  with self.assertRaises(ValueError):gate.prepare.validate_source_build_lock(runtime(contracts.NEW_SOURCE),architecture='arm64')

if __name__=='__main__':unittest.main()
