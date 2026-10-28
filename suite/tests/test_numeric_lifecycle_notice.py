"""Aggregate notices observe the real lifecycle main flow using synthetic cases."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from suite.tests.test_numeric_notice import environment


ROOT = Path(__file__).resolve().parents[1]/'e2e'
PRIVATE = 'SYNTHETIC-PRIVATE-INPUT C:/private/aggregate ::error::caption'


def implementation(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NumericLifecycleNoticeTests(unittest.TestCase):
    def run_main(self, *, enabled=True, error=None, uno_code=0, baseline_change=False,
                 telemetry_error=None, import_error=False):
        smoke = implementation('lifecycle_smoke')
        notice = implementation('numeric_notice')
        env = environment()
        env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '6'
        if not enabled:
            env.pop('OPENGEUL_SUITE_NUMERIC_NOTICE')
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            suite, fixtures, output = (root/name for name in ('suite','baseline','output'))
            suite.mkdir(); fixtures.mkdir()
            fixture = fixtures/'synthetic.bin'
            fixture.write_bytes(b'synthetic baseline')
            records = [dict(case=name, success=True, **{key:True for key in required})
                       for name, required in smoke.CASE_REQUIREMENTS.items()]

            def packaged_uno(*args, **kwargs):
                if error is not None:
                    raise error
                result = dict(success=uno_code == 0,
                              cases=[dict(case=row['case'],success=True) for row in records])
                (output/'packaged-uno-result.json').write_text(json.dumps(result))
                if baseline_change:
                    fixture.write_bytes(b'synthetic changed baseline')
                return SimpleNamespace(returncode=uno_code)

            stack.enter_context(patch.object(smoke, 'os', SimpleNamespace(name='nt')))
            stack.enter_context(patch.object(smoke.native, 'prepare_ascii_cohort', return_value=object()))
            stack.enter_context(patch.object(smoke.native, 'collect_cases', return_value=records))
            stack.enter_context(patch.object(smoke.native, 'write_result'))
            stack.enter_context(patch.object(smoke.subprocess, 'run', side_effect=packaged_uno))
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            stack.enter_context(patch.dict('sys.modules', {'numeric_notice':None if import_error else notice}))
            if telemetry_error:
                stack.enter_context(patch.object(notice, telemetry_error, side_effect=RuntimeError('synthetic telemetry error')))
            with redirect_stdout(stream):
                status = smoke.main(['--suite',str(suite),'--fixtures',str(fixtures),'--output',str(output)])
            report = json.loads((output/'results.json').read_text(encoding='utf-8'))
        lines = [line.split('::',2)[2] for line in stream.getvalue().splitlines()
                 if line.startswith('::notice title=')]
        self.assertNotIn(PRIVATE, stream.getvalue())
        notices = [notice.decode_notice(line,'a'*40,123,expected_architecture=0xaa64) for line in lines]
        return status, report, notices, notice

    def assert_original_case_results(self, report):
        self.assertEqual(report['expectedCaseCount'], 7)
        self.assertEqual(report['completedCaseCount'], 7)
        self.assertEqual(report['passedCaseCount'], 7)
        self.assertTrue(all(row['success'] is True for row in report['tests']))
        self.assertTrue(all('numericFailure' not in row for row in report['tests']))

    def test_aggregate_exception_adds_closed_code_and_preserves_original_error_and_exit(self):
        status, report, notices, notice = self.run_main(error=RuntimeError(PRIVATE))
        self.assertEqual(status, 1)
        self.assertFalse(report['success'])
        self.assertEqual(report['error'], 'Independent packaged UNO verification failed: RuntimeError: '+PRIVATE)
        self.assertIn('numericFailure', report, 'Opted-in aggregate exception needs its closed numeric code')
        code = notice.validate_failure_code(report['numericFailure'])
        self.assertEqual(code['exceptionCode'], notice.EXCEPTIONS[RuntimeError])
        self.assertEqual(code['fileCode'], notice.SOURCE_FILES['lifecycle_smoke.py'])
        self.assertGreater(code['line'], 0)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['scopeCode'], 6)
        self.assertEqual(notices[0]['caseCode'], notice.CASES['lifecycle-summary'][0])
        self.assertTrue(report['baselineFixturesUnchanged'])
        self.assert_original_case_results(report)

    def test_disabled_exception_keeps_original_report_without_numeric_fields_or_notices(self):
        _, enabled, _, _ = self.run_main(error=RuntimeError(PRIVATE))
        status, disabled, notices, _ = self.run_main(enabled=False,error=RuntimeError(PRIVATE))
        self.assertEqual(status, 1)
        self.assertNotIn('numericFailure', disabled)
        enabled.pop('numericFailure')
        self.assertEqual(disabled, enabled)
        self.assertEqual(notices, [])

    def test_nonzero_uno_status_emits_without_inventing_an_exception_code(self):
        status, report, notices, _ = self.run_main(uno_code=1)
        self.assertEqual(status, 1)
        self.assertFalse(report['success'])
        self.assertEqual(report['packagedUnoExitCode'], 1)
        self.assertEqual(report['error'], 'Independent packaged UNO lifecycle reopen failed; inspect packaged-uno-result.json and packaged-uno.log')
        self.assertNotIn('numericFailure', report)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['exceptionCode'], 0)
        self.assert_original_case_results(report)

    def test_changed_baseline_emits_without_changing_the_existing_failure_result(self):
        status, report, notices, _ = self.run_main(baseline_change=True)
        self.assertEqual(status, 1)
        self.assertFalse(report['baselineFixturesUnchanged'])
        self.assertFalse(report['success'])
        self.assertEqual(report['error'], 'Lifecycle tests changed baseline fixture files')
        self.assertNotIn('numericFailure', report)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['exceptionCode'], 0)
        self.assert_original_case_results(report)

    def test_successful_aggregate_does_not_emit_a_failure_notice(self):
        status, report, notices, _ = self.run_main()
        self.assertEqual(status, 0)
        self.assertTrue(report['success'])
        self.assertTrue(report['baselineFixturesUnchanged'])
        self.assertNotIn('numericFailure', report)
        self.assertEqual(notices, [])

    def test_telemetry_failures_cannot_replace_the_original_exception_or_final_result(self):
        for target in ('capture_failure_code','emit_case_notice'):
            with self.subTest(target=target):
                status, report, _, _ = self.run_main(error=RuntimeError(PRIVATE),telemetry_error=target)
                self.assertEqual(status, 1)
                self.assertEqual(report['error'], 'Independent packaged UNO verification failed: RuntimeError: '+PRIVATE)
                self.assert_original_case_results(report)
        status, report, notices, _ = self.run_main(error=RuntimeError(PRIVATE),import_error=True)
        self.assertEqual(status, 1)
        self.assertEqual(report['error'], 'Independent packaged UNO verification failed: RuntimeError: '+PRIVATE)
        self.assertNotIn('numericFailure', report)
        self.assertEqual(notices, [])


if __name__ == '__main__':
    unittest.main()
