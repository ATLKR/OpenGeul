"""One opt-in, nonqualifying failure receipt; no process or document queries."""
import json
from pathlib import Path
import re

MAX_BYTES = 8192
OUTPUT = Path('paired-print-failure.numeric.json')
PROGRESS_KEYS = {'phaseCode', 'printerCallAttempted', 'printerCallReturned',
    'originalOracleAttempted', 'originalOracleReturned', 'rootIdentityKnown',
    'originalRootPid', 'originalRootCreationFileTime'}
FAILURE_KEYS = {'schemaVersion', 'completed', 'qualification', 'errorCode',
    'exceptionCode', 'stageCode', 'knownRole', 'fontCode', 'fileSizeKnown',
    'fileSize', 'linkCountKnown', 'linkCount', 'frames', 'unknownFrames',
    'truncated', 'censusObservation'}
KEYS = {'schemaVersion', 'kindCode', 'completed', 'qualification',
    'acceptanceEligible', 'sourceBindingKnown', 'sourceWords', 'harnessRunId',
    'harnessRunAttempt', 'roleCode', 'caseCode', 'progress', 'failure'}


def _check(condition):
    if not condition:
        raise ValueError('Invalid fixed numeric failure receipt')


def _int(value, low, high):
    _check(type(value) is int and low <= value <= high)


def _words(source):
    _check(type(source) is str and re.fullmatch('[0-9a-f]{40}', source) is not None)
    return [int(source[i:i+8], 16) for i in range(0, 40, 8)]


def _progress():
    return {'phaseCode': 0, 'printerCallAttempted': None,
        'printerCallReturned': None, 'originalOracleAttempted': None,
        'originalOracleReturned': None, 'rootIdentityKnown': False,
        'originalRootPid': 0, 'originalRootCreationFileTime': 0}


def _validate_census(value):
    if value is None:
        return
    keys = {'schemaVersion', 'diagnosticOnly', 'acceptanceEligible', 'rootPid',
        'originalRootCreationFileTime', 'sealed', 'requireLiveRoot', 'snapshotCount',
        'knownCount', 'guardUnexpectedCount', 'rootSnapshotReachableCount', 'rows'}
    _check(type(value) is dict and set(value) == keys)
    _check(type(value['schemaVersion']) is int and value['schemaVersion'] == 1)
    _check(value['diagnosticOnly'] is True and value['acceptanceEligible'] is False)
    for key in ('sealed', 'requireLiveRoot'):
        _check(type(value[key]) is bool)
    for key, low, high in (('rootPid', 1, 2**32-1), ('originalRootCreationFileTime', 1, 2**64-1),
            ('snapshotCount', 1, 10000), ('knownCount', 1, 65), ('guardUnexpectedCount', 1, 64),
            ('rootSnapshotReachableCount', 0, 64)):
        _int(value[key], low, high)
    _check(value['knownCount'] + value['guardUnexpectedCount'] <= 65)
    _check(value['rootSnapshotReachableCount'] <= value['guardUnexpectedCount'] <= value['snapshotCount'])
    rows = value['rows']
    _check(type(rows) is list and len(rows) == value['rootSnapshotReachableCount'])
    previous = 0
    for row in rows:
        _check(type(row) is dict and set(row) == {'pid', 'parentPid', 'executableRoleCode'})
        _int(row['pid'], previous + 1, 2**32-1)
        _int(row['parentPid'], 1, 2**32-1)
        _int(row['executableRoleCode'], 0, 3)
        _check(row['pid'] != value['rootPid'] and row['parentPid'] != row['pid'])
        previous = row['pid']


