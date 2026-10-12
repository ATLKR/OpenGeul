"""Editor checkpoints retain failure evidence without adding or bypassing gates."""
from pathlib import Path
import importlib.util
import re
import shlex
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))
from policy import load_workflow

UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
STAGES = (('prepare', 'Prepare'), ('native-tests', 'NativeTests'), ('release', 'Release'))
EDITORS = (('windows-editor', 'x64', 'windows-2025'),
           ('windows-editor-arm64', 'arm64', 'windows-11-arm'))


def condition(step):
    value = step.get('if', 'success()').strip()
    if value.startswith('${{') and value.endswith('}}'):
        value = value[3:-2].strip()
    return re.sub(r'\s+', '', value)


class BuildProgressWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.jobs = load_workflow(ROOT / '.github/workflows/msix.yml')['jobs']

    def indexed_steps(self, name):
        steps = self.jobs[name]['steps']
        ids = [(index, step['id']) for index, step in enumerate(steps) if 'id' in step]
        self.assertEqual(len(ids), len({value for _, value in ids}), 'Step IDs must be unique')
        return steps, {step['id']: (index, step) for index, step in enumerate(steps) if 'id' in step}

    def required_step(self, indexed, step_id):
        self.assertIn(step_id, indexed, f'Missing checkpoint contract step: {step_id}')
        return indexed[step_id]

    def helper(self):
        path = ROOT / 'ci/build_progress.py'
        self.assertTrue(path.is_file(), 'The workflow must invoke its production progress wrapper')
        spec = importlib.util.spec_from_file_location('workflow_build_progress_contract', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_each_stage_finishes_with_its_checkpoint_before_the_next_stage(self):
        expected = [name for slug, _ in STAGES for name in ('editor-' + slug, 'progress-' + slug)]
        for job, _, _ in EDITORS:
            with self.subTest(job=job):
                steps, indexed = self.indexed_steps(job)
                selected = [(index, step['id']) for index, step in enumerate(steps)
                            if step.get('id', '').startswith(('editor-', 'progress-'))]
                self.assertEqual([name for _, name in selected], expected)
                for slug, _ in STAGES:
                    stage_index, _ = self.required_step(indexed, 'editor-' + slug)
                    upload_index, _ = self.required_step(indexed, 'progress-' + slug)
                    self.assertEqual(upload_index, stage_index + 1,
                                     'Publish the completed stage before starting more work')

    def test_workflow_binds_each_wrapper_invocation_to_the_stage_and_native_architecture(self):
        for job, architecture, _ in EDITORS:
            with self.subTest(job=job):
                steps, indexed = self.indexed_steps(job)
                invocations = [step for step in steps if 'ci/build_progress.py' in step.get('run', '')]
                self.assertEqual(len(invocations), 3)
                self.assertFalse(any(re.search(r'build-msix\.ps1\s+-Phase\s+Editor\b', step.get('run', ''))
                                     for step in steps), 'Do not also execute the old monolithic editor build')
                for slug, stage in STAGES:
                    _, step = self.required_step(indexed, 'editor-' + slug)
                    self.assertEqual(shlex.split(step['run']),
                                     ['python', 'ci/build_progress.py', 'run', '--stage', stage,
                                      '--architecture', architecture])

    def test_stage_failures_and_checkpoint_failures_block_later_build_and_capture_steps(self):
        for job, _, _ in EDITORS:
            with self.subTest(job=job):
                steps, indexed = self.indexed_steps(job)
                for slug, _ in STAGES:
                    _, step = self.required_step(indexed, 'editor-' + slug)
                    self.assertEqual(condition(step), 'success()')
                    self.assertEqual(str(step.get('continue-on-error', 'false')).lower(), 'false')
                release_index, _ = self.required_step(indexed, 'progress-release')
                for step in steps[release_index + 1:]:
                    self.assertEqual(condition(step), 'success()',
                                     'Component and fixture capture must require all preceding stages')
                    self.assertEqual(str(step.get('continue-on-error', 'false')).lower(), 'false')

    def test_checkpoint_uploads_keep_only_safe_stage_output_and_run_attempt_identity(self):
        for job, architecture, _ in EDITORS:
            with self.subTest(job=job):
                _, indexed = self.indexed_steps(job)
                for slug, _ in STAGES:
                    _, step = self.required_step(indexed, 'progress-' + slug)
                    self.assertEqual(step.get('uses'), UPLOAD)
                    self.assertEqual(condition(step),
                                     f"always()&&!cancelled()&&steps.editor-{slug}.outcome!='skipped'")
                    self.assertEqual(str(step.get('continue-on-error', 'false')).lower(), 'false')
                    options = step['with']
                    self.assertEqual(options['name'],
                                     f'opengeul-build-progress-editor-{architecture}-{slug}-'
                                     '${{ github.run_id }}-${{ github.run_attempt }}')
                    self.assertEqual(options['path'], f'.work/build-progress/editor-{architecture}/{slug}/')
                    self.assertEqual(str(options['retention-days']), '1')
                    self.assertEqual(options['if-no-files-found'], 'error')
                    self.assertEqual(str(options['compression-level']), '6')
                    self.assertEqual(str(options.get('overwrite', 'false')).lower(), 'false')
                    self.assertEqual(str(options.get('include-hidden-files', 'false')).lower(), 'false')

    def test_same_run_wasm_is_mandatory_before_any_editor_stage(self):
        for job, _, _ in EDITORS:
            with self.subTest(job=job):
                steps, indexed = self.indexed_steps(job)
                prepare_index, _ = self.required_step(indexed, 'editor-prepare')
                downloads = [(index, step) for index, step in enumerate(steps)
                             if 'opengeul-wasm-$env:GITHUB_RUN_ID' in step.get('run', '')]
                self.assertEqual(len(downloads), 1)
                index, step = downloads[0]
                self.assertLess(index, prepare_index)
                self.assertIn('gh run download $env:GITHUB_RUN_ID --repo $env:GITHUB_REPOSITORY', step['run'])
                self.assertIn('--dir wasm-input', step['run'])
                self.assertEqual(step['env']['GH_TOKEN'], '${{ github.token }}')
                self.assertEqual(condition(step), 'success()')
                self.assertEqual(str(step.get('continue-on-error', 'false')).lower(), 'false')

    def test_original_component_and_fixture_upload_contracts_follow_the_release_checkpoint(self):
        for job, architecture, _ in EDITORS:
            with self.subTest(job=job):
                steps, indexed = self.indexed_steps(job)
                release_index, _ = self.required_step(indexed, 'progress-release')
                suffix = '' if architecture == 'x64' else '-arm64'
                for role, path in (('editor-component', '.work/editor-component/'),
                                   ('e2e-inputs', '.work/native-inputs/')):
                    name = 'opengeul-' + role + suffix + '-${{ github.run_id }}'
                    matches = [(index, step) for index, step in enumerate(steps)
                               if step.get('with', {}).get('name') == name]
                    self.assertEqual(len(matches), 1)
                    index, step = matches[0]
                    self.assertGreater(index, release_index)
                    self.assertEqual(step['uses'], UPLOAD)
                    self.assertEqual(condition(step), 'success()')
                    self.assertEqual(step['with']['path'], path)
                    self.assertEqual(str(step['with']['include-hidden-files']).lower(), 'true')
                    self.assertEqual(str(step['with']['retention-days']), '1')
                    self.assertEqual(step['with']['if-no-files-found'], 'error')
                    self.assertEqual(str(step['with']['compression-level']), '9')

    def test_checkpoints_do_not_add_jobs_or_change_editor_and_release_dependency_contracts(self):
        self.assertEqual(set(self.jobs), {'preflight', 'wasm', 'windows-editor', 'windows-editor-arm64',
                         'windows-cli', 'windows-cli-arm64', 'build', 'build-arm64', 'native-e2e',
                         'native-e2e-arm64', 'browser-e2e', 'msix-install', 'msix-native-arm64', 'msix-install-arm64',
                         'virtual-print', 'virtual-print-arm64', 'release', 'cleanup-transports'})
        for name, _, runner in EDITORS:
            job = self.jobs[name]
            self.assertEqual(set(job['needs']), {'preflight', 'wasm'})
            self.assertEqual(job['runs-on'], runner)
            self.assertEqual(job['permissions'], {'contents': 'read', 'actions': 'read'})
            self.assertEqual(str(job['timeout-minutes']), '120')
            self.assertEqual(job['if'],
                             "github.event.repository.private == false && (needs.preflight.outputs.mode == 'full')")
        self.assertEqual(set(self.jobs['release']['needs']), {'wasm', 'build', 'build-arm64', 'native-e2e',
                         'native-e2e-arm64', 'browser-e2e', 'msix-install', 'msix-native-arm64', 'msix-install-arm64',
                         'virtual-print', 'virtual-print-arm64'})
        self.assertEqual(set(self.jobs['cleanup-transports']['needs']), set(self.jobs) - {'cleanup-transports'})

    def test_production_wrapper_builds_the_fixed_powershell_command_for_both_architectures(self):
        helper = self.helper()
        for _, architecture, _ in EDITORS:
            for _, stage in STAGES:
                with self.subTest(stage=stage, architecture=architecture):
                    self.assertEqual(helper.build_command(stage, architecture),
                                     ['pwsh', '-NoLogo', '-NoProfile', '-File', 'scripts/build-msix.ps1',
                                      '-Phase', 'Editor', '-EditorStage', stage, '-WasmDirectory', 'wasm-input',
                                      '-Architecture', architecture])

    def test_wrapper_rejects_unsupported_stage_and_architecture_before_process_creation(self):
        helper = self.helper()
        for stage, architecture in (('All', 'x64'), ('prepare', 'x64'), ('Release', 'x86'),
                                    ('Release', 'arm64-extra'), ('Prepare; exit 0', 'x64')):
            with self.subTest(stage=stage, architecture=architecture), self.assertRaises(ValueError):
                helper.build_command(stage, architecture)


if __name__ == '__main__':
    unittest.main()
