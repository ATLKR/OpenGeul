"""Pure replay of the product worker's retained private-job shutdown proof."""
import json
import math
import ntpath


MAX_RECEIPT_BYTES = 256 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_cleanup_receipt(raw):
    """Read bounded, unambiguous JSON without changing the archived bytes."""
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_RECEIPT_BYTES,
             'Owned shutdown receipt is empty or exceeds its finite limit')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'Duplicate shutdown JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite shutdown JSON number: ' + value)
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid owned shutdown JSON') from exc
    _require(isinstance(result, dict), 'Owned shutdown JSON must be an object')
    return result


def _int(value, minimum=0, maximum=0xffffffffffffffff):
    return type(value) is int and minimum <= value <= maximum


def _time(value):
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
             'Invalid shutdown monotonic time')
    return value


def _image(value):
    _require(isinstance(value, str) and value and '\0' not in value
             and ntpath.isabs(value), 'Absolute native process image is required')
    return ntpath.normcase(ntpath.normpath(value))


def _members(rows, *, final):
    _require(isinstance(rows, list) and 0 < len(rows) <= 128,
             'Retained owned member observations are missing or unbounded')
    identities, pids, handles = set(), set(), set()
    for row in rows:
        _require(isinstance(row, dict) and not any('error' in key.lower() for key in row),
                 'Retained member contains a native observation error')
        _require(_int(row.get('pid'), 1, 0xffffffff)
                 and _int(row.get('creationTime'), 1) and _int(row.get('handleValue'), 1),
                 'Retained member PID/generation/HANDLE is missing')
        _require(type(row.get('alive')) is bool and _int(row.get('waitResult'))
                 and row['waitResult'] == (258 if row['alive'] else 0)
                 and row.get('getExitCodeProcessResult') is True
                 and _int(row.get('exitCode'), 0, 0xffffffff)
                 and row.get('exitCodeHex') == f"0x{row['exitCode']:08x}",
                 'Raw retained member wait/exit proof is invalid')
        _require(not final or (row['alive'] is False and row['exitCode'] == 0),
                 'Owned member remained alive or exited nonzero')
        identity = (row['pid'], row['creationTime'], row['handleValue'], _image(row.get('image')))
        _require(row['pid'] not in pids and row['handleValue'] not in handles,
                 'Duplicate retained member PID/HANDLE')
        pids.add(row['pid']); handles.add(row['handleValue']); identities.add(identity)
    return identities


def _final_census(group, job, started, finished):
    _require(isinstance(group, dict), 'Final raw private-job census is missing')
    for key, expected in (('schemaVersion', 1), ('informationClass', 3), ('jobHandleValue', job),
                          ('capacity', 128), ('maxAttempts', 3), ('bufferBytes', 1032),
                          ('headerBytes', 8), ('processIdBytes', 8)):
        _require(type(group.get(key)) is int and group[key] == expected,
                 'Final private-job census binding/layout differs: ' + key)
    _require(group.get('kind') == 'private-job-process-census'
             and group.get('api') == 'QueryInformationJobObject'
             and group.get('classification') == 'complete'
             and not any('error' in key.lower() for key in group),
             'Final private-job census is incomplete or failed')
    begin, end = _time(group.get('startedAt')), _time(group.get('finishedAt'))
    _require(started <= begin <= end <= finished, 'Final census is outside the graceful wait')
    calls = group.get('calls')
    _require(isinstance(calls, list) and 1 <= len(calls) <= 3, 'Final census raw calls are missing')
    previous = begin
    for attempt, row in enumerate(calls, 1):
        _require(isinstance(row, dict) and type(row.get('attempt')) is int and row['attempt'] == attempt
                 and row.get('result') is True and _int(row.get('lastError'), 0, 0xffffffff),
                 'Final census raw API call failed')
        _require(all(_int(row.get(key)) for key in ('assigned', 'count', 'returnLength'))
                 and 0 <= row['count'] <= row['assigned'] <= 128
                 and 8 + 8 * row['count'] <= row['returnLength'] <= 1032,
                 'Final census raw header is invalid')
        pids = row.get('pids')
        _require(isinstance(pids, list) and len(pids) == row['count']
                 and all(_int(pid, 1, 0xffffffff) for pid in pids) and len(set(pids)) == len(pids),
                 'Final census raw PID list is invalid')
        begin_call, end_call = _time(row.get('startedAt')), _time(row.get('finishedAt'))
        _require(previous <= begin_call <= end_call <= end, 'Final census call times differ')
        previous = end_call
        if attempt < len(calls):
            _require(row['count'] < row['assigned'] and row.get('classification') == 'incomplete',
                     'Final census retry lost its incomplete raw call')
        else:
            _require(row['assigned'] == row['count'] == 0 and pids == []
                     and row.get('classification') == 'complete', 'Final private job was not empty')


