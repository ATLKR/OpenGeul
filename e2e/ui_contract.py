"""명시적인 제품 UI case 계약. 제품/브라우저를 시작하지 않는 독립 gate."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import sys
import os
from pathlib import Path, PureWindowsPath
import re
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import equation_dialog_focus

PREFIX = 'test_hop_followups.OpenGeulFollowups.'
BASELINE_COMMON = (
    'test_production_startup_has_no_development_bridge',
    'test_edit_save_reopen_unicode_xml_and_emoji',
    'test_three_roundtrips_preserve_all_edits_once',
    'test_undo_redo_changes_the_saved_document',
    'test_open_and_zoom_do_not_modify_the_source',
    'test_plain_p_keyboard_input_and_saved_document',
    'test_paragraph_fixture_survives_edit_save',
    'test_missing_font_does_not_prevent_text_roundtrip',
    'test_font_help_is_explicit_and_never_auto_downloads_fonts',
    'test_toolbar_label_preference_persists_without_changing_document',
)
BASELINE_NATIVE = (
    'test_save_as_hwpx_from_hwp_is_a_real_zip_not_renamed_hwp',
    'test_save_as_hwp_and_reconvert_with_the_shipped_cli',
    'test_legacy_hwp_direct_save_still_works',
    'test_cancelled_native_save_as_preserves_original_and_dirty_state',
    'test_multiple_windows_use_real_native_creation',
    'test_corrupt_open_leaves_original_document_usable',
)
COMMON_CHECKS = {
    'test_advanced_table_merge_split_history_reopen': ('grid', 'merged', 'merge-undo', 'merge-redo', 'split', 'split-undo', 'split-redo', 'reopen', 'next-edit', 'source-sha'),
    'test_advanced_existing_nested_cell_edit_history_reopen': ('nested', 'edited', 'undo', 'redo', 'selection-delete', 'delete-undo', 'delete-redo', 'reopen', 'next-edit', 'source-sha'),
    'test_advanced_field_insert_fill_history_reopen': ('inserted', 'insert-undo', 'insert-redo', 'filled', 'fill-undo', 'fill-redo', 'reopen', 'next-edit', 'source-sha'),
    'test_advanced_equation_chord_doubleclick_history_reopen': ('inserted', 'property-undo', 'create-undo', 'create-redo', 'property-redo', 'doubleclick-edit', 'edit-undo', 'edit-redo', 'ink', 'reopen', 'next-edit', 'source-sha'),
    'test_advanced_footnote_endnote_history_reopen': ('footnote', 'foot-text-undo', 'foot-create-undo', 'foot-create-redo', 'foot-text-redo', 'endnote', 'end-text-undo', 'end-create-undo', 'end-create-redo', 'end-text-redo', 'reopen', 'next-edit', 'source-sha'),
    'test_advanced_header_footer_landscape_page_history_reopen': ('header', 'header-undo', 'header-redo', 'footer', 'footer-undo', 'footer-redo', 'page', 'page-undo', 'page-redo', 'page-break', 'break-undo', 'break-redo', 'reopen', 'next-edit', 'source-sha'),
    'test_advanced_textbox_create_edit_history_reopen': ('created', 'create-undo', 'create-redo', 'text', 'text-undo', 'text-redo', 'properties', 'property-undo', 'property-redo', 'reopen', 'next-edit', 'source-sha'),
    'test_supported_table_cells_row_undo_redo_reopen': ('cells', 'row-added', 'undo', 'redo', 'reopen'),
    'test_supported_image_picker_placement_undo_redo_reopen': ('placed', 'undo', 'redo', 'reopen'),
    'test_supported_image_placement_cannot_cross_documents': ('placement-ready', 'replacement-clean'),
    'test_supported_find_replace_and_selected_format': ('replace', 'undo', 'redo', 'selected-style', 'plain-style', 'reopen'),
}
NATIVE_CHECKS = {
    'test_supported_real_windows_korean_ime_commit_cancel_replace_roundtrip': ('actual-Microsoft-profile', 'physical-ascii-korean-switch', 'trusted-composition-commit', 'selected-replacement', 'single-undo-redo', 'actual-os-cancel-preserves-body-selection-history', 'save-as-real-reopen', 'source-sha'),
    'test_supported_external_os_html_menu_keyboard_atomic_roundtrip': ('menu-paste', 'menu-single-undo', 'menu-single-redo', 'menu-source-sha', 'menu-reopen', 'keyboard-paste', 'keyboard-single-undo', 'keyboard-single-redo', 'keyboard-source-sha', 'keyboard-reopen'),
    'test_supported_external_os_bitmap_menu_keyboard_atomic_roundtrip': ('menu-paste', 'menu-single-undo', 'menu-single-redo', 'menu-source-sha', 'menu-reopen', 'keyboard-paste', 'keyboard-single-undo', 'keyboard-single-redo', 'keyboard-source-sha', 'keyboard-reopen'),
    'test_native_new_document_first_save_hwp_cancel_success_reopen': ('new-dirty', 'first-picker-cancel', 'first-save-format-body', 'clean-native-close', 'reopen-next-direct-save'),
    'test_native_new_document_first_save_hwpx_cancel_success_reopen': ('new-dirty', 'first-picker-cancel', 'first-save-format-body', 'clean-native-close', 'reopen-next-direct-save'),
    'test_native_dirty_new_cancel_then_safety_save_preserves_document': ('new-cancel-keeps-source-dirty', 'new-safety-save-before-blank', 'blank-next-save-has-no-old-document', 'safety-saved-source-real-reopen'),
    'test_native_dirty_new_cancelled_safety_picker_keeps_document': ('unsaved-new-dirty', 'safety-picker-cancel-keeps-new-dirty', 'next-real-save-retains-unsaved-text', 'cancelled-safety-real-reopen'),
    'test_supported_keyboard_clipboard_copy_cut_paste': ('clipboard', 'copy-paste', 'cut', 'undo', 'redo', 'reopen'),
    'test_supported_menu_clipboard_copy_cut_paste': ('clipboard', 'copy-paste', 'cut', 'undo', 'redo', 'reopen'),
    'test_supported_gui_pdf_basic_hwp_hwpx_unsaved': ('basic.hwp', 'basic.hwpx', 'unicode.hwpx', 'next-save'),
    'test_supported_gui_pdf_explicit_two_pages_table_image': ('two-pages', 'table', 'image-pattern', 'source-dirty', 'next-save'),
    'test_supported_gui_pdf_cancel_preserves_target_and_dirty': ('picker-target-entered', 'target-preserved', 'no-partial-output', 'source-dirty', 'next-save', 'next-export'),
    'test_supported_recent_owned_hosted_profile_restart_clear': ('hosted-guard', 'owned-inventory', 'restart-open', 'clear', 'restart-empty'),
    'test_supported_real_explorer_drop_and_invalid_recovery': ('owned-drag', 'drop-open', 'source-sha', 'invalid-drop', 'next-save'),
    'test_supported_installed_font_public_selection_roundtrip': ('installed-option', 'selected-font', 'reopen', 'source-sha'),
}
# Canonical lexical order is fixed by these explicit names, never discovery.
BASELINE_NATIVE_CHECKS = {
    'test_multiple_windows_use_real_native_creation': ('two-native-page-hwnds', 'b-save-keeps-a-source-dirty', 'independent-two-saved-bodies', 'b-close-cancel-keeps-b-dirty-a-live', 'b-close-save-keeps-a-live', 'a-next-edit-save-after-b-close', 'a-clean-close-after-b-close', 'both-real-native-reopens'),
}
EXPECTED_BROWSER_CASES = tuple(sorted(PREFIX + name for name in (*BASELINE_COMMON, *COMMON_CHECKS)))
EXPECTED_NATIVE_CASES = tuple(sorted(PREFIX + name for name in (*BASELINE_COMMON, *BASELINE_NATIVE, *COMMON_CHECKS, *NATIVE_CHECKS)))
# Reviewed counts are independent of test discovery and cannot shrink with deletion.
EXPECTED_COUNTS = {'browser': 21, 'native': 42}
HELPERS = (
    'scripts/ensure-korean-ime.ps1', 'scripts/korean_ime_readiness.py',
    'e2e/advanced_edit_oracle.py', 'e2e/advanced_edit_cases.py',
    'e2e/generate-advanced-fixtures.mjs', 'e2e/advanced_edit_fixtures.py',
    'e2e/verify-advanced-fixtures.mjs', 'e2e/native_advanced_inputs.py',
    'e2e/windows_ime.py', 'e2e/native_clipboard.py',
    'e2e/native_ime_cases.py', 'e2e/native_clipboard_cases.py',
    'e2e/native_document_policy.py',
    'e2e/native_document_windows.py',
    'e2e/native_document_lifecycle_cases.py',
    'e2e/run.py', 'e2e/ui_contract.py', 'e2e/driver.py', 'e2e/test_editor.py',
    'e2e/test_hop_followups.py', 'e2e/test_supported_features.py',
    'e2e/hwpx_oracle.py', 'e2e/supported_feature_oracle.py', 'e2e/print_oracle.py',
    'e2e/native_controls.py', 'e2e/native_architecture.py', 'e2e/print_focus.py',
    'e2e/webview_debug.py', 'e2e/requirements.txt',
    'e2e/uia_snapshot.py', 'scripts/releasekit.py', 'scripts/windows_arch.py',
    'scripts/equation_dialog_focus.py', 'scripts/prepare_upstream.py',
)


def manifest(mode):
    if mode not in EXPECTED_COUNTS:
        raise ValueError('UI mode must be browser or native')
    cases = EXPECTED_NATIVE_CASES if mode == 'native' else EXPECTED_BROWSER_CASES
    if len(cases) != EXPECTED_COUNTS[mode] or len(set(cases)) != len(cases):
        raise ValueError('Reviewed UI manifest count or uniqueness changed')
    return cases


def helper_hashes(root: Path):
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in HELPERS}


def validate_frontend_source(binding, helpers):
    if (type(binding) is not dict or set(binding) != {'equationDialogFocus', 'preparedFiles', 'helperSha256'}
            or type(binding['preparedFiles']) is not dict
            or set(binding['preparedFiles']) != set(equation_dialog_focus.SOURCE_FILES)
            or binding['helperSha256'] != {equation_dialog_focus.HELPER: helpers.get(equation_dialog_focus.HELPER)}):
        raise ValueError('Equation dialog focus input source binding mismatch')
    equation_dialog_focus.validate_contract(binding['equationDialogFocus'], binding['preparedFiles'], helpers)


def frontend_source_binding(fixtures: Path, root: Path):
    path = fixtures/'advanced-owned/provenance.json'
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
        raise ValueError('Equation dialog focus input provenance is missing or unbounded')
    value = json.loads(path.read_text(encoding='utf-8'))
    binding = value.get('frontendSource')
    validate_frontend_source(binding, helper_hashes(root))
    return binding


def exact_ids(ids, mode):
    if tuple(ids) != manifest(mode):
        raise ValueError('UI case IDs/order differ from the exact canonical manifest')


def discovered_ids(suite):
    values = []
    for test in suite:
        if hasattr(test, '_tests'):
            values.extend(discovered_ids(test))
        else:
            values.append(test.id())
    return values


def junit_bytes(records):
    counts = Counter(row['status'] for row in records)
    xml = ET.Element('testsuite', name='OpenGeul E2E', tests=str(len(records)),
                     failures=str(counts['failed']), errors=str(counts['error']), skipped=str(counts['skipped']))
    for row in records:
        case = ET.SubElement(xml, 'testcase', name=row['test'], time=str(row['seconds']))
        if row['status'] != 'passed':
            ET.SubElement(case, {'failed': 'failure', 'error': 'error', 'skipped': 'skipped'}[row['status']]).text = row['message']
    return ET.tostring(xml, encoding='utf-8', xml_declaration=True)


def validate_evidence(payload, junit, *, mode, root, before, source_binding):
    """Consume the binding, records and JUnit together; metadata alone is insufficient."""
    expected = manifest(mode)
    if (payload.get('mode') != mode or type(payload.get('expectedTests')) is not int
            or payload.get('expectedTests') != EXPECTED_COUNTS[mode]):
        raise ValueError('Wrong UI execution mode/count')
    if payload.get('caseIds') != list(expected) or payload.get('success') is not True:
        raise ValueError('UI manifest/success does not match the execution contract')
    current = helper_hashes(root)
    if before != current or payload.get('helperSha256') != current or set(before) != set(HELPERS):
        raise ValueError('UI actual helper binding changed before/after execution')
    validate_frontend_source(source_binding, current)
    if payload.get('frontendSource') != source_binding:
        raise ValueError('Equation dialog focus serialized/input source binding mismatch')
    records = payload.get('tests')
    if not isinstance(records, list):
        raise ValueError('Missing UI records')
    exact_ids((row.get('test') for row in records), mode)
    for row in records:
        name = row['test'].removeprefix(PREFIX)
        checks = (*COMMON_CHECKS.get(name, ()), *NATIVE_CHECKS.get(name, ()), *BASELINE_NATIVE_CHECKS.get(name, ()))
        actual = row.get('checks', {})
        if row.get('status') != 'passed' or set(actual) != set(checks) or any(value is not True for value in actual.values()):
            raise ValueError('UI failure/skip or missing/false required oracle check')
    try:
        xml = ET.fromstring(junit)
    except ET.ParseError as error:
        raise ValueError('Unreadable UI JUnit') from error
    if xml.tag != 'testsuite' or any(xml.get(key) != value for key, value in {
            'tests': str(len(expected)), 'failures': '0', 'errors': '0', 'skipped': '0'}.items()):
        raise ValueError('UI JUnit totals differ from records')
    cases = list(xml)
    if any(case.tag != 'testcase' or list(case) for case in cases):
        raise ValueError('UI JUnit contains failure/skip/unexpected records')
    exact_ids((case.get('name') for case in cases), mode)
    json_times = {row['test']: str(row['seconds']) for row in records}
    if any(case.get('time') != json_times[case.get('name')] for case in cases):
        raise ValueError('UI JUnit timing differs from exact JSON records')
    return True


def hosted_recent_guard(environment, *, platform, repository_head, process):
    """Call before any recent-profile mutation. No APPDATA override/profile fiction."""
    literal = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
               'RUNNER_OS': 'Windows', 'GITHUB_REPOSITORY': 'ATLKR/OpenGeul',
               'GITHUB_RUN_ATTEMPT': '1'}
    if platform != 'nt' or any(environment.get(k) != v for k, v in literal.items()):
        raise ValueError('최근 문서 검사는 폐기될 실제 hosted Windows Source profile만 허용합니다')
    if environment.get('GITHUB_JOB') not in ('native-e2e', 'native-e2e-arm64'):
        raise ValueError('Wrong native Source job for recent-profile mutation')
    run = environment.get('GITHUB_RUN_ID', '')
    if not run.isascii() or not run.isdecimal() or int(run) <= 0:
        raise ValueError('Missing actual Source run identity')
    if not repository_head or environment.get('GITHUB_SHA') != repository_head:
        raise ValueError('Recent-profile Source checkout/head binding differs')
    if process.get('native') is not True or process.get('runningAtInspection') is not True:
        raise ValueError('Recent-profile mutation needs a verified actual native process')
    if (process.get('sourceCommit') != repository_head or process.get('sourceRun') != run
            or process.get('runAttempt') != '1'):
        raise ValueError('Actual native process is not bound to this Source run/attempt')
    return True


def require_owned_recent_paths(paths, roots):
    """Outside-owned inventory must fail before selection or clear is dispatched."""
    if not isinstance(paths, list) or len(paths) > 100:
        raise ValueError('Invalid recent-document inventory')
    owned = [canonical_local_path(root) for root in roots]
    for value in paths:
        if not isinstance(value, str):
            raise ValueError('Recent document path must be an observed absolute path')
        path = canonical_local_path(value)
        if not any(path.is_relative_to(root) for root in owned):
            raise ValueError('Outside-owned recent entry; clear is forbidden: '+value)
    return True


def local_windows_dos_path(value):
    """Compare local DOS names, including a legitimate extended drive alias.

    Device/UNC/ADS/traversal names are not aliases of an owned local document.
    Validate before PureWindowsPath can collapse dot components; extended names
    must also obey ordinary DOS filename semantics before removing the prefix.
    """
    if not isinstance(value, str) or not value or len(value) > 32767:
        raise ValueError('Invalid local Windows document path')
    extended = value.startswith('\\\\?\\')
    raw = value[4:] if extended else value
    if extended and '/' in raw:
        raise ValueError('Extended Windows path must use DOS separators')
    raw = raw.replace('/', '\\')
    if not re.match(r'^[A-Za-z]:\\', raw):
        raise ValueError('Only an absolute local Windows DOS drive path is owned')
    components = raw[3:].split('\\')
    for component in components:
        if (not component or component in ('.', '..') or component.endswith((' ', '.'))
                or any(ord(char) < 32 or char in '<>:"|?*' for char in component)
                or re.fullmatch(r'CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³]',
                                component.split('.')[0], re.IGNORECASE)):
            raise ValueError('Unsafe Windows document path component')
    return PureWindowsPath(raw)


def canonical_local_path(value):
    """Resolve actual local filesystem identity, retaining the owned-root gate."""
    raw = str(value) if isinstance(value, Path) else value
    if os.name == 'nt':
        path = Path(local_windows_dos_path(raw)).resolve()
        # A reparse target must remain a local DOS path, too.
        return Path(local_windows_dos_path(str(path)))
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise ValueError('Recent document path must be an observed absolute path')
    return Path(raw).resolve()
