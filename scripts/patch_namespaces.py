"""Preserve header XML namespaces in the pinned native and WASM rhwp serializer path."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
ROOT = Path(__file__).resolve().parents[1]

def patch(source: Path) -> None:
    header = source/'src/parser/hwpx/header.rs'
    text = header.read_text(encoding='utf-8')
    edits = [
        ('use super::HwpxError;', 'use super::HwpxError;\n#[path = "opengeul_namespaces.rs"]\nmod opengeul_namespaces;\nuse opengeul_namespaces::HeaderNamespaces;'),
        ('    let mut doc_info = DocInfo::default();', '    let namespaces = HeaderNamespaces::new(xml).map_err(HwpxError::XmlError)?;\n    let mut doc_info = DocInfo::default();'),
        ('parse_numbering(e, &mut reader, &mut doc_info, xml)?;', 'parse_numbering(e, &mut reader, &mut doc_info, xml, &namespaces)?;'),
        ('parse_bullet_hwpx(e, &mut reader, xml)?;', 'parse_bullet_hwpx(e, &mut reader, xml, &namespaces)?;'),
        ('    doc_info.hwpx_head_tail = extract_head_tail(xml);', '    doc_info.hwpx_head_tail = namespaces.tail().map_err(HwpxError::XmlError)?.or_else(|| extract_head_tail(xml));'),
        ('    doc_info.memo_properties_xml = extract_memo_properties(xml);', '    doc_info.memo_properties_xml = namespaces.memo_properties().map_err(HwpxError::XmlError)?.or_else(|| extract_memo_properties(xml));'),
        ('    xml: &str,\n) -> Result<Bullet, HwpxError> {', '    xml: &str,\n    namespaces: &HeaderNamespaces,\n) -> Result<Bullet, HwpxError> {'),
        ('    xml: &str,\n) -> Result<(), HwpxError> {\n    let mut num = Numbering::default();', '    xml: &str,\n    namespaces: &HeaderNamespaces,\n) -> Result<(), HwpxError> {\n    let mut num = Numbering::default();'),
        ('bullet.raw_para_head = Some(xml[inner_start..inner_end].to_string());', 'bullet.raw_para_head = Some(namespaces.fragment(inner_start..inner_end).map_err(HwpxError::XmlError)?);'),
        ('num.raw_para_heads = Some(xml[inner_start..inner_end].to_string());', 'num.raw_para_heads = Some(namespaces.fragment(inner_start..inner_end).map_err(HwpxError::XmlError)?);'),
    ]
    before = hashlib.sha256(header.read_bytes()).hexdigest()
    for old,new in edits:
        if text.count(old) != 1: raise ValueError(f'Namespace patch expected one anchor: {old[:90]}')
        text = text.replace(old,new)
    header.write_text(text,encoding='utf-8')
    helper = header.parent/'opengeul_namespaces.rs'
    shutil.copyfile(ROOT/'overlay/hwpx_namespaces.rs',helper)
    (source/'.opengeul-namespaces.json').write_text(json.dumps({
        'patch':'HWPX header raw-fragment inherited namespaces',
        'upstreamHeaderSha256':before, 'patchedHeaderSha256':hashlib.sha256(header.read_bytes()).hexdigest(),
        'helperSha256':hashlib.sha256(helper.read_bytes()).hexdigest(),
    },indent=2)+'\n',encoding='utf-8')
    print('Applied scoped namespace preservation; native and WASM binaries require rebuilding.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    patch(parser.parse_args().source.resolve())
