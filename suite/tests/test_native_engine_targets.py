"""Finite authenticated target policy; portable contracts, never compiler proof."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote

POLICY = SOURCE.parents[1]/'engine-build/native-targets.json'


class NativeEngineTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def ps(self, body):
        script = self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+'\n'+body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def rejected(self, body):
        self.ps("$rejected=$false;try { "+body+" } catch { if($_.Exception -is [Management.Automation.CommandNotFoundException]){throw};$rejected=$true };if(-not $rejected){throw 'Unsafe target accepted'}")

    def test_fixed_target_facts_and_manifest_authentication(self):
        policy = json.loads(POLICY.read_text())
        self.assertEqual({'schemaVersion', 'targets'}, set(policy))
        self.assertEqual(1, policy['schemaVersion'])
        self.assertEqual({'arm64', 'x64'}, set(policy['targets']))
        pin = json.loads((POLICY.parent/'source-build.json').read_text())['nativeTargets']
        self.assertEqual({'filename': POLICY.name, 'size': POLICY.stat().st_size,
                          'sha256': hashlib.sha256(POLICY.read_bytes()).hexdigest()}, pin)
        for arch, machine, cpu, triple, distro, year, toolset, tools, recipe, version, runner, runner_arch in (
            ('arm64', 0xaa64, 'AARCH64', 'aarch64-pc-cygwin', 'LibreOfficeWinArm64', '2026', 'v145', 'Hostarm64/arm64', 'windows-arm64-v1', 1, 'windows-11-arm', 'ARM64'),
            ('x64', 0x8664, 'X86_64', 'x86_64-pc-cygwin', 'LibreOfficeWin64', '2022', 'v143', 'Hostx64/x64', 'windows-x64-common-v2', 2, 'windows-2022', 'X64')):
            suffix = '-x64' if arch == 'x64' else ''
            expected = dict(architecture=arch, nativeMachine=machine, productMachine=machine, processMachine=0,
                configureCpu=cpu, configureTriple=triple, distro=distro, compilerYear=year, toolset=toolset,
                compilerTools=tools, sourceRecipe=recipe, proofVersion=version, runner=runner, runnerArchitecture=runner_arch,
                requiredBuildTypes=['FIREBIRD', 'LIBATOMIC_OPS', 'LIBTOMMATH'] if arch == 'arm64' else ['FIREBIRD', 'LIBTOMMATH'],
                workflow=f'.github/workflows/office-native-engine{suffix}.yml',
                ref=f'refs/heads/work/opengeul-office-native-engine{suffix}', job=f'native-firebird-and-office{suffix}',
                artifactPrefix=f'opengeul-native-{arch}-engine-', archive=f'OpenGeul-Office-engine-{arch}.zip',
                crtRedistributionUrl=f'https://learn.microsoft.com/en-us/visualstudio/releases/{year}/redistribution')
            self.assertEqual(expected, policy['targets'][arch])
            resolved = json.loads(self.ps(f"Get-NativeEngineTarget '{arch}'|ConvertTo-Json -Depth 8 -Compress"))
            self.assertEqual(expected, resolved)
            names = json.loads(self.ps(f"@(Get-CrtNames '{arch}')|ConvertTo-Json -Compress"))
            self.assertEqual(8 if arch == 'arm64' else 9, len(names))
            self.assertEqual(arch == 'x64', 'vcruntime140_1.dll' in names)

    def test_target_policy_rejects_compiler_profile_swaps_and_mixed_pairs(self):
        original = json.loads(POLICY.read_text())
        path, pin_path = self.root/'compiler-policy.json', self.root/'compiler-pin.json'
        def validate(policy, architecture):
            raw = json.dumps(policy).encode()
            path.write_bytes(raw)
            pin_path.write_text(json.dumps(dict(filename='native-targets.json', size=len(raw),
                                                sha256=hashlib.sha256(raw).hexdigest())))
            return f"ConvertFrom-NativeEngineTargetPolicy ([IO.File]::ReadAllBytes({quote(path)})) (Get-Content {quote(pin_path)} -Raw|ConvertFrom-Json -AsHashtable) '{architecture}'"
        for architecture, expected in (('arm64', ('2026', 'v145')), ('x64', ('2022', 'v143'))):
            self.ps(validate(original, architecture))
            for year, toolset in (('2022', 'v143'), ('2026', 'v145'), ('2022', 'v145'),
                                  ('2026', 'v143'), ('2050', 'v149')):
                if (year, toolset) == expected:
                    continue
                with self.subTest(architecture=architecture, year=year, toolset=toolset):
                    changed = json.loads(json.dumps(original))
                    changed['targets'][architecture].update(compilerYear=year, toolset=toolset,
                        crtRedistributionUrl=f'https://learn.microsoft.com/en-us/visualstudio/releases/{year}/redistribution')
                    call = validate(changed, architecture)
                    self.ps("$rejected=$false;try { "+call+" } catch { "
                            "if($_.Exception.Message -cne 'Native target architecture/compiler identity differs.'){throw};"
                            "$rejected=$true };if(-not $rejected){throw 'Compiler profile drift accepted'}")

    def test_target_policy_rejects_unknown_architecture_rows_hash_and_path_injection(self):
        original = json.loads(POLICY.read_text())
        def validate(value, pin_change=None, raw=None):
            raw = json.dumps(value).encode() if raw is None else raw
            path = self.root/'synthetic-policy.json'; path.write_bytes(raw)
            pin = dict(filename='native-targets.json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            pin.update(pin_change or {})
            pin_path = self.root/'pin.json'; pin_path.write_text(json.dumps(pin))
            return f"ConvertFrom-NativeEngineTargetPolicy ([IO.File]::ReadAllBytes({quote(path)})) (Get-Content {quote(pin_path)} -Raw|ConvertFrom-Json -AsHashtable) 'arm64'"
        self.ps(validate(original))
        for change in ({'sha256': '0'*64}, {'size': 1}, {'filename': '../native-targets.json'}, {'filename': str(POLICY)}, {'extra': 'injected'}):
            self.rejected(validate(original, change))
        mutations = []
        for action in (
            lambda p: p['targets'].update(x86=dict(p['targets']['x64'])),
            lambda p: p['targets'].pop('x64'),
            lambda p: p.update(extra=True),
            lambda p: p.update(schemaVersion=True),
            lambda p: p['targets']['arm64'].update(extra='injected'),
            lambda p: p['targets']['arm64'].update(architecture='x64'),
            lambda p: p['targets']['arm64'].update(nativeMachine=0x8664),
            lambda p: p['targets']['x64'].update(configureCpu='AARCH64'),
            lambda p: p['targets']['x64'].update(configureTriple='aarch64-pc-cygwin'),
            lambda p: p['targets']['x64'].update(distro='LibreOfficeWinArm64'),
            lambda p: p['targets']['x64'].update(sourceRecipe='windows-arm64-v1'),
            lambda p: p['targets']['x64'].update(proofVersion='2'),
            lambda p: p['targets']['x64'].update(requiredBuildTypes=['FIREBIRD', 'FIREBIRD']),
            lambda p: p['targets']['x64'].update(workflow='../injected.yml'),
            lambda p: p['targets']['x64'].update(crtRedistributionUrl='https://example.invalid/terms')):
            changed = json.loads(json.dumps(original)); action(changed); mutations.append(changed)
        for index, changed in enumerate(mutations):
            with self.subTest(mutation=index):
                self.rejected(validate(changed))
        self.rejected(validate(original, raw=POLICY.read_bytes().replace(b'"schemaVersion": 1', b'"schemaVersion": 1, "schemaVersion": 1')))
        for invocation in ("Get-NativeEngineTarget 'x86'", "Get-NativeEngineTarget 'X64'", "Get-NativeEngineTarget 'ARM64'", "Get-NativeEngineTarget -Path '/synthetic'", "Get-NativeEngineTarget -Targets @{}", "Get-NativeEngineTarget -Architecture 'arm64' -PolicyPath '/synthetic'"):
            self.rejected(invocation)

    def test_arm_defaults_outputs_configure_and_diagnostics_are_frozen(self):
        self.ps("""
