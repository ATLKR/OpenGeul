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
    if (type(result) is not dict or result.keys() != {'schemaVersion', *FIELDS}
            or type(result['schemaVersion']) is not int or result['schemaVersion'] != 1):
        return None
    value = [result[key] for key in FIELDS]
    if not valid(value) or record.get('stage') != STAGE_NAMES[result['stageCode']]:
        return None
    for key in ('officePid','officeCreationTime','childHwnd'):
        if type(record.get(key)) is not int or record[key] != result[key]:
            return None
    return value
