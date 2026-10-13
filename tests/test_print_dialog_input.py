"""Actual native Print dispatch with only the Windows boundary substituted."""
import ast
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from test_print_native_input import Probe

ROOT = Path(__file__).resolve().parents[1]


class Button:
    handle = 301
    def __init__(self, probe):
        self.probe = probe; self.inputs = []; self.caption = '&Print'; self.error = None
    def process_id(self): return 20
    def class_name(self): return 'Button'
    def control_id(self): return 1
    def is_visible(self): return True
    def is_enabled(self): return True
    def window_text(self): return self.caption
    def rectangle(self): return types.SimpleNamespace(left=10, top=20, right=50, bottom=60)
    def click_input(self):
        self.inputs.append((self.handle, self.probe.foreground_hwnd))
        if self.error: raise self.error


class Dialog:
    handle = 300
    def __init__(self, button): self.button = button
    def process_id(self): return 20
    def class_name(self): return '#32770'
    def window_text(self): return 'Print'
    def children(self, **filters): return [self.button]
    def descendants(self, **filters): return [self.button]


class NativePrintDialogInputTests(unittest.TestCase):
    def setUp(self):
        self.probe = Probe(); self.probe.parents[301] = 300
        self.probe.windows[100] = dict(hwnd=100, pid=10, tid=11, cls='Tauri Window',
            root=100, owners=[], visible=True, enabled=False)
        self.button = Button(self.probe); self.dialog = Dialog(self.button)
        self.runtime = {'nativeArchitecture': {'processId': 10, 'architecture': 'arm64'},
            'webview2Native': {'rootProcessId': 10, 'processes': [{'processId': 20, 'parentProcessId': 10}]}}
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('print_focus_boundary', ROOT/'e2e/print_focus.py')
        focus = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'pywinauto': types.SimpleNamespace(Desktop=None)}):
            spec.loader.exec_module(focus)
        self.module = None
        target = ROOT/'e2e/print_dialog_input.py'
        if target.exists():
            spec = importlib.util.spec_from_file_location('owned_print_dispatch', target)
            self.module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {'print_focus': focus}): spec.loader.exec_module(self.module)
        tree = ast.parse((ROOT/'e2e/virtual_print.py').read_text(encoding='utf8'))
        control = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'control')
        self.legacy_scope = {}
        exec(compile(ast.Module(body=[control], type_ignores=[]), 'actual-native-control', 'exec'), self.legacy_scope)

    def call(self):
        if self.module is None:
            # Execute the old physical input for behavioral RED, not an import failure.
            return self.legacy_scope['control'](self.dialog, 'Button', 1).click_input()
        return self.module.click_owned_print_dialog(self.dialog, 10, self.runtime,
            app_handle=77, evidence_dir=self.folder, probe=self.probe)

    def diagnostic(self):
        p = self.folder/'print-native-dispatch-diagnostic.json'
        self.assertTrue(p.is_file()); self.assertLessEqual(p.stat().st_size, 8192)
        return json.loads(p.read_bytes())

    def reject(self):
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])
        self.assertFalse(self.diagnostic()['passed']); self.assertTrue(self.probe.closed)

    def test_verified_webview_dialog_activates_once_and_dispatches_once(self):
        self.call()
        self.assertEqual(self.button.inputs, [(301, 300)])
        self.assertEqual(self.probe.activations, [300]); self.assertEqual(self.probe.barriers, [300])
        data = self.diagnostic(); self.assertTrue(data['passed']); self.assertEqual(data['phase'], 'print-dispatched')
        self.assertEqual(data['hitHwnd'], 301); self.assertEqual(data['hitHwndAtInput'], 301)
        self.assertEqual(data['physicalClickAttempts'], 1); self.assertFalse(data['sourceQualified'])

    def test_already_exact_foreground_needs_no_activation_or_barrier(self):
        self.probe.foreground_hwnd = 300; self.call()
        self.assertEqual(self.button.inputs, [(301, 300)]); self.assertEqual(self.probe.activations, [])
        self.assertEqual(self.probe.barriers, [])

    def test_foreign_overlay_and_same_dialog_sibling_receive_zero_input(self):
        for hit in (999, 302):
            with self.subTest(hit=hit):
                self.setUp(); self.probe.hit_hwnd = hit; self.reject()
                self.assertEqual(self.diagnostic()['hitHwnd'], hit)

    def test_overlay_arriving_at_final_global_hit_receives_zero_input(self):
        hits = []
        def hit(point): hits.append(point); return 301 if len(hits) == 1 else 999
        self.probe.hit = hit; self.reject()
        self.assertEqual(len(hits), 2); self.assertEqual(self.diagnostic()['hitHwndAtInput'], 999)

    def test_changed_held_process_window_owner_or_rectangle_during_hit_receives_zero_input(self):
        for change in ('pid-reuse', 'dialog-tid', 'button-tid', 'owner', 'rectangle', 'foreground'):
            with self.subTest(change=change):
                self.setUp()
                def hit(point):
                    if change == 'pid-reuse': self.probe.processes[20]['creation'] += 1
                    elif change == 'dialog-tid': self.probe.windows[300]['tid'] += 1
                    elif change == 'button-tid': self.probe.windows[301]['tid'] += 1
                    elif change == 'owner': self.probe.windows[100]['tid'] += 1
                    elif change == 'rectangle': self.button.rectangle = lambda: types.SimpleNamespace(left=20, top=20, right=50, bottom=60)
                    else: self.probe.foreground_hwnd = 999
                    return 301
                self.probe.hit = hit; self.reject()

    def test_foreground_change_during_final_hit_receives_zero_input(self):
        hits = []
        def hit(point):
            hits.append(point)
            if len(hits) == 2: self.probe.foreground_hwnd = 999
            return 301
        self.probe.hit = hit; self.reject()
        self.assertEqual(len(hits), 2)

    def test_foreign_or_changed_native_window_and_non_direct_button_reject(self):
        for kind in ('dialog-pid', 'dialog-root', 'dialog-class', 'button-pid', 'button-tid', 'button-root', 'hidden', 'disabled', 'parent', 'owner-pid', 'no-owner', 'closed'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'dialog-pid': self.probe.windows[300]['pid'] = 99
                elif kind == 'dialog-root': self.probe.windows[300]['root'] = 999
                elif kind == 'dialog-class': self.probe.windows[300]['cls'] = 'foreign'
                elif kind == 'button-pid': self.probe.windows[301]['pid'] = 99
                elif kind == 'button-tid': self.probe.windows[301]['tid'] = 99
                elif kind == 'button-root': self.probe.windows[301]['root'] = 999
                elif kind == 'hidden': self.probe.windows[301]['visible'] = False
                elif kind == 'disabled': self.probe.windows[301]['enabled'] = False
                elif kind == 'parent': self.probe.parents[301] = 302
                elif kind == 'owner-pid': self.probe.windows[100]['pid'] = 99
                elif kind == 'no-owner': self.probe.windows[300]['owners'] = []
                else: del self.probe.windows[300]
                self.reject(); self.assertEqual(self.probe.activations, [])

    def test_wrong_app_or_recycled_ancestry_rejects_before_activation(self):
        for kind in ('wrong-app', 'foreign-parent', 'cycle', 'duplicate', 'older-child', 'missing-app-handle'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'wrong-app': self.runtime['nativeArchitecture']['processId'] = 99
                elif kind == 'foreign-parent': self.runtime['webview2Native']['processes'][0]['parentProcessId'] = 99
                elif kind == 'cycle': self.runtime['webview2Native']['processes'][0]['parentProcessId'] = 20
                elif kind == 'duplicate': self.runtime['webview2Native']['processes'].append(self.runtime['webview2Native']['processes'][0])
                elif kind == 'older-child': self.probe.processes[20]['creation'] = 99
                elif self.module is not None:
                    with self.assertRaises(AssertionError): self.module.click_owned_print_dialog(self.dialog, 10, self.runtime,
                        app_handle=None, evidence_dir=self.folder, probe=self.probe)
                    self.assertEqual(self.button.inputs, []); continue
                self.reject(); self.assertEqual(self.probe.activations, [])

    def test_wrong_caption_and_ambiguous_direct_button_reject_without_opaque_text(self):
        opaque = 'secret https://example.invalid/opaque?token=secret'
        for caption in ('Cancel', 'Apply', opaque):
            with self.subTest(caption=caption):
                self.setUp(); self.button.caption = caption; self.reject()
                self.assertNotIn('secret', json.dumps(self.diagnostic()))
        self.setUp(); self.dialog.children = lambda **filters: [self.button, self.button]; self.reject()

    def test_rejected_activation_barrier_and_foreign_after_barrier_do_not_retry(self):
        for kind in ('activation', 'barrier', 'foreground'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'activation': self.probe.activation_result = False
                elif kind == 'barrier': self.probe.barrier_result = False
                else:
                    def barrier(*args): self.probe.foreground_hwnd = 999; return True
                    self.probe.sync_activation = barrier
                self.reject(); self.assertEqual(self.probe.activations, [300])
                self.assertLessEqual(len(self.probe.barriers), 1)

    def test_dispatch_error_escapes_once_and_message_is_not_persisted(self):
        self.button.error = OSError('secret https://example.invalid/opaque?token=secret')
        with self.assertRaises(OSError): self.call()
        self.assertEqual(self.button.inputs, [(301, 300)])
        data = self.diagnostic(); self.assertFalse(data['passed']); self.assertEqual(data['errorType'], 'OSError')
        self.assertEqual(data['physicalClickAttempts'], 1); self.assertNotIn('secret', json.dumps(data))

    def test_successful_click_can_close_print_and_activate_save_without_second_click(self):
        original = self.button.click_input
        def click(): original(); del self.probe.windows[300]; self.probe.foreground_hwnd = 400
        self.button.click_input = click; self.call()
        self.assertEqual(self.button.inputs, [(301, 300)]); self.assertTrue(self.diagnostic()['passed'])
        self.assertEqual(self.diagnostic()['foregroundAfter'], 400)

    def test_actual_print_document_routes_runtime_and_held_handle_through_guard_before_save(self):
        tree = ast.parse((ROOT/'e2e/virtual_print.py').read_text(encoding='utf8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'print_document')
        source = self.folder/'fixture.hwpx'; source.write_bytes(b'synthetic fixture')
        output = self.folder/'case'; seen = []; saves = []
        class Queue:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def jobs(self): return []
        def session(mode, folder, source, **kwargs):
            folder.mkdir(); (folder/'runtime.json').write_text(json.dumps(self.runtime))
            return types.SimpleNamespace(proc=types.SimpleNamespace(pid=10, _handle=77))
        def guarded(dialog, pid, runtime, **kwargs):
            seen.append((dialog, pid, runtime, kwargs))
            self.assertEqual(kwargs, {'app_handle': 77, 'evidence_dir': output})
            return self.module.click_owned_print_dialog(dialog, pid, runtime, probe=self.probe, **kwargs)
        def save(*args): saves.append(args); raise AssertionError('unguarded legacy dispatch reached Save wait')
        scope = {'ExitStack': ExitStack, 'shutil': shutil, 'json': json, 'VirtualQueue': Queue, 'Session': session,
            'digest': lambda p: hashlib.sha256(p.read_bytes()).hexdigest(), 'stop_session': lambda *a: None,
            'capture_failure': lambda *a: False, 'system_dialog': lambda *a: self.dialog,
            'configure_media': lambda *a, **kw: None, 'snapshot': lambda *a: None,
            'control': self.legacy_scope['control'], 'click_owned_print_dialog': guarded, 'save_print_output': save}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'actual-print-document', 'exec'), scope)
        self.probe.hit_hwnd = 999
        with self.assertRaises(AssertionError): scope['print_document'](Path('OpenGeul.exe'), source, {'pages': [{}]}, output)
        self.assertEqual(len(seen), 1); self.assertEqual(seen[0][:3], (self.dialog, 10, self.runtime))
        self.assertEqual(self.button.inputs, []); self.assertEqual(saves, [])
        self.assertTrue(json.loads((output/'source-preservation.json').read_bytes())['unchanged'])


if __name__ == '__main__': unittest.main()
