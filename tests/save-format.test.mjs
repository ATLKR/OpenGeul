import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveSavePath } from '../overlay/save-format.ts';
for (const [path, fallback, expectedPath, format] of [
  ['C:\\문서\\견적서.hwpx', 'hwp', 'C:\\문서\\견적서.hwpx', 'hwpx'],
  ['/tmp/Report.HWPX', 'hwp', '/tmp/Report.HWPX', 'hwpx'],
  ['/tmp/Report.HWP', 'hwpx', '/tmp/Report.HWP', 'hwp'],
  ['/tmp/견적서', 'hwpx', '/tmp/견적서.hwpx', 'hwpx'],
  ['C:\\folder.with.dots\\report', 'hwp', 'C:\\folder.with.dots\\report.hwp', 'hwp'],
]) test(`resolve ${path} using ${fallback}`, () => assert.deepEqual(resolveSavePath(path, fallback), {path: expectedPath, format}));
for (const path of ['', ' ', '/tmp/file.txt', '/tmp/file.hwpx.exe', '/tmp/', 'C:\\dir\\', '/tmp/a.', '/tmp/a.hwpx ', '/tmp/a\0.hwpx']) {
  test(`reject unsafe/unsupported target ${JSON.stringify(path)}`, () => assert.throws(() => resolveSavePath(path, 'hwp')));
}
