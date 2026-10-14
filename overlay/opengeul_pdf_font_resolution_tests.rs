//! Native policy regressions for a missing base family after embedding filtering.
#[path = "../src/renderer/pdf/opengeul_pdf_guard.rs"]
mod guard;
use std::sync::{Arc, Mutex};

fn svg(family: &str, extra: &str) -> String {
    let family = family.replace('&', "&amp;").replace('"', "&quot;");
    format!(r#"<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><text x="10" y="30" font-family="{family}" {extra}>A</text></svg>"#)
}

fn installed() -> usvg::fontdb::Database {
    let mut db = usvg::fontdb::Database::new();
    db.load_system_fonts();
    guard::enforce(&mut db, &[]).expect("Native PDF requires permitted installed fonts");
    db
}

fn visible_text(group: &usvg::Group) -> String {
    let mut value = String::new();
    for node in group.children() {
        match node {
            usvg::Node::Group(group) => value.push_str(&visible_text(group)),
            usvg::Node::Text(text) => for span in text.layouted().iter().filter(|span| span.visible) {
                for glyph in &span.positioned_glyphs {
                    assert_ne!(glyph.id.0, 0, "Supported A must have a real glyph");
                    value.push_str(&glyph.text);
                }
            },
            _ => {}
        }
    }
    value
}

#[test]
fn missing_base_retains_visible_text_with_stable_installed_family() {
    let source = svg("serif", "");
    let mut db = installed();
    db.set_serif_family("OPENGEUL-OWNED-MISSING-FAMILY");
    assert!(db.query(&usvg::fontdb::Query {
        families: &[usvg::fontdb::Family::Serif], ..Default::default()
    }).is_none());
    let family = db.faces().flat_map(|face| face.families.iter().filter(|(name, _)| !name.is_empty())
        .map(move |(name, _)| (name.as_str(), face.post_script_name.as_str(), face.index)))
        .min().expect("Permitted installed face").0.to_owned();
    let expected = db.query(&usvg::fontdb::Query {
        families: &[usvg::fontdb::Family::Name(&family)], ..Default::default()
    }).expect("Stable installed family must be queryable");
    let selected = Arc::new(Mutex::new(Vec::new()));
    let observed = selected.clone();
    let resolver = guard::installed_base_font_selector();
    let mut options = usvg::Options::default();
    options.fontdb = Arc::new(db);
    options.font_resolver.select_font = Box::new(move |font, db| {
        let id = resolver(font, db); observed.lock().unwrap().push(id); id
    });
    let tree = usvg::Tree::from_str(&source, &options).unwrap();
    assert_eq!(&*selected.lock().unwrap(), &[Some(expected)]);
    assert_eq!(visible_text(tree.root()), "A");
}

#[test]
fn stock_family_id_and_authored_style_are_preserved() {
    let db = installed();
    let family = db.faces().next().unwrap().families[0].0.clone();
    let source = svg(&family, r#"font-weight="700" font-style="italic" font-stretch="condensed""#);
    let checked = Arc::new(Mutex::new(0usize));
    let observed = checked.clone();
    let stock = usvg::FontResolver::default_font_selector();
    let resolver = guard::installed_base_font_selector();
    let mut options = usvg::Options::default(); options.fontdb = Arc::new(db);
    options.font_resolver.select_font = Box::new(move |font, db| {
        assert_eq!(font.weight(), 700);
        assert_eq!(font.style(), usvg::FontStyle::Italic);
        assert_eq!(font.stretch(), usvg::FontStretch::Condensed);
        let expected = stock(font, db).expect("Original installed family must resolve");
        assert_eq!(resolver(font, db), Some(expected));
        *observed.lock().unwrap() += 1; Some(expected)
    });
    usvg::Tree::from_str(&source, &options).unwrap();
    assert_eq!(*checked.lock().unwrap(), 1);
}

#[test]
fn restricted_requested_family_still_fails_before_fallback() {
    let mut db = installed();
    let face = db.faces().next().unwrap(); let index = face.index;
    let family = face.families[0].0.clone();
    let mut data = db.with_face_data(face.id, |data, _| data.to_vec()).unwrap();
    let u32_at = |data: &[u8], offset| u32::from_be_bytes(data[offset..offset + 4].try_into().unwrap()) as usize;
    let offset = if &data[..4] == b"ttcf" { u32_at(&data, 12 + index as usize * 4) } else { 0 };
    let count = u16::from_be_bytes(data[offset + 4..offset + 6].try_into().unwrap()) as usize;
    let table = (0..count).map(|n| offset + 12 + n * 16).find(|&at| &data[at..at + 4] == b"OS/2").unwrap();
    let flags = u32_at(&data, table + 8) + 8;
    data[flags..flags + 2].copy_from_slice(&2u16.to_be_bytes());
    db.load_font_data(data);
    let error = guard::enforce(&mut db, &[svg(&family, "")]).unwrap_err();
    assert!(error.contains("포함 권한"));
    assert!(!db.is_empty(), "A permitted fallback cannot waive the denied request");
}

#[test]
fn empty_installed_database_still_fails_closed() {
    let mut db = usvg::fontdb::Database::new();
    let error = guard::enforce(&mut db, &[svg("serif", "")]).unwrap_err();
    assert!(error.contains("설치된 글꼴"));
    assert!(db.is_empty());
}
