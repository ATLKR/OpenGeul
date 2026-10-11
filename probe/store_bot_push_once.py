"""고정 JSON 끝에 LF 한 개만 추가하는 일회 GITHUB_TOKEN webhook 진단."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess

# root가 실제 main 병합 후 별도 GET 증거로 확정한다. 미정이면 읽기도 금지한다.
EXPECTED_MAIN_SHA = 'b3c8b61d01731dc1e39357034d9c489a3ea829a9'
EXPECTED_BLOB_SHA = '84458dd0b22b02f3128c44119afad4f07fe851d2'
EXPECTED_BYTES_SHA256 = '02c85a1dd1245309e4683b74284a6f82ea46226001c5e3e59360fdb8c597f3cf'
REPO = 'ATLKR/OpenGeul'
REF = 'refs/heads/diagnostic/store-bot-push-once'
WORKFLOW_REF = REPO + '/.github/workflows/store-package.yml@' + REF
FILE_PATH = 'website/store-release.json'
PREFIX = 'repos/' + REPO + '/'
HEAD_API = PREFIX + 'git/ref/heads/main'
FILE_API = PREFIX + 'contents/' + FILE_PATH
RECEIPT_PATH = Path('bot-push-receipt.json')
MAX_FILE = 8192
MAX_RESPONSE = 65536
METADATA = {'formatVersion': 1, 'appId': '9PJH0T3PHRMF', 'status': 'Published',
            'version': '1.1.1.0', 'storeUrl': 'https://apps.microsoft.com/detail/9PJH0T3PHRMF',
            'submissionId': '1152921505702042424'}


def require(condition):
    if not condition:
        raise ValueError('고정 진단 계약을 확인하지 못했습니다')


def sha(value, length=40):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(data, limit):
    require(isinstance(data, bytes) and len(data) <= limit)
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False))


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def environment(env):
    require(env.get('GITHUB_REPOSITORY') == REPO and env.get('GITHUB_REF') == REF
            and env.get('GITHUB_WORKFLOW_REF') == WORKFLOW_REF
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_RUN_ATTEMPT') == '1'
            and re.fullmatch('[1-9][0-9]{0,24}', env.get('GITHUB_RUN_ID', '')) is not None)
    token, gh_token = env.get('GITHUB_TOKEN', ''), env.get('GH_TOKEN', '')
    require(bool(token) and hmac.compare_digest(token, gh_token))
    with Path(env['GITHUB_EVENT_PATH']).open('rb') as stream:
        event = decode(stream.read(MAX_RESPONSE + 1), MAX_RESPONSE)
    repo = event.get('repository') if isinstance(event, dict) else None
    require(isinstance(repo, dict) and repo.get('private') is False and repo.get('full_name') == REPO)


def github(method, path, body=None):
    allowed = (method, path) in (('GET', HEAD_API), ('GET', FILE_API + '?ref=main'), ('PUT', FILE_API))
    allowed = allowed or (method == 'GET' and path.startswith(PREFIX + 'commits/')
                          and sha(path.removeprefix(PREFIX + 'commits/')))
    require(allowed and (body is None) == (method == 'GET'))
    command = ['gh', 'api', '--hostname', 'github.com', '--method', method, path]
    data = None
    if body is not None:
        command += ['--input', '-']
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    try:
        response = subprocess.run(command, input=data, capture_output=True, timeout=25)
        require(response.returncode == 0)
        result = decode(response.stdout, MAX_RESPONSE)
        require(isinstance(result, dict))
        return result
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        raise ValueError('고정 GitHub API 요청에 실패했습니다') from None


def main_head(value):
    require(isinstance(value, dict) and value.get('ref') == 'refs/heads/main')
    obj = value.get('object')
    require(isinstance(obj, dict) and obj.get('type') == 'commit' and sha(obj.get('sha')))
    return obj['sha']


def file_bytes(value, expected_blob, expected_bytes):
    require(isinstance(value, dict) and value.get('type') == 'file' and value.get('path') == FILE_PATH
            and value.get('encoding') == 'base64' and value.get('sha') == expected_blob
            and type(value.get('size')) is int and 0 < value['size'] <= MAX_FILE
            and isinstance(value.get('content'), str) and len(value['content']) <= 2 * MAX_FILE)
    try:
        raw = base64.b64decode(value['content'].replace('\n', ''), validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('고정 파일 인코딩을 확인하지 못했습니다') from None
    require(len(raw) == value['size'] and blob(raw) == expected_blob
            and hashlib.sha256(raw).hexdigest() == expected_bytes)
    metadata = decode(raw, MAX_FILE)
    require(isinstance(metadata, dict) and metadata == METADATA
            and type(metadata.get('formatVersion')) is int and raw.endswith(b'\n'))
    return raw


def one_parent(value):
    require(isinstance(value, dict))
    parents = value.get('parents')
    require(isinstance(parents, list) and len(parents) == 1
            and isinstance(parents[0], dict) and parents[0].get('sha') == EXPECTED_MAIN_SHA)


def execute(request, env, receipt):
    receipt.update(status='pending', stage='guards', putAttempted=False, putResponseReceived=False,
                   onePathVerified=False, cloudflareBuildVerified=False, publicationMetadataChanged=False)
    require(sha(EXPECTED_MAIN_SHA) and sha(EXPECTED_BLOB_SHA) and sha(EXPECTED_BYTES_SHA256, 64))
    environment(env)
    receipt.update(runId=env['GITHUB_RUN_ID'], runAttempt=1, expectedMainSha=EXPECTED_MAIN_SHA,
                   oldBlobSha=EXPECTED_BLOB_SHA, oldBytesSha256=EXPECTED_BYTES_SHA256, path=FILE_PATH)
    receipt['stage'] = 'read_main'
    require(main_head(request('GET', HEAD_API)) == EXPECTED_MAIN_SHA)
    receipt['stage'] = 'read_file'
    raw = file_bytes(request('GET', FILE_API + '?ref=main'), EXPECTED_BLOB_SHA, EXPECTED_BYTES_SHA256)
    new = raw + b'\n'
    require(len(new) <= MAX_FILE)
    new_blob, new_bytes = blob(new), hashlib.sha256(new).hexdigest()
    receipt.update(newBlobSha=new_blob, newBytesSha256=new_bytes)
    receipt['stage'] = 'recheck_main'
    require(main_head(request('GET', HEAD_API)) == EXPECTED_MAIN_SHA)
    # Contents API는 파일 SHA만 원자적으로 비교한다. root는 진단 동안 다른 main 쓰기를 중지한다.
    receipt.update(stage='put_once', putAttempted=True)
    result = request('PUT', FILE_API, {'branch': 'main', 'sha': EXPECTED_BLOB_SHA,
                     'content': base64.b64encode(new).decode('ascii'),
                     'message': '진단: Store 공개 메타데이터 끝 줄바꿈으로 bot webhook 확인'})
    receipt['putResponseReceived'] = True
    commit = result.get('commit') if isinstance(result, dict) else None
    if isinstance(commit, dict) and sha(commit.get('sha')):
        receipt['commitSha'] = commit['sha']
    content = result.get('content') if isinstance(result, dict) else None
    require(isinstance(commit, dict) and sha(commit.get('sha')) and commit['sha'] != EXPECTED_MAIN_SHA
            and isinstance(content, dict) and content.get('path') == FILE_PATH and content.get('sha') == new_blob)
    one_parent(commit)
    receipt['stage'] = 'verify_commit'
    observed = request('GET', PREFIX + 'commits/' + commit['sha'])
    require(isinstance(observed, dict) and observed.get('sha') == commit['sha'])
    one_parent(observed)
    files = observed.get('files')
    require(isinstance(files, list) and len(files) == 1 and isinstance(files[0], dict)
            and files[0].get('filename') == FILE_PATH and files[0].get('status') == 'modified'
            and files[0].get('sha') == new_blob)
    receipt['stage'] = 'verify_main_and_file'
    require(main_head(request('GET', HEAD_API)) == commit['sha'])
    require(file_bytes(request('GET', FILE_API + '?ref=main'), new_blob, new_bytes) == new)
    receipt.update(status='success', stage='complete', onePathVerified=True)
    return receipt


def main():
    receipt = {'status': 'pending', 'stage': 'init', 'putAttempted': False,
               'onePathVerified': False, 'cloudflareBuildVerified': False}
    code = 0
    try:
        execute(github, os.environ, receipt)
    except Exception:
        receipt['status'] = 'failed'
        code = 1
    try:
        RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError:
        print('::error::진단 결과 파일 저장에 실패했습니다. 추가 요청을 수행하지 않습니다.')
        return 1
    if code:
        print('::error::고정 일회 진단 검증에 실패했습니다. 추가 PUT을 수행하지 않습니다.')
    else:
        print(json.dumps(receipt, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
