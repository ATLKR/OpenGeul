/** Offline INPUT generation only. This is not product UI execution evidence. */
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const prepared=resolve(process.argv[2]);
const folder=resolve(process.argv[3]);
const vendor=join(prepared,'apps/studio-host/vendor/rhwp-core');
const {default:init,HwpDocument}=await import(pathToFileURL(join(vendor,'rhwp.js')));
const wasm=readFileSync(join(vendor,'rhwp_bg.wasm'));
await init({module_or_path:wasm}); mkdirSync(folder,{recursive:true});
const sha=b=>createHash('sha256').update(b).digest('hex');
const files={};
function checked(raw){const value=typeof raw==='string'?JSON.parse(raw):raw;
  if(value?.ok===false)throw Error(JSON.stringify(value));return value;}
function blank(){const doc=HwpDocument.createEmpty();checked(doc.createBlankDocument());return doc;}
function save(name,doc){const bytes=doc.exportHwpx();writeFileSync(join(folder,name+'.hwpx'),bytes,{flag:'wx'});files[name+'.hwpx']=sha(bytes);}
let doc=blank(); save('owned-blank',doc);doc.free();
doc=blank(); const table=checked(doc.createTable(0,0,0,2,2));
for(let ci=0;ci<4;ci++)checked(doc.insertTextInCell(0,table.paraIdx,table.controlIdx,ci,0,0,'ADV-CELL-'+Math.floor(ci/2)+(ci%2)));
save('owned-grid',doc);
checked(doc.mergeTableCells(0,table.paraIdx,table.controlIdx,0,0,0,1));save('owned-merged',doc);
checked(doc.splitTableCellInto(0,table.paraIdx,table.controlIdx,0,0,1,2,false,false));save('owned-split',doc);doc.free();
doc=blank();checked(doc.insertText(0,0,0,'FIELD-BODY-HEAD'));
const field=checked(doc.insertClickHereField(0,0,15,'ADV-GUIDE','ADV-MEMO','ADV-NAME',true));
save('owned-field-guide',doc);checked(doc.setFieldValueByName('ADV-NAME','ADV-VALUE'));
save('owned-field-filled',doc);doc.free();
doc=blank();checked(doc.insertText(0,0,0,'EQUATION-BODY'));
checked(doc.insertEquation(0,0,13,'x^2 + {1} over {2}',1000,0));save('owned-equation',doc);doc.free();
doc=blank();checked(doc.insertText(0,0,0,'NOTE-BODY'));
const foot=checked(doc.insertFootnote(0,0,9));
checked(doc.insertTextInFootnote(0,0,foot.controlIdx,0,2,'ADV-FOOTNOTE'));
const end=checked(doc.insertEndnote(0,0,9));
checked(doc.insertTextInFootnote(0,0,end.controlIdx,0,2,'ADV-ENDNOTE'));
save('owned-notes',doc);doc.free();
doc=blank();checked(doc.insertText(0,0,0,'PAGE-BODY-ONE'));checked(doc.insertPageBreak(0,0,13));
checked(doc.insertText(0,1,0,'PAGE-BODY-TWO'));
checked(doc.setPageDef(0,JSON.stringify({width:Math.round(210*7200/25.4),height:Math.round(297*7200/25.4),
  landscape:true,binding:0,marginLeft:4819,marginRight:5386,marginTop:3685,marginBottom:6520,
  marginHeader:2268,marginFooter:2551,marginGutter:0})));
checked(doc.createHeaderFooter(0,true,0));checked(doc.insertTextInHeaderFooter(0,true,0,0,0,'ADV-HEADER'));
checked(doc.createHeaderFooter(0,false,0));checked(doc.insertTextInHeaderFooter(0,false,0,0,0,'ADV-FOOTER'));
save('owned-page',doc);doc.free();
doc=blank();checked(doc.insertText(0,0,0,'SHAPE-BODY'));
checked(doc.createShapeControl(JSON.stringify({sectionIdx:0,paraIdx:0,charOffset:10,width:11339,height:5669,
  horzOffset:20000,vertOffset:30000,shapeType:'rectangle'})));
save('owned-shape',doc);doc.free();
doc=blank();checked(doc.insertText(0,0,0,'SHAPE-BODY'));
const textbox=checked(doc.createShapeControl(JSON.stringify({sectionIdx:0,paraIdx:0,charOffset:10,width:11339,height:5669,
  horzOffset:20000,vertOffset:30000,shapeType:'textbox',treatAsChar:false,textWrap:'InFrontOfText'})));
checked(doc.insertTextInCell(0,textbox.paraIdx,textbox.controlIdx,0,0,0,'ADV-TEXTBOX'));
save('owned-textbox',doc);doc.free();
writeFileSync(join(folder,'provenance.json'),JSON.stringify({purpose:'Owned synthetic inputs; no GUI claim',
  vendorWasmSha256:sha(wasm),generated:files},null,2));
