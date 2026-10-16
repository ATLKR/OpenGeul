"""Evidence policy tests for genuine native Korean composition, independent of Windows."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'korean_ime_smoke.py'
sys.path.insert(0, str(SOURCE.parent))
SPEC = importlib.util.spec_from_file_location('suite_korean_ime_smoke', SOURCE)
ime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ime)


class KoreanImePolicyTests(unittest.TestCase):
    def readiness(self):
        return {'suiteOnly': True, 'capabilityAfter': 'Installed', 'restartNeeded': False,
                  'userLanguageConfigured': True,
                  'profile': {'inputTip': '0412:{A1A1A1A1-1111-2222-3333-444444444444}{B2B2B2B2-1111-2222-3333-444444444444}',
                              'providerClsid': '{A1A1A1A1-1111-2222-3333-444444444444}',
                              'profileGuid': '{B2B2B2B2-1111-2222-3333-444444444444}',
                              'registered': True, 'component': {'signatureStatus': 'Valid',
                              'sha256': 'a' * 64, 'machine': 0x8664,
                              'signerSubject': 'CN=Microsoft Windows, O=Microsoft Corporation, C=US'}}}

    def record(self):
        events = []
        for composition, result in [('ㅎ', ''), ('하', ''), ('한', ''), ('ㄱ', '한'),
                                    ('그', ''), ('글', ''), ('그', ''), ('글', ''), ('', '글')]:
            events.append({'message': 0x10f, 'pid': 31, 'tid': 41, 'hwnd': 51,
                           'layout': 0x0412, 'composition': composition, 'result': result})
        return {'module': 'writer', 'officePid': 31, 'editorTid': 41, 'keyboardFocusHwnd': 51,
                'inputMethod': 'SendInput-scancode', 'unicodeInputUsed': False,
                'keyTokens': list('gksrmf') + ['BACKSPACE', 'f', 'RIGHT'],
                'activeLayout': 0x0412, 'events': events,
                'readiness': self.readiness(),
                'activeProfile': {'activeLanguage': 0x0412,
                                  'activeClsid': '{A1A1A1A1-1111-2222-3333-444444444444}',
                                  'activeProfile': '{B2B2B2B2-1111-2222-3333-444444444444}'},
                'savedText': 'Engine-OpenGeul-writer 한글\nIME-OpenGeul-writer:한글',
                'reopened': {'text': 'Engine-OpenGeul-writer 한글\nIME-OpenGeul-writer:한글'},
                'layoutRestored': True}

    def test_real_dubeolsik_commit_backspace_save_and_reopen_satisfy_policy(self):
        result = ime.validate_ime_evidence(self.record())
        self.assertTrue(result['imeVerified'])
        self.assertTrue(result['backspaceCompositionVerified'])

    def test_unicode_only_input_cannot_claim_ime(self):
        for patch in ({'inputMethod': 'Unicode-SendInput'}, {'unicodeInputUsed': True},
                      {'keyTokens': ['한글']}, {'events': []}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.validate_ime_evidence({**self.record(), **patch})

    def test_missing_or_different_tsf_profile_is_not_microsoft_ime_evidence(self):
        for patch in ({'activeProfile': {}}, {'readiness': {}},
                      {'activeProfile': {'activeLanguage': 0x0412, 'activeClsid': '{UNVERIFIED}',
                                         'activeProfile': '{B2B2B2B2-1111-2222-3333-444444444444}'}}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.validate_ime_evidence({**self.record(), **patch})

    def test_foreign_process_or_thread_composition_cannot_satisfy_policy(self):
        for key in ('pid', 'tid', 'hwnd', 'layout'):
            record = self.record()
            for event in record['events']: event[key] = 123
            with self.subTest(key=key), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_saved_preexisting_korean_without_distinct_new_marker_is_rejected(self):
        for key in ('savedText', 'reopened'):
            record = self.record()
            record[key] = 'Engine-OpenGeul-writer 한글' if key == 'savedText' else {'text': 'Engine-OpenGeul-writer 한글'}
            with self.subTest(key=key), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_missing_backspace_transition_and_missing_commit_are_rejected(self):
        for index in (6, 8):
            record = self.record()
            del record['events'][index]
            with self.subTest(index=index), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_calc_reopen_must_preserve_formula_and_original_marker(self):
        record = self.record()
        record.update(module='calc', savedText=record['savedText'].replace('writer', 'calc'))
        record['reopened'] = {'text': record['savedText'], 'formula': '=SUM(B1:C1)', 'value': 42}
        self.assertTrue(ime.validate_ime_evidence(record)['imeVerified'])
        record['reopened']['value'] = 0
        with self.assertRaises(AssertionError): ime.validate_ime_evidence(record)

    def test_incomplete_or_unsigned_readiness_cannot_enable_real_input(self):
        record = self.readiness()
        self.assertEqual(ime.require_readiness(record), record)
        for patch in ({'capabilityAfter': 'NotPresent'}, {'restartNeeded': True}, {'userLanguageConfigured': False}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.require_readiness({**record, **patch})
        unsigned = copy.deepcopy(record)
        unsigned['profile']['component']['signatureStatus'] = 'NotSigned'
        with self.assertRaises(AssertionError): ime.require_readiness(unsigned)

    def test_physical_sequence_contains_scancodes_and_never_vk_packet(self):
        events = ime.scan_events(list('gksrmf') + ['BACKSPACE', 'f', 'RIGHT'])
        self.assertEqual(len(events), 18)
        self.assertTrue(all(row['vk'] == 0 and row['flags'] & 8 and not row['flags'] & 4 for row in events))
        self.assertEqual([row['scan'] for row in events[::2]], [0x22, 0x25, 0x1f, 0x13, 0x32, 0x21, 0x0e, 0x21, 0x4d])
        with self.assertRaises(ValueError): ime.scan_events(['한글'])


if __name__ == '__main__': unittest.main()
