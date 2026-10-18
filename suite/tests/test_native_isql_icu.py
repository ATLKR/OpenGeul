"""Portable child-environment/compiled-ICU boundaries; no Windows loader claim."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'suite/scripts/build-native-engine.ps1'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class NativeIsqlIcuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-isql-icu-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "owned source's tree"
        self.icu = self.source / 'workdir/UnpackedTarball/icu/source/lib'
        self.icu.mkdir(parents=True)
        self.names = ('icudt78.dll', 'icuuc78.dll', 'icuin78.dll')
        for name in self.names:
            self.pe(self.icu / name)
        self.config = "@{ICU_MAJOR='78';ICU_MINOR='3';SYSTEM_ICU='';MSVC_USE_DEBUG_RUNTIME=''}"

    def pe(self, path, machine=0xaa64, dll=True):
        raw = bytearray(512)
        raw[:2] = b'MZ'
        struct.pack_into('<I', raw, 60, 128)
        raw[128:132] = b'PE\0\0'
        struct.pack_into('<H', raw, 132, machine)
        struct.pack_into('<H', raw, 150, 0x2002 if dll else 2)
        struct.pack_into('<H', raw, 152, 0x20b)
        marker = path.name.encode('ascii')
        raw[256:256 + len(marker)] = marker
        path.write_bytes(raw)

    def ps(self, body):
        script = self.root / 'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(DRIVER) + '\n' + body, encoding='utf-8')
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def rejected(self, body):
        self.ps("$caught=$false;try {" + body + "|Out-Null}catch{$caught=$true};"
                "if(-not $caught){throw 'Unsafe ICU/environment condition accepted'}")

    def plan(self):
        return 'Get-IsqlIcuPlan ' + quote(self.source) + ' ' + self.config

    def test_compiled_plan_binds_exact_release_triplet_native_pe_and_hashes(self):
        plan = json.loads(self.ps(self.plan() + '|ConvertTo-Json -Depth 8 -Compress'))
        self.assertEqual(str(self.icu), plan['directory'])
        self.assertEqual('78.3', plan['version'])
        self.assertEqual('arm64', plan['architecture'])
        self.assertEqual(list(self.names), [row['name'] for row in plan['files']])
        for row in plan['files']:
            path = self.icu / row['name']
            self.assertEqual(str(path), row['path'])
            self.assertEqual(0xaa64, row['machine'])
            self.assertEqual('nativeArm64', row['role'])
            self.assertEqual(path.stat().st_size, row['size'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])

    def test_compiled_plan_rejects_foreign_missing_linked_and_wrong_config(self):
        # First establish this function exists/accepts the good source. A missing
        # helper must not masquerade as all negative cases being rejected.
        self.ps(self.plan() + '|Out-Null')
        target = self.icu / self.names[1]
        native = target.read_bytes()
        for machine in (0x8664, 0x14c):
            self.pe(target, machine)
            self.rejected(self.plan())
        self.pe(target, dll=False)
        self.rejected(self.plan())
        target.unlink()
        self.rejected(self.plan())
        actual = self.root / 'actual-native.dll'
        actual.write_bytes(native)
        target.symlink_to(actual)
        self.rejected(self.plan())
        target.unlink()
        target.write_bytes(native)
        linked = self.root / 'linked-source'
        linked.symlink_to(self.source, target_is_directory=True)
        self.rejected('Get-IsqlIcuPlan ' + quote(linked) + ' ' + self.config)
        for old, new in (("ICU_MAJOR='78'", "ICU_MAJOR='79'"),
                         ("ICU_MINOR='3'", "ICU_MINOR='2'"),
                         ("SYSTEM_ICU=''", "SYSTEM_ICU='TRUE'"),
                         ("MSVC_USE_DEBUG_RUNTIME=''", "MSVC_USE_DEBUG_RUNTIME='TRUE'")):
            self.rejected('Get-IsqlIcuPlan ' + quote(self.source) + ' ' + self.config.replace(old, new))

    def test_plugin_plan_binds_native_engine_without_changing_config_or_files(self):
        firebird = self.root / 'firebird'
        plugins = firebird / 'plugins'
        plugins.mkdir(parents=True)
        engine = plugins / 'Engine12.dll'
        self.pe(engine)
        config = firebird / 'firebird.conf'
        config.write_bytes(b'Providers = Remote, Engine12, Loopback\n')
        before = {str(p.relative_to(firebird)): p.read_bytes() for p in firebird.rglob('*') if p.is_file()}
        plan = json.loads(self.ps('Get-IsqlPluginPlan ' + quote(firebird) + '|ConvertTo-Json -Depth 8 -Compress'))
        self.assertEqual(str(plugins), plan['directory'])
        self.assertEqual('arm64', plan['architecture'])
        self.assertEqual(1, len(plan['files']))
        row = plan['files'][0]
        self.assertEqual('Engine12.dll', row['name'])
        self.assertEqual(str(engine), row['path'])
        self.assertEqual(0xaa64, row['machine'])
        self.assertEqual('nativeArm64', row['role'])
        self.assertEqual(engine.stat().st_size, row['size'])
        self.assertEqual(hashlib.sha256(engine.read_bytes()).hexdigest(), row['sha256'])
        self.assertEqual(before, {str(p.relative_to(firebird)): p.read_bytes() for p in firebird.rglob('*') if p.is_file()})

    def test_plugin_plan_rejects_missing_foreign_executable_and_linked_engine(self):
        firebird = self.root / 'firebird'
        plugins = firebird / 'plugins'
        plugins.mkdir(parents=True)
        engine = plugins / 'Engine12.dll'
        self.pe(engine)
        command = 'Get-IsqlPluginPlan ' + quote(firebird)
        self.ps(command + '|Out-Null')
        original = engine.read_bytes()
        for machine in (0x8664, 0x14c):
            self.pe(engine, machine)
            self.rejected(command)
        self.pe(engine, dll=False)
        self.rejected(command)
        engine.unlink()
        self.rejected(command)
        actual = self.root / 'actual-engine.dll'
        actual.write_bytes(original)
        engine.symlink_to(actual)
        self.rejected(command)
        engine.unlink()
        engine.write_bytes(original)
        linked = self.root / 'linked-firebird'
        linked.symlink_to(firebird, target_is_directory=True)
        self.rejected('Get-IsqlPluginPlan ' + quote(linked))

    def test_real_children_receive_scoped_overrides_and_parent_default_and_failure_stay_intact(self):
        child = self.root / 'observe.py'
        child.write_text('import json,os,sys\nprint(json.dumps({"PATH":os.environ.get("PATH"),'
                         '"FIREBIRD":os.environ.get("FIREBIRD")}))\nsys.exit(int(sys.argv[1]))\n')
        state = self.root / 'parent.json'
        self.ps(f"""
