"""Unwired file-only DbgHelp adapter. An owned child watchdog is REQUIRED externally.

Native calls cannot be preempted by this injected budget. Never use this inside
an editor hook, load the target DLL, or treat a symbol name as runtime evidence.
"""
import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
import struct
import threading
import uuid


def _module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

retention=_module('resolution_retention',Path(__file__).with_name('retain-plugin-symbols.py'))
IMAGE_BASE=0x10000000
# Exact symbols; local explicit paths only; no deferred/public-only/anything fallback.
OPTIONS=0x400|0x80|0x1000|0x20000|0x100|0x80000|0x2000000|0x200|0x2
TAGS={'WinSalYieldMutex::doAcquire':'mutex-acquire','WinSalYieldMutex::doRelease':'mutex-release',
      'ImplSalYieldMutexAcquireWithWait':'mutex-acquire-with-wait'}
SERIAL=threading.Lock()


class ResolutionError(ValueError):pass
class ModuleIdentityError(ResolutionError):
    # Bits: symbol type, base, size, GUID, age, unmatched flag, exact PDB path.
    def __str__(self):return 'loaded-symbol-identity'

def require(ok,code):
    if not ok:raise ResolutionError(code)


def _path_syntax(path):
    path=Path(path)
    text=str(path)
    require(path.is_absolute() and not text.startswith(('\\\\','//')) and
            not any(c in text for c in ('*',';','\r','\n')) and 'srv' not in text.lower().split(':')[:-1], 'local-path-required')
    # ANSI DbgHelp seam is deliberately limited to exact ASCII local paths.
    require(text.isascii(),'unsupported-local-path-encoding')
    return path


def _path(path,budget=None):
    path=_path_syntax(path)
    retention.unlinked(path,budget=budget)
    return path


def _frame(value,return_rva,image_size):
    result=dict(returnRva=return_rva,callRva=return_rva-4,tag='unresolved')
    if not isinstance(value,dict):return result
    address,size=value.get('address'),value.get('size');name=value.get('name')
    flags=value.get('flags')
    if (type(address) is not int or type(size) is not int or type(flags) is not int or
        value.get('base')!=IMAGE_BASE or value.get('tag')!=5 or flags & (0x200|0x400|0x2000) or
        size<=0 or not IMAGE_BASE<=address<address+size<=IMAGE_BASE+image_size or
        not address<=IMAGE_BASE+return_rva-4<address+size or name not in TAGS):return result
    result.update(tag=TAGS[name],functionRva=address-IMAGE_BASE,functionSize=size)
    return result


def resolve(dll_bytes,pdb_path,verified_identity,return_rvas,budget,runtime=None):
    require(SERIAL.acquire(blocking=False),'concurrent-symbol-session')
    try:return _resolve(dll_bytes,pdb_path,verified_identity,return_rvas,budget,runtime)
    finally:SERIAL.release()


def qualify(dll_bytes,pdb_path,verified_identity,budget,runtime=None):
    require(SERIAL.acquire(blocking=False),'concurrent-symbol-session')
    try:return _resolve(dll_bytes,pdb_path,verified_identity,[],budget,runtime,qualification=True)
    finally:SERIAL.release()


