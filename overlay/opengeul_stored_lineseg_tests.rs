//! Authored public-API field documents and adversarial stored row ownership.
//! No original/private documents, font programs, CLI bypass or weakened IR diff.
use rhwp::{DocumentCore, model::{document::Document, paragraph::{LineSeg, Paragraph}}};
use rhwp::model::control::Control;
use rhwp::serializer::hwpx::roundtrip::{diff_documents, strip_hwp_to_hwpx_noise};

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
    core.export_hwp_native().expect("native HWP serialization")
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
        assert!(p.line_segs.iter().all(|s|s.tag&LineSeg::TAG_IMPLEMENTATION_PROPERTY!=0 && s.line_height>0 && s.text_height>0));
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
    let input=rhwp::serializer::serialize_document(&stored).expect("actual stored regression bytes");
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
