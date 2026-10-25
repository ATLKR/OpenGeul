"""Pure file eligibility and native seam; no Windows execution on portable hosts."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_plugin_symbols import dll,pdb,GUID

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/plugin_symbol_resolution.py'

class Budget:
    started=0.;work_deadline=27.;deadline=30.
    def __init__(self):self.time=0.
    def now(self,*,cleanup=False):
        if self.time >= (30 if cleanup else 27):raise TimeoutError('original budget')
        return self.time

class Runtime:
    def __init__(self,path):self.path=path;self.calls=[];self.info={};self.answer={};self.fail_cleanup=False;self.on_query=None;self.held_paths=[];self.released=[]
    def preflight_path(self,path):pass
    def hold(self,path):self.calls.append('hold');self.held_paths.append(path);return 123+len(self.held_paths)
    def release(self,handle):self.calls.append('release');self.released.append(handle);return True
    def initialize(self,path,options):self.calls.append('initialize');return True
    def load(self,path,base,size,image_handle=None):self.calls.append('load');self.base=base;self.size=size;self.loaded_file_handle=image_handle;return base
    def module(self,base):
        self.calls.append('module');return dict(dict(type=3,base=base,size=self.size,path=str(self.path),guid=str(GUID),age=2,unmatched=False),**self.info)
    def query(self,address):
        self.calls.append(('query',address))
        if self.on_query:self.on_query()
        return dict(dict(name='WinSalYieldMutex::doAcquire',base=self.base,address=self.base+0x1100,size=16,tag=5,flags=0),**self.answer)
    def unload(self,base):self.calls.append('unload');return not self.fail_cleanup
    def cleanup(self):self.calls.append('cleanup');return True

class ResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SCRIPT.exists():
            spec=importlib.util.spec_from_file_location('resolution',SCRIPT);cls.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.m)
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'bounded resolver missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name).resolve()/'vclplug_winlo.pdb';self.path.write_bytes(pdb())
        self.dll_path=self.path.with_suffix('.dll');self.dll_path.write_bytes(dll())
        self.budget=Budget();self.runtime=Runtime(self.path)
        self.proof=dict(kind='matched-plugin-symbols',identityMatched=True,acceptance=False,sourceCommit='a'*40,
            matchedIdentity=dict(guid=str(GUID),age=2),files=dict(dll=dict(name='vclplug_winlo.dll',**self.m.retention.pin(dll())),pdb=dict(name='vclplug_winlo.pdb',**self.m.retention.pin(pdb()))))
    def run_resolve(self,rvas=None):return self.m.resolve(dll(),self.path,self.proof,[0x1104] if rvas is None else rvas,self.budget,runtime=self.runtime)
    def test_fixed_name_qualification_roundtrip_is_not_runtime_attribution(self):
        def fixed():
            self.runtime.calls.append('fixed-name')
            return dict(name='WinSalYieldMutex::doAcquire',base=self.m.IMAGE_BASE,address=self.m.IMAGE_BASE+0x1100,size=16,tag=5,flags=0)
        self.runtime.fixed_acquire=fixed
        self.assertTrue(hasattr(self.m,'qualify'),'fixed native qualification missing')
        result=self.m.qualify(dll(),self.path,self.proof,self.budget,runtime=self.runtime)
        self.assertTrue(result['qualification']['roundTripMatched'])
        self.assertFalse(result['runtimeCallerProved']);self.assertEqual(result['frames'],[])
        self.assertEqual(self.runtime.calls[-4:],['unload','cleanup','release','release'])
        self.assertEqual(self.runtime.calls.count('fixed-name'),1)
        self.runtime.info={'type':7}
        result=self.m.qualify(dll(),self.path,self.proof,self.budget,runtime=self.runtime)
        self.assertTrue(result['qualification']['roundTripMatched'])
        self.assertFalse(result['runtimeCallerProved'])
    def test_qualification_wrong_or_nearest_name_never_passes(self):
        self.assertTrue(hasattr(self.m,'qualify'),'fixed native qualification missing')
        good=dict(name='WinSalYieldMutex::doAcquire',base=self.m.IMAGE_BASE,address=self.m.IMAGE_BASE+0x1100,size=16,tag=5,flags=0)
        for wrong in (None,dict(good,name='unknown'),dict(good,size=0),dict(good,address=0)):
            self.runtime.fixed_acquire=lambda:wrong
            with self.assertRaises(self.m.ResolutionError):self.m.qualify(dll(),self.path,self.proof,self.budget,runtime=self.runtime)
        self.runtime.fixed_acquire=lambda:good;self.runtime.answer={'size':8}
        with self.assertRaises(self.m.ResolutionError):self.m.qualify(dll(),self.path,self.proof,self.budget,runtime=self.runtime)
    def test_read_budget_stops_between_pdb_chunks(self):
        import io
        reads=[]
        class Stream(io.BytesIO):
            def fileno(self):return 12
            def read(inner,size=-1):
                reads.append(size);value=super(Stream,inner).read(size);self.budget.time=27.;return value
        stream=Stream(b'x'*(2*1024*1024));info=self.path.stat()
        from types import SimpleNamespace
        large=SimpleNamespace(**{key:getattr(info,key) for key in ('st_mode','st_dev','st_ino','st_mtime_ns','st_ctime_ns')},st_size=2*1024*1024)
        with patch.object(Path,'open',return_value=stream),patch.object(Path,'stat',return_value=large),patch.object(os,'fstat',return_value=large):
            with self.assertRaises(TimeoutError):self.m.retention.read_regular(self.path,3*1024*1024,budget=self.budget)
        self.assertEqual(len(reads),1)
    def test_known_function_callpc_and_mandatory_cleanup(self):
        r=self.run_resolve();self.assertEqual(r['frames'][0]['tag'],'mutex-acquire');self.assertEqual(r['frames'][0]['callRva'],0x1100)
        self.assertEqual(self.runtime.calls[-4:],['unload','cleanup','release','release']);self.assertTrue(r['cleanupComplete']);self.assertFalse(r['runtimeCallerProved'])
        self.assertNotIn(str(self.path),json.dumps(r));self.assertNotIn('WinSal',json.dumps(r))
    def test_bad_hash_or_identity_never_starts_native(self):
        for key in ('dll','pdb'):
            saved=self.proof['files'][key]['sha256'];self.proof['files'][key]['sha256']='0'*64
            with self.assertRaises(self.m.ResolutionError):self.run_resolve()
            self.proof['files'][key]['sha256']=saved
        self.assertEqual(self.runtime.calls,[])
    def test_query_bounds_zero_or_nearest_export_unresolved(self):
        for answer in ({'size':0},{'flags':0x200},{'tag':10},{'name':'private raw unknown'},{'address':self.m.IMAGE_BASE+0x1200},{'base':0}):
            # Runtime's dict merge intentionally permits test overrides.
            self.runtime.answer=answer
            r=self.run_resolve();self.assertEqual(r['frames'][0]['tag'],'unresolved')
    def test_wrong_loaded_pdb_never_queries_but_cleans(self):
        self.runtime.info={'guid':'ffffffff-ffff-ffff-ffff-ffffffffffff'}
        with self.assertRaises(self.m.ResolutionError):self.run_resolve()
        self.assertFalse(any(isinstance(c,tuple) for c in self.runtime.calls));self.assertEqual(self.runtime.calls[-4:],['unload','cleanup','release','release'])
    def test_symbol_load_uses_held_verified_pe_without_relaxing_unmatched(self):
        original=self.runtime.load
        def load(path,base,size,image_handle=None):
            self.runtime.info={'unmatched':Path(path)!=self.dll_path}
            return original(path,base,size,image_handle)
        self.runtime.load=load
        result=self.run_resolve()
        self.assertTrue(result['complete']);self.assertTrue(result['imageHeldDuringResolution'])
        self.assertEqual(self.runtime.held_paths,[str(self.path),str(self.dll_path)])
        self.assertEqual(self.runtime.loaded_file_handle,125,'loader did not receive the held PE handle')
        self.assertCountEqual(self.runtime.released,[124,125])
        self.runtime.load=original;self.runtime.info={'unmatched':True}
        with self.assertRaises(self.m.ModuleIdentityError) as caught:self.run_resolve()
        self.assertEqual(caught.exception.args,((32,3),))
    def test_missing_or_wrong_sibling_image_never_reaches_native_loading(self):
        self.dll_path.unlink()
        with self.assertRaises(FileNotFoundError):self.run_resolve()
        self.assertEqual(self.runtime.calls,[])
        self.dll_path.write_bytes(dll()+b'changed')
        with self.assertRaisesRegex(self.m.ResolutionError,'image-bytes-mismatch'):self.run_resolve()
        self.assertEqual(self.runtime.calls,[])
    def test_image_replacement_during_hold_rejected_and_both_handles_released(self):
        original=self.runtime.hold
        def hold(path):
            handle=original(path)
            if Path(path)==self.dll_path:self.dll_path.write_bytes(dll()+b'changed')
            return handle
        self.runtime.hold=hold
        with self.assertRaisesRegex(self.m.ResolutionError,'image-changed-under-lock'):self.run_resolve()
        self.assertNotIn('initialize',self.runtime.calls)
        self.assertCountEqual(self.runtime.released,[124,125])
    def test_expiry_after_image_hold_still_releases_both_handles(self):
        original=self.runtime.hold
        def hold(path):
            handle=original(path)
            if Path(path)==self.dll_path:self.budget.time=27.
            return handle
        self.runtime.hold=hold
        with self.assertRaises(TimeoutError):self.run_resolve()
        self.assertNotIn('initialize',self.runtime.calls)
        self.assertCountEqual(self.runtime.released,[124,125])
    def test_image_change_after_query_or_release_failure_never_passes(self):
        self.runtime.on_query=lambda:self.dll_path.write_bytes(dll()+b'changed')
        with self.assertRaisesRegex(self.m.ResolutionError,'image-changed'):self.run_resolve()
        self.assertCountEqual(self.runtime.released,[124,125])
        self.dll_path.write_bytes(dll());self.runtime=Runtime(self.path)
        original=self.runtime.release
        def release(handle):original(handle);return handle!=125
        self.runtime.release=release
        with self.assertRaises(self.m.ResolutionError) as caught:self.run_resolve()
        self.assertEqual(caught.exception.resolutionReceipt['cleanupErrors'],[{'stage':'image-handle','errorType':'ResolutionError'}])
        self.assertCountEqual(self.runtime.released,[124,125])
    def test_dia_symbols_require_the_same_exact_identity_as_pdb(self):
        self.runtime.info={'type':7}
        self.assertTrue(self.run_resolve()['complete'])
        for kind in (0,1,2,4,5,6,8,9):
            self.runtime.info={'type':kind}
            with self.assertRaises(self.m.ResolutionError):self.run_resolve()
        for wrong in ({'type':4},{'type':5},{'type':7,'age':3},{'type':7,'guid':'wrong'},
                      {'type':7,'base':0},{'type':7,'size':1},{'type':7,'unmatched':True},
                      {'type':7,'path':str(self.path.with_name('other.pdb'))}):
            self.runtime.info=wrong
            with self.assertRaises(self.m.ResolutionError):self.run_resolve()
    def test_metadata_rejection_preserves_only_finite_mismatch_bits(self):
        self.assertTrue(hasattr(self.m,'ModuleIdentityError'),'individual identity mismatch evidence absent')
        self.runtime.info={'type':4,'age':3,'guid':'private-guid','path':'private-path'}
        with self.assertRaises(self.m.ModuleIdentityError) as caught:self.run_resolve()
        self.assertEqual(caught.exception.args,((1|8|16|64,4),))
        self.assertNotIn('private',str(caught.exception))
        self.assertEqual(self.runtime.calls[-4:],['unload','cleanup','release','release'])
    def test_original_expiry_no_second_query_and_cleanup(self):
        self.runtime.on_query=lambda:setattr(self.budget,'time',27.)
        with self.assertRaises(TimeoutError):self.run_resolve([0x1104,0x1108])
        self.assertEqual(sum(isinstance(c,tuple) for c in self.runtime.calls),1);self.assertEqual(self.runtime.calls[-4:],['unload','cleanup','release','release'])
    def test_cleanup_failure_cannot_return_success(self):
        self.runtime.fail_cleanup=True
        with self.assertRaises(self.m.ResolutionError) as caught:self.run_resolve()
        self.assertFalse(caught.exception.resolutionReceipt['cleanupComplete']);self.assertEqual(self.runtime.calls[-1],'release')
    def test_invalid_rvas_and_ambient_symbols_rejected_before_native(self):
        for rvas in ([0],[5],[0x2004],[0x1104]*33):
            with self.assertRaises(self.m.ResolutionError):self.run_resolve(rvas)
        with patch.dict(os.environ,{'_NT_SYMBOL_PATH':'srv*private'}):
            with self.assertRaises(self.m.ResolutionError):self.run_resolve()
        self.assertEqual(self.runtime.calls,[])
    def test_search_directory_rejects_unrelated_files(self):
        (self.path.parent/'other.pdb').write_bytes(b'not eligible')
        with self.assertRaises(self.m.ResolutionError):self.run_resolve()
        self.assertEqual(self.runtime.calls,[])
    def test_native_initialize_expiry_between_options_and_session(self):
        runtime=object.__new__(self.m.NativeRuntime);runtime.budget=self.budget;runtime.session=1;runtime.drive_type=lambda path:3;calls=[]
        def options(value):self.budget.time=27.;return value
        runtime.options=options;runtime.init=lambda *a:calls.append(a)
        with self.assertRaises(TimeoutError):runtime.initialize(str(self.path.parent),self.m.OPTIONS)
        self.assertEqual(calls,[])
    def test_fixed_windows_abi_layout(self):
        self.assertEqual(self.m.C.sizeof(self.m.ModuleInfo),1680)
        self.assertEqual(self.m.C.sizeof(self.m.SymbolInfo),88)
        self.assertEqual(self.m.SymbolInfo.Name.offset,84)
        self.assertEqual(self.m.ModuleInfo.PdbSig70.offset,1624)
    def test_primary_error_survives_failed_cleanup(self):
        self.runtime.info={'age':3};self.runtime.fail_cleanup=True
        with self.assertRaisesRegex(self.m.ResolutionError,'loaded-symbol-identity') as caught:self.run_resolve()
        self.assertEqual(caught.exception.resolutionReceipt['cleanupErrors'][0]['stage'],'unload')
        self.assertEqual(self.runtime.calls[-1],'release')
    def test_native_uses_only_explicit_system_dbghelp_and_noninvading_session(self):
        from types import SimpleNamespace
        system=self.path.parent/'system';system.mkdir();(system/'dbghelp.dll').write_bytes(b'synthetic system file')
        calls=[]
        class Function:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        def directory(buffer,size):buffer.value=str(system);return len(str(system))
        kernel=SimpleNamespace(GetSystemDirectoryW=Function(directory),GetDriveTypeW=Function(lambda path:3),CreateFileW=Function(lambda *args:123),CloseHandle=Function(lambda handle:True))
        names=('SymSetOptions','SymInitialize','SymLoadModuleEx','SymGetModuleInfo64','SymFromAddr','SymFromName','SymUnloadModule64','SymCleanup')
        native=SimpleNamespace(**{n:Function(lambda *a:True) for n in names})
        native.SymSetOptions=Function(lambda mask:mask)
        native.SymInitialize=Function(lambda *a:calls.append(('initialize',a)) or True)
        def load(path,**kwargs):calls.append(('library',path,kwargs));return kernel if path=='kernel32.dll' else native
        arch=SimpleNamespace(observe_native_architecture=lambda:{},validate_native_architecture=lambda value,expected:self.assertEqual(expected,'arm64'))
        with patch.object(self.m,'os',SimpleNamespace(name='nt',path=os.path,environ=os.environ)),patch.object(self.m,'_module',return_value=arch),patch.object(self.m.C,'WinDLL',load,create=True):
            runtime=self.m.NativeRuntime(self.budget)
            self.assertTrue(runtime.initialize(str(self.path.parent),self.m.OPTIONS))
        self.assertEqual(calls[1][1],str(system/'dbghelp.dll'));self.assertEqual(calls[1][2]['winmode'],0x800)
        self.assertFalse(calls[-1][1][2]);self.assertIsNotNone(calls[-1][1][0])
        self.assertEqual(calls[-1][1][1],str(self.path.parent).encode('ascii'))

    def test_mapped_remote_drive_rejected_before_symbol_options(self):
        runtime=object.__new__(self.m.NativeRuntime);runtime.budget=self.budget;runtime.session=1;runtime.drive_type=lambda path:4
        calls=[];runtime.options=lambda value:calls.append('options');runtime.init=lambda *args:calls.append('initialize')
        with self.assertRaisesRegex(self.m.ResolutionError,'local-fixed-drive'):
            runtime.initialize(str(self.path.parent),self.m.OPTIONS)
        self.assertEqual(calls,[])

    def test_pdb_replacement_on_lock_acquisition_rejected_before_initialize(self):
        def hold(path):
            self.runtime.calls.append('hold');self.path.write_bytes(pdb()+b'changed');return 123
        self.runtime.hold=hold
        with self.assertRaises(self.m.ResolutionError):self.run_resolve()
        self.assertEqual(self.runtime.calls,['hold','release'])
    def test_expiry_after_hold_still_releases_original_handle(self):
        def hold(path):self.runtime.calls.append('hold');self.budget.time=27.;return 123
        self.runtime.hold=hold
        with self.assertRaises(TimeoutError):self.run_resolve()
        self.assertEqual(self.runtime.calls,['hold','release'])
    def test_release_failure_stops_success_and_preserves_primary(self):
        self.runtime.release=lambda handle:False
        with self.assertRaises(self.m.ResolutionError) as caught:self.run_resolve()
        self.assertEqual(caught.exception.resolutionReceipt['cleanupErrors'][-1]['stage'],'pdb-handle')
        self.runtime.info={'age':3}
        with self.assertRaisesRegex(self.m.ResolutionError,'loaded-symbol-identity') as caught:self.run_resolve()
        self.assertFalse(caught.exception.resolutionReceipt['cleanupComplete'])
    def test_native_hold_denies_write_delete_and_passes_only_image_handle_to_loader(self):
        runtime=object.__new__(self.m.NativeRuntime);runtime.budget=self.budget;runtime.session=1
        runtime.drive_type=lambda path:3;calls=[]
        runtime.open_file=lambda *args:calls.append(('open',args)) or 123
        runtime.close_file=lambda handle:calls.append(('close',handle)) or True
        runtime.load_module=lambda *args:calls.append(('load',args)) or self.m.IMAGE_BASE
        self.assertEqual(runtime.hold(str(self.dll_path)),123)
        self.assertEqual(calls[0][1],(str(self.dll_path),0x80000000,1,None,3,0x80,None))
        runtime.load(str(self.dll_path),self.m.IMAGE_BASE,8192,123)
        self.assertEqual(calls[1][1][1],123)
        self.assertEqual(calls[1][1][2],str(self.dll_path).encode('ascii'))
        self.assertTrue(runtime.release(123));self.assertEqual(calls[-1],('close',123))
        for invalid in (None,0,-1,True,self.m.C.c_void_p(-1).value,2**64):
            count=len(calls)
            with self.assertRaisesRegex(self.m.ResolutionError,'image-handle'):
                runtime.load(str(self.dll_path),self.m.IMAGE_BASE,8192,invalid)
            self.assertEqual(len(calls),count)
    def test_initialize_failure_releases_without_unload_or_session_cleanup(self):
        self.runtime.initialize=lambda *args:False
        with self.assertRaisesRegex(self.m.ResolutionError,'symbol-initialize'):self.run_resolve()
        self.assertEqual(self.runtime.calls,['hold','hold','release','release'])
    def test_total_expiry_still_attempts_all_mandatory_releases(self):
        self.runtime.on_query=lambda:setattr(self.budget,'time',30.)
        with self.assertRaises(TimeoutError) as caught:self.run_resolve()
        self.assertEqual(self.runtime.calls[-4:],['unload','cleanup','release','release'])
        self.assertFalse(caught.exception.resolutionReceipt['cleanupComplete'])
        self.assertEqual(caught.exception.resolutionReceipt['cleanupErrors'][-1]['stage'],'cleanup-budget')

    def test_remote_artifact_preflight_precedes_every_filesystem_observation(self):
        native=object.__new__(self.m.NativeRuntime);native.budget=self.budget;native.drive_type=lambda root:4
        with patch.object(self.m.retention,'unlinked',side_effect=AssertionError('stat forbidden')),patch.object(self.m.retention,'read_regular',side_effect=AssertionError('read forbidden')),patch.object(Path,'iterdir',side_effect=AssertionError('listing forbidden')):
            with self.assertRaisesRegex(self.m.ResolutionError,'local-fixed-drive'):
                self.m.resolve(dll(),self.path,self.proof,[0x1104],self.budget,runtime=native)
        self.assertEqual(self.runtime.calls,[])

    def test_allowed_entry_link_rejected_before_is_file(self):
        from types import SimpleNamespace
        entry=self.path.parent/'vclplug_winlo.dll';entry.write_bytes(b'synthetic')
        original_stat=Path.lstat;original_file=Path.is_file;lookups=[]
        def observed_stat(path,*args,**kwargs):
            value=original_stat(path,*args,**kwargs)
            if path==entry:return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=1024)
            return value
        def observed_file(path):
            if path==entry:
                lookups.append(path)
                raise AssertionError('followed linked entry before rejection')
            return original_file(path)
        with patch.object(Path,'lstat',observed_stat),patch.object(Path,'is_file',observed_file):
            with self.assertRaisesRegex(self.m.retention.SymbolError,'linked-path'):
                self.run_resolve()
        self.assertEqual(lookups,[])

class NotificationSymbolTagsTests(unittest.TestCase):
    def test_only_fixed_pinned_notification_names_receive_closed_tags(self):
        spec=importlib.util.spec_from_file_location('notification_symbols',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        for name,tag in {'ImplSalFrameSetInputContext':'frame-input-context','WinSalFrame::SetInputContext':'frame-input-context-dispatch',
                         'SalFrameWndProc':'frame-window-procedure','ImplHandleKeyMsg':'frame-key-handler'}.items():
            value={'name':name,'base':m.IMAGE_BASE,'address':m.IMAGE_BASE+0x1100,'size':16,'tag':5,'flags':0}
            self.assertEqual(m._frame(value,0x1104,0x2000)['tag'],tag)
            self.assertEqual(m._frame(dict(value,name=name+'Suffix'),0x1104,0x2000)['tag'],'unresolved')
