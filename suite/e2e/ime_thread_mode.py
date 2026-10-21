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
