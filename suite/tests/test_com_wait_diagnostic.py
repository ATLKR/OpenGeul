"""Compile standalone fixture and exercise pure contracts; never invoke Win32 here."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'suite/shell-tests/ComWaitDiagnostic.cs'

class ComWaitDiagnosticTests(unittest.TestCase):
    def test_explicit_routes_do_not_run_native_experiment_in_normal_tests(self):
        source = (ROOT / 'suite/shell-tests/Program.cs').read_text()
        self.assertIn('ComWaitDiagnostic.IsDiagnosticCommand(args)', source)
        self.assertIn('ComWaitDiagnostic.RunAsync(args)', source)
        self.assertIn('ComWaitDiagnostic.PureContractTests()', source)
        self.assertNotIn('tests.AddRange(ComWaitDiagnostic', source)

    def test_real_standalone_csharp_pure_contracts(self):
        self.assertTrue(SOURCE.exists(), 'standalone bounded fixture absent')
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell required for standalone C# compile/pure contracts')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'check.ps1'
            script.write_text("$ErrorActionPreference='Stop'\nAdd-Type -Path $env:COM_WAIT_SOURCE\n[ComWaitDiagnostic]::PureContractTests()\n[ComWaitDiagnostic]::ArrivalContractTests()\n'PURE_CONTRACTS_PASSED'\n")
            result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)], env=dict(os.environ, COM_WAIT_SOURCE=str(SOURCE)), capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PURE_CONTRACTS_PASSED', result.stdout)

if __name__ == '__main__':
    unittest.main()
