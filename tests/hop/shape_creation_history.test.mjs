/** Routing contract only: real prepared commands/dispatcher/InputHandler/WASM/
 * internal history, with an owned synthetic DOM/event/layout boundary. No browser
 * renderer or native platform qualification. Run against unmodified source for
 * RED, then HOP_SHAPE_HISTORY_HANDLER=<patched source copy> for GREEN. */
import {prepared} from './shape_creation_history.loader.mjs';
import {createShapeHistoryDom,parseGeneratedXml} from './shape_creation_history.dom.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {inflateRawSync} from 'node:zlib';
import {createHash} from 'node:crypto';

const src=resolve(process.env.RHWP_SOURCE ?? resolve(prepared,'third_party/rhwp'),'rhwp-studio/src');
const native=await import(pathToFileURL(resolve(prepared,'apps/studio-host/vendor/rhwp-core/rhwp.js')));
const vendorWasm=resolve(prepared,'apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm');
await native.default({module_or_path:readFileSync(vendorWasm)});
const importSource=name=>import(pathToFileURL(resolve(src,name)));
const {WasmBridge}=await importSource('core/wasm-bridge.ts');
const {EventBus}=await importSource('core/event-bus.ts');
const {VirtualScroll}=await importSource('view/virtual-scroll.ts');
const {ViewportManager}=await importSource('view/viewport-manager.ts');

const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const immutableFiles=[vendorWasm,...['engine/input-handler.ts','engine/input-handler-mouse.ts','engine/history.ts','command/commands/insert.ts','core/wasm-bridge.ts'].map(name=>resolve(src,name))];
if(process.env.HOP_SHAPE_HISTORY_HANDLER)immutableFiles.push(resolve(process.env.HOP_SHAPE_HISTORY_HANDLER));
const immutableHashes=new Map(immutableFiles.map(path=>[path,sha(readFileSync(path))]));

// Read only the native engine's generated HWPX ZIP entry. No expected structure
// is manufactured by the test or inserted into the document.
function zipEntry(raw,name){
  const bytes=Buffer.from(raw);
  const end=bytes.lastIndexOf(Buffer.from([0x50,0x4b,0x05,0x06]));
  assert.ok(end>=0,'Native export must be a ZIP package');
  let cursor=bytes.readUInt32LE(end+16);
  for(let i=0;i<bytes.readUInt16LE(end+10);i++){
    assert.equal(bytes.readUInt32LE(cursor),0x02014b50,'Valid central directory');
    const method=bytes.readUInt16LE(cursor+10),length=bytes.readUInt32LE(cursor+20);
    const nameLength=bytes.readUInt16LE(cursor+28),extraLength=bytes.readUInt16LE(cursor+30),commentLength=bytes.readUInt16LE(cursor+32);
    const found=bytes.subarray(cursor+46,cursor+46+nameLength).toString('utf8');
    if(found===name){
      const local=bytes.readUInt32LE(cursor+42);
      const start=local+30+bytes.readUInt16LE(local+26)+bytes.readUInt16LE(local+28);
      const compressed=bytes.subarray(start,start+length);
      assert.ok(method===0||method===8,'Native ZIP uses supported compression');
      return (method===8?inflateRawSync(compressed):compressed).toString('utf8');
    }
    cursor+=46+nameLength+extraLength+commentLength;
  }
  throw new Error(`Native export omitted ${name}`);
}
function inspectExport(_dom,bytes){
  const xml=parseGeneratedXml(zipEntry(bytes,'Contents/section0.xml'));
  const all=node=>[node,...node.children.flatMap(all)];
  const text=node=>node.text+node.children.map(text).join('');
  const shapes=['rect','line','ellipse'].flatMap(kind=>all(xml).filter(node=>node.localName===kind).map(node=>{
    const size=node.children.find(child=>child.localName==='sz');
    return {kind,width:Number(size.attrs.width),height:Number(size.attrs.height),
      text:all(node).filter(child=>child.localName==='drawText').map(text).join(''),wrap:node.attrs.textWrap};
  }));
  const body=xml.children.filter(node=>node.localName==='p').flatMap(paragraph=>
    paragraph.children.filter(node=>node.localName==='run').flatMap(run=>
      run.children.filter(node=>node.localName==='t').map(text))).join('');
  return {shapes,body};
}

