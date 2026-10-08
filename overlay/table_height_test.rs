//! Synthetic counterpart to the WASM geometry gate. No external documents or fonts.
use serde_json::Value;
use std::{fs, path::PathBuf};

fn collect<'a>(node: &'a Value, kind: &str, output: &mut Vec<&'a Value>) {
    if node["type"].as_str() == Some(kind) { output.push(node); }
    if let Some(children) = node["children"].as_array() {
        for child in children { collect(child, kind, output); }
    }
}
fn number(node: &Value, key: &str) -> f64 {
    let value = node["bbox"][key].as_f64().expect("finite numeric bounding box");
    assert!(value.is_finite()); value
}
#[test]
fn terminal_compressed_line_fits_without_changing_nonterminal_spacing() {
    let folder = PathBuf::from(std::env::var("OPENGEUL_TABLE_FIXTURES").expect("synthetic fixtures required"));
    for spacing in [-300i32, 0, 600] {
        let bytes = fs::read(folder.join(format!("table-spacing-{spacing}.hwpx"))).expect("read fixture");
        let document = rhwp::wasm_api::HwpDocument::from_bytes(&bytes).expect("parse synthetic HWPX");
        let tree: Value = serde_json::from_str(&document.get_page_render_tree(0).expect("render tree")).expect("JSON");
        let mut cells = Vec::new(); collect(&tree, "Cell", &mut cells);
        assert_eq!(cells.len(), 1);
        let cell = cells[0];
        let mut lines = Vec::new(); collect(cell, "TextLine", &mut lines);
        assert_eq!(lines.len(), 5);
        let mut runs = Vec::new(); collect(cell, "TextRun", &mut runs);
        let text: String = runs.iter().map(|run| run["text"].as_str().expect("text")).collect();
        for row in 0..5 { assert_eq!(text.matches(&format!("Row {row} lastline")).count(), 1); }
        let bottom = lines.iter().map(|line| number(line, "y") + number(line, "h")).fold(f64::NEG_INFINITY, f64::max);
        assert!(bottom <= number(cell, "y") + number(cell, "h") + 0.25, "last glyph line clips at spacing {spacing}");
        let expected = f64::from(5 * (1000 + spacing) + (-spacing).max(0) + 282) * 96.0 / 7200.0;
        assert!((number(cell, "h") - expected).abs() < 0.25, "positive/negative height mismatch: {spacing}");
        let pitch = f64::from(1000 + spacing) * 96.0 / 7200.0;
        for pair in lines.windows(2) { assert!((number(pair[1], "y") - number(pair[0], "y") - pitch).abs() < 0.25); }
    }
}