def _resolve(dll_bytes,pdb_path,proof,rvas,budget,runtime,qualification=False):
    budget.now()
    require(budget.deadline==budget.started+30 and budget.work_deadline==budget.deadline-3,'original-budget-required')
    require(type(dll_bytes) is bytes and 0<len(dll_bytes)<=retention.MAX_DLL and type(proof) is dict and proof.get('kind')=='matched-plugin-symbols' and
            proof.get('identityMatched') is True and proof.get('acceptance') is False,'verified-pair-required')
    require(not os.environ.get('_NT_SYMBOL_PATH') and not os.environ.get('_NT_ALTERNATE_SYMBOL_PATH'),'ambient-symbol-path')
    path=_path_syntax(pdb_path);require(path.name=='vclplug_winlo.pdb','fixed-pdb-name')
    budget.now()
    if runtime is None:runtime=NativeRuntime(budget)
    runtime.preflight_path(str(path));budget.now()
    path=_path(path,budget)
    entries=[]
    for entry in path.parent.iterdir():
        budget.now();entries.append(entry.name)
        require(len(entries)<=3 and entry.name in ('vclplug_winlo.pdb','vclplug_winlo.dll','receipt.json'),'pair-only-directory')
        _path(entry,budget)
        require(entry.is_file(),'pair-only-directory')
    pdb_bytes=retention.read_regular(path,retention.MAX_PDB,budget=budget);budget.now()
    for key,data,name in (('dll',dll_bytes,'vclplug_winlo.dll'),('pdb',pdb_bytes,'vclplug_winlo.pdb')):
        require(proof.get('files',{}).get(key)==dict(name=name,**retention.pin(data)),'pair-hash-mismatch')
        budget.now()
    identity=retention.pe_identity(dll_bytes)
    require(identity==retention.pdb_identity(pdb_bytes)==proof.get('matchedIdentity'),'pair-identity-mismatch');budget.now()
    pe=struct.unpack_from('<I',dll_bytes,60)[0];image_size=struct.unpack_from('<I',dll_bytes,pe+24+56)[0]
    require(type(rvas) is list and (len(rvas)==0 if qualification else 0<len(rvas)<=32) and all(type(r) is int and 4<=r<=image_size and r%4==0 for r in rvas),'return-rva-bounds')
    image_path=_path(path.with_name('vclplug_winlo.dll'),budget)
    require(retention.read_regular(image_path,retention.MAX_DLL,budget=budget)==dll_bytes,'image-bytes-mismatch');budget.now()
    receipt=dict(schemaVersion=1,kind='local-plugin-symbol-resolution',acceptance=False,runtimeCallerProved=False,functionAliasUniquenessProved=False,
                 identity=identity,dllSha256=retention.pin(dll_bytes)['sha256'],pdbSha256=retention.pin(pdb_bytes)['sha256'],
                 complete=False,cleanupComplete=False,frames=[],cleanupErrors=[],nativeCallsPreemptible=False)
    initialized=False;loaded=0;held=None;image_held=None;primary=None
    try:
        budget.now()
        budget.now();held=runtime.hold(str(path))
        require(type(held) is int and held>0,'pdb-handle');budget.now()
        require(retention.read_regular(path,retention.MAX_PDB,budget=budget)==pdb_bytes,'pdb-changed-under-lock');budget.now()
        receipt['pdbHeldDuringResolution']=True
        image_held=runtime.hold(str(image_path))
        require(type(image_held) is int and image_held>0,'image-handle');budget.now()
        require(retention.read_regular(image_path,retention.MAX_DLL,budget=budget)==dll_bytes,'image-changed-under-lock');budget.now()
        receipt['imageHeldDuringResolution']=True
        budget.now();initialized=runtime.initialize(str(path.parent),OPTIONS)
        require(initialized is True,'symbol-initialize');budget.now()
        # Supply the verified PE so DbgHelp can match its CodeView identity to
        # the held PDB. This reads symbol metadata; it never executes the image.
        loaded=runtime.load(str(image_path),IMAGE_BASE,image_size,image_held)
        require(loaded==IMAGE_BASE,'symbol-load');budget.now()
        info=runtime.module(IMAGE_BASE);budget.now()
        # DbgHelp documents both SymPdb and SymDia as loaded symbol backends.
        # Every exact identity predicate and the later function proof still apply.
        checks=(info.get('type') in (3,7),info.get('base')==IMAGE_BASE,
                info.get('size')==image_size,info.get('guid')==identity['guid'],
                info.get('age')==identity['age'],info.get('unmatched') is False,
                Path(info.get('path',''))==path)
        mismatch=sum(1<<i for i,matched in enumerate(checks) if not matched)
        if mismatch:
            symbol_type=info.get('type')
            # No actual identity/path value leaves the bounded child.
            kind=symbol_type if type(symbol_type) is int and 0<=symbol_type<=8 else 9
            raise ModuleIdentityError((mismatch,kind))
        if qualification:
            budget.now();named=runtime.fixed_acquire();budget.now()
            require(type(named) is dict and type(named.get('address')) is int,'fixed-symbol-unavailable')
            rva=named['address']-IMAGE_BASE+4
            require(rva%4==0 and _frame(named,rva,image_size)['tag']=='mutex-acquire','fixed-symbol-range')
            budget.now();again=runtime.query(named['address']);budget.now()
            require(again==named,'fixed-symbol-roundtrip')
            receipt['qualification']=dict(roundTripMatched=True,tag='mutex-acquire',
                functionRva=rva-4,functionSize=named['size'],functionAliasUniquenessProved=False)
        for rva in rvas:
            budget.now();value=runtime.query(IMAGE_BASE+rva-4);budget.now()
            receipt['frames'].append(_frame(value,rva,image_size))
        require(retention.read_regular(image_path,retention.MAX_DLL,budget=budget)==dll_bytes,'image-changed');budget.now()
        require(retention.read_regular(path,retention.MAX_PDB,budget=budget)==pdb_bytes,'pdb-changed');budget.now()
        receipt['complete']=True
    except BaseException as exc:
        primary=exc;receipt['failureClass']=type(exc).__name__
        raise
    finally:
        # Mandatory release is attempted even after expiry; no additional query.
        for label,action in (('unload',lambda:runtime.unload(loaded)) if loaded else ('unload',None),
                             ('cleanup',lambda:runtime.cleanup()) if initialized else ('cleanup',None),
                             ('image-handle',lambda:runtime.release(image_held)) if image_held else ('image-handle',None),
                             ('pdb-handle',lambda:runtime.release(held)) if held else ('pdb-handle',None)):
            if action is None:continue
            try:require(action() is True,'symbol-'+label)
            except BaseException as error:receipt['cleanupErrors'].append(dict(stage=label,errorType=type(error).__name__))
        try:budget.now(cleanup=True)
        except BaseException as error:receipt['cleanupErrors'].append(dict(stage='cleanup-budget',errorType=type(error).__name__))
        receipt['cleanupComplete']=not receipt['cleanupErrors']
        if primary is not None:primary.resolutionReceipt=receipt
        elif not receipt['cleanupComplete']:
            error=ResolutionError('symbol-cleanup');error.resolutionReceipt=receipt;raise error
    require(len(json.dumps(receipt))<=8192,'receipt-size')
    return receipt


