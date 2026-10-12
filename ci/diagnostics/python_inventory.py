"""Inspect only this interpreter; no install, network, environment or user data."""
import ctypes
import importlib
import json
import os
from pathlib import Path
import platform
import struct
import sys


def pe_machine(path):
    with Path(path).open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('not-pe')
        offset = struct.unpack_from('<I', header, 60)[0]
        if not 64 <= offset <= 1024 * 1024:
            raise ValueError('pe-offset')
        stream.seek(offset)
        signature = stream.read(6)
        if len(signature) != 6 or signature[:4] != b'PE\0\0':
            raise ValueError('pe-header')
        return struct.unpack_from('<H', signature, 4)[0]


def report():
    executable = Path(sys.executable).resolve(strict=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'e2e'))
    from native_architecture import WindowsProbe
    process = WindowsProbe().inspect(os.getpid())
    available = {}
    for name in ('ctypes', 'ssl', 'sqlite3', 'venv', 'xml.etree.ElementTree'):
        try:
            importlib.import_module(name)
            available[name] = True
        except ImportError:
            available[name] = False
    return {
        'version': list(sys.version_info[:3]), 'executable': str(executable),
        'platformMachine': platform.machine(), 'pointerBits': ctypes.sizeof(ctypes.c_void_p) * 8,
        'executablePeMachine': pe_machine(executable),
        'actualProcessMachine': process['processMachine'], 'actualNativeOsMachine': process['nativeMachine'],
        'nativeProcess': process['processMachine'] == 0,
        'stdlibImportsAvailable': available,
        'networkCalls': 0, 'installedPackages': 0, 'compiledProducts': 0,
    }


if __name__ == '__main__':
    print(json.dumps(report(), sort_keys=True, ensure_ascii=False, allow_nan=False))
