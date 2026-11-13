"""Compiler-only named Windows metadata; no ambient environment or Win32 calls."""
import importlib
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_writer_observer_phase import module,BASE


class AtomicEnvironment(unittest.TestCase):
    def setUp(self):
        isolated=patch.object(os,'environ',{'WRITER_ENV_TEST_ONLY':'1'})
        isolated.start();self.addCleanup(isolated.stop)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        source=str(BASE/'suite/e2e');sys.path.insert(0,source);self.addCleanup(sys.path.remove,source)
        self.msaa=importlib.import_module('writer_server_observer_msaa')
        self.m=module()
        windows=self.root/'Windows';user=self.root/'User'
        self.values={'SystemRoot':str(windows),'WINDIR':str(windows),'USERPROFILE':str(user),
            'APPDATA':str(user/'AppData/Roaming'),'LOCALAPPDATA':str(user/'AppData/Local'),
            'ProgramData':str(self.root/'ProgramData')}
        for path in self.values.values():Path(path).mkdir(parents=True,exist_ok=True)
        tempdir=self.root/'temp';office=self.root/'office/program'
        for path in (tempdir,office,windows/'System32'):path.mkdir(parents=True)
        self.runtime=self.msaa.HostRuntime(self.root/'python/python.exe',self.root/'phase.py',windows,tempdir,office)
        self.descriptor=self.msaa.Descriptor(31,41,71)
        self.reads=[]

    def read(self,key):
        self.reads.append(key)
        if key not in self.values:raise AssertionError('Unexpected bootstrap key')
        return self.values[key]

    def build(self):return self.m.build_atomic_environment(self.read,self.runtime,self.descriptor)

    def test_only_programdata_is_added_to_the_existing_fresh_host_environment(self):
        expected=self.msaa.build_host_environment(lambda key:self.values[key],self.runtime,self.descriptor)
        actual=self.build()
        self.assertEqual(self.reads,['SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA','ProgramData'])
        self.assertEqual(set(actual),set(expected)|{'ProgramData'})
        self.assertEqual(actual['ProgramData'],str(Path(self.values['ProgramData']).resolve()))
        self.assertEqual({key:actual[key]for key in expected},expected)

    def test_msaa_observer_environment_still_reads_only_its_original_five_keys(self):
        value=self.msaa.build_host_environment(self.read,self.runtime,self.descriptor)
        self.assertEqual(self.reads,['SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA'])
        self.assertNotIn('ProgramData',value)

    def test_no_direct_ambient_mapping_read_copy_or_iteration_occurs(self):
        accesses=[]
        class Unreadable:
            def reject(self,*args,**kwargs):accesses.append(1);raise AssertionError()
            __getitem__=get=__iter__=keys=items=values=copy=__len__=reject
        with patch.object(os,'environ',Unreadable()):value=self.build()
        self.assertIn('ProgramData',value);self.assertEqual(accesses,[])

    def test_missing_non_string_relative_and_oversized_values_are_rejected(self):
        for value in (None,True,{},'', 'relative','/'+'x'*32768):
            self.values['ProgramData']=value
            with self.subTest(case_type=type(value).__name__),self.assertRaises(ValueError):self.build()

    def test_file_missing_directory_and_parent_traversal_are_rejected(self):
        file=self.root/'file';file.write_bytes(b'fixture')
        for path in (file,self.root/'absent',self.root/'ProgramData/..'/'ProgramData'):
            self.values['ProgramData']=str(path)
            with self.subTest(case=int(path==file)),self.assertRaises(ValueError):self.build()

    def test_existing_command_expansion_paths_are_rejected(self):
        path=self.root/'Program%Data';path.mkdir();self.values['ProgramData']=str(path)
        with self.assertRaises(ValueError):self.build()

    def test_link_or_reparse_directory_is_rejected_without_resolving_it(self):
        original=Path.lstat;target=Path(self.values['ProgramData'])
        for linked,reparse in ((True,False),(False,True)):
            def lstat(path,*args,**kwargs):
                value=original(path,*args,**kwargs)
                return SimpleNamespace(st_mode=stat.S_IFLNK if linked else value.st_mode,
                    st_file_attributes=1024 if reparse else 0) if path==target else value
            with self.subTest(link=linked),patch.object(Path,'lstat',lstat),self.assertRaises(ValueError):self.build()

    def test_main_chooses_compiler_bootstrap_only_for_atomic(self):
        chosen=[]
        def run(**kwargs):chosen.append(kwargs['environment_builder']);return self.m._receipt()
        for kind in ('atomic','observe'):
            arguments=['--host-python',str(self.runtime.host_python),'--windows',str(self.runtime.windows),
                '--temp',str(self.runtime.temp),'--office-program',str(self.runtime.office_program),
                '--seconds','45','--receipt',str(self.root/(kind+'.json')),'--',kind]
            with patch.dict(sys.modules,{'writer_server_observer_win32':SimpleNamespace(NativeApi=lambda:object())}),\
                    patch.object(self.msaa.HostRuntime,'validated',classmethod(lambda cls,*args:self.runtime)),\
                    patch.object(self.m,'run_phase',run):
                self.assertEqual(self.m.main(arguments),1)
        self.assertEqual(chosen,[self.m.build_atomic_environment,self.msaa.build_host_environment])

    def test_actual_native_environment_encoder_admits_only_the_added_known_key(self):
        native=importlib.import_module('writer_server_observer_win32')
        environment=self.build()
        block=native._environment_block(environment)
        text=bytes(block).decode('utf-16-le')
        self.assertIn('ProgramData='+self.values['ProgramData']+'\0',text)
        self.assertTrue(text.endswith('\0\0'))
        for extra in ({'UNREVIEWED_KEY':'synthetic'},{'programdata':self.values['ProgramData']}):
            with self.subTest(duplicate='programdata' in extra),self.assertRaises(native.NativeCallError):
                native._environment_block(dict(environment,**extra))


if __name__=='__main__':unittest.main()
