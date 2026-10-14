//! Filters the native SVG PDF font database before svg2pdf can embed/subset fonts.
//! This is a metadata safeguard, not a complete license/provenance audit.
#[path = "opengeul_font_policy.rs"]
mod font_policy;
use std::collections::BTreeSet;

pub fn incomplete_page_error(page_index: usize) -> String {
    format!("PDF 내보내기를 중단했습니다: {}페이지를 변환할 수 없어 PDF 파일을 저장하지 않았습니다.", page_index + 1)
}

#[cfg(feature = "native-skia")]
pub fn reject_direct_export() -> Result<(), String> {
    Err("OpenGeul direct PDF export is unavailable because this Skia path cannot enforce font embedding permissions. Use the guarded SVG backend (--backend svg).".into())
}

pub fn enforce(fontdb: &mut usvg::fontdb::Database, pages: &[String]) -> Result<(), String> {
    let mut denied = Vec::new();
    let mut denied_names = BTreeSet::new();
    for face in fontdb.faces() {
        let allowed = fontdb.with_face_data(face.id, |data,index| {
            font_policy::permits_subset_embedding(font_policy::embedding_flags(data,index))
        }).unwrap_or(false);
        if !allowed {
            denied.push(face.id);
            for (name,_) in &face.families { denied_names.insert(name.to_lowercase()); }
        }
    }
    for id in denied { fontdb.remove_face(id); }
    if fontdb.is_empty() {
        return Err("PDF에 포함할 수 있는 설치된 글꼴을 찾지 못했습니다. '글꼴 도움말'에서 Noto 글꼴을 설치한 뒤 다시 시도하세요.".into());
    }
    for page in pages {
        for family in requested_families(page) {
            if denied_names.contains(&family.to_lowercase()) {
                return Err(format!("PDF 글꼴 포함을 중단했습니다: {family}. 포함 권한 메타데이터가 제한적이거나 확인되지 않았습니다. 원본을 보존하고 문서 복사본의 글꼴을 허용된 글꼴로 변경하세요."));
            }
        }
    }
    Ok(())
}

/// Keep authored family matches intact, then use an already permitted installed
/// family when usvg cannot find any base face. Glyph fallback cannot run until
/// a base face exists. The caller must apply `enforce` before using this resolver.
pub fn installed_base_font_selector() -> usvg::FontSelectionFn<'static> {
    let stock = usvg::FontResolver::default_font_selector();
    Box::new(move |font, fontdb| {
        if let Some(id) = stock(font, fontdb) {
            return Some(id);
        }
        // Font discovery IDs/order are not a family preference. Use only
        // resident family metadata and a locale-independent stable ordering.
        let (family, _, _) = fontdb.faces().flat_map(|face| {
            face.families.iter().filter(|(name, _)| !name.is_empty()).map(move |(name, _)| {
                (name.as_str(), face.post_script_name.as_str(), face.index)
            })
        }).min()?;
        let stretch = match font.stretch() {
            usvg::FontStretch::UltraCondensed => usvg::fontdb::Stretch::UltraCondensed,
            usvg::FontStretch::ExtraCondensed => usvg::fontdb::Stretch::ExtraCondensed,
            usvg::FontStretch::Condensed => usvg::fontdb::Stretch::Condensed,
            usvg::FontStretch::SemiCondensed => usvg::fontdb::Stretch::SemiCondensed,
            usvg::FontStretch::Normal => usvg::fontdb::Stretch::Normal,
            usvg::FontStretch::SemiExpanded => usvg::fontdb::Stretch::SemiExpanded,
            usvg::FontStretch::Expanded => usvg::fontdb::Stretch::Expanded,
            usvg::FontStretch::ExtraExpanded => usvg::fontdb::Stretch::ExtraExpanded,
            usvg::FontStretch::UltraExpanded => usvg::fontdb::Stretch::UltraExpanded,
        };
        let style = match font.style() {
            usvg::FontStyle::Normal => usvg::fontdb::Style::Normal,
            usvg::FontStyle::Italic => usvg::fontdb::Style::Italic,
            usvg::FontStyle::Oblique => usvg::fontdb::Style::Oblique,
        };
        fontdb.query(&usvg::fontdb::Query {
            families: &[usvg::fontdb::Family::Name(family)],
            weight: usvg::fontdb::Weight(font.weight()), stretch, style,
        })
    })
}

fn requested_families(svg: &str) -> Vec<String> {
    let mut result=Vec::new();
    for quote in ['"','\''] {
        let anchor=format!("font-family={quote}");
        let mut remaining=svg;
        while let Some(start)=remaining.find(&anchor) {
            remaining=&remaining[start+anchor.len()..];
            let Some(end)=remaining.find(quote) else { break; };
            let value=remaining[..end].replace("&quot;","\"").replace("&apos;","'").replace("&amp;","&");
            result.extend(value.split(',').map(|x|x.trim().trim_matches(['\'','"']).to_string()).filter(|x| !x.is_empty()));
            remaining=&remaining[end+quote.len_utf8()..];
        }
    }
    result
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn recognizes_family_chains() {
        assert_eq!(requested_families(r#"<text font-family="'Test Font', serif">x</text>"#),vec!["Test Font","serif"]);
    }
}