$a=Get-NativeEngineTarget; $b=Get-NativeEngineTarget 'arm64'
if(($a|ConvertTo-Json -Compress) -cne ($b|ConvertTo-Json -Compress)){throw 'ARM default drift'}
$a.workflow='injected';if((Get-NativeEngineTarget).workflow -ceq 'injected'){throw 'Mutable policy cache'}
$normal=Get-NativeEngineBuildMode Full; $diag=Get-NativeEngineBuildMode Full -CalcDispatchDiagnostic
if($normal.archive -cne 'OpenGeul-Office-engine-arm64.zip' -or $normal.receipt -cne 'source-build-receipt.json' -or -not $normal.acceptanceEligible){throw 'ARM output drift'}
if($diag.archive -cne 'OpenGeul-Office-engine-arm64-calc-dispatch.zip' -or $diag.acceptanceEligible -or $diag.fullEngineQualified){throw 'Diagnostic output drift'}
$args=@(Get-ConfigureArguments)
foreach($arg in @('--with-distro=LibreOfficeWinArm64','--build=aarch64-pc-cygwin','--host=aarch64-pc-cygwin','--with-visual-studio=2026')){if($arg -cnotin $args){throw 'ARM configure drift'}}
if((Get-NativeEngineTarget).toolset -cne 'v145' -or (Get-NativeEngineTarget).sourceRecipe -cne 'windows-arm64-v1'){throw 'ARM recipe drift'}
""")

    def test_native_host_rejects_wrong_machine_for_each_finite_target(self):
        for arch, machine in (('arm64', 0xaa64), ('x64', 0x8664)):
            self.ps(f"Assert-NativeBuildHost @{{isWindows=$true;processMachine=0;nativeMachine={machine}}} '{arch}'")
            for windows, process, native in (('$false', 0, machine), ('$true', machine, machine), ('$true', 0, 0x8664 if arch == 'arm64' else 0xaa64)):
                self.rejected(f"Assert-NativeBuildHost @{{isWindows={windows};processMachine={process};nativeMachine={native}}} '{arch}'")

    def owner_context(self, arch):
        suffix = '-x64' if arch == 'x64' else ''
        return """
