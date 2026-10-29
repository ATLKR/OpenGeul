"""Execute the acceptance build block with the real portable ZIP file check."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from suite import payload
from suite.tests import test_portable_package_check as portable_tests
from suite.tests.test_calc_matrix_workflow import field, run_code, workflow_steps
from suite.tests.test_com_wait_workflow import evaluate
from suite.tests.test_navigation_diagnostic_workflow import condition


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the real command boundary')
class PortablePackageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = portable_tests.PortablePackageTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.checkout = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve(strict=True)
        scripts = self.checkout / 'suite/scripts'
        scripts.mkdir(parents=True)
        shutil.copy2(portable_tests.SCRIPT, scripts / portable_tests.SCRIPT.name)
        (scripts / 'build-suite.ps1').write_text(
            "param($Architecture, $EngineArchive, $EngineReceipt)\n"
            "if ($Architecture -cne $env:PORTABLE_TEST_ARCHITECTURE) { throw 'Wrong build architecture.' }\n",
            encoding='utf-8')
        self.env_file = self.checkout / 'github-env'
        self.env_file.touch()

    def execute_build(self, *, mode='acceptance', architecture='x64', source_commit='a'*40):
        archive = Path(str(self.fixture.root) + '.zip')
        shutil.copy2(self.fixture.archive, archive)
        build = next(step for step in workflow_steps() if field(step, 'id') == 'build')
        code = run_code(build).replace('${{ matrix.architecture }}', architecture)
        script = self.checkout / 'build-step.ps1'
        script.write_text("$ErrorActionPreference = 'Stop'\n"
                          "function python { & $env:PORTABLE_TEST_PYTHON @args }\n" + code,
                          encoding='utf-8')
        environment = dict(os.environ, OPENGEUL_SUITE_RUN_MODE=mode,
                           SUITE_PACKAGE=str(self.fixture.root), GITHUB_ENV=str(self.env_file),
                           GITHUB_SHA=source_commit, GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='2',
                           PORTABLE_TEST_ARCHITECTURE=architecture, PORTABLE_TEST_PYTHON=sys.executable,
                           PYTHONPATH=str(ROOT))
        for name in ('SUITE_ARCHIVE', 'SUITE_FOREIGN_CWD'):
            environment.pop(name, None)
        process = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive',
                                  '-File', str(script)], cwd=self.checkout, env=environment,
                                 capture_output=True, text=True, encoding='utf-8', timeout=30)
        published = dict(line.split('=', 1) for line in self.env_file.read_text(encoding='utf-8-sig').splitlines())
        return process, published, archive

    def test_acceptance_build_routes_normal_gates_to_verified_repaired_payload(self):
        before = self.fixture.snapshot(self.fixture.root)
        process, published, archive = self.execute_build()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('SUITE_PACKAGE', published, 'Acceptance build did not run and publish the portable ZIP gate')
        repaired = Path(published['SUITE_PACKAGE'])
        self.assertEqual(repaired.name, 'OpenGeul Office 복구 검증')
        self.assertEqual(self.fixture.snapshot(self.fixture.root), before)
        self.assertEqual(self.fixture.snapshot(repaired), before)
        payload.verify_payload(repaired, self.fixture.inventory)
        self.assertEqual(Path(published['SUITE_ARCHIVE']), archive)
        self.assertEqual(archive.read_bytes(), self.fixture.archive.read_bytes())
        receipts = list((self.checkout / '.work/suite-portable').glob('*.json'))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding='utf-8'))
        self.assertEqual(receipt['repairedRoot'], str(repaired))
        self.assertEqual(receipt['sourceCommit'], 'a'*40)
        self.assertEqual(receipt['architecture'], 'x64')
        for flag in ('passed', 'archiveInventoryMatched', 'relocationVerified',
                     'sameVersionCoexistenceVerified', 'corruptionDetected', 'repairVerified'):
            self.assertIs(receipt[flag], True)
        self.assertIs(receipt['existingHwpPreserved']['passed'], True)
        self.assertIs(receipt['updateVerified'], False)
        self.assertIs(receipt['guiVerified'], False)
        foreign_cwd = Path(published['SUITE_FOREIGN_CWD'])
        self.assertTrue(foreign_cwd.is_dir())
        self.assertEqual(foreign_cwd.parent, repaired.parent)
        self.assertFalse(foreign_cwd.is_relative_to(repaired))
        self.assertFalse(repaired.is_relative_to(foreign_cwd))
        self.assertTrue(any(ord(char) > 127 for char in str(foreign_cwd)))
        self.assertIn(' ', str(foreign_cwd))
        self.assertNotEqual(self.fixture.snapshot(Path(receipt['extractedRoot'])), before)

    def test_corrupt_final_zip_fails_build_without_publishing_package(self):
        before = self.fixture.snapshot(self.fixture.root)
        self.fixture.zip([(name, data + b'corrupt' if name == 'worker/session.py' else data)
                          for name, data in self.fixture.members])
        process, published, _ = self.execute_build()
        self.assertNotEqual(process.returncode, 0, 'A corrupt final ZIP did not fail the build step')
        self.assertEqual(published, {})
        self.assertEqual(self.fixture.snapshot(self.fixture.root), before)

    def test_receipt_source_commit_must_match_the_workflow_event(self):
        process, published, _ = self.execute_build(source_commit='b'*40)
        self.assertNotEqual(process.returncode, 0, 'A receipt for another source commit qualified')
        self.assertEqual(published, {})

    def test_receipt_architecture_must_match_the_matrix(self):
        process, published, _ = self.execute_build(architecture='arm64')
        self.assertNotEqual(process.returncode, 0, 'An x64 receipt qualified the ARM64 matrix')
        self.assertEqual(published, {})

    def test_diagnostic_build_keeps_the_staged_baseline(self):
        process, published, _ = self.execute_build(mode='focus-diagnostic')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(published, {})
        self.assertFalse((self.checkout / '.work/suite-portable').exists())

    def test_sequenced_arm_writer_diagnostic_uses_the_same_repaired_payload_and_foreign_cwd(self):
        self.fixture.provenance['architecture'] = 'arm64'
        for path in self.fixture.root.rglob('*'):
            if path.is_file() and (path.suffix in ('.exe', '.bin') or path.name == 'hostfxr.dll'):
                self.fixture.write(path.relative_to(self.fixture.root), portable_tests.pe(0xaa64))
        self.fixture.source_archive()
        self.fixture.save_metadata()
        self.fixture.inventory = payload.create_inventory(self.fixture.root, architecture='arm64')
        self.fixture.write_json(payload.INVENTORY, self.fixture.inventory)
        self.fixture.members = [(p.relative_to(self.fixture.root).as_posix(), p.read_bytes())
                               for p in sorted(self.fixture.root.rglob('*')) if p.is_file()]
        self.fixture.zip(self.fixture.members)
        before = self.fixture.snapshot(self.fixture.root)
        process, published, archive = self.execute_build(mode='ime-mode-diagnostic', architecture='arm64')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('SUITE_PACKAGE', published, 'Writer diagnosis skipped the original portable preparation')
        repaired = Path(published['SUITE_PACKAGE'])
        self.assertEqual(repaired.name, 'OpenGeul Office 복구 검증')
        self.assertEqual(self.fixture.snapshot(repaired), before)
        self.assertEqual(self.fixture.snapshot(self.fixture.root), before)
        self.assertEqual(Path(published['SUITE_ARCHIVE']), archive)
        foreign_cwd = Path(published['SUITE_FOREIGN_CWD'])
        self.assertTrue(foreign_cwd.is_dir())
        self.assertFalse(repaired.is_relative_to(foreign_cwd))

    def test_x64_writer_diagnostic_cannot_promote_a_portable_payload(self):
        process, published, _ = self.execute_build(mode='ime-mode-diagnostic')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(published, {})
        self.assertFalse((self.checkout / '.work/suite-portable').exists())

    def test_following_gates_keep_startup_count_evidence_and_original_zip_handoff(self):
        steps = workflow_steps()
        startup = next(step for step in steps if 'python suite/e2e/startup_smoke.py ' in step)
        code = run_code(startup)
        self.assertIn('--launch-cwd $env:SUITE_FOREIGN_CWD --output .work/suite-startup --attempts 40', code)
        evidence = next(step for step in steps if field(step, 'if') ==
                        '"env.OPENGEUL_SUITE_RUN_MODE == \'acceptance\' && (always())"')
        self.assertIn('.work/suite-portable/', evidence)
        delivery = steps[-1]
        self.assertIn('        path: ${{ env.SUITE_ARCHIVE }}\n', delivery)
        self.assertEqual(field(delivery, 'if'),
                         '"env.OPENGEUL_SUITE_RUN_MODE == \'acceptance\' && (success() && steps.home-routes.outcome == \'success\')"')


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the real command boundary')
class FinalZipProofWorkflowTests(unittest.TestCase):
    PREFIX = '::notice title=OpenGeul portable ZIP proof::'

    def proof_step(self):
        proof = next((step for step in workflow_steps() if field(step, 'id') == 'final-zip-proof'), None)
        self.assertIsNotNone(proof, 'Final product ZIP proof step is missing')
        return proof

    def execute_proof(self, *, change=None, mutate_zip=False, mode='acceptance', architecture='arm64'):
        with tempfile.TemporaryDirectory(prefix='OpenGeul final ZIP 경계 ') as temporary:
            root = Path(temporary)
            archive = root / '최종 원본 & $payload.zip'
            with zipfile.ZipFile(archive, 'w') as stream:
                stream.writestr('synthetic.txt', 'synthetic payload only')
            digest, length = hashlib.sha256(archive.read_bytes()).hexdigest(), archive.stat().st_size
            receipt = dict(schemaVersion=1, kind='portable-package-file-check',
                sourceCommit='a'*40, architecture=architecture, archivePath=str(archive),
                archiveSha256=digest, passed=True, archiveInventoryMatched=True,
                relocationVerified=True, sameVersionCoexistenceVerified=True,
                corruptionDetected=True, repairVerified=True,
                updateVerified=False, guiVerified=False, existingHwpPreserved=dict(passed=True))
            receipt.update(change or {})
            directory = root / '.work/suite-portable'; directory.mkdir(parents=True)
            (directory / f'123-{architecture}-1 휴대용 검증.receipt.json').write_text(
                json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
            if mutate_zip:
                with archive.open('ab') as stream: stream.write(b'changed after the original check')
            code = run_code(self.proof_step()).replace('${{ matrix.architecture }}', architecture)
            script = root / 'boundary.ps1'; script.write_text(code, encoding='utf-8')
            environment = dict(os.environ, OPENGEUL_SUITE_RUN_MODE=mode, GITHUB_SHA='a'*40,
                GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', SUITE_ARCHIVE=str(archive))
            result = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive',
                '-File', str(script)], cwd=root, env=environment, capture_output=True,
                text=True, encoding='utf-8', timeout=30)
            return result, digest, length, str(root)

    def test_valid_current_receipt_emits_only_bound_product_zip_fields(self):
        for architecture in ('x64', 'arm64'):
            with self.subTest(architecture=architecture):
                result, digest, length, private_root = self.execute_proof(architecture=architecture)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stderr, '')
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith(self.PREFIX))
                message = lines[0][len(self.PREFIX):]
                self.assertLessEqual(len(message.encode('utf-8')), 1024)
                self.assertEqual(json.loads(message), dict(schemaVersion=1, sourceCommit='a'*40,
                    runId=123, runAttempt=1, architecture=architecture, sha256=digest, bytes=length))
                self.assertNotIn(private_root, result.stdout)

    def test_changed_zip_rejects_without_publishing_a_notice(self):
        result, *_ = self.execute_proof(mutate_zip=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(self.PREFIX, result.stdout)

    def test_wrong_source_path_architecture_or_incomplete_receipt_rejects(self):
        for change in ({'sourceCommit': 'b'*40}, {'architecture': 'x64'}, {'archivePath': '/foreign.zip'},
                       {'repairVerified': False}, {'passed': False}, {'guiVerified': True},
                       {'kind': ['portable-package-file-check']}):
            with self.subTest(change=tuple(change)):
                result, *_ = self.execute_proof(change=change)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(self.PREFIX, result.stdout)

    def test_diagnostic_mode_cannot_publish_product_zip_proof(self):
        result, *_ = self.execute_proof(mode='calc-dispatch-diagnostic')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(self.PREFIX, result.stdout)

    def test_workflow_matches_candidate_upload_condition_and_precedes_it(self):
        steps = workflow_steps(); proof = self.proof_step(); delivery = steps[-1]
        self.assertEqual(steps[-2], proof)
        self.assertEqual(condition(proof), condition(delivery))
        expression = condition(proof)
        for mode in ('acceptance', 'calc-dispatch-diagnostic', 'ime-mode-diagnostic', 'focus-diagnostic', 'unknown'):
            for success in (False, True):
                for home in ('success', 'failure', 'skipped'):
                    with self.subTest(mode=mode, success=success, home=home):
                        self.assertEqual(evaluate(expression.replace('success()', str(success)), mode,
                            'arm64', {'home-routes': home}), mode == 'acceptance' and success and home == 'success')


if __name__ == '__main__':
    unittest.main()
