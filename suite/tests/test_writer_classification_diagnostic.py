"""Numeric classification observations over the original synthetic native ports."""
from pathlib import Path
import json
import tempfile
import unittest

from test_writer_server_observer_runner_composition import setup, runner


FIELDS = {'classificationAttemptCount': 4096, 'classificationReasonCode': 10,
    'classificationCensusCount': 128, 'classificationMatchedRoleMask': 15,
    'classificationCurrentRoleCode': 4, 'classificationHistoricalRoleCode': 4,
    'classificationWaitResult': 0xffffffff, 'classificationExitCode': 0xffffffff}


def record_classification_calls(instance, components):
    calls, active = [], [False]
    for code, name in ((1, 'census'), (2, 'open_initial_member'), (3, 'identity'),
                       (4, 'member'), (5, 'state'), (7, 'close')):
        original = getattr(components.api, name)
        def record(*args, _original=original, _code=code, **kwargs):
            if active[0]: calls.append((_code, args[0]))
            return _original(*args, **kwargs)
        setattr(components.api, name, record)
    original_image = components.prep.process_image
    def image(*args, **kwargs):
        if active[0]: calls.append((6, args[0]))
        return original_image(*args, **kwargs)
    components.prep.process_image = image
    original_classify = instance._classify
    def classify(*args, **kwargs):
        active[0] = True
        try: return original_classify(*args, **kwargs)
        finally: active[0] = False
    instance._classify = classify
    return calls


