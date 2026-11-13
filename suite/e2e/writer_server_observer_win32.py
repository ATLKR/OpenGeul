"""Dedicated Writer observer Win64 port; no product launch fallback.

Launch is preparation before the controller's runtime S.  This module never
starts a timeout, reopens a cleanup PID, or treats a kill request as retirement.
Portable syscall seams verify the bindings; Windows/SDK execution is unverified.
"""
import ctypes as C
from dataclasses import dataclass, field
from enum import IntEnum
import ntpath
import subprocess
import sys


WINDOWS_ACTUAL_VERIFIED = False
SDK_COMPILE_VERIFIED = False
H, U32, B, U16 = C.c_void_p, C.c_uint32, C.c_int32, C.c_uint16
SIZE, I64 = C.c_size_t, C.c_int64
PTR_MAX = (1 << (C.sizeof(H) * 8)) - 1
_ENV_KEYS = frozenset(name.casefold() for name in (
    'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'ProgramData',
    'PATH', 'PYTHONHOME', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE', 'PYTHONIOENCODING',
    'UNO_PATH', 'URE_BOOTSTRAP', 'OPENGEUL_WRITER_SERVER_OBSERVER'))


class FailureCode(IntEnum):
    NONE = 0
    UNSUPPORTED_PLATFORM = 1
    INVALID_INPUT = 2
    CONTROLLER_IDENTITY = 3
    CREATE_JOB = 4
    JOB_LIMIT = 5
    INHERITANCE = 6
    STDIO = 7
    ATTRIBUTE_SIZE = 8
    ATTRIBUTE_INITIALIZE = 9
    ATTRIBUTE_JOB = 10
    ATTRIBUTE_HANDLES = 11
    CREATE_PROCESS = 12
    HOST_IDENTITY = 13
    MEMBERSHIP = 14
    HOST_STATE = 15
    RESUME = 16
    LOCAL_RELEASE = 17
    NATIVE_CALL = 18
    CENSUS = 19
    INITIAL_MEMBER = 20
    CLOCK = 21


class NativeCallError(RuntimeError):
    def __init__(self, code, *, retained_handle=None):
        self.code = FailureCode(code)
        self.retained_handle = retained_handle
        super().__init__('writer_observer_native_' + self.code.name.lower())

    def __repr__(self):
        return '<NativeCallError ' + self.code.name + '>'


class FileTime(C.Structure):
    _fields_ = [('low', U32), ('high', U32)]


class SecurityAttributes(C.Structure):
    _fields_ = [('size', U32), ('descriptor', H), ('inherit', B)]


class StartupInfo(C.Structure):
    _fields_ = [('cb', U32), ('reserved', H), ('desktop', H), ('title', H),
                ('x', U32), ('y', U32), ('x_size', U32), ('y_size', U32),
                ('x_chars', U32), ('y_chars', U32), ('fill', U32), ('flags', U32),
                ('show', U16), ('reserved_size', U16), ('reserved_bytes', H),
                ('stdin', H), ('stdout', H), ('stderr', H)]


class StartupInfoEx(C.Structure):
    _fields_ = [('startup', StartupInfo), ('attributes', H)]


class ProcessInfo(C.Structure):
    _fields_ = [('process', H), ('thread', H), ('pid', U32), ('tid', U32)]


class BasicLimits(C.Structure):
    _fields_ = [('process_time', I64), ('job_time', I64), ('flags', U32),
                ('minimum_working_set', SIZE), ('maximum_working_set', SIZE),
                ('active_process_limit', U32), ('affinity', SIZE),
                ('priority', U32), ('scheduling', U32)]


class ExtendedLimits(C.Structure):
    _fields_ = [('basic', BasicLimits), ('io', C.c_uint64 * 6),
                ('process_memory', SIZE), ('job_memory', SIZE),
                ('peak_process_memory', SIZE), ('peak_job_memory', SIZE)]


