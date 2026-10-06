"""Bind fixture generator WASM to the exact Windows build being printed."""
import hashlib,json
from pathlib import Path

def verify(package:Path,wasm:Path,commit:str,run_id:str):
    provenance=json.loads((package/'provenance.json').read_text(encoding='utf-8'))
    if provenance.get('commit')!=commit or str(provenance.get('runId'))!=str(run_id):
        raise ValueError('Printer test payload source/run mismatch')
    record=json.loads((wasm/'OPEN_GEUL_WASM.json').read_text(encoding='utf-8'))
    if record!=provenance.get('sourceParity',{}).get('wasmRebuild'):
        raise ValueError('Fixture engine differs from the packaged engine')
    for name in ('rhwp.js','rhwp.d.ts','rhwp_bg.wasm','rhwp_bg.wasm.d.ts','package.json','LICENSE'):
        path=wasm/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=record['artifacts'].get(name):
            raise ValueError(f'Fixture engine integrity mismatch: {name}')
    return provenance
if __name__=='__main__':
    import sys
    verify(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4])
    print('Print payload and fixture generator have identical source-bound WASM')
