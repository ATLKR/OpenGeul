import {pathToFileURL,fileURLToPath} from 'node:url';
import {existsSync,readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {resolve as pathResolve} from 'node:path';
const hop=process.env.HOP_SOURCE ?? pathResolve('.work/hop');
const rhwp=process.env.RHWP_SOURCE ?? pathResolve(hop,'third_party/rhwp');
const overrideConfig=pathResolve(hop,'config/rhwp-studio-overrides.json');
const overrides=new Set(existsSync(overrideConfig)
 ? JSON.parse(readFileSync(overrideConfig,'utf8')).overrides.map(({id})=>'@/'+id) : []);
export async function resolve(specifier, context, next) {
 let path;
 if(specifier==='@wasm/rhwp.js') path=pathResolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp.js');
 else if(specifier.startsWith('@/upstream/')) path=pathResolve(hop,'apps/studio-host/src',specifier.slice(2)+'.ts');
 else if(specifier.startsWith('@upstream/')) path=pathResolve(rhwp,'rhwp-studio/src',specifier.slice(10)+'.ts');
 // The editor uses HOP's shortcut table through its Vite override.
 else if(specifier==='@/command/shortcut-map' || overrides.has(specifier)) path=pathResolve(hop,'apps/studio-host/src',specifier.slice(2)+(specifier.endsWith('.css')?'':'.ts'));
 else if(specifier.startsWith('@/')) path=pathResolve(rhwp,'rhwp-studio/src',specifier.slice(2)+(specifier.endsWith('.ts')?'':'.ts'));
 else if(specifier.startsWith('.') && context.parentURL) {
  const candidate=fileURLToPath(new URL(specifier,context.parentURL));
  if(!existsSync(candidate) && existsSync(candidate+'.ts')) path=candidate+'.ts';
 }
 if(path)return {url:pathToFileURL(path).href,shortCircuit:true};
 return next(specifier,context);
}

export async function load(url,context,next) {
 if(url.startsWith('file:') && url.endsWith('.css')) {
  // Native insert commands import dialog CSS; style application is a DOM boundary.
  return {format:'module',source:'export default {};',shortCircuit:true};
 }
 if(url.startsWith('file:') && url.endsWith('.ts')) {
  // Native upstream classes use parameter properties, which strip-only mode cannot load.
  const source=stripTypeScriptTypes(readFileSync(fileURLToPath(url),'utf8'),{mode:'transform',sourceUrl:url});
  return {format:'module',source,shortCircuit:true};
 }
 return next(url,context);
}
