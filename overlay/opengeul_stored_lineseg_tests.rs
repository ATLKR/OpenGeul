//! Authored public-API field documents and adversarial stored row ownership.
//! No original/private documents, font programs, CLI bypass or weakened IR diff.
use rhwp::{DocumentCore, model::{document::Document, paragraph::{LineSeg, Paragraph}}};
use rhwp::model::control::Control;
use rhwp::serializer::hwpx::roundtrip::{diff_documents, strip_hwp_to_hwpx_noise};

fn external_stored_hwp(bytes: Vec<u8>) -> Vec<u8> {
    use std::io::{Cursor, Read};
    // The authored CFB becomes an external-store adversary by removing only its
    // rhwp authentication witness. The original BodyText bytes remain exact.
    let mut file=cfb::CompoundFile::open(Cursor::new(bytes)).expect("owned authored CFB");
    let before={let mut row=Vec::new();file.open_stream("/BodyText/Section0").expect("owned body stream").read_to_end(&mut row).expect("owned body bytes");row};
    file.remove_stream("/RhwpLineSegTags").expect("remove only the authored authentication witness");
    let bytes=file.into_inner().into_inner();
    let mut readback=cfb::CompoundFile::open(Cursor::new(bytes.clone())).expect("owned external CFB readback");
    let mut after=Vec::new();readback.open_stream("/BodyText/Section0").expect("same original body stream").read_to_end(&mut after).expect("same original body bytes");
    assert_eq!(before,after,"fixture classification cannot rewrite the actual stored record payload");
    assert!(readback.open_stream("/RhwpLineSegTags").is_err(),"the external fixture cannot retain an authenticated-runtime witness");
    bytes
}

fn authored() -> Vec<u8> {
    let mut core=DocumentCore::new_empty();
    core.create_blank_document_native().expect("owned blank");
    for (i,text) in ["BODY-ROOT","BODY-TAIL","CUSTOMER:","ITEM:",""].iter().enumerate() {
        if !text.is_empty(){core.insert_text_native(0,i,0,text).expect("public text");}
        if i<4 {core.split_paragraph_native(0,i,text.chars().count(),None).expect("public paragraph split");}
    }
    core.insert_click_here_field_at(0,2,9,"Customer","owned regression","CUSTOMER",true).expect("public body field");
    core.insert_click_here_field_at(0,3,5,"Item","owned regression","ITEM",true).expect("public repeated body field");
    core.create_table_native(0,4,0,2,2).expect("public table");
    for (cell,text) in ["CELL-R0-C0","CELL-R0-C1","CELL-R1-C0","CELL-R1-C1|"].iter().enumerate() {
        core.insert_text_in_cell_native(0,4,0,cell,0,0,text).expect("public cell text");
    }
    core.insert_click_here_field_at_in_cell(0,4,0,3,0,11,false,"Item","owned regression","ITEM",true).expect("public table field");
    core.set_field_value_by_name_at("CUSTOMER",0,"C-INIT").expect("public body value");
    core.set_field_value_by_name_at("ITEM",0,"I-BODY").expect("public first repeated value");
    core.set_field_value_by_name_at("ITEM",1,"I-CELL").expect("public second repeated value");
    external_stored_hwp(core.export_hwp_native().expect("native HWP serialization"))
}

fn fields(doc: &Document) -> Vec<&Paragraph> {
    fn visit<'a>(p: &'a Paragraph, out: &mut Vec<&'a Paragraph>) {
        if p.controls.iter().any(|c|matches!(c,Control::Field(_))){out.push(p);}
        for control in &p.controls {
            if let Control::Table(table)=control {
                for cell in &table.cells {for p in &cell.paragraphs {visit(p,out);}}
            }
        }
    }
    let mut result=Vec::new();
    for section in &doc.sections {for p in &section.paragraphs {visit(p,&mut result);}}
    assert_eq!(result.len(),3,"body and table fields retain their owners");
    result
}

fn tuples(p: &Paragraph) -> Vec<[i64;9]> {
    p.serializable_line_segs().iter().map(|s|[s.text_start as i64,s.vertical_pos as i64,
        s.line_height as i64,s.text_height as i64,s.baseline_distance as i64,
        s.line_spacing as i64,s.column_start as i64,s.segment_width as i64,s.tag as i64]).collect()
}

fn assert_rows(a: &Document,b: &Document) {
    for (before,after) in fields(a).iter().zip(fields(b)) {
        assert_eq!(tuples(before),tuples(after),"all nine stored row fields must remain exact");
        assert!(!after.serializable_line_segs().is_empty());
    }
}

#[test]
fn authored_positive_body_and_cell_rows_survive_hwp_hwpx_hwp() {
    let input=authored();let before=rhwp::parse_document(&input).expect("parse native authored HWP");
    for p in fields(&before) {
        assert_eq!(p.source_line_seg_vertical_pos.as_ref().expect("actual imported origin").len(),p.serializable_line_segs().len());
        assert!(p.line_segs.iter().all(|s|s.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY==0 && s.line_height>0 && s.text_height>0),"upstream normalizes the non-authenticated bit while the parser retains actual stored ownership");
    }
    let xml=rhwp::serializer::serialize_hwpx(&before).expect("HWP to HWPX");
    let middle=rhwp::parse_document(&xml).expect("parse HWPX");
    let diff=strip_hwp_to_hwpx_noise(diff_documents(&before,&middle));
    assert!(diff.is_empty(),"unchanged CLI IR verification: {diff:?}");
    assert_rows(&before,&middle);
    let back=DocumentCore::from_bytes(&xml).expect("public HWPX import").export_hwp_with_adapter().expect("public HWPX to HWP");
    let after=rhwp::parse_document(&back).expect("parse saved native HWP");assert_rows(&before,&after);
}

#[test]
fn shared_hwp_projection_preserves_owned_fallback_and_rejects_runtime_rows() {
    for case in 0..7 {
        let mut core=DocumentCore::from_bytes(&persistence_owned_hwpx_input()).expect("public source-line HWPX import");
        let original=tuples(fields(core.document())[0]);assert!(!original.is_empty());
        let p=&mut core.document_mut().sections[0].paragraphs[2];
        assert_eq!(p.source_line_seg_vertical_pos.as_ref().expect("parser-owned positive source").len(),p.serializable_line_segs().len());
        match case {
            0=>{},
            1=>{let mut fill=p.line_segs[0].clone();fill.vertical_pos=999999;p.line_segs.push(fill);p.layout_only_fill_lines=1;},
            2=>{p.source_line_seg_vertical_pos=None;for row in &mut p.line_segs{row.tag|=LineSeg::TAG_IMPLEMENTATION_PROPERTY;}},
            3=>{p.source_line_seg_vertical_pos=Some(Vec::new());for row in &mut p.line_segs{row.tag|=LineSeg::TAG_IMPLEMENTATION_PROPERTY;}},
            4=>{p.line_segs[0].tag|=LineSeg::TAG_EMPTY_SEGMENT;p.line_segs[0].line_height=0;p.line_segs[0].text_height=0;},
            5=>p.invalidate_layout_inputs(),
            _=>p.line_segs[0].text_start=p.char_count+1000,
        }
        let mut fallback=tuples(p);
        if let Some(positions)=&p.source_line_seg_vertical_pos {
            for (row,source) in fallback.iter_mut().zip(positions) {row[1]=*source as i64;}
        }
        let live=format!("{:?}",core.document());
        if case==6 {
            // c909 HWP keeps an all-outside original cache as its deliberate
            // loss-avoidance fallback. HWPX must instead omit that same cache.
            // Keep both format-specific policies; no general axis exception.
            let xml=core.export_hwpx_native().expect("out-of-axis HWPX export");
            let xml_readback=rhwp::parse_document(&xml).expect("out-of-axis HWPX readback");
            assert!(fields(&xml_readback)[0].line_segs.is_empty(),"HWPX still rejects the out-of-axis source cache");
        }
        let bytes=core.export_hwp_with_adapter().expect("public HWP source-line export");
        let after=rhwp::parse_document(&bytes).expect("actual HWP source-line readback");
        assert!(after.hwpx_origin_keeps_source_lines(),"the actual HWP output binds the source-line lineage boundary");
        if case<=1 {assert_eq!(tuples(fields(&after)[0]),original,"only the parser-owned serializable prefix crosses the shared HWP boundary");}
        else if case==6 {assert_eq!(tuples(fields(&after)[0]),fallback,"all nine original source row fields survive the intentional HWP fallback");}
        else {assert!(fields(&after)[0].line_segs.is_empty(),"invalid or unowned runtime partition cannot become stored HWP evidence");}
        assert_eq!(format!("{:?}",core.document()),live,"shared cache projection changes only the serializer's clone");
    }
}

#[test]
fn imported_hwpx_stored_flags_coordinates_and_layout_survive_repeated_save() {
    let original=rhwp::parse_document(&authored()).expect("HWP");
    let first=rhwp::serializer::serialize_hwpx(&original).expect("first HWPX");
    let imported=rhwp::parse_document(&first).expect("actual HWPX parser origin");
    let second=rhwp::serializer::serialize_hwpx(&imported).expect("second HWPX");
    let reloaded=rhwp::parse_document(&second).expect("saved HWPX");
    assert!(diff_documents(&imported,&reloaded).is_empty());assert_rows(&imported,&reloaded);
    let core=DocumentCore::from_bytes(&second).expect("public saved document");assert_eq!(core.page_count(),1);
    for p in fields(core.document()) {assert!(p.line_segs.iter().all(|s|s.line_height>0 && s.text_height>0 && s.baseline_distance>=0));}
}

#[test]
fn public_field_and_text_edits_cannot_resurrect_stale_stored_origin() {
    for (name,occurrence) in [("CUSTOMER",0),("ITEM",1)] {
        let mut core=DocumentCore::from_bytes(&authored()).expect("public imported document");
        core.set_field_value_by_name_at(name,occurrence,"CHANGED-OWNED-한글").expect("public body/cell field edit");
        let target=if name=="CUSTOMER"{0}else{2};
        let edited=fields(core.document())[target];
        assert!(edited.source_line_seg_vertical_pos.is_none() || edited.stored_text_partition_is_dirty(),"edited source is invalidated or replaced by its owner");
        let output=core.export_hwpx_native().expect("edited HWPX");
        let saved=rhwp::parse_document(&output).expect("read edited HWPX");
        assert!(fields(&saved)[target].line_segs.is_empty(),"runtime-only synthetic rows are omitted");
        assert!(fields(&saved)[target].text.contains("CHANGED-OWNED-한글"));
    }
    let mut core=DocumentCore::from_bytes(&authored()).expect("public import for text edit");
    core.insert_text_native(0,2,0,"REAL-TEXT-EDIT-").expect("public field paragraph text edit");
    let edited=fields(core.document())[0];
    assert!(edited.source_line_seg_vertical_pos.is_none() || edited.stored_text_partition_is_dirty());
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("text edited export")).expect("read edited text");
    assert!(fields(&saved)[0].line_segs.is_empty());assert!(fields(&saved)[0].text.starts_with("REAL-TEXT-EDIT-"));
}

