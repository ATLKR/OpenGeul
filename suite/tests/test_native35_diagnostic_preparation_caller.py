"""Actual PowerShell caller boundaries with a committed non-native action stub."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CALLER = ROOT / 'suite/scripts/prepare-native35-input-witness.ps1'
BRANCH = 'refs/heads/work/native35-arm64-input-witness'
WORKFLOW = 'ATLKR/OpenGeul/.github/workflows/suite-native35-input-witness.yml@' + BRANCH
BASE_CRITICAL = (
    'e2e/native31_desktop_control.py', 'e2e/runner-ready.py', 'ci/policy.py',
    '.github/workflows/office-native31-desktop-control.yml', 'e2e/native31_privacy_prepare.py',
    '.github/workflows/office-native31-privacy-prepare.yml', 'suite/e2e/native_window_evidence.py',
    'e2e/native31_suite_prepare.py', '.github/workflows/office-suite.yml',
    'suite/scripts/prepare-native31.ps1')
ADDED_CRITICAL = ('e2e/native35_input_witness_prepare.py',
                  'suite/scripts/prepare-native35-input-witness.ps1',
                  '.github/workflows/suite-native35-input-witness.yml')
STUB = '''import argparse,json,os,pathlib,sys
p=argparse.ArgumentParser();p.add_argument('--prepare-privacy',action='store_true');p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
assert a.prepare_privacy
a.output.mkdir()
(a.output/'99-result.json').write_text(json.dumps(dict(success=True,privacyPreparationQualified=True,physicalTaskbarGatePassed=True,partial='original')))
pathlib.Path(os.environ['TEST_INVOCATION']).write_text(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd(),ref=os.environ['GITHUB_REF'],workflow=os.environ['GITHUB_WORKFLOW_REF'],job=os.environ['GITHUB_JOB'])))
sys.exit(int(os.environ.get('TEST_ENTRY_EXIT','0')))
'''


def workflow_run_block(path):
    steps = re.split(r'(?m)^    - ', path.read_text())
    step = next(s for s in steps if re.search(r'(?m)^      id: diagnostic-preparation$', s))
    block = re.search(r'(?m)^      run: \|\n((?:        .*\n)+)', step)
    assert block is not None, 'Diagnostic workflow preparation has no literal run block'
    return '\n'.join(line[8:] for line in block.group(1).splitlines()) + '\n'


class DiagnosticPreparationCallerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CALLER.is_file(), 'Diagnostic preparation caller is missing')
        self.pwsh = shutil.which('pwsh')
        if not self.pwsh:
            self.skipTest('PowerShell is required for actual caller boundaries')

    def fixture(self, folder):
        root, runner = folder / 'main', folder / 'runner'
        root.mkdir(); runner.mkdir()
        for name in BASE_CRITICAL + ADDED_CRITICAL:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(STUB.encode() if name == ADDED_CRITICAL[0] else (ROOT / name).read_bytes())
        (root / '.gitattributes').write_text('* text eol=lf\n')
        (root / '.gitignore').write_text('.work/\ndist/\n')
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
        git('init', '-q'); git('config', 'user.name', 'Diagnostic caller test')
        git('config', 'user.email', 'test@example.invalid'); git('add', '.')
        git('commit', '-qm', 'committed diagnostic fixture')
        sha = git('rev-parse', 'HEAD')
        (root / '.work').mkdir(); (root / '.work/generated.bin').write_bytes(b'generated')
        (root / 'dist').mkdir(); (root / 'dist/generated.zip').write_bytes(b'generated')
        event = folder / 'event.json'
        payload = dict(repository=dict(full_name='ATLKR/OpenGeul', id=123, private=False),
                       sender=dict(login='ATLKR', id=65988341, type='User'), ref=BRANCH, deleted=False, after=sha)
        event.write_text(json.dumps(payload))
        env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                   RUNNER_OS='Windows', RUNNER_ARCH='ARM64', GITHUB_REPOSITORY='ATLKR/OpenGeul',
                   GITHUB_EVENT_NAME='push', GITHUB_JOB='windows-suite', GITHUB_REF=BRANCH,
                   GITHUB_WORKFLOW_REF=WORKFLOW, GITHUB_SHA=sha, GITHUB_WORKFLOW_SHA=sha,
                   GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_ACTOR='ATLKR',
                   GITHUB_ACTOR_ID='65988341', GITHUB_EVENT_PATH=str(event),
                   GITHUB_WORKSPACE=str(root), RUNNER_TEMP=str(runner),
                   TEST_INVOCATION=str(folder / 'invocation.json'), TEST_ENTRY_EXIT='0')
        env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']
        return root, runner, sha, git, event, payload, env

    def powershell(self, folder, code, env, *, root=None):
        script = folder / 'boundary.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. '" + str(CALLER).replace("'", "''") + "'\n" + code)
        return subprocess.run([self.pwsh, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                              cwd=root or folder, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=50)

    def test_exact_context_rejects_spoofed_ref_owner_source_and_private_event(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            root, runner, sha, git, event, payload, env = self.fixture(folder)
            run = self.powershell(folder, 'Assert-Native35DiagnosticContext', env)
            self.assertEqual(run.returncode, 0, run.stdout)
            for key, value in [('GITHUB_REF', 'refs/heads/work/opengeul-office-arm64'),
                               ('GITHUB_WORKFLOW_REF', WORKFLOW + '-other'), ('GITHUB_JOB', 'prepare'),
                               ('RUNNER_ARCH', 'X64'), ('GITHUB_ACTOR', 'other'),
                               ('GITHUB_SHA', '0' * 40), ('GITHUB_WORKFLOW_SHA', 'b' * 40)]:
                with self.subTest(key=key):
                    run = self.powershell(folder, 'Assert-Native35DiagnosticContext', {**env, key: value})
                    self.assertNotEqual(run.returncode, 0, run.stdout)
            for patch in [dict(repository={**payload['repository'], 'private': True}),
                          dict(sender={**payload['sender'], 'id': 1}), dict(after='b' * 40), dict(deleted=True)]:
                with self.subTest(event=patch):
                    event.write_text(json.dumps({**payload, **patch}))
                    run = self.powershell(folder, 'Assert-Native35DiagnosticContext', env)
                    self.assertNotEqual(run.returncode, 0, run.stdout)
            self.assertFalse(Path(env['TEST_INVOCATION']).exists())

    def test_exact_source_extension_detaches_without_generated_payload_or_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            root, runner, sha, git, event, payload, env = self.fixture(folder)
            hooks = folder / 'untrusted-hooks'; hooks.mkdir()
            marker = folder / 'hook-executed'
            hook = hooks / 'post-checkout'; hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n'); hook.chmod(0o755)
            git('config', 'core.hooksPath', str(hooks)); git('config', 'core.autocrlf', 'true')
            setup = runner / 'setup'; setup.mkdir()
            source, proof = runner / 'source', folder / 'proof.json'
            code = '''$expected = @(''' + ','.join("'" + x + "'" for x in BASE_CRITICAL + ADDED_CRITICAL) + ''')
Assert-Native31 (($Native31Critical -join '|') -ceq ($expected -join '|')) 'Critical extension differs.'
$state=@{Clock=[Diagnostics.Stopwatch]::StartNew();Commands=[Collections.Generic.List[object]]::new()}
$proof=New-Native31Source $env:GITHUB_WORKSPACE $env:TEST_SOURCE $env:TEST_SETUP $state
Write-Native31Json $env:TEST_PROOF @{proof=$proof;commands=$state.Commands}
'''
            run = self.powershell(folder, code, {**env, 'TEST_SOURCE': str(source), 'TEST_SETUP': str(setup), 'TEST_PROOF': str(proof)})
            self.assertEqual(run.returncode, 0, run.stdout)
            record = json.loads(proof.read_text())
            self.assertEqual(record['proof']['action']['head'], sha)
            self.assertTrue(record['proof']['detached'] and record['proof']['strictClean'])
            self.assertEqual(set(record['proof']['files']), set(BASE_CRITICAL + ADDED_CRITICAL))
            self.assertFalse((source / '.work').exists()); self.assertFalse((source / 'dist').exists())
            self.assertFalse(marker.exists()); self.assertTrue((source / '.git').is_file())
            self.assertLessEqual(len(record['commands']), 64)
            for name, pin in record['proof']['files'].items():
                raw = (source / name).read_bytes()
                self.assertEqual(raw, subprocess.check_output(['git', '-C', str(root), 'show', sha + ':' + name]))
                self.assertEqual(hashlib.sha256(raw).hexdigest(), pin['sha256'])

    def test_entry_and_staging_failures_preserve_raw_core_truth_and_primary_error(self):
        for exit_code, stage_failure in [(0, False), (7, False), (0, True), (7, True)]:
            with self.subTest(exit=exit_code, stage_failure=stage_failure), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                root, runner, sha, git, event, payload, env = self.fixture(folder)
                destination = root / '.work/suite-input-witness-preparation'
                if stage_failure:
                    destination.mkdir(); (destination / 'old.json').write_bytes(b'old evidence')
                block = workflow_run_block(root / ADDED_CRITICAL[2])
                self.assertNotIn('$LASTEXITCODE', block)
                script = folder / 'workflow-boundary.ps1'
                script.write_text("Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue\n" + block)
                run = subprocess.run(
                    [self.pwsh, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                    cwd=root, env={**env, 'TEST_ENTRY_EXIT': str(exit_code)},
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=50)
                self.assertEqual(run.returncode == 0, exit_code == 0 and not stage_failure, run.stdout)
                setup = runner / 'suite-input-witness-setup-123-1'
                control = runner / 'suite-input-witness-preparation-123-1'
                source = runner / 'suite-input-witness-source-123-1'
                raw = (control / '99-result.json').read_bytes()
                self.assertTrue(json.loads(raw)['privacyPreparationQualified'])
                self.assertTrue(json.loads(raw)['physicalTaskbarGatePassed'])
                invocation = json.loads(Path(env['TEST_INVOCATION']).read_text())
                self.assertTrue(Path(invocation['cwd']).samefile(source))
                self.assertEqual(invocation['argv'], ['--prepare-privacy', '--output', str(control)])
                self.assertEqual((invocation['ref'], invocation['workflow'], invocation['job']), (BRANCH, WORKFLOW, 'windows-suite'))
                entry = json.loads((setup / '20-entry-exit.json').read_text())
                self.assertEqual(entry['exitCode'], exit_code)
                scope = json.loads((setup / '00-setup-start.json').read_text())
                for flag in ['success', 'qualification', 'privacyPreparationQualified', 'hostReadyQualified',
                             'productQualified', 'officeReplacementCertified', 'mainNativePrivacySetupPerformed']:
                    self.assertIs(scope[flag], False)
                self.assertTrue(scope['diagnosticOnly'] and scope['diagnosticPreparationSeparatelyRecorded'])
                self.assertEqual(scope['diagnosticPreparationEvidence'], '.work/suite-input-witness-preparation/')
                if exit_code:
                    self.assertTrue((setup / '90-caller-failure.json').is_file())
                if stage_failure:
                    self.assertEqual((destination / 'old.json').read_bytes(), b'old evidence')
                    staged = json.loads((setup / '99-staging-failure.json').read_text())
                    self.assertEqual(bool(staged['primaryFailure']), bool(exit_code))
                else:
                    self.assertEqual((destination / 'control/99-result.json').read_bytes(), raw)

    def test_workflow_run_block_uses_exception_outcome_without_native_exitcode(self):
        block = workflow_run_block(ROOT / ADDED_CRITICAL[2])
        self.assertIn("$ErrorActionPreference = 'Stop'", block)
        self.assertIn('./suite/scripts/prepare-native35-input-witness.ps1', block)
        self.assertNotIn('$LASTEXITCODE', block)

    def test_modified_source_or_nonroot_is_rejected_before_native_entry_and_staged(self):
        for mode in ['modified-adapter', 'nested-root']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                root, runner, sha, git, event, payload, env = self.fixture(folder)
                requested = root
                if mode == 'modified-adapter':
                    with (root / ADDED_CRITICAL[0]).open('ab') as stream:
                        stream.write(b'\n# uncommitted action change\n')
                else:
                    requested = root / 'nested'; requested.mkdir(); (requested / '.work').mkdir()
                run = self.powershell(folder, 'Invoke-Native35InputWitnessPreparation $env:TEST_ROOT $env:RUNNER_TEMP',
                                      {**env, 'TEST_ROOT': str(requested)}, root=root)
                self.assertNotEqual(run.returncode, 0, run.stdout)
                self.assertFalse(Path(env['TEST_INVOCATION']).exists())
                setup = runner / 'suite-input-witness-setup-123-1'
                self.assertTrue((setup / '90-caller-failure.json').is_file())
                self.assertTrue((requested / '.work/suite-input-witness-preparation/setup/90-caller-failure.json').is_file(), run.stdout)


if __name__ == '__main__':
    unittest.main()
