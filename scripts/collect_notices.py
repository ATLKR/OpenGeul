"""Collect dependency license texts; creates a review inventory, not a legal clearance."""
import argparse
import json
from pathlib import Path
import re
import subprocess


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


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--source',type=Path,required=True); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); source=args.source.resolve(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    inventory=[]
    packages={}
    for directory, flags in [('apps/desktop/src-tauri',[]),('third_party/rhwp',['--features','native-skia'])]:
        result=subprocess.run(['cargo','metadata','--format-version','1','--locked',*flags],cwd=source/directory,check=True,capture_output=True,text=True,encoding='utf-8')
        for item in json.loads(result.stdout)['packages']:packages[item['id']]=item
    for item in packages.values():
        ident='cargo-'+item['name']+'-'+item['version']
        ident=re.sub(r'[^A-Za-z0-9._-]','_',ident)
        location=Path(item['manifest_path']).parent
        texts=collect(location,out/ident)
        license_file=item.get('license_file')
        if license_file:
            path=(location/license_file).resolve()
            if path.is_relative_to(location.resolve()) and path.is_file():
                try: (out/ident/'declared-license.txt').write_text(path.read_text(encoding='utf-8'),encoding='utf-8'); texts.append('declared-license.txt')
                except UnicodeError: pass
        inventory.append({'ecosystem':'cargo','name':item['name'],'version':item['version'],'declaredLicense':item.get('license'),'texts':texts})
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
