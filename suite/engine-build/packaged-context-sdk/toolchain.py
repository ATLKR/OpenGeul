"""Installed native tools and exact observer input; never installs or downloads."""
from __future__ import annotations
import ctypes as C
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path
import re
import stat
import struct
import sys
import time
from supervisor import GateFailure,win_path

MANIFEST_SHA='746176ff820c8ca659fb09584f3d3dd6bf1fa33fe491ed73485e3e22e48390e5'
BUNDLE_SHA='0f38f3c60c36f73ab71c4af6a9b0eb77433c8f289659994c8b86070c25e866c6'
SOURCE_INPUTS_SHA='369bfbf3caaf51867e9dc5b330ad0f8206fa1c04e4f7378575c6922d055bbb04'
MACHINES={'x64':0x8664,'arm64':0xaa64}

def cmd_path(value):return win_path(value)

def _file_failure(code,links=None):
    error=GateFailure(2);error.filesystem_code=code
    if type(links) is int and 0<=links<=1048576:error.observed_link_count=links
    return error

def canonical(path,*,directory=False):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise _file_failure(1)
    for q in (p,*p.parents):
        s=q.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise _file_failure(2)
    s=p.stat()
    if directory:
        if not stat.S_ISDIR(s.st_mode):raise _file_failure(5)
    elif not stat.S_ISREG(s.st_mode):raise _file_failure(3)
    elif s.st_nlink!=1:raise _file_failure(4,s.st_nlink)
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

def installed_pe(path,machine,role):
    if type(role) is not int or role not in (1,2):raise GateFailure(2)
    try:return pe(path,machine)
    except GateFailure as error:
        error.file_role_code=role
        raise

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
    headers=('um/Windows.h','um/appmodel.h','shared/sddl.h','um/shlobj.h','um/knownfolders.h',
      'shared/sdkddkver.h','ucrt/stdio.h','cppwinrt/winrt/base.h','cppwinrt/winrt/Windows.Storage.h')
    libraries=('windowsapp.lib','shell32.lib','ole32.lib','advapi32.lib','uuid.lib','kernel32.lib')
    return tuple('Include/'+version+'/'+p for p in headers)+tuple('Lib/'+version+'/um/'+arch+'/'+p for p in libraries)+('Lib/'+version+'/ucrt/'+arch+'/libucrt.lib',)

