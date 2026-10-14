// Real source loader for the shape routing test. CSS and DOM geometry are outside
// its scope; WASM, InputHandler, CursorState, and CommandHistory are never mocked.
import {registerHooks,createRequire,stripTypeScriptTypes} from 'node:module';
import {existsSync,readFileSync,statSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

export const prepared=resolve(process.env.HOP_SHAPE_HISTORY_PREPARED ?? process.env.HOP_SOURCE ?? '.work/hop');
const upstream=resolve(process.env.RHWP_SOURCE ?? resolve(prepared,'third_party/rhwp'),'rhwp-studio/src');
const host=resolve(prepared,'apps/studio-host/src');
const overrideFile=resolve(prepared,'config/rhwp-studio-overrides.json');
const overrides=new Set(JSON.parse(readFileSync(overrideFile,'utf8')).overrides.map(entry=>entry.id));
const dependencyRoots=[prepared,dirname(host),dirname(upstream),...JSON.parse(process.env.HOP_SHAPE_HISTORY_DEPENDENCY_ROOTS ?? '[]')];
const inputHandlerUrl=pathToFileURL(resolve(upstream,'engine/input-handler.ts')).href;
const alternateHandler=process.env.HOP_SHAPE_HISTORY_HANDLER;
const connectorUrl=pathToFileURL(resolve(upstream,'engine/input-handler-connector.ts')).href;
const alternateConnector=process.env.HOP_SHAPE_HISTORY_CONNECTOR;
let resolvingDependency=false;
function existingModule(base){
  for(const candidate of [base,base+'.ts',base+'.js',resolve(base,'index.ts')])
    if(existsSync(candidate)&&statSync(candidate).isFile())return pathToFileURL(candidate).href;
  return pathToFileURL(base).href;
}
export function resolveDependency(specifier){
  let failure;
  const previous=resolvingDependency;resolvingDependency=true;
  try{for(const root of dependencyRoots){
    try{return createRequire(resolve(root,'package.json')).resolve(specifier);}catch(error){failure=error;}
  }}finally{resolvingDependency=previous;}
  throw new Error(`Required existing dependency unavailable: ${specifier}. Set HOP_SHAPE_HISTORY_DEPENDENCY_ROOTS to existing project roots.`,{cause:failure});
}
registerHooks({
  resolve(specifier,context,next){
    if(specifier==='@wasm/rhwp.js')return next(pathToFileURL(resolve(prepared,'apps/studio-host/vendor/rhwp-core/rhwp.js')).href,context);
    if(specifier.startsWith('@/upstream/'))return next(existingModule(resolve(host,specifier.slice(2))),context);
    if(specifier.startsWith('@upstream/'))return next(existingModule(resolve(upstream,specifier.slice(10))),context);
    if(specifier.startsWith('@/')){
      const id=specifier.slice(2);
      const root=overrides.has(id.replace(/\.ts$/,''))?host:upstream;
      return next(existingModule(resolve(root,id)),context);
    }
    if(specifier.startsWith('.')&&context.parentURL?.startsWith(pathToFileURL(prepared+'/').href)){
      const base=resolve(dirname(fileURLToPath(context.parentURL)),specifier);
      if(!/\.[a-z]+$/i.test(base))return next(existingModule(base),context);
    }
    try{return next(specifier,context);}catch(error){
      if(resolvingDependency||specifier.startsWith('.')||specifier.startsWith('/')||specifier.startsWith('node:'))throw error;
      return next(pathToFileURL(resolveDependency(specifier)).href,context);
    }
  },
  load(url,context,next){
    if(url.endsWith('.css'))return {format:'module',source:'export {};',shortCircuit:true};
    if(url.startsWith('file:')&&url.endsWith('.ts')){
      const path=url===inputHandlerUrl&&alternateHandler?resolve(alternateHandler)
        :url===connectorUrl&&alternateConnector?resolve(alternateConnector):fileURLToPath(url);
      // Vite supplies this production environment in the product bundle.
      const source='import.meta.env ??= {DEV:false,PROD:true};\n'+stripTypeScriptTypes(readFileSync(path,'utf8'),{mode:'transform',sourceUrl:url});
      return {format:'module',source,shortCircuit:true};
    }
    return next(url,context);
  },
});
