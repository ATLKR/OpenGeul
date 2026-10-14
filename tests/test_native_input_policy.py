from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
"""Offline helper policy/encoding tests, never an OS or product success receipt."""
import copy
import struct
import unittest
import native_clipboard as clip
import windows_ime as ime

HEAD = '08b7fdc408fbd73fd68c39e990a6531fbf3748a2'
ENV = {'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
       'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'38515988373',
       'GITHUB_SHA':HEAD,'GITHUB_JOB':'native-e2e'}
FOCUS = {'foreground':101,'root':101,'focus':102,'focusRoot':101,'rootPid':10,
         'focusPid':11,'focusTid':12,'focusClass':'Chrome_RenderWidgetHostHWND',
         'rootClass':'Tauri Window','visible':True,'enabled':True,'layout':0xe0010412,
         'session':2,'desktop':'Default','guiFlags':0,'menuOwner':0}
PROCESSES = {10:{'pid':10,'creation':100,'session':2},11:{'pid':11,'creation':101,'session':2}}

class EncodingTests(unittest.TestCase):
    def test_cf_html_offsets_are_utf8_bytes_with_korean_and_emoji(self):
        fragment='<p><b>한글😀 RICH</b></p>'
        data=clip.cf_html(fragment)
        self.assertIn(fragment.encode(), data)
        parsed=clip.inspect_cf_html(data)
        self.assertEqual(parsed['fragment'],fragment)
        self.assertGreater(parsed['endFragment']-parsed['startFragment'],len(fragment))

    def test_cf_html_rejects_character_offsets_and_outside_fragment(self):
        data=clip.cf_html('<p>한글😀</p>')
        self.assertIn(b'StartFragment:',data)
        for key in (b'StartFragment:',b'EndFragment:',b'EndHTML:'):
            start=data.index(key)+len(key)
            bad=data[:start]+b'9999999999'+data[start+10:]
            with self.subTest(key=key),self.assertRaises(ValueError):clip.inspect_cf_html(bad)

    def test_cf_html_rejects_nul_and_oversize_before_os_write(self):
        for value in ('A\x00B','X'*(4*1024*1024)):
            with self.subTest(length=len(value)),self.assertRaises(ValueError):clip.cf_html(value)

    def test_dib_v5_top_down_bgra_pixels_and_masks_are_exact(self):
        data=clip.dib_v5(2,2,bytes([230,30,30,255,30,30,230,255]*2))
        self.assertEqual(len(data),124+16)
        self.assertEqual(struct.unpack_from('<IiiHHI',data),(124,2,-2,1,32,3))
        self.assertEqual(struct.unpack_from('<IIII',data,40),(0xff0000,0xff00,0xff,0xff000000))
        self.assertEqual(data[124:],bytes([30,30,230,255,230,30,30,255]*2))

    def test_dib_rejects_bad_dimensions_and_short_pixels(self):
        for width,height,pixels in ((0,1,b''),(1,-1,b''),(4097,1,b''),(2,2,b'\0'*15),(True,1,b'\0'*4)):
            with self.subTest(width=width,height=height),self.assertRaises(ValueError):clip.dib_v5(width,height,pixels)

    def test_unicode_text_is_terminated_utf16le(self):
        self.assertEqual(clip.unicode_text('한😀'),'한😀\0'.encode('utf-16le'))
        with self.assertRaises(ValueError):clip.unicode_text('A\0B')

    def test_office_rtf_does_not_synthesize_a_standard_bitmap(self):
        payloads=clip.clipboard_payloads(text='OFFICE',html='<p>OFFICE</p>',rtf='{\\rtf1 data}')
        self.assertEqual(set(payloads),{'CF_UNICODETEXT','HTML Format','Rich Text Format'})

    def test_payload_bounds_and_empty_clipboard_are_explicit(self):
        self.assertEqual(clip.clipboard_payloads(),{})
        for kwargs in ({'png':b'not a png'},{'rtf':'not rtf'},{'rtf':'{\\rtf1\0}'},{'text':'X'*(3*1024*1024)}):
            with self.subTest(keys=list(kwargs)),self.assertRaises(ValueError):clip.clipboard_payloads(**kwargs)

