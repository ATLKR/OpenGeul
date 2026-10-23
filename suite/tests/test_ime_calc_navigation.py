"""The real bounded navigation policy with synthetic native/RPC boundaries."""
import copy
import importlib.util
from pathlib import Path
import sys
import struct
import tempfile
from types import SimpleNamespace as NS
import unittest

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(Path(__file__).parent))
import calc_model_barrier
import writer_model_reader as model
from test_calc_model_barrier import observation, workbook
from test_calc_initial_selection_program import Proxy, area
import test_calc_pending_input as pending_fixtures
from test_writer_model_barrier import (original_shell_fixture,
    retime_native_cleanup_fixture, synthetic_frame)
from test_writer_model_reader import cleanup_fixture

SOURCE = E2E / 'ime_calc_navigation.py'
api = None
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('calc_navigation_tested', SOURCE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)


def navigation_fixture(directory, binding=None):
    frame = synthetic_frame(Path(directory) / 'Suite', 'unused')
    if binding is not None:
        frame.binding.update(binding)
    source = Path(directory) / 'OpenGeul-calc.xlsx'
    original = workbook()
    source.write_bytes(original)
    frame.binding['documentUrl'] = source.as_uri()
    baseline = calc_model_barrier.baseline_from_ooxml(original)
    pending = pending_fixtures.PendingInputTests()
    pending.setUp()
    try:
        absent = pending.reader().read()
    finally:
        pending.doCleanups()
    absent['childHwnd'] = frame.binding['childHwnd']

    def row(sequence, column, line):
        value = observation(frame, baseline['a1Text'], 1.1 + sequence * .3,
                            1.2 + sequence * .3, False)
        value['pendingInput'] = copy.deepcopy(absent)
        selected = Proxy(getRangeAddress=lambda: area(column, line))
        clock = lambda: (value['readStartedAt'] + value['readFinishedAt']) / 2
        function = model.read_calc_initial_selection if sequence == 0 else model.read_calc_selection
        selection = function(Proxy(getSelection=lambda: selected), deadline=10.,
                             proxy_type=Proxy, clock=clock)
        proof = selection['shapeWitness']
        identity = value['unoSnapshots']['before']['proxyIdentity']
        proof.update(helperPid=value['readerProcess']['pid'],
                     controllerId=identity['retainedIds']['controller'])
        for key in ('proxyTypeId', 'proxyTypeName', 'proxyTypeModule'):
            proof[key] = identity[key]
        for call in proof['calls']:
            if isinstance(call['result'], dict) and 'typeId' in call['result']:
                call['result']['typeId'] = identity['proxyTypeId']
        contract = model._CALC_PENDING_INITIAL_CONTRACT
        value.update(kind=contract.kind, operations=list(contract.operations),
            calcSelectionPhase=dict(program='calc-a1-b1-c1-d1-pending-initial-selection-v2',
                requestAction='start' if sequence == 0 else 'read',
                requestSequence=sequence, phase='initial' if sequence == 0 else 'strict'))
        value['calcInitialSelection' if sequence == 0 else 'calcSelection'] = selection
        return value

    initial, selected = row(0, 5, 7), row(1, 0, 0)
    cleanup = cleanup_fixture(frame.binding, str(frame.suite))
    cleanup.update(kind='owned-calc-pending-initial-program-reader-cleanup',
                   startedAt=2., finishedAt=2.1, deadline=10.)
    retime_native_cleanup_fixture(cleanup)
    native = {key: frame.binding[key] for key in (
        'shellPid', 'shellCreationTime', 'officePid', 'officeCreationTime',
        'expectedImage', 'suiteHwnd', 'parentHwnd', 'childHwnd', 'rootHwnd')}
    return NS(frame=frame, source=source, original=original, baseline=baseline,
              initial=initial, selected=selected, row=row, cleanup=cleanup,
              native=native, shell=original_shell_fixture(frame.binding, frame.suite))


