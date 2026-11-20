"""Offline language FOD acquisition must preserve real Microsoft bytes."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/korean_fod_source.py'
SPEC = importlib.util.spec_from_file_location('suite_korean_fod_source', SOURCE)
fod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fod)


class Response(io.BytesIO):
    def __init__(self, payload, *, status=206, headers=None):
        super().__init__(payload)
        self.status = status
        self.headers = {'Content-Range': 'bytes 2048-2059/6864345088', 'Content-Length': '12', **(headers or {})}
    def geturl(self): return fod.ISO_URL


class KoreanFodSourceTests(unittest.TestCase):
    def package(self):
        return {'relativePath': 'LanguagesAndOptionalFeatures/fixture.cab',
                'start': 2048, 'bytes': 12, 'sha256': hashlib.sha256(b'cab-fixture!').hexdigest()}

    def acquire(self, package=None, response=None):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            record = fod.download_package(package or self.package(), folder,
                opener=lambda request, timeout: response or Response(b'cab-fixture!'))
            return record, (folder / 'LanguagesAndOptionalFeatures/fixture.cab').read_bytes()

    def test_exact_official_range_bytes_and_digest_produce_inspectable_file(self):
        record, payload = self.acquire()
        self.assertEqual(payload, b'cab-fixture!')
        self.assertEqual(record['sha256'], self.package()['sha256'])
        self.assertEqual(record['bytes'], 12)

    def test_full_iso_response_or_wrong_content_range_is_rejected_before_consumption(self):
        for response in (Response(b'cab-fixture!', status=200),
                         Response(b'cab-fixture!', headers={'Content-Range': 'bytes 0-11/6864345088'}),
                         Response(b'cab-fixture!', headers={'Content-Range': 'bytes 2048-2059/123'}),
                         Response(b'cab-fixture!', headers={'Content-Length': '6864345088'})):
            with self.subTest(headers=response.headers, status=response.status), self.assertRaises(ValueError):
                self.acquire(response=response)

    def test_truncated_extra_or_changed_package_bytes_cannot_be_a_valid_source(self):
        for payload in (b'cab-fixtur', b'cab-fixture!!', b'bad-fixture!'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.acquire(response=Response(payload))

    def test_path_escape_and_out_of_media_range_are_rejected(self):
        for patch in ({'relativePath': '../fixture.cab'}, {'relativePath': '/fixture.cab'},
                      {'start': -1}, {'start': 6864345080}, {'bytes': 0}, {'bytes': 32 * 1024**2 + 1}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.acquire(package={**self.package(), **patch})

    def test_source_never_overwrites_an_existing_cab(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            destination = folder / self.package()['relativePath']
            destination.parent.mkdir()
            destination.write_bytes(b'keep original')
            with self.assertRaises(FileExistsError):
                fod.download_package(self.package(), folder, opener=lambda request, timeout: Response(b'cab-fixture!'))
            self.assertEqual(destination.read_bytes(), b'keep original')

    def test_source_rejects_linked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            other = folder / 'other'
            other.mkdir()
            link = folder / 'LanguagesAndOptionalFeatures'
            if os.name == 'nt':
                # Directory junctions need no developer-mode/symlink privilege.
                subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(other)],
                               check=True, capture_output=True, timeout=10)
                self.assertTrue(link.is_junction())
            else:
                link.symlink_to(other, target_is_directory=True)
                self.assertTrue(link.is_symlink())
            with self.assertRaises(ValueError):
                fod.download_package(self.package(), folder, opener=lambda request, timeout: Response(b'cab-fixture!'))
            self.assertEqual(list(other.iterdir()), [])


if __name__ == '__main__': unittest.main()
