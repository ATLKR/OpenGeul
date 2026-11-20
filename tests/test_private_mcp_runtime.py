"""Private MCP copies only the source-verified single-file CLI component."""
import hashlib
import importlib.util
import io
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ENTRY=ROOT/'e2e/mcp_worker.py'


class PrivateMcpRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.exe=self.root/'runtime/Tools/rhwp.exe'
        self.exe.parent.mkdir(parents=True);self.exe.write_bytes(b'unit-owned-cli')
        self.digest=hashlib.sha256(self.exe.read_bytes()).hexdigest();self.output=self.root/'private'
        spec=importlib.util.spec_from_file_location('private_mcp_runtime_tested',ENTRY)
        self.worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.worker)

    def copy(self,**options):
        return self.worker.private_runtime(self.exe,self.output,expected_sha256=options.get('digest',self.digest))

    def test_private_mcp_excludes_the_unrelated_gui_payload_above_96_mib(self):
        with (self.exe.parent.parent/'OpenGeul.exe').open('wb') as stream:stream.truncate(96*1024*1024+1)
        owned=self.copy()
        self.assertEqual(owned,self.output/'Tools/rhwp.exe')
        self.assertEqual(owned.read_bytes(),self.exe.read_bytes())
        self.assertEqual(sorted(p.relative_to(self.output).as_posix() for p in self.output.rglob('*')),['Tools','Tools/rhwp.exe'])

    def test_unrelated_editor_and_tools_resources_are_not_enumerated_or_copied(self):
        (self.exe.parent/'unrelated.dll').write_bytes(b'unit-foreign-runtime')
        with patch.object(Path,'rglob',side_effect=AssertionError('No GUI enumeration')):
            owned=self.copy()
        self.assertEqual(owned.read_bytes(),b'unit-owned-cli')
        self.assertFalse((owned.parent/'unrelated.dll').exists())

    def test_expected_cli_hash_is_required_and_wrong_copy_cannot_be_launched(self):
        for digest in ('0'*64,'G'*64,True,None,'a'*63):
            with self.subTest(valid=digest=='0'*64):
                with tempfile.TemporaryDirectory(dir=self.root) as location:
                    self.output=Path(location)/'private'
                    with self.assertRaises(ValueError):self.copy(digest=digest)

    def test_oversized_cli_still_fails_without_creating_destination(self):
        with self.exe.open('wb') as stream:stream.truncate(96*1024*1024+1)
        with self.assertRaises(ValueError):self.copy()
        self.assertFalse(self.output.exists())

    def test_empty_cli_still_fails_without_creating_destination(self):
        self.exe.write_bytes(b'')
        with self.assertRaises(ValueError):self.copy()
        self.assertFalse(self.output.exists())

    def test_existing_destination_is_not_overwritten(self):
        self.output.mkdir();marker=self.output/'unit-marker';marker.write_bytes(b'unchanged')
        with self.assertRaises(ValueError):self.copy()
        self.assertEqual(marker.read_bytes(),b'unchanged')
        self.assertEqual(len(tuple(self.output.iterdir())),1)

    def test_source_cli_symlink_is_rejected(self):
        original=Path.is_symlink
        if sys.platform=='win32':
            with patch.object(Path,'is_symlink',lambda p:p==self.exe or original(p)):
                with self.assertRaises(ValueError):self.copy()
        else:
            real=self.exe.parent/'unit-real.exe';self.exe.rename(real);self.exe.symlink_to(real)
            with self.assertRaises(ValueError):self.copy()
        self.assertFalse(self.output.exists())

    def test_windows_reparse_on_cli_parent_or_destination_parent_is_rejected(self):
        original=Path.lstat
        for marked in (self.exe,self.exe.parent,self.exe.parent.parent,self.output.parent):
            with self.subTest(role=marked==self.exe):
                def lstat(path,*args,**kwargs):
                    value=original(path,*args,**kwargs)
                    if path!=marked:return value
                    class Reparse:
                        st_file_attributes=0x400
                        def __getattr__(self,name):return getattr(value,name)
                    return Reparse()
                with patch.object(Path,'lstat',lstat):
                    with self.assertRaises(ValueError):self.copy()
                self.assertFalse(self.output.exists())

    def test_destination_symlink_is_not_followed(self):
        outside=self.root/'untouched';outside.mkdir()
        original=Path.is_symlink
        if sys.platform=='win32':
            with patch.object(Path,'is_symlink',lambda p:p==self.output or original(p)):
                with self.assertRaises(ValueError):self.copy()
        else:
            self.output.symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError):self.copy()
        self.assertEqual(tuple(outside.iterdir()),())

    def test_malformed_cli_location_cannot_supply_another_executable(self):
        for location in (self.root/'runtime/rhwp.exe',self.root/'runtime/Tools/other.exe'):
            location.write_bytes(b'unit-other')
            with self.assertRaises(ValueError):self.worker.private_runtime(location,self.output,expected_sha256=self.digest)
        self.assertFalse(self.output.exists())

    def test_changed_cli_bytes_during_copy_are_rejected_before_return(self):
        original=Path.open
        def open_file(path,*args,**kwargs):
            if path==self.exe and args and args[0]=='rb':return io.BytesIO(b'unit-changed-cli')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',open_file):
            with self.assertRaises(ValueError):self.copy()

    def test_copied_cli_is_same_path_shape_for_the_owned_com_worker(self):
        owned=self.copy()
        self.assertEqual(owned.parent.name,'Tools')
        self.assertEqual(owned.name,'rhwp.exe')
        self.assertEqual(hashlib.sha256(owned.read_bytes()).hexdigest(),self.digest)
        self.assertEqual(hashlib.sha256(self.exe.read_bytes()).hexdigest(),self.digest)

    def test_native_pe_architecture_guard_accepts_only_the_same_copied_machine(self):
        for architecture,machine,other in (('x64',0x8664,'arm64'),('arm64',0xAA64,'x64')):
            with self.subTest(architecture=architecture),tempfile.TemporaryDirectory(dir=self.root) as temporary:
                self.output=Path(temporary)/'private'
                raw=bytearray(256);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,128)
                raw[128:132]=b'PE\0\0';struct.pack_into('<H',raw,132,machine)
                self.exe.write_bytes(raw);self.digest=hashlib.sha256(raw).hexdigest()
                self.assertEqual(self.worker.verify_executable(self.exe,architecture),machine)
                owned=self.copy()
                self.assertEqual(self.worker.verify_executable(owned,architecture),machine)
                with self.assertRaises(ValueError):self.worker.verify_executable(owned,other)
