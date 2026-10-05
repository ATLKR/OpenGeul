import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {defaultShortcuts,matchShortcut}=await import(pathToFileURL(resolve(process.env.HOP_SOURCE ?? '.work/hop','apps/studio-host/src/command/shortcut-map.ts')));
const event=(values={})=>({key:'',code:'',ctrlKey:false,metaKey:false,shiftKey:false,altKey:false,...values});
for(const [name,platform,ua,primary] of [['Windows','Win32','Windows NT 10.0','ctrlKey'],['macOS','MacIntel','Mac OS X','metaKey']]) {
 for(const [key,shiftKey] of [['p',false],['P',false],['P',true],['ㅔ',false]]) {
  test(`${name}: ordinary ${key} shift=${shiftKey} reaches text editing`,()=>{
   Object.defineProperty(globalThis,'navigator',{value:{platform,userAgent:ua},configurable:true});
   assert.equal(matchShortcut(event({key,code:'KeyP',shiftKey}),defaultShortcuts),null);
  });
 }
 test(`${name}: print and function keys remain usable`,()=>{
  Object.defineProperty(globalThis,'navigator',{value:{platform,userAgent:ua},configurable:true});
  assert.equal(matchShortcut(event({key:'p',code:'KeyP',[primary]:true}),defaultShortcuts),'file:print');
  assert.equal(matchShortcut(event({key:'f6'}),defaultShortcuts),'format:style-dialog');
  assert.equal(matchShortcut(event({key:'f7'}),defaultShortcuts),'file:page-setup');
  assert.equal(matchShortcut(event({key:'p',[primary]:true,shiftKey:true}),defaultShortcuts),'table:block-product');
 });
}
