import assets from './assets.mjs';

export default {
  async fetch(request) {
    if (!['GET', 'HEAD'].includes(request.method)) {
      return new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD' } });
    }
    let path = new URL(request.url).pathname;
    if (path === '/') path = '/index.html';
    if (path === '/privacy' || path === '/privacy/') path = '/privacy.html';
    const asset = Object.hasOwn(assets, path) ? assets[path] : null;
    if (!asset) return new Response('Not found', { status: 404 });
    const headers = {
      'Content-Type': asset.type,
      'Cache-Control': path.startsWith('/assets/') && path !== '/assets/store-version.svg' ? 'public, max-age=3600' : 'public, max-age=60',
      'Content-Security-Policy': "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      ETag: '"' + asset.sha256 + '"'
    };
    if (request.headers.get('If-None-Match') === headers.ETag) {
      return new Response(null, { status: 304, headers });
    }
    const body = request.method === 'HEAD' ? null : Uint8Array.from(atob(asset.base64), c => c.charCodeAt(0));
    return new Response(body, { headers });
  }
};
