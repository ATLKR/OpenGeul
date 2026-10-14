"""Draft mandatory native UI cases; imported into native suite only after review.

All actions use public menus/textarea or actual Windows input. XML expectations
are predetermined owned text; application exports are never used as goldens.
This module has not run on Windows and does not assert qualification by itself.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess

from playwright.sync_api import expect
from driver import digest, until
from hwpx_oracle import inspect_hwpx
from supported_feature_oracle import text_fixture
from native_document_policy import assert_body_markers
from native_document_windows import OwnedDocumentWindows
from test_editor import FIXTURES, EXE

class NativeDocumentLifecycleCases:
    def _owned_windows(self):
        owner = OwnedDocumentWindows(self.session)
        self.addCleanup(owner.close)
        return owner, owner.first()

    def _saved_body(self, path, required, forbidden=(), *, exact=None, label):
        if path.suffix.lower() == '.hwp':
            self.assertTrue(path.read_bytes().startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'))
            from native_architecture import verify_executable
            architecture = self.session.native_architecture['architecture']
            cli = EXE.parent/'Tools/rhwp.exe'
            verify_executable(cli, architecture)
            converted = self.folder/f'{label}-independent-container.hwpx'
            self.assertFalse(converted.exists(), 'Oracle conversion target must be fresh')
            result = subprocess.run([str(cli), 'export-hwpx', str(path), str(converted)],
                                    cwd=cli.parent, capture_output=True, timeout=90)
            self.assertLessEqual(len(result.stdout)+len(result.stderr), 1024*1024)
            (self.folder/f'{label}-cli.log').write_bytes(result.stdout+b'\n'+result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            payload = converted
        else:
            self.assertEqual(path.suffix.lower(), '.hwpx')
            self.assertTrue(path.read_bytes().startswith(b'PK\x03\x04'))
            payload = path
        inspection = assert_body_markers(payload, required, forbidden, exact_text=exact)
        (self.folder/f'{label}-body-oracle.json').write_text(json.dumps({
            'path': path.name, 'sha256': digest(path), 'oracleContainer': payload.name,
            'oracleContainerSha256': digest(payload), 'required': list(required),
            'forbidden': list(forbidden), 'bodyText': inspection['bodyText'],
            'bodyParagraphs': inspection['bodyParagraphs'],
        }, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        return inspection

    def _new_first_save(self, format):
        source = self.document
        source_sha = digest(source)
        old_marker = 'OpenGeul fixture 한글 가나다 & <xml> Ω 123'
        marker = f'새문서-{format.upper()}-한글-Ω-123'
        again = '-실제재열기-456'
        target = self.folder/f'첫 저장 결과.{format}'
        self.assertFalse(target.exists())
        owner, current = self._owned_windows()
        current.menu('file:new-doc')
        current.wait_loaded('새 문서.hwp')
        self.assertFalse(current.page.title().startswith('• '))
        current.edit(marker)
        self.assertTrue(current.page.title().startswith('• '))
        self.checked('new-dirty')
        current.save_first(target, cancel=True)
        self.assertFalse(target.exists())
        self.assertEqual(digest(source), source_sha)
        self.assertTrue(current.page.title().startswith('• '))
        self.checked('first-picker-cancel')
        # This second actual command/picker/success proves the cancelled command
        # released its lock; picker disappearance alone did not prove that.
        current.save_first(target)
        self._saved_body(target, [marker], [old_marker], exact=marker, label='first-save')
        self.assertEqual(digest(source), source_sha)
        self.assertFalse(current.page.title().startswith('• '))
        self.checked('first-save-format-body')
        current.request_close()
        current.wait_closed()
        owner.close()
        self.checked('clean-native-close')
        # Reopening invokes a fresh actual production executable, not a WASM
        # parser-only recreation or the converter's notion of successful open.
        self.open(target)
        reopened_owner, reopened = self._owned_windows()
        reopened.edit(again)
        reopened.save_existing(target)
        self._saved_body(target, [marker, again], [old_marker], exact=marker+again, label='first-reopen')
        self.assertEqual(digest(source), source_sha)
        self.checked('reopen-next-direct-save')

    def test_native_new_document_first_save_hwp_cancel_success_reopen(self):
        self._new_first_save('hwp')

    def test_native_new_document_first_save_hwpx_cancel_success_reopen(self):
        self._new_first_save('hwpx')

    def test_multiple_windows_use_real_native_creation(self):
        # Preserve the original public New Window assertion, then test actual
        # document ownership rather than stopping at another rendered root.
        path_a = text_fixture(FIXTURES/'blank.hwpx', self.folder/'창 A 문서.hwpx', ['DOC-A-BASE'])
        path_b = text_fixture(FIXTURES/'blank.hwpx', self.folder/'창 B 문서.hwpx', ['DOC-B-BASE'])
        source_a, source_b = digest(path_a), digest(path_b)
        self.open(path_a)
        owner, a = self._owned_windows()
        before_pages = len(self.session.context.pages)
        b = owner.new(a)
        self.assertGreater(len(self.session.context.pages), before_pages)
        self.assertFalse(a.page.is_closed())
        self.assertNotEqual(a.hwnd, b.hwnd)
        expect(b.page.locator('#studio-root')).to_be_visible()
        self.checked('two-native-page-hwnds')
        b.open(path_b)
        a.edit('-DOC-A-EDIT-Ω')
        b.edit('-DOC-B-EDIT-한글')
        self.assertTrue(a.page.title().startswith('• '))
        self.assertTrue(b.page.title().startswith('• '))
        b.save_existing(path_b)
        self._saved_body(path_b, ['DOC-B-BASE', 'DOC-B-EDIT-한글'], ['DOC-A-BASE', 'DOC-A-EDIT-Ω'],
                         exact='DOC-B-BASE-DOC-B-EDIT-한글', label='b-first-save')
        self.assertEqual(digest(path_a), source_a)
        self.assertNotEqual(digest(path_b), source_b)
        self.assertTrue(a.page.title().startswith('• '))
        self.checked('b-save-keeps-a-source-dirty')
        a.save_existing(path_a)
        self._saved_body(path_a, ['DOC-A-BASE', 'DOC-A-EDIT-Ω'], ['DOC-B-BASE', 'DOC-B-EDIT-한글'],
                         exact='DOC-A-BASE-DOC-A-EDIT-Ω', label='a-first-save')
        self.assertFalse(a.page.title().startswith('• '))
        self.assertFalse(b.page.title().startswith('• '))
        saved_a, saved_b = digest(path_a), digest(path_b)
        self.checked('independent-two-saved-bodies')
        b.edit('-DOC-B-UNSAVED-789')
        b.request_close()
        b.choose_unsaved('취소', path_b.name)
        self.assertFalse(b.page.is_closed())
        b._editor()
        self.assertTrue(b.page.title().startswith('• '))
        self.assertEqual(digest(path_a), saved_a)
        self.assertEqual(digest(path_b), saved_b)
        self.assertFalse(a.page.is_closed())
        self.checked('b-close-cancel-keeps-b-dirty-a-live')
        b.request_close()
        b.choose_unsaved('저장', path_b.name)
        b.wait_closed()
        self._saved_body(path_b, ['DOC-B-BASE', 'DOC-B-EDIT-한글', 'DOC-B-UNSAVED-789'],
                         ['DOC-A-BASE', 'DOC-A-EDIT-Ω'],
                         exact='DOC-B-BASE-DOC-B-EDIT-한글-DOC-B-UNSAVED-789', label='b-close-save')
        self.assertEqual(digest(path_a), saved_a)
        self.assertFalse(a.page.is_closed())
        self.assertIsNone(self.session.proc.poll())
        self.checked('b-close-save-keeps-a-live')
        a.edit('-DOC-A-AFTER-B-CLOSE')
        a.save_existing(path_a)
        self._saved_body(path_a, ['DOC-A-BASE', 'DOC-A-EDIT-Ω', 'DOC-A-AFTER-B-CLOSE'],
                         ['DOC-B-BASE', 'DOC-B-EDIT-한글', 'DOC-B-UNSAVED-789'],
                         exact='DOC-A-BASE-DOC-A-EDIT-Ω-DOC-A-AFTER-B-CLOSE', label='a-after-b-close')
        self.checked('a-next-edit-save-after-b-close')
        a.request_close(); a.wait_closed()
        self.checked('a-clean-close-after-b-close')
        owner.close()
        # Independently reopen both saved results through the actual app.
        for path, markers, forbidden, label, again, previous_body in (
            (path_b, ['DOC-B-BASE', 'DOC-B-EDIT-한글', 'DOC-B-UNSAVED-789'], ['DOC-A-BASE'], 'b-reopen',
             '-DOC-B-REOPEN', 'DOC-B-BASE-DOC-B-EDIT-한글-DOC-B-UNSAVED-789'),
            (path_a, ['DOC-A-BASE', 'DOC-A-EDIT-Ω', 'DOC-A-AFTER-B-CLOSE'], ['DOC-B-BASE'], 'a-reopen',
             '-DOC-A-REOPEN', 'DOC-A-BASE-DOC-A-EDIT-Ω-DOC-A-AFTER-B-CLOSE')):
            self.open(path)
            reopened_owner, reopened = self._owned_windows()
            reopened.edit(again)
            reopened.save_existing(path)
            self._saved_body(path, [*markers, again], forbidden, exact=previous_body+again, label=label)
            reopened_owner.close()
        self.checked('both-real-native-reopens')

    def test_native_dirty_new_cancel_then_safety_save_preserves_document(self):
        source = self.document; original = digest(source)
        marker = '-DIRTY-NEW-한글-Ω'
        owner, current = self._owned_windows()
        current.edit(marker)
        current.menu('file:new-doc')
        current.choose_unsaved('취소', source.name)
        self.assertTrue(current.page.title().startswith('• '))
        self.assertEqual(digest(source), original)
        self.checked('new-cancel-keeps-source-dirty')
        current.menu('file:new-doc')
        current.choose_unsaved('저장', source.name)
        current.wait_loaded('새 문서.hwp')
        self._saved_body(source, ['OpenGeul fixture', marker], label='new-safety-save')
        self.assertFalse(current.page.title().startswith('• '))
        self.checked('new-safety-save-before-blank')
        fresh = '-NEW-AFTER-SAFETY-SAVE'
        target = self.folder/'교체 뒤 새 문서.hwpx'
        current.edit(fresh)
        current.save_first(target)
        self._saved_body(target, [fresh], ['OpenGeul fixture', marker], exact=fresh, label='new-after-safety')
        self.checked('blank-next-save-has-no-old-document')
        owner.close()
        self.open(source)
        reopened_owner, reopened = self._owned_windows()
        again = '-SAFETY-SOURCE-REOPEN'
        reopened.edit(again)
        reopened.save_existing(source)
        self._saved_body(source, ['OpenGeul fixture', marker, again], ['NEW-AFTER-SAFETY-SAVE'],
                         exact='OpenGeul fixture 한글 가나다 & <xml> Ω 123'+marker+again,
                         label='safety-source-reopen')
        self.checked('safety-saved-source-real-reopen')

    def test_native_dirty_new_cancelled_safety_picker_keeps_document(self):
        source = self.document; original = digest(source)
        marker = 'UNSAVED-NEW-한글-Ω-321'
        cancelled = self.folder/'취소한 안전 저장.hwpx'
        target = self.folder/'취소 뒤 복구 저장.hwpx'
        owner, current = self._owned_windows()
        current.menu('file:new-doc'); current.wait_loaded('새 문서.hwp')
        current.edit(marker)
        self.checked('unsaved-new-dirty')
        current.menu('file:new-doc')
        current.choose_unsaved('저장', '새 문서.hwp')
        current.picker(cancelled, cancel=True)
        self.assertFalse(cancelled.exists())
        self.assertTrue(current.page.title().startswith('• '))
        self.assertEqual(digest(source), original)
        self.checked('safety-picker-cancel-keeps-new-dirty')
        current.save_first(target)
        self._saved_body(target, [marker], ['OpenGeul fixture'], exact=marker, label='safety-picker-next-save')
        self.assertFalse(cancelled.exists())
        self.assertEqual(digest(source), original)
        self.checked('next-real-save-retains-unsaved-text')
        owner.close()
        self.open(target)
        reopened_owner, reopened = self._owned_windows()
        again = '-AFTER-SAFETY-PICKER-REOPEN'
        reopened.edit(again)
        reopened.save_existing(target)
        self._saved_body(target, [marker, again], ['OpenGeul fixture'], exact=marker+again, label='safety-picker-reopen')
        self.checked('cancelled-safety-real-reopen')
