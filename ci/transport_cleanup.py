"""Remove only consumed same-run transports, never tests, Releases or other runs.

Failing runs keep their one-day inputs/evidence. Successful PRs keep the candidate
package. A package is removable only AFTER its eligible release job succeeded.
There is no billing API access or promise of account-wide zero spending.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from policy import require_public, select_mode

REPO = 'ATLKR/OpenGeul'
GATES = ('preflight', 'wasm', 'browser-e2e', 'build', 'native-e2e', 'msix-install', 'virtual-print', 'release')
TRANSPORT = ('opengeul-wasm', 'opengeul-browser-inputs', 'opengeul-e2e-inputs', 'opengeul-windows-x64')
LIMITS = dict(zip(TRANSPORT, (32, 64, 16, 96)))
SHA = re.compile(r'[0-9a-f]{40}\Z')


def context(env, event):
    require_public(event)
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or env.get('GITHUB_REPOSITORY') != REPO or event['repository'].get('full_name') != REPO
            or env.get('GITHUB_ACTOR') == 'dependabot[bot]' or env.get('GITHUB_RUN_ATTEMPT') != '1'):
        raise ValueError('Cleanup is limited to first-attempt, owned, public hosted runs')
    event_name = env['GITHUB_EVENT_NAME']
    mode = select_mode(event_name, event.get('inputs') or {})
    if env.get('CI_MODE') != mode: raise ValueError('Preflight mode differs from event policy')
    sha = env.get('GITHUB_SHA', '')
    if event_name == 'pull_request':
        head = event.get('pull_request', {}).get('head', {})
        if head.get('repo', {}).get('full_name') != REPO: raise ValueError('No fork cleanup authority')
        sha = head.get('sha', '')
    run_id = env.get('GITHUB_RUN_ID', '')
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run_id) or not SHA.fullmatch(sha):
        raise ValueError('Invalid immutable run identity')
    return {'run_id': int(run_id), 'sha': sha, 'event': event_name,
            'ref': env['GITHUB_REF'], 'mode': mode}


def allowed_names(ctx, needs):
    if set(needs) != set(GATES): raise ValueError('Consumer gate set is incomplete or changed')
    states = {name: value.get('result') for name, value in needs.items()}
    mode = ctx['mode']
    if mode == 'checks': return set()
    if mode not in ('engine', 'full'): raise ValueError('Unreviewed cleanup mode')
    expected = dict.fromkeys(GATES, 'success')
    publishing = (mode == 'full' and ctx['event'] in ('push', 'workflow_dispatch')
                  and (ctx['ref'] == 'refs/heads/main' or ctx['ref'].startswith('refs/tags/v')))
    if not publishing: expected['release'] = 'skipped'
    if mode == 'engine':
        for name in ('build', 'native-e2e', 'msix-install', 'virtual-print'): expected[name] = 'skipped'
    if states != expected: return set()  # Keep failure inputs for diagnosis; never call DELETE.
    prefixes = set(TRANSPORT[:3]) if mode == 'full' else {TRANSPORT[1]}
    if publishing: prefixes.add(TRANSPORT[3])
    return {f'{name}-{ctx["run_id"]}' for name in prefixes}


def validate_run(ctx, run):
    if (type(run.get('id')) is not int or run['id'] != ctx['run_id']
            or run.get('run_attempt') != 1 or run.get('head_sha') != ctx['sha']
            or run.get('event') != ctx['event'] or run.get('path') != '.github/workflows/msix.yml'):
        raise ValueError('API run identity differs from the authorized current run')
    for field in ('repository', 'head_repository'):
        repo = run.get(field, {})
        if repo.get('full_name') != REPO or repo.get('private') is not False:
            raise ValueError('Run does not belong to the owned public repository')


def validate_artifact(ctx, artifact):
    owner = artifact.get('workflow_run', {})
    if owner.get('id') != ctx['run_id'] or owner.get('head_sha') != ctx['sha']:
        raise ValueError('Transport belongs to a different source or run')
    prefix = artifact['name'].rsplit('-', 1)[0]
    size = artifact.get('size_in_bytes')
    if (prefix not in LIMITS or type(artifact.get('id')) is not int or artifact['id'] <= 0
            or artifact.get('expired') is not False or type(size) is not int
            or not 0 <= size <= LIMITS[prefix] * 1024 * 1024 + 1024 * 1024):
        raise ValueError('Invalid transport identity, expiry or bounded size')


def plan(ctx, needs, run, listing):
    names = allowed_names(ctx, needs)
    if not names: return []
    validate_run(ctx, run)
    artifacts = listing.get('artifacts')
    if (not isinstance(artifacts, list) or len(artifacts) > 100
            or type(listing.get('total_count')) is not int or listing['total_count'] != len(artifacts)):
        raise ValueError('Incomplete or oversized artifact listing; no partial cleanup')
    selected = []; seen_names = set(); seen_ids = set()
    for artifact in artifacts:
        if artifact.get('name') not in names: continue
        validate_artifact(ctx, artifact)
        if artifact['name'] in seen_names or artifact['id'] in seen_ids:
            raise ValueError('Ambiguous duplicate artifact identity')
        seen_names.add(artifact['name']); seen_ids.add(artifact['id']); selected.append(artifact)
    if seen_names != names: raise ValueError('Expected consumed transports missing; retain all inputs')
    return sorted(selected, key=lambda a: a['id'])


def execute(ctx, needs, api):
    if not allowed_names(ctx, needs):
        return {'deletedBytes': 0, 'deleted': [], 'reason': 'Required consumers did not all succeed, or no transport stage'}
    root = f'repos/{REPO}/actions'
    run = api('GET', f'{root}/runs/{ctx["run_id"]}')
    listing = api('GET', f'{root}/runs/{ctx["run_id"]}/artifacts?per_page=100')
    selected = plan(ctx, needs, run, listing)
    # Validate the entire selected batch again BEFORE deleting its first member.
    for artifact in selected:
        current = api('GET', f'{root}/artifacts/{artifact["id"]}')
        validate_artifact(ctx, current)
        for key in ('id', 'name', 'size_in_bytes', 'digest'):
            if current.get(key) != artifact.get(key): raise ValueError('Artifact changed before cleanup')
    result = {'deletedBytes': 0, 'deleted': [], 'reason': 'All consumers finished; evidence and unpublished candidates retained'}
    for artifact in selected:
        api('DELETE', f'{root}/artifacts/{artifact["id"]}')
        result['deleted'].append({'id': artifact['id'], 'name': artifact['name']})
        result['deletedBytes'] += artifact['size_in_bytes']
        print('Removed consumed transport:', artifact['name'], artifact['size_in_bytes'], 'bytes', flush=True)
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def github_api(token):
    opener = urllib.request.build_opener(NoRedirect)
    def request(method, path):
        if method not in ('GET', 'DELETE') or not path.startswith(f'repos/{REPO}/actions/'):
            raise ValueError('Unexpected cleanup API endpoint')
        req = urllib.request.Request('https://api.github.com/' + path, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'OpenGeul-same-run-cleanup'})
        try:
            with opener.open(req, timeout=30) as response:
                if method == 'DELETE':
                    if response.status != 204: raise ValueError('Artifact deletion not confirmed')
                    return None
                data = response.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024: raise ValueError('API response exceeds inspection bound')
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            # No token, headers or remote response body are logged. No deletion retry.
            raise RuntimeError(f'Artifact cleanup API failed with HTTP {exc.code}') from None
    return request


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    ctx = context(os.environ, event)
    result = execute(ctx, json.loads(os.environ['CI_NEEDS']), github_api(os.environ['GH_TOKEN']))
    print(json.dumps(result, indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write('## Temporary CI transport cleanup\n\n' + result['reason'] + '.\n\n'
                + f'Removed {len(result["deleted"])} same-run artifacts ({result["deletedBytes"]:,} bytes). '
                + 'No test evidence, other runs or published Releases were deleted.\n')

if __name__ == '__main__': main()
