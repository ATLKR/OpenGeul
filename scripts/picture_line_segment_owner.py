"""Pin the public picture TAC row-owner invalidation without geometry changes."""
from pathlib import Path
import hashlib
import stat

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/picture_line_segment_owner.py'
SOURCE_FILES = ('third_party/rhwp/src/document_core/commands/object_ops/picture.rs',)
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/document_core/commands/object_ops/picture.rs': 'd5d3f7ea45606c98ab2f0a4325aacac6a3ed9b8d3d2cb09532d1c2c04063150f'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/document_core/commands/object_ops/picture.rs': '6be03f1fc667ffaba63694f7be8805fd290ee6710cd555629c3d591953ca68a9'}
REPLACEMENTS = (('            if should_migrate_to_inline {\n                let crate::model::paragraph::Paragraph {', '            Self::invalidate_picture_line_origin(para);\n            if should_migrate_to_inline {\n                let crate::model::paragraph::Paragraph {'), ('            if !was_tac && now_tac {\n                if let crate::model::control::Control::Picture(pic_box) =', '            if was_tac != now_tac {\n                Self::invalidate_picture_line_origin(inner_para);\n                // Text-bearing header/footer reverse migration has no row rebuild.\n                // Its old geometry is a template until the existing recompose runs.\n                if was_tac && (!inner_para.text.is_empty() || !inner_para.char_offsets.is_empty()) {\n                    inner_para.invalidate_layout_inputs();\n                }\n            }\n            if !was_tac && now_tac {\n                if let crate::model::control::Control::Picture(pic_box) ='), ('    /// [Task #1151 v2] Floating picture → inline 마이그레이션 (H1 정합).\n', "    // Geometry-only TAC migration cannot retain the replaced row owner's vpos.\n    // Keep the unchanged source text axis and dirty state, and exclude any\n    // renderer-appended suffix before publishing the row vector.\n    fn invalidate_picture_line_origin(para: &mut crate::model::paragraph::Paragraph) {\n        let source_axis = para.hwpx_axis_shift;\n        let was_dirty = para.stored_text_partition_is_dirty();\n        let rows = para.serializable_line_segs().to_vec();\n        para.replace_line_segs(rows);\n        para.hwpx_axis_shift = source_axis;\n        if was_dirty {\n            para.invalidate_layout_inputs();\n        }\n    }\n\n    /// [Task #1151 v2] Floating picture → inline 마이그레이션 (H1 정합).\n"))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def regular(path):
    path = Path(path)
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Picture row owner source must not use symlink/reparse paths')
    if not path.is_file():
        raise ValueError('Missing pinned picture row owner source')

def apply(source):
    source = Path(source)
    name = SOURCE_FILES[0]; path = source/name; regular(path)
    raw = path.read_bytes(); before = hashlib.sha256(raw).hexdigest()
    if before != INPUT_SOURCE_SHA256[name]:
        raise ValueError('Picture row owner source drift or reapplication')
    value = raw
    for old, new in REPLACEMENTS:
        if value.count(old.encode()) != 1:
            raise ValueError('Picture row owner anchor must occur exactly once')
        value = value.replace(old.encode(), new.encode())
    if hashlib.sha256(value).hexdigest() != OUTPUT_SOURCE_SHA256[name]:
        raise ValueError('Picture row owner output differs from frozen patch')
    path.write_bytes(value)
    return {'beforeSha256': {name: before}, 'afterSha256': {name: sha(path)},
            'helperSha256': sha(ROOT/HELPER)}

def validate_contract(proof, prepared_files, helpers):
    expected = {'beforeSha256': INPUT_SOURCE_SHA256, 'afterSha256': OUTPUT_SOURCE_SHA256,
                'helperSha256': sha(ROOT/HELPER)}
    if type(proof) is not dict or set(proof) != set(expected) or proof != expected:
        raise ValueError('Exact picture row owner before/after/helper proof required')
    if type(prepared_files) is not dict or any(prepared_files.get(name) != digest for name,digest in OUTPUT_SOURCE_SHA256.items()):
        raise ValueError('Current picture row owner prepared source differs')
    if type(helpers) is not dict or helpers.get(HELPER) != expected['helperSha256']:
        raise ValueError('Current picture row owner helper is missing or drifted')
