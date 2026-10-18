"""Windows-only pkgconf build-tool identity and configure handoff boundaries."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote
from suite.tests.test_payload import pe


def tool_pe(imports=('KERNEL32.dll', 'msvcrt.dll')):
    data = bytearray(pe())
    struct.pack_into('<II', data, 152+120, 0x1000, (len(imports)+1)*20)
    offset = 768
    for index, name in enumerate(imports):
        struct.pack_into('<I', data, 512+index*20+12, 0x1000+offset-512)
        encoded = name.encode('ascii') + b'\0'
        data[offset:offset+len(encoded)] = encoded; offset += len(encoded)
    return bytes(data)


class NativePkgconfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def ps(self, body):
        script = self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(SOURCE) + '\n' + body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout+'\n'+result.stderr)
        return result.stdout.strip()

    def rejected(self, body):
        self.ps("$rejected=$false;try{"+body+"}catch{if($_.Exception -is [System.Management.Automation.CommandNotFoundException]){throw};$rejected=$true};if(-not $rejected){throw 'Invalid Windows build tool admitted'}")

    def test_pkgconf_assignment_is_one_explicit_argument_and_harfbuzz_stays_enabled(self):
        arguments = json.loads(self.ps("@(Get-ConfigureArguments '/cache' '/jdk' '/ant' '/cygdrive/c/build tools/pkgconf-2.4.3.exe')|ConvertTo-Json -Compress"))
        self.assertIn('PKG_CONFIG=/cygdrive/c/build tools/pkgconf-2.4.3.exe', arguments)
        self.assertFalse(any('harfbuzz' in value and ('disable' in value or 'without' in value) for value in arguments))

    def test_windows_build_tool_pe_imports_do_not_change_native_product_admission(self):
        path = self.root/'pkgconf-2.4.3.exe'; path.write_bytes(tool_pe())
        identity = json.loads(self.ps(f"Get-WindowsBuildToolPeIdentity {quote(path)}|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual(0x8664, identity['machine'])
        self.assertEqual(['KERNEL32.dll', 'msvcrt.dll'], identity['imports'])
        self.assertEqual('buildHostTool', identity['role'])
        self.assertFalse(identity['productPayload'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), identity['sha256'])
        self.rejected(f"Get-ProductPeIdentity {quote(path)}")

    def test_windows_build_tool_refuses_cygwin_and_malformed_import_tables(self):
        path = self.root/'pkgconf-2.4.3.exe'; path.write_bytes(tool_pe(('cygwin1.dll',)))
        self.rejected(f"Get-WindowsBuildToolPeIdentity {quote(path)}")
        data = bytearray(tool_pe()); struct.pack_into('<I', data, 524, 0x7fffffff); path.write_bytes(data)
        self.rejected(f"Get-WindowsBuildToolPeIdentity {quote(path)}")
        path.write_bytes(b'MZ truncated')
        self.rejected(f"Get-WindowsBuildToolPeIdentity {quote(path)}")

    def test_official_tool_pin_is_exact_and_remains_separate_from_product(self):
        pin = json.loads(self.ps('Get-WindowsPkgconfPin|ConvertTo-Json -Compress'))
        self.assertEqual('https://dev-www.libreoffice.org/extern/pkgconf-2.4.3.exe', pin['url'])
        self.assertEqual(90624, pin['size'])
        self.assertEqual('791cd6dbc56f7268fbf9c4652d6634b0f5c59687ab4e504565e58245952edd41', pin['sha256'])
        self.assertEqual(0x8664, pin['machine'])

    def test_acquisition_authenticates_bytes_and_requires_exact_logged_version(self):
        source = self.root/'fixture.exe'; source.write_bytes(tool_pe())
        download, evidence = self.root/'download', self.root/'evidence'
        download.mkdir(); evidence.mkdir()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        setup = (f"$global:fixturePin=Get-WindowsPkgconfPin;$global:fixturePin.size={source.stat().st_size};"
                 f"$global:fixturePin.sha256={quote(digest)};"
                 "function Get-WindowsPkgconfPin {$global:fixturePin};"
                 "function Get-AuthenticatedDownload {param($Url,$Destination,$Size,$Algorithm,$Hash,$Receipt)"
                 "if($Url -cne 'https://dev-www.libreoffice.org/extern/pkgconf-2.4.3.exe' -or $Algorithm -cne 'SHA256'){throw 'Wrong authenticated input request'};"
                 f"Copy-Item {quote(source)} $Destination}};"
                 "function Invoke-LoggedCommand {param($FilePath,$Arguments,$WorkingDirectory,$LogPrefix)"
                 "if($Arguments.Count -ne 1 -or $Arguments[0] -cne '--version'){throw 'Wrong executable probe'};"
                 "[IO.File]::WriteAllText(($LogPrefix+'.stdout.log'),$global:probeVersion);"
                 "[pscustomobject]@{stdout=($LogPrefix+'.stdout.log');receipt=($LogPrefix+'.command.json')}};")
        result = json.loads(self.ps(setup+"$global:probeVersion='2.4.3';"
                            f"Get-AuthenticatedWindowsPkgconf {quote(download)} {quote(evidence)} {quote(self.root)}|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual('2.4.3', result['version'])
        self.assertEqual(digest, result['identity']['sha256'])
        self.assertFalse(result['productPayload'])
        self.assertTrue((evidence/'pkgconf-build-tool.json').is_file())
        (download/'pkgconf-2.4.3.exe').unlink()
        self.rejected(setup+"$global:probeVersion='3.0.8';"
                      f"Get-AuthenticatedWindowsPkgconf {quote(download)} {quote(evidence)} {quote(self.root)}")
        (download/'pkgconf-2.4.3.exe').unlink()
        self.rejected(setup+"$global:fixturePin.sha256=('0'*64);$global:probeVersion='2.4.3';"
                      f"Get-AuthenticatedWindowsPkgconf {quote(download)} {quote(evidence)} {quote(self.root)}")

    @unittest.skipUnless(os.environ.get('OPENGEUL_PKGCONF_OFFICIAL_TOOL') and
                         os.environ.get('OPENGEUL_LIBREOFFICE_CONFIGURE_SOURCE'),
                         'Actual official tool and pinned configure source require explicit local inputs')
    def test_actual_official_tool_and_pinned_configure_requirement(self):
        tool = Path(os.environ['OPENGEUL_PKGCONF_OFFICIAL_TOOL'])
        configure = Path(os.environ['OPENGEUL_LIBREOFFICE_CONFIGURE_SOURCE']).read_bytes()
        manifest = json.loads((SOURCE.parents[1]/'engine-build/source-build.json').read_text())
        self.assertEqual(manifest['configureSource']['sha256'], hashlib.sha256(configure).hexdigest())
        self.assertIn(b'AC_PATH_PROG(PKG_CONFIG,pkgconf-2.4.3.exe,,[$PATH:$LODE_HOME/opt/bin])', configure)
        self.assertIn(b'Add PKG_CONFIG=/path/to/pkgconf-2.4.3.exe to autogen.input', configure)
        result = json.loads(self.ps(f"$pin=Get-WindowsPkgconfPin;Confirm-FileIdentity {quote(tool)} $pin.size SHA256 $pin.sha256|Out-Null;"
                                   f"Get-WindowsBuildToolPeIdentity {quote(tool)}|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual(0x8664, result['machine'])
        self.assertEqual(12, len(result['imports']))
        self.assertIn('KERNEL32.dll', result['imports'])
        self.assertIn('VCRUNTIME140.dll', result['imports'])


if __name__ == '__main__': unittest.main()
