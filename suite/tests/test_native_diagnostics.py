"""Read-only native diagnostic boundaries; these are not Windows crash proof."""
import importlib
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))


class NativeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module('native_diagnostics')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.payload = self.root / 'payload'
        self.profile = self.root / 'profile'
        self.payload.mkdir()
        self.profile.mkdir()

    def test_disabled_diagnostics_do_not_open_processes_or_write_files(self):
        class Process:
            def open_diagnostic_witnesses(self):
                raise AssertionError('disabled diagnostics touched process')
        result = self.module.create_diagnostics({}, self.payload, self.profile, Process())
        self.assertIsNone(result)
        self.assertEqual({'payload', 'profile'}, {p.name for p in self.root.iterdir()})

    def test_archive_copies_only_owned_crash_and_records_exact_hashes(self):
        import hashlib
        crash = self.profile / 'crash'
        crash.mkdir()
        (crash / 'own.dmp').write_bytes(b'owned crash bytes')
        (self.profile / 'foreign-document.docx').write_bytes(b'never archive')
        evidence = self.root / 'evidence'
        collector = self.module.create_diagnostics({'OPENGEUL_SUITE_DIAGNOSTICS': str(evidence)},
                                                   self.payload, self.profile, None)
        collector.archive_crash()
        manifest = json.loads((collector.directory / 'manifest.json').read_text())
        self.assertTrue(manifest['archiveComplete'])
        self.assertEqual([{'path': 'crash/own.dmp', 'bytes': 17,
            'sha256': hashlib.sha256(b'owned crash bytes').hexdigest()}], manifest['files'])
        self.assertEqual(b'owned crash bytes', (collector.directory / 'crash' / 'own.dmp').read_bytes())
        self.assertFalse((collector.directory / 'foreign-document.docx').exists())
        self.assertTrue((crash / 'own.dmp').is_file())

    def test_external_crash_symlink_is_rejected_without_copying_foreign_bytes(self):
        foreign = self.root / 'foreign'
        foreign.mkdir()
        (foreign / 'secret.dmp').write_bytes(b'foreign bytes')
        try:
            (self.profile / 'crash').symlink_to(foreign, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation unavailable')
        collector = self.module.create_diagnostics(
            {'OPENGEUL_SUITE_DIAGNOSTICS': str(self.root / 'evidence')}, self.payload, self.profile, None)
        with self.assertRaises(ValueError):
            collector.archive_crash()
        self.assertFalse(any(p.name == 'secret.dmp' for p in collector.directory.rglob('*')))

    def test_output_inside_payload_profile_or_through_link_is_rejected(self):
        for directory in (self.payload / 'evidence', self.profile / 'evidence'):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.module.create_diagnostics({'OPENGEUL_SUITE_DIAGNOSTICS': str(directory)},
                                               self.payload, self.profile, None)
        foreign = self.root / 'foreign'
        foreign.mkdir()
        linked = self.root / 'linked'
        try:
            linked.symlink_to(foreign, target_is_directory=True)
        except OSError:
            return  # Windows link privilege is not assumed for these unit tests.
        with self.assertRaises(ValueError):
            self.module.create_diagnostics({'OPENGEUL_SUITE_DIAGNOSTICS': str(linked / 'evidence')},
                                           self.payload, self.profile, None)
        self.assertEqual([], list(foreign.iterdir()))

    def test_process_witness_keeps_original_exit_code_without_terminating_or_reopening(self):
        windows = importlib.import_module('native_windows')
        calls, alive = [], [True]

        class Api:
            def job_pids(self, job):
                calls.append(('job', job))
                return [77] if alive[0] else []
            def open_owned(self, pid, job):
                calls.append(('open', pid, job))
                return 123
            def identity(self, handle):
                return {'image': 'C:/Office/program/soffice.bin', 'creationTime': 123456}
            def state(self, handle):
                return {'alive': alive[0], 'exitCode': 259 if alive[0] else 0xC0000005,
                        'exitCodeHex': '0x00000103' if alive[0] else '0xc0000005'}
            def close(self, handle):
                calls.append(('close', handle))

        witness = windows.JobProcessWitnesses(9, api=Api())
        first = witness.snapshot()
        alive[0] = False
        second = witness.snapshot()
        self.assertTrue(first[0]['alive'])
        self.assertFalse(second[0]['alive'])
        self.assertEqual(0xC0000005, second[0]['exitCode'])
        self.assertEqual(123456, second[0]['creationTime'])
        self.assertEqual(1, sum(call[0] == 'open' for call in calls))
        self.assertFalse(any(call[0] in ('terminate', 'wait') for call in calls))
        witness.close()
        self.assertEqual(('close', 123), calls[-1])

    def test_failed_snapshot_records_error_instead_of_claiming_process_exited(self):
        windows = importlib.import_module('native_windows')
        class Api:
            def job_pids(self, job): return [77]
            def open_owned(self, pid, job): raise OSError('query denied')
        witness = windows.JobProcessWitnesses(9, api=Api())
        state = witness.snapshot()[0]
        self.assertIn('error', state)
        self.assertNotIn('alive', state)
        self.assertNotIn('exitCode', state)

    def test_cleanup_snapshots_before_termination_and_archives_before_profile_removal(self):
        import shutil
        from types import SimpleNamespace
        native = importlib.import_module('native')
        calls, alive = [], [True]
        (self.profile / 'crash').mkdir()
        (self.profile / 'crash' / 'own.dmp').write_bytes(b'owned crash')
        evidence = self.root / 'evidence'
        class Witness:
            def snapshot(self):
                calls.append(('snapshot', alive[0]))
                return [{'pid': 7, 'image': 'soffice.bin', 'creationTime': 123,
                         'alive': alive[0], 'exitCode': 259 if alive[0] else 1}]
            def close(self): calls.append(('witness-close',))
        def terminate():
            calls.append(('terminate',))
            alive[0] = False
        process = SimpleNamespace(open_diagnostic_witnesses=lambda: Witness(),
            poll=lambda: None if alive[0] else 1, terminate=terminate,
            wait=lambda timeout: 1, close=lambda: calls.append(('process-close',)))
        backend = native.UnoBackend(self.payload / 'Office')
        backend.process = process
        backend.profile = SimpleNamespace(name=str(self.profile), cleanup=lambda: shutil.rmtree(self.profile))
        with patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': str(evidence)}), redirect_stderr(io.StringIO()):
            backend.cleanup()
        self.assertLess(calls.index(('snapshot', True)), calls.index(('terminate',)))
        self.assertLess(calls.index(('snapshot', False)), calls.index(('process-close',)))
        self.assertFalse(self.profile.exists())
        manifests = list(evidence.glob('*/manifest.json'))
        self.assertEqual(1, len(manifests))
        self.assertEqual('crash/own.dmp', json.loads(manifests[0].read_text())['files'][0]['path'])

    def test_cleanup_with_diagnostics_disabled_preserves_process_lifecycle(self):
        from types import SimpleNamespace
        native = importlib.import_module('native')
        calls = []
        process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append('terminate'),
            wait=lambda timeout: calls.append('wait'), close=lambda: calls.append('close'),
            open_diagnostic_witnesses=lambda: self.fail('disabled diagnostics queried process'))
        backend = native.UnoBackend(self.payload / 'Office')
        backend.process = process
        backend.profile = SimpleNamespace(cleanup=lambda: calls.append('profile'))
        with patch.dict(os.environ, {}, clear=True):
            backend.cleanup()
        self.assertEqual(['terminate', 'wait', 'close', 'profile'], calls)

    def test_load_exception_is_recorded_before_cleanup_and_original_error_survives(self):
        from types import SimpleNamespace
        native = importlib.import_module('native')
        alive = [True]
        original = RuntimeError('bridge disposed during load')
        class Witness:
            def snapshot(self):
                return [{'pid': 7, 'image': 'soffice.bin', 'creationTime': 456,
                         'alive': alive[0], 'exitCode': 259 if alive[0] else 0xC0000005}]
            def close(self): pass
        process = SimpleNamespace(open_diagnostic_witnesses=lambda: Witness())
        def fail_load(*args):
            alive[0] = False
            raise original
        peer_properties = {}
        peer = SimpleNamespace(setPosSize=lambda *args: None,
                               setProperty=peer_properties.__setitem__, getProperty=peer_properties.get)
        frame = SimpleNamespace(initialize=lambda peer: None, setName=lambda name: None,
                                registerDispatchProviderInterceptor=lambda interceptor: None)
        desktop = SimpleNamespace(getFrames=lambda: SimpleNamespace(append=lambda frame: None),
                                  loadComponentFromURL=fail_load)
        services = {'com.sun.star.frame.Desktop': desktop, 'com.sun.star.frame.Frame': frame,
                    'com.sun.star.awt.Toolkit': SimpleNamespace(createSystemChild=lambda *args: peer)}
        context = SimpleNamespace(ServiceManager=SimpleNamespace(createInstanceWithContext=lambda name, ctx: services[name]))
        uno = SimpleNamespace(Any=lambda name, value: value, createUnoStruct=lambda name: SimpleNamespace())
        backend = native.UnoBackend(self.payload / 'Office', uno_loader=lambda: uno,
                                    connector=lambda *args: context,
                                    window_api=SimpleNamespace(validate_parent=lambda hwnd: None))
        backend.process = process
        backend.profile = SimpleNamespace(name=str(self.profile))
        backend._start_runtime = lambda: None
        evidence = self.root / 'evidence'
        with patch.dict(os.environ, {'OPENGEUL_SUITE_DIAGNOSTICS': str(evidence)}), \
                patch.object(backend, '_bootstrap_ui', return_value=None), \
                patch.object(native, 'make_interceptor', return_value=object()), \
                patch.object(native, 'make_interaction_handler', return_value=object()), redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError) as caught:
                backend.attach(123, {'factory': 'private:factory/scalc', 'displayName': 'OpenGeul Calc'},
                               640, 480, self.root / 'test.xlsx')
        self.assertIs(original, caught.exception)
        events = [json.loads(line) for line in next(evidence.glob('*/events.jsonl')).read_text().splitlines()]
        self.assertEqual(['before-ui-bootstrap', 'after-ui-bootstrap', 'before-load', 'load-exception'],
                         [event['phase'] for event in events])
        self.assertTrue(events[0]['processes'][0]['alive'])
        self.assertEqual(0xC0000005, events[-1]['processes'][0]['exitCode'])
        backend.diagnostics.close()


if __name__ == '__main__':
    unittest.main()