class Classification(unittest.TestCase):
    def setUp(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def tearDown(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def require_fields(self, report):
        self.assertTrue(FIELDS.keys() <= report['preparation'].keys())
        return report['preparation']

    def require_rejected(self, report, reason):
        prep = self.require_fields(report)
        self.assertEqual(report['failureCode'], 6)
        self.assertEqual(prep['classificationReasonCode'], reason)
        self.assertIsNone(prep['rolesClassified'])
        self.assertIsNone(prep['cohortAdmitted'])
        self.assertIsNone(prep['runtimeEntered'])
        self.assertIsNone(prep['originalEngineExitObserved'])
        self.assertTrue(report['captureIncomplete'])
        self.assertFalse(report['normalAcceptance'])
        self.assertFalse(report['fullEngineQualified'])
        self.assertFalse(report['acceptanceEligible'])
        self.assertFalse(report['guiVerified'])
        return prep

    def test_every_existing_guard_has_a_fixed_reason_without_changing_native_call_order(self):
        host = [(1, 1000), (3, 201), (4, 201), (5, 201), (6, 201)]
        worker = [(2, 301), (3, 202), (4, 202), (5, 202), (6, 202)]
        engine = [(2, 401), (3, 301), (4, 301), (5, 301), (6, 301)]
        expected = {1: [(1, 1000)], 2: [(1, 1000)],
            3: host + worker[:2] + [(7, 202)],
            4: host + worker[:3] + [(7, 202)],
            5: host + worker[:4] + [(7, 202)],
            6: host + worker + engine + [(7, 202), (7, 301)],
            7: host + worker + engine + [(7, 202), (7, 301)],
            8: [(1, 1000)] + worker + [(7, 202)], 9: host}
        for reason in range(1, 10):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as folder:
                runner._PENDING_CASES.clear(); runner._CASE_STARTED = False
                obj, inputs, c, _ = setup(folder)
                original_identity, original_member, original_state = c.api.identity, c.api.member, c.api.state
                if reason == 1: c.api.census = lambda job: [101, 301, 401]
                elif reason == 2: c.api.census = lambda job: (301, 401)
                elif reason == 3:
                    c.api.identity = lambda handle: (999, 311) if handle == 202 else original_identity(handle)
                elif reason == 4:
                    c.api.member = lambda handle, job: False if handle == 202 else original_member(handle, job)
                elif reason == 5:
                    c.api.state = lambda handle: (0, 42) if handle == 202 else original_state(handle)
                elif reason == 6:
                    unknown = inputs.output / 'synthetic-unknown.exe'; unknown.touch()
                    c.api.images[301] = unknown
                elif reason == 7: c.api.images[301] = inputs.output / 'OpenGeul.Office.exe'
                elif reason == 8:
                    c.api.census = lambda job: (301, 101, 401)
                    c.api.images[202] = inputs.output / 'OpenGeul.Office.exe'
                else:
                    c.api.identity = lambda handle: (101, 999) if handle == 201 else original_identity(handle)
                calls = record_classification_calls(obj, c)
                report = obj.execute(inputs)
                self.assertEqual(calls, expected[reason])
                prep = self.require_rejected(report, reason)
                self.assertEqual(prep['classificationAttemptCount'], 1)
                self.assertNotIn('helper-launch', c.api.calls)
                if reason != 9:
                    self.assertTrue(prep['cleanupComplete'])
                    self.assertEqual(report['pendingRetainedCount'], 0)

    def test_success_records_actual_current_roles_and_state_without_historical_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            calls = record_classification_calls(obj, c)
            report = obj.execute(inputs); prep = self.require_fields(report)
            self.assertEqual(calls, [(1, 1000), (3, 201), (4, 201), (5, 201), (6, 201),
                (2, 301), (3, 202), (4, 202), (5, 202), (6, 202),
                (2, 401), (3, 301), (4, 301), (5, 301), (6, 301), (7, 202), (7, 301)])
            self.assertEqual(report['failureCode'], 0)
            self.assertEqual(prep['classificationAttemptCount'], 1)
            self.assertEqual(prep['classificationReasonCode'], 0)
            self.assertEqual(prep['classificationCensusCount'], 3)
            self.assertEqual(prep['classificationMatchedRoleMask'], 7)
            self.assertEqual(prep['classificationCurrentRoleCode'], 3)
            self.assertEqual(prep['classificationHistoricalRoleCode'], 0)
            self.assertEqual(prep['classificationWaitResult'], 258)
            self.assertEqual(prep['classificationExitCode'], 259)

    def history_failure(self, folder, *, wrong_birth=False, unknown_image=False):
        obj, inputs, c, _ = setup(folder)
        polls = [0]
        original_state, original_identity = c.api.state, c.api.identity
        def census(job): polls[0] += 1; return (101, 301)
        def state(handle):
            if handle == 202 and polls[0] > 1 and not unknown_image: return 0, 42
            return original_state(handle)
        def identity(handle):
            if handle == 202 and polls[0] > 1 and wrong_birth: return 301, 999
            return original_identity(handle)
        c.api.census, c.api.state, c.api.identity = census, state, identity
        if unknown_image:
            unknown = inputs.output / 'synthetic-unknown.exe'; unknown.touch()
            original_image = c.prep.process_image
            def image(handle, **kwargs):
                if handle == 202 and polls[0] > 1: return str(unknown)
                return original_image(handle, **kwargs)
            c.prep.process_image = image
        calls = record_classification_calls(obj, c)
        return obj.execute(inputs), calls

    def test_exited_previous_worker_preserves_its_exact_historical_generation_only(self):
        with tempfile.TemporaryDirectory() as folder:
            report, calls = self.history_failure(folder)
            prep = self.require_rejected(report, 5)
            self.assertEqual(prep['classificationCount'], 2)
            self.assertEqual(prep['classificationAttemptCount'], 2)
            self.assertEqual(prep['classificationCensusCount'], 2)
            self.assertEqual(prep['classificationMatchedRoleMask'], 1)
            self.assertEqual(prep['classificationCurrentRoleCode'], 0)
            self.assertEqual(prep['classificationHistoricalRoleCode'], 2)
            self.assertEqual(prep['classificationWaitResult'], 0)
            self.assertEqual(prep['classificationExitCode'], 42)
            self.assertEqual(calls[-5:], [(2, 301), (3, 202), (4, 202), (5, 202), (7, 202)])

    def test_same_pid_with_another_birth_is_unknown_history_and_still_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            report, _ = self.history_failure(folder, wrong_birth=True)
            prep = self.require_rejected(report, 5)
            self.assertEqual(prep['classificationHistoricalRoleCode'], 0)
            self.assertEqual(prep['classificationCurrentRoleCode'], 0)

    def test_previous_role_never_admits_an_unknown_current_image(self):
        with tempfile.TemporaryDirectory() as folder:
            report, _ = self.history_failure(folder, unknown_image=True)
            prep = self.require_rejected(report, 6)
            self.assertEqual(prep['classificationHistoricalRoleCode'], 2)
            self.assertEqual(prep['classificationCurrentRoleCode'], 0)
            self.assertEqual(prep['classificationMatchedRoleMask'], 1)

    def test_partial_failure_cannot_match_more_distinct_roles_than_its_current_census(self):
        with tempfile.TemporaryDirectory() as folder:
            report, _ = self.history_failure(folder)
        prep = self.require_rejected(report, 5)
        self.assertEqual(prep['classificationCensusCount'], 2)
        self.assertEqual(prep['classificationMatchedRoleMask'], 1)
        prep['classificationMatchedRoleMask'] = 7
        with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(report)

    def test_original_iteration_cap_is_distinct_from_a_process_guard_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            c.api.census = lambda job: (101, 301)
            obj.pause = lambda seconds: None
            report = obj.execute(inputs)
            prep = self.require_rejected(report, 10)
            self.assertEqual(prep['classificationAttemptCount'], 4096)
            self.assertEqual(prep['classificationCount'], 2)
            self.assertEqual(prep['classificationMatchedRoleMask'], 3)

    def test_before_classification_every_new_field_is_unknown(self):
        report = runner.empty_report()
        prep = self.require_fields(report)
        self.assertTrue(all(prep[key] is None for key in FIELDS))

    def test_closed_schema_rejects_unknown_fields_bool_overflow_and_unbound_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            good = obj.execute(inputs)
        self.require_fields(good)
        for key, maximum in FIELDS.items():
            for value in (True, -1, maximum + 1, 1.25, 'SYNTHETIC_PRIVATE'):
                report = json.loads(json.dumps(good)); report['preparation'][key] = value
                with self.subTest(field=list(FIELDS).index(key), category=type(value).__name__):
                    with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(report)
        report = runner.empty_report(); report['preparation']['classificationPrivate'] = 1
        with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(report)
        report = runner.empty_report(); report['preparation']['classificationCurrentRoleCode'] = 1
        with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(report)

    def test_completed_classification_cannot_claim_missing_roles_or_no_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            good = obj.execute(inputs)
        for values in ({'classificationAttemptCount': 0}, {'classificationReasonCode': 5},
                {'classificationMatchedRoleMask': 3}, {'classificationCensusCount': 2},
                {'classificationCurrentRoleCode': 0}, {'classificationCount': 4},
                {'classificationWaitResult': 0}):
            report = json.loads(json.dumps(good)); report['preparation'].update(values)
            with self.subTest(field_count=len(values)):
                with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(report)


if __name__ == '__main__': unittest.main()
