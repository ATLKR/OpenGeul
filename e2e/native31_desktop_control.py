"""CI-only ARM64 desktop observation and explicit privacy preparation control.

The controller owns only its suspended diagnostic child and descendants. Legacy
Source/Store bindings and privacy classifier remain byte-for-byte unchanged.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time
import unicodedata
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'refs/heads/work/opengeul-office-native31-desktop-control'
WORKFLOW = 'ATLKR/OpenGeul/.github/workflows/office-native31-desktop-control.yml@' + BRANCH
PREPARE_BRANCH = 'refs/heads/work/opengeul-office-native31-privacy-prepare'
PREPARE_WORKFLOW = 'ATLKR/OpenGeul/.github/workflows/office-native31-privacy-prepare.yml@' + PREPARE_BRANCH
PREPARE_MAX_FILES = 72
MAX_JSON = 256 * 1024
MAX_CENSUS_WINDOWS = 256  # Native31 diagnostic only; legacy readiness remains 64.
MAX_FILES = 48
MAX_IMAGE = 128 * 1024 * 1024
SOURCE_FILES = ('e2e/native31_desktop_control.py', 'e2e/runner-ready.py',
                'ci/policy.py', '.github/workflows/office-native31-desktop-control.yml',
                'e2e/native31_privacy_prepare.py', '.github/workflows/office-native31-privacy-prepare.yml',
                'suite/e2e/native_window_evidence.py')
spec = importlib.util.spec_from_file_location('native31_legacy_classifier', ROOT / 'e2e/runner-ready.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
require = legacy.require


class ControlBinding(NamedTuple):
    """Explicit caller-owned context; standalone callers keep the strict defaults."""
    ref: str
    workflow: str
    job: str
    observer_entry: str
    additional_source_files: tuple[str, ...] = ()


def bound_hashes(binding):
    return source_hashes(additional_files=binding.additional_source_files) if binding else source_hashes()


def bound_source(budget, binding):
    return source_receipt(budget, additional_files=binding.additional_source_files) if binding else source_receipt(budget)


def flags(*, prepare_privacy=False):
    value = dict(readOnly=True, diagnosticOnly=True, actions=[], inputsPerformed=0,
                 readiness=False, hostReadyQualified=False, productQualified=False, productExecuted=False)
    if prepare_privacy:
        value.update(readOnly=False, consentActions=[], privacyPreparationQualified=False,
                     physicalTaskbarGatePassed=False, closeRequests=0, physicalPointerGateInvocations=0)
    return value


def error_record(exc):
    value = {'type': type(exc).__name__, 'message': str(exc)[:2048]}
    if hasattr(exc, 'details'): value['details'] = exc.details
    if hasattr(exc, 'cleanup_failures'): value['cleanupFailures'] = exc.cleanup_failures
    return value


def diagnostic_error(message, **details):
    error = ValueError(message)
    error.details = details
    return error


def encoded_json(value):
    # Escapes also preserve an invalid surrogate in a raw offending-property receipt.
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + '\n').encode('utf-8')


def validate_census(value):
    """Validate the full diagnostic census without changing legacy limits or rows."""
    legacy.shape(value, ('foregroundHwnd', 'windows', 'truncated'))
    legacy.integer(value['foregroundHwnd'])
    require(type(value['truncated']) is bool and type(value['windows']) is list
            and 1 <= len(value['windows']) <= MAX_CENSUS_WINDOWS, 'Diagnostic census bounds mismatch')
    seen = set()
    for row in value['windows']:
        # A one-row view is only schema validation; never a replacement census
        # or an assertion of enumeration completeness. Retain the original flag.
        legacy.validate_windows({'foregroundHwnd': value['foregroundHwnd'],
                                 'windows': [row], 'truncated': value['truncated']})
        require(row['hwnd'] not in seen, 'Duplicate diagnostic census HWND')
        seen.add(row['hwnd'])
    require(value['foregroundHwnd'] in seen, 'Diagnostic census foreground absent')
    require(len(encoded_json(value)) <= MAX_JSON, 'Diagnostic census JSON exceeds 256 KiB')


def uia_property(field, value):
    if field in ('name', 'automationId', 'className'):
        limit = 2048 if field == 'name' else 256
        require(type(value) is str, 'UIA ' + field + ' is not an available string')
        require(len(value) <= limit, 'UIA ' + field + ' exceeds ' + str(limit) + ' characters')
        allowed = '\r\n\t' if field == 'name' else ''
        require(all((unicodedata.category(char) not in ('Cc', 'Cs')) or char in allowed for char in value),
                'UIA ' + field + ' contains a forbidden control/surrogate')
    elif field in ('controlType', 'processId'):
        legacy.integer(value, 0)
    else:
        # COM UIA BOOL values can be bool or the exact native integer 0/1.
        require(type(value) is bool or (type(value) is int and value in (0, 1)), 'UIA ' + field + ' is not BOOL 0/1')
        value = bool(value)
    return value


def raw_property(value):
    raw = {'pythonType': type(value).__name__[:256], 'valueAvailable': True}
    if type(value) is str:
        raw.update(value=value[:2048], length=len(value), valueTruncated=len(value) > 2048)
    elif value is None or type(value) is bool or (type(value) is int and value.bit_length() <= 64):
        raw['value'] = value
    else:
        raw['valueAvailable'] = False
        if type(value) is float: raw['representation'] = repr(value)
    return raw


def validate_diagnostic_uia(value, hwnd):
    require(type(value) is dict and set(value) in ({'hwnd', 'nodes', 'truncated'},
            {'hwnd', 'nodes', 'truncated', 'error', 'partialNode'}), 'Diagnostic UIA fields mismatch')
    legacy.integer(hwnd)
    require(type(value['hwnd']) is int and value['hwnd'] == hwnd and type(value['nodes']) is list and len(value['nodes']) <= 64
            and type(value['truncated']) is bool, 'Diagnostic UIA bounds mismatch')
    for node in value['nodes']:
        legacy.shape(node, ('name', 'controlType', 'automationId', 'className', 'processId', 'enabled', 'offscreen'))
        for field, raw in node.items():
            normalized = uia_property(field, raw)
            require(type(normalized) is type(raw), 'Diagnostic UIA node must retain canonical native field types')
    require(len(encoded_json(value)) <= MAX_JSON, 'Diagnostic UIA JSON bound exceeded')


@contextmanager
def physical_queries(probe, evidence, name):
    # No third-party/UIA initialization is allowed while this token is outstanding.
    user = probe.user
    receipt = dict(requestedContext=-4, initialContext=None, previousContext=None, effectiveContext=None,
                   restoreReturnedContext=None, finalContext=None, effectiveMatchesRequested=False,
                   restored=False, primaryFailure=None, restoreFailure=None)
    previous = None; primary = None; cleanup = []
    try:
        receipt['initialContext'] = int(user.GetThreadDpiAwarenessContext() or 0)
        require(receipt['initialContext'], 'Initial thread DPI context unavailable')
        previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        receipt['previousContext'] = int(previous or 0)
        require(previous, 'PMv2 query coordinate context unavailable')
        receipt['effectiveContext'] = int(user.GetThreadDpiAwarenessContext() or 0)
        receipt['effectiveMatchesRequested'] = bool(user.AreDpiAwarenessContextsEqual(
            receipt['effectiveContext'], ctypes.c_void_p(-4)))
        require(receipt['effectiveMatchesRequested'], 'Physical PMv2 context mismatch')
        yield receipt
    except Exception as exc:
        primary = exc
        receipt['primaryFailure'] = error_record(exc)
        raise
    finally:
        if previous:
            try:
                receipt['restoreReturnedContext'] = int(user.SetThreadDpiAwarenessContext(previous) or 0)
                receipt['finalContext'] = int(user.GetThreadDpiAwarenessContext() or 0)
                receipt['restored'] = bool(receipt['restoreReturnedContext'] and receipt['finalContext']
                    and user.AreDpiAwarenessContextsEqual(receipt['finalContext'], previous)
                    and user.AreDpiAwarenessContextsEqual(receipt['finalContext'], receipt['initialContext']))
                require(receipt['restored'], 'Physical query DPI restore failed')
            except Exception as exc:
                receipt['restoreFailure'] = error_record(exc)
                cleanup.append({'stage': name, **error_record(exc)})
        try:
            evidence.write(name, receipt)
        except Exception as exc:
            cleanup.append({'stage': name + '-receipt', **error_record(exc)})
        if cleanup:
            if primary is None: primary = ValueError('Physical query DPI cleanup failed')
            primary.cleanup_failures = getattr(primary, 'cleanup_failures', []) + cleanup
            if receipt['primaryFailure'] is None: raise primary



class Budget:
    def __init__(self, seconds=120, *, clock=time.monotonic, deadline=None):
        self.clock = clock
        self.deadline = clock() + seconds if deadline is None else deadline

    def remaining(self, reserve=0):
        remaining = self.deadline - self.clock() - reserve
        if remaining <= 0:
            raise TimeoutError('Original 120 second deadline exhausted')
        return remaining


def unaliased(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute unaliased path required')
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'Symlink/reparse path rejected')
    return path


class Evidence:
    def __init__(self, path, *, max_files=MAX_FILES):
        require(max_files in (MAX_FILES, PREPARE_MAX_FILES), 'Unknown evidence file bound')
        self.path = unaliased(path)
        self.max_files = max_files

    @classmethod
    def create(cls, path, runner_temp, *, max_files=MAX_FILES):
        path, runner_temp = unaliased(path), unaliased(runner_temp)
        require(path.parent == runner_temp and runner_temp.is_dir() and not path.exists(),
                'Output must be a fresh direct child of owned RUNNER_TEMP')
        path.mkdir()
        return cls(path, max_files=max_files)

    def write(self, name, value):
        require(re.fullmatch('[a-z0-9-]{1,64}', name), 'Invalid evidence name')
        unaliased(self.path)
        limit = self.max_files if self.max_files == PREPARE_MAX_FILES else min(self.max_files, MAX_FILES)
        require(len(list(self.path.iterdir())) < limit, 'Evidence file count exceeded')
        raw = encoded_json(value)
        require(len(raw) <= MAX_JSON, 'Evidence JSON exceeds 256 KiB')
        with (self.path / (name + '.json')).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def validate_native(native):
    legacy.integer(native.get('processId'))
    legacy.integer(native.get('sessionId'), 0)
    require(type(native.get('processMachine')) is int and native['processMachine'] == 0
            and type(native.get('nativeMachine')) is int and native['nativeMachine'] == 0xAA64,
            'Actual native ARM64 process required')


def validate_execution(env, event, native, platform, *, prepare_privacy=False, binding=None):
    branch, workflow, job = (PREPARE_BRANCH, PREPARE_WORKFLOW, 'prepare') if prepare_privacy else (BRANCH, WORKFLOW, 'observe')
    if binding is not None:
        require(prepare_privacy and type(binding) is ControlBinding, 'Explicit binding requires preparation mode')
        branch, workflow, job = binding.ref, binding.workflow, binding.job
    expected = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
                    RUNNER_ARCH='ARM64', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_EVENT_NAME='push',
                    GITHUB_JOB=job, GITHUB_REF=branch, GITHUB_WORKFLOW_REF=workflow,
                    GITHUB_RUN_ATTEMPT='1', GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341')
    require(platform == 'nt' and all(env.get(k) == v for k, v in expected.items()), 'Exact hosted control binding required')
    source = legacy.commit_sha(env.get('GITHUB_SHA'))
    legacy.decimal(env.get('GITHUB_RUN_ID'))
    legacy.public_repository(event.get('repository'), owned=True)
    require(legacy.event_actor(event, env) == ('ATLKR', 65988341, 'User'), 'Owner actor required')
    require(event.get('ref') == branch and event.get('deleted') is False and event.get('after') == source,
            'Actual push ref/deleted/after mismatch')
    require(env.get('GITHUB_WORKFLOW_SHA') == source, 'Workflow SHA mismatch')
    validate_native(native)
    return dict(sourceCommit=source, runId=env['GITHUB_RUN_ID'],
                runAttempt='1', repository='ATLKR/OpenGeul', workflowRef=workflow, ref=branch,
                event='push', job=job, actor='ATLKR', actorId=65988341, actorType='User')


def validate_context(env, event, checkout, native, platform, *, prepare_privacy=False, binding=None):
    context = validate_execution(env, event, native, platform, prepare_privacy=prepare_privacy, binding=binding)
    require(checkout.get('head') == context['sourceCommit'] and checkout.get('dirty') is False,
            'Checkout SHA or clean source mismatch')
    legacy.commit_sha(checkout.get('tree'))
    return {**context, 'sourceTree': checkout['tree']}


def source_hashes(*, additional_files=()):
    require(type(additional_files) is tuple and len(additional_files) <= 8, 'Additional source file bound exceeded')
    result = {}
    for name in (*SOURCE_FILES, *additional_files):
        require(type(name) is str and re.fullmatch(r'[a-zA-Z0-9_./-]{1,256}', name)
                and not Path(name).is_absolute() and '..' not in Path(name).parts, 'Invalid source receipt path')
        path = unaliased(ROOT / name)
        with path.open('rb') as stream:
            raw = stream.read(MAX_JSON + 1)
        require(len(raw) <= MAX_JSON, 'Source file exceeds bounded receipt input')
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


def git_read(args, budget):
    result = subprocess.run(['git', '-C', str(ROOT), *args], check=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=budget.remaining())
    require(len(result.stdout) <= MAX_JSON, 'Git receipt too large')
    return result.stdout.decode('utf-8').strip()


def source_receipt(budget, *, additional_files=()):
    receipt = dict(head=git_read(['rev-parse', 'HEAD'], budget), tree=git_read(['rev-parse', 'HEAD^{tree}'], budget),
                   dirty=bool(git_read(['status', '--porcelain=v1', '--untracked-files=all', '--ignored'], budget)))
    receipt['files'] = source_hashes(additional_files=additional_files) if additional_files else source_hashes()
    return receipt


def same_host(before, after):
    fields = ('sessionId', 'windowsDirectory', 'windowsVersion', 'imageOS', 'imageVersion', 'desktop', 'windowStation')
    require(all(field in before and field in after and before[field] == after[field] for field in fields),
            'Controller/observer session, Windows/image/desktop mismatch')


def parking_point(rect):
    left, top, right, bottom = rect
    require(left < right and top < bottom, 'Taskbar rectangle empty')
    return [(left + right) // 2, bottom - 1] if right - left >= bottom - top else [right - 1, (top + bottom) // 2]


def classify(observed, session, windows, *, complete, stable):
    require(complete and stable, 'Incomplete/unavailable/truncated/raced observation')
    foreground = observed.get('foreground')
    require(type(foreground) is dict, 'Foreground unavailable')
    legacy.validate_windows({'foregroundHwnd': foreground['hwnd'], 'windows': [foreground], 'truncated': False})
    trees = observed.get('uia')
    require(type(trees) is list and 1 <= len(trees) <= 2, 'Complete target UIA required')
    for tree in trees:
        validate_diagnostic_uia(tree, tree['hwnd'])
        require(not tree['truncated'] and 'error' not in tree and tree['nodes'], 'UIA unavailable/truncated')
    foreground_trees = [tree for tree in trees if tree['hwnd'] == foreground['hwnd']]
    require(len(foreground_trees) == 1 and all(node['processId'] == foreground['processId']
            for node in foreground_trees[0]['nodes']), 'Foreground UIA ownership unavailable')
    processes = observed.get('processes')
    require(type(processes) is list and 1 <= len(processes) <= 8, 'Complete target processes required')
    for process in processes:
        require(process.get('createdFileTime', 0) > 0 and process.get('sessionId') == session
                and process.get('imageBytes', 0) > 0 and process['imageBytes'] <= MAX_IMAGE
                and re.fullmatch('[0-9a-f]{64}', process.get('imageSha256', ''))
                and process.get('signature', {}).get('status') not in (None, '', 'Unavailable', 'UnknownError'),
                'Process identity/image/signature unavailable')
    require(sum(process.get('processId') == foreground['processId'] for process in processes) == 1,
            'Foreground process identity unavailable')
    try:
        candidate = legacy.privacy_candidate(observed, session, windows)
    except (ValueError, KeyError) as exc:
        foreground = observed.get('foreground')
        # A plausible privacy surface must not turn a failed strict match into absence.
        attempted = foreground and (foreground.get('title') == 'Microsoft account'
            or foreground.get('className') == 'Windows.UI.Core.CoreWindow')
        attempted = attempted or any(node.get('automationId') == 'OobeSettingsAcceptButton'
            or node.get('name') == 'Choose privacy settings for your device'
            for tree in observed.get('uia', []) for node in tree.get('nodes', []))
        require(not attempted, 'Attempted privacy candidate rejected: ' + str(exc))
        return {**flags(), 'status': 'privacy-absent-observed', 'classifierRejection': error_record(exc),
                'absenceScope': 'Complete current foreground only; original failure is not qualified'}
    return {**flags(), 'status': 'privacy-match', 'candidate': candidate,
            'candidateOperationNotExecuted': candidate['operation']}


def await_job_retirement(owner, budget, receipt):
    """Observe only the retained Job, inside the original cleanup reserve."""
    receipt['startedMonotonic'] = budget.clock()
    try:
        for _ in range(4096):
            budget.remaining(3)
            started = budget.clock()
            row = {'phase': 'job-retirement', 'startedMonotonic': started}
            try:
                row.update(owner.accounting())
            except Exception as exc:
                row.update(querySucceeded=None, failure=error_record(exc))
                raise
            finally:
                finished = budget.clock()
                row.update(finishedMonotonic=finished,
                           remainingSeconds=max(0, budget.deadline - finished))
                receipt['sampleCount'] += 1
                receipt['samples'].append(row)
                if len(receipt['samples']) > 64:
                    del receipt['samples'][16]
                    receipt['samplesDropped'] += 1
            require(row['querySucceeded'] is True, 'Owned job accounting unavailable')
            budget.remaining(3)  # A zero returned after the reserve is not readiness.
            if row['activeProcesses'] == 0:
                return
            time.sleep(min(0.05, budget.remaining(3)))
        raise TimeoutError('Owned job retirement observation count exhausted')
    finally:
        receipt['finishedMonotonic'] = budget.clock()
        receipt['remainingSeconds'] = max(0, budget.deadline - receipt['finishedMonotonic'])


def run_owned(owner, budget, evidence, *, prepare_privacy=False):
    result = {**flags(prepare_privacy=prepare_privacy), 'success': False, 'forced': False,
              'timedOut': False, 'naturalExit': False, 'jobRetiredNaturally': False,
              'jobRetirement': {'deadlineMonotonic': budget.deadline, 'cleanupReserveSeconds': 3,
                                'sampleCount': 0, 'samplesDropped': 0, 'samples': []}}
    evidence.write('20-observer-launch', {**flags(prepare_privacy=prepare_privacy), 'deadlineMonotonic': budget.deadline, 'stage': 'before-create'})
    try:
        budget.remaining(3)
        owner.create_suspended()
        owner.assign()
        result['observer'] = owner.identity()
        evidence.write('21-observer-bound', result['observer'])
        budget.remaining(3)
        owner.resume()
        if not owner.wait(budget.remaining(3)):
            raise TimeoutError('Diagnostic observer did not exit before original deadline reserve')
        result['exitCode'] = owner.exit_code()
        # The process handle can signal before the Job's accounting retires it
        # or its descendants. Natural root exit alone cannot qualify containment.
        result['naturalExit'] = True
        await_job_retirement(owner, budget, result['jobRetirement'])
        result['jobRetiredNaturally'] = True
        require(result['exitCode'] == 0, 'Observer returned diagnostic failure')
        result['success'] = True
    except Exception as exc:
        result['failure'] = error_record(exc)
        result['timedOut'] = isinstance(exc, TimeoutError)
        # Unknown or nonzero accounting is never treated as an empty Job.
        # Do not retry a failed query or spend the reserved cleanup time polling.
        needs_cleanup = owner.created and not result['jobRetiredNaturally']
        if needs_cleanup:
            result['forced'] = True
            try:
                owner.terminate_owned()
            except Exception as cleanup:
                result['cleanupFailure'] = error_record(cleanup)
    finally:
        try:
            owner.close()
        except Exception as cleanup:
            result['success'] = False
            result['cleanupFailure'] = error_record(cleanup)
        result['ownedCleanupOutcomes'] = list(owner.cleanup_outcomes)
        result['success'] = result['success'] and not result['forced']
        evidence.write('90-owned-lifecycle', result)
    return result


class Probe(legacy.WindowsProbe):
    """Strict query-only replacement for permissive observation methods."""
    def __init__(self):
        super().__init__()
        self.shell = ctypes.WinDLL('shell32', use_last_error=True)
        for name, args, result in [
            ('GetAncestor', [W.HWND, W.UINT], W.HWND), ('GetWindow', [W.HWND, W.UINT], W.HWND),
            ('GetWindowLongPtrW', [W.HWND, ctypes.c_int], ctypes.c_ssize_t),
            ('FindWindowW', [W.LPCWSTR, W.LPCWSTR], W.HWND),
            ('WindowFromPhysicalPoint', [W.POINT], W.HWND),
            ('GetThreadDesktop', [W.DWORD], W.HANDLE), ('GetProcessWindowStation', [], W.HANDLE),
            ('GetUserObjectInformationW', [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD, ctypes.POINTER(W.DWORD)], W.BOOL),
            ('SetThreadDpiAwarenessContext', [W.HANDLE], W.HANDLE),
            ('GetThreadDpiAwarenessContext', [], W.HANDLE),
            ('AreDpiAwarenessContextsEqual', [W.HANDLE, W.HANDLE], W.BOOL)]:
            api = getattr(self.user, name); api.argtypes = args; api.restype = result
        self.kernel.GetCurrentThreadId.restype = W.DWORD

    def named_object(self, handle):
        require(handle, 'Desktop/window station handle unavailable')
        buffer = ctypes.create_unicode_buffer(257); needed = W.DWORD()
        require(self.user.GetUserObjectInformationW(handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)),
                'Desktop/window station name unavailable')
        legacy.text(buffer.value)
        return buffer.value

    def identity(self):
        value = {**self.host(), 'sessionId': self.session_id(), 'windowsDirectory': self.windows_directory(),
                 'windowsVersion': list(sys.getwindowsversion()[:5]),
                 'imageOS': os.environ.get('ImageOS'), 'imageVersion': os.environ.get('ImageVersion'),
                 'desktop': self.named_object(self.user.GetThreadDesktop(self.kernel.GetCurrentThreadId())),
                 'windowStation': self.named_object(self.user.GetProcessWindowStation())}
        validate_native(value)
        require(all(value[k] for k in ('imageOS', 'imageVersion', 'desktop', 'windowStation')), 'Host image/desktop unavailable')
        value['process'] = self.process_identity(self.kernel.GetCurrentProcess(), value['processId'])
        return value

    def process_identity(self, handle, pid):
        state = self.startup_process_state(handle, pid)
        require(state['createdFileTime'] > 0 and state['exitCode'] == 259, 'Process unavailable or exited')
        size = W.DWORD(1025); buffer = ctypes.create_unicode_buffer(1025)
        require(self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) and size.value <= 1024,
                'Process image path unavailable/truncated')
        legacy.text(buffer.value, 1024)
        return {'processId': pid, 'imagePath': buffer.value, **state}

    def text_value(self, hwnd, class_name=False):
        buffer = ctypes.create_unicode_buffer(258)
        ctypes.set_last_error(0)
        function = self.user.GetClassNameW if class_name else self.user.GetWindowTextW
        length = function(hwnd, buffer, 258)
        require(0 <= length <= 256 and (length or not class_name) and ctypes.get_last_error() == 0,
                'Window text unavailable/truncated')
        legacy.text(buffer.value)
        return buffer.value

    def window(self, hwnd):
        require(hwnd and self.user.IsWindow(hwnd), 'Window absent/raced')
        pid = W.DWORD(); tid = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)); rect = W.RECT()
        require(tid and pid.value and self.user.GetWindowRect(hwnd, ctypes.byref(rect)), 'Window identity/rectangle unavailable')
        row = dict(hwnd=int(hwnd), processId=pid.value, threadId=int(tid), title=self.text_value(hwnd),
                   className=self.text_value(hwnd, True), visible=bool(self.user.IsWindowVisible(hwnd)),
                   enabled=bool(self.user.IsWindowEnabled(hwnd)), rectangle=[rect.left, rect.top, rect.right, rect.bottom])
        legacy.validate_windows({'foregroundHwnd': int(hwnd), 'windows': [row], 'truncated': False})
        return row

    def target(self, hwnd):
        row = self.window(hwnd)
        for field, offset in [('style', -16), ('exStyle', -20)]:
            ctypes.set_last_error(0); value = self.user.GetWindowLongPtrW(hwnd, offset)
            require(value or not ctypes.get_last_error(), 'Window style unavailable')
            row[field] = int(value) & 0xffffffff
        row['rootHwnd'] = int(self.user.GetAncestor(hwnd, 2) or 0)
        require(row['rootHwnd'], 'Window root unavailable')
        ctypes.set_last_error(0)
        row['ownerHwnd'] = int(self.user.GetWindow(hwnd, 4) or 0)
        require(not ctypes.get_last_error(), 'Window owner query failed')
        row['ownerAbsent'] = row['ownerHwnd'] == 0
        return row

    def census(self):
        foreground = int(self.user.GetForegroundWindow() or 0)
        # A zero result can represent a transient activation, so cannot prove absence.
        require(foreground, 'Foreground unavailable/transient')
        rows = [self.window(foreground)]; errors = []; truncated = False
        def callback(hwnd, _):
            nonlocal truncated
            try:
                if any(row['hwnd'] == int(hwnd) for row in rows): return True
                if len(rows) == MAX_CENSUS_WINDOWS:
                    truncated = True; return False
                rows.append(self.window(hwnd)); return True
            except Exception as exc:
                errors.append(error_record(exc)); return False
        cb = self.callback(callback)
        result = bool(self.user.EnumWindows(cb, 0))
        return dict(foregroundHwnd=foreground, windows=rows, truncated=truncated), errors, result

    def taskbar(self):
        class AppBarData(ctypes.Structure):
            _fields_ = [('cbSize', W.DWORD), ('hWnd', W.HWND), ('uCallbackMessage', W.UINT),
                        ('uEdge', W.UINT), ('rc', W.RECT), ('lParam', W.LPARAM)]
        self.shell.SHAppBarMessage.argtypes = [W.DWORD, ctypes.POINTER(AppBarData)]
        self.shell.SHAppBarMessage.restype = ctypes.c_size_t
        hwnd = int(self.user.FindWindowW('Shell_TrayWnd', None) or 0)
        target = self.target(hwnd)
        require(target['className'] == 'Shell_TrayWnd' and target['visible'], 'Visible taskbar required')
        data = AppBarData(); data.cbSize = ctypes.sizeof(data)
        require(self.shell.SHAppBarMessage(5, ctypes.byref(data)), 'ABM_GETTASKBARPOS failed')
        rectangle = [data.rc.left, data.rc.top, data.rc.right, data.rc.bottom]
        point = parking_point(rectangle)
        hit = int(self.user.WindowFromPhysicalPoint(W.POINT(*point)) or 0)
        root = int(self.user.GetAncestor(hit, 2) or 0) if hit else 0
        require(hit and root, 'Physical point hit/root unavailable')
        return dict(taskbarHwnd=hwnd, taskbarRect=rectangle, chosenPhysicalPoint=point,
                    actualPointHwnd=hit, actualRootHwnd=root, rootEqualsTaskbar=root == hwnd,
                    pointerMoved=False, taskbar=target)

    def strict_uia(self, hwnd):
        """Retain full bounded names and the exact failing property's diagnostic data."""
        result = {'hwnd': hwnd, 'nodes': [], 'truncated': False}
        location = dict(stage='initialize', nodeIndex=0, property=None, field=None)
        partial = {}; raw = None
        try:
            from pywinauto.uia_defines import IUIA
            api = IUIA(); root = api.iuia.ElementFromHandle(hwnd); walker = api.iuia.ControlViewWalker; pending = [root]
            fields = [('name', 'CurrentName'), ('controlType', 'CurrentControlType'),
                      ('automationId', 'CurrentAutomationId'), ('className', 'CurrentClassName'),
                      ('processId', 'CurrentProcessId'), ('enabled', 'CurrentIsEnabled'), ('offscreen', 'CurrentIsOffscreen')]
            while pending:
                if len(result['nodes']) >= 64:
                    result['truncated'] = True; break
                element = pending.pop(); partial = {}
                for field, property_name in fields:
                    location = dict(stage='property', nodeIndex=len(result['nodes']), property=property_name, field=field)
                    raw = {'valueAvailable': False, 'pythonType': None}
                    value = getattr(element, property_name)
                    raw = raw_property(value)
                    partial[field] = uia_property(field, value)
                location = dict(stage='node-json-bound', nodeIndex=len(result['nodes']), property=None, field=None)
                raw = None
                # Reserve space for a full partial node, offending-value preview, and error.
                require(len(encoded_json({**result, 'nodes': result['nodes'] + [partial]})) <= MAX_JSON - 65536,
                        'UIA aggregate JSON capacity exhausted; node not appended')
                result['nodes'].append(partial); partial = {}; raw = None
                location = dict(stage='first-child', nodeIndex=len(result['nodes']) - 1, property=None, field=None)
                child = walker.GetFirstChildElement(element); siblings = []
                while child and len(siblings) + len(pending) + len(result['nodes']) < 64:
                    siblings.append(child)
                    location['stage'] = 'next-sibling'
                    child = walker.GetNextSiblingElement(child)
                if child: result['truncated'] = True
                pending.extend(reversed(siblings))
        except Exception as exc:
            hresult = getattr(exc, 'hresult', None)
            result['error'] = {**error_record(exc), **location, 'raw': raw,
                               'hresult': f'0x{hresult & 0xffffffff:08x}' if type(hresult) is int else None}
            result['partialNode'] = partial
        # The caller persists this raw/partial record before structural validation.
        return result


