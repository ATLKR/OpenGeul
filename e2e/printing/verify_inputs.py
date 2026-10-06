"""Verify printer test inputs against the requested immutable build and source patches."""
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from wasm_artifacts import FILES, expected, sha, validate

def verify(package: Path, wasm: Path, commit: str, run_id: str):
    if not re.fullmatch(r'[a-f0-9]{40}', commit) or not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Immutable build SHA and run ID required')
    value = json.loads((package/'provenance.json').read_text(encoding='utf-8-sig'))
    for key, wanted in {'repository':'ATLKR/OpenGeul','commit':commit,'runId':run_id}.items():
        if str(value.get(key)) != wanted: raise ValueError(f'Printer payload provenance mismatch: {key}')
    validate(wasm)
    provenance = json.loads((wasm/'OPEN_GEUL_WASM.json').read_text())
    for key, wanted in expected().items():
        if provenance.get(key) != wanted: raise ValueError(f'Printer WASM source mismatch: {key}')
    for name in FILES:
        if provenance['artifacts'].get(name) != sha(wasm/name): raise ValueError(f'Printer WASM hash mismatch: {name}')
    print(json.dumps({'verifiedPrinterBuild':commit,'runId':run_id}))

if __name__=='__main__': verify(Path('package'), Path('wasm-input'), os.environ['PRINT_BUILD_SHA'], os.environ['PRINT_BUILD_RUN'])
