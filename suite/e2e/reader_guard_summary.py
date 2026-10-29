"""Closed diagnostics from an original reader guard; never sample native state.

Slots are context, presence mask, phase, observed, validated, pending, capture
relation, inventory/start/count/cleanup/finished flags, then seven signed
remaining-millisecond values and the Writer reader budget. Times are existing
controller clock reads, never new measurements. Cleanup flags are frozen before
the semantic context unwinds, including when all events share one clock tick.
"""
from __future__ import annotations

import math

_FROZEN = []
_BOUND = []
_ASSOCIATIONS = []  # One combined bound, including Writer freezes not yet bound.
_CORE = sum(1 << (i - 2) for i in (2, 3, 4, 5, 12, 13, 14))
_MAX_MASK = (1 << 18) - 1
_ROOT = __file__.replace('\\', '/').rsplit('/', 1)[0]
_BINDING = ('shellPid', 'shellCreationTime', 'officePid', 'officeCreationTime',
            'suiteHwnd', 'parentHwnd', 'childHwnd', 'rootHwnd')
_INV_KEYS = {'schemaVersion', 'kind', 'deadline', 'observationPresent',
             'validationReturned', 'ownedPositiveCapturePending', 'timeoutPhase',
             'firstCheckedAt', 'lastCheckedAt'}


def _need(value):
    if not value:
        raise ValueError('Unbound original reader guard')


def _time(value):
    _need(type(value) in (int, float) and math.isfinite(value) and value >= 0)
    return value


def _int(value, maximum=2**64 - 1):
    _need(type(value) is int and 0 < value <= maximum)
    return value


def _ms(deadline, at):
    value = math.floor(1000 * (deadline - _time(at)))
    _need(-(2**31) <= value < 2**31)
    return value


def _remember(container, entry):
    container.append(entry)
    if not any(existing is entry for existing in _ASSOCIATIONS):
        _ASSOCIATIONS.append(entry)
    while len(_ASSOCIATIONS) > 32:
        expired = _ASSOCIATIONS.pop(0)
        _FROZEN[:] = [item for item in _FROZEN if item is not expired]
        _BOUND[:] = [item for item in _BOUND if item is not expired]


def valid(value):
    """Pure decoder predicate; importing this module loads no producer code."""
    if (type(value) is not list or len(value) != 20
            or any(type(item) is not int for item in value)
            or value[0] not in (1, 2) or not 0 <= value[1] <= _MAX_MASK
            or value[1] & _CORE != _CORE):
        return False
    known = lambda i: bool(value[1] & (1 << (i - 2)))
    if any(not known(i) and value[i] != 0 for i in range(2, 20)):
        return False
    if (not 0 <= value[2] <= 5 or any(value[i] not in (0, 1)
            for i in (3, 4, 5, 7, 8, 10, 11))
            or not 0 <= value[6] <= 5 or not 0 <= value[9] <= 120
            or any(not -(2**31) <= value[i] < 2**31 for i in range(12, 19))
            or (known(19) and not 1 <= value[19] <= 12000)):
        return False
    phase, observed, validated, pending = value[2:6]
    if ((validated and not observed) or (pending and not validated)
            or (known(6) != bool(observed))
            or (phase == 0 and not (value[0] == 2 and observed and not validated and not pending))
            or (phase == 1 and observed and not (validated and pending))
            or (phase == 2 and not (observed and not validated and not pending))
            or (phase == 3 and not (observed and validated and not pending))
            or (phase == 4 and not (observed and validated and not pending and value[6] == 0))
            or (phase == 5 and not (observed and validated and pending))
            or (pending and value[6] == 0) or value[12] < value[13]
            or value[13] < value[14] or value[14] > 0
            or (phase == 0 and value[13] < 0)
            or (phase > 0 and (value[13] > 0 or value[13] != value[14]))
            or (known(15) and known(16) and value[15] < value[16])
            or (known(16) and value[16] < value[12])
            or (known(17) and known(18) and value[17] < value[18])):
        return False
    if value[0] == 1:
        return phase > 0 and not any(known(i) for i in (*range(7, 12), 19))
    if ((known(8) and value[8] and known(7) and not value[7])
            or (known(9) and value[9] and known(8) and not value[8])
            or (known(10) and value[10] and known(9) and value[9] == 0)
            or (known(11) and value[11] and known(10) and not value[10])
            or (known(19) and value[12] > value[19])):
        return False
    return True


