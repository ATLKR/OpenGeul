"""Synthetic T12 ordering; no Windows, document, input or restart proof."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import test_writer_server_observer_console as console_fixture
from test_writer_first_owned_peer_profile import retained_guard_line
from test_writer_server_observer_runner_composition import runner


class RetainedEngineRestart(unittest.TestCase):
    def setUp(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def tearDown(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def test_admitted_five_member_original_engine_exit81_rejects_before_attachment(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, profile, file_api, opens = console_fixture.Console().composed(folder)
            api = c.api
            identity, member, opened, state, census = (
                api.identity, api.member, api.open_initial_member, api.state, api.census)
            api.images[305] = inputs.output / 'Office/program/soffice.exe'
            api.identity = lambda handle: (601, 611) if handle == 305 else identity(handle)
            api.member = lambda handle, job: job == 1000 if handle == 305 else member(handle, job)
            api.open_initial_member = lambda pid, job: 305 if pid == 601 else opened(pid, job)
            api.census = lambda job: (101, 301, 501, 601, 401) if job == 1000 and not api.dead else census(job)
            transition = [False]
            engine_samples, admissions, attachment_calls = [], [], []

            def original_state(handle):
                if handle == 305:
                    return (0, 0) if api.dead else (258, 259)
                if handle == 301:
                    value = (0, 81) if transition[0] else state(handle)
                    engine_samples.append(value)
                    return value
                return state(handle)

            api.state = original_state
            original_cohort = c.Cohort

            class OriginalCohort(original_cohort):
                def admit(self):
                    super().admit()
                    admissions.append((self.admitted, len(self._members), self.original_engine.handle))

                def verify(self, budget=None):
                    transition[0] = True
                    return super().verify(budget)

            c.Cohort = OriginalCohort
            original_attachment = c.prep.find_attachment_once
            c.prep.find_attachment_once = lambda *args, **kwargs: (
                attachment_calls.append(1), original_attachment(*args, **kwargs))[1]
            report = obj.execute(inputs)

        prep = report['preparation']
        self.assertEqual(admissions, [(True, 5, 301)])
        self.assertIn((258, 259), engine_samples)
        self.assertIn((0, 81), engine_samples)
        self.assertEqual(prep['classificationCensusCount'], 5)
        self.assertEqual(prep['classificationCount'], 4)
        self.assertEqual(prep['classificationMatchedRoleMask'], 15)
        self.assertEqual(prep['classificationAuxiliaryCount'], 1)
        self.assertEqual((report['stageCode'], report['failureCode']), (4, 13))
        self.assertEqual((prep['preparationFailureKindCode'], prep['preparationFailureSourceCode'],
                          prep['preparationFailureLine']), (14, 7, retained_guard_line()))
        self.assertEqual((prep['cohortFailureRoleCode'], prep['cohortFailureWaitResult'],
                          prep['cohortFailureExitCode']), (3, 0, 81))
        self.assertEqual(attachment_calls, [])
        self.assertEqual(prep['focusSampleCount'], 0)
        self.assertEqual(prep['inputCount'], 0)
        self.assertIsNone(prep['attachmentBound'])
        self.assertIsNone(prep['runtimeEntered'])
        self.assertIsNone(report['msaa']['getAccFocusAttempted'])
        self.assertTrue(prep['cohortAdmitted'])
        self.assertTrue(prep['disposalRequested'])
        self.assertTrue(prep['originalEngineExitObserved'])
        self.assertTrue(prep['consoleAuxiliaryExitObserved'])
        self.assertTrue(prep['consoleJobEmptyObserved'])
        self.assertTrue(prep['consoleFileReleased'])
        self.assertTrue(prep['cleanupComplete'])
        self.assertEqual(report['pendingRetainedCount'], 0)
        self.assertEqual(api.calls.count('dispose-1000'), 1)
        self.assertNotIn('helper-launch', api.calls)
        self.assertFalse(report['normalAcceptance'])
        self.assertFalse(report['fullEngineQualified'])
        self.assertFalse(report['acceptanceEligible'])
        self.assertFalse(report['guiVerified'])


if __name__ == '__main__':
    unittest.main()
