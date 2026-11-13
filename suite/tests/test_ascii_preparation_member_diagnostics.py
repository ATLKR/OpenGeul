"""Read-only native-boundary fakes for a lingering private compiler Job.

The preparation policy, deadline and original cleanup path execute unchanged.
No process, compiler, foreign census or Windows API is invoked by these tests.
"""
import unittest

import test_ascii_message_preparation as base

m = base.m


class DiagnosticApi:
    def __init__(self, clock):
        self.clock = clock
        self.pids = [901]
        self.calls = []
        self.closed = []
        self.opened = []
        self.expire_at = None
        self.fail_at = None
        self.partial = False
        self.membership = [True, True]
        self.image = 'C:\\Tools\\native-child.exe'

    def step(self, name, *values):
        self.calls.append((name, *values))
        if self.expire_at == name:
            self.clock.value = 127.
        if self.fail_at == name:
            raise OSError('diagnostic ' + name + ' failed')

    def job_pids(self, job, *, record, check):
        check()
        self.step('job_pids', job)
        group = dict(schemaVersion=1, kind='private-job-process-census',
                     jobHandleValue=job, capacity=128, maxAttempts=3,
                     classification='failed' if self.partial else 'complete',
                     calls=[dict(classification='incomplete' if self.partial else 'complete',
                                 assigned=len(self.pids) + int(self.partial),
                                 count=len(self.pids), pids=list(self.pids))])
        record(group)
        check()
        if self.partial:
            error = RuntimeError('Private job census remained incomplete')
            error.job_census = group
            raise error
        return list(self.pids)

    def open_process(self, access, inherit, pid):
        self.step('OpenProcess', access, inherit, pid)
        handle = (1 << 40) + pid
        self.opened.append(handle)
        return handle

    def is_in_job(self, handle, job, member):
        self.step('IsProcessInJob', handle, job)
        member._obj.value = self.membership.pop(0) if self.membership else True
        return True

    def query_image(self, handle, flags, text, length):
        self.step('QueryFullProcessImageNameW', handle)
        text.value = self.image
        length._obj.value = len(self.image)
        return True

    def get_times(self, handle, creation, exited, kernel, user):
        self.step('GetProcessTimes', handle)
        value = 134370233752663598
        creation._obj.dwLowDateTime = value & 0xffffffff
        creation._obj.dwHighDateTime = value >> 32
        return True

    def wait_for(self, handle, timeout):
        self.step('WaitForSingleObject', handle, timeout)
        return 258

    def get_exit(self, handle, code):
        self.step('GetExitCodeProcess', handle)
        code._obj.value = 259
        return True

    def close_handle(self, handle):
        self.closed.append(handle)
        self.step('CloseHandle', handle)
        return True


