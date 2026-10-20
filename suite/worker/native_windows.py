"""Pointer-width-safe Win32 windows and an owned process Job Object.

The office launcher starts suspended, is assigned to our private job, then resumes.
Its soffice.bin child therefore belongs to the same job. No process-name killing,
user process enumeration, or kill-on-worker-exit policy is used.
"""
import ctypes
from ctypes import wintypes as wt
import os
from pathlib import Path
import subprocess
import time

from session import WorkerError


def canonicalize_temp_environment(inherited, *, resolver=None):
    """Copy child env with canonical TEMP/TMP; never change global Firebird policy."""
    environment = dict(inherited)
    resolve = resolver or (lambda value: str(Path(value).resolve()))
    for name, value in inherited.items():
        if name.upper() in ('TEMP', 'TMP') and value:
            # LO 26.8 preserves 8.3 temp paths in DatabaseAccess=Restrict, while
            # Firebird 3.0.13 expands database paths to long names before checking.
            # Give both libraries the same path without weakening Restrict.
            environment[name] = str(resolve(value))
    return environment


def windows_dll(name):
    if os.name != 'nt':
        raise WorkerError('unsupported_platform', 'Windows에서만 네이티브 Office 편집기를 사용할 수 있습니다.')
    return ctypes.WinDLL(name, use_last_error=True)


def bind(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


class WindowApi:
    def __init__(self):
        user = windows_dll('user32')
        self.is_window = bind(user, 'IsWindow', [wt.HWND], wt.BOOL)
        self.get_parent = bind(user, 'GetParent', [wt.HWND], wt.HWND)

    def validate_parent(self, hwnd):
        if not self.is_window(hwnd):
            raise WorkerError('invalid_window', 'OpenGeul 문서 패널 창을 찾을 수 없습니다.')

    def validate_child(self, child, parent):
        if not self.is_window(child) or self.get_parent(child) != parent:
            raise WorkerError('embedding_failed', 'Office 편집기가 OpenGeul 패널의 자식 창으로 연결되지 않았습니다.')


class StartupInfo(ctypes.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
                ('lpTitle', wt.LPWSTR), ('dwX', wt.DWORD), ('dwY', wt.DWORD),
                ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
                ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD),
                ('dwFlags', wt.DWORD), ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD),
                ('lpReserved2', ctypes.POINTER(wt.BYTE)), ('hStdInput', wt.HANDLE),
                ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE),
                ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


class JobCensusError(RuntimeError):
    def __init__(self, message, *, winerror=None):
        super().__init__(message)
        self.winerror = winerror