def installed_sdk(root,arch,*,observations=None,operation=None):
    probe=None
    if observations is not None:
        keys={'operations','failures','failureCount','truncated'}
        if type(observations) is not dict or set(observations)!=keys or type(observations['operations']) is not list or type(observations['failures']) is not list or type(observations['failureCount']) is not int or not 0<=observations['failureCount']<=2147483647 or type(observations['truncated']) is not bool:raise GateFailure(2)
        if type(operation) is not int or operation not in (1,2) or [p.get('operationCode') for p in observations['operations']]!=list(range(1,operation)) or len(observations['failures'])>4:raise GateFailure(2)
        probe={'operationCode':operation,'enumerationKnown':False,'candidateCount':None}
        observations['operations'].append(probe)
    root=canonical(root,directory=True)
    versions=[]
    for p in canonical(root/'Include',directory=True).iterdir():
        if p.is_dir() and re.fullmatch(r'10\.0\.\d{4,6}\.\d{1,5}',p.name):versions.append(p.name)
    if probe is not None:probe.update(enumerationKnown=True,candidateCount=len(versions))
    for ver in sorted(versions,key=lambda v:tuple(map(int,v.split('.'))),reverse=True):
        slot=None
        try:
            rows=[]
            for slot,rel in enumerate(sdk_members(ver,arch),1):
                b=read(root/rel)
                rows.append({'slot':len(rows)+1,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
            return {'root':str(root),'version':ver,'files':rows}
        except (OSError,GateFailure) as error:
            if observations is not None:
                observations['failureCount']+=1
                if len(observations['failures'])<4:
                    from ci_entry import failure_observation
                    observations['failures'].append({'operationCode':operation,'version':list(map(int,ver.split('.'))),
                      'memberSlot':slot,'reason':failure_observation(error,1 if operation==1 else 6)})
                else:observations['truncated']=True
            continue
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

_REGISTRY_PATHS=(
    (r'SOFTWARE\Microsoft\Windows\CurrentVersion','ProgramFilesDir',64),
    (r'SOFTWARE\Microsoft\Windows\CurrentVersion','ProgramFilesDir (x86)',64),
    (r'SOFTWARE\Microsoft\Windows Kits\Installed Roots','KitsRoot10',32),
    (r'SOFTWARE\Microsoft\Windows Kits\Installed Roots','KitsRoot10',64),
    (r'SOFTWARE\Microsoft\Microsoft SDKs\Windows\v10.0','InstallationFolder',64))

def _registry_path(registry,slot,*,optional=False):
    if type(slot) is not int or not 1<=slot<=5 or type(optional) is not bool or optional and slot not in (3,4,5):raise GateFailure(12)
    key,name,view=_REGISTRY_PATHS[slot-1]
    flags=registry.KEY_READ|(registry.KEY_WOW64_32KEY if view==32 else registry.KEY_WOW64_64KEY)
    try:handle=registry.OpenKey(registry.HKEY_LOCAL_MACHINE,key,0,flags)
    except FileNotFoundError as error:
        if optional and type(error) is FileNotFoundError and getattr(error,'winerror',None)==2:return None,1
        raise
    with handle:
        try:value,kind=registry.QueryValueEx(handle,name)
        except FileNotFoundError as error:
            if optional and type(error) is FileNotFoundError and getattr(error,'winerror',None)==2:return None,2
            raise
    if type(kind) is not int or kind!=registry.REG_SZ or type(value) is not str:raise GateFailure(12)
    return cmd_path(value.rstrip('\\')),0

def sdk_registry_root(registry):
    # CsWinRT open_sdk() explicitly tries the32-bit Installed Roots view.
    # Check both exact modern views and the original legacy64 contract.
    rows=tuple(_registry_path(registry,slot,optional=True) for slot in (3,4,5))
    present=[root for root,missing in rows if root is not None]
    if not present:
        # Bits4/2/1 denote missing VALUE rather than KEY in modern32/64/legacy64.
        # All eight shapes fit the existing native/public failureCode bound31.
        raise GateFailure(24+sum(bit for (root,missing),bit in zip(rows,(4,2,1)) if missing==2))
    if any(ntpath.normcase(root)!=ntpath.normcase(present[0]) for root in present[1:]):raise GateFailure(13)
    return present[0]

class _CommandLease:
    """OS-selected WRP classification and change detection, not signature proof."""
    def __init__(self,architecture,deadline,api,*,clock=time.monotonic):
        self._api=api;self._clock=clock;self._deadline=deadline;self._handle=None
        self._record=None;self._base=None;self._stable=False;self._wrp=False
        self._closed=False;self._close_attempted=False;self._cleanup_ok=True;self._rechecks=0
        self.path=None;self.system_root=None
        try:
            if architecture not in MACHINES:raise GateFailure(14)
            self._machine=MACHINES[architecture];self._check(deadline)
            self.path,self.system_root=self._os_path(deadline)
            # Store a returned native handle before any post-call clock check.
            self._handle=self._api.open(self.path);self._check(deadline)
            self._valid_handle(self._handle)
            stamp,record=self._measure(self._handle,deadline)
            self._base=stamp;self._record=record
            self.verify()
        except BaseException as error:
            self.close()
            if isinstance(error,(KeyboardInterrupt,SystemExit,GateFailure)):raise
            raise GateFailure(14) from None
    @staticmethod
    def _valid_handle(handle):
        if type(handle) is not int or not 0<handle<(1<<(8*C.sizeof(C.c_void_p)))-1:raise GateFailure(14)
    def _check(self,end):
        now=self._clock()
        if (type(end) not in (int,float) or type(self._deadline) not in (int,float)
            or not math.isfinite(end) or not math.isfinite(self._deadline) or end>self._deadline
            or type(now) not in (int,float) or not math.isfinite(now) or now>=end-1):raise GateFailure(10)
    def _call(self,name,*args,end):
        self._check(end);self._api.set_deadline(end)
        value=getattr(self._api,name)(*args);self._check(end);return value
    def _os_path(self,end):
        directory=cmd_path(self._call('system_directory',end=end).rstrip('\\'))
        windows=cmd_path(self._call('windows_directory',end=end).rstrip('\\'))
        path=cmd_path(ntpath.join(directory,'cmd.exe'))
        if ntpath.normcase(path)!=ntpath.normcase(ntpath.join(windows,'System32','cmd.exe')):raise GateFailure(14)
        if self._call('no_reparse',path,end=end) is not True:raise GateFailure(14)
        protected=self._call('is_protected',path,end=end);self._wrp=protected is True
        if protected is not True:raise GateFailure(14)
        return path,windows
    def _stamp(self,value):
        keys={'identity','finalPath','size','modified','links','regular','reparse','inheritable'}
        if type(value) is not dict or set(value)!=keys:raise GateFailure(14)
        identity=value['identity'];modified=value['modified'];size=value['size'];links=value['links']
        if (type(identity) is not tuple or len(identity)!=2 or type(identity[0]) is not int or not 0<identity[0]<=0xffffffffffffffff
            or type(identity[1]) is not bytes or len(identity[1])!=16 or not any(identity[1])
            or type(modified) is not tuple or len(modified)!=2 or any(type(v) is not int or not 0<v<=0x7fffffffffffffff for v in modified)
            or type(size) is not int or not 0<size<=128*1024*1024 or type(links) is not int or not 1<=links<=1048576
            or value['regular'] is not True or value['reparse'] is not False or value['inheritable'] is not False):raise GateFailure(14)
        final=value['finalPath']
        if type(final) is not str or not final.startswith('\\\\?\\') or len(final)>32768:raise GateFailure(14)
        final=cmd_path(final[4:])
        if ntpath.normcase(final)!=ntpath.normcase(self.path):raise GateFailure(14)
        return identity,ntpath.normcase(final),size,modified,links
    def _measure(self,handle,end):
        before=self._stamp(self._call('snapshot',handle,end=end))
        b=self._call('read',handle,before[2],end=end)
        after=self._stamp(self._call('snapshot',handle,end=end))
        if type(b) is not bytes or len(b)!=before[2] or before!=after:raise GateFailure(14)
        if len(b)<152 or b[:2]!=b'MZ':raise GateFailure(14)
        offset=struct.unpack_from('<I',b,0x3c)[0]
        if not 64<=offset<=len(b)-26 or b[offset:offset+4]!=b'PE\0\0':raise GateFailure(14)
        machine=struct.unpack_from('<H',b,offset+4)[0];flags=struct.unpack_from('<H',b,offset+22)[0]
        if machine!=self._machine or not flags&2 or flags&0x2000 or struct.unpack_from('<H',b,offset+24)[0]!=0x20b:raise GateFailure(14)
        return after,{'machine':machine,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    @property
    def record(self):
        return None if self._record is None else dict(self._record)
    def verify(self,*,deadline=None):
        self._stable=False;end=self._deadline if deadline is None else deadline;fresh=None
        try:
            self._check(end);self._valid_handle(self._handle)
            path,windows=self._os_path(end)
            if ntpath.normcase(path)!=ntpath.normcase(self.path) or ntpath.normcase(windows)!=ntpath.normcase(self.system_root):raise GateFailure(14)
            stamp,record=self._measure(self._handle,end)
            if stamp!=self._base or record!=self._record:raise GateFailure(14)
            # Retain fresh handle before the deadline can reject this phase.
            fresh=self._api.open(self.path);self._check(end);self._valid_handle(fresh)
            stamp,record=self._measure(fresh,end)
            if stamp!=self._base or record!=self._record:raise GateFailure(14)
            self._rechecks+=1;self._stable=True
        except (KeyboardInterrupt,SystemExit,GateFailure):raise
        except BaseException:raise GateFailure(14) from None
        finally:
            if fresh is not None:
                try:closed=self._api.close(fresh) is True
                except BaseException:closed=False
                if not closed:
                    self._cleanup_ok=False;self._stable=False
                    if sys.exc_info()[0] is None:raise GateFailure(14)
        return self.record
    def close(self):
        if self._close_attempted:return self._closed and self._cleanup_ok
        self._close_attempted=True;handle=self._handle;self._handle=None
        if handle is None:self._closed=True
        else:
            try:self._closed=self._api.close(handle) is True
            except BaseException:self._closed=False
        return self._closed and self._cleanup_ok
    def observation(self):
        return {'systemDirectoryKnown':self._record is not None,'wrpProtected':self._wrp,
          'protectionClassificationOnly':True,'signatureVerified':False,
          'linkCount':None if self._base is None else self._base[4],
          'handleIdentityStable':self._stable,'freshPathStable':self._stable,'bytesPeHashStable':self._stable,
          'rechecks':self._rechecks,'closed':self._closed and self._cleanup_ok}

def acquire_command(architecture,deadline):
    try:
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or time.monotonic()>=deadline-1:raise GateFailure(10)
        return _CommandLease(architecture,deadline,_Win32CommandApi(deadline))
    except GateFailure as error:
        error.file_role_code=2
        raise

def validate_command_observation(value,*,require_closed=False):
    keys={'systemDirectoryKnown','wrpProtected','protectionClassificationOnly','signatureVerified',
      'linkCount','handleIdentityStable','freshPathStable','bytesPeHashStable','rechecks','closed'}
    if type(value) is not dict or set(value)!=keys or type(require_closed) is not bool:raise GateFailure(14)
    for name in keys-{'linkCount','rechecks'}:
        if type(value[name]) is not bool:raise GateFailure(14)
    if value['protectionClassificationOnly'] is not True or value['signatureVerified'] is not False:raise GateFailure(14)
    if value['linkCount'] is not None and (type(value['linkCount']) is not int or not 1<=value['linkCount']<=1048576):raise GateFailure(14)
    if type(value['rechecks']) is not int or not 0<=value['rechecks']<=128:raise GateFailure(14)
    if require_closed and (value['linkCount'] is None or value['rechecks']<1 or any(value[k] is not True for k in
      ('systemDirectoryKnown','wrpProtected','handleIdentityStable','freshPathStable','bytesPeHashStable','closed'))):raise GateFailure(14)
    return value

def system_locations(arch,*,deadline):
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
    controller=installed_pe(buf.value,MACHINES[arch],1)
    pf,_=_registry_path(winreg,1);pf86,_=_registry_path(winreg,2)
    sdk=sdk_registry_root(winreg)
    vswhere=Path(pf86)/'Microsoft Visual Studio/Installer/vswhere.exe'
    # vswhere may be an installed x86 tool on both hosts; it is metadata discovery only.
    try:raw=read(vswhere)
    except GateFailure as error:
        error.file_role_code=3
        raise
    offset=struct.unpack_from('<I',raw,0x3c)[0] if len(raw)>=64 else 0
    if not 64<=offset<=len(raw)-26 or raw[offset:offset+4]!=b'PE\0\0':raise GateFailure(12)
    vs_machine=struct.unpack_from('<H',raw,offset+4)[0]
    if vs_machine not in (0x14c,MACHINES[arch]):raise GateFailure(12)
    lease=acquire_command(arch,deadline)
    try:
        if ntpath.normcase(system)!=ntpath.normcase(lease.system_root):raise GateFailure(14)
        return {'system':system,'programFiles':pf,'programFilesX86':pf86,'sdk':sdk,'vswhere':str(vswhere),'command':lease.path,
          'controller':controller,'commandRecord':lease.record,'commandLease':lease,'vswhereSha256':hashlib.sha256(raw).hexdigest()}
    except BaseException:
        lease.close()
        raise


"""Native-only fragment for the SDK toolchain's exact OS-command lease.

Merge into toolchain.py, whose existing GateFailure and canonical are required.
This adapter reports file observations; it does not grant a path, hardlink,
publisher, signature, runtime or servicing qualification.
"""
import ctypes as C
import os
from os import fspath as _command_fspath
from pathlib import Path
import stat
import sys
import math
import time


class _CommandFileId128(C.Structure):
    _fields_=[('Identifier',C.c_uint8*16)]


class _CommandFileIdInfo(C.Structure):
    _fields_=[('VolumeSerialNumber',C.c_uint64),('FileId',_CommandFileId128)]


class _CommandStandardInfo(C.Structure):
    _fields_=[('AllocationSize',C.c_int64),('EndOfFile',C.c_int64),
        ('NumberOfLinks',C.c_uint32),('DeletePending',C.c_uint8),('Directory',C.c_uint8)]


class _CommandAttributeTagInfo(C.Structure):
    _fields_=[('FileAttributes',C.c_uint32),('ReparseTag',C.c_uint32)]


class _CommandBasicInfo(C.Structure):
    _fields_=[('CreationTime',C.c_int64),('LastAccessTime',C.c_int64),
        ('LastWriteTime',C.c_int64),('ChangeTime',C.c_int64),('FileAttributes',C.c_uint32)]


def _command_wide(path):
    value=_command_fspath(path)
    if type(value) is not str or not value or '\0' in value:
        raise GateFailure(14) from None
    raw=value.encode('utf-16-le')
    if len(raw)//2>=32768:
        raise GateFailure(14) from None
    return (C.c_uint16*(len(raw)//2+1)).from_buffer_copy(raw+b'\0\0')


def _command_handle(value):
    if type(value) is not int or not 0<value<(1<<(C.sizeof(C.c_void_p)*8))-1:
        raise GateFailure(14) from None
    return value


def _command_text(buffer,length):
    if type(length) is not int or not 0<length<len(buffer) or buffer[length]!=0:
        raise GateFailure(14) from None
    value=C.string_at(C.addressof(buffer),length*2).decode('utf-16-le')
    if not value or '\0' in value:
        raise GateFailure(14) from None
    return value


class _Win32CommandApi:
    """Typed read-only APIs; native calls are unavailable on non-Windows hosts."""
    def __init__(self,deadline,*,clock=time.monotonic):
        self._deadline=deadline;self._active_end=deadline;self._clock=clock
        try:
            self.set_deadline(deadline)
            if os.name!='nt' or sys.platform!='win32' or C.sizeof(C.c_void_p)!=8:
                raise GateFailure(14) from None
            self._kernel=self._invoke(C.WinDLL,'kernel32.dll',use_last_error=True,winmode=0x800)
            self._sfc=self._invoke(C.WinDLL,'sfc.dll',use_last_error=True,winmode=0x800)
            u16=C.POINTER(C.c_uint16);u32=C.c_uint32;handle=C.c_void_p;i32=C.c_int32
            def bind(dll,name,args,result):
                function=getattr(dll,name);function.argtypes=args;function.restype=result
                return function
            self._system=self._invoke(bind,self._kernel,'GetSystemDirectoryW',[u16,u32],u32)
            self._windows=self._invoke(bind,self._kernel,'GetWindowsDirectoryW',[u16,u32],u32)
            self._protected=self._invoke(bind,self._sfc,'SfcIsFileProtected',[handle,u16],i32)
            self._open=self._invoke(bind,self._kernel,'CreateFileW',[u16,u32,u32,handle,u32,u32,handle],handle)
            self._information=self._invoke(bind,self._kernel,'GetFileInformationByHandleEx',[handle,i32,handle,u32],i32)
            self._final=self._invoke(bind,self._kernel,'GetFinalPathNameByHandleW',[handle,u16,u32,u32],u32)
            self._type=self._invoke(bind,self._kernel,'GetFileType',[handle],u32)
            self._flags=self._invoke(bind,self._kernel,'GetHandleInformation',[handle,C.POINTER(u32)],i32)
            self._seek=self._invoke(bind,self._kernel,'SetFilePointerEx',[handle,C.c_int64,C.POINTER(C.c_int64),u32],i32)
            self._read=self._invoke(bind,self._kernel,'ReadFile',[handle,handle,u32,C.POINTER(u32),handle],i32)
            self._close=self._invoke(bind,self._kernel,'CloseHandle',[handle],i32)
        except GateFailure:raise
        except Exception:
            raise GateFailure(14) from None

    def _check_end(self,end):
        now=self._clock()
        if (type(end) not in (int,float) or type(self._deadline) not in (int,float)
                or not math.isfinite(end) or not math.isfinite(self._deadline)
                or end>self._deadline or type(now) not in (int,float)
                or not math.isfinite(now) or now>=end-1):
            raise GateFailure(10) from None

    def set_deadline(self,end):
        """Use a caller phase inside the original window, never a new window."""
        try:self._check_end(end);self._active_end=end
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def _check(self):
        self._check_end(self._active_end)

    def _invoke(self,function,*args,**kwargs):
        self._check();value=function(*args,**kwargs);self._check();return value

    def _directory(self,function):
        buffer=(C.c_uint16*32768)()
        return _command_text(buffer,self._invoke(function,buffer,len(buffer)))

    def system_directory(self):
        try:return self._directory(self._system)
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def windows_directory(self):
        try:return self._directory(self._windows)
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def no_reparse(self,path):
        try:
            self._check();leaf=Path(path)
            if not leaf.is_absolute() or '..' in leaf.parts:return False
            for parent in leaf.parents:
                info=self._invoke(parent.lstat)
                if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                        or getattr(info,'st_file_attributes',0)&0x400):return False
            info=self._invoke(leaf.lstat)
            return bool(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and not getattr(info,'st_file_attributes',0)&0x400)
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def is_protected(self,path):
        try:return bool(self._invoke(self._protected,None,_command_wide(path)))
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def open(self,path):
        try:
            # No other native API may run between acquiring and returning this
            # handle: the caller must retain it before deadline/policy checks.
            self._check()
            return _command_handle(self._open(_command_wide(path),0x80000000,1,None,3,0x00200000,None))
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def snapshot(self,handle):
        try:
            handle=_command_handle(handle)
            values=[]
            for kind,structure in ((18,_CommandFileIdInfo),(1,_CommandStandardInfo),
                    (9,_CommandAttributeTagInfo),(0,_CommandBasicInfo)):
                value=structure()
                if not self._invoke(self._information,handle,kind,C.byref(value),C.sizeof(value)):
                    raise GateFailure(14) from None
                values.append(value)
            identity,standard,attributes,basic=values
            buffer=(C.c_uint16*32768)()
            final=_command_text(buffer,self._invoke(self._final,handle,buffer,len(buffer),0))
            file_type=self._invoke(self._type,handle);flags=C.c_uint32()
            if not self._invoke(self._flags,handle,C.byref(flags)):
                raise GateFailure(14) from None
            return dict(identity=(int(identity.VolumeSerialNumber),bytes(identity.FileId.Identifier)),
                finalPath=final,size=int(standard.EndOfFile),
                modified=(int(basic.LastWriteTime),int(basic.ChangeTime)),links=int(standard.NumberOfLinks),
                regular=bool(file_type==1 and not standard.Directory and not standard.DeletePending
                    and not (attributes.FileAttributes|basic.FileAttributes)&0x10),
                reparse=bool((attributes.FileAttributes|basic.FileAttributes)&0x400 or attributes.ReparseTag),
                inheritable=bool(flags.value&1))
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def read(self,handle,expected_size):
        try:
            handle=_command_handle(handle)
            if type(expected_size) is not int or not 0<expected_size<=128*1024*1024:
                raise GateFailure(14) from None
            position=C.c_int64()
            if not self._invoke(self._seek,handle,0,C.byref(position),0) or position.value!=0:
                raise GateFailure(14) from None
            data=bytearray()
            while len(data)<expected_size:
                size=min(65536,expected_size-len(data));buffer=(C.c_uint8*size)();received=C.c_uint32()
                if not self._invoke(self._read,handle,buffer,size,C.byref(received),None) or not 0<received.value<=size:
                    raise GateFailure(14) from None
                data.extend(bytes(buffer[:received.value]))
            extra=(C.c_uint8*1)();received=C.c_uint32()
            if not self._invoke(self._read,handle,extra,1,C.byref(received),None) or received.value!=0:
                raise GateFailure(14) from None
            return bytes(data)
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None

    def close(self,handle):
        try:return bool(self._close(_command_handle(handle)))
        except GateFailure:raise
        except Exception:raise GateFailure(14) from None
