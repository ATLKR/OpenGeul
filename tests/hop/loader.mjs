import {pathToFileURL,fileURLToPath} from 'node:url';
import {existsSync} from 'node:fs';
import {resolve as pathResolve} from 'node:path';
const hop=process.env.HOP_SOURCE ?? pathResolve('.work/hop');
const rhwp=process.env.RHWP_SOURCE ?? pathResolve(hop,'third_party/rhwp');
export async function resolve(specifier, context, next) {
 let path;
 if(specifier.startsWith('@/upstream/')) path=pathResolve(hop,'apps/studio-host/src',specifier.slice(2)+'.ts');
 else if(specifier.startsWith('@upstream/')) path=pathResolve(rhwp,'rhwp-studio/src',specifier.slice(10)+'.ts');
 else if(specifier.startsWith('.') && context.parentURL) {
  const candidate=fileURLToPath(new URL(specifier,context.parentURL));
  if(!existsSync(candidate) && existsSync(candidate+'.ts')) path=candidate+'.ts';
 }
 if(path)return {url:pathToFileURL(path).href,shortCircuit:true};
 return next(specifier,context);
}
