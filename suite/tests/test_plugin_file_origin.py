"""Real byte/identity policy, with only Win32 file operations replaced on Linux."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
from test_plugin_symbols import dll,GUID
from test_plugin_symbol_resolution import Budget

SCRIPT=Path(__file__).resolve().parents[1]/'e2e/plugin_file_origin.py'

class Files:
    def __init__(self,data,budget):
        self.data=data;self.budget=budget;self.closed=[];self.opened=[];self.identities=0
        self.changed=False;self.late=False;self.close_ok=True
    def preflight(self,path):pass
    def open(self,path):self.opened.append(path);return 123
    def final_path(self,handle):return self.opened[-1]
    def identity(self,handle):
        assert handle==123
        self.identities+=1
        return dict(volume=7,fileId=bytes(range(16)),size=1536+(self.changed and self.identities>1))
    def read(self,handle,limit,budget):
        assert handle==123 and limit==32*1024*1024 and budget is self.budget
        if self.late:self.budget.time=27.
        return self.data
    def close(self,handle):self.closed.append(handle);return self.close_ok

class PluginFileOriginTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'prelaunch plugin lease is missing')
        s=importlib.util.spec_from_file_location('plugin_origin_test',SCRIPT)
        self.m=importlib.util.module_from_spec(s);s.loader.exec_module(self.m)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name).resolve()/'Office/program/vclplug_winlo.dll'
        self.path.parent.mkdir(parents=True);self.path.write_bytes(dll())
        self.budget=Budget();self.api=Files(dll(),self.budget)
        self.proof=dict(kind='matched-plugin-symbols',identityMatched=True,acceptance=False,
            matchedIdentity=dict(guid=str(GUID),age=2),files=dict(dll=dict(
                name='vclplug_winlo.dll',bytes=1536,sha256=hashlib.sha256(dll()).hexdigest())))
    def acquire(self):return self.m.PluginFileLease(self.path,self.proof,self.budget,runtime=self.api)
    def test_verified_file_stays_held_until_explicit_cleanup_without_public_path(self):
        lease=self.acquire()
        self.assertEqual(lease.binding()['fileId'],bytes(range(16)))
        self.assertEqual(lease.binding()['volume'],7)
        self.assertTrue(lease.receipt['verified']);self.assertFalse(lease.receipt['released'])
        self.assertNotIn(str(self.path),json.dumps(lease.receipt));self.assertEqual(self.api.closed,[])
        lease.close();self.assertTrue(lease.receipt['released']);self.assertEqual(self.api.closed,[123])
        with self.assertRaises(self.m.PluginOriginError):lease.binding()
    def test_wrong_bytes_release_handle_and_never_return_binding(self):
        self.api.data=dll()+b'x'
        with self.assertRaises(self.m.PluginOriginError):self.acquire()
        self.assertEqual(self.api.closed,[123])
    def test_wrong_rsds_identity_release_handle(self):
        self.proof['matchedIdentity']['age']=3
        with self.assertRaises(self.m.PluginOriginError):self.acquire()
        self.assertEqual(self.api.closed,[123])
    def test_changed_held_identity_rejected(self):
        self.api.changed=True
        with self.assertRaises(self.m.PluginOriginError):self.acquire()
        self.assertEqual(self.api.closed,[123])
    def test_original_budget_expiry_during_read_releases_handle(self):
        self.api.late=True
        with self.assertRaises(TimeoutError):self.acquire()
        self.assertEqual(self.api.closed,[123])
    def test_bad_name_and_symlink_never_open(self):
        with self.assertRaises(self.m.PluginOriginError):
            self.m.PluginFileLease(self.path.with_name('other.dll'),self.proof,self.budget,runtime=self.api)
        original=Path.lstat
        def linked(path,*args,**kw):
            info=original(path,*args,**kw)
            return NS(st_mode=info.st_mode,st_file_attributes=1024) if path==self.path.parent else info
        with patch.object(Path,'lstat',linked):
            with self.assertRaises((self.m.PluginOriginError,ValueError)):self.acquire()
        self.assertEqual(self.api.opened,[])
    def test_failed_release_cannot_claim_cleanup_success(self):
        lease=self.acquire();self.api.close_ok=False
        with self.assertRaises(self.m.PluginOriginError):lease.close()
        self.assertFalse(lease.receipt['released'])
    def test_slow_ancestor_lookup_stops_before_next_lookup_or_open(self):
        original=Path.lstat;seen=[]
        def slow(path,*args,**kw):
            seen.append(path);result=original(path,*args,**kw);self.budget.time=27.;return result
        with patch.object(Path,'lstat',slow):
            with self.assertRaises(TimeoutError):self.acquire()
        self.assertEqual(len(seen),1);self.assertEqual(self.api.opened,[])
    def test_handle_path_mismatch_releases_before_binding(self):
        self.api.final_path=lambda handle:str(self.path.with_name('other.dll'))
        with self.assertRaises(self.m.PluginOriginError):self.acquire()
        self.assertEqual(self.api.closed,[123])
    def test_post_open_link_change_rejected(self):
        original=Path.lstat
        def changed(path,*args,**kw):
            info=original(path,*args,**kw)
            return NS(st_mode=info.st_mode,st_file_attributes=1024) if self.api.opened and path==self.path.parent else info
        with patch.object(Path,'lstat',changed):
            with self.assertRaises(ValueError):self.acquire()
        self.assertEqual(self.api.closed,[123])
    def test_native_identity_stops_before_size_query_when_first_call_expires(self):
        native=self.m.FileApi.__new__(self.m.FileApi);native.budget=self.budget
        def first(*args):self.budget.time=27.;return 1
        def forbidden(*args):self.fail('A second native query ran after expiry')
        native.file_info=first;native.file_size=forbidden
        with self.assertRaises(TimeoutError):native.identity(123)

if __name__=='__main__':unittest.main()