$ref='refs/heads/work/opengeul-office-native-engine%s';$sha='a'*40
$context=@{GITHUB_ACTIONS='true';RUNNER_ENVIRONMENT='github-hosted';RUNNER_OS='Windows';RUNNER_ARCH='%s';GITHUB_REPOSITORY='ATLKR/OpenGeul';GITHUB_REPOSITORY_OWNER='ATLKR';GITHUB_EVENT_NAME='push';GITHUB_JOB='native-firebird-and-office%s';GITHUB_REF=$ref;GITHUB_WORKFLOW_REF=('ATLKR/OpenGeul/.github/workflows/office-native-engine%s.yml@'+$ref);GITHUB_RUN_ATTEMPT='1';GITHUB_ACTOR='ATLKR';GITHUB_ACTOR_ID='65988341';GITHUB_SHA=$sha;GITHUB_WORKFLOW_SHA=$sha;GITHUB_RUN_ID='123'}
$event=@{repository=@{full_name='ATLKR/OpenGeul';private=$false;id=1405493151};sender=@{login='ATLKR';id=65988341;type='User'};ref=$ref;deleted=$false;after=$sha}
""" % (suffix, 'X64' if arch == 'x64' else 'ARM64', suffix, suffix)

    def test_no_symbol_full_requires_owner_first_push_attempt_and_source(self):
        for arch in ('arm64', 'x64'):
            self.ps(self.owner_context(arch)+f"""
Assert-NativeEngineOwnerPush $context $event '{arch}'
foreach($key in @($context.Keys)) {{
 $bad=$context.Clone();$bad[$key]='wrong';$rejected=$false
 try {{Assert-NativeEngineOwnerPush $bad $event '{arch}'}} catch {{$rejected=$true}}
 if(-not $rejected){{throw 'Owner/source context drift accepted'}}
}}
foreach($key in @('ref','deleted','after','sender','repository')) {{
 $bad=$event.Clone();$bad.Remove($key);$rejected=$false
 try {{Assert-NativeEngineOwnerPush $context $bad '{arch}'}} catch {{$rejected=$true}}
 if(-not $rejected){{throw 'Incomplete event accepted'}}
}}
""")
        for phase, architecture in (('Full', ''), ('Full', "-Architecture 'arm64'"),
                                    ('Full', "-Architecture 'x64'"), ('FULL', ''),
                                    ('full', "-Architecture 'arm64'"), ('fUlL', "-Architecture 'x64'")):
            self.ps(f"""
