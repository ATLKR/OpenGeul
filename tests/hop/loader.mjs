import {pathToFileURL,fileURLToPath} from 'node:url';
import {existsSync,readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {resolve as pathResolve} from 'node:path';
const hop=process.env.HOP_SOURCE ?? pathResolve('.work/hop');
const rhwp=process.env.RHWP_SOURCE ?? pathResolve(hop,'third_party/rhwp');
export async function resolve(specifier, context, next) {
 let path;
 if(specifier.startsWith('@/upstream/')) path=pathResolve(hop,'apps/studio-host/src',specifier.slice(2)+'.ts');
 else if(specifier.startsWith('@upstream/')) path=pathResolve(rhwp,'rhwp-studio/src',specifier.slice(10)+'.ts');
 // The editor uses HOP's shortcut table through its Vite override.
 else if(specifier==='@/command/shortcut-map') path=pathResolve(hop,'apps/studio-host/src/command/shortcut-map.ts');
 else if(specifier.startsWith('@/')) path=pathResolve(rhwp,'rhwp-studio/src',specifier.slice(2)+(specifier.endsWith('.ts')?'':'.ts'));
 else if(specifier.startsWith('.') && context.parentURL) {
  const candidate=fileURLToPath(new URL(specifier,context.parentURL));
  if(!existsSync(candidate) && existsSync(candidate+'.ts')) path=candidate+'.ts';
 }
 if(path)return {url:pathToFileURL(path).href,shortCircuit:true};
 return next(specifier,context);
}

export async function load(url,context,next) {
 if(url.startsWith('file:') && url.endsWith('.ts')) {
  // Native upstream classes use parameter properties, which strip-only mode cannot load.
  const source=stripTypeScriptTypes(readFileSync(fileURLToPath(url),'utf8'),{mode:'transform',sourceUrl:url});
  return {format:'module',source,shortCircuit:true};
 }
 return next(url,context);
}
