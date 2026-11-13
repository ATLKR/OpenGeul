"""Opt-in cleanup of a failed, private Calc launch, never a passing input test.

Only the UIA actor has a new private Job. Product launch/worker jobs are unchanged.
Terminating that actor bounds its lifetime, not a remote provider's queued action.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

MAX_JSON = 64 * 1024
MAX_SECONDS = 60
_RETAINED_ACTORS = []  # An unproved helper remains owned until its controller exits.
_RETAINED_PRODUCT_PROOFS = []
_BLOCK_LATER_LAUNCHES = False
SOURCE_FILES = ('e2e/calc_early_cleanup.py', 'e2e/calc_failure_actor.py',
    'e2e/generated_calc_close.py', 'e2e/lifecycle_smoke.py', 'e2e/windows_smoke.py',
    'e2e/native_window_evidence.py', 'e2e/ascii_editor_input.py', 'e2e/calc_model_barrier.py',
    'worker/native_windows.py', 'worker/session.py')


def require_launch_permitted():
    assert not _BLOCK_LATER_LAUNCHES, 'Earlier failure actor outcome is unknown; no later GUI case may launch'


def read_json(raw):
    assert isinstance(raw, bytes) and 0 < len(raw) <= MAX_JSON, 'Cleanup JSON size'
    def pairs(rows):
        out = {}
        for key, value in rows:
            assert key not in out, 'Duplicate cleanup JSON key'
            out[key] = value
        return out
    def finite(value):
        result = float(value)
        assert math.isfinite(result), 'Nonfinite cleanup JSON'
        return result
    def constant(value):
        raise ValueError('Nonfinite cleanup JSON: ' + value)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                       parse_float=finite, parse_constant=constant)
    assert isinstance(value, dict), 'Cleanup JSON object required'
    return value


def plain(path):
    path = Path(path)
    assert path.is_absolute() and '..' not in path.parts and not str(path).startswith(('\\\\', '//'))
    for part in (path, *path.parents):
        assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked cleanup path'
    return path


def write_original(path, value):
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    assert len(raw) <= MAX_JSON, 'Cleanup output exceeds bound'
    with plain(path).open('xb') as stream:
        stream.write(raw)
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def require_early(record, observer_never_started, observer):
    assert observer_never_started is True and observer is None, 'Model observer was not proved never started'
    assert record.get('success') is False and record.get('module') == 'calc'
    allowed = {'physical-uncommitted-calc-save': ('calc-active-cell-save', ('launch', 'focus-editor'), 'saveShortcutCount'),
               'physical-calc-uncommitted-close': ('calc-close-' + str(record.get('choice')), ('attach',), 'closeShortcutCount')}
    case, stages, count = allowed[record['kind']]
    assert record.get('case') == case and record.get('stage') in stages, 'Outside early launch boundary'
    if record['kind'] == 'physical-calc-uncommitted-close':
        assert record.get('choice') in ('save', 'discard', 'cancel')
    assert record.get('navigationKeys') == [] and record.get('commitKeys') == []
    assert type(record.get(count)) is int and record[count] == 0, 'Measured action attempted'
    assert not any(record.get(k) for k in ('physicalAsciiMarker', 'asciiEditorInputs', 'pendingInputTextVerified',
        'uncommittedBeforeSaveVerified', 'uncommittedBeforeCloseVerified', 'beforeCloseActions'))
    readiness = list(record.get('editorFocusReadinessRecords', []))
    if 'editorFocusReadiness' in record:
        readiness.append(record['editorFocusReadiness'])
    for row in readiness:
        assert isinstance(row, dict) and all(type(row.get(k)) is int and row[k] == 0
            for k in ('clickAttempts', 'controlF6Attempts')), 'Editor setup input attempted or unknown'


def await_actor(actor, action_deadline, recovery_deadline, *, clock=time.monotonic, sleep=time.sleep):
    result = dict(forced=False, timedOut=False, deathProved=False, fallbackAllowed=False, errors=[], samples=[])
    def sample():
        row = actor.snapshot()
        if len(result['samples']) < 8:
            result['samples'].append(row)
        result['final'] = row
        result['exitCode'] = row['exitCode']
        result['deathProved'] = row['waitResult'] == 0 and row['pids'] == []
        return result['deathProved']
    try:
        if getattr(actor,'launch',{}).get('launchError'):
            raise RuntimeError(actor.launch['launchError'])
        while clock() < action_deadline:
            if sample(): break
            sleep(min(.1, max(0, action_deadline - clock())))
        if not result['deathProved']:
            result['timedOut'] = True
    except BaseException as exc:
        result['errors'].append(type(exc).__name__ + ': ' + str(exc)[:1024])
    if not result['deathProved'] or result.get('exitCode') != 0:
        result['forced'] = True
        try:
            actor.terminate()
            result['terminateReturned'] = True
        except BaseException as exc:
            result['errors'].append(type(exc).__name__ + ': ' + str(exc)[:1024])
        while clock() < recovery_deadline and not result['deathProved']:
            try:
                if sample(): break
            except BaseException as exc:
                result['errors'].append(type(exc).__name__ + ': ' + str(exc)[:1024])
                break
            sleep(min(.1, max(0, recovery_deadline - clock())))
    result['fallbackAllowed'] = result['deathProved']
    if result['deathProved']:
        try:
            actor.close()
            result['handlesReleased'] = True
        except BaseException as exc:
            result['errors'].append(type(exc).__name__ + ': ' + str(exc)[:1024])
            result['handlesReleased'] = False
            _RETAINED_ACTORS.append(actor)
    else:
        _RETAINED_ACTORS.append(actor)
    return result


def invoke_outcome(actor, intent, final):
    normal = (actor.get('deathProved') is True and actor.get('forced') is False
        and actor.get('timedOut') is False and type(actor.get('exitCode')) is int and actor['exitCode'] == 0 and not actor.get('errors')
        and isinstance(intent, dict) and intent.get('invokeIntent') is True
        and type(intent.get('invokeAttempts')) is int and intent['invokeAttempts'] == 1
        and isinstance(final, dict) and final.get('success') is True
        and final.get('invokeReturned') is True and type(final.get('invokeAttempts')) is int
        and final['invokeAttempts'] == 1)
    return dict(normal=normal, invokeIntentRetained=isinstance(intent, dict) and intent.get('invokeIntent') is True,
        invocationsPerformed=1 if normal else None,
        remoteProviderCancellationProved=False,
        basis='Original successful return' if normal else 'Unknown: intent/actor death cannot revoke or establish provider execution')


def validate_actor_receipts(receipts, request):
    assert set(receipts) == {'10-bound.json','20-prompt.json','30-invoke-intent.json','99-result.json'}, 'Incomplete actor originals'
    bound, prompt, intent, final = (receipts[k] for k in ('10-bound.json','20-prompt.json','30-invoke-intent.json','99-result.json'))
    for key in ('shellCreation','engineCreation'):
        assert type(bound.get(key)) is int and bound[key] == request[key], 'Actor bound a different generation'
    for key in ('shellHandleValue','engineHandleValue'):
        assert type(bound.get(key)) is int and bound[key] > 0
    discard = prompt.get('discard')
    assert isinstance(discard,dict) and intent.get('discard') == final.get('discard') == discard, 'Actor Discard identity changed'
    assert discard.get('shellPid') == request['shellPid'] and type(discard.get('shellPid')) is int
    for key in ('dialogHwnd','buttonHwnd','controlId'):
        assert type(discard.get(key)) is int and discard[key] > 0
    assert isinstance(discard.get('runtimeId'),list) and discard['runtimeId']
    observed = prompt.get('observation',{})
    assert observed.get('ready') is True and observed.get('dialogHwnd') == discard['dialogHwnd']
    assert observed.get('ownerHwnd') == request['hwnd'] and observed.get('shellPid') == request['shellPid']


def source_pins():
    root = Path(__file__).resolve().parents[1]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def verify_worker_archive(output, proof, evidence, deadline):
    """Join the original complete archive to the retained engine generation."""
    from native_cleanup_receipt import load_cleanup_receipt, validate_cleanup_receipt
    folders = list(plain(output / 'diagnostics').iterdir())
    assert len(folders) == 1 and re.fullmatch('[0-9a-f]{32}', folders[0].name), 'Ambiguous worker archive'
    folder = plain(folders[0])
    assert 0 < plain(folder/'manifest.json').stat().st_size <= MAX_JSON
    raw = (folder / 'manifest.json').read_bytes()
    manifest = read_json(raw)
    assert manifest.get('kind') == 'owned-office-native-diagnostics' and manifest.get('archiveComplete') is True
    rows = manifest['files']
    assert isinstance(rows, list) and 0 < len(rows) <= 128
    names = set()
    total = 0
    for row in rows:
        assert time.monotonic() < deadline, 'Worker archive deadline expired'
        name = row['path']
        assert isinstance(name, str) and name not in names and not any(c in name for c in ('\\',':','\0'))
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert name and Path(name).as_posix() == name and name != 'manifest.json', 'Noncanonical archive member'
        names.add(name)
        path = plain(folder / name)
        assert path.is_file() and type(row['bytes']) is int and 0 <= row['bytes'] <= 16 * 1024 * 1024
        total += row['bytes']
        assert total <= 16 * 1024 * 1024, 'Worker archive exceeds cleanup validation bound'
        assert path.stat().st_size == row['bytes']
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == row['sha256']
    actual = set()
    pending = [folder]
    entries = 0
    while pending:
        assert time.monotonic() < deadline, 'Worker archive tree deadline expired'
        for path in pending.pop().iterdir():
            entries += 1
            assert entries <= 256, 'Worker archive tree exceeds bound'
            path = plain(path)
            if path.is_dir():
                pending.append(path)
            else:
                assert path.is_file(), 'Nonregular archive entry'
                actual.add(path.relative_to(folder).as_posix())
    assert names | {'manifest.json'} <= actual <= names | {'manifest.json', 'events.jsonl'}, 'Unlisted product archive file'
    if 'events.jsonl' in actual - names:
        assert (folder/'events.jsonl').stat().st_size + total <= 16 * 1024 * 1024, 'Raw journal exceeds archive bound'
    assert 'shutdown.json' in names
    assert (folder/'shutdown.json').stat().st_size <= 256 * 1024
    shutdown_raw = (folder / 'shutdown.json').read_bytes()
    shutdown = load_cleanup_receipt(shutdown_raw)
    validate_cleanup_receipt(shutdown, expected_engine_image=str(proof.saved.suite / 'Office/program/soffice.bin'),
                             launcher_pid=manifest['launcherPid'])
    assert any(row['pid'] == proof.engine.pid and row['creationTime'] == proof.engine.creation
               for row in shutdown['initialMembers']), 'Archive engine differs from retained original'
    evidence['workerArchive'] = dict(path=str(folder), manifestSha256=hashlib.sha256(raw).hexdigest(),
        shutdownSha256=hashlib.sha256(shutdown_raw).hexdigest(), complete=True)


def legacy_recovery(process, record, proof, evidence, deadline):
    """Label the unchanged numeric-PID fallback honestly; no descendant proof."""
    import lifecycle_smoke as lifecycle
    import windows_smoke as native
    row = dict(kind='legacy-numeric-pid-tree-recovery', attempted=False, forced=None,
               descendantsDeathProved=False, productShutdownQualified=False)
    evidence['legacyRecovery'] = row
    if process.poll() is not None:
        row.update(shellExitCode=process.poll(), forced=False)
        return
    assert deadline - time.monotonic() >= 20, 'No reserved legacy recovery budget'
    assert lifecycle.process_identity(proof.shell.kernel, int(process._handle)) == (
        proof.saved.suite / 'OpenGeul.Office.exe', proof.shell.creation)
    assert proof.shell.live(), 'Original shell generation already exited'
    row.update(attempted=True, forceRequested=True, forced=None, numericPid=process.pid, maximumSeconds=20)
    native.stop_owned_test_process(process, record)
    row.update(shellExitCode=process.poll(), error=record.get('cleanupError'),
               timedOut='TimeoutExpired' in str(record.get('cleanupError', '')),
               outcome='Unqualified legacy recovery; exact descendant outcome unknown')


def run_early(api, process, record, proof, evidence):
    global _BLOCK_LATER_LAUNCHES
    from calc_failure_cleanup import _verify_attachment
    from generated_calc_close import verify_saved_calc_copy
    from calc_failure_actor import ActorProcess
    import lifecycle_smoke as lifecycle
    started = time.monotonic()
    deadline = started + MAX_SECONDS
    evidence.update(kind='owned-early-calc-failure-cleanup', deadlineSeconds=MAX_SECONDS,
                    modelObserverNeverStarted=True, productShutdownQualified=False, success=False)
    output = plain(Path(process.opengeul_evidence_output).resolve())
    folder = output / ('failure-cleanup-' + uuid.uuid4().hex)
    folder.mkdir(exist_ok=False)
    record['earlyCleanupOwnsFallback'] = True
    nonce = folder.name.removeprefix('failure-cleanup-')
    action_deadline = min(started + 20, deadline - 27)
    actor = None
    allow_fallback = True
    try:
        _verify_attachment(api, process, record, proof)
        assert not any(api.user.GetWindow(h, 4) == proof.hwnd for h in api.windows(process.pid)), 'Existing owned dialog before close'
        request = dict(schemaVersion=1, kind='failed-calc-discard-actor', nonce=nonce, case=proof.case,
            deadline=action_deadline, suite=str(proof.saved.suite), fixture=str(proof.saved.path),
            fixtureSha256=proof.saved.sha256, fixtureBytes=proof.saved.path.stat().st_size,
            shellPid=proof.shell.pid, shellCreation=proof.shell.creation,
            enginePid=proof.engine.pid, engineCreation=proof.engine.creation,
            hwnd=proof.hwnd, parent=proof.parent, child=proof.child,
            command=list(proof.command), record={k:record[k] for k in ('case','kind','module','success','stage','navigationKeys','commitKeys')},
            sourcePins=source_pins())
        for key in ('choice','saveShortcutCount','closeShortcutCount','editorFocusReadiness','editorFocusReadinessRecords'):
            if key in record: request['record'][key] = record[key]
        request_pin = write_original(folder / 'request.json', request)
        evidence.update(attempted=True, actorDirectory=str(folder), request=request_pin,
            shellCreationTime=proof.shell.creation, engineCreationTime=proof.engine.creation,
            shellHandleValue=int(proof.shell.handle), engineHandleValue=int(proof.engine.handle),
            documentCloseMessageCount=0, homeCloseMessageCount=0)
        _verify_attachment(api, process, record, proof)
        assert time.monotonic() < action_deadline, 'Document close action deadline expired'
        evidence['documentCloseIntent'] = dict(hwnd=proof.hwnd, shellPid=process.pid)
        evidence['documentCloseMessageCount'] = 1  # Attempt, including an API error.
        api.request_close(proof.hwnd, process.pid)
        assert time.monotonic() < action_deadline, 'Actor launch deadline expired'
        actor = ActorProcess([sys.executable, '-B', str(Path(__file__).with_name('calc_failure_actor.py')),
            '--request', str(folder / 'request.json'), '--sha256', request_pin['sha256'], '--nonce', nonce], folder)
        result = await_actor(actor, action_deadline, deadline - 22)
        result['launch'] = actor.launch
        evidence['actor'] = result
        allow_fallback = result['fallbackAllowed']
        receipts = {}
        allowed = {'request.json', '10-bound.json', '20-prompt.json', '30-invoke-intent.json', '99-result.json'}
        paths = list(folder.iterdir())
        assert len(paths) <= len(allowed), 'Too many actor outputs'
        for path in paths:
            assert path.name in allowed and path.is_file(), 'Unexpected actor output'
            if path.name == 'request.json': continue
            assert 0 < plain(path).stat().st_size <= MAX_JSON
            raw = path.read_bytes();value = read_json(raw)
            assert value.get('nonce') == nonce and value.get('case') == proof.case and value.get('requestSha256') == request_pin['sha256']
            receipts[path.name] = value
        outcome = invoke_outcome(result, receipts.get('30-invoke-intent.json'), receipts.get('99-result.json'))
        if outcome['normal']: validate_actor_receipts(receipts, request)
        evidence['invoke'] = outcome
        assert outcome['normal'], 'UIA actor failed/timed out; provider outcome unknown'
        while time.monotonic() < deadline - 22:
            if not proof.engine.live() and not api.user.IsWindow(proof.hwnd) and not api.user.IsWindow(proof.child): break
            time.sleep(.1)
        assert not proof.engine.live(), 'Original engine still alive'
        assert not api.user.IsWindow(proof.hwnd) and not api.user.IsWindow(proof.child), 'Original windows still live'
        # No foreground needed for this owned Home WM_CLOSE either.
        assert lifecycle.process_identity(proof.shell.kernel, int(process._handle)) == (
            proof.saved.suite / 'OpenGeul.Office.exe', proof.shell.creation)
        home = api.home(process)
        assert home, 'Owned Home not ready'
        assert api.home(process) == home, 'Owned Home identity changed'
        assert proof.shell.live() and process.poll() is None, 'Original shell is not live at Home close'
        assert lifecycle.process_identity(proof.shell.kernel, int(process._handle)) == (
            proof.saved.suite / 'OpenGeul.Office.exe', proof.shell.creation), 'Original shell generation changed'
        assert lifecycle.process_identity(proof.shell.kernel, proof.shell.handle) == (
            proof.saved.suite / 'OpenGeul.Office.exe', proof.shell.creation), 'Retained shell generation changed'
        assert time.monotonic() < deadline - 22, 'Normal cleanup action deadline expired'
        evidence['homeCloseIntent'] = dict(hwnd=home, shellPid=process.pid,
            originalShellCreation=proof.shell.creation, retainedHandleValue=int(proof.shell.handle),
            popenHandleValue=int(process._handle), originalShellLive=True, uniqueOwnedHome=True)
        evidence['homeCloseMessageCount'] = 1
        api.request_close(home, process.pid)
        assert time.monotonic() < deadline - 22, 'Normal cleanup deadline expired'
        process.wait(timeout=deadline - 22 - time.monotonic())
        assert process.poll() == 0 and not proof.shell.live(), 'Original shell not normally exited'
        verify_saved_calc_copy(proof.saved)
        verify_worker_archive(output, proof, evidence, deadline - 22)
        assert time.monotonic() < deadline - 22, 'Normal cleanup deadline expired'
        evidence.update(success=True, baselineBytesUnchanged=True, originalEngineExited=True, shellExitCode=0)
    except BaseException as exc:
        evidence['error'] = type(exc).__name__ + ': ' + str(exc)[:2048]
        if actor is not None and 'actor' not in evidence:
            result = await_actor(actor, time.monotonic(), deadline - 22)
            result['launch'] = actor.launch
            evidence['actor'] = result
            allow_fallback = result['fallbackAllowed']
        evidence.setdefault('invoke', dict(normal=False, invocationsPerformed=None, remoteProviderCancellationProved=False))
        if actor is not None and not evidence['invoke']['normal']:
            _BLOCK_LATER_LAUNCHES = True
        if allow_fallback:
            try: legacy_recovery(process, record, proof, evidence, deadline)
            except BaseException as later: evidence['recoveryError'] = type(later).__name__ + ': ' + str(later)[:2048]
        else:
            _RETAINED_PRODUCT_PROOFS.append(proof)
            evidence['recoveryError'] = 'Actor death not proved; no fallback or later GUI action permitted'
    finally:
        evidence['elapsedSeconds'] = time.monotonic() - started
        record['success'] = False
        evidence['parentReceiptPath'] = str(folder / 'parent-result.json')
