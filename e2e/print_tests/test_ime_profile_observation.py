"""Genuine Python profile/caller boundaries with synthetic native returns only."""
import ast
from contextlib import contextmanager, nullcontext, redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


def load(relative,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


IME=load('e2e/windows_ime.py','numeric_candidate_windows_ime')
with patch.dict(sys.modules,{'windows_ime':IME}):
    CASES=load('e2e/native_ime_cases.py','numeric_candidate_native_ime_cases')
HKL=0xe0010412
FIXED_NAME='ime-profile-failure.numeric.json'


class StopAfterGuard(Exception): pass


class FakeImm:
    def __init__(self,count=0,result=1,raises=None):
        self.count=count;self.result=result;self.raises=raises;self.calls=[]
    def ImmIsIME(self,layout):
        self.calls.append(('isIme',layout))
        if self.raises and self.raises[0]=='isIme':raise self.raises[1]
        return self.result
    def ImmGetIMEFileNameW(self,layout,buffer,capacity):
        self.calls.append(('filename',layout,capacity))
        if self.raises and self.raises[0]=='filename':raise self.raises[1]
        return self.count
    def ImmGetDescriptionW(self,*unused):
        self.calls.append(('description',))
        raise StopAfterGuard()


class Keyboard:
    def __init__(self):
        self.binding={};self.calls=[]
    def layouts(self):self.calls.append('layouts');return [HKL]
    def ready(self,**unused):self.calls.append('ready');return {'layout':HKL}
    def prerequisites(self):return {'synthetic':True}


def subject(count=0,result=1,raises=None):
    value=IME.MicrosoftKoreanIme.__new__(IME.MicrosoftKoreanIme)
    value.keyboard=Keyboard();value.imm=FakeImm(count,result,raises);value.records=[]
    return value


@contextmanager
def configure_imports():
    driver=ModuleType('driver');driver.until=lambda predicate,**unused:predicate()
    policy=ModuleType('native_document_policy');policy.assert_body_markers=lambda *a,**k:None
    with patch.dict(sys.modules,{'driver':driver,'native_document_policy':policy}):yield


class Harness(CASES.NativeImeCases):
    def __init__(self,folder):self.folder=Path(folder);self.writes=[]
    def _ime_receipt(self,name,value):self.writes.append(name)


def execute_configure(case,ime):
    with configure_imports(),patch.object(CASES,'require_korean_prerequisites',return_value=True):
        case._ime_configure(ime.keyboard,ime,SimpleNamespace(page=None),'synthetic')


def normalize(source):return ast.dump(ast.parse(source),include_attributes=False)


class Counts(unittest.TestCase):
    def test_genuine_inventory_guard_failure_has_fixed_numeric_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            harness=Harness(folder);ime=subject()
            with self.assertRaises(AssertionError):execute_configure(harness,ime)
            target=Path(folder)/FIXED_NAME
            self.assertTrue(target.is_file())
            value=json.loads(target.read_text())
            self.assertEqual((value['phaseCode'],value['actualCountObserved'],value['actualCount'],value['guardStage']),(1,1,0,4))
            self.assertTrue(all(type(item) is int for item in value.values()))
            self.assertEqual(ime.imm.calls,[('isIme',HKL),('isIme',HKL),('filename',HKL,1024)])
            self.assertEqual(ime.keyboard.calls,['layouts'])

    def test_active_failure_phase_has_one_call_each(self):
        with tempfile.TemporaryDirectory() as folder:
            ime=subject();case=Harness(folder)
            with self.assertRaises(AssertionError):case._ime_profile_call(ime,2)
            value=json.loads((Path(folder)/FIXED_NAME).read_text())
            self.assertEqual(value['phaseCode'],2)
            self.assertEqual(ime.imm.calls,[('isIme',HKL),('filename',HKL,1024)])
            self.assertEqual(ime.keyboard.calls,['ready'])

    def test_original_count_guard_boundaries_unchanged(self):
        for count,kind,stage in [(0,AssertionError,4),(1023,AssertionError,4),(1024,AssertionError,4),(1022,StopAfterGuard,5)]:
            with self.subTest(count=count),tempfile.TemporaryDirectory() as folder:
                ime=subject(count);case=Harness(folder)
                with self.assertRaises(kind):case._ime_profile_call(ime,2)
                value=json.loads((Path(folder)/FIXED_NAME).read_text())
                self.assertEqual((value['actualCount'],value['guardStage']),(count,stage))

    def test_original_false_guard_and_no_filename_call(self):
        with tempfile.TemporaryDirectory() as folder:
            ime=subject(result=0)
            with self.assertRaises(AssertionError):Harness(folder)._ime_profile_call(ime,2)
            value=json.loads((Path(folder)/FIXED_NAME).read_text())
            self.assertEqual((value['isImeObserved'],value['isImeResult'],value['filenameCallOccurred'],value['actualCountObserved']),(1,0,0,0))
            self.assertEqual(ime.imm.calls,[('isIme',HKL)])

    def test_native_no_return_keeps_original_exception_identity(self):
        for where,stage,occurred in [('isIme',1,0),('filename',3,1)]:
            with self.subTest(where=where),tempfile.TemporaryDirectory() as folder:
                primary=RuntimeError();ime=subject(raises=(where,primary))
                try:Harness(folder)._ime_profile_call(ime,2)
                except BaseException as actual:self.assertIs(actual,primary)
                else:self.fail()
                value=json.loads((Path(folder)/FIXED_NAME).read_text())
                self.assertEqual((value['guardStage'],value['filenameCallOccurred'],value['actualCountObserved']),(stage,occurred,0))

    def test_raw_bool_only_exact_int_and_truth_conversion_once(self):
        class Truth:
            def __init__(self):self.calls=0
            def __bool__(self):self.calls+=1;return True
            def __repr__(self):raise AssertionError()
            def __int__(self):raise AssertionError()
        for raw in (True,Truth()):
            with tempfile.TemporaryDirectory() as folder:
                ime=subject(result=raw)
                with self.assertRaises(AssertionError):Harness(folder)._ime_profile_call(ime,2)
                value=json.loads((Path(folder)/FIXED_NAME).read_text())
                self.assertEqual(value['isImeObserved'],0)
                if type(raw) is Truth:self.assertEqual(raw.calls,1)

    def test_filename_original_int_conversion_once(self):
        class Count:
            calls=0
            def __int__(self):self.calls+=1;return 0
        raw=Count()
        with tempfile.TemporaryDirectory() as folder:
            ime=subject(count=raw)
            with self.assertRaises(AssertionError):Harness(folder)._ime_profile_call(ime,2)
            self.assertEqual(raw.calls,1)

    def test_stale_snapshot_not_written_if_call_never_enters_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            ime=subject();case=Harness(folder)
            primary=RuntimeError()
            with self.assertRaises(AssertionError):case._ime_profile_call(ime,2)
            (Path(folder)/FIXED_NAME).unlink()
            ime.keyboard.ready=lambda **unused:(_ for _ in ()).throw(primary)
            try:case._ime_profile_call(ime,2)
            except BaseException as actual:self.assertIs(actual,primary)
            else:self.fail()
            self.assertFalse((Path(folder)/FIXED_NAME).exists())

    def test_wrong_phase_and_malformed_snapshot_not_written(self):
        for mutation in ('phase','string','extra'):
            with tempfile.TemporaryDirectory() as folder:
                ime=subject();case=Harness(folder);original=ime.active_profile
                def operation():
                    try:original()
                    except BaseException:
                        row=ime._profile_observation[1]
                        if mutation=='phase':row['phaseCode']=1
                        elif mutation=='string':row['actualCount']='SYNTHETIC'
                        else:row['text']='SYNTHETIC'
                        raise
                ime.active_profile=operation
                with self.assertRaises(AssertionError):case._ime_profile_call(ime,2)
                self.assertFalse((Path(folder)/FIXED_NAME).exists())

    def test_write_failure_and_existing_file_keep_primary_cleanup(self):
        for existing in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/FIXED_NAME
                if existing:target.write_bytes(b'SYNTHETIC_EXISTING')
                primary=RuntimeError();ime=subject(raises=('filename',primary));closed=[]
                try:
                    with patch.object(Path,'open',side_effect=OSError()) if not existing else nullcontext():
                        try:Harness(folder)._ime_profile_call(ime,2)
                        except BaseException as actual:self.assertIs(actual,primary)
                        else:self.fail()
                finally:closed.append(1)
                self.assertEqual(closed,[1])
                if existing:self.assertEqual(target.read_bytes(),b'SYNTHETIC_EXISTING')

    def test_observer_storage_failure_cannot_mask_primary(self):
        class RejectStorage(IME.MicrosoftKoreanIme):
            def __setattr__(self,key,value):
                if key=='_profile_observation':raise RuntimeError()
                return super().__setattr__(key,value)
        with tempfile.TemporaryDirectory() as folder:
            ime=RejectStorage.__new__(RejectStorage);ime.keyboard=Keyboard();primary=RuntimeError()
            ime.imm=FakeImm(raises=('filename',primary));ime.records=[]
            try:Harness(folder)._ime_profile_call(ime,2)
            except BaseException as actual:self.assertIs(actual,primary)
            else:self.fail()
            self.assertFalse((Path(folder)/FIXED_NAME).exists())

    def test_previous_generation_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            ime=subject();case=Harness(folder)
            with self.assertRaises(AssertionError):case._ime_profile_call(ime,2)
            stale=ime._profile_observation;(Path(folder)/FIXED_NAME).unlink();primary=RuntimeError()
            def replay():ime._profile_observation=stale;raise primary
            ime.active_profile=replay
            try:case._ime_profile_call(ime,2)
            except BaseException as actual:self.assertIs(actual,primary)
            else:self.fail()
            self.assertFalse((Path(folder)/FIXED_NAME).exists())

    def test_non_integer_layout_never_exports_coerced_identity(self):
        for layout in (True,-1,2**64):
            with tempfile.TemporaryDirectory() as folder:
                ime=subject();ime.keyboard.ready=lambda **unused:{'layout':layout}
                with self.assertRaises(AssertionError):Harness(folder)._ime_profile_call(ime,2)
                self.assertFalse((Path(folder)/FIXED_NAME).exists())

    def test_success_dispatch_keeps_output_and_has_no_numeric_writer(self):
        for phase,name in [(1,'select_installed_profile'),(2,'active_profile')]:
            with tempfile.TemporaryDirectory() as folder:
                ime=subject();expected=object();calls=[]
                setattr(ime,name,lambda:(calls.append(phase),expected)[1])
                self.assertIs(Harness(folder)._ime_profile_call(ime,phase),expected)
                self.assertEqual(calls,[phase]);self.assertFalse((Path(folder)/FIXED_NAME).exists())

    def test_unknown_phase_executes_nothing(self):
        for phase in (0,3,True,None):
            with tempfile.TemporaryDirectory() as folder:
                ime=subject()
                with self.assertRaises(ValueError):Harness(folder)._ime_profile_call(ime,phase)
                self.assertEqual(ime.imm.calls,[]);self.assertEqual(ime.keyboard.calls,[])




if __name__ == '__main__':
    unittest.main()
