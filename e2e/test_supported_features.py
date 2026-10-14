"""실제 제품 public DOM/native controls로만 수행하는 지원 기능 필수 사례.

제품 실행은 승인된 Source Actions에서 한다. 로컬 oracle unit 통과는 이
파일의 browser/native 제품 실행 성공을 뜻하지 않는다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from playwright.sync_api import expect
from driver import Session, digest, edit, menu, primary_modifier, until
from hwpx_oracle import inspect_hwpx
from native_architecture import verify_process
from supported_feature_oracle import (
    A4, CELL_MARKERS, assert_picture, assert_style, assert_table,
    checkerboard, inspect_gui_pdf, inspect_supported_hwpx, text_fixture,
)
from ui_contract import hosted_recent_guard, require_owned_recent_paths
from test_editor import FIXTURES, OUTPUT, MODE, EXE, BROWSER


class SupportedTests:
    def checked(self, name):
        if not hasattr(self, 'supported_checks'):
            self.supported_checks = {}
        if name in self.supported_checks:
            raise AssertionError('Duplicate required UI oracle check: '+name)
        self.supported_checks[name] = True

    def blank(self, name='owned-blank.hwpx'):
        source = self.folder/name
        shutil.copy2(FIXTURES/'blank.hwpx', source)
        self.open(source)
        return source

    def area(self):
        return self.page.locator('textarea[aria-label="문서 편집 입력"]')

    def undo(self):
        self.area().focus()
        self.page.keyboard.press(primary_modifier(self.page)+'+z')

    def redo(self):
        self.area().focus()
        self.page.keyboard.press(primary_modifier(self.page)+'+Shift+z')

    def create_table(self):
        self.page.locator('#icon-toolbar button[data-cmd="table:create"]').click()
        cell = self.page.locator('[data-row="1"][data-col="1"]')
        expect(cell).to_be_visible()
        cell.hover(); cell.click()
        self.area().focus()
        for index, marker in enumerate(CELL_MARKERS):
            self.page.keyboard.insert_text(marker)
            if index < 3:
                self.page.keyboard.press('Tab')

    def test_supported_table_cells_row_undo_redo_reopen(self):
        self.blank()
        self.create_table()
        assert_table(self.save(), 2); self.checked('cells')
        menu(self.page, 'table:insert-row-below', category='table')
        assert_table(self.save(), 3); self.checked('row-added')
        self.undo(); assert_table(self.save(), 2); self.checked('undo')
        self.redo(); saved = self.save(); assert_table(saved, 3); self.checked('redo')
        self.open(saved); assert_table(self.save(), 3); self.checked('reopen')

    def test_supported_image_picker_placement_undo_redo_reopen(self):
        self.blank()
        image = checkerboard(self.folder/'owned-checkerboard.png')
        self.session.pick_image(image)
        placement = self.session.place_image()
        (self.folder/'image-placement.json').write_text(json.dumps(placement), encoding='utf-8')
        assert_picture(self.save(), 1); self.checked('placed')
        self.undo(); assert_picture(self.save(), 0); self.checked('undo')
        self.redo(); saved = self.save(); assert_picture(saved, 1); self.checked('redo')
        self.open(saved); assert_picture(self.save(), 1); self.checked('reopen')

    def test_supported_image_placement_cannot_cross_documents(self):
        self.blank('document-a.hwpx')
        image = checkerboard(self.folder/'owned-context-image.png')
        self.session.pick_image(image); self.checked('placement-ready')
        # A's image has fully decoded and placement is pending. Replace through
        # the actual file menu in the same Session; no race hooks/test bridge.
        replacement = text_fixture(FIXTURES/'blank.hwpx', self.folder/'document-b.hwpx', ['DOCUMENT-B-TARGET'])
        before = digest(replacement)
        self.session.open_public(replacement); self.document = replacement
        canvas = self.page.locator('canvas.document-page-canvas').first
        canvas.click(position={'x': 120, 'y': 160})
        saved = self.save()
        result = assert_picture(saved, 0)
        self.assertEqual(result['text'], 'DOCUMENT-B-TARGET')
        if MODE == 'browser':
            self.assertEqual(digest(replacement), before)
        self.checked('replacement-clean')

    def test_supported_find_replace_and_selected_format(self):
        self.blank()
        edit(self.page, 'PLAIN-HEAD FIND-OLD FIND-OLD FORMAT-MARKER')
        menu(self.page, 'edit:find-replace', category='edit')
        dialog = self.page.locator('.find-dialog')
        expect(dialog).to_be_visible()
        inputs = dialog.locator('.find-dialog-input')
        self.assertEqual(inputs.count(), 2)
        inputs.nth(0).fill('FIND-OLD'); inputs.nth(1).fill('FIND-NEW')
        dialog.get_by_role('button', name='모두 바꾸기', exact=True).click()
        dialog.locator('.dialog-close').click()
        text = inspect_hwpx(self.save())['text']
        self.assertEqual(text, 'PLAIN-HEAD FIND-NEW FIND-NEW FORMAT-MARKER'); self.checked('replace')
        self.undo()
        self.assertEqual(inspect_hwpx(self.save())['text'], 'PLAIN-HEAD FIND-OLD FIND-OLD FORMAT-MARKER'); self.checked('undo')
        self.redo()
        self.assertEqual(inspect_hwpx(self.save())['text'], 'PLAIN-HEAD FIND-NEW FIND-NEW FORMAT-MARKER'); self.checked('redo')
        self.area().focus()
        self.page.keyboard.press('Meta+ArrowDown' if primary_modifier(self.page) == 'Meta' else 'Control+End')
        for _ in 'FORMAT-MARKER':
            self.page.keyboard.press('Shift+ArrowLeft')
        self.page.locator('#btn-bold').click()
        self.page.locator('#font-size').fill('14')
        self.page.locator('#font-size').press('Enter')
        saved = self.save()
        assert_style(saved, 'FORMAT-MARKER', bold=True, height=1400); self.checked('selected-style')
        assert_style(saved, 'PLAIN-HEAD', bold=False, height=1000); self.checked('plain-style')
        self.open(saved)
        assert_style(self.save(), 'FORMAT-MARKER', bold=True, height=1400); self.checked('reopen')


class SupportedNativeTests(SupportedTests):
    def setUp(self):
        if self._testMethodName != 'test_supported_recent_owned_hosted_profile_restart_clear':
            return super().setUp()
        # Do not open a file (which records a recent entry) before the profile
        # and actual process guard. APPDATA/native identifier are untouched.
        self.folder = OUTPUT/self._testMethodName; self.folder.mkdir(parents=True, exist_ok=True)
        self.session = None; self.index = 1; self.document = None
        self.addCleanup(self.close)
        head = self.repository_head()
        # Literal guard before startup, with no environment values fabricated.
        literal = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Windows',
                   'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_RUN_ATTEMPT': '1'}
        if os.name != 'nt' or any(os.environ.get(k) != v for k, v in literal.items()) or os.environ.get('GITHUB_SHA') != head:
            raise AssertionError('Refusing recent-profile mutation outside the literal hosted Windows Source run')
        self.session = Session(MODE, self.folder/'session-1', None, executable=EXE, browser=BROWSER)
        self.page = self.session.page
        self.recent_guard()

    def repository_head(self):
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def recent_guard(self):
        process = verify_process(self.session.proc.pid, EXE, os.environ['E2E_ARCHITECTURE'], handle=int(self.session.proc._handle))
        hosted_recent_guard(os.environ, platform=os.name, repository_head=self.repository_head(), process=process)

    def recent_paths(self):
        self.recent_guard()
        started = len(self.session.dialogs)
        menu(self.page, 'file:open-recent')
        dialog = self.page.locator('.recent-documents-dialog')
        def observed():
            if dialog.is_visible():
                return 'list'
            if (self.page.locator('#sb-message').inner_text() == '최근 문서가 없습니다'
                    and any(row['type'] == 'alert' and row['message'] == '최근 문서가 없습니다.'
                            for row in self.session.dialogs[started:])):
                return 'empty'
            return False
        state = until(observed, pump=lambda n: self.page.wait_for_timeout(n*1000))
        if state == 'empty':
            self.assertEqual(dialog.count(), 0)
            return None, []
        paths = dialog.locator('.recent-documents-path').all_text_contents()
        # Every observed entry must belong to this run's owned fixtures/output.
        require_owned_recent_paths(paths, (OUTPUT, FIXTURES))
        return dialog, paths

    def clipboard_flow(self, *, keyboard):
        self.blank()
        marker = 'OWNED-CLIPBOARD-'+('KEYBOARD' if keyboard else 'MENU')+'-한글'
        edit(self.page, marker)
        self.area().focus(); self.session.native_keys('^a')
        def command(name, keys):
            if keyboard:
                self.session.native_keys(keys)
            else:
                menu(self.page, 'edit:'+name, category='edit')
        command('copy', '^c')
        until(lambda: self.session.os_clipboard_text() == marker)
        self.assertEqual(self.session.os_clipboard_text(), marker); self.checked('clipboard')
        self.area().focus(); self.session.native_keys('^{END}')
        self.page.keyboard.insert_text('|KEEP|')
        command('paste', '^v')
        self.assertEqual(inspect_hwpx(self.save())['text'], marker+'|KEEP|'+marker); self.checked('copy-paste')
        self.area().focus(); self.session.native_keys('^{HOME}')
        cut_text = marker+'|KEEP|'
        self.session.native_keys('+{RIGHT '+str(len(cut_text))+'}')
        # Cut a declared prefix while preserving the second copy. The clipboard
        # must change from the copied marker, so stale CF_UNICODETEXT cannot pass.
        command('cut', '^x')
        until(lambda: self.session.os_clipboard_text() == cut_text)
        self.assertEqual(self.session.os_clipboard_text(), cut_text)
        self.assertEqual(inspect_hwpx(self.save())['text'], marker); self.checked('cut')
        self.undo(); self.assertEqual(inspect_hwpx(self.save())['text'], marker+'|KEEP|'+marker); self.checked('undo')
        self.redo(); saved = self.save(); self.assertEqual(inspect_hwpx(saved)['text'], marker); self.checked('redo')
        self.open(saved); self.assertEqual(inspect_hwpx(self.save())['text'], marker); self.checked('reopen')

    def test_supported_keyboard_clipboard_copy_cut_paste(self):
        self.clipboard_flow(keyboard=True)

    def test_supported_menu_clipboard_copy_cut_paste(self):
        self.clipboard_flow(keyboard=False)

    def test_supported_installed_font_public_selection_roundtrip(self):
        source = self.blank()
        original = digest(source)
        marker = 'INSTALLED-FONT-MARKER'
        edit(self.page, marker)
        self.area().focus(); self.session.native_keys('^a')
        menu(self.page, 'format:char-shape', category='format')
        dialog = self.page.locator('.cs-dialog')
        expect(dialog).to_be_visible()
        select = dialog.locator('select').filter(has=self.page.locator('optgroup[label="로컬 글꼴"]'))
        self.assertEqual(select.count(), 1)
        # This group is populated by detected installed fonts, unlike the
        # document/current/base font menu which can contain missing names.
        self.assertEqual(select.locator('optgroup[label="로컬 글꼴"] option[value="Arial"]').count(), 1)
        # CharShapeDialog uses a real HTML select (the toolbar uses custom
        # selects). Open it physically and navigate its observed public choices;
        # select_option/dispatchEvent/programmatic property assignment are absent.
        values = select.locator('option').evaluate_all('(options) => options.map(o => o.value)')
        index = max(i for i, value in enumerate(values) if value == 'Arial')
        select.click(); self.page.keyboard.press('Home')
        for _ in range(index):
            self.page.keyboard.press('ArrowDown')
        self.page.keyboard.press('Enter')
        expect(select).to_have_value('Arial')
        dialog.locator('.dialog-btn-primary').click(); self.checked('installed-option')
        saved = self.folder/'font-roundtrip.hwpx'
        self.session.save(source, saved, save_as=True)
        assert_style(saved, marker, bold=False, font='Arial'); self.checked('selected-font')
        self.assertEqual(digest(source), original); self.checked('source-sha')
        self.open(saved); assert_style(self.save(), marker, bold=False, font='Arial'); self.checked('reopen')
        self.assertFalse([url for url in self.session.requests if url.split('?')[0].lower().endswith(('.ttf', '.otf', '.woff', '.woff2'))])

    def test_supported_gui_pdf_basic_hwp_hwpx_unsaved(self):
        for name, marker in (('basic.hwp', 'OpenGeul fixture'), ('basic.hwpx', 'OpenGeul fixture'), ('unicode.hwpx', '견적서 테스트')):
            source = self.folder/name; shutil.copy2(FIXTURES/name, source)
            original = digest(source); self.open(source)
            edit(self.page, ' GUI-PDF-END')
            target = self.folder/(name+'.pdf')
            status = self.session.export_pdf(target)
            self.assertTrue(status['saved'])
            inspection = inspect_gui_pdf(target, {'pages': [{'size_pt': A4, 'markers': [marker, 'GUI-PDF-END']}]}, self.folder/(name+'-pdf'))
            self.assertEqual(inspection['pages'], 1)
            self.assertEqual(digest(source), original)
            self.assertTrue(self.page.title().startswith('• '))
            self.checked(name)
            edit(self.page, ' AFTER-GUI-PDF')
            saved = self.folder/(name+'-after.hwpx')
            self.session.save(source, saved, save_as=True)
            self.assertEqual(inspect_hwpx(saved)['text'].count('AFTER-GUI-PDF'), 1)
        self.checked('next-save')

    def test_supported_gui_pdf_explicit_two_pages_table_image(self):
        owned = self.folder/'owned-gui-inputs'; owned.mkdir()
        source = text_fixture(FIXTURES/'blank.hwpx', owned/'two-pages.hwpx',
                              ['GUI-PAGE-ONE', 'GUI-PAGE-TWO'], page_breaks=(1,))
        original = digest(source); self.open(source)
        self.area().focus(); self.session.native_keys('^{HOME}')
        self.create_table()
        prepared = self.folder/'objects.hwpx'
        self.session.save(source, prepared, save_as=True)
        assert_table(prepared, 2)
        self.session.pick_image(checkerboard(owned/'owned-gui-pattern.png'))
        self.session.place_image()
        edit(self.page, ' GUI-PDF-END')
        expected = {'pages': [
            {'size_pt': A4, 'markers': ['GUI-PAGE-ONE', *CELL_MARKERS],
             'ink_pairs': [['CELL-01', 'CELL-11']]},
            {'size_pt': A4, 'markers': ['GUI-PAGE-TWO', 'GUI-PDF-END']},
        ]}
        before = digest(prepared)
        target = self.folder/'gui-two-pages-objects.pdf'
        self.session.export_pdf(target)
        result = inspect_gui_pdf(target, expected, self.folder/'gui-pdf-oracle', checkerboard_page=0)
        self.assertEqual(result['pages'], 2); self.checked('two-pages')
        self.assertEqual(len([m for m in result['checks'][0]['markers'] if m['text'] in CELL_MARKERS]), 4)
        self.assertEqual(len(result['checks'][0]['ink_pairs']), 1); self.checked('table')
        self.assertEqual(result['image_pattern']['squares'], 32); self.checked('image-pattern')
        self.assertEqual(digest(source), original); self.assertEqual(digest(prepared), before)
        self.assertTrue(self.page.title().startswith('• ')); self.checked('source-dirty')
        edit(self.page, ' AFTER-GUI-PDF')
        self.document = prepared
        saved = self.save(); assert_picture(saved, 1); assert_table(saved, 2)
        self.assertEqual(inspect_hwpx(saved)['text'].count('AFTER-GUI-PDF'), 1); self.checked('next-save')

    def test_supported_gui_pdf_cancel_preserves_target_and_dirty(self):
        original = digest(self.document)
        edit(self.page, ' GUI-PDF-CANCEL')
        target = self.folder/'existing-target.pdf'; target.write_bytes(b'OWNED-EXISTING-PDF-TARGET')
        before = digest(target)
        inventory = {p.name for p in self.folder.iterdir()}
        self.assertIsNone(self.session.export_pdf(target, cancel=True))
        self.assertEqual(digest(target), before); self.checked('target-preserved')
        self.assertEqual({p.name for p in self.folder.iterdir()}, inventory); self.checked('no-partial-output')
        self.assertEqual(digest(self.document), original); self.assertTrue(self.page.title().startswith('• ')); self.checked('source-dirty')
        edit(self.page, ' AFTER-PDF-CANCEL')
        self.assertIn('AFTER-PDF-CANCEL', inspect_hwpx(self.save())['text']); self.checked('next-save')

    def test_supported_recent_owned_hosted_profile_restart_clear(self):
        self.recent_guard(); self.checked('hosted-guard')
        dialog, _ = self.recent_paths()
        if dialog is not None:
            dialog.get_by_role('button', name='취소', exact=True).click()
        self.checked('owned-inventory')
        source = text_fixture(FIXTURES/'blank.hwpx', self.folder/'owned-recent.hwpx', ['OWNED-RECENT-MARKER'])
        original = digest(source)
        self.session.open_public(source); self.document = source
        saved = self.folder/'owned-recent-saved.hwpx'
        self.session.save(source, saved, save_as=True)
        old_pid = self.session.proc.pid
        self.close(); self.index += 1
        self.session = Session(MODE, self.folder/f'session-{self.index}', None, executable=EXE)
        self.page = self.session.page
        self.assertNotEqual(old_pid, self.session.proc.pid)
        dialog, paths = self.recent_paths()
        self.assertIn(str(saved), paths)
        item = dialog.locator('.recent-documents-item').filter(has=self.page.locator('.recent-documents-path', has_text=str(saved)))
        self.assertEqual(item.count(), 1); item.dblclick()
        self.session.wait_loaded(saved.name); self.document = saved
        self.assertEqual(inspect_hwpx(self.save())['text'], 'OWNED-RECENT-MARKER'); self.checked('restart-open')
        dialog, _ = self.recent_paths(); self.recent_guard()
        dialog.locator('.recent-documents-clear').click()
        expect(self.page.locator('.recent-documents-dialog')).to_have_count(0)
        self.assertEqual(digest(source), original); self.checked('clear')
        self.close(); self.index += 1
        self.session = Session(MODE, self.folder/f'session-{self.index}', None, executable=EXE)
        self.page = self.session.page
        dialog, paths = self.recent_paths(); self.assertEqual(paths, [])
        self.assertIsNone(dialog); self.checked('restart-empty')

    def test_supported_real_explorer_drop_and_invalid_recovery(self):
        folder = self.folder/'owned-explorer-fixtures'; folder.mkdir()
        source = text_fixture(FIXTURES/'blank.hwpx', folder/'owned-drop.hwpx', ['OWNED-DROP-MARKER'])
        invalid = folder/'owned-invalid.hwpx'; invalid.write_bytes(b'PK\x03\x04owned invalid drop')
        original = digest(source)
        drag = self.session.explorer_drop(source)
        self.assertTrue(drag['actualPhysicalDrag']); self.checked('owned-drag')
        self.session.wait_loaded(source.name); self.document = source
        # Save As keeps the drag input immutable and gives the invalid-drop
        # recovery a separate editable target.
        saved = self.folder/'drop-editable.hwpx'
        self.session.save(source, saved, save_as=True)
        self.assertEqual(inspect_hwpx(saved)['text'], 'OWNED-DROP-MARKER'); self.checked('drop-open')
        self.assertEqual(digest(source), original); self.checked('source-sha')
        self.document = saved
        before = digest(saved)
        self.session.explorer_drop(invalid)
        self.assertTrue(self.session.wait_open_failure())
        self.assertEqual(digest(saved), before); self.checked('invalid-drop')
        edit(self.page, ' AFTER-INVALID-DROP')
        self.assertEqual(inspect_hwpx(self.save())['text'], 'OWNED-DROP-MARKER AFTER-INVALID-DROP'); self.checked('next-save')
