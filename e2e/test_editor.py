from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import zipfile
import xml.etree.ElementTree as ET
from playwright.sync_api import expect
from driver import Session, digest, edit, menu, until, primary_modifier
from hwpx_oracle import inspect_hwpx
from native_controls import dismiss_error_dialog

FIXTURES=Path(os.environ['E2E_FIXTURES']).resolve()
OUTPUT=Path(os.environ['E2E_OUTPUT']).resolve()
MODE=os.environ.get('E2E_MODE','browser')
EXE=Path(os.environ['E2E_EXE']).resolve() if MODE=='native' else None
BROWSER=os.environ.get('E2E_BROWSER','chromium')

class EditorTests(unittest.TestCase):
    def setUp(self):
        self.folder=OUTPUT/self._testMethodName
        self.folder.mkdir(parents=True,exist_ok=True)
        self.document=self.folder/'견적서 테스트.HWPX'
        shutil.copy2(FIXTURES/'basic.hwpx',self.document)
        self.session=None; self.index=0
        self.addCleanup(self.close)
        self.open(self.document)

    def close(self):
        if self.session:
            self.session.close(); self.session=None

    def open(self,path):
        self.close(); self.index+=1; self.document=path
        self.session=Session(MODE,self.folder/f'session-{self.index}',path,executable=EXE,browser=BROWSER,url=os.environ.get('E2E_URL','http://127.0.0.1:7700'))
        self.page=self.session.page

    def save(self):
        output=self.folder/f'saved-{self.index}.hwpx'
        result=self.session.save(self.document,output)
        self.assertIsNotNone(result)
        return result

    def test_production_startup_has_no_development_bridge(self):
        self.assertTrue(self.page.evaluate('typeof window.__wasm === "undefined" && typeof window.__inputHandler === "undefined"'))
        self.assertEqual(inspect_hwpx(self.document)['text'],'OpenGeul fixture 한글 가나다 & <xml> Ω 123')
        self.assertFalse(self.session.errors,self.session.errors)

    def test_edit_save_reopen_unicode_xml_and_emoji(self):
        marker=' E2E 한글 & <saved> Ω 😀 END'
        edit(self.page,marker)
        saved=self.save()
        text=inspect_hwpx(saved)['text']
        self.assertEqual(text.count(marker),1)
        self.open(saved)
        edit(self.page,' REOPENED')
        saved=self.save()
        self.assertIn(marker,inspect_hwpx(saved)['text'])
        self.assertIn('REOPENED',inspect_hwpx(saved)['text'])

    def test_three_roundtrips_preserve_all_edits_once(self):
        markers=[]
        for i in range(3):
            marker=f' ROUNDTRIP-{i}-가나다 '
            markers.append(marker);edit(self.page,marker)
            saved=self.save()
            text=inspect_hwpx(saved)['text']
            for expected in markers:self.assertEqual(text.count(expected),1)
            self.open(saved)

    def test_undo_redo_changes_the_saved_document(self):
        marker=' UNDO-REDO-MARKER '
        edit(self.page,marker)
        self.page.keyboard.press(primary_modifier(self.page)+'+z')
        saved=self.save()
        self.assertNotIn(marker,inspect_hwpx(saved)['text'])
        self.page.locator('textarea').first.focus()
        self.page.keyboard.press(primary_modifier(self.page)+'+Shift+z')
        saved=self.save()
        self.assertEqual(inspect_hwpx(saved)['text'].count(marker),1)

    def test_open_and_zoom_do_not_modify_the_source(self):
        original=digest(self.document)
        zoom=self.page.locator('#sb-zoom-val').inner_text()
        self.page.locator('#sb-zoom-in').click()
        expect(self.page.locator('#sb-zoom-val')).not_to_have_text(zoom)
        self.page.locator('#sb-zoom-out').click()
        self.assertEqual(digest(self.document),original)

    def test_font_help_is_explicit_and_never_auto_downloads_fonts(self):
        self.page.get_by_role('button',name='글꼴 도움말',exact=True).click()
        dialog=self.page.locator('dialog[open]')
        expect(dialog).to_contain_text('자동으로 설치하지 않습니다')
        expect(dialog).to_contain_text('공식')
        if MODE=='native':
            expect(dialog.locator('[role="status"]')).to_contain_text('Noto Sans KR:',timeout=15000)
        dialog.get_by_role('button',name='닫기',exact=True).click()
        self.assertFalse([url for url in self.session.requests if url.split('?')[0].lower().endswith(('.ttf','.otf','.woff','.woff2'))],self.session.requests)

    def test_paragraph_fixture_survives_edit_save(self):
        source=self.folder/'paragraphs.hwpx';shutil.copy2(FIXTURES/'paragraphs.hwpx',source)
        self.open(source);edit(self.page,' PARAGRAPHS-END ')
        result=inspect_hwpx(self.save())
        for i in range(12):self.assertIn(f'Row {i:02}',result['text'])
        self.assertIn('PARAGRAPHS-END',result['text'])

    def test_missing_font_does_not_prevent_text_roundtrip(self):
        source=self.folder/'missing-font.hwpx'
        with zipfile.ZipFile(FIXTURES/'missing-font.hwpx') as archive,zipfile.ZipFile(source,'w') as out:
            changed=0
            for entry in archive.infolist():
                value=archive.read(entry.filename)
                if entry.filename=='Contents/header.xml':
                    tree=ET.fromstring(value)
                    for element in tree.iter():
                        if element.tag.rsplit('}',1)[-1]=='font' and 'face' in element.attrib:
                            element.set('face','OpenGeul Deliberately Missing Font');changed+=1
                    value=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
                out.writestr(entry,value)
        self.assertGreater(changed,0)
        self.open(source);edit(self.page,' FALLBACK-END ')
        self.assertIn('FALLBACK-END',inspect_hwpx(self.save())['text'])

