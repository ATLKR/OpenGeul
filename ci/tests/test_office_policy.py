"""Only the named Office jobs may use their reviewed runner/time envelopes."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'policy.py'
SUITE = '.github/workflows/office-suite.yml'
ENGINE = '.github/workflows/office-native-engine.yml'
PUBLIC = 'github.event.repository.private == false'


def workflow(job_name, **job):
    return {'on': {'push': {}}, 'jobs': {job_name: {
        'if': PUBLIC, 'steps': [{
            'uses': 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02',
            'with': {'path': 'out', 'retention-days': 1}}], **job}}}


def suite_workflow():
    return workflow('windows-suite', **{
        'runs-on': '${{ matrix.runner }}', 'timeout-minutes': 150,
        'strategy': {'fail-fast': False, 'matrix': {'include': [
            {'architecture': 'x64', 'runner': 'windows-2025'},
            {'architecture': 'arm64', 'runner': 'windows-11-arm'}]}}})


def engine_workflow():
    return workflow('native-firebird-and-office', **{
        'runs-on': 'windows-11-arm', 'timeout-minutes': 360})


class OfficePolicyTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('office_ci_policy', SOURCE)
        self.policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.policy)

    def test_cli_passes_the_exact_workflow_path_to_named_job_policy(self):
        for name, value in ((SUITE, suite_workflow()), (ENGINE, engine_workflow())):
            with self.subTest(workflow=name), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / name
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(value), encoding='utf-8')
                result = subprocess.run([sys.executable, str(SOURCE), '--root', folder],
                    text=True, capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_original_named_upper_bounds_are_allowed(self):
        self.assertTrue(self.policy.audit(suite_workflow(), workflow_path=SUITE))
        self.assertTrue(self.policy.audit(engine_workflow(), workflow_path=ENGINE))

    def test_missing_or_other_paths_cannot_borrow_an_office_envelope(self):
        for name, value in ((SUITE, suite_workflow()), (ENGINE, engine_workflow())):
            for other in (None, Path(name).name, name.replace('.yml', '.yaml'),
                          '.github/workflows/copied.yml', '../' + name):
                with self.subTest(workflow=name, context=other), self.assertRaises(ValueError):
                    self.policy.audit(value, workflow_path=other)

    def test_other_jobs_in_the_same_file_cannot_borrow_the_longer_timeout(self):
        for name, value in ((SUITE, suite_workflow()), (ENGINE, engine_workflow())):
            job = value['jobs'].pop(next(iter(value['jobs'])))
            value['jobs']['another-job'] = job
            with self.subTest(workflow=name), self.assertRaises(ValueError):
                self.policy.audit(value, workflow_path=name)

    def test_named_timeout_boundaries_do_not_accept_extensions_or_expressions(self):
        for name, build, limit in ((SUITE, suite_workflow, 150), (ENGINE, engine_workflow, 360)):
            for timeout in (None, 0, -1, True, 1.5, limit + 1, '${{ inputs.timeout }}'):
                value = build()
                next(iter(value['jobs'].values()))['timeout-minutes'] = timeout
                with self.subTest(workflow=name, timeout=timeout), self.assertRaises(ValueError):
                    self.policy.audit(value, workflow_path=name)

    def test_generic_jobs_keep_the_original_120_minute_limit(self):
        value = workflow('test', **{'runs-on': 'windows-11-arm', 'timeout-minutes': 120})
        self.assertTrue(self.policy.audit(value))
        value['jobs']['test']['timeout-minutes'] = 121
        for context in (None, SUITE, ENGINE):
            with self.subTest(context=context), self.assertRaises(ValueError):
                self.policy.audit(value, workflow_path=context)

    def test_suite_cannot_replace_its_fixed_runner_expression(self):
        for runner in ('windows-2025', '${{ matrix.os }}', '${{ inputs.runner }}',
                       'self-hosted', {'group': 'paid'}, ['windows-2025']):
            value = suite_workflow()
            value['jobs']['windows-suite']['runs-on'] = runner
            value['jobs']['windows-suite']['timeout-minutes'] = 120
            with self.subTest(runner=runner), self.assertRaises(ValueError):
                self.policy.audit(value, workflow_path=SUITE)

    def test_suite_matrix_cannot_add_axes_rows_or_different_architecture_runners(self):
        matrices = [None, {}, '${{ fromJSON(inputs.matrix) }}',
            {'include': '${{ inputs.include }}'},
            {'include': [{'architecture': 'x64', 'runner': 'windows-2025'}]},
            {'include': [
                {'architecture': 'x64', 'runner': 'windows-2025'},
                {'architecture': 'arm64', 'runner': 'windows-2025'}]},
            {'include': [
                {'architecture': 'x64', 'runner': 'windows-2025'},
                {'architecture': 'arm64', 'runner': 'self-hosted'}]},
            {'include': [
                {'architecture': '${{ inputs.arch }}', 'runner': 'windows-2025'},
                {'architecture': 'arm64', 'runner': 'windows-11-arm'}]}]
        original = suite_workflow()['jobs']['windows-suite']['strategy']['matrix']
        extra_axis = copy.deepcopy(original)
        extra_axis['extra'] = [1, 2]
        matrices.append(extra_axis)
        extra_row = copy.deepcopy(original)
        extra_row['include'].append({'architecture': 'x64', 'runner': 'windows-2025'})
        matrices.append(extra_row)
        extra_key = copy.deepcopy(original)
        extra_key['include'][0]['extra'] = 'unexpected'
        matrices.append(extra_key)
        for matrix in matrices:
            value = suite_workflow()
            value['jobs']['windows-suite']['strategy']['matrix'] = matrix
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                self.policy.audit(value, workflow_path=SUITE)

    def test_native_engine_cannot_change_runner_or_multiply_its_long_job(self):
        for runner in ('windows-2025', '${{ matrix.runner }}', '${{ inputs.runner }}',
                       'self-hosted', {'group': 'paid'}, ['windows-11-arm']):
            value = engine_workflow()
            value['jobs']['native-firebird-and-office']['runs-on'] = runner
            value['jobs']['native-firebird-and-office']['timeout-minutes'] = 120
            with self.subTest(runner=runner), self.assertRaises(ValueError):
                self.policy.audit(value, workflow_path=ENGINE)
        for strategy in ({'matrix': {'extra': [1, 2]}}, {'matrix': {}}, None, []):
            value = engine_workflow()
            value['jobs']['native-firebird-and-office']['strategy'] = strategy
            with self.subTest(strategy=strategy), self.assertRaises(ValueError):
                self.policy.audit(value, workflow_path=ENGINE)

    def test_office_context_never_bypasses_public_or_failure_guards(self):
        mutations = [
            {'if': None}, {'if': 'always()'}, {'if': PUBLIC + ' || true'},
            {'continue-on-error': True}, {'snapshot': 'image'},
            {'container': 'custom/image'}, {'services': {'db': {}}},
            {'uses': 'owner/repo/.github/workflows/run.yml@main'},
            {'steps': [{'run': 'exit 1', 'continue-on-error': True}]}]
        for name, build in ((SUITE, suite_workflow), (ENGINE, engine_workflow)):
            for mutation in mutations:
                value = build()
                next(iter(value['jobs'].values())).update(mutation)
                with self.subTest(workflow=name, mutation=mutation), self.assertRaises(ValueError):
                    self.policy.audit(value, workflow_path=name)

    def test_office_context_keeps_action_cache_lfs_and_one_day_retention_checks(self):
        steps = [
            {'uses': 'actions/checkout@v6'},
            {'uses': 'actions/cache@' + 'a' * 40},
            {'uses': 'actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1',
             'with': {'cache': False}},
            {'uses': 'actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444',
             'with': {'package-manager-cache': True}},
            {'uses': 'actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09',
             'with': {'lfs': True}},
            {'uses': 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02',
             'with': {'path': 'out', 'retention-days': 7}}]
        for name, build in ((SUITE, suite_workflow), (ENGINE, engine_workflow)):
            for step in steps:
                value = build()
                next(iter(value['jobs'].values()))['steps'] = [step]
                with self.subTest(workflow=name, step=step), self.assertRaises(ValueError):
                    self.policy.audit(value, workflow_path=name)

    def test_cli_does_not_trust_a_copied_workflows_display_name(self):
        value = suite_workflow()
        value['name'] = 'OpenGeul Office Suite 개발 검증'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / '.github/workflows/copied.yml'
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(value), encoding='utf-8')
            result = subprocess.run([sys.executable, str(SOURCE), '--root', folder],
                text=True, capture_output=True, timeout=10)
            self.assertNotEqual(0, result.returncode)


if __name__ == '__main__':
    unittest.main()
