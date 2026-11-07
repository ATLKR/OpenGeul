"""Fixed independent native source workflows; portable policy, not Windows proof."""
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]


class NativeSourceWorkflowTests(unittest.TestCase):
    def test_owner_then_isolated_units_then_native_preflight_and_downloads(self):
        steps=self.workflow('x64')['jobs']['native-firebird-and-office-x64']['steps']
        owner=next(i for i,step in enumerate(steps) if 'Assert-NativeEngineEnvironment x64' in step.get('run',''))
        units=next(i for i,step in enumerate(steps) if 'Invoke-NativeEngineUnitGate' in step.get('run',''))
        build=next(i for i,step in enumerate(steps) if '-Phase Full -Architecture x64' in step.get('run',''))
        self.assertLess(owner,units);self.assertLess(units,build)
        self.assertNotIn('if',steps[units]);self.assertNotIn('continue-on-error',steps[units])
        self.assertIn('$env:OPENGEUL_ENGINE_BUILD_DEADLINE_UTC',steps[units]['run'])
        self.assertIn('(Get-Command python -ErrorAction Stop).Source',steps[units]['run'])
        self.assertIn("if (-not $?) { throw",steps[units]['run'])
        source=(ROOT/'suite/scripts/build-native-engine.ps1').read_text()
        lifecycle=source[source.index('function Invoke-NativeEngineBuild('):]
        self.assertLess(lifecycle.index('Invoke-NativeX64Preflight $work $evidence'),lifecycle.index("$receipt.stage='authenticated-downloads'"))

    def workflow(self,architecture):
        suffix='-x64' if architecture=='x64' else ''
        return yaml.safe_load((ROOT/f'.github/workflows/office-native-engine{suffix}.yml').read_text())

    def test_fixed_x64_workflow_branch_runner_job_and_artifact(self):
        value=self.workflow('x64');job=value['jobs']['native-firebird-and-office-x64']
        self.assertEqual({'contents':'read'},value['permissions'])
        self.assertEqual(['work/opengeul-office-native-engine-x64'],value['on']['push']['branches'])
        self.assertEqual('windows-2025',job['runs-on']);self.assertEqual(360,job['timeout-minutes'])
        self.assertIn('AddMinutes(330)',job['steps'][0]['run'])
        setup=next(step for step in job['steps'] if step.get('uses','').startswith('actions/setup-python@'))
        self.assertEqual({'python-version':'3.12','architecture':'x64'},setup['with'])
        commands='\n'.join(step.get('run','') for step in job['steps'])
        self.assertIn('Assert-NativeEngineEnvironment x64',commands)
        self.assertIn('-Architecture x64',commands);self.assertNotIn('-MutexSymbols',commands)
        self.assertNotIn('-CalcDispatchDiagnostic',commands)
        artifact=next(step for step in job['steps'] if step.get('with',{}).get('name','').startswith('opengeul-native-x64-engine-${{'))
        self.assertEqual(['.work/native-engine-evidence/OpenGeul-Office-engine-x64.zip',
                         '.work/native-engine-evidence/source-build-receipt.json'],artifact['with']['path'].splitlines())
        self.assertNotIn('always()',artifact.get('if',''))

    def test_architecture_runs_do_not_cancel_or_trigger_each_other(self):
        arm,x64=self.workflow('arm64'),self.workflow('x64')
        self.assertNotIn('workflow_dispatch',x64['on'])
        self.assertNotIn('workflow_run',x64['on'])
        self.assertNotIn('concurrency',x64)
        self.assertFalse(set(arm['on']['push']['branches']) & set(x64['on']['push']['branches']))
        self.assertNotIn('matrix',x64['jobs']['native-firebird-and-office-x64'].get('strategy',{}))

    def test_shared_dependencies_are_in_validation_inventory(self):
        paths=self.workflow('x64')['on']['push']['paths']
        for path in ['suite/scripts/build-native-engine.ps1','suite/engine-build/**','suite/tests/**',
                     'suite/crt.py','suite/pe_imports.py','suite/payload.py','suite/e2e/**','suite/worker/**','suite/config/runtime.lock.json']:
            self.assertIn(path,paths)

    def test_whole_run_success_is_not_replaced_by_matrix_row_success(self):
        value=self.workflow('x64')
        self.assertEqual(['native-firebird-and-office-x64'],list(value['jobs']))
        job=value['jobs']['native-firebird-and-office-x64']
        self.assertNotIn('continue-on-error',job)
        for step in job['steps']:
            self.assertNotIn('continue-on-error',step)
            if 'uses' in step:
                self.assertRegex(step['uses'],r'@[0-9a-f]{40}$')
        build=next(step['run'] for step in job['steps'] if '-Architecture x64' in step.get('run',''))
        self.assertIn("if (-not $?) { throw",build)


if __name__=='__main__':unittest.main()
