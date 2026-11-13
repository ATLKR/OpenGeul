"""Fixed-width receipts for the observer's existing owned-thread TSF manager.

Mode state is a setup acknowledgement. Real Korean composition and exact saved
and reopened content remain the independent delivery gates.
"""
import ctypes
import math
import time

OBSERVER_CLSID = '{9A60C08C-C9E4-4D70-90B6-2A073C5BFAD8}'
NOT_ATTEMPTED = -2147483638
_SIGNED = ('status', 'cleanupStatus', 'managerHr', 'compartmentManagerHr',
    'enumerationHr', 'enumerationNextHr', 'openGetHr', 'conversionGetHr',
    'beforeOpenHr', 'beforeConversionHr', 'clientQueryHr', 'clientHr',
    'openSetHr', 'conversionSetHr', 'afterOpenHr', 'afterConversionHr')
_UNSIGNED = ('enumerationCount', 'installedMask', 'clientId', 'beforeOpenType',
    'beforeConversionType', 'afterOpenType', 'afterConversionType')
_VALUES = ('beforeOpen', 'beforeConversion', 'requestedOpen', 'requestedConversion',
    'afterOpen', 'afterConversion')
_COUNTS = ('openSetCalls', 'conversionSetCalls', 'releaseCalls',
    'referencesAcquired', 'referencesReleased')


_PRESENCE = ('managerPresent', 'compartmentManagerPresent', 'enumeratorPresent',
    'openPresent', 'conversionPresent', 'clientPresent', 'nextFetched', 'clientIdCalls',
    'modulePresent', 'lookupPresent', 'managerCallAttempts')


class NativeModeReceipt(ctypes.Structure):
    _fields_ = ([(name, ctypes.c_int32) for name in _SIGNED]
        + [(name, ctypes.c_uint32) for name in _UNSIGNED]
        + [(name, ctypes.c_int32) for name in _VALUES]
        + [(name, ctypes.c_uint32) for name in _COUNTS]
        + [(name, ctypes.c_uint32) for name in _PRESENCE]
        + [('variantClearHr', ctypes.c_int32)])


class NativeCommandBudget(ctypes.Structure):
    _fields_ = [('counter', ctypes.c_uint64), ('frequency', ctypes.c_uint64)]


class NativeCommandRejection(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint32), ('sequence', ctypes.c_uint32),
               ('during', ctypes.c_uint32), ('reason', ctypes.c_uint32)]


def receipt_dict(value):
    return {name: int(getattr(value, name)) for name, _ in NativeModeReceipt._fields_}


