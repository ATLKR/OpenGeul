"""Execute portable PowerShell boundaries; never claim Windows compiler proof."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest

from suite.tests.test_native_crt_probe import OwnedInheritedPipeFixture

SOURCE=Path(__file__).resolve().parents[1]/'scripts/build-native-engine.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


def quote(value): return "'"+str(value).replace("'","''")+"'"


class NativeEngineBuildTests(unittest.TestCase):
    def _x64_source_hook_fixture(self):
        import hashlib
        from suite.tests.test_native_source_recipe import load
        module = load('apply_native_source'); engine = SOURCE.parents[1] / 'engine-build'
        lock = json.loads((engine / 'source-build.json').read_bytes())
        self.assertIn('windowsZstdSourceLinks', lock)
        plan = module._select_plan(lock, (engine / 'native-targets.json').read_bytes(), 'x64')
        source = self.root / 'source'; evidence = self.root / 'evidence'; evidence.mkdir()
        for name, fixture in [('external/firebird/ExternalProject_firebird.mk', 'native-icu-path/ExternalProject_firebird.mk'),
                              ('external/zstd/UnpackedTarball_zstd.mk', 'native-zstd-unpack/UnpackedTarball_zstd.mk'),
                              ('solenv/gbuild/platform/com_MSC_defs.mk', 'native-gpg-build-compiler/com_MSC_defs.mk'),
                              ('external/harfbuzz/ExternalProject_harfbuzz.mk', 'native-meson-path/ExternalProject_harfbuzz.mk')]:
            target = source / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((SOURCE.parents[1] / 'tests/fixtures' / fixture).read_bytes())
        loader = module._install_firebird_loader_path(source, evidence, lock['windowsFirebirdLoaderPath'])
        zstd = module._install_zstd_source_links(source, evidence, lock['windowsZstdSourceLinks'])
        gpg = module._install_gpg_build_compiler_path(source, evidence, lock['windowsGpgBuildCompilerPath'])
        for pin in lock['windowsAtlNativePaths']['recipes']:
            relative = pin['path']
            fixture = ('native-atl-path/Library_so_activex.mk' if relative == 'extensions/Library_so_activex.mk'
                       else 'native-atl-consumers/'+relative)
            target = source/relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((SOURCE.parents[1]/'tests/fixtures'/fixture).read_bytes())
        atl = module._install_atl_native_paths(source, evidence, lock['windowsAtlNativePaths'])
        harfbuzz = module._install_harfbuzz_native_meson_paths(source, evidence, lock['windowsHarfbuzzNativeMesonPaths'])
        good = dict(sourcePortManifestSha256=hashlib.sha256((engine / 'source-build.json').read_bytes()).hexdigest(),
                    nativeTargetsSha256=hashlib.sha256((engine / 'native-targets.json').read_bytes()).hexdigest(),
                    sourceHooks=dict(kind='native-windows-common-source-hooks', architecture='x64',
                                     firebirdLoaderPath=loader, zstdSourceLinks=zstd, gpgBuildCompilerPath=gpg, atlNativePaths=atl,
                                     harfbuzzNativeMesonPaths=harfbuzz),
                    sourceRecipeProof=dict(schemaVersion=1, kind='native-engine-source-recipe-install', architecture='x64',
                        recipeId=plan['recipeId'], hookOrder=plan['recipe']['hooks'],
                        policySha256=hashlib.sha256((engine / 'native-targets.json').read_bytes()).hexdigest(),
                        manifestSha256=hashlib.sha256((engine / 'source-build.json').read_bytes()).hexdigest(),
                        recipeSha256=hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest(),
                        armGuardedSources=[dict(path=row['path'], beforeSha256=row['beforeSha256'],
                                               sha256=row['beforeSha256'], unchanged=True) for row in plan['armGuardedSources']],
                        nativeBuildVerified=False, fullEngineQualified=False, acceptanceEligible=False, guiVerified=False))
        return module, lock, source, evidence, good

    def _assert_x64_source_hook_binding(self,hook):
        import copy
        _, _, _, _, good = self._x64_source_hook_fixture()
        path = self.root / 'receipt.json'; path.write_text(json.dumps(good))
        call = f"Assert-NativeSourceRecipeBinding (Get-Content {quote(path)} -Raw|ConvertFrom-Json) x64"
        self.ps(call)
        selected=good['sourceHooks'][hook]
        for field, value in [('schemaVersion', True), ('kind', 'other'), ('path', '../escape'), ('condition', 'WNT_AARCH64'),
                             ('condition', ['WNT_X86_64']), ('beforeSha256', [selected['beforeSha256']]),
                             ('beforeBytes', True), ('afterBytes', 1.5), ('beforeSha256', '0' * 64),
                             ('afterSha256', '0' * 64), ('nativeBuildVerified', 0), ('fullEngineQualified', True),
                             ('acceptanceEligible', True), ('guiVerified', True), ('evidence', {}),
                             ('evidence', dict(selected['evidence'], extra=selected['evidence']['original'])), ('extra', False)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(good); changed['sourceHooks'][hook][field] = value
                path.write_text(json.dumps(changed)); self.rejected(call)
        changed = copy.deepcopy(good); changed['sourceHooks'].pop(hook)
        path.write_text(json.dumps(changed)); self.rejected(call)
        path.write_text(json.dumps(good))
        for phase in ('original', 'effective'):
            with self.subTest(phase=phase):
                retained = Path(selected['evidence'][phase]); raw = retained.read_bytes()
                retained.unlink(); self.rejected(call)
                retained.write_bytes(raw + b'changed'); self.rejected(call)
                retained.write_bytes(raw)

    def test_x64_zstd_binding_rejects_malformed_proof_or_missing_evidence(self):
        self._assert_x64_source_hook_binding('zstdSourceLinks')

    def test_x64_gpg_binding_rejects_malformed_proof_or_missing_evidence(self):
        self._assert_x64_source_hook_binding('gpgBuildCompilerPath')

    def test_x64_harfbuzz_binding_rejects_malformed_proof_or_missing_evidence(self):
        self._assert_x64_source_hook_binding('harfbuzzNativeMesonPaths')

    def test_x64_harfbuzz_binding_requires_canonical_loader_parent_and_exact_plan(self):
        import copy
        _, _, _, evidence, good = self._x64_source_hook_fixture()
        packet=self.root/'harfbuzz-receipt.json'
        call=f'Assert-NativeSourceRecipeBinding (Get-Content {quote(packet)} -Raw|ConvertFrom-Json) x64'
        packet.write_text(json.dumps(good));self.ps(call)
        selected=good['sourceHooks']['harfbuzzNativeMesonPaths']
        variants=[]
        for field,value in [('beforeBytes',str(selected['beforeBytes'])),('afterBytes',str(selected['afterBytes'])),
                            ('path',[selected['path']]),('kind',[selected['kind']])]:
            changed=copy.deepcopy(good);changed['sourceHooks']['harfbuzzNativeMesonPaths'][field]=value;variants.append(changed)
        for flag in ('nativeBuildVerified','fullEngineQualified','acceptanceEligible','guiVerified'):
            changed=copy.deepcopy(good);changed['sourceHooks']['harfbuzzNativeMesonPaths'][flag]=0;variants.append(changed)
        changed=copy.deepcopy(good);changed['sourceRecipeProof']['recipeSha256']='0'*64;variants.append(changed)
        changed=copy.deepcopy(good);changed['sourceRecipeProof']['hookOrder'].remove('harfbuzzNativeMesonPaths');variants.append(changed)
        other=self.root/'other-evidence';other.mkdir()
        for phase in ('original','effective'):
            original=Path(selected['evidence'][phase]);(other/original.name).write_bytes(original.read_bytes())
        changed=copy.deepcopy(good);changed['sourceHooks']['harfbuzzNativeMesonPaths']['evidence']={phase:str(other/Path(path).name) for phase,path in selected['evidence'].items()};variants.append(changed)
        for phase in ('original','effective'):
            changed=copy.deepcopy(good);original=Path(selected['evidence'][phase])
            changed['sourceHooks']['harfbuzzNativeMesonPaths']['evidence'][phase]=str(evidence/'..'/evidence.name/original.name);variants.append(changed)
            alternate=evidence/('other-'+original.name);alternate.write_bytes(original.read_bytes())
            changed=copy.deepcopy(good);changed['sourceHooks']['harfbuzzNativeMesonPaths']['evidence'][phase]=str(alternate);variants.append(changed)
        for index,changed in enumerate(variants):
            with self.subTest(mutation=index):packet.write_text(json.dumps(changed));self.rejected(call)

    def test_x64_harfbuzz_manifest_descriptor_is_closed_and_typed(self):
        _, _, _, _, good = self._x64_source_hook_fixture()
        packet=self.root/'harfbuzz-receipt.json';packet.write_text(json.dumps(good))
        engine=SOURCE.parents[1]/'engine-build'
        self.ps(f'Assert-NativeSourceRecipeBinding (Get-Content {quote(packet)} -Raw|ConvertFrom-Json) x64')
        for mutation in ("$pin|Add-Member -NotePropertyName unexpected -NotePropertyValue 0", "$pin.size=[string]$pin.size", "$pin.afterSize=[string]$pin.afterSize",
                         "$pin.sha256=@($pin.sha256)", "$pin.path=@($pin.path)", "$pin.condition='WNT_X86_64'"):
            body=f"""
$receipt=Get-Content {quote(packet)} -Raw|ConvertFrom-Json
$manifest=Get-Content {quote(engine/'source-build.json')} -Raw|ConvertFrom-Json
$pin=$manifest.windowsHarfbuzzNativeMesonPaths;{mutation}
$encoded=$manifest|ConvertTo-Json -Depth 40 -Compress
function Get-Content {{param($LiteralPath,[switch]$Raw) $encoded}}
Assert-NativeSourceRecipeBinding $receipt x64
"""
            with self.subTest(mutation=mutation):self.rejected(body)

    def test_x64_atl_group_binding_rejects_malformed_or_missing_recipe_evidence(self):
        import copy
        _, _, _, _, good = self._x64_source_hook_fixture()
        packet = self.root/'atl-receipt.json'
        call = f'Assert-NativeSourceRecipeBinding (Get-Content {quote(packet)} -Raw|ConvertFrom-Json) x64'
        packet.write_text(json.dumps(good)); self.ps(call)
        cases = []
        for field, value in [('schemaVersion', True), ('kind', 'other'), ('condition', 'WNT_AARCH64'),
                             ('nativeBuildVerified', 0), ('fullEngineQualified', True), ('acceptanceEligible', None), ('guiVerified', True), ('extra', False)]:
            changed=copy.deepcopy(good);changed['sourceHooks']['atlNativePaths'][field]=value;cases.append(changed)
        changed=copy.deepcopy(good);changed['sourceHooks'].pop('atlNativePaths');cases.append(changed)
        for mutation in ('missing','extra','reorder'):
            changed=copy.deepcopy(good);rows=changed['sourceHooks']['atlNativePaths']['recipes']
            if mutation=='missing':rows.pop()
            elif mutation=='extra':rows.append(copy.deepcopy(rows[0]))
            else:rows[0],rows[1]=rows[1],rows[0]
            cases.append(changed)
        for field, value in [('path','../escape'),('beforeBytes',True),('afterBytes',1.5),('beforeSha256',['0'*64]),('afterSha256','0'*64),('evidence',{}),('extra',False)]:
            changed=copy.deepcopy(good);changed['sourceHooks']['atlNativePaths']['recipes'][0][field]=value;cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(packet=index):packet.write_text(json.dumps(changed));self.rejected(call)
        packet.write_text(json.dumps(good))
        for index, row in enumerate(good['sourceHooks']['atlNativePaths']['recipes']):
            for phase in ('original','effective'):
                with self.subTest(recipe=index,phase=phase):
                    path=Path(row['evidence'][phase]);raw=path.read_bytes();path.unlink();self.rejected(call)
                    path.write_bytes(raw+b'changed');self.rejected(call);path.write_bytes(raw)

    def test_x64_atl_final_source_binding_checks_all_six_actual_outputs(self):
        _, lock, source, _, _ = self._x64_source_hook_fixture()
        engine=SOURCE.parents[1]/'engine-build'
        execute=f"""
$source={quote(source)};$manifest=Get-Content {quote(engine/'source-build.json')} -Raw|ConvertFrom-Json
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
$loops=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.ForEachStatementAst] -and $n.Condition.Extent.Text -ceq '$manifest.windowsAtlNativePaths.recipes'}},$true))
if($errors.Count -or $loops.Count -ne 1){{throw 'Expected one final finite ATL source check'}}
Invoke-Expression $loops[0].Extent.Text
"""
        self.ps(execute)
        for pin in lock['windowsAtlNativePaths']['recipes']:
            target=source/pin['path'];raw=target.read_bytes();target.write_bytes(raw+b'changed')
            with self.subTest(recipe=pin['path']):self.rejected(execute)
            target.write_bytes(raw)

    def _harfbuzz_cygwin_gate(self, architecture='x64', failure=False, expired=False):
        commands=self.root/'commands';commands.mkdir(exist_ok=True)
        repo=self.root/'repo with space';repo.mkdir(exist_ok=True)
        source=self.root/'pristine source';source.mkdir(exist_ok=True)
        body=f"""
$Architecture={quote(architecture)};$receipt=[ordered]@{{}};$commands={quote(commands)}
$unixRepo={quote(repo)};$unixSource={quote(source)};$work={quote(self.root)};$evidence={quote(self.root)}
$bash='owned-bash';$cygpath='owned-cygpath';$script:calls=0;$script:budgetCalls=0
function Assert-NativeBuildTimeRemaining {{$script:budgetCalls++;if(${str(expired).lower()}){{throw 'expired original test budget'}}}}
function Invoke-CygwinScript {{param($Bash,$Cygpath,$Script,$WorkingDirectory,$LogPrefix) $script:calls++;if(${str(failure).lower()}){{throw 'owned replay failed'}}}}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
$blocks=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.IfStatementAst] -and
 $n.Clauses[0].Item1.Extent.Text -ceq "`$Architecture -ceq 'x64'" -and $n.Extent.Text.Contains("`$receipt.stage='real-x64-harfbuzz-native-meson-tests'")}},$true))
