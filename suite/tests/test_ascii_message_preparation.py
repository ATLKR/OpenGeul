"""Portable private-Job/preparation policy tests; never compile or probe Windows."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'e2e'))
SPEC = importlib.util.spec_from_file_location('ascii_preparation_tests', ROOT / 'e2e/ascii_message_preparation.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def pe(machine):
    raw = bytearray(64 + 24 + 112)
    raw[:2] = b'MZ'
    struct.pack_into('<I', raw, 60, 64)
    raw[64:68] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', raw, 68, machine, 1, 0, 0, 0, 112, 0x2000)
    struct.pack_into('<H', raw, 88, 0x20b)
    return bytes(raw)


class Clock:
    value = 100.
    def __call__(self): return self.value
    def sleep(self, seconds): self.value += seconds


class Runtime:
    def __init__(self, case):
        self.case = case
        self.processes = []
        self.states = [[(0, 0, 0)], [(0, 0, 0)]]
        self.close_error = False
        self.query_error = False
        self.late = False
        self.machine = 0x8664

    def start(self, argv, folder):
        index = len(self.processes)
        case = self.case
        process = SimpleNamespace(handle=40 + index, job=60 + index, pid=80 + index,
                                  index=index, forced=False, closed=False, queries=0, argv=argv)
        def terminate(): process.forced = True
        def close():
            process.closed = True
            process.handle = process.job = None
            if self.close_error: raise RuntimeError('close failed')
        process.terminate, process.close = terminate, close
        self.processes.append(process)
        if index == 0:
            (folder / 'discovery.stdout').write_bytes(str(case.install).encode())
            (folder / 'discovery.stderr').write_bytes(b'')
        else:
            (folder / 'ascii-message-observer.dll').write_bytes(pe(self.machine))
            (folder / 'compiler.stdout').write_bytes(b'compile output')
            (folder / 'compiler.stderr').write_bytes(b'')
        return process

    def identity(self, process):
        return dict(pid=process.pid, processHandle=process.handle, jobHandle=process.job,
                    image='native-compiler-test.exe', creationTime=134370233752663598)

    def current(self, process):
        if process.forced: return (0, 0, 1)
        states = self.states[process.index]
        return states[min(process.queries, len(states) - 1)]

    def root(self, process):
        wait, _, code = self.current(process)
        return dict(waitResult=wait, exitCode=code)

    def census(self, process):
        _, active, _ = self.current(process)
        process.queries += 1
        raw = bytearray(48)
        struct.pack_into('<III', raw, 36, 2, active, 0)
        if self.late and not process.forced: self.case.clock.value = 127.
        return dict(querySucceeded=not self.query_error, lastError=5 if self.query_error else 0,
                    returnLength=48, activeProcesses=active, totalProcesses=2, terminatedProcesses=0,
                    rawHex=raw.hex())


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        for name in m.SOURCES: (self.source / name).write_bytes(('fixed ' + name).encode())
        self.programs = self.root / 'programs'
        vswhere = self.programs / 'Microsoft Visual Studio/Installer/vswhere.exe'
        vswhere.parent.mkdir(parents=True)
        vswhere.write_bytes(b'fixture')
        self.install = self.root / 'VS'
        vcvars = self.install / 'VC/Auxiliary/Build/vcvarsall.bat'
        vcvars.parent.mkdir(parents=True)
        vcvars.write_bytes(b'fixture')
        self.output = self.root / 'output'
        self.clock = Clock()
        self.runtime = Runtime(self)
        self.native = dict(processMachine=0, nativeMachine=0x8664,
                           processArchitecture='x64', nativeArchitecture='x64')
        for patcher in (patch.object(m, 'SOURCE_ROOT', self.source),
                        patch.object(m, '_Runtime', return_value=self.runtime),
                        patch.object(m.time, 'monotonic', self.clock),
                        patch.object(m.time, 'sleep', self.clock.sleep),
                        patch.object(m.native_arch, 'observe_native_architecture', side_effect=lambda: self.native),
                        patch.dict(os.environ, {'ProgramFiles(x86)': str(self.programs)})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepare(self, architecture='x64'):
        return m.prepare_observer(self.output, architecture=architecture)

    def proof(self): return json.loads((self.output / 'preparation.json').read_bytes())

    def mutate(self, descriptor, callback):
        value = self.proof()
        callback(value)
        raw = (json.dumps(value) + '\n').encode()
        path = self.output / 'preparation.json'
        path.write_bytes(raw)
        descriptor['preparationReceipt'].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def test_success_requires_two_naturally_empty_jobs_and_pins_every_output(self):
        descriptor = self.prepare()
        self.assertEqual(m.require_prepared_library(descriptor), self.output / 'ascii-message-observer.dll')
        proof = self.proof()
        self.assertEqual([row['stage'] for row in proof['stages']], ['discovery', 'compile'])
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))
        self.assertEqual(proof['deadline'] - proof['startedAt'], 30.)
        self.assertEqual(proof['workDeadline'], proof['deadline'] - 3.)
        self.assertIn('compiler.stderr', proof['outputs'])
        self.assertEqual(proof['stages'][0]['identity']['creationTime'], 134370233752663598)

    def test_arm64_uses_arm64_environment_and_native_dll(self):
        self.native.update(nativeMachine=0xaa64, processArchitecture='arm64', nativeArchitecture='arm64')
        self.runtime.machine = 0xaa64
        descriptor = self.prepare('arm64')
        self.assertIn(' arm64 >', (self.output / 'compile.cmd').read_text())
        self.assertIn('/MACHINE:ARM64', (self.output / 'compile.cmd').read_text())
        m.require_prepared_library(descriptor, architecture='arm64')

    def test_root_exit_without_empty_job_waits_read_only_under_original_budget(self):
        self.runtime.states[0] = [(0, 1, 0), (0, 1, 0), (0, 0, 0)]
        self.prepare()
        stage = self.proof()['stages'][0]
        self.assertEqual(stage['queryCount'], 3)
        self.assertEqual([s['activeProcesses'] for s in stage['samples']], [1, 1, 0])
        self.assertEqual(len(self.runtime.processes), 2)
        self.assertTrue(all(not p.forced for p in self.runtime.processes))

    def test_running_root_even_with_empty_census_cannot_succeed(self):
        self.runtime.states[0] = [(258, 0, None)]
        with self.assertRaisesRegex(AssertionError, 'deadline'): self.prepare()
        self.assertFalse(self.proof()['success'])
        self.assertEqual(len(self.runtime.processes), 1)
        self.assertTrue(self.runtime.processes[0].forced)

    def test_nonempty_job_timeout_only_terminates_its_retained_private_job(self):
        self.runtime.states[0] = [(0, 1, 0)]
        with self.assertRaisesRegex(AssertionError, 'deadline'): self.prepare()
        stage = self.proof()['stages'][0]
        self.assertTrue(stage['forcedOwnedJobCleanup'])
        self.assertTrue(self.runtime.processes[0].closed)
        self.assertEqual(len(stage['samples']), 64)
        self.assertEqual(stage['droppedSamples'], stage['queryCount'] - 64)

    def test_zero_observed_after_deadline_is_retained_but_never_success(self):
        self.runtime.late = True
        with self.assertRaisesRegex(AssertionError, 'deadline'): self.prepare()
        stage = self.proof()['stages'][0]
        self.assertEqual(stage['samples'][-1]['activeProcesses'], 0)
        self.assertEqual(stage['samples'][-1]['observedAt'], 127.)
        self.assertFalse(stage['natural'])

    def test_query_error_is_fatal_even_if_raw_active_field_is_zero(self):
        self.runtime.query_error = True
        with self.assertRaisesRegex(AssertionError, 'accounting'): self.prepare()
        self.assertFalse(self.proof()['stages'][0]['samples'][0]['querySucceeded'])

    def test_nonzero_stage_exit_stops_before_compile_and_preserves_failure(self):
        self.runtime.states[0] = [(0, 0, 3)]
        self.runtime.close_error = True
        with self.assertRaisesRegex(AssertionError, 'compiler stage failed'): self.prepare()
        self.assertEqual(len(self.runtime.processes), 1)
        self.assertEqual(self.proof()['error']['type'], 'AssertionError')
        self.assertEqual(self.proof()['stages'][0]['cleanupErrors'][0]['message'], 'close failed')

    def test_successful_root_and_job_do_not_hide_handle_close_failure(self):
        self.runtime.close_error = True
        with self.assertRaisesRegex(RuntimeError, 'close failed'): self.prepare()
        self.assertFalse(self.proof()['success'])
        self.assertFalse(self.proof()['stages'][0]['handlesClosed'])

    def test_wrong_native_dll_is_fatal_before_descriptor(self):
        self.runtime.machine = 0xaa64
        with self.assertRaisesRegex(AssertionError, 'architecture'): self.prepare()
        self.assertFalse(self.proof()['success'])

    def test_foreign_controller_architecture_never_starts_compiler(self):
        self.native['processMachine'] = 0x8664
        with self.assertRaisesRegex(AssertionError, 'architecture'): self.prepare()
        self.assertEqual(self.runtime.processes, [])

    def test_preparation_cannot_repeat_or_reuse_existing_folder(self):
        self.prepare()
        with self.assertRaises(FileExistsError): self.prepare()
        self.assertEqual(len(self.runtime.processes), 2)

    def test_changed_source_or_header_refuses_reuse(self):
        descriptor = self.prepare()
        for name in m.SOURCES:
            original = (self.source / name).read_bytes()
            (self.source / name).write_bytes(b'changed')
            with self.assertRaisesRegex(AssertionError, 'source changed'): m.require_prepared_library(descriptor)
            (self.source / name).write_bytes(original)

    def test_changed_dll_refuses_reuse_even_with_valid_pe_header(self):
        descriptor = self.prepare()
        path = self.output / 'ascii-message-observer.dll'
        path.write_bytes(path.read_bytes() + b'drift')
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_rehashed_boolean_only_success_without_zero_census_is_rejected(self):
        descriptor = self.prepare()
        self.mutate(descriptor, lambda p: p['stages'][1]['samples'][-1].update(activeProcesses=1))
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_rehashed_raw_accounting_disagreement_is_rejected(self):
        descriptor = self.prepare()
        self.mutate(descriptor, lambda p: p['stages'][1]['samples'][-1].update(rawHex='00' * 48))
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_rehashed_forced_cleanup_can_never_become_natural_success(self):
        descriptor = self.prepare()
        self.mutate(descriptor, lambda p: p['stages'][0].update(forcedOwnedJobCleanup=True))
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_rehashed_late_success_is_rejected(self):
        descriptor = self.prepare()
        self.mutate(descriptor, lambda p: p.update(finishedAt=p['workDeadline']))
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_rehashed_invalid_stage_order_is_rejected(self):
        descriptor = self.prepare()
        self.mutate(descriptor, lambda p: p['stages'].reverse())
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_rehashed_stage_timestamp_overlap_is_rejected(self):
        descriptor = self.prepare()
        self.mutate(descriptor, lambda p: p['stages'][1].update(startedAt=p['startedAt'] - 1))
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_output_log_drift_is_rejected(self):
        descriptor = self.prepare()
        (self.output / 'compiler.stdout').write_bytes(b'different')
        with self.assertRaisesRegex(AssertionError, 'output changed'): m.require_prepared_library(descriptor)

    def test_schema_boolean_cannot_impersonate_integer_version(self):
        descriptor = self.prepare()
        descriptor['schemaVersion'] = True
        with self.assertRaises(AssertionError): m.require_prepared_library(descriptor)

    def test_requested_architecture_must_equal_preparation(self):
        descriptor = self.prepare()
        with self.assertRaisesRegex(AssertionError, 'architecture differs'):
            m.require_prepared_library(descriptor, architecture='arm64')

    def test_linked_output_is_rejected_without_process_launch(self):
        link = self.root / 'linked'
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(AssertionError, 'Linked'):
            m.prepare_observer(link / 'output', architecture='x64')
        self.assertEqual(self.runtime.processes, [])

    def test_folder_preparation_cannot_renew_the_thirty_second_budget(self):
        original = Path.mkdir
        def delayed(folder, *args, **kwargs):
            original(folder, *args, **kwargs)
            if folder == self.output: self.clock.value += 30.
        with patch.object(Path, 'mkdir', delayed):
            with self.assertRaisesRegex(AssertionError, 'deadline'): self.prepare()
        self.assertEqual(self.runtime.processes, [])
        self.assertEqual(self.proof()['startedAt'], 100.)
        self.assertEqual(self.proof()['deadline'], 130.)
        self.assertFalse(self.proof()['success'])

    def test_receipt_write_failure_preserves_primary_compiler_failure(self):
        self.runtime.states[0] = [(0, 0, 3)]
        with patch.object(m, '_write_json', side_effect=OSError('receipt unavailable')):
            with self.assertRaisesRegex(AssertionError, 'compiler stage failed') as caught: self.prepare()
        self.assertEqual(caught.exception.preparationReceiptError,
                         dict(type='OSError', message='receipt unavailable'))
        self.assertTrue(self.runtime.processes[0].closed)

    def test_receipt_write_failure_on_otherwise_success_is_fatal(self):
        with patch.object(m, '_write_json', side_effect=OSError('receipt unavailable')):
            with self.assertRaisesRegex(OSError, 'receipt unavailable'): self.prepare()
        self.assertTrue(all(p.closed for p in self.runtime.processes))

    def test_ascii_scripts_pass_unicode_paths_as_wide_argv_without_console_codepage(self):
        self.output = self.root / '준비 결과'
        self.prepare()
        for name in ('discover.cmd', 'compile.cmd'):
            text = (self.output / name).read_text(encoding='utf-8')
            self.assertTrue(text.isascii())
            self.assertNotIn('chcp', text)
            self.assertNotIn('준비 결과', text)
        self.assertIn(' -utf8 -latest ', (self.output / 'discover.cmd').read_text())
        for process in self.runtime.processes:
            self.assertIn(process.argv[3], ('discover.cmd', 'compile.cmd'))
            self.assertTrue(any('준비 결과' in item for item in process.argv[4:]))
        self.assertIn('/OUT:"%~4"', (self.output / 'compile.cmd').read_text())


if __name__ == '__main__': unittest.main()
