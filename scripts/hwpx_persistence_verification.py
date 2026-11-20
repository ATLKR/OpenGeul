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
 'third_party/rhwp/src/model/document.rs',
 'third_party/rhwp/src/document_core/mod.rs',
 'third_party/rhwp/src/model/bin_data.rs',
 'third_party/rhwp/src/document_core/commands/bin_data_prune.rs',
 'third_party/rhwp/src/parser/hwpx/mod.rs',
 'third_party/rhwp/src/serializer/hwpx/context.rs',
 'third_party/rhwp/src/parser/hwpx/content.rs')
INPUT_SOURCE_SHA256 = {'third_party/rhwp/src/cli/commands/edit/runtime.rs': 'ae6d2cb181e719e548cfbe61da0393ccb837e3749b2422d68267d438db6a295c',
 'third_party/rhwp/src/serializer/hwpx/roundtrip.rs': '07e95e9255946772e0142f411f7195321a0dd210d670d5538024560e424936b3',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '2e83bfe3d7d3c95b81a1f12c4c64202292e00f583762cbdbf4d654eb8fbd2562',
 'third_party/rhwp/src/model/identity/walk.rs': '6381910852edfcdeed8916a8b8f8998d6a06d3568a5f420e3f5cf834dbe87d08',
 'third_party/rhwp/src/model/identity.rs': 'f9791f7dcce9f81e2fc260a0519971bd45838b8b9fb5453eba9682cf6d52efd9',
 'third_party/rhwp/src/serializer/hwpx/field.rs': 'eba22b7936e3e36ef30ee5aafe57ab320e6f1a86dcd37bcdf5476616c593b505',
 'third_party/rhwp/src/serializer/line_cache.rs': '8973f204008c077051515eb6eef2a327e47535887150505de7ac88c4a1ca515f',
 'third_party/rhwp/src/document_core/commands/object_ops/picture_inline_migration.rs': '8da5248dc46339f9c00f292b38e265ea038707436edd76ff253b71943d47032e',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs': '2c9c15669ca0b4b071a10ab232b9a9d991bd98fa0634be1640df096d0f5fc541',
 'third_party/rhwp/src/serializer/hwpx_lineage_lines.rs': '3b9d5e503beedd3df2e839d05d91eb5901ddfca4e3f2fb63ab3c33a83712d367',
 'third_party/rhwp/src/serializer/cfb_writer.rs': 'b2688d25e7c1bdf444d6be5f6fb08d204a56cbcf75ef0a70d3769e31bf373e61',
 'third_party/rhwp/src/model/document.rs': '1bf0e9df2fe46b0ede670b1bf34812f0791a170b96e37609fb65212f6ff6d40f',
 'third_party/rhwp/src/document_core/mod.rs': '8ecd1d93712ebe7fa504b2c85efa3dbea51454ec1117ab891354a8451138cfc4',
 'third_party/rhwp/src/model/bin_data.rs': 'acb3139d219227979e2e56086e58ec0832f71ef0a10a0a67452cb079f8c43ec4',
 'third_party/rhwp/src/document_core/commands/bin_data_prune.rs': '832bf14ac42a8bc0405e88b8b44ea3c5a9d7c711b779501ea139489057621c52',
 'third_party/rhwp/src/parser/hwpx/mod.rs': '3c96f124b409aeb52fb132e9cbcf55a57c6743d11616c1d6f9808d1dab9f4331',
 'third_party/rhwp/src/serializer/hwpx/context.rs': '7b1f6d7270ba1e9da55ebbc71e83be4b0582cb021db077d9e5f1bf171eafde0e',
 'third_party/rhwp/src/parser/hwpx/content.rs': '709195d0a244a498fe2830e79bbaeb6cb139af77e37e731514ea647199be3827'}
