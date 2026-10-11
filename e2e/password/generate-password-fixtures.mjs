/** Task-authored inputs generated through the library's bundled blank template. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const [wasmArgument, existingArgument, outputArgument, ...extra] = process.argv.slice(2);
assert(wasmArgument && existingArgument && outputArgument && extra.length === 0,
  'Usage: node generate-password-fixtures.mjs <wasmDir> <existingE2eFixtureDir> <outDir>');
const wasmDir = resolve(wasmArgument);
const existingDir = resolve(existingArgument);
const output = resolve(outputArgument);
const verifier = join(dirname(fileURLToPath(import.meta.url)), 'verify-password-fixtures.py');
const python = process.env.OPENGEUL_PROBE_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
const pythonOptions = {encoding: 'utf8', env: {...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8'}};
const password = 'OpenGeul-native-123456'; // Public, task-owned QA value; not a user secret.
const expectedText = 'OpenGeul owned encrypted native QA 2026-10-11 — 한글 & <xml> Ω 123';
const priorExpectedText = 'OpenGeul fixture 한글 가나다 & <xml> Ω 123';
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const read = (name) => readFileSync(join(wasmDir, name));
const js = read('rhwp.js');
const wasm = read('rhwp_bg.wasm');
assert.equal(wasm.subarray(0, 8).toString('hex'), '0061736d01000000', 'valid WASM module');
const artifactNames = ['rhwp.js', 'rhwp_bg.wasm', 'rhwp.d.ts', 'rhwp_bg.wasm.d.ts', 'package.json', 'LICENSE'];
for (const name of artifactNames) {
  const info = lstatSync(join(wasmDir, name));
  assert(info.isFile() && !info.isSymbolicLink(), `regular artifact required: ${name}`);
}
assert.equal(JSON.parse(read('package.json').toString('utf8')).version, '0.8.7', 'package version');

// Final qualification requires the source-bound rebuild manifest and matching
// bytes. A pristine upstream artifact can never silently acquire that label.
let provenance = null;
if (existsSync(join(wasmDir, 'OPEN_GEUL_WASM.json'))) {
  provenance = JSON.parse(read('OPEN_GEUL_WASM.json').toString('utf8'));
  const lock = JSON.parse(readFileSync(resolve('config/upstream.lock.json'), 'utf8'));
  assert.equal(lock.hop?.version, '0.4.5');
  assert.equal(lock.hop?.commit, '34bd15c97e0851627cb7f055042c5340198aeb7f');
  assert.equal(lock.rhwp?.version, '0.8.7');
  assert.equal(lock.rhwp?.commit, '1a76570e833917d15817415a53c09ad61ab3203f');
  assert.deepEqual(provenance.upstream, lock, 'source-bound checkout upstream lock');
  assert.equal(provenance.namespaceHelper,
    sha256(readFileSync(resolve('overlay/hwpx_namespaces.rs'))), 'source-bound namespace helper');
  assert.equal(provenance.namespacePatcher,
    sha256(readFileSync(resolve('scripts/patch_namespaces.py'))), 'source-bound namespace patcher');
  for (const name of artifactNames) {
    assert.equal(sha256(read(name)), provenance.artifacts?.[name], `source-bound ${name}`);
  }
}
const qualification = provenance ? 'final-source-bound' : 'preliminary-pinned-vendor';
if (!provenance) {
  assert(existsSync(join(wasmDir, 'PROVENANCE.json')), 'verified engine provenance required');
  const upstream = JSON.parse(read('PROVENANCE.json').toString('utf8'));
  assert.equal(upstream.version, '0.8.7');
  assert.equal(upstream.commit, '1a76570e833917d15817415a53c09ad61ab3203f');
  for (const name of artifactNames) {
    assert.equal(sha256(read(name)), upstream.artifacts?.[name]?.sha256, `pinned vendor ${name}`);
  }
}

// Independently confirm that the prior document is our known smoke fixture.
const priorInspection = JSON.parse(execFileSync(python,
  [verifier, '--plaintext-hwpx', join(existingDir, 'basic.hwpx'), '--text', priorExpectedText],
  pythonOptions));
assert.equal(priorInspection.text, priorExpectedText);
assert.notEqual(expectedText, priorExpectedText);
if (existsSync(output)) assert.equal(readdirSync(output).length, 0, 'output directory must be empty');
mkdirSync(output, {recursive: true});
writeFileSync(join(output, 'prior.hwpx'), readFileSync(join(existingDir, 'basic.hwpx')));

const {default: init, HwpDocument} = await import(pathToFileURL(join(wasmDir, 'rhwp.js')));
await init({module_or_path: wasm});
function checked(value) {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value;
  assert.notEqual(parsed?.ok, false, JSON.stringify(parsed));
  return parsed;
}
function textOf(document) {
  // The Unicode method returns a JSON string; TEXT additionally maps CP949.
  return JSON.parse(document.getTextFileUnicode()).replace(/\r\n/g, '\n').trimEnd();
}
function expectRejected(open, match) {
  let result;
  let error;
  try { result = open(); }
  catch (value) { error = String(value?.message ?? value); }
  finally { result?.free(); }
  assert(error, 'protected input must reject this open attempt');
  assert.match(error, match);
  return error;
}

const created = HwpDocument.createEmpty();
let protectedBytes;
try {
  checked(created.createBlankDocument());
  checked(created.insertText(0, 0, 0, expectedText));
  assert.equal(textOf(created), expectedText);
  protectedBytes = {
    hwp: Buffer.from(created.exportHwpWithPassword(password)),
    hwpx: Buffer.from(created.exportHwpxWithPassword(password)),
  };
} finally { created.free(); }

const fixtures = [];
const roundtrips = [];
for (const [format, bytes] of Object.entries(protectedBytes)) {
  const path = `protected.${format}`;
  writeFileSync(join(output, path), bytes);
  const normalError = expectRejected(() => new HwpDocument(bytes), /비밀번호|Encrypted/i);
  const wrongError = expectRejected(() => HwpDocument.openWithPassword(bytes, 'OpenGeul-wrong-public-QA'), /비밀번호가 일치하지 않/);
  const opened = HwpDocument.openWithPassword(bytes, password);
  try {
    assert.equal(textOf(opened), expectedText);
    for (const [outputFormat, plaintext] of [
      ['hwp', Buffer.from(opened.exportHwp())],
      ['hwpx', Buffer.from(opened.exportHwpx())],
    ]) {
      const plainPath = `${format}-reopened-plain.${outputFormat}`;
      writeFileSync(join(output, plainPath), plaintext);
      const reopened = new HwpDocument(plaintext);
      try { assert.equal(textOf(reopened), expectedText); }
      finally { reopened.free(); }
      roundtrips.push({inputFormat: format, outputFormat, path: plainPath,
        bytes: plaintext.length, sha256: sha256(plaintext)});
    }
    fixtures.push({format, path, sha256: sha256(bytes), bytes: bytes.length,
      normalOpenRejected: true, wrongPasswordRejected: true, correctPasswordTextVerified: true,
      normalError, wrongError, pageCount: opened.pageCount()});
  } finally { opened.free(); }
}

const manifest = {
  schemaVersion: 1,
  password,
  expectedText,
  priorExpectedText,
  priorPath: 'prior.hwpx',
  prior: {sha256: sha256(readFileSync(join(output, 'prior.hwpx'))),
    bytes: readFileSync(join(output, 'prior.hwpx')).length},
  fixtures,
  roundtrips,
  engine: {wasmSha256: sha256(wasm), jsSha256: sha256(js), provenance, qualification},
  generation: {
    source: 'Public WASM createEmpty/createBlankDocument/insertText/password export APIs',
    textOwnership: 'Task-authored content generated via the library bundled blank template; no user document, external sample, or font program input',
    generatorSha256: sha256(readFileSync(fileURLToPath(import.meta.url))),
    verifierSha256: sha256(readFileSync(verifier)),
    priorInspection,
  },
};
writeFileSync(join(output, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
const independent = JSON.parse(execFileSync(python, [verifier, '--manifest', join(output, 'manifest.json')],
  pythonOptions));
writeFileSync(join(output, 'independent-verification.json'), JSON.stringify(independent, null, 2) + '\n');
for (const fixture of fixtures) fixture.encryption = independent.fixtures[fixture.format];
manifest.independentVerification = {passed: true, path: 'independent-verification.json'};
writeFileSync(join(output, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(JSON.stringify({qualification, fixtures: fixtures.map(({format, bytes, sha256, encryption}) =>
  ({format, bytes, sha256, encryption})), normalWrongCorrect: 'passed', plaintextRoundtrips: roundtrips.length,
  independentVerification: 'passed', output}, null, 2));
