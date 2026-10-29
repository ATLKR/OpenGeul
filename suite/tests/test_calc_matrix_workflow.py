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
READY = '"env.OPENGEUL_SUITE_RUN_MODE == \'acceptance\' && (!cancelled() && steps.fixtures.outcome == \'success\')"'
SEQUENCED_READY = ('"(env.OPENGEUL_SUITE_RUN_MODE == \'acceptance\' || '
                   '(env.OPENGEUL_SUITE_RUN_MODE == \'ime-mode-diagnostic\' && '
                   'matrix.architecture == \'arm64\')) && '
                   '(!cancelled() && steps.fixtures.outcome == \'success\')"')


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
                          if field(step, 'id') == 'suite-unit-shell')
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
        old_gui = next(i for i, step in enumerate(steps) if 'korean_ime_smoke.py --suite' in step
                       and '--output .work/suite-korean-ime' in step)
        for name, script in [('calc-save', 'calc_save_smoke.py'), ('calc-close', 'calc_close_probe.py')]:
            with self.subTest(name=name):
                probe_index = next((i for i, step in enumerate(steps) if field(step, 'id') == name), None)
                self.assertIsNotNone(probe_index, 'Physical Calc probe is absent from the matrix')
                self.assertLess(fixture, probe_index)
                self.assertLess(probe_index, old_gui)
                probe = steps[probe_index]
                self.assertEqual(field(probe, 'if'), SEQUENCED_READY)
                code = run_code(probe)
                self.assertIn('python suite/e2e/' + script + ' --suite $env:SUITE_PACKAGE', code)
                self.assertIn('--fixtures .work/suite-engine/fixtures --output .work/suite-' + name, code)
                self.assertIn('if ($LASTEXITCODE -ne 0)', code)
                # Each harness selects its own local diagnostics beneath output;
                # a global worker root would not collect these native archives.
                self.assertNotIn('OPENGEUL_SUITE_DIAGNOSTICS:', probe)
                verify, evidence = steps[probe_index + 1:probe_index + 3]
                self.assertEqual(field(verify, 'if'), SEQUENCED_READY, 'Package verification must also run after probe failure')
                self.assertIn('python suite/scripts/verify-suite.py $env:SUITE_PACKAGE', run_code(verify))
                self.assertIn('if ($LASTEXITCODE -ne 0)', run_code(verify))
                self.assertEqual(field(evidence, 'if'), READY, 'Evidence must survive probe/verification failure')
                self.assertIn('uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02', evidence)
                self.assertIn('path: .work/suite-' + name + '/', evidence)
                self.assertIn('include-hidden-files: true', evidence)
                self.assertIn('retention-days: 1', evidence)
                self.assertIn('if-no-files-found: error', evidence)
                self.assertIn('${{ matrix.architecture }}-${{ github.run_id }}-${{ github.run_attempt }}', evidence)
        final = next(step for step in steps if field(step, 'if') == '"env.OPENGEUL_SUITE_RUN_MODE == \'acceptance\' && (always())"')
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

    def test_integrity_stage_metadata_preserves_original_assertions_and_filesystem_calls(self):
        step=next(step for step in workflow_steps() if field(step,'shell')=='python')
        tree=ast.parse(run_code(step))
        # Original gate fingerprints, captured before adding stage assignments.
        expected={
            'check_native_archives':'5b5edf66a6284ce0f2f97a3d6b95f857647f107fcd76f432c5a28fb76a150f1d',
            'check_evidence_crash_dumps':'62b000e99d1a63f2bdfd3e9abbd3b39361e4c3868f4600df17a75193672219b8'}
        filesystem={'is_dir','is_symlink','glob','rglob','is_file','open','read','read_text',
            'resolve','is_relative_to','stat','read_bytes'}
        for node in tree.body:
            if not isinstance(node,ast.FunctionDef) or node.name not in expected:continue
            guards=[ast.dump(item,include_attributes=False) for item in ast.walk(node) if isinstance(item,ast.Assert)]
            calls=[ast.dump(item,include_attributes=False) for item in sorted((item for item in ast.walk(node)
                if isinstance(item,ast.Call) and isinstance(item.func,ast.Attribute) and item.func.attr in filesystem),
                key=lambda item:(item.lineno,item.col_offset))]
            digest=hashlib.sha256(json.dumps([guards,calls],separators=(',',':')).encode()).hexdigest()
            self.assertEqual(digest,expected[node.name],node.name)

    def test_each_original_archive_root_keeps_its_failed_gate_stage(self):
        import numeric_notice
        check=self.verifier()
        self.assertEqual(sum(name.startswith('native-integrity-') for name in numeric_notice.STAGES),60)
        prefixes=('shared','calc-save','calc-close-save','calc-close-discard','calc-close-cancel')
        gates=('root-admission','manifest-discovery','path-crash-scan','archive-bytes','shutdown-proof')
        for index,prefix in enumerate(prefixes):
            for gate in gates:
                with self.subTest(root=prefix,gate=gate),tempfile.TemporaryDirectory() as folder:
                    roots=self.archives(folder);root=roots[index];archive=root/'owned-profile'
                    if gate=='root-admission':root.rename(Path(folder)/'omitted-root')
                    elif gate=='manifest-discovery':(archive/'manifest.json').unlink()
                    elif gate=='path-crash-scan':(root/'PRIVATE-DOCUMENT.mdmp').write_bytes(b'dump')
                    elif gate=='archive-bytes':(archive/'report.txt').write_bytes(b'changed')
                    else:
                        proof=json.loads(FIXTURES.read_text())['forced']
                        self.write_shutdown(archive,proof,expected_engine(folder))
                    record=check(roots)['roots'][index]
                    self.assertIs(record['success'],False)
                    self.assertEqual(record.get('stage'),'native-integrity-'+prefix+'-'+gate)
                    self.assertIn(record['stage'],numeric_notice.STAGES)

    def test_original_member_assertions_have_distinct_numeric_failure_stages(self):
        import numeric_notice
        check=self.verifier()
        prefixes=('shared','calc-save','calc-close-save','calc-close-discard','calc-close-cancel')
        gates=('archive-complete','archive-list','archive-path','archive-location',
               'archive-bytes','archive-hash')
        for index,prefix in enumerate(prefixes):
            for gate in gates:
                with self.subTest(root=prefix,gate=gate),tempfile.TemporaryDirectory() as folder:
                    roots=self.archives(folder);archive=roots[index]/'owned-profile'
                    manifest=archive/'manifest.json';record=json.loads(manifest.read_text())
                    if gate=='archive-complete':record['archiveComplete']=False
                    elif gate=='archive-list':record['files']=None
                    elif gate=='archive-path':record['files'][0]['path']='../PRIVATE-DOCUMENT'
                    elif gate=='archive-location':record['files'][0]['path']='PRIVATE-MISSING'
                    elif gate=='archive-bytes':record['files'][0]['bytes']+=1
                    else:record['files'][0]['sha256']='0'*64
                    manifest.write_text(json.dumps(record),encoding='utf-8')
                    result=check(roots)['roots'][index]
                    self.assertIs(result['success'],False)
                    self.assertEqual(result['errorType'],'AssertionError')
                    self.assertEqual(result['stage'],'native-integrity-'+prefix+'-'+gate)
                    self.assertIn(result['stage'],numeric_notice.STAGES)

    def test_each_original_evidence_root_keeps_its_failed_gate_stage(self):
        import numeric_notice
        check=self.verifier()
        for index,prefix in enumerate(('calc-save','calc-close')):
            for gate in ('root-admission','path-crash-scan'):
                with self.subTest(root=prefix,gate=gate),tempfile.TemporaryDirectory() as folder:
                    roots=self.archives(folder)
                    evidence=roots[1].parent if index==0 else roots[2].parents[1]
                    if gate=='root-admission':evidence.rename(Path(folder)/'omitted-evidence')
                    else:(evidence/'PRIVATE-DOCUMENT.mdmp').write_bytes(b'dump')
                    record=check(roots)['evidenceRoots'][index]
                    self.assertIs(record['success'],False)
                    self.assertEqual(record.get('stage'),'native-integrity-evidence-'+prefix+'-'+gate)
                    self.assertIn(record['stage'],numeric_notice.STAGES)

    def test_additional_archive_and_evidence_roots_keep_original_checks_and_generic_stage(self):
        import shutil
        step=next(step for step in workflow_steps() if field(step,'shell')=='python')
        tree=ast.parse(run_code(step))
        definitions=ast.Module(body=[node for node in tree.body if isinstance(node,
            (ast.Import,ast.ImportFrom,ast.FunctionDef))],type_ignores=[])
        namespace={};exec(compile(definitions,str(WORKFLOW),'exec'),namespace)
        with tempfile.TemporaryDirectory() as folder:
            roots=self.archives(folder);extra=Path(folder)/'.work/extra-archive'
            shutil.copytree(roots[0],extra);roots.append(extra)
            extra_evidence=Path(folder)/'.work/extra-evidence';extra_evidence.mkdir()
            evidence=[roots[1].parent,roots[2].parents[1],extra_evidence]
            check=namespace['check_all_native_archives']
            result=check(roots,evidence,expected_engine(folder))
            self.assertIs(result['success'],True)
            self.assertEqual((len(result['roots']),len(result['evidenceRoots']),result['completeArchives']),(6,3,6))
            (extra/'owned-profile/manifest.json').unlink();extra_evidence.rmdir()
            result=check(roots,evidence,expected_engine(folder))
            self.assertIs(result['success'],False)
            self.assertEqual((len(result['roots']),len(result['evidenceRoots'])),(6,3))
            for record,message in ((result['roots'][-1],'No owned native diagnostic manifests were archived'),
                                   (result['evidenceRoots'][-1],'Owned Calc evidence is missing')):
                self.assertEqual(record['errorType'],'AssertionError')
                self.assertEqual(record['error'],message)
                self.assertEqual(record['stage'],'verify-native-archives')

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
        from test_native_archive_completeness import NativeArchiveCompletenessTests
        fixture = NativeArchiveCompletenessTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        completed = fixture.workflow_process()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads((fixture.root / '.work/suite-native-integrity.json').read_text(encoding='utf-8'))
        self.assertEqual(result['generationCompleteness']['matchedGenerations'], len(fixture.expected))

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