def _modules():
    if __package__:
        from . import capture_readiness, numeric_notice
    else:
        import capture_readiness
        import numeric_notice
    return capture_readiness, numeric_notice


def _trace(primary):
    _need(type(primary) is AssertionError)
    frames, current = [], primary.__traceback__
    for _ in range(64):
        if current is None:
            break
        frames.append(current.tb_frame)
        current = current.tb_next
    _need(frames and current is None)
    return frames


def _context(record, writer):
    _need(type(record) is dict and record.get('success') is False)
    expected = (('case', 'ime-writer'), ('module', 'writer'),
                ('stage', 'verify-pre-prefix-editing-context')) if writer else (
                ('case', 'calc-close-cancel'), ('module', 'calc'), ('stage', 'type-without-enter'))
    _need(all(type(record.get(key)) is str and record[key] == text for key, text in expected))
    _need(type(record.get('kind')) is str and record['kind'] in (
        ('native-korean-ime', 'native-ime-mode-diagnostic') if writer else ('physical-calc-uncommitted-close',)))
    if writer:
        _need(type(record.get('architecture')) is str and record['architecture'] in ('x64', 'arm64'))
    return tuple(record[key] for key in ('case', 'module', 'stage', 'kind')) + (
        record['architecture'] if writer else None,)


def _owner(record, receipt, binding):
    _need(type(receipt) is dict and type(binding) is dict)
    numbers = {key: _int(binding.get(key)) for key in _BINDING}
    _need(numbers['shellPid'] != numbers['officePid'] and numbers['rootHwnd'] == numbers['suiteHwnd'])
    for key, name in (('shellPid', 'shellPid'), ('officePid', 'officePid'),
                      ('windowHwnd', 'suiteHwnd'), ('parentHwnd', 'parentHwnd'), ('childHwnd', 'childHwnd')):
        _need(_int(record.get(key)) == numbers[name])
    originals = []
    for role, pid, creation in (('Shell', numbers['shellPid'], numbers['shellCreationTime']),
                                ('Engine', numbers['officePid'], numbers['officeCreationTime'])):
        value = receipt.get('original' + role)
        _need(type(value) is dict and _int(value.get('pid')) == pid
              and _int(value.get('creationTime')) == creation and _int(value.get('handleValue'))
              and type(value.get('waitResult')) is int and value['waitResult'] == 258)
        originals.append(tuple(value[key] for key in ('pid', 'handleValue', 'creationTime', 'waitResult')))
    return numbers, tuple(originals)


def _row(row, binding, originals, pending):
    _need(type(row) is dict)
    witness = []
    for role, original in zip(('shell', 'engine'), originals):
        value = row.get(role)
        _need(type(value) is dict)
        observed = tuple(value.get(key) for key in ('pid', 'handleValue', 'creationTime', 'waitResult'))
        _need(all(type(item) is int for item in observed) and observed == original)
        witness.extend(observed)
    scope = row.get('scope'); _need(type(scope) is dict)
    threads = {}
    for edge in ('before', 'after'):
        values = scope.get(edge); _need(type(values) is dict)
        for role, hwnd, pid in (('suite', binding['suiteHwnd'], binding['shellPid']),
                                ('editor', binding['childHwnd'], binding['officePid'])):
            window = values.get(role); _need(type(window) is dict and window.get('isWindow') is True)
            numbers = tuple(_int(window.get(key)) for key in ('hwnd', 'pid', 'threadId', 'rootHwnd'))
            _need(numbers[0] == hwnd and numbers[1] == pid and numbers[3] == binding['suiteHwnd'])
            if role in threads: _need(threads[role] == numbers[2])
            threads[role] = numbers[2]; witness.extend(numbers)
    focus = scope.get('focus'); capture = scope.get('capture')
    _need(type(focus) is dict and focus.get('isWindow') is True and type(capture) is dict)
    focused = tuple(_int(focus.get(key)) for key in ('hwnd', 'pid', 'threadId', 'rootHwnd'))
    _need(focused[1:] == (binding['officePid'], threads['editor'], binding['suiteHwnd'])
          and scope.get('focusWithinEditor') is True)
    witness.extend(focused); focus_hwnd = focused[0]
    parent = scope.get('parent'); _need(type(parent) is dict and parent.get('isWindow') is True)
    parent_numbers = tuple(_int(parent.get(key)) for key in ('hwnd', 'pid', 'threadId', 'rootHwnd'))
    _need(parent_numbers == (binding['parentHwnd'], binding['shellPid'], threads['suite'], binding['suiteHwnd'])
          and all(scope.get(key) is True for key in ('suiteOwnsParent', 'parentOwnsChild',
              'parentVisible', 'parentEnabled', 'childVisible', 'childEnabled')))
    witness.extend(parent_numbers)
    value = capture.get('hwnd'); _need(type(value) is int and 0 <= value < 2**64)
    if pending:
        _need(value > 0 and capture.get('isWindow') is True
              and _int(capture.get('rootHwnd')) == binding['suiteHwnd'])
        expected = {binding['shellPid']: threads['suite'], binding['officePid']: threads['editor']}
        pid = _int(capture.get('pid')); _need(pid in expected and _int(capture.get('threadId')) == expected[pid])
        witness.extend((pid, capture['threadId'], capture['rootHwnd']))
    relation = next((code for hwnd, code in ((binding['childHwnd'], 1), (focus_hwnd, 2),
        (binding['parentHwnd'], 3), (binding['suiteHwnd'], 4)) if value == hwnd), 5) if value else 0
    witness.extend((focus_hwnd, value))
    return relation, tuple(witness)


