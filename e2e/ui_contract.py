"""명시적인 제품 UI case 계약. 제품/브라우저를 시작하지 않는 독립 gate."""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

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
    'test_supported_table_cells_row_undo_redo_reopen': ('cells', 'row-added', 'undo', 'redo', 'reopen'),
    'test_supported_image_picker_placement_undo_redo_reopen': ('placed', 'undo', 'redo', 'reopen'),
    'test_supported_image_placement_cannot_cross_documents': ('placement-ready', 'replacement-clean'),
    'test_supported_find_replace_and_selected_format': ('replace', 'undo', 'redo', 'selected-style', 'plain-style', 'reopen'),
}
NATIVE_CHECKS = {
    'test_supported_keyboard_clipboard_copy_cut_paste': ('clipboard', 'copy-paste', 'cut', 'undo', 'redo', 'reopen'),
    'test_supported_menu_clipboard_copy_cut_paste': ('clipboard', 'copy-paste', 'cut', 'undo', 'redo', 'reopen'),
    'test_supported_gui_pdf_basic_hwp_hwpx_unsaved': ('basic.hwp', 'basic.hwpx', 'unicode.hwpx', 'next-save'),
    'test_supported_gui_pdf_explicit_two_pages_table_image': ('two-pages', 'table', 'image-pattern', 'source-dirty', 'next-save'),
    'test_supported_gui_pdf_cancel_preserves_target_and_dirty': ('target-preserved', 'no-partial-output', 'source-dirty', 'next-save'),
    'test_supported_recent_owned_hosted_profile_restart_clear': ('hosted-guard', 'owned-inventory', 'restart-open', 'clear', 'restart-empty'),
    'test_supported_real_explorer_drop_and_invalid_recovery': ('owned-drag', 'drop-open', 'source-sha', 'invalid-drop', 'next-save'),
    'test_supported_installed_font_public_selection_roundtrip': ('installed-option', 'selected-font', 'reopen', 'source-sha'),
}
EXPECTED_BROWSER_CASES = tuple(sorted(PREFIX + name for name in (*BASELINE_COMMON, *COMMON_CHECKS)))
EXPECTED_NATIVE_CASES = tuple(sorted(PREFIX + name for name in (*BASELINE_COMMON, *BASELINE_NATIVE, *COMMON_CHECKS, *NATIVE_CHECKS)))
# Reviewed counts are independent of test discovery and cannot shrink with deletion.
EXPECTED_COUNTS = {'browser': 14, 'native': 28}
HELPERS = (
    'e2e/run.py', 'e2e/ui_contract.py', 'e2e/driver.py', 'e2e/test_editor.py',
    'e2e/test_hop_followups.py', 'e2e/test_supported_features.py',
    'e2e/hwpx_oracle.py', 'e2e/supported_feature_oracle.py', 'e2e/print_oracle.py',
    'e2e/native_controls.py', 'e2e/native_architecture.py', 'e2e/print_focus.py',
    'e2e/webview_debug.py', 'e2e/requirements.txt',
    'e2e/uia_snapshot.py', 'scripts/releasekit.py', 'scripts/windows_arch.py',
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


def exact_ids(ids, mode):
    values = list(ids)
    if Counter(values) != Counter(manifest(mode)):
        raise ValueError('UI case IDs differ from the exact reviewed manifest')


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


def validate_evidence(payload, junit, *, mode, root, before):
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
    records = payload.get('tests')
    if not isinstance(records, list):
        raise ValueError('Missing UI records')
    exact_ids((row.get('test') for row in records), mode)
    for row in records:
        name = row['test'].removeprefix(PREFIX)
        checks = (*COMMON_CHECKS.get(name, ()), *NATIVE_CHECKS.get(name, ()))
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
    owned = [Path(root).resolve() for root in roots]
    for value in paths:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('Recent document path must be an observed absolute path')
        path = Path(value).resolve()
        if not any(path.is_relative_to(root) for root in owned):
            raise ValueError('Outside-owned recent entry; clear is forbidden: '+value)
    return True
