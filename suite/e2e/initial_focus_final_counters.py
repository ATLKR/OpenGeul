"""Pure numeric projection of already framed, identity-checked counter snapshots.

The caller owns raw framing, envelope/worker/trace identity, bounded collection and
actual retirement proof. This module performs no IO or native operations. It never
qualifies focus/menu acceptance or makes an absent marker mean non-execution.
"""

IDENTITY_KEYS = ('shellPid shellCreationTime officePid officeCreationTime formHwnd '
    'panelHwnd childHwnd shellThreadId editorThreadId managedThreadId').split()
COUNTER_KEYS = ('preOwnerActivated preOwnerAppActive preOwnerAppInactive activatedCount '
    'appActiveCount appInactiveCount queueEntryCount queueGuardCount coreQueueCount '
    'coreQueueTrueCount coreQueueFalseCount postAttemptCount postReturnCount '
    'callbackEntryCount callbackExitCount availabilityCount').split()
_WIRE_IDENTITY = dict(formHwnd='originalFormHwnd', panelHwnd='originalPanelHwnd',
    childHwnd='originalChildHwnd')
_FLAGS = ('identityKnown ownerChanged retired disposeReturned updateFailed pendingKnown pending '
    'availabilityKnown availabilityValue availabilityMaskKnown evaluationComplete '
    'postUncertain callbackOutstanding').split()
_KEYS = set(COUNTER_KEYS + _FLAGS + ['sequence', 'schemaVersion', 'snapshotKindCode', 'ownerGeneration', 'cap',
    'overflowMask', 'snapshotRevision', 'availabilitySourceCode', 'evaluatedMask', 'trueMask',
    'firstRejectId'] + [_WIRE_IDENTITY.get(key, key) for key in IDENTITY_KEYS])


def parse_initial_focus_final_counters(rows, *, retained_identity, retirement_confirmed):
    """Project <=128 numeric snapshot details+sequence rows from one existing read.

    Caller joins actual envelope stage prefix/final to snapshotKindCode1/2.
    A prefix preserves valid partial latest counts and never closes an interval.
    Only a recovered, retired, same-owner interval without counter/observer loss
    permits interpreting its zero counts. Old event stream completeness stays
    unknown. Error codes:1 missing,2 shape/bounds,3 identity,4 ordering,5 incomplete,
    6 overflow,7 arithmetic/masks. Invalid data exports no partial row.
    """
    result = dict(schemaVersion=2, known=0, counterIntervalComplete=0, zeroCountsUsable=0,
        acceptanceEligible=0, eventCompletenessUnknown=1, errorCode=1, scope={}, latest={})
    code = 2
    def integer(value, maximum, minimum=0):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError()
        return value
    try:
        if type(retirement_confirmed) is not bool or type(retained_identity) is not dict or set(retained_identity) != set(IDENTITY_KEYS):
            raise ValueError()
        identity = {key: integer(retained_identity[key], 2**63-1, 1) for key in IDENTITY_KEYS}
        if type(rows) not in (tuple, list) or len(rows) > 128:
            raise ValueError()
        if not rows:
            return result
        previous = None
        for row in rows:
            code = 2
            if type(row) is not dict or set(row) != _KEYS:
                raise ValueError()
            for key in _FLAGS:
                integer(row[key], 1)
            for key in COUNTER_KEYS + ['snapshotRevision']:
                integer(row[key], 65535, 1 if key == 'snapshotRevision' else 0)
            integer(row['sequence'], 128, 1); integer(row['ownerGeneration'], 128, 1)
            integer(row['overflowMask'], (1 << 17)-1)
            if integer(row['schemaVersion'], 2, 2) != 2 or integer(row['cap'], 65535, 65535) != 65535:
                raise ValueError()
            integer(row['availabilitySourceCode'], 5)
            kind = integer(row['snapshotKindCode'], 2, 1)
            if kind == 1 and (row['retired'] or row['disposeReturned']) or kind == 2 and row['retired'] != 1:
                raise ValueError()
            code = 3
            for key, value in identity.items():
                observed = integer(row[_WIRE_IDENTITY.get(key, key)], 2**63-1)
                if row['identityKnown'] and observed != value:
                    raise ValueError()
            if identity['shellPid'] == identity['officePid'] or identity['shellCreationTime'] > identity['officeCreationTime'] or len({identity[k] for k in ('formHwnd','panelHwnd','childHwnd')}) != 3:
                raise ValueError()
            code = 4
            if previous is not None:
                if row['sequence'] <= previous['sequence'] or row['snapshotRevision'] <= previous['snapshotRevision'] or row['ownerGeneration'] != previous['ownerGeneration'] or kind < previous['snapshotKindCode']:
                    raise ValueError()
                if any(row[key] < previous[key] for key in COUNTER_KEYS) or any(row[key] < previous[key] for key in ('retired','disposeReturned','ownerChanged','updateFailed','identityKnown')) or row['overflowMask'] | previous['overflowMask'] != row['overflowMask']:
                    raise ValueError()
                if previous['identityKnown'] and any(row[_WIRE_IDENTITY.get(key,key)] != previous[_WIRE_IDENTITY.get(key,key)] for key in IDENTITY_KEYS):
                    raise ValueError()
            code = 7
            if row['pending'] and not row['pendingKnown'] or row['availabilityValue'] and not row['availabilityKnown']:
                raise ValueError()
            mask = integer(row['evaluatedMask'], 16383)
            true = integer(row['trueMask'], 16383)
            first = integer(row['firstRejectId'], 14)
            if mask & (mask+1) or true & ~mask or first != ((mask ^ true) & -(mask ^ true)).bit_length():
                raise ValueError()
            if row['availabilityMaskKnown']:
                if not row['availabilityKnown'] or not row['evaluationComplete'] or mask != ((1 << first)-1 if first else 16383) or row['availabilityValue'] != int(first == 0):
                    raise ValueError()
            elif mask or true or first or row['evaluationComplete']:
                raise ValueError()
            if row['availabilityKnown'] != int(row['availabilityCount'] > 0):
                raise ValueError()
            if not row['overflowMask']:
                if row['queueGuardCount'] + row['coreQueueCount'] != row['queueEntryCount'] or row['coreQueueTrueCount'] + row['coreQueueFalseCount'] != row['coreQueueCount']:
                    raise ValueError()
                if row['postReturnCount'] != row['coreQueueTrueCount']:
                    raise ValueError()
                if not (row['callbackExitCount'] <= row['callbackEntryCount'] <= row['postAttemptCount'] <= row['coreQueueCount'] and row['postReturnCount'] <= row['postAttemptCount']):
                    raise ValueError()
                if row['postUncertain'] != int(row['postAttemptCount'] != row['postReturnCount']) or row['callbackOutstanding'] != int(row['postAttemptCount'] != row['callbackExitCount']):
                    raise ValueError()
            previous = row
        latest = dict(previous)
        complete = latest['snapshotKindCode'] == 2 and retirement_confirmed and all(latest[key] == 1 for key in ('identityKnown','retired','disposeReturned','pendingKnown','availabilityKnown','availabilityMaskKnown')) and not any(latest[key] for key in ('ownerChanged','updateFailed','overflowMask','postUncertain','callbackOutstanding'))
        result.update(known=int(complete), counterIntervalComplete=int(complete), zeroCountsUsable=int(complete),
            errorCode=0 if complete else 6 if latest['overflowMask'] else 5,
            scope=dict(identity), latest=latest)
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        result['errorCode'] = code
        return result
