"""Evidence-policy tests for the Windows lifecycle acceptance harness."""
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from editor_program_boundary import editor_program_factory
import xml.etree.ElementTree as ET
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'lifecycle_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_lifecycle_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class LifecycleSmokeTests(unittest.TestCase):
    def test_lifecycle_observes_shared_focus_readiness_once_before_navigation_and_marker_input(self):
        case = object.__new__(smoke.Case)
        case.record = {'attachments': [{'hwnd': 11, 'parent': 12, 'child': 22, 'officePid': 88}]}
        case.process = SimpleNamespace(pid=77)
        case.prepared_library={'kind':'test-only-prepared'}
        # This test isolates the unchanged focus/input protocol. Real completion
        # and stale-title rejection are exercised by test_writer_model_barrier.
        completion = SimpleNamespace(begin=Mock(return_value=object()), complete=Mock(), abort=Mock())
        case._writer_model_context = lambda hwnd, child: completion
        case.api = SimpleNamespace(require_foreground=lambda hwnd: None, require_editor_focus=lambda hwnd, child: 22,
                                   title=lambda hwnd: '* OpenGeul Writer', pid=lambda hwnd: 999)
        window = SimpleNamespace(set_focus=Mock(), click_input=Mock())
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: window))
        observed = []
        def keyboard(keys, **options):
            if keys == '^{END}': self.assertIn('ready', observed, 'Navigation must follow actual focus readiness')
            observed.append(keys)
        def prepare(api, hwnd, child, shell_pid, office_pid, record, click_editor, enter_document, **options):
            self.assertEqual((hwnd, child, shell_pid, office_pid), (11, 22, 77, 88))
            click_editor()
            enter_document()
            observed.append('ready')
            return 22
        readiness = Mock(side_effect=prepare)
        def inject(*args, **options):
            self.assertIn('ready', observed)
            observed.append('marker')
        ascii_input = Mock(side_effect=inject)
        with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop),
                                       'pywinauto.keyboard': SimpleNamespace(send_keys=keyboard)}), \
             patch.object(smoke.native, 'prepare_editor_focus', readiness), \
             patch.object(smoke.native, 'FirstAdmissionEditorSession', editor_program_factory(keyboard)), \
             patch.object(smoke.native, 'activate_owned_suite', side_effect=lambda api,process,hwnd,record:api.require_foreground(hwnd)), \
             patch.object(smoke.native, 'click_owned_editor', side_effect=lambda *args:window.click_input()) as clicked, \
             patch.object(smoke.native.ascii_input, 'type_ascii', ascii_input):
            case.edit(11, 22, '-LIFECYCLE-NEW-')
        readiness.assert_called_once()
        clicked.assert_called_once_with(case.api,case.process,11,12,22,88,case.record)
        window.click_input.assert_called_once()
        ascii_input.assert_called_once_with(case.api,11,22,'-LIFECYCLE-NEW-',case.record,pause=0.025,deadline=completion.deadline,original_popen=case.process,
            native_binding=dict(shellPid=77,officePid=88,suiteHwnd=11,parentHwnd=12,childHwnd=22),prepared_library=case.prepared_library)
        self.assertEqual(observed, ['^{F6}', 'ready', '^{END}', 'marker'])

    def test_lifecycle_rejects_missing_or_ambiguous_attachment_before_editor_input(self):
        attachment = {'hwnd':11, 'child':22, 'officePid':88}
        for attachments in ([], [attachment, attachment.copy()], [{**attachment,'child':999}]):
            with self.subTest(attachments=attachments):
                case = object.__new__(smoke.Case)
                case.record, case.process = {'attachments':attachments}, SimpleNamespace(pid=77)
                case.api = SimpleNamespace(require_foreground=lambda hwnd:None, require_editor_focus=lambda *args:22,
                                           title=lambda hwnd:'* OpenGeul Writer')
                window = SimpleNamespace(set_focus=Mock(), click_input=Mock())
                desktop = SimpleNamespace(window=lambda **kw:SimpleNamespace(wrapper_object=lambda:window))
                keyboard, ascii_input, readiness = Mock(), Mock(), Mock()
                with patch.dict('sys.modules', {'pywinauto':SimpleNamespace(Desktop=lambda **kw:desktop),
                                               'pywinauto.keyboard':SimpleNamespace(send_keys=keyboard)}), \
                     patch.object(smoke.native,'prepare_editor_focus',readiness), \
                     patch.object(smoke.native.ascii_input,'type_ascii',ascii_input):
                    with self.assertRaises(AssertionError): case.edit(11,22,'-LIFECYCLE-NEW-')
                window.click_input.assert_not_called()
                keyboard.assert_not_called()
                ascii_input.assert_not_called()
                readiness.assert_not_called()

    def picker_fixture(self, *, wrong_readback=False, readonly=False, method_error=None,
                       unicode_window=True, wrong_selection=False, missed_assignment=False, native_failure=None):
        calls = []
        focus = SimpleNamespace(hwnd=500,steal_after_assignment=False,native_override=None,native_override_after_assignment=False,
                                selection=(2,4), messages=[],unicode_window=unicode_window,style=0x50810080)
        class Value:
            CurrentIsReadOnly = readonly
            def __init__(self): self.text = '새 문서.odt'
            @property
            def CurrentValue(self):
                calls.append(('read',self.text))
                if method_error == 'read': raise RuntimeError('value read failed')
                return self.text
            def SetValue(self, text):
                raise AssertionError('ValuePattern.SetValue must not perform this native Edit transaction')
        value = Value()
        root_info = SimpleNamespace(handle=500, process_id=31, runtime_id=[42,500],
                                    name='OpenGeul Writer — 다른 이름으로 저장', control_type='Window')
        field_info = SimpleNamespace(handle=510, process_id=31, runtime_id=[42,510],
                                     name='File name:', control_type='Edit', automation_id='1001')
        accessible = SimpleNamespace(element_info=root_info)
        field = SimpleNamespace(element_info=field_info, iface_value=value,is_visible=lambda: True,is_enabled=lambda: True)
        api = SimpleNamespace(pid=lambda handle: 31,title=lambda handle: 'OpenGeul Writer — 다른 이름으로 저장',
                              class_name=lambda handle: '#32770' if handle==500 else 'Edit', require_foreground=lambda handle: None,
                              user=SimpleNamespace(IsWindow=lambda handle: True,GetWindow=lambda handle,relation: 100,
                                                   IsChild=lambda parent,child: parent==500 and child==510,
                                                   GetAncestor=lambda handle,relation: 500))
        def click_field():
            calls.append(('focus',510))
            focus.hwnd=510
        field.click_input=click_field
        def gui_info(thread,pointer):
            pointer._obj.hwndActive=500
            pointer._obj.hwndFocus=focus.hwnd
            pointer._obj.hwndCapture=0
            pointer._obj.hwndMenuOwner=0
            return 1
        def native_text(handle,message,capacity,buffer,flags,timeout,result):
            self.assertEqual((handle,flags,timeout),(510,3,1000))
            focus.messages.append(message)
            if native_failure == message: return 0
            if message==0xB0:
                self.assertEqual((capacity,buffer),(0,0))
                result._obj.value=focus.selection[0] | (focus.selection[1]<<16)
                return 1
            if message==0xB1:
                self.assertEqual((capacity,buffer),(0,-1))
                calls.append(('select',0,-1))
                if not wrong_selection: focus.selection=(0,len(value.text.encode('utf-16-le'))//2)
                result._obj.value=0
                return 1
            if message==0xC2:
                self.assertEqual(capacity,1,'EM_REPLACESEL must retain undo information')
                text=smoke.ctypes.wstring_at(buffer)
                calls.append(('assign',text))
                if method_error == 'assign': raise RuntimeError('native assignment failed')
                if not missed_assignment: value.text=text[:-1] if wrong_readback else text
                if focus.steal_after_assignment: focus.hwnd=999
                if focus.native_override_after_assignment: focus.native_override='stale native filename'
                result._obj.value=0
                return 1
            self.assertEqual(message,13)
            actual=value.text if focus.native_override is None else focus.native_override
            import ctypes
            source=ctypes.create_unicode_buffer(actual)
            self.assertLessEqual(len(actual.encode('utf-16-le'))//2+1,capacity)
            self.assertLessEqual(ctypes.sizeof(source),capacity*ctypes.sizeof(ctypes.c_wchar))
            ctypes.memmove(buffer,ctypes.addressof(source),ctypes.sizeof(source))
            result._obj.value=len(actual.encode('utf-16-le'))//2
            return 1
        api.user.GetGUIThreadInfo=gui_info
        api.user.GetWindowThreadProcessId=lambda handle,pointer:111
        api.user.GetForegroundWindow=lambda:500
        api.user.SendMessageTimeoutW=native_text
        api.user.IsWindowUnicode=lambda handle:focus.unicode_window
        api.user.GetWindowLongW=lambda handle,index:focus.style
        api.focus_state=focus
        return api,accessible,field,calls

    def test_picker_filename_uses_one_native_selection_replacement_and_exact_readback(self):
        api,root,field,calls = self.picker_fixture()
        record = {}
        expected = 'D:\\owned\\새 문서 저장 결과 & 한글.docx'
        smoke.set_owned_picker_filename(api,31,100,500,root,field,expected,record)
        evidence, = record['pickerFilenameInputs']
        self.assertEqual(calls,[('read','새 문서.odt'),('focus',510),('select',0,-1),('assign',expected),('read',expected)])
        self.assertTrue(evidence['success'])
        self.assertEqual((evidence['expected'],evidence['before'],evidence['after']), (expected,'새 문서.odt',expected))
        self.assertEqual(evidence['assignmentAttempts'],1)
        self.assertEqual(evidence['selectionSetAttempts'],1)
        self.assertEqual(evidence['method'],'Win32-Edit-EM_REPLACESEL')
        self.assertEqual(evidence['nativeEdit']['selectionBefore']['packedResult'],2|(4<<16))
        self.assertEqual(evidence['nativeEdit']['selectionAfterSelect']['start'],0)
        self.assertEqual(evidence['nativeEdit']['selectionAfterSelect']['end'],len('새 문서.odt'))
        self.assertEqual(evidence['nativeEdit']['replaceResult']['messageReturn'],0,
                         'A zero EM_REPLACESEL message return is normal; exact readback proves mutation')
        self.assertEqual(evidence['nativeEdit']['replacementUtf16LeHex'],expected.encode('utf-16-le').hex())
        self.assertEqual(api.focus_state.messages,[13,13,0xB0,0xB1,0xB0,0xC2,13])
        self.assertEqual(evidence['field']['runtimeId'],[42,510])
        self.assertEqual(evidence['dialogUia']['nativeHandle'],500)

    def test_picker_native_edit_rejects_nonunicode_wrong_selection_and_missing_assignment(self):
        for mode in ('non-unicode','wrong-selection','missed-assignment','truncated-readback'):
            with self.subTest(mode=mode):
                api,root,field,calls=self.picker_fixture(unicode_window=mode!='non-unicode',
                    wrong_selection=mode=='wrong-selection',missed_assignment=mode=='missed-assignment',
                    wrong_readback=mode=='truncated-readback')
                record={}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                receipt,=record['pickerFilenameInputs']
                self.assertFalse(receipt['success'])
                self.assertEqual(receipt['assignmentAttempts'],int(mode in ('missed-assignment','truncated-readback')))
                self.assertEqual(receipt['selectionSetAttempts'],int(mode!='non-unicode'))
                self.assertEqual(sum(c[0]=='assign' for c in calls),receipt['assignmentAttempts'])
                self.assertIn('error',receipt)

    def test_picker_native_edit_failure_retains_raw_result_and_never_retries(self):
        for message in (0xB0,0xB1,0xC2):
            with self.subTest(message=message):
                api,root,field,calls=self.picker_fixture(native_failure=message)
                record={}
                with self.assertRaises(OSError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                receipt,=record['pickerFilenameInputs']
                self.assertFalse(receipt['success'])
                self.assertEqual(api.focus_state.messages.count(message),1)
                key={0xB0:'selectionBefore',0xB1:'selectResult',0xC2:'replaceResult'}[message]
                self.assertEqual(receipt['nativeEdit'][key]['sendReturn'],0)
                self.assertIn('error',receipt)

    def test_picker_native_edit_rejects_nul_and_utf16_overflow_before_any_mutation(self):
        for target in ('D:\\owned\\bad\0name.docx','x'*4095,'😀'*2048):
            with self.subTest(target_length=len(target)):
                api,root,field,calls=self.picker_fixture()
                record={}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,target,record)
                receipt,=record['pickerFilenameInputs']
                self.assertEqual(receipt['selectionSetAttempts'],0)
                self.assertEqual(receipt['assignmentAttempts'],0)
                self.assertFalse(any(c[0] in ('select','assign') for c in calls))

    def test_picker_native_edit_uses_utf16_selection_lengths_and_retains_multiline_style_as_diagnostic(self):
        api,root,field,calls=self.picker_fixture()
        field.iface_value.text='가😀.odt'
        api.focus_state.style |= 4
        record={}
        target='D:\\owned\\한글 😀.docx'
        smoke.set_owned_picker_filename(api,31,100,500,root,field,target,record)
        receipt,=record['pickerFilenameInputs']
        self.assertTrue(receipt['success'])
        self.assertEqual(receipt['nativeEdit']['selectionAfterSelect']['end'],len('가😀.odt'.encode('utf-16-le'))//2)
        self.assertEqual(receipt['nativeEdit']['replacementUtf16Units'],len(target.encode('utf-16-le'))//2)
        self.assertTrue(receipt['nativeEdit']['multiline'],'Style is retained, not assumed to explain Windows behavior')
        self.assertIs(api.user.SendMessageTimeoutW.restype,smoke.ctypes.c_ssize_t)
        self.assertEqual(api.user.SendMessageTimeoutW.argtypes[-1],smoke.ctypes.POINTER(smoke.ctypes.c_size_t))
        self.assertIs(api.user.GetWindowLongW.restype,smoke.ctypes.c_int32)

    def test_native_text_fixture_copies_native_wchar_buffer_and_nul_with_declared_capacity(self):
        api,root,field,calls=self.picker_fixture()
        actual='가😀.odt'
        field.iface_value.text=actual
        source=smoke.ctypes.create_unicode_buffer(actual)
        destination=smoke.ctypes.create_unicode_buffer(32)
        smoke.ctypes.memset(smoke.ctypes.addressof(destination),0xa5,smoke.ctypes.sizeof(destination))
        count=smoke.ctypes.c_size_t()
        api.user.SendMessageTimeoutW(510,13,len(destination),smoke.ctypes.addressof(destination),3,1000,smoke.ctypes.byref(count))
        self.assertEqual(destination.value,actual)
        self.assertEqual(bytes(destination)[:smoke.ctypes.sizeof(source)],bytes(source))
        self.assertEqual(bytes(destination)[smoke.ctypes.sizeof(source):],b'\xa5'*(smoke.ctypes.sizeof(destination)-smoke.ctypes.sizeof(source)))
        self.assertEqual(count.value,len(actual.encode('utf-16-le'))//2)
        self.assertEqual(len(source),(len(actual.encode('utf-16-le'))//2 if smoke.ctypes.sizeof(smoke.ctypes.c_wchar)==2 else len(actual))+1)
        before=bytes(destination)
        for capacity in (1,len(actual.encode('utf-16-le'))//2):
            with self.subTest(capacity=capacity),self.assertRaises(AssertionError):
                api.user.SendMessageTimeoutW(510,13,capacity,smoke.ctypes.addressof(destination),3,1000,smoke.ctypes.byref(count))
        self.assertEqual(bytes(destination),before,'A declared capacity failure must not write any buffer bytes')

    def test_picker_native_edit_rechecks_live_ownership_focus_and_foreground_before_text_mutation(self):
        for mode in ('pid','dead','root','focus','foreground','unicode','native-edit-class'):
            with self.subTest(mode=mode):
                api,root,field,calls=self.picker_fixture()
                original=api.user.SendMessageTimeoutW
                queries=[]
                def send(*args):
                    result=original(*args)
                    if args[1]==0xB0:
                        queries.append(1)
                        if len(queries)==2:
                            if mode=='pid': api.pid=lambda handle:99
                            if mode=='dead': api.user.IsWindow=lambda handle:False
                            if mode=='root': api.user.GetAncestor=lambda handle,relation:999
                            if mode=='focus': api.focus_state.hwnd=999
                            if mode=='foreground': api.user.GetForegroundWindow=lambda:999
                            if mode=='foreground': api.user.GetAncestor=lambda handle,relation:999 if handle==999 else 500
                            if mode=='unicode': api.focus_state.unicode_window=False
                            if mode=='native-edit-class': api.class_name=lambda handle:'RichEdit50W'
                    return result
                api.user.SendMessageTimeoutW=send
                record={}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                receipt,=record['pickerFilenameInputs']
                self.assertEqual(receipt['selectionSetAttempts'],1)
                self.assertEqual(receipt['assignmentAttempts'],0)
                self.assertEqual(receipt['nativeEdit']['replaceResult']['sendReturn'],None)
                self.assertNotIn(0xC2,api.focus_state.messages)
                self.assertFalse(any(c[0]=='assign' for c in calls))

    def test_picker_timeout_without_native_error_does_not_report_stale_last_error(self):
        api,root,field,calls=self.picker_fixture(native_failure=0xC2)
        original=api.user.GetGUIThreadInfo
        state={'lastError':5}
        def context(*args):
            state['lastError']=5
            return original(*args)
        api.user.GetGUIThreadInfo=context
        record={}
        with patch.object(smoke.ctypes,'set_last_error',side_effect=lambda code:state.update(lastError=code),create=True), \
             patch.object(smoke.ctypes,'get_last_error',side_effect=lambda:state['lastError'],create=True):
            with self.assertRaises(OSError) as failure:
                smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
        self.assertEqual(failure.exception.errno,0)
        self.assertEqual(record['pickerFilenameInputs'][0]['nativeEdit']['replaceResult']['sendReturn'],0)

    def test_picker_rejects_oversized_packed_selection_and_readonly_changes_before_mutation(self):
        for mode in ('packed-before','packed-after','readonly-before-select','readonly-before-replace'):
            with self.subTest(mode=mode):
                api,root,field,calls=self.picker_fixture()
                original=api.user.SendMessageTimeoutW
                queries=[]
                def send(*args):
                    returned=original(*args)
                    if args[1]==0xB0:
                        queries.append(1)
                        if mode=='packed-before' and len(queries)==1: args[-1]._obj.value |= 1<<32
                        if mode=='packed-after' and len(queries)==2: args[-1]._obj.value |= 1<<32
                        if mode=='readonly-before-select' and len(queries)==1: field.iface_value.CurrentIsReadOnly=True
                        if mode=='readonly-before-replace' and len(queries)==2: field.iface_value.CurrentIsReadOnly=True
                    return returned
                api.user.SendMessageTimeoutW=send
                record={}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                receipt,=record['pickerFilenameInputs']
                self.assertEqual(receipt['assignmentAttempts'],0)
                self.assertEqual(receipt['selectionSetAttempts'],int(mode in ('packed-after','readonly-before-replace')))
                self.assertNotIn(0xC2,api.focus_state.messages)

    def test_native_edit_pure_receipt_replay_rejects_changed_intent_results_and_context(self):
        api,root,field,calls=self.picker_fixture()
        record={}
        smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
        receipt,=record['pickerFilenameInputs']
        smoke.require_picker_native_edit_receipt(receipt,31,500,510)
        for key,value in [('method','UIA-ValuePattern-SetValue'),('selectionSetAttempts',2),('assignmentAttempts',2)]:
            invalid=json.loads(json.dumps(receipt));invalid[key]=value
            with self.assertRaises(AssertionError): smoke.require_picker_native_edit_receipt(invalid,31,500,510)
        for key,value in [('unicodeWindow',False),('replaceReadOnly',True),('replacementUtf16LeHex','00')]:
            invalid=json.loads(json.dumps(receipt));invalid['nativeEdit'][key]=value
            with self.assertRaises(AssertionError): smoke.require_picker_native_edit_receipt(invalid,31,500,510)
        for node,key,value in [('selectResult','lParam',0),('replaceResult','wParam',0),
                               ('replaceResult','sendReturn',0),('selectionAfterSelect','packedResult',0),
                               ('selectionAfterSelect','messageReturn',1<<32)]:
            invalid=json.loads(json.dumps(receipt));invalid['nativeEdit'][node][key]=value
            with self.assertRaises(AssertionError): smoke.require_picker_native_edit_receipt(invalid,31,500,510)
        invalid=json.loads(json.dumps(receipt));invalid['nativeEdit']['replaceResult']['context']['fieldPid']=99
        with self.assertRaises(AssertionError): smoke.require_picker_native_edit_receipt(invalid,31,500,510)

    def test_picker_filename_rejects_foreign_or_readonly_controls_before_assignment(self):
        self.assertTrue(hasattr(smoke,'set_owned_picker_filename'),'Owned native ValuePattern assignment is missing')
        invalids = ('dialog-pid','document-dead','owner','class','native-edit-class','caption','uia-root','field-pid','field-id','runtime-id','native-parent','readonly')
        for invalid in invalids:
            with self.subTest(invalid=invalid):
                api,root,field,calls = self.picker_fixture(readonly=invalid=='readonly')
                if invalid=='dialog-pid': api.pid=lambda handle: 99 if handle==500 else 31
                if invalid=='document-dead': api.user.IsWindow=lambda handle: handle!=100
                if invalid=='owner': api.user.GetWindow=lambda handle,relation: 999
                if invalid=='class': api.class_name=lambda handle: 'Foreign'
                if invalid=='native-edit-class': api.class_name=lambda handle: '#32770' if handle==500 else 'RichEdit50W'
                if invalid=='caption': api.title=lambda handle: 'Foreign'
                if invalid=='uia-root': root.element_info.handle=999
                if invalid=='field-pid': field.element_info.process_id=99
                if invalid=='field-id': field.element_info.automation_id='other'
                if invalid=='runtime-id': field.element_info.runtime_id=[]
                if invalid=='native-parent': api.user.IsChild=lambda parent,child: False
                record = {}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                self.assertFalse(any(c[0] in ('focus','assign') for c in calls))
                evidence, = record['pickerFilenameInputs']
                self.assertFalse(evidence['success'])
                self.assertEqual(evidence['assignmentAttempts'],0)
                self.assertIn('error',evidence)

    def test_picker_filename_preserves_mismatched_value_and_method_failure_without_retry(self):
        self.assertTrue(hasattr(smoke,'set_owned_picker_filename'),'Owned native ValuePattern assignment is missing')
        for mode in ('wrong-readback','assign','read'):
            with self.subTest(mode=mode):
                api,root,field,calls = self.picker_fixture(wrong_readback=mode=='wrong-readback',method_error=mode)
                expected,record='D:\\owned\\새 문서 & 한글.docx',{}
                with self.assertRaises((AssertionError,RuntimeError)):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,expected,record)
                evidence, = record['pickerFilenameInputs']
                self.assertFalse(evidence['success'])
                self.assertEqual(sum(c[0]=='assign' for c in calls),0 if mode=='read' else 1)
                self.assertEqual(evidence['expected'],expected)
                self.assertIn('before',evidence)
                self.assertIn('after',evidence)
                if mode=='wrong-readback':
                    self.assertEqual(evidence['after'],expected[:-1])
                    self.assertIn('Picker filename differs',evidence['error'])

    def test_picker_focus_is_actual_native_edit_before_one_assignment_and_readback(self):
        api,root,field,calls=self.picker_fixture()
        record={}
        smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
        receipt,=record['pickerFilenameInputs']
        self.assertEqual(receipt['focusBefore']['focusHwnd'],500)
        self.assertEqual(receipt['focusAfterClick']['focusHwnd'],510)
        self.assertEqual(receipt['focusAfterAssignment']['focusHwnd'],510)
        self.assertEqual(receipt['focusAfterAssignment']['nativeText'],receipt['after'])
        self.assertEqual(receipt['focusAfterAssignment']['threadId'],111)
        self.assertEqual(receipt['focusClickAttempts'],1)
        self.assertLess(calls.index(('focus',510)),next(i for i,c in enumerate(calls) if c[0]=='assign'))

    def test_picker_stolen_focus_and_native_text_mismatch_fail_without_repeat(self):
        for mode in ('focus-not-acquired','focus-stolen-after-assignment','native-text-mismatch','native-stale-after-assignment'):
            with self.subTest(mode=mode):
                api,root,field,calls=self.picker_fixture()
                if mode=='focus-not-acquired': field.click_input=lambda:calls.append(('focus-missed',510))
                if mode=='focus-stolen-after-assignment': api.focus_state.steal_after_assignment=True
                if mode=='native-text-mismatch': api.focus_state.native_override='stale native filename'
                if mode=='native-stale-after-assignment': api.focus_state.native_override_after_assignment=True
                record={}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                receipt,=record['pickerFilenameInputs']
                self.assertFalse(receipt['success'])
                self.assertIn('error',receipt)
                self.assertEqual(receipt['assignmentAttempts'],0 if mode in ('focus-not-acquired','native-text-mismatch') else 1)
                self.assertEqual(sum(c[0]=='assign' for c in calls),receipt['assignmentAttempts'])

    def test_picker_rechecks_fresh_ownership_and_foreground_before_physical_focus(self):
        for mode in ('changed-pid','foreign-foreground'):
            with self.subTest(mode=mode):
                api,root,field,calls=self.picker_fixture()
                if mode=='changed-pid':
                    queries=[]
                    def pid(handle):
                        if handle==510:
                            queries.append(handle)
                            return 31 if len(queries)==1 else 99
                        return 31
                    api.pid=pid
                else:
                    api.user.GetForegroundWindow=lambda:999
                    api.user.GetAncestor=lambda handle,relation:999 if handle==999 else 500
                record={}
                with self.assertRaises(AssertionError):
                    smoke.set_owned_picker_filename(api,31,100,500,root,field,'D:\\owned\\한글.docx',record)
                receipt,=record['pickerFilenameInputs']
                self.assertEqual(receipt['focusClickAttempts'],0)
                self.assertEqual(receipt['assignmentAttempts'],0)
                self.assertFalse(any(c[0] in ('focus','assign') for c in calls))
                self.assertIn('error',receipt)

    def test_actual_picker_assigns_fixture_then_physically_selects_save_or_cancel(self):
        for cancel in (False,True):
            with self.subTest(cancel=cancel):
                api,root,field,calls = self.picker_fixture()
                case=SimpleNamespace(api=api,process=SimpleNamespace(pid=31),record={},
                                     dialog=lambda hwnd,caption:(500,root),screenshot=lambda *args:None)
                action_id='2' if cancel else '1'
                def click():
                    self.assertTrue(case.record['pickerFilenameInputs'][0]['success'])
                    calls.append(('click',action_id))
                action=SimpleNamespace(element_info=SimpleNamespace(automation_id=action_id),
                                       is_visible=lambda:True,is_enabled=lambda:True,click_input=click)
                root.descendants=lambda **options:[field] if options.get('control_type')=='Edit' else [action]
                native_root=SimpleNamespace(set_focus=lambda:None)
                desktop=SimpleNamespace(window=lambda **options:SimpleNamespace(wrapper_object=lambda:native_root))
                def unexpected_keyboard(*args,**kwargs):
                    raise AssertionError('Fixture filename must not use the unreliable keyboard path')
                modules={'pywinauto':SimpleNamespace(Desktop=lambda **kwargs:desktop),
                         'pywinauto.keyboard':SimpleNamespace(send_keys=unexpected_keyboard)}
                with patch.dict('sys.modules',modules):
                    self.assertEqual(smoke.Case.picker(case,100,'D:\\owned\\새 문서 & 한글.docx',cancel=cancel),500)
                self.assertEqual(calls[-1],('click',action_id))
                self.assertEqual(sum(c[0]=='assign' for c in calls),1)

    def test_policy_api_is_present(self):
        for name in ('CASE_REQUIREMENTS', 'lifecycle_report', 'writer_evidence',
                     'owned_target', 'require_dialog_action', 'require_child_bounds',
                     'generate_hwpx', 'copy_writer_fixture'):
            self.assertTrue(hasattr(smoke, name), 'Missing lifecycle evidence policy: ' + name)

    def test_report_requires_every_case_and_concrete_native_evidence(self):
        if not hasattr(smoke, 'CASE_REQUIREMENTS'): self.skipTest('RED: policy API not implemented')
        records = [{'case': name, 'success': True, **{key: True for key in flags}}
                   for name, flags in smoke.CASE_REQUIREMENTS.items()]
        self.assertTrue(smoke.lifecycle_report(records)['success'])
        self.assertEqual(len(records), 7)
        for index, record in enumerate(records):
            for flag in smoke.CASE_REQUIREMENTS[record['case']]:
                invalid = [item.copy() for item in records]
                invalid[index][flag] = False
                self.assertFalse(smoke.lifecycle_report(invalid)['success'], flag)
        for invalid in (records[:-1], records + records[:1], records + [{'case': 'unexpected', 'success': True}]):
            self.assertFalse(smoke.lifecycle_report(invalid)['success'])

    def test_copy_uses_passing_generated_provenance_without_mutating_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures, owned = root / 'fixtures', root / 'owned'
            fixtures.mkdir()
            owned.mkdir()
            source = fixtures / 'OpenGeul-writer.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Engine-OpenGeul-writer UI-OpenGeul-writer</w:t></w:r></w:p></w:body></w:document>')
            record = {'schemaVersion': 1, 'kind': 'engine', 'passed': True,
                      'cases': [{'module': 'writer', 'status': 'passed', 'fixture': str(source.resolve())}]}
            baseline = root / 'engine-smoke.json'
            baseline.write_text(json.dumps(record), encoding='utf-8')
            before = source.read_bytes()
            copied = smoke.copy_writer_fixture(fixtures, owned, '복사 문서 & 한글.docx')
            self.assertEqual(copied.read_bytes(), before)
            self.assertEqual(source.read_bytes(), before)
            record['passed'] = False
            baseline.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaises(AssertionError): smoke.copy_writer_fixture(fixtures, owned, 'invalid.docx')

    def test_uno_evidence_requires_exact_body_source_sha_and_unchanged_file(self):
        self.assertTrue(hasattr(smoke, 'require_uno_observation'), 'Missing independent UNO evidence policy')
        expected = {'sha256': 'abc123', 'bodyText': 'Owned\n한글 & body'}
        result = smoke.require_uno_observation(expected, 'Owned\r\n한글 & body', 'abc123', 'abc123')
        self.assertEqual(result['bodyText'], expected['bodyText'])
        for actual, before, after in (('Wrong body', 'abc123', 'abc123'),
                                     (expected['bodyText'], 'changed', 'changed'),
                                     (expected['bodyText'], 'abc123', 'changed')):
            with self.assertRaises(AssertionError): smoke.require_uno_observation(expected, actual, before, after)

    def test_independent_uno_reopen_retains_each_case_and_observed_text_after_one_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            fixtures = output / 'fixtures'
            fixtures.mkdir()
            records = []
            for name in ('dirty-writer-cancel-save', 'dirty-writer-discard'):
                target = fixtures / (name + '.docx')
                with zipfile.ZipFile(target, 'w') as package:
                    package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Owned body</w:t></w:r></w:p></w:body></w:document>')
                records.append({'case': name, 'success': True,
                                'savedDocuments': [{'path': str(target), **smoke.writer_evidence(target)}]})
            (output / 'results.json').write_text(json.dumps({'tests': records}), encoding='utf-8')
            class Engine:
                cleanup_errors = []
                def __init__(self, suite): pass
                def start(self): pass
                def cleanup(self): pass
                def close_document(self, document): pass
                def load(self, url):
                    text = 'Wrong observed body' if 'cancel-save' in url else 'Owned body'
                    return SimpleNamespace(supportsService=lambda name: True,
                                           getText=lambda: SimpleNamespace(getString=lambda: text))
            with patch.object(smoke, '_sibling', return_value=SimpleNamespace(Engine=Engine)):
                self.assertEqual(smoke.verify_saved_with_uno(output, output), 1)
            result = json.loads((output / 'packaged-uno-result.json').read_text(encoding='utf-8'))
            self.assertEqual(len(result['cases']), 2, 'One failed document must not hide another case\'s independent result')
            self.assertFalse(result['success'])
            self.assertFalse(result['cases'][0]['success'])
            self.assertTrue(result['cases'][1]['success'])
            self.assertEqual(result['cases'][0]['documents'][0]['observedBodyText'], 'Wrong observed body')

    def test_writer_evidence_reads_only_body_text_and_exact_marker_counts(self):
        if not hasattr(smoke, 'writer_evidence'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'owned.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>BASE-</w:t></w:r><w:r><w:t>MARKER</w:t></w:r></w:p></w:body></w:document>')
                package.writestr('word/comments.xml', '<comment>FORBIDDEN</comment>')
            evidence = smoke.writer_evidence(source, ('BASE-MARKER',), ('FORBIDDEN',))
            self.assertEqual(evidence['bodyText'], 'BASE-MARKER')
            self.assertEqual(len(evidence['sha256']), 64)
            with self.assertRaises(AssertionError): smoke.writer_evidence(source, ('MISSING',))
            with self.assertRaises(AssertionError): smoke.writer_evidence(source, (), ('MARKER',))

    def test_writer_evidence_keeps_actual_soft_breaks_and_tabs_for_exact_uno_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'owned.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Engine-OpenGeul-writer 한글</w:t><w:br/><w:t>-LIFECYCLE-</w:t><w:tab/><w:t>끝</w:t></w:r></w:p><w:p><w:r><w:t>다음 문단</w:t><w:cr/></w:r></w:p></w:body></w:document>')
            evidence = smoke.writer_evidence(source, ('-LIFECYCLE-',))
            expected = 'Engine-OpenGeul-writer 한글\n-LIFECYCLE-\t끝\n다음 문단\n'
            self.assertEqual(evidence['bodyText'], expected)
            self.assertEqual(evidence['bodyParagraphs'], ['Engine-OpenGeul-writer 한글\n-LIFECYCLE-\t끝', '다음 문단\n'])
            smoke.require_uno_observation(evidence, expected, evidence['sha256'], evidence['sha256'])

    def test_owned_menu_search_uses_supported_window_roots_and_deduplicates_runtime_identity(self):
        self.assertTrue(hasattr(smoke, 'owned_menu_items'), 'Owned menu enumeration is missing')
        def item(name, pid, identity, visible=True, enabled=True):
            return SimpleNamespace(element_info=SimpleNamespace(name=name, process_id=pid, runtime_id=identity),
                                   is_visible=lambda: visible, is_enabled=lambda: enabled)
        expected = item('새 문서', 31, [42, 1])
        children = [expected, item('새 문서', 99, [42, 2]), item('다른 이름으로 저장...', 31, [42, 3]),
                    item('새 문서', 31, [42, 4], visible=False)]
        root = SimpleNamespace(element_info=SimpleNamespace(process_id=31), descendants=lambda **kw: children)
        class Desktop:
            def windows(self, **options):
                self.options = options
                return [root, root]
        desktop = Desktop()
        self.assertEqual(smoke.owned_menu_items(desktop, 31, '새 문서'), [expected])
        self.assertEqual(desktop.options, {'process': 31})

    def test_overwrite_yes_button_uses_exact_observed_label_and_owned_process(self):
        self.assertTrue(hasattr(smoke, 'owned_dialog_button'), 'Owned exact-label dialog selection is missing')
        def button(name, pid, automation_id, visible=True, enabled=True):
            return SimpleNamespace(element_info=SimpleNamespace(name=name, process_id=pid, automation_id=automation_id),
                                   is_visible=lambda: visible, is_enabled=lambda: enabled)
        expected = button('Yes', 31, 'CommandButton_6')
        controls = [button('No', 31, '7'), button('Yes', 99, '6'), expected,
                    button('Yes', 31, '6', visible=False)]
        accessible = SimpleNamespace(descendants=lambda **kw: controls)
        self.assertIs(smoke.owned_dialog_button(accessible, 31, ('Yes', '예', '예(&Y)')), expected)
        for controls in ([button('No', 31, '6')], [expected, expected], [button('Yes', 99, '6')]):
            accessible = SimpleNamespace(descendants=lambda **kw: controls)
            with self.assertRaises(AssertionError): smoke.owned_dialog_button(accessible, 31, ('Yes', '예', '예(&Y)'))

    def test_saveas_surface_skips_picker_with_real_nested_confirmation_text(self):
        # Run 38937322964 reported the outer picker HWND 1442708 as its own
        # overwrite confirmation because UIA descendants include owned dialogs.
        self.assertTrue(hasattr(smoke, 'saveas_error_surface'), 'Distinct native Save As surface selector is missing')
        document, picker, confirmation, pid = 918474, 1442708, 1550000, 1160
        target = '잠긴 저장 대상 & 한글.docx'
        texts = ['Confirm Save As', target + ' already exists.\r\nDo you want to replace it?', 'Yes', 'No']
        root_info = SimpleNamespace(handle=confirmation, process_id=pid, runtime_id=[42, confirmation],
                                    name='Confirm Save As', control_type='Window')
        root = SimpleNamespace(element_info=root_info, descendants=lambda: [SimpleNamespace(element_info=SimpleNamespace(name=text)) for text in texts])
        queried = []
        def window(**options):
            queried.append(options['handle'])
            self.assertEqual(options['handle'], confirmation, 'Never classify aggregate picker/document descendants as a new dialog')
            return SimpleNamespace(wrapper_object=lambda: root)
        api = SimpleNamespace(windows=lambda owned_pid: [picker, document, confirmation],
                              pid=lambda handle: pid, class_name=lambda handle: '#32770',
                              title=lambda handle: 'Confirm Save As',
                              user=SimpleNamespace(GetWindow=lambda handle, relation: picker if handle == confirmation else document,
                                                   IsWindow=lambda handle: True))
        desktop = SimpleNamespace(window=window)
        observed = smoke.saveas_error_surface(api, pid, document, picker, target, desktop)
        self.assertEqual(observed[:3], ('overwrite', confirmation, picker))
        self.assertEqual(queried, [confirmation])
        for invalid in ({'handle': picker}, {'process_id': 99}, {'runtime_id': []}):
            original = root_info.__dict__.copy()
            root_info.__dict__.update(invalid)
            with self.assertRaises(AssertionError):
                smoke.saveas_error_surface(api, pid, document, picker, target, desktop)
            root_info.__dict__.clear()
            root_info.__dict__.update(original)
        for foreign_pid, owner in ((99, picker), (pid, 777)):
            api.pid = lambda handle, value=foreign_pid: value
            api.user.GetWindow = lambda handle, relation, value=owner: value
            self.assertIsNone(smoke.saveas_error_surface(api, pid, document, picker, target, desktop))

    def test_failed_saveas_real_picker_first_order_reaches_only_distinct_confirmation_yes(self):
        class ReachedOwnedYes(Exception): pass
        def click_yes(): raise ReachedOwnedYes('distinct confirmation Yes selected')
        document, picker, confirmation, pid = 918474, 1442708, 1550000, 1160
        prompt = '잠긴 저장 대상 & 한글.docx already exists.\r\nDo you want to replace it?'
        info = SimpleNamespace(handle=confirmation, process_id=pid, runtime_id=[42, confirmation],
                               name='Confirm Save As', control_type='Window', parent=None)
        yes_info = SimpleNamespace(handle=700, process_id=pid, runtime_id=[42, 700],
                                   name='Yes', control_type='Button', parent=info)
        yes = SimpleNamespace(element_info=yes_info, is_visible=lambda: True, is_enabled=lambda: True, click_input=click_yes)
        text = SimpleNamespace(element_info=SimpleNamespace(name=prompt))
        confirmation_root = SimpleNamespace(element_info=info, descendants=lambda **kw: [yes] if kw else [text, yes], set_focus=lambda: None)
        picker_root = SimpleNamespace(element_info=SimpleNamespace(handle=picker, process_id=pid),
                                      descendants=lambda **kw: [text, yes, SimpleNamespace(element_info=SimpleNamespace(name='File name:'))])
        roots = {picker: picker_root, confirmation: confirmation_root}
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: roots[kw['handle']]))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'original.docx'
            source.write_bytes(b'owned original')
            case = SimpleNamespace(source=source, folder=folder, record={}, process=SimpleNamespace(pid=pid),
                                   attach=lambda: (document, 200, 300), edit=lambda *args: None,
                                   shell_command=lambda *args: None, picker=lambda *args: picker,
                                   screenshot=lambda *args: None)
            owners = {document: 0, picker: document, confirmation: picker}
            case.api = SimpleNamespace(windows=lambda owned_pid: [picker, confirmation], pid=lambda handle: pid,
                title=lambda handle: 'OpenGeul Writer — 다른 이름으로 저장' if handle == picker else 'Confirm Save As',
                class_name=lambda handle: '#32770', require_foreground=lambda handle: None,
                user=SimpleNamespace(GetWindow=lambda handle, relation: owners[handle], IsWindow=lambda handle: True,
                                     GetAncestor=lambda handle, relation: confirmation))
            with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop)}), \
                 patch.object(smoke, 'ExclusiveRead', return_value=SimpleNamespace(close=lambda: None)):
                with self.assertRaisesRegex(ReachedOwnedYes, 'distinct confirmation Yes selected'):
                    smoke.failed_saveas(case)
            self.assertEqual(case.record['saveAsOverwriteOwnership']['dialog']['hwnd'], confirmation)

    def test_overwrite_button_ancestry_binds_uia_and_native_confirmation_roots(self):
        self.assertTrue(hasattr(smoke, 'require_dialog_button_ancestry'), 'Exact confirmation button ancestry is missing')
        root = SimpleNamespace(handle=600, process_id=31, runtime_id=[42, 600],
                               name='Confirm Save As', control_type='Window', parent=None)
        pane = SimpleNamespace(handle=700, process_id=31, runtime_id=[42, 700],
                               name='', control_type='Pane', parent=root)
        button = SimpleNamespace(handle=0, process_id=31, runtime_id=[42, 6],
                                 name='Yes', control_type='Button', parent=pane)
        api = SimpleNamespace(pid=lambda handle: 31,
                              user=SimpleNamespace(IsWindow=lambda handle: True,
                                                   GetAncestor=lambda handle, relation: 600))
        accessible = SimpleNamespace(element_info=root)
        action = SimpleNamespace(element_info=button)
        proof = smoke.require_dialog_button_ancestry(api, accessible, action, 31, 600)
        self.assertEqual([row['nativeHandle'] for row in proof], [0, 700, 600])
        self.assertEqual(proof[1]['nativeRoot'], 600)
        for element, changes in ((pane, {'control_type': 'Window', 'handle': 800}),
                                 (pane, {'process_id': 99}), (button, {'runtime_id': []}),
                                 (root, {'handle': 500}), (pane, {'parent': None})):
            original = element.__dict__.copy()
            element.__dict__.update(changes)
            with self.assertRaises(AssertionError):
                smoke.require_dialog_button_ancestry(api, accessible, action, 31, 600)
            element.__dict__.clear()
            element.__dict__.update(original)
        api.user.GetAncestor = lambda handle, relation: 999
        failed_path = []
        with self.assertRaises(AssertionError):
            smoke.require_dialog_button_ancestry(api, accessible, action, 31, 600, failed_path)
        self.assertEqual(failed_path[-1]['nativeHandle'], 700)
        self.assertEqual(failed_path[-1]['nativeRoot'], 999, 'Keep the raw failing ancestry before any input')

    def test_real_save_error_action_targets_exact_owned_ok_without_assuming_automation_id(self):
        class ReachedOwnedOk(Exception): pass
        def click_ok(): raise ReachedOwnedOk('owned OK selected')
        okay = SimpleNamespace(element_info=SimpleNamespace(name='OK', process_id=31, automation_id='CommandButton_1'),
                               is_visible=lambda: True, is_enabled=lambda: True, click_input=click_ok)
        prompt = SimpleNamespace(element_info=SimpleNamespace(name='문서를 저장하지 못했습니다. 문서 창을 유지합니다.'))
        info = SimpleNamespace(handle=600, process_id=31, runtime_id=[42, 600], name='OpenGeul Office', control_type='Window')
        accessible = SimpleNamespace(element_info=info, descendants=lambda **kw: [okay] if kw else [prompt, okay], set_focus=lambda: None)
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: accessible))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'original.docx'
            source.write_bytes(b'owned original')
            case = SimpleNamespace(source=source, folder=folder, record={}, process=SimpleNamespace(pid=31),
                                   attach=lambda: (100, 200, 300), edit=lambda *args: None,
                                   shell_command=lambda *args: None, picker=lambda *args: 500,
                                   screenshot=lambda *args: None)
            case.api = SimpleNamespace(windows=lambda pid: [600], pid=lambda hwnd: 31,
                                       title=lambda hwnd: 'OpenGeul Office', class_name=lambda hwnd: '#32770',
                                       require_foreground=lambda hwnd: None,
                                       user=SimpleNamespace(GetWindow=lambda hwnd, relation: 100, IsWindow=lambda handle: True))
            with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop)}), \
                 patch.object(smoke, 'ExclusiveRead', return_value=SimpleNamespace(close=lambda: None)):
                with self.assertRaisesRegex(ReachedOwnedOk, 'owned OK selected'):
                    smoke.failed_saveas(case)

    def test_read_only_hwp_label_census_keeps_names_without_instantiating_control_wrappers(self):
        self.assertTrue(hasattr(smoke, 'accessibility_names'), 'Raw accessibility label census is missing')
        children = [SimpleNamespace(name='경로 확인 & 한글 문서.hwpx', control_type=None),
                    SimpleNamespace(name='OpenGeul', control_type='Text')]
        info = SimpleNamespace(name='Owned HWP root', descendants=lambda: children)
        def wrapped_descendants(): raise KeyError(None)
        root = SimpleNamespace(element_info=info, descendants=wrapped_descendants)
        self.assertEqual(smoke.accessibility_names(root), ['Owned HWP root', '경로 확인 & 한글 문서.hwpx', 'OpenGeul'])

    def test_hwp_child_census_uses_native_parent_and_exact_image_without_starting_wmi(self):
        self.assertIn('shell_creation', inspect.signature(smoke._hwp_child_process).parameters,
                      'Snapshot PID reuse is not rejected against retained shell creation')
        class Function:
            def __init__(self, operation): self.operation = operation
            def __call__(self, *args): return self.operation(*args)
        class Kernel:
            def __init__(self, rows, creation_overrides=None):
                self.rows, self.position, self.error = rows, -1, 0
                self.creation_overrides = creation_overrides or {}
                self.opened, self.closed = [], []
                self.CreateToolhelp32Snapshot = Function(lambda flags, pid: 777)
                self.Process32FirstW = Function(lambda handle, entry: self.entry(entry, 0))
                self.Process32NextW = Function(lambda handle, entry: self.entry(entry, self.position + 1))
                self.OpenProcess = Function(self.open)
                self.QueryFullProcessImageNameW = Function(self.image)
                self.GetProcessTimes = Function(self.times)
                self.GetSystemTimePreciseAsFileTime = Function(self.clock)
                self.WaitForSingleObject = Function(lambda handle, timeout: 258)
                self.CloseHandle = Function(lambda handle: self.closed.append(handle) or 1)
            def entry(self, pointer, position):
                self.position = position
                if position >= len(self.rows):
                    self.error = 18
                    return 0
                pid, parent, name, _ = self.rows[position]
                pointer._obj.th32ProcessID, pointer._obj.th32ParentProcessID = pid, parent
                pointer._obj.szExeFile = name
                return 1
            def open(self, access, inherit, pid):
                self.opened.append(pid)
                return 1000 + pid
            def image(self, handle, flags, buffer, length):
                buffer.value = next(row[3] for row in self.rows if row[0] == handle - 1000)
                length._obj.value = len(buffer.value.encode('utf-16-le')) // 2
                return 1
            def times(self, handle, creation, exit_time, kernel_time, user_time):
                created = self.creation_overrides.get(handle - 1000, (1 << 32) + handle - 1000)
                creation._obj.dwLowDateTime, creation._obj.dwHighDateTime = created & 0xffffffff, created >> 32
                return 1
            def clock(self, pointer):
                pointer._obj.dwLowDateTime, pointer._obj.dwHighDateTime = 1000, 1
        executable = Path('/owned/OpenGeul.exe').resolve()
        foreign = Path('/foreign/OpenGeul.exe').resolve()
        foreign_unicode = Path('/foreign/한글 😀/OpenGeul.exe').resolve()
        rows = [(106, 99, 'OpenGeul.exe', str(executable)),
                (107, 31, 'OpenGeul.exe', str(foreign)),
                (108, 31, 'OpenGeul.exe', str(executable)),
                (109, 31, 'Foreign.exe', str(Path('/foreign/Foreign.exe').resolve())),
                (111, 31, 'OpenGeul.exe', str(foreign_unicode))]
        self.assertTrue(all(Path(row[3]).is_absolute() and Path(row[3]).resolve() == Path(row[3]) for row in rows),
                        'Fake QueryFullProcessImageNameW must emit canonical full paths')
        for additional, expected in (([], 108), ([(110, 31, 'OpenGeul.exe', str(executable))], None)):
            kernel = Kernel(rows + additional)
            with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
                 patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True), \
                 patch.object(smoke.subprocess, 'run', side_effect=AssertionError('WMI subprocess must not run')):
                if additional:
                    with self.assertRaises(AssertionError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
                else:
                    census = {}
                    observed = smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31, evidence=census)
                    self.assertEqual(observed, {'pid': expected, 'parentPid': 31, 'creationFileTime': (1 << 32) + expected,
                                                'executable': str(executable)})
                    unicode_candidate, = [candidate for candidate in census['candidates'] if candidate['pid'] == 111]
                    self.assertEqual(unicode_candidate['nativeImage'], str(foreign_unicode))
                    self.assertEqual(unicode_candidate['nativeImageLength'], len(str(foreign_unicode).encode('utf-16-le')) // 2)
                    self.assertGreater(unicode_candidate['nativeImageLength'], len(str(foreign_unicode)))
                    self.assertFalse(unicode_candidate['matched'], 'A Unicode foreign full image remains a rejected negative')
            self.assertEqual(kernel.opened[:2], [107, 108])
            self.assertIn(777, kernel.closed)
            self.assertIn(1107, kernel.closed)
            self.assertIn(1108, kernel.closed)
            self.assertIs(kernel.CreateToolhelp32Snapshot.restype, smoke.wintypes.HANDLE)
            self.assertEqual(kernel.Process32FirstW.argtypes, (smoke.wintypes.HANDLE, smoke.ctypes.POINTER(smoke.ProcessEntry32W)))
        self.assertEqual(smoke.ProcessEntry32W.th32DefaultHeapID.offset, 16)
        self.assertEqual(smoke.ProcessEntry32W.th32ParentProcessID.offset, 32)
        self.assertEqual(smoke.ProcessEntry32W.szExeFile.offset, 44)
        kernel = Kernel([rows[0]])
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True):
            self.assertIsNone(smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31))
        self.assertEqual(kernel.closed, [777])
        self.assertFalse(kernel.opened)
        kernel = Kernel(rows)
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True):
            for invalid in (-1, 0, 1 << 32, True):
                with self.assertRaises(AssertionError): smoke._hwp_child_process(invalid, executable, shell_creation=(1 << 32) + 31)
        kernel = Kernel(rows)
        kernel.OpenProcess = Function(lambda *args: 0)
        kernel.error = 5
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True), \
             patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'native failure'), create=True):
            with self.assertRaises(OSError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
        self.assertEqual(kernel.closed, [777], 'Snapshot must close after a candidate handle failure')
        kernel = Kernel(rows)
        kernel.CreateToolhelp32Snapshot = Function(lambda *args: smoke.ctypes.c_void_p(-1).value)
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(smoke.ctypes, 'get_last_error', return_value=5, create=True), \
             patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'native failure'), create=True):
            with self.assertRaises(OSError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
        self.assertFalse(kernel.closed, 'An invalid snapshot is never passed to CloseHandle')
        for created in ((1 << 32) + 1, (1 << 32) + 2000):
            kernel = Kernel([rows[2]], {108: created})
            with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
                 patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True):
                self.assertIsNone(smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31),
                                  'Stale PPID or post-snapshot recycled same-image process must never match')
            self.assertEqual(kernel.closed, [1108, 777])
        for failed in ('Process32FirstW', 'Process32NextW', 'QueryFullProcessImageNameW', 'GetProcessTimes'):
            kernel = Kernel(rows)
            setattr(kernel, failed, Function(lambda *args: 0))
            kernel.error = 5
            with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
                 patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True), \
                 patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'native failure'), create=True):
                with self.assertRaises(OSError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
            self.assertIn(777, kernel.closed, failed)
            if failed in ('QueryFullProcessImageNameW', 'GetProcessTimes'): self.assertIn(1107, kernel.closed, failed)

    def test_retained_hwp_handle_rejects_pid_reuse_with_changed_creation_time(self):
        self.assertIn('expected_creation', inspect.signature(smoke.BoundHwpProcess).parameters,
                      'Retained handle does not verify the native snapshot creation witness')
        class Function:
            def __init__(self, operation): self.operation = operation
            def __call__(self, *args): return self.operation(*args)
        closed = []
        def times(handle, creation, *args):
            creation._obj.dwLowDateTime, creation._obj.dwHighDateTime = 108, 1
            return 1
        def image(handle, flags, buffer, length):
            buffer.value = str(Path('/owned/OpenGeul.exe').resolve())
            length._obj.value = len(buffer.value.encode('utf-16-le')) // 2
            return 1
        kernel = SimpleNamespace(**{name: Function(lambda *args: 1) for name in (
            'CreateToolhelp32Snapshot', 'Process32FirstW', 'Process32NextW', 'WaitForSingleObject', 'GetSystemTimePreciseAsFileTime')},
            OpenProcess=Function(lambda *args: 1108), GetProcessTimes=Function(times),
            QueryFullProcessImageNameW=Function(image), CloseHandle=Function(lambda handle: closed.append(handle) or 1))
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True):
            with self.assertRaisesRegex(AssertionError, 'creation'):
                smoke.BoundHwpProcess(108, Path('/owned/OpenGeul.exe'), expected_creation=(1 << 32) + 107)
        self.assertEqual(closed, [1108])

    def test_hwp_readiness_requires_real_postload_toolbar_and_enabled_offscreen_input(self):
        self.assertTrue(hasattr(smoke, 'hwp_postload_observation'), 'Post-load HWP readiness policy is missing')
        def row(name, kind, identity, *, enabled=True, visible=True, bounds=(10, 10, 70, 30)):
            return {'name': name, 'controlType': kind, 'automationId': identity, 'enabled': enabled,
                    'visible': visible, 'bounds': list(bounds), 'processId': 31, 'runtimeId': [31, len(identity)]}
        rows = [row('경로 확인 & 한글 문서.hwpx', 'Text', 'sb-message'),
                row('문서 편집 입력', 'Edit', '', visible=False, bounds=(-9999, 0, -9998, 1)),
                row('글자 크기 (pt)', 'Edit', 'font-size'), row('대표', 'Button', ''), row('바탕글', 'Button', '')]
        proof = smoke.hwp_postload_observation(rows)
        self.assertTrue(proof['postLoadEditorVerified'])
        self.assertTrue(proof['toolbarEnabled'])
        self.assertEqual(proof['editorInput']['name'], '문서 편집 입력')
        self.assertFalse(proof['editorInput']['visible'], 'Production IME textarea is deliberately offscreen')
        self.assertEqual(proof['fontSize']['automationId'], 'font-size')
        self.assertEqual(proof['fontLanguage']['name'], '대표')
        for invalid in (rows[:2], rows[:3], rows[:4]):
            self.assertIsNone(smoke.hwp_postload_observation(invalid), 'Filename and attached WebView do not prove document readiness')
        for index, key, value in ((1, 'enabled', False), (2, 'enabled', False), (2, 'visible', False),
                                  (2, 'controlType', 'Text'), (3, 'visible', False), (4, 'enabled', False)):
            invalid = [item.copy() for item in rows]
            invalid[index][key] = value
            self.assertIsNone(smoke.hwp_postload_observation(invalid))
        with self.assertRaises(AssertionError): smoke.hwp_postload_observation(rows + [rows[2]])

    def test_hwp_raw_snapshot_retains_unavailable_metadata_without_certifying_a_control(self):
        class COMError(Exception): hresult = -2147220991
        class Stale:
            name, control_type, automation_id, process_id, runtime_id = '글자 크기 (pt)', 'Edit', 'font-size', None, None
            @property
            def rectangle(self): raise COMError('Element is no longer available')
        info = SimpleNamespace(name='Owned HWP root', control_type='Window', automation_id='', process_id=31,
                               runtime_id=[31], enabled=True, visible=True,
                               rectangle=SimpleNamespace(left=0, top=0, right=800, bottom=600), descendants=lambda: [Stale()])
        with patch.dict('sys.modules', {'comtypes': SimpleNamespace(COMError=COMError)}):
            try: rows = smoke.hwp_accessibility_snapshot(SimpleNamespace(element_info=info))
            except COMError: self.fail('Unavailable UIA metadata must be retained as failed observation, never certify readiness')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['name'], '글자 크기 (pt)')
        self.assertEqual(rows[1]['metadataError']['hresult'], -2147220991)
        self.assertFalse(rows[1]['enabled'])
        self.assertIsNone(smoke.hwp_postload_observation(rows))

    def test_targets_are_fresh_direct_children_and_never_links(self):
        if not hasattr(smoke, 'owned_target'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = smoke.owned_target(root, '한글 저장 & 결과.docx')
            self.assertEqual(target.parent, root.resolve())
            target.write_bytes(b'owned')
            for name in ('한글 저장 & 결과.docx', '../escape.docx', '/absolute.docx'):
                with self.assertRaises(AssertionError): smoke.owned_target(root, name)
            link = root / 'link.docx'
            try: link.symlink_to(target)
            except OSError: return
            with self.assertRaises(AssertionError): smoke.owned_target(root, link.name)

    def test_dialog_action_checks_all_identity_and_exact_expected_button(self):
        if not hasattr(smoke, 'require_dialog_action'): self.skipTest('RED: policy API not implemented')
        identity = dict(pid=31, shell_pid=31, owner=44, document=44,
                        title='OpenGeul Writer', expected_title='OpenGeul Writer',
                        class_name='#32770', text=['변경 내용을 저장하시겠습니까?'],
                        expected_text='변경 내용을 저장하시겠습니까?', button='취소', allowed=('저장', '저장하지 않음', '취소'))
        smoke.require_dialog_action(**identity)
        for key, value in (('pid', 99), ('owner', 55), ('title', 'Foreign'),
                           ('class_name', 'Foreign'), ('text', ['foreign']), ('button', '확인')):
            with self.assertRaises(AssertionError): smoke.require_dialog_action(**{**identity, key: value})

    def test_saveas_overwrite_accepts_only_complete_live_document_or_picker_owner_chain(self):
        self.assertTrue(hasattr(smoke, 'require_saveas_overwrite_owner'), 'Explicit common-dialog ownership policy is missing')
        document = {'hwnd': 100, 'pid': 31, 'live': True}
        picker = {'hwnd': 500, 'pid': 31, 'live': True, 'owner': 100, 'title': 'OpenGeul Writer — 다른 이름으로 저장', 'class': '#32770'}
        dialog = {'hwnd': 600, 'pid': 31, 'live': True, 'owner': 500, 'title': 'Confirm Save As', 'class': '#32770',
                  'texts': ['잠긴 저장 대상 & 한글.docx already exists.', 'Do you want to replace it?']}
        for owner, chain in ((500, 'picker-owned'), (100, 'document-owned')):
            observed = {**dialog, 'owner': owner}
            self.assertEqual(smoke.require_saveas_overwrite_owner(observed, picker, document, 31, '잠긴 저장 대상 & 한글.docx'), chain)
        for target, key, value in (('dialog', 'owner', 999), ('dialog', 'pid', 99), ('dialog', 'live', False),
                                   ('dialog', 'class', 'Foreign'), ('dialog', 'title', 'Foreign'),
                                   ('dialog', 'texts', ['A different document already exists.']),
                                   ('picker', 'owner', 999), ('picker', 'pid', 99), ('picker', 'live', False),
                                   ('picker', 'class', 'Foreign'), ('picker', 'title', 'Foreign'),
                                   ('document', 'pid', 99), ('document', 'live', False)):
            fixtures = {'dialog': dialog.copy(), 'picker': picker.copy(), 'document': document.copy()}
            fixtures[target][key] = value
            with self.assertRaises(AssertionError):
                smoke.require_saveas_overwrite_owner(fixtures['dialog'], fixtures['picker'], fixtures['document'], 31, '잠긴 저장 대상 & 한글.docx')

    def test_bounds_require_child_to_fill_host_client_after_screen_mapping(self):
        if not hasattr(smoke, 'require_child_bounds'): self.skipTest('RED: policy API not implemented')
        self.assertEqual(smoke.require_child_bounds((0, 0, 900, 600), (0, 0, 900, 600)), [900, 600])
        for actual in ((0, 0, 800, 600), (1, 0, 901, 600), (0, 0, 900, 0)):
            with self.assertRaises(AssertionError): smoke.require_child_bounds((0, 0, 900, 600), actual)

    def test_generated_hwpx_contains_only_owned_text_and_leaves_template_intact(self):
        if not hasattr(smoke, 'generate_hwpx'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '경로 확인 & 문서.hwpx'
            template = Path(__file__).resolve().parents[2] / 'tests/fixtures/advanced-owned/owned-blank.hwpx'
            original = template.read_bytes()
            smoke.generate_hwpx(target)
            with zipfile.ZipFile(target) as package:
                text = ''.join(ET.fromstring(package.read('Contents/section0.xml')).itertext())
                self.assertIn('Suite-HWPX-route-한글 & 123', text)
                self.assertIsNone(package.testzip())
            self.assertEqual(template.read_bytes(), original)
            with self.assertRaises(AssertionError): smoke.generate_hwpx(target)


if __name__ == '__main__': unittest.main()
