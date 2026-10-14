"""Offline native-interface harness; never starts Windows, Explorer or the app."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path, PureWindowsPath
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
import native_controls


class Probe:
    def __init__(self):
        self.root = {'hwnd': 10, 'root': 10, 'pid': 303, 'tid': 91,
                     'cls': 'CabinetWClass', 'visible': True, 'enabled': True, 'owners': []}
        self.child = {**self.root, 'hwnd': 11, 'cls': 'DirectUIHWND'}
        self.foreground_hwnd = 10
        self.root_reads = 0
        self.mutate_second = None
        self.process_changed = False
        self.events = []
    def verify_process(self, pid, record):
        self.events.append('process')
        if self.process_changed or pid != 303 or record != {'creation': 123, 'session': 1}:
            raise AssertionError('Held process changed')
    def window(self, hwnd):
        self.events.append('window')
        if hwnd == 10:
            self.root_reads += 1
            if self.root_reads == 2 and self.mutate_second:
                self.root.update(self.mutate_second)
            return copy.deepcopy(self.root)
        if hwnd == 11: return copy.deepcopy(self.child)
        raise AssertionError('Dead HWND')
    def hit(self, point):
        self.events.append('hit')
        return 11
    def foreground(self): return self.foreground_hwnd


class Item:
    def __init__(self):
        self.pid = 303; self.visible = True; self.enabled = True
        self.runtime = [42, 5]
        self.bounds = [20, 40, 80, 80]
        self.element_info = SimpleNamespace(element=SimpleNamespace(GetRuntimeId=lambda: self.runtime))
    def process_id(self): return self.pid
    def is_visible(self): return self.visible
    def is_enabled(self): return self.enabled
    def rectangle(self):
        return SimpleNamespace(**dict(zip(('left', 'top', 'right', 'bottom'), self.bounds)))


class DriverProbe(Probe):
    def __init__(self):
        super().__init__()
        self.app = {'hwnd': 20, 'root': 20, 'pid': 202, 'tid': 92, 'cls': 'Tauri Window',
                    'visible': True, 'enabled': True, 'owners': []}
        self.app_child = {**self.app, 'hwnd': 21, 'cls': 'Chrome_RenderWidgetHostHWND'}
        self.process = SimpleNamespace(inspect=lambda pid: {'imagePath': '/Windows/explorer.exe'})
        self.closed = False
    def window(self, hwnd):
        if hwnd in (20, 21): return copy.deepcopy(self.app if hwnd == 20 else self.app_child)
        return super().window(hwnd)
    def hit(self, point): return 11 if point[0] < 500 else 21
    def bind_process(self, pid, proof): return {'creation': 123, 'session': 1}
    def verify_process(self, pid, record):
        if pid == 202: return
        return super().verify_process(pid, record)
    def close(self): self.closed = True


class ExplorerDriverTests(unittest.TestCase):
    def run_driver(self, *, wrong_point=False, wrong_readback=False, wrong_cleanup_thread=False):
        import driver
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        source = Path(folder.name)/'owned-fixtures'/'owned-drop.hwpx'
        source.parent.mkdir(); source.write_bytes(b'owned')
        probe = DriverProbe()
        if wrong_point: probe.child['pid'] = 999
        state = {'started': False, 'selected': [], 'clock': 0}
        self.inputs = []; self.probe = probe; self.folder = Path(folder.name)
        class Window:
            def __init__(self, hwnd, pid): self.handle = hwnd; self.pid = pid; self.closed = False
            def process_id(self): return self.pid
            def class_name(self): return 'Tauri Window' if self.pid == 202 else 'CabinetWClass'
            def is_visible(self): return True
            def is_enabled(self): return True
            def set_focus(self): probe.foreground_hwnd = self.handle
            def move_window(self, **kwargs): pass
            def client_to_screen(self, point): return point
            def close(self): self.closed = True
            def wrapper_object(self): return self
        explorer = Window(10, 303); app = Window(20, 202); self.explorer = explorer
        item = Item(); item.window_text = lambda: source.name
        def old_unbound_click():
            self.inputs.append(('unbound-selection', None)); state['selected'] = [str(source)]
        item.click_input = old_unbound_click
        def shell_rows(*args, **kwargs):
            rows = [{'hwnd': 10, 'path': str(source.parent), 'selected': state['selected']}] if state['started'] else []
            return SimpleNamespace(returncode=0, stdout=json.dumps(rows))
        def launch(*args, **kwargs): state['started'] = True
        def physical_click(*, coords):
            self.inputs.append(('selection', coords))
            state['selected'] = [str(source.parent/'owned-invalid.hwpx' if wrong_readback else source)]
        def release(**kwargs):
            self.inputs.append(('release', kwargs['coords']))
            if wrong_cleanup_thread: probe.root['tid'] = 999
        mouse = SimpleNamespace(click=physical_click,
            press=lambda **kwargs: self.inputs.append(('press', kwargs['coords'])),
            move=lambda **kwargs: self.inputs.append(('move', kwargs['coords'])),
            release=release)
        desktop = SimpleNamespace(window=lambda **kwargs: explorer, windows=lambda **kwargs: [app])
        def advance(seconds): state['clock'] += seconds
        session = driver.Session.__new__(driver.Session)
        session.mode = 'native'; session.folder = self.folder; session.proc = SimpleNamespace(pid=202, _handle=1)
        session.native_architecture = {'architecture': 'x64'}
        session.page = SimpleNamespace(locator=lambda selector: SimpleNamespace(
            bounding_box=lambda: {'x': 800, 'y': 100, 'width': 200, 'height': 200}),
            evaluate=lambda script: 1, wait_for_timeout=lambda ms: advance(ms/1000))
        (self.folder/'runtime.json').write_text('{}')
        modules = {'pywinauto': SimpleNamespace(Desktop=lambda **kwargs: desktop, mouse=mouse),
                   'print_focus': SimpleNamespace(WindowsFocusProbe=lambda: probe,
                       _bind_native_print_processes=lambda *args: ({202: {}}, lambda pid: None)),
                   'uia_snapshot': SimpleNamespace(snapshot_descendants=lambda *args, **kwargs: [item])}
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, modules))
            stack.enter_context(patch.object(driver, 'os', SimpleNamespace(name='nt')))
            stack.enter_context(patch.object(driver, 'subprocess', SimpleNamespace(run=shell_rows, Popen=launch)))
            stack.enter_context(patch.object(driver, 'verify_process', return_value={'architecture': 'x64'}))
            stack.enter_context(patch.object(driver, 'time', SimpleNamespace(monotonic=lambda: state['clock'], sleep=advance)))
            return session.explorer_drop(source)

    def test_driver_connects_verified_selection_to_one_real_drag_flow(self):
        result = self.run_driver()
        self.assertTrue(result['actualPhysicalDrag'])
        self.assertEqual([kind for kind, _ in self.inputs].count('selection'), 1)
        self.assertEqual([kind for kind, _ in self.inputs].count('press'), 1)
        self.assertEqual([kind for kind, _ in self.inputs].count('move'), 20)
        self.assertEqual([kind for kind, _ in self.inputs].count('release'), 1)
        self.assertNotIn('unbound-selection', [kind for kind, _ in self.inputs])
        self.assertTrue(self.probe.closed)

    def test_driver_wrong_point_fails_before_selection_and_writes_bound_metadata(self):
        with self.assertRaises(AssertionError): self.run_driver(wrong_point=True)
        self.assertEqual(self.inputs, [])
        diagnostic = json.loads((self.folder/'native-explorer-ownership.json').read_text())
        self.assertEqual(diagnostic['foreground'], 10)
        self.assertEqual(diagnostic['hit']['pid'], 999)
        self.assertEqual(diagnostic['point'], [50, 60])
        self.assertTrue(self.probe.closed)

    def test_driver_wrong_readback_has_one_selection_no_drag_and_owned_diagnostic(self):
        with self.assertRaises(AssertionError): self.run_driver(wrong_readback=True)
        self.assertEqual([kind for kind, _ in self.inputs], ['selection'])
        diagnostic = json.loads((self.folder/'native-explorer-ownership.json').read_text())
        self.assertEqual(diagnostic['selectedCount'], 1)
        self.assertTrue(diagnostic['selected'][0]['owned'])
        self.assertTrue(diagnostic['selected'][0]['raw'].endswith('owned-invalid.hwpx'))
        self.assertTrue(self.probe.closed)

    def test_driver_diagnostic_cap_omits_oversize_owned_raw_paths(self):
        from driver import Session
        with tempfile.TemporaryDirectory() as folder:
            session = Session.__new__(Session); session.folder = Path(folder)
            diagnostic = {'stage': 'explorer-point', 'point': [50, 60], 'foreground': 10,
                          'selected': [{'owned': True, 'raw': '한'*2048}]*4}
            session._record_explorer_failure(diagnostic)
            data = (session.folder/'native-explorer-ownership.json').read_bytes()
            self.assertLessEqual(len(data), 16*1024)
            result = json.loads(data)
            self.assertTrue(result['rawOwnedPathsOmittedForSize'])
            self.assertEqual(result['point'], [50, 60])
            self.assertFalse(any('raw' in row for row in result['selected']))

    def test_diagnostic_write_failure_preserves_original_ownership_failure(self):
        original = Path.write_bytes
        def refused_diagnostic(path, data):
            if path.name == 'native-explorer-ownership.json':
                raise OSError('write refused')
            return original(path, data)
        with patch.object(Path, 'write_bytes', refused_diagnostic):
            with self.assertRaises(AssertionError): self.run_driver(wrong_point=True)
        self.assertEqual(self.inputs, [])

    def test_cleanup_does_not_close_retargeted_explorer_window(self):
        with self.assertRaises(AssertionError): self.run_driver(wrong_cleanup_thread=True)
        self.assertFalse(self.explorer.closed)
        self.assertTrue(self.probe.closed)
        diagnostic = json.loads((self.folder/'native-explorer-ownership.json').read_text())
        self.assertTrue(diagnostic['cleanupRejected'])
        self.assertTrue(diagnostic['actualPhysicalDrag'])
        self.assertEqual(diagnostic['window']['tid'], 999)


class ExplorerOwnershipTests(unittest.TestCase):
    def select(self, probe, item=None, *, diagnostic=None):
        clicks = []
        def click(point):
            probe.events.append('click'); clicks.append(point)
        self.clicks = clicks
        return native_controls.physical_explorer_selection(
            probe, 10, 303, {'creation': 123, 'session': 1}, item or Item(), click,
            diagnostic=diagnostic)

    def test_one_physical_click_follows_two_live_bindings(self):
        probe = Probe(); record = self.select(probe)
        self.assertEqual(self.clicks, [(50, 60)])
        self.assertEqual(record['foreground'], 10)
        self.assertEqual(probe.events.count('process'), 2)
        self.assertEqual(probe.events.count('hit'), 2)
        self.assertEqual(probe.events[-1], 'click')

    def test_wrong_window_pid_thread_class_and_readiness_reject_before_click(self):
        for field, value in (('hwnd', 20), ('root', 20), ('pid', 999), ('tid', 0),
                             ('cls', 'Tauri Window'), ('visible', False), ('enabled', False)):
            with self.subTest(field=field):
                probe = Probe(); probe.root[field] = value
                with self.assertRaises(AssertionError): self.select(probe)
                self.assertEqual(self.clicks, [])

    def test_wrong_point_owner_and_foreground_reject_before_click(self):
        for field, value in (('root', 20), ('pid', 999), ('tid', 0), ('visible', False), ('enabled', False)):
            with self.subTest(field=field):
                probe = Probe(); probe.child[field] = value; diagnostic = {}
                with self.assertRaises(AssertionError): self.select(probe, diagnostic=diagnostic)
                self.assertEqual(self.clicks, [])
                self.assertIn('point', diagnostic); self.assertIn('hit', diagnostic)
        probe = Probe(); probe.foreground_hwnd = 20
        with self.assertRaises(AssertionError): self.select(probe)
        self.assertEqual(self.clicks, [])

    def test_item_owner_runtime_and_geometry_reject_before_click(self):
        for field, value in (('pid', 999), ('visible', False), ('enabled', False),
                             ('runtime', []), ('runtime', ['unknown']), ('bounds', [20, 40, 20, 80]),
                             ('bounds', [20, 40, 80.5, 80])):
            with self.subTest(field=field, value=value):
                item = Item(); setattr(item, field, value)
                with self.assertRaises(AssertionError): self.select(Probe(), item)
                self.assertEqual(self.clicks, [])

    def test_second_observation_rejects_thread_and_owner_substitution(self):
        for change in ({'tid': 92}, {'pid': 999}, {'hwnd': 20}):
            with self.subTest(change=change):
                probe = Probe(); probe.mutate_second = change
                with self.assertRaises(AssertionError): self.select(probe)
                self.assertEqual(self.clicks, [])

    def test_held_process_replacement_rejects_before_click(self):
        probe = Probe(); probe.process_changed = True
        with self.assertRaises(AssertionError): self.select(probe)
        self.assertEqual(self.clicks, [])

    def readback_helper(self):
        helper = getattr(native_controls, 'require_explorer_selection', None)
        self.assertIsNotNone(helper, 'Actual selected-path readback gate is missing')
        return helper

    def test_actual_single_selected_owned_path_is_accepted(self):
        readback = self.readback_helper()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'owned-drop.hwpx'; target.write_bytes(b'owned')
            row = {'hwnd': 10, 'path': folder, 'selected': [str(target)]}
            self.assertEqual(readback(row, target, 10), row)

    def test_selected_local_dos_alias_case_matches_and_malicious_prefix_does_not(self):
        readback = self.readback_helper()
        # Offline Windows path/stat interface only; no native product evidence.
        class OfflineDosFile(PureWindowsPath):
            def resolve(self): return self
            def is_file(self): return self.name.lower() == 'owned-drop.hwpx'
        import ui_contract
        with patch.object(ui_contract, 'Path', OfflineDosFile), \
                patch.object(ui_contract, 'os', SimpleNamespace(name='nt')):
            target = r'D:\owned\fixtures\owned-drop.hwpx'
            row = {'hwnd': 10, 'path': r'\\?\d:\OWNED\FIXTURES',
                   'selected': [r'\\?\d:\Owned\Fixtures\OWNED-DROP.HWPX']}
            self.assertEqual(readback(row, target, 10), row)
            for raw in (r'\\?\D:\owned\private.hwpx', r'\\?\UNC\host\share\owned-drop.hwpx',
                        r'\\.\D:\owned\fixtures\owned-drop.hwpx', r'D:\owned\fixtures\owned-drop.hwpx:stream',
                        r'\\?\D:\owned\fixtures\..\owned-drop.hwpx'):
                with self.subTest(raw=raw), self.assertRaises(AssertionError):
                    readback({**row, 'selected': [raw]}, target, 10)

    def test_wrong_empty_duplicate_window_folder_and_path_readbacks_are_rejected(self):
        readback = self.readback_helper()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'owned-drop.hwpx'; target.write_bytes(b'owned')
            good = {'hwnd': 10, 'path': folder, 'selected': [str(target)]}
            bad = [None, {**good, 'hwnd': 20}, {**good, 'path': str(Path(folder).parent)},
                   {**good, 'selected': []}, {**good, 'selected': [str(target), str(target)]},
                   {**good, 'selected': [str(Path(folder)/'another.hwpx')]},
                   {**good, 'selected': ['relative.hwpx']}, {**good, 'selected': [None]}]
            for row in bad:
                with self.subTest(row=row), self.assertRaises(AssertionError):
                    readback(row, target, 10)

    def test_unowned_readback_diagnostic_is_bounded_and_private_path_is_redacted(self):
        readback = self.readback_helper()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'owned-drop.hwpx'; target.write_bytes(b'owned')
            private = str(Path(folder).parent/'PRIVATE-document.hwpx')
            diagnostic = {}
            with self.assertRaises(AssertionError):
                readback({'hwnd': 10, 'path': folder, 'selected': [private]*101}, target, 10,
                              diagnostic=diagnostic)
            self.assertEqual(diagnostic['selectedCount'], 101)
            self.assertNotIn(private, str(diagnostic))
            self.assertLess(len(str(diagnostic)), 4096)
            diagnostic = {}
            with self.assertRaises(AssertionError):
                readback({'hwnd': 10, 'path': folder, 'selected': [private]}, target, 10,
                              diagnostic=diagnostic)
            self.assertNotIn(private, str(diagnostic))
            self.assertEqual(diagnostic['selected'][0]['owned'], False)

    def test_wrong_owned_readback_keeps_exact_raw_owned_diagnostic(self):
        readback = self.readback_helper()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'owned-drop.hwpx'; target.write_bytes(b'owned')
            other = str(Path(folder)/'owned-invalid.hwpx'); diagnostic = {}
            with self.assertRaises(AssertionError):
                readback({'hwnd': 10, 'path': folder, 'selected': [other]}, target, 10,
                              diagnostic=diagnostic)
            self.assertEqual(diagnostic['selected'], [{'owned': True, 'raw': other}])


if __name__ == '__main__': unittest.main()
