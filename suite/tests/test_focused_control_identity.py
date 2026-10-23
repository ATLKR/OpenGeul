"""Real target/perform guards with bounded focused-ancestor identity doubles."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

import owned_control_actions as policy
from test_owned_control_actions import Clock, ControlProbe


class Element:
    def __init__(self, identity, kind, hwnd, parent=None, name='node', rectangle=(0, 0, 900, 700)):
        self.parent = parent
        self.values = dict(CurrentNativeWindowHandle=hwnd, CurrentProcessId=77,
            CurrentControlType=kind, CurrentName=name, CurrentAutomationId='',
            CurrentBoundingRectangle=NS(**dict(zip(('left', 'top', 'right', 'bottom'), rectangle))),
            CurrentIsOffscreen=False, CurrentIsEnabled=True)
        self.runtime = [42, identity]
        self.reads = []
        self.errors = {}
        self.on_runtime = lambda: None

    def __getattr__(self, name):
        self.reads.append(name)
        if name in self.errors:
            raise self.errors[name]
        return self.values[name]

    def GetRuntimeId(self):
        self.reads.append('GetRuntimeId')
        self.on_runtime()
        return self.runtime


class FocusedControlIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root_path = Path(self.temporary.name).resolve()
        self.process = NS(pid=77, _handle=1234, args=[str(self.root_path/'OpenGeul.Office.exe')],
            opengeul_suite_root=self.root_path, opengeul_evidence_output=self.root_path,
            opengeul_evidence_case='focused-identity')
        self.clock = Clock()
        self.boundary = ControlProbe(self.process, self.clock)
        self.root = Element(11, 50032, 11, name='OpenGeul Writer')
        self.bar = Element(21, 50010, 21, self.root)
        self.file = Element(20, 50011, 20, self.bar, name='파일', rectangle=(10, 30, 50, 50))
        self.focus = Element(900, 50004, 20, self.file)
        self.native = object.__new__(policy.NativeControlProbe)
        self.native.clock, self.native.deadline = self.clock, 6.
        self.native.uia = NS(iuia=NS(GetFocusedElement=lambda:self.focus,
            CompareElements=lambda a,b:a is b,
            ControlViewWalker=NS(GetParentElement=lambda element:element.parent)))
        self.native.desktop = NS(window=lambda **kw:NS(wrapper_object=lambda:NS(element_info=NS(_element=self.root))))
        self.native._window = lambda hwnd:copy.deepcopy(self.boundary.value['document'])
        self.native.foreground = lambda:11
        self.native.native_focus = lambda thread:copy.deepcopy(self.boundary.value['gui'])
        self.native.user = NS(IsChild=lambda parent,child:False)
        self.control = NS(element_info=NS(_element=self.file))
        self.boundary.target_snapshot = self.native.target_snapshot
        self.record = {}

    def action(self, *, keyboard=False):
        if keyboard:
            self.record['attachments'] = [dict(hwnd=11,parent=55,child=56,officePid=88)]
            return policy.send_host_menu_shortcut(object(),self.process,11,self.control,self.record,
                shortcut='CTRL_S',caption='OpenGeul Writer — 다른 이름으로 저장',
                probe=self.boundary,clock=self.clock)
        return policy.click_owned_control(object(),self.process,11,self.control,self.record,
            purpose='FILE_MENU',probe=self.boundary,clock=self.clock)

    def no_input(self):
        self.assertNotIn('move',self.boundary.calls)
        self.assertNotIn('click',self.boundary.calls)
        self.assertFalse(any(isinstance(v,tuple) and v[0]=='send' for v in self.boundary.calls))

    def test_long_unrelated_focused_name_and_automation_do_not_block_one_file_click(self):
        self.focus.values.update(CurrentName='private-document-name-'*200,
                                 CurrentAutomationId='unrelated-focus-automation-'*200)
        value = None; error = None
        try:value = self.action()
        except BaseException as exc:error = exc
        self.assertIsNone(error,'Unconsumed focus metadata still blocks the original File click')
        self.assertTrue(value['success'])
        self.assertEqual((value['clickAttempts'],value['requestedInputs'],value['insertedInputs']),(1,2,2))
        self.assertNotIn('CurrentName',self.focus.reads)
        self.assertNotIn('CurrentAutomationId',self.focus.reads)

    def test_throwing_unrelated_focus_properties_are_never_queried_through_real_target(self):
        for name in ['CurrentName','CurrentAutomationId','CurrentBoundingRectangle','CurrentIsOffscreen','CurrentIsEnabled']:
            self.focus.errors[name] = OSError('Unconsumed focused property was queried')
        value = None; error = None
        try:value = self.action(keyboard=True)
        except BaseException as exc:error = exc
        self.assertIsNone(error,'Focused identity walk read unrelated metadata')
        self.assertTrue(value['success'])
        self.assertEqual((value['requestedInputs'],value['insertedInputs']),(4,4))
        self.assertEqual(set(value['before']['focusAncestry'][0]),{'runtimeId','pid','nativeHwnd','controlType'})
        self.assertEqual(set(self.focus.reads),{'CurrentNativeWindowHandle','CurrentProcessId','CurrentControlType','GetRuntimeId'})

    def test_actual_target_long_name_or_automation_remains_fatal_before_input(self):
        for field in ['CurrentName','CurrentAutomationId']:
            with self.subTest(field=field):
                self.file.values[field] = 'x'*257
                with self.assertRaises(AssertionError):self.action()
                self.no_input()
                self.file.values[field] = '파일' if field=='CurrentName' else ''

    def test_actual_target_rectangle_exception_is_not_hidden(self):
        self.file.errors['CurrentBoundingRectangle'] = OSError('target geometry failed')
        with self.assertRaisesRegex(OSError,'target geometry failed'):self.action()
        self.no_input()

    def test_actual_target_ancestry_metadata_bound_is_unchanged(self):
        self.bar.values['CurrentName'] = 'x'*257
        with self.assertRaises(AssertionError):self.action()
        self.no_input()

    def test_invalid_focused_runtime_ids_remain_fatal_with_bounded_field_diagnostics(self):
        for runtime in ([], list(range(65)), [True], [2**31], [-2**31-1], ['42']):
            with self.subTest(runtime=runtime):
                self.focus.runtime = runtime
                with self.assertRaises(AssertionError) as failure:self.action()
                self.assertIn('focused identity',str(failure.exception).lower())
                self.assertIn('runtime',str(failure.exception).lower())
                self.assertLess(len(str(failure.exception)),256)
                self.no_input()

    def test_invalid_native_handle_pid_or_control_type_is_not_coerced(self):
        bad = [('CurrentNativeWindowHandle',False),('CurrentNativeWindowHandle',1.0),
               ('CurrentNativeWindowHandle',2**32),('CurrentNativeWindowHandle',-2**31-1),
               ('CurrentProcessId',True),('CurrentProcessId',0),('CurrentProcessId',2**32),
               ('CurrentProcessId','77'),('CurrentControlType',True),
               ('CurrentControlType',0),('CurrentControlType',2**31)]
        for name,value in bad:
            with self.subTest(name=name,value=value):
                original = self.focus.values[name];self.focus.values[name] = value
                with self.assertRaises(AssertionError) as failure:self.action(keyboard=True)
                self.assertIn('focused identity',str(failure.exception).lower())
                self.assertLess(len(str(failure.exception)),256)
                self.no_input();self.focus.values[name] = original

    def test_null_native_handle_and_exact_signed_runtime_boundary_keep_other_guards(self):
        self.focus.values['CurrentNativeWindowHandle'] = None
        self.focus.runtime = [-2**31, 2**31-1]
        value = self.action(keyboard=True)
        self.assertTrue(value['success'])
        self.assertEqual(value['before']['focusAncestry'][0]['nativeHwnd'],0)
        self.assertEqual(value['before']['focusAncestry'][0]['runtimeId'],self.focus.runtime)

    def test_foreign_focused_pid_is_still_rejected_by_real_host_menu_guard(self):
        self.focus.values['CurrentProcessId'] = 999
        with self.assertRaises(AssertionError):self.action(keyboard=True)
        self.no_input()

    def test_failed_target_root_native_capture_and_foreign_focus_root_reject_before_input(self):
        for kind in ['uia-root','capture','native-root']:
            with self.subTest(kind=kind):
                if kind=='uia-root':self.file.parent = None
                elif kind=='capture':self.boundary.value['gui']['captureHwnd'] = 999
                else:self.boundary.value['gui']['focusRootHwnd'] = 999
                with self.assertRaises(AssertionError):self.action()
                self.no_input();self.file.parent=self.bar
                self.boundary.value['gui'].update(captureHwnd=0,focusRootHwnd=11)

    def test_identity_provider_error_remains_fatal_without_metadata_fallback(self):
        self.focus.errors['CurrentProcessId'] = OSError('focused identity provider failure')
        with self.assertRaisesRegex(OSError,'focused identity provider failure'):self.action()
        self.no_input()

    def test_focus_identity_query_cannot_renew_original_action_deadline(self):
        self.focus.on_runtime = lambda:setattr(self.clock,'now',6.)
        with self.assertRaisesRegex(AssertionError,'deadline'):self.action()
        self.no_input()
        self.assertEqual(self.native.deadline,6.)


if __name__ == '__main__':
    unittest.main()
