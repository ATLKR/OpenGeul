"""Boundary evidence for one-shot input diagnostics; no Windows injection here."""
import copy
import ctypes
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'lifecycle_input_probe.py'
sys.path.insert(0, str(SOURCE.parent))
if SOURCE.is_file():
    SPEC = importlib.util.spec_from_file_location('suite_lifecycle_input_probe', SOURCE)
    probe = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(probe)
else:
    probe = None


class LifecycleInputProbeTests(unittest.TestCase):
    def evidence(self):
        marker = '-LIFECYCLE-NEW-'
        events, calls = [], []
        for index, char in enumerate(marker):
            events.extend([
                {'sequence': index * 3 + 1, 'message': 0x100, 'wparam': 0xe7, 'remove': True,
                 'pid': 31, 'tid': 41, 'hwnd': 51, 'focus': 51, 'layout': 0x04090409},
                {'sequence': index * 3 + 2, 'message': 0x102, 'wparam': ord(char), 'remove': True,
                 'pid': 31, 'tid': 41, 'hwnd': 51, 'focus': 51, 'layout': 0x04090409},
                {'sequence': index * 3 + 3, 'message': 0x101, 'wparam': 0xe7, 'remove': True,
                 'pid': 31, 'tid': 41, 'hwnd': 51, 'focus': 51, 'layout': 0x04090409}])
            calls.append({'requested': 2, 'inserted': 2, 'events': [
                {'type': 1, 'vk': 0, 'scan': ord(char), 'flags': 4},
                {'type': 1, 'vk': 0, 'scan': ord(char), 'flags': 6}]})
        return {'marker': marker, 'officePid': 31, 'editorTid': 41,
                'focusAfter': {'focus': 51, 'layout': 0x04090409},
                'overflow': False, 'messages': events, 'sendInputCalls': calls,
                'model': {'bodyText': marker, 'childHwnd': 61, 'readOnlyObservation': True}}

    def test_accepted_sendinput_pairs_do_not_prove_the_missing_f_reached_the_queue(self):
        self.assertIsNotNone(probe, 'The owned-thread input receipt analyzer is missing')
        evidence = self.evidence()
        evidence['messages'] = [row for row in evidence['messages']
                                if not (row['message'] == 0x102 and row['wparam'] == ord('F'))]
        evidence['model']['bodyText'] = '-LIECYCLE-NEW-'
        result = probe.analyze_delivery(evidence)
        self.assertTrue(result['sendInputPairsExact'])
        self.assertFalse(result['dequeuedCharactersExact'])
        self.assertFalse(result['modelExact'])
        self.assertEqual(result['dequeuedText'], '-LIECYCLE-NEW-')

    def test_dequeued_f_with_missing_model_f_does_not_invent_the_model_read_order(self):
        self.assertIsNotNone(probe)
        evidence = self.evidence()
        evidence['model']['bodyText'] = '-LIECYCLE-NEW-'
        result = probe.analyze_delivery(evidence)
        self.assertTrue(result['dequeuedCharactersExact'])
        self.assertFalse(result['modelExact'])
        self.assertEqual(result['boundary'], 'dequeued-characters-match-model-differs-order-unresolved')

    def test_no_remove_peeks_are_not_counted_as_duplicate_characters(self):
        self.assertIsNotNone(probe)
        evidence = self.evidence()
        peek = copy.deepcopy(evidence['messages'][1])
        peek.update(remove=False, sequence=0)
        evidence['messages'].insert(1, peek)
        self.assertTrue(probe.analyze_delivery(evidence)['dequeuedCharactersExact'])

    def test_foreign_thread_partial_pair_and_non_english_layout_cannot_qualify(self):
        self.assertIsNotNone(probe)
        for change, key in ((lambda row: row['messages'][1].update(tid=999), 'ownedMessageIdentity'),
                            (lambda row: row['sendInputCalls'][0].update(inserted=1), 'sendInputPairsExact'),
                            (lambda row: row['messages'][1].update(layout=0x04120412), 'englishLayout'),
                            (lambda row: row.update(overflow=True), 'boundedComplete')):
            evidence = self.evidence()
            change(evidence)
            with self.subTest(key=key):
                self.assertFalse(probe.analyze_delivery(evidence)[key])

    def test_controlled_plan_has_twenty_fresh_alternating_trials(self):
        self.assertIsNotNone(probe)
        plan = probe.trial_plan()
        self.assertEqual(len(plan), 20)
        self.assertEqual(len({row['case'] for row in plan}), 20)
        self.assertEqual([row['instrumented'] for row in plan], [True, False] * 10)

    def model_witness(self):
        return {'officePid': 31, 'childHwnd': 61, 'officeCreationTime': 101,
                'expectedImage': str(Path('/owned/Office/program/soffice.bin').resolve()),
                'readOnlyObservation': True, 'witness': {
                    'officePid': 31, 'childHwnd': 61, 'officeCreationTime': 101,
                    'retainedProcessHandle': True, 'imageVerified': True, 'creationTimeVerified': True,
                    'hwndVerifiedBefore': True, 'hwndVerifiedAfter': True, 'generationVerifiedAfter': True}}

    def test_model_snapshot_rejects_missing_retention_and_changed_generation(self):
        self.assertIsNotNone(probe)
        program = Path('/owned/Office/program/soffice.bin').resolve()
        self.assertTrue(hasattr(probe, 'require_model_witness'), 'Model snapshots lack retained-generation validation')
        row = self.model_witness()
        probe.require_model_witness(row, 31, 61, 101, program)
        for field, value in (('officePid', 99), ('childHwnd', 99), ('officeCreationTime', 102),
                             ('expectedImage', str(program.parent / 'foreign.exe'))):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                probe.require_model_witness({**row, field: value}, 31, 61, 101, program)
        for field in ('retainedProcessHandle', 'imageVerified', 'creationTimeVerified',
                      'hwndVerifiedBefore', 'hwndVerifiedAfter', 'generationVerifiedAfter'):
            with self.subTest(witness=field), self.assertRaises(AssertionError):
                probe.require_model_witness({**row, 'witness': {**row['witness'], field: False}}, 31, 61, 101, program)

    def test_generation_change_stops_before_any_input_or_uno_connection(self):
        self.assertTrue(hasattr(probe, 'retained_generation'), 'The original process generation is not retained across input')
        initial = SimpleNamespace(creation_time=101, handle=17, exited=lambda seconds: False, close=lambda: None)
        entered = []
        with patch.object(probe, 'EngineProcessWitness', return_value=initial), \
                patch.object(probe.accessible, '_owned_process') as bind:
            with self.assertRaisesRegex(AssertionError, 'generation'):
                with probe.retained_generation(61, 31, Path('/owned/soffice.bin'), {}, expected_creation=102):
                    entered.append(True)
        self.assertFalse(entered)
        bind.assert_not_called()

    def test_retained_generation_cleanup_preserves_the_primary_input_failure(self):
        self.assertTrue(hasattr(probe, 'retained_generation'))
        def failed_close():
            raise OSError('secondary retained handle failure')
        initial = SimpleNamespace(creation_time=101, handle=17, exited=lambda seconds: False, close=failed_close)
        checked = SimpleNamespace(creation_time=101, handle=18, exited=lambda seconds: False, close=lambda: None)
        api = SimpleNamespace(user=SimpleNamespace(IsWindow=lambda child: True), pid=lambda child: 31)
        witness = {}
        with patch.object(probe, 'EngineProcessWitness', return_value=initial), \
                patch.object(probe.accessible, '_owned_process', return_value=(api, checked)):
            with self.assertRaisesRegex(RuntimeError, 'primary input failure'):
                with probe.retained_generation(61, 31, Path('/owned/soffice.bin'), witness):
                    raise RuntimeError('primary input failure')
        self.assertIn('secondary retained handle failure', witness['cleanupError'])

    def test_exit_of_the_retained_generation_after_model_read_cannot_pass(self):
        self.assertTrue(hasattr(probe, 'retained_generation'))
        exited = [False]
        initial = SimpleNamespace(creation_time=101, handle=17, exited=lambda seconds: exited[0], close=lambda: None)
        checked = SimpleNamespace(creation_time=101, handle=18, exited=lambda seconds: False, close=lambda: None)
        api = SimpleNamespace(user=SimpleNamespace(IsWindow=lambda child: True), pid=lambda child: 31)
        witness = {}
        with patch.object(probe, 'EngineProcessWitness', return_value=initial), \
                patch.object(probe.accessible, '_owned_process', return_value=(api, checked)):
            with self.assertRaisesRegex(AssertionError, 'generation'):
                with probe.retained_generation(61, 31, Path('/owned/soffice.bin'), witness):
                    exited[0] = True
        self.assertFalse(witness.get('generationVerifiedAfter', False))

    def test_sendinput_observer_passes_the_original_buffer_once_and_retains_short_count(self):
        self.assertIsNotNone(probe)
        class Key(ctypes.Structure):
            _fields_ = [('wVk', ctypes.c_uint16), ('wScan', ctypes.c_uint16),
                        ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32), ('dwExtraInfo', ctypes.c_uint64)]
        class Input(ctypes.Structure):
            _fields_ = [('type', ctypes.c_uint32), ('ki', Key)]
        items = (Input * 2)()
        for item, flags in zip(items, (4, 6)):
            item.type, item.ki.wScan, item.ki.dwFlags = 1, ord('F'), flags
        pointer = ctypes.byref(items)
        native_calls = []
        def original(count, supplied, size):
            native_calls.append((count, supplied is pointer, size))
            return 1
        functions = SimpleNamespace(SendInput=original)
        fake = SimpleNamespace(win32functions=functions, win32structures=SimpleNamespace(INPUT=Input))
        observer = object.__new__(probe.DeliveryObserver)
        observer.calls = []
        observer.snapshot = lambda: {'focus': 51, 'layout': 0x04090409}
        with patch.dict(sys.modules, {'pywinauto': fake}):
            with observer.capture_sendinput():
                inserted = functions.SendInput(2, pointer, ctypes.sizeof(Input))
        self.assertEqual(inserted, 1)
        self.assertEqual(native_calls, [(2, True, ctypes.sizeof(Input))])
        self.assertIs(functions.SendInput, original)
        self.assertEqual(observer.calls[0]['inserted'], 1)
        self.assertEqual([row['scan'] for row in observer.calls[0]['events']], [ord('F'), ord('F')])


if __name__ == '__main__':
    unittest.main()
