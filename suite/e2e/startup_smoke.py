"""Bounded actual-Windows Calc/Writer startup stress, with no retry-to-green.

Run against fresh engine-smoke fixtures before a keyboard-edit smoke run changes
those fixture bytes. Every attempt launches and closes one owned Suite shell;
failures are retained while all remaining planned attempts still run.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

import windows_smoke as native

CYCLE = (('calc', 'existing'), ('calc', 'new'), ('writer', 'existing'), ('writer', 'new'))
EXTENSIONS = {'calc': 'xlsx', 'writer': 'docx'}


def build_plan(attempts):
    if type(attempts) is not int or attempts not in (20, 40):
        raise ValueError('Startup stress requires exactly 20 or 40 bounded attempts')
    return [dict(attempt=index + 1, module=CYCLE[index % 4][0], mode=CYCLE[index % 4][1],
                 case=f'attempt-{index + 1:03d}-{CYCLE[index % 4][1]}-{CYCLE[index % 4][0]}')
            for index in range(attempts)]


def mark_stage(record, stage):
    record['stage'] = stage
    record['steps'].append(stage)


def record_exception(record, exc):
    record.update(success=False, exception=type(exc).__name__ + ': ' + str(exc),
                  traceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def owned_windows(api, process):
    """Snapshot only HWNDs owned by the shell launched for this attempt."""
    return [dict(hwnd=int(hwnd), pid=api.pid(hwnd), title=api.title(hwnd),
                 className=api.class_name(hwnd), ownerHwnd=int(api.user.GetWindow(hwnd, 4) or 0),
                 parentHwnd=int(api.user.GetPropW(hwnd, 'OpenGeul.Office.ParentHwnd') or 0),
                 childHwnd=int(api.user.GetPropW(hwnd, 'OpenGeul.Office.ChildHwnd') or 0))
            for hwnd in api.windows(process.pid)]



class EngineProcessWitness:
    """Read-only handle retained from the verified embedded engine before close."""
    def __init__(self, pid):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.close_handle = kernel.CloseHandle
        self.close_handle.argtypes, self.close_handle.restype = (wintypes.HANDLE,), wintypes.BOOL
        self.wait = kernel.WaitForSingleObject
        self.wait.argtypes, self.wait.restype = (wintypes.HANDLE, wintypes.DWORD), wintypes.DWORD
        self.exit_code = kernel.GetExitCodeProcess
        self.exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        self.exit_code.restype = wintypes.BOOL
        open_process = kernel.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        get_times = kernel.GetProcessTimes
        get_times.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        get_times.restype = wintypes.BOOL
        self.handle = open_process(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not get_times(self.handle, ctypes.byref(created), ctypes.byref(exited),
                             ctypes.byref(kernel_time), ctypes.byref(user_time)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.creation_time = (created.dwHighDateTime << 32) | created.dwLowDateTime
            assert self.creation_time > 0, 'Owned engine creation identity is missing'
        except Exception:
            self.close()
            raise

    def exited(self, seconds):
        result = self.wait(self.handle, int(seconds * 1000))
        if result == 258: return False
        if result != 0: raise ctypes.WinError(ctypes.get_last_error())
        return True

    def code(self):
        result = wintypes.DWORD()
        if not self.exit_code(self.handle, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(result.value)

    def close(self):
        if self.handle:
            self.close_handle(self.handle)
            self.handle = None


def run_native_attempt(suite, fixtures, output, attempt):
    """Run one launch once. Cleanup cannot convert its original failure to success."""
    record = dict(attempt, success=False, stage='case-setup', steps=['case-setup'],
                  exception=None, traceback='', shellPid=None, windowHwnd=None, parentHwnd=None,
                  childHwnd=None, officePid=None, ownedWindows=[], cleanClose=False,
                  nativeParentVerified=False, noExternalOfficeWindow=False,
                  stderrLog=attempt['case'] + '-stderr.log', stderrCaptured=False,
                  screenshot=None, screenshotCaptured=False, forcedCleanupRequired=False)
    process = api = source = before = engine = None
    started = time.monotonic()
    try:
        module, mode = attempt['module'], attempt['mode']
        command = native.new_document_command(suite, module)
        if mode == 'existing':
            mark_stage(record, 'verify-engine-fixture')
            source = native.require_engine_fixture(fixtures, module, EXTENSIONS[module])
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            record.update(file=source.name, beforeSha256=before)
            command += ['--file', str(source)]
        mark_stage(record, 'launch')
        process = native.launch_suite(command, suite, output, attempt['case'])
        record['shellPid'] = process.pid
        api = native.Windows()
        mark_stage(record, 'attach')
        hwnd, parent, child, office_pid = native.verified_attachment(api, process, module)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid,
                      title=api.title(hwnd), nativeParentVerified=True,
                      noExternalOfficeWindow=True, ownedWindows=owned_windows(api, process))
        mark_stage(record, 'capture-engine-identity')
        engine = EngineProcessWitness(office_pid)
        record['officeCreationTime'] = engine.creation_time
        assert api.pid(child) == office_pid and api.user.IsWindow(child), 'Embedded engine identity changed during capture'
        mark_stage(record, 'capture-attached')
        from pywinauto import Desktop
        screenshot = attempt['case'] + '-attached.png'
        Desktop(backend='win32').window(handle=hwnd).wrapper_object().capture_as_image().save(output / screenshot)
        record.update(screenshot=screenshot, screenshotCaptured=True)
        assert not api.windows(office_pid), api.external_window_message(office_pid, 'Office created an unowned visible top-level window')
        mark_stage(record, 'close-document')
        api.request_close(hwnd, process.pid)
        mark_stage(record, 'wait-document-close')
        native.wait_for(lambda: not api.user.IsWindow(hwnd), seconds=20)
        mark_stage(record, 'wait-editor-close')
        native.wait_for(lambda: not api.user.IsWindow(child), seconds=10)
        mark_stage(record, 'find-home')
        home = native.wait_for(lambda: api.home(process), seconds=10)
        record['homeHwnd'] = int(home)
        mark_stage(record, 'close-home')
        api.request_close(home, process.pid)
        mark_stage(record, 'wait-shell-exit')
        process.wait(timeout=25)
        record['shellExitCode'] = process.returncode
        assert process.returncode == 0, 'Suite shell did not close cleanly'
        assert not api.user.IsWindow(hwnd) and not api.user.IsWindow(child) and not api.user.IsWindow(home), 'Owned test windows survived normal shutdown'
        assert not api.windows(process.pid), 'Owned shell windows survived normal shutdown'
        mark_stage(record, 'wait-engine-exit')
        record['officeExited'] = engine.exited(10)
        assert record['officeExited'], 'Owned Office engine survived normal shutdown'
        record['officeExitCode'] = engine.code()
        record['cleanClose'] = True
        if source is not None:
            mark_stage(record, 'verify-final-fixture')
            after = hashlib.sha256(source.read_bytes()).hexdigest()
            record.update(afterSha256=after, fixtureUnchanged=before == after)
            assert before == after, 'Startup-only test changed the generated fixture bytes'
        mark_stage(record, 'complete')
        record['success'] = True
    except Exception as exc:
        record_exception(record, exc)
        if api is not None and process is not None:
            try:
                record['ownedWindowsAtFailure'] = owned_windows(api, process)
            except Exception as snapshot_error:
                record['ownedWindowSnapshotError'] = type(snapshot_error).__name__ + ': ' + str(snapshot_error)
        try:
            from PIL import ImageGrab
            screenshot = attempt['case'] + '-failure.png'
            ImageGrab.grab().save(output / screenshot)
            record.update(screenshot=screenshot, screenshotCaptured=True)
        except Exception as screenshot_error:
            record['screenshotError'] = type(screenshot_error).__name__ + ': ' + str(screenshot_error)
    finally:
        if process is not None:
            record['forcedCleanupRequired'] = process.poll() is None
            native.stop_owned_test_process(process, record)
            record['cleanupShellExitCode'] = process.poll()
        if engine is not None:
            try:
                record['officeExitedAfterCleanup'] = engine.exited(5)
                if not record['officeExitedAfterCleanup']:
                    record.update(success=False, cleanupError='Owned Office engine survived bounded cleanup')
            except Exception as cleanup_error:
                record.update(success=False, cleanupError=type(cleanup_error).__name__ + ': ' + str(cleanup_error))
            finally:
                engine.close()
        stderr = output / record['stderrLog']
        try:
            if stderr.is_file():
                record.update(stderrCaptured=True, stderrText=stderr.read_text(encoding='utf-8', errors='replace'))
        except Exception as stderr_error:
            record.update(success=False, stderrReadError=type(stderr_error).__name__ + ': ' + str(stderr_error))
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return record


def evidence_errors(record, expected):
    errors = []
    for key in ('attempt', 'module', 'mode'):
        if record.get(key) != expected[key]: errors.append('identity:' + key)
    for key in ('success', 'cleanClose', 'nativeParentVerified', 'noExternalOfficeWindow',
                'stderrCaptured', 'screenshotCaptured', 'officeExited'):
        if record.get(key) is not True: errors.append(key)
    for key in ('shellPid', 'windowHwnd', 'parentHwnd', 'childHwnd', 'officePid', 'officeCreationTime'):
        if type(record.get(key)) is not int or record[key] <= 0: errors.append(key)
    if record.get('shellPid') == record.get('officePid'): errors.append('separateOfficePid')
    if record.get('stage') != 'complete': errors.append('stage')
    if record.get('shellExitCode') != 0: errors.append('shellExitCode')
    if record.get('exception') is not None: errors.append('exception')
    if record.get('forcedCleanupRequired') is not False: errors.append('forcedCleanupRequired')
    for key in ('cleanupError', 'recordWriteError', 'stderrReadError'):
        if record.get(key): errors.append(key)
    if not record.get('stderrLog') or not record.get('screenshot'): errors.append('evidencePaths')
    if expected['mode'] == 'existing' and record.get('fixtureUnchanged') is not True:
        errors.append('fixtureUnchanged')
    return errors


def stress_report(records, attempts):
    plan = build_plan(attempts)
    expected = {attempt['case']: attempt for attempt in plan}
    counts = Counter(record.get('case') for record in records)
    missing = [case for case in expected if case not in counts]
    duplicates = sorted(str(case) for case, count in counts.items() if count > 1)
    unexpected = sorted(str(case) for case in counts if case not in expected)
    failures, invalid = [], {}
    for record in records:
        case = record.get('case')
        errors = evidence_errors(record, expected[case]) if case in expected else ['unexpectedAttempt']
        if errors:
            failures.append(case)
            invalid[str(case)] = errors
    out_of_order = [record.get('case') for record in records] != [attempt['case'] for attempt in plan]
    return dict(schemaVersion=1, kind='native-startup-stress', success=not (
                    failures or missing or duplicates or unexpected or out_of_order),
                imeVerified=False, expectedAttemptCount=attempts, completedAttemptCount=len(records),
                passedAttemptCount=len(records) - len(failures), failedAttempts=failures,
                missingAttempts=missing, duplicateAttempts=duplicates, unexpectedAttempts=unexpected,
                outOfOrder=out_of_order, invalidEvidence=invalid, attempts=records)


def run_attempts(plan, run, output, attempts):
    records = []
    for attempt in plan:
        try:
            record = dict(run(attempt))
        except Exception as exc:
            record = dict(attempt, stage='case-setup')
            record_exception(record, exc)
        try:
            native.write_result(output, attempt['case'], record)
        except Exception as exc:
            record.update(success=False, recordWriteError=type(exc).__name__ + ': ' + str(exc))
        records.append(record)
        print(attempt['case'] + ': ' + ('passed' if record.get('success') is True else
              'FAILED at ' + record.get('stage', 'unknown') + ': ' + str(record.get('exception') or record.get('cleanupError') or 'missing success')), flush=True)
    report = stress_report(records, attempts)
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f"Startup attempts: {report['passedAttemptCount']}/{attempts} passed; success={report['success']}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--attempts', type=int, choices=(20, 40), default=20)
    args = parser.parse_args()
    if os.name != 'nt': raise RuntimeError('Actual Windows GUI execution is required')
    if not __debug__: raise RuntimeError('Do not disable native GUI assertions with Python -O')
    for path in (args.suite, args.fixtures, args.output):
        assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Linked Suite/fixture/evidence directories are not accepted'
    suite, fixtures, output = args.suite.resolve(), args.fixtures.resolve(), args.output.resolve()
    assert suite != output and suite not in output.parents, 'Evidence must be outside the payload'
    assert fixtures != output and fixtures not in output.parents, 'Evidence must be outside generated fixtures'
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output)), 'Only local test paths are accepted'
    output.mkdir(parents=True, exist_ok=False)
    plan = build_plan(args.attempts)
    report = run_attempts(plan, lambda attempt: run_native_attempt(suite, fixtures, output, attempt), output, args.attempts)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
