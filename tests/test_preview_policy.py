"""Semantic print settings: never confuse unrelated app controls with preview UI."""
import importlib.util
from pathlib import Path
import unittest
PATH=Path(__file__).resolve().parents[1]/'e2e/preview_policy.py'
class PreviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.is_file(),'Missing explicit preview-setting policy')
        s=importlib.util.spec_from_file_location('preview_policy',PATH)
        self.m=importlib.util.module_from_spec(s);s.loader.exec_module(self.m)
    def node(self,name,type='Button',**kw):
        return dict(name=name,type=type,enabled=True,pid=5,**kw)
    def test_old_button_dropdown(self):
        nodes=[self.node('Printer A4'),self.node('Paper size Letter')]
        self.assertEqual(self.m.dropdown_index(nodes,'Paper size',{5}),1)
    def test_new_combo_group(self):
        self.assertEqual(self.m.dropdown_index([self.node('',type='ComboBox',group='Margins')],'Margins',{5}),0)
    def test_disabled_does_not_act(self):
        n=self.node('Paper size Letter');n['enabled']=False
        self.assertIsNone(self.m.dropdown_index([n],'Paper size',{5}))
    def test_foreign_process_rejected(self):
        self.assertIsNone(self.m.dropdown_index([self.node('Paper size Letter')],'Paper size',{6}))
    def test_unknown_label_rejected(self):
        with self.assertRaises(ValueError):self.m.dropdown_index([], 'Print', {5})
    def test_duplicates_fail_closed(self):
        with self.assertRaises(ValueError):self.m.dropdown_index([self.node('Paper size Letter')]*2,'Paper size',{5})
    def test_offscreen_semantic_control_is_allowed(self):
        self.assertEqual(self.m.dropdown_index([self.node('Margins Default',visible=False)],'Margins',{5}),0)
    def test_similar_label_not_selected(self):
        self.assertIsNone(self.m.dropdown_index([self.node('Paper size malicious extra')],'Paper size',{5}))
    def test_option_exact_match(self):
        self.assertEqual(self.m.option_index([self.node('A4',type='ListItem')],'A4',{5}),0)
    def test_plain_text_is_not_an_option(self):
        self.assertIsNone(self.m.option_index([self.node('A4',type='Text')],'A4',{5}))
    def test_option_duplicates_rejected(self):
        with self.assertRaises(ValueError):self.m.option_index([self.node('None',type='ListItem')]*2,'None',{5})
    def test_margin_option_and_paper_value_whitelist(self):
        for value in ('None','A4'):
            self.assertEqual(self.m.option_index([self.node(value,type='ListItem')],value,{5}),0)
        with self.assertRaises(ValueError):self.m.option_index([], 'Letter', {5})
    def test_actual_paper_margin_scale_validated(self):
        self.m.validate_settings({'paper':'A4','margins':'None','actualSize':True})
        for key,value in [('paper','Letter'),('margins','Default'),('actualSize',False)]:
            with self.assertRaises(ValueError):self.m.validate_settings({'paper':'A4','margins':'None','actualSize':True, key:value})
if __name__=='__main__':unittest.main()
