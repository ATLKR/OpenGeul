"""Pointer-width-safe Win32 windows and an owned process Job Object.

The office launcher starts suspended, is assigned to our private job, then resumes.
Its soffice.bin child therefore belongs to the same job. No process-name killing,
user process enumeration, or kill-on-worker-exit policy is used.
"""
import ctypes
from ctypes import wintypes as wt
import os
import subprocess

from session import WorkerError


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


class OwnedOfficeProcess:
    def __init__(self, argv, cwd):
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
        env = dict(os.environ)
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

    def wait(self, timeout):
        result = self.wait_for(self.handle, int(timeout * 1000))
        if result == 258:
            raise subprocess.TimeoutExpired('owned Office process', timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if not self.end_job(self.job, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        for handle in (self.handle, self.job):
            if handle:
                self.close_handle(handle)
        self.handle = self.job = None
