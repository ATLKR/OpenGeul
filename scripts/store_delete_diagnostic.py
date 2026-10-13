"""One reviewed draft DELETE with exact guards and sanitized response evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from check_store_api import authenticate
from store_pending_observe import APP_ID, IDENTITY, BASE, decode, require, reference, fingerprint, summary
from store_status_diagnostics import item, sanitize

REF = 'refs/heads/diagnostic/store-delete-reason-113'
PENDING = '1152921505702100805'
PUBLISHED = '1152921505702042424'
SEMANTIC_SHA = '51f2a2a519cf4378b1adba9ba41d679288fca972b4cd6d55969a417fe046db01'
MAX_GET = 1024 * 1024
MAX_BODY = 64 * 1024
MAX_OUTPUT = 128 * 1024
RUNS_PATH = 'repos/ATLKR/OpenGeul/actions/workflows/store-package.yml/runs?branch=diagnostic/store-delete-reason-113&event=workflow_dispatch&per_page=100'
ISSUE_PATH = 'repos/ATLKR/OpenGeul/issues/20'
EXPECTED_JOURNAL = {
    'app_id': APP_ID, 'phase': 'delete_attempted', 'tag': 'v1.1.3',
    'source_sha': '859f676167b258a7a6a57ecdfcb0e224338de01a',
    'release_id': '410953892', 'run_id': '38294374822',
    'submission_id': PENDING, 'adopted_pending_id': PENDING, 'deleted_id': PENDING,
    'baseline_id': PUBLISHED,
    'adopted_baseline_semantic_sha256': SEMANTIC_SHA,
    'adopted_draft_semantic_sha256': SEMANTIC_SHA,
    'adopted_latest_draft_semantic_sha256': SEMANTIC_SHA,
    'source_asset_fingerprint_sha256': 'fa5e0d0857d7e5d3331c731d408cea0aad9656f55ae25e68b70c4504c01cd11e',
    'source_msix_sha256_by_arch': {
        'x64': '2901fbc514dbc868083c8bb50b8a0eedd4bbc0c9cf703a96062de8da9f8d3655',
        'arm64': 'fd5af011629f4026a3c276d932d9453c38f1ac6d9d590163b03be81030ed2ace'},
    'store_msix_sha256_by_arch': {
        'x64': '76cbf587c649aea14f83bbbd717a85f505c3586781a7927400a4949ddeb379f5',
        'arm64': '31a2dfb8e3b42f2e41b10f7ef542f4accb353e6d9c639c5638c02d4d808f2299'}}


def workflow_scope():
    require(os.getenv('GITHUB_REPOSITORY') == 'ATLKR/OpenGeul'
            and os.getenv('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.getenv('GITHUB_REF') == REF and os.getenv('GITHUB_RUN_ATTEMPT') == '1'
            and os.getenv('GITHUB_ACTOR') == 'ATLKR' and os.getenv('GITHUB_JOB') == 'delete-diagnostic'
            and os.getenv('GITHUB_WORKFLOW_REF') == 'ATLKR/OpenGeul/.github/workflows/store-package.yml@' + REF
            and os.getenv('DELETE_PENDING_ID') == PENDING
            and re.fullmatch(r'[0-9a-f]{40}', os.getenv('GITHUB_SHA', ''))
            and re.fullmatch(r'[1-9][0-9]{0,24}', os.getenv('GITHUB_RUN_ID', '')))


def gh_read(path):
    require(path in {RUNS_PATH, ISSUE_PATH})
    result = subprocess.run(['gh', 'api', '--method', 'GET', path],
                            capture_output=True, timeout=30, check=False)
    require(result.returncode == 0 and 0 < len(result.stdout) <= MAX_GET)
    return result.stdout


def check_runs(raw):
    value = decode(raw)
    runs = value.get('workflow_runs')
    count = value.get('total_count')
    # A full page is ambiguous. Refuse rather than silently omit a prior dispatch.
    require(type(count) is int and 0 < count < 100 and isinstance(runs, list) and len(runs) == count)
    require(all(isinstance(run, dict) for run in runs))
    matches = [run for run in runs if run.get('head_sha') == os.getenv('GITHUB_SHA')]
    require(len(matches) == 1)
    run = matches[0]
    require(type(run.get('id')) is int and str(run['id']) == os.getenv('GITHUB_RUN_ID')
            and run.get('head_branch') == REF.removeprefix('refs/heads/')
            and run.get('event') == 'workflow_dispatch' and run.get('path') == '.github/workflows/store-package.yml'
            and type(run.get('run_attempt')) is int and run['run_attempt'] == 1
            and run.get('repository', {}).get('full_name') == 'ATLKR/OpenGeul'
            and run.get('repository', {}).get('private') is False)
    for key in ('actor', 'triggering_actor'):
        require(isinstance(run.get(key), dict) and run[key].get('login') == 'ATLKR' and run[key].get('type') == 'User')


def parse_journal(raw):
    issue = decode(raw)
    require(issue.get('number') == 20 and type(issue.get('number')) is int
            and issue.get('id') == 5819766913 and type(issue.get('id')) is int
            and issue.get('title') == 'OpenGeul Store submission state (' + APP_ID + ')'
            and issue.get('state') == 'open' and 'pull_request' not in issue
            and issue.get('html_url') == 'https://github.com/ATLKR/OpenGeul/issues/20'
            and issue.get('url') == 'https://api.github.com/repos/ATLKR/OpenGeul/issues/20')
    user = issue.get('user')
    require(isinstance(user, dict) and user.get('login') == 'github-actions[bot]'
            and user.get('type') == 'Bot' and user.get('id') == 41898282)
    body = issue.get('body')
    marker = '<!-- opengeul-store-state\n'
    require(isinstance(body, str) and len(body.encode()) <= MAX_BODY and body.count(marker) == 1)
    state_text, end = body.split(marker, 1)[1].split('\n-->', 1)
    require(not end.strip())
    state = decode(state_text.encode())
    require(state == EXPECTED_JOURNAL)
    return state


def guarded_summary(value, expected, status):
    selected = summary(value, expected)
    require(selected['status'] == status and selected['draftContentSha256'] == SEMANTIC_SHA
            and selected['targetPublishMode'] == 'Manual' and selected['freeBasePrice']
            and selected['availableMarketsFree'] and selected['mandatoryUpdate'] is False
            and not selected['uploadDestinationPresent']
            and selected['packages'] == [{'architecture': 'x64', 'version': '1.1.1.0', 'fileStatus': 'Uploaded'}])
    return selected


def safe_item(value, secrets):
    # Keep valid codes even when the service uses object-valued details.
    projected = {key: value[key] for key in ('code', 'errorCode') if key in value}
    message = value.get('message', value.get('details'))
    if isinstance(message, str):
        message = re.sub(r'(?i)(["\']?(?:authorization|access_token|token|client_secret|password|sig)["\']?\s*[=:]\s*)(["\'])(.*?)\2',
                         r'\1[redacted-auth]', message)
        for secret in secrets:
            if isinstance(secret, str) and secret:
                encoded = urllib.parse.quote(secret, safe='')
                if encoded != secret:
                    message = re.sub(re.escape(encoded), '[redacted]', message, flags=re.IGNORECASE)
        projected['message'] = sanitize(message, secrets)
    return item(projected, secrets)


def response_receipt(status, raw, secrets):
    if raw is None:
        return {'httpStatus': status, 'responseBodyUnavailable': True, 'errors': [], 'projection': 'unavailable'}
    truncated = len(raw) > MAX_BODY
    body = raw[:MAX_BODY]
    result = {'httpStatus': status, 'responseBodyUnavailable': False, 'responseBytesCaptured': len(body),
              'responseTruncated': truncated, 'responseSha256': hashlib.sha256(body).hexdigest(),
              'responseSha256Scope': 'prefix' if truncated else 'full', 'errors': [],
              'projection': 'truncated' if truncated else 'empty' if not body else 'malformed'}
    if truncated or not body:
        return result
    try:
        parsed = decode(body)
    except (ValueError, TypeError, UnicodeError):
        return result
    result['projection'] = 'parsed'
    def visit(value, depth=0):
        if depth > 4 or len(result['errors']) >= 16 or not isinstance(value, dict):
            return
        if any(key in value for key in ('code', 'errorCode', 'message')) or isinstance(value.get('details'), str):
            result['errors'].append(safe_item(value, secrets))
        for key in ('error', 'innererror', 'innerError', 'details'):
            visit(value.get(key), depth + 1)
        errors = value.get('errors')
        if isinstance(errors, list):
            for entry in errors[:16]:
                visit(entry, depth + 1)
    visit(parsed)
    return result


def write_json(output, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    require(len(raw) <= MAX_OUTPUT)
    output.write(raw)
    output.flush()
    os.fsync(output.fileno())


def exclusive_file(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(descriptor, 'wb')


def probe(opener, token, journal, directory, secrets=()):
    directory = Path(directory)
    require(not directory.exists() and not directory.is_symlink())
    directory.mkdir()
    secrets = tuple(secrets) + (token,)
    result = {'formatVersion': 1, 'appId': APP_ID, 'pendingId': PENDING, 'publishedId': PUBLISHED,
              'outcome': 'guard-rejected', 'stage': 'journal', 'storeMutationsAttempted': False,
              'deletionAcknowledged': False, 'deletionReconciled': False,
              'journalMutationPerformed': False, 'storeSubmitted': False, 'gets': [],
              'execution': {'commit': os.getenv('GITHUB_SHA'), 'runId': os.getenv('GITHUB_RUN_ID'),
                            'attempt': os.getenv('GITHUB_RUN_ATTEMPT')}}
    # Reserve and validate the final destination before any Store mutation.
    with exclusive_file(directory / 'delete-diagnostic.json') as final:
        def get(endpoint, role, allow_404=False):
            require(endpoint in {BASE, BASE + '/submissions/' + PENDING, BASE + '/submissions/' + PUBLISHED})
            request = urllib.request.Request(endpoint, method='GET', headers={
                'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
            try:
                with opener.open(request, timeout=30) as response:
                    require(response.status == 200)
                    raw = response.read(MAX_GET + 1)
            except urllib.error.HTTPError as error:
                result['gets'].append({'role': role, 'httpStatus': error.code})
                error.close()
                require(allow_404 and error.code == 404)
                return None
            value = decode(raw)
            result['gets'].append({'role': role, 'httpStatus': 200, 'responseBytes': len(raw),
                                   'responseSha256': hashlib.sha256(raw).hexdigest()})
            return value

        def app_guard(app, pending):
            require(app.get('id') == APP_ID and app.get('packageIdentityName') == IDENTITY
                    and 'pendingApplicationSubmission' in app and 'lastPublishedApplicationSubmission' in app
                    and reference(app['pendingApplicationSubmission']) == pending
                    and reference(app['lastPublishedApplicationSubmission']) == PUBLISHED)

        try:
            require(journal == EXPECTED_JOURNAL)
            result['journalPhase'] = 'delete_attempted'
            result['journalStateSha256'] = fingerprint(journal)
            result['stage'] = 'fixed-pre-delete-gets'
            app_guard(get(BASE, 'app-before'), PENDING)
            result['pendingBefore'] = guarded_summary(get(BASE + '/submissions/' + PENDING, 'pending-before'), PENDING, 'PendingCommit')
            result['publishedBefore'] = guarded_summary(get(BASE + '/submissions/' + PUBLISHED, 'published-before'), PUBLISHED, 'Published')
            with exclusive_file(directory / 'pre-delete-intent.json') as intent:
                write_json(intent, {**result, 'deleteCallPlanned': True, 'stage': 'local-delete-intent'})
            result['stage'] = 'one-delete'
            result['storeMutationsAttempted'] = True
            request = urllib.request.Request(BASE + '/submissions/' + PENDING, method='DELETE', data=None,
                headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Content-Type': 'application/json'})
            status = None
            raw = None
            try:
                with opener.open(request, timeout=30) as response:
                    status = response.status
                    raw = response.read(MAX_BODY + 1)
            except urllib.error.HTTPError as error:
                status = error.code
                try:
                    raw = error.read(MAX_BODY + 1)
                except (OSError, TimeoutError, ValueError):
                    pass
                finally:
                    error.close()
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                pass
            result['deleteResponse'] = response_receipt(status, raw, secrets)
            result['outcome'] = 'delete-rejected' if status is not None and not 200 <= status < 300 else 'delete-unacknowledged'
            if status is not None and 200 <= status < 300 and raw == b'':
                result['deletionAcknowledged'] = True
                result['outcome'] = 'delete-acknowledged-reconciliation-incomplete'
                result['stage'] = 'post-delete-reconciliation-gets'
                app_guard(get(BASE, 'app-after'), None)
                require(get(BASE + '/submissions/' + PENDING, 'old-pending-after', allow_404=True) is None)
                guarded_summary(get(BASE + '/submissions/' + PUBLISHED, 'published-after'), PUBLISHED, 'Published')
                result['deletionReconciled'] = True
                result['outcome'] = 'delete-acknowledged-and-reconciled'
        except Exception:
            # Never expose transport exceptions, arbitrary service fields, or credentials.
            result['verificationFailure'] = True
        write_json(final, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    stage = 'workflow-scope'
    probe_started = False
    try:
        workflow_scope()
        require(not args.output_dir.exists() and not args.output_dir.is_symlink())
        stage = 'first-dispatch-run-history'
        check_runs(gh_read(RUNS_PATH))
        stage = 'fixed-issue20-read'
        journal = parse_journal(gh_read(ISSUE_PATH))
        stage = 'authentication'
        opener, token = authenticate()
        secrets = [value for key, value in os.environ.items()
                   if re.search(r'(?i)(SECRET|TOKEN|PASSWORD|(?:^|_)KEY(?:_|$))', key)]
        probe_started = True
        result = probe(opener, token, journal, args.output_dir, secrets)
    except Exception:
        possible_write = probe_started and (args.output_dir / 'pre-delete-intent.json').exists()
        result = {'outcome': 'delete-unacknowledged' if possible_write else 'guard-rejected', 'stage': stage, 'storeMutationsAttempted': possible_write,
                  'deletionAcknowledged': False, 'deletionReconciled': False, 'journalMutationPerformed': False,
                  'reason': 'Scope, authentication, or strict response verification failed; raw values withheld.'}
        if not args.output_dir.exists() and not args.output_dir.is_symlink():
            args.output_dir.mkdir()
            with exclusive_file(args.output_dir / 'delete-diagnostic.json') as output:
                write_json(output, result)
    print(json.dumps({key: result[key] for key in ('outcome', 'storeMutationsAttempted', 'deletionAcknowledged', 'deletionReconciled')}, sort_keys=True))
    return 0 if result['deletionReconciled'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
