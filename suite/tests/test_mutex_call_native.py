"""Owned native disassembly driver; portable process seams, no DLL execution."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_ascii_message_preparation import Clock, Runtime, pe
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
SCRIPT = ROOT/'scripts/mutex_call_native.py'

class NativeCallsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'native static call driver absent')
        spec=importlib.util.spec_from_file_location('mutex_call_native_test',SCRIPT)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.install=self.root/'VS';self.clock=Clock()
        version=self.install/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        version.parent.mkdir(parents=True);version.write_text('14.44.35207\n')
        self.tool=self.install/'VC/Tools/MSVC/14.44.35207/bin/Hostarm64/arm64/dumpbin.exe'
        self.tool.parent.mkdir(parents=True)
        tool=bytearray(pe(0xaa64));struct.pack_into('<H',tool,64+22,2);self.tool.write_bytes(tool)
        programs=self.root/'programs';vswhere=programs/'Microsoft Visual Studio/Installer/vswhere.exe'
        vswhere.parent.mkdir(parents=True);vswhere.write_bytes(b'fake')
        case=self
        class FakeRuntime(Runtime):
            def start(inner,argv,folder):
                process=super().start(argv,folder)
                inner.folders.append(folder)
                if process.index:
                    (folder/'query.stdout').write_bytes(case.output)
                    (folder/'query.stderr').write_bytes(b'')
                    inner.scripts.append((folder/'compile.cmd').read_text())
                return process
        self.output=b'private disassembly text';self.runtime=FakeRuntime(self)
        self.runtime.folders=[];self.runtime.scripts=[];self.runtime.states=[[(0,0,0)]]*3
        self.calls=[];self.fixture_ok=True
        self.native=dict(processMachine=0,nativeMachine=0xaa64,processArchitecture='arm64',nativeArchitecture='arm64')
        for p in (patch.object(self.m.shared,'_Runtime',return_value=self.runtime),
                  patch.object(self.m.shared.time,'monotonic',self.clock),
                  patch.object(self.m.shared.time,'sleep',self.clock.sleep),
                  patch.object(self.m.shared.native_arch,'observe_native_architecture',return_value=self.native),
                  patch.dict(os.environ,{'ProgramFiles(x86)':str(programs)})):
            p.start();self.addCleanup(p.stop)
        self.budget=self.m.shared._Budget()
    def classify(self,text,**kw):
        self.calls.append((text,kw))
        if kw.get('fixture_target') is not None:return {'fixtureValidated':self.fixture_ok,'complete':True,'callCount':1,'calls':[]}
        return {'complete':True,'instructionCount':25,'callCount':1,'calls':[],'status':'classified','attributionProved':False}
    def run_driver(self,fixture_size=32):
        return self.m.inspect_calls(pe(0xaa64),pe(0xaa64),production_base=0x180000000,
            production_range={'beginRva':100192,'endRvaExclusive':100292},
            fixture_base=0x180000000,fixture_range={'beginRva':4096,'endRvaExclusive':4096+fixture_size},
            fixture_target=4200,condition_iat=9000,budget=self.budget,classify=self.classify)
    def test_fixture_first_three_owned_stages_and_private_files_removed(self):
        result=self.run_driver()
        self.assertEqual(len(self.calls),2);self.assertEqual(self.calls[0][1]['fixture_target'],4200)
        self.assertEqual(len(self.runtime.processes),3)
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))
        self.assertTrue(result['temporaryFilesRemoved'])
        self.assertTrue(all(not p.exists() for p in self.runtime.folders))
        for script in self.runtime.scripts:
            self.assertIn('/NOPDB /DISASM:NOBYTES /RANGE:',script)
        self.assertNotIn(str(self.root),json.dumps(result));self.assertNotIn('private disassembly',json.dumps(result))
    def test_fixture_mismatch_stops_before_production(self):
        self.fixture_ok=False
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertEqual(len(self.runtime.processes),2)
        self.assertTrue(all(not p.exists() for p in self.runtime.folders))
    def test_original_deadline_forces_owned_cleanup(self):
        self.runtime.late=True
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertTrue(self.runtime.processes[0].forced and self.runtime.processes[0].closed)
        self.assertEqual(self.budget.deadline,130)
    def test_expired_entry_never_launches_or_renews(self):
        self.clock.value=127
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertEqual(self.runtime.processes,[])
    def test_oversized_output_stops_before_classification(self):
        self.output=b'x'*(256*1024+1)
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertEqual(self.calls,[])
        self.assertTrue(all(not p.exists() for p in self.runtime.folders))
    def test_wrong_host_and_nonzero_exit_reject(self):
        self.native.update(nativeMachine=0x8664,nativeArchitecture='x64')
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertFalse(self.runtime.processes)
    def test_nonzero_query_and_handle_failure_cleanup_retained(self):
        self.runtime.states[1]=[(0,0,1)]
        with self.assertRaises(AssertionError) as caught:self.run_driver()
        self.assertTrue(self.runtime.processes[1].forced)
        self.assertTrue(caught.exception.callInspection['temporaryFilesRemoved'])
    def test_pinned_tool_wrong_machine_is_rejected(self):
        raw=bytearray(self.tool.read_bytes());struct.pack_into('<H',raw,68,0x8664);self.tool.write_bytes(raw)
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertEqual(len(self.runtime.processes),1)
    def test_exported_noinline_fixture_helper(self):
        source=(ROOT/'scripts/mutex-layout-fixture.cpp').read_text()
        self.assertIn('extern "C" __declspec(dllexport) __declspec(noinline) std::uint32_t OpenGeulFixtureObserve',source)
        self.assertIn('observed = OpenGeulFixtureObserve(count)',source)
    def test_unclosed_process_rejects_and_cleans_private_files(self):
        self.runtime.close_error=True
        with self.assertRaises(RuntimeError) as caught:self.run_driver()
        self.assertTrue(caught.exception.callInspection['temporaryFilesRemoved'])
        self.assertFalse(caught.exception.callInspection['stages'][0]['handlesClosed'])
    def test_cleanup_failure_does_not_mask_primary(self):
        self.fixture_ok=False
        original=self.m.shutil.rmtree
        def fail(path):
            original(path)
            raise OSError('synthetic cleanup verification failure')
        with patch.object(self.m.shutil,'rmtree',side_effect=fail):
            with self.assertRaisesRegex(AssertionError,'Fixture disassembly') as caught:self.run_driver()
        self.assertEqual(caught.exception.callInspection['cleanupErrorType'],'OSError')
        self.assertFalse(caught.exception.callInspection['temporaryFilesRemoved'])
    def test_success_cleanup_failure_is_fatal(self):
        original=self.m.shutil.rmtree
        def fail(path):
            original(path)
            raise OSError('synthetic cleanup verification failure')
        with patch.object(self.m.shutil,'rmtree',side_effect=fail):
            with self.assertRaises(OSError) as caught:self.run_driver()
        self.assertFalse(caught.exception.callInspection['success'])
    def test_fixture_classifier_cannot_renew_original_work_budget(self):
        original=self.classify
        def late(*args,**kwargs):
            result=original(*args,**kwargs)
            self.clock.value=127
            return result
        self.classify=late
        with self.assertRaises(AssertionError):self.run_driver()
        self.assertEqual(len(self.runtime.processes),2)
        self.assertTrue(all(not p.exists() for p in self.runtime.folders))
    def test_inspected_target_tamper_rejected_before_parser(self):
        original=self.runtime.start
        def tamper(argv,folder):
            process=original(argv,folder)
            if process.index==1:(folder/'fixture.dll').write_bytes(b'changed')
            return process
        self.runtime.start=tamper
        with self.assertRaisesRegex(AssertionError,'Inspected input changed'):self.run_driver()
        self.assertEqual(self.calls,[])
    def test_dumpbin_admission_does_not_expand_to_x64_or_other_names(self):
        value={'path':str(self.tool),'bytes':self.tool.stat().st_size,
               'machine':0x8664,'sha256':'0'*64}
        with self.assertRaises(AssertionError):
            self.m.native_compiler_tools.validate_tool_pin(value,'x64','dumpbin.exe')
        with self.assertRaises(AssertionError):
            self.m.native_compiler_tools.validate_tool_pin(value,'x64','arbitrary.exe')
    def test_real_classifier_receives_complete_fixture_then_production(self):
        spec=importlib.util.spec_from_file_location('native_call_classifier_integration',ROOT/'scripts/mutex_call_classification.py')
        classifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(classifier)
        self.classify=classifier.parse_and_classify
        original=self.runtime.start
        def listing(argv,folder):
            process=original(argv,folder)
            if process.index:
                begin,count=(4096,8) if process.index==1 else (100192,25)
                rows=['nop']*count
                rows[1]='bl '+format(0x180000000+4200,'016X') if process.index==1 else 'blr x8'
                text='Dump of file private.dll\n'+''.join(f'{0x180000000+begin+4*i:016X}: {op}\n' for i,op in enumerate(rows))
                (folder/'query.stdout').write_text(text)
            return process
        self.runtime.start=listing
        result=self.run_driver()
        self.assertTrue(result['fixture']['fixtureValidated'])
        self.assertEqual(result['production']['instructionCount'],25)
        self.assertFalse(result['production']['attributionProved'])
        self.assertLess(len(json.dumps(result)),4096)
        self.assertNotIn('private.dll',json.dumps(result))
    def test_tool_mutated_during_query_is_rejected(self):
        original=self.runtime.start
        def tamper(argv,folder):
            process=original(argv,folder)
            if process.index==1:self.tool.write_bytes(self.tool.read_bytes()+b'changed')
            return process
        self.runtime.start=tamper
        with self.assertRaisesRegex(AssertionError,'Disassembler changed'):self.run_driver()
        self.assertFalse(self.calls)
    def test_final_cleanup_does_not_grant_success_after_original_deadline(self):
        original=self.m.shutil.rmtree
        def late(path):
            original(path)
            self.clock.value=130
        with patch.object(self.m.shutil,'rmtree',side_effect=late):
            with self.assertRaises(AssertionError) as caught:self.run_driver()
        self.assertTrue(caught.exception.callInspection['temporaryFilesRemoved'])
        self.assertFalse(caught.exception.callInspection['success'])
    def test_classifier_reason_is_retained_without_private_output(self):
        spec=importlib.util.spec_from_file_location('native_failure_classifier',ROOT/'scripts/mutex_call_classification.py')
        classifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(classifier)
        self.classify=classifier.parse_and_classify
        self.output=b'private/path/unrecognized disassembly'
        with self.assertRaises(classifier.ClassificationError) as caught:self.run_driver()
        receipt=caught.exception.callInspection
        self.assertEqual(receipt['classificationReason'],'unsupported-output-line')
        self.assertNotIn('private/path',json.dumps(receipt))
        self.assertTrue(receipt['temporaryFilesRemoved'])
    def test_forged_reason_cannot_disclose_private_text(self):
        def forged(*args,**kwargs):
            error=ValueError('private/path')
            error.reason_code='private/path'
            raise error
        self.classify=forged
        with self.assertRaises(ValueError) as caught:self.run_driver()
        self.assertNotIn('private/path',json.dumps(caught.exception.callInspection))
        self.assertNotIn('classificationReason',caught.exception.callInspection)
    def test_fixture_more_than25_rows_rejected_before_native_launch(self):
        with self.assertRaises(AssertionError):self.run_driver(fixture_size=104)
        self.assertEqual(self.runtime.processes,[])
