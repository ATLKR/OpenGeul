"""Exercise the real print entrypoint with only OS accessibility boundaries faked."""
import importlib.util
from pathlib import Path
import sys,types,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
class Window:
    def __init__(self,pid=3,name='Print',cls='RootView',children=()):
        self.pid=pid;self.name=name;self.cls=cls;self.children=list(children)
    def process_id(self):return self.pid
    def window_text(self):return self.name
    def class_name(self):return self.cls
    def is_enabled(self):return True
    def descendants(self,**kw):return self.children
class PrintConfigurationOrderTests(unittest.TestCase):
    def setUp(self):
        self.events=[];self.fail_config=False;self.fail_invoke=False
        self.root=Window(name='OpenGeul',cls='Tauri Window')
        self.action=Window(name='Print using system dialog… (Ctrl+Shift+P)')
        self.action.iface_invoke=types.SimpleNamespace(Invoke=self.invoke)
        self.action.click_input=lambda:self.events.append('old-click')
        self.preview=Window(children=[Window(name='More settings'),self.action])
        self.previews=[self.preview]
        desktop=types.SimpleNamespace(window=lambda **kw:types.SimpleNamespace(wrapper_object=lambda:self.root))
        def configure(preview,pids,folder):
            self.events.append('configure')
            if self.fail_config:raise ValueError('media rejected')
        def wait(fn,**kw):
            result=fn()
            if result is None or result is False:raise AssertionError('not ready')
            return result
        spec=importlib.util.spec_from_file_location('configured_print_focus',ROOT/'e2e/print_focus.py')
        self.m=importlib.util.module_from_spec(spec)
        self.fake=patch.dict(sys.modules,{
            'pywinauto':types.SimpleNamespace(Desktop=lambda **kw:desktop),
            'comtypes':types.SimpleNamespace(COMError=type('COMError',(Exception,),{})),
            'preview_settings':types.SimpleNamespace(configure_preview=configure,wait=wait),
            'print_ui_policy':types.SimpleNamespace(system_link=lambda nodes,pids:1 if len(nodes)==2 else None),
        })
        self.fake.start();self.addCleanup(self.fake.stop)
        spec.loader.exec_module(self.m)
        self.m._owned_pids=lambda pid:{pid}
        self.m._preview_windows=lambda *args:self.previews
        self.m._node=lambda c:{'name':c.window_text(),'pid':c.process_id(),'visible':True,'enabled':True,'handle':1,'type':'Button','rect':[0,0,100,10]}
        self.tick=0
        def now():
            self.tick+=1;return self.tick
        self.m.time=types.SimpleNamespace(monotonic=now,sleep=lambda seconds:None)
    def invoke(self):
        self.events.append('invoke')
        if self.fail_invoke:raise OSError('dispatched action failed')
    def test_media_configured_before_system_driver_opens(self):
        self.m.open_system_dialog(10,3)
        self.assertEqual(self.events,['configure','invoke'])
    def test_wrong_app_owner_never_configures_or_prints(self):
        self.root.pid=4
        with self.assertRaises(AssertionError):self.m.open_system_dialog(10,3)
        self.assertEqual(self.events,[])
    def test_ambiguous_preview_never_configures_or_prints(self):
        self.previews.append(self.preview)
        with self.assertRaises(AssertionError):self.m.open_system_dialog(10,3)
        self.assertEqual(self.events,[])
    def test_configuration_failure_prevents_system_print(self):
        self.fail_config=True
        with self.assertRaises(ValueError):self.m.open_system_dialog(10,3)
        self.assertEqual(self.events,['configure'])
    def test_dispatched_native_invoke_is_not_retried(self):
        self.fail_invoke=True
        with self.assertRaises(OSError):self.m.open_system_dialog(10,3)
        self.assertEqual(self.events,['configure','invoke'])
    def test_missing_system_action_is_not_success(self):
        self.preview.children=self.preview.children[:1]
        with self.assertRaises(AssertionError):self.m.open_system_dialog(10,3)
        self.assertNotIn('invoke',self.events)
if __name__=='__main__':unittest.main()
