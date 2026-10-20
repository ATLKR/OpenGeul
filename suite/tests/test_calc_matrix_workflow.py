"""Run the workflow's archive verifier against authentic and damaged evidence."""
import ast
import copy
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/office-suite.yml'
FIXTURES = Path(__file__).parent / 'fixtures/owned-office-shutdown.json'
PACKAGE = 'dist/OpenGeul-Office-test'


def expected_engine(folder):
    return (Path(folder) / PACKAGE / 'Office/program/soffice.bin').resolve()
ROOTS = ('.work/suite-worker-diagnostics', '.work/suite-calc-save/diagnostics',
         *('.work/suite-calc-close/calc-close-' + choice + '/diagnostics'
           for choice in ('save', 'discard', 'cancel')))
READY = "'!cancelled() && steps.fixtures.outcome == ''success'''"


def workflow_steps():
    return re.split(r'^    - name: ', WORKFLOW.read_text(encoding='utf-8'), flags=re.M)[1:]


def field(step, name):
    match = re.search(r'^      ' + re.escape(name) + r': (.+)$', step, re.M)
    return match.group(1) if match else None


def run_code(step):
    match = re.search(r'^      run: \|\n((?:        .*\n|\n)+)', step, re.M)
    if not match:
        raise AssertionError('Workflow step has no literal run block')
    return textwrap.dedent(match.group(1))