def _base(record, primary, session, receipt, deadline, writer):
    capture, codec = _modules()
    frames = _trace(primary); leaf = frames[-1]
    _context(record, writer)
    _need(vars(session).get('record') is record and vars(session).get('receipt') is receipt)
    current = vars(primary).get('opengeul_capture_invocation')
    _need(type(current) is dict and current.keys() == _INV_KEYS
          and capture.current_capture_invocation(receipt) is current
          and current.get('schemaVersion') == 1 and type(current.get('schemaVersion')) is int
          and type(current.get('kind')) is str and current['kind'] == 'owned-capture-readiness-invocation'
          and _time(current.get('deadline')) == deadline)
    phase = current.get('timeoutPhase'); _need(type(phase) is int and 0 <= phase <= 5)
    flags = [current.get(key) for key in ('observationPresent', 'validationReturned', 'ownedPositiveCapturePending')]
    _need(all(type(flag) is bool for flag in flags))
    if leaf.f_code is capture.settle_owned_capture.__code__:
        _need(phase > 0 and leaf.f_locals.get('receipt') is receipt
              and leaf.f_locals.get('current') is current)
        failed = _time(leaf.f_locals.get('checked_at'))
    else:
        _need(writer and phase == 0 and leaf.f_code is type(session)._budget.__code__
              and leaf.f_code.co_filename.replace('\\', '/') == _ROOT + '/ime_keyboard_session.py'
              and leaf.f_locals.get('self') is session
              and any(frame.f_code is type(session)._validate_guard.__code__
                      and frame.f_locals.get('self') is session for frame in frames))
        failed = _time(leaf.f_locals.get('checked_at'))
    first, last = _time(current.get('firstCheckedAt')), _time(current.get('lastCheckedAt'))
    _need(first <= last <= failed and failed >= deadline)
    binding_key = 'expectedNative' if writer else 'expectedBinding'
    binding, originals = _owner(record, receipt, receipt.get(binding_key))
    live_binding = vars(session).get('binding'); _need(type(live_binding) is dict)
    _need(all(type(live_binding.get(key)) is int and live_binding[key] == number
              for key, number in binding.items()))
    capture_frames = [frame for frame in frames if frame.f_code is capture.settle_owned_capture.__code__
        and frame.f_locals.get('receipt') is receipt and frame.f_locals.get('current') is current
        and frame.f_locals.get('binding') is live_binding]
    _need(len(capture_frames) == 1)
    row = vars(primary).get('opengeul_capture_observation')
    relation, witness = None, None
    if flags[0]:
        _need(row is receipt.get('lastGuardObservation')
              and capture_frames[0].f_locals.get('row') is row)
        relation, witness = _row(row, binding, originals, flags[2])
    else:
        _need(row is None)
    value = [2 if writer else 1, 0] + [0] * 18
    def put(index, number):
        _need(type(number) is int)
        value[index] = number; value[1] |= 1 << (index - 2)
    put(2, phase)
    for index, flag in zip((3, 4, 5), flags): put(index, int(flag))
    if relation is not None: put(6, relation)
    for index, at in ((12, first), (13, last), (14, failed),
                      (15, receipt.get('startedAt')), (16, receipt.get('engineHandleAdmittedAt'))):
        if at is not None: put(index, _ms(deadline, at))
    return value, put, current, row, witness, binding, codec.capture_failure_frames(primary)