class GuardTests(unittest.TestCase):
    def test_native_menu_mode_blocks_keys_even_when_focus_window_is_unchanged(self):
        self.assertTrue(hasattr(ime,'require_gui_idle'),'Native menu-mode guard is missing')
        self.assertEqual(ime.require_gui_idle(1,0),{'guiFlags':1,'menuOwner':0})
        for flags,owner in ((4,0),(8,0),(16,0),(28,0),(0,101),(True,0),(0,True)):
            with self.subTest(flags=flags,owner=owner),self.assertRaises(AssertionError):ime.require_gui_idle(flags,owner)
        for flags,owner in ((4,0),(8,0),(16,0),(0,101)):
            row={**FOCUS,'guiFlags':flags,'menuOwner':owner}
            with self.subTest(flags=flags,owner=owner),self.assertRaises(AssertionError):ime.require_focus(row,row,PROCESSES)

    def test_actual_binding_requires_exact_repo_run_attempt_and_head(self):
        result=ime.validate_hosted_binding(ENV,HEAD,platform='nt')
        self.assertIsInstance(result,dict)
        self.assertEqual(result.get('sourceRun'),ENV['GITHUB_RUN_ID'])
        for key,value in [('GITHUB_ACTIONS','false'),('RUNNER_ENVIRONMENT','self-hosted'),('GITHUB_REPOSITORY','other/repo'),
                          ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_SHA','1'*40),('GITHUB_RUN_ID','1x'),('GITHUB_JOB','other')]:
            bad={**ENV,key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):ime.validate_hosted_binding(bad,HEAD,platform='nt')
        with self.assertRaises(ValueError):ime.validate_hosted_binding(ENV,HEAD,platform='posix')

    def test_two_focus_observations_bind_real_input_thread_and_layout(self):
        result=ime.require_focus(FOCUS,copy.deepcopy(FOCUS),PROCESSES,language=0x0412)
        self.assertIsInstance(result,dict)
        self.assertEqual(result['focusTid'],12)
        self.assertEqual(result['layout']&0xffff,0x0412)

    def test_focus_change_pid_reuse_and_foreground_loss_block_input(self):
        for key,value in [('foreground',333),('focus',103),('focusPid',99),('focusTid',13),('layout',0x409),
                          ('session',3),('desktop','Winlogon'),('visible',False),('enabled',False)]:
            bad={**FOCUS,key:value}
            with self.subTest(key=key),self.assertRaises(AssertionError):ime.require_focus(FOCUS,bad,PROCESSES,language=0x412)
        with self.assertRaises(AssertionError):ime.require_focus(FOCUS,FOCUS,{10:PROCESSES[10]},language=0x412)

    def test_scan_codes_are_bounded_and_never_unicode_packet(self):
        sequence=ime.scancode_sequence(['g','k','s','SPACE','HANGUL','ESCAPE'])
        self.assertEqual(len(sequence),12)
        self.assertTrue(all(row['unicode'] is False for row in sequence))
        self.assertEqual(sequence[0]['scan'],0x22)
        self.assertEqual(sequence[1]['up'],True)
        for keys in (['한글'],['UNKNOWN'],['g']*513):
            with self.subTest(keys=str(keys)[:40]),self.assertRaises(ValueError):ime.scancode_sequence(keys)

    def test_chord_uppercase_name_does_not_add_a_second_shift_modifier(self):
        self.assertEqual(ime.scancode_sequence(['CTRL+SHIFT+Z']),ime.scancode_sequence(['CTRL+SHIFT+z']))
        self.assertEqual(ime.scancode_sequence(['CTRL+A']),ime.scancode_sequence(['CTRL+a']))

    def test_composition_receipt_requires_trusted_actual_start_update_end(self):
        events=[{'type':'compositionstart','isTrusted':True,'data':''},
                {'type':'compositionupdate','isTrusted':True,'data':'ㅎ'},
                {'type':'compositionupdate','isTrusted':True,'data':'한'},
                {'type':'compositionend','isTrusted':True,'data':'한'}]
        self.assertEqual(ime.inspect_composition(events,'한').get('committed'),'한')
        for bad in (events[1:],events[:-1],[{**row,'isTrusted':False} for row in events],events+[events[-1]]):
            with self.subTest(rows=len(bad)),self.assertRaises(AssertionError):ime.inspect_composition(bad,'한')

    def test_clipboard_cleanup_requires_unchanged_owner_and_sequence(self):
        before={'hwnd':101,'pid':10,'creation':100,'session':2,'sequence':30}
        self.assertEqual(clip.validate_owner(before,copy.deepcopy(before)),before)
        for key,value in [('hwnd',102),('pid',11),('creation',101),('session',3),('sequence',31)]:
            with self.subTest(key=key),self.assertRaises(AssertionError):clip.validate_owner(before,{**before,key:value})

class RuntimeContractTests(unittest.TestCase):
    def test_foreign_or_unknown_delayed_request_cannot_claim_owned_app_read(self):
        api=FakeClipboardApi();api.requester=lambda:{'hwnd':303,'pid':99,'tid':777,'identityObserved':True}
        core=clip.ClipboardCore(api,101)
        core.publish({'HTML Format':clip.cf_html('<b>RICH</b>')},delayed=('HTML Format',))
        core.released.set();core.render(core.format_ids['HTML Format'],timeout=.1)
        row=core.requests[0]
        self.assertEqual(row.get('requester'),{'hwnd':303,'pid':99,'tid':777,'identityObserved':True})
        self.assertIs(row.get('requesterQualified'),False)

    def test_render_all_checks_owner_again_after_open_and_never_marks_paste_completed(self):
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        self.assertTrue(hasattr(core,'render_all'),'WM_RENDERALLFORMATS lifecycle is missing')
        core.publish({'HTML Format':clip.cf_html('<b>RICH</b>')},delayed=('HTML Format',))
        api.on_open=lambda:setattr(api,'owner',102)
        self.assertFalse(core.render_all())
        self.assertEqual(core.requests,[])
        self.assertEqual(core.rendered,set())

    def test_delayed_render_uses_actual_request_signal_and_never_opens_clipboard(self):
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        core.publish({'HTML Format':clip.cf_html('<b>RICH</b>')},delayed=('HTML Format',))
        opens=api.opens;core.released.set();core.render(core.format_ids['HTML Format'],timeout=.1)
        self.assertTrue(core.requested.is_set())
        self.assertEqual(api.opens,opens)
        self.assertEqual(len(core.requests),1)
        self.assertTrue(core.requests[0]['completed'])
        self.assertEqual(core.readback()['readbackMatched'],True)

    def test_delayed_render_timeout_cannot_be_normalized_as_completion(self):
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        core.publish({'HTML Format':clip.cf_html('<b>RICH</b>')},delayed=('HTML Format',))
        with self.assertRaises(TimeoutError):core.render(core.format_ids['HTML Format'],timeout=.001)
        self.assertTrue(core.requested.is_set())
        self.assertFalse(core.requests[0]['completed'])
        self.assertFalse(core.rendered)
    def test_keyboard_runtime_refuses_non_windows_before_importing_native_tools(self):
        import os
        if os.name!='nt':
            self.assertTrue(hasattr(ime,'WindowsKeyboard'),'Real OS keyboard adapter is missing')
            with self.assertRaisesRegex(ValueError,'Windows'):ime.WindowsKeyboard(None,None,None,None,None)

    def test_clipboard_runtime_refuses_non_windows_before_any_mutation(self):
        import os
        if os.name!='nt':
            self.assertTrue(hasattr(clip,'WindowsClipboardProvider'),'Real OS clipboard adapter is missing')
            with self.assertRaisesRegex(ValueError,'Windows'):clip.WindowsClipboardProvider({},source_root='.')

    def test_core_frees_only_untransferred_handles_and_closes_on_set_failure(self):
        self.assertTrue(hasattr(clip,'ClipboardCore'),'Owner/memory core is missing')
        api=FakeClipboardApi(fail_set=2)
        core=clip.ClipboardCore(api,101)
        with self.assertRaisesRegex(OSError,'SetClipboardData'):
            core.publish({'CF_UNICODETEXT':clip.unicode_text('OWNED'),'HTML Format':clip.cf_html('<b>RICH</b>')})
        self.assertEqual(api.freed,[202])
        self.assertEqual(api.transferred,[201])
        self.assertFalse(api.opened)

    def test_core_does_not_clear_foreign_clipboard_during_cleanup(self):
        self.assertTrue(hasattr(clip,'ClipboardCore'),'Owner/memory core is missing')
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        core.publish({'CF_UNICODETEXT':clip.unicode_text('OWNED')})
        api.owner=102
        self.assertEqual(core.clear_if_owned(),False)
        self.assertEqual(api.empties,1)

    def test_core_readback_rejects_payload_change_and_checks_memory_bounds(self):
        self.assertTrue(hasattr(clip,'ClipboardCore'),'Owner/memory core is missing')
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        core.publish({'CF_UNICODETEXT':clip.unicode_text('OWNED')})
        self.assertEqual(core.readback()['formats'][0]['bytes'],12)
        api.memory[201]=clip.unicode_text('WRONG')
        with self.assertRaisesRegex(AssertionError,'payload'):core.readback()

    def test_unrendered_delayed_metadata_cannot_claim_actual_payload_readback(self):
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        core.publish({'HTML Format':clip.cf_html('<b>RICH</b>')},delayed=('HTML Format',))
        receipt=core.readback()
        self.assertTrue(receipt['metadataMatched'])
        self.assertFalse(receipt['readbackMatched'])
        self.assertFalse(receipt['formats'][0]['rendered'])

    def test_core_owner_change_between_open_and_empty_blocks_all_mutation(self):
        self.assertTrue(hasattr(clip,'ClipboardCore'),'Owner/memory core is missing')
        api=FakeClipboardApi();core=clip.ClipboardCore(api,101)
        core.publish({'CF_UNICODETEXT':clip.unicode_text('OWNED')})
        api.on_open=lambda:setattr(api,'owner',102)
        self.assertFalse(core.clear_if_owned())
        self.assertEqual(api.empties,1)
        self.assertFalse(api.opened)

class FakeClipboardApi:
    """OS boundary only; production core encodes/checks/owns the operation."""
    def __init__(self,fail_set=None):
        self.owner=0;self.sequence=10;self.opened=False;self.empties=0;self.next_handle=200
        self.memory={};self.formats={};self.freed=[];self.transferred=[];self.fail_set=fail_set;self.on_open=None;self.opens=0
    def identity(self,hwnd):return {'hwnd':hwnd,'pid':10,'creation':100,'session':2}
    def owner_record(self,hwnd):return {**self.identity(self.owner),'sequence':self.sequence}
    def open(self,hwnd):
        self.opened=True;self.opens+=1
        if self.on_open:self.on_open()
    def close(self):self.opened=False
    def empty(self):self.empties+=1;self.owner=101;self.sequence+=1;self.formats={}
    def format_id(self,name):return {'CF_UNICODETEXT':13,'HTML Format':49301}.get(name,49302)
    def alloc(self,data):self.next_handle+=1;self.memory[self.next_handle]=data;return self.next_handle
    def free(self,handle):self.freed.append(handle);self.memory.pop(handle,None)
    def set(self,fmt,handle):
        if self.fail_set and len(self.transferred)+1==self.fail_set:raise OSError('SetClipboardData failed')
        self.formats[fmt]=handle;self.transferred.append(handle);self.sequence+=1
    def enumerate_formats(self):return list(self.formats)
    def read(self,fmt,length):return self.memory[self.formats[fmt]][:length]

if __name__=='__main__':unittest.main(verbosity=2)
