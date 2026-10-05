"""Narrow HOP backports; preserve authorship and fail on unexpected upstream changes."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
ROOT = Path(__file__).resolve().parents[1]

def patch(source: Path):
    host = source/'apps/studio-host'
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
    evidence = {'upstreamPr':'https://github.com/golbin/hop/pull/101','upstreamCommit':'f9bbe8dc66172a1959af1e388e6c28a5b597c5a6','author':'FMsongX2','issues':[95,100],'scope':'OpenGeul downstream backport; no upstream issue is closed', 'beforeSha256':hashlib.sha256(original.encode()).hexdigest(), 'afterSha256':hashlib.sha256(updated.encode()).hexdigest()}
    (source/'.opengeul-hop-fixes.json').write_text(json.dumps(evidence,indent=2)+'\n')
    ledger=source/'.opengeul-overlay.json'
    state=json.loads(ledger.read_text());state['hopBackports']=[evidence];state['toolbarLabelPreference']={'upstreamIssue':97,'defaultVisible':True};ledger.write_text(json.dumps(state,indent=2)+'\n')
    print('Applied HOP #101 backport for Windows #95/macOS #100 and #97 label preference.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    patch(parser.parse_args().source.resolve())
