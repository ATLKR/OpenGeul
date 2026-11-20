#!/usr/bin/env python3
"""Compile a static ARM64 layout witness; never load or execute the emitted DLL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import ascii_message_preparation as shared

SOURCE = Path(__file__).resolve().with_name('mutex-layout-fixture.cpp')


def pin(path, budget, limit, *, allow_empty=False):
    budget.now()
    path = shared._absolute(path)
    assert path.is_file() and path.stat().st_size <= limit, 'Fixture input/output size rejected'
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(limit + 1)
        budget.now()
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    assert tuple(getattr(before, k) for k in fields) == tuple(getattr(after, k) for k in fields), 'Fixture file changed'
    assert (allow_empty or len(raw) > 0) and len(raw) == before.st_size <= limit, 'Fixture file size changed'
    result = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    budget.now()
    return raw, result


def public_stages(stages):
    # Existing private-Job helper keeps detailed commands/paths only in memory.
    result = []
    for stage in stages[:2]:
        row = {key: stage[key] for key in ('stage', 'startedAt', 'finishedAt', 'natural',
               'queryCount', 'droppedSamples', 'handlesClosed', 'forcedOwnedJobCleanup') if key in stage}
        row['cleanupErrorTypes'] = [v['type'] for v in stage.get('cleanupErrors', [])[:4]]
        if 'error' in stage: row['errorType'] = stage['error']['type']
        sample = stage.get('cleanupLastSample') or (stage.get('samples') or [None])[-1]
        if sample:
            row['finalAccounting'] = {key: sample[key] for key in ('querySucceeded', 'returnLength',
                 'activeProcesses', 'totalProcesses', 'terminatedProcesses')}
            row['root'] = sample['root']
        result.append(row)
    return result


def prepare(output, *, architecture):
    budget = shared._Budget()
    assert architecture == 'arm64', 'Compile-only fixture requires native ARM64'
    folder = shared._absolute(output)
    budget.now()
    folder.mkdir(parents=True, exist_ok=False)
    receipt = dict(schemaVersion=1, kind='compile-only-mutex-layout-fixture', architecture=architecture,
                   startedAt=budget.started, deadline=budget.deadline, workDeadline=budget.work_deadline,
                   success=False, executed=False, sourcePins={}, stages=[])
    internal = dict(stages=[])
    stage = 'input-validation'
    try:
        budget.now()
        shared.native_arch.validate_native_architecture(shared.native_arch.observe_native_architecture(), architecture)
        runtime = shared._Runtime()
        raw, source_pin = pin(SOURCE, budget, 65536)
        receipt['sourcePins'][SOURCE.name] = source_pin
        _, helper_pin = pin(Path(__file__).resolve(), budget, 65536)
        receipt['sourcePins'][Path(__file__).name] = helper_pin
        shared_source = Path(shared.__file__).resolve()
        _, shared_pin = pin(shared_source, budget, 65536)
        receipt['sourcePins'][shared_source.name] = shared_pin
        local_source = folder / SOURCE.name
        local_source.write_bytes(raw)
        assert pin(local_source, budget, 65536)[1] == source_pin
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        assert vswhere.is_file(), 'Existing MSVC discovery unavailable'
        discovery = folder / 'discover.cmd'
        discovery.write_text('@echo off\n"%~1" -utf8 -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.ARM64 -property installationPath >"%~2" 2>"%~3"\nexit /b %errorlevel%\n', encoding='ascii')
        stage = 'discovery'
        shared._run_stage(runtime, folder, 'discovery', discovery, budget, internal,
                          [vswhere, folder / 'discovery.stdout', folder / 'discovery.stderr'])
        raw, _ = pin(folder / 'discovery.stdout', budget, 32768)
        found = raw.decode('utf-8-sig').strip()
        assert found and '\n' not in found and '\r' not in found, 'Ambiguous MSVC installation'
        vcvars = shared._absolute(Path(found) / 'VC/Auxiliary/Build/vcvarsall.bat')
        assert vcvars.is_file(), 'Existing ARM64 MSVC environment unavailable'
        library = folder / 'mutex-layout-fixture.dll'
        compile_script = folder / 'compile.cmd'
        compile_script.write_text('@echo off\nset "VSCMD_SKIP_SENDTELEMETRY=1"\ncall "%~1" arm64 >"%~2" 2>&1\nif errorlevel 1 exit /b 1\n'
            'cl.exe /nologo /LD /O2 /MD /EHsc /GR /std:c++17 /W4 /utf-8 "%~3" /link /MACHINE:ARM64 /OPT:NOICF /INCREMENTAL:NO /OUT:"%~4" >"%~5" 2>"%~6"\nexit /b %errorlevel%\n', encoding='ascii')
        receipt['scriptPins'] = {p.name: pin(p, budget, 65536)[1] for p in (discovery, compile_script)}
        stage = 'compile'
        shared._run_stage(runtime, folder, 'compile', compile_script, budget, internal,
                          [vcvars, folder / 'environment.log', local_source, library,
                           folder / 'compiler.stdout', folder / 'compiler.stderr'])
        stage = 'output-validation'
        _, library_pin = pin(library, budget, 32 * 1024 * 1024)
        shared.native_arch.require_native_pe(library, architecture)
        budget.now()
        assert pin(library, budget, 32 * 1024 * 1024)[1] == library_pin, 'Fixture DLL changed'
        assert pin(SOURCE, budget, 65536)[1] == pin(local_source, budget, 65536)[1] == source_pin, 'Fixture source changed'
        assert pin(Path(__file__).resolve(), budget, 65536)[1] == helper_pin, 'Preparation source changed'
        assert pin(shared_source, budget, 65536)[1] == shared_pin, 'Shared preparation source changed'
        receipt['library'] = dict(name=library.name, machine=0xaa64, **library_pin)
        receipt.update(success=True, finishedAt=budget.now())
        return library
    except BaseException as error:
        receipt.update(success=False, errorType=type(error).__name__, errorStage=stage)
        raise
    finally:
        receipt['stages'] = public_stages(internal['stages'])
        primary = sys.exc_info()[1]
        try:
            receipt['compilerLogPins'] = {}
            for name in ('compiler.stdout', 'compiler.stderr'):
                try:
                    budget.now()
                    if (folder / name).is_file():
                        receipt['compilerLogPins'][name] = pin(folder / name, budget, 1024 * 1024, allow_empty=True)[1]
                except Exception as diagnostic_error:
                    receipt['compilerLogPinErrorType'] = type(diagnostic_error).__name__
                    break
            shared._write_json(folder / 'receipt.json', receipt)
            if primary is None:
                budget.now(cleanup=True)
        except BaseException as later:
            if primary is None: raise
            primary.fixtureReceiptErrorType = type(later).__name__


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--architecture', required=True, choices=('arm64',))
    args = parser.parse_args(argv)
    try:
        prepare(args.output, architecture=args.architecture)
        return 0
    except Exception as error:
        print('Compile-only fixture failed: ' + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
