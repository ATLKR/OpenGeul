"""Synthetic bounded provider doubles; no actual Windows COM/UIA is executed."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from owned_native_menu import NativeMenuProbe


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value


class Provider:
    def __init__(self, clock, *, elapsed=0, mismatch=False):
        self.clock, self.elapsed, self.mismatch = clock, elapsed, mismatch
        self.values, self.operations = {}, []

    def __setattr__(self, name, value):
        if name in ('ConnectionTimeout', 'TransactionTimeout'):
            self.clock.value += self.elapsed
            self.values[name] = value
            self.operations.append(('set', name, value))
        else:
            object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name in ('ConnectionTimeout', 'TransactionTimeout'):
            self.clock.value += self.elapsed
            value = self.values[name] + int(self.mismatch)
            self.operations.append(('get', name, value))
            return value
        raise AttributeError(name)


def probe_with(provider=None, *, now=0, elapsed=0, mismatch=False):
    probe = NativeMenuProbe.__new__(NativeMenuProbe)
    probe.clock, probe.deadline = Clock(now), 5
    probe.provider_client = provider if provider is not None else Provider(
        probe.clock, elapsed=elapsed, mismatch=mismatch)
    return probe


class NativeMenuProviderTimeoutTests(unittest.TestCase):
    def test_each_provider_timeout_is_less_than_one_quarter_of_original_remaining(self):
        probe = probe_with()
        self.assertEqual(probe._call(lambda value: value, 'result'), 'result')
        self.assertEqual(probe.provider_client.values,
            {'ConnectionTimeout': 1249, 'TransactionTimeout': 1249})
        self.assertEqual([row[:2] for row in probe.provider_client.operations], [
            ('set', 'ConnectionTimeout'), ('get', 'ConnectionTimeout'),
            ('set', 'TransactionTimeout'), ('get', 'TransactionTimeout')])
        self.assertIs(probe.provider_timeout_verified, True)

    def test_second_call_uses_original_deadline_and_smaller_remaining_budget(self):
        probe = probe_with()
        probe._call(lambda: setattr(probe.clock, 'value', 1))
        probe._call(lambda: None)
        self.assertEqual([row[2] for row in probe.provider_client.operations if row[0] == 'set'],
            [1249, 1249, 999, 999])
        self.assertEqual(probe.deadline, 5)

    def test_unsupported_timeout_properties_fail_before_target(self):
        class Unsupported:
            __slots__ = ()
        probe = probe_with(Unsupported()); calls = []
        with self.assertRaises(AttributeError):
            probe._call(lambda: calls.append('target'))
        self.assertEqual(calls, [])

    def test_timeout_readback_mismatch_fails_before_target(self):
        probe = probe_with(mismatch=True); calls = []
        with self.assertRaises(AssertionError):
            probe._call(lambda: calls.append('target'))
        self.assertEqual(calls, [])

    def test_expired_original_deadline_does_not_touch_provider_or_target(self):
        probe = probe_with(now=5); calls = []
        with self.assertRaises(AssertionError):
            probe._call(lambda: calls.append('target'))
        self.assertEqual(calls, [])
        self.assertEqual(probe.provider_client.operations, [])

    def test_submillisecond_provider_budget_fails_before_target(self):
        probe = probe_with(now=4.999); calls = []
        with self.assertRaises(AssertionError):
            probe._call(lambda: calls.append('target'))
        self.assertEqual(calls, [])
        self.assertEqual(probe.provider_client.operations, [])

    def test_slow_timeout_setup_cannot_admit_a_target_with_stale_larger_timeouts(self):
        # Four setters/readbacks consume 4.4 s: the two initial 1249 ms
        # timeouts no longer fit the original 600 ms remaining allowance.
        probe = probe_with(elapsed=1.1); calls = []
        with self.assertRaises(AssertionError):
            probe._call(lambda: calls.append('target'))
        self.assertEqual(calls, [])
        self.assertLess(probe.clock.value, probe.deadline)

    def test_target_overrun_is_rejected_without_a_retry(self):
        probe = probe_with(); calls = []
        def target():
            calls.append('target')
            probe.clock.value = 5
        with self.assertRaises(AssertionError):
            probe._call(target)
        self.assertEqual(calls, ['target'])

    def test_close_provider_drops_all_private_element_and_client_references(self):
        probe = probe_with(); shared = SimpleNamespace(marker=object())
        names = ('file_element', 'menu_bar_element', 'current_control', '_retained', 'uia')
        for name in names:
            setattr(probe, name, object())
        marker = shared.marker
        self.assertIs(probe.close_provider(), True)
        for name in names + ('provider_client',):
            self.assertIsNone(getattr(probe, name))
        self.assertIs(shared.marker, marker)


if __name__ == '__main__':
    unittest.main()
