"""Compile-only preparation contracts; fake owned processes never execute a DLL."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'e2e'))
from test_ascii_message_preparation import Clock, Runtime, pe
SCRIPT=ROOT/'scripts/prepare-mutex-fixture.py'

class MutexPreparationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'compile-only mutex fixture preparer missing')
        spec=importlib.util.spec_from_file_location('mutex_fixture_preparation',SCRIPT)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.output=self.root/'output';self.clock=Clock()
        self.install=self.root/'VS';vcvars=self.install/'VC/Auxiliary/Build/vcvarsall.bat'
        vcvars.parent.mkdir(parents=True);vcvars.write_bytes(b'fixture')
        programs=self.root/'programs';vswhere=programs/'Microsoft Visual Studio/Installer/vswhere.exe'
        vswhere.parent.mkdir(parents=True);vswhere.write_bytes(b'fixture')
        case=self
        class FakeRuntime(Runtime):
            def start(inner,argv,folder):
                process=super().start(argv,folder)
                if process.index==1:
                    (folder/'ascii-message-observer.dll').rename(folder/'mutex-layout-fixture.dll')
                return process
        self.runtime=FakeRuntime(self);self.runtime.machine=0xaa64
        self.native=dict(processMachine=0,nativeMachine=0xaa64,processArchitecture='arm64',nativeArchitecture='arm64')
        for p in (patch.object(self.m.shared,'_Runtime',return_value=self.runtime),
                  patch.object(self.m.shared.time,'monotonic',self.clock),
                  patch.object(self.m.shared.time,'sleep',self.clock.sleep),
                  patch.object(self.m.shared.native_arch,'observe_native_architecture',return_value=self.native),
                  patch.dict(os.environ,{'ProgramFiles(x86)':str(programs)})):
            p.start();self.addCleanup(p.stop)
    def run_prepare(self,architecture='arm64'):
        return self.m.prepare(self.output,architecture=architecture)
    def receipt(self):return json.loads((self.output/'receipt.json').read_bytes())
    def test_two_owned_jobs_native_dll_pins_and_sanitized_receipt(self):
        result=self.run_prepare();r=self.receipt()
        self.assertTrue(r['success']);self.assertEqual(result,self.output/'mutex-layout-fixture.dll')
        self.assertEqual(r['deadline']-r['startedAt'],30)
        self.assertEqual(r['workDeadline'],r['deadline']-3)
        self.assertEqual([s['stage'] for s in r['stages']],['discovery','compile'])
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))
        self.assertTrue(all(s['natural'] and s['handlesClosed'] for s in r['stages']))
        self.assertEqual(r['library']['machine'],0xaa64)
        self.assertIn('mutex-layout-fixture.cpp',r['sourcePins'])
        raw=(self.output/'receipt.json').read_text();self.assertNotIn(str(self.root),raw)
        self.assertNotIn('command',raw);self.assertNotIn('rawHex',raw)
    def test_original_deadline_forces_owned_cleanup_without_compile(self):
        self.runtime.late=True
        with self.assertRaises(AssertionError):self.run_prepare()
        self.assertEqual(len(self.runtime.processes),1)
        self.assertTrue(self.runtime.processes[0].forced and self.runtime.processes[0].closed)
        self.assertFalse(self.receipt()['success'])
    def test_wrong_architecture_rejected_before_launch(self):
        with self.assertRaises(AssertionError):self.run_prepare('x64')
        self.assertEqual(self.runtime.processes,[])
    def test_wrong_native_image_rejected(self):
        self.runtime.machine=0x8664
        with self.assertRaises(AssertionError):self.run_prepare()
        self.assertFalse(self.receipt()['success'])
        self.assertTrue(all(p.closed for p in self.runtime.processes))
    def test_nonzero_compile_exit_or_unclosed_handle_never_success(self):
        self.runtime.states[1]=[(0,0,1)]
        with self.assertRaises(AssertionError):self.run_prepare()
        self.assertFalse(self.receipt()['success'])
        self.assertTrue(self.runtime.processes[1].forced)
    def test_handle_close_failure_retained(self):
        self.runtime.close_error=True
        with self.assertRaises(RuntimeError):self.run_prepare()
        self.assertFalse(self.receipt()['success'])
        self.assertFalse(self.receipt()['stages'][0]['handlesClosed'])
    def test_accumulated_discovery_compile_time_never_resets_budget(self):
        real=self.runtime.census
        def timed(process):
            self.clock.value=126. if process.index==0 else (128. if not process.forced else 128.1)
            return real(process)
        self.runtime.census=timed
        with self.assertRaises(AssertionError):self.run_prepare()
        self.assertEqual(len(self.runtime.processes),2)
        self.assertTrue(self.runtime.processes[-1].forced and self.runtime.processes[-1].closed)
        self.assertEqual(self.receipt()['deadline'],130.)
        self.assertFalse(self.receipt()['success'])

    def test_changed_compilation_source_rejected(self):
        real=self.runtime.start
        def mutate(argv,folder):
            process=real(argv,folder)
            if process.index==1:(folder/'mutex-layout-fixture.cpp').write_bytes(b'changed')
            return process
        self.runtime.start=mutate
        with self.assertRaises(AssertionError):self.run_prepare()
        self.assertFalse(self.receipt()['success'])

    def test_receipt_completion_still_charged_to_total_budget(self):
        real=self.m.shared._write_json
        def late(path,value):
            real(path,value);self.clock.value=130.
        with patch.object(self.m.shared,'_write_json',late):
            with self.assertRaises(AssertionError):self.run_prepare()

    def test_failure_stage_and_log_hashes_without_raw_diagnostics(self):
        self.runtime.states[1]=[(0,0,1)]
        with self.assertRaises(AssertionError):self.run_prepare()
        proof=self.receipt()
        self.assertEqual(proof['errorStage'],'compile')
        self.assertIn('ascii_message_preparation.py',proof['sourcePins'])
        self.assertIn('compiler.stdout',proof['compilerLogPins'])
        self.assertEqual(proof['compilerLogPins']['compiler.stderr']['bytes'],0)
        self.assertNotIn('compile output',json.dumps(proof))

    def test_source_mirror_and_compile_no_icf_never_dll_execution(self):
        self.run_prepare();source=(self.output/'mutex-layout-fixture.cpp').read_text()
        base=source.split('class OpenGeulFixtureBase',1)[1].split('class OpenGeulFixtureMutex',1)[0]
        self.assertLess(base.index('~OpenGeulFixtureBase'),base.index('tryToAcquire'))
        self.assertLess(base.index('tryToAcquire'),base.index('IsCurrentThread'))
        self.assertLess(base.index('IsCurrentThread'),base.index('doRelease'))
        self.assertLess(base.index('doRelease'),base.index('doAcquire'))
        derived=source.split('class OpenGeulFixtureMutex',1)[1].split('};',1)[0]
        self.assertLess(derived.index('doAcquire'),derived.index('doRelease'))
        self.assertIn('__declspec(dllexport)',derived)
        script=(self.output/'compile.cmd').read_text()
        for flag in ('/GR','/OPT:NOICF','/MACHINE:ARM64','cl.exe',' arm64 '):self.assertIn(flag,script)
        self.assertIn(' /MD ',script)
        self.assertNotIn(' /MT ',script)
        self.assertTrue(all(p.argv[3] in ('discover.cmd','compile.cmd') for p in self.runtime.processes))

if __name__=='__main__':unittest.main()
