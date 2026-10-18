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

class PreparationTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):SPEC.loader.exec_module(control)

    def patch_tool(self):
        import shutil,os
        tool=shutil.which('patch')
        if not tool:
            candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/usr/bin/patch.exe'
            if candidate.is_file():tool=str(candidate)
        self.assertTrue(tool,'Real GNU patch required for preparation transport regression')
        return Path(tool)

    def fixture(self, tmp, drift=False):
        source=Path(tmp)/'source';(source/'PCbuild').mkdir(parents=True)
        raw=(ROOT/'suite/diagnostics/native-python/preparation-fixtures/openssl.props').read_bytes()
        self.assertEqual(__import__('hashlib').sha256(raw).hexdigest(),'02c2037ca9a4e89fa2ccfb557f51b4a71672bbbacd2bbd3851026f2e7f8dea0e')
        if drift:raw=raw.replace(b'<_DLLSuffix>-3</_DLLSuffix>',b'<_DLLSuffix>-99</_DLLSuffix>')
        (source/'PCbuild/openssl.props').write_bytes(raw)
        return source,ROOT/'suite/diagnostics/native-python/python-3.7.6-msvc-ssl.patch.1'

    def test_authentic_mixed_eol_patch_preserves_binary_source_bytes(self):
        import json,hashlib
        with tempfile.TemporaryDirectory() as tmp:
            source,patch=self.fixture(tmp);prefix=Path(tmp)/'patch'
            control.apply_patch(source,patch,self.patch_tool(),prefix)
            command=json.loads(Path(str(prefix)+'.json').read_text())
            self.assertIn('--binary',command['argv'],'Git/MSYS patch must use explicit byte-preserving I/O for authentic mixed-EOL patch')
            result=(source/'PCbuild/openssl.props').read_bytes()
            self.assertEqual(hashlib.sha256(result).hexdigest(),'80462ef8f222e7bcd8c775963872bd77066a8d9f44eb5517641fda53de037d33')

    def test_failed_authentic_patch_retains_targets_rejects_and_stage_hashes(self):
        import json,hashlib
        with tempfile.TemporaryDirectory() as tmp:
            source,patch=self.fixture(tmp,drift=True);prefix=Path(tmp)/'patch'
            before=(source/'PCbuild/openssl.props').read_bytes()
            with self.assertRaises(ValueError):control.apply_patch(source,patch,self.patch_tool(),prefix)
            evidence=Path(str(prefix)+'.files')
            self.assertTrue((evidence/'before/PCbuild/openssl.props').is_file(),'Pre-patch raw target missing')
            self.assertEqual((evidence/'before/PCbuild/openssl.props').read_bytes(),before)
            self.assertEqual((evidence/'after/PCbuild/openssl.props').read_bytes(),before)
            self.assertTrue((evidence/'after/PCbuild/openssl.props.rej').is_file(),'GNU patch rejection bytes missing')
            receipt=json.loads(Path(str(prefix)+'.json').read_text())
            self.assertEqual(receipt['exitCode'],1)
            self.assertEqual(receipt['before'][0]['sha256'],hashlib.sha256(before).hexdigest())
            self.assertTrue(receipt['after']);self.assertTrue(receipt['patch']['sha256'])

