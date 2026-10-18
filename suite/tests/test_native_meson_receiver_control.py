"""Portable controller/source checks; actual Windows feasibility is a separate run."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'suite/scripts/probe-native-meson-receiver.ps1'
PREPARE = ROOT / 'suite/diagnostics/native-meson-receiver/prepare.py'
PWSH = os.environ.get('PWSH', '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def prepare_module():
    spec = importlib.util.spec_from_file_location('meson_control_prepare', PREPARE)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ControllerContractTests(unittest.TestCase):
    def ps(self, body):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.ps1'
            path.write_text("$ErrorActionPreference='Stop'\n. " + quote(SCRIPT) + '\n' + body)
            result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(path)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return result.stdout.strip()

    def test_normal_completion_rejects_cleanup_timeout_crash_and_unrelated_make_exit(self):
        self.ps("""
$good=@{pipeDrainComplete=$true;forcedTermination=$false;directProcessDeathVerified=$true;processTreeCleanup='not-requested';cleanupErrors=@();exitCode=2;passed=$false}
$r=Assert-MesonCompletion ([pscustomobject]$good) @(0,2)
if($r.succeeded -or $r.exitCode -ne 2){throw 'Ordinary make failure was altered'}
foreach($change in @(@{forcedTermination=$true},@{pipeDrainComplete=$false},@{directProcessDeathVerified=$false},@{processTreeCleanup='unproved-after-direct-process-exit'},@{cleanupErrors=@('error')},@{exitCode=3},@{exitCode=-1073741819},@{exitCode=0;passed=$false})) {
 $bad=$good.Clone();foreach($k in $change.Keys){$bad[$k]=$change[$k]}
 $rejected=$false;try{Assert-MesonCompletion ([pscustomobject]$bad) @(0,2)|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw ('Unproved command accepted '+($change|ConvertTo-Json -Compress))}
}
""")

    def test_original_red_requires_exact_compiler_failure_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'meson.log'
            expected = "/cygdrive/c/PROGRA~1/VS/Hostarm64/arm64/cl.exe"
            good = ("Running `" + expected + " /?` gave \"[WinError 2] The system cannot find the file specified\"\n"
                    "ERROR: Unknown compiler(s): [['" + expected + "']]\n")
            log.write_text(good)
            self.ps('Assert-MesonOriginalFailure '+quote(log)+' '+quote(expected)+'|Out-Null')
            for changed in (good.replace('[WinError 2]', '[WinError 5]'),
                            good.replace(expected, 'C:/other/cl.exe'),
                            good + 'access violation\n', 'Ninja not found\n'):
                log.write_text(changed)
                self.ps('$rejected=$false;try{Assert-MesonOriginalFailure '+quote(log)+' '+quote(expected)+
                        '|Out-Null}catch{$rejected=$true};if(-not $rejected){throw "Unrelated RED accepted"}')

    def test_native_identity_binds_actual_pid_raw_creation_ticks_and_arm64(self):
        self.ps("""
$good=[pscustomobject]@{pid=21;creationTimeRawTicks='134050123456789123';processMachine=0;nativeMachine=43620}
Assert-MesonNativeIdentity $good|Out-Null
foreach($bad in @(@{pid=0;creationTimeRawTicks='134050123456789123';processMachine=0;nativeMachine=43620},@{pid=21;creationTimeRawTicks='1.3405e17';processMachine=0;nativeMachine=43620},@{pid=21;creationTimeRawTicks='134050123456789123';processMachine=34404;nativeMachine=43620})) {
 $rejected=$false;try{Assert-MesonNativeIdentity ([pscustomobject]$bad)|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw 'Native process identity accepted without actual evidence'}
}
""")

    def test_dot_source_is_inert_and_script_parses(self):
        self.ps("$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile("+
                quote(SCRIPT)+",[ref]$tokens,[ref]$errors)|Out-Null;if($errors.Count){throw ($errors|Out-String)};"+
                "if(-not (Get-Command Invoke-NativeMesonReceiverControl)){throw 'Controller missing'}")

    def test_importing_production_helpers_preserves_workflow_deadline(self):
        self.ps(". "+quote(SCRIPT)+" -DeadlineUtc '2030-01-01T00:18:00.0000000Z';"+
                "if($DeadlineUtc -cne '2030-01-01T00:18:00.0000000Z'){throw 'Driver import reset the workflow deadline'}")

    def test_candidate_pkgconf_requires_fixture_selection_and_sentinels(self):
        self.ps("""
