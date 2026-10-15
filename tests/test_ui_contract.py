"""제품 실행 없이 실제 UI runner validator의 negative 계약을 검사한다."""
import copy
import hashlib
import json
import importlib
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
from ui_contract import (
    BASELINE_COMMON, BASELINE_NATIVE, BASELINE_NATIVE_CHECKS, COMMON_CHECKS, NATIVE_CHECKS,
    EXPECTED_COUNTS, HELPERS, PREFIX, discovered_ids, exact_ids,
    helper_hashes, hosted_recent_guard, junit_bytes, manifest, validate_evidence, frontend_source_binding,
    require_owned_recent_paths, local_windows_dos_path, canonical_local_path,
)
from driver import Session
import equation_dialog_focus


def frontend_binding():
    helper = equation_dialog_focus.HELPER
    helper_sha = hashlib.sha256((ROOT/helper).read_bytes()).hexdigest()
    return {'equationDialogFocus': {'beforeSha256':dict(equation_dialog_focus.INPUT_SOURCE_SHA256),
            'afterSha256':dict(equation_dialog_focus.OUTPUT_SOURCE_SHA256), 'helperSha256':helper_sha},
            'preparedFiles':dict(equation_dialog_focus.OUTPUT_SOURCE_SHA256), 'helperSha256':{helper:helper_sha}}


def evidence(mode='native'):
    checks = {**COMMON_CHECKS, **NATIVE_CHECKS, **BASELINE_NATIVE_CHECKS}
    records = [{'test': case, 'status': 'passed', 'seconds': .125, 'message': '',
                'checks': {key: True for key in checks.get(case.removeprefix(PREFIX), ())}}
               for case in manifest(mode)]
    payload = {'mode': mode, 'expectedTests': EXPECTED_COUNTS[mode], 'caseIds': list(manifest(mode)),
               'helperSha256': helper_hashes(ROOT), 'frontendSource':frontend_binding(), 'success': True, 'tests': records}
    return payload, junit_bytes(records)