def image_receipt(path, budget):
    path = unaliased(Path(path))
    size = path.stat().st_size
    require(0 < size <= MAX_IMAGE, 'Process image byte limit exceeded')
    digest = hashlib.sha256(); total = 0
    with path.open('rb') as stream:
        header = stream.read(64)
        require(len(header) == 64 and header[:2] == b'MZ', 'PE DOS header absent')
        offset = struct.unpack_from('<I', header, 60)[0]
        require(64 <= offset <= size - 6, 'PE offset invalid')
        stream.seek(offset); pe = stream.read(6)
        require(pe[:4] == b'PE\0\0', 'PE signature absent')
        machine = struct.unpack_from('<H', pe, 4)[0]
        stream.seek(0)
        while True:
            budget.remaining()
            block = stream.read(min(1024 * 1024, MAX_IMAGE + 1 - total))
            if not block: break
            total += len(block); require(total <= size and total <= MAX_IMAGE, 'Image changed/oversized')
            digest.update(block)
    require(total == size == path.stat().st_size, 'Image size changed')
    return dict(imageBytes=size, imageSha256=digest.hexdigest(), peMachine=machine)


def signatures(paths, budget):
    # Fixed script and JSON stdin; no interpolated paths, no profile or shell input.
    script = "$ErrorActionPreference='Stop'; $p=[Console]::In.ReadToEnd()|ConvertFrom-Json; @($p|ForEach-Object { $s=Get-AuthenticodeSignature -LiteralPath $_ -ErrorAction Stop; @{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject;issuer=[string]$s.SignerCertificate.Issuer;thumbprint=[string]$s.SignerCertificate.Thumbprint} })|ConvertTo-Json -Compress"
    executable = Path(os.environ['NATIVE31_PWSH'])
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', script],
        input=json.dumps(paths).encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=min(20, budget.remaining()))
    require(result.returncode == 0 and len(result.stdout) <= 16384, 'Signature query failed/oversized')
    values = json.loads(result.stdout.decode('utf-8-sig'))
    if isinstance(values, dict): values = [values]
    require(type(values) is list and len(values) == len(paths), 'Signature result count mismatch')
    for value in values:
        legacy.shape(value, ('status', 'subject', 'issuer', 'thumbprint'))
        for field in value: legacy.text(value[field])
        require(value['status'] not in ('', 'UnknownError', 'Unavailable'), 'Signature unavailable')
        value['publisherMicrosoft'] = value['status'] == 'Valid' and bool(re.search(r'(?:CN|O)=Microsoft(?: Windows| Corporation)', value['subject']))
    return values


