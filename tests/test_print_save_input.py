"""Owned Save dialog input; substitute only the external Windows boundary."""
import ast
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from test_print_native_input import Probe

ROOT = Path(__file__).resolve().parents[1]


class Control:
    def __init__(self, probe, hwnd, cls, identifier):
        self.probe, self.handle, self.cls, self.identifier = probe, hwnd, cls, identifier
        self.value = ''; self.inputs = []; self.error = None
    def process_id(self): return 20
    def class_name(self): return self.cls
    def control_id(self): return self.identifier
    def is_visible(self): return True
    def is_enabled(self): return True
    def parent(self): return self.combo
    def rectangle(self): return types.SimpleNamespace(left=10, top=20, right=50, bottom=60)
    def window_text(self): return self.value
    def set_edit_text(self, value):
        self.inputs.append(('edit', self.handle, self.probe.foreground_hwnd)); self.value = value
    def click_input(self):
        self.inputs.append(('click', self.handle, self.probe.foreground_hwnd))
        if self.error: raise self.error


class SaveDialog:
    handle = 300
    def __init__(self, field, button): self.field, self.button = field, button
    def process_id(self): return 20
    def class_name(self): return '#32770'
    def window_text(self): return 'Save Print Output As'
    def descendants(self, **filters):
        return [self.button] if filters else [self.field, self.button]


class PrintSaveInputTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('owned_save_test', ROOT/'e2e/print_focus.py')
        self.module = importlib.util.module_from_spec(spec)
        desktop = types.ModuleType('pywinauto'); desktop.Desktop = None
        with patch.dict(sys.modules, {'pywinauto': desktop}): spec.loader.exec_module(self.module)
        self.probe = Probe()
        self.probe.windows[100] = dict(hwnd=100, pid=10, tid=11, cls='Tauri Window',
                                      root=100, owners=[], visible=True, enabled=False)
        for hwnd, cls in ((302, 'Edit'), (303, 'ComboBox')):
            self.probe.windows[hwnd] = dict(hwnd=hwnd, pid=20, tid=21, cls=cls,
                                          root=300, owners=[100], visible=True, enabled=True)
        self.field = Control(self.probe, 302, 'Edit', 1001)
        self.field.combo = Control(self.probe, 303, 'ComboBox', 1148)
        self.button = Control(self.probe, 301, 'Button', 1)
        self.dialog = SaveDialog(self.field, self.button)
        self.runtime = {'nativeArchitecture': {'processId': 10, 'architecture': 'arm64'},
                        'webview2Native': {'rootProcessId': 10, 'processes': [
                            {'processId': 20, 'parentProcessId': 10}]}}
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name); self.output = self.folder/'printed.pdf'
        self.clock = 0
        def tick(): self.clock += .25; return self.clock
        self.module.time = types.SimpleNamespace(monotonic=tick, sleep=lambda seconds: None)

    def call(self):
        # The legacy path remains executable for a meaningful safety RED: it
        # really sends input to the wrong foreground/overlay, not a TypeError.
        fn = self.module.fill_print_output
        with patch.object(self.module, 'WindowsFocusProbe', lambda: self.probe):
            sys.path.insert(0, str(ROOT/'e2e'))
            try:
                if 'app_pid' not in inspect.signature(fn).parameters: return fn(self.dialog, self.output)
                return fn(self.dialog, self.output, 10, self.runtime, app_handle=77,
                          evidence_dir=self.folder, probe=self.probe)
            finally: sys.path.pop(0)

    def diagnostic(self):
        path = self.folder/'print-save-input-diagnostic.json'
        self.assertTrue(path.is_file()); self.assertLessEqual(path.stat().st_size, 8192)
        return json.loads(path.read_bytes())

    def reject(self):
        with self.assertRaises(AssertionError): self.call()
        self.assertEqual(self.button.inputs, [])
        self.assertFalse(self.diagnostic()['passed'])

    def test_foreign_overlay_receives_no_physical_save_input(self):
        self.probe.hit_hwnd = 999; self.reject()

    def test_foreign_foreground_after_one_owned_activation_receives_no_input(self):
        def barrier(hwnd, expected, report): self.probe.foreground_hwnd = 999; return True
        self.probe.sync_activation = barrier; self.reject()
        self.assertEqual(self.field.inputs, [])

    def test_verified_webview_child_dialog_activates_once_and_saves_once(self):
        self.call()
        self.assertEqual(self.field.inputs, [('edit', 302, 300)])
        self.assertEqual(self.button.inputs, [('click', 301, 300)])
        self.assertEqual(self.probe.activations, [300]); self.assertEqual(self.probe.barriers, [300])
        data = self.diagnostic(); self.assertTrue(data['passed']); self.assertTrue(data['pathAccepted'])
        self.assertEqual(data['dialogPid'], 20); self.assertEqual(data['hitHwnd'], 301)
        self.assertNotIn(str(self.output), json.dumps(data)); self.assertTrue(self.probe.closed)

    def test_exact_foreground_needs_no_extra_activation(self):
        self.probe.foreground_hwnd = 300; self.call()
        self.assertEqual(self.probe.activations, []); self.assertEqual(self.probe.barriers, [])
        self.assertEqual(len(self.button.inputs), 1)

    def test_foreign_or_recycled_webview_and_wrong_app_reject_before_input(self):
        for kind in ('foreign-parent', 'cycle', 'wrong-app', 'duplicate', 'creation'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'foreign-parent': self.runtime['webview2Native']['processes'][0]['parentProcessId'] = 99
                elif kind == 'cycle': self.runtime['webview2Native']['processes'][0]['parentProcessId'] = 20
                elif kind == 'wrong-app': self.runtime['nativeArchitecture']['processId'] = 99
                elif kind == 'duplicate': self.runtime['webview2Native']['processes'].append(self.runtime['webview2Native']['processes'][0])
                else: self.probe.processes[20]['creation'] = 99
                self.reject(); self.assertEqual(self.field.inputs, []); self.assertEqual(self.probe.activations, [])

    def test_closed_retargeted_or_unready_native_dialog_and_controls_reject(self):
        for hwnd, change in ((300, {'pid': 99}), (300, {'cls': 'foreign'}), (300, {'root': 999}),
                             (300, {'visible': False}), (301, {'tid': 99}), (301, {'enabled': False}),
                             (302, {'pid': 99}), (302, {'root': 999}), (303, {'tid': 99})):
            with self.subTest(hwnd=hwnd, change=change):
                self.setUp(); self.probe.windows[hwnd].update(change); self.reject()
                self.assertEqual(self.field.inputs, [])
        self.setUp(); del self.probe.windows[300]; self.reject(); self.assertEqual(self.field.inputs, [])

    def test_foreign_native_owner_rejects_before_input(self):
        self.probe.windows[100]['pid'] = 99; self.reject(); self.assertEqual(self.field.inputs, [])

    def test_path_acceptance_loses_focus_or_retargets_process_control_or_owner(self):
        for kind in ('foreground', 'creation', 'button', 'rectangle', 'owner'):
            with self.subTest(kind=kind):
                self.setUp(); original = self.field.set_edit_text
                def edit(value):
                    original(value)
                    if kind == 'foreground': self.probe.foreground_hwnd = 999
                    elif kind == 'creation': self.probe.processes[20]['creation'] += 1
                    elif kind == 'button': self.probe.windows[301]['tid'] += 1
                    elif kind == 'rectangle': self.button.rectangle = lambda: types.SimpleNamespace(left=20, top=20, right=50, bottom=60)
                    else: self.probe.windows[100]['tid'] += 1
                self.field.set_edit_text = edit; self.reject()
                self.assertEqual(len(self.field.inputs), 1)

    def test_hit_query_retargets_hwnd_or_foreground_and_receives_no_input(self):
        for kind in ('hwnd', 'foreground', 'process'):
            with self.subTest(kind=kind):
                self.setUp()
                def hit(point):
                    if kind == 'hwnd': self.probe.windows[301]['tid'] += 1
                    elif kind == 'foreground': self.probe.foreground_hwnd = 999
                    else: self.probe.processes[20]['creation'] += 1
                    return 301
                self.probe.hit = hit; self.reject()

    def test_same_dialog_sibling_at_center_is_rejected(self):
        self.probe.hit_hwnd = 302; self.reject()

    def test_overlay_arriving_during_final_liveness_recheck_receives_no_input(self):
        calls=[]
        def hit(point):
            calls.append(point); return 301 if len(calls)==1 else 999
        self.probe.hit=hit; self.reject()
        self.assertEqual(len(calls),2); self.assertEqual(self.diagnostic()['hitHwndAtInput'],999)

    def test_rejected_activation_barrier_or_path_is_not_retried(self):
        for kind in ('activation', 'barrier', 'path'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'activation': self.probe.activation_result = False
                elif kind == 'barrier': self.probe.barrier_result = False
                else: self.field.window_text = lambda: 'not accepted'
                self.reject(); self.assertLessEqual(len(self.probe.activations), 1)
                self.assertLessEqual(len(self.field.inputs), 1)

    def test_dispatch_error_is_not_retried_and_opaque_message_is_not_persisted(self):
        self.button.error = OSError('secret https://example.invalid/opaque?token=secret')
        with self.assertRaises(OSError): self.call()
        self.assertEqual(len(self.button.inputs), 1)
        data = self.diagnostic(); self.assertFalse(data['passed']); self.assertEqual(data['errorType'], 'OSError')
        self.assertNotIn('secret', json.dumps(data)); self.assertTrue(self.probe.closed)

    def test_click_can_close_dialog_without_false_failure_or_second_click(self):
        original = self.button.click_input
        def click(): original(); del self.probe.windows[300]; self.probe.foreground_hwnd = 100
        self.button.click_input = click; self.call()
        self.assertEqual(len(self.button.inputs), 1); self.assertTrue(self.diagnostic()['passed'])

    def test_owned_shell_readiness_settles_within_the_existing_budget_before_input(self):
        self.probe.foreground_hwnd=300;original=self.probe.window;reads=[]
        def window(hwnd):
            row=original(hwnd)
            if hwnd==300:
                row['enabled']=self.clock>=1;reads.append((self.clock,row['enabled']))
            return row
        self.probe.window=window;self.call()
        self.assertTrue(any(not ready for _time,ready in reads))
        self.assertEqual(len(self.field.inputs),1);self.assertEqual(len(self.button.inputs),1)
        self.assertGreaterEqual(self.clock,1.75);self.assertLess(self.clock,30)
        data=self.diagnostic();self.assertFalse(data['initialWindow']['enabled'])
        self.assertTrue(data['readyWindow']['enabled']);self.assertEqual(self.probe.activations,[])

    def test_owned_shell_never_ready_stays_bounded_and_receives_no_input(self):
        self.probe.windows[300]['enabled']=False
        with self.assertRaisesRegex(AssertionError,'stabilize'):self.call()
        self.assertEqual(self.field.inputs,[]);self.assertEqual(self.button.inputs,[])
        self.assertGreaterEqual(self.clock,30);self.assertLess(self.clock,32)
        data=self.diagnostic();self.assertFalse(data['passed']);self.assertFalse(data['initialWindow']['enabled'])

    def test_loading_shell_identity_change_is_rejected_without_input(self):
        for kind in ('pid','tid','root','class','owner','closed'):
            with self.subTest(kind=kind):
                self.setUp();original=self.probe.window
                def window(hwnd):
                    row=original(hwnd)
                    if hwnd==300:
                        row['enabled']=False
                        if self.clock>=1:
                            if kind=='closed':raise AssertionError('Closed native window')
                            if kind=='class':row['cls']='foreign'
                            elif kind=='owner':row['owners']=[999]
                            else:row[kind]=999
                    return row
                self.probe.window=window;self.reject();self.assertEqual(self.field.inputs,[])
                self.assertLess(self.clock,3)

    def test_shell_loses_readiness_after_ready_snapshot_and_no_input_is_sent(self):
        original=self.probe.window
        def window(hwnd):
            row=original(hwnd)
            if hwnd==300 and self.clock>=1:row['enabled']=False
            return row
        self.probe.window=window;self.reject();self.assertEqual(self.field.inputs,[])

    def test_initial_foreign_window_identity_is_rejected_before_any_readiness_wait(self):
        self.probe.windows[300].update(pid=99,enabled=False);self.reject()
        self.assertEqual(self.clock,0);self.assertEqual(self.field.inputs,[])

    def test_loading_native_values_are_recorded_even_before_identity_rejection(self):
        self.probe.windows[300].update(root=999,visible=False,enabled=False);self.reject()
        data=self.diagnostic();self.assertEqual(data['initialWindow']['root'],999)
        self.assertFalse(data['initialWindow']['visible']);self.assertFalse(data['initialWindow']['enabled'])

    def test_foreign_title_or_class_is_recorded_only_as_a_safe_mismatch(self):
        opaque='secret https://example.invalid/opaque?token=secret'
        self.dialog.window_text=lambda:opaque;self.probe.windows[300]['cls']=opaque;self.reject()
        data=self.diagnostic();self.assertNotIn('secret',json.dumps(data))
        self.assertFalse(data['initialWrapperTitleMatched']);self.assertEqual(data['initialWindow']['cls'],'unexpected-class')

    def test_actual_print_caller_filters_save_ownership_and_passes_held_runtime(self):
        tree = ast.parse((ROOT/'e2e/virtual_print.py').read_text(encoding='utf8'))
        selected = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'save_print_output')
        (self.folder/'session').mkdir(); (self.folder/'session/runtime.json').write_text(json.dumps(self.runtime),encoding='utf8')
        seen=[]
        def visible(title,pid): seen.append((title,pid)); return self.dialog
        def guarded(dialog,output,pid,runtime,**kwargs):
            self.assertEqual(kwargs['app_handle'],77); self.assertEqual(kwargs['evidence_dir'],self.folder)
            return self.module.fill_print_output(dialog,output,pid,runtime,probe=self.probe,**kwargs)
        scope={'json':json,'wait':lambda check:check(),'visible_dialog':visible,'fill_print_output':guarded}
        exec(compile(ast.Module(body=[selected],type_ignores=[]),'actual-save-caller','exec'),scope)
        self.probe.hit_hwnd=999
        session=types.SimpleNamespace(proc=types.SimpleNamespace(pid=10,_handle=77))
        sys.path.insert(0,str(ROOT/'e2e'))
        try:
            with self.assertRaises(AssertionError):scope['save_print_output'](session,self.output,self.folder)
        finally:sys.path.pop(0)
        self.assertEqual(seen,[('Save Print Output As',10)]);self.assertEqual(self.button.inputs,[])

    def output_wait(self,wait):
        tree=ast.parse((ROOT/'e2e/virtual_print.py').read_text(encoding='utf8'))
        selected=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='print_output_wait')
        scope={'json':json,'time':self.module.time,'wait':wait}
        exec(compile(ast.Module(body=[selected],type_ignores=[]),'actual-output-wait','exec'),scope)
        return scope['print_output_wait']

    def test_output_stage_retains_original_timeout_and_opaque_failure_is_redacted(self):
        seen=[]
        def wait(check,seconds):
            seen.append(seconds);raise OSError('secret https://example.invalid/opaque?token=secret')
        with self.assertRaises(OSError):self.output_wait(wait)(self.folder,'pdf-created',lambda:False,90)
        self.assertEqual(seen,[90]);data=json.loads((self.folder/'print-output-progress-diagnostic.json').read_bytes())
        self.assertEqual(data['phase'],'pdf-created');self.assertFalse(data['passed'])
        self.assertEqual(data['errorType'],'OSError');self.assertNotIn('secret',json.dumps(data))

    def test_output_stage_returns_real_spooler_observation_without_changes(self):
        result={'queue':'synthetic-owned','jobs':[{'JobId':12}]};seen=[]
        def wait(check,seconds):seen.append(seconds);return check()
        self.assertIs(self.output_wait(wait)(self.folder,'owned-spooler-completed',lambda:result,30),result)
        self.assertEqual(seen,[30]);data=json.loads((self.folder/'print-output-progress-diagnostic.json').read_bytes())
        self.assertTrue(data['passed']);self.assertEqual(data['phase'],'owned-spooler-completed')


if __name__ == '__main__': unittest.main()
