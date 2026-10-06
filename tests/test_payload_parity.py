"""Tests exercise real ZIP/checksum verification, never an extraction mock."""
import hashlib
import io
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'e2e'), str(ROOT / 'scripts')]
from prepare_payload import prepare
from buildkit import manifest, DEV_IDENTITY


class PayloadParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        self.output = self.root / 'runtime'
        pe = bytearray(256)
        pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
        pe[128:132] = b'PE\0\0'; pe[132:134] = (0x8664).to_bytes(2, 'little')
        self.payload = {'AppxManifest.xml': manifest(DEV_IDENTITY, '1.0.0').encode(),
                        'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                        'WebView2Loader.dll': b'loader-original',
                        'Notices/OpenGeul-LICENSE.txt': b'MIT', 'Assets/StoreLogo.png': b'PNG'}
        self.metadata = {'AppxBlockMap.xml': b'<BlockMap/>', '[Content_Types].xml': b'<Types/>'}
        self.msix = self.package / 'app.msix'
        self.portable = self.package / 'app-portable.zip'
        self.write_zip(self.msix, {**self.payload, **self.metadata})
        self.write_zip(self.portable, self.payload)
        self.checksums()

    def write_zip(self, path, files):
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files.items(): z.writestr(name, data)

    def checksums(self, omit=()):
        data = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                       for p in sorted(self.package.iterdir()) if p.name != 'SHA256SUMS.txt' and p.name not in omit)
        (self.package / 'SHA256SUMS.txt').write_text(data)

    def rejected(self):
        with self.assertRaises((ValueError, zipfile.BadZipFile)): prepare(self.package, self.output)
        self.assertFalse(self.output.exists(), 'Failed preflight left a partial runtime')

    def test_equal_full_runtime_is_accepted(self):
        prepare(self.package, self.output)
        self.assertEqual((self.output / 'WebView2Loader.dll').read_bytes(), b'loader-original')

    def test_dll_mismatch_is_not_hidden_by_equal_exes(self):
        self.write_zip(self.portable, {**self.payload, 'WebView2Loader.dll': b'different-loader'})
        self.checksums(); self.rejected()

    def test_resource_mismatch_is_rejected(self):
        self.write_zip(self.portable, {**self.payload, 'Assets/StoreLogo.png': b'different'})
        self.checksums(); self.rejected()

    def test_missing_runtime_resource_is_rejected(self):
        self.write_zip(self.portable, {k:v for k,v in self.payload.items() if k != 'WebView2Loader.dll'})
        self.checksums(); self.rejected()

    def test_extra_portable_runtime_file_is_rejected(self):
        self.write_zip(self.portable, {**self.payload, 'extra.dll': b'not-packaged'})
        self.checksums(); self.rejected()

    def test_empty_checksum_manifest_is_rejected(self):
        (self.package / 'SHA256SUMS.txt').write_text('')
        self.rejected()

    def test_unlisted_archive_is_rejected(self):
        self.checksums(omit=('app-portable.zip',)); self.rejected()

    def test_unlisted_provenance_is_rejected(self):
        (self.package / 'provenance.json').write_text('{}')
        self.rejected()

    def test_duplicate_checksum_entry_is_rejected(self):
        path = self.package / 'SHA256SUMS.txt'
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + '\n')
        self.rejected()

    def test_tampered_checksum_is_rejected(self):
        path = self.package / 'SHA256SUMS.txt'
        path.write_text('0' * 64 + path.read_text()[64:])
        self.rejected()

    def test_rejects_checksum_path_escape(self):
        path = self.package / 'SHA256SUMS.txt'
        path.write_text('0' * 64 + '  ../app.msix\n')
        self.rejected()

    def test_rejects_duplicate_zip_entries(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(self.portable, 'a') as z: z.writestr('Assets/StoreLogo.png', b'PNG')
        self.checksums(); self.rejected()

    def test_rejects_windows_case_aliases(self):
        with zipfile.ZipFile(self.portable, 'a') as z: z.writestr('opengeul.EXE', self.payload['OpenGeul.exe'])
        self.checksums(); self.rejected()

    def test_rejects_slash_aliases_in_msix(self):
        with zipfile.ZipFile(self.msix, 'a') as z: z.writestr('Tools\\rhwp.exe', self.payload['Tools/rhwp.exe'])
        self.checksums(); self.rejected()

    def test_rejects_archive_path_escape_without_partial_output(self):
        with zipfile.ZipFile(self.portable, 'a') as z: z.writestr('../escaped', b'bad')
        self.checksums(); self.rejected()
        self.assertFalse((self.root / 'escaped').exists())

    def test_rejects_ntfs_alternate_stream(self):
        with zipfile.ZipFile(self.portable, 'a') as z: z.writestr('file.txt:stream', b'bad')
        self.checksums(); self.rejected()

    def test_rejects_windows_trailing_dot(self):
        with zipfile.ZipFile(self.portable, 'a') as z: z.writestr('Assets/StoreLogo.png.', b'bad')
        self.checksums(); self.rejected()

    def test_rejects_windows_device_names(self):
        with zipfile.ZipFile(self.portable, 'a') as z: z.writestr('Assets/CON.txt', b'bad')
        self.checksums(); self.rejected()

    def test_rejects_archive_symlink(self):
        item = zipfile.ZipInfo('link'); item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.portable, 'a') as z: z.writestr(item, '../outside')
        self.checksums(); self.rejected()

    def test_rejects_symlinked_package_input(self):
        target = self.root / 'external.zip'; self.portable.rename(target)
        self.portable.symlink_to(target); self.checksums(); self.rejected()

    def test_existing_runtime_is_never_overwritten(self):
        self.output.mkdir(); marker = self.output / 'keep'; marker.write_text('user data')
        with self.assertRaises(ValueError): prepare(self.package, self.output)
        self.assertEqual(marker.read_text(), 'user data')


if __name__ == '__main__': unittest.main()
