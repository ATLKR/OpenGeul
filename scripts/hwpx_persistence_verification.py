"""Pin conservative independent HWPX persistence expectation and strict HF rows."""
from pathlib import Path
import hashlib
import stat

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/hwpx_persistence_verification.py'
SOURCE_FILES = ('third_party/rhwp/src/cli/commands/edit/runtime.rs',
 'third_party/rhwp/src/serializer/hwpx/roundtrip.rs',
 'third_party/rhwp/src/serializer/hwpx/section.rs',
 'third_party/rhwp/src/model/identity/walk.rs',
 'third_party/rhwp/src/model/identity.rs',
 'third_party/rhwp/src/serializer/hwpx/field.rs',
 'third_party/rhwp/src/serializer/line_cache.rs',
 'third_party/rhwp/src/document_core/commands/object_ops/picture_inline_migration.rs',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs',
 'third_party/rhwp/src/serializer/hwpx_lineage_lines.rs',
 'third_party/rhwp/src/serializer/cfb_writer.rs',
 'third_party/rhwp/src/model/document.rs')
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/cli/commands/edit/runtime.rs': 'f72c07514749473538aa16c002905c724c7643aad88844a089ae2342e7254d9e',
 'third_party/rhwp/src/serializer/hwpx/roundtrip.rs': '07e95e9255946772e0142f411f7195321a0dd210d670d5538024560e424936b3',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '7e6e795d59dbe81f5bcbd202f5c00fb0e75e0b644003664340951d886e874c22',
 'third_party/rhwp/src/model/identity/walk.rs': '6381910852edfcdeed8916a8b8f8998d6a06d3568a5f420e3f5cf834dbe87d08',
 'third_party/rhwp/src/model/identity.rs': 'f9791f7dcce9f81e2fc260a0519971bd45838b8b9fb5453eba9682cf6d52efd9',
 'third_party/rhwp/src/serializer/hwpx/field.rs': 'eba22b7936e3e36ef30ee5aafe57ab320e6f1a86dcd37bcdf5476616c593b505',
 'third_party/rhwp/src/serializer/line_cache.rs': '8973f204008c077051515eb6eef2a327e47535887150505de7ac88c4a1ca515f',
 'third_party/rhwp/src/document_core/commands/object_ops/picture_inline_migration.rs': '8da5248dc46339f9c00f292b38e265ea038707436edd76ff253b71943d47032e',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs': '83028d89330c646f316e0dc67a0dd28e280754d5c3c78f8827c8c71262b6820f',
 'third_party/rhwp/src/serializer/hwpx_lineage_lines.rs': '3b9d5e503beedd3df2e839d05d91eb5901ddfca4e3f2fb63ab3c33a83712d367',
 'third_party/rhwp/src/serializer/cfb_writer.rs': '91f988913f37f7aea3395c3df776bba5b70df6acf6ff3469e155a0018d2b59ed',
 'third_party/rhwp/src/model/document.rs': 'd878510e7f089c6cd7da29adab79a0ccf7dbc674748a6aeaa4d6560e47873e2a'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/cli/commands/edit/runtime.rs': '9750d3e4bf8f87f3bc633fd66eaa3b814bc5ccc3883cd018597c56aeb5599dc4',
 'third_party/rhwp/src/serializer/hwpx/roundtrip.rs': 'd6d40257180143824e21ddbc90d83b4717338bc7d8e91976518f5c06bd8a29fa',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '7e6e795d59dbe81f5bcbd202f5c00fb0e75e0b644003664340951d886e874c22',
 'third_party/rhwp/src/model/identity/walk.rs': '6381910852edfcdeed8916a8b8f8998d6a06d3568a5f420e3f5cf834dbe87d08',
 'third_party/rhwp/src/model/identity.rs': 'f9791f7dcce9f81e2fc260a0519971bd45838b8b9fb5453eba9682cf6d52efd9',
 'third_party/rhwp/src/serializer/hwpx/field.rs': 'bef1e3781454b1ae3ff24fe45f74163d24e2eb52c3f6e6791588ed23e0e8559e',
 'third_party/rhwp/src/serializer/line_cache.rs': '8973f204008c077051515eb6eef2a327e47535887150505de7ac88c4a1ca515f',
 'third_party/rhwp/src/document_core/commands/object_ops/picture_inline_migration.rs': '8da5248dc46339f9c00f292b38e265ea038707436edd76ff253b71943d47032e',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs': '83028d89330c646f316e0dc67a0dd28e280754d5c3c78f8827c8c71262b6820f',
 'third_party/rhwp/src/serializer/hwpx_lineage_lines.rs': '3b9d5e503beedd3df2e839d05d91eb5901ddfca4e3f2fb63ab3c33a83712d367',
 'third_party/rhwp/src/serializer/cfb_writer.rs': '91f988913f37f7aea3395c3df776bba5b70df6acf6ff3469e155a0018d2b59ed',
 'third_party/rhwp/src/model/document.rs': 'd878510e7f089c6cd7da29adab79a0ccf7dbc674748a6aeaa4d6560e47873e2a'}
