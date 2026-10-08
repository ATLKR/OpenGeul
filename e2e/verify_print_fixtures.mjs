/** Validate synthetic printer input via the exact generated WASM, not PDF output. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
const vendor=resolve(process.argv[2]),folder=resolve(process.argv[3]);
const {default:init,HwpDocument}=await import(pathToFileURL(join(vendor,'rhwp.js')));
await init({module_or_path:readFileSync(join(vendor,'rhwp_bg.wasm'))});
const cases=JSON.parse(readFileSync(join(folder,'print-cases.json'),'utf8'));
function text(node){return (node.type==='TextRun'?node.text:'')+(node.children??[]).map(text).join('');}
for(const c of cases){
  const doc=new HwpDocument(readFileSync(join(folder,c.file)));
  try{
    assert.equal(doc.pageCount(),c.pages.length,`${c.name}: page count`);
    for(let i=0;i<c.pages.length;i++){
      const t=text(JSON.parse(doc.getPageRenderTree(i)));
      for(const marker of c.pages[i].markers)assert.equal(t.split(marker).length-1,1,`${c.name}: ${marker}`);
    }
  }finally{doc.free();}
}
console.log(`Verified ${cases.length} synthetic printer fixtures with real engine page/text data.`);