def _proof(record, primary, session, receipt, binding, writer, context=None):
    key = 'expectedNative' if writer else 'expectedBinding'
    numbers, originals = _owner(record, receipt, receipt[key])
    _need(numbers == binding)
    before = record.get('beforeInput') if not writer else None
    if not writer:
        _need(type(before) is dict and type(before.get('bindingBefore')) is dict)
    timing = tuple((name, _time(before[name])) for name in ('readStartedAt', 'readFinishedAt')
                   if before is not None and name in before)
    return (_context(record, writer), _trace(primary)[-1], receipt[key],
            receipt['originalShell'], receipt['originalEngine'], tuple(numbers.items()),
            originals, context.get('expectedNative') if context is not None else None,
            vars(session).get('binding'), before,
            before['bindingBefore'] if before is not None else None, timing)


def freeze_writer(record, primary, session, context):
    """Freeze scalar state inside require_context_target, before semantic finally."""
    try:
        if any(entry[0] is record and entry[1] is primary for entry in _FROZEN): return
        receipt = vars(session).get('receipt')
        _need(type(context) is dict and record.get('imeSemanticContext') is context
              and record.get('imeKeyboardSession') is receipt
              and context.get('schemaVersion') == 1 and type(context.get('schemaVersion')) is int
              and context.get('kind') == 'ime-semantic-editing-context'
              and context.get('module') == 'writer' and context.get('phase') == 'pre')
        started, deadline, setup = (_time(context.get(key)) for key in ('startedAt', 'readerDeadline', 'setupDeadline'))
        method = type(session).require_context_target.__code__
        codes = [item for item in method.co_consts if type(item) is type(method) and item.co_name == 'current']
        _need(len(codes) == 1 and method.co_filename.replace('\\', '/') == _ROOT + '/ime_keyboard_session.py')
        callers = [frame for frame in _trace(primary) if frame.f_code is codes[0]
            and frame.f_locals.get('self') is session and frame.f_locals.get('context') is context
            and frame.f_locals.get('started') == started and frame.f_locals.get('deadline') == deadline]
        _need(len(callers) == 1)
        _need(started < deadline == min(setup, started + 12.)
              and vars(session).get('deadline') == deadline
              and vars(session).get('setup_deadline') == setup == _time(receipt.get('setupDeadline')))
        value, put, current, row, witness, binding, frames = _base(record, primary, session, receipt, deadline, True)
        expected = context.get('expectedNative'); _need(type(expected) is dict)
        _need(all(type(expected.get(key)) is int and expected[key] == number for key, number in binding.items()))
        inventory = ('inventoryEvidence' in context, 'inventorySha256' in context)
        _need(inventory[0] == inventory[1]); put(7, int(inventory[0]))
        attempted = context.get('readerStartAttempted', False); _need(type(attempted) is bool); put(8, int(attempted))
        observations, timings = context.get('observations'), context.get('sampleTimings')
        _need(type(observations) is list and type(timings) is list and len(observations) == len(timings) <= 120)
        put(9, len(observations)); put(10, int('cleanup' in context)); put(11, int('finishedAt' in context))
        if timings:
            last = timings[-1]; _need(type(last) is dict)
            requested, received = _time(last.get('requestedAt')), _time(last.get('receivedAt'))
            _need(started <= requested <= received <= deadline)
            put(17, _ms(deadline, requested)); put(18, _ms(deadline, received))
        if 'cleanup' in context: _need(type(context['cleanup']) is dict)
        if 'finishedAt' in context: _time(context['finishedAt'])
        put(19, math.floor(1000 * (deadline - started)))
        _need(valid(value))
        _remember(_FROZEN, (record, primary, session, receipt, context, current, row, witness,
                        tuple(value), tuple(map(tuple, frames)), dict(current),
                        _proof(record, primary, session, receipt, binding, True, context)))
    except Exception:
        return


