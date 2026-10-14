/** Owned field/control INPUT setup before fresh real handler/history. */
import assert from 'node:assert/strict';
import {inflateRawSync,deflateRawSync} from 'node:zlib';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {prepared} from './nested_line_navigation.loader.mjs';
import {inputFixture,source} from './nested_line_navigation.harness.mjs';
import {parseGeneratedXml} from './shape_creation_history.dom.mjs';
const {WasmBridge}=await source('core/wasm-bridge.ts');
const native=await import(pathToFileURL(resolve(prepared,'apps/studio-host/vendor/rhwp-core/rhwp.js')));
export const wrappedText='ALPHA BETA GAMMA DELTA EPSILON ZETA ETA THETA IOTA KAPPA LAMBDA MU';
function entries(raw){const b=Buffer.from(raw),end=b.lastIndexOf(Buffer.from([80,75,5,6]));let c=b.readUInt32LE(end+16);const f=new Map();for(let i=0;i<b.readUInt16LE(end+10);i++){const len=b.readUInt16LE(c+28),extra=b.readUInt16LE(c+30),comment=b.readUInt16LE(c+32),local=b.readUInt32LE(c+42),start=local+30+b.readUInt16LE(local+26)+b.readUInt16LE(local+28),raw=b.subarray(start,start+b.readUInt32LE(c+20));f.set(b.subarray(c+46,c+46+len).toString(),b.readUInt16LE(c+10)===8?inflateRawSync(raw):Buffer.from(raw));c+=46+len+extra+comment;}return f;}
function crc32(b){let c=0xffffffff;for(const byte of b){c^=byte;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xedb88320:0);}return (c^0xffffffff)>>>0;}
function zip(f){const local=[],central=[];let offset=0;for(const [path,raw] of f){const name=Buffer.from(path),method=path==='mimetype'?0:8,data=method===8?deflateRawSync(raw):raw,crc=crc32(raw),l=Buffer.alloc(30),c=Buffer.alloc(46);l.writeUInt32LE(0x04034b50);l.writeUInt16LE(20,4);l.writeUInt16LE(method,8);l.writeUInt32LE(crc,14);l.writeUInt32LE(data.length,18);l.writeUInt32LE(raw.length,22);l.writeUInt16LE(name.length,26);local.push(l,name,data);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(20,4);c.writeUInt16LE(20,6);c.writeUInt16LE(method,10);c.writeUInt32LE(crc,16);c.writeUInt32LE(data.length,20);c.writeUInt32LE(raw.length,24);c.writeUInt16LE(name.length,28);c.writeUInt32LE(offset,42);central.push(c,name);offset+=l.length+name.length+data.length;}const d=Buffer.concat(central),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(f.size,8);end.writeUInt16LE(f.size,10);end.writeUInt32LE(d.length,12);end.writeUInt32LE(offset,16);return Buffer.concat([...local,d,end]);}
const all=n=>[n,...n.children.flatMap(all)];
const child=(n,name)=>n.children.find(c=>c.localName===name);
const escape=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const xml=n=>'<'+n.name+Object.entries(n.attrs).map(([k,v])=>' '+k+'="'+escape(v)+'"').join('')+'>'+escape(n.text)+n.children.map(xml).join('')+'</'+n.name+'>';
const textNode=value=>({name:'hp:t',localName:'t',attrs:{},children:[],text:value});
export function nativeInputLayout(input){const doc=new native.HwpDocument(input.bytes);try{return JSON.parse(doc.getPageTextLayout(0)).runs.filter(r=>JSON.stringify(r.cellPath)===JSON.stringify(input.path));}finally{doc.free();}}
export function fieldInput(depth,guide='ClickHere',value=null){
 const input=inputFixture(depth,wrappedText),w=new WasmBridge();w.loadDocument(input.bytes,'owned-nested-field-input.hwpx');const result=w.insertClickHereField({sectionIndex:0,paragraphIndex:0,charOffset:7,parentParaIndex:0,cellPath:input.path},guide,'owned memo','ownedNestedField',true);assert.equal(result.ok,true);input.fieldId=result.fieldId;if(value!==null){const filled=w.setFieldValueByName('ownedNestedField',value);assert.equal(filled.ok,true);assert.equal(filled.newValue,value);}input.bytes=w.exportHwpx();input.text=w.getTextInCellByPath(0,0,JSON.stringify(input.path),0,w.getCellParagraphLengthByPath(0,0,JSON.stringify(input.path)));w.releaseDocument();return input;
}
export function nativeInputLines(input){
 const rows=nativeInputLayout(input).filter(r=>r.secIdx===0&&r.paraIdx===0&&Number.isSafeInteger(r.charStart)&&r.text.length>0),groups=[];let logicalStart=0;
 for(const row of rows.sort((a,b)=>a.charStart-b.charStart)){const baseline=row.y+row.h*0.85;let group=groups.find(g=>Math.abs(g.baseline-baseline)<0.15);const start=logicalStart;logicalStart+=Array.from(row.text).length;if(!group){group={baseline,start,end:logicalStart,rows:[]};groups.push(group);}group.start=Math.min(group.start,start);group.end=Math.max(group.end,logicalStart);group.rows.push({...row,logicalStart:start});}
 assert.equal(rows.map(r=>r.text).join(''),input.text,'Independent native source-backed rows must cover exact logical INPUT text');return groups.sort((a,b)=>a.start-b.start);
}
export function inlineEquations(bytes){const root=parseGeneratedXml(entries(bytes).get('Contents/section0.xml').toString()),table=all(root).filter(n=>n.localName==='tbl').at(-1);return all(table).filter(n=>n.localName==='equation').map(n=>({id:n.attrs.id,script:child(n,'script').text,treatAsChar:child(n,'pos').attrs.treatAsChar}));}
export function inlineEquationInput(depth){
 const input=inputFixture(depth,wrappedText),seed=new WasmBridge();seed.createNewDocument();assert.equal(seed.insertEquation(0,0,0,'x^2',1000,0).ok,true);const seedFiles=entries(seed.exportHwpx());seed.releaseDocument();
 const equation=structuredClone(all(parseGeneratedXml(seedFiles.get('Contents/section0.xml').toString())).find(n=>n.localName==='equation'));assert.equal(child(equation,'pos').attrs.treatAsChar,'1');
 const files=entries(input.bytes),root=parseGeneratedXml(files.get('Contents/section0.xml').toString()),table=all(root).filter(n=>n.localName==='tbl').at(-1),p=child(child(child(child(table,'tr'),'tc'),'subList'),'p'),run=child(p,'run');run.children=[textNode(wrappedText.slice(0,5)),equation,textNode(wrappedText.slice(5))];
 for(const node of all(root).filter(n=>n.localName==='p'))node.children=node.children.filter(n=>n.localName!=='linesegarray');files.set('Contents/section0.xml',Buffer.from('<?xml version="1.0" encoding="UTF-8"?>'+xml(root)));
 const w=new WasmBridge();w.loadDocument(zip(files),'owned-nested-inline-equation-input.hwpx');const len=w.getCellParagraphLengthByPath(0,0,JSON.stringify(input.path));assert.equal(w.getTextInCellByPath(0,0,JSON.stringify(input.path),0,len),wrappedText);assert.equal(len,Array.from(wrappedText).length);input.bytes=w.exportHwpx();w.releaseDocument();return input;
}
