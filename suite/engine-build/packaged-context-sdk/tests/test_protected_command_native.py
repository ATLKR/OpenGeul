"""Direct fake-DLL ABI checks; never invokes a Windows API on this host."""
import ctypes as C
import importlib.util
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sys
ORIGIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ORIGIN/'tests'));sys.path.insert(0,str(ORIGIN))
SOURCE=ORIGIN/'toolchain.py'

class Clock:
    def __init__(self):self.value=0.
    def __call__(self):return self.value


class FixedFailure(Exception):
    def __init__(self,code):self.code=code;super().__init__('fixed gate failure')


def put_wide(buffer,text):
    data=text.encode('utf-16-le')+b'\0\0'
    C.memmove(buffer,data,len(data))
    return len(data)//2-1


def get_wide(buffer):
    units=[]
    for value in buffer:
        if not value:break
        units.append(value)
    return b''.join(n.to_bytes(2,'little') for n in units).decode('utf-16-le')


class Function:
    def __init__(self,name,callback,trace):self.name=name;self.callback=callback;self.trace=trace
    def __call__(self,*args):self.trace.append((self.name,args));return self.callback(*args)


class Dlls:
    def __init__(self):
        self.trace=[];self.loads=[];self.handle=0x12345678abcdef
        self.system='C:\\Windows\\System32';self.windows='C:\\Windows'
        self.final='\\\\?\\C:\\Windows\\System32\\cmd.exe'
        self.data=b'synthetic-command-bytes';self.position=0;self.maximum_read=65536
        self.links=2;self.directory=False;self.delete_pending=False;self.attributes=0
        self.basic_attributes=0;self.tag=0;self.file_type=1;self.handle_flags=0
        self.protected=1;self.close_result=1;self.info_fail=None;self.read_fail=False
        self.access_time=100
        callbacks={
            'GetSystemDirectoryW':lambda b,n:put_wide(b,self.system),
            'GetWindowsDirectoryW':lambda b,n:put_wide(b,self.windows),
            'SfcIsFileProtected':lambda reserved,p:self.protected,
            'CreateFileW':lambda *args:self.handle,
            'GetFileInformationByHandleEx':self.information,
            'GetFinalPathNameByHandleW':lambda h,b,n,f:put_wide(b,self.final),
            'GetFileType':lambda h:self.file_type,
            'GetHandleInformation':self.handle_information,
            'SetFilePointerEx':self.seek,
            'ReadFile':self.read,
            'CloseHandle':lambda h:self.close_result,
        }
        self.functions={name:Function(name,callback,self.trace) for name,callback in callbacks.items()}
    def load(self,name,**kwargs):
        self.loads.append((name,kwargs))
        names=['SfcIsFileProtected'] if name=='sfc.dll' else [n for n in self.functions if n!='SfcIsFileProtected']
        return SimpleNamespace(**{n:self.functions[n] for n in names})
    def information(self,h,kind,output,size):
        if kind==self.info_fail:return 0
        row=output._obj
        if kind==18:
            row.VolumeSerialNumber=0x123456789abcdef
            row.FileId.Identifier[:]=bytes(range(16))
        elif kind==1:
            row.AllocationSize=4096;row.EndOfFile=len(self.data);row.NumberOfLinks=self.links
            row.DeletePending=self.delete_pending;row.Directory=self.directory
        elif kind==9:row.FileAttributes=self.attributes;row.ReparseTag=self.tag
        elif kind==0:
            row.LastWriteTime=1234567890123;row.ChangeTime=1234567890456
            row.LastAccessTime=self.access_time
            row.FileAttributes=self.basic_attributes
        else:raise AssertionError('Unexpected information class')
        return 1
    def handle_information(self,h,output):output._obj.value=self.handle_flags;return 1
    def seek(self,h,distance,position,method):self.position=distance;position._obj.value=distance;return 1
    def read(self,h,buffer,count,received,overlapped):
        if self.read_fail:return 0
        self.access_time+=1
        data=self.data[self.position:self.position+min(count,self.maximum_read)]
        C.memmove(buffer,data,len(data));received._obj.value=len(data);self.position+=len(data)
        return 1


class ProtectedCommandNativeTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SOURCE.is_file(),'Native adapter fragment is missing')
        spec=importlib.util.spec_from_file_location('command_native_under_test',SOURCE)
        module=importlib.util.module_from_spec(spec);module.GateFailure=FixedFailure
        module.canonical=lambda path,**kwargs:path
        spec.loader.exec_module(module)
        module.GateFailure=FixedFailure
        module.canonical=lambda path,**kwargs:path
        return module
    def build(self):
        module=self.module();dlls=Dlls()
        module.os=SimpleNamespace(name='nt');module.sys=SimpleNamespace(platform='win32')
        clock=Clock()
        with patch.object(C,'WinDLL',dlls.load,create=True):api=module._Win32CommandApi(180.,clock=clock)
        api.test_clock=clock
        return module,dlls,api
    def failure(self,callback):
        with self.assertRaises(FixedFailure) as caught:callback()
        self.assertEqual(caught.exception.code,14)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_non_windows_refuses_before_loading_any_dll(self):
        module=self.module();module.os=SimpleNamespace(name='posix');module.sys=SimpleNamespace(platform='linux')
        dlls=Dlls()
        with patch.object(C,'WinDLL',dlls.load,create=True):self.failure(lambda:module._Win32CommandApi(180.,clock=Clock()))
        self.assertEqual(dlls.loads,[])

    def test_secure_load_and_all_abi_types_are_exact(self):
        m,d,a=self.build()
        self.assertEqual(d.loads,[('kernel32.dll',{'use_last_error':True,'winmode':0x800}),('sfc.dll',{'use_last_error':True,'winmode':0x800})])
        u16=C.POINTER(C.c_uint16);u32=C.c_uint32;handle=C.c_void_p;i32=C.c_int32
        signatures={
            'GetSystemDirectoryW':([u16,u32],u32),'GetWindowsDirectoryW':([u16,u32],u32),
            'SfcIsFileProtected':([handle,u16],i32),
            'CreateFileW':([u16,u32,u32,handle,u32,u32,handle],handle),
            'GetFileInformationByHandleEx':([handle,i32,handle,u32],i32),
            'GetFinalPathNameByHandleW':([handle,u16,u32,u32],u32),
            'GetFileType':([handle],u32),'GetHandleInformation':([handle,C.POINTER(u32)],i32),
            'SetFilePointerEx':([handle,C.c_int64,C.POINTER(C.c_int64),u32],i32),
            'ReadFile':([handle,handle,u32,C.POINTER(u32),handle],i32),
            'CloseHandle':([handle],i32),
        }
        for name,(args,result) in signatures.items():
            with self.subTest(api=name):
                self.assertEqual(d.functions[name].argtypes,args);self.assertIs(d.functions[name].restype,result)
        self.assertEqual([C.sizeof(k) for k in (m._CommandFileIdInfo,m._CommandStandardInfo,m._CommandAttributeTagInfo,m._CommandBasicInfo)],[24,24,8,40])
        self.assertEqual(m._CommandStandardInfo.NumberOfLinks.offset,16)
        self.assertEqual(m._CommandBasicInfo.FileAttributes.offset,32)

    def test_directory_api_uses_fixed_utf16_units_including_surrogate_pairs(self):
        m,d,a=self.build();d.system='C:\\Synthetic-\U00010000\\System32'
        self.assertEqual(a.system_directory(),d.system);self.assertEqual(a.windows_directory(),d.windows)

    def test_combined_lease_uses_real_typed_adapter_with_synthetic_dll_calls(self):
        from test_protected_command_lease import Clock,pe_bytes
        m,d,a=self.build();clock=Clock();d.system=r'C:\Windows\System32';d.windows=r'C:\Windows'
        d.final=r'\\?\C:\Windows\System32\cmd.exe';d.data=pe_bytes();opened=[]
        def opened_file(*args):
            opened.append(100+len(opened));return opened[-1]
        d.functions['CreateFileW'].callback=opened_file
        with patch.object(a,'no_reparse',lambda path:True):
            lease=m._CommandLease('x64',180.0,a,clock=clock)
            self.assertEqual(lease.record['machine'],0x8664);self.assertEqual(lease.observation()['linkCount'],2)
            self.assertTrue(lease.close())
        closed=[args[0] for name,args in d.trace if name=='CloseHandle']
        self.assertEqual(sorted(closed),sorted(opened));self.assertEqual(len(closed),len(set(closed)))

    def test_self_read_access_time_updates_do_not_change_the_identity_stamp(self):
        from test_protected_command_lease import Clock,pe_bytes
        m,d,a=self.build();d.system=r'C:\Windows\System32';d.windows=r'C:\Windows'
        d.final=r'\\?\C:\Windows\System32\cmd.exe';d.data=pe_bytes();clock=Clock();handles=[]
        def opened_file(*args):
            handles.append(100+len(handles));return handles[-1]
        d.functions['CreateFileW'].callback=opened_file
        with patch.object(a,'no_reparse',lambda path:True):
            lease=m._CommandLease('x64',180.0,a,clock=clock);before=d.access_time
            self.assertEqual(lease.verify(),lease.record)
            self.assertGreater(d.access_time,before);self.assertTrue(lease.close())

    def test_native_adapter_preserves_cancellation_for_the_lease_cleanup_path(self):
        m,d,a=self.build()
        def cancelled(*args):raise KeyboardInterrupt()
        d.functions['ReadFile'].callback=cancelled
        with self.assertRaises(KeyboardInterrupt):a.read(d.handle,len(d.data))

    def test_directory_lengths_and_encoding_fail_closed(self):
        m,d,a=self.build()
        for value in (0,32768,32769):
            d.functions['GetSystemDirectoryW'].callback=lambda b,n,value=value:value
            self.failure(a.system_directory)
        def malformed(b,n):b[0]=0xd800;b[1]=0;return 1
        d.functions['GetWindowsDirectoryW'].callback=malformed;self.failure(a.windows_directory)

    def test_no_reparse_private_checks_each_parent_and_keeps_hardlinks(self):
        m,d,a=self.build();seen=[]
        class Node:
            def __init__(self,name,mode,attributes=0):self.name=name;self.mode=mode;self.attributes=attributes
            def lstat(self):
                seen.append(self.name)
                return SimpleNamespace(st_mode=self.mode,st_file_attributes=self.attributes,st_nlink=2)
        parent=Node('parent',stat.S_IFDIR);root=Node('root',stat.S_IFDIR)
        leaf=Node('leaf',stat.S_IFREG);leaf.parents=(parent,root);leaf.parts=('root','parent','leaf');leaf.is_absolute=lambda:True
        with patch.object(m,'Path',lambda value:leaf):self.assertTrue(a.no_reparse('synthetic'))
        self.assertEqual(seen,['parent','root','leaf'])
        for target,mode,attributes in ((leaf,stat.S_IFLNK,0),(leaf,stat.S_IFREG,0x400),(parent,stat.S_IFDIR,0x400)):
            old=(target.mode,target.attributes);target.mode,target.attributes=mode,attributes
            with patch.object(m,'Path',lambda value:leaf):self.assertFalse(a.no_reparse('synthetic'))
            target.mode,target.attributes=old

    def test_wrp_is_only_a_boolean_classification(self):
        m,d,a=self.build();self.assertTrue(a.is_protected('C:\\Synthetic\\cmd.exe'))
        reserved,path=d.trace[-1][1];self.assertIsNone(reserved);self.assertEqual(get_wide(path),'C:\\Synthetic\\cmd.exe')
        d.protected=0;self.assertFalse(a.is_protected('C:\\Synthetic\\cmd.exe'))

    def test_open_uses_read_only_noninheritable_existing_reparse_safe_flags_and_no_followup(self):
        m,d,a=self.build();d.trace.clear();self.assertEqual(a.open('C:\\Synthetic\\cmd.exe'),d.handle)
        self.assertEqual([name for name,args in d.trace],['CreateFileW'])
        path,access,share,security,disposition,flags,template=d.trace[0][1]
        self.assertEqual(get_wide(path),'C:\\Synthetic\\cmd.exe')
        self.assertEqual((access,share,security,disposition,flags,template),(0x80000000,1,None,3,0x00200000,None))

    def test_open_failure_never_retries_or_queries_unretained_handle(self):
        m,d,a=self.build()
        for h in (None,0,-1,(1<<(C.sizeof(C.c_void_p)*8))-1):
            d.handle=h;d.trace.clear();self.failure(lambda:a.open('C:\\Synthetic\\cmd.exe'))
            self.assertEqual([name for name,args in d.trace],['CreateFileW'])

    def test_snapshot_returns_only_eight_typed_handle_bound_observations(self):
        m,d,a=self.build();row=a.snapshot(d.handle)
        self.assertEqual(row,{'identity':(0x123456789abcdef,bytes(range(16))),
            'finalPath':d.final,'size':len(d.data),'modified':(1234567890123,1234567890456),
            'links':2,'regular':True,'reparse':False,'inheritable':False})
        infos=[args for name,args in d.trace if name=='GetFileInformationByHandleEx']
        self.assertEqual([r[1] for r in infos],[18,1,9,0]);self.assertEqual([r[3] for r in infos],[24,24,8,40])
        self.assertTrue(all(r[0]==d.handle for r in infos))

    def test_snapshot_reports_inheritance_reparse_directory_and_delete_pending_without_policy_alias(self):
        for field,value,key,expected in [('handle_flags',1,'inheritable',True),('tag',0xa000000c,'reparse',True),
              ('basic_attributes',0x400,'reparse',True),('directory',True,'regular',False),
              ('delete_pending',True,'regular',False),('file_type',3,'regular',False)]:
            m,d,a=self.build();setattr(d,field,value)
            with self.subTest(field=field):self.assertIs(a.snapshot(d.handle)[key],expected)

    def test_snapshot_api_failure_and_bounded_path_failure_are_fixed_gate14(self):
        m,d,a=self.build();d.info_fail=18;self.failure(lambda:a.snapshot(d.handle))
        d.info_fail=None;d.functions['GetFinalPathNameByHandleW'].callback=lambda *args:32768
        self.failure(lambda:a.snapshot(d.handle))

    def test_read_resets_pointer_accepts_partial_reads_and_checks_exact_eof(self):
        m,d,a=self.build();d.position=9;d.maximum_read=3
        self.assertEqual(a.read(d.handle,len(d.data)),d.data)
        self.assertEqual(d.trace[0][0],'SetFilePointerEx')
        reads=[args for name,args in d.trace if name=='ReadFile']
        self.assertTrue(all(0<r[2]<=65536 and r[4] is None for r in reads))
        self.assertEqual(reads[-1][2],1)

    def test_read_size_short_trailing_and_native_failures_never_return_partial_bytes(self):
        m,d,a=self.build()
        for size in (True,0,-1,128*1024*1024+1):
            d.trace.clear();self.failure(lambda:a.read(d.handle,size));self.assertEqual(d.trace,[])
        for expected in (len(d.data)-1,len(d.data)+1):self.failure(lambda:a.read(d.handle,expected))
        d.read_fail=True;self.failure(lambda:a.read(d.handle,len(d.data)))

    def test_close_reports_boolean_and_native_exceptions_are_sanitized(self):
        m,d,a=self.build();self.assertTrue(a.close(d.handle));d.close_result=0;self.assertFalse(a.close(d.handle))
        def fail(*args):raise OSError('synthetic unavailable API')
        d.functions['CloseHandle'].callback=fail;self.failure(lambda:a.close(d.handle))
        d.functions['SfcIsFileProtected'].callback=fail;self.failure(lambda:a.is_protected('C:\\Synthetic\\cmd.exe'))

    def deadline_failure(self,callback):
        with self.assertRaises(FixedFailure) as caught:callback()
        self.assertEqual(caught.exception.code,10)

    def late(self,dlls,api,name):
        original=dlls.functions[name].callback
        def callback(*args):
            result=original(*args);api.test_clock.value=180.;return result
        dlls.functions[name].callback=callback

    def test_active_deadline_is_pure_finite_and_never_exceeds_original_window(self):
        m,d,a=self.build();d.trace.clear();a.set_deadline(30.)
        self.assertEqual(d.trace,[])
        for end in (True,None,float('nan'),float('inf'),181.,1.):
            with self.subTest(kind=type(end).__name__):self.deadline_failure(lambda:a.set_deadline(end))
        # A later phase may reuse only the still-existing original window.
        a.set_deadline(180.);a.test_clock.value=179.;self.deadline_failure(lambda:a.set_deadline(180.))
        self.assertEqual(d.trace,[])

    def test_expired_constructor_does_not_load_any_dll(self):
        m=self.module();m.os=SimpleNamespace(name='nt');m.sys=SimpleNamespace(platform='win32');d=Dlls();clock=Clock();clock.value=179.
        with patch.object(C,'WinDLL',d.load,create=True):self.deadline_failure(lambda:m._Win32CommandApi(180.,clock=clock))
        self.assertEqual(d.loads,[])

    def test_first_late_dll_load_stops_before_second_load(self):
        m=self.module();m.os=SimpleNamespace(name='nt');m.sys=SimpleNamespace(platform='win32');d=Dlls();clock=Clock()
        def late_load(*args,**kwargs):result=d.load(*args,**kwargs);clock.value=180.;return result
        with patch.object(C,'WinDLL',late_load,create=True):self.deadline_failure(lambda:m._Win32CommandApi(180.,clock=clock))
        self.assertEqual(len(d.loads),1)

    def test_late_binding_stops_before_another_function_is_bound(self):
        m=self.module();m.os=SimpleNamespace(name='nt');m.sys=SimpleNamespace(platform='win32');d=Dlls();clock=Clock();bound=[]
        class Kernel:
            def __getattr__(self,name):bound.append(name);clock.value=180.;return d.functions[name]
        def load(name,**kwargs):
            result=d.load(name,**kwargs)
            return Kernel() if name=='kernel32.dll' else result
        with patch.object(C,'WinDLL',load,create=True):self.deadline_failure(lambda:m._Win32CommandApi(180.,clock=clock))
        self.assertEqual(bound,['GetSystemDirectoryW']);self.assertEqual(d.trace,[])

    def test_first_late_information_call_stops_all_remaining_snapshot_calls(self):
        m,d,a=self.build();self.late(d,a,'GetFileInformationByHandleEx')
        self.deadline_failure(lambda:a.snapshot(d.handle))
        self.assertEqual([name for name,args in d.trace],['GetFileInformationByHandleEx'])

    def test_late_final_path_or_type_never_reaches_next_snapshot_api(self):
        for name,next_name in [('GetFinalPathNameByHandleW','GetFileType'),('GetFileType','GetHandleInformation'),('GetHandleInformation',None)]:
            m,d,a=self.build();self.late(d,a,name)
            with self.subTest(api=name):self.deadline_failure(lambda:a.snapshot(d.handle))
            calls=[n for n,args in d.trace];self.assertEqual(calls[-1],name)
            if next_name:self.assertNotIn(next_name,calls)

    def test_late_seek_stops_before_any_read(self):
        m,d,a=self.build();self.late(d,a,'SetFilePointerEx')
        self.deadline_failure(lambda:a.read(d.handle,len(d.data)))
        self.assertEqual([name for name,args in d.trace],['SetFilePointerEx'])

    def test_first_late_read_stops_second_iteration_and_eof_read(self):
        for partial in (True,False):
            m,d,a=self.build();d.maximum_read=3 if partial else 65536;self.late(d,a,'ReadFile')
            with self.subTest(partial=partial):self.deadline_failure(lambda:a.read(d.handle,len(d.data)))
            self.assertEqual([name for name,args in d.trace],['SetFilePointerEx','ReadFile'])

    def test_late_directory_or_sfc_never_returns_authority(self):
        for name,method in [('GetSystemDirectoryW','system_directory'),('GetWindowsDirectoryW','windows_directory'),('SfcIsFileProtected','is_protected')]:
            m,d,a=self.build();self.late(d,a,name)
            with self.subTest(api=name):
                if method=='is_protected':self.deadline_failure(lambda:getattr(a,method)('C:\\Synthetic\\cmd.exe'))
                else:self.deadline_failure(getattr(a,method))
            self.assertEqual([n for n,args in d.trace],[name])

    def test_each_lstat_is_bounded_and_cancellation_is_not_reclassified(self):
        for late_index in range(3):
            m,d,a=self.build();seen=[]
            class Node:
                def __init__(self,index,mode):self.index=index;self.mode=mode
                def lstat(self):
                    seen.append(self.index)
                    if self.index==late_index:a.test_clock.value=180.
                    return SimpleNamespace(st_mode=self.mode,st_file_attributes=0,st_nlink=2)
            parent,root=Node(0,stat.S_IFDIR),Node(1,stat.S_IFDIR);leaf=Node(2,stat.S_IFREG)
            leaf.parents=(parent,root);leaf.parts=('root','parent','leaf');leaf.is_absolute=lambda:True
            with patch.object(m,'Path',lambda value:leaf),self.subTest(index=late_index):self.deadline_failure(lambda:a.no_reparse('synthetic'))
            self.assertEqual(seen,list(range(late_index+1)))
        m,d,a=self.build()
        def cancelled():raise KeyboardInterrupt()
        leaf=SimpleNamespace(parents=(),parts=('root','leaf'),is_absolute=lambda:True,lstat=cancelled)
        with patch.object(m,'Path',lambda value:leaf),self.assertRaises(KeyboardInterrupt):a.no_reparse('synthetic')

    def test_open_returns_late_handle_to_caller_and_close_ignores_expired_deadline(self):
        m,d,a=self.build();self.late(d,a,'CreateFileW')
        retained=a.open('C:\\Synthetic\\cmd.exe')
        self.assertEqual(retained,d.handle)
        self.assertEqual([name for name,args in d.trace],['CreateFileW'])
        self.deadline_failure(lambda:a.snapshot(retained))
        self.assertTrue(a.close(retained))
        self.assertEqual([name for name,args in d.trace],['CreateFileW','CloseHandle'])
        d.trace.clear();self.deadline_failure(lambda:a.open('C:\\Synthetic\\cmd.exe'));self.assertEqual(d.trace,[])

    def test_system_exit_and_keyboard_interrupt_propagate_from_native_calls(self):
        for kind in (KeyboardInterrupt,SystemExit):
            for name,method in [('GetSystemDirectoryW','system_directory'),('SfcIsFileProtected','is_protected'),('ReadFile','read')]:
                m,d,a=self.build()
                def cancelled(*args,kind=kind):raise kind()
                d.functions[name].callback=cancelled
                with self.subTest(kind=kind.__name__,api=name),self.assertRaises(kind):
                    if method=='is_protected':a.is_protected('C:\\Synthetic\\cmd.exe')
                    elif method=='read':a.read(d.handle,len(d.data))
                    else:a.system_directory()


if __name__=='__main__':unittest.main()
