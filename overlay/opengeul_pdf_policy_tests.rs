//! Distribution PDF policy at the public export boundary.
//!
//! The upstream fixture contains original synthetic outlines under MIT; see
//! tests/fixtures/fonts/RHWPExactKerningSmoke.LICENSE.md. Only its metadata is
//! changed in memory, and each test writes its own temporary font directory.

#![cfg(not(target_arch = "wasm32"))]

use rhwp::renderer::pdf::{svgs_to_pdf_with_options, PdfBackend, PdfExportOptions};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

const FONT: &[u8] = include_bytes!("fixtures/fonts/RHWPExactKerningSmoke.ttf");

fn u16_at(bytes: &[u8], offset: usize) -> u16 {
    u16::from_be_bytes(bytes[offset..offset + 2].try_into().unwrap())
}

fn table_offset(bytes: &[u8], tag: &[u8; 4]) -> usize {
    (0..usize::from(u16_at(bytes, 4)))
        .map(|index| 12 + index * 16)
        .find_map(|record| {
            (&bytes[record..record + 4] == tag).then(|| {
                u32::from_be_bytes(bytes[record + 8..record + 12].try_into().unwrap()) as usize
            })
        })
        .expect("synthetic SFNT contains the requested table")
}

fn font_with_flags(flags: u16) -> Vec<u8> {
    let mut bytes = FONT.to_vec();
    let offset = table_offset(&bytes, b"OS/2") + 8;
    bytes[offset..offset + 2].copy_from_slice(&flags.to_be_bytes());
    bytes
}

fn usable_family(bytes: &[u8], flags: u16) -> String {
    let mut database = usvg::fontdb::Database::new();
    database.load_font_data(bytes.to_vec());
    let faces: Vec<_> = database.faces().collect();
    assert_eq!(faces.len(), 1, "modified fixture must remain a usable font");
    assert_eq!(
        database.with_face_data(faces[0].id, |data, index| {
            assert_eq!(index, 0);
            u16_at(data, table_offset(data, b"OS/2") + 8)
        }),
        Some(flags),
        "the font loader must expose the actual embedding permission metadata"
    );
    assert!(ttf_parser::Face::parse(bytes, 0)
        .expect("valid synthetic font")
        .glyph_index('A')
        .is_some());
    faces[0].families[0].0.clone()
}

// Keep one permitted, differently named face available when the requested face
// is restricted. This reaches the family-specific guard even without OS fonts.
fn unrelated_allowed_font() -> Vec<u8> {
    let mut bytes = font_with_flags(0);
    let name = table_offset(&bytes, b"name");
    let strings = name + usize::from(u16_at(&bytes, name + 4));
    for index in 0..usize::from(u16_at(&bytes, name + 2)) {
        let record = name + 6 + index * 12;
        let start = strings + usize::from(u16_at(&bytes, record + 10));
        let length = usize::from(u16_at(&bytes, record + 8));
        if length > 1 && &bytes[start..start + 2] == b"\0R" {
            bytes[start + 1] = b'S';
        } else if length > 0 && bytes[start] == b'R' {
            bytes[start] = b'S';
        }
    }
    assert_ne!(usable_family(&bytes, 0), usable_family(FONT, 4));
    bytes
}

struct FontDirectory(PathBuf);

impl FontDirectory {
    fn new(bytes: &[u8]) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "opengeul-pdf-policy-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).expect("create isolated font directory");
        fs::write(path.join("requested.ttf"), bytes).expect("write synthetic font");
        Self(path)
    }

    fn compatibility_options(&self, family: &str) -> PdfExportOptions {
        let mut options = PdfExportOptions::default();
        options.font_paths = vec![self.0.clone()];
        options.fallback_serif = family.into();
        options.fallback_sans = family.into();
        options.fallback_mono = family.into();
        options
    }
}

impl Drop for FontDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn svg(family: &str) -> String {
    format!(
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="180" height="80"><text x="10" y="42" font-family="{family}" font-size="32">A</text></svg>"#
    )
}

#[test]
fn default_svg_backend_produces_complete_searchable_pdf_with_permitted_fonts() {
    assert_eq!(PdfBackend::default(), PdfBackend::CompatibilitySvg);
    for flags in [0, 8] {
        let bytes = font_with_flags(flags);
        let family = usable_family(&bytes, flags);
        let directory = FontDirectory::new(&bytes);
        let options = directory.compatibility_options(&family);
        assert!(options.embed_text, "searchable text remains the default");
        let pdf = svgs_to_pdf_with_options(&[svg(&family)], &options)
            .unwrap_or_else(|error| panic!("permitted fsType={flags} must export: {error}"));
        assert!(pdf.starts_with(b"%PDF-"));
        assert!(pdf.trim_ascii_end().ends_with(b"%%EOF"));
        assert!(
            pdf.windows(b"/ToUnicode".len())
                .any(|window| window == b"/ToUnicode"),
            "permitted synthetic text must be embedded with a searchable character map"
        );
    }
}