class CalcMatrixWorkflowTests(unittest.TestCase):
    def test_pinned_image_tooling_is_installed_before_unit_discovery(self):
        steps = workflow_steps()
        unit_index = next(i for i, step in enumerate(steps)
                          if 'python -m unittest discover -s suite/tests -v' in step)
        image_steps = [(i, run_code(step)) for i, step in enumerate(steps)
                       if 'python -m pip install Pillow==12.3.0' in step]
        self.assertEqual(len(image_steps), 1)
        image_index, code = image_steps[0]
        self.assertLess(image_index, unit_index,
                        'PNG checkpoint unit checks need Pillow before discovery')
        command = 'python -m pip install Pillow==12.3.0'
        self.assertIn('if ($LASTEXITCODE -ne 0)', code[code.index(command) + len(command):])

    def test_independent_probes_precede_existing_fixture_mutations(self):
        steps = workflow_steps()
        fixture = next(i for i, step in enumerate(steps) if field(step, 'id') == 'fixtures')
        old_gui = next(i for i, step in enumerate(steps) if 'korean_ime_smoke.py --suite' in step)
        for name, script in [('calc-save', 'calc_save_smoke.py'), ('calc-close', 'calc_close_probe.py')]:
            with self.subTest(name=name):
                probe_index = next((i for i, step in enumerate(steps) if field(step, 'id') == name), None)
                self.assertIsNotNone(probe_index, 'Physical Calc probe is absent from the matrix')
                self.assertLess(fixture, probe_index)
                self.assertLess(probe_index, old_gui)
                probe = steps[probe_index]
                self.assertEqual(field(probe, 'if'), READY)
                code = run_code(probe)
                self.assertIn('python suite/e2e/' + script + ' --suite $env:SUITE_PACKAGE', code)
                self.assertIn('--fixtures .work/suite-engine/fixtures --output .work/suite-' + name, code)
                self.assertIn('if ($LASTEXITCODE -ne 0)', code)
                # Each harness selects its own local diagnostics beneath output;
                # a global worker root would not collect these native archives.
                self.assertNotIn('OPENGEUL_SUITE_DIAGNOSTICS:', probe)
                verify, evidence = steps[probe_index + 1:probe_index + 3]
                self.assertEqual(field(verify, 'if'), READY, 'Package verification must also run after probe failure')
                self.assertIn('python suite/scripts/verify-suite.py $env:SUITE_PACKAGE', run_code(verify))
                self.assertIn('if ($LASTEXITCODE -ne 0)', run_code(verify))
                self.assertEqual(field(evidence, 'if'), READY, 'Evidence must survive probe/verification failure')
                self.assertIn('uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02', evidence)
                self.assertIn('path: .work/suite-' + name + '/', evidence)
                self.assertIn('include-hidden-files: true', evidence)
                self.assertIn('retention-days: 7', evidence)
                self.assertIn('if-no-files-found: error', evidence)
                self.assertIn('${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}', evidence)
        final = next(step for step in steps if field(step, 'if') == 'always()')
        for name in ('calc-save', 'calc-close'):
            self.assertIn('.work/suite-' + name + '/', final)

    def verifier(self):
        step = next(step for step in workflow_steps() if field(step, 'shell') == 'python')
        self.assertEqual(field(step, 'if'), READY)
        tree = ast.parse(run_code(step))
        # Execute the actual inline imports/functions, not a test reimplementation.
        definitions = ast.Module(body=[node for node in tree.body if isinstance(node,
            (ast.Import, ast.ImportFrom, ast.FunctionDef))], type_ignores=[])
        namespace = {}
        exec(compile(definitions, str(WORKFLOW), 'exec'), namespace)
        self.assertTrue('check_all_native_archives' in namespace, 'Every owned Calc diagnostics root needs an independent check')
        root_assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                            and any(isinstance(target, ast.Name) and target.id == 'roots' for target in node.targets)]
        self.assertEqual(len(root_assignments), 1)
        actual = ast.literal_eval(root_assignments[0].value)
        self.assertEqual(tuple(actual), ROOTS)
        self.assertIn("assert result['success']", run_code(step), 'A damaged archive must fail the job after writing its receipt')
        self.assertLess(run_code(step).index("Path('.work/suite-native-integrity.json').write_text"),
                        run_code(step).index("assert result['success']"))
        evidence_assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                                and any(isinstance(target, ast.Name) and target.id == 'evidence_roots' for target in node.targets)]
        self.assertEqual(len(evidence_assignments), 1)
        self.assertEqual(ast.literal_eval(evidence_assignments[0].value),
                         ('.work/suite-calc-save', '.work/suite-calc-close'))
        return lambda roots: namespace['check_all_native_archives'](roots, [roots[1].parent, roots[2].parents[1]], expected_engine(roots[1].parents[2]))

    def write_shutdown(self, archive, proof, expected):
        proof = copy.deepcopy(proof)
        proof['expectedEngineImage'] = str(expected)
        for row in proof['initialMembers'] + proof['finalMembers']:
            row['image'] = str(expected.parent / ntpath.basename(row['image']))
        raw = (json.dumps(proof, allow_nan=False) + '\n').encode()
        (archive / 'shutdown.json').write_bytes(raw)
        manifest = archive / 'manifest.json'
        record = json.loads(manifest.read_text(encoding='utf-8'))
        record['files'] = [item for item in record['files'] if item['path'] != 'shutdown.json']
        record['files'].append(dict(path='shutdown.json', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        manifest.write_text(json.dumps(record), encoding='utf-8')

    def archives(self, folder):
        # GitHub's Python shell executes a temporary script outside the checkout.
        module = Path(folder) / 'suite/e2e/native_cleanup_receipt.py'
        module.parent.mkdir(parents=True)
        module.write_bytes((WORKFLOW.parents[2] / 'suite/e2e/native_cleanup_receipt.py').read_bytes())
        roots = [Path(folder) / root for root in ROOTS]
        for root in roots:
            archive = root / 'owned-profile'
            archive.mkdir(parents=True)
            raw = b'owned native diagnostic bytes'
            (archive / 'report.txt').write_bytes(raw)
            record = dict(schemaVersion=1, kind='owned-office-native-diagnostics', launcherPid=10,
                          archiveComplete=True, files=[dict(path='report.txt',
                          bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())])
            (archive / 'manifest.json').write_text(json.dumps(record), encoding='utf-8')
            self.write_shutdown(archive, json.loads(FIXTURES.read_text(encoding='utf-8'))['graceful'], expected_engine(folder))
        return roots

    def workflow_environment(self):
        environment = dict(os.environ, GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2',
                           SUITE_PACKAGE=PACKAGE)
        environment.pop('PYTHONPATH', None)
        return environment

    def test_authentic_archives_cover_original_and_all_four_calc_roots(self):
        check = self.verifier()
        with tempfile.TemporaryDirectory() as folder:
            roots = self.archives(folder)
            result = check(roots)
            self.assertIs(result['success'], True)
            self.assertEqual(result['completeArchives'], 5)
            self.assertEqual(result['verifiedFiles'], 10)
            self.assertEqual(result['qualifiedShutdowns'], 5)
            self.assertEqual(result['crashDumps'], 0)
            self.assertEqual([item['root'] for item in result['roots']], list(map(str, roots)))

    def test_changed_hash_and_size_fail_in_each_owned_root(self):
        check = self.verifier()
        for index in range(len(ROOTS)):
            for raw in (b'changed native diagnostic xx', b'short'):
                with self.subTest(root=ROOTS[index], raw=raw), tempfile.TemporaryDirectory() as folder:
                    roots = self.archives(folder)
                    original = roots[index] / 'owned-profile/report.txt'
                    if len(raw) > 10:
                        raw = b'x' * original.stat().st_size  # Same size, wrong hash.
                    original.write_bytes(raw)
                    result = check(roots)
                    self.assertIs(result['success'], False)
                    self.assertEqual(len(result['roots']), 5)
                    self.assertIs(result['roots'][index]['success'], False)

    def test_unlisted_crash_suffix_or_magic_is_rejected_in_every_calc_root(self):
        check = self.verifier()
        for index in range(len(ROOTS)):
            for name, raw in [('stray.DmP', b'dump'), ('stray.MdMp', b'dump'), ('stray.bin', b'MDMPpayload')]:
                with self.subTest(root=ROOTS[index], name=name), tempfile.TemporaryDirectory() as folder:
                    roots = self.archives(folder)
                    (roots[index] / name).write_bytes(raw)
                    result = check(roots)
                    self.assertIs(result['success'], False)
                    self.assertIs(result['roots'][index]['success'], False)
                    self.assertNotEqual(result.get('crashDumps'), 0, 'A failed scan must not certify zero crash dumps')

    def test_missing_first_root_does_not_hide_later_damaged_calc_archives(self):
        check = self.verifier()
        with tempfile.TemporaryDirectory() as folder:
            roots = self.archives(folder)
            roots[0] = roots[0] / 'missing'
            (roots[-1] / 'unlisted.bin').write_bytes(b'MDMP')
            result = check(roots)
            self.assertIs(result['success'], False)
            self.assertEqual([item['success'] for item in result['roots']], [False, True, True, True, False])

    def test_incomplete_unsafe_and_duplicate_manifests_remain_failures(self):
        check = self.verifier()
        for mutation in ('incomplete', 'escaped', 'duplicate'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                roots = self.archives(folder)
                manifest = roots[1] / 'owned-profile/manifest.json'
                record = json.loads(manifest.read_text(encoding='utf-8'))
                if mutation == 'incomplete':
                    record['archiveComplete'] = False
                elif mutation == 'escaped':
                    record['files'][0]['path'] = '../report.txt'
                else:
                    record['files'].append(copy.deepcopy(record['files'][0]))
                manifest.write_text(json.dumps(record), encoding='utf-8')
                result = check(roots)
                self.assertIs(result['success'], False)
                self.assertIs(result['roots'][1]['success'], False)

    def test_clean_profiles_without_crash_files_are_valid_archives(self):
        check = self.verifier()
        with tempfile.TemporaryDirectory() as folder:
            roots = self.archives(folder)
            for root in roots:
                manifest = root / 'owned-profile/manifest.json'
                record = json.loads(manifest.read_text(encoding='utf-8'))
                record['files'] = [item for item in record['files'] if item['path'] == 'shutdown.json']
                (manifest.parent / 'report.txt').unlink()
                manifest.write_text(json.dumps(record), encoding='utf-8')
            result = check(roots)
            self.assertIs(result['success'], True)
            self.assertEqual(result['completeArchives'], 5)
            self.assertEqual(result['verifiedFiles'], 5)
            self.assertEqual(result['qualifiedShutdowns'], 5)

    def test_each_product_archive_requires_actual_manifest_hashed_shutdown(self):
        check = self.verifier()
        for index in range(len(ROOTS)):
            for damage in ('missing', 'unlisted', 'changed-hash', 'changed-size', 'observer-kind'):
                with self.subTest(root=ROOTS[index], damage=damage), tempfile.TemporaryDirectory() as folder:
                    roots = self.archives(folder)
                    archive = roots[index] / 'owned-profile'
                    manifest = archive / 'manifest.json'
                    record = json.loads(manifest.read_text())
                    if damage == 'missing':
                        (archive / 'shutdown.json').unlink()
                    elif damage == 'unlisted':
                        record['files'] = record['files'][:1]
                    elif damage == 'observer-kind':
                        record['kind'] = 'e2e-observer'
                        record['files'] = record['files'][:1]
                        (archive / 'shutdown.json').unlink()
                    else:
                        raw = (archive / 'shutdown.json').read_bytes()
                        (archive / 'shutdown.json').write_bytes(b'x' * len(raw) if damage == 'changed-hash' else b'{}')
                    manifest.write_text(json.dumps(record))
                    result = check(roots)
                    self.assertIs(result['success'], False)
                    self.assertIs(result['roots'][index]['success'], False)

    def test_hash_valid_force_nonzero_and_unproved_receipts_fail_even_with_shell_zero(self):
        step = next(step for step in workflow_steps() if field(step, 'shell') == 'python')
        fixtures = json.loads(FIXTURES.read_text())
        for name in ('forced', 'nonzero', 'unproved'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                roots = self.archives(folder)
                archive = roots[-1] / 'owned-profile'
                self.write_shutdown(archive, fixtures[name], expected_engine(folder))
                raw = (archive / 'shutdown.json').read_bytes()
                (Path(folder) / '.work/shell-exit.json').write_text('{"exitCode":0}')
                completed = subprocess.run([sys.executable, '-c', run_code(step)], cwd=folder,
                                           env=self.workflow_environment(), capture_output=True, text=True, timeout=20)
                self.assertNotEqual(completed.returncode, 0)
                receipt = json.loads((Path(folder) / '.work/suite-native-integrity.json').read_text())
                self.assertEqual([row['success'] for row in receipt['roots']], [True]*4 + [False])
                self.assertEqual(raw, (archive / 'shutdown.json').read_bytes(), 'Raw failure proof must survive the gate')

    def test_observer_evidence_outside_product_roots_has_no_product_receipt_requirement(self):
        check = self.verifier()
        with tempfile.TemporaryDirectory() as folder:
            roots = self.archives(folder)
            observer = roots[1].parent / 'active-cell-reader/observer'
            observer.mkdir(parents=True)
            (observer / 'manifest.json').write_text('{"kind":"e2e-observer"}')
            self.assertTrue(check(roots)['success'])

    def test_runner_temporary_python_script_imports_validator_from_checkout(self):
        step = next(step for step in workflow_steps() if field(step, 'shell') == 'python')
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as runner:
            self.archives(folder)
            script = Path(runner) / 'workflow.py'
            script.write_text(run_code(step))
            completed = subprocess.run([sys.executable, str(script)], cwd=folder,
                                       env=self.workflow_environment(), capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_actual_workflow_process_writes_failure_receipt_before_nonzero_exit(self):
        step = next(step for step in workflow_steps() if field(step, 'shell') == 'python')
        with tempfile.TemporaryDirectory() as folder:
            roots = self.archives(folder)
            (roots[0] / 'owned-profile/manifest.json').unlink()
            (roots[-1] / 'unlisted.bin').write_bytes(b'MDMP')
            env = self.workflow_environment()
            completed = subprocess.run([sys.executable, '-c', run_code(step)], cwd=folder,
                                       env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(completed.returncode, 0)
            receipt = json.loads((Path(folder) / '.work/suite-native-integrity.json').read_text(encoding='utf-8'))
            self.assertIs(receipt['success'], False)
            self.assertEqual(receipt['sourceCommit'], 'a' * 40)
            self.assertEqual((receipt['runId'], receipt['runAttempt']), ('123', '2'))
            self.assertEqual([row['success'] for row in receipt['roots']], [False, True, True, True, False])
            self.assertIn('No owned native diagnostic manifests', receipt['roots'][0]['error'])
            self.assertIn('Native crash dump found', receipt['roots'][-1]['error'])

    def test_crash_files_outside_archives_in_uploaded_calc_trees_fail_the_job(self):
        step = next(step for step in workflow_steps() if field(step, 'shell') == 'python')
        for relative, raw in [('.work/suite-calc-save/active-cell-reader/reader.DMP', b'dump'),
                              ('.work/suite-calc-close/calc-close-cancel/after-reader/opaque.bin', b'MDMPpayload')]:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as folder:
                self.archives(folder)
                dump = Path(folder) / relative
                dump.parent.mkdir(parents=True)
                dump.write_bytes(raw)
                env = self.workflow_environment()
                completed = subprocess.run([sys.executable, '-c', run_code(step)], cwd=folder,
                                           env=env, capture_output=True, text=True, timeout=20)
                self.assertNotEqual(completed.returncode, 0, 'Crash files in uploaded reader evidence must fail qualification')
                receipt = json.loads((Path(folder) / '.work/suite-native-integrity.json').read_text(encoding='utf-8'))
                self.assertIs(receipt['success'], False)
                self.assertTrue(any('Native crash dump found' in row.get('error', '')
                                    for row in receipt['evidenceRoots']))


if __name__ == '__main__':
    unittest.main()
