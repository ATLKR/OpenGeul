"""Offline contracts for reconstructing metadata and safely explaining readback."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.find_spec('store_metadata_readback')
if SPEC is not None:
    import store_metadata_readback as readback
else:
    readback = None
import store_submit as writer


class MetadataReadbackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(readback, 'The read-only metadata diagnostic is missing')
        self.pending = '1152921505702500000'
        self.state = {
            'app_id': '9PJH0T3PHRMF', 'phase': 'draft_ready', 'tag': 'v1.1.3',
            'submission_id': self.pending, 'baseline_id': '1152921505702042424',
            'source_sha': 'a' * 40, 'release_id': '410953892', 'run_id': '38294374822',
            'source_asset_fingerprint_sha256': 'b' * 64,
            'source_msix_sha256_by_arch': {'x64': 'c' * 64, 'arm64': 'd' * 64},
            'store_msix_sha256_by_arch': {'x64': 'e' * 64, 'arm64': 'f' * 64},
        }
        self.baseline = {
            'id': self.state['baseline_id'], 'status': 'Published',
            'statusDetails': {}, 'friendlyName': 'Private baseline name',
            'fileUploadUrl': 'https://private.example/upload?sig=PRIVATE_SECRET',
            'targetPublishMode': 'Manual', 'targetPublishDate': None,
            'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'US': 'Base'}},
            'listings': {'ko-kr': {'baseListing': {
                'title': 'OpenGeul', 'description': '기존 설명', 'features': ['기존 기능'],
                'releaseNotes': '기존 변경 사항', 'images': [],
            }}},
            'notesForCertification': 'Keep human notes\nOpenGeul request stale',
            'applicationPackages': [{
                'id': '11', 'fileName': 'old.msix', 'fileStatus': 'Uploaded',
                'version': '1.1.1.0', 'architecture': 'X64',
                'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None',
            }],
            'packageDeliveryOptions': {'isMandatoryUpdate': False},
        }

    def reconstructed(self):
        return readback.expected_metadata(copy.deepcopy(self.baseline), copy.deepcopy(self.state))

    def actual_for(self, expected):
        return dict(copy.deepcopy(expected), id=self.pending, status='PendingCommit')

    def test_reconstructs_production_metadata_without_mutating_baseline(self):
        original = copy.deepcopy(self.baseline)
        expected, details = self.reconstructed()
        self.assertEqual(self.baseline, original)
        self.assertEqual(expected['targetPublishMode'], 'Immediate')
        self.assertEqual(expected['pricing'], original['pricing'])
        self.assertEqual(expected['packageDeliveryOptions'], original['packageDeliveryOptions'])
        for field in ('id', 'status', 'statusDetails', 'fileUploadUrl', 'friendlyName'):
            self.assertNotIn(field, expected)
        packages = expected['applicationPackages']
        self.assertEqual(packages[0], dict(original['applicationPackages'][0], fileStatus='PendingDelete'))
        self.assertEqual(packages[1:], [
            {'fileName': 'OpenGeul_1.1.3.0_x64_store-unsigned.msix', 'fileStatus': 'PendingUpload',
             'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None'},
            {'fileName': 'OpenGeul_1.1.3.0_arm64_store-unsigned.msix', 'fileStatus': 'PendingUpload',
             'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None'},
        ])
        reviewed = writer.apply_korean_listing(original)['listings']
        self.assertEqual(expected['listings'], reviewed)
        self.assertEqual(expected['notesForCertification'].splitlines(), ['Keep human notes', writer._marker(details)])

    def test_exact_readback_passes_all_six_production_conditions(self):
        expected, details = self.reconstructed()
        result = readback.comparison(expected, self.actual_for(expected), details, self.pending)
        for name in ('id', 'status', 'marker', 'packages', 'pricing', 'listings'):
            self.assertIs(result['conditions'][name], True, name)
        self.assertEqual(result['leafDifferences'], [])

    def test_backend_requirement_normalization_fails_package_confirmation(self):
        expected, details = self.reconstructed()
        for change in ('changed', 'unset'):
            with self.subTest(change=change):
                actual = self.actual_for(expected)
                if change == 'changed':
                    actual['applicationPackages'][1]['minimumSystemRam'] = '1GB'
                else:
                    actual['applicationPackages'][1].pop('minimumSystemRam')
                result = readback.comparison(expected, actual, details, self.pending)
                self.assertIs(result['conditions']['packages'], False)
                self.assertIs(result['conditions']['pricing'], True)
                self.assertIs(result['conditions']['listings'], True)

    def test_listing_and_pricing_differences_keep_paths_and_hashes_without_values(self):
        expected, details = self.reconstructed()
        actual = self.actual_for(expected)
        actual['listings']['ko-kr']['baseListing']['description'] = 'PRIVATE_SECRET https://private.example/?sig=PRIVATE_SECRET'
        actual['pricing']['marketSpecificPricings']['US'] = 'PRIVATE_SECRET'
        result = readback.comparison(expected, actual, details, self.pending)
        self.assertIs(result['conditions']['listings'], False)
        self.assertIs(result['conditions']['pricing'], False)
        diffs = result['leafDifferences']
        self.assertEqual(len(diffs), 2)
        paths = json.dumps([diff['path'] for diff in diffs])
        self.assertIn('description', paths)
        self.assertIn('US', paths)
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE_SECRET', serialized)
        self.assertNotIn('https://', serialized)
        for diff in diffs:
            for side in ('expected', 'actual'):
                self.assertRegex(diff[side]['sha256'], r'^[a-f0-9]{64}$')
                self.assertIn('type', diff[side])

    def test_missing_leaf_and_null_leaf_are_distinct(self):
        expected, details = self.reconstructed()
        expected['listings']['ko-kr']['baseListing']['releaseNotes'] = None
        actual = self.actual_for(expected)
        del actual['listings']['ko-kr']['baseListing']['releaseNotes']
        result = readback.comparison(expected, actual, details, self.pending)
        self.assertIs(result['conditions']['listings'], False)
        self.assertEqual(len(result['leafDifferences']), 1)
        diff = result['leafDifferences'][0]
        self.assertNotEqual(diff['expected'], diff['actual'])

    def test_unknown_key_paths_and_package_url_names_are_not_emitted(self):
        expected, details = self.reconstructed()
        actual = self.actual_for(expected)
        actual['pricing']['https://private.example/?sig=PRIVATE_SECRET'] = None
        actual['applicationPackages'][1]['fileName'] = 'https://private.example/PRIVATE_SECRET.msix?sig=PRIVATE_SECRET'
        result = readback.comparison(expected, actual, details, self.pending)
        serialized = json.dumps(result)
        self.assertIs(result['conditions']['packages'], False)
        self.assertIs(result['conditions']['pricing'], False)
        self.assertNotIn('PRIVATE_SECRET', serialized)
        self.assertNotIn('https://', serialized)
        self.assertRegex(serialized, r'[a-f0-9]{64}')

    def test_unknown_ascii_secret_keys_and_noncanonical_filenames_are_hashed(self):
        expected, details = self.reconstructed()
        actual = self.actual_for(expected)
        actual['pricing']['PRIVATE_SECRET'] = None
        actual['listings']['ko-kr']['baseListing']['PRIVATE_SECRET'] = 'hidden'
        actual['applicationPackages'][1]['fileName'] = 'PRIVATE_SECRET.msix'
        result = readback.comparison(expected, actual, details, self.pending)
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE_SECRET', serialized)
        self.assertNotIn('old.msix', serialized)
        self.assertIn('OpenGeul_1.1.3.0_x64_store-unsigned.msix', serialized)
        self.assertIs(result['conditions']['packages'], False)

    def test_strict_bounded_json_decode_rejects_duplicates_nonfinite_and_oversize(self):
        for raw in (b'{"id":"one","id":"two"}', b'{"nested":{"x":1,"x":2}}',
                    b'{"value":NaN}', b'{"value":Infinity}', b' ' * (1024 * 1024 + 1)):
            with self.subTest(bodyBytes=len(raw)):
                with self.assertRaises(ValueError):
                    readback.decode(raw)
        self.assertEqual(readback.decode(b'{"value":null}'), {'value': None})


if __name__ == '__main__':
    unittest.main()