def validate_cleanup_receipt(proof, *, expected_engine_image, launcher_pid):
    """Require graceful, zero-exit death of the actual archived product job."""
    _require(isinstance(proof, dict) and type(proof.get('schemaVersion')) is int
             and proof['schemaVersion'] == 1 and proof.get('kind') == 'owned-office-job-cleanup',
             'Owned product shutdown receipt is missing')
    for key in ('success', 'gracefulQualified', 'jobEmptyVerified', 'deathProved', 'resourcesReleased'):
        _require(proof.get(key) is True, 'Owned product shutdown did not qualify: ' + key)
    for key in ('forcedTermination', 'profileRetained'):
        _require(proof.get(key) is False, 'Owned product shutdown retained/forced resources: ' + key)
    _require(proof.get('errors') == [] and isinstance(proof.get('errors'), list)
             and proof.get('finalJobPids') == [] and isinstance(proof.get('finalJobPids'), list),
             'Owned product shutdown has errors or remaining members')
    _require(_int(launcher_pid, 1, 0xffffffff) and type(proof.get('launcherPid')) is int
             and proof['launcherPid'] == launcher_pid and _int(proof.get('launcherHandleValue'), 1)
             and type(proof.get('launcherExitCode')) is int and proof['launcherExitCode'] == 0
             and type(proof.get('launcherWaitResult')) is int and proof['launcherWaitResult'] == 0,
             'Original archived launcher wait/zero-exit proof is missing')
    _require(_int(proof.get('jobHandleValue'), 1), 'Original private Office job HANDLE is missing')
    expected = _image(expected_engine_image)
    _require(expected.endswith('\\program\\soffice.bin') and _image(proof.get('expectedEngineImage')) == expected,
             'Shutdown engine image differs from the tested Suite')
    initial = _members(proof.get('initialMembers'), final=False)
    final = _members(proof.get('finalMembers'), final=True)
    _require(initial <= final and any(row['alive'] is True and _image(row['image']) == expected
                                     for row in proof['initialMembers']),
             'Owned engine/member generation, image or retained HANDLE changed')
    for key in ('gracefulBudgetSeconds', 'recoveryBudgetSeconds'):
        _require(type(proof.get(key)) is int and proof[key] == 5, 'Original shutdown budget differs')
    _require(proof.get('terminateRequested') is True and proof.get('terminateResult') is True,
             'Graceful desktop termination was not accepted')
    _require(not any(key.startswith(('forcedTerminationStarted', 'forcedTerminationFinished', 'recoveryWait'))
                     for key in proof), 'Successful shutdown contains forced recovery evidence')
    times = [_time(proof.get(key)) for key in ('terminateStartedAt', 'terminateFinishedAt',
                                               'gracefulWaitStartedAt', 'gracefulWaitFinishedAt')]
    _require(times == sorted(times), 'Graceful shutdown observation times differ')
    _require(_time(proof.get('elapsedSeconds')) >= times[-1] - times[0],
             'Shutdown elapsed time excludes the graceful wait')
    _final_census(proof.get('lastJobCensus'), proof['jobHandleValue'], times[2], times[3])
    return proof
