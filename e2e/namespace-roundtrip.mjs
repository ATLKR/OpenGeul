/** Exercise the real engine with a namespace-aliased, synthetic HWPX input. */
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
const [binding,input,output]=process.argv.slice(2);
const vendor=resolve(binding);
const {default:init,HwpDocument}=await import(pathToFileURL(join(vendor,'rhwp.js')));
await init({module_or_path:readFileSync(join(vendor,'rhwp_bg.wasm'))});
const doc=new HwpDocument(readFileSync(input));
try {writeFileSync(output,doc.exportHwpx());} finally {doc.free();}