async function harness(t){
  const dom=createShapeHistoryDom();
  const globalNames=['window','document','navigator','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLCanvasElement','Element','MouseEvent','KeyboardEvent','Event','localStorage','getComputedStyle','requestAnimationFrame','cancelAnimationFrame','__APP_VERSION__','__HOP_VERSION__'];
  const originalSetTimeout=globalThis.setTimeout,timers=new Set();
  const descriptors=new Map(globalNames.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  for(const name of globalNames){
    let value=dom.window[name];
    if(['getComputedStyle','requestAnimationFrame','cancelAnimationFrame'].includes(name))value=value.bind(dom.window);
    if(name.startsWith('__'))value='shape-history-test';
    Object.defineProperty(globalThis,name,{value,configurable:true});
  }
  globalThis.setTimeout=(...args)=>{const timer=originalSetTimeout(...args);timers.add(timer);return timer;};
  // Load the actual modules only after the real DOM boundary exists.
  const {InputHandler}=await importSource('engine/input-handler.ts');
  const {insertCommands}=await importSource('command/commands/insert.ts');
  const {editCommands}=await import('@/command/commands/edit');
  const {viewCommands}=await importSource('command/commands/view.ts');
  const {CommandRegistry}=await importSource('command/registry.ts');
  const {CommandDispatcher}=await importSource('command/dispatcher.ts');
  // Input fixture setup only. The placement/edit under test starts later through
  // actual commands and DOM events, with a fresh real handler/history.
  const wasm=new WasmBridge();wasm.createNewDocument();wasm.insertText(0,0,0,'OWNED-BODY');
  const eventBus=new EventBus(),virtualScroll=new VirtualScroll(),viewport=new ViewportManager(eventBus);
  virtualScroll.setPageDimensions([wasm.getPageInfo(0)]);
  const container=document.getElementById('scroll-container'),content=document.getElementById('scroll-content'),canvas=content.querySelector('canvas');
  const rect={x:0,y:0,left:0,top:0,right:800,bottom:1200,width:800,height:1200,toJSON(){return this;}};
  for(const element of [container,content,canvas]){
    element.getBoundingClientRect=()=>rect;
    Object.defineProperty(element,'clientWidth',{value:800});Object.defineProperty(element,'clientHeight',{value:1200});
  }
  const handler=new InputHandler(container,wasm,eventBus,virtualScroll,viewport);
  handler.activateWithCaretPosition();
  let mode='normal';
  const registry=new CommandRegistry();registry.registerAll(insertCommands);
  registry.registerAll(editCommands.filter(command=>['edit:undo','edit:redo'].includes(command.id)));
  registry.registerAll(viewCommands.filter(command=>command.id==='view:form-mode'));
  const context=()=>({hasDocument:wasm.pageCount>0,hasSelection:handler.hasSelection(),inTable:handler.isInTable(),inCellSelectionMode:handler.isInCellSelectionMode(),inPictureObjectSelection:handler.isInPictureObjectSelection(),inField:handler.isInField(),isEditable:mode!=='form',editMode:mode,isFormMode:mode==='form',canEditFormField:handler.canEditCurrentFormField(),canUndo:handler.canUndo(),canRedo:handler.canRedo(),zoom:1,showControlCodes:false,showParagraphMarks:false});
  const services={wasm,eventBus,getInputHandler:()=>handler,getContext:context,getViewportManager:()=>viewport,setEditMode(next){mode=next;handler.setEditMode(next);}};
  const dispatcher=new CommandDispatcher(registry,services,eventBus);handler.setDispatcher(dispatcher);
  const commandResults=new Map();
  for(const button of document.querySelectorAll('button[data-cmd]'))button.addEventListener('click',()=>commandResults.set(button.dataset.cmd,dispatcher.dispatchWithResult(button.dataset.cmd)));
  const clickCommand=id=>{document.querySelector(`button[data-cmd="${id}"]`).click();return commandResults.get(id);};
  const mouse=(type,x,y)=>canvas.dispatchEvent(new dom.window.MouseEvent(type,{bubbles:true,button:0,buttons:type==='mouseup'?0:1,clientX:x,clientY:y}));
  const keyboard=key=>document.querySelector('textarea[aria-label="문서 편집 입력"]').dispatchEvent(new dom.window.KeyboardEvent('keydown',{bubbles:true,key,code:key}));
  const begin=kind=>{
    const result=clickCommand(kind==='textbox'?'insert:textbox':'insert:shape');
    assert.equal(result.ok,true,'Actual insertion command accepted');
    if(kind!=='textbox'){
      const title=kind==='line'?'직선':'사각형';
      const button=Array.from(document.querySelectorAll('.shape-picker-btn')).find(node=>node.title===title);
      assert.ok(button,'Real picker exposes requested shape');button.click();
    }
    assert.equal(container.style.cursor,'crosshair');
  };
  t.after(()=>{
    for(const timer of timers)clearTimeout(timer);globalThis.setTimeout=originalSetTimeout;
    handler.dispose();wasm.releaseDocument();dom.window.close();
    for(const [name,descriptor] of descriptors)descriptor?Object.defineProperty(globalThis,name,descriptor):delete globalThis[name];
    for(const [path,hash] of immutableHashes)assert.equal(sha(readFileSync(path)),hash,'Source/WASM bytes must remain unchanged: '+path);
  });
  return {dom,wasm,handler,container,canvas,begin,mouse,keyboard,clickCommand,
    export:()=>wasm.exportHwpx(),inspect:bytes=>inspectExport(dom,bytes),
    place(kind,{drag=true,x=200,y=250,endX=350,endY=325}={}){begin(kind);mouse('mousedown',x,y);if(drag)mouse('mousemove',endX,endY);mouse('mouseup',endX,endY);assert.equal(container.style.cursor,'');},
  };
}

for(const kind of ['textbox','rectangle','line'])test(`${kind} placement enters real history; public undo/redo and saved reopen preserve shape`,async t=>{
  const h=await harness(t);const before=h.export();
  assert.equal(h.handler.canUndo(),false);assert.equal(h.inspect(before).shapes.length,0);
  h.place(kind);const created=h.export(),expected=h.inspect(created);
  assert.equal(expected.shapes.length,1);assert.equal(expected.shapes[0].kind,kind==='line'?'line':'rect');
  assert.equal(expected.shapes[0].width,11250);assert.equal(expected.shapes[0].height,5625);assert.equal(expected.body,'OWNED-BODY');
  assert.equal(h.handler.canUndo(),true,'Shape creation must record a real undo entry');
  assert.equal(h.clickCommand('edit:undo').ok,true);assert.deepEqual(h.inspect(h.export()),h.inspect(before));
  assert.equal(h.handler.canRedo(),true);assert.equal(h.clickCommand('edit:redo').ok,true);
  const redone=h.export();assert.deepEqual(h.inspect(redone),expected);
  // Actual HWPX parser/reopen through the real bridge, not test-generated XML.
  const reopened=new WasmBridge();try{reopened.loadDocument(redone,'owned-shape.hwpx');assert.deepEqual(h.inspect(reopened.exportHwpx()),expected);}finally{reopened.releaseDocument();}
});

for(const kind of ['textbox','rectangle','line'])test(`${kind} click-only default preserves dimensions including zero-height line`,async t=>{
  const h=await harness(t);h.place(kind,{drag:false,endX:200,endY:250});
  const [shape]=h.inspect(h.export()).shapes;
  assert.equal(shape.width,Math.round(30*96/25.4*75));
  assert.equal(shape.height,kind==='line'?0:shape.width);
  assert.equal(h.handler.canUndo(),true);assert.equal(h.clickCommand('edit:undo').ok,true);assert.equal(h.inspect(h.export()).shapes.length,0);
  assert.equal(h.clickCommand('edit:redo').ok,true);assert.deepEqual(h.inspect(h.export()).shapes,[shape]);
});

test('Escape cancellation preserves actual document bytes and empty history',async t=>{
  const h=await harness(t);const before=h.export();h.begin('textbox');h.mouse('mousedown',200,250);h.keyboard('Escape');
  h.mouse('mouseup',350,325);assert.equal(h.container.style.cursor,'');assert.deepEqual(h.export(),before);
  assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
});

test('zero-motion gesture preserves textbox click default rather than zero-size mutation',async t=>{
  const h=await harness(t);h.place('textbox',{endX:200,endY:250});
  const [shape]=h.inspect(h.export()).shapes;assert.equal(shape.width,8504);assert.equal(shape.height,8504);
  assert.equal(h.handler.canUndo(),true);
});

test('form mode blocks public creation without document/history mutation',async t=>{
  const h=await harness(t);const before=h.export();assert.equal(h.clickCommand('view:form-mode').ok,true);
  assert.deepEqual(h.clickCommand('insert:textbox'),{ok:false,reason:'blocked-in-form-mode'});
  assert.deepEqual(h.export(),before);assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
});

test('form mode entered during pending placement drops real mutation and creates no snapshot',async t=>{
  const h=await harness(t);const before=h.export();h.begin('textbox');h.mouse('mousedown',200,250);
  assert.equal(h.clickCommand('view:form-mode').ok,true);h.mouse('mousemove',350,325);h.mouse('mouseup',350,325);
  assert.deepEqual(h.export(),before,'Router gate must prevent in-progress placement mutation');
  assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);assert.equal(h.container.style.cursor,'');
});

