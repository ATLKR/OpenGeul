"""Portable boundaries for a diagnostic; no portable engine qualification."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / 'suite/scripts/probe-native-firebird-archive.ps1'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'
INPUTS = Path('/workspace/work/opengeul-improvements/work/arm64-expansion-research/firebird-port-inputs')


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


class NativeFirebirdArchiveProbeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PROBE.is_file(), 'The bounded archive/link diagnostic is missing')
        self.temp = tempfile.TemporaryDirectory(prefix='firebird-archive-probe-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'evidence'; self.out.mkdir()
        self.manifest = json.loads((ROOT / 'suite/engine-build/source-build.json').read_bytes())

    def ps(self, body, success=True):
        path = self.root / 'case.ps1'
        path.write_text("$ErrorActionPreference='Stop'\n. " + q(PROBE) + '\n' + body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(path)], capture_output=True, text=True, timeout=40)
        self.assertEqual(success, result.returncode == 0, result.stdout + result.stderr)
        return result

    def helper(self):
        path = self.out / 'archive-helper.py'
        self.ps('Write-ArchiveProbeHelper ' + q(path))
        return path

    def prepare(self):
        fb = Path(os.environ.get('OPENGEUL_FIREBIRD_SOURCE_ARCHIVE', str(INPUTS / 'Firebird-3.0.13.33818-0.tar.bz2')))
        patches = Path(os.environ.get('OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES', str(INPUTS / 'libreoffice-firebird')))
        if not fb.is_file() or not patches.is_dir():
            if os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1':
                self.fail('Mandatory original source inputs are missing')
            self.skipTest('Pinned source archive and patch bytes required')
        self.assertEqual(self.manifest['firebird']['sha256'], hashlib.sha256(fb.read_bytes()).hexdigest())
        lo = self.root / 'tiny-lo-container.tar.xz'
        with tarfile.open(lo, 'w:xz') as archive:
            for pin in self.manifest['upstreamWindowsPatches']:
                data = (patches / pin['filename']).read_bytes()
                self.assertEqual(pin['sha256'], hashlib.sha256(data).hexdigest())
                item = tarfile.TarInfo('libreoffice-' + self.manifest['libreoffice']['version'] + '/external/firebird/' + pin['filename'])
                item.size = len(data); archive.addfile(item, io.BytesIO(data))
        self.ps('Invoke-ArchiveRecipePreparation -Python ' + q(sys.executable) + ' -Git ' + q(shutil.which('git')) +
                ' -Repo ' + q(ROOT) + ' -FirebirdArchive ' + q(fb) + ' -LibreOfficeArchive ' + q(lo) +
                ' -SourceRoot ' + q(self.root / 'source') + ' -Output ' + q(self.out) + ' | Out-Null')
        return json.loads((self.out / 'archive-recipe.json').read_bytes())

    def test_authenticated_recipe_replays_and_expands_the_actual_ar_crus(self):
        recipe = self.prepare()
        self.assertEqual('ar', recipe['archiveTool'])
        self.assertEqual('$(AR) crus', recipe['staticLibraryLink'])
        self.assertEqual('$(STATICLIB_LINK) $@ $^', recipe['archiveCommand'])
        self.assertEqual(25, len(recipe['upstreamPatches']))
        self.assertTrue((self.out / 'original-make.defaults').is_file())
        self.assertTrue((self.out / 'effective-Makefile.in').is_file())
        makefile = self.out / 'comparison.mk'
        (self.out / 'archive-probe.obj').touch()
        self.ps('Write-ArchiveComparisonMakefile ' + q(makefile) + ' ' + q(self.out / 'archive-recipe.json'))
        result = subprocess.run([shutil.which('make'), '-n', '-f', str(makefile), 'common.lib'], cwd=self.out,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('ar  crus common.lib archive-probe.obj', result.stdout)
        self.assertNotIn('lib.exe', result.stdout)
        for patch in recipe['upstreamPatches']:
            if patch['recipeIncluded']:
                raw = (self.out / 'recipe-patches' / patch['filename']).read_bytes()
                original = (self.out / 'upstream-patches' / patch['filename']).read_bytes()
                self.assertEqual(patch['selectedDiffSha256'], hashlib.sha256(raw).hexdigest())
                # Every retained selected diff section is unchanged source bytes.
                for section in raw.split(b'--- ')[1:]:
                    self.assertIn(b'--- ' + section, original)

    @unittest.skipUnless(os.name != 'nt' and shutil.which('make'), 'Portable make process boundary requires POSIX GNU make')
    def test_native_make_recipe_passes_literal_out_and_the_same_object_to_explicit_tool(self):
        tool = self.root / 'selected-lib.exe'
        tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > received.txt\n')
        tool.chmod(0o755)
        obj = self.root / 'archive-probe.obj'; obj.write_bytes(b'controlled object, never native qualification')
        makefile = self.root / 'native.mk'
        self.ps('Write-ArchiveNativeMakefile ' + q(makefile) + ' ' + q(tool) + ' ' + q(obj))
        result = subprocess.run([shutil.which('make'), '--no-print-directory', '-f', str(makefile), 'common.lib'],
                                cwd=self.root, capture_output=True, text=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['/NOLOGO', '/OUT:common.lib', str(obj)], (self.root / 'received.txt').read_text().splitlines())

    def test_changed_recipe_is_rejected_before_a_comparison_is_written(self):
        self.prepare()
        path = self.root / 'source/builds/posix/make.defaults'
        path.write_bytes(path.read_bytes().replace(b'$(AR) crus', b'$(AR) cr'))
        result = subprocess.run([sys.executable, str(self.out / 'archive-helper.py'), 'recipe', str(self.root / 'source'),
            str(self.out / 'changed.json'), str(self.out)], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('Expected exact original archive recipe', result.stderr)
        self.assertFalse((self.out / 'changed.json').exists())

    def test_archive_inspection_preserves_missing_index_and_rejects_truncated_members(self):
        helper = self.helper(); path = self.out / 'common.lib'
        def member(name, raw):
            return (name.ljust(16) + '0'.ljust(12) + '0'.ljust(6) + '0'.ljust(6) + '100644'.ljust(8) +
                    str(len(raw)).ljust(10) + '`\n').encode() + raw + (b'\n' if len(raw) % 2 else b'')
        obj = bytearray(60); struct.pack_into('<HH', obj, 0, 0xaa64, 1)
        path.write_bytes(b'!<arch>\n' + member('probe.obj/', obj))
        def inspect():
            result = subprocess.run([sys.executable, str(helper), 'inspect', str(path)], capture_output=True, text=True, timeout=5)
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)
        data = inspect()
        self.assertTrue(data['structurallyComplete']); self.assertEqual([], data['linkerMembers'])
        self.assertEqual(0xaa64, data['members'][0]['machine'])
        path.write_bytes(path.read_bytes()[:-1]); data = inspect()
        self.assertFalse(data['structurallyComplete']); self.assertIn('Truncated archive member', data['error'])

    def test_expected_nonzero_is_observed_without_erasing_the_raw_command_failure(self):
        child = self.root / 'exit-seven.py'; child.write_text('import sys; print("original archive failure"); sys.exit(7)\n')
        result = self.ps('$script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes 1\n' +
            '$r=Invoke-ArchiveObservedCommand ' + q(sys.executable) + ' @(' + q(child) + ') ' + q(self.root) + ' ' + q(self.out / 'original') + '\n' +
            '$r | ConvertTo-Json -Depth 8')
        record = json.loads(result.stdout[result.stdout.rfind('\n{') + 1:])
        self.assertFalse(record['passed']); self.assertEqual(7, record['exitCode'])
        raw = json.loads((self.out / 'original.command.json').read_bytes())
        self.assertFalse(raw['passed']); self.assertTrue(raw['pipeDrainComplete']); self.assertFalse(raw['forcedTermination'])
        self.assertIn('original archive failure', (self.out / 'original.stdout.log').read_text())

    def test_foreign_or_unjoined_runtime_never_qualifies_the_native_control(self):
        base = {'passed': True, 'exitCode': 0, 'pipeDrainComplete': True, 'directProcessDeathVerified': True,
                'forcedTermination': False, 'cleanupErrors': [], 'pid': 101}
        for name in ('library', 'link', 'run'):
            (self.out / (name + '.command.json')).write_text(json.dumps(base))
        runtime = self.out / 'run.stdout.log'
        valid = {'kind': 'native-arm64-archive-link-probe', 'pid': 101, 'processMachine': 0, 'nativeMachine': 0xaa64, 'value': 42}
        def confirm(success):
            return self.ps('Confirm-ArchiveNativeControl ' + q(self.out) + ' | Out-Null', success=success)
        runtime.write_text(json.dumps(valid) + '\n'); confirm(True)
        for field, value in [('pid', 102), ('processMachine', 0x8664), ('nativeMachine', 0x8664), ('value', 41)]:
            changed = dict(valid); changed[field] = value; runtime.write_text(json.dumps(changed) + '\n'); confirm(False)
        runtime.write_text(json.dumps(valid) + '\n')
        changed = dict(base, forcedTermination=True); (self.out / 'link.command.json').write_text(json.dumps(changed)); confirm(False)

    def test_native_batch_uses_explicit_tool_and_host_target_with_no_environment_injection(self):
        batch = self.out / 'native.cmd'
        self.ps('Write-ArchiveNativeBatch ' + q(batch) + " 'C:/VS/VsDevCmd.bat' 'C:/VS/Hostarm64/arm64/lib.exe' @('/NOLOGO','/OUT:C:/out/common.lib','C:/out/archive-probe.obj')")
        text = batch.read_text()
        self.assertIn('-arch=arm64 -host_arch=arm64', text)
        self.assertIn('"C:/VS/Hostarm64/arm64/lib.exe" "/NOLOGO" "/OUT:C:/out/common.lib"', text)
        self.assertIn('set LIB=', text); self.assertIn('set CL=', text)
        self.ps('Write-ArchiveNativeBatch ' + q(self.out / 'bad.cmd') + " 'C:/VS/VsDevCmd.bat' 'C:/VS/lib.exe' @('/OUT:C:/bad&echo.exe')", success=False)


if __name__ == '__main__':
    unittest.main()
