"""Locked diagnostic artifacts authenticate before any inner digest is trusted."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from suite.tests import test_fetch_source_engine as fetch


SCRIPT = fetch.ROOT / 'suite/scripts/fetch-calc-dispatch.ps1'
ENGINE = 'OpenGeul-Office-engine-arm64-calc-dispatch.zip'
RECEIPT = 'calc-dispatch-source-build-receipt.json'
CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
REPOSITORY_ID = 1405493151


@unittest.skipUnless(fetch.PWSH, 'PowerShell runtime unavailable')
class CalcDispatchFetchTests(unittest.TestCase):
    def fixture(self, root):
        fixture = fetch.FetchSourceEngineTests()
        _, artifact, run, scenario, _, _ = fixture.fixture(root)
        marker = dict(schemaVersion=1, kind='calc-save-dispatch-diagnostic',
                      sourceCommit='a'*40, sourceLockSha256='c'*64, coreCommit=CORE,
                      acceptanceEligible=False, fullEngineQualified=False)
        engine = fetch.zip_bytes([
            ('program/soffice.bin', b'synthetic ARM64 engine', 0),
            ('program/soffice.exe', b'synthetic ARM64 launcher', 0),
            ('program/python.exe', b'synthetic ARM64 Python', 0),
            ('program/opengeul-calc-dispatch-diagnostic.json', json.dumps(marker).encode(), 0)])
        proof = dict(schemaVersion=1, kind='native-office-engine-calc-dispatch-diagnostic',
                     phase='Full', architecture='arm64', stage='complete',
                     status='native-engine-calc-dispatch-diagnostic-built', passed=True,
                     fullEngineQualified=False, acceptanceEligible=False, guiVerified=False,
                     sourceCommit='a'*40, sourceRun=123, runAttempt=1, sourceTree='b'*40,
                     sourceLockSha256='c'*64, sourcePin=dict(coreCommit=CORE),
                     host=dict(isWindows=True, processMachine=0, nativeMachine=0xaa64),
                     calcDispatchSourceHooks=dict(schemaVersion=1,
                         kind='calc-save-dispatch-diagnostic-source', passed=True,
                         target='windows-arm64', coreCommit=CORE, lockSha256='c'*64,
                         fullEngineQualified=False, acceptanceEligible=False),
                     artifact=dict(path='producer-owned-engine.zip', size=len(engine), sha256=fetch.sha(engine)))
        lock = dict(schemaVersion=1, kind='calc-dispatch-diagnostic-input', architecture='arm64',
                    repository='ATLKR/OpenGeul', repositoryId=REPOSITORY_ID,
                    sourceCommit='a'*40, runId=123, runAttempt=1, artifactId=456,
                    sourceLockSha256='c'*64, coreCommit=CORE)
        artifact.update(name='opengeul-native-arm64-calc-dispatch-123-1')
        artifact['workflow_run'].update(repository_id=REPOSITORY_ID, head_repository_id=REPOSITORY_ID)
        run.update(event='push', head_branch='work/opengeul-office-native-engine',
                   actor=dict(login='ATLKR', id=65988341, type='User'))
        for name in ('repository', 'head_repository'):
            run[name].update(id=REPOSITORY_ID, private=False)
        self.save(root, 'run', run)
        self.pack(root, lock, artifact, proof, engine)
        return lock, artifact, run, scenario, proof, engine

    def save(self, root, name, value):
        (root / (name + '.json')).write_text(json.dumps(value), encoding='utf-8')

    def pack(self, root, lock, artifact, proof, engine, *, entries=None):
        receipt = json.dumps(proof).encode()
        outer = fetch.zip_bytes(entries if entries is not None else
                                [(ENGINE, engine, 0), (RECEIPT, receipt, 0)])
        (root / 'outer.zip').write_bytes(outer)
        lock.update(artifactSha256=fetch.sha(outer), artifactSize=len(outer))
        artifact.update(digest='sha256:' + fetch.sha(outer), size_in_bytes=len(outer))
        self.save(root, 'lock', lock)
        self.save(root, 'artifact', artifact)
        return receipt

    def execute(self, root, *, timeout_seconds=1200):
        self.assertTrue(SCRIPT.is_file(), 'A distinct locked Calc dispatch artifact fetcher is required')
        harness = fetch.HARNESS.replace('Invoke-SourceEngineFetch', 'Invoke-CalcDispatchFetch')
        harness = harness.replace('SourceLockPath=', 'DiagnosticLockPath=')
        harness = harness.replace('. $Script\n', ". $Script -Output (Join-Path $Root 'output') -TimeoutSeconds 23\n"
                                  "if ($Output -cne (Join-Path $Root 'output') -or $TimeoutSeconds -ne 23) { throw 'Imported helper overwrote diagnostic parameters.' }\n")
        (root / 'harness.ps1').write_text(harness, encoding='utf-8')
        environment = dict(os.environ, GH_TOKEN=fetch.SECRET, GITHUB_TOKEN=fetch.SECRET)
        process = subprocess.run([fetch.PWSH, '-NoLogo', '-NoProfile', '-File', str(root / 'harness.ps1'),
                                  '-Root', str(root), '-Script', str(SCRIPT),
                                  '-FetchTimeoutSeconds', str(timeout_seconds)], env=environment,
                                 capture_output=True, text=True, timeout=30)
        output = process.stdout + process.stderr
        self.assertNotIn(fetch.SECRET, output)
        self.assertNotIn(fetch.SIGNED_SECRET, output)
        for path in (root / 'output').glob('*.json'):
            self.assertNotIn(fetch.SECRET, path.read_text())
            self.assertNotIn(fetch.SIGNED_SECRET, path.read_text())
        events = json.loads((root / 'events.json').read_text()) if (root / 'events.json').exists() else []
        return process, events if isinstance(events, list) else [events]

    def test_locked_outer_digest_authenticates_derived_inner_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock, _, _, _, proof, engine = self.fixture(root)
            process, events = self.execute(root)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual((root / 'output' / ENGINE).read_bytes(), engine)
            receipt = (root / 'output' / RECEIPT).read_bytes()
            self.assertEqual(json.loads(receipt), proof)
            audit = json.loads((root / 'output/calc-dispatch-download.json').read_text())
            self.assertIs(audit['passed'], True)
            self.assertEqual(audit['artifactSha256'], lock['artifactSha256'])
            self.assertEqual(audit['engineSha256'], fetch.sha(engine))
            self.assertEqual(audit['receiptSha256'], fetch.sha(receipt))
            self.assertEqual(audit['sourceCommit'], lock['sourceCommit'])
            self.assertEqual(audit['sourceLockSha256'], lock['sourceLockSha256'])
            self.assertEqual([item['endpoint'] for item in events], ['artifact', 'run', 'redirect', 'blob'])
            self.assertEqual([item['authenticated'] for item in events], [True, True, True, False])
            self.assertNotIn('producer-owned-engine', json.dumps(audit))

    def test_metadata_rejects_wrong_source_owner_attempt_branch_family_or_digest(self):
        cases = [('run', 'head_sha', 'b'*40), ('run', 'run_attempt', 2),
                 ('run', 'event', 'workflow_dispatch'), ('run', 'head_branch', 'main'),
                 ('run', 'conclusion', 'failure'), ('run.actor', 'id', 1),
                 ('run.repository', 'id', 1), ('run.head_repository', 'private', True),
                 ('artifact', 'name', 'opengeul-native-arm64-engine-123-1'),
                 ('artifact', 'digest', 'sha256:' + 'd'*64),
                 ('artifact.workflow_run', 'head_sha', 'b'*40)]
        for target, key, value in cases:
            with self.subTest(target=target, key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root)
                name, *nested = target.split('.')
                document = json.loads((root / (name + '.json')).read_text())
                part = document
                for item in nested:
                    part = part[item]
                part[key] = value
                self.save(root, name, document)
                process, events = self.execute(root)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(any(item['endpoint'] in ('redirect', 'blob') for item in events))
                self.assertFalse((root / 'output' / ENGINE).exists())

    def test_outer_must_authenticate_before_receipt_is_parsed_or_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            outer = root / 'outer.zip'
            raw = bytearray(outer.read_bytes()); raw[-1] ^= 1; outer.write_bytes(raw)
            process, _ = self.execute(root)
            self.assertNotEqual(process.returncode, 0)
            self.assertFalse((root / 'output' / RECEIPT).exists())
            self.assertFalse((root / 'output' / ENGINE).exists())
            audit = json.loads((root / 'output/calc-dispatch-download.json').read_text())
            self.assertFalse(audit['passed'])
            self.assertEqual(audit['stage'], 'authenticated-outer-zip')
            self.assertNotIn('receiptSha256', audit)

    def test_authenticated_receipt_still_requires_diagnostic_source_and_hook_joins(self):
        cases = [('sourceCommit', 'b'*40), ('sourceRun', 999), ('runAttempt', True),
                 ('sourceLockSha256', 'd'*64), ('fullEngineQualified', True),
                 ('calcDispatchSourceHooks.lockSha256', 'd'*64),
                 ('calcDispatchSourceHooks.coreCommit', 'e'*40),
                 ('calcDispatchSourceHooks.passed', 'true'),
                 ('artifact.sha256', 'f'*64)]
        for key, value in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                lock, artifact, _, _, proof, engine = self.fixture(root)
                part = proof
                names = key.split('.')
                for name in names[:-1]:
                    part = part[name]
                part[names[-1]] = value
                self.pack(root, lock, artifact, proof, engine)
                process, _ = self.execute(root)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(json.loads((root / 'output/calc-dispatch-download.json').read_text())['passed'])

    def test_only_two_exact_regular_diagnostic_members_are_extracted(self):
        for mode in ('ordinary', 'extra', 'duplicate', 'linked', 'traversal'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                lock, artifact, _, _, proof, engine = self.fixture(root)
                entries = [(ENGINE, engine, 0), (RECEIPT, json.dumps(proof).encode(), 0)]
                if mode == 'ordinary': entries[0] = (fetch.ENGINE, engine, 0)
                if mode == 'extra': entries.append(('extra', b'unsafe', 0))
                if mode == 'duplicate': entries[1] = entries[0]
                if mode == 'linked': entries[0] = (ENGINE, engine, 0xa000 << 16)
                if mode == 'traversal': entries[0] = ('../' + ENGINE, engine, 0)
                self.pack(root, lock, artifact, proof, engine, entries=entries)
                process, _ = self.execute(root)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse((root / 'output' / ENGINE).exists())
                self.assertFalse((root / 'output' / RECEIPT).exists())

    def test_forbidden_signed_download_stops_without_retry_or_other_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, _, _, scenario, _, _ = self.fixture(root)
            scenario['blobStatus'] = 403; self.save(root, 'scenario', scenario)
            process, events = self.execute(root)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual([item['endpoint'] for item in events], ['artifact', 'run', 'redirect', 'blob'])
            audit = json.loads((root / 'output/calc-dispatch-download.json').read_text())
            self.assertFalse(audit['passed'])
            self.assertFalse((root / 'output' / ENGINE).exists())

    def test_only_selected_server_metadata_fields_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, artifact, _, _, _, _ = self.fixture(root)
            artifact['workflow_run']['unapproved'] = 'Do not persist arbitrary server fields'
            self.save(root, 'artifact', artifact)
            process, _ = self.execute(root)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            metadata = json.loads((root / 'output/artifact-server-metadata.json').read_text())
            self.assertEqual(set(metadata['artifact']['workflow_run']),
                             {'id', 'repository_id', 'head_repository_id', 'head_sha'})

    def test_array_source_identity_cannot_be_coerced_to_the_expected_string(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, _, run, _, _, _ = self.fixture(root)
            run['head_sha'] = ['a'*40]; self.save(root, 'run', run)
            process, events = self.execute(root)
            self.assertNotEqual(process.returncode, 0, 'An array was accepted as the producer source string')
            self.assertFalse(any(item['endpoint'] == 'blob' for item in events))

    def test_existing_output_is_preserved_before_http(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            output = root / 'output'; output.mkdir()
            marker = output / 'keep'; marker.write_bytes(b'original evidence')
            process, events = self.execute(root)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(events, [])
            self.assertEqual(list(output.iterdir()), [marker])
            self.assertEqual(marker.read_bytes(), b'original evidence')

    def test_missing_external_artifact_pins_fail_before_output_or_http(self):
        for key in ('artifactId', 'artifactSha256', 'artifactSize'):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                lock, _, _, _, _, _ = self.fixture(root)
                del lock[key]; self.save(root, 'lock', lock)
                process, events = self.execute(root)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(events, [])
                self.assertFalse((root / 'output').exists())

    def test_stalled_body_uses_one_original_cancellation_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, _, _, scenario, _, _ = self.fixture(root)
            with fetch.loopback_responses(root, stalled='blob') as origin:
                scenario['loopbackOrigin'] = origin; self.save(root, 'scenario', scenario)
                process, _ = self.execute(root, timeout_seconds=1)
            self.assertNotEqual(process.returncode, 0)
            audit = json.loads((root / 'output/calc-dispatch-download.json').read_text())
            self.assertFalse(audit['passed'])
            self.assertTrue(audit['deadlineExceeded'])
            self.assertLess(audit['elapsedSeconds'], 3)
            self.assertFalse((root / 'output' / ENGINE).exists())


if __name__ == '__main__':
    unittest.main()
