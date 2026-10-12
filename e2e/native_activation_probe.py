"""제품 Launcher 경로를 실제 Windows에서 관측한다. 기본 실행은 합성 파일·폴더만 연다."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading

from native_architecture import verify_executable, verify_host, verify_process

FONT_URI = 'https://opengeul.allenlim.net/fonts'
MODES = ('owned-file', 'owned-folder', 'owned-uri', 'ownerless-uri')
READY_KEYS = {'formatVersion', 'event', 'mode', 'target', 'processId', 'architecture',
              'observationPhase',
              'callerApartment', 'callerApartmentType', 'ownerHwnd', 'ownerProcessId',
              'ownerVisible', 'ownedVisibleWindowCount'}
RESULT_KEYS = READY_KEYS | {'outcome', 'hresult', 'errorKind', 'error', 'elapsedMs'}


def _require(value, message):
    if not value:raise ValueError(message)


def _unique(pairs):
    result = {}
    for name, value in pairs:
        _require(name not in result, '중복 JSON 키를 허용하지 않습니다')
        result[name] = value
    return result


def _json(data):
    _require(isinstance(data, bytes) and 0 < len(data) <= 32768, '관측 JSON 크기가 올바르지 않습니다')
    try:value = json.loads(data.decode('utf-8'), object_pairs_hook=_unique)
    except (UnicodeError, json.JSONDecodeError) as error:raise ValueError('관측 JSON을 읽을 수 없습니다') from error
    _require(isinstance(value, dict), '관측 JSON 객체가 필요합니다')
    return value


def parse_ready(data, *, mode, target, pid, architecture):
    value = _json(data)
    _require(set(value) == READY_KEYS and value['formatVersion'] == 1
             and type(value['formatVersion']) is int and value['event'] == 'ready', 'ready JSON 계약이 다릅니다')
    _require(value['observationPhase'] == 'before-activation', '활성화 시작 전 관측의 binding이 필요합니다')
    _require(mode in MODES and value['mode'] == mode and value['target'] == target,
             '진단 동작 또는 합성 대상이 다릅니다')
    _require(isinstance(target, str) and 0 < len(target) <= 32768 and '\0' not in target,
             '진단 대상 문자열이 올바르지 않습니다')
    if 'uri' in mode:_require(target == FONT_URI, '명시적인 공식 글꼴 URI만 진단할 수 있습니다')
    _require(type(value['processId']) is int and value['processId'] == pid and 0 < pid <= 0xffffffff
             and value['architecture'] == architecture and architecture in ('x64', 'arm64'),
             '진단의 실제 native PID 또는 아키텍처가 다릅니다')
    for key in ('ownerHwnd', 'ownerProcessId', 'ownedVisibleWindowCount', 'callerApartmentType'):
        _require(type(value[key]) is int, '소유 창·COM 관측은 정수여야 합니다')
    _require(type(value['ownerVisible']) is bool and 0 <= value['ownedVisibleWindowCount'] <= 10000,
             '실제 창 표시 관측이 올바르지 않습니다')
    if mode == 'ownerless-uri':
        _require(value['callerApartment'] == 'MTA' and value['callerApartmentType'] == 1
                 and value['ownerHwnd'] == value['ownerProcessId'] == value['ownedVisibleWindowCount'] == 0
                 and value['ownerVisible'] is False, 'owner 없는 URI는 실제 MTA와 소유 창 없음이 필요합니다')
    else:
        _require(value['callerApartment'] == 'STA' and value['callerApartmentType'] in (0, 3)
                 and 0 < value['ownerHwnd'] <= 0xffffffffffffffff and value['ownerProcessId'] == pid
                 and value['ownerVisible'] is True and value['ownedVisibleWindowCount'] > 0,
                 '진단 PID가 소유한 표시 중인 STA 창이 필요합니다')
    return value


def parse_result(data, ready, *, exit_code):
    value = _json(data)
    _require(set(value) == RESULT_KEYS and value['event'] == 'result', 'result JSON 계약이 다릅니다')
    snapshot = {key: item for key, item in value.items() if key in READY_KEYS}
    snapshot['event'] = 'ready'
    checked = parse_ready(json.dumps(snapshot).encode('utf-8'), mode=ready['mode'], target=ready['target'],
                          pid=ready['processId'], architecture=ready['architecture'])
    _require(checked == ready, '결과가 다른 활성화 시작 전 관측을 참조합니다')
    _require(type(value['elapsedMs']) is int and 0 <= value['elapsedMs'] <= 3600000,
             '실제 활성화 소요 시간이 올바르지 않습니다')
    if value['outcome'] == 'accepted':
        _require(exit_code == 0 and value['hresult'] is None and value['errorKind'] is None
                 and value['error'] is None, '오류를 활성화 성공으로 기록할 수 없습니다')
        accepted = True
    elif value['outcome'] == 'error':
        _require(exit_code == 2 and (value['hresult'] is None or type(value['hresult']) is int
                 and -2147483648 <= value['hresult'] <= 2147483647)
                 and isinstance(value['errorKind'], str) and 0 < len(value['errorKind']) <= 128
                 and isinstance(value['error'], str) and 0 < len(value['error']) <= 8192,
                 '실제 실패·HRESULT·메시지가 필요합니다')
        accepted = False
    else:raise ValueError('지원하지 않는 활성화 결과입니다')
    return {'accepted': accepted, 'externalRenderingVerified': False, 'ready': ready, 'result': value}


def _verify_window(ready):
    """자신이 시작한 probe의 창만 검증하며 다른 앱을 조작하지 않는다."""
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.IsWindowVisible.argtypes = [wintypes.HWND];api.IsWindowVisible.restype = wintypes.BOOL
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    api.EnumWindows.argtypes = [callback, wintypes.LPARAM];api.EnumWindows.restype = wintypes.BOOL
    owned = []
    @callback
    def inspect(hwnd, _parameter):
        pid = wintypes.DWORD();api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == ready['processId'] and api.IsWindowVisible(hwnd):owned.append(int(hwnd))
        return True
    _require(api.EnumWindows(inspect, 0) and len(owned) == ready['ownedVisibleWindowCount'],
             'probe의 실제 표시 중인 창 목록이 다릅니다')
    if ready['ownerHwnd']:
        pid = wintypes.DWORD()
        _require(api.GetWindowThreadProcessId(ready['ownerHwnd'], ctypes.byref(pid))
                 and pid.value == ready['processId'] and ready['ownerHwnd'] in owned,
                 '실제 HWND가 소유한 native probe PID에 속하지 않습니다')
    else:_require(not owned, 'owner 없는 MTA 진단에 소유 창이 있습니다')
    return {'verified': True, 'processId': ready['processId'], 'ownedVisibleWindows': owned}


def _ready_line(stream, timeout):
    responses = queue.Queue(maxsize=1)
    def read():
        try:responses.put(stream.readline(32769))
        except Exception as error:responses.put(error)
    worker = threading.Thread(target=read, name='activation-probe-ready', daemon=True)
    worker.start()
    try:value = responses.get(timeout=timeout)
    except queue.Empty as error:raise ValueError('probe ready 응답 시간이 초과되었습니다') from error
    if isinstance(value, Exception):raise ValueError('probe ready 응답을 읽지 못했습니다') from value
    return value


def observe(binary, architecture, mode, target, output, timeout):
    """native PID와 live HWND를 검증한 후에만 자신의 probe에 GO를 보낸다."""
    raw = b'';stderr = b'';native = None;window = None;record = None;drained = False
    process = subprocess.Popen([str(binary), mode, str(target)], cwd=binary.parent,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _require(hasattr(process, '_handle'), '소유한 Windows probe handle이 없습니다')
        native = verify_process(process.pid, binary, architecture, handle=int(process._handle))
        raw = _ready_line(process.stdout, min(timeout, 30))
        ready = parse_ready(raw, mode=mode, target=str(target), pid=process.pid, architecture=architecture)
        window = _verify_window(ready)
        result, stderr = process.communicate(input=b'GO\n', timeout=timeout)
        drained = True
        raw += result
        _require(len(stderr) <= 32768 and not stderr, '성공/활성화 실패 외의 진단 오류가 발생했습니다')
        observation = parse_result(result, ready, exit_code=process.returncode)
        record = {**observation, 'passed': observation['accepted'], 'nativeArchitecture': native,
                  'liveOwnerObservation': window, 'exitCode': process.returncode}
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        record = {'accepted': False, 'passed': False, 'externalRenderingVerified': False,
                  'mode': mode, 'error': str(error), 'nativeArchitecture': native,
                  'liveOwnerObservation': window}
    finally:
        # 이 controller가 만든 probe만 종료한다. 연결 앱·Explorer·브라우저는 종료하지 않는다.
        if process.poll() is None:process.kill()
        if not drained:
            tail, errors = process.communicate(timeout=10)
            raw += tail;stderr += errors
        (output/f'{mode}.stdout.jsonl').write_bytes(raw[:65536])
        (output/f'{mode}.stderr.txt').write_bytes(stderr[:32768])
        if record is not None:record['exitCode'] = process.returncode
    return record


def run(binary, architecture, output, *, include_uri=False, timeout=60):
    binary = Path(binary).absolute();output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    records = [];fixture = None;error = None;fixtures = None;host = None;text = None;cleanup_error = None
    try:
        _require(os.name == 'nt', '실제 Windows에서만 활성화 진단을 실행할 수 있습니다')
        _require(type(timeout) is int and 1 <= timeout <= 180, '진단 시간 제한은 1~180초여야 합니다')
        verify_executable(binary, architecture);host = verify_host(architecture)
        fixture = Path(tempfile.mkdtemp(prefix='OpenGeul-활성화-'))
        folder = fixture/'한글 진단 폴더';folder.mkdir()
        text = folder/'읽기 전용 진단.txt';text.write_text('OpenGeul Windows 기본 앱 활성화 진단\n', encoding='utf-8')
        fixtures = {'file': str(text), 'fileSha256': hashlib.sha256(text.read_bytes()).hexdigest(), 'folder': str(folder)}
        text.chmod(0o444)
        targets = [('owned-file', text), ('owned-folder', folder)]
        if include_uri:targets += [('owned-uri', FONT_URI), ('ownerless-uri', FONT_URI)]
        for mode, target in targets:
            records.append(observe(binary, architecture, mode, target, output, timeout))
    except (ValueError, OSError) as failure:error = str(failure)
    finally:
        try:
            if text is not None and text.exists():text.chmod(0o666)
        except OSError as failure:cleanup_error = str(failure)
        if fixture is not None:shutil.rmtree(fixture, ignore_errors=True)
    report = {'formatVersion': 1, 'passed': bool(records) and all(r['passed'] for r in records) and error is None,
              'architecture': architecture, 'host': host, 'includeUri': include_uri, 'observations': records,
              'error': error, 'fixtures': fixtures, 'fixturesRemoved': fixture is None or not fixture.exists(),
              'cleanupError': cleanup_error,
              'externalRenderingVerified': False, 'storeSubmissionPerformed': False,
              'packagedApplicationVerified': False,
              'controllerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--architecture', choices=('x64', 'arm64'), required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--include-uri', action='store_true', help='공식 글꼴 URI를 실제 연결 브라우저로 열기')
    parser.add_argument('--timeout-seconds', type=int, default=60)
    args = parser.parse_args()
    report = run(args.binary, args.architecture, args.output_dir,
                 include_uri=args.include_uri, timeout=args.timeout_seconds)
    print(json.dumps({'passed': report['passed'], 'output': str(args.output_dir/'result.json')}, ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':main()
