"""Semantic native-preview controls, independent of desktop/DPI/local keyboard."""
import importlib.util
from pathlib import Path
import unittest

PATH=Path(__file__).resolve().parents[1]/'e2e/print_ui_policy.py'

class PrintUiPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.exists(),'Missing semantic print control policy')
        spec=importlib.util.spec_from_file_location('print_ui_policy',PATH)
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)
        self.good={'name':'Print using system dialog… (Ctrl+Shift+P)','type':'Hyperlink',
                   'visible':True,'enabled':True,'pid':123}

    def test_new_runtime_hyperlink(self):self.assertEqual(self.mod.system_link([self.good],{123}),0)
    def test_old_runtime_button(self):self.assertEqual(self.mod.system_link([{**self.good,'type':'Button'}],{123}),0)
    def test_initially_missing_control_is_not_a_click_target(self):self.assertIsNone(self.mod.system_link([],{123}))
    def test_offscreen_exact_action_is_still_semantically_identified(self):
        self.assertEqual(self.mod.system_link([{**self.good,'visible':False}],{123}),0)
    def test_disabled_control_is_not_ready(self):
        self.assertIsNone(self.mod.system_link([{**self.good,'enabled':False}],{123}))
    def test_unowned_window_is_never_selected(self):self.assertIsNone(self.mod.system_link([self.good],{456}))
    def test_plain_text_is_not_an_action(self):self.assertIsNone(self.mod.system_link([{**self.good,'type':'Text'}],{123}))
    def test_ambiguous_links_fail_closed(self):
        with self.assertRaises(ValueError):self.mod.system_link([self.good,self.good],{123})
    def test_hidden_duplicate_is_still_ambiguous(self):
        with self.assertRaises(ValueError):
            self.mod.system_link([self.good,{**self.good,'visible':False}],{123})
    def test_similar_or_injected_name_does_not_match(self):
        for title in ('Print','Print using system dialog… (Ctrl+Shift+P) extra','Print using system dialog; run script'):
            self.assertIsNone(self.mod.system_link([{**self.good,'name':title}],{123}))
    def test_ascii_ellipsis_alias(self):
        self.assertEqual(self.mod.system_link([{**self.good,'name':'Print using system dialog... (Ctrl+Shift+P)'}],{123}),0)

if __name__=='__main__':unittest.main()
