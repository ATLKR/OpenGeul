"""Keep Suite builds and the controlled UI probe on one supported .NET runtime."""
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = '10.0.15'
SDK = '10.0.404'
SETUP = '0f4a354dd5547a28c70b7853dbd95d5b67886e73'


class ShellRuntimeLockTests(unittest.TestCase):
    def project(self, relative):
        return ET.fromstring((ROOT / relative).read_text())

    def test_bootstrap_installs_the_policy_yaml_pin_before_suite_discovery(self):
        import ast
        import shlex
        from suite.tests.workflow_scope import suite_workflow_sections
        pins = [line.strip() for line in (ROOT / 'ci/requirements.txt').read_text().splitlines()
                if line.strip().startswith('PyYAML==')]
        self.assertEqual(len(pins), 1)
        self.assertRegex(pins[0], r'\APyYAML==[0-9]+\.[0-9]+\.[0-9]+\Z')
        policy = ast.parse((ROOT / 'ci/policy.py').read_text())
        loader = next(node for node in policy.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'load_workflow')
        self.assertTrue(any(isinstance(node, ast.Import) and any(alias.name == 'yaml' for alias in node.names)
                            for node in ast.walk(loader)), 'The tested loader requires the declared YAML tool')
        normal = suite_workflow_sections((ROOT / '.github/workflows/office-suite.yml').read_text())[1]
        lines = [line.strip() for line in normal.splitlines()]
        installs = [index for index, line in enumerate(lines)
                    if line.startswith('python -m pip install ')
                    and shlex.split(line) == ['python', '-m', 'pip', 'install', pins[0]]]
        self.assertEqual(len(installs), 1, 'Install the existing CI YAML pin before Suite discovery')
        units = [index for index, line in enumerate(lines)
                 if line == 'python -m suite.scripts.run_unit_checks -s suite/tests -v']
        self.assertEqual(len(units), 1)
        self.assertLess(installs[0], units[0])
        self.assertEqual(lines[installs[0] + 1],
            "if ($LASTEXITCODE -ne 0) { throw 'Pinned YAML workflow tooling installation failed.' }")

    def test_shell_targets_supported_windows_runtime_without_patch_drift(self):
        project = self.project('suite/shell/OpenGeul.Office.csproj')
        self.assertEqual('net10.0-windows', project.findtext('.//TargetFramework'))
        self.assertEqual(RUNTIME, project.findtext('.//RuntimeFrameworkVersion'))
        self.assertEqual('true', project.findtext('.//UseWindowsForms'))
        self.assertEqual('true', project.findtext('.//EnableWindowsTargeting'))
        self.assertEqual('false', project.findtext('.//TargetLatestRuntimePatch'))
        self.assertEqual('PerMonitorV2', project.findtext('.//ApplicationHighDpiMode'))

    def test_core_and_its_tests_use_the_same_supported_framework(self):
        for relative in ('suite/shell/Core/OpenGeul.Office.Core.csproj',
                         'suite/shell-tests/OpenGeul.Office.Tests.csproj'):
            with self.subTest(project=relative):
                self.assertEqual('net10.0', self.project(relative).findtext('.//TargetFramework'))
                self.assertEqual('true', self.project(relative).findtext('.//TreatWarningsAsErrors'))

    def test_active_architecture_locks_match_the_published_runtime(self):
        expected = dict(name='.NET Windows Desktop', version=RUNTIME,
            sourceUrl='https://github.com/dotnet/runtime/tree/v' + RUNTIME,
            desktopSourceUrl='https://github.com/dotnet/winforms/tree/v' + RUNTIME)
        for architecture, filename in (('x64', 'runtime.lock.json'), ('arm64', 'runtime.arm64.lock.json')):
            with self.subTest(architecture=architecture):
                lock = json.loads((ROOT / 'suite/config' / filename).read_text())
                self.assertEqual(architecture, lock['architecture'])
                self.assertEqual(expected, lock['shellRuntime'])

    def test_sdk_is_exact_and_never_selects_an_installed_newer_major(self):
        path = ROOT / 'global.json'
        self.assertTrue(path.is_file(), 'The Suite SDK requires an exact global.json pin')
        self.assertEqual(dict(sdk=dict(version=SDK, rollForward='disable', allowPrerelease=False)),
                         json.loads(path.read_text()))

    def test_every_shell_build_workflow_sets_up_the_exact_native_sdk(self):
        for name, expected in (
            ('office-suite.yml', ['${{ matrix.architecture }}', 'arm64']),
            ('office-home-routes.yml', ['x64']),
            ('office-taskdialog-uia-probe.yml', ['x64'])):
            with self.subTest(workflow=name):
                spec = importlib.util.spec_from_file_location('shell_runtime_ci_policy', ROOT / 'ci/policy.py')
                policy = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(policy)
                workflow = policy.load_workflow(ROOT / '.github/workflows' / name)
                steps = [step for job in workflow['jobs'].values() for step in job['steps']
                         if step.get('uses', '').startswith('actions/setup-dotnet@')]
                self.assertEqual(len(expected), len(steps))
                self.assertEqual(SETUP, policy.ACTIONS.get('actions/setup-dotnet'))
                for step, architecture in zip(steps, expected):
                    self.assertEqual('actions/setup-dotnet@' + SETUP, step['uses'])
                    self.assertEqual({'dotnet-version': SDK, 'skip-lts-prepass': 'true',
                                      'architecture': architecture}, step['with'])


    def test_controlled_taskdialog_observes_the_same_exact_runtime(self):
        path = ROOT / 'suite/e2e/taskdialog_uia_probe.py'
        spec = importlib.util.spec_from_file_location('shell_runtime_taskdialog_probe', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project, _ = module.stub_sources()
        project = ET.fromstring(project)
        self.assertEqual('net10.0-windows', project.findtext('.//TargetFramework'))
        self.assertEqual(RUNTIME, project.findtext('.//RuntimeFrameworkVersion'))
        self.assertEqual('Disable', project.findtext('.//RollForward'))
        self.assertIn("owner['framework']!='.NET " + RUNTIME + "'", path.read_text())


if __name__ == '__main__':
    unittest.main()
