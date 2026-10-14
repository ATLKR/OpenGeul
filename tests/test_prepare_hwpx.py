"""Cancellation must finish in the application before the native driver continues."""
import importlib.util
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import prepare_hwpx


def load_driver():
    api = types.SimpleNamespace(sync_playwright=Mock(), expect=Mock())
    spec = importlib.util.spec_from_file_location('cancel_save_driver', ROOT/'e2e/driver.py')
    driver = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'playwright': types.ModuleType('playwright'), 'playwright.sync_api': api}), \
            patch.object(sys, 'path', [str(ROOT/'e2e'), *sys.path]):
        spec.loader.exec_module(driver)
    return driver


class CancelledSaveAsDriverTests(unittest.TestCase):
    def setUp(self):
        self.driver = load_driver()
        self.events = []
        self.session = self.driver.Session.__new__(self.driver.Session)
        self.session.mode = 'native'
        self.session.page = Mock()
        self.session.native_dialog = Mock(side_effect=lambda target: self.events.append(('dialog-closed', target)))
        self.driver.menu = Mock(side_effect=lambda page, command: self.events.append(('menu', command)))
        self.driver.expect = Mock(return_value=types.SimpleNamespace(to_have_text=self.wait_for_completion))

    def wait_for_completion(self, message, *, timeout):
        self.events.append(('completion', message, timeout))

    def test_cancel_waits_for_exact_application_completion_before_returning(self):
        result = self.session.save(Path('original.hwpx'), Path('must-not-exist.hwpx'), save_as=True, cancel=True)
        self.events.append(('returned', result))
        self.assertEqual(self.events, [
            ('menu', 'file:save-as'), ('dialog-closed', None),
            ('completion', '다른 이름으로 저장 취소', 30000), ('returned', None),
        ])
        self.session.page.locator.assert_called_once_with('#sb-message')
        self.session.page.wait_for_function.assert_not_called()

    def test_missing_cancellation_completion_fails_without_retrying(self):
        def incomplete(message, *, timeout):
            self.wait_for_completion(message, timeout=timeout)
            raise AssertionError('application cancellation did not complete')
        self.driver.expect.return_value.to_have_text = incomplete
        with self.assertRaisesRegex(AssertionError, 'application cancellation did not complete'):
            self.session.save(Path('original.hwpx'), Path('must-not-exist.hwpx'), save_as=True, cancel=True)
        self.driver.menu.assert_called_once_with(self.session.page, 'file:save-as')
        self.session.native_dialog.assert_called_once_with(None)
        self.driver.expect.assert_called_once()


