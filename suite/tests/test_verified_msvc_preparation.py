"""Portable verified MSVC cohort policy: real file/PE pins, synthetic Job execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

import test_ascii_message_preparation as base
import test_native_clang_preparation as clang
import native_compiler_tools as tools


class VerifiedMsvcTests(unittest.TestCase):
    setUp = base.PreparationTests.setUp
    prepare = base.PreparationTests.prepare
    proof = base.PreparationTests.proof
    mutate = base.PreparationTests.mutate

    def tool(self, name='cl.exe'):
        return self.install / 'VC/Tools/MSVC/14.50.35717/bin/Hostx64/x64' / name

    def version(self):
        return self.install / 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'

    def change_during_compile(self, callback):
        original = self.runtime.start
        def start(argv, folder):
            process = original(argv, folder)
            if process.index == 1: callback()
            return process
        self.runtime.start = start

    def assert_precompile_rejected(self):
        with self.assertRaises((AssertionError, FileNotFoundError)): self.prepare()
        self.assertEqual(len(self.runtime.processes), 1)
        self.assertTrue(self.runtime.processes[0].closed)
        self.assertFalse(self.proof()['success'])

    def test_msvc_producer_and_consumer_require_selection_and_native_tool_witness(self):
        descriptor = self.prepare()
        compiler = descriptor.get('compiler', {})
        self.assertEqual(compiler.get('mode'), 'msvc')
        self.assertEqual(compiler['before'], compiler['after'])
        self.assertEqual(set(compiler['before']), {'cl.exe', 'link.exe'})
        selection = compiler['selection']
        self.assertEqual(selection['installationRoot'], str(self.install))
        self.assertEqual(selection['toolsetVersion'], '14.50.35717')
        self.assertEqual(selection['architecture'], 'x64')
        for name in ('cl.exe', 'link.exe'):
            self.assertEqual(compiler['before'][name]['path'], str(self.tool(name)))
            self.assertEqual(compiler['before'][name]['sha256'], hashlib.sha256(self.tool(name).read_bytes()).hexdigest())
            for phase in ('before', 'after'):
                self.assertEqual(set(self.proof()['compilerStatFacts'][phase][name]), {'pathBefore','fdBefore','fdAfter','pathAfter'})
        self.assertEqual(self.runtime.processes[1].argv[-2:], [str(self.tool()), str(self.tool('link.exe'))])
        script = (self.output/'compile.cmd').read_text()
        self.assertIn(' x64 -vcvars_ver=14.50.35717 >', script)
        self.assertIn('"%~7" /nologo /c ', script)
        self.assertIn('"%~8" /NOLOGO /DLL /MACHINE:X64', script)
        self.assertNotIn('\ncl.exe ', script)
        self.assertNotIn('\nlink.exe ', script)
        self.assertEqual(base.m.require_prepared_library(descriptor), self.output/'ascii-message-observer.dll')
        self.assertEqual((self.proof()['workDeadline'], self.proof()['deadline']), (127.,130.))
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))

    def test_missing_version_rejects_before_compile(self):
        self.version().unlink()
        self.assert_precompile_rejected()

    def test_version_is_numeric_fixed_topology_not_command_text(self):
        self.version().write_bytes(b'14.50.35717 & exit /b 0')
        self.assert_precompile_rejected()

    def test_oversized_version_rejects_before_compile(self):
        self.version().write_bytes(b'1'*129)
        self.assert_precompile_rejected()

    def test_missing_exact_link_rejects_before_compile(self):
        self.tool('link.exe').unlink()
        self.assert_precompile_rejected()

    def test_linked_vs_root_rejects_before_compile(self):
        alias = self.root/'alias'
        alias.symlink_to(self.install, target_is_directory=True)
        self.install = alias
        self.assert_precompile_rejected()

    def test_wrong_host_rejects_before_compile(self):
        self.tool().write_bytes(clang.executable(0xaa64))
        self.assert_precompile_rejected()

    def test_dll_or_managed_compiler_rejects_before_compile(self):
        for image in (clang.executable(characteristics=0x2002), clang.executable(clr=True)):
            self.tool().write_bytes(image)
            if self.output.exists():
                import shutil
                shutil.rmtree(self.output)
                self.runtime.processes.clear()
            self.assert_precompile_rejected()

    def test_tool_drift_rejects_after_compile_and_closes_original_jobs(self):
        self.change_during_compile(lambda: self.tool('link.exe').write_bytes(clang.executable()+b'drift'))
        with self.assertRaisesRegex(AssertionError, 'changed'): self.prepare()
        self.assertFalse(self.proof()['success'])
        self.assertTrue(all(p.closed for p in self.runtime.processes))
        self.assertEqual(len(self.runtime.processes), 2)

    def test_selection_file_drift_during_compile_rejects(self):
        self.change_during_compile(lambda: self.version().write_bytes(b'14.50.35718'))
        with self.assertRaises(AssertionError): self.prepare()
        self.assertFalse(self.proof()['success'])
        self.assertTrue(all(p.closed for p in self.runtime.processes))

    def test_msvc_failure_is_one_original_compile_without_fallback(self):
        self.runtime.states[1]=[(0,0,1)]
        with self.assertRaisesRegex(AssertionError, 'compiler stage failed'): self.prepare()
        self.assertEqual(len(self.runtime.processes),2)
        self.assertTrue(all(p.closed for p in self.runtime.processes))
        self.assertEqual(self.proof().get('compiler',{}).get('mode'),'msvc')

    def test_consumer_rejects_legacy_unwitnessed_descriptor(self):
        descriptor=self.prepare()
        descriptor.pop('compiler',None)
        self.mutate(descriptor, lambda proof: proof.pop('compiler',None))
        with self.assertRaises((AssertionError,KeyError)): base.m.require_prepared_library(descriptor)

    def corrupt_compiler(self, callback):
        descriptor=self.prepare()
        def change(proof):
            self.assertIn('compiler',proof)
            callback(proof['compiler'])
            descriptor['compiler']=proof['compiler']
        self.mutate(descriptor,change)
        with self.assertRaises((AssertionError,KeyError)): base.m.require_prepared_library(descriptor)

    def test_consumer_missing_selection_fails_closed(self):
        self.corrupt_compiler(lambda compiler: compiler.pop('selection',None))

    def test_consumer_unchanged_hash_outside_selected_vs_is_rejected(self):
        def corrupt(compiler):
            for phase in ('before','after'): compiler[phase]['cl.exe']['path']=str(self.root/'cl.exe')
        self.corrupt_compiler(corrupt)

    def test_consumer_host_and_beforeafter_mismatch_rejected(self):
        self.corrupt_compiler(lambda compiler: compiler['before']['cl.exe'].update(machine=0xaa64))

    def test_consumer_selection_current_files_must_match(self):
        descriptor=self.prepare()
        self.version().write_bytes(b'14.50.35718')
        with self.assertRaises(AssertionError): base.m.require_prepared_library(descriptor)

    def test_consumer_rehashed_changed_recipe_rejected(self):
        descriptor=self.prepare()
        script=self.output/'compile.cmd'
        script.write_text(script.read_text().replace('/W4','/W0'))
        self.mutate(descriptor,lambda proof: proof['outputs'].update({'compile.cmd':base.m._pin(script)}))
        with self.assertRaises(AssertionError): base.m.require_prepared_library(descriptor)

    def test_consumer_stat_sizes_must_correlate_with_the_tool_hash_witness(self):
        descriptor=self.prepare()
        def change(proof):
            for phase in ('before','after'):
                for snap in proof['compilerStatFacts'][phase]['cl.exe'].values(): snap['st_size']+=1
        self.mutate(descriptor,change)
        with self.assertRaises(AssertionError): base.m.require_prepared_library(descriptor)

    def test_consumer_missing_stat_witness_fails_closed(self):
        descriptor=self.prepare()
        self.mutate(descriptor,lambda proof: proof.pop('compilerStatFacts'))
        with self.assertRaises((AssertionError,KeyError)): base.m.require_prepared_library(descriptor)

    def test_vcvars_drift_during_compile_rejects(self):
        self.change_during_compile(lambda: (self.version().parent/'vcvarsall.bat').write_bytes(b'changed'))
        with self.assertRaises(AssertionError): self.prepare()
        self.assertFalse(self.proof()['success'])
        self.assertTrue(all(p.closed for p in self.runtime.processes))

    def test_msvc_mode_rejects_an_llvm_tool_even_when_native(self):
        path=self.tool().with_name('clang-cl.exe');path.write_bytes(clang.executable())
        with self.assertRaises(AssertionError): tools.pin_native_tool(path,'x64',check=lambda:None,compiler_mode='msvc')

    def test_msvc_names_never_enter_default_llvm_allowlist(self):
        with self.assertRaises(AssertionError): tools.pin_native_tool(self.tool(),'x64',check=lambda:None)
        with self.assertRaises(AssertionError): tools.validate_tool_pin(dict(path=str(self.tool()),bytes=200,sha256='0'*64,machine=0x8664),'x64','cl.exe')


class CohortSelectionTests(unittest.TestCase):
    def load_editor(self):
        spec=importlib.util.spec_from_file_location('verified_msvc_editor',Path(__file__).resolve().parents[1]/'e2e/ascii_editor_input.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_shared_x64_explicitly_selects_vs_bundled_clang_before_one_delegate_call(self):
        editor=self.load_editor(); backend=ModuleType('ascii_message_preparation'); calls=[]
        def prepare(folder,**kwargs):
            calls.append((folder,kwargs)); raise RuntimeError('synthetic compiler failure')
        backend.prepare_observer=prepare
        budget=object()
        with patch.dict(sys.modules,{'ascii_message_preparation':backend}):
            with self.assertRaises(RuntimeError): editor.prepare_observer(Path('/fixed/output'),architecture='x64',budget=budget)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1],dict(architecture='x64',budget=budget,compiler_mode='vs-bundled-clang'))

    def test_shared_arm_preserves_llvm_and_same_budget(self):
        editor=self.load_editor(); backend=ModuleType('ascii_message_preparation'); calls=[]
        backend.prepare_observer=lambda folder,**kwargs:calls.append(kwargs) or 7
        budget=object()
        with patch.dict(sys.modules,{'ascii_message_preparation':backend}):
            self.assertEqual(editor.prepare_observer(Path('/fixed/output'),architecture='arm64',budget=budget),7)
        self.assertEqual(calls,[dict(architecture='arm64',budget=budget)])


if __name__=='__main__': unittest.main()
