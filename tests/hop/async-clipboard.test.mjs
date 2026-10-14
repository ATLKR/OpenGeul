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
const {WasmBridge}=await upstream('core/wasm-bridge.ts');
const {EventBus}=await upstream('core/event-bus.ts');
const {InputHandler}=await upstream('engine/input-handler.ts');
const {CursorState}=await upstream('engine/cursor.ts');
const {CommandHistory}=await upstream('engine/history.ts');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
const position=(charOffset=0)=>({sectionIndex:0,paragraphIndex:0,charOffset});
const tick=()=>new Promise((resolve)=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};

// Rendering and browser decode are the only substitutes. Document replacement,
// selection, operations, mutations, snapshots, history and save bytes are real.
function harness(t) {
  const wasm=new WasmBridge();
  // This Vite dev-only external-image fetch is outside the offline document test.
  wasm.populateExternalImagesFromDevServer=async()=>{};
  wasm.createNewDocument();
  wasm.insertText(0,0,0,'DOCUMENT-A-SELECTED');
  const cursor=new CursorState(wasm);
  const history=new CommandHistory();
  const eventBus=new EventBus();
  const noop=()=>{};
  const renderer={clear:noop,hide:noop,dispose:noop,render:noop,show:noop,update:noop};
  const handler=Object.assign(Object.create(InputHandler.prototype),{
    active:true,editMode:'edit',wasm,cursor,history,eventBus,
    viewportManager:{getZoom:()=>1},selectionRenderer:renderer,
    caret:renderer,fieldMarker:renderer,caretLayoutReveal:{requestFor:noop,clear:noop},
    deferredPaginationRunner:{cancel:noop},_cellBlockLetterImeGuard:{reset:noop},
    _compositionFragment:null,textarea:{value:'',removeEventListener:noop,remove:noop,focus:noop},
    container:{removeEventListener:noop},rawTextMutationEffects:{reset:noop},
    flushDeferredPaginationIfNeeded:noop,cancelDeferredPaginationFlush:noop,
    resetRawTextMutationEffects:noop,prepareTextMutationBeforeCursor:()=>false,
    clearTableResizeRuntimeCache:noop,stopTextSelectionDragAutoScroll:noop,
    updateCaret(){this.updateSelection();},
  });
  const select=(start=0,end=10)=>{
    cursor.clearSelection();cursor.moveTo(position(start));cursor.setAnchor();cursor.moveTo(position(end));
    handler.updateSelection();
  };
  select();
  t.after(()=>{history.clear(wasm);wasm.borrowDocumentHandle()?.free();});
  return {handler,wasm,cursor,history,eventBus,select,
    text:()=>wasm.borrowDocumentHandle().getTextFileText(),
    bytes:()=>Buffer.from(wasm.borrowDocumentHandle().exportHwpx()),
    replace(){wasm.createNewDocument();wasm.insertText(0,0,0,'DOCUMENT-B-TARGET');handler.deactivate();handler.active=true;select();},
  };
}

function browser(t,{decode=Promise.resolve(),rtfRead}={}) {
  const originals=new Map(['Image','FileReader','document'].map((key)=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  globalThis.Image=class {naturalWidth=1;naturalHeight=1;decode(){return decode;}};
  globalThis.FileReader=class {
    readAsDataURL(){const finish=()=>{this.result=`data:image/png;base64,${png.toString('base64')}`;this.onload();};
      if(rtfRead)rtfRead.promise.then(finish);else queueMicrotask(finish);}
  };
  globalThis.document={removeEventListener(){}};
  const create=URL.createObjectURL,revoke=URL.revokeObjectURL;
  let created=0,revoked=0;
  URL.createObjectURL=()=>{created++;return 'blob:clipboard-regression';};
  URL.revokeObjectURL=()=>{revoked++;};
  t.after(()=>{for(const [key,value] of originals)value?Object.defineProperty(globalThis,key,value):delete globalThis[key];URL.createObjectURL=create;URL.revokeObjectURL=revoke;});
  return {created:()=>created,revoked:()=>revoked};
}

function paste(handler,kind,wait) {
  const values=kind==='rtf'?{
    'text/html':'<p>CLIPBOARD-RTF</p><img src="file:///clip.png" width="1" height="1">',
    'text/plain':'CLIPBOARD-RTF',
    'text/rtf':`{\\rtf1{\\pict\\pngblip ${png.toString('hex')}}}`,
  }:{};
  const file={type:'image/png',arrayBuffer:()=>wait?.promise ?? Promise.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength))};
  handler.onPaste({preventDefault(){},clipboardData:{getData:(type)=>values[type]??'',items:kind==='rtf'?[]:[{kind:'file',type:file.type,getAsFile:()=>file}]}});
}