def _validate(value):
    _check(type(value) is dict and set(value) == KEYS)
    _check(type(value['schemaVersion']) is int and value['schemaVersion'] == 1)
    _check(type(value['kindCode']) is int and value['kindCode'] == 1)
    _check(value['completed'] is False and value['qualification'] is False and value['acceptanceEligible'] is False)
    _check(type(value['sourceBindingKnown']) is bool)
    _check(type(value['sourceWords']) is list and len(value['sourceWords']) == 5)
    for word in value['sourceWords']:
        _int(word, 0, 2**32-1)
    _int(value['harnessRunId'], 0, 2**63-1)
    _int(value['harnessRunAttempt'], 0, 2**31-1)
    if value['sourceBindingKnown']:
        _check(value['harnessRunId'] > 0 and value['harnessRunAttempt'] > 0)
    else:
        _check(value['sourceWords'] == [0] * 5 and value['harnessRunId'] == value['harnessRunAttempt'] == 0)
    _int(value['roleCode'], 0, 2)
    _int(value['caseCode'], 0, 6)
    _check((value['roleCode'] == value['caseCode'] == 0) or
           (value['roleCode'] in (1, 2) and value['caseCode'] in (1, 6)))
    p = value['progress']
    _check(type(p) is dict and set(p) == PROGRESS_KEYS)
    _int(p['phaseCode'], 0, 5)
    for key in ('printerCallAttempted', 'printerCallReturned', 'originalOracleAttempted', 'originalOracleReturned'):
        _check(p[key] is None or type(p[key]) is bool)
    _check(p['printerCallReturned'] is not True or p['printerCallAttempted'] is True)
    _check(p['originalOracleReturned'] is not True or p['originalOracleAttempted'] is True)
    _check(type(p['rootIdentityKnown']) is bool)
    _int(p['originalRootPid'], 0, 2**32-1)
    _int(p['originalRootCreationFileTime'], 0, 2**64-1)
    _check((p['originalRootPid'] > 0 and p['originalRootCreationFileTime'] > 0) if p['rootIdentityKnown'] else p['originalRootPid'] == p['originalRootCreationFileTime'] == 0)
    f = value['failure']
    _check(type(f) is dict and set(f) == FAILURE_KEYS)
    _check(type(f['schemaVersion']) is int and f['schemaVersion'] == 2 and f['completed'] is False and f['qualification'] is False)
    for key, high in (('errorCode', 33), ('exceptionCode', 11), ('stageCode', 8), ('knownRole', 2),
            ('fontCode', 2), ('fileSize', 512*1024*1024), ('linkCount', 65535), ('unknownFrames', 64)):
        _int(f[key], 0, high)
    for key in ('fileSizeKnown', 'linkCountKnown', 'truncated'):
        _check(type(f[key]) is bool)
    _check(type(f['frames']) is list and len(f['frames']) <= 12)
    for frame in f['frames']:
        _check(type(frame) is dict and set(frame) == {'fileCode', 'functionCode', 'line'})
        _int(frame['fileCode'], 1, 9)
        _int(frame['functionCode'], 1, 102)
        _int(frame['line'], 1, 20000)
    _validate_census(f['censusObservation'])
    if value['roleCode'] and f['knownRole']:
        _check(value['roleCode'] == f['knownRole'])
    if p['rootIdentityKnown'] and f['censusObservation'] is not None:
        c = f['censusObservation']
        _check((p['originalRootPid'], p['originalRootCreationFileTime']) == (c['rootPid'], c['originalRootCreationFileTime']))
    return value


def build_sidecar(error, projected):
    _check(isinstance(error, BaseException))
    fields = BaseException.__getattribute__(error, '__dict__')
    _check(type(projected) is dict and projected.get('kind') == 'paired-print-failure-numeric')
    value = {'schemaVersion': 1, 'kindCode': 1, 'completed': False,
        'qualification': False, 'acceptanceEligible': False,
        'sourceBindingKnown': False, 'sourceWords': [0] * 5,
        'harnessRunId': 0, 'harnessRunAttempt': 0, 'roleCode': 0,
        'caseCode': 0, 'progress': _progress(),
        'failure': {key: projected[key] for key in FAILURE_KEYS}}
    binding = fields.get('pairedFailureBinding')
    if type(binding) is tuple and len(binding) == 3:
        words = _words(binding[0])
        _int(binding[1], 1, 2**63-1)
        _int(binding[2], 1, 2**31-1)
        value.update(sourceBindingKnown=True, sourceWords=words,
                     harnessRunId=binding[1], harnessRunAttempt=binding[2])
    role, case = fields.get('pairedRole'), fields.get('pairedFailureCase')
    if type(role) is int and role in (1, 2) and type(case) is int and case in (1, 6):
        value['roleCode'] = role
        value['caseCode'] = case
    progress = fields.get('pairedFailureProgress')
    if type(progress) is dict and set(progress) == PROGRESS_KEYS:
        value['progress'] = {key: progress[key] for key in PROGRESS_KEYS}
    return _validate(value)


def encode_sidecar(value):
    _validate(value)
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    _check(len(data) <= MAX_BYTES)
    return data


def validate_sidecar(data, expected_source, expected_run, expected_attempt):
    _check(type(data) is bytes and 0 < len(data) <= MAX_BYTES and data.isascii())
    def pairs(items):
        result = {}
        for key, value in items:
            _check(key not in result)
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=pairs)
    _validate(value)
    # Producer writes this one exact canonical form; no opaque values or suffix.
    _check(encode_sidecar(value) == data)
    _check(value['sourceBindingKnown'] and value['sourceWords'] == _words(expected_source))
    _int(expected_run, 1, 2**63-1)
    _int(expected_attempt, 1, 2**31-1)
    _check((value['harnessRunId'], value['harnessRunAttempt']) == (expected_run, expected_attempt))
    return value


def write_sidecar(error, projected, *, path=OUTPUT):
    data = encode_sidecar(build_sidecar(error, projected))
    # Fixed caller-owned local output, exclusive creation, one <=8KiB write.
    with path.open('xb') as stream:
        stream.write(data)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--expected-run', type=int, required=True)
    parser.add_argument('--expected-attempt', type=int, required=True)
    args = parser.parse_args()
    try:
        # Reuse the existing exact local-file identity, no-alias and byte cap.
        from paired_print_windows import read_regular
        data, _ = read_regular(OUTPUT, MAX_BYTES)
        validate_sidecar(data, args.expected_source, args.expected_run, args.expected_attempt)
    except Exception:
        print('{"admitted":false,"qualification":false,"errorCode":1}')
        return 1
    print('{"admitted":true,"qualification":false,"errorCode":0}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