def _calc(record, primary):
    _context(record, False)
    frames = _trace(primary)
    for frame in frames:
        session = frame.f_locals.get('self')
        if (session is not None and type(session).__name__ == 'CountedEditorShortcuts'
                and frame.f_code.co_filename.replace('\\', '/') == _ROOT + '/counted_editor_shortcuts.py'
                and vars(session).get('record') is record):
            receipt = vars(session).get('receipt')
            sessions = record.get('editorShortcutSessions')
            _need(type(sessions) is list and sessions and sessions[-1] is receipt
                  and type(receipt) is dict and receipt.get('schemaVersion') == 1
                  and type(receipt.get('schemaVersion')) is int
                  and receipt.get('kind') == 'owned-counted-editor-navigation'
                  and type(receipt.get('actions')) is list and not receipt['actions']
                  and record.get('closeShortcutCount') == 0 and type(record.get('closeShortcutCount')) is int)
            deadline = _time(receipt.get('deadline'))
            value, put, current, row, witness, binding, owned = _base(record, primary, session, receipt, deadline, False)
            before = record.get('beforeInput'); _need(type(before) is dict)
            expected = before.get('bindingBefore'); _need(type(expected) is dict)
            _need(all(type(expected.get(key)) is int and expected[key] == number for key, number in binding.items()))
            for index, key in ((17, 'readStartedAt'), (18, 'readFinishedAt')):
                if key in before: put(index, _ms(deadline, before[key]))
            _need(valid(value))
            return (record, primary, session, receipt, None, current, row, witness,
                    tuple(value), tuple(map(tuple, owned)), dict(current),
                    _proof(record, primary, session, receipt, binding, False))
    raise ValueError('Missing original counted reader guard')


def _same_failure(record, primary, original_frames):
    _, codec = _modules()
    actual = codec.capture_failure_frames(primary)
    stored = codec.validate_failure_frames(record.get('numericFailureFrames'))
    failure = codec.validate_failure_code(record.get('numericFailure'))
    _need(stored and actual and stored == actual[-len(stored):]
          and list(map(list, original_frames)) == actual[-len(original_frames):]
          and failure == codec.capture_failure_code(primary)
          and stored[-1] == [failure['fileCode'], failure['line']])


def bind(record, primary):
    """Bind one actual failure; absence or malformed data leaves it unknown."""
    try:
        if any(entry[0] is record for entry in _BOUND): return
        if type(record) is not dict or type(primary) is not AssertionError: return
        if record.get('case') == 'ime-writer':
            entry = next(entry for entry in reversed(_FROZEN) if entry[0] is record and entry[1] is primary)
        else:
            entry = _calc(record, primary)
        _remember(_BOUND, entry)
    except Exception:
        return


def project(record):
    """Return only a copy of a currently bound immutable numeric witness."""
    try:
        capture, _ = _modules()
        entry = next(entry for entry in reversed(_BOUND) if entry[0] is record)
        _, primary, session, receipt, context, current, row, witness, vector, frames, metadata, proof = entry
        _need(_context(record, context is not None) == proof[0] and _trace(primary)[-1] is proof[1])
        _need(vars(session).get('record') is record and vars(session).get('receipt') is receipt
              and capture.current_capture_invocation(receipt) is current and current == metadata
              and vars(primary).get('opengeul_capture_invocation') is current
              and vars(primary).get('opengeul_capture_observation') is row)
        if context is not None:
            _need(record.get('imeSemanticContext') is context and record.get('imeKeyboardSession') is receipt
                  and context.get('expectedNative') is proof[7])
        else:
            sessions = record.get('editorShortcutSessions'); _need(type(sessions) is list and sessions and sessions[-1] is receipt)
        key = 'expectedNative' if context is not None else 'expectedBinding'
        _need(receipt.get(key) is proof[2] and receipt.get('originalShell') is proof[3]
              and receipt.get('originalEngine') is proof[4] and vars(session).get('binding') is proof[8])
        binding, originals = _owner(record, receipt, receipt[key])
        _need(tuple(binding.items()) == proof[5] and originals == proof[6]
              and all(type(proof[8].get(name)) is int and proof[8][name] == number
                      for name, number in binding.items()))
        if context is not None:
            _need(all(type(proof[7].get(name)) is int and proof[7][name] == number
                      for name, number in binding.items()))
        else:
            before = record.get('beforeInput')
            _need(before is proof[9] and before.get('bindingBefore') is proof[10]
                  and all(type(proof[10].get(name)) is int and proof[10][name] == number
                          for name, number in binding.items()))
            timing = tuple((name, _time(before[name])) for name in ('readStartedAt', 'readFinishedAt') if name in before)
            _need(timing == proof[11])
        if row is not None:
            _need(receipt.get('lastGuardObservation') is row)
            relation, current_witness = _row(row, binding, originals, bool(vector[5]))
            _need(relation == vector[6] and current_witness == witness)
        _same_failure(record, primary, frames)
        value = list(vector); _need(valid(value)); return value
    except Exception:
        return None