$queries=@{
 'tool-version'=[pscustomobject]@{stdout="2.4.3`n"};
 versions=[pscustomobject]@{stdout="1.3.15`n78.3`n"};
 paths=[pscustomobject]@{stdout="C:/fixtures/graphite/graphite2-uninstalled.pc`nC:/fixtures/icu/icu-uc-uninstalled.pc`n"};
 'graphite-sentinel'=[pscustomobject]@{stdout='graphite'};'icu-sentinel'=[pscustomobject]@{stdout='icu'};
 'prefix-path'=[pscustomobject]@{stdout='C:/fixtures/prefix pc/prefix-control.pc'};
 cflags=[pscustomobject]@{stdout='-IC:/fixtures/include'};libs=[pscustomobject]@{stdout='C:/fixtures/fixture.lib'}
}
Assert-MesonFixtureQueries $queries 'C:/fixtures'|Out-Null
foreach($name in @('tool-version','versions','paths','graphite-sentinel','icu-sentinel','prefix-path','cflags','libs')) {
 $bad=$queries.Clone();$bad[$name]=[pscustomobject]@{stdout=''}
 $rejected=$false;try{Assert-MesonFixtureQueries $bad 'C:/fixtures'|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw ('Machine fallback or empty '+$name+' accepted')}
}
$wrongVersion=$queries.Clone();$wrongVersion['tool-version']=[pscustomobject]@{stdout='2.4.4'}
$rejected=$false;try{Assert-MesonFixtureQueries $wrongVersion 'C:/fixtures'|Out-Null}catch{$rejected=$true}
if(-not $rejected){throw 'A different pkgconf version was accepted'}
""")


class PrepareContractTests(unittest.TestCase):
    def test_exact_approved_planner_output_is_installed_and_real_recipe_is_retained(self):
        module = prepare_module()
        with tempfile.TemporaryDirectory(prefix='receiver-source-proof-') as folder:
            root = Path(folder)
            repo = root / 'repo'
            port = repo / 'suite/engine-build'
            port.mkdir(parents=True)
            for name in ('enable_firebird_arm64.py', 'source-build.json'):
                shutil.copyfile(ROOT / 'suite/engine-build' / name, port / name)
            work, evidence = root / 'work', root / 'evidence'
            work.mkdir(); evidence.mkdir()
            result = module.prepare(repo, work, evidence, sys.executable,
                                    'C:/pinned/meson.py', 'C:/pinned/pkgconf.exe',
                                    '/cygdrive/c/PROGRA~1/VS/Hostarm64/arm64/cl.exe',
                                    '/cygdrive/c/Python:/cygdrive/c/Windows/System32')
            self.assertEqual('b30ba8ae89b1fae10a3a634579b6284b1de33f80', result['productionBaseCommit'])
            self.assertEqual('f959b6f564baf45777f531b588932b2e969bdfbf21ffdb41630874838415cfcb',
                             result['installedRecipeSha256'])
            installed = Path(result['installedRecipe']).read_bytes()
            self.assertEqual(result['returnedCandidateSha256'], hashlib.sha256(installed).hexdigest())
            self.assertFalse(result['fullInstallerExecuted'])
            self.assertFalse(result['fullHarfBuzzOptionsExecuted'])
            self.assertEqual(4, len(result['observations']))
            cross_payload = None
            for observation in result['observations']:
                self.assertEqual(Path(result['dependencies']), Path(observation['directory']).parent)
                makefile = Path(observation['makefile']).read_text()
                recipe = (evidence / (('original' if observation['arm'] == 'original' else 'effective') +
                          '-ExternalProject_harfbuzz.mk')).read_text()
                self.assertTrue(makefile.endswith(recipe))
                self.assertNotIn('MAKE_HOST :=', makefile)
                self.assertIn('define gb_ExternalProject_run\n', makefile)
                self.assertIn('builtin-make-host.txt,$(MAKE_HOST)', makefile)
                self.assertIn('EXTERNAL_WORKDIR := .\n', makefile)
                self.assertIn('gb_UnpackedTarball_workdir := ..\n', makefile)
                cross = Path(observation['crossFile'])
                self.assertEqual(Path(result['dependencies']) / 'harfbuzz/cross-file.txt', cross)
                self.assertFalse(cross.exists())
                dry = subprocess.run([shutil.which('make'), '--no-print-directory', '-n', '-f', observation['makefile']],
                                     cwd=observation['directory'], text=True, capture_output=True, timeout=15)
                self.assertEqual(0, dry.returncode, dry.stdout + dry.stderr)
                self.assertIn('-Dsubset=enabled', dry.stdout)
                self.assertIn('-Dicu_builtin=true', dry.stdout)
                self.assertIn('compile -C builddir libs', dry.stdout)
                payload = cross.read_bytes()
                self.assertTrue(payload.startswith(b'[binaries]\n'))
                self.assertIn(b"c = ['/cygdrive/c/PROGRA~1/VS/Hostarm64/arm64/cl.exe']", payload)
                if cross_payload is not None:
                    self.assertEqual(cross_payload, payload)
                cross_payload = payload
                self.assertFalse((work / 'Dependency').exists())
                cross.unlink()

    def test_changed_production_module_rejects_before_control_source_writes(self):
        module = prepare_module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); repo = root / 'repo'; port = repo / 'suite/engine-build'
            port.mkdir(parents=True)
            for name in ('enable_firebird_arm64.py', 'source-build.json'):
                shutil.copyfile(ROOT / 'suite/engine-build' / name, port / name)
            with (port / 'enable_firebird_arm64.py').open('a') as stream:
                stream.write('\n# changed production bytes\n')
            work, evidence = root / 'work', root / 'evidence';work.mkdir();evidence.mkdir()
            with self.assertRaisesRegex(ValueError, 'approved immutable binding'):
                module.prepare(repo, work, evidence, sys.executable, 'C:/meson.py', 'C:/pkgconf.exe',
                               '/cygdrive/c/cl.exe', '/cygdrive/c/Python:/cygdrive/c/Windows/System32')
            self.assertEqual([], list(work.iterdir()))
            self.assertEqual([], list(evidence.iterdir()))

    def test_source_planner_hash_is_exact_function_code(self):
        module = prepare_module()
        source = 'import os\n\ndef wanted(x):\n    return x+1\n\ndef other():\n    pass\n'
        self.assertEqual(hashlib.sha256(b'def wanted(x):\n    return x+1').hexdigest(),
                         module.function_hash(source, 'wanted'))
        with self.assertRaises(ValueError):
            module.function_hash(source, 'missing')

    def test_authentic_macro_extraction_rejects_duplicate_or_missing_definitions(self):
        module = prepare_module()
        source = 'prefix\ndefine real\n$(1) && touch $@\nendef\nsuffix\n'
        self.assertEqual('define real\n$(1) && touch $@\nendef\n', module.authentic_macro(source, 'real'))
        for raw in ('prefix', source + source):
            with self.assertRaises(ValueError):
                module.authentic_macro(raw, 'real')

    def test_make_values_fail_closed_on_make_metacharacters(self):
        module = prepare_module()
        self.assertEqual('C:/Program Files/Tool', module.make_value('C:/Program Files/Tool'))
        for value in ('a$b', 'a#b', 'a\nb', 'a\rb', 'a\0b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.make_value(value)


class ShallowAncestryContractTests(unittest.TestCase):
    def test_two_parent_hops_require_three_checkout_generations(self):
        # Local test objects only: no clone, network, remote or source commit
        # fabrication. Git's actual shallow boundary controls the same gate.
        with tempfile.TemporaryDirectory(prefix='receiver-shallow-fixture-') as folder:
            root = Path(folder)
            def git(*arguments, check=True):
                return subprocess.run(['git', '-C', str(root), *arguments], text=True,
                                      capture_output=True, check=check, timeout=10)
            git('init', '-q')
            git('-c', 'user.name=Receiver fixture', '-c', 'user.email=receiver@example.invalid',
                'commit', '-q', '--allow-empty', '-m', 'local shallow fixture parent')
            parent = git('rev-parse', 'HEAD').stdout.strip()
            git('-c', 'user.name=Receiver fixture', '-c', 'user.email=receiver@example.invalid',
                'commit', '-q', '--allow-empty', '-m', 'local shallow fixture Control1')
            middle = git('rev-parse', 'HEAD').stdout.strip()
            git('-c', 'user.name=Receiver fixture', '-c', 'user.email=receiver@example.invalid',
                'commit', '-q', '--allow-empty', '-m', 'local shallow fixture child')
            child = git('rev-parse', 'HEAD').stdout.strip()
            shallow = root / '.git/shallow'
            shallow.write_text(middle + '\n')
            self.assertEqual(1, git('merge-base', '--is-ancestor', parent, 'HEAD', check=False).returncode)
            shallow.write_text(parent + '\n')
            self.assertEqual(0, git('merge-base', '--is-ancestor', parent, 'HEAD', check=False).returncode)
            self.assertEqual('', git('remote').stdout)


if __name__ == '__main__':
    unittest.main()
