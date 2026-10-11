"""Submit a verified stable Store package; preserve uncertain writes across runs."""
from __future__ import annotations
import argparse
import base64
import copy
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


def _verify(tag, directory):
    version = _version(tag)
    if os.getenv('GITHUB_REPOSITORY') != REPOSITORY or os.getenv('GITHUB_REF') != 'refs/heads/main':
        raise SubmissionBlocked('Store writes require the owned main workflow')
    verify_checksums(directory)
    if sum(path.stat().st_size for path in directory.iterdir()) > LIMIT:
        raise SubmissionBlocked('Store artifacts exceed 96 MiB')
    details = json.loads((directory / 'store-provenance.json').read_text(encoding='utf-8'))
    source = directory.resolve().parent / '.work/store-source'
    if sum(path.stat().st_size for path in source.iterdir()) > LIMIT:
        raise SubmissionBlocked('Source release artifacts exceed 96 MiB')
    verify_checksums(source)
    provenance = json.loads((directory / 'source-provenance.json').read_text(encoding='utf-8'))
    if (provenance != json.loads((source / 'provenance.json').read_text(encoding='utf-8'))
            or details.get('storeAppId') != STORE_APP_ID or details.get('identity') != STORE_IDENTITY
            or details.get('version') != tag[1:] or details.get('unsigned') is not True
            or details.get('storeCertified') is not False
            or details.get('sourceCommit') != provenance.get('commit')
            or str(details.get('sourceRunId')) != str(provenance.get('runId'))
            or details.get('sourceMsixSha256') != provenance.get('sha256')
            or details.get('sourceRelease') != f'https://github.com/{REPOSITORY}/releases/tag/{tag}'
            or (directory / 'AppxManifest.xml').read_bytes() != manifest(STORE_IDENTITY, tag[1:]).encode()):
        raise SubmissionBlocked('Store package provenance does not match its validated source')
    run_id = _id(provenance['runId'])
    release = _gh('GET', f'releases/tags/{tag}')
    if release.get('draft') is not False or release.get('tag_name') != tag or _id(release['id']) != _id(details['sourceReleaseId']):
        raise SubmissionBlocked('Source release identity changed')
    run = _gh('GET', f'actions/runs/{run_id}')
    if run.get('event') != 'push' or run.get('head_branch') != tag:
        raise SubmissionBlocked('Store submission requires the stable tag push source run')
    jobs = [job for page in _gh('GET', f'actions/runs/{run_id}/jobs?per_page=100', pages=True) for job in page['jobs']]
    authorize_release(tag, provenance, run, _gh('GET', f'commits/{tag}')['sha'], jobs)
    with tempfile.TemporaryDirectory(prefix='store-recheck-', dir=source.parent) as temporary:
        original = source / prepare(source, Path(temporary) / 'payload')['msix']
    name = f'OpenGeul_{package_version(tag[1:])}_x64_store-unsigned.msix'
    package = directory / name
    if (details.get('package') != name or provenance.get('package') != original.name
            or verify_msix(original)['sha256'] != provenance['sha256']
            or verify_msix(package)['sha256'] != details.get('sha256')
            or verify_repackage(original, package, tag[1:]) != details.get('runtimeSha256')):
        raise SubmissionBlocked('Store package bytes or runtime parity changed')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr(name, package.read_bytes())
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
        if state.get(field) is not None and not re.fullmatch('[0-9a-f]{' + str(size) + '}', state[field]):
            raise SubmissionBlocked('Store state Issue has invalid source identity')
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
    text = 'Store automation state. Do not clear an attempted phase until its outcome is reconciled.\n'
    if warning: text += f'\n@ATLKR Store automation stopped: {warning}. Review Partner Center and this Actions run.\n'
    run_id = os.getenv('GITHUB_RUN_ID') or state.get('run_id')
    if run_id: text += f'\n[Actions run](https://github.com/{REPOSITORY}/actions/runs/{_id(run_id)})\n'
    if state.get('tag'): text += f'\n[Source release](https://github.com/{REPOSITORY}/releases/tag/{state["tag"]})\n'
    return text + '\n' + JOURNAL + json.dumps(state, sort_keys=True) + '\n-->\n'


