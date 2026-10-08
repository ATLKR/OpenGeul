"""The new native cases supplement, never replace, any of the original 62 editor runs."""
from collections import Counter

EDITOR_METHODS = (
    'test_production_startup_has_no_development_bridge',
    'test_edit_save_reopen_unicode_xml_and_emoji',
    'test_three_roundtrips_preserve_all_edits_once',
    'test_undo_redo_changes_the_saved_document',
    'test_open_and_zoom_do_not_modify_the_source',
    'test_font_help_is_explicit_and_never_auto_downloads_fonts',
    'test_paragraph_fixture_survives_edit_save',
    'test_missing_font_does_not_prevent_text_roundtrip',
    'test_plain_p_keyboard_input_and_saved_document',
    'test_toolbar_label_preference_persists_without_changing_document',
)
NATIVE_METHODS = (
    'test_save_as_hwpx_from_hwp_is_a_real_zip_not_renamed_hwp',
    'test_save_as_hwp_and_reconvert_with_the_shipped_cli',
    'test_cancelled_native_save_as_preserves_original_and_dirty_state',
    'test_legacy_hwp_direct_save_still_works',
    'test_multiple_windows_use_real_native_creation',
    'test_corrupt_open_leaves_original_document_usable',
)
ZOOM_METHODS = (
    'test_native_zoom_960px_file_switch_save_reopen',
    'test_native_zoom_1023px_file_switch_save_reopen',
    'test_native_zoom_1025px_file_switch_save_reopen',
)


def required_methods(mode):
    if mode not in ('browser', 'native'):
        raise ValueError('Unknown E2E mode')
    return EDITOR_METHODS + (NATIVE_METHODS + ZOOM_METHODS if mode == 'native' else ())


def coverage_ok(mode, records):
    required = required_methods(mode)
    names = [record.get('test', '').rsplit('.', 1)[-1] for record in records]
    return (Counter(names) == Counter(required)
            and all(record.get('status') == 'passed' for record in records))