def require_mode_receipt(receipt, command, *, previous=None):
    names = {name for name, _ in NativeModeReceipt._fields_}
    assert isinstance(receipt, dict) and set(receipt) == names, 'Incomplete native TSF mode receipt'
    assert all(type(value) is int for value in receipt.values()), 'Native mode values must remain exact integers'
    for name, kind in NativeModeReceipt._fields_:
        lower, upper = (-2**31, 2**31) if kind is ctypes.c_int32 else (0, 2**32)
        assert lower <= receipt[name] < upper, 'Native mode value exceeds its fixed-width field: ' + name
    assert type(command) is int and command in (1, 2, 3, 4)
    for name in ('status', 'cleanupStatus', 'managerHr', 'compartmentManagerHr',
                 'enumerationHr', 'enumerationNextHr', 'openGetHr',
                 'conversionGetHr', 'beforeOpenHr', 'beforeConversionHr'):
        assert receipt[name] == 0, 'Owned-thread TSF mode admission failed: ' + name
    assert all(receipt[name] == 1 for name in ('managerPresent', 'compartmentManagerPresent', 'enumeratorPresent', 'openPresent', 'conversionPresent', 'modulePresent', 'lookupPresent', 'managerCallAttempts')), 'Native TSF interfaces were not present'
    assert receipt['nextFetched'] == 1 and receipt['variantClearHr'] == 0, 'Native enumeration or VARIANT cleanup failed'
    assert receipt['installedMask'] == 3 and 2 <= receipt['enumerationCount'] <= 64, 'Original keyboard compartments were not enumerated'
    assert receipt['beforeOpenType'] == receipt['beforeConversionType'] == 3, 'Original mode state is not concrete VT_I4'
    assert receipt['releaseCalls'] == 1 and receipt['referencesAcquired'] == receipt['referencesReleased'], 'Native mode COM references were not released'
    assert receipt['referencesAcquired'] >= (5 if command == 1 else 6)
    if command == 1:
        assert receipt['openSetCalls'] == receipt['conversionSetCalls'] == receipt['clientId'] == 0, 'Original mode capture must be read-only'
        assert receipt['clientPresent'] == receipt['clientIdCalls'] == 0
        assert all(receipt[name] == NOT_ATTEMPTED for name in ('clientQueryHr', 'clientHr',
            'openSetHr', 'conversionSetHr', 'afterOpenHr', 'afterConversionHr')), 'Read-only mode capture claims unattempted native operations'
        return receipt
    assert receipt['clientPresent'] == receipt['clientIdCalls'] == 1
    assert receipt['clientId'] > 0 and receipt['openSetCalls'] == receipt['conversionSetCalls'] == 1, 'Mode setting requires one pair with its own client ID'
    for name in ('clientQueryHr', 'clientHr', 'openSetHr', 'conversionSetHr', 'afterOpenHr', 'afterConversionHr'):
        assert receipt[name] == 0, 'Native TSF mode operation failed: ' + name
    assert receipt['afterOpenType'] == receipt['afterConversionType'] == 3
    if command == 4:
        assert isinstance(previous, tuple) and len(previous) == 2 and all(type(v) is int for v in previous), 'Exact original TSF mode state is missing'
        requested = previous
    else:
        requested = (1, receipt['beforeConversion'] | 1 if command == 3 else receipt['beforeConversion'] & ~1)
    assert (receipt['requestedOpen'], receipt['requestedConversion']) == requested, 'Requested mode differs from the original command'
    assert (receipt['afterOpen'], receipt['afterConversion']) == requested, 'Requested mode was not read back on the owned thread'
    return receipt


def _typed_pair(receipt, prefix):
    result = []
    for key in ('Open', 'Conversion'):
        hr, kind, value = (receipt[prefix+key+'Hr'], receipt[prefix+key+'Type'], receipt[prefix+key])
        assert (hr, kind) in ((0, 3), (1, 0)), 'Unsupported typed TSF value'
        result.append((hr, kind, value if kind == 3 else None))
    return tuple(result)


def require_original_pair(pair):
    assert type(pair) is tuple and len(pair) == 2 and all(type(value) is tuple and len(value) == 3 for value in pair), 'Immutable original TSF pair is missing'
    for hr, kind, value in pair:
        assert type(hr) is int and type(kind) is int
        assert ((hr, kind) == (1, 0) and value is None) or ((hr, kind) == (0, 3) and type(value) is int and -2**31 <= value < 2**31), 'Invalid original TSF tag'
    assert all(value[:2] == pair[0][:2] for value in pair), 'Mixed original TSF pair is not admitted'
    return pair


def typed_pair_dict(pair):
    result = {}
    for key, (hr, kind, value) in zip(('open', 'conversion'), pair):
        result[key] = dict(hresult=hr, variantType=kind, kind='i4' if kind == 3 else 'empty')
        if kind == 3: result[key]['value'] = value
    return result