$env:PATH='controller-path';$env:FIREBIRD='controller-firebird'
$overrides=@{{PATH={quote(str(self.icu) + os.pathsep + 'controller-path')};FIREBIRD='owned-firebird'}}
Invoke-LoggedCommand {quote(sys.executable)} @({quote(child)},'0') {quote(self.root)} {quote(self.root/'overridden')} -EnvironmentOverrides $overrides|Out-Null
Invoke-LoggedCommand {quote(sys.executable)} @({quote(child)},'0') {quote(self.root)} {quote(self.root/'default')}|Out-Null
$caught=$false;try {{Invoke-LoggedCommand {quote(sys.executable)} @({quote(child)},'7') {quote(self.root)} {quote(self.root/'failed')} -EnvironmentOverrides $overrides|Out-Null}}catch{{$caught=$true}}
if(-not $caught){{throw 'Failed child was accepted'}}
Write-BuildJson {quote(state)} @{{PATH=$env:PATH;FIREBIRD=$env:FIREBIRD}}
""")
        expected = {'PATH': str(self.icu) + os.pathsep + 'controller-path', 'FIREBIRD': 'owned-firebird'}
        for prefix in ('overridden', 'failed'):
            self.assertEqual(expected, json.loads((self.root / (prefix + '.stdout.log')).read_text()))
            receipt = json.loads((self.root / (prefix + '.command.json')).read_text())
            self.assertTrue(receipt['pipeDrainComplete'])
            self.assertTrue(receipt['directProcessDeathVerified'])
            self.assertFalse(receipt['forcedTermination'])
            self.assertEqual({key: hashlib.sha256(value.encode()).hexdigest() for key, value in expected.items()},
                             receipt['environmentOverrideSha256'])
            self.assertNotIn('controller-path', (self.root / (prefix + '.command.json')).read_text())
        failed = json.loads((self.root / 'failed.command.json').read_text())
        self.assertFalse(failed['passed'])
        self.assertEqual(7, failed['exitCode'])
        default = json.loads((self.root / 'default.command.json').read_text())
        self.assertTrue(default['passed'])
        self.assertNotIn('environmentOverrideSha256', default)
        inherited = {'PATH': 'controller-path', 'FIREBIRD': 'controller-firebird'}
        self.assertEqual(inherited, json.loads((self.root / 'default.stdout.log').read_text()))
        self.assertEqual(inherited, json.loads(state.read_text()))
        self.rejected(f"Invoke-LoggedCommand {quote(sys.executable)} @('-c','print(1)') {quote(self.root)} {quote(self.root/'forbidden')} -EnvironmentOverrides @{{SECRET='never-record-this'}}")
        self.assertNotIn('never-record-this', (self.root / 'forbidden.command.json').read_text())

    @unittest.skipIf(os.name == 'nt', 'Portable executable observer requires a POSIX shebang')
    def test_actual_isql_create_and_reopen_calls_use_same_child_only_environment(self):
        (self.root / 'firebird').mkdir()
        plugins = self.root / 'firebird/plugins'
        plugins.mkdir()
        self.pe(plugins / 'Engine12.dll')
        isql = self.root / 'observe-isql'
        isql.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                        'print(json.dumps({"PATH":os.environ.get("PATH"),'
                        '"FIREBIRD":os.environ.get("FIREBIRD"),"BOOT":os.environ.get("FIREBIRD_BOOT_BUILD"),"args":sys.argv[1:]}))\n')
        isql.chmod(0o700)
        self.ps(f"""
