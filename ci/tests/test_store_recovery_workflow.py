"""409 초안 복구도 소유자의 수동 실행과 현재 다섯 Store gate를 요구한다."""
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


class StoreRecoveryWorkflowTests(unittest.TestCase):
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

    def test_recovery_is_typed_default_off_and_reuses_existing_fingerprint(self):
        inputs = self.typed['on']['workflow_dispatch']['inputs']
        flag = inputs['recover_pending_submission']
        self.assertEqual(flag['type'], 'boolean')
        self.assertIs(flag['required'], False)
        self.assertIs(flag['default'], False)
        self.assertEqual(set(inputs), {'release_tag', 'verify_store_api', 'submit_to_store',
                                     'adopt_pending_submission', 'recover_pending_submission',
                                     'adoption_draft_sha256'})
        self.assertEqual(inputs['adoption_draft_sha256']['type'], 'string')
        self.assertEqual(inputs['adoption_draft_sha256']['default'], '')

    def test_recovery_input_reaches_only_existing_writer_environment(self):
        self.assertEqual(self.writer['env']['STORE_RECOVER_PENDING'],
                         '${{ inputs.recover_pending_submission }}')
        self.assertEqual(self.writer['env']['STORE_ADOPTION_DRAFT_SHA256'],
                         '${{ inputs.adoption_draft_sha256 }}')
        self.assertEqual(self.writer['run'],
                         'python scripts/store_submit.py --release-tag "$RELEASE_TAG" --package-directory store-output')
        for job in self.workflow['jobs'].values():
            self.assertNotIn('STORE_RECOVER_PENDING', job.get('env', {}))
            for step in job['steps']:
                if step is not self.writer:
                    self.assertNotIn('STORE_RECOVER_PENDING', step.get('env', {}))
                self.assertNotIn('${{ inputs.recover_pending_submission }}', step.get('run', ''))

    def test_recovery_requires_owner_actor_and_owner_trigger(self):
        for actor in ('ATLKR', 'github-actions[bot]', 'other'):
            for trigger in ('ATLKR', 'github-actions[bot]', 'other'):
                with self.subTest(actor=actor, trigger=trigger):
                    self.assertEqual(self.allowed(**{
                        'inputs.recover_pending_submission': True,
                        'github.actor': actor, 'github.triggering_actor': trigger,
                    }), actor == trigger == 'ATLKR')

    def test_flags_are_mutually_exclusive_and_default_bot_path_is_preserved(self):
        for adoption, recovery in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(adoption=adoption, recovery=recovery):
                self.assertEqual(self.allowed(**{'inputs.adopt_pending_submission': adoption,
                    'inputs.recover_pending_submission': recovery}), not (adoption and recovery))
        for actor, trigger in (('github-actions[bot]', 'github-actions[bot]'),
                               ('github-actions[bot]', 'ATLKR')):
            self.assertTrue(self.allowed(**{'github.actor': actor, 'github.triggering_actor': trigger}))

    def test_every_mode_keeps_public_manual_main_submission_and_five_successes(self):
        self.assertEqual(self.submit['needs'], NEEDS)
        failures = {
            'github.event.repository.private': (True,),
            'github.event_name': ('push', 'pull_request', 'schedule'),
            'github.repository': ('other/OpenGeul',),
            'github.ref': ('refs/tags/v1.1.3', 'refs/heads/other'),
            'inputs.submit_to_store': (False,),
            **{("needs." + job + ".result" if '-' not in job
                else "needs['" + job + "'].result"): ('failure', 'skipped', 'cancelled', None)
               for job in NEEDS},
        }
        for adoption, recovery in ((False, False), (True, False), (False, True)):
            flags = {'inputs.adopt_pending_submission': adoption,
                     'inputs.recover_pending_submission': recovery}
            self.assertTrue(self.allowed(**flags))
            for name, values in failures.items():
                for value in values:
                    with self.subTest(adoption=adoption, recovery=recovery, condition=name, value=value):
                        self.assertFalse(self.allowed(**dict(flags, **{name: value})))

    def test_recovery_adds_no_jobs_or_gate_bypass(self):
        self.assertEqual(set(self.workflow['jobs']), set(NEEDS) | {'submit', 'verify-api'})
        for name, job in self.workflow['jobs'].items():
            if name != 'submit':
                self.assertNotIn('recover_pending_submission', json.dumps(job))
                self.assertNotIn('STORE_RECOVER_PENDING', json.dumps(job))
        audit(self.workflow)


if __name__ == '__main__':
    unittest.main()
