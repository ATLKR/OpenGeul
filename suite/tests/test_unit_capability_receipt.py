"""Finite Suite capability receipts; portable fakes are not Windows qualification."""
from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'suite/scripts/unit-capability-receipt.py'
WORKFLOW = ROOT / '.github/workflows/office-suite.yml'
ENV_NAMES = (
    'OPENGEUL_FIREBIRD_PORT_REQUIRE_SOURCE', 'OPENGEUL_ATL_REQUIRE_CYGWIN_REPLAY',
    'OPENGEUL_MESON_REQUIRE_CYGWIN_REPLAY', 'OPENGEUL_FIREBIRD_SOURCE_ARCHIVE',
    'OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES', 'OPENGEUL_LIBREOFFICE_PYTHON_PATCHES',
    'OPENGEUL_LIBREOFFICE_ATL_SOURCE', 'OPENGEUL_LIBREOFFICE_MESON_SOURCE',
    'OPENGEUL_MDDS_SOURCE_ARCHIVE',
)


def unit_step():
    return next(block for block in re.split(r'^    - name: ', WORKFLOW.read_text(), flags=re.M)
                if block.startswith('Suite 단위 검사와 Windows shell 빌드 검사\n'))


def unit_code():
    match = re.search(r'^      run: \|\n((?:        .*\n|\n)+)', unit_step(), re.M)
    return textwrap.dedent(match[1])


def unit_environment():
    match = re.search(r'^      env:\n((?:        [A-Z0-9_]+:.*\n)+)', unit_step(), re.M)
    return {} if match is None else {key.strip():value.strip().strip("'\"")
        for key, value in (line.split(':', 1) for line in match[1].splitlines())}


class Observations:
    def __init__(self):
        self.paths = []
        self.tools = []
        self.git_calls = []
        self.git_stdout = b'a' * 40 + b'\n' + b'b' * 40 + b'\n'
        self.path_results = {'/usr/bin/make': False, '/bin/bash': True}
        self.tool_results = {'cc': None, 'gcc': 'C:/tools/gcc.exe', 'c++': None,
                             'g++': None, 'patch': 'C:/tools/patch.exe', 'autoconf': None}

    def is_file(self, path):
        # Logical query keys are portable; production observations stay untouched.
        logical_path = path.as_posix()
        self.paths.append(logical_path)
        return self.path_results[logical_path]

    def which(self, name):
        self.tools.append(name)
        return self.tool_results[name]

    def git(self, argv, **kwargs):
        self.git_calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=self.git_stdout, stderr=b'')


class UnitCapabilityReceiptTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.is_file(), 'Suite unit capability collector is missing')
        spec = importlib.util.spec_from_file_location('unit_capability_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                                RUNNER_OS='Windows', RUNNER_ARCH='ARM64',
                                GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_JOB='windows-suite',
                                GITHUB_SHA='a' * 40, GITHUB_RUN_ID='39494751608', GITHUB_RUN_ATTEMPT='1')
        self.observations = Observations()

    def collect(self, module, phase='before', **changes):
        arguments = dict(env=self.environment, source_root=self.root, cwd=self.root,
                         executable='C:/Python/python.exe', version='3.12.10 test interpreter',
                         os_name='nt', is_file=self.observations.is_file,
                         which=self.observations.which, git_runner=self.observations.git)
        arguments.update(changes)
        return module.collect(phase, **arguments)

    def test_whitelist_preserves_empty_and_unset_without_retaining_secrets(self):
        module = self.module()
        self.environment.update(OPENGEUL_FIREBIRD_SOURCE_ARCHIVE='',
                                OPENGEUL_LIBREOFFICE_PYTHON_PATCHES='C:/source with spaces',
                                GITHUB_TOKEN='do-not-retain', UNRELATED_SECRET='do-not-retain',
                                OPENGEUL_UNAPPROVED_VALUE='do-not-retain')
        row = self.collect(module)
        self.assertEqual(set(row['environment']), set(ENV_NAMES))
        self.assertEqual(row['environment']['OPENGEUL_FIREBIRD_SOURCE_ARCHIVE'], '')
        self.assertIsNone(row['environment']['OPENGEUL_LIBREOFFICE_FIREBIRD_PATCHES'])
        self.assertEqual(row['environment']['OPENGEUL_LIBREOFFICE_PYTHON_PATCHES'], 'C:/source with spaces')
        self.assertNotIn('do-not-retain', json.dumps(row))
        self.assertTrue(row['readOnly'])
        self.assertFalse(row['productExecuted'])

    def test_observes_exact_paths_and_which_results_without_executing_tools(self):
        for path_type in (PurePosixPath, PureWindowsPath):
            with self.subTest(path_type=path_type.__name__):
                observations = Observations()
                self.assertIs(observations.is_file(path_type('/usr/bin/make')), False)
                self.assertIs(observations.is_file(path_type('/bin/bash')), True)
                self.assertEqual(observations.paths, ['/usr/bin/make', '/bin/bash'])
        row = self.collect(self.module())
        self.assertEqual(self.observations.paths, ['/usr/bin/make', '/bin/bash'])
        self.assertEqual(self.observations.tools, ['cc', 'gcc', 'c++', 'g++', 'patch', 'autoconf'])
        self.assertIs(row['capabilities']['make'], False)
        self.assertIs(row['capabilities']['bash'], True)
        self.assertEqual(row['which'], self.observations.tool_results)
        self.assertEqual({k: row['capabilities'][k] for k in ('compiler', 'cxx', 'patch', 'autoconf')},
                         dict(compiler=True, cxx=False, patch=True, autoconf=False))

    def test_keeps_phase_interpreter_cwd_and_exact_source_run_identity(self):
        row = self.collect(self.module(), 'after')
        self.assertEqual((row['phase'], row['osName']), ('after', 'nt'))
        self.assertEqual((row['sourceCommit'], row['sourceTree']), ('a' * 40, 'b' * 40))
        self.assertEqual((row['runId'], row['runAttempt'], row['architecture']), (39494751608, 1, 'arm64'))
        self.assertEqual(row['interpreter'], dict(executable='C:/Python/python.exe', version='3.12.10 test interpreter'))
        self.assertEqual(row['cwd'], str(self.root.resolve()))
        argv, options = self.observations.git_calls[0]
        self.assertEqual(argv, ['git', '-C', str(self.root.resolve()), 'rev-parse', 'HEAD', 'HEAD^{tree}'])
        self.assertEqual(options['timeout'], 5)
        self.assertTrue(options['check'])

    def test_rejects_source_job_run_phase_and_cwd_drift(self):
        module = self.module()
        for field, value in [('GITHUB_SHA', 'c' * 40), ('GITHUB_RUN_ID', '01'),
                             ('GITHUB_RUN_ATTEMPT', '0'), ('GITHUB_JOB', 'prepare'),
                             ('GITHUB_REPOSITORY', 'foreign/OpenGeul'), ('RUNNER_ARCH', 'x86')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.collect(module, env={**self.environment, field: value})
        for phase in ('during', '', None):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                self.collect(module, phase)
        with self.assertRaises(ValueError):
            self.collect(module, cwd=self.root.parent)
        with self.assertRaises(ValueError):
            self.collect(module, os_name='posix')

    def test_bounds_git_receipt_and_does_not_convert_non_boolean_observations(self):
        module = self.module()
        self.observations.git_stdout = b'x' * 1025
        with self.assertRaises(ValueError):
            self.collect(module)
        self.observations.git_stdout = b'a' * 40 + b'\n' + b'b' * 40 + b'\n'
        self.observations.path_results['/usr/bin/make'] = 1
        with self.assertRaises(ValueError):
            self.collect(module)
        self.observations.path_results['/usr/bin/make'] = False
        self.observations.tool_results['gcc'] = 1
        with self.assertRaises(ValueError):
            self.collect(module)

    def test_git_timeout_remains_failure_before_any_receipt_is_written(self):
        module = self.module()
        def timeout(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        with self.assertRaises(subprocess.TimeoutExpired):
            self.collect(module, git_runner=timeout)
        self.assertFalse((self.root / '.work').exists())

    def test_exclusive_before_after_files_preserve_original_bytes(self):
        module = self.module()
        folder = self.root / '.work/suite-unit-capabilities'
        before = module.write_receipt(folder, self.collect(module))
        original = before.read_bytes()
        after = module.write_receipt(folder, self.collect(module, 'after'))
        self.assertEqual((before.name, after.name), ('before.json', 'after.json'))
        with self.assertRaises(FileExistsError):
            module.write_receipt(folder, self.collect(module))
        self.assertEqual(before.read_bytes(), original)
        self.assertEqual(json.loads(after.read_bytes())['phase'], 'after')

    def test_oversized_or_nonfinite_json_writes_no_partial_receipt(self):
        module = self.module()
        folder = self.root / '.work/suite-unit-capabilities'
        self.environment['OPENGEUL_LIBREOFFICE_ATL_SOURCE'] = 'x' * 65536
        with self.assertRaises(ValueError):
            module.write_receipt(folder, self.collect(module))
        self.assertFalse(folder.exists())
        self.environment.pop('OPENGEUL_LIBREOFFICE_ATL_SOURCE')
        row = self.collect(module); row['invalid'] = float('nan')
        with self.assertRaises(ValueError):
            module.write_receipt(folder, row)
        self.assertFalse(folder.exists())

    def test_output_alias_and_non_directory_fail_without_overwriting(self):
        module = self.module()
        destination = self.root / 'destination'; destination.mkdir()
        alias = self.root / 'alias'
        if os.name == 'nt':
            # Reparse metadata is portable to test without a symlink privilege.
            alias.mkdir()
            original_lstat = Path.lstat
            def reparse(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == alias else info
            row = self.collect(module)
            with patch.object(Path, 'lstat', reparse), self.assertRaises(ValueError):
                module.write_receipt(alias, row)
        else:
            alias.symlink_to(destination, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.write_receipt(alias, self.collect(module))
        self.assertEqual(list(destination.iterdir()), [])
        existing = self.root / 'file'; existing.write_bytes(b'preserve')
        with self.assertRaises((ValueError, FileExistsError, NotADirectoryError)):
            module.write_receipt(existing, self.collect(module))
        self.assertEqual(existing.read_bytes(), b'preserve')

    def test_cli_output_failure_returns_nonzero_and_keeps_existing_receipt(self):
        module = self.module()
        folder = self.root / 'receipts'
        row = self.collect(module)
        target = module.write_receipt(folder, row)
        original = target.read_bytes()
        error = io.StringIO()
        with patch.object(module, 'collect', return_value=row), redirect_stderr(error):
            status = module.main(['--phase', 'before', '--output', str(folder)])
        self.assertEqual(status, 1)
        self.assertIn('FileExistsError', error.getvalue())
        self.assertEqual(target.read_bytes(), original)


class UnitCapabilityWorkflowTests(unittest.TestCase):
    def test_receipts_bracket_only_the_existing_unit_process_and_reach_aggregate(self):
        code = unit_code()
        command = 'python -m suite.scripts.run_unit_checks -s suite/tests -v'
        self.assertIn('unit-capability-receipt.py --phase before', code)
        self.assertIn('unit-capability-receipt.py --phase after', code)
        self.assertLess(code.index('--phase before'), code.index(command))
        self.assertLess(code.index(command), code.index('--phase after'))
        self.assertLess(code.index('--phase after'), code.index('dotnet run --project'))
        self.assertIn('finally', code)
        self.assertIn("if ($LASTEXITCODE -ne 0) { throw 'Suite shell tests failed.' }", code)
        aggregate = next(block for block in re.split(r'^    - name: ', WORKFLOW.read_text(), flags=re.M)
                         if 'name: opengeul-suite-evidence-${{ matrix.architecture }}' in block)
        self.assertIn('.work/suite-unit-capabilities/', aggregate)
        self.assertEqual(WORKFLOW.read_text().count('id: native31-privacy-prepare'), 1)
        names = ['suite.tests.test_unit_capability_receipt.UnitCapabilityReceiptTests.test_whitelist_preserves_empty_and_unset_without_retaining_secrets',
                 'suite.tests.test_unit_capability_receipt.UnitCapabilityWorkflowTests.test_unit_failure_remains_primary_and_after_receipt_runs_before_core']
        isolated = ("import importlib.util,sys,unittest; assert importlib.util.find_spec('yaml') is None; "
                    "suite=unittest.defaultTestLoader.loadTestsFromNames(" + repr(names) + "); "
                    "result=unittest.TextTestRunner(verbosity=2).run(suite); "
                    "sys.exit(0 if result.wasSuccessful() and result.testsRun==2 and not result.skipped else 1)")
        process = subprocess.run([sys.executable, '-S', '-B', '-c', isolated], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stdout)

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the actual workflow command boundary')
    def test_unit_runner_uses_step_optin_and_exact_module_arguments(self):
        stub = r'''
        $ErrorActionPreference = 'Stop'
        function python {
            if ($args[0] -eq '-m') {
                if (($args -join ' ') -cne '-m suite.scripts.run_unit_checks -s suite/tests -v') { throw 'Unexpected unit runner route.' }
                if ($env:OPENGEUL_SUITE_UNIT_NOTICE -cne '1' -or (Test-Path Env:OPENGEUL_SUITE_NUMERIC_NOTICE)) { throw 'Unexpected unit notice scope.' }
                Add-Content $env:CAP_TEST_LOG 'unit-wrapper'
            } else {
                Add-Content $env:CAP_TEST_LOG $args[[Array]::IndexOf($args, '--phase') + 1]
            }
            $global:LASTEXITCODE = 0
        }
        function dotnet { Add-Content $env:CAP_TEST_LOG 'core'; $global:LASTEXITCODE = 0 }
        '''
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); script = directory/'step.ps1'; log = directory/'calls.log'
            script.write_text(textwrap.dedent(stub) + unit_code())
            env = dict(os.environ, CAP_TEST_LOG=str(log), GH_TOKEN='synthetic-unit-fixture', GITHUB_TOKEN='synthetic-unit-fixture')
            for name in ('OPENGEUL_SUITE_NUMERIC_NOTICE','OPENGEUL_SUITE_UNIT_NOTICE'):
                env.pop(name, None)
            env.update(unit_environment())
            process = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                                     env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertEqual(['before','unit-wrapper','after','core'], log.read_text().splitlines())

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the actual workflow command boundary')
    def test_unit_failure_remains_primary_and_after_receipt_runs_before_core(self):
        stub = r'''
        $ErrorActionPreference = 'Stop'
        function python {
            if ($args[0] -eq '-m') {
                Add-Content $env:CAP_TEST_LOG 'unit'
                if ($env:CAP_TEST_THROW_UNIT -eq '1') { throw 'PRIMARY_UNIT_LAUNCH' }
                $global:LASTEXITCODE = [int]$env:CAP_TEST_UNIT
            } else {
                $phase = $args[[Array]::IndexOf($args, '--phase') + 1]
                Add-Content $env:CAP_TEST_LOG $phase
                if ($phase -eq 'after' -and $env:CAP_TEST_THROW_AFTER -eq '1') { throw 'AFTER_CAPTURE_FAILURE' }
                if ($phase -eq 'before') { $global:LASTEXITCODE = [int]$env:CAP_TEST_BEFORE }
                else { $global:LASTEXITCODE = [int]$env:CAP_TEST_AFTER }
            }
        }
        function dotnet {
            Add-Content $env:CAP_TEST_LOG 'core'
            $global:LASTEXITCODE = [int]$env:CAP_TEST_CORE
        }
        '''
        cases = [(0, 0, 0, 0, ''), (7, 0, 9, 0, 'Suite unit tests failed.'),
                 (0, 8, 0, 0, 'Suite unit capability receipts failed.'),
                 (0, 0, 9, 0, 'Suite unit capability receipts failed.'),
                 (0, 0, 0, 9, 'Suite shell tests failed.')]
        for unit, before, after, core, error in cases:
            with self.subTest(unit=unit, before=before, after=after, core=core), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); script = directory / 'step.ps1'; log = directory / 'calls.log'
                script.write_text(textwrap.dedent(stub) + unit_code())
                env = dict(os.environ, CAP_TEST_LOG=str(log), CAP_TEST_UNIT=str(unit), CAP_TEST_BEFORE=str(before),
                           CAP_TEST_AFTER=str(after), CAP_TEST_CORE=str(core), CAP_TEST_THROW_UNIT='0', CAP_TEST_THROW_AFTER='0')
                process = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                                         env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode == 0, not error, process.stdout + process.stderr)
                if error: self.assertIn(error, process.stderr)
                self.assertEqual(log.read_text().splitlines(), ['before', 'unit', 'after'] + ([] if unit else ['core']))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); script = directory / 'step.ps1'; log = directory / 'calls.log'
            script.write_text(textwrap.dedent(stub) + unit_code())
            env = dict(os.environ, CAP_TEST_LOG=str(log), CAP_TEST_UNIT='0', CAP_TEST_BEFORE='0', CAP_TEST_AFTER='0',
                       CAP_TEST_CORE='0', CAP_TEST_THROW_UNIT='1', CAP_TEST_THROW_AFTER='1')
            process = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                                     env=env, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('PRIMARY_UNIT_LAUNCH', process.stderr)
            self.assertNotIn('AFTER_CAPTURE_FAILURE', process.stderr)
            self.assertEqual(log.read_text().splitlines(), ['before', 'unit', 'after'])


if __name__ == '__main__':
    unittest.main()
