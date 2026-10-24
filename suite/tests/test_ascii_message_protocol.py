"""Fixed-width observer ABI only; actual hook behavior is not exercised here."""
import ctypes
import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_message_protocol.py'


class AsciiMessageProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Missing separate fixed-width ASCII observer protocol')
        spec = importlib.util.spec_from_file_location('tested_ascii_message_protocol', SOURCE)
        self.protocol = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.protocol)

    def state(self):
        p = self.protocol; state = p.State()
        state.magic, state.version = p.MAGIC, p.VERSION
        state.stateSize, state.eventSize, state.capacity = ctypes.sizeof(p.State), ctypes.sizeof(p.Event), p.CAPACITY
        state.pid, state.tid, state.controllerPid = 88, 99, 77
        state.hwnd, state.nonce, state.engineCreationTime, state.layout = 0x123456789, 0x223456789, 0x323456789, 0x04090409
        return state

    def test_event_and_header_have_fixed_cross_architecture_sizes_and_offsets(self):
        p = self.protocol
        self.assertEqual(96, ctypes.sizeof(p.Event))
        self.assertEqual(32, p.Event.hwnd.offset)
        self.assertEqual(80, p.Event.shiftState.offset)
        self.assertEqual(2, p.VERSION)
        self.assertEqual(328, ctypes.sizeof(p.QueueSample))
        self.assertEqual(336, ctypes.sizeof(p.Readiness))
        self.assertEqual(120, p.State.readiness.offset)
        self.assertEqual(456, p.State.events.offset)
        self.assertEqual(456 + 4096 * 96, p.State.traceVersion.offset)
        self.assertEqual(407008, ctypes.sizeof(p.State))
        self.assertEqual(8, ctypes.alignment(p.State))

    def test_full_handle_filetime_and_signed_modifier_state_survive_decoding(self):
        state = self.state(); state.count = 1
        e = state.events[0]; e.sequence = 1; e.hwnd = 0x123456789; e.shiftState = -32768
        rows = self.protocol.committed_events(bytes(state), after=0)
        self.assertEqual(0x123456789, rows[0]['hwnd'])
        self.assertEqual(-32768, rows[0]['shiftState'])

    def test_legacy_state_version_is_rejected_instead_of_reusing_old_layout(self):
        state = self.state(); state.version = 1
        with self.assertRaisesRegex(AssertionError, 'ABI'):
            self.protocol.committed_events(bytes(state), after=0)

    def test_a_reserved_uncommitted_row_is_not_fabricated_into_evidence(self):
        state = self.state(); state.count = 2; state.events[0].sequence = 1
        rows = self.protocol.committed_events(bytes(state), after=0)
        self.assertEqual([1], [row['sequence'] for row in rows])

    def test_a_different_nonzero_commit_sequence_fails_instead_of_being_skipped(self):
        state = self.state(); state.count = 1; state.events[0].sequence = 2
        with self.assertRaisesRegex(AssertionError, 'sequence'):
            self.protocol.committed_events(bytes(state), after=0)

    def test_truncated_wrong_abi_overflow_and_negative_or_excess_count_are_fatal(self):
        state = self.state()
        with self.assertRaises(AssertionError): self.protocol.committed_events(bytes(state)[:-1], after=0)
        for field, value in [('magic', 0), ('version', 7), ('stateSize', 1), ('eventSize', 40),
                             ('capacity', 99), ('overflow', 1), ('count', -1), ('count', 4097)]:
            with self.subTest(field=field):
                state = self.state(); setattr(state, field, value)
                with self.assertRaises(AssertionError): self.protocol.committed_events(bytes(state), after=0)

    def test_unknown_event_reserved_data_and_native_failure_are_fatal(self):
        state = self.state(); state.count = 1; state.events[0].sequence = 1; state.events[0].reserved = 1
        with self.assertRaises(AssertionError): self.protocol.committed_events(bytes(state), after=0)
        state = self.state(); state.status = -8
        with self.assertRaisesRegex(AssertionError, 'status'):
            self.protocol.committed_events(bytes(state), after=0)

    def test_already_committed_baseline_is_not_replayed_and_cannot_exceed_count(self):
        state = self.state(); state.count = 2
        for i in range(2): state.events[i].sequence = i + 1
        self.assertEqual([2], [row['sequence'] for row in self.protocol.committed_events(bytes(state), after=1)])
        for after in (True, -1, 3):
            with self.subTest(after=after), self.assertRaises(AssertionError):
                self.protocol.committed_events(bytes(state), after=after)


if __name__ == '__main__': unittest.main()