U32=C.c_uint32;U64=C.c_uint64;BOOL=C.c_int32
class ModuleInfo(C.Structure):
    _fields_=[('SizeOfStruct',U32),('BaseOfImage',U64),('ImageSize',U32),('TimeDateStamp',U32),('CheckSum',U32),
        ('NumSyms',U32),('SymType',U32),('ModuleName',C.c_char*32),('ImageName',C.c_char*256),
        ('LoadedImageName',C.c_char*256),('LoadedPdbName',C.c_char*256),('CVSig',U32),('CVData',C.c_char*780),
        ('PdbSig',U32),('PdbSig70',C.c_ubyte*16),('PdbAge',U32),('PdbUnmatched',BOOL),('DbgUnmatched',BOOL),
        ('LineNumbers',BOOL),('GlobalSymbols',BOOL),('TypeInfo',BOOL),('SourceIndexed',BOOL),('Publics',BOOL),
        ('MachineType',U32),('Reserved',U32)]
class SymbolInfo(C.Structure):
    _fields_=[('SizeOfStruct',U32),('TypeIndex',U32),('Reserved',U64*2),('Index',U32),('Size',U32),
        ('ModBase',U64),('Flags',U32),('Value',U64),('Address',U64),('Register',U32),('Scope',U32),
        ('Tag',U32),('NameLen',U32),('MaxNameLen',U32),('Name',C.c_char*1)]


