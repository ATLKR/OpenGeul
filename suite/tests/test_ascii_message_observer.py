"""Controller sequencing with typed native-boundary doubles, never Windows proof."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

from test_ascii_message_progress import action, stream, TARGET


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_message_observer.py'


class Clock:
    def __init__(self): self.value = 100.; self.pauses = []
    def __call__(self): return self.value
    def pause(self, seconds): self.pauses.append(seconds); self.value += seconds


class Probe:
    def __init__(self, batches=None):
        self.batches = list(batches if batches is not None else [stream()])
        self.target = dict(TARGET); self.calls = []; self.installed = 0
        self.stop_error = self.close_error = self.admit_error = self.start_error = None
        self.seen = 0
    def admit(self):
        self.calls.append('admit')
        if self.admit_error: raise self.admit_error
        return dict(self.target)
    def guard(self): self.calls.append('guard'); return dict(self.target)
    def start(self):
        self.calls.append('start'); self.installed = 2
        if self.start_error: raise self.start_error
    def arm(self, index): self.calls.append(('arm', index)); return self.seen
    def read_events(self, after):
        self.calls.append(('read', after)); rows = self.batches.pop(0) if self.batches else []
        if rows: self.seen = rows[-1]['sequence']
        return copy.deepcopy(rows)
    def can_stop(self): return bool(self.installed)
    def stop(self):
        self.calls.append('stop')
        if self.stop_error: raise self.stop_error
        return dict(recordingStopped=True, remoteCallbackQuiescenceProved=False)
    def close(self):
        self.calls.append('close')
        if self.close_error: raise self.close_error
        return dict(controllerResourcesReleased=True, engineHandleReleased=True,
                    unhookAttempts=self.installed, remoteCallbackQuiescenceProved=False)


class AsciiMessageObserverTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Missing owned ASCII queue observer controller')
        sys.path.insert(0, str(SOURCE.parent))
        self.addCleanup(lambda: sys.path.remove(str(SOURCE.parent)))
        spec = importlib.util.spec_from_file_location('tested_ascii_message_observer', SOURCE)
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.process = NS(pid=77, opengeul_evidence_output=Path(self.directory.name),
                          opengeul_evidence_case='owned-ascii-case')
        self.binding = dict(shellPid=77, officePid=88, childHwnd=TARGET['hwnd'])
        self.clock = Clock(); self.record = {}

    def observer(self, probe=None, deadline=101.):
        probe = probe or Probe()
        observer = self.module.OwnedAsciiObserver(None, self.process, self.binding,
            {'architecture': 'x64'}, self.record, deadline,
            clock=self.clock, pause=self.clock.pause, probe=probe)
        return observer, probe

    def complete(self, observer):
        observer.arm(action()); proof = observer.await_progress(action()); observer.finish(1)
        return proof

    def test_attach_guard_arm_real_progress_stop_then_release_without_semantic_claim(self):
        observer, probe = self.observer()
        with observer: proof = self.complete(observer)
        self.assertTrue(observer.receipt['success'])
        self.assertTrue(proof['queueConsumed']); self.assertFalse(proof['semanticInsertionProved'])
        self.assertEqual(1, probe.calls.count('start')); self.assertEqual(1, probe.calls.count('stop'))
        self.assertEqual(1, probe.calls.count('close'))
        self.assertLess(probe.calls.index('admit'), probe.calls.index('start'))
        self.assertLess(probe.calls.index('stop'), probe.calls.index('close'))
        self.assertFalse(observer.receipt['cleanup']['remoteCallbackQuiescenceProved'])

    def test_delayed_partial_progress_reads_new_rows_only_without_any_input_retry(self):
        rows = stream(); observer, probe = self.observer(Probe([rows[:2], [], rows[2:]]))
        with observer: self.complete(observer)
        self.assertEqual([('read', 0), ('read', 2), ('read', 2)], [c for c in probe.calls if isinstance(c, tuple) and c[0] == 'read'])
        self.assertEqual([('arm', 0)], [c for c in probe.calls if isinstance(c, tuple) and c[0] == 'arm'])
        self.assertTrue(self.clock.pauses); self.assertTrue(all(0 < seconds <= .01 for seconds in self.clock.pauses))

    def test_missing_progress_expires_original_deadline_and_still_releases_owned_resources(self):
        observer, probe = self.observer(Probe([]), deadline=100.025)
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            with observer: self.complete(observer)
        self.assertFalse(observer.receipt['success']); self.assertEqual(1, probe.calls.count('close'))
        self.assertNotIn('stop', probe.calls)
        self.assertLessEqual(self.clock.value, 100.025)

    def test_wrong_character_is_retained_before_rejection_and_never_authorizes_next_arm(self):
        rows = stream(); rows[1]['wParam'] = ord('b')
        observer, probe = self.observer(Probe([rows]))
        with self.assertRaisesRegex(AssertionError, 'character'):
            with observer: self.complete(observer)
        self.assertEqual(ord('b'), observer.receipt['actions'][0]['observations'][1]['wParam'])
        with self.assertRaisesRegex(AssertionError, 'failed'): observer.arm(dict(action(), index=1))
        self.assertEqual(1, probe.calls.count('close'))

    def test_guard_target_change_is_retained_and_fatal_before_arm(self):
        observer, probe = self.observer()
        with self.assertRaises(AssertionError):
            with observer:
                probe.target['hwnd'] += 1; observer.arm(action())
        self.assertNotIn(('arm', 0), probe.calls)
        self.assertNotEqual(TARGET['hwnd'], observer.receipt['lastTargetObservation']['hwnd'])

    def test_partial_install_or_timed_out_start_never_skips_cleanup(self):
        for installed in (1, 2):
            with self.subTest(installed=installed):
                probe = Probe(); probe.start_error = TimeoutError('inert start timed out')
                original = probe.start
                def partial():
                    try: original()
                    finally: probe.installed = installed
                probe.start = partial; observer, _ = self.observer(probe)
                with self.assertRaisesRegex(TimeoutError, 'start'):
                    with observer: self.fail('failed start entered input')
                self.assertEqual(1, probe.calls.count('close')); self.assertFalse(observer.receipt['success'])
                self.assertEqual(installed, observer.receipt['cleanup']['unhookAttempts'])

    def test_admission_failure_also_releases_partial_native_resources_once(self):
        probe = Probe(); probe.admit_error = OSError('native admission failed')
        observer, _ = self.observer(probe)
        with self.assertRaises(OSError): observer.__enter__()
        self.assertEqual(['admit', 'close'], probe.calls)

    def test_failed_stop_is_fatal_after_complete_queue_progress_but_close_still_runs(self):
        probe = Probe(); probe.stop_error = TimeoutError('inert stop timed out')
        observer, _ = self.observer(probe)
        with self.assertRaisesRegex(TimeoutError, 'stop'):
            with observer: self.complete(observer)
        self.assertEqual(1, probe.calls.count('close')); self.assertFalse(observer.receipt['success'])

    def test_cleanup_failure_does_not_become_success_or_mask_a_primary_wrong_character(self):
        rows = stream(); rows[1]['wParam'] = ord('b')
        probe = Probe([rows]); probe.close_error = OSError('unhook failed')
        observer, _ = self.observer(probe)
        with self.assertRaisesRegex(AssertionError, 'character'):
            with observer: self.complete(observer)
        self.assertTrue(any('unhook failed' in value for value in observer.receipt['cleanupErrors']))
        self.assertFalse(observer.receipt['success'])

    def test_incomplete_or_duplicate_finish_cannot_certify_a_session(self):
        observer, _ = self.observer()
        with self.assertRaises(AssertionError):
            with observer: observer.finish(1)
        observer, _ = self.observer()
        with self.assertRaises(AssertionError):
            with observer:
                self.complete(observer); observer.finish(1)

    def test_late_cleanup_or_transient_bad_clock_stays_fatal_with_mandatory_release(self):
        for changed in ('late', 'nan'):
            with self.subTest(changed=changed):
                observer, probe = self.observer()
                close = probe.close
                def delayed():
                    result = close()
                    self.clock.value = 102. if changed == 'late' else float('nan')
                    return result
                probe.close = delayed
                with self.assertRaises(AssertionError):
                    with observer: self.complete(observer)
                self.assertEqual(1, probe.calls.count('close')); self.assertFalse(observer.receipt['success'])
                self.clock.value = 100.

    def test_exact_final_timestamp_at_deadline_cannot_become_success(self):
        observer, probe = self.observer()
        original = observer._now
        def final_edge():
            if observer.closed and observer.receipt.get('cleanup'):
                count = getattr(observer, 'closing_reads', 0) + 1
                observer.closing_reads = count
                if count == 2: self.clock.value = observer.deadline
            return original()
        observer._now = final_edge
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            with observer: self.complete(observer)
        self.assertFalse(observer.receipt['success'])
        self.assertEqual(1, probe.calls.count('close'))

    def test_caught_duplicate_finish_stays_failed_on_normal_context_exit(self):
        observer, probe = self.observer()
        with self.assertRaisesRegex(AssertionError, 'failed'):
            with observer:
                self.complete(observer)
                with self.assertRaises(AssertionError): observer.finish(1)
        self.assertFalse(observer.receipt['success'])

    def test_successful_plan_requires_stop_ack_even_if_backend_can_stop_becomes_false(self):
        observer, probe = self.observer()
        with self.assertRaisesRegex(AssertionError, 'stop'):
            with observer:
                self.complete(observer); probe.can_stop = lambda: False
        self.assertFalse(observer.receipt['success']); self.assertEqual(1, probe.calls.count('close'))


if __name__ == '__main__': unittest.main()
