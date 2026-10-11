/** HOP #94: exercise the actual prepared host function, not a duplicate implementation.
 * Only DOM/font/canvas boundaries are doubled. Windows E2E remains a separate gate.
 * Removing the capture/restore around loadDocument makes the narrow desktop cases fail.
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {stripTypeScriptTypes} from 'node:module';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source = readFileSync(resolve(process.env.HOP_SOURCE ?? '.work/hop', 'apps/studio-host/src/main.ts'), 'utf8');
const start = 'async function initializeDocument(';
const end = '\nasync function canReplaceCurrentDocument(';
assert.equal(source.split(start).length, 2, 'Expected exactly one real initialization function');
assert.equal(source.split(end).length, 2, 'Expected its unchanged function boundary');
const begin = source.indexOf(start), finish = source.indexOf(end, begin);
assert.ok(finish > begin, 'Initialization source boundary moved');
const code = stripTypeScriptTypes(source.slice(begin, finish));

async function initialize({desktop, width=960, zoom=1.5, fail=false, hasView=true, fonts=[]}) {
  const state = {zoom, calls:[], errors:[], clean:0, activated:0};
  const viewport = {getZoom:() => state.zoom, setZoom:value => {state.calls.push(value); state.zoom=value;}};
  const canvasView = hasView ? {
    prepareDocumentLoad() {}, getViewportManager:() => viewport,
    async loadDocument() {
      await Promise.resolve();
      if (fail) throw new Error('render-load-failed');
      // The pinned CanvasView applies mobile auto-fit below 1024px in either runtime.
      if (width < 1024) viewport.setZoom(0.91);
    },
  } : null;
  const context = {
    canvasView, isTauriRuntime:() => desktop, window:{innerWidth:width},
    sbMessage:() => ({textContent:''}), sbSection:() => ({textContent:''}),
    totalSections:0, homeScreen:null,
    loadWebFonts:async (values, progress) => {progress(values.length, values.length);},
    inputHandler:{deactivate(){}, activateWithCaretPosition(){state.activated++;}},
    toolbar:{setEnabled(){}, initFontDropdown(){}, initStyleDropdown(){}},
    documentState:{markClean(){state.clean++;}},
    console:{error:(...args) => state.errors.push(args)}, alert() {},
  };
  const load = runInNewContext(code+'\ninitializeDocument;', context);
  await load({pageCount:1, sectionCount:1, fontsUsed:fonts}, 'Synthetic document');
  return state;
}

for (const width of [960, 989, 1023, 1024, 1025, 1280]) {
  test(`desktop opening at ${width}px preserves the chosen 150% zoom`, async () => {
    const state = await initialize({desktop:true, width});
    assert.equal(state.zoom, 1.5);
    assert.equal(state.clean, 1); assert.equal(state.activated, 1);
    assert.equal(state.errors.length, 0);
  });
}
for (const width of [360, 960, 1023]) {
  test(`browser opening at ${width}px keeps its existing automatic fit`, async () => {
    const state = await initialize({desktop:false, width});
    assert.equal(state.zoom, 0.91); assert.deepEqual(state.calls, [0.91]);
    assert.equal(state.errors.length, 0);
  });
}
test('wide browser preserves zoom without a desktop override', async () => {
  const state = await initialize({desktop:false, width:1280});
  assert.equal(state.zoom, 1.5); assert.deepEqual(state.calls, []);
});
test('desktop minimum and maximum zoom survive asynchronous font/document loading', async () => {
  for (const zoom of [0.1, 4.0]) {
    const state = await initialize({desktop:true, zoom, fonts:['Arial']});
    assert.equal(state.zoom, zoom); assert.equal(state.errors.length, 0);
  }
});
test('failed document load is not restored or marked clean', async () => {
  const state = await initialize({desktop:true, fail:true});
  assert.deepEqual(state.calls, []); assert.equal(state.clean, 0); assert.equal(state.activated, 0);
  assert.equal(state.errors.length, 1); assert.match(String(state.errors[0][1]), /render-load-failed/);
});
test('absent canvas keeps the existing optional-view path without a new exception', async () => {
  const state = await initialize({desktop:true, hasView:false});
  assert.deepEqual(state.calls, []); assert.equal(state.errors.length, 0);
});
