/** Synthetic browser smoke inputs through the exact production WASM binding. */
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
const source=resolve(process.argv[2]??'.work/hop');
const output=resolve(process.argv[3]??'.work/e2e-fixtures');
const vendor=join(source,'apps/studio-host/vendor/rhwp-core');
const {default:init,HwpDocument}=await import(pathToFileURL(join(vendor,'rhwp.js')));
await init({module_or_path:readFileSync(join(vendor,'rhwp_bg.wasm'))});
mkdirSync(output,{recursive:true});
function checked(value){const v=typeof value==='string'?JSON.parse(value):value;if(v?.ok===false)throw new Error(JSON.stringify(v));return v;}
function document(text){const doc=HwpDocument.createEmpty();checked(doc.createBlankDocument());if(text)checked(doc.insertText(0,0,0,text));return doc;}
function save(name,doc){try{writeFileSync(join(output,name+'.hwp'),doc.exportHwp());writeFileSync(join(output,name+'.hwpx'),doc.exportHwpx());}finally{doc.free();}}
for(const [name,text] of [['blank',''],['basic','OpenGeul fixture 한글 가나다 & <xml> Ω 123'],['unicode','견적서 테스트 😀 한글 & < > Ω Cafe\u0301 끝'],['missing-font','Missing font fallback 문서']]){save(name,document(text));}
const doc=document('');
for(let i=0;i<12;i++){const text=`Row ${String(i).padStart(2,'0')} — generated content 한글 ${i}`;checked(doc.insertText(0,i,0,text));if(i!==11)checked(doc.splitParagraph(0,i,[...text].length));}
save('paragraphs',doc);
writeFileSync(join(output,'invalid.hwpx'),Buffer.from([0x50,0x4b,3,4,1,2,3]));
console.log('Generated browser smoke fixtures using production WASM, without a native compilation dependency.');
