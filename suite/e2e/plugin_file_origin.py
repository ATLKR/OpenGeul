"""Prelaunch lease of one verified plugin; never proof of live code integrity."""
import ctypes as C
import hashlib
import importlib.util
import os
from pathlib import Path


class PluginOriginError(ValueError):pass

def require(ok,code):
    if not ok:raise PluginOriginError(code)


class PluginFileLease:
    def __init__(self,path,proof,budget,*,runtime=None):
        self.handle=None;self.runtime=runtime;self.path=Path(path)
        self.receipt=dict(schemaVersion=1,kind='held-plugin-file-origin',verified=False,
            released=False,fileOriginBindingOnly=True,liveMemoryIntegrityProved=False)
        budget.now()
        require(budget.deadline==budget.started+30 and budget.work_deadline==budget.deadline-3,'original-preparation-budget')
        require(self.path.is_absolute() and self.path.name=='vclplug_winlo.dll' and
                not str(self.path).startswith(('\\\\','//')),'fixed-local-plugin-path')
        require(type(proof) is dict and proof.get('kind')=='matched-plugin-symbols' and
                proof.get('identityMatched') is True and proof.get('acceptance') is False,'verified-pair-required')
        budget.now()
        if self.runtime is None:self.runtime=FileApi(budget)
        self.runtime.preflight(str(self.path));budget.now()
        source=Path(__file__).resolve().parents[1]/'scripts/retain-plugin-symbols.py'
        spec=importlib.util.spec_from_file_location('plugin_origin_retention',source)
        retention=importlib.util.module_from_spec(spec);spec.loader.exec_module(retention)
        budget.now();retention.unlinked(self.path,budget=budget);budget.now()
        try:
            self.handle=self.runtime.open(str(self.path))
            require(type(self.handle) is int and self.handle>0,'plugin-open');budget.now()
            before=self.runtime.identity(self.handle);budget.now()
            require(type(before) is dict and set(before)=={'volume','fileId','size'} and
                    type(before['volume']) is int and 0<=before['volume']<2**64 and
                    type(before['fileId']) is bytes and len(before['fileId'])==16 and any(before['fileId']) and
                    type(before['size']) is int and 0<before['size']<=retention.MAX_DLL,'plugin-file-identity')
            data=self.runtime.read(self.handle,retention.MAX_DLL,budget);budget.now()
            after=self.runtime.identity(self.handle);budget.now()
            require(before==after and type(data) is bytes and len(data)==before['size'],'plugin-file-changed')
            pin=dict(name='vclplug_winlo.dll',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            require(proof.get('files',{}).get('dll')==pin,'plugin-bytes-mismatch');budget.now()
            identity=retention.pe_identity(data);budget.now()
            require(identity==proof.get('matchedIdentity'),'plugin-rsds-mismatch')
            canonical=self.runtime.final_path(self.handle);budget.now()
            require(canonical==str(self.path),'plugin-final-path-mismatch')
            retention.unlinked(self.path,budget=budget);budget.now()
            self.original=before
            self.receipt.update(verified=True,dllSha256=pin['sha256'],bytes=pin['bytes'],matchedIdentity=identity)
            budget.now()
        except BaseException as primary:
            if self.handle:
                try:self.close()
                except BaseException as cleanup:self.receipt['cleanupErrorType']=type(cleanup).__name__
            primary.pluginOriginReceipt=dict(self.receipt)
            raise

    def binding(self):
        require(self.handle is not None and self.receipt['verified'] and not self.receipt['released'],'plugin-lease-unavailable')
        return dict(path=str(self.path),architecture='arm64',**self.original)

    def close(self):
        if self.handle is None:return
        require(self.runtime.close(self.handle) is True,'plugin-handle-release')
        self.handle=None;self.receipt['released']=True


class FileIdInfo(C.Structure):
    _fields_=[('VolumeSerialNumber',C.c_uint64),('FileId',C.c_ubyte*16)]


class FileApi:
    def __init__(self,budget):
        self.budget=budget
        require(os.name=='nt','native-windows-required');budget.now()
        from native_suite_architecture import observe_native_architecture,validate_native_architecture
        validate_native_architecture(observe_native_architecture(),'arm64');budget.now()
        k=C.WinDLL('kernel32.dll',use_last_error=True,winmode=0x800);self.kernel=k
        U=C.c_uint32;P=C.c_void_p;B=C.c_int32
        def bind(name,args,result):
            f=getattr(k,name);f.argtypes=args;f.restype=result;return f
        self.drive=bind('GetDriveTypeW',[C.c_wchar_p],U)
        self.open_file=bind('CreateFileW',[C.c_wchar_p,U,U,P,U,U,P],P)
        self.close_file=bind('CloseHandle',[P],B)
        self.final_name=bind('GetFinalPathNameByHandleW',[P,C.c_wchar_p,U,U],U)
        self.file_info=bind('GetFileInformationByHandleEx',[P,C.c_int32,P,U],B)
        self.file_size=bind('GetFileSizeEx',[P,C.POINTER(C.c_int64)],B)
        self.read_file=bind('ReadFile',[P,P,U,C.POINTER(U),P],B)
        budget.now()

    def preflight(self,path):require(self.drive(str(Path(path).anchor))==3,'plugin-fixed-drive')
    def open(self,path):
        handle=self.open_file(path,0x80000000,1,None,3,0x80,None)
        require(handle not in (None,0,C.c_void_p(-1).value),'plugin-open')
        return int(handle)
    def final_path(self,handle):
        self.budget.now();buffer=C.create_unicode_buffer(1024)
        count=int(self.final_name(handle,buffer,len(buffer),0));self.budget.now()
        require(0<count<len(buffer),'plugin-final-path-length')
        value=buffer.value
        require(value.startswith('\\\\?\\') and len(value)>6 and value[5:7]==':\\','plugin-final-path-local')
        return value[4:]
    def identity(self,handle):
        info=FileIdInfo();size=C.c_int64()
        self.budget.now()
        require(self.file_info(handle,18,C.byref(info),C.sizeof(info)),'plugin-file-information')
        self.budget.now()
        require(self.file_size(handle,C.byref(size)),'plugin-file-size')
        self.budget.now()
        return dict(volume=int(info.VolumeSerialNumber),fileId=bytes(info.FileId),size=int(size.value))
    def read(self,handle,limit,budget):
        chunks=[];total=0;buffer=C.create_string_buffer(262144);count=C.c_uint32()
        while True:
            budget.now();count.value=0
            require(self.read_file(handle,buffer,len(buffer),C.byref(count),None),'plugin-file-read')
            budget.now();require(count.value<=len(buffer),'plugin-read-count')
            if not count.value:break
            total+=count.value;require(total<=limit,'plugin-read-bound')
            chunks.append(buffer.raw[:count.value])
        return b''.join(chunks)
    def close(self,handle):return bool(self.close_file(handle))
