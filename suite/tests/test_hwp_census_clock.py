"""Native HWP census clock/ownership receipts, using only fake Win32 calls."""
from contextlib import ExitStack
import copy
import ctypes
import importlib.util
import inspect
from pathlib import Path, PureWindowsPath
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e/lifecycle_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_hwp_precise_census_policy', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)

BASE = 1 << 32
SHELL_PID = 31
SHELL_CREATED = BASE + 100
SNAPSHOT_TIME = BASE + 1000
EXECUTABLE = Path('/owned/OpenGeul.exe').resolve()


def split_filetime(value):
    return {'low': value & 0xffffffff, 'high': value >> 32, 'fileTime': value}


def row(pid=108, parent=SHELL_PID, *, name='OpenGeul.exe', image=None, created=BASE + 500):
    return {'pid': pid, 'parent': parent, 'name': name,
            'image': str(EXECUTABLE if image is None else image), 'created': created}


class Function:
    def __init__(self, operation):
        self.operation = operation

    def __call__(self, *args):
        return self.operation(*args)


class Kernel:
    def __init__(self, rows=None, *, precise=SNAPSHOT_TIME, failed=None):
        self.rows = [row()] if rows is None else rows
        self.precise, self.failed = precise, failed
        self.error, self.position = 0, -1
        self.calls, self.opened, self.closed = [], [], []
        self.GetSystemTimeAsFileTime = Function(lambda p: self.clock(p, SHELL_CREATED - 10, 'coarse'))
        self.GetSystemTimePreciseAsFileTime = Function(lambda p: self.clock(p, self.precise, 'precise'))
        self.CreateToolhelp32Snapshot = Function(self.snapshot)
        self.Process32FirstW = Function(lambda h, p: self.entry(p, 0))
        self.Process32NextW = Function(lambda h, p: self.entry(p, self.position + 1))
        self.OpenProcess = Function(self.open)
        self.QueryFullProcessImageNameW = Function(self.image)
        self.GetProcessTimes = Function(self.times)
        self.WaitForSingleObject = Function(lambda *args: 258)
        self.CloseHandle = Function(self.close)

    def clock(self, pointer, value, label):
        self.calls.append(label)
        pointer._obj.dwLowDateTime = value & 0xffffffff
        pointer._obj.dwHighDateTime = value >> 32

    def snapshot(self, flags, pid):
        assert (flags, pid) == (2, 0)
        self.calls.append('snapshot')
        return 777

    def entry(self, pointer, position):
        self.position = position
        if position >= len(self.rows):
            self.error = 18
            return 0
        current = self.rows[position]
        pointer._obj.th32ProcessID = current['pid']
        pointer._obj.th32ParentProcessID = current['parent']
        pointer._obj.szExeFile = current['name']
        return 1

    def open(self, access, inherit, pid):
        assert access == 0x1000 and inherit is False
        self.opened.append(pid)
        return 1000 + pid

    def process(self, handle):
        return next(item for item in self.rows if item['pid'] == handle - 1000)

    def image(self, handle, flags, buffer, size):
        if self.failed == 'image':
            self.error = 5
            return 0
        buffer.value = self.process(handle)['image']
        size._obj.value = len(buffer.value.encode('utf-16-le')) // 2
        return 1

    def times(self, handle, creation, exit_time, kernel_time, user_time):
        if self.failed == 'times':
            self.error = 5
            return 0
        created = self.process(handle)['created']
        creation._obj.dwLowDateTime = created & 0xffffffff
        creation._obj.dwHighDateTime = created >> 32
        return 1

    def close(self, handle):
        self.closed.append(handle)
        return 1


