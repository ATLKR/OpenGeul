"""Preflight tests a native module's Python contract before compiling Windows.

Only the unavailable desktop module and native controls are faked. The actual
exported helper, filename selection and readiness logic are executed unchanged.
"""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]

class Clock:
    def __init__(self):self.now=0.0
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds

class Combo:
    handle=13
    def class_name(self):return 'ComboBox'
    def process_id(self):return 1
    def is_visible(self):return True
    def is_enabled(self):return True
    def rectangle(self):return types.SimpleNamespace(left=0,top=0,right=200,bottom=20)

class Field:
    handle=11
    def __init__(self):self.text='';self.inputs=0;self.visible=True;self.reject=False
    def class_name(self):return 'Edit'
    def process_id(self):return 1
    def is_visible(self):return self.visible
    def is_enabled(self):return True
    def parent(self):return Combo()
    def rectangle(self):return types.SimpleNamespace(left=0,top=0,right=200,bottom=20)
    def set_edit_text(self,text):
        self.inputs+=1
        if not self.reject:self.text=text
    def window_text(self):return self.text

class Button:
    handle=12
    def __init__(self):self.clicks=0;self.visible=True;self.error=False
    def is_visible(self):return self.visible
    def is_enabled(self):return True
    def control_id(self):return 1
    def class_name(self):return 'Button'
    def process_id(self):return 1
    def rectangle(self):return types.SimpleNamespace(left=0,top=30,right=100,bottom=60)
    def click_input(self):
        self.clicks+=1
        if self.error:raise OSError('Native input failed after dispatch')

class Probe:
    """External Win32 boundary only; the real exported readiness helper runs."""
    def bind_process(self,pid,expected,handle=None):return {'pid':pid,'creation':1,'session':1}
    def verify_process(self,pid,expected):
        if pid!=1 or expected!={'pid':1,'creation':1,'session':1}:raise AssertionError('Changed process')
    def window(self,hwnd):
        return {'hwnd':hwnd,'pid':1,'tid':2,'root':10,'owners':[],
                'cls':{10:'#32770',11:'Edit',12:'Button',13:'ComboBox'}[hwnd],
                'visible':True,'enabled':True}
    def foreground(self):return 10
    def hit(self,point):return 12
    def close(self):pass

class PrintExportsTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('print_focus_preflight',ROOT/'e2e/print_focus.py')
        self.module=importlib.util.module_from_spec(spec)
        desktop=types.ModuleType('pywinauto');desktop.Desktop=None
        controls_spec=importlib.util.spec_from_file_location('native_controls_preflight',ROOT/'e2e/native_controls.py')
        controls=importlib.util.module_from_spec(controls_spec);controls_spec.loader.exec_module(controls)
        self.modules=patch.dict(sys.modules,{'pywinauto':desktop,'native_controls':controls})
        self.modules.start();self.addCleanup(self.modules.stop)
        spec.loader.exec_module(self.module)
        self.clock=Clock();self.module.time=self.clock
        self.field=Field();self.button=Button()
        self.dialog=types.SimpleNamespace(handle=10,process_id=lambda:1,class_name=lambda:'#32770',
            window_text=lambda:'Save Print Output As',
            descendants=lambda **kw:[self.button] if kw.get('class_name')=='Button' else [self.field])
        self.runtime={'nativeArchitecture':{'processId':1,'architecture':'arm64'},
                      'webview2Native':{'rootProcessId':1,'processes':[]}}
    def call(self):
        self.assertTrue(callable(getattr(self.module,'fill_print_output',None)),'Missing native print output function')
        self.module.fill_print_output(self.dialog,Path('printed.pdf'),1,self.runtime,app_handle=77,probe=Probe())
    def test_all_print_focus_imports_resolve_before_windows_build(self):
        tree=ast.parse((ROOT/'e2e/virtual_print.py').read_text())
        names=[alias.name for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module=='print_focus' for alias in n.names]
        self.assertIn('fill_print_output',names)
        for name in names:self.assertTrue(callable(getattr(self.module,name,None)),f'Missing print export: {name}')
    def test_stable_field_is_filled_and_clicked_once(self):
        self.call();self.assertEqual(self.field.inputs,1);self.assertEqual(self.button.clicks,1)
        self.assertGreaterEqual(self.clock.now,.75)
    def test_hidden_field_never_receives_input(self):
        self.field.visible=False
        with self.assertRaisesRegex(AssertionError,'stabilize'):self.call()
        self.assertEqual(self.field.inputs,0);self.assertEqual(self.button.clicks,0)
    def test_rejected_filename_does_not_click_save(self):
        self.field.reject=True
        with self.assertRaisesRegex(AssertionError,'accepted'):self.call()
        self.assertEqual(self.field.inputs,1);self.assertEqual(self.button.clicks,0)
    def test_dispatched_save_error_is_not_retried(self):
        self.button.error=True
        with self.assertRaises(OSError):self.call()
        self.assertEqual(self.button.clicks,1)
    def test_ambiguous_save_buttons_never_click(self):
        self.dialog.descendants=lambda **kw:[self.button,Button()] if kw.get('class_name')=='Button' else [self.field]
        with self.assertRaisesRegex(AssertionError,'stabilize'):self.call()
        self.assertEqual(self.button.clicks,0)

if __name__=='__main__':unittest.main()
