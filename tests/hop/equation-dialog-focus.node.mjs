/** Actual equation dialog, jsdom DOM, full InputHandler/history, and native WASM.
 * Only timer delivery is controlled. These tests do not manufacture the extra
 * font digits observed in the original browser artifact or replace engine APIs.
 */
import {prepared,upstream,vendor,resolveDependency} from './equation-dialog-focus.loader.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const jsdomPath=resolveDependency('jsdom');
const jsdomRequire=createRequire(jsdomPath);
assert.equal(JSON.parse(readFileSync(jsdomRequire.resolve('jsdom/package.json'),'utf8')).version,'26.1.0','Use the reviewed test-only DOM dependency');
const {JSDOM}=await import(pathToFileURL(jsdomPath));
const native=await import(pathToFileURL(resolve(vendor,'rhwp.js')));
const wasmPath=resolve(vendor,'rhwp_bg.wasm');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
if(process.env.HOP_EQUATION_FOCUS_WASM_SHA256)assert.equal(sha(readFileSync(wasmPath)),process.env.HOP_EQUATION_FOCUS_WASM_SHA256,'Actual selected native engine must match its declared pin');
await native.default({module_or_path:readFileSync(wasmPath)});
const source=name=>import(pathToFileURL(resolve(upstream,name)));
const immutablePaths=[wasmPath,resolve(vendor,'rhwp.js'),...['ui/equation-editor-dialog.ts','engine/input-handler.ts','engine/history.ts','core/wasm-bridge.ts'].map(name=>resolve(upstream,name))];
if(process.env.EQUATION_DIALOG_FOCUS_EDITOR)immutablePaths.push(resolve(process.env.EQUATION_DIALOG_FOCUS_EDITOR));
const immutableHashes=new Map(immutablePaths.map(path=>[path,sha(readFileSync(path))]));
const SCRIPT='x^2 + {1} over {2}';

/** The browser event-loop boundary, including delivery already dequeued at cancel. */
function timerBoundary(){
  const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
  let next=1,clock=0;
  const records=new Map();
  globalThis.setTimeout=(callback,delay=0,...args)=>{
    const handle=next++;records.set(handle,{callback,args,delay:Number(delay),due:clock+Number(delay),canceled:false,delivered:false});return handle;
  };
  globalThis.clearTimeout=handle=>{const record=records.get(handle);if(record)record.canceled=true;else originalClear(handle);};
  const pending=delay=>[...records].filter(([,record])=>!record.canceled&&!record.delivered&&(delay===undefined||record.delay===delay)).map(([handle])=>handle);
  const deliver=(handle,{alreadyDequeued=false}={})=>{
    const record=records.get(handle);assert.ok(record,'Timer must have been queued by product code');
    if(record.canceled&&!alreadyDequeued)return;
    record.delivered=true;record.callback(...record.args);
  };
  return {pending,deliver,
    tick(milliseconds){clock+=milliseconds;for(const [handle,record] of [...records].sort((a,b)=>a[1].due-b[1].due))if(!record.canceled&&!record.delivered&&record.due<=clock)deliver(handle);},
    restore(){globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;},
  };
}

