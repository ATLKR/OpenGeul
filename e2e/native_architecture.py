"""제품 PE와 소유한 실제 Windows PID의 네이티브 아키텍처를 확인한다."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from releasekit import pe_machine
from windows_arch import machine_for, require_architecture


def _require(condition, message):
    if not condition:raise ValueError(message)


class WindowsProbe:
    """외부 handle은 닫지 않고 이 probe가 연 query handle만 정리한다."""
    def __init__(self):
        if os.name != 'nt':raise ValueError('실제 Windows process 관측이 필요합니다')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.api.GetProcessId.argtypes = [wintypes.HANDLE]
        self.api.GetProcessId.restype = wintypes.DWORD
        self.api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                      wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.api.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.api.IsWow64Process2.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.WORD),
                                           ctypes.POINTER(wintypes.WORD)]
        self.api.IsWow64Process2.restype = wintypes.BOOL
        self.api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.api.GetExitCodeProcess.restype = wintypes.BOOL
        self.api.GetPackageFullName.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
        self.api.GetPackageFullName.restype = wintypes.LONG

    def processes(self):
        """소유 관계를 고르기 위한 snapshot metadata만 읽는다."""
        class Entry(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                        ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                        ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                        ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                        ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR*260)]
        self.api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ('Process32FirstW', 'Process32NextW'):
            function = getattr(self.api, name)
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
            function.restype = wintypes.BOOL
        snapshot = self.api.CreateToolhelp32Snapshot(2, 0)
        _require(snapshot not in (None, ctypes.c_void_p(-1).value), 'process snapshot을 열 수 없습니다')
        try:
            entry = Entry();entry.dwSize = ctypes.sizeof(entry)
            _require(self.api.Process32FirstW(snapshot, ctypes.byref(entry)), 'process snapshot이 비어 있습니다')
            result = []
            while True:
                result.append({'processId': entry.th32ProcessID, 'parentProcessId': entry.th32ParentProcessID,
                               'executableName': entry.szExeFile})
                _require(len(result) <= 10000, 'process snapshot 크기를 초과했습니다')
                if not self.api.Process32NextW(snapshot, ctypes.byref(entry)):
                    _require(ctypes.get_last_error() == 18, 'process snapshot을 완전히 읽을 수 없습니다')
                    break
            return result
        finally:self.api.CloseHandle(snapshot)

    def inspect(self, pid, handle=None):
        _require(type(pid) is int and pid > 0, '소유한 process PID가 올바르지 않습니다')
        own = handle is None
        if own:handle = self.api.OpenProcess(0x1000, False, pid)
        _require(handle is not None and int(handle) > 0, '소유한 process query handle을 열 수 없습니다')
        try:
            actual_pid = self.api.GetProcessId(handle)
            _require(actual_pid == pid, 'query handle의 process PID가 다릅니다')
            path = ctypes.create_unicode_buffer(32768);length = wintypes.DWORD(len(path))
            _require(self.api.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)),
                     '소유한 process 실행 경로를 확인할 수 없습니다')
            process, native = wintypes.WORD(), wintypes.WORD()
            _require(self.api.IsWow64Process2(handle, ctypes.byref(process), ctypes.byref(native)),
                     'IsWow64Process2 아키텍처 관측에 실패했습니다')
            exit_code = wintypes.DWORD()
            _require(self.api.GetExitCodeProcess(handle, ctypes.byref(exit_code)), 'process 상태 관측에 실패했습니다')
            size = wintypes.UINT(0)
            status = self.api.GetPackageFullName(handle, ctypes.byref(size), None)
            package = None
            if status == 122:
                _require(0 < size.value <= 32768, 'process package identity 크기가 올바르지 않습니다')
                name = ctypes.create_unicode_buffer(size.value)
                _require(self.api.GetPackageFullName(handle, ctypes.byref(size), name) == 0,
                         'process package identity 관측에 실패했습니다')
                package = name.value
            else:_require(status == 15700, 'process package identity 응답이 올바르지 않습니다')
            return {'processId': actual_pid, 'imagePath': path.value,
                    'processMachine': process.value, 'nativeMachine': native.value,
                    'exitCode': exit_code.value, 'packageFullName': package}
        finally:
            if own:self.api.CloseHandle(handle)


def verify_host(architecture, *, probe=None):
    architecture = require_architecture(architecture)
    record = (probe or WindowsProbe()).inspect(os.getpid())
    _require(record['processId'] == os.getpid() and type(record['nativeMachine']) is int
             and record['nativeMachine'] == machine_for(architecture), '실제 Windows 호스트 아키텍처가 다릅니다')
    process = record['processMachine']
    _require(type(process) is int and (process == 0 or
             architecture == 'arm64' and process == 0x8664), '지원한 native 또는 x64 controller가 아닙니다')
    return {'architecture': architecture, 'nativeMachine': record['nativeMachine'],
            'controller': {'processId': record['processId'], 'processMachine': process,
                           'architecture': architecture if process == 0 else 'x64-emulated',
                           'native': process == 0}}


def verify_executable(executable, architecture='x64'):
    architecture = require_architecture(architecture)
    executable = Path(executable)
    _require(executable.is_file() and not executable.is_symlink() and
             0 < executable.stat().st_size <= 96*1024*1024, '정규 제품 실행 파일이 필요합니다')
    with executable.open('rb') as stream:return pe_machine(stream.read(4096), architecture)


def verify_process(pid, executable, architecture='x64', *, handle=None, package_full_name=None, probe=None):
    architecture = require_architecture(architecture)
    _require(type(pid) is int and pid > 0, '소유한 제품 PID가 올바르지 않습니다')
    executable = Path(executable);machine = verify_executable(executable, architecture)
    api = probe or WindowsProbe()
    host = verify_host(architecture, probe=api)
    record = api.inspect(pid, handle)
    _require(type(record['processId']) is int and record['processId'] == pid,
             '관측한 제품 PID가 소유한 PID와 다릅니다')
    image = Path(record['imagePath'])
    _require(image.is_file() and image.samefile(executable), '제품 PID가 다른 실행 파일을 사용합니다')
    _require(type(record['processMachine']) is int and record['processMachine'] == 0
             and type(record['nativeMachine']) is int and record['nativeMachine'] == machine_for(architecture),
             '제품 process는 기대한 아키텍처의 네이티브 실행이 아닙니다')
    if package_full_name is not None:
        _require(isinstance(package_full_name, str) and package_full_name and
                 record['packageFullName'] == package_full_name, '제품 process의 설치 package identity가 다릅니다')
    return {'architecture': architecture, 'processId': pid, 'imagePath': str(executable.resolve()),
            'peMachine': machine, 'processMachine': record['processMachine'],
            'nativeMachine': record['nativeMachine'], 'native': True,
            'runningAtInspection': record['exitCode'] == 259, 'packageFullName': record['packageFullName'],
            'sha256': hashlib.sha256(executable.read_bytes()).hexdigest(), 'bytes': executable.stat().st_size,
            'controller': host['controller'], 'helperSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'sourceCommit': os.getenv('GITHUB_SHA'), 'sourceRun': os.getenv('GITHUB_RUN_ID'),
            'runAttempt': os.getenv('GITHUB_RUN_ATTEMPT')}


def verify_webview2(root_pid, architecture='x64', *, probe=None):
    """소유한 GUI의 후손만 query하고 실제 WebView2 native 실행을 확인한다."""
    architecture = require_architecture(architecture)
    _require(type(root_pid) is int and root_pid > 0, '소유한 GUI PID가 올바르지 않습니다')
    api = probe or WindowsProbe();rows = api.processes()
    _require(isinstance(rows, list) and 0 < len(rows) <= 10000, 'process snapshot 크기가 올바르지 않습니다')
    by_pid = {}
    for row in rows:
        pid, parent, name = row['processId'], row['parentProcessId'], row['executableName']
        _require(type(pid) is int and pid >= 0 and type(parent) is int and parent >= 0
                 and isinstance(name, str) and len(name) <= 260 and pid not in by_pid,
                 'process snapshot identity가 올바르지 않습니다')
        by_pid[pid] = row
    descendants = {root_pid}
    while True:
        children = {pid for pid, row in by_pid.items() if row['parentProcessId'] in descendants}
        expanded = descendants | children
        if expanded == descendants:break
        descendants = expanded
    owned = [row for pid, row in sorted(by_pid.items()) if pid != root_pid and pid in descendants
             and row['executableName'].isascii() and row['executableName'].lower() == 'msedgewebview2.exe']
    _require(owned and len(owned) <= 64, '소유한 실제 WebView2 process가 없습니다')
    proofs = []
    for row in owned:
        actual = api.inspect(row['processId']);image = Path(actual['imagePath'])
        _require(image.name.isascii() and image.name.lower() == 'msedgewebview2.exe',
                 'WebView2 PID가 다른 실제 실행 파일을 사용합니다')
        proof = verify_process(row['processId'], image, architecture, probe=api)
        proofs.append({key: proof[key] for key in ('processId', 'imagePath', 'peMachine', 'processMachine',
                                                  'nativeMachine', 'sha256', 'bytes', 'runningAtInspection')}
                      | {'parentProcessId': row['parentProcessId']})
    _require(any(item['runningAtInspection'] for item in proofs), '소유한 WebView2 process가 실행 중이 아닙니다')
    return {'rootProcessId': root_pid, 'architecture': architecture, 'processes': proofs,
            'helperSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _fresh(path):
    _require(not path.exists() and not path.is_symlink(), '기존 아키텍처 증거를 덮어쓰지 않습니다')


def _write(path, data):
    _fresh(path);path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:stream.write(data)


def run_cli(executable, architecture, output, help_output, *, package_full_name=None,
            probe=None, process_factory=subprocess.Popen):
    """자신이 시작한 CLI handle을 관측하고 성공한 help/증거만 보존한다."""
    architecture = require_architecture(architecture)
    executable, output, help_output = Path(executable), Path(output), Path(help_output)
    _fresh(output);_fresh(help_output)
    _require(output.resolve() != help_output.resolve(), 'CLI 증거와 도움말 경로가 같습니다')
    verify_executable(executable, architecture)
    if package_full_name is not None:
        _require(isinstance(package_full_name, str) and package_full_name,
                 '기대한 CLI package identity가 올바르지 않습니다')
    verify_host(architecture, probe=probe)
    process = process_factory([str(executable), '--help'], cwd=executable.parent,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        _require(hasattr(process, '_handle'), '소유한 Windows CLI handle이 없습니다')
        native = verify_process(process.pid, executable, architecture, handle=int(process._handle),
                                package_full_name=package_full_name, probe=probe)
        data, _ = process.communicate(timeout=30)
        _require(process.returncode == 0 and isinstance(data, bytes) and len(data) <= 1024*1024,
                 '제품 CLI가 정상 종료하지 않았거나 도움말 크기를 초과했습니다')
        _require(re.search('rhwp|usage|사용', data.decode('utf-8', errors='replace'), re.IGNORECASE),
                 '제품 CLI 도움말이 올바르지 않습니다')
        proof = {'success': True, 'exitCode': process.returncode,
                 'packageFullName': native['packageFullName'],
                 'nativeArchitecture': native, 'helpBytes': len(data),
                 'helpSha256': hashlib.sha256(data).hexdigest()}
        _write(help_output, data)
        _write(output, (json.dumps(proof, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
        return proof
    finally:
        if process.poll() is None:
            process.kill();process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser();commands = parser.add_subparsers(dest='command', required=True)
    for name in ('host', 'process', 'cli'):
        child = commands.add_parser(name)
        child.add_argument('--architecture', choices=('x64','arm64'), default='x64')
        child.add_argument('--output', type=Path, required=True)
        if name != 'host':
            child.add_argument('--executable', type=Path, required=True)
            child.add_argument('--package-full-name')
        if name == 'process':
            child.add_argument('--pid', type=int, required=True)
            child.add_argument('--webview2', action='store_true')
        if name == 'cli':child.add_argument('--help-output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'cli':
        proof = run_cli(args.executable, args.architecture, args.output, args.help_output,
                        package_full_name=args.package_full_name)
    else:
        _fresh(args.output)
        proof = verify_host(args.architecture) if args.command == 'host' else verify_process(
            args.pid, args.executable, args.architecture, package_full_name=args.package_full_name)
        if args.command == 'process' and args.webview2:
            proof['webview2Native'] = verify_webview2(args.pid, args.architecture)
        _write(args.output, (json.dumps(proof, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'architecture': args.architecture, 'nativeProcessVerified': args.command != 'host',
                      'processId': proof.get('processId', proof.get('nativeArchitecture', {}).get('processId')),
                      'sha256': proof.get('sha256', proof.get('nativeArchitecture', {}).get('sha256'))}))


if __name__ == '__main__':
    try:main()
    except Exception:
        raise SystemExit('실제 제품 아키텍처 검사에 실패했습니다. 기존 증거는 보존합니다.') from None
