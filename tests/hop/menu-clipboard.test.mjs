import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const hop=resolve(process.env.HOP_SOURCE??'.work/hop');
const upstream=(p)=>import(pathToFileURL(resolve(hop,'third_party/rhwp/rhwp-studio/src',p)));
const native=await import(pathToFileURL(resolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp.js')));
await native.default({module_or_path:readFileSync(resolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm'))});
const {WasmBridge}=await upstream('core/wasm-bridge.ts');
const {EventBus}=await upstream('core/event-bus.ts');
const {InputHandler}=await upstream('engine/input-handler.ts');
const {CursorState}=await upstream('engine/cursor.ts');
const {CommandHistory}=await upstream('engine/history.ts');
const {InsertTextCommand}=await upstream('engine/command.ts');
const {prepareRhwpInternalClipboardHtml}=await upstream('engine/input-handler-keyboard.ts');
const {editCommands}=await import(pathToFileURL(resolve(hop,'apps/studio-host/src/command/commands/edit.ts')));
const menu=editCommands.find(c=>c.id==='edit:paste');
const position=(charOffset=0)=>({sectionIndex:0,paragraphIndex:0,charOffset});
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');

// Browser clipboard reads/events, painting and image decode are external boundaries.
// The command, handler, cursor, bridge, native WASM, history and saved bytes are real.
function harness(t,text='MARKER|KEEP|') {
  const wasm=new WasmBridge();wasm.populateExternalImagesFromDevServer=async()=>{};
  wasm.createNewDocument();wasm.insertText(0,0,0,text);
  const cursor=new CursorState(wasm),history=new CommandHistory(),eventBus=new EventBus();
  cursor.moveTo(position([...text].length));
  const noop=()=>{},renderer={clear:noop,hide:noop,dispose:noop,render:noop,show:noop,update:noop};
  const listeners=new Set();
  const handler=Object.assign(Object.create(InputHandler.prototype),{
    active:true,editMode:'edit',wasm,cursor,history,eventBus,
    viewportManager:{getZoom:()=>1},selectionRenderer:renderer,caret:renderer,
    fieldMarker:renderer,caretLayoutReveal:{requestFor:noop,clear:noop},
    deferredPaginationRunner:{cancel:noop},_cellBlockLetterImeGuard:{reset:noop},
    _compositionFragment:null,rawTextMutationEffects:{reset:noop},
    textarea:{value:'',focus:noop,remove:noop,addEventListener:(type,fn)=>{if(type==='paste')listeners.add(fn);},removeEventListener:(type,fn)=>listeners.delete(fn)},
    container:{removeEventListener:noop},stopTextSelectionDragAutoScroll:noop,
    flushDeferredPaginationIfNeeded:noop,cancelDeferredPaginationFlush:noop,
    resetRawTextMutationEffects:noop,prepareTextMutationBeforeCursor:()=>false,
    clearTableResizeRuntimeCache:noop,updateCaret(){this.updateSelection();},
  });
  t.after(()=>{history.clear(wasm);wasm.borrowDocumentHandle()?.free();});
  const h={handler,wasm,cursor,history,eventBus,
    text:()=>JSON.parse(wasm.borrowDocumentHandle().getTextFileUnicode()).replaceAll('\r\n','\n'),
    bytes:()=>Buffer.from(wasm.borrowDocumentHandle().exportHwpx()),
    select(start=0,end=6){cursor.clearSelection();cursor.moveTo(position(start));cursor.setAnchor();cursor.moveTo(position(end));handler.updateSelection();},
    nativePaste(data){const event={preventDefault(){},clipboardData:data};for(const fn of listeners)fn(event);handler.onPaste(event);},
    paste(values){handler.onPaste({preventDefault(){},clipboardData:{getData:type=>values[type]??'',items:[]}});},
    replace(){wasm.createNewDocument();wasm.insertText(0,0,0,'NEW-DOCUMENT');handler.deactivate();handler.active=true;cursor.clearSelection();cursor.moveTo(position(3));handler.updateSelection();},
  };
  return h;
}

function browser(t,h,{command=false,clipboard,decode=Promise.resolve()}={}) {
  const originals=new Map(['navigator','document','DataTransfer','ClipboardEvent','Image','FileReader','requestAnimationFrame'].map(k=>[k,Object.getOwnPropertyDescriptor(globalThis,k)]));
  const defaultClipboard={async read(){return [{types:['text/plain'],getType:async()=>new Blob(['MARKER'],{type:'text/plain'})}];}};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:clipboard??defaultClipboard}});
  globalThis.document={removeEventListener(){},execCommand(name){assert.equal(name,'paste');return typeof command==='function'?command():command;}};
  globalThis.DataTransfer=class {
    values=new Map();items=[];
    constructor(){this.items.add=file=>this.items.push({kind:'file',type:file.type,getAsFile:()=>file});}
    setData(type,value){this.values.set(type,value);}
    getData(type){return this.values.get(type)??'';}
  };
  globalThis.ClipboardEvent=class {constructor(type,options){this.type=type;this.clipboardData=options.clipboardData;}preventDefault(){}};
  globalThis.Image=class {naturalWidth=1;naturalHeight=1;decode(){return decode;}};
  globalThis.FileReader=class {readAsDataURL(){queueMicrotask(()=>{this.result=`data:image/png;base64,${png.toString('base64')}`;this.onload();});}};
  globalThis.requestAnimationFrame=()=>0;
  t.after(()=>{for(const [key,value] of originals)value?Object.defineProperty(globalThis,key,value):delete globalThis[key];});
}
async function menuPaste(h){menu.execute({getInputHandler:()=>h.handler,wasm:h.wasm});for(let i=0;i<5;i++)await tick();}
function savedText(t,h){const saved=new native.HwpDocument(h.bytes());t.after(()=>saved.free());return JSON.parse(saved.getTextFileUnicode()).replaceAll('\r\n','\n');}
function oneUndoRedo(h,before,after){assert.equal(h.text(),after);h.history.undo(h.wasm);assert.equal(h.text(),before);assert.equal(h.history.canUndo(),false);h.history.redo(h.wasm);assert.equal(h.text(),after);}

for(const command of [false,true])test(`real menu + native WASM recover execCommand=${command} without a delivered paste`,async(t)=>{
  const h=harness(t);browser(t,h,{command});await menuPaste(h);
  assert.equal(h.text(),'MARKER|KEEP|MARKER');assert.equal(savedText(t,h),h.text());
  oneUndoRedo(h,'MARKER|KEEP|','MARKER|KEEP|MARKER');
});
test('a delivered native paste retains the original pipeline without a duplicate read',async(t)=>{
  const h=harness(t);browser(t,h,{command:()=>{h.nativePaste({getData:type=>type==='text/plain'?'NATIVE':'',items:[]});return false;},clipboard:{read(){throw Error('must not read after delivered event');}}});
  await menuPaste(h);oneUndoRedo(h,'MARKER|KEEP|','MARKER|KEEP|NATIVE');
});
test('real menu supports WebViews exposing only readText',async(t)=>{
  const h=harness(t);browser(t,h,{clipboard:{readText:async()=> '한글😀'}});await menuPaste(h);
  assert.equal(savedText(t,h),'MARKER|KEEP|한글😀');oneUndoRedo(h,'MARKER|KEEP|','MARKER|KEEP|한글😀');
});
test('real menu falls back to OS readText when rich read is unsupported',async(t)=>{
  const h=harness(t);browser(t,h,{clipboard:{read:async()=>{throw new Error('rich unavailable');},readText:async()=> 'PLAIN'}});await menuPaste(h);
  oneUndoRedo(h,'MARKER|KEEP|','MARKER|KEEP|PLAIN');
});
for(const [name,text] of [['selected plain','ONE'],['selected multiline','ONE\r\n한글😀\nTHREE']])test(`${name} restores replacement and all pasted lines with one undo`,(t)=>{
  const h=harness(t);browser(t,h);h.select();const before=h.text();h.paste({'text/plain':text});
  const after=h.text();assert.equal(after,text.replaceAll('\r\n','\n')+'|KEEP|');assert.equal(savedText(t,h),after);oneUndoRedo(h,before,after);
});
test('ordinary plain paste has one undo distinct from preceding typed text',t=>{
  const h=harness(t);browser(t,h);h.handler.executeOperation({kind:'command',command:new InsertTextCommand(h.cursor.getPosition(),'TYPED')});
  const before=h.text();h.paste({'text/plain':'PASTED'});assert.equal(savedText(t,h),before+'PASTED');
  h.history.undo(h.wasm);assert.equal(h.text(),before,'paste must not merge with prior keyboard input');
  h.history.undo(h.wasm);assert.equal(h.text(),'MARKER|KEEP|');
});
test('empty ordinary clipboard preserves selected text, bytes and history',t=>{
  const h=harness(t);browser(t,h);h.select();const before=h.bytes();h.paste({'text/plain':''});
  assert.equal(h.text(),'MARKER|KEEP|');assert.deepEqual(h.bytes(),before);assert.equal(h.history.canUndo(),false);assert.ok(h.cursor.hasSelection());
});
test('plain paste before a Home-exited field keeps subsequent typing outside that field',t=>{
  const h=harness(t,'TAIL');browser(t,h);
  const field=h.wasm.insertClickHereField(position(),'guide','memo','owned',true);assert.equal(field.ok,true);
  assert.equal(h.wasm.setFieldValue(field.fieldId,'FIELD').ok,true);h.cursor.moveTo(position());
  assert.equal(h.handler.markCurrentFieldStartOutside(),true);
  h.paste({'text/plain':'BEFORE'});h.handler.updateFieldMarkers();
  h.handler.executeOperation({kind:'command',command:new InsertTextCommand(h.cursor.getPosition(),'NEXT')});
  assert.equal(h.wasm.getFieldValue(field.fieldId).value,'FIELD','continued typing must remain before the field');
  assert.equal(h.wasm.getFieldList()[0].startCharIdx,10);
  h.history.undo(h.wasm);h.history.undo(h.wasm);assert.equal(h.wasm.getFieldList()[0].startCharIdx,0);
  assert.equal(h.wasm.getFieldValue(field.fieldId).value,'FIELD');
});
test('menu rich internal marker keeps copied bold formatting and one undo',async(t)=>{
  const h=harness(t);h.wasm.applyCharFormat(0,0,0,6,JSON.stringify({bold:true}));h.wasm.copySelection(0,0,0,0,6);
  const html=prepareRhwpInternalClipboardHtml(h.handler,h.wasm.exportSelectionHtml(0,0,0,0,6),'MARKER');
  browser(t,h,{clipboard:{read:async()=>[{types:['text/html','text/plain'],getType:async(type)=>new Blob([type==='text/html'?html:'MARKER'],{type})}]}});
  await menuPaste(h);assert.equal(h.text(),'MARKER|KEEP|MARKER');assert.equal(savedText(t,h),h.text());
  assert.equal(h.wasm.getCharPropertiesAt(0,0,12).bold,true);oneUndoRedo(h,'MARKER|KEEP|','MARKER|KEEP|MARKER');
});
test('menu HTML clipboard keeps rich text through the original native importer',async(t)=>{
  const h=harness(t);browser(t,h,{clipboard:{read:async()=>[{types:['text/html','text/plain'],getType:async(type)=>new Blob([type==='text/html'?'<p><b>RICH</b></p>':'RICH'],{type})}]}});
  await menuPaste(h);assert.ok(h.text().includes('RICH'));assert.equal(savedText(t,h),h.text());
  const after=h.text();oneUndoRedo(h,'MARKER|KEEP|',after);
});
test('menu image clipboard creates a saved picture with atomic replacement',async(t)=>{
  const h=harness(t);h.select();browser(t,h,{clipboard:{read:async()=>[{types:['image/png'],getType:async()=>new Blob([png],{type:'image/png'})}]}});
  await menuPaste(h);const after=h.text();assert.notEqual(after,'MARKER|KEEP|');
  const saved=new native.HwpDocument(h.bytes());t.after(()=>saved.free());
  const picture=JSON.parse(saved.getControls()).find(({userDesc})=>userDesc==='그림');assert.ok(picture);
  assert.deepEqual(Buffer.from(saved.getControlImageData(0,picture.para,'',picture.controlIndex)),png);oneUndoRedo(h,'MARKER|KEEP|',after);
});
test('menu advertised HTML and RTF preserve Office clipboard image bytes',async(t)=>{
  const h=harness(t);h.select();
  const values={'text/html':'<p>OFFICE</p><img src="file:///clip.png" width="1" height="1">','text/plain':'OFFICE','text/rtf':`{\\rtf1{\\pict\\pngblip ${png.toString('hex')}}}`};
  browser(t,h,{clipboard:{read:async()=>[{types:Object.keys(values),getType:async(type)=>new Blob([values[type]],{type})}]}});
  await menuPaste(h);assert.ok(h.text().includes('OFFICE'));
  const saved=new native.HwpDocument(h.bytes());t.after(()=>saved.free());
  const picture=JSON.parse(saved.getControls()).find(({userDesc})=>userDesc==='그림');assert.ok(picture);
  assert.deepEqual(Buffer.from(saved.getControlImageData(0,picture.para,'',picture.controlIndex)),png);oneUndoRedo(h,'MARKER|KEEP|',h.text());
});
test('clipboard read rejection preserves the document and original undo history',async(t)=>{
  const h=harness(t);h.select();const before=h.bytes();
  browser(t,h,{clipboard:{read:async()=>{throw new Error('OS clipboard denied');}}});
  await assert.rejects(h.handler.performPaste(),/OS clipboard denied/);
  assert.deepEqual(h.bytes(),before);assert.equal(h.history.canUndo(),false);assert.ok(h.cursor.hasSelection());
});
for(const boundary of ['read','blob'])for(const action of ['document replacement','selection change and return','close','form mode','user edit'])test(`menu ${boundary} completion cannot cross ${action}`,async(t)=>{
  const h=harness(t),wait=deferred();h.select();
  let started=false;
  const item={types:['text/plain'],getType:()=>{if(boundary==='blob')started=true;return boundary==='blob'?wait.promise:Promise.resolve(new Blob(['STALE']));}};
  browser(t,h,{clipboard:{read:()=>{if(boundary==='read')started=true;return boundary==='read'?wait.promise:Promise.resolve([item]);}}});
  const pending=h.handler.performPaste();await tick();
  assert.equal(started,true,'the real clipboard operation must reach the deferred external boundary');
  if(action==='document replacement')h.replace();
  if(action==='selection change and return'){h.select(2,8);h.select();}
  if(action==='close')h.handler.deactivate();
  if(action==='form mode')h.handler.setEditMode('form');
  if(action==='user edit'){h.cursor.clearSelection();h.handler.executeOperation({kind:'command',command:new InsertTextCommand(h.cursor.getPosition(),'USER')});}
  const before=h.bytes(),undo=h.history.peekUndoTop(),redo=h.history.peekRedoTop();
  wait.resolve(boundary==='read'?[item]:new Blob(['STALE']));assert.equal(await pending,false);await tick();
  assert.deepEqual(h.bytes(),before);assert.equal(h.history.peekUndoTop(),undo);assert.equal(h.history.peekRedoTop(),redo);
});
