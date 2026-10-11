"""Collect dependency license texts; creates a review inventory, not a legal clearance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUST_SKIA_NAMES = {'skia-safe', 'skia-bindings'}
RUST_SKIA_VERSION = '0.99.0'
RUST_SKIA_COMMIT = 'a25a0fdb7d90429aa2d1355eab3b910ced359f50'
RUST_SKIA_SHA256 = '4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a'
RUST_SKIA_NOTICE = ROOT / 'notices/rust-skia-0.99.0-LICENSE.txt'


def collect(directory: Path, output: Path) -> list[str]:
    output.mkdir(parents=True,exist_ok=True)
    copied=[]
    for path in directory.iterdir():
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve()) and re.match(r'^(licen[cs]e|copying|notice|copyright)([._-]|$)',path.name,re.I):
            try: text=path.read_text(encoding='utf-8')
            except (UnicodeError,OSError): continue
            if len(text)>2_000_000: continue
            dest=output/(path.name+'.txt')
            dest.write_text(text,encoding='utf-8'); copied.append(dest.name)
    return copied


def collect_cargo(packages: list[dict], out: Path) -> list[dict]:
    inventory=[]
    runtime_names=set()
    for item in packages:
        ident=re.sub(r'[^A-Za-z0-9._-]','_','cargo-'+item['name']+'-'+item['version'])
        location=Path(item['manifest_path']).parent
        texts=collect(location,out/ident)
        license_file=item.get('license_file')
        if license_file:
            path=(location/license_file).resolve()
            if path.is_relative_to(location.resolve()) and path.is_file():
                try: (out/ident/'declared-license.txt').write_text(path.read_text(encoding='utf-8'),encoding='utf-8'); texts.append('declared-license.txt')
                except UnicodeError: pass
        record={'ecosystem':'cargo','name':item['name'],'version':item['version'],'declaredLicense':item.get('license'),'texts':texts}
        if item['name'] in RUST_SKIA_NAMES:
            if item['version'] != RUST_SKIA_VERSION or item.get('license') != 'MIT':
                raise ValueError('Shipped rust-skia version/license changed; review its exact notice before packaging')
            data=RUST_SKIA_NOTICE.read_bytes()
            if hashlib.sha256(data).hexdigest() != RUST_SKIA_SHA256:
                raise ValueError('Shipped rust-skia license text is missing or differs from the reviewed upstream version')
            name='rust-skia-LICENSE.txt'
            (out/ident/name).write_bytes(data)
            texts.append(name)
            record['runtimeNotice']={'sourceCommit':RUST_SKIA_COMMIT,
                'sourceUrl':f'https://raw.githubusercontent.com/rust-skia/rust-skia/{RUST_SKIA_COMMIT}/LICENSE',
                'sha256':RUST_SKIA_SHA256,'file':name,'shippedBy':'Tools/rhwp.exe native-skia'}
            runtime_names.add(item['name'])
        inventory.append(record)
    if runtime_names != RUST_SKIA_NAMES:
        raise ValueError('Metadata is missing a required shipped rust-skia dependency')
    return inventory


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--source',type=Path,required=True); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); source=args.source.resolve(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    inventory=[]
    packages={}
    for directory, flags in [('apps/desktop/src-tauri',[]),('third_party/rhwp',['--features','native-skia'])]:
        result=subprocess.run(['cargo','metadata','--format-version','1','--locked',*flags],cwd=source/directory,check=True,capture_output=True,text=True,encoding='utf-8')
        for item in json.loads(result.stdout)['packages']:packages[item['id']]=item
    inventory=collect_cargo(list(packages.values()),out)
    # Over-inclusive build dependency inventory, not a claim that every item ships.
    store=source/'node_modules/.pnpm'
    for manifest in store.glob('*/node_modules/**/package.json'):
        if len(manifest.relative_to(store).parts)>6: continue
        try: item=json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError,ValueError): continue
        name=item.get('name'); version=item.get('version')
        if not isinstance(name,str) or not isinstance(version,str): continue
        ident=re.sub(r'[^A-Za-z0-9._-]','_','npm-'+name+'-'+version)
        texts=collect(manifest.parent,out/ident)
        inventory.append({'ecosystem':'npm','name':name,'version':version,'declaredLicense':item.get('license'),'texts':texts})
    (out/'inventory.json').write_text(json.dumps({'status':'requires-human-review','packages':inventory},ensure_ascii=False,indent=2),encoding='utf-8')
    missing=sum(not x['texts'] for x in inventory)
    print(f'Collected {len(inventory)} dependency records; {missing} need missing-license-text review. This does not clear release licensing.')

if __name__=='__main__': main()
