"""Owned activation policy/typed boundaries; no Windows runtime qualification."""
import copy
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class ActivationCallerRegression(unittest.TestCase):
    def test_home_activates_owned_caption_before_the_single_qualified_tile_click(self):
        import home_routing_smoke as home
        from test_base_save_readiness import NativeBoundary
        boundary = NativeBoundary([lambda b: [b.save]])
        boundary.root.CurrentNativeWindowHandle = 11
        boundary.save.CurrentName = 'OpenGeul Calc'
        boundary.api.user.GetAncestor = lambda hwnd, flag: 11
        boundary.api.user.IsChild = lambda parent, child: (parent, child) == (11, 102)
        def forbidden():
            raise RuntimeError('SetForegroundWindow denied before physical Home action')
        window = NS(element_info=NS(_element=boundary.root), set_focus=forbidden)
        modules = boundary.modules()
        modules['pywinauto'] = NS(Desktop=lambda backend: NS(window=lambda handle: NS(wrapper_object=lambda: window)))
        modules['pywinauto.controls.uiawrapper'] = NS(UIAWrapper=lambda info: NS(
            element_info=info, click_input=lambda: boundary.calls.append(('tile-click',))))
        record = {}; failure = None; activations = []
        def activate(api, process, hwnd, result):
            activations.append((process, hwnd, result))
        with patch.dict(sys.modules, modules), patch.object(home.native, 'activate_owned_suite', activate, create=True):
            try:
                home.click_home_action(boundary.api, boundary.process, 11, 'calc', record)
            except RuntimeError as exc:
                failure = str(exc)
        self.assertIsNone(failure, 'Home still depends on the denied programmatic foreground call')
        self.assertEqual([(p, h) for p, h, _ in activations], [(boundary.process, 11)])
        self.assertEqual([row[0] for row in boundary.calls].count('tile-click'), 1)
        self.assertEqual(record['homeActions'][0]['clicks'], 1)


class Clock:
    def __init__(self): self.now = 1.
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Probe:
    def __init__(self, process, clock):
        self.process, self.clock = process, clock
        self.foreground_root = 99
        self.row = dict(hwnd=11, pid=77, threadId=9, rootHwnd=11,
                        visible=True, enabled=True, cloaked=0, iconic=False,
                        rectangle=[0, 0, 1024, 720])
        self.identity = dict(pid=77, handleValue=2**40, creationTime=134370086799550953,
                             image=str(process.opengeul_suite_root / 'OpenGeul.Office.exe'), waitResult=258)
        self.calls = []; self.hit_mode = 'caption'; self.inserted = 2
        self.fail = None; self.after_move = None; self.after_click = None
    def enter_dpi(self, receipt):
        self.calls.append('dpi-enter')
        if self.fail == 'dpi-enter': raise OSError('DPI entry failed')
        receipt.update(previousContext=123, verified=True)
    def restore_dpi(self, receipt):
        self.calls.append('dpi-restore'); receipt['restored'] = self.fail != 'dpi-restore'
        if self.fail == 'dpi-restore': raise OSError('DPI restoration failed')
    def process_snapshot(self, process):
        self.calls.append('process')
        if self.fail == 'process': raise OSError('native identity query failed')
        return copy.deepcopy(self.identity)
    def window_snapshot(self, hwnd):
        self.calls.append('window')
        if self.fail == 'window': raise OSError('native window query failed')
        return copy.deepcopy(self.row)
    def foreground(self):
        self.calls.append('foreground'); return self.foreground_root
    def caption(self, hwnd):
        self.calls.append('caption')
        return dict(rectangle=[8, 8, 1016, 32], state=0)
    def point_snapshot(self, hwnd, point):
        self.calls.append('hit')
        return dict(point=list(point), hitHwnd=11 if self.hit_mode != 'foreign' else 99,
                    rootHwnd=11 if self.hit_mode != 'foreign' else 99, pid=77,
                    hitTest=2 if self.hit_mode == 'caption' else 1)
    def move(self, point, receipt):
        self.calls.append('move'); receipt.update(pointerMoveAttempts=1, pointerReadback=list(point))
        if self.after_move: self.after_move()
    def click(self, receipt):
        self.calls.append('click')
        # Intent must already be durable before the first mouse button effect.
        intent = list(self.process.opengeul_evidence_output.glob('*-click-intent.json'))
        assert len(intent) == 1 and json.loads(intent[0].read_bytes())['clickAttempts'] == 1
        receipt.update(requestedInputs=2, insertedInputs=self.inserted, clickCompleted=self.inserted == 2)
        if self.inserted != 2:
            receipt['ownedButtonRelease'] = dict(requested=int(self.inserted == 1), inserted=int(self.inserted == 1))
            raise AssertionError('partial caption click insertion')
        self.foreground_root = 11
        if self.after_click: self.after_click()


class OwnedActivationPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = E2E / 'suite_window_activation.py'
        assert source.is_file(), 'Owned Suite activation policy is missing'
        spec = importlib.util.spec_from_file_location('suite_window_activation_tested', source)
        cls.mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.mod)
    def fixture(self, directory):
        output = Path(directory).resolve(); suite = output / 'Suite'; suite.mkdir()
        process = NS(pid=77, _handle=2**40, args=[str(suite / 'OpenGeul.Office.exe')],
                     opengeul_suite_root=suite, opengeul_evidence_output=output,
                     opengeul_evidence_case='owned-case', poll=lambda: None)
        clock = Clock(); probe = Probe(process, clock); record = {}
        return process, clock, probe, record
    def run_activation(self, process, clock, probe, record, seconds=1):
        def strict(hwnd):
            self.assertEqual(probe.foreground_root, hwnd, 'strict owned foreground was bypassed')
        return self.mod.activate_suite_window(strict, process, 11, record, probe=probe,
                                               clock=clock, pause=clock.sleep, seconds=seconds)
    def test_one_caption_click_has_separate_durable_receipts_and_restored_dpi(self):
        with tempfile.TemporaryDirectory() as directory:
            p, c, probe, record = self.fixture(directory)
            result = self.run_activation(p, c, probe, record)
            self.assertTrue(result['ready']); self.assertEqual(result['clickAttempts'], 1)
            self.assertEqual(probe.calls.count('click'), 1)
            self.assertTrue(result['dpiScope']['restored'])
            self.assertNotIn('homeActions', record); self.assertNotIn('navigationKeys', record)
            final, = Path(directory).glob('*-result.json')
            self.assertEqual(json.loads(final.read_bytes()), result)
    def test_already_owned_foreground_never_moves_or_clicks(self):
        with tempfile.TemporaryDirectory() as directory:
            p, c, probe, record = self.fixture(directory); probe.foreground_root = 11
            value = self.run_activation(p, c, probe, record)
            self.assertEqual(value['clickAttempts'], 0)
            self.assertFalse({'move', 'click', 'caption'} & set(probe.calls))
    def test_later_activation_cannot_replace_the_original_retained_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            p, c, probe, record = self.fixture(directory); probe.foreground_root = 11
            self.run_activation(p, c, probe, record)
            probe.identity['creationTime'] += 1
            with self.assertRaisesRegex(AssertionError, 'generation'): self.run_activation(p, c, probe, record)
            self.assertNotIn('click', probe.calls); self.assertEqual(len(record['windowActivations']), 2)
    def test_late_dpi_restoration_cannot_qualify_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            p, c, probe, record = self.fixture(directory); probe.foreground_root = 11
            original = probe.restore_dpi
            def late(receipt): original(receipt); c.now += 2
            probe.restore_dpi = late
            with self.assertRaisesRegex(AssertionError, 'deadline'): self.run_activation(p, c, probe, record)
            self.assertFalse(record['windowActivations'][0]['ready'])
    def test_generation_handle_image_and_live_state_must_match_original_popen(self):
        for key, bad in [('pid', 88), ('handleValue', 42), ('image', '/foreign.exe'), ('waitResult', 0)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                p, c, probe, record = self.fixture(directory); probe.identity[key] = bad
                with self.assertRaises(AssertionError): self.run_activation(p, c, probe, record)
                self.assertNotIn('move', probe.calls); self.assertNotIn('click', probe.calls)
                self.assertTrue(record['windowActivations'][0]['dpiScope']['restored'])
    def test_dead_hidden_disabled_cloaked_minimized_or_foreign_root_never_inputs(self):
        for key, bad in [('pid', 88), ('rootHwnd', 99), ('visible', False), ('enabled', False), ('cloaked', 1), ('iconic', True)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                p, c, probe, record = self.fixture(directory); probe.row[key] = bad
                with self.assertRaises(AssertionError): self.run_activation(p, c, probe, record)
                self.assertNotIn('move', probe.calls); self.assertNotIn('click', probe.calls)
    def test_occluded_or_noncaption_points_fail_without_click_or_cursor_move(self):
        for mode in ('foreign', 'client'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                p, c, probe, record = self.fixture(directory); probe.hit_mode = mode
                with self.assertRaisesRegex(AssertionError, 'caption'): self.run_activation(p, c, probe, record)
                self.assertNotIn('move', probe.calls); self.assertNotIn('click', probe.calls)
    def test_identity_or_hit_race_after_move_prevents_button_effect(self):
        for mutation in ('creation', 'hit', 'geometry'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                p, c, probe, record = self.fixture(directory)
                def race():
                    if mutation == 'creation': probe.identity['creationTime'] += 1
                    elif mutation == 'hit': probe.hit_mode = 'foreign'
                    else: probe.row['rectangle'][0] += 1
                probe.after_move = race
                with self.assertRaises(AssertionError): self.run_activation(p, c, probe, record)
                self.assertEqual(probe.calls.count('move'), 1); self.assertNotIn('click', probe.calls)
    def test_partial_click_is_never_repeated_or_qualified(self):
        for count in (0, 1):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                p, c, probe, record = self.fixture(directory); probe.inserted = count
                with self.assertRaisesRegex(AssertionError, 'partial'): self.run_activation(p, c, probe, record)
                value = record['windowActivations'][0]
                self.assertEqual(value['insertedInputs'], count); self.assertFalse(value['ready'])
                self.assertEqual(probe.calls.count('click'), 1)
    def test_postclick_foreground_deadline_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            p, c, probe, record = self.fixture(directory)
            probe.after_click = lambda: setattr(probe, 'foreground_root', 99)
            with self.assertRaisesRegex(AssertionError, 'foreground'): self.run_activation(p, c, probe, record)
            self.assertEqual(probe.calls.count('click'), 1); self.assertLessEqual(c.now, 2.1)
    def test_native_query_and_dpi_failures_keep_original_error_and_no_button_input(self):
        for failure in ('process', 'window', 'dpi-enter', 'dpi-restore'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                p, c, probe, record = self.fixture(directory); probe.fail = failure
                if failure == 'dpi-restore': probe.foreground_root = 11
                with self.assertRaises(OSError): self.run_activation(p, c, probe, record)
                self.assertNotIn('click', probe.calls); self.assertFalse(record['windowActivations'][0]['ready'])
    def test_signed_live_caption_geometry_and_invalid_no_area_policy(self):
        self.assertEqual(self.mod.caption_candidates([-1600, -900, 0, 0], [-1592, -892, -8, -868]),
                         [(-1196, -880), (-800, -880), (-404, -880)])
        for window, caption in [([0, 0, 10, 10], [20, 20, 30, 30]), ([0, 0, 0, 10], [0, 0, 0, 4])]:
            with self.subTest(window=window), self.assertRaises(AssertionError): self.mod.caption_candidates(window, caption)


class Function:
    def __init__(self, action=lambda *args: 1): self.action, self.calls = action, []
    def __call__(self, *args): self.calls.append(args); return self.action(*args)


class Library:
    def __getattr__(self, name):
        function = Function(); setattr(self, name, function); return function


class NativeActivationBoundary(unittest.TestCase):
    def setUp(self):
        import suite_window_activation as activation
        self.mod = activation; self.user, self.kernel, self.dwm = Library(), Library(), Library()
        self.clock = Clock()
        self.probe = activation.NativeActivationProbe(9., self.clock, user=self.user, kernel=self.kernel, dwm=self.dwm)
        self.context = 123
        def context(value):
            previous, self.context = self.context, value
            return previous
        self.user.SetThreadDpiAwarenessContext.action = context
        self.user.GetThreadDpiAwarenessContext.action = lambda: self.context
        self.user.AreDpiAwarenessContextsEqual.action = lambda a, b: a == b
    def test_win64_abi_keeps_physical_coordinates_and_opaque_handles(self):
        self.assertEqual(ctypes.sizeof(self.mod.Point), 8)
        self.assertEqual(ctypes.sizeof(self.mod.Rect), 16)
        self.assertEqual(ctypes.sizeof(self.mod.TitleBarInfo), 44)
        self.assertEqual(ctypes.sizeof(self.mod.Input), 40)
        self.assertEqual(self.user.SendInput.argtypes, (ctypes.c_uint32, ctypes.POINTER(self.mod.Input), ctypes.c_int))
        self.assertIs(self.user.WindowFromPhysicalPoint.restype, ctypes.c_void_p)
        self.assertIs(self.user.SendMessageTimeoutW.restype, ctypes.c_ssize_t)
        self.assertEqual(self.user.GetWindowThreadProcessId.argtypes[0], ctypes.c_void_p)
    def test_dpi_scope_restores_the_saved_context_after_later_query_failure(self):
        receipt = {}; self.probe.enter_dpi(receipt)
        self.assertEqual(self.context, -4)
        self.probe.restore_dpi(receipt)
        self.assertTrue(receipt['verified']); self.assertTrue(receipt['restored'])
        self.assertEqual(self.context, 123)
    def test_one_partial_native_button_insertion_releases_only_its_own_down(self):
        self.user.GetAsyncKeyState.action = lambda key: 0
        self.user.GetSystemMetrics.action = lambda key: 0
        self.user.GetPhysicalCursorPos.action = lambda value: setattr(value._obj, 'x', 20) or setattr(value._obj, 'y', 10) or 1
        self.user.SendInput.action = lambda count, payload, size: 1
        receipt = dict(chosenPhysicalPoint=[20, 10])
        with self.assertRaisesRegex(AssertionError, 'partial'): self.probe.click(receipt)
        self.assertEqual([call[0] for call in self.user.SendInput.calls], [2, 1])
        self.assertEqual(receipt['insertedInputs'], 1)
        self.assertEqual(receipt['ownedButtonRelease']['inserted'], 1)
        self.assertFalse(receipt['clickCompleted'])
    def test_preexisting_mouse_button_or_changed_cursor_prevents_native_insertion(self):
        for reason in ('held', 'cursor'):
            with self.subTest(reason=reason):
                self.user.GetAsyncKeyState.action = lambda key: 0x8000 if reason == 'held' else 0
                self.user.GetPhysicalCursorPos.action = lambda value: 1
                self.user.SendInput.calls.clear()
                with self.assertRaises(AssertionError): self.probe.click(dict(chosenPhysicalPoint=[20, 10]))
                self.assertEqual(self.user.SendInput.calls, [])
    def test_dpi_entry_overrun_still_retains_and_restores_the_changed_context(self):
        def late_context(value):
            previous, self.context = self.context, value
            self.clock.now = 10.
            return previous
        self.user.SetThreadDpiAwarenessContext.action = late_context
        value = {}
        with self.assertRaises(AssertionError): self.probe.enter_dpi(value)
        self.assertEqual(value.get('previousContext'), 123, 'A changed DPI scope was lost at the deadline')
        self.probe.restore_dpi(value)
        self.assertTrue(value['restored'])
    def test_native_partial_release_error_preserves_the_original_partial_insertion(self):
        self.user.GetAsyncKeyState.action = lambda key: 0
        self.user.GetSystemMetrics.action = lambda key: 0
        self.user.GetPhysicalCursorPos.action = lambda value: setattr(value._obj, 'x', 20) or setattr(value._obj, 'y', 10) or 1
        def insertion(count, payload, size):
            if count == 1: raise OSError('owned release failed')
            return 1
        self.user.SendInput.action = insertion
        value = dict(chosenPhysicalPoint=[20, 10])
        with self.assertRaisesRegex(AssertionError, 'partial'): self.probe.click(value)
        self.assertEqual(value['insertedInputs'], 1)
        self.assertIn('owned release failed', value['ownedButtonRelease']['error'])
    def configure_native(self, process):
        self.user.GetAncestor.action = lambda hwnd, kind: hwnd
        self.user.GetForegroundWindow.action = lambda: self.foreground
        self.foreground = 99; self.cursor = [512, 767]
        self.user.IsIconic.action = lambda hwnd: 0
        self.user.GetWindowThreadProcessId.action = lambda hwnd, pid: setattr(pid._obj, 'value', 77) or 9
        def rectangle(hwnd, output):
            output._obj.left, output._obj.top, output._obj.right, output._obj.bottom = 0, 0, 1024, 720
            return 1
        self.user.GetWindowRect.action = rectangle
        self.dwm.DwmGetWindowAttribute.action = lambda *args: 0
        def caption(hwnd, output):
            output._obj.rectangle = self.mod.Rect(8, 8, 1016, 32)
            return 1
        self.user.GetTitleBarInfo.action = caption
        self.user.WindowFromPhysicalPoint.action = lambda point: 11
        self.user.SendMessageTimeoutW.action = lambda *args: setattr(args[-1]._obj, 'value', 2) or 1
        self.user.GetPhysicalCursorPos.action = lambda output: setattr(output._obj, 'x', self.cursor[0]) or setattr(output._obj, 'y', self.cursor[1]) or 1
        self.user.SetPhysicalCursorPos.action = lambda x, y: self.cursor.__setitem__(slice(None), [x, y]) or 1
        self.user.GetAsyncKeyState.action = lambda key: 0
        self.user.GetSystemMetrics.action = lambda key: 0
        self.user.SendInput.action = lambda count, payload, size: setattr(self, 'foreground', 11) or count
        self.kernel.GetProcessId.action = lambda handle: 77
        self.kernel.WaitForSingleObject.action = lambda handle, timeout: 258
        def times(handle, creation, *rest):
            creation._obj.low = 134370086799550953 & 0xffffffff
            creation._obj.high = 134370086799550953 >> 32
            return 1
        self.kernel.GetProcessTimes.action = times
        image = str(process.opengeul_suite_root / 'OpenGeul.Office.exe')
        self.kernel.QueryFullProcessImageNameW.action = lambda handle, flags, output, length: setattr(output, 'value', image) or setattr(length._obj, 'value', len(image)) or 1
    def test_actual_typed_adapter_uses_original_handle_hit_test_and_one_serial_click(self):
        with tempfile.TemporaryDirectory() as directory:
            process, clock, _, record = OwnedActivationPolicy().fixture(directory)
            self.configure_native(process)
            result = self.mod.activate_suite_window(lambda hwnd: self.assertEqual(self.foreground, hwnd), process, 11,
                record, probe=self.probe, clock=self.clock, pause=self.clock.sleep, seconds=2)
            self.assertTrue(result['ready']); self.assertEqual(result['originalProcess']['creationTime'], 134370086799550953)
            self.assertEqual([call[0] for call in self.user.SendInput.calls], [2])
            self.assertTrue(all(call[0] == 2**40 for call in self.kernel.GetProcessId.calls))
            self.assertTrue(all(call[-2] <= 200 for call in self.user.SendMessageTimeoutW.calls))
            self.assertFalse({'SetForegroundWindow', 'SetFocus', 'AttachThreadInput'} & self.user.__dict__.keys())
    def test_typed_hit_query_failure_is_fail_closed_and_restores_dpi(self):
        with tempfile.TemporaryDirectory() as directory:
            process, clock, _, record = OwnedActivationPolicy().fixture(directory)
            self.configure_native(process); self.user.SendMessageTimeoutW.action = lambda *args: 0
            with self.assertRaisesRegex(OSError, 'WM_NCHITTEST'):
                self.mod.activate_suite_window(lambda hwnd: None, process, 11, record,
                    probe=self.probe, clock=self.clock, pause=self.clock.sleep, seconds=2)
            self.assertEqual(self.user.SendInput.calls, [])
            self.assertEqual(self.context, 123)
    def test_unknown_native_return_is_not_fabricated_as_inserted_input(self):
        self.user.GetAsyncKeyState.action = lambda key: 0
        self.user.GetSystemMetrics.action = lambda key: 0
        self.user.GetPhysicalCursorPos.action = lambda value: setattr(value._obj, 'x', 20) or setattr(value._obj, 'y', 10) or 1
        def failure(*args): raise OSError('native return unavailable')
        self.user.SendInput.action = failure
        value = dict(chosenPhysicalPoint=[20, 10])
        with self.assertRaisesRegex(OSError, 'unavailable'): self.probe.click(value)
        self.assertIsNone(value['insertedInputs']); self.assertEqual(value['inputCallAttempts'], 1)
        self.assertIn('return unavailable', value['inputCountBasis'])
        self.assertEqual(len(self.user.SendInput.calls), 1)


if __name__ == '__main__': unittest.main()
