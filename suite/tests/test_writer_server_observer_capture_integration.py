"""Use the actual repository capture API and its original-owner binding."""
import importlib.util
from pathlib import Path
import sys
import unittest

from test_writer_server_observer_sequence import Capture, Cohort, Clock
import writer_server_observer_lifecycle as lifecycle


def actual_capture_module():
    local = Path(__file__).resolve().parents[1] / 'e2e' / 'writer_server_observer_capture.py'
    source = local
    if not source.is_file(): raise AssertionError('Actual repository capture API is missing')
    name = '_actual_writer_capture_integration_api'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


class ActualCaptureContracts(unittest.TestCase):
    def test_actual_frozen_owner_binding_reaches_arm_and_original_call(self):
        actual = actual_capture_module(); cohort = Cohort(None)
        binding = actual.OriginalOwnerBinding(original_engine=cohort.original_engine,
            suite_hwnd=1 + 1, editor_hwnd=2 + 1, editor_tid=3 + 1)
        result = lifecycle.RuntimeSession(Clock()).execute(cohort=cohort, owner=binding,
            capture_factory=lambda budget: Capture(budget, None), verify_original=lambda: True,
            original_call=lambda budget: None)
        self.assertTrue(result.armed); self.assertTrue(result.original_call_attempted)
        self.assertTrue(result.original_call_returned)
        self.assertTrue(result.capture_incomplete)  # No actual watchdog was supplied.


if __name__ == '__main__': unittest.main()
