"""고정 SDK 원본만 읽는다. WACK/SDK assembly 실행과 외부 요청은 하지 않는다."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import threading
import time

SDK_ROOT = Path(r'C:\Program Files (x86)\Windows Kits\10\App Certification Kit')
FILE_LIMIT = 16 * 1024 * 1024
READ_LIMIT = 128 * 1024 * 1024
COPY_LIMIT = 16 * 1024 * 1024
SECONDS_LIMIT = 90
JSON_LIMIT = 2 * 1024 * 1024
TERMS = ('BlockedExecutables', 'BlockedExecutable', 'Blocked executables', 'LaunchProcess',
         'Launch Process', 'CreateProcessW', 'CreateProcessA', 'ShellExecuteExW',
         'CreateProcessAsUserW', 'PowerShell', 'cmd.exe', 'BlackList', 'Blacklist', 'Windows10S')
ORIGINALS = frozenset(('microsoft.windows.softwarelogo.tests.dll', 'microsoft.windows.softwarelogo.shared.dll',
    'microsoft.windows.softwarelogo.metadatavalidation.tests.dll', 'microsoft.windows.softwarelogo.testbase.dll',
    'microsoft.windows.softwarelogo.tasks.dll', 'microsoft.windows.softwarelogo.executiondriver.dll',
    'corelibrary.dll', 'binaryinfo.dll', 'configuration.xml', 'reportlocalizationstrings.xml'))
EXPECTED_ENV = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Windows',
    'GITHUB_REPOSITORY': 'ATLKR/OpenGeul', 'GITHUB_ACTOR': 'ATLKR', 'GITHUB_TRIGGERING_ACTOR': 'ATLKR',
    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
    'GITHUB_REF': 'refs/heads/diagnostic/wack-sdk-inspect-113',
    'GITHUB_WORKFLOW_REF': 'ATLKR/OpenGeul/.github/workflows/store-package.yml@refs/heads/diagnostic/wack-sdk-inspect-113'}
TOOL_ROOT = Path(r'C:\Program Files (x86)\Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools')
TOOL_CANDIDATES = (TOOL_ROOT / 'x64/ildasm.exe', TOOL_ROOT / 'ildasm.exe',
    Path(r'C:\Program Files (x86)\Microsoft SDKs\Windows\v10.0A\bin\NETFX4.8Tools\x64\ildasm.exe'))


def require(condition):
    if not condition:
        raise ValueError('SDK inspection guard rejected')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def context(env, event):
    require(all(env.get(k) == v for k, v in EXPECTED_ENV.items()))
    require(bool(re.fullmatch('[1-9][0-9]*', env.get('GITHUB_RUN_ID', ''))))
    require(isinstance(event, dict) and event.get('repository', {}).get('full_name') == 'ATLKR/OpenGeul')
    require(event['repository'].get('private') is False)
    inputs = event.get('inputs')
    require(inputs is None or type(inputs) is dict and inputs == {})
    require(not env.get('GH_TOKEN') and not env.get('GITHUB_TOKEN'))


def deadline_check(clock, deadline):
    require(clock() <= deadline)


def regular(path, root):
    require(path.is_relative_to(root))
    cursor = path
    while True:
        info = cursor.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400)
        if cursor == root:
            break
        cursor = cursor.parent
    return path.lstat()


def read_file(path, root, clock, deadline):
    deadline_check(clock, deadline)
    before = regular(path, root)
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= FILE_LIMIT)
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        require((opened.st_dev, opened.st_ino, opened.st_size) == (before.st_dev, before.st_ino, before.st_size))
        raw = stream.read(FILE_LIMIT + 1)
        after = os.fstat(stream.fileno())
    require(len(raw) == before.st_size and (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns))
    deadline_check(clock, deadline)
    return raw


def pe_headers(raw):
    result = {'pe': False, 'managedClrHeaderPresent': False}
    if len(raw) < 64 or raw[:2] != b'MZ':
        return result
    offset = struct.unpack_from('<I', raw, 60)[0]
    if offset + 24 > len(raw) or raw[offset:offset + 4] != b'PE\0\0':
        return result
    machine, _, _, _, _, optional_size, _ = struct.unpack_from('<HHIIIHH', raw, offset + 4)
    optional = offset + 24
    if optional_size < 2 or optional + optional_size > len(raw):
        return result
    magic = struct.unpack_from('<H', raw, optional)[0]
    directory = {0x10b: (92, 96), 0x20b: (108, 112)}.get(magic)
    result.update(pe=True, machine=hex(machine), optionalMagic=hex(magic))
    if directory and optional_size >= directory[1] + 15 * 8:
        count = struct.unpack_from('<I', raw, optional + directory[0])[0]
        if count >= 15:
            rva, size = struct.unpack_from('<II', raw, optional + directory[1] + 14 * 8)
            result.update(managedClrHeaderPresent=bool(rva and size), clrHeaderRva=rva, clrHeaderSize=size)
    return result


def hits(raw):
    rows = []
    for term in TERMS:
        for encoding in ('ascii', 'utf-16le'):
            needle, start, offsets = term.encode(encoding), 0, []
            while len(offsets) < 8:
                offset = raw.find(needle, start)
                if offset < 0:
                    break
                offsets.append(offset)
                start = offset + 1
            if offsets:
                rows.append({'term': term, 'encoding': encoding, 'offsetBytes': offsets,
                             'truncated': raw.find(needle, start) >= 0})
    return rows


def sdk_version(path):
    # 표준 Win32 version-resource 조회이며 SDK executable을 로드하거나 시작하지 않는다.
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32))
    api.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
    api.GetFileVersionInfoW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
    api.VerQueryValueW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32))
    size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(ctypes.c_uint32()))
    require(0 < size <= 1024 * 1024)
    data = ctypes.create_string_buffer(size)
    require(api.GetFileVersionInfoW(str(path), 0, size, data))
    pointer, length = ctypes.c_void_p(), ctypes.c_uint32()
    require(api.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)) and length.value >= 52)
    fixed = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
    require(fixed[0] == 0xFEEF04BD)
    return '.'.join(map(str, (fixed[2] >> 16, fixed[2] & 65535, fixed[3] >> 16, fixed[3] & 65535)))


def collect(root, output, clock=time.monotonic):
    deadline = clock() + SECONDS_LIMIT
    require(root.is_absolute() and root.is_dir() and not output.exists())
    require(not output.resolve().is_relative_to(root.resolve()))
    require(stat.S_ISDIR(regular(root, root).st_mode))
    rows, files, pending, entries, read_total = [], [], [root], 0, 0
    while pending:
        deadline_check(clock, deadline)
        directory = pending.pop()
        require(stat.S_ISDIR(regular(directory, root).st_mode))
        with os.scandir(directory) as listing:
            for entry in listing:
                entries += 1
                require(entries <= 4096)
                info = regular(Path(entry.path), root)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                else:
                    require(stat.S_ISREG(info.st_mode) and len(files) < 1024)
                    files.append(Path(entry.path))
    copied, copy_total = {}, 0
    for path in sorted(files):
        require(read_total + path.stat().st_size <= READ_LIMIT)
        raw = read_file(path, root, clock, deadline)
        read_total += len(raw)
        relative = path.relative_to(root).as_posix()
        rows.append({'path': relative, 'size': len(raw), 'sha256': sha(raw), 'peHeaders': pe_headers(raw), 'hits': hits(raw)})
        if relative.lower() in ORIGINALS:
            copy_total += len(raw)
            require(copy_total <= COPY_LIMIT)
            copied[relative] = raw
    result = {'scope': '고정 App Certification Kit SDK의 읽기 전용 원본/PE/CLR/문자열 증거',
        'sdkCodeExecuted': False, 'wackExecuted': False, 'sourceQualificationAsserted': False,
        'sdkVersion': sdk_version(root / 'appcert.exe') if os.name == 'nt' and (root / 'appcert.exe').exists() else None,
        'files': rows, 'fileCount': len(rows), 'readBytes': read_total, 'copiedOriginals': sorted(copied),
        'copiedBytes': copy_total, 'missingFixedOriginals': sorted(ORIGINALS - {n.lower() for n in copied}),
        'limits': {'seconds': SECONDS_LIMIT, 'perFileBytes': FILE_LIMIT, 'readBytes': READ_LIMIT, 'copiedBytes': COPY_LIMIT}}
    encoded = json.dumps(result, ensure_ascii=False, indent=2).encode() + b'\n'
    require(len(encoded) <= JSON_LIMIT)
    deadline_check(clock, deadline)
    output.mkdir()
    (output / 'originals').mkdir()
    for name, raw in copied.items():
        deadline_check(clock, deadline)
        (output / 'originals' / name).write_bytes(raw)
    (output / 'inventory.json').write_bytes(encoded)
    return result


def capture(command, seconds=30, cap=8 * 1024 * 1024):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    kept, counts, overflow = [bytearray(), bytearray()], [0, 0], threading.Event()
    def reader(stream, index, limit):
        with stream:
            while chunk := stream.read(65536):
                counts[index] += len(chunk)
                remaining = limit - len(kept[index])
                kept[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
    threads = [threading.Thread(target=reader, args=(stream, index, limit), daemon=True)
        for index, (stream, limit) in enumerate(((process.stdout, cap), (process.stderr, 1024 * 1024)))]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + seconds
    try:
        while process.poll() is None:
            if overflow.is_set() or time.monotonic() > deadline:
                process.kill()
                raise ValueError('bounded passive capture rejected')
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
    require(process.returncode == 0 and not overflow.is_set() and not any(thread.is_alive() for thread in threads))
    return bytes(kept[0]), {'exitCode': process.returncode, 'stdoutBytes': counts[0], 'stdoutSha256': sha(kept[0]),
        'stderrBytes': counts[1], 'stderrSha256': sha(kept[1]), 'secondsLimit': seconds, 'stdoutBytesLimit': cap}


def passive_il(root, output):
    selected = next((path for path in TOOL_CANDIDATES if path.is_file()), None)
    require(selected is not None)
    for ancestor in (selected, *selected.parents):
        info = ancestor.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400)
    tool_raw = read_file(selected, selected.parent, time.monotonic, time.monotonic() + 5)
    carrier = next(path for path in root.iterdir() if path.name.lower() == 'microsoft.windows.softwarelogo.tests.dll')
    carrier_raw = read_file(carrier, root, time.monotonic, time.monotonic() + 5)
    require(pe_headers(carrier_raw)['managedClrHeaderPresent'])
    arguments = ['/text', '/nobar', '/utf8', '/tokens', '/raweh']
    stdout, detail = capture([str(selected), *arguments, str(carrier)])
    (output / 'tests.full.il').write_bytes(stdout)
    result = {'scope': '설치된 ildasm으로 SDK assembly의 전체 IL/metadata만 읽음; assembly 실행 없음',
        'tool': {'fixedCandidateIndex': TOOL_CANDIDATES.index(selected), 'name': selected.name, 'size': len(tool_raw), 'sha256': sha(tool_raw)},
        'carrier': {'name': carrier.name, 'size': len(carrier_raw), 'sha256': sha(carrier_raw)},
        'arguments': arguments, 'capture': detail, 'complete': True}
    (output / 'passive-il.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


def failure(error):
    name = type(error).__name__
    return {'status': 'failed', 'exceptionType': name if name in ('ValueError', 'OSError', 'PermissionError', 'FileNotFoundError') else 'Exception',
        'sdkCodeExecuted': False, 'wackExecuted': False, 'sourceQualificationAsserted': False}


def main():
    try:
        require(sys.argv[1:] == [] and os.name == 'nt')
        event_path = Path(os.environ['GITHUB_EVENT_PATH'])
        require(event_path.stat().st_size <= JSON_LIMIT)
        context(os.environ, json.loads(event_path.read_bytes()))
        for ancestor in (SDK_ROOT, *SDK_ROOT.parents):
            info = ancestor.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400)
        result = collect(SDK_ROOT, Path('wack-sdk-inspect'))
        require(result['sdkVersion'] == '10.0.26100.8249' and not result['missingFixedOriginals'])
        passive_il(SDK_ROOT, Path('wack-sdk-inspect'))
        print(json.dumps({'status': 'success', 'sdkVersion': result['sdkVersion'], 'files': result['fileCount'], 'copiedBytes': result['copiedBytes']}))
        return 0
    except Exception as error:
        safe = failure(error)
        Path('wack-sdk-inspect-failure.json').write_text(json.dumps(safe) + '\n')
        print(json.dumps(safe), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
