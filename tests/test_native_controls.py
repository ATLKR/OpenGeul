"""The native dialog selector must reject ambiguous or hidden controls."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
try:
    from native_controls import filename_control
except ImportError:
    filename_control = None

class Control:
    def __init__(self,name='Edit',parent='ComboBox',visible=True,enabled=True):
        self.name,self.parent_name,self.visible,self.enabled=name,parent,visible,enabled
    def class_name(self):return self.name
    def parent(self):return Control(self.parent_name)
    def is_visible(self):return self.visible
    def is_enabled(self):return self.enabled

class FilenameControlTests(unittest.TestCase):
    def choose(self,controls):
        self.assertIsNotNone(filename_control,'Native dialog selector has not been implemented')
        return filename_control(controls)
    def test_selects_filename_not_search_box_or_hidden_edit(self):
        target=Control()
        self.assertIs(self.choose([Control('SearchEditBoxWrapperClass'),Control(visible=False),target,Control(parent='Other')]),target)
    def test_disabled_control_is_not_selected(self):
        with self.assertRaises(ValueError):self.choose([Control(enabled=False)])
    def test_missing_filename_control_is_an_error(self):
        with self.assertRaises(ValueError):self.choose([])
    def test_multiple_visible_filename_controls_are_an_error(self):
        with self.assertRaises(ValueError):self.choose([Control(),Control()])