async function harness(t){
  const dom=new JSDOM('<!doctype html><html><body><button id="outside">Outside</button><main><div id="scroll-container"><div id="scroll-content"><canvas></canvas></div></div></main></body></html>',{url:'https://equation-focus.test.invalid/',pretendToBeVisual:true});
  const names=['window','document','navigator','DOMParser','Node','Element','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLCanvasElement','SVGElement','MouseEvent','KeyboardEvent','Event','MutationObserver','localStorage','getComputedStyle','requestAnimationFrame','cancelAnimationFrame','__APP_VERSION__','__HOP_VERSION__'];
  const descriptors=new Map(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  for(const name of names){
    let value=dom.window[name];
    if(['getComputedStyle','requestAnimationFrame','cancelAnimationFrame'].includes(name))value=value.bind(dom.window);
    if(name.startsWith('__'))value='equation-focus-test';
    Object.defineProperty(globalThis,name,{value,configurable:true});
  }
  let wasm,handler,dialog,timers;
  t.after(()=>{
    dialog?.hide();handler?.dispose();wasm?.releaseDocument();dom.window.close();timers?.restore();
    for(const [name,descriptor] of descriptors)descriptor?Object.defineProperty(globalThis,name,descriptor):delete globalThis[name];
    for(const [path,hash] of immutableHashes)assert.equal(sha(readFileSync(path)),hash,'Source/candidate/native bytes unchanged: '+path);
  });
  const {WasmBridge}=await source('core/wasm-bridge.ts');
  const {EventBus}=await source('core/event-bus.ts');
  const {InputHandler}=await source('engine/input-handler.ts');
  const {VirtualScroll}=await source('view/virtual-scroll.ts');
  const {ViewportManager}=await source('view/viewport-manager.ts');
  const {EquationEditorDialog}=await source('ui/equation-editor-dialog.ts');
  // Owned INPUT setup finishes before the fresh full handler and its history.
  wasm=new WasmBridge();wasm.createNewDocument();wasm.insertText(0,0,0,'OWNED-BODY');
  const equation=wasm.insertEquation(0,0,10,SCRIPT,1000,0);assert.equal(equation.ok,true,'Native input equation exists');
  const eventBus=new EventBus(),virtualScroll=new VirtualScroll(),viewport=new ViewportManager(eventBus);
  virtualScroll.setPageDimensions(Array.from({length:wasm.pageCount},(_,i)=>wasm.getPageInfo(i)));
  handler=new InputHandler(document.getElementById('scroll-container'),wasm,eventBus,virtualScroll,viewport);
  dialog=new EquationEditorDialog(wasm,eventBus,{wasm,eventBus,getInputHandler:()=>handler});
  const state=()=>({bytes:Buffer.from(wasm.exportHwpx()),props:wasm.getEquationProperties(0,equation.paraIdx,equation.controlIdx),position:handler.getCursorPosition(),canUndo:handler.canUndo(),canRedo:handler.canRedo()});
  const before=state();assert.equal(before.props.script,SCRIPT);assert.equal(before.props.fontSize,1000);assert.equal(before.canUndo,false);assert.equal(before.canRedo,false);
  timers=timerBoundary();
  document.getElementById('outside').focus();
  const open=()=>dialog.open(0,equation.paraIdx,equation.controlIdx);
  open();
  const overlay=document.querySelector('.eq-dialog').parentElement,script=overlay.querySelector('.eq-script'),font=overlay.querySelector('.eq-props-row input[type=number]'),preview=overlay.querySelector('.eq-preview');
  const observer=new MutationObserver(()=>{});observer.observe(preview,{childList:true,subtree:true});t.after(()=>observer.disconnect());
  const assertPreview=()=>{
    const svg=preview.querySelector('svg');assert.ok(svg,'Valid callback renders an actual native equation SVG');
    const expected=new DOMParser().parseFromString(wasm.renderEquationPreview(SCRIPT,1000,0),'image/svg+xml').documentElement;
    assert.ok(svg.isEqualNode(document.importNode(expected,true)),'Preview DOM exactly matches the actual native script/font SVG');
  };
  const assertUnchanged=()=>{assert.deepEqual(state(),before,'Focus/preview cannot change native document, equation script/font, cursor, or real history');assert.equal(script.value,SCRIPT);assert.equal(font.value,'10');};
  return {dom,dialog,timers,open,overlay,script,font,preview,observer,assertPreview,assertUnchanged,outside:document.getElementById('outside')};
}

for(const [name,selector] of [
  ['font input','.eq-props-row input[type=number]'],
  ['symbol search','.eq-search-input'],
  ['confirm button','.dialog-footer .dialog-btn-primary'],
])test(`initial equation callback preserves focus owned by ${name}`,async t=>{
  const h=await harness(t),owner=h.overlay.querySelector(selector);owner.focus();assert.equal(document.activeElement,owner);
  h.timers.tick(50);
  assert.equal(document.activeElement,owner,'Pending initial focus must respect a user-owned dialog control');
  h.assertPreview();h.assertUnchanged();
});

test('idle initial callback focuses script and renders exact native preview without history',async t=>{
  const h=await harness(t);assert.equal(document.activeElement,h.outside);assert.equal(h.preview.childNodes.length,0);
  h.timers.tick(50);assert.equal(document.activeElement,h.script);h.assertPreview();h.assertUnchanged();
});

test('initial callback preserves an already focused script selection',async t=>{
  const h=await harness(t);h.script.focus();h.script.setSelectionRange(2,5);
  h.timers.tick(50);assert.equal(document.activeElement,h.script);assert.equal(h.script.selectionStart,2);assert.equal(h.script.selectionEnd,5);h.assertPreview();h.assertUnchanged();
});

test('hide cancels pending focus and preview before timer delivery',async t=>{
  const h=await harness(t);h.dialog.hide();h.outside.focus();
  assert.equal(h.timers.pending(50).length,0,'Closing cancels the actual initial task');
  h.timers.tick(50);assert.equal(document.activeElement,h.outside);assert.equal(h.observer.takeRecords().length,0,'Closed dialog receives no preview work');h.assertUnchanged();
});

test('a stale callback after hide/reopen cannot focus or preview the new opening',async t=>{
  const h=await harness(t),[old]=h.timers.pending(50);h.dialog.hide();h.open();h.font.focus();
  const current=h.timers.pending(50).at(-1);assert.notEqual(current,old);
  h.timers.deliver(old,{alreadyDequeued:true});assert.equal(document.activeElement,h.font,'Canceled opening cannot steal current focus');assert.equal(h.observer.takeRecords().length,0,'Canceled opening cannot render current preview');
  assert.deepEqual(h.timers.pending(50),[current],'Canceled opening cannot consume the new timer');
  h.timers.tick(50);assert.equal(document.activeElement,h.font);h.assertPreview();h.assertUnchanged();
});

test('a stale callback cannot erase the reopened timer handle used by hide',async t=>{
  const h=await harness(t),[old]=h.timers.pending(50);h.dialog.hide();h.open();
  h.timers.deliver(old,{alreadyDequeued:true});h.observer.takeRecords();
  h.dialog.hide();h.outside.focus();assert.equal(h.timers.pending(50).length,0,'New opening remains cancelable after stale delivery');
  h.timers.tick(50);assert.equal(document.activeElement,h.outside);assert.equal(h.observer.takeRecords().length,0);h.assertUnchanged();
});

test('opening the reusable dialog again cancels its previous initial task',async t=>{
  const h=await harness(t),[old]=h.timers.pending(50);h.open();h.font.focus();
  const pending=h.timers.pending(50);assert.equal(pending.length,1,'Exactly one current opening owns the task');assert.notEqual(pending[0],old);
  h.timers.deliver(old,{alreadyDequeued:true});assert.equal(document.activeElement,h.font);assert.equal(h.observer.takeRecords().length,0);
  h.timers.tick(50);assert.equal(document.activeElement,h.font);h.assertPreview();h.assertUnchanged();
});

test('a detached overlay receives no deferred focus or native preview',async t=>{
  const h=await harness(t);h.overlay.remove();h.outside.focus();h.timers.tick(50);
  assert.equal(document.activeElement,h.outside);assert.equal(h.observer.takeRecords().length,0,'Deferred callback requires the owning overlay to remain connected');h.assertUnchanged();
});
