//! Synthetic, redistributable fixtures. No customer documents or font programs.
use hop_rhwp_adapter::{split_paragraph_for_editing, DocumentCore};
use std::{env, fs, path::PathBuf};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let out = PathBuf::from(env::args().nth(1).ok_or("output directory required")?);
    fs::create_dir_all(&out)?;
    for (name, text) in [
        ("blank", ""),
        ("basic", "OpenGeul fixture 한글 가나다 & <xml> Ω 123"),
        ("unicode", "견적서 테스트 😀 한글 & < > Ω Cafe\u{301} 끝"),
        ("missing-font", "Missing font fallback 문서"),
    ] {
        let mut core = DocumentCore::new_empty();
        core.create_blank_document_native().map_err(|e| e.to_string())?;
        if !text.is_empty() { core.insert_text_native(0, 0, 0, text).map_err(|e| e.to_string())?; }
        fs::write(out.join(format!("{name}.hwp")), core.export_hwp_native().map_err(|e| e.to_string())?)?;
        fs::write(out.join(format!("{name}.hwpx")), core.export_hwpx_native().map_err(|e| e.to_string())?)?;
    }
    let mut core = DocumentCore::new_empty();
    core.create_blank_document_native().map_err(|e| e.to_string())?;
    for index in 0..12usize {
        let text = format!("Row {index:02} — generated content 한글 {index}");
        core.insert_text_native(0, index, 0, &text).map_err(|e| e.to_string())?;
        if index != 11 { split_paragraph_for_editing(&mut core, 0, index, text.chars().count())?; }
    }
    fs::write(out.join("paragraphs.hwpx"), core.export_hwpx_native().map_err(|e| e.to_string())?)?;
    fs::write(out.join("invalid.hwpx"), b"PK\x03\x04this is not a document")?;
    println!("Generated synthetic fixtures at {}", out.display());
    Ok(())
}
