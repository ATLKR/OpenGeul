"""Retirement archive isolation with synthetic native rows and real bounded files."""
import copy
from contextlib import contextmanager
import hashlib
import json
import ntpath
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from suite.tests.test_ime_engine_retirement import Fixture, retirement


def descriptor(raw):
    return dict(rawUtf8=raw.decode('utf-8'), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class RetirementProfileIsolationTests(unittest.TestCase):
    @contextmanager
    def isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(folder)
            with patch.dict('os.environ', fixture.environment, clear=True):
                yield fixture

    def target(self, fixture, uuid='1' * 32):
        folder, manifest, shutdown = fixture.archive(uuid)
        manifest['ownedProfile'] = fixture.original_profile['canonicalPath']
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        return folder, manifest, shutdown

    def foreign(self, fixture, uuid='0' * 32):
        target, manifest, shutdown = self.target(fixture)
        folder = fixture.root / uuid
        folder.mkdir()
        rows = copy.deepcopy(shutdown['initialMembers'])
        for row in rows:
            row['pid'] += 100
            row['creationTime'] += 1000
            row.pop('handleValue', None)
        manifest = dict(schemaVersion=1, kind='owned-office-native-diagnostics',
                        archiveComplete=False, launcherPid=shutdown['launcherPid'] + 100,
                        workerPid=655, ownedProfile='C:\\foreign-profile', files=[])
        events = [dict(phase=phase, utc='2026-10-23T07:00:00+00:00', processes=copy.deepcopy(rows))
                  for phase in ['before-ui-bootstrap', 'after-ui-bootstrap', 'before-load']]
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        (folder / 'events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events))
        return target, folder, manifest, events

    def test_unrelated_incomplete_archive_does_not_block_selected_generation_in_either_sort_order(self):
        for uuid in ['0' * 32, 'f' * 32]:
            with self.subTest(uuid=uuid), self.isolated() as fixture:
                target, foreign, manifest, events = self.foreign(fixture, uuid)
                proof = fixture.verify(fixture.admit())
                self.assertIs(fixture.require(proof), proof)
                self.assertEqual(proof['archive']['uuid'], target.name)
                excluded, = proof['scan']['unrelatedIncomplete']
                self.assertEqual(set(excluded), {'uuid', 'manifest', 'events', 'profile', 'engine'})
                self.assertEqual(excluded['uuid'], foreign.name)
                self.assertEqual(excluded['profile'], 'c:\\foreign-profile')
                self.assertEqual(excluded['manifest'], descriptor((foreign / 'manifest.json').read_bytes()))
                self.assertEqual(excluded['events'], descriptor((foreign / 'events.jsonl').read_bytes()))
                engine, = [row for row in events[0]['processes'] if row['image'].endswith('soffice.bin')]
                self.assertEqual(excluded['engine'], dict(pid=engine['pid'], creationTime=engine['creationTime'],
                    image=ntpath.normcase(ntpath.normpath(engine['image']))))

    def test_foreign_complete_archive_still_uses_original_complete_candidate_checks(self):
        with self.isolated() as fixture:
            target, foreign, manifest, events = self.foreign(fixture)
            shutdown = json.loads((target / 'shutdown.json').read_text())
            shutdown['launcherPid'] += 100
            for group in ('initialMembers', 'finalMembers'):
                for row in shutdown[group]:
                    row['pid'] += 100
                    row['creationTime'] += 1000
            raw = (json.dumps(shutdown) + '\n').encode()
            (foreign / 'shutdown.json').write_bytes(raw)
            manifest.update(archiveComplete=True,
                files=[dict(path='shutdown.json', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())])
            (foreign / 'manifest.json').write_text(json.dumps(manifest))
            proof = fixture.verify(fixture.admit())
            self.assertIs(fixture.require(proof), proof)
            self.assertEqual(len(proof['scan']['candidates']), 2)
            self.assertEqual(proof['scan'].get('unrelatedIncomplete', []), [])

    def test_missing_target_or_its_shutdown_and_same_profile_incomplete_are_fatal(self):
        for mode in ['no-target', 'missing-target-shutdown', 'same-profile-incomplete', 'selected-profile-mismatch']:
            with self.subTest(mode=mode), self.isolated() as fixture:
                target, foreign, manifest, events = self.foreign(fixture)
                if mode == 'no-target':
                    for path in target.iterdir():
                        path.unlink()
                    target.rmdir()
                elif mode == 'missing-target-shutdown':
                    (target / 'shutdown.json').unlink()
                elif mode == 'same-profile-incomplete':
                    manifest['ownedProfile'] = fixture.original_profile['canonicalPath']
                    (foreign / 'manifest.json').write_text(json.dumps(manifest))
                else:
                    current = json.loads((target / 'manifest.json').read_text())
                    current['ownedProfile'] = 'C:\\relabeled-target'
                    (target / 'manifest.json').write_text(json.dumps(current))
                with self.assertRaises((AssertionError, ValueError, FileNotFoundError)):
                    fixture.verify(fixture.admit())

    def test_incomplete_header_needs_exact_local_profile_and_empty_member_inventory(self):
        changes = [dict(schemaVersion=True), dict(kind='unknown'), dict(archiveComplete=0),
                   dict(workerPid=True), dict(launcherPid=0), dict(files=[{'path': 'shutdown.json'}])]
        changes += [dict(ownedProfile=p) for p in ['', 'relative', 'C:\\', '\\\\server\\share\\profile',
                                                  '\\\\?\\C:\\foreign-profile', 'C:\\a\\..\\foreign-profile',
                                                  'C:\\foreign-profile.', 'C:\\foreign-profile ',
                                                  'C:\\folder:stream\\profile', 'C:\\Users\\RUNNER~1\\profile',
                                                  'C:\\CON\\profile', 'C:\\AUX.txt\\profile',
                                                  'C:\\bad?name\\profile']]
        for change in changes:
            with self.subTest(change=change), self.isolated() as fixture:
                target, foreign, manifest, events = self.foreign(fixture)
                manifest.update(change)
                (foreign / 'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises((AssertionError, ValueError, FileNotFoundError)):
                    fixture.verify(fixture.admit())

    def test_unrelated_journal_rejects_malformed_json_nonfinite_and_wrong_phase(self):
        for mode in ['duplicate-key', 'nonfinite', 'not-object', 'empty', 'wrong-first-phase', 'missing-processes']:
            with self.subTest(mode=mode), self.isolated() as fixture:
                target, foreign, manifest, events = self.foreign(fixture)
                if mode == 'duplicate-key':
                    raw = json.dumps(events[0]).replace('{', '{"phase":"before-ui-bootstrap",', 1) + '\n'
                elif mode == 'nonfinite':
                    raw = json.dumps(dict(events[0], diagnostic=float('nan'))) + '\n'
                elif mode == 'not-object':
                    raw = '[]\n'
                elif mode == 'empty':
                    raw = ''
                elif mode == 'wrong-first-phase':
                    events[0]['phase'] = 'before-load'
                    raw = ''.join(json.dumps(row) + '\n' for row in events)
                else:
                    del events[0]['processes']
                    raw = ''.join(json.dumps(row) + '\n' for row in events)
                (foreign / 'events.jsonl').write_text(raw)
                with self.assertRaises((AssertionError, ValueError, FileNotFoundError)):
                    fixture.verify(fixture.admit())

    def test_unrelated_journal_requires_stable_native_engine_and_manifest_launcher(self):
        for mode in ['empty-processes', 'too-many', 'bool-pid', 'float-birth', 'wrong-wait', 'failed-exit',
                     'error', 'missing-launcher', 'duplicate-engine', 'changed-birth', 'wrong-image']:
            with self.subTest(mode=mode), self.isolated() as fixture:
                target, foreign, manifest, events = self.foreign(fixture)
                rows = events[0]['processes']
                if mode == 'empty-processes': rows.clear()
                elif mode == 'too-many': events[0]['processes'] = rows * 65
                elif mode == 'bool-pid': rows[1]['pid'] = True
                elif mode == 'float-birth': rows[1]['creationTime'] = float(rows[1]['creationTime'])
                elif mode == 'wrong-wait': rows[1]['alive'] = False
                elif mode == 'failed-exit': rows[1]['getExitCodeProcessResult'] = False
                elif mode == 'error': rows[1]['observationError'] = 'unknown'
                elif mode == 'missing-launcher': rows.pop(0)
                elif mode == 'duplicate-engine': rows.append(copy.deepcopy(rows[1]))
                elif mode == 'changed-birth': events[1]['processes'][1]['creationTime'] += 1
                else: rows[1]['image'] = 'C:\\foreign-package\\program\\soffice.bin'
                (foreign / 'events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events))
                with self.assertRaises((AssertionError, ValueError, FileNotFoundError)):
                    fixture.verify(fixture.admit())

    def test_foreign_profile_cannot_hide_full_target_generation_but_shared_single_fields_are_distinct(self):
        for same in ['pid', 'birth', 'both']:
            with self.subTest(same=same), self.isolated() as fixture:
                target, foreign, manifest, events = self.foreign(fixture)
                for event in events:
                    engine = event['processes'][1]
                    if same in ['pid', 'both']: engine['pid'] = fixture.engine['pid']
                    if same in ['birth', 'both']: engine['creationTime'] = fixture.engine['creationTime']
                (foreign / 'events.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events))
                if same == 'both':
                    with self.assertRaises((AssertionError, ValueError, FileNotFoundError)):
                        fixture.verify(fixture.admit())
                else:
                    # PID reuse or equal creation timestamps do not equate complete native generations.
                    proof = fixture.verify(fixture.admit())
                    self.assertIs(fixture.require(proof), proof)
                    excluded, = proof['scan']['unrelatedIncomplete']
                    self.assertEqual(excluded['engine']['pid'], events[0]['processes'][1]['pid'])
                    self.assertEqual(excluded['engine']['creationTime'], events[0]['processes'][1]['creationTime'])

    def test_replay_rejects_forged_exclusion_projection_raw_descriptor_count_and_duplicates(self):
        with self.isolated() as fixture:
            self.foreign(fixture)
            original = fixture.verify(fixture.admit())
            changes = [lambda p: p['scan'].pop('unrelatedIncomplete'),
                       lambda p: p['scan']['unrelatedIncomplete'].append(copy.deepcopy(p['scan']['unrelatedIncomplete'][0])),
                       lambda p: p['scan']['unrelatedIncomplete'][0].update(profile=fixture.original_profile['canonicalPath']),
                       lambda p: p['scan']['unrelatedIncomplete'][0]['engine'].update(pid=fixture.engine['pid']),
                       lambda p: p['scan']['unrelatedIncomplete'][0]['engine'].update(creationTime=True),
                       lambda p: p['scan']['unrelatedIncomplete'][0].update(extra='unapproved'),
                       lambda p: p['scan']['unrelatedIncomplete'][0]['events'].update(bytes=1),
                       lambda p: p['scan']['unrelatedIncomplete'][0]['manifest'].update(sha256='0' * 64),
                       lambda p: p['scan'].update(descriptorBytes=p['scan']['descriptorBytes'] + 1)]
            for index, mutate in enumerate(changes):
                with self.subTest(index=index):
                    proof = copy.deepcopy(original)
                    mutate(proof)
                    with self.assertRaises((AssertionError, ValueError, KeyError)):
                        fixture.require(proof)

    def test_replay_revalidates_manifest_profile_and_target_identity_from_raw_journal(self):
        for mode in ['manifest-profile', 'journal-target', 'journal-error']:
            with self.subTest(mode=mode), self.isolated() as fixture:
                self.foreign(fixture)
                proof = fixture.verify(fixture.admit())
                row = proof['scan']['unrelatedIncomplete'][0]
                if mode == 'manifest-profile':
                    manifest = json.loads(row['manifest']['rawUtf8'])
                    manifest['ownedProfile'] = fixture.original_profile['canonicalPath']
                    row['manifest'] = descriptor(json.dumps(manifest).encode())
                    row['profile'] = fixture.original_profile['canonicalPath']
                else:
                    events = [json.loads(line) for line in row['events']['rawUtf8'].splitlines()]
                    for event in events:
                        if mode == 'journal-target':
                            event['processes'][1].update(pid=fixture.engine['pid'], creationTime=fixture.engine['creationTime'])
                        else: event['processes'][1]['error'] = 'unknown'
                    raw = ''.join(json.dumps(event) + '\n' for event in events).encode()
                    row['events'] = descriptor(raw)
                    if mode == 'journal-target':
                        row['engine'].update(pid=fixture.engine['pid'], creationTime=fixture.engine['creationTime'])
                # Recompute accounting too: the parser, not stale byte totals, must reject these records.
                proof['scan']['descriptorBytes'] = sum(
                    r[key]['bytes'] for r in proof['scan']['candidates'] for key in ['manifest', 'shutdown']) + sum(
                    r[key]['bytes'] for r in proof['scan']['unrelatedIncomplete'] for key in ['manifest', 'events'])
                with self.assertRaises((AssertionError, ValueError, KeyError)):
                    fixture.require(proof)

    def test_journal_byte_bound_and_descriptor_aggregate_include_excluded_records(self):
        with self.isolated() as fixture:
            target, foreign, manifest, events = self.foreign(fixture)
            (foreign / 'events.jsonl').write_bytes(b'x' * (256 * 1024 + 1))
            with self.assertRaises((AssertionError, ValueError)):
                fixture.verify(fixture.admit())
        with self.isolated() as fixture:
            target, foreign, manifest, events = self.foreign(fixture)
            total = sum((folder / name).stat().st_size for folder, names in
                [(target, ['manifest.json', 'shutdown.json']), (foreign, ['manifest.json', 'events.jsonl'])]
                for name in names)
            with patch.object(retirement, 'MAX_DESCRIPTORS', total):
                proof = fixture.verify(fixture.admit())
                self.assertEqual(proof['scan']['descriptorBytes'], total)
                self.assertIs(fixture.require(proof), proof)
            with patch.object(retirement, 'MAX_DESCRIPTORS', total - 1):
                with self.assertRaises((AssertionError, ValueError)):
                    fixture.require(proof)
        with self.isolated() as fixture:
            target, foreign, manifest, events = self.foreign(fixture)
            total = sum(path.stat().st_size for folder in [target, foreign] for path in folder.iterdir())
            with patch.object(retirement, 'MAX_DESCRIPTORS', total - 1):
                with self.assertRaises((AssertionError, ValueError)):
                    fixture.verify(fixture.admit())


if __name__ == '__main__':
    unittest.main()
