"""Actual API-launched commands and the workflow's unmodified status guard.

This portable boundary does not execute the native Office build or qualify it.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'suite/scripts/build-native-engine.ps1'
WORKFLOW = ROOT / '.github/workflows/office-native-engine.yml'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def actual_status_guard():
    text = WORKFLOW.read_text(encoding='utf-8')
    step = text.split('      - name: Build and verify native Firebird before the full Office engine\n', 1)[1]
    step = step.split('      - name: Retain original source build diagnostics\n', 1)[0]
    commands = textwrap.dedent(step.split('        run: |\n', 1)[1]).strip().splitlines()
    assert commands[0].startswith('./suite/scripts/build-native-engine.ps1 ')
    return '\n'.join(commands[1:])


class NativeEngineWorkflowStatusTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path(PWSH).is_file(), 'Actual PowerShell is required for workflow status checks')
        self.temporary = tempfile.TemporaryDirectory(prefix='native-workflow-status-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_guard(self, *, child_exit=0, stale_native_exit=None):
        prefix = self.root / 'actual-command'
        child = self.root / 'child.py'
        child.write_text('import sys\nprint("original stdout",flush=True)\n'
                         'print("original stderr",file=sys.stderr,flush=True)\n'
                         f'sys.exit({child_exit})\n', encoding='utf-8')
        setup = '' if stale_native_exit is None else f'$global:LASTEXITCODE={stale_native_exit}\n'
        script = self.root / 'case.ps1'
        # No command or assignment can intervene between the API command and
        # the exact workflow guard: $? belongs to that original invocation.
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(DRIVER) + '\n' + setup +
            'Invoke-LoggedCommand ' + quote(sys.executable) + ' @(' + quote(child) + ') ' +
            quote(self.root) + ' ' + quote(prefix) + '|Out-Null\n' + actual_status_guard() + '\n' +
            'Write-BuildJson ' + quote(self.root / 'after-guard.json') +
            " ([ordered]@{reached=$true;lastNativeExitCode=$LASTEXITCODE})\n", encoding='utf-8')
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                capture_output=True, text=True, timeout=20)
        receipt = json.loads((self.root / 'actual-command.command.json').read_bytes())
        self.assertEqual('original stdout', (self.root / 'actual-command.stdout.log').read_text().strip())
        self.assertEqual('original stderr', (self.root / 'actual-command.stderr.log').read_text().strip())
        return result, receipt

    def test_successful_api_command_is_accepted_without_a_native_exit_variable(self):
        result, receipt = self.run_guard()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(receipt['passed']); self.assertEqual(0, receipt['exitCode'])
        self.assertTrue(receipt['pipeDrainComplete'])
        self.assertIsNone(json.loads((self.root / 'after-guard.json').read_bytes())['lastNativeExitCode'])

    def test_successful_api_command_does_not_inherit_a_stale_native_failure(self):
        result, receipt = self.run_guard(stale_native_exit=7)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(receipt['passed']); self.assertEqual(0, receipt['exitCode'])
        self.assertEqual(7, json.loads((self.root / 'after-guard.json').read_bytes())['lastNativeExitCode'])

    def test_failed_owned_command_keeps_its_exit_seven_receipt_and_original_error(self):
        result, receipt = self.run_guard(child_exit=7)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(receipt['passed']); self.assertEqual(7, receipt['exitCode'])
        self.assertTrue(receipt['pipeDrainComplete'])
        self.assertIn('Command failed with exit 7', receipt['error'])
        self.assertIn('Command failed with exit 7', result.stderr)
        self.assertNotIn('Native ARM64 Office source build or functional verification failed.', result.stderr)
        self.assertFalse((self.root / 'after-guard.json').exists())


if __name__ == '__main__':
    unittest.main()
