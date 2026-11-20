/** The HOP minimal WASM graph preserves HWP editing without advertising PDF import. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const hop=resolve(process.env.HOP_SOURCE??'.work/hop');
const vendor=resolve(hop,'apps/studio-host/vendor/rhwp-core');
const source=path=>import(pathToFileURL(resolve(hop,'third_party/rhwp/rhwp-studio/src',path)));
const native=await import(pathToFileURL(resolve(vendor,'rhwp.js')));
await native.default({module_or_path:readFileSync(resolve(vendor,'rhwp_bg.wasm'))});
const {WasmBridge}=await source('core/wasm-bridge.ts');
const {documentFileInputAccept,unsupportedDocumentMessage}=await source('command/file-system-access.ts');

test('minimal source-built engine reports unavailable PDF import and preserves ordinary HWPX editing',()=>{
 const bridge=new WasmBridge();
 try {
  assert.equal(bridge.hasPdfImportCapability(),false);
  assert.equal(native.PdfEditorReopen,undefined);
  assert.ok(!documentFileInputAccept(bridge.hasPdfImportCapability()).includes('.pdf'));
  assert.equal(unsupportedDocumentMessage('owned.pdf',false),'현재 빌드는 PDF 가져오기를 지원하지 않습니다.');
  const html=readFileSync(resolve(hop,'apps/studio-host/index.html'),'utf8');
  assert.match(html,/<input type="file" id="file-input" accept="\.hwp,\.hwpx"/);
  bridge.createNewDocument();bridge.insertText(0,0,0,'HWPX-EDIT-STILL-AVAILABLE');
  const bytes=bridge.exportHwpx(), reopened=new native.HwpDocument(bytes);
  try {assert.match(reopened.getTextFileUnicode(),/HWPX-EDIT-STILL-AVAILABLE/);}
  finally {reopened.free();}
 } finally {bridge.releaseDocument();}
});