class OwnedObserver:
    """Only this CreateProcess handle and its assigned job can be terminated."""
    def __init__(self, probe, env, argv, budget, expected):
        self.probe, self.env, self.argv, self.budget, self.expected = probe, env, argv, budget, expected
        self.created = False; self.process = self.thread = self.job = None; self.assigned = False
        self.cleanup_outcomes = []
        kernel = self.probe.kernel
        for name, args, result in [
            ('CreateJobObjectW', [W.LPVOID, W.LPCWSTR], W.HANDLE),
            ('SetInformationJobObject', [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD], W.BOOL),
            ('QueryInformationJobObject', [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD, W.LPVOID], W.BOOL),
            ('AssignProcessToJobObject', [W.HANDLE, W.HANDLE], W.BOOL),
            ('TerminateJobObject', [W.HANDLE, W.UINT], W.BOOL),
            ('TerminateProcess', [W.HANDLE, W.UINT], W.BOOL),
            ('ResumeThread', [W.HANDLE], W.DWORD),
            ('WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD)]:
            api = getattr(kernel, name); api.argtypes = args; api.restype = result

    def create_suspended(self):
        import _winapi
        self.process, self.thread, self.pid, self.tid = _winapi.CreateProcess(
            sys.executable, subprocess.list2cmdline(self.argv), None, None, False,
            0x00000004 | 0x00000400 | 0x08000000, self.env, str(ROOT), subprocess.STARTUPINFO())
        self.created = True

    def assign(self):
        class BasicLimit(ctypes.Structure):
            _fields_ = [('perProcessTime', ctypes.c_int64), ('perJobTime', ctypes.c_int64),
                        ('flags', W.DWORD), ('minWorkingSet', ctypes.c_size_t), ('maxWorkingSet', ctypes.c_size_t),
                        ('activeProcessLimit', W.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', W.DWORD), ('scheduling', W.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('readOps','writeOps','otherOps','readBytes','writeBytes','otherBytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', BasicLimit), ('io', IO), ('processMemory', ctypes.c_size_t),
                        ('jobMemory', ctypes.c_size_t), ('peakProcessMemory', ctypes.c_size_t), ('peakJobMemory', ctypes.c_size_t)]
        self.job = self.probe.kernel.CreateJobObjectW(None, None)
        require(self.job, 'Owned job creation failed')
        limit = Extended(); limit.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        require(self.probe.kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limit), ctypes.sizeof(limit)),
                'Owned kill-on-close job configuration failed')
        require(self.probe.kernel.AssignProcessToJobObject(self.job, self.process), 'Suspended observer assignment failed')
        self.assigned = True

    def identity(self):
        identity = self.probe.process_identity(self.process, self.pid)
        validate_native(identity)
        require(identity['sessionId'] == self.expected['sessionId']
                and ntpath.normcase(identity['imagePath']) == ntpath.normcase(sys.executable),
                'Suspended observer executable/session mismatch')
        receipt = image_receipt(identity['imagePath'], self.budget)
        require(receipt['peMachine'] == 0xAA64, 'Observer executable PE is not ARM64')
        require(receipt == self.expected['executable'], 'Controller/observer executable bytes mismatch')
        return {**identity, **receipt, 'threadId': self.tid, 'processHandle': int(self.process),
                'threadHandle': int(self.thread), 'jobHandle': int(self.job), 'assignedBeforeResume': self.assigned,
                'argv': self.argv, 'environment': self.env, 'sourceFiles': self.expected['sourceFiles']}

    def resume(self):
        require(self.assigned, 'Observer must be job-owned before resume')
        require(self.probe.kernel.ResumeThread(self.thread) == 1, 'Suspended observer resume failed')

    def wait(self, seconds):
        result = self.probe.kernel.WaitForSingleObject(self.process, max(1, int(seconds * 1000)))
        require(result in (0, 258), 'Observer handle wait failed')
        return result == 0

    def exit_code(self):
        code = W.DWORD()
        require(self.probe.kernel.GetExitCodeProcess(self.process, ctypes.byref(code)), 'Observer exit code unavailable')
        return code.value

    def accounting(self):
        require(self.assigned and self.job, 'Owned job accounting requires the retained assigned Job')
        class Accounting(ctypes.Structure):
            _fields_ = [('userTime', ctypes.c_int64), ('kernelTime', ctypes.c_int64),
                        ('periodUserTime', ctypes.c_int64), ('periodKernelTime', ctypes.c_int64),
                        ('faults', ctypes.c_uint32), ('total', ctypes.c_uint32),
                        ('active', ctypes.c_uint32), ('terminated', ctypes.c_uint32)]
        account = Accounting()
        result = self.probe.kernel.QueryInformationJobObject(self.job, 1, ctypes.byref(account), ctypes.sizeof(account), None)
        fields = {'totalUserTime100ns': 'userTime', 'totalKernelTime100ns': 'kernelTime',
                  'periodUserTime100ns': 'periodUserTime', 'periodKernelTime100ns': 'periodKernelTime',
                  'totalPageFaultCount': 'faults', 'totalProcesses': 'total',
                  'activeProcesses': 'active', 'totalTerminatedProcesses': 'terminated'}
        return {'jobHandle': int(self.job), 'queryClass': 1, 'bufferBytes': ctypes.sizeof(account),
                'queryResult': int(result), 'querySucceeded': bool(result),
                'lastError': None if result else getattr(ctypes, 'get_last_error', lambda: 0)(),
                **{key: int(getattr(account, field)) if result else None for key, field in fields.items()}}

    def descendants_empty(self):
        if not self.assigned: return True
        receipt = self.accounting()
        require(receipt['querySucceeded'], 'Owned job accounting unavailable')
        return receipt['activeProcesses'] == 0

    def cleanup_call(self, operation, handle, *arguments):
        # Mandatory cleanup is never gated by an expired observation deadline.
        row = {'operation': operation, 'handle': int(handle), 'startedMonotonic': self.budget.clock()}
        if arguments: row['exitCodeArgument'] = arguments[0]
        try:
            result = getattr(self.probe.kernel, operation)(handle, *arguments)
            row.update(nativeResult=int(result), succeeded=bool(result),
                       lastError=None if result else getattr(ctypes, 'get_last_error', lambda: 0)())
            return bool(result)
        except Exception as exc:
            row.update(nativeResult=None, succeeded=False, failure=error_record(exc))
            raise
        finally:
            row['finishedMonotonic'] = self.budget.clock()
            row['remainingSeconds'] = max(0, self.budget.deadline - row['finishedMonotonic'])
            self.cleanup_outcomes.append(row)

    def terminate_owned(self):
        # The unassigned case is only this freshly created, still suspended handle.
        if self.assigned:
            require(self.cleanup_call('TerminateJobObject', self.job, 1), 'Owned diagnostic job termination failed')
        elif self.created:
            require(self.cleanup_call('TerminateProcess', self.process, 1), 'Owned suspended handle termination failed')

    def close(self):
        errors = []
        for name in ('thread', 'process', 'job'):
            handle = getattr(self, name)
            if handle:
                try:
                    if not self.cleanup_call('CloseHandle', handle): errors.append(name)
                except Exception:
                    errors.append(name)
                finally:
                    setattr(self, name, None)
        require(not errors, 'Owned handle close failed: ' + ','.join(errors))


def capture(probe, evidence, budget, controller, *, prepare_privacy=False, binding=None):
    handles = []
    primary = None
    try:
        evidence.write('30-observer-start', {**flags(), 'deadlineMonotonic': budget.deadline})
        identity = probe.identity()
        evidence.write('31-observer-host', identity)
        same_host(controller['host'], identity)
        bound, _ = legacy.bounded_object(evidence.path / '21-observer-bound.json')
        require(identity['processId'] == bound['processId']
                and identity['process']['createdFileTime'] == bound['createdFileTime'], 'Observer self/held identity mismatch')
        source = bound_source(budget, binding)
        event, digest = legacy.bounded_object(os.environ['GITHUB_EVENT_PATH'])
        context = validate_context(os.environ, event, source, identity, os.name, prepare_privacy=True, **({'binding': binding} if binding else {})) if prepare_privacy else validate_context(os.environ, event, source, identity, os.name)
        require(source['files'] == controller['sourceFiles'] and digest == controller['eventSha256'], 'Observer source/event changed')
        evidence.write('32-observer-context', {**context, 'source': source, 'eventSha256': digest})
        with physical_queries(probe, evidence, '36-native-dpi'):
            census, errors, enumeration_ok = probe.census()
            evidence.write('33-window-census', {**census, 'errors': errors, 'enumerationSucceeded': enumeration_ok})
            validate_census(census)
            census_complete = enumeration_ok and not errors and not census['truncated']
            # Preserve targeted blocker evidence even if the wider census is incomplete.
            # The final classifier still rejects that incomplete observation.
            taskbar = probe.taskbar()
            evidence.write('34-physical-hit', taskbar)
            target_hwnds = list(dict.fromkeys([census['foregroundHwnd'], taskbar['actualPointHwnd'],
                                             taskbar['actualRootHwnd'], taskbar['taskbarHwnd']]))
            targets = [probe.target(hwnd) for hwnd in target_hwnds]
            evidence.write('35-target-windows', {'targets': targets})
            census_foreground = next(row for row in census['windows'] if row['hwnd'] == census['foregroundHwnd'])
            foreground_target = next(row for row in targets if row['hwnd'] == census['foregroundHwnd'])
            # Classification uses this target snapshot, whose full metadata is rechecked
            # below. Project only the exact legacy schema; retain and reject census drift.
            foreground = {key: foreground_target[key] for key in
                          ('hwnd', 'processId', 'threadId', 'title', 'className', 'visible', 'enabled', 'rectangle')}
            require(foreground == census_foreground, 'Census-to-target foreground metadata raced')
        # Target owners first; no arbitrary slice can discard a positive foreground.
        pids = list(dict.fromkeys(row['processId'] for row in targets))
        require(len(pids) <= 8, 'Target process bound exceeded')
        processes = []
        for index, pid in enumerate(pids):
            budget.remaining()
            evidence.write(f'40-process-{index}-before', {'processId': pid, 'stage': 'before-open'})
            handle = probe.kernel.OpenProcess(0x1000, False, pid)
            require(handle, 'Target process denied/unavailable')
            handles.append((handle, pid))
            process = probe.process_identity(handle, pid)
            evidence.write(f'41-process-{index}-raw', process)
            require(process['sessionId'] == identity['sessionId'], 'Target owner session mismatch')
            process.update(image_receipt(process['imagePath'], budget))
            processes.append(process)
            evidence.write(f'42-process-{index}-image', process)
        evidence.write('43-signatures-before', {'paths': [p['imagePath'] for p in processes]})
        signed = signatures([p['imagePath'] for p in processes], budget)
        for process, signature in zip(processes, signed): process['signature'] = signature
        evidence.write('44-processes-complete', {'processes': processes})
        with physical_queries(probe, evidence, '62-screen-dpi'):
            evidence.write('60-screen-before', {'stage': 'before-capture'})
            from PIL import ImageGrab
            import io
            screen = ImageGrab.grab(all_screens=False)
            require(0 < screen.width <= 8192 and 0 < screen.height <= 8192 and screen.width * screen.height <= 20_000_000,
                    'Screenshot pixel bound exceeded')
            buffer = io.BytesIO(); screen.save(buffer, format='PNG'); data = buffer.getvalue()
            require(8 <= len(data) <= 8 * 1024 * 1024, 'Screenshot byte bound exceeded')
            with (evidence.path / 'foreground-desktop.png').open('xb') as stream: stream.write(data)
            evidence.write('61-screen-after', {'width': screen.width, 'height': screen.height,
                           'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        trees = []
        for index, hwnd in enumerate(dict.fromkeys([census['foregroundHwnd'], taskbar['actualRootHwnd']])):
            budget.remaining()
            evidence.write(f'50-uia-{index}-before', {'hwnd': hwnd, 'stage': 'before-COM'})
            tree = probe.strict_uia(hwnd)
            trees.append(tree)
            evidence.write(f'51-uia-{index}-after', tree)
            if 'error' in tree:
                raise diagnostic_error('UIA observation failed: ' + tree['error'].get('message', 'unavailable property'),
                                       uiaFailure=tree['error'])
            validate_diagnostic_uia(tree, hwnd)
            require(not tree['truncated'] and tree['nodes'], 'UIA unavailable/truncated')
            target = next(row for row in targets if row['hwnd'] == hwnd)
            require(all(node['processId'] == target['processId'] for node in tree['nodes']), 'UIA target ownership mismatch')
        observed = {'foreground': foreground,
                    'processes': processes, 'uia': trees}
        evidence.write('70-raw-observation', {**flags(), **observed})
        with physical_queries(probe, evidence, '72-recheck-dpi'):
            require(int(probe.user.GetForegroundWindow() or 0) == census['foregroundHwnd'], 'Foreground changed')
            refreshed_targets = [probe.target(hwnd) for hwnd in target_hwnds]
            refreshed_processes = [probe.process_identity(handle, pid) for handle, pid in handles]
            refreshed_hit = probe.taskbar()
            evidence.write('71-identity-recheck', {'targets': refreshed_targets, 'processes': refreshed_processes,
                                                 'physicalHit': refreshed_hit})
            require(refreshed_targets == targets, 'Target HWND/PID/TID/metadata raced')
            for before, after in zip(processes, refreshed_processes):
                require(all(before[key] == after[key] for key in after), 'Held process creation/session/image/native raced')
            require(refreshed_hit == taskbar, 'Taskbar point identity raced')
        same_host(identity, probe.identity())
        budget.remaining()
        result = classify(observed, identity['sessionId'], identity['windowsDirectory'], complete=census_complete, stable=True)
        evidence.write('80-classification', result)
        final_source = bound_source(budget, binding)
        evidence.write('81-source-recheck', final_source)
        require(final_source == source, 'Source changed during observation')
        return result
    except Exception as exc:
        primary = exc
        raise
    finally:
        cleanup = []; closed_count = 0
        for handle, pid in handles:
            try:
                require(probe.kernel.CloseHandle(handle), 'Target query handle close failed')
                closed_count += 1
            except Exception as exc:
                cleanup.append({'stage': 'process-handle', 'processId': pid, **error_record(exc)})
        try:
            evidence.write('85-observer-cleanup', {'errors': cleanup, 'queryHandlesClosed': closed_count,
                'pointerMoved': False, 'primaryFailure': error_record(primary) if primary else None})
        except Exception as exc:
            cleanup.append({'stage': 'cleanup-receipt', **error_record(exc)})
        if cleanup:
            if primary is not None:
                primary.cleanup_failures = getattr(primary, 'cleanup_failures', []) + cleanup
            else:
                failure = ValueError('Observer cleanup failed')
                failure.cleanup_failures = cleanup
                raise failure


def privacy_preparation_module():
    spec = importlib.util.spec_from_file_location('native31_privacy_preparation', ROOT / 'e2e/native31_privacy_prepare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observer(args, *, binding=None):
    budget = Budget(deadline=args.deadline)
    prepare_privacy = getattr(args, 'prepare_privacy', False)
    evidence = Evidence(args.output, max_files=PREPARE_MAX_FILES if prepare_privacy else MAX_FILES)
    try:
        budget.remaining()
        controller, _ = legacy.bounded_object(evidence.path / '10-controller.json')
        probe = Probe()
        classification = capture(probe, evidence, budget, controller, prepare_privacy=prepare_privacy, **({'binding': binding} if binding else {}))
        if prepare_privacy:
            privacy_preparation_module().PreparationSession(sys.modules[__name__], probe, evidence, budget, controller, classification,
                **({'source_receipt': lambda deadline: bound_source(deadline, binding)} if binding else {})).run()
        budget.remaining()
        return 0
    except Exception as exc:
        action_flags = flags(prepare_privacy=prepare_privacy)
        if prepare_privacy:
            try:
                action_flags = privacy_preparation_module().preparation_receipt(sys.modules[__name__], evidence)
            except Exception as receipt_error:
                action_flags.update(inputsPerformed=None, preparationReceiptFailure=error_record(receipt_error))
            action_flags['privacyPreparationQualified'] = False
        evidence.write('89-observer-failure', {**action_flags, 'failure': error_record(exc),
            'timedOut': isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)),
            'forced': isinstance(exc, subprocess.TimeoutExpired)})
        return 1


def child_environment(env):
    # An exact retained allowlist, excluding GitHub tokens and arbitrary Python startup options.
    names = ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'USERPROFILE',
             'APPDATA', 'LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'PSModulePath',
             'ImageOS', 'ImageVersion', 'GITHUB_ACTIONS', 'RUNNER_ENVIRONMENT', 'RUNNER_OS', 'RUNNER_ARCH',
             'RUNNER_TEMP', 'GITHUB_REPOSITORY', 'GITHUB_EVENT_NAME', 'GITHUB_EVENT_PATH', 'GITHUB_JOB',
             'GITHUB_REF', 'GITHUB_WORKFLOW_REF', 'GITHUB_SHA', 'GITHUB_WORKFLOW_SHA', 'GITHUB_RUN_ID',
             'GITHUB_RUN_ATTEMPT', 'GITHUB_ACTOR', 'GITHUB_ACTOR_ID', 'NATIVE31_PWSH')
    result = {name: env[name] for name in names if name in env}
    result.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    return result


def controller(args, *, binding=None):
    budget = Budget()  # The only deadline origin, before filesystem/native/source work.
    prepare_privacy = getattr(args, 'prepare_privacy', False)
    evidence = Evidence.create(args.output, os.environ['RUNNER_TEMP'], max_files=PREPARE_MAX_FILES if prepare_privacy else MAX_FILES)
    result = {**flags(prepare_privacy=prepare_privacy), 'success': False, 'forced': False, 'timedOut': False}
    evidence.write('00-start', {**result, 'deadlineMonotonic': budget.deadline, 'budgetSeconds': 120})
    try:
        require(os.name == 'nt', 'Actual Windows required')
        probe = Probe(); host = probe.identity()
        evidence.write('01-controller-host', host)
        source_files = bound_hashes(binding)
        event, event_digest = legacy.bounded_object(os.environ['GITHUB_EVENT_PATH'])
        context = validate_execution(os.environ, event, host, os.name, prepare_privacy=prepare_privacy, binding=binding)
        executable = image_receipt(sys.executable, budget)
        require(executable['peMachine'] == 0xAA64, 'Controller executable must be ARM64 PE')
        record = {**context, 'host': host, 'sourceFiles': source_files, 'executable': executable,
                  'eventSha256': event_digest, 'deadlineMonotonic': budget.deadline}
        evidence.write('10-controller', record)
        entry = unaliased(ROOT / binding.observer_entry) if binding else Path(__file__).resolve()
        require(entry.is_relative_to(ROOT) and entry.is_file(), 'Observer entry outside source checkout')
        argv = [sys.executable, '-B', str(entry), '--observer', '--deadline', str(budget.deadline),
                '--output', str(evidence.path)]
        if prepare_privacy: argv.append('--prepare-privacy')
        owned = OwnedObserver(probe, child_environment(os.environ), argv, budget,
                              {'sessionId': host['sessionId'], 'executable': executable, 'sourceFiles': source_files})
        result = run_owned(owned, budget, evidence, prepare_privacy=prepare_privacy)
        child_failure = evidence.path / '89-observer-failure.json'
        if child_failure.exists():
            failure, _ = legacy.bounded_object(child_failure)
            result['observerFailure'] = failure
            result['success'] = False
            result['timedOut'] = result['timedOut'] or failure.get('timedOut', False)
            result['forced'] = result['forced'] or failure.get('forced', False)
        if result['success']:
            child_context, _ = legacy.bounded_object(evidence.path / '32-observer-context.json')
            result['context'] = validate_context(os.environ, event, child_context['source'], host, os.name, prepare_privacy=prepare_privacy, binding=binding)
            require(bound_hashes(binding) == source_files, 'Controller source files changed')
            classification, _ = legacy.bounded_object(evidence.path / '80-classification.json')
            require(classification.get('status') in ('privacy-match', 'privacy-absent-observed')
                    and all(classification.get(k) == v for k, v in flags().items()), 'Invalid child result flags')
            result['status'] = classification['status']
        budget.remaining()
    except Exception as exc:
        result['success'] = False
        result['failure'] = error_record(exc)
        result['timedOut'] = result['timedOut'] or isinstance(exc, TimeoutError)
    finally:
        if prepare_privacy:
            try:
                privacy_preparation_module().finalize_preparation(sys.modules[__name__], evidence, result)
            except Exception as exc:
                result['success'] = False
                result['privacyPreparationQualified'] = False
                result['preparationReceiptFailure'] = error_record(exc)
                result['inputsPerformed'] = None
        result['remainingSeconds'] = max(0, budget.deadline - time.monotonic())
        evidence.write('99-result', result)
    return 0 if result['success'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--observer', action='store_true')
    parser.add_argument('--prepare-privacy', action='store_true', help='Explicit separately bound privacy-only close and physical taskbar control')
    parser.add_argument('--deadline', type=float)
    args = parser.parse_args()
    require(args.observer == (args.deadline is not None), 'Observer/deadline arguments must be paired')
    return observer(args) if args.observer else controller(args)


if __name__ == '__main__':
    raise SystemExit(main())
