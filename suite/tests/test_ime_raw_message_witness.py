"""Bounded diagnostic transport checks, never native IME qualification."""
import ast
import ctypes
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'suite/e2e/ime_raw_message_witness.py'
sys.path.insert(0, str(ROOT / 'suite/e2e'))


def literal():
    tree = ast.parse((ROOT / 'suite/e2e/korean_ime_smoke.py').read_text())
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'OBSERVER_SOURCE' for t in n.targets))


class RawMessageWitnessTests(unittest.TestCase):
    def load(self):
        self.assertTrue(MODULE.is_file(), 'Raw diagnostic module is not implemented')
        spec = importlib.util.spec_from_file_location('raw_witness_under_test', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def binding(self):
        return dict(officePid=31, officeCreationTime=134372212912475013, shellPid=77,
                    shellCreationTime=134372212899129241, suiteHwnd=11, rootHwnd=11,
                    parentHwnd=12, childHwnd=22, expectedImage='C:\\suite\\soffice.bin')

    def test_generated_copy_reverses_without_touching_production(self):
        api = self.load()
        original = literal()
        generated, audit = api.instrument_source(original, 'Local\\Raw_0123456789abcdef', 2**63 + 9)
        self.assertEqual(api.remove_instrumentation(generated, 'Local\\Raw_0123456789abcdef', 2**63 + 9), original)
        self.assertEqual(audit['originalSourceSha256'], api.BASE_SOURCE_SHA256)
        self.assertEqual(audit['rawBytes'], 8256)
        self.assertIn('Event events[512]', generated)
        self.assertIn('if(code>=0 && wp==PM_REMOVE)', generated)
        self.assertEqual(original, literal())
        for value in (original + '\n', original * 2):
            with self.assertRaises(AssertionError):
                api.instrument_source(value, 'Local\\Raw_0123456789abcdef', 7)

    def test_invalid_mapping_and_nonce_never_generate_native_code(self):
        api = self.load()
        for name, nonce in [('Local\\bad"name', 1), ('Local\\Raw_0123456789abcdef', True),
                            ('Local\\Raw_0123456789abcdef', 0), ('Local\\Raw_0123456789abcdef', 2**64)]:
            with self.subTest(name=name, nonce=nonce), self.assertRaises((AssertionError, ValueError)):
                api.instrument_source(literal(), name, nonce)

    def test_sidecar_layout_and_full_native_widths(self):
        api = self.load()
        self.assertEqual((ctypes.sizeof(api.RawHeader), ctypes.sizeof(api.RawRow), ctypes.sizeof(api.RawBuffer)), (64, 64, 8256))
        expected = {'sequence': 0, 'hookKind': 4, 'nCode': 8, 'validBits': 12, 'hookWParam': 16,
                    'hwnd': 24, 'message': 32, 'msgTime': 36, 'wParam': 40, 'lParam': 48, 'ptX': 56, 'ptY': 60}
        self.assertEqual({n: getattr(api.RawRow, n).offset for n in expected}, expected)
        state = api.new_buffer(self.binding(), 41, 2**63 + 9)
        state.header.writerReady = 1
        state.header.reservedCount = 1
        row = state.rows[0]
        row.sequence, row.hookKind, row.validBits, row.hookWParam = 1, 2, 3, 3
        row.hwnd, row.message, row.msgTime = 2**64 - 1, 0x100, 2**32 - 1
        row.wParam, row.lParam, row.ptX, row.ptY = 2**64 - 1, -2**63, -2**31, 2**31 - 1
        report = api.decode_snapshot(bytes(state), self.binding(), 41, 2**63 + 9)
        self.assertEqual(report['rows'][0]['hookWParam'], 3)
        self.assertEqual(report['rows'][0]['hwnd'], 2**64 - 1)
        self.assertEqual(report['rows'][0]['lParam'], -2**63)
        self.assertEqual(report['rows'][0]['msgTime'], 2**32 - 1)
        self.assertFalse(report['actualRecipientIdentityMeasured'])
        self.assertFalse(report['tsfStateObserved'])

    def test_cwp_time_and_point_unavailable_not_zero_measurements(self):
        api = self.load()
        state = api.new_buffer(self.binding(), 41, 9)
        state.header.writerReady, state.header.reservedCount = 1, 1
        row = state.rows[0]
        row.sequence, row.hookKind, row.message, row.hwnd = 1, 1, 0x10f, 22
        result = api.decode_snapshot(bytes(state), self.binding(), 41, 9)['rows'][0]
        self.assertIsNone(result['msgTime'])
        self.assertIsNone(result['point'])
        self.assertIsNone(result['removed'])

    def test_invalid_binding_nonce_and_extent_fail_as_diagnostic_data(self):
        api = self.load()
        state = api.new_buffer(self.binding(), 41, 9)
        for field, value in [('nonce', 10), ('rowBytes', 63), ('capacity', 129), ('cachedExpectedPid', 32)]:
            changed = api.RawBuffer.from_buffer_copy(bytes(state))
            setattr(changed.header, field, value)
            with self.subTest(field=field), self.assertRaises((AssertionError, ValueError)):
                api.decode_snapshot(bytes(changed), self.binding(), 41, 9)
        for data in (bytes(state)[:-1], bytes(state) + b'\0'):
            with self.assertRaises((AssertionError, ValueError)):
                api.decode_snapshot(data, self.binding(), 41, 9)
        for status, masks in [(False, [0]*4), (0, [False]*4), (0, [2**32, 0, 0, 0]), (0, [0])]:
            with self.assertRaises((AssertionError, ValueError)):
                api.decode_snapshot(bytes(state), self.binding(), 41, 9, native_read_status=status, stable_row_masks=masks)
        self.assertEqual(ctypes.sizeof(api.RawReadMetadata), 64)
        self.assertEqual([getattr(api.RawReadMetadata, name).offset for name, _ in api.READ_FIELDS], list(range(0, 64, 4)))

    def test_incomplete_prefix_and_independent_overflow_never_forge_absence(self):
        api = self.load()
        state = api.new_buffer(self.binding(), 41, 9)
        state.header.writerReady, state.header.reservedCount, state.header.overflowBits = 1, 2, 1
        state.rows[0].sequence, state.rows[0].hookKind, state.rows[0].validBits = 1, 2, 3
        state.rows[0].hookWParam, state.rows[0].message = 1, 0x100
        report = api.decode_snapshot(bytes(state), self.binding(), 41, 9)
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['firstIncompleteSequence'], 2)
        self.assertFalse(report['complete'])
        self.assertEqual(report['overflowBits'], 1)

    def test_single_call_success_partial_zero_and_exception_semantics(self):
        api = self.load()
        for result in (0, 1, 2):
            calls, errors = [], [17]
            capture = api.FirstKeyRecorder(self.binding(), clock=iter([1., 2.]).__next__,
                get_error=lambda: errors[0], set_error=lambda value: errors.__setitem__(0, value))
            payload = (ctypes.c_ubyte * 80)(*range(80))
            def native(*args):
                calls.append(args)
                self.assertEqual(errors[0], 17)
                errors[0] = 29
                return result
            self.assertIs(capture.call(native, 2, payload, 40, token='g'), result)
            self.assertEqual(len(calls), 1)
            self.assertIs(calls[0][1], payload)
            self.assertEqual(calls[0][0::2], (2, 40))
            self.assertEqual(capture.receipt['returnCount'], result)
            self.assertEqual(capture.receipt['bufferBeforeHex'], bytes(payload).hex())
            self.assertEqual(capture.receipt['bufferAfterHex'], bytes(payload).hex())
            self.assertEqual(errors[0], 29)
        primary = KeyboardInterrupt('native primary')
        capture = api.FirstKeyRecorder(self.binding())
        calls = []
        def broken(*args):
            calls.append(args)
            raise primary
        with self.assertRaises(KeyboardInterrupt) as caught:
            capture.call(broken, 2, (ctypes.c_ubyte * 80)(), 40, token='g')
        self.assertIs(caught.exception, primary)
        self.assertEqual(len(calls), 1)

    def test_metadata_failures_and_later_keys_never_retry_or_skip(self):
        api = self.load()
        def broken_clock():
            raise RuntimeError('clock unavailable')
        capture = api.FirstKeyRecorder(self.binding(), clock=broken_clock)
        calls = []
        native = lambda *args: calls.append(args) or 2
        payload = (ctypes.c_ubyte * 80)()
        for token in ['g', 'k', 's', 'r', 'm', 'f', 'BACKSPACE', 'f', 'RIGHT']:
            self.assertEqual(capture.call(native, 2, payload, 40, token=token), 2)
        self.assertEqual(len(calls), 9)
        self.assertIn('captureErrors', capture.receipt)
        self.assertFalse(capture.receipt['intentDurableBeforeCall'])

    def test_hash_and_error_capture_faults_do_not_replace_native_result(self):
        api = self.load()
        capture = api.FirstKeyRecorder(self.binding())
        calls = []
        payload = (ctypes.c_ubyte * 80)()
        with patch.object(api, 'sha', side_effect=KeyboardInterrupt('hash secondary')):
            self.assertEqual(capture.call(lambda *args: calls.append(args) or 1, 2, payload, 40, token='g'), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(capture.receipt['returnCount'], 1)
        self.assertEqual(len(capture.receipt['captureErrors']), 2)

    def test_native_exception_retains_after_buffer_and_hash_fault_is_secondary(self):
        api = self.load()
        for hash_fault in (False, True):
            payload = (ctypes.c_ubyte * 80)()
            primary = KeyboardInterrupt('native primary')
            errors, calls = [17], []
            capture = api.FirstKeyRecorder(self.binding(), get_error=lambda: errors[0],
                set_error=lambda value: errors.__setitem__(0, value))
            def native(*args):
                calls.append(args)
                payload[10] = 42
                errors[0] = 29
                if hash_fault:
                    api.sha = lambda data: (_ for _ in ()).throw(RuntimeError('after hash fault'))
                raise primary
            with self.assertRaises(KeyboardInterrupt) as caught:
                capture.call(native, 2, payload, 40, token='g')
            self.assertIs(caught.exception, primary)
            self.assertEqual(errors[0], 29)
            self.assertEqual(len(calls), 1)
            if hash_fault:
                self.assertTrue(capture.receipt['captureErrors'])
            else:
                self.assertEqual(bytes.fromhex(capture.receipt['bufferAfterHex'])[10], 42)

    def test_sidecar_mapping_partial_failure_closes_once(self):
        api = self.load()
        class Broken:
            closed = 0
            def __setitem__(self, key, value):
                raise KeyboardInterrupt('mapping write primary')
            def close(self):
                self.closed += 1
        value = Broken()
        with self.assertRaisesRegex(KeyboardInterrupt, 'mapping write primary'):
            api.Sidecar(self.binding(), 41, 9, 'Local\\Raw_0123456789abcdef', factory=lambda: value)
        self.assertEqual(value.closed, 1)
        class BrokenClose(Broken):
            def close(self):
                self.closed += 1
                raise RuntimeError('close secondary')
        value = BrokenClose()
        with self.assertRaisesRegex(KeyboardInterrupt, 'mapping write primary') as caught:
            api.Sidecar(self.binding(), 41, 9, 'Local\\Raw_0123456789abcdef', factory=lambda: value)
        self.assertIn('close secondary', caught.exception.raw_sidecar_close_error)
        self.assertEqual(value.closed, 1)
        class Owned(bytearray):
            closed = 0
            def close(self):
                self.closed += 1
        mapping = Owned(8256)
        sidecar = api.Sidecar(self.binding(), 41, 9, 'Local\\Raw_0123456789abcdef', factory=lambda: mapping)
        sidecar.close()
        sidecar.close()
        self.assertEqual(mapping.closed, 1)

    def test_private_physical_preserves_full_count_assertion(self):
        api = self.load()
        import korean_ime_smoke as production
        original = production.physical_key
        function = api.make_physical_key(production)
        for count in (0, 1, 2):
            calls, guard = [], []
            capture = api.FirstKeyRecorder(self.binding())
            send = types.SimpleNamespace(argtypes=None, restype=None)
            class Native:
                argtypes = restype = None
                def __call__(self, *args):
                    calls.append(args)
                    return count
            user = types.SimpleNamespace(SendInput=Native(), GetKeyboardLayout=lambda tid: 0x04120412)
            observer = types.SimpleNamespace(require_target=lambda: guard.append('owned'), api=types.SimpleNamespace(user=user), tid=41, first_key=capture)
            record = {'keyTokens': []}
            if count == 2:
                function(observer, 'g', record)
                self.assertEqual(record['keyTokens'], ['g'])
            else:
                with self.assertRaisesRegex(AssertionError, 'Physical scan-code input was not fully delivered'):
                    function(observer, 'g', record)
                self.assertEqual(record['keyTokens'], [])
            self.assertEqual(guard, ['owned'])
            self.assertEqual(len(calls), 1)
        self.assertIs(production.physical_key, original)

    def test_private_physical_exact_windows64_g_input_buffer(self):
        api = self.load()
        import korean_ime_smoke as production
        class Keyboard(ctypes.Structure):
            _fields_ = [('wVk', ctypes.c_uint16), ('wScan', ctypes.c_uint16), ('dwFlags', ctypes.c_uint32),
                        ('time', ctypes.c_uint32), ('dwExtraInfo', ctypes.c_uint64)]
        class Mouse(ctypes.Structure):
            _fields_ = [('dx', ctypes.c_int32), ('dy', ctypes.c_int32), ('mouseData', ctypes.c_uint32),
                        ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32), ('dwExtraInfo', ctypes.c_uint64)]
        class Payload(ctypes.Union):
            _fields_ = [('keyboard', Keyboard), ('mouse', Mouse)]
        class Input(ctypes.Structure):
            _fields_ = [('type', ctypes.c_uint32), ('payload', Payload)]
        self.assertEqual(ctypes.sizeof(Input), 40)
        function = api.make_physical_key(production)
        function.__globals__.update(Input=Input, KeyboardInput=Keyboard)
        calls = []
        class Native:
            argtypes = restype = None
            def __call__(self, *args):
                calls.append(args)
                return 2
        capture = api.FirstKeyRecorder(self.binding())
        observer = types.SimpleNamespace(require_target=lambda: None, tid=41, first_key=capture,
            api=types.SimpleNamespace(user=types.SimpleNamespace(SendInput=Native(), GetKeyboardLayout=lambda tid: 0x04120412)))
        record = {'keyTokens': []}
        function(observer, 'g', record)
        expected = bytearray(80)
        for offset, flags in [(0, 8), (40, 10)]:
            struct.pack_into('<I', expected, offset, 1)
            struct.pack_into('<H', expected, offset + 10, 34)
            struct.pack_into('<I', expected, offset + 12, flags)
        self.assertEqual(bytes(calls[0][1]), bytes(expected))
        self.assertEqual(capture.receipt['bufferBeforeHex'], expected.hex())
        self.assertEqual(capture.receipt['bufferAfterHex'], expected.hex())
        self.assertEqual(capture.receipt['returnCount'], 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(record['keyTokens'], ['g'])

    def test_private_main_and_constructor_resolve_only_private_functions(self):
        api = self.load()
        import korean_ime_smoke as production
        names = ('OBSERVER_SOURCE', 'CompositionObserver', 'compile_observer', 'physical_key', 'case', 'main')
        before = {name: getattr(production, name) for name in names}
        class Observer: pass
        private = api.make_private_main(production, Observer)
        self.assertEqual(private.__globals__['case'].__code__.co_firstlineno, production.case.__code__.co_firstlineno)
        self.assertIs(private.__globals__['case'].__globals__['CompositionObserver'], Observer)
        self.assertIsNot(private.__globals__['case'], production.case)
        self.assertIsNot(private.__globals__['case'].__globals__['physical_key'], production.physical_key)
        self.assertEqual(private.__globals__['case'].__globals__['physical_key'].__code__.co_firstlineno, production.physical_key.__code__.co_firstlineno)
        generated, _ = api.instrument_source(literal(), 'Local\\Raw_0123456789abcdef', 9)
        initializer = api.make_private_initializer(production, generated)
        compiler = initializer.__globals__['compile_observer']
        self.assertEqual(compiler.__globals__['OBSERVER_SOURCE'], generated)
        self.assertEqual(compiler.__code__, production.compile_observer.__code__)
        for name in names:
            self.assertIs(getattr(production, name), before[name])

    def test_private_compiler_runs_generated_source_and_original_three_case_plan(self):
        api = self.load()
        import korean_ime_smoke as production
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'finite.py'
            text = '''
def compile_observer():
    return OBSERVER_SOURCE
class Original:
    def __init__(self, *args, **kwargs):
        self.source = compile_observer()
    def close(self):
        calls.append('original-close')
def case(module):
    keyboard = NS(binding=binding, tid=41)
    record = {'architecture': 'arm64'}
    setup_deadline = 60
    return CompositionObserver(module,
            architecture=record['architecture'], setup_deadline=setup_deadline)
def main(argv=None):
    return [case(module) for module, extension in INPUT_CASES]
'''
            path.write_text(text)
            namespace = dict(OBSERVER_SOURCE=literal(), NS=types.SimpleNamespace,
                             binding=self.binding(), INPUT_CASES=production.INPUT_CASES, calls=[])
            exec(compile(text, str(path), 'exec'), namespace)
            namespace['CompositionObserver'] = namespace['Original']
            fake = types.SimpleNamespace(**namespace, physical_key=production.physical_key)
            generated, _ = api.instrument_source(literal(), 'Local\\Raw_0123456789abcdef', 9)
            initialized = types.SimpleNamespace()
            api.make_private_initializer(fake, generated)(initialized)
            self.assertEqual(initialized.source, generated)
            calls = []
            def observer(module, **kwargs):
                calls.append((module, kwargs))
                return module
            self.assertEqual(api.make_private_main(fake, observer)(), ['writer', 'calc', 'impress'])
            self.assertTrue(all(row[1]['diagnostic_native'] == self.binding() and row[1]['diagnostic_tid'] == 41 for row in calls))
            self.assertIs(fake.OBSERVER_SOURCE, namespace['OBSERVER_SOURCE'])
            self.assertIs(namespace['CompositionObserver'], namespace['Original'])

    def test_observer_sidecar_failures_keep_original_cleanup_and_primary(self):
        api = self.load()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'finite.py'
            path.write_text('''
def compile_observer(*args, **kwargs):
    return OBSERVER_SOURCE
class Original:
    def __init__(self, *args, **kwargs):
        self.generated = compile_observer()
        self.dll = object()
    def close(self):
        calls.append('original-close')
        if close_error is not None:
            raise close_error
''')
            calls = []
            namespace = dict(OBSERVER_SOURCE=literal(), calls=calls, close_error=None)
            exec(compile(path.read_text(), str(path), 'exec'), namespace)
            fake = types.SimpleNamespace(CompositionObserver=namespace['Original'], compile_observer=namespace['compile_observer'], OBSERVER_SOURCE=literal())
            for sidecar_error in ('setup', 'configure', 'read', 'persist'):
                class Sidecar:
                    def __init__(self, *args):
                        if sidecar_error == 'setup': raise KeyboardInterrupt('setup secondary')
                    def configure(self, dll):
                        if sidecar_error == 'configure': raise KeyboardInterrupt('configure secondary')
                    def snapshot(self, dll):
                        raise KeyboardInterrupt('read secondary')
                    def close(self): calls.append('raw-close')
                Observer = api.make_observer_class(fake)
                with patch.object(api, 'Sidecar', Sidecar), patch.object(api, 'write_once', side_effect=KeyboardInterrupt('persist secondary')):
                    instance = Observer(None, 11, 22, 22, 31, Path(directory), {}, diagnostic_native=self.binding(), diagnostic_tid=41)
                    self.assertEqual(instance.first_key.call(lambda *args: 2, 2, (ctypes.c_ubyte * 80)(), 40, token='g'), 2)
                    instance.close()
                    instance.close()
                self.assertIn('original-close', calls)
                self.assertTrue(instance.raw_errors)
                self.assertFalse(instance.first_key.receipt['persistedAfterCall'])
                self.assertFalse(instance.raw_entry['firstKeyCall']['persistedAfterCall'])
            Observer = api.make_observer_class(fake)
            with patch.object(api.uuid, 'uuid4', side_effect=KeyboardInterrupt('nonce secondary')), patch.object(api, 'Sidecar') as factory:
                instance = Observer(None, 11, 22, 22, 31, Path(directory), {}, diagnostic_native=self.binding(), diagnostic_tid=41)
                instance.close()
                factory.assert_not_called()
            self.assertFalse(instance.raw_entry['instrumentation']['rawCaptureEnabled'])
            self.assertIn('RAW_CAPTURE_ENABLED=false', instance.generated)
            primary = KeyboardInterrupt('original unhook primary')
            namespace['close_error'] = primary
            Observer = api.make_observer_class(fake)
            with patch.object(api, 'Sidecar', side_effect=RuntimeError('setup secondary')), patch.object(api, 'write_once', side_effect=RuntimeError('persist secondary')):
                instance = Observer(None, 11, 22, 22, 31, Path(directory), {}, diagnostic_native=self.binding(), diagnostic_tid=41)
                with self.assertRaises(KeyboardInterrupt) as caught:
                    instance.close()
            self.assertIs(caught.exception, primary)

    def test_report_never_qualifies_and_primary_survives_persistence_error(self):
        api = self.load()
        report = api.diagnostic_report({'success': True, 'imeVerified': True, 'tests': [{'success': True}]})
        for key in ('success', 'imeVerified', 'productQualified', 'wholePairQualified', 'officeReplacementCertified', 'stateEffectClaim', 'timingNeutralClaim'):
            self.assertIs(report[key], False)
        primary = RuntimeError('original failure')
        calls = []
        def persist():
            calls.append('persist')
            raise KeyboardInterrupt('secondary')
        self.assertIs(api.secondary(persist, primary), primary)
        self.assertEqual(calls, ['persist'])

    def test_real_sized_original_report_is_preserved_without_bloating_summary(self):
        api = self.load()
        original = dict(success=False, imeVerified=False, tests=[
            dict(case='ime-' + module, module=module, stage='physical-dubeolsik-composition',
                 success=False, imeVerified=False, error='original primary', retainedNativeReceipt='x' * 600000)
            for module in ('writer', 'calc', 'impress')])
        data = (json.dumps(original) + '\n').encode()
        self.assertGreater(len(data), 524288)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            def main(argv):
                output.mkdir()
                (output / 'results.json').write_bytes(data)
                return 1
            production = types.SimpleNamespace(**{name: object() for name in
                ('OBSERVER_SOURCE', 'CompositionObserver', 'compile_observer', 'physical_key', 'case', 'main')})
            observer = types.SimpleNamespace(completed=[])
            with patch.object(api, 'make_private_main', return_value=main), patch.object(api, 'make_observer_class', return_value=observer):
                self.assertEqual(api.run_diagnostic(production, [], output, {'diagnosticOnly': True}), 1)
            self.assertEqual((output / 'production-case-results.json').read_bytes(), data)
            self.assertEqual((output / 'results.json').read_bytes(), data)
            summary = json.loads((output / 'raw-message-diagnostic.json').read_bytes())
            self.assertLess((output / 'raw-message-diagnostic.json').stat().st_size, 16384)
            self.assertEqual(summary['originalProductionReport']['sha256'], api.sha(data))
            self.assertEqual([row['case'] for row in summary['caseSummaries']], ['ime-writer', 'ime-calc', 'ime-impress'])
            self.assertFalse(summary['success'])
            self.assertFalse(summary['stateEffectClaim'])

    def test_outer_report_persistence_never_replaces_original_base_exception(self):
        api = self.load()
        primary = KeyboardInterrupt('original case primary')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            def main(argv):
                output.mkdir()
                (output / 'results.json').write_text('{}')
                raise primary
            production = types.SimpleNamespace(**{name: object() for name in
                ('OBSERVER_SOURCE', 'CompositionObserver', 'compile_observer', 'physical_key', 'case', 'main')})
            with patch.object(api, 'make_private_main', return_value=main), patch.object(api, 'make_observer_class', return_value=types.SimpleNamespace(completed=[])), \
                    patch.object(api, 'write_once', side_effect=SystemExit('persistence secondary')), patch.object(sys, 'stderr'):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    api.run_diagnostic(production, [], output, {})
            self.assertIs(caught.exception, primary)

    def test_source_binding_rejects_changed_host_ref_and_noncanonical_run(self):
        api = self.load()
        valid = dict(GITHUB_SHA='a'*40, GITHUB_WORKFLOW_SHA='a'*40,
            GITHUB_REF='refs/heads/work/native35-arm64-input-witness',
            GITHUB_WORKFLOW_REF='ATLKR/OpenGeul/.github/workflows/suite-native35-input-witness.yml@refs/heads/work/native35-arm64-input-witness',
            GITHUB_WORKFLOW='Diagnostic', GITHUB_RUN_ID='39926984619', GITHUB_RUN_ATTEMPT='1',
            GITHUB_JOB='windows-suite', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_ACTIONS='true',
            RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows', RUNNER_ARCH='ARM64', GITHUB_EVENT_NAME='push')
        for key, value in [('RUNNER_ARCH', 'X64'), ('GITHUB_REF', 'refs/heads/main'),
                           ('GITHUB_RUN_ID', '01'), ('GITHUB_RUN_ID', str(2**64)),
                           ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_WORKFLOW_SHA', 'b'*40)]:
            with self.subTest(key=key, value=value), patch.object(api.subprocess, 'check_output') as native:
                with self.assertRaises(AssertionError):
                    api.source_binding(dict(valid, **{key: value}), ROOT)
                native.assert_not_called()

    def portable_source(self, api, enabled):
        generated, _ = api.instrument_source(literal(), 'Local\\Raw_0123456789abcdef',
            18364758544493064720, capture_enabled=enabled)
        helper_start = generated.index('// Generated diagnostic copy only.')
        helper = generated[helper_start:generated.index('static bool connect() {', helper_start)]
        export_start = generated.index('// Separate diagnostic exports.')
        exports = generated[export_start:generated.index('BOOL WINAPI DllMain(', export_start)]
        hooks = generated[generated.index('extern "C" __declspec(dllexport) LRESULT CALLBACK HookCall('):
                          generated.index('extern "C" __declspec(dllexport) unsigned int StateSize()')]
        declarations = generated[generated.index('struct Event {'):generated.index('static State* shared = nullptr;')]
        abi = '#include "ime_thread_mode.h"\n#include "ime_command_admission.h"\nusing WCHAR=uint16_t;\n' + declarations + '\n'
        abi += 'static_assert(sizeof(Event)==1080 && sizeof(State)==553720 && sizeof(opengeul_ime::ModeReceipt)==184,"Original ABI changed");\n'
        harness = NATIVE_HARNESS_SOURCE.replace('__GENERATED_RAW_HELPER__', abi + helper)
        return harness.replace('__GENERATED_RAW_EXPORTS__', exports).replace('__GENERATED_HOOKS__', hooks)

    def portable_run(self, source, folder):
        for name in ('ime_thread_mode.h', 'ime_command_admission.h'):
            (folder / name).write_bytes((ROOT / 'suite/e2e' / name).read_bytes())
        path, executable = folder / 'raw.cpp', folder / 'raw'
        path.write_text(source)
        compiled = subprocess.run(['/usr/bin/g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(executable)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        self.assertEqual(compiled.returncode, 0, compiled.stdout.decode(errors='replace'))
        return subprocess.run([str(executable)], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)

    def test_exact_generated_cpp_portable_branches_and_unchanged_original_abi(self):
        api = self.load()
        import korean_ime_smoke as production
        self.assertEqual((ctypes.sizeof(production.NativeEvent), ctypes.sizeof(production.NativeState)), (1080, 553720))
        for enabled in (True, False):
            with self.subTest(captureEnabled=enabled), tempfile.TemporaryDirectory() as directory:
                completed = self.portable_run(self.portable_source(api, enabled), Path(directory))
                self.assertEqual(completed.returncode, 0, completed.stdout.decode(errors='replace'))
                self.assertIn(b'PASS', completed.stdout)

    def test_portable_checks_detect_remove3_loss_and_new_state_query(self):
        source = self.portable_source(self.load(), True)
        anchor = '!(hookWParam&PM_REMOVE)'
        self.assertEqual(source.count(anchor), 1)
        wrong_remove = source.replace(anchor, '!(hookWParam==PM_REMOVE)', 1)
        anchor = 'static void raw_hook_get(int code,WPARAM hookWParam,LPARAM pointer) {\n    RawLastError restore;'
        self.assertEqual(source.count(anchor), 1)
        new_query = source.replace(anchor, anchor + '\n    GetKeyboardLayout(0);', 1)
        for name, changed in [('remove3-loss', wrong_remove), ('new-query', new_query)]:
            with self.subTest(mutant=name), tempfile.TemporaryDirectory() as directory:
                completed = self.portable_run(changed, Path(directory))
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(b'Assertion', completed.stdout)


NATIVE_HARNESS_SOURCE = r'''// Portable fake-Win32 harness. Includes the exact authored fragments below.
// No production module, DLL, application, or live native API is executed.
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>

#define __declspec(value)
#define WINAPI
#define CALLBACK
using LONG = int32_t;
using DWORD = uint32_t;
using BOOL = int32_t;
using HANDLE = void*;
using HWND = void*;
using WPARAM = uintptr_t;
using LPARAM = intptr_t;
using LRESULT = intptr_t;
using UINT = uint32_t;
constexpr BOOL FALSE = 0;
constexpr DWORD FILE_MAP_WRITE = 2, FILE_MAP_READ = 4;
constexpr int HC_ACTION = 0;
constexpr WPARAM PM_REMOVE = 1;
constexpr UINT WM_KEYDOWN=256, WM_KEYUP=257, WM_CHAR=258;
constexpr UINT WM_IME_STARTCOMPOSITION=269, WM_IME_ENDCOMPOSITION=270;
constexpr UINT WM_IME_COMPOSITION=271, WM_IME_CHAR=646;
struct POINT { int32_t x, y; };
struct MSG { HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; POINT pt; };
struct CWPSTRUCT { LPARAM lParam; WPARAM wParam; UINT message; HWND hwnd; };

namespace fake {
DWORD error=0;
void* view=nullptr;
bool failOpen=false, failMap=false, failUnmap=false, failClose=false;
unsigned opens=0, maps=0, unmaps=0, closes=0, forbiddenCalls=0;
unsigned reservations=0, observes=0, forwards=0;
LONG* reservationAddress=nullptr;
bool contention=false;
DWORD originalEntryError=0, nextEntryError=0;
void (*copyHook)(void*,const void*,size_t)=nullptr;
}
DWORD GetLastError() { return fake::error; }
void SetLastError(DWORD value) { fake::error=value; }
HANDLE OpenFileMappingW(DWORD access,BOOL inherit,const wchar_t*) {
    ++fake::opens; fake::error=701;
    assert(access==(FILE_MAP_READ|FILE_MAP_WRITE) && inherit==FALSE);
    return fake::failOpen ? nullptr : reinterpret_cast<HANDLE>(uintptr_t(0x1000));
}
void* MapViewOfFile(HANDLE handle,DWORD access,DWORD high,DWORD low,size_t bytes) {
    ++fake::maps; fake::error=702;
    assert(handle && access==(FILE_MAP_READ|FILE_MAP_WRITE) && high==0 && low==0 && bytes==8256);
    return fake::failMap ? nullptr : fake::view;
}
BOOL UnmapViewOfFile(const void* view) {
    ++fake::unmaps; fake::error=703; assert(view==fake::view); return !fake::failUnmap;
}
BOOL CloseHandle(HANDLE handle) {
    ++fake::closes; fake::error=704; assert(handle); return !fake::failClose;
}
LONG InterlockedCompareExchange(volatile LONG* pointer,LONG value,LONG expected) {
    if(pointer==fake::reservationAddress && value==expected+1) {
        ++fake::reservations;
        if(fake::contention) { fake::contention=false; *pointer=expected+1; return expected+1; }
    }
    const LONG old=*pointer; if(old==expected)*pointer=value; return old;
}
LONG InterlockedExchange(volatile LONG* pointer,LONG value) {
    const LONG old=*pointer; *pointer=value; return old;
}
LONG InterlockedOr(volatile LONG* pointer,LONG value) {
    const LONG old=*pointer; *pointer=old|value; return old;
}
void MemoryBarrier() { std::atomic_thread_fence(std::memory_order_seq_cst); }
void CopyMemory(void* destination,const void* source,size_t bytes) {
    std::memcpy(destination,source,bytes);
    if(fake::copyHook)fake::copyHook(destination,source,bytes);
}
int forbidden(const char*) { ++fake::forbiddenCalls; return 0; }
#define ImmGetContext(...) forbidden("ImmGetContext")
#define ImmGetOpenStatus(...) forbidden("ImmGetOpenStatus")
#define ImmGetConversionStatus(...) forbidden("ImmGetConversionStatus")
#define ImmReleaseContext(...) forbidden("ImmReleaseContext")
#define GetKeyState(...) forbidden("GetKeyState")
#define GetKeyboardState(...) forbidden("GetKeyboardState")
#define GetQueueStatus(...) forbidden("GetQueueStatus")
#define GetKeyboardLayout(...) forbidden("GetKeyboardLayout")
#define QueryPerformanceCounter(...) forbidden("QueryPerformanceCounter")
#define QueryPerformanceFrequency(...) forbidden("QueryPerformanceFrequency")
#define GetWindowThreadProcessId(...) forbidden("GetWindowThreadProcessId")
#define GetCurrentThreadId(...) forbidden("GetCurrentThreadId")
#define GetCurrentProcessId(...) forbidden("GetCurrentProcessId")
#define IsWindow(...) forbidden("IsWindow")
#define GetAncestor(...) forbidden("GetAncestor")
#define GetForegroundWindow(...) forbidden("GetForegroundWindow")
#define GetFocus(...) forbidden("GetFocus")
#define TF_GetThreadMgr(...) forbidden("TF_GetThreadMgr")
#define __RAW_NONCE__ 18364758544493064720ULL
#ifndef __RAW_ENABLED__
#define __RAW_ENABLED__ true
#endif
__GENERATED_RAW_HELPER__
__GENERATED_RAW_EXPORTS__

// The bodies after raw_hook_* are the original production hook bodies.
void observe(HWND,UINT,WPARAM,LPARAM,UINT) {
    ++fake::observes; fake::originalEntryError=GetLastError(); SetLastError(901);
}
LRESULT CallNextHookEx(HANDLE,int,WPARAM,LPARAM) {
    ++fake::forwards; fake::nextEntryError=GetLastError(); return LRESULT(0x12345678);
}
__GENERATED_HOOKS__

RawSidecar sidecar{};
void reset() {
    fake::error=321; fake::view=&sidecar;
    fake::failOpen=fake::failMap=fake::failUnmap=fake::failClose=false;
    fake::opens=fake::maps=fake::unmaps=fake::closes=fake::forbiddenCalls=0;
    fake::reservations=fake::observes=fake::forwards=0;
    fake::reservationAddress=nullptr;fake::contention=false;fake::copyHook=nullptr;
    raw_setup_attempted=0;raw_mapping=nullptr;raw_sidecar=nullptr;
    raw_cached_pid=raw_cached_tid=0;raw_cached_creation=0;
    sidecar=RawSidecar{};
    sidecar.header.magic=RAW_MAGIC;sidecar.header.version=1;
    sidecar.header.headerBytes=64;sidecar.header.rowBytes=64;sidecar.header.capacity=128;
    sidecar.header.enabled=1;sidecar.header.cachedExpectedPid=71;
    sidecar.header.cachedExpectedTid=83;sidecar.header.cachedEngineCreationTime=uint64_t(1)<<60;
    sidecar.header.nonce=__RAW_NONCE__;
}
void ready() {
    raw_setup_once(71,83);
    assert(fake::error==321 && sidecar.header.writerReady==1 && raw_sidecar==&sidecar);
    assert(raw_cached_pid==71 && raw_cached_tid==83 && raw_cached_creation==(uint64_t(1)<<60));
    assert(fake::opens==1 && fake::maps==1 && fake::closes==0 && fake::unmaps==0);
    fake::reservationAddress=reinterpret_cast<LONG*>(&sidecar.header.reservedCount);
}
MSG message(UINT type=WM_KEYDOWN) {
    return MSG{reinterpret_cast<HWND>(uintptr_t(0xfedcba9876543210ULL)),type,
        WPARAM(0xfffffffffffffff1ULL),std::numeric_limits<LPARAM>::min(),0,POINT{-2000000000,2000000000}};
}
void assert_no_extra_queries(unsigned opens,unsigned maps) {
    assert(fake::forbiddenCalls==0 && fake::opens==opens && fake::maps==maps);
    assert(fake::closes==0 && fake::unmaps==0 && fake::error==321);
}
void test_setup() {
    reset();fake::failOpen=true;raw_setup_once(71,83);
    assert(!raw_sidecar && !sidecar.header.writerReady && fake::opens==1 && !fake::maps && !fake::closes);
    fake::failOpen=false;raw_setup_once(71,83);assert(fake::opens==1 && fake::error==321);
    reset();fake::failMap=true;raw_setup_once(71,83);
    assert(!raw_sidecar && fake::opens==1 && fake::maps==1 && fake::closes==1 && !fake::unmaps && fake::error==321);
    for(unsigned fault=0;fault<13;++fault) {
        reset();
        switch(fault) {
        case 0:sidecar.header.magic=0;break;case 1:sidecar.header.version=2;break;
        case 2:sidecar.header.headerBytes=63;break;case 3:sidecar.header.rowBytes=63;break;
        case 4:sidecar.header.capacity=129;break;case 5:sidecar.header.nonce=0;break;
        case 6:sidecar.header.cachedExpectedPid=72;break;case 7:sidecar.header.cachedExpectedTid=84;break;
        case 8:sidecar.header.cachedEngineCreationTime=0;break;case 9:sidecar.header.reservedZero=1;break;
        case 10:sidecar.header.reservedCount=1;break;case 11:sidecar.header.overflowBits=1;break;
        case 12:sidecar.header.writerReady=1;break;
        }
        fake::failUnmap=fake::failClose=true;
        raw_setup_once(71,83);
        assert(!raw_sidecar && fake::unmaps==1 && fake::closes==1 && fake::error==321);
        raw_setup_once(71,83);assert(fake::opens==1 && fake::unmaps==1 && fake::closes==1);
    }
    reset();ready();raw_setup_once(71,83);assert(fake::opens==1);
}
void test_raw_fields_filters_and_forwarding() {
    for(WPARAM remove=0;remove<=3;++remove) {
        reset();ready();MSG m=message();
        raw_hook_get(HC_ACTION,remove,reinterpret_cast<LPARAM>(&m));
        assert(sidecar.header.reservedCount==((remove&PM_REMOVE)?1:0));
        if(remove&PM_REMOVE) {
            const RawRow& r=sidecar.rows[0];
            assert(r.sequence==1 && r.hookKind==2 && r.nCode==0 && r.validBits==3 && r.hookWParam==remove);
            assert(r.hwnd==0xfedcba9876543210ULL && r.wParam==0xfffffffffffffff1ULL);
            assert(r.lParam==std::numeric_limits<int64_t>::min() && r.msgTime==0 && r.ptX==-2000000000 && r.ptY==2000000000);
        }
        assert_no_extra_queries(1,1);
    }
    for(int code:{-1,0,1}) for(WPARAM remove:{WPARAM(0),WPARAM(1),WPARAM(2),WPARAM(3)}) {
        reset();ready();MSG m=message(WM_IME_COMPOSITION);
        const LRESULT result=HookGet(code,remove,reinterpret_cast<LPARAM>(&m));
        assert(result==LRESULT(0x12345678) && fake::forwards==1);
        assert(fake::observes==unsigned(code>=0 && remove==1));
        assert(sidecar.header.reservedCount==int(code==HC_ACTION && (remove&PM_REMOVE)));
        if(fake::observes)assert(fake::originalEntryError==321 && fake::nextEntryError==901);
        else assert(fake::nextEntryError==321);
        assert(fake::forbiddenCalls==0);
    }
    for(int code:{-1,0,1}) for(UINT type:{WM_CHAR,WM_IME_COMPOSITION,UINT(0x8351)}) {
        reset();ready();CWPSTRUCT m{LPARAM(-7),WPARAM(0xfedcba9876543210ULL),type,reinterpret_cast<HWND>(uintptr_t(999))};
        const LRESULT result=HookCall(code,WPARAM(0xfffffffffffffff3ULL),reinterpret_cast<LPARAM>(&m));
        assert(result==LRESULT(0x12345678) && fake::forwards==1 && fake::observes==unsigned(code>=0));
        assert(sidecar.header.reservedCount==int(code==0 && type!=0x8351));
        if(sidecar.header.reservedCount) {
            const RawRow& r=sidecar.rows[0];
            assert(r.hookKind==1 && r.validBits==0 && r.msgTime==0 && r.ptX==0 && r.ptY==0);
            assert(r.hwnd==999 && r.wParam==0xfedcba9876543210ULL && r.hookWParam==0xfffffffffffffff3ULL && r.lParam==-7);
        }
        assert(fake::forbiddenCalls==0);
    }
    for(UINT type:{WM_KEYDOWN,WM_KEYUP,WM_CHAR,WM_IME_STARTCOMPOSITION,WM_IME_ENDCOMPOSITION,WM_IME_COMPOSITION,WM_IME_CHAR,UINT(0x8351),UINT(999)}) {
        reset();ready();MSG m=message(type);m.time=0xffffffffU;
        raw_hook_get(0,3,reinterpret_cast<LPARAM>(&m));
        assert(sidecar.header.reservedCount==int(type!=0x8351 && type!=999));
        if(sidecar.header.reservedCount)assert(sidecar.rows[0].msgTime==0xffffffffU);
        CWPSTRUCT sent{m.lParam,m.wParam,type,m.hwnd};const LONG before=sidecar.header.reservedCount;
        raw_hook_call(0,0,reinterpret_cast<LPARAM>(&sent));
        assert(sidecar.header.reservedCount-before==int(type!=WM_KEYDOWN && type!=WM_KEYUP && type!=0x8351 && type!=999));
        assert_no_extra_queries(1,1);
    }
    reset();ready();sidecar.header.enabled=0;MSG m=message();raw_hook_get(0,1,reinterpret_cast<LPARAM>(&m));
    assert(!sidecar.header.reservedCount);assert_no_extra_queries(1,1);
    sidecar.header.enabled=1;sidecar.header.writerReady=0;raw_hook_get(0,1,reinterpret_cast<LPARAM>(&m));
    assert(!sidecar.header.reservedCount);assert_no_extra_queries(1,1);
}
void test_capacity_and_contention() {
    reset();ready();MSG m=message();
    for(unsigned n=0;n<128;++n)raw_hook_get(0,1,reinterpret_cast<LPARAM>(&m));
    assert(sidecar.header.reservedCount==128 && sidecar.rows[127].sequence==128 && fake::reservations==128);
    raw_hook_get(0,1,reinterpret_cast<LPARAM>(&m));
    assert(sidecar.header.reservedCount==128 && (sidecar.header.overflowBits&RAW_OVERFLOW_CAPACITY) && fake::reservations==128);
    assert_no_extra_queries(1,1);
    reset();ready();fake::contention=true;raw_hook_get(0,1,reinterpret_cast<LPARAM>(&m));
    assert(sidecar.header.reservedCount==1 && !sidecar.rows[0].sequence && fake::reservations==1);
    assert(sidecar.header.overflowBits&RAW_OVERFLOW_CONTENTION);assert_no_extra_queries(1,1);
}
void test_abi_and_copy() {
    assert(RawStateSize()==8256 && RawHeaderSize()==64 && RawRowSize()==64 && RawReadMetadataSize()==64);
    const uint32_t header[]={0,4,8,12,16,20,24,28,32,36,40,44,48,56};
    const uint32_t row[]={0,4,8,12,16,24,32,36,40,48,56,60};
    for(unsigned i=0;i<14;++i)assert(RawHeaderOffset(i)==header[i]);
    for(unsigned i=0;i<12;++i)assert(RawRowOffset(i)==row[i]);
    for(unsigned i=0;i<16;++i)assert(RawReadMetadataOffset(i)==i*4);
    assert(RawHeaderOffset(14)==0xffffffffU && RawRowOffset(12)==0xffffffffU && RawReadMetadataOffset(16)==0xffffffffU);
    reset();ready();MSG m=message();raw_hook_get(0,3,reinterpret_cast<LPARAM>(&m));
    RawSidecar copy{};RawReadMetadata meta{};
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && meta.copied==1 && meta.validityStatus==0 && meta.completePrefix==1);
    assert(meta.stableRowMasks[0]==1 && std::memcmp(&sidecar,&copy,sizeof(copy))==0 && fake::error==321);
    sidecar.rows[0].sequence=0;
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && (meta.validityStatus&RAW_READ_MISSING_PUBLICATION) && meta.completePrefix==0);
    sidecar.rows[0].sequence=1;
    fake::copyHook=[](void*,const void* from,size_t bytes) {
        if(from==&sidecar && bytes==8256)sidecar.rows[0].sequence=2;
    };
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && (meta.validityStatus&RAW_READ_TORN_PUBLICATION) && meta.completePrefix==0);
    assert(copy.rows[0].sequence==1); // Native bytes retained, invalidity stays in metadata.
    fake::copyHook=nullptr;sidecar.rows[0].sequence=1;
    fake::copyHook=[](void*,const void* from,size_t bytes) {
        if(from==&sidecar && bytes==8256)sidecar.header.reservedCount=2;
    };
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && (meta.validityStatus&RAW_READ_COUNT_CHANGED));
    fake::copyHook=nullptr;sidecar.header.reservedCount=-1;
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && (meta.validityStatus&RAW_READ_INVALID_COUNTER));
    sidecar.header.reservedCount=129;
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && (meta.validityStatus&RAW_READ_INVALID_COUNTER));
    sidecar.header.magic=0;
    assert(ReadRawSnapshot(&sidecar,&copy,&meta)==1 && (meta.validityStatus&RAW_READ_INVALID_HEADER) && meta.completePrefix==0);
    const RawSidecar before=sidecar;
    assert(ReadRawSnapshot(&sidecar,&sidecar,&meta)==0 && std::memcmp(&before,&sidecar,sizeof(before))==0);
    assert(ReadRawSnapshot(nullptr,&copy,&meta)==0 && ReadRawSnapshot(&sidecar,&copy,nullptr)==0);
    assert(fake::forbiddenCalls==0 && fake::error==321);
}

bool sawUnpublishedRowCopy=false;
void test_sequence_last_and_copy_statuses() {
    reset();ready();sawUnpublishedRowCopy=false;
    fake::copyHook=[](void* to,const void*,size_t bytes) {
        if(to==&sidecar.rows[0] && bytes==64) {
            sawUnpublishedRowCopy=true;
            assert(sidecar.header.reservedCount==1 && sidecar.rows[0].sequence==0);
            RawSidecar copy{};RawReadMetadata metadata{};
            assert(ReadRawSnapshot(&sidecar,&copy,&metadata)==1);
            assert((metadata.validityStatus&RAW_READ_MISSING_PUBLICATION) && metadata.completePrefix==0);
            assert(copy.rows[0].sequence==0 && metadata.stableRowMasks[0]==0);
        }
    };
    MSG m=message();raw_hook_get(0,3,reinterpret_cast<LPARAM>(&m));
    assert(sawUnpublishedRowCopy && sidecar.rows[0].sequence==1);fake::copyHook=nullptr;
    assert_no_extra_queries(1,1);
    RawSidecar copy{};RawReadMetadata metadata{};
    sidecar.header.writerReady=0;
    assert(ReadRawSnapshot(&sidecar,&copy,&metadata)==1 && (metadata.validityStatus&RAW_READ_READY_UNAVAILABLE));
    sidecar.header.writerReady=1;sidecar.header.overflowBits=RAW_OVERFLOW_CAPACITY;
    assert(ReadRawSnapshot(&sidecar,&copy,&metadata)==1 && (metadata.validityStatus&RAW_READ_OVERFLOW_OBSERVED));
    fake::copyHook=[](void*,const void* from,size_t bytes) {
        if(from==&sidecar && bytes==8256)sidecar.header.overflowBits|=RAW_OVERFLOW_CONTENTION;
    };
    assert(ReadRawSnapshot(&sidecar,&copy,&metadata)==1 && (metadata.validityStatus&RAW_READ_OVERFLOW_CHANGED));
    fake::copyHook=[](void*,const void* from,size_t bytes) {
        if(from==&sidecar && bytes==8256)sidecar.header.enabled=0;
    };
    assert(ReadRawSnapshot(&sidecar,&copy,&metadata)==1 && (metadata.validityStatus&RAW_READ_ENABLED_CHANGED));
    fake::copyHook=[](void*,const void* from,size_t bytes) {
        if(from==&sidecar && bytes==8256)++sidecar.header.cachedExpectedTid;
    };
    assert(ReadRawSnapshot(&sidecar,&copy,&metadata)==1 && (metadata.validityStatus&RAW_READ_HEADER_CHANGED));
    fake::copyHook=nullptr;
    const RawSidecar original=sidecar;
    assert(ReadRawSnapshot(&sidecar,&copy,reinterpret_cast<RawReadMetadata*>(&sidecar.header))==0);
    assert(ReadRawSnapshot(&sidecar,reinterpret_cast<RawSidecar*>(reinterpret_cast<char*>(&sidecar)+8),&metadata)==0);
    assert(std::memcmp(&original,&sidecar,sizeof(original))==0 && fake::forbiddenCalls==0 && fake::error==321);
}


void test_call_language_payloads_without_get_selection_change() {
    for(UINT type:{UINT(0x50),UINT(0x51)}) {
        for(LPARAM bits:{std::numeric_limits<LPARAM>::min(),std::numeric_limits<LPARAM>::max(),LPARAM(-1),LPARAM(0x04120412)}) {
            reset();ready();
            CWPSTRUCT sent{bits,WPARAM(0xfedcba9876543210ULL),type,reinterpret_cast<HWND>(uintptr_t(0x8000000000000001ULL))};
            raw_hook_call(HC_ACTION,WPARAM(0xfffffffffffffff3ULL),reinterpret_cast<LPARAM>(&sent));
            assert(sidecar.header.reservedCount==1 && sidecar.rows[0].sequence==1);
            const RawRow& raw=sidecar.rows[0];
            assert(raw.hookKind==1 && raw.validBits==0 && raw.message==type);
            assert(raw.hookWParam==0xfffffffffffffff3ULL && raw.hwnd==0x8000000000000001ULL);
            assert(raw.wParam==0xfedcba9876543210ULL && raw.lParam==bits);
            assert(raw.msgTime==0 && raw.ptX==0 && raw.ptY==0);
            assert_no_extra_queries(1,1);
            reset();ready();
            const LRESULT result=HookCall(HC_ACTION,WPARAM(0xfffffffffffffff3ULL),reinterpret_cast<LPARAM>(&sent));
            assert(result==LRESULT(0x12345678) && fake::observes==1 && fake::forwards==1);
            assert(fake::originalEntryError==321 && fake::nextEntryError==901 && fake::error==901);
            assert(sidecar.header.reservedCount==1 && sidecar.rows[0].lParam==bits);
            assert(fake::forbiddenCalls==0 && fake::opens==1 && fake::maps==1 && !fake::closes && !fake::unmaps);
            // Neither newly selected CALL message is added to GET coverage.
            reset();ready();MSG queued=message(type);queued.lParam=bits;
            raw_hook_get(HC_ACTION,3,reinterpret_cast<LPARAM>(&queued));
            assert(sidecar.header.reservedCount==0);assert_no_extra_queries(1,1);
            assert(!raw_selected_get(type) && raw_selected_call(type));
        }
    }
}

int main() {
    if(!RAW_CAPTURE_ENABLED) {
        reset();raw_setup_once(71,83);raw_setup_once(71,83);
        MSG m=message();raw_hook_get(0,3,reinterpret_cast<LPARAM>(&m));
        CWPSTRUCT sent{m.lParam,m.wParam,WM_CHAR,m.hwnd};
        raw_hook_call(0,0,reinterpret_cast<LPARAM>(&sent));
        assert(raw_setup_attempted==1 && !raw_sidecar && !sidecar.header.writerReady && !sidecar.header.reservedCount);
        assert(!fake::opens && !fake::maps && !fake::unmaps && !fake::closes && !fake::forbiddenCalls && fake::error==321);
        std::cout<<"PASS compile-time unavailable logger makes zero mapping probes\n";
        return 0;
    }
    test_setup();test_raw_fields_filters_and_forwarding();test_capacity_and_contention();test_abi_and_copy();test_sequence_last_and_copy_statuses();test_call_language_payloads_without_get_selection_change();
    std::cout<<"PASS raw native setup/ABI/forwarding/fields/cap/publication contracts\n";
}
'''


if __name__ == '__main__':
    unittest.main()
