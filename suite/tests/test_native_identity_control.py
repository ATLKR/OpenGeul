"""Ordinary finite diagnostic guards, never Windows/native/engine qualification."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'suite/diagnostics/native-runtime-identity'
SPEC = importlib.util.spec_from_file_location('native_identity_control', DATA / 'control.py')
CONTROL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROL)


class NativeIdentityControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owned = tempfile.TemporaryDirectory(prefix='native30-identity-')
        cls.root = Path(cls.owned.name)
        cls.generated = cls.root / 'generated'
        cls.generated.mkdir()
        cls.no_git = cls.root / 'no-git'
        cls.no_git.mkdir()
        for ancestor in (cls.no_git, *cls.no_git.parents):
            if (ancestor / '.git').exists():
                raise ValueError('Portable ordinary fixture must also lie outside all Git parents')
        cls.parent = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        fragments = {row['path']: (DATA / row['path']).read_bytes()
                     for member in CONTROL.source()['members'] for row in member['fragments']}
        # This local ordinary guard omits only the absent Cygwin tool census.
        # Authentic Perl/Make/Git fragments are identical; no Windows claim.
        CONTROL.render_fragments(fragments, cls.generated, str(cls.generated), str(ROOT), str(cls.no_git), cygwin=False)
        result = subprocess.run(['/bin/bash', str(cls.generated / 'generate-control.sh')], capture_output=True, timeout=20)
        if result.returncode:
            raise ValueError(result.stderr.decode(errors='replace'))
        cls.cases = cls.root / 'cases'
        CONTROL.make_cases(cls.generated, cls.cases, cls.parent, require_cygwin=False)

    @classmethod
    def tearDownClass(cls):
        cls.owned.cleanup()

    def test_source_fragments_and_exact_consumer_dependency_closure_are_pinned(self):
        manifest = CONTROL.source()
        self.assertEqual(302435508, manifest['archive']['bytes'])
        self.assertEqual({'suite/prepare.py', 'suite/crt.py'}, {r['path'] for r in manifest['consumer']['files']})
        for member in manifest['members']:
            for fragment in member['fragments']:
                CONTROL.check((DATA / fragment['path']).read_bytes(), fragment, fragment['path'])
        for row in manifest['consumer']['files']:
            CONTROL.check((DATA / 'consumer-snapshot' / row['path']).read_bytes(), row, row['path'])
        CONTROL.check((ROOT / manifest['producer']['path']).read_bytes(), manifest['producer'], 'unchanged reviewed producer')
        self.assertEqual('2b325a6db10e3c5d9da1296315c2351bcbf25e5b', manifest['consumer']['commit'])

    def test_authentic_subroutines_and_make_definitions_remain_complete(self):
        for filename, name in (('replace-setup-variables.pl', 'replace_setup_variables'),
                               ('sorting-profile.pl', 'sorting_profile'), ('windows-lineends.pl', 'include_windows_lineends')):
            original = (DATA / filename).read_bytes()
            self.assertTrue(original.startswith(('sub ' + name).encode()))
            self.assertTrue(original.endswith(b'}\n'))
            self.assertIn(original, (self.generated / 'installed-control.pl').read_bytes())
        self.assertIn((DATA / 'developer-setup.mk').read_bytes(), (self.generated / 'developer-control.mk').read_bytes())
        self.assertIn((DATA / 'developer-version.mk').read_bytes(), (self.generated / 'developer-control.mk').read_bytes())
        items = (DATA / 'installed-profile-items.scp').read_text()
        self.assertEqual(2, len(re.findall(r'^End$', items, re.M)))

    def test_authentic_no_git_and_real_parent_generation_remain_distinct(self):
        CONTROL.verify_generation(self.generated, self.parent, require_cygwin=False)
        self.assertEqual(b'[Bootstrap]\r\nbuildid=680(Build:1)\r\n', (self.generated / 'installed-no-git/setup.ini').read_bytes())
        self.assertEqual(CONTROL.FALLBACK, CONTROL.read_id(self.generated / 'installed-no-git/version.ini', 'Version'))
        self.assertEqual(self.parent, CONTROL.read_id(self.generated / 'installed-parent/version.ini', 'Version'))
        self.assertEqual(self.parent, CONTROL.read_id(self.generated / 'developer/instsetoo_native/setup/version.ini', 'Version'))
        self.assertNotEqual(self.parent, CONTROL.CORE)

    def test_no_git_probes_retain_real_failure_without_nested_trace_claim(self):
        manifest = CONTROL.load(self.generated / 'generation-commands.json')
        for command in manifest['commands']:
            if command.get('separateProbe'):
                self.assertFalse(command['interceptsNestedGit'])
        for label in ('rev-parse', 'installed-git', 'developer-git'):
            name = 'no-git-' + label
            self.assertNotEqual(0, CONTROL.load(self.generated / (name + '.status.json'))['exitCode'])
            self.assertEqual(b'', (self.generated / (name + '.stdout.raw')).read_bytes())
            self.assertTrue((self.generated / (name + '.stderr.raw')).read_bytes())
        perl = json.loads((self.generated / 'perl-no-git.stdout.raw').read_bytes())
        self.assertIs(type(perl['immediateChildStatusWord']), int)
        self.assertGreater(perl['immediateChildStatusWord'], 0)

    def test_generated_configuration_comes_from_authentic_version(self):
        config = CONTROL.load(self.generated / 'configuration.json')
        self.assertEqual(dict(LIBO_VERSION_MAJOR='26', LIBO_VERSION_MINOR='8', LIBO_VERSION_MICRO='1', LIBO_VERSION_PATCH='1', LIBO_VERSION_SUFFIX=''), config)
        inputs = CONTROL.load(self.generated / 'installer-input.json')
        self.assertIn('not configure output', inputs['boundary'])

    def test_finite_cases_use_isolated_inputs_and_explicit_fixture_boundaries(self):
        self.assertEqual(24, len(CONTROL.CASES))
        self.assertEqual(set(CONTROL.CASES), {p.name for p in self.cases.iterdir() if p.is_dir()})
        self.assertEqual(5, len(CONTROL.ACCEPTED))
        for name in CONTROL.CASES:
            case = CONTROL.load(self.cases / name / 'case.json')
            self.assertEqual(name in CONTROL.ACCEPTED, case['expectedAccepted'])
            self.assertEqual(self.parent, case['sourceCommit'])
            self.assertTrue(case['fixtureProvenance']['controlFixture'])
            self.assertFalse(case['fixtureProvenance']['historicalOriginalIniBytes'])
            for flag, value in CONTROL.FLAGS.items():
                self.assertIs(case[flag], value)
            for filename, record in case['inputFiles'].items():
                raw = (self.cases / name / 'runtime/program' / filename).read_bytes()
                self.assertEqual(record['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(raw, (self.cases / name / 'input' / filename).read_bytes())

    def test_stage_mutations_isolate_descriptor_and_authenticated_map_predicates(self):
        for name in ('authentic-no-git', 'stage-row-hash', 'stage-missing-row', 'stage-duplicate-row', 'stage-wrong-member'):
            root = self.cases / name
            case = CONTROL.load(root / 'case.json')
            self.assertEqual(CONTROL.descriptor(root / 'evidence/installed-runtime-stage.json'), case['installedRuntimeStage']['receipt'])
        for name, key in (('stage-reference-size', 'bytes'), ('stage-reference-hash', 'sha256')):
            root = self.cases / name
            case = CONTROL.load(root / 'case.json')
            self.assertNotEqual(CONTROL.descriptor(root / 'evidence/installed-runtime-stage.json')[key], case['installedRuntimeStage']['receipt'][key])

    def test_wrong_source_cases_change_real_pin_without_archive_substitution(self):
        original = CONTROL.pin()
        for name, key in (('wrong-source-hash', 'sha256'), ('wrong-source-size', 'size'), ('wrong-source-core', 'coreCommit'), ('wrong-source-version', 'version'), ('wrong-source-url', 'url')):
            actual = CONTROL.load(self.cases / name / 'case.json')['sourcePin']
            self.assertEqual({key}, {field for field in original if original[field] != actual[field]})
        controller = (ROOT / 'suite/scripts/probe-native-identity-control.ps1').read_text()
        self.assertNotIn('function Confirm-FileIdentity', controller)
        self.assertIn('Set-RuntimeBuildIdentity $spec.runtimeRoot $Archive', controller)
        self.assertNotIn('source archive fixture', controller)

    def test_source_extraction_refuses_unlinked_and_incomplete_inputs(self):
        bad = self.root / 'tiny.tar.xz'
        bad.write_bytes(b'tiny is not authenticated source')
        out = self.root / 'bad-out'
        out.mkdir()
        with self.assertRaisesRegex(ValueError, 'full source archive size mismatch'):
            CONTROL.authenticate_extract(bad, self.no_git, out)
        linked = self.root / 'linked-source'
        linked.symlink_to(bad)
        with self.assertRaisesRegex(ValueError, 'Linked control path'):
            CONTROL.authenticate_extract(linked, self.no_git, out)

    def test_rejects_unsafe_upstream_unquoted_source_paths(self):
        with self.assertRaisesRegex(ValueError, 'shell-safe POSIX paths'):
            CONTROL.render_fragments({}, self.generated, str(self.generated), '/unsafe space', str(self.no_git))

    def test_inherited_git_redirections_reject_before_creating_output(self):
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'git_dir', 'Git_Config_Count'):
            with self.subTest(name=name), patch.dict(os.environ, {name: '/control-fixture'}):
                with self.assertRaisesRegex(ValueError, 'Inherited Git environment forbidden'):
                    CONTROL.render(None)

    def test_exact_consumer_imports_in_fresh_isolated_process(self):
        command = "import importlib.util,json;from pathlib import Path;s=importlib.util.spec_from_file_location('control'," + repr(str(DATA / 'control.py')) + ");m=importlib.util.module_from_spec(s);s.loader.exec_module(m);v,i=m.import_consumer();print(json.dumps(dict(api=v.__name__,imports=i)))"
        result = subprocess.run([sys.executable, '-I', '-B', '-c', command], capture_output=True, text=True, check=True)
        record = json.loads(result.stdout)
        self.assertEqual('_source_build_identity', record['api'])
        self.assertEqual({str(DATA / 'consumer-snapshot/suite/prepare.py'), str(DATA / 'consumer-snapshot/suite/crt.py')}, {r['path'] for r in record['imports']})

    def test_workflow_and_controller_bind_one_original_deadline_and_source(self):
        workflow = (ROOT / '.github/workflows/office-native-identity-control.yml').read_text()
        controller = (ROOT / 'suite/scripts/probe-native-identity-control.ps1').read_text()
        self.assertIn('runs-on: windows-11-arm', workflow)
        self.assertIn('timeout-minutes: 20', workflow)
        self.assertEqual(1, workflow.count('AddMinutes(15)'))
        self.assertLess(workflow.index('AddMinutes(15)'), workflow.index('actions/checkout@'))
        self.assertIn('if: always()', workflow)
        self.assertIn('architecture: arm64', workflow)
        self.assertEqual(3, len(re.findall(r'uses: [\w/-]+@[0-9a-f]{40}', workflow)))
        self.assertIn('inputs.source_sha == github.sha', workflow)
        self.assertIn('branches: [work/opengeul-office-native30-identity-control]', workflow)
        self.assertIn('github.event_name == \'push\' || inputs.source_sha == github.sha', workflow)
        self.assertIn("IDENTITY_EXPECTED_SOURCE_COMMIT: ${{ github.event_name == 'push' && github.sha || inputs.source_sha }}", workflow)
        self.assertIn('suite/diagnostics/native-runtime-identity/**', workflow)
        self.assertIn('-ExpectedSourceTree $env:IDENTITY_EXPECTED_SOURCE_TREE', workflow)
        self.assertIn('explicitTreeInputRequired=($EventName -ceq \'workflow_dispatch\')', controller)
        self.assertIn("@('tree','HEAD^{tree}',$receipt.source.sourceTree)", controller)
        self.assertEqual(1, controller.count('New-NativeBuildBudget $DeadlineUtc 15'))
        for guard in ('Get-NativeBuildHost', 'Assert-NoInheritedGitRedirection', 'New-IdentityNoGitSource',
                      'Assert-RuntimeBuildIdentity', '-NativeLinks', 'creationUtcTicks -isnot [long]',
                      "export PATH=/usr/local/bin:/usr/bin:/bin:$PATH", 'final-source-clean'):
            self.assertIn(guard, controller + (DATA / 'control.py').read_text())
        self.assertNotIn('Invoke-NativeEngineBuild ', controller)
        self.assertNotIn('function Invoke-LoggedCommand', controller)


class IdentityBudgetRegressionTests(unittest.TestCase):
    def test_actual_budget_deadline_uses_exact_json_string_in_both_time_zones(self):
        # Exact original bytes from run39416400170/attempt1, not a rebuilt receipt.
        budget_raw = (
            b'{\r\n'
            b'  "schemaVersion": 1,\r\n'
            b'  "origin": "first-user-step",\r\n'
            b'  "startedUtc": "2026-10-20T11:38:41.8155116Z",\r\n'
            b'  "deadlineUtc": "2026-10-20T11:53:41.8155116Z",\r\n'
            b'  "controlMinutes": 15,\r\n'
            b'  "jobTimeoutMinutes": 20,\r\n'
            b'  "nominalReserveMinutes": 5,\r\n'
            b'  "runnerSetupIncluded": false\r\n'
            b'}\r\n')
        self.assertEqual('2c48ec3f6572560ddff748022595084ea7e0c9b9d74496713e9ab9d188a45d46', hashlib.sha256(budget_raw).hexdigest())
        deadline = json.loads(budget_raw)['deadlineUtc']
        controller = (ROOT / 'suite/scripts/probe-native-identity-control.ps1').read_text()
        # Execute the actual controller read/check, stopping before budget creation,
        # host probing or any other work. The historical deadline is never renewed.
        check = re.search(r'(?ms)^        \$budget(?:Raw)?=.*?(?=^        \$script:NativeEngineBuildBudget=)', controller)
        self.assertIsNotNone(check, 'Actual controller budget check must be extractable')
        block = check.group()
        pwsh = shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'
        self.assertTrue(Path(pwsh).is_file(), 'Existing local PowerShell required for budget regression')
        cases = (
            ('actual-budget', budget_raw, deadline, True),
            ('different-deadline-tick', budget_raw, deadline.replace('8155116', '8155117'), False),
            ('equivalent-offset-not-exact-string', budget_raw.replace(deadline.encode(), deadline[:-1].encode()+b'+00:00'), deadline, False),
            ('nonstring-deadline', budget_raw.replace(('"'+deadline+'"').encode(), b'0'), deadline, False),
            ('wrong-origin', budget_raw.replace(b'first-user-step', b'wrong-origin'), deadline, False),
            ('wrong-control-minutes', budget_raw.replace(b'"controlMinutes": 15', b'"controlMinutes": 16'), deadline, False),
            ('wrong-job-minutes', budget_raw.replace(b'"jobTimeoutMinutes": 20', b'"jobTimeoutMinutes": 21'), deadline, False),
            ('wrong-reserve-minutes', budget_raw.replace(b'"nominalReserveMinutes": 5', b'"nominalReserveMinutes": 4'), deadline, False))
        with tempfile.TemporaryDirectory(prefix='native30-budget-') as owned:
            budget_path = Path(owned) / 'job-budget.json'
            script = Path(owned) / 'actual-controller-budget-check.ps1'
            script.write_text(
                'param([string]$BudgetPath,[string]$DeadlineUtc)\n'
                "$ErrorActionPreference='Stop'\n"
                '$env:OPENGEUL_IDENTITY_CONTROL_BUDGET_RECEIPT=$BudgetPath\n'
                '[TimeZoneInfo]::ClearCachedData()\n'
                '$observed=Get-Content -LiteralPath $BudgetPath -Raw|ConvertFrom-Json\n'
                'Write-Output ("parsedDeadlineType="+$observed.deadlineUtc.GetType().FullName)\n'
                'Write-Output ("localZone="+[TimeZoneInfo]::Local.Id)\n'
                + block + "Write-Output 'Original budget accepted.'\n")
            for zone in ('UTC', 'America/Los_Angeles'):
                for name, raw, expected, accepted in cases:
                    with self.subTest(zone=zone, case=name):
                        budget_path.write_bytes(raw)
                        result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script), str(budget_path), expected],
                                                capture_output=True, text=True, timeout=15, env=dict(os.environ, TZ=zone))
                        print('budget-regression', zone, name, 'exit='+str(result.returncode), 'checkSha256='+hashlib.sha256(block.encode()).hexdigest(), result.stdout.strip())
                        self.assertEqual(accepted, result.returncode == 0, result.stderr)
                        if accepted:
                            self.assertIn('Original budget accepted.', result.stdout)


if __name__ == '__main__':
    unittest.main()
