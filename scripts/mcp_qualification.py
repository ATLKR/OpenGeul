"""설치된 제품의 MCP runtime receipt를 현재 소스·CLI·package 신원에 연결한다.

네트워크/제품 실행/입력 수정은 하지 않는다. receipt는 저자 인증이 아니며 실제
Actions 성공·원본 SHA·전체 소스/Store 제출 허가는 호출자가 별도로 검증한다.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys

from windows_arch import machine_for, require_architecture
from windows_components import regular

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_CAP = 128 * 1024
FRAME_CAP = 2 * 1024 * 1024
RUNTIME_CAP = 96 * 1024 * 1024
FIXED_CLSID = 'c6c4d247-b4f0-563d-a649-4765796e3164'
SCOPE = '실제 MCP stdio·합성 문서·native COM worker; 전체 도구·개인 문서·Store 인증을 주장하지 않음'
WORKER_SCOPE = '실제 경로·바이트·생성 시각·고정 bootstrap; SCM ancestry를 사용하지 않음'
INSTALLED_SCOPE = '설치 fixed COM class의 native/package identity 관측; 공유 process 강제 종료 없음'
STRESS_SCOPE = '원본·인쇄 기준과 별개의 작업자 강제 종료용 합성 복사본'
CASE_NAMES = ('initialize', 'ping', 'tools-list', 'normal-read', 'normal-write',
    'ir-diff-code3', 'batch-partial-code1', *('malformed-paths-' + str(n) for n in range(4)),
    *('password-' + fmt + '-' + mode for fmt in ('hwp', 'hwpx') for mode in ('missing', 'wrong', 'correct')))
CASE_NAMES += ('session-open', 'session-text', 'session-replace', 'session-edited-text', 'session-save',
    'session-close', 'session-closed-query', 'session-ping', 'workspace-list', 'workspace-open', 'workspace-text',
    'workspace-replace', 'workspace-edited-text', 'workspace-save', 'workspace-close', 'workspace-journal')
CASE_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 17, 18, 19, 20, 21,
    22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37)
SESSION_CHECKS = (
    {'opened': True, 'sourceUnchanged': True, 'outputAbsent': True},
    {'sourceTextMatched': True, 'docIdMatched': True},
    {'replacedCount': 1, 'docIdMatched': True, 'sourceUnchanged': True, 'outputAbsent': True},
    {'editedTextMatched': True, 'markerCount': 1, 'docIdMatched': True, 'sourceUnchanged': True, 'outputAbsent': True},
    {'saveVerified': True, 'docIdMatched': True, 'independentXmlPassed': True, 'markerCount': 1,
        'sourceUnchanged': True, 'outputBytesMatched': True},
    {'closed': True, 'docIdMatched': True, 'sourceUnchanged': True})
SESSION_WORKSPACE_CHECKS = (*SESSION_CHECKS, {'rejected': True, 'nextOpenHint': True},
    {'passed': True, 'sameServerAlive': True}, {'entryCount': 1, 'ownedEntryMatched': True, 'sourceUnchanged': True},
    {**SESSION_CHECKS[0], 'listedIdUsed': True}, *SESSION_CHECKS[1:],
    {'journalEntries': 4, 'documentIdsMatched': True, 'sequenceMatched': True, 'replaceChanged': True,
        'replaceDigestsDiffer': True, 'saveChangedFalse': True, 'saveDigestsMatch': True, 'noJournalErrors': True,
        'textDigestsMatched': True})
TOP_KEYS = {'formatVersion', 'cases', 'caseCount', 'sourceCommit', 'sourceRun', 'runAttempt',
    'architecture', 'context', 'productSha256', 'helperSha256', 'nativeArchitectureHelperSha256',
    'fullSourceQualified', 'storeCertified', 'scope', 'passed', 'limits', 'serverNativeArchitecture',
    'phase', 'lastCompletedCase', 'stressFixture', 'workerIsolation', 'framesSent', 'framesReceived'}
BINDING_KEYS = {'sourceCommit', 'sourceRun', 'runAttempt'}
NATIVE_KEYS = {'architecture', 'processId', 'imagePath', 'peMachine', 'processMachine',
    'nativeMachine', 'native', 'packageFullName', 'sha256', 'createdFileTime', *BINDING_KEYS}


def require(value, message):
    if not value:
        raise ValueError(message)


def shape(value, keys, message):
    require(type(value) is dict and set(value) == set(keys), message)


def integer(value, minimum, maximum, message):
    require(type(value) is int and minimum <= value <= maximum, message)


def exact(value, expected, message):
    require(type(value) is type(expected) and value == expected, message)


def sha256(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), '정규 SHA256이 필요합니다')
    return value


def source_binding(commit, run, attempt):
    require(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit), '현재 소스 commit이 필요합니다')
    for value in (run, attempt):
        require(type(value) is str and re.fullmatch('[1-9][0-9]{0,19}', value), '현재 실행/시도가 필요합니다')
    return {'sourceCommit': commit, 'sourceRun': run, 'runAttempt': attempt}


def helper_hash(name):
    path = ROOT / 'e2e' / name
    regular(path)
    require(0 < path.stat().st_size <= 1024 * 1024, '현재 helper 크기가 올바르지 않습니다')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_name(value, architecture):
    require(type(value) is str and len(value) <= 256, '설치 package full name이 필요합니다')
    match = re.fullmatch(r'[A-Za-z0-9.-]+_((?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){3})_'
        + architecture + r'__[0-9abcdefghjkmnpqrstvwxyz]{13}', value)
    require(match is not None and all(int(part) <= 65535 for part in match[1].split('.')), '설치 package 버전/아키텍처가 올바르지 않습니다')


def image_path(value, full_name):
    require(type(value) is str and 0 < len(value) <= 32768 and not any(ord(c) < 32 for c in value), '설치 실행 경로가 필요합니다')
    path = PureWindowsPath(value)
    require(path.is_absolute() and '..' not in path.parts and
        tuple(p.lower() for p in path.parts[-3:]) == (full_name.lower(), 'tools', 'rhwp.exe'), '실제 설치 CLI 경로가 다릅니다')
    return path


def native(record, architecture, cli_hash, full_name, binding, *, server, native_helper):
    shape(record, NATIVE_KEYS | ({'bytes', 'helperSha256', 'runningAtInspection', 'controller'} if server else {'classId', 'binding'}), 'MCP process 증명 필드가 다릅니다')
    exact(record['architecture'], architecture, '다른 제품 아키텍처입니다')
    exact(record['native'], True, '제품은 native 실행이어야 합니다')
    machine = machine_for(architecture)
    for key, expected in (('peMachine', machine), ('processMachine', 0), ('nativeMachine', machine)):
        exact(record[key], expected, '제품 PE/WOW/native machine이 다릅니다')
    integer(record['processId'], 1, 2**32 - 1, '제품 PID가 올바르지 않습니다')
    integer(record['createdFileTime'], 1, 2**64 - 1, '제품 생성 시각이 올바르지 않습니다')
    exact(record['packageFullName'], full_name, '제품 package 신원이 다릅니다')
    exact(record['sha256'], cli_hash, '실제 CLI 해시가 다릅니다')
    for key, expected in binding.items():
        exact(record[key], expected, '제품 실행의 source/run/attempt가 다릅니다')
    image_path(record['imagePath'], full_name)
    if server:
        integer(record['bytes'], 1, RUNTIME_CAP, '실제 CLI 크기가 올바르지 않습니다')
        exact(record['helperSha256'], native_helper, 'native helper 소스가 다릅니다')
        exact(record['runningAtInspection'], True, 'MCP 서버가 관측 시 종료됐습니다')
        controller = record['controller']
        shape(controller, {'processId', 'processMachine', 'architecture', 'native'}, 'controller 증명 필드가 다릅니다')
        integer(controller['processId'], 1, 2**32 - 1, 'controller PID가 올바르지 않습니다')
        require(controller['processId'] != record['processId'], 'controller와 제품 PID가 같습니다')
        process = controller['processMachine']
        require(type(process) is int and (process == 0 or architecture == 'arm64' and process == 0x8664), '지원한 Windows controller가 아닙니다')
        exact(controller['architecture'], architecture if process == 0 else 'x64-emulated', 'controller architecture가 다릅니다')
        exact(controller['native'], process == 0, 'controller native 판정이 다릅니다')
    else:
        exact(record['classId'], FIXED_CLSID, '설치된 fixed COM class가 다릅니다')
        exact(record['binding'], WORKER_SCOPE, '작업자 bootstrap 증명 범위가 다릅니다')


def response(record, name, request_id, checks):
    shape(record, {'name', 'requestId', 'responseSha256', 'responseBytes', 'checks'}, 'MCP 응답 증명 필드가 다릅니다')
    exact(record['name'], name, 'MCP 사례 순서/이름이 다릅니다')
    exact(record['requestId'], request_id, 'MCP request ID가 다릅니다')
    sha256(record['responseSha256'])
    integer(record['responseBytes'], 1, FRAME_CAP, 'MCP 응답 크기가 올바르지 않습니다')
    shape(record['checks'], checks, 'MCP 판정 필드가 다릅니다')
    for key, expected in checks.items():
        value = record['checks'][key]
        if type(expected) is tuple:
            integer(value, *expected, 'MCP 판정 계수가 올바르지 않습니다')
        else:
            exact(value, expected, 'MCP 필수 판정이 실패했거나 형식이 다릅니다')


def verify(proof, architecture, cli_sha256, package_full_name, source_commit, source_run, run_attempt):
    """입력을 수정하지 않고 현재 설치 MCP 증명만 반환한다. 전체 qualification은 주장하지 않는다."""
    architecture = require_architecture(architecture)
    sha256(cli_sha256); package_name(package_full_name, architecture)
    binding = source_binding(source_commit, source_run, run_attempt)
    shape(proof, TOP_KEYS, '설치 MCP 증명 필드가 다릅니다')
    for key, expected in {'formatVersion': 1, 'architecture': architecture, 'context': 'installed',
            'productSha256': cli_sha256, **binding, 'fullSourceQualified': False, 'storeCertified': False,
            'passed': True, 'scope': SCOPE, 'caseCount': 33, 'phase': 'hwp_ws_journal',
            'lastCompletedCase': CASE_NAMES[-1], 'framesSent': 39, 'framesReceived': 38,
            'helperSha256': helper_hash('mcp_worker.py'), 'nativeArchitectureHelperSha256': helper_hash('native_architecture.py')}.items():
        exact(proof[key], expected, '현재 설치 MCP 실행/범위/완료 판정이 다릅니다')
    limits = {'frameBytes': FRAME_CAP, 'runtimeBytes': RUNTIME_CAP, 'requestTimeoutSeconds': 30}
    shape(proof['limits'], limits, 'MCP 실행 한도 필드가 다릅니다')
    for key, value in limits.items(): exact(proof['limits'][key], value, 'MCP 실행 한도가 다릅니다')
    cases = proof['cases']
    require(type(cases) is list and len(cases) == 33, '전체 33개 MCP 사례가 필요합니다')
    checks = ({'protocolPassed': True}, {'passed': True}, {'toolsListed': (13, 2000), 'requiredToolsPresent': True},
        {'sourceTextMatched': True}, {'independentXmlPassed': True, 'sourceUnchanged': True, 'replacedCount': (1, 2**31 - 1)},
        {'cliExitCode': 3, 'sameJson': True}, {'cliExitCode': 1, 'records': 2, 'sameNdjson': True},
        *({'rejected': True, 'serverResponsive': True} for _ in range(4)),
        *({'expectedResultPassed': True, 'ciphertextUnchanged': True} for _ in range(6)), *SESSION_WORKSPACE_CHECKS)
    for record, name, request_id, values in zip(cases, CASE_NAMES, CASE_IDS, checks):
        response(record, name, request_id, values)
    stress = proof['stressFixture']
    shape(stress, {'sha256', 'bytes', 'addedSyntheticParagraphs', 'scope'}, '합성 stress fixture 필드가 다릅니다')
    sha256(stress['sha256']); integer(stress['bytes'], 1, RUNTIME_CAP, '합성 fixture 크기가 다릅니다')
    exact(stress['addedSyntheticParagraphs'], 1500, '합성 fixture 문단 수가 다릅니다')
    exact(stress['scope'], STRESS_SCOPE, '합성 fixture 범위가 다릅니다')
    isolation = proof['workerIsolation']
    shape(isolation, {'worker', 'sameServerAlive', 'forcedTermination', 'batchRecords', 'response', 'scope'}, '설치 worker 증명 필드가 다릅니다')
    for key, value in {'sameServerAlive': True, 'forcedTermination': False, 'batchRecords': 64, 'scope': INSTALLED_SCOPE}.items():
        exact(isolation[key], value, '설치 worker batch/서버 생존/강제 종료 판정이 다릅니다')
    response(isolation['response'], 'installed-worker-batch64', 38, {'records': 64, 'passed': True})
    hashes = [row['responseSha256'] for row in [*cases, isolation['response']]]
    require(len(set(hashes)) == 34, '서로 다른 request ID의 응답 해시가 중복됩니다')
    parent, worker = proof['serverNativeArchitecture'], isolation['worker']
    for record, is_server in ((parent, True), (worker, False)):
        native(record, architecture, cli_sha256, package_full_name, binding, server=is_server,
            native_helper=proof['nativeArchitectureHelperSha256'])
    require(worker['processId'] not in (parent['processId'], parent['controller']['processId'])
        and worker['createdFileTime'] >= parent['createdFileTime'], '설치 worker PID/생성 시각이 서버와 다릅니다')
    require(image_path(parent['imagePath'], package_full_name) == image_path(worker['imagePath'], package_full_name), '서버와 worker 실행 경로가 다릅니다')
    return proof


def read_receipt(path):
    regular(path)
    require(0 < path.stat().st_size <= RECEIPT_CAP, 'MCP receipt 크기 한도를 초과했습니다')
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'MCP receipt JSON 키가 중복됩니다'); result[key] = value
        return result
    def nonfinite(_): raise ValueError('MCP receipt JSON 숫자가 정규 형식이 아닙니다')
    try:
        with path.open('rb') as stream:
            raw = stream.read(RECEIPT_CAP + 1)
        require(0 < len(raw) <= RECEIPT_CAP, 'MCP receipt 읽기 크기 한도를 초과했습니다')
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('MCP receipt는 bounded UTF-8 JSON이어야 합니다') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--architecture', choices=('x64', 'arm64'), required=True)
    parser.add_argument('--cli-sha256', required=True); parser.add_argument('--package-full-name', required=True)
    parser.add_argument('--source-commit', default=os.getenv('GITHUB_SHA'))
    parser.add_argument('--source-run', default=os.getenv('GITHUB_RUN_ID'))
    parser.add_argument('--run-attempt', default=os.getenv('GITHUB_RUN_ATTEMPT'))
    args = parser.parse_args()
    verify(read_receipt(args.receipt), args.architecture, args.cli_sha256, args.package_full_name,
        args.source_commit, args.source_run, args.run_attempt)
    print(json.dumps({'passed': True, 'context': 'installed', 'architecture': args.architecture,
        'caseCount': 33, 'fullSourceQualified': False, 'storeCertified': False}, ensure_ascii=False))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError):
        raise SystemExit('설치 MCP 증명이 현재 실행·제품 신원·33개 필수 판정을 만족하지 않습니다.') from None