class NativePickerReadinessTests(unittest.TestCase):
    def setUp(self):
        self.driver = load_driver()
        self.session = self.driver.Session.__new__(self.driver.Session)
        self.session.proc = types.SimpleNamespace(pid=123)
        self.session.page = Mock()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session.folder = Path(self.temp.name)
        self.evidence = self.session.folder/'native-picker-readiness.json'
        self.filename = Mock()
        self.filename.class_name.return_value = 'Edit'
        self.filename.parent.return_value.class_name.return_value = 'ComboBox'
        self.filename.is_visible.return_value = True
        self.filename.is_enabled.return_value = True
        # Preserve actual Edit input/readback semantics in this offline fixture.
        self.filename.window_text.return_value = ''
        self.filename.set_edit_text.side_effect = lambda value: setattr(self.filename.window_text, 'return_value', value)
        self.button = Mock()
        self.button.control_id.return_value = 1
        self.button.is_visible.return_value = True
        self.button.is_enabled.return_value = True
        self.dialog = Mock(handle=456)
        self.dialog.process_id.return_value = 123
        self.dialog.class_name.return_value = '#32770'
        self.dialog.window_text.return_value = 'Save As'
        self.spec = Mock()
        self.spec.wrapper_object.return_value = self.dialog
        self.desktop = Mock()
        self.desktop.window.return_value = self.spec
        self.api = patch.dict(sys.modules, {'pywinauto': types.SimpleNamespace(Desktop=lambda **kw: self.desktop)})
        self.api.start()
        self.addCleanup(self.api.stop)
        class InvalidWindowHandle(RuntimeError):
            pass
        error_api = patch.dict(sys.modules, {
            'pywinauto.controls': types.ModuleType('pywinauto.controls'),
            'pywinauto.controls.hwndwrapper': types.SimpleNamespace(InvalidWindowHandle=InvalidWindowHandle)})
        error_api.start()
        self.addCleanup(error_api.stop)
        self.closed = False
        self.button.click_input.side_effect = lambda: setattr(self, 'closed', True)
        def thread(hwnd, pid):
            pid._obj.value = 123
            return 7
        def classname(hwnd, text, size):
            text.value = '#32770'
            return len(text.value)
        self.driver.ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(
            user32=types.SimpleNamespace(IsWindow=lambda hwnd: not self.closed,
                IsWindowVisible=lambda hwnd: not self.closed, IsWindowEnabled=lambda hwnd: True,
                GetWindowThreadProcessId=thread, GetClassNameW=classname)),
            c_uint32=ctypes.c_uint32, byref=ctypes.byref, create_unicode_buffer=ctypes.create_unicode_buffer)
        self.driver.until = Mock(side_effect=self.poll)

    def poll(self, check, timeout=25, **kwargs):
        # Model bounded polling without sleeping or performing any dialog action.
        for _ in range(3):
            try:
                value = check()
                if value:
                    return value
            except ValueError:
                pass
        raise AssertionError('native picker filename never became ready')

    def test_waits_for_initially_missing_filename_then_acts_once(self):
        self.dialog.descendants.side_effect = [[], [self.filename], [self.button]]
        target = Path('selected.hwpx')
        self.session.native_dialog(target)
        self.desktop.window.assert_called_once_with(class_name='#32770', process=123)
        self.filename.set_edit_text.assert_called_once_with(str(target))
        self.filename.window_text.assert_called_once_with()
        self.button.click_input.assert_called_once()
        self.assertEqual(self.dialog.descendants.call_count, 3)
        self.assertFalse(self.evidence.exists())

    def test_changed_filename_after_initial_readiness_never_clicks(self):
        self.dialog.descendants.side_effect = [[], [self.filename]]
        self.filename.window_text.side_effect = lambda: 'different-output.hwpx'
        target = Path('selected.hwpx')
        with self.assertRaisesRegex(AssertionError, 'Native filename changed'):
            self.session.native_dialog(target)
        self.filename.set_edit_text.assert_called_once_with(str(target))
        self.filename.window_text.assert_called_once_with()
        self.dialog.set_focus.assert_not_called()
        self.button.click_input.assert_not_called()
        self.assertEqual(self.dialog.descendants.call_count, 2)
        self.assertFalse(self.evidence.exists())

    def test_never_ready_picker_fails_before_setting_or_clicking(self):
        self.dialog.descendants.return_value = []
        with self.assertRaisesRegex(AssertionError, 'filename never became ready'):
            self.session.native_dialog(Path('selected.hwpx'))
        self.filename.set_edit_text.assert_not_called()
        self.button.click_input.assert_not_called()

    def test_wrong_owner_is_rejected_before_enumerating_controls(self):
        self.dialog.process_id.return_value = 999
        self.dialog.descendants.side_effect = lambda **kw: [self.button] if kw else [self.filename]
        with self.assertRaisesRegex(AssertionError, 'ownership'):
            self.session.native_dialog(Path('selected.hwpx'))
        self.dialog.descendants.assert_not_called()
        self.dialog.window_text.assert_not_called()
        self.button.click_input.assert_not_called()
        self.assertFalse(self.evidence.exists())

    def test_failed_readiness_records_only_verified_owned_metadata(self):
        self.dialog.descendants.return_value = []
        with self.assertRaisesRegex(AssertionError, 'filename never became ready'):
            self.session.native_dialog(Path('selected.hwpx'))
        value = json.loads(self.evidence.read_bytes())
        self.assertEqual({key: value[key] for key in ('hwnd', 'pid', 'class', 'title')},
                         {'hwnd': 456, 'pid': 123, 'class': '#32770', 'title': 'Save As'})
        self.assertEqual(value['descendants'], [])
        self.assertFalse(value['collectionFailed'])
        self.assertLessEqual(self.evidence.stat().st_size, 16*1024)
        self.filename.set_edit_text.assert_not_called()
        self.button.click_input.assert_not_called()

    def test_many_unicode_controls_and_long_title_stay_bounded(self):
        control = Mock()
        control.class_name.return_value = '界'*512
        control.parent.return_value.class_name.return_value = '類'*512
        control.control_id.return_value = 42
        control.is_visible.return_value = True
        control.is_enabled.return_value = False
        control.window_text.side_effect = AssertionError('control text must never be collected')
        control.get_edit_text.side_effect = AssertionError('filename text must never be collected')
        self.dialog.window_text.return_value = '저'*1024
        self.dialog.descendants.return_value = [control]*1000
        self.driver.until.side_effect = AssertionError('native picker filename never became ready')
        with self.assertRaisesRegex(AssertionError, 'filename never became ready'):
            self.session.native_dialog(Path('secret-filename.hwpx'))
        raw = self.evidence.read_bytes()
        value = json.loads(raw)
        self.assertLessEqual(len(raw), 16*1024)
        self.assertEqual(len(value['title']), 256)
        self.assertGreater(len(value['descendants']), 0)
        self.assertLessEqual(len(value['descendants']), 64)
        for record in value['descendants']:
            self.assertEqual(set(record), {'class', 'parentClass', 'controlId', 'visible', 'enabled'})
            self.assertLessEqual(len(record['class']), 64)
            self.assertLessEqual(len(record['parentClass']), 64)
        for flag in ('titleTruncated', 'descendantsTruncated', 'classNamesTruncated', 'sizeTruncated'):
            self.assertTrue(value[flag], flag)
        self.assertNotIn(b'secret-filename', raw)
        control.window_text.assert_not_called()
        control.get_edit_text.assert_not_called()
        self.filename.set_edit_text.assert_not_called()
        self.button.click_input.assert_not_called()

    def test_collection_failure_preserves_original_exception_and_omits_error_text(self):
        failure = AssertionError('original readiness failure')
        self.driver.until.side_effect = failure
        self.dialog.descendants.side_effect = OSError('private document/password text')
        with self.assertRaises(AssertionError) as caught:
            self.session.native_dialog(Path('selected.hwpx'))
        self.assertIs(caught.exception, failure)
        raw = self.evidence.read_bytes()
        value = json.loads(raw)
        self.assertTrue(value['collectionFailed'])
        self.assertEqual(value['descendants'], [])
        self.assertNotIn(b'private document/password text', raw)
        self.button.click_input.assert_not_called()

    def test_owner_changed_after_readiness_failure_writes_no_metadata(self):
        failure = AssertionError('original readiness failure')
        self.driver.until.side_effect = failure
        self.dialog.process_id.side_effect = [123, 999]
        with self.assertRaises(AssertionError) as caught:
            self.session.native_dialog(Path('selected.hwpx'))
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.evidence.exists())
        self.dialog.window_text.assert_not_called()
        self.dialog.descendants.assert_not_called()
        self.button.click_input.assert_not_called()

    def test_metadata_write_failure_preserves_original_exception(self):
        failure = AssertionError('original readiness failure')
        self.driver.until.side_effect = failure
        self.dialog.descendants.return_value = []
        self.session.folder = self.session.folder/'does-not-exist'
        with self.assertRaises(AssertionError) as caught:
            self.session.native_dialog(Path('selected.hwpx'))
        self.assertIs(caught.exception, failure)
        self.button.click_input.assert_not_called()

    def test_changed_pinned_hwnd_writes_no_metadata(self):
        failure = AssertionError('original readiness failure')
        def fail(check, **kwargs):
            self.dialog.handle = 789
            raise failure
        self.driver.until.side_effect = fail
        with self.assertRaises(AssertionError) as caught:
            self.session.native_dialog(Path('selected.hwpx'))
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.evidence.exists())
        self.dialog.window_text.assert_not_called()
        self.dialog.descendants.assert_not_called()
        self.button.click_input.assert_not_called()