def navigate_session(session):
    """Use complete real-policy receipts when older session fixtures reach Calc."""
    data = navigation_fixture(session.process.opengeul_evidence_output, session.binding)
    data.shell['handleValue'] = session.shell['handleValue']
    def factory(*args, **kwargs):
        def start(deadline):
            session.clock.now = 1.2
            return data.initial
        def read(deadline):
            session.clock.now = 1.5
            return data.selected
        def close(deadline):
            session.clock.now = 2.2
            return data.cleanup
        return NS(start=start, read=read, close=close)
    return session.navigate_calc(data.frame.suite, data.source, data.original,
        original_shell=data.shell, reader_factory=factory)


class CalcNavigationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'Missing fixed Calc pre-F2 source selection barrier')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = navigation_fixture(self.temp.name)
        self.now = 1.
        self.calls = []
        self.record = {}
        self.change = None
        self.start_error = self.read_error = self.close_error = None

    def factory(self, *args, **kwargs):
        self.calls.append(('construct', kwargs))
        def start(deadline):
            self.calls.append(('start', deadline))
            if self.start_error: raise self.start_error
            self.now = 1.2
            return self.data.initial
        def read(deadline):
            self.calls.append(('read', deadline))
            if self.read_error: raise self.read_error
            self.now = 1.5
            return self.data.selected
        def close(deadline):
            self.calls.append(('close', deadline))
            if self.close_error: raise self.close_error
            self.now = 2.2
            return self.data.cleanup
        return NS(start=start, read=read, close=close)

    def home(self):
        self.calls.append(('CTRL_HOME',))
        if self.change: self.change()
        events = [dict(vk=0, scan=29, flags=8), dict(vk=0, scan=71, flags=9),
                  dict(vk=0, scan=71, flags=11), dict(vk=0, scan=29, flags=10)]
        native = self.data.native
        edge = dict(shell=dict(pid=native['shellPid'], creationTime=native['shellCreationTime'],
            image=str(self.data.frame.suite / 'OpenGeul.Office.exe'), waitResult=258, handleValue=901),
            engine=dict(pid=native['officePid'], creationTime=native['officeCreationTime'],
                        image=native['expectedImage'], waitResult=258, handleValue=902))
        return dict(shortcut='CTRL_HOME', requestedInputs=4, insertedInputs=4,
            inputCallAttempts=1, startedAt=1.25, finishedAt=1.3, deadline=10.,
            events=events, before=copy.deepcopy(edge), after=copy.deepcopy(edge),
            bufferHex=b''.join(struct.pack('<I4xHHII4xQ8x', 1,
                x['vk'], x['scan'], x['flags'], 0, 0) for x in events).hex())

    def run_navigation(self, **changes):
        self.now = 1.
        self.calls = []
        data = self.data
        options = dict(original_shell=data.shell, expected_native=data.native,
            require_current=lambda: self.calls.append(('guard',)), send_home=self.home,
            reader_factory=self.factory, clock=lambda: self.now)
        options.update(changes)
        return api.observe_calc_navigation(data.frame.suite, data.source,
            data.original, self.record, 10., **options)

    def test_f8_initial_then_source_strict_a1_and_release_finish_before_f2(self):
        value = self.run_navigation()
        self.assertTrue(value['success'])
        self.assertEqual([x[0] for x in self.calls if x[0] != 'guard'],
                         ['construct', 'start', 'CTRL_HOME', 'read', 'close'])
        self.assertEqual(value['initial']['calcInitialSelection']['ranges'],
            [dict(sheet=0, startColumn=5, startRow=7, endColumn=5, endRow=7)])
        self.assertEqual(value['afterCtrlHome']['calcSelection']['range'],
            dict(sheet=0, startColumn=0, startRow=0, endColumn=0, endRow=0))
        self.assertEqual([x[1] for x in self.calls if x[0] in ('start', 'read', 'close')], [10., 10., 10.])
        self.assertEqual(self.calls[0][0], 'guard')

    def test_still_f8_after_home_is_fatal_and_reader_is_closed_once(self):
        self.data.selected = self.data.row(1, 5, 7)
        with self.assertRaisesRegex(AssertionError, 'A1'):
            self.run_navigation()
        self.assertFalse(self.record['calcNavigationContext']['success'])
        self.assertEqual([x[0] for x in self.calls].count('CTRL_HOME'), 1)
        self.assertEqual([x[0] for x in self.calls].count('close'), 1)

    def test_missing_or_ambiguous_selection_never_certifies_navigation(self):
        for field in ('calcSelection', 'calcSelectionPhase', 'ambiguous'):
            with self.subTest(field=field):
                original = self.data.selected
                self.data.selected = copy.deepcopy(original)
                if field == 'ambiguous':
                    self.data.selected['calcSelection'] = copy.deepcopy(self.data.initial['calcInitialSelection'])
                else:self.data.selected.pop(field)
                with self.assertRaises((AssertionError, KeyError)):
                    self.run_navigation()
                self.data.selected = original
                self.record = {}

    def test_native_generation_profile_url_or_grid_drift_is_fatal(self):
        mutations = [lambda r: r['bindingBefore'].update(officeCreationTime=333),
            lambda r: r['bindingAfter'].update(documentUrl='file:///wrong.xlsx'),
            lambda r: r['nativeSnapshots']['helperAfter'].update(profileUrl='file:///C:/other'),
            lambda r: r.update(a1Text='changed'), lambda r: r.update(isModified=True)]
        for change in mutations:
            with self.subTest(change=change):
                original = self.data.selected
                self.data.selected = copy.deepcopy(original)
                change(self.data.selected)
                with self.assertRaises((AssertionError, KeyError)):
                    self.run_navigation()
                self.data.selected = original
                self.record = {}

    def test_wrong_rpc_action_sequence_or_initial_phase_is_fatal(self):
        for field, value in [('requestAction', 'start'), ('requestSequence', 2),
                             ('requestSequence', True), ('phase', 'initial')]:
            with self.subTest(field=field, value=value):
                original = self.data.selected
                self.data.selected = copy.deepcopy(original)
                self.data.selected['calcSelectionPhase'][field] = value
                with self.assertRaises(AssertionError): self.run_navigation()
                self.data.selected = original
                self.record = {}

    def test_selected_read_must_follow_actual_home_not_just_have_a1_values(self):
        self.data.selected['readStartedAt'] = 1.1
        with self.assertRaises(AssertionError): self.run_navigation()

    def test_failed_start_or_read_retains_primary_and_still_closes_owned_helper(self):
        for stage in ('start_error', 'read_error'):
            with self.subTest(stage=stage):
                error = RuntimeError('original RPC failure')
                setattr(self, stage, error)
                self.close_error = RuntimeError('secondary release failure')
                with self.assertRaises(RuntimeError) as caught: self.run_navigation()
                self.assertIs(caught.exception, error)
                self.assertIn('secondary release', self.record['calcNavigationContext']['cleanupErrors'][0])
                self.assertFalse(self.record['calcNavigationContext']['success'])
                setattr(self, stage, None)
                self.record = {}

    def test_release_failure_or_job_nonempty_is_fatal_even_after_strict_a1(self):
        for mode in ('exception', 'physical', 'job', 'handle'):
            with self.subTest(mode=mode):
                cleanup = self.data.cleanup
                self.data.cleanup = copy.deepcopy(cleanup)
                if mode == 'exception': self.close_error = RuntimeError('release failed')
                elif mode == 'physical': self.data.cleanup['physicalCleanupSucceeded'] = False
                elif mode == 'job': self.data.cleanup['finalJobPids'] = [999]
                else: self.data.cleanup['handleClosures'][0]['result'] = False
                with self.assertRaises((AssertionError, RuntimeError)): self.run_navigation()
                self.assertFalse(self.record['calcNavigationContext']['success'])
                self.data.cleanup = cleanup; self.close_error = None; self.record = {}

    def test_original_deadline_and_file_bytes_cannot_be_renewed_or_changed(self):
        self.change = lambda: setattr(self, 'now', 10.)
        with self.assertRaises((AssertionError, TimeoutError)): self.run_navigation()
        self.assertEqual(self.record['calcNavigationContext']['readerDeadline'], 10.)
        self.record = {}; self.now = 1.; self.change = lambda: self.data.source.write_bytes(b'changed')
        with self.assertRaises(AssertionError): self.run_navigation()

    def test_no_home_input_when_initial_witness_or_inventory_is_invalid(self):
        self.data.initial['calcSelectionPhase']['requestSequence'] = 1
        with self.assertRaises(AssertionError): self.run_navigation()
        self.assertNotIn(('CTRL_HOME',), self.calls)

    def test_replay_rejects_success_flag_without_complete_barrier(self):
        context = self.run_navigation()
        for field in ('initial', 'afterCtrlHome', 'cleanup', 'homeCommand'):
            with self.subTest(field=field):
                changed = copy.deepcopy(context); changed.pop(field)
                with self.assertRaises((AssertionError, KeyError)):
                    api.require_calc_navigation(changed, suite=self.data.frame.suite,
                        expected_native=self.data.native, expected_url=self.data.source.as_uri(), setup_deadline=10., now=2.3)

    def test_replay_rejects_widened_key_budget_and_boolean_native_binding(self):
        context = self.run_navigation()
        changed = copy.deepcopy(context);changed['homeCommand']['deadline'] = 11.
        with self.assertRaises(AssertionError):
            api.require_calc_navigation(changed, suite=self.data.frame.suite,
                expected_native=self.data.native, expected_url=self.data.source.as_uri(), setup_deadline=10., now=2.3)
        native = dict(self.data.native, rootHwnd=True)
        with self.assertRaises(AssertionError):
            api.require_calc_navigation(context, suite=self.data.frame.suite,
                expected_native=native, expected_url=self.data.source.as_uri(), setup_deadline=10., now=2.3)


