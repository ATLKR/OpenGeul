"""Execute the acceptance build block with the real portable ZIP file check."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from suite import payload
from suite.tests import test_portable_package_check as portable_tests
from suite.tests.test_calc_matrix_workflow import field, run_code, workflow_steps


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


if __name__ == '__main__':
    unittest.main()
