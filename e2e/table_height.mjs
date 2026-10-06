/** Real production-engine geometry regression; no DOM test bridge or font binaries. */
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
const [mode, vendorArgument, outputArgument, expectation] = process.argv.slice(2);
assert.ok(['generate', 'verify'].includes(mode), 'Expected generate or verify');
assert.ok(vendorArgument && outputArgument, 'Expected WASM folder and fixture folder');
const vendor = resolve(vendorArgument), output = resolve(outputArgument);
const {default: init, HwpDocument} = await import(pathToFileURL(join(vendor, 'rhwp.js')));
await init({module_or_path: readFileSync(join(vendor, 'rhwp_bg.wasm'))});
mkdirSync(output, {recursive: true});
function checked(raw) {const value = JSON.parse(raw); assert.equal(value.ok, true); return value;}
if (mode === 'generate') {
  const doc = HwpDocument.createEmpty();
  try {
    doc.createBlankDocument();
    const {paraIdx, controlIdx} = checked(doc.createTable(0, 0, 0, 1, 1));
    for (let i = 0; i < 5; i++) {
      const text = `Row ${i} lastline`;
      checked(doc.insertTextInCell(0, paraIdx, controlIdx, 0, i, 0, text));
      if (i < 4) checked(doc.splitParagraphInCell(0, paraIdx, controlIdx, 0, i, text.length));
    }
    writeFileSync(join(output, 'table-base.hwpx'), doc.exportHwpx());
  } finally {doc.free();}
} else {
  assert.ok(expectation === undefined || expectation === '--expect-clipping');
  const red = expectation === '--expect-clipping';
  const reports = [];
  function collect(node, type) {
    return [...(node.type === type ? [node] : []), ...(node.children ?? []).flatMap(child => collect(child, type))];
  }
  function inspect(doc, spacing, phase) {
    const tree = JSON.parse(doc.getPageRenderTree(0));
    const cells = collect(tree, 'Cell');
    assert.equal(cells.length, 1, 'Synthetic table must render one cell');
    const cell = cells[0], lines = collect(cell, 'TextLine');
    assert.equal(lines.length, 5, 'All five lines must reach the renderer');
    const text = collect(cell, 'TextRun').map(node => node.text).join('');
    for (let i = 0; i < 5; i++) assert.equal(text.split(`Row ${i} lastline`).length - 1, 1);
    const bottom = Math.max(...lines.map(line => line.bbox.y + line.bbox.h));
    const overflow = bottom - cell.bbox.y - cell.bbox.h;
    assert.ok(Number.isFinite(overflow));
    // Preserve compression BETWEEN lines; only a terminal negative trailing is excluded.
    const pitch = (1000 + spacing) * 96 / 7200;
    for (let i = 1; i < 5; i++) assert.ok(Math.abs(lines[i].bbox.y - lines[i-1].bbox.y - pitch) < 0.25);
    const expectedHeight = (5 * (1000 + spacing) + (red ? 0 : Math.max(-spacing, 0)) + 282) * 96 / 7200;
    assert.ok(Math.abs(cell.bbox.h - expectedHeight) < 0.25, `height ${cell.bbox.h} != ${expectedHeight}`);
    if (red && spacing < 0) assert.ok(overflow > 1, 'Baseline must exhibit actual glyph clipping');
    else assert.ok(overflow <= 0.25, `Terminal line clipped by ${overflow.toFixed(3)}px`);
    reports.push({spacing, phase, height: cell.bbox.h, overflow});
  }
  for (const spacing of [-300, 0, 600]) {
    const doc = new HwpDocument(readFileSync(join(output, `table-spacing-${spacing}.hwpx`)));
    try {
      inspect(doc, spacing, 'opened');
      if (!red) {
        const reopened = new HwpDocument(doc.exportHwpx());
        try {inspect(reopened, spacing, 'hwpx-reopened');} finally {reopened.free();}
      }
    } finally {doc.free();}
  }
  writeFileSync(join(output, red ? 'table-red.json' : 'table-green.json'), JSON.stringify(reports, null, 2) + '\n');
  console.log(`${red ? 'EXPECTED RED' : 'GREEN'}: ${reports.length} real-engine geometry checks`, reports);
}
