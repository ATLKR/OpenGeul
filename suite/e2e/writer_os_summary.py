"""Pure projection of an already completed, closed Writer OS failure result.

The fixed vector follows the probe's existing numeric fields, excluding its
schemaVersion. No target, process, clock, COM interface or document is sampled.
Reference/VARIANT release counters are diagnostics, never engine death proof.
"""
from __future__ import annotations

_MAXIMA = dict(verified=1, stageCode=14, hresult=0xffffffff,
    officePid=0xffffffff, officeCreationTime=2**64-1, childHwnd=2**64-1,
    rootRole=0x7fffffff, documentRole=0x7fffffff, focusedRole=0x7fffffff,
    focusedState=0x7fffffff, focusVariantType=0xffff, parentCount=32,
    ia2Supported=1, textSupported=1, ownerBefore=1, ownerAfter=1,
    referencesAcquired=256, referencesReleased=256, variantsCreated=64,
    variantsCleared=64, cleanupFailure=1, cleanupHresult=0xffffffff,
    ownerReleased=1)
FIELDS = tuple(_MAXIMA)
STAGE_NAMES = {1:'writer-os-owner', 2:'writer-os-abi', 3:'writer-os-root',
    4:'writer-os-focus', 5:'writer-os-document-role', 6:'writer-os-focus-state',
    7:'writer-os-ia2', 8:'writer-os-text', 9:'writer-os-parent',
    10:'writer-os-owner', 11:'writer-os-cleanup',
    13:'writer-os-protocol', 14:'writer-os-timeout'}

_FOCUS_CALL_MAXIMA = dict(attempted=1, returned=1, hrObserved=1,
    hr=0xffffffff, vtObserved=1, rejectCode=5)


def valid_focus_call(value, variant_type):
    """Closed optional client-call diagnostics, never an acceptance predicate."""
    if (type(value) is not dict or value.keys() != _FOCUS_CALL_MAXIMA.keys()
            or any(type(value[key]) is not int or not 0 <= value[key] <= maximum
                   for key, maximum in _FOCUS_CALL_MAXIMA.items())
            or type(variant_type) is not int or not 0 <= variant_type <= 0xffff):
        return False
    if (value['returned'] > value['attempted'] or value['hrObserved'] > value['returned']
            or value['vtObserved'] > value['returned']
            or not value['hrObserved'] and value['hr']
            or not value['vtObserved'] and variant_type):
        return False
    code = value['rejectCode']
    if code == 1:
        return value['attempted'] == 1 and value['returned'] == value['hrObserved'] == value['vtObserved'] == 0
    if code in (2, 3, 4, 5):
        if not value['returned'] == value['hrObserved'] == value['vtObserved'] == 1:
            return False
        if code == 2:
            return value['hr'] != 0
        return value['hr'] == 0 and (variant_type not in (3, 9) if code == 3 else variant_type == (9 if code == 4 else 3))
    if value['returned'] == value['hrObserved'] == value['vtObserved'] == 1:
        return value['hr'] == 0 and variant_type in (3, 9)
    # Code zero without a complete observation is unknown, not getter success.
    return True


def valid(value):
    """Validate a failure vector without importing producer/native modules."""
    if (type(value) is not list or len(value) != len(FIELDS)
            or any(type(number) is not int or not 0 <= number <= maximum
                   for number, maximum in zip(value, _MAXIMA.values()))):
        return False
    result = dict(zip(FIELDS, value))
    return (result['verified'] == 0 and result['stageCode'] in STAGE_NAMES
        and all(result[key] > 0 for key in ('officePid','officeCreationTime','childHwnd'))
        and result['referencesReleased'] <= result['referencesAcquired']
        and result['variantsCleared'] <= result['variantsCreated'])


def project(record):
    """Read only the closed result already held by this Writer failure record."""
    if (type(record) is not dict or record.get('case') != 'korean-ui-writer'
            or record.get('module') != 'writer' or record.get('success') is not False):
        return None
    result = record.get('writerOsAccessibility')
    base = {'schemaVersion', *FIELDS}
    if (type(result) is not dict or result.keys() not in (base, base | {'focusCall'})
            or type(result['schemaVersion']) is not int or result['schemaVersion'] != 1):
        return None
    if 'focusCall' in result and not valid_focus_call(result['focusCall'], result['focusVariantType']):
        return None
    value = [result[key] for key in FIELDS]
    if not valid(value) or record.get('stage') != STAGE_NAMES[result['stageCode']]:
        return None
    for key in ('officePid','officeCreationTime','childHwnd'):
        if type(record.get(key)) is not int or record[key] != result[key]:
            return None
    return value