REPLACEMENTS = {'third_party/rhwp/src/serializer/hwpx/roundtrip.rs': (('/// IR diff 결과 — 발견된 차이 목록을 보관.\n',
                                                        '/// Independent stored-model expectation for HWPX '
                                                        'edit-save verification.\n'
                                                        '/// This never reads the serialized output or '
                                                        'changes the open live document.\n'
                                                        '/// Only cache partitions that the existing writer '
                                                        'proves non-persistent are\n'
                                                        '/// removed. Context-dependent slot/axis '
                                                        'transformations remain fail-closed in\n'
                                                        '/// the original comparator; this is not a general '
                                                        'serialization projection.\n'
                                                        'pub fn hwpx_persistence_document(live: &Document) '
                                                        '-> Document {\n'
                                                        '    use crate::model::identity::walk::{walk, '
                                                        'Node};\n'
                                                        '    use crate::model::paragraph::{LineSeg, '
                                                        'Paragraph};\n'
                                                        '\n'
                                                        '    fn project(para: &mut Paragraph) {\n'
                                                        '        let serializable_line_segs = '
                                                        'para.serializable_line_segs();\n'
                                                        '        // The exact owner predicate is copied '
                                                        'mechanically from the pinned\n'
                                                        '        // HWPX writer. Here the entire '
                                                        'serializable partition must be derived;\n'
                                                        '        // mixed/context-dependent axis subsets '
                                                        'stay in the strict comparison.\n'
                                                        '        let axis_line_segs = '
                                                        'serializable_line_segs;\n'
                                                        '        let imported_stored_origin = para\n'
                                                        '            .source_line_seg_vertical_pos\n'
                                                        '            .as_ref()\n'
                                                        '            .is_some_and(|v| v.len() == '
                                                        'serializable_line_segs.len())\n'
                                                        '            && '
                                                        'serializable_line_segs.iter().all(|s| {\n'
                                                        '                s.tag & LineSeg::TAG_EMPTY_SEGMENT '
                                                        '== 0\n'
                                                        '                    && s.line_height > 0\n'
                                                        '                    && s.text_height > 0\n'
                                                        '            });\n'
                                                        '        let all_synthetic = '
                                                        '!imported_stored_origin\n'
                                                        '            && !axis_line_segs.is_empty()\n'
                                                        '            && axis_line_segs\n'
                                                        '                .iter()\n'
                                                        '                .all(|s| s.tag & '
                                                        'LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0);\n'
                                                        '        let mut stored = if '
                                                        '!crate::serializer::line_cache::can_serialize_hwpx_line_partition(para) '
                                                        '|| all_synthetic {\n'
                                                        '            Vec::new()\n'
                                                        '        } else {\n'
                                                        '            serializable_line_segs.to_vec()\n'
                                                        '        };\n'
                                                        '        if let Some(source_vpos) = '
                                                        'para.source_line_seg_vertical_pos.as_deref()\n'
                                                        '            .filter(|v| v.len() == '
                                                        'serializable_line_segs.len())\n'
                                                        '        {\n'
                                                        '            for (row, original) in '
                                                        'stored.iter_mut().zip(source_vpos) {\n'
                                                        '                row.vertical_pos = *original;\n'
                                                        '            }\n'
                                                        '        }\n'
                                                        "        // Change only the clone's cache partition; "
                                                        'retain axes, dirty state,\n'
                                                        '        // source ownership, text, formatting, '
                                                        'controls and all live history.\n'
                                                        '        para.line_segs = stored;\n'
                                                        '        para.layout_only_fill_lines = 0;\n'
                                                        '    }\n'
                                                        '    fn paragraphs(paras: &mut [Paragraph]) {\n'
                                                        '        walk(paras, |node| {\n'
                                                        '            if let Node::Paragraph(para) = node { '
                                                        'project(para); }\n'
                                                        '            Ok(())\n'
                                                        '        }).expect("the paragraph projection '
                                                        'callback is infallible");\n'
                                                        '    }\n'
                                                        '    let mut expected = live.clone();\n'
                                                        '    for section in &mut expected.sections {\n'
                                                        '        paragraphs(&mut section.paragraphs);\n'
                                                        '        for master in &mut '
                                                        'section.section_def.master_pages {\n'
                                                        '            paragraphs(&mut master.paragraphs);\n'
                                                        '        }\n'
                                                        '    }\n'
                                                        '    expected\n'
                                                        '}\n'
                                                        '\n'
                                                        '/// IR diff 결과 — 발견된 차이 목록을 보관.\n'),
                                                       ('            (Control::Endnote(na), '
                                                        'Control::Endnote(nb)) => {\n'
                                                        '                for (k, (qa, qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    let p = '
                                                        'format!("{path}/ctrl[{ci}]en.p[{k}]");\n'
                                                        '                    diff_paragraph_linesegs(out, '
                                                        'section, paragraph, &p, qa, qb);\n'
                                                        '                }\n'
                                                        '            }\n',
                                                        '            (Control::Endnote(na), '
                                                        'Control::Endnote(nb)) => {\n'
                                                        '                for (k, (qa, qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    let p = '
                                                        'format!("{path}/ctrl[{ci}]en.p[{k}]");\n'
                                                        '                    diff_paragraph_linesegs(out, '
                                                        'section, paragraph, &p, qa, qb);\n'
                                                        '                }\n'
                                                        '            }\n'
                                                        '            (Control::Header(na), '
                                                        'Control::Header(nb)) => {\n'
                                                        '                for (k, (qa, qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    let p = '
                                                        'format!("{path}/ctrl[{ci}]hdr.p[{k}]");\n'
                                                        '                    diff_paragraph_linesegs(out, '
                                                        'section, paragraph, &p, qa, qb);\n'
                                                        '                }\n'
                                                        '            }\n'
                                                        '            (Control::Footer(na), '
                                                        'Control::Footer(nb)) => {\n'
                                                        '                for (k, (qa, qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    let p = '
                                                        'format!("{path}/ctrl[{ci}]ftr.p[{k}]");\n'
                                                        '                    diff_paragraph_linesegs(out, '
                                                        'section, paragraph, &p, qa, qb);\n'
                                                        '                }\n'
                                                        '            }\n'),
                                                       ('    /// 문단의 `line_segs` 불일치 — lineseg 원본 보존 게이트 '
                                                        '(#1380).\n',
                                                        '    /// Exact persistent text mismatch, without '
                                                        'exposing private text in diagnostics.\n'
                                                        '    ParagraphText { section: usize, paragraph: '
                                                        'usize, path: String,\n'
                                                        '                    expected_char_count: usize, '
                                                        'actual_char_count: usize },\n'
                                                        '    /// Effective stored field identity; instance '
                                                        'IDs and other runtime bits are excluded.\n'
                                                        '    FieldIdentity { section: usize, paragraph: '
                                                        "usize, path: String, changed: Vec<&'static str> },\n"
                                                        '    /// Owned Header/Footer paragraph cardinality '
                                                        'is persistent semantic data.\n'
                                                        '    NestedParagraphCount { section: usize, '
                                                        'paragraph: usize, path: String,\n'
                                                        '                           expected: usize, actual: '
                                                        'usize },\n'
                                                        '    /// 문단의 `line_segs` 불일치 — lineseg 원본 보존 게이트 '
                                                        '(#1380).\n'),
                                                       ('            ParagraphCharShapes {\n',
                                                        '            ParagraphText { section, paragraph, '
                                                        'path, expected_char_count, actual_char_count } =>\n'
                                                        '                write!(f,"section[{}] '
                                                        'paragraph[{}]{} text differs: expected_chars={} '
                                                        'actual_chars={}",section,paragraph,path,expected_char_count,actual_char_count),\n'
                                                        '            FieldIdentity { section, paragraph, '
                                                        'path, changed } =>\n'
                                                        '                write!(f,"section[{}] '
                                                        'paragraph[{}]{} field identity differs: '
                                                        '{}",section,paragraph,path,changed.join(",")),\n'
                                                        '            NestedParagraphCount { section, '
                                                        'paragraph, path, expected, actual } =>\n'
                                                        '                write!(f,"section[{}] '
                                                        'paragraph[{}]{} nested paragraphs: expected={} '
                                                        'actual={}",section,paragraph,path,expected,actual),\n'
                                                        '            ParagraphCharShapes {\n'),
                                                       ('    use crate::model::control::Control;\n'
                                                        '\n'
                                                        '    let ca = &pa.char_shapes;',
                                                        '    use crate::model::control::Control;\n'
                                                        '\n'
                                                        '    if pa.text != pb.text {\n'
                                                        '        diff.push(IrDifference::ParagraphText { '
                                                        'section, paragraph, path: path.to_string(),\n'
                                                        '            expected_char_count: '
                                                        'pa.text.chars().count(), actual_char_count: '
                                                        'pb.text.chars().count() });\n'
                                                        '    }\n'
                                                        '    let ca = &pa.char_shapes;'),
                                                       ('            (Control::Field(fa), '
                                                        'Control::Field(fb)) => {\n'
                                                        '                if fa.raw_parameters_xml != '
                                                        'fb.raw_parameters_xml {',
                                                        '            (Control::Field(fa), '
                                                        'Control::Field(fb)) => {\n'
                                                        '                let mut changed = Vec::new();\n'
                                                        '                if '
                                                        'fa.ctrl_data_name.as_deref().unwrap_or("") != '
                                                        'fb.ctrl_data_name.as_deref().unwrap_or("") { '
                                                        'changed.push("name"); }\n'
                                                        '                if fa.command != fb.command { '
                                                        'changed.push("command"); }\n'
                                                        '                if '
                                                        'super::field::field_type_attr(fa) != '
                                                        'super::field::field_type_attr(fb) { '
                                                        'changed.push("effective_type"); }\n'
                                                        '                if !changed.is_empty() { '
                                                        'diff.push(IrDifference::FieldIdentity { section, '
                                                        'paragraph,\n'
                                                        '                    path: '
                                                        'format!("{path}/ctrl[{ci}]field"), changed }); }\n'
                                                        '                if fa.raw_parameters_xml != '
                                                        'fb.raw_parameters_xml {'),
                                                       ('            (Control::Endnote(na), '
                                                        'Control::Endnote(nb)) => {\n'
                                                        '                for (k, (qa, qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    let p = '
                                                        'format!("{path}/ctrl[{ci}]en.p[{k}]");\n'
                                                        '                    '
                                                        'diff_paragraph_char_shapes(diff, section, '
                                                        'paragraph, &p, qa, qb);\n'
                                                        '                }\n'
                                                        '            }\n',
                                                        '            (Control::Endnote(na), '
                                                        'Control::Endnote(nb)) => {\n'
                                                        '                for (k, (qa, qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    let p = '
                                                        'format!("{path}/ctrl[{ci}]en.p[{k}]");\n'
                                                        '                    '
                                                        'diff_paragraph_char_shapes(diff, section, '
                                                        'paragraph, &p, qa, qb);\n'
                                                        '                }\n'
                                                        '            }\n'
                                                        '            (Control::Header(na), '
                                                        'Control::Header(nb)) => {\n'
                                                        '                let owner = '
                                                        'format!("{path}/ctrl[{ci}]hdr");\n'
                                                        '                if na.paragraphs.len() != '
                                                        'nb.paragraphs.len() {\n'
                                                        '                    '
                                                        'diff.push(IrDifference::NestedParagraphCount { '
                                                        'section, paragraph, path: owner.clone(), expected: '
                                                        'na.paragraphs.len(), actual: nb.paragraphs.len() '
                                                        '});\n'
                                                        '                }\n'
                                                        '                for (k, (qa,qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    '
                                                        'diff_paragraph_char_shapes(diff,section,paragraph,&format!("{owner}.p[{k}]"),qa,qb);\n'
                                                        '                }\n'
                                                        '            }\n'
                                                        '            (Control::Footer(na), '
                                                        'Control::Footer(nb)) => {\n'
                                                        '                let owner = '
                                                        'format!("{path}/ctrl[{ci}]ftr");\n'
                                                        '                if na.paragraphs.len() != '
                                                        'nb.paragraphs.len() {\n'
                                                        '                    '
                                                        'diff.push(IrDifference::NestedParagraphCount { '
                                                        'section, paragraph, path: owner.clone(), expected: '
                                                        'na.paragraphs.len(), actual: nb.paragraphs.len() '
                                                        '});\n'
                                                        '                }\n'
                                                        '                for (k, (qa,qb)) in '
                                                        'na.paragraphs.iter().zip(nb.paragraphs.iter()).enumerate() '
                                                        '{\n'
                                                        '                    '
                                                        'diff_paragraph_char_shapes(diff,section,paragraph,&format!("{owner}.p[{k}]"),qa,qb);\n'
                                                        '                }\n'
                                                        '            }\n'),
                                                       ('    /// Exact persistent text mismatch, without '
                                                        'exposing private text in diagnostics.\n',
                                                        '    /// Same-ID persistent font height corruption, '
                                                        'without treating resource counts as values.\n'
                                                        '    CharShapeProperty { index: usize, property: '
                                                        "&'static str, expected: i64, actual: i64 },\n"
                                                        '    /// Exact persistent text mismatch, without '
                                                        'exposing private text in diagnostics.\n'),
                                                       ('            ParagraphText { section, paragraph, '
                                                        'path, expected_char_count, actual_char_count } =>\n',
                                                        '            CharShapeProperty { index, property, '
                                                        'expected, actual } =>\n'
                                                        '                write!(f,"char_shape[{}].{} '
                                                        'differs: expected={} '
                                                        'actual={}",index,property,expected,actual),\n'
                                                        '            ParagraphText { section, paragraph, '
                                                        'path, expected_char_count, actual_char_count } '
                                                        '=>\n'),
                                                       ('    if a.doc_info.para_shapes.len() != '
                                                        'b.doc_info.para_shapes.len() {',
                                                        '    for (index,(expected,actual)) in '
                                                        'a.doc_info.char_shapes.iter().zip(&b.doc_info.char_shapes).enumerate() '
                                                        '{\n'
                                                        '        if expected.base_size != actual.base_size '
                                                        '{\n'
                                                        '            '
                                                        'diff.push(IrDifference::CharShapeProperty { index, '
                                                        'property: "base_size",\n'
                                                        '                expected: expected.base_size as '
                                                        'i64, actual: actual.base_size as i64 });\n'
                                                        '        }\n'
                                                        '    }\n'
                                                        '    if a.doc_info.para_shapes.len() != '
                                                        'b.doc_info.para_shapes.len() {'),
                                                       ('                if fa.command != fb.command { '
                                                        'changed.push("command"); }',
                                                        '                if fa.command != fb.command { '
                                                        'changed.push("command"); }\n'
                                                        '                if fa.is_editable_in_form() != '
                                                        'fb.is_editable_in_form() { '
                                                        'changed.push("editable"); }\n'
                                                        '                if fa.is_dirty() != fb.is_dirty() { '
                                                        'changed.push("dirty"); }')),
 'third_party/rhwp/src/cli/commands/edit/runtime.rs': (('        '
                                                        'rhwp::serializer::hwpx::roundtrip::diff_exported_hwpx_documents(\n'
                                                        '            doc.document(),\n'
                                                        '            reloaded.document(),\n'
                                                        '        )',
                                                        '        // Expected content comes from the live '
                                                        'model, never the saved output.\n'
                                                        '        let expected = '
                                                        'rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(doc.document());\n'
                                                        '        let actual = '
                                                        'rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(reloaded.document());\n'
                                                        '        '
                                                        'rhwp::serializer::hwpx::roundtrip::diff_documents(&expected, '
                                                        '&actual)'),),
 'third_party/rhwp/src/serializer/hwpx/field.rs': (('fn field_type_attr(field: &Field) -> &str {',
                                                    'pub(crate) fn field_type_attr(field: &Field) -> &str '
                                                    '{'),)}
