"""Run one unchanged preparation and retain finite failure-only build evidence.

This diagnostic branch does not build or qualify an Office package. Installed
MSVC batch files are copied after preparation, under a separate read-only copy
budget; that budget cannot extend or qualify the original preparation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback


def pin(path):
    data = path.read_bytes()
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def write_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()
    assert len(raw) <= 1024 * 1024
    with path.open('xb') as stream:
        stream.write(raw)


def ordinary(path):
    for part in (path, *path.parents):
        assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked diagnostic path'
    return path


def snapshot_scripts(preparation, output):
    """Copy bounded installed sources, never execute or change their contents."""
    started = time.monotonic()
    result = dict(startedAt=started, deadline=started + 8, complete=False, files=[])
    try:
        receipt = json.loads((preparation / 'preparation.json').read_bytes())
        commands = [row['command'] for row in receipt['stages'] if row['stage'] == 'compile']
        assert len(commands) == 1
        vcvars = ordinary(Path(commands[0][4]))
        assert vcvars.is_absolute() and vcvars.name.casefold() == 'vcvarsall.bat'
        install = vcvars.parents[3]
        assert vcvars.relative_to(install).as_posix().casefold() == 'vc/auxiliary/build/vcvarsall.bat'
        result['installation'] = str(install)
        candidates = []
        def walk_error(error):
            raise error
        for base in (install / 'VC/Auxiliary/Build', install / 'Common7/Tools/vsdevcmd'):
            ordinary(base)
            assert base.is_dir(), 'Installed script subtree is unavailable'
            for directory, children, names in os.walk(base, followlinks=False, onerror=walk_error):
                assert time.monotonic() < result['deadline'], 'Script snapshot copy deadline expired'
                parent = ordinary(Path(directory))
                children[:] = [name for name in children if not (parent / name).is_symlink()
                               and not getattr(parent / name, 'is_junction', lambda: False)()]
                for name in sorted(names):
                    if name.casefold().endswith('.bat'):
                        candidates.append(parent / name)
                        assert len(candidates) <= 255, 'Installed script count exceeds bound'
        candidates.append(install / 'Common7/Tools/VsDevCmd.bat')
        assert len(candidates) <= 256
        total = 0
        for source in sorted(set(candidates)):
            assert time.monotonic() < result['deadline'], 'Script snapshot copy deadline expired'
            ordinary(source)
            assert source.is_file() and source.stat().st_size <= 256 * 1024, 'Installed script exceeds bound'
            raw = source.read_bytes()
            total += len(raw)
            assert len(raw) <= 256 * 1024 and total <= 4 * 1024 * 1024, 'Script snapshot bytes exceed bound'
            relative = source.relative_to(install)
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            result['files'].append(dict(relativePath=relative.as_posix(), source=str(source),
                                        bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
            assert time.monotonic() < result['deadline'], 'Script snapshot copy deadline expired'
        result['complete'] = True
    except BaseException as exc:
        result['error'] = dict(type=type(exc).__name__, message=str(exc)[:1024])
    result['finishedAt'] = time.monotonic()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', choices=('x64', 'arm64'), required=True)
    parser.add_argument('--compiler-mode', choices=('msvc', 'clang-lld'), default='clang-lld')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert os.name == 'nt', 'Native Windows diagnosis only'
    output = ordinary(args.output)
    assert output.is_absolute()
    output.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[2]
    e2e = repository / 'suite/e2e'
    sources = [Path(__file__).resolve(), e2e / 'native_compiler_tools.py', e2e / 'ascii_message_preparation.py',
               e2e / 'ascii_message_observer.cpp', e2e / 'ascii_message_protocol.h',
               e2e / 'native_suite_architecture.py', repository / 'suite/worker/native_windows.py']
    source_before = {str(path.relative_to(repository)): pin(path) for path in sources}
    source_commit = os.environ.get('GITHUB_SHA', '')
    assert re.fullmatch('[0-9a-f]{40}', source_commit)
    result = dict(kind='one-native-compiler-preparation-diagnosis', sourceCommit=source_commit,
                  runId=os.environ.get('GITHUB_RUN_ID'), attempt=os.environ.get('GITHUB_RUN_ATTEMPT'),
                  architecture=args.architecture, compilerMode=args.compiler_mode, python=sys.version, pythonExecutable=sys.executable,
                  sourceBefore=source_before, success=False, officePackageQualified=False)
    preparation = output / 'preparation'
    try:
        sys.path.insert(0, str(e2e))
        from ascii_message_preparation import prepare_observer
        result['descriptor'] = prepare_observer(preparation, architecture=args.architecture, compiler_mode=args.compiler_mode)
        result['success'] = True
    except BaseException as exc:
        result['error'] = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    finally:
        result['installedScriptSnapshot'] = snapshot_scripts(preparation, output / 'installed-scripts')
        try:
            result['sourceAfter'] = {str(path.relative_to(repository)): pin(path) for path in sources}
        except BaseException as exc:
            result['sourceAfter'] = None
            result['sourceAfterError'] = dict(type=type(exc).__name__, message=str(exc)[:1024])
        if result['sourceAfter'] != source_before:
            result['success'] = False
            result['sourceDrift'] = True
        write_new(output / 'diagnosis.json', result)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
