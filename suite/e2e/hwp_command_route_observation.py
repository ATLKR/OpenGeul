"""Closed, same-read route numbers. No IO, zero proof or input causation authority."""
from initial_focus_final_counters import IDENTITY_KEYS, parse_initial_focus_final_counters

_STAGES = ('received', 'enqueueReturned', 'execute')
_KEYS = set(('schemaVersion statusCode ownerGeneration cap attemptCap overflowMask '
    'updateFailureMask ownerMismatch coverageComplete eventCompletenessUnknown zeroCountsUsable '
    'acceptanceEligible').split()) | {stage + suffix for stage in _STAGES for suffix in ('Count', 'LastSequence')}


def hwp_command_route_unknown(code=1):
    return dict(schemaVersion=1, known=0, snapshotKnown=0, positiveRouteObserved=0,
        coverageComplete=0, zeroCountsUsable=0, eventCompletenessUnknown=1,
        acceptanceEligible=0, errorCode=code, scope={}, latest={})


def parse_hwp_command_route(rows, *, retained_identity, retirement_confirmed):
    """At most128 exact frames from the existing, retained prefix/final read.

    A positive result means only the original new:hwp pre-create branch was
    observed historically. It proves no HWP identity, launch result or gesture
    attribution. Last-sequence arrivals may reorder; callback may precede return.
    Missing/partial coverage can never establish non-execution.
    """
    result = hwp_command_route_unknown()
    code = 2
    def integer(value, maximum, minimum=0):
        if type(value) is not int or not minimum <= value <= maximum: raise ValueError()
        return value
    try:
        if type(rows) not in (list, tuple) or len(rows) > 128: raise ValueError()
        if not rows: return result
        if any(type(row) is not dict or set(row) != {'focus', 'route'} for row in rows): raise ValueError()
        # Reuse the unchanged focus parser's closed owner/generation/scope gates.
        original = parse_initial_focus_final_counters([row['focus'] for row in rows],
            retained_identity=retained_identity, retirement_confirmed=retirement_confirmed)
        code = 3
        if not original['latest'] or set(original['scope']) != set(IDENTITY_KEYS): raise ValueError()
        owner_generation = original['latest']['ownerGeneration']
        previous = None
        for row in rows:
            focus = row['focus']
            if focus['identityKnown'] != 1 or any(focus[key] for key in ('ownerChanged','updateFailed','overflowMask')):
                raise ValueError()
            if focus['snapshotKindCode'] == 2 and not (retirement_confirmed and focus['disposeReturned'] == 1):
                raise ValueError()
            value = row['route']; code = 2
            if type(value) is not dict or set(value) != _KEYS: raise ValueError()
            for key, expected in (('schemaVersion',1),('cap',65535),('attemptCap',16),
                    ('coverageComplete',0),('eventCompletenessUnknown',1),('zeroCountsUsable',0),('acceptanceEligible',0)):
                integer(value[key],expected,expected)
            integer(value['statusCode'],3,1); integer(value['ownerGeneration'],128,1)
            integer(value['overflowMask'],7); integer(value['updateFailureMask'],15); integer(value['ownerMismatch'],1)
            for stage in _STAGES:
                count = integer(value[stage+'Count'],65535)
                sequence = integer(value[stage+'LastSequence'],2**63-1)
                if (count == 0) != (sequence == 0): raise ValueError()
            code = 3
            if value['ownerGeneration'] != owner_generation or value['ownerGeneration'] != focus['ownerGeneration']:
                raise ValueError()
            code = 4
            if value['statusCode'] != 1 or any(value[key] for key in ('overflowMask','updateFailureMask','ownerMismatch')):
                raise ValueError()
            if any(value[stage+'Count'] > value['receivedCount'] for stage in _STAGES[1:]): raise ValueError()
            if previous is not None:
                for stage in _STAGES:
                    count, last = stage+'Count', stage+'LastSequence'
                    if value[count] < previous[count] or value[count] == previous[count] and value[last] != previous[last]:
                        raise ValueError()
            previous = value
        positive = all(previous[stage+'Count'] > 0 for stage in _STAGES) and len({previous[stage+'LastSequence'] for stage in _STAGES}) == 1
        result.update(snapshotKnown=1, positiveRouteObserved=int(positive), errorCode=0 if positive else 5,
            scope=dict(original['scope'],ownerGeneration=owner_generation), latest=dict(previous))
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        result['errorCode'] = code
        return result
