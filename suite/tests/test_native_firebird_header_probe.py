"""Header-only diagnostic boundaries, using real pinned patch/header bytes.

The tiny LO tar is a container fixture; every extracted patch retains its real
manifest SHA. No portable result qualifies MSVC, Windows or an Office engine.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / 'suite/scripts/probe-native-firebird-header.ps1'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'
INPUTS = Path('/workspace/work/opengeul-improvements/work/arm64-expansion-research/firebird-port-inputs')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class NativeFirebirdHeaderProbeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PROBE.is_file(), 'The bounded native header diagnostic is missing')
        self.temp = tempfile.TemporaryDirectory(prefix='firebird-header-probe-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'evidence'; self.output.mkdir()
        self.manifest = json.loads((ROOT / 'suite/engine-build/source-build.json').read_bytes())
        self.archive = Path(os.environ.get('OPENGEUL_FIREBIRD_SOURCE_ARCHIVE',
            str(INPUTS / 'Firebird-3.0.13.33818-0.tar.bz2')))
        self.patches = Path(os.environ.get('OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES', str(INPUTS / 'libreoffice-firebird')))

    def require_source_inputs(self):
        if not self.archive.is_file() or not self.patches.is_dir():
            if os.environ.get('OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE') == '1':
                self.fail('Mandatory original Firebird/LibreOffice patch inputs are missing')
            self.skipTest('Pinned local Firebird archive and LibreOffice patch bytes required')

    def ps(self, body, success=True):
        script = self.root / 'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. " + quote(PROBE) + '\n' + body)
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(success, result.returncode == 0, result.stdout + result.stderr)
        return result

    def helper(self):
        path = self.output / 'extract-header.py'
        self.ps('Write-FirebirdHeaderHelper ' + quote(path))
        return path

    def lo_archive(self):
        path = self.root / 'tiny-lo-container.tar.xz'
        with tarfile.open(path, 'w:xz') as archive:
            for pin in self.manifest['upstreamWindowsPatches']:
                data = (self.patches / pin['filename']).read_bytes()
                self.assertEqual(pin['sha256'], hashlib.sha256(data).hexdigest())
                name = 'libreoffice-' + self.manifest['libreoffice']['version'] + '/external/firebird/' + pin['filename']
                entry = tarfile.TarInfo(name); entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        return path

    def preparation(self, manifest_path=None):
        import sys
        self.require_source_inputs()
        return ('Invoke-FirebirdHeaderPreparation -Python ' + quote(sys.executable) +
                ' -Git ' + quote(shutil.which('git')) + ' -Repo ' + quote(ROOT) +
                ' -FirebirdArchive ' + quote(self.archive) +
                ' -LibreOfficeArchive ' + quote(self.lo_archive()) +
                ' -SourceRoot ' + quote(self.root / 'source') + ' -Output ' + quote(self.output) +
                (' -ManifestPath ' + quote(manifest_path) if manifest_path else ''))

    def test_real_header_and_all_pinned_patch_bytes_prepare_only_the_target(self):
        self.ps(self.preparation())
        header = self.root / 'source/src/include/gen/autoconfig_msvc.h'
        pin = self.manifest['msvcPlatformHeader']
        self.assertEqual(pin['afterSha256'], hashlib.sha256(header.read_bytes()).hexdigest())
        self.assertEqual([header], [p for p in (self.root / 'source').rglob('*') if p.is_file()])
        plan = json.loads((self.output / 'header-extraction.json').read_bytes())
        self.assertEqual(25, len(plan['upstreamPatches']))
        self.assertEqual(pin['upstreamHeaderPatches'], plan['headerPatches'])
        self.assertEqual(pin['archiveSha256'], hashlib.sha256((self.output / 'header-from-archive.h').read_bytes()).hexdigest())
        self.assertEqual(pin['beforeSha256'], hashlib.sha256((self.output / 'header-before-port.h').read_bytes()).hexdigest())
        commands = [json.loads(p.read_bytes()) for p in self.output.glob('apply-*.command.json')]
        self.assertEqual(2, len(commands))
        self.assertTrue(all(c['passed'] and c['exitCode'] == 0 and c['pipeDrainComplete'] for c in commands))
        self.assertTrue(all('--include=src/include/gen/autoconfig_msvc.h' in c['arguments'] for c in commands))

    def test_wrong_final_header_pin_fails_and_preserves_original_command_evidence(self):
        changed = json.loads(json.dumps(self.manifest)); changed['msvcPlatformHeader']['afterSha256'] = 'f' * 64
        pin = self.root / 'changed-manifest.json'; pin.write_text(json.dumps(changed))
        result = self.ps(self.preparation(pin), success=False)
        self.assertIn('header-after-port', result.stderr)
        self.assertTrue((self.output / 'header-before-port.h').is_file())
        self.assertTrue((self.output / 'apply-port-header.command.json').is_file())

    def test_duplicate_or_link_header_is_rejected_before_target_write(self):
        import sys
        self.require_source_inputs()
        helper = self.helper(); lo = self.lo_archive()
        with tarfile.open(self.archive) as archive:
            name = 'Firebird-' + self.manifest['firebird']['version'] + '/src/include/gen/autoconfig_msvc.h'
            data = archive.extractfile(name).read()
        for kind in ('duplicate', 'symlink'):
            with self.subTest(kind=kind):
                fb = self.root / (kind + '.tar.bz2')
                with tarfile.open(fb, 'w:bz2') as archive:
                    entry = tarfile.TarInfo(name); entry.size = len(data)
                    if kind == 'symlink':
                        entry.type = tarfile.SYMTYPE; entry.linkname = '../foreign'; entry.size = 0
                    archive.addfile(entry, io.BytesIO(data) if kind != 'symlink' else None)
                    if kind == 'duplicate': archive.addfile(entry, io.BytesIO(data))
                source = self.root / kind
                result = subprocess.run([sys.executable, str(helper), str(fb), str(lo),
                    str(ROOT / 'suite/engine-build/source-build.json'), str(source), str(self.root / (kind + '-evidence'))],
                    capture_output=True, text=True, timeout=15)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse((source / 'src/include/gen/autoconfig_msvc.h').exists())

    @unittest.skipUnless(os.name != 'nt' and shutil.which('g++'), 'Portable native-ABI rejection boundary needs GNU C++')
    def test_generated_compile_source_rejects_foreign_predefs_and_host_long_abi(self):
        self.ps(self.preparation())
        cpp = self.root / 'probe.cpp'
        self.ps('Write-FirebirdHeaderCompileSource ' + quote(cpp))
        base = [shutil.which('g++'), '-std=c++17', '-fsyntax-only', '-I' + str(self.root / 'source'), str(cpp)]
        for macros in ([], ['-D_M_ARM64=1', '-D_M_ARM64EC=1']):
            result = subprocess.run(base + macros, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('actual native MSVC ARM64 ABI', result.stderr)
        result = subprocess.run(base + ['-D_M_ARM64=1'], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('native Windows LLP64 long', result.stderr)

    def test_coff_architecture_and_bounds_are_checked_without_claiming_a_compile(self):
        obj = self.root / 'fixture.obj'
        data = bytearray(60); struct.pack_into('<HH', data, 0, 0xaa64, 1)
        obj.write_bytes(data)
        self.ps('Get-FirebirdHeaderObjectIdentity ' + quote(obj) + ' | Out-Null')
        for machine, sections in ((0x8664, 1), (0xaa64, 2)):
            struct.pack_into('<HH', data, 0, machine, sections); obj.write_bytes(data)
            self.ps('Get-FirebirdHeaderObjectIdentity ' + quote(obj) + ' | Out-Null', success=False)


if __name__ == '__main__':
    unittest.main()
