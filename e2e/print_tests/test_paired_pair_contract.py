"""Portable admission/orchestration tests; OS printing is an explicit port."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'paired_print_contract.py'
api = None
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('paired_contract_candidate', SOURCE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)


def font_state():
    return {'scopeCode': 1, 'files': [
        {'fontCode': 1, 'present': True, 'bytes': 100, 'sha256': '1' * 64, 'volume': 1, 'fileId': 2, 'modifiedNs': 3},
        {'fontCode': 2, 'present': False, 'bytes': 0, 'sha256': None, 'volume': 0, 'fileId': 0, 'modifiedNs': 0},
    ]}


class Port:
    """Synthetic external Windows observations, not a product/API substitute."""
    def __init__(self):
        self.calls = []
        self.observations = []
        self.font_calls = 0
        self.change_font_at = None
        self.mutate = None
        self.cancellation = None
        self.oracle_passed = False

    def font_snapshot(self):
        self.font_calls += 1
        row = font_state()
        if self.font_calls == self.change_font_at:
            row['files'][0]['sha256'] = '2' * 64
        return row

    def print_case(self, renderer, fixture):
        self.calls.append((renderer['roleCode'], fixture['caseCode']))
        if self.cancellation is not None:
            raise self.cancellation
        row = {
            'roleCode': renderer['roleCode'], 'caseCode': fixture['caseCode'],
            'harnessSourceCommit': renderer['harnessSourceCommit'],
            'harnessRunId': renderer['harnessRunId'],
            'harnessRunAttempt': renderer['harnessRunAttempt'],
            'appSourceCommit': renderer['appSourceCommit'],
            'executableSha256': renderer['executableSha256'],
            'executableBytes': renderer['executableBytes'],
            'wasmProvenanceSha256': renderer['wasmSha256'],
            'fixtureBeforeSha256': fixture['sha256'],
            'fixtureAfterSha256': fixture['sha256'],
            'pdfCreated': True, 'spoolerCompleted': True, 'paperValidated': True,
            'originalOraclePassed': self.oracle_passed,
            'primaryErrorCode': 0 if self.oracle_passed else 1,
            'raster': {'pixels': [1786, 2526], 'bbox': [264, 306, 1526, 430], 'ink': 12889, 'maskSha256': '3' * 64},
            'retainedRootExited': True, 'retainedWebviewCount': 2,
            'retainedWebviewsExited': True, 'cleanupMayBeForced': True,
            'pdfSha256': '5' * 64, 'pdfBytes': 100, 'pngSha256': '6' * 64, 'pngBytes': 200,
        }
        if self.mutate is not None:
            self.mutate(row)
        self.observations.append(copy.deepcopy(row))
        return row


class PairContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'paired diagnostic contract is absent')
        self.expected = api.expected_renderers(
            harness_source='a' * 40, run_id=17, attempt=1,
            current_editor_sha256='b' * 64, current_editor_bytes=300,
            current_wasm_sha256='c' * 64, current_js_sha256='d' * 64,
        )
        self.fixtures = [{'caseCode': 1, 'sha256': 'e' * 64, 'bytes': 200},
                         {'caseCode': 6, 'sha256': 'f' * 64, 'bytes': 300}]
        self.port = Port()

    def run_pair(self):
        return api.run_comparison(self.expected, self.fixtures, self.port)

    def reject_mutation(self, mutation):
        self.port.mutate = mutation
        with self.assertRaises(api.Rejected):
            self.run_pair()
        self.assertEqual(self.port.calls, [(1, 1)])

    def test_oracle_failure_is_preserved_and_both_roles_are_observed_once(self):
        row = self.run_pair()
        self.assertEqual(self.port.calls, [(1, 1), (1, 6), (2, 1), (2, 6)])
        self.assertTrue(row['observationComplete'])
        self.assertFalse(row['originalOracleAllPassed'])
        self.assertEqual(row['exitCode'], 1)
        self.assertFalse(row['acceptanceEligible'])
        self.assertFalse(row['sourceQualified'])
        self.assertEqual([x['primaryErrorCode'] for x in row['observations']], [1, 1, 1, 1])

    def test_even_all_oracles_passing_never_creates_qualification(self):
        self.port.oracle_passed = True
        row = self.run_pair()
        self.assertTrue(row['originalOracleAllPassed'])
        self.assertEqual(row['exitCode'], 0)
        self.assertFalse(row['qualification'])
        self.assertFalse(row['acceptanceEligible'])

    def test_renderer_source_and_current_harness_binding_remain_distinct(self):
        row = self.run_pair()
        self.assertEqual(row['harnessSourceCommit'], 'a' * 40)
        self.assertEqual(row['renderers'][0]['appSourceCommit'], '131ccbf3ac10a82e1d6785b4c906fb836b912e73')
        self.assertEqual(row['renderers'][1]['appSourceCommit'], 'a' * 40)
        self.assertFalse(row['legacyIsGoldenProducer'])

    def test_wrong_binary_stops_before_another_print(self):
        self.reject_mutation(lambda r: r.update(executableSha256='0' * 64))

    def test_historical_renderer_cannot_relabel_the_current_harness_source(self):
        self.reject_mutation(lambda r: r.update(harnessSourceCommit='131ccbf3ac10a82e1d6785b4c906fb836b912e73'))

    def test_wrong_current_run_attempt_cannot_supply_observations(self):
        self.reject_mutation(lambda r: r.update(harnessRunAttempt=2))

    def test_wrong_current_run_cannot_supply_observations(self):
        self.reject_mutation(lambda r: r.update(harnessRunId=18))

    def test_noninteger_process_count_is_not_retirement_evidence(self):
        self.reject_mutation(lambda r: r.update(retainedWebviewCount=True))

    def test_wrong_legacy_label_cannot_borrow_current_source_identity(self):
        self.reject_mutation(lambda r: r.update(appSourceCommit='a' * 40))

    def test_current_wasm_provenance_cannot_be_relabelled_as_legacy(self):
        self.reject_mutation(lambda r: r.update(wasmProvenanceSha256='c' * 64))

    def test_fixture_changed_by_printing_stops_the_pair(self):
        self.reject_mutation(lambda r: r.update(fixtureAfterSha256='9' * 64))

    def test_wrong_fixture_is_not_an_expected_hash_source(self):
        self.reject_mutation(lambda r: r.update(fixtureBeforeSha256='9' * 64, fixtureAfterSha256='9' * 64))

    def test_unknown_success_field_does_not_upgrade_diagnostic_receipt(self):
        self.reject_mutation(lambda r: r.update(success=True))

    def test_unobserved_actual_force_claim_is_not_accepted_as_cleanup_scope(self):
        self.reject_mutation(lambda r: r.update(cleanupForced=True))

    def test_boolean_ink_is_not_an_integer(self):
        self.reject_mutation(lambda r: r['raster'].update(ink=True))

    def test_foreign_role_and_case_observation_are_rejected(self):
        self.reject_mutation(lambda r: r.update(roleCode=2, caseCode=6))

    def test_original_process_retirement_is_required_before_next_role(self):
        self.reject_mutation(lambda r: r.update(retainedRootExited=False))

    def test_webview_retirement_is_required_even_if_the_root_exited(self):
        self.reject_mutation(lambda r: r.update(retainedWebviewsExited=False))

    def test_empty_webview_inventory_cannot_claim_retirement(self):
        self.reject_mutation(lambda r: r.update(retainedWebviewCount=0))

    def test_pdf_missing_cannot_become_an_ink_mismatch(self):
        self.reject_mutation(lambda r: r.update(pdfCreated=False))

    def test_uncompleted_spooler_cannot_become_an_ink_mismatch(self):
        self.reject_mutation(lambda r: r.update(spoolerCompleted=False))

    def test_media_failure_cannot_become_an_ink_mismatch(self):
        self.reject_mutation(lambda r: r.update(paperValidated=False))

    def test_oracle_pass_boolean_and_primary_code_must_agree(self):
        self.reject_mutation(lambda r: r.update(originalOraclePassed=True))

    def test_font_change_halts_before_the_next_session(self):
        self.port.change_font_at = 2
        with self.assertRaises(api.Rejected):
            self.run_pair()
        self.assertEqual(self.port.calls, [(1, 1)])

    def test_missing_font_is_recorded_without_claiming_actual_selection(self):
        row = self.run_pair()
        self.assertFalse(row['actualSelectedFontIdentityKnown'])
        self.assertTrue(row['sampledFontFilesStable'])

    def test_fixture_subset_and_duplicate_cannot_replace_the_fixed_pair(self):
        self.fixtures = self.fixtures[:1]
        with self.assertRaises(api.Rejected):
            self.run_pair()
        self.assertEqual(self.port.calls, [])

    def test_cancellation_propagates_without_more_prints(self):
        primary = KeyboardInterrupt()
        self.port.cancellation = primary
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.run_pair()
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.port.calls, [(1, 1)])

    def test_invalid_external_source_is_rejected_before_port_use(self):
        with self.assertRaises(api.Rejected):
            api.expected_renderers(harness_source='not-a-sha', run_id=17, attempt=1,
                                   current_editor_sha256='b' * 64, current_editor_bytes=300,
                                   current_wasm_sha256='c' * 64, current_js_sha256='d' * 64)
        self.assertEqual(self.port.calls, [])

    def test_boolean_legacy_role_is_not_silently_normalized_to_integer_one(self):
        self.expected['renderers'][0]['roleCode'] = True
        with self.assertRaises(api.Rejected):
            self.run_pair()
        self.assertEqual(self.port.calls, [])

    def test_current_binary_cannot_be_the_legacy_binary(self):
        with self.assertRaises(api.Rejected):
            api.expected_renderers(harness_source='a' * 40, run_id=17, attempt=1,
                                   current_editor_sha256='aa34b05cd63cef8fe880ca3697661270d47afd42bf5ce1e0b7c3b6f5f3450be8',
                                   current_editor_bytes=36402688,
                                   current_wasm_sha256='c' * 64, current_js_sha256='d' * 64)


if __name__ == '__main__':
    unittest.main()
