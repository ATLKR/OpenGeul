"""Fake UNO preparation boundaries; real pending-input coverage is physical E2E."""
import importlib
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import unittest

from suite.tests import test_calc_save as save_fixture

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))


class CalcClosePreparationTests(unittest.TestCase):
    def setUp(self):
        self.api=importlib.import_module('calc_close')
        self.fixture=save_fixture.CalcSaveTests(); self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.modified=False
        f.document.isModified=lambda:self.modified
        f.document.getTitle=lambda:'Original'
        self.transaction=f.transaction()
        def query(url,target,flags):
            self.assertEqual(('.uno:AcceptFormula','.uno:','AcceptFormula','_self',0),
                             (url.Complete,url.Protocol,url.Path,target,flags))
            f.calls.append(('query-accept',));return f.dispatch
        f.controller.queryDispatch=query
        # The native slot has no semantic return value; FAILURE is not a veto.
        f.result=NS(State=0,Result=None)

    def test_ordinary_buffer_preparation_is_one_owned_main_thread_native_operation_without_store(self):
        f=self.fixture; f.effect=lambda:setattr(self,'modified',True)
        result=self.api.prepare_calc_close(self.transaction)
        self.assertTrue(result['modified']);self.assertTrue(result['nativeModified'])
        self.assertFalse(result['closePreparation']['asyncValidationQualified'])
        self.assertEqual(1,len(f.executed()))
        _,provider,command,target,flags,args=f.executed()[0]
        self.assertIs(provider,f.controller)
        self.assertEqual(('.uno:AcceptFormula','_self',0),(command,target,flags))
        self.assertEqual({'OnMainThread':True},args)
        self.assertIs(f.document,f.backend.document)
        self.assertEqual(f.path,self.transaction.path)

    def test_clean_model_is_not_a_pending_input_oracle_and_still_requires_explicit_choice(self):
        result=self.api.prepare_calc_close(self.transaction)
        self.assertFalse(result['nativeModified'])
        self.assertTrue(result['modified'])
        self.assertTrue(result['closePreparation']['requiresExplicitChoice'])
        self.assertFalse(result['closePreparation']['pendingInputAbsenceVerified'])

    def test_untitled_readonly_and_owned_path_do_not_open_picker_or_store(self):
        f=self.fixture; f.url='';f.document.isReadonly=lambda:True
        result=self.api.prepare_calc_close(self.transaction)
        self.assertTrue(result['modified'])
        self.assertEqual({'OnMainThread':True},f.executed()[0][5])
        self.assertEqual('',f.url)

    def test_ownership_and_active_frame_failures_keep_document_without_fallback(self):
        f=self.fixture
        f.frame.getController=lambda:object()
        with self.assertRaises(self.api.WorkerError): self.api.prepare_calc_close(self.transaction)
        self.assertEqual([],f.executed())
        f.frame.getController=lambda:f.controller
        f.effect=lambda:setattr(f.frame,'isActive',lambda:False)
        with self.assertRaises(self.api.WorkerError): self.api.prepare_calc_close(self.transaction)
        self.assertEqual(1,len(f.executed()))
        self.assertIs(f.document,f.backend.document)

    def test_missing_unknown_or_value_bearing_dispatch_result_never_qualifies_preparation(self):
        f=self.fixture
        for result in (None,NS(State=True,Result=None),NS(State=2,Result=None),NS(State=1,Result=True)):
            f.result=result
            with self.subTest(result=result),self.assertRaises(self.api.WorkerError):
                self.api.prepare_calc_close(self.transaction)
        self.assertEqual(4,len(f.executed()))
        self.assertIs(f.document,f.backend.document)

    def test_reentrant_preparation_or_save_is_rejected_and_failure_releases_only_local_guard(self):
        f=self.fixture; nested=[]
        def effect():
            with self.assertRaises(self.api.WorkerError): self.api.prepare_calc_close(self.transaction)
            nested.append(True)
        f.effect=effect
        self.api.prepare_calc_close(self.transaction)
        self.assertEqual([True],nested);self.assertEqual(1,len(f.executed()))
        f.effect=None;self.transaction.saving=True
        with self.assertRaises(self.api.WorkerError): self.api.prepare_calc_close(self.transaction)
        self.assertEqual(1,len(f.executed()))
        self.transaction.saving=False
        self.api.prepare_calc_close(self.transaction)
        self.assertEqual(2,len(f.executed()))


if __name__=='__main__':unittest.main()
