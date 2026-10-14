/** Load the exact prepared source; only explicit reviewed candidates are replaced. */
import {prepared} from './shape_creation_history.loader.mjs';
import {registerHooks,stripTypeScriptTypes} from 'node:module';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
export {prepared};
const cursorUrl=pathToFileURL(resolve(prepared,'third_party/rhwp/rhwp-studio/src/engine/cursor.ts')).href;
const bridgeUrl=pathToFileURL(resolve(prepared,'third_party/rhwp/rhwp-studio/src/core/wasm-bridge.ts')).href;
registerHooks({load(url,context,next){
 const candidate=url===cursorUrl?process.env.NESTED_LINE_NAVIGATION_CURSOR:url===bridgeUrl?process.env.NESTED_LINE_NAVIGATION_BRIDGE:undefined;
 if(candidate){
  const source='import.meta.env ??= {DEV:false,PROD:true};\n'+stripTypeScriptTypes(readFileSync(resolve(candidate),'utf8'),{mode:'transform',sourceUrl:url});
  return {format:'module',source,shortCircuit:true};
 }
 return next(url,context);
}});
