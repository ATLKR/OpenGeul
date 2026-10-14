"""Small Win32 observation boundary and independent ZIP/XML oracle tests."""
import copy
import io
import sys
from pathlib import Path
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
from native_document_policy import (choose_editor_hwnd, require_editor, require_hit,
    require_focus_map, require_owned_dialog, double_checked_action, assert_body_markers,
    require_dialog_action)

def editor(hwnd=10):
    return dict(hwnd=hwnd, root=hwnd, pid=202, tid=91, cls='Tauri Window',
                visible=True, enabled=True, owners=[])

def package(body='DOC-A &amp; Ω', extra='', *, section_namespace='http://www.hancom.co.kr/hwpml/2011/section'):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('mimetype', b'application/hwp+zip')
        archive.writestr('Contents/header.xml', b'<head/>')
        archive.writestr('Contents/content.hpf', b'<package/>')
        archive.writestr('Contents/section0.xml', (
            f'<hs:sec xmlns:hs="{section_namespace}" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            f'<hp:p><hp:run><hp:t>{body}</hp:t>{extra}</hp:run></hp:p></hs:sec>').encode())
    return data.getvalue()

class EditorOwnershipTests(unittest.TestCase):
    def test_new_window_is_exactly_one_new_owned_root(self):
        self.assertEqual(choose_editor_hwnd([editor(10)], [editor(10), editor(20)], 202), 20)

    def test_first_window_is_the_sole_owned_root(self):
        self.assertEqual(choose_editor_hwnd([], [editor(10)], 202), 10)

    def test_no_new_window_or_two_new_windows_are_not_selectable(self):
        for after in ([editor(10)], [editor(10), editor(20), editor(30)]):
            with self.subTest(after=after), self.assertRaises(AssertionError):
                choose_editor_hwnd([editor(10)], after, 202)

    def test_foreign_pid_never_becomes_the_new_editor(self):
        with self.assertRaises(AssertionError):
            choose_editor_hwnd([editor(10)], [editor(10), {**editor(20), 'pid': 999}], 202)

    def test_duplicate_hwnd_and_boolean_hwnd_are_rejected(self):
        for after in ([editor(10), editor(10)], [{**editor(10), 'hwnd': True}]):
            with self.subTest(after=after), self.assertRaises(AssertionError):
                choose_editor_hwnd([], after, 202)

    def test_same_editor_identity_is_ready(self):
        self.assertEqual(require_editor(editor(), editor()), editor())

    def test_changed_editor_identity_is_rejected(self):
        for key, value in [('hwnd', 11), ('root', 11), ('pid', 999), ('tid', 92),
                           ('cls', 'CabinetWClass'), ('owners', [99]),
                           ('visible', False), ('enabled', False)]:
            with self.subTest(key=key), self.assertRaises(AssertionError):
                require_editor({**editor(), key: value}, editor())

    def test_same_pid_other_editor_is_not_an_owned_hit(self):
        with self.assertRaises(AssertionError):
            require_hit({**editor(20), 'hwnd': 21}, editor(10), {202})

    def test_held_webview_child_of_exact_editor_is_an_owned_hit(self):
        child = {**editor(), 'hwnd': 11, 'pid': 303, 'cls': 'Chrome_RenderWidgetHostHWND'}
        self.assertEqual(require_hit(child, editor(), {202, 303}), child)

    def test_unheld_pid_hidden_or_disabled_hit_is_rejected(self):
        child = {**editor(), 'hwnd': 11, 'pid': 303}
        for changed, allowed in [(child, {202}), ({**child, 'visible': False}, {202, 303}),
                                 ({**child, 'enabled': False}, {202, 303})]:
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                require_hit(changed, editor(), allowed)

    def test_read_only_focus_binds_target_page_to_native_foreground(self):
        rows = [{'pageKey': 'A', 'focused': False}, {'pageKey': 'B', 'focused': True}]
        self.assertEqual(require_focus_map('B', rows), rows)

    def test_false_ambiguous_or_missing_page_focus_is_rejected(self):
        for rows in ([{'pageKey': 'A', 'focused': True}],
                     [{'pageKey': 'A', 'focused': False}, {'pageKey': 'B', 'focused': False}],
                     [{'pageKey': 'A', 'focused': True}, {'pageKey': 'B', 'focused': True}],
                     [{'pageKey': 'B', 'focused': True}, {'pageKey': 'B', 'focused': False}],
                     [{'pageKey': 'B', 'focused': 1}]):
            with self.subTest(rows=rows), self.assertRaises(AssertionError):
                require_focus_map('B', rows)

    def test_dialog_is_owned_by_the_exact_editor_not_merely_app_pid(self):
        dialog = {**editor(40), 'cls': '#32770', 'owners': [20]}
        with self.assertRaises(AssertionError):
            require_owned_dialog(dialog, editor(10), {10, 20})

    def test_exact_editor_dialog_chain_is_accepted(self):
        dialog = {**editor(40), 'cls': '#32770', 'owners': [10]}
        self.assertEqual(require_owned_dialog(dialog, editor(10), {10, 20}), dialog)

    def test_dialog_cycle_foreign_pid_and_foreign_root_are_rejected(self):
        dialog = {**editor(40), 'cls': '#32770', 'owners': [10]}
        for change in ({'owners': []}, {'owners': [20, 10]}, {'owners': [10, 10]},
                       {'pid': 999}, {'root': 10}, {'enabled': False}, {'cls': 'Tauri Window'}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                require_owned_dialog({**dialog, **change}, editor(10), {10, 20})

    def test_action_is_sent_once_after_two_identical_observations(self):
        events = []
        def read(): events.append('read'); return {'hwnd': 10, 'tid': 91}
        result = double_checked_action(read, lambda state: events.append(('input', state)))
        self.assertEqual(events, ['read', 'read', ('input', {'hwnd': 10, 'tid': 91})])
        self.assertEqual(result, {'hwnd': 10, 'tid': 91})

    def test_changed_second_observation_sends_no_input(self):
        reads = iter([{'hwnd': 10, 'tid': 91}, {'hwnd': 10, 'tid': 92}]); events = []
        with self.assertRaises(AssertionError):
            double_checked_action(lambda: next(reads), events.append)
        self.assertEqual(events, [])

class BodyOracleTests(unittest.TestCase):
    def test_real_zip_xml_unicode_and_body_markers_are_checked(self):
        result = assert_body_markers(package(), ['DOC-A & Ω'], ['DOC-B'], exact_text='DOC-A & Ω')
        self.assertIsInstance(result, dict)
        self.assertEqual(result['bodyText'], 'DOC-A & Ω')

    def test_required_marker_moved_into_header_fails(self):
        extra = '<hp:ctrl><hp:header><hp:subList><hp:p><hp:run><hp:t>DOC-A</hp:t></hp:run></hp:p></hp:subList></hp:header></hp:ctrl>'
        with self.assertRaises(AssertionError):
            assert_body_markers(package('', extra), ['DOC-A'])

    def test_duplicate_missing_cross_document_or_changed_exact_text_fails(self):
        for value in ('DOC-A DOC-A', 'OTHER', 'DOC-A DOC-B', 'OLD DOC-A'):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                assert_body_markers(package(value), ['DOC-A'], ['DOC-B'], exact_text='DOC-A')

    def test_same_marker_hidden_in_a_control_is_not_accepted_twice(self):
        extra = '<hp:ctrl><hp:footNote><hp:subList><hp:p><hp:run><hp:t>DOC-A</hp:t></hp:run></hp:p></hp:subList></hp:footNote></hp:ctrl>'
        with self.assertRaises(AssertionError):
            assert_body_markers(package('DOC-A', extra), ['DOC-A'])

    def test_split_text_runs_form_one_body_marker(self):
        result = assert_body_markers(package('DOC</hp:t><hp:t>-A'), ['DOC-A'])
        self.assertIsInstance(result, dict)
        self.assertEqual(result['bodyText'], 'DOC-A')

    def test_invalid_zip_is_rejected_by_original_container_oracle(self):
        with self.assertRaises(ValueError): assert_body_markers(b'PK\x03\x04bad', ['DOC-A'])

    def test_paragraph_namespace_cannot_impersonate_section_root(self):
        with self.assertRaises(AssertionError):
            assert_body_markers(package('DOC-A', section_namespace='http://www.hancom.co.kr/hwpml/2011/paragraph'), ['DOC-A'])

class DialogSemanticsTests(unittest.TestCase):
    def expected(self):
        return {'controlId': 1000, 'label': '저장', 'title': '저장 확인',
                'promptText': '창 B 문서.hwpx의 변경 내용을 저장할까요?'}

    def test_expected_control_label_prompt_and_title_are_kept(self):
        self.assertEqual(require_dialog_action(self.expected(), self.expected()), self.expected())

    def test_same_handle_changed_meaning_before_first_read_sends_no_input(self):
        for key, value in [('controlId', 1001), ('label', '저장 안 함'), ('title', '다른 대화상자'),
                           ('promptText', '창 A 문서.hwpx의 변경 내용을 저장할까요?')]:
            events = []
            with self.subTest(key=key), self.assertRaises(AssertionError):
                double_checked_action(lambda: require_dialog_action({**self.expected(), key: value}, self.expected()),
                                      events.append)
            self.assertEqual(events, [])

    def test_same_handle_changed_meaning_before_second_read_sends_no_input(self):
        events = []
        reads = iter([self.expected(), {**self.expected(), 'label': '저장 안 함'}])
        with self.assertRaises(AssertionError):
            double_checked_action(lambda: require_dialog_action(next(reads), self.expected()), events.append)
        self.assertEqual(events, [])

    def test_picker_expected_action_id_is_independent_of_current_button(self):
        expected = {'controlId': 1, 'label': 'Save', 'title': 'Save As', 'promptText': None}
        with self.assertRaises(AssertionError):
            require_dialog_action({**expected, 'controlId': 2}, expected)

class UnexpectedWebDialogTests(unittest.TestCase):
    def owner(self):
        from native_document_windows import OwnedDocumentWindows
        owner = OwnedDocumentWindows.__new__(OwnedDocumentWindows)
        owner.session = SimpleNamespace(dialogs=[], proc=SimpleNamespace(pid=202))
        owner.probe = SimpleNamespace(verify_process=lambda *args: None)
        owner.processes = {202: {}}
        owner.fatal_error = None
        return owner

    def test_readiness_poll_cannot_swallow_an_unexpected_confirmation(self):
        from driver import until
        owner = self.owner(); events = []; calls = []
        dialog = SimpleNamespace(type='confirm', message='unexpected owned synthetic confirmation',
                                 dismiss=lambda: events.append('dismiss'))
        def observed():
            calls.append('read')
            if len(calls) == 1: owner._unexpected_web_dialog('A')(dialog)
            events.append('later-document-input')
            return True
        with self.assertRaises(RuntimeError):
            until(observed, timeout=.1, pump=lambda seconds: None)
        self.assertEqual(calls, ['read'])
        self.assertEqual(events, ['dismiss'])

    def test_unexpected_dialog_latches_failure_before_all_later_inputs(self):
        owner = self.owner()
        dialog = SimpleNamespace(type='alert', message='unexpected', dismiss=lambda: None)
        try: owner._unexpected_web_dialog('A')(dialog)
        except Exception: pass
        with self.assertRaises(RuntimeError): owner._app()

class FilenameInputBoundaryTests(unittest.TestCase):
    def picker(self, *, second_child=None, second_bounds=None, second_hit=None, second_foreground=None):
        """Exercise Session's real scoped filename dispatch with read-only Win32 fakes."""
        import driver
        from native_document_windows import BoundDocumentWindow
        events = []; state = {'visible': True, 'typed': None, 'reads': 0, 'hit_read': False}
        parent = {**editor(20), 'pid': 321, 'enabled': False}
        dialog_row = {**editor(66), 'pid': 321, 'tid': 99, 'cls': '#32770', 'owners': [20]}
        child = {**dialog_row, 'hwnd': 67, 'root': 66, 'cls': 'Edit'}
        combo = {**child, 'hwnd': 68, 'cls': 'ComboBox'}
        def observe(hwnd):
            if hwnd == 20: return copy.deepcopy(parent)
            if hwnd == 66: return copy.deepcopy(dialog_row)
            if hwnd == 68: return copy.deepcopy(combo)
            if hwnd == 67:
                if state['hit_read']:
                    state['hit_read'] = False; events.append('hit-read')
                else:
                    state['reads'] += 1; events.append('child-read')
                return {**child, **(second_child or {})} if state['reads'] >= 2 else copy.deepcopy(child)
            raise AssertionError('Unexpected fake HWND')
        def rectangle():
            values = second_bounds if state['reads'] >= 2 and second_bounds is not None else [10, 10, 110, 30]
            return SimpleNamespace(**dict(zip(('left', 'top', 'right', 'bottom'), values)))
        filename = SimpleNamespace(handle=67, class_name=lambda: 'Edit', process_id=lambda: 321,
            parent=lambda: SimpleNamespace(handle=68, class_name=lambda: 'ComboBox', process_id=lambda: 321),
            is_visible=lambda: True, is_enabled=lambda: True, rectangle=rectangle,
            set_edit_text=lambda text: (events.append(('filename', text)), state.update(typed=text)),
            window_text=lambda: state['typed'])
        button = SimpleNamespace(control_id=lambda: 1, is_visible=lambda: True, is_enabled=lambda: True)
        dialog = SimpleNamespace(handle=66, process_id=lambda: 321, class_name=lambda: '#32770',
            window_text=lambda: 'Save As',
            descendants=lambda **kw: [button] if kw.get('class_name') == 'Button' else [filename],
            client_rect=lambda: SimpleNamespace(left=0, top=0, right=300, bottom=200),
            client_to_screen=lambda point: point)
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wait=lambda *args, **kw: None,
            wrapper_object=lambda: dialog))
        def hit(point):
            state['hit_read'] = True
            return second_hit if state['reads'] >= 2 and second_hit is not None else 67
        probe = SimpleNamespace(window=observe, hit=hit,
            foreground=lambda: second_foreground if state['reads'] >= 2 and second_foreground is not None else 66,
            parent=lambda hwnd: {67: 68, 68: 66}.get(hwnd, 0),
            user=SimpleNamespace(IsWindow=lambda hwnd: True, IsWindowVisible=lambda hwnd: state['visible']))
        owner = SimpleNamespace(probe=probe, windows={20: None}, dialogs={}, _app=lambda: None,
                                _record=lambda *args: None)
        bound = BoundDocumentWindow(owner, 'A', None, parent)
        bound.picker_purpose = 'save'
        bound.click_dialog_button = lambda *args, **kw: state.update(visible=False)
        def thread_process(hwnd, pointer): pointer._obj.value = 321; return 99
        def class_name(hwnd, buffer, length): buffer.value = '#32770'; return len(buffer.value)
        user = SimpleNamespace(GetWindowThreadProcessId=thread_process, GetClassNameW=class_name,
            IsWindow=lambda hwnd: True, IsWindowVisible=lambda hwnd: state['visible'], IsWindowEnabled=lambda hwnd: True)
        modules = {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop),
            'pywinauto.controls': SimpleNamespace(), 'pywinauto.controls.hwndwrapper': SimpleNamespace(
                InvalidWindowHandle=type('InvalidWindowHandle', (Exception,), {}))}
        session = driver.Session.__new__(driver.Session); session.proc = SimpleNamespace(pid=321)
        with patch.dict(sys.modules, modules), patch.object(driver.ctypes, 'windll', SimpleNamespace(user32=user), create=True):
            try: session.native_dialog(ROOT/'owned-target.hwpx', owner_scope=bound)
            except AssertionError as error:
                error.input_events = [event for event in events if isinstance(event, tuple) and event[0] == 'filename']
                raise
        return events

    def test_filename_write_follows_two_matching_control_observations_once(self):
        events = self.picker()
        self.assertEqual(events, ['child-read', 'hit-read', 'child-read', 'hit-read',
                                 ('filename', str(ROOT/'owned-target.hwpx'))])

    def test_second_filename_child_identity_change_sends_no_input(self):
        for key, value in [('hwnd', 69), ('root', 20), ('pid', 999), ('tid', 100),
                           ('cls', 'OtherEdit'), ('owners', [21]), ('visible', False), ('enabled', False)]:
            with self.subTest(key=key):
                with self.assertRaises(AssertionError) as caught: self.picker(second_child={key: value})
                self.assertEqual(caught.exception.input_events, [])

    def test_second_filename_screen_bounds_hit_or_foreground_change_sends_no_input(self):
        for change in ({'second_bounds': [11, 10, 111, 30]}, {'second_hit': 20}, {'second_foreground': 20}):
            with self.subTest(change=change):
                with self.assertRaises(AssertionError) as caught: self.picker(**change)
                self.assertEqual(caught.exception.input_events, [])

