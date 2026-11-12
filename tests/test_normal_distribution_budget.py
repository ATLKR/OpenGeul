"""Normal Source budget behavior, closed sizes and unchanged Store boundaries."""
import base64
import copy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ('scripts', 'e2e', 'tests', 'ci')]
import release_pair as pair
import store_package
import store_qualification
import native_wack_transport as transport
import test_native_wack_transport as transport_fixture
import test_release_pair as pair_fixture

MIB = 1024 * 1024


class NormalDistributionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def sparse(self, name, size):
        path = self.root / name
        with path.open('wb') as stream:
            stream.truncate(size)
        return path

    def budget_result(self, paths, cap):
        try:
            return 1, pair.budget(paths, cap)
        except ValueError:
            return 0, 0

    def fixture(self):
        fixture = pair_fixture.ReleasePairTests('test_valid_pair_preserves_original_bytes_and_exact_22_assets')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_observed_x64_distribution_is_admitted_by_normal_budget(self):
        path = self.sparse('normal.bin', 111553816)
        self.assertEqual(self.budget_result([path], pair.ARCH_LIMIT), (1, 111553816))

    def test_normal_arch_128mib_is_admitted_and_one_more_byte_rejected(self):
        path = self.sparse('normal.bin', 134217728)
        self.assertEqual(self.budget_result([path], pair.ARCH_LIMIT), (1, 134217728))
        with path.open('r+b') as stream:
            stream.truncate(134217729)
        self.assertEqual(self.budget_result([path], pair.ARCH_LIMIT), (0, 0))

    def test_normal_pair_admits_both_observed_required_distributions(self):
        paths = [self.sparse('x64.bin', 111553816), self.sparse('arm64.bin', 104472912)]
        self.assertEqual(self.budget_result(paths, pair.PAIR_LIMIT), (1, 216026728))

    def test_normal_pair_256mib_is_admitted_and_one_more_byte_rejected(self):
        paths = [self.sparse('x64.bin', 134217728), self.sparse('arm64.bin', 134217728)]
        self.assertEqual(self.budget_result(paths, pair.PAIR_LIMIT), (1, 268435456))
        with paths[1].open('r+b') as stream:
            stream.truncate(134217729)
        self.assertEqual(self.budget_result(paths, pair.PAIR_LIMIT), (0, 0))

    def test_shared_source_metadata_admits_observed_pair_without_store_write(self):
        release = {'draft': False, 'tag_name': 'v1.1.4', 'assets': [
            {'name': 'normal-x64.msix', 'size': 111553816},
            {'name': 'normal-arm64.msix', 'size': 104472912}]}
        try:
            count = len(store_package._release_assets('v1.1.4', release))
        except ValueError:
            count = 0
        self.assertEqual(count, 2)

    def test_shared_source_metadata_rejects_256mib_plus_one(self):
        release = {'draft': False, 'tag_name': 'v1.1.4', 'assets': [
            {'name': 'normal-x64.msix', 'size': 134217728},
            {'name': 'normal-arm64.msix', 'size': 134217729}]}
        with self.assertRaises(ValueError):
            store_package._release_assets('v1.1.4', release)

    def test_store_qualification_still_rejects_96mib_plus_one_before_json_or_api(self):
        folder = self.root / 'store'
        folder.mkdir()
        with (folder / 'store.msix').open('wb') as stream:
            stream.truncate(100663297)
        with self.assertRaisesRegex(ValueError, '한도'):
            store_qualification._store(folder, {})

    def test_full_pair_above_old_budget_preserves_exact_roles_and_all_qualification(self):
        fixture = self.fixture()
        for arch, total in [('x64', 111553816), ('arm64', 104472912)]:
            folder = fixture.packages[arch]
            help_path = folder / 'rhwp-help.txt'
            other_size = sum(p.stat().st_size for p in folder.iterdir() if p != help_path)
            with help_path.open('wb') as stream:
                stream.truncate(total - other_size)
            fixture.sums(folder)
            self.assertEqual(sum(p.stat().st_size for p in folder.iterdir()), total)
        fixture.rebind_split()
        observed = fixture.assemble()
        self.assertEqual(pair.verify_pair(fixture.output), observed)
        self.assertEqual(len(list(fixture.output.iterdir())), 22)
        self.assertGreater(sum(p.stat().st_size for p in fixture.output.iterdir()), 201326592)
        for arch in ('x64', 'arm64'):
            self.assertEqual(pair.sha(fixture.output / ('rhwp-help-' + arch + '.txt')),
                             pair.sha(fixture.packages[arch] / 'rhwp-help.txt'))

    def test_architecture_budget_includes_raw_wack_before_any_output(self):
        fixture = self.fixture()
        folder = fixture.packages['x64']
        help_path = folder / 'rhwp-help.txt'
        other_size = sum(p.stat().st_size for p in folder.iterdir() if p != help_path)
        wack_size = sum(p.stat().st_size for p in fixture.wacks['x64'].iterdir())
        with help_path.open('wb') as stream:
            stream.truncate(134217729 - other_size - wack_size)
        self.assertLessEqual(sum(p.stat().st_size for p in folder.iterdir()), 134217728)
        with self.assertRaisesRegex(ValueError, '고정 릴리스 바이트 한도'):
            fixture.assemble()
        self.assertFalse(fixture.output.exists())

    def test_pair_reader_counts_global_metadata_in_256mib_total(self):
        fixture = self.fixture()
        fixture.assemble()
        metadata = fixture.output / 'provenance.json'
        other_size = sum(p.stat().st_size for p in fixture.output.iterdir() if p != metadata)
        with metadata.open('wb') as stream:
            stream.truncate(268435457 - other_size)
        with self.assertRaisesRegex(ValueError, '고정 릴리스 바이트 한도'):
            pair.verify_pair(fixture.output)

    def test_numeric_sizes_expose_over_cap_without_truncating_any_role(self):
        fixture = self.fixture()
        sizes = getattr(pair, 'distribution_sizes', None)
        self.assertTrue(callable(sizes), 'Closed numeric size operation is missing')
        folder = fixture.packages['x64']
        with (folder / 'rhwp-help.txt').open('wb') as stream:
            stream.truncate(134217729)
        result = sizes(folder, 'x64')
        self.assertEqual(result['cliHelpBytes'], 134217729)
        self.assertGreater(result['totalBytes'], 134217728)
        self.assertEqual(result['withinBudget'], 0)

    def test_unsigned_source_file_map_128_is_distinct_from_store_and_signed_96(self):
        self.assertIn('scope', inspect.signature(transport._files).parameters,
                      'Unsigned Source budget needs an explicit verified scope')
        folder = self.root / 'unsigned'
        folder.mkdir()
        with (folder / 'normal.bin').open('wb') as stream:
            stream.truncate(134217728)
        self.assertEqual(transport._files(folder, scope='source')['normal.bin']['bytes'], 134217728)
        for scope in ('store', None):
            with self.assertRaises(ValueError):
                transport._files(folder, scope=scope)
        with (folder / 'normal.bin').open('r+b') as stream:
            stream.truncate(134217729)
        with self.assertRaises(ValueError):
            transport._files(folder, scope='source')

    def test_source_unsigned_archive_expansion_accepts_above96_but_store_rejects(self):
        self.assertIn('scope', inspect.signature(transport._unsigned_archive).parameters,
                      'Unsigned ZIP expansion needs a verified scope')
        path = self.sparse('normal.bin', 100663297)
        archive_path = self.root / 'input.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, 'normal.bin')
        files = {'normal.bin': {'bytes': 100663297, 'sha256': pair.sha(path)}}
        transport._unsigned_archive(archive_path.read_bytes(), files, scope='source')
        with self.assertRaises(ValueError):
            transport._unsigned_archive(archive_path.read_bytes(), files, scope='store')

    def test_source_unsigned_archive_expansion_rejects_128mib_plus_one(self):
        path = self.sparse('normal.bin', 134217729)
        archive_path = self.root / 'input.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, 'normal.bin')
        with self.assertRaisesRegex(ValueError, '원본 ZIP 파일 수/확장'):
            transport._unsigned_archive(archive_path.read_bytes(),
                {'normal.bin': {'bytes': 134217729, 'sha256': '0' * 64}}, scope='source')

    def test_actual_github_adapter_keeps_signed96_and_reads_source128_only_by_scope(self):
        self.assertIn('unsigned_scope', inspect.signature(transport.GitHub.zip).parameters,
                      'Actual transport read must receive the unsigned scope')
        backend = transport.GitHub()
        observed = []
        def bounded_read(path, cap):
            observed.append((path, cap))
            return b'synthetic'
        with patch.object(backend, '_bytes', side_effect=bounded_read):
            for scope, expected in [(None, 100663296), ('source', 134217728), ('store', 100663296)]:
                self.assertEqual(backend.zip(100, unsigned_scope=scope), b'synthetic')
                self.assertEqual(observed[-1], ('actions/artifacts/100/zip', expected))
            before = len(observed)
            with self.assertRaises(ValueError):
                backend.zip(100, unsigned_scope='foreign')
            self.assertEqual(len(observed), before)

    @staticmethod
    def sized_metadata(origin, size):
        origin = copy.deepcopy(origin)
        origin['artifact']['size_in_bytes'] = size
        raw = pair.encoded(origin['artifact'])
        origin['metadata'] = {'rawBase64': base64.b64encode(raw).decode(), 'bytes': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest()}
        return origin

    def transport_case(self):
        fixture = transport_fixture.NativeJoinTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_source_unsigned_metadata_replay_above96_passes_both_existing_proof_boundaries(self):
        fixture = self.transport_case()
        native, origin = copy.deepcopy(fixture.native), copy.deepcopy(fixture.origin)
        source = self.sized_metadata(origin['unsigned'], 104472912)
        native['producer']['unsigned'] = copy.deepcopy(source)
        origin['unsigned'] = copy.deepcopy(source)
        origin['nativeJsonSha256'] = hashlib.sha256(pair.encoded(native) + b'\n').hexdigest()
        try:
            transport._producer_proof(native, fixture.binding, 'source')
            transport._origin_proof(origin, native, fixture.binding, 'source')
            admitted = True
        except ValueError:
            admitted = False
        self.assertTrue(admitted, 'Both Source unsigned metadata replays need normal128')

    def test_source_unsigned_metadata_replay_above128_is_rejected(self):
        fixture = self.transport_case()
        native = copy.deepcopy(fixture.native)
        native['producer']['unsigned'] = self.sized_metadata(native['producer']['unsigned'], 134217729)
        with self.assertRaises(ValueError):
            transport._producer_proof(native, fixture.binding, 'source')

    def test_source_signed_native_metadata_replay_stays96(self):
        fixture = self.transport_case()
        origin = copy.deepcopy(fixture.origin)
        origin['native'] = self.sized_metadata(origin['native'], 100663297)
        with self.assertRaises(ValueError):
            transport._origin_proof(origin, fixture.native, fixture.binding, 'source')

    def test_store_unsigned_metadata_replay_stays96(self):
        import native_split_fixture
        fixture = self.transport_case()
        split, _, _, _ = native_split_fixture.make_split(fixture.unsigned, fixture.installation,
            fixture.binding, 'store', fixture.files)
        native = split['native']
        native['producer']['unsigned'] = self.sized_metadata(native['producer']['unsigned'], 100663297)
        with self.assertRaisesRegex(ValueError, 'artifact 이름·크기·digest·만료'):
            transport._producer_proof(native, fixture.binding, 'store')

    def test_closed_distribution_sizes_have_exact_six_numeric_roles(self):
        fixture = self.fixture()
        sizes = getattr(pair, 'distribution_sizes', None)
        self.assertTrue(callable(sizes), 'Closed numeric distribution size observation is missing')
        for arch, code in [('x64', 1), ('arm64', 2)]:
            folder = fixture.packages[arch]
            result = sizes(folder, arch)
            self.assertEqual(set(result), {'schemaVersion', 'architectureCode', 'fileCount', 'msixBytes',
                'portableBytes', 'manifestBytes', 'provenanceBytes', 'checksumBytes', 'cliHelpBytes', 'totalBytes', 'capBytes', 'withinBudget'})
            self.assertTrue(all(type(value) is int for value in result.values()))
            self.assertEqual((result['schemaVersion'], result['architectureCode'], result['fileCount']), (1, code, 6))
            self.assertEqual(result['totalBytes'], sum(p.stat().st_size for p in folder.iterdir()))
            self.assertEqual(result['msixBytes'], (folder / json.loads((folder / 'provenance.json').read_bytes())['package']).stat().st_size)
            self.assertEqual(result['cliHelpBytes'], 10)
            self.assertEqual((result['capBytes'], result['withinBudget']), (134217728, 1))

    def test_closed_sizes_reject_unknown_and_missing_roles(self):
        fixture = self.fixture()
        sizes = getattr(pair, 'distribution_sizes', None)
        self.assertTrue(callable(sizes), 'Closed numeric size operation is missing')
        folder = fixture.packages['x64']
        unknown = folder / 'SYNTHETIC_UNTRUSTED_NAME.txt'
        unknown.write_text('synthetic')
        with self.assertRaises(ValueError):
            sizes(folder, 'x64')
        unknown.unlink()
        (folder / 'rhwp-help.txt').unlink()
        with self.assertRaises(ValueError):
            sizes(folder, 'x64')

    def test_closed_sizes_reject_changed_architecture(self):
        fixture = self.fixture()
        sizes = getattr(pair, 'distribution_sizes', None)
        self.assertTrue(callable(sizes), 'Closed numeric size operation is missing')
        with self.assertRaises(ValueError):
            sizes(fixture.packages['x64'], 'arm64')

    def test_closed_sizes_reject_linked_role(self):
        fixture = self.fixture()
        sizes = getattr(pair, 'distribution_sizes', None)
        self.assertTrue(callable(sizes), 'Closed numeric size operation is missing')
        help_path = fixture.packages['x64'] / 'rhwp-help.txt'
        original = self.root / 'outside.txt'
        original.write_text('synthetic')
        help_path.unlink()
        try:
            help_path.symlink_to(original)
        except OSError:
            self.skipTest('Platform does not permit a synthetic symlink')
        with self.assertRaises(ValueError):
            sizes(fixture.packages['x64'], 'x64')

    def test_sizes_cli_emits_numeric_json_without_filename_or_content(self):
        fixture = self.fixture()
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/release_pair.py'), 'sizes',
            '--package-directory', str(fixture.packages['x64']), '--architecture', 'x64'],
            cwd=ROOT, env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, 'Closed sizes CLI must succeed')
        receipt = json.loads(result.stdout)
        self.assertTrue(all(type(value) is int for value in receipt.values()))
        self.assertEqual(result.stderr, b'')

    def test_sizes_cli_failure_does_not_echo_unknown_filename(self):
        fixture = self.fixture()
        (fixture.packages['x64'] / 'SYNTHETIC_UNTRUSTED_NAME.txt').write_text('synthetic')
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/release_pair.py'), 'sizes',
            '--package-directory', str(fixture.packages['x64']), '--architecture', 'x64'],
            cwd=ROOT, env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'Normal distribution size observation failed.\n')


if __name__ == '__main__':
    unittest.main()
