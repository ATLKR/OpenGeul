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
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import traceback
from urllib.parse import urlparse
from urllib.request import url2pathname

import windows_smoke as native

CYCLE = (('calc', 'existing'), ('calc', 'new'), ('writer', 'existing'), ('writer', 'new'))
EXTENSIONS = {'calc': 'xlsx', 'writer': 'docx'}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def profile_existence(profile):
    """Probe local path components without following links or network paths."""
    if not profile.is_absolute() or str(profile).startswith(('\\\\', '//')):
        return dict(exists=None, probeSkipped='Nonlocal profile path')
    current = Path(profile.anchor)
    try:
        for part in profile.parts[1:]:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                return dict(exists=None, probeSkipped='Linked profile path component')
        return dict(exists=True)
    except FileNotFoundError:
        return dict(exists=False)
    except OSError as exc:
        return dict(exists=None, probeError=type(exc).__name__ + ': ' + str(exc))


def fixture_snapshot(fixtures):
    """Nonrecursive listing; only generated lock siblings may expose contents."""
    if fixtures.is_symlink() or getattr(fixtures, 'is_junction', lambda: False)() or not fixtures.is_dir():
        raise ValueError('Fixture evidence requires the real generated directory')
    entries = []
    for path in sorted(fixtures.iterdir(), key=lambda item: item.name):
        try:
            info = path.lstat()
            linked = stat.S_ISLNK(info.st_mode) or getattr(path, 'is_junction', lambda: False)()
            entry = dict(name=path.name, bytes=info.st_size, modifiedTimeNs=info.st_mtime_ns,
                         isSymlink=linked, isDirectory=stat.S_ISDIR(info.st_mode))
            lock = path.name.casefold().startswith(('.lock', '.~lock.', '~$'))
            if lock and not linked and stat.S_ISREG(info.st_mode):
                if info.st_size > 8192:
                    entry['lockContentOmitted'] = True
                else:
                    with path.open('rb') as stream:
                        payload = stream.read(8193)
                    if len(payload) > 8192:
                        entry['lockContentOmitted'] = True
                    else:
                        text = payload.decode('utf-8', errors='replace')
                        profiles = []
                        for url in re.findall(r'file://[^,;\s]+', text):
                            parsed = urlparse(url)
                            # Lock metadata is read, never used to load or alter a profile.
                            if parsed.netloc not in ('', 'localhost'): continue
                            profile = Path(url2pathname(parsed.path))
                            profiles.append(dict(url=url, path=str(profile), **profile_existence(profile)))
                        entry.update(lockContent=text, sha256=hashlib.sha256(payload).hexdigest(), profiles=profiles)
            entries.append(entry)
        except OSError as exc:
            entries.append(dict(name=path.name, error=type(exc).__name__ + ': ' + str(exc)))
    return dict(capturedAtUtc=utc_now(), entries=entries)


def capture_fixture_snapshot(record, key, fixtures):
    try:
        record[key] = fixture_snapshot(fixtures)
    except Exception as exc:
        record[key] = dict(error=type(exc).__name__ + ': ' + str(exc), capturedAtUtc=utc_now())


def matching_wer_reports(roots, runtime_image, started, ended):
    """Read small Report.wer metadata only, matched to our image and time range."""
    matched = []
    image = ntpath.normcase(ntpath.normpath(str(runtime_image)))
    for root in roots:
        if root.is_symlink() or getattr(root, 'is_junction', lambda: False)() or not root.is_dir(): continue
        try:
            folders = list(root.iterdir())
        except OSError:
            continue
        for folder in folders:
            report = folder / 'Report.wer'
            try:
                if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)() or not folder.is_dir(): continue
                if report.is_symlink() or not report.is_file(): continue
                info = report.stat()
                if not started <= info.st_mtime <= ended or info.st_size > 1024 * 1024: continue
                raw = report.read_bytes()
                text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='replace')
                fields = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
                if ntpath.normcase(ntpath.normpath(fields.get('AppPath', ''))) != image: continue
                metadata = {key: value for key, value in fields.items() if key in (
                    'EventType', 'ReportIdentifier', 'ReportStatus', 'AppName', 'AppPath') or
                    re.fullmatch(r'Sig\[\d+\]\.(Name|Value)', key)}
                matched.append(dict(reportPath=str(report), modifiedTimeNs=info.st_mtime_ns, metadata=metadata))
            except OSError:
                continue
    return matched