class UnsavedChoiceBoundaryTests(unittest.TestCase):
    def choose(self, *, choice='저장', control_id=1004, prompt='창 B 문서.hwpx의 변경 내용을 저장할까요?', title='저장 확인'):
        from native_document_windows import BoundDocumentWindow
        events = []; state = {'visible': True}
        button = SimpleNamespace(window_text=lambda: choice, control_id=lambda: control_id,
                                 is_visible=lambda: True, is_enabled=lambda: True)
        dialog = SimpleNamespace(handle=66, class_name=lambda: '#32770', window_text=lambda: title,
                                 is_visible=lambda: state['visible'], is_enabled=lambda: True,
                                 descendants=lambda **kw: [button])
        owner = SimpleNamespace(session=SimpleNamespace(proc=SimpleNamespace(pid=321)),
            desktop=SimpleNamespace(windows=lambda **kw: [dialog]),
            probe=SimpleNamespace(user=SimpleNamespace(IsWindow=lambda hwnd: True,
                                                      IsWindowVisible=lambda hwnd: state['visible'])))
        bound = BoundDocumentWindow(owner, 'B', None, editor(20))
        bound.bind_dialog = lambda dialog: None
        bound._prompt_text = lambda dialog: prompt
        def click(dialog, button, **expected):
            events.append(expected); state['visible'] = False
        bound.click_dialog_button = click
        bound.finish_dialog = lambda hwnd: None
        def once(check, **kw):
            if not check(): raise AssertionError('Read-only condition is not ready')
        with patch('driver.until', once):
            try: bound.choose_unsaved(choice, '창 B 문서.hwpx')
            except AssertionError as error:
                error.input_events = events.copy()
                raise
        return events

    def test_source_known_yes_no_cancel_ids_and_exact_document_prompt_are_requested(self):
        for choice, control_id in (('저장', 1004), ('저장 안 함', 1008), ('취소', 1001)):
            with self.subTest(choice=choice):
                events = self.choose(choice=choice, control_id=control_id)
                self.assertEqual(events, [{'expected_control_id': control_id, 'expected_label': choice,
                    'expected_title': '저장 확인', 'expected_prompt': '창 B 문서.hwpx의 변경 내용을 저장할까요?'}])

    def test_initial_wrong_unsaved_button_id_never_becomes_its_own_expectation(self):
        for wrong_id in (1, 2, 1000, 1001, 1008):
            with self.subTest(wrong_id=wrong_id):
                with self.assertRaises(AssertionError) as caught: self.choose(control_id=wrong_id)
                self.assertEqual(caught.exception.input_events, [])

    def test_initial_wrong_document_prefix_suffix_extra_prompt_or_title_sends_no_input(self):
        for prompt in ('다른 창 B 문서.hwpx의 변경 내용을 저장할까요?',
                       '창 B 문서.hwpx.bak의 변경 내용을 저장할까요?',
                       '창 A 문서.hwpx의 변경 내용을 저장할까요?',
                       '창 B 문서.hwpx의 변경 내용을 저장할까요?\n다른 문서도 저장합니다.'):
            with self.subTest(prompt=prompt):
                with self.assertRaises(AssertionError) as caught: self.choose(prompt=prompt)
                self.assertEqual(caught.exception.input_events, [])
        with self.assertRaises(AssertionError) as caught: self.choose(title='다른 저장 확인')
        self.assertEqual(caught.exception.input_events, [])

if __name__ == '__main__': unittest.main()
