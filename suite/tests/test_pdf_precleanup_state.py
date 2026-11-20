"""Synthetic retained-HANDLE diagnostics; no Windows or PDF qualification claim."""
import importlib.util
from pathlib import Path
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'pdf_export_smoke.py'
spec = importlib.util.spec_from_file_location('pdf_precleanup_smoke', SOURCE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class PdfPrecleanupStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = self.root / 'suite'
        self.output = self.root / 'evidence'
        (self.output / 'sources').mkdir(parents=True)
        (self.output / 'exports').mkdir()

    def engine(self, *, state=None, state_error=None):
        events = []
        state = state if state is not None else dict(
            alive=True, waitResult=258, exitCode=259, getExitCodeProcessResult=True)
        engine = smoke.Engine(self.suite)
        identities = {
            11: (101, dict(pid=11, creationTime=1111,
                           image=str(self.suite / 'Office/program/soffice.exe'))),
            22: (202, dict(pid=22, creationTime=2222,
                           image=str(self.suite / 'Office/program/soffice.bin'))),
        }

        class Api:
            def state(self, handle):
                events.append(('state', handle))
                if state_error is not None:
                    raise state_error
                return state

        class Witness:
            job = 42

            def __init__(self):
                self.api = Api()
                self.members = identities

            def snapshot(self):
                # Opening/discovering another member after startup is forbidden.
                if 'startup-snapshot' in events:
                    raise AssertionError('Unexpected member discovery')
                events.append('startup-snapshot')
                return [dict(identity, alive=True, exitCode=259)
                        for handle, identity in self.members.values()]

        witness = Witness()

        class Process:
            job = 42

            def open_diagnostic_witnesses(self):
                events.append('startup-retain')
                return witness

        engine.process = Process()
        with patch.object(smoke.baseline.Engine, 'start', lambda self: None):
            engine.start()
        return engine, events

    def observe(self, engine):
        self.assertTrue(hasattr(engine, '_observe_initial_load_failure'))
        return engine._observe_initial_load_failure()

    def test_original_engine_retained_state_is_read_once_without_discovery(self):
        for alive, waited, code in ((True, 258, 259), (False, 0, 0), (False, 0, 259)):
            with self.subTest(alive=alive, waited=waited, code=code):
                engine, events = self.engine(state=dict(alive=alive, waitResult=waited,
                    exitCode=code, getExitCodeProcessResult=True,
                    exitCodeHex='not part of the numeric observation'))
                before = list(events)
                result = self.observe(engine)
                self.assertEqual(events, before + [('state', 202)])
                self.assertEqual(result, dict(schemaVersion=1, diagnosticOnly=True,
                    acceptanceEligible=False, roleCode=2, bindingVerified=True,
                    pid=22, creationTime=2222, stateCallAttempted=True,
                    stateCallReturned=True, alive=alive, waitResult=waited,
                    getExitCodeProcessResult=True, exitCode=code, probeErrorCode=0))
                self.assertFalse(engine.owned_job_evidence['jobEmptyVerified'])
                self.assertNotIn('final', engine.owned_job_evidence)
                self.assertTrue(all(value is None or type(value) in (int, bool)
                                    for value in result.values()))

    def test_replaced_binding_never_adopts_launcher_or_new_engine(self):
        for defect in ('handle', 'birth', 'image', 'pid', 'process', 'job',
                       'witness-job', 'api', 'missing', 'witness'):
            with self.subTest(defect=defect):
                engine, events = self.engine()
                witness = engine.witness
                handle, identity = witness.members[22]
                if defect == 'handle':
                    witness.members[22] = (303, identity)
                elif defect in ('birth', 'image', 'pid'):
                    changed = dict(identity)
                    changed[dict(birth='creationTime', image='image', pid='pid')[defect]] = {
                        'birth': 2223, 'image': str(self.suite / 'other/soffice.bin'), 'pid': True}[defect]
                    witness.members[22] = (handle, changed)
                elif defect == 'process':
                    engine.process = SimpleNamespace(job=42)
                elif defect == 'job':
                    engine.process.job = 43
                elif defect == 'witness-job':
                    witness.job = 43
                elif defect == 'api':
                    witness.api = SimpleNamespace(state=lambda handle: self.fail('Replaced API'))
                elif defect == 'missing':
                    del witness.members[22]
                    witness.members[33] = (303, dict(identity, pid=33, creationTime=3333))
                else:
                    engine.witness = SimpleNamespace(job=42, members=witness.members, api=witness.api)
                result = self.observe(engine)
                self.assertEqual(events, ['startup-retain', 'startup-snapshot'])
                self.assertEqual(result['probeErrorCode'], 2)
                self.assertFalse(result['bindingVerified'])
                self.assertFalse(result['stateCallAttempted'])
                self.assertIsNone(result['pid'])
                self.assertIsNone(result['alive'])

    def test_unavailable_startup_anchor_has_no_probe_or_successful_state(self):
        engine, events = self.engine()
        engine._initial_load_anchor = None
        result = self.observe(engine)
        self.assertEqual(result['probeErrorCode'], 1)
        self.assertEqual(events, ['startup-retain', 'startup-snapshot'])
        self.assertIsNone(result['exitCode'])
        self.assertIsNone(result['getExitCodeProcessResult'])

    def test_state_failure_and_malformed_results_remain_unknown_and_numeric(self):
        engine, events = self.engine(state_error=OSError('synthetic private detail'))
        result = self.observe(engine)
        self.assertEqual(result['probeErrorCode'], 3)
        self.assertTrue(result['stateCallAttempted'])
        self.assertFalse(result['stateCallReturned'])
        self.assertIsNone(result['alive'])
        self.assertIsNone(result['getExitCodeProcessResult'])
        self.assertIsNone(result['exitCode'])
        good = dict(alive=True, waitResult=258, exitCode=259, getExitCodeProcessResult=True)
        for field, value in (('alive', 1), ('waitResult', True), ('waitResult', 1),
                             ('exitCode', True), ('exitCode', -1), ('exitCode', 2**32),
                             ('getExitCodeProcessResult', 1), ('getExitCodeProcessResult', False),
                             ('alive', False)):
            with self.subTest(field=field, value=value):
                engine, events = self.engine(state=dict(good, **{field: value}))
                result = self.observe(engine)
                self.assertEqual(result['probeErrorCode'], 4)
                self.assertTrue(result['stateCallReturned'])
                self.assertIsNone(result['alive'])
                self.assertIsNone(result['exitCode'])

    def run_case(self, engine, events, *, load_error=None, observer_error=None,
                 fail_on_load=1, cleanup_error=False):
        path = self.output / 'exports/writer.pdf'
        document = SimpleNamespace(url='', getURL=lambda: document.url,
                                   storeToURL=lambda url, props: path.write_bytes(b'%PDF-1.7\nsynthetic'))
        primary = []
        loads = 0

        def load(url):
            nonlocal loads
            loads += 1
            events.append('first-load' if not any(item == 'first-load' for item in events) else 'reopen')
            if load_error is not None and loads == fail_on_load:
                raise load_error
            document.url = url
            return document

        def error(exc):
            primary.append((exc, [row.name for row in traceback.extract_tb(exc.__traceback__)]))
            return dict(type=type(exc).__name__)

        def store(document, source, source_filter):
            source.write_bytes(b'synthetic source')
            document.url = source.as_uri()

        def cleanup():
            events.append('cleanup')
            if cleanup_error:
                engine.cleanup_errors.append('synthetic cleanup failure')
                return
            initial = engine.owned_job_evidence['initial']
            engine.owned_job_evidence.update(final=[dict(row, alive=False, exitCode=0)
                for row in initial], finalJobPids=[], jobEmptyVerified=True,
                shutdown='graceful', forcedTermination=False)

        engine.load = load
        engine.start = lambda: events.append('already-started')
        engine.close_document = lambda doc: events.append('close-document')
        engine.cleanup = cleanup
        engine.store_new = store
        engine.prop = lambda key, value: (key, value)
        engine.uno = SimpleNamespace(Any=lambda name, value: SimpleNamespace(
            type=SimpleNamespace(typeName=name), value=value))
        if observer_error is not None:
            engine._observe_initial_load_failure = lambda: (_ for _ in ()).throw(observer_error)
        with patch.object(smoke, 'Engine', lambda suite: engine), \
                patch.object(smoke, '_require_font', lambda engine: None), \
                patch.object(smoke, '_populate', lambda *args: None), \
                patch.object(smoke, '_validate_model', lambda *args: None), \
                patch.object(smoke, '_interaction_handler', lambda: None), \
                patch.object(smoke, '_error', error):
            result = smoke.run_case(self.suite, self.output, smoke.case_specs()[0])
        return result, primary

    def test_load_failure_observation_precedes_unchanged_close_and_cleanup(self):
        engine, events = self.engine(state=dict(alive=False, waitResult=0,
            exitCode=0, getExitCodeProcessResult=True))
        failure = RuntimeError('synthetic load failure')
        result, primary = self.run_case(engine, events, load_error=failure)
        self.assertIs(primary[0][0], failure)
        self.assertEqual(primary[0][1][-1], 'load')
        self.assertEqual(events[-4:], ['first-load', ('state', 202), 'close-document', 'cleanup'])
        self.assertEqual(result['initialLoadFailureState']['exitCode'], 0)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['ownedEngineClosed'])

    def test_observer_baseexception_does_not_replace_primary_or_skip_cleanup(self):
        engine, events = self.engine()
        failure = RuntimeError('synthetic primary')
        result, primary = self.run_case(engine, events, load_error=failure,
                                        observer_error=KeyboardInterrupt('synthetic observer'))
        self.assertIs(primary[0][0], failure)
        self.assertEqual(primary[0][1][-1], 'load')
        self.assertIn('initialLoadFailureState', result)
        self.assertEqual(result['initialLoadFailureState']['probeErrorCode'], 5)
        self.assertIsNone(result['initialLoadFailureState']['exitCode'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(events[-2:], ['close-document', 'cleanup'])

    def test_success_has_no_diagnostic_state_call_or_failure_field(self):
        engine, events = self.engine(state_error=AssertionError('No probe on success'))
        result, primary = self.run_case(engine, events)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(primary, [])
        self.assertNotIn('initialLoadFailureState', result)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'state' for event in events))
        self.assertEqual(events[-1], 'cleanup')

    def test_later_reopen_failure_is_not_relabelled_as_initial_load_failure(self):
        engine, events = self.engine(state_error=AssertionError('No probe on reopen failure'))
        failure = RuntimeError('synthetic reopen failure')
        result, primary = self.run_case(engine, events, load_error=failure, fail_on_load=2)
        self.assertIs(primary[0][0], failure)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('initialLoadFailureState', result)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'state' for event in events))

    def test_unknown_observation_cannot_qualify_failed_cleanup(self):
        engine, events = self.engine(state_error=OSError('synthetic observer failure'))
        failure = RuntimeError('synthetic primary')
        result, primary = self.run_case(engine, events, load_error=failure, cleanup_error=True)
        self.assertIs(primary[0][0], failure)
        self.assertEqual(result['initialLoadFailureState']['probeErrorCode'], 3)
        self.assertIsNone(result['initialLoadFailureState']['alive'])
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['ownedEngineClosed'])
        self.assertEqual(result['cleanupErrors'], ['synthetic cleanup failure'])
        self.assertFalse(result['ownedJobEvidence']['jobEmptyVerified'])


if __name__ == '__main__':
    unittest.main()
