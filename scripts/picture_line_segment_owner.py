"""Pin the public picture TAC row-owner invalidation without geometry changes."""
from pathlib import Path
import hashlib
import stat

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/picture_line_segment_owner.py'
SOURCE_FILES = ('third_party/rhwp/src/document_core/commands/object_ops/picture.rs',)
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/document_core/commands/object_ops/picture.rs': '7924191598d0fafb79c53543b5518864f20485565c6b3087c211c2bec632d6d2'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/document_core/commands/object_ops/picture.rs': '8247ad3f73d90e153b8f4ec565f925791aefddb1fc2490f05c1ae4b78eea6534'}
REPLACEMENTS = (('            let stored_end = crate::renderer::composer::paragraph_flow_end(para);\n            let has_text = !para.text.is_empty();\n            if should_migrate_to_inline {', '            let stored_end = crate::renderer::composer::paragraph_flow_end(para);\n            let has_text = !para.text.is_empty();\n            Self::invalidate_picture_line_origin(para);\n            if should_migrate_to_inline {'), ('            if !was_tac && now_tac {\n                Self::migrate_picture_floating_to_inline(', '            if was_tac != now_tac {\n                Self::invalidate_picture_line_origin(inner_para);\n            }\n            if !was_tac && now_tac {\n                Self::migrate_picture_floating_to_inline('), ('    /// TAC 그림을 자리차지 개체로 되돌릴 때, 텍스트 없는 그림 전용 문단의\n', "    // Geometry-only TAC migration cannot retain the replaced row owner's vpos.\n    // Keep the unchanged source text axis and dirty state, and exclude any\n    // renderer-appended suffix before publishing the row vector.\n    fn invalidate_picture_line_origin(para: &mut crate::model::paragraph::Paragraph) {\n        let source_axis = para.hwpx_axis_shift;\n        let was_dirty = para.stored_text_partition_is_dirty();\n        let rows = para.serializable_line_segs().to_vec();\n        para.replace_line_segs(rows);\n        para.hwpx_axis_shift = source_axis;\n        if was_dirty {\n            para.invalidate_layout_inputs();\n        }\n    }\n\n    /// TAC 그림을 자리차지 개체로 되돌릴 때, 텍스트 없는 그림 전용 문단의\n"))

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