OUTPUT_SOURCE_SHA256 = {'third_party/rhwp/src/cli/commands/edit/runtime.rs': '654b582680a323f8472515be4f45f54677b8952802914fa4e9f5bc7ce16c43c5',
 'third_party/rhwp/src/serializer/hwpx/roundtrip.rs': '65eb5e7b96c92a23b6d1b1929ec81ee8db033ae0caf0bfdf54f96a8152381be0',
 'third_party/rhwp/src/serializer/hwpx/section.rs': '2e83bfe3d7d3c95b81a1f12c4c64202292e00f583762cbdbf4d654eb8fbd2562',
 'third_party/rhwp/src/model/identity/walk.rs': '6381910852edfcdeed8916a8b8f8998d6a06d3568a5f420e3f5cf834dbe87d08',
 'third_party/rhwp/src/model/identity.rs': 'f9791f7dcce9f81e2fc260a0519971bd45838b8b9fb5453eba9682cf6d52efd9',
 'third_party/rhwp/src/serializer/hwpx/field.rs': 'bef1e3781454b1ae3ff24fe45f74163d24e2eb52c3f6e6791588ed23e0e8559e',
 'third_party/rhwp/src/serializer/line_cache.rs': '8973f204008c077051515eb6eef2a327e47535887150505de7ac88c4a1ca515f',
 'third_party/rhwp/src/document_core/commands/object_ops/picture_inline_migration.rs': '8da5248dc46339f9c00f292b38e265ea038707436edd76ff253b71943d47032e',
 'third_party/rhwp/src/serializer/hwpx/roundtrip/export_cache.rs': '2c9c15669ca0b4b071a10ab232b9a9d991bd98fa0634be1640df096d0f5fc541',
 'third_party/rhwp/src/serializer/hwpx_lineage_lines.rs': '3b9d5e503beedd3df2e839d05d91eb5901ddfca4e3f2fb63ab3c33a83712d367',
 'third_party/rhwp/src/serializer/cfb_writer.rs': 'b2688d25e7c1bdf444d6be5f6fb08d204a56cbcf75ef0a70d3769e31bf373e61',
 'third_party/rhwp/src/model/document.rs': '1bf0e9df2fe46b0ede670b1bf34812f0791a170b96e37609fb65212f6ff6d40f',
 'third_party/rhwp/src/document_core/mod.rs': '8ecd1d93712ebe7fa504b2c85efa3dbea51454ec1117ab891354a8451138cfc4',
 'third_party/rhwp/src/model/bin_data.rs': 'acb3139d219227979e2e56086e58ec0832f71ef0a10a0a67452cb079f8c43ec4',
 'third_party/rhwp/src/document_core/commands/bin_data_prune.rs': 'bb0e831ef362a5498384aedec11be5ec22210c71ff190337a159c9c5860a76a2',
 'third_party/rhwp/src/parser/hwpx/mod.rs': '3c96f124b409aeb52fb132e9cbcf55a57c6743d11616c1d6f9808d1dab9f4331',
 'third_party/rhwp/src/serializer/hwpx/context.rs': '7b1f6d7270ba1e9da55ebbc71e83be4b0582cb021db077d9e5f1bf171eafde0e',
 'third_party/rhwp/src/parser/hwpx/content.rs': '3930d8d2c861a72c05b0196a73d8fb331cfb2781bebb28f109e115f16c25341d'}
