import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const native = vi.hoisted(() => ({ detect: vi.fn(), ensure: vi.fn() }));
vi.mock('./local-fonts', () => ({
  detectLocalFontEntries: native.detect,
  ensureLocalFontsAvailable: native.ensure,
}));
vi.unmock('./font-catalog');

let faces: string[];
let styles: Array<{ textContent: string }>;
beforeEach(() => {
  vi.resetModules();
  native.detect.mockReset().mockResolvedValue([]);
  native.ensure.mockReset().mockResolvedValue(new Set<string>());
  faces=[];styles=[];
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Font network access is forbidden'); }));
  vi.stubGlobal('document', {
    fonts: { check: () => false, add: vi.fn() },
    head: { appendChild: (node: { textContent: string }) => styles.push(node) },
    createElement: () => ({ textContent: '' }),
  });
  vi.stubGlobal('FontFace', class {
    constructor(name: string) { faces.push(name); }
    async load() { return this; }
  });
});
afterEach(() => vi.unstubAllGlobals());

describe('OpenGeul installed-font product policy', () => {
  it('does not advertise bundled or substitute fonts as installed', async () => {
    const { FONT_LIST, REGISTERED_FONTS } = await import('./font-catalog');
    expect(FONT_LIST).toEqual([]);
    expect(REGISTERED_FONTS.size).toBe(0);
  });
  it('opens a document with missing fonts without downloads or fabricated faces', async () => {
    const { loadWebFonts } = await import('./font-loader');
    await expect(loadWebFonts(['Missing Document Font'])).resolves.toBeUndefined();
    expect(faces).toEqual([]);
    expect(styles.every(style => style.textContent === '')).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('detects native system fonts without loading bundled substitutes', async () => {
    native.detect.mockResolvedValue([{ family: 'Noto Sans KR', sourceKind: 'system-installed' }]);
    const { loadWebFonts, getDetectedOSFonts } = await import('./font-loader');
    await loadWebFonts(['Noto Sans KR']);
    expect(getDetectedOSFonts().has('Noto Sans KR')).toBe(true);
    expect(faces).toEqual([]);
  });
  it('retains per-user fonts supplied by the native loader', async () => {
    native.detect.mockResolvedValue([{ family: 'My Installed Font', sourceKind: 'file-backed' }]);
    native.ensure.mockResolvedValue(new Set(['My Installed Font']));
    const { loadWebFonts, getDetectedOSFonts } = await import('./font-loader');
    await loadWebFonts(['My Installed Font']);
    expect(getDetectedOSFonts().has('My Installed Font')).toBe(true);
    expect(native.ensure).toHaveBeenCalledWith(expect.arrayContaining(['My Installed Font']));
    expect(faces).toEqual([]);
  });
  it('preserves upstream restricted-authoring checks without claiming a bundled replacement', async () => {
    native.detect.mockResolvedValue([{ family: 'HY헤드라인M', sourceKind: 'system-installed' }]);
    native.ensure.mockResolvedValue(new Set(['HY헤드라인M']));
    const { loadWebFonts, getDetectedOSFonts } = await import('./font-loader');
    await loadWebFonts(['HY헤드라인M']);
    expect(getDetectedOSFonts().has('HY헤드라인M')).toBe(false);
    expect(faces).toEqual([]);
  });
  it('degrades safely when native font discovery fails', async () => {
    native.detect.mockRejectedValue(new Error('catalog unavailable'));
    native.ensure.mockRejectedValue(new Error('font unavailable'));
    const { loadWebFonts, getDetectedOSFonts } = await import('./font-loader');
    await expect(loadWebFonts()).resolves.toBeUndefined();
    expect(getDetectedOSFonts().size).toBe(0);
    expect(fetch).not.toHaveBeenCalled();
    expect(faces).toEqual([]);
  });
});
