import importlib.util
from pathlib import Path
import sys
import unittest

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
try:
    import korean_ui_smoke as smoke
except ImportError:
    smoke = None


def tab(name, index, *, pid=200, control_type='TabItem', parent_type='Tab', parent=10):
    return dict(name=name, processId=pid, controlType=control_type, visible=True,
                runtimeId=[42, index], parentRuntimeId=[42, parent],
                parentProcessId=pid, parentControlType=parent_type, legacyRole=None,
                parentLegacyRole=None)


def snapshot(controls):
    return dict(childHwnd=123, officePid=200, rootProcessId=200, controls=controls)


class KoreanUiEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'The bounded native Korean UI collector is missing')

    def test_actual_korean_tab_items_in_same_native_tab_control_pass(self):
        evidence = smoke.require_korean_tabs(snapshot([tab('홈', 1), tab('삽입', 2)]), 200, 123)
        self.assertEqual(evidence['koreanTabLabels'], ['삽입', '홈'])
        self.assertTrue(evidence['koreanUiVerified'])
        self.assertTrue(evidence['tabbedUiVerified'])

    def test_english_native_tabs_plus_korean_shell_file_menu_fail(self):
        controls = [tab('Home', 1), tab('Insert', 2), tab('파일', 3, pid=100, control_type='MenuItem')]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_korean_menus_and_document_text_do_not_prove_a_tabbed_ui(self):
        for control_type in ('MenuItem', 'Text', 'Button', 'Document'):
            with self.subTest(control_type=control_type), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(snapshot([tab('홈', 1, control_type=control_type),
                                                    tab('삽입', 2, control_type=control_type)]), 200, 123)

    def test_config_without_accessible_controls_does_not_prove_language(self):
        data = snapshot([])
        data.update(UILocale='ko', ActiveWriter='notebookbar.ui')
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(data, 200, 123)

    def test_tabs_must_be_visible_and_share_an_owned_tab_container(self):
        bad = [tab('홈', 1), tab('삽입', 2, parent=20)]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(bad), 200, 123)
        bad[1] = tab('삽입', 2)
        bad[1]['visible'] = False
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(bad), 200, 123)

    def test_native_ownership_cannot_be_replaced_by_matching_labels(self):
        for key in ('childHwnd', 'officePid', 'rootProcessId'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data[key] += 1
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_mnemonic_markup_is_removed_without_accepting_label_substrings(self):
        self.assertEqual(smoke.normalize_label('삽입(~I)'), '삽입')
        self.assertEqual(smoke.normalize_label('~홈'), '홈')
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot([tab('홈페이지', 1), tab('삽입', 2)]), 200, 123)


if __name__ == '__main__':
    unittest.main()
