import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FILE = ROOT / 'paired_print_run.py'
if FILE.exists():
    spec = importlib.util.spec_from_file_location('paired_run_candidate', FILE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
else:
    api = None
import paired_print_contract as core
import paired_print_diagnostic as admission


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'entrypoint absent')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []
        self.canonical = copy.deepcopy(admission.LEGACY_HWP)
        owner = self
        class Inputs:
            def check_asset(self, asset, path):
                owner.events.append(('check', Path(path).name))
                if not Path(path).is_file(): raise core.Rejected(30)
            def download_locked(self, asset, destination):
                owner.events.append(('download', asset['url']))
                Path(destination).write_bytes(b'PINNED-SYNTHETIC')
                return Path(destination)
            def extract_hwp_zip(self, archive, destination, *, limit=512*1024*1024):
                owner.events.append(('extract', Path(archive).name))
                Path(destination).mkdir()
                (Path(destination) / 'OpenGeul.exe').write_bytes(b'EXE-SYNTHETIC')
        self.inputs = Inputs()

    def test_default_missing_legacy_does_not_start_transport_or_extract(self):
        with self.assertRaises(core.Rejected):
            api.acquire_legacy(self.canonical, self.root / 'inputs', self.root / 'runtime',
                               acquire=False, inputs=self.inputs)
        self.assertEqual(self.events, [('check', 'legacy-portable.zip')])

    def test_no_optin_refuses_before_input_or_os_discovery(self):
        from types import SimpleNamespace
        with self.assertRaises(core.Rejected): api.run(SimpleNamespace(run_paired_print=False))
        self.assertEqual(self.events, [])

    def test_optin_transport_uses_only_fixed_canonical_assets_and_checks_before_extract(self):
        self.root.joinpath('inputs').mkdir()
        result = api.acquire_legacy(self.canonical, self.root / 'inputs', self.root / 'runtime',
                                    acquire=True, inputs=self.inputs)
        self.assertEqual(result, self.root / 'runtime/OpenGeul.exe')
        kinds = [x[0] for x in self.events]
        self.assertEqual(kinds, ['download', 'check', 'download', 'check', 'extract', 'check'])
        urls = [x[1] for x in self.events if x[0] == 'download']
        self.assertEqual(urls, [self.canonical['url'], self.canonical['provenanceUrl']])

    def test_changed_canonical_lock_never_reaches_download(self):
        self.canonical['sha256'] = '9' * 64
        with self.assertRaises(core.Rejected):
            api.acquire_legacy(self.canonical, self.root / 'inputs', self.root / 'runtime',
                               acquire=True, inputs=self.inputs)
        self.assertEqual(self.events, [])

    def test_old_archive_bad_result_or_existing_runtime_is_not_adopted(self):
        (self.root / 'runtime').mkdir()
        with self.assertRaises(core.Rejected):
            api.acquire_legacy(self.canonical, self.root / 'inputs', self.root / 'runtime',
                               acquire=True, inputs=self.inputs)
        self.assertEqual(self.events, [])

    def test_once_generated_fixtures_select_only_table_and_basic_hwpx(self):
        table, basic = self.root / 'print-table--300.hwpx', self.root / 'basic.hwpx'
        table.write_bytes(b'ONCE-TABLE'); basic.write_bytes(b'ONCE-BASIC')
        names = ('table--300','table-0','table-600','multipage','basic-hwp','basic-hwpx','page-range','cancel')
        cases = [{'name': n, 'path': table if n != 'basic-hwpx' else basic,
                  'pages': [{'size_pt': [595.28, 841.86]}]} for n in names]
        mapping, bound = api.bind_fixtures(cases)
        self.assertEqual(tuple(mapping), (1, 6))
        self.assertEqual(bound[0]['sha256'], hashlib.sha256(b'ONCE-TABLE').hexdigest())
        self.assertEqual(bound[1]['sha256'], hashlib.sha256(b'ONCE-BASIC').hexdigest())

    def test_duplicate_or_unknown_case_is_not_a_synthetic_input_admission(self):
        with self.assertRaises(core.Rejected): api.bind_fixtures([])

    def test_original_mismatch_is_rethrown_after_collector_and_preserves_identity(self):
        primary, events = ValueError('SYNTHETIC-ONLY'), []
        class Port:
            profile_observations = []
            def raise_original_oracle(self): events.append('raise'); raise primary
        def compare(*args): events.append('compare'); return {'exitCode': 1}
        def collect(*args): events.append('collect'); return {'qualification': False}
        with self.assertRaises(ValueError) as caught:
            api.execute_pair({}, [], Port(), self.root/'private', self.root/'allowlisted',
                             compare=compare, collector=collect)
        self.assertIs(caught.exception, primary)
        self.assertEqual(events, ['compare', 'collect', 'raise'])

    def test_unknown_retirement_does_not_invoke_collector(self):
        events = []
        def bad(*args): raise core.Rejected(15)
        with self.assertRaises(core.Rejected):
            api.execute_pair({}, [], object(), self.root/'private', self.root/'allowlisted',
                             compare=bad, collector=lambda *args: events.append(1))
        self.assertEqual(events, [])


if __name__ == '__main__': unittest.main()
