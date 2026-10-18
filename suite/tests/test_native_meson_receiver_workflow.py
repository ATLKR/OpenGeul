"""Narrow YAML contract and actual portable PowerShell workflow wiring.

These checks execute the workflow's pre-checkout budget/source guard and its
probe invocation. The probe stand-in records arguments and exercises status
propagation; it does not model the native Meson receiver or qualify Windows.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/office-native-meson-receiver-control.yml'
ENGINE_WORKFLOW = ROOT / '.github/workflows/office-native-engine.yml'
PWSH = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'
SOURCE_SHA = 'ba9280eb0fa2c5b427c4457bac6f73cb3339ee6d'
PROBE = './suite/scripts/probe-native-meson-receiver.ps1'


def workflow():
    assert WORKFLOW.is_file(), 'Dedicated native Meson receiver control workflow is missing'
    return yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))


def steps():
    jobs = workflow()['jobs']
    assert len(jobs) == 1, 'The receiver control must remain one bounded job'
    return next(iter(jobs.values()))['steps']


class NativeMesonReceiverWorkflowContractTests(unittest.TestCase):
    def test_push_and_dispatch_have_only_the_approved_control_scope(self):
        events = workflow()['on']
        self.assertEqual({'push', 'workflow_dispatch'}, set(events))
        self.assertEqual(['work/suite-native-meson-control'], events['push']['branches'])
        self.assertEqual([
            '.github/workflows/office-native-meson-receiver-control.yml',
            'suite/scripts/probe-native-meson-receiver.ps1',
            'suite/diagnostics/native-meson-receiver/**',
            'suite/tests/test_native_meson_receiver*.py',
        ], events['push']['paths'])
        self.assertEqual({'inputs'}, set(events['workflow_dispatch']))
        inputs = events['workflow_dispatch']['inputs']
        self.assertEqual({'source_sha'}, set(inputs))
        self.assertIs(True, inputs['source_sha']['required'])
        self.assertEqual('string', inputs['source_sha']['type'])
        self.assertNotIn('default', inputs['source_sha'])

    def test_read_only_single_arm64_job_reserves_the_twenty_minute_limit(self):
        definition = workflow()
        self.assertEqual({'contents': 'read'}, definition['permissions'])
        self.assertIs(False, definition['concurrency']['cancel-in-progress'])
        self.assertIn('${{ github.ref }}', definition['concurrency']['group'])
        self.assertEqual(1, len(definition['jobs']))
        job = next(iter(definition['jobs'].values()))
        self.assertEqual('windows-11-arm', job['runs-on'])
        self.assertEqual(20, job['timeout-minutes'])
        self.assertNotIn('permissions', job)
        self.assertNotIn('strategy', job)
        self.assertIn("github.repository == 'ATLKR/OpenGeul'", job['if'])
        self.assertIn("github.ref == 'refs/heads/work/suite-native-meson-control'", job['if'])
        self.assertTrue(all(step.get('shell') == 'pwsh' for step in steps() if 'run' in step))

    def test_checkout_is_immutable_and_reuses_existing_pinned_actions(self):
        actual = steps()
        self.assertEqual(5, len(actual))
        self.assertIn('run', actual[0], 'Deadline/source validation must precede checkout and setup')
        engine = yaml.safe_load(ENGINE_WORKFLOW.read_text(encoding='utf-8'))
        existing = {
            step['uses'].split('@')[0]: step['uses']
            for job in engine['jobs'].values() for step in job['steps'] if 'uses' in step
        }
        action_steps = [step for step in actual if 'uses' in step]
        self.assertEqual(['actions/checkout', 'actions/setup-python', 'actions/upload-artifact'],
                         [step['uses'].split('@')[0] for step in action_steps])
        for step in action_steps:
            action, pin = step['uses'].split('@')
            self.assertRegex(pin, r'^[0-9a-f]{40}$')
            self.assertEqual(existing[action], step['uses'])
        self.assertEqual({'ref': '${{ github.sha }}', 'persist-credentials': False, 'fetch-depth': 5}, actual[1]['with'])
        self.assertEqual({'python-version': '3.12', 'architecture': 'arm64'}, actual[2]['with'])
        self.assertEqual('${{ inputs.source_sha }}',
                         actual[0]['env']['OPENGEUL_MESON_CONTROL_REQUESTED_SHA'])
        self.assertNotIn('${{', actual[0]['run'], 'Untrusted dispatch text belongs in env, not PowerShell source')

    def test_evidence_is_always_retained_even_if_checkout_or_setup_fails(self):
        upload = steps()[-1]
        self.assertEqual('always()', upload['if'])
        options = upload['with']
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', options['name'])
        self.assertEqual([
            '${{ runner.temp }}/opengeul-native-meson-receiver-${{ github.run_id }}-${{ github.run_attempt }}/',
            '.work/native-meson-receiver-evidence/',
        ], options['path'].splitlines())
        self.assertNotIn('dmp', options['path'].lower())
        self.assertIs(True, options['include-hidden-files'])
        self.assertEqual('error', options['if-no-files-found'])
        self.assertEqual(7, options['retention-days'])


class NativeMesonReceiverWorkflowExecutionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path(PWSH).is_file(), 'Actual PowerShell is required; these wiring tests must not silently skip')
        self.temporary = tempfile.TemporaryDirectory(prefix='native-meson-workflow-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runner = self.root / 'runner'
        self.runner.mkdir()
        self.github_env = self.root / 'github-env'
        self.github_env.write_text('', encoding='utf-8')
        self.environment = dict(os.environ,
            RUNNER_TEMP=str(self.runner), GITHUB_ENV=str(self.github_env),
            GITHUB_SHA=SOURCE_SHA, GITHUB_EVENT_NAME='push', GITHUB_RUN_ID='12345',
            GITHUB_RUN_ATTEMPT='2', OPENGEUL_MESON_CONTROL_REQUESTED_SHA='',
            GIT_CONFIG_GLOBAL=str(self.root / 'git-global'), GIT_CONFIG_NOSYSTEM='1')

    def execute(self, body, **environment):
        script = self.root / 'actual-step.ps1'
        script.write_text(body, encoding='utf-8')
        return subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(script)],
            cwd=self.root, env=dict(self.environment, **environment),
            capture_output=True, text=True, timeout=20)

    def exported(self):
        return dict(line.split('=', 1) for line in self.github_env.read_text(encoding='utf-8-sig').splitlines())

    def test_first_step_starts_one_eighteen_minute_deadline_and_preserves_source_bytes(self):
        before = datetime.now(timezone.utc)
        result = self.execute(steps()[0]['run'])
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        after = datetime.now(timezone.utc)
        exported = self.exported()
        deadline = datetime.fromisoformat(exported['OPENGEUL_MESON_CONTROL_DEADLINE_UTC'].replace('Z', '+00:00'))
        self.assertGreaterEqual((deadline - before).total_seconds(), 18 * 60)
        self.assertLessEqual((deadline - after).total_seconds(), 18 * 60)
        receipt = json.loads(Path(exported['OPENGEUL_MESON_CONTROL_BUDGET_RECEIPT']).read_text(encoding='utf-8-sig'))
        self.assertEqual('first-user-step', receipt['origin'])
        self.assertEqual(exported['OPENGEUL_MESON_CONTROL_DEADLINE_UTC'], receipt['deadlineUtc'])
        self.assertEqual(18, receipt['controlMinutes'])
        self.assertEqual(20, receipt['jobTimeoutMinutes'])
        self.assertEqual(2, receipt['nominalReserveMinutes'])
        self.assertEqual(SOURCE_SHA, receipt['sourceSha'])
        self.assertEqual('component-receiver-feasibility-only', receipt['scope'])
        for setting, expected in [('core.autocrlf', 'false'), ('core.longpaths', 'true')]:
            configured = subprocess.run(['git', 'config', '--global', '--get', setting],
                env=self.environment, capture_output=True, text=True, check=True)
            self.assertEqual(expected, configured.stdout.strip())

    def test_dispatch_accepts_only_the_exact_immutable_workflow_sha(self):
        result = self.execute(steps()[0]['run'], GITHUB_EVENT_NAME='workflow_dispatch',
                              OPENGEUL_MESON_CONTROL_REQUESTED_SHA=SOURCE_SHA)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(Path(self.exported()['OPENGEUL_MESON_CONTROL_BUDGET_RECEIPT']).read_text(encoding='utf-8-sig'))
        self.assertEqual(SOURCE_SHA, receipt['requestedSourceSha'])

    def test_dispatch_rejects_missing_moving_malformed_or_mismatching_sources_before_setup(self):
        for attempt, requested in enumerate([
            '', 'work/suite-native-meson-control', 'x' * 40, 'a' * 41,
            'f' * 40, SOURCE_SHA.upper(), '$(Set-Content injected yes)',
        ], start=1):
            with self.subTest(requested=requested):
                result = self.execute(steps()[0]['run'], GITHUB_EVENT_NAME='workflow_dispatch',
                                      OPENGEUL_MESON_CONTROL_REQUESTED_SHA=requested,
                                      GITHUB_RUN_ATTEMPT=str(attempt))
                self.assertNotEqual(0, result.returncode)
                self.assertRegex(result.stderr, r'source_sha|immutable')
                self.assertFalse((self.root / 'injected').exists())
                self.assertFalse((self.root / 'git-global').exists())
                self.assertTrue(Path(self.exported()['OPENGEUL_MESON_CONTROL_BUDGET_RECEIPT']).is_file())

    def test_an_invalid_github_sha_is_rejected_without_accepting_a_branch(self):
        result = self.execute(steps()[0]['run'], GITHUB_SHA='work/suite-native-meson-control')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('immutable', result.stderr)

    def install_probe_argument_witness(self):
        probe = self.root / PROBE.removeprefix('./')
        probe.parent.mkdir(parents=True)
        probe.write_text('''[CmdletBinding()]
param([string]$WorkDirectory, [string]$OutputDirectory, [string]$DeadlineUtc)
[ordered]@{work=$WorkDirectory;output=$OutputDirectory;deadline=$DeadlineUtc} |
    ConvertTo-Json | Set-Content -LiteralPath 'probe-arguments.json' -Encoding utf8NoBOM
if ($env:PROBE_WIRING_MODE -eq 'exit') { exit 7 }
if ($env:PROBE_WIRING_MODE -eq 'throw') { throw 'original probe exception' }
''', encoding='utf-8')

    def invoke_probe_step(self, mode='success'):
        self.install_probe_argument_witness()
        run = steps()[3]['run']
        self.assertIn(PROBE, run)
        return self.execute('$global:LASTEXITCODE=99\n' + run,
            OPENGEUL_MESON_CONTROL_DEADLINE_UTC='2026-10-18T10:18:00.0000000Z', PROBE_WIRING_MODE=mode)

    def test_probe_gets_the_exact_work_evidence_paths_and_shared_deadline_despite_stale_native_exit(self):
        result = self.invoke_probe_step()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({
            'work': '.work/native-meson-receiver',
            'output': '.work/native-meson-receiver-evidence',
            'deadline': '2026-10-18T10:18:00.0000000Z',
        }, json.loads((self.root / 'probe-arguments.json').read_text(encoding='utf-8-sig')))

    def test_probe_nonzero_script_exit_cannot_be_coerced_into_success(self):
        result = self.invoke_probe_step('exit')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('Native Meson receiver control failed', result.stderr)

    def test_probe_original_exception_remains_a_failure(self):
        result = self.invoke_probe_step('throw')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('original probe exception', result.stderr)


if __name__ == '__main__':
    unittest.main()
