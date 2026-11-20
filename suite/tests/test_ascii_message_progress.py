"""Read-only target-queue progress; no Windows or semantic delivery claims."""
import copy
import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ascii_message_progress.py'
TARGET = dict(pid=88, tid=99, hwnd=0x123456789, layout=0x04090409)


def action(character='a'):
    upper = character.isupper() or character == ':'
    scan = {'a': 0x1e, 'l': 0x26, ':': 0x27, ' ': 0x39}[character.lower()]
    keys = ([0x2a] if upper else []) + [scan]
    events = [dict(vk=0, scan=key, flags=8) for key in keys]
    events += [dict(vk=0, scan=key, flags=10) for key in reversed(keys)]
    return dict(index=0, character=character, events=events)


def row(sequence, message, value, scan, *, remove=1, epoch=1):
    up = message == 0x101
    return dict(sequence=sequence, actionEpoch=epoch, origin=1, remove=remove,
        message=message, pid=88, tid=99, hwnd=TARGET['hwnd'], layout=TARGET['layout'],
        wParam=value, lParam=1 | scan << 16 | (0xc0000000 if up else 0),
        messageTime=500, extraInfo=0, nativeTick=500,
        shiftState=0, controlState=0, altState=0, capsState=0, flags=0)


def stream(character='a'):
    expected = action(character)
    key = ord(character.upper()) if character.isalpha() else {':': 0xba, ' ': 0x20}[character]
    rows = []
    for event in expected['events']:
        scan = event['scan']; code = 0x10 if scan == 0x2a else key
        rows.append(row(len(rows) + 1, 0x101 if event['flags'] & 2 else 0x100, code, scan))
        if not event['flags'] & 2 and scan != 0x2a:
            rows.append(row(len(rows) + 1, 0x102, ord(character), scan))
    return rows


class AsciiMessageProgressTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Missing bounded ASCII target-queue progress policy')
        spec = importlib.util.spec_from_file_location('tested_ascii_message_progress', SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def pending(self, character='a', baseline=0):
        return self.module.CharacterProgress(action(character), TARGET, baseline)

    def test_all_counts_without_observed_messages_do_not_acknowledge_a_character(self):
        self.assertIsNone(self.pending().observe([]))

    def test_exact_character_and_key_up_acknowledge_queue_progress_without_a_dispatch_return(self):
        proof = self.pending().observe(stream())
        self.assertTrue(proof['queueConsumed'])
        self.assertFalse(proof['semanticInsertionProved'])
        self.assertEqual([1, 2, 3], [r['sequence'] for r in proof['events']])

    def test_delayed_key_up_requires_a_later_actual_observation(self):
        state = self.pending(); rows = stream()
        self.assertIsNone(state.observe(rows[:2]))
        self.assertTrue(state.observe(rows[2:])['queueConsumed'])

    def test_key_up_before_character_is_supported_without_inventing_a_total_order(self):
        rows = stream(); rows[1], rows[2] = rows[2], rows[1]
        for i, item in enumerate(rows): item['sequence'] = i + 1
        self.assertTrue(self.pending().observe(rows)['queueConsumed'])

    def test_uppercase_waits_for_the_original_shift_release_as_well(self):
        rows = stream('L'); state = self.pending('L')
        self.assertIsNone(state.observe(rows[:-1]))
        self.assertTrue(state.observe(rows[-1:])['queueConsumed'])

    def test_repeated_nonremoving_character_peeks_are_diagnostic_not_duplicates(self):
        rows = stream(); peek = copy.deepcopy(rows[1]); peek['remove'] = 0
        rows[1:1] = [peek, copy.deepcopy(peek)]
        for i, item in enumerate(rows): item['sequence'] = i + 1
        proof = self.pending().observe(rows)
        self.assertTrue(proof['queueConsumed'])
        self.assertEqual(1, len([r for r in proof['events'] if r['message'] == 0x102 and r['remove'] == 1]))

    def test_nonremoving_peek_alone_never_certifies_character_consumption(self):
        rows = stream(); rows[1]['remove'] = 0
        self.assertIsNone(self.pending().observe(rows))

    def test_wrong_or_duplicate_consumed_character_is_fatal(self):
        for changed in ('wrong', 'duplicate'):
            with self.subTest(changed=changed):
                rows = stream()
                if changed == 'wrong': rows[1]['wParam'] = ord('b')
                else:
                    rows.insert(2, copy.deepcopy(rows[1]))
                    for i, item in enumerate(rows): item['sequence'] = i + 1
                with self.assertRaisesRegex(AssertionError, 'character'):
                    self.pending().observe(rows)

    def test_wrong_target_generation_slot_hkl_or_epoch_is_fatal(self):
        for field in ('pid', 'tid', 'hwnd', 'layout', 'actionEpoch'):
            with self.subTest(field=field):
                rows = stream(); rows[1][field] += 1
                with self.assertRaises(AssertionError): self.pending().observe(rows)

    def test_noncontiguous_replayed_or_untyped_sequence_is_fatal(self):
        for value in (0, 3, True):
            with self.subTest(value=value):
                rows = stream(); rows[0]['sequence'] = value
                with self.assertRaises(AssertionError): self.pending().observe(rows)

    def test_reordered_or_repeated_key_messages_are_fatal(self):
        rows = stream(); rows[0]['message'] = 0x101; rows[0]['lParam'] |= 0xc0000000
        with self.assertRaises(AssertionError): self.pending().observe(rows)

    def test_wrong_scan_repeat_system_key_or_source_is_fatal(self):
        for field, value in [('lParam', 1 | 0x30 << 16), ('lParam', 2 | 0x1e << 16),
                             ('message', 0x104), ('origin', 2), ('flags', 1)]:
            with self.subTest(field=field, value=value):
                rows = stream(); rows[0][field] = value
                with self.assertRaises(AssertionError): self.pending().observe(rows)

    def test_raw_target_thread_modifier_state_is_retained_without_controller_state_substitution(self):
        rows = stream('L'); rows[2]['shiftState'] = -32768
        proof = self.pending('L').observe(rows)
        self.assertEqual(-32768, proof['events'][2]['shiftState'])

    def test_message_extra_information_is_raw_diagnostic_not_a_unique_injection_tag(self):
        rows = stream(); rows[1]['extraInfo'] = 0x123456789
        proof = self.pending().observe(rows)
        self.assertEqual(0x123456789, proof['events'][1]['extraInfo'])
        self.assertFalse(proof['semanticInsertionProved'])

    def test_a_wrong_character_cannot_be_ignored_then_replaced_by_a_good_observation(self):
        state = self.pending(); rows = stream(); wrong = copy.deepcopy(rows[:2]); wrong[1]['wParam'] = ord('b')
        with self.assertRaises(AssertionError): state.observe(wrong)
        with self.assertRaisesRegex(AssertionError, 'failed'): state.observe(rows[1:])

    def test_baseline_sequence_is_joined_exactly_and_input_rows_are_not_mutated(self):
        rows = stream()
        for item in rows: item['sequence'] += 40
        before = copy.deepcopy(rows); proof = self.pending(baseline=40).observe(rows)
        self.assertEqual(rows, before)
        self.assertEqual(40, proof['baselineSequence'])
        rows[0]['wParam'] = 0
        self.assertEqual(ord('A'), proof['events'][0]['wParam'])

    def test_progress_cannot_reopen_or_accept_extra_events_after_completion(self):
        state = self.pending(); state.observe(stream())
        with self.assertRaises(AssertionError): state.observe([row(4, 0x101, 65, 0x1e)])

    def test_finite_event_capacity_fails_without_overwriting_earlier_evidence(self):
        state = self.pending(); rows = [row(i + 1, 0x100, 65, 0x1e, remove=0)
                                      for i in range(self.module.MAX_CHARACTER_EVENTS + 1)]
        with self.assertRaisesRegex(AssertionError, 'bound'): state.observe(rows)


if __name__ == '__main__': unittest.main()
