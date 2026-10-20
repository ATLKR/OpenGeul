"""Inspect the actual native ARM64 CI host and authenticated upstream baseline.

This records build prerequisites and binary metadata; it is not Suite E2E proof.
It does not install the Office MSI or qualify the baseline's missing Firebird.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'suite'))
from prepare import download_locked
from msi_cab import WindowsMsiDatabase

BASELINE_SELECTOR = 'suite/config/runtime.arm64-baseline.lock.json'
BASELINE_BYTES = 1618
BASELINE_SHA256 = 'f58107858b83e29c7b98aea1dc41141a637caeba1f6e9a8e3b84395968c1b0c1'
BASELINE_ASSET = {
    'name':'LibreOffice','version':'26.8.1.1',
    'url':'https://mirror.clarkson.edu/tdf/libreoffice/stable/26.8.1/win/aarch64/LibreOffice_26.8.1_Win_aarch64.msi',
    'size':360910848,'sha256':'97c2173752325af1da3d8731f41c8e09a7c4ad491cf55d9b1069fadb5668e6d7',
}


def validate_baseline(lock):
    if type(lock.get('schemaVersion')) is not int or lock['schemaVersion']!=1 or lock.get('architecture')!='arm64':
        raise ValueError('Official baseline requires schema1 and ARM64 architecture')
    runtime=lock.get('runtime')
    if not isinstance(runtime,dict) or runtime.get('format','msi')!='msi':
        raise ValueError('Official baseline requires MSI format')
    if 'sourceBuild' in runtime:
        raise ValueError('Official baseline must not carry sourceBuild metadata')
    if any(runtime.get(key)!=value for key,value in BASELINE_ASSET.items()):
        raise ValueError('Official ARM64 MSI asset identity differs')


def _unlinked_metadata(path, directory=False):
    value=path.lstat()
    if stat.S_ISLNK(value.st_mode) or getattr(value,'st_file_attributes',0)&0x400:
        raise ValueError('Baseline input path must be unlinked and non-reparse')
    expected=stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(value.st_mode):
        raise ValueError('Baseline input requires regular file and directory ancestors')
    return value


def load_baseline(selector, root=ROOT):
    if not isinstance(selector,str) or selector!=BASELINE_SELECTOR:
        raise ValueError('Only the explicit official ARM64 baseline selector is permitted')
    path=Path(root)/BASELINE_SELECTOR
    before={item:_unlinked_metadata(item,item!=path) for item in (path,*path.parents)}
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
    with os.fdopen(os.open(path,flags),'rb') as stream:
        opened=os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size!=BASELINE_BYTES:
            raise ValueError('Official baseline input size pin mismatch')
        # Compare metadata only within each API: path and handle fields can differ.
        revision=lambda item:(item.st_dev,item.st_ino,item.st_size,item.st_mtime_ns,item.st_ctime_ns)
        raw=stream.read(BASELINE_BYTES+1)
        if revision(os.fstat(stream.fileno()))!=revision(opened):
            raise ValueError('Baseline input identity changed while reading')
    for item,previous in before.items():
        current=_unlinked_metadata(item,item!=path)
        if (current.st_dev,current.st_ino,current.st_mode)!=(previous.st_dev,previous.st_ino,previous.st_mode):
            raise ValueError('Baseline input path identity changed')
        if item==path and revision(current)!=revision(previous):
            raise ValueError('Baseline input identity changed after reading')
    sha=hashlib.sha256(raw).hexdigest()
    if len(raw)!=BASELINE_BYTES or sha!=BASELINE_SHA256:
        raise ValueError('Official baseline input SHA256 pin mismatch')
    lock=json.loads(raw)
    validate_baseline(lock)
    return lock,{'inputRole':'official-arm64-msi-baseline','lockPath':BASELINE_SELECTOR,
        'lockBytes':len(raw),'lockSha256':sha,'architecture':'arm64','format':'msi',
        'asset':{key:lock['runtime'][key] for key in BASELINE_ASSET}}


def write(path, value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False)
        stream.write('\n')


def machine(path):
    with path.open('rb') as stream:
        header=stream.read(64)
        if len(header)<64 or header[:2]!=b'MZ': return None
        stream.seek(struct.unpack_from('<I',header,60)[0])
        pe=stream.read(6)
        if len(pe)!=6 or pe[:4]!=b'PE\0\0': return None
        return struct.unpack_from('<H',pe,4)[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-lock',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    lock,baseline_input=load_baseline(args.baseline_lock,ROOT)
    out=args.output.resolve()
    if out.exists(): raise ValueError('Probe output must be fresh')
    out.mkdir(parents=True)
    write(out/'baseline-input.json',baseline_input)
    if os.name!='nt': raise RuntimeError('Actual Windows ARM64 host required')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.IsWow64Process2.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(ctypes.c_ushort)]
    kernel.IsWow64Process2.restype=ctypes.c_int
    process,native=ctypes.c_ushort(),ctypes.c_ushort()
    if not kernel.IsWow64Process2(kernel.GetCurrentProcess(),ctypes.byref(process),ctypes.byref(native)):
        raise ctypes.WinError(ctypes.get_last_error())
    host={'processMachine':process.value,'nativeMachine':native.value,'pythonMachine':machine(Path(sys.executable)),
          'platform':platform.platform(),'python':sys.version,'disk':dict(zip(('total','used','free'),shutil.disk_usage(out))),
          'sourceCommit':os.environ.get('GITHUB_SHA'),'runId':os.environ.get('GITHUB_RUN_ID'),
          'kind':'native-arm64-prerequisite-probe','suiteE2eVerified':False}
    write(out/'host.json',host)
    if process.value!=0 or native.value!=0xaa64 or host['pythonMachine']!=0xaa64:
        raise RuntimeError('Probe must use native ARM64 Python on native ARM64 Windows')
    msi=download_locked(lock['runtime'],out/'upstream-arm64.msi')
    with WindowsMsiDatabase(msi) as database:
        rows=database.file_rows()
        write(out/'native-crt-msi-rows.json',{'files':[r for r in rows if any(x in str(r.get('FileName','')).lower() for x in ('vcruntime','msvcp140','concrt140'))], 'media':database.media_rows()})
    image=out/'admin-image'
    command=['msiexec.exe','/a',str(msi),'/qn','/norestart','TARGETDIR='+str(image),'/L*v',str(out/'msi.log')]
    result=subprocess.run(command,timeout=300,check=False)
    write(out/'extraction.json',{'returncode':result.returncode,'command':command,'msiSha256':hashlib.sha256(msi.read_bytes()).hexdigest()})
    if result.returncode: raise RuntimeError('Native ARM64 baseline extraction failed')
    binaries=[]; interesting=[]
    for path in sorted(image.rglob('*')):
        if not path.is_file(): continue
        name=path.relative_to(image).as_posix()
        if any(token in name.lower() for token in ('firebird','sdbc','hsqldb','jdbc','jvmfwk','java','juh','jurt')):
            interesting.append({'path':name,'bytes':path.stat().st_size})
        if path.suffix.lower() in ('.exe','.dll','.pyd'):
            code=machine(path)
            item={'path':name,'machine':code,'bytes':path.stat().st_size}
            if code!=0xaa64:
                item['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            binaries.append(item)
    write(out/'baseline-binaries.json',{'input':lock['runtime'],'binaries':binaries,'databaseAndJavaFiles':interesting,'suiteE2eVerified':False})
    print(json.dumps({'nativeMachine':native.value,'binaryCount':len(binaries),'baselineOnly':True}))


if __name__=='__main__':
    main()
