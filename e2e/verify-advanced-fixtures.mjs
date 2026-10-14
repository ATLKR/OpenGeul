/** Source-loadability evidence only, not GUI execution or an expected-output oracle. */
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
const vendor=join(resolve(process.argv[2]),'apps/studio-host/vendor/rhwp-core');
const folder=resolve(process.argv[3]);
const {default:init,HwpDocument}=await import(pathToFileURL(join(vendor,'rhwp.js')));
await init({module_or_path:readFileSync(join(vendor,'rhwp_bg.wasm'))});
const provenance=JSON.parse(readFileSync(join(folder,'provenance.json')));
for(const name of Object.keys(provenance.generated)){
 const doc=new HwpDocument(readFileSync(join(folder,name))); doc.free();
}
writeFileSync(join(folder,'loadability.json'),JSON.stringify({
 allOwnedHwpxLoadedByPreparedWasm:true,method:'constructor only; no GUI claim',
 names:Object.keys(provenance.generated)},null,2)+'\n');
