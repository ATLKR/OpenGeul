"""공개된 Store 버전만 관측하고 공개 메타데이터 한 파일을 갱신한다."""
from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

from check_store_api import authenticate
from store_package import STORE_APP_ID, STORE_IDENTITY

STORE_URL = 'https://apps.microsoft.com/detail/' + STORE_APP_ID
BASE = 'https://manage.devcenter.microsoft.com/v1.0/my/applications/' + STORE_APP_ID
CONTENTS = 'contents/website/store-release.json'
MAX_PUBLIC = 8192
MAX_RESPONSE = 1024 * 1024
FIELDS = {'formatVersion', 'appId', 'status', 'version', 'storeUrl', 'submissionId'}


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('중복 JSON 필드는 허용하지 않습니다')
        value[key] = item
    return value


def _json(data, limit):
    if not isinstance(data, bytes) or len(data) > limit:
        raise ValueError('JSON 크기 제한을 초과했습니다')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('잘못된 JSON 숫자입니다')))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('올바른 UTF-8 JSON이 아닙니다') from None


def _version(value):
    if (not isinstance(value, str)
            or re.fullmatch(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3}', value) is None):
        raise ValueError('Store 버전 형식이 올바르지 않습니다')
    parts = tuple(int(part) for part in value.split('.'))
    if any(part > 65535 for part in parts):
        raise ValueError('Store 버전 범위를 초과했습니다')
    return parts


def _submission_id(value):
    if not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,24}', value) is None:
        raise ValueError('Store 제출 ID가 올바르지 않습니다')
    return value


def validate_metadata(value):
    if (not isinstance(value, dict) or set(value) != FIELDS
            or type(value.get('formatVersion')) is not int or value['formatVersion'] != 1
            or value.get('appId') != STORE_APP_ID or value.get('status') != 'Published'
            or value.get('storeUrl') != STORE_URL):
        raise ValueError('공개 Store 메타데이터 계약이 일치하지 않습니다')
    _version(value['version'])
    _submission_id(value['submissionId'])
    return dict(value)


def decode_metadata(data):
    return validate_metadata(_json(data, MAX_PUBLIC))


def encode_metadata(value):
    data = (json.dumps(validate_metadata(value), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(data) > MAX_PUBLIC:
        raise ValueError('공개 Store 메타데이터 크기를 초과했습니다')
    return data


def _reference(app):
    if (not isinstance(app, dict) or app.get('id') != STORE_APP_ID
            or app.get('packageIdentityName') != STORE_IDENTITY['name']
            or app.get('publisherName') != STORE_IDENTITY['publisher']):
        raise ValueError('Store 앱 신원이 일치하지 않습니다')
    reference = app.get('lastPublishedApplicationSubmission')
    if not isinstance(reference, dict) or reference.get('status') not in (None, 'Published'):
        raise ValueError('공개된 Store 제출 참조가 없습니다')
    return _submission_id(reference.get('id'))


def metadata_from_store(app, submission):
    submission_id = _reference(app)
    if (not isinstance(submission, dict) or submission.get('id') != submission_id
            or submission.get('status') != 'Published' or submission.get('targetPublishMode') != 'Manual'):
        raise ValueError('일치하는 수동 공개 Store 제출이 아닙니다')
    pricing = submission.get('pricing')
    if (not isinstance(pricing, dict) or pricing.get('priceId') != 'Free'
            or not isinstance(pricing.get('marketSpecificPricings'), dict)
            or any(not isinstance(price, str) or price not in ('Free', 'Base', 'NotAvailable')
                   for price in pricing['marketSpecificPricings'].values())):
        raise ValueError('무료 Store 가격 계약이 일치하지 않습니다')
    packages = submission.get('applicationPackages')
    if not isinstance(packages, list) or not 1 <= len(packages) <= 128:
        raise ValueError('Store 패키지 목록이 올바르지 않습니다')
    versions = set()
    for package in packages:
        if (not isinstance(package, dict) or not isinstance(package.get('architecture'), str)
                or package['architecture'].lower() != 'x64' or package.get('fileStatus') != 'Uploaded'):
            raise ValueError('공개 x64 Store 패키지가 아닙니다')
        _version(package.get('version'))
        versions.add(package['version'])
    if len(versions) != 1:
        raise ValueError('공개 Store 패키지 버전이 하나로 일치하지 않습니다')
    return validate_metadata({'formatVersion': 1, 'appId': STORE_APP_ID, 'status': 'Published',
                              'version': versions.pop(), 'storeUrl': STORE_URL, 'submissionId': submission_id})


def observe(opener, token):
    def get(url):
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
                                                      'Accept': 'application/json'}, method='GET')
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError('Store GET 응답 상태가 올바르지 않습니다')
            value = _json(response.read(MAX_RESPONSE + 1), MAX_RESPONSE)
        if not isinstance(value, dict):
            raise ValueError('Store GET 응답 형식이 올바르지 않습니다')
        return value
    app = get(BASE)
    submission_id = _reference(app)
    return metadata_from_store(app, get(BASE + '/submissions/' + submission_id))


