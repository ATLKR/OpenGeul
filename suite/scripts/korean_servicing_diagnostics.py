"""Bounded read-only evidence after actual Suite Korean servicing fails.

Read only the system CBS log tail and bounded current-attempt package/error
lines, plus actual OS and servicing-package registry identities. This collector
never repairs Windows, reads user documents or promotes setup to readiness.
"""
from __future__ import annotations

import argparse
from collections import deque
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

MAX_TAIL_BYTES = 1024 * 1024
STAMP = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
RELEVANT = re.compile(r'error|fail|missing|source|package|payload|capability|on.?demand|cbs_e|0x8[0-9a-f]{7}', re.I)


def plain_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('Servicing diagnostics refuse linked paths')
    return path


def read_tail(path, byte_limit=MAX_TAIL_BYTES):
    if type(byte_limit) is not int or not 0 < byte_limit <= MAX_TAIL_BYTES:
        raise ValueError('The CBS tail budget must be between one byte and one MiB')
    path = plain_path(path)
    with path.open('rb') as stream:
        size = os.fstat(stream.fileno()).st_size
        start = max(0, size - byte_limit)
        stream.seek(start)
        payload = stream.read(min(byte_limit, size))
    return {'sourceBytes': size, 'tailStart': start, 'tailBytes': len(payload),
            'truncated': start > 0}, payload


def select_attempt_lines(text, since, through, byte_limit=262144, line_limit=512):
    if (type(byte_limit) is not int or not 0 < byte_limit <= 262144
            or type(line_limit) is not int or not 0 < line_limit <= 512 or since > through):
        raise ValueError('Current-attempt diagnostics require finite ordered bounds')
    selected, used, matches = deque(), 0, 0
    stamp = None
    for line in text.splitlines():
        found = STAMP.match(line)
        if found:
            try: stamp = datetime.strptime(found.group(1), '%Y-%m-%d %H:%M:%S')
            except ValueError: stamp = None
        if stamp is None or not since <= stamp <= through or not RELEVANT.search(line): continue
        encoded = (line + '\n').encode('utf-8')
        matches += 1
        if len(encoded) > byte_limit: continue
        selected.append(encoded)
        used += len(encoded)
        while selected and (used > byte_limit or len(selected) > line_limit):
            used -= len(selected.popleft())
    return {'text': b''.join(selected).decode('utf-8'), 'matchedLines': matches,
            'selectedLines': len(selected), 'selectedBytes': used, 'truncated': matches > len(selected)}


def registry_observation():
    import winreg
    view = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    current = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    observation = {'host': {}, 'servicingPackages': [], 'packageEnumerationTruncated': False}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, current, 0, view) as key:
        for name in ('CurrentBuildNumber', 'UBR', 'DisplayVersion', 'EditionID', 'InstallationType'):
            try:
                value = winreg.QueryValueEx(key, name)[0]
                if isinstance(value, int) or isinstance(value, str) and len(value) <= 128:
                    observation['host'][name] = value
            except FileNotFoundError: pass
    package_root = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\Packages'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, package_root, 0, view) as key:
        count = winreg.QueryInfoKey(key)[0]
        observation['packageRegistryKeyCount'] = count
        observation['packageEnumerationTruncated'] = count > 20000
        for index in range(min(count, 20000)):
            name = winreg.EnumKey(key, index)
            # RollupFix identifies LCUs/checkpoints; also keep the exact SSU
            # identities and Korean package states without an unrelated dump.
            if len(name) > 512 or not re.search(r'Package_for_(?:RollupFix|ServicingStack)|LanguageFeatures-.*(?:ko-kr|Kore)', name, re.I): continue
            if len(observation['servicingPackages']) >= 128:
                observation['packageEnumerationTruncated'] = True
                break
            with winreg.OpenKey(key, name, 0, view) as package:
                try: state = winreg.QueryValueEx(package, 'CurrentState')[0]
                except FileNotFoundError: state = None
                observation['servicingPackages'].append({'name': name, 'currentState': state})
    return observation


def collect(output, since_utc):
    if os.name != 'nt': raise RuntimeError('Actual Windows servicing diagnostics require Windows')
    now = datetime.now(timezone.utc)
    if since_utc.tzinfo is None or not 0 <= (now - since_utc).total_seconds() <= 900:
        raise ValueError('CBS evidence must belong to this bounded current setup attempt')
    output = plain_path(output)
    output.mkdir(parents=True, exist_ok=False)
    record = {'formatVersion': 1, 'sourceCommit': os.environ.get('GITHUB_SHA'),
              'sourceRun': os.environ.get('GITHUB_RUN_ID'), 'job': os.environ.get('GITHUB_JOB'),
              'sinceUtc': since_utc.isoformat(), 'throughUtc': now.isoformat(),
              'suiteOnly': True, 'productInputVerified': False, 'storeQualified': False,
              'sourceQualified': False, 'status': 'partial', 'errors': []}
    try:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetWindowsDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        kernel.GetWindowsDirectoryW.restype = ctypes.c_uint
        windows = ctypes.create_unicode_buffer(32768)
        length = kernel.GetWindowsDirectoryW(windows, len(windows))
        if not 0 < length < len(windows): raise ctypes.WinError(ctypes.get_last_error())
        cbs = Path(windows.value) / 'Logs/CBS/CBS.log'
        metadata, payload = read_tail(cbs)
        (output / 'cbs-tail.log').write_bytes(payload)
        text = payload.decode('utf-8-sig', errors='replace')
        if metadata['truncated'] and '\n' in text: text = text.split('\n', 1)[1]
        selected = select_attempt_lines(text, since_utc.astimezone().replace(tzinfo=None), now.astimezone().replace(tzinfo=None))
        (output / 'cbs-current-attempt.log').write_text(selected.pop('text'), encoding='utf-8')
        record['cbs'] = {**metadata, **selected, 'sourcePath': str(cbs),
                         'timestampInterpretation': 'CBS local wall time converted from actual UTC attempt bounds'}
    except Exception as exc: record['errors'].append('CBS: ' + type(exc).__name__ + ': ' + str(exc))
    try: record.update(registry_observation())
    except Exception as exc: record['errors'].append('registry: ' + type(exc).__name__ + ': ' + str(exc))
    if not record['errors']: record['status'] = 'observed'
    (output / 'diagnostics.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--since-utc', required=True)
    args = parser.parse_args(argv)
    since = datetime.fromisoformat(args.since_utc.replace('Z', '+00:00'))
    print(json.dumps(collect(args.output, since), indent=2), flush=True)
    return 0


if __name__ == '__main__': raise SystemExit(main())
