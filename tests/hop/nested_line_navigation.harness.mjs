/** Real engine and public routing; synthetic DOM page geometry/events only. */
import {prepared} from './nested_line_navigation.loader.mjs';
import {createShapeHistoryDom,parseGeneratedXml} from './shape_creation_history.dom.mjs';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {inflateRawSync,deflateRawSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const src=resolve(prepared,'third_party/rhwp/rhwp-studio/src');
export const source=name=>import(pathToFileURL(resolve(src,name)));
const vendor=resolve(prepared,'apps/studio-host/vendor/rhwp-core');
const native=await import(pathToFileURL(resolve(vendor,'rhwp.js')));
await native.default({module_or_path:readFileSync(resolve(vendor,'rhwp_bg.wasm'))});
const {WasmBridge}=await source('core/wasm-bridge.ts');
const {EventBus}=await source('core/event-bus.ts');
const {VirtualScroll}=await source('view/virtual-scroll.ts');
const {ViewportManager}=await source('view/viewport-manager.ts');
export const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const paths=['engine/cursor.ts','engine/input-handler.ts','engine/input-handler-keyboard.ts','engine/input-handler-text.ts','engine/history.ts','core/wasm-bridge.ts'].map(name=>resolve(src,name));
paths.push(resolve(vendor,'rhwp_bg.wasm'));
if(process.env.NESTED_LINE_NAVIGATION_CURSOR)paths.push(resolve(process.env.NESTED_LINE_NAVIGATION_CURSOR));
if(process.env.NESTED_LINE_NAVIGATION_BRIDGE)paths.push(resolve(process.env.NESTED_LINE_NAVIGATION_BRIDGE));
export const immutableHashes=new Map(paths.map(path=>[path,sha(readFileSync(path))]));

function entries(raw){
 const bytes=Buffer.from(raw),end=bytes.lastIndexOf(Buffer.from([0x50,0x4b,0x05,0x06]));let cursor=bytes.readUInt32LE(end+16);const files=new Map();
 for(let i=0;i<bytes.readUInt16LE(end+10);i++){
  const len=bytes.readUInt16LE(cursor+28),extra=bytes.readUInt16LE(cursor+30),comment=bytes.readUInt16LE(cursor+32),local=bytes.readUInt32LE(cursor+42),start=local+30+bytes.readUInt16LE(local+26)+bytes.readUInt16LE(local+28);
  const compressed=bytes.subarray(start,start+bytes.readUInt32LE(cursor+20));
  files.set(bytes.subarray(cursor+46,cursor+46+len).toString(),bytes.readUInt16LE(cursor+10)===8?inflateRawSync(compressed):Buffer.from(compressed));cursor+=46+len+extra+comment;
 }return files;
}
function crc32(bytes){let value=0xffffffff;for(const byte of bytes){value^=byte;for(let bit=0;bit<8;bit++)value=(value>>>1)^((value&1)?0xedb88320:0);}return (value^0xffffffff)>>>0;}
function zip(files){
 const local=[],central=[];let offset=0;
 for(const [path,raw] of files){const name=Buffer.from(path),method=path==='mimetype'?0:8,compressed=method===8?deflateRawSync(raw):raw,crc=crc32(raw);
  const l=Buffer.alloc(30);l.writeUInt32LE(0x04034b50);l.writeUInt16LE(20,4);l.writeUInt16LE(method,8);l.writeUInt32LE(crc,14);l.writeUInt32LE(compressed.length,18);l.writeUInt32LE(raw.length,22);l.writeUInt16LE(name.length,26);
  local.push(l,name,compressed);const c=Buffer.alloc(46);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(20,4);c.writeUInt16LE(20,6);c.writeUInt16LE(method,10);c.writeUInt32LE(crc,16);c.writeUInt32LE(compressed.length,20);c.writeUInt32LE(raw.length,24);c.writeUInt16LE(name.length,28);c.writeUInt32LE(offset,42);central.push(c,name);offset+=l.length+name.length+compressed.length;
 }
 const end=Buffer.alloc(22),directory=Buffer.concat(central);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(files.size,8);end.writeUInt16LE(files.size,10);end.writeUInt32LE(directory.length,12);end.writeUInt32LE(offset,16);return Buffer.concat([...local,directory,end]);
}
const escape=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function xml(node){return '<'+node.name+Object.entries(node.attrs).map(([k,v])=>' '+k+'="'+escape(v)+'"').join('')+'>'+escape(node.text)+node.children.map(xml).join('')+'</'+node.name+'>';}
const all=node=>[node,...node.children.flatMap(all)];
const child=(node,name)=>node.children.find(n=>n.localName===name);
const node=(name,attrs={},children=[],text='')=>({name:'hp:'+name,localName:name,attrs,children,text});
export function inspect(bytes){
 const root=parseGeneratedXml(entries(bytes).get('Contents/section0.xml').toString()),owners={};
 const text=p=>p.children.filter(n=>n.localName==='run').flatMap(r=>r.children.filter(n=>n.localName==='t').map(t=>t.text)).join('');
 function read(owner,path){owners[path]=owner.children.filter(n=>n.localName==='p').map(text);let ti=0;
  for(const p of owner.children.filter(n=>n.localName==='p'))for(const run of p.children.filter(n=>n.localName==='run'))for(const tbl of run.children.filter(n=>n.localName==='tbl')){
   const tp=path+'/t'+ti++;for(const row of tbl.children.filter(n=>n.localName==='tr'))for(const cell of row.children.filter(n=>n.localName==='tc')){const addr=child(cell,'cellAddr');read(child(cell,'subList'),tp+'/r'+addr.attrs.rowAddr+'c'+addr.attrs.colAddr);}
  }
 }read(root,'s0/body');return owners;
}

export function inputFixture(depth,text,{mixedStyle=false,paragraphs=[text],paragraphIndex=0}={}){
 // Actual native exported grid is the owned INPUT. Nesting/fixture paragraph
 // authoring occurs before any handler/history exists; never during tested UI.
 const seed=new WasmBridge();seed.createNewDocument();seed.createTableEx({sectionIdx:0,paraIdx:0,charOffset:0,rowCount:1,colCount:1,colWidths:[48000],rowHeights:[18000]});
 let files=entries(seed.exportHwpx());seed.releaseDocument();const root=parseGeneratedXml(files.get('Contents/section0.xml').toString()),base=all(root).find(n=>n.localName==='tbl');
 const template=structuredClone(child(child(child(base,'tr'),'tc'),'subList').children.find(n=>n.localName==='p'));
 const path=[];
 function make(level){
  const table=structuredClone(base),width=level===0?48000:level===depth-1?9000:24000,height=18000+(depth-level-1)*18000;table.attrs.id=String(2010000+level);child(table,'sz').attrs.width=String(width);child(table,'sz').attrs.height=String(height);
  const cell=child(child(table,'tr'),'tc');child(cell,'cellSz').attrs.width=String(width);child(cell,'cellSz').attrs.height=String(height);const sub=child(cell,'subList');
  function paragraph(value,id){const p=structuredClone(template);p.attrs.id=String(id);p.children=[node('run',{charPrIDRef:'0'},[node('t',{},[],value)])];return p;}
  if(level===depth-1){sub.children=paragraphs.map((value,i)=>paragraph(value,2020000+level*10+i));path.push({controlIndex:level===0?2:0,cellIndex:0,cellParaIndex:paragraphIndex});}
  else {path.push({controlIndex:level===0?2:0,cellIndex:0,cellParaIndex:1});const p=paragraph('',2020001+level*10);p.children=[node('run',{charPrIDRef:'0'},[make(level+1)])];sub.children=[paragraph('OUTER-'+level,2020000+level*10),p];}
  return table;
 }
 const nested=make(0),parent=all(root).find(n=>n.children.includes(base));parent.children[parent.children.indexOf(base)]=nested;
 for(const p of all(root).filter(n=>n.localName==='p'))p.children=p.children.filter(n=>n.localName!=='linesegarray');
 files.set('Contents/section0.xml',Buffer.from('<?xml version="1.0" encoding="UTF-8"?>'+xml(root)));
 const input=new WasmBridge();input.loadDocument(zip(files),'owned-navigation-input.hwpx');
 if(mixedStyle)input.applyCharFormatInCellByPath(0,0,JSON.stringify(path),3,9,JSON.stringify({fontSize:1800,bold:true}));
 const bytes=input.exportHwpx(),pageCount=input.pageCount;input.releaseDocument();
 // Independent native text-layout API on immutable INPUT (not keyboard output).
 // Product consumes explicit paint textLine groups; this oracle consumes the
 // native text-run identities and scalar charStart/charX boundaries instead.
 const oracle=new native.HwpDocument(bytes),rows=[];
 try{for(let page=0;page<pageCount;page++)for(const row of JSON.parse(oracle.getPageTextLayout(page)).runs??[]){
  if(row.secIdx===0&&row.parentParaIdx===0&&JSON.stringify(row.cellPath)===JSON.stringify(path))rows.push({...row,page});
 }}finally{oracle.free();}
 const groups=[];
 for(const row of rows){const baseline=row.y+row.h*0.85;let group=groups.find(g=>g.page===row.page&&Math.abs(g.baseline-baseline)<0.15);
  if(!group){group={page:row.page,baseline,start:row.charStart,end:row.charStart+Array.from(row.text).length,rows:[]};groups.push(group);}
  group.start=Math.min(group.start,row.charStart);group.end=Math.max(group.end,row.charStart+Array.from(row.text).length);group.rows.push(row);
 }
 const chars=Array.from(text),lines=groups.sort((a,b)=>a.start-b.start).map(g=>({...g,end:chars[g.end-1]==='\n'?g.end-1:g.end}));
 assert.ok(lines.length,'Actual native input has nested text layout');
 return {bytes,path,text,depth,lines,target:'s0/body'+('/t0/r0c0'.repeat(depth))};
}

export async function harness(t,input){
 const dom=createShapeHistoryDom(),names=['window','document','navigator','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLCanvasElement','Element','MouseEvent','KeyboardEvent','Event','localStorage','getComputedStyle','requestAnimationFrame','cancelAnimationFrame','__APP_VERSION__','__HOP_VERSION__'];
 const descriptors=new Map(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)])),realTimeout=globalThis.setTimeout,timers=new Set();
 for(const name of names){let value=dom.window[name];if(['getComputedStyle','requestAnimationFrame','cancelAnimationFrame'].includes(name))value=value.bind(dom.window);if(name.startsWith('__'))value='nested-navigation-test';Object.defineProperty(globalThis,name,{value,configurable:true});}
 globalThis.setTimeout=(...args)=>{const timer=realTimeout(...args);timers.add(timer);return timer;};
 const {InputHandler}=await source('engine/input-handler.ts'),{CommandRegistry}=await source('command/registry.ts'),{CommandDispatcher}=await source('command/dispatcher.ts');const {editCommands}=await import('@/command/commands/edit');
 const wasm=new WasmBridge();wasm.loadDocument(input.bytes,'owned-navigation-input.hwpx');const eventBus=new EventBus(),virtualScroll=new VirtualScroll(),viewport=new ViewportManager(eventBus);virtualScroll.setPageDimensions(Array.from({length:wasm.pageCount},(_,i)=>wasm.getPageInfo(i)));
 const container=document.getElementById('scroll-container'),content=document.getElementById('scroll-content'),canvas=content.querySelector('canvas'),rect={x:0,y:0,left:0,top:0,right:800,bottom:1200,width:800,height:1200};
 for(const el of [container,content,canvas]){el.getBoundingClientRect=()=>rect;Object.defineProperty(el,'clientWidth',{value:800});Object.defineProperty(el,'clientHeight',{value:1200});}
 let handler=new InputHandler(container,wasm,eventBus,virtualScroll,viewport);handler.activateWithCaretPosition();
 const registry=new CommandRegistry();registry.registerAll(editCommands.filter(c=>['edit:undo','edit:redo'].includes(c.id)));
 const context=()=>({hasDocument:wasm.pageCount>0,hasSelection:handler.hasSelection(),inTable:handler.isInTable(),inCellSelectionMode:handler.isInCellSelectionMode(),inPictureObjectSelection:handler.isInPictureObjectSelection(),inField:handler.isInField(),isEditable:true,editMode:'normal',isFormMode:false,canUndo:handler.canUndo(),canRedo:handler.canRedo()});
 const dispatcher=new CommandDispatcher(registry,{wasm,eventBus,getInputHandler:()=>handler,getContext:context,getViewportManager:()=>viewport},eventBus);handler.setDispatcher(dispatcher);const results=new Map();
 for(const button of document.querySelectorAll('button[data-cmd]'))button.addEventListener('click',()=>results.set(button.dataset.cmd,dispatcher.dispatchWithResult(button.dataset.cmd)));
 const command=id=>{document.querySelector(`button[data-cmd="${id}"]`).click();return results.get(id);};
 const area=()=>document.querySelector('textarea[aria-label="문서 편집 입력"]');
 const key=(key,options={})=>{area().focus();area().dispatchEvent(new dom.window.KeyboardEvent('keydown',{bubbles:true,key,code:key,...options}));};
 const type=text=>{area().focus();area().value=text;area().dispatchEvent(new dom.window.Event('input',{bubbles:true}));};
 const clickAtOffset=offset=>{
  const r=wasm.getCursorRectByPath(0,0,JSON.stringify(input.path),offset),x=virtualScroll.getPageLeftResolved(r.pageIndex,800)+r.x+0.1,y=virtualScroll.getPageOffset(r.pageIndex)+r.y+r.height/2;
  for(const type of ['mousedown','mouseup'])canvas.dispatchEvent(new dom.window.MouseEvent(type,{bubbles:true,button:0,buttons:type==='mouseup'?0:1,clientX:x,clientY:y}));
  assert.deepEqual(handler.getCursorPosition().cellPath,input.path,'Actual physical point must enter exact nested owner');
 };
 t.after(()=>{for(const timer of timers)clearTimeout(timer);globalThis.setTimeout=realTimeout;handler.dispose();wasm.releaseDocument();dom.window.close();for(const [name,descriptor] of descriptors)descriptor?Object.defineProperty(globalThis,name,descriptor):delete globalThis[name];for(const [path,hash] of immutableHashes)assert.equal(sha(readFileSync(path)),hash,'Original source/candidate/WASM unchanged');});
 return {wasm,get handler(){return handler;},virtualScroll,key,type,command,clickAtOffset,export:()=>wasm.exportHwpx(),inspect:()=>inspect(wasm.exportHwpx()),
  reopen(bytes){handler.dispose();wasm.loadDocument(bytes,'owned-navigation-reopened.hwpx');virtualScroll.setPageDimensions(Array.from({length:wasm.pageCount},(_,i)=>wasm.getPageInfo(i)));handler=new InputHandler(container,wasm,eventBus,virtualScroll,viewport);handler.setDispatcher(dispatcher);handler.activateWithCaretPosition();},
  position:()=>handler.getCursorPosition(),caret:()=>{const node=document.querySelector('.caret');return node?.style??null;},
 };
}
