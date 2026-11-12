import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def synthetic_pe(machine=0x8664):
    b=bytearray(512);b[:2]=b'MZ';struct.pack_into('<I',b,0x3c,128)
    b[128:132]=b'PE\0\0';struct.pack_into('<H',b,132,machine)
    struct.pack_into('<H',b,150,0x22);struct.pack_into('<H',b,152,0x20b)
    return bytes(b)

class ToolchainTests(unittest.TestCase):
    def api(self):
        self.assertTrue((ROOT/'toolchain.py').is_file(),'strict installed toolchain implementation required')
        import toolchain
        return toolchain
    def test_pe_native_machine_is_mandatory_and_corruption_rejected(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'tool.exe';p.write_bytes(synthetic_pe())
            self.assertEqual(m.pe(p,0x8664)['machine'],0x8664)
            with self.assertRaises(m.GateFailure):m.pe(p,0xaa64)
            p.write_bytes(b'MZ'+b'\0'*200)
            with self.assertRaises(m.GateFailure):m.pe(p,0x8664)
    def test_symlink_and_hardlink_are_not_canonical_source_or_tool(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'tool.exe';p.write_bytes(synthetic_pe())
            alias=root/'alias.exe';alias.symlink_to(p)
            with self.assertRaises(m.GateFailure):m.pe(alias,0x8664)
            alias.unlink();alias.hardlink_to(p)
            with self.assertRaises(m.GateFailure):m.pe(p,0x8664)
    def test_coff_machine_and_section_table_are_checked(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.obj';b=bytearray(60);struct.pack_into('<HH',b,0,0x8664,1);p.write_bytes(b)
            self.assertEqual(m.coff(p,0x8664)['machine'],0x8664)
            with self.assertRaises(m.GateFailure):m.coff(p,0xaa64)
            p.write_bytes(b[:20])
            with self.assertRaises(m.GateFailure):m.coff(p,0x8664)
    def test_unknown_arch_and_emulation_fail_before_selecting_tools(self):
        m=self.api()
        for args in (('x86',0x14c,0),('arm64',0xaa64,0x8664),('x64',0xaa64,0)):
            with self.subTest(case=args[0]):
                with self.assertRaises(m.GateFailure):m.architecture(*args)
        self.assertEqual(m.architecture('arm64',0xaa64,0),'arm64')
    def test_windows_cmd_paths_reject_expansion_or_injection(self):
        m=self.api()
        self.assertEqual(m.cmd_path(r'C:\Program Files\VS'),r'C:\Program Files\VS')
        for s in (r'C:\a%PATH%',r'C:\a!x!',r'C:\a&b',r'C:\a\..\b',r'\\host\share',r'C:\a"b'):
            with self.assertRaises(m.GateFailure):m.cmd_path(s)
    def test_missing_cppwinrt_or_import_library_is_not_silently_substituted(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);ver='10.0.26100.0'
            for rel in m.sdk_members(ver,'x64'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic-sdk-file')
            found=m.installed_sdk(root,'x64');self.assertEqual(found['version'],ver)
            for rel in ('Include/'+ver+'/cppwinrt/winrt/Windows.Storage.h','Lib/'+ver+'/um/x64/windowsapp.lib'):
                p=root/rel;data=p.read_bytes();p.unlink()
                with self.assertRaises(m.GateFailure):m.installed_sdk(root,'x64')
                p.write_bytes(data)
    def test_source_bundle_requires_all_thirteen_exact_bytes(self):
        m=self.api();source=ROOT/'frozen-v2'
        self.assertEqual(len(m.verify_bundle(source)),13)
        import shutil
        with tempfile.TemporaryDirectory() as td:
            r=Path(td)/'bundle';shutil.copytree(source,r)
            p=r/'context_observer.hpp';p.write_bytes(p.read_bytes()+b'\n')
            with self.assertRaises(m.GateFailure):m.verify_bundle(r)
    def test_unadmitted_entry_does_not_report_sdk_success_or_spawn(self):
        self.assertTrue((ROOT/'run_sdk_gate.py').is_file(),'SDK gate entry required')
        import run_sdk_gate
        if sys.platform!='win32':
            r=run_sdk_gate.execute('x64',ROOT/'frozen-v2',None)
            self.assertFalse(r['sdkGatePassed']);self.assertFalse(r['actualWindowsExecuted'])
            self.assertEqual(r['failureCode'],3)
    def test_unsupported_cli_cannot_write_into_preexisting_unowned_directory(self):
        self.assertTrue((ROOT/'run_sdk_gate.py').is_file(),'SDK gate entry required')
        import run_sdk_gate
        import contextlib,io
        if sys.platform!='win32':
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);out=root/'sdk-gate.numeric.json'
                with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    code=run_sdk_gate.main(['--diagnostic-sdk-only','--architecture','x64','--source-bundle',str(ROOT/'frozen-v2'),'--work-root',str(root),'--output',str(out)])
                self.assertEqual(code,2);self.assertFalse(out.exists(),'unowned output must remain absent')
    def test_vs_metadata_rejects_ambiguous_incomplete_preview_and_old_toolsets(self):
        m=self.api();import json
        record={'installationPath':r'C:\Program Files\Visual Studio','installationVersion':'17.14.19',
          'isComplete':True,'isLaunchable':True,'isPrerelease':False}
        self.assertEqual(m.vs_metadata(json.dumps([record]).encode())['version'],'17.14.19')
        variants=[[record,record],[],[{**record,'isComplete':False}],[{**record,'isPrerelease':True}],
          [{**record,'installationVersion':'16.11.0'}],[{**record,'installationPath':r'C:\a%PATH%'}]]
        for index,value in enumerate(variants):
            with self.subTest(case=index):
                with self.assertRaises(m.GateFailure):m.vs_metadata(json.dumps(value).encode())
    def test_batch_factory_has_no_normal_observation_mode_and_clears_compiler_injection(self):
        import run_sdk_gate as gate
        vs={'cl':r'C:\VS\cl.exe','link':r'C:\VS\link.exe','devcmd':r'C:\VS\VsDevCmd.bat'}
        sdk={'root':r'C:\SDK','version':'10.0.26100.0'}
        with self.assertRaises(gate.GateFailure):gate.compile_batch('normal',vs,sdk,r'C:\owned','x64')
        for phase in ('port','smoke','link'):
            text=gate.compile_batch(phase,vs,sdk,r'C:\owned','x64')
            self.assertIn('set "CL="',text);self.assertIn('set "_CL_="',text)
            self.assertIn('set "LINK="',text);self.assertIn('set "_LINK_="',text)
            self.assertNotIn('set >',text);self.assertNotIn('set_input',text)
    def test_private_job_environment_accepts_only_complete_fresh_literal_map(self):
        self.assertTrue((ROOT/'owned_job_win32.py').is_file(),'typed owned Job port required')
        import owned_job_win32 as native
        from supervisor import child_environment
        e=child_environment(r'C:\Windows',r'C:\Program Files',r'C:\Program Files (x86)',r'C:\owned')
        block=native._environment_block(e)
        self.assertEqual(list(block)[-2:],[0,0])
        variants=[{**e,'GH_TOKEN':'SYNTHETIC'},dict(e),dict(e)]
        variants[1].pop('PATH');variants[2]['VSCMD_SKIP_SENDTELEMETRY']='0'
        for index,v in enumerate(variants):
            with self.subTest(case=index):
                with self.assertRaises(native.NativeCallError):native._environment_block(v)
        class ParentMap(dict):
            def items(self):raise AssertionError('parent map enumerated')
        with self.assertRaises(native.NativeCallError):native._environment_block(ParentMap(e))
    def test_unknown_cli_argument_is_never_printed(self):
        import run_sdk_gate as gate
        import contextlib,io
        out=io.StringIO();err=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=gate.main(['--unknown','SYNTHETIC-PRIVATE-ARG'])
        self.assertEqual(code,2);self.assertEqual(out.getvalue(),'');self.assertEqual(err.getvalue(),'')
    def test_existing_or_alias_compiler_output_is_rejected_before_launch(self):
        import run_sdk_gate as gate
        self.assertTrue(hasattr(gate,'require_fresh_outputs'),'compile output admission required')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.assertTrue(gate.require_fresh_outputs(root,('observer.obj',)))
            p=root/'observer.obj';p.write_bytes(b'synthetic')
            with self.assertRaises(gate.GateFailure):gate.require_fresh_outputs(root,('observer.obj',))
            p.unlink();p.symlink_to(root/'absent')
            with self.assertRaises(gate.GateFailure):gate.require_fresh_outputs(root,('observer.obj',))
