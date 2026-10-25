"""Prepare one native ASCII observer before any editor phase starts.

Discovery and compilation share a 30 second deadline. Each process starts
suspended in its own private Job; root exit alone never proves natural closure.
This module does not launch Office or grant an input deadline.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time

import native_suite_architecture as native_arch

SOURCES = ('ascii_message_observer.cpp', 'ascii_message_protocol.h', 'bounded_stack_windows.h', 'bounded_plugin_origin_windows.h')
SOURCE_ROOT = Path(__file__).resolve().parent
LIMIT, CLEANUP_RESERVE, QUERY_CAP = 30., 3., 4096


def _pin(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)()
    raw = path.read_bytes()
    assert len(raw) <= 8 * 1024 * 1024, 'Observer preparation file exceeds its bound'
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def _absolute(path):
    path = Path(path)
    assert path.is_absolute(), 'Absolute preparation path required'
    for part in (path, *path.parents):
        assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked preparation path'
    return path


def _quoted(path):
    value = str(_absolute(path))
    assert not any(c in value for c in '\r\n"%!&|<>^'), 'Unsupported command-script path'
    return '"' + value + '"'


class _Budget:
    def __init__(self):
        self.started = self.last = time.monotonic()
        assert type(self.started) in (int, float) and math.isfinite(self.started)
        self.deadline = self.started + LIMIT
        self.work_deadline = self.deadline - CLEANUP_RESERVE

    def now(self, *, cleanup=False):
        now = time.monotonic()
        assert type(now) in (int, float) and math.isfinite(now) and now >= self.last, 'Preparation clock changed'
        self.last = now
        assert now < (self.deadline if cleanup else self.work_deadline), 'Observer preparation deadline expired'
        return now


class _Runtime:
    def __init__(self):
        # Worker module imports remain lazy: portable discovery never loads Win32.
        worker = str(SOURCE_ROOT.parent / 'worker')
        sys.path.insert(0, worker)
        try:
            import native_windows
        finally:
            sys.path.remove(worker)
        self.native = native_windows
        self.diagnostics = native_windows.ProcessDiagnosticsApi()

    def start(self, argv, folder):
        return self.native.OwnedOfficeProcess(argv, folder)

    def identity(self, process):
        return dict(self.diagnostics.identity(process.handle), pid=process.pid,
                    processHandle=int(process.handle), jobHandle=int(process.job))

    def root(self, process):
        waited = int(process.wait_for(process.handle, 0))
        assert waited in (0, 258), 'Compiler root wait failed'
        return dict(waitResult=waited, exitCode=process.poll() if waited == 0 else None)

    def census(self, process):
        class Accounting(C.Structure):
            _fields_ = [(name, C.c_int64) for name in ('user', 'kernel', 'periodUser', 'periodKernel')]
            _fields_ += [(name, C.c_uint32) for name in ('pageFaults', 'total', 'active', 'terminated')]
        assert C.sizeof(Accounting) == 48
        result, length = Accounting(), C.c_uint32()
        succeeded = bool(self.diagnostics.query_job(process.job, 1, C.byref(result), 48, C.byref(length)))
        error = C.get_last_error()
        return dict(querySucceeded=succeeded, lastError=error, returnLength=length.value,
                    activeProcesses=result.active, totalProcesses=result.total,
                    terminatedProcesses=result.terminated, rawHex=bytes(result).hex())


def _remaining_member_diagnostic(runtime, process, budget, stage, sample):
    """One optional, read-only census under the original work deadline.

    A newly opened HANDLE is only a witness to these later samples. Neither
    the PID census nor matching membership checks is an atomic historical
    identity/exit proof. No diagnostic result qualifies natural Job closure.
    """
    diagnostic = dict(triggerSample=sample, workDeadline=budget.work_deadline,
                      identityCap=8, members=[], identityEnumerationComplete=False,
                      naturalExitProved=False)
    stage['remainingMemberDiagnostic'] = diagnostic  # Mark once, including failure.
    try:
        budget.now()
        api = runtime.diagnostics
        def record(group):
            diagnostic['census'] = group
        pids = api.job_pids(process.job, record=record, check=budget.now)
        budget.now()
        census = diagnostic['census']
        assert census['classification'] == 'complete', 'Diagnostic Job census is incomplete'
        assert (type(pids) is list and len(pids) <= 128 and len(set(pids)) == len(pids)
                and all(type(pid) is int and 0 < pid <= 0xffffffff for pid in pids)
                and census['calls'][-1]['pids'] == pids), 'Invalid diagnostic Job PID list'
        if len(pids) > diagnostic['identityCap']:
            diagnostic['identityOmission'] = 'Complete census exceeds identity cap 8; no member HANDLEs opened'
            return
        for pid in pids:
            budget.now()
            row = dict(pid=pid, calls=[], identityScope='newly-retained-diagnostic-samples-only',
                       classification='racy-or-unavailable', handleClosed=False)
            diagnostic['members'].append(row)
            handle = None
            try:
                def call(name, function, *args):
                    event = dict(api=name, startedAt=budget.now())
                    row['calls'].append(event)
                    result = function(*args)
                    event.update(result=int(result), lastError=getattr(C, 'get_last_error', lambda: None)(),
                                 finishedAt=time.monotonic())
                    budget.now()
                    return result

                # Register ownership immediately on return, BEFORE any clock
                # check; even expiry during OpenProcess must close this HANDLE.
                opened = dict(api='OpenProcess', startedAt=budget.now())
                row['calls'].append(opened)
                handle = api.open_process(0x00101000, False, pid)
                error = getattr(C, 'get_last_error', lambda: None)()
                row['handleValue'] = int(handle or 0)
                opened.update(result=row['handleValue'], lastError=error, finishedAt=time.monotonic())
                budget.now()
                assert handle, 'Diagnostic OpenProcess failed'

                def membership(name):
                    member = W.BOOL()
                    succeeded = bool(call('IsProcessInJob', api.is_in_job, handle, process.job, C.byref(member)))
                    row[name] = dict(apiSucceeded=succeeded, inOwnedJob=bool(member.value))
                    assert succeeded and member.value, 'Diagnostic member left the retained private Job'
                membership('membershipBefore')
                image, length = C.create_unicode_buffer(1024), W.DWORD(1024)
                assert call('QueryFullProcessImageNameW', api.query_image, handle, 0, image, C.byref(length)), 'Diagnostic image query failed'
                assert 0 < length.value < 1024, 'Diagnostic image exceeds its bound'
                row['image'] = image.value
                creation, exited, kernel, user = W.FILETIME(), W.FILETIME(), W.FILETIME(), W.FILETIME()
                assert call('GetProcessTimes', api.get_times, handle, C.byref(creation), C.byref(exited),
                            C.byref(kernel), C.byref(user)), 'Diagnostic process-time query failed'
                row['creationTime'] = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                assert row['creationTime'] > 0, 'Diagnostic process creation time is unavailable'
                waited = int(call('WaitForSingleObject', api.wait_for, handle, 0))
                assert waited in (0, 258), 'Diagnostic member wait failed'
                code = W.DWORD()
                assert call('GetExitCodeProcess', api.get_exit, handle, C.byref(code)), 'Diagnostic exit query failed'
                row['state'] = dict(waitResult=waited, exitCode=int(code.value))
                membership('membershipAfter')
                row['classification'] = 'consistent-at-separate-diagnostic-samples'
            except BaseException as exc:
                row['error'] = dict(type=type(exc).__name__[:128], message=str(exc)[:512])
            finally:
                if handle:
                    # Mandatory release is not an optional new observation and
                    # still runs when the original work deadline has expired.
                    try:
                        row['handleClosed'] = bool(api.close_handle(handle))
                        assert row['handleClosed'], 'Diagnostic CloseHandle failed'
                    except BaseException as exc:
                        row['closeError'] = dict(type=type(exc).__name__[:128], message=str(exc)[:512])
            budget.now()
        diagnostic['identityEnumerationComplete'] = all(
            row['classification'] == 'consistent-at-separate-diagnostic-samples' and row['handleClosed']
            for row in diagnostic['members'])
    except BaseException as exc:
        diagnostic['error'] = dict(type=type(exc).__name__[:128], message=str(exc)[:512])


def _run_stage(runtime, folder, stage, script, budget, receipt, arguments):
    assert script.parent == folder and script.name in ('discover.cmd', 'compile.cmd')
    for value in arguments:
        _quoted(value)  # Reject command expansion/metacharacters before wide argv.
    # An ASCII script basename avoids cmd's special first-quoted-command rules.
    # Unicode paths arrive through CreateProcessW argv, never OEM-decoded script
    # text. CREATE_NO_WINDOW needs no console or codepage change.
    command = [os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe'), '/d', '/c', script.name,
               *map(str, arguments)]
    row = dict(stage=stage, command=command, startedAt=budget.now(), samples=[],
               queryCount=0, droppedSamples=0, natural=False, cleanupErrors=[])
    receipt['stages'].append(row)
    process, primary = None, None
    try:
        process = runtime.start(command, folder)
        row['identity'] = runtime.identity(process)
        budget.now()
        while True:
            budget.now()
            assert row['queryCount'] < QUERY_CAP, 'Compiler Job query cap exceeded'
            root = runtime.root(process)
            sample = dict(runtime.census(process), root=root, observedAt=time.monotonic())
            row['queryCount'] += 1
            row['samples'].append(sample)
            if len(row['samples']) > 64:
                del row['samples'][16]
                row['droppedSamples'] += 1
            budget.now()
            assert (sample['querySucceeded'] is True and type(sample['returnLength']) is int
                    and sample['returnLength'] == 48), 'Compiler Job accounting failed'
            assert all(type(sample[key]) is int and 0 <= sample[key] <= 0xffffffff
                       for key in ('activeProcesses', 'totalProcesses', 'terminatedProcesses'))
            assert sample['activeProcesses'] <= sample['totalProcesses'], 'Invalid compiler Job accounting'
            if root['waitResult'] == 0:
                assert type(root['exitCode']) is int and root['exitCode'] == 0, 'Native observer compiler stage failed'
                if sample['activeProcesses'] == 0:
                    row.update(natural=True, finishedAt=budget.now())
                    break
                if 'remainingMemberDiagnostic' not in row:
                    _remaining_member_diagnostic(runtime, process, budget, row, sample)
            remaining = budget.work_deadline - budget.now()
            time.sleep(min(.025, remaining))
    except BaseException as exc:
        primary = exc
        row['error'] = dict(type=type(exc).__name__, message=str(exc)[:1024])
        if process is not None:
            row['forcedOwnedJobCleanup'] = True
            try:
                process.terminate()
                for _ in range(128):
                    budget.now(cleanup=True)
                    sample = dict(runtime.census(process), root=runtime.root(process), observedAt=budget.now(cleanup=True))
                    row['cleanupLastSample'] = sample
                    if (sample['querySucceeded'] is True and sample['returnLength'] == 48
                            and sample['activeProcesses'] == 0 and sample['root']['waitResult'] == 0):
                        break
                    time.sleep(min(.01, budget.deadline - budget.now(cleanup=True)))
                else:
                    raise AssertionError('Owned compiler Job cleanup query cap exceeded')
            except BaseException as later:
                row['cleanupErrors'].append(dict(type=type(later).__name__, message=str(later)[:1024]))
        raise
    finally:
        if process is not None:
            try:
                process.close()
                assert process.handle is None and process.job is None, 'Compiler HANDLE close remained incomplete'
                row['handlesClosed'] = True
            except BaseException as later:
                row['handlesClosed'] = False
                row['cleanupErrors'].append(dict(type=type(later).__name__, message=str(later)[:1024]))
                if primary is None:
                    raise


def _write_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()
    assert len(raw) <= 1024 * 1024, 'Observer preparation receipt exceeds bound'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_observer(output_folder, *, architecture, compiler_mode='clang-lld', budget=None):
    budget = _Budget() if budget is None else budget
    assert budget.deadline == budget.started + LIMIT and budget.work_deadline == budget.deadline - CLEANUP_RESERVE, 'Original preparation budget required'
    budget.now()
    architecture = native_arch.require_architecture(architecture)
    assert compiler_mode in ('msvc', 'clang-lld'), 'Unknown observer compiler mode'
    folder = _absolute(output_folder)
    folder.mkdir(parents=True, exist_ok=False)
    receipt = dict(schemaVersion=1, kind='ascii-message-observer-preparation', architecture=architecture,
                   startedAt=budget.started, deadline=budget.deadline, workDeadline=budget.work_deadline,
                   stages=[], success=False, sourcePins={})
    receipt_path = folder / 'preparation.json'
    try:
        budget.now()
        receipt['nativeArchitecture'] = native_arch.validate_native_architecture(
            native_arch.observe_native_architecture(), architecture)
        runtime = _Runtime()
        for name in SOURCES:
            original = _absolute(SOURCE_ROOT / name)
            receipt['sourcePins'][name] = _pin(original)
            (folder / name).write_bytes(original.read_bytes())
            assert _pin(folder / name) == receipt['sourcePins'][name], 'Observer source copy changed'
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        assert vswhere.is_file(), 'Microsoft C++ tools discovery is unavailable'
        component = ('Microsoft.VisualStudio.Component.VC.Tools.ARM64' if architecture == 'arm64'
                     else 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64')
        discovery = folder / 'discover.cmd'
        discovery.write_text('@echo off\n"%~1" -utf8 -latest -products * -requires ' + component
            + ' -property installationPath >"%~2" 2>"%~3"\nexit /b %errorlevel%\n', encoding='ascii')
        _run_stage(runtime, folder, 'discovery', discovery, budget, receipt,
                   [vswhere, folder / 'discovery.stdout', folder / 'discovery.stderr'])
        raw = (folder / 'discovery.stdout').read_bytes()
        assert 0 < len(raw) <= 32768, 'Invalid MSVC discovery output'
        found = raw.decode('utf-8-sig').strip()
        assert '\n' not in found and '\r' not in found, 'Ambiguous MSVC installation'
        vcvars = Path(found) / 'VC/Auxiliary/Build/vcvarsall.bat'
        assert vcvars.is_file(), 'Native C++ compiler environment unavailable'
        library = folder / 'ascii-message-observer.dll'
        compile_script = folder / 'compile.cmd'
        tool_arguments = []
        if compiler_mode == 'clang-lld':
            from native_compiler_tools import pin_native_tool
            llvm = _absolute(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'LLVM/bin')
            tool_arguments = [llvm / name for name in ('clang-cl.exe', 'lld-link.exe')]
            receipt['compiler'] = dict(mode='clang-lld', before={}, after={})
            receipt['compilerStatFacts'] = dict(before={}, after={})
            for tool in tool_arguments:
                facts = {}
                receipt['compilerStatFacts']['before'][tool.name] = facts
                receipt['compiler']['before'][tool.name] = pin_native_tool(tool, architecture, check=budget.now, facts=facts)
            target = 'aarch64-pc-windows-msvc' if architecture == 'arm64' else 'x86_64-pc-windows-msvc'
            compile_script.write_text('@echo off\nset "VSCMD_SKIP_SENDTELEMETRY=1"\ncall "%~1"'
                + (' arm64' if architecture == 'arm64' else ' x64')
                + ' >"%~2" 2>&1\nif errorlevel 1 exit /b 1\n'
                + '"%~7" --target=' + target + ' /nologo /c /O2 /MT /EHsc /std:c++17 /W4 /utf-8 "%~3"'
                + ' /Foascii_message_observer.obj >"%~5" 2>"%~6"\nif errorlevel 1 exit /b 1\n'
                + '"%~8" /NOLOGO /DLL /MACHINE:' + ('ARM64' if architecture == 'arm64' else 'X64')
                + ' /OUT:"%~4" /IMPLIB:ascii_message_observer.lib ascii_message_observer.obj user32.lib kernel32.lib'
                + ' >>"%~5" 2>>"%~6"\nexit /b %errorlevel%\n', encoding='ascii')
        else:
            compile_script.write_text('@echo off\nset "VSCMD_SKIP_SENDTELEMETRY=1"\ncall "%~1"' + (' arm64' if architecture == 'arm64' else ' x64')
                + ' >"%~2" 2>&1\nif errorlevel 1 exit /b 1\n'
                + 'cl.exe /nologo /LD /O2 /MT /EHsc /std:c++17 /W4 /utf-8 "%~3" /link /MACHINE:'
                + ('ARM64' if architecture == 'arm64' else 'X64')
                + ' /OUT:"%~4" user32.lib kernel32.lib >"%~5" 2>"%~6"\nexit /b %errorlevel%\n', encoding='ascii')
        _run_stage(runtime, folder, 'compile', compile_script, budget, receipt,
                   [vcvars, folder / 'environment.log', folder / SOURCES[0], library,
                    folder / 'compiler.stdout', folder / 'compiler.stderr', *tool_arguments])
        if tool_arguments:
            for tool in tool_arguments:
                facts = {}
                receipt['compilerStatFacts']['after'][tool.name] = facts
                receipt['compiler']['after'][tool.name] = pin_native_tool(tool, architecture, check=budget.now, facts=facts)
            assert receipt['compiler']['before'] == receipt['compiler']['after'], 'Native compiler tools changed during preparation'
        native_arch.require_native_pe(library, architecture)
        receipt['library'] = dict(path=str(library), **_pin(library))
        for name in SOURCES:
            assert _pin(SOURCE_ROOT / name) == _pin(folder / name) == receipt['sourcePins'][name], 'Observer source changed during preparation'
        receipt['outputs'] = {p.name: _pin(p) for p in sorted(folder.iterdir()) if p.is_file()}
        receipt.update(success=True, finishedAt=budget.now())
    except BaseException as exc:
        receipt['success'] = False
        receipt['error'] = dict(type=type(exc).__name__, message=str(exc)[:1024])
        raise
    finally:
        primary = sys.exc_info()[1]
        try:
            _write_json(receipt_path, receipt)
        except BaseException as later:
            if primary is None:
                raise
            primary.preparationReceiptError = dict(type=type(later).__name__, message=str(later)[:1024])
    descriptor = dict(schemaVersion=1, kind='prepared-ascii-message-observer', architecture=architecture,
                sourcePins=receipt['sourcePins'], library=receipt['library'],
                preparationReceipt=dict(path=str(receipt_path), **_pin(receipt_path)))
    if 'compiler' in receipt: descriptor['compiler'] = receipt['compiler']
    budget.now(cleanup=True)
    return descriptor


def require_prepared_library(descriptor, *, architecture=None):
    assert type(descriptor) is dict and type(descriptor.get('schemaVersion')) is int and descriptor['schemaVersion'] == 1
    assert descriptor.get('kind') == 'prepared-ascii-message-observer', 'Missing original observer preparation'
    selected = native_arch.require_architecture(descriptor.get('architecture'))
    assert architecture is None or selected == architecture, 'Prepared observer architecture differs'
    native_arch.validate_native_architecture(native_arch.observe_native_architecture(), selected)
    library = _absolute(descriptor['library']['path'])
    proof = _absolute(descriptor['preparationReceipt']['path'])
    assert proof.parent == library.parent and proof.name == 'preparation.json'
    assert library.name == 'ascii-message-observer.dll'
    assert _pin(library) == {key: descriptor['library'][key] for key in ('bytes', 'sha256')}
    assert _pin(proof) == {key: descriptor['preparationReceipt'][key] for key in ('bytes', 'sha256')}
    receipt = json.loads(proof.read_bytes())
    assert (receipt['kind'], receipt['schemaVersion'], receipt['architecture'], receipt['success']) == \
        ('ascii-message-observer-preparation', 1, selected, True)
    assert type(receipt['schemaVersion']) is int and receipt['success'] is True and receipt['library'] == descriptor['library']
    assert receipt['sourcePins'] == descriptor['sourcePins'] and set(receipt['sourcePins']) == set(SOURCES)
    if 'compiler' in receipt or 'compiler' in descriptor:
        from native_compiler_tools import validate_tool_pin
        compiler = receipt['compiler']
        assert compiler == descriptor['compiler'] and set(compiler) == {'mode', 'before', 'after'}
        assert compiler['mode'] == 'clang-lld' and compiler['before'] == compiler['after']
        assert set(compiler['before']) == {'clang-cl.exe', 'lld-link.exe'}
        for name, value in compiler['before'].items(): validate_tool_pin(value, selected, name)
        assert receipt['stages'][1]['command'][-2:] == [compiler['before'][name]['path'] for name in ('clang-cl.exe', 'lld-link.exe')]
    native_arch.validate_native_architecture(receipt['nativeArchitecture'], selected)
    times = [receipt[key] for key in ('startedAt', 'finishedAt', 'workDeadline', 'deadline')]
    assert all(type(value) in (int, float) and math.isfinite(value) for value in times)
    start, finish, work, deadline = times
    assert start <= finish < work == deadline - CLEANUP_RESERVE and deadline == start + LIMIT
    assert [row['stage'] for row in receipt['stages']] == ['discovery', 'compile']
    prior = start
    for row in receipt['stages']:
        assert row['natural'] is True and row['handlesClosed'] is True and not row['cleanupErrors']
        assert 'error' not in row and 'forcedOwnedJobCleanup' not in row
        assert prior <= row['startedAt'] <= row['finishedAt'] <= finish
        assert type(row['queryCount']) is int and 1 <= row['queryCount'] <= QUERY_CAP
        assert len(row['samples']) == min(row['queryCount'], 64) and row['droppedSamples'] == max(0, row['queryCount'] - 64)
        identity = row['identity']
        assert all(type(identity[key]) is int and identity[key] > 0 for key in ('pid', 'processHandle', 'jobHandle', 'creationTime'))
        previous_observation = row['startedAt']
        for sample in row['samples']:
            assert sample['querySucceeded'] is True and type(sample['returnLength']) is int and sample['returnLength'] == 48
            assert type(sample['rawHex']) is str and len(sample['rawHex']) == 96
            raw = bytes.fromhex(sample['rawHex'])
            total, active, terminated = struct.unpack_from('<III', raw, 36)
            assert all(type(sample[key]) is int for key in ('totalProcesses', 'activeProcesses', 'terminatedProcesses'))
            assert (sample['totalProcesses'], sample['activeProcesses'], sample['terminatedProcesses']) == (total, active, terminated)
            assert active <= total and 0 <= terminated <= total
            assert (type(sample['observedAt']) in (int, float) and math.isfinite(sample['observedAt'])
                    and previous_observation <= sample['observedAt'] <= row['finishedAt'])
            assert type(sample['root']['waitResult']) is int and sample['root']['waitResult'] in (0, 258)
            assert (sample['root']['exitCode'] is None if sample['root']['waitResult'] == 258
                    else type(sample['root']['exitCode']) is int and sample['root']['exitCode'] == 0)
            previous_observation = sample['observedAt']
        last = row['samples'][-1]
        assert (last['querySucceeded'] is True and type(last['returnLength']) is int and last['returnLength'] == 48
                and type(last['activeProcesses']) is int and last['activeProcesses'] == 0
                and type(last['root']['waitResult']) is int and last['root']['waitResult'] == 0
                and type(last['root']['exitCode']) is int and last['root']['exitCode'] == 0
                and row['startedAt'] <= last['observedAt'] <= row['finishedAt'])
        prior = row['finishedAt']
    for name in SOURCES:
        assert _pin(SOURCE_ROOT / name) == _pin(library.parent / name) == receipt['sourcePins'][name], 'Prepared observer source changed'
    for name, pin in receipt['outputs'].items():
        assert Path(name).name == name and _pin(library.parent / name) == pin, 'Observer preparation output changed'
    return native_arch.require_native_pe(library, selected)
