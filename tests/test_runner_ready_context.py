"""Real public-event/ref/actor/job context gates for the hosted ARM helper."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'ATLKR/OpenGeul'
USER = {'login': 'ATLKR', 'id': 65988341, 'type': 'User'}
BOT = {'login': 'github-actions[bot]', 'id': 41898282, 'type': 'Bot'}
PUBLIC = {'full_name': REPOSITORY, 'private': False, 'id': 1405493151}


def module():
    spec = importlib.util.spec_from_file_location('runner_ready_context', ROOT / 'e2e/runner-ready.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'event.json'
        self.value = module()

    def context(self, *, event='push', ref='refs/heads/main', actor=USER,
                job='native-e2e-arm64', workflow='msix.yml', attempt='1', payload=None):
        body = {'repository': copy.deepcopy(PUBLIC), 'sender': copy.deepcopy(actor)}
        if event == 'push': body.update(ref=ref, deleted=False)
        if event == 'workflow_dispatch': body['ref'] = ref.removeprefix('refs/heads/')
        if event == 'schedule': body['schedule'] = '0 18 * * 0'
        if payload is not None: body.update(copy.deepcopy(payload))
        self.path.write_text(json.dumps(body), encoding='utf-8')
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
               'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_EVENT_NAME': event,
               'GITHUB_REF': ref, 'GITHUB_ACTOR': actor['login'], 'GITHUB_ACTOR_ID': str(actor['id']),
               'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '38217759325',
               'GITHUB_RUN_ATTEMPT': attempt, 'GITHUB_JOB': job,
               'GITHUB_EVENT_PATH': str(self.path),
               'GITHUB_WORKFLOW_REF': f'{REPOSITORY}/.github/workflows/{workflow}@{ref}'}
        return env

    def pr(self, *, fork=True, actor=None):
        actor = actor or {'login': 'public-contributor', 'id': 91827364, 'type': 'User'}
        head = {'full_name': 'public-contributor/OpenGeul', 'private': False, 'id': 91827365} if fork else copy.deepcopy(PUBLIC)
        payload = {'number': 17, 'pull_request': {'number': 17,
                   'head': {'repo': head, 'ref': 'work/change', 'sha': 'b' * 40},
                   'base': {'repo': copy.deepcopy(PUBLIC), 'ref': 'main', 'sha': 'c' * 40},
                   'merge_commit_sha': 'a' * 40}}
        return self.context(event='pull_request', ref='refs/pull/17/merge', actor=actor, payload=payload)

    def reject(self, env):
        with self.assertRaises(ValueError): self.value.binding(env)

    def test_only_literal_public_owned_repository_payload_can_run(self):
        for private in (True, 'false', 0, None):
            with self.subTest(private=private):
                env = self.context(payload={'repository': {**PUBLIC, 'private': private}})
                self.reject(env)
        self.reject(self.context(payload={'repository': {**PUBLIC, 'full_name': 'other/OpenGeul'}}))

    def test_missing_oversized_or_duplicate_event_cannot_run(self):
        env = self.context(); self.path.unlink(); self.reject(env)
        env = self.context(); self.path.write_bytes(b' ' * (256 * 1024 + 1)); self.reject(env)
        env = self.context(); self.path.write_text('{"repository":{"private":true,"private":false,"full_name":"ATLKR/OpenGeul"}}'); self.reject(env)
        env = self.context(); self.path.write_text('{"repository":{"private":false,"full_name":"ATLKR/OpenGeul"},"repository":{"private":false,"full_name":"ATLKR/OpenGeul"}}'); self.reject(env)

    def test_source_push_supports_main_canonical_and_version_matched_development_tags(self):
        self.assertEqual(json.loads((ROOT / 'config/product.json').read_text())['version'], '1.1.3')
        for ref in ('refs/heads/main', 'refs/tags/v1.1.3', 'refs/tags/v1.1.3-dev.72.1'):
            for job in ('native-e2e-arm64', 'virtual-print-arm64', 'msix-install-arm64'):
                with self.subTest(ref=ref, job=job): self.assertEqual(self.value.binding(self.context(ref=ref, job=job))['ref'], ref)

    def test_source_current_attempt_is_preserved_without_release_authorization(self):
        for attempt in ('1', '2', '53'):
            self.assertEqual(self.value.binding(self.context(attempt=attempt))['runAttempt'], attempt)
        for attempt in ('0', '01', '-1', '2.0', '1' * 21): self.reject(self.context(attempt=attempt))

    def test_wrong_tags_refs_and_version_env_override_are_rejected(self):
        for ref in ('refs/heads/feature', 'refs/tags/v1.1.2', 'refs/tags/v1.1.4-dev.72.1',
                    'refs/tags/v1.1.3-dev.0.1', 'refs/tags/v1.1.3-dev.72.0', 'refs/tags/v1.1.3-extra'):
            env = self.context(ref=ref); env['PRODUCT_VERSION'] = '1.1.4'; self.reject(env)
        self.reject(self.context(payload={'ref': 'refs/heads/other'}))
        self.reject(self.context(payload={'deleted': True}))

    def test_source_manual_and_schedule_support_main_only(self):
        for event in ('workflow_dispatch', 'schedule'):
            self.assertEqual(self.value.binding(self.context(event=event, actor=BOT, attempt='2'))['runAttempt'], '2')
            self.reject(self.context(event=event, ref='refs/tags/v1.1.3'))
        self.reject(self.context(event='repository_dispatch'))

    def test_source_public_users_and_bots_require_exact_sender_env_identity(self):
        for actor in (USER, BOT, {'login': 'public-contributor', 'id': 91827364, 'type': 'User'},
                      {'login': 'dependabot[bot]', 'id': 49699333, 'type': 'Bot'}):
            self.assertEqual(self.value.binding(self.context(actor=actor))['actor'], actor['login'])
        for change in ({'login': 'other-user'}, {'id': 1234}, {'id': True}, {'type': 'Organization'},
                       {'login': 'bad login'}, {'login': 'github-actions[bot]', 'id': 999, 'type': 'Bot'}):
            env = self.context(); body = json.loads(self.path.read_text()); body['sender'].update(change)
            self.path.write_text(json.dumps(body)); self.reject(env)
        env = self.context(actor={**BOT, 'id': 999}); self.reject(env)
        env = self.context(actor={**USER, 'id': 999}); self.reject(env)
        env = self.context(); env['GITHUB_ACTOR_ID'] = '065988341'; self.reject(env)

    def test_schedule_missing_sender_has_only_fixed_env_actor_fallback(self):
        for actor in (USER, BOT):
            env = self.context(event='schedule', actor=actor); body=json.loads(self.path.read_text()); body.pop('sender')
            self.path.write_text(json.dumps(body)); self.assertEqual(self.value.binding(env)['actor'], actor['login'])
        env = self.context(event='schedule', actor={'login': 'public-contributor', 'id': 91827364, 'type': 'User'})
        body=json.loads(self.path.read_text()); body.pop('sender'); self.path.write_text(json.dumps(body)); self.reject(env)
        env = self.context(); body=json.loads(self.path.read_text()); body.pop('sender'); self.path.write_text(json.dumps(body)); self.reject(env)
        self.reject(self.context(event='schedule', payload={'sender': None}))

    def test_binding_retains_actual_event_digest_and_canonical_config_version(self):
        env = self.context(); result = self.value.binding(env)
        self.assertEqual(result['eventSha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual((result['actorId'], result['actorType'], result['context']), (USER['id'], 'User', 'source'))
        config = Path(self.tmp.name) / 'config'; config.mkdir()
        (config / 'product.json').write_text(json.dumps({'repository': REPOSITORY, 'version': '1.2.3'}))
        self.value.ROOT = Path(self.tmp.name)
        env = self.context(ref='refs/tags/v1.2.3-dev.72.1'); env['PRODUCT_VERSION'] = '9.9.9'
        self.assertEqual(self.value.binding(env)['productVersion'], '1.2.3')
        self.reject(self.context(ref='refs/tags/v1.1.3'))

    def test_source_sha_run_and_manual_payload_bindings_are_required(self):
        for key, value in (('GITHUB_SHA', '0' * 40), ('GITHUB_SHA', 'A' * 40),
                           ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ID', '01'), ('GITHUB_RUN_ID', '1' * 21)):
            env = self.context(); env[key] = value; self.reject(env)
        self.reject(self.context(event='workflow_dispatch', payload={'ref': 'foreign-branch'}))
        for raw in (b'null', b'[]', b'{"repository": NaN}', b'\xff', b'{'):
            env = self.context(); self.path.write_bytes(raw); self.reject(env)

    def test_public_pr_same_repo_and_fork_contributors_are_supported(self):
        for fork in (False, True): self.assertEqual(self.value.binding(self.pr(fork=fork))['ref'], 'refs/pull/17/merge')
        env=self.pr(); body=json.loads(self.path.read_text()); body['pull_request']['merge_commit_sha']=None
        self.path.write_text(json.dumps(body)); self.value.binding(env)

    def test_pr_number_base_head_and_sha_mismatches_are_rejected(self):
        for change in ('number', 'pr-number', 'base-owner', 'base-private', 'head-private', 'head-sha', 'base-sha', 'merge-sha', 'head-shape', 'base-id'):
            env=self.pr(); body=json.loads(self.path.read_text()); pr=body['pull_request']
            if change=='number': body['number']=18
            elif change=='pr-number': pr['number']=18
            elif change=='base-owner': pr['base']['repo']['full_name']='other/OpenGeul'
            elif change=='base-private': pr['base']['repo']['private']=True
            elif change=='head-private': pr['head']['repo']['private']=True
            elif change=='head-sha': pr['head']['sha']='0'*40
            elif change=='base-sha': pr['base']['sha']='bad'
            elif change=='merge-sha': pr['merge_commit_sha']='d'*40
            elif change=='head-shape': pr['head']=None
            elif change=='base-id': pr['base']['repo']['id']=1234
            self.path.write_text(json.dumps(body)); self.reject(env)
        for ref in ('refs/pull/17/head','refs/pull/18/merge','refs/heads/main'):
            env=self.pr(); env['GITHUB_REF']=ref; env['GITHUB_WORKFLOW_REF']=f'{REPOSITORY}/.github/workflows/msix.yml@{ref}'; self.reject(env)

    def test_source_job_workflow_and_host_drift_are_rejected(self):
        for key,val in [('GITHUB_JOB','native-e2e'),('GITHUB_JOB','unknown-job'),
                        ('GITHUB_WORKFLOW_REF',f'{REPOSITORY}/.github/workflows/msix.yml@refs/heads/feature'),
                        ('GITHUB_WORKFLOW_REF',f'{REPOSITORY}/.github/workflows/store-package.yml@refs/heads/main'),
                        ('RUNNER_ENVIRONMENT','self-hosted'),('GITHUB_ACTIONS','false'),('GITHUB_REPOSITORY','other/repo')]:
            env=self.context(); env[key]=val; self.reject(env)

    def test_store_only_fixed_actors_manual_main_arm_store_wack(self):
        for actor in (USER,BOT):
            env=self.context(event='workflow_dispatch',actor=actor,job='store-wack',workflow='store-package.yml',attempt='2'); env['ARCHITECTURE']='arm64'
            self.assertEqual(self.value.binding(env)['runAttempt'],'2')
        for change in ('actor','event','ref','arch','job','workflow'):
            env=self.context(event='workflow_dispatch',job='store-wack',workflow='store-package.yml'); env['ARCHITECTURE']='arm64'
            if change=='actor': env=self.context(event='workflow_dispatch',actor={'login':'public-contributor','id':91827364,'type':'User'},job='store-wack',workflow='store-package.yml');env['ARCHITECTURE']='arm64'
            elif change=='event': env['GITHUB_EVENT_NAME']='pull_request'
            elif change=='ref': env['GITHUB_REF']='refs/tags/v1.1.3'
            elif change=='arch': env['ARCHITECTURE']='x64'
            elif change=='job': env['GITHUB_JOB']='store-package'
            elif change=='workflow': env['GITHUB_WORKFLOW_REF']=f'{REPOSITORY}/.github/workflows/msix.yml@refs/heads/main'
            self.reject(env)

    def test_diagnostic_stays_fixed_actor_attempt_workflow_job_and_public_event(self):
        branch='refs/heads/diagnostic/arm-runner-ready71'
        env=self.context(event='workflow_dispatch',ref=branch,job='observe',workflow='store-package.yml')
        self.assertEqual(self.value.binding(env)['runAttempt'],'1')
        for key,val in [('GITHUB_ACTOR_ID','999'),('GITHUB_RUN_ATTEMPT','2'),('GITHUB_JOB','store-wack'),('GITHUB_WORKFLOW_REF',f'{REPOSITORY}/.github/workflows/msix.yml@{branch}')]:
            env=self.context(event='workflow_dispatch',ref=branch,job='observe',workflow='store-package.yml');env[key]=val;self.reject(env)
        env=self.context(event='workflow_dispatch',ref=branch,actor=BOT,job='observe',workflow='store-package.yml');self.reject(env)
        env=self.context(event='workflow_dispatch',ref=branch,job='observe',workflow='store-package.yml',payload={'repository':{**PUBLIC,'private':True}});self.reject(env)

    def test_print_diagnostic_is_one_exact_owned_context(self):
        branch='refs/heads/diagnostic/owned-print-preview-75'
        env=self.context(event='workflow_dispatch',ref=branch,job='print-diagnostic',workflow='store-package.yml')
        self.assertEqual(self.value.binding(env)['context'],'print-focus-diagnostic')
        for key,val in [('GITHUB_RUN_ATTEMPT','2'),('GITHUB_JOB','observe'),
                        ('GITHUB_REF',branch+'-other'),('GITHUB_ACTOR_ID','999'),
                        ('GITHUB_WORKFLOW_REF',f'{REPOSITORY}/.github/workflows/msix.yml@{branch}')]:
            env=self.context(event='workflow_dispatch',ref=branch,job='print-diagnostic',workflow='store-package.yml')
            env[key]=val;self.reject(env)
        env=self.context(event='workflow_dispatch',ref=branch,actor=BOT,job='print-diagnostic',workflow='store-package.yml');self.reject(env)
        env=self.context(event='workflow_dispatch',ref=branch,job='print-diagnostic',workflow='store-package.yml',payload={'repository':{**PUBLIC,'private':True}});self.reject(env)


if __name__=='__main__':unittest.main()
