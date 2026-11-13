"""Execute the driver's actual PS generation statements and real GNU make.

Portable tests prove the process/path boundary, not native Windows compilation
or the identity of the unrecorded make executable in original run39019877862.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/build-native-engine.ps1'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name != 'nt' and Path('/usr/bin/make').is_file(),
                     'Portable real POSIX GNU make boundary; actual Cygwin is qualified by Windows CI')
class NativeSourcePinPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-pin-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source's owned directory"
        self.source.mkdir()
        self.commands = self.root / "commands's owned directory"
        self.commands.mkdir()
        self.makefile = self.commands / "source input's.mk"
        self.script = self.commands / "source input's.sh"
        self.foreign = self.root / 'foreign-tools'
        self.foreign.mkdir()
        self.foreign_called = self.root / 'foreign-make-called'
        foreign = self.foreign / 'make'
        foreign.write_text('#!/bin/bash\nprintf called > ' + quote(self.foreign_called) +
                           '\nprintf "foreign make cannot read POSIX path\\n" >&2\nexit 2\n')
        foreign.chmod(0o700)
        self.python_bytes = b'generated authenticated Python source fixture'
        self.python_sha = hashlib.sha256(self.python_bytes).hexdigest()
        self.pip_bytes = b'generated authenticated pip source fixture'
        self.pip_sha = hashlib.sha256(self.pip_bytes).hexdigest()
        (self.source / 'download.lst').write_text(
            'PYTHON_VERSION := 3.13.15\nPYTHON_TARBALL := Python-$(PYTHON_VERSION).tar.xz\n'
            f'PYTHON_SHA256SUM := {self.python_sha}\nPIP_TARBALL := pip-26.1.whl\n'
            f'PIP_SHA256SUM := {self.pip_sha}\n')

    def ps(self, body, *, accepted=True):
        case = self.root / 'case.ps1'
        case.write_text("$ErrorActionPreference='Stop'\n. " + quote(SOURCE) + '\n' + body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(case)],
                                text=True, capture_output=True, timeout=30)
        if accepted:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, 'Changed cached source was accepted')
        return result

    def generate(self, *, unix_makefile=None):
        # Execute the actual production statements, not a test reimplementation
        # of their shell text. The complete driver is dot-sourced, not run.
        self.ps(f"""
$makePins={quote(self.makefile)}
$pinScript={quote(self.script)}
$unixSource={quote(self.source)}
$unixMakePins={quote(unix_makefile or self.makefile)}
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(SOURCE)},[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count) {{throw 'Driver has PowerShell parse errors'}}
$statements=@($ast.FindAll({{param($node)
 $node -is [Management.Automation.Language.CommandAst] -and
 $node.GetCommandName() -eq 'Write-BashScript' -and
 $node.CommandElements[1].Extent.Text -in @('$makePins','$pinScript')
}},$true))
if($statements.Count -ne 2) {{throw 'Expected exact production source-pin makefile/script generation statements'}}
foreach($statement in $statements) {{Invoke-Expression $statement.Extent.Text}}
""")
        self.assertTrue(self.makefile.is_file(), 'Production writer must create the exact referenced makefile')
        self.assertNotIn(b'\r', self.makefile.read_bytes())
        self.assertNotIn(b'\r', self.script.read_bytes())

    def run_shell(self):
        environment = dict(os.environ, PATH=str(self.foreign) + ':/usr/bin:/bin')
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', str(self.script)],
                              text=True, capture_output=True, env=environment, timeout=10)

    def require_pins(self, output):
        actual = {line for line in output.splitlines() if line.startswith('PIN|')}
        self.assertEqual(actual, {f'PIN|PYTHON_TARBALL|Python-3.13.15.tar.xz|{self.python_sha}',
                                  f'PIN|PIP_TARBALL|pip-26.1.whl|{self.pip_sha}'})

    def test_existing_generated_posix_makefile_uses_real_gnu_make_despite_foreign_path(self):
        self.generate()
        result = self.run_shell()
        self.assertEqual(result.returncode, 0, 'Generated file exists, but wrong make/path dialect was used: ' + result.stderr)
        self.assertFalse(self.foreign_called.exists())
        self.assertIn('GNU Make', result.stdout)
        self.require_pins(result.stdout)

    def test_nonexistent_converted_path_fails_before_any_make_version_or_pin_output(self):
        self.generate(unix_makefile=self.commands / 'missing converted file.mk')
        result = self.run_shell()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.foreign_called.exists())
        self.assertEqual(result.stdout, '')

    def test_real_make_resolved_pins_still_authenticate_source_archive_bytes(self):
        self.generate()
        result = self.run_shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.require_pins(result.stdout)
        log = self.root / 'pins.stdout.log'
        log.write_text(result.stdout)
        cache = self.root / 'authenticated-cache'
        cache.mkdir()
        python = cache / 'Python-3.13.15.tar.xz'
        python.write_bytes(self.python_bytes)
        (cache / 'pip-26.1.whl').write_bytes(self.pip_bytes)
        report = self.root / 'inventory.json'
        command = f'Write-ExternalSourceInventory {quote(cache)} {quote(log)} {quote(report)} @{{}} "" -RequirePython|Out-Null'
        self.ps(command)
        receipt = json.loads(report.read_text())
        self.assertTrue(receipt['pythonSourceVerified'])
        self.assertEqual(len(receipt['archives']), 2)
        python.write_bytes(self.python_bytes + b' changed')
        rejected = self.ps(command, accepted=False)
        self.assertIn('fails authenticated download.lst hash', rejected.stderr)


if __name__ == '__main__':
    unittest.main()
