"""Store repackaging preserves the validated release's complete runtime."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e')]
from buildkit import DEV_IDENTITY, manifest
from store_package import REQUIRED_JOBS, STORE_IDENTITY, authorize_release, verify_repackage


class StorePackageTests(unittest.TestCase):
    def test_successful_release_requires_every_source_gate(self):
        sha = 'a' * 40
        provenance = {'version': '1.1.1', 'repository': 'ATLKR/OpenGeul', 'commit': sha, 'runId': '123'}
        run = {'id': 123, 'run_number': 29, 'run_attempt': 1, 'head_sha': sha,
               'repository': {'full_name': 'ATLKR/OpenGeul'}, 'path': '.github/workflows/msix.yml',
               'event': 'push', 'status': 'completed', 'conclusion': 'success'}
        jobs = [{'name': name, 'conclusion': 'success'} for name in sorted(REQUIRED_JOBS)]
        authorize_release('v1.1.1-dev.29.1', provenance, run, sha, jobs)
        jobs[0]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'gates did not all succeed'):
            authorize_release('v1.1.1-dev.29.1', provenance, run, sha, jobs)
        with self.assertRaisesRegex(ValueError, 'successful owned source run'):
            authorize_release('v1.1.1-dev.29.1', provenance, run, 'b' * 40, jobs)

    def test_only_identity_changes_and_dll_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, store = root / 'source.msix', root / 'store.msix'
            pe = bytearray(256)
            pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
            pe[128:132] = b'PE\0\0'; pe[132:134] = (0x8664).to_bytes(2, 'little')
            runtime = {'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                       'WebView2Loader.dll': b'original loader', 'Notices/OpenGeul-LICENSE.txt': b'MIT',
                       'AppxBlockMap.xml': b'<BlockMap/>', '[Content_Types].xml': b'<Types/>'}
            with zipfile.ZipFile(source, 'w') as archive:
                for name, value in runtime.items(): archive.writestr(name, value)
                archive.writestr('AppxManifest.xml', manifest(DEV_IDENTITY, '1.1.1'))

            def write_store(files, identity=STORE_IDENTITY):
                with zipfile.ZipFile(store, 'w') as archive:
                    for name, value in files.items(): archive.writestr(name, value)
                    archive.writestr('AppxManifest.xml', manifest(identity, '1.1.1'))

            write_store(runtime)
            verified = verify_repackage(source, store, '1.1.1')
            self.assertEqual(verified['WebView2Loader.dll'], hashlib.sha256(b'original loader').hexdigest())
            self.assertNotIn('AppxManifest.xml', verified)
            write_store({**runtime, 'WebView2Loader.dll': b'different loader'})
            with self.assertRaisesRegex(ValueError, 'Runtime bytes changed'):
                verify_repackage(source, store, '1.1.1')
            write_store(runtime, DEV_IDENTITY)
            with self.assertRaisesRegex(ValueError, 'Store manifest'):
                verify_repackage(source, store, '1.1.1')
            write_store({name: value for name, value in runtime.items() if name != 'WebView2Loader.dll'})
            with self.assertRaisesRegex(ValueError, 'Runtime file set changed'):
                verify_repackage(source, store, '1.1.1')


if __name__ == '__main__': unittest.main()
