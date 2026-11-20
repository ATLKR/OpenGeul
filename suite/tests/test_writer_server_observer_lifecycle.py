"""Portable contracts; synthetic fixtures do not certify Windows admission."""
import importlib
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))


class Clock:
    frequency = 1000
    def __init__(self): self.value = 100000
    def read(self): return self.value


class Contracts(unittest.TestCase):
    def module(self):
        try: return importlib.import_module('writer_server_observer_lifecycle')
        except ModuleNotFoundError: self.fail('lifecycle implementation absent')

    def test_budget_has_one_original_absolute_interval(self):
        m = self.module(); clock = Clock()
        budget = m.OriginalWriterBudget.start(clock)
        self.assertEqual((budget.start_qpc, budget.cutoff_qpc, budget.deadline_qpc), (100000, 125000, 130000))
        clock.value = 124001
        self.assertEqual(budget.remaining_ms(observation=True), 999)
        self.assertEqual(budget.remaining_ms(observation=False), 5999)

    def test_exact_cutoff_forbids_a_new_observation(self):
        m = self.module(); clock = Clock(); budget = m.OriginalWriterBudget.start(clock)
        clock.value = 125000
        with self.assertRaises(m.DiagnosticFailure): budget.check(observation=True)
        self.assertEqual(budget.remaining_ms(observation=False), 5000)

    def test_exact_deadline_forbids_success(self):
        m = self.module(); clock = Clock(); budget = m.OriginalWriterBudget.start(clock)
        clock.value = 130000
        with self.assertRaises(m.DiagnosticFailure): budget.check(observation=False)

    def test_budget_clock_reversal_is_sticky(self):
        m = self.module(); clock = Clock(); budget = m.OriginalWriterBudget.start(clock)
        clock.value += 1; budget.check(observation=True); clock.value -= 2
        with self.assertRaises(m.DiagnosticFailure): budget.check(observation=True)
        clock.value = 100010
        with self.assertRaises(m.DiagnosticFailure): budget.check(observation=False)

    def test_frequency_change_cannot_extend_the_interval(self):
        m = self.module(); clock = Clock(); budget = m.OriginalWriterBudget.start(clock)
        clock.frequency = 2000
        with self.assertRaises(m.DiagnosticFailure): budget.check(observation=True)

    def test_noninteger_clock_is_not_silently_rounded(self):
        m = self.module(); clock = Clock(); clock.value = 1.25
        with self.assertRaises(m.DiagnosticFailure): m.OriginalWriterBudget.start(clock)

    def test_invalid_frequency_is_rejected(self):
        m = self.module()
        for value in (0, -1, True, 1.5):
            with self.subTest(kind=type(value).__name__):
                clock = Clock(); clock.frequency = value
                with self.assertRaises(m.DiagnosticFailure): m.OriginalWriterBudget.start(clock)

    def test_qpc_deadline_overflow_is_rejected(self):
        m = self.module(); clock = Clock(); clock.value = (1 << 63) - 1
        with self.assertRaises(m.DiagnosticFailure): m.OriginalWriterBudget.start(clock)

    def test_budget_cannot_be_rebased_or_mutated(self):
        m = self.module(); budget = m.OriginalWriterBudget.start(Clock())
        with self.assertRaises((AttributeError, TypeError)): budget.deadline_qpc = 1

    def test_runtime_session_can_begin_only_once(self):
        m = self.module(); session = m.RuntimeSession(Clock())
        first = session.begin_runtime()
        with self.assertRaises(m.DiagnosticFailure): session.begin_runtime()
        self.assertEqual(first.deadline_qpc, 130000)

    def test_preparation_has_no_runtime_budget(self):
        m = self.module(); clock = Clock(); session = m.RuntimeSession(clock)
        clock.value += 500000
        self.assertIsNone(session.budget)
        budget = session.begin_runtime()
        self.assertEqual((budget.start_qpc, budget.deadline_qpc), (600000, 630000))

    def layout(self, m, root):
        root = Path(root); payload = root / 'payload'; win = root / 'system'; temp = root / 'owned-temp'
        program = payload / 'Office' / 'program'; core = program / 'python-core-3.13.15'
        for p in (core / 'bin', core / 'lib' / 'site-packages', win / 'System32', temp, root / 'profile' / 'Roaming', root / 'profile' / 'Local'):
            p.mkdir(parents=True, exist_ok=True)
        (core / 'bin' / 'python.exe').touch(); (program / 'fundamental.ini').touch()
        layout = m.RuntimeLayout.validated(payload, win, temp)
        values = {'SystemRoot': str(win), 'WINDIR': str(win), 'USERPROFILE': str(root / 'profile'), 'APPDATA': str(root / 'profile' / 'Roaming'), 'LOCALAPPDATA': str(root / 'profile' / 'Local'), 'PATH': 'SYNTHETIC_SECRET_MUST_NOT_BE_COPIED', 'PYTHONPATH': 'SYNTHETIC_SECRET_MUST_NOT_BE_COPIED', 'GH_TOKEN': 'SYNTHETIC_SECRET_MUST_NOT_BE_COPIED'}
        return layout, values

    def descriptor(self):
        # These small constructed tokens are synthetic grammar fixtures only.
        return ':'.join(('1', str(1 + 1), str(2 + 1), format(3 + 1, '016x'), '131328', 'OpenGeulWriterServerObserver'))

    def test_environment_reads_only_named_nonsecret_bootstrap_keys(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root); requested = []
            def read(name): requested.append(name); return values.get(name)
            env = m.build_launch_environment(read, layout, self.descriptor())
            self.assertEqual(requested, ['SystemRoot', 'WINDIR', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'])
            self.assertEqual(set(env), {'SystemRoot', 'WINDIR', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP', 'PATH', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE', 'PYTHONIOENCODING', 'UNO_PATH', 'URE_BOOTSTRAP', 'OPENGEUL_WRITER_SERVER_OBSERVER'})
            self.assertTrue(all('SYNTHETIC_SECRET' not in v for v in env.values()))

    def test_environment_reconstructs_search_paths_instead_of_copying(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root)
            env = m.build_launch_environment(values.get, layout, self.descriptor())
            self.assertEqual(env['PATH'].split(';'), [str(layout.program), str(layout.windows / 'System32'), str(layout.windows)])
            self.assertEqual(env['PYTHONPATH'].split(';'), [str(layout.program), str(layout.core / 'lib'), str(layout.core / 'lib' / 'site-packages')])
            self.assertEqual(env['TEMP'], str(layout.temp)); self.assertEqual(env['TMP'], str(layout.temp))

    def test_missing_bootstrap_key_fails_without_ambient_fallback(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root); del values['APPDATA']
            with self.assertRaises(m.DiagnosticFailure): m.build_launch_environment(values.get, layout, self.descriptor())

    def test_profile_escape_is_rejected(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root); values['APPDATA'] = str(layout.windows)
            with self.assertRaises(m.DiagnosticFailure): m.build_launch_environment(values.get, layout, self.descriptor())

    def test_environment_cannot_replace_validated_system_location(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root); values['SystemRoot'] = str(layout.temp)
            with self.assertRaises(m.DiagnosticFailure): m.build_launch_environment(values.get, layout, self.descriptor())

    def test_bad_private_descriptor_is_not_exported_in_error(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root)
            with self.assertRaises(m.DiagnosticFailure) as caught: m.build_launch_environment(values.get, layout, 'SYNTHETIC_SECRET_MUST_NOT_BE_COPIED')
            self.assertNotIn('SYNTHETIC_SECRET', str(caught.exception))

    def test_private_layout_is_not_exposed_by_repr(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            layout, values = self.layout(m, root)
            self.assertNotIn(root, repr(layout))

    def test_unvalidated_layout_cannot_authorize_an_environment(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            good, values = self.layout(m, root)
            unvalidated = m.RuntimeLayout(good.payload, good.windows, good.temp, good.program, good.core)
            with self.assertRaises(m.DiagnosticFailure): m.build_launch_environment(values.get, unvalidated, self.descriptor())

    def test_search_path_separator_in_layout_is_rejected(self):
        m = self.module()
        with tempfile.TemporaryDirectory(prefix='synthetic;') as root:
            with self.assertRaises(m.DiagnosticFailure): self.layout(m, root)

    def test_clock_frequency_access_failure_has_only_numeric_error(self):
        m = self.module()
        class Broken:
            @property
            def frequency(self): raise RuntimeError('SYNTHETIC_SECRET_DO_NOT_REPORT')
        try:
            m.OriginalWriterBudget.start(Broken())
        except Exception as error:
            self.assertIs(type(error), m.DiagnosticFailure)
            self.assertNotIn('SYNTHETIC_SECRET', str(error))
        else: self.fail('Invalid clock was accepted')

    def test_replacing_frozen_budget_cannot_extend_or_rebase_it(self):
        m = self.module(); budget = m.OriginalWriterBudget.start(Clock())
        for changes in ({'deadline_qpc': 131000}, {'cutoff_qpc': 126000},
                        {'start_qpc': 101000, 'cutoff_qpc': 126000, 'deadline_qpc': 131000}):
            with self.subTest(field_count=len(changes)):
                with self.assertRaises(m.DiagnosticFailure): replace(budget, **changes)


if __name__ == '__main__': unittest.main()