class NativeTests(EditorTests):
    def test_save_as_hwpx_from_hwp_is_a_real_zip_not_renamed_hwp(self):
        source=self.folder/'legacy.hwp';shutil.copy2(FIXTURES/'basic.hwp',source)
        original=digest(source);self.open(source);edit(self.page,' HWP-TO-HWPX ')
        target=self.folder/'새 형식.hwpx'
        result=self.session.save(source,target,save_as=True)
        self.assertIn('HWP-TO-HWPX',inspect_hwpx(result)['text'])
        self.assertEqual(digest(source),original)
        self.open(target)

    def test_save_as_hwp_and_reconvert_with_the_shipped_cli(self):
        edit(self.page,' HWPX-TO-HWP ')
        target=self.folder/'converted.hwp'
        self.session.save(self.document,target,save_as=True)
        self.assertTrue(target.read_bytes().startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'))
        converted=self.folder/'cli-roundtrip.hwpx'
        result=subprocess.run([str(EXE.parent/'Tools/rhwp.exe'),'export-hwpx',str(target),str(converted)],text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=90)
        (self.folder/'cli.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('HWPX-TO-HWP',inspect_hwpx(converted)['text'])
        self.open(target)

    def test_cancelled_native_save_as_preserves_original_and_dirty_state(self):
        original=digest(self.document);edit(self.page,' CANCELLED-CHANGE ')
        target=self.folder/'must-not-exist.hwpx'
        self.assertIsNone(self.session.save(self.document,target,save_as=True,cancel=True))
        self.assertFalse(target.exists());self.assertEqual(digest(self.document),original)
        self.assertTrue(self.page.title().startswith('• '))
        saved=self.save();self.assertIn('CANCELLED-CHANGE',inspect_hwpx(saved)['text'])

    def test_legacy_hwp_direct_save_still_works(self):
        source=self.folder/'legacy-save.hwp';shutil.copy2(FIXTURES/'basic.hwp',source)
        self.open(source);edit(self.page,' LEGACY-SAVE ')
        self.session.save(source,source)
        result=self.folder/'legacy-verify.hwpx'
        proc=subprocess.run([str(EXE.parent/'Tools/rhwp.exe'),'export-hwpx',str(source),str(result)],capture_output=True,timeout=90)
        self.assertEqual(proc.returncode,0,proc.stderr.decode('utf-8',errors='replace'))
        self.assertIn('LEGACY-SAVE',inspect_hwpx(result)['text'])

    def test_multiple_windows_use_real_native_creation(self):
        before=len(self.session.context.pages)
        self.page.locator('textarea').first.focus()
        with self.session.context.expect_page(timeout=30000) as event:
            self.page.keyboard.press('Control+Shift+n')
        expect(event.value.locator('#studio-root')).to_be_visible(timeout=30000)
        self.assertGreater(len(self.session.context.pages),before)
        self.assertFalse(self.page.is_closed())

    def test_corrupt_open_leaves_original_document_usable(self):
        original=digest(self.document)
        menu(self.page,'file:open')
        self.session.native_dialog(FIXTURES/'invalid.hwpx')
        message=dismiss_error_dialog(self.session.proc.pid)
        self.session.dialogs.append({'type':'native-error','message':message})
        expect(self.page.locator('#sb-message')).to_contain_text('파일 열기 실패')
        self.assertEqual(digest(self.document),original)
        edit(self.page,' AFTER-ERROR ')
        self.assertIn('AFTER-ERROR',inspect_hwpx(self.save())['text'])


def suite():
    return unittest.defaultTestLoader.loadTestsFromTestCase(NativeTests if MODE=='native' else EditorTests)