$source={quote(self.source)};$fbOutput={quote(self.root/'firebird')};$isql={quote(isql)}
$work={quote(self.root)};$evidence={quote(self.root)};$createSql='create.sql';$verifySql='verify.sql'
$receipt=@{{configuration={self.config};isql=@{{}}}};$env:PATH='parent-path';$env:FIREBIRD='parent-firebird'
$env:FIREBIRD_BOOT_BUILD=$null
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Driver syntax errors'}}
foreach($left in @('$receipt.isql.icu','$receipt.isql.plugins','$isqlEnvironment','$receipt.isql.environment')){{
 $rows=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq $left}},$true))
 if($rows.Count -eq 0 -and $left -ceq '$receipt.isql.plugins'){{continue}}
 if($rows.Count -ne 1){{throw ('Missing unique isql binding '+$left)}}
 Invoke-Expression $rows[0].Extent.Text
}}
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Invoke-LoggedCommand' -and $n.CommandElements[1].Extent.Text -ceq '$isql'}},$true))
if($calls.Count -ne 2){{throw 'Expected original create/reopen commands'}}
foreach($call in $calls){{Invoke-Expression $call.Extent.Text|Out-Null}}
if($env:PATH -cne 'parent-path' -or $env:FIREBIRD -cne 'parent-firebird'){{throw 'isql changed controller environment'}}
if($env:FIREBIRD_BOOT_BUILD){{throw 'isql enabled bootstrap mode'}}
Write-BuildJson {quote(self.root/'binding.json')} $receipt.isql
""")
        binding = json.loads((self.root / 'binding.json').read_text())
        for prefix in ('isql-create', 'isql-reopen'):
            child = json.loads((self.root / (prefix + '.stdout.log')).read_text())
            self.assertEqual(os.pathsep.join((str(self.icu), str(plugins), 'parent-path')), child['PATH'],
                             'Non-boot bare Engine12 cannot find the owned plugins directory')
            self.assertEqual(str(self.root / 'firebird'), child['FIREBIRD'])
            self.assertIsNone(child['BOOT'], 'Standalone proof must retain normal embedded mode')
            self.assertEqual(['-b', '-q'], child['args'][:2])
        self.assertEqual([str(self.icu), str(plugins)], binding['environment']['PATH']['prepend'])
        self.assertTrue(binding['environment']['PATH']['inheritParent'])
        self.assertEqual(str(self.root / 'firebird'), binding['environment']['FIREBIRD'])
        self.assertEqual(str(plugins), binding['plugins']['directory'])


if __name__ == '__main__':
    unittest.main()