class StoredLineOriginPreparationTests(unittest.TestCase):
    """Public ledger assembly only; host patch anchors are separate dependencies.

    This tiny authored source does not qualify Rust parsing or native GUI output.
    Host replacements and prior feature proof checks are isolated so the real
    preparation function can exercise its final source-proof/ledger boundary.
    """
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name)
        self.ledger = self.source/'.opengeul-overlay.json'
        files = {
            'apps/studio-host/src/core/tauri-bridge.ts':
                '  private async saveHwpThroughStaging(\n  private async confirmExternalOverwriteIfNeeded(\n',
            'apps/studio-host/src/core/tauri-bridge.test.ts':
                "  it('blocks direct save for HWPX sources', () => {});\n"
                "  it.each([false, true])('saves HWP bytes through native state', () => {});\n",
            'apps/studio-host/src/main.ts': '// owned host fixture\n',
            'apps/desktop/src-tauri/src/owned-protected.rs': '// owned preserved capability\n',
            'third_party/rhwp/src/parser/body_text.rs': '// owned parser fixture\n',
            'third_party/rhwp/src/parser/hwpx/section.rs': '// owned HWPX parser fixture\n',
            'third_party/rhwp/src/serializer/hwpx/section.rs': '// owned HWPX serializer fixture\n',
            'third_party/rhwp/src/document_core/commands/object_ops/picture.rs': '// owned picture fixture\n',
            'third_party/rhwp/src/document_core/commands/text_editing.rs': '// owned virtual picture layout fixture\n',
        }
        for name, data in files.items():
            path = self.source/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data, encoding='utf-8')
        protected = 'apps/desktop/src-tauri/src/owned-protected.rs'
        self.original = {'preservedFiles': {protected:self.sha(self.source/protected)},
                         'changes':['owned miniature preparation input'],
                         'asyncFontSelectionGuard': {'afterSha256':{}},
                         'menuClipboardPaste': {'testFixture':'owned prior proof'}}
        self.ledger.write_text(json.dumps(self.original)+'\n', encoding='utf-8')
        self.original_ledger = self.ledger.read_bytes()
        self.observed = []
        for target in ('replace', 'validate_async_font_selection_proof'):
            control = patch.object(prepare_hwpx, target)
            control.start(); self.addCleanup(control.stop)
        menu_validation = patch.object(prepare_hwpx.menu_clipboard, 'validate')
        menu_validation.start(); self.addCleanup(menu_validation.stop)
        refresh = patch.object(prepare_hwpx.menu_clipboard, 'refresh_hwpx_lib',
                               side_effect=lambda source, proof:self.observed.append('menu-final'))
        refresh.start(); self.addCleanup(refresh.stop)
        stored = patch.object(prepare_hwpx, 'apply_stored_lineseg_origin')
        self.stored = stored.start(); self.addCleanup(stored.stop)
        hashes = {name:self.sha(self.source/name) for name in files
                  if name.startswith('third_party/rhwp/') and not name.endswith(('/picture.rs', '/text_editing.rs'))}
        self.proof = {'beforeSha256':dict(hashes), 'afterSha256':dict(hashes), 'helperSha256':'a'*64}
        self.stored.return_value = self.proof
        picture = patch.object(prepare_hwpx, 'apply_picture_line_segment_owner')
        self.picture = picture.start(); self.addCleanup(picture.stop)
        name = 'third_party/rhwp/src/document_core/commands/object_ops/picture.rs'
        picture_hash = self.sha(self.source/name)
        self.picture_proof = {'beforeSha256':{name:picture_hash},
                              'afterSha256':{name:picture_hash}, 'helperSha256':'b'*64}
        self.picture.return_value = self.picture_proof
        virtual = patch.object(prepare_hwpx, 'apply_virtual_picture_layout_admission')
        self.virtual = virtual.start(); self.addCleanup(virtual.stop)
        name = 'third_party/rhwp/src/document_core/commands/text_editing.rs'
        virtual_hash = self.sha(self.source/name)
        self.virtual_proof = {'beforeSha256':{name:virtual_hash},
                              'afterSha256':{name:virtual_hash}, 'helperSha256':'c'*64}
        self.virtual.return_value = self.virtual_proof

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_unreviewed_stored_source_cannot_publish_hwpx_completion_ledger(self):
        self.stored.side_effect = ValueError('Unreviewed stored line source')
        with self.assertRaisesRegex(ValueError, 'Unreviewed stored line source'):
            prepare_hwpx.patch(self.source)
        self.assertEqual(self.ledger.read_bytes(), self.original_ledger)
        self.picture.assert_not_called()
        self.virtual.assert_not_called()

    def test_unreviewed_picture_source_cannot_publish_hwpx_completion_ledger(self):
        self.picture.side_effect = ValueError('Unreviewed picture line owner source')
        with self.assertRaisesRegex(ValueError, 'Unreviewed picture line owner source'):
            prepare_hwpx.patch(self.source)
        self.stored.assert_called_once_with(self.source)
        self.picture.assert_called_once_with(self.source)
        self.assertEqual(self.ledger.read_bytes(), self.original_ledger)
        self.virtual.assert_not_called()

    def test_unreviewed_virtual_layout_source_cannot_publish_hwpx_completion_ledger(self):
        self.virtual.side_effect = ValueError('Unreviewed virtual picture layout source')
        with self.assertRaisesRegex(ValueError, 'Unreviewed virtual picture layout source'):
            prepare_hwpx.patch(self.source)
        self.stored.assert_called_once_with(self.source)
        self.picture.assert_called_once_with(self.source)
        self.virtual.assert_called_once_with(self.source)
        self.assertEqual(self.ledger.read_bytes(), self.original_ledger)

    def test_final_hwpx_ledger_binds_virtual_layout_after_picture_without_rewriting_prior_proofs(self):
        def virtual(source):
            self.assertEqual(source, self.source)
            self.assertEqual(self.ledger.read_bytes(), self.original_ledger)
            self.stored.assert_called_once_with(self.source)
            self.picture.assert_called_once_with(self.source)
            self.assertEqual(self.observed, ['menu-final'])
            return self.virtual_proof
        self.virtual.side_effect = virtual
        prepare_hwpx.patch(self.source)
        value = json.loads(self.ledger.read_bytes())
        self.assertEqual(value['storedLineSegmentOrigin'], self.proof)
        self.assertEqual(value['pictureLineSegmentOwner'], self.picture_proof)
        self.assertEqual(value['virtualPictureLayoutAdmission'], self.virtual_proof)
        self.assertEqual(value['baselinePreservedFiles'], self.original['preservedFiles'])
        self.assertEqual(value['preservedFiles'], self.original['preservedFiles'])
        self.assertTrue(value['hwpxSaveV1'])
        self.virtual.assert_called_once_with(self.source)

    def test_final_hwpx_ledger_binds_picture_proof_after_stored_origin_without_rewriting_prior_proof(self):
        def stored(source):
            self.assertEqual(self.observed, ['menu-final'])
            self.assertEqual(self.ledger.read_bytes(), self.original_ledger)
            self.observed.append('stored-final')
            return self.proof
        def picture(source):
            self.assertEqual(source, self.source)
            self.assertEqual(self.observed, ['menu-final', 'stored-final'])
            self.assertEqual(self.ledger.read_bytes(), self.original_ledger)
            self.observed.append('picture-final')
            return self.picture_proof
        self.stored.side_effect = stored
        self.picture.side_effect = picture
        prepare_hwpx.patch(self.source)
        value = json.loads(self.ledger.read_bytes())
        self.assertEqual(value['storedLineSegmentOrigin'], self.proof)
        self.assertEqual(value['pictureLineSegmentOwner'], self.picture_proof)
        self.assertEqual(value['virtualPictureLayoutAdmission'], self.virtual_proof)
        self.assertEqual(value['baselinePreservedFiles'], self.original['preservedFiles'])
        self.assertEqual(value['preservedFiles'], self.original['preservedFiles'])
        self.assertTrue(value['hwpxSaveV1'])
        self.assertEqual(self.observed, ['menu-final', 'stored-final', 'picture-final'])
        self.picture.assert_called_once_with(self.source)

    def test_final_hwpx_ledger_binds_exact_stored_source_proof_after_prior_features(self):
        def stored(source):
            self.assertEqual(self.observed, ['menu-final'])
            self.assertEqual(self.ledger.read_bytes(), self.original_ledger)
            self.observed.append('stored-final')
            return self.proof
        self.stored.side_effect = stored
        prepare_hwpx.patch(self.source)
        value = json.loads(self.ledger.read_bytes())
        self.assertEqual(value['storedLineSegmentOrigin'], self.proof)
        self.assertEqual(value['pictureLineSegmentOwner'], self.picture_proof)
        self.assertEqual(value['virtualPictureLayoutAdmission'], self.virtual_proof)
        self.assertTrue(value['hwpxSaveV1'])
        self.assertEqual(value['baselinePreservedFiles'], self.original['preservedFiles'])
        self.assertEqual(value['preservedFiles'], self.original['preservedFiles'])
        self.assertEqual(self.observed, ['menu-final', 'stored-final'])
        self.stored.assert_called_once_with(self.source)


if __name__ == '__main__':
    unittest.main()
