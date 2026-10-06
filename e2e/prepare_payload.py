"""Reverify artifacts and extract the same runtime bytes that are inside the MSIX."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


def prepare(package: Path, output: Path):
    for line in (package/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
        expected,name=line.split(maxsplit=1);name=name.lstrip('*')
        if Path(name).name!=name:raise ValueError('Checksum filename must be a basename')
        if hashlib.sha256((package/name).read_bytes()).hexdigest().lower()!=expected.lower():raise ValueError(f'Hash mismatch: {name}')
    msix=list(package.glob('*.msix'));portable=list(package.glob('*portable.zip'))
    if len(msix)!=1 or len(portable)!=1:raise ValueError('Exactly one MSIX and portable archive required')
    from releasekit import verify_msix
    verify_msix(msix[0])
    if output.exists():raise ValueError('Refusing to overwrite an existing test runtime')
    output.mkdir(parents=True)
    with zipfile.ZipFile(portable[0]) as archive,zipfile.ZipFile(msix[0]) as packaged:
        for entry in archive.infolist():
            name=entry.filename.replace('\\','/')
            if name.startswith('/') or ':' in name or '..' in PurePosixPath(name).parts:raise ValueError('Unsafe archive path')
            if entry.is_dir():continue
            path=output.joinpath(*PurePosixPath(name).parts);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(archive.read(entry))
        for name in ('OpenGeul.exe','Tools/rhwp.exe'):
            data=(output/name).read_bytes()
            if not data.startswith(b'MZ'):raise ValueError(f'Not a PE executable: {name}')
            member=next(item for item in packaged.namelist() if item.replace('\\','/')==name)
            if data!=packaged.read(member):raise ValueError(f'Portable/MSIX payload mismatch: {name}')
    print(json.dumps({'msix':msix[0].name,'portable':portable[0].name,
        'editorSha256':hashlib.sha256((output/'OpenGeul.exe').read_bytes()).hexdigest()}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('package',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();prepare(args.package,args.output)