class CommandEnvironmentContractTests(unittest.TestCase):
    def test_common_appdata_os_fields_propagate_only_to_allowed_child(self):
        import sys
        ps=PowerShellControlTests()
        with tempfile.TemporaryDirectory() as tmp:
            prefix=Path(tmp)/'child'
            ps.ps("$env:ALLUSERSPROFILE='C:\\ProgramData';$env:SystemDrive='C:';$env:OPENGEUL_FAKE_CREDENTIAL='must-stay-parent';$child=Get-PythonControlChildEnvironment @{};if($child.ALLUSERSPROFILE -cne $env:ALLUSERSPROFILE -or $child.SystemDrive -cne $env:SystemDrive){throw 'Documented shell-folder OS fields missing'};if($child.ContainsKey('OPENGEUL_FAKE_CREDENTIAL')){throw 'arbitrary credential copied'};Invoke-PythonControlBuildCommand '"+sys.executable+"' @('-c','import os;assert os.environ[\"ALLUSERSPROFILE\"]==\"C:\\\\ProgramData\";assert os.environ[\"SystemDrive\"]==\"C:\";assert \"OPENGEUL_FAKE_CREDENTIAL\" not in os.environ;print(\"OS fields propagated\")') '"+tmp+"' '"+str(prefix)+"' -ChildEnvironment $child -TimeoutMinutes 1|Out-Null;if($env:OPENGEUL_FAKE_CREDENTIAL -cne 'must-stay-parent' -or $env:ALLUSERSPROFILE -cne 'C:\\ProgramData' -or $env:SystemDrive -cne 'C:'){throw 'parent changed'}")
            self.assertIn('OS fields propagated',Path(str(prefix)+'.stdout.log').read_text())

    def test_requested_property_aliases_have_distinct_windows_evidence_paths(self):
        ps=PowerShellControlTests()
        with tempfile.TemporaryDirectory() as tmp:
            ps.ps("$cases=@(Get-PythonControlPropertyCases);if(($cases.requested -join ',') -cne 'default,x86,ARM64,arm64'){throw 'Requested values changed'};$seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase);foreach($case in $cases){$paths=New-PythonControlMeasurementPaths '"+tmp+"' $case;if(-not $seen.Add($paths.prefix)){throw 'Windows path alias'};Set-Content -LiteralPath ($paths.prefix+'.command.json') -Value '{}'};if($seen.Count -ne 4){throw 'Expected four real invocations'}")

    def test_preexisting_measurement_receipt_cannot_be_accepted_as_current(self):
        ps=PowerShellControlTests()
        with tempfile.TemporaryDirectory() as tmp:
            ps.ps("$case=@(Get-PythonControlPropertyCases)[2];$paths=New-PythonControlMeasurementPaths '"+tmp+"' $case;Set-Content ($paths.prefix+'.command.json') 'original receipt';$rejected=$false;try{New-PythonControlMeasurementPaths '"+tmp+"' $case|Out-Null}catch{$rejected=$true};if(-not $rejected -or (Get-Content ($paths.prefix+'.command.json') -Raw).Trim() -cne 'original receipt'){throw 'Existing receipt accepted or altered'}")

class ActualControlThreeAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        SPEC.loader.exec_module(control)
        cls.fixture=json.loads((ROOT/'suite/diagnostics/native-python/control3-baseline-fixture.json').read_text())
        cls.log='\n'.join(row['raw'] for row in cls.fixture['lines'])
        cls.inventory=cls.fixture['inventory']

    def test_actual_tracker_wrappers_bind_child_tools_and_separate_freeze_helper(self):
        binding=control.bind_tools(self.log,'baseline',self.inventory)
        self.assertEqual(len(binding),2)
        self.assertTrue(hasattr(control,'tool_commands'),'Executable-token parser missing')
        commands=control.tool_commands(self.log)
        self.assertTrue(any(c['origin']=='tracker-child' for c in commands))
        self.assertTrue(all('.exe /' not in c['path'] for c in commands))
        self.assertTrue(any('/x64/' in c['path'].replace('\\','/').lower() and ' /Od ' in c['arguments'] for c in commands))
        wrapped=next(row['raw'] for row in self.fixture['lines'] if 'Tracker.exe' in row['raw'] and 'HostX86\\arm64\\CL.exe' in row['raw'])
        bad=wrapped.replace(self.inventory['toolsRoot'],'C:\\UnselectedVS')
        with self.assertRaises(ValueError):control.bind_tools(self.log.replace(wrapped,bad),'baseline',self.inventory)


    def test_exact_observed_unicode_heap_site_is_variant_never_original_reproduction(self):
        proof=control.admit_build(self.log,1,'baseline',self.inventory)
        self.assertEqual(proof['status'],'observed-heap-site-variant')
        self.assertFalse(proof['originalSiteReproduced']);self.assertFalse(proof['causalCorrectionProven'])
        self.assertEqual(proof['observedHeapSite'],'Objects/unicodetype_db.h(4295)')
        for bad in [self.log.replace('unicodetype_db.h(4295)','unicodetype_db.h(4296)'),self.log.replace('unicodetype_db.h(4295)','other.h(4295)'),self.log.replace('1 Error(s)','11 Error(s)'),self.log+'\nerror MSB4018: unrelated',self.log+'\nHacl_Hash_SHA2.c(243): fatal error C1002: compiler is out of heap space in pass 2']:
            with self.assertRaises(ValueError):control.admit_build(bad,1,'baseline',self.inventory)
        for code in [2,3221225477]:
            with self.assertRaises(ValueError):control.admit_build(self.log,code,'baseline',self.inventory)

    def candidate_model(self):
        # Test-only routing model; no native candidate execution claim.
        import re
        rows=[]
        for row in self.fixture['lines']:
            text=row['raw']
            if re.search(r'fatal error|32-bit linker|restarting link|FAILED|1 Error\(s\)',text,re.I):continue
            rows.append(re.sub(r'HostX86([\\/])arm64',r'Hostarm64\1arm64',text,flags=re.I))
        return '\n'.join(rows)+'\nBuild succeeded.\n0 Error(s)'

    def test_candidate_product_flags_exclude_only_authentic_x64_freeze_helper(self):
        log=self.candidate_model()
        proof=control.admit_build(log,0,'candidate',self.inventory)
        self.assertEqual(proof['status'],'passed')
        self.assertTrue(proof['buildHostHelpers'])
        self.assertTrue(any('/Od' in c['arguments'] for c in proof['buildHostHelpers']))
        borrowed=log.replace('/GL','').replace('HostX86\\x64\\CL.exe /c','HostX86\\x64\\CL.exe /c /GL')
        for bad in [borrowed,log.replace('/O2','/Od'),log.replace('Hostarm64','HostX86'),log.replace('_freeze_module','other_helper'),log.replace('VC\\Tools\\MSVC','Different\\Tools\\MSVC')]:
            with self.assertRaises(ValueError):control.admit_build(bad,0,'candidate',self.inventory)

    def test_actual_product_link_inputs_exclude_tracking_and_property_tokens(self):
        self.assertTrue(hasattr(control,'link_input_evidence'),'Scoped product Link input parser missing')
        expected=control.expected_inputs(ROOT/'suite/diagnostics/native-python')
        evidence=control.link_input_evidence(self.log,self.inventory['productSourceRoot'],expected)
        self.assertEqual(evidence['inputCount'],235)
        polluted=self.log+'\npythoncore\\%(Filename).res\npythoncore\\pythoncore.vcxproj.res\npythoncore\\a.obj|b.obj'
        self.assertEqual(control.link_input_evidence(polluted,self.inventory['productSourceRoot'],expected)['inputs'],evidence['inputs'])
        for bad in [self.log.replace('getpath.obj"','extra.obj"'),self.log.replace('getpath.obj"','getpath.obj" \"extra.obj\"')]:
            with self.assertRaises(ValueError):control.link_input_evidence(bad,self.inventory['productSourceRoot'],expected)

    def test_variant_finalizer_retains_candidate_feasibility_and_fails_strict_workflow(self):
        PowerShellControlTests().ps("$r=[ordered]@{passed=$false;causalCorrectionProven=$false;stage='runtime'};$failed=$false;try{Complete-PythonControlResult $r @{status='observed-heap-site-variant';originalSiteReproduced=$false} @{status='passed'} @{testsPassed=$true}}catch{$failed=$true};if(-not $failed -or $r.passed -or $r.causalCorrectionProven -or $r.originalSiteReproduced -or -not $r.candidateFeasible){throw 'Variant admitted as original causal success'}")

class ReviewedActualParserGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        SPEC.loader.exec_module(control)
        cls.fixture=json.loads((ROOT/'suite/diagnostics/native-python/control3-baseline-fixture.json').read_text())
        cls.log='\n'.join(r['raw'] for r in cls.fixture['lines']);cls.inventory=cls.fixture['inventory']

    def test_unknown_tracker_child_rejects_and_actual_sdk_rc_scope_is_retained(self):
        bad=self.log.replace('HostX86\\arm64\\CL.exe"','HostX86\\arm64\\unknown.exe"')
        with self.assertRaises(ValueError):control.admit_build(bad,1,'baseline',self.inventory)
        proof=control.admit_build(self.log,1,'baseline',self.inventory)
        self.assertTrue(proof['resourceCompilers'])
        self.assertTrue(all(c['path'].lower().endswith('rc.exe') for c in proof['resourceCompilers']))
        for bad in [self.log.replace('10.0.26100.0\\x86\\rc.exe','10.0.99999.0\\x86\\rc.exe'),self.log.replace('python_nt.res"','other.res"')]:
            with self.assertRaises(ValueError):control.admit_build(bad,1,'baseline',self.inventory)

    def test_each_product_cl_and_link_preserves_its_own_required_flags(self):
        import re
        def candidate_model(log):
            rows=[]
            for text in log.split('\n'):
                if re.search(r'fatal error|32-bit linker|restarting link|FAILED|1 Error\(s\)',text,re.I):continue
                rows.append(re.sub(r'HostX86([\\/])arm64',r'Hostarm64\1arm64',text,flags=re.I))
            return '\n'.join(rows)+'\nBuild succeeded.\n0 Error(s)'
        self.assertEqual(control.admit_build(candidate_model(self.log),0,'candidate',self.inventory)['status'],'passed')
        for rows,flags in [({230271,230273},['/O2','/GL','/MP','/Zm200']),({298312},['/LTCG','/MACHINE:ARM64'])]:
            for flag in flags:
                changed='\n'.join(r['raw'].replace(flag,'') if r['physicalLf'] in rows else r['raw'] for r in self.fixture['lines'])
                with self.assertRaises(ValueError,msg=flag+' baseline'):control.admit_build(changed,1,'baseline',self.inventory)
                with self.assertRaises(ValueError,msg=flag+' candidate'):control.admit_build(candidate_model(changed),0,'candidate',self.inventory)

    def test_link_argv_counts_unquoted_inputs_and_rejects_relative_extra_duplicate_response(self):
        expected=control.expected_inputs(ROOT/'suite/diagnostics/native-python');e=control.link_input_evidence(self.log,self.inventory['productSourceRoot'],expected)
        first=next(r['raw'] for r in self.fixture['lines'] if r['physicalLf']==298312)
        for suffix in [' extra.obj',' "extra.obj"',' '+e['absoluteInputs'][0],' @unretained.rsp',' "@unretained.rsp"']:
            changed=self.log.replace(first,first.rstrip('\r')+suffix+'\r')
            with self.assertRaises(ValueError,msg=suffix):control.link_input_evidence(changed,self.inventory['productSourceRoot'],expected)
        last=next(r['raw'] for r in self.fixture['lines'] if r['physicalLf']==298546)
        moved=last.replace(' (TaskId:210)','')+'\n                     extra.obj (TaskId:210)\r'
        with self.assertRaises(ValueError):control.link_input_evidence(self.log.replace(last,moved),self.inventory['productSourceRoot'],expected)
        unquoted=self.log.replace('"'+e['absoluteInputs'][0]+'"',e['absoluteInputs'][0],1)
        self.assertEqual(control.link_input_evidence(unquoted,self.inventory['productSourceRoot'],expected)['inputCount'],235)
