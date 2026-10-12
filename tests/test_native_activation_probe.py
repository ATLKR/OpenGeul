"""실제 Windows 관측의 JSON 계약을 검증하며 실패를 성공으로 바꾸지 않는다."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
spec = importlib.util.spec_from_file_location('activation_probe_controller', ROOT/'e2e/native_activation_probe.py')
native_activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native_activation)


class NativeActivationObservationTests(unittest.TestCase):
    def ready(self, mode='owned-file'):
        ownerless = mode == 'ownerless-uri'
        return {'formatVersion': 1, 'event': 'ready', 'mode': mode,
                'observationPhase': 'before-activation',
                'target': native_activation.FONT_URI if 'uri' in mode else 'C:\\임시 폴더\\진단.txt',
                'processId': 4321, 'architecture': 'arm64',
                'callerApartment': 'MTA' if ownerless else 'STA',
                'callerApartmentType': 1 if ownerless else 3,
                'ownerHwnd': 0 if ownerless else 7654,
                'ownerProcessId': 0 if ownerless else 4321,
                'ownerVisible': not ownerless,
                'ownedVisibleWindowCount': 0 if ownerless else 1}

    def result(self, ready, outcome='accepted', hresult=None):
        return {**ready, 'event': 'result', 'outcome': outcome,
                'hresult': hresult, 'errorKind': None if outcome == 'accepted' else 'Other',
                'error': None if outcome == 'accepted' else 'Windows가 열기 요청을 수락하지 않았습니다',
                'elapsedMs': 12}

    def parse(self, ready, result=None, exit_code=0):
        parsed = native_activation.parse_ready(json.dumps(ready).encode(),
                mode=ready['mode'], target=ready['target'], pid=4321, architecture='arm64')
        return native_activation.parse_result(json.dumps(result or self.result(ready)).encode(), parsed,
                                               exit_code=exit_code)

    def test_owned_sta_success_is_only_acceptance_and_preserves_owner(self):
        ready = self.ready()
        observed = self.parse(ready)
        self.assertTrue(observed['accepted'])
        self.assertFalse(observed['externalRenderingVerified'])
        self.assertEqual(observed['ready']['ownerProcessId'], 4321)

    def test_false_or_cancel_is_failed_observation_without_invented_hresult(self):
        ready = self.ready()
        observed = self.parse(ready, self.result(ready, 'error'), exit_code=2)
        self.assertFalse(observed['accepted'])
        self.assertIsNone(observed['result']['hresult'])

    def test_actual_hresult_is_preserved_exactly(self):
        ready = self.ready()
        observed = self.parse(ready, self.result(ready, 'error', -2147467260), exit_code=2)
        self.assertFalse(observed['accepted'])
        self.assertEqual(observed['result']['hresult'], -2147467260)

    def test_ownerless_uri_requires_mta_and_no_owned_visible_window(self):
        ready = self.ready('ownerless-uri')
        self.assertTrue(self.parse(ready)['accepted'])
        for field, bad in [('callerApartment', 'STA'), ('callerApartmentType', 0),
                           ('ownerHwnd', 5), ('ownerProcessId', 4321),
                           ('ownerVisible', True), ('ownedVisibleWindowCount', 1)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                value = {**ready, field: bad};self.parse(value)

    def test_owned_window_must_be_visible_and_belong_to_exact_native_process(self):
        ready = self.ready()
        for field, bad in [('ownerProcessId', 9999), ('ownerHwnd', 0), ('ownerVisible', False),
                           ('ownedVisibleWindowCount', 0), ('processId', True),
                           ('architecture', 'x64'), ('callerApartmentType', 1)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.parse({**ready, field: bad})

    def test_target_is_bound_to_controller_and_uri_is_only_explicit_official_url(self):
        ready = self.ready()
        with self.assertRaises(ValueError):
            native_activation.parse_ready(json.dumps(ready).encode(), mode='owned-file',
                    target='C:\\다른 파일.txt', pid=4321, architecture='arm64')
        for mode in ('owned-uri', 'ownerless-uri'):
            value = self.ready(mode);value['target'] = 'https://example.com'
            with self.subTest(mode=mode), self.assertRaises(ValueError):self.parse(value)

    def test_result_cannot_change_owner_or_claim_success_with_error_or_wrong_exit(self):
        ready = self.ready()
        for field, value in [('ownerProcessId', 99), ('hresult', -2147467260),
                             ('error', '실패'), ('errorKind', 'Other'), ('elapsedMs', True)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.parse(ready, {**self.result(ready), field: value})
        with self.assertRaises(ValueError):self.parse(ready, exit_code=2)
        with self.assertRaises(ValueError):self.parse(ready, self.result(ready, 'error'), exit_code=0)

    def test_result_common_fields_reject_equal_boolean_or_float_values(self):
        ready = self.ready()
        for field, value in [('formatVersion', True), ('ownerVisible', 1),
                             ('callerApartmentType', 3.0), ('ownerHwnd', 7654.0),
                             ('ownedVisibleWindowCount', 1.0), ('observationPhase', 'after-activation')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.parse(ready, {**self.result(ready), field: value})

    def test_duplicate_unknown_or_overlong_json_is_rejected(self):
        ready = self.ready();data = json.dumps(ready).encode()
        for raw in (data[:-1]+b',"processId":4321}',
                    json.dumps({**ready, 'passed': True}).encode(), b' '*32769,
                    b'\xff', b'[]'):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                native_activation.parse_ready(raw, mode=ready['mode'], target=ready['target'],
                                                pid=4321, architecture='arm64')

    def test_error_requires_a_real_bounded_message_and_signed_hresult(self):
        ready = self.ready();result = self.result(ready, 'error')
        for field, value in [('error', ''), ('error', 'x'*8193), ('hresult', True),
                             ('hresult', 2147483648), ('hresult', '0x80004004'),
                             ('outcome', 'passed'), ('errorKind', None)]:
            with self.subTest(field=field, value=str(value)[:20]), self.assertRaises(ValueError):
                self.parse(ready, {**result, field: value}, exit_code=2)


if __name__ == '__main__':unittest.main()
