"""Independent, numeric managed-state observations from an already framed read.

No IO, native query, focus decision or counter mutation belongs here. A known row
is one sampled managed comparison, never an event interval or focus acceptance.
"""
import json
import re

from initial_focus_final_counters import IDENTITY_KEYS, parse_initial_focus_final_counters

_STATUS = b'{"event":"suite.initialEditorFocusStatus","component":"host",'
_COUNTER = b'{"event":"suite.initialEditorFocusFlow","component":"host",'
_OBSERVE = _COUNTER + b'"stage":"observe",'
_DETAILS = set('schemaVersion ownerGeneration prefixSnapshotRevision originalFormHwnd '
    'originalPanelHwnd originalChildHwnd activeFormIsThis'.split())
_ENVELOPE = set('event component stage sequence utc processId managedThreadId '
    'workerProcessId traceId details'.split())


def initial_focus_status_unknown(code, original=None):
    value = dict(schemaVersion=1, attempted=True, known=False, acceptanceEligible=False,
        eventCompletenessUnknown=True, errorCode=code, gapObserved=False, gapCount=0,
        scope={}, rows=[])
    if type(original) is dict and original.get('captureModeCode') == 2:
        value.update(captureModeCode=2, historicalIdentityOnly=True,
            retirementConfirmed=original.get('retirementConfirmed') is True)
    return value


def parse_initial_focus_status(lines, *, original, trace, worker, managed, budget):
    """Use only this read's original rich identity and validated prefix snapshots.

    Unknown:1 missing,2 shape/bounds,3 identity,4 ordering/prefix join,5 budget.
    Counter wire/identity/arithmetic are validated by the unchanged original
    closed parser; its incomplete interval is not used to infer absent events.
    """
    code = 2

    def integer(value, maximum, minimum=0):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError()
        return value

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError()

    def envelope(line, event):
        nonlocal code
        code = 2
        assert line.isascii()
        value = json.loads(line.decode('ascii'), object_pairs_hook=unique,
            parse_constant=invalid_constant)
        assert type(value) is dict and set(value) == _ENVELOPE
        assert value['event'] == event and value['component'] == 'host'
        assert type(value['utc']) is str and re.fullmatch(
            r'\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)', value['utc'])
        integer(value['sequence'], 128, 1)
        code = 3
        assert integer(value['processId'], 0xffffffff, 1) == identity['shellPid']
        assert integer(value['managedThreadId'], 0x7fffffff, 1) == managed
        assert integer(value['workerProcessId'], 0x7fffffff, 1) == worker
        assert type(value['traceId']) is str and value['traceId'] == trace
        return value

    try:
        budget()
        assert type(lines) in (list, tuple) and len(lines) <= 8192
        assert all(type(line) is bytes and len(line) <= 64*1024 and line.endswith(b'\n') for line in lines)
        assert sum(map(len, lines)) <= 2*1024*1024
        code = 3
        assert type(original) is dict and original.get('known') is True
        assert type(managed) is int and 1 <= managed <= 0x7fffffff
        assert type(worker) is int and 1 <= worker <= 0x7fffffff
        assert type(trace) is str and re.fullmatch('[0-9a-f]{32}', trace)
        scope = original['scope']
        assert type(scope) is dict and set(scope) == set(IDENTITY_KEYS)-{'managedThreadId'} | {'moduleCode'}
        integer(scope['moduleCode'], 6, 1)
        identity = {key: scope[key] for key in IDENTITY_KEYS if key != 'managedThreadId'}
        identity['managedThreadId'] = managed
        for value in identity.values():
            integer(value, 2**63-1, 1)
        counter_rows = []; prefixes = {}; status_rows = []
        for position, line in enumerate(lines):
            budget()
            if line.startswith(_STATUS):
                value = envelope(line, 'suite.initialEditorFocusStatus')
                code = 2
                assert value['stage'] == 'status.completed'
                details = value['details']
                assert type(details) is dict and set(details) == _DETAILS
                for item in details.values():
                    integer(item, 2**63-1)
                assert details['schemaVersion'] == 1
                integer(details['ownerGeneration'], 128, 1)
                integer(details['prefixSnapshotRevision'], 65535, 1)
                integer(details['activeFormIsThis'], 1)
                code = 3
                for wire, key in (('originalFormHwnd', 'formHwnd'),
                        ('originalPanelHwnd', 'panelHwnd'), ('originalChildHwnd', 'childHwnd')):
                    assert details[wire] == identity[key]
                status_rows.append((position, value['sequence'], dict(details)))
                assert len(status_rows) <= 128
            elif line.startswith(_COUNTER) and not line.startswith(_OBSERVE):
                value = envelope(line, 'suite.initialEditorFocusFlow')
                code = 2
                assert value['stage'] in ('prefix', 'final')
                details = value['details']
                assert type(details) is dict and all(type(item) is int for item in details.values())
                assert 'sequence' not in details
                assert details.get('snapshotKindCode') == (1 if value['stage'] == 'prefix' else 2)
                row = dict(sequence=value['sequence'], **details)
                counter_rows.append(row)
                assert len(counter_rows) <= 128
                if value['stage'] == 'prefix':
                    key = (details.get('ownerGeneration'), details.get('snapshotRevision'))
                    code = 4
                    assert key not in prefixes
                    prefixes[key] = (position, row)
        if not status_rows:
            return initial_focus_status_unknown(1, original)
        budget(); code = 4
        validated = parse_initial_focus_final_counters(counter_rows, retained_identity=identity,
            retirement_confirmed=original.get('retirementConfirmed') is True)
        assert validated['errorCode'] in (0, 5, 6) and validated['latest']
        assert validated['scope'] == identity
        rows = []; sequence = 0; revision = 0; generation = None; gaps = 0
        for position, current, details in status_rows:
            budget(); code = 4
            assert current > sequence
            assert details['prefixSnapshotRevision'] > revision
            assert generation is None or details['ownerGeneration'] == generation
            key = (details['ownerGeneration'], details['prefixSnapshotRevision'])
            prefix_position, prefix = prefixes[key]
            assert prefix_position < position
            assert prefix['identityKnown'] == 1
            assert not any(prefix[name] for name in
                ('ownerChanged', 'retired', 'disposeReturned', 'updateFailed', 'overflowMask'))
            gaps += current - sequence - 1
            sequence = current; revision = details['prefixSnapshotRevision']; generation = details['ownerGeneration']
            rows.append(dict(sequence=current, **details))
        budget()
        value = dict(schemaVersion=1, attempted=True, known=True, acceptanceEligible=False,
            eventCompletenessUnknown=True, errorCode=0, gapObserved=gaps > 0,
            gapCount=gaps, scope=dict(scope), rows=rows)
        if original.get('captureModeCode') == 2:
            value.update(captureModeCode=2, historicalIdentityOnly=True,
                retirementConfirmed=original.get('retirementConfirmed') is True)
        return value
    except TimeoutError:
        return initial_focus_status_unknown(5, original)
    except Exception:
        return initial_focus_status_unknown(code, original)
