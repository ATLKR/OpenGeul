/** Synthetic printer documents through the real pinned engine; no third-party documents/fonts. */
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [vendorArg, outputArg]=process.argv.slice(2);
if(!vendorArg||!outputArg)throw new Error('usage: generate.mjs <WASM vendor directory> <output>');
const vendor=resolve(vendorArg),output=resolve(outputArg);
const {default:init,HwpDocument}=await import(pathToFileURL(join(vendor,'rhwp.js')));
await init({module_or_path:readFileSync(join(vendor,'rhwp_bg.wasm'))});
mkdirSync(output,{recursive:true});
function checked(v){const r=typeof v==='string'?JSON.parse(v):v;if(r?.ok===false)throw new Error(JSON.stringify(r));return r;}
function blank(){const d=HwpDocument.createEmpty();checked(d.createBlankDocument());return d;}
const manifest={};
function save(name,d,pages){
 assert.equal(d.pageCount(),pages.length,`synthetic ${name} page count`);
 for(const ext of ['hwp','hwpx']){
  const bytes=ext==='hwp'?d.exportHwp():d.exportHwpx();
  const reopened=new HwpDocument(bytes);
  try{assert.equal(reopened.pageCount(),pages.length,`reopened ${name}.${ext} page count`);}
  finally{reopened.free();}
  writeFileSync(join(output,`${name}.${ext}`),bytes);
 }
 manifest[name]={pages,size_pt:[595.276,841.89]};d.free();
}
let d=blank();checked(d.insertText(0,0,0,'PRINT-FIRST'));
checked(d.splitParagraph(0,0,11));checked(d.insertText(0,1,0,'PRINT-LAST'));
save('print-basic',d,[['PRINT-FIRST','PRINT-LAST']]);
d=blank();
for(let i=0;i<3;i++){
 const text=`PAGE-${i+1}-FIRST PAGE-${i+1}-LAST`;
 checked(d.insertText(0,i,0,text));
 if(i<2)checked(d.insertPageBreak(0,i,text.length));
}
save('print-three',d,Array.from({length:3},(_,i)=>[`PAGE-${i+1}-FIRST`,`PAGE-${i+1}-LAST`]));
d=blank();let created=checked(d.createTable(0,0,0,2,2));console.log('Synthetic table location',created);
for(let cell=0;cell<4;cell++){
 checked(d.insertTextInCell(0,created.paraIdx,created.controlIdx,cell,0,0,`CELL-${cell+1}-FIRST`));
 checked(d.splitParagraphInCell(0,created.paraIdx,created.controlIdx,cell,0,12));
 checked(d.insertTextInCell(0,created.paraIdx,created.controlIdx,cell,1,0,`CELL-${cell+1}-LAST`));
}
save('print-table',d,[[...Array.from({length:4},(_,i)=>[`CELL-${i+1}-FIRST`,`CELL-${i+1}-LAST`]).flat()]]);
writeFileSync(join(output,'print-manifest.json'),JSON.stringify(manifest,null,2)+'\n');
