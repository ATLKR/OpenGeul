"""Physical ASCII input: exact case, Win64 ABI, preconditions and fail-closed delivery."""
import copy
import ctypes
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from editor_program_boundary import editor_program_factory


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_editor_input.py'
if SOURCE.exists():
    SPEC = importlib.util.spec_from_file_location('suite_ascii_editor_input_tests', SOURCE)
    keyboard = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(keyboard)
else:
    keyboard = None


class FakeWindows:
    def __init__(self, counts=()):
        self.sent, self.counts, self.focus_checks = [], list(counts), []
        self.layout, self.current_layout, self.down, self.caps = 0x04090409, 0x04090409, set(), 0
        self.focus = 33
        self.user = SimpleNamespace(
            GetKeyboardLayout=lambda tid: self.layout if tid else self.current_layout,
            GetAsyncKeyState=lambda key: 0x8000 if key in self.down else 0,
            GetKeyState=lambda key: self.caps,
            GetWindowThreadProcessId=lambda hwnd, _: 44,
            GetForegroundWindow=lambda: 11,
            GetAncestor=lambda hwnd, kind: 11,
            SendInput=lambda count, payload, size: self.send(count, payload, size))

    def require_foreground(self, hwnd):
        if hwnd != 11: raise AssertionError('foreign foreground')

    def require_editor_focus(self, hwnd, child):
        self.focus_checks.append((hwnd, child))
        if not self.focus: raise AssertionError('foreign editor focus')
        return self.focus

    def pid(self, hwnd): return 77 if hwnd == 11 else 88

    def editor_focus_snapshot(self, hwnd, child, shell_pid, office_pid):
        def window(handle):
            return {'hwnd': handle, 'isWindow': True, 'pid': self.pid(handle),
                    'threadId': 44, 'rootHwnd': hwnd, 'className': 'Owned-test-window'}
        binding = {'suite': window(hwnd), 'editor': window(child),
                   'foreground': window(hwnd), 'editorWithinSuite': True}
        return {'before': binding, 'after': binding, 'querySucceeded': True,
                'queryAttempted': True, 'queriedThreadId': 44, 'cbSize': 72, 'lastError': 0,
                'focus': window(self.focus), 'focusWithinEditor': True,
                'capture': {'hwnd': 0, 'isWindow': False, 'pid': 0, 'threadId': 0, 'rootHwnd': 0, 'className': ''}}

    def send(self, count, payload, size):
        self.sent.append((count, bytes(payload), size))
        value = self.counts.pop(0) if self.counts else count
        if isinstance(value, Exception): raise value
        return value


class AsciiEditorInputTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(keyboard, 'Missing source-supported physical ASCII editor injector')

    def test_optional_absolute_deadline_blocks_expired_input_without_changing_default_receipts(self):
        for deadline in (1., True, float('nan'), float('inf')):
            api, record = FakeWindows(), {}
            with self.subTest(deadline=deadline), self.assertRaises(AssertionError):
                keyboard.type_ascii(api, 11, 22, 'a', record, pause=.04,
                    deadline=deadline, clock=lambda: 1.)
            self.assertEqual(api.sent, [])

    def test_optional_deadline_caps_existing_pause_and_stops_before_next_character(self):
        api, record, now = FakeWindows(), {}, [1.]
        def advance(seconds): now[0] += seconds
        with patch.object(keyboard.time, 'sleep', side_effect=advance) as sleep:
            with self.assertRaisesRegex(AssertionError, 'deadline'):
                keyboard.type_ascii(api, 11, 22, 'ab', record, pause=.04,
                    deadline=1.02, clock=lambda: now[0])
        self.assertEqual(len(api.sent), 1)
        self.assertAlmostEqual(sleep.call_args.args[0], .02)
        self.assertFalse(record['asciiEditorInputs'][0]['success'])

    def test_deadline_is_rechecked_after_snapshot_before_each_existing_sendinput(self):
        api, record, now = FakeWindows(), {}, [1.]
        original = api.require_editor_focus
        def delayed_focus(*args):
            result = original(*args); now[0] = 2.
            return result
        api.require_editor_focus = delayed_focus
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            keyboard.type_ascii(api, 11, 22, 'a', record, pause=.04,
                deadline=2., clock=lambda: now[0])
        self.assertEqual(api.sent, [])

    def inject(self, text='aA-09 ', api=None, **kw):
        api, record = api or FakeWindows(), {}
        kw.setdefault('pause', 0.025)
        with patch.object(keyboard.time, 'sleep') as sleep:
            keyboard.type_ascii(api, 11, 22, text, record, **kw)
        return api, record['asciiEditorInputs'][0], sleep

    def test_win64_input_abi_has_keyboard_offset_eight_and_size_forty(self):
        self.assertEqual(ctypes.sizeof(keyboard.Input), 40)
        self.assertEqual(keyboard.Input.payload.offset, 8)
        self.assertEqual(ctypes.sizeof(keyboard.KeyboardInput), 24)
        self.assertEqual(keyboard.KeyboardInput.dwExtraInfo.offset, 16)

    def test_uppercase_requires_explicit_shift_and_lowercase_does_not(self):
        lower, upper = keyboard.ascii_actions('aA')
        self.assertEqual(lower['events'], [{'vk': 0, 'scan': 0x1e, 'flags': 8}, {'vk': 0, 'scan': 0x1e, 'flags': 10}])
        self.assertEqual(upper['events'], [{'vk': 0, 'scan': 0x2a, 'flags': 8}, *lower['events'], {'vk': 0, 'scan': 0x2a, 'flags': 10}])

    def test_digits_hyphen_and_space_have_unshifted_us_scans(self):
        actions = keyboard.ascii_actions('1234567890- ')
        self.assertEqual([row['events'][0]['scan'] for row in actions], list(range(2, 12)) + [12, 57])
        self.assertTrue(all(len(row['events']) == 2 for row in actions))

    def test_colon_brackets_the_us_semicolon_scan_with_explicit_shift(self):
        try:
            actions = keyboard.ascii_actions(':')
        except ValueError as exc:
            self.fail('The literal IME scaffold colon needs a counted physical plan: ' + str(exc))
        self.assertEqual(actions, [{'index': 0, 'character': ':', 'events': [
            {'vk': 0, 'scan': 0x2a, 'flags': 8},
            {'vk': 0, 'scan': 0x27, 'flags': 8},
            {'vk': 0, 'scan': 0x27, 'flags': 10},
            {'vk': 0, 'scan': 0x2a, 'flags': 10}]}])
        api, receipt, sleep = self.inject(':', pause=0.04)
        self.assertEqual([sent[0] for sent in api.sent], [4])
        self.assertEqual(receipt['actions'][0]['bufferHex'], bytes(keyboard.input_buffer(actions[0]['events'])).hex())
        self.assertEqual(sleep.call_args_list, [((0.04,),)])
        keyboard.require_ascii_receipt(receipt, ':', 11, 22)

    def test_three_exact_ime_scaffolds_keep_spaces_colon_and_original_pacing(self):
        for module in ('writer', 'calc', 'impress'):
            prefix = ' ime-opengeul-' + module + ':'
            with self.subTest(module=module):
                try:
                    api, receipt, sleep = self.inject(prefix, pause=0.04)
                except ValueError as exc:
                    self.fail('The full literal IME scaffold must have counted physical input: ' + str(exc))
                self.assertEqual(''.join(action['character'] for action in receipt['actions']), prefix)
                self.assertEqual([sent[0] for sent in api.sent], [2] * (len(prefix) - 1) + [4])
                self.assertEqual(sleep.call_args_list, [((0.04,),)] * len(prefix))
                keyboard.require_ascii_receipt(receipt, prefix, 11, 22)

    def test_partial_colon_only_releases_inserted_shift_and_never_retypes(self):
        api, record = FakeWindows(counts=(1, 1)), {}
        try:
            with patch.object(keyboard.time, 'sleep'), self.assertRaisesRegex(AssertionError, 'inserted 1 of 4'):
                keyboard.type_ascii(api, 11, 22, ':', record, pause=0.04)
        except ValueError as exc:
            self.fail('Colon needs a physical plan before partial insertion can be bounded: ' + str(exc))
        self.assertEqual([sent[0] for sent in api.sent], [4, 1])
        self.assertEqual(record['asciiEditorInputs'][0]['success'], False)
        self.assertEqual(record['asciiEditorInputs'][0]['actions'][0]['cleanup']['events'],
                         [{'vk': 0, 'scan': 0x2a, 'flags': 10}])

    def test_rejects_unicode_key_syntax_newlines_empty_and_unbounded_input_before_any_event(self):
        for text in ('한글', 'x\n', '{F6}', '+', '', 'a' * 257):
            api = FakeWindows()
            with self.subTest(text=text[:20]), self.assertRaises((ValueError, AssertionError)):
                self.inject(text, api)
            self.assertEqual(api.sent, [])

    def test_exact_case_receipt_has_actual_buffers_counts_focus_and_original_pause(self):
        api, receipt, sleep = self.inject(pause=0.025)
        self.assertEqual(len(api.sent), 6)
        self.assertEqual([row[0] for row in api.sent], [2, 4, 2, 2, 2, 2])
        self.assertEqual(sleep.call_args_list, [((0.025,),)] * 6)
        self.assertEqual(len(api.focus_checks), 12)
        self.assertEqual(receipt['text'], 'aA-09 ')
        self.assertEqual(receipt['inputMethod'], 'SendInput-scancode')
        self.assertIs(receipt['unicodeInputUsed'], False)
        for sent, action in zip(api.sent, receipt['actions']):
            self.assertEqual(sent[1].hex(), action['bufferHex'])
            self.assertEqual(sent[2], 40)
            self.assertEqual(action['inserted'], action['requested'])
            self.assertEqual(action['before']['focusHwnd'], 33)
            self.assertIs(action['before']['editorFocusVerified'], True)
        keyboard.require_ascii_receipt(receipt, 'aA-09 ', 11, 22)

    def test_rejects_target_or_current_thread_layout_change_without_mutating_it(self):
        for attribute in ('layout', 'current_layout'):
            api = FakeWindows()
            setattr(api, attribute, 0x04120412)
            with self.subTest(attribute=attribute), self.assertRaisesRegex(AssertionError, 'English'):
                self.inject(api=api)
            self.assertEqual(api.sent, [])
            self.assertEqual(getattr(api, attribute), 0x04120412)

    def test_rejects_physical_modifiers_and_capslock_without_releasing_them(self):
        for key in (0x10, 0x11, 0x12, 0xa0, 0xa1, 0xa2, 0xa3, 0xa4, 0xa5, 0x14):
            api = FakeWindows()
            api.down.add(key)
            with self.subTest(key=key), self.assertRaisesRegex(AssertionError, 'neutral'):
                self.inject(api=api)
            self.assertEqual(api.sent, [])
            self.assertEqual(api.down, {key})
        api = FakeWindows()
        api.caps = 1
        with self.assertRaisesRegex(AssertionError, 'Caps Lock'): self.inject(api=api)
        self.assertEqual(api.sent, [])
        self.assertEqual(api.caps, 1)

    def test_rejects_foreign_focus_without_any_typing(self):
        api = FakeWindows()
        api.focus = 0
        with self.assertRaisesRegex(AssertionError, 'foreign editor focus'): self.inject(api=api)
        self.assertEqual(api.sent, [])

    def test_partial_character_fails_and_releases_only_inserted_own_downs(self):
        # Prefix [Shift down, A down] needs A up then Shift up. No text retry.
        api, record = FakeWindows([2]), {}
        with self.assertRaisesRegex(AssertionError, 'inserted 2 of 4'):
            keyboard.type_ascii(api, 11, 22, 'Ab', record, pause=0.025)
        receipt = record['asciiEditorInputs'][0]
        self.assertIs(receipt['success'], False)
        self.assertEqual(len(receipt['actions']), 1)
        self.assertEqual(len(api.sent), 2)
        self.assertEqual(receipt['actions'][0]['cleanup']['events'], [
            {'vk': 0, 'scan': 0x1e, 'flags': 10}, {'vk': 0, 'scan': 0x2a, 'flags': 10}])
        self.assertEqual(receipt['actions'][0]['cleanup']['inserted'], 2)
        self.assertIn('inserted 2 of 4', receipt['error'])

    def test_partial_zero_or_completed_keyup_never_releases_foreign_keys(self):
        for inserted, expected in ((0, []), (1, [0x2a]), (3, [0x2a])):
            api, record = FakeWindows([inserted]), {}
            with self.subTest(inserted=inserted), self.assertRaises(AssertionError):
                keyboard.type_ascii(api, 11, 22, 'A', record, pause=0.025)
            cleanup = record['asciiEditorInputs'][0]['actions'][0].get('cleanup', {})
            self.assertEqual([row['scan'] for row in cleanup.get('events', [])], expected)
            self.assertEqual(len(api.sent), 2 if expected else 1)

    def test_cleanup_failure_retains_original_partial_input_failure(self):
        api, record = FakeWindows([2, RuntimeError('cleanup failed')]), {}
        with self.assertRaisesRegex(AssertionError, 'inserted 2 of 4'):
            keyboard.type_ascii(api, 11, 22, 'A', record, pause=0.025)
        receipt = record['asciiEditorInputs'][0]
        self.assertIn('inserted 2 of 4', receipt['error'])
        self.assertIn('cleanup failed', receipt['actions'][0]['cleanup']['error'])
        self.assertIs(receipt['success'], False)

    def test_lost_focus_after_input_fails_original_action_without_retry(self):
        api, record = FakeWindows(), {}
        def send(count, payload, size):
            api.sent.append((count, bytes(payload), size))
            api.focus = 0
            return count
        api.user.SendInput = send
        with self.assertRaisesRegex(AssertionError, 'foreign editor focus'):
            keyboard.type_ascii(api, 11, 22, 'ab', record, pause=0.025)
        self.assertEqual(len(api.sent), 1)
        self.assertIs(record['asciiEditorInputs'][0]['success'], False)

    def test_owned_editor_thread_change_stops_before_typing_another_character(self):
        api, record = FakeWindows(), {}
        api.user.GetWindowThreadProcessId = lambda hwnd, _: 99 if api.sent else 44
        with self.assertRaisesRegex(AssertionError, 'thread changed'):
            keyboard.type_ascii(api, 11, 22, 'ab', record, pause=0.025)
        self.assertEqual(len(api.sent), 1)
        self.assertIs(record['asciiEditorInputs'][0]['success'], False)

    def test_independent_replay_rejects_case_buffers_unicode_counts_layout_and_foreign_identity(self):
        _, receipt, _ = self.inject('Aa-0', pause=0.04)
        changes = [lambda x: x.update(text='aa-0'), lambda x: x.update(unicodeInputUsed=True),
                   lambda x: x.update(documentHwnd=999), lambda x: x.update(childHwnd=999),
                   lambda x: x.update(inputSize=32), lambda x: x.update(success=False),
                   lambda x: x['actions'][0].update(inserted=3),
                   lambda x: x['actions'][0].update(bufferHex='00'),
                   lambda x: x['actions'][0]['events'][0].update(flags=4),
                   lambda x: x['actions'][0]['before'].update(targetLayout=0x04120412),
                   lambda x: x['actions'][0]['after'].update(editorFocusVerified=False),
                   lambda x: x['actions'][0]['after'].update(editorThreadId=99),
                   lambda x: x['actions'][1]['before'].update(editorThreadId=99),
                   lambda x: x['actions'].pop()]
        for change in changes:
            altered = copy.deepcopy(receipt)
            change(altered)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                keyboard.require_ascii_receipt(altered, 'Aa-0', 11, 22)


