import unittest
from playwright.sync_api import expect
from driver import edit, digest
from hwpx_oracle import inspect_hwpx
from test_editor import EditorTests, NativeTests, MODE

class FollowupTests:
    def test_plain_p_keyboard_input_and_saved_document(self):
        edit(self.page, ' KEYBOARD-BEGIN-')
        self.page.keyboard.press('p')
        self.page.keyboard.press('Shift+KeyP')
        self.page.keyboard.insert_text('-KEYBOARD-END ')
        target = self.save()
        marker = 'KEYBOARD-BEGIN-pP-KEYBOARD-END'
        self.assertEqual(inspect_hwpx(target)['text'].count(marker), 1)
        self.open(target)
        self.assertEqual(inspect_hwpx(self.save())['text'].count(marker), 1)

    def test_toolbar_label_preference_persists_without_changing_document(self):
        original = digest(self.document)
        toolbar = self.page.locator('#icon-toolbar')
        first_label = toolbar.locator('.tb-label').first
        expect(first_label).to_be_visible()
        old_height = toolbar.bounding_box()['height']
        self.page.locator('[data-menu="view"] > .menu-title').click()
        self.page.get_by_label('도구모음 글자 표시', exact=True).uncheck()
        expect(first_label).not_to_be_visible()
        button = toolbar.locator('button[title]').first
        self.assertTrue(button.get_attribute('aria-label'))
        self.assertLessEqual(toolbar.bounding_box()['height'], old_height)
        self.page.reload(wait_until='domcontentloaded')
        self.page.wait_for_function('document.querySelector("#opengeul-toolbar-labels") !== null')
        expect(self.page.locator('#icon-toolbar .tb-label').first).not_to_be_visible()
        self.page.locator('[data-menu="view"] > .menu-title').click()
        self.page.get_by_label('도구모음 글자 표시', exact=True).check()
        expect(self.page.locator('#icon-toolbar .tb-label').first).to_be_visible()
        self.assertEqual(digest(self.document), original)

def suite():
    base = NativeTests if MODE == 'native' else EditorTests
    combined = type('OpenGeulFollowups', (FollowupTests, base), {})
    return unittest.defaultTestLoader.loadTestsFromTestCase(combined)
