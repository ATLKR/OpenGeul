"""Diagnostic resource accounting and bounded ownership, not release qualification."""
import ctypes
import importlib.util
import os
from pathlib import Path
import sys
import time
import urllib.request
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT/'ci/pressure_benchmark.py'


def module():
    if not PATH.is_file():
        return None
    spec = importlib.util.spec_from_file_location('pressure_benchmark_test', PATH)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


class PressureBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.is_file(), 'The actual compile/resource sampler is missing')
        self.m = module()

    def test_llp64_structures_match_official_windows_api(self):
        self.assertEqual(ctypes.sizeof(self.m.FILETIME), 8)
        self.assertEqual(ctypes.sizeof(self.m.MEMORYSTATUSEX), 64)
        self.assertEqual(self.m.MEMORYSTATUSEX.ullAvailPhys.offset, 16)

    def test_cpu_kernel_time_includes_idle_and_is_counted_once(self):
        self.assertEqual(self.m.cpu_interval((100, 200, 100), (150, 280, 120)),
                         {'totalTicks': 100, 'busyTicks': 50, 'cpuBusyPercent': 50.0})
        self.assertEqual(self.m.cpu_interval((100, 200, 100), (100, 280, 120))['cpuBusyPercent'], 100)

    def test_invalid_counter_intervals_fail_instead_of_reporting_headroom(self):
        for before, after in [((1,2,3),(0,3,4)), ((1,2,3),(1,2,3)),
                              ((1,2,3),(9,3,4)), ((True,2,3),(3,4,5))]:
            with self.subTest(before=before, after=after):
                with self.assertRaises(ValueError): self.m.cpu_interval(before, after)

    def test_weighted_cpu_average_and_actual_memory_minimum(self):
        samples = [{'availablePhysicalBytes': 12, 'totalPhysicalBytes': 16, 'totalTicks': 1, 'busyTicks': 1},
                   {'availablePhysicalBytes': 7, 'totalPhysicalBytes': 16, 'totalTicks': 3, 'busyTicks': 0}]
        result = self.m.statistics(samples)
        self.assertEqual(result['meanCpuBusyPercent'], 25)
        self.assertEqual(result['minimumAvailablePhysicalBytes'], 7)
        self.assertEqual(result['peakSystemUsedPhysicalBytes'], 9)
        self.assertEqual(result['sampleCount'], 2)

    def test_workload_is_the_original_locked_native_skia_cli_release(self):
        self.assertEqual(self.m.COMMAND, ('cargo', 'build', '--release', '--locked', '--target',
                         'aarch64-pc-windows-msvc', '--package', 'rhwp', '--bin', 'rhwp', '--features', 'native-skia'))
        self.assertEqual(self.m.LEVELS, (8, 12, 16))

    def test_unknown_or_empty_statistics_do_not_qualify_a_result(self):
        for samples in [[], [{'availablePhysicalBytes': 20, 'totalPhysicalBytes': 16, 'totalTicks': 1, 'busyTicks': 0}],
                        [{'availablePhysicalBytes': 7, 'totalPhysicalBytes': 16, 'totalTicks': 0, 'busyTicks': 0}]]:
            with self.assertRaises(ValueError): self.m.statistics(samples)

    def test_source_guard_refuses_other_product_changes(self):
        self.assertEqual(self.m.check_changed_paths(self.m.CHANGED_PATHS), list(self.m.CHANGED_PATHS))
        for paths in [[], (*self.m.CHANGED_PATHS, 'overlay/com-worker/src/main.rs'),
                      tuple(x for x in self.m.CHANGED_PATHS if 'test_' not in x)]:
            with self.assertRaises(ValueError): self.m.check_changed_paths(paths)

    def test_file_cap_refuses_overwrite_and_oversized_evidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'evidence.json'
            self.m.write_new(path, b'abc', 3)
            self.assertEqual(path.read_bytes(), b'abc')
            with self.assertRaises(ValueError): self.m.write_new(path, b'def', 3)
            with self.assertRaises(ValueError): self.m.write_new(Path(temporary)/'too-large', b'abcd', 3)

    def test_post_exit_reader_failure_blocks_a_successful_parent(self):
        state = {'logCapExceeded':False,'readerError':False}
        self.assertIsNone(self.m.reader_failure(state))
        state['logCapExceeded'] = True
        self.assertEqual(self.m.reader_failure(state), 'logCapExceeded')
        state['logCapExceeded'] = False; state['readerError'] = True
        self.assertEqual(self.m.reader_failure(state), 'logReaderFailed')

    def test_bearer_is_initial_api_only_and_never_copied_to_signed_blob(self):
        with patch.dict(os.environ, {'GH_TOKEN':'synthetic-test-token'}):
            request = self.m.github_request('actions/artifacts/11741399358/zip')
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-test-token')
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(request, None, 302, 'Found', {},
                        'https://example.blob.core.windows.net/diagnostic-synthetic-zip')
        self.assertIsNone(redirected.get_header('Authorization'))

    @unittest.skipUnless(os.name == 'nt', 'Actual Win32 API probe requires the benchmark Windows runner')
    def test_actual_windows_api(self):
        probe = self.m.WindowsProbe()
        before = probe.sample()
        time.sleep(.05)
        after = probe.sample()
        self.assertGreater(self.m.cpu_interval(before['cpuTimes'], after['cpuTimes'])['totalTicks'], 0)
        self.assertGreater(after['availablePhysicalBytes'], 0)


if __name__ == '__main__': unittest.main()
