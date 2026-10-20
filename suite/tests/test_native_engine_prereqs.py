"""Real file/PE/COFF boundaries for installed Windows Java build tools."""
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
import unittest
import zipfile

from suite.tests.test_native_engine_build import PWSH, SOURCE, quote
from suite.tests.test_payload import pe


def import_library(machine):
    member = struct.pack('<HHHHIIHH', 0, 0xffff, 0, machine, 0, 8, 0, 0) + b'jvm\0jvm\0'
    header = ('jvm.dll/'.ljust(16) + '0'.ljust(12) + '0'.ljust(6) + '0'.ljust(6)
              + '100644'.ljust(8) + str(len(member)).ljust(10) + '`\n').encode('ascii')
    return b'!<arch>\n' + header + member + (b'\n' if len(member) % 2 else b'')


class NativeJavaPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(strict=True)

    def ps(self, body):
        script = self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(SOURCE) + '\n' + body, encoding='utf-8')
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stdout + '\n' + result.stderr)
        return result.stdout.strip()

    def rejected(self, body):
        self.ps("$rejected=$false; try { " + body + " } catch { if($_.Exception -is [System.Management.Automation.CommandNotFoundException]){throw}; $rejected=$true }; if(-not $rejected){throw 'Invalid prerequisite was accepted'}")

    def jdk(self, name='native jdk', machine=0xaa64):
        root = self.root/name
        for relative in ('bin/java.exe', 'bin/javac.exe', 'bin/server/jvm.dll', 'bin/jawt.dll'):
            path = root/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pe(machine, dll=path.suffix == '.dll'))
        for relative in ('lib/jvm.lib', 'lib/jawt.lib'):
            path = root/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(import_library(machine))
        for relative in ('include/jni.h', 'include/win32/jni_md.h'):
            path = root/relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('/* JNI fixture */')
        (root/'release').write_text('JAVA_VERSION="21.0.12"\nOS_ARCH="aarch64"\nIMPLEMENTOR="Fixture JDK"\n')
        return root

    def ant(self):
        root = self.root/'apache ant'
        (root/'bin').mkdir(parents=True)
        (root/'bin/ant').write_text('#!/bin/sh\nexec java org.apache.tools.ant.Main "$@"\n')
        (root/'lib').mkdir()
        for filename, main in (('ant.jar', 'org/apache/tools/ant/Main.class'),
                               ('ant-launcher.jar', 'org/apache/tools/ant/launch/Launcher.class')):
            with zipfile.ZipFile(root/'lib'/filename, 'w') as jar:
                jar.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nImplementation-Version: 1.10.18\n')
                jar.writestr(main, bytes.fromhex('cafebabe'))
        return root

    def test_actual_native_jdk_pe_and_jni_import_libraries_are_bound_to_receipt(self):
        jdk = self.jdk()
        data = json.loads(self.ps(f"Get-NativeJdkPlan {quote(jdk)}|ConvertTo-Json -Depth 12 -Compress"))
        self.assertEqual(str(jdk), data['home'])
        self.assertEqual('21.0.12', data['javaVersion'])
        self.assertEqual(4, len(data['nativeFiles']))
        self.assertTrue(all(row['machine'] == 0xaa64 for row in data['nativeFiles']))
        self.assertEqual(2, len(data['importLibraries']))
        self.assertTrue(all(row['machines'] == [0xaa64] for row in data['importLibraries']))
        self.assertEqual(hashlib.sha256((jdk/'release').read_bytes()).hexdigest(), data['releaseSha256'])

    def test_native_launchers_cannot_hide_foreign_jvm_or_import_library(self):
        for relative in ('bin/java.exe', 'bin/javac.exe', 'bin/server/jvm.dll', 'lib/jvm.lib', 'lib/jawt.lib'):
            with self.subTest(relative=relative):
                jdk = self.jdk(relative.replace('/', '-'))
                path = jdk/relative
                path.write_bytes(import_library(0x8664) if path.suffix == '.lib' else pe(0x8664, dll=path.suffix == '.dll'))
                self.rejected(f"Get-NativeJdkPlan {quote(jdk)}")

    def test_missing_jni_and_malformed_import_libraries_fail_closed(self):
        jdk = self.jdk()
        (jdk/'include/win32/jni_md.h').unlink()
        self.rejected(f"Get-NativeJdkPlan {quote(jdk)}")
        (jdk/'include/win32/jni_md.h').write_text('/* JNI */')
        (jdk/'lib/jvm.lib').write_bytes(b'!<arch>\n')
        self.rejected(f"Get-NativeJdkPlan {quote(jdk)}")

    def test_aarch64_environment_home_is_selected_before_foreign_default_home(self):
        native = self.jdk(); foreign = self.jdk('foreign', 0x8664)
        data = json.loads(self.ps(f"$env:JAVA_HOME_21_AARCH64={quote(native)};$env:JAVA_HOME={quote(foreign)}; Resolve-NativeJdk ''|ConvertTo-Json -Depth 12 -Compress"))
        self.assertEqual(str(native), data['home'])
        self.assertEqual('JAVA_HOME_21_AARCH64', data['selection'])
        self.rejected(f"$env:JAVA_HOME_21_AARCH64={quote(native)};Resolve-NativeJdk {quote(foreign)}")

    def test_installed_ant_jars_and_launcher_are_bound_without_product_changes(self):
        ant = self.ant()
        data = json.loads(self.ps(f"Get-AntPlan {quote(ant)}|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual(str(ant), data['home'])
        self.assertEqual(2, len(data['jars']))
        self.assertEqual('1.10.18', data['version'])
        self.assertEqual(hashlib.sha256((ant/'lib/ant.jar').read_bytes()).hexdigest(), data['jars'][0]['sha256'])
        (ant/'lib/ant-launcher.jar').write_bytes(b'not a JAR')
        self.rejected(f"Get-AntPlan {quote(ant)}")

    def test_explicit_java_and_ant_homes_reach_single_configure_arguments(self):
        result = json.loads(self.ps("@(Get-ConfigureArguments '/owned/cache' '/cygdrive/c/native jdk' '/cygdrive/c/apache ant')|ConvertTo-Json -Compress"))
        self.assertIn('--with-jdk-home=/cygdrive/c/native jdk', result)
        self.assertIn('--with-ant-home=/cygdrive/c/apache ant', result)
        self.assertNotIn('--without-java', result)
        self.assertNotIn('--disable-odk', result)

    def test_distro_documentation_tools_are_in_the_cygwin_setup_request(self):
        packages = self.ps('Get-CygwinBuildPackages').split(',')
        self.assertIn('doxygen', packages)
        self.assertIn('graphviz', packages)
        self.assertNotIn('ant', packages)
        self.assertNotIn('nasm', packages)

    def test_driver_binds_installed_java_tools_before_large_source_downloads(self):
        jdk, ant = self.jdk(), self.ant()
        work, output = self.root/'owned-work', self.root/'evidence'
        self.ps("function Get-NativeBuildHost { @{isWindows=$true;processMachine=0;nativeMachine=43620} }; "
                "function Get-SourceRunBinding { @{sourceCommit=('a'*40);sourceTree=('b'*40)} }; "
                "function Get-AuthenticatedDownload { throw 'stopped before downloading actual sources' }; "
                f"try {{Invoke-NativeEngineBuild Full {quote(work)} {quote(output)} '' 4 {quote(jdk)} {quote(ant)}}} catch {{}}")
        receipt = json.loads((output/'source-build-receipt.json').read_text())
        self.assertEqual(str(jdk), receipt.get('javaTools', {}).get('jdk', {}).get('home'))
        self.assertEqual(str(ant), receipt.get('javaTools', {}).get('ant', {}).get('home'))
        self.assertEqual('authenticated-downloads', receipt['stage'])
        self.assertFalse(receipt['passed'])
        self.assertIn('stopped before downloading', receipt['error'])

    def test_nonzero_owned_command_emits_bounded_original_failure_tails(self):
        child = self.root/'failed_tool.py'
        child.write_text("import sys\nprint('DISCARDED_STDOUT_PREFIX')\nprint('stdout filler\\n'*1000)\nprint('ORIGINAL_CONFIGURE_STDOUT_CAUSE')\nsys.stderr.write('DISCARDED_STDERR_PREFIX\\n'+'stderr filler\\n'*1000+'ORIGINAL_CONFIGURE_STDERR_CAUSE\\n')\nsys.exit(9)\n")
        prefix = self.root/'failure'
        output = self.ps(f"try {{Invoke-LoggedCommand {quote(os.sys.executable)} @({quote(child)}) {quote(self.root)} {quote(prefix)}}} catch {{}}")
        self.assertIn('ORIGINAL_CONFIGURE_STDOUT_CAUSE', output)
        self.assertIn('ORIGINAL_CONFIGURE_STDERR_CAUSE', output)
        self.assertNotIn('DISCARDED_STDOUT_PREFIX', output)
        self.assertNotIn('DISCARDED_STDERR_PREFIX', output)
        self.assertLess(len(output), 18000)
        receipt = json.loads((self.root/'failure.command.json').read_text())
        self.assertEqual(9, receipt['exitCode'])
        self.assertFalse(receipt['passed'])
        self.assertIn('DISCARDED_STDOUT_PREFIX', (self.root/'failure.stdout.log').read_text())

    @unittest.skipUnless(os.name == 'posix', 'Portable actual bash boundary requires POSIX')
    def test_identity_receipt_runs_only_explicit_user_and_platform_queries(self):
        commands, evidence = self.root/'commands', self.root/'evidence'
        commands.mkdir(); evidence.mkdir()
        raw = self.ps("function Invoke-CygwinScript { param($Bash,$Cygpath,$Script,$WorkingDirectory,$LogPrefix) "
                      "Invoke-LoggedCommand '/bin/bash' @($Script) $WorkingDirectory $LogPrefix }; "
                      f"Get-CygwinIdentity '/bin/bash' '' {quote(commands)} {quote(self.root)} {quote(evidence)}|ConvertTo-Json -Depth 8 -Compress")
        data = json.loads(raw.splitlines()[-1])
        self.assertEqual(str(os.getuid()), data['userId'])
        self.assertEqual(str(os.getgid()), data['groupId'])
        self.assertEqual(platform.machine(), data['machine'])
        self.assertEqual(platform.release(), data['kernelRelease'])
        self.assertTrue(data['operatingSystem'])
        self.assertTrue(data['kernelVersion'])
        script = (commands/'cygwin-identity.sh').read_text()
        self.assertNotIn('env', script)
        self.assertNotIn('whoami', script)
        self.assertIn('/usr/bin/id -u', script)
        self.assertIn('/usr/bin/uname -v', script)
        receipt = json.loads((evidence/'cygwin-identity.command.json').read_text())
        self.assertTrue(receipt['passed'])


if __name__ == '__main__': unittest.main()
