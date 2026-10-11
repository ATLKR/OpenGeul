import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / 'probe/hwp-picker-editor57.py'
SPEC = importlib.util.spec_from_file_location('picker_observation57', PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class PickerObservation57Tests(unittest.TestCase):
    def observation(self, root):
        observed = probe.PickerObservation.__new__(probe.PickerObservation)
        observed.root = root
        observed.output = root / 'evidence'
        observed.output.mkdir()
        observed.exe = root / 'OpenGeul.exe'
        observed.exe.write_bytes(b'owned diagnostic exe')
        observed.protected = root / 'protected.hwp'
        observed.original = root / 'original.hwp'
        observed.protected.write_bytes(b'owned encrypted fixture')
        observed.original.write_bytes(observed.protected.read_bytes())
        observed.encrypted = {'sha256': probe.sha(observed.original)}
        observed.started = time.monotonic()
        observed.stage = 'verified-inputs'
        observed.records = []
        observed.session = Mock()
        observed.session.page = None
        return observed

    def run_observation(self, observed):
        with patch.object(probe, 'EDITOR_BYTES', observed.exe.stat().st_size), \
             patch.object(probe, 'EDITOR_SHA', probe.sha(observed.exe)), patch('builtins.print'):
            code = observed.run()
        return code, json.loads((observed.output / 'picker-result.json').read_text())

    def test_never_ready_picker_preserves_stage_and_failure_metadata_without_success(self):
        with tempfile.TemporaryDirectory() as temp:
            observed = self.observation(Path(temp))
            def fail():
                observed.mark('request-first-hwp-save-as')
                (observed.output / 'native-picker-readiness.json').write_text('{"pid":123,"hwnd":456,"class":"#32770"}')
                raise AssertionError('Condition timed out after 20s; filename edit found 0')
            observed.exercise = fail
            code, result = self.run_observation(observed)
            self.assertEqual(code, 1)
            self.assertFalse(result['pickerObservationPassed'])
            self.assertFalse(result['qualification'])
            self.assertEqual(result['error']['stage'], 'request-first-hwp-save-as')
            self.assertIn('filename edit found 0', result['error']['message'])
            self.assertTrue((observed.output / 'native-picker-readiness.json').is_file())
            observed.session.close.assert_called_once()

    def test_real_sequence_stops_at_first_picker_failure_before_consent_or_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            observed = self.observation(Path(temp))
            observed.documents = Path(temp)
            observed.plaintext = Path(temp) / 'separate.hwp'
            observed.manifest = {'password': 'OpenGeul-native-123456', 'expectedText': 'owned content'}
            session = observed.session
            session.page = Mock()
            session.dialogs = []
            session.page.evaluate.return_value = True
            session.page.title.return_value = '• protected.hwp — OpenGeul'
            dialog = session.page.get_by_role.return_value
            dialog.count.return_value = 1
            password = Mock()
            password.input_value.return_value = ''
            error = Mock()
            error.inner_text.return_value = '비밀번호가 일치하지 않습니다. 다시 입력하세요.'
            dialog.locator.side_effect = lambda selector: password if selector == '#hwp-password-input' else error
            observed.Session = Mock(return_value=session)
            observed.edit = Mock()
            observed.menu = Mock()
            observed.acknowledge_block = Mock()
            observed.accept_consent = Mock()
            calls = []
            def picker(target):
                calls.append(target)
                if target == observed.plaintext:
                    session.folder = observed.output / 'session'
                    session.folder.mkdir()
                    (session.folder / 'native-picker-readiness.json').write_text('{"pid":123,"hwnd":456}')
                    raise AssertionError('strict filename readiness found 0 Edit')
            session.native_dialog.side_effect = picker
            code, result = self.run_observation(observed)
            self.assertEqual(code, 1)
            self.assertEqual(calls, [observed.protected, observed.plaintext])
            self.assertEqual([call.args[1] for call in observed.menu.call_args_list],
                             ['file:open', 'file:save', 'file:save-as'])
            observed.accept_consent.assert_not_called()
            observed.Session.assert_called_once()
            self.assertEqual(result['error']['stage'], 'request-first-hwp-save-as')
            self.assertFalse(observed.plaintext.exists())
            self.assertTrue((session.folder / 'native-picker-readiness.json').is_file())

    def test_cleanup_failure_preserves_original_picker_error_and_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            observed = self.observation(Path(temp))
            observed.exercise = Mock(side_effect=ValueError('strict picker ownership failure'))
            observed.session.close.side_effect = OSError('cleanup did not complete')
            code, result = self.run_observation(observed)
            self.assertEqual(code, 1)
            self.assertEqual(result['error']['type'], 'ValueError')
            self.assertEqual(result['cleanupError']['type'], 'OSError')
            self.assertFalse(result['pickerObservationPassed'])

    def test_gui_completion_cannot_pass_if_protected_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            observed = self.observation(Path(temp))
            observed.exercise = lambda: observed.protected.write_bytes(b'changed source')
            code, result = self.run_observation(observed)
            self.assertEqual(code, 1)
            self.assertFalse(result['protectedSourceUnchanged'])
            self.assertFalse(result['pickerObservationPassed'])

    def test_success_is_explicitly_only_picker_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            observed = self.observation(Path(temp))
            observed.exercise = lambda: observed.mark('picker-observation-complete', freshReopenWithoutPassword=True)
            code, result = self.run_observation(observed)
            self.assertEqual(code, 0)
            self.assertTrue(result['pickerObservationPassed'])
            self.assertFalse(result['qualification'])
            self.assertNotIn('success', result)
            self.assertNotIn('expectedTests', result)
            self.assertEqual(result['sourceCommit'], probe.SOURCE)
            self.assertEqual(result['sourceRun'], probe.SOURCE_RUN)


if __name__ == '__main__':
    unittest.main()
