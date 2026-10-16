import importlib.util
from copy import deepcopy
from pathlib import Path
import sys
import unittest

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
try:
    import korean_ui_smoke as smoke
except ImportError:
    smoke = None


def tab(name, index, *, role=38, parent=None):
    path = [0, 1] if parent is None else parent
    return dict(name=name, index=index, role=role, visible=True,
                indexPath=path+[index], parentIndexPath=path,
                liveParentVerified=True, liveIndexReadbackVerified=True,
                rectangle=[20+index*70, 20, 80+index*70, 40])


def snapshot(controls):
    return dict(kind='owned-native-vcl-accessibility', roleNamespace='com.sun.star.accessibility.AccessibleRole',
                roleConstants={'PAGE_TAB':38, 'PAGE_TAB_LIST':39}, officePid=200, childHwnd=123,
                module='writer', loadedModuleService='com.sun.star.text.TextDocument',
                containerHwnd=123, sameLiveFrameVerified=True, ownedPeerAccessibleParentAbsent=True,
                nativeNotebookbarBinding=dict(ownedPeerWidgetVerified=True,targetWidgetType='TabControlUIObject',
                                             targetWidgetId='ContextContainer',nextFocusMatchesTargetWidget=True,
                                             focusRestored=True,selectionUnchanged=True),
                rootRectangle=[0, 0, 1024, 768], boundsDpiContext='per-monitor-v2', truncated=False,
                witness=dict(retainedProcessHandle=True,imageVerified=True,creationTimeVerified=True,
                             hwndVerifiedBefore=True,hwndVerifiedAfter=True,boundsDpiContextRestored=True),
                tabContainers=[dict(role=39,visible=True,sameLiveParentVerified=True,
                                    distinctLiveObjectsVerified=True,indexReadbackVerified=True,
                                    rectangle=[0,10,1024,150],indexPath=[0,1],tabs=controls)])


class KoreanUiEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'The bounded native Korean UI collector is missing')

    def test_actual_korean_tab_items_in_same_native_tab_control_pass(self):
        evidence = smoke.require_korean_tabs(snapshot([tab('홈', 1), tab('삽입', 2)]), 200, 123)
        self.assertEqual(evidence['koreanTabLabels'], ['삽입', '홈'])
        self.assertTrue(evidence['koreanUiVerified'])
        self.assertTrue(evidence['tabbedUiVerified'])

    def test_english_native_tabs_plus_korean_shell_file_menu_fail(self):
        controls = [tab('Home', 1), tab('Insert', 2), tab('파일', 3, role=35)]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_korean_menus_and_document_text_do_not_prove_a_tabbed_ui(self):
        for role in (35, 61, 43, 13, 37):
            with self.subTest(role=role), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(snapshot([tab('홈', 1, role=role),
                                                    tab('삽입', 2, role=role)]), 200, 123)

    def test_config_without_accessible_controls_does_not_prove_language(self):
        data = snapshot([])
        data.update(UILocale='ko', ActiveWriter='notebookbar.ui')
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(data, 200, 123)

    def test_tabs_must_be_visible_and_share_an_owned_tab_container(self):
        bad = [tab('홈', 1), tab('삽입', 2, parent=[0,2])]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(bad), 200, 123)
        bad[1] = tab('삽입', 2)
        bad[1]['visible'] = False
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(bad), 200, 123)

    def test_native_ownership_cannot_be_replaced_by_matching_labels(self):
        for key in ('childHwnd', 'officePid', 'containerHwnd'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data[key] += 1
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_mnemonic_markup_is_removed_without_accepting_label_substrings(self):
        self.assertEqual(smoke.normalize_label('삽입(~I)'), '삽입')
        self.assertEqual(smoke.normalize_label('~홈'), '홈')
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot([tab('홈페이지', 1), tab('삽입', 2)]), 200, 123)

    def test_unrendered_contextual_tabs_do_not_replace_or_hide_rendered_required_tabs(self):
        hidden = tab('문맥별 도구', 3)
        hidden['rectangle'] = [0, 0, 0, 0]  # VCL may retain SHOWING on an unused context page.
        evidence = smoke.require_korean_tabs(snapshot([tab('홈', 1), tab('삽입', 2), hidden]), 200, 123)
        self.assertTrue(evidence['koreanUiVerified'])

    def test_duplicate_actual_indices_cannot_claim_distinct_native_tabs(self):
        controls = [tab('홈', 1), tab('삽입', 1)]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_live_parent_object_and_index_readback_are_required(self):
        baseline = snapshot([tab('홈', 1), tab('삽입', 2)])
        for key in ('sameLiveParentVerified', 'distinctLiveObjectsVerified', 'indexReadbackVerified'):
            data = deepcopy(baseline)
            data['tabContainers'][0][key] = False
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)
        for key in ('liveParentVerified', 'liveIndexReadbackVerified'):
            data = deepcopy(baseline)
            data['tabContainers'][0]['tabs'][1][key] = False
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_retained_process_image_creation_and_window_witnesses_are_required(self):
        for key in ('retainedProcessHandle', 'imageVerified', 'creationTimeVerified', 'hwndVerifiedBefore', 'hwndVerifiedAfter'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data['witness'][key] = False
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_wrong_frame_module_or_role_namespace_cannot_supply_korean_text(self):
        baseline = snapshot([tab('홈', 1), tab('삽입', 2)])
        for change in ({'loadedModuleService': 'com.sun.star.sheet.SpreadsheetDocument'},
                       {'sameLiveFrameVerified': False},
                       {'roleNamespace': 'Microsoft.ActiveAccessibility'},
                       {'roleConstants': {'PAGE_TAB':37, 'PAGE_TAB_LIST':60}}):
            data = deepcopy(baseline)
            data.update(change)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_foreign_widget_focus_or_unrestored_selection_cannot_bind_native_tabs(self):
        for key, value in (('ownedPeerWidgetVerified', False), ('targetWidgetType', 'ButtonUIObject'),
                           ('targetWidgetId', 'foreign frame'), ('nextFocusMatchesTargetWidget', False),
                           ('focusRestored', False), ('selectionUnchanged', False)):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data['nativeNotebookbarBinding'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_required_tab_outside_owned_native_window_cannot_qualify(self):
        controls = [tab('홈', 1), tab('삽입', 2)]
        controls[1]['rectangle'] = [1500, 0, 1600, 20]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_rendered_bounds_require_verified_scoped_physical_pixel_context(self):
        for missing in ('boundsDpiContext', 'boundsDpiContextRestored'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            if missing == 'boundsDpiContext':
                data.pop(missing)
            else:
                data['witness'][missing] = False
            with self.subTest(missing=missing), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)


class PrivateNativeTransportTests(unittest.TestCase):
    def test_exact_owned_gui_pipe_is_accepted_without_publishing_it(self):
        value = 'OpenGeul_' + 'a'*32
        args = ['soffice.bin', '--invisible', '--accept=pipe,name='+value+';urp;StarOffice.ServiceManager']
        self.assertEqual(value, smoke.accessible.private_pipe(args))

    def test_public_socket_malformed_duplicate_or_headless_transport_is_rejected(self):
        valid = '--accept=pipe,name=OpenGeul_'+'a'*32+';urp;StarOffice.ServiceManager'
        for args in (['--invisible', '--accept=socket,host=localhost,port=2002;urp;StarOffice.ServiceManager'],
                     ['--invisible', valid, valid], ['--headless', valid],
                     ['--invisible', valid.replace('a'*32, 'foreign')]):
            with self.subTest(args=args), self.assertRaises(AssertionError):
                smoke.accessible.private_pipe(args)


if __name__ == '__main__':
    unittest.main()
