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


def workflow_test_environment(**overrides):
    # Child fixtures retain only nonsecret paths plus explicit synthetic inputs.
    names=('PATH','PATHEXT','SystemRoot','WINDIR','SystemDrive','ComSpec','TEMP','TMP',
           'HOME','USERPROFILE','LOCALAPPDATA','APPDATA','XDG_CACHE_HOME','XDG_CONFIG_HOME',
           'XDG_DATA_HOME','PYTHONUTF8')
    values={name:value for name in names if (value:=os.environ.get(name)) is not None}
    values.update(overrides)
    return values


class WorkflowFixtureEnvironmentTests(unittest.TestCase):
    def test_offline_child_environments_never_copy_or_enumerate_ambient_values(self):
        from unittest.mock import patch
        from suite.tests.test_fetch_source_engine import fetch_test_environment
        names={'PATH','PATHEXT','SystemRoot','WINDIR','SystemDrive','ComSpec','TEMP','TMP',
               'HOME','USERPROFILE','LOCALAPPDATA','APPDATA','XDG_CACHE_HOME','XDG_CONFIG_HOME',
               'XDG_DATA_HOME','PYTHONUTF8'}
        class Source:
            def __init__(self):self.read=[]
            def get(self,name):
                if name not in names:raise AssertionError('Ambient non-allowlisted read forbidden')
                self.read.append(name)
                return 'synthetic executable path' if name=='PATH' else None
            def __iter__(self):raise AssertionError('Ambient enumeration forbidden')
            def copy(self):raise AssertionError('Ambient copy forbidden')
            def keys(self):raise AssertionError('Ambient keys forbidden')
        for helper in (fetch_test_environment,workflow_test_environment):
            source=Source()
            with patch.object(os,'environ',source):values=helper(FIXTURE_ONLY='synthetic')
            self.assertEqual(dict(PATH='synthetic executable path',FIXTURE_ONLY='synthetic'),values)
            self.assertEqual(16,len(source.read));self.assertEqual(16,len(set(source.read)))
            self.assertEqual(names,set(source.read))


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
            "if ($Architecture -cne $env:PORTABLE_TEST_ARCHITECTURE) { throw 'Wrong build architecture.' }\n"
            "@{architecture=$Architecture;engineArchive=$EngineArchive;engineReceipt=$EngineReceipt}|ConvertTo-Json|Set-Content build-arguments.json\n",
            encoding='utf-8')
        self.env_file = self.checkout / 'github-env'
        self.env_file.touch()

    def execute_build(self, *, mode='acceptance', architecture='x64', source_commit='a'*40, runtime_format='msi', source_outcome='success'):
        archive = Path(str(self.fixture.root) + '.zip')
        shutil.copy2(self.fixture.archive, archive)
        build = next(step for step in workflow_steps() if field(step, 'id') == 'build')
        code = run_code(build).replace('${{ matrix.architecture }}', architecture).replace('${{ steps.source-engine.outcome }}', source_outcome)
        script = self.checkout / 'build-step.ps1'
        script.write_text("$ErrorActionPreference = 'Stop'\n"
                          "function python { & $env:PORTABLE_TEST_PYTHON @args }\n" + code,
                          encoding='utf-8')
        environment = workflow_test_environment( OPENGEUL_SUITE_RUN_MODE=mode,
                           SUITE_PACKAGE=str(self.fixture.root), GITHUB_ENV=str(self.env_file),
                           GITHUB_SHA=source_commit, GITHUB_RUN_ID='123456', GITHUB_RUN_ATTEMPT='2',
                           PORTABLE_TEST_ARCHITECTURE=architecture, PORTABLE_TEST_PYTHON=sys.executable,
                           SUITE_RUNTIME_FORMAT=runtime_format,
                           PYTHONPATH=str(ROOT))
        for name in ('SUITE_ARCHIVE', 'SUITE_FOREIGN_CWD'):
            environment.pop(name, None)
        process = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive',
                                  '-File', str(script)], cwd=self.checkout, env=environment,
                                 capture_output=True, text=True, encoding='utf-8', timeout=30)
        published = dict(line.split('=', 1) for line in self.env_file.read_text(encoding='utf-8-sig').splitlines())
        return process, published, archive


    def test_source_format_passes_exact_inputs_for_either_architecture(self):
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture):
                process,_,_=self.execute_build(mode='focus-diagnostic',architecture=architecture,runtime_format='source-built-zip')
                self.assertEqual(0,process.returncode,process.stdout+process.stderr)
                args=json.loads((self.checkout/'build-arguments.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(architecture,args['architecture'])
                self.assertEqual(f'.work/source-engine-input/OpenGeul-Office-engine-{architecture}.zip',args['engineArchive'])
                self.assertEqual('.work/source-engine-input/source-build-receipt.json',args['engineReceipt'])

    def test_source_fetch_failure_never_enters_an_msi_build(self):
        process,published,_=self.execute_build(mode='focus-diagnostic',runtime_format='source-built-zip',source_outcome='failure')
        self.assertNotEqual(0,process.returncode)
        self.assertFalse((self.checkout/'build-arguments.json').exists())
        self.assertEqual({},published)

    def test_portable_repair_does_not_republish_or_downgrade_the_admitted_runtime_format(self):
        process,published,_=self.execute_build(runtime_format='source-built-zip')
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertEqual(set(published),{'SUITE_PACKAGE','SUITE_ARCHIVE','SUITE_FOREIGN_CWD'})
        arguments=json.loads((self.checkout/'build-arguments.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(arguments['engineArchive'],'.work/source-engine-input/OpenGeul-Office-engine-x64.zip')
        self.assertEqual(arguments['engineReceipt'],'.work/source-engine-input/source-build-receipt.json')
        self.assertNotIn('SUITE_RUNTIME_FORMAT',published,'A repaired path cannot relabel the admitted runtime')

    def test_unknown_runtime_format_is_fatal_before_build(self):
        process,published,_=self.execute_build(mode='focus-diagnostic',runtime_format='unknown')
        self.assertNotEqual(0,process.returncode)
        self.assertFalse((self.checkout/'build-arguments.json').exists())
        self.assertEqual({},published)

    def test_runtime_input_selection_is_validated_before_format_based_fetch(self):
        steps=workflow_steps()
        selection=next((step for step in steps if field(step,'id')=='runtime-input'),None)
        self.assertIsNotNone(selection,'An explicit validated runtime selection step is required')
        fetch=next(step for step in steps if field(step,'id')=='source-engine')
        self.assertLess(steps.index(selection),steps.index(fetch))
        self.assertIn("env.SUITE_RUNTIME_FORMAT == 'source-built-zip'",condition(fetch))
        self.assertTrue(condition(fetch).startswith("env.SUITE_RUNTIME_FORMAT == 'source-built-zip' &&"))
        self.assertIn('-SourceLockPath $env:SUITE_RUNTIME_LOCK',run_code(fetch))


    def test_format_selected_fetch_retains_all_diagnostic_admission_guards(self):
        fetch=next(step for step in workflow_steps() if field(step,'id')=='source-engine')
        expression=condition(fetch)
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture):
                self.assertTrue(evaluate(expression,'acceptance',architecture,runtime_format='source-built-zip'))
                self.assertFalse(evaluate(expression,'acceptance',architecture,runtime_format='msi'))
                self.assertFalse(evaluate(expression,'acceptance',architecture,runtime_format='unknown'))
                self.assertFalse(evaluate(expression,'com-wait-diagnostic',architecture,runtime_format='source-built-zip'))
                for mode in ('focus-diagnostic','reader-console-diagnostic','ime-mode-diagnostic','matched-plugin-caller','sal-offset-mapping','mutex-function-mapping'):
                    self.assertFalse(evaluate(expression,mode,architecture,{'sal-offset-admission':'failure'},runtime_format='source-built-zip'))
                    self.assertEqual(architecture=='arm64',evaluate(expression,mode,architecture,{'sal-offset-admission':'success'},runtime_format='source-built-zip'))

    def test_runtime_selection_executes_strict_source_lock_validation_for_both_architectures(self):
        from suite.tests.test_prepare import source_build_fixture,x64_source_build_fixture
        selection=next(step for step in workflow_steps() if field(step,'id')=='runtime-input')
        for architecture in ('x64','arm64'):
            for mutation in (None,'unknown-format','bad-source-pin','missing-runtime'):
                with self.subTest(architecture=architecture,mutation=mutation),tempfile.TemporaryDirectory(prefix='runtime input selection ') as temporary:
                    root=Path(temporary);inputs=root/'fixture';inputs.mkdir()
                    _,runtime,_,_= (x64_source_build_fixture(inputs) if architecture=='x64' else source_build_fixture(inputs))
                    lock=dict(schemaVersion=1,architecture=architecture,version='0.1.0-dev',runtime=runtime)
                    if mutation=='unknown-format':runtime['format']='unknown'
                    elif mutation=='bad-source-pin':runtime['sourceBuild']['receiptSha256']='invalid'
                    elif mutation=='missing-runtime':lock.pop('runtime')
                    config=root/'suite/config';config.mkdir(parents=True)
                    name='runtime.arm64.lock.json' if architecture=='arm64' else 'runtime.lock.json'
                    (config/name).write_text(json.dumps(lock))
                    output=root/'github-env';output.touch();script=root/'selection.ps1'
                    code=run_code(selection).replace('${{ matrix.architecture }}',architecture)
                    script.write_text("$ErrorActionPreference='Stop'\nfunction python { & $env:PORTABLE_TEST_PYTHON @args }\n"+code)
                    environment=workflow_test_environment(GITHUB_ENV=str(output),PORTABLE_TEST_PYTHON=sys.executable,PYTHONPATH=str(ROOT))
                    process=subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(script)],cwd=root,env=environment,capture_output=True,text=True,timeout=30)
                    fields=dict(line.split('=',1) for line in output.read_text(encoding='utf-8-sig').splitlines())
                    if mutation is None:
                        self.assertEqual(0,process.returncode,process.stdout+process.stderr)
                        self.assertEqual('source-built-zip',fields['SUITE_RUNTIME_FORMAT'])
                        self.assertEqual('suite/config/'+name,fields['SUITE_RUNTIME_LOCK'])
                    else:
                        self.assertNotEqual(0,process.returncode);self.assertEqual({},fields)

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
            environment = workflow_test_environment( OPENGEUL_SUITE_RUN_MODE=mode, GITHUB_SHA='a'*40,
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
