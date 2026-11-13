"""The paired diagnostic adds evidence without changing any normal gate."""
from pathlib import Path
import ast
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))
from policy import audit, load_workflow

SCOPE = ("github.repository == 'ATLKR/OpenGeul' && github.event.repository.private == false"
         " && github.event_name == 'pull_request' && github.event.pull_request.draft == true"
         " && github.event.pull_request.head.repo.full_name == 'ATLKR/OpenGeul'"
         " && github.event.pull_request.head.ref == 'work/opengeul-office-arm64'"
         " && matrix.os == 'windows-2025'")
ATTEMPT = ("always() && !cancelled() && " + SCOPE +
           " && steps.print-inputs.outcome == 'success'"
           " && (steps.normal-print.outcome == 'success' || steps.normal-print.outcome == 'failure')")


class PairedPrintWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / '.github/workflows/msix.yml'
        self.workflow = load_workflow(self.path)
        self.job = self.workflow['jobs']['virtual-print']
        self.steps = self.job['steps']
        self.byid = {s['id']: s for s in self.steps if 'id' in s}

    def test_exactly_one_diagnostic_on_the_existing_matrix(self):
        paired = [(j, s) for j, job in self.workflow['jobs'].items() for s in job.get('steps', [])
                  if 'e2e/paired_print_run.py' in s.get('run', '')]
        self.assertEqual(len(paired), 1)
        self.assertEqual(paired[0][0], 'virtual-print')
        self.assertEqual(self.job['strategy']['matrix'], {'os': ['windows-2022', 'windows-2025']})
        self.assertEqual(self.job['runs-on'], '${{ matrix.os }}')
        self.assertEqual(self.job['timeout-minutes'], '30')

    def test_owned_exact_branch_draft_2025_and_completed_normal_attempt_are_required(self):
        self.assertEqual(self.byid['paired-print']['if'], ATTEMPT)
        for rejected, replacement in (("draft == true", "draft == false"),
                ("'work/opengeul-office-arm64'", "'another-branch'"),
                ("'windows-2025'", "'windows-2022'")):
            self.assertNotEqual(self.byid['paired-print']['if'], ATTEMPT.replace(rejected, replacement))

    def test_normal_print_command_and_implicit_success_condition_remain(self):
        normal = self.byid['normal-print']
        self.assertNotIn('if', normal)
        self.assertNotIn('continue-on-error', normal)
        self.assertEqual(normal['run'], 'python -u e2e/virtual_print.py --exe runtime/OpenGeul.exe --inputs inputs/e2e-fixtures --fixtures print-fixtures --out print-evidence')
        self.assertNotIn('if', self.byid['print-inputs'])
        self.assertLess(self.steps.index(normal), self.steps.index(self.byid['paired-print']))

    def test_same_once_generated_fixtures_and_same_run_current_package_are_used(self):
        run = self.byid['paired-print']['run']
        for term in ('--run-paired-print', '--acquire-legacy', '--package package', '--wasm wasm-input',
                     '--inputs inputs/e2e-fixtures', '--fixtures print-fixtures',
                     '--harness-source $env:GITHUB_SHA', '--run-id $env:GITHUB_RUN_ID',
                     '--run-attempt $env:GITHUB_RUN_ATTEMPT', '--current-provenance-sha256 $provenanceSha'):
            self.assertIn(term, run)
        self.assertNotIn(' generate ', run)
        self.assertNotIn('gh run', run)
        self.assertNotIn('latest', run)

    def test_failure_is_not_suppressed_and_verifier_always_runs_after_attempt(self):
        for name in ('paired-print', 'paired-print-admit'):
            self.assertNotIn('continue-on-error', self.byid[name])
        condition = self.byid['paired-print-admit']['if']
        self.assertEqual(condition, 'always() && !cancelled() && ' + SCOPE +
            " && (steps.paired-print.outcome == 'success' || steps.paired-print.outcome == 'failure')")
        run = self.byid['paired-print-admit']['run']
        for term in ('python ci/paired_print_evidence.py', '--expected-source $env:GITHUB_SHA',
                     '--expected-run $env:GITHUB_RUN_ID', '--expected-attempt $env:GITHUB_RUN_ATTEMPT'):
            self.assertIn(term, run)

    def test_upload_requires_independent_admission_and_only_the_separate_allowlist(self):
        step = self.byid['paired-print-evidence']
        self.assertEqual(step['if'], 'always() && !cancelled() && ' + SCOPE +
                         " && steps.paired-print-admit.outcome == 'success'")
        self.assertEqual(step['with']['path'], 'paired-print-evidence/')
        self.assertEqual(step['with']['retention-days'], '1')
        self.assertEqual(step['with']['if-no-files-found'], 'error')
        self.assertTrue(step['uses'].endswith('@ea165f8d65b6e75b540449e92b4886f43607fa02'))

    def test_existing_success_only_collector_and_release_job_are_not_reinterpreted(self):
        normal = self.byid['synthetic-pdfs']
        self.assertEqual(normal['if'], "success() && github.repository == 'ATLKR/OpenGeul' && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')")
        self.assertEqual(self.byid['synthetic-pdfs-evidence']['with']['path'], 'synthetic-pdf-evidence/')
        self.assertNotIn('paired-print', self.workflow['jobs']['release']['needs'])
        self.assertNotIn('paired', str(self.workflow['on']))

    def test_existing_public_runner_policy_and_finite_workflow_envelopes(self):
        self.assertTrue(audit(self.workflow, workflow_path='.github/workflows/msix.yml'))
        self.assertLessEqual(self.path.stat().st_size, 128 * 1024)
        runs = [s.get('run', '') for job in self.workflow['jobs'].values() for s in job.get('steps', [])]
        conditions = [s.get('if', '') for job in self.workflow['jobs'].values() for s in job.get('steps', [])]
        self.assertLessEqual(max(map(len, runs)), 21000)
        self.assertLessEqual(max(map(len, conditions)), 4096)

    def test_actual_condition_truth_table_rejects_other_branch_runner_fork_and_bad_stages(self):
        context = {'github.repository': 'ATLKR/OpenGeul', 'github.event.repository.private': False,
            'github.event_name': 'pull_request', 'github.event.pull_request.draft': True,
            'github.event.pull_request.head.repo.full_name': 'ATLKR/OpenGeul',
            'github.event.pull_request.head.ref': 'work/opengeul-office-arm64',
            'matrix.os': 'windows-2025', 'steps.print-inputs.outcome': 'success',
            'steps.normal-print.outcome': 'failure'}
        def permits(values, cancelled=False):
            source = self.byid['paired-print']['if'].replace('always()', 'True').replace('!cancelled()', str(not cancelled))
            for key in sorted(values, key=len, reverse=True): source = source.replace(key, repr(values[key]))
            source = source.replace('&&', ' and ').replace('||', ' or ')
            source = re.sub(r'\bfalse\b', 'False', source)
            source = re.sub(r'\btrue\b', 'True', source)
            def read(node):
                if isinstance(node, ast.Expression): return read(node.body)
                if isinstance(node, ast.Constant) and type(node.value) in (bool, str): return node.value
                if isinstance(node, ast.BoolOp):
                    return all(read(n) for n in node.values) if isinstance(node.op, ast.And) else any(read(n) for n in node.values)
                if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1 and isinstance(node.ops[0], ast.Eq):
                    return read(node.left) == read(node.comparators[0])
                raise AssertionError('unreviewed synthetic expression grammar')
            return read(ast.parse(source, mode='eval'))
        self.assertTrue(permits(context))
        self.assertTrue(permits({**context, 'steps.normal-print.outcome': 'success'}))
        for key, value in (('github.repository', 'someone/OpenGeul'), ('github.event.repository.private', True),
                ('github.event_name', 'push'), ('github.event_name', 'workflow_dispatch'),
                ('github.event.pull_request.draft', False), ('github.event.pull_request.head.repo.full_name', 'fork/OpenGeul'),
                ('github.event.pull_request.head.ref', 'work/opengeul-office-arm64-extra'),
                ('github.event.pull_request.head.ref', 'main'), ('matrix.os', 'windows-2022'),
                ('matrix.os', 'windows-11-arm'), ('steps.print-inputs.outcome', 'failure'),
                ('steps.normal-print.outcome', 'skipped'), ('steps.normal-print.outcome', 'cancelled')):
            with self.subTest(field=key, value=value): self.assertFalse(permits({**context, key: value}))
        self.assertFalse(permits(context, cancelled=True))


if __name__ == '__main__': unittest.main()