class MemberDiagnosticTests(unittest.TestCase):
    setUp = base.PreparationTests.setUp
    prepare = base.PreparationTests.prepare
    proof = base.PreparationTests.proof

    def lingering(self, states=None):
        self.runtime.states[0] = states or [(0, 1, 0), (0, 1, 0), (0, 0, 0)]
        self.api = self.runtime.diagnostics = DiagnosticApi(self.clock)

    def diagnostic(self):
        stage = self.proof()['stages'][0]
        self.assertIn('remainingMemberDiagnostic', stage)
        return stage['remainingMemberDiagnostic']

    def test_first_lingering_root_sample_collects_once_without_granting_success(self):
        self.lingering()
        self.prepare()
        row = self.diagnostic()
        self.assertEqual([c for c in self.api.calls if c[0] == 'job_pids'], [('job_pids', 60)])
        self.assertEqual(row['triggerSample']['activeProcesses'], 1)
        self.assertEqual(row['triggerSample']['root'], dict(waitResult=0, exitCode=0))
        self.assertTrue(self.proof()['stages'][0]['natural'])
        self.assertEqual(self.proof()['stages'][0]['queryCount'], 3)
        self.assertIs(row['naturalExitProved'], False)
        self.assertEqual(self.api.closed, self.api.opened)

    def test_member_identity_preserves_64bit_handle_creation_and_owned_job(self):
        self.lingering()
        self.prepare()
        row = self.diagnostic()['members'][0]
        self.assertEqual(row['pid'], 901)
        self.assertEqual(row['handleValue'], (1 << 40) + 901)
        self.assertEqual(row['creationTime'], 134370233752663598)
        self.assertEqual(row['image'], self.api.image)
        self.assertEqual(row['membershipBefore']['inOwnedJob'], True)
        self.assertEqual(row['membershipAfter']['inOwnedJob'], True)
        self.assertEqual(row['state'], dict(waitResult=258, exitCode=259))
        self.assertEqual(row['identityScope'], 'newly-retained-diagnostic-samples-only')
        self.assertTrue(row['handleClosed'])
        self.assertIn(('OpenProcess', 0x00101000, False, 901), self.api.calls)

    def test_success_with_zero_job_never_enumerates_members(self):
        self.api = self.runtime.diagnostics = DiagnosticApi(self.clock)
        self.prepare()
        self.assertEqual(self.api.calls, [])
        self.assertTrue(all('remainingMemberDiagnostic' not in r for r in self.proof()['stages']))

    def test_live_root_and_nonempty_job_do_not_trigger_diagnostic(self):
        self.lingering([(258, 1, None), (0, 0, 0)])
        self.prepare()
        self.assertEqual(self.api.calls, [])

    def test_nonzero_root_exit_stays_primary_without_diagnostic(self):
        self.lingering([(0, 1, 3)])
        with self.assertRaisesRegex(AssertionError, 'compiler stage failed'):
            self.prepare()
        self.assertEqual(self.api.calls, [])
        self.assertTrue(self.runtime.processes[0].forced)

    def test_late_accounting_row_does_not_start_new_diagnostic(self):
        self.lingering([(0, 1, 0)])
        self.runtime.late = True
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            self.prepare()
        self.assertEqual(self.api.calls, [])

    def test_eight_complete_members_are_bounded_and_each_handle_is_closed(self):
        self.lingering()
        self.api.pids = list(range(901, 909))
        self.prepare()
        row = self.diagnostic()
        self.assertEqual(len(row['members']), 8)
        self.assertEqual(self.api.closed, self.api.opened)
        self.assertEqual(len(self.api.closed), 8)
        self.assertTrue(all(r['handleClosed'] for r in row['members']))

    def test_complete_overcap_census_is_preserved_without_partial_identity_claim(self):
        self.lingering()
        self.api.pids = list(range(901, 1030))[:128]
        self.prepare()
        row = self.diagnostic()
        self.assertEqual(row['census']['calls'][0]['pids'], self.api.pids)
        self.assertEqual(row['members'], [])
        self.assertIn('8', row['identityOmission'])
        self.assertEqual(self.api.opened, [])
        self.assertIs(row['identityEnumerationComplete'], False)

    def test_partial_census_is_retained_but_never_used_to_open_a_handle(self):
        self.lingering()
        self.api.partial = True
        self.prepare()
        row = self.diagnostic()
        self.assertEqual(row['census']['classification'], 'failed')
        self.assertIn('incomplete', row['error']['message'])
        self.assertEqual(self.api.opened, [])

    def test_budget_expiring_during_open_closes_handle_before_any_member_read(self):
        self.lingering([(0, 1, 0)])
        self.api.expire_at = 'OpenProcess'
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            self.prepare()
        row = self.diagnostic()['members'][0]
        self.assertEqual([c[0] for c in self.api.calls], ['job_pids', 'OpenProcess', 'CloseHandle'])
        self.assertEqual(self.api.closed, self.api.opened)
        self.assertTrue(row['handleClosed'])
        self.assertTrue(self.runtime.processes[0].forced)

    def test_expired_census_opens_no_members_and_keeps_original_timeout(self):
        self.lingering([(0, 1, 0)])
        self.api.expire_at = 'job_pids'
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            self.prepare()
        row = self.diagnostic()
        self.assertEqual(self.api.opened, [])
        self.assertIn('deadline', row['error']['message'])
        self.assertEqual(self.proof()['error']['message'], 'Observer preparation deadline expired')

    def test_diagnostic_getter_failure_does_not_replace_timeout_or_skip_cleanup(self):
        self.lingering([(0, 1, 0)])
        self.api.fail_at = 'GetProcessTimes'
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            self.prepare()
        row = self.diagnostic()['members'][0]
        self.assertIn('GetProcessTimes', row['error']['message'])
        self.assertEqual(self.api.closed, self.api.opened)
        self.assertTrue(self.runtime.processes[0].forced)
        self.assertTrue(self.runtime.processes[0].closed)
        self.assertEqual(self.proof()['error']['message'], 'Observer preparation deadline expired')

    def test_member_leaving_job_is_labelled_racy_without_historical_identity_claim(self):
        self.lingering()
        self.api.membership = [True, False]
        self.prepare()
        row = self.diagnostic()['members'][0]
        self.assertEqual(row['membershipBefore']['inOwnedJob'], True)
        self.assertEqual(row['membershipAfter']['inOwnedJob'], False)
        self.assertEqual(row['classification'], 'racy-or-unavailable')
        self.assertTrue(row['handleClosed'])

    def test_close_failure_is_diagnostic_and_does_not_grant_false_natural_exit(self):
        self.lingering([(0, 1, 0)])
        self.api.fail_at = 'CloseHandle'
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            self.prepare()
        row = self.diagnostic()['members'][0]
        self.assertFalse(row['handleClosed'])
        self.assertIn('CloseHandle', row['closeError']['message'])
        self.assertFalse(self.proof()['stages'][0]['natural'])
        self.assertTrue(self.runtime.processes[0].forced)


if __name__ == '__main__':
    unittest.main()