function pointerHarness(h) {
  const noop=()=>{};
  document.addEventListener=noop;
  const content={clientWidth:800,getBoundingClientRect:()=>({left:0,top:0})};
  h.handler.container={clientWidth:800,clientHeight:1200,style:{},querySelector:()=>content,
    getBoundingClientRect:()=>({left:0,top:0}),removeEventListener:noop};
  h.handler.virtualScroll={getPageAtPoint:()=>0,getPageOffset:()=>0,getPageWidth:()=>800,getPageLeftResolved:()=>0};
  h.handler.canEditHyperlink=()=>false;
  h.handler.updateFieldMarkers=noop;
  h.handler.prepareClickHerePointerEntry=noop;
  return (x,y)=>{
    const e={clientX:x,clientY:y,button:0,shiftKey:false,ctrlKey:false,metaKey:false,altKey:false,
      preventDefault(){},target:{closest:()=>null}};
    h.handler.onClick(e);h.handler.onMouseUp(e);
  };
}

const changes={
  replacement:(h)=>h.replace(),
  'reopen identical bytes':(h)=>{const bytes=h.bytes();h.wasm.loadDocument(bytes,'same.hwpx');h.handler.deactivate();h.handler.active=true;h.select();},
  close:(h)=>h.handler.deactivate(),
  'close and reactivate':(h)=>{h.handler.deactivate();h.handler.active=true;h.select();},
  dispose:(h)=>h.handler.dispose(),
  'selection change':(h)=>h.select(2,12),
  'selection change and return':(h)=>{h.select(2,12);h.select();},
  'cursor move':(h)=>{h.cursor.clearSelection();h.cursor.moveTo(position(3));h.handler.updateSelection();},
  edit:(h)=>{h.handler.executeOperation({kind:'snapshot',operationType:'concurrent-edit',operation:(wasm)=>{wasm.insertText(0,0,18,'USER');return position(10);}});h.select();},
  'edit and undo':(h)=>{h.handler.executeOperation({kind:'snapshot',operationType:'concurrent-edit',operation:(wasm)=>{wasm.insertText(0,0,18,'USER');return position(10);}});h.history.undo(h.wasm);h.handler.afterEdit();h.select();},
  'form mode':(h)=>h.handler.setEditMode('form'),
  'page definition edit':(h)=>{const page=h.wasm.getPageDef(0);h.wasm.setPageDef(0,{...page,marginLeft:page.marginLeft+100});h.eventBus.emit('document-changed');},
};

for(const kind of ['image','rtf']) {
  for(const [name,change] of Object.entries(changes)) {
    test(`${kind}: pending conversion cancels on ${name} without changing text, save bytes or history`,async(t)=>{
      const wait=deferred();browser(t,kind==='rtf'?{rtfRead:wait}:{});
      const h=harness(t);paste(h.handler,kind,kind==='image'?wait:undefined);
      await tick();change(h);
      const beforeText=h.text(),beforeBytes=h.bytes(),undo=h.history.peekUndoTop(),redo=h.history.peekRedoTop();
      wait.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength));await tick();
      assert.equal(h.text(),beforeText,'stale paste changed the current document text');
      assert.deepEqual(h.bytes(),beforeBytes,'stale paste changed the saved HWPX document');
      assert.equal(h.history.peekUndoTop(),undo,'stale paste added an undo entry');
      assert.equal(h.history.peekRedoTop(),redo,'stale paste destroyed redo');
    });
  }
  test(`${kind}: unchanged document paste replaces the selection and preserves one undo/redo operation and saved image`,async(t)=>{
    browser(t);const h=harness(t),beforeText=h.text();
    paste(h.handler,kind);await tick();
    assert.notEqual(h.text(),beforeText);
    assert.equal(h.text().includes('DOCUMENT-A'),false);
    const afterText=h.text(),afterBytes=h.bytes();
    assert.equal(h.history.canUndo(),true);
    h.history.undo(h.wasm);
    assert.equal(h.text(),beforeText,'one undo must restore the complete paste replacement');
    assert.equal(h.history.canUndo(),false,'selection deletion must share the paste snapshot');
    h.history.redo(h.wasm);
    assert.equal(h.text(),afterText);
    const reopened=new native.HwpDocument(afterBytes);t.after(()=>reopened.free());
    assert.equal(reopened.getTextFileText(),afterText);
    const picture=JSON.parse(reopened.getControls()).find(({userDesc})=>userDesc==='그림');
    assert.ok(picture,'saved document must contain the pasted picture');
    assert.deepEqual(Buffer.from(reopened.getControlImageData(0,picture.para,'',picture.controlIndex)),png);
  });
}

