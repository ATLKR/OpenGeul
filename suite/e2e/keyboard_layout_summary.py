"""Closed values from an existing failed layout guard; never observe native state."""
from __future__ import annotations

FIELDS = ('origin', 'slot', 'officePid', 'officeCreationTime', 'childHwnd',
          'targetLayout', 'currentThreadLayout')
_KEY = '_keyboardLayoutFailure'
_US = 0x04090409
_BINDING = ('shellPid', 'shellCreationTime', 'officePid', 'officeCreationTime',
            'suiteHwnd', 'parentHwnd', 'childHwnd', 'rootHwnd')
_CONTEXT = ('case', 'module', 'kind', 'stage', 'architecture')
_OUTER = (('shellPid', 'shellPid'), ('shellCreationTime', 'shellCreationTime'),
          ('officePid', 'officePid'), ('officeCreationTime', 'officeCreationTime'),
          ('windowHwnd', 'suiteHwnd'), ('parentHwnd', 'parentHwnd'), ('childHwnd', 'childHwnd'))
_BOUND = []  # At most 32 exact record/raw/binding associations; never a fallback value.


def _need(condition):
    if not condition:
        raise ValueError('Unbound original keyboard layout failure')


def valid(value):
    """Pure wire predicate; zero HKL means only that observed API value."""
    return (type(value) is list and len(value) == 7
        and all(type(item) is int for item in value)
        and value[0] in (1, 2) and value[1] in (1, 2)
        and (value[0] != 1 or value[1] == 1)
        and 0 < value[2] < 2**32
        and all(0 < value[i] < 2**64 for i in (3, 4))
        and all(0 <= value[i] < 2**64 for i in (5, 6))
        and (value[5] != _US or value[6] != _US))


def _numbers(binding):
    _need(type(binding) is dict)
    values = tuple(binding[key] for key in _BINDING)
    _need(all(type(value) is int and 0 < value <
        (2**32 if key in ('shellPid', 'officePid') else 2**64)
        for key, value in zip(_BINDING, values)))
    _need(binding['shellPid'] != binding['officePid']
        and binding['rootHwnd'] == binding['suiteHwnd']
        and binding['officeCreationTime'] >= binding['shellCreationTime'])
    return values


def _outer(record, binding):
    for outer, native in _OUTER:
        if outer in record:
            _need(type(record[outer]) is int and record[outer] == binding[native])


def _context(record):
    values = []
    for key in _CONTEXT:
        present = key in record
        value = record.get(key)
        _need(not present or (type(value) is str and len(value) <= 160))
        values.append((key, present, value))
    return tuple(values)


def _receipt(record, origin):
    if origin == 1:
        value = record.get('imeKeyboardSession')
    else:
        receipts = record.get('editorShortcutSessions')
        _need(receipts is None or (type(receipts) is list and receipts))
        value = receipts[-1] if receipts is not None else None
    _need(value is None or type(value) is dict)
    return value


def _proof(receipt, binding):
    if receipt is None:
        return None
    proof = []
    for role, pid, creation in (('Shell', 'shellPid', 'shellCreationTime'),
                                ('Engine', 'officePid', 'officeCreationTime')):
        if 'original' + role not in receipt:
            proof.append(None)
            continue
        original = receipt['original' + role]
        _need(type(original) is dict)
        values = tuple(original[key] for key in ('pid', 'creationTime', 'handleValue', 'waitResult'))
        _need(all(type(value) is int for value in values)
            and values[0] == binding[pid] and values[1] == binding[creation]
            and 0 < values[2] < 2**64 and values[3] == 258)
        proof.append(values)
    native = receipt.get('expectedNative')
    _need(native is None or _numbers(native) == _numbers(binding))
    return tuple(proof)


def _current_owner(owner, record, binding, receipt):
    if owner is not None:
        state = vars(owner)
        _need(state.get('record') is record and state.get('binding') is binding
            and state.get('receipt') is receipt)


def remember(record, origin, slot, keyboard, binding, *, owner=None):
    """Retain already returned values for this record and retained binding only."""
    _need(type(record) is dict)
    record.pop(_KEY, None)
    _BOUND[:] = [entry for entry in _BOUND if entry[0] is not record]
    numbers = _numbers(binding)
    _outer(record, binding)
    context = _context(record)
    _need(type(keyboard) is dict)
    value = [origin, slot, binding['officePid'], binding['officeCreationTime'],
             binding['childHwnd'], keyboard['targetLayout'], keyboard['currentThreadLayout']]
    _need(valid(value))
    receipt = _receipt(record, origin)
    proof = _proof(receipt, binding)
    _current_owner(owner, record, binding, receipt)
    raw = dict(zip(FIELDS, value))
    record[_KEY] = raw
    _BOUND.append((record, raw, binding, numbers, context, receipt, proof, tuple(value), owner))
    del _BOUND[:-32]


def project(record):
    """Reject copied, reused or mutated evidence; read no Windows/native state."""
    try:
        if type(record) is not dict:
            return None
        raw = record.get(_KEY)
        if type(raw) is not dict or set(raw) != set(FIELDS):
            return None
        for original_record, original, binding, numbers, context, receipt, proof, frozen, owner in _BOUND:
            if original_record is not record or original is not raw:
                continue
            _current_owner(owner, record, binding, receipt)
            _need(_numbers(binding) == numbers and _context(record) == context)
            _outer(record, binding)
            value = [raw[key] for key in FIELDS]
            _need(valid(value) and tuple(value) == frozen)
            _need(_receipt(record, value[0]) is receipt and _proof(receipt, binding) == proof)
            return value
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return None