RESOURCE_EXPECTATION_API = r'''mod opengeul_resource_expectation {
    use std::collections::{BTreeMap, BTreeSet};
    use crate::model::bin_data::{BinDataBytes, BinDataContent, BinDataType, MAX_BIN_DATA_BYTES};
    use crate::model::control::Control;
    use crate::model::document::Document;
    use crate::model::identity::walk::{walk, Node};
    use crate::model::shape::{OleShape, ShapeObject};
    use crate::model::paragraph::Paragraph;

    #[derive(Debug, PartialEq)]
    struct Plan {
        kept: Vec<bool>,
        positions: Vec<Option<u16>>,
    }

    // Storage identifiers never become positional references. The original
    // orphan snapshot and embedded-font owners protect their original bytes.
    fn plan(ids: &[u16], refs: &[u16], original: &BTreeSet<u16>, fonts: &BTreeSet<u16>) -> Option<Plan> {
        if ids.len() > u16::MAX as usize { return None; }
        let mut storage = BTreeMap::new();
        for (index, &id) in ids.iter().enumerate() {
            if id != 0 && storage.insert(id, index).is_some() { return None; }
        }
        let mut kept: Vec<bool> = ids.iter().map(|id| original.contains(id) || fonts.contains(id)).collect();
        for &id in refs {
            if id == 0 { continue; }
            let slot = usize::from(id) - 1;
            let slot = if slot < ids.len() { slot } else { *storage.get(&id)? };
            kept[slot] = true;
        }
        let mut next = 0u16;
        let positions = kept.iter().map(|keep| {
            if *keep { next += 1; Some(next) } else { None }
        }).collect();
        Some(Plan { kept, positions })
    }

    // Chart placeholders are identities of Chart/*.xml, not binary slots.
    // A fallback is a distinct OLE owner and must be walked independently.
    fn ole(ole: &mut OleShape, f: &mut impl FnMut(u8, &mut u16) -> Option<()>, opaque: &mut impl FnMut(u32, Option<&str>) -> Option<()>) -> Option<()> {
        if let Some(image) = &mut ole.drawing.fill.image { f(2, &mut image.bin_data_id)?; }
        if let Some(target) = ole.chart_id_ref.as_deref() { opaque(ole.bin_data_id, Some(target))?; }
        else if let Ok(mut id) = u16::try_from(ole.bin_data_id) {
            f(3, &mut id)?;
            ole.bin_data_id = u32::from(id);
        } else { opaque(ole.bin_data_id, None)?; }
        if let Some(fallback) = &mut ole.chart_switch_fallback {
            self::ole(fallback, f, opaque)?;
            if let Some(caption) = &mut fallback.caption { paragraphs(&mut caption.paragraphs, f, opaque)?; }
            if let Some(caption) = &mut fallback.drawing.caption { paragraphs(&mut caption.paragraphs, f, opaque)?; }
            if let Some(textbox) = &mut fallback.drawing.text_box { paragraphs(&mut textbox.paragraphs, f, opaque)?; }
        }
        Some(())
    }

    fn paragraphs(paras: &mut [Paragraph], f: &mut impl FnMut(u8, &mut u16) -> Option<()>, opaque: &mut impl FnMut(u32, Option<&str>) -> Option<()>) -> Option<()> {
        walk(paras, |node| {
            let valid = match node {
                Node::Control(Control::Picture(picture)) => f(1, &mut picture.image_attr.bin_data_id),
                Node::Shape(shape) => match shape {
                    ShapeObject::Picture(picture) => f(1, &mut picture.image_attr.bin_data_id),
                    ShapeObject::Ole(value) => ole(value, f, opaque),
                    _ => {
                        if let Some(drawing) = shape.drawing_mut() {
                            if let Some(image) = &mut drawing.fill.image { f(2, &mut image.bin_data_id) } else { Some(()) }
                        } else { Some(()) }
                    },
                },
                _ => Some(()),
            };
            valid.ok_or_else(|| crate::error::HwpError::RenderError("Unsupported binary resource binding".into()))
        }).ok()
    }

    // Independent identity walk, including canonical detached master pages.
    // This does not call the exporter's recursive BinData-prune visitor.
    fn slots(document: &mut Document, f: &mut impl FnMut(u8, &mut u16) -> Option<()>, opaque: &mut impl FnMut(u32, Option<&str>) -> Option<()>) -> Option<()> {
        for section in &mut document.sections {
            paragraphs(&mut section.paragraphs, f, opaque)?;
            for master in &mut section.section_def.master_pages { paragraphs(&mut master.paragraphs, f, opaque)?; }
        }
        for border in &mut document.doc_info.border_fills {
            if let Some(image) = &mut border.fill.image { f(4, &mut image.bin_data_id)?; }
        }
        for bullet in &mut document.doc_info.bullets {
            if let Some(mut id) = bullet.image_reference() {
                f(5, &mut id)?;
                if bullet.raw_para_head.is_none() {
                    bullet.image_data[3] = u8::try_from(id).ok()?;
                } else { bullet.image_bullet = i32::from(id); }
            }
        }
        Some(())
    }

    fn font_bindings(document: &Document) -> Vec<(u8, u16)> {
        let mut bindings = Vec::new();
        for font in document.doc_info.font_faces.iter().flatten() {
            if font.is_embedded { bindings.push((6, font.resolved_bin_data_id.unwrap_or(0))); }
            if let Some(substitute) = &font.subst_font {
                if substitute.is_embedded { bindings.push((7, substitute.resolved_bin_data_id.unwrap_or(0))); }
            }
        }
        bindings
    }

    // HWPX serialization resolves the source DocInfo record namespace first;
    // a sparse storage identifier is only the direct-lookup fallback.
    fn source_storage(document: &Document, id: u16) -> Option<u16> {
        if id == 0 { return Some(0); }
        if let Some(entry) = document.doc_info.bin_data_list.get(usize::from(id) - 1) {
            if entry.storage_id != 0 { return Some(entry.storage_id); }
            // An explicit invalid descriptor cannot borrow another owner's bytes.
            return None;
        }
        document.bin_data_content.iter().find(|content| content.id == id).map(|content| content.id)
    }

    fn source_key(document: &Document, id: u16) -> Option<u32> {
        if id == 0 { return Some(0); }
        if let Some(entry) = document.doc_info.bin_data_list.get(usize::from(id) - 1) {
            if entry.storage_id != 0 { return Some(u32::from(entry.storage_id)); }
            if matches!(&entry.data_type, BinDataType::Link) { return Some(65536 + u32::from(id)); }
            return None;
        }
        source_storage(document, id).map(u32::from)
    }

    // Re-imported HWPX has its own namespace: manifest entries sorted by
    // source storage ID become 1-based IDs. Derive this solely from source
    // ownership; do not read the exporter context or normalize actual output.
    fn canonical_manifest(document: &mut Document) -> Option<()> {
        // HWP5 Link records have no storage ID. The persisted HWPX namespace
        // gives each remaining zero-Link record a distinct ID after ordinary
        // manifest resources, in source record order; URI bytes remain exact.
        let mut next = document.bin_data_content.iter().filter(|c| c.extension != "ooxml_chart").map(|c| c.id)
            .chain(document.doc_info.bin_data_list.iter().map(|entry| entry.storage_id)).max().unwrap_or(0);
        for entry in &mut document.doc_info.bin_data_list {
            if entry.storage_id == 0 {
                if !matches!(&entry.data_type, BinDataType::Link) { return None; }
                next = next.checked_add(1)?;
                entry.storage_id = next;
            }
        }
        // Only zero-byte, declared HWP5 link slots can reach this point.
        // They are not package payloads and their descriptors remain above.
        if document.bin_data_content.iter().any(|c| c.id == 0 && !empty(c)) { return None; }
        document.bin_data_content.retain(|c| c.id != 0);
        let old_ids: Vec<u16> = document.bin_data_content.iter().map(|c| c.id).collect();
        let chart_ids: BTreeSet<u16> = document.bin_data_content.iter().filter(|c| c.extension == "ooxml_chart").map(|c| c.id).collect();
        let mut manifest: BTreeSet<u16> = old_ids.iter().copied().filter(|id| !chart_ids.contains(id)).collect();
        for entry in &document.doc_info.bin_data_list {
            if entry.storage_id == 0 || chart_ids.contains(&entry.storage_id) { return None; }
            manifest.insert(entry.storage_id);
        }
        if manifest.contains(&0) { return None; }
        let mut ranks = BTreeMap::new();
        for (index, id) in manifest.into_iter().enumerate() {
            let rank = u16::try_from(index + 1).ok()?;
            if chart_ids.contains(&rank) { return None; }
            ranks.insert(id, rank);
        }
        let mut raw = Vec::new();
        slots(document, &mut |_, id| { raw.push(*id); Some(()) }, &mut |_, _| Some(()))?;
        let mut sources = BTreeMap::new();
        for id in raw { sources.insert(id, source_storage(document, id)?); }
        slots(document, &mut |_, id| {
            if *id != 0 { *id = *ranks.get(sources.get(id)?)?; }
            Some(())
        }, &mut |_, _| Some(()))?;
        for font in document.doc_info.font_faces.iter_mut().flatten() {
            if font.is_embedded { if let Some(id) = &mut font.resolved_bin_data_id { if *id != 0 { *id = *ranks.get(id)?; } } }
            if let Some(substitute) = &mut font.subst_font {
                if substitute.is_embedded { if let Some(id) = &mut substitute.resolved_bin_data_id { if *id != 0 { *id = *ranks.get(id)?; } } }
            }
        }
        for content in &mut document.bin_data_content {
            if !chart_ids.contains(&content.id) { content.id = *ranks.get(&content.id)?; }
        }
        for entry in &mut document.doc_info.bin_data_list {
            let embedded = old_ids.contains(&entry.storage_id) && !chart_ids.contains(&entry.storage_id);
            if !embedded {
                // A declared descriptor without embedded bytes is serialized
                // as a link/placeholder. Preserve its exact URI, including empty.
                entry.data_type = BinDataType::Link;
                entry.abs_path = Some(entry.abs_path.clone().or_else(|| entry.rel_path.clone()).unwrap_or_default());
                entry.rel_path = None;
            } else if matches!(&entry.data_type, BinDataType::Link) {
                entry.data_type = BinDataType::Embedding;
            }
            entry.storage_id = *ranks.get(&entry.storage_id)?;
        }
        document.bin_data_content.sort_by_key(|content| content.id);
        document.doc_info.bin_data_list.sort_by_key(|entry| entry.storage_id);
        Some(())
    }

    pub(super) fn expected(core: &crate::DocumentCore) -> Option<Document> {
        let mut document = super::hwpx_persistence_document(core.document());
        let ids: Vec<u16> = document.bin_data_content.iter().map(|content| content.id).collect();
        let mut fonts: BTreeSet<u16> = font_bindings(&document).into_iter().map(|(_, id)| id).filter(|id| *id != 0).collect();
        // OOXML Chart parts are outside content.hpf's BinData manifest. They
        // have independent ownership and this BinData prune grants no deletion.
        fonts.extend(document.bin_data_content.iter().filter(|c| c.extension == "ooxml_chart").map(|c| c.id));
        if document.bin_data_content.iter().any(|content| content.id == 0 && !empty(content)) { return None; }
        let mut raw_refs = Vec::new();
        let mut has_opaque_owner = false;
        slots(&mut document, &mut |_, id| { raw_refs.push(*id); Some(()) }, &mut |_, chart| { if chart.is_none() { has_opaque_owner = true; } Some(()) })?;
        let mut sources = BTreeMap::new();
        let mut refs = Vec::new();
        for raw in raw_refs {
            let key = source_key(&document, raw)?;
            sources.insert(raw, key);
            let position = if key == 0 { None }
                else if key <= u32::from(u16::MAX) { document.bin_data_content.iter().position(|content| u32::from(content.id) == key) }
                else {
                    let index = usize::from(raw) - 1;
                    document.bin_data_content.get(index).filter(|content| content.id == 0 && content.extension.is_empty() && matches!(&content.data, BinDataBytes::Loaded(bytes) if bytes.is_empty())).map(|_| index)
                };
            refs.push(position.map(|index| u16::try_from(index + 1)).transpose().ok()?.unwrap_or(0));
        }
        // An opaque non-positional OLE owner never grants deletion permission.
        if has_opaque_owner { fonts.extend(ids.iter().copied()); }
        let original: BTreeSet<u16> = core.loaded_unreferenced_bin_data.iter().copied().collect();
        let plan = plan(&ids, &refs, &original, &fonts)?;
        let dropped: BTreeSet<u16> = ids.iter().zip(&plan.kept).filter_map(|(&id, keep)| (!keep).then_some(id)).collect();
        let mut index = 0;
        document.bin_data_content.retain(|_| { let keep = plan.kept[index]; index += 1; keep });
        let retained: BTreeSet<u16> = document.bin_data_content.iter().map(|content| content.id).collect();
        let mut record_positions = BTreeMap::new();
        let mut records = Vec::new();
        for (index, entry) in std::mem::take(&mut document.doc_info.bin_data_list).into_iter().enumerate() {
            if !dropped.contains(&entry.storage_id) || retained.contains(&entry.storage_id) {
                let key = if entry.storage_id != 0 { u32::from(entry.storage_id) }
                    else if matches!(&entry.data_type, BinDataType::Link) { 65536 + u32::try_from(index + 1).ok()? }
                    else { return None; };
                record_positions.insert(key, u16::try_from(records.len() + 1).ok()?);
                records.push(entry);
            }
        }
        document.doc_info.bin_data_list = records;
        slots(&mut document, &mut |_, id| {
            if *id != 0 {
                let key = sources.get(id)?;
                *id = if let Some(position) = record_positions.get(key) { *position } else { u16::try_from(*key).ok()? };
            }
            Some(())
        }, &mut |_, _| Some(()))?;
        canonical_manifest(&mut document)?;
        Some(document)
    }

    fn bindings(document: &Document) -> Option<Vec<(u8, u32, Option<String>)>> {
        let mut temporary = document.clone();
        let mut result = Vec::new();
        let mut opaque = Vec::new();
        slots(&mut temporary, &mut |role, id| {
            let storage = source_storage(document, *id)?;
            let target = document.doc_info.bin_data_list.iter().find(|entry| entry.storage_id == storage && matches!(&entry.data_type, BinDataType::Link)).map(|entry| entry.abs_path.clone().or_else(|| entry.rel_path.clone()).unwrap_or_default());
            result.push((role, u32::from(storage), target)); Some(())
        }, &mut |id, target| { opaque.push((8, id, target.map(str::to_owned))); Some(()) })?;
        result.extend(font_bindings(document).into_iter().map(|(role, id)| (role, u32::from(id), None)));
        result.extend(opaque);
        // Unreferenced external descriptors retain their URI as well; they are
        // metadata owners even though no external bytes may be fetched here.
        result.extend(document.doc_info.bin_data_list.iter().filter(|entry| matches!(&entry.data_type, BinDataType::Link)).map(|entry| (9, u32::from(entry.storage_id), Some(entry.abs_path.clone().or_else(|| entry.rel_path.clone()).unwrap_or_default()))));
        Some(result)
    }

    // This proves exact preserved ZIP encoding, including its verification
    // metadata. CRC or decompressed length by itself never proves equality.
    fn payload(left: &BinDataBytes, right: &BinDataBytes) -> bool {
        if let (BinDataBytes::Loaded(a), BinDataBytes::Loaded(b)) = (left, right) { return a == b; }
        if let (Some(a), Some(b)) = (left.load_deflated_zip_entry(), right.load_deflated_zip_entry()) {
            if a.crc32 == b.crc32 && a.uncompressed_size == b.uncompressed_size && a.compressed_bytes == b.compressed_bytes { return true; }
        }
        match (left.load_limited_shared(MAX_BIN_DATA_BYTES), right.load_limited_shared(MAX_BIN_DATA_BYTES)) {
            (Some(a), Some(b)) => a.as_ref() == b.as_ref(),
            _ => false,
        }
    }

    fn empty(content: &BinDataContent) -> bool {
        match &content.data {
            BinDataBytes::Loaded(bytes) => bytes.is_empty(),
            data => data.load_limited_shared(0).is_some_and(|bytes| bytes.is_empty()),
        }
    }

    fn indexed(document: &Document) -> Option<BTreeMap<u16, &BinDataContent>> {
        let mut entries = BTreeMap::new();
        for content in &document.bin_data_content {
            if content.id == 0 {
                if !empty(content) { return None; }
            } else if entries.insert(content.id, content).is_some() { return None; }
        }
        Some(entries)
    }

    pub(super) fn same_resources(expected: &Document, actual: &Document) -> bool {
        let Some(expected_bindings) = bindings(expected) else { return false; };
        let Some(actual_bindings) = bindings(actual) else { return false; };
        if expected_bindings != actual_bindings { return false; }
        let Some(left) = indexed(expected) else { return false; };
        let Some(right) = indexed(actual) else { return false; };
        for (id, content) in &left {
            match right.get(id) {
                Some(other) if content.extension.eq_ignore_ascii_case(&other.extension) && payload(&content.data, &other.data) => {},
                None if empty(content) => {},
                _ => return false,
            }
        }
        for (id, content) in &right {
            if !left.contains_key(id) && !empty(content) { return false; }
        }
        true
    }
}

/// Independent source-state expectation; no export or serialized output is read.
pub fn hwpx_persistence_expected_document(core: &crate::DocumentCore) -> Option<Document> {
    opengeul_resource_expectation::expected(core)
}

/// Retained resource bytes and semantic bindings remain independently exact.
pub fn hwpx_persistence_resources_match(expected: &Document, actual: &Document) -> bool {
    opengeul_resource_expectation::same_resources(expected, actual)
}
'''

