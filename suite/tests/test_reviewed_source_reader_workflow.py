"""Only the three reviewed reader routes may cross the historical job oracle."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from suite.tests.workflow_scope import suite_workflow_sections

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/office-suite.yml'
FIXTURE = ROOT / 'suite/tests/fixtures/writer-server-observer-normal-workflow.json'
FIXTURE_SHA = '191eb38642ecdc5d885815cea9567c70cdd49c7950d325403e143db113b62e2c'
ENTRIES = {
    'calc-save': ('calc_save_smoke.py', '.work/suite-calc-save'),
    'calc-close': ('calc_close_probe.py', '.work/suite-calc-close'),
    'ime': ('korean_ime_smoke.py', '.work/suite-korean-ime'),
}


class ReviewedSourceReaderWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text()
        self.normal = suite_workflow_sections(self.source)[1]
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA)
        self.original_sha = json.loads(raw)['normalJobTextSha256']
        self.steps = yaml.safe_load(self.source)['jobs']['windows-suite']['steps']

    def entry(self, name):
        script, output = ENTRIES[name]
        rows = [row for row in self.steps if
                'python suite/e2e/' + script + ' --suite' in row.get('run', '') and
                '--output ' + output + ' @sourceReaderArgs\n' in row.get('run', '')]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def pair(self, name):
        run = self.entry(name)['run']
        lines = run.splitlines(keepends=True)
        launch = next(i for i, line in enumerate(lines) if line.startswith('python '))
        # Preserve actual YAML literal bytes; do not manufacture the helper's
        # reviewed strings or derive the expected historical digest from them.
        return ''.join('        ' + line for line in lines[:launch + 1])

    def accepted(self, source):
        from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
        try:
            text = original_normal_oracle_text(source)
        except ValueError:
            return False
        return hashlib.sha256(text.encode()).hexdigest() == self.original_sha

    def test_current_three_reader_routes_match_the_immutable_historical_oracle(self):
        self.assertTrue(self.accepted(self.normal))
        for name in ENTRIES:
            pair = self.pair(name)
            self.assertEqual(self.normal.count(pair), 1)
            self.assertIn("-cnotin @('x64', 'arm64')", pair)
            self.assertIn("-ceq 'source-built-zip'", pair)
            self.assertIn("-cne 'msi'", pair)
            self.assertTrue(pair.endswith(' @sourceReaderArgs\n'))
        for name in ('calc-save', 'calc-close'):
            self.assertIn("$env:OPENGEUL_SUITE_RUN_MODE -ceq 'acceptance'", self.pair(name))

    def test_missing_one_or_all_reader_prologues_cannot_downgrade_to_legacy(self):
        all_removed = self.normal
        for name in ENTRIES:
            pair = self.pair(name)
            legacy = pair.splitlines(keepends=True)[-1].replace(' @sourceReaderArgs', '')
            with self.subTest(entry=name):
                self.assertFalse(self.accepted(self.normal.replace(pair, legacy, 1)))
            all_removed = all_removed.replace(pair, legacy, 1)
        self.assertFalse(self.accepted(all_removed))

    def test_partial_deleted_or_duplicated_reader_bytes_are_not_normalized(self):
        for name in ENTRIES:
            pair = self.pair(name)
            variants = (pair.replace('$sourceReaderArgs = @()\n', '', 1),
                        pair.replace(' @sourceReaderArgs\n', '\n', 1),
                        pair.replace("'--source-qualified-reader'", "'--other-reader'", 1),
                        pair + pair)
            for index, replacement in enumerate(variants):
                with self.subTest(entry=name, variant=index):
                    self.assertFalse(self.accepted(self.normal.replace(pair, replacement, 1)))

    def test_moving_a_whole_pair_or_only_its_prologue_still_fails_the_oracle(self):
        for name in ENTRIES:
            pair = self.pair(name)
            prologue, command = pair.rsplit('        python ', 1)
            command = '        python ' + command
            moved_pair = self.normal.replace(pair, '', 1) + pair
            split_pair = self.normal.replace(pair, command, 1) + prologue
            with self.subTest(entry=name):
                self.assertFalse(self.accepted(moved_pair))
                self.assertFalse(self.accepted(split_pair))

    def test_mode_format_architecture_and_condition_substitutions_are_rejected(self):
        for name in ENTRIES:
            pair = self.pair(name)
            replacements = [("-ceq 'source-built-zip'", "-eq 'source-built-zip'"),
                            ("-ceq 'source-built-zip'", "-ceq 'SOURCE-BUILT-ZIP'"),
                            ("-cne 'msi'", "-cne 'unknown'"),
                            ("-cnotin @('x64', 'arm64')", "-cnotin @('x64', 'arm64', 'x86')"),
                            ("'${{ matrix.architecture }}'", "'arm64'")]
            if name != 'ime':
                replacements.append(("-ceq 'acceptance'", "-ne 'diagnostic'"))
            for index, (before, after) in enumerate(replacements):
                with self.subTest(entry=name, variant=index):
                    self.assertIn(before, pair)
                    changed = pair.replace(before, after, 1)
                    self.assertFalse(self.accepted(self.normal.replace(pair, changed, 1)))

    def test_unrelated_gate_or_order_edits_remain_visible_to_frozen_digest(self):
        for changed in (self.normal.replace('timeout-minutes: 150', 'timeout-minutes: 151'),
                        self.normal.replace('run_unit_checks -s suite/tests', 'run_unit_checks -s another/tests'),
                        self.normal + '    - run: unreviewed_gate\n'):
            self.assertNotEqual(changed, self.normal)
            self.assertFalse(self.accepted(changed))

    def invoke(self, name, runtime_format, architecture, mode='acceptance'):
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell, 'Existing PowerShell is required')
        # Execute the complete original run block. A PowerShell function records
        # the actual Python argv, including array splatting, without launching
        # any engine, reader or external command.
        prefix = ("$ErrorActionPreference='Stop'\n$global:LASTEXITCODE=0\n"
                  "$script:launches=@()\n"
                  "function global:python { $script:launches += ,@($args); [IO.File]::WriteAllText($env:OWNED_READER_LAUNCH_WITNESS, '1'); $global:LASTEXITCODE=0 }\n")
        suffix = "\nWrite-Output (ConvertTo-Json -Depth 5 -Compress @{launches=@($script:launches)})\n"
        code = prefix + self.entry(name)['run'].replace('${{ matrix.architecture }}', architecture) + suffix
        with tempfile.TemporaryDirectory() as owned:
            script = Path(owned) / 'owned-reader-route.ps1'
            script.write_text(code)
            witness = Path(owned) / 'python-launch.numeric'
            child_env = {'PATH': str(Path(shell).parent), 'SUITE_RUNTIME_FORMAT': runtime_format,
                         'OPENGEUL_SUITE_RUN_MODE': mode, 'SUITE_PACKAGE': 'C:/SyntheticSuite', 'PYTHONUTF8': '1',
                         'OWNED_READER_LAUNCH_WITNESS': str(witness)}
            if os.name == 'nt':
                child_env['SystemRoot'] = os.environ.get('SystemRoot', r'C:\Windows')
            else:
                child_env['PATH'] += os.pathsep + '/usr/bin' + os.pathsep + '/bin'
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(script)],
                                    env=child_env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, timeout=15)
            result.python_launch_observed = witness.is_file()
            return result

    def expected_argv(self, name, extra):
        script, output = ENTRIES[name]
        value = ['suite/e2e/' + script, '--suite', 'C:/SyntheticSuite', '--fixtures', '.work/suite-engine/fixtures']
        if name == 'ime':
            value += ['--readiness', '.work/suite-korean-readiness/readiness.json']
        return value + ['--output', output] + extra

    def test_actual_powershell_launches_preserve_complete_commands_and_source_arguments(self):
        for name in ENTRIES:
            for architecture in ('x64', 'arm64'):
                for runtime_format in ('source-built-zip', 'msi'):
                    with self.subTest(entry=name, architecture=architecture, format=runtime_format):
                        result = self.invoke(name, runtime_format, architecture)
                        self.assertEqual(result.returncode, 0)
                        self.assertTrue(result.python_launch_observed)
                        extra = ['--source-qualified-reader', architecture] if runtime_format == 'source-built-zip' else []
                        self.assertEqual(json.loads(result.stdout), {'launches': [self.expected_argv(name, extra)]})

    def test_actual_powershell_unknown_profiles_stop_before_the_python_function(self):
        for name in ENTRIES:
            for runtime_format, architecture in [('SOURCE-BUILT-ZIP', 'arm64'), ('unknown', 'arm64'), ('', 'arm64'),
                                                ('source-built-zip', 'x86'), ('source-built-zip', 'ARM64'), ('source-built-zip', '')]:
                with self.subTest(entry=name, architecture=architecture):
                    result = self.invoke(name, runtime_format, architecture)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(result.python_launch_observed)
                    self.assertEqual(result.stdout, '')
        # A nonzero final exit alone cannot prove no earlier launch. This
        # deliberately wrong owned script must trip the independent witness.
        with patch.object(self, 'entry', return_value={'run': "python owned-fixture.py\nthrow 'Owned post-launch rejection'\n"}):
            result = self.invoke('ime', 'unknown', 'arm64')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.python_launch_observed)

    def test_actual_calc_diagnostic_keeps_original_commands_without_live_reader_authority(self):
        for name in ('calc-save', 'calc-close'):
            for runtime_format in ('source-built-zip', 'msi'):
                with self.subTest(entry=name, format=runtime_format):
                    result = self.invoke(name, runtime_format, 'arm64', mode='ime-mode-diagnostic')
                    self.assertEqual(result.returncode, 0)
                    self.assertTrue(result.python_launch_observed)
                    self.assertEqual(json.loads(result.stdout), {'launches': [self.expected_argv(name, [])]})


if __name__ == '__main__':
    unittest.main()
