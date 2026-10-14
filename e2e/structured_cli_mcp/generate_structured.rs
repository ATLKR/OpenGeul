//! Draft same-source native fixture generator. Expected values live independently in expected.json.
//! Compile only through the reviewed Source native generator target; never a product private test bridge.
use hop_rhwp_adapter::{split_paragraph_for_editing, DocumentCore};
use std::{env, fs, path::PathBuf};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let out=PathBuf::from(env::args().nth(1).ok_or("fresh output directory required")?);
    if !out.is_dir() || out.join("structured.hwp").exists() || out.join("structured.hwpx").exists() { return Err("owned fresh stage required".into()); }
    let png=fs::read(out.join("checkerboard.png"))?;
    let mut core=DocumentCore::new_empty();
    core.create_blank_document_native().map_err(|e|e.to_string())?;
    let paragraphs=["BODY-한글-😀-Ω-&-<xml> FIND-OWNED FIND-OWNED","BODY-TAIL","CUSTOMER:","ITEM:",""];
    for (i,text) in paragraphs.iter().enumerate() {
        if !text.is_empty(){core.insert_text_native(0,i,0,text).map_err(|e|e.to_string())?;}
        if i+1<paragraphs.len(){split_paragraph_for_editing(&mut core,0,i,text.chars().count())?;}
    }
    core.insert_click_here_field_at(0,2,9,"Customer","owned draft","CUSTOMER",true).map_err(|e|e.to_string())?;
    core.insert_click_here_field_at(0,3,5,"Item","owned draft","ITEM",true).map_err(|e|e.to_string())?;
    let table=core.create_table_native(0,4,0,2,2).map_err(|e|e.to_string())?;
    let address:serde_json::Value=serde_json::from_str(&table)?;
    if address["ok"]!=true || address["paraIdx"]!=4 || address["controlIdx"]!=0 { return Err("predeclared table address differs".into()); }
    for (cell,text) in ["CELL-R0-C0","CELL-R0-C1","CELL-R1-C0","CELL-R1-C1|"].iter().enumerate() {
        core.insert_text_in_cell_native(0,4,0,cell,0,0,text).map_err(|e|e.to_string())?;
    }
    core.insert_click_here_field_at_in_cell(0,4,0,3,0,11,false,"Item","owned draft","ITEM",true).map_err(|e|e.to_string())?;
    core.set_field_value_by_name_at("CUSTOMER",0,"C-INIT").map_err(|e|e.to_string())?;
    core.set_field_value_by_name_at("ITEM",0,"I-BODY").map_err(|e|e.to_string())?;
    core.set_field_value_by_name_at("ITEM",1,"I-CELL").map_err(|e|e.to_string())?;
    core.apply_char_format_in_cell_native(0,4,0,1,0,0,10,r##"{"italic":true,"textColor":"#123456"}"##).map_err(|e|e.to_string())?;
    // A4 blank's public defaults; independent stage rejects any different geometry.
    core.insert_picture_native(0,5,0,&[],&png,11339,5669,32,16,"png","OWNED-CHECKERBOARD",Some(8504),Some(28346)).map_err(|e|e.to_string())?;
    fs::write(out.join("structured.hwp"),core.export_hwp_native().map_err(|e|e.to_string())?)?;
    fs::write(out.join("structured.hwpx"),core.export_hwpx_native().map_err(|e|e.to_string())?)?;
    println!("{}",serde_json::json!({"generated":true,"files":["structured.hwp","structured.hwpx"],"table":{"section":0,"paragraph":4,"control":0}}));
    Ok(())
}
