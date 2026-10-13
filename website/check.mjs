import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

assert.ok(process.argv[2], 'Usage: node website/check.mjs <built-worker-directory> [--published-links]');
assert.ok(process.argv.length === 3 || (process.argv.length === 4 && process.argv[3] === '--published-links'), 'Only --published-links is supported');
const { default: worker } = await import(pathToFileURL(resolve(process.argv[2], 'worker.mjs')));
const root = await worker.fetch(new Request('https://opengeul.allenlim.net/'));
assert.equal(root.status, 200);
const home = await root.clone().text();
assert.ok(home.includes('allenlim@allenlim.net'));
const storePage = 'https://apps.microsoft.com/detail/9PJH0T3PHRMF';
const storeApp = 'ms-windows-store://pdp/?ProductId=9PJH0T3PHRMF';
const releaseTag = 'v1.1.4';
const releasePage = `https://github.com/ATLKR/OpenGeul/releases/tag/${releaseTag}`;
const portableZips = ['x64', 'arm64'].map(architecture => ({
  architecture,
  name: `OpenGeul_1.1.4_windows-${architecture}_unsigned-portable.zip`,
  url: `https://github.com/ATLKR/OpenGeul/releases/download/${releaseTag}/OpenGeul_1.1.4_windows-${architecture}_unsigned-portable.zip`
}));
const links = [...home.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].map((match) => ({
  href: match[1].match(/\bhref="([^"]*)"/)?.[1],
  classes: match[1].match(/\bclass="([^"]*)"/)?.[1].split(/\s+/) ?? [],
  label: match[2].replace(/<[^>]*>/g, '').trim()
}));
const storeLinks = links.filter(({ href }) => href?.startsWith('https://apps.microsoft.com/') || href?.startsWith('ms-windows-store:'));
assert.ok(storeLinks.some(({ href, classes, label }) => href === storePage && classes.includes('primary') && label.includes('Microsoft Store')));
assert.ok(storeLinks.every(({ href }) => [storePage, storeApp].includes(href)), 'Store links must identify the exact OpenGeul product');
for (const { architecture, url } of portableZips) {
  const zipLinks = links.filter(({ href }) => href === url);
  assert.equal(zipLinks.length, 1, `The native ${architecture} ZIP must have one explicit download link`);
  assert.ok(zipLinks.every(({ classes, label }) => !classes.includes('primary') && label.toLowerCase().includes(architecture)), 'Unsigned ZIP links must remain secondary and identify their architecture');
}
assert.deepEqual(links.filter(({ href }) => href?.endsWith('.zip')).map(({ href }) => href).sort(), portableZips.map(({ url }) => url).sort());
assert.ok(links.some(({ href }) => href === releasePage));
assert.ok(home.includes('서명되지 않은 포터블'));
assert.match(home, /Windows 10 버전 2004 이상 또는 Windows 11의 x64/);
assert.match(home, /Windows 11의 ARM64/);
assert.match(home, /시스템 종류/);
assert.match(home, /1\.1\.4에는 사용량 분석용 텔레메트리가 포함되지 않습니다/);
assert.doesNotMatch(home, /ARM64와 32비트 전용 빌드는 제공하지 않습니다|v1\.1\.4-dev\./);
assert.ok(home.includes('Store에서 제공하는 아키텍처는 제품 페이지에서 확인하세요.'));
assert.doesNotMatch(home, /배포(?:는)? 준비 중|Store 배포를 준비|공개되면/);
assert.equal(root.headers.get('Content-Type'), 'text/html; charset=utf-8');
assert.match(home, /<a[^>]+href="https:\/\/apps\.microsoft\.com\/detail\/9PJH0T3PHRMF"[^>]*><img[^>]+src="\/assets\/store-version\.svg"[^>]+alt="[^"]+"[^>]*><\/a>/);
const metadataResponse = await worker.fetch(new Request('https://opengeul.allenlim.net/api/store-release.json'));
assert.equal(metadataResponse.status, 200);
assert.equal(metadataResponse.headers.get('Content-Type'), 'application/json; charset=utf-8');
const metadataText = await metadataResponse.text();
assert.ok(new TextEncoder().encode(metadataText).length <= 8192);
const metadata = JSON.parse(metadataText);
assert.deepEqual(Object.keys(metadata).sort(), ['formatVersion', 'appId', 'status', 'version', 'storeUrl', 'submissionId'].sort());
assert.equal(metadata.formatVersion, 1);
assert.equal(metadata.appId, '9PJH0T3PHRMF');
assert.equal(metadata.status, 'Published');
assert.equal(metadata.storeUrl, storePage);
assert.match(metadata.version, /^(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}$/);
assert.ok(metadata.version.split('.').every(part => Number(part) <= 65535));
assert.match(metadata.submissionId, /^[1-9][0-9]{0,24}$/);
const badge = await worker.fetch(new Request('https://opengeul.allenlim.net/assets/store-version.svg'));
assert.equal(badge.headers.get('Content-Type'), 'image/svg+xml; charset=utf-8');
assert.equal(badge.headers.get('Cache-Control'), 'public, max-age=60');
const badgeText = await badge.text();
assert.ok(badgeText.includes(metadata.version));
assert.match(badgeText, /role="img"[^>]*aria-label="[^"]+"/);
assert.doesNotMatch(badgeText, /<script|(?:href|src)="https?:|fileUpload|Authorization|access_token/);
for (const path of ['/api/store-release.json', '/assets/store-version.svg']) {
  const response = await worker.fetch(new Request('https://opengeul.allenlim.net' + path));
  assert.equal((await worker.fetch(new Request('https://opengeul.allenlim.net' + path, { method: 'HEAD' }))).status, 200);
  assert.equal((await worker.fetch(new Request('https://opengeul.allenlim.net' + path, { headers: { 'If-None-Match': response.headers.get('ETag') } }))).status, 304);
}
const privacy = await worker.fetch(new Request('https://opengeul.allenlim.net/privacy'));
assert.equal(privacy.status, 200);
assert.ok((await privacy.text()).includes('Cloudflare'));
const picture = await worker.fetch(new Request('https://opengeul.allenlim.net/assets/opengeul-editor.png'));
assert.deepEqual([...new Uint8Array(await picture.arrayBuffer()).slice(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
const head = await worker.fetch(new Request('https://opengeul.allenlim.net/', { method: 'HEAD' }));
assert.equal(await head.text(), '');
assert.equal((await worker.fetch(new Request('https://opengeul.allenlim.net/', { headers: { 'If-None-Match': root.headers.get('ETag') } }))).status, 304);
assert.equal((await worker.fetch(new Request('https://opengeul.allenlim.net/missing'))).status, 404);
assert.equal((await worker.fetch(new Request('https://opengeul.allenlim.net/constructor'))).status, 404);
assert.equal((await worker.fetch(new Request('https://opengeul.allenlim.net/', { method: 'POST' }))).status, 405);
console.log('한글 사용 안내, x64·ARM64 포터블 링크, Store 공개 버전 배지, Worker 경로·캐시 검사 통과. 외부 파일의 공개·릴리스 검증은 별도입니다.');

// Publication also requires a fully qualified source run and immutable Source22
// byte verification. HTTP availability alone does not establish that qualification.
if (process.argv[3] === '--published-links') {
  const api = `https://api.github.com/repos/ATLKR/OpenGeul/releases/tags/${releaseTag}`;
  const response = await fetch(api, { headers: { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' }, signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200, `${releaseTag} must be a real public GitHub release (HTTP ${response.status})`);
  let raw = '';
  let bytes = 0;
  const decoder = new TextDecoder();
  for await (const chunk of response.body) {
    bytes += chunk.length;
    assert.ok(bytes <= 256 * 1024, 'Release metadata exceeds the bounded HTTP check');
    raw += decoder.decode(chunk, { stream: true });
  }
  raw += decoder.decode();
  const release = JSON.parse(raw);
  assert.equal(release.tag_name, releaseTag);
  assert.equal(release.html_url, releasePage);
  assert.equal(release.draft, false);
  assert.equal(release.prerelease, false);
  const expectedAssets = ['provenance.json', 'SHA256SUMS.txt'];
  for (const { architecture, name } of portableZips) {
    expectedAssets.push(name, `OpenGeul_1.1.4.0_${architecture}_development-unsigned.msix`,
      `AppxManifest-${architecture}.xml`, `provenance-${architecture}.json`, `SHA256SUMS-${architecture}.txt`,
      `rhwp-help-${architecture}.txt`, `install-${architecture}.json`, `wack-${architecture}.xml`,
      `wack-${architecture}.json`, `wack-context-${architecture}.json`);
  }
  assert.ok(Array.isArray(release.assets));
  assert.deepEqual(release.assets.map(({ name }) => name).sort(), expectedAssets.sort(), 'The published release must contain the exact canonical Source22 asset names');
  assert.ok(release.assets.every(({ size, state }) => Number.isSafeInteger(size) && size > 0 && size <= 96 * 1024 * 1024 && state === 'uploaded'));
  assert.ok(release.assets.reduce((total, { size }) => total + size, 0) <= 192 * 1024 * 1024);
  const checks = await Promise.allSettled(portableZips.map(async ({ name, url }) => {
    const asset = release.assets.find(asset => asset.name === name);
    assert.equal(asset.browser_download_url, url);
    const head = await fetch(url, { method: 'HEAD', signal: AbortSignal.timeout(15000) });
    assert.equal(head.status, 200, `${name} must be downloadable (HTTP ${head.status})`);
    assert.match(head.headers.get('Content-Type') ?? '', /^(?:application\/(?:octet-stream|zip|x-zip-compressed))(?:;|$)/i, `${name} must be an actual ZIP download, not an HTML page`);
    const length = head.headers.get('Content-Length');
    if (length !== null) assert.equal(length, String(asset.size), `${name} HTTP size must match the public asset`);
  }));
  for (const check of checks) if (check.status === 'rejected') throw check.reason;
  const page = await fetch(releasePage, { method: 'HEAD', signal: AbortSignal.timeout(15000) });
  assert.equal(page.status, 200, 'The linked release page must be public');
  console.log('실제 GitHub 공개 URL과 Source22 파일 목록 확인 통과. 전체 Source 실행·원본 바이트·WACK 검증은 게시 전에 별도로 확인해야 합니다.');
}
