"""Explicit B selection and preserved normal SDK surface; no SDK execution."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
MARKER = '[sdk-batch-codes]'
NOT_ADMITTED, ADMITTED, CANCELLED = '0', '1', '2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def selected(step, *, message='', cancelled=False, prior_success=True, eligible=NOT_ADMITTED,
             outcome='success'):
    text = step.get('if', 'true').strip().removeprefix('${{').removesuffix('}}').strip()
    explicit_status = any(name + '(' in text for name in ('always', 'cancelled', 'success', 'failure'))
    text = text.replace('github.event.head_commit.message', 'message')
    text = text.replace('steps.B.outputs.s', 'eligible')
    text = text.replace('steps.B.outcome', 'outcome')
    text = text.replace('&&', ' and ').replace('||', ' or ')
    text = re.sub(r'!(?!=)', ' not ', text).strip()
    tree = ast.parse(text, mode='eval')
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
               ast.Compare, ast.Eq, ast.NotEq, ast.Name, ast.Load, ast.Constant, ast.Call)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError('Unreviewed step selector grammar')
    functions = {'always': lambda: True, 'cancelled': lambda: cancelled,
                 'success': lambda: prior_success, 'failure': lambda: not prior_success,
                 'contains': lambda value, needle: needle.casefold() in value.casefold()}
    if any(not isinstance(node.func, ast.Name) or node.func.id not in functions
           for node in ast.walk(tree) if isinstance(node, ast.Call)):
        raise AssertionError('Unreviewed step selector call')
    result = bool(eval(compile(tree, 'closed-b-step-selector', 'eval'),
                       {'__builtins__': {}}, {**functions, 'message': message, 'eligible': eligible, 'outcome': outcome,
                                            'true': True, 'false': False}))
    return result and (explicit_status or prior_success)


class BatchSidecarWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.path = REPO / '.github/workflows/office-suite.yml'
        self.workflow = yaml.safe_load(self.path.read_bytes())
        self.job = self.workflow['jobs']['packaged-context-sdk']

    def step(self, name):
        if name == 'sdk-batch-artifact':
            found = [step for step in self.job['steps'] if step.get('with', {}).get('path', '').startswith(
                '.work/packaged-context-sdk-batch-public/')]
        elif name == 'sdk-batch-terminal':
            found = [step for step in self.job['steps'] if step.get('run', '').strip() == 'exit 1']
        else:
            found = [step for step in self.job['steps']
                     if step.get('id') == ('B' if name == 'sdk-batch-codes' else name)]
        self.assertEqual(len(found), 1, 'One explicit B workflow action is required')
        return found[0]

    def test_default_sdk_body_and_artifact_are_preserved_exactly(self):
        run = self.step('sdk-compile')['run']
        normalized = re.sub(r"(\$(?:entryPin|bootstrapPin|manifestPin) = ')[0-9a-f]{64}(')",
                            lambda match: match[1] + '0' * 64 + match[2], run)
        self.assertEqual(len(run), 20996)
        self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(),
                         '0051ea3156d0522a7282312b80b7602f4c5a79cc32fdffda32695ff513dbdf58')
        uploads = [step for step in self.job['steps']
                   if step.get('with', {}).get('path') ==
                   '.work/packaged-context-sdk-public/${{ matrix.os }}/report.numeric.json']
        self.assertEqual(len(uploads), 1)
        self.assertEqual(digest(uploads[0]), 'f2739c9168c824d91fae588b4c2b3163d14201ac8ac5f09df6778a83fb1461e7')

    def test_owner_selector_runners_permissions_and_other_jobs_are_unchanged(self):
        self.assertEqual(digest({key: value for key, value in self.job.items() if key != 'steps'}),
                         '36717af2c7ba7b3b8676ba9da7196dbf508de1e33d82ccaf3c2ab0b1bdb89053')
        self.assertEqual(digest({key: value for key, value in self.workflow.items() if key != 'jobs'}),
                         '480ebac8b3189aab470703b258204cbf7882dea48226fa6033f2d9de7c5ea26d')
        self.assertEqual(digest({key: value for key, value in self.workflow['jobs'].items()
                                 if key != 'packaged-context-sdk'}),
                         'fbe78765a01cd5bdbe0c1a65b37fc3f9cb44b8ec99ac633e91faaaa8e80da266')

    def test_explicit_marker_selects_b_instead_of_default_sdk(self):
        normal = self.step('sdk-compile')
        instrumented = self.step('sdk-batch-codes')
        for message, expected in (('', False), ('ordinary source repair', False),
                                  ('[ime-finalization-compile]', False), ('[sdk-batch-hints]', False),
                                  ('[sdk-batch-codes-other]', False), ('[sdk-batch-codes', False),
                                  ('sdk-batch-codes', False), (MARKER, True), (MARKER.upper(), True),
                                  ('observe ' + MARKER + ' only', True)):
            with self.subTest(case=expected, messageRole=len(message)):
                self.assertIs(selected(instrumented, message=message), expected)
                self.assertIs(selected(normal, message=message), not expected)

    def test_cancelled_b_does_not_start_the_run_upload_or_terminal(self):
        for name in ('sdk-batch-codes', 'sdk-batch-artifact', 'sdk-batch-terminal'):
            step = self.step(name)
            self.assertFalse(selected(step, message=MARKER, cancelled=True,
                                      prior_success=False, eligible=ADMITTED))

    def test_b_artifact_requires_exact_admission_even_after_run_failure(self):
        upload = self.step('sdk-batch-artifact')
        for eligible in ('false', '', 'TRUE', 'true', '01', NOT_ADMITTED, CANCELLED):
            self.assertFalse(selected(upload, message=MARKER, prior_success=False, eligible=eligible))
        self.assertTrue(selected(upload, message=MARKER, prior_success=False, eligible=ADMITTED))
        self.assertFalse(selected(upload, message='', prior_success=False, eligible=ADMITTED))
        paths = upload['with']['path'].splitlines()
        self.assertEqual(paths, [
            '.work/packaged-context-sdk-batch-public/${{ matrix.os }}/controller.numeric.json',
            '.work/packaged-context-sdk-batch-public/${{ matrix.os }}/batch-hints.numeric.json'])
        self.assertEqual(upload['with']['retention-days'], 1)
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertEqual(upload['uses'], 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02')

    def test_b_terminal_qualifies_no_success_even_after_missing_state_or_artifact_failure(self):
        terminal = self.step('sdk-batch-terminal')
        for outcome in ('success', 'failure', 'cancelled', 'skipped', '', None, 'unknown'):
            for prior in (False, True):
                for signal in (NOT_ADMITTED, ADMITTED, CANCELLED, '', None, 'unknown'):
                    with self.subTest(outcome=outcome, earlierStepsSucceeded=prior, signal=signal):
                        self.assertIs(selected(terminal, message=MARKER, prior_success=prior,
                                               eligible=signal, outcome=outcome), outcome == 'success')
            self.assertFalse(selected(terminal, message='', prior_success=False, outcome=outcome))
        self.assertEqual(terminal['shell'], 'pwsh')
        self.assertEqual(terminal['run'].strip(), 'exit 1')

    def test_child_cancellation_stops_upload_and_terminal_without_a_github_job_cancel(self):
        for name in ('sdk-batch-artifact', 'sdk-batch-terminal'):
            for success in (False, True):
                with self.subTest(role=name, priorSucceeded=success):
                    self.assertFalse(selected(self.step(name), message=MARKER, cancelled=False,
                                              prior_success=success, eligible=CANCELLED, outcome='failure'))

    def test_b_invokes_separate_admitted_controller_and_verifier_without_mode_inference(self):
        step = self.step('sdk-batch-codes')
        run = step['run']
        self.assertEqual(step['timeout-minutes'], 4)
        self.assertEqual(run.count('--instrumented-batch-codes'), 1)
        self.assertEqual(run.count('--verify-batch-codes-only'), 1)
        self.assertNotIn('--instrumented-batch-hints', run)
        self.assertNotIn('--verify-batch-sidecar-only', run)
        self.assertLess(run.index('--instrumented-batch-codes'), run.index('--verify-batch-codes-only'))
        for option in ('--architecture', '--expected-entry-sha256', '--expected-bootstrap-sha256',
                       '--expected-approved-manifest-sha256'):
            self.assertIn(option, run)
        self.assertNotIn('continue-on-error', step)
        self.assertNotIn('Invoke-Expression', run)
        self.assertNotIn('report.numeric.json', run)
        self.assertRegex(run, r'exit \$c\s*$')

    def test_b_controller_exit_is_not_overwritten_by_the_verifier(self):
        run = self.step('sdk-batch-codes')['run']
        self.assertEqual(len(re.findall(r'\$c\s*=\s*\$LASTEXITCODE', run)), 1)
        self.assertIn('$z = $LASTEXITCODE', run)
        self.assertLess(run.index('$c = $LASTEXITCODE'), run.index('--verify-batch-codes-only'))
        tail = run[run.index('--verify-batch-codes-only'):]
        self.assertEqual(re.findall(r'\$c\s*=\s*([0-9]+)', tail), ['130'])
        self.assertIn("if($z-in$x){$ok='2';if($c-eq0){$c=130};throw}", tail)

    def test_b2_preserves_b1_run_except_two_exact_prefixes_and_external_pins(self):
        run = self.step('sdk-batch-codes')['run']
        self.assertEqual(run.count('--instrumented-batch-codes'), 1)
        self.assertEqual(run.count('--verify-batch-codes-only'), 1)
        canonical = run.replace('--instrumented-batch-codes', '--instrumented-batch-hints', 1)
        canonical = canonical.replace('--verify-batch-codes-only', '--verify-batch-sidecar-only', 1)
        pins = list(re.finditer(r"\$p='[0-9a-f]{64}','[0-9a-f]{64}','[0-9a-f]{64}'", canonical))
        self.assertEqual(len(pins), 1)
        start, end = pins[0].span()
        canonical = canonical[:start] + re.sub('[0-9a-f]{64}', '0' * 64, pins[0].group()) + canonical[end:]
        self.assertEqual(len(canonical), 1955)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(),
                         'c2d54344e7b247c6af2a076b967a758a339c525dd02f4e358ae9fa90590a067b')

    def powershell(self, body, *, fixture=None, check_output=False, output_fault=False,
                   actual_exit=False):
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell, 'Existing PowerShell is required')
        with tempfile.TemporaryDirectory(prefix='sdk-b-workflow-') as td:
            root = Path(td)
            script = root / 'check.ps1'
            output = root / 'receipt.numeric.json'
            config = root / 'fixture.numeric.json'
            config.write_text(json.dumps(fixture or {}, separators=(',', ':')))
            script.write_text(body)
            signal = root / 'outputs.numeric.txt'
            if output_fault:
                signal.mkdir()
            environment = {'PATH': str(Path(shell).parent) + os.pathsep + os.defpath,
                           'HOME': td, 'XDG_CONFIG_HOME': td, 'POWERSHELL_TELEMETRY_OPTOUT': '1',
                           'GITHUB_OUTPUT': str(root / 'outputs.numeric.txt')}
            if os.name == 'nt':
                environment['SystemRoot'] = os.environ.get('SystemRoot', r'C:\Windows')
            with output.open('xb') as stream:
                child = subprocess.Popen([shell, '-NoLogo', '-NoProfile', '-NonInteractive',
                                          '-File', str(script), str(config)], cwd=root, env=environment,
                                         stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.DEVNULL)
                try:
                    code = child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=1)
                    self.fail('Pure PowerShell workflow check timed out')
            if not actual_exit:
                self.assertEqual(code, 0, 'Pure PowerShell workflow check failed')
            record = json.loads(output.read_bytes())
            if output_fault:
                self.assertTrue(signal.is_dir(), 'Existing output fault target must be preserved')
                self.assertEqual(list(signal.iterdir()), [])
            elif check_output:
                self.assertTrue(signal.is_file(), 'The downstream state output is required')
                self.assertLessEqual(signal.stat().st_size, 16)
                self.assertEqual(signal.read_text(encoding='utf-8-sig'), 's=' + record['eligible'] + '\n')
            if actual_exit:
                record['processExit'] = code
            return record

    def test_actual_powershell_parser_accepts_the_whole_new_run(self):
        run = self.step('sdk-batch-codes')['run']
        body = "$t=$null;$e=$null;$null=[System.Management.Automation.Language.Parser]::ParseInput(" + \
            "'" + run.replace("'", "''") + "',[ref]$t,[ref]$e);@{errors=$e.Count}|ConvertTo-Json -Compress"
        self.assertEqual(self.powershell(body), {'errors': 0})

    def envelope(self, *, admitted=True):
        return {'schemaVersion': 1, 'admitted': admitted,
                'controllerSha256': 'a' * 64 if admitted else None,
                'sidecarSha256': 'b' * 64 if admitted else None,
                'reasonCode': 0 if admitted else 7}

    def observe_verifier(self, payload, *, controller=2, verifier=0, output_fault=False,
                         actual_exit=False):
        run = self.step('sdk-batch-codes')['run']
        fragment = run.split('$c = $LASTEXITCODE;', 1)[1]
        self.assertTrue(fragment.endswith('exit $c\n'))
        fragment = fragment.removesuffix('exit $c\n')
        body = """param([string]$Config)