def load_sibling(name):
    spec = importlib.util.spec_from_file_location('ascii_test_' + name, SOURCE.with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AsciiEditorIntegrationTests(unittest.TestCase):
    def test_all_thirteen_existing_marker_input_buffers_match_frozen_bb926_bytes(self):
        # Native Win64 INPUT bytes captured from the parent bb926 source before
        # adding colon. These hashes include every original character buffer.
        expected = {
            'UI-OpenGeul-writer': '3111fad0223e4161e27c60b1329a732a21b44cda3e512fd6cdb443f898923713',
            'UI-OpenGeul-calc': '75fc5e031c5c94c7668af31f450aacab40420dc6f570a44fcc21bd1daffba8e9',
            'UI-OpenGeul-impress': 'd7a1657742d4ea0258026e96522220cb9ca08c30b44f09dcfeeacc24eba59e55',
            '-LIFECYCLE-CANCEL-SAVE-': '9f83db4733f7564a0dc640fb72e0626cf228fc494b760a598b51e51cd520f252',
            '-AFTER-CANCEL-': '1c544a62877ccea93d35758f687a9772932d76b94b33b071a6d594115eb419eb',
            '-LIFECYCLE-DISCARD-': 'fc45bcef836b7a230fa2b6d9b4b12bf1da0910ef2608c497e0150c19f5b0f02d',
            '-LIFECYCLE-NEW-': '6c0f89c2df497f58e3d561d1c00fe97f76063856455a957f215a386e33be3cb6',
            '-AFTER-PICKER-CANCEL-': '784893741d052cfad898d9479e6456cf127687908d1e64bd2cd6f462c82827e9',
            '-FAILED-SAVEAS-DIRTY-': '0edf0cef14f1c209405262e07a6dcc0fd7d4de357dc5359bf6d84bee74d0322f',
            '-AFTER-SAVEAS-ERROR-': 'dab73e281689f486bda6013b1036d8fb4df0093f108f6f07b94d1f7bbcd8b86d',
            '-HOME-CANCEL-DIRTY-': '31cb8f3878be617e2a4818621f35789c8218c853d7b8b7ab115c0686aaaee982',
            '-REMAINDER-EDIT-': '91c4a03d1871d4fd391837d102b8c890ef0ef5c05faefc0a44d418fe03a51185',
            '-AFTER-RESIZE-MINIMIZE-RESTORE-': '8c087d270c4efb7cf07a47e314946e4bdd5ff1726fa91edba0bb47ef1db6e04a'}
        lifecycle, native = load_sibling('lifecycle_smoke'), load_sibling('windows_smoke')
        markers = list(native.EDITOR_MARKERS.values()) + [
            marker for group in lifecycle.ASCII_EDITOR_MARKERS.values() for marker in group]
        self.assertEqual(set(markers), set(expected))
        for marker in markers:
            with self.subTest(marker=marker):
                raw = b''.join(bytes(keyboard.input_buffer(row['events'])) for row in keyboard.ascii_actions(marker))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected[marker])

    def test_lifecycle_keeps_navigation_and_dirty_check_but_routes_only_marker_to_physical_ascii(self):
        lifecycle = load_sibling('lifecycle_smoke')
        self.assertTrue(hasattr(lifecycle.native, 'ascii_input'), 'Lifecycle lacks physical ASCII sibling helper')
        case = object.__new__(lifecycle.Case)
        case.record = {'attachments': [{'hwnd': 11, 'parent': 12, 'child': 22, 'officePid': 88}]}
        case.process, case.api = SimpleNamespace(pid=77), FakeWindows()
        # Isolate this existing navigation/input contract. Completion itself is
        # covered by the real-policy regressions in test_writer_model_barrier.
        completion = SimpleNamespace(begin=Mock(return_value=object()), complete=Mock(), abort=Mock())
        case._writer_model_context = lambda hwnd, child: completion
        case.api.title = lambda hwnd: '* OpenGeul Writer'
        window = SimpleNamespace(set_focus=Mock(), click_input=Mock())
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: window))
        send_keys, type_ascii = Mock(), Mock()
        with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop),
                                       'pywinauto.keyboard': SimpleNamespace(send_keys=send_keys)}), \
                patch.object(lifecycle.native, 'activate_owned_suite',
                    side_effect=lambda api, process, hwnd, record: api.require_foreground(hwnd)) as activated, \
                patch.object(lifecycle.native, 'click_owned_editor',
                    side_effect=lambda *args: window.click_input()) as clicked, \
                patch.object(lifecycle.native, 'FirstAdmissionEditorSession', editor_program_factory(send_keys)), \
                patch.object(lifecycle.native.ascii_input, 'type_ascii', type_ascii):
            case.edit(11, 22, '-LIFECYCLE-NEW-')
        activated.assert_called_once_with(case.api, case.process, 11, case.record)
        clicked.assert_called_once_with(case.api,case.process,11,12,22,88,case.record)
        type_ascii.assert_called_once_with(case.api, 11, 22, '-LIFECYCLE-NEW-', case.record, pause=0.025,deadline=completion.deadline)
        self.assertEqual([call.args[0] for call in send_keys.call_args_list], ['^{F6}', '^{END}'])
        self.assertEqual(case.record['stage'], 'physical-editor-input')
        self.assertGreaterEqual(len(case.api.focus_checks), 3)

    def test_general_gui_routes_three_exact_markers_with_original_pacing_and_keeps_save_checks(self):
        native = load_sibling('windows_smoke')
        self.assertTrue(hasattr(native, 'ascii_input'), 'GUI lacks physical ASCII sibling helper')
        for module, extension in native.INPUT_CASES:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / ('OpenGeul-' + module + '.' + extension)
                source.write_text('Engine-OpenGeul-' + module)
                original_bytes = source.read_bytes()
                marker = 'UI-OpenGeul-' + module
                api = FakeWindows()
                api.title, api.windows = lambda hwnd: 'OpenGeul ' + module, lambda pid: []
                api.external_window_message = lambda *args: 'unexpected external window'
                process = SimpleNamespace(pid=77)
                window = SimpleNamespace(maximize=Mock(), set_focus=Mock(), click_input=Mock(),
                                         capture_as_image=lambda: SimpleNamespace(save=lambda _: None))
                desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: window))
                events = []
                def send(keys, **kw):
                    events.append(('keys', keys))
                    if keys == '^s': source.write_text('Engine-OpenGeul-' + module + marker)
                send_keys = Mock(side_effect=send)
                type_ascii = Mock(side_effect=lambda *args, **kw: events.append(('type', args[3])))
                # This existing test isolates navigation/input/save routing with
                # synthetic files. Real Calc XML and completion policy are covered
                # by test_calc_model_barrier and test_native_smoke.
                baseline, plan = {'fixture': 'isolated Calc baseline'}, object()
                def begin(actual_marker):
                    events.append(('begin', actual_marker))
                    return plan
                completion = SimpleNamespace(begin=Mock(side_effect=begin),
                    complete=Mock(side_effect=lambda actual_plan: events.append(('complete', actual_plan))), abort=Mock())
                with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop),
                                               'pywinauto.keyboard': SimpleNamespace(send_keys=send_keys)}), \
                        patch.object(native.calc_model_barrier, 'baseline_from_ooxml', return_value=baseline) as parse_baseline, \
                        patch.object(native, 'CalcModelContext', return_value=completion) as model_context, \
                        patch.object(native, 'FirstAdmissionEditorSession', editor_program_factory(send_keys)), \
                        patch.object(native, 'require_engine_fixture', return_value=source), \
                        patch.object(native, 'package_text', side_effect=lambda path: path.read_text()), \
                        patch.object(native, 'launch_suite', return_value=process), \
                        patch.object(native, 'Windows', return_value=api), \
                        patch.object(native, 'verified_attachment', return_value=(11, 12, 22, 88)), \
                        patch.object(native, 'activate_owned_suite',
                            side_effect=lambda api, process, hwnd, record: api.require_foreground(hwnd)) as activated, \
                        patch.object(native, 'click_owned_editor',
                            side_effect=lambda *args: window.click_input()) as clicked, \
                        patch.object(native.ascii_input, 'type_ascii', type_ascii), \
                        patch.object(native, '_verified_saved_calc_close_proof', return_value=object()), \
                        patch.object(native, 'close_document'), patch.object(native, 'close_home'), \
                        patch.object(native, 'stop_owned_test_process'):
                    result = native.document_case(root, root, root, module, extension, True)
                activated.assert_called_once_with(api, process, 11, result)
                clicked.assert_called_once_with(api,process,11,12,22,88,result)
                self.assertEqual(type_ascii.call_count,1)
                self.assertEqual(type_ascii.call_args.args,(api,11,22,marker,result))
                self.assertEqual(type_ascii.call_args.kwargs['pause'],.04)
                self.assertIsInstance(type_ascii.call_args.kwargs['deadline'],float)
                sent = [call.args[0] for call in send_keys.call_args_list]
                self.assertNotIn(marker, sent)
                self.assertEqual(sent.count('^{F6}'), 1)
                window.click_input.assert_called_once_with()
                self.assertTrue(result['editorFocusReadiness']['ready'])
                self.assertIn('^s', sent)
                if module == 'calc':
                    parse_baseline.assert_called_once_with(original_bytes)
                    self.assertEqual((root / 'calc-model-baseline.xlsx').read_bytes(), original_bytes)
                    model_context.assert_called_once_with(root, source, root, process,
                        {'hwnd': 11, 'parent': 12, 'child': 22, 'officePid': 88}, result, baseline)
                    completion.begin.assert_called_once_with(marker)
                    completion.complete.assert_called_once_with(plan)
                    completion.abort.assert_not_called()
                    self.assertEqual(events, [('keys', '^{F6}'), ('begin', marker),
                        ('keys', '^{HOME}'), ('keys', '{F2}'), ('keys', '^{END}'), ('type', marker), ('keys', '{ENTER}'),
                        ('complete', plan), ('keys', '^s')])
                else:
                    parse_baseline.assert_not_called()
                    model_context.assert_not_called()
                self.assertIs(result['keyboardInputVerified'], True)
                self.assertIs(result['contentMutationVerified'], True)
                self.assertNotEqual(result['beforeSha256'], result['afterSha256'])

    def test_exact_source_marker_maps_cover_only_existing_ascii_editor_cases(self):
        lifecycle, native = load_sibling('lifecycle_smoke'), load_sibling('windows_smoke')
        self.assertTrue(hasattr(lifecycle, 'ASCII_EDITOR_MARKERS'), 'Lifecycle markers cannot be independently derived')
        self.assertEqual(lifecycle.ASCII_EDITOR_MARKERS, {
            'dirty-writer-cancel-save': ('-LIFECYCLE-CANCEL-SAVE-', '-AFTER-CANCEL-'),
            'dirty-writer-discard': ('-LIFECYCLE-DISCARD-',),
            'new-writer-saveas-cancel': ('-LIFECYCLE-NEW-', '-AFTER-PICKER-CANCEL-'),
            'failed-saveas-retains-editor': ('-FAILED-SAVEAS-DIRTY-', '-AFTER-SAVEAS-ERROR-'),
            'home-two-documents-cancel': ('-HOME-CANCEL-DIRTY-', '-REMAINDER-EDIT-'),
            'resize-minimize-restore': ('-AFTER-RESIZE-MINIMIZE-RESTORE-',)})
        self.assertEqual(native.EDITOR_MARKERS, {name: 'UI-OpenGeul-' + name for name in ('writer', 'calc', 'impress')})


if __name__ == '__main__': unittest.main()
