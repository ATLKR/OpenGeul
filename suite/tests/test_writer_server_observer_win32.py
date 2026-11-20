"""Portable syscall seams; these tests never execute a Windows process."""
import ctypes as C
import importlib.util
import itertools
from pathlib import Path
import sys
import types
import unittest


SOURCE = Path(__file__).parents[1] / 'e2e' / 'writer_server_observer_win32.py'
if SOURCE.exists():
    sys.path.insert(0, str(SOURCE.parent))
    import writer_server_observer_win32 as M
else:
    M = types.SimpleNamespace()


def integer(value):
    return int(getattr(value, 'value', value) or 0)


class Function:
    def __init__(self, implementation):
        self.implementation = implementation
        self.argtypes = self.restype = None

    def __call__(self, *args):
        return self.implementation(*args)


class Kernel:
    """A typed API seam with private synthetic kernel objects, never OS objects."""
    def __init__(self):
        self.counter = itertools.count(1)
        self.controller, self.job, self.nul, self.host, self.thread = [next(self.counter) for _ in range(5)]
        self.controller_identity = (next(self.counter), next(self.counter))
        self.host_identity = (next(self.counter), next(self.counter))
        self.identities = {self.controller: self.controller_identity, self.host: self.host_identity}
        self.waits = {self.controller: 258, self.host: 258}
        self.last_error = 0
        self.events = []
        self.attributes = {}
        self.closed = []
        self.fail = set()
        self.member_value = True
        self.census_pids = (self.host_identity[0],)
        self.census_assigned = None
        self.frequency = 10_000_000
        self.created = False
        self.duplicated = []
        self.captured_environment = None
        functions = {
            'CreateJobObjectW': self.create_job, 'SetInformationJobObject': self.set_limits,
            'GetHandleInformation': self.handle_information, 'CreateFileW': self.open_nul,
            'InitializeProcThreadAttributeList': self.initialize, 'UpdateProcThreadAttribute': self.update,
            'DeleteProcThreadAttributeList': self.delete, 'CreateProcessW': self.create,
            'ResumeThread': self.resume, 'GetProcessId': self.process_id,
            'GetProcessTimes': self.process_times, 'WaitForSingleObject': self.wait,
            'GetExitCodeProcess': self.exit_code, 'IsProcessInJob': self.member,
            'QueryInformationJobObject': self.census, 'TerminateJobObject': self.terminate,
            'CloseHandle': self.close, 'QueryPerformanceCounter': self.qpc,
            'QueryPerformanceFrequency': self.qpc_frequency, 'OpenProcess': self.open_process,
            'GetCurrentProcess': self.current_process, 'DuplicateHandle': self.duplicate_handle,
        }
        for name, function in functions.items():
            setattr(self, name, Function(function))

    def create_job(self, security, name):
        self.events.append('create-job')
        assert security is None and name is None
        return 0 if 'job' in self.fail else self.job

    def set_limits(self, job, kind, value, size):
        self.events.append('job-limits')
        assert integer(job) == self.job and integer(kind) == 9 and integer(size) == 144
        limits = C.cast(value, C.POINTER(M.ExtendedLimits)).contents
        assert limits.basic.flags == 0x2000
        return 'limits' not in self.fail

    def handle_information(self, handle, flags):
        value = 1 if integer(handle) == self.nul else 0
        if 'job-inherit' in self.fail and integer(handle) == self.job:
            value = 1
        if 'nul-no-inherit' in self.fail and integer(handle) == self.nul:
            value = 0
        C.cast(flags, C.POINTER(C.c_uint32))[0] = value
        return True

    def open_nul(self, name, access, share, security, disposition, flags, template):
        self.events.append('open-nul')
        assert self.CreateFileW.argtypes[1] is C.c_uint32
        assert integer(access) == 0xC0000000 and integer(share) == 3 and integer(disposition) == 3
        assert bytes(C.cast(name, C.POINTER(C.c_uint16))[:4]) == bytes((ord('N'), ord('U'), ord('L'), 0))
        assert C.cast(security, C.POINTER(M.SecurityAttributes)).contents.inherit == 1
        return 0 if 'nul' in self.fail else self.nul

    def initialize(self, address, count, flags, size):
        assert integer(count) == 2 and integer(flags) == 0
        if not address:
            self.last_error = 122
            C.cast(size, C.POINTER(C.c_size_t))[0] = 256
            return False
        self.events.append('initialize-attributes')
        return 'initialize' not in self.fail

    def update(self, address, flags, attribute, value, size, previous, returned):
        key = integer(attribute)
        assert key in (0x2000D, 0x20002) and integer(size) == C.sizeof(C.c_void_p)
        assert integer(flags) == 0 and previous is None and returned is None
        self.events.append('job-list' if key == 0x2000D else 'handle-list')
        if ('job-list' if key == 0x2000D else 'handle-list') in self.fail:
            return False
        self.attributes[key] = integer(C.cast(value, C.POINTER(C.c_void_p))[0])
        return True

    def delete(self, address):
        self.events.append('delete-attributes')
        if 'delete' in self.fail:
            raise RuntimeError('synthetic syscall failure')

    def create(self, application, command, process_security, thread_security, inherit, flags,
               environment, directory, startup, information):
        self.events.append('create-process')
        assert bool(inherit) is True
        assert integer(flags) == 0x08080404
        assert self.attributes == {0x2000D: self.job, 0x20002: self.nul}
        start = C.cast(startup, C.POINTER(M.StartupInfoEx)).contents
        assert start.startup.cb == 112 and start.startup.flags & 0x100
        assert (start.startup.stdin, start.startup.stdout, start.startup.stderr) == (self.nul,) * 3
        assert start.attributes
        buffer = C.cast(environment, C.POINTER(C.c_uint16))
        values = []
        for i in range(4096):
            values.append(buffer[i])
            if i and values[-2:] == [0, 0]:
                break
        self.captured_environment = bytes().join(int(v).to_bytes(2, 'little') for v in values).decode('utf-16-le')
        info = C.cast(information, C.POINTER(M.ProcessInfo)).contents
        if 'create' not in self.fail or 'partial-create' in self.fail:
            info.process, info.thread = self.host, self.thread
            if 'missing-process-handle' in self.fail:
                info.process = None
            info.pid, info.tid = self.host_identity[0], next(self.counter)
            self.created = True
        return 'create' not in self.fail

    def resume(self, thread):
        self.events.append('resume')
        assert integer(thread) == self.thread
        return 0xFFFFFFFF if 'resume' in self.fail else 1

    def process_id(self, handle):
        if integer(handle) == C.c_void_p(-1).value:
            return 0 if 'current-pid-zero' in self.fail else self.controller_identity[0]
        return self.identities[integer(handle)][0]

    def process_times(self, handle, created, exited, kernel, user):
        value = self.identities[integer(handle)][1]
        if 'controller-changed' in self.fail and integer(handle) == self.controller and self.created:
            value += 1
        result = C.cast(created, C.POINTER(M.FileTime)).contents
        result.low, result.high = value & 0xFFFFFFFF, value >> 32
        return 'times' not in self.fail

    def wait(self, handle, milliseconds):
        assert integer(milliseconds) == 0
        return 0xFFFFFFFF if 'wait' in self.fail else self.waits[integer(handle)]

    def exit_code(self, handle, value):
        C.cast(value, C.POINTER(C.c_uint32))[0] = 259 if self.waits[integer(handle)] == 258 else 0
        return 'exit-code' not in self.fail

    def member(self, handle, job, result):
        self.events.append('membership')
        C.cast(result, C.POINTER(C.c_int32))[0] = self.member_value and integer(job) == self.job
        return 'member-api' not in self.fail

    def census(self, job, kind, value, size, returned):
        self.events.append('census')
        assert integer(job) == self.job and integer(kind) == 3
        result = C.cast(value, C.POINTER(M.JobPidList)).contents
        result.assigned = len(self.census_pids) if self.census_assigned is None else self.census_assigned
        result.count = len(self.census_pids)
        for i, value in enumerate(self.census_pids):
            result.pids[i] = value
        C.cast(returned, C.POINTER(C.c_uint32))[0] = M.JobPidList.pids.offset + len(self.census_pids) * C.sizeof(C.c_size_t)
        return 'census' not in self.fail

    def terminate(self, job, code):
        self.events.append('terminate-job')
        assert integer(job) == self.job
        return 'terminate' not in self.fail

    def close(self, handle):
        self.events.append('close')
        if 'close-nul' in self.fail and integer(handle) == self.nul:
            return False
        if 'close-member' in self.fail and integer(handle) == self.host:
            return False
        if 'close-duplicate' in self.fail and integer(handle) in self.duplicated:
            return False
        self.closed.append(integer(handle))
        return True

    def qpc(self, result):
        C.cast(result, C.POINTER(C.c_int64))[0] = next(self.counter)
        return True

    def qpc_frequency(self, result):
        C.cast(result, C.POINTER(C.c_int64))[0] = self.frequency
        return True

    def open_process(self, rights, inherit, pid):
        self.events.append('open-initial-member')
        assert integer(rights) == 0x00101000 and not inherit and integer(pid) == self.host_identity[0]
        return self.host

    def current_process(self):
        return C.c_void_p(-1).value

    def duplicate_handle(self, source, original, target, result, rights, inherit, options):
        self.events.append('duplicate-controller')
        assert integer(source) == integer(original) == integer(target) == C.c_void_p(-1).value
        assert integer(rights) == 0x00101000 and not inherit and integer(options) == 0
        if 'duplicate' not in self.fail or 'duplicate-partial' in self.fail:
            handle = next(self.counter)
            self.duplicated.append(handle)
            self.identities[handle] = self.controller_identity
            self.waits[handle] = 258
            C.cast(result, C.POINTER(C.c_void_p))[0] = handle
        if 'duplicate-raises-after-write' in self.fail:
            raise RuntimeError('synthetic syscall failure')
        return 'duplicate' not in self.fail


