/** Execute the real prepared HOP edit command with a controlled async clipboard.
 * Only document/input/OS-clipboard boundaries are doubled. This is not native
 * rich clipboard layout validation or a real user-file reproduction of HOP #96.
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {stripTypeScriptTypes} from 'node:module';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source = readFileSync(resolve(process.env.HOP_SOURCE ?? '.work/hop', 'apps/studio-host/src/command/commands/edit.ts'), 'utf8');
const boundary = 'type ClipboardInputHandler = {';
assert.equal(source.split(boundary).length, 2, 'Reviewed clipboard command boundary moved');
const body = stripTypeScriptTypes(source.slice(source.indexOf(boundary)))
  .replace('export const editCommands =', 'const editCommands =');

function harness({cell=false, context={}}={}) {
  const state = {generation:7, loaded:true, deleted:[], warnings:[], writes:[], delegates:[], copies:[]};
  state.selection = {start:{sectionIndex:0, paragraphIndex:0, charOffset:0},
    end:{sectionIndex:0, paragraphIndex:0, charOffset:4}};
  if (cell) for (const pos of Object.values(state.selection))
    Object.assign(pos, {parentParaIndex:0, controlIndex:1, cellIndex:0, cellParaIndex:0});
  const input = {getSelection:() => state.selection,
    performDelete:() => state.deleted.push({generation:state.generation, selection:JSON.stringify(state.selection)}),
    performCut:() => state.delegates.push('cut'), performCopy:() => state.delegates.push('copy')};
  state.handler = input;
  const wasm = {get documentGeneration(){return state.generation;}, hasLoadedDocument:() => state.loaded,
    copySelection:(...a) => state.copies.push(['body',...a]),
    copySelectionInCell:(...a) => state.copies.push(['cell',...a]),
    exportSelectionHtml:() => '<p style="text-align:center">KEEP</p>',
    exportSelectionInCellHtml:() => '<td>KEEP</td>', getClipboardText:() => 'KEEP'};
  const services = {wasm, getInputHandler:() => state.handler, getContext:() => context};
  let resolveWrite, rejectWrite;
  const write = new Promise((resolve,reject) => {resolveWrite=resolve;rejectWrite=reject;});
  const commands = runInNewContext(body+'\neditCommands;', {
    upstreamEditCommands:['cut','copy','paste'].map(action => ({id:'edit:'+action, execute(){}})),
    replaceUpstreamCommands:(_upstream, replacements) => replacements,
    prepareRhwpInternalClipboardHtml:(_input,html) => html,
    writeTextHtmlToClipboard:(text,html) => {state.writes.push({text,html});return write;},
    console:{warn:(...args) => state.warnings.push(args)},
  });
  const start = (action='cut') => commands.find(c => c.id==='edit:'+action).execute(services);
  const settle = async (error) => {
    if(error)rejectWrite(error);else resolveWrite();
    await new Promise(resolve => setImmediate(resolve));
  };
  return {state, start, settle};
}

test('normal cut waits for clipboard success then deletes once', async () => {
  const h=harness();h.start();assert.equal(h.state.deleted.length,0);
  await h.settle();assert.equal(h.state.deleted.length,1);assert.equal(h.state.writes.length,1);
  assert.equal(h.state.writes[0].text,'KEEP');assert.match(h.state.writes[0].html,/text-align:center/);
});
test('document replacement with identical selection coordinates never deletes the new document', async () => {
  const h=harness();h.start();h.state.generation++;
  await h.settle();assert.equal(h.state.deleted.length,0);
});
test('unloaded document never receives delayed delete', async () => {
  const h=harness();h.start();h.state.loaded=false;
  await h.settle();assert.equal(h.state.deleted.length,0);
});
test('new handler cannot authorize a stale handler deletion', async () => {
  const h=harness();h.start();h.state.handler={...h.state.handler};
  await h.settle();assert.equal(h.state.deleted.length,0);
});
test('selection snapshot must be immutable before the asynchronous write', async () => {
  const h=harness();h.start();h.state.selection.end.charOffset=9;
  await h.settle();assert.equal(h.state.deleted.length,0);
});
test('changed selection object never deletes a different range', async () => {
  const h=harness();h.start();h.state.selection={...h.state.selection,end:{...h.state.selection.end,charOffset:9}};
  await h.settle();assert.equal(h.state.deleted.length,0);
});
test('clipboard rejection keeps document contents and is handled', async () => {
  const h=harness();h.start();await h.settle(new Error('clipboard-denied'));
  assert.equal(h.state.deleted.length,0);assert.equal(h.state.warnings.length,1);
});
test('copy keeps the source regardless of subsequent document replacement', async () => {
  const h=harness();h.start('copy');h.state.generation++;
  await h.settle();assert.equal(h.state.deleted.length,0);assert.equal(h.state.writes.length,1);
});
test('empty selection and absent handler do not write or delete', async () => {
  for(const part of ['selection','handler']){
    const h=harness();h.state[part]=null;h.start();await h.settle();
    assert.equal(h.state.deleted.length,0);assert.equal(h.state.writes.length,0);
  }
});
test('cell text cut retains existing export path', async () => {
  const h=harness({cell:true});h.start();await h.settle();
  assert.equal(h.state.deleted.length,1);assert.equal(h.state.copies[0][0],'cell');
});
test('cell text cut does not delete in a replacement document', async () => {
  const h=harness({cell:true});h.start();h.state.generation++;
  await h.settle();assert.equal(h.state.deleted.length,0);
});
test('invalid document generation cannot authorize destructive cut', async () => {
  for(const value of [undefined,null,NaN,Infinity,-1,7.1,'7',true]){
    const h=harness();h.state.generation=value;h.start();await h.settle();
    assert.equal(h.state.deleted.length,0,`invalid generation ${String(value)}`);
  }
});
test('picture and table object delegation remains separate and unchanged', async () => {
  for(const key of ['inPictureObjectSelection','inTableObjectSelection']){
    const h=harness({context:{[key]:true}});h.start();h.start('copy');await h.settle();
    assert.deepEqual(h.state.delegates,['cut','copy']);assert.equal(h.state.writes.length,0);
  }
});
