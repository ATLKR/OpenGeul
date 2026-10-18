import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DRIVER = ROOT/'suite/scripts/probe-native-atl.ps1'
PWSH = shutil.which('pwsh')
POSIX_REPLAY = os.name == 'posix' and all(pathlib.Path(p).is_file() for p in ('/bin/bash','/usr/bin/make','/usr/bin/python3'))


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def coff_archive(machine=0xaa64):
    data = struct.pack('<HHIIIHH', machine, 0, 0, 0, 0, 0, 0)
    header = b'probe.obj/'.ljust(16) + b'0'.ljust(12) + b'0'.ljust(6)*2 + b'0'.ljust(8) + str(len(data)).encode().ljust(10) + b'`\n'
    return b'!<arch>\n' + header + data


@unittest.skipUnless(PWSH, 'PowerShell is required for the diagnostic controller tests')
class NativeAtlControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def ps(self, command, success=True):
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command',
                                 "$ErrorActionPreference='Stop'; . " + quote(DRIVER) + '; ' + command],
                                capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        else:
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def toolchain(self):
        vs = self.root/'VS18'
        tools = vs/'VC/Tools/MSVC/14.51.36231'
        tools.mkdir(parents=True)
        default = vs/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
        default.parent.mkdir(parents=True)
        default.write_text('14.51.36231\n')
        instance = dict(instanceId='selected', installationVersion='18.10.12224.181',
                        installationPath=str(vs), productId='Microsoft.VisualStudio.Product.Enterprise', isComplete=True, isPrerelease=False)
        inp = self.root/'instances.json'
        inp.write_text(json.dumps([instance]))
        return inp, tools

    def census(self, machine=0xaa64):
        _, tools = self.toolchain()
        inc = tools/'atlmfc/include'
        inc.mkdir(parents=True)
        for name in ('atlbase.h', 'atlcom.h', 'atlctl.h'):
            (inc/name).write_text('/* header fixture */\n')
        lib = tools/'atlmfc/lib/spectre/arm64/atls.lib'
        lib.parent.mkdir(parents=True)
        lib.write_bytes(coff_archive(machine))
        data = lib.read_bytes()
        member = dict(ordinal=0, headerOffset=8, payloadOffset=68, rawName='probe.obj/', resolvedName='probe.obj',
                      payloadBytes=20, payloadSha256=hashlib.sha256(data[68:]).hexdigest(), kind='ordinaryCoffObject', machine=machine)
        profiles = [dict(kind=kind, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                         aa64ObjectCount=int(machine == 0xaa64), arm64EcObjectCount=int(machine == 0xa641), members=[member])
                    for kind in ('regular','spectre')]
        (self.root/'census-profiles.json').write_text(json.dumps(profiles))
        return tools, inc, lib

    def census_call(self, tools):
        return f"Get-AtlCensus {quote(tools)} @(Get-Content -Raw {quote(self.root/'census-profiles.json')}|ConvertFrom-Json)"

    def test_selected_vs18_default_toolset_is_bound_without_other_vs_fallback(self):
        inp, tools = self.toolchain()
        data = json.loads(self.ps(f"Get-AtlToolchainPlan @(Get-Content -Raw {quote(inp)}|ConvertFrom-Json)|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual(str(tools), data['compilerRoot'])
        self.assertEqual('v145', data['toolset'])
        instances = json.loads(inp.read_text())
        instances.append(dict(instances[0], instanceId='ambiguous'))
        inp.write_text(json.dumps(instances))
        self.ps(f"Get-AtlToolchainPlan @(Get-Content -Raw {quote(inp)}|ConvertFrom-Json)", success=False)
        inp.write_text(json.dumps([dict(instances[0], installationVersion='17.14.1')]))
        self.ps(f"Get-AtlToolchainPlan @(Get-Content -Raw {quote(inp)}|ConvertFrom-Json)", success=False)

    def test_census_requires_headers_and_selected_arm64_archive(self):
        tools, inc, lib = self.census()
        data = json.loads(self.ps(self.census_call(tools)+"|ConvertTo-Json -Depth 12 -Compress"))
        self.assertTrue(data['readyForNativeLinkMeasurement'])
        self.assertEqual([0xaa64], data['selectedLibrary']['machines'])
        self.assertEqual(str(lib), data['selectedLibrary']['path'])
        self.assertTrue(all(item['sha256'] for item in data['headers']))
        (inc/'atlbase.h').unlink()
        data = json.loads(self.ps(self.census_call(tools)+"|ConvertTo-Json -Depth 12 -Compress"))
        self.assertFalse(data['readyForNativeLinkMeasurement'])
        self.assertIsNone(data['headers'][0]['sha256'])
        self.assertEqual('missing', data['headers'][0]['status'])

    def test_selected_spectre_parent_does_not_fallback_to_regular_arm64_library(self):
        tools, _, lib = self.census()
        lib.unlink()
        regular = tools/'atlmfc/lib/arm64/atls.lib'
        regular.parent.mkdir(parents=True)
        regular.write_bytes(coff_archive())
        data = json.loads(self.ps(self.census_call(tools)+"|ConvertTo-Json -Depth 12 -Compress"))
        self.assertFalse(data['readyForNativeLinkMeasurement'])
        self.assertEqual(str(lib), data['selectedLibrary']['path'])
        self.assertIsNone(data['selectedLibrary']['sha256'])

    def test_foreign_arm64ec_archive_and_linked_headers_are_rejected(self):
        tools, inc, _ = self.census(0xa641)
        data = json.loads(self.ps(self.census_call(tools)+"|ConvertTo-Json -Depth 12 -Compress"))
        self.assertFalse(data['readyForNativeLinkMeasurement'])
        self.assertEqual('rejected', data['selectedLibrary']['status'])
        target = self.root/'outside.h'; target.write_text('outside')
        (inc/'atlbase.h').unlink()
        (inc/'atlbase.h').symlink_to(target)
        data = json.loads(self.ps(self.census_call(tools)+"|ConvertTo-Json -Depth 12 -Compress"))
        self.assertFalse(data['readyForNativeLinkMeasurement'])
        self.assertEqual('rejected', data['headers'][0]['status'])

    def test_nonzero_diagnostic_is_admitted_only_with_normal_drained_completion(self):
        receipt = dict(exitCode=2, passed=False, pipeDrainComplete=True, forcedTermination=False,
                       directProcessDeathVerified=True, processTreeCleanup='not-requested', cleanupErrors=[])
        p = self.root/'command.json'
        p.write_text(json.dumps(receipt))
        data = json.loads(self.ps(f"Assert-AtlCommandCompletion (Get-Content -Raw {quote(p)}|ConvertFrom-Json)|ConvertTo-Json -Compress"))
        self.assertFalse(data['succeeded'])
        for field, value in [('forcedTermination', True), ('pipeDrainComplete', False), ('directProcessDeathVerified', False), ('cleanupErrors', ['failed'])]:
            p.write_text(json.dumps(dict(receipt, **{field:value})))
            self.ps(f"Assert-AtlCommandCompletion (Get-Content -Raw {quote(p)}|ConvertFrom-Json)", success=False)

    def test_only_make_exit2_can_join_expected_error_text_as_failed_baseline_evidence(self):
        receipt = dict(exitCode=2, passed=False, pipeDrainComplete=True, forcedTermination=False,
                       directProcessDeathVerified=True, processTreeCleanup='not-requested', cleanupErrors=[])
        p = self.root/'make-command.json'
        log = self.root/'make-output.log'
        expected = {
            'Header': "C:\\owned\\atl-control.cpp(4): fatal error C1083: Cannot open include file: 'atlbase.h': No such file or directory\n",
            'Library': "LINK : fatal error LNK1104: cannot open file '/cygdrive/c/atl/lib/atls.lib'\n",
        }
        for kind, text in expected.items():
            log.write_text(text)
            command = (f"Assert-AtlCommandCompletion (Get-Content -Raw {quote(p)}|ConvertFrom-Json)|Out-Null; "
                       f"Assert-AtlExpectedFailure {quote(log)} {kind}|ConvertTo-Json -Compress")
            with self.subTest(kind=kind, exitCode=2):
                p.write_text(json.dumps(receipt))
                data = json.loads(self.ps(command))
                self.assertEqual(kind, data['kind'])
            for code in (139, 3221225477, -1073741819, 1, 127):
                with self.subTest(kind=kind, exitCode=code):
                    p.write_text(json.dumps(dict(receipt, exitCode=code)))
                    self.ps(command, success=False)
        with self.subTest(kind='candidate-success', exitCode=0):
            p.write_text(json.dumps(dict(receipt, exitCode=0, passed=True)))
            data = json.loads(self.ps(f"Assert-AtlCommandCompletion (Get-Content -Raw {quote(p)}|ConvertFrom-Json)|ConvertTo-Json -Compress"))
            self.assertTrue(data['succeeded'])
            self.assertEqual(0, data['exitCode'])

    def test_only_expected_atl_header_and_library_failures_support_path_findings(self):
        log = self.root/'failure.log'
        log.write_text("C:\\owned\\atl-control.cpp(4): fatal error C1083: Cannot open include file: 'atlbase.h': No such file or directory\n")
        self.ps(f"Assert-AtlExpectedFailure {quote(log)} Header")
        for text in ('access violation', 'fatal error C1083: cannot open windows.h', 'fatal error LNK2001: unresolved external symbol'):
            log.write_text(text)
            self.ps(f"Assert-AtlExpectedFailure {quote(log)} Header", success=False)
            self.ps(f"Assert-AtlExpectedFailure {quote(log)} Library", success=False)
        log.write_text("LINK : fatal error LNK1104: cannot open file '/cygdrive/c/atl/lib/atls.lib'\n")
        self.ps(f"Assert-AtlExpectedFailure {quote(log)} Library")

    def test_showincludes_must_witness_the_selected_census_header(self):
        header = self.root/'atlbase.h'; header.write_text('header')
        log = self.root/'include.log'
        log.write_text('Note: including file: '+str(header)+'\n')
        data = json.loads(self.ps(f"Assert-AtlHeaderInclusion {quote(log)} {quote(header)}|ConvertTo-Json -Compress"))
        self.assertEqual(str(header), data['header'])
        log.write_text('Note: including file: '+str(self.root/'other/atlbase.h')+'\n')
        self.ps(f"Assert-AtlHeaderInclusion {quote(log)} {quote(header)}", success=False)

    def test_native_consumption_requires_archive_loaded_and_map_evidence(self):
        _, _, lib = self.census()
        log = self.root/'link.log'
        mapping = self.root/'link.map'
        mapping.write_text(' 0001:00000000 ?owned@@YAXXZ 0000000140001000 f atls:probe.obj\n')
        command = (f"$pin=@(Get-Content -Raw {quote(self.root/'census-profiles.json')}|ConvertFrom-Json)|Where-Object kind -eq 'spectre'; "
                   f"$library=Read-AtlStaticArchive {quote(lib)} $pin; Assert-AtlNativeConsumption @({quote(log)}) {quote(mapping)} $library|ConvertTo-Json -Depth 12 -Compress")
        log.write_text('Searching '+str(lib)+':\n')
        self.ps(command, success=False)
        log.write_text('    Loaded '+str(lib)+'(probe.obj)\n')
        data = json.loads(self.ps(command))
        self.assertTrue(data['nativeConsumedOnlyVerified'])
        self.assertEqual('probe.obj', data['consumedMembers'][0]['resolvedName'])
        log.write_text('    Loaded '+str(self.root/'other/atls.lib')+'(probe.obj)\n')
        self.ps(command, success=False)

    def test_control_classifies_path_axes_without_claiming_engine_qualification(self):
        command = "Get-AtlControlConclusion $false $true $false $true|ConvertTo-Json -Compress"
        data = json.loads(self.ps(command))
        self.assertEqual('configured-header-and-library-paths-unusable', data['finding'])
        self.assertFalse(data['fullEngineQualified'])
        self.assertFalse(data['guiVerified'])
        data = json.loads(self.ps("Get-AtlControlConclusion $true $true $true $true|ConvertTo-Json -Compress"))
        self.assertEqual('atl-prerequisite-reproduced-no-path-failure', data['finding'])

    def test_native_argument_builders_preserve_distinct_optimized_compile_and_explicit_library_arguments(self):
        command = "Get-AtlCompileArguments @('C:/sdk/include') '/cygdrive/c/atl/include' 'C:/work/probe.cpp' 'C:/work/probe.obj' 'C:/work/probe.pdb'|ConvertTo-Json -Compress"
        args = json.loads(self.ps(command))
        self.assertIn('-I/cygdrive/c/atl/include', args)
        self.assertEqual(['-c','C:/work/probe.cpp','-FoC:/work/probe.obj','-FdC:/work/probe.pdb'], args[-4:])
        for flag in ('-O2','-GL','-MD','-EHsc','-std:c++20'):
            self.assertIn(flag,args)
        args = json.loads(self.ps("Get-AtlLinkArguments @('C:/sdk/lib/arm64') '/cygdrive/c/atl/lib/arm64' 'C:/work/probe.obj' 'C:/work/probe.exe' 'C:/work/probe.map'|ConvertTo-Json -Compress"))
        self.assertIn('/cygdrive/c/atl/lib/arm64/atls.lib',args)
        self.assertIn('-LIBPATH:/cygdrive/c/atl/lib/arm64',args)
        self.assertIn('C:/work/probe.obj',args)
        self.assertIn('-LTCG',args)
        self.assertIn('-MACHINE:ARM64',args)
        self.assertIn('-VERBOSE:LIB',args)

    @unittest.skipUnless(POSIX_REPLAY, 'Portable argv replay needs POSIX Bash, make, and shebang Python')
    def test_real_make_preserves_native_argv_and_normal_owned_receipt(self):
        tools = self.root/'helper tools'; tools.mkdir()
        for name, content in {
            'cygpath.exe': '#!/bin/sh\nprintf "%s\\n" "$2"\n',
            'bash.exe': '#!/bin/sh\nexec /bin/bash "$@"\n',
            'env.exe': '#!/bin/sh\nexec /usr/bin/env "$@"\n',
            'argv tool': '#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n',
        }.items():
            p = tools/name; p.write_text(content); p.chmod(0o755)
        evidence = self.root/'evidence'; evidence.mkdir()
        args = ['/cygdrive/c/tool/include', 'C:/path with spaces/atls.lib', "literal'quote", '$HOME`touch /no`$(bad)']
        array = '@('+','.join(quote(item) for item in args)+')'
        output = self.ps(f"Write-AtlMakeControl probe {array} {quote(tools/'argv tool')} {quote(self.root)} {quote(evidence)} {quote(tools/'bash.exe')} {quote(tools/'cygpath.exe')} {quote(self.root)}|ConvertTo-Json -Depth 8 -Compress")
        result = json.loads(output.strip().split('\n')[-1])
        self.assertTrue(result['succeeded'])
        observed = json.loads(pathlib.Path(result['stdout']).read_bytes().split(b'\n')[-2])
        self.assertEqual(args, observed)
        receipt = json.loads(pathlib.Path(result['commandReceipt']).read_bytes())
        self.assertTrue(receipt['pipeDrainComplete'])
        self.assertFalse(receipt['forcedTermination'])
        self.assertTrue(receipt['directProcessDeathVerified'])

    @unittest.skipUnless(os.name == 'posix', 'Checks actual non-Windows fail-closed entrypoint')
    def test_dot_sourcing_helpers_preserves_requested_fresh_evidence_destination(self):
        work, evidence = self.root/'custom work', self.root/'custom evidence'
        result = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(DRIVER),
                                 '-WorkDirectory', str(work), '-OutputDirectory', str(evidence)],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertTrue((evidence/'atl-control-receipt.json').is_file(), result.stdout+result.stderr)
        receipt = json.loads((evidence/'atl-control-receipt.json').read_bytes())
        self.assertFalse(receipt['completed'])
        self.assertFalse(receipt['fullEngineQualified'])
        self.assertIsNone(receipt['configuredPaths'])


if __name__ == '__main__':
    unittest.main()
