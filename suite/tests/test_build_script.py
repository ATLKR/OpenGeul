"""Build orchestration selects one architecture before invoking build tools."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which('pwsh')

HARNESS = r"""
param([string]$Root)
$ErrorActionPreference = 'Stop'
$global:EventsPath = Join-Path $Root 'events.jsonl'
function global:dotnet {
    @{command='dotnet'; arguments=@($args)} | ConvertTo-Json -Compress | Add-Content $global:EventsPath
    $outputIndex = [Array]::IndexOf($args, '-o')
    New-Item -ItemType Directory -Path $args[$outputIndex + 1] | Out-Null
    $global:LASTEXITCODE = 0
}
function global:python {
    @{command='python'; arguments=@($args)} | ConvertTo-Json -Compress | Add-Content $global:EventsPath
    if ($args[0] -eq 'suite/prepare.py') {
        $outputIndex = [Array]::IndexOf($args, '--output')
        New-Item -ItemType Directory -Path $args[$outputIndex + 1] | Out-Null
    } elseif ($args[0] -eq '-c') {
        [IO.File]::WriteAllText($args[-1], 'test archive')
    } else { throw 'Unexpected Python invocation.' }
    $global:LASTEXITCODE = 0
}
$buildArguments = Get-Content (Join-Path $Root 'arguments.json') -Raw | ConvertFrom-Json -AsHashtable
& (Join-Path $Root 'suite/scripts/build-suite.ps1') @buildArguments
"""


@unittest.skipUnless(PWSH, 'PowerShell runtime unavailable')
class BuildScriptTests(unittest.TestCase):
    def run_build(self, root, **options):
        scripts = root / 'suite/scripts'
        scripts.mkdir(parents=True)
        shutil.copyfile(ROOT / 'suite/scripts/build-suite.ps1', scripts / 'build-suite.ps1')
        config = root / 'suite/config'
        config.mkdir()
        for architecture, name, version in (
                ('x64', 'runtime.lock.json', '1.2.3-x64-test'),
                ('arm64', 'runtime.arm64.lock.json', '4.5.6-arm64-test')):
            (config / name).write_text(json.dumps({
                'architecture': architecture, 'version': version}), encoding='utf-8')
        arguments = {'WorkDirectory': str(root / 'build-work'), **options}
        (root / 'arguments.json').write_text(json.dumps(arguments), encoding='utf-8')
        harness = root / 'harness.ps1'
        harness.write_text(HARNESS, encoding='utf-8')
        result = subprocess.run(
            [PWSH, '-NoProfile', '-File', str(harness), '-Root', str(root)],
            cwd=root, capture_output=True, text=True, timeout=30)
        events_path = root / 'events.jsonl'
        events = [json.loads(line) for line in events_path.read_text().splitlines()] \
            if events_path.exists() else []
        return result, events

    def assert_build(self, root, events, architecture, output):
        self.assertEqual([event['command'] for event in events], ['dotnet', 'python', 'python'])
        publish = events[0]['arguments']
        self.assertEqual(publish[publish.index('-r') + 1], 'win-' + architecture)
        prepare = events[1]['arguments']
        self.assertEqual(prepare[0], 'suite/prepare.py')
        self.assertIn('--architecture', prepare)
        self.assertEqual(prepare[prepare.index('--architecture') + 1], architecture)
        self.assertEqual(Path(prepare[prepare.index('--output') + 1]), output)
        self.assertEqual(Path(events[2]['arguments'][-2]), output)
        self.assertEqual(Path(events[2]['arguments'][-1]), Path(str(output) + '.zip'))
        self.assertTrue(output.is_dir())
        self.assertEqual(Path(str(output) + '.zip').read_text(), 'test archive')

    def test_default_build_uses_x64_lock_version_and_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result, events = self.run_build(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_build(root, events, 'x64', root / 'dist/OpenGeul-Office-1.2.3-x64-test-windows-x64')

    def test_arm64_build_uses_arm64_lock_version_and_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result, events = self.run_build(root, Architecture='arm64')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_build(root, events, 'arm64', root / 'dist/OpenGeul-Office-4.5.6-arm64-test-windows-arm64')

    def test_accepted_uppercase_architecture_is_normalized_for_rid_prepare_and_output(self):
        for architecture, version in (('X64', '1.2.3-x64-test'), ('ARM64', '4.5.6-arm64-test')):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                result, events = self.run_build(root, Architecture=architecture)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_build(root, events, architecture.lower(),
                                  root / ('dist/OpenGeul-Office-' + version + '-windows-' + architecture.lower()))

    def test_explicit_output_is_retained_for_selected_architecture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'custom-output'
            result, events = self.run_build(root, Architecture='arm64', OutputDirectory=str(output))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_build(root, events, 'arm64', output)

    def test_existing_explicit_file_or_directory_is_preserved_before_build_tools_run(self):
        for directory in (False, True):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                output = root / 'preserve-output'
                sentinel = output / 'sentinel.txt' if directory else output
                if directory:
                    output.mkdir()
                sentinel.write_bytes(b'preserve existing output')
                result, events = self.run_build(root, Architecture='arm64', OutputDirectory=str(output))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Suite output already exists', result.stdout + result.stderr)
                self.assertEqual(events, [])
                self.assertEqual(sentinel.read_bytes(), b'preserve existing output')
                self.assertFalse((root / 'build-work').exists())

    def test_unknown_architecture_is_rejected_before_build_tools_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result, events = self.run_build(root, Architecture='x86')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ValidateSet', result.stdout + result.stderr)
            self.assertEqual(events, [])
            self.assertFalse((root / 'build-work').exists())


if __name__ == '__main__':
    unittest.main()
