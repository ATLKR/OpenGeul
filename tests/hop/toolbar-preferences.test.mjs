import test from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../../overlay/hop-fixes/toolbar-preferences.ts';
for(const [raw,want] of [[null,true],['true',true],['false',false],['garbage',true]]) {
 test(`saved ${raw} means labels=${want}`,()=>{assert.equal(api.readToolbarLabels({getItem:()=>raw}),want);});
}
test('storage read denial preserves the default',()=>{assert.equal(api.readToolbarLabels({getItem(){throw Error('denied')}}),true);});
test('storage write denial does not crash the UI',()=>{assert.equal(api.writeToolbarLabels({setItem(){throw Error('denied')}},false),false);});
test('only the namespaced boolean preference is persisted',()=>{const writes=[];assert.equal(api.writeToolbarLabels({setItem:(...args)=>writes.push(args)},false),true);assert.deepEqual(writes,[['opengeul.toolbar.labels.visible','false']]);});