def github(method, path, data=None):
    if (method, path) not in (('GET', CONTENTS + '?ref=main'), ('PUT', CONTENTS)):
        raise ValueError('허용된 공개 메타데이터 경로가 아닙니다')
    command = ['gh', 'api', '--hostname', 'github.com', '--method', method, 'repos/ATLKR/OpenGeul/' + path]
    body = None
    if data is not None:
        command += ['--input', '-']
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    try:
        result = subprocess.run(command, input=body, capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError('GitHub 메타데이터 요청에 실패했습니다')
        value = _json(result.stdout, MAX_RESPONSE)
        if not isinstance(value, dict):
            raise ValueError('GitHub 응답 형식이 올바르지 않습니다')
        return value
    except (OSError, subprocess.SubprocessError):
        raise ValueError('GitHub 메타데이터 요청에 실패했습니다') from None


def synchronize(candidate, request=github):
    candidate = validate_metadata(candidate)
    current = request('GET', CONTENTS + '?ref=main')
    if (not isinstance(current, dict) or current.get('type') != 'file'
            or current.get('path') != 'website/store-release.json' or current.get('encoding') != 'base64'
            or not isinstance(current.get('sha'), str) or re.fullmatch(r'[a-f0-9]{40}', current['sha']) is None
            or not isinstance(current.get('content'), str) or len(current['content']) > 16 * 1024):
        raise ValueError('현재 공개 메타데이터 파일의 신원이 일치하지 않습니다')
    try:
        raw = base64.b64decode(current['content'].replace('\n', ''), validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('현재 공개 메타데이터 인코딩이 올바르지 않습니다') from None
    previous = decode_metadata(raw)
    if _version(candidate['version']) < _version(previous['version']):
        raise ValueError('Store 공개 버전 회귀를 차단했습니다')
    if candidate == previous:
        return False
    result = request('PUT', CONTENTS, {'branch': 'main', 'sha': current['sha'],
                     'content': base64.b64encode(encode_metadata(candidate)).decode('ascii'),
                     'message': 'Store 공개 버전 메타데이터 갱신'})
    content = result.get('content') if isinstance(result, dict) else None
    if (not isinstance(content, dict) or content.get('path') != 'website/store-release.json'
            or not isinstance(content.get('sha'), str) or re.fullmatch(r'[a-f0-9]{40}', content['sha']) is None):
        raise ValueError('GitHub 메타데이터 갱신 응답이 일치하지 않습니다')
    return True


def require_environment():
    if (os.environ.get('GITHUB_REPOSITORY') != 'ATLKR/OpenGeul'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch')):
        raise ValueError('공개 main 전용 Store 관측 실행이 아닙니다')
    try:
        with Path(os.environ['GITHUB_EVENT_PATH']).open('rb') as stream:
            event = _json(stream.read(MAX_RESPONSE + 1), MAX_RESPONSE)
    except (KeyError, OSError):
        raise ValueError('공개 저장소 이벤트를 확인할 수 없습니다') from None
    repository = event.get('repository') if isinstance(event, dict) else None
    if (not isinstance(repository, dict) or repository.get('private') is not False
            or repository.get('full_name') != 'ATLKR/OpenGeul'):
        raise ValueError('공개 소유 저장소 이벤트가 아닙니다')


def refresh():
    require_environment()
    opener, token = authenticate()
    candidate = observe(opener, token)
    changed = synchronize(candidate, github)
    print('Store 공개 버전:', candidate['version'], '; 메타데이터:', '갱신' if changed else '변경 없음')
    return candidate, changed


def badge_svg(value):
    version = validate_metadata(value)['version']
    # 모든 삽입 값은 고정 문자열 또는 검증된 ASCII 버전 숫자다.
    label = 'Store 공개 버전'
    width = 154 + max(92, len(version) * 8 + 16)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="28" role="img" '
           f'aria-label="{label} {version}"><title>{label} {version}</title>'
           '<rect width="154" height="28" fill="#334155"/>'
           f'<rect x="154" width="{width - 154}" height="28" fill="#166534"/>'
           '<g fill="#fff" font-family="sans-serif" font-size="12" text-anchor="middle">'
           f'<text x="77" y="19">{label}</text><text x="{154 + (width - 154) // 2}" y="19">{version}</text>'
           '</g></svg>\n')
    return svg.encode('utf-8')


if __name__ == '__main__':
    try:
        refresh()
    except Exception:
        # 네트워크 예외/응답/URL/비밀값을 Actions 로그나 summary에 쓰지 않는다.
        print('::error::Store 공개 버전 확인 또는 메타데이터 갱신에 실패했습니다. 자동 추가 갱신은 수행하지 않습니다.')
        sys.exit(1)
