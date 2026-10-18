"""Record helper resolution inside Meson's activated VS environment."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys


def identity(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    if len(raw) < 64 or raw[:2] != b'MZ':
        raise ValueError('Reached helper is not PE')
    pe = struct.unpack_from('<I', raw, 60)[0]
    if pe < 64 or pe + 26 > len(raw) or raw[pe:pe+4] != b'PE\0\0':
        raise ValueError('Reached helper has invalid PE headers')
    return {'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'machine': struct.unpack_from('<H', raw, pe + 4)[0], 'role': 'build helper, not product payload'}


if __name__ == '__main__':
    tools = {}
    for name in ('cl.exe', 'link.exe', 'lib.exe', 'ninja.exe'):
        found = shutil.which(name)
        if not found:
            raise ValueError('Meson VS environment did not resolve ' + name)
        tools[name] = identity(found)
    with Path(sys.argv[1]).open('x', encoding='utf-8') as stream:
        json.dump({'scope': 'Meson activated-environment helper resolution', 'python': sys.executable,
                   'tools': tools, 'PATH': os.environ.get('PATH')}, stream, indent=2)
        stream.write('\n')