class JobPidList(C.Structure):
    _fields_ = [('assigned', U32), ('count', U32), ('pids', SIZE * 128)]


@dataclass(repr=False)
class OwnedLaunch:
    """Private mutable resource owner, including failed/uncertain launch state."""
    job: object = None
    host: object = None
    thread: object = None
    identity: object = None
    controller_handle: object = None
    controller_identity: object = None
    nonce: object = None
    creation_job_membership: bool = False
    pre_resume_verified: bool = False
    resumed: bool = False
    uncertain: bool = False
    failed: bool = False
    failure_code: FailureCode = FailureCode.NONE
    attributes_released: bool = True
    stdio_released: bool = True
    local_cleanup_complete: bool = False
    stdio: object = None
    _attribute_address: object = None
    _attribute_initialized: bool = False
    _buffers: list = field(default_factory=list)

    def __repr__(self):
        return '<OwnedLaunch private>'


def _handle(value, code=FailureCode.INVALID_INPUT):
    value = getattr(value, 'value', value)
    if type(value) is not int or not 0 < value < PTR_MAX:
        raise NativeCallError(code)
    return value


def _utf16(text):
    try:
        data = text.encode('utf-16-le') + b'\0\0'
        return (U16 * (len(data) // 2)).from_buffer_copy(data)
    except Exception:
        raise NativeCallError(FailureCode.INVALID_INPUT) from None


def _environment_block(environment):
    # Only the caller's fresh explicit dictionary is accepted, never os.environ.
    if type(environment) is not dict or not environment:
        raise NativeCallError(FailureCode.INVALID_INPUT)
    folded = set()
    for name, value in environment.items():
        if (type(name) is not str or name.casefold() not in _ENV_KEYS
                or name.casefold() in folded or type(value) is not str
                or '\0' in value):
            raise NativeCallError(FailureCode.INVALID_INPUT)
        folded.add(name.casefold())
    return _utf16('\0'.join(name + '=' + environment[name]
                           for name in sorted(environment, key=str.casefold)) + '\0')


class NativeApi:
    """Real typed Win32 boundary. Injected libraries are portable test seams."""
    def __init__(self, *, kernel=None, last_error=None):
        if C.sizeof(H) != 8:
            raise NativeCallError(FailureCode.UNSUPPORTED_PLATFORM)
        if kernel is None:
            if sys.platform != 'win32':
                raise NativeCallError(FailureCode.UNSUPPORTED_PLATFORM)
            kernel = C.WinDLL('kernel32', use_last_error=True)
        self._last_error = last_error or getattr(C, 'get_last_error', lambda: 0)
        definitions = (
            ('_create_job', 'CreateJobObjectW', (H, H), H),
            ('_set_job', 'SetInformationJobObject', (H, C.c_int32, H, U32), B),
            ('_handle_info', 'GetHandleInformation', (H, C.POINTER(U32)), B),
            ('_create_file', 'CreateFileW', (C.POINTER(U16), U32, U32, C.POINTER(SecurityAttributes), U32, U32, H), H),
            ('_initialize', 'InitializeProcThreadAttributeList', (H, U32, U32, C.POINTER(SIZE)), B),
            ('_update', 'UpdateProcThreadAttribute', (H, U32, SIZE, H, SIZE, H, H), B),
            ('_delete', 'DeleteProcThreadAttributeList', (H,), None),
            ('_create', 'CreateProcessW', (C.POINTER(U16), C.POINTER(U16), H, H, B, U32, H, C.POINTER(U16), H, C.POINTER(ProcessInfo)), B),
            ('_resume', 'ResumeThread', (H,), U32),
            ('_pid', 'GetProcessId', (H,), U32),
            ('_times', 'GetProcessTimes', (H, C.POINTER(FileTime), C.POINTER(FileTime), C.POINTER(FileTime), C.POINTER(FileTime)), B),
            ('_wait', 'WaitForSingleObject', (H, U32), U32),
            ('_exit', 'GetExitCodeProcess', (H, C.POINTER(U32)), B),
            ('_member', 'IsProcessInJob', (H, H, C.POINTER(B)), B),
            ('_census', 'QueryInformationJobObject', (H, C.c_int32, H, U32, C.POINTER(U32)), B),
            ('_terminate', 'TerminateJobObject', (H, U32), B),
            ('_close', 'CloseHandle', (H,), B),
            ('_qpc', 'QueryPerformanceCounter', (C.POINTER(I64),), B),
            ('_frequency', 'QueryPerformanceFrequency', (C.POINTER(I64),), B),
            ('_open', 'OpenProcess', (U32, B, U32), H),
            ('_current_process', 'GetCurrentProcess', (), H),
            ('_duplicate', 'DuplicateHandle', (H, H, H, C.POINTER(H), U32, B, U32), B),
        )
        for attribute, name, args, result in definitions:
            function = getattr(kernel, name)
            function.argtypes, function.restype = args, result
            setattr(self, attribute, function)

    def identity(self, handle):
        handle = _handle(handle)
        pid = int(self._pid(handle))
        created, exited, kernel, user = (FileTime() for _ in range(4))
        if not pid or not self._times(handle, C.byref(created), C.byref(exited), C.byref(kernel), C.byref(user)):
            raise NativeCallError(FailureCode.NATIVE_CALL)
        birth = (int(created.high) << 32) | int(created.low)
        if not birth:
            raise NativeCallError(FailureCode.NATIVE_CALL)
        return pid, birth

    def retain_current_controller(self):
        """Retain this process via its current pseudo object, never a PID reopen."""
        duplicate, handle = H(), None
        try:
            current = self._current_process()
            if getattr(current, 'value', current) not in (-1, PTR_MAX):
                raise NativeCallError(FailureCode.CONTROLLER_IDENTITY)
            try:
                made = self._duplicate(current, current, current, C.byref(duplicate),
                                       0x00101000, False, 0)
            finally:
                if duplicate.value and duplicate.value != PTR_MAX:
                    handle = _handle(duplicate.value)
            if not made or handle is None:
                raise NativeCallError(FailureCode.CONTROLLER_IDENTITY)
            identity = self.identity(handle)
            if self.state(handle)[0] != 258:
                raise NativeCallError(FailureCode.CONTROLLER_IDENTITY)
            return handle, identity
        except BaseException:
            retained = None
            if handle:
                try:
                    if not self.close(handle):retained = handle
                except BaseException:retained = handle
            raise NativeCallError(FailureCode.CONTROLLER_IDENTITY, retained_handle=retained) from None

    def state(self, handle):
        handle = _handle(handle)
        waited = int(self._wait(handle, 0))
        code = U32()
        if waited not in (0, 258) or not self._exit(handle, C.byref(code)):
            raise NativeCallError(FailureCode.NATIVE_CALL)
        return waited, int(code.value)

    def member(self, handle, job):
        result = B()
        if not self._member(_handle(handle), _handle(job), C.byref(result)):
            raise NativeCallError(FailureCode.MEMBERSHIP)
        return bool(result.value)

    def census(self, job):
        result, size = JobPidList(), U32()
        if not self._census(_handle(job), 3, C.byref(result), C.sizeof(result), C.byref(size)):
            raise NativeCallError(FailureCode.CENSUS)
        count = int(result.count)
        if (count != result.assigned or count > 128
                or not JobPidList.pids.offset + count * C.sizeof(SIZE) <= size.value <= C.sizeof(result)):
            raise NativeCallError(FailureCode.CENSUS)
        pids = tuple(int(result.pids[i]) for i in range(count))
        if len(set(pids)) != len(pids) or any(not 0 < pid <= 0xFFFFFFFF for pid in pids):
            raise NativeCallError(FailureCode.CENSUS)
        return pids

    def terminate_job(self, job):
        return bool(self._terminate(_handle(job), 1))

    def close(self, handle):
        return bool(self._close(_handle(handle)))

    def qpc_read(self):
        result = I64()
        if not self._qpc(C.byref(result)) or result.value <= 0:
            raise NativeCallError(FailureCode.CLOCK)
        return int(result.value)

    def qpc_frequency(self):
        result = I64()
        if not self._frequency(C.byref(result)) or result.value <= 0:
            raise NativeCallError(FailureCode.CLOCK)
        return int(result.value)

    def open_initial_member(self, pid, job):
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
            raise NativeCallError(FailureCode.INITIAL_MEMBER)
        handle = self._open(0x00101000, False, pid)
        try:
            handle = _handle(handle)
            if not self.member(handle, job):
                raise NativeCallError(FailureCode.INITIAL_MEMBER)
            return handle
        except BaseException:
            retained = None
            if handle:
                try:
                    if not self.close(handle):retained = handle
                except BaseException:retained = handle
            raise NativeCallError(FailureCode.INITIAL_MEMBER, retained_handle=retained) from None

    def _inheritable(self, handle):
        flags = U32()
        if not self._handle_info(_handle(handle), C.byref(flags)):
            raise NativeCallError(FailureCode.INHERITANCE)
        return bool(flags.value & 1)

    def _controller(self, owned):
        if (int(self._pid(self._current_process())) != owned.controller_identity[0]
                or self.identity(owned.controller_handle) != owned.controller_identity
                or self.state(owned.controller_handle)[0] != 258):
            raise NativeCallError(FailureCode.CONTROLLER_IDENTITY)

    def release_launch_local(self, owned):
        """Release independent local setup resources; host/job remain caller-owned."""
        if owned._attribute_initialized:
            try:
                self._delete(owned._attribute_address)
                owned._attribute_initialized = False
                owned.attributes_released = True
                owned._attribute_address = None
                owned._buffers.clear()
            except BaseException:
                owned.attributes_released = False
        else:
            owned.attributes_released = True
            owned._attribute_address = None
            owned._buffers.clear()
        if owned.stdio:
            try:
                if self.close(owned.stdio):
                    owned.stdio = None
                    owned.stdio_released = True
            except BaseException:
                pass
        owned.local_cleanup_complete = owned.attributes_released and owned.stdio_released
        return owned.local_cleanup_complete

    def launch(self, argv, cwd, environment, *, controller_binding):
        owned, phase = OwnedLaunch(), FailureCode.INVALID_INPUT
        try:
            if (type(argv) not in (tuple, list) or not argv or any(type(a) is not str or '\0' in a for a in argv)
                    or not ntpath.isabs(argv[0]) or type(cwd) is not str or not ntpath.isabs(cwd) or '\0' in cwd
                    or type(controller_binding) is not tuple or len(controller_binding) != 3
                    or type(controller_binding[1]) is not tuple or len(controller_binding[1]) != 2
                    or any(type(v) is not int or v <= 0 for v in controller_binding[1])
                    or controller_binding[2] is None):
                raise NativeCallError(FailureCode.INVALID_INPUT)
            owned.controller_handle = _handle(controller_binding[0])
            owned.controller_identity, owned.nonce = controller_binding[1:]
            block = _environment_block(environment)
            application, command, directory = _utf16(argv[0]), _utf16(subprocess.list2cmdline(argv)), _utf16(cwd)
            phase = FailureCode.CONTROLLER_IDENTITY
            self._controller(owned)
            phase = FailureCode.CREATE_JOB
            owned.job = _handle(self._create_job(None, None), phase)
            phase = FailureCode.INHERITANCE
            if self._inheritable(owned.job):raise NativeCallError(phase)
            phase = FailureCode.JOB_LIMIT
            limits = ExtendedLimits();limits.basic.flags = 0x2000
            if not self._set_job(owned.job, 9, C.byref(limits), C.sizeof(limits)):raise NativeCallError(phase)
            phase = FailureCode.STDIO
            security = SecurityAttributes(C.sizeof(SecurityAttributes), None, 1)
            owned.stdio = _handle(self._create_file(_utf16('NUL'), 0xC0000000, 3, C.byref(security), 3, 0x80, None), phase)
            owned.stdio_released = False
            if not self._inheritable(owned.stdio):raise NativeCallError(FailureCode.INHERITANCE)
            phase = FailureCode.ATTRIBUTE_SIZE
            size = SIZE()
            result = self._initialize(None, 2, 0, C.byref(size))
            if result or self._last_error() != 122 or not 0 < size.value <= 1024 * 1024:raise NativeCallError(phase)
            attributes = C.create_string_buffer(size.value)
            owned._attribute_address = C.addressof(attributes)
            job_values, handle_values = (H * 1)(owned.job), (H * 1)(owned.stdio)
            owned._buffers = [attributes, job_values, handle_values]
            phase = FailureCode.ATTRIBUTE_INITIALIZE
            if not self._initialize(owned._attribute_address, 2, 0, C.byref(size)):raise NativeCallError(phase)
            owned._attribute_initialized, owned.attributes_released = True, False
            phase = FailureCode.ATTRIBUTE_JOB
            if not self._update(owned._attribute_address, 0, 0x2000D, C.byref(job_values), C.sizeof(job_values), None, None):raise NativeCallError(phase)
            phase = FailureCode.ATTRIBUTE_HANDLES
            if not self._update(owned._attribute_address, 0, 0x20002, C.byref(handle_values), C.sizeof(handle_values), None, None):raise NativeCallError(phase)
            startup, info = StartupInfoEx(), ProcessInfo()
            startup.startup.cb, startup.startup.flags = C.sizeof(StartupInfoEx), 0x100
            startup.startup.stdin = startup.startup.stdout = startup.startup.stderr = owned.stdio
            startup.attributes = owned._attribute_address
            phase = FailureCode.CREATE_PROCESS
            try:
                made = self._create(application, command, None, None, True, 0x08080404,
                                    block, directory, C.byref(startup), C.byref(info))
            except BaseException:
                owned.host, owned.thread = info.process, info.thread
                owned.uncertain = True
                raise
            owned.host, owned.thread = info.process, info.thread
            if not made:
                owned.uncertain = bool(owned.host or owned.thread)
                raise NativeCallError(phase)
            try:
                _handle(owned.host);_handle(owned.thread)
            except NativeCallError:
                owned.uncertain = True
                raise NativeCallError(phase) from None
            phase = FailureCode.HOST_IDENTITY
            owned.identity = self.identity(owned.host)
            if owned.identity[0] != int(info.pid):raise NativeCallError(phase)
            phase = FailureCode.MEMBERSHIP
            owned.creation_job_membership = self.member(owned.host, owned.job)
            if not owned.creation_job_membership:raise NativeCallError(phase)
            phase = FailureCode.HOST_STATE
            if self.state(owned.host)[0] != 258:raise NativeCallError(phase)
            phase = FailureCode.CONTROLLER_IDENTITY
            self._controller(owned)
            owned.pre_resume_verified = True
            phase = FailureCode.RESUME
            try:count = int(self._resume(owned.thread))
            except BaseException:
                owned.uncertain = True
                raise
            if count != 1:
                owned.uncertain = True
                raise NativeCallError(phase)
            owned.resumed = True
        except BaseException as error:
            owned.failed = True
            owned.failure_code = error.code if isinstance(error, NativeCallError) else phase
        finally:
            if not self.release_launch_local(owned):
                owned.failed = True
                if owned.failure_code == FailureCode.NONE:owned.failure_code = FailureCode.LOCAL_RELEASE
        return owned
