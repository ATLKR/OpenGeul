"""패키지·소유 PID·native guard 연결이 빠지면 실제 Windows 검사를 시작하지 않는다."""
from pathlib import Path
import ast
import unittest
ROOT=Path(__file__).resolve().parents[1]

class NativeHarnessWiringTests(unittest.TestCase):
    def test_session_checks_pe_before_launch_and_uses_the_retained_owned_handle(self):
        source=(ROOT/'e2e/driver.py').read_text();tree=ast.parse(source)
        session=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Session')
        init=next(n for n in session.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
        calls=[n for n in ast.walk(init) if isinstance(n,ast.Call)]
        guard=next(n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='verify_executable')
        launch=next(n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='Popen')
        host=next(n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='verify_host')
        proof=next(n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='verify_process')
        self.assertLess(guard.lineno,launch.lineno);self.assertLess(host.lineno,launch.lineno)
        self.assertLess(launch.lineno,proof.lineno)
        self.assertEqual(ast.unparse(proof.args[0]),'self.proc.pid')
        self.assertEqual(ast.unparse(next(k.value for k in proof.keywords if k.arg=='handle')),'int(self.proc._handle)')
        self.assertIn("runtime['webview2Native']=verify_webview2(self.proc.pid,architecture)",source)
    def test_installed_product_proofs_bind_package_identity_and_architecture(self):
        install=(ROOT/'e2e/msix-install.ps1').read_text()
        for binding in ('ProcessorArchitecture -cne $Architecture','IsWow64Process2',):
            if binding=='IsWow64Process2':
                self.assertIn(binding,(ROOT/'e2e/native_architecture.py').read_text())
            else:self.assertIn(binding,install)
        self.assertIn('process --architecture $Architecture --pid $launched.Id --executable $executable --package-full-name $installed.PackageFullName --webview2',install)
        self.assertIn('-Architecture $Architecture -PythonPath',install)
        cli=(ROOT/'e2e/installed-cli.ps1').read_text()
        self.assertIn('cli --architecture $Architecture --executable $CliPath --package-full-name $PackageFullName',cli)
        self.assertIn('$result.nativeArchitecture=$actual.nativeArchitecture',cli)
        self.assertIn('$result.helpBytes=$actual.helpBytes',cli)
        self.assertIn('$result.helpSha256=$actual.helpSha256',cli)
        self.assertNotIn('& $CliPath --help',cli)
    def test_arm_framework_is_verified_before_install_and_same_registration_rechecked(self):
        install=(ROOT/'e2e/msix-install.ps1').read_text()
        self.assertIn('https://aka.ms/Microsoft.VCLibs.arm64.14.00.Desktop.appx',install)
        for guard in ('$frameworkIdentity.Name -ne $name','$frameworkIdentity.Publisher -ne $requiredPublisher',
                      '$frameworkIdentity.ProcessorArchitecture -cne $Architecture','[version]$frameworkIdentity.Version -lt $minimum'):
            self.assertIn(guard,install)
        self.assertLess(install.index('$frameworkIdentity.ProcessorArchitecture -cne $Architecture'),install.index('Add-AppxPackage -Path $download'))
        self.assertEqual(install.count('$_.Architecture.ToString().ToLowerInvariant() -eq $Architecture'),2)
    def test_existing_native_close_and_owned_cleanup_are_preserved(self):
        source=(ROOT/'e2e/driver.py').read_text()
        self.assertIn("['taskkill','/PID',str(self.proc.pid),'/T','/F']",source)
        self.assertNotIn('taskkill /IM',source)
        install=(ROOT/'e2e/msix-install.ps1').read_text()
        self.assertIn("if ((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash -ne $before)",install)
        self.assertIn("Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'OpenGeul.exe') }",install)
        self.assertIn("Where-Object { $_.Path -eq (Join-Path $installed.InstallLocation 'Tools/rhwp.exe') }",install)

if __name__=='__main__':unittest.main()
