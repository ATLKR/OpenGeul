"""Native option activation must commit through one action, never silent retry."""
import importlib.util
from pathlib import Path
import sys,types,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
class Choice:
    def __init__(self):
        self.visible=True;self.enabled=True;self.clicks=0;self.scrolls=0;self.fail=False
        self.iface_scroll_item=types.SimpleNamespace(ScrollIntoView=self.scroll)
    def scroll(self):self.scrolls+=1
    def is_visible(self):return self.visible
    def is_enabled(self):return self.enabled
    def click_input(self):
        self.clicks+=1
        if self.fail:raise OSError('action dispatched then failed')
class Clock:
    def __init__(self):self.now=0
    def monotonic(self):return self.now
    def sleep(self,delay):self.now+=delay
class PreviewActionTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('preview_settings_test',ROOT/'e2e/preview_settings.py')
        self.module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'print_focus':types.SimpleNamespace(_node=lambda c:{})}),patch.object(sys,'path',[str(ROOT/'e2e'),*sys.path]):spec.loader.exec_module(self.module)
        self.module.time=Clock();self.choice=Choice()
        self.assertTrue(callable(getattr(self.module,'activate_option',None)),'Missing native option commit helper')
    def call(self):
        self.assertTrue(callable(getattr(self.module,'activate_option',None)),'Missing native option commit helper')
        self.module.activate_option(self.choice)
    def test_visible_option_clicked_once(self):self.call();self.assertEqual(self.choice.clicks,1)
    def test_failed_click_is_not_retried(self):
        self.choice.fail=True
        with self.assertRaises(OSError):self.call()
        self.assertEqual(self.choice.clicks,1)
    def test_offscreen_option_without_scroll_completion_never_clicked(self):
        self.choice.visible=False
        with self.assertRaises(AssertionError):self.call()
        self.assertEqual(self.choice.clicks,0);self.assertEqual(self.choice.scrolls,1)
    def test_disabled_option_never_clicked(self):
        self.choice.enabled=False
        with self.assertRaises(AssertionError):self.call()
        self.assertEqual(self.choice.clicks,0)
if __name__=='__main__':unittest.main()
