"""Bounded class-3 native census contracts; DLL calls alone are simulated."""
import copy
import ctypes
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))


class JobProcessCensusTests(unittest.TestCase):
    def setUp(self):
        self.native = importlib.import_module('native_windows')
        self.calls, self.receipts = [], []
        self.clock = [1.0]
        self.last_error = [0]

    def census(self, script, *, check=None):
        api = object.__new__(self.native.ProcessDiagnosticsApi)
        remaining = list(script)

        def query(job, info, output, size, used):
            self.assertEqual((job, info), (401, 3))
            row = remaining.pop(0)
            self.calls.append((job, info, size))
            value = output._obj
            value.assigned, value.count = row['assigned'], row['count']
            for index, pid in enumerate(row.get('pids', [])[:128]):
                value.pids[index] = pid
            used._obj.value = row.get('used', 8 + 8 * min(row['count'], 128))
            self.last_error[0] = row.get('error', 0)
            self.clock[0] += .001
            return row.get('result', True)

        api.query_job = query
        with patch.object(ctypes, 'get_last_error', lambda: self.last_error[0], create=True), \
                patch.object(self.native, 'time', create=True) as timer:
            timer.monotonic.side_effect = lambda: self.clock[0]
            return api.job_pids(401, record=lambda r: self.receipts.append(copy.deepcopy(r)), check=check)

    def test_in_capacity_partial_then_complete_returns_only_complete_list_and_keeps_raw_calls(self):
        result = self.census([dict(assigned=3, count=2, pids=[98, 99]),
                              dict(assigned=2, count=2, pids=[98, 100])])
        self.assertEqual(result, [98, 100])
        self.assertEqual(len(self.calls), 2)
        group, = self.receipts
        self.assertEqual(group['classification'], 'complete')
        self.assertEqual([r['classification'] for r in group['calls']], ['incomplete', 'complete'])
        self.assertEqual([r['pids'] for r in group['calls']], [[98, 99], [98, 100]])
        self.assertEqual((group['jobHandleValue'], group['capacity'], group['maxAttempts']), (401, 128, 3))
        self.assertEqual((group['api'], group['informationClass']), ('QueryInformationJobObject', 3))
        self.assertEqual((group['bufferBytes'], group['headerBytes'], group['processIdBytes']), (1032, 8, 8))
        for index, row in enumerate(group['calls'], 1):
            self.assertEqual(row['attempt'], index)
            self.assertTrue(row['result'])
            self.assertEqual(row['lastError'], 0)
            self.assertLessEqual(row['startedAt'], row['finishedAt'])
            self.assertEqual(row['returnLength'], 24)

    def test_incomplete_census_exhausts_exactly_three_calls_without_returning_partial_pids(self):
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            self.census([dict(assigned=3, count=2, pids=[98, 99])] * 3)
        self.assertEqual(len(self.calls), 3)
        group, = self.receipts
        self.assertEqual(group['classification'], 'failed')
        self.assertEqual([r['classification'] for r in group['calls']], ['incomplete'] * 3)

    def test_capacity_overflow_and_invalid_headers_fail_on_first_call(self):
        for row in (dict(assigned=129, count=128), dict(assigned=129, count=129),
                    dict(assigned=1, count=2), dict(assigned=128, count=129),
                    dict(assigned=2, count=2, used=23), dict(assigned=0, count=0, used=1033)):
            with self.subTest(row=row):
                before = len(self.calls)
                with self.assertRaises(RuntimeError):
                    self.census([row])
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(self.receipts[-1]['classification'], 'failed')
                self.assertEqual(len(self.receipts[-1]['calls']), 1)

    def test_native_failures_including_more_data_never_retry_or_trust_output(self):
        for code in (5, 234):
            with self.subTest(error=code):
                before = len(self.calls)
                with self.assertRaises(RuntimeError) as raised:
                    self.census([dict(assigned=3, count=2, pids=[98, 99], result=False, error=code)])
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(raised.exception.winerror, code)
                self.assertEqual(raised.exception.job_census, self.receipts[-1])
                self.assertEqual(self.receipts[-1]['calls'][0]['classification'], 'api-error')
                self.assertFalse(self.receipts[-1]['calls'][0]['result'])

    def test_exact_empty_success_is_one_complete_census(self):
        self.assertEqual(self.census([dict(assigned=0, count=0, pids=[])]), [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.receipts[0]['calls'][0]['pids'], [])
        self.assertEqual(self.receipts[0]['calls'][0]['classification'], 'complete')

    def test_original_deadline_check_surrounds_every_native_call_and_stops_next_attempt(self):
        checks = []

        def check():
            checks.append(self.clock[0])
            if self.clock[0] >= 1.001:
                raise TimeoutError('original reader deadline')

        with self.assertRaisesRegex(TimeoutError, 'original reader deadline') as raised:
            self.census([dict(assigned=3, count=2, pids=[98, 99])], check=check)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(checks), 2)
        self.assertEqual(raised.exception.job_census, self.receipts[-1])
        self.assertEqual(self.receipts[-1]['classification'], 'failed')
        self.assertEqual(self.receipts[-1]['calls'][0]['classification'], 'incomplete')

    def test_expired_before_query_records_failure_and_never_calls_native_api(self):
        def check():
            raise TimeoutError('already expired')

        with self.assertRaisesRegex(TimeoutError, 'already expired'):
            self.census([], check=check)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.receipts[-1]['calls'], [])

    def test_legacy_no_keyword_caller_still_gets_complete_list(self):
        api = object.__new__(self.native.ProcessDiagnosticsApi)
        def query(job, info, output, size, used):
            output._obj.assigned = output._obj.count = 1
            output._obj.pids[0] = 77
            used._obj.value = 16
            return True
        api.query_job = query
        with patch.object(ctypes, 'get_last_error', lambda: 0, create=True):
            self.assertEqual(api.job_pids(401), [77])

    def test_legacy_call_does_not_treat_in_capacity_incompleteness_as_buffer_overflow(self):
        api = object.__new__(self.native.ProcessDiagnosticsApi)
        rows = [(3, 2, [98, 99]), (2, 2, [98, 100])]
        calls = []
        def query(job, info, output, size, used):
            assigned, count, pids = rows.pop(0)
            calls.append((job, info, size))
            output._obj.assigned, output._obj.count = assigned, count
            for index, pid in enumerate(pids):
                output._obj.pids[index] = pid
            used._obj.value = 24
            return True
        api.query_job = query
        with patch.object(ctypes, 'get_last_error', lambda: 0, create=True):
            self.assertEqual(api.job_pids(401), [98, 100])
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
