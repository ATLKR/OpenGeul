"""Fixed original-byte upload to one existing draft. No publish/delete/retries."""
import hashlib, io, json, os, stat, subprocess, sys, urllib.error, urllib.parse, urllib.request, zipfile
from pathlib import Path

ROOT = 'repos/ATLKR/OpenGeul'
BASE = Path(__file__).resolve().parents[1]
CONTRACT = BASE / 'probe/archive-upload64-contract.json'
if hashlib.sha256(CONTRACT.read_bytes()).hexdigest() != '30600a443d7f7f0509362dcb38d72a7cbd5a833b48cf896a28e21e29206f0417':
    raise ValueError('Fixed transfer contract differs')
C = json.loads(CONTRACT.read_text())
UPLOAD = 'https://uploads.github.com/' + ROOT + '/releases/409905491/assets?name='
REF = ROOT + '/git/ref/tags/store-package-1.1.2-dev.64.1'

def require(value):
    if not value: raise ValueError('Fixed archive transfer guard rejected evidence')

def digest(data): return hashlib.sha256(data).hexdigest()

def context(env, event):
    expected = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
        'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_ACTOR': 'ATLKR',
        'GITHUB_TRIGGERING_ACTOR': 'ATLKR', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_REF': 'refs/heads/diagnostic/archive-upload64'}
    require(all(env.get(k) == v for k, v in expected.items()))
    require(event.get('repository', {}).get('full_name') == 'ATLKR/OpenGeul'
        and event['repository'].get('private') is False)
    inputs = event.get('inputs', {})
    require(inputs.get('release_tag') == C['sourceTag']
        and inputs.get('submit_to_store') in (False, 'false')
        and inputs.get('verify_store_api') in (False, 'false'))

def listing(api, path, key=None):
    rows = []; total = None
    for page in range(1, 11):
        result = api('GET', ROOT + '/' + path + f'?per_page=100&page={page}')
        batch = result[key] if key else result
        require(isinstance(batch, list) and len(batch) <= 100)
        if key:
            require(type(result.get('total_count')) is int)
            if total is None: total = result['total_count']
            require(total == result['total_count'])
        rows.extend(batch)
        if len(batch) < 100:
            require(total is None or total == len(rows))
            require(len({r['id'] for r in rows}) == len(rows))
            return rows
    raise ValueError('Incomplete bounded API listing')

def source_assets(api):
    release = api('GET', ROOT + '/releases/409897256')
    require(release.get('id') == 409897256 and release.get('tag_name') == C['sourceTag']
        and release.get('draft') is False and release.get('prerelease') is True)
    rows = listing(api, 'releases/409897256/assets')
    stable = [{k: r[k] for k in ('id', 'name', 'size', 'state', 'digest')} for r in rows]
    fingerprint = digest(json.dumps(sorted(stable, key=lambda r: r['name']),
        sort_keys=True, separators=(',', ':')).encode())
    require(len(rows) == 6 and fingerprint == C['sourceAssetSnapshotSha256'])

def run_jobs(api, run_id, path, event, names):
    run = api('GET', ROOT + f'/actions/runs/{run_id}')
    require(run.get('id') == run_id and run.get('run_attempt') == 1
        and run.get('head_sha') == C['sourceCommit'] and run.get('head_branch') == 'main'
        and run.get('path') == path and run.get('event') == event
        and run.get('status') == 'completed' and run.get('conclusion') == 'success'
        and run.get('repository', {}).get('full_name') == 'ATLKR/OpenGeul'
        and run['repository'].get('private') is False)
    rows = listing(api, f'actions/runs/{run_id}/attempts/1/jobs', 'jobs')
    for name in names:
        found = [j for j in rows if j.get('name') == name]; require(len(found) == 1)
        j = found[0]
        require(j.get('run_id') == run_id and j.get('head_sha') == C['sourceCommit']
            and j.get('run_attempt', 1) == 1 and j.get('status') == 'completed'
            and j.get('conclusion') == 'success')
    return run, rows

def archive_state(api):
    release = api('GET', ROOT + '/releases/409905491')
    require(release.get('id') == 409905491 and release['id'] != 409897256
        and release.get('tag_name') == C['archiveTag'] and release.get('draft') is True
        and release.get('prerelease') is True and release.get('target_commitish') == C['sourceCommit'])
    ref = api('GET', REF)
    if ref is not None: require(ref.get('object') == {'type': 'commit', 'sha': C['sourceCommit'],
        'url': 'https://api.github.com/' + ROOT + '/git/commits/' + C['sourceCommit']})
    rows = listing(api, 'releases/409905491/assets')
    require(len(rows) <= 7 and len({r['name'] for r in rows}) == len(rows))
    for row in rows: asset(row, row['name'])
    return rows

def asset(row, name):
    require(name in C['assets'] and row.get('name') == name and type(row.get('id')) is int
        and row['id'] > 0 and row.get('state') == 'uploaded'
        and row.get('size') == C['assets'][name]['size']
        and row.get('digest') == 'sha256:' + C['assets'][name]['sha256'])

