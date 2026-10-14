/** Active shape-picker variants: actual commands/InputHandler/internal history/
 * WASM with owned synthetic DOM events and geometry. No GUI/native paint claim. */
import {prepared} from './shape_creation_history.loader.mjs';
import {createShapeHistoryDom,parseGeneratedXml} from './shape_creation_history.dom.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {inflateRawSync} from 'node:zlib';
import {createHash} from 'node:crypto';

const src=resolve(process.env.RHWP_SOURCE??resolve(prepared,'third_party/rhwp'),'rhwp-studio/src');
const source=name=>import(pathToFileURL(resolve(src,name)));
const vendor=resolve(prepared,'apps/studio-host/vendor/rhwp-core');
const native=await import(pathToFileURL(resolve(vendor,'rhwp.js')));
await native.default({module_or_path:readFileSync(resolve(vendor,'rhwp_bg.wasm'))});
const {WasmBridge}=await source('core/wasm-bridge.ts');
const {EventBus}=await source('core/event-bus.ts');
const {VirtualScroll}=await source('view/virtual-scroll.ts');
const {ViewportManager}=await source('view/viewport-manager.ts');
const paths=['engine/input-handler.ts','engine/input-handler-mouse.ts','engine/input-handler-connector.ts','engine/history.ts','command/commands/insert.ts','ui/shape-picker.ts'].map(name=>resolve(src,name));
paths.push(resolve(vendor,'rhwp_bg.wasm'));
if(process.env.HOP_SHAPE_HISTORY_HANDLER)paths.push(resolve(process.env.HOP_SHAPE_HISTORY_HANDLER));
if(process.env.HOP_SHAPE_HISTORY_CONNECTOR)paths.push(resolve(process.env.HOP_SHAPE_HISTORY_CONNECTOR));
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const hashes=new Map(paths.map(path=>[path,digest(readFileSync(path))]));
const variants=[['ellipse','타원'],['arc','호'],['polygon','다각형'],
  ['connector-straight','직선'],['connector-straight-arrow','직선 화살표'],
  ['connector-stroke','꺾인'],['connector-stroke-arrow','꺾인 화살표'],
  ['connector-arc','곡선'],['connector-arc-arrow','곡선 화살표']];
const connectorTypes={'connector-straight':'STRAIGHT_NOARROW','connector-straight-arrow':'STRAIGHT_ONEWAY',
  'connector-stroke':'STROKE_NOARROW','connector-stroke-arrow':'STROKE_ONEWAY',
  'connector-arc':'ARC_NOARROW','connector-arc-arrow':'ARC_ONEWAY'};

function sectionXml(raw){
  const bytes=Buffer.from(raw),end=bytes.lastIndexOf(Buffer.from([0x50,0x4b,0x05,0x06]));
  assert.ok(end>=0);let cursor=bytes.readUInt32LE(end+16);
  for(let index=0;index<bytes.readUInt16LE(end+10);index++){
    assert.equal(bytes.readUInt32LE(cursor),0x02014b50);
    const length=bytes.readUInt32LE(cursor+20),method=bytes.readUInt16LE(cursor+10);
    const nameLength=bytes.readUInt16LE(cursor+28),extra=bytes.readUInt16LE(cursor+30),comment=bytes.readUInt16LE(cursor+32);
    if(bytes.subarray(cursor+46,cursor+46+nameLength).toString()==='Contents/section0.xml'){
      const local=bytes.readUInt32LE(cursor+42),start=local+30+bytes.readUInt16LE(local+26)+bytes.readUInt16LE(local+28);
      const compressed=bytes.subarray(start,start+length);return (method===8?inflateRawSync(compressed):compressed).toString();
    }
    cursor+=46+nameLength+extra+comment;
  }
  throw new Error('Actual native export lacks section XML');
}
function inspect(bytes){
  const xml=parseGeneratedXml(sectionXml(bytes));
  const all=node=>[node,...node.children.flatMap(all)],text=node=>node.text+node.children.map(text).join('');
  const shapes=all(xml).filter(node=>['rect','ellipse','arc','polygon','line','connectLine'].includes(node.localName)).map(node=>{
    const size=node.children.find(child=>child.localName==='sz');
    return {kind:node.localName,width:Number(size.attrs.width),height:Number(size.attrs.height),
      type:node.attrs.type??null,points:node.children.filter(child=>['pt','startPt','endPt','controlPt'].includes(child.localName)).map(child=>child.attrs)};
  });
  const body=xml.children.filter(node=>node.localName==='p').flatMap(p=>p.children.filter(node=>node.localName==='run').flatMap(run=>run.children.filter(node=>node.localName==='t').map(text))).join('');
  return {shapes,body};
}

