"""Admission rejects false causal/architecture/source proof, using retained log shapes."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('control', ROOT/'suite/scripts/native_python_control.py')
control = importlib.util.module_from_spec(SPEC) if SPEC else None


class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SPEC.loader or not Path(SPEC.origin).exists():
            return
        SPEC.loader.exec_module(control)

    def require_helper(self):
        self.assertTrue(Path(SPEC.origin).is_file(), 'native Python control implementation missing')

    def build(self, log, code, case):
        root='C:/SelectedVS/VC/Tools/MSVC/14.51.36231'
        tools=[]
        for host,machine in [('HostX86',0x14c),('Hostarm64',0xAA64)]:
            for name in ['CL.exe','link.exe','c2.dll']:
                tools.append({'path':root+'/bin/'+host+'/arm64/'+name,'sha256':'a'*64,'size':100,'machine':machine,'fileVersion':'19.51.36260.0'})
        for host in ['HostX86','HostX64','Hostarm64']:
            log=log.replace(host+'/arm64/',root+'/bin/'+host+'/arm64/')
        log+='\nPythonControl actual task override: Platform=ARM64 VCToolsInstallDir='+root+'/ VCToolsVersion=14.51.36231'
        return control.admit_build(log,code,case,{'toolsRoot':root,'toolsetVersion':'14.51.36231','tools':tools,'observedTools':tools})

    def test_baseline_requires_msbuild_failure_and_exact_heap_retry(self):
        self.require_helper()
        log = ('HostX86/arm64/CL.exe /O2 /GL /MP /Zm200\n'
               'HostX86/arm64/link.exe /LTCG /MACHINE:ARM64\n'
               'Hacl_Hash_SHA2.c(243): fatal error C1002: compiler is out of heap space in pass 2\n'
               'LINK : the 32-bit linker ran out of heap space and is going to restart linking with a 64-bit linker\n'
               'LINK : restarting link with 64-bit linker HostX64/arm64/link.exe\n'
               'Finished generating code\npythoncore.vcxproj -- FAILED.\nBuild FAILED.\n1 Error(s)')
        self.assertEqual(self.build(log, 1, 'baseline')['status'], 'reproduced')
        for bad in [log.replace('C1002', 'C1060'), log.replace('Build FAILED.', 'Build succeeded.'), log.replace('32-bit linker', 'linker')]:
            with self.assertRaises(ValueError): self.build(bad, 1, 'baseline')
        with self.assertRaises(ValueError): self.build(log, 0, 'baseline')
        self.assertEqual(self.build(log[:log.index('Hacl_')]+ 'Build succeeded.\n0 Error(s)', 0, 'baseline')['status'], 'non-reproduction')

    def test_candidate_requires_actual_native_tools_and_no_retry(self):
        self.require_helper()
        log='Hostarm64/arm64/CL.exe /O2 /GL /MP /Zm200\nHostarm64/arm64/link.exe /LTCG /MACHINE:ARM64\nBuild succeeded.\n0 Error(s)'
        self.assertEqual(self.build(log+'\nunused fallback property=HostX86/arm64/link.exe', 0, 'candidate')['status'], 'passed')
        for bad in [log.replace('Hostarm64', 'HostX64'), log+'\nrestarting link', log.replace('/GL', '/Od')]:
            with self.assertRaises(ValueError): self.build(bad, 0, 'candidate')

    def test_input_closure_is_complete_not_hacl_subset(self):
        self.require_helper()
        expected=control.expected_inputs(ROOT/'suite/diagnostics/native-python')
        self.assertEqual(len(expected),235)
        control.check_inputs(expected,expected)
        with self.assertRaises(ValueError): control.check_inputs(expected[:-1],expected)

    def test_source_pin_and_tree_drift_rejected(self):
        self.require_helper()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.c';p.write_bytes(b'authentic')
            with self.assertRaises(ValueError):control.verify_file(p,9,'0'*64)
            self.assertTrue(hasattr(control,'tree_digest'),'source tree verifier missing')
            good=control.tree_digest(Path(tmp))
            p.write_bytes(b'drift')
            self.assertNotEqual(good,control.tree_digest(Path(tmp)))

    def test_recipe_and_patch_drift_fails_before_mutation(self):
        self.require_helper()
        data=ROOT/'suite/diagnostics/native-python'
        control.verify_recipes(data)
        with tempfile.TemporaryDirectory() as t:
            import shutil
            dst=Path(t)/'data'; shutil.copytree(data,dst)
            (dst/'decimal.patch.1').write_bytes(b'changed')
            with self.assertRaises(ValueError): control.verify_recipes(dst)

    def test_runtime_requires_exact_exe_dll_native_and_builtin(self):
        self.require_helper()
        good={'executable':'C:/owned/python.exe','dll':'C:/owned/python313.dll','processMachine':0,'nativeMachine':0xAA64,'module':'built-in','constructors':['_sha2']*4,'testsPassed':True}
        control.admit_runtime(good,good['executable'],good['dll'])
        for k,v in [('dll','C:/other/python313.dll'),('module','_hashlib.pyd'),('processMachine',0x8664),('testsPassed',False),('constructors',['_hashlib']*4)]:
            with self.assertRaises(ValueError): control.admit_runtime(dict(good,**{k:v}),good['executable'],good['dll'])

if __name__ == '__main__': unittest.main()

class PowerShellControlTests(unittest.TestCase):
    def ps(self, script):
        import os, shutil, subprocess
        pwsh=shutil.which('pwsh') or str(ROOT.parent/'work/ime-api-review/powershell/pwsh')
        result=subprocess.run([pwsh,'-NoProfile','-Command',". '"+str(ROOT/'suite/scripts/probe-native-python.ps1')+"';"+script+';exit 0'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result

    def test_import_preserves_distinct_arguments_and_has_no_side_effect(self):
        self.ps("if(-not(Get-Command Invoke-PythonControl)){throw 'missing control'}; if($PythonControlOutput -ne ''){throw 'bad default'}")

    def test_sanitized_environment_removes_fake_credential_and_restores(self):
        self.ps("$env:OPENGEUL_TEST_SECRET='credential-sentinel'; $child=Get-PythonControlChildEnvironment @{}; if($child.ContainsKey('OPENGEUL_TEST_SECRET')){throw 'secret copied'}; if($env:OPENGEUL_TEST_SECRET -cne 'credential-sentinel'){throw 'parent changed'}")

    def test_expired_budget_preserves_unqualified_diagnostic(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';work=Path(tmp)/'work'
            self.ps("try {Invoke-PythonControl '"+str(out)+"' '"+str(work)+"' '2001-01-01T00:00:00.0000000Z'}catch{}")
            receipt=json.loads((out/'diagnostic.json').read_text())
            self.assertFalse(receipt['passed']);self.assertFalse(receipt['causalCorrectionProven']);self.assertIn('error',receipt)

class RoundOneReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SPEC.loader.exec_module(control)

    def test_baseline_rejects_crash_and_outer_make_exit(self):
        log='Hacl_Hash_SHA2.c(243): fatal error C1002: compiler is out of heap space in pass 2\n32-bit linker ran out of heap space\nrestarting link with 64-bit linker HostX64/arm64/link.exe\nFinished generating code\npythoncore.vcxproj -- FAILED.\nBuild FAILED.\n1 Error(s)'
        # A matching textual diagnostic cannot turn a natural crash/outer make exit into MSBuild exit1.
        for code in [3221225477,-1073741819,2,124]:
            with self.assertRaisesRegex(ValueError,'Expected direct MSBuild normal failure exit1',msg=str(code)):control.admit_build(log,code,'baseline')

    def test_baseline_rejects_unrelated_errors_and_nonexact_summary(self):
        fixture=ControlTests()
        log=('HostX86/arm64/CL.exe /O2 /GL /MP /Zm200\nHostX86/arm64/link.exe /LTCG /MACHINE:ARM64\n'
             'Hacl_Hash_SHA2.c(243): fatal error C1002: compiler is out of heap space in pass 2\n'
             'LINK : the 32-bit linker ran out of heap space and is going to restart linking with a 64-bit linker\n'
             'LINK : restarting link with 64-bit linker HostX64/arm64/link.exe\n'
             'Finished generating code\npythoncore.vcxproj -- FAILED.\nBuild FAILED.\n1 Error(s)')
        fixture.build(log,1,'baseline')
        for bad in [log.replace('1 Error(s)','11 Error(s)'),log+'\nother.c(10): fatal error C1002: compiler is out of heap space in pass 2',log+'\nerror MSB6006: other task failed',log+'\nLINK : fatal error LNK1120: unresolved external',log+'\nerror : unrelated failure']:
            with self.assertRaises(ValueError):fixture.build(bad,1,'baseline')

    def test_overall_nonreproduction_retains_feasibility_but_fails(self):
        ps=PowerShellControlTests()
        ps.ps("$r=[ordered]@{passed=$false;causalCorrectionProven=$false;stage='runtime'}; $failed=$false; try {Complete-PythonControlResult $r @{status='non-reproduction'} @{status='passed'} @{testsPassed=$true}}catch{$failed=$true}; if(-not $failed -or $r.passed -or $r.causalCorrectionProven -or -not $r.candidateFeasible){throw 'nonreproduction incorrectly passes'}; Complete-PythonControlResult $r @{status='reproduced'} @{status='passed'} @{testsPassed=$true}; if(-not $r.passed -or -not $r.causalCorrectionProven){throw 'valid pair rejected'}")

    def test_wrong_root_toolset_and_version_are_rejected(self):
        self.assertTrue(hasattr(control,'bind_tools'),'resolved tool binding missing')
        root='C:/SelectedVS/VC/Tools/MSVC/14.51.36231'
        tools=[]
        for name in ['CL.exe','link.exe','c2.dll']:
            tools.append({'path':root+'/bin/Hostarm64/arm64/'+name,'sha256':'a'*64,'size':100,'machine':0xAA64,'fileVersion':'19.51.36260.0'})
        inventory={'toolsRoot':root,'toolsetVersion':'14.51.36231','tools':tools,'observedTools':tools}
        log='\n'.join(t['path']+' /O2' for t in tools if t['path'].endswith('.exe'))+'\nPythonControl actual task override: Platform=ARM64 VCToolsInstallDir='+root+'/ VCToolsVersion=14.51.36231'
        self.assertEqual(len(control.bind_tools(log,'candidate',inventory)),2)
        self.assertEqual(len(control.bind_tools(log.replace('/','\\').replace('\\O2','/O2'),'candidate',inventory)),2)
        for bad in [log.replace('SelectedVS','DifferentVS'),log.replace('14.51.36231','14.99.99999')]:
            with self.assertRaises(ValueError):control.bind_tools(bad,'candidate',inventory)
        changed=dict(inventory,observedTools=[dict(tools[0],fileVersion='19.99.99999.0'),*tools[1:]])
        with self.assertRaises(ValueError):control.bind_tools(log,'candidate',changed)
        with self.assertRaises(ValueError):control.bind_tools(log.replace(root,'relative/path'),'candidate',inventory)

    def test_child_environment_omits_credential_without_parent_mutation(self):
        import sys
        ps=PowerShellControlTests()
        with tempfile.TemporaryDirectory() as tmp:
            prefix=Path(tmp)/'child'
            ps.ps("$env:OPENGEUL_TEST_SECRET='credential-sentinel';$child=Get-PythonControlChildEnvironment @{};if($env:OPENGEUL_TEST_SECRET -cne 'credential-sentinel' -or $child.ContainsKey('OPENGEUL_TEST_SECRET')){throw 'parent mutation or secret copy'}; Invoke-PythonControlBuildCommand '"+sys.executable+"' @('-c','import os;assert \"OPENGEUL_TEST_SECRET\" not in os.environ;print(\"child clean\")') '"+tmp+"' '"+str(prefix)+"' -ChildEnvironment $child -TimeoutMinutes 1|Out-Null; if($env:OPENGEUL_TEST_SECRET -cne 'credential-sentinel'){throw 'parent changed'}")
            self.assertEqual(Path(str(prefix)+'.stdout.log').read_text().strip(),'child clean')

class RoundOneChildBoundaryTests(unittest.TestCase):
    def test_sanitized_child_timeout_keeps_owned_failure_receipt(self):
        import json,sys
        ps=PowerShellControlTests()
        with tempfile.TemporaryDirectory() as tmp:
            prefix=Path(tmp)/'timeout'
            ps.ps("$child=Get-PythonControlChildEnvironment @{};try{Invoke-PythonControlBuildCommand '"+sys.executable+"' @('-c','import time;print(\"before timeout\",flush=True);time.sleep(20)') '"+tmp+"' '"+str(prefix)+"' -ChildEnvironment $child -TimeoutMinutes (1.0/60)|Out-Null}catch{}")
            proof=json.loads(Path(str(prefix)+'.command.json').read_text())
            self.assertFalse(proof['passed']);self.assertTrue(proof['forcedTermination']);self.assertTrue(proof['directProcessDeathVerified'])
            self.assertIn('before timeout',Path(str(prefix)+'.stdout.log').read_text())
