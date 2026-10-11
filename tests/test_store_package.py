"""Store repackaging preserves the validated release's complete runtime."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e')]
from buildkit import DEV_IDENTITY, manifest
from store_package import STORE_IDENTITY, authorize_release, verify_repackage
import store_package

PRODUCT_VERSION = json.loads((ROOT / 'config/product.json').read_text())['version']


class StorePackageTests(unittest.TestCase):
    def source_run(self, status='completed', conclusion='success'):
        return {'id': 123, 'run_number': 29, 'run_attempt': 1, 'head_sha': 'a' * 40,
                'repository': {'full_name': 'ATLKR/OpenGeul'}, 'path': '.github/workflows/msix.yml',
                'event': 'push', 'status': status, 'conclusion': conclusion}

    def source_jobs(self):
        return [{'name': name, 'conclusion': 'success'} for name in (
            'preflight', 'wasm', 'windows-editor', 'windows-cli', 'build', 'release', 'msix-install',
            'native-e2e (windows-2022)', 'native-e2e (windows-2025)',
            'virtual-print (windows-2022)', 'virtual-print (windows-2025)',
            'browser-e2e (chromium)', 'browser-e2e (firefox)', 'browser-e2e (webkit)')]

    def release_directory(self, root, timestamp=None):
        root.mkdir()
        pe = bytearray(256)
        pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
        pe[128:132] = b'PE\0\0'; pe[132:134] = (0x8664).to_bytes(2, 'little')
        files = {'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                 'Notices/OpenGeul-LICENSE.txt': b'MIT',
                 'AppxManifest.xml': manifest(DEV_IDENTITY, PRODUCT_VERSION).encode()}
        msix = root / f'OpenGeul_{PRODUCT_VERSION}.0_x64_unsigned.msix'
        with zipfile.ZipFile(msix, 'w') as archive:
            for name, value in files.items():
                archive.writestr(zipfile.ZipInfo(name, timestamp) if timestamp else name, value)
            archive.writestr('AppxBlockMap.xml', b'<BlockMap/>')
            archive.writestr('[Content_Types].xml', b'<Types/>')
        with zipfile.ZipFile(root / f'OpenGeul_{PRODUCT_VERSION}_x64_portable.zip', 'w') as archive:
            for name, value in files.items(): archive.writestr(name, value)
        provenance = {'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40,
                      'runId': '123', 'package': msix.name,
                      'sha256': hashlib.sha256(msix.read_bytes()).hexdigest()}
        (root / 'provenance.json').write_text(json.dumps(provenance) + '\n')
        (root / 'SHA256SUMS.txt').write_text(''.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in sorted(root.iterdir())))
        return root

    def release_environment(self):
        return {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_EVENT_NAME': 'push',
                'GITHUB_REF': f'refs/tags/v{PRODUCT_VERSION}', 'GITHUB_SHA': 'a' * 40,
                'GITHUB_RUN_ID': '123', 'GITHUB_RUN_NUMBER': '29', 'GITHUB_RUN_ATTEMPT': '1'}

    def test_source_completion_wait_preserves_success_authorization(self):
        self.assertTrue(callable(getattr(store_package, 'wait_for_source_run', None)),
                        'The dispatched child must wait for source completion')
        responses = [self.source_run('in_progress', None), self.source_run()]
        with patch.object(store_package, 'github', side_effect=responses), \
                patch.object(store_package.time, 'monotonic', return_value=0), \
                patch.object(store_package.time, 'sleep'):
            run = store_package.wait_for_source_run('123')
        self.assertEqual((run['id'], run['status'], run['conclusion']), (123, 'completed', 'success'))

    def test_source_failure_unknown_identity_and_timeout_fail_closed(self):
        self.assertTrue(callable(getattr(store_package, 'wait_for_source_run', None)))
        for run in (self.source_run(conclusion='failure'), self.source_run('unexpected', None),
                    {**self.source_run('in_progress', None), 'id': 456}):
            with self.subTest(run=run), patch.object(store_package, 'github', return_value=run):
                with self.assertRaises(ValueError): store_package.wait_for_source_run('123')
        with patch.object(store_package, 'github', return_value=self.source_run('in_progress', None)), \
                patch.object(store_package.time, 'monotonic', side_effect=[0, 301]):
            with self.assertRaisesRegex(ValueError, 'completion'):
                store_package.wait_for_source_run('123', timeout=300)

    def test_matching_release_is_reused_and_changed_assets_are_never_overwritten(self):
        self.assertTrue(callable(getattr(store_package, 'ensure_source_release', None)),
                        'Release retries must verify existing bytes instead of overwriting them')
        with tempfile.TemporaryDirectory() as temporary:
            local = self.release_directory(Path(temporary) / 'local')
            remote = Path(temporary) / 'remote'
            shutil.copytree(local, remote)
            release = {'id': 8, 'tag_name': f'v{PRODUCT_VERSION}', 'draft': False,
                       'assets': [{'name': path.name, 'size': path.stat().st_size, 'state': 'uploaded'}
                                  for path in sorted(local.iterdir())]}
            commands = []

            def gh_download(command, **kwargs):
                commands.append(command)
                self.assertEqual(command[:3], ['gh', 'release', 'download'])
                destination = Path(command[command.index('--dir') + 1])
                for path in remote.iterdir(): shutil.copy2(path, destination / path.name)
                return subprocess.CompletedProcess(command, 0)

            def github(path, **kwargs):
                if path == 'releases?per_page=100': return [[release]]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected remote lookup: ' + path)

            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package.subprocess, 'run', side_effect=gh_download):
                self.assertFalse(store_package.ensure_source_release(f'v{PRODUCT_VERSION}', local))
                (remote / 'provenance.json').write_text('changed source')
                with self.assertRaises(ValueError):
                    store_package.ensure_source_release(f'v{PRODUCT_VERSION}', local)
                other_run = json.loads((local / 'provenance.json').read_text())
                other_run['runId'] = '456'
                (remote / 'provenance.json').write_text(json.dumps(other_run) + '\n')
                (remote / 'SHA256SUMS.txt').write_text(''.join(
                    hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
                    for path in sorted(remote.iterdir()) if path.name != 'SHA256SUMS.txt'))
                with self.assertRaisesRegex(ValueError, 'authorized build'):
                    store_package.ensure_source_release(f'v{PRODUCT_VERSION}', local)
            self.assertEqual(json.loads((remote / 'provenance.json').read_text())['runId'], '456')
            self.assertEqual(len(commands), 3)

    def test_new_release_requires_local_hash_and_owned_source_then_creates_once(self):
        self.assertTrue(callable(getattr(store_package, 'ensure_source_release', None)))
        with tempfile.TemporaryDirectory() as temporary:
            local = self.release_directory(Path(temporary) / 'local')
            commands = []

            def github(path, **kwargs):
                if path == 'releases?per_page=100': return [[]]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected remote lookup: ' + path)

            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package.subprocess, 'run',
                                 side_effect=lambda command, **kwargs: commands.append(command)):
                self.assertTrue(store_package.ensure_source_release(f'v{PRODUCT_VERSION}', local))
                self.assertEqual(commands[0][:4], ['gh', 'release', 'create', f'v{PRODUCT_VERSION}'])
                (local / 'provenance.json').write_text('tampered')
                with self.assertRaises(ValueError): store_package.ensure_source_release(f'v{PRODUCT_VERSION}', local)
            self.assertEqual(len(commands), 1)

    def test_release_retry_reuses_valid_original_assets_instead_of_fresh_archive_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = self.release_directory(Path(temporary) / 'local', (2026, 10, 12, 0, 0, 0))
            remote = self.release_directory(Path(temporary) / 'remote', (2026, 10, 11, 0, 0, 0))
            self.assertNotEqual((local / 'provenance.json').read_bytes(), (remote / 'provenance.json').read_bytes())
            release = {'id': 8, 'tag_name': f'v{PRODUCT_VERSION}', 'draft': False,
                       'assets': [{'name': path.name, 'size': path.stat().st_size, 'state': 'uploaded'}
                                  for path in sorted(remote.iterdir())]}

            def github(path, **kwargs):
                if path == 'releases?per_page=100': return [[release]]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected remote lookup: ' + path)

            def download(command, **kwargs):
                self.assertEqual(command[:3], ['gh', 'release', 'download'])
                destination = Path(command[command.index('--dir') + 1])
                for path in remote.iterdir(): shutil.copy2(path, destination / path.name)

            before = {path.name: path.read_bytes() for path in remote.iterdir()}
            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package.subprocess, 'run', side_effect=download):
                try:
                    created = store_package.ensure_source_release(f'v{PRODUCT_VERSION}', local)
                except ValueError as error:
                    self.fail(f'Valid original release must survive archive timestamp changes: {error}')
                self.assertFalse(created)
            self.assertEqual({path.name: path.read_bytes() for path in remote.iterdir()}, before)

    def test_store_dispatch_only_accepts_owned_explicit_stable_tag_push(self):
        self.assertTrue(callable(getattr(store_package, 'dispatch_store', None)))
        commands = []
        with patch.dict(os.environ, self.release_environment(), clear=True), \
                patch.object(store_package.subprocess, 'run',
                             side_effect=lambda command, **kwargs: commands.append(command)):
            store_package.dispatch_store(f'v{PRODUCT_VERSION}')
            for env, tag in (({'GITHUB_EVENT_NAME': 'workflow_dispatch'}, f'v{PRODUCT_VERSION}'),
                             ({'GITHUB_REF': 'refs/heads/main'}, f'v{PRODUCT_VERSION}'),
                             ({'GITHUB_REPOSITORY': 'other/OpenGeul'}, f'v{PRODUCT_VERSION}'),
                             ({'GITHUB_REF': f'refs/tags/v{PRODUCT_VERSION}-dev.29.1'}, f'v{PRODUCT_VERSION}-dev.29.1'),
                             ({'GITHUB_REF': 'refs/tags/v1.01.2'}, 'v1.01.2')):
                with self.subTest(env=env), patch.dict(os.environ, env):
                    with self.assertRaises(ValueError): store_package.dispatch_store(tag)
        self.assertEqual(commands, [['gh', 'workflow', 'run', 'store-package.yml', '--repo', 'ATLKR/OpenGeul',
                                     '--ref', 'main', '-f', f'release_tag=v{PRODUCT_VERSION}', '-f', 'submit_to_store=true']])

    def test_successful_release_requires_every_source_gate(self):
        sha = 'a' * 40
        provenance = {'version': '1.1.1', 'repository': 'ATLKR/OpenGeul', 'commit': sha, 'runId': '123'}
        run = {'id': 123, 'run_number': 29, 'run_attempt': 1, 'head_sha': sha,
               'repository': {'full_name': 'ATLKR/OpenGeul'}, 'path': '.github/workflows/msix.yml',
               'event': 'push', 'status': 'completed', 'conclusion': 'success'}
        jobs = self.source_jobs()
        authorize_release('v1.1.1-dev.29.1', provenance, run, sha, jobs)
        jobs[0]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'gates did not all succeed'):
            authorize_release('v1.1.1-dev.29.1', provenance, run, sha, jobs)
        with self.assertRaisesRegex(ValueError, 'successful owned source run'):
            authorize_release('v1.1.1-dev.29.1', provenance, run, 'b' * 40, jobs)

    def test_parallel_windows_producers_must_both_succeed(self):
        sha = 'a' * 40
        provenance = {'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul', 'commit': sha, 'runId': '123'}
        for producer in ('windows-editor', 'windows-cli'):
            for conclusion in (None, 'failure', 'cancelled', 'skipped'):
                with self.subTest(producer=producer, conclusion=conclusion):
                    jobs = [job for job in self.source_jobs() if job['name'] != producer]
                    if conclusion is not None:
                        jobs.append({'name': producer, 'conclusion': conclusion})
                    with self.assertRaisesRegex(ValueError, 'gates did not all succeed'):
                        authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), sha, jobs)

    def test_rejected_windows_producer_cannot_prepare_or_repackage_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            published = self.release_directory(root / 'published')
            source = root / '.work/store-source'
            payload = root / '.work/store-payload'
            output = root / 'store-output'
            jobs = self.source_jobs()
            next(job for job in jobs if job['name'] == 'windows-cli')['conclusion'] = 'failure'

            def github(path, **kwargs):
                if path == f'releases/tags/v{PRODUCT_VERSION}':
                    return {'tag_name': f'v{PRODUCT_VERSION}', 'draft': False,
                            'assets': [{'name': path.name, 'size': path.stat().st_size}
                                       for path in published.iterdir()]}
                if path == 'actions/runs/123/jobs?per_page=100': return [{'jobs': jobs}]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected remote lookup: ' + path)

            def download(command, **kwargs):
                self.assertEqual(command[:3], ['gh', 'release', 'download'])
                shutil.copytree(published, source)

            with patch.object(store_package, 'os', SimpleNamespace(name='nt')), \
                    patch.object(store_package, 'Path', side_effect=lambda value: root / value), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package, 'wait_for_source_run', return_value=self.source_run()), \
                    patch.object(store_package.subprocess, 'run', side_effect=download), \
                    patch.object(store_package, 'prepare', side_effect=AssertionError(
                        'Payload preparation reached before Windows producer gates succeeded')) as prepare:
                with self.assertRaisesRegex(ValueError, 'gates did not all succeed'):
                    store_package.build(f'v{PRODUCT_VERSION}', root / 'MakeAppx.exe', output)
                prepare.assert_not_called()
            self.assertFalse(payload.exists())
            self.assertFalse(output.exists())

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
