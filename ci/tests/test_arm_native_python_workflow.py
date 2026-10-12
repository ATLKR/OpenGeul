"""Reuse native Python only for stdlib compiler/package work on ARM hosts."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'ci'))
from policy import load_workflow


class NativeArmPythonWorkflowTests(unittest.TestCase):
    def setup(self, job):
        actions=[s['with'] for s in job['steps'] if s.get('uses','').startswith('actions/setup-python@')]
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0]['python-version'],'3.12')
        return actions[0]

    def test_only_stdlib_arm_compile_and_assembly_reuse_native_python(self):
        jobs=load_workflow(ROOT/'.github/workflows/msix.yml')['jobs']
        selected={name for name,job in jobs.items()
                  if any(s.get('uses','').startswith('actions/setup-python@') for s in job['steps'])
                  if self.setup(job).get('architecture')=='arm64'}
        self.assertEqual(selected,{'windows-editor-arm64','windows-cli-arm64','build-arm64'})
        for name in selected:
            self.assertEqual(jobs[name]['runs-on'],'windows-11-arm')

    def test_native_ui_mcp_print_and_sdk_controllers_keep_x64_python(self):
        jobs=load_workflow(ROOT/'.github/workflows/msix.yml')['jobs']
        for name in ('native-e2e-arm64','msix-native-arm64','msix-install-arm64','virtual-print-arm64'):
            with self.subTest(job=name):self.assertEqual(self.setup(jobs[name])['architecture'],'x64')

    def test_store_arm_controller_stays_x64(self):
        jobs=load_workflow(ROOT/'.github/workflows/store-package.yml')['jobs']
        arm=[job for job in jobs.values() if job.get('runs-on')=='windows-11-arm']
        self.assertGreater(len(arm),0)
        for job in arm:self.assertEqual(self.setup(job)['architecture'],'x64')

    def test_arm_compiler_still_requests_native_target_all_phases(self):
        jobs=load_workflow(ROOT/'.github/workflows/msix.yml')['jobs']
        editor='\n'.join(s.get('run','') for s in jobs['windows-editor-arm64']['steps'])
        for phase in ('Prepare','NativeTests','Release'):
            self.assertIn(f'--stage {phase} --architecture arm64',editor)
        cli='\n'.join(s.get('run','') for s in jobs['windows-cli-arm64']['steps'])
        package='\n'.join(s.get('run','') for s in jobs['build-arm64']['steps'])
        self.assertIn('-Phase Cli -Architecture arm64 -WasmDirectory wasm-input',cli)
        self.assertIn('-Phase Package -Architecture arm64',package)


if __name__=='__main__':unittest.main()
