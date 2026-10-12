"""Submit a verified stable Store package; preserve uncertain writes across runs."""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from buildkit import manifest, package_version
from check_store_api import authenticate
from releasekit import REPOSITORY, verify_msix
from store_listing import apply_korean_listing
from store_package import (STORE_APP_ID, STORE_IDENTITY, authorize_release,
                           prepare, verify_checksums, verify_repackage)

BASE = f'https://manage.devcenter.microsoft.com/v1.0/my/applications/{STORE_APP_ID}'
TITLE = f'OpenGeul Store submission state ({STORE_APP_ID})'
JOURNAL = '<!-- opengeul-store-state\n'
MARKER = 'OpenGeul request '
ACCEPTED = {'PreProcessing', 'Certification', 'Release', 'PendingPublication', 'Publishing', 'Published'}
FAILED = {'CommitFailed', 'PreProcessingFailed', 'CertificationFailed', 'ReleaseFailed', 'PublishFailed', 'Canceled'}
PHASES = {'idle', 'delete_attempted', 'delete_confirmed', 'create_attempted', 'draft_ready', 'commit_attempted', 'submitted'}
LIMIT = 96 * 1024 * 1024


class SubmissionBlocked(ValueError):
    """A fixed, secret-free reason that can be shown in GitHub."""


class StoreError(SubmissionBlocked):
    def __init__(self, operation, status):
        self.status = status
        super().__init__(f'Store {operation} failed with HTTP {status}' if status else f'Store {operation} has no acknowledged response')


def _id(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,24}', str(value)):
        raise SubmissionBlocked('Invalid owned resource ID')
    return str(value)


def _version(tag):
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise SubmissionBlocked('Only canonical stable vX.Y.Z tags may submit to Store')
    try: package_version(tag[1:])
    except ValueError: raise SubmissionBlocked('Only canonical stable vX.Y.Z tags may submit to Store') from None
    return tuple(int(part) for part in tag[1:].split('.'))


