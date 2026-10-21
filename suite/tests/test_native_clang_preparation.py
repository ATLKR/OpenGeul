"""Portable native-EXE/explicit LLVM preparation tests; no compiler is run."""
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_ascii_message_preparation as base


TOOL_HELPER = Path(__file__).resolve().parents[1] / 'e2e/native_compiler_tools.py'


def executable(machine=0x8664, *, characteristics=2, magic=0x20b, clr=False):
    raw = bytearray(64 + 24 + 240 + 128)
    raw[:2] = b'MZ'
    struct.pack_into('<I', raw, 60, 64)
    raw[64:68] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', raw, 68, machine, 1, 0, 0, 0, 240, characteristics)
    struct.pack_into('<H', raw, 88, magic)
    struct.pack_into('<I', raw, 88 + 108, 16)
    if clr: struct.pack_into('<II', raw, 88 + 112 + 14 * 8, 4096, 72)
    return bytes(raw)


class NativeCompilerToolTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL_HELPER.is_file(), 'bounded native compiler helper missing')
        spec = importlib.util.spec_from_file_location('native_compiler_tools_tested', TOOL_HELPER)
        self.tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tools)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name).resolve() / 'clang-cl.exe'
        self.path.write_bytes(executable())

    def pin(self, architecture='x64', check=lambda: None, **kwargs):
        return self.tools.pin_native_tool(self.path, architecture, check=check, **kwargs)

    def test_stable_windows_path_and_fd_ctime_difference_is_valid(self):
        original = os.fstat
        def fd_stat(fd):
            value = original(fd)
            fields = {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            fields['st_ctime_ns'] += 123456700
            return SimpleNamespace(**fields)
        with patch.object(self.tools.os, 'fstat', side_effect=fd_stat):
            value = self.pin()
        self.assertEqual(value['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_same_held_fd_metadata_mutation_is_rejected(self):
        original, calls = os.fstat, []
        def fd_stat(fd):
            value = original(fd)
            calls.append(fd)
            fields = {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            if len(calls) == 2: fields['st_mtime_ns'] += 1
            return SimpleNamespace(**fields)
        facts = {}
        with patch.object(self.tools.os, 'fstat', side_effect=fd_stat):
            with self.assertRaisesRegex(AssertionError, 'held FD changed'):
                self.pin(facts=facts)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(facts['fdBefore']['st_mtime_ns'], facts['fdAfter']['st_mtime_ns'])

    def test_same_path_metadata_mutation_is_rejected(self):
        original, calls = Path.stat, []
        def path_stat(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == self.path and not kwargs.get('follow_symlinks') is False:
                calls.append(True)
                if len(calls) == 3:
                    fields = {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
                    fields['st_ino'] += 1
                    return SimpleNamespace(**fields)
            return value
        facts = {}
        with patch.object(Path, 'stat', path_stat):
            with self.assertRaisesRegex(AssertionError, 'path changed'):
                self.pin(facts=facts)
        self.assertNotEqual(facts['pathBefore']['st_ino'], facts['pathAfter']['st_ino'])

    def test_stable_fd_size_must_match_path_and_streamed_bytes(self):
        original = os.fstat
        def fd_stat(fd):
            value = original(fd)
            fields = {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            fields['st_size'] += 1
            return SimpleNamespace(**fields)
        facts = {}
        with patch.object(self.tools.os, 'fstat', side_effect=fd_stat):
            with self.assertRaisesRegex(AssertionError, 'streamed bytes'):
                self.pin(facts=facts)
        self.assertEqual(set(facts), {'pathBefore', 'fdBefore', 'fdAfter', 'pathAfter'})
        self.assertEqual(facts['fdBefore'], facts['fdAfter'])

    def test_final_path_snapshot_crossing_original_deadline_keeps_facts_and_rejects_pin(self):
        original, calls, expired = Path.stat, [], False
        def path_stat(path, *args, **kwargs):
            nonlocal expired
            value = original(path, *args, **kwargs)
            if path == self.path and not kwargs.get('follow_symlinks') is False:
                calls.append(True)
                if len(calls) == 3: expired = True
            return value
        def check():
            if expired: raise TimeoutError('original deadline after path snapshot')
        facts = {}
        with patch.object(Path, 'stat', path_stat):
            with self.assertRaisesRegex(TimeoutError, 'after path snapshot'):
                self.pin(check=check, facts=facts)
        self.assertEqual(set(facts), {'pathBefore', 'fdBefore', 'fdAfter', 'pathAfter'})
        self.assertTrue(all(type(v) is int for row in facts.values() for v in row.values()))

    def test_native_executable_pin_has_exact_hash_size_and_host_machine(self):
        value = self.pin()
        self.assertEqual(value, dict(path=str(self.path), bytes=self.path.stat().st_size,
                                    sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(), machine=0x8664))
        self.tools.validate_tool_pin(value, 'x64', 'clang-cl.exe')

    def test_arm64_requires_native_aa64_host_executable(self):
        self.path.write_bytes(executable(0xaa64))
        self.assertEqual(self.pin('arm64')['machine'], 0xaa64)
        with self.assertRaises(AssertionError): self.pin('x64')

    def test_wrong_host_arm64ec_dll_managed_and_non_executable_are_rejected(self):
        for raw in (executable(0xa641), executable(0xaa64), executable(characteristics=0x2002),
                    executable(characteristics=0), executable(magic=0x10b), executable(clr=True)):
            with self.subTest(header=raw[68:70]):
                self.path.write_bytes(raw)
                with self.assertRaises(AssertionError): self.pin()

    def test_large_tools_stream_beyond_old_eight_mib_output_cap(self):
        with self.path.open('ab') as stream: stream.write(b'x' * (9 * 1024 * 1024))
        checks = []
        value = self.pin(check=lambda: checks.append(True))
        self.assertGreater(value['bytes'], 8 * 1024 * 1024)
        self.assertGreater(len(checks), 12)
        self.assertEqual(value['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_tool_size_cap_remains_distinct_and_fail_closed(self):
        with patch.object(self.tools, 'MAX_TOOL_BYTES', 100):
            with self.assertRaisesRegex(AssertionError, 'bound'): self.pin()

    def test_original_budget_guard_aborts_tool_read(self):
        calls = []
        def expired():
            calls.append(True)
            if len(calls) == 3: raise TimeoutError('original work deadline')
        with self.assertRaisesRegex(TimeoutError, 'original work'): self.pin(check=expired)

    def test_original_deadline_crossed_during_final_validation_rejects_pin(self):
        expired = False
        original = self.tools.validate_tool_pin
        def validate(*args):
            nonlocal expired
            original(*args)
            expired = True
        def check():
            if expired: raise TimeoutError('original work deadline after validation')
        with patch.object(self.tools, 'validate_tool_pin', side_effect=validate):
            with self.assertRaisesRegex(TimeoutError, 'after validation'):
                self.pin(check=check)

    def test_tool_changed_during_admission_is_rejected(self):
        calls = []
        def changed():
            calls.append(True)
            if len(calls) == 3:
                with self.path.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(AssertionError, 'changed'): self.pin(check=changed)

    def test_rehashed_pin_cannot_impersonate_host_or_tool_name(self):
        value = self.pin()
        for change in (dict(machine=0xaa64), dict(bytes=True), dict(sha256='f'), dict(path=str(self.path.with_name('link.exe')))):
            with self.subTest(change=change):
                with self.assertRaises(AssertionError):
                    self.tools.validate_tool_pin(dict(value, **change), 'x64', 'clang-cl.exe')


class NativeClangPreparationTests(unittest.TestCase):
    prepare = base.PreparationTests.prepare
    proof = base.PreparationTests.proof
    mutate = base.PreparationTests.mutate

    def setUp(self):
        base.PreparationTests.setUp(self)
        self.assertIn('compiler_mode', inspect.signature(base.m.prepare_observer).parameters,
                      'explicit experimental compiler mode missing')
        self.bin = self.root / 'Program Files/LLVM/bin'
        self.bin.mkdir(parents=True)
        for name in ('clang-cl.exe', 'lld-link.exe'):
            (self.bin / name).write_bytes(executable())
        patcher = patch.dict(os.environ, {'ProgramFiles': str(self.root / 'Program Files')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def clang(self, architecture='x64'):
        return base.m.prepare_observer(self.output, architecture=architecture, compiler_mode='clang-lld')

    def test_explicit_clang_and_lld_use_same_original_compile_job_without_msvc_fallback(self):
        descriptor = self.clang()
        text = (self.output / 'compile.cmd').read_text()
        self.assertIn('"%~7"', text)
        self.assertIn('"%~8"', text)
        self.assertIn('/c ', text)
        self.assertIn('/DLL /MACHINE:X64', text)
        self.assertNotIn('\ncl.exe ', text)
        self.assertNotIn('\nlink.exe ', text)
        self.assertEqual(self.runtime.processes[1].argv[-2:], [str(self.bin / 'clang-cl.exe'), str(self.bin / 'lld-link.exe')])
        proof = self.proof()
        self.assertEqual(proof['compiler']['mode'], 'clang-lld')
        self.assertEqual(proof['compiler']['before'], proof['compiler']['after'])
        self.assertEqual([row['stage'] for row in proof['stages']], ['discovery', 'compile'])
        self.assertEqual((proof['deadline'], proof['workDeadline']), (130., 127.))
        self.assertEqual(len(self.runtime.processes), 2)
        self.assertEqual(base.m.require_prepared_library(descriptor), self.output / 'ascii-message-observer.dll')

    def test_arm64_uses_native_tools_and_explicit_aarch64_target(self):
        self.native.update(nativeMachine=0xaa64, processArchitecture='arm64', nativeArchitecture='arm64')
        self.runtime.machine = 0xaa64
        for file in self.bin.iterdir(): file.write_bytes(executable(0xaa64))
        self.clang('arm64')
        text = (self.output / 'compile.cmd').read_text()
        self.assertIn('--target=aarch64-pc-windows-msvc', text)
        self.assertIn('/DLL /MACHINE:ARM64', text)
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))

    def test_default_msvc_does_not_consult_llvm_installation(self):
        for file in self.bin.iterdir(): file.unlink()
        self.prepare()
        self.assertNotIn('compiler', self.proof())
        self.assertIn('\ncl.exe ', (self.output / 'compile.cmd').read_text())

    def test_missing_or_emulated_llvm_is_fatal_without_msvc_fallback(self):
        (self.bin / 'clang-cl.exe').write_bytes(executable(0xaa64))
        with self.assertRaises(AssertionError): self.clang()
        self.assertFalse(self.proof()['success'])
        self.assertFalse(any(p.index == 1 for p in self.runtime.processes))

    def test_tool_changed_by_compile_stage_prevents_prepared_descriptor(self):
        original = self.runtime.start
        def start(argv, folder):
            process = original(argv, folder)
            if process.index == 1:
                with (self.bin / 'lld-link.exe').open('ab') as stream: stream.write(b'drift')
            return process
        self.runtime.start = start
        with self.assertRaisesRegex(AssertionError, 'changed'): self.clang()
        self.assertFalse(self.proof()['success'])
        self.assertTrue(all(p.closed for p in self.runtime.processes))

    def test_rehashed_compiler_receipt_cannot_accept_wrong_host_pin(self):
        descriptor = self.clang()
        def corrupt(proof):
            for phase in ('before', 'after'):
                proof['compiler'][phase]['clang-cl.exe']['machine'] = 0xaa64
            descriptor['compiler'] = proof['compiler']
        self.mutate(descriptor, corrupt)
        with self.assertRaises(AssertionError): base.m.require_prepared_library(descriptor)

    def test_failed_preparation_retains_bounded_raw_same_api_stat_facts(self):
        original, calls = os.fstat, []
        def fd_stat(fd):
            value = original(fd)
            calls.append(fd)
            fields = {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            if len(calls) == 2: fields['st_mtime_ns'] += 1
            return SimpleNamespace(**fields)
        with patch.object(os, 'fstat', side_effect=fd_stat):
            with self.assertRaisesRegex(AssertionError, 'held FD changed'): self.clang()
        proof = self.proof()
        self.assertFalse(proof['success'])
        self.assertEqual([row['stage'] for row in proof['stages']], ['discovery'])
        self.assertEqual(proof['compilerStatFacts']['after'], {})
        self.assertEqual(set(proof['compilerStatFacts']['before']), {'clang-cl.exe'})
        facts = proof['compilerStatFacts']['before']['clang-cl.exe']
        self.assertEqual(set(facts), {'pathBefore', 'fdBefore', 'fdAfter'})
        self.assertNotEqual(facts['fdBefore']['st_mtime_ns'], facts['fdAfter']['st_mtime_ns'])
        for row in facts.values():
            self.assertEqual(set(row), {'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'})
            self.assertTrue(all(type(v) is int and v.bit_length() <= 256 for v in row.values()))
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))

    def test_new_mode_keeps_original_nonempty_job_timeout_and_owned_cleanup(self):
        self.runtime.states[1] = [(0, 1, 0)]
        with self.assertRaisesRegex(AssertionError, 'deadline'): self.clang()
        self.assertFalse(self.proof()['success'])
        self.assertTrue(self.proof()['stages'][1]['forcedOwnedJobCleanup'])
        self.assertEqual(self.proof()['stages'][1]['cleanupLastSample']['activeProcesses'], 0)
        self.assertTrue(all(p.closed for p in self.runtime.processes))


if __name__ == '__main__':
    unittest.main()
