"""Verify real runtime payloads and authorize development releases; never sign a package."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from buildkit import ROOT, FONT_EXTENSIONS, SECRET_EXTENSIONS, package_version

REPOSITORY = 'ATLKR/OpenGeul'

def release_allowed(repo: str, event: str, ref: str) -> bool:
    if repo != REPOSITORY or event not in ('push', 'workflow_dispatch'):
        return False
    return ref == 'refs/heads/main' or (event == 'push' and bool(re.fullmatch(r'refs/tags/v[1-9][0-9]*\.[0-9]+\.[0-9]+', ref)))

def release_tag(version: str, ref: str, run: str, attempt: str) -> str:
    package_version(version)
    if ref.startswith('refs/tags/'):
        tag = ref.removeprefix('refs/tags/')
        if tag != 'v' + version:
            raise ValueError('Release tag must match config/product.json version')
        return tag
    if ref != 'refs/heads/main' or not re.fullmatch(r'[1-9][0-9]*', run) or not re.fullmatch(r'[1-9][0-9]*', attempt):
        raise ValueError('Invalid main-branch release identity')
    return f'v{version}-dev.{run}.{attempt}'

def pe_machine(header: bytes) -> int:
    if len(header) < 64 or header[:2] != b'MZ':
        raise ValueError('Runtime file is not a PE executable')
    offset = struct.unpack_from('<I', header, 60)[0]
    if offset + 6 > len(header) or header[offset:offset + 4] != b'PE\0\0':
        raise ValueError('Invalid PE header')
    machine = struct.unpack_from('<H', header, offset + 4)[0]
    if machine != 0x8664:
        raise ValueError('This distribution requires Windows x64 executables')
    return machine

def verify_msix(path: Path) -> dict:
    required = {'OpenGeul.exe', 'Tools/rhwp.exe', 'AppxManifest.xml', 'AppxBlockMap.xml', '[Content_Types].xml', 'Notices/OpenGeul-LICENSE.txt'}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate package members')
        for item in archive.infolist():
            name = item.filename.replace('\\', '/')
            parts = PurePosixPath(name)
            if parts.is_absolute() or '..' in parts.parts or ':' in name:
                raise ValueError('Unsafe package path')
            if item.is_dir():
                continue
            if parts.suffix.lower() in FONT_EXTENSIONS | SECRET_EXTENSIONS:
                raise ValueError('Font or credential file in package')
            with archive.open(item) as entry:
                header = entry.read(4096)
            if header[:4] in (b'wOFF', b'wOF2', b'ttcf', b'OTTO', b'\0\1\0\0'):
                raise ValueError('Disguised font file in package')
            if name.endswith('.exe'):
                pe_machine(header)
        normalized = {name.replace('\\', '/') for name in names}
        if not required <= normalized:
            raise ValueError('Package lacks required real runtime, manifest or license files: ' + str(required - normalized))
        if 'AppxSignature.p7x' in normalized:
            raise ValueError('Expected an unsigned development package')
        def content(name):
            return archive.read(next(x for x in names if x.replace('\\','/') == name))
        doc = ET.fromstring(content('AppxManifest.xml'))
        ns = {'p':'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
        identity = doc.find('p:Identity', ns)
        if identity is None or identity.get('ProcessorArchitecture') != 'x64':
            raise ValueError('Wrong MSIX architecture')
        app = doc.find('p:Applications/p:Application', ns)
        if app is None or app.get('Executable') != 'OpenGeul.exe':
            raise ValueError('MSIX does not launch the real OpenGeul editor')
    return {'unsigned':True, 'architecture':'x64', 'members':len(names), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def finish(output: Path, source: Path) -> None:
    product = json.loads((ROOT/'config/product.json').read_text(encoding='utf-8'))
    packages = sorted(output.glob('*.msix'))
    if len(packages) != 1:
        raise ValueError('Expected exactly one MSIX')
    result = verify_msix(packages[0])
    result.update(repository=REPOSITORY, commit=os.getenv('GITHUB_SHA'), runId=os.getenv('GITHUB_RUN_ID'),
                  version=product['version'], package=packages[0].name,
                  upstream=json.loads((ROOT/'config/upstream.lock.json').read_text(encoding='utf-8')),
                  sourceParity=json.loads((source/'.opengeul-overlay.json').read_text(encoding='utf-8')),
                  manualWindowsUx='not-verified', storeCertified=False)
    (output/'provenance.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(output.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('verify');p.add_argument('package',type=Path)
    p=sub.add_parser('finish');p.add_argument('output',type=Path);p.add_argument('source',type=Path)
    sub.add_parser('authorize')
    a=ap.parse_args()
    if a.cmd=='verify':print(json.dumps(verify_msix(a.package),indent=2))
    elif a.cmd=='finish':finish(a.output,a.source)
    else:
        if not release_allowed(os.getenv('GITHUB_REPOSITORY',''),os.getenv('GITHUB_EVENT_NAME',''),os.getenv('GITHUB_REF','')):
            raise SystemExit('Release is not authorized for this repository/event/ref')
        version=json.loads((ROOT/'config/product.json').read_text(encoding='utf-8'))['version']
        tag=release_tag(version,os.environ['GITHUB_REF'],os.environ['GITHUB_RUN_NUMBER'],os.environ['GITHUB_RUN_ATTEMPT'])
        print(tag)
        if os.getenv('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as f:f.write('tag='+tag+'\n')
if __name__=='__main__':main()
