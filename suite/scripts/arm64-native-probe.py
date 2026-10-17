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
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'suite'))
from prepare import download_locked
from msi_cab import WindowsMsiDatabase


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
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists(): raise ValueError('Probe output must be fresh')
    out.mkdir(parents=True)
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
    lock=json.loads((ROOT/'suite/config/runtime.arm64.lock.json').read_text())
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
