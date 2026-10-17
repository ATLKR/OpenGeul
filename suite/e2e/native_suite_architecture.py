"""Lazy, native Windows architecture observations for Suite E2E witnesses."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
from pathlib import Path
import struct

NATIVE_MACHINES = {'x64': 0x8664, 'arm64': 0xaa64}
MACHINE_ARCHITECTURES = {value: key for key, value in NATIVE_MACHINES.items()}


def require_architecture(architecture):
    assert isinstance(architecture, str) and architecture in NATIVE_MACHINES, 'Unsupported native Suite architecture'
    return architecture


def _kernel():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], W.HANDLE
    kernel.IsWow64Process2.argtypes = [W.HANDLE, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16)]
    kernel.IsWow64Process2.restype = W.BOOL
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [W.HANDLE], W.BOOL
    return kernel


def observe_native_architecture(process_handle=None):
    kernel = _kernel()
    handle = kernel.GetCurrentProcess() if process_handle is None else process_handle
    process, native = ctypes.c_uint16(), ctypes.c_uint16()
    if not kernel.IsWow64Process2(handle, ctypes.byref(process), ctypes.byref(native)):
        raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'IsWow64Process2 failed')
    return {'processMachine': process.value, 'nativeMachine': native.value,
            'processArchitecture': MACHINE_ARCHITECTURES.get(process.value or native.value),
            'nativeArchitecture': MACHINE_ARCHITECTURES.get(native.value)}


def validate_native_architecture(observed, expected_architecture):
    architecture = require_architecture(expected_architecture)
    assert (isinstance(observed, dict) and type(observed.get('processMachine')) is int
            and observed['processMachine'] == 0 and type(observed.get('nativeMachine')) is int
            and observed['nativeMachine'] == NATIVE_MACHINES[architecture]
            and observed.get('processArchitecture') == architecture
            and observed.get('nativeArchitecture') == architecture), 'Native process/controller and OS architecture differ from Suite inventory'
    return observed


def observe_owned_process(pid, architecture):
    require_architecture(architecture)
    assert type(pid) is int and pid > 0, 'An owned native process ID is required'
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'Cannot inspect owned native process')
    try:
        return validate_native_architecture(observe_native_architecture(handle), architecture)
    finally:
        assert kernel.CloseHandle(handle), 'Owned architecture process handle cleanup failed'


def require_native_pe(path, architecture):
    """Check the emitted observer DLL's native PE identity before loading it."""
    require_architecture(architecture)
    path = Path(path)
    with path.open('rb') as stream:
        dos = stream.read(64)
        assert len(dos) == 64 and dos[:2] == b'MZ', 'Invalid native observer PE image'
        offset = struct.unpack_from('<I', dos, 60)[0]
        assert 64 <= offset <= 1024 * 1024, 'Invalid native observer PE offset'
        stream.seek(offset)
        header = stream.read(24)
        assert len(header) == 24 and header[:4] == b'PE\0\0', 'Invalid native observer PE signature'
        machine, sections, _, _, _, optional_size, characteristics = struct.unpack_from('<HHIIIHH', header, 4)
        optional = stream.read(optional_size)
        assert (machine == NATIVE_MACHINES[architecture] and 1 <= sections <= 96
                and 112 <= optional_size <= 4096 and len(optional) == optional_size
                and struct.unpack_from('<H', optional)[0] == 0x20b
                and characteristics & 0x2000), 'Native observer DLL architecture/header mismatch: ' + architecture
    return path