def require_typed_mode_receipt(receipt, command, *, original=None, allow_empty=False):
    """Wire4 policy; old concrete validation remains the strict delegate."""
    assert type(command) is int and command in (1, 2, 3, 4) and type(allow_empty) is bool
    assert type(receipt) is dict and set(receipt) == {name for name, _ in NativeModeReceipt._fields_}, 'Incomplete typed mode receipt'
    for name, kind in NativeModeReceipt._fields_:
        value = receipt[name]
        lower, upper = (-2**31, 2**31) if kind is ctypes.c_int32 else (0, 2**32)
        assert type(value) is int and lower <= value < upper, 'Invalid typed mode field: ' + name
    before = _typed_pair(receipt, 'before')
    if command == 1:
        assert original is None
        require_original_pair(before)
        if before[0][1] == 3:
            require_mode_receipt(receipt, 1)
            return before
        assert allow_empty, 'Empty original TSF state requires the exact original US profile'
    else:
        require_original_pair(original)
        if original[0][1] == 3 or command == 3 or (command == 2 and all(value[1] == 3 for value in before)):
            require_mode_receipt(receipt, command, previous=tuple(value[2] for value in original) if command == 4 else None)
            return _typed_pair(receipt, 'after')
    for name in ('status', 'cleanupStatus', 'managerHr', 'compartmentManagerHr', 'enumerationHr', 'enumerationNextHr', 'openGetHr', 'conversionGetHr', 'variantClearHr'):
        assert receipt[name] == 0, 'Typed mode operation/cleanup failed: ' + name
    assert receipt['installedMask'] == 3 and 2 <= receipt['enumerationCount'] <= 64
    assert all(receipt[name] == 1 for name in ('managerPresent', 'compartmentManagerPresent', 'enumeratorPresent', 'openPresent', 'conversionPresent', 'modulePresent', 'lookupPresent', 'managerCallAttempts', 'nextFetched'))
    expected_refs = 6 if command == 2 else 5
    assert receipt['releaseCalls'] == 1 and receipt['referencesAcquired'] == receipt['referencesReleased'] == expected_refs
    if command in (1, 4):
        assert all(receipt[name] == 0 for name in ('openSetCalls', 'conversionSetCalls', 'clientId', 'clientIdCalls', 'clientPresent'))
        assert all(receipt[name] == NOT_ATTEMPTED for name in ('clientQueryHr', 'clientHr', 'openSetHr', 'conversionSetHr', 'afterOpenHr', 'afterConversionHr'))
        return before
    assert command == 2 and all(value[:2] == (1, 0) for value in before), 'Only both-EMPTY Korean state may initialize a new ASCII target'
    assert receipt['clientPresent'] == receipt['clientIdCalls'] == receipt['openSetCalls'] == receipt['conversionSetCalls'] == 1 and receipt['clientId'] > 0
    assert all(receipt[name] == 0 for name in ('clientQueryHr', 'clientHr', 'openSetHr', 'conversionSetHr', 'afterOpenHr', 'afterConversionHr'))
    assert (receipt['requestedOpen'], receipt['requestedConversion']) == (1, 0), 'New ASCII target must be explicit open1/full ALPHANUMERIC0'
    after = _typed_pair(receipt, 'after')
    assert after == ((0, 3, 1), (0, 3, 0)), 'Explicit new ASCII target was not read back exactly'
    return after


def counter_budget(deadline, *, clock=time.monotonic, counter=None, frequency=None):
    """Conservatively translate the remaining parent budget to native QPC ticks.

    Sample the counter before the Python clock. Time spent between those reads
    consumes the budget rather than extending the native deadline.
    """
    assert type(deadline) in (int, float) and math.isfinite(deadline)
    if counter is None:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_int64)]
        kernel.QueryPerformanceCounter.restype = ctypes.c_int
        kernel.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_int64)]
        kernel.QueryPerformanceFrequency.restype = ctypes.c_int
        value = ctypes.c_int64()
        if not kernel.QueryPerformanceFrequency(ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        frequency = value.value
        def counter():
            stamp = ctypes.c_int64()
            if not kernel.QueryPerformanceCounter(ctypes.byref(stamp)):
                raise ctypes.WinError(ctypes.get_last_error())
            return stamp.value
    assert type(frequency) is int and frequency > 0, 'Invalid native counter frequency'
    started = counter()
    assert type(started) is int and started > 0
    remaining = deadline - clock()
    assert 0 < remaining < float('inf'), 'Original native mode deadline expired'
    result = started + math.floor(remaining * frequency)
    assert started < result < 2**63, 'No finite native mode counter budget remains'
    return result, frequency