class KeyboardNavigationTests(unittest.TestCase):
    def session(self, directory):
        from test_ime_keyboard_session import IMEKeyboardSessionTests
        fixture = IMEKeyboardSessionTests()
        self.addCleanup(fixture.doCleanups)
        session, process, binding, boundary, clock, probe, record = fixture.fixture(directory, 'calc')
        session.start(); session.focus_editor(6.); fixture.ready(session)
        data = navigation_fixture(directory, binding)
        data.shell['handleValue'] = session.shell['handleValue']
        order = []
        probe.after_send = lambda: order.append(session.receipt['actions'][-1]['shortcut'])
        def factory(*args, **kwargs):
            self.assertEqual(kwargs['getter_contract'], 'calc-a1-b1-c1-d1-pending-initial-selection-v2')
            def start(deadline):
                order.append('start0'); clock.now = 1.2
                return data.initial
            def read(deadline):
                order.append('read1'); clock.now = 1.5
                return data.selected
            def close(deadline):
                order.append('release2'); clock.now = 2.2
                return data.cleanup
            return NS(start=start, read=read, close=close)
        return session, data, probe, record, factory, order

    def navigate(self, session, data, factory):
        method = getattr(session, 'navigate_calc', None)
        self.assertTrue(callable(method), 'Calc keys need a fixed source-bound navigation phase')
        return method(data.frame.suite, data.source, data.original,
                      original_shell=data.shell, reader_factory=factory)

    def test_real_session_places_source_barrier_between_the_same_single_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            session, data, probe, record, factory, order = self.session(directory)
            self.navigate(session, data, factory)
            self.assertEqual(order, ['start0', 'CTRL_HOME', 'read1', 'release2', 'F2', 'CTRL_END'])
            self.assertEqual([a['shortcut'] for a in session.receipt['actions']],
                             ['CTRL_F6', 'CTRL_HOME', 'F2', 'CTRL_END'])
            self.assertEqual([len(raw) for _, raw, _ in probe.sent], [160, 160, 80, 160])
            self.assertEqual(session.phase, 'navigated')
            self.assertTrue(record['calcNavigationContext']['success'])
            session.close(RuntimeError('bounded pre-prefix test ends here'))

    def test_unproved_calc_navigation_cannot_reach_navigated(self):
        with tempfile.TemporaryDirectory() as directory:
            session, data, probe, record, factory, order = self.session(directory)
            with self.assertRaises(AssertionError): session.navigate()
            self.assertEqual(order, [])
            self.assertNotEqual(session.phase, 'navigated')
            session.close()

    def test_still_f8_or_bad_release_blocks_f2_in_real_session(self):
        for mode in ('f8', 'release'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                session, data, probe, record, factory, order = self.session(directory)
                if mode == 'f8': data.selected = data.row(1, 5, 7)
                else: data.cleanup['physicalCleanupSucceeded'] = False
                with self.assertRaises(AssertionError): self.navigate(session, data, factory)
                self.assertEqual(order, ['start0', 'CTRL_HOME', 'read1', 'release2'])
                self.assertEqual([a['shortcut'] for a in session.receipt['actions']], ['CTRL_F6', 'CTRL_HOME'])
                session.close()

    def test_navigation_context_identity_and_native_generation_are_live_guards(self):
        for mode in ('replace', 'birth', 'deadline', 'url'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                session, data, probe, record, factory, order = self.session(directory)
                def mutate():
                    order.append('CTRL_HOME')
                    if mode == 'replace': record['calcNavigationContext'] = copy.deepcopy(record['calcNavigationContext'])
                    elif mode == 'birth': probe.engine['creationTime'] += 1
                    elif mode == 'deadline': record['calcNavigationContext']['readerDeadline'] += 1
                    else: record['calcNavigationContext']['expectedUrl'] = 'file:///foreign.xlsx'
                probe.after_send = mutate
                with self.assertRaises(AssertionError): self.navigate(session, data, factory)
                self.assertNotIn('F2', order)
                self.assertNotIn('CTRL_END', order)
                session.close()

    def test_writer_and_impress_keep_original_keys_without_a_calc_reader_path(self):
        from test_ime_keyboard_session import IMEKeyboardSessionTests
        for module, expected in [('writer', ['CTRL_F6', 'CTRL_END']),
                                 ('impress', ['CTRL_F6', 'TAB', 'F2', 'CTRL_END'])]:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as directory:
                fixture = IMEKeyboardSessionTests();self.addCleanup(fixture.doCleanups)
                session, process, binding, boundary, clock, probe, record = fixture.fixture(directory, module)
                session.start();session.focus_editor(6.);fixture.ready(session);session.navigate()
                self.assertEqual([x['shortcut'] for x in session.receipt['actions']], expected)
                self.assertNotIn('calcNavigationContext', record)
                self.assertFalse(list(Path(directory).glob('ime-calc-navigation-reader')))
                session.close(RuntimeError('bounded navigation test ends here'))

    def test_pre_semantic_cannot_overlap_navigation_or_precede_its_acknowledgement(self):
        for mode in ('acknowledgement', 'F2', 'PRE'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                session, data, probe, record, factory, order = self.session(directory)
                self.navigate(session, data, factory)
                context = dict(success=True, module='calc', phase='pre', expectedPrefix=None,
                    expectedNative=dict(session.binding), setupDeadline=10., readerDeadline=9.,
                    startedAt=2.2, finishedAt=2.2)
                if mode == 'acknowledgement': session.receipt['calcNavigationReadiness']['acknowledgedAt'] = 2.3
                elif mode == 'F2': session.receipt['actions'][2]['startedAt'] = 2.1
                else: context['startedAt'] = 2.1
                record['imeSemanticContexts'] = [context];record['imeSemanticContext'] = context
                with self.assertRaises(AssertionError): session.semantic_ready(context, phase='pre')
                session.close()


if __name__ == '__main__':
    unittest.main()
