"""Portable admission and exact-source transform tests, never native MSVC proof."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mdds_probe', ROOT/'suite/scripts/native_mdds_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AdmissionTests(unittest.TestCase):
    def command(self, code=0):
        return dict(exitCode=code, forcedTermination=False, pipeDrainComplete=True,
                    directProcessDeathVerified=True, cleanupErrors=[], pid=42,
                    creationUtcTicks=639278626391148272)

    def test_original_must_fail_at_matching_equality_declaration(self):
        original = self.command(2)
        log = "flat_segment_tree_def.inl(761): error C2382: 'mdds::flat_segment_tree<Key,Value>::operator ==': redefinition; different exception specifications\nflat_segment_tree.hpp(501): note: see declaration of 'mdds::flat_segment_tree<Key,Value>::operator =='\n"
        probe.admit_original(original, log)
        for command, text in [(self.command(), log), (original, 'error C1083 missing header'),
                              (original, log.replace('hpp(501)', 'hpp(500)')),
                              (dict(original, forcedTermination=True), log),
                              (dict(original, pipeDrainComplete=False), log),
                              (original, log+'error C1083: unrelated error\n')]:
            with self.subTest(command=command, text=text):
                with self.assertRaises(ValueError): probe.admit_original(command, text)
        self.assertEqual(json.loads(json.dumps(original))['creationUtcTicks'], 639278626391148272)

    def test_original_rejects_crash_and_unknown_status_after_matching_diagnostic(self):
        log = "flat_segment_tree_def.inl(761): error C2382: 'mdds::flat_segment_tree<Key,Value>::operator ==': redefinition; different exception specifications\nflat_segment_tree.hpp(501): note: see declaration of 'mdds::flat_segment_tree<Key,Value>::operator =='\n"
        for code in (-1073741819, 3221225477, 1, 3, 99):
            with self.subTest(exitCode=code):
                with self.assertRaises(ValueError):probe.admit_original(self.command(code),log)

    def test_selected_path_is_private_and_cleanup_runs_on_capture_failure(self):
        source=(ROOT/'suite/scripts/probe-native-mdds.ps1').read_text()
        self.assertIn('set PATH > "%~1"',source)
        self.assertNotIn("'set PATH',",source)
        pwsh=os.environ.get('OPENGEUL_MDDS_PWSH') or shutil.which('pwsh')
        if not pwsh:self.skipTest('PowerShell unavailable for private snapshot lifecycle check')
        script=r'''
param([string]$Driver,[string]$Root)
. $Driver
function Invoke-LoggedCommand([string]$FilePath,[string[]]$Arguments,[string]$WorkingDirectory,[string]$LogPrefix,[double]$TimeoutMinutes) {
    if($Arguments[-1] -cne (Join-Path $WorkingDirectory 'selected-path.private.txt')){throw 'Private path argument differs.'}
    Set-Content -LiteralPath $Arguments[-1] -Value 'PATH=private-path-fixture-sentinel' -Encoding utf8NoBOM
    Set-Content -LiteralPath ($LogPrefix+'.stdout.log') -Value @('INCLUDE=selected/include','LIB=selected/lib','LIBPATH=selected/libpath','WindowsSdkDir=selected/sdk') -Encoding utf8NoBOM
    if($script:throwCapture){throw 'Injected command capture failure.'}
}
foreach($failure in @($false,$true)) {
    $name=if($failure){'failure'}else{'success'};$work=Join-Path $Root ($name+'-work');$out=Join-Path $Root ($name+'-evidence')
    New-Item -ItemType Directory $work,$out|Out-Null;$script:throwCapture=$failure;$caught=$false
    try {
        $selected=Get-MddsToolchainEnvironment 'selected-vsdevcmd.bat' 'mock-native-cmd' $work $out
        if($failure){throw 'Expected capture failure.'}
        if($selected['PATH'] -cne 'private-path-fixture-sentinel'){throw 'Selected private PATH differs.'}
        $digest=Get-Content (Join-Path $out 'path-environment.json') -Raw|ConvertFrom-Json
        $expected=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($selected['PATH']))).ToLowerInvariant()
        if($digest.pathSha256 -cne $expected){throw 'PATH digest differs.'}
    } catch {
        $caught=$true
        if(-not $failure -or $_.Exception.Message -cne 'Injected command capture failure.'){throw}
    }
    if($failure -and -not $caught){throw 'Failure not observed.'}
    if(Test-Path -LiteralPath (Join-Path $work 'selected-path.private.txt')){throw 'Private snapshot was retained.'}
    foreach($file in Get-ChildItem -LiteralPath $out -File){if([IO.File]::ReadAllText($file.FullName).Contains('private-path-fixture-sentinel')){throw 'Raw PATH reached evidence.'}}
}
Write-Output 'private-path-success-and-failure-cleanup-passed'
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'path-lifecycle.ps1';path.write_text(script)
            result=subprocess.run([pwsh,'-NoProfile','-File',str(path),str(ROOT/'suite/scripts/probe-native-mdds.ps1'),tmp],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('private-path-success-and-failure-cleanup-passed',result.stdout)

    def test_object_machine_is_checked_without_treating_coff_as_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'probe.obj'; p.write_bytes(b'\x64\xaa'+b'\0'*18)
            self.assertEqual(probe.object_identity(p)['machine'], 0xaa64)
            p.write_bytes(b'\x64\x86'+b'\0'*18)
            with self.assertRaises(ValueError): probe.object_identity(p)

    def test_native_bigobj_machine_uses_its_actual_coff_header(self):
        import struct
        header=struct.pack('<HHHHI',0,0xffff,2,0xaa64,0)+bytes.fromhex('c7a1bad1eebaa94baf20faf66aa4dcb8')+bytes(28)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'probe.obj';p.write_bytes(header)
            self.assertEqual(probe.object_identity(p)['machine'],0xaa64)
            p.write_bytes(header[:6]+b'\x64\x86'+header[8:])
            with self.assertRaises(ValueError):probe.object_identity(p)

    def test_unsafe_archive_members_and_collisions_are_rejected(self):
        for name in ['x/../../escape', 'x/a\\b', '/x/absolute', 'x/C:/drive']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'source.tar'; root=Path(tmp)/'tree'
                with tarfile.open(p, 'w') as out:
                    row=tarfile.TarInfo(name);row.size=1;out.addfile(row, io.BytesIO(b'x'))
                with self.assertRaises(ValueError): probe.extract_complete(p, root, 'x', 100, 10000)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.tar'; root=Path(tmp)/'tree'
            with tarfile.open(p, 'w') as out:
                for _ in range(2):
                    row=tarfile.TarInfo('x/file');row.size=1;out.addfile(row, io.BytesIO(b'x'))
            with self.assertRaises(ValueError): probe.extract_complete(p, root, 'x', 100, 10000)


@unittest.skipUnless(os.environ.get('OPENGEUL_MDDS_REAL_SOURCE'), 'Set authenticated original MDDS directory for real source contracts')
class RealSourceTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(os.environ['OPENGEUL_MDDS_REAL_SOURCE'])
        self.hpp=(self.root/'include/mdds/flat_segment_tree.hpp').read_bytes()
        self.inl=(self.root/'include/mdds/flat_segment_tree_def.inl').read_bytes()

    def test_only_exact_equality_body_moves_and_second_application_fails(self):
        hpp,inl=probe.relocate(self.hpp,self.inl)
        self.assertEqual(hpp.replace(probe.IN_CLASS,probe.DECL),self.hpp)
        self.assertEqual(inl.replace(probe.AFTER_DEFINITION,probe.DEFINITION+probe.AFTER_DEFINITION),self.inl)
        self.assertEqual(hpp.count(b'noexcept(nothrow_eq_comparable_v)'), self.hpp.count(b'noexcept(nothrow_eq_comparable_v)'))
        for h,i in [(hpp,inl),(self.hpp+b' ',self.inl),(self.hpp,self.inl.replace(b'noexcept',b'NOEXCEPT',1))]:
            with self.assertRaises(ValueError):probe.relocate(h,i)

    def test_real_lo_patch_unconditionally_changes_node(self):
        patch=Path(os.environ['OPENGEUL_MDDS_REAL_PATCH']).read_bytes()
        node=(self.root/'include/mdds/node.hpp').read_bytes()
        patched=probe.apply_lo_patch(node,patch)
        self.assertIn(b'if(--p->refcount == 0)',patched)
        self.assertNotIn(b'    --p->refcount;\n    if (!p->refcount)',patched)
        with self.assertRaises(ValueError): probe.apply_lo_patch(patched,patch)
        with self.assertRaises(ValueError): probe.apply_lo_patch(node,patch+b' ')


if __name__=='__main__':unittest.main()