$ErrorActionPreference='Stop'
$fixture=Get-Content -LiteralPath $Config -Raw|ConvertFrom-Json
$c=$fixture.controller;$ok='0';$script:callCount=0;$py='Invoke-Fixture';$e='fixture';$q=@()
function Native-Exit([long]$value) {
    if($value-lt-2147483648-or$value-gt4294967295){throw 'Invalid synthetic native status'}
    if($value-gt2147483647){$value-=4294967296}
    return [int]$value
}
if($fixture.nativeCarrier) {
    if([Diagnostics.Process].GetProperty('ExitCode').PropertyType-ne[int]){throw 'Native exit carrier changed'}
    $c=Native-Exit $fixture.controller
}
function Invoke-Fixture {
    $script:callCount++
    $global:LASTEXITCODE=if($fixture.nativeCarrier){Native-Exit $fixture.verifier}else{$fixture.verifier}
    $fixture.payload
}
try{
""" + fragment + """
$record=[ordered]@{controllerExit=$c;verifierCalls=$script:callCount;eligible=$ok}
if($fixture.nativeCarrier){$record.carrierType=$c.GetType().FullName}
$record|ConvertTo-Json -Compress
""" + ('exit $c\n' if actual_exit else '')
        return self.powershell(body, fixture={'payload': payload, 'controller': controller, 'verifier': verifier,
                                              'nativeCarrier': actual_exit},
                               check_output=True, output_fault=output_fault, actual_exit=actual_exit)

    def test_actual_powershell_preserves_primary_failure_and_admits_only_valid_five_fields(self):
        payload = json.dumps(self.envelope(), sort_keys=True, separators=(',', ':'))
        for controller in (0, 2, 5):
            record = self.observe_verifier(payload, controller=controller)
            self.assertEqual(record, {'controllerExit': controller, 'verifierCalls': 1, 'eligible': ADMITTED})

    def test_actual_powershell_skips_the_verifier_for_each_cancellation_exit_form(self):
        payload = json.dumps(self.envelope(), separators=(',', ':'))
        for controller in (130, 3221225786, -1073741510):
            record = self.observe_verifier(payload, controller=controller)
            self.assertEqual(record, {'controllerExit': controller, 'verifierCalls': 0, 'eligible': CANCELLED})

    def test_actual_powershell_propagates_verifier_cancellation_instead_of_the_controller_result(self):
        payload = json.dumps(self.envelope(), separators=(',', ':'))
        for controller in (0, 2, 5):
            for verifier in (130, 3221225786, -1073741510):
                with self.subTest(controller=controller, verifier=verifier):
                    self.assertEqual(self.observe_verifier(payload, controller=controller, verifier=verifier),
                                     {'controllerExit': 130 if controller == 0 else controller,
                                      'verifierCalls': 1, 'eligible': CANCELLED})

    def test_actual_powershell_rejects_malformed_or_unavailable_verifier_results(self):
        variants = []
        for key, value in (('schemaVersion', True), ('schemaVersion', 2), ('admitted', 'true'),
                           ('reasonCode', True), ('reasonCode', 1), ('controllerSha256', 'a' * 63),
                           ('sidecarSha256', ['b' * 64]), ('unexpected', 0)):
            item = self.envelope()
            item[key] = value
            variants.append(json.dumps(item, separators=(',', ':')))
        item = self.envelope()
        del item['sidecarSha256']
        variants.append(json.dumps(item, separators=(',', ':')))
        variants.extend(('not JSON', 'x' * 513, [json.dumps(self.envelope())] * 2,
                         json.dumps(self.envelope(admitted=False), separators=(',', ':'))))
        for index, payload in enumerate(variants):
            with self.subTest(case=index):
                record = self.observe_verifier(payload)
                self.assertEqual(record, {'controllerExit': 2, 'verifierCalls': 1, 'eligible': NOT_ADMITTED})
        payload = json.dumps(self.envelope(), separators=(',', ':'))
        self.assertEqual(self.observe_verifier(payload, verifier=1),
                         {'controllerExit': 2, 'verifierCalls': 1, 'eligible': NOT_ADMITTED})

    def test_actual_output_write_fault_preserves_primary_exit_and_downstream_fail_closed(self):
        payload = json.dumps(self.envelope(), separators=(',', ':'))
        cases = [(code, 0) for code in (0, 2, 5, 130, 3221225786, -1073741510)]
        cases.extend((code, cancel) for code in (2, 5)
                     for cancel in (130, 3221225786, -1073741510))
        for controller, verifier in cases:
            with self.subTest(controller=controller, verifier=verifier):
                record = self.observe_verifier(payload, controller=controller, verifier=verifier,
                                               output_fault=True, actual_exit=True)
                # NativeCommandProcessor assigns Process.ExitCode (Int32), not a JSON Int64.
                expected_carrier = controller - 4294967296 if controller > 2147483647 else controller
                self.assertEqual(record['controllerExit'], expected_carrier)
                self.assertEqual(record['carrierType'], 'System.Int32')
                self.assertIs(record['processExit'] == 0, controller == 0)
                outcome = 'success' if record['processExit'] == 0 else 'failure'
                self.assertFalse(selected(self.step('sdk-batch-artifact'), message=MARKER,
                                          prior_success=False, eligible='', outcome=outcome))
                self.assertIs(selected(self.step('sdk-batch-terminal'), message=MARKER,
                                       prior_success=False, eligible='', outcome=outcome), controller == 0)

    def test_new_runs_and_whole_workflow_stay_inside_existing_review_budgets(self):
        self.assertLessEqual(self.path.stat().st_size, 131072)
        for step in self.job['steps']:
            if 'run' in step:
                self.assertLessEqual(len(step['run']), 21000)
                self.assertNotIn('${{', step['run'])


if __name__ == '__main__':
    unittest.main()