def _gh(method, path, data=None, *, pages=False):
    command = ['gh', 'api', '--method', method, f'repos/{REPOSITORY}/{path}']
    if pages: command += ['--paginate', '--slurp']
    if data is not None: command += ['--input', '-']
    try:
        response = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                                  check=True, capture_output=True, text=True, encoding='utf-8', timeout=120)
        return json.loads(response.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        raise SubmissionBlocked(f'GitHub {method} failed; response contents were not logged') from None


def _request(opener, token, method, path, data=None):
    if method not in {'GET', 'POST', 'PUT', 'DELETE'} or not re.fullmatch(r'(?:submissions(?:/[1-9][0-9]{0,24})?(?:/(?:status|commit))?)?', path):
        raise SubmissionBlocked('Unowned Store API request')
    request = urllib.request.Request(BASE + ('/' + path if path else ''), method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Content-Type': 'application/json'})
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024: raise ValueError('Response too large')
            if method == 'DELETE': return response.status, body
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        raise StoreError(method, error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise StoreError(method, None) from None


def _upload(opener, url, body):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port is not None
            or not re.fullmatch(r'[a-z0-9]{3,24}\.blob\.core\.windows\.net', parsed.hostname or '')
            or not parsed.path.startswith('/') or not parsed.query or len(body) > LIMIT):
        raise SubmissionBlocked('Invalid bounded Store upload destination')
    request = urllib.request.Request(url, method='PUT', data=body, headers={
        'Content-Type': 'application/zip', 'Content-Length': str(len(body)),
        'Content-MD5': base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode(),
        'x-ms-blob-type': 'BlockBlob', 'x-ms-version': '2020-10-02'})
    try:
        with opener.open(request, timeout=120) as response:
            if response.status != 201 or response.read(1): raise StoreError('upload', response.status)
    except urllib.error.HTTPError as error:
        raise StoreError('upload', error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise StoreError('upload', None) from None


def _newer(version):
    for page in _gh('GET', 'tags?per_page=100', pages=True):
        for tag in page:
            try: candidate = _version(tag['name'])
            except (KeyError, SubmissionBlocked): continue
            if candidate > version: return True
    return False


def _inspect_qualified(directory, source):
    # 실제 Store 신원/서명/설치/native/raw12 검증은 공유 검사기를 반드시 사용한다.
    from store_qualification import inspect_qualified
    return inspect_qualified(directory, source)


def _actor(actor):
    if not isinstance(actor, dict): return False
    if actor.get('login') == 'ATLKR': return actor.get('type') == 'User'
    return (actor.get('login') == 'github-actions[bot]' and actor.get('type') == 'Bot'
            and type(actor.get('id')) is int and actor['id'] == 41898282)


def _store_workflow(details):
    run_id = _id(os.getenv('GITHUB_RUN_ID'))
    attempt = _id(os.getenv('GITHUB_RUN_ATTEMPT'))
    sha = os.getenv('GITHUB_SHA')
    run = _gh('GET', f'actions/runs/{run_id}')
    if (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
            or _id(run.get('id')) != run_id or run.get('head_sha') != sha
            or type(run.get('run_attempt')) is not int or str(run['run_attempt']) != attempt
            or run.get('repository', {}).get('full_name') != REPOSITORY
            or run.get('repository', {}).get('private') is not False
            or run.get('event') != 'workflow_dispatch' or run.get('head_branch') != 'main'
            or run.get('path') != '.github/workflows/store-package.yml'
            or run.get('status') != 'in_progress' or run.get('conclusion') is not None
            or not _actor(run.get('actor')) or not _actor(run.get('triggering_actor'))
            or run['actor']['login'] != os.getenv('GITHUB_ACTOR')
            or details.get('repackageCommit') != sha or str(details.get('repackageRunId')) != run_id):
        raise SubmissionBlocked('Store writes require the current owned main workflow and actor')
    jobs = [job for page in _gh('GET', f'actions/runs/{run_id}/jobs?per_page=100', pages=True) for job in page['jobs']]
    for name in ('package', 'Store WACK (windows-2025)', 'Store WACK (windows-11-arm)', 'qualify'):
        found = [job for job in jobs if job.get('name') == name]
        if (len(found) != 1 or found[0].get('status') != 'completed' or found[0].get('conclusion') != 'success'
                or str(found[0].get('run_id')) != run_id or type(found[0].get('run_attempt')) is not int
                or str(found[0]['run_attempt']) != attempt or found[0].get('head_sha') != sha):
            raise SubmissionBlocked('Both Store WACK and qualification jobs must succeed in this exact execution')
    return attempt


def _verify(tag, directory):
    from release_pair import verify_pair, source_fingerprint, copy_architecture
    version = _version(tag)
    if os.getenv('GITHUB_REPOSITORY') != REPOSITORY or os.getenv('GITHUB_REF') != 'refs/heads/main':
        raise SubmissionBlocked('Store writes require the owned main workflow')
    product = json.loads((Path(__file__).resolve().parents[1] / 'config/product.json').read_text(encoding='utf-8'))
    if product.get('version') != tag[1:]: raise SubmissionBlocked('Stable submission must match the current product version')
    verify_checksums(directory)
    if sum(path.stat().st_size for path in directory.iterdir()) > LIMIT:
        raise SubmissionBlocked('Store artifacts exceed 96 MiB')
    details = json.loads((directory / 'store-provenance.json').read_text(encoding='utf-8'))
    source = directory.resolve().parent / '.work/store-source'
    provenance = verify_pair(source)
    fingerprint = source_fingerprint(source)
    if (type(details.get('formatVersion')) is not int or details['formatVersion'] != 2
            or type(provenance.get('formatVersion')) is not int or provenance['formatVersion'] != 2
            or set(details.get('architectures', {})) != {'x64', 'arm64'}
            or provenance != json.loads((directory / 'source-provenance.json').read_text(encoding='utf-8'))
            or details.get('storeAppId') != STORE_APP_ID or details.get('identity') != STORE_IDENTITY
            or details.get('version') != tag[1:] or provenance.get('version') != tag[1:]
            or details.get('unsigned') is not True or details.get('storeCertified') is not False
            or details.get('sourceCommit') != provenance.get('commit')
            or details.get('sourceRunId') != provenance.get('runId')
            or details.get('sourceRunAttempt') != provenance.get('runAttempt')
            or details.get('sourceAssetFingerprintSha256') != fingerprint
            or details.get('sourceRelease') != f'https://github.com/{REPOSITORY}/releases/tag/{tag}'):
        raise SubmissionBlocked('Store pair provenance does not match its validated Source22')
    run_id = _id(provenance['runId'])
    release = _gh('GET', f'releases/tags/{tag}')
    if release.get('draft') is not False or release.get('tag_name') != tag or _id(release['id']) != _id(details['sourceReleaseId']):
        raise SubmissionBlocked('Source release identity changed')
    assets = release.get('assets')
    local = {path.name: path for path in source.iterdir()}
    if (not isinstance(assets, list) or len(assets) != 22
            or {item.get('name') for item in assets} != set(local)):
        raise SubmissionBlocked('The published source must contain exactly the validated 22 assets')
    for asset in assets:
        path = local[asset['name']]; _id(asset.get('id'))
        if (asset.get('state') != 'uploaded' or type(asset.get('size')) is not int
                or asset['size'] != path.stat().st_size
                or asset.get('digest') != 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()):
            raise SubmissionBlocked('Published Source22 asset bytes changed')
    run = _gh('GET', f'actions/runs/{run_id}')
    if run.get('event') != 'push' or run.get('head_branch') != tag:
        raise SubmissionBlocked('Store submission requires the stable tag push source run')
    jobs = [job for page in _gh('GET', f'actions/runs/{run_id}/jobs?per_page=100', pages=True) for job in page['jobs']]
    authorize_release(tag, provenance, run, _gh('GET', f'commits/{tag}')['sha'], jobs)
    attempt = _store_workflow(details)
    proof = _inspect_qualified(directory, source)
    if (type(proof.get('formatVersion')) is not int or proof['formatVersion'] != 1
            or proof.get('repository') != REPOSITORY or proof.get('storeCertified') is not False
            or set(proof.get('architectures', {})) != {'x64','arm64'}
            or proof.get('storeRunAttempt') != attempt
            or any(proof.get(key) != details[key] for key in (
                'sourceCommit','sourceRunId','sourceRunAttempt','sourceReleaseId','sourceAssetFingerprintSha256',
                'repackageCommit','repackageRunId'))):
        raise SubmissionBlocked('Current dual Store identity qualification is required')
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix='store-pair-recheck-', dir=source.parent) as temporary, \
            zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        for architecture in ('x64', 'arm64'):
            entry = details['architectures'][architecture]
            original = provenance['architectures'][architecture]['provenance']
            restored = Path(temporary) / architecture
            copy_architecture(source, architecture, restored)
            with tempfile.TemporaryDirectory(prefix='payload-', dir=temporary) as payload:
                prepared = prepare(restored, Path(payload) / 'runtime', architecture=architecture)
            name = f'OpenGeul_{package_version(tag[1:])}_{architecture}_store-unsigned.msix'
            package = directory / name
            receipt = proof['architectures'][architecture]
            if (entry.get('package') != name or entry.get('manifest') != f'AppxManifest-{architecture}.xml'
                    or entry.get('sourceMsix') != original['package'] or prepared['msix'] != original['package']
                    or entry.get('sourceMsixSha256') != original['sha256']
                    or verify_msix(source / original['package'], architecture=architecture)['sha256'] != original['sha256']
                    or verify_msix(package, architecture=architecture)['sha256'] != entry.get('sha256')
                    or (directory / entry['manifest']).read_bytes() != manifest(STORE_IDENTITY, tag[1:], architecture).encode()
                    or verify_repackage(source / original['package'], package, tag[1:], architecture=architecture) != entry.get('runtimeSha256')
                    or receipt.get('architecture') != architecture or receipt.get('fullWackPassed') is not True
                    or receipt.get('storeCertified') is not False or receipt.get('originalMsix') != name
                    or receipt.get('originalMsixSha256') != entry['sha256']):
                raise SubmissionBlocked('One Store package lacks matching source bytes, complete parity or full WACK')
            raw = package.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise SubmissionBlocked('Store package changed while preparing upload')
            archive.writestr(name, raw)
    if source_fingerprint(source) != fingerprint: raise SubmissionBlocked('Source pair changed during submission validation')
    body = buffer.getvalue()
    if len(body) > LIMIT: raise SubmissionBlocked('Store ZIP exceeds 96 MiB')
    return details, version, body


def _journal_state(body):
    if not isinstance(body, str) or body.count(JOURNAL) != 1 or len(body) > 64 * 1024:
        raise SubmissionBlocked('Store state Issue has invalid journal metadata')
    state = json.loads(body.split(JOURNAL, 1)[1].split('\n-->', 1)[0])
    if state.get('app_id') != STORE_APP_ID or state.get('phase') not in PHASES:
        raise SubmissionBlocked('Store state Issue belongs to another app or phase')
    if state['phase'] in {'draft_ready', 'commit_attempted', 'submitted'}: _id(state.get('submission_id'))
    for field in ('submission_id', 'deleted_id', 'baseline_id', 'release_id', 'run_id'):
        if state.get(field) is not None: _id(state[field])
    if state.get('tag') is not None: _version(state['tag'])
    for field, size in (('source_sha', 40), ('source_msix_sha256', 64)):
        if state.get(field) is not None and (not isinstance(state[field], str) or not re.fullmatch('[0-9a-f]{' + str(size) + '}', state[field])):
            raise SubmissionBlocked('Store state Issue has invalid source identity')
    fields = {'source_asset_fingerprint_sha256', 'source_msix_sha256_by_arch', 'store_msix_sha256_by_arch'}
    if fields & state.keys():
        if (not fields <= state.keys() or not isinstance(state['source_asset_fingerprint_sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', state['source_asset_fingerprint_sha256'])):
            raise SubmissionBlocked('Store journal has incomplete source pair identity')
        for field in fields - {'source_asset_fingerprint_sha256'}:
            value = state[field]
            if (not isinstance(value, dict) or set(value) != {'x64','arm64'}
                    or any(not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) for digest in value.values())):
                raise SubmissionBlocked('Store journal has incomplete package pair identity')
    return state


def _owned_journal(item):
    if not isinstance(item, dict): return False
    author = item.get('user')
    return (item.get('title') == TITLE and 'pull_request' not in item
            and isinstance(author, dict) and author.get('login') == 'github-actions[bot]'
            and author.get('type') == 'Bot' and author.get('id') == 41898282)


def _journal():
    candidates = [item for page in _gh('GET', 'issues?state=all&per_page=100', pages=True) for item in page
                  if _owned_journal(item)]
    if len(candidates) > 1: raise SubmissionBlocked('Multiple Store state Issues require reconciliation')
    if candidates:
        item = candidates[0]
        state = None
    else:
        state = {'app_id': STORE_APP_ID, 'phase': 'idle'}
        item = _gh('POST', 'issues', {'title': TITLE, 'body': _journal_body(state)})
        if not _owned_journal(item) or _journal_state(item['body']) != state:
            raise SubmissionBlocked('Owned Store state Issue creation was not acknowledged')
    number = _id(item['number'])
    fresh = _gh('GET', f'issues/{number}')
    if not _owned_journal(fresh) or _id(fresh['number']) != number:
        raise SubmissionBlocked('Store state Issue ownership could not be confirmed')
    current = _journal_state(fresh['body'])
    if state is not None and current != state:
        raise SubmissionBlocked('Store state Issue creation could not be confirmed')
    return {'number': number, 'state': current}


def _journal_body(state, warning=None):
    text = 'Store 자동화 상태 기록입니다. 시도한 동작의 결과를 확인하기 전에는 해당 단계를 지우지 마세요.\n'
    if warning: text += f'\n@ATLKR Store 자동화를 중단했습니다. 기술 진단: {warning}. Store 상태와 이 Actions 실행을 API로 확인하세요.\n'
    run_id = os.getenv('GITHUB_RUN_ID') or state.get('run_id')
    if run_id: text += f'\n[Actions 실행](https://github.com/{REPOSITORY}/actions/runs/{_id(run_id)})\n'
    if state.get('tag'): text += f'\n[소스 릴리스](https://github.com/{REPOSITORY}/releases/tag/{state["tag"]})\n'
    return text + '\n' + JOURNAL + json.dumps(state, sort_keys=True) + '\n-->\n'


def _save(journal, phase, details=None, *, warning=None, **fields):
    state = dict(journal['state'], phase=phase)
    if details:
        state.update(tag='v' + details['version'], release_id=_id(details['sourceReleaseId']),
                     run_id=_id(details['sourceRunId']), source_sha=details['sourceCommit'])
        if details.get('formatVersion') == 2:
            state.pop('source_msix_sha256', None)
            state.update(_pair_identity(details))
        else: state['source_msix_sha256'] = details['sourceMsixSha256']
    state.update(fields)
    if 'source_asset_fingerprint_sha256' in state:
        current = _gh('GET', f'issues/{journal["number"]}')
        if (not _owned_journal(current) or _id(current['number']) != journal['number']
                or _journal_state(current['body']) != journal['state']):
            raise SubmissionBlocked('Store journal changed before mutation; reconcile the current attempt')
    expected = _journal_body(state, warning)
    item = _gh('PATCH', f'issues/{journal["number"]}', {'body': expected, 'state': 'open'})
    if not _owned_journal(item) or _id(item['number']) != journal['number'] or _journal_state(item['body']) != state:
        raise SubmissionBlocked('Store journal update was not acknowledged')
    fresh = _gh('GET', f'issues/{journal["number"]}')
    if not _owned_journal(fresh) or _id(fresh['number']) != journal['number'] or _journal_state(fresh['body']) != state:
        raise SubmissionBlocked('Store journal update could not be confirmed')
    journal['state'] = state


def _marker(details):
    if details.get('formatVersion') == 2:
        value = {key: details[key] for key in ('formatVersion','version','sourceReleaseId','sourceCommit','sourceAssetFingerprintSha256')}
        value['architectures'] = {arch: {key: entry[key] for key in ('sourceMsixSha256','package','sha256')}
            for arch, entry in details['architectures'].items()}
        return MARKER + json.dumps(value, sort_keys=True)
    return MARKER + json.dumps({key: details[key] for key in ('version', 'sourceReleaseId', 'sourceCommit', 'sourceMsixSha256')}, sort_keys=True)


def _pair_identity(details):
    return {'source_asset_fingerprint_sha256': details['sourceAssetFingerprintSha256'],
        'source_msix_sha256_by_arch': {arch: entry['sourceMsixSha256'] for arch,entry in details['architectures'].items()},
        'store_msix_sha256_by_arch': {arch: entry['sha256'] for arch,entry in details['architectures'].items()}}


def _journal_matches(state, details):
    if (state.get('tag') != 'v' + details['version'] or state.get('source_sha') != details['sourceCommit']
            or state.get('release_id') != _id(details['sourceReleaseId']) or state.get('run_id') != _id(details['sourceRunId'])):
        return False
    if details.get('formatVersion') == 2:
        return all(state.get(key) == value for key,value in _pair_identity(details).items())
    return state.get('source_msix_sha256') == details['sourceMsixSha256']


def _app(api):
    _, app = api('GET', '')
    if (not isinstance(app, dict) or app.get('id') != STORE_APP_ID
            or app.get('packageIdentityName') != STORE_IDENTITY['name']
            or app.get('publisherName') != STORE_IDENTITY['publisher']):
        raise SubmissionBlocked('Store returned another application identity')
    for name in ('pendingApplicationSubmission', 'lastPublishedApplicationSubmission'):
        if app.get(name) is not None:
            if not isinstance(app[name], dict): raise SubmissionBlocked('Invalid Store submission reference')
            _id(app[name].get('id'))
    return app


def _ref(app, key):
    return _id(app[key]['id']) if app.get(key) is not None else None


def _free(submission):
    pricing = submission.get('pricing', {})
    overrides = pricing.get('marketSpecificPricings')
    if (pricing.get('priceId') != 'Free' or not isinstance(overrides, dict)
            or any(value not in ('Free', 'Base', 'NotAvailable') for value in overrides.values())):
        raise SubmissionBlocked('Free Store pricing and all market overrides must be preserved')


def _publication_mode(submission):
    if submission.get('targetPublishMode') not in ('Manual', 'Immediate'):
        raise SubmissionBlocked('Store publication mode is unknown')


def _immediate(submission):
    if submission.get('targetPublishMode') != 'Immediate':
        raise SubmissionBlocked('This Store update must publish automatically after certification')


def _packages_version(submission):
    versions = []
    packages = submission.get('applicationPackages')
    if not isinstance(packages, list) or not packages: raise SubmissionBlocked('Store package versions are unavailable')
    for package in packages:
        if package.get('fileStatus') == 'PendingDelete': continue
        value = package.get('version')
        if (not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', value)
                or any(int(part) > 65535 for part in value.split('.'))):
            raise SubmissionBlocked('Unknown pending Store version requires reconciliation')
        versions.append(tuple(int(part) for part in value.split('.')))
    if not versions: raise SubmissionBlocked('Store package versions are unavailable')
    return max(versions)


def _packages_match(submission, expected):
    actual = submission.get('applicationPackages')
    if not isinstance(actual, list) or len(actual) != len(expected): return False
    by_name = {package.get('fileName'): package for package in actual if isinstance(package, dict)}
    return (len(by_name) == len(expected)
            and all(package['fileName'] in by_name
                    and all(by_name[package['fileName']].get(field) == value for field, value in package.items())
                    for package in expected))


def _published_architectures(submission):
    packages = submission.get('applicationPackages')
    if not isinstance(packages, list): raise SubmissionBlocked('Published package architectures are unavailable')
    active = [item for item in packages if item.get('fileStatus') != 'PendingDelete']
    architectures = []
    for item in active:
        value = item.get('architecture')
        if not isinstance(value, str) or not value.isascii():
            raise SubmissionBlocked('Published package architecture is unknown')
        architectures.append(value.lower())
    if sorted(architectures) not in (['x64'], ['arm64','x64']):
        raise SubmissionBlocked('Published baseline must be x64 or one matching x64/ARM64 pair')
    if any(item.get('fileStatus') != 'Uploaded' for item in active):
        raise SubmissionBlocked('Published baseline package is not uploaded')
    if len(active) == 2 and active[0].get('version') != active[1].get('version'):
        raise SubmissionBlocked('Published baseline pair versions differ')


def _requested_pair(api, submission_id, details, template):
    """동일 SID만 재조회. PreProcessing의 미완성 SDK 필드는 관측 성공으로 꾸미지 않는다."""
    expected = {entry['package']: arch for arch,entry in details['architectures'].items()}
    deadline = time.monotonic() + 600
    for _ in range(40):
        _, current = api('GET', f'submissions/{submission_id}')
        _immediate(current); _free(current)
        if (current.get('status') not in ACCEPTED | {'CommitStarted'}
                or _id(current.get('id')) != submission_id or _marker(details) not in current.get('notesForCertification','').splitlines()
                or current.get('pricing') != template.get('pricing') or current.get('listings') != template.get('listings')):
            raise SubmissionBlocked('Committed Store pair identity, publication control or metadata changed')
        packages = current.get('applicationPackages')
        if not isinstance(packages, list) or any(not isinstance(item, dict) for item in packages):
            raise SubmissionBlocked('Committed Store package records are unavailable')
        active = [item for item in packages if item.get('fileStatus') != 'PendingDelete']
        names = [item.get('fileName') for item in active]
        if len(names) != len(set(names)) or any(name not in expected for name in names):
            raise SubmissionBlocked('Committed Store package pair contains unexpected records')
        if set(names) == set(expected):
            observed = True
            for item in active:
                arch = expected[item['fileName']]
                value = item.get('architecture')
                if value is not None and (not isinstance(value,str) or not value.isascii() or value.lower() != arch):
                    raise SubmissionBlocked('Committed Store package architecture differs')
                if item.get('version') is not None and item['version'] != package_version(details['version']):
                    raise SubmissionBlocked('Committed Store package version differs')
                if item.get('fileStatus') not in {'PendingUpload','Uploaded'}:
                    raise SubmissionBlocked('Committed Store package upload state is unknown')
                observed &= value is not None and item.get('version') is not None and item.get('fileStatus') == 'Uploaded'
            return {'packageMetadataObserved': bool(observed)}
        if time.monotonic() + 15 >= deadline: break
        time.sleep(15)
    raise SubmissionBlocked('Committed Store pair names remain unconfirmed after bounded same-ID polling')


def _poll(api, submission_id):
    deadline = time.monotonic() + 600
    for _ in range(40):
        _, result = api('GET', f'submissions/{submission_id}/status')
        status = result.get('status')
        if status in ACCEPTED | FAILED: return status
        if status not in {'PendingCommit', 'CommitStarted'}: raise SubmissionBlocked('Store processing status is unknown')
        if time.monotonic() + 15 >= deadline: break
        time.sleep(15)
    raise SubmissionBlocked('Store commit outcome remains unconfirmed after bounded polling')


def _warn(reason):
    print(f'::error::Store 제출 자동화를 중단했습니다. 기술 진단: {reason}')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(f'Store 자동화를 중단했습니다. 기술 진단: {reason}. GitHub 릴리스는 계속 이용할 수 있습니다.\n')
    try:
        journal = _journal()
        _save(journal, journal['state']['phase'], warning=reason)
    except (SubmissionBlocked, KeyError, TypeError, ValueError, AttributeError):
        print('::error::GitHub warning Issue could not be updated; inspect this Actions failure.')


def submit(tag, directory):
    try:
        details, version, body = _verify(tag, directory)
        journal = _journal()
        state = journal['state']
        if state['phase'] in {'delete_attempted', 'create_attempted'}:
            raise SubmissionBlocked('An earlier Store mutation lacks acknowledgment; reconcile the app journal before any new submission')
        opener, token = authenticate()
        def api(method, path, data=None): return _request(opener, token, method, path, data)
        paired = details.get('formatVersion') == 2
        if paired and state.get('tag') == tag and state['phase'] in {'draft_ready','commit_attempted','submitted'} and not _journal_matches(state, details):
            raise SubmissionBlocked('Current journal does not own the complete verified package pair')
        if state['phase'] == 'commit_attempted':
            submission_id = _id(state.get('submission_id'))
            _, current = api('GET', f'submissions/{submission_id}')
            if _id(current.get('id')) != submission_id:
                raise SubmissionBlocked('Recorded Store submission identity changed')
            if current.get('status') in FAILED and state.get('tag') != tag:
                _publication_mode(current)  # 실패가 확정된 과거 Manual journal의 읽기 복구만 허용한다.
            else:
                _immediate(current)
            status = _poll(api, submission_id)
            _save(journal, 'submitted', status=status)
            state = journal['state']
        if state['phase'] == 'submitted' and state.get('status') in FAILED and state.get('tag') == tag:
            raise SubmissionBlocked(f'Store processing stopped in {state["status"]}; a newer stable release is required')
        if _newer(version): return {'outcome': 'superseded', 'tag': tag}
        app = _app(api)
        baseline_id = _ref(app, 'lastPublishedApplicationSubmission')
        if not baseline_id:
            raise SubmissionBlocked('Automatic Store replacement requires a Published baseline; the initial submission was preserved')
        _, baseline = api('GET', f'submissions/{baseline_id}')
        if _id(baseline['id']) != baseline_id or baseline.get('status') != 'Published':
            raise SubmissionBlocked('Store has no verified Published baseline')
        _free(baseline)
        _publication_mode(baseline)
        if paired: _published_architectures(baseline)
        elif (not isinstance(baseline.get('applicationPackages'), list) or not baseline['applicationPackages']
                or any(package.get('architecture', '').lower() != 'x64' for package in baseline['applicationPackages'])):
            raise SubmissionBlocked('Automatic updates require the published x64 package template')
        pending_id = _ref(app, 'pendingApplicationSubmission')
        if state['phase'] in {'draft_ready', 'submitted'} and state['submission_id'] not in {pending_id, baseline_id}:
            raise SubmissionBlocked('Recorded Store submission disappeared without acknowledged deletion or publication')
        target = version + (0,)
        if _packages_version(baseline) >= target: return {'outcome': 'superseded', 'tag': tag}
        # 설명 계획 전체를 확인한 뒤에만 기존 제출을 삭제하거나 새 제출을 만든다.
        template = apply_korean_listing(baseline)
        template['targetPublishMode'] = 'Immediate'
        pending = None
        if pending_id:
            if pending_id == baseline_id: raise SubmissionBlocked('Published submissions cannot be deleted')
            _, pending = api('GET', f'submissions/{pending_id}')
            if (_id(pending['id']) != pending_id or pending.get('status') == 'Published'
                    or pending.get('status') not in ACCEPTED | FAILED | {'None', 'PendingCommit', 'CommitStarted'}):
                raise SubmissionBlocked('Published or unowned pending submission cannot be replaced')
            # 과거 tag의 journal도 처리 중인 Manual 제출의 삭제/재commit을 허가하지 않는다.
            if pending.get('status') in ACCEPTED | {'CommitStarted'}:
                _immediate(pending)
            lines = pending.get('notesForCertification', '').splitlines()
            matching = _marker(details) in lines
            if matching and pending.get('status') in FAILED:
                _save(journal, 'submitted', details, submission_id=pending_id, status=pending['status'])
                raise SubmissionBlocked(f'Store processing stopped in {pending["status"]}; a newer stable release is required')
            if matching and pending.get('status') in ACCEPTED | {'CommitStarted'}:
                status = pending['status']
                if status == 'CommitStarted':
                    status = _poll(api, pending_id)
                    _, pending = api('GET', f'submissions/{pending_id}')
                _immediate(pending)
                _save(journal, 'submitted', details, submission_id=pending_id, status=status)
                if status in FAILED: raise SubmissionBlocked(f'Store processing stopped in {status}; a newer stable release is required')
                if paired:
                    observed = _requested_pair(api, pending_id, details, template)
                else:
                    if (_id(pending['id']) != pending_id or _packages_version(pending) != target
                            or not any(package.get('fileName') == details['package'] and package.get('version') == package_version(tag[1:])
                                       and package.get('fileStatus') != 'PendingDelete' for package in pending['applicationPackages'])):
                        raise SubmissionBlocked('Existing Store request does not contain the verified target package version')
                    observed = {}
                return {'outcome': 'already_requested', 'tag': tag, 'submission_id': pending_id, 'status': status, **observed}
            owned = matching or (state['phase'] == 'draft_ready' and state.get('submission_id') == pending_id
                     and _journal_matches(state, details))
            if owned and pending.get('status') == 'PendingCommit':
                # 소유권이 확인된 편집 가능한 Manual 초안만 동일 SID PUT으로 전환한다.
                _publication_mode(pending)
            if not (owned and pending.get('status') == 'PendingCommit'):
                if paired and not (state['phase'] in {'draft_ready','submitted'}
                        and state.get('submission_id') == pending_id and state.get('tag')
                        and _version(state['tag']) < version):
                    raise SubmissionBlocked('An unowned pending Store submission is preserved for reconciliation')
                if _packages_version(pending) >= target: return {'outcome': 'superseded', 'tag': tag}
                fresh = _app(api)
                if _ref(fresh, 'pendingApplicationSubmission') != pending_id or _ref(fresh, 'lastPublishedApplicationSubmission') != baseline_id or _newer(version):
                    raise SubmissionBlocked('Store or stable tag state changed before deletion')
                _, current = api('GET', f'submissions/{pending_id}')
                if (_id(current['id']) != pending_id or current.get('status') == 'Published'
                        or any(current.get(field) != pending.get(field) for field in ('status', 'applicationPackages', 'notesForCertification', 'pricing', 'listings'))
                        or _packages_version(current) >= target):
                    raise SubmissionBlocked('Pending submission changed before deletion')
                _save(journal, 'delete_attempted', details, deleted_id=pending_id, baseline_id=baseline_id, submission_id=None)
                status, acknowledgment = api('DELETE', f'submissions/{pending_id}')
                if not 200 <= status < 300 or acknowledgment != b'':
                    raise SubmissionBlocked('Store deletion was not acknowledged by an empty successful response')
                fresh = _app(api)
                if _ref(fresh, 'pendingApplicationSubmission') is not None or _ref(fresh, 'lastPublishedApplicationSubmission') != baseline_id:
                    raise SubmissionBlocked('Store deletion is not confirmed or another submission appeared')
                try: api('GET', f'submissions/{pending_id}')
                except StoreError as error:
                    if error.status != 404: raise
                else: raise SubmissionBlocked('Deleted Store submission is still readable')
                _save(journal, 'delete_confirmed')
                pending_id = None
        if not pending_id:
            fresh = _app(api)
            if _ref(fresh, 'pendingApplicationSubmission') is not None or _ref(fresh, 'lastPublishedApplicationSubmission') != baseline_id or _newer(version):
                raise SubmissionBlocked('Store or stable tag state changed before creation')
            _save(journal, 'create_attempted', details, baseline_id=baseline_id, submission_id=None)
            _, pending = api('POST', 'submissions')
            pending_id = _id(pending['id'])
            if pending_id == baseline_id or pending.get('status') != 'PendingCommit':
                raise SubmissionBlocked('New Store draft was not acknowledged')
            _save(journal, 'draft_ready', details, submission_id=pending_id)
        metadata = template
        for package in metadata['applicationPackages']:
            package['fileStatus'] = 'PendingDelete'
        package_names = ([details['architectures'][arch]['package'] for arch in ('x64','arm64')]
                         if paired else [details['package']])
        for name in package_names:
            metadata['applicationPackages'].append({'fileName': name, 'fileStatus': 'PendingUpload',
                                                   'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None'})
        notes = [line for line in metadata.get('notesForCertification', '').splitlines() if not line.startswith(MARKER)]
        metadata['notesForCertification'] = '\n'.join(notes + [_marker(details)])
        for field in ('id', 'status', 'statusDetails', 'fileUploadUrl', 'friendlyName'):
            metadata.pop(field, None)
        _, updated = api('PUT', f'submissions/{pending_id}', metadata)
        _immediate(updated)
        if (_id(updated['id']) != pending_id or updated.get('status') != 'PendingCommit'
                or _marker(details) not in updated.get('notesForCertification', '').splitlines()
                or not _packages_match(updated, metadata['applicationPackages'])
                or updated.get('pricing') != metadata['pricing'] or updated.get('listings') != metadata.get('listings')):
            raise SubmissionBlocked('Store metadata update was not confirmed')
        _upload(opener, updated['fileUploadUrl'], body)
        fresh = _app(api)
        if _ref(fresh, 'pendingApplicationSubmission') != pending_id or _ref(fresh, 'lastPublishedApplicationSubmission') != baseline_id or _newer(version):
            raise SubmissionBlocked('Store or stable tag state changed before commit')
        _, current = api('GET', f'submissions/{pending_id}')
        _immediate(current)
        if (_id(current['id']) != pending_id or current.get('status') != 'PendingCommit' or _marker(details) not in current.get('notesForCertification', '').splitlines()
                or not _packages_match(current, metadata['applicationPackages'])
                or current.get('pricing') != updated.get('pricing') or current.get('listings') != updated.get('listings')):
            raise SubmissionBlocked('Store draft changed before commit')
        _save(journal, 'commit_attempted', details, submission_id=pending_id)
        try: api('POST', f'submissions/{pending_id}/commit')
        except StoreError: pass  # Read this exact ID; do not issue another commit.
        status = _poll(api, pending_id)
        _save(journal, 'submitted', details, submission_id=pending_id, status=status)
        if status in FAILED: raise SubmissionBlocked(f'Store processing stopped in {status}; a newer stable release is required')
        observed = _requested_pair(api, pending_id, details, template) if paired else {}
        return {'outcome': 'requested', 'tag': tag, 'submission_id': pending_id, 'status': status, **observed}
    except SubmissionBlocked as error:
        _warn(str(error))
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OSError, zipfile.BadZipFile):
        reason = 'Store submission validation failed; credentials, URLs and response contents were not logged'
        _warn(reason)
        raise SubmissionBlocked(reason) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-tag', required=True)
    parser.add_argument('--package-directory', type=Path, default=Path('store-output'))
    args = parser.parse_args()
    try: result = submit(args.release_tag, args.package_directory)
    except SubmissionBlocked: raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(f'Store 제출 결과: {json.dumps(result, sort_keys=True)}. 인증 완료와 실제 공개는 별도로 확인해야 합니다.\n')


if __name__ == '__main__': main()