class HwpCensusClockTests(unittest.TestCase):
    def native(self, kernel):
        stack = ExitStack()
        stack.enter_context(patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True))
        stack.enter_context(patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True))
        stack.enter_context(patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'fake native failure'), create=True))
        stack.enter_context(patch.object(smoke.subprocess, 'run', side_effect=AssertionError('Census must not launch a subprocess')))
        return stack

    def observe(self, kernel):
        receipt = {}
        with self.native(kernel):
            match = smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED, evidence=receipt)
        return match, receipt

    def pure(self, receipt, *, pid=SHELL_PID, created=SHELL_CREATED, executable=EXECUTABLE):
        return smoke.require_hwp_census_receipt(receipt, pid, created, executable)

    def test_optional_receipt_and_pure_replay_api_are_available(self):
        self.assertIn('evidence', inspect.signature(smoke._hwp_child_process).parameters)
        self.assertTrue(callable(getattr(smoke, 'require_hwp_census_receipt', None)))

    def test_existing_caller_without_receipt_uses_precise_instead_of_older_coarse_time(self):
        kernel = Kernel()
        with self.native(kernel):
            match = smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED)
        self.assertEqual(match['pid'], 108)
        self.assertEqual(kernel.calls[:2], ['precise', 'snapshot'])
        self.assertNotIn('coarse', kernel.calls)

    def test_precise_void_clock_precedes_snapshot_and_never_reads_coarse_clock(self):
        kernel = Kernel()
        match, receipt = self.observe(kernel)
        self.assertEqual(kernel.calls[:2], ['precise', 'snapshot'])
        self.assertNotIn('coarse', kernel.calls, 'A coarse FILETIME below process creation must never substitute for precise UTC')
        self.assertEqual(kernel.GetSystemTimePreciseAsFileTime.argtypes, (ctypes.POINTER(smoke.wintypes.FILETIME),))
        self.assertIsNone(kernel.GetSystemTimePreciseAsFileTime.restype)
        self.assertEqual(receipt['schemaVersion'], 1)
        self.assertEqual(receipt['kind'], 'native-hwp-child-census')
        self.assertEqual(receipt['clockApi'], 'GetSystemTimePreciseAsFileTime')
        self.assertEqual(receipt['shellPid'], SHELL_PID)
        self.assertEqual(receipt['shellCreationFileTime'], SHELL_CREATED)
        self.assertEqual(receipt['snapshotClock'], split_filetime(SNAPSHOT_TIME))
        self.assertEqual(receipt['snapshotStartedFileTime'], SNAPSHOT_TIME)
        self.assertTrue(receipt['snapshotHandleCreated'])
        self.assertTrue(receipt['snapshotClosed'])
        self.assertTrue(receipt['enumerationComplete'])
        self.assertTrue(receipt['success'])
        self.assertEqual(receipt['match'], match)
        self.assertEqual(self.pure(receipt), match)
        candidate, = receipt['candidates']
        self.assertEqual(candidate['nativeCreation'], split_filetime(BASE + 500))
        self.assertEqual(candidate['nativeImage'], str(EXECUTABLE))
        self.assertEqual(candidate['nativeImageLength'], len(str(EXECUTABLE).encode('utf-16-le')) // 2)
        self.assertTrue(candidate['matched'])
        self.assertTrue(candidate['handleClosed'])
        self.assertEqual(kernel.closed, [1108, 777])

    def test_inverted_precise_clock_is_retained_before_assertion_without_snapshot(self):
        kernel, receipt = Kernel(precise=SHELL_CREATED - 1), {}
        with self.native(kernel), self.assertRaises(AssertionError):
            smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED, evidence=receipt)
        self.assertEqual(receipt['snapshotClock'], split_filetime(SHELL_CREATED - 1))
        self.assertEqual(receipt['snapshotStartedFileTime'], SHELL_CREATED - 1)
        self.assertFalse(receipt['snapshotHandleCreated'])
        self.assertFalse(receipt['success'])
        self.assertTrue(receipt['error'])
        self.assertNotIn('snapshot', kernel.calls)
        self.assertFalse(kernel.opened)
        self.assertFalse(kernel.closed)
        with self.assertRaises((AssertionError, KeyError)):
            self.pure(receipt)

    def test_void_precise_clock_does_not_consult_stale_last_error(self):
        kernel, receipt = Kernel(), {}
        kernel.error = 5
        def last_error():
            self.assertFalse('precise' in kernel.calls and 'snapshot' not in kernel.calls,
                             'The VOID precise-clock call has no success/LastError result to inspect')
            return kernel.error
        with self.native(kernel), patch.object(smoke.ctypes, 'get_last_error', side_effect=last_error, create=True):
            match = smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED, evidence=receipt)
        self.assertEqual(match['pid'], 108)
        self.assertTrue(receipt['success'])

    def test_child_creation_interval_is_inclusive_and_rejects_stale_or_recycled_pid(self):
        for created, expected in ((SHELL_CREATED, True), (SNAPSHOT_TIME, True),
                                  (SHELL_CREATED - 1, False), (SNAPSHOT_TIME + 1, False)):
            with self.subTest(created=created):
                kernel = Kernel([row(created=created)])
                match, receipt = self.observe(kernel)
                self.assertEqual(match is not None, expected)
                candidate, = receipt['candidates']
                self.assertEqual(candidate['generationWithinSnapshot'], expected)
                self.assertEqual(candidate['matched'], expected)
                self.assertTrue(candidate['handleClosed'])
                self.assertTrue(receipt['success'])
                self.assertEqual(self.pure(receipt), match)

    def test_only_intersecting_parent_and_name_candidates_are_opened_and_exact_image_can_match(self):
        foreign = Path('/foreign/OpenGeul.exe').resolve()
        kernel = Kernel([row(106, 99), row(107, image=foreign),
                         row(109, name='Foreign.exe'), row(110, 99, name='Foreign.exe'), row()])
        match, receipt = self.observe(kernel)
        self.assertEqual(match['pid'], 108)
        self.assertEqual(kernel.opened, [107, 108])
        self.assertEqual([item['pid'] for item in receipt['candidates']], [106, 107, 109, 108])
        self.assertEqual([item['queryAttempted'] for item in receipt['candidates']], [False, True, False, True])
        self.assertFalse(receipt['candidates'][1]['imageMatches'])
        self.assertEqual(self.pure(receipt), match)

    def test_missing_precise_export_fails_without_coarse_fallback_or_snapshot(self):
        kernel, receipt = Kernel(), {}
        del kernel.GetSystemTimePreciseAsFileTime
        with self.native(kernel), self.assertRaises((AttributeError, OSError, RuntimeError)):
            smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED, evidence=receipt)
        self.assertNotIn('coarse', kernel.calls)
        self.assertNotIn('snapshot', kernel.calls)
        self.assertFalse(kernel.opened)
        self.assertFalse(receipt['success'])
        self.assertTrue(receipt['error'])

    def test_failed_native_identity_queries_retain_candidate_and_close_owned_handles(self):
        for operation in ('image', 'times'):
            with self.subTest(operation=operation):
                kernel, receipt = Kernel(failed=operation), {}
                with self.native(kernel), self.assertRaises(OSError):
                    smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED, evidence=receipt)
                self.assertFalse(receipt['success'])
                self.assertTrue(receipt['error'])
                self.assertTrue(receipt['snapshotClosed'])
                candidate, = receipt['candidates']
                self.assertTrue(candidate['queryAttempted'])
                self.assertTrue(candidate['handleClosed'])
                self.assertEqual(kernel.closed, [1108, 777])
                if operation == 'times':
                    self.assertEqual(candidate['nativeImage'], str(EXECUTABLE))
                with self.assertRaises((AssertionError, KeyError)):
                    self.pure(receipt)

    def test_ambiguous_matches_preserve_all_candidates_but_never_certify_success(self):
        kernel, receipt = Kernel([row(), row(109)]), {}
        with self.native(kernel), self.assertRaises(AssertionError):
            smoke._hwp_child_process(SHELL_PID, EXECUTABLE, shell_creation=SHELL_CREATED, evidence=receipt)
        self.assertFalse(receipt['success'])
        self.assertTrue(receipt['error'])
        self.assertTrue(receipt['enumerationComplete'])
        self.assertTrue(receipt['snapshotClosed'])
        self.assertEqual([candidate['pid'] for candidate in receipt['candidates'] if candidate['matched']], [108, 109])
        self.assertEqual(kernel.closed, [1108, 1109, 777])
        with self.assertRaises((AssertionError, KeyError)):
            self.pure(receipt)

    def test_pure_replay_recomputes_raw_clock_generation_image_and_parent_instead_of_trusting_flags(self):
        _, original = self.observe(Kernel())
        def recycled(receipt):
            candidate, = receipt['candidates']
            candidate['creationFileTime'] = SNAPSHOT_TIME + 1
            candidate['nativeCreation'] = split_filetime(SNAPSHOT_TIME + 1)
            receipt['match']['creationFileTime'] = SNAPSHOT_TIME + 1
        def foreign_image(receipt):
            candidate, = receipt['candidates']
            candidate['nativeImage'] = candidate['image'] = str(Path('/foreign/OpenGeul.exe').resolve())
            candidate['nativeImageLength'] = len(candidate['nativeImage'].encode('utf-16-le')) // 2
            receipt['match']['executable'] = candidate['image']
        mutations = {
            'coarse-clock-label': lambda r: r.update(clockApi='GetSystemTimeAsFileTime'),
            'clock-raw-low': lambda r: r['snapshotClock'].update(low=999),
            'clock-combined-value': lambda r: r.update(snapshotStartedFileTime=SNAPSHOT_TIME + 1),
            'recycled-same-image-false-positive': recycled,
            'foreign-image-false-positive': foreign_image,
            'foreign-parent-false-positive': lambda r: r['candidates'][0].update(parentPid=99),
            'foreign-name-false-positive': lambda r: r['candidates'][0].update(snapshotExeName='Foreign.exe'),
            'candidate-handle-not-closed': lambda r: r['candidates'][0].update(handleClosed=False),
            'snapshot-handle-not-closed': lambda r: r.update(snapshotClosed=False),
            'enumeration-incomplete': lambda r: r.update(enumerationComplete=False),
            'missing-reported-match': lambda r: r.update(match=None),
            'unproved-clock-api': lambda r: r.pop('clockApi'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(original)
                mutate(changed)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    self.pure(changed)
        with self.assertRaises((AssertionError, KeyError)):
            self.pure(original, pid=99)
        with self.assertRaises((AssertionError, KeyError)):
            self.pure(original, created=SHELL_CREATED + 1)

    def test_pure_replay_compares_windows_paths_without_linux_resolve_or_case_sensitivity(self):
        _, receipt = self.observe(Kernel())
        receipt['expectedExecutable'] = 'D:\\Owned\\OpenGeul.exe'
        candidate, = receipt['candidates']
        candidate['image'] = 'd:\\OWNED\\OPENGEUL.EXE'
        candidate['nativeImage'] = candidate['image']
        candidate['nativeImageLength'] = len(candidate['nativeImage'].encode('utf-16-le')) // 2
        receipt['match']['executable'] = candidate['image']
        self.assertEqual(self.pure(receipt, executable=PureWindowsPath('d:/owned/opengeul.exe')), receipt['match'])


if __name__ == '__main__':
    unittest.main()
