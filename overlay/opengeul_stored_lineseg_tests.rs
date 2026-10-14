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

// Additive Source4 boundaries. The original six tests above remain unchanged.
const OWNER_PNG: &[u8]=&[137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,1,0,0,0,1,8,6,0,0,0,31,21,196,137,0,0,0,13,73,68,65,84,120,156,99,248,207,192,240,31,0,5,0,1,255,137,153,61,29,0,0,0,0,73,69,78,68,174,66,96,130];

fn owner_picture_core() -> DocumentCore {
    let mut author=DocumentCore::new_empty();author.create_blank_document_native().expect("owned owner blank");
    author.insert_picture_native(0,0,0,&[],OWNER_PNG,11339,5669,1,1,"png","OWNED-ROW-OWNER",Some(8504),Some(28346)).expect("public owner picture");
    DocumentCore::from_bytes(&author.export_hwp_native().expect("owned stored source")).expect("public stored owner import")
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

#[test]
fn public_tac_preserves_existing_dirty_partition_until_recomputed() {
    let mut core=owner_picture_core();let index=owner_picture_index(&core.document().sections[0].paragraphs[0]);
    let before=owner_text_state(&core.document().sections[0].paragraphs[0]);
    core.document_mut().sections[0].paragraphs[0].invalidate_layout_inputs();
    core.set_picture_properties_native(0,0,index,r#"{"treatAsChar":true}"#).expect("public dirty TAC");
    let after=&core.document().sections[0].paragraphs[0];
    assert!(after.stored_text_partition_is_dirty(),"geometry-only publication cannot certify an already invalid text partition");
    assert_eq!(owner_text_state(after),before,"text/control-slot structure stays unchanged");
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("dirty owner save")).expect("dirty owner readback");
    assert!(saved.sections[0].paragraphs[0].line_segs.is_empty(),"consumer must recompute an invalid cache");
    assert_eq!(saved.sections[0].paragraphs[0].text,before.0);
    assert!(core.render_page_svg_native(0).expect("dirty owner render").contains("<image"));
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

#[test]
fn public_hwpx_tac_keeps_nonzero_source_text_axis_and_leading_slots() {
    let mut author=owner_picture_core();author.insert_text_native(0,0,0,"AXIS-OWNED-1234567890").expect("public axis text");
    let mut doc=rhwp::parse_document(&author.export_hwp_native().expect("axis authored HWP")).expect("axis stored source");
    doc.sections[0].raw_stream=None;
    let p=&mut doc.sections[0].paragraphs[0];
    let mut second=p.line_segs[0].clone();second.text_start=p.char_offsets[8];second.vertical_pos+=1600;second.tag&=!LineSeg::TAG_IMPLEMENTATION_PROPERTY;
    p.line_segs[0].tag&=!LineSeg::TAG_IMPLEMENTATION_PROPERTY;p.line_segs.push(second);
    let bytes=rhwp::serializer::serialize_hwpx(&doc).expect("actual leading-slot HWPX input");
    let mut core=DocumentCore::from_bytes(&bytes).expect("public leading-slot HWPX import");
    let before=&core.document().sections[0].paragraphs[0];let shift=before.hwpx_axis_shift;
    assert!(shift>0,"real HWPX parser supplies the leading secPr/colPr source axis");
    let starts:Vec<_>=before.line_segs.iter().map(|s|s.text_start).collect();assert!(starts.iter().any(|s|*s>0));
    let projected:Vec<_>=starts.iter().map(|s|before.line_seg_text_start_of(*s)).collect();
    let text_state=owner_text_state(before);let index=owner_picture_index(before);
    core.set_picture_properties_native(0,0,index,r#"{"treatAsChar":true}"#).expect("public HWPX axis TAC");
    let after=&core.document().sections[0].paragraphs[0];assert_eq!(after.hwpx_axis_shift,shift);
    assert_eq!(after.line_segs.iter().map(|s|s.text_start).collect::<Vec<_>>(),starts);
    assert_eq!(starts.iter().map(|s|after.line_seg_text_start_of(*s)).collect::<Vec<_>>(),projected);
    assert_eq!(owner_text_state(after),text_state);
    let saved=rhwp::parse_document(&core.export_hwpx_native().expect("source-axis save")).expect("source-axis readback");
    assert_eq!(saved.sections[0].paragraphs[0].text,text_state.0);
    assert_eq!(saved.sections[0].paragraphs[0].line_segs.iter().map(|s|s.text_start).collect::<Vec<_>>(),starts,"unchanged HWPX text axis survives public save");
    assert!(core.render_page_svg_native(0).expect("source-axis render").contains("<image"));
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
fn public_imported_tac_header_footer_text_reverse_invalidates_stored_origin() {
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
        let input=author.export_hwp_native().expect("actual stored HF input");
        let mut core=DocumentCore::from_bytes(&input).expect("public stored HF import");
        let address=owner_hf_address(core.document(),is_header);let before=owner_hf_paragraph(core.document(),address);
        assert!(before.source_line_seg_vertical_pos.is_some());assert!(before.text.contains("OWNED-HF-TEXT"));
        let text=before.text.clone();let (pi,ci,inner,picture)=address;
        core.set_header_footer_picture_properties_native(0,pi,ci,inner,picture,r#"{"treatAsChar":false}"#).expect("public imported HF TAC reverse");
        let after=owner_hf_paragraph(core.document(),address);
        assert!(after.source_line_seg_vertical_pos.is_none());assert!(after.stored_text_partition_is_dirty(),"early-return HF geometry cannot certify its old rows");assert_eq!(after.text,text);
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
    author.export_hwp_native().expect("actual stored Endnote source")
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
