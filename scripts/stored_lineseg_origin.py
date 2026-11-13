"""Bind actual imported line segment origin across HWP/HWPX without changing IR checks.

The four original files are immutable pins. Only parser-observed positive stored
rows receive source lineage; runtime replacement/dirty/axis rules remain owned
by the original core. No metadata override or legacy output refresh is accepted.
"""
from pathlib import Path
import hashlib
import stat

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/stored_lineseg_origin.py'
SOURCE_FILES = ('third_party/rhwp/src/parser/body_text.rs',
 'third_party/rhwp/src/parser/hwpx/section.rs',
 'third_party/rhwp/src/serializer/hwpx/section.rs',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs')
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/parser/body_text.rs': '2ee7268ce3551d647eaa12e60e9396307ac5a6107c975e94c03e6db042c685f8',
 'third_party/rhwp/src/parser/hwpx/section.rs': '52525a51471a6d0a2d3c30d4b4829c895d93f8fe121c5baf677a36aa60b9f313',
 'third_party/rhwp/src/serializer/hwpx/section.rs': 'a3b508ba3278959dcda554ee30aaf629bb1ddd51080bf6d25cff3e5ba0c969c6',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs': 'fffb404df94819fbb2f427280ae89a51b8dac37c35535015feb95cf4fd928936'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/parser/body_text.rs': '393dc7ae3ca5d0fc95d1f9808f537a6ba151c2d825b298154ed806f4c07ab44b',
 'third_party/rhwp/src/parser/hwpx/section.rs': '9d31c3b7ac652c01cc137e9ef2ca1df0de734af3010f7706a8613e031f656928',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '7e6e795d59dbe81f5bcbd202f5c00fb0e75e0b644003664340951d886e874c22',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs': '83028d89330c646f316e0dc67a0dd28e280754d5c3c78f8827c8c71262b6820f'}

_BEFORE_0 = """                para.line_segs = parse_para_line_seg(&record.data);
"""
_AFTER_0 = """                para.source_line_seg_vertical_pos = None;
                para.line_segs = parse_para_line_seg(&record.data);
                // OpenGeul: an implementation bit in actual stored bytes is not proof
                // that this row was synthesized by this runtime. Preserve only sized,
                // non-placeholder imported rows; replacement/reflow clears this origin.
                if !para.line_segs.is_empty()
                    && para.line_segs.iter().all(|s| {
                        s.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0
                            && s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0
                            && s.line_height > 0
                            && s.text_height > 0
                    })
                {
                    para.source_line_seg_vertical_pos =
                        Some(para.line_segs.iter().map(|s| s.vertical_pos).collect());
                }
"""

_BEFORE_1 = """    // [Task #1058 후속] HWPX `<hp:p id>` → HWP PARA_HEADER instance_id 매핑.
"""
_AFTER_1 = """    // OpenGeul: an implementation bit in actual stored bytes is not proof
    // that this row was synthesized by this runtime. Preserve only sized,
    // non-placeholder imported rows; replacement/reflow clears this origin.
    if !para.line_segs.is_empty()
        && para.line_segs.iter().all(|s| {
            s.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0
                && s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0
                && s.line_height > 0
                && s.text_height > 0
        })
    {
        para.source_line_seg_vertical_pos =
            Some(para.line_segs.iter().map(|s| s.vertical_pos).collect());
    }

    // [Task #1058 후속] HWPX `<hp:p id>` → HWP PARA_HEADER instance_id 매핑.
"""

_BEFORE_2 = '        let all_synthetic = line_segs_are_all_synthetic(axis_line_segs);\n        Ok(\n            if !axis_line_segs.is_empty() && position_axis_intact && !all_synthetic {\n                // IR 기반 출력 — 원본 lineseg 값 보존 (#177)\n                //\n                // [#5847] reflow 의 구역 단위 vpos 재계산이 원본 캐시 보유 문단의\n                // vertpos 를 문서 누적 좌표로 덮어쓴 경우, 파싱 때 스냅샷해 둔 원본\n                // 쪽-상대 좌표로 되돌려 낸다 — 누적 좌표가 파일로 나가면 한글 2022 가\n                // 캐시를 신뢰해 조판을 폐기한다(08818: 81쪽 → 5쪽). axis 절단은 앞\n                // 접두 슬라이스라 인덱스가 그대로 대응한다.\n                let source_vpos = crate::serializer::line_cache::source_vertical_positions(para)\n                    .map(|v| &v[..axis_line_segs.len()]);\n'
_AFTER_2 = '        // Stored input flags alone do not prove runtime synthesis. A complete\n        // sized source partition retains its parser-observed row ownership.\n        let imported_stored_origin = para\n            .source_line_seg_vertical_pos\n            .as_ref()\n            .is_some_and(|v| v.len() == serializable_line_segs.len())\n            && serializable_line_segs.iter().all(|s| {\n                s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0\n                    && s.line_height > 0\n                    && s.text_height > 0\n            });\n        let all_synthetic = !imported_stored_origin\n            && line_segs_are_all_synthetic(axis_line_segs);\n        Ok(\n            if !axis_line_segs.is_empty() && position_axis_intact && !all_synthetic {\n                // IR 기반 출력 — 원본 lineseg 값 보존 (#177)\n                //\n                // [#5847] reflow 의 구역 단위 vpos 재계산이 원본 캐시 보유 문단의\n                // vertpos 를 문서 누적 좌표로 덮어쓴 경우, 파싱 때 스냅샷해 둔 원본\n                // 쪽-상대 좌표로 되돌려 낸다 — 누적 좌표가 파일로 나가면 한글 2022 가\n                // 캐시를 신뢰해 조판을 폐기한다(08818: 81쪽 → 5쪽). axis 절단은 앞\n                // 접두 슬라이스라 인덱스가 그대로 대응한다.\n                let source_vpos = para\n                    .source_line_seg_vertical_pos\n                    .as_deref()\n                    .filter(|v| v.len() == serializable_line_segs.len())\n                    .map(|v| &v[..axis_line_segs.len()]);\n'

_BEFORE_3 = '        // #5847: 임시 재조판 줄은 파일에 싣지 않는다. 정상 원본 줄은 유지한다.\n        if !crate::serializer::line_cache::can_serialize_hwpx_line_partition(para)\n            || para\n                .line_segs\n                .iter()\n                .all(|line| line.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0)\n        {\n            para.line_segs.clear();\n        } else if let Some(positions) =\n            crate::serializer::line_cache::source_vertical_positions(para).map(<[i32]>::to_vec)\n        {\n            for (line, source) in para.line_segs.iter_mut().zip(positions) {\n                line.vertical_pos = source;\n            }\n        }\n'
_AFTER_3 = '        // Imported sized rows own their stored flags even when bit 31 is set.\n        // Renderer-only suffixes are excluded at this shared HWP/HWPX boundary.\n        let serializable_line_segs = para.serializable_line_segs();\n        let imported_stored_origin = para\n            .source_line_seg_vertical_pos\n            .as_ref()\n            .is_some_and(|v| v.len() == serializable_line_segs.len())\n            && serializable_line_segs.iter().all(|s| {\n                s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0\n                    && s.line_height > 0\n                    && s.text_height > 0\n            });\n        let all_synthetic = !imported_stored_origin\n            && !serializable_line_segs.is_empty()\n            && serializable_line_segs\n                .iter()\n                .all(|s| s.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0);\n        let mut stored = if !crate::serializer::line_cache::can_serialize_hwpx_line_partition(para)\n            || all_synthetic\n        {\n            Vec::new()\n        } else {\n            serializable_line_segs.to_vec()\n        };\n        if let Some(source_vpos) = para\n            .source_line_seg_vertical_pos\n            .as_deref()\n            .filter(|v| v.len() == serializable_line_segs.len())\n        {\n            for (row, original) in stored.iter_mut().zip(source_vpos) {\n                row.vertical_pos = *original;\n            }\n        }\n        para.line_segs = stored;\n        para.layout_only_fill_lines = 0;\n'

REPLACEMENTS = {
    SOURCE_FILES[0]: (_BEFORE_0, _AFTER_0),
    SOURCE_FILES[1]: (_BEFORE_1, _AFTER_1),
    SOURCE_FILES[2]: (_BEFORE_2, _AFTER_2),
    SOURCE_FILES[3]: (_BEFORE_3, _AFTER_3),
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def regular(path):
    path=Path(path)
    for candidate in (path,*path.parents):
        if candidate.exists() or candidate.is_symlink():
            mode=candidate.lstat()
            if stat.S_ISLNK(mode.st_mode) or getattr(mode,'st_file_attributes',0)&0x400:
                raise ValueError('Stored line origin source must not use symlink/reparse paths')
    if not path.is_file():
        raise ValueError('Missing pinned stored line origin source')

def apply(source):
    source=Path(source)
    before={};patched={}
    for name in SOURCE_FILES:
        path=source/name;regular(path)
        raw=path.read_bytes();before[name]=hashlib.sha256(raw).hexdigest()
        if before[name]!=INPUT_SOURCE_SHA256[name]:
            raise ValueError('Stored line origin source drift or reapplication')
        old,new=REPLACEMENTS[name]
        if raw.count(old.encode())!=1:
            raise ValueError('Stored line origin anchor must occur exactly once')
        value=raw.replace(old.encode(),new.encode())
        if hashlib.sha256(value).hexdigest()!=OUTPUT_SOURCE_SHA256[name]:
            raise ValueError('Stored line origin output does not match the frozen patch')
        patched[name]=value
    # Validate the entire source set before writing any member.
    for name,value in patched.items():
        (source/name).write_bytes(value)
    proof={'beforeSha256':before,'afterSha256':{name:sha(source/name) for name in SOURCE_FILES},
           'helperSha256':sha(ROOT/HELPER)}
    return proof

def validate_contract(proof,prepared_files,helpers):
    expected={'beforeSha256':INPUT_SOURCE_SHA256,'afterSha256':OUTPUT_SOURCE_SHA256,
              'helperSha256':sha(ROOT/HELPER)}
    if type(proof) is not dict or set(proof)!=set(expected) or proof!=expected:
        raise ValueError('Exact stored line origin before/after/helper proof is required')
    if type(prepared_files) is not dict or any(prepared_files.get(name)!=value for name,value in OUTPUT_SOURCE_SHA256.items()):
        raise ValueError('Current stored line origin prepared source differs')
    if type(helpers) is not dict or helpers.get(HELPER)!=expected['helperSha256']:
        raise ValueError('Current stored line origin helper is missing or drifted')
