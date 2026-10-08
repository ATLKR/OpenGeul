"""OS-boundary regression: a new TaskDialog must not rebind the old file dialog."""
import importlib.util
from pathlib import Path
import unittest
PATH=Path(__file__).resolve().parents[1]/'e2e/native_controls.py'
class Window:
    def __init__(self,handle,pid=42,cls='#32770'):self.handle=handle;self.pid=pid;self.cls=cls;self.visible=True
    def process_id(self):return self.pid
    def class_name(self):return self.cls
class Spec:
    def __init__(self,desktop,query):self.desktop=desktop;self.query=query
    def wait(self,*args,**kwargs):pass
    def wrapper_object(self):return self.desktop.windows.get(self.query.get('handle',self.desktop.current))
    def visible(self):
        w=self.wrapper_object();return bool(w and w.visible)
class Desktop:
    def __init__(self):self.windows={100:Window(100)};self.current=100;self.queries=[]
    def window(self,**kw):self.queries.append(kw);return Spec(self,kw)
class BoundDialogTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('native_controls',PATH)
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)
        self.assertTrue(hasattr(self.mod,'bind_dialog'),'File dialog still uses a rebinding selector')
    def test_new_error_dialog_does_not_keep_closed_file_picker_visible(self):
        desktop=Desktop();bound=self.mod.bind_dialog(desktop,42)
        desktop.windows[100].visible=False;desktop.windows[200]=Window(200);desktop.current=200
        self.assertFalse(bound.visible());self.assertEqual(desktop.queries[-1],{'handle':100})
    def test_original_visible_picker_does_not_pass_as_closed(self):
        desktop=Desktop();self.assertTrue(self.mod.bind_dialog(desktop,42).visible())
    def test_foreign_process_is_rejected(self):
        desktop=Desktop();desktop.windows[100].pid=17
        with self.assertRaises(ValueError):self.mod.bind_dialog(desktop,42)
    def test_non_dialog_is_rejected(self):
        desktop=Desktop();desktop.windows[100].cls='Tauri Window'
        with self.assertRaises(ValueError):self.mod.bind_dialog(desktop,42)
if __name__=='__main__':unittest.main()