async function harness(t,{connectors=false}={}){
  const dom=createShapeHistoryDom(),globalNames=['window','document','navigator','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLCanvasElement','Element','MouseEvent','KeyboardEvent','Event','localStorage','getComputedStyle','requestAnimationFrame','cancelAnimationFrame','__APP_VERSION__','__HOP_VERSION__'];
  const descriptors=new Map(globalNames.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  const timerFunction=globalThis.setTimeout,timers=new Set();
  for(const name of globalNames){let value=dom.window[name];if(['getComputedStyle','requestAnimationFrame','cancelAnimationFrame'].includes(name))value=value.bind(dom.window);if(name.startsWith('__'))value='shape-variant-test';Object.defineProperty(globalThis,name,{value,configurable:true});}
  globalThis.setTimeout=(...args)=>{const timer=timerFunction(...args);timers.add(timer);return timer;};
  const {InputHandler}=await source('engine/input-handler.ts'),{insertCommands}=await source('command/commands/insert.ts');
  const {editCommands}=await import('@/command/commands/edit');
  const {viewCommands}=await source('command/commands/view.ts');
  const {CommandRegistry}=await source('command/registry.ts'),{CommandDispatcher}=await source('command/dispatcher.ts');
  const wasm=new WasmBridge();wasm.createNewDocument();wasm.insertText(0,0,0,'VARIANT-BODY');
  // Owned native input fixture. The mutation under test begins only after the
  // full real InputHandler constructor gives it fresh history.
  if(connectors)for(const horzOffset of [10000,25000]){
    assert.equal(wasm.createShapeControl({sectionIdx:0,paraIdx:0,charOffset:0,width:6000,height:6000,horzOffset,vertOffset:12000,shapeType:'rectangle'}).ok,true);
  }
  const eventBus=new EventBus(),virtualScroll=new VirtualScroll(),viewport=new ViewportManager(eventBus);
  virtualScroll.setPageDimensions([wasm.getPageInfo(0)]);
  const container=document.getElementById('scroll-container'),content=document.getElementById('scroll-content'),canvas=content.querySelector('canvas');
  const rect={x:0,y:0,left:0,top:0,right:800,bottom:1200,width:800,height:1200};
  for(const node of [container,content,canvas]){node.getBoundingClientRect=()=>rect;Object.defineProperty(node,'clientWidth',{value:800});Object.defineProperty(node,'clientHeight',{value:1200});}
  const handler=new InputHandler(container,wasm,eventBus,virtualScroll,viewport);handler.activateWithCaretPosition();
  const registry=new CommandRegistry();registry.registerAll(insertCommands);registry.registerAll(editCommands.filter(command=>['edit:undo','edit:redo'].includes(command.id)));
  registry.registerAll(viewCommands.filter(command=>command.id==='view:form-mode'));let mode='normal';
  const context=()=>({hasDocument:wasm.pageCount>0,hasSelection:handler.hasSelection(),inTable:handler.isInTable(),inPictureObjectSelection:handler.isInPictureObjectSelection(),inField:handler.isInField(),isEditable:mode!=='form',editMode:mode,isFormMode:mode==='form',canEditFormField:false,canUndo:handler.canUndo(),canRedo:handler.canRedo(),zoom:1,showControlCodes:false,showParagraphMarks:false});
  const dispatcher=new CommandDispatcher(registry,{wasm,eventBus,getInputHandler:()=>handler,getContext:context,getViewportManager:()=>viewport,setEditMode(next){mode=next;handler.setEditMode(next);}},eventBus);handler.setDispatcher(dispatcher);
  const results=new Map();for(const button of document.querySelectorAll('button[data-cmd]'))button.addEventListener('click',()=>results.set(button.dataset.cmd,dispatcher.dispatchWithResult(button.dataset.cmd)));
  const command=id=>{document.querySelector(`button[data-cmd="${id}"]`).click();return results.get(id);};
  const mouse=(type,x,y)=>canvas.dispatchEvent(new dom.window.MouseEvent(type,{bubbles:true,button:0,buttons:type==='mouseup'?0:1,clientX:x,clientY:y}));
  const click=(x,y)=>{mouse('mousedown',x,y);mouse('mouseup',x,y);};
  const begin=type=>{
    assert.equal(command('insert:shape').ok,true);
    const title=variants.find(([id])=>id===type)?.[1];assert.ok(title);
    const buttons=Array.from(document.querySelectorAll('.shape-picker-btn')).filter(button=>button.title===title);
    const button=type==='connector-straight'?buttons[1]:buttons[0];assert.ok(button,'Actual public picker choice available');button.click();assert.equal(container.style.cursor,'crosshair');
  };
  const keyboard=key=>document.querySelector('textarea[aria-label="문서 편집 입력"]').dispatchEvent(new dom.window.KeyboardEvent('keydown',{bubbles:true,key,code:key}));
  t.after(()=>{for(const timer of timers)clearTimeout(timer);globalThis.setTimeout=timerFunction;handler.dispose();wasm.releaseDocument();dom.window.close();for(const [name,descriptor] of descriptors)descriptor?Object.defineProperty(globalThis,name,descriptor):delete globalThis[name];for(const [path,hash] of hashes)assert.equal(digest(readFileSync(path)),hash,'Actual source/WASM bytes unchanged');});
  return {wasm,handler,container,begin,mouse,click,keyboard,command,export:()=>wasm.exportHwpx(),virtualScroll,
    connectionPoints(){
      const controls=wasm.getPageControlLayout(0).controls.filter(control=>control.type==='shape').sort((a,b)=>a.x-b.x);
      assert.equal(controls.length,2,'Real fixture layout has two connectable rectangles');
      const left=virtualScroll.getPageLeftResolved(0,800),top=virtualScroll.getPageOffset(0);
      return [{x:left+controls[0].x+controls[0].w,y:top+controls[0].y+controls[0].h/2},
        {x:left+controls[1].x,y:top+controls[1].y+controls[1].h/2}];
    },
  };
}
function polygonPending(h){h.begin('polygon');for(const point of [[200,250],[350,250],[350,350]])h.click(...point);}
function connectorPending(h,type='connector-straight'){
  const [start,end]=h.connectionPoints();h.begin(type);h.click(start.x,start.y);h.mouse('mousemove',end.x,end.y);return end;
}
function finishPending(h,type,end){if(type==='polygon')h.click(200,250);else h.click(end.x,end.y);}
function replacementInput(connectors){
  const fixture=new WasmBridge();try{
    fixture.createNewDocument();fixture.insertText(0,0,0,'DOCUMENT-B');
    if(connectors)for(const horzOffset of [10000,25000])assert.equal(fixture.createShapeControl({sectionIdx:0,paraIdx:0,charOffset:0,width:6000,height:6000,horzOffset,vertOffset:12000,shapeType:'rectangle'}).ok,true);
    return fixture.exportHwpx();
  }finally{fixture.releaseDocument();}
}
function assertHistoryAndReopen(h,before,created){
  assert.equal(h.handler.canUndo(),true,'Active public variant creation must enter real history');
  assert.equal(h.command('edit:undo').ok,true);assert.deepEqual(inspect(h.export()),inspect(before));
  assert.equal(h.command('edit:redo').ok,true);assert.deepEqual(inspect(h.export()),inspect(created));
  const reopened=new WasmBridge();try{reopened.loadDocument(h.export(),'owned-variant.hwpx');assert.deepEqual(inspect(reopened.exportHwpx()),inspect(created));}finally{reopened.releaseDocument();}
}

for(const type of ['ellipse','arc'])test(`${type} real picker drag uses common creation history path`,async t=>{
  const h=await harness(t),before=h.export();h.begin(type);h.mouse('mousedown',200,250);h.mouse('mousemove',350,325);h.mouse('mouseup',350,325);
  const created=h.export(),result=inspect(created);assert.equal(result.shapes.length,1);assert.equal(result.shapes[0].kind,type);assert.equal(result.body,'VARIANT-BODY');assertHistoryAndReopen(h,before,created);
});

for(const finish of ['doubleclick','near-first-point','Escape'])test(`polygon public ${finish} completion records creation history`,async t=>{
  const h=await harness(t),before=h.export();h.begin('polygon');
  for(const point of [[200,250],[350,250],[350,350]])h.click(...point);
  if(finish==='doubleclick')h.mouse('dblclick',350,350);else if(finish==='near-first-point')h.click(200,250);else h.keyboard('Escape');
  assert.equal(h.container.style.cursor,'');const created=h.export(),result=inspect(created);
  assert.equal(result.shapes.length,1);assert.equal(result.shapes[0].kind,'polygon');assert.equal(result.body,'VARIANT-BODY');assertHistoryAndReopen(h,before,created);
});

for(const [type] of variants.filter(([type])=>type.startsWith('connector-')))test(`${type} actual connection-point clicks create connector history`,async t=>{
  const h=await harness(t,{connectors:true}),before=h.export(),[start,end]=h.connectionPoints();
  h.begin(type);h.click(start.x,start.y);h.mouse('mousemove',end.x,end.y);h.click(end.x,end.y);
  assert.equal(h.container.style.cursor,'');const created=h.export(),result=inspect(created);
  assert.equal(result.shapes.filter(shape=>shape.kind==='rect').length,2);
  const [connector]=result.shapes.filter(shape=>shape.kind==='connectLine');assert.ok(connector,'Actual native export contains connected line');
  assert.equal(connector.type,connectorTypes[type],'Actual saved type matches public picker choice');
  const endpoints=connector.points.filter(point=>'subjectIDRef' in point);assert.equal(endpoints.length,2);
  assert.ok(endpoints.every(point=>Number(point.subjectIDRef)>0),'Saved connector endpoints retain both subject links');
  assert.deepEqual(endpoints.map(point=>Number(point.subjectIdx)),[1,3],'Saved endpoints retain right/left attachment indices');
  assert.equal(result.body,'VARIANT-BODY');assertHistoryAndReopen(h,before,created);
});

test('polygon one-point Escape cancels without mutation/history',async t=>{
  const h=await harness(t),before=h.export();h.begin('polygon');h.click(200,250);h.keyboard('Escape');assert.equal(h.container.style.cursor,'');assert.equal(digest(h.export()),digest(before));assert.equal(h.handler.canUndo(),false);
});
test('connector empty-point clicks followed by Escape create no mutation/history',async t=>{
  const h=await harness(t,{connectors:true}),before=h.export();h.begin('connector-straight');h.click(650,700);h.click(660,710);h.keyboard('Escape');assert.equal(h.container.style.cursor,'');assert.equal(digest(h.export()),digest(before));assert.equal(h.handler.canUndo(),false);
});
test('connector Escape after valid start point cancels without mutation/history',async t=>{
  const h=await harness(t,{connectors:true}),before=h.export(),[start]=h.connectionPoints();h.begin('connector-stroke');h.click(start.x,start.y);h.keyboard('Escape');assert.equal(h.container.style.cursor,'');assert.equal(digest(h.export()),digest(before));assert.equal(h.handler.canUndo(),false);
});

for(const type of ['polygon','connector-straight'])test(`${type} pending public drawing respects newly entered form mode`,async t=>{
  const h=await harness(t,{connectors:type.startsWith('connector-')});
  const end=type==='polygon'?(polygonPending(h),null):connectorPending(h);
  assert.equal(h.command('view:form-mode').ok,true);const before=h.export();finishPending(h,type,end);
  assert.equal(digest(h.export()),digest(before),'Form mode must prevent pending creation mutation');
  assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);assert.equal(h.container.style.cursor,'');
});