class UiContractTests(unittest.TestCase):
    def validate(self, payload, xml=None, *, mode='native', before=None, source_binding=None):
        return validate_evidence(payload, xml or junit_bytes(payload['tests']), mode=mode,
                                 root=ROOT, before=before or helper_hashes(ROOT),
                                 source_binding=frontend_binding() if source_binding is None else source_binding)

    def test_native_advanced_input_stager_bytes_are_bound_for_both_ui_modes(self):
        name = 'e2e/native_advanced_inputs.py'
        self.assertIn(name, HELPERS)
        self.assertEqual(helper_hashes(ROOT)[name], hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
        for mode in ('browser', 'native'):
            payload, xml = evidence(mode)
            payload['helperSha256'][name] = '0'*64
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'helper'):
                self.validate(payload, xml, mode=mode)

    def test_equation_dialog_focus_helper_and_preparation_are_bound_for_both_modes(self):
        for name in ('scripts/equation_dialog_focus.py', 'scripts/prepare_upstream.py'):
            with self.subTest(helper=name):
                self.assertIn(name, HELPERS)

    def test_equation_dialog_focus_missing_input_source_proof_is_rejected(self):
        for mode in ('browser', 'native'):
            payload, xml = evidence(mode)
            payload.pop('frontendSource', None)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Equation dialog focus'):
                self.validate(payload, xml, mode=mode)

    def test_equation_dialog_focus_matching_input_and_payload_cannot_forge_fixed_source(self):
        name, = equation_dialog_focus.SOURCE_FILES
        for mode in ('browser', 'native'):
            for change in ('missing-proof', 'helper', 'before', 'after', 'missing-source', 'observed-hash', 'coherent-legacy', 'extra-proof', 'extra-source'):
                payload, xml = evidence(mode); binding = copy.deepcopy(payload['frontendSource'])
                proof = binding['equationDialogFocus']
                if change == 'missing-proof': binding.pop('equationDialogFocus')
                elif change == 'helper':
                    proof['helperSha256'] = binding['helperSha256'][equation_dialog_focus.HELPER] = '0'*64
                elif change in ('before', 'after'): proof[change+'Sha256'][name] = '0'*64
                elif change == 'missing-source': binding['preparedFiles'].pop(name)
                elif change == 'observed-hash': binding['preparedFiles'][name] = '0'*64
                elif change == 'extra-proof': proof['optional'] = True
                elif change == 'extra-source': binding['preparedFiles']['unreviewed.ts'] = '0'*64
                else:
                    proof['afterSha256'][name] = binding['preparedFiles'][name] = equation_dialog_focus.INPUT_SOURCE_SHA256[name]
                payload['frontendSource'] = copy.deepcopy(binding)
                with self.subTest(mode=mode, change=change), self.assertRaises(ValueError):
                    self.validate(payload, xml, mode=mode, source_binding=binding)

    def test_equation_dialog_focus_serialized_payload_cannot_replace_actual_input_binding(self):
        for mode in ('browser', 'native'):
            payload, xml = evidence(mode)
            payload['frontendSource']['preparedFiles'][equation_dialog_focus.SOURCE_FILES[0]] = '0'*64
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Equation dialog focus serialized/input'):
                self.validate(payload, xml, mode=mode)

    def test_equation_dialog_focus_actual_input_provenance_is_read_and_revalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            fixtures = Path(directory); path = fixtures/'advanced-owned/provenance.json'
            path.parent.mkdir()
            binding = frontend_binding()
            path.write_text(json.dumps({'generated':{}, 'frontendSource':binding}))
            self.assertEqual(frontend_source_binding(fixtures, ROOT), binding)
            changed = copy.deepcopy(binding)
            name, = equation_dialog_focus.SOURCE_FILES
            changed['equationDialogFocus']['afterSha256'][name] = changed['preparedFiles'][name] = '0'*64
            path.write_text(json.dumps({'generated':{}, 'frontendSource':changed}))
            with self.assertRaises(ValueError): frontend_source_binding(fixtures, ROOT)
            path.write_text(json.dumps({'generated':{}}))
            with self.assertRaisesRegex(ValueError, 'Equation dialog focus'): frontend_source_binding(fixtures, ROOT)
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'Equation dialog focus'): frontend_source_binding(fixtures, ROOT)

    def test_actual_input_generator_reobserves_equation_source_helper_and_ledger(self):
        # Owned engine double exercises the actual generator's source lifetime;
        # this is a producer contract test, not product/GUI execution evidence.
        generator = (ROOT/'e2e/generate-advanced-fixtures.mjs').read_bytes()
        helper = (ROOT/equation_dialog_focus.HELPER).read_bytes()
        for changed in ('source', 'helper', 'ledger'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory); prepared = folder/'prepared'
                source = prepared/equation_dialog_focus.SOURCE_FILES[0]
                source.parent.mkdir(parents=True)
                source.write_bytes(b'owned equation source lifetime fixture\n')
                target = folder/equation_dialog_focus.HELPER
                target.parent.mkdir(); target.write_bytes(helper)
                proof = {'beforeSha256':dict(equation_dialog_focus.INPUT_SOURCE_SHA256),
                         'afterSha256':{source.relative_to(prepared).as_posix():hashlib.sha256(source.read_bytes()).hexdigest()},
                         'helperSha256':hashlib.sha256(helper).hexdigest()}
                ledger = prepared/'.opengeul-overlay.json'
                ledger.write_text(json.dumps({'equationDialogFocus':proof}))
                local = folder/'e2e/generate-advanced-fixtures.mjs'
                local.parent.mkdir(); local.write_bytes(generator)
                vendor = prepared/'apps/studio-host/vendor/rhwp-core'
                vendor.mkdir(parents=True)
                (vendor/'package.json').write_text('{"type":"module"}')
                (vendor/'rhwp_bg.wasm').write_bytes(b'\0asm\1\0\0\0')
                mutation = {'source': f"writeFileSync({json.dumps(str(source))},'changed owned source');",
                            'helper': f"writeFileSync({json.dumps(str(target))},'changed owned helper');",
                            'ledger': f"writeFileSync({json.dumps(str(ledger))},JSON.stringify({{equationDialogFocus:{{changed:true}}}}));"}[changed]
                (vendor/'rhwp.js').write_text("import {writeFileSync} from 'node:fs';\n"
                    "export default async function init(){}\n"
                    "export const HwpDocument={createEmpty(){return new Proxy({}, {get(_,name){"
                    "if(name==='exportHwpx')return ()=>new Uint8Array([1,2,3]);"
                    "return ()=>{if(name==='createBlankDocument'){"+mutation+"}"
                    "return {ok:true,paraIdx:0,controlIdx:0};};}});}};\n")
                output = folder/'advanced-owned'
                result = subprocess.run(['node', str(local), str(prepared), str(output)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'actual prepared source/helper proof changed during input generation', result.stderr)
                self.assertFalse((output/'provenance.json').exists())

    def test_reviewed_baseline_and_fixed_counts(self):
        self.assertEqual(len(BASELINE_COMMON), 10)
        self.assertEqual(len(BASELINE_NATIVE), 6)
        self.assertEqual(EXPECTED_COUNTS, {'browser': 21, 'native': 42})
        self.assertEqual(len(HELPERS),34)  # Source8 helper/preparation plus native input stager; cases remain21/42.
        self.assertEqual(set(BASELINE_NATIVE_CHECKS),{'test_multiple_windows_use_real_native_creation'})
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

    def test_browser_html_picker_scope_precedes_page_and_navigation(self):
        # Offline lifecycle regression only; this does not launch a browser or
        # claim coverage of Chromium's File System Access OS dialogs.
        for browser_name in ('chromium', 'firefox', 'webkit'):
            with self.subTest(browser=browser_name), tempfile.TemporaryDirectory() as folder:
                events = []
                page = Mock()
                page.evaluate.return_value = {'platform': 'offline', 'userAgent': 'offline'}
                context = Mock()
                def install_scope(script):
                    removed = re.findall(
                        r"Object\.defineProperty\(window, '([^']+)', \{value: undefined, configurable: true\}\)", script)
                    self.assertEqual(set(removed), {'showOpenFilePicker', 'showSaveFilePicker'})
                    self.assertEqual(len(removed), 2)
                    events.append('scope')
                context.add_init_script.side_effect = install_scope
                context.new_page.side_effect = lambda: (events.append('page'), page)[1]
                page.goto.side_effect = lambda *args, **kwargs: events.append('navigation')
                browser = Mock(version='offline-browser')
                browser.new_context.return_value = context
                playwright = Mock()
                getattr(playwright, browser_name).launch.return_value = browser
                with patch('driver.sync_playwright') as start, patch('driver.expect'), \
                        patch('driver.menu'), patch.object(Session, 'wait_loaded'):
                    start.return_value.start.return_value = playwright
                    session = Session('browser', Path(folder), None, browser=browser_name)
                self.assertEqual(events, ['scope', 'page', 'navigation'])
                playwright.chromium.connect_over_cdp.assert_not_called()
                session.close()

    def test_public_replacement_keeps_browser_chooser_and_native_dialog_paths(self):
        target = ROOT/'owned-document-b.hwpx'
        for mode in ('browser', 'native'):
            with self.subTest(mode=mode):
                session = Session.__new__(Session)
                session.mode = mode; session.page = MagicMock()
                session.native_dialog = Mock(); session.wait_loaded = Mock()
                chooser = Mock()
                session.page.expect_file_chooser.return_value.__enter__.return_value = SimpleNamespace(value=chooser)
                with patch('driver.menu') as actual_menu:
                    session.open_public(target)
                actual_menu.assert_called_once_with(session.page, 'file:open')
                session.wait_loaded.assert_called_once_with(target.name)
                session.page.locator.assert_not_called()  # No direct file-input substitution.
                if mode == 'browser':
                    session.page.expect_file_chooser.assert_called_once_with()
                    chooser.set_files.assert_called_once_with(str(target))
                    session.native_dialog.assert_not_called()
                else:
                    session.native_dialog.assert_called_once_with(target)
                    session.page.expect_file_chooser.assert_not_called()
                    chooser.set_files.assert_not_called()

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
        payload, xml = evidence(); payload['expectedTests'] = float(EXPECTED_COUNTS['native'])
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
            validate_evidence(payload, xml, mode='native', root=ROOT, before=before, source_binding=frontend_binding())

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

    def test_local_dos_extended_alias_case_and_unicode_preserve_identity(self):
        target = PureWindowsPath(r'D:\a\OpenGeul\evidence\견적서 테스트.HWPX')
        for raw in (str(target), r'\\?\d:\A\OPENgeul\EVIDENCE\견적서 테스트.hwpx',
                    'D:/a/OpenGeul/evidence/견적서 테스트.HWPX'):
            with self.subTest(raw=raw):
                self.assertEqual(local_windows_dos_path(raw), target)

    def test_local_dos_rejects_namespace_devices_ads_and_dot_aliases(self):
        rejected = [r'\\server\share\file.hwpx', r'\\?\UNC\server\share\file.hwpx',
            r'\\.\D:\owned\file.hwpx', r'\??\D:\owned\file.hwpx',
            r'\\?\GLOBALROOT\Device\HarddiskVolume1\file.hwpx', r'D:owned\file.hwpx',
            r'D:\owned\file.hwpx:stream', r'D:\owned\..\file.hwpx', r'D:\owned\.\file.hwpx',
            r'\\?\D:\owned\file.hwpx.', r'\\?\D:\owned\file.hwpx ',
            r'\\?\D:/owned/file.hwpx', r'D:\owned\\file.hwpx', 'D:\\owned\\file\x00.hwpx']
        rejected += [rf'D:\owned\{device}.hwpx' for device in
                     ('CON', 'NUL', 'AUX', 'PRN', 'COM1', 'LPT9', 'COM¹', 'LPT³', 'CONIN$', 'CONOUT$')]
        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                local_windows_dos_path(raw)

    def test_recent_symlink_escape_and_inventory_limit_stay_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'owned'; root.mkdir()
            outside = Path(folder)/'outside'; outside.mkdir()
            (root/'escape').symlink_to(outside, target_is_directory=True)
            self.assertEqual(canonical_local_path(root/'safe.hwpx'), (root/'safe.hwpx').resolve())
            with self.assertRaises(ValueError):
                require_owned_recent_paths([str(root/'escape'/'document.hwpx')], [root])
            with self.assertRaises(ValueError):
                require_owned_recent_paths([str(root/'safe.hwpx')]*101, [root])

    def test_recent_dos_alias_inventory_keeps_outside_rejection(self):
        # Pure Windows lexical resolution on this offline host. Real filesystem
        # resolution remains in canonical_local_path and is covered above.
        class OfflineDosPath(PureWindowsPath):
            def resolve(self): return self
        with patch('ui_contract.Path', OfflineDosPath), patch('ui_contract.os', SimpleNamespace(name='nt')):
            root = r'D:\a\OpenGeul\evidence'
            self.assertTrue(require_owned_recent_paths(
                [r'\\?\d:\A\OPENgeul\EVIDENCE\견적서 테스트.HWPX'], [root]))
            for raw in (r'\\?\D:\a\OpenGeul\private.hwpx', r'D:\a\OpenGeul\evidence-other\file.hwpx',
                        r'\\?\D:\a\OpenGeul\evidence\..\private.hwpx', r'\\?\UNC\host\share\file.hwpx'):
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    require_owned_recent_paths([raw], [root])


if __name__ == '__main__': unittest.main()
