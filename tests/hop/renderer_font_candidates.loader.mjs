import {registerHooks,stripTypeScriptTypes} from 'node:module';
import {readFileSync,existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
export const prepared=resolve(process.env.RENDERER_FONT_CANDIDATES_PREPARED??'.work/hop');
const host=resolve(prepared,'apps/studio-host/src');
const fixture=new URL('./renderer_font_candidates.fixture.mjs',import.meta.url).href;
registerHooks({
 resolve(specifier,context,next){
  if(specifier==='@upstream/core/local-fonts'||specifier==='@tauri-apps/api/core')return {url:fixture,shortCircuit:true};
  if(specifier.startsWith('@/'))return {url:pathToFileURL(resolve(host,specifier.slice(2)+'.ts')).href,shortCircuit:true};
  if(specifier.startsWith('.')&&context.parentURL?.startsWith('file:')){
   const candidate=fileURLToPath(new URL(specifier,context.parentURL));
   if(!existsSync(candidate)&&existsSync(candidate+'.ts'))return {url:pathToFileURL(candidate+'.ts').href,shortCircuit:true};
  }
  return next(specifier,context);
 },
 load(url,context,next){
  if(url.startsWith('file:')&&url.endsWith('.ts'))return {format:'module',source:stripTypeScriptTypes(readFileSync(fileURLToPath(url),'utf8'),{mode:'transform',sourceUrl:url}),shortCircuit:true};
  return next(url,context);
 }
});
