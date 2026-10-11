"""Read exactly the approved Store application/submission; emit a bounded whitelist."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

APP_ID = '9PJH0T3PHRMF'
SUBMISSION_ID = '1152921505702042424'
IDENTITY = '57904TaewonLiodLim.OpenGeul'
BASE = f'https://manage.devcenter.microsoft.com/v1.0/my/applications/{APP_ID}'
MAX_RESPONSE = 1024 * 1024
STATUSES = {'None', 'Canceled', 'PendingCommit', 'CommitStarted', 'CommitFailed',
            'PendingPublication', 'Publishing', 'Published', 'PublishFailed',
            'PreProcessing', 'PreProcessingFailed', 'Certification',
            'CertificationFailed', 'Release', 'ReleaseFailed', 'InProgress'}


def reference(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not re.fullmatch(r'[1-9][0-9]{0,24}', str(value.get('id', ''))):
        raise ValueError('Unrecognized submission reference')
    status = value.get('status')
    if status is not None and status not in STATUSES:
        raise ValueError('Unrecognized reference status')
    return {'id': str(value['id']), 'status': status}


def pricing_summary(pricing):
    pricing = pricing if isinstance(pricing, dict) else {}
    base = pricing.get('priceId')
    base_tier = isinstance(base, str) and re.fullmatch(r'Tier[1-9][0-9]*', base) is not None
    free_base = True if base == 'Free' else False if base_tier else None
    overrides = pricing.get('marketSpecificPricings')
    counts = None
    if isinstance(overrides, dict):
        counts = dict.fromkeys(('Free', 'Base', 'NotAvailable', 'recognizedTier', 'unknown'), 0)
        for value in overrides.values():
            if isinstance(value, str) and value in ('Free', 'Base', 'NotAvailable'):
                counts[value] += 1
            elif isinstance(value, str) and re.fullmatch(r'Tier[1-9][0-9]*', value):
                counts['recognizedTier'] += 1
            else:
                counts['unknown'] += 1
    available_free = None
    if counts is not None and counts['unknown'] == 0 and free_base is not None:
        available_free = free_base and counts['recognizedTier'] == 0
    return {'freeBasePrice': free_base, 'marketOverrideCounts': counts,
            'availableMarketsFree': available_free}


def observe(opener, token, now=None):
    def get(url):
        request = urllib.request.Request(url, method='GET', headers={
            'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        with opener.open(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError('Bounded response exceeded')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('Unrecognized response schema')
        return value

    app = get(BASE)
    if app.get('id') != APP_ID or app.get('packageIdentityName') != IDENTITY:
        raise ValueError('Application identity mismatch')
    refs = {field: reference(app.get(field)) for field in (
        'lastPublishedApplicationSubmission', 'pendingApplicationSubmission', 'lastSubmission')}
    submission = get(BASE + '/submissions/' + SUBMISSION_ID)
    status = submission.get('status')
    mode = submission.get('targetPublishMode')
    if str(submission.get('id')) != SUBMISSION_ID or status not in STATUSES or mode not in {'Immediate', 'Manual', 'SpecificDate'}:
        raise ValueError('Submission identity or status mismatch')
    packages = submission.get('applicationPackages')
    if not isinstance(packages, list) or len(packages) > 128:
        raise ValueError('Unrecognized packages')
    versions = []
    for package in packages:
        version = package.get('version') if isinstance(package, dict) else None
        if not isinstance(version, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', version) or any(int(part) > 65535 for part in version.split('.')):
            raise ValueError('Unrecognized package version')
        versions.append(version)
    url = submission.get('fileUploadUrl')
    if url is not None and not isinstance(url, str):
        raise ValueError('Unrecognized upload URL field')
    expiry_valid = None
    if url:
        try:
            expiry = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get('se', [])
            if len(expiry) == 1:
                instant = datetime.fromisoformat(expiry[0].replace('Z', '+00:00'))
                if instant.tzinfo is not None:
                    expiry_valid = instant > (now or datetime.now(timezone.utc))
        except (ValueError, OverflowError):
            pass
    return {'observation': 'read-only', 'appId': APP_ID, 'packageIdentityName': IDENTITY,
            **refs, 'existingSubmission': {'id': SUBMISSION_ID, 'status': status,
                'targetPublishMode': mode, 'has_fileUploadUrl': bool(url),
                'fileUploadExpiryValid': expiry_valid,
                'expiryCheckScope': 'timestamp only; not signature or upload authorization',
                'packageCount': len(packages), 'packageVersions': versions,
                **pricing_summary(submission.get('pricing'))}}


def report_api_replacement_blocker(result):
    """Report only the fixed verified hold; never interpolate raw API fields."""
    if (not isinstance(result, dict) or result.get('observation') != 'read-only'
            or result.get('appId') != APP_ID or result.get('packageIdentityName') != IDENTITY
            or 'lastPublishedApplicationSubmission' not in result
            or result['lastPublishedApplicationSubmission'] is not None):
        return False
    pending = result.get('pendingApplicationSubmission')
    existing = result.get('existingSubmission')
    if (not isinstance(pending, dict) or pending.get('id') != SUBMISSION_ID
            or not isinstance(existing, dict) or existing.get('id') != SUBMISSION_ID
            or existing.get('status') not in {'Certification', 'PendingPublication', 'Release'}
            or pending.get('status') not in {None, existing['status']}
            or existing.get('targetPublishMode') != 'Manual'
            or existing.get('has_fileUploadUrl') is not False):
        return False
    print('::warning title=Store API replacement path unresolved::'
          'The fixed initial Manual submission has no Published baseline or upload URL; '
          'a supported API-only replacement and recovery path remains unverified. '
          'No Store mutation was attempted.')
    summary = ('### Store API replacement path unresolved\n\n'
               f'- App: `{APP_ID}`; pending submission: `{SUBMISSION_ID}`.\n'
               f'- Verified status: `{existing["status"]}`; publication mode: `Manual`.\n'
               '- Published baseline: absent; package upload URL: absent.\n\n'
               'The observer performed only the fixed application/submission GETs after OAuth. '
               'Read access does not establish write or cancellation acceptance. '
               'This is an unresolved safe API path, not a universal REST prohibition. '
               'Preserve this submission and the Manual hold; do not publish the historical package '
               'or delete the initial record as a probe. No Store mutation was attempted.\n')
    if len(summary.encode('utf-8')) > 2048:
        raise ValueError('Fixed Store blocker summary exceeds 2 KiB')
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        try:
            with open(path, 'a', encoding='utf-8') as stream:
                stream.write(summary)
        except OSError:
            print('::warning title=Store blocker summary unavailable::'
                  'The bounded summary could not be written; inspect the sanitized observation artifact.')
    return True


def load_authenticate():
    helper = Path(__file__).resolve().parents[1] / '.store-auth-source' / 'scripts'
    if not (helper / 'check_store_api.py').is_file():
        raise ValueError('Pinned authentication helper missing')
    sys.path.insert(0, str(helper))
    from check_store_api import authenticate
    return authenticate


def run_observation():
    stage = 'workflow-scope'
    try:
        if os.environ.get('GITHUB_REPOSITORY') != 'ATLKR/OpenGeul' or os.environ.get('GITHUB_REF') != 'refs/heads/diagnostic/msix-manifest-38132094391':
            raise ValueError('Unexpected workflow scope')
        stage = 'authentication'
        opener, token = load_authenticate()()
        stage = 'fixed-resource-get'
        return observe(opener, token), 0
    except Exception as error:
        return {'observation': 'unverified', 'stage': stage,
                'httpStatus': error.code if isinstance(error, urllib.error.HTTPError) else None,
                'reason': 'Access or validation failed; credentials, URLs and response contents omitted'}, 1


def self_check():
    from contextlib import redirect_stdout, redirect_stderr
    from unittest import mock
    app = {'id': APP_ID, 'packageIdentityName': IDENTITY,
           'lastPublishedApplicationSubmission': None,
           'pendingApplicationSubmission': {'id': SUBMISSION_ID, 'status': 'Certification'},
           'lastSubmission': None, 'privateResponse': 'SECRET_RESPONSE'}
    submission = {'id': SUBMISSION_ID, 'status': 'Certification', 'targetPublishMode': 'Manual',
                  'fileUploadUrl': 'https://example.blob.core.windows.net/path?sig=SECRET_SAS&se=2099-01-01T00%3A00%3A00Z',
                  'applicationPackages': [{'version': '1.1.1.0', 'privatePackageField': 'SECRET_PACKAGE'}],
                  'pricing': {'priceId': 'Free', 'marketSpecificPricings': {'KR': 'Base'}},
                  'statusDetails': {'private': 'SECRET_RESPONSE'}}
    class Opener:
        def __init__(self, application, existing):
            self.responses = [application, existing]
            self.calls = []
        def open(self, request, timeout):
            assert request.get_method() == 'GET' and timeout == 30
            self.calls.append(request.full_url)
            return io.BytesIO(json.dumps(self.responses[len(self.calls) - 1]).encode())
    opener = Opener(app, submission)
    result = observe(opener, 'SECRET_OAUTH', datetime(2026, 10, 11, tzinfo=timezone.utc))
    assert opener.calls == [BASE, BASE + '/submissions/' + SUBMISSION_ID]
    assert result['existingSubmission']['has_fileUploadUrl'] is True
    assert result['existingSubmission']['fileUploadExpiryValid'] is True
    assert result['existingSubmission']['freeBasePrice'] is True
    assert result['lastPublishedApplicationSubmission'] is None
    assert 'SECRET_' not in json.dumps(result) and '"fileUploadUrl"' not in json.dumps(result)
    pricing_cases = [
        ({'priceId': 'Free', 'marketSpecificPricings': {'SECRET_MARKET_A': 'Free', 'SECRET_MARKET_B': 'Base', 'SECRET_MARKET_C': 'NotAvailable'}}, True,
         {'Free': 1, 'Base': 1, 'NotAvailable': 1, 'recognizedTier': 0, 'unknown': 0}),
        ({'priceId': 'Free', 'marketSpecificPricings': {'SECRET_MARKET': 'Tier12'}}, False,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 1, 'unknown': 0}),
        ({'priceId': 'Free', 'marketSpecificPricings': {'SECRET_MARKET': {'priceId': 'Free'}}}, None,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 0, 'unknown': 1}),
        ({'priceId': 'Free'}, None, None),
        ({'priceId': 'Free', 'marketSpecificPricings': {}}, True,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 0, 'unknown': 0}),
        ({'priceId': 'Tier1', 'marketSpecificPricings': {}}, False,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 0, 'unknown': 0}),
        ({'priceId': 'Free', 'marketSpecificPricings': {'SECRET_MARKET_A': 'Tier1', 'SECRET_MARKET_B': 'SECRET_UNKNOWN'}}, None,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 1, 'unknown': 1}),
        ({'priceId': 'Free', 'marketSpecificPricings': {'SECRET_MARKET': 'Tier0'}}, None,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 0, 'unknown': 1}),
        ({'priceId': 'SECRET_UNKNOWN', 'marketSpecificPricings': {}}, None,
         {'Free': 0, 'Base': 0, 'NotAvailable': 0, 'recognizedTier': 0, 'unknown': 0}),
    ]
    for pricing, available_free, counts in pricing_cases:
        summary = observe(Opener(app, {**submission, 'pricing': pricing}), 'SECRET_OAUTH')['existingSubmission']
        assert 'availableMarketsFree' in summary, 'Pricing availability summary is missing'
        assert summary['availableMarketsFree'] is available_free
        assert summary['marketOverrideCounts'] == counts
        assert 'marketOverridesFreeOrBase' not in summary
        assert 'SECRET_' not in json.dumps(summary) and '"Tier12"' not in json.dumps(summary)
    submission['fileUploadUrl'] = None
    assert observe(Opener(app, submission), 'SECRET_OAUTH')['existingSubmission']['has_fileUploadUrl'] is False
    submission['fileUploadUrl'] = 'https://example.blob.core.windows.net/?sig=SECRET_SAS&se=2000-01-01T00%3A00%3A00Z'
    assert observe(Opener(app, submission), 'SECRET_OAUTH')['existingSubmission']['fileUploadExpiryValid'] is False
    for invalid in ({**app, 'id': 'SECRET_RESPONSE'}, {**app, 'packageIdentityName': 'SECRET_RESPONSE'}):
        opener = Opener(invalid, submission)
        try:
            observe(opener, 'SECRET_OAUTH')
        except ValueError:
            assert len(opener.calls) == 1
        else:
            raise AssertionError('Mismatched app must block the submission GET')
    error = urllib.error.HTTPError(BASE, 403, 'SECRET_RESPONSE', {}, io.BytesIO(b'SECRET_RESPONSE'))
    with mock.patch.dict(os.environ, {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_REF': 'refs/heads/diagnostic/msix-manifest-38132094391'}), mock.patch.dict(run_observation.__globals__, {'load_authenticate': lambda: lambda: (_ for _ in ()).throw(error)}):
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            failed, exit_code = run_observation()
        assert exit_code == 1 and failed['httpStatus'] == 403
        assert 'SECRET_' not in json.dumps(failed) and not stdout.getvalue() and not stderr.getvalue()
    class FailedGet:
        def open(self, request, timeout):
            assert request.get_method() == 'GET' and request.full_url == BASE and timeout == 30
            raise error
    with mock.patch.dict(os.environ, {'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_REF': 'refs/heads/diagnostic/msix-manifest-38132094391'}), mock.patch.dict(run_observation.__globals__, {'load_authenticate': lambda: lambda: (FailedGet(), 'SECRET_OAUTH')}):
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            failed, exit_code = run_observation()
        assert exit_code == 1 and failed['stage'] == 'fixed-resource-get' and failed['httpStatus'] == 403
        assert 'SECRET_' not in json.dumps(failed) and not stdout.getvalue() and not stderr.getvalue()
    import tempfile
    blocked = {**result, 'pendingApplicationSubmission': {'id': SUBMISSION_ID, 'status': None},
               'existingSubmission': {**result['existingSubmission'], 'has_fileUploadUrl': False}}
    with tempfile.TemporaryDirectory() as temporary:
        summary_path = Path(temporary) / 'summary.md'
        with mock.patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary_path)}):
            with redirect_stdout(io.StringIO()) as stdout:
                assert report_api_replacement_blocker(blocked) is True
            summary = summary_path.read_text(encoding='utf-8')
            assert stdout.getvalue().count('::warning') == 1 and len(summary.encode('utf-8')) <= 2048
            assert 'SECRET_' not in stdout.getvalue() + summary
            before = summary_path.read_bytes()
            with redirect_stdout(io.StringIO()) as stdout:
                assert report_api_replacement_blocker({**blocked, 'observation': 'unverified'}) is False
                assert report_api_replacement_blocker(result) is False  # Upload URL was present.
            assert not stdout.getvalue() and summary_path.read_bytes() == before
            # A held Release/Manual state still has no verified Published baseline
            # or upload path. Exercise the actual fixed GET -> sanitized report flow.
            release_app = {**app, 'pendingApplicationSubmission': {'id': SUBMISSION_ID, 'status': 'Release'}}
            release_submission = {**submission, 'status': 'Release', 'fileUploadUrl': None,
                                  'pricing': {'priceId': 'Free', 'marketSpecificPricings':
                                              {'SECRET_MARKET_A': 'NotAvailable', 'SECRET_MARKET_B': 'NotAvailable'}}}
            release_opener = Opener(release_app, release_submission)
            release = observe(release_opener, 'SECRET_OAUTH')
            assert release_opener.calls == [BASE, BASE + '/submissions/' + SUBMISSION_ID]
            assert release['existingSubmission']['packageVersions'] == ['1.1.1.0']
            assert release['existingSubmission']['marketOverrideCounts']['NotAvailable'] == 2
            with redirect_stdout(io.StringIO()) as stdout:
                assert report_api_replacement_blocker(release) is True
            added = summary_path.read_text(encoding='utf-8')[len(before.decode('utf-8')):]
            assert stdout.getvalue().count('::warning') == 1
            assert 'Verified status: `Release`' in added and len(added.encode('utf-8')) <= 2048
            assert 'not a universal REST prohibition' in added
            assert 'SECRET_' not in stdout.getvalue() + added and 'fileUploadUrl' not in added
            before = summary_path.read_bytes()
            rejected = [
                {**release, 'lastPublishedApplicationSubmission': {'id': SUBMISSION_ID, 'status': 'Published'}},
                {**release, 'appId': 'OTHER_APP'},
                {**release, 'packageIdentityName': 'OTHER_IDENTITY'},
                {**release, 'pendingApplicationSubmission': {'id': '123', 'status': 'Release'}},
                {**release, 'existingSubmission': {**release['existingSubmission'], 'id': '123'}},
                {**release, 'existingSubmission': {**release['existingSubmission'], 'targetPublishMode': 'Immediate'}},
                {**release, 'existingSubmission': {**release['existingSubmission'], 'has_fileUploadUrl': True}},
                {**release, 'pendingApplicationSubmission': {'id': SUBMISSION_ID, 'status': 'Published'},
                 'existingSubmission': {**release['existingSubmission'], 'status': 'Published'}},
                {**release, 'pendingApplicationSubmission': {'id': SUBMISSION_ID, 'status': 'Publishing'},
                 'existingSubmission': {**release['existingSubmission'], 'status': 'Publishing'}},
            ]
            for candidate in rejected:
                with redirect_stdout(io.StringIO()) as stdout:
                    assert report_api_replacement_blocker(candidate) is False
                assert not stdout.getvalue() and summary_path.read_bytes() == before
    print('Store observation self-check passed: exact GETs, identity, expiry and secret-free success/failure output.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    result, code = run_observation()
    text = json.dumps(result, sort_keys=True) + '\n'
    if len(text.encode('utf-8')) > 8192:
        raise ValueError('Sanitized observation exceeds 8 KiB')
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    if code == 0:
        report_api_replacement_blocker(result)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