OWNER_POLICY = '        let imported_stored_origin = para\n            .source_line_seg_vertical_pos\n            .as_ref()\n            .is_some_and(|v| v.len() == serializable_line_segs.len())\n            && serializable_line_segs.iter().all(|s| {\n                s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0\n                    && s.line_height > 0\n                    && s.text_height > 0\n            });\n        let all_synthetic = !imported_stored_origin\n            && line_segs_are_all_synthetic(axis_line_segs);\n'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def regular(path):
    path=Path(path)
    for candidate in (path,*path.parents):
        if candidate.exists() or candidate.is_symlink():
            info=candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('HWPX persistence source must not use symlink/reparse paths')
    if not path.is_file():raise ValueError('Missing pinned HWPX persistence source')

def apply(source):
    source=Path(source);pending={};before={}
    # Validate every dependency and prospective output before changing any file.
    for name in SOURCE_FILES:
        path=source/name;regular(path);raw=path.read_bytes();before[name]=hashlib.sha256(raw).hexdigest()
        if before[name]!=INPUT_SOURCE_SHA256[name]:raise ValueError('HWPX persistence source drift or reapplication')
        value=raw
        for old,new in REPLACEMENTS.get(name,()):
            if value.count(old.encode())!=1:raise ValueError('HWPX persistence anchor must occur exactly once')
            value=value.replace(old.encode(),new.encode())
        if hashlib.sha256(value).hexdigest()!=OUTPUT_SOURCE_SHA256[name]:raise ValueError('HWPX persistence output differs from frozen patch')
        pending[name]=value
    writer=pending['third_party/rhwp/src/serializer/hwpx/section.rs'].decode()
    if writer.count(OWNER_POLICY)!=1:raise ValueError('Exact original writer owner policy required')
    for name,value in pending.items():
        if name in REPLACEMENTS:(source/name).write_bytes(value)
    return {'beforeSha256':before,'afterSha256':{n:sha(source/n) for n in SOURCE_FILES},'helperSha256':sha(ROOT/HELPER)}

def validate_contract(proof,prepared_files,helpers):
    expected={'beforeSha256':INPUT_SOURCE_SHA256,'afterSha256':OUTPUT_SOURCE_SHA256,'helperSha256':sha(ROOT/HELPER)}
    if type(proof) is not dict or set(proof)!=set(expected) or proof!=expected:raise ValueError('Exact HWPX persistence before/after/helper proof required')
    if type(prepared_files) is not dict or any(prepared_files.get(n)!=d for n,d in OUTPUT_SOURCE_SHA256.items()):raise ValueError('Current HWPX persistence prepared source differs')
    if type(helpers) is not dict or helpers.get(HELPER)!=expected['helperSha256']:raise ValueError('Current HWPX persistence helper missing or drifted')
