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
    ready.require(hashlib.sha256((ROOT / 'e2e/runner-ready.py').read_bytes()).hexdigest() == '4b0583eece75b37d2f8c4d811bd7eca6833418153f1c5a2111b790b423b9f464', 'production lifecycle helper bytes 다름')
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
        'boundWindow': None, 'boundProcess': None, 'naturalProcessExitObserved': False,
        'productionCandidateCommit': '60b40844cf76b4a8e300d2fe951346fded343f2a',
        'postExitBoundImageCompositeQualified': False, 'foregroundWaitPredicateExercised': False,
        'discoveryLimitSeconds': 20, 'targetWaitLimitSeconds': 65}
    held = None; started = time.monotonic(); discovery_deadline = started + 20; deadline = None; target_started = None; expected = ntpath.join(probe.windows_directory(), 'System32', 'wsl.exe')
    try:
        probe.screen(out / 'before.png')
        while True:
            ready.require(time.monotonic() < (deadline if held else discovery_deadline),
                'targeted wait deadline 초과' if held else 'bounded discovery에서 live WSL 미관측')
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
                target_started = time.monotonic(); deadline = target_started + 65
                record['discoveryDurationMs'] = round((target_started - started) * 1000)
                record['targetStartElapsedMs'] = record['discoveryDurationMs']
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
                initial = probe.startup_process_state(held, process['processId'])
                ready.require(initial['createdFileTime'] == process['createdFileTime'] and initial['sessionId'] == process['sessionId']
                    and initial['processMachine'] == 0 and initial['nativeMachine'] == 0xAA64 and initial['exitCode'] == 259, 'live held identity 변경')
                record['liveBoundImage'] = probe.bound_image(expected, deadline=deadline)
                ready.require(record['liveBoundImage']['bytes'] == process['imageBytes']
                    and record['liveBoundImage']['sha256'] == process['imageSha256']
                    and record['liveBoundImage']['signature'] == process['signature'], 'live process/file fingerprint 변경')
            if held:
                window = record['boundWindow']; process = record['boundProcess']; exists = bool(probe.user.IsWindow(window['hwnd']))
                state = probe.startup_process_state(held, process['processId'])
                owner = W.DWORD(); thread = probe.user.GetWindowThreadProcessId(window['hwnd'], ctypes.byref(owner)) if exists else 0
                ready.require(state['createdFileTime'] == process['createdFileTime']
                    and state['sessionId'] == process['sessionId'] == probe.session_id()
                    and state['processMachine'] == 0 and state['nativeMachine'] == 0xAA64, 'held WSL identity 변경')
                ready.require(not exists or (owner.value == process['processId'] and thread == window['threadId']), 'WSL HWND owner 변경')
                sample['targetElapsedMs'] = round((time.monotonic() - target_started) * 1000)
                sample.update(windowExists=exists, visible=bool(probe.user.IsWindowVisible(window['hwnd'])) if exists else False,
                    heldExitCode=state['exitCode'], sameWindowForeground=rows['foregroundHwnd'] == window['hwnd'])
                if state['exitCode'] != 259:
                    ready.require(not exists, '종료된 WSL HWND가 남았습니다')
                    record['naturalProcessExitObserved'] = True; record['samples'].append(sample)
                    record['postExitHeldIdentity'] = state
                    record['postExitImage'] = probe.bound_image(expected, deadline=deadline)
                    record['boundImageEqual'] = record['postExitImage'] == record['liveBoundImage']
                    ready.require(record['boundImageEqual'], 'bound post-exit disk image 변경')
                    ready.require(probe.startup_process_state(held, process['processId']) == state
                        and not probe.user.IsWindow(window['hwnd']), 'post-image held identity/window 변경')
                    ready.require(time.monotonic() <= deadline, '65초 composite deadline 초과')
                    record['postExitBoundImageCompositeQualified'] = True
                    record['targetWaitDurationMs'] = round((time.monotonic() - target_started) * 1000)
                    break
            record['samples'].append(sample)
            remaining = (deadline if held else discovery_deadline) - time.monotonic()
            ready.require(remaining > 0, 'bounded observation deadline 초과')
            time.sleep(min(0.5, remaining))
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
        'naturalProcessExitObserved': record['naturalProcessExitObserved'],
        'postExitBoundImageCompositeQualified': record['postExitBoundImageCompositeQualified'], 'sourceQualified': False}))


if __name__ == '__main__': main()
