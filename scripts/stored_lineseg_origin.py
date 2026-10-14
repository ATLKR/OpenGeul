"""Bind actual imported line segment origin across HWP/HWPX without changing IR checks.

The three original files are immutable pins. Only parser-observed positive stored
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
 'third_party/rhwp/src/serializer/hwpx/section.rs')
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/parser/body_text.rs': '6373fe16d27297a4dd242ac0690b695e389e25bb100922817ca0cdb78e393ed8',
 'third_party/rhwp/src/parser/hwpx/section.rs': '7d5d38bb8060bbbd454029f7bbab3cf90af589262ab432b7e95a03034be056b7',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '87e7ec7579b30bf82f2995bd69c846586d5f6743597ddd6fb57eb130883b78a3'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/parser/body_text.rs': '38a73a4c40bb34a889166d0965c7db08d2ce383fdf99a66e65bb5884e566cd57',
 'third_party/rhwp/src/parser/hwpx/section.rs': '27306e4d8b2832680d2407c19aaf80cf1124026d0f1794c0677429a91a482449',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '527676d0109f326f373b770aa619e33453d439e77fc101bafd5c075b3c4da8b6'}

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

_BEFORE_2 = """    let all_synthetic = !axis_line_segs.is_empty()
        && axis_line_segs
            .iter()
            .all(|s| s.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0);

    if !axis_line_segs.is_empty() && position_axis_intact && !all_synthetic {
        // IR 기반 출력 — 원본 lineseg 값 보존 (#177)
        //
        // [#5847] reflow 의 구역 단위 vpos 재계산이 원본 캐시 보유 문단의
        // vertpos 를 문서 누적 좌표로 덮어쓴 경우, 파싱 때 스냅샷해 둔 원본
        // 쪽-상대 좌표로 되돌려 낸다 — 누적 좌표가 파일로 나가면 한글 2022 가
        // 캐시를 신뢰해 조판을 폐기한다(08818: 81쪽 → 5쪽). axis 절단은 앞
        // 접두 슬라이스라 인덱스가 그대로 대응한다.
        let source_vpos = para
            .source_line_seg_vertical_pos
            .as_deref()
            .filter(|v| v.len() == para.line_segs.len())
            .map(|v| &v[..axis_line_segs.len()]);
"""
_AFTER_2 = """    // Imported sized rows retain exact flags and coordinates across formats.
    // A partial/stale snapshot cannot promote runtime-only synthetic rows.
    let imported_stored_origin = para
        .source_line_seg_vertical_pos
        .as_ref()
        .is_some_and(|v| v.len() == serializable_line_segs.len())
        && serializable_line_segs.iter().all(|s| {
            s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0
                && s.line_height > 0
                && s.text_height > 0
        });
    let all_synthetic = !imported_stored_origin
        && !axis_line_segs.is_empty()
        && axis_line_segs
            .iter()
            .all(|s| s.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0);

    if !axis_line_segs.is_empty() && position_axis_intact && !all_synthetic {
        // IR 기반 출력 — 원본 lineseg 값 보존 (#177)
        //
        // [#5847] reflow 의 구역 단위 vpos 재계산이 원본 캐시 보유 문단의
        // vertpos 를 문서 누적 좌표로 덮어쓴 경우, 파싱 때 스냅샷해 둔 원본
        // 쪽-상대 좌표로 되돌려 낸다 — 누적 좌표가 파일로 나가면 한글 2022 가
        // 캐시를 신뢰해 조판을 폐기한다(08818: 81쪽 → 5쪽). axis 절단은 앞
        // 접두 슬라이스라 인덱스가 그대로 대응한다.
        let source_vpos = para
            .source_line_seg_vertical_pos
            .as_deref()
            .filter(|v| v.len() == serializable_line_segs.len())
            .map(|v| &v[..axis_line_segs.len()]);
"""

REPLACEMENTS = {
    SOURCE_FILES[0]: (_BEFORE_0, _AFTER_0),
    SOURCE_FILES[1]: (_BEFORE_1, _AFTER_1),
    SOURCE_FILES[2]: (_BEFORE_2, _AFTER_2),
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
