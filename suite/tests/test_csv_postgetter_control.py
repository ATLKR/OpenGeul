"""Focused diagnostic boundaries; synthetic bytes never qualify a GUI run."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'suite/e2e/csv_postgetter_control.py'


class CsvPostgetterControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assert_source_present = SOURCE.is_file()
        if cls.assert_source_present:
            spec = importlib.util.spec_from_file_location('csv_control_contract', SOURCE)
            cls.api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.api)

    def setUp(self):
        self.assertTrue(self.assert_source_present, 'Fixed CSV diagnostic companion is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_fixed_selection_rejects_missing_duplicate_or_changed_csv_row(self):
        plan = self.api.home.build_plan()
        before = copy.deepcopy(plan)
        expected = dict(case='home-open-calc-csv', kind='open', module='calc', extension='csv')
        self.assertEqual(self.api.select_csv_spec(plan), expected)
        self.assertEqual(plan, before)
        for changed in ([r for r in plan if r != expected], plan + [expected],
                        [dict(r, extension='xlsx') if r == expected else r for r in plan],
                        [dict(r, extra=True) if r == expected else r for r in plan]):
            with self.subTest(plan=changed), self.assertRaises(AssertionError):
                self.api.select_csv_spec(changed)
        self.assertFalse(self.api.home.summarize([dict(expected, success=True, cleanClose=True, forcedCleanup=False)])['success'])

    def source_fixture(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('GITHUB_SHA', None)
        repo = self.root / 'repo'
        repo.mkdir()
        for name in ('suite/e2e/csv_postgetter_control.py', 'suite/e2e/home_routing_smoke.py', 'suite/e2e/home_calc_close.py',
                     'suite/worker/office_worker.py', 'suite/shell/Program.cs', 'suite/payload.py',
                     '.github/workflows/office-csv-postgetter-control.yml'):
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
        git('init', '-q')
        git('add', '.')
        git('-c', 'user.email=control@example.invalid', '-c', 'user.name=Control Test', 'commit', '-qm', 'Synthetic source boundary')
        suite = self.root / 'suite'
        (suite / 'Sources').mkdir(parents=True)
        archive = suite / 'Sources/OpenGeul-Office-source.zip'
        git('archive', '--format=zip', '--output', str(archive), 'HEAD')
        (suite / 'worker').mkdir()
        (suite / 'worker/office_worker.py').write_bytes((repo / 'suite/worker/office_worker.py').read_bytes())
        for name in ('OpenGeul.Office.exe', 'OpenGeul.Office.dll', 'runtime-branding.json'):
            (suite / name).write_bytes(name.encode())
        provenance = dict(sourceCommit=git('rev-parse', 'HEAD'), architecture='x64',
                          sourceArchiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        (suite / 'suite-provenance.json').write_text(json.dumps(provenance))
        files = {p.relative_to(suite).as_posix(): dict(size=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in suite.rglob('*') if p.is_file()}
        (suite / 'suite-inventory.json').write_text(json.dumps(dict(architecture='x64', files=files)))
        return repo, suite, git

    def test_source_join_rejects_checkout_helper_drift(self):
        repo, suite, _ = self.source_fixture()
        proof = self.api.source_join(suite, repo)
        self.assertTrue(proof['success'])
        self.assertTrue(any(r['path'] == 'suite/e2e/home_routing_smoke.py' for r in proof['sourceFiles']))
        (repo / 'suite/e2e/home_routing_smoke.py').write_bytes(b'changed helper')
        with self.assertRaises(AssertionError):
            self.api.source_join(suite, repo)

    def test_source_join_rejects_different_commit_worker_or_inventory_bytes(self):
        repo, suite, git = self.source_fixture()
        worker = suite / 'worker/office_worker.py'
        original = worker.read_bytes()
        worker.write_bytes(b'changed packaged worker')
        with self.assertRaises(AssertionError):
            self.api.source_join(suite, repo)
        worker.write_bytes(original)
        (suite / 'OpenGeul.Office.dll').write_bytes(b'changed host')
        with self.assertRaises(AssertionError):
            self.api.source_join(suite, repo)
        (suite / 'OpenGeul.Office.dll').write_bytes(b'OpenGeul.Office.dll')
        git('-c', 'user.email=control@example.invalid', '-c', 'user.name=Control Test', 'commit', '--allow-empty', '-qm', 'Different commit')
        with self.assertRaises(AssertionError):
            self.api.source_join(suite, repo)

    @staticmethod
    def reindex_package(suite):
        provenance_path = suite / 'suite-provenance.json'
        provenance = json.loads(provenance_path.read_bytes())
        provenance['sourceArchiveSha256'] = hashlib.sha256((suite / 'Sources/OpenGeul-Office-source.zip').read_bytes()).hexdigest()
        provenance_path.write_text(json.dumps(provenance))
        files = {p.relative_to(suite).as_posix(): dict(size=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in suite.rglob('*') if p.is_file() and p.name != 'suite-inventory.json'}
        (suite / 'suite-inventory.json').write_text(json.dumps(dict(architecture='x64', files=files)))

    def test_self_consistent_inventory_cannot_admit_worker_without_current_source(self):
        repo, suite, _ = self.source_fixture()
        (suite / 'worker/extra.py').write_bytes(b'not in the current source ZIP')
        self.reindex_package(suite)
        with self.assertRaisesRegex(AssertionError, 'worker'):
            self.api.source_join(suite, repo)

    def test_self_consistent_inventory_cannot_hide_source_or_worker_byte_mismatch(self):
        repo, suite, _ = self.source_fixture()
        worker = suite / 'worker/office_worker.py'
        worker.write_bytes(b'changed but self-consistently inventoried worker')
        self.reindex_package(suite)
        with self.assertRaisesRegex(AssertionError, 'Packaged worker differs'):
            self.api.source_join(suite, repo)
        worker.write_bytes((repo / 'suite/worker/office_worker.py').read_bytes())
        archive_path = suite / 'Sources/OpenGeul-Office-source.zip'
        with zipfile.ZipFile(archive_path) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
            comment = archive.comment
        contents['suite/e2e/home_routing_smoke.py'] = b'changed archive helper with original commit comment'
        with zipfile.ZipFile(archive_path, 'w') as archive:
            archive.comment = comment
            for name, raw in contents.items():
                archive.writestr(name, raw)
        self.reindex_package(suite)
        with self.assertRaisesRegex(AssertionError, 'checkout bytes differ'):
            self.api.source_join(suite, repo)

    def test_corresponding_source_requires_exact_committed_helper_set(self):
        repo, suite, _ = self.source_fixture()
        archive_path = suite / 'Sources/OpenGeul-Office-source.zip'
        with zipfile.ZipFile(archive_path) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
            comment = archive.comment
        # A genuine Git archive succeeds; only source-member identity changes below.
        self.assertTrue(self.api.source_join(suite, repo)['success'])
        helper = 'suite/e2e/home_calc_close.py'
        self.assertTrue((repo / helper).is_file())
        self.assertIn(helper, original)
        for mutation in ('omit-executing-helper', 'add-uncommitted-helper'):
            contents = dict(original)
            if mutation == 'omit-executing-helper':
                del contents[helper]
            else:
                contents['suite/e2e/uncommitted_helper.py'] = b'not in recorded HEAD'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.comment = comment
                for name, raw in contents.items():
                    archive.writestr(name, raw)
            self.reindex_package(suite)
            proof = {}
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(AssertionError, 'source member set'):
                    self.api.source_join(suite, repo, proof)
                members = proof['sourceMembers']
                self.assertIn(helper, members['expected'])
                self.assertEqual(members['missing'], [helper] if mutation == 'omit-executing-helper' else [])
                self.assertEqual(members['unexpected'], ['suite/e2e/uncommitted_helper.py'] if mutation == 'add-uncommitted-helper' else [])

    def test_original_png_rehash_rejects_tamper_or_dimension_mismatch(self):
        from PIL import Image
        name = 'home-open-calc-csv-calc-post-getter.png'
        path = self.root / name
        Image.new('RGB', (3, 2)).save(path)
        raw = path.read_bytes()
        receipt = dict(image=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), width=3, height=2)
        self.assertEqual(self.api.verify_png(self.root, receipt)['sha256'], receipt['sha256'])
        with self.assertRaises(AssertionError):
            self.api.verify_png(self.root, dict(receipt, width=4))
        path.write_bytes(raw + b'tamper')
        with self.assertRaises(AssertionError):
            self.api.verify_png(self.root, receipt)

    def test_output_rejects_overlap_links_and_preserves_existing_results(self):
        suite, features = self.root / 'suite', self.root / 'features'
        suite.mkdir(); features.mkdir()
        for output in (suite, suite / 'child', features / 'child', self.root):
            with self.subTest(output=output), self.assertRaises(AssertionError):
                self.api.prepare_output(suite, features, output)
        output = self.root / 'fresh'
        self.api.prepare_output(suite, features, output)
        (output / 'sentinel').write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            self.api.prepare_output(suite, features, output)
        self.assertEqual((output / 'sentinel').read_bytes(), b'preserve')
        if os.name != 'nt':
            link = self.root / 'linked'
            link.symlink_to(suite, target_is_directory=True)
            with self.assertRaises(AssertionError):
                self.api.prepare_output(link, features, self.root / 'other')

    def test_source_failure_is_recorded_and_archive_verification_still_attempted(self):
        suite, features, output = [self.root / p for p in ('suite', 'features', 'output')]
        suite.mkdir(); features.mkdir()
        self.api.prepare_output(suite, features, output)
        # Negative control only: failing source admission must launch no Home process.
        with patch.object(self.api, 'source_join', side_effect=AssertionError('source mismatch')), \
             patch.object(self.api.home, 'HomeCase') as case, \
             patch.object(self.api.home, 'verify_native_archives', side_effect=AssertionError('archive failure')) as archives:
            report = self.api.run_control(suite, features, output)
        case.assert_not_called()
        archives.assert_called_once_with(suite, output / 'diagnostics', [report['cases'][0]])
        self.assertFalse(report['success'])
        self.assertIn('source mismatch', report['runError']['error'])
        self.assertIn('archive failure', report['nativeIntegrity']['error'])
        self.assertTrue((output / 'home-open-calc-csv-result.json').is_file())
        self.assertTrue((output / 'native-integrity.json').is_file())
        self.assertTrue((output / 'source-join.json').is_file())
        self.assertFalse(report['finalQualificationReplacement'])
        self.assertTrue(report['humanVisualReviewPending'])
        self.assertFalse(report['gridVisibleVerified'])
        self.assertFalse(report['paintCompleteVerified'])

    def test_secondary_replay_failure_preserves_original_case_failure_and_forced_cleanup(self):
        record = dict(case='home-open-calc-csv', success=False, forcedCleanup=True,
                      error='original owned close failure', traceback='original native traceback', stage='owned-close')
        self.assertTrue(callable(getattr(self.api, 'record_failure', None)), 'A secondary control failure must preserve the original case error')
        with patch.object(self.api.home.native, 'capture_failure') as capture:
            failure = self.api.record_failure(self.root, record, AssertionError('strict replay failed'))
        capture.assert_not_called()
        self.assertEqual(record['error'], 'original owned close failure')
        self.assertEqual(record['traceback'], 'original native traceback')
        self.assertEqual(record['stage'], 'owned-close')
        self.assertTrue(record['forcedCleanup'])
        self.assertFalse(record['success'])
        self.assertIn('strict replay failed', failure['error'])
        self.assertEqual(record['controlFailure'], failure)

    def test_workflow_is_branch_bounded_and_always_verifies_and_uploads(self):
        from suite.tests.test_home_routes_workflow import field, run_code, step_by_id, steps
        workflow = ROOT / '.github/workflows/office-csv-postgetter-control.yml'
        text = workflow.read_text()
        self.assertIn('branches: [work/opengeul-office-csv-postgetter-control]', text)
        self.assertIn('runs-on: windows-2025', text)
        self.assertIn('timeout-minutes: 45', text)
        self.assertNotIn('home_fixture_inputs.py', text)
        self.assertNotIn('home_routing_smoke.py --suite', text)
        self.assertNotIn('workflow_dispatch', text)
        self.assertIn('pywinauto==0.6.9 Pillow==12.3.0', text)
        self.assertIn('./suite/scripts/build-suite.ps1 -Architecture x64', run_code(step_by_id(workflow, 'build')))
        prep = run_code(step_by_id(workflow, 'office-features'))
        self.assertIn('suite/e2e/office_feature_smoke.py --suite $package --output .work/suite-office-features', prep)
        self.assertNotIn('--case', prep)
        diagnostic = run_code(step_by_id(workflow, 'csv-control'))
        self.assertEqual(diagnostic.count('python suite/e2e/csv_postgetter_control.py --suite'), 1)
        verification = step_by_id(workflow, 'post-verify')
        self.assertIn('always()', field(verification, 'if'))
        self.assertIn("steps.build.outcome == ''success''", field(verification, 'if'))
        self.assertIn('python suite/scripts/verify-suite.py $package', run_code(verification))
        self.assertIn('if ($LASTEXITCODE -ne 0)', run_code(verification))
        upload = next(s for s in steps(workflow) if 'actions/upload-artifact@' in s)
        self.assertEqual(field(upload, 'if'), 'always()')
        for pattern in ('Sources/', 'worker/', 'OpenGeul.Office.*', 'suite-inventory.json',
                        'suite-provenance.json', 'runtime-branding.json', '.work/suite-csv-postgetter-control/',
                        '.work/suite-office-features/', '.work/csv-control-build.log'):
            self.assertIn(pattern, upload)
        current = (ROOT / '.github/workflows/office-home-routes.yml').read_text()
        import re
        for action in ('checkout', 'setup-python', 'upload-artifact'):
            self.assertEqual(re.search('actions/' + action + '@([a-f0-9]{40})', text).group(1),
                             re.search('actions/' + action + '@([a-f0-9]{40})', current).group(1))


if __name__ == '__main__':
    unittest.main()
