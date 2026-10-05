"""OpenGeul distribution helpers. Python 3.11+, no third-party runtime dependencies."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
import zlib

ROOT = Path(__file__).resolve().parents[1]
FONT_EXTENSIONS = {'.ttf', '.otf', '.ttc', '.otc', '.woff', '.woff2', '.eot', '.pfb', '.pfm'}
SECRET_EXTENSIONS = {'.pfx', '.p12', '.pem', '.key', '.cer', '.crt'}
DEV_IDENTITY = {'name':'AllenLabs.OpenGeul.Development', 'publisher':'CN=OpenGeul Development', 'displayName':'OpenGeul Development'}


def package_version(version: str) -> str:
    if not re.fullmatch(r'(?:[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', version):
        raise ValueError('Version must be MAJOR.MINOR.PATCH, MAJOR >= 1, without suffixes')
    if any(int(x) > 65535 for x in version.split('.')):
        raise ValueError('MSIX components must be <= 65535')
    return version + '.0'


def replace_once(text: str, old: str, new: str, *, expected: int = 1) -> str:
    count = text.count(old)
    if count != expected:
        raise ValueError(f'Upstream anchor count changed: expected {expected}, got {count}: {old[:90]!r}')
    return text.replace(old, new)


def tauri_config(source: dict, version: str) -> dict:
    package_version(version)
    data = copy.deepcopy(source)
    data.update(productName='OpenGeul', identifier='org.allenlabs.opengeul', version=version)
    for window in data.setdefault('app', {}).get('windows', []): window['title'] = 'OpenGeul'
    data.setdefault('plugins', {}).pop('updater', None)
    bundle = data.setdefault('bundle', {})
    bundle.update(publisher='OpenGeul contributors', resources={},
                  shortDescription='Independent HWP/HWPX document editor',
                  longDescription='OpenGeul is an independent downstream distribution based on HOP and rhwp.',
                  copyright='OpenGeul contributors. Upstream copyright notices retained in Notices.',
                  icon=['../../../assets/opengeul/app.png', '../../../assets/opengeul/app.ico'])
    bundle.pop('macOS', None)
    bundle.pop('windows', None)
    bundle['fileAssociations'] = [
        {'ext':['hwp'], 'name':'HWP Document', 'role':'Editor'},
        {'ext':['hwpx'], 'name':'HWPX Document', 'role':'Editor'},
    ]
    data.setdefault('build', {})['beforeBuildCommand'] = 'cd ../.. && pnpm run build:studio && python ../../scripts/buildkit.py frontend apps/studio-host/dist'
    return data


def validate_identity(identity: dict, *, store: bool = False) -> dict:
    required=('name','publisher','displayName')
    if any(not isinstance(identity.get(k),str) or not identity[k] for k in required):
        raise ValueError('Supply exact name, publisher and displayName from Partner Center')
    if any(any(ord(c) < 32 for c in identity[k]) for k in required):
        raise ValueError('Identity fields must not contain control characters')
    if not re.fullmatch(r'[A-Za-z0-9.-]{3,50}',identity['name']):
        raise ValueError('Invalid Package/Identity/Name')
    if not identity['publisher'].startswith('CN='):
        raise ValueError('Publisher must be the exact Partner Center distinguished name, starting CN=')
    if store and any(re.search(r'REPLACE|PLACEHOLDER|DEVELOPMENT|YOUR_',identity[k],re.I) for k in required):
        raise ValueError('Development/example identity is not a Store identity')
    return {k:identity[k] for k in required}


def manifest(identity: dict, version: str) -> str:
    identity=validate_identity(identity)
    ns='http://schemas.microsoft.com/appx/manifest/foundation/windows10'
    uap='http://schemas.microsoft.com/appx/manifest/uap/windows10'
    rescap='http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities'
    ET.register_namespace('',ns); ET.register_namespace('uap',uap); ET.register_namespace('rescap',rescap)
    p=lambda n:f'{{{ns}}}{n}'
    u=lambda n:f'{{{uap}}}{n}'
    root=ET.Element(p('Package'),IgnorableNamespaces='uap rescap')
    ET.SubElement(root,p('Identity'),Name=identity['name'],Publisher=identity['publisher'],Version=package_version(version),ProcessorArchitecture='x64')
    props=ET.SubElement(root,p('Properties'))
    for key,value in [('DisplayName','OpenGeul'),('PublisherDisplayName',identity['displayName']),('Logo','Assets/StoreLogo.png')]: ET.SubElement(props,p(key)).text=value
    deps=ET.SubElement(root,p('Dependencies'))
    ET.SubElement(deps,p('TargetDeviceFamily'),Name='Windows.Desktop',MinVersion='10.0.19041.0',MaxVersionTested='10.0.26100.0')
    resources=ET.SubElement(root,p('Resources'))
    for lang in ('ko-kr','en-us'): ET.SubElement(resources,p('Resource'),Language=lang)
    apps=ET.SubElement(root,p('Applications'))
    app=ET.SubElement(apps,p('Application'),Id='OpenGeul',Executable='OpenGeul.exe',EntryPoint='Windows.FullTrustApplication')
    ET.SubElement(app,u('VisualElements'),DisplayName='OpenGeul',Description='HWP/HWPX document editor',BackgroundColor='transparent',Square150x150Logo='Assets/Square150x150Logo.png',Square44x44Logo='Assets/Square44x44Logo.png')
    exts=ET.SubElement(app,p('Extensions'))
    ext=ET.SubElement(exts,u('Extension'),Category='windows.fileTypeAssociation')
    assoc=ET.SubElement(ext,u('FileTypeAssociation'),Name='opengeul.documents')
    types=ET.SubElement(assoc,u('SupportedFileTypes'))
    for value in ('.hwp','.hwpx'): ET.SubElement(types,u('FileType')).text=value
    caps=ET.SubElement(root,p('Capabilities'))
    ET.SubElement(caps,f'{{{rescap}}}Capability',Name='runFullTrust')
    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n'+ET.tostring(root,encoding='unicode')+'\n'


def audit_payload(root: Path) -> None:
    if not root.is_dir(): raise ValueError(f'Payload directory not found: {root}')
    for path in root.rglob('*'):
        rel=path.relative_to(root)
        if path.is_symlink(): raise ValueError(f'Symlink is not permitted: {rel}')
        if path.is_dir(): continue
        ext=path.suffix.lower()
        if ext in FONT_EXTENSIONS | SECRET_EXTENSIONS: raise ValueError(f'Forbidden payload: {rel}')
        if len(rel.parts)==1 and (rel.name in ('OpenGeul.exe','AppxManifest.xml') or ext=='.dll'): continue
        if rel.as_posix()=='Tools/rhwp.exe': continue
        if len(rel.parts)==2 and rel.parts[0]=='Assets' and ext=='.png': continue
        if rel.parts[0]=='Notices' and ext in ('.txt','.md','.json'): continue
        raise ValueError(f'Unreviewed payload file: {rel}')


def audit_frontend(root: Path) -> None:
    if not (root / 'index.html').is_file(): raise ValueError('Frontend build did not produce index.html')
    for path in root.rglob('*'):
        if path.is_symlink(): raise ValueError(f'Frontend symlink: {path.name}')
        if not path.is_file(): continue
        if path.suffix.lower() in FONT_EXTENSIONS | SECRET_EXTENSIONS:
            raise ValueError(f'Forbidden frontend payload: {path.name}')
        with path.open('rb') as handle: magic=handle.read(4)
        if magic in (b'wOFF', b'wOF2', b'ttcf', b'OTTO', b'\x00\x01\x00\x00'):
            raise ValueError(f'Font-like binary in frontend build: {path.name}')


def permits_subset_embedding(fs_type: int | None) -> bool:
    # Deliberately conservative, not a general-purpose license determination.
    return fs_type in (0,8)


def _png(size: int) -> bytes:
    # Build-time geometric development icon; no font files or rasterized typeface.
    rows=[]
    for y in range(size):
        row=bytearray([0])
        for x in range(size):
            page=size//5 < x < size*4//5 and size//8 < y < size*7//8
            line=page and size*3//10 < x < size*7//10 and any(abs(y-size*n//10)<max(1,size//70) for n in (4,5,6))
            row.extend((20,50,70,255) if line else (245,247,250,255) if page else (25,100,120,255))
        rows.append(row)
    def chunk(tag:bytes,data:bytes)->bytes:
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')


def make_assets(out: Path) -> None:
    out.mkdir(parents=True,exist_ok=True)
    for name,size in [('StoreLogo',50),('Square44x44Logo',44),('Square150x150Logo',150),('app',256)]: (out/f'{name}.png').write_bytes(_png(size))
    raw=_png(256)
    (out/'app.ico').write_bytes(struct.pack('<HHH',0,1,1)+struct.pack('<BBBBHHII',0,0,0,0,1,32,len(raw),22)+raw)


def main() -> None:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='command',required=True)
    m=sub.add_parser('manifest'); m.add_argument('--out',type=Path,required=True); m.add_argument('--identity',type=Path); m.add_argument('--store',action='store_true')
    a=sub.add_parser('audit'); a.add_argument('directory',type=Path)
    a=sub.add_parser('assets'); a.add_argument('directory',type=Path)
    a=sub.add_parser('frontend'); a.add_argument('directory',type=Path)
    ns=ap.parse_args()
    if ns.command=='audit': audit_payload(ns.directory); print('Payload file audit passed (not a binary-embedding or legal audit).')
    elif ns.command=='assets': make_assets(ns.directory)
    elif ns.command=='frontend': audit_frontend(ns.directory); print('Frontend font-file audit passed.')
    else:
        identity=json.loads(ns.identity.read_text(encoding='utf-8-sig')) if ns.identity else DEV_IDENTITY
        identity=validate_identity(identity,store=ns.store)
        version=json.loads((ROOT/'config/product.json').read_text(encoding='utf-8'))['version']
        ns.out.write_text(manifest(identity,version),encoding='utf-8')

if __name__=='__main__': main()
