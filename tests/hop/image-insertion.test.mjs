import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const hop=resolve(process.env.HOP_SOURCE ?? '.work/hop');
const rhwp=resolve(process.env.RHWP_SOURCE ?? `${hop}/third_party/rhwp`);
const upstream=(path)=>import(pathToFileURL(resolve(rhwp,'rhwp-studio/src',path)));
const native=await import(pathToFileURL(resolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp.js')));
await native.default({module_or_path:readFileSync(resolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm'))});
const {insertCommands}=await upstream('command/commands/insert.ts');
const {WasmBridge}=await upstream('core/wasm-bridge.ts');
const {EventBus}=await upstream('core/event-bus.ts');
const {InputHandler}=await upstream('engine/input-handler.ts');
const {CursorState}=await upstream('engine/cursor.ts');
const {CommandHistory}=await upstream('engine/history.ts');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
const pngBuffer=()=>png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength);
const position=(charOffset=0)=>({sectionIndex:0,paragraphIndex:0,charOffset});
const tick=()=>new Promise((resolve)=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
const noop=()=>{};

// File chooser, browser image decoding and rendering are external boundaries.
// Commands, lifecycle, mouse handlers, hitTest, document generations/handles,
// insertPicture, snapshots/history and saved/reopened image bytes are real.
function browser(t,{bytes,decode}={}) {
  const keys=['document','Image','requestAnimationFrame','setTimeout'];
  const originals=new Map(keys.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  const create=URL.createObjectURL,revoke=URL.revokeObjectURL,timer=globalThis.setTimeout;
  let input,created=0,revoked=0,reads=0,images=0;
  const timers=[];
  const listeners=new Map();
  const element=()=>({style:{},setAttribute:noop,appendChild:noop,addEventListener:noop,
    removeEventListener:noop,remove(){this.removed=true;},click:noop});
  globalThis.document={body:element(),getElementById:()=>null,
    addEventListener(type,callback,options){if(!listeners.has(type))listeners.set(type,new Map());listeners.get(type).set(callback,options);},
    removeEventListener(type,callback){listeners.get(type)?.delete(callback);},
    dispatchEvent(event){for(const [callback,options] of [...(listeners.get(event.type) ?? [])]){if(options?.once)listeners.get(event.type).delete(callback);callback(event);}},
    createElement(tag){const result=element();if(tag==='input')input=result;return result;}};
  globalThis.requestAnimationFrame=fn=>{fn();return 1;};
  globalThis.setTimeout=(...args)=>{const id=timer(...args);id.unref();timers.push(id);return id;};
  globalThis.Image=class {
    naturalWidth=1;naturalHeight=1;
    set src(value){images++;(decode?.promise ?? Promise.resolve()).then(()=>this.onload(),()=>this.onerror());}
  };
  URL.createObjectURL=()=>{created++;return 'blob:image-insertion-regression';};
  URL.revokeObjectURL=()=>{revoked++;};
  const file={name:'owned-1px.png',arrayBuffer(){reads++;return bytes?.promise ?? Promise.resolve(pngBuffer());}};
  t.after(()=>{timers.forEach(clearTimeout);for(const [key,value] of originals)value?Object.defineProperty(globalThis,key,value):delete globalThis[key];URL.createObjectURL=create;URL.revokeObjectURL=revoke;});
  return {choose(files=[file]){input.files=files;return input.onchange();},
    created:()=>created,revoked:()=>revoked,reads:()=>reads,images:()=>images,
    mouseUpListeners:()=>listeners.get('mouseup')?.size ?? 0};
}

function harness(t) {
  const wasm=new WasmBridge();
  wasm.populateExternalImagesFromDevServer=async()=>{}; // Vite dev-only external fetch.
  wasm.createNewDocument();wasm.insertText(0,0,0,'DOCUMENT-A-SELECTED');
  const cursor=new CursorState(wasm),history=new CommandHistory(),eventBus=new EventBus();
  const renderer={clear:noop,hide:noop,dispose:noop,render:noop,show:noop,update:noop};
  const content={clientWidth:800,getBoundingClientRect:()=>({left:0,top:0})};
  const handler=Object.assign(Object.create(InputHandler.prototype),{
    active:true,editMode:'edit',wasm,cursor,history,eventBus,imagePlacementMode:false,
    imagePlacementData:null,imagePlacementDrag:null,imagePlacementOverlay:null,
    imageInsertionLifecycle:0,imagePlacementContext:null,
    viewportManager:{getZoom:()=>1},selectionRenderer:renderer,caret:renderer,fieldMarker:renderer,
    caretLayoutReveal:{requestFor:noop,clear:noop},deferredPaginationRunner:{cancel:noop},
    _cellBlockLetterImeGuard:{reset:noop},_compositionFragment:null,
    textarea:{value:'',removeEventListener:noop,remove:noop,focus:noop},
    container:{clientWidth:800,clientHeight:1200,style:{},querySelector:()=>content,
      getBoundingClientRect:()=>({left:0,top:0}),removeEventListener:noop},
    virtualScroll:{getPageAtPoint:()=>0,getPageOffset:()=>0,getPageWidth:()=>800,getPageLeftResolved:()=>0},
    rawTextMutationEffects:{reset:noop},flushDeferredPaginationIfNeeded:noop,
    cancelDeferredPaginationFlush:noop,resetRawTextMutationEffects:noop,
    prepareTextMutationBeforeCursor:()=>false,clearTableResizeRuntimeCache:noop,
    stopTextSelectionDragAutoScroll:noop,canEditHyperlink:()=>false,
    updateFieldMarkers:noop,prepareClickHerePointerEntry:noop,
    updateCaret(){this.updateSelection();},
  });
  handler.onMouseUpBound=handler.onMouseUp.bind(handler);
  let currentHandler=handler;
  const calls=[],insert=wasm.insertPicture.bind(wasm);
  wasm.insertPicture=(...args)=>{calls.push({generation:wasm.documentGeneration,position:args.slice(0,3),size:args.slice(5,7)});return insert(...args);};
  const select=(start=0,end=10)=>{cursor.clearSelection();cursor.moveTo(position(start));cursor.setAnchor();cursor.moveTo(position(end));handler.updateSelection();};
  select();
  t.after(()=>{history.clear(wasm);wasm.borrowDocumentHandle()?.free();});
  const pointer=(x,y)=>({clientX:x,clientY:y,button:0,shiftKey:false,ctrlKey:false,metaKey:false,altKey:false,
    preventDefault:noop,target:{closest:()=>null}});
  const clickPoint=()=>{wasm.getPageLayerTreeObject(0);const locator=new CursorState(wasm);locator.moveTo(position(14));const rect=locator.getRect();assert.ok(rect);return pointer(rect.x,rect.y+4);};
  const start=()=>handler.onClick(clickPoint());
  const finish=(drag=false)=>{
    const event=clickPoint();
    if(!handler.imagePlacementDrag)handler.onClick(event);
    if(drag){event.clientX+=30;event.clientY+=20;handler.onMouseMove(event);assert.equal(handler.imagePlacementDrag.isDragging,true);}
    const hit=handler.hitTestFromEvent(event);assert.ok(hit,'native hitTest must find the follow-up mouse location');
    document.dispatchEvent({...event,type:'mouseup'});return hit;
  };
  return {handler,wasm,cursor,history,eventBus,calls,select,start,finish,
    command(){insertCommands.find(c=>c.id==='insert:image').execute({wasm,getInputHandler:()=>currentHandler});},
    replaceHandler(){currentHandler=Object.create(InputHandler.prototype);},
    text:()=>wasm.borrowDocumentHandle().getTextFileText(),
    bytes:()=>Buffer.from(wasm.borrowDocumentHandle().exportHwpx()),
    pictures:()=>JSON.parse(wasm.borrowDocumentHandle().getControls()).filter(({userDesc})=>userDesc==='그림'),
    replace(){wasm.createNewDocument();wasm.insertText(0,0,0,'DOCUMENT-B-TARGET');handler.deactivate();handler.active=true;select();},
    reopen(){const saved=this.bytes();wasm.loadDocument(saved,'same.hwpx');handler.deactivate();handler.active=true;select();},
  };
}

function cleanPlacement(h) {
  assert.equal(h.handler.imagePlacementMode,false,'stale insertion must not enter placement');
  assert.equal(h.handler.imagePlacementData,null);
  assert.equal(h.handler.imagePlacementDrag,null);
  assert.equal(h.handler.imagePlacementOverlay,null);
  assert.equal(h.handler.container.style.cursor ?? '','');
}
const subscriptions=h=>[...h.eventBus.handlers.values()].reduce((sum,set)=>sum+set.size,0);
function unchanged(h,before) {
  assert.equal(h.text(),before.text);assert.ok(h.bytes().equals(before.bytes),'stale insertion changed saved HWPX bytes');
  assert.equal(h.history.peekUndoTop(),before.undo);assert.equal(h.history.peekRedoTop(),before.redo);
  assert.equal(h.calls.length,0,'stale insertion called native insertPicture');
}
const snapshot=h=>({text:h.text(),bytes:h.bytes(),undo:h.history.peekUndoTop(),redo:h.history.peekRedoTop()});

for(const gate of ['chooser','arrayBuffer','decode','already-ready']) {
  test(`insert:image: document replacement at ${gate} cancels before follow-up click`,async(t)=>{
    const bytes=deferred(),decode=deferred(),b=browser(t,{bytes,decode}),h=harness(t),count=subscriptions(h);
    h.command();if(gate==='chooser')h.replace();
    const work=b.choose();if(gate==='arrayBuffer')h.replace();
    bytes.resolve(pngBuffer());await tick();if(gate==='decode')h.replace();
    decode.resolve();await work;
    if(gate==='already-ready'){assert.equal(h.handler.imagePlacementMode,true);h.replace();}
    const before=snapshot(h);h.finish();
    unchanged(h,before);cleanPlacement(h);assert.equal(subscriptions(h),count);assert.equal(b.revoked(),b.created());
  });
}

for(const [name,change] of Object.entries({
  'close and reactivate':h=>{h.handler.deactivate();h.handler.active=true;h.select();},
  'reopen identical bytes':h=>h.reopen(),
  'dispose':h=>h.handler.dispose(),
  'replace input handler':h=>h.replaceHandler(),
  'replace native document without deactivation':h=>{h.wasm.createNewDocument();h.wasm.insertText(0,0,0,'DOCUMENT-B-TARGET');h.select();},
})) {
  test(`insert:image: pending decode cancels on ${name}`,async(t)=>{
    const decode=deferred(),b=browser(t,{decode}),h=harness(t),count=subscriptions(h);
    h.command();const work=b.choose();await tick();assert.equal(b.images(),1);
    change(h);const before=snapshot(h);decode.resolve();await work;
    cleanPlacement(h);unchanged(h,before);assert.equal(subscriptions(h),count);assert.equal(b.created(),1);assert.equal(b.revoked(),1);
  });
}

for(const [name,change] of Object.entries({replacement:h=>h.replace(),reopen:h=>h.reopen(),
  deactivation:h=>h.handler.deactivate(),dispose:h=>h.handler.dispose(),
  'native replacement':h=>{h.wasm.createNewDocument();h.wasm.insertText(0,0,0,'DOCUMENT-B-TARGET');},
  'input handler replacement':h=>h.replaceHandler(),
})) {
  test(`insert:image: ${name} cancels an actual placement drag and removes overlay`,async(t)=>{
    const b=browser(t),h=harness(t);h.command();await b.choose();h.start();
    h.handler.onMouseMove({clientX:200,clientY:150});
    assert.equal(h.handler.imagePlacementDrag.isDragging,true);
    const overlay=h.handler.imagePlacementOverlay;assert.ok(overlay);
    change(h);
    if(!['native replacement','input handler replacement'].includes(name)) {
      cleanPlacement(h);assert.equal(b.mouseUpListeners(),0,'lifecycle must release the pending mouseup listener immediately');
      assert.equal(overlay.removed,true);
    }
    const before=snapshot(h);h.finish();
    unchanged(h,before);cleanPlacement(h);assert.equal(overlay.removed,true);assert.equal(b.created(),b.revoked());
  });
}

for(const gate of ['normal click','normal drag','arrayBuffer selection change','decode selection change','ready selection change']) {
  test(`insert:image: ${gate} preserves native placement, one undo/redo and original PNG after reopen`,async(t)=>{
    const bytes=deferred(),decode=deferred(),b=browser(t,{bytes,decode}),h=harness(t),count=subscriptions(h);
    const originalText=h.text();h.command();const work=b.choose();
    if(gate==='arrayBuffer selection change')h.select(2,12);
    bytes.resolve(pngBuffer());await tick();if(gate==='decode selection change')h.select(2,12);
    decode.resolve();await work;if(gate==='ready selection change')h.select(2,12);
    assert.equal(h.handler.imagePlacementMode,true);
    const selected=h.cursor.getSelection();assert.ok(selected);
    const hit=h.finish(gate==='normal drag'),saved=h.bytes();
    assert.notEqual(hit.charOffset,selected.focus.charOffset,'follow-up hitTest must determine insertion, independently of the selection');
    assert.equal(h.pictures().length,1);assert.equal(h.text(),originalText,'file image placement must preserve selected text');
    assert.deepEqual(h.calls[0].position,[hit.sectionIndex,hit.paragraphIndex,hit.charOffset]);
    assert.deepEqual(h.calls[0].size,gate==='normal drag'?[2250,1500]:[75,75]);
    cleanPlacement(h);assert.equal(b.mouseUpListeners(),0);assert.equal(h.history.canUndo(),true);h.history.undo(h.wasm);
    assert.equal(h.pictures().length,0);assert.equal(h.text(),originalText);assert.equal(h.history.canUndo(),false);
    h.history.redo(h.wasm);assert.equal(h.pictures().length,1);assert.equal(h.text(),originalText);
    const reopened=new native.HwpDocument(saved);t.after(()=>reopened.free());
    const picture=JSON.parse(reopened.getControls()).find(({userDesc})=>userDesc==='그림');assert.ok(picture);
    assert.equal(reopened.getTextFileText(),originalText);
    assert.deepEqual(Buffer.from(reopened.getControlImageData(0,picture.para,'',picture.controlIndex)),png);
    assert.equal(subscriptions(h),count);assert.equal(b.created(),1);assert.equal(b.revoked(),1);
  });
}

test('insert:image: Escape cancels the real pending drag before another document click',async(t)=>{
  const b=browser(t),h=harness(t);h.command();await b.choose();h.start();
  const overlay=h.handler.imagePlacementOverlay;assert.ok(overlay);
  h.handler.onKeyDown({key:'Escape',preventDefault:noop,stopPropagation:noop});
  cleanPlacement(h);assert.equal(b.mouseUpListeners(),0);assert.equal(overlay.removed,true);h.replace();const before=snapshot(h);h.finish();unchanged(h,before);
});

test('insert:image: empty file chooser result neither reads bytes nor enters placement',async(t)=>{
  const b=browser(t),h=harness(t),count=subscriptions(h);h.command();await b.choose([]);
  cleanPlacement(h);h.replace();const before=snapshot(h);h.finish();unchanged(h,before);
  assert.equal(b.reads(),0);assert.equal(b.created(),0);assert.equal(subscriptions(h),count);
});

test('insert:image: failed browser decode releases its object URL and leaves document/history untouched',async(t)=>{
  const decode=deferred(),b=browser(t,{decode}),h=harness(t),count=subscriptions(h),before=snapshot(h);
  const warn=console.warn;console.warn=noop;t.after(()=>{console.warn=warn;});
  h.command();const work=b.choose();await tick();decode.reject(new Error('synthetic browser decode failure'));await work;
  cleanPlacement(h);unchanged(h,before);assert.equal(b.created(),1);assert.equal(b.revoked(),1);assert.equal(subscriptions(h),count);
});
