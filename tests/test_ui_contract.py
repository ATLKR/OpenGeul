"""제품 실행 없이 실제 UI runner validator의 negative 계약을 검사한다."""
import copy
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
from ui_contract import (
    BASELINE_COMMON, BASELINE_NATIVE, COMMON_CHECKS, NATIVE_CHECKS,
    EXPECTED_COUNTS, HELPERS, PREFIX, discovered_ids, exact_ids,
    helper_hashes, hosted_recent_guard, junit_bytes, manifest, validate_evidence,
    require_owned_recent_paths,
)
from driver import Session


def evidence(mode='native'):
    checks = {**COMMON_CHECKS, **NATIVE_CHECKS}
    records = [{'test': case, 'status': 'passed', 'seconds': .125, 'message': '',
                'checks': {key: True for key in checks.get(case.removeprefix(PREFIX), ())}}
               for case in manifest(mode)]
    payload = {'mode': mode, 'expectedTests': EXPECTED_COUNTS[mode], 'caseIds': list(manifest(mode)),
               'helperSha256': helper_hashes(ROOT), 'success': True, 'tests': records}
    return payload, junit_bytes(records)


class UiContractTests(unittest.TestCase):
    def validate(self, payload, xml=None, *, mode='native', before=None):
        return validate_evidence(payload, xml or junit_bytes(payload['tests']), mode=mode,
                                 root=ROOT, before=before or helper_hashes(ROOT))

    def test_reviewed_baseline_and_fixed_counts(self):
        self.assertEqual(len(BASELINE_COMMON), 10)
        self.assertEqual(len(BASELINE_NATIVE), 6)
        self.assertEqual(EXPECTED_COUNTS, {'browser': 14, 'native': 28})
        for mode in EXPECTED_COUNTS:
            payload, xml = evidence(mode)
            self.assertTrue(self.validate(payload, xml, mode=mode))
            self.assertTrue(set(PREFIX+n for n in BASELINE_COMMON).issubset(manifest(mode)))
        self.assertTrue(set(PREFIX+n for n in BASELINE_NATIVE).issubset(manifest('native')))

    def test_actual_discovered_suite_matches_manifest_without_starting_product(self):
        # Import/discover only. No setUp/browser/Session is executed.
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('browser', 'native'):
                with patch.dict(os.environ, {'E2E_MODE': mode, 'E2E_FIXTURES': folder,
                         'E2E_OUTPUT': folder, 'E2E_EXE': str(Path(folder)/'OpenGeul.exe')}):
                    for module in ('test_editor', 'test_supported_features', 'test_hop_followups'):
                        sys.modules.pop(module, None)
                    imported = importlib.import_module('test_hop_followups')
                    exact_ids(discovered_ids(imported.suite()), mode)

    def test_missing_replaced_duplicate_extra_preflight_are_rejected(self):
        cases = list(manifest('native'))
        wrong = (cases[:-1], cases[:-1]+['different.case'], cases[:-1]+[cases[0]], cases+[cases[0]])
        for ids in wrong:
            with self.subTest(ids=ids[-1:]), self.assertRaises(ValueError):
                exact_ids(ids, 'native')

    def test_discovered_reverse_and_adjacent_swap_are_rejected(self):
        for mode in ('browser', 'native'):
            cases = list(manifest(mode))
            adjacent = cases.copy(); adjacent[0], adjacent[1] = adjacent[1], adjacent[0]
            for wrong in (list(reversed(cases)), adjacent):
                with self.subTest(mode=mode, ids=wrong[:2]), self.assertRaises(ValueError):
                    exact_ids(wrong, mode)

    def test_json_reverse_is_rejected_with_original_or_reversed_junit(self):
        for mode in ('browser', 'native'):
            for matching_junit in (False, True):
                payload, xml = evidence(mode)
                payload['tests'].reverse()
                if matching_junit:
                    xml = junit_bytes(payload['tests'])
                with self.subTest(mode=mode, matching_junit=matching_junit), self.assertRaises(ValueError):
                    self.validate(payload, xml, mode=mode)

    def test_junit_reverse_alone_is_rejected(self):
        for mode in ('browser', 'native'):
            payload, _ = evidence(mode)
            xml = junit_bytes(list(reversed(payload['tests'])))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.validate(payload, xml, mode=mode)

    def test_gui_pdf_cancel_preserves_target_in_picker_dispatch(self):
        session = Session.__new__(Session)
        session.mode = 'native'; session.page = Mock(); session.native_dialog = Mock()
        target = ROOT/'owned-existing-target.pdf'
        with patch('driver.menu'), patch('driver.expect') as css_expect:
            self.assertIsNone(session.export_pdf(target, cancel=True))
        session.native_dialog.assert_called_once_with(target, cancel=True)
        css_expect.assert_not_called()  # CSS state is not an operation-lock predicate.

    def test_native_cancel_enters_verified_filename_before_physical_cancel(self):
        self.picker_cancel_fixture(wrong_readback=False)

    def test_native_cancel_rejects_changed_filename_before_input(self):
        with self.assertRaisesRegex(AssertionError, 'filename'):
            self.picker_cancel_fixture(wrong_readback=True)

    def picker_cancel_fixture(self, *, wrong_readback):
        # Offline control harness only: no real Desktop/process/Windows input.
        # Exercise the actual helper's target/readback/action/ownership branches.
        import driver
        events = []
        state = {'visible': True, 'typed': None}
        target = ROOT/'owned-existing-target.pdf'
        filename = Mock()
        filename.class_name.return_value = 'Edit'
        filename.parent.return_value.class_name.return_value = 'ComboBox'
        filename.is_visible.return_value = filename.is_enabled.return_value = True
        filename.set_edit_text.side_effect = lambda value: (events.append(('filename', value)), state.update(typed=value))
        filename.window_text.side_effect = lambda: 'changed-target.pdf' if wrong_readback else state['typed']
        buttons = []
        for control_id in (1, 2):
            button = Mock()
            button.class_name.return_value = 'Button'
            button.control_id.return_value = control_id
            button.is_visible.return_value = button.is_enabled.return_value = True
            button.click_input.side_effect = lambda action=control_id: (events.append(('click', action)), state.update(visible=False))
            buttons.append(button)
        dialog = Mock()
        dialog.handle = 66; dialog.process_id.return_value = 321
        dialog.class_name.return_value = '#32770'
        dialog.descendants.side_effect = lambda **kw: buttons if kw.get('class_name') == 'Button' else [filename, *buttons]
        spec = Mock(); spec.wrapper_object.return_value = dialog
        desktop = Mock(); desktop.window.return_value = spec
        def thread_process(hwnd, reference):
            reference._obj.value = 321
            return 99
        def class_name(hwnd, buffer, length):
            buffer.value = '#32770'
            return len(buffer.value)
        user32 = SimpleNamespace(GetWindowThreadProcessId=thread_process,
            GetClassNameW=class_name, IsWindow=lambda hwnd: True,
            IsWindowVisible=lambda hwnd: state['visible'], IsWindowEnabled=lambda hwnd: True)
        modules = {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop),
            'pywinauto.controls': SimpleNamespace(),
            'pywinauto.controls.hwndwrapper': SimpleNamespace(InvalidWindowHandle=type('InvalidWindowHandle', (Exception,), {}))}
        session = Session.__new__(Session); session.proc = SimpleNamespace(pid=321)
        with patch.dict(sys.modules, modules), patch.object(driver.ctypes, 'windll', SimpleNamespace(user32=user32), create=True):
            session.native_dialog(target, cancel=True)
        self.assertEqual(events, [('filename', str(target)), ('click', 2)])
        self.assertEqual(state['typed'], str(target))

    def test_postflight_missing_replaced_duplicate_and_extra_are_rejected(self):
        for mutation in ('missing', 'replaced', 'duplicate', 'extra'):
            payload, _ = evidence()
            if mutation == 'missing': payload['tests'].pop()
            if mutation == 'replaced': payload['tests'][-1]['test'] = 'different.case'
            if mutation == 'duplicate': payload['tests'][-1] = copy.deepcopy(payload['tests'][0])
            if mutation == 'extra': payload['tests'].append(copy.deepcopy(payload['tests'][0]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validate(payload)

    def test_failure_error_skip_and_false_success_are_rejected(self):
        for status in ('failed', 'error', 'skipped'):
            payload, _ = evidence(); payload['tests'][0]['status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError): self.validate(payload)
        for value in (False, 1, 'true', None):
            payload, xml = evidence(); payload['success'] = value
            with self.subTest(success=value), self.assertRaises(ValueError): self.validate(payload, xml)

    def test_required_oracle_checks_missing_false_substitute_are_rejected(self):
        for bad in ({}, {'clipboard': True}, {'clipboard': False}, {'clipboard': 1}):
            payload, _ = evidence()
            target = next(row for row in payload['tests'] if row['test'].endswith('test_supported_keyboard_clipboard_copy_cut_paste'))
            target['checks'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.validate(payload)
        for value in (False, 1, 'true', None):
            payload, _ = evidence()
            target = next(row for row in payload['tests'] if row['test'].endswith('test_supported_keyboard_clipboard_copy_cut_paste'))
            target['checks']['clipboard'] = value
            with self.subTest(full_check_value=value), self.assertRaises(ValueError): self.validate(payload)
        payload, _ = evidence()
        payload['tests'][0]['checks']['unreviewed-subcase'] = True
        with self.assertRaises(ValueError): self.validate(payload)

    def test_other_mode_count_and_changed_manifest_are_rejected(self):
        for key, value in (('mode', 'browser'), ('expectedTests', 16), ('caseIds', [])):
            payload, xml = evidence(); payload[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate(payload, xml)
        payload, xml = evidence(); payload['expectedTests'] = 28.0
        with self.assertRaises(ValueError): self.validate(payload, xml)
        with self.assertRaises(ValueError): manifest('other')
        payload, xml = evidence('browser')
        with self.assertRaises(ValueError): self.validate(payload, xml, mode='native')

    def test_helper_hash_is_consumed_before_after_and_from_serialized_payload(self):
        payload, xml = evidence()
        bad = dict(payload['helperSha256']); bad[HELPERS[0]] = '0'*64
        payload['helperSha256'] = bad
        with self.assertRaises(ValueError): self.validate(payload, xml)
        payload, xml = evidence()
        with self.assertRaises(ValueError): self.validate(payload, xml, before=bad)
        before = helper_hashes(ROOT)
        with patch('ui_contract.helper_hashes', return_value=bad), self.assertRaises(ValueError):
            validate_evidence(payload, xml, mode='native', root=ROOT, before=before)

    def test_junit_totals_cases_statuses_times_and_duplicates_must_match(self):
        for mutation in ('count', 'missing', 'duplicate', 'replacement', 'skip', 'time', 'malformed'):
            payload, xml = evidence(); tree = ET.fromstring(xml)
            if mutation == 'count': tree.set('tests', '16')
            if mutation == 'missing': tree.remove(tree[-1])
            if mutation == 'duplicate': tree[-1].set('name', tree[0].get('name'))
            if mutation == 'replacement': tree[-1].set('name', 'different.case')
            if mutation == 'skip': ET.SubElement(tree[0], 'skipped')
            if mutation == 'time': tree[0].set('time', '999')
            xml = b'<invalid' if mutation == 'malformed' else ET.tostring(tree)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.validate(payload, xml)

    def test_recent_guard_rejects_nonhosted_wrong_source_job_run_attempt_process(self):
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Windows',
               'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_JOB': 'native-e2e',
               'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a'*40}
        process = {'native': True, 'runningAtInspection': True, 'sourceCommit': 'a'*40,
                   'sourceRun': '12345', 'runAttempt': '1'}
        self.assertTrue(hosted_recent_guard(env, platform='nt', repository_head='a'*40, process=process))
        for key, value in (('GITHUB_ACTIONS', 'false'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                           ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_JOB', 'browser-e2e'),
                           ('GITHUB_RUN_ID', ''), ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_SHA', 'b'*40)):
            wrong = {**env, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                hosted_recent_guard(wrong, platform='nt', repository_head='a'*40, process=process)
        for key, value in (('native', False), ('runningAtInspection', False), ('sourceRun', '67890')):
            with self.subTest(process=key), self.assertRaises(ValueError):
                hosted_recent_guard(env, platform='nt', repository_head='a'*40, process={**process, key: value})
        with self.assertRaises(ValueError): hosted_recent_guard(env, platform='posix', repository_head='a'*40, process=process)

    def test_recent_outside_owned_inventory_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'owned'; root.mkdir()
            self.assertTrue(require_owned_recent_paths([str(root/'missing-but-owned.hwpx')], [root]))
            for paths in ([str(Path(folder)/'private-document.hwpx')], ['relative.hwpx'], [''], [1], None):
                with self.subTest(paths=paths), self.assertRaises(ValueError): require_owned_recent_paths(paths, [root])


if __name__ == '__main__': unittest.main()
