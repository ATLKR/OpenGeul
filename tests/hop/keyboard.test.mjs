import test from 'node:test';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';

const hop=resolve(process.env.HOP_SOURCE ?? '.work/hop');
const rhwp=resolve(process.env.RHWP_SOURCE ?? `${hop}/third_party/rhwp`);
const upstream=(path)=>import(pathToFileURL(resolve(rhwp,'rhwp-studio/src',path)));
const {defaultShortcuts,matchShortcut}=await import(pathToFileURL(resolve(hop,'apps/studio-host/src/command/shortcut-map.ts')));
const {onKeyDown,handleCtrlKey}=await upstream('engine/input-handler-keyboard.ts');
const {CommandDispatcher}=await upstream('command/dispatcher.ts');
const {CommandRegistry}=await upstream('command/registry.ts');
const {formatCommands}=await upstream('command/commands/format.ts');
const {PicturePropsDialog}=await upstream('ui/picture-props-dialog.ts');
const objectProperties=formatCommands.find(({id})=>id==='format:object-properties');

const event=(values={})=>({
  key:'',code:'',ctrlKey:false,metaKey:false,shiftKey:false,altKey:false,
  isComposing:false,keyCode:0,defaultPrevented:false,
  preventDefault(){this.defaultPrevented=true;},...values,
});

function installPlatform(t,platform,userAgent) {
  const previous=Object.getOwnPropertyDescriptor(globalThis,'navigator');
  Object.defineProperty(globalThis,'navigator',{value:{platform,userAgent},configurable:true});
  t.after(()=>previous ? Object.defineProperty(globalThis,'navigator',previous) : delete globalThis.navigator);
}

function keyboardHarness(t,{picture=false,formMode=false}={}) {
  let pictureSelected=picture;
  const opened=[];
  const executed=[];
  const previousOpen=PicturePropsDialog.prototype.open;
  PicturePropsDialog.prototype.open=function(...args){opened.push(args);};
  t.after(()=>{PicturePropsDialog.prototype.open=previousOpen;});
  const cursor={
    isInHeaderFooter:()=>false,isInFootnote:()=>false,
    isInPictureObjectSelection:()=>pictureSelected,isInTableObjectSelection:()=>false,
    isInBlockSelectionMode:()=>false,isInCellSelectionMode:()=>false,
    isInCell:()=>false,getPosition:()=>({sectionIndex:0,paragraphIndex:0,charOffset:0}),
  };
  const handler={
    active:true,cursor,handleCtrlKey,
    isInPictureObjectSelection:()=>pictureSelected,isInTableObjectSelection:()=>false,
    getSelectedPictureRef:()=>({sec:0,ppi:1,ci:2,type:'image'}),
    exitPictureObjectSelectionIfNeeded(){pictureSelected=false;},
  };
  const registry=new CommandRegistry();
  registry.register(objectProperties);
  for(const id of ['file:print','format:style-dialog','file:page-setup','table:block-product']) {
    registry.register({id,execute(){executed.push(id);}});
  }
  const eventBus={emit(){}};
  const services={eventBus,wasm:{},getInputHandler:()=>handler,getContext:()=>({
    hasDocument:true,isFormMode:formMode,inPictureObjectSelection:pictureSelected,inTableObjectSelection:false,
  })};
  handler.dispatcher=new CommandDispatcher(registry,services,eventBus);
  return {handler,opened,executed,isPictureSelected:()=>pictureSelected};
}

for(const [name,platform,ua,primary,nonPrimary] of [
  ['Windows','Win32','Windows NT 10.0','ctrlKey','metaKey'],
  ['macOS','MacIntel','Mac OS X','metaKey','ctrlKey'],
]) {
  for(const [key,shiftKey] of [['p',false],['P',false],['P',true],['ㅔ',false]]) {
    test(`${name}: ordinary ${key} shift=${shiftKey} remains available for body typing`,(t)=>{
      installPlatform(t,platform,ua);
      const {handler,opened}=keyboardHarness(t);
      const e=event({key,code:'KeyP',shiftKey});
      onKeyDown.call(handler,e);
      assert.equal(e.defaultPrevented,false);
      assert.deepEqual(opened,[]);
    });
  }
  for(const key of ['p','P','ㅔ']) {
    test(`${name}: ${key} opens properties while a picture remains selected`,(t)=>{
      installPlatform(t,platform,ua);
      const {handler,opened,isPictureSelected}=keyboardHarness(t,{picture:true});
      const e=event({key,code:'KeyP'});
      onKeyDown.call(handler,e);
      assert.equal(e.defaultPrevented,true);
      assert.equal(isPictureSelected(),true);
      assert.deepEqual(opened,[[0,1,2,'image']]);
    });
  }
  test(`${name}: disabled object properties in form mode do not consume p`,(t)=>{
    installPlatform(t,platform,ua);
    const {handler,opened}=keyboardHarness(t,{formMode:true});
    const e=event({key:'p',code:'KeyP'});
    onKeyDown.call(handler,e);
    assert.equal(e.defaultPrevented,false);
    assert.deepEqual(opened,[]);
  });
  test(`${name}: print, function keys, and modified P keep their commands`,(t)=>{
    installPlatform(t,platform,ua);
    const {handler,executed}=keyboardHarness(t);
    for(const [values,id] of [
      [{key:'p',code:'KeyP',[primary]:true},'file:print'],
      [{key:'F6'},'format:style-dialog'],
      [{key:'F7'},'file:page-setup'],
      [{key:'p',code:'KeyP',[primary]:true,shiftKey:true},'table:block-product'],
    ]) {
      const e=event(values);
      onKeyDown.call(handler,e);
      assert.equal(e.defaultPrevented,true,id);
      assert.equal(executed.at(-1),id);
      assert.equal(matchShortcut(e,defaultShortcuts),id);
    }
  });
  test(`${name}: the non-primary system modifier does not trigger plain P`,(t)=>{
    installPlatform(t,platform,ua);
    const {handler,opened}=keyboardHarness(t);
    const e=event({key:'p',code:'KeyP',[nonPrimary]:true});
    onKeyDown.call(handler,e);
    assert.equal(e.defaultPrevented,false);
    assert.deepEqual(opened,[]);
    assert.equal(matchShortcut(e,defaultShortcuts),null);
  });
}

test('an attempted unmodified command that throws still consumes its key',(t)=>{
  installPlatform(t,'Win32','Windows NT 10.0');
  const {handler}=keyboardHarness(t);
  const registry=new CommandRegistry();
  registry.register({...objectProperties,canExecute:()=>true,execute(){throw Error('dialog failed');}});
  handler.dispatcher=new CommandDispatcher(registry,{getContext:()=>({isFormMode:false})},{emit(){}});
  const previousError=console.error;
  console.error=()=>{};
  t.after(()=>{console.error=previousError;});
  const e=event({key:'p',code:'KeyP'});
  onKeyDown.call(handler,e);
  assert.equal(e.defaultPrevented,true);
});

test('the native object-properties command requires a picture or table selection',()=>{
  assert.equal(objectProperties.canExecute({inPictureObjectSelection:false,inTableObjectSelection:false}),false);
  assert.equal(objectProperties.canExecute({inPictureObjectSelection:true,inTableObjectSelection:false}),true);
  assert.equal(objectProperties.canExecute({inPictureObjectSelection:false,inTableObjectSelection:true}),true);
});
