"""Installed native tools and exact observer input; never installs or downloads."""
from __future__ import annotations
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
from supervisor import GateFailure,win_path

MANIFEST_SHA='746176ff820c8ca659fb09584f3d3dd6bf1fa33fe491ed73485e3e22e48390e5'
BUNDLE_SHA='0f38f3c60c36f73ab71c4af6a9b0eb77433c8f289659994c8b86070c25e866c6'
SOURCE_INPUTS_SHA='369bfbf3caaf51867e9dc5b330ad0f8206fa1c04e4f7378575c6922d055bbb04'
MACHINES={'x64':0x8664,'arm64':0xaa64}

def cmd_path(value):return win_path(value)

def canonical(path,*,directory=False):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise GateFailure(2)
    for q in (p,*p.parents):
        s=q.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise GateFailure(2)
    s=p.stat()
    if directory:
        if not stat.S_ISDIR(s.st_mode):raise GateFailure(2)
    elif not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise GateFailure(2)
    return p

def _identity(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink

def read(path,limit=128*1024*1024):
    p=canonical(path);before=p.stat()
    if not 0<before.st_size<=limit:raise GateFailure(2)
    fd=os.open(p,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
    try:
        first=os.fstat(fd)
        with os.fdopen(fd,'rb',closefd=False) as stream:b=stream.read(limit+1)
        after=os.fstat(fd)
    finally:os.close(fd)
    if len(b)>limit or _identity(before)!=_identity(first) or _identity(first)!=_identity(after) or _identity(after)!=_identity(canonical(p).stat()):raise GateFailure(2)
    return b

def pe(path,machine):
    b=read(path)
    if machine not in MACHINES.values() or len(b)<152 or b[:2]!=b'MZ':raise GateFailure(2)
    offset=struct.unpack_from('<I',b,0x3c)[0]
    if not 64<=offset<=len(b)-26 or b[offset:offset+4]!=b'PE\0\0':raise GateFailure(2)
    actual=struct.unpack_from('<H',b,offset+4)[0];flags=struct.unpack_from('<H',b,offset+22)[0]
    if actual!=machine or not flags&2 or flags&0x2000 or struct.unpack_from('<H',b,offset+24)[0]!=0x20b:raise GateFailure(2)
    return {'machine':actual,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def coff(path,machine):
    b=read(path,32*1024*1024)
    if len(b)<60:raise GateFailure(2)
    actual,sections=struct.unpack_from('<HH',b)
    if actual!=machine or not 1<=sections<=65535 or 20+40*sections>len(b):raise GateFailure(2)
    return {'machine':actual,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def architecture(expected,native,emulated):
    if expected not in MACHINES or type(native) is not int or type(emulated) is not int or MACHINES[expected]!=native or emulated!=0:raise GateFailure(2)
    return expected

def verify_bundle(root):
    root=canonical(root,directory=True);raw=read(root/'final-manifest-v2.json',65536)
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:raise GateFailure(3)
    try:value=json.loads(raw)
    except BaseException:raise GateFailure(3) from None
    files=value.get('files')
    if type(files) is not list or len(files)!=13:raise GateFailure(3)
    raw=read(root/'source-inputs.json',65536)
    if hashlib.sha256(raw).hexdigest()!=SOURCE_INPUTS_SHA:raise GateFailure(3)
    try:ported=json.loads(raw)
    except BaseException:raise GateFailure(3) from None
    if type(ported) is not dict or set(ported)!={'schemaVersion','kind','originalManifestSha256','historicalValidationNotReissued','files'} or type(ported['schemaVersion']) is not int or ported['schemaVersion']!=1 or ported['kind']!='sdk-observer-relative-source-inputs' or ported['originalManifestSha256']!=MANIFEST_SHA or ported['historicalValidationNotReissued'] is not True or type(ported['files']) is not list or len(ported['files'])!=13:raise GateFailure(3)
    rows=[]
    for item,effective in zip(files,ported['files']):
        if type(item) is not dict or set(item)!= {'path','bytes','sha256'} or type(item['path']) is not str:raise GateFailure(3)
        if type(effective) is not dict or set(effective)!={'path','sourceBytes','sourceSha256','effectiveBytes','effectiveSha256','transformationCode'} or effective['path']!=item['path'] or effective['sourceBytes']!=item['bytes'] or effective['sourceSha256']!=item['sha256'] or type(effective['effectiveBytes']) is not int or not 0<effective['effectiveBytes']<=1024*1024 or type(effective['effectiveSha256']) is not str or not re.fullmatch('[0-9a-f]{64}',effective['effectiveSha256']):raise GateFailure(3)
        code=1 if item['path']=='README.md' else 0
        if type(effective['transformationCode']) is not int or effective['transformationCode']!=code:raise GateFailure(3)
        if not code and (effective['effectiveBytes']!=item['bytes'] or effective['effectiveSha256']!=item['sha256']):raise GateFailure(3)
        rel=Path(item['path'])
        if rel.is_absolute() or '..' in rel.parts or '\\' in item['path']:raise GateFailure(3)
        b=read(root/rel,1024*1024)
        if len(b)!=effective['effectiveBytes'] or hashlib.sha256(b).hexdigest()!=effective['effectiveSha256']:raise GateFailure(3)
        rows.append({'slot':len(rows)+1,'bytes':len(b),'sha256':effective['effectiveSha256']})
    if hashlib.sha256(read(root/'bundle-manifest-v2.json',65536)).hexdigest()!=BUNDLE_SHA:raise GateFailure(3)
    return rows

def sdk_members(version,arch):
    if not re.fullmatch(r'10\.0\.\d{4,6}\.\d{1,5}',version) or arch not in MACHINES:raise GateFailure(2)
    headers=('um/Windows.h','um/appmodel.h','um/sddl.h','um/shlobj.h','um/knownfolders.h',
      'shared/sdkddkver.h','ucrt/stdio.h','cppwinrt/winrt/base.h','cppwinrt/winrt/Windows.Storage.h')
    libraries=('windowsapp.lib','shell32.lib','ole32.lib','advapi32.lib','uuid.lib','kernel32.lib')
    return tuple('Include/'+version+'/'+p for p in headers)+tuple('Lib/'+version+'/um/'+arch+'/'+p for p in libraries)+('Lib/'+version+'/ucrt/'+arch+'/libucrt.lib',)

def installed_sdk(root,arch):
    root=canonical(root,directory=True)
    versions=[]
    for p in canonical(root/'Include',directory=True).iterdir():
        if p.is_dir() and re.fullmatch(r'10\.0\.\d{4,6}\.\d{1,5}',p.name):versions.append(p.name)
    for ver in sorted(versions,key=lambda v:tuple(map(int,v.split('.'))),reverse=True):
        try:
            rows=[]
            for rel in sdk_members(ver,arch):
                b=read(root/rel)
                rows.append({'slot':len(rows)+1,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
            return {'root':str(root),'version':ver,'files':rows}
        except (OSError,GateFailure):continue
    raise GateFailure(12)

def vs_metadata(raw):
    if type(raw) is not bytes or not 0<len(raw)<=256*1024:raise GateFailure(12)
    try:v=json.loads(raw.decode('utf-8-sig'))
    except BaseException:raise GateFailure(12) from None
    if type(v) is not list or len(v)!=1 or type(v[0]) is not dict:raise GateFailure(12)
    v=v[0];version=v.get('installationVersion');path=v.get('installationPath')
    if type(version) is not str or not re.fullmatch(r'(17|18)\.\d{1,3}(?:\.\d{1,6}){1,2}',version):raise GateFailure(12)
    if v.get('isComplete') is not True or v.get('isLaunchable') is not True or v.get('isPrerelease') is not False:raise GateFailure(12)
    return {'path':cmd_path(path),'version':version}

def installed_vs(metadata,arch):
    if arch not in MACHINES:raise GateFailure(2)
    root=canonical(metadata['path'],directory=True)
    raw=read(root/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt',128)
    try:ver=raw.decode('utf-8-sig').strip()
    except BaseException:raise GateFailure(12) from None
    if not re.fullmatch(r'14\.\d{1,3}\.\d{4,6}(?:\.\d{1,5})?',ver):raise GateFailure(12)
    binary=root/'VC/Tools/MSVC'/ver/'bin'/('Host'+arch)/arch
    dev=root/'Common7/Tools/VsDevCmd.bat';read(dev,1024*1024)
    cl=binary/'cl.exe';link=binary/'link.exe'
    rows={'cl':pe(cl,MACHINES[arch]),'link':pe(link,MACHINES[arch])}
    for name in ('libcmt.lib','libcpmt.lib','libvcruntime.lib'):read(root/'VC/Tools/MSVC'/ver/'lib'/arch/name)
    return {'root':str(root),'version':ver,'installationVersion':metadata['version'],'cl':str(cl),'link':str(link),'devcmd':str(dev),'records':rows,'devcmdSha256':hashlib.sha256(read(dev,1024*1024)).hexdigest()}

def system_locations(arch):
    if sys.platform!='win32':raise GateFailure(1)
    import winreg
    k=C.WinDLL('kernel32',use_last_error=True)
    k.GetWindowsDirectoryW.argtypes=[C.c_wchar_p,C.c_uint32];k.GetWindowsDirectoryW.restype=C.c_uint32
    k.GetModuleFileNameW.argtypes=[C.c_void_p,C.c_wchar_p,C.c_uint32];k.GetModuleFileNameW.restype=C.c_uint32
    k.GetCurrentProcess.argtypes=[];k.GetCurrentProcess.restype=C.c_void_p
    k.IsWow64Process2.argtypes=[C.c_void_p,C.POINTER(C.c_uint16),C.POINTER(C.c_uint16)];k.IsWow64Process2.restype=C.c_int32
    p,n=C.c_uint16(),C.c_uint16()
    if not k.IsWow64Process2(k.GetCurrentProcess(),C.byref(p),C.byref(n)):raise GateFailure(12)
    architecture(arch,n.value,p.value)
    buf=C.create_unicode_buffer(32768);length=k.GetWindowsDirectoryW(buf,len(buf))
    if not 0<length<len(buf):raise GateFailure(12)
    system=cmd_path(buf.value.rstrip('\\'))
    buf=C.create_unicode_buffer(32768);length=k.GetModuleFileNameW(None,buf,len(buf))
    if not 0<length<len(buf):raise GateFailure(12)
    controller=pe(buf.value,MACHINES[arch])
    def registry(key,name):
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as h:value,kind=winreg.QueryValueEx(h,name)
        if kind!=winreg.REG_SZ or type(value) is not str:raise GateFailure(12)
        return cmd_path(value.rstrip('\\'))
    key=r'SOFTWARE\Microsoft\Windows\CurrentVersion'
    pf=registry(key,'ProgramFilesDir');pf86=registry(key,'ProgramFilesDir (x86)')
    sdk=registry(r'SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0','InstallationFolder')
    vswhere=Path(pf86)/'Microsoft Visual Studio/Installer/vswhere.exe'
    # vswhere may be an installed x86 tool on both hosts; it is metadata discovery only.
    raw=read(vswhere)
    offset=struct.unpack_from('<I',raw,0x3c)[0] if len(raw)>=64 else 0
    if not 64<=offset<=len(raw)-26 or raw[offset:offset+4]!=b'PE\0\0':raise GateFailure(12)
    vs_machine=struct.unpack_from('<H',raw,offset+4)[0]
    if vs_machine not in (0x14c,MACHINES[arch]):raise GateFailure(12)
    cmd=Path(system)/'System32/cmd.exe';command=pe(cmd,MACHINES[arch])
    return {'system':system,'programFiles':pf,'programFilesX86':pf86,'sdk':sdk,'vswhere':str(vswhere),'command':str(cmd),
      'controller':controller,'commandRecord':command,'vswhereSha256':hashlib.sha256(raw).hexdigest()}
