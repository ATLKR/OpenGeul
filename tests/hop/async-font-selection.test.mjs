import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {inflateRawSync} from 'node:zlib';

// Only the native IPC transport is replaced. The installed-only font loader,
// local-font dispatch, native document, formatter, cursor and history stay real.
registerHooks({resolve(specifier,context,next){
  if(specifier==='@tauri-apps/api/core')return {
    url:'data:text/javascript,'+encodeURIComponent('export const invoke = (command, args) => globalThis.__ownedFontInvoke(command, args);'),
    shortCircuit:true,
  };
  return next(specifier,context);
}});
const hop=resolve(process.env.HOP_SOURCE ?? '.work/hop');
const rhwp=resolve(process.env.RHWP_SOURCE ?? `${hop}/third_party/rhwp`);
const upstream=path=>import(pathToFileURL(resolve(rhwp,'rhwp-studio/src',path)));
const host=path=>import(pathToFileURL(resolve(hop,'apps/studio-host/src',path)));
const native=await import(pathToFileURL(resolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp.js')));
await native.default({module_or_path:readFileSync(resolve(hop,'apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm'))});
const {WasmBridge}=await upstream('core/wasm-bridge.ts');
const {EventBus}=await upstream('core/event-bus.ts');
const {InputHandler}=await upstream('engine/input-handler.ts');
const {CursorState}=await upstream('engine/cursor.ts');
const {CommandHistory}=await upstream('engine/history.ts');
const {Toolbar}=await host('ui/toolbar.ts');
const {resetDesktopFonts}=await host('core/desktop-local-fonts.ts');
const {FONT_LIST}=await host('core/font-catalog.ts');
const font='SYNTHETIC-TARGET-FONT';
const otherFont='SYNTHETIC-LATEST-FONT';
const noop=()=>{};
const position=(charOffset=0)=>({sectionIndex:0,paragraphIndex:0,charOffset});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
const key=key=>({key,code:key,preventDefault:noop,shiftKey:false,ctrlKey:false,altKey:false,metaKey:false,isComposing:false,keyCode:0});
const subscriptions=h=>[...h.eventBus.handlers.values()].reduce((count,entries)=>count+entries.size,0);

function element() {
  const listeners=new Map();
  return {value:'',style:{},children:[],classList:{toggle:noop},
    appendChild(child){this.children.push(child);},insertBefore(child){this.children.unshift(child);},
    replaceChildren(){this.children=[];},querySelector:()=>null,querySelectorAll:()=>[],
    addEventListener(type,fn){listeners.set(type,fn);},removeEventListener:noop,remove:noop,
    dispatch(type,event={}){listeners.get(type)?.(event);},setAttribute:noop};
}

function boundaries(t,gate='read') {
  const originals=new Map(['window','document','FontFace','CSS','__ownedFontInvoke'].map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  const read=deferred(),face=deferred(),trace=[];
  globalThis.window={__TAURI_INTERNALS__:{},location:{protocol:'tauri:',search:''}};
  globalThis.CSS={escape:value=>value};
  globalThis.document={documentElement:{lang:'ko'},head:element(),createElement:element,
    addEventListener:noop,removeEventListener:noop,fonts:{add:noop,delete:noop,check:()=>true}};
  globalThis.__ownedFontInvoke=async(command,args)=>{
    trace.push({command,args});
    if(command==='list_local_fonts')return [font,otherFont].map(family=>({family,postScriptName:family,style:'normal',sourceKind:'file-backed',path:`/owned/${family}.ttf`}));
    if(command==='read_local_font'){if(gate==='read')await read.promise;return [0,1,2,3];}
    throw Error(`unexpected native command ${command}`);
  };
  globalThis.FontFace=class {
    constructor(family,bytes){this.family=family;assert.ok(bytes instanceof Uint8Array);}
    async load(){trace.push({command:'FontFace.load',family:this.family});if(gate==='face')await face.promise;return this;}
  };
  resetDesktopFonts();
  t.after(()=>{resetDesktopFonts();for(const [name,value] of originals)value?Object.defineProperty(globalThis,name,value):delete globalThis[name];});
  return {trace,release(){read.resolve();face.resolve();},async pending(){
    const expected=gate==='face'?'FontFace.load':'read_local_font';
    for(let turn=0;turn<40&&!trace.some(entry=>entry.command===expected);turn++)await tick();
    assert.ok(trace.some(entry=>entry.command===expected),`actual installed font ${expected} boundary must be pending`);
    assert.deepEqual(FONT_LIST,[],'offline installed-only catalog must stay empty');
  }};
}

function harness(t) {
  const wasm=new WasmBridge();
  wasm.populateExternalImagesFromDevServer=async()=>{}; // Vite-only fetch outside the offline test.
  wasm.createNewDocument();wasm.insertText(0,0,0,'FIRST SECOND');
  const cursor=new CursorState(wasm),history=new CommandHistory(),eventBus=new EventBus();
  const renderer={clear:noop,hide:noop,dispose:noop,render:noop,show:noop,update:noop};
  const handler=Object.assign(Object.create(InputHandler.prototype),{
    active:true,editMode:'edit',wasm,cursor,history,eventBus,
    viewportManager:{getZoom:()=>1,getViewportSize:()=>({width:800,height:1200}),getScrollY:()=>0,getScrollX:()=>0},
    virtualScroll:{getVisiblePages:()=>[0]},selectionRenderer:renderer,cellSelectionRenderer:renderer,
    caret:renderer,fieldMarker:renderer,caretLayoutReveal:{requestFor:noop,clear:noop},
    deferredPaginationRunner:{cancel:noop},_cellBlockLetterImeGuard:{reset:noop},_compositionFragment:null,
    textarea:{value:'',removeEventListener:noop,remove:noop,focus:noop},container:{removeEventListener:noop},
    rawTextMutationEffects:{reset:noop},flushDeferredPaginationIfNeeded:noop,cancelDeferredPaginationFlush:noop,
    resetRawTextMutationEffects:noop,prepareTextMutationBeforeCursor:()=>false,
    clearTableResizeRuntimeCache:noop,stopTextSelectionDragAutoScroll:noop,
    updateCaret(){this.updateSelection();},
  });
  // These are the real constructor's event delivery conditions, with its DOM
  // rendering initialization omitted. applyCharFormat/executeOperation are real.
  eventBus.on('format-char',props=>{if(handler.active&&handler.editMode!=='form')handler.applyCharFormat(props);});
  const toolbar=Object.assign(Object.create(Toolbar.prototype),{
    wasm,eventBus,fontApplyRequestId:0,fontLang:element(),fontName:element(),fontSize:element(),
    btnSizeUp:element(),btnSizeDown:element(),container:element(),
  });
  // Execute the provider expression from actual prepared main.ts. Startup DOM
  // is omitted, but changing main's wiring cannot leave this native test green.
  const main=readFileSync(resolve(hop,'apps/studio-host/src/main.ts'),'utf8');
  const wiring=main.match(/toolbar = new Toolbar\(document\.getElementById\('style-bar'\)!, wasm, eventBus, dispatcher, (\(\) => \{[\s\S]*?\n    \})\);/);
  assert.ok(wiring,'actual main must wire the InputHandler font context provider');
  const runtime=new Function('handler',`let inputHandler = handler; return {capture: ${wiring[1]}, replace(other) { inputHandler = other; }};`)(handler);
  toolbar.captureFontApplyContext=runtime.capture;
  toolbar.fontLang.value='all';
  toolbar.setupFontControls();
  const select=(start=0,end=5)=>{cursor.clearSelection();cursor.moveTo(position(start));cursor.setAnchor();cursor.moveTo(position(end));handler.updateSelection();};
  select();
  toolbar.lastFontFamilies=wasm.getCharPropertiesAt(0,0,0).fontFamilies;
  const initialSubscriptions=subscriptions({eventBus});
  t.after(()=>{assert.equal(subscriptions({eventBus}),initialSubscriptions,'font context listeners leaked');history.clear(wasm);wasm.borrowDocumentHandle()?.free();});
  return {wasm,cursor,history,eventBus,handler,toolbar,select,runtime,
    bytes:()=>Buffer.from(wasm.borrowDocumentHandle().exportHwpx()),
    props:offset=>wasm.getCharPropertiesAt(0,0,offset),
    language(value){toolbar.fontLang.value=value;toolbar.fontLang.dispatch('change');},
    replace(){wasm.createNewDocument();wasm.insertText(0,0,0,'FIRST SECOND');handler.deactivate();handler.active=true;select();},
    reopen(){const bytes=this.bytes();wasm.loadDocument(bytes,'same.hwpx');handler.deactivate();handler.active=true;select();},
  };
}

const snapshot=h=>({bytes:h.bytes(),first:h.props(0),second:h.props(6),undo:h.history.peekUndoTop(),redo:h.history.peekRedoTop(),pending:h.handler.pendingCharShape});
function unchanged(h,before) {
  assert.deepEqual(h.props(0),before.first,'stale font request changed FIRST properties');
  assert.deepEqual(h.props(6),before.second,'stale font request changed SECOND properties');
  assert.equal(h.bytes().equals(before.bytes),true,'stale font request changed HWPX bytes or added FontIds');
  assert.equal(h.history.peekUndoTop(),before.undo,'stale font request added undo');
  assert.equal(h.history.peekRedoTop(),before.redo,'stale font request destroyed redo');
  assert.deepEqual(h.handler.pendingCharShape,before.pending,'stale font request staged caret formatting');
}

const changes={
  'selection change':h=>h.select(6,12),
  'selection change and return':h=>{h.select(6,12);h.select();},
  'cursor key movement and return':h=>{h.handler.onKeyDown(key('ArrowRight'));h.select();},
  'document replacement':h=>h.replace(),
  'reopen identical saved bytes':h=>h.reopen(),
  'native replacement without deactivation':h=>{h.wasm.createNewDocument();h.wasm.insertText(0,0,0,'FIRST SECOND');h.select();},
  close:h=>h.handler.deactivate(),
  'close and reactivate':h=>{h.handler.deactivate();h.handler.active=true;h.select();},
  dispose:h=>h.handler.dispose(),
  edit:h=>{h.handler.executeOperation({kind:'snapshot',operationType:'user-edit',operation:wasm=>{wasm.insertText(0,0,12,' USER');return position(5);}});h.select();},
  'edit and undo':h=>{h.handler.executeOperation({kind:'snapshot',operationType:'user-edit',operation:wasm=>{wasm.insertText(0,0,12,' USER');return position(5);}});h.history.undo(h.wasm);h.handler.afterEdit();h.select();},
  'form mode':h=>h.handler.setEditMode('form'),
  'form mode and return':h=>{h.handler.setEditMode('form');h.handler.setEditMode('edit');},
  'language change':h=>h.language('1'),
  'language change and return':h=>{h.language('1');h.language('all');},
  'replace current input handler':h=>h.runtime.replace(Object.create(InputHandler.prototype)),
};

for(const gate of ['read','face'])for(const [name,change] of Object.entries(changes)) {
  test(`installed font ${gate}: ${name} cancels without formatting, FontIds or history`,async(t)=>{
    const boundary=boundaries(t,gate),h=harness(t);
    const work=h.toolbar.applyFontSelection(font);await boundary.pending();
    change(h);const before=snapshot(h);boundary.release();await work;
    unchanged(h,before);
  });
}

// Read the actual ZIP's central directory: save assertions inspect native
// HWPX XML, without replacing export or requiring an extra dependency.
function zipEntry(bytes,name) {
  for(let offset=0;offset+46<=bytes.length;offset++) {
    if(bytes.readUInt32LE(offset)!==0x02014b50)continue;
    const len=bytes.readUInt16LE(offset+28),entryName=bytes.subarray(offset+46,offset+46+len).toString();
    if(entryName!==name)continue;
    const local=bytes.readUInt32LE(offset+42),size=bytes.readUInt32LE(offset+20);
    const dataStart=local+30+bytes.readUInt16LE(local+26)+bytes.readUInt16LE(local+28);
    const data=bytes.subarray(dataStart,dataStart+size),method=bytes.readUInt16LE(offset+10);
    assert.ok(method===0||method===8);return (method===8?inflateRawSync(data):data).toString();
  }
  throw Error(`missing native HWPX entry ${name}`);
}

for(const language of ['all','0','1','2','3','4','5','6']) {
  test(`installed font unchanged language ${language}: FIRST formats, SECOND stays unchanged, undo/redo and reopen retain font`,async(t)=>{
    const boundary=boundaries(t),h=harness(t);h.language(language);
    const before=snapshot(h),work=h.toolbar.applyFontSelection(font);await boundary.pending();boundary.release();await work;
    const first=h.props(0),second=h.props(6),after=h.bytes();
    assert.notDeepEqual(first,before.first);assert.deepEqual(second,before.second);
    const expected=[...before.first.fontFamilies];
    if(language==='all')expected.fill(font);else expected[Number(language)]=font;
    assert.deepEqual(first.fontFamilies,expected,'font must apply only to the captured language');
    assert.match(zipEntry(after,'Contents/header.xml'),new RegExp(font));
    assert.match(zipEntry(after,'Contents/section0.xml'),/charPrIDRef=/);
    assert.equal(h.history.canUndo(),true);h.history.undo(h.wasm);
    assert.deepEqual(h.props(0).fontFamilies,before.first.fontFamilies);
    assert.equal(h.history.canUndo(),false);h.history.redo(h.wasm);
    assert.deepEqual(h.props(0).fontFamilies,expected);
    const reopened=new native.HwpDocument(after);t.after(()=>reopened.free());
    assert.deepEqual(JSON.parse(reopened.getCharPropertiesAt(0,0,0)).fontFamilies,expected);
    // The native HWPX reader normalizes default pattern fill fields on every
    // round trip. Compare SECOND with the same baseline round-trip boundary.
    const baselineReopened=new native.HwpDocument(before.bytes);t.after(()=>baselineReopened.free());
    assert.deepEqual(JSON.parse(reopened.getCharPropertiesAt(0,0,6)),JSON.parse(baselineReopened.getCharPropertiesAt(0,0,6)));
  });
}

const fontSet={name:'synthetic installed set',korean:font,english:otherFont,chinese:font,japanese:otherFont,other:font,symbol:otherFont,user:font};
test('installed representative font set: selection change and return cancels all seven FontIds',async(t)=>{
  const boundary=boundaries(t),h=harness(t),work=h.toolbar.applyFontSet(fontSet);await boundary.pending();
  h.select(6,12);h.select();const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});
test('installed representative font set unchanged: seven languages, one undo/redo and reopen',async(t)=>{
  const boundary=boundaries(t),h=harness(t),before=snapshot(h),work=h.toolbar.applyFontSet(fontSet);
  await boundary.pending();boundary.release();await work;
  const expected=[font,otherFont,font,otherFont,font,otherFont,font],bytes=h.bytes();
  assert.deepEqual(h.props(0).fontFamilies,expected);assert.deepEqual(h.props(6),before.second);
  assert.equal(h.history.canUndo(),true);h.history.undo(h.wasm);
  assert.deepEqual(h.props(0).fontFamilies,before.first.fontFamilies);assert.equal(h.history.canUndo(),false);
  h.history.redo(h.wasm);assert.deepEqual(h.props(0).fontFamilies,expected);
  const reopened=new native.HwpDocument(bytes);t.after(()=>reopened.free());
  assert.deepEqual(JSON.parse(reopened.getCharPropertiesAt(0,0,0)).fontFamilies,expected);
});

test('installed font: latest request still wins',async(t)=>{
  const boundary=boundaries(t),h=harness(t),first=h.toolbar.applyFontSelection(font);
  await boundary.pending();const latest=h.toolbar.applyFontSelection(otherFont);boundary.release();await Promise.all([first,latest]);
  assert.deepEqual(h.props(0).fontFamilies,Array(7).fill(otherFont));assert.equal(h.history.canUndo(),true);
  h.history.undo(h.wasm);assert.equal(h.history.canUndo(),false);
});
test('installed font: real dropdown initialization still cancels pending requests before FontIds',async(t)=>{
  const boundary=boundaries(t),h=harness(t),work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.toolbar.initFontDropdown();const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});

test('installed font: real table cell-selection keys and return cancel without changing any cell or FontIds',async(t)=>{
  const boundary=boundaries(t),h=harness(t);h.cursor.clearSelection();
  const table=h.wasm.createTable(0,0,12,1,2);assert.equal(table.ok,true);
  for(let cell=0;cell<2;cell++)h.wasm.insertTextInCell(0,table.paraIdx,table.controlIdx,cell,0,0,`CELL-${cell}`);
  h.cursor.moveToCellByIndex(0,table.paraIdx,table.controlIdx,undefined,0,'start');
  assert.equal(h.cursor.enterCellSelectionMode(),true);h.handler.updateCellSelection();
  const selected=h.cursor.captureCellSelection(),initialPosition=h.cursor.getPosition();
  const work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.handler.onKeyDown(key('ArrowRight'));assert.notDeepEqual(h.cursor.captureCellSelection(),selected);
  h.handler.onKeyDown(key('ArrowLeft'));assert.deepEqual(h.cursor.captureCellSelection(),selected);
  assert.deepEqual(h.cursor.getPosition(),initialPosition);
  const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});

function enterHeader(h) {
  h.wasm.createHeaderFooter(0,true,0);h.wasm.insertTextInHeaderFooter(0,true,0,0,0,'HEADER TEXT');
  h.cursor.enterHeaderFooterMode(true,0,0,0);
  const point=charOffset=>({sectionIdx:0,isHeader:true,applyTo:0,paraIdx:0,charOffset});
  assert.equal(h.cursor.selectHeaderFooterRange(point(0),point(6),0),true);
  h.handler.updateSelection();return point;
}
test('installed font: real header selection key and return cancels its pending format',async(t)=>{
  const boundary=boundaries(t),h=harness(t),point=enterHeader(h);
  const work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.handler.onKeyDown(key('ArrowRight'));assert.equal(h.cursor.hasHeaderFooterSelection(),false);
  assert.equal(h.cursor.selectHeaderFooterRange(point(0),point(6),0),true);h.handler.updateSelection();
  const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});
test('installed font: real header escape into body cancels before adding FontIds',async(t)=>{
  const boundary=boundaries(t),h=harness(t);enterHeader(h);
  const work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.handler.onKeyDown({...key('Escape'),shiftKey:true});assert.equal(h.cursor.isInHeaderFooter(),false);h.select();
  const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});
test('installed font unchanged header selection: native range format and one undo/redo preserve body',async(t)=>{
  const boundary=boundaries(t),h=harness(t);enterHeader(h);
  const before=snapshot(h),headerBefore=h.wasm.getCharPropertiesInHeaderFooter(0,true,0,0,0);
  const work=h.toolbar.applyFontSelection(font);await boundary.pending();boundary.release();await work;
  assert.deepEqual(h.props(0),before.first);assert.deepEqual(h.props(6),before.second);
  assert.deepEqual(h.wasm.getCharPropertiesInHeaderFooter(0,true,0,0,0).fontFamilies,Array(7).fill(font));
  const bytes=h.bytes();assert.match(zipEntry(bytes,'Contents/header.xml'),new RegExp(font));
  h.history.undo(h.wasm);assert.equal(h.history.canUndo(),false);
  assert.deepEqual(h.wasm.getCharPropertiesInHeaderFooter(0,true,0,0,0).fontFamilies,headerBefore.fontFamilies);
  h.history.redo(h.wasm);assert.deepEqual(h.wasm.getCharPropertiesInHeaderFooter(0,true,0,0,0).fontFamilies,Array(7).fill(font));
});
test('installed font: real footnote escape and body return cancel the original selection request',async(t)=>{
  const boundary=boundaries(t),h=harness(t),note=h.wasm.insertFootnote(0,0,12);assert.equal(note.ok,true);
  assert.equal(h.wasm.insertTextInFootnote(0,note.paraIdx,note.controlIdx,0,2,'NOTE TEXT').ok,true);
  const work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.cursor.enterFootnoteMode(0,note.paraIdx,note.controlIdx,0,0);h.handler.updateSelection();
  assert.equal(h.cursor.isInFootnote(),true);h.handler.onKeyDown(key('Escape'));
  assert.equal(h.cursor.isInFootnote(),false);h.select();
  const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});
test('installed font unchanged refresh: native selection refresh and prior layout completion keep request current',async(t)=>{
  const boundary=boundaries(t),h=harness(t),work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.handler.updateSelection();h.cursor.updateRect();h.handler.updateCellSelection();
  for(const [event,payload] of [['picture-object-selection-changed',false],['table-object-selection-changed',false],
    ['headerFooterModeChanged','none'],['footnoteModeChanged',false],['cursor-rect-updated',h.cursor.getRect()],['editing-page-changed',0]])h.eventBus.emit(event,payload);
  // completeResumablePagination publishes only the existing layout result;
  // actual native flush preserves document content and current selection.
  h.wasm.flushDeferredPagination();h.handler.completeResumablePagination(h.wasm.pageCount);
  boundary.release();await work;assert.deepEqual(h.props(0).fontFamilies,Array(7).fill(font));assert.equal(h.history.canUndo(),true);
});

for(const mode of ['inactive','form','missing current handler'])test(`installed font ${mode}: skips loading and FontIds before starting`,async(t)=>{
  const boundary=boundaries(t),h=harness(t);
  if(mode==='inactive')h.handler.deactivate();else if(mode==='form')h.handler.setEditMode('form');else h.runtime.replace(null);
  const before=snapshot(h);await h.toolbar.applyFontSelection(font);unchanged(h,before);
  assert.deepEqual(boundary.trace,[]);
});
test('installed font failure: native FontFace rejection after replacement cannot format the new document',async(t)=>{
  const boundary=boundaries(t,'face'),h=harness(t);
  globalThis.FontFace=class {constructor(family){this.family=family;}async load(){boundary.trace.push({command:'FontFace.load'});throw await failure.promise;}};
  const failure=deferred(),work=h.toolbar.applyFontSelection(font);await boundary.pending();
  h.replace();const before=snapshot(h);failure.resolve(Error('synthetic FontFace decoder rejection'));await work;unchanged(h,before);
});

function pointerHarness(h) {
  const content={clientWidth:800,getBoundingClientRect:()=>({left:0,top:0})};
  h.handler.container={clientWidth:800,clientHeight:1200,style:{},querySelector:()=>content,
    getBoundingClientRect:()=>({left:0,top:0}),removeEventListener:noop};
  Object.assign(h.handler.virtualScroll,{getPageAtPoint:()=>0,getPageOffset:()=>0,getPageWidth:()=>800,getPageLeftResolved:()=>0});
  Object.assign(h.handler,{canEditHyperlink:()=>false,updateFieldMarkers:noop,prepareClickHerePointerEntry:noop});
  return (x,y)=>{
    const e={clientX:x,clientY:y,button:0,shiftKey:false,ctrlKey:false,metaKey:false,altKey:false,preventDefault:noop,target:{closest:()=>null}};
    h.handler.onClick(e);h.handler.onMouseUp(e);
  };
}
for(const object of ['picture','table'])test(`installed font: native ${object} selection click and return cancels the original body format`,async(t)=>{
  const boundary=boundaries(t),h=harness(t);h.cursor.clearSelection();
  let table;
  if(object==='picture'){
    const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
    assert.equal(h.wasm.insertPicture(0,0,12,'',png,7500,7500,100,100,'png','').ok,true);
  }else {table=h.wasm.createTable(0,0,12,1,2);assert.equal(table.ok,true);}
  h.wasm.getPageLayerTreeObject(0);h.cursor.moveTo(position(3));const rect=h.cursor.getRect();assert.ok(rect);
  const click=pointerHarness(h);h.select();
  const work=h.toolbar.applyFontSelection(font);await boundary.pending();
  if(object==='picture'){click(50,50);assert.equal(h.cursor.isInPictureObjectSelection(),true);}
  else {const box=h.wasm.getTableCellBboxes(0,table.paraIdx,table.controlIdx)[0];assert.ok(box);click(box.x,box.y+2);assert.equal(h.cursor.isInTableObjectSelection(),true);}
  click(rect.x,rect.y+4);h.select();assert.equal(h.cursor.isInPictureObjectSelection(),false);assert.equal(h.cursor.isInTableObjectSelection(),false);
  const before=snapshot(h);boundary.release();await work;unchanged(h,before);
});
