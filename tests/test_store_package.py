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
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e'), str(ROOT / 'tests')]
from test_mcp_qualification import installed_proof
from buildkit import DEV_IDENTITY, manifest
from windows_arch import component_artifact_name, machine_for
from wack_result import inspect as inspect_wack
from store_package import STORE_IDENTITY, authorize_release, verify_repackage
import store_package

PRODUCT_VERSION = json.loads((ROOT / 'config/product.json').read_text())['version']


class StorePackageTests(unittest.TestCase):
    def source_run(self, status='completed', conclusion='success'):
        return {'id': 123, 'run_number': 29, 'run_attempt': 1, 'head_sha': 'a' * 40,
                'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False},
                'head_repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}, 'path': '.github/workflows/msix.yml',
                'event': 'push', 'status': status, 'conclusion': conclusion}

    def source_jobs(self):
        return [{'name': name, 'conclusion': 'success'} for name in (
            'preflight', 'wasm', 'windows-editor', 'windows-cli', 'build', 'release', 'msix-install',
            'native-e2e (windows-2022)', 'native-e2e (windows-2025)',
            'virtual-print (windows-2022)', 'virtual-print (windows-2025)',
            'browser-e2e (chromium)', 'browser-e2e (firefox)', 'browser-e2e (webkit)')]

    def dual_source_jobs(self):
        jobs = self.source_jobs() + [{'name': name, 'conclusion': 'success'} for name in (
            'windows-editor-arm64', 'windows-cli-arm64', 'build-arm64', 'msix-install-arm64', 'msix-native-arm64',
            'native-e2e (windows-11-arm)', 'virtual-print (windows-11-arm)')]
        return [{**job, 'status': 'completed', 'run_id': 123, 'run_attempt': 1, 'head_sha': 'a' * 40} for job in jobs]

    def release_directory(self, root, timestamp=None, architecture='x64'):
        root.mkdir()
        pe = bytearray(256)
        pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
        pe[128:132] = b'PE\0\0'; pe[132:134] = machine_for(architecture).to_bytes(2, 'little')
        files = {'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                 'Notices/OpenGeul-LICENSE.txt': b'MIT',
                 'AppxManifest.xml': manifest(DEV_IDENTITY, PRODUCT_VERSION, architecture).encode()}
        msix = root / f'OpenGeul_{PRODUCT_VERSION}.0_{architecture}_unsigned.msix'
        with zipfile.ZipFile(msix, 'w') as archive:
            for name, value in files.items():
                archive.writestr(zipfile.ZipInfo(name, timestamp) if timestamp else name, value)
            archive.writestr('AppxBlockMap.xml', b'<BlockMap/>')
            archive.writestr('[Content_Types].xml', b'<Types/>')
        with zipfile.ZipFile(root / f'OpenGeul_{PRODUCT_VERSION}_{architecture}_portable.zip', 'w') as archive:
            for name, value in files.items(): archive.writestr(name, value)
        provenance = {'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40,
                      'runId': '123', 'package': msix.name,
                      'sha256': hashlib.sha256(msix.read_bytes()).hexdigest()}
        (root / 'provenance.json').write_text(json.dumps(provenance) + '\n')
        (root / 'SHA256SUMS.txt').write_text(''.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in sorted(root.iterdir())))
        return root

    def checksum_directory(self, root):
        (root / 'SHA256SUMS.txt').write_text(''.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n'
            for path in sorted(root.iterdir()) if path.name != 'SHA256SUMS.txt'))

    def dual_release_directory(self, root):
        import release_pair
        root.mkdir()
        packages, wacks = {}, {}
        for architecture in ('x64', 'arm64'):
            package = self.release_directory(root / architecture, architecture=architecture)
            packages[architecture] = package
            provenance = json.loads((package / 'provenance.json').read_text())
            components = {'formatVersion': 1, 'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40,
                          'runId': '123', 'runAttempt': '1', 'sourceContractSha256': 'b' * 64, 'components': {}}
            with zipfile.ZipFile(package / provenance['package']) as archive:
                for role, name in (('editor', 'OpenGeul.exe'), ('cli', 'Tools/rhwp.exe')):
                    raw = archive.read(name)
                    components['components'][role] = {
                        'artifactName': component_artifact_name(role, '123', architecture), 'runAttempt': '1',
                        'provenanceSha256': ('c' if role == 'editor' else 'd') * 64,
                        'runtime': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                (package / 'AppxManifest.xml').write_bytes(archive.read('AppxManifest.xml'))
            (package / 'rhwp-help.txt').write_text('rhwp help\n')
            provenance.update(unsigned=True, architecture=architecture, members=6,
                              upstream=json.loads((ROOT / 'config/upstream.lock.json').read_text()),
                              sourceParity={'version': PRODUCT_VERSION, 'source': 'OpenGeul distribution overlays'},
                              manualWindowsUx='not-verified', storeCertified=False, windowsComponents=components)
            (package / 'provenance.json').write_text(json.dumps(provenance) + '\n')
            self.checksum_directory(package)
            wack = root / ('wack-' + architecture); wack.mkdir(); wacks[architecture] = wack
            signed = ('e' if architecture == 'x64' else 'f') * 64
            (wack / 'install.json').write_text(json.dumps({
                'success': True, 'originalSha256': provenance['sha256'].upper(),
                'signedTestPackageSha256': signed.upper(), 'publisher': DEV_IDENTITY['publisher'],
                'packageFullName': f"{DEV_IDENTITY['name']}_{PRODUCT_VERSION}.0_{architecture}__9za217j1njc2t",
                'mcp': installed_proof(architecture,components['components']['cli']['sha256'],
                    f"{DEV_IDENTITY['name']}_{PRODUCT_VERSION}.0_{architecture}__9za217j1njc2t",
                    'a' * 40, '123', '1', components['components']['cli']['size'])}) + '\n')
            (wack / 'wack-context.json').write_text(json.dumps({
                'invocationMode': 'documented-appxpackagepath', 'inputPackageSha256': signed.upper(),
                'runnerSessionId': 1, 'wackSessionId': 1}) + '\n')
            (wack / 'wack.xml').write_text(f'''<REPORT OVERALL_RESULT="PASS" PARTIAL_RUN="FALSE" APP_NAME="{DEV_IDENTITY['name']}" APP_VERSION="{PRODUCT_VERSION}.0" VALIDATION_TYPE="CommandLine" APP_TYPE="Centennial" VERSION="10.0.26100.8249">
                <APPLICATIONS><Installed_Programs><Program Source="AppxPackage" Name="{DEV_IDENTITY['name']}" Version="{PRODUCT_VERSION}.0"><Indicators><WindowsStoreAppManifestIndicators><PackageManifest><Package><Identity Name="{DEV_IDENTITY['name']}" Publisher="{DEV_IDENTITY['publisher']}" Version="{PRODUCT_VERSION}.0" ProcessorArchitecture="{architecture}"/></Package></PackageManifest></WindowsStoreAppManifestIndicators></Indicators></Program></Installed_Programs></APPLICATIONS>
                <TEST NAME="Required"><RESULT>PASS</RESULT></TEST><TEST NAME="Blocked executables" OPTIONAL="TRUE"><RESULT>PASS</RESULT></TEST></REPORT>''')
            (wack / 'wack.json').write_text(json.dumps(inspect_wack(
                wack / 'wack.xml', DEV_IDENTITY['name'], PRODUCT_VERSION + '.0', 0)) + '\n')
        output = root / 'pair'
        release_pair.assemble(packages['x64'], packages['arm64'], wacks['x64'], wacks['arm64'], output,
                              env={'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_SHA': 'a' * 40,
                                   'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'})
        return output

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
               'repository': {'full_name': 'ATLKR/OpenGeul', 'private': False},
                'head_repository': {'full_name': 'ATLKR/OpenGeul', 'private': False}, 'path': '.github/workflows/msix.yml',
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

    def test_dual_source_requires_every_arm64_gate(self):
        provenance = {'formatVersion': 2, 'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul',
                      'commit': 'a' * 40, 'runId': '123', 'runAttempt': '1'}
        jobs = self.dual_source_jobs()
        authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), 'a' * 40, jobs)
        for required in ('windows-editor-arm64', 'windows-cli-arm64', 'build-arm64', 'msix-install-arm64', 'msix-native-arm64',
                         'native-e2e (windows-11-arm)', 'virtual-print (windows-11-arm)'):
            for conclusion in (None, 'failure', 'cancelled', 'skipped'):
                candidate = [dict(job) for job in jobs if job['name'] != required]
                if conclusion is not None:
                    candidate.append({'name': required, 'conclusion': conclusion, 'run_id': 123,
                                      'run_attempt': 1, 'head_sha': 'a' * 40})
                with self.subTest(required=required, conclusion=conclusion), self.assertRaises(ValueError):
                    authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), 'a' * 40, candidate)

    def test_all21_dual_source_jobs_require_completed_same_head_and_attempt(self):
        provenance = {'formatVersion': 2, 'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul',
                      'commit': 'a' * 40, 'runId': '123', 'runAttempt': '1'}
        self.assertEqual(len(store_package.REQUIRED_JOBS), 21)
        for name in store_package.REQUIRED_JOBS:
            for changes in ({'status':None}, {'status':'in_progress'}, {'status':'queued'},
                            {'conclusion':'failure'}, {'conclusion':'skipped'}, {'conclusion':'cancelled'},
                            {'head_sha':'b'*40}, {'run_attempt':2}, {'run_id':124}):
                jobs=self.dual_source_jobs();next(job for job in jobs if job['name']==name).update(changes)
                with self.subTest(name=name, changes=changes), self.assertRaises(ValueError):
                    authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), 'a'*40, jobs)
            for change in ('missing','duplicate'):
                jobs=self.dual_source_jobs();job=next(job for job in jobs if job['name']==name)
                if change=='missing': jobs.remove(job)
                else: jobs.append(dict(job))
                with self.subTest(name=name, change=change), self.assertRaises(ValueError):
                    authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), 'a'*40, jobs)

    def test_dual_source_api_owner_and_head_must_be_literal_public(self):
        provenance = {'formatVersion': 2, 'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul',
                      'commit': 'a' * 40, 'runId': '123', 'runAttempt': '1'}
        for role in ('repository','head_repository'):
            for change in (None, {}, {'full_name':'fork/OpenGeul','private':False},
                           {'full_name':'ATLKR/OpenGeul','private':True},
                           {'full_name':'ATLKR/OpenGeul','private':'false'},
                           {'full_name':'ATLKR/OpenGeul','private':0}):
                run=self.source_run();run[role]=change
                with self.subTest(role=role, change=change), self.assertRaises(ValueError):
                    authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, run, 'a'*40, self.dual_source_jobs())

    def test_dual_source_rejects_other_attempt_duplicate_or_foreign_gate_evidence(self):
        provenance = {'formatVersion': 2, 'version': PRODUCT_VERSION, 'repository': 'ATLKR/OpenGeul',
                      'commit': 'a' * 40, 'runId': '123', 'runAttempt': '1'}
        for attempt in (None, True, 1, '01', '0', '2'):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', {**provenance, 'runAttempt': attempt},
                                  self.source_run(), 'a' * 40, self.dual_source_jobs())
        for changes in ({'run_attempt': 2}, {'run_id': 456}, {'head_sha': 'b' * 40}):
            jobs = self.dual_source_jobs(); jobs[-1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), 'a' * 40, jobs)
        jobs = self.dual_source_jobs(); jobs.append(dict(jobs[-1]))
        with self.assertRaises(ValueError):
            authorize_release(f'v{PRODUCT_VERSION}-dev.29.1', provenance, self.source_run(), 'a' * 40, jobs)

    def test_pair_source_publication_preserves_exact_twenty_two_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.dual_release_directory(Path(temporary) / 'assembled')
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            commands = []
            def github(path, **kwargs):
                if path == 'releases?per_page=100': return [[]]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected lookup: ' + path)
            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package.subprocess, 'run', side_effect=lambda command, **kwargs: commands.append(command)):
                self.assertTrue(store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source))
            self.assertEqual(len(before), 22)
            self.assertEqual(commands[0][:4], ['gh', 'release', 'create', f'v{PRODUCT_VERSION}'])
            self.assertEqual(set(commands[0][4:26]), {str(source / name) for name in before})
            self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, before)

    def test_unknown_source_format_cannot_fall_back_to_historical_x64_publication(self):
        for format_version in (1, 3, True, '2', None):
            with tempfile.TemporaryDirectory() as temporary:
                source = self.release_directory(Path(temporary) / 'source')
                provenance = json.loads((source / 'provenance.json').read_text()); provenance['formatVersion'] = format_version
                (source / 'provenance.json').write_text(json.dumps(provenance) + '\n'); self.checksum_directory(source)
                with self.subTest(format_version=format_version), patch.dict(os.environ, self.release_environment(), clear=True), \
                        patch.object(store_package, 'github') as github, patch.object(store_package.subprocess, 'run') as command:
                    with self.assertRaises(ValueError): store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source)
                    github.assert_not_called(); command.assert_not_called()

    def test_pair_source_publication_rejects_foreign_environment_before_any_github_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.dual_release_directory(Path(temporary) / 'assembled')
            for changes in ({'GITHUB_SHA': 'e' * 40}, {'GITHUB_RUN_ID': '456'}, {'GITHUB_RUN_ATTEMPT': '2'}):
                with self.subTest(changes=changes), patch.dict(os.environ, {**self.release_environment(), **changes}, clear=True), \
                        patch.object(store_package, 'github') as github, patch.object(store_package.subprocess, 'run') as command:
                    with self.assertRaises(ValueError): store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source)
                    github.assert_not_called(); command.assert_not_called()

    def test_pair_source_publication_revalidates_raw_wack_after_outer_checksums_are_recomputed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.dual_release_directory(Path(temporary) / 'assembled')
            raw = source / 'wack-arm64.xml'
            raw.write_text(raw.read_text().replace('PARTIAL_RUN="FALSE"', 'PARTIAL_RUN="TRUE"'))
            self.checksum_directory(source)
            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github') as github, patch.object(store_package.subprocess, 'run') as command:
                with self.assertRaises(ValueError): store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source)
                github.assert_not_called(); command.assert_not_called()

    def test_existing_pair_release_is_preserved_and_tampered_wack_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = self.dual_release_directory(root / 'assembled')
            remote = root / 'remote'; shutil.copytree(source, remote)
            release = {'id': 8, 'tag_name': f'v{PRODUCT_VERSION}', 'draft': False,
                       'assets': [{'name': path.name, 'size': path.stat().st_size, 'state': 'uploaded'}
                                  for path in sorted(remote.iterdir())]}
            commands = []
            def github(path, **kwargs):
                if path == 'releases?per_page=100': return [[release]]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected lookup: ' + path)
            def download(command, **kwargs):
                commands.append(command); self.assertEqual(command[:3], ['gh', 'release', 'download'])
                destination = Path(command[command.index('--dir') + 1])
                for path in remote.iterdir(): shutil.copy2(path, destination / path.name)
            before = {path.name: path.read_bytes() for path in remote.iterdir()}
            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package.subprocess, 'run', side_effect=download):
                self.assertFalse(store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source))
                self.assertEqual({path.name: path.read_bytes() for path in remote.iterdir()}, before)
                raw = remote / 'wack-x64.xml'; raw.write_text(raw.read_text().replace('OVERALL_RESULT="PASS"', 'OVERALL_RESULT="WARNING"'))
                self.checksum_directory(remote)
                with self.assertRaises(ValueError): store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source)
            self.assertIn('OVERALL_RESULT="WARNING"', (remote / 'wack-x64.xml').read_text())
            self.assertEqual(len(commands), 2)

    def test_existing_self_consistent_pair_must_match_current_validated_twenty_two_bytes(self):
        import release_pair
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = self.dual_release_directory(root / 'assembled')
            remote = root / 'remote'; shutil.copytree(source, remote)
            help_path = remote / 'rhwp-help-arm64.txt'; previous = hashlib.sha256(help_path.read_bytes()).hexdigest()
            help_path.write_text('rhwp help from another valid snapshot\n')
            checksums = remote / 'SHA256SUMS-arm64.txt'
            checksums.write_text(checksums.read_text().replace(previous + '  rhwp-help.txt',
                                 hashlib.sha256(help_path.read_bytes()).hexdigest() + '  rhwp-help.txt'))
            self.checksum_directory(remote)
            self.assertEqual(release_pair.verify_pair(remote), release_pair.verify_pair(source))
            self.assertNotEqual(release_pair.source_fingerprint(remote), release_pair.source_fingerprint(source))
            release = {'id': 8, 'tag_name': f'v{PRODUCT_VERSION}', 'draft': False,
                       'assets': [{'name': path.name, 'size': path.stat().st_size, 'state': 'uploaded'}
                                  for path in sorted(remote.iterdir())]}
            commands = []
            def github(path, **kwargs):
                if path == 'releases?per_page=100': return [[release]]
                if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
                self.fail('Unexpected lookup: ' + path)
            def download(command, **kwargs):
                commands.append(command); self.assertEqual(command[:3], ['gh', 'release', 'download'])
                destination = Path(command[command.index('--dir') + 1])
                for path in remote.iterdir(): shutil.copy2(path, destination / path.name)
            before = {path.name: path.read_bytes() for path in remote.iterdir()}
            with patch.dict(os.environ, self.release_environment(), clear=True), \
                    patch.object(store_package, 'github', side_effect=github), \
                    patch.object(store_package.subprocess, 'run', side_effect=download):
                with self.assertRaisesRegex(ValueError, 'bytes'):
                    store_package.ensure_source_release(f'v{PRODUCT_VERSION}', source)
            self.assertEqual(len(commands), 1)
            self.assertEqual({path.name: path.read_bytes() for path in remote.iterdir()}, before)

    def invoke_pair_build(self, root, published, output, *, failed_makeappx_architecture=None, jobs=None):
        source = root / '.work/store-source'
        commands = []
        def github(path, **kwargs):
            if path == f'releases/tags/v{PRODUCT_VERSION}':
                return {'id': 8, 'html_url': f'https://github.com/ATLKR/OpenGeul/releases/tag/v{PRODUCT_VERSION}',
                        'tag_name': f'v{PRODUCT_VERSION}', 'draft': False,
                        'assets': [{'name': path.name, 'size': path.stat().st_size} for path in published.iterdir()]}
            if path == 'actions/runs/123/jobs?per_page=100': return [{'jobs': jobs or self.dual_source_jobs()}]
            if path == f'commits/v{PRODUCT_VERSION}': return {'sha': 'a' * 40}
            self.fail('Unexpected lookup: ' + path)
        def command(command, **kwargs):
            commands.append(command)
            if command[:3] == ['gh', 'release', 'download']:
                shutil.copytree(published, source); return
            self.assertEqual(command[1:3], ['pack', '/d'])
            payload = Path(command[3]); destination = Path(command[command.index('/p') + 1])
            if failed_makeappx_architecture and f'_{failed_makeappx_architecture}_' in destination.name:
                raise subprocess.CalledProcessError(1, command)
            with zipfile.ZipFile(destination, 'w') as archive:
                for path in sorted(payload.rglob('*')):
                    if path.is_file(): archive.write(path, path.relative_to(payload).as_posix())
                archive.writestr('AppxBlockMap.xml', b'<BlockMap/>'); archive.writestr('[Content_Types].xml', b'<Types/>')
        with patch.object(store_package, 'os', SimpleNamespace(name='nt', getenv=os.getenv)), \
                patch.object(store_package, 'Path', side_effect=lambda value: root / value), \
                patch.object(store_package, 'github', side_effect=github), \
                patch.object(store_package, 'wait_for_source_run', return_value=self.source_run()), \
                patch.object(store_package.subprocess, 'run', side_effect=command):
            store_package.build(f'v{PRODUCT_VERSION}', root / 'MakeAppx.exe', output)
        return commands

    def invoke_source_download(self, root, published, output, tag, *, jobs=None, run=None, tag_sha='a' * 40):
        commands = []
        def github(path, **kwargs):
            if path == f'releases/tags/{tag}':
                return {'id': 8, 'html_url': f'https://github.com/ATLKR/OpenGeul/releases/tag/{tag}',
                        'tag_name': tag, 'draft': False, 'assets': [
                            {'name': path.name, 'size': path.stat().st_size} for path in published.iterdir()]}
            if path == 'actions/runs/123/jobs?per_page=100': return [{'jobs': jobs or self.dual_source_jobs()}]
            if path == f'commits/{tag}': return {'sha': tag_sha}
            self.fail('Unexpected read-only lookup: ' + path)
        def download(command, **kwargs):
            commands.append(command); self.assertEqual(command[:3], ['gh', 'release', 'download'])
            shutil.copytree(published, Path(command[command.index('--dir') + 1]), dirs_exist_ok=True)
        with patch.object(store_package, 'github', side_effect=github), \
                patch.object(store_package, 'wait_for_source_run', return_value=run or self.source_run()), \
                patch.object(store_package.subprocess, 'run', side_effect=download), \
                patch.object(store_package, 'ensure_source_release', side_effect=AssertionError('Read-only mode reached a publisher')), \
                patch.object(store_package, 'dispatch_store', side_effect=AssertionError('Read-only mode reached a dispatcher')):
            result = store_package.download_source_release(tag, output)
        return commands, result

    def test_read_only_download_accepts_bound_stable_and_dev_and_preserves_twenty_two_bytes(self):
        import release_pair
        for tag in (f'v{PRODUCT_VERSION}', f'v{PRODUCT_VERSION}-dev.29.1'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); published = self.dual_release_directory(root / 'assembled'); output = root / 'source-output'
                before = {path.name: path.read_bytes() for path in published.iterdir()}
                commands, result = self.invoke_source_download(root, published, output, tag)
                self.assertEqual(len(commands), 1)
                self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)
                self.assertEqual({path.name: path.read_bytes() for path in published.iterdir()}, before)
                self.assertEqual(result['sourceAssetFingerprintSha256'], release_pair.source_fingerprint(output))
                self.assertEqual((result['sourceReleaseId'], result['sourceCommit'], result['sourceRunId'], result['sourceRunAttempt']),
                                 (8, 'a' * 40, '123', '1'))
                self.assertFalse(result['storeWritesPerformed'])

    def test_read_only_download_rejects_unsupported_or_wrong_run_tag_without_publication(self):
        for tag in ('latest', 'refs/tags/v1.1.3', 'v1.01.3', 'v1.1.3-dev.29.2', 'v1.1.3-dev.30.1'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); published = self.dual_release_directory(root / 'assembled'); output = root / 'source-output'
                with self.subTest(tag=tag), self.assertRaises(ValueError):
                    self.invoke_source_download(root, published, output, tag)
                self.assertFalse(output.exists())

    def test_read_only_download_requires_dual_and_raw_full_wack_after_recomputed_checksums(self):
        for case in ('legacy', 'raw-wack'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                published = (self.release_directory(root / 'published') if case == 'legacy'
                             else self.dual_release_directory(root / 'assembled'))
                if case == 'raw-wack':
                    report = published / 'wack-arm64.xml'
                    report.write_text(report.read_text().replace('PARTIAL_RUN="FALSE"', 'PARTIAL_RUN="TRUE"'))
                    self.checksum_directory(published)
                output = root / 'source-output'
                with self.subTest(case=case), self.assertRaises(ValueError):
                    self.invoke_source_download(root, published, output, f'v{PRODUCT_VERSION}')
                self.assertFalse(output.exists())
                self.assertEqual(list(root.glob('opengeul-source-read-*')), [])

    def test_read_only_download_requires_owned_whole_source_gates_and_removes_staging_on_failure(self):
        for case in ('failed-arm', 'foreign-attempt', 'failed-run', 'foreign-tag'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); published = self.dual_release_directory(root / 'assembled'); output = root / 'source-output'
                jobs, run, tag_sha = self.dual_source_jobs(), self.source_run(), 'a' * 40
                if case == 'failed-arm': jobs[-1]['conclusion'] = 'failure'
                if case == 'foreign-attempt': jobs[-1]['run_attempt'] = 2
                if case == 'failed-run': run['conclusion'] = 'failure'
                if case == 'foreign-tag': tag_sha = 'f' * 40
                with self.subTest(case=case), self.assertRaises(ValueError):
                    self.invoke_source_download(root, published, output, f'v{PRODUCT_VERSION}', jobs=jobs, run=run, tag_sha=tag_sha)
                self.assertFalse(output.exists())
                self.assertEqual(list(root.glob('opengeul-source-read-*')), [])

    def test_read_only_download_refuses_existing_or_reparse_output_before_get(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / 'existing'; output.mkdir(); (output / 'sentinel').write_text('keep')
            with patch.object(store_package, 'github') as github, self.assertRaises(ValueError):
                store_package.download_source_release(f'v{PRODUCT_VERSION}', output)
            github.assert_not_called(); self.assertEqual((output / 'sentinel').read_text(), 'keep')
            destination = root / 'destination'; destination.mkdir(); link = root / 'link'; link.symlink_to(destination, target_is_directory=True)
            with patch.object(store_package, 'github') as github, self.assertRaises(ValueError):
                store_package.download_source_release(f'v{PRODUCT_VERSION}', link / 'source-output')
            github.assert_not_called()

    def test_read_only_download_cli_is_exclusive_with_publish_and_dispatch(self):
        for other in ('--publish-release', '--dispatch-store'):
            command = [sys.executable, str(ROOT / 'scripts/store_package.py'), '--download-source-release', other,
                       '--release-tag', f'v{PRODUCT_VERSION}', '--output', '.work/store-source']
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('not allowed with argument', result.stderr)

    def test_pair_build_emits_two_verified_store_packages_and_per_architecture_provenance(self):
        import release_pair
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); published = self.dual_release_directory(root / 'assembled')
            before = {path.name: path.read_bytes() for path in published.iterdir()}; output = root / 'store-output'
            with patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ID': '777'}, clear=True):
                commands = self.invoke_pair_build(root, published, output)
            self.assertEqual(sum(command[1:3] == ['pack', '/d'] for command in commands), 2)
            store_package.verify_checksums(output)
            provenance = json.loads((output / 'store-provenance.json').read_text())
            self.assertEqual(provenance['formatVersion'], 2)
            self.assertEqual(set(provenance['architectures']), {'x64', 'arm64'})
            self.assertEqual(provenance['sourceAssetFingerprintSha256'], release_pair.source_fingerprint(published))
            self.assertEqual((provenance['sourceCommit'], provenance['sourceRunId'], provenance['sourceRunAttempt']),
                             ('a' * 40, '123', '1'))
            self.assertEqual((provenance['repackageCommit'], provenance['repackageRunId']), ('b' * 40, '777'))
            self.assertEqual(provenance['identity'], STORE_IDENTITY)
            self.assertIs(provenance['unsigned'], True); self.assertIs(provenance['storeCertified'], False)
            for architecture, details in provenance['architectures'].items():
                expected = f'OpenGeul_{PRODUCT_VERSION}.0_{architecture}_store-unsigned.msix'
                self.assertEqual(details['package'], expected)
                self.assertEqual(details['sha256'], hashlib.sha256((output / expected).read_bytes()).hexdigest())
                original = published / details['sourceMsix']
                self.assertEqual(details['sourceMsixSha256'], hashlib.sha256(original.read_bytes()).hexdigest())
                self.assertEqual(details['runtimeSha256'], verify_repackage(original, output / expected, PRODUCT_VERSION, architecture))
                self.assertEqual((output / details['manifest']).read_bytes(), manifest(STORE_IDENTITY, PRODUCT_VERSION, architecture).encode())
            self.assertEqual((output / 'source-provenance.json').read_bytes(), before['provenance.json'])
            self.assertEqual({path.name: path.read_bytes() for path in published.iterdir()}, before)
            self.assertEqual({path.name: path.read_bytes() for path in (root / '.work/store-source').iterdir()}, before)

    def test_pair_build_second_makeappx_failure_never_publishes_partial_store_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); published = self.dual_release_directory(root / 'assembled'); output = root / 'store-output'
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke_pair_build(root, published, output, failed_makeappx_architecture='arm64')
            self.assertFalse(output.exists())

    def test_pair_store_output_cannot_mutate_source_or_follow_symlink_parent(self):
        for location in ('source', 'symlink'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); published = self.dual_release_directory(root / 'assembled')
                if location == 'source':
                    output = root / '.work/store-source/unexpected-store-output'
                else:
                    destination = root / 'destination'; destination.mkdir()
                    link = root / 'output-link'; link.symlink_to(destination, target_is_directory=True)
                    output = link / 'store-output'
                with self.subTest(location=location):
                    with self.assertRaises(ValueError):
                        self.invoke_pair_build(root, published, output)
                    self.assertFalse(output.exists())

    def test_pair_output_ancestor_windows_reparse_attributes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); published = self.dual_release_directory(root / 'assembled')
            parent = root / 'reparse-output'; parent.mkdir(); output = parent / 'store-output'
            original = Path.lstat
            def lstat(path, *args, **kwargs):
                actual = original(path, *args, **kwargs)
                if path == parent:
                    return SimpleNamespace(st_mode=actual.st_mode, st_file_attributes=0x400)
                return actual
            with patch.object(Path, 'lstat', lstat):
                with self.assertRaisesRegex(ValueError, 'reparse'):
                    self.invoke_pair_build(root, published, output)
            self.assertFalse(output.exists())

    def test_pair_build_failed_arm64_gate_never_stages_runtime_or_creates_store_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); published = self.dual_release_directory(root / 'assembled'); output = root / 'store-output'
            jobs = self.dual_source_jobs(); jobs[-1]['conclusion'] = 'failure'
            with self.assertRaisesRegex(ValueError, 'gates did not all succeed'):
                self.invoke_pair_build(root, published, output, jobs=jobs)
            self.assertFalse((root / '.work/store-payload').exists()); self.assertFalse(output.exists())

    def test_pair_build_asset_bounds_and_duplicates_fail_before_download(self):
        for assets in ([{'name': 'provenance.json', 'size': 192 * 1024 * 1024 + 1}],
                       [{'name': 'provenance.json', 'size': -1}], [{'name': 'provenance.json', 'size': True}],
                       [{'name': 'provenance.json', 'size': 1}] * 2,
                       [{'name': '../provenance.json', 'size': 1}]):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                release = {'id': 8, 'tag_name': f'v{PRODUCT_VERSION}', 'draft': False, 'assets': assets}
                with self.subTest(assets=assets), patch.object(store_package, 'os', SimpleNamespace(name='nt')), \
                        patch.object(store_package, 'Path', side_effect=lambda value: root / value), \
                        patch.object(store_package, 'github', return_value=release), \
                        patch.object(store_package.subprocess, 'run') as command:
                    with self.assertRaises(ValueError):
                        store_package.build(f'v{PRODUCT_VERSION}', root / 'MakeAppx.exe', root / 'store-output')
                    command.assert_not_called()

    def test_arm64_repackage_preserves_runtime_and_rejects_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pe = bytearray(256)
            pe[:2] = b'MZ'; pe[60:64] = (128).to_bytes(4, 'little')
            pe[128:132] = b'PE\0\0'; pe[132:134] = (0xAA64).to_bytes(2, 'little')
            runtime = {'OpenGeul.exe': bytes(pe), 'Tools/rhwp.exe': bytes(pe),
                       'WebView2Loader.dll': bytes(pe) + b'ARM64 loader', 'Notices/OpenGeul-LICENSE.txt': b'MIT',
                       'AppxBlockMap.xml': b'<BlockMap/>', '[Content_Types].xml': b'<Types/>'}
            source, store = root / 'source.msix', root / 'store.msix'
            def write(path, identity, architecture, files):
                with zipfile.ZipFile(path, 'w') as archive:
                    for name, value in files.items(): archive.writestr(name, value)
                    archive.writestr('AppxManifest.xml', manifest(identity, PRODUCT_VERSION, architecture))
            write(source, DEV_IDENTITY, 'arm64', runtime)
            write(store, STORE_IDENTITY, 'arm64', runtime)
            self.assertEqual(verify_repackage(source, store, PRODUCT_VERSION, 'arm64')['WebView2Loader.dll'],
                             hashlib.sha256(runtime['WebView2Loader.dll']).hexdigest())
            with self.assertRaises(ValueError): verify_repackage(source, store, PRODUCT_VERSION, 'x64')
            write(source, DEV_IDENTITY, 'x64', runtime)
            with self.assertRaises(ValueError): verify_repackage(source, store, PRODUCT_VERSION, 'arm64')
            write(source, DEV_IDENTITY, 'arm64', runtime)
            write(store, STORE_IDENTITY, 'arm64', {**runtime, 'WebView2Loader.dll': bytes(pe) + b'changed'})
            with self.assertRaisesRegex(ValueError, 'Runtime bytes changed'):
                verify_repackage(source, store, PRODUCT_VERSION, 'arm64')

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
                       'WebView2Loader.dll': bytes(pe) + b'original loader', 'Notices/OpenGeul-LICENSE.txt': b'MIT',
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
            self.assertEqual(verified['WebView2Loader.dll'], hashlib.sha256(runtime['WebView2Loader.dll']).hexdigest())
            self.assertNotIn('AppxManifest.xml', verified)
            write_store({**runtime, 'WebView2Loader.dll': bytes(pe) + b'different loader'})
            with self.assertRaisesRegex(ValueError, 'Runtime bytes changed'):
                verify_repackage(source, store, '1.1.1')
            write_store(runtime, DEV_IDENTITY)
            with self.assertRaisesRegex(ValueError, 'Store manifest'):
                verify_repackage(source, store, '1.1.1')
            write_store({name: value for name, value in runtime.items() if name != 'WebView2Loader.dll'})
            with self.assertRaisesRegex(ValueError, 'Runtime file set changed'):
                verify_repackage(source, store, '1.1.1')


if __name__ == '__main__': unittest.main()
