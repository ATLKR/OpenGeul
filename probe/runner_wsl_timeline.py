"""고정 공개 ARM 진단의 WSL 자연 수명 관측. OS 입력/종료 없음."""
import ctypes
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ready_reader', ROOT / 'e2e/runner-ready.py')
ready = importlib.util.module_from_spec(spec); spec.loader.exec_module(ready)
BRANCH = 'refs/heads/diagnostic/source81-wsl-timeline'


def main():
    env = os.environ
    ready.require(env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_ENVIRONMENT') == 'github-hosted'
        and env.get('GITHUB_REPOSITORY') == ready.REPOSITORY and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
        and env.get('GITHUB_REF') == BRANCH and env.get('GITHUB_JOB') == 'observe'
        and env.get('GITHUB_WORKFLOW_REF') == f'{ready.REPOSITORY}/.github/workflows/store-package.yml@{BRANCH}'
        and env.get('GITHUB_RUN_ATTEMPT') == '1', '고정 읽기 전용 hosted 진단 경계가 다릅니다')
    event, event_hash = ready.public_event(env)
    ready.require(ready.event_actor(event, env) == ('ATLKR', 65988341, 'User'), '진단 actor가 다릅니다')
    source = ready.commit_sha(env.get('GITHUB_SHA')); run = ready.decimal(env.get('GITHUB_RUN_ID'))
    out = ready.safe_output(Path('wsl-timeline')); out.mkdir()
    probe = ready.WindowsProbe(); host = probe.host()
    ready.require(host['nativeMachine'] == 0xAA64 and host['processMachine'] in (0, 0x8664), 'ARM host가 아닙니다')
    probe.kernel.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
    probe.kernel.GetExitCodeProcess.restype = W.BOOL
    record = {'sourceCommit': source, 'runId': run, 'runAttempt': 1, 'eventSha256': event_hash,
        'diagnosticOnly': True, 'sourceQualified': False, 'productExecuted': False, 'readOnly': True,
        'inputsPerformed': 0, 'registryWrites': 0, 'processTerminations': 0, 'controller': host,
        'helperSha256': hashlib.sha256((ROOT / 'e2e/runner-ready.py').read_bytes()).hexdigest(),
        'observerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'samples': [],
        'boundWindow': None, 'boundProcess': None, 'naturalProcessExitObserved': False}
    held = None; started = time.monotonic(); expected = ntpath.join(probe.windows_directory(), 'System32', 'wsl.exe')
    try:
        probe.screen(out / 'before.png')
        while time.monotonic() - started < 90:
            rows = probe.windows(); ready.validate_windows(rows)
            fore = next((w for w in rows['windows'] if w['hwnd'] == rows['foregroundHwnd']), None)
            sample = {'elapsedMs': round((time.monotonic() - started) * 1000), 'foregroundHwnd': rows['foregroundHwnd'],
                'foregroundProcessId': fore['processId'] if fore else None,
                'foregroundThreadId': fore['threadId'] if fore else None,
                'foregroundClass': fore['className'] if fore else None}
            candidates = [w for w in rows['windows'] if w['className'] == 'ConsoleWindowClass'
                and ntpath.normcase(w['title']) == ntpath.normcase(expected) and w['visible'] and w['enabled']]
            if held is None and candidates:
                ready.require(len(candidates) == 1, '관측 WSL 창이 하나가 아닙니다')
                window = candidates[0]; process = probe.processes([window['processId']])[0]; signature = process['signature']
                ready.require(ntpath.normcase(process['imagePath']) == ntpath.normcase(expected)
                    and process['createdFileTime'] > 0 and process['sessionId'] == probe.session_id()
                    and process['processMachine'] == 0 and process['nativeMachine'] == 0xAA64
                    and process['imageBytes'] > 0 and len(process['imageSha256']) == 64
                    and signature['status'] == 'Valid' and signature['publisherMicrosoft'] is True
                    and 'CN=Microsoft Windows,' in signature['subject'] and 'O=Microsoft Corporation,' in signature['subject'],
                    '관측 WSL 실제 경로/native/session/서명이 다릅니다')
                held = probe.kernel.OpenProcess(0x1000, False, window['processId']); ready.require(held, 'held WSL 조회 실패')
                record.update(boundWindow=window, boundProcess=process)
            if held:
                window = record['boundWindow']; process = record['boundProcess']; exists = bool(probe.user.IsWindow(window['hwnd']))
                exit_code = W.DWORD(); ready.require(probe.kernel.GetExitCodeProcess(held, ctypes.byref(exit_code)), 'held exit 조회 실패')
                owner = W.DWORD(); thread = probe.user.GetWindowThreadProcessId(window['hwnd'], ctypes.byref(owner)) if exists else 0
                times = [W.FILETIME() for _ in range(4)]; native = W.WORD(); machine = W.WORD()
                ready.require(probe.kernel.GetProcessTimes(held, *[ctypes.byref(t) for t in times])
                    and ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) == process['createdFileTime']
                    and probe.kernel.IsWow64Process2(held, ctypes.byref(machine), ctypes.byref(native))
                    and machine.value == 0 and native.value == 0xAA64, 'held WSL identity 변경')
                ready.require(not exists or (owner.value == process['processId'] and thread == window['threadId']), 'WSL HWND owner 변경')
                sample.update(windowExists=exists, visible=bool(probe.user.IsWindowVisible(window['hwnd'])) if exists else False,
                    heldExitCode=exit_code.value, sameWindowForeground=rows['foregroundHwnd'] == window['hwnd'])
                if exit_code.value != 259:
                    ready.require(not exists, '종료된 WSL HWND가 남았습니다')
                    record['naturalProcessExitObserved'] = True; record['samples'].append(sample); break
            record['samples'].append(sample); time.sleep(0.5)
    except Exception as error:
        record['errorType'] = type(error).__name__
    finally:
        if held: probe.kernel.CloseHandle(held)
        record['durationMs'] = round((time.monotonic() - started) * 1000)
        probe.screen(out / 'after.png')
        raw = (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode()
        ready.require(len(raw) <= 256 * 1024, '관측 JSON 상한 초과'); (out / 'timeline.json').write_bytes(raw)
    ready.require('errorType' not in record, '읽기 전용 timeline identity 실패')
    print(json.dumps({'readOnly': True, 'wslObserved': held is not None,
        'naturalProcessExitObserved': record['naturalProcessExitObserved'], 'sourceQualified': False}))


if __name__ == '__main__': main()
