"""Original layout guards, with synthetic native boundaries and closed evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
E2E = HERE.parent / 'e2e'
sys.path[:0] = [str(E2E), str(HERE)]
import test_ime_keyboard_session as ime_fixtures
import test_scenario_editor_shortcuts as scenario_fixtures

SOURCE = E2E / 'keyboard_layout_summary.py'
if SOURCE.is_file():
    import keyboard_layout_summary as summary
else:
    summary = None

US = 0x04090409
KO = 0x04120412
GENERATION = 134370146624845933
KEY = '_keyboardLayoutFailure'
FIELDS = ('origin', 'slot', 'officePid', 'officeCreationTime', 'childHwnd',
          'targetLayout', 'currentThreadLayout')


class KeyboardLayoutSummaryTests(unittest.TestCase):
    def ime(self, directory):
        factory = ime_fixtures.IMEKeyboardSessionTests()
        self.addCleanup(factory.doCleanups)
        f = factory.fixture(directory, retain_evidence=False)
        session, _, _, _, _, probe, record = f
        record.update(case='ime-writer', kind='native-korean-ime', stage='setup',
                      architecture='arm64', shellPid=77)
        session.start()
        self.addCleanup(session.close, AssertionError('synthetic original failure'))
        return session, probe, record

    def scenario(self, directory):
        factory = scenario_fixtures.ScenarioEditorShortcutsTests()
        f = factory.fixture(directory)
        session = factory.session(f)
        record = f[5]
        record.update(case='writer-heading1', module='writer', kind='native-writer-style',
                      stage='enter-editor', architecture='arm64')
        session._prepare()
        self.addCleanup(session._finish, AssertionError('synthetic original failure'))
        return session, f[4], record

    def assert_vector(self, record, expected):
        self.assertIn(KEY, record)
        self.assertIsNotNone(summary, 'Missing pure keyboard layout evidence helper')
        self.assertEqual(set(record[KEY]), set(FIELDS))
        self.assertEqual([record[KEY][key] for key in FIELDS], expected)
        self.assertEqual(summary.project(record), expected)
        self.assertTrue(summary.valid(expected))
        self.assertNotIn('PRIVATE_', json.dumps(record[KEY]))

    def test_actual_ime_failed_guard_keeps_original_values_without_another_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            session, probe, record = self.ime(directory)
            probe.layout = KO
            probe.calls.clear()
            with self.assertRaisesRegex(AssertionError, 'exact original US layout'):
                session._guard(strict=False)
            self.assertEqual(probe.calls,
                ['shell', ('engine', 2**41), 'scope', ('keyboard', 44)])
            self.assertEqual(probe.sent, [])
            self.assert_vector(record, [1, 1, 88, GENERATION, 22, KO, US])

    def test_actual_scenario_guard_distinguishes_both_existing_keyboard_slots(self):
        for slot in (1, 2):
            with self.subTest(slot=slot), tempfile.TemporaryDirectory() as directory:
                session, probe, record = self.scenario(directory)
                original = probe.keyboard_snapshot
                calls = []
                def keyboard(thread):
                    row = original(thread)
                    calls.append(thread)
                    if len(calls) == slot:
                        row['currentThreadLayout'] = KO
                    return row
                probe.keyboard_snapshot = keyboard
                probe.calls.clear()
                with self.assertRaisesRegex(AssertionError, 'exact English US layout'):
                    session._owned_guard()
                self.assertEqual(calls, [44, 44])
                self.assertEqual(probe.calls,
                    ['shell', ('engine', 2**41), 'scope', ('keyboard', 44), ('keyboard', 44)])
                self.assertEqual(probe.sent, [])
                self.assert_vector(record, [2, slot, 88, GENERATION, 22, US, KO])

    def test_exact_us_guards_add_no_optional_evidence_or_remember_call(self):
        self.assertIsNotNone(summary)
        for make, guard in ((self.ime, '_guard'), (self.scenario, '_owned_guard')):
            with tempfile.TemporaryDirectory() as directory:
                session, probe, record = make(directory)
                with patch.object(summary, 'remember', side_effect=AssertionError('should not run')) as remember:
                    getattr(session, guard)()
                self.assertEqual(remember.call_count, 0)
                self.assertNotIn(KEY, record)
                self.assertIsNone(summary.project(record))

    def test_optional_helper_failure_preserves_original_assertion(self):
        self.assertIsNotNone(summary)
        for make, guard, message in ((self.ime, '_guard', 'exact original US layout'),
                                    (self.scenario, '_owned_guard', 'exact English US layout')):
            with tempfile.TemporaryDirectory() as directory:
                session, probe, record = make(directory)
                probe.current_layout = KO
                with patch.object(summary, 'remember', side_effect=ValueError('PRIVATE_HELPER_ERROR')) as remember:
                    with self.assertRaisesRegex(AssertionError, message):
                        getattr(session, guard)()
                self.assertEqual(remember.call_count, 1)
                self.assertNotIn(KEY, record)
                self.assertEqual(probe.sent, [])

    def fixture(self):
        binding = dict(shellPid=77, shellCreationTime=GENERATION-100,
            officePid=88, officeCreationTime=GENERATION, suiteHwnd=11,
            parentHwnd=12, childHwnd=22, rootHwnd=11)
        record = dict(case='ime-writer', module='writer', kind='native-korean-ime',
            stage='setup', officePid=88, officeCreationTime=GENERATION, childHwnd=22)
        keyboard = dict(targetLayout=KO, currentThreadLayout=US,
            keysDown=[], capsLockOn=False, scrollLockOn=False, numLockOn=True,
            private='PRIVATE_INPUT_SENTINEL')
        return record, keyboard, binding

    def test_closed_vector_allows_zero_observed_hkl_but_requires_a_mismatch(self):
        self.assertIsNotNone(summary)
        for origin, slot in ((1, 1), (2, 1), (2, 2)):
            for target, controller in ((KO, US), (US, KO), (0, US), (US, 0), (0, 0)):
                with self.subTest(origin=origin, slot=slot, target=target, controller=controller):
                    value = [origin, slot, 88, GENERATION, 22, target, controller]
                    self.assertTrue(summary.valid(value))
        self.assertFalse(summary.valid([1, 1, 88, GENERATION, 22, US, US]))
        self.assertFalse(summary.valid([1, 2, 88, GENERATION, 22, KO, US]))

    def test_closed_vector_rejects_types_bounds_and_extra_values(self):
        self.assertIsNotNone(summary)
        value = [1, 1, 88, GENERATION, 22, KO, US]
        for index in range(7):
            for bad in (True, False, '1', 1.0, None):
                changed = list(value); changed[index] = bad
                with self.subTest(index=index, bad=bad): self.assertFalse(summary.valid(changed))
        for index, bad in ((0, 0), (0, 3), (1, 0), (1, 3), (2, 0), (2, 2**32),
                           (3, 0), (3, 2**64), (4, 0), (4, 2**64),
                           (5, -1), (5, 2**64), (6, -1), (6, 2**64)):
            changed = list(value); changed[index] = bad
            with self.subTest(index=index, bad=bad): self.assertFalse(summary.valid(changed))
        for bad in (tuple(value), dict(enumerate(value)), value[:-1], value+[0], None):
            self.assertFalse(summary.valid(bad))

    def test_projection_binds_exact_record_raw_snapshot_binding_and_context(self):
        self.assertIsNotNone(summary)
        mutations = [lambda r, k, b: r.update(officePid=89),
                     lambda r, k, b: r.update(officeCreationTime=GENERATION+1),
                     lambda r, k, b: r.update(childHwnd=23),
                     lambda r, k, b: r.update(stage='another-stage'),
                     lambda r, k, b: b.update(officeCreationTime=GENERATION+1),
                     lambda r, k, b: r[KEY].update(targetLayout=0),
                     lambda r, k, b: r[KEY].update(extra='PRIVATE_RAW_FIELD'),
                     lambda r, k, b: r.update({KEY:dict(r[KEY])})]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                record, keyboard, binding = self.fixture()
                summary.remember(record, 1, 1, keyboard, binding)
                self.assertEqual(summary.project(record), [1,1,88,GENERATION,22,KO,US])
                self.assertIsNone(summary.project(copy.deepcopy(record)))
                mutate(record, keyboard, binding)
                self.assertIsNone(summary.project(record))

    def test_current_session_receipt_replacement_rejects_old_evidence(self):
        self.assertIsNotNone(summary)
        for origin in (1, 2):
            record, keyboard, binding = self.fixture()
            receipt = dict(originalEngine=dict(pid=88, creationTime=GENERATION,
                handleValue=2**41, waitResult=258))
            if origin == 1: record['imeKeyboardSession'] = receipt
            else: record['editorShortcutSessions'] = [receipt]
            summary.remember(record, origin, 1, keyboard, binding)
            self.assertIsNotNone(summary.project(record))
            if origin == 1: record['imeKeyboardSession'] = dict(receipt)
            else: record['editorShortcutSessions'].append(dict(receipt))
            self.assertIsNone(summary.project(record))

    def test_actual_guard_owner_replacement_cannot_reuse_its_old_binding_snapshot(self):
        self.assertIsNotNone(summary)
        for make, guard in ((self.ime, '_guard'), (self.scenario, '_owned_guard')):
            for attribute in ('record', 'binding', 'receipt'):
                with self.subTest(make=make.__name__, attribute=attribute), tempfile.TemporaryDirectory() as directory:
                    session, probe, record = make(directory)
                    probe.layout = KO
                    with self.assertRaises(AssertionError): getattr(session, guard)()
                    self.assertIsNotNone(summary.project(record))
                    setattr(session, attribute, dict(getattr(session, attribute)))
                    self.assertIsNone(summary.project(record))

    def test_missing_outer_identity_is_not_invented_and_bad_remember_clears_stale_snapshot(self):
        self.assertIsNotNone(summary)
        record, keyboard, binding = self.fixture()
        for key in ('officePid', 'officeCreationTime', 'childHwnd'): record.pop(key)
        summary.remember(record, 2, 2, keyboard, binding)
        self.assertIsNotNone(summary.project(record))
        self.assertNotIn('officePid', record)
        with self.assertRaises(ValueError):
            summary.remember(record, 1, 2, keyboard, binding)
        self.assertNotIn(KEY, record)
        self.assertIsNone(summary.project(record))

    def test_associations_have_a_fixed_bound_and_never_supply_another_records_vector(self):
        self.assertIsNotNone(summary)
        records = []
        for _ in range(33):
            record, keyboard, binding = self.fixture()
            summary.remember(record, 1, 1, keyboard, binding)
            records.append(record)
        self.assertIsNone(summary.project(records[0]))
        self.assertIsNotNone(summary.project(records[-1]))
        self.assertIsNone(summary.project({KEY:dict(records[-1][KEY])}))

    def test_pure_decoder_import_initializes_no_native_or_producer_modules(self):
        self.assertIsNotNone(summary)
        code = ('import importlib.util,sys;'
            f'spec=importlib.util.spec_from_file_location("pure_layout",{str(SOURCE)!r});'
            'module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);'
            f'assert module.valid([1,1,88,{GENERATION},22,{KO},{US}]);'
            'assert module.project({}) is None;'
            'assert not any(n in sys.modules for n in '
            '("ctypes","windows_smoke","ime_keyboard_session","scenario_editor_shortcuts","numeric_notice","uno","pywinauto"))')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__': unittest.main()