for(const type of ['polygon','connector-straight'])for(const lifecycle of ['deactivate','dispose'])test(`${type} ${lifecycle} clears pending cursor and overlays`,async t=>{
  const h=await harness(t,{connectors:type.startsWith('connector-')});
  if(type==='polygon')polygonPending(h);else connectorPending(h);
  const before=h.export();
  const overlays=()=>document.querySelectorAll('.connector-points-overlay,.connector-preview').length+document.body.children.filter(node=>node.localName!=='main').length;
  assert.ok(overlays()>0,'Real drawing path created an overlay before lifecycle transition');
  h.handler[lifecycle]();assert.equal(h.container.style.cursor,'');assert.equal(overlays(),0,'Lifecycle must remove actual drawing overlays');
  assert.equal(digest(h.export()),digest(before));assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
});

for(const type of ['polygon','connector-straight'])test(`${type} pending document A gesture cannot mutate replacement document B`,async t=>{
  const h=await harness(t,{connectors:type.startsWith('connector-')}),replacement=replacementInput(type.startsWith('connector-'));
  const expected=inspect(replacement),originalHash=digest(replacement);
  const end=type==='polygon'?(polygonPending(h),null):connectorPending(h);
  h.wasm.loadDocument(replacement,'owned-variant-b.hwpx');h.handler.deactivate();h.handler.activateWithCaretPosition();
  finishPending(h,type,end);assert.deepEqual(inspect(h.export()),expected,'Pending A creation must not affect B');
  assert.equal(digest(replacement),originalHash,'Owned B source bytes remain immutable');
  assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);assert.equal(h.container.style.cursor,'');
});
