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



_GUI_SAMPLE_MAXIMA = dict(phaseCode=2, attempted=1, known=1, errorCode=7,
    focusWithinChild=1, activeCode=5, focusCode=5, captureCode=5, menuOwnerCode=5)


def valid_gui_focus(value, focus_call=None):
    """Optional Win32 interval classifications; never Writer qualification."""
    if (type(value) is not dict or value.keys() != {
            'schemaVersion', 'diagnosticOnly', 'acceptanceEligible', 'before', 'after'}
            or any(type(value[key]) is not int for key in
                ('schemaVersion', 'diagnosticOnly', 'acceptanceEligible'))
            or (value['schemaVersion'], value['diagnosticOnly'], value['acceptanceEligible']) != (1, 1, 0)):
        return False
    for phase, name in ((1, 'before'), (2, 'after')):
        row = value[name]
        if (type(row) is not dict or row.keys() != _GUI_SAMPLE_MAXIMA.keys()
                or any(type(row[key]) is not int or not 0 <= row[key] <= maximum
                    for key, maximum in _GUI_SAMPLE_MAXIMA.items()) or row['phaseCode'] != phase):
            return False
        codes = [row[key] for key in ('activeCode', 'focusCode', 'captureCode', 'menuOwnerCode')]
        if row['known']:
            if (row['attempted'] != 1 or row['errorCode'] != 0 or not all(codes)
                    or row['focusWithinChild'] != int(row['focusCode'] in (2, 3))):
                return False
        elif row['errorCode'] == 0 or any(codes) or row['focusWithinChild']:
            return False
        if row['errorCode'] in (4, 5, 7) and row['attempted'] != 1:
            return False
    if value['after']['attempted'] and not (value['before']['attempted']
            and type(focus_call) is dict and focus_call.get('attempted') == 1):
        return False
    return True


_POST_MAXIMA = dict(schemaVersion=1, diagnosticOnly=1, acceptanceEligible=0,
    sameRetainedRoot=1, known=1, attemptedMask=7, observedMask=7, stopCode=7,
    rootState=0x7fffffff, ia2Supported=1, textSupported=1,
    ownerBefore=1, ownerAfter=1, officePid=0xffffffff,
    officeCreationTime=2**64-1, childHwnd=2**64-1,
    generationBefore=2**64-1, generationAfter=2**64-1,
    startedMicros=2**63-1, finishedMicros=2**63-1, deadlineMicros=2**63-1,
    hresultObserved=1, hresult=0xffffffff)


def valid_post_failure(value, original):
    """Same-root diagnostic only; zero outside observedMask remains unknown."""
    if (type(value) is not dict or value.keys() != _POST_MAXIMA.keys()
            or any(type(value[k]) is not int or not 0 <= value[k] <= limit
                for k, limit in _POST_MAXIMA.items())
            or (value['schemaVersion'], value['diagnosticOnly'], value['acceptanceEligible'],
                value['sameRetainedRoot']) != (1, 1, 0, 1)):
        return False
    if (original.get('verified') != 0 or original.get('stageCode') != 4
            or original.get('hresult') != 0 or original.get('focusVariantType') != 0
            or original.get('focusCall') != dict(attempted=1, returned=1,
                hrObserved=1, hr=0, vtObserved=1, rejectCode=3)
            or any(value[k] != original.get(k) for k in
                ('officePid', 'officeCreationTime', 'childHwnd'))):
        return False
    a, m = value['attemptedMask'], value['observedMask']
    if (a not in (0,1,3,7) or m not in (0,1,3,7) or m & ~a
            or a & 2 and not m & 1 or a & 4 and not m & 2
            or not m & 1 and value['rootState']
            or value['ia2Supported'] != int(bool(m & 2))
            or value['textSupported'] != int(bool(m & 4))
            or value['generationBefore'] != (value['officeCreationTime'] if value['ownerBefore'] else 0)
            or value['generationAfter'] != (value['officeCreationTime'] if value['ownerAfter'] else 0)
            or value['ownerAfter'] > value['ownerBefore']
            or a and not value['ownerBefore']
            or not value['hresultObserved'] and value['hresult']):
        return False
    complete = (m == 7 and value['ownerBefore'] == value['ownerAfter'] == 1
        and 0 <= value['startedMicros'] <= value['finishedMicros'] < value['deadlineMicros']
        and value['hresultObserved'] == value['hresult'] == 0 and value['stopCode'] == 0)
    return (bool(value['known']) == complete and
        (value['stopCode'] != 0 or complete))


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
    if (type(result) is not dict or not base <= result.keys()
            or not result.keys() <= base | {'focusCall', 'guiFocus', 'postFailureDiagnostic'}
            or type(result['schemaVersion']) is not int or result['schemaVersion'] != 1):
        return None
    if 'focusCall' in result and not valid_focus_call(result['focusCall'], result['focusVariantType']):
        return None
    if 'guiFocus' in result and not valid_gui_focus(result['guiFocus'], result.get('focusCall')):
        return None
    if 'postFailureDiagnostic' in result and not valid_post_failure(result['postFailureDiagnostic'], result):
        return None
    value = [result[key] for key in FIELDS]
    if not valid(value) or record.get('stage') != STAGE_NAMES[result['stageCode']]:
        return None
    for key in ('officePid','officeCreationTime','childHwnd'):
        if type(record.get(key)) is not int or record[key] != result[key]:
            return None
    return value
