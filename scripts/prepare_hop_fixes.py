"""Narrow HOP backports; preserve authorship and fail on unexpected upstream changes."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
ROOT = Path(__file__).resolve().parents[1]

ZOOM_LOAD_ANCHOR = """    inputHandler?.deactivate();
    await canvasView?.loadDocument();
    toolbar?.setEnabled(true);"""
ZOOM_LOAD_REPLACEMENT = """    inputHandler?.deactivate();
    // HOP #94; adapted from golbin/hop 2b1189b3079045481134864d9ccb02ca535ea6bb.
    // Mobile auto-fit must not overwrite the desktop user's chosen document zoom.
    const desktopZoom = isTauriRuntime() ? canvasView?.getViewportManager().getZoom() : undefined;
    await canvasView?.loadDocument();
    if (desktopZoom !== undefined) canvasView?.getViewportManager().setZoom(desktopZoom);
    toolbar?.setEnabled(true);"""

def patch_desktop_zoom(text: str) -> str:
    """Keep browser auto-fit, restoring only the desktop zoom after successful load."""
    if text.count(ZOOM_LOAD_ANCHOR) != 1 or 'desktopZoom' in text:
        raise ValueError('Desktop zoom patch does not match the pinned host initialization')
    return text.replace(ZOOM_LOAD_ANCHOR, ZOOM_LOAD_REPLACEMENT)

def patch(source: Path):
    host = source/'apps/studio-host'
    main = host/'src/main.ts'
    original_main = main.read_text(encoding='utf-8')
    updated_main = patch_desktop_zoom(original_main)
    path = host/'src/command/shortcut-map.ts'
    original = path.read_text(encoding='utf-8')
    needle = '...upstreamDefaultShortcuts.filter(([shortcut]) => !hopShortcutKeys.has(shortcutKey(shortcut))),'
    replacement = '''...upstreamDefaultShortcuts.filter(
    ([shortcut]) => !hopShortcutKeys.has(shortcutKey(shortcut)) && !isUnmodifiedCharacterShortcut(shortcut),
  ),'''
    helper = '''// Adapted from golbin/hop#101 (FMsongX2, f9bbe8dc66172a1959af1e388e6c28a5b597c5a6).
// Ordinary character shortcuts are consumed even when the pinned handler cannot execute them.
// Keep object properties available through its existing menu and toolbar button.
function isUnmodifiedCharacterShortcut(shortcut: ShortcutDef): boolean {
  return !shortcut.ctrl && !shortcut.alt && !shortcut.shift && shortcut.key.length === 1;
}

'''
    if original.count(needle) != 1 or original.count('export function matchShortcut(') != 1:
        raise ValueError('HOP keyboard patch does not match the pinned source')
    updated = original.replace(needle, replacement).replace('export function matchShortcut(', helper+'export function matchShortcut(')
    index = host/'index.html'
    markup = index.read_text(encoding='utf-8')
    for old,new in [('<span class="md-shortcut">P</span>', ''), ('title="개체 속성 (P)"','title="개체 속성"')]:
        if markup.count(old) != 1: raise ValueError('Object properties UI anchor changed')
        markup = markup.replace(old,new)
    path.write_text(updated,encoding='utf-8')
    for filename in ('toolbar-preferences.ts', 'toolbar-labels.ts', 'toolbar-labels.css'):
        shutil.copyfile(ROOT/'overlay/hop-fixes'/filename,host/'src'/('opengeul-'+filename))
    anchor = '<script type="module" src="/src/main.ts"></script>'
    if markup.count(anchor) != 1: raise ValueError('HOP application entry changed')
    markup = markup.replace(anchor,anchor+'\n  <script type="module" src="/src/opengeul-toolbar-labels.ts"></script>')
    index.write_text(markup,encoding='utf-8')
    main.write_bytes(updated_main.encode('utf-8'))
    evidence = {'upstreamPr':'https://github.com/golbin/hop/pull/101','upstreamCommit':'f9bbe8dc66172a1959af1e388e6c28a5b597c5a6','author':'FMsongX2','issues':[95,100],'scope':'OpenGeul downstream backport; no upstream issue is closed', 'beforeSha256':hashlib.sha256(original.encode()).hexdigest(), 'afterSha256':hashlib.sha256(updated.encode()).hexdigest()}
    (source/'.opengeul-hop-fixes.json').write_text(json.dumps(evidence,indent=2)+'\n')
    ledger=source/'.opengeul-overlay.json'
    state=json.loads(ledger.read_text());state['hopBackports']=[evidence];state['toolbarLabelPreference']={'upstreamIssue':97,'defaultVisible':True}
    state['desktopZoomPreservation'] = {
        'issue': 94, 'upstreamCommit': '2b1189b3079045481134864d9ccb02ca535ea6bb',
        'scope': 'Desktop document-load zoom only; toolbar layout and native macOS behavior remain separate',
        'beforeSha256': hashlib.sha256(original_main.encode()).hexdigest(),
        'afterSha256': hashlib.sha256(updated_main.encode()).hexdigest(),
    }
    ledger.write_text(json.dumps(state,indent=2)+'\n')
    print('Applied HOP #101 backport for Windows #95/macOS #100 and #97 label preference; preserved desktop document zoom for #94.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    patch(parser.parse_args().source.resolve())