test('public command rejects missing real document without history mutation',async t=>{
  const h=await harness(t);h.wasm.releaseDocument();
  assert.deepEqual(h.clickCommand('insert:textbox'),{ok:false,reason:'disabled'});
  assert.equal(h.wasm.hasLoadedDocument(),false);assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
});

test('pending placement with a released real document fails without history entry',async t=>{
  const h=await harness(t);h.begin('textbox');h.mouse('mousedown',200,250);h.mouse('mousemove',350,325);
  // A real closed-document context: snapshot creation rejects in the actual
  // WASM bridge. No engine method/result or history object is replaced.
  h.wasm.releaseDocument();h.mouse('mouseup',350,325);
  assert.equal(h.wasm.hasLoadedDocument(),false);assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
  assert.equal(h.container.style.cursor,'');
});

function replacementInput(text){
  const fixture=new WasmBridge();
  try{fixture.createNewDocument();fixture.insertText(0,0,0,text);return fixture.exportHwpx();}
  finally{fixture.releaseDocument();}
}

for(const kind of ['textbox','rectangle','line'])test(`${kind} pending placement cannot cross A to B document replacement`,async t=>{
  const h=await harness(t),a=h.export(),b=replacementInput('OWNED-DOCUMENT-B');
  const hashes=[sha(a),sha(b)];h.begin(kind);
  h.wasm.loadDocument(b,'owned-b.hwpx');h.handler.deactivate();h.handler.activateWithCaretPosition();
  h.mouse('mousedown',200,250);h.mouse('mousemove',350,325);h.mouse('mouseup',350,325);
  assert.deepEqual(h.inspect(h.export()),{shapes:[],body:'OWNED-DOCUMENT-B'});
  assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
  assert.deepEqual([sha(a),sha(b)],hashes);assert.equal(h.container.style.cursor,'');
});

