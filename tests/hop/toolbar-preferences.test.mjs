import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const {initToolbarLabels,toolbarLabelsCommand}=await import(pathToFileURL(resolve(
  process.env.HOP_SOURCE ?? '.work/hop','apps/studio-host/src/host/toolbar-labels.ts',
)));
const key='hop.toolbar-labels';

function toolbarHarness(t,raw=null,{readDenied=false,writeDenied=false}={}) {
  const saved=new Map(raw===null ? [] : [[key,raw]]);
  const writes=[];
  const listeners=new Map();
  const items=Array.from({length:2},()=>({
    active:false,attributes:{},
    classList:{toggle(name,visible){assert.equal(name,'active');this.item.active=visible;}},
    setAttribute(name,value){this.attributes[name]=value;},
  }));
  for(const item of items) item.classList.item=item;
  const root={dataset:{}};
  const globals={
    document:{documentElement:root,querySelectorAll(selector){assert.equal(selector,'[data-cmd="view:toolbar-labels"]');return items;}},
    window:{addEventListener(type,listener){listeners.set(type,listener);}},
    localStorage:{
      getItem(name){if(readDenied)throw Error('denied');return saved.get(name) ?? null;},
      setItem(name,value){if(writeDenied)throw Error('denied');saved.set(name,value);writes.push([name,value]);},
    },
  };
  for(const [name,value] of Object.entries(globals)) {
    const previous=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{value,configurable:true});
    t.after(()=>previous ? Object.defineProperty(globalThis,name,previous) : delete globalThis[name]);
  }
  const assertVisible=(visible)=>{
    assert.equal(root.dataset.toolbarLabels,visible ? 'shown' : 'hidden');
    for(const item of items) {
      assert.equal(item.active,visible);
      assert.equal(item.attributes['aria-checked'],String(visible));
    }
  };
  return {saved,writes,assertVisible,storageEvent:(event)=>listeners.get('storage')(event)};
}

for(const [raw,visible] of [[null,true],['shown',true],['hidden',false],['garbage',true]]) {
  test(`native saved ${raw} initializes labels=${visible} and the menu state`,(t)=>{
    const ui=toolbarHarness(t,raw);
    initToolbarLabels();
    ui.assertVisible(visible);
    assert.deepEqual(ui.writes,[]);
  });
}

test('denied storage reads preserve the visible default',(t)=>{
  const ui=toolbarHarness(t,'hidden',{readDenied:true});
  initToolbarLabels();
  ui.assertVisible(true);
});

test('an existing OpenGeul hidden preference migrates to the native preference',(t)=>{
  const ui=toolbarHarness(t);
  ui.saved.set('opengeul.toolbar.labels.visible','false');
  initToolbarLabels();
  ui.assertVisible(false);
  assert.deepEqual(ui.writes,[[key,'hidden']]);
});

test('a native visible preference takes precedence over the legacy hidden value',(t)=>{
  const ui=toolbarHarness(t,'shown');
  ui.saved.set('opengeul.toolbar.labels.visible','false');
  initToolbarLabels();
  ui.assertVisible(true);
  assert.deepEqual(ui.writes,[]);
});

test('denied migration writes still preserve the legacy hidden preference',(t)=>{
  const ui=toolbarHarness(t,null,{writeDenied:true});
  ui.saved.set('opengeul.toolbar.labels.visible','false');
  assert.doesNotThrow(()=>initToolbarLabels());
  ui.assertVisible(false);
  assert.deepEqual(ui.writes,[]);
});

test('the native command toggles labels, menu accessibility state, and its saved preference',(t)=>{
  const ui=toolbarHarness(t);
  initToolbarLabels();
  toolbarLabelsCommand.execute();
  ui.assertVisible(false);
  toolbarLabelsCommand.execute();
  ui.assertVisible(true);
  assert.deepEqual(ui.writes,[[key,'hidden'],[key,'shown']]);
});

test('denied storage writes still apply the current window preference',(t)=>{
  const ui=toolbarHarness(t,null,{writeDenied:true});
  initToolbarLabels();
  assert.doesNotThrow(()=>toolbarLabelsCommand.execute());
  ui.assertVisible(false);
  assert.deepEqual(ui.writes,[]);
});

test('storage changes synchronize other windows and ignore unrelated preferences',(t)=>{
  const ui=toolbarHarness(t);
  initToolbarLabels();
  ui.saved.set(key,'hidden');
  ui.storageEvent({key:'unrelated'});
  ui.assertVisible(true);
  ui.storageEvent({key});
  ui.assertVisible(false);
  ui.saved.delete(key);
  ui.storageEvent({key:null});
  ui.assertVisible(true);
  assert.deepEqual(ui.writes,[]);
});