def validate_files(files):
    require(set(files) == set(C['assets']))
    for name, data in files.items():
        require(len(data) == C['assets'][name]['size'] and digest(data) == C['assets'][name]['sha256'])

def payloads(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 7 and {e.filename for e in entries} == set(C['assets']))
        for e in entries:
            require(not e.is_dir() and not stat.S_ISLNK(e.external_attr >> 16)
                and not e.flag_bits & 1 and e.file_size == C['assets'][e.filename]['size'])
        files = {e.filename: archive.read(e) for e in entries}
    validate_files(files)
    return files

def transfer(api, download, env, event):
    context(env, event)
    run, jobs = run_jobs(api, 38167617349, '.github/workflows/msix.yml', 'push', sp.REQUIRED_JOBS | {'cleanup-transports'})
    require(run.get('run_number') == 64)
    run_jobs(api, 38171791278, '.github/workflows/store-package.yml', 'workflow_dispatch', {'package', 'verify-api'})
    artifact = api('GET', ROOT + '/actions/artifacts/11713548698')
    require(artifact.get('id') == 11713548698 and artifact.get('expired') is False
        and artifact.get('name') == 'opengeul-store-38171791278'
        and artifact.get('size_in_bytes') == C['storeArtifactBytes']
        and artifact.get('digest') == 'sha256:' + C['storeArtifactSha256']
        and artifact.get('workflow_run', {}).get('id') == 38171791278
        and artifact['workflow_run'].get('head_sha') == C['sourceCommit']
        and artifact['workflow_run'].get('head_branch') == 'main')
    raw = download(artifact)
    require(len(raw) == C['storeArtifactBytes'] and digest(raw) == C['storeArtifactSha256'])
    files = payloads(raw)
    tag = api('GET', ROOT + '/commits/' + C['sourceTag'])
    sp.authorize_release(C['sourceTag'], json.loads(files['source-provenance.json']), run, tag['sha'], jobs)
    source_assets(api); archive_state(api)
    for name in sorted(files):
        source_assets(api)
        present = {r['name'] for r in archive_state(api)}
        if name not in present:
            validate_files(files)
            asset(api('POST', UPLOAD + urllib.parse.quote(name, safe=''), files[name]), name)
    source_assets(api)
    run_jobs(api, 38167617349, '.github/workflows/msix.yml', 'push', sp.REQUIRED_JOBS | {'cleanup-transports'})
    rows = archive_state(api); require(len(rows) == 7)
    return {'archiveId': 409905491, 'published': False, 'diagnosticOnly': True,
        'assets': [{k: r[k] for k in ('id', 'name', 'size', 'state', 'digest')} for r in rows]}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None

class Transport:
    def __init__(self, token): self.token = token; self.opener = urllib.request.build_opener(NoRedirect)
    def __call__(self, method, path, data=None):
        require(method == 'GET' and path.startswith(ROOT + '/') or method == 'POST'
            and path == UPLOAD + urllib.parse.quote(path.removeprefix(UPLOAD), safe='')
            and path.removeprefix(UPLOAD) in C['assets'] and data is not None)
        url = path if method == 'POST' else 'https://api.github.com/' + path
        request = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/octet-stream'})
        try:
            with self.opener.open(request, timeout=60) as response:
                require(response.status == (201 if method == 'POST' else 200))
                raw = response.read(2 * 1024 * 1024 + 1); require(len(raw) <= 2 * 1024 * 1024)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if method == 'GET' and path == REF and exc.code == 404: return None
            raise RuntimeError('Archive API request failed') from None
    def download(self, artifact):
        request = urllib.request.Request('https://api.github.com/' + ROOT + '/actions/artifacts/11713548698/zip',
            headers={'Authorization': 'Bearer ' + self.token})
        try: self.opener.open(request, timeout=60); raise ValueError('Expected official artifact redirect')
        except urllib.error.HTTPError as exc:
            require(exc.code == 302); location = exc.headers['Location']
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == 'https' and parsed.hostname.endswith('.blob.core.windows.net')
            and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment)
        with self.opener.open(urllib.request.Request(location), timeout=60) as response:
            require(response.status == 200)
            raw = response.read(C['storeArtifactBytes'] + 1)
            require(len(raw) == C['storeArtifactBytes'])
            return raw

sys.path.insert(0, str(BASE / 'scripts'))
import store_package as sp

if __name__ == '__main__':
    try:
        for name, expected in C['validators'].items(): require(digest((BASE / name).read_bytes()) == expected)
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        transport = Transport(os.environ['GH_TOKEN'])
        print(json.dumps(transfer(transport, transport.download, os.environ, event), indent=2))
    except Exception:
        print('Archive transfer failed; draft retained. No publication requested.', file=sys.stderr)
        sys.exit(1)
