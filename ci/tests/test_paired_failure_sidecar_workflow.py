"""The numeric failure upload preserves the original print/release workflow."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ci'))
from policy import load_workflow
from test_paired_print_workflow import SCOPE

BASELINE_WORKFLOW_SHA256 = '319c7b2044f501184a515441237773cfb0bb1bda2997c40077c63cbd2b8525a2'
FAILURE = 'always() && !cancelled() && ' + SCOPE + " && steps.paired-print.outcome == 'failure'"


class FailureSidecarWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow(ROOT / '.github/workflows/msix.yml')
        self.steps = self.workflow['jobs']['virtual-print']['steps']
        self.byid = {s['id']: s for s in self.steps if 'id' in s}

    def test_optin_occurs_only_on_existing_exact_paired_attempt(self):
        runs = [s.get('run', '') for job in self.workflow['jobs'].values() for s in job.get('steps', [])]
        self.assertEqual(sum(r.count('--failure-numeric-sidecar') for r in runs), 1)
        self.assertIn('--failure-numeric-sidecar', self.byid['paired-print']['run'])
        self.assertNotIn('--failure-numeric-sidecar', self.byid['normal-print']['run'])

    def test_validation_uses_independent_ci_source_run_attempt_and_fixed_file(self):
        step = self.byid.get('paired-failure-admit')
        self.assertIsNotNone(step, 'failure-only independent validation is absent')
        self.assertEqual(step['if'], FAILURE)
        self.assertEqual(step['run'], 'python e2e/paired_print_failure_sidecar.py --expected-source $env:GITHUB_SHA --expected-run $env:GITHUB_RUN_ID --expected-attempt $env:GITHUB_RUN_ATTEMPT')
        self.assertNotIn('continue-on-error', step)

    def test_upload_is_one_numeric_file_after_its_own_validation(self):
        step = self.byid.get('paired-failure-evidence')
        self.assertIsNotNone(step, 'bounded failure-only upload is absent')
        self.assertEqual(step['if'], FAILURE + " && steps.paired-failure-admit.outcome == 'success'")
        self.assertEqual(step['uses'], 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02')
        self.assertEqual(step['with']['path'], 'paired-print-failure.numeric.json')
        self.assertEqual(step['with']['retention-days'], '1')
        self.assertEqual(step['with']['if-no-files-found'], 'error')
        self.assertNotIn('continue-on-error', step)

    def test_all_original_workflow_semantics_are_preserved(self):
        original = copy.deepcopy(self.workflow)
        original['jobs']['virtual-print']['steps'] = [s for s in original['jobs']['virtual-print']['steps']
            if s.get('id') not in ('paired-failure-admit', 'paired-failure-evidence')]
        for step in original['jobs']['virtual-print']['steps']:
            if step.get('id') == 'paired-print':
                step['run'] = step['run'].replace(' --failure-numeric-sidecar', '')
        actual = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, BASELINE_WORKFLOW_SHA256)

    def test_failure_scope_rejects_other_event_fork_branch_runner_and_cancel(self):
        step = self.byid.get('paired-failure-evidence')
        self.assertIsNotNone(step)
        expression = step['if']
        values = {'github.repository': 'ATLKR/OpenGeul', 'github.event.repository.private': False,
            'github.event_name': 'pull_request', 'github.event.pull_request.draft': True,
            'github.event.pull_request.head.repo.full_name': 'ATLKR/OpenGeul',
            'github.event.pull_request.head.ref': 'work/opengeul-office-arm64',
            'matrix.os': 'windows-2025', 'steps.paired-print.outcome': 'failure',
            'steps.paired-failure-admit.outcome': 'success'}
        def permits(context, cancelled=False):
            source = expression.replace('always()', 'True').replace('!cancelled()', str(not cancelled))
            for key in sorted(context, key=len, reverse=True): source = source.replace(key, repr(context[key]))
            source = re.sub(r'\bfalse\b', 'False', source.replace('&&', ' and '))
            source = re.sub(r'\btrue\b', 'True', source)
            def read(node):
                if isinstance(node, ast.Expression): return read(node.body)
                if isinstance(node, ast.Constant) and type(node.value) in (bool, str): return node.value
                if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And): return all(read(n) for n in node.values)
                if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1 and isinstance(node.ops[0], ast.Eq): return read(node.left) == read(node.comparators[0])
                raise AssertionError('Unsupported synthetic expression grammar')
            return read(ast.parse(source, mode='eval'))
        self.assertTrue(permits(values))
        for key, value in [('github.repository', 'other/OpenGeul'), ('github.event.repository.private', True),
                ('github.event_name', 'push'), ('github.event_name', 'workflow_dispatch'),
                ('github.event.pull_request.draft', False), ('github.event.pull_request.head.repo.full_name', 'fork/OpenGeul'),
                ('github.event.pull_request.head.ref', 'main'), ('matrix.os', 'windows-2022'), ('matrix.os', 'windows-11-arm'),
                ('steps.paired-print.outcome', 'success'), ('steps.paired-print.outcome', 'skipped'),
                ('steps.paired-failure-admit.outcome', 'failure')]:
            with self.subTest(field=key): self.assertFalse(permits({**values, key: value}))
        self.assertFalse(permits(values, cancelled=True))


if __name__ == '__main__': unittest.main()
