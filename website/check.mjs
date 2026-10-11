import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const { default: worker } = await import(pathToFileURL(resolve(process.argv[2], 'worker.mjs')));
const root = await worker.fetch(new Request('https://opengeul.allenlim.net/'));
assert.equal(root.status, 200);
const home = await root.clone().text();
assert.ok(home.includes('allenlim@allenlim.net'));
const storePage = 'https://apps.microsoft.com/detail/9PJH0T3PHRMF';
const storeApp = 'ms-windows-store://pdp/?ProductId=9PJH0T3PHRMF';
const developmentZip = 'https://github.com/ATLKR/OpenGeul/releases/download/v1.1.2-dev.64.1/OpenGeul_1.1.2_windows-x64_unsigned-portable.zip';
const links = [...home.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].map((match) => ({
  href: match[1].match(/\bhref="([^"]*)"/)?.[1],
  classes: match[1].match(/\bclass="([^"]*)"/)?.[1].split(/\s+/) ?? [],
  label: match[2].replace(/<[^>]*>/g, '').trim()
}));
const storeLinks = links.filter(({ href }) => href?.startsWith('https://apps.microsoft.com/') || href?.startsWith('ms-windows-store:'));
assert.ok(storeLinks.some(({ href, classes, label }) => href === storePage && classes.includes('primary') && label.includes('Microsoft Store')));
assert.ok(storeLinks.every(({ href }) => [storePage, storeApp].includes(href)), 'Store links must identify the exact OpenGeul product');
const zipLinks = links.filter(({ href }) => href === developmentZip);
assert.ok(zipLinks.length > 0);
assert.ok(zipLinks.every(({ classes }) => !classes.includes('primary')), 'The unsigned development ZIP must remain secondary');
assert.ok(home.includes('서명되지 않은 개발판'));
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
console.log('Website Store product links, secondary development ZIP, Worker routes, privacy, image bytes, HEAD, caching and method checks passed.');
