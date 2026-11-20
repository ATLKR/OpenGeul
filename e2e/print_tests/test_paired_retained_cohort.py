"""Real binder call-shape, synthetic Win32 kernel results, no OS processes."""
import ast
import ctypes
import contextlib
import json
from ctypes import wintypes
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'paired_print_diagnostic.py'
sys.path.insert(0, str(FILE.parent))
spec = importlib.util.spec_from_file_location('paired_retained_candidate', FILE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class Function:
    def __init__(self, call): self.call = call
    def __call__(self, *args): return self.call(*args)


class Kernel:
    def __init__(self):
        self.pid = {99: 1}
        self.created = {99: 101}
        self.state = {99: 258}
        self.opened = []
        self.closed = []
        self.waited = []
        self.wrong_sync_generation = False
        self.OpenProcess = Function(self.open)
        self.CloseHandle = Function(lambda handle: self.closed.append(handle) is None)
        self.GetProcessId = Function(lambda handle: self.pid[handle])
        self.GetProcessTimes = Function(self.times)
        self.WaitForSingleObject = Function(self.wait)

    def open(self, rights, inherit, pid):
        self.opened.append((rights, inherit, pid))
        handle = 1000 + pid
        self.pid[handle] = pid
        self.created[handle] = 100 + pid + (1 if self.wrong_sync_generation else 0)
        self.state[handle] = 258
        return handle

    def wait(self, handle, milliseconds):
        self.waited.append(handle)
        if handle >= 10000: return 0xffffffff  # QUERY-only is not waitable.
        return self.state[handle]

    def times(self, handle, created, exited, kernel, user):
        created._obj.dwLowDateTime = self.created[handle]
        created._obj.dwHighDateTime = 0
        return True


class Focus:
    def __init__(self):
        self.ctypes = ctypes
        self.W = wintypes
        self.kernel = Kernel()
        self.rows = [{'processId': 1, 'parentProcessId': 200, 'executableName': 'OpenGeul.exe'},
                     {'processId': 2, 'parentProcessId': 1, 'executableName': 'msedgewebview2.exe'},
                     {'processId': 3, 'parentProcessId': 2, 'executableName': 'msedgewebview2.exe'},
                     {'processId': 4, 'parentProcessId': 1, 'executableName': 'msedgewebview2.exe'}]
        self.snapshot_error = None
        self.process = SimpleNamespace(api=self.kernel, processes=self.processes)
        self.handles = {}

    def processes(self):
        if self.snapshot_error is not None: raise self.snapshot_error
        return self.rows

    def bind_process(self, pid, expected, handle=None):
        if pid in self.handles: return self.handles[pid][2]
        own = handle is None
        handle = 10000 + pid if own else handle
        self.kernel.pid[handle] = pid
        self.kernel.created[handle] = 100 + pid
        self.kernel.state[handle] = 258
        record = {'pid': pid, 'creation': 100 + pid, 'session': 1}
        if 'parentProcessId' in expected: record['parentProcessId'] = expected['parentProcessId']
        self.handles[pid] = (handle, own, record, expected)
        return record

    def verify_process(self, pid, expected):
        assert self.kernel.state[self.handles[pid][0]] == 258

    def _times_session(self, pid, handle):
        return {'pid': pid, 'creation': self.kernel.created[handle], 'session': 1}

    def close(self):
        for handle, own, *_ in self.handles.values():
            if own: self.kernel.CloseHandle(handle)
        self.handles.clear()


class RetainedCohortTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(api, 'RetainedLease', None)), 'retained native cohort adapter is absent')
        tree = ast.parse((ROOT / 'print_focus.py').read_bytes())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_bind_native_print_processes')
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'actual-print-binder', 'exec'), namespace)
        self.binder = namespace['_bind_native_print_processes']
        self.focus = Focus()
        self.session = SimpleNamespace(proc=SimpleNamespace(pid=1, _handle=99))
        app = {'processId': 1, 'architecture': 'x64'}
        web = [{'processId': 3, 'parentProcessId': 2}, {'processId': 2, 'parentProcessId': 1}, {'processId': 4, 'parentProcessId': 1}]
        self.runtime = {'nativeArchitecture': app, 'webview2Native': {'rootProcessId': 1, 'processes': web}}

    def lease(self, **kw):
        lease = api.RetainedLease(self.session, self.runtime, probe=self.focus, binder=self.binder, **kw)
        self.addCleanup(lease.close)
        return lease

    def stopped(self):
        for handle in self.focus.kernel.state: self.focus.kernel.state[handle] = 0
        self.focus.rows = [{'processId': 200, 'parentProcessId': 0, 'executableName': 'controller.exe'}]

    def test_all_known_webviews_get_new_synchronize_handles(self):
        lease = self.lease()
        self.assertEqual({pid for _, _, pid in self.focus.kernel.opened}, {2, 3, 4})
        self.assertTrue(all(rights == 0x101000 and inherit is False for rights, inherit, _ in self.focus.kernel.opened))
        self.assertFalse(any(handle >= 10000 for handle in self.focus.kernel.waited))
        self.assertEqual(lease.retained_count, 4)

    def test_root_popen_handle_is_not_reopened_or_closed(self):
        lease = self.lease()
        lease.close()
        self.assertNotIn(99, self.focus.kernel.closed)
        self.assertNotIn(1, [pid for _, _, pid in self.focus.kernel.opened])

    def test_sync_handle_generation_must_match_the_original_live_query(self):
        self.focus.kernel.wrong_sync_generation = True
        with self.assertRaises(api.Rejected): self.lease()
        self.assertTrue(self.focus.kernel.closed)

    def test_sealed_cohort_retirement_uses_the_original_handles(self):
        lease = self.lease()
        self.assertFalse(lease.__exit__(None, None, None))
        self.stopped()
        result = lease.wait_retired()
        self.assertEqual(result, {'retainedRootExited': True, 'retainedWebviewCount': 3, 'retainedWebviewsExited': True})

    def test_no_before_cleanup_census_means_unknown(self):
        lease = self.lease()
        self.stopped()
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_new_descendant_before_cleanup_is_not_adopted(self):
        lease = self.lease()
        self.focus.rows.append({'processId': 5, 'parentProcessId': 1, 'executableName': 'msedgewebview2.exe'})
        lease.__exit__(None, None, None)
        self.stopped()
        with self.assertRaises(api.Rejected): lease.wait_retired()
        self.assertNotIn(5, [pid for _, _, pid in self.focus.kernel.opened])

    def test_new_descendant_during_shutdown_blocks_next_role(self):
        lease = self.lease()
        lease.__exit__(None, None, None)
        self.stopped()
        self.focus.rows.append({'processId': 5, 'parentProcessId': 2, 'executableName': 'msedgewebview2.exe'})
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_unexpected_census_keeps_numeric_roles_and_original_rejection(self):
        lease = self.lease()
        self.focus.rows += [
            {'processId': 5, 'parentProcessId': 1, 'executableName': 'msedgewebview2.exe'},
            {'processId': 6, 'parentProcessId': 5, 'executableName': 'conhost.exe'},
            {'processId': 7, 'parentProcessId': 3, 'executableName': 'werfault.exe'},
            {'processId': 8, 'parentProcessId': 1, 'executableName': 'SYNTHETIC-PRIVATE-NAME'}]
        opened = list(self.focus.kernel.opened)
        with mock.patch.object(self.focus.process, 'processes', wraps=self.focus.process.processes) as snapshots:
            lease.__exit__(None, None, None)
        self.assertEqual(snapshots.call_count, 1)
        error = lease.checkpoint_error
        self.assertIs(type(error), api.Rejected)
        self.assertEqual(error.code, 15)
        record = getattr(error, 'pairedCensusObservation', None)
        self.assertIs(type(record), dict)
        self.assertEqual(record, {'schemaVersion': 1, 'diagnosticOnly': True, 'acceptanceEligible': False,
            'rootPid': 1, 'originalRootCreationFileTime': 101, 'sealed': True, 'requireLiveRoot': True,
            'snapshotCount': 8, 'knownCount': 4, 'guardUnexpectedCount': 4, 'rootSnapshotReachableCount': 4,
            'rows': [{'pid': 5, 'parentPid': 1, 'executableRoleCode': 1},
                     {'pid': 6, 'parentPid': 5, 'executableRoleCode': 2},
                     {'pid': 7, 'parentPid': 3, 'executableRoleCode': 3},
                     {'pid': 8, 'parentPid': 1, 'executableRoleCode': 0}]})
        self.assertNotIn('SYNTHETIC', json.dumps(record))
        self.assertEqual(self.focus.kernel.opened, opened)
        self.assertEqual(set(lease.handles), {1, 2, 3, 4})
        self.stopped()
        with self.assertRaises(api.Rejected) as caught: lease.wait_retired()
        self.assertIs(caught.exception, error)
        lease.close()
        self.assertEqual(sorted(self.focus.kernel.closed), [1002, 1003, 1004, 10002, 10003, 10004])

    def test_known_seed_child_is_not_claimed_root_snapshot_reachable(self):
        lease = self.lease()
        self.focus.rows[1]['parentProcessId'] = 200
        self.focus.rows.append({'processId': 5, 'parentProcessId': 2, 'executableName': 'conhost.exe'})
        lease.__exit__(None, None, None)
        record = getattr(lease.checkpoint_error, 'pairedCensusObservation', None)
        self.assertIs(type(record), dict)
        self.assertEqual(record['guardUnexpectedCount'], 1)
        self.assertEqual(record['rootSnapshotReachableCount'], 0)
        self.assertEqual(record['rows'], [])

    def test_snapshot_name_enum_never_extracts_a_basename_or_coerces_objects(self):
        class Opaque:
            def __str__(self): raise AssertionError()
            def __repr__(self): raise AssertionError()
        for name in (None, 1, Opaque(), 'x'*261, 'C:/conhost.exe', 'conhost.exe ', 'wеrfault.exe', 'WerFаult.exe'):
            with self.subTest(nameType=type(name).__name__):
                self.focus = Focus();lease = self.lease()
                self.focus.rows.append({'processId': 5, 'parentProcessId': 1, 'executableName': name})
                lease.__exit__(None, None, None)
                record = getattr(lease.checkpoint_error, 'pairedCensusObservation', None)
                self.assertIs(type(record), dict)
                self.assertEqual(record['rows'], [{'pid': 5, 'parentPid': 1, 'executableRoleCode': 0}])
                self.assertEqual(set(record['rows'][0]), {'pid','parentPid','executableRoleCode'})
                lease.close()

    def test_exact_ascii_case_variants_keep_the_closed_executable_role(self):
        for name, role in (('WerFault.exe', 3), ('wErFaUlT.eXe', 3), ('CONHOST.EXE', 2), ('MSEDGEWEBVIEW2.EXE', 1)):
            with self.subTest(role=role):
                self.focus = Focus();lease = self.lease()
                self.focus.rows.append({'processId': 5, 'parentProcessId': 1, 'executableName': name})
                lease.__exit__(None, None, None)
                record = getattr(lease.checkpoint_error, 'pairedCensusObservation', None)
                self.assertIs(type(record), dict)
                self.assertEqual(record['rows'], [{'pid': 5, 'parentPid': 1, 'executableRoleCode': role}])
                lease.close()

    def test_shutdown_census_record_does_not_claim_a_new_live_generation(self):
        lease = self.lease();lease.__exit__(None, None, None);self.stopped()
        self.focus.rows.append({'processId': 5, 'parentProcessId': 2, 'executableName': 'conhost.exe'})
        opened = list(self.focus.kernel.opened)
        with self.assertRaises(api.Rejected) as caught: lease.wait_retired()
        record = getattr(caught.exception, 'pairedCensusObservation', None)
        self.assertIs(type(record), dict)
        self.assertEqual(caught.exception.code, 15)
        self.assertTrue(record['sealed']);self.assertFalse(record['requireLiveRoot'])
        self.assertEqual(record['originalRootCreationFileTime'], 101)
        self.assertEqual((record['guardUnexpectedCount'], record['rootSnapshotReachableCount']), (1, 0))
        self.assertNotIn('rootLiveState', record)
        self.assertEqual(self.focus.kernel.opened, opened)

    def test_census_observation_fault_cannot_replace_original_guard(self):
        for failure in (MemoryError(), KeyboardInterrupt(), SystemExit()):
            with self.subTest(faultType=type(failure).__name__):
                self.focus = Focus()
                lease = self.lease()
                self.focus.rows.append({'processId': 5, 'parentProcessId': 1, 'executableName': 'conhost.exe'})
                original = api.require; captured = []
                def guard(condition, code=1):
                    try: return original(condition, code)
                    except api.Rejected as error:
                        if code == 15: captured.append(error)
                        raise
                with mock.patch.object(api, '_observe_census_failure', side_effect=failure, create=True) as observe, \
                     mock.patch.object(api, 'require', guard):
                    lease.__exit__(None, None, None)
                self.assertEqual(observe.call_count, 1)
                self.assertEqual(len(captured), 1)
                self.assertIs(lease.checkpoint_error, captured[0])
                self.assertEqual(captured[0].code, 15)
                self.stopped()
                with self.assertRaises(api.Rejected) as caught: lease.wait_retired()
                self.assertIs(caught.exception, captured[0])
                lease.close()

    def test_census_failure_keeps_existing_operation_primary_and_blocks_next_role(self):
        lease = self.lease(); primary = ValueError(); roles = []
        self.focus.rows.append({'processId': 5, 'parentProcessId': 1, 'executableName': 'conhost.exe'})
        def printer(*args, admission):
            observed = admission(self.session, args[3])
            with contextlib.ExitStack() as stack:
                stack.callback(self.stopped)
                stack.push(observed)
                raise primary
        with self.assertRaises(ValueError) as caught:
            for role in (1, 2):
                roles.append(role)
                api.invoke_print(printer, Path('editor'), Path('fixture'), {}, Path('fresh'),
                                 lambda session, folder: lease, lambda error: error is primary)
        self.assertIs(caught.exception, primary)
        self.assertEqual(roles, [1])
        self.assertIs(type(lease.checkpoint_error), api.Rejected)
        self.assertIs(getattr(primary, 'pairedCensusObservation', None),
                      getattr(lease.checkpoint_error, 'pairedCensusObservation', object()))
        self.assertTrue(lease.closed)

    def test_incomplete_census_exception_is_not_erased(self):
        lease = self.lease()
        primary = OSError()
        self.focus.snapshot_error = primary
        self.assertFalse(lease.__exit__(None, None, None))
        self.stopped()
        with self.assertRaises(OSError) as caught: lease.wait_retired()
        self.assertIs(caught.exception, primary)

    def test_wait_failed_cannot_be_labelled_exit(self):
        lease = self.lease()
        lease.__exit__(None, None, None)
        self.stopped()
        self.focus.kernel.state[1002] = 0xffffffff
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_post_exit_creation_is_checked_against_the_held_generation(self):
        lease = self.lease()
        lease.__exit__(None, None, None)
        self.stopped()
        self.focus.kernel.created[1002] += 1
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_duplicate_snapshot_pid_is_not_complete(self):
        lease = self.lease()
        self.focus.rows.append(dict(self.focus.rows[0]))
        lease.__exit__(None, None, None)
        self.stopped()
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_live_captured_webview_missing_from_census_is_unknown(self):
        lease = self.lease()
        self.focus.rows = [row for row in self.focus.rows if row['processId'] != 3]
        lease.__exit__(None, None, None)
        self.stopped()
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_late_completed_snapshot_does_not_bypass_retirement_deadline(self):
        values = iter([0.0, 11.0])
        lease = self.lease(clock=lambda: next(values))
        lease.__exit__(None, None, None)
        self.stopped()
        with self.assertRaises(api.Rejected): lease.wait_retired()

    def test_regressing_clock_aborts_before_another_snapshot(self):
        calls = []
        values = iter([10.0, 9.0, 1000.0])
        def clock():
            calls.append(True)
            return next(values)
        lease = self.lease(clock=clock, sleeper=lambda seconds: None)
        lease.__exit__(None, None, None)
        with self.assertRaises(api.Rejected): lease.wait_retired()
        self.assertEqual(len(calls), 2)

    def test_held_process_timeout_stays_bounded_without_killing(self):
        now = [0.0]
        lease = self.lease(clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
        lease.__exit__(None, None, None)
        with self.assertRaises(api.Rejected): lease.wait_retired()
        self.assertLessEqual(now[0], 10.1)


if __name__ == '__main__': unittest.main()