class ProcessDiagnosticsApi:
    """Queries only the supplied private job, with read-only process handles."""
    def __init__(self):
        kernel = windows_dll('kernel32')
        self.query_job = bind(kernel, 'QueryInformationJobObject',
            [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)], wt.BOOL)
        self.open_process = bind(kernel, 'OpenProcess', [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE)
        self.is_in_job = bind(kernel, 'IsProcessInJob', [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)], wt.BOOL)
        self.query_image = bind(kernel, 'QueryFullProcessImageNameW',
            [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL)
        self.get_times = bind(kernel, 'GetProcessTimes', [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4, wt.BOOL)
        self.get_exit = bind(kernel, 'GetExitCodeProcess', [wt.HANDLE, ctypes.POINTER(wt.DWORD)], wt.BOOL)
        self.wait_for = bind(kernel, 'WaitForSingleObject', [wt.HANDLE, wt.DWORD], wt.DWORD)
        self.close_handle = bind(kernel, 'CloseHandle', [wt.HANDLE], wt.BOOL)

    def job_pids(self, job, *, record=None, check=None):
        # A partial list is never ownership evidence. Only coherent in-capacity
        # successful reads can be queried again, at most three times. This is a
        # conservative census policy, not an assertion about a past race.
        class Pids(ctypes.Structure):
            # Windows DWORD is explicitly 32 bits, also in portable DLL seams.
            _fields_ = [('assigned', ctypes.c_uint32), ('count', ctypes.c_uint32),
                        ('pids', ctypes.c_size_t * 128)]
        group = dict(schemaVersion=1, kind='private-job-process-census',
            api='QueryInformationJobObject', informationClass=3,
            jobHandleValue=int(job), capacity=128, maxAttempts=3,
            bufferBytes=ctypes.sizeof(Pids), headerBytes=Pids.pids.offset,
            processIdBytes=ctypes.sizeof(ctypes.c_size_t), startedAt=time.monotonic(),
            finishedAt=None, classification='failed', calls=[])
        emitted = False
        try:
            for attempt in range(1, 4):
                if check:check()
                result, used = Pids(), wt.DWORD()
                started = time.monotonic()
                succeeded = bool(self.query_job(job, 3, ctypes.byref(result),
                    ctypes.sizeof(result), ctypes.byref(used)))
                error = int(ctypes.get_last_error())  # Capture before any other native call.
                row = dict(attempt=attempt, startedAt=started, finishedAt=time.monotonic(),
                    result=succeeded, lastError=error, assigned=int(result.assigned),
                    count=int(result.count), returnLength=int(used.value),
                    pids=[int(result.pids[i]) for i in range(min(int(result.count), 128))],
                    classification='api-error')
                group['calls'].append(row)
                if succeeded:
                    if result.count > 128 or result.assigned > 128:
                        row['classification']='capacity-exceeded'
                    elif result.count > result.assigned or not (
                            Pids.pids.offset + result.count * ctypes.sizeof(ctypes.c_size_t)
                            <= used.value <= ctypes.sizeof(result)):
                        row['classification']='invalid-header'
                    else:
                        row['classification']='complete' if result.assigned == result.count else 'incomplete'
                if check:check()
                if not succeeded:
                    # Failure output is retained diagnostically, never trusted,
                    # including ERROR_MORE_DATA (234).
                    raise JobCensusError('Private job census API failed', winerror=error)
                if row['classification'] in ('capacity-exceeded', 'invalid-header'):
                    raise JobCensusError('Private job census '+row['classification'])
                if row['classification']=='complete':
                    group.update(classification='complete', finishedAt=time.monotonic())
                    if record:
                        emitted=True;record(group)
                    return list(row['pids'])
            raise JobCensusError('Private job census remained incomplete after three bounded reads')
        except BaseException as exc:
            group.update(classification='failed', finishedAt=time.monotonic(),
                error=dict(type=type(exc).__name__, message=str(exc), winerror=getattr(exc,'winerror',None)))
            exc.job_census=group
            if record and not emitted:
                try:record(group)
                except BaseException as later:
                    # Preserve the original failure and its current raw calls
                    # even when the bounded history cannot accept another group.
                    group['recordingError']=dict(type=type(later).__name__[:128],message=str(later)[:1024])
            raise

    def open_owned(self, pid, job):
        handle = self.open_process(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        member = wt.BOOL()
        if not self.is_in_job(handle, job, ctypes.byref(member)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close_handle(handle)
            raise error
        if not member.value:
            self.close_handle(handle)
            raise RuntimeError('PID no longer belongs to the private Office job')
        return handle

    def identity(self, handle):
        image, length = ctypes.create_unicode_buffer(32768), wt.DWORD(32768)
        if not self.query_image(handle, 0, image, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        creation, exit_time, kernel, user = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if not self.get_times(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                              ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'image': image.value, 'creationTime': (creation.dwHighDateTime << 32) | creation.dwLowDateTime}

    def state(self, handle):
        waited = self.wait_for(handle, 0)
        if waited not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        code = wt.DWORD()
        if not self.get_exit(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'alive': waited == 258, 'waitResult': int(waited), 'exitCode': int(code.value),
                'exitCodeHex': f'0x{code.value:08x}', 'getExitCodeProcessResult': True}

    def close(self, handle):
        if not self.close_handle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class JobProcessWitnesses:
    """Retain members' identities/exit codes across a load failure and cleanup."""
    def __init__(self, job, api=None):
        self.job, self.api, self.members = job, api or ProcessDiagnosticsApi(), {}
        self.failed_members = {}

    def snapshot(self):
        errors = [row for handle, row in self.failed_members.values()]
        for pid in self.api.job_pids(self.job):
            if pid in self.members or pid in self.failed_members:
                continue
            handle = None
            try:
                handle = self.api.open_owned(pid, self.job)
                identity = dict(self.api.identity(handle), pid=pid)
                self.members[pid] = (handle, identity)
            except Exception as exc:
                row = {'pid': pid, 'error': {'type': type(exc).__name__, 'message': str(exc),
                                           'winerror': getattr(exc, 'winerror', None)}}
                errors.append(row)
                if handle is not None:
                    row['handleValue'] = int(handle)
                    try:
                        self.api.close(handle)
                    except Exception as later:
                        row['handleCloseError'] = {'type': type(later).__name__, 'message': str(later),
                                                   'winerror': getattr(later, 'winerror', None)}
                        self.failed_members[pid] = (handle, row)
        result = []
        for handle, identity in self.members.values():
            try:
                result.append(dict(identity, **self.api.state(handle)))
            except Exception as exc:
                result.append(dict(identity, error={'type': type(exc).__name__, 'message': str(exc),
                                                   'winerror': getattr(exc, 'winerror', None)}))
        return result + errors

    def retained_snapshot(self):
        """Strict shutdown evidence; optional diagnostic errors cannot prove exit."""
        rows = self.snapshot()
        if any(row.get('error') or type(row.get('alive')) is not bool for row in rows):
            raise RuntimeError('Retained private-job member observation failed: ' + repr(rows))
        handles = {pid: int(handle) for pid, (handle, _) in self.members.items()}
        return [dict(row, handleValue=handles[row['pid']]) for row in rows]

    def close(self):
        first = None
        for collection in (self.members, self.failed_members):
            for pid, (handle, identity) in list(collection.items()):
                try:
                    self.api.close(handle)
                    del collection[pid]
                except Exception as exc:
                    if first is None:
                        first = exc
        if first is not None:
            raise first


class OwnedOfficeProcess:
    def __init__(self, argv, cwd):
        env = canonicalize_temp_environment(os.environ)
        kernel = windows_dll('kernel32')
        self.close_handle = bind(kernel, 'CloseHandle', [wt.HANDLE], wt.BOOL)
        self.get_exit = bind(kernel, 'GetExitCodeProcess', [wt.HANDLE, ctypes.POINTER(wt.DWORD)], wt.BOOL)
        self.wait_for = bind(kernel, 'WaitForSingleObject', [wt.HANDLE, wt.DWORD], wt.DWORD)
        self.end_job = bind(kernel, 'TerminateJobObject', [wt.HANDLE, wt.UINT], wt.BOOL)
        create_job = bind(kernel, 'CreateJobObjectW', [ctypes.c_void_p, wt.LPCWSTR], wt.HANDLE)
        assign_job = bind(kernel, 'AssignProcessToJobObject', [wt.HANDLE, wt.HANDLE], wt.BOOL)
        resume = bind(kernel, 'ResumeThread', [wt.HANDLE], wt.DWORD)
        create = bind(kernel, 'CreateProcessW', [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p,
                      ctypes.c_void_p, wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                      ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo)], wt.BOOL)
        kill = bind(kernel, 'TerminateProcess', [wt.HANDLE, wt.UINT], wt.BOOL)
        self.job = create_job(None, None)
        self.handle = None
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        info, startup = ProcessInfo(), StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        # Set a private DLL search path without changing the worker's environment.
        env['PATH'] = str(cwd) + os.pathsep + env.get('PATH', '')
        env_block = ctypes.create_unicode_buffer('\0'.join(k + '=' + v for k, v in sorted(env.items())) + '\0\0')
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        flags = 0x00000004 | 0x00000400 | 0x08000000  # suspended, Unicode env, no console
        if not create(argv[0], command, None, None, False, flags, env_block, str(cwd),
                      ctypes.byref(startup), ctypes.byref(info)):
            self.close_handle(self.job)
            self.job = None
            raise ctypes.WinError(ctypes.get_last_error())
        self.handle, self.pid = info.hProcess, int(info.dwProcessId)
        try:
            if not assign_job(self.job, self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            if resume(info.hThread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            kill(self.handle, 1)
            self.close()
            raise
        finally:
            self.close_handle(info.hThread)

    def poll(self):
        result = wt.DWORD()
        if not self.get_exit(self.handle, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return None if result.value == 259 else result.value

    def open_diagnostic_witnesses(self):
        return JobProcessWitnesses(self.job)

    def wait(self, timeout):
        result = self.wait_for(self.handle, int(timeout * 1000))
        if result == 258:
            raise subprocess.TimeoutExpired('owned Office process', timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def wait_for_job_exit(self, witnesses, timeout, *, clock=None, sleeper=None):
        """One deadline for every retained member and a fresh complete census.

        The caller captures members before requesting shutdown and keeps this
        witness, job and profile if death cannot be proved. This never forces a
        process or treats the launcher's exit alone as Office shutdown.
        """
        if witnesses.job != self.job or not 0 < timeout <= 30:
            raise ValueError('A bounded wait on this original private job is required')
        clock, sleeper = clock or time.monotonic, sleeper or time.sleep
        deadline = clock() + timeout
        while True:
            rows = witnesses.retained_snapshot()
            censuses = []
            pids = witnesses.api.job_pids(self.job, record=censuses.append)
            result = dict(jobEmptyVerified=False, finalMembers=rows, finalJobPids=pids,
                          launcherExitCode=None, launcherWaitResult=None, lastJobCensus=censuses[-1])
            if not pids and all(row['alive'] is False and row.get('waitResult') == 0 for row in rows):
                result['launcherExitCode'] = self.wait(timeout=0)
                result['launcherWaitResult'] = 0
                result['jobEmptyVerified'] = True
                return result
            remaining = deadline - clock()
            if remaining <= 0:
                return result
            for handle, _ in list(witnesses.members.values()):
                remaining = deadline - clock()
                if remaining <= 0:
                    break
                waited = witnesses.api.wait_for(handle, max(1, int(remaining * 1000)))
                if waited not in (0, 258):
                    raise RuntimeError('Retained owned process wait failed')
            # A signaled member may remain briefly in the job census. Bound
            # discovery without a spin loop or a new per-child wait budget.
            remaining = deadline - clock()
            if remaining > 0:
                sleeper(min(.01, remaining))

    def terminate(self):
        if not self.end_job(self.job, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        first = None
        for name in ('handle', 'job'):
            handle = getattr(self, name)
            if handle:
                if self.close_handle(handle):
                    setattr(self, name, None)
                elif first is None:
                    first = ctypes.WinError(ctypes.get_last_error())
        if first is not None:
            raise first