class Win32LifecycleTests(unittest.TestCase):
    def test_reimporting_test_fixture_keeps_canonical_module_and_owned_launch_identity(self):
        original=sys.modules['writer_server_observer_win32']
        owned=original.OwnedLaunch
        alias='_writer_win32_test_identity_probe'
        try:
            spec=importlib.util.spec_from_file_location(alias,Path(__file__))
            probe=importlib.util.module_from_spec(spec)
            sys.modules[alias]=probe
            spec.loader.exec_module(probe)
            self.assertIs(sys.modules['writer_server_observer_win32'],original)
            self.assertIs(probe.M,original)
            self.assertIs(probe.M.OwnedLaunch,owned)
        finally:sys.modules.pop(alias,None)

    def setup_api(self):
        self.assertTrue(callable(getattr(M, 'NativeApi', None)), 'NativeApi missing')
        kernel = Kernel()
        return M.NativeApi(kernel=kernel, last_error=lambda: kernel.last_error), kernel

    def launch(self, api, kernel, environment=None):
        return api.launch((r'C:\diagnostic\Office.exe',), r'C:\diagnostic',
                          {'PATH': r'C:\diagnostic'} if environment is None else environment,
                          controller_binding=(kernel.controller, kernel.controller_identity, object()))

    def controller_factory(self, api):
        factory = getattr(api, 'retain_current_controller', None)
        self.assertTrue(callable(factory), 'Controller retained-HANDLE factory missing')
        return factory()

    def test_controller_factory_duplicates_current_object_without_pid_open(self):
        api, kernel = self.setup_api()
        handle, identity = self.controller_factory(api)
        self.assertTrue(handle and handle != C.c_void_p(-1).value)
        self.assertEqual(identity, kernel.controller_identity)
        self.assertEqual(kernel.events, ['duplicate-controller'])
        self.assertFalse(kernel.closed)

    def test_controller_factory_partial_duplicate_close_failure_retains_resource(self):
        api, kernel = self.setup_api();kernel.fail.update(('duplicate', 'duplicate-partial', 'close-duplicate'))
        self.assertTrue(callable(getattr(api, 'retain_current_controller', None)), 'Controller factory missing')
        with self.assertRaises(M.NativeCallError) as caught:api.retain_current_controller()
        self.assertTrue(caught.exception.retained_handle)
        self.assertNotIn('open-initial-member', kernel.events)

    def test_controller_factory_identity_failure_releases_duplicate(self):
        api, kernel = self.setup_api();kernel.fail.add('times')
        self.assertTrue(callable(getattr(api, 'retain_current_controller', None)), 'Controller factory missing')
        with self.assertRaises(M.NativeCallError) as caught:api.retain_current_controller()
        self.assertIsNone(caught.exception.retained_handle)
        self.assertTrue(kernel.duplicated and kernel.duplicated[0] in kernel.closed)

    def test_controller_factory_exception_after_output_keeps_failed_close_handle(self):
        api, kernel = self.setup_api();kernel.fail.update(('duplicate-raises-after-write', 'close-duplicate'))
        with self.assertRaises(M.NativeCallError) as caught:api.retain_current_controller()
        self.assertTrue(caught.exception.retained_handle)

    def test_creation_job_list_and_nul_handle_list_precede_verified_resume(self):
        api, kernel = self.setup_api()
        owned = self.launch(api, kernel)
        self.assertFalse(owned.failed)
        self.assertTrue(owned.resumed and owned.creation_job_membership and owned.pre_resume_verified)
        self.assertLess(kernel.events.index('job-list'), kernel.events.index('create-process'))
        self.assertLess(kernel.events.index('membership'), kernel.events.index('resume'))
        self.assertEqual(kernel.closed, [kernel.nul])
        self.assertTrue(owned.local_cleanup_complete)

    def test_foreign_job_stops_before_resume_and_preserves_partial_handles(self):
        api, kernel = self.setup_api();kernel.member_value = False
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertFalse(owned.resumed or owned.pre_resume_verified)
        self.assertTrue(owned.host and owned.thread and owned.job)
        self.assertNotIn('resume', kernel.events)

    def test_controller_generation_change_is_rejected_before_resume(self):
        api, kernel = self.setup_api();kernel.fail.add('controller-changed')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertNotIn('resume', kernel.events)

    def test_foreign_live_controller_is_rejected_before_job_creation(self):
        api, kernel = self.setup_api()
        foreign = next(kernel.counter)
        identity = (next(kernel.counter), next(kernel.counter))
        kernel.identities[foreign], kernel.waits[foreign] = identity, 258
        owned = api.launch((r'C:\diagnostic\Office.exe',), r'C:\diagnostic',
            {'PATH': r'C:\diagnostic'}, controller_binding=(foreign, identity, object()))
        self.assertTrue(owned.failed)
        self.assertEqual(owned.failure_code, M.FailureCode.CONTROLLER_IDENTITY)
        self.assertNotIn('create-job', kernel.events)
        self.assertNotIn('resume', kernel.events)

    def test_missing_current_process_identity_is_unknown_before_job_creation(self):
        api, kernel = self.setup_api();kernel.fail.add('current-pid-zero')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertNotIn('create-job', kernel.events)
        self.assertNotIn('resume', kernel.events)

    def test_unknown_environment_key_is_not_inherited(self):
        api, kernel = self.setup_api()
        owned = self.launch(api, kernel, {'PATH': r'C:\diagnostic', 'SYNTHETIC_SECRET_TOKEN': 'synthetic-sentinel'})
        self.assertTrue(owned.failed)
        self.assertNotIn('create-process', kernel.events)
        self.assertIsNone(kernel.captured_environment)

    def test_environment_is_explicit_unicode_double_terminated(self):
        api, kernel = self.setup_api()
        self.assertFalse(self.launch(api, kernel).failed)
        self.assertEqual(kernel.captured_environment, 'PATH=C:\\diagnostic\0\0')

    def test_partial_create_failure_keeps_original_handles_and_uncertain_flag(self):
        api, kernel = self.setup_api();kernel.fail.update(('create', 'partial-create'))
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed and owned.uncertain)
        self.assertTrue(owned.host and owned.thread and owned.job)
        self.assertNotIn('resume', kernel.events)

    def test_success_without_process_handle_is_uncertain_partial_creation(self):
        api, kernel = self.setup_api();kernel.fail.add('missing-process-handle')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed and owned.uncertain)
        self.assertTrue(owned.thread and owned.job)
        self.assertEqual(owned.failure_code, M.FailureCode.CREATE_PROCESS)
        self.assertNotIn('resume', kernel.events)

    def test_job_creation_failure_is_not_reported_as_invalid_input(self):
        api, kernel = self.setup_api();kernel.fail.add('job')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertEqual(owned.failure_code, M.FailureCode.CREATE_JOB)

    def test_stdio_creation_failure_is_not_reported_as_invalid_input(self):
        api, kernel = self.setup_api();kernel.fail.add('nul')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertEqual(owned.failure_code, M.FailureCode.STDIO)

    def test_resume_failure_does_not_drop_original_handles(self):
        api, kernel = self.setup_api();kernel.fail.add('resume')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed and owned.uncertain)
        self.assertFalse(owned.resumed)
        self.assertTrue(owned.host and owned.thread and owned.job)

    def test_attribute_failure_has_no_create_or_assign_fallback(self):
        api, kernel = self.setup_api();kernel.fail.add('job-list')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed and owned.job)
        self.assertNotIn('create-process', kernel.events)
        self.assertIn('delete-attributes', kernel.events)
        self.assertIn(kernel.nul, kernel.closed)

    def test_attribute_cleanup_failure_does_not_skip_stdio_release(self):
        api, kernel = self.setup_api();kernel.fail.add('delete')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertFalse(owned.local_cleanup_complete)
        self.assertIn(kernel.nul, kernel.closed)

    def test_stdio_close_failure_is_incomplete_and_retains_resource(self):
        api, kernel = self.setup_api();kernel.fail.add('close-nul')
        owned = self.launch(api, kernel)
        self.assertTrue(owned.failed)
        self.assertFalse(owned.local_cleanup_complete)
        self.assertTrue(owned.stdio)

    def test_inherited_job_or_noninheritable_nul_fails_closed(self):
        for failure in ('job-inherit', 'nul-no-inherit'):
            with self.subTest(failure=failure):
                api, kernel = self.setup_api();kernel.fail.add(failure)
                self.assertTrue(self.launch(api, kernel).failed)
                self.assertNotIn('create-process', kernel.events)

    def test_retained_state_is_zero_wait_and_checks_exit_result(self):
        api, kernel = self.setup_api()
        self.assertEqual(api.state(kernel.host), (258, 259))
        kernel.waits[kernel.host] = 0
        self.assertEqual(api.state(kernel.host), (0, 0))
        kernel.fail.add('exit-code')
        with self.assertRaises(M.NativeCallError):api.state(kernel.host)

    def test_invalid_wait_is_unknown_not_retired(self):
        api, kernel = self.setup_api();kernel.fail.add('wait')
        with self.assertRaises(M.NativeCallError):api.state(kernel.host)

    def test_census_requires_complete_single_read(self):
        api, kernel = self.setup_api();kernel.census_pids = ()
        self.assertEqual(api.census(kernel.job), ())
        kernel.census_assigned = 1
        with self.assertRaises(M.NativeCallError):api.census(kernel.job)
        self.assertEqual(kernel.events.count('census'), 2)

    def test_initial_member_retains_readonly_handle_and_rejects_foreign_job(self):
        api, kernel = self.setup_api()
        self.assertTrue(api.open_initial_member(kernel.host_identity[0], kernel.job))
        kernel.member_value = False
        with self.assertRaises(M.NativeCallError):api.open_initial_member(kernel.host_identity[0], kernel.job)
        self.assertIn(kernel.host, kernel.closed)

    def test_initial_member_close_failure_preserves_private_handle(self):
        api, kernel = self.setup_api();kernel.member_value = False;kernel.fail.add('close-member')
        with self.assertRaises(M.NativeCallError) as caught:api.open_initial_member(kernel.host_identity[0], kernel.job)
        self.assertTrue(caught.exception.retained_handle)

    def test_identity_and_qpc_reject_invalid_native_evidence(self):
        api, kernel = self.setup_api()
        self.assertEqual(api.identity(kernel.host), kernel.host_identity)
        self.assertGreater(api.qpc_read(), 0)
        self.assertEqual(api.qpc_frequency(), 10_000_000)
        kernel.frequency = 0
        with self.assertRaises(M.NativeCallError):api.qpc_frequency()
        kernel.fail.add('times')
        with self.assertRaises(M.NativeCallError):api.identity(kernel.host)

    def test_termination_permission_failure_is_false_without_alternate_kill(self):
        api, kernel = self.setup_api();kernel.fail.add('terminate')
        self.assertFalse(api.terminate_job(kernel.job))
        self.assertEqual(kernel.events, ['terminate-job'])

    def test_private_resources_have_no_identity_repr(self):
        api, kernel = self.setup_api();owned = self.launch(api, kernel)
        self.assertEqual(repr(owned), '<OwnedLaunch private>')
        error = M.NativeCallError(M.FailureCode.NATIVE_CALL, retained_handle=kernel.host)
        self.assertNotIn(str(kernel.host), repr(error))


if __name__ == '__main__':
    unittest.main()