#[test]
fn public_picture_tac_replacement_cannot_reuse_same_count_stored_origin() {
    // Original owned one-pixel PNG. Construct through the public author API,
    // then store a positive bit31 row to exercise the parser-observed boundary.
    // This adversarial source is a regression input, never Source evidence.
    const PNG: &[u8]=&[137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130];
    let mut author=DocumentCore::new_empty();author.create_blank_document_native().expect("owned picture blank");
    author.insert_picture_native(0,0,0,&[],PNG,11339,5669,1,1,"png","OWNED-LINE-ORIGIN",Some(8504),Some(28346)).expect("public picture insertion");
    let mut stored=rhwp::parse_document(&author.export_hwp_native().expect("owned picture HWP")).expect("stored authored picture");
    stored.sections[0].raw_stream=None;
    let p=&mut stored.sections[0].paragraphs[0];
    assert_eq!(p.line_segs.len(),1);assert!(p.line_segs[0].line_height>0&&p.line_segs[0].text_height>0);
    p.line_segs[0].tag|=LineSeg::TAG_IMPLEMENTATION_PROPERTY;p.line_segs[0].vertical_pos=7777;
    let input=external_stored_hwp(rhwp::serializer::serialize_document(&stored).expect("actual stored regression bytes"));
    let parsed=rhwp::parse_document(&input).expect("public parser");
    assert_eq!(parsed.sections[0].paragraphs[0].source_line_seg_vertical_pos,Some(vec![7777]));
    let mut core=DocumentCore::from_bytes(&input).expect("public stored picture import");
    let picture_idx=core.document().sections[0].paragraphs[0].controls.iter().position(|control|match control {
        Control::Picture(_)=>true,
        Control::Shape(shape)=>matches!(shape.as_ref(),rhwp::model::shape::ShapeObject::Picture(_)),
        _=>false,
    }).expect("actual parsed picture owner, after section/column definitions");
    for tac in [true,false] {
        let result=core.set_picture_properties_native(0,0,picture_idx,if tac{r#"{"treatAsChar":true}"#}else{r#"{"treatAsChar":false}"#}).expect("public TAC transition");
        assert_eq!(serde_json::from_str::<serde_json::Value>(&result).expect("public outcome")["ok"],true);
    }
    let current=&core.document().sections[0].paragraphs[0];
    assert!(current.source_line_seg_vertical_pos.is_none()||current.stored_text_partition_is_dirty(),"public rebuilt same-count vector cannot retain the old source owner");
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("picture edit save")).expect("picture edit readback");
    assert!(saved.sections[0].paragraphs[0].line_segs.is_empty(),"runtime rebuilt bit31 rows must remain excluded");
    let mut images=0;
    for page in 0..core.page_count() {images+=core.render_page_svg_native(page).expect("all-page public picture render").matches("<image").count();}
    assert_eq!(images,1,"picture remains visible through ownership invalidation");
}

#[test]
fn incomplete_snapshot_placeholder_dirty_and_out_of_axis_rows_stay_excluded() {
    for kind in 0..5 {
        let mut doc=rhwp::parse_document(&authored()).expect("authored imported source");
        let p=&mut doc.sections[0].paragraphs[2];
        match kind {
            0=>p.source_line_seg_vertical_pos=Some(Vec::new()),
            1=>p.source_line_seg_vertical_pos.as_mut().expect("origin").push(999),
            2=>{p.line_segs[0].tag|=LineSeg::TAG_EMPTY_SEGMENT;p.line_segs[0].line_height=0;p.line_segs[0].text_height=0;},
            3=>p.invalidate_layout_inputs(),
            4=>p.line_segs[0].text_start=p.char_count+1000,
            _=>unreachable!(),
        }
        let bytes=rhwp::serializer::serialize_hwpx(&doc).expect("safe export");
        let after=rhwp::parse_document(&bytes).expect("safe reload");
        assert!(fields(&after)[0].line_segs.is_empty(),"invalid source lineage/cache kind {kind} must not be emitted");
    }
}

fn record(tag:u32,level:u32,data:&[u8],out:&mut Vec<u8>) {
    assert!(data.len()<4095);out.extend_from_slice(&(tag|(level<<10)|((data.len() as u32)<<20)).to_le_bytes());out.extend_from_slice(data);
}
fn row(vpos:i32,height:i32,tag:u32)->Vec<u8> {
    let mut value=Vec::new();value.extend_from_slice(&0u32.to_le_bytes());
    for n in [vpos,height,height,850,600,0,1000] {value.extend_from_slice(&n.to_le_bytes());}
    value.extend_from_slice(&tag.to_le_bytes());value
}

#[test]
fn external_stored_positive_bit31_is_not_authenticated_runtime_origin() {
    let mut bytes=Vec::new();let mut header=vec![0;22];header[..4].copy_from_slice(&2u32.to_le_bytes());
    record(66,0,&header,&mut bytes);record(67,1,&[b'A',0,13,0],&mut bytes);
    record(69,1,&row(7777,1000,0x80060000),&mut bytes);
    let section=rhwp::parser::body_text::parse_body_text_section(&bytes).expect("actual external stored row parser");
    let p=&section.paragraphs[0];
    assert_eq!(p.source_line_seg_vertical_pos,Some(vec![7777]),"sized external stored rows retain their actual vpos owner");
    assert_eq!(p.line_segs[0].tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY,0,"upstream clears the non-authenticated runtime bit");
}

#[test]
fn hwpx_sized_stored_rows_keep_origin_without_requiring_runtime_tag() {
    use rhwp::parser::hwpx::section::parse_hwpx_section;
    for (flags,height,expected) in [
        (0,1000,Some(vec![7777])),
        (LineSeg::TAG_IMPLEMENTATION_PROPERTY,1000,Some(vec![7777])),
        (LineSeg::TAG_EMPTY_SEGMENT,1000,None),
        (0,0,None),
    ] {
        let xml=format!(r#"<hs:sec xmlns:hs="urn:hwp:section" xmlns:hp="urn:hwp:paragraph"><hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:t>A</hp:t></hp:run><hp:linesegarray><hp:lineseg textpos="0" vertpos="7777" vertsize="{height}" textheight="{height}" baseline="850" spacing="600" horzpos="0" horzsize="1000" flags="{flags}"/></hp:linesegarray></hp:p></hs:sec>"#);
        let section=parse_hwpx_section(&xml).expect("authored synthetic stored section");
        assert_eq!(section.paragraphs.len(),1);
        assert_eq!(section.paragraphs[0].source_line_seg_vertical_pos,expected);
    }
}

#[test]
fn authenticated_native_runtime_rows_do_not_become_external_stored_origin() {
    let mut author=DocumentCore::new_empty();author.create_blank_document_native().expect("owned authenticated blank");
    author.insert_text_native(0,0,0,"AUTHENTICATED-RUNTIME-ROW").expect("public authored text");
    let bytes=author.export_hwp_native().expect("actual authenticated native HWP");
    let parsed=rhwp::parse_document(&bytes).expect("actual section digest authentication");
    assert!(parsed.extra_streams.iter().any(|(name,_)|name=="/RhwpLineSegTags"),"the actual native output carries its semantic witness");
    let runtime:Vec<_>=parsed.sections.iter().flat_map(|s|s.paragraphs.iter())
        .filter(|p|p.line_segs.iter().any(|r|r.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY!=0)).collect();
    assert!(!runtime.is_empty(),"the witness must cover actual positive runtime rows");
    for p in runtime {assert!(p.source_line_seg_vertical_pos.is_none(),"authenticated synthetic rows cannot gain external ownership on parse");}
}

#[test]
fn later_direct_child_line_record_replacement_never_inherits_prior_origin() {
    for placeholder in [false,true] {
        let mut bytes=Vec::new();let mut header=vec![0;22];header[..4].copy_from_slice(&2u32.to_le_bytes());
        record(66,0,&header,&mut bytes);record(67,1,&[b'A',0,13,0],&mut bytes);
        record(69,1,&row(100,1000,0x80060000),&mut bytes);
        record(69,1,&row(250,if placeholder{0}else{1000},if placeholder{0x80070000}else{0x60000}),&mut bytes);
        let section=rhwp::parser::body_text::parse_body_text_section(&bytes).expect("actual direct-child parser");
        let p=&section.paragraphs[0];assert!(p.source_line_seg_vertical_pos.is_none(),"last parsed vector owns its origin");
        if !p.line_segs.is_empty(){assert_eq!(p.line_segs[0].vertical_pos,250);}
    }
}

// Additive Source4 boundaries. The original six tests above remain unchanged.
const OWNER_PNG: &[u8]=&[137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130];

fn owner_picture_core() -> DocumentCore {
    let mut author=DocumentCore::new_empty();author.create_blank_document_native().expect("owned owner blank");
    author.insert_picture_native(0,0,0,&[],OWNER_PNG,11339,5669,1,1,"png","OWNED-ROW-OWNER",Some(8504),Some(28346)).expect("public owner picture");
    DocumentCore::from_bytes(&external_stored_hwp(author.export_hwp_native().expect("owned stored source"))).expect("public stored owner import")
}

fn owner_picture_index(p: &Paragraph) -> usize {
    p.controls.iter().position(|control|match control {
        Control::Picture(_)=>true,
        Control::Shape(shape)=>matches!(shape.as_ref(),rhwp::model::shape::ShapeObject::Picture(_)),
        _=>false,
    }).expect("actual picture owner")
}

fn owner_text_state(p: &Paragraph) -> (String,Vec<u32>,Vec<(u32,u32)>,usize) {
    (p.text.clone(),p.char_offsets.clone(),p.char_shapes.iter().map(|s|(s.start_pos,s.char_shape_id)).collect(),p.controls.len())
}

fn assert_recomputed_picture_partition(p: &Paragraph) {
    assert!(p.source_line_seg_vertical_pos.is_none(),"fresh rows cannot claim their replaced source owner");
    assert!(!p.stored_text_partition_is_dirty(),"actual full reflow publishes a current text/control partition");
    assert_eq!(p.hwpx_axis_shift,0,"newly computed rows use the current HWP paragraph axis");
    assert!(!p.line_segs.is_empty());
    assert_eq!(p.layout_only_fill_lines,0);
    assert_eq!(p.layout_space_metrics.len(),p.line_segs.len(),"the same fill publishes every row's metrics");
    for (row,(start,_)) in p.line_segs.iter().zip(&p.layout_space_metrics) {
        assert_eq!(row.text_start,*start);
        assert!(row.text_start<=p.char_count);
        assert!(row.line_height>0&&row.text_height>0&&row.baseline_distance>0);
        assert_eq!(row.tag&LineSeg::TAG_EMPTY_SEGMENT,0);
        assert_ne!(row.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY,0,"fresh runtime rows are not imported cache evidence");
    }
}

#[test]
fn public_tac_recomputes_dirty_partition_and_publishes_fresh_owned_metrics() {
    let mut core=owner_picture_core();let index=owner_picture_index(&core.document().sections[0].paragraphs[0]);
    let before=owner_text_state(&core.document().sections[0].paragraphs[0]);
    let p=&mut core.document_mut().sections[0].paragraphs[0];
    p.line_segs[0].line_height=1;p.line_segs[0].text_height=1;p.line_segs[0].baseline_distance=1;
    p.invalidate_layout_inputs();
    core.set_picture_properties_native(0,0,index,r#"{"treatAsChar":true}"#).expect("public dirty TAC");
    let after=&core.document().sections[0].paragraphs[0];
    assert_recomputed_picture_partition(after);
    assert!(after.line_segs.iter().any(|row|row.line_height>=5669&&row.text_height>=5669),"actual inline picture height replaces stale one-unit metrics");
    assert_eq!(owner_text_state(after),before,"text/control-slot structure stays unchanged");
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("dirty owner save")).expect("dirty owner readback");
    assert!(saved.sections[0].paragraphs[0].line_segs.is_empty(),"fresh bit31 rows without an imported owner remain runtime-only");
    assert_eq!(saved.sections[0].paragraphs[0].text,before.0);
    assert!(core.render_page_svg_native(0).expect("dirty owner render").contains("<image"));
}

#[test]
fn public_text_free_body_tac_publishes_recomputed_rows_before_save() {
    let mut core=owner_picture_core();let index=owner_picture_index(&core.document().sections[0].paragraphs[0]);
    // The local migration is geometry-only, but the public BODY setter then
    // performs real reflow after the TAC change. Numeric evidence is retained
    // separately from the original cb80 one-RED observation.
    let p=&mut core.document_mut().sections[0].paragraphs[0];
    p.text.clear();p.char_offsets.clear();p.invalidate_layout_inputs();
    assert!(p.stored_text_partition_is_dirty());assert!(p.layout_space_metrics.is_empty());
    let before=owner_text_state(p);
    core.set_picture_properties_native(0,0,index,r#"{"treatAsChar":true}"#).expect("public text-free body TAC");
    let after=&core.document().sections[0].paragraphs[0];
    assert_recomputed_picture_partition(after);
    assert_eq!(tuples(after),vec![[0,0,5669,5669,4819,600,0,42520,2147876864]],"the actual frame publishes all nine new row fields");
    assert_eq!(owner_text_state(after),before);assert!(!after.layout_object_projection);assert!(!after.layout_float_band);
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("text-free body save")).expect("text-free body readback");
    assert!(saved.sections[0].paragraphs[0].line_segs.is_empty(),"fresh bit31 frame rows remain runtime-only");
}

#[test]
fn public_text_free_header_footer_tac_keeps_dirty_without_reflow_publication() {
    for is_header in [true,false] {
        let mut author=owner_picture_core();author.create_header_footer_native(0,is_header,0).expect("public text-free header/footer");
        let body_picture=owner_picture_index(&author.document().sections[0].paragraphs[0]);
        let picture=author.document().sections[0].paragraphs[0].controls[body_picture].clone();
        // create_header_footer_native intentionally starts with no saved rows.
        // Author one sized source row from the independent owned body template.
        let mut source_row=author.document().sections[0].paragraphs[0].serializable_line_segs()[0].clone();
        source_row.tag=0x80060000;source_row.vertical_pos=5555;
        let paragraphs=author.document_mut().sections[0].paragraphs.iter_mut().flat_map(|p|p.controls.iter_mut()).find_map(|c|match c {
            Control::Header(h) if is_header=>Some(&mut h.paragraphs),
            Control::Footer(f) if !is_header=>Some(&mut f.paragraphs),
            _=>None,
        }).expect("owned text-free HF model");
        let p=&mut paragraphs[0];p.controls.push(picture);p.ctrl_data_records.push(None);p.char_count+=8;
        p.line_segs=vec![source_row];
        let input=external_stored_hwp(author.export_hwp_native().expect("authored stored HF cache"));
        let mut core=DocumentCore::from_bytes(&input).expect("actual parser-owned HF import");
        let address=owner_hf_address(core.document(),is_header);let (pi,ci,inner,picture)=address;
        let p=match &mut core.document_mut().sections[0].paragraphs[pi].controls[ci] {
            Control::Header(h)=>&mut h.paragraphs[inner],Control::Footer(f)=>&mut f.paragraphs[inner],
            _=>panic!("actual imported HF paragraph"),
        };
        assert_eq!(p.source_line_seg_vertical_pos.as_ref().expect("parser-observed sized source owner").len(),1);
        // Explicit dirty adversarial input. Clear bit31 so allSynthetic cannot
        // hide a lost dirty-state guard. The original source owner must also go.
        p.text.clear();p.char_offsets.clear();p.line_segs[0].tag&=!LineSeg::TAG_IMPLEMENTATION_PROPERTY;p.invalidate_layout_inputs();
        let before=owner_text_state(p);let axis=p.hwpx_axis_shift;let mut expected=tuples(p);
        assert_eq!(expected.len(),1);assert_eq!(expected[0][8]&i64::from(LineSeg::TAG_IMPLEMENTATION_PROPERTY),0);
        expected[0][2]=5669;expected[0][3]=5669;expected[0][4]=4819;
        core.set_header_footer_picture_properties_native(0,pi,ci,inner,picture,r#"{"treatAsChar":true}"#).expect("public HF geometry-only TAC");
        let after=owner_hf_paragraph(core.document(),address);
        assert!(after.stored_text_partition_is_dirty());assert!(after.source_line_seg_vertical_pos.is_none());
        assert!(after.layout_space_metrics.is_empty());assert!(!after.layout_object_projection);assert!(!after.layout_float_band);
        assert_eq!(after.layout_only_fill_lines,0);assert_eq!(after.hwpx_axis_shift,axis);
        assert_eq!(tuples(after),expected,"only three geometry fields change; no fresh partition is published");
        assert_eq!(owner_text_state(after),before);
        let props:serde_json::Value=serde_json::from_str(&core.get_header_footer_picture_properties_native(0,pi,ci,inner,picture).expect("actual HF property readback")).expect("HF property JSON");
        assert_eq!(props["treatAsChar"],true);
        let live=format!("{:?}",core.document());let bytes=core.export_hwpx_native().expect("dirty HF save");
        let saved=rhwp::parse_document(&bytes).expect("dirty HF readback");
        assert!(owner_hf_paragraph(&saved,owner_hf_address(&saved,is_header)).line_segs.is_empty(),"dirty low-bit31 rows must be omitted even though allSynthetic is false");
        assert!(format!("{:?}",core.document())==live,"persistence cannot certify or alter the open dirty input");
    }
}

#[test]
fn public_tac_never_promotes_renderer_only_suffix_to_stored_rows() {
    let mut core=owner_picture_core();let index=owner_picture_index(&core.document().sections[0].paragraphs[0]);
    let before=owner_text_state(&core.document().sections[0].paragraphs[0]);
    let p=&mut core.document_mut().sections[0].paragraphs[0];
    let mut fill=p.line_segs[0].clone();fill.vertical_pos=999999;fill.tag|=LineSeg::TAG_IMPLEMENTATION_PROPERTY;
    p.line_segs.push(fill);p.layout_only_fill_lines=1;
    assert_eq!(p.serializable_line_segs().len(),1,"owned adversarial projection has one stored row");
    core.set_picture_properties_native(0,0,index,r#"{"treatAsChar":true}"#).expect("public projected TAC");
    let after=&core.document().sections[0].paragraphs[0];
    assert_eq!(after.layout_only_fill_lines,0);assert_eq!(after.line_segs.len(),1);
    assert!(after.line_segs.iter().all(|s|s.vertical_pos!=999999));assert_eq!(owner_text_state(after),before);
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("projection owner save")).expect("projection owner readback");
    assert!(saved.sections[0].paragraphs[0].line_segs.iter().all(|s|s.vertical_pos!=999999));
    assert_eq!(saved.sections[0].paragraphs[0].text,before.0);
    assert!(core.render_page_svg_native(0).expect("projection owner render").contains("<image"));
}

fn owner_hwpx_tac_axis_input(marker:&[u8])->Vec<u8> {
    let mut author=owner_picture_core();author.insert_text_native(0,0,0,"AXIS-OWNED-1234567890").expect("public axis text");
    let mut doc=rhwp::parse_document(&author.export_hwp_native().expect("axis authored HWP")).expect("axis stored source");
    doc.sections[0].raw_stream=None;
    let p=&mut doc.sections[0].paragraphs[0];
    let mut second=p.line_segs[0].clone();second.text_start=p.char_offsets[8];second.vertical_pos+=1600;second.tag&=!LineSeg::TAG_IMPLEMENTATION_PROPERTY;
    p.line_segs[0].tag&=!LineSeg::TAG_IMPLEMENTATION_PROPERTY;p.line_segs.push(second);
    let marker_path=rhwp::model::document::HWP5_ORIGIN_HWPX_MARKER_PATH;
    doc.hwpx_aux_entries.retain(|(path,_)|path!=marker_path);
    doc.hwpx_aux_entries.push((marker_path.to_string(),marker.to_vec()));
    rhwp::serializer::serialize_hwpx(&doc).expect("explicit source-axis HWPX input")
}

fn assert_public_hwpx_tac_recomputes_source_axis(marker:&[u8],legacy:bool) {
    let bytes=owner_hwpx_tac_axis_input(marker);
    let mut core=DocumentCore::from_bytes(&bytes).expect("public leading-slot HWPX import");
    assert_eq!(core.document().hwpx_aux_entry(rhwp::model::document::HWP5_ORIGIN_HWPX_MARKER_PATH),Some(marker));
    let before=&core.document().sections[0].paragraphs[0];let shift=before.hwpx_axis_shift;
    if legacy {assert!(shift>0,"legacy marker source keeps the real leading secPr/colPr correction");}
    else {assert_eq!(shift,0,"paragraph-UTF16 marker source already includes the leading slots");}
    let starts:Vec<_>=before.line_segs.iter().map(|s|s.text_start).collect();assert!(starts.iter().any(|s|*s>0));
    let projected:Vec<_>=starts.iter().map(|s|before.line_seg_text_start_of(*s)).collect();
    if legacy {assert!(starts.iter().zip(&projected).any(|(raw,paragraph)|raw!=paragraph));}
    else {assert_eq!(starts,projected);}
    let text_state=owner_text_state(before);let index=owner_picture_index(before);
    core.set_picture_properties_native(0,0,index,r#"{"treatAsChar":true}"#).expect("public HWPX axis TAC");
    let after=&core.document().sections[0].paragraphs[0];assert_recomputed_picture_partition(after);
    assert!(after.line_segs.iter().all(|row|after.line_seg_text_start_of(row.text_start)==row.text_start));
    assert_eq!(owner_text_state(after),text_state);
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("source-axis save")).expect("source-axis readback");
    assert_eq!(saved.sections[0].paragraphs[0].text,text_state.0);
    assert!(saved.sections[0].paragraphs[0].line_segs.is_empty(),"fresh computed rows cannot masquerade as either imported source axis");
    assert!(core.render_page_svg_native(0).expect("source-axis render").contains("<image"));
}

#[test]
fn public_legacy_hwpx_tac_recomputes_nonzero_source_axis_without_reusing_it() {
    assert_public_hwpx_tac_recomputes_source_axis(b"1",true);
}

#[test]
fn public_paragraph_utf16_hwpx_tac_recomputes_zero_shift_source_axis() {
    assert_public_hwpx_tac_recomputes_source_axis(b"2:paragraph-utf16",false);
}

fn owner_hf_address(doc: &Document,is_header:bool)->(usize,usize,usize,usize) {
    for (pi,p) in doc.sections[0].paragraphs.iter().enumerate() {
        for (ci,c) in p.controls.iter().enumerate() {
            let paragraphs=match c {
                Control::Header(h) if is_header=>&h.paragraphs,
                Control::Footer(f) if !is_header=>&f.paragraphs,
                _=>continue,
            };
            for (inner,p) in paragraphs.iter().enumerate() {
                if p.controls.iter().any(|c|matches!(c,Control::Picture(_))){return (pi,ci,inner,owner_picture_index(p));}
            }
        }
    }
    panic!("actual owned header/footer picture address");
}

fn owner_hf_paragraph(doc:&Document,address:(usize,usize,usize,usize))->&Paragraph {
    let (pi,ci,inner,_)=address;
    match &doc.sections[0].paragraphs[pi].controls[ci] {
        Control::Header(h)=>&h.paragraphs[inner],
        Control::Footer(f)=>&f.paragraphs[inner],
        _=>panic!("actual owned header/footer"),
    }
}

#[test]
fn public_imported_tac_header_footer_text_reverse_publishes_fresh_partition() {
    for is_header in [true,false] {
        let mut author=owner_picture_core();author.create_header_footer_native(0,is_header,0).expect("public header/footer");
        author.insert_text_in_header_footer_native(0,is_header,0,0,0,"OWNED-HF-TEXT").expect("public HF text");
        let body_index=owner_picture_index(&author.document().sections[0].paragraphs[0]);
        let picture=author.document().sections[0].paragraphs[0].controls[body_index].clone();
        // Explicit authored adversarial model input, then real serialize/import.
        // Runtime behavior is exercised solely through the public HF setter.
        let doc=author.document_mut();doc.sections[0].raw_stream=None;
        let paragraphs=doc.sections[0].paragraphs.iter_mut().flat_map(|p|p.controls.iter_mut()).find_map(|c|match c {
            Control::Header(h) if is_header=>Some(&mut h.paragraphs),
            Control::Footer(f) if !is_header=>Some(&mut f.paragraphs),
            _=>None,
        }).expect("owned HF model");
        let p=&mut paragraphs[0];p.controls.push(picture);p.ctrl_data_records.push(None);p.char_count+=8;
        let (pi,ci,inner,picture)=owner_hf_address(author.document(),is_header);
        author.set_header_footer_picture_properties_native(0,pi,ci,inner,picture,r#"{"treatAsChar":true}"#).expect("public authored HF TAC");
        let p=match &mut author.document_mut().sections[0].paragraphs[pi].controls[ci] {
            Control::Header(h)=>&mut h.paragraphs[inner],
            Control::Footer(f)=>&mut f.paragraphs[inner],
            _=>panic!("actual authored HF paragraph"),
        };
        let mut row=p.line_segs[0].clone();row.vertical_pos=5555;row.line_height=5669;row.text_height=5669;row.baseline_distance=4819;row.tag=0x80060000;p.line_segs=vec![row];p.source_line_seg_vertical_pos=None;
        let input=external_stored_hwp(author.export_hwp_native().expect("actual stored HF input"));
        let mut core=DocumentCore::from_bytes(&input).expect("public stored HF import");
        let address=owner_hf_address(core.document(),is_header);let before=owner_hf_paragraph(core.document(),address);
        assert!(before.source_line_seg_vertical_pos.is_some());assert!(before.text.contains("OWNED-HF-TEXT"));
        let text=before.text.clone();let (pi,ci,inner,picture)=address;
        core.set_header_footer_picture_properties_native(0,pi,ci,inner,picture,r#"{"treatAsChar":false}"#).expect("public imported HF TAC reverse");
        let after=owner_hf_paragraph(core.document(),address);
        assert_recomputed_picture_partition(after);assert_eq!(after.text,text);
        let props:serde_json::Value=serde_json::from_str(&core.get_header_footer_picture_properties_native(0,pi,ci,inner,picture).expect("public HF property readback")).expect("public HF JSON");
        assert_eq!(props["treatAsChar"],false);
        let saved=rhwp::parse_document(&core.export_hwpx_native().expect("public HF save")).expect("public HF saved readback");
        let saved_p=owner_hf_paragraph(&saved,owner_hf_address(&saved,is_header));
        assert!(saved_p.line_segs.is_empty());assert_eq!(saved_p.text,text);
        // Remove the independent body picture only after the TAC/save assertions.
        // The remaining rendered image must belong to the owned header/footer.
        let body_picture=owner_picture_index(&core.document().sections[0].paragraphs[0]);
        core.delete_control_native(0,0,body_picture).expect("public body picture deletion");
        assert!(!core.document().sections[0].paragraphs.iter().any(|p|p.controls.iter().any(|c|matches!(c,Control::Picture(_)))));
        let (pi,ci,inner,picture)=owner_hf_address(core.document(),is_header);
        assert_eq!(owner_hf_paragraph(core.document(),(pi,ci,inner,picture)).text,text);
        let props:serde_json::Value=serde_json::from_str(&core.get_header_footer_picture_properties_native(0,pi,ci,inner,picture).expect("remaining owned HF readback")).expect("owned HF JSON");
        assert_eq!(props["treatAsChar"],false);
        let mut hf_images=0;
        for page in 0..core.page_count(){hf_images+=core.render_page_svg_native(page).expect("HF-only owner render").matches("<image").count();}
        assert_eq!(hf_images,1,"the owned header/footer picture itself remains visible");
    }
}

// Additive Source5 admission tests. Original Native10 above stays byte-identical.
fn owner_endnote_address(doc:&Document)->(usize,usize,usize,usize,usize) {
    let mut virtual_para=doc.sections[0].paragraphs.len();
    for (pi,p) in doc.sections[0].paragraphs.iter().enumerate() {
        for (ci,control) in p.controls.iter().enumerate() {
            if let Control::Endnote(note)=control {
                for (inner,p) in note.paragraphs.iter().enumerate() {
                    if p.controls.iter().any(|c|matches!(c,Control::Picture(_))) {
                        return (pi,ci,inner,virtual_para,owner_picture_index(p));
                    }
                    virtual_para+=1;
                }
            }
        }
    }
    panic!("actual owned Endnote picture address");
}

fn owner_endnote_paragraph(doc:&Document,address:(usize,usize,usize,usize,usize))->&Paragraph {
    let (pi,ci,inner,_,_)=address;
    match &doc.sections[0].paragraphs[pi].controls[ci] {
        Control::Endnote(note)=>&note.paragraphs[inner],
        _=>panic!("actual owned Endnote"),
    }
}

fn owner_endnote_input(initial_tac:bool)->Vec<u8> {
    let mut author=owner_picture_core();
    let body_picture=owner_picture_index(&author.document().sections[0].paragraphs[0]);
    if initial_tac {
        author.set_picture_properties_native(0,0,body_picture,r#"{"treatAsChar":true}"#).expect("public authored inline picture");
    }
    let picture=author.document().sections[0].paragraphs[0].controls[body_picture].clone();
    let created:serde_json::Value=serde_json::from_str(&author.insert_endnote_native(0,0,0).expect("public Endnote insertion")).expect("public Endnote address");
    let pi=created["paraIdx"].as_u64().expect("actual note parent") as usize;
    let ci=created["controlIdx"].as_u64().expect("actual note control") as usize;
    author.insert_text_in_footnote_native(0,pi,ci,0,0,"ENDNOTE-OWNED-TEXT").expect("public Endnote text insertion");
    let doc=author.document_mut();doc.sections[0].raw_stream=None;
    let p=match &mut doc.sections[0].paragraphs[pi].controls[ci] {
        Control::Endnote(note)=>&mut note.paragraphs[0],
        _=>panic!("actual authored Endnote"),
    };
    // Explicit owned imported-data adversary; not a product fixture override.
    p.controls.push(picture);p.ctrl_data_records.push(None);p.char_count+=8;
    let mut row=p.line_segs[0].clone();row.vertical_pos=3333;
    row.line_height=if initial_tac{5669}else{1000};row.text_height=row.line_height;
    row.baseline_distance=if initial_tac{4819}else{850};row.tag=0x80060000;
    p.line_segs=vec![row];p.source_line_seg_vertical_pos=None;
    external_stored_hwp(author.export_hwp_native().expect("actual stored Endnote source"))
}

#[test]
fn public_endnote_picture_tac_both_directions_skip_body_band_and_save() {
    for initial_tac in [false,true] {
        let mut core=DocumentCore::from_bytes(&owner_endnote_input(initial_tac)).expect("public stored Endnote import");
        let address=owner_endnote_address(core.document());let (pi,ci,_,virtual_para,picture)=address;
        let info:serde_json::Value=serde_json::from_str(&core.get_note_edit_info_native(0,pi,ci).expect("public note edit address")).expect("public note JSON");
        assert_eq!(info["kind"],"endnote");assert_eq!(info["virtualParaIndex"].as_u64(),Some(virtual_para as u64));
        assert!(virtual_para>=core.document().sections[0].paragraphs.len());
        let before:serde_json::Value=serde_json::from_str(&core.get_picture_properties_native(0,virtual_para,picture).expect("public virtual picture getter")).expect("public picture JSON");
        assert_eq!(before["treatAsChar"],initial_tac);
        let text=owner_endnote_paragraph(core.document(),address).text.clone();
        assert!(text.contains("ENDNOTE-OWNED-TEXT"));
        let body_rows:Vec<_>=core.document().sections[0].paragraphs.iter().map(tuples).collect();
        let body_states:Vec<_>=core.document().sections[0].paragraphs.iter().map(owner_text_state).collect();
        let result:serde_json::Value=serde_json::from_str(&core.set_picture_properties_native(0,virtual_para,picture,if initial_tac{r#"{"treatAsChar":false}"#}else{r#"{"treatAsChar":true}"#}).expect("supported public Endnote TAC must return without body-index panic")).expect("actual TAC outcome");
        assert_eq!(result["ok"],true);
        let after:serde_json::Value=serde_json::from_str(&core.get_picture_properties_native(0,virtual_para,picture).expect("public virtual picture readback")).expect("public picture JSON");
        assert_eq!(after["treatAsChar"],!initial_tac);
        assert_eq!(core.document().sections[0].paragraphs.iter().map(tuples).collect::<Vec<_>>(),body_rows,"virtual edit must not stage or replace real body rows");
        assert_eq!(core.document().sections[0].paragraphs.iter().map(owner_text_state).collect::<Vec<_>>(),body_states);
        let edited=owner_endnote_paragraph(core.document(),address);assert!(edited.source_line_seg_vertical_pos.is_none());assert_eq!(edited.text,text);
        let output=core.export_hwpx_native().expect("public Endnote save");let saved=rhwp::parse_document(&output).expect("actual saved Endnote readback");
        let saved_address=owner_endnote_address(&saved);let saved_note=owner_endnote_paragraph(&saved,saved_address);
        assert_eq!(saved_note.text,text);assert!(saved_note.line_segs.is_empty(),"runtime-only bit31 rows cannot recover their old source owner");
        let reloaded=DocumentCore::from_bytes(&output).expect("public saved Endnote reopen");let (_,_,_,virtual_para,picture)=owner_endnote_address(reloaded.document());
        let props:serde_json::Value=serde_json::from_str(&reloaded.get_picture_properties_native(0,virtual_para,picture).expect("saved virtual picture getter")).expect("saved picture JSON");assert_eq!(props["treatAsChar"],!initial_tac);
        let mut images=0;for page in 0..core.page_count(){images+=core.render_page_svg_native(page).expect("actual Endnote/body render").matches("<image").count();}
        assert_eq!(images,2,"the unchanged body picture and edited Endnote picture remain visible");
    }
}

#[test]
fn public_invalid_picture_addresses_reject_without_live_document_mutation() {
    let mut core=DocumentCore::from_bytes(&owner_endnote_input(false)).expect("public owned invalid-address source");
    let (_,_,_,virtual_para,picture)=owner_endnote_address(core.document());
    let before=core.export_hwpx_native().expect("owned before invalid call");
    for (section,para,control) in [(usize::MAX,0,0),(0,usize::MAX,picture),(0,virtual_para+1,picture),(0,virtual_para,usize::MAX)] {
        assert!(core.get_picture_properties_native(section,para,control).is_err());
        assert!(core.set_picture_properties_native(section,para,control,r#"{"treatAsChar":true}"#).is_err(),"unsupported address must not invoke a live edit");
        assert_eq!(core.export_hwpx_native().expect("actual unchanged invalid-call export"),before);
        let props:serde_json::Value=serde_json::from_str(&core.get_picture_properties_native(0,virtual_para,picture).expect("unchanged supported virtual getter")).expect("actual getter JSON");assert_eq!(props["treatAsChar"],false);
    }
}


fn persistence_owned_hwpx_input() -> Vec<u8> {
    let stored=rhwp::parse_document(&authored()).expect("owned stored field document");
    rhwp::serializer::serialize_hwpx(&stored).expect("owned actual HWPX persistence input")
}

fn persistence_causal_marker_hwpx_input() -> Vec<u8> {
    let bytes=DocumentCore::from_bytes(&authored()).expect("public causal HWP input").export_hwpx_native().expect("public causal HWPX export");
    let stored=rhwp::parse_document(&bytes).expect("actual causal marker HWPX");
    assert_eq!(stored.hwpx_aux_entry(rhwp::model::document::HWP5_ORIGIN_HWPX_MARKER_PATH),Some(b"2:paragraph-utf16".as_slice()),"same actual Source112 generator/export marker route");
    bytes
}

fn persistence_assert_raw_row_diffs(a:&Document,b:&Document,owners:&[(usize,usize,&str)]) {
    use rhwp::serializer::hwpx::roundtrip::IrDifference;
    let raw=diff_documents(a,b);
    assert_eq!(raw.differences.len(),owners.len(),"exact number of edited runtime partitions");
    let mut actual_owners=std::collections::BTreeSet::new();
    for difference in &raw.differences {
        match difference {
            IrDifference::ParagraphLinesegs{section,paragraph,path,detail}=>{
                assert_eq!(detail,"count: expected=1 actual=0","only each identified runtime row is omitted");
                assert!(actual_owners.insert((*section,*paragraph,path.as_str())),"no duplicate owner cause");
            },
            _=>panic!("unexpected non-row persistence difference"),
        }
    }
    assert_eq!(actual_owners,owners.iter().copied().collect(),"every raw omission belongs to the exact edited owner");
}

#[test]
fn public_three_field_hwpx_save_has_exact_raw_cause_and_strict_persistence_identity() {
    let mut core=DocumentCore::from_bytes(&persistence_causal_marker_hwpx_input()).expect("public owned HWPX import");
    for(name,index,value)in[("CUSTOMER",0,"고객-한글-Ω"),("ITEM",0,"FIRST"),("ITEM",1,"SECOND")] {
        core.set_field_value_by_name_at(name,index,value).expect("actual public field edit");
    }
    let live_before=format!("{:?}",core.document());
    let bytes=core.export_hwpx_native().expect("actual edited HWPX save");
    let actual=DocumentCore::from_bytes(&bytes).expect("public saved HWPX readback");
    persistence_assert_raw_row_diffs(core.document(),actual.document(),&[(0,2,""),(0,3,""),(0,4,"/ctrl[0]tbl.cell[3].p[0]")]);
    let expected=rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(core.document());
    assert!(diff_documents(&expected,&rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(actual.document())).is_empty(),"unchanged strict comparator checks the independent expected persistence model");
    assert_eq!(format!("{:?}",core.document()),live_before,"save verification cannot mutate the open live document or source axes");
    assert_eq!(core.export_hwpx_native().expect("repeat save"),bytes);
}

#[test]
fn public_field_and_ordinary_cell_hwpx_save_have_exact_two_owner_causes() {
    let mut core=DocumentCore::from_bytes(&persistence_causal_marker_hwpx_input()).expect("public owned HWPX import");
    let siblings:Vec<_>=[1,2].iter().map(|&i|{let p=fields(core.document())[i];(tuples(p),owner_text_state(p))}).collect();
    core.delete_text_in_cell_native(0,4,0,0,0,0,"CELL-R0-C0".chars().count()).expect("public session cell clear");
    core.insert_text_in_cell_native(0,4,0,0,0,0,"SESSION-CELL").expect("public session cell text with unchanged style");
    core.set_field_value_by_name_at("CUSTOMER",0,"SESSION-FIELD").expect("public live session field edit");
    let before=format!("{:?}",core.document());let bytes=core.export_hwpx_native().expect("session snapshot save");
    let actual=DocumentCore::from_bytes(&bytes).expect("saved session readback");
    persistence_assert_raw_row_diffs(core.document(),actual.document(),&[(0,2,""),(0,4,"/ctrl[0]tbl.cell[0].p[0]")]);
    let expected=rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(core.document());
    assert!(diff_documents(&expected,&rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(actual.document())).is_empty());
    for i in [1,2] {assert_eq!(tuples(fields(core.document())[i]),tuples(fields(&expected)[i]),"untouched imported positive sibling preserves all nine fields");}
    for (saved,(rows,state)) in [1,2].iter().map(|&i|fields(actual.document())[i]).zip(&siblings) {
        assert_eq!(tuples(saved),*rows,"independent saved sibling preserves all nine stored fields");
        assert_eq!(owner_text_state(saved),*state,"independent saved sibling text/control/format metadata is unchanged");
    }
    assert_eq!(format!("{:?}",core.document()),before,"live session remains open and byte-for-byte unchanged");
}

#[test]
fn public_single_field_only_hwpx_save_has_one_exact_owner_cause() {
    let mut core=DocumentCore::from_bytes(&persistence_causal_marker_hwpx_input()).expect("public single-field HWPX import");
    core.set_field_value_by_name_at("CUSTOMER",0,"SESSION-FIELD").expect("one public field edit");
    let live=format!("{:?}",core.document());let bytes=core.export_hwpx_native().expect("single-field save");
    let actual=DocumentCore::from_bytes(&bytes).expect("single-field readback");
    persistence_assert_raw_row_diffs(core.document(),actual.document(),&[(0,2,"")]);
    assert!(persistence_canonical_diff(core.document(),actual.document()).is_empty());
    assert_eq!(format!("{:?}",core.document()),live);
}


fn persistence_canonical_diff(a:&Document,b:&Document)->rhwp::serializer::hwpx::roundtrip::IrDiff {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document;
    diff_documents(&hwpx_persistence_document(a),&hwpx_persistence_document(b))
}

#[test]
fn persistence_rejects_same_length_body_cell_text_and_field_identity_corruption() {
    use rhwp::serializer::hwpx::roundtrip::IrDifference;
    let expected=rhwp::parse_document(&persistence_owned_hwpx_input()).expect("owned actual persisted HWPX");
    for owner in [0,1] {
        let mut corrupt=expected.clone();
        let paragraph=if owner==0 {&mut corrupt.sections[0].paragraphs[2]} else {
            match &mut corrupt.sections[0].paragraphs[4].controls[0] {Control::Table(t)=>&mut t.cells[3].paragraphs[0],_=>panic!("owned table")}
        };
        let len=paragraph.text.chars().count();let (value,changed)=if owner==0 {("C-INIT","X-INIT")} else {("I-CELL","X-CELL")};
        assert_eq!(paragraph.text.matches(value).count(),1,"the actual owned field value is selected");
        paragraph.text=paragraph.text.replacen(value,changed,1);assert_eq!(paragraph.text.chars().count(),len);
        let tampered_text=paragraph.text.clone();
        let bytes=rhwp::serializer::serialize_hwpx(&corrupt).expect("actual same-length field-value output corruption");
        let actual=rhwp::parse_document(&bytes).expect("independent corrupted field-value readback");
        let diff=persistence_canonical_diff(&expected,&actual);
        assert!(diff.differences.iter().any(|d|matches!(d,IrDifference::ParagraphText{..})),"same-length text/value corruption must fail for its actual semantic reason");
        let diagnostic=diff.differences.iter().map(ToString::to_string).collect::<Vec<_>>().join("\n");
        assert!(diagnostic.contains("text"));assert!(!diagnostic.contains(&tampered_text),"diagnostics do not expose document text");
    }
    for is_endnote in [false,true] {
        let mut author=DocumentCore::new_empty();author.create_blank_document_native().expect("owned note document");
        let address=if is_endnote {author.insert_endnote_native(0,0,0)} else {author.insert_footnote_native(0,0,0)}.expect("public owned note insertion");
        let address:serde_json::Value=serde_json::from_str(&address).expect("actual public note address");
        let parent=address["paraIdx"].as_u64().expect("actual note parent") as usize;let control=address["controlIdx"].as_u64().expect("actual note control") as usize;
        author.insert_text_in_footnote_native(0,parent,control,0,0,"OWNED-NOTE-TEXT").expect("public Footnote/Endnote text");
        let bytes=author.export_hwpx_native().expect("actual owned note save");let expected=rhwp::parse_document(&bytes).expect("independent stored note input");
        let mut corrupt=expected.clone();let paragraph=corrupt.sections[0].paragraphs.iter_mut().flat_map(|p|p.controls.iter_mut()).find_map(|c|match c {
            Control::Footnote(n) if !is_endnote=>Some(&mut n.paragraphs[0]),Control::Endnote(n) if is_endnote=>Some(&mut n.paragraphs[0]),_=>None,
        }).expect("actual stored owned note");
        let len=paragraph.text.chars().count();assert_eq!(paragraph.text.matches("OWNED-NOTE-TEXT").count(),1);
        paragraph.text=paragraph.text.replacen("OWNED-NOTE-TEXT","OTHER-NOTE-TEXT",1);assert_eq!(paragraph.text.chars().count(),len);
        let bytes=rhwp::serializer::serialize_hwpx(&corrupt).expect("actual same-length note output corruption");let actual=rhwp::parse_document(&bytes).expect("independent corrupted note readback");
        assert!(persistence_canonical_diff(&expected,&actual).differences.iter().any(|d|matches!(d,IrDifference::ParagraphText{path,..} if path.contains(if is_endnote{"en.p["}else{"fn.p["}))),"same-length owned note text must fail for its actual semantic reason and owning note path");
    }
    for scalar in [0,1,2] {
        let mut corrupt=expected.clone();let field=corrupt.sections[0].paragraphs[2].controls.iter_mut().find_map(|c|if let Control::Field(f)=c{Some(f)}else{None}).expect("owned field");
        match scalar {0=>field.ctrl_data_name=Some("CUST0MER".into()),1=>{field.command.push('X');},_=>field.field_type=rhwp::model::control::FieldType::Date}
        assert!(persistence_canonical_diff(&expected,&corrupt).differences.iter().any(|d|matches!(d,IrDifference::FieldIdentity{..})),"persistent field identity corruption remains strict");
    }
}

#[test]
fn persistence_runtime_owner_policy_preserves_imported_rows_axes_and_suffix_boundary() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document;
    let original=rhwp::parse_document(&persistence_owned_hwpx_input()).expect("owned stored positive source");
    for case in 0..7 {
        let mut live=original.clone();let p=&mut live.sections[0].paragraphs[2];
        assert_eq!(p.line_segs.len(),1);let original_row=p.line_segs[0].clone();p.hwpx_axis_shift=16;
        match case {
            0=>{},
            1=>{
                p.source_line_seg_vertical_pos=None;
                for row in &mut p.line_segs {row.tag|=LineSeg::TAG_IMPLEMENTATION_PROPERTY;}
                assert!(p.line_segs.iter().all(|row|row.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY!=0),"case 1 fixture requires runtime-tagged rows before the empty-partition oracle");
            },
            2=>{
                p.source_line_seg_vertical_pos=None;
                for row in &mut p.line_segs {row.tag|=LineSeg::TAG_IMPLEMENTATION_PROPERTY;}
                let mut ordinary=original_row.clone();ordinary.tag&=!LineSeg::TAG_IMPLEMENTATION_PROPERTY;p.line_segs.push(ordinary);
                assert_eq!(p.line_segs.iter().map(|row|u32::from(row.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY!=0)).collect::<Vec<_>>(),vec![1,0],"case 2 fixture requires runtime then ordinary classifications before the mixed-partition oracle");
            },
            3=>p.source_line_seg_vertical_pos=Some(Vec::new()),
            4=>{p.line_segs[0].line_height=0;p.line_segs[0].text_height=0;p.line_segs[0].tag|=LineSeg::TAG_EMPTY_SEGMENT;},
            5=>p.invalidate_layout_inputs(),
            _=>{let mut fill=original_row.clone();fill.vertical_pos+=999;p.line_segs.push(fill);p.layout_only_fill_lines=1;},
        }
        let axis=p.hwpx_axis_shift;let dirty=p.stored_text_partition_is_dirty();let before=format!("{live:?}");
        let expected=hwpx_persistence_document(&live);let actual=&expected.sections[0].paragraphs[2];
        assert_eq!(actual.hwpx_axis_shift,axis);assert_eq!(actual.stored_text_partition_is_dirty(),dirty);
        assert_eq!(actual.text,live.sections[0].paragraphs[2].text);assert_eq!(format!("{live:?}"),before);
        if [1,3,4,5].contains(&case){assert!(actual.line_segs.is_empty());}
        else if case==2 {assert_eq!(actual.line_segs.len(),2,"mixed owned-axis rows cannot be blanket-dropped");}
        else {assert_eq!(actual.line_segs.len(),1);assert_eq!(tuples(actual),tuples(&original.sections[0].paragraphs[2]),"positive source row and serializable-prefix ownership retain all nine fields");}
    }
}

#[test]
fn persistence_none_ordinary_rows_keep_all_nine_fields() {
    let mut live=rhwp::parse_document(&persistence_owned_hwpx_input()).expect("owned ordinary stored HWPX");
    let p=&mut live.sections[0].paragraphs[2];
    assert_eq!(p.line_segs.len(),1,"the ordinary None control uses one actual stored row");
    assert!(p.line_segs.iter().all(|row|row.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY==0),"the legacy control remains ordinary rather than runtime-tagged");
    p.source_line_seg_vertical_pos=None;
    let original=tuples(p);
    let expected=rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(&live);
    assert_eq!(tuples(&expected.sections[0].paragraphs[2]),original,"None alone cannot discard an ordinary stored partition or change any of its nine fields");
    let bytes=rhwp::serializer::serialize_hwpx(&live).expect("ordinary None actual HWPX save");
    let reopened=rhwp::parse_document(&bytes).expect("ordinary None independent HWPX reopen");
    assert_eq!(tuples(&reopened.sections[0].paragraphs[2]),original,"ordinary None save/reopen preserves all nine stored fields");
    assert_eq!(tuples(&live.sections[0].paragraphs[2]),original,"the independent persistence expectation cannot mutate the live row");
}

#[test]
fn genuine_and_marker_hwpx_field_save_compare_independent_persistent_models() {
    use rhwp::model::document::HWP5_ORIGIN_HWPX_MARKER_PATH;
    let plain=persistence_owned_hwpx_input();let marker=DocumentCore::from_bytes(&authored()).expect("public HWP").export_hwpx_native().expect("public HWPX marker route");
    assert!(rhwp::parse_document(&plain).expect("native HWPX").hwpx_aux_entry(HWP5_ORIGIN_HWPX_MARKER_PATH).is_none());
    assert!(rhwp::parse_document(&marker).expect("marker HWPX").hwpx_aux_entry(HWP5_ORIGIN_HWPX_MARKER_PATH).is_some());
    for input in [plain,marker] {
        let mut live=DocumentCore::from_bytes(&input).expect("both legitimate import branches");
        live.set_field_value_by_name_at("CUSTOMER",0,"NATIVE-HWPX-VALUE").expect("public field edit");
        let before=format!("{:?}",live.document());let saved=live.export_hwpx_native().expect("actual HWPX output");let reload=DocumentCore::from_bytes(&saved).expect("actual output readback");
        assert!(persistence_canonical_diff(live.document(),reload.document()).is_empty(),"post-import runtime materialization is independently projected, never treated as stored source ownership");
        assert_eq!(format!("{:?}",live.document()),before);
    }
}


fn persistence_rewrite_hwpx_part(bytes:&[u8],part:&str,change:impl FnOnce(String)->String)->Vec<u8> {
    use std::io::{Cursor,Read};
    let mut archive=zip::ZipArchive::new(Cursor::new(bytes)).expect("actual owned output ZIP");
    let mut writer=rhwp::serializer::hwpx::writer::HwpxZipWriter::new();let mut change=Some(change);let mut changed=0;
    for i in 0..archive.len() {
        let mut file=archive.by_index(i).expect("original output ZIP member");let name=file.name().expect("valid owned output member name").into_owned();let mut raw=Vec::new();file.read_to_end(&mut raw).expect("CRC checked output bytes");
        if name==part {raw=change.take().expect("single selected output member")(String::from_utf8(raw).expect("owned XML")).into_bytes();changed+=1;}
        if name=="mimetype" {writer.write_stored(&name,&raw).expect("required stored mimetype");}else{writer.write_deflated(&name,&raw).expect("owned package member");}
    }
    assert_eq!(changed,1);writer.finish().expect("actual corrupted output package")
}

#[test]
fn actual_stored_positive_bit31_injection_cannot_be_hidden_by_actual_projection() {
    let mut live=DocumentCore::from_bytes(&persistence_owned_hwpx_input()).expect("owned HWPX");live.set_field_value_by_name_at("CUSTOMER",0,"SESSION-FIELD").expect("public edit");
    let saved=live.export_hwpx_native().expect("actual output");let expected=rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(live.document());assert!(fields(&expected)[0].line_segs.is_empty());
    let corrupt=persistence_rewrite_hwpx_part(&saved,"Contents/section0.xml",|mut xml| {
        let start=xml.match_indices("<hp:p ").nth(2).expect("actual field owner").0;let end=start+xml[start..].find("</hp:p>").expect("owned body field paragraph");
        assert!(!xml[start..end].contains("<hp:linesegarray"));
        xml.insert_str(end,r#"<hp:linesegarray><hp:lineseg textpos="0" vertpos="7777" vertsize="1000" textheight="1000" baseline="850" spacing="600" horzpos="0" horzsize="42520" flags="2147876864"/></hp:linesegarray>"#);xml
    });
    let actual=DocumentCore::from_bytes(&corrupt).expect("actual serialized tamper is parsed independently");let p=fields(actual.document())[0];
    assert_eq!(p.source_line_seg_vertical_pos,Some(vec![7777]),"only the actual parser, not verification, grants stored source ownership");
    let canonical=rhwp::serializer::hwpx::roundtrip::hwpx_persistence_document(actual.document());assert_eq!(fields(&canonical)[0].line_segs.len(),1,"sized positive imported bit31 row remains actual persisted data");
    assert!(!diff_documents(&expected,&canonical).is_empty(),"wrongly persisted runtime row cannot be normalized away");
}

#[test]
fn actual_hwpx_text_style_and_table_control_corruption_are_rejected() {
    let live=DocumentCore::from_bytes(&persistence_owned_hwpx_input()).expect("public saved input");let saved=live.export_hwpx_native().expect("actual package");
    let corrupt=persistence_rewrite_hwpx_part(&saved,"Contents/section0.xml",|xml| {assert!(xml.contains("BODY-ROOT"));xml.replacen("BODY-ROOT","BODY-FAIL",1)});
    let actual=DocumentCore::from_bytes(&corrupt).expect("same-length XML text corruption");assert!(!persistence_canonical_diff(live.document(),actual.document()).is_empty());
    for mutation in [0,1] {
        let mut doc=rhwp::parse_document(&saved).expect("actual independent persisted model");
        let corrupt=if mutation==0 {
            persistence_rewrite_hwpx_part(&saved,"Contents/header.xml",|xml| {
                let start=xml.find("<hh:charPr ").expect("actual persisted character style declaration");let end=start+xml[start..].find('>').expect("actual charPr closure");
                let prefix="height=\"";let at=start+xml[start..end].find(prefix).expect("actual persisted font height")+prefix.len();let stop=at+xml[at..end].find('"').expect("height closure");
                let original=xml[at..stop].parse::<i32>().expect("exact signed font height");let mut changed=xml;changed.replace_range(at..stop,&(original+100).to_string());changed
            })
        } else {doc.sections[0].paragraphs[4].controls.clear();rhwp::serializer::serialize_hwpx(&doc).expect("independent corrupted table output")};let actual=DocumentCore::from_bytes(&corrupt).expect("actual mutated output import");
        let diff=persistence_canonical_diff(live.document(),actual.document());
        if mutation==0 {assert_eq!(live.document().doc_info.char_shapes.len(),actual.document().doc_info.char_shapes.len());assert_eq!(live.document().sections[0].paragraphs[2].char_shapes[0].char_shape_id,actual.document().sections[0].paragraphs[2].char_shapes[0].char_shape_id);assert!(diff.differences.iter().any(|d|matches!(d,rhwp::serializer::hwpx::roundtrip::IrDifference::CharShapeProperty{property:"base_size",..})),"same-count/same-ID persisted font height corruption remains strict");}
        else {assert!(!diff.is_empty(),"persisted table-control loss remains strict");}
    }
}

fn persistence_hf_paragraph_mut(doc:&mut Document,is_header:bool)->&mut Paragraph {
    for p in &mut doc.sections[0].paragraphs {for c in &mut p.controls {
        match c {Control::Header(h) if is_header=>return &mut h.paragraphs[0],Control::Footer(h) if !is_header=>return &mut h.paragraphs[0],_=>{}}
    }}panic!("owned header/footer paragraph");
}

#[test]
fn public_header_footer_persistence_rejects_scalar_row_and_paragraph_count_corruption() {
    use rhwp::serializer::hwpx::roundtrip::IrDifference;
    for is_header in [true,false] {
        let mut author=owner_picture_core();author.create_header_footer_native(0,is_header,0).expect("public HF");author.insert_text_in_header_footer_native(0,is_header,0,0,0,"OWNED-HF-TEXT").expect("public HF text");
        let row=LineSeg{text_start:0,vertical_pos:4444,line_height:1000,text_height:1000,baseline_distance:850,line_spacing:600,column_start:0,segment_width:42520,tag:0x60000};
        let p=persistence_hf_paragraph_mut(author.document_mut(),is_header);p.line_segs=vec![row];p.source_line_seg_vertical_pos=None;
        let saved=author.export_hwpx_native().expect("actual authored HF persisted row");let live=DocumentCore::from_bytes(&saved).expect("actual HF imported bytes");let again=live.export_hwpx_native().expect("healthy HF snapshot");let healthy=DocumentCore::from_bytes(&again).expect("healthy HF reload");assert!(persistence_canonical_diff(live.document(),healthy.document()).is_empty());
        for mutation in [0,1] {
            let corrupt=persistence_rewrite_hwpx_part(&again,"Contents/section0.xml",|xml| {
                if mutation==0 {assert!(xml.contains("OWNED-HF-TEXT"));xml.replacen("OWNED-HF-TEXT","OWNED-HF-FAIL",1)}
                else {
                    let open=if is_header{"<hp:header"}else{"<hp:footer"};let close=if is_header{"</hp:header>"}else{"</hp:footer>"};
                    let start=xml.find(open).expect("owned HF XML scope");let end=start+xml[start..].find(close).expect("owned HF XML closure");
                    let prefix="vertpos=\"";let at=start+xml[start..end].find(prefix).expect("actual persisted HF row coordinate")+prefix.len();let stop=at+xml[at..end].find('"').expect("actual HF coordinate closure");
                    let original=xml[at..stop].parse::<i32>().expect("actual serialized coordinate");let mut changed=xml;changed.replace_range(at..stop,&(original+1).to_string());changed
                }
            });
            let actual=DocumentCore::from_bytes(&corrupt).expect("actual HF scalar/row tamper");let diff=persistence_canonical_diff(live.document(),actual.document());
            if mutation==0 {assert!(diff.differences.iter().any(|d|matches!(d,IrDifference::ParagraphText{path,..} if path.contains(if is_header{"hdr"}else{"ftr"}))));}
            else {assert!(diff.differences.iter().any(|d|matches!(d,IrDifference::ParagraphLinesegs{path,..} if path.contains(if is_header{"hdr"}else{"ftr"}))));}
        }
        let mut corrupt=rhwp::parse_document(&again).expect("actual HF model");
        for p in &mut corrupt.sections[0].paragraphs {for c in &mut p.controls {match c {
            Control::Header(h) if is_header=>h.paragraphs.push(h.paragraphs[0].clone()),Control::Footer(h) if !is_header=>h.paragraphs.push(h.paragraphs[0].clone()),_=>{}}}}
        let bytes=rhwp::serializer::serialize_hwpx(&corrupt).expect("actual additional HF paragraph");let actual=DocumentCore::from_bytes(&bytes).expect("HF count readback");
        assert!(persistence_canonical_diff(live.document(),actual.document()).differences.iter().any(|d|matches!(d,IrDifference::NestedParagraphCount{..})),"HF paragraph count cannot evade paired traversal");
    }
}


#[test]
fn persistence_field_identity_keeps_empty_name_and_parsed_known_alias_semantics() {
    use rhwp::serializer::hwpx::roundtrip::IrDifference;
    let original=rhwp::parse_document(&persistence_owned_hwpx_input()).expect("owned actual HWPX");let mut empty=original.clone();let mut explicit=original.clone();
    for(doc,value)in[(&mut empty,None),(&mut explicit,Some(String::new()))] {
        let field=doc.sections[0].paragraphs[2].controls.iter_mut().find_map(|c|if let Control::Field(f)=c{Some(f)}else{None}).expect("actual field");field.ctrl_data_name=value;
    }
    assert!(!diff_documents(&empty,&explicit).differences.iter().any(|d|matches!(d,IrDifference::FieldIdentity{..})),"only None and exact empty field name have the same persisted meaning");
    let saved=persistence_owned_hwpx_input();let alias=persistence_rewrite_hwpx_part(&saved,"Contents/section0.xml",|xml| {assert!(xml.contains("type=\"CLICK_HERE\""));xml.replacen("type=\"CLICK_HERE\"","type=\"CLICKHERE\"",1)});
    let a=DocumentCore::from_bytes(&saved).expect("canonical persisted kind");let b=DocumentCore::from_bytes(&alias).expect("recognized persisted spelling alias");
    assert!(!persistence_canonical_diff(a.document(),b.document()).differences.iter().any(|d|matches!(d,IrDifference::FieldIdentity{..})),"actual parser and writer already define recognized type semantics");
}


#[test]
fn persistent_font_height_preserves_positive_and_zero_values_without_normalization() {
    let original=rhwp::parse_document(&persistence_owned_hwpx_input()).expect("owned persisted font declaration");
    for size in [1200,0] {
        let mut expected=original.clone();expected.doc_info.char_shapes[0].base_size=size;
        let bytes=rhwp::serializer::serialize_hwpx(&expected).expect("actual signed integer font-height write");let actual=rhwp::parse_document(&bytes).expect("actual font-height readback");
        assert_eq!(actual.doc_info.char_shapes[0].base_size,size);
        assert!(!diff_documents(&expected,&actual).differences.iter().any(|d|matches!(d,rhwp::serializer::hwpx::roundtrip::IrDifference::CharShapeProperty{..})),"zero is not converted to a nominal font size or waived by a comparison filter");
    }
}


#[test]
fn actual_hwpx_field_editable_and_dirty_attribute_corruption_is_strict() {
    use rhwp::serializer::hwpx::roundtrip::IrDifference;
    let input=persistence_owned_hwpx_input();let live=DocumentCore::from_bytes(&input).expect("actual owned field input");let saved=live.export_hwpx_native().expect("actual field output");
    for label in ["editable","dirty"] {
        let corrupt=persistence_rewrite_hwpx_part(&saved,"Contents/section0.xml",|xml| {
            let start=xml.find("<hp:fieldBegin ").expect("actual owned field");let end=start+xml[start..].find('>').expect("field attribute boundary");let prefix=format!("{label}=\"");
            let at=start+xml[start..end].find(&prefix).expect("actual persisted getter flag")+prefix.len();let stop=at+xml[at..end].find('"').expect("boolean attribute end");
            let original=&xml[at..stop];let flipped=if original=="1" {"0"} else {assert_eq!(original,"0");"1"};let mut changed=xml;changed.replace_range(at..stop,flipped);changed
        });
        let actual=DocumentCore::from_bytes(&corrupt).expect("actual XML flag corruption");let diff=persistence_canonical_diff(live.document(),actual.document());
        assert!(diff.differences.iter().any(|d|matches!(d,IrDifference::FieldIdentity{changed,..} if changed.contains(&label))),"only the actual persistent getter flag changes; raw properties are not compared");
    }
}

// rhwp 0.9.1: independent expected-resource normalization, using real public
// create/edit/export/import APIs. This source must run in the native gate.
fn resource_owned_input(original_orphan: bool) -> (Vec<u8>, Option<u16>) {
    use rhwp::model::bin_data::{BinData, BinDataCompression, BinDataContent, BinDataStatus, BinDataType};
    let mut author=DocumentCore::new_empty();author.create_blank_document_native().expect("owned resource blank");
    for _ in 0..2 {
        author.insert_picture_native(0,0,0,&[],OWNER_PNG,11339,5669,1,1,"png","OWNED-RESOURCE-IDENTITY",Some(8504),Some(28346)).expect("public owned picture insertion");
    }
    let bytes=author.export_hwpx_native().expect("actual initial owned HWPX");
    if !original_orphan { return (bytes,None); }
    let mut document=rhwp::parse_document(&bytes).expect("parse owned original HWPX");
    let id=document.bin_data_content.iter().map(|c|c.id).max().unwrap_or(0).checked_add(1).expect("owned storage ID");
    let mut orphan_bytes=OWNER_PNG.to_vec();orphan_bytes.extend_from_slice(b"OWNED-ORPHAN");
    document.bin_data_content.push(BinDataContent{id,data:orphan_bytes.into(),extension:"png".into()});
    document.doc_info.bin_data_list.push(BinData{raw_data:None,attr:0x0101,data_type:BinDataType::Embedding,compression:BinDataCompression::Default,status:BinDataStatus::Success,abs_path:None,rel_path:None,storage_id:id,extension:Some("png".into())});
    (rhwp::serializer::serialize_hwpx(&document).expect("actual owned pre-existing orphan fixture"),Some(id))
}

fn resource_delete_first(original_orphan: bool) -> (DocumentCore, Option<u16>) {
    let (bytes,orphan)=resource_owned_input(original_orphan);
    let mut core=DocumentCore::from_bytes(&bytes).expect("public load initializes original orphan ownership");
    let index=core.document().sections[0].paragraphs[0].controls.iter().enumerate().filter_map(|(index,control)|match control {
        Control::Picture(picture)=>Some((index,picture.image_attr.bin_data_id)),_=>None,
    }).min_by_key(|(_,position)|*position).expect("actual first picture position").0;
    core.delete_picture_control_native(0,0,index).expect("public deletion leaves append-only live BinData");
    // HWPX re-import assigns sorted manifest entries a new 1-based namespace.
    // This fixture independently knows its only original orphan and surviving picture.
    let canonical_orphan=orphan.map(|source_id| {
        let document=core.document();let mut retained=std::collections::BTreeSet::from([source_id]);
        for control in &document.sections[0].paragraphs[0].controls {if let Control::Picture(p)=control{retained.insert(document.bin_data_content[usize::from(p.image_attr.bin_data_id)-1].id);}}
        u16::try_from(retained.iter().position(|id|*id==source_id).expect("known original orphan source role")+1).expect("owned small canonical namespace")
    });
    (core,canonical_orphan)
}

fn resource_saved_pair(core: &DocumentCore) -> (Document,Document) {
    use rhwp::serializer::hwpx::roundtrip::{hwpx_persistence_document,hwpx_persistence_expected_document};
    let before=format!("{:?}",core.document());
    let expected=hwpx_persistence_expected_document(core).expect("independent supported resource expectation");
    let bytes=core.export_hwpx_native().expect("actual edited HWPX serialization");
    let reloaded=DocumentCore::from_bytes(&bytes).expect("independent actual saved HWPX import");
    let actual=hwpx_persistence_document(reloaded.document());
    assert!(before==format!("{:?}",core.document()),"expectation and save preserve the live model");
    (expected,actual)
}

#[test]
fn actual_picture_delete_save_reopen_keeps_independent_resource_and_content_expectation() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let (core,_)=resource_delete_first(false);let (expected,actual)=resource_saved_pair(&core);
    assert!(diff_documents(&expected,&actual).is_empty(),"normal deletion must satisfy the original independent content oracle");
    assert!(hwpx_persistence_resources_match(&expected,&actual),"retained payload and semantic resource bindings remain exact");
}

#[test]
fn actual_original_orphan_survives_unrelated_picture_delete_and_save() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let (core,orphan)=resource_delete_first(true);let orphan=orphan.expect("owned original orphan identity");
    let (expected,actual)=resource_saved_pair(&core);
    assert!(expected.bin_data_content.iter().any(|c|c.id==orphan));assert!(actual.bin_data_content.iter().any(|c|c.id==orphan));
    let mut original_bytes=OWNER_PNG.to_vec();original_bytes.extend_from_slice(b"OWNED-ORPHAN");
    assert!(actual.bin_data_content.iter().find(|c|c.id==orphan).expect("canonical original orphan role").data.load_limited(1024).is_some_and(|bytes|bytes==original_bytes));
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
}

#[test]
fn actual_reloaded_resource_loss_mutation_and_binding_change_are_not_normalized_away() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let (core,orphan)=resource_delete_first(true);let orphan=orphan.expect("owned original orphan identity");
    let (expected,actual)=resource_saved_pair(&core);
    assert!(hwpx_persistence_resources_match(&expected,&actual));
    let referenced=actual.sections[0].paragraphs[0].controls.iter().find_map(|control|match control {Control::Picture(p)=>Some(p.image_attr.bin_data_id),_=>None}).expect("actual retained picture reference");
    let retained_id=actual.bin_data_content[usize::from(referenced)-1].id;
    for id in [retained_id,orphan] {
        let mut changed=actual.clone();let content=changed.bin_data_content.iter_mut().find(|c|c.id==id).expect("owned retained storage");
        let mut bytes=content.data.load_limited(1024).expect("bounded owned PNG or original-orphan fixture");bytes[0]^=1;content.data=bytes.into();
        assert!(!hwpx_persistence_resources_match(&expected,&changed),"same-count referenced or original-orphan payload mutation must fail");
        let mut missing=actual.clone();missing.bin_data_content.retain(|c|c.id!=id);
        assert!(!hwpx_persistence_resources_match(&expected,&missing),"missing retained or original-orphan payload must fail");
    }
    let mut rebound=actual.clone();let wrong=rebound.bin_data_content.iter().position(|c|c.id==orphan).expect("actual original orphan slot") as u16+1;
    for control in &mut rebound.sections[0].paragraphs[0].controls {if let Control::Picture(p)=control {p.image_attr.bin_data_id=wrong;}}
    assert!(!hwpx_persistence_resources_match(&expected,&rebound),"equal PNG bytes cannot hide a changed storage-owner binding");
}

// The canonical detached master-page owner and chart placeholder use actual
// rhwp types and the public mutable document API, never a model-shaped stub.
fn resource_detached_master() -> DocumentCore {
    let mut core=DocumentCore::new_empty();core.create_blank_document_native().expect("actual empty master source");
    for _ in 0..2 {core.insert_picture_native(0,0,0,&[],OWNER_PNG,11339,5669,1,1,"png","OWNED-MASTER-RESOURCE",Some(8504),Some(28346)).expect("public master fixture picture");}
    core.create_master_page_native(0,r#"{"applyTo":0}"#).expect("public master creation");
    let section=&mut core.document_mut().sections[0];
    let controls=std::mem::take(&mut section.paragraphs[0].controls);
    let (pictures,others):(Vec<_>,Vec<_>)=controls.into_iter().partition(|c|matches!(c,Control::Picture(_)));
    assert_eq!(pictures.len(),2);section.paragraphs[0].controls=others;
    section.section_def.master_pages[0].paragraphs[0].controls=pictures;
    let canonical=section.section_def.clone();
    for paragraph in &mut section.paragraphs {for control in &mut paragraph.controls{if let Control::SectionDef(def)=control{**def=canonical.clone();}}}
    // Materialize a valid owned source model after moving controls through the
    // public model API. This is fixture construction, never the expected oracle.
    let before=format!("{:?}",core.document());
    let bytes=core.export_hwpx_native().expect("actual first master fixture serialization");
    assert!(before==format!("{:?}",core.document()));
    let core=DocumentCore::from_bytes(&bytes).expect("actual master fixture source load");
    assert_eq!(core.document().bin_data_content.len(),2,"the first export must retain both fresh master-owned resources");
    assert_eq!(core.document().sections[0].section_def.master_pages[0].paragraphs[0].controls.iter().filter(|c|matches!(c,Control::Picture(_))).count(),2);
    core
}

#[test]
fn actual_detached_master_picture_save_reopen_preserves_resource_owners() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_detached_master();let(expected,actual)=resource_saved_pair(&core);
    assert_eq!(expected.bin_data_content.len(),2);assert_eq!(actual.bin_data_content.len(),2);
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
    assert!(!actual.sections[0].section_def.master_pages[0].paragraphs[0].controls.is_empty());
}

#[test]
fn actual_detached_master_same_count_resource_rebinding_is_rejected() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_detached_master();let(expected,actual)=resource_saved_pair(&core);
    assert!(hwpx_persistence_resources_match(&expected,&actual),"the negative control requires an admitted unchanged baseline");
    let mut changed=actual.clone();
    let mut positions=changed.sections[0].section_def.master_pages[0].paragraphs[0].controls.iter().filter_map(|c|match c{Control::Picture(p)=>Some(p.image_attr.bin_data_id),_=>None});
    let first=positions.next().expect("actual first master image");let second=positions.next().expect("actual second master image");assert_ne!(first,second);
    for c in &mut changed.sections[0].section_def.master_pages[0].paragraphs[0].controls {if let Control::Picture(p)=c{if p.image_attr.bin_data_id==first{p.image_attr.bin_data_id=second;break;}}}
    assert_eq!(changed.bin_data_content.len(),actual.bin_data_content.len());
    assert!(!hwpx_persistence_resources_match(&expected,&changed));
}

fn resource_chart_placeholder() -> DocumentCore {
    let mut core=DocumentCore::new_empty();core.create_blank_document_native().expect("actual chart source");
    let mut ole=rhwp::model::shape::OleShape::default();ole.chart_id_ref=Some("Chart/chart1.xml".into());ole.bin_data_id=60001;
    core.document_mut().sections[0].paragraphs[0].controls.push(Control::Shape(Box::new(rhwp::model::shape::ShapeObject::Ole(Box::new(ole)))));
    core.document_mut().bin_data_content.push(rhwp::model::bin_data::BinDataContent{id:60001,data:b"<c:chartSpace xmlns:c=\"http://schemas.openxmlformats.org/drawingml/2006/chart\"><c:chart><c:plotArea/></c:chart></c:chartSpace>".to_vec().into(),extension:"ooxml_chart".into()});
    core
}

#[test]
fn actual_native_chart_placeholder_60001_save_reopen_is_supported() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_chart_placeholder();let(expected,actual)=resource_saved_pair(&core);
    let part=actual.bin_data_content.iter().find(|c|c.id==60001&&c.extension=="ooxml_chart").expect("actual Chart part retained outside the binary manifest");
    assert!(part.data.load_limited(1024).is_some_and(|bytes|!bytes.is_empty()));
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
}

#[test]
fn actual_chart_target_and_placeholder_identity_are_not_normalized_away() {
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_chart_placeholder();let(expected,actual)=resource_saved_pair(&core);
    assert!(hwpx_persistence_resources_match(&expected,&actual),"the chart negative requires an admitted unchanged baseline");
    let part=actual.bin_data_content.iter().position(|c|c.id==60001&&c.extension=="ooxml_chart").expect("known retained Chart part");
    let mut missing=actual.clone();missing.bin_data_content.remove(part);assert!(!hwpx_persistence_resources_match(&expected,&missing));
    let mut modified=actual.clone();let mut bytes=modified.bin_data_content[part].data.load_limited(1024).expect("bounded authored Chart part");bytes[0]^=1;modified.bin_data_content[part].data=bytes.into();assert!(!hwpx_persistence_resources_match(&expected,&modified));
    for target in [false,true] {
        let mut changed=actual.clone();let mut changed_one=false;
        for c in &mut changed.sections[0].paragraphs[0].controls {if let Control::Shape(s)=c {if let rhwp::model::shape::ShapeObject::Ole(o)=s.as_mut(){if target{o.chart_id_ref=Some("Chart/chart2.xml".into());}else{o.bin_data_id=60002;}changed_one=true;}}}
        assert!(changed_one);assert!(!hwpx_persistence_resources_match(&expected,&changed));
    }
}

// Synthetic URI metadata only. No external image is loaded: input pictures have
// external_path=None and re-import uses the byte-only parser, without a directory.
fn resource_linked_source(remove_link_picture: bool, zero_link_slot: bool) -> DocumentCore {
    use rhwp::model::bin_data::{BinDataBytes,BinDataType};
    let mut core=DocumentCore::new_empty();core.create_blank_document_native().expect("owned linked source");
    for _ in 0..2 {core.insert_picture_native(0,0,0,&[],OWNER_PNG,11339,5669,1,1,"png","OWNED-LINKED-RESOURCE",Some(8504),Some(28346)).expect("actual authored embedded image");}
    let document=core.document_mut();
    let record=&mut document.doc_info.bin_data_list[0];record.data_type=BinDataType::Link;record.attr &= !0x000f;record.raw_data=None;
    record.abs_path=if zero_link_slot{None}else{Some("https://example.invalid/owned-linked.png".into())};record.rel_path=None;
    if zero_link_slot {record.storage_id=0;let data=&mut document.bin_data_content[0];data.id=0;data.data=BinDataBytes::Loaded(Vec::new());data.extension.clear();}
    else {document.bin_data_content.remove(0);}
    if remove_link_picture {
        let index=core.document().sections[0].paragraphs[0].controls.iter().position(|c|matches!(c,Control::Picture(p)if p.image_attr.bin_data_id==1)).expect("owned link control");
        core.delete_picture_control_native(0,0,index).expect("public linked-picture deletion");
    }
    core
}

fn resource_fixture_stage(function:u8,stage:u8,line:u32,values:&[u64]) {
    assert!(values.len()<=8);
    eprintln!("OPEN_GEUL_RESOURCE_FIXTURE {}",serde_json::json!({"function":function,"stage":stage,"line":line,"values":values}));
}

fn resource_byte_only_pair(core:&DocumentCore)->(Document,Document){
    use rhwp::serializer::hwpx::roundtrip::{hwpx_persistence_document,hwpx_persistence_expected_document};
    resource_fixture_stage(2,50,line!(),&[]);
    let expected=hwpx_persistence_expected_document(core).expect("existing linked or empty-slot save must have an independent expectation");
    resource_fixture_stage(2,51,line!(),&[1]);
    let bytes=core.export_hwpx_native().expect("actual linked metadata export");
    resource_fixture_stage(2,55,line!(),&[bytes.len() as u64]);
    let actual=hwpx_persistence_document(&rhwp::parse_document(&bytes).expect("byte-only linked metadata import"));
    resource_fixture_stage(2,60,line!(),&[actual.bin_data_content.len() as u64]);
    (expected,actual)
}

#[test]
fn actual_linked_uri_and_embedded_resource_preservation_are_supported(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_linked_source(false,false);let(expected,actual)=resource_byte_only_pair(&core);
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
    let link=actual.doc_info.bin_data_list.iter().find(|entry|entry.data_type==rhwp::model::bin_data::BinDataType::Link).expect("retained linked role");
    assert!(link.abs_path.as_deref()==Some("https://example.invalid/owned-linked.png"));
    let mut changed=actual.clone();changed.doc_info.bin_data_list.iter_mut().find(|entry|entry.storage_id==link.storage_id).unwrap().abs_path=Some("https://example.invalid/other.png".into());
    assert!(!hwpx_persistence_resources_match(&expected,&changed),"same-count linked target substitution must fail");
}

#[test]
fn actual_unreferenced_link_record_does_not_erase_later_embedded_owner(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_linked_source(true,false);let source_bytes=core.document().bin_data_content[0].data.load_limited(1024).expect("owned surviving embedded data");
    let(expected,actual)=resource_byte_only_pair(&core);
    assert!(actual.bin_data_content.iter().any(|c|c.data.load_limited(1024).is_some_and(|bytes|bytes==source_bytes)),"an earlier link descriptor cannot erase a later owned resource");
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
}

#[test]
fn actual_unreferenced_hwp5_empty_link_slot_has_no_deletion_authority_for_ink(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_linked_source(true,true);let(expected,actual)=resource_byte_only_pair(&core);
    assert_eq!(actual.bin_data_content.iter().filter(|c|c.data.load_limited(1024).is_some_and(|bytes|!bytes.is_empty())).count(),1);
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
}

#[test]
fn actual_referenced_missing_descriptor_and_invalid_zero_storage_are_rejected(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_expected_document;
    let mut core=resource_linked_source(false,true);
    // A declared Link with an empty URI is a supported missing-image placeholder.
    // This negative instead has an invalid zero-storage embedded descriptor.
    core.document_mut().doc_info.bin_data_list[0].data_type=rhwp::model::bin_data::BinDataType::Embedding;
    core.document_mut().doc_info.bin_data_list[0].attr=(core.document().doc_info.bin_data_list[0].attr&!0x000f)|1;
    assert!(hwpx_persistence_expected_document(&core).is_none(),"a referenced zero-storage embedded descriptor is invalid");
    for c in &mut core.document_mut().sections[0].paragraphs[0].controls {if let Control::Picture(p)=c{p.image_attr.bin_data_id=65500;}}
    assert!(hwpx_persistence_expected_document(&core).is_none(),"a missing source descriptor cannot borrow an unrelated resource");
}

fn resource_actual_hwp5_link(empty_uri:bool)->DocumentCore {
    let mut author=resource_linked_source(false,true);
    if !empty_uri {
        let document=author.document_mut();document.doc_info.bin_data_list[0].abs_path=Some("https://example.invalid/owned-hwp5-link.png".into());
        for control in &mut document.sections[0].paragraphs[0].controls {if let Control::Picture(p)=control{if p.image_attr.bin_data_id==1{p.image_attr.external_path=Some("https://example.invalid/owned-hwp5-link.png".into());}}}
    }
    let source=&author.document().doc_info.bin_data_list[0];
    resource_fixture_stage(1,10,line!(),&[u64::from(source.data_type==rhwp::model::bin_data::BinDataType::Link),u64::from(source.attr&0x000f),u64::from(source.storage_id)]);
    let bytes=author.export_hwp_native().expect("actual owned HWP5 serialization without marker bypass");
    resource_fixture_stage(1,20,line!(),&[bytes.len() as u64]);
    let core=DocumentCore::from_bytes(&bytes).expect("independent actual HWP5 load");
    let parsed=&core.document().doc_info.bin_data_list[0];
    resource_fixture_stage(1,30,line!(),&[u64::from(parsed.data_type==rhwp::model::bin_data::BinDataType::Link),u64::from(parsed.attr&0x000f),u64::from(parsed.storage_id),u64::from(core.document().bin_data_content[0].id)]);
    assert!(core.document().doc_info.bin_data_list[0].data_type==rhwp::model::bin_data::BinDataType::Link);
    assert_eq!(core.document().doc_info.bin_data_list[0].storage_id,0);
    assert_eq!(core.document().bin_data_content[0].id,0);
    assert!(core.document().bin_data_content[0].data.load_limited(0).is_some_and(|bytes|bytes.is_empty()));
    resource_fixture_stage(1,40,line!(),&[1]);
    core
}

#[test]
fn actual_hwp5_zero_storage_link_and_embedded_owner_survive_hwpx_reopen(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_actual_hwp5_link(false);let(expected,actual)=resource_byte_only_pair(&core);
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
    assert!(actual.doc_info.bin_data_list.iter().any(|entry|entry.data_type==rhwp::model::bin_data::BinDataType::Link&&entry.abs_path.as_deref()==Some("https://example.invalid/owned-hwp5-link.png")));
    assert_eq!(actual.bin_data_content.iter().filter(|c|c.data.load_limited(1024).is_some_and(|b|!b.is_empty())).count(),1);
}

#[test]
fn actual_hwp5_link_uri_and_owner_substitution_are_rejected(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_actual_hwp5_link(false);let(expected,actual)=resource_byte_only_pair(&core);
    assert!(hwpx_persistence_resources_match(&expected,&actual));
    let link=actual.doc_info.bin_data_list.iter().find(|entry|entry.data_type==rhwp::model::bin_data::BinDataType::Link).expect("owned actual linked role").storage_id;
    let embedded=actual.bin_data_content[0].id;assert_ne!(link,embedded);
    let mut changed=actual.clone();changed.doc_info.bin_data_list.iter_mut().find(|entry|entry.storage_id==link).unwrap().abs_path=Some("https://example.invalid/changed-hwp5-link.png".into());
    assert!(!hwpx_persistence_resources_match(&expected,&changed));
    let mut changed=actual.clone();let mut count=0;
    for control in &mut changed.sections[0].paragraphs[0].controls {if let Control::Picture(p)=control{if p.image_attr.bin_data_id==link{p.image_attr.bin_data_id=embedded;count+=1;}}}
    assert_eq!(count,1);assert!(!hwpx_persistence_resources_match(&expected,&changed));
}

#[test]
fn actual_hwp5_declared_empty_link_is_a_preserved_placeholder(){
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_resources_match;
    let core=resource_actual_hwp5_link(true);let(expected,actual)=resource_byte_only_pair(&core);
    assert!(diff_documents(&expected,&actual).is_empty());assert!(hwpx_persistence_resources_match(&expected,&actual));
    assert!(actual.doc_info.bin_data_list.iter().any(|entry|entry.data_type==rhwp::model::bin_data::BinDataType::Link&&entry.abs_path.as_deref().unwrap_or_default().is_empty()));
    assert_eq!(actual.sections[0].paragraphs[0].controls.iter().filter(|c|matches!(c,Control::Picture(_))).count(),2);
}

#[test]
fn actual_empty_link_manifest_entry_preserves_position_and_rejects_missing_paths() {
    use rhwp::parser::hwpx::content::parse_content_hpf;
    let xml = r#"<package><manifest>
<item id="empty-link" href="" media-type="image/png" isEmbeded="0"/>
<item id="embedded" href="BinData/image2.png" media-type="image/png" isEmbeded="1"/>
</manifest></package>"#;
    let parsed = parse_content_hpf(xml).expect("public package parser");
    assert_eq!(parsed.bin_data_items.len(), 2);
    assert_eq!(parsed.bin_data_items[0].id, "empty-link");
    assert!(!parsed.bin_data_items[0].is_embedded);
    assert!(parsed.bin_data_items[0].href.is_empty());
    assert_eq!(parsed.bin_data_items[1].id, "embedded");
    let rejected = r#"<package><manifest>
<item id="no-href" media-type="image/png" isEmbeded="0"/>
<item id="embedded-empty" href="" media-type="image/png" isEmbeded="1"/>
<item id="default-embedded" href="" media-type="image/png"/>
<item id="xml-empty" href="" media-type="application/xml" isEmbeded="0"/>
<item id="" href="" media-type="image/png" isEmbeded="0"/>
<item id="   " href="" media-type="image/png" isEmbeded="0"/>
<unrelated id="noise" href="" media-type="image/png" isEmbeded="0"/>
</manifest></package>"#;
    assert!(parse_content_hpf(rejected).expect("public rejection parse").bin_data_items.is_empty());
}

#[test]
fn actual_zero_embedding_descriptor_cannot_borrow_a_colliding_owned_resource() {
    use rhwp::model::bin_data::BinDataType;
    use rhwp::serializer::hwpx::roundtrip::hwpx_persistence_expected_document;
    let mut core = resource_linked_source(false, true);
    let document = core.document_mut();
    document.doc_info.bin_data_list[0].data_type = BinDataType::Embedding;
    document.doc_info.bin_data_list[0].attr = (document.doc_info.bin_data_list[0].attr & !0x000f) | 1;
    document.doc_info.bin_data_list[1].storage_id = 1;
    document.bin_data_content[1].id = 1;
    assert_eq!(document.doc_info.bin_data_list[0].storage_id, 0);
    assert!(document.bin_data_content[0].data.is_empty());
    assert!(!document.bin_data_content[1].data.is_empty());
    assert!(hwpx_persistence_expected_document(&core).is_none(), "an explicit invalid record cannot borrow a later resource by numeric collision");
}
