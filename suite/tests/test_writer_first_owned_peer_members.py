"""Closed first-admission snapshot under the real RetainedCohort guard."""
import tempfile
import unittest

import test_writer_first_owned_peer_profile as profile_fixture


class FirstPeerMembers(unittest.TestCase):
    def tearDown(self):
        profile_fixture.runner._PENDING_CASES.clear()
        profile_fixture.runner._CASE_STARTED = False

    def fixture(self, folder, *, opt_in=True, console=False):
        x = profile_fixture.FirstOwnedPeerProfile().fixture(folder, profile=opt_in)
        if not console:
            x.obj.console_profile = None
            census = x.api.census
            x.api.census = lambda job: tuple(pid for pid in census(job) if pid != 501)
        return x

    def assert_rejected_before_runtime(self, report, x):
        self.assertEqual(report['failureCode'], 13)
        self.assertNotIn('admitted', x.events)
        self.assertEqual(x.events.count('admit-attempt'), 1)
        self.assertEqual(len(x.peers), 1)
        self.assertEqual(report['preparation']['inputCount'], 0)
        self.assertIsNone(report['preparation']['runtimeEntered'])
        self.assertIsNone(report['runtime']['runtime_started'])
        self.assertGreater(report['pendingRetainedCount'], 0)
        self.assertIsNot(report['preparation']['cleanupComplete'], True)

    def test_console_free_opt_in_rejects_a_new_unknown_member_after_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            identity, member, state, opened, census = (
                x.api.identity, x.api.member, x.api.state, x.api.open_initial_member, x.api.census)
            x.api.identity = lambda h: (999, 1999) if h == 309 else identity(h)
            x.api.member = lambda h, job: job == 1000 if h == 309 else member(h, job)
            x.api.state = lambda h: ((0, 0) if x.api.dead else (258, 259)) if h == 309 else state(h)
            unknown_opens = []
            def open_member(pid, job):
                if pid == 999:
                    unknown_opens.append(pid)
                    return 309
                return opened(pid, job)
            x.api.open_initial_member = open_member
            x.hooks.before_admit = lambda: setattr(x.api, 'census', lambda job: (*census(job), 999) if job == 1000 and not x.api.dead else census(job))
            report = x.obj.execute(x.inputs)
        self.assert_rejected_before_runtime(report, x)
        self.assertEqual(unknown_opens, [])

    def test_console_free_opt_in_rejects_a_classified_launcher_disappearing_after_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            census = x.api.census
            x.hooks.before_admit = lambda: setattr(x.api, 'census', lambda job: tuple(pid for pid in census(job) if pid != 601))
            report = x.obj.execute(x.inputs)
        self.assert_rejected_before_runtime(report, x)

    def test_console_free_opt_in_rejects_recycled_launcher_birth_after_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            identity = x.api.identity
            x.hooks.before_admit = lambda: setattr(x.api, 'identity', lambda h: (601, 999) if h == 305 else identity(h))
            report = x.obj.execute(x.inputs)
        self.assert_rejected_before_runtime(report, x)

    def test_same_pid_and_birth_with_wrong_original_job_membership_still_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            member = x.api.member
            x.hooks.before_admit = lambda: setattr(x.api, 'member', lambda h, job: False if h == 305 else member(h, job))
            report = x.obj.execute(x.inputs)
        self.assert_rejected_before_runtime(report, x)

    def test_console_free_opt_in_keeps_a_legal_exact_current_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertEqual(x.cohorts[0]._expected_members, ((101, 111), (301, 311), (601, 611), (401, 501)))
        self.assertIsNone(x.cohorts[0].auxiliary)
        self.assertFalse(x.cohorts[0]._require_all_exit)
        self.assertEqual(report['preparation']['inputCount'], 0)
        self.assertFalse(report['normalAcceptance'])

    def test_console_opt_in_keeps_the_original_auxiliary_and_all_exit_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder, console=True)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertEqual(set(x.cohorts[0]._expected_members), {(101, 111), (301, 311), (601, 611), (401, 501), (501, 511)})
        self.assertEqual((x.cohorts[0].auxiliary.pid, x.cohorts[0].auxiliary.birth), (501, 511))
        self.assertTrue(x.cohorts[0]._require_all_exit)

    def test_console_free_default_keeps_the_original_empty_options(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder, opt_in=False)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertIsNone(x.cohorts[0]._expected_members)
        self.assertIsNone(x.cohorts[0].auxiliary)
        self.assertFalse(x.cohorts[0]._require_all_exit)


if __name__ == '__main__': unittest.main()
