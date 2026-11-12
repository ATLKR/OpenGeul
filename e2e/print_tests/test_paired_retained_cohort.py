"""Real binder call-shape, synthetic Win32 kernel results, no OS processes."""
import ast
import ctypes
from ctypes import wintypes
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

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
