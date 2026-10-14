"""Proposed native-only UI mixin. Not wired into the frozen product/test contract.

These methods must run on a new approved full Source SHA after integration/review.
This file is not a TestCase and must not produce a local simulated Windows PASS.
"""
from pathlib import Path
import json
import os

from native_clipboard import WindowsClipboardProvider,clipboard_payloads
from windows_ime import WindowsKeyboard


class NativeClipboardCases:
    def _native_input_receipt(self,name,payload):
        encoded=json.dumps(payload,ensure_ascii=False,indent=2).encode('utf-8')
        if len(encoded)>65536:raise AssertionError('Native clipboard receipt exceeds its byte bound')
        (self.folder/name).write_bytes(encoded)

    def _owned_keyboard(self):
        if os.name!='nt' or self.session.mode!='native':
            raise ValueError('Clipboard UI case requires actual Windows native product')
        from native_document_windows import OwnedDocumentWindows
        import driver
        owner=OwnedDocumentWindows(self.session);self.addCleanup(owner.close)
        current=owner.first()  # One held, physical focus click, never DOM focus.
        source_root=Path(driver.__file__).resolve().parents[1]
        keyboard=WindowsKeyboard(current.hwnd,self.session.proc.pid,int(self.session.proc._handle),
                                 owner.runtime,source_root,owner_scope=current)
        return keyboard,current,owner

    def _clipboard_save_as(self,name,current):
        from driver import menu,until
        from native_document_policy import double_checked_action
        from playwright.sync_api import expect
        target=self.folder/name
        self.assertFalse(target.exists(),'Clipboard Save As target must be fresh')
        # Save As must not activate the canvas, which would move selection/caret.
        double_checked_action(current._ready,lambda observed:menu(current.page,'file:save-as'))
        current.picker(target,purpose='save')
        expect(current.page.locator('#sb-message')).to_contain_text('저장 완료',timeout=30000)
        current.page.wait_for_function('!document.title.startsWith("• ")',timeout=30000)
        until(target.is_file);self.document=target
        return target

    def _external_case(self,kind,transport):
        from driver import digest,menu
        from test_editor import FIXTURES
        from supported_feature_oracle import text_fixture,inspect_supported_hwpx,assert_style,assert_checkerboard
        original=text_fixture(FIXTURES/'blank.hwpx',self.folder/f'{kind}-{transport}-input.hwpx',['SELECTED-ORIGINAL'])
        original_sha=digest(original);self.open(original)
        keyboard,current,owner=self._owned_keyboard()
        with keyboard:
            # Original input is fixture XML; actual selection and paste use OS input/menu.
            keyboard.send(['CTRL+a'])
            if kind=='html':
                payloads=clipboard_payloads(text='PLAIN-FALLBACK-DISALLOWED',html='<p><b>RICH-HTML-한글</b></p>')
            else:
                colors=((230,30,30),(30,30,230))
                pixels=bytes(value for y in range(16) for x in range(32) for value in (*colors[(x//4+y//4)%2],255))
                payloads=clipboard_payloads(bitmap=(32,16,pixels))
            source_root=Path(__import__('driver').__file__).resolve().parents[1]
            with WindowsClipboardProvider(payloads,source_root=source_root) as provider:
                before=provider.readback()
                self._native_input_receipt(f'{kind}-{transport}-before-os-clipboard.json',before)
                if transport=='menu':
                    from native_document_policy import double_checked_action
                    double_checked_action(current._ready,lambda observed:menu(current.page,'edit:paste',category='edit'))
                else:keyboard.send(['CTRL+v'])
                self._native_input_receipt(f'{kind}-{transport}-input-request.json',{
                    'beforeClipboard':before,'OSKeys':keyboard.entries,'transport':transport,'sourceQualified':False})
                # Initial document is clean. Dirty publication follows the actual
                # production paste mutation, including asynchronous image decode.
                self.page.wait_for_function('document.title.startsWith("• ")',timeout=30000)
                first=self._clipboard_save_as(f'{kind}-{transport}-after.hwpx',current)
                result=inspect_supported_hwpx(first)
                if kind=='html':
                    self.assertEqual(result['text'],'RICH-HTML-한글')
                    assert_style(first,'RICH-HTML-한글',bold=True)
                    self.assertEqual(result['pictures'],[]);self.assertEqual(result['tables'],[])
                else:
                    self.assertNotIn('SELECTED-ORIGINAL',result['text'])
                    self.assertEqual(len(result['pictures']),1);self.assertEqual(result['binary_parts'],1)
                    picture=result['pictures'][0]
                    self.assertEqual((picture['width_hu'],picture['height_hu']),(2400,1200))
                    assert_checkerboard(picture['data'])
                self.checked(transport+'-paste')
                current.prepare();keyboard.send(['CTRL+z'])
                restored=self._clipboard_save_as(f'{kind}-{transport}-undo.hwpx',current)
                restored_result=inspect_supported_hwpx(restored)
                self.assertEqual(restored_result['text'],'SELECTED-ORIGINAL')
                self.assertEqual(restored_result['pictures'],[]);self.assertEqual(restored_result['tables'],[])
                assert_style(restored,'SELECTED-ORIGINAL',bold=False,height=1000)
                self.checked(transport+'-single-undo')
                current.prepare();keyboard.send(['CTRL+SHIFT+z'])
                redone=self._clipboard_save_as(f'{kind}-{transport}-redo.hwpx',current)
                redo_result=inspect_supported_hwpx(redone)
                self.assertEqual(redo_result['text'],result['text'])
                if kind=='html':assert_style(redone,'RICH-HTML-한글',bold=True)
                else:
                    self.assertEqual(len(redo_result['pictures']),1)
                    self.assertEqual(redo_result['pictures'][0]['data'],result['pictures'][0]['data'])
                    self.assertEqual((redo_result['pictures'][0]['width_hu'],redo_result['pictures'][0]['height_hu']),(2400,1200))
                self.checked(transport+'-single-redo')
                after=provider.readback()
                evidence={'beforeClipboard':before,'afterClipboard':after,'OSKeys':keyboard.entries,
                          'kind':kind,'transport':transport,'sourceQualified':False}
                self._native_input_receipt(f'{kind}-{transport}-os-clipboard.json',evidence)
        self.assertEqual(digest(original),original_sha);self.checked(transport+'-source-sha')
        owner.close();self.open(redone)
        reopened_keyboard,reopened_current,reopened_owner=self._owned_keyboard()
        with reopened_keyboard:
            reopened=self._clipboard_save_as(f'{kind}-{transport}-reopened.hwpx',reopened_current)
        reopened_owner.close()
        reopened_result=inspect_supported_hwpx(reopened)
        self.assertEqual(reopened_result['text'],result['text'])
        if kind=='html':assert_style(reopened,'RICH-HTML-한글',bold=True)
        else:
            self.assertEqual(len(reopened_result['pictures']),1)
            assert_checkerboard(reopened_result['pictures'][0]['data'])
            self.assertEqual((reopened_result['pictures'][0]['width_hu'],reopened_result['pictures'][0]['height_hu']),(2400,1200))
        self.checked(transport+'-reopen')

    def test_supported_external_os_html_menu_keyboard_atomic_roundtrip(self):
        for transport in ('menu','keyboard'):
            with self.subTest(transport=transport):self._external_case('html',transport)

    def test_supported_external_os_bitmap_menu_keyboard_atomic_roundtrip(self):
        for transport in ('menu','keyboard'):
            with self.subTest(transport=transport):self._external_case('bitmap',transport)

    def probe_office_rtf_transport(self):
        """Produces actual transport evidence only; RTF support remains unqualified."""
        from driver import menu
        from supported_feature_oracle import checkerboard,inspect_supported_hwpx
        png=checkerboard(self.folder/'owned-rtf-checkerboard.png').read_bytes()
        nonexistent=self.folder/'clipboard-reference-must-not-exist.png'
        if nonexistent.exists():raise AssertionError('RTF probe image reference unexpectedly exists')
        html='<p>OFFICE-RTF-OWNED</p><img src="'+nonexistent.as_uri()+'" width="32" height="16">'
        payloads=clipboard_payloads(text='OFFICE-RTF-OWNED',html=html,rtf='{\\rtf1{\\pict\\pngblip '+png.hex()+'}}')
        keyboard,current,owner=self._owned_keyboard()
        with keyboard:
            source_root=Path(__import__('driver').__file__).resolve().parents[1]
            with WindowsClipboardProvider(payloads,source_root=source_root) as provider:
                os_data=provider.readback()
                public_support=self.page.evaluate('''()=>({
                    userAgent:navigator.userAgent,
                    clipboardReadAvailable:typeof navigator.clipboard?.read==='function',
                    rtfAdvertisedSupport:typeof ClipboardItem==='function'&&typeof ClipboardItem.supports==='function'?ClipboardItem.supports('text/rtf'):null
                })''')
                self._native_input_receipt('rtf-before-os-clipboard.json',{
                    'OSClipboard':os_data,'publicAPI':public_support,'sourceQualified':False,'supportProven':False})
                from native_document_policy import double_checked_action
                double_checked_action(current._ready,lambda observed:menu(current.page,'edit:paste',category='edit'))
                self.page.wait_for_function('document.title.startsWith("• ")',timeout=30000)
                saved=self._clipboard_save_as('rtf-probe-saved.hwpx',current)
                result=inspect_supported_hwpx(saved)
                actual={'text':result['text'],'pictures':len(result['pictures']),
                        'imagePayloadMatches':len(result['pictures'])==1 and result['pictures'][0]['data']==png}
                receipt={'OSClipboard':os_data,'publicAPI':public_support,'savedDocument':actual,
                         'sourceQualified':False,'supportProven':False,
                         'note':'No standalone text/rtf or delayed document-switch success is inferred.'}
                self._native_input_receipt('rtf-actual-transport.json',receipt)
                return receipt
