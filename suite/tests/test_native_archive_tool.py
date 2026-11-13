"""Portable selected-tool and child-script boundaries; no native library claim."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
DRIVER=ROOT/'suite/scripts/build-native-engine.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"

class NativeArchiveToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='native-archive-tool-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve(strict=True)
        self.compiler=self.root/"selected VS's toolchain/VC/Tools/MSVC/14.51.36231"
        self.tool=self.compiler/'bin/Hostarm64/arm64/lib.exe';self.tool.parent.mkdir(parents=True)
        self.pe(0xaa64)

    def pe(self,machine):
        raw=bytearray(512);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,128)
        raw[128:132]=b'PE\0\0';struct.pack_into('<H',raw,132,machine);struct.pack_into('<H',raw,152,0x20b)
        self.tool.write_bytes(raw)

    def ps(self,body):
        script=self.root/'case.ps1';script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+'\n'+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=20)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        return result.stdout

    def test_librarian_is_exact_selected_native_tool_and_wrong_or_linked_tool_is_rejected(self):
        plan=json.loads(self.ps('Get-NativeLibrarianPlan '+quote(self.compiler)+'|ConvertTo-Json -Depth 6 -Compress'))
        self.assertEqual(str(self.tool),plan['path']);self.assertEqual(0xaa64,plan['machine'])
        self.assertEqual(hashlib.sha256(self.tool.read_bytes()).hexdigest(),plan['sha256'])
        for machine in (0x8664,0x14c):
            self.pe(machine)
            self.ps('$caught=$false;try {Get-NativeLibrarianPlan '+quote(self.compiler)+'|Out-Null}catch{$caught=$true};if(-not $caught){throw "Foreign librarian accepted"}')
        self.pe(0xaa64);native=self.tool.read_bytes();self.tool.unlink()
        self.ps('$caught=$false;try {Get-NativeLibrarianPlan '+quote(self.compiler)+'|Out-Null}catch{$caught=$true};if(-not $caught){throw "Missing tool fell back to PATH"}')
        actual=self.root/'actual-lib.exe';actual.write_bytes(native)
        try:self.tool.symlink_to(actual)
        except (OSError,NotImplementedError):return
        self.ps('$caught=$false;try {Get-NativeLibrarianPlan '+quote(self.compiler)+'|Out-Null}catch{$caught=$true};if(-not $caught){throw "Linked librarian accepted"}')

    @unittest.skipIf(os.name=='nt','Portable POSIX child environment check')
    def test_actual_owned_make_writer_quotes_librarian_and_keeps_controller_environment(self):
        output=self.root/'commands/make.sh';output.parent.mkdir();source=self.root/'source';source.mkdir()
        fake=self.root/'make';fake.write_text('#!/bin/bash\nprintf "%s" "$OPENGEUL_FIREBIRD_LIB"\n');fake.chmod(0o700)
        observed=self.root/'state.json'
        self.ps(f"""
$script={quote(output)};$unixSource={quote(source)};$Jobs=4;$target='ExternalProject_firebird'
$receipt=@{{nativeLibrarian=@{{path={quote(self.tool)}}}}};$env:OPENGEUL_FIREBIRD_LIB='controller-preserved'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Write-BashScript' -and $n.CommandElements[1].Extent.Text -eq '$script' -and $n.Extent.Text.Contains('make -j')}},$true))
if($errors.Count -or $calls.Count -ne 1){{throw 'Expected one owned make writer'}}
Invoke-Expression $calls[0].Extent.Text
Write-BuildJson {quote(observed)} @{{controller=$env:OPENGEUL_FIREBIRD_LIB}}
""")
        # Keep the actual production exports/quoting; only replace its make
        # command with an owned observer so no product code executes here.
        raw=output.read_text();self.assertIn('export OPENGEUL_FIREBIRD_LIB=',raw)
        raw=raw.replace('make -j4 ExternalProject_firebird',str(fake))
        output.write_text(raw)
        result=subprocess.run(['/bin/bash',str(output)],capture_output=True,text=True,timeout=5)
        self.assertEqual(0,result.returncode,result.stderr);self.assertEqual(str(self.tool),result.stdout)
        self.assertEqual('controller-preserved',json.loads(observed.read_text())['controller'])

    def test_actual_configured_compiler_binding_selects_the_librarian_plan(self):
        self.ps(f"""
$nativeCompilerRoot={quote(self.compiler)};$receipt=@{{}}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$receipt.nativeLibrarian'}},$true))
if($errors.Count -or $calls.Count -ne 1){{throw 'Configured librarian preflight binding is missing'}}
Invoke-Expression $calls[0].Extent.Text
if($receipt.nativeLibrarian.path -cne {quote(self.tool)}){{throw 'Librarian escaped the selected native compiler root'}}
""")

if __name__=='__main__':unittest.main()