for(const kind of ['image','rtf']) {
  test(`${kind}: real picture selection click and return cancels the pending paste`,async(t)=>{
    const wait=deferred();browser(t,kind==='rtf'?{rtfRead:wait}:{});const h=harness(t);
    h.cursor.clearSelection();
    assert.equal(h.wasm.insertPicture(0,0,18,'',png,7500,7500,100,100,'png','').ok,true);
    h.wasm.getPageLayerTreeObject(0);
    h.cursor.moveTo(position(3));const caret=h.cursor.getRect();assert.ok(caret);
    const click=pointerHarness(h);
    paste(h.handler,kind,kind==='image'?wait:undefined);
    click(50,50);assert.equal(h.cursor.isInPictureObjectSelection(),true);
    click(caret.x,caret.y+4);assert.equal(h.cursor.isInPictureObjectSelection(),false);
    const current=h.cursor.getPosition();
    assert.equal(current.sectionIndex,0);assert.equal(current.paragraphIndex,0);assert.equal(current.charOffset,3);
    assert.equal(h.cursor.getSelection(),null);
    const beforeText=h.text(),beforeBytes=h.bytes();
    wait.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength));await tick();
    assert.equal(h.text(),beforeText);
    assert.deepEqual(h.bytes(),beforeBytes,'stale paste changed saved bytes after picture selection returned');
    assert.equal(h.history.canUndo(),false);
  });
  test(`${kind}: real table border selection click and return cancels the pending paste`,async(t)=>{
    const wait=deferred();browser(t,kind==='rtf'?{rtfRead:wait}:{});const h=harness(t);
    h.cursor.clearSelection();
    const table=h.wasm.createTable(0,0,18,1,2);assert.equal(table.ok,true);
    h.wasm.getPageLayerTreeObject(0);h.cursor.moveTo(position(3));
    const caret=h.cursor.getRect();assert.ok(caret);
    const bbox=h.wasm.getTableCellBboxes(0,table.paraIdx,table.controlIdx)[0];assert.ok(bbox);
    const click=pointerHarness(h);
    paste(h.handler,kind,kind==='image'?wait:undefined);
    click(bbox.x,bbox.y+2);assert.equal(h.cursor.isInTableObjectSelection(),true);
    click(caret.x,caret.y+4);assert.equal(h.cursor.isInTableObjectSelection(),false);
    const current=h.cursor.getPosition();
    assert.equal(current.sectionIndex,0);assert.equal(current.paragraphIndex,0);assert.equal(current.charOffset,3);
    assert.equal(h.cursor.getSelection(),null);
    const beforeText=h.text(),beforeBytes=h.bytes();
    wait.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength));await tick();
    assert.equal(h.text(),beforeText);
    assert.deepEqual(h.bytes(),beforeBytes,'stale paste changed saved bytes after table selection returned');
    assert.equal(h.history.canUndo(),false);
  });
  for(const boundary of ['idle flush','resumable completion']) {
    test(`${kind}: prior cell edit ${boundary} keeps an unchanged pending paste current`,{timeout:3000},async(t)=>{
      const wait=deferred();browser(t,kind==='rtf'?{rtfRead:wait}:{});const h=harness(t);
      h.cursor.clearSelection();const table=h.wasm.createTable(0,0,0,1,2);
      h.cursor.moveToCellByIndex(0,table.paraIdx,table.controlIdx,undefined,0,'start');
      const edit=h.wasm.insertTextInCellDeferredPagination(0,table.paraIdx,table.controlIdx,0,0,0,'PRIOR USER EDIT');
      assert.equal(edit.paginationDeferred,true);assert.equal(edit.cellFlowChanged,false);
      h.cursor.moveToCellByIndex(0,table.paraIdx,table.controlIdx,undefined,0,'end');
      h.handler.deferredPaginationRunner={hasPendingWork:()=>false,cancel(){}};
      h.handler.flushDeferredPaginationIfNeeded=InputHandler.prototype.flushDeferredPaginationIfNeeded;
      h.handler.cancelDeferredPaginationFlush=InputHandler.prototype.cancelDeferredPaginationFlush;
      t.after(()=>h.handler.cancelDeferredPaginationFlush());
      const expected=boundary==='idle flush'?'deferred-pagination-flush:idle-auto':'deferred-pagination-complete';
      const layoutDone=new Promise((resolve)=>{
        const off=h.eventBus.on('document-changed',(reason)=>{if(reason===expected){off();resolve();}});
      });
      if(boundary==='idle flush')h.handler.scheduleDeferredPaginationFlush();
      paste(h.handler,kind,kind==='image'?wait:undefined);
      if(boundary==='resumable completion'){
        h.wasm.flushDeferredPagination();h.handler.completeResumablePagination(h.wasm.pageCount);
      }
      await layoutDone;const before=h.bytes(),beforeText=h.text();
      wait.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength));await tick();
      assert.equal(h.history.canUndo(),true,'layout completion cancelled an unchanged paste');
      assert.notDeepEqual(h.bytes(),before);
      h.history.undo(h.wasm);assert.equal(h.text(),beforeText,'undo must preserve the earlier cell edit');
      assert.equal(h.text().includes('PRIOR USER EDIT'),true);
    });
  }
}

