"""Portable typed-ctypes regression for cross-loaded picker API instances."""
import ctypes
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


E2E = Path(__file__).resolve().parents[1] / 'e2e'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, E2E / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PickerGuiTypeOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = load('picker_gui_first', 'windows_smoke.py')
        cls.second = load('picker_gui_second', 'windows_smoke.py')
        cls.lifecycle = load('picker_gui_lifecycle', 'lifecycle_smoke.py')

    def provider(self, owner, *, returned=1, thread=111, pid=31, root=500,
                 live=True, class_name='Edit', focus=510, capture=0, menu=0, flags=0):
        calls = []
        signature = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_uint32,
                                     ctypes.POINTER(owner.GuiThreadInfo))

        def gui_info(tid, pointer):
            info = pointer.contents
            calls.append(dict(threadId=tid, cbSize=info.cbSize))
            info.flags = flags
            info.hwndActive = 500
            info.hwndFocus = focus
            info.hwndCapture = capture
            info.hwndMenuOwner = menu
            return returned

        callback = signature(gui_info)
        api = object.__new__(owner.Windows)
        api.user = SimpleNamespace(GetGUIThreadInfo=callback,
            GetWindowThreadProcessId=lambda handle, pointer: thread,
            IsWindow=lambda handle: live, GetAncestor=lambda handle, relation: root,
            GetForegroundWindow=lambda: 500)
        api.pid = lambda handle: pid
        api.class_name = lambda handle: class_name
        return api, calls

    def observe(self, api):
        evidence = {}
        try:
            self.lifecycle.picker_filename_context(api, 31, 500, 510, evidence)
        except ctypes.ArgumentError as error:
            self.fail('Owned picker passed another loaded module\'s structure: ' + str(error))
        return evidence

    def test_picker_accepts_each_api_owners_exact_pointer_without_rebinding(self):
        self.assertIsNot(self.first.GuiThreadInfo, self.second.GuiThreadInfo)
        for owner in (self.first, self.second):
            with self.subTest(owner=owner.__name__):
                self.assertIsNot(owner.GuiThreadInfo, self.lifecycle.native.GuiThreadInfo)
                api, calls = self.provider(owner)
                function = api.user.GetGUIThreadInfo
                before = (function.argtypes, function.restype)
                evidence = self.observe(api)
                self.assertEqual((evidence['threadId'], evidence['focusHwnd']), (111, 510))
                info = api.query_gui_thread_info(111)
                self.assertIs(type(info), owner.GuiThreadInfo)
                self.assertEqual(info.hwndFocus, 510)
                self.assertEqual(calls, [dict(threadId=111, cbSize=72)] * 2)
                self.assertIs(api.user.GetGUIThreadInfo, function)
                self.assertEqual((function.argtypes, function.restype), before)

    def test_picker_retains_fixed_layout_and_exact_native_gui_values(self):
        owner = self.first
        self.assertEqual(ctypes.sizeof(owner.GuiThreadInfo), 72)
        self.assertEqual({name: getattr(owner.GuiThreadInfo, name).offset for name in
                          ('cbSize', 'flags', 'hwndActive', 'hwndFocus', 'hwndCapture',
                           'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret', 'rcCaret')},
                         dict(cbSize=0, flags=4, hwndActive=8, hwndFocus=16, hwndCapture=24,
                              hwndMenuOwner=32, hwndMoveSize=40, hwndCaret=48, rcCaret=56))
        api, calls = self.provider(owner, capture=731, menu=732, flags=7)
        evidence = self.observe(api)
        self.assertEqual({key: evidence[key] for key in
                          ('activeHwnd', 'focusHwnd', 'captureHwnd', 'menuOwnerHwnd', 'flags')},
                         dict(activeHwnd=500, focusHwnd=510, captureHwnd=731, menuOwnerHwnd=732, flags=7))
        self.assertEqual(calls, [dict(threadId=111, cbSize=72)])

    def test_api_rejects_non_dword_positive_thread_ids_before_native_query(self):
        for tid in (0, -1, 2**32, True, 1.0, None, '111'):
            with self.subTest(tid=tid):
                api, calls = self.provider(self.first)
                try:
                    with self.assertRaises(AssertionError):
                        api.query_gui_thread_info(tid)
                except AttributeError as error:
                    self.fail('API-owned typed GUI query is missing: ' + str(error))
                self.assertEqual(calls, [])

    def test_native_gui_failure_preserves_error_before_readback_or_mutation(self):
        api, calls = self.provider(self.first, returned=0)
        with patch.object(ctypes, 'get_last_error', return_value=5, create=True):
            try:
                with self.assertRaises(OSError) as failure:
                    self.lifecycle.picker_filename_context(api, 31, 500, 510, {})
            except ctypes.ArgumentError as error:
                self.fail('Pointer collision hid the native failure: ' + str(error))
        self.assertEqual(failure.exception.errno, 5)
        self.assertIn('GetGUIThreadInfo for owned filename field failed', str(failure.exception))
        self.assertEqual(calls, [dict(threadId=111, cbSize=72)])

    def test_invalid_native_field_thread_fails_before_gui_query(self):
        for thread in (0, -1):
            with self.subTest(thread=thread):
                api, calls = self.provider(self.first, thread=thread)
                with self.assertRaisesRegex(AssertionError, 'disappeared'):
                    self.lifecycle.picker_filename_context(api, 31, 500, 510, {})
                self.assertEqual(calls, [])

    def test_foreign_or_changed_field_identity_fails_before_gui_query(self):
        for changed in (dict(pid=32), dict(root=999), dict(live=False), dict(class_name='Button')):
            with self.subTest(changed=changed):
                api, calls = self.provider(self.first, **changed)
                with self.assertRaises(AssertionError):
                    self.lifecycle.picker_filename_context(api, 31, 500, 510, {})
                self.assertEqual(calls, [])

    def test_foreign_native_focus_is_retained_and_still_rejected_before_input(self):
        api, calls = self.provider(self.first, focus=999)
        evidence = self.observe(api)
        self.assertEqual(evidence['focusHwnd'], 999)
        with self.assertRaisesRegex(AssertionError, 'outside the exact native Edit'):
            self.lifecycle.require_picker_filename_focus(evidence, 31, 500, 510, 111)
        self.assertEqual(calls, [dict(threadId=111, cbSize=72)])


if __name__ == '__main__':
    unittest.main()
