"""Preserve final composition input before upstream clears the textarea on compositionend."""
from pathlib import Path
import argparse, hashlib, json, shutil
ROOT = Path(__file__).resolve().parents[1]
def patch(source: Path):
    directory = source/'third_party/rhwp/rhwp-studio/src/engine'
    target = directory/'input-handler-text.ts'
    original = target.read_text(encoding='utf-8')
    old = 'export function onCompositionEnd(this: any): void {\n  const anchor = this.compositionAnchor;'
    new = 'export function onCompositionEnd(this: any): void {\n  settleFinalComposition(this, () => onInput.call(this));\n  const anchor = this.compositionAnchor;'
    if original.count(old) != 1: raise ValueError('Composition patch does not match pinned source')
    updated = "import { settleFinalComposition } from './opengeul-composition-final';\n" + original.replace(old,new)
    target.write_text(updated,encoding='utf-8')
    shutil.copyfile(ROOT/'overlay/composition-final.ts',directory/'opengeul-composition-final.ts')
    ledger = source/'.opengeul-overlay.json'
    value=json.loads(ledger.read_text())
    value['compositionFix']={'beforeSha256':hashlib.sha256(original.encode()).hexdigest(),'afterSha256':hashlib.sha256(updated.encode()).hexdigest(),'helperSha256':hashlib.sha256((directory/'opengeul-composition-final.ts').read_bytes()).hexdigest(),'evidence':'Firefox trusted compositionend precedes final input: run 37334337631'}
    ledger.write_text(json.dumps(value,indent=2)+'\n')
    print('Applied final composition reconciliation; no browser-specific bypass.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);patch(p.parse_args().source.resolve())
