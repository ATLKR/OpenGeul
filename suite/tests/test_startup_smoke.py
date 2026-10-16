"""Platform-neutral coverage for strict native startup stress evidence."""
from contextlib import redirect_stdout
from collections import Counter
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'startup_smoke.py'


class StartupSmokeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'The bounded startup stress harness is missing')
        spec = importlib.util.spec_from_file_location('suite_startup_smoke', SOURCE)
        self.smoke = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SOURCE.parent))
        try:
            spec.loader.exec_module(self.smoke)
        finally:
            sys.path.pop(0)

    def passing_record(self, attempt):
        return dict(attempt, success=True, stage='complete', exception=None, traceback='',
                    shellPid=101, windowHwnd=102, parentHwnd=103, childHwnd=104, officePid=105,
                    nativeParentVerified=True, noExternalOfficeWindow=True, cleanClose=True,
                    shellExitCode=0, officeExited=True, officeCreationTime=123456789, stderrLog=attempt['case'] + '-stderr.log', stderrCaptured=True,
                    screenshot=attempt['case'] + '-attached.png', screenshotCaptured=True,
                    fixtureUnchanged=True, forcedCleanupRequired=False)

    def test_plan_alternates_existing_and_new_calc_and_writer_without_retries(self):
        plan = self.smoke.build_plan(20)
        self.assertEqual(len(plan), 20)
        self.assertEqual([(item['module'], item['mode']) for item in plan[:8]],
                         [('calc', 'existing'), ('calc', 'new'), ('writer', 'existing'), ('writer', 'new')] * 2)
        self.assertEqual(Counter((item['module'], item['mode']) for item in plan),
                         {('calc', 'existing'): 5, ('calc', 'new'): 5,
                          ('writer', 'existing'): 5, ('writer', 'new'): 5})
        self.assertEqual([item['attempt'] for item in plan], list(range(1, 21)))
        self.assertEqual(len({item['case'] for item in plan}), 20)
        self.assertEqual(len(self.smoke.build_plan(40)), 40)
        for count in (0, 1, 19, 21, 41, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.smoke.build_plan(count)

    def test_all_twenty_attempts_and_required_native_evidence_must_pass(self):
        plan = self.smoke.build_plan(20)
        records = [self.passing_record(attempt) for attempt in plan]
        report = self.smoke.stress_report(records, 20)
        self.assertTrue(report['success'])
        self.assertEqual(report['expectedAttemptCount'], 20)
        self.assertEqual(report['passedAttemptCount'], 20)
        self.assertFalse(report['failedAttempts'])
        self.assertFalse(report['imeVerified'])
        for field, value in (('success', False), ('cleanClose', False), ('nativeParentVerified', False),
                             ('noExternalOfficeWindow', False), ('stderrCaptured', False),
                             ('screenshotCaptured', False), ('windowHwnd', 0), ('childHwnd', 0),
                             ('shellExitCode', 1), ('officeExited', False), ('officeCreationTime', None), ('stage', 'attach'), ('fixtureUnchanged', False),
                             ('forcedCleanupRequired', True), ('exception', 'late failure')):
            with self.subTest(field=field):
                changed = [dict(record) for record in records]
                changed[0][field] = value
                failed = self.smoke.stress_report(changed, 20)
                self.assertFalse(failed['success'])
                self.assertIn(plan[0]['case'], failed['failedAttempts'])

    def test_failure_stays_failed_even_when_later_attempt_of_same_module_passes(self):
        plan = self.smoke.build_plan(20)
        records = [self.passing_record(attempt) for attempt in plan]
        records[0].update(success=False, stage='attach', exception='RuntimeError: original attach failed')
        report = self.smoke.stress_report(records, 20)
        self.assertFalse(report['success'])
        self.assertEqual(report['failedAttempts'], [plan[0]['case']])
        self.assertEqual(report['passedAttemptCount'], 19)
        self.assertEqual(report['attempts'][0]['exception'], 'RuntimeError: original attach failed')

    def test_missing_duplicate_unexpected_and_wrong_identity_cannot_pass(self):
        plan = self.smoke.build_plan(20)
        records = [self.passing_record(attempt) for attempt in plan]
        variants = [('missingAttempts', records[:-1], plan[-1]['case']),
                    ('duplicateAttempts', records + [dict(records[0])], plan[0]['case']),
                    ('unexpectedAttempts', records + [dict(records[0], case='unplanned')], 'unplanned')]
        for field, changed, name in variants:
            with self.subTest(field=field):
                report = self.smoke.stress_report(changed, 20)
                self.assertFalse(report['success'])
                self.assertIn(name, report[field])
        for field, value in (('module', 'base'), ('mode', 'new'), ('attempt', 2)):
            with self.subTest(field=field):
                changed = [dict(record) for record in records]
                changed[0][field] = value
                self.assertFalse(self.smoke.stress_report(changed, 20)['success'])
        reversed_records = list(reversed(records))
        self.assertFalse(self.smoke.stress_report(reversed_records, 20)['success'])

    def test_collector_runs_each_attempt_once_and_retains_exception_chain_and_later_results(self):
        plan = self.smoke.build_plan(20)
        calls = []
        def run(attempt):
            calls.append(attempt['case'])
            if attempt['attempt'] == 1:
                try:
                    raise ValueError('native original detail')
                except ValueError as exc:
                    raise RuntimeError('attach failed') from exc
            return self.passing_record(attempt)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory)
            report = self.smoke.run_attempts(plan, run, output, 20)
            saved = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            first = json.loads((output / (plan[0]['case'] + '-result.json')).read_text(encoding='utf-8'))
            self.assertEqual(calls, [attempt['case'] for attempt in plan])
            self.assertEqual(len(list(output.glob('*-result.json'))), 20)
            self.assertFalse(report['success'])
            self.assertEqual(saved, report)
            self.assertEqual(first['stage'], 'case-setup')
            self.assertIn('RuntimeError: attach failed', first['exception'])
            self.assertIn('ValueError: native original detail', first['traceback'])
            self.assertEqual(report['passedAttemptCount'], 19)
            self.assertTrue(report['attempts'][-1]['success'])

    def test_returned_cleanup_failure_is_retained_and_all_attempts_continue(self):
        plan = self.smoke.build_plan(20)
        def run(attempt):
            record = self.passing_record(attempt)
            if attempt['attempt'] == 1:
                record.update(success=False, cleanupError='owned process stayed live')
            return record
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            report = self.smoke.run_attempts(plan, run, Path(directory), 20)
        self.assertFalse(report['success'])
        self.assertEqual(report['attempts'][0]['cleanupError'], 'owned process stayed live')
        self.assertEqual(report['completedAttemptCount'], 20)


if __name__ == '__main__':
    unittest.main()
