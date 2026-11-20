"""Nonconsuming target-thread snapshots before the first ASCII arm.

GetQueueStatus changes low-word newness bookkeeping. This is neither an atomic
queue drain nor application dispatch, semantic input or callback retirement.
"""
from __future__ import annotations

import copy

QS_INPUT_MASK = 0x1c07
MAX_QUERIES = 8192


def retain_sample(ledger, row):
    ledger['pollCount'] += 1
    value = copy.deepcopy(row)
    if len(ledger['first']) < 16:
        ledger['first'].append(value)
    else:
        ledger['last'].append(value)
        del ledger['last'][:-48]


def require_initial_queue_sample(row, target, creation, *, request):
    assert type(row) is dict, 'Invalid initial ASCII queue snapshot'
    unsigned = ('request', 'requestAfter', 'ack', 'ackAfter', 'queueFlags', 'queueStatus',
                'keyboardSucceeded', 'keyboardError', 'callbackDepth', 'pid', 'tid')
    for key in unsigned:
        assert type(row[key]) is int and 0 <= row[key] <= 0xffffffff, 'Untyped initial queue snapshot: ' + key
    for key in ('hwnd', 'engineCreationTime', 'layout', 'tickStarted', 'tickFinished'):
        assert type(row[key]) is int and 0 < row[key] <= 0xffffffffffffffff, 'Invalid initial queue native identity/time: ' + key
    assert type(row['status']) is int and -(2**31) <= row['status'] < 2**31
    assert type(request) is int and 1 <= request <= MAX_QUERIES
    assert row['request'] == row['requestAfter'] == row['ack'] == row['ackAfter'] == request, 'Initial ASCII readiness ACK is stale or torn'
    assert all(row[key] == target[key] for key in ('pid', 'tid', 'hwnd', 'layout')), 'Initial ASCII queue target changed'
    assert type(creation) is int and creation > 0 and row['engineCreationTime'] == creation, 'Initial ASCII queue generation changed'
    assert row['queueFlags'] == QS_INPUT_MASK, 'Initial ASCII queue query mask changed'
    assert not (row['queueStatus'] >> 16) & ~QS_INPUT_MASK, 'Unknown initial queue current-status flags'
    assert row['tickStarted'] <= row['tickFinished'], 'Initial ASCII queue native clock regressed'
    keys = row['keyboardState']
    assert type(keys) is list and len(keys) == 256
    assert all(type(value) is int and 0 <= value <= 255 for value in keys), 'Invalid target keyboard byte snapshot'
    assert row['status'] == 0, 'Initial ASCII native readiness failed: ' + str(row['status'])
    assert row['keyboardSucceeded'] == 1 and row['keyboardError'] == 0, 'Initial target GetKeyboardState failed'
    assert 1 <= row['callbackDepth'] < 2**31, 'Invalid initial readiness callback depth'
    assert not keys[0x14] & 1 and not keys[0x91] & 1, 'Initial target CapsLock/ScrollLock policy changed'
    # Ignore low bits for non-toggle keys. NumLock's toggle bit is preserved,
    # not forcibly cleared; the existing parent native lock guard still runs.
    return not (row['queueStatus'] >> 16) & QS_INPUT_MASK and not any(value & 0x80 for value in keys) and row['callbackDepth'] == 1
