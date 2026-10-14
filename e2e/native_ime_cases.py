"""Concrete real Windows Korean IME UI case draft; not wired into frozen CI.

Uses native-document owner scope and real OS keys and installed IMM profile identity. No insert_text, VK_PACKET,
composition event dispatch, product hook or manually assigned textarea content.
Unknown Microsoft profile or unproved initial keyboard/body mode fails closed.
No external process HIMC is obtained or read; mode getters are not inferred.
"""
from __future__ import annotations
import json
from pathlib import Path

from windows_ime import (WindowsKeyboard,MicrosoftKoreanIme,CompositionObserver,
    require_korean_prerequisites,inspect_composition,inspect_cancelled_composition,
    inspect_live_composition,inspect_mode_probe)

IME_CHECKS=('actual-Microsoft-profile','physical-ascii-korean-switch','trusted-composition-commit',
            'selected-replacement','single-undo-redo','actual-os-cancel-preserves-body-selection-history',
            'save-as-real-reopen','source-sha')


class NativeImeCases:
    def _ime_receipt(self,name,value):
        data=json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')
        if len(data)>128*1024:raise AssertionError('Actual IME receipt exceeds its byte bound')
        (self.folder/name).write_bytes(data)

    def _ime_owner(self):
        from native_document_windows import OwnedDocumentWindows
        owner=OwnedDocumentWindows(self.session)
        self.addCleanup(owner.close)
        return owner,owner.first()

    def _ime_keyboard(self,owner,current):
        import driver
        root=Path(driver.__file__).resolve().parents[1]
        return WindowsKeyboard(current.hwnd,self.session.proc.pid,int(self.session.proc._handle),
                               owner.runtime,root,owner_scope=current)

    def _ime_body(self,path,expected,label):
        from native_document_policy import assert_body_markers
        from driver import digest
        inspection=assert_body_markers(path,[expected],[],exact_text=expected)
        self._ime_receipt(label+'-body.json',{'expected':expected,'actual':inspection['bodyText'],
            'bodyParagraphs':inspection['bodyParagraphs'],'sha256':digest(path),'sourceQualified':False})
        return inspection

    def _ime_save_as(self,current,name):
        from driver import until,menu
        from native_document_policy import double_checked_action
        from playwright.sync_api import expect
        target=self.folder/name
        self.assertFalse(target.exists(),'IME Save As oracle target must be fresh')
        # Do not use current.menu/prepare: their canvas activation click moves
        # the caret. Hold the page/HWND through two read-only observations, then
        # click the actual public menu, preserving the just-restored selection.
        double_checked_action(current._ready,lambda observed:menu(current.page,'file:save-as'))
        current.picker(target,purpose='save')
        expect(current.page.locator('#sb-message')).to_contain_text('저장 완료',timeout=30000)
        current.page.wait_for_function('!document.title.startsWith("• ")',timeout=30000)
        until(target.is_file)
        self.document=target
        return target

    def _ime_set_mode_by_key(self,ime,wanted,current):
        # Initial state was proved using physical gks+RIGHT, trusted events and
        # independent saved-body XML. This is only the last requested state:
        # each following real composition / exact saved ASCII body proves the
        # effect. Never label SendInput delivery itself as a mode success.
        if type(getattr(ime,'last_requested_native',None)) is not bool:
            raise AssertionError('Actual initial keyboard mode has not been proved')
        if ime.last_requested_native is not wanted:
            ime.toggle_mode();ime.last_requested_native=wanted
            current.page.wait_for_timeout(100)
        return {'requestedNative':wanted,'resultVerifiedByFollowingCase':False}

    def _ime_configure(self,keyboard,ime,current,label,*,restore=None):
        from driver import until
        from native_document_policy import assert_body_markers
        prerequisites=keyboard.prerequisites()
        self._ime_receipt(label+'-prerequisites.json',prerequisites)
        require_korean_prerequisites(prerequisites)
        chosen=ime.select_installed_profile()
        self._ime_receipt(label+'-chosen-profile.json',chosen)
        until(lambda: keyboard.ready(language=0x0412),timeout=10,
              pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
        active=ime.active_profile()
        self._ime_receipt(label+'-actual-profile.json',active)
        # Real mode probe is confined to a fresh scratch document. Both accepted
        # results have exact persisted XML and trusted actual OS input receipts.
        # Event absence, undocumented getter 0, and layout alone are insufficient.
        current.menu('file:new-doc');current.wait_loaded('새 문서.hwp');current.prepare()
        held_focus=keyboard.ready(language=0x0412)
        observer=CompositionObserver(current.page,keyboard)
        try:
            keyboard.send(list('gks'),language=0x0412)
            current.page.wait_for_timeout(100)
            keyboard.send(['RIGHT'],language=0x0412)
            current.page.wait_for_timeout(100)
            probe_path=self._ime_save_as(current,label+'-actual-mode-probe.hwpx')
            body=None
            for expected in ('한','gks'):
                try:
                    inspection=assert_body_markers(probe_path,[expected],[],exact_text=expected)
                    body=inspection['bodyText'];break
                except AssertionError:pass
            if body is None:raise AssertionError('Saved physical keyboard mode probe is neither exact Korean nor ASCII')
            observed=inspect_mode_probe(observer.read(),body)
            self._ime_receipt(label+'-actual-mode-probe.json',{
                'probe':observed,'events':observer.read(),'OSKeys':keyboard.entries,
                'profile':active,'sourceQualified':False})
        finally:observer.close()
        if restore is None:
            current.menu('file:new-doc');current.wait_loaded('새 문서.hwp')
        else:current.open(restore)
        current.prepare()
        after=keyboard.ready(language=0x0412)
        # Actual document replacement must preserve the held input HWND/thread/
        # layout and app ancestry used for the real initial-mode observation.
        if after!=held_focus:raise AssertionError('Held keyboard target changed after scratch probe/document load')
        after_profile=ime.active_profile()
        if after_profile['profile']!=active['profile']:
            raise AssertionError('Actual Microsoft profile changed after scratch probe/document load')
        ime.last_requested_native=observed['native']
        return active

    def _ime_selection(self,page):
        # Public renderer rectangles are read only. They prove selection survived
        # cancellation before Save As/menu activation can move the caret.
        rows=page.evaluate('''()=>Array.from(document.querySelectorAll('.selection-layer .selection-highlight'))
          .filter(node=>getComputedStyle(node).display!=='none')
          .map(node=>({left:node.style.left,top:node.style.top,width:node.style.width,height:node.style.height}))''')
        if not isinstance(rows,list) or not 1<=len(rows)<=64:
            raise AssertionError('Actual selected body range has no bounded public selection rectangles')
        return rows

    def test_supported_real_windows_korean_ime_commit_cancel_replace_roundtrip(self):
        from driver import digest,until
        original=self.document;original_sha=digest(original)
        owner,current=self._ime_owner()
        current.menu('file:new-doc');current.wait_loaded('새 문서.hwp');current.prepare()
        committed='ASCII BASE 한글 ENG'
        first_path=None
        with self._ime_keyboard(owner,current) as keyboard:
            ime=MicrosoftKoreanIme(keyboard)
            self._ime_configure(keyboard,ime,current,'new-body')
            self.checked('actual-Microsoft-profile')
            self._ime_set_mode_by_key(ime,False,current)
            keyboard.send(['A','S','C','I','I','SPACE','B','A','S','E','SPACE'],language=0x0412)
            self._ime_set_mode_by_key(ime,True,current)
            observer=CompositionObserver(current.page,keyboard)
            try:
                keyboard.send(list('gksrmf'),language=0x0412)
                until(lambda: inspect_live_composition(observer.read(),'한글'),timeout=10,
                      pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                # A real OS navigation key asks the installed IME to commit.
                keyboard.send(['RIGHT'],language=0x0412)
                events=until(lambda: inspect_composition(observer.read(),'한글'),timeout=10,
                             pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                self._ime_receipt('actual-gksrmf-commit.json',{
                    'source':keyboard.binding,'inspection':events,'events':observer.read(),
                    'OSKeys':keyboard.entries,'IME':ime.records,'sourceQualified':False})
            finally:observer.close()
            self.checked('trusted-composition-commit')
            self._ime_set_mode_by_key(ime,False,current)
            keyboard.send(['SPACE','E','N','G'],language=0x0412)
            first_path=self._ime_save_as(current,'ime-committed.hwpx')
            self._ime_body(first_path,committed,'ime-committed')
            self.checked('physical-ascii-korean-switch')
            self.assertEqual(digest(original),original_sha)
        owner.close()

        # Fresh actual app reopen, not a WASM-only parse. Re-attest its input
        # thread/profile before any keys. Existing source bytes stay immutable.
        first_sha=digest(first_path);self.open(first_path)
        owner,current=self._ime_owner()
        with self._ime_keyboard(owner,current) as keyboard:
            ime=MicrosoftKoreanIme(keyboard)
            self._ime_configure(keyboard,ime,current,'reopened-body',restore=first_path)
            self._ime_set_mode_by_key(ime,True,current)
            keyboard.send(['CTRL+a'],language=0x0412)
            selected_before=self._ime_selection(current.page)
            observer=CompositionObserver(current.page,keyboard)
            try:
                # One syllable forms one actual composition transaction, unlike
                # assuming the two-syllable word always has one Undo boundary.
                keyboard.send(list('gks'),language=0x0412)
                until(lambda: inspect_live_composition(observer.read(),'한'),timeout=10,
                      pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                keyboard.send(['RIGHT'],language=0x0412)
                receipt=until(lambda: inspect_composition(observer.read(),'한'),timeout=10,
                              pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                self.assertEqual(receipt['compositions'],1)
                self._ime_receipt('actual-selected-ime-commit.json',{
                    'selectionBefore':selected_before,'events':observer.read(),'inspection':receipt,
                    'OSKeys':keyboard.entries,'IME':ime.records,'sourceQualified':False})
            finally:observer.close()
            replaced=self._ime_save_as(current,'ime-replacement.hwpx')
            self._ime_body(replaced,'한','ime-replacement');self.checked('selected-replacement')
            current.prepare();keyboard.send(['CTRL+z'],language=0x0412)
            restored=self._ime_save_as(current,'ime-replacement-undo.hwpx')
            self._ime_body(restored,committed,'ime-replacement-undo')
            current.prepare();keyboard.send(['CTRL+SHIFT+z'],language=0x0412)
            redone=self._ime_save_as(current,'ime-replacement-redo.hwpx')
            self._ime_body(redone,'한','ime-replacement-redo');self.checked('single-undo-redo')

            current.prepare();self._ime_set_mode_by_key(ime,True,current)
            keyboard.send(['CTRL+a'],language=0x0412)
            cancel_selection=self._ime_selection(current.page)
            observer=CompositionObserver(current.page,keyboard)
            try:
                keyboard.send(list('rk'),language=0x0412)
                until(lambda: inspect_live_composition(observer.read(),'가'),timeout=10,
                      pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                # Real OS Escape is tested rather than assuming it cancels.
                # A profile which commits on Escape fails the strict empty-end
                # and independent selection/body/history oracle below.
                keyboard.send(['ESCAPE'],language=0x0412)
                cancelled=until(lambda: inspect_cancelled_composition(observer.read()),timeout=10,
                                pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                until(lambda: self._ime_selection(current.page)==cancel_selection,timeout=10,
                      pump=lambda seconds:current.page.wait_for_timeout(seconds*1000))
                self._ime_receipt('actual-ime-cancel.json',{
                    'inspection':cancelled,'selectionBefore':cancel_selection,'selectionAfter':self._ime_selection(current.page),
                    'events':observer.read(),'OSKeys':keyboard.entries,'IME':ime.records,'sourceQualified':False})
            finally:observer.close()
            cancelled_path=self._ime_save_as(current,'ime-cancelled.hwpx')
            self._ime_body(cancelled_path,'한','ime-cancelled')
            # An added cancel/no-op history entry would make this Undo restore
            # only the same syllable instead of the full original selected body.
            current.prepare();keyboard.send(['CTRL+z'],language=0x0412)
            after_cancel_undo=self._ime_save_as(current,'ime-cancel-history-undo.hwpx')
            self._ime_body(after_cancel_undo,committed,'ime-cancel-history-undo')
            current.prepare();keyboard.send(['CTRL+SHIFT+z'],language=0x0412)
            after_cancel_redo=self._ime_save_as(current,'ime-cancel-history-redo.hwpx')
            self._ime_body(after_cancel_redo,'한','ime-cancel-history-redo')
            self.checked('actual-os-cancel-preserves-body-selection-history')
            self.assertEqual(digest(first_path),first_sha)
            self.assertEqual(digest(original),original_sha)
        owner.close()

        self.open(after_cancel_redo)
        owner,current=self._ime_owner()
        with self._ime_keyboard(owner,current) as keyboard:
            ime=MicrosoftKoreanIme(keyboard)
            self._ime_configure(keyboard,ime,current,'final-reopen',restore=after_cancel_redo)
            self._ime_set_mode_by_key(ime,False,current)
            keyboard.send(['CTRL+END','SPACE','R','E','O','P','E','N'],language=0x0412)
            final=self._ime_save_as(current,'ime-final-reopened.hwpx')
            self._ime_body(final,'한 REOPEN','ime-final-reopened')
            self._ime_receipt('actual-ime-final-os-state.json',{'OSKeys':keyboard.entries,'IME':ime.records,'sourceQualified':False})
        self.checked('save-as-real-reopen')
        self.assertEqual(digest(original),original_sha);self.assertEqual(digest(first_path),first_sha)
        self.checked('source-sha')