test('image: document replacement during decode cancels and releases its object URL',async(t)=>{
  const wait=deferred(),url=browser(t,{decode:wait.promise}),h=harness(t);
  paste(h.handler,'image');await tick();assert.equal(url.created(),1);
  h.replace();const before=h.bytes();wait.resolve();await tick();
  assert.deepEqual(h.bytes(),before);assert.equal(h.history.canUndo(),false);assert.equal(url.revoked(),1);
});

test('image: view refresh with unchanged selection keeps the paste current',async(t)=>{
  const wait=deferred();browser(t);const h=harness(t);paste(h.handler,'image',wait);
  h.handler.updateSelection();h.cursor.updateRect();h.handler.updateSelection();
  h.handler.updateCellSelection();
  for(const [event,payload] of [
    ['picture-object-selection-changed',false],['table-object-selection-changed',false],
    ['headerFooterModeChanged','none'],['footnoteModeChanged',false],
    ['cursor-rect-updated',h.cursor.getRect()],['editing-page-changed',0],
  ]) h.eventBus.emit(event,payload);
  wait.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength));await tick();
  assert.equal(h.history.canUndo(),true);
});

test('image: decode failure preserves the selection, document and history and releases the URL',async(t)=>{
  const wait=deferred(),url=browser(t,{decode:wait.promise}),h=harness(t);
  const before=h.bytes(),selection=h.cursor.getSelection();
  const warn=console.warn;console.warn=()=>{};t.after(()=>{console.warn=warn;});
  paste(h.handler,'image');await tick();wait.reject(new Error('synthetic decode failure'));await tick();
  assert.deepEqual(h.bytes(),before);assert.deepEqual(h.cursor.getSelection(),selection);
  assert.equal(h.history.canUndo(),false);assert.equal(url.revoked(),1);
  assert.equal([...h.eventBus.handlers.values()].reduce((n,handlers)=>n+handlers.size,0),0,'failed conversion leaked context listeners');
});

test('rtf: conversion failure after document replacement cannot run its HTML fallback in B',async(t)=>{
  browser(t);const h=harness(t);
  // Replacing the target inside the real FileReader failure boundary makes the
  // actual inlineOfficeClipboardImages promise reject before the HTML fallback.
  globalThis.FileReader=class {readAsDataURL(){h.replace();throw new Error('synthetic RTF read failure');}};
  const warn=console.warn;console.warn=()=>{};t.after(()=>{console.warn=warn;});
  paste(h.handler,'rtf');const before=h.bytes();await tick();
  assert.deepEqual(h.bytes(),before);assert.equal(JSON.parse(h.text()).trim(),'DOCUMENT-B-TARGET');
  assert.equal(h.history.canUndo(),false);
});

for(const kind of ['image','rtf']) {
  test(`${kind}: real cell-selection keyboard movement and return cancels the pending paste`,async(t)=>{
    const wait=deferred();browser(t,kind==='rtf'?{rtfRead:wait}:{});const h=harness(t);
    h.cursor.clearSelection();
    const table=h.wasm.createTable(0,0,0,1,2);
    assert.equal(table.ok,true);
    h.cursor.moveToCellByIndex(0,table.paraIdx,table.controlIdx,undefined,0,'start');
    assert.equal(h.cursor.enterCellSelectionMode(),true);
    h.handler.cellSelectionRenderer={clear(){},render(){}};
    h.handler.updateCellSelection();
    const initialSelection=h.cursor.captureCellSelection(),initialPosition=h.cursor.getPosition();
    paste(h.handler,kind,kind==='image'?wait:undefined);
    const key=(key)=>({key,code:key,preventDefault(){},shiftKey:false,ctrlKey:false,altKey:false,metaKey:false,isComposing:false,keyCode:0});
    h.handler.onKeyDown(key('ArrowRight'));
    assert.notDeepEqual(h.cursor.captureCellSelection(),initialSelection);
    h.handler.onKeyDown(key('ArrowLeft'));
    assert.deepEqual(h.cursor.captureCellSelection(),initialSelection);
    assert.deepEqual(h.cursor.getPosition(),initialPosition);
    const beforeText=h.text(),beforeBytes=h.bytes();
    wait.resolve(png.buffer.slice(png.byteOffset,png.byteOffset+png.byteLength));await tick();
    assert.equal(h.text(),beforeText);
    assert.deepEqual(h.bytes(),beforeBytes,'stale paste changed saved bytes after cell selection moved away and returned');
    assert.equal(h.history.canUndo(),false,'stale paste added history after cell selection moved away and returned');
  });
}
