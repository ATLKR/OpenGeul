"""Synthetic producer archives for the separate six-engine menu UI gate."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_native_archive_completeness as old_archives

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/native_menu_archive_completeness.py'
REPORT = '.work/suite-native-menu/results.json'
ROOT = '.work/suite-native-menu/worker-diagnostics'
MODULES = ('writer', 'calc', 'impress', 'draw', 'math', 'base')
VIEW_MODULES = ('writer', 'calc')
CORE_COMMANDS = ['new-hwp', 'home', 'new', 'open', 'save', 'saveAs', 'close']


class NativeMenuArchiveCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory).resolve()
        self.suite = self.root / 'Suite 한글'; self.suite.mkdir()
        self.base = old_archives.NativeArchiveCompletenessTests('test_every_source_fixed_case_and_original_generation_has_one_archive')
        self.base.root, self.base.suite = self.root, self.suite
        self.base.image = str(self.suite / 'Office/program/soffice.bin')
        self.base.next_pid, self.base.expected = 100, []
        rows = []
        for module in MODULES:
            row = self.base.row('native-menu-' + module, 1, 'gui', ROOT)
            row.update(module=module, kind='native-menu-gesture-case', scenarioCompleted=True,
                actualWindowsExecuted=True, nativeMenuVerified=True, cleanupConfirmed=True,
                cleanClose=True, forcedCleanupRequired=False, officeExited=True,
                officeExitedAfterCleanup=True, officeExitCode=0, shellExitCode=0,
                engineHandleReleased=True, officeCreationTime=row['nativeArchiveGeneration']['creationTime'])
            row.update(viewRoundtripCompleted=module in VIEW_MODULES,
                       viewPhysicalVerified=module in VIEW_MODULES)
            if module in VIEW_MODULES:
                row['nativeViewRoundtrip'] = dict(kind='native-view-roundtrip', module=module,
                    success=True, originalHomeSurvived=True,
                    previewActions=[dict(kind='owned-native-menu-action', success=True,
                        command='printPreview', gesture=False) for _ in range(2)],
                    observations=[dict(kind='owned-native-view-observation', success=True,
                        module=module, preview=preview, menuVisible=visible)
                        for preview, visible in ((True, True), (False, True), (False, False), (False, True))],
                    fullscreenActions=[dict(kind='owned-native-fullscreen-toggle', success=True,
                        module=module, focusReturned=True) for _ in range(2)],
                    coreCommands=[dict(kind='owned-native-menu-action', success=True,
                        command='core-commands', gesture=True, coreCommandsVerified=True,
                        coreCommands=list(CORE_COMMANDS), focusReturned=True) for _ in range(2)])
            rows.append(row)
        self.report = dict(schemaVersion=1, kind='native-menu-gesture-matrix', success=True,
            actualWindowsExecuted=True, nativeMenuVerified=True, scenarioSuccess=True,
            acceptanceEligible=False, expectedCaseCount=6, completedCaseCount=6,
            viewPhysicalVerified=True, viewPhysicalExpectedCaseCount=2, viewPhysicalVerifiedCaseCount=2,
            passedCaseCount=6, missingModules=[], failedModules=[], tests=rows)
        self.save_report()
        for index, entry in enumerate(self.base.expected):
            self.base.archive(entry, index)

    def implementation(self):
        self.assertTrue(SOURCE.is_file(), 'The independent native menu archive join is missing')
        spec = importlib.util.spec_from_file_location('native_menu_archive_under_test', SOURCE)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def verify(self):
        return self.implementation().verify_native_menu_archive_completeness(self.root, self.suite)

    def save_report(self):
        self.base.write_json(self.root / REPORT, self.report)

    def reseal_last(self, change):
        entry = self.base.expected[0]
        path = entry['folder'] / 'events.jsonl'
        lines = path.read_bytes().splitlines()
        last = json.loads(lines[-1]); change(last)
        lines[-1] = json.dumps(last, separators=(',', ':')).encode()
        path.write_bytes(b'\n'.join(lines) + b'\n')
        entry['diagnostics'].record_shutdown(entry['shutdownProof'])

    def test_exact_six_source_cases_match_sealed_archives_without_rewriting_reports(self):
        before = (self.root / REPORT).read_bytes()
        result = self.verify()
        self.assertIs(result['success'], True)
        self.assertEqual((result['expectedGenerations'], result['matchedGenerations']), (6, 6))
        self.assertEqual([r['case'] for r in result['archives']], ['native-menu-' + m for m in MODULES])
        self.assertEqual(result['sourceReceipts'][0]['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual((self.root / REPORT).read_bytes(), before)
        self.assertTrue(all(row['lastEventVerified'] for row in result['archives']))
        for forbidden in ('bodyText', 'keyTokens', 'processes', 'metadata'):
            self.assertNotIn(forbidden, json.dumps(result))

    def test_legacy_success_report_without_physical_view_cases_is_rejected(self):
        for key in ('viewPhysicalVerified', 'viewPhysicalExpectedCaseCount',
                    'viewPhysicalVerifiedCaseCount'):
            self.report.pop(key, None)
        for row in self.report['tests']:
            for key in ('viewRoundtripCompleted', 'viewPhysicalVerified', 'nativeViewRoundtrip'):
                row.pop(key, None)
        self.save_report()
        with self.assertRaises(ValueError):
            self.verify()

    def test_view_report_flags_and_counts_cannot_qualify_missing_or_different_coverage(self):
        original = copy.deepcopy(self.report)
        for key, values in (
                ('viewPhysicalVerified', (None, False, 1, 'true')),
                ('viewPhysicalExpectedCaseCount', (None, 1, 3, True, 2.0, '2')),
                ('viewPhysicalVerifiedCaseCount', (None, 1, 3, True, 2.0, '2'))):
            for value in values:
                with self.subTest(key=key, value=value):
                    self.report = copy.deepcopy(original)
                    if value is None: self.report.pop(key)
                    else: self.report[key] = value
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()

    def test_each_writer_and_calc_requires_its_actual_completed_view_roundtrip(self):
        original = copy.deepcopy(self.report)
        for index in (0, 1):
            for key in ('viewRoundtripCompleted', 'viewPhysicalVerified'):
                for value in (None, False, 1, 'true'):
                    with self.subTest(module=VIEW_MODULES[index], key=key, value=value):
                        self.report = copy.deepcopy(original)
                        if value is None: self.report['tests'][index].pop(key)
                        else: self.report['tests'][index][key] = value
                        self.save_report()
                        with self.assertRaises(ValueError): self.verify()

    def test_other_modules_cannot_replace_or_mix_with_the_two_source_fixed_view_cases(self):
        original = copy.deepcopy(self.report)
        for index in range(2, 6):
            for mixed in (False, True):
                with self.subTest(module=MODULES[index], mixed=mixed):
                    self.report = copy.deepcopy(original)
                    target = self.report['tests'][index]
                    target.update(viewRoundtripCompleted=True, viewPhysicalVerified=True,
                                  nativeViewRoundtrip=copy.deepcopy(self.report['tests'][0]['nativeViewRoundtrip']))
                    target['nativeViewRoundtrip']['module'] = MODULES[index]
                    if mixed:
                        self.report['tests'][0].update(viewRoundtripCompleted=False, viewPhysicalVerified=False)
                        self.report['tests'][0].pop('nativeViewRoundtrip')
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()

    def test_roundtrip_kind_module_success_and_home_must_match_the_original_case(self):
        original = copy.deepcopy(self.report)
        changes = (('kind', 'other'), ('module', 'calc'), ('success', False),
                   ('success', 1), ('originalHomeSurvived', False), ('originalHomeSurvived', None))
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.report = copy.deepcopy(original)
                roundtrip = self.report['tests'][0]['nativeViewRoundtrip']
                if value is None: roundtrip.pop(key)
                else: roundtrip[key] = value
                self.save_report()
                with self.assertRaises(ValueError): self.verify()
        for value in (None, [], True):
            self.report = copy.deepcopy(original)
            if value is None: self.report['tests'][0].pop('nativeViewRoundtrip')
            else: self.report['tests'][0]['nativeViewRoundtrip'] = value
            self.save_report()
            with self.assertRaises(ValueError): self.verify()

    def test_roundtrip_requires_each_current_source_plan_step_and_order(self):
        original = copy.deepcopy(self.report)
        for field in ('previewActions', 'observations', 'fullscreenActions', 'coreCommands'):
            for mutation in ('missing', 'short', 'extra', 'failed', 'kind'):
                with self.subTest(field=field, mutation=mutation):
                    self.report = copy.deepcopy(original)
                    roundtrip = self.report['tests'][0]['nativeViewRoundtrip']
                    if mutation == 'missing': roundtrip.pop(field)
                    elif mutation == 'short': roundtrip[field].pop()
                    elif mutation == 'extra': roundtrip[field].append(copy.deepcopy(roundtrip[field][-1]))
                    else: roundtrip[field][0]['success' if mutation == 'failed' else 'kind'] = False if mutation == 'failed' else 'other'
                    self.save_report()
                    with self.assertRaises(ValueError): self.verify()
        for target, key, value in (
                ('previewActions', 'command', 'save'), ('previewActions', 'gesture', True),
                ('fullscreenActions', 'module', 'calc'), ('fullscreenActions', 'focusReturned', False),
                ('observations', 'module', 'calc'), ('observations', 'preview', 1),
                ('observations', 'menuVisible', False), ('coreCommands', 'command', 'save'),
                ('coreCommands', 'gesture', False), ('coreCommands', 'coreCommandsVerified', False),
                ('coreCommands', 'coreCommands', CORE_COMMANDS[:-1]), ('coreCommands', 'focusReturned', False)):
            with self.subTest(field=target, key=key):
                self.report = copy.deepcopy(original)
                self.report['tests'][0]['nativeViewRoundtrip'][target][0][key] = value
                self.save_report()
                with self.assertRaises(ValueError): self.verify()
        self.report = copy.deepcopy(original)
        observations = self.report['tests'][0]['nativeViewRoundtrip']['observations']
        observations[0], observations[1] = observations[1], observations[0]
        self.save_report()
        with self.assertRaises(ValueError): self.verify()

    def test_failed_or_synthetic_report_cannot_substitute_for_actual_six_case_source(self):
        original = copy.deepcopy(self.report)
        for key, value in (('success', False), ('actualWindowsExecuted', False),
                           ('nativeMenuVerified', False), ('kind', 'other'), ('expectedCaseCount', 5)):
            with self.subTest(key=key):
                self.report = copy.deepcopy(original); self.report[key] = value; self.save_report()
                with self.assertRaises(ValueError): self.verify()

    def test_missing_duplicated_or_reordered_cases_are_rejected(self):
        original = copy.deepcopy(self.report)
        for rows in (original['tests'][:-1], original['tests'] + [original['tests'][0]],
                     list(reversed(original['tests']))):
            self.report = copy.deepcopy(original); self.report['tests'] = rows; self.save_report()
            with self.assertRaises(ValueError): self.verify()

    def test_unconfirmed_case_cleanup_and_wrong_original_engine_are_rejected(self):
        original = copy.deepcopy(self.report)
        for key, value in (('cleanupConfirmed', False), ('forcedCleanupRequired', True),
                           ('engineHandleReleased', False), ('officeExitCode', 1),
                           ('officeCreationTime', original['tests'][0]['officeCreationTime'] + 1)):
            with self.subTest(key=key):
                self.report = copy.deepcopy(original); self.report['tests'][0][key] = value; self.save_report()
                with self.assertRaises(ValueError): self.verify()

    def test_original_shell_binding_and_image_guards_are_reused(self):
        original = copy.deepcopy(self.report)
        for target in ('shell', 'image'):
            with self.subTest(target=target):
                self.report = copy.deepcopy(original)
                if target == 'shell':
                    self.report['tests'][0]['windowActivations'][0]['originalProcess']['pid'] += 1
                else:
                    self.report['tests'][0]['nativeArchiveGeneration']['image'] = 'C:/foreign/soffice.bin'
                self.save_report()
                with self.assertRaises(ValueError): self.verify()

    def test_missing_archive_and_duplicate_archive_do_not_hide_in_siblings(self):
        entry = self.base.expected[0]
        original = entry['folder']; moved = self.root / 'omitted'
        original.rename(moved)
        with self.assertRaises(ValueError): self.verify()
        moved.rename(original)
        shutil.copytree(original, self.root / ROOT / ('f' * 32))
        with self.assertRaises(ValueError): self.verify()

    def test_orphan_engine_archive_is_rejected(self):
        self.base.row('synthetic-orphan', 1, 'gui', ROOT)
        self.base.archive(self.base.expected[-1], 7)
        with self.assertRaises(ValueError): self.verify()

    def test_existing_archive_member_hash_and_graceful_guards_are_not_bypassed(self):
        entry = self.base.expected[0]
        events = entry['folder'] / 'events.jsonl'; original = events.read_bytes()
        events.write_bytes(b'?' + original[1:])
        with self.assertRaises(ValueError): self.verify()
        events.write_bytes(original)
        proof = copy.deepcopy(entry['shutdownProof']); proof['forcedTermination'] = True
        entry['diagnostics'].record_shutdown(proof)
        with self.assertRaises(ValueError): self.verify()

    def test_last_event_must_be_after_shutdown_even_if_its_new_bytes_are_sealed(self):
        self.reseal_last(lambda last: last.update(phase='shutdown-unconfirmed'))
        with self.assertRaises(ValueError): self.verify()

    def test_last_event_cannot_hide_missing_duplicate_or_new_engine_generation(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'; original = path.read_bytes()
        changes = [lambda last: last.update(processes=[]),
            lambda last: last['processes'].append(copy.deepcopy(last['processes'][-1])),
            lambda last: last['processes'][-1].update(pid=999999),
            lambda last: last['processes'][-1].update(creationTime=999999),
            lambda last: last['processes'][-1].update(image='C:/foreign/soffice.bin')]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                path.write_bytes(original); self.reseal_last(change)
                with self.assertRaises(ValueError): self.verify()

    def test_earlier_owned_helper_can_exit_before_the_shutdown_witness_is_opened(self):
        # Actual diagnostics retain job members from bootstrap onward, while the
        # shutdown observer opens later and cannot see an already dead helper.
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        lines = path.read_bytes().splitlines()
        early, terminal = json.loads(lines[0]), json.loads(lines[-1])
        helper = copy.deepcopy(terminal['processes'][0])
        helper.update(pid=900001, creationTime=500001,
            image=str(self.suite / 'Office/program/helper.exe'))
        early['processes'].append(dict(helper, alive=True, waitResult=258,
            exitCode=259, exitCodeHex='0x00000103'))
        terminal['processes'].append(helper)
        lines[0] = json.dumps(early).encode(); lines[-1] = json.dumps(terminal).encode()
        path.write_bytes(b'\n'.join(lines) + b'\n')
        entry['diagnostics'].record_shutdown(entry['shutdownProof'])
        result = self.verify()
        self.assertEqual(result['archives'][0]['lastEventMemberCount'], 3)
        self.assertEqual(result['archives'][0]['earlierDiagnosticMemberCount'], 1)

    def test_diagnostic_only_terminal_member_needs_the_same_earlier_owned_generation(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        original = path.read_bytes()
        for mismatch in ('missing', 'pid', 'creationTime', 'image', 'error'):
            with self.subTest(mismatch=mismatch):
                lines = original.splitlines()
                early, terminal = json.loads(lines[0]), json.loads(lines[-1])
                helper = copy.deepcopy(terminal['processes'][0])
                helper.update(pid=900001, creationTime=500001,
                    image=str(self.suite / 'Office/program/helper.exe'))
                observed = dict(helper, alive=True, waitResult=258,
                    exitCode=259, exitCodeHex='0x00000103')
                if mismatch == 'pid': observed['pid'] += 1
                elif mismatch == 'creationTime': observed['creationTime'] += 1
                elif mismatch == 'image': observed['image'] = 'C:/foreign/helper.exe'
                elif mismatch == 'error': observed['error'] = {'type': 'SyntheticError'}
                if mismatch != 'missing': early['processes'].append(observed)
                terminal['processes'].append(helper)
                lines[0] = json.dumps(early).encode(); lines[-1] = json.dumps(terminal).encode()
                path.write_bytes(b'\n'.join(lines) + b'\n')
                entry['diagnostics'].record_shutdown(entry['shutdownProof'])
                with self.assertRaises(ValueError): self.verify()

    def test_last_event_native_errors_alive_or_nonzero_exit_fail(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'; original = path.read_bytes()
        for key, value in (('alive', True), ('waitResult', 258), ('exitCode', 1),
                           ('getExitCodeProcessResult', False), ('error', {'type': 'synthetic'})):
            with self.subTest(key=key):
                path.write_bytes(original)
                self.reseal_last(lambda last, key=key, value=value: last['processes'][-1].update({key: value}))
                with self.assertRaises(ValueError): self.verify()

    def test_oversized_last_event_and_trailing_partial_line_are_rejected(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        self.reseal_last(lambda last: last.update(syntheticPadding='x' * (256 * 1024)))
        with self.assertRaises(ValueError): self.verify()
        # Corrupting sealed terminal bytes is also rejected by the shared hash guard.
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError): self.verify()

    def test_cli_replay_writes_a_bounded_result_and_preserves_failed_qualification(self):
        module = self.implementation()
        target = self.root / 'coverage.json'
        args = ['--workspace', str(self.root), '--suite', str(self.suite), '--output', str(target)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 0)
        self.assertEqual(json.loads(target.read_text())['matchedGenerations'], 6)
        self.reseal_last(lambda last: last.update(phase='shutdown-unconfirmed'))
        failed = self.root / 'failure.json'
        args[-1] = str(failed)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        value = json.loads(failed.read_text())
        self.assertFalse(value['success'])
        self.assertEqual(value['errorType'], 'ValueError')
        self.assertNotIn('processes', value)

    def test_cli_must_not_resolve_away_a_linked_workspace_before_admission(self):
        linked = self.root / 'linked-workspace'
        try:
            os.symlink(self.root, linked, target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlink creation is unavailable to this test process')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.implementation().main(['--workspace', str(linked), '--suite', str(self.suite),
                '--output', str(self.root / 'linked-result.json')])

    def test_cli_rejects_a_dangling_output_symlink_without_creating_its_target(self):
        target = self.root / 'not-created.json'; linked = self.root / 'linked-output.json'
        try:
            os.symlink(target, linked)
        except OSError:
            self.skipTest('File symlink creation is unavailable to this test process')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.implementation().main(['--workspace', str(self.root), '--suite', str(self.suite),
                '--output', str(linked)])
        self.assertFalse(target.exists())

    def test_different_menu_cases_cannot_reuse_the_same_original_engine_generation(self):
        first, second = self.report['tests'][:2]
        second['nativeArchiveGeneration'] = copy.deepcopy(first['nativeArchiveGeneration'])
        second['officePid'] = first['officePid']
        second['officeCreationTime'] = first['officeCreationTime']
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'Duplicate original'):
            self.verify()

    def test_only_the_terminal_event_is_parsed_after_the_stream_hash_is_verified(self):
        entry = self.base.expected[0]; path = entry['folder'] / 'events.jsonl'
        lines = path.read_bytes().splitlines()
        lines[0] = b'SYNTHETIC-UNPARSED-EARLIER-EVENT'
        path.write_bytes(b'\n'.join(lines) + b'\n')
        entry['diagnostics'].record_shutdown(entry['shutdownProof'])
        self.assertTrue(self.verify()['success'])

    def test_terminal_event_re_read_is_bound_to_the_descriptor_already_verified(self):
        module = self.implementation(); original = module.original._archived
        path = self.base.expected[0]['folder'] / 'events.jsonl'
        def archive_then_change(*args):
            result = original(*args)
            raw = path.read_bytes(); path.write_bytes(b'?' + raw[1:])
            return result
        with patch.object(module.original, '_archived', side_effect=archive_then_change):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                module.verify_native_menu_archive_completeness(self.root, self.suite)
