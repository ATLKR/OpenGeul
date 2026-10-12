"""공개 ARM 러너를 관찰하고 명시적 --prepare에서 검증된 OS 창만 정상 닫는다."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import subprocess
import time

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
             'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_ACTOR': 'ATLKR', 'GITHUB_RUN_ATTEMPT': '1'}
    require(all(env.get(k) == v for k, v in fixed.items()), '허용된 공개 ARM 진단 실행이 아닙니다')
    diagnostic = env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and env.get('GITHUB_REF') == BRANCH
    production = env.get('GITHUB_EVENT_NAME') == 'push' and env.get('GITHUB_REF') == 'refs/heads/main' \
        and env.get('GITHUB_WORKFLOW_REF') == 'ATLKR/OpenGeul/.github/workflows/msix.yml@refs/heads/main'
    require(diagnostic or production, '허용된 ARM hosted 진단/Source 실행이 아닙니다')
    require(type(env.get('GITHUB_SHA')) is str and re.fullmatch('[0-9a-f]{40}', env['GITHUB_SHA'])
            and type(env.get('GITHUB_RUN_ID')) is str and re.fullmatch('[1-9][0-9]{0,19}', env['GITHUB_RUN_ID']),
            '진단 source/run 바인딩이 없습니다')
    return {'sourceCommit': env['GITHUB_SHA'], 'runId': env['GITHUB_RUN_ID'], 'runAttempt': '1',
            'repository': 'ATLKR/OpenGeul', 'actor': 'ATLKR', 'ref': env['GITHUB_REF']}


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
        shape(row, ('processId', 'imagePath', 'imageBytes', 'imageSha256', 'createdFileTime', 'sessionId',
                    'processMachine', 'nativeMachine', 'signature'))
        integer(row['processId']); text(row['imagePath'], 1024); integer(row['imageBytes'], 0)
        require(row['imageSha256'] == '' or re.fullmatch('[0-9a-f]{64}', row['imageSha256']), '이미지 SHA 형식이 다릅니다')
        integer(row['createdFileTime'], 0); integer(row['sessionId'], 0)
        require((row['processMachine'] is None and row['nativeMachine'] is None) or
                all(type(row[k]) is int and 0 <= row[k] <= 65535 for k in ('processMachine', 'nativeMachine')),
                'process 아키텍처 관찰 형식이 다릅니다')
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


PRIVACY_FOOTER = 'ms-appx-web://microsoft.windows.cloudexperiencehost/core/view/oobeLightFooterHost.html'
PAGING_WARNING = ('Windows created a temporary paging file on your computer because of a problem that occurred '
                  'with your paging file configuration when you started your computer.  The total paging file '
                  'size for all disk drives may be somewhat larger than the size you specified.')


def owned_os_candidate(observed, session_id, windows_directory, executable, title, class_name, *, relative_path=None, owner_only=True):
    window = observed.get('foreground')
    require(type(window) is dict and window['title'] == title and window['className'] == class_name
            and window['visible'] is True and window['enabled'] is True, '관측된 OS 전경 창이 다릅니다')
    processes = [p for p in observed['processes'] if p['processId'] == window['processId']]
    require(len(processes) == 1, 'OS 창 소유 process가 유일하지 않습니다'); process = processes[0]
    signature = process['signature']
    expected_path = ntpath.join(windows_directory, relative_path or ntpath.join('System32', executable))
    require(ntpath.normcase(process['imagePath']) == ntpath.normcase(expected_path)
            and process['createdFileTime'] > 0 and process['sessionId'] == session_id
            and process['processMachine'] == 0 and process['nativeMachine'] == 0xAA64
            and process['imageBytes'] > 0 and re.fullmatch('[0-9a-f]{64}', process['imageSha256'])
            and signature['status'] == 'Valid' and signature['publisherMicrosoft'] is True
            and re.search(r'(?:^|,\s*)CN=Microsoft Windows(?:,|$)', signature['subject'])
            and re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', signature['subject']),
            'OS process의 경로·native·생성시각·session·Microsoft 서명이 다릅니다')
    trees = [t for t in observed['uia'] if t['hwnd'] == window['hwnd']]
    require(len(trees) == 1 and 'error' not in trees[0] and trees[0]['truncated'] is False
            and trees[0]['nodes'] and (not owner_only or all(n['processId'] == window['processId'] for n in trees[0]['nodes'])),
            'OS 창 UIA 소유권/완전성이 다릅니다')
    return {'hwnd': window['hwnd'], 'window': window, 'process': process,
            'uia': trees[0], 'operation': 'WM_CLOSE', 'kind': executable}


def privacy_candidate(observed, session_id, windows_directory):
    candidate = owned_os_candidate(observed, session_id, windows_directory,
                                   'WWAHost.exe', 'Microsoft account', 'Windows.UI.Core.CoreWindow')
    nodes = candidate['uia']['nodes']
    require(any(n['name'] == 'Choose privacy settings for your device' and n['controlType'] == 50033 and not n['offscreen'] for n in nodes)
            and any(n['name'] == 'Windows Setup' and n['controlType'] == 50006 for n in nodes)
            and any(n['name'] == PRIVACY_FOOTER and n['controlType'] == 50033 for n in nodes)
            and sum(n['name'] == 'Next, tab through all privacy settings to continue' and
                    n['automationId'] == 'OobeSettingsAcceptButton' and n['controlType'] == 50000 and
                    n['enabled'] and not n['offscreen'] for n in nodes) == 1,
            '관측된 CloudExperienceHost 개인정보 페이지 문맥이 다릅니다')
    return candidate


def paging_candidate(observed, session_id, windows_directory):
    candidate = owned_os_candidate(observed, session_id, windows_directory,
                                   'SystemPropertiesPerformance.exe', 'System Properties', '#32770')
    nodes = candidate['uia']['nodes']
    require(any(n['name'] == bounded(PAGING_WARNING) and n['controlType'] == 50020 for n in nodes)
            and sum(n['name'] == 'OK' and n['controlType'] == 50000 and n['enabled'] and not n['offscreen'] for n in nodes) == 1,
            '관측된 임시 paging-file 경고 문맥이 다릅니다')
    return candidate


def search_candidate(observed, session_id, windows_directory):
    candidate = owned_os_candidate(observed, session_id, windows_directory, 'SearchHost.exe', 'Search',
        'Windows.UI.Core.CoreWindow', relative_path=ntpath.join('SystemApps',
        'MicrosoftWindows.Client.CBS_cw5n1h2txyewy', 'SearchHost.exe'), owner_only=False)
    nodes = candidate['uia']['nodes']; owner = candidate['process']['processId']
    require(nodes[0]['name'] == 'Search' and nodes[0]['className'] == 'Windows.UI.Core.CoreWindow'
            and nodes[0]['controlType'] == 50032 and nodes[0]['processId'] == owner
            and sum(n['name'] == 'Search box' and n['automationId'] == 'SearchTextBox' and
                    n['className'] == 'RichEditBox' and n['controlType'] == 50004 and n['processId'] == owner
                    and n['enabled'] and not n['offscreen'] for n in nodes) == 1,
            '관측된 Windows Search root/SearchTextBox 문맥이 다릅니다')
    child_pids = set(n['processId'] for n in nodes) - {owner}
    require(len(child_pids) <= 3 and all(pid > 0 for pid in child_pids), 'Search UIA child PID 상한이 다릅니다')
    prefix = ntpath.join(ntpath.splitdrive(windows_directory)[0] + '\\', 'Program Files (x86)',
                         'Microsoft', 'EdgeWebView', 'Application')
    for pid in child_pids:
        processes = [p for p in observed['processes'] if p['processId'] == pid]
        require(len(processes) == 1, 'Search UIA child process 바인딩이 없습니다'); process = processes[0]
        suffix = process['imagePath'][len(prefix):] if ntpath.normcase(process['imagePath']).startswith(ntpath.normcase(prefix) + '\\') else ''
        signature = process['signature']
        require(re.fullmatch(r'\\[0-9]{1,5}(?:\.[0-9]{1,5}){3}\\msedgewebview2\.exe', suffix, re.IGNORECASE)
                and process['createdFileTime'] >= candidate['process']['createdFileTime']
                and process['sessionId'] == session_id and process['processMachine'] == 0 and process['nativeMachine'] == 0xAA64
                and process['imageBytes'] > 0 and re.fullmatch('[0-9a-f]{64}', process['imageSha256'])
                and signature['status'] == 'Valid' and signature['publisherMicrosoft'] is True
                and re.search(r'(?:^|,\s*)CN=Microsoft Corporation(?:,|$)', signature['subject'])
                and re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', signature['subject']),
                'Search UIA child의 native/생성시각/session/정확 EdgeWebView 경로/서명이 다릅니다')
    candidate['boundUiaChildProcesses'] = [p for p in observed['processes'] if p['processId'] in child_pids]
    return candidate


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
             ('IsWindow', [W.HWND], W.BOOL),
             ('SendMessageTimeoutW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
             ('GetWindowRect', [W.HWND, ctypes.POINTER(W.RECT)], W.BOOL)]:
            f = getattr(self.user, name); f.argtypes = args; f.restype = result
        for name, args, result in [('GetCurrentProcess', [], W.HANDLE), ('GetCurrentProcessId', [], W.DWORD),
             ('IsWow64Process2', [W.HANDLE, ctypes.POINTER(W.WORD), ctypes.POINTER(W.WORD)], W.BOOL),
             ('OpenProcess', [W.DWORD, W.BOOL, W.DWORD], W.HANDLE), ('CloseHandle', [W.HANDLE], W.BOOL),
             ('QueryFullProcessImageNameW', [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)], W.BOOL),
             ('ProcessIdToSessionId', [W.DWORD, ctypes.POINTER(W.DWORD)], W.BOOL),
             ('GetWindowsDirectoryW', [W.LPWSTR, W.UINT], W.UINT),
             ('GetProcessTimes', [W.HANDLE, *[ctypes.POINTER(W.FILETIME)] * 4], W.BOOL)]:
            f = getattr(self.kernel, name); f.argtypes = args; f.restype = result

    def host(self):
        process = W.WORD(); native = W.WORD()
        require(self.kernel.IsWow64Process2(self.kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)),
                '실제 host native machine을 읽지 못했습니다')
        return {'processId': int(self.kernel.GetCurrentProcessId()), 'processMachine': process.value, 'nativeMachine': native.value}

    def session_id(self):
        session = W.DWORD()
        require(self.kernel.ProcessIdToSessionId(self.kernel.GetCurrentProcessId(), ctypes.byref(session)),
                '현재 controller session을 읽지 못했습니다')
        return session.value

    def windows_directory(self):
        path = ctypes.create_unicode_buffer(1024)
        size = self.kernel.GetWindowsDirectoryW(path, 1024)
        require(0 < size < 1024, 'Windows system 경로를 읽지 못했습니다')
        return path.value

    def windows(self):
        foreground = int(self.user.GetForegroundWindow() or 0); rows = []; truncated = False
        def read(hwnd, _):
            nonlocal truncated
            if any(row['hwnd'] == int(hwnd) for row in rows): return True
            if len(rows) >= MAX_WINDOWS: truncated = True; return False
            pid = W.DWORD(); tid = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not tid or not pid.value: return True
            title = ctypes.create_unicode_buffer(257); cls = ctypes.create_unicode_buffer(257); rect = W.RECT()
            self.user.GetWindowTextW(hwnd, title, 257); self.user.GetClassNameW(hwnd, cls, 257); self.user.GetWindowRect(hwnd, ctypes.byref(rect))
            rows.append({'hwnd': int(hwnd), 'processId': pid.value, 'threadId': int(tid), 'title': bounded(title.value),
                         'className': bounded(cls.value), 'visible': bool(self.user.IsWindowVisible(hwnd)),
                         'enabled': bool(self.user.IsWindowEnabled(hwnd)), 'rectangle': [rect.left, rect.top, rect.right, rect.bottom]})
            return True
        # EnumWindows may enumerate many hidden windows before the foreground.
        # Read that exact HWND first, retaining the same total bound and no input.
        if foreground: read(foreground, 0)
        callback = self.callback(read); self.user.EnumWindows(callback, 0)
        return {'foregroundHwnd': foreground, 'windows': rows, 'truncated': truncated}

    def uia(self, hwnd):
        result = {'hwnd': hwnd, 'nodes': [], 'truncated': False}
        try:
            from pywinauto.uia_defines import IUIA
            api = IUIA(); root = api.iuia.ElementFromHandle(hwnd); walker = api.iuia.ControlViewWalker; pending = [root]
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
                   'sessionId': 0, 'processMachine': None, 'nativeMachine': None,
                   'signature': {'status': 'Unavailable', 'subject': '', 'issuer': '', 'thumbprint': '', 'publisherMicrosoft': False}}
            session = W.DWORD()
            if self.kernel.ProcessIdToSessionId(pid, ctypes.byref(session)): row['sessionId'] = session.value
            handle = self.kernel.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    process = W.WORD(); native = W.WORD()
                    if self.kernel.IsWow64Process2(handle, ctypes.byref(process), ctypes.byref(native)):
                        row['processMachine'] = process.value; row['nativeMachine'] = native.value
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

    def current(self, hwnd):
        windows = self.windows(); validate_windows(windows)
        window = next((w for w in windows['windows'] if w['hwnd'] == hwnd), None)
        require(window is not None and windows['foregroundHwnd'] == hwnd,
                '관측한 OS 창이 현재 전경 창과 다릅니다')
        tree = self.uia(hwnd); validate_uia(tree, hwnd)
        pids = list(dict.fromkeys([window['processId']] + [n['processId'] for n in tree['nodes'] if n['processId']]))
        require(len(pids) <= MAX_PROCESSES, 'OS UIA 소유 process 상한을 넘었습니다')
        return {'foreground': window, 'processes': self.processes(pids), 'uia': [tree]}

    def close_verified(self, candidate):
        classifiers = {'WWAHost.exe': privacy_candidate, 'SystemPropertiesPerformance.exe': paging_candidate,
                       'SearchHost.exe': search_candidate}
        require(candidate['kind'] in classifiers, '알 수 없는 OS 창 닫기를 허용하지 않습니다')
        classifier = classifiers[candidate['kind']]
        fresh = classifier(self.current(candidate['hwnd']), self.session_id(), self.windows_directory())
        require(fresh['process'] == candidate['process'] and
                fresh.get('boundUiaChildProcesses') == candidate.get('boundUiaChildProcesses') and
                all(fresh['window'][k] == candidate['window'][k] for k in
                    ('hwnd', 'processId', 'threadId', 'title', 'className', 'visible', 'enabled')),
                '닫기 직전 OS 창/PID/생성시각/이미지/서명이 변경됐습니다')
        handle = self.kernel.OpenProcess(0x1000, False, candidate['process']['processId'])
        require(handle, '닫기 직전 소유 process handle을 열지 못했습니다')
        ownership_changed = False; post_send_error = None; exists_after = None; visible_after = None
        try:
            times = [W.FILETIME() for _ in range(4)]; process = W.WORD(); native = W.WORD()
            require(self.kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]) and
                    ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) == candidate['process']['createdFileTime']
                    and self.kernel.IsWow64Process2(handle, ctypes.byref(process), ctypes.byref(native))
                    and process.value == 0 and native.value == 0xAA64,
                    '닫기 직전 held process 생성시각/native가 변경됐습니다')
            pid = W.DWORD(); thread = self.user.GetWindowThreadProcessId(candidate['hwnd'], ctypes.byref(pid))
            require(pid.value == candidate['process']['processId'] and thread == candidate['window']['threadId'],
                    '닫기 직전 HWND 소유권이 변경됐습니다')
            require(int(self.user.GetForegroundWindow() or 0) == candidate['hwnd'],
                    '닫기 직전 전경 HWND가 변경됐습니다')
            result = ctypes.c_size_t()
            delivered = bool(self.user.SendMessageTimeoutW(candidate['hwnd'], 0x0010, 0, 0, 0x0002, 3000, ctypes.byref(result)))
            deadline = time.monotonic() + 10
            try:
                while self.user.IsWindow(candidate['hwnd']) and time.monotonic() < deadline:
                    pid = W.DWORD(); self.user.GetWindowThreadProcessId(candidate['hwnd'], ctypes.byref(pid))
                    if not pid.value and not self.user.IsWindow(candidate['hwnd']): break
                    if pid.value != candidate['process']['processId']: ownership_changed = True; break
                    time.sleep(0.1)
                exists_after = bool(self.user.IsWindow(candidate['hwnd']))
                visible_after = bool(self.user.IsWindowVisible(candidate['hwnd'])) if exists_after and not ownership_changed else False if not exists_after else None
                disappeared = not exists_after
            except Exception as error:
                post_send_error = bounded(type(error).__name__); disappeared = False
        finally: self.kernel.CloseHandle(handle)
        return {'operation': 'WM_CLOSE', 'kind': candidate['kind'], 'hwnd': candidate['hwnd'],
                'processId': candidate['process']['processId'], 'createdFileTime': candidate['process']['createdFileTime'],
                'imageSha256': candidate['process']['imageSha256'], 'messageRequests': 1,
                'verifiedOwner': fresh['process'], 'verifiedClass': fresh['window']['className'],
                'boundUiaChildProcesses': fresh.get('boundUiaChildProcesses', []),
                'livePidAndThreadRechecked': True, 'heldProcessCreationAndNativeRechecked': True, 'uiaContextRechecked': True,
                'ownershipChangedAfterSend': ownership_changed, 'messageDelivered': delivered,
                'windowExistsAfter': exists_after, 'windowVisibleAfter': visible_after,
                'postSendErrorType': post_send_error,
                'windowDisappeared': not ownership_changed and disappeared}

    def focus_probe(self):
        """현재 helper 자신의 창 하나만 만들고 focus/제거를 검증한다."""
        wndproc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        class WindowClass(ctypes.Structure):
            _fields_ = [('style', W.UINT), ('proc', wndproc), ('classExtra', ctypes.c_int), ('windowExtra', ctypes.c_int),
                        ('instance', W.HINSTANCE), ('icon', W.HICON), ('cursor', W.HANDLE), ('brush', W.HBRUSH),
                        ('menu', W.LPCWSTR), ('name', W.LPCWSTR)]
        self.kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]; self.kernel.GetModuleHandleW.restype = W.HMODULE
        for name, args, result in [
            ('DefWindowProcW', [W.HWND, W.UINT, W.WPARAM, W.LPARAM], ctypes.c_ssize_t),
            ('RegisterClassW', [ctypes.POINTER(WindowClass)], W.WORD),
            ('UnregisterClassW', [W.LPCWSTR, W.HINSTANCE], W.BOOL),
            ('CreateWindowExW', [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID], W.HWND),
            ('SetForegroundWindow', [W.HWND], W.BOOL), ('DestroyWindow', [W.HWND], W.BOOL),
            ('PeekMessageW', [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
            ('TranslateMessage', [ctypes.POINTER(W.MSG)], W.BOOL), ('DispatchMessageW', [ctypes.POINTER(W.MSG)], ctypes.c_ssize_t)]:
            api = getattr(self.user, name); api.argtypes = args; api.restype = result
        callback = wndproc(lambda hwnd, message, wparam, lparam: self.user.DefWindowProcW(hwnd, message, wparam, lparam))
        pid = int(self.kernel.GetCurrentProcessId()); instance = self.kernel.GetModuleHandleW(None)
        name = f'OpenGeulRunnerReadyOwnedProbe_{pid}'; window_class = WindowClass()
        window_class.proc = callback; window_class.instance = instance; window_class.name = name
        require(self.user.RegisterClassW(ctypes.byref(window_class)), '소유 focus probe class 생성 실패')
        hwnd = None; result = {'processId': pid, 'className': name, 'foregroundMatched': False, 'ownedWindowRemoved': False}
        try:
            hwnd = self.user.CreateWindowExW(0, name, 'OpenGeul CI owned focus probe', 0x10CF0000,
                                            20, 20, 360, 180, None, None, instance, None)
            require(hwnd, '소유 focus probe 창 생성 실패'); hwnd = int(hwnd); owner = W.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)); require(owner.value == pid, 'probe PID가 다릅니다')
            result.update({'hwnd': hwnd, 'foregroundBefore': int(self.user.GetForegroundWindow() or 0), **self.host()})
            result['setForegroundReturned'] = bool(self.user.SetForegroundWindow(hwnd))
            message = W.MSG(); deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                for _ in range(64):
                    if not self.user.PeekMessageW(ctypes.byref(message), hwnd, 0, 0, 1): break
                    self.user.TranslateMessage(ctypes.byref(message)); self.user.DispatchMessageW(ctypes.byref(message))
                if int(self.user.GetForegroundWindow() or 0) == hwnd: break
                time.sleep(0.05)
            result['foregroundAfter'] = int(self.user.GetForegroundWindow() or 0)
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            result['foregroundMatched'] = result['foregroundAfter'] == hwnd and owner.value == pid
        finally:
            if hwnd and self.user.IsWindow(hwnd):
                owner = W.DWORD(); self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                require(owner.value == pid, 'probe cleanup HWND 소유권이 다릅니다')
                self.user.DestroyWindow(hwnd)
            result['ownedWindowRemoved'] = not hwnd or not bool(self.user.IsWindow(hwnd))
            require(self.user.UnregisterClassW(name, instance), '소유 focus probe class 제거 실패')
        return result

    def screen(self, path):
        from PIL import ImageGrab
        screen = ImageGrab.grab(all_screens=False)
        require(screen.width <= 8192 and screen.height <= 8192 and screen.width * screen.height <= 20_000_000,
                '화면 픽셀 상한을 초과했습니다')
        screen.save(path, format='PNG')
        return {'width': screen.width, 'height': screen.height}


def prepare(probe, env, output):
    """검증된 OS 전경 창만 정상 닫고 helper 소유 focus probe로 준비 상태를 확인한다."""
    scope = binding(env); output = safe_output(output); output.mkdir()
    result = {'formatVersion': 1, **scope, 'diagnosticOnly': True, 'sourceQualified': False,
              'productExecuted': False, 'hostReadyQualified': False, 'readOnly': False,
              'scope': '공개 disposable ARM hosted OS 창의 정상 닫기와 helper 소유 focus만 검증',
              'helperSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'actions': [], 'inputsPerformed': 0, 'consentInputsPerformed': 0, 'registryWrites': 0,
              'processTerminations': 0, 'focusProbe': None, 'stage': 'beforeObservation'}
    try:
        before = observe(probe, env, output / 'before')
        foreground = before['foreground']
        if foreground and foreground['title'] == 'Microsoft account':
            result['stage'] = 'privacyOwnerValidation'
            candidate = privacy_candidate(before, probe.session_id(), probe.windows_directory())
            result['stage'] = 'privacyNormalClose'
            closed = probe.close_verified(candidate); result['actions'].append(closed); result['inputsPerformed'] += 1
            require(closed['messageDelivered'] and closed['windowDisappeared'], 'OS 개인정보 창의 정상 닫기가 완료되지 않았습니다')
        windows = probe.windows(); validate_windows(windows)
        foreground = next((w for w in windows['windows'] if w['hwnd'] == windows['foregroundHwnd']), None)
        if foreground and foreground['title'] == 'Search' and foreground['className'] == 'Windows.UI.Core.CoreWindow':
            result['stage'] = 'searchOwnerValidation'
            candidate = search_candidate(probe.current(foreground['hwnd']), probe.session_id(), probe.windows_directory())
            result['stage'] = 'searchNormalClose'
            closed = probe.close_verified(candidate); result['actions'].append(closed); result['inputsPerformed'] += 1
            require(closed['messageDelivered'] and closed['windowDisappeared'], '관측된 Windows Search 창의 정상 닫기가 완료되지 않았습니다')
        # Known paging-file warning is handled only if it actually becomes foreground.
        windows = probe.windows(); validate_windows(windows)
        foreground = next((w for w in windows['windows'] if w['hwnd'] == windows['foregroundHwnd']), None)
        if foreground and foreground['title'] == 'System Properties' and foreground['className'] == '#32770':
            result['stage'] = 'pagingOwnerValidation'
            candidate = paging_candidate(probe.current(foreground['hwnd']), probe.session_id(), probe.windows_directory())
            result['stage'] = 'pagingNormalClose'
            closed = probe.close_verified(candidate); result['actions'].append(closed); result['inputsPerformed'] += 1
            require(closed['messageDelivered'] and closed['windowDisappeared'], '관측된 paging-file 경고의 정상 닫기가 완료되지 않았습니다')
        result['stage'] = 'ownedFocusProbe'
        focus = probe.focus_probe(); result['focusProbe'] = focus
        require(focus['setForegroundReturned'] is True and focus['foregroundMatched'] is True and focus['ownedWindowRemoved'] is True,
                'helper 소유 창의 실제 foreground/cleanup 검증이 통과하지 않았습니다')
        result['hostReadyQualified'] = True; result['stage'] = 'complete'
    except Exception as error:
        result['errorType'] = bounded(type(error).__name__)
    finally:
        try:
            observe(probe, env, output / 'after')
            result['afterObservationRetained'] = True
        except Exception as error:
            result['afterObservationRetained'] = False; result['afterErrorType'] = bounded(type(error).__name__)
            result['hostReadyQualified'] = False
        raw = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        require(len(raw) <= MAX_JSON, '준비 결과 JSON 상한을 초과했습니다')
        with (output / 'preparation.json').open('xb') as stream: stream.write(raw)
    require(result['hostReadyQualified'], 'ARM hosted runner 준비가 완료되지 않았습니다')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true', help='검증된 OS 창만 WM_CLOSE로 정상 닫고 owned focus를 검증')
    args = parser.parse_args(); binding(os.environ)
    if args.prepare:
        value = prepare(WindowsProbe(), os.environ, args.output)
        print(json.dumps({'hostReadyQualified': value['hostReadyQualified'], 'inputsPerformed': value['inputsPerformed'],
                          'sourceQualified': False, 'productExecuted': False}, ensure_ascii=False))
        return
    value = observe(WindowsProbe(), os.environ, args.output)
    print(json.dumps({'observationCompleted': True, 'windows': len(value['windowObservation']['windows']),
                      'inputsPerformed': 0, 'sourceQualified': False}, ensure_ascii=False))


if __name__ == '__main__': main()