REPLACEMENTS = {'third_party/rhwp/src/serializer/hwpx/roundtrip.rs': (('/// IR diff 결과 — 발견된 차이 목록을 보관.\n',
                                                        ('/// Independent stored-model expectation for HWPX edit-save verification.\n/// This never reads the serialized output or changes the open live document.\n/// Only cache partitions that the existing writer proves non-persistent are\n/// removed. Context-dependent slot/axis transformations remain fail-closed in\n/// the original comparator; this is not a general serialization projection.\npub fn hwpx_persistence_document(live: &Document) -> Document {\n    use crate::model::identity::walk::{walk, Node};\n    use crate::model::paragraph::{LineSeg, Paragraph};\n\n    fn project(para: &mut Paragraph) {\n        let serializable_line_segs = para.serializable_line_segs();\n        // The exact owner predicate is copied mechanically from the pinned\n        // HWPX writer. Here the entire serializable partition must be derived;\n        // mixed/context-dependent axis subsets stay in the strict comparison.\n        let axis_line_segs = serializable_line_segs;\n        let imported_stored_origin = para\n            .source_line_seg_vertical_pos\n            .as_ref()\n            .is_some_and(|v| v.len() == serializable_line_segs.len())\n            && serializable_line_segs.iter().all(|s| {\n                s.tag & LineSeg::TAG_EMPTY_SEGMENT == 0\n                    && s.line_height > 0\n                    && s.text_height > 0\n            });\n        let all_synthetic = !imported_stored_origin\n            && !axis_line_segs.is_empty()\n            && axis_line_segs\n                .iter()\n                .all(|s| s.tag & LineSeg::TAG_IMPLEMENTATION_PROPERTY != 0);\n        let mut stored = if !crate::serializer::line_cache::can_serialize_hwpx_line_partition(para) || all_synthetic\n            || (para.source_line_seg_vertical_pos.is_some() && !imported_stored_origin) {\n            Vec::new()\n        } else {\n            serializable_line_segs.to_vec()\n        };\n        if let Some(source_vpos) = para.source_line_seg_vertical_pos.as_deref()\n            .filter(|v| v.len() == serializable_line_segs.len())\n        {\n            for (row, original) in stored.iter_mut().zip(source_vpos) {\n                row.vertical_pos = *original;\n            }\n        }\n        // Change only the clone\'s cache partition; retain axes, dirty state,\n        // source ownership, text, formatting, controls and all live history.\n        para.line_segs = stored;\n        para.layout_only_fill_lines = 0;\n    }\n    fn paragraphs(paras: &mut [Paragraph]) {\n        walk(paras, |node| {\n            if let Node::Paragraph(para) = node { project(para); }\n            Ok(())\n        }).expect("the paragraph projection callback is infallible");\n    }\n    let mut expected = live.clone();\n    for section in &mut expected.sections {\n        paragraphs(&mut section.paragraphs);\n        for master in &mut section.section_def.master_pages {\n            paragraphs(&mut master.paragraphs);\n        }\n    }\n    expected\n}\n\n' + RESOURCE_EXPECTATION_API + '\n/// IR diff 결과 — 발견된 차이 목록을 보관.\n')),
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
 'third_party/rhwp/src/cli/commands/edit/runtime.rs': (('        rhwp::serializer::hwpx::roundtrip::diff_exported_hwpx_documents(\n            &doc.hwpx_export_expected_document(),\n            reloaded.document(),\n        )',
                                                        '        // Preserve independently derived live content, resource ownership and bytes.\n        let expected = match rhwp::serializer::hwpx::roundtrip::hwpx_persistence_expected_document(doc) {\n            Some(document) => document,\n            None => return (serde_json::json!({ "identical": false, "diffCount": null }), true),\n        };\n        let actual = rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(reloaded.document());\n        if !rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match(&expected, &actual) {\n            return (serde_json::json!({ "identical": false, "diffCount": null }), true);\n        }\n        let strict_diff = rhwp::serializer::hwpx::roundtrip::diff_documents(&expected, &actual);\n        if !strict_diff.is_empty() {\n            strict_diff\n        } else {\n        rhwp::serializer::hwpx::roundtrip::diff_exported_hwpx_documents(\n            &doc.hwpx_export_expected_document(),\n            reloaded.document(),\n        )\n        }'),),
 'third_party/rhwp/src/serializer/hwpx/field.rs': (('fn field_type_attr(field: &Field) -> &str {',
                                                    'pub(crate) fn field_type_attr(field: &Field) -> &str '
                                                    '{'),),
 'third_party/rhwp/src/parser/hwpx/content.rs': (('                        let mut is_embedded = true;\n'
  '                        for attr in e.attributes().flatten() {',
  '                        let mut is_embedded = true;\n'
  '                        let mut href_present = false;\n'
  '                        for attr in e.attributes().flatten() {'),
 ('                                b"href" => href = attr_value(&attr),',
  '                                b"href" => { href = attr_value(&attr); href_present = true; },'),
 ('                        if !id.is_empty() && !href.is_empty() {',
  '                        // A declared external missing-image placeholder still owns\n'
  '                        // a manifest position. A missing href or empty embedded/XML\n'
  '                        // path remains invalid and cannot shift other resource owners.\n'
  '                        let declared_empty_link = href_present && href.is_empty()\n'
  '                            && !id.trim().is_empty() && !is_embedded\n'
  '                            && media_type != "application/xml";\n'
  '                        if !id.is_empty() && (!href.is_empty() || declared_empty_link) {'))}
# Separate exporter backport; the independent oracle above uses identity walk.
REPLACEMENTS['third_party/rhwp/src/document_core/commands/bin_data_prune.rs'] = (('    fn visit_shape(shape: &mut ShapeObject, f: &mut dyn FnMut(&mut u16)) {\n',
  '    // Chart placeholders name Chart/*.xml; their fallback is a distinct OLE.\n'
  '    fn visit_ole(ole: &mut crate::model::shape::OleShape, f: &mut dyn FnMut(&mut u16)) {\n'
  '        visit_drawing(&mut ole.drawing, f);\n'
  '        if let Some(caption) = ole.caption.as_mut() {\n'
  '            visit_paragraphs(&mut caption.paragraphs, f);\n'
  '        }\n'
  '        if ole.chart_id_ref.is_none() {\n'
  '            if let Ok(mut id) = u16::try_from(ole.bin_data_id) {\n'
  '                f(&mut id);\n'
  '                ole.bin_data_id = u32::from(id);\n'
  '            }\n'
  '        }\n'
  '        if let Some(fallback) = ole.chart_switch_fallback.as_mut() {\n'
  '            visit_ole(fallback, f);\n'
  '        }\n'
  '    }\n'
  '\n'
  '    fn visit_shape(shape: &mut ShapeObject, f: &mut dyn FnMut(&mut u16)) {\n'),
 ('            ShapeObject::Ole(ole) => {\n'
  '                visit_drawing(&mut ole.drawing, f);\n'
  '                if let Some(caption) = ole.caption.as_mut() {\n'
  '                    visit_paragraphs(&mut caption.paragraphs, f);\n'
  '                }\n'
  '                // OLE 의 참조는 `u32` 다. `u16` 범위 밖이면 순번 의미가 아니므로\n'
  '                // 손대지 않는다 — 모으는 쪽도 같은 조건으로 건너뛴다.\n'
  '                if let Ok(mut id) = u16::try_from(ole.bin_data_id) {\n'
  '                    f(&mut id);\n'
  '                    ole.bin_data_id = u32::from(id);\n'
  '                }\n'
  '            }\n',
  '            ShapeObject::Ole(ole) => visit_ole(ole, f),\n'),
 ('    for section in &mut doc.sections {\n'
  '        visit_paragraphs(&mut section.paragraphs, f);\n'
  '    }\n',
  '    for section in &mut doc.sections {\n'
  '        visit_paragraphs(&mut section.paragraphs, f);\n'
  '        for master in &mut section.section_def.master_pages {\n'
  '            visit_paragraphs(&mut master.paragraphs, f);\n'
  '        }\n'
  '    }\n'),
 ('    kept_storage.extend(keep_storage);\n',
  '    kept_storage.extend(keep_storage);\n'
  '    // Chart/*.xml is a separate package role, not a BinData manifest resource.\n'
  '    kept_storage.extend(doc.bin_data_content.iter().filter(|content| content.extension == '
  '"ooxml_chart").map(|content| content.id));\n'),
 ('    visit_bin_data_refs(doc, &mut |id| {\n'
  '        if *id > 0 && (*id as usize) <= before {\n'
  '            referenced.insert(*id as usize - 1);\n'
  '        }\n'
  '    });',
  '    let mut raw_refs = Vec::new();\n'
  '    visit_bin_data_refs(doc, &mut |id| raw_refs.push(*id));\n'
  '    for id in raw_refs {\n'
  '        if id == 0 { continue; }\n'
  '        if let Some(record) = doc.doc_info.bin_data_list.get(usize::from(id) - 1) {\n'
  '            if record.storage_id == 0 && record.data_type == '
  'crate::model::bin_data::BinDataType::Link {\n'
  '                if let Some(content) = doc.bin_data_content.get(usize::from(id) - 1) {\n'
  '                    if crate::model::bin_data::is_hwp5_link_slot(content, Some(record)) { '
  'referenced.insert(usize::from(id) - 1); }\n'
  '                }\n'
  '                continue;\n'
  '            }\n'
  '        }\n'
  '        let storage = match doc.doc_info.bin_data_list.get(usize::from(id) - 1) {\n'
  '            Some(record) if record.storage_id != 0 => record.storage_id,\n'
  '            // Ambiguous explicit metadata grants no deletion permission. Keep\n'
  '            // the clone unchanged; the independent source gate rejects it.\n'
  '            Some(_) => { referenced.extend(0..before); continue; },\n'
  '            None => id,\n'
  '        };\n'
  '        if let Some(index) = doc.bin_data_content.iter().position(|content| content.id == '
  'storage) {\n'
  '            referenced.insert(index);\n'
  '        }\n'
  '    }'),
 ('    visit_bin_data_refs(doc, &mut |id| {\n'
  '        if *id == 0 || (*id as usize) > before {\n'
  '            return;\n'
  '        }\n'
  '        if let Some(next) = new_index[*id as usize - 1] {\n'
  '            *id = (next + 1) as u16;\n'
  '        }\n'
  '    });',
  '    let retained_storage: BTreeSet<u16> = '
  'doc.bin_data_content.iter().enumerate().filter(|(index, _)| '
  'new_index[*index].is_some()).map(|(_, content)| content.id).collect();\n'
  '    let dropped_before_remap: BTreeSet<u16> = '
  'doc.bin_data_content.iter().enumerate().filter(|(index, _)| '
  'new_index[*index].is_none()).map(|(_, content)| content.id).collect();\n'
  '    let mut next_record = 0u16;\n'
  '    let mut record_positions = std::collections::BTreeMap::new();\n'
  '    for (index, entry) in doc.doc_info.bin_data_list.iter().enumerate() {\n'
  '        if !dropped_before_remap.contains(&entry.storage_id) || '
  'retained_storage.contains(&entry.storage_id) {\n'
  '            next_record += 1;\n'
  '            if entry.storage_id != 0 || entry.data_type == '
  'crate::model::bin_data::BinDataType::Link { record_positions.insert((index + 1) as u16, '
  'next_record); }\n'
  '        }\n'
  '    }\n'
  '    visit_bin_data_refs(doc, &mut |id| {\n'
  '        if let Some(next) = record_positions.get(id) { *id = *next; }\n'
  '    });'))

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