APPLICATION_EVENTS_SCRIPT = r'''param(
    [Parameter(Mandatory=$true)][string]$RuntimeImage,
    [Parameter(Mandatory=$true)][string]$StartedAt,
    [Parameter(Mandatory=$true)][string]$EndedAt,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$start = [DateTimeOffset]::Parse($StartedAt).UtcDateTime
$end = [DateTimeOffset]::Parse($EndedAt).UtcDateTime
$image = [IO.Path]::GetFullPath($RuntimeImage)
$events = @()
$queryErrors = @()
$candidates = @(Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000,1001,1002; StartTime=$start; EndTime=$end} -ErrorAction SilentlyContinue -ErrorVariable queryErrors)
foreach ($event in $candidates) {
    $original = $event.ToXml()
    [xml]$xml = $original
    $owned = $false
    foreach ($data in @($xml.Event.EventData.Data)) {
        if ([string]::Equals([string]$data.InnerText, $image, [StringComparison]::OrdinalIgnoreCase)) { $owned = $true }
    }
    if (-not $owned) { continue }
    $filename = 'application-event-' + [string]$event.RecordId + '.xml'
    [IO.File]::WriteAllText((Join-Path $OutputDirectory $filename), $original, [Text.UTF8Encoding]::new($false))
    $events += @{eventId=$event.Id; recordId=$event.RecordId; provider=$event.ProviderName; timeCreatedUtc=$event.TimeCreated.ToUniversalTime().ToString('o'); xmlFile=$filename}
}
$errors = @($queryErrors | Where-Object { $_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*' } | ForEach-Object { $_.ToString() })
@{runtimeImage=$image; startedAtUtc=$start.ToString('o'); endedAtUtc=$end.ToString('o'); events=$events; errors=$errors} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'application-events.json') -Encoding UTF8
'''


def collect_crash_diagnostics(suite, output, started_at, ended_at):
    """Best-effort evidence never changes or hides the native attempt outcome."""
    target = output / 'crash-diagnostics'
    runtime_image = suite / 'Office' / 'program' / 'soffice.bin'
    result = dict(runtimeImage=str(runtime_image), startedAtUtc=started_at, endedAtUtc=ended_at)
    script = target / 'collect-application-events.ps1'
    try:
        target.mkdir(exist_ok=False)
        script.write_text(APPLICATION_EVENTS_SCRIPT, encoding='utf-8-sig')
    except Exception as exc:
        result['collectorSetupError'] = type(exc).__name__ + ': ' + str(exc)
        return result
    try:
        with (target / 'collector-stdout.log').open('xb') as stdout, (target / 'collector-stderr.log').open('xb') as stderr:
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(script), '-RuntimeImage', str(runtime_image), '-StartedAt', started_at,
                '-EndedAt', ended_at, '-OutputDirectory', str(target)], cwd=suite, shell=False,
                stdout=stdout, stderr=stderr, timeout=45, check=False)
        result['eventCollectorExitCode'] = process.returncode
        events = json.loads((target / 'application-events.json').read_text(encoding='utf-8-sig'))
        result.update(applicationEvents=events, applicationEventsFile='crash-diagnostics/application-events.json')
    except Exception as exc:
        result['eventCollectorError'] = type(exc).__name__ + ': ' + str(exc)
    try:
        roots = [Path(base) / 'Microsoft' / 'Windows' / 'WER' / name
                 for base in (os.environ.get('ProgramData'), os.environ.get('LOCALAPPDATA')) if base
                 for name in ('ReportArchive', 'ReportQueue')]
        reports = matching_wer_reports(roots, runtime_image,
            datetime.fromisoformat(started_at).timestamp(), datetime.fromisoformat(ended_at).timestamp())
        (target / 'wer-metadata.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        result.update(werMetadataFile='crash-diagnostics/wer-metadata.json', matchedWerReportCount=len(reports))
    except Exception as exc:
        result['werCollectorError'] = type(exc).__name__ + ': ' + str(exc)
    return result


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
    record['startedAtUtc'] = utc_now()
    capture_fixture_snapshot(record, 'fixtureDirectoryBeforeLaunch', fixtures)
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
        assert not api.windows(office_pid), 'Office created an unowned visible top-level window'
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
        capture_fixture_snapshot(record, 'fixtureDirectoryAtFailure', fixtures)
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
        capture_fixture_snapshot(record, 'fixtureDirectoryAfterCleanup', fixtures)
        record['endedAtUtc'] = utc_now()
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
    started_at = utc_now()
    initial_snapshot = {}
    capture_fixture_snapshot(initial_snapshot, 'initialFixtureDirectory', fixtures)
    plan = build_plan(args.attempts)
    report = run_attempts(plan, lambda attempt: run_native_attempt(suite, fixtures, output, attempt), output, args.attempts)
    ended_at = utc_now()
    report.update(startedAtUtc=started_at, endedAtUtc=ended_at, **initial_snapshot,
                  diagnostics=collect_crash_diagnostics(suite, output, started_at, ended_at))
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
