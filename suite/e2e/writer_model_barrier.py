"""Strict read-only Writer completion policy for the acceptance harness.

This synchronizes a new harness. It neither repairs text nor establishes the
cause of earlier physical input loss. Portable replay performs no filesystem,
Windows API, UNO, focus, input or model mutation operations.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
import re
import traceback

from writer_style_smoke import validate_python_observation


OPERATIONS = ['resolve-existing-owned-frame', 'Text.getString', 'isModified', 'verify-retained-generation']
MAX_READS = 120
MAX_SECONDS = 12.0
MAX_BODY_BYTES = 1024 * 1024
BINDING_KEYS = {'shellPid','shellCreationTime','officePid','officeCreationTime','expectedImage',
    'suiteHwnd','parentHwnd','childHwnd','rootHwnd','privatePipe','frameIdentity',
    'controllerIdentity','modelIdentity','documentUrl'}


def _path(value):
    assert isinstance(value, str) and value, 'An absolute owned path is required'
    path = PureWindowsPath(value)
    if not path.is_absolute(): path = PurePosixPath(value)
    assert path.is_absolute() and '..' not in path.parts, 'Owned path is relative or escaped'
    return path


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _time(value):
    assert type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Invalid monotonic time'
    return float(value)


def _text(value):
    assert isinstance(value, str) and len(value.encode('utf-8')) <= MAX_BODY_BYTES, 'Invalid bounded Writer body'
    return value.replace('\r\n', '\n').replace('\r', '\n')


def require_python_identity(identity, suite_root, inventory, inventory_sha256):
    """Recompute all seven roles from explicit trusted inventory, without I/O."""
    root = _path(str(suite_root))
    assert isinstance(inventory_sha256, str) and re.fullmatch('[a-f0-9]{64}', inventory_sha256)
    assert isinstance(identity, dict) and type(identity.get('schemaVersion')) is int and identity['schemaVersion'] == 1 and identity.get('verified') is True
    assert _path(identity['suiteRoot']) == root and identity['inventorySha256'] == inventory_sha256
    paths = validate_python_observation(str(root), identity['observed'], inventory)
    assert isinstance(identity.get('files'), dict) and set(identity['files']) == set(paths), 'Incomplete seven-role Python identity'
    for role, relative in paths.items():
        actual, expected = identity['files'][role], inventory['files'].get(relative)
        assert isinstance(expected, dict) and set(expected) == {'size','sha256'}
        assert type(expected['size']) is int and expected['size'] > 0
        assert isinstance(expected['sha256'], str) and re.fullmatch('[a-f0-9]{64}', expected['sha256'])
        assert isinstance(actual, dict) and set(actual) == {'path','relativePath','size','sha256'}
        assert _path(actual['path']) == root / relative and actual['relativePath'] == relative
        assert type(actual['size']) is int and actual['size'] == expected['size'] and actual['sha256'] == expected['sha256'], 'Python role differs from trusted inventory'
    return paths


def _binding(binding, suite_root):
    assert isinstance(binding, dict) and set(binding) == BINDING_KEYS, 'Incomplete owned frame binding'
    for key in ('shellPid','officePid','suiteHwnd','parentHwnd','childHwnd','rootHwnd','shellCreationTime','officeCreationTime'):
        assert type(binding[key]) is int and binding[key] > 0, 'Invalid owned native identity: ' + key
    assert binding['shellPid'] != binding['officePid'] and binding['suiteHwnd'] == binding['rootHwnd']
    assert _path(binding['expectedImage']) == _path(str(suite_root)) / 'Office/program/soffice.bin'
    assert isinstance(binding['privatePipe'], str) and re.fullmatch('OpenGeul_[a-f0-9]{32}', binding['privatePipe'])
    for key in ('frameIdentity','controllerIdentity','modelIdentity'):
        assert isinstance(binding[key], str) and 0 < len(binding[key]) <= 4096, 'Missing retained UNO object identity'
    assert isinstance(binding['documentUrl'], str) and len(binding['documentUrl']) <= 32768
    return binding


def require_original_shell(raw, binding, suite_root):
    """Replay the actual launched Popen HANDLE, not a later numeric PID lookup."""
    assert isinstance(raw,dict) and raw.get('kind')=='retained-suite-popen-process'
    assert type(raw.get('pid')) is int and raw['pid']==binding['shellPid']
    assert type(raw.get('handleValue')) is int and raw['handleValue']>0
    assert _path(raw['nativeImage'])==_path(str(suite_root))/'OpenGeul.Office.exe'
    assert type(raw['nativeImageLength']) is int and raw['nativeImageLength']==len(raw['nativeImage'].encode('utf-16-le'))//2
    created=raw['nativeCreation']
    assert all(type(created[key]) is int for key in ('low','high','fileTime'))
    assert 0<=created['low']<=0xffffffff and 0<=created['high']<=0xffffffff
    assert (created['high']<<32)|created['low']==created['fileTime']==binding['shellCreationTime']>0, 'Reader did not bind the original launched Suite generation'
    assert type(raw.get('waitResult')) is int and raw['waitResult']==258
    assert type(raw.get('exitCode')) is int and raw['exitCode']==259
    return raw


@dataclass(frozen=True)
class Expectation:
    suite_root: str
    baseline_body: str
    completed_markers: tuple
    next_marker: str
    prior_body: str
    expected_body: str
    started_at: float
    deadline: float
    binding_json: str
    before_input_json: str
    inventory_json: str
    inventory_sha256: str
    original_shell_json: str

    @property
    def binding(self): return json.loads(self.binding_json)

    @property
    def inventory(self): return json.loads(self.inventory_json)

    def receipt(self):
        return dict(schemaVersion=1, suiteRoot=self.suite_root, baselineBody=self.baseline_body,
            completedMarkers=list(self.completed_markers), nextMarker=self.next_marker,
            priorBody=self.prior_body, expectedBody=self.expected_body, startedAt=self.started_at,
            deadline=self.deadline, binding=self.binding, beforeInput=json.loads(self.before_input_json),
            inventorySha256=self.inventory_sha256,originalShell=json.loads(self.original_shell_json))


def freeze_expectation(binding, baseline_body, completed_markers, next_marker, before_input,
                       *, suite_root, original_shell, inventory, inventory_sha256, started_at, timeout_seconds=MAX_SECONDS):
    start = _time(started_at)
    assert type(timeout_seconds) in (float, int) and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= MAX_SECONDS, 'Invalid bounded completion budget'
    baseline = _text(baseline_body)
    assert isinstance(completed_markers, (list, tuple))
    markers = tuple(completed_markers)
    assert all(isinstance(marker,str) and 0 < len(marker) <= 256 and marker.isascii() for marker in (*markers,next_marker)), 'Invalid exact physical markers'
    binding = _binding(copy.deepcopy(binding), suite_root)
    require_original_shell(original_shell,binding,suite_root)
    prior = baseline + ''.join(markers); expected = prior + next_marker
    plan = Expectation(str(_path(str(suite_root))),baseline,markers,next_marker,prior,expected,start,
        start+timeout_seconds,_json(binding),_json(before_input),_json(inventory),inventory_sha256,_json(original_shell))
    assert _text(before_input['bodyText']) == prior, 'Before-input model differs from independently frozen prior body'
    assert validate_observation(plan,before_input,prior) == 'pending'
    return plan


def validate_observation(plan, observation, previous_body):
    """Pure: validate exact ownership/Python/time/body; accept only append prefixes."""
    assert isinstance(plan, Expectation) and isinstance(observation, dict)
    assert observation.get('kind') == 'existing-owned-writer-body'
    binding = plan.binding
    assert observation.get('bindingBefore') == binding and observation.get('bindingAfter') == binding, 'Owned Writer binding or generation changed'
    assert observation.get('retainedProcessHandle') is True and observation.get('handleSignaled') is False
    assert all(observation.get(key) is True for key in ('readOnlyObservation','sameFrameControllerModelVerified','readCallCleanupSucceeded','readerStillRetained'))
    assert observation.get('operations') == OPERATIONS, 'Reader performed unsupported operations'
    begin,end = _time(observation.get('readStartedAt')),_time(observation.get('readFinishedAt'))
    assert plan.started_at <= begin <= end <= plan.deadline, 'Reader exceeded the original absolute budget'
    require_python_identity(observation.get('pythonIdentity'),plan.suite_root,plan.inventory,plan.inventory_sha256)
    # The backend owns raw typed native/UNO evidence and its mandatory portable replay.
    from writer_model_reader import require_owned_observation
    require_owned_observation(observation,binding,plan.suite_root)
    frozen = json.loads(plan.before_input_json)
    assert observation['helperLaunch']==frozen['helperLaunch'], 'Actual owned observer launch receipt changed between reads'
    for origin in ('controller','helper'):
        anchor = frozen['nativeSnapshots'][origin+'Before']
        for suffix in ('Before','After'):
            current = observation['nativeSnapshots'][origin+suffix]
            assert all(current[name]['handleValue']==anchor[name]['handleValue'] for name in ('shell','office')), 'Original retained process HANDLE was replaced between reads'
            assert current['officeCommandLine']==anchor['officeCommandLine'] and current['profileUrl']==anchor['profileUrl'], 'Original Office transport/profile changed between reads'
    for key in ('pid','creationTime','handleValue','jobHandleValue'):
        assert observation['readerProcess'][key]==frozen['readerProcess'][key], 'Original observer process generation, HANDLE or job changed'
    assert _path(observation['readerProcess']['image'])==_path(frozen['readerProcess']['image'])
    assert _path(observation['readerProcess']['image'])==_path(observation['pythonIdentity']['observed']['processImage']), 'Python receipt describes another reader image'
    prior, expected = plan.prior_body, plan.expected_body
    previous, body = _text(previous_body), _text(observation.get('bodyText'))
    assert previous.startswith(prior) and expected.startswith(previous), 'Invalid prior accepted append prefix'
    assert body.startswith(prior) and expected.startswith(body), 'Writer body changed baseline, dropped, duplicated or reordered input'
    assert len(body) >= len(previous), 'Writer append prefix regressed'
    return 'complete' if body == expected else 'pending'


def await_completion(plan, reader, *, clock, pause, record, max_reads=MAX_READS):
    """Observe one immutable deadline. Never type, repair or retry a failed plan."""
    assert isinstance(record, dict)
    assert 'state' not in record and 'error' not in record, 'A completed or failed receipt cannot be reused'
    assert type(max_reads) is int and 0 < max_reads <= MAX_READS
    record.update(schemaVersion=1,kind='writer-model-completion',success=False,state='pending',
        expectation=plan.receipt(),deadline=plan.deadline,observations=[],
        originalPhysicalAsciiLossCauseEstablished=False,productFixEstablished=False)
    previous = plan.prior_body
    try:
        for _ in range(max_reads):
            begin = _time(clock())
            assert begin < plan.deadline, 'Writer model completion deadline expired'
            row = {'startedAt':begin}; record['observations'].append(row)
            try:
                observation = reader(plan.deadline)
                row['observation'] = copy.deepcopy(observation)
            except BaseException as exc:
                row['error'] = type(exc).__name__ + ': ' + str(exc)
                raise
            finally:
                row['finishedAt'] = _time(clock())
            assert begin <= row['finishedAt'] <= plan.deadline, 'Reader returned after the original absolute deadline'
            assert begin <= _time(observation['readStartedAt']) <= _time(observation['readFinishedAt']) <= row['finishedAt'], 'Raw read is outside its recorded call interval'
            state = validate_observation(plan,observation,previous); row['decision']=state
            previous = _text(observation['bodyText'])
            if state == 'complete':
                record.update(success=True,state='model-complete',modelEqualityAt=row['finishedAt'])
                return observation
            remaining = plan.deadline - _time(clock())
            assert remaining > 0, 'Writer model completion deadline expired'
            pause(min(0.1,remaining))
        raise AssertionError('Writer model pending-read limit exceeded')
    except BaseException as exc:
        record.update(success=False,state='failed',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
        raise


def finalize_completion(plan, record, cleanup, finished_at):
    """A model equality is insufficient until the owned observer is released."""
    assert record.get('state') == 'model-complete' and record.get('success') is True
    try:
        from writer_model_reader import require_reader_cleanup
        require_reader_cleanup(cleanup,plan.binding,plan.deadline)
        finished = _time(finished_at)
        assert _time(record['modelEqualityAt']) <= _time(cleanup['startedAt']) <= _time(cleanup['finishedAt']) <= finished <= plan.deadline, 'Reader cleanup is not after equality and within the original absolute budget'
        frozen=json.loads(plan.before_input_json)
        assert cleanup['helperLaunch']==frozen['helperLaunch'], 'Cleanup describes another actual observer launch'
        reader=frozen['readerProcess']
        members=[row for row in cleanup['readerMembers'] if row['pid']==reader['pid']]
        assert len(members)==1 and cleanup['releaseAcknowledgement']['readerPid']==reader['pid'], 'Cleanup released another observer process'
        member=members[0]
        assert all(member[key]==reader[key] for key in ('creationTime','handleValue','jobHandleValue')), 'Cleanup describes another observer generation, HANDLE or job'
        assert _path(member['image'])==_path(reader['image']) and cleanup['jobHandleValue']==reader['jobHandleValue']
        anchor=frozen['nativeSnapshots']['controllerBefore']
        for key in ('nativeBefore','nativeAfter'):
            raw=cleanup[key]
            assert all(raw[name]['handleValue']==anchor[name]['handleValue'] for name in ('shell','office')), 'Cleanup closed different retained controller handles'
            assert raw['officeCommandLine']==anchor['officeCommandLine'] and raw['profileUrl']==anchor['profileUrl'], 'Cleanup belongs to another Office transport/profile'
        record.update(cleanup=copy.deepcopy(cleanup),finishedAt=finished,state='complete',success=True)
        return record
    except BaseException as exc:
        record.update(cleanup=copy.deepcopy(cleanup),state='failed',success=False,error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
        raise


def replay_completion(receipt, *, suite_root, inventory, inventory_sha256,
                      binding, baseline_body, completed_markers, next_marker):
    """Independently replay one final raw receipt against external expectations."""
    assert isinstance(receipt,dict) and type(receipt.get('schemaVersion')) is int and receipt['schemaVersion'] == 1
    assert receipt.get('kind') == 'writer-model-completion' and receipt.get('state') == 'complete' and receipt.get('success') is True
    assert receipt.get('originalPhysicalAsciiLossCauseEstablished') is False and receipt.get('productFixEstablished') is False
    raw = receipt['expectation']; start,deadline = _time(raw['startedAt']),_time(raw['deadline'])
    assert raw['binding'] == binding and raw['baselineBody'] == _text(baseline_body)
    plan = freeze_expectation(binding,baseline_body,completed_markers,next_marker,raw['beforeInput'],
        suite_root=suite_root,original_shell=raw['originalShell'],inventory=inventory,inventory_sha256=inventory_sha256,
        started_at=start,timeout_seconds=deadline-start)
    assert raw == plan.receipt() and receipt['deadline'] == plan.deadline, 'Completion expectation or budget changed'
    rows = receipt['observations']; assert isinstance(rows,list) and 0 < len(rows) <= MAX_READS
    previous, last_time = plan.prior_body,_time(raw['beforeInput']['readFinishedAt'])
    for index,row in enumerate(rows):
        begin,end = _time(row['startedAt']),_time(row['finishedAt'])
        observation=row['observation']
        assert last_time <= begin <= _time(observation['readStartedAt']) <= _time(observation['readFinishedAt']) <= end <= plan.deadline
        decision=validate_observation(plan,observation,previous)
        assert row['decision']==decision and (decision=='complete') is (index==len(rows)-1), 'Completion was premature or observations continued after equality'
        previous,last_time=_text(observation['bodyText']),end
    assert receipt['modelEqualityAt']==last_time
    replayed=dict(state='model-complete',success=True,modelEqualityAt=last_time)
    finalize_completion(plan,replayed,receipt['cleanup'],receipt['finishedAt'])
    return dict(reads=len(rows),binding=copy.deepcopy(binding),expectedBody=plan.expected_body,
                startedAt=plan.started_at,finishedAt=receipt['finishedAt'],deadline=plan.deadline)


def replay_case_completions(record, *, suite_root, inventory, inventory_sha256,
                            baseline_body, expected_urls):
    """Portable whole-case replay; caller supplies independent body/URL anchors.

    expected_urls maps the source-derived edited (Suite HWND, child HWND) pairs to
    original file URL, or an explicit empty URL for a known blank factory frame.
    Callers separately join returned generations to verified native archives.
    """
    import lifecycle_smoke as lifecycle
    assert isinstance(record,dict) and isinstance(expected_urls,dict)
    markers=lifecycle.ASCII_EDITOR_MARKERS.get(record['case'],())
    completions=record.get('writerModelCompletions',[])
    readiness,typed=record.get('editorFocusReadinessRecords',[]),record.get('asciiEditorInputs',[])
    assert len(completions)==len(readiness)==len(typed)==len(markers), 'Missing or extra original edit completion evidence'
    assert [item['text'] for item in typed]==list(markers), 'Original physical marker order changed'
    if readiness: assert record['editorFocusReadiness']==readiness[-1]
    ledgers={}; frames={}; total_reads=0; previous_finished=0.0; original_shell=None
    for receipt,focus,inputs,marker in zip(completions,readiness,typed,markers):
        binding=receipt['expectation']['binding']; key=(binding['suiteHwnd'],binding['childHwnd'])
        matches=[a for a in record['attachments'] if (a['hwnd'],a['child'])==key]
        assert len(matches)==1 and key in expected_urls, 'Completion must bind one original case attachment'
        attachment=matches[0]
        assert binding['shellPid']==record['shellPid'] and binding['officePid']==attachment['officePid'] and binding['parentHwnd']==attachment['parent']
        assert binding['documentUrl']==expected_urls[key], 'Model URL differs from independent source-derived target'
        shell=receipt['expectation']['originalShell']
        if original_shell is None:original_shell=copy.deepcopy(shell)
        else:assert shell==original_shell, 'Original Popen shell HANDLE or generation changed between edits'
        assert (focus['suiteHwnd'],focus['childHwnd'])==key
        lifecycle.native.require_editor_focus_readiness(focus,key[0],key[1],record['shellPid'],attachment['officePid'])
        lifecycle.native.ascii_input.require_ascii_receipt(inputs,marker,*key)
        assert inputs['pauseSeconds']==0.025, 'Original lifecycle character pacing changed'
        if key in frames:
            # Reader/proxy representations may differ across new observation
            # helpers, but the original native frame/generation/URL cannot.
            native_keys=BINDING_KEYS-{'frameIdentity','controllerIdentity','modelIdentity'}
            assert all(binding[k]==frames[key][k] for k in native_keys), 'Owned frame generation changed between edits'
            native=receipt['expectation']['beforeInput']['nativeSnapshots']['controllerBefore']
            assert native['officeCommandLine']==frames[key]['officeCommandLine'] and native['profileUrl']==frames[key]['profileUrl'], 'Owned frame transport/profile changed between edits'
        else:
            frames[key]=copy.deepcopy(binding)
            native=receipt['expectation']['beforeInput']['nativeSnapshots']['controllerBefore']
            frames[key].update(officeCommandLine=copy.deepcopy(native['officeCommandLine']),profileUrl=native['profileUrl'])
        before=ledgers.setdefault(key,[])
        replayed=replay_completion(receipt,suite_root=suite_root,inventory=inventory,
            inventory_sha256=inventory_sha256,binding=binding,baseline_body=baseline_body,
            completed_markers=before,next_marker=marker)
        assert previous_finished<=replayed['startedAt'], 'Original edit completion intervals overlap or are reordered'
        previous_finished=replayed['finishedAt']
        total_reads+=replayed['reads'];before.append(marker)
    assert set(frames)==set(expected_urls), 'Source-derived edited attachment coverage differs'
    return dict(schemaVersion=1,kind='writer-model-case-replay',success=True,editCount=len(markers),
        readCount=total_reads,frameGenerations=list(frames.values()),
        originalPhysicalAsciiLossCauseEstablished=False,productFixEstablished=False)