$script:gate=0
function Assert-NativeEngineEnvironment {{param($Architecture);$script:gate++;throw 'Observed normal Full owner admission'}}
try {{Invoke-NativeEngineBuild {phase} {quote(self.root/'work')} {quote(self.root/'output')} '' 4 {architecture}}} catch {{if($_.Exception.Message -cne 'Observed normal Full owner admission'){{throw}}}}
if($script:gate -ne 1 -or (Test-Path {quote(self.root/'work')})){{throw 'Full admission was bypassed or late'}}
""")

    def test_normal_full_real_environment_gate_and_arm_default_receipts(self):
        event_path = self.root/'synthetic-event.json'
        prefix = self.owner_context('arm64')+f"""
$event|ConvertTo-Json -Depth 8|Set-Content {quote(event_path)}
foreach($key in $context.Keys){{[Environment]::SetEnvironmentVariable($key,$context[$key])}}
$env:GITHUB_EVENT_PATH={quote(event_path)}
function Get-NativeBuildHost {{throw 'Observed ARM host boundary'}}
"""
        for label, options in (('omitted', ''), ('explicit', '-Architecture arm64')):
            work, output = self.root/(label+'-work'), self.root/(label+'-evidence')
            self.ps(prefix+f"try {{Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4 {options}}} catch {{if($_.Exception.Message -cne 'Observed ARM host boundary'){{throw}}}}")
            receipt = json.loads((output/'source-build-receipt.json').read_text())
            for key, value in dict(schemaVersion=1, kind='native-office-engine-source-build', phase='Full',
                                   architecture='arm64', status='failed', passed=False, fullEngineQualified=False,
                                   acceptanceEligible=False, guiVerified=False, stage='native-host').items():
                self.assertEqual(value, receipt[key], key)
            self.assertFalse((output/'OpenGeul-Office-engine-arm64.zip').exists())
        for key, value in (('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_WORKFLOW_SHA', 'b'*40)):
            work, output = self.root/(key+'-work'), self.root/(key+'-evidence')
            self.rejected(prefix+f"$env:{key}='{value}';Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4")
            self.assertFalse(output.exists())

    def test_x64_invalid_modes_fail_before_any_build_or_qualified_output(self):
        for options in ("Firebird", "Full -MutexSymbols", "Full -CalcDispatchDiagnostic", "Firebird -MutexSymbols -CalcDispatchDiagnostic"):
            self.ps(f"""
function Assert-NativeEngineEnvironment {{param($Architecture)}}
function Assert-MutexSymbolsEnvironment {{throw 'Unexpected symbols admission'}}
function New-BuildDirectories {{throw 'Invalid x64 mode reached build directories'}}
$rejected=$false
try {{Invoke-NativeEngineBuild {options} -WorkDirectory {quote(self.root/'work')} -OutputDirectory {quote(self.root/'output')} -SourceLockPath '' -Jobs 4 -Architecture x64}} catch {{
 if($_.Exception.Message -notmatch 'x64.*normal Full'){{throw}};$rejected=$true
}}
if(-not $rejected -or (Test-Path {quote(self.root/'output')})){{throw 'Invalid x64 mode admitted'}}
""")

    def test_target_resolution_preserves_single_script_budget(self):
        self.ps("""
$script:NativeEngineBuildBudget=New-NativeBuildBudget '' 1
$before=$script:NativeEngineBuildBudget;$remaining=Get-NativeBuildRemaining
foreach($architecture in @('arm64','x64')){Get-NativeEngineTarget $architecture|Out-Null}
if(-not [object]::ReferenceEquals($before,$script:NativeEngineBuildBudget)){throw 'Budget owner/reset drift'}
if((Get-NativeBuildRemaining) -gt $remaining){throw 'Budget allowance reset'}
""")
        raw = SOURCE.read_text()
        self.assertEqual(2, raw.count('$script:NativeEngineBuildBudget=New-NativeBuildBudget'))
        self.ps("""
foreach($name in @('Invoke-NativeEngineBuild','Invoke-NativeEngineUnitGate')) {
 $body=(Get-Command $name).ScriptBlock.ToString()
 $initializations=[regex]::Matches($body,'\\$script:NativeEngineBuildBudget=New-NativeBuildBudget[^\\r\\n]*')
 if($initializations.Count -ne 1 -or $initializations[0].Value -cne '$script:NativeEngineBuildBudget=New-NativeBuildBudget $DeadlineUtc') {
  throw 'Entrypoint must use the one original absolute deadline'
 }
}
""")
        self.assertIn('[ValidateRange(0.000001,330)]', raw)
        self.assertNotIn('Import-Module', raw)


if __name__ == '__main__': unittest.main()