#[test]
fn default_svg_backend_rejects_a_usable_restricted_requested_font() {
    let bytes = font_with_flags(2);
    let family = usable_family(&bytes, 2);
    let directory = FontDirectory::new(&bytes);
    fs::write(
        directory.0.join("unrelated-allowed.ttf"),
        unrelated_allowed_font(),
    )
    .unwrap();
    let error =
        svgs_to_pdf_with_options(&[svg(&family)], &directory.compatibility_options(&family))
            .expect_err("restricted font must be denied before PDF conversion");
    assert!(error.contains("PDF 글꼴 포함을 중단했습니다"), "{error}");
    assert!(error.contains(&family), "{error}");
}

#[cfg(feature = "native-skia")]
mod direct {
    use super::*;
    use rhwp::paint::*;
    use rhwp::renderer::layer_renderer::LayerRasterRenderer;
    use rhwp::renderer::pdf::{
        layer_trees_to_pdf, layer_trees_to_pdf_with_links, layer_trees_to_pdf_with_options,
        DirectPdfExportOptions,
    };
    use rhwp::renderer::render_tree::{BoundingBox, FieldMarkerType, TextRunNode};
    use rhwp::renderer::skia::{native_skia_glyph_run_replay_proof, SkiaLayerRenderer};
    use rhwp::renderer::TextStyle;

    fn text_tree(family: &str) -> PageLayerTree {
        let run = TextRunNode {
            text: "A".into(),
            style: TextStyle {
                font_family: family.into(),
                font_size: 32.0,
                ..Default::default()
            },
            char_shape_id: None,
            para_shape_id: None,
            section_index: None,
            para_index: None,
            char_start: None,
            cell_context: None,
            is_para_end: false,
            is_line_break_end: false,
            rotation: 0.0,
            is_vertical: false,
            char_overlap: None,
            border_fill_id: 0,
            baseline: 32.0,
            field_marker: FieldMarkerType::None,
            layout_positions: None,
            display_text: None,
        };
        PageLayerTree::new(
            180.0,
            80.0,
            LayerNode::leaf(
                BoundingBox::new(0.0, 0.0, 180.0, 80.0),
                None,
                vec![PaintOp::text_run(
                    BoundingBox::new(10.0, 10.0, 40.0, 40.0),
                    run,
                )],
            ),
        )
    }

