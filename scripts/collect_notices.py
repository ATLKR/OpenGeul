"""Collect dependency license texts; creates a review inventory, not a legal clearance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUST_SKIA_NAMES = {'skia-safe', 'skia-bindings'}
RUST_SKIA_VERSION = '0.156.0'
RUST_SKIA_COMMIT = 'ce6727ef251518df37bcfdde4865b71f7e3a4352'
RUST_SKIA_SHA256 = '4b33ed5b329a3a79eb1243fd91373c68b0ae0b9df7503bfc50d0c5253adf1b9a'
RUST_SKIA_NOTICE = ROOT / 'notices/rust-skia-0.156.0-LICENSE.txt'
RHWP_SOURCE_COMMIT = 'c9095c5f67632e6721e800ccc7fb43ea49d26682'
# These source-package notices are not all at Cargo's package root. Keep their
# exact origins in the review inventory without claiming that every asset ships.
SUPPLEMENTAL_NOTICES = {
    'rhwp-pdf-import-backend': {
        'version':'0.3.78-rhwp.1', 'license':'MIT OR Apache-2.0',
        'directory':'vendor/rhwp-pdf-import-backend',
        'files':{
            'src/fonts/assets/LICENSE-DejaVu':'5fe93f9ee914fc7c4f0cfc73b7b0e972167f1b8f89ba57f9ad55d6013eb8a8ac',
            'src/fonts/assets/LICENSE-NotoEmoji':'8d64bebb6ad6958b0f38a25e2ca948ffc5df8bca30bfb55d92a67244e1c8fec0',
            'src/fonts/assets/LICENSE-fallback-fonts':'7fee68f76f08309b3a599bd93c66e0c5f263e6ccfe98dbe74ecfabbe1eb77429',
            'TRADEMARKS.md':'09fbcb46691825dc4f3a981e841b6f0521543419860ca1aec64cd576ec067277',
        },
    },
    'rhwp-zune-jpeg': {
        'version':'0.5.15-rhwp.1', 'license':'(MIT OR Apache-2.0 OR Zlib) AND IJG',
        'directory':'vendor/rhwp-zune-jpeg',
        'files':{'README.ijg':'75815e3bf6484201a3c3d17a1bbf10f2e8e3237f84df10a2357ea896db2a81d6'},
    },
    'rhwp-hayro-jpeg2000': {
        'version':'0.4.0-rhwp.1', 'license':'Apache-2.0 OR MIT',
        'directory':'vendor/rhwp-hayro-jpeg2000',
        'files':{'assets/LICENSE.txt':'469d87b5fa48f8aaf69e25f4fcac3a309c97dbb7d561b917638abdb640e004d9'},
    },
}

# Exact reviewed omissions only. Additional third-party notices do not satisfy a
# package's missing declared-license text or change its declaration/clearance.
REVIEWED_SOURCE_NOTICES = {
    ('cargo', 'r-efi'): {
        '5.3.0': {
            'license':'MIT OR Apache-2.0 OR LGPL-2.1-or-later',
            'manifestSha256':'dba000c0173b09b1e3b69afa42a715b5ab64355e6502ce6d9d1767c7845cf402',
            'sourcePath':'AUTHORS',
            'sourceSha256':'ff92bed461f50338dd703a9ba9aee496a425957873df1d91192776e4bdf5dda7',
            'noticeSha256':'ff92bed461f50338dd703a9ba9aee496a425957873df1d91192776e4bdf5dda7',
            'packageLicenseText':True,
            'sourceUrl':'https://raw.githubusercontent.com/r-efi/r-efi/97b55bed1c2c91dcbf787674849f05337ff80b33/AUTHORS',
            'packageProvenance':{
                'archiveUrl':'https://crates.io/api/v1/crates/r-efi/5.3.0/download',
                'archiveSha256':'69cdb34c158ceb288df11e18b4bd39de994f6657d83847bdffdbd7f346754b0f'}},
        '6.0.0': {
            'license':'MIT OR Apache-2.0 OR LGPL-2.1-or-later',
            'manifestSha256':'a021f9fb0645cc5de5770cf7f41594c1deff4b388eca933b289752aa52666829',
            'sourcePath':'AUTHORS',
            'sourceSha256':'d027e91dbc9cdbb2f1190068e498bd6b61cff022b6a032b191021ba658d96111',
            'noticeSha256':'d027e91dbc9cdbb2f1190068e498bd6b61cff022b6a032b191021ba658d96111',
            'packageLicenseText':True,
            'sourceUrl':'https://raw.githubusercontent.com/r-efi/r-efi/7e1b0322d31d625f81a5656096330934f9cd835d/AUTHORS',
            'packageProvenance':{
                'archiveUrl':'https://crates.io/api/v1/crates/r-efi/6.0.0/download',
                'archiveSha256':'f8dcc9c7d52a811697d2151c701e0d08956f92b0e24136cf4cf27b57a6a0d9bf'}},
    },
    ('npm', 'rolldown'): {'1.2.16': {
        'license':'MIT',
        'manifestSha256':'525884560d75c4eecb362453e6bbf92b1618d2261ddfbb1a806f164be0813f84',
        'sourcePath':'THIRD-PARTY-LICENSE',
        'sourceSha256':'a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c',
        'noticeSha256':'a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c',
        'packageLicenseText':False,
        'sourceUrl':'https://registry.npmjs.org/rolldown/-/rolldown-1.2.16.tgz',
        'packageProvenance':{
            'archiveUrl':'https://registry.npmjs.org/rolldown/-/rolldown-1.2.16.tgz',
            'archiveIntegrity':'sha512-bWvlMpFKiTfDKfnK7FC2MPgPeWCf/Kpwsq49ApdW+FQaBZb6O6dZ4MAPbPUjp7hYQrw/RobqCzn64BRrQecGHw==',
            'archiveMember':'package/THIRD-PARTY-LICENSE'}}},
    ('npm', 'stackback'): {'0.0.2': {
        'license':'MIT',
        'manifestSha256':'4d984909b27d37d2f1a379b9cda7292a6e3a133c076df166d740a17514ac6e60',
        'sourcePath':'formatstack.js',
        'sourceSha256':'3c1191bd7094a36098418e7d1606e2a49e7ee25b5ddee54b0b2514ea1a43b8a7',
        'lineRange':[1,26],
        'noticeSha256':'b154c4cabeeb587f5cc63a41d0551ae69504460762d189a72ae141558ec5d184',
        'packageLicenseText':False,
        'sourceUrl':'https://registry.npmjs.org/stackback/-/stackback-0.0.2.tgz',
        'packageProvenance':{
            'archiveUrl':'https://registry.npmjs.org/stackback/-/stackback-0.0.2.tgz',
            'archiveIntegrity':'sha512-1XMJE5fQo1jGH6Y/7ebnwPOBEkIEnT4QF32d5R1+VXdXveM0IBMJt8zfaxX1P3QhVwrYe+576+jkANtSS2mBbw==',
            'archiveMember':'package/formatstack.js'}}},
}


def reviewed_file(location: Path, name: str, expected: str) -> bytes:
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise ValueError('Reviewed notice path must remain inside its package')
    path=location/relative
    for component in (path,*path.parents):
        info=component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
            raise ValueError('Reviewed notice input must not use aliases')
        if component==location:break
    if not stat.S_ISREG(path.stat().st_mode) or not path.resolve().is_relative_to(location.resolve()):
        raise ValueError('Reviewed notice input must be a regular package file')
    with path.open('rb') as stream:data=stream.read(2_000_001)
    if len(data)>2_000_000 or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Reviewed notice source/manifest differs from the exact reviewed bytes')
    data.decode('utf-8')
    return data


def collect_reviewed_notices(ecosystem: str, item: dict, location: Path, output: Path) -> list[dict]:
    versions=REVIEWED_SOURCE_NOTICES.get((ecosystem,item['name']))
    if versions is None:return []
    pin=versions.get(item['version'])
    if pin is None or item.get('license')!=pin['license']:
        raise ValueError('Reviewed notice package version/license requires review')
    manifest='Cargo.toml' if ecosystem=='cargo' else 'package.json'
    reviewed_file(location,manifest,pin['manifestSha256'])
    data=reviewed_file(location,pin['sourcePath'],pin['sourceSha256'])
    line_range=pin.get('lineRange')
    if line_range is not None:
        lines=data.splitlines(keepends=True)
        if (len(line_range)!=2 or any(type(n) is not int for n in line_range)
                or line_range[0]!=1 or not 1<=line_range[1]<=len(lines)):
            raise ValueError('Reviewed notice comment range is invalid')
        selected=lines[:line_range[1]]
        if not all(line.startswith(b'//') for line in selected):
            raise ValueError('Reviewed notice range must contain only the leading license comment')
        data=b''.join(selected)
    if hashlib.sha256(data).hexdigest()!=pin['noticeSha256']:
        raise ValueError('Reviewed notice output differs from the complete reviewed notice')
    filename='reviewed/'+Path(pin['sourcePath']).name+'.txt'
    destination=output/filename;destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(data)
    record={'sourcePath':pin['sourcePath'],'sourceSha256':pin['sourceSha256'],
            'sha256':pin['noticeSha256'],'file':filename,'sourceUrl':pin['sourceUrl'],
            'packageProvenance':pin['packageProvenance'],'packageLicenseText':pin['packageLicenseText']}
    if line_range is not None:record['sourceLineRange']=list(line_range)
    return [record]


def collect_supplements(item: dict, location: Path, output: Path) -> list[dict]:
    pin=SUPPLEMENTAL_NOTICES.get(item['name'])
    if pin is None:return []
    if item['version'] != pin['version'] or item.get('license') != pin['license']:
        raise ValueError('Supplemental notice package version/license requires review')
    inputs=[]
    for name,expected in pin['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError('Supplemental notice path must remain in the package')
        path=location/relative
        for component in (path,*path.parents):
            info=component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
                raise ValueError('Supplemental notice source must not use aliases')
            if component==location:break
        if not path.is_file() or not path.resolve().is_relative_to(location.resolve()):
            raise ValueError('Supplemental notice source must remain a regular package file')
        with path.open('rb') as stream:data=stream.read(2_000_001)
        if len(data)>2_000_000 or hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('Supplemental notice text differs from the reviewed source')
        data.decode('utf-8')
        inputs.append((name,expected,data))
    records=[]
    for name,expected,data in inputs:
        filename='supplemental/'+name+'.txt'
        destination=output/filename;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
        records.append({'sourcePath':name,'sha256':expected,'file':filename,
            'sourceUrl':f'https://raw.githubusercontent.com/edwardkim/rhwp/{RHWP_SOURCE_COMMIT}/{pin["directory"]}/{name}'})
    return records


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
        supplements=collect_supplements(item,location,out/ident)
        if supplements:
            record['supplementalNotices']=supplements
            texts.extend(entry['file'] for entry in supplements)
        reviewed=collect_reviewed_notices('cargo',item,location,out/ident)
        if reviewed:
            record['reviewedNotices']=reviewed
            texts.extend(entry['file'] for entry in reviewed if entry['packageLicenseText'])
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
        record={'ecosystem':'npm','name':name,'version':version,'declaredLicense':item.get('license'),'texts':texts}
        additional=collect_reviewed_notices('npm',item,manifest.parent,out/ident)
        if additional:record['additionalNotices']=additional
        inventory.append(record)
    (out/'inventory.json').write_text(json.dumps({'status':'requires-human-review','packages':inventory},ensure_ascii=False,indent=2),encoding='utf-8')
    missing=sum(not x['texts'] for x in inventory)
    print(f'Collected {len(inventory)} dependency records; {missing} need missing-license-text review. This does not clear release licensing.')
    print(f'Collected {sum(len(x.get("additionalNotices",[])) for x in inventory)} additional third-party notices; these do not fill a missing declared package license.')

if __name__=='__main__': main()
