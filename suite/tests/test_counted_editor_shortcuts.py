"""Counted navigation policy and native ABI; no Windows input is exercised here."""
import copy
import ctypes
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
SOURCE = E2E / 'counted_editor_shortcuts.py'
if SOURCE.is_file():
    SPEC = importlib.util.spec_from_file_location('counted_shortcuts_tested', SOURCE)
    shortcuts = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(shortcuts)
else:
    shortcuts = None


class Clock:
    def __init__(self): self.now = 1.
    def __call__(self): return self.now


class Probe:
    """Finite native boundary double; all policy and receipt code stays real."""
    def __init__(self, process, binding, clock):
        self.process, self.binding, self.clock = process, binding, clock
        self.calls, self.sent, self.counts = [], [], []
        self.shell = dict(pid=77, handleValue=2**40, creationTime=binding['shellCreationTime'],
                          image=str(process.opengeul_suite_root / 'OpenGeul.Office.exe'), waitResult=258)
        self.engine = dict(pid=88, handleValue=2**41, creationTime=binding['officeCreationTime'],
                           image=binding['expectedImage'], waitResult=258)
        self.layout = self.current_layout = 0x04090409
        self.keys_down = []; self.caps = self.scroll = False
        self.focus = 33; self.thread = 44; self.capture = 0; self.foreground = 11
        self.ancestry = True; self.close_result = True; self.open_after = self.after_send = None
    def process_snapshot(self, process):
        self.calls.append('shell')
        return copy.deepcopy(self.shell)
    def open_engine(self, pid):
        self.calls.append(('open', pid))
        if self.open_after: self.open_after()
        return self.engine['handleValue']
    def engine_snapshot(self, handle):
        self.calls.append(('engine', handle))
        return copy.deepcopy(self.engine)
    def scope_snapshot(self, api, binding):
        self.calls.append('scope')
        def window(handle, pid):
            return dict(hwnd=handle, isWindow=bool(handle), pid=pid, threadId=self.thread if pid == 88 else 45,
                        rootHwnd=11 if handle in (11, 12, 22, 33) else handle, className='owned-native-window')
        edge = dict(suite=window(11, 77), editor=window(22, 88),
                    foreground=window(self.foreground, 77), editorWithinSuite=self.ancestry)
        return dict(before=copy.deepcopy(edge), after=copy.deepcopy(edge),
                    queryAttempted=True, querySucceeded=True, queriedThreadId=self.thread,
                    cbSize=72, lastError=0, focus=window(self.focus, 88), focusWithinEditor=True,
                    capture=dict(hwnd=self.capture), parent=window(12, 77),
                    suiteOwnsParent=self.ancestry, parentOwnsChild=self.ancestry,
                    parentVisible=True, parentEnabled=True, childVisible=True, childEnabled=True)
    def keyboard_snapshot(self, thread):
        self.calls.append(('keyboard', thread))
        return dict(targetLayout=self.layout, currentThreadLayout=self.current_layout,
                    keysDown=list(self.keys_down), capsLockOn=self.caps,
                    scrollLockOn=self.scroll, numLockOn=True)
    def send(self, payload):
        raw = bytes(payload); self.sent.append((len(payload), raw, ctypes.sizeof(payload._type_)))
        self.calls.append(('send', len(payload)))
        # Native effects require an actual closed intent file, not a mock write.
        intents = list(self.process.opengeul_evidence_output.glob('*-input-intent.json'))
        assert intents and any(json.loads(p.read_bytes())['actions'][-1]['bufferHex'] == raw.hex()
                               for p in intents)
        value = self.counts.pop(0) if self.counts else len(payload)
        if isinstance(value, BaseException): raise value
        if self.after_send: self.after_send()
        return value
    def release(self, payload):
        self.sent.append((len(payload), bytes(payload), ctypes.sizeof(payload._type_)))
        self.calls.append(('release', len(payload)))
        value = self.counts.pop(0) if self.counts else len(payload)
        if isinstance(value, BaseException): raise value
        return value
    def close_engine(self, handle):
        self.calls.append(('close', handle))
        if isinstance(self.close_result, BaseException): raise self.close_result
        return self.close_result


class CountedEditorShortcutsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shortcuts, 'Missing counted native editor shortcut policy')
    def fixture(self, directory):
        output = Path(directory).resolve(); suite = output / 'Suite'; suite.mkdir()
        process = NS(pid=77, _handle=2**40, args=[str(suite / 'OpenGeul.Office.exe')],
                     opengeul_suite_root=suite, opengeul_evidence_output=output,
                     opengeul_evidence_case='counted-case')
        binding = dict(shellPid=77, shellCreationTime=134370146610049226,
                       officePid=88, officeCreationTime=134370146624845933,
                       expectedImage=str(suite / 'Office/program/soffice.bin'),
                       suiteHwnd=11, parentHwnd=12, childHwnd=22, rootHwnd=11)
        process.opengeul_activation_binding = (77, 2**40, str(suite / 'OpenGeul.Office.exe'),
                                               binding['shellCreationTime'], 258)
        api = NS(require_editor_focus=lambda hwnd, child: 33,
                 require_foreground=lambda hwnd: None)
        clock = Clock(); probe = Probe(process, binding, clock); record = {}
        return process, binding, api, clock, probe, record
    def session(self, fixture):
        p, b, api, clock, probe, record = fixture
        return shortcuts.CountedEditorShortcuts(api, p, b, record, 10., probe=probe, clock=clock)
    def full(self, session):
        session.navigate('^{HOME}')
        session.navigate('{F2}^{END}')
    def test_generation_ledger_preserves_first_admission_time_without_a_handle_or_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            p,b,api,clock,probe,record=self.fixture(directory)
            self.assertIsNone(shortcuts.join_shortcut_generation(p,12,22,probe.engine))
            first=shortcuts.admit_shortcut_generation(p,12,22,probe.engine,1.)
            self.assertEqual(first['generation'],[88,b['expectedImage'],134370146624845933])
            self.assertEqual(first['firstAdmittedAt'],1.)
            self.assertNotIn('handleValue',first)
            first['generation'][2]+=1
            second=shortcuts.admit_shortcut_generation(p,12,22,probe.engine,9.)
            self.assertEqual(second['generation'][2],134370146624845933)
            self.assertEqual(second['firstAdmittedAt'],1.)
            self.assertEqual(probe.sent,[])
    def test_reader_admission_rejects_replacement_after_an_earlier_shortcut_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=self.fixture(directory);p,b,api,clock,probe,record=fixture
            shortcuts.admit_shortcut_generation(p,12,22,probe.engine,1.)
            b['officeCreationTime']+=1;probe.engine['creationTime']+=1
            with self.assertRaisesRegex(AssertionError,'Earlier shortcut engine generation changed'):
                with self.session(fixture):self.fail('Replaced engine was admitted')
            self.assertEqual(probe.sent,[])
            self.assertEqual(sum(c==('open',88) for c in probe.calls),1)
            self.assertEqual(sum(c==('close',2**41) for c in probe.calls),1)
    def test_corrupt_prior_admission_cannot_be_joined_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            p,b,api,clock,probe,record=self.fixture(directory)
            shortcuts.admit_shortcut_generation(p,12,22,probe.engine,1.)
            p.opengeul_editor_shortcut_admissions[(12,22,88)]['generation'][2]+=1
            for operation in (lambda:shortcuts.join_shortcut_generation(p,12,22,probe.engine),
                              lambda:shortcuts.admit_shortcut_generation(p,12,22,probe.engine,9.)):
                with self.assertRaisesRegex(AssertionError,'admission changed'):operation()
    def test_different_pid_cannot_readmit_same_original_parent_child_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            p,b,api,clock,probe,record=self.fixture(directory)
            shortcuts.admit_shortcut_generation(p,12,22,probe.engine,1.)
            other=dict(probe.engine,pid=99)
            for operation in (lambda:shortcuts.join_shortcut_generation(p,12,22,other),
                              lambda:shortcuts.admit_shortcut_generation(p,12,22,other,9.)):
                with self.assertRaisesRegex(AssertionError,'slot.*PID|PID.*slot'):operation()
    def test_exact_scan_plans_and_independent_win64_bytes(self):
        self.assertEqual(ctypes.sizeof(shortcuts.Input), 40)
        self.assertEqual(shortcuts.Input.payload.offset, 8)
        plan = shortcuts.shortcut_events('CTRL_HOME')
        self.assertEqual(plan, [dict(vk=0, scan=0x1d, flags=8), dict(vk=0, scan=0x47, flags=9),
                                dict(vk=0, scan=0x47, flags=11), dict(vk=0, scan=0x1d, flags=10)])
        raw = b''.join(struct.pack('<I4xHHII4xQ8x', 1, 0, e['scan'], e['flags'], 0, 0) for e in plan)
        self.assertEqual(bytes(shortcuts.input_buffer(plan)), raw)
        self.assertEqual(shortcuts.shortcut_events('F2'), [dict(vk=0, scan=0x3c, flags=8), dict(vk=0, scan=0x3c, flags=10)])
        self.assertEqual([e['scan'] for e in shortcuts.shortcut_events('CTRL_END')], [0x1d, 0x4f, 0x4f, 0x1d])
        for value in ('^s', 'ESC', 'CTRL_HOME CTRL_HOME', '', None):
            with self.subTest(value=value), self.assertRaises((ValueError, AssertionError)):
                shortcuts.shortcut_events(value)
    def test_shared_leaf_presets_are_exact_without_expanding_calc_navigation(self):
        expected = {'CTRL_F6': [(0x1d, 8), (0x40, 8), (0x40, 10), (0x1d, 10)],
                    'CTRL_S': [(0x1d, 8), (0x1f, 8), (0x1f, 10), (0x1d, 10)],
                    'CTRL_W': [(0x1d, 8), (0x11, 8), (0x11, 10), (0x1d, 10)],
                    'CTRL_1': [(0x1d, 8), (0x02, 8), (0x02, 10), (0x1d, 10)],
                    'TAB': [(0x0f, 8), (0x0f, 10)], 'ENTER': [(0x1c, 8), (0x1c, 10)]}
        for preset, events in expected.items():
            with self.subTest(preset=preset):
                try:
                    plan = shortcuts.shortcut_events(preset)
                except ValueError as exc:
                    self.fail('Missing authorized exact shared-leaf preset: ' + str(exc))
                self.assertEqual([(e['scan'], e['flags']) for e in plan], events)
                self.assertTrue(all(e['vk'] == 0 and e['flags'] & 8 for e in plan))
        self.assertEqual(shortcuts.ORDER, ('CTRL_HOME', 'F2', 'CTRL_END'))
    def test_owned_control_leaf_plans_do_not_add_calc_actions_or_a_key_parser(self):
        for preset, expected in [('CTRL_SHIFT_S', [(0x1d, 8), (0x2a, 8), (0x1f, 8),
                                                   (0x1f, 10), (0x2a, 10), (0x1d, 10)]),
                                 ('ESCAPE', [(0x01, 8), (0x01, 10)])]:
            with self.subTest(preset=preset):
                try: plan = shortcuts.shortcut_events(preset)
                except ValueError as exc: self.fail('Missing Root-authorized native leaf: ' + str(exc))
                self.assertEqual([(e['scan'], e['flags']) for e in plan], expected)
        self.assertEqual(shortcuts.ORDER, ('CTRL_HOME', 'F2', 'CTRL_END'))
    def test_public_release_plans_validate_known_prefix_and_preserve_extended_keyups(self):
        function = getattr(shortcuts, 'owned_release_events', None)
        self.assertTrue(callable(function), 'Missing shared known-prefix key-up policy')
        events = shortcuts.shortcut_events('CTRL_HOME')
        self.assertEqual(function(events, 2), [dict(vk=0, scan=0x47, flags=11), dict(vk=0, scan=0x1d, flags=10)])
        self.assertEqual(function(events, 0), [])
        self.assertEqual(function(events, len(events)), [])
        for count in (-1, 5, None, True):
            with self.subTest(count=count), self.assertRaises((ValueError, AssertionError)):
                function(events, count)
        with self.assertRaises((ValueError, AssertionError)):
            function([dict(vk=0, scan=0x38, flags=8)], 1)
    def test_three_original_chords_have_durable_intents_one_handle_and_exact_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe, record = fixture[-2:]
            with self.session(fixture) as session: self.full(session)
            receipt, = record['editorShortcutSessions']
            self.assertIs(receipt['success'], True)
            self.assertEqual([a['shortcut'] for a in receipt['actions']], ['CTRL_HOME', 'F2', 'CTRL_END'])
            self.assertEqual([s[0] for s in probe.sent], [4, 2, 4])
            self.assertEqual(sum(isinstance(c, tuple) and c[0] == 'open' for c in probe.calls), 1)
            self.assertEqual(sum(isinstance(c, tuple) and c[0] == 'close' for c in probe.calls), 1)
            self.assertIs(receipt['engineHandleReleased'], True)
            self.assertEqual(receipt['deadline'], 10.)
            self.assertEqual(receipt['expectedBinding'], fixture[1])
            for action, (_, raw, size) in zip(receipt['actions'], probe.sent):
                self.assertEqual(action['bufferHex'], raw.hex()); self.assertEqual(size, 40)
                self.assertEqual(action['requestedInputs'], action['insertedInputs'])
                self.assertEqual(action['inputCallAttempts'], 1)
            final, = Path(directory).glob('*-session-result.json')
            self.assertEqual(json.loads(final.read_bytes()), receipt)
    def test_partial_prefix_only_releases_its_own_held_scans(self):
        expected = {0: [], 1: [(0x1d, 10)], 2: [(0x47, 11), (0x1d, 10)], 3: [(0x1d, 10)]}
        for inserted, released in expected.items():
            with self.subTest(inserted=inserted), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe, record = fixture[-2:]; probe.counts = [inserted]
                with self.assertRaisesRegex(AssertionError, 'partial'):
                    with self.session(fixture) as session: session.navigate('^{HOME}')
                self.assertEqual(len(probe.sent), 1 + bool(released))
                if released:
                    _, raw, _ = probe.sent[1]
                    values = [struct.unpack('<I4xHHII4xQ8x', raw[i:i+40]) for i in range(0, len(raw), 40)]
                    self.assertEqual([(v[2], v[3]) for v in values], released)
                    self.assertTrue(all(v[1] == 0 and v[3] & 2 for v in values))
                self.assertIs(record['editorShortcutSessions'][0]['success'], False)
    def test_unavailable_or_invalid_return_never_guesses_an_inserted_prefix(self):
        for value in (OSError('native return unavailable'), None, True, -1, 5):
            with self.subTest(value=repr(value)), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe, record = fixture[-2:]; probe.counts = [value]
                with self.assertRaises(BaseException):
                    with self.session(fixture) as session: session.navigate('^{HOME}')
                self.assertEqual(len(probe.sent), 1)
                action = record['editorShortcutSessions'][0]['actions'][0]
                self.assertIsNone(action['insertedInputs'])
                self.assertNotIn('ownedKeyUp', action)
    def test_preexisting_modifier_or_navigation_key_prevents_every_input(self):
        for key in (0x11, 0xa2, 0x10, 0x12, 0x5b, 0x24, 0x23, 0x71):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe = fixture[-2]; probe.keys_down = [key]
                with self.assertRaisesRegex(AssertionError, 'neutral'):
                    with self.session(fixture) as session: self.full(session)
                self.assertEqual(probe.sent, [])
    def test_non_us_layout_or_lock_state_prevents_every_input(self):
        for attr, value in [('layout', 0x04120412), ('current_layout', 0x04120412), ('caps', True), ('scroll', True)]:
            with self.subTest(attr=attr), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe = fixture[-2]; setattr(probe, attr, value)
                with self.assertRaises(AssertionError):
                    with self.session(fixture) as session: self.full(session)
                self.assertEqual(probe.sent, [])
    def test_original_activation_and_reader_engine_generations_are_required(self):
        for field in ('activation', 'shellCreation', 'engineCreation', 'engineImage', 'enginePid', 'ancestry'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); p, _, _, _, probe, _ = fixture
                if field == 'activation': del p.opengeul_activation_binding
                if field == 'shellCreation': probe.shell['creationTime'] += 1
                if field == 'engineCreation': probe.engine['creationTime'] += 1
                if field == 'engineImage': probe.engine['image'] += '.foreign'
                if field == 'enginePid': probe.engine['pid'] += 1
                if field == 'ancestry': probe.ancestry = False
                with self.assertRaises((AssertionError, AttributeError)):
                    with self.session(fixture) as session: self.full(session)
                self.assertEqual(probe.sent, [])
    def test_prior_click_generation_is_joined_but_its_handle_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); p, b, _, _, probe, _ = fixture
            p.opengeul_editor_click_generations = {(12, 22, 88): (88, b['expectedImage'], b['officeCreationTime'])}
            with self.session(fixture) as session: self.full(session)
            self.assertEqual(probe.calls.count(('open', 88)), 1)
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); p, b, _, _, probe, _ = fixture
            p.opengeul_editor_click_generations = {(12, 22, 88): (88, b['expectedImage'], b['officeCreationTime'] + 1)}
            with self.assertRaisesRegex(AssertionError, 'click'):
                with self.session(fixture) as session: self.full(session)
            self.assertEqual(probe.sent, [])
    def test_foreign_foreground_capture_and_noneditor_focus_fail_closed(self):
        for attr, value in [('foreground', 99), ('capture', 99), ('focus', 0)]:
            with self.subTest(attr=attr), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe = fixture[-2]; setattr(probe, attr, value)
                with self.assertRaises(AssertionError):
                    with self.session(fixture) as session: self.full(session)
                self.assertEqual(probe.sent, [])
    def test_identity_layout_or_thread_change_after_first_event_never_retries(self):
        for mutate in (lambda p: p.engine.update(creationTime=p.engine['creationTime'] + 1),
                       lambda p: setattr(p, 'layout', 0x04120412),
                       lambda p: setattr(p, 'thread', 55)):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe = fixture[-2]; probe.after_send = lambda: mutate(probe)
                with self.assertRaises(AssertionError):
                    with self.session(fixture) as session: self.full(session)
                self.assertEqual(len(probe.sent), 1)
    def test_expired_budget_never_reopens_or_leaks_a_newly_admitted_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); fixture[3].now = 11.
            with self.assertRaisesRegex(AssertionError, 'deadline'):
                with self.session(fixture) as session: self.full(session)
            self.assertFalse(any(isinstance(c, tuple) and c[0] == 'open' for c in fixture[-2].calls))
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe = fixture[-2]; probe.open_after = lambda: setattr(fixture[3], 'now', 11.)
            with self.assertRaisesRegex(AssertionError, 'deadline'):
                with self.session(fixture) as session: self.full(session)
            self.assertEqual(probe.calls.count(('close', 2**41)), 1); self.assertEqual(probe.sent, [])
    def test_send_finishing_late_cannot_qualify_and_still_closes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe, record = fixture[-2:]
            probe.after_send = lambda: setattr(fixture[3], 'now', 11.)
            with self.assertRaisesRegex(AssertionError, 'deadline'):
                with self.session(fixture) as session: self.full(session)
            self.assertEqual(len(probe.sent), 1); self.assertEqual(probe.calls.count(('close', 2**41)), 1)
            self.assertEqual(record['editorShortcutSessions'][0]['actions'][0]['insertedInputs'], 4)
    def test_intent_collision_prevents_native_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe = fixture[-2]
            (Path(directory) / 'counted-case-editor-shortcuts-000-00-input-intent.json').write_text('original')
            with self.assertRaises(FileExistsError):
                with self.session(fixture) as session: session.navigate('^{HOME}')
            self.assertEqual(probe.sent, [])
    def test_generation_change_during_intent_retention_stops_before_input(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe = fixture[-2]; session = self.session(fixture)
            original = session._retain
            def retain(phase):
                original(phase)
                if phase == 'input-intent': probe.engine['creationTime'] += 1
            session._retain = retain
            with self.assertRaisesRegex(AssertionError, 'generation'):
                with session: session.navigate('^{HOME}')
            self.assertEqual(probe.sent, [])
    def test_close_failure_cannot_qualify_or_replace_an_existing_primary_error(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); fixture[-2].close_result = False
            with self.assertRaisesRegex(AssertionError, 'HANDLE'):
                with self.session(fixture) as session: self.full(session)
            self.assertFalse(fixture[-1]['editorShortcutSessions'][0]['engineHandleReleased'])
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe = fixture[-2]
            original = OSError('original insertion failure'); probe.counts = [original]; probe.close_result = OSError('secondary close failure')
            with self.assertRaises(OSError) as got:
                with self.session(fixture) as session: session.navigate('^{HOME}')
            self.assertIs(got.exception, original)
            self.assertIn('secondary', repr(fixture[-1]['editorShortcutSessions'][0]['cleanupErrors']))
    def test_repeated_or_unexpected_navigation_never_adds_input(self):
        for value in ('^s', '^{HOME}', '{F2}', '{ESC}'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory); probe = fixture[-2]
                with self.assertRaises(AssertionError):
                    with self.session(fixture) as session:
                        session.navigate('^{HOME}'); session.navigate(value)
                self.assertEqual(len(probe.sent), 1)
    def test_short_session_or_late_session_use_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); session = self.session(fixture)
            with self.assertRaises(AssertionError): session.navigate('^{HOME}')
            with self.assertRaisesRegex(AssertionError, 'complete'):
                with session: session.navigate('^{HOME}')
            with self.assertRaises(AssertionError): session.navigate('{F2}^{END}')
    def test_caught_failed_input_is_sticky_and_cannot_resume_or_qualify(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe, record = fixture[-2:]; probe.counts = [0]
            with self.assertRaises(AssertionError):
                with self.session(fixture) as session:
                    with self.assertRaises(AssertionError): session.navigate('^{HOME}')
                    with self.assertRaises(AssertionError): session.navigate('{F2}^{END}')
            self.assertEqual(len(probe.sent), 1)
            self.assertFalse(record['editorShortcutSessions'][0]['success'])
    def test_a_later_rejected_use_preserves_the_first_native_error_object(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory); probe = fixture[-2]
            original = OSError('first native error'); probe.counts = [original]
            with self.assertRaises(BaseException) as got:
                with self.session(fixture) as session:
                    with self.assertRaises(OSError): session.navigate('^{HOME}')
                    session.navigate('{F2}^{END}')
            self.assertIs(got.exception, original)
            self.assertEqual(len(probe.sent), 1)
    def test_native_adapter_uses_pointer_width_and_counted_input_prototypes(self):
        class Function:
            def __init__(self, result=1): self.result, self.calls = result, []
            def __call__(self, *args):
                self.calls.append(args)
                return self.result(*args) if callable(self.result) else self.result
        class Library:
            def __getattr__(self, name):
                value = Function(); setattr(self, name, value); return value
        user, kernel, dwm = Library(), Library(), Library()
        clock = Clock()
        probe = shortcuts.NativeShortcutProbe(10., clock, user=user, kernel=kernel, dwm=dwm)
        self.assertEqual(kernel.OpenProcess.argtypes, (ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32))
        self.assertIs(kernel.OpenProcess.restype, ctypes.c_void_p)
        self.assertEqual(kernel.CloseHandle.argtypes, (ctypes.c_void_p,))
        self.assertEqual(user.GetKeyboardLayout.argtypes, (ctypes.c_uint32,))
        self.assertIs(user.GetKeyboardLayout.restype, ctypes.c_void_p)
        self.assertEqual(user.SendInput.argtypes, (ctypes.c_uint32, ctypes.POINTER(shortcuts.Input), ctypes.c_int))
        kernel.OpenProcess.result = 2**41
        self.assertEqual(probe.open_engine(88), 2**41)
        self.assertEqual(kernel.OpenProcess.calls, [(0x00101000, False, 88)])
        payload = shortcuts.input_buffer(shortcuts.shortcut_events('CTRL_HOME'))
        user.SendInput.result = 4
        self.assertEqual(probe.send(payload), 4)
        self.assertEqual(user.SendInput.calls[0][0], 4)
        self.assertEqual(bytes(user.SendInput.calls[0][1]), bytes(payload))
        self.assertEqual(user.SendInput.calls[0][2], 40)
        clock.now = 11.
        with self.assertRaisesRegex(AssertionError, 'deadline'): probe.send(payload)
        self.assertTrue(probe.close_engine(2**41))
        self.assertEqual(kernel.CloseHandle.calls, [(2**41,)])


if __name__ == '__main__': unittest.main()