    // Portable glyph resources also bypass the SVG font database. Use a valid
    // exact resource, not a bad font or unsupported paint op that errors anyway.
    fn embedded_font_tree(bytes: &[u8], family: &str) -> PageLayerTree {
        let mut tree = text_tree(family);
        let digest = FontDigest {
            algorithm: "blake3".into(),
            value: resource_digest_hex(bytes),
        };
        let data_ref = BinaryResourceRef {
            kind: BinaryResourceKind::FontBlob,
            id: font_blob_resource_key(bytes.len(), &digest.value),
        };
        tree.resources.intern_font_blob_bytes(bytes);
        tree.resources
            .font_resources_mut()
            .blobs
            .push(FontBlobResource {
                id: FontBlobKey("policy-blob".into()),
                digest: Some(digest.clone()),
                source: FontResourceSource::Embedded,
                data_ref: Some(data_ref.clone()),
                portability: FontPortability::PortableBlob { digest, data_ref },
            });
        tree.resources
            .font_resources_mut()
            .faces
            .push(FontFaceResource {
                id: FontFaceKey("policy-face".into()),
                blob_key: FontBlobKey("policy-blob".into()),
                face_index: 0,
                postscript_name: None,
                family_names: Vec::new(),
                style_names: Vec::new(),
                weight_class: None,
                width_class: None,
                italic: None,
            });
        let LayerNodeKind::Leaf { ops } = &mut tree.root.kind else {
            unreachable!()
        };
        let PaintOp::TextRun {
            source: Some(source),
            ..
        } = &ops[0]
        else {
            unreachable!()
        };
        let mut variant = PaintVariantMeta::text_run_default("text-0");
        variant.variant_id = "glyphRun".into();
        variant.variant_kind = TextVariantKind::GlyphRun;
        variant.is_default_fallback = false;
        variant.quality = Some(TextVariantQuality::Exact);
        variant.anchor_op_id = Some("text-0".into());
        let run = LayerGlyphRunPaint {
            source: source.clone(),
            variant,
            paint_style: PaintTextStyle::from(&TextStyle {
                font_size: 32.0,
                ..Default::default()
            }),
            shape_key: ShapeKey {
                font_instance: FontInstanceKey {
                    face_key: FontFaceKey("policy-face".into()),
                    size_px: 32.0,
                    variations: Vec::new(),
                    synthetic_bold: false,
                    synthetic_italic: false,
                },
                direction: TextDirection::Ltr,
                writing_mode: WritingMode::HorizontalTb,
                script: None,
                language: None,
                features: Vec::new(),
                shaping_engine: ShapingEngineId("fixture".into()),
                fallback_policy: FontFallbackPolicyId("none".into()),
            },
            placement: TextRunPlacement {
                run_to_page: LayerAffineTransform {
                    a: 1.0,
                    b: 0.0,
                    c: 0.0,
                    d: 1.0,
                    e: 10.0,
                    f: 42.0,
                },
                baseline_y: 42.0,
            },
            glyph_ids: vec![u32::from(
                ttf_parser::Face::parse(bytes, 0)
                    .unwrap()
                    .glyph_index('A')
                    .unwrap()
                    .0,
            )],
            positions: vec![LayerPoint { x: 0.0, y: 0.0 }],
            advances: None,
            clusters: vec![GlyphCluster {
                source_range_utf8: TextSourceRange::new(0, 1),
                source_range_utf16: Some(TextSourceRange::new(0, 1)),
                text_range_utf8: Some(TextSourceRange::new(0, 1)),
                glyph_range: GlyphRange::new(0, 1),
                flags: Vec::new(),
            }],
            direction: TextDirection::Ltr,
            bidi_level: Some(0),
            writing_mode: WritingMode::HorizontalTb,
            orientation: GlyphRunOrientation::Horizontal,
            glyph_transforms: None,
            diagnostics: GlyphRunDiagnostics {
                quality: TextVariantQuality::Exact,
                replay_eligibility: GlyphRunReplayEligibility::Portable,
                strict_visual_eligible: true,
                max_origin_delta_px: 0.0,
                max_advance_delta_px: 0.0,
                max_residual_after_adjustment_px: 0.0,
                cluster_mismatch_count: 0,
                missing_glyph_count: 0,
                used_fallback_font_count: 0,
                reason: None,
            },
        };
        assert!(native_skia_glyph_run_replay_proof(&run, &tree.resources).typeface_constructible);
        ops.push(PaintOp::glyph_run(
            BoundingBox::new(10.0, 10.0, 40.0, 40.0),
            run,
        ));
        tree
    }

    fn assert_policy_denied(result: Result<Vec<u8>, String>, entrypoint: &str) {
        let error = result.unwrap_err();
        for term in ["OpenGeul", "direct PDF", "SVG"] {
            assert!(
                error.contains(term),
                "{entrypoint} returned a different error: {error}"
            );
        }
    }

    fn assert_all_entrypoints_denied(tree: &PageLayerTree, options: &DirectPdfExportOptions) {
        let pages = std::slice::from_ref(tree);
        assert_policy_denied(layer_trees_to_pdf(pages), "default options");
        assert_policy_denied(
            layer_trees_to_pdf_with_options(pages, options),
            "explicit options",
        );
        assert_policy_denied(
            layer_trees_to_pdf_with_links(pages, &[Vec::new()], options),
            "links",
        );
    }

    #[test]
    fn all_direct_pdf_entrypoints_deny_restricted_permitted_and_fontless_pages() {
        for flags in [2, 0, 8] {
            let bytes = font_with_flags(flags);
            let family = usable_family(&bytes, flags);
            let directory = FontDirectory::new(&bytes);
            let mut options = DirectPdfExportOptions::default();
            options.font_paths = vec![directory.0.clone()];
            assert_all_entrypoints_denied(&text_tree(&family), &options);
            assert_all_entrypoints_denied(&embedded_font_tree(&bytes, &family), &options);
        }
        let fontless = PageLayerTree::new(
            180.0,
            80.0,
            LayerNode::leaf(BoundingBox::new(0.0, 0.0, 180.0, 80.0), None, Vec::new()),
        );
        assert_all_entrypoints_denied(&fontless, &DirectPdfExportOptions::default());
    }

    #[test]
    fn direct_pdf_policy_leaves_native_png_available() {
        let bytes = font_with_flags(2);
        let family = usable_family(&bytes, 2);
        let tree = embedded_font_tree(&bytes, &family);
        let directory = FontDirectory::new(&bytes);
        let png = SkiaLayerRenderer::new()
            .with_font_paths(&[directory.0.clone()])
            .render_png(&tree)
            .expect("font embedding policy must preserve raster PNG rendering");
        assert!(png.starts_with(b"\x89PNG\r\n\x1a\n"));
    }
}
