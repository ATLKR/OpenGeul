"""Exact final Suite context adapter; x64 stays stdlib-only and performs no action."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'refs/heads/work/opengeul-office-native35-tsf-diagnostic'
WORKFLOW = 'ATLKR/OpenGeul/.github/workflows/office-suite-native35-tsf-diagnostic.yml@' + BRANCH
ADDITIONAL_SOURCE_FILES = ('e2e/native35_tsf_profile_prepare.py', '.github/workflows/office-suite-native35-tsf-diagnostic.yml',
                           'suite/scripts/prepare-native35-tsf-profile.ps1')
MAX_JSON = 256 * 1024


def require(value, message):
    if not value: raise ValueError(message)


def plain_path(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute unaliased path required')
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'Linked/reparse preparation path rejected')
    return path


def read_event():
    path = plain_path(Path(os.environ['GITHUB_EVENT_PATH']))
    with path.open('rb') as stream: raw = stream.read(MAX_JSON + 1)
    require(len(raw) <= MAX_JSON, 'Event exceeds finite bound')
    event = json.loads(raw)
    require(type(event) is dict, 'Actual event object required')
    return event


def validate_context(env, event, architecture, platform):
    require(architecture in ('arm64', 'x64'), 'Unknown Suite architecture')
    expected = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
        RUNNER_ARCH='ARM64' if architecture == 'arm64' else 'X64', GITHUB_REPOSITORY='ATLKR/OpenGeul',
        GITHUB_EVENT_NAME='push', GITHUB_JOB='windows-tsf-profile-diagnostic', GITHUB_REF=BRANCH, GITHUB_WORKFLOW_REF=WORKFLOW,
        GITHUB_RUN_ATTEMPT='1', GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341')
    require(platform == 'nt' and all(env.get(k) == v for k, v in expected.items()), 'Exact final Suite owner-push context required')
    sha = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) and env.get('GITHUB_WORKFLOW_SHA') == sha
            and re.fullmatch('[1-9][0-9]{0,19}', env.get('GITHUB_RUN_ID', '')), 'Suite source/run identity mismatch')
    repository, sender = event.get('repository'), event.get('sender')
    require(type(repository) is dict and repository.get('full_name') == 'ATLKR/OpenGeul'
            and repository.get('private') is False and type(repository.get('id')) is int and repository['id'] > 0,
            'Public owned Suite repository required')
    require(type(sender) is dict and sender.get('login') == 'ATLKR' and type(sender.get('id')) is int
            and sender['id'] == 65988341 and sender.get('type') == 'User', 'Actual owner event sender required')
    require(event.get('ref') == BRANCH and event.get('deleted') is False and event.get('after') == sha,
            'Actual Suite push ref/deleted/after mismatch')
    return dict(sourceCommit=sha, runId=env['GITHUB_RUN_ID'], runAttempt='1', architecture=architecture,
                repository='ATLKR/OpenGeul', ref=BRANCH, workflowRef=WORKFLOW, job='windows-tsf-profile-diagnostic', event='push')


def load_control():
    spec = importlib.util.spec_from_file_location('native31_suite_control', ROOT / 'e2e/native31_desktop_control.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def control_binding(core):
    return core.ControlBinding(BRANCH, WORKFLOW, 'windows-tsf-profile-diagnostic', 'e2e/native35_tsf_profile_prepare.py', ADDITIONAL_SOURCE_FILES)


def arm_entry(args, *, platform=None):
    validate_context(os.environ, read_event(), 'arm64', os.name if platform is None else platform)
    require(args.prepare_privacy, 'Suite action requires explicit preparation mode')
    core = load_control()
    return (core.observer if args.observer else core.controller)(args, binding=control_binding(core))


def x64_native_identity():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []; kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetCurrentProcessId.argtypes = []; kernel.GetCurrentProcessId.restype = ctypes.c_uint32
    kernel.IsWow64Process2.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16)]
    kernel.IsWow64Process2.restype = ctypes.c_int32
    kernel.ProcessIdToSessionId.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    kernel.ProcessIdToSessionId.restype = ctypes.c_int32
    process, native, session = ctypes.c_uint16(), ctypes.c_uint16(), ctypes.c_uint32()
    pid = kernel.GetCurrentProcessId()
    require(kernel.IsWow64Process2(kernel.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native))
            and kernel.ProcessIdToSessionId(pid, ctypes.byref(session)), 'x64 native identity unavailable')
    with open(sys.executable, 'rb') as stream:
        header = stream.read(64)
        require(len(header) == 64 and header[:2] == b'MZ', 'Python PE DOS header unavailable')
        offset = int.from_bytes(header[60:64], 'little'); require(64 <= offset <= 1024 * 1024, 'Python PE offset out of bounds')
        stream.seek(offset); pe = stream.read(6)
    require(len(pe) == 6 and pe[:4] == b'PE\0\0', 'Python PE signature unavailable')
    return dict(processId=pid, processMachine=process.value, nativeMachine=native.value, sessionId=session.value,
                peMachine=int.from_bytes(pe[4:6], 'little'), executable=sys.executable)


def x64_source_identity(root, sha, *, seconds=10):
    deadline = time.monotonic() + seconds
    def git(*arguments):
        remaining = deadline - time.monotonic(); require(remaining > 0, 'x64 source budget exhausted')
        result = subprocess.run(['git', '-C', str(root), *arguments], check=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=remaining)
        require(len(result.stdout) <= MAX_JSON, 'x64 source output exceeds bound')
        return result.stdout
    head = git('rev-parse', 'HEAD').decode().strip(); tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    require(head == sha and re.fullmatch('[0-9a-f]{40}', tree), 'x64 actual checkout identity differs')
    files = {}
    for name in ADDITIONAL_SOURCE_FILES:
        path = plain_path(root / name)
        with path.open('rb') as stream: actual = stream.read(MAX_JSON + 1)
        require(len(actual) <= MAX_JSON and actual == git('show', sha + ':' + name), 'x64 source bytes differ from exact commit')
        files[name] = hashlib.sha256(actual).hexdigest()
    return dict(head=head, tree=tree, files=files, sourceRoot=str(root))


def x64_entry(args, *, platform=None, native_reader=None, source_reader=None):
    output = plain_path(args.output); runner_temp = plain_path(Path(os.environ['RUNNER_TEMP']))
    require(output.parent == runner_temp and runner_temp.is_dir() and not output.exists(), 'Fresh direct output child required')
    output.mkdir()
    result = dict(readOnly=True, diagnosticOnly=True, actions=[], inputsPerformed=0, closeRequests=0,
                  consentActions=[], productExecuted=False, readiness=False, hostReadyQualified=False,
                  productQualified=False, privacyPreparationQualified=False, physicalTaskbarGatePassed=False,
                  physicalPointerGateInvocations=0, success=False, status='not-applicable')
    try:
        require(not args.observer and args.deadline is None, 'x64 has no observer/controller')
        result.update(validate_context(os.environ, read_event(), 'x64', os.name if platform is None else platform))
        native = (native_reader or x64_native_identity)()
        result['native'] = native
        require(native['processId'] > 0 and native['processMachine'] == 0 and native['nativeMachine'] == 0x8664
                and native['peMachine'] == 0x8664 and native['sessionId'] > 0, 'Actual native x64 self identity required')
        result['source'] = (source_reader or x64_source_identity)(ROOT, result['sourceCommit'])
        result['success'] = True
        return 0
    except Exception as exc:
        result.update(status='failure', failure={'type': type(exc).__name__, 'message': str(exc)[:2048]})
        return 1
    finally:
        raw = (json.dumps(result, indent=2) + '\n').encode()
        require(len(raw) <= MAX_JSON, 'x64 receipt exceeds bound')
        with (output / '99-not-applicable.json').open('xb') as stream: stream.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', choices=('arm64', 'x64'), default='arm64')
    parser.add_argument('--prepare-privacy', action='store_true')
    parser.add_argument('--observer', action='store_true')
    parser.add_argument('--deadline', type=float)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.observer == (args.deadline is not None), 'Observer/deadline arguments must be paired')
    return arm_entry(args) if args.architecture == 'arm64' else x64_entry(args)


if __name__ == '__main__':
    raise SystemExit(main())
