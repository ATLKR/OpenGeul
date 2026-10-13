"""명시한 초안 채택도 기존 Store 검증과 소유자 실행 범위 안에 둔다."""
import ast
import json
from pathlib import Path
import re
import sys
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy import audit, load_workflow

ROOT = Path(__file__).resolve().parents[2]
NEEDS = ['package', 'store-native-arm64', 'store-wack-x64', 'store-wack', 'qualify']


class StoreAdoptionWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / '.github/workflows/store-package.yml'
        self.workflow = load_workflow(path)
        self.typed = yaml.safe_load(path.read_text(encoding='utf-8'))
        self.submit = self.workflow['jobs']['submit']
        self.writer = next(step for step in self.submit['steps']
                           if 'scripts/store_submit.py' in step.get('run', ''))

    def allowed(self, **changes):
        values = {
            'github.event.repository.private': False,
            'github.event_name': 'workflow_dispatch',
            'github.repository': 'ATLKR/OpenGeul',
            'github.ref': 'refs/heads/main',
            'github.actor': 'ATLKR',
            'github.triggering_actor': 'ATLKR',
            'inputs.submit_to_store': True,
            'inputs.adopt_pending_submission': False,
            'inputs.recover_pending_submission': False,
            **{("needs." + job + ".result" if '-' not in job
                else "needs['" + job + "'].result"): 'success' for job in NEEDS},
        }
        values.update(changes)
        expression = self.submit['if']
        for name in sorted(values, key=len, reverse=True):
            expression = expression.replace(name, repr(values[name]))
        expression = expression.replace('&&', ' and ').replace('||', ' or ')
        expression = re.sub(r'!(?!=)', ' not ', expression)
        expression = re.sub(r'\bfalse\b', 'False', expression)
        expression = re.sub(r'\btrue\b', 'True', expression)
        tree = ast.parse(expression.strip(), mode='eval')
        permitted = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp,
                     ast.Not, ast.Compare, ast.Eq, ast.Constant)
        self.assertTrue(all(isinstance(node, permitted) for node in ast.walk(tree)))
        return eval(compile(tree, '<workflow-condition>', 'eval'), {'__builtins__': {}})

    def test_adoption_inputs_are_typed_and_disabled_by_default(self):
        inputs = self.typed['on']['workflow_dispatch']['inputs']
        flag = inputs['adopt_pending_submission']
        self.assertEqual(flag['type'], 'boolean')
        self.assertIs(flag['required'], False)
        self.assertIs(flag['default'], False)
        digest = inputs['adoption_draft_sha256']
        self.assertEqual(digest['type'], 'string')
        self.assertIs(digest['required'], False)
        self.assertEqual(digest['default'], '')

    def test_exact_inputs_reach_only_writer_without_shell_interpolation(self):
        expected = {
            'STORE_ADOPT_PENDING': '${{ inputs.adopt_pending_submission }}',
            'STORE_ADOPTION_DRAFT_SHA256': '${{ inputs.adoption_draft_sha256 }}',
        }
        for name, value in expected.items():
            self.assertEqual(self.writer['env'][name], value)
        self.assertEqual(self.writer['run'],
                         'python scripts/store_submit.py --release-tag "$RELEASE_TAG" --package-directory store-output')
        for job in self.workflow['jobs'].values():
            for step in job['steps']:
                if step is not self.writer:
                    self.assertTrue(set(expected).isdisjoint(step.get('env', {})))
                self.assertNotIn('${{ inputs.adopt_pending_submission }}', step.get('run', ''))
                self.assertNotIn('${{ inputs.adoption_draft_sha256 }}', step.get('run', ''))

    def test_adoption_requires_owner_actor_and_owner_trigger(self):
        for actor in ('ATLKR', 'github-actions[bot]', 'other'):
            for trigger in ('ATLKR', 'github-actions[bot]', 'other'):
                with self.subTest(actor=actor, trigger=trigger):
                    self.assertEqual(self.allowed(**{
                        'inputs.adopt_pending_submission': True,
                        'github.actor': actor,
                        'github.triggering_actor': trigger,
                    }), actor == trigger == 'ATLKR')
        self.assertTrue(self.allowed(**{
            'github.actor': 'github-actions[bot]',
            'github.triggering_actor': 'ATLKR',
        }))

    def test_both_modes_keep_public_manual_main_submission_and_all_five_gates(self):
        self.assertEqual(self.submit['needs'], NEEDS)
        failures = {
            'github.event.repository.private': True,
            'github.event_name': 'push',
            'github.repository': 'other/OpenGeul',
            'github.ref': 'refs/tags/v1.1.3',
            'inputs.submit_to_store': False,
        }
        failures.update({("needs." + job + ".result" if '-' not in job
                          else "needs['" + job + "'].result"): 'failure' for job in NEEDS})
        for adoption in (False, True):
            self.assertTrue(self.allowed(**{'inputs.adopt_pending_submission': adoption}))
            for name, value in failures.items():
                with self.subTest(adoption=adoption, condition=name):
                    self.assertFalse(self.allowed(**{'inputs.adopt_pending_submission': adoption,
                                                     name: value}))

    def test_adoption_adds_no_jobs_or_public_runner_policy_bypass(self):
        self.assertEqual(set(self.workflow['jobs']),
                         set(NEEDS) | {'submit', 'verify-api'})
        for name, job in self.workflow['jobs'].items():
            if name != 'submit':
                self.assertNotIn('adopt_pending_submission', json.dumps(job))
                self.assertNotIn('adoption_draft_sha256', json.dumps(job))
        audit(self.workflow)


if __name__ == '__main__':
    unittest.main()
