"""Bind the rebuilt WASM files to this checkout's pinned source and namespace fix."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
ROOT=Path(__file__).resolve().parents[1]
FILES=('rhwp.js','rhwp.d.ts','rhwp_bg.wasm','rhwp_bg.wasm.d.ts','package.json','LICENSE')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def expected():
    return {'upstream':json.loads((ROOT/'config/upstream.lock.json').read_text()),
            'namespaceHelper':sha(ROOT/'overlay/hwpx_namespaces.rs'),
            'namespacePatcher':sha(ROOT/'scripts/patch_namespaces.py')}
def validate(folder):
    for name in FILES:
        path=folder/name
        if path.is_symlink() or not path.is_file():raise ValueError(f'Invalid WASM input: {name}')
    if (folder/'rhwp_bg.wasm').read_bytes()[:8]!=b'\0asm\1\0\0\0':raise ValueError('Invalid WASM binary')
    package=json.loads((folder/'package.json').read_text(encoding='utf-8'))
    if package.get('version')!=expected()['upstream']['rhwp']['version']:raise ValueError('WASM version mismatch')
def capture(folder):
    validate(folder)
    value=expected();value['artifacts']={name:sha(folder/name) for name in FILES}
    value['generator']='wasm-pack 0.14.0 --target web --release --no-opt'
    (folder/'OPEN_GEUL_WASM.json').write_text(json.dumps(value,indent=2)+'\n')
def install(folder,source):
    validate(folder)
    value=json.loads((folder/'OPEN_GEUL_WASM.json').read_text())
    for key,expected_value in expected().items():
        if value.get(key)!=expected_value:raise ValueError(f'WASM source mismatch: {key}')
    target=source/'apps/studio-host/vendor/rhwp-core'
    original=json.loads((target/'PROVENANCE.json').read_text())
    for name in FILES:
        if sha(folder/name)!=value['artifacts'].get(name):raise ValueError(f'WASM artifact mismatch: {name}')
    for name in FILES:shutil.copyfile(folder/name,target/name)
    (target/'PROVENANCE.json').write_text(json.dumps({'originalUpstream':original,'opengeulRebuild':value},indent=2)+'\n')
    ledger=source/'.opengeul-overlay.json'
    if ledger.exists():
        state=json.loads(ledger.read_text());state['wasmRebuild']=value
        state['namespacePatch']=json.loads((source/'third_party/rhwp/.opengeul-namespaces.json').read_text())
        ledger.write_text(json.dumps(state,indent=2)+'\n')
    print('Verified and installed source-bound rebuilt WASM; upstream provenance retained separately.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['capture','install']);p.add_argument('folder',type=Path);p.add_argument('source',type=Path,nargs='?')
    a=p.parse_args()
    if a.mode=='capture':capture(a.folder.resolve())
    elif a.source is None:p.error('install requires source')
    else:install(a.folder.resolve(),a.source.resolve())