test('pending textbox placement remains cancelled after A to B to A replacement',async t=>{
  const h=await harness(t),a=h.export(),b=replacementInput('OWNED-DOCUMENT-B');
  const hashes=[sha(a),sha(b)];h.begin('textbox');
  for(const [bytes,name] of [[b,'owned-b.hwpx'],[a,'owned-a.hwpx']]){
    h.wasm.loadDocument(bytes,name);h.handler.deactivate();h.handler.activateWithCaretPosition();
  }
  h.mouse('mousedown',200,250);h.mouse('mousemove',350,325);h.mouse('mouseup',350,325);
  assert.deepEqual(h.inspect(h.export()),{shapes:[],body:'OWNED-BODY'});
  assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
  assert.deepEqual([sha(a),sha(b)],hashes);assert.equal(h.container.style.cursor,'');
});

test('pending textbox drag is cancelled on deactivation before replacement',async t=>{
  const h=await harness(t),before=h.export();h.begin('textbox');h.mouse('mousedown',200,250);h.mouse('mousemove',350,325);
  h.handler.deactivate();h.handler.activateWithCaretPosition();h.mouse('mouseup',350,325);
  assert.deepEqual(h.export(),before);assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
  assert.equal(h.container.style.cursor,'');
});

test('disposed handler clears pending shape gesture without mutation/history',async t=>{
  const h=await harness(t),before=h.export();h.begin('textbox');h.mouse('mousedown',200,250);h.mouse('mousemove',350,325);
  h.handler.dispose();h.mouse('mouseup',350,325);h.mouse('mousedown',200,250);h.mouse('mouseup',350,325);
  assert.deepEqual(h.export(),before);assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
  assert.equal(h.container.style.cursor,'');
});
