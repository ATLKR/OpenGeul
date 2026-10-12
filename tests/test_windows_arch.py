"""아키텍처 선언·PE·매니페스트·전체 런타임이 일치해야 준비한다."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e')]
from buildkit import DEV_IDENTITY, manifest
from releasekit import pe_machine, verify_msix
from prepare_payload import prepare


def pe(machine):
    raw = bytearray(256)
    raw[:2] = b'MZ'
    struct.pack_into('<I', raw, 60, 128)
    raw[128:132] = b'PE\0\0'
    struct.pack_into('<H', raw, 132, machine)
    return bytes(raw)


class WindowsArchitectureTests(unittest.TestCase):
    def call(self, function, *args, architecture):
        try:
            return function(*args, architecture=architecture)
        except TypeError as error:
            self.fail(f'명시적 Windows 아키텍처 계약이 필요합니다: {error}')

    def test_arm64_manifest_and_pe_are_accepted_only_when_arm64_is_expected(self):
        xml = self.call(manifest, DEV_IDENTITY, '1.1.3', architecture='arm64')
        identity = ET.fromstring(xml).find('{http://schemas.microsoft.com/appx/manifest/foundation/windows10}Identity')
        self.assertEqual(identity.get('ProcessorArchitecture'), 'arm64')
        self.assertEqual(self.call(pe_machine, pe(0xAA64), architecture='arm64'), 0xAA64)
        with self.assertRaises(ValueError):
            pe_machine(pe(0xAA64))
        with self.assertRaises(ValueError):
            self.call(pe_machine, pe(0x8664), architecture='arm64')
        with self.assertRaises(ValueError):
            self.call(pe_machine, pe(0xA641), architecture='arm64')

    def test_unknown_or_wrong_typed_architecture_is_rejected(self):
        for value in ('x86', 'neutral', 'ARM64', '', None, False, 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.call(manifest, DEV_IDENTITY, '1.1.3', architecture=value)

    def files(self, architecture, cli_machine=None):
        machine = {'x64': 0x8664, 'arm64': 0xAA64}[architecture]
        return {'AppxManifest.xml': self.call(manifest, DEV_IDENTITY, '1.1.3', architecture=architecture).encode(),
            'OpenGeul.exe': pe(machine), 'Tools/rhwp.exe': pe(machine if cli_machine is None else cli_machine),
            'Notices/OpenGeul-LICENSE.txt': b'MIT'}

    def package(self, root, files):
        msix = root / 'app.msix'
        with zipfile.ZipFile(msix, 'w') as archive:
            for name, raw in dict(files, **{'AppxBlockMap.xml': b'<BlockMap/>', '[Content_Types].xml': b'<Types/>'}).items():
                archive.writestr(name, raw)
        with zipfile.ZipFile(root / 'app-portable.zip', 'w') as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
        (root / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in sorted(root.iterdir())), encoding='utf-8')
        return msix

    def test_each_matching_package_prepares_identical_full_runtime(self):
        for architecture in ('x64', 'arm64'):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'package'; root.mkdir()
                files = self.files(architecture)
                msix = self.package(root, files)
                self.assertEqual(self.call(verify_msix, msix, architecture=architecture)['architecture'], architecture)
                output = Path(temp) / 'runtime'
                result = self.call(prepare, root, output, architecture=architecture)
                self.assertEqual(result['architecture'], architecture)
                for name, raw in files.items():
                    self.assertEqual((output / name).read_bytes(), raw)

    def test_mixed_runtime_or_manifest_never_creates_output(self):
        for declared, cli_machine, expected in [('arm64', 0x8664, 'arm64'), ('arm64', 0xAA64, 'x64'), ('x64', 0xAA64, 'x64')]:
            with self.subTest(declared=declared, cli=cli_machine, expected=expected), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'package'; root.mkdir()
                self.package(root, self.files(declared, cli_machine))
                output = Path(temp) / 'runtime'
                with self.assertRaises(ValueError):
                    self.call(prepare, root, output, architecture=expected)
                self.assertFalse(output.exists())

    def test_x64_dll_in_arm64_package_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'package'; root.mkdir()
            files = self.files('arm64')
            files['WebView2Loader.dll'] = pe(0x8664)
            self.package(root, files)
            output = Path(temp) / 'runtime'
            with self.assertRaises(ValueError):
                self.call(prepare, root, output, architecture='arm64')
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
