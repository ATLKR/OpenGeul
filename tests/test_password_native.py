import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('password_native', ROOT / 'e2e/password/native.py')
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class CompletionPage:
    def __init__(self, title='• protected.hwp - OpenGeul', *, terminal=True, editable=True):
        self.current_title = title
        self.terminal = terminal
        self.editable = editable
        self.calls = []

    def wait_for_function(self, expression, *, arg=None, timeout):
        if arg is not None:
            self.calls.append(('terminal', arg, timeout))
            if not self.terminal:
                raise TimeoutError('Cancellation never completed')
        else:
            self.calls.append(('editing', timeout))
            if not self.editable:
                raise TimeoutError('Editing never became ready')

    def title(self):
        self.calls.append(('title',))
        return self.current_title

    def locator(self, selector):
        self.calls.append(('locator', selector))
        return SimpleNamespace(wait_for=lambda **kwargs: self.calls.append(('input', kwargs)))

    def is_closed(self):
        return False


class PasswordCancellationTests(unittest.TestCase):
    def setUp(self):
        self.probe = NATIVE.Qualification.__new__(NATIVE.Qualification)
        self.document = Path('protected.hwp')

    def test_terminal_completion_precedes_document_and_editing_readiness(self):
        page = CompletionPage()
        self.probe.wait_cancelled_operation(SimpleNamespace(page=page), '파일 열기 취소', self.document)
        self.assertEqual(page.calls, [
            ('terminal', '파일 열기 취소', 30000), ('title',), ('editing', 30000),
            ('locator', 'textarea[aria-label="문서 편집 입력"]'), ('input', {'state': 'attached'}),
        ])

    def test_missing_terminal_fails_even_when_title_and_editor_look_ready(self):
        page = CompletionPage(terminal=False)
        with self.assertRaisesRegex(TimeoutError, 'never completed'):
            self.probe.wait_cancelled_operation(SimpleNamespace(page=page), '창 닫기 취소', self.document)
        self.assertEqual(page.calls, [('terminal', '창 닫기 취소', 30000)])

    def test_terminal_does_not_accept_replaced_document(self):
        page = CompletionPage(title='• prior.hwpx - OpenGeul')
        with self.assertRaisesRegex(AssertionError, 'replaced'):
            self.probe.wait_cancelled_operation(SimpleNamespace(page=page), '파일 열기 취소', self.document)
        self.assertEqual(page.calls, [('terminal', '파일 열기 취소', 30000), ('title',)])

    def test_terminal_does_not_accept_editor_that_remains_disabled(self):
        page = CompletionPage(editable=False)
        with self.assertRaisesRegex(TimeoutError, 'Editing never'):
            self.probe.wait_cancelled_operation(SimpleNamespace(page=page), '다른 이름으로 저장 취소', self.document)
        self.assertEqual(page.calls[-1], ('editing', 30000))

    def test_dirty_replacement_waits_for_completion_before_next_native_close(self):
        class NextClose(Exception):
            pass

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            prior, protected = folder / 'prior.hwpx', folder / 'protected.hwp'
            protected.write_bytes(b'owned encrypted source')
            checksum = NATIVE.sha(protected)
            page = CompletionPage()
            session = SimpleNamespace(page=page, proc=SimpleNamespace(poll=lambda: None),
                                      native_dialog=Mock(), wait_loaded=Mock(), close=Mock())
            self.probe.session = Mock(return_value=(folder, prior, protected, checksum, session))
            self.probe.open_protected = Mock(return_value=MagicMock())
            self.probe.password = 'owned password'
            self.probe.edit = Mock()
            self.probe.menu = Mock()
            self.probe.unsaved_choice = Mock(return_value={'choice': '취소'})
            self.probe.request_native_close = Mock(side_effect=NextClose)
            with self.assertRaises(NextClose):
                self.probe.dirty_close_replacement('hwp')
            self.assertEqual(page.calls[:4], [('title',), ('title',),
                                             ('terminal', '파일 열기 취소', 30000), ('title',)])
            session.wait_loaded.assert_called_once_with(protected.name)
            self.assertEqual(NATIVE.sha(protected), checksum)
            session.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
