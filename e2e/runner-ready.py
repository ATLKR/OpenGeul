"""공개 hosted ARM 러너의 창을 한 번 관찰한다. 입력·종료·설정 변경은 없다."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

MAX_WINDOWS = 64
MAX_UIA = 64
MAX_PROCESSES = 8
MAX_JSON = 256 * 1024
BRANCH = 'refs/heads/diagnostic/arm-runner-ready71'


def require(value, message):
    if not value: raise ValueError(message)


def text(value, limit=256):
    require(type(value) is str and len(value) <= limit and not any(ord(c) < 32 for c in value),
            '관찰 문자열이 상한 또는 형식을 벗어났습니다')
    return value


def bounded(value, limit=256):
    return ''.join(c if ord(c) >= 32 else ' ' for c in str(value or ''))[:limit]


def integer(value, minimum=1):
    require(type(value) is int and minimum <= value < 2**64, '관찰 정수 형식이 다릅니다')


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys), '관찰 필드가 다릅니다')


def binding(env):
    fixed = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
             'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
             'GITHUB_REF': BRANCH, 'GITHUB_ACTOR': 'ATLKR', 'GITHUB_RUN_ATTEMPT': '1'}
    require(all(env.get(k) == v for k, v in fixed.items()), '허용된 공개 ARM 진단 실행이 아닙니다')
    require(type(env.get('GITHUB_SHA')) is str and re.fullmatch('[0-9a-f]{40}', env['GITHUB_SHA'])
            and type(env.get('GITHUB_RUN_ID')) is str and re.fullmatch('[1-9][0-9]{0,19}', env['GITHUB_RUN_ID']),
            '진단 source/run 바인딩이 없습니다')
    return {'sourceCommit': env['GITHUB_SHA'], 'runId': env['GITHUB_RUN_ID'], 'runAttempt': '1',
            'repository': 'ATLKR/OpenGeul', 'actor': 'ATLKR', 'ref': BRANCH}


def safe_output(path):
    path = Path(path).absolute()
    require('..' not in path.parts, '출력 경로 별칭을 허용하지 않습니다')
    for p in (path, *path.parents):
        if p.exists() or p.is_symlink():
            s = p.lstat()
            require(not stat.S_ISLNK(s.st_mode) and not getattr(s, 'st_file_attributes', 0) & 0x400,
                    '출력 symlink/reparse를 허용하지 않습니다')
    require(path.parent.is_dir() and not path.exists(), '기존 진단 출력을 덮어쓰지 않습니다')
    return path


def validate_windows(value):
    shape(value, ('foregroundHwnd', 'windows', 'truncated'))
    integer(value['foregroundHwnd'], 0)
    require(type(value['truncated']) is bool and type(value['windows']) is list
            and len(value['windows']) <= MAX_WINDOWS, '창 관찰 상한이 다릅니다')
    seen = set()
    for row in value['windows']:
        shape(row, ('hwnd', 'processId', 'threadId', 'title', 'className', 'visible', 'enabled', 'rectangle'))
        for k in ('hwnd', 'processId', 'threadId'): integer(row[k])
        require(row['hwnd'] not in seen, '중복 HWND를 허용하지 않습니다'); seen.add(row['hwnd'])
        text(row['title']); text(row['className'])
        require(type(row['visible']) is bool and type(row['enabled']) is bool
                and type(row['rectangle']) is list and len(row['rectangle']) == 4
                and all(type(n) is int and -100000 <= n <= 100000 for n in row['rectangle']),
                '창 상태/좌표 형식이 다릅니다')


def validate_uia(value, hwnd):
    require(type(value) is dict and set(value) in ({'hwnd', 'nodes', 'truncated'}, {'hwnd', 'nodes', 'truncated', 'error'}),
            'UIA 관찰 필드가 다릅니다')
    require(value['hwnd'] == hwnd and type(value['nodes']) is list and len(value['nodes']) <= MAX_UIA
            and type(value['truncated']) is bool, 'UIA 상한이 다릅니다')
    for row in value['nodes']:
        shape(row, ('name', 'controlType', 'automationId', 'className', 'processId', 'enabled', 'offscreen'))
        for key in ('name', 'automationId', 'className'): text(row[key])
        integer(row['controlType'], 0); integer(row['processId'], 0)
        require(type(row['enabled']) is bool and type(row['offscreen']) is bool, 'UIA 상태 형식이 다릅니다')
    if 'error' in value:
        shape(value['error'], ('type', 'hresult')); text(value['error']['type']); text(value['error']['hresult'])


def observe(probe, env, output):
    scope = binding(env); output = safe_output(output); host = probe.host()
    shape(host, ('processId', 'processMachine', 'nativeMachine')); integer(host['processId'])
    require(type(host['processMachine']) is int and host['processMachine'] in (0, 0x8664)
            and type(host['nativeMachine']) is int and host['nativeMachine'] == 0xAA64,
            '실제 Windows ARM64 호스트가 아닙니다')
    windows = probe.windows(); validate_windows(windows)
    foreground = next((r for r in windows['windows'] if r['hwnd'] == windows['foregroundHwnd']), None)
    uia = []
    if windows['foregroundHwnd']:
        tree = probe.uia(windows['foregroundHwnd']); validate_uia(tree, windows['foregroundHwnd']); uia.append(tree)
    pids = list(dict.fromkeys(([foreground['processId']] if foreground else [])
        + [n['processId'] for tree in uia for n in tree['nodes'] if n['processId']]
        + [r['processId'] for r in windows['windows'] if r['visible']]))[:MAX_PROCESSES]
    processes = probe.processes(pids)
    require(type(processes) is list and len(processes) == len(pids)
            and [r.get('processId') for r in processes] == pids, '제한된 process 관찰이 다릅니다')
    for row in processes:
        shape(row, ('processId', 'imagePath', 'imageBytes', 'imageSha256', 'createdFileTime', 'sessionId', 'signature'))
        integer(row['processId']); text(row['imagePath'], 1024); integer(row['imageBytes'], 0)
        require(row['imageSha256'] == '' or re.fullmatch('[0-9a-f]{64}', row['imageSha256']), '이미지 SHA 형식이 다릅니다')
        integer(row['createdFileTime'], 0); integer(row['sessionId'], 0)
        shape(row['signature'], ('status', 'subject', 'issuer', 'thumbprint', 'publisherMicrosoft'))
        for key in ('status', 'subject', 'issuer', 'thumbprint'): text(row['signature'][key])
        require(type(row['signature']['publisherMicrosoft']) is bool, '서명 판정 형식이 다릅니다')
    output.mkdir()
    image = output / 'foreground-desktop.png'; dimensions = probe.screen(image)
    shape(dimensions, ('width', 'height'))
    require(all(type(v) is int and 0 < v <= 8192 for v in dimensions.values())
            and dimensions['width'] * dimensions['height'] <= 20_000_000
            and image.is_file() and not image.is_symlink() and 8 <= image.stat().st_size <= 8 * 1024 * 1024,
            '화면 관찰 상한이 다릅니다')
    data = image.read_bytes(); require(data.startswith(b'\x89PNG\r\n\x1a\n'), '화면 PNG 형식이 다릅니다')
    value = {'formatVersion': 1, **scope, 'readOnly': True, 'inputsPerformed': 0,
             'diagnosticOnly': True, 'sourceQualified': False, 'productExecuted': False,
             'hostReadyQualified': False, 'scope': 'Windows ARM64 hosted foreground 관찰만; consent/registry/process/input 변경 없음',
             'helperSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'controller': {**host, 'native': host['processMachine'] == 0},
             'foreground': foreground, 'windowObservation': windows, 'processes': processes, 'uia': uia,
             'screen': {**dimensions, 'path': image.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    require(len(raw) <= MAX_JSON, 'JSON 관찰 상한을 초과했습니다')
    with (output / 'observation.json').open('xb') as stream: stream.write(raw)
    return value


class WindowsProbe:
    def __init__(self):
        require(os.name == 'nt', 'Windows 전용 관찰입니다')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        for name, args, result in [('EnumWindows', [self.callback, W.LPARAM], W.BOOL),
             ('GetForegroundWindow', [], W.HWND), ('GetWindowThreadProcessId', [W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
             ('GetWindowTextW', [W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
             ('GetClassNameW', [W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int),
             ('IsWindowVisible', [W.HWND], W.BOOL), ('IsWindowEnabled', [W.HWND], W.BOOL),
             ('GetWindowRect', [W.HWND, ctypes.POINTER(W.RECT)], W.BOOL)]:
            f = getattr(self.user, name); f.argtypes = args; f.restype = result
        for name, args, result in [('GetCurrentProcess', [], W.HANDLE), ('GetCurrentProcessId', [], W.DWORD),
             ('IsWow64Process2', [W.HANDLE, ctypes.POINTER(W.WORD), ctypes.POINTER(W.WORD)], W.BOOL),
             ('OpenProcess', [W.DWORD, W.BOOL, W.DWORD], W.HANDLE), ('CloseHandle', [W.HANDLE], W.BOOL),
             ('QueryFullProcessImageNameW', [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)], W.BOOL),
             ('ProcessIdToSessionId', [W.DWORD, ctypes.POINTER(W.DWORD)], W.BOOL),
             ('GetProcessTimes', [W.HANDLE, *[ctypes.POINTER(W.FILETIME)] * 4], W.BOOL)]:
            f = getattr(self.kernel, name); f.argtypes = args; f.restype = result

    def host(self):
        process = W.WORD(); native = W.WORD()
        require(self.kernel.IsWow64Process2(self.kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)),
                '실제 host native machine을 읽지 못했습니다')
        return {'processId': int(self.kernel.GetCurrentProcessId()), 'processMachine': process.value, 'nativeMachine': native.value}

    def windows(self):
        foreground = int(self.user.GetForegroundWindow() or 0); rows = []; truncated = False
        def read(hwnd, _):
            nonlocal truncated
            if len(rows) >= MAX_WINDOWS: truncated = True; return False
            pid = W.DWORD(); tid = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not tid or not pid.value: return True
            title = ctypes.create_unicode_buffer(257); cls = ctypes.create_unicode_buffer(257); rect = W.RECT()
            self.user.GetWindowTextW(hwnd, title, 257); self.user.GetClassNameW(hwnd, cls, 257); self.user.GetWindowRect(hwnd, ctypes.byref(rect))
            rows.append({'hwnd': int(hwnd), 'processId': pid.value, 'threadId': int(tid), 'title': bounded(title.value),
                         'className': bounded(cls.value), 'visible': bool(self.user.IsWindowVisible(hwnd)),
                         'enabled': bool(self.user.IsWindowEnabled(hwnd)), 'rectangle': [rect.left, rect.top, rect.right, rect.bottom]})
            return True
        callback = self.callback(read); self.user.EnumWindows(callback, 0)
        return {'foregroundHwnd': foreground, 'windows': rows, 'truncated': truncated}

    def uia(self, hwnd):
        result = {'hwnd': hwnd, 'nodes': [], 'truncated': False}
        try:
            from pywinauto.uia_defines import IUIA
            api = IUIA(); root = api.iuia.ElementFromHandle(hwnd); walker = api.tree_walker; pending = [root]
            while pending and len(result['nodes']) < MAX_UIA:
                element = pending.pop(); result['nodes'].append({'name': bounded(element.CurrentName),
                    'controlType': int(element.CurrentControlType), 'automationId': bounded(element.CurrentAutomationId),
                    'className': bounded(element.CurrentClassName), 'processId': int(element.CurrentProcessId),
                    'enabled': bool(element.CurrentIsEnabled), 'offscreen': bool(element.CurrentIsOffscreen)})
                child = walker.GetFirstChildElement(element); siblings = []
                while child and len(siblings) + len(pending) + len(result['nodes']) < MAX_UIA:
                    siblings.append(child); child = walker.GetNextSiblingElement(child)
                if child: result['truncated'] = True
                pending.extend(reversed(siblings))
            if pending: result['truncated'] = True
        except Exception as e:
            result['error'] = {'type': bounded(type(e).__name__), 'hresult': f'0x{getattr(e, "hresult", 0) & 0xffffffff:08x}'}
        return result

    def processes(self, pids):
        rows = []
        for pid in pids:
            row = {'processId': pid, 'imagePath': '', 'imageBytes': 0, 'imageSha256': '', 'createdFileTime': 0,
                   'sessionId': 0, 'signature': {'status': 'Unavailable', 'subject': '', 'issuer': '', 'thumbprint': '', 'publisherMicrosoft': False}}
            session = W.DWORD()
            if self.kernel.ProcessIdToSessionId(pid, ctypes.byref(session)): row['sessionId'] = session.value
            handle = self.kernel.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    size = W.DWORD(32768); name = ctypes.create_unicode_buffer(size.value)
                    if self.kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)) and len(name.value) <= 1024:
                        row['imagePath'] = bounded(name.value, 1024)
                    times = [W.FILETIME() for _ in range(4)]
                    if self.kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                        row['createdFileTime'] = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
                finally: self.kernel.CloseHandle(handle)
            path = Path(row['imagePath'])
            if row['imagePath'] and path.is_file() and not path.is_symlink() and path.stat().st_size <= 128 * 1024 * 1024:
                row['imageBytes'] = path.stat().st_size
                with path.open('rb') as f:
                    h = hashlib.sha256()
                    for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
                row['imageSha256'] = h.hexdigest()
            rows.append(row)
        # 경로는 stdin JSON으로 전달한다. shell text/argv/env에서 실행하지 않는다.
        script = "$p=[Console]::In.ReadToEnd()|ConvertFrom-Json; @($p|ForEach-Object { try { $s=Get-AuthenticodeSignature -LiteralPath $_ -ErrorAction Stop; @{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject;issuer=[string]$s.SignerCertificate.Issuer;thumbprint=[string]$s.SignerCertificate.Thumbprint} } catch { @{status='Unavailable';subject='';issuer='';thumbprint=''} } })|ConvertTo-Json -Compress"
        try:
            completed = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
                input=json.dumps([r['imagePath'] for r in rows]).encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
            require(completed.returncode == 0 and len(completed.stdout) <= 16384, '서명 관찰 상한을 벗어났습니다')
            signatures = json.loads(completed.stdout.decode('utf-8-sig'))
            if type(signatures) is dict: signatures = [signatures]
            require(type(signatures) is list and len(signatures) == len(rows), '서명 관찰 개수가 다릅니다')
            for row, signature in zip(rows, signatures):
                fields = {key: bounded(signature.get(key, '')) for key in ('status', 'subject', 'issuer', 'thumbprint')}
                fields['publisherMicrosoft'] = fields['status'] == 'Valid' and bool(re.search(r'(?:CN|O)=Microsoft(?: Windows| Corporation)', fields['subject']))
                row['signature'] = fields
        except (OSError, subprocess.SubprocessError, ValueError): pass
        return rows

    def screen(self, path):
        from PIL import ImageGrab
        screen = ImageGrab.grab(all_screens=False)
        require(screen.width <= 8192 and screen.height <= 8192 and screen.width * screen.height <= 20_000_000,
                '화면 픽셀 상한을 초과했습니다')
        screen.save(path, format='PNG')
        return {'width': screen.width, 'height': screen.height}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); binding(os.environ)
    value = observe(WindowsProbe(), os.environ, args.output)
    print(json.dumps({'observationCompleted': True, 'windows': len(value['windowObservation']['windows']),
                      'inputsPerformed': 0, 'sourceQualified': False}, ensure_ascii=False))


if __name__ == '__main__': main()