class NativeRuntime:
    """Single-session Windows adapter; system DbgHelp only, never target image load."""
    def __init__(self,budget):
        self.budget=budget;budget.now()
        require(os.name=='nt','native-windows-required')
        arch=_module('resolution_arch',Path(__file__).resolve().parents[1]/'e2e/native_suite_architecture.py')
        arch.validate_native_architecture(arch.observe_native_architecture(),'arm64')
        budget.now()
        kernel=C.WinDLL('kernel32.dll',use_last_error=True,winmode=0x800)
        kernel.GetDriveTypeW.argtypes=[C.c_wchar_p];kernel.GetDriveTypeW.restype=U32
        self.drive_type=kernel.GetDriveTypeW
        kernel.CreateFileW.argtypes=[C.c_wchar_p,U32,U32,C.c_void_p,U32,U32,C.c_void_p];kernel.CreateFileW.restype=C.c_void_p
        kernel.CloseHandle.argtypes=[C.c_void_p];kernel.CloseHandle.restype=BOOL
        self.open_file=kernel.CreateFileW;self.close_file=kernel.CloseHandle
        kernel.GetSystemDirectoryW.argtypes=[C.c_wchar_p,U32];kernel.GetSystemDirectoryW.restype=U32
        budget.now()
        buffer=C.create_unicode_buffer(32768);length=kernel.GetSystemDirectoryW(buffer,len(buffer))
        require(0<length<len(buffer),'system-directory');budget.now()
        library=_path(Path(buffer.value)/'dbghelp.dll',budget)
        budget.now()
        self.dll=C.WinDLL(str(library),use_last_error=True,winmode=0x800)
        budget.now()
        self.token=C.c_ubyte();self.session=C.cast(C.pointer(self.token),C.c_void_p)
        def bind(name,args,result):
            fn=getattr(self.dll,name);fn.argtypes=args;fn.restype=result;return fn
        self.options=bind('SymSetOptions',[U32],U32)
        self.init=bind('SymInitialize',[C.c_void_p,C.c_char_p,BOOL],BOOL)
        self.load_module=bind('SymLoadModuleEx',[C.c_void_p,C.c_void_p,C.c_char_p,C.c_char_p,U64,U32,C.c_void_p,U32],U64)
        self.get_module=bind('SymGetModuleInfo64',[C.c_void_p,U64,C.POINTER(ModuleInfo)],BOOL)
        self.get_symbol=bind('SymFromAddr',[C.c_void_p,U64,C.POINTER(U64),C.POINTER(SymbolInfo)],BOOL)
        self.get_named=bind('SymFromName',[C.c_void_p,C.c_char_p,C.POINTER(SymbolInfo)],BOOL)
        self.unload_module=bind('SymUnloadModule64',[C.c_void_p,U64],BOOL)
        self.clean=bind('SymCleanup',[C.c_void_p],BOOL)
    def preflight_path(self,path):
        _path_syntax(path)
        self.budget.now();require(self.drive_type(str(Path(path).anchor))==3,'local-fixed-drive')
        self.budget.now()
    def hold(self,path):
        self.budget.now();require(self.drive_type(str(Path(path).anchor))==3,'local-fixed-drive')
        self.budget.now()
        handle=self.open_file(path,0x80000000,1,None,3,0x80,None)
        require(handle not in (None,0,C.c_void_p(-1).value),'symbol-file-open')
        # Transfer ownership before any subsequent deadline check.
        return int(handle)
    def release(self,handle):return bool(self.close_file(handle))
    def initialize(self,path,options):
        self.budget.now();require(self.drive_type(str(Path(path).anchor))==3,'local-fixed-drive')
        self.budget.now();require(self.options(options)==options,'symbol-options')
        self.budget.now()
        return bool(self.init(self.session,path.encode('ascii'),False))
    def load(self,path,base,size,image_handle):
        require(type(image_handle) is int and 0<image_handle<C.c_void_p(-1).value,'image-handle')
        return int(self.load_module(self.session,image_handle,path.encode('ascii'),b'owned_plugin',base,size,None,0))
    def module(self,base):
        info=ModuleInfo();info.SizeOfStruct=C.sizeof(info)
        require(self.get_module(self.session,base,C.byref(info)),'module-information')
        return dict(type=int(info.SymType),base=int(info.BaseOfImage),size=int(info.ImageSize),
            path=info.LoadedPdbName.decode('ascii'),guid=str(uuid.UUID(bytes_le=bytes(info.PdbSig70))),age=int(info.PdbAge),
            unmatched=bool(info.PdbUnmatched or info.DbgUnmatched))
    def fixed_acquire(self):
        return self._symbol(lambda info:self.get_named(self.session,b'owned_plugin!WinSalYieldMutex::doAcquire',info))
    def query(self,address):
        displacement=U64()
        return self._symbol(lambda info:self.get_symbol(self.session,address,C.byref(displacement),info))
    def _symbol(self,call):
        storage=C.create_string_buffer(C.sizeof(SymbolInfo)+1024);info=C.cast(storage,C.POINTER(SymbolInfo))
        info.contents.SizeOfStruct=C.sizeof(SymbolInfo);info.contents.MaxNameLen=1024
        if not call(info):return None
        value=info.contents
        require(value.NameLen<1024,'symbol-name-bound')
        name=C.string_at(C.addressof(storage)+SymbolInfo.Name.offset,value.NameLen).decode('ascii',errors='strict')
        return dict(name=name,base=int(value.ModBase),address=int(value.Address),size=int(value.Size),tag=int(value.Tag),flags=int(value.Flags))
    def unload(self,base):return bool(self.unload_module(self.session,base))
    def cleanup(self):return bool(self.clean(self.session))