def _save(journal, phase, details=None, *, warning=None, **fields):
    state = dict(journal['state'], phase=phase)
    if details:
        state.update(tag='v' + details['version'], release_id=_id(details['sourceReleaseId']),
                     run_id=_id(details['sourceRunId']), source_sha=details['sourceCommit'],
                     source_msix_sha256=details['sourceMsixSha256'])
    state.update(fields)
    expected = _journal_body(state, warning)
    item = _gh('PATCH', f'issues/{journal["number"]}', {'body': expected, 'state': 'open'})
    if not _owned_journal(item) or _id(item['number']) != journal['number'] or _journal_state(item['body']) != state:
        raise SubmissionBlocked('Store journal update was not acknowledged')
    fresh = _gh('GET', f'issues/{journal["number"]}')
    if not _owned_journal(fresh) or _id(fresh['number']) != journal['number'] or _journal_state(fresh['body']) != state:
        raise SubmissionBlocked('Store journal update could not be confirmed')
    journal['state'] = state


def _marker(details):
    return MARKER + json.dumps({key: details[key] for key in ('version', 'sourceReleaseId', 'sourceCommit', 'sourceMsixSha256')}, sort_keys=True)


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
    print(f'::error::{reason}')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(f'Store automation stopped: {reason}. The GitHub release remains available.\n')
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
        if state['phase'] == 'commit_attempted':
            status = _poll(api, _id(state.get('submission_id')))
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
        if (not isinstance(baseline.get('applicationPackages'), list) or not baseline['applicationPackages']
                or any(package.get('architecture', '').lower() != 'x64' for package in baseline['applicationPackages'])):
            raise SubmissionBlocked('Automatic updates require the published x64 package template')
        pending_id = _ref(app, 'pendingApplicationSubmission')
        if state['phase'] in {'draft_ready', 'submitted'} and state['submission_id'] not in {pending_id, baseline_id}:
            raise SubmissionBlocked('Recorded Store submission disappeared without acknowledged deletion or publication')
        target = version + (0,)
        if _packages_version(baseline) >= target: return {'outcome': 'superseded', 'tag': tag}
        pending = None
        if pending_id:
            if pending_id == baseline_id: raise SubmissionBlocked('Published submissions cannot be deleted')
            _, pending = api('GET', f'submissions/{pending_id}')
            if (_id(pending['id']) != pending_id or pending.get('status') == 'Published'
                    or pending.get('status') not in ACCEPTED | FAILED | {'None', 'PendingCommit', 'CommitStarted'}):
                raise SubmissionBlocked('Published or unowned pending submission cannot be replaced')
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
                _save(journal, 'submitted', details, submission_id=pending_id, status=status)
                if status in FAILED: raise SubmissionBlocked(f'Store processing stopped in {status}; a newer stable release is required')
                if (_id(pending['id']) != pending_id or _packages_version(pending) != target
                        or not any(package.get('fileName') == details['package'] and package.get('version') == package_version(tag[1:])
                                   and package.get('fileStatus') != 'PendingDelete' for package in pending['applicationPackages'])):
                    raise SubmissionBlocked('Existing Store request does not contain the verified target package version')
                return {'outcome': 'already_requested', 'tag': tag, 'submission_id': pending_id, 'status': status}
            owned = (matching or (state['phase'] == 'draft_ready' and state.get('submission_id') == pending_id
                     and state.get('tag') == tag and state.get('source_sha') == details['sourceCommit']
                     and state.get('source_msix_sha256') == details['sourceMsixSha256']))
            if not (owned and pending.get('status') == 'PendingCommit'):
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
        metadata = copy.deepcopy(baseline)
        for package in metadata['applicationPackages']:
            package['fileStatus'] = 'PendingDelete'
        metadata['applicationPackages'].append({'fileName': details['package'], 'fileStatus': 'PendingUpload',
                                               'minimumDirectXVersion': 'None', 'minimumSystemRam': 'None'})
        notes = [line for line in metadata.get('notesForCertification', '').splitlines() if not line.startswith(MARKER)]
        metadata['notesForCertification'] = '\n'.join(notes + [_marker(details)])
        for field in ('id', 'status', 'statusDetails', 'fileUploadUrl', 'friendlyName'):
            metadata.pop(field, None)
        _, updated = api('PUT', f'submissions/{pending_id}', metadata)
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
        return {'outcome': 'requested', 'tag': tag, 'submission_id': pending_id, 'status': status}
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
            stream.write(f'Store submission result: {json.dumps(result, sort_keys=True)}. Certification completion remains separate.\n')


if __name__ == '__main__': main()
