"""Reader profile authority stays external to raw receipts and helper JSON."""
import copy
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from suite import source_contracts
from suite.tests import test_native_menu_source_admission as admission_fixtures

E2E=Path(__file__).resolve().parents[1]/"e2e"
if str(E2E) not in sys.path: sys.path.insert(0,str(E2E))
reader=importlib.import_module("writer_model_reader")
OLD="Office/program/python-core-3.13.15/bin/python.exe"
NEW="Office/program/python-core-3.13.17/bin/python.exe"
DIGEST="a"*64

class ReaderSourceProfileTests(unittest.TestCase):
    def options(self, **extra):
        return dict(shell_pid=11,expected_shell_creation=12,suite_hwnd=13,parent_hwnd=14,
                    child_hwnd=15,office_pid=16,expected_url="file:///owned/doc.odt",**extra)

    def test_none_preserves_exact_legacy_without_io(self):
        with patch.object(Path,"stat",side_effect=AssertionError("filesystem forbidden")), patch.object(Path,"resolve",side_effect=AssertionError("filesystem forbidden")):
            self.assertEqual(reader.require_reader_source_context(None,"C:/Suite",None),OLD)
            controller=reader.OwnedWriterReader("C:/Suite","C:/out",**self.options())
        self.assertEqual(controller._reader_core_member,OLD)
        self.assertNotIn("source_admission",controller.config)
        self.assertEqual(controller._source_replay_options(),{})

    def test_data_projection_is_closed_and_grants_no_admission(self):
        self.assertEqual(reader._reader_member_for_contract(source_contracts.LEGACY),OLD)
        self.assertEqual(reader._reader_member_for_contract(source_contracts.NEW),NEW)
        clone=source_contracts.SourceContract("26.8.2.2",source_contracts.NEW.core,"3.13.17","3.0.14.33856-0","2","2")
        for untrusted in (clone,dict(version="26.8.2.2",python_version="3.13.17"),None):
            with self.assertRaises(ValueError):reader._reader_member_for_contract(untrusted)
        with self.assertRaises(ValueError):reader.require_reader_source_context(source_contracts.NEW,"C:/Suite",DIGEST)

    def test_mapping_duck_and_unsealed_context_cannot_select_python17(self):
        class Duck:
            suite_root=Path("C:/Suite")
            def source_contract(self):return source_contracts.NEW
            def summary(self):return dict(inventorySha256=DIGEST,sourceCoreCommit=source_contracts.NEW.core)
        for untrusted in ({"sourceCoreCommit":source_contracts.NEW.core},Duck()):
            with self.assertRaises(ValueError):reader.require_reader_source_context(untrusted,"C:/Suite",DIGEST)
            with self.assertRaises(ValueError):reader.OwnedWriterReader("C:/Suite","C:/out",**self.options(source_admission=untrusted,inventory_sha256=DIGEST))

    def test_member_requires_one_external_expectation_not_any_core(self):
        binding=dict(shellPid=11,officePid=16)
        row=dict(inOwnedJob=True,isInJobApiSucceeded=True,jobHandleValue=1,pid=17,
                 creationTime=18,handleValue=19,image="C:/Suite/"+NEW,waitResult=258,exitCode=259)
        with self.assertRaises(AssertionError):reader._reader_member(row,binding,"C:/Suite",True)
        reader._reader_member(row,binding,"C:/Suite",True,core_member=NEW)
        row["image"]="C:/Suite/"+OLD
        with self.assertRaises(AssertionError):reader._reader_member(row,binding,"C:/Suite",True,core_member=NEW)

    def test_missing_external_context_rejects_python17_cleanup_at_member_boundary(self):
        binding=dict(shellPid=11,officePid=16)
        row=dict(inOwnedJob=True,isInJobApiSucceeded=True,jobHandleValue=1,pid=17,
                 creationTime=18,handleValue=19,image="C:/Suite/"+NEW,waitResult=0,exitCode=0)
        with self.assertRaises(AssertionError):reader._job_member(row,binding,"C:/Suite",False,dict(path="C:/Windows/conhost.exe"))
        self.assertEqual(reader._job_member(row,binding,"C:/Suite",False,dict(path="C:/Windows/conhost.exe"),core_member=NEW),"packaged-python")

    def test_actual_legacy_factory_context_binds_suite_and_inventory_without_io(self):
        fixture=admission_fixtures.SourceMenuAdmissionTests("test_admits_real_validators_and_freezes_closed_binary_summary")
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        gate=fixture.implementation()
        admitted=fixture.admit();digest=admitted.summary()["inventorySha256"]
        with patch.dict(sys.modules,{"native_menu_source_admission":gate}), patch.object(Path,"stat",side_effect=AssertionError("filesystem forbidden")), patch.object(Path,"resolve",side_effect=AssertionError("filesystem forbidden")):
            self.assertEqual(reader.require_reader_source_context(admitted,str(fixture.root),digest),OLD)
            for root,sha in ((str(fixture.root)+"-other",digest),(str(fixture.root),"0"*64),(str(fixture.root),None)):
                with self.assertRaises(ValueError):reader.require_reader_source_context(admitted,root,sha)
            controller=reader.OwnedModelReader(fixture.root,fixture.root/"output",expected_service="com.sun.star.sheet.SpreadsheetDocument",getter_contract=reader.CALC_GETTER_CONTRACT,**self.options(source_admission=admitted,inventory_sha256=digest))
            self.assertIs(controller._source_replay_options()["source_admission"],admitted)
            self.assertEqual(controller._source_replay_options()["inventory_sha256"],digest)
            config=controller.config
        self.assertNotIn("expected_reader_image_relative",config)
        self.assertNotIn("source_admission",config)
        self.assertNotIn("inventory_sha256",config)
        json.dumps(config)

    def test_config_metadata_cannot_recreate_source_authority(self):
        controller=reader.OwnedWriterReader("C:/Suite","C:/out",**self.options())
        controller.config.update(sourceCoreCommit=source_contracts.NEW.core,inventorySha256=DIGEST)
        self.assertEqual(controller._source_replay_options(),{})
        self.assertEqual(controller._reader_core_member,OLD)
        with self.assertRaises(ValueError):reader.require_reader_source_context(controller.config,"C:/Suite",DIGEST)
        json.dumps(controller.config)


    def test_public_observation_ignores_raw_new_source_claims_without_context(self):
        from suite.tests.test_writer_model_reader import binding_fixture,observation_fixture
        binding=binding_fixture();observation=observation_fixture(binding)
        reader.require_owned_observation(observation,binding,"C:/Suite")
        modified=json.loads(json.dumps(observation).replace("python-core-3.13.15/","python-core-3.13.17/"))
        modified.update(sourceCoreCommit=source_contracts.NEW.core,inventorySha256=DIGEST,source_admission=dict(sourceCoreCommit=source_contracts.NEW.core))
        with self.assertRaisesRegex(AssertionError,"Reader job contains a foreign executable"):
            reader.require_owned_observation(modified,binding,"C:/Suite")

    def test_public_cleanup_ignores_raw_new_source_claims_without_context(self):
        from suite.tests.test_writer_model_reader import binding_fixture,cleanup_fixture
        binding=binding_fixture();cleanup=cleanup_fixture(binding,"C:/Suite")
        reader.require_reader_cleanup(cleanup,binding,12.0)
        modified=json.loads(json.dumps(cleanup).replace("python-core-3.13.15/","python-core-3.13.17/"))
        modified.update(sourceCoreCommit=source_contracts.NEW.core,inventorySha256=DIGEST)
        with self.assertRaisesRegex(AssertionError,"Reader job contains a foreign executable"):
            reader.require_reader_cleanup(modified,binding,12.0)

    def test_admitted_legacy_context_joins_raw_observation_and_cleanup_inventory(self):
        from suite.tests.test_writer_model_reader import binding_fixture,observation_fixture,cleanup_fixture
        fixture=admission_fixtures.SourceMenuAdmissionTests("test_admits_real_validators_and_freezes_closed_binary_summary")
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        gate=fixture.implementation();admitted=fixture.admit();digest=admitted.summary()["inventorySha256"]
        binding=binding_fixture();binding["expectedImage"]=str(fixture.root/"Office/program/soffice.bin")
        observation=observation_fixture(binding,str(fixture.root));observation["pythonIdentity"]["inventorySha256"]=digest
        cleanup=cleanup_fixture(binding,str(fixture.root))
        with patch.dict(sys.modules,{"native_menu_source_admission":gate}), patch.object(Path,"stat",side_effect=AssertionError("filesystem forbidden")), patch.object(Path,"resolve",side_effect=AssertionError("filesystem forbidden")):
            reader.require_owned_observation(observation,binding,str(fixture.root),source_admission=admitted,inventory_sha256=digest)
            reader.require_reader_cleanup(cleanup,binding,12.0,source_admission=admitted,inventory_sha256=digest)
            observation["pythonIdentity"]["inventorySha256"]="0"*64
            with self.assertRaisesRegex(AssertionError,"Reader observation inventory differs"):
                reader.require_owned_observation(observation,binding,str(fixture.root),source_admission=admitted,inventory_sha256=digest)


    def test_cold_canonical_modules_fail_closed_without_importing(self):
        with patch.dict(sys.modules,{"native_menu_source_admission":None}), patch("builtins.__import__",side_effect=AssertionError("Cold import forbidden")):
            with self.assertRaises(ValueError):reader.require_reader_source_context({"sourceCoreCommit":source_contracts.NEW.core},"C:/Suite",DIGEST)
        with patch.dict(sys.modules,{"suite.source_contracts":None}), patch("builtins.__import__",side_effect=AssertionError("Cold import forbidden")):
            with self.assertRaises(ValueError):reader._reader_member_for_contract(source_contracts.NEW)

if __name__=="__main__":unittest.main()