if($errors.Count -or $blocks.Count -ne 1){{throw 'Expected one x64 pristine HarfBuzz replay gate'}}
$rejected=$false;try{{Invoke-Expression $blocks[0].Extent.Text}}catch{{$rejected=$true}}
[ordered]@{{calls=$script:calls;budgetCalls=$script:budgetCalls;rejected=$rejected;recorded=$receipt.Contains('harfbuzzNativeMesonReplayChecksExecuted');passed=$receipt.harfbuzzNativeMesonReplayChecksExecuted}}|ConvertTo-Json -Compress
"""
        return json.loads(self.ps(body)),commands/'x64-harfbuzz-source-gate.sh',repo,source

    def test_x64_harfbuzz_cygwin_gate_requires_success_in_original_budget_before_hooks(self):
        good,script,_,_=self._harfbuzz_cygwin_gate()
        self.assertEqual(dict(calls=1,budgetCalls=1,rejected=False,recorded=True,passed=True),good)
        self.assertTrue(script.is_file())
        arm,_,_,_=self._harfbuzz_cygwin_gate('arm64')
        self.assertEqual(dict(calls=0,budgetCalls=0,rejected=False,recorded=False,passed=None),arm)
        failed,_,_,_=self._harfbuzz_cygwin_gate(failure=True)
        self.assertEqual(dict(calls=1,budgetCalls=1,rejected=True,recorded=False,passed=None),failed)
        expired,_,_,_=self._harfbuzz_cygwin_gate(expired=True)
        self.assertEqual(dict(calls=0,budgetCalls=1,rejected=True,recorded=False,passed=None),expired)
        raw=SOURCE.read_text();self.assertLess(raw.index("$receipt.stage='real-x64-harfbuzz-native-meson-tests'"),raw.index("$receipt.stage='install-authenticated-source-hooks'"))
        execute=f"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
$guards=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.IfStatementAst] -and
 $n.Clauses[0].Item1.Extent.Text.Contains('$receipt.harfbuzzNativeMesonReplayChecksExecuted -isnot [bool]')}},$true))
if($errors.Count -or $guards.Count -ne 1){{throw 'Expected one Full replay qualification guard'}}
$receipt=[ordered]@{{harfbuzzNativeMesonReplayChecksExecuted=$true}};Invoke-Expression $guards[0].Extent.Text
foreach($value in @($false,0,1,'true',$null)){{
 $receipt=[ordered]@{{harfbuzzNativeMesonReplayChecksExecuted=$value}};$rejected=$false
 try{{Invoke-Expression $guards[0].Extent.Text}}catch{{$rejected=$true}}
 if(-not $rejected){{throw 'Missing or untyped replay was qualified'}}
}}
$receipt=[ordered]@{{}};$rejected=$false;try{{Invoke-Expression $guards[0].Extent.Text}}catch{{$rejected=$true}}
if(-not $rejected){{throw 'Missing replay was qualified'}}
"""
        self.ps(execute)

    @unittest.skipIf(os.name == 'nt', 'Portable Bash runner; actual Cygwin replay is a separate Windows source gate')
    def test_x64_harfbuzz_cygwin_gate_rejects_skips_wrong_count_or_failed_tests(self):
        import sys
        _,script,repo,source=self._harfbuzz_cygwin_gate()
        text=script.read_text();self.assertIn('/usr/bin/python3 -',text)
        methods=[
            'test_x64_harfbuzz_native_meson_receives_exact_compiler_argv_and_native_package_list',
            'test_x64_harfbuzz_other_profiles_keep_original_argv_and_environment',
            'test_x64_harfbuzz_rejects_invalid_compilers_and_conversion_before_meson',
            'test_x64_harfbuzz_real_cygwin_uses_builtin_host_and_actual_path_conversion']
        expected=['suite.tests.test_native_source_recipe.ActualSourceRecipeTests.'+name for name in methods]
        receiver=f"""
import json,os
from pathlib import Path
from types import SimpleNamespace
assert os.environ.get('OPENGEUL_NATIVE_SOURCE_RECIPE_SOURCE')=={str(source)!r}
assert os.environ.get('OPENGEUL_NATIVE_SOURCE_RECIPE_REQUIRE_SOURCE')=='1'
assert os.environ.get('OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY')=='1'
class Loader:
 def loadTestsFromNames(self,names):
  assert names=={expected!r}
  return names
defaultTestLoader=Loader()
class TextTestRunner:
 def __init__(self,*args,**kwargs):pass
 def run(self,suite):
  row=json.loads(Path('controlled-result.json').read_text())
  return SimpleNamespace(testsRun=row['testsRun'],skipped=[0]*row['skipped'],wasSuccessful=lambda:row['success'])
"""
        (repo/'unittest.py').write_text(receiver)
        # Substitute only the controller interpreter for this portable test;
        # the generated production command remains the actual Cygwin Python.
        script.write_text(text.replace('/usr/bin/python3 -',shlex.quote(sys.executable)+' -',1))
        clean={'PATH':'/workspace/toolcache/opengeul-validation/powershell:/usr/bin:/bin',
            'XDG_CACHE_HOME':'/workspace/toolcache/opengeul-validation/cache',
            'XDG_CONFIG_HOME':'/workspace/toolcache/opengeul-validation/config',
            'XDG_DATA_HOME':'/workspace/toolcache/opengeul-validation/data','PYTHONUTF8':'1'}
        for count,skip,passed in ((4,0,True),(3,0,True),(4,1,True),(4,0,False)):
            (repo/'controlled-result.json').write_text(json.dumps(dict(testsRun=count,skipped=skip,success=passed)))
            result=subprocess.run(['/usr/bin/bash',str(script)],env=clean,capture_output=True,timeout=10)
            with self.subTest(testsRun=count,skipped=skip,success=passed):
                self.assertEqual(count==4 and skip==0 and passed,result.returncode==0)

    def test_x64_final_harfbuzz_source_mutation_is_rejected(self):
        _, _, source, _, _ = self._x64_source_hook_fixture()
        engine=SOURCE.parents[1]/'engine-build'
        execute=f"""
$source={quote(source)};$manifest=Get-Content {quote(engine/'source-build.json')} -Raw|ConvertFrom-Json
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.CommandAst] -and
 $n.GetCommandName() -eq 'Confirm-FileIdentity' -and $n.Extent.Text.Contains('$manifest.windowsHarfbuzzNativeMesonPaths.path')}},$true))
if($errors.Count -or $calls.Count -ne 1){{throw 'Expected one actual final HarfBuzz source identity check'}}
Invoke-Expression $calls[0].Extent.Text|Out-Null
"""
        self.ps(execute)
        target=source/'external/harfbuzz/ExternalProject_harfbuzz.mk'
        raw=target.read_bytes();target.write_bytes(raw+b'changed');self.rejected(execute)
        target.unlink();self.rejected(execute)

    def test_x64_final_gpg_source_mutation_is_rejected(self):
        from suite.tests.test_native_source_recipe import load
        module=load('apply_native_source');engine=SOURCE.parents[1]/'engine-build'
        lock=json.loads((engine/'source-build.json').read_bytes())
        source=self.root/'source';target=source/module.GPG_PATH;target.parent.mkdir(parents=True)
        target.write_bytes((SOURCE.parents[1]/'tests/fixtures/native-gpg-build-compiler/com_MSC_defs.mk').read_bytes())
        evidence=self.root/'evidence';evidence.mkdir()
        module._install_gpg_build_compiler_path(source,evidence,lock['windowsGpgBuildCompilerPath'])
        execute=f"""
$source={quote(source)};$manifest=Get-Content {quote(engine/'source-build.json')} -Raw|ConvertFrom-Json
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.CommandAst] -and
 $n.GetCommandName() -eq 'Confirm-FileIdentity' -and $n.Extent.Text.Contains('$manifest.windowsGpgBuildCompilerPath.path')}},$true))
if($errors.Count -or $calls.Count -ne 1){{throw 'Expected one actual final GPG source identity check'}}
Invoke-Expression $calls[0].Extent.Text|Out-Null
"""
        self.ps(execute);target.write_bytes(target.read_bytes()+b'changed');self.rejected(execute)

    def test_x64_final_zstd_source_mutation_is_rejected(self):
        from suite.tests.test_native_source_recipe import load
        module = load('apply_native_source'); engine = SOURCE.parents[1] / 'engine-build'
        lock = json.loads((engine / 'source-build.json').read_bytes())
        self.assertIn('windowsZstdSourceLinks', lock)
        source = self.root / 'source'; target = source / 'external/zstd/UnpackedTarball_zstd.mk'
        target.parent.mkdir(parents=True); target.write_bytes((SOURCE.parents[1] / 'tests/fixtures/native-zstd-unpack/UnpackedTarball_zstd.mk').read_bytes())
        evidence = self.root / 'evidence'; evidence.mkdir()
        module._install_zstd_source_links(source, evidence, lock['windowsZstdSourceLinks'])
        execute = f"""
$source={quote(source)};$manifest=Get-Content {quote(engine/'source-build.json')} -Raw|ConvertFrom-Json
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.CommandAst] -and
 $n.GetCommandName() -eq 'Confirm-FileIdentity' -and $n.Extent.Text.Contains('$manifest.windowsZstdSourceLinks.path')}},$true))
if($errors.Count -or $calls.Count -ne 1){{throw 'Expected one actual final zstd source identity check'}}
Invoke-Expression $calls[0].Extent.Text|Out-Null
"""
        self.ps(execute)
        target.write_bytes(target.read_bytes() + b'changed')
        self.rejected(execute)

    def test_x64_source_binding_requires_exact_loader_hook_and_four_unchanged_guards(self):
        import copy
        _, _, _, _, good = self._x64_source_hook_fixture()
        self.assertEqual(4, len(good['sourceRecipeProof']['armGuardedSources']))
        path = self.root / 'receipt.json'; path.write_text(json.dumps(good))
        call = f"Assert-NativeSourceRecipeBinding (Get-Content {quote(path)} -Raw|ConvertFrom-Json) x64"
        self.ps(call)
        bad = []
        for field, value in [('schemaVersion', True), ('kind', 'other'), ('path', '../escape'), ('condition', 'WNT_AARCH64'),
                             ('beforeBytes', 1), ('afterBytes', 1.5), ('beforeSha256', '0' * 64),
                             ('afterSha256', '0' * 64), ('nativeBuildVerified', True), ('nativeBuildVerified', 0), ('guiVerified', True),
                             ('acceptanceEligible', True), ('fullEngineQualified', True), ('unknown', False)]:
            changed = copy.deepcopy(good); changed['sourceHooks']['firebirdLoaderPath'][field] = value; bad.append(changed)
        changed = copy.deepcopy(good); changed['sourceRecipeProof']['hookOrder'] = ['moduleBootstrap', 'winAccFocusOrder']; bad.append(changed)
        changed = copy.deepcopy(good); changed['sourceRecipeProof']['armGuardedSources'].append(dict(good['sourceRecipeProof']['armGuardedSources'][0])); bad.append(changed)
        changed = copy.deepcopy(good); changed['sourceRecipeProof']['armGuardedSources'][0]['unchanged'] = False; bad.append(changed)
        for index, packet in enumerate(bad):
            with self.subTest(case=index):
                path.write_text(json.dumps(packet)); self.rejected(call)

    def test_crt_terms_snapshot_hash_and_url_match_selected_visual_studio(self):
        import hashlib
        path=self.root/'terms.html'
        for arch,year in [('arm64','2026'),('x64','2022')]:
            raw=('Visual Studio '+year+' REDIST.TXT VC\\redist').encode();path.write_bytes(raw)
            result=json.loads(self.ps(f"Assert-VcRedistributionTerms {quote(path)} {arch}|ConvertTo-Json -Compress"))
            self.assertEqual('https://learn.microsoft.com/en-us/visualstudio/releases/'+year+'/redistribution',result['url'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),result['sha256'])
            self.rejected(f"Assert-VcRedistributionTerms {quote(path)} "+('x64' if arch=='arm64' else 'arm64'))
        path.write_bytes(b'Visual Studio 2022');self.rejected(f"Assert-VcRedistributionTerms {quote(path)} x64")

    def test_x64_winacc_requires_actual_native_binary_hash_and_both_import_tables(self):
        import hashlib
        from suite.tests.test_payload import pe
        path=self.root/'program/winaccessibility.dll';path.parent.mkdir();path.write_bytes(pe(0x8664,dll=True))
        good=dict(path='program/winaccessibility.dll',machine=0x8664,role='nativeX64',size=path.stat().st_size,
                  sha256=hashlib.sha256(path.read_bytes()).hexdigest(),imports=dict(normal=['kernel32.dll'],delay=[]))
        proof=self.root/'winacc.json';proof.write_text(json.dumps(good))
        call=f"Assert-WinAccBinaryProof (Get-Content {quote(proof)} -Raw|ConvertFrom-Json) {quote(self.root)} x64"
        self.ps(call)
        for key,value in [('machine',0xaa64),('role','buildHostTool'),('sha256','0'*64),('size',0),('imports',{}),('imports',dict(normal=[],delay=[])),('imports',dict(normal=['kernel32.dll']))]:
            with self.subTest(key=key,value=value):
                proof.write_text(json.dumps(dict(good,**{key:value})));self.rejected(call)
        proof.write_text(json.dumps(good));path.unlink();self.rejected(call)

    def test_x64_failed_preflight_never_reaches_download_or_qualified_archive(self):
        work=self.root/'work';output=self.root/'evidence'
        self.ps("function Assert-NativeEngineEnvironment {param($Architecture)}; function Get-NativeBuildHost {param($Architecture) @{isWindows=$true;processMachine=0;nativeMachine=34404}}; "
                "function Get-SourceRunBinding {@{sourceCommit=('a'*40);sourceTree=('b'*40)}}; "
                "function Resolve-NativeJdk {@{home='synthetic'}}; function Resolve-Ant {@{home='synthetic'}}; "
                "function Invoke-NativeX64Preflight {throw 'owned preflight rejected'}; function Get-AuthenticatedDownload {throw 'DOWNLOAD MUST NOT RUN'}; "
                f"try{{Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4 -Architecture x64}}catch{{}}")
        receipt=json.loads((output/'source-build-receipt.json').read_text())
        self.assertEqual(2,receipt['schemaVersion']);self.assertEqual('x64',receipt['architecture'])
        self.assertIn('owned preflight rejected',receipt['error']);self.assertNotIn('DOWNLOAD MUST NOT RUN',receipt['error'])
        for field in ('passed','fullEngineQualified','acceptanceEligible','guiVerified'):self.assertIs(False,receipt[field])
        self.assertFalse(list(output.glob('*.zip')))

    def test_x64_base_requires_independent_native_generations_rows_and_original_retirement(self):
        import copy
        image=str(self.root/'runtime/program/soffice.bin')
        processes=[dict(role='uno-python',pid=10,processMachine=0,nativeMachine=0x8664)]
        retirement=[]
        for phase,pid in [('create',20),('reopen',30)]:
            host=dict(role='uno-host',pid=pid,processMachine=0,nativeMachine=0x8664,jobOwned=True,phase=phase,image=image,creationTime=pid*100)
            processes.append(host)
            member=dict(pid=pid,creationTime=pid*100,image=image,handleValue=pid+5,alive=True,exitCode=259)
            retirement.append(dict(phase=phase,handlesClosed=True,cleanup=dict(schemaVersion=1,kind='owned-engine-job-cleanup',
                gracefulQualified=True,forcedTermination=False,jobEmptyVerified=True,finalJobPids=[],launcherExitCode=0,
                errors=[],jobHandleValue=pid+7,expectedEngineImage=image,initialMembers=[member],finalMembers=[dict(member,alive=False,exitCode=0)])))
        good=dict(schemaVersion=2,passed=True,guiVerified=False,independentReopenVerified=True,nativeProcesses=processes,
                  rows=[dict(id=1,text='Engine-OpenGeul-base 한글',amount=42)],retirement=retirement)
        path=self.root/'base.json'
        call=f"Assert-BaseProof {quote(path)} -Architecture x64 -RuntimeRoot {quote(self.root/'runtime')}"
        path.write_text(json.dumps(good));self.ps(call+'|Out-Null')
        bad=[]
        for key,value in [('passed',False),('rows',[]),('independentReopenVerified',False),('schemaVersion',1),('retirement',[])]:
            bad.append(dict(good,**{key:value}))
        for field,value in [('handlesClosed',False),('cleanup',{})]:
            changed=copy.deepcopy(good);changed['retirement'][0][field]=value;bad.append(changed)
        for field,value in [('forcedTermination',True),('launcherExitCode',1),('jobEmptyVerified',False)]:
            changed=copy.deepcopy(good);changed['retirement'][0]['cleanup'][field]=value;bad.append(changed)
        for field,value in [('nativeMachine',0xaa64),('processMachine',0x8664),('image',str(self.root/'foreign/soffice.bin')),('creationTime',0)]:
            changed=copy.deepcopy(good);changed['nativeProcesses'][1][field]=value;bad.append(changed)
        changed=copy.deepcopy(good);changed['nativeProcesses'][2].update(pid=20,creationTime=2000);bad.append(changed)
        changed=copy.deepcopy(good);changed['retirement'][0]['cleanup']['finalMembers'][0]['exitCode']=1;bad.append(changed)
        for index,value in enumerate(bad):
            with self.subTest(case=index):
                path.write_text(json.dumps(value));self.rejected(call)

    def test_x64_native_host_product_and_archive_mode(self):
        from suite.tests.test_payload import pe
        self.ps("Assert-NativeBuildHost @{isWindows=$true;processMachine=0;nativeMachine=34404} x64")
        for machine,process in [(43620,0),(34404,34404),(34404,332)]:
            self.rejected(f"Assert-NativeBuildHost @{{isWindows=$true;processMachine={process};nativeMachine={machine}}} x64")
        path=self.root/'native.exe';path.write_bytes(pe(0x8664))
        data=json.loads(self.ps(f"Get-ProductPeIdentity {quote(path)} -Architecture x64|ConvertTo-Json -Compress"))
        self.assertEqual('nativeX64',data['role'])
        path.write_bytes(pe(0xaa64))
        self.rejected(f"Get-ProductPeIdentity {quote(path)} -Architecture x64")
        mode=json.loads(self.ps("Get-NativeEngineBuildMode Full -Architecture x64|ConvertTo-Json -Compress"))
        self.assertEqual('OpenGeul-Office-engine-x64.zip',mode['archive'])
        self.rejected('Get-NativeEngineBuildMode Full -Architecture x64 -CalcDispatchDiagnostic')

    def test_x64_crt_requires_all_nine_signed_files_and_actual_compiler_floor(self):
        from suite.crt import crt_names
        from suite.tests.test_payload import pe
        tools=self.root/'VS/VC/Tools/MSVC/14.44.35207';tools.mkdir(parents=True)
        metadata=self.root/'VS/VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt';metadata.parent.mkdir(parents=True);metadata.write_bytes(b'14.44.35207\r\n')
        redist=self.root/'VS/VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT';redist.mkdir(parents=True)
        for name in crt_names('x64'): (redist/name).write_bytes(pe(0x8664,dll=True))
        mock=self.crt_mock().replace('14.50.12350.0','14.44.35211.0').replace('14,50,12350,0','14,44,35211,0')
        call=f"Get-AppLocalCrtPlan {quote(tools)} v143 -Architecture x64"
        raw=self.ps(mock+call+'|ConvertTo-Json -Depth 12 -Compress')
        plan=json.loads(raw);self.assertEqual(9,len(plan['files']))
        self.assertEqual('14.44.35207.0',plan['minimumRuntimeVersion'])
        self.assertEqual('14.44.35211.0',plan['selectedFileVersionFloor'])
        for name in crt_names('x64'):
            path=redist/name;original=path.read_bytes();path.unlink()
            self.rejected(mock+call);path.write_bytes(original)
        self.rejected(mock.replace('14,44,35211,0','14,44,35206,0')+call)
        self.rejected(mock.replace("status='Valid'","status='NotSigned'")+call)
        (redist/'vcruntime140_1.dll').write_bytes(pe(0xaa64,dll=True))
        self.rejected(mock+call)

    def x64_crt_package_fixture(self):
        from suite.crt import crt_names
        from suite.tests.test_payload import pe
        tools=self.root/'VS/VC/Tools/MSVC/14.44.35207';tools.mkdir(parents=True)
        metadata=self.root/'VS/VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt';metadata.parent.mkdir(parents=True);metadata.write_bytes(b'14.44.35207\r\n')
        roots=[]
        for directory in ('14.44.35112','14.44.99999'):
            path=self.root/'VS/VC/Redist/MSVC'/directory/'x64/Microsoft.VC143.CRT';path.mkdir(parents=True);roots.append(path)
            for name in crt_names('x64'):(path/name).write_bytes(pe(0x8664,dll=True))
        mock=self.crt_mock().replace('14.50.12350.0','14.44.35211.0').replace('14,50,12350,0','14,44,35211,0')
        return tools,roots,mock

    def test_x64_crt_package_floor_uses_actual_files_and_deterministic_minimum(self):
        tools,roots,mock=self.x64_crt_package_fixture()
        call=f"Get-AppLocalCrtPlan {quote(tools)} v143 x64 '14.44.35207.0'"
        old_in_new=mock.replace('@(14,44,35211,0)',"$(if($Path -like '*99999*'){@(14,44,35206,0)}else{@(14,44,35211,0)})")
        plan=json.loads(self.ps(old_in_new+call+'|ConvertTo-Json -Depth 12 -Compress'))
        self.assertEqual(str(roots[0]),plan['sourceDirectory'])
        self.assertEqual('actual-signed-crt-files-v1',plan['selectionBasis'])
        self.assertEqual('14.44.35211.0',plan['selectedFileVersionFloor'])
        # Directory label alone cannot rescue old actual files.
        for file in roots[0].iterdir():file.unlink()
        self.rejected(old_in_new+call)
        from suite.tests.test_payload import pe
        from suite.crt import crt_names
        for name in crt_names('x64'):(roots[0]/name).write_bytes(pe(0x8664,dll=True))
        newer=mock.replace('@(14,44,35211,0)',"$(if($Path -like '*99999*'){@(14,44,35212,0)}else{@(14,44,35211,0)})")
        plan=json.loads(self.ps(newer+call+'|ConvertTo-Json -Depth 12 -Compress'))
        self.assertEqual(str(roots[1]),plan['sourceDirectory']);self.assertEqual('14.44.35212.0',plan['selectedFileVersionFloor'])
        one_lower=newer.replace("$Path -like '*99999*'","$Path -like '*99999*' -and [IO.Path]::GetFileName($Path) -cne 'vcruntime140.dll'")
        plan=json.loads(self.ps(one_lower+call+'|ConvertTo-Json -Depth 12 -Compress'))
        self.assertEqual(str(roots[0]),plan['sourceDirectory'])
        self.rejected(mock+call.replace('14.44.35207.0','14.44.35229.0'))

    def test_x64_crt_eligible_signature_or_machine_failure_has_no_fallback(self):
        from suite.tests.test_payload import pe
        tools,roots,mock=self.x64_crt_package_fixture()
        call=f"Get-AppLocalCrtPlan {quote(tools)} v143 x64 '14.44.35207.0'"
        bad=mock.replace("status='Valid'","status=$(if($Path -like '*99999*'){'NotSigned'}else{'Valid'})")
        self.rejected(bad+call)
        (roots[1]/'vcruntime140.dll').write_bytes(pe(0xaa64,dll=True));self.rejected(mock+call)
        (roots[1]/'vcruntime140.dll').write_bytes(b'bad PE');self.rejected(mock+call)

    def setUp(self):
        self.assertTrue(SOURCE.is_file(),'Native ARM64 source-build driver is missing')
        self.assertTrue(Path(PWSH).is_file(),'Portable PowerShell is required for command-boundary tests')
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(strict=True)

    def ps(self,body):
        script=self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+"\n"+body,encoding='utf-8')
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],text=True,capture_output=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def rejected(self,body):
        self.ps("$rejected=$false; try { "+body+" } catch { $rejected=$true }; if(-not $rejected){ throw 'Unsafe condition was accepted' }")

    def full_stage_caller(self, architecture, summary_kind):
        """Execute the actual Full stage statements at the logged-command boundary."""
        script=self.root/'full-stage-caller.ps1'
        body=r'''
$ErrorActionPreference='Stop'
$driver=__DRIVER__
$root=__ROOT__
$Architecture=__ARCHITECTURE__
$summaryKind=__SUMMARY_KIND__
$tokens=$null;$parseErrors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseFile($driver,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count -ne 0){throw 'Stage caller parse failed'}
$entry=@($tree.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-NativeEngineBuild'},$true))
if($entry.Count -ne 1){throw 'Stage caller function is ambiguous'}
$calls=@($entry[0].Body.FindAll({param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -ceq '$staged' -and
    @($node.Right.FindAll({param($child) $child -is [System.Management.Automation.Language.CommandAst] -and $child.GetCommandName() -ceq 'Invoke-LoggedCommand'},$true)).Count -eq 1
},$true))
if($calls.Count -ne 1){throw 'Stage caller assignment is ambiguous'}
$statements=@($calls[0].Parent.Statements)
$index=[Array]::IndexOf($statements,$calls[0])
if($index -lt 0 -or $index+2 -ge $statements.Count){throw 'Stage caller statements are incomplete'}
$summary=$statements[$index+1];$guard=$statements[$index+2]
if($summary -isnot [System.Management.Automation.Language.AssignmentStatementAst] -or
    $summary.Left.Extent.Text -cne '$receipt.installedRuntimeStage' -or
    @($summary.Right.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -ceq 'Get-Content'},$true)).Count -ne 1 -or
    $guard -isnot [System.Management.Automation.Language.IfStatementAst]){throw 'Stage caller summary guard is incomplete'}
$repo=Split-Path (Split-Path (Split-Path $driver -Parent) -Parent) -Parent
$source=Join-Path $root 'source';$instdir=Join-Path $root 'installed-runtime';$evidence=Join-Path $root 'evidence'
$stageHelper=Join-Path $repo 'suite/engine-build/stage_installed_runtime.py';$python='bounded-python'
$script:summaryPath=Join-Path $root 'stage-summary.json'
$compact=[ordered]@{passed=$true;runtimeRoot=$instdir}
switch($summaryKind){
    'matching' {$compact.architecture=$Architecture}
    'wrong' {$compact.architecture=if($Architecture -ceq 'x64'){'arm64'}else{'x64'}}
    'nonstring' {$compact.architecture=@($Architecture)}
    'missing' {}
    default {throw 'Unexpected summary fixture'}
}
$compact|ConvertTo-Json -Depth 4 -Compress|Set-Content -LiteralPath $script:summaryPath -Encoding utf8
$script:callCount=0;$script:arguments=@()
function Invoke-LoggedCommand {
    param($File,$Arguments,$WorkingDirectory,$Prefix)
    $script:callCount++;$script:arguments=@($Arguments)
    return @{stdout=$script:summaryPath}
}
$receipt=@{};$accepted=$false
$actual=($calls[0].Extent.Text,$summary.Extent.Text,$guard.Extent.Text)-join "`n"
try { & ([scriptblock]::Create($actual));$accepted=$true } catch {$accepted=$false}
$selectors=@(for($i=0;$i -lt $script:arguments.Count;$i++){if($script:arguments[$i] -ceq '--architecture'){$i}})
$matches=$selectors.Count -eq 1 -and $selectors[0]+1 -lt $script:arguments.Count -and $script:arguments[$selectors[0]+1] -ceq $Architecture
[ordered]@{accepted=$accepted;callCount=$script:callCount;selectorCount=$selectors.Count;selectorMatches=$matches}|ConvertTo-Json -Compress
'''
        for token,value in [('__DRIVER__',quote(SOURCE)),('__ROOT__',quote(self.root)),
                            ('__ARCHITECTURE__',quote(architecture)),('__SUMMARY_KIND__',quote(summary_kind))]:
            body=body.replace(token,value)
        script.write_text(body,encoding='utf-8')
        for name in ('stage-child-cache','stage-child-config','stage-child-data'):
            (self.root/name).mkdir(exist_ok=True)
        child_environment={'PATH':str(Path(PWSH).resolve(strict=True).parent),
            'XDG_CACHE_HOME':str(self.root/'stage-child-cache'),
            'XDG_CONFIG_HOME':str(self.root/'stage-child-config'),
            'XDG_DATA_HOME':str(self.root/'stage-child-data'),'PYTHONUTF8':'1'}
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],
            cwd=self.root,env=child_environment,text=True,capture_output=True,timeout=30)
        self.assertEqual(0,result.returncode,'The actual stage caller boundary did not complete')
        try:value=json.loads(result.stdout.strip())
        except (ValueError,TypeError):self.fail('The stage caller returned no numeric summary')
        self.assertEqual(set(value),{'accepted','callCount','selectorCount','selectorMatches'})
        self.assertIs(type(value['accepted']),bool);self.assertIs(type(value['selectorMatches']),bool)
        self.assertIs(type(value['callCount']),int);self.assertIs(type(value['selectorCount']),int)
        return value

    def test_full_stage_caller_child_environment_uses_selected_binary_and_owned_paths(self):
        from unittest.mock import patch
        selected=self.root/'selected PowerShell binary'/'pwsh.exe'
        selected.parent.mkdir();selected.write_bytes(b'synthetic selected binary')
        expected={'XDG_CACHE_HOME':self.root/'stage-child-cache',
            'XDG_CONFIG_HOME':self.root/'stage-child-config','XDG_DATA_HOME':self.root/'stage-child-data'}
        seen=[]
        def boundary(arguments,**options):
            child=options.get('env');values=child if type(child) is dict else {}
            checks={'closedFive':type(child) is dict and set(child)=={'PATH',*expected,'PYTHONUTF8'},
                'binarySelected':arguments[0]==str(selected),
                'pathSelected':values.get('PATH')==str(selected.resolve(strict=True).parent),
                'utf8':values.get('PYTHONUTF8')=='1','cwdOwned':options.get('cwd')==self.root}
            checks.update({key:values.get(key)==str(value) for key,value in expected.items()})
            seen.append(checks)
            return subprocess.CompletedProcess([],0,json.dumps(dict(accepted=True,callCount=1,
                selectorCount=1,selectorMatches=True)),'')
        with patch(__name__+'.PWSH',str(selected)),patch.object(subprocess,'run',side_effect=boundary):
            value=self.full_stage_caller('x64','matching')
        self.assertEqual(len(seen),1)
        self.assertTrue(all(seen[0].values()),'The stage child environment escaped its selected or owned paths')
        self.assertTrue(value['accepted'])

    def test_actual_full_stage_caller_passes_selected_architecture_once(self):
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture):
                value=self.full_stage_caller(architecture,'matching')
                self.assertEqual(value['callCount'],1)
                self.assertTrue(value['accepted'])
                self.assertEqual(value['selectorCount'],1)
                self.assertTrue(value['selectorMatches'])

    def test_actual_full_stage_caller_rejects_missing_wrong_or_nonstring_architecture(self):
        for architecture in ('x64','arm64'):
            for summary in ('missing','wrong','nonstring'):
                with self.subTest(architecture=architecture,summary=summary):
                    value=self.full_stage_caller(architecture,summary)
                    self.assertEqual(value['callCount'],1)
                    self.assertFalse(value['accepted'])

    def test_native_source_gate_requires_explicit_mdds_archive_and_existing_actual_source_module(self):
        script = self.root/'source-gate.sh'
        self.ps(f"Write-NativeSourceGate {quote(script)} '/owned/repo' '/owned/lo source' '/owned/firebird.tar.bz2' '/owned/mdds.tar.xz'")
        raw = script.read_text()
        parsed = [shlex.split(line) for line in raw.splitlines()]
        self.assertEqual([['/usr/bin/python3', '-m', 'unittest',
            'suite.tests.test_firebird_arm64_port', 'suite.tests.test_native_python_host',
            'suite.tests.test_native_atl_path', 'suite.tests.test_native_meson_path',
            'suite.tests.test_winacc_focus_order', '-v']],
            [argv for argv in parsed if argv and argv[0] == '/usr/bin/python3'])
        self.assertEqual([
            ['export', 'PATH=/usr/local/bin:/usr/bin:/bin:$PATH'],
            ['export', 'OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE=1'],
            ['export', 'OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY=1'],
            ['export', 'OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY=1'],
            ['export', 'OPENGEUL_FIREBIRD_SOURCE_ARCHIVE=/owned/firebird.tar.bz2'],
            ['export', 'OPENGEUL_MDDS_SOURCE_ARCHIVE=/owned/mdds.tar.xz'],
            ['export', 'OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES=/owned/lo source/external/firebird'],
            ['export', 'OPENGEUL_LIBREOFFICE_ATL_SOURCE=/owned/lo source'],
            ['export', 'OPENGEUL_LIBREOFFICE_MESON_SOURCE=/owned/lo source'],
            ['export', 'OPENGEUL_LIBREOFFICE_PYTHON_PATCHES=/owned/lo source/external/python3']],
            [argv for argv in parsed if argv and argv[0] == 'export'])
        bash = 'bash'
        if os.name == 'nt':
            git = shutil.which('git')
            self.assertIsNotNone(git, 'Git for Windows is required for the Bash syntax check')
            git_path = Path(git).resolve(strict=True)
            self.assertEqual('git.exe', git_path.name.casefold())
            self.assertIn(git_path.parent.name.casefold(), {'bin', 'cmd'})
            bash_path = git_path.parent.parent/'bin/bash.exe'
            self.assertTrue(bash_path.is_file(), 'Git for Windows Bash is required for the syntax check')
            bash = str(bash_path)
        result = subprocess.run([bash,'-n',str(script)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)
        atl_source = (SOURCE.parents[1]/'tests/test_native_atl_path.py').read_text()
        methods = re.findall(r'    def test_producer_mandates_actual_source_and_replay\(self\):\n(.*?)(?=\n    def |\n\nclass |\Z)',
                             atl_source,re.DOTALL)
        self.assertEqual(1,len(methods))
        self.assertNotRegex(methods[0],r'\b(?:subprocess|PWSH|test_native_engine_build)\b')
        self.assertNotRegex(methods[0],r'(?m)^\s*(?:import|from)\s')

    def test_winacc_source_patch_receipt_binds_all_sources_patch_and_retained_bytes(self):
        from suite.tests.test_winacc_focus_order import WinAccFocusOrderTests,CORE
        helper=WinAccFocusOrderTests();helper.setUp();self.addCleanup(helper.doCleanups)
        proof=helper.install();pin=helper.pin()
        proof_file=self.root/'winacc-proof.json';proof_file.write_text(json.dumps(proof))
        pin_file=self.root/'winacc-pin.json';pin_file.write_text(json.dumps(pin))
        load=f"$proof=Get-Content {quote(proof_file)} -Raw|ConvertFrom-Json; $pin=Get-Content {quote(pin_file)} -Raw|ConvertFrom-Json; "
        call=f"Assert-WinAccFocusSourcePatchReceipt $proof $pin '{CORE}' {quote(helper.evidence)}"
        self.ps(load+call)
        for field,value in (('passed',False),('coreCommit','0'*40),('afterSha256','0'*64),
                ('patchSha256','0'*64),('nativeBuildVerified',True),('guiVerified',True),
                ('currentCiRootCauseConfirmed',True)):
            changed=dict(proof,**{field:value});proof_file.write_text(json.dumps(changed))
            self.rejected(load+call)
        proof_file.write_text(json.dumps(proof))
        self.rejected(load+"$proof.sourceFiles[1].beforeSha256='"+'0'*64+"'; "+call)
        self.rejected(load+"$proof.sourceFiles=@($proof.sourceFiles[0],$proof.sourceFiles[0],$proof.sourceFiles[2]); "+call)
        (helper.evidence/'effective-AccObjectWinManager.cxx').write_bytes(b'synthetic evidence drift')
        self.rejected(load+call)

    def test_actual_mdds_header_retention_copies_owned_bytes_and_rejects_drift_or_links(self):
        import hashlib
        names = ['flat_segment_tree.hpp', 'flat_segment_tree_def.inl', 'node.hpp']
        source = self.root / 'source'; include = source / 'workdir/UnpackedTarball/mdds/include/mdds'
        include.mkdir(parents=True)
        lock = {'headers': [], 'nodeHeader': None}
        for name in names:
            raw = ('retention boundary '+name+'\n').encode(); (include/name).write_bytes(raw)
            item = {'path':'include/mdds/'+name, 'afterBytes':len(raw), 'afterSha256':hashlib.sha256(raw).hexdigest()}
            if name == 'node.hpp': lock['nodeHeader'] = item
            else: lock['headers'].append(item)
        pin = self.root/'mdds.json'; pin.write_text(json.dumps(lock))
        def retain(label):
            evidence = self.root/label; evidence.mkdir()
            result = json.loads(self.ps(f"Save-ActualMddsHeaders {quote(source)} {quote(evidence)} (Get-Content {quote(pin)} -Raw|ConvertFrom-Json)|ConvertTo-Json -Depth 8 -Compress"))
            return evidence,result
        evidence,result = retain('good')
        self.assertTrue(result['matchesExpected'])
        self.assertEqual(3,len(result['files']))
        for item in result['files']:
            self.assertEqual('retained',item['status'])
            self.assertEqual(Path(item['sourcePath']).read_bytes(),Path(item['evidencePath']).read_bytes())
            self.assertEqual(item['expectedSha256'],item['sha256'])
        (include/names[0]).write_bytes(b'drift')
        _,result = retain('drift');self.assertFalse(result['matchesExpected'])
        self.assertEqual('retained',result['files'][0]['status'])
        self.assertFalse(result['files'][0]['matchesExpected'])
        (include/names[0]).unlink()
        _,result = retain('missing');self.assertFalse(result['matchesExpected'])
        self.assertEqual('missing',result['files'][0]['status'])
        (include/names[0]).symlink_to(include/names[1])
        _,result = retain('linked');self.assertFalse(result['matchesExpected'])
        self.assertEqual('rejected',result['files'][0]['status'])
        self.assertFalse((self.root/'linked'/('actual-mdds-'+names[0])).exists())

    def test_native_host_requires_real_windows_arm64_and_unemulated_controller(self):
        self.ps("Assert-NativeBuildHost ([pscustomobject]@{isWindows=$true;processMachine=0;nativeMachine=43620})")
        for props in ("isWindows=$false;processMachine=0;nativeMachine=43620", "isWindows=$true;processMachine=34404;nativeMachine=43620", "isWindows=$true;processMachine=0;nativeMachine=34404"):
            self.rejected("Assert-NativeBuildHost ([pscustomobject]@{"+props+"})")

    def test_fresh_directories_refuse_existing_overlap_and_linked_parent(self):
        work=self.root/'work'; output=self.root/'output'
        self.ps(f"$paths=New-BuildDirectories {quote(work)} {quote(output)}; if(-not(Test-Path $paths.work)){{throw 'No owned work directory'}}")
        self.rejected(f"New-BuildDirectories {quote(work)} {quote(self.root/'fresh')}")
        self.rejected(f"New-BuildDirectories {quote(self.root/'outer')} {quote(self.root/'outer/inner')}")
        link=self.root/'link'
        try: link.symlink_to(work,target_is_directory=True)
        except (OSError,NotImplementedError): return
        self.rejected(f"New-BuildDirectories {quote(link/'new')} {quote(self.root/'another')}")

    def test_download_receipt_omits_redirect_capability_and_userinfo(self):
        result=self.ps("Get-DownloadReceiptLocation ([uri]'https://synthetic:password@example.invalid/package.zip?sig=synthetic-capability#fragment')")
        self.assertEqual('https://example.invalid/package.zip',result)
        result=self.ps("Get-DownloadReceiptLocation ([uri]'https://example.invalid/package.zip')")
        self.assertEqual('https://example.invalid/package.zip',result)

    def test_mutex_symbols_are_opt_in_and_keep_release_configuration(self):
        self.ps("""
$normal=@(Get-ConfigureArguments); $diagnostic=@(Get-ConfigureArguments -MutexSymbols)
if(@($normal|Where-Object {$_ -like '*symbols*'}).Count -ne 0) {throw 'Default symbols changed'}
if(@($diagnostic|Where-Object {$_ -ceq '--enable-symbols=Library_vclplug_win'}).Count -ne 1) {throw 'Exact symbol filter missing'}
$good=@{ENABLE_SYMBOLS_FOR='Library_vclplug_win';ENABLE_OPTIMIZED='TRUE';ENABLE_DEBUG='';ENABLE_DBGUTIL='';ENABLE_OPTIMIZED_DEBUG='';MSVC_USE_DEBUG_RUNTIME=''}
Assert-MutexSymbolsConfiguration $good
foreach($key in $good.Keys) {
  $bad=$good.Clone(); $bad[$key]='wrong'; $rejected=$false
  try { Assert-MutexSymbolsConfiguration $bad } catch { $rejected=$true }
  if(-not $rejected){throw 'Configuration drift admitted'}
  $bad=$good.Clone(); $bad.Remove($key); $rejected=$false
  try { Assert-MutexSymbolsConfiguration $bad } catch { $rejected=$true }
  if(-not $rejected){throw 'Missing configuration admitted'}
}
""")

    def test_mutex_symbols_require_exact_first_owner_push(self):
        self.ps("""
$ref='refs/heads/work/opengeul-office-native-engine'; $sha='a'*40
$context=@{GITHUB_ACTIONS='true';RUNNER_ENVIRONMENT='github-hosted';RUNNER_OS='Windows';RUNNER_ARCH='ARM64';GITHUB_REPOSITORY='ATLKR/OpenGeul';GITHUB_REPOSITORY_OWNER='ATLKR';GITHUB_EVENT_NAME='push';GITHUB_JOB='native-firebird-and-office';GITHUB_REF=$ref;GITHUB_WORKFLOW_REF=('ATLKR/OpenGeul/.github/workflows/office-native-engine.yml@'+$ref);GITHUB_RUN_ATTEMPT='1';GITHUB_ACTOR='ATLKR';GITHUB_ACTOR_ID='65988341';GITHUB_SHA=$sha;GITHUB_WORKFLOW_SHA=$sha;GITHUB_RUN_ID='123'}
$event=@{repository=@{full_name='ATLKR/OpenGeul';private=$false;id=1405493151};sender=@{login='ATLKR';id=65988341;type='User'};ref=$ref;deleted=$false;after=$sha}
Assert-MutexSymbolsOwnerPush $context $event
foreach($key in $context.Keys){
 $bad=$context.Clone();$bad[$key]='wrong';$rejected=$false
 try{Assert-MutexSymbolsOwnerPush $bad $event}catch{$rejected=$true}
 if(-not $rejected){throw 'Context drift admitted'}
}
foreach($key in @('ref','deleted','after','sender','repository')){
 $bad=$event.Clone();$bad.Remove($key);$rejected=$false
 try{Assert-MutexSymbolsOwnerPush $context $bad}catch{$rejected=$true}
 if(-not $rejected){throw 'Incomplete event admitted'}
}
""")

    def test_mutex_symbols_reject_ambient_build_overrides_without_disclosing_values(self):
        self.ps("""
Assert-MutexSymbolsOverrides @{}
foreach($key in @('MAKEFLAGS','MFLAGS','GNUMAKEFLAGS','MAKEOVERRIDES','enable_symbols','debug','dbglevel','enable_optimized','CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CL','_CL_','LINK','_LINK_')) {
 $rejected=$false
 try{Assert-MutexSymbolsOverrides @{$key='synthetic-private-value'}}catch{
  $rejected=$true
  if($_.Exception.Message.Contains('synthetic-private-value')){throw 'Override value leaked'}
 }
 if(-not $rejected){throw 'Ambient build override admitted'}
}
""")

    def test_mutex_symbols_reject_nonfull_before_directory_creation(self):
        work=self.root/'work';output=self.root/'output'
        self.rejected(f"Invoke-NativeEngineBuild Firebird {quote(work)} {quote(output)} '' 4 -MutexSymbols")
        self.assertFalse(work.exists());self.assertFalse(output.exists())

    def test_config_requires_native_firebird_not_just_successful_configure(self):
        config=self.root/'config_host.mk'
        good={'OS':'WNT','COM':'MSC','CPUNAME':'AARCH64','HOST_PLATFORM':'aarch64-pc-cygwin','BUILD_PLATFORM':'aarch64-pc-cygwin','WIN_HOST_ARCH':'arm64','WIN_BUILD_ARCH':'arm64','ENABLE_FIREBIRD_SDBC':'TRUE','SYSTEM_FIREBIRD':'','CROSS_COMPILING':'','BUILD_TYPE':'FIREBIRD ICU LIBATOMIC_OPS LIBTOMMATH','PKGFORMAT':'archive','ENABLE_ONLINE_UPDATE':'','ENABLE_ONLINE_UPDATE_MAR':'','ENABLE_BREAKPAD':''}
        def write(values): config.write_text(''.join(f'export {key}={value}\n' for key,value in values.items()))
        write({key:value for key,value in good.items() if key not in ('WIN_HOST_ARCH','WIN_BUILD_ARCH')})
        self.ps(f"$config=Assert-GeneratedConfiguration {quote(config)}; if($config.CPUNAME -ne 'AARCH64'){{throw 'Wrong parsed config'}}")
        for field,value in [('CPUNAME','X86_64'),('ENABLE_FIREBIRD_SDBC',''),('CROSS_COMPILING','TRUE'),('CROSS_COMPILING','yes'),('SYSTEM_FIREBIRD','TRUE'),('BUILD_TYPE','ICU'),('HOST_PLATFORM','x86_64-pc-cygwin')]:
            with self.subTest(field=field):
                write(dict(good,**{field:value}))
                self.rejected(f"Assert-GeneratedConfiguration {quote(config)}")

    def test_failure_receipt_and_config_logs_survive_native_host_rejection(self):
        work=self.root/'failed-work';output=self.root/'failed-evidence'
        self.ps(f"function Assert-NativeEngineEnvironment {{param($Architecture)}}; function Get-NativeBuildHost {{ throw 'observed wrong actual host' }}; try {{ Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4 }} catch {{ }}")
        receipt=json.loads((output/'source-build-receipt.json').read_text())
        self.assertFalse(receipt['passed'])
        self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('native-host',receipt['stage'])
        self.assertIn('observed wrong actual host',receipt['error'])
        self.assertFalse((output/'OpenGeul-Office-engine-arm64.zip').exists())

    def test_generated_native_base_probe_has_valid_python_syntax(self):
        probe=self.root/'probe.py'
        self.ps(f"Write-BaseProofScript {quote(probe)}")
        compile(probe.read_text(encoding='utf-8'),str(probe),'exec')

    def test_generated_native_base_probe_cleanup_tracks_installed_runtime_in_both_phases(self):
        import ast
        from suite.e2e import engine_smoke as smoke
        probe=self.root/'probe.py'
        self.ps(f"Write-BaseProofScript {quote(probe)}")
        tree=ast.parse(probe.read_text(encoding='utf-8'),str(probe))
        loops=[node for node in ast.walk(tree) if isinstance(node,ast.For)
               and isinstance(node.target,ast.Name) and node.target.id=='phase']
        self.assertEqual(1,len(loops))
        loop=loops[0]
        phases=ast.literal_eval(loop.iter)
        self.assertEqual(('create','reopen'),phases)
        setup_end=next(index for index,node in enumerate(loop.body) if isinstance(node,ast.Try))
        start=loop.body[setup_end].body[0].value
        self.assertIsInstance(start,ast.Call)
        self.assertEqual(('engine','start'),(start.func.value.id,start.func.attr))
        setup=compile(ast.Module(body=loop.body[:setup_end],type_ignores=[]),str(probe),'exec')
        runtime=self.root/'fixture-installed-runtime'
        for phase in phases:
            with self.subTest(phase=phase):
                scope=dict(smoke=smoke,repo=self.root/'fixture-repo',runtime=runtime,phase=phase)
                exec(setup,scope)
                engine=scope['engine']
                self.assertIsInstance(engine,smoke.Engine)
                self.assertEqual(runtime,engine.runtime)
                # Synthetic retained-member fixture only; no Windows process is launched.
                member=dict(pid=42,creationTime=123,handleValue=99,
                            image=str(runtime/'program/soffice.bin'),alive=True,exitCode=259)
                evidence=engine.cleanup_evidence
                evidence.update(jobHandleValue=11,gracefulQualified=True,jobEmptyVerified=True,
                                initialMembers=[member],finalMembers=[dict(member,alive=False,exitCode=0)],
                                finalJobPids=[],launcherExitCode=0)
                try:
                    self.assertIs(evidence,smoke.validate_cleanup_evidence(evidence))
                except ValueError as exc:
                    self.fail(str(exc))

    def test_recipe_explicit_native_triples_visual_studio_and_firebird_first(self):
        raw=self.ps("[pscustomobject]@{configure=@(Get-ConfigureArguments);firebird=@(Get-BuildTargets Firebird);full=@(Get-BuildTargets Full)}|ConvertTo-Json -Compress")
        data=json.loads(raw)
        for argument in ('--build=aarch64-pc-cygwin','--host=aarch64-pc-cygwin','--with-visual-studio=2026','--enable-firebird-sdbc','--without-system-firebird'):
            self.assertIn(argument,data['configure'])
        self.assertEqual(['ExternalProject_firebird','firebird'],data['firebird'])
        self.assertEqual(data['firebird']+['build'],data['full'])
        self.assertFalse(any('cross-build' in arg for arg in data['configure']))

    def test_bash_scripts_are_utf8_without_bom_or_windows_crlf(self):
        script=self.root/'actual.sh'
        self.ps(f"Write-BashScript {quote(script)} @('set -euo pipefail','printf bash-native-boundary')")
        data=script.read_bytes()
        self.assertNotIn(b'\r',data)
        self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
        if os.name!='nt':
            result=subprocess.run(['/bin/bash',str(script)],capture_output=True,text=True,timeout=5)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual('bash-native-boundary',result.stdout)

    def test_extra_source_modules_are_authenticated_and_cache_is_explicit(self):
        raw=self.ps("[pscustomobject]@{pins=@(Get-ExtraSourcePins);configure=@(Get-ConfigureArguments '/owned/source-cache')}|ConvertTo-Json -Depth 8 -Compress")
        data=json.loads(raw)
        self.assertEqual(3,len(data['pins']))
        self.assertEqual([53513324,62319860,236160656],[pin['size'] for pin in data['pins']])
        for pin in data['pins']:
            self.assertTrue(pin['url'].startswith('https://download.documentfoundation.org/libreoffice/src/26.8.1/'))
            self.assertEqual(64,len(pin['sha256']))
        self.assertIn('--with-external-tar=/owned/source-cache',data['configure'])

    def test_authenticated_source_uses_exact_official_url_size_and_hash(self):
        lock=SOURCE.parents[1]/'config/runtime.lock.json'
        data=json.loads(self.ps(f"Get-SourcePin {quote(lock)}|ConvertTo-Json -Compress"))
        self.assertEqual(302435508,data['size'])
        self.assertEqual('296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785',data['sha256'])
        self.assertEqual(json.loads(lock.read_text())['runtime']['sourceUrl'],data['url'])
        self.assertEqual('bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1',data.get('coreCommit'))
        bad=json.loads(lock.read_text()); bad['runtime']['sourceUrl']='https://example.org/renamed.tar.xz'
        path=self.root/'bad.json';path.write_text(json.dumps(bad))
        self.rejected(f"Get-SourcePin {quote(path)}")

    def build_identity_fixture(self, original='a'*40):
        import hashlib
        runtime=self.root/'runtime';program=runtime/'program';program.mkdir(parents=True)
        for name,section in (('version.ini','Version'),('setup.ini','Bootstrap')):
            (program/name).write_bytes(f'[{section}]\r\nbuildid={original}\r\nVendor=LibreOffice\r\n'.encode())
        archive=self.root/'source.tar.xz';archive.write_bytes(b'authenticated source archive fixture')
        pin={'url':'https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
             'version':'26.8.1.1','size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
             'coreCommit':'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'}
        fixture_size,fixture_hash=pin['size'],pin['sha256']
        if original=='680(Build:1)':
            pin.update(size=302435508,sha256='296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785')
        pin_path=self.root/'source-pin.json';pin_path.write_text(json.dumps(pin))
        evidence=self.root/'evidence';evidence.mkdir()
        self.refresh_identity_stage(runtime,evidence)
        config=self.root/'identity-config.json';config.write_text(json.dumps(dict(LIBO_VERSION_MAJOR='26',LIBO_VERSION_MINOR='8',LIBO_VERSION_MICRO='1',LIBO_VERSION_PATCH='1',LIBO_VERSION_SUFFIX='')))
        call=f"Set-RuntimeBuildIdentity {quote(runtime)} {quote(archive)} (Get-Content {quote(pin_path)} -Raw|ConvertFrom-Json) {quote('a'*40)} {quote(evidence)} (Get-Content {quote(config)} -Raw|ConvertFrom-Json -AsHashtable) (Get-Content {quote(self.root/'stage-summary.json')} -Raw|ConvertFrom-Json)"
        if original=='680(Build:1)':
            # Keep unit tests portable: only substitute the tiny archive fixture's
            # descriptor at the existing authentication boundary. The real hash
            # verifier still checks fixture bytes and all stage descriptors.
            call=("$verifier=${function:Confirm-FileIdentity}; function Confirm-FileIdentity($Path,$Size,$Algorithm,$Hash) { "
                  +f"if($Path -ceq {quote(archive)}) {{ if($Size -ne 302435508 -or $Hash -cne {quote(pin['sha256'])}) {{throw 'Source pin drift'}}; "
                  +f"& $verifier $Path {fixture_size} $Algorithm {quote(fixture_hash)} "
                  +"} else { & $verifier $Path $Size $Algorithm $Hash } }; "+call)
        return runtime,archive,pin_path,evidence,pin,call

    def refresh_identity_stage(self,runtime,evidence):
        import hashlib
        rows=[]
        for path in (runtime/'program').iterdir():
            raw=path.read_bytes()
            rows.append(dict(path='program/'+path.name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                             archivePath='main.zip',archiveMember='wrapper/program/'+path.name))
        stage=evidence/'installed-runtime-stage.json'
        stage.write_text(json.dumps(dict(schemaVersion=1,kind='source-built-installed-runtime-stage',passed=True,
            runtimeRoot=str(runtime),configuredProduct='LibreOfficeDev',configuredVersion='26.8.1.1',
            archives=[dict(kind='main',path='main.zip',wrapperRoot='wrapper')],files=rows)))
        (self.root/'stage-summary.json').write_text(json.dumps(dict(passed=True,runtimeRoot=str(runtime),
            receipt=dict(path=str(stage),bytes=stage.stat().st_size,sha256=hashlib.sha256(stage.read_bytes()).hexdigest()))))

    def test_accepts_authentic_reconstructed_installed_fallback(self):
        runtime,_,_,_,_,call=self.build_identity_fixture('680(Build:1)')
        # Authentic reconstructed setup profile, not recovered historical bytes.
        setup=runtime/'program/setup.ini'
        setup.write_bytes(b'[Bootstrap]\r\nbuildid=680(Build:1)\r\n')
        self.assertEqual('9d13ae895496c19d7702b77998d1c0f4ba0ab8e757c3a73671e87433eb227703',__import__('hashlib').sha256(setup.read_bytes()).hexdigest())
        self.refresh_identity_stage(runtime,self.root/'evidence')
        data=json.loads(self.ps(call+'|ConvertTo-Json -Depth 12 -Compress'))
        self.assertEqual('installed-no-git-fallback',data['identityMode'])

    def test_runtime_identity_corrects_known_parent_git_or_empty_id_using_authenticated_source_pin(self):
        for original in ('a'*40,'','bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'):
            with self.subTest(original=original),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,_,_,evidence,pin,call=self.build_identity_fixture(original)
                    before={name:(runtime/'program'/name).read_bytes() for name in ('version.ini','setup.ini')}
                    data=json.loads(self.ps(call+'|ConvertTo-Json -Depth 8 -Compress'))
                    self.assertEqual(pin['coreCommit'],data['expectedBuildId'])
                    self.assertEqual(pin['sha256'],data['sourceArchiveSha256'])
                    for name in before:
                        self.assertEqual(before[name],(evidence/('original-runtime-'+name)).read_bytes())
                        self.assertEqual(before[name].replace(('buildid='+original).encode(),('buildid='+pin['coreCommit']).encode()),
                                         (runtime/'program'/name).read_bytes())
                        self.assertEqual(original,data['files']['program/'+name]['originalBuildId'])
                        self.assertEqual(original!=pin['coreCommit'],data['files']['program/'+name]['corrected'])
                finally:self.root=old_root

    def test_runtime_identity_rejects_unrelated_parent_id_missing_duplicate_or_wrong_section_before_writes(self):
        for mutation in ('unrelated','missing','duplicate','spaced-key','leading-space','section','hidden-section','missing-file','archive-hash','archive-size'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,archive,_,evidence,_,call=self.build_identity_fixture()
                    path=runtime/'program/version.ini'
                    if mutation=='unrelated':path.write_bytes(path.read_bytes().replace(b'a'*40,b'f'*40))
                    elif mutation=='missing':path.write_bytes(b'[Version]\r\nVendor=LibreOffice\r\n')
                    elif mutation=='duplicate':path.write_bytes(path.read_bytes()+b'buildid='+b'a'*40+b'\r\n')
                    elif mutation=='spaced-key':path.write_bytes(path.read_bytes()+b'buildid ='+b'f'*40+b'\r\n')
                    elif mutation=='leading-space':path.write_bytes(path.read_bytes()+b' buildid='+b'f'*40+b'\r\n')
                    elif mutation=='section':path.write_bytes(path.read_bytes().replace(b'[Version]',b'[Other]'))
                    elif mutation=='hidden-section':path.write_bytes(b'[Version]\r\nVendor=LibreOffice\r\n [Other]\r\nbuildid='+b'a'*40+b'\r\n')
                    elif mutation=='missing-file':path.unlink()
                    elif mutation=='archive-hash':archive.write_bytes(b'x'*archive.stat().st_size)
                    else:archive.write_bytes(archive.read_bytes()+b'x')
                    self.refresh_identity_stage(runtime,evidence)
                    before={p.name:p.read_bytes() for p in (runtime/'program').iterdir()}
                    self.rejected(call)
                    self.assertEqual(before,{p.name:p.read_bytes() for p in (runtime/'program').iterdir()})
                    diagnostic=json.loads((evidence/'runtime-build-identity-diagnostic.json').read_text())
                    self.assertFalse(diagnostic['passed'])
                    for name,raw in before.items():
                        self.assertEqual(raw,(evidence/('original-runtime-'+name)).read_bytes())
                    self.assertEqual(2,len(diagnostic['files']))
                finally:self.root=old_root

    def test_installed_identity_rejects_source_config_stage_and_mixed_originals_with_raw_retention(self):
        import hashlib
        for mutation in ('unknown-id','wrong-fallback','mixed','version','config','source-hash','stage-hash',
                         'stage-size','stage-source','stage-duplicate','stage-missing','stage-archive','stage-bytes'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,_,pin_path,evidence,_,call=self.build_identity_fixture('680(Build:1)')
                    path=runtime/'program/setup.ini'
                    if mutation in ('unknown-id','wrong-fallback','mixed'):
                        value={'unknown-id':'f'*40,'wrong-fallback':'2680(Build:1)','mixed':'a'*40}[mutation]
                        path.write_bytes(path.read_bytes().replace(b'680(Build:1)',value.encode()))
                        self.refresh_identity_stage(runtime,evidence)
                    elif mutation in ('version','source-hash'):
                        pin=json.loads(pin_path.read_text());pin['version' if mutation=='version' else 'sha256']='26.8.2.1' if mutation=='version' else 'f'*64
                        pin_path.write_text(json.dumps(pin))
                    elif mutation=='config':
                        config=self.root/'identity-config.json';data=json.loads(config.read_text());data['LIBO_VERSION_MINOR']='9';config.write_text(json.dumps(data))
                    else:
                        stage=evidence/'installed-runtime-stage.json';data=json.loads(stage.read_text())
                        if mutation=='stage-hash':stage.write_text(stage.read_text()+' ')
                        elif mutation=='stage-size':
                            summary=self.root/'stage-summary.json';value=json.loads(summary.read_text());value['receipt']['bytes']+=1;summary.write_text(json.dumps(value))
                        else:
                            if mutation=='stage-source':data['configuredVersion']='26.8.2.1'
                            elif mutation=='stage-duplicate':data['files'].append(data['files'][0].copy())
                            elif mutation=='stage-missing':data['files'].pop()
                            elif mutation=='stage-archive':data['files'][0]['archivePath']='help.zip'
                            else:data['files'][0]['bytes']+=1
                            stage.write_text(json.dumps(data))
                            summary=self.root/'stage-summary.json';value=json.loads(summary.read_text());value['receipt'].update(bytes=stage.stat().st_size,sha256=hashlib.sha256(stage.read_bytes()).hexdigest());summary.write_text(json.dumps(value))
                    before={p.name:p.read_bytes() for p in (runtime/'program').iterdir()}
                    self.rejected(call)
                    self.assertEqual(before,{p.name:p.read_bytes() for p in (runtime/'program').iterdir()})
                    diagnostic=json.loads((evidence/'runtime-build-identity-diagnostic.json').read_text())
                    self.assertFalse(diagnostic['passed'])
                    for name,raw in before.items():self.assertEqual(raw,(evidence/('original-runtime-'+name)).read_bytes())
                finally:self.root=old_root

    def test_identity_snapshots_precede_utf8_rejection_and_never_overwrite_evidence(self):
        runtime,_,_,evidence,_,call=self.build_identity_fixture()
        path=runtime/'program/version.ini';path.write_bytes(b'[Version]\r\nbuildid=\xff\r\n')
        self.refresh_identity_stage(runtime,evidence)
        before={p.name:p.read_bytes() for p in (runtime/'program').iterdir()}
        self.rejected(call)
        saved={p.name:p.read_bytes() for p in evidence.iterdir()}
        self.rejected(call)
        self.assertEqual(saved,{p.name:p.read_bytes() for p in evidence.iterdir()})
        self.assertEqual(before,{p.name:p.read_bytes() for p in (runtime/'program').iterdir()})
        for name,raw in before.items():self.assertEqual(raw,(evidence/('original-runtime-'+name)).read_bytes())

    def test_identity_retention_rejects_linked_oversized_and_empty_inputs(self):
        for damage in ('linked','oversized','empty'):
            with self.subTest(damage=damage),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,_,_,evidence,_,call=self.build_identity_fixture()
                    path=runtime/'program/version.ini'
                    if damage=='linked':
                        target=self.root/'target.ini';target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
                    else:path.write_bytes(b'x'*65537 if damage=='oversized' else b'')
                    before={p.name:p.read_bytes() for p in (runtime/'program').iterdir()}
                    self.rejected(call)
                    self.assertEqual(before,{p.name:p.read_bytes() for p in (runtime/'program').iterdir()})
                    diagnostic=json.loads((evidence/'runtime-build-identity-diagnostic.json').read_text())
                    self.assertEqual('rejected',diagnostic['files']['program/version.ini']['status'])
                    self.assertEqual('retained',diagnostic['files']['program/setup.ini']['status'])
                    self.assertFalse((evidence/'original-runtime-version.ini').exists())
                    self.assertEqual(before['setup.ini'],(evidence/'original-runtime-setup.ini').read_bytes())
                finally:self.root=old_root

    def test_final_runtime_identity_verification_rejects_wrong_missing_or_changed_effective_metadata(self):
        for mutation in ('unchanged','wrong-id','empty-id','missing-file','other-metadata'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                old_root=self.root;self.root=Path(folder)
                try:
                    runtime,_,pin_path,_,pin,call=self.build_identity_fixture()
                    proof=self.root/'identity.json'
                    self.ps(call+f'|ConvertTo-Json -Depth 8|Set-Content {quote(proof)}')
                    path=runtime/'program/version.ini'
                    if mutation=='wrong-id':path.write_bytes(path.read_bytes().replace(pin['coreCommit'].encode(),b'f'*40))
                    elif mutation=='empty-id':path.write_bytes(path.read_bytes().replace(pin['coreCommit'].encode(),b''))
                    elif mutation=='missing-file':path.unlink()
                    elif mutation=='other-metadata':path.write_bytes(path.read_bytes()+b'other=changed\r\n')
                    check=f"Assert-RuntimeBuildIdentity {quote(runtime)} (Get-Content {quote(pin_path)} -Raw|ConvertFrom-Json) (Get-Content {quote(proof)} -Raw|ConvertFrom-Json)"
                    if mutation=='unchanged':self.ps(check+'|Out-Null')
                    else:self.rejected(check)
                finally:self.root=old_root

    def test_authentication_rejects_wrong_size_or_hash_before_execution(self):
        fixture=self.root/'owned';fixture.write_bytes(b'authenticated')
        import hashlib
        digest=hashlib.sha256(fixture.read_bytes()).hexdigest()
        self.ps(f"Confirm-FileIdentity {quote(fixture)} 13 SHA256 {quote(digest)}|Out-Null")
        self.rejected(f"Confirm-FileIdentity {quote(fixture)} 12 SHA256 {quote(digest)}")
        self.rejected(f"Confirm-FileIdentity {quote(fixture)} 13 SHA256 {quote('0'*64)}")

    def test_command_boundary_preserves_stdout_stderr_and_nonzero_receipt(self):
        prefix=self.root/'command'
        body=f"try {{ Invoke-LoggedCommand -FilePath {quote(os.sys.executable)} -Arguments @('-c','import sys;print(\"stdout retained\");print(\"stderr retained\",file=sys.stderr);sys.exit(9)') -WorkingDirectory {quote(self.root)} -LogPrefix {quote(prefix)} }} catch {{ }}"
        self.ps(body)
        self.assertIn('stdout retained',(self.root/'command.stdout.log').read_text())
        self.assertIn('stderr retained',(self.root/'command.stderr.log').read_text())
        receipt=json.loads((self.root/'command.command.json').read_text())
        self.assertEqual(9,receipt['exitCode'])
        self.assertFalse(receipt['passed'])
        self.assertIn('import sys;',receipt['arguments'][1])

    def test_successful_command_retains_exact_spaced_arguments(self):
        prefix=self.root/'success'
        self.ps(f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','import sys;print(sys.argv[1])','exact spaced argument') {quote(self.root)} {quote(prefix)}|Out-Null")
        self.assertEqual('exact spaced argument',(self.root/'success.stdout.log').read_text().strip())
        self.assertTrue(json.loads((self.root/'success.command.json').read_text())['passed'])

    def test_completed_fast_command_without_start_time_retains_success_and_truthful_receipt(self):
        # Wait for the real child, then expose the same null metadata observed
        # from fast git. Keep its original Process object and redirected pipes.
        prefix=self.root/'fast-exit'
        self.ps("$original=${function:Get-CommandCreationIdentity}; "
            "function Get-CommandCreationIdentity($Process) { "
            "if(-not $Process.WaitForExit(5000)){throw 'Fixture child did not exit'}; "
            "$Process|Add-Member -MemberType ScriptProperty -Name StartTime -Value {$null} -Force; "
            "& $original $Process }; "
            f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','print(\"fast completed output\")') {quote(self.root)} {quote(prefix)}|Out-Null")
        receipt=json.loads((self.root/'fast-exit.command.json').read_text())
        self.assertTrue(receipt['passed']);self.assertEqual(0,receipt['exitCode'])
        self.assertTrue(receipt['directProcessDeathVerified']);self.assertTrue(receipt['pipeDrainComplete'])
        self.assertIsNone(receipt['creationUtcTicks'])
        self.assertEqual('unavailable-after-exit',receipt['creationIdentityStatus'])
        self.assertGreater(receipt['pid'],0)
        self.assertEqual('fast completed output',(self.root/'fast-exit.stdout.log').read_text().strip())

    def pipe_descendant(self,delay):
        child=self.root/'pipe-child.py'
        child.write_text("import os, pathlib, sys, time\n"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            f"time.sleep({delay!r})\nprint('descendant final stdout',flush=True)\n"
            "print('descendant final stderr',file=sys.stderr,flush=True)\n",encoding='utf-8')
        parent=self.root/'pipe-parent.py'
        parent.write_text("import pathlib, subprocess, sys, time\n"
            "subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],stdout=sys.stdout,stderr=sys.stderr)\n"
            "deadline=time.monotonic()+2\n"
            "while not pathlib.Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.01)\n"
            "print('direct parent exited',flush=True)\n",encoding='utf-8')
        return parent,child,self.root/'descendant.pid'

    def test_exited_parent_cannot_restart_deadline_for_inherited_output_pipes(self):
        prefix=self.root/'inherited'
        with OwnedInheritedPipeFixture(self.root) as fixture:
            arguments=','.join(map(quote,fixture.arguments))
            self.ps(f"try {{ Invoke-LoggedCommand {quote(os.sys.executable)} @({arguments}) {quote(self.root)} {quote(prefix)} -TimeoutMinutes (1.0/60) | Out-Null }} catch {{ }}")
            receipt=json.loads((self.root/'inherited.command.json').read_text())
            self.assertFalse(receipt['passed'],'Direct exit 0 cannot qualify a command whose output EOF missed its deadline')
            self.assertEqual(0,receipt['exitCode'])
            self.assertLess(receipt['elapsedSeconds'],3)
            self.assertFalse(receipt['pipeDrainComplete'])
            self.assertFalse(receipt['forcedTermination'])
            self.assertTrue(receipt['directProcessDeathVerified'])
            self.assertEqual('unproved-after-direct-process-exit',receipt['processTreeCleanup'])
            self.assertIn('direct parent exited',(self.root/'inherited.stdout.log').read_text())
        self.assertEqual(0,fixture.observation['exitCode'])

    def test_pipe_eof_inside_original_deadline_preserves_final_descendant_output(self):
        parent,child,pidfile=self.pipe_descendant(.15)
        prefix=self.root/'drained'
        self.ps(f"Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(parent)},{quote(child)},{quote(pidfile)}) {quote(self.root)} {quote(prefix)} -TimeoutMinutes (2.0/60) | Out-Null")
        receipt=json.loads((self.root/'drained.command.json').read_text())
        self.assertTrue(receipt['passed'])
        self.assertTrue(receipt['pipeDrainComplete'])
        self.assertFalse(receipt['forcedTermination'])
        self.assertTrue(receipt['directProcessDeathVerified'])
        self.assertIn('descendant final stdout',(self.root/'drained.stdout.log').read_text())
        self.assertIn('descendant final stderr',(self.root/'drained.stderr.log').read_text())

    def test_running_command_timeout_forces_only_owned_tree_and_preserves_failure(self):
        prefix=self.root/'running'
        self.ps(f"try {{ Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','import time;print(\"before timeout\",flush=True);time.sleep(20)') {quote(self.root)} {quote(prefix)} -TimeoutMinutes (1.0/60) | Out-Null }} catch {{ }}")
        receipt=json.loads((self.root/'running.command.json').read_text())
        self.assertFalse(receipt['passed'])
        self.assertTrue(receipt['forcedTermination'])
        self.assertTrue(receipt['directProcessDeathVerified'])
        self.assertFalse(receipt['pipeDrainComplete'])
        self.assertLess(receipt['elapsedSeconds'],7)
        self.assertIn('before timeout',(self.root/'running.stdout.log').read_text())

    def test_shared_build_budget_is_not_restarted_for_later_commands(self):
        body=f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes (1.0/60); "
        for name,delay in (('first',.25),('second',3),('third',0)):
            body+=f"try {{ Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','import time;time.sleep({delay})') {quote(self.root)} {quote(self.root/name)}|Out-Null }} catch {{ }}; "
        self.ps(body)
        receipts=[json.loads((self.root/(name+'.command.json')).read_text()) for name in ('first','second','third')]
        self.assertTrue(receipts[0]['passed'])
        self.assertFalse(receipts[1]['passed'])
        self.assertTrue(receipts[1]['forcedTermination'])
        self.assertLess(receipts[1]['effectiveTimeoutMilliseconds'],800)
        self.assertFalse(receipts[2]['passed'])
        self.assertNotIn('pid',receipts[2],'Expired build budget must reject before launch')
        self.assertIn('shared build deadline',receipts[2]['error'])

    def test_build_deadline_requires_utc_roundtrip_and_cannot_extend_local_maximum(self):
        self.ps("$budget=New-NativeBuildBudget -DeadlineUtc ([DateTime]::UtcNow.AddHours(10).ToString('o')); if($budget.record.timeoutMilliseconds -gt 330*60000){throw 'Extended local maximum'}")
        for deadline in ('2020-01-01T00:00:00.0000000Z','2026-10-17T01:00:00.0000000+01:00','not a timestamp'):
            self.rejected(f"New-NativeBuildBudget -DeadlineUtc {quote(deadline)}")

    def test_expired_build_deadline_retains_failure_before_native_host_or_commands(self):
        output=self.root/'expired-evidence'
        self.ps(f"function Assert-NativeEngineEnvironment {{param($Architecture)}}; function Get-NativeBuildHost {{ throw 'Native host must not run after deadline' }}; try {{ Invoke-NativeEngineBuild Full {quote(self.root/'expired-work')} {quote(output)} '' 4 -DeadlineUtc '2020-01-01T00:00:00.0000000Z' }} catch {{ }}")
        receipt=json.loads((output/'source-build-receipt.json').read_text())
        self.assertFalse(receipt['passed']);self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('build-time-budget',receipt['stage'])
        self.assertIn('deadline',receipt['error'])
        self.assertNotIn('host',receipt)
        self.assertFalse((output/'OpenGeul-Office-engine-arm64.zip').exists())

    def test_final_deadline_cannot_leave_a_qualified_declaration_in_failure_receipt(self):
        target=self.root/'late-admission.json'
        body="$tokens=$null;$errors=$null;$text=Get-Content -LiteralPath "+quote(SOURCE)+" -Raw; "
        body+="$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors); "
        body+="$build=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-NativeEngineBuild'},$true); "
        body+="$outer=$build.Body.Find({param($n) $n -is [Management.Automation.Language.TryStatementAst]},$true); "
        body+="$artifact=$outer.Body.Find({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$receipt.artifact'},$true); "
        body+="$tail='if($Phase -eq ''Full'') {'+$text.Substring($artifact.Extent.EndOffset,$outer.Body.Extent.EndOffset-1-$artifact.Extent.EndOffset); "
        body+="$caught=$outer.CatchClauses[0].Body.Extent.Text;$caught=$caught.Substring(1,$caught.Length-2); "
        body+="$receipt=[ordered]@{passed=$false;fullEngineQualified=$false;status='failed'};$Phase='Full';$script:checks=0; "
        body+="function Assert-NativeBuildTimeRemaining {$script:checks++;if($script:checks -eq 2){throw 'Observed final shared build deadline'}}; "
        body+="try {& ([scriptblock]::Create('try {'+$tail+'} catch {'+$caught+'}'))} catch {}; "
        body+="if($script:checks -ne 2){throw 'Final deadline boundary was not exercised'}; Write-BuildJson "+quote(target)+" $receipt"
        self.ps(body)
        receipt=json.loads(target.read_text())
        self.assertFalse(receipt['passed']);self.assertFalse(receipt['fullEngineQualified'])
        self.assertEqual('failed',receipt['status'])
        self.assertIn('Observed final shared build deadline',receipt['error'])

    def finalization_deadline_case(self, expiry):
        source=self.root/'synthetic-source';source.mkdir();(source/'config_host.mk').write_text('synthetic diagnostics')
        evidence=self.root/'synthetic-evidence';evidence.mkdir()
        archive=evidence/'synthetic-engine.zip';archive.write_bytes(b'synthetic archive sentinel')
        body=f"""
$tokens=$null;$errors=$null;$text=Get-Content -LiteralPath {quote(SOURCE)} -Raw
$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
$build=$ast.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-NativeEngineBuild'}},$true)
$outer=$build.Body.Find({{param($n) $n -is [Management.Automation.Language.TryStatementAst]}},$true)
$Architecture='x64';$source={quote(source)};$evidence={quote(evidence)};$zip={quote(archive)};$manifest=$null
$mode=@{{receipt='synthetic-result.json'}}
$receipt=[ordered]@{{passed=$true;fullEngineQualified=$true;acceptanceEligible=$true;status='native-engine-source-build-qualified';buildBudget=@{{}}}}
$previousBudget=[pscustomobject]@{{marker='previous scope'}}
$script:fixtureClock=[pscustomobject]@{{Elapsed=[pscustomobject]@{{TotalMilliseconds=0;TotalSeconds=0}}}}
$script:originalBudget=[pscustomobject]@{{record=@{{timeoutMilliseconds=100}};clock=$script:fixtureClock}}
$script:NativeEngineBuildBudget=$script:originalBudget
$script:writeObservations=[Collections.Generic.List[object]]::new()
$script:fixtureWriter=${{function:Write-BuildJson}}
function Copy-Item {{param($LiteralPath,$Destination,[switch]$Force)
 Microsoft.PowerShell.Management\\Copy-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
 if('{expiry}' -ceq 'copy'){{$script:fixtureClock.Elapsed.TotalMilliseconds=200;$script:fixtureClock.Elapsed.TotalSeconds=0.2}}
}}
function Write-BuildJson($Path,$Value) {{
 $script:writeObservations.Add(@{{passed=$Value.passed;originalBudget=[object]::ReferenceEquals($script:NativeEngineBuildBudget,$script:originalBudget)}})
 &$script:fixtureWriter $Path $Value
 if('{expiry}' -ceq 'write'){{$script:fixtureClock.Elapsed.TotalMilliseconds=200;$script:fixtureClock.Elapsed.TotalSeconds=0.2}}
}}
$thrown=$false
try {{& ([scriptblock]::Create('try {{Assert-NativeBuildTimeRemaining}} finally '+$outer.Finally.Extent.Text))}}
catch {{if($_.Exception.Message -notmatch 'shared build deadline'){{throw}};$thrown=$true}}
[ordered]@{{thrown=$thrown;archivePresent=(Test-Path -LiteralPath $zip);budgetRestored=[object]::ReferenceEquals($script:NativeEngineBuildBudget,$previousBudget);writes=@($script:writeObservations);proof=(Get-Content -LiteralPath (Join-Path $evidence $mode.receipt) -Raw|ConvertFrom-Json)}}|ConvertTo-Json -Depth 10 -Compress
"""
        result=json.loads(self.ps(body))
        self.assertTrue(result['budgetRestored'])
        self.assertTrue(all(row['originalBudget'] for row in result['writes']))
        return result

    def test_x64_final_diagnostic_copy_expiry_revokes_proof_and_archive(self):
        result=self.finalization_deadline_case('copy')
        self.assertTrue(result['thrown']);self.assertFalse(result['archivePresent'])
        self.assertEqual([False],[row['passed'] for row in result['writes']])
        for name in ('passed','fullEngineQualified','acceptanceEligible'):self.assertIs(False,result['proof'][name])

    def test_x64_final_receipt_write_expiry_revokes_persisted_success_and_archive(self):
        result=self.finalization_deadline_case('write')
        self.assertTrue(result['thrown']);self.assertFalse(result['archivePresent'])
        self.assertEqual([True,False],[row['passed'] for row in result['writes']])
        for name in ('passed','fullEngineQualified','acceptanceEligible'):self.assertIs(False,result['proof'][name])

    def test_x64_in_budget_finalization_keeps_proof_and_restores_budget_last(self):
        result=self.finalization_deadline_case('none')
        self.assertFalse(result['thrown']);self.assertTrue(result['archivePresent'])
        self.assertEqual([True],[row['passed'] for row in result['writes']])
        for name in ('passed','fullEngineQualified','acceptanceEligible'):self.assertIs(True,result['proof'][name])

    def test_native_unit_child_clears_ambient_values_and_retains_required_tool_paths(self):
        prefix=self.root/'unit-environment'
        child=self.root/'unit-environment.py'
        child.write_text("import json,os,shutil\n"
            "assert os.environ.get('OPENGEUL_SYNTHETIC_UNIT_SENTINEL') is None\n"
            "assert shutil.which('pwsh') is not None\n"
            "assert os.environ.get('PYTHONUTF8')=='1'\n"
            "assert os.environ.get('PYTHONDONTWRITEBYTECODE')=='1'\n"
            "print(json.dumps({'isolated':True,'requiredTools':True}))\n")
        setup=""
        if os.name!='nt':
            system=self.root/'synthetic-os';(system/'System32').mkdir(parents=True)
            setup=f"$env:SystemRoot={quote(system)}; "
        self.ps(setup+"$env:OPENGEUL_SYNTHETIC_UNIT_SENTINEL='synthetic-only'; "+
            f"Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(child)}) {quote(self.root)} {quote(prefix)} -NativeUnitEnvironment|Out-Null")
        receipt=json.loads((self.root/'unit-environment.command.json').read_text())
        self.assertTrue(receipt['passed'])
        self.assertEqual('native-unit-required-paths-only',receipt['environmentPolicy'])
        self.assertEqual({'isolated':True,'requiredTools':True},json.loads((self.root/'unit-environment.stdout.log').read_text()))

    def test_native_unit_gate_requires_original_unexpired_deadline_before_child(self):
        evidence=self.root/'unit-deadline';evidence.mkdir()
        body=f"""
$script:previous=[pscustomobject]@{{marker='prior budget'}};$script:NativeEngineBuildBudget=$script:previous
function Invoke-LoggedCommand {{throw 'CHILD MUST NOT START'}}
foreach($deadline in @('',[DateTime]::UtcNow.AddMinutes(-1).ToString('o'))) {{
 $rejected=$false
 try {{Invoke-NativeEngineUnitGate {quote(Path(os.sys.executable).resolve(strict=True))} {quote(SOURCE.parents[2])} {quote(evidence)} $deadline}}
 catch {{if($_.Exception.Message -match 'CHILD MUST NOT START'){{throw}};$rejected=$true}}
 if(-not $rejected){{throw 'Missing or expired deadline accepted'}}
 if(-not [object]::ReferenceEquals($script:previous,$script:NativeEngineBuildBudget)){{throw 'Original budget scope lost'}}
}}
"""
        self.ps(body)
        self.assertFalse(json.loads((evidence/'native-unit-gate.json').read_text())['passed'])
        self.assertFalse(list(evidence.glob('*.command.json')))

    def test_native_unit_gate_nonzero_child_prevents_following_step(self):
        evidence=self.root/'unit-gate';evidence.mkdir()
        system=self.root/'synthetic-os';(system/'System32').mkdir(parents=True)
        marker=self.root/'following-step'
        setup=f"$env:SystemRoot={quote(system)}; " if os.name!='nt' else ''
        body=setup+f"""
function Get-NativeBuildHost {{param($Architecture) @{{isWindows=$true;processMachine=0;nativeMachine=34404}}}}
$script:actualUnitLogger=${{function:Invoke-LoggedCommand}}
function Invoke-LoggedCommand($FilePath,$Arguments,$WorkingDirectory,$LogPrefix,[switch]$NativeUnitEnvironment) {{
 if(-not $NativeUnitEnvironment){{throw 'Unit isolation was omitted'}}
 &$script:actualUnitLogger $FilePath @('-c','import sys;sys.exit(7)') $WorkingDirectory $LogPrefix -NativeUnitEnvironment
}}
Invoke-NativeEngineUnitGate {quote(Path(os.sys.executable).resolve(strict=True))} {quote(SOURCE.parents[2])} {quote(evidence)} ([DateTime]::UtcNow.AddMinutes(1).ToString('o'))
Set-Content -LiteralPath {quote(marker)} -Value 'following step must not execute'
"""
        script=self.root/'unit-failure.ps1';script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+'\n'+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(0,result.returncode)
        receipt=json.loads((evidence/'native-unit-checks.command.json').read_text())
        self.assertEqual(7,receipt['exitCode']);self.assertFalse(receipt['passed'])
        proof=json.loads((evidence/'native-unit-gate.json').read_text())
        self.assertFalse(proof['passed']);self.assertFalse(marker.exists())

    def test_authenticated_redirect_keeps_bytes_and_status_without_signed_query(self):
        import hashlib
        import http.server
        import threading
        observed=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                observed.append(handler.path)
                if handler.path=='/denied':
                    handler.send_response(403,'synthetic-capability');handler.end_headers()
                elif handler.path=='/start':
                    handler.send_response(302);handler.send_header('Location','/payload?sig=synthetic-capability');handler.end_headers()
                else:
                    handler.send_response(200);handler.send_header('Content-Length','2');handler.end_headers();handler.wfile.write(b'ab')
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        target=self.root/'payload';receipt=self.root/'receipt.json'
        output=self.ps(f"Get-AuthenticatedDownload 'http://127.0.0.1:{server.server_port}/start' {quote(target)} 2 SHA256 {quote(hashlib.sha256(b'ab').hexdigest())} {quote(receipt)}|Out-Null")
        raw=receipt.read_text();data=json.loads(raw)
        self.assertEqual(['/start','/payload?sig=synthetic-capability'],observed)
        self.assertEqual('authenticated',data['status']);self.assertEqual(200,data['httpStatus'])
        self.assertEqual(f'http://127.0.0.1:{server.server_port}/payload',data['finalUrl'])
        self.assertNotIn('synthetic-capability',raw+output);self.assertEqual(b'ab',target.read_bytes())
        denied=self.root/'denied.json'
        output=self.ps(f"try {{ Get-AuthenticatedDownload 'http://127.0.0.1:{server.server_port}/denied' {quote(self.root/'not-created')} 2 SHA256 {quote(hashlib.sha256(b'ab').hexdigest())} {quote(denied)}|Out-Null }} catch {{ $_.Exception.ToString() }}")
        raw=denied.read_text();data=json.loads(raw)
        self.assertEqual(403,data['httpStatus']);self.assertEqual('failed',data['status'])
        self.assertIn('errorType',data);self.assertNotIn('synthetic-capability',raw+output)
        self.assertFalse((self.root/'not-created').exists())

    def test_cygwin_bootstrap_requests_the_signature_verified_official_setup_checksum(self):
        # Independent official sha512.sum, cross-checked against the detached
        # signature dated 2026-11-01 and the install.html Cygwin RSA fingerprint.
        expected = '9bbbd4de497842446af58af875590ace5d8fa3c557cd7e27328569dfa68e58213da1cc1a6fb7102d4f0f01be38e0b92c6fa74f61b6eb7351a0481ca4bd9e8781'
        source = SOURCE.read_text()
        start = source.index("        $setup=Join-Path $downloads 'setup-x86_64.exe'\n")
        stop = source.index("        $manifestPath=", start)
        # Execute the actual bootstrap selection, replacing only network I/O.
        # No installer is executed and no unpinned download can reach a server.
        result = json.loads(self.ps(f"""
$downloads={quote(self.root)};$evidence={quote(self.root)};$receipt=@{{}}
function Get-AuthenticatedDownload($Url,$Destination,$Size,$Algorithm,$Hash,$ReceiptPath) {{
    return [ordered]@{{url=$Url;destination=$Destination;algorithm=$Algorithm;hash=$Hash}}
}}
{source[start:stop]}
$receipt.cygwinSetup|ConvertTo-Json -Compress
"""))
        self.assertEqual('https://cygwin.com/setup-x86_64.exe', result['url'])
        self.assertEqual(str(self.root/'setup-x86_64.exe'), result['destination'])
        self.assertEqual('SHA512', result['algorithm'])
        self.assertEqual(expected, result['hash'])

    def test_shared_deadline_cancels_stalled_authenticated_download_body(self):
        import hashlib
        import http.server
        import threading
        import time
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                handler.send_response(200);handler.send_header('Content-Length','2');handler.end_headers()
                handler.wfile.write(b'a');handler.wfile.flush();time.sleep(3)
                try:handler.wfile.write(b'z')
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        prefix=self.root/'download';receipt=self.root/'download.json'
        self.ps(f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes (1.0/60); try {{ Get-AuthenticatedDownload 'http://127.0.0.1:{server.server_port}/fixture' {quote(prefix)} 2 SHA256 {quote(hashlib.sha256(b'az').hexdigest())} {quote(receipt)}|Out-Null }} catch {{ }}")
        data=json.loads(receipt.read_text())
        self.assertEqual('failed',data['status'],'Headers alone must not remove the deadline from the streamed body')
        self.assertLess(data['elapsedSeconds'],2)
        self.assertEqual(b'a',prefix.read_bytes(),'Partial original bytes remain available after cancellation')

    def test_workflow_establishes_deadline_before_checkout_outside_workspace(self):
        import textwrap
        import datetime
        workflow=SOURCE.parents[2]/'.github/workflows/office-native-engine.yml'
        text=workflow.read_text()
        first=text.split('        run: |\n',1)[1].split('      - name: Preserve exact source bytes',1)[0]
        runner=self.root/'runner-temp';runner.mkdir();github_env=self.root/'github-env'
        self.ps(f"$env:RUNNER_TEMP={quote(runner)};$env:GITHUB_ENV={quote(github_env)};$env:GITHUB_RUN_ID='123';$env:GITHUB_RUN_ATTEMPT='1';\n"+textwrap.dedent(first))
        values=dict(line.split('=',1) for line in github_env.read_text().splitlines())
        path=Path(values['OPENGEUL_ENGINE_BUDGET_RECEIPT'])
        self.assertEqual(runner,path.parent.parent)
        receipt=json.loads(path.read_text());self.assertEqual('first-user-step',receipt['origin'])
        self.assertFalse(receipt['runnerSetupIncluded']);self.assertEqual(30,receipt['nominalReserveMinutes'])
        start=datetime.datetime.fromisoformat(receipt['startedUtc'].replace('Z','+00:00'))
        end=datetime.datetime.fromisoformat(receipt['deadlineUtc'].replace('Z','+00:00'))
        self.assertEqual(330*60,(end-start).total_seconds())
        self.assertEqual(receipt['deadlineUtc'],values['OPENGEUL_ENGINE_BUILD_DEADLINE_UTC'])
        self.assertIn('-DeadlineUtc $env:OPENGEUL_ENGINE_BUILD_DEADLINE_UTC',text)
        self.assertIn('Copy-Item -LiteralPath $env:OPENGEUL_ENGINE_BUDGET_RECEIPT',text)

    def test_engine_archive_uses_bounded_command_and_preserves_exact_runtime_bytes(self):
        import zipfile
        runtime=self.root/'runtime';runtime.mkdir();(runtime/'nested').mkdir()
        (runtime/'nested/한글.txt').write_bytes(b'exact native runtime fixture')
        evidence=self.root/'zip-evidence';evidence.mkdir();archive=evidence/'engine.zip'
        self.ps(f"$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes (5.0/60); Write-NativeEngineArchive {quote(runtime)} {quote(archive)} {quote(evidence)}")
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(['nested/한글.txt'],package.namelist())
            self.assertEqual(b'exact native runtime fixture',package.read('nested/한글.txt'))
        receipt=json.loads((evidence/'package-native-engine.command.json').read_text())
        self.assertTrue(receipt['passed']);self.assertTrue(receipt['pipeDrainComplete'])
        self.assertLessEqual(receipt['effectiveTimeoutMilliseconds'],5000)
        self.assertEqual(str(runtime),receipt['arguments'][-2])
        self.assertEqual(str(archive),receipt['arguments'][-1])

    def test_pe_machine_rejects_emulated_products_and_truncated_headers(self):
        path=self.root/'native.exe'
        data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,0xAA64);struct.pack_into('<H',data,148,240);struct.pack_into('<H',data,152,0x20B)
        path.write_bytes(data)
        self.ps(f"$pe=Get-ProductPeIdentity {quote(path)}; if($pe.machine -ne 43620){{throw 'Not ARM64'}}")
        struct.pack_into('<H',data,132,0x8664);path.write_bytes(data)
        self.rejected(f"Get-ProductPeIdentity {quote(path)}")
        path.write_bytes(b'MZ')
        self.rejected(f"Get-ProductPeIdentity {quote(path)}")

    def test_il_only_anycpu_dll_is_preserved_but_native_x86_flags_fail(self):
        path=self.root/'managed.dll'
        data=bytearray(1024);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0'
        struct.pack_into('<H',data,132,0x14c);struct.pack_into('<H',data,134,1);struct.pack_into('<H',data,148,224);struct.pack_into('<H',data,150,0x2000)
        opt=152;struct.pack_into('<H',data,opt,0x10b);struct.pack_into('<I',data,opt+92,16);struct.pack_into('<II',data,opt+96+14*8,0x2000,72)
        section=opt+224;struct.pack_into('<IIII',data,section+8,512,0x2000,512,512)
        struct.pack_into('<I',data,512,72);struct.pack_into('<III',data,520,0x2080,32,1);data[640:644]=b'BSJB'
        path.write_bytes(data)
        self.ps(f"$pe=Get-ProductPeIdentity {quote(path)};if($pe.role -ne 'managedAnyCpu'){{throw 'IL-only AnyCPU rejected'}}")
        for offset,value in [(528,3),(576,0x2222)]:
            bad=bytearray(data);struct.pack_into('<I',bad,offset,value);path.write_bytes(bad)
            self.rejected(f"Get-ProductPeIdentity {quote(path)}")

    def test_only_exact_authenticated_python_template_metadata_is_admitted(self):
        raw=self.ps("@(Get-PinnedPythonTemplates)|ConvertTo-Json -Compress")
        pins=json.loads(raw)
        self.assertEqual(10,len(pins))
        chosen=pins[0]
        self.ps(f"Assert-PythonTemplateAdmission {quote(chosen['path'])} {chosen['machine']} {quote(chosen['sha256'])}|Out-Null")
        for path,machine,digest in [('program/python.exe',chosen['machine'],chosen['sha256']),
                                    (chosen['path'],0xAA64,chosen['sha256']),
                                    (chosen['path'],chosen['machine'],'0'*64)]:
            self.rejected(f"Assert-PythonTemplateAdmission {quote(path)} {machine} {quote(digest)}")

    def test_x64_templates_reuse_only_existing_foreign_payload_admissions(self):
        from suite.payload import COMPANION_PE_ADMISSIONS
        pins=json.loads(self.ps('@(Get-PinnedPythonTemplates x64)|ConvertTo-Json -Compress'))
        foreign={pin['path']: {key:pin[key] for key in ('machine','sha256','role')} for pin in pins if pin['machine']!=0x8664}
        expected={path.removeprefix('Office/'):value for path,value in COMPANION_PE_ADMISSIONS.items() if value['role']=='pythonLauncherTemplate'}
        self.assertEqual(expected,foreign)
        for path,pin in foreign.items():
            self.ps(f"Assert-PythonTemplateAdmission {quote(path)} {pin['machine']} {quote(pin['sha256'])} x64|Out-Null")
            self.rejected(f"Assert-PythonTemplateAdmission {quote(path)} {pin['machine']} {quote('0'*64)} x64")
        self.rejected("Assert-PythonTemplateAdmission 'program/twain32shim.exe' 332 ('a'*64) x64")

    def test_external_archives_match_authenticated_download_list_before_qualification(self):
        import hashlib
        cache=self.root/'cache';cache.mkdir()
        archive=cache/'Python-owned.tar.xz';archive.write_bytes(b'pinned Python input')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        pins=self.root/'pins.log';pins.write_text('PIN|PYTHON_TARBALL|Python-owned.tar.xz|'+digest+'\n')
        output=self.root/'source-inputs.json'
        self.ps(f"Write-ExternalSourceInventory {quote(cache)} {quote(pins)} {quote(output)} @{{}} '' -RequirePython|Out-Null")
        data=json.loads(output.read_text())
        self.assertEqual(digest,data['archives'][0]['sha256'])
        self.assertTrue(data['pythonSourceVerified'])
        archive.write_bytes(b'tampered')
        self.rejected(f"Write-ExternalSourceInventory {quote(cache)} {quote(pins)} {quote(self.root/'bad-inputs.json')} @{{}} '' -RequirePython")
        archive.write_bytes(b'pinned Python input')
        (cache/'unknown-pip.zip').write_bytes(b'not upstream pinned')
        self.rejected(f"Write-ExternalSourceInventory {quote(cache)} {quote(pins)} {quote(self.root/'unknown-inputs.json')} @{{}} '' -RequirePython")

    def test_reused_command_prefix_preserves_original_receipt(self):
        prefix=self.root/'once'
        self.ps(f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','print(123)') {quote(self.root)} {quote(prefix)}|Out-Null")
        original=(self.root/'once.command.json').read_bytes()
        self.rejected(f"Invoke-LoggedCommand {quote(os.sys.executable)} @('-c','print(456)') {quote(self.root)} {quote(prefix)}")
        self.assertEqual(original,(self.root/'once.command.json').read_bytes())

    def crt_fixture(self,family='Microsoft.VC145.CRT',redist_version='14.50.12350'):
        tools=self.root/'VS/VC/Tools/MSVC/14.50.12345'
        tools.mkdir(parents=True)
        source=self.root/('VS/VC/Redist/MSVC/'+redist_version+'/arm64/'+family)
        source.mkdir(parents=True)
        names=('concrt140.dll','msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_atomic_wait.dll','msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_threads.dll')
        data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0';struct.pack_into('<H',data,132,0xAA64);struct.pack_into('<H',data,148,240);struct.pack_into('<H',data,152,0x20B)
        for name in names:(source/name).write_bytes(data)
        return tools,source,names

    def crt_mock(self):
        return "function Get-CrtSigningIdentity($Path) { [pscustomobject]@{status='Valid';signerSubject='CN=Microsoft Corporation, O=Microsoft Corporation, C=US';signerThumbprint=('a'*40);fileVersion='14.50.12350.0';productVersion='14.50.12350.0';fileVersionParts=@(14,50,12350,0);productVersionParts=@(14,50,12350,0);companyName='Microsoft Corporation';originalFilename=[IO.Path]::GetFileName($Path)} }; "

    def test_source_run_binding_matches_real_git_tree_and_rejects_dirty_or_wrong_run_sha(self):
        repo=self.root/'bound-repo';repo.mkdir()
        driver=repo/'driver.ps1';driver.write_text('# committed driver\n')
        manifest=repo/'source-build.json';manifest.write_text('{"schemaVersion":1}\n')
        policy=repo/'suite/engine-build/native-targets.json';policy.parent.mkdir(parents=True);policy.write_text('synthetic committed policy\n')
        def git(*arguments):
            result=subprocess.run(['git','-C',str(repo),*arguments],text=True,capture_output=True,timeout=5)
            self.assertEqual(0,result.returncode,result.stderr)
            return result.stdout.strip()
        git('init','-q');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        git('add','.');git('commit','-qm','fixture')
        head=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
        logs=self.root/'source-logs';logs.mkdir()
        env=f"$env:GITHUB_SHA='{head}';$env:GITHUB_RUN_ID='39000146117';$env:GITHUB_RUN_ATTEMPT='2'; "
        raw=self.ps(env+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(logs)}|ConvertTo-Json -Compress")
        data=json.loads(raw.splitlines()[-1])
        self.assertEqual(head,data['sourceCommit']);self.assertEqual(tree,data['sourceTree'])
        self.assertEqual(39000146117,data['sourceRun']);self.assertEqual(2,data['runAttempt'])
        import hashlib
        self.assertEqual(hashlib.sha256(driver.read_bytes()).hexdigest(),data['driverSha256'])
        self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),data['sourcePortManifestSha256'])
        self.assertEqual(hashlib.sha256(policy.read_bytes()).hexdigest(),data['nativeTargetsSha256'])
        policy.write_text('synthetic policy drift\n')
        policy_dirty=self.root/'policy-dirty';policy_dirty.mkdir()
        self.rejected(env+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(policy_dirty)}")
        policy.write_text('synthetic committed policy\n')
        wrong=self.root/'wrong-run';wrong.mkdir()
        self.rejected(env.replace(head,'0'*40)+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(wrong)}")
        driver.write_text('# uncommitted changed driver\n')
        dirty=self.root/'dirty-run';dirty.mkdir()
        self.rejected(env+f"Get-SourceRunBinding {quote(repo)} {quote(driver)} {quote(manifest)} {quote(dirty)}")

    def test_native_crt_preflight_binds_configured_vs_and_permits_current_abi_folder(self):
        tools,source,names=self.crt_fixture(family='Microsoft.VC143.CRT')
        raw=self.ps(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'|ConvertTo-Json -Depth 12 -Compress")
        plan=json.loads(raw)
        self.assertEqual('arm64',plan['architecture'])
        self.assertEqual(8,len(plan['files']))
        self.assertEqual(str(source),plan['sourceDirectory'])
        self.assertEqual('Microsoft.VC143.CRT',plan['redistFamily'])
        self.assertEqual('14.50.12345',plan['compilerToolsVersion'])
        self.assertEqual(set(names),{row['name'] for row in plan['files']})
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v143'")

    def test_architecture_family_preserves_x64_default_and_native_arm64_exact_eight(self):
        raw=self.ps("@{default=@(Get-CrtNames);x64=@(Get-CrtNames 'x64');arm64=@(Get-CrtNames 'arm64')}|ConvertTo-Json -Compress")
        families=json.loads(raw)
        self.assertEqual(families['default'],families['x64'])
        self.assertEqual(9,len(families['x64']));self.assertEqual(8,len(families['arm64']))
        self.assertIn('vcruntime140_1.dll',families['x64'])
        self.assertNotIn('vcruntime140_1.dll',families['arm64'])
        self.rejected("Get-CrtNames 'x86'")

    def test_native_crt_preflight_does_not_require_or_stage_x64_one(self):
        tools,source,names=self.crt_fixture()
        (source/'vcruntime140_1.dll').write_bytes(b'foreign x64 evidence, never native')
        raw=self.ps(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'|ConvertTo-Json -Depth 12 -Compress")
        self.assertEqual(set(names),{row['name'] for row in json.loads(raw)['files']})
        self.rejected(self.crt_mock()+f"Assert-CrtFile {quote(source/'vcruntime140_1.dll')} '14.50.12345.0'")

    def test_native_crt_same_tool_version_directory_is_accepted(self):
        tools,source,names=self.crt_fixture(redist_version='14.50.12345')
        self.ps(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'|Out-Null")

    def test_native_crt_preflight_rejects_older_toolset_missing_file_and_bad_pe(self):
        tools,source,names=self.crt_fixture(redist_version='14.44.99999')
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")
        new=source.parents[2]/'14.50.12350/arm64/Microsoft.VC145.CRT'
        new.parent.mkdir(parents=True);shutil.move(str(source),str(new))
        (new/names[-1]).unlink()
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")
        (new/names[-1]).write_bytes(b'MZ')
        self.rejected(self.crt_mock()+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")

    def test_native_crt_preflight_rejects_nonmicrosoft_signature_and_older_dll_version(self):
        tools,source,names=self.crt_fixture()
        base=self.crt_mock()
        for changed in (base.replace("status='Valid'","status='NotTrusted'"),base.replace('O=Microsoft Corporation','O=Other Corporation'),base.replace('@(14,50,12350,0)','@(14,44,99999,0)')):
            self.rejected(changed+f"Get-AppLocalCrtPlan {quote(tools)} 'v145'")

    def test_native_crt_stage_copies_only_eight_authentic_bytes_and_redistribution_terms(self):
        tools,source,names=self.crt_fixture()
        (source/'arbitrary.dll').write_bytes(b'never copy')
        program=self.root/'instdir/program';program.mkdir(parents=True)
        terms=self.root/'terms.html';terms.write_text('Preserved Microsoft Visual Studio2026 redistribution terms')
        raw=self.ps(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145'; Install-AppLocalCrt $plan {quote(program)} {quote(terms)}|ConvertTo-Json -Depth 12 -Compress")
        receipt=json.loads(raw)
        self.assertEqual('arm64',receipt['architecture'])
        self.assertEqual(8,len(receipt['files']))
        self.assertEqual(set(names),{p.name for p in program.iterdir()})
        for name in names:self.assertEqual((source/name).read_bytes(),(program/name).read_bytes())
        self.assertTrue((program.parent/'share/readme/Microsoft-VC145-redistribution.html').is_file())

    def test_native_crt_stage_rejects_extra_one_before_copying_native_family(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'instdir/program';program.mkdir(parents=True)
        foreign=program/'vcruntime140_1.dll';foreign.write_bytes(b'preserve foreign bytes')
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([foreign],list(program.iterdir()))
        self.assertEqual(b'preserve foreign bytes',foreign.read_bytes())

    def test_native_crt_stage_rejects_legacy_versioned_runtime_before_copy(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'instdir/program';program.mkdir(parents=True)
        legacy=program/'msvcr120.dll';legacy.write_bytes(b'preserve legacy runtime')
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([legacy],list(program.iterdir()))

    def test_native_crt_stage_rejects_linked_notice_directory_before_any_copy(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'instdir/program';program.mkdir(parents=True)
        outside=self.root/'outside';outside.mkdir()
        share=program.parent/'share';share.mkdir()
        try:(share/'readme').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError):return
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([],list(program.iterdir()))
        self.assertEqual([],list(outside.iterdir()))

    def test_native_crt_stage_rejects_collision_or_changed_source_before_any_copy(self):
        tools,source,names=self.crt_fixture()
        program=self.root/'program';program.mkdir()
        target=program/names[0];target.write_bytes(b'preserve collision')
        terms=self.root/'terms.html';terms.write_text('Owned terms snapshot')
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([target],list(program.iterdir()))
        self.assertEqual(b'preserve collision',target.read_bytes())
        target.unlink()
        self.rejected(self.crt_mock()+f"$plan=Get-AppLocalCrtPlan {quote(tools)} 'v145';[IO.File]::WriteAllText({quote(source/names[0])},'changed');Install-AppLocalCrt $plan {quote(program)} {quote(terms)}")
        self.assertEqual([],list(program.iterdir()))

    def test_native_import_closure_function_runs_source_bound_helper_with_exact_architecture(self):
        from suite.tests.test_crt import CrtImportClosureTests
        from suite.tests.test_payload import pe
        runtime=self.root/'runtime';runtime.mkdir()
        CrtImportClosureTests().fixture(runtime)
        (runtime/'program/soffice.bin').write_bytes(pe(0xaa64))
        evidence=self.root/'evidence';evidence.mkdir()
        repo=SOURCE.parents[2]
        raw=self.ps(f"Invoke-CrtImportAudit {quote(os.sys.executable)} {quote(repo)} {quote(runtime)} {quote(evidence)}|ConvertTo-Json -Depth 12 -Compress")
        proof=json.loads(raw.splitlines()[-1])
        self.assertTrue(proof['passed']);self.assertEqual('arm64',proof['architecture'])
        self.assertEqual(9,proof['checkedPeCount'])
        self.assertTrue((evidence/'crt-import-closure.json').is_file())
        self.assertTrue((evidence/'crt-import-closure.command.json').is_file())

    def test_isql_oracle_requires_exact_committed_rows_and_rollback(self):
        output=self.root/'isql.log'
        output.write_text('ROW_COUNT 2\nTOTAL 68\nROW_ONE 1\nROW_THREE 1\n')
        self.ps(f"Assert-IsqlOutput {quote(output)}")
        output.write_text('ROW_COUNT 2\nTOTAL 42\nROW_ONE 1\nROW_THREE 1\n')
        self.rejected(f"Assert-IsqlOutput {quote(output)}")
        sql=self.ps("Get-IsqlSql -DatabasePath 'C:\\owned\\proof.fdb'|ConvertTo-Json -Compress")
        sql=json.loads(sql)
        self.assertIn('ROLLBACK;',sql['create'])
        self.assertIn('DELETE FROM OPENGEUL_ARM64_PROBE',sql['create'])
        self.assertIn('ROW_THREE',sql['verify'])

    def test_isql_verify_quotes_reserved_result_alias_without_changing_columns(self):
        sql=json.loads(self.ps("Get-IsqlSql -DatabasePath 'C:\\owned\\proof.fdb'|ConvertTo-Json -Compress"))
        aliases=re.findall(r'\bAS\s+("[^"]+"|[A-Z_]+)',sql['verify'])
        self.assertEqual(['ROW_COUNT','TOTAL','ROW_ONE','ROW_THREE'],[name.strip('"') for name in aliases])
        # Firebird 3.0.13 keywords.cpp marks ROW_COUNT reserved; parse.y's
        # symbol_item_alias_name accepts SYMBOL, not that context-variable token.
        # A double-quoted identifier becomes SYMBOL and keeps SET LIST's label.
        for alias in aliases:
            if alias.strip('"') in {'ROW_COUNT'}:
                self.assertEqual('"'+alias.strip('"')+'"',alias,'Reserved Firebird result alias must be delimited')
        self.assertIn('COUNT(*) AS ',sql['verify'])
        self.assertIn('SUM(AMOUNT) AS TOTAL',sql['verify'])
        self.assertIn('WHEN ID=1 AND AMOUNT=55 THEN 1 ELSE 0 END) AS ROW_ONE',sql['verify'])
        self.assertIn('WHEN ID=3 AND AMOUNT=13 THEN 1 ELSE 0 END) AS ROW_THREE',sql['verify'])
        self.assertIn('FROM OPENGEUL_ARM64_PROBE;',sql['verify'])

    def test_full_qualification_rejects_missing_base_native_or_crud_semantics(self):
        report=self.root/'base.json'
        good={'schemaVersion':1,'passed':True,'guiVerified':False,'nativeProcesses':[{'processMachine':0,'nativeMachine':43620,'role':'uno-python'},{'processMachine':0,'nativeMachine':43620,'role':'uno-host','jobOwned':True,'phase':'create'},{'processMachine':0,'nativeMachine':43620,'role':'uno-host','jobOwned':True,'phase':'reopen'}],'rows':[{'id':1,'text':'Engine-OpenGeul-base 한글','amount':42}],'independentReopenVerified':True}
        report.write_text(json.dumps(good))
        self.ps(f"Assert-BaseProof {quote(report)}|Out-Null")
        for field,value in [('passed',False),('rows',[]),('independentReopenVerified',False),('nativeProcesses',[{'processMachine':34404,'nativeMachine':43620}]),('nativeProcesses',[{'processMachine':0,'nativeMachine':43620,'role':'soffice-launcher'}]*3)]:
            report.write_text(json.dumps(dict(good,**{field:value})))
            self.rejected(f"Assert-BaseProof {quote(report)}")


if __name__=='__main__':unittest.main()
