"""Closed diagnostics only; no Windows tools/package/context is exercised."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class FailureObservationTests(unittest.TestCase):
    def api(self):
        import ci_entry
        self.assertTrue(callable(getattr(ci_entry,'failure_observation',None)),'closed failure observation required')
        return ci_entry
    def test_unknown_exception_message_and_path_are_never_projected(self):
        m=self.api();marker='SYNTHETIC-PRIVATE-MARKER'
        try:raise RuntimeError(marker)
        except RuntimeError as error:value=m.failure_observation(error,8)
        self.assertEqual(value['stageCode'],8);self.assertEqual(value['exceptionTypeCode'],0)
        self.assertFalse(value['exceptionKnown']);self.assertNotIn(marker,json.dumps(value))
        self.assertNotIn('message',value);self.assertNotIn('path',value)
    def test_ci_failure_and_os_numeric_codes_are_separate_from_generic31(self):
        m=self.api();value=m.failure_observation(m.CiFailure(7),3)
        self.assertEqual(value['exceptionTypeCode'],1);self.assertEqual(value['nativeCode'],7)
        error=FileNotFoundError(2,'SYNTHETIC',r'C:\SYNTHETIC-PRIVATE')
        error.winerror=3
        value=m.failure_observation(error,8)
        self.assertEqual(value['exceptionTypeCode'],5);self.assertEqual(value['errno'],2);self.assertEqual(value['winerror'],3)
        self.assertNotIn('SYNTHETIC',json.dumps(value))
    def test_installed_command_role_hardlink_is_observed_and_still_rejected(self):
        m=self.api();import toolchain
        self.assertTrue(callable(getattr(toolchain,'installed_pe',None)),'finite installed role seam required')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'command.exe';path.write_bytes(b'SYNTHETIC')
            (root/'alias.exe').hardlink_to(path)
            caught=None
            try:toolchain.installed_pe(path,0x8664,2)
            except toolchain.GateFailure as error:caught=m.failure_observation(error,8)
            self.assertIsNotNone(caught,'the original hardlink guard must keep rejecting')
            self.assertEqual(caught['exceptionTypeCode'],2);self.assertEqual(caught['nativeCode'],2)
            self.assertEqual(caught['fileRoleCode'],2);self.assertEqual(caught['filesystemCode'],4)
            self.assertEqual(caught['observedLinkCount'],2)
            self.assertTrue(any(row['fileCode']==2 and row['line']>0 for row in caught['sourceFrames']))
    def test_owned_source_hardlink_guard_is_not_given_installed_file_authority(self):
        m=self.api();import toolchain
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'source.py';path.write_bytes(b'SYNTHETIC')
            (root/'alias.py').hardlink_to(path)
            with self.assertRaises(toolchain.GateFailure) as raised:toolchain.read(path)
            value=m.failure_observation(raised.exception,7)
            self.assertIsNone(value['fileRoleCode']);self.assertEqual(value['observedLinkCount'],2)
    def test_no_autoload_for_optional_exception_classification(self):
        m=self.api()
        from unittest.mock import patch
        import importlib
        with patch.object(importlib,'import_module',side_effect=AssertionError('unexpected import')):
            value=m.failure_observation(RuntimeError('SYNTHETIC'),5)
        self.assertEqual(value['exceptionTypeCode'],0)
    def test_noninteger_attributes_do_not_enter_numeric_report(self):
        m=self.api();import supervisor
        error=supervisor.GateFailure(2);error.file_role_code='SYNTHETIC';error.observed_link_count=True
        error.filesystem_code=-3
        value=m.failure_observation(error,8)
        self.assertIsNone(value['fileRoleCode']);self.assertIsNone(value['observedLinkCount']);self.assertIsNone(value['filesystemCode'])
    def test_failure_report_is_versioned_and_keeps_outer_unknown(self):
        m=self.api();value=m.failure_observation(m.CiFailure(3),5)
        report=m.public_report({'sourceCommit':'a'*40},None,None,failure=31,observation=value)
        self.assertEqual(report['schemaVersion'],2);self.assertEqual(report['failureObservation'],value)
        self.assertFalse(report['sdkReportKnown']);self.assertIsNone(report['sdkStage'])
        self.assertFalse(report['envelopeKnown']);self.assertIsNone(report['envelopeCleanupProved'])
        self.assertFalse(report['qualification']);self.assertFalse(report['canService'])
    def test_unsupported_stage_is_not_invented(self):
        m=self.api()
        for value in (True,-1,14,'8',None):
            with self.subTest(case=type(value).__name__),self.assertRaises(m.CiFailure):m.failure_observation(RuntimeError(),value)
    def test_known_native_enum_is_projected_as_its_numeric_code(self):
        m=self.api();import owned_job_win32
        value=m.failure_observation(owned_job_win32.NativeCallError(owned_job_win32.FailureCode.NATIVE_CALL),10)
        self.assertEqual(value['exceptionTypeCode'],3);self.assertEqual(value['nativeCode'],18)
