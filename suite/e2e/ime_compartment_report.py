"""Closed numeric projection of existing receipts; never observes the target.

OnChange is a post-change observation. Neither this receipt nor file-only symbol
resolution proves its setter, a runtime caller, or release acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

if __package__:
    from . import numeric_notice
else:
    import numeric_notice

TITLE = 'OpenGeul IME compartment numeric v1'
OPT_IN = 'OPENGEUL_SUITE_IME_COMPARTMENT_NOTICE'
MAX_BYTES = 32768
KIND, SCOPE = 4, 11
_CALLBACK_STATUS = {'disabled': 0, 'inconclusive': 1, 'not-triggered': 2, 'complete': 3, 'unavailable': 4}
_CLEANUP_STATUS = {'pending': 0, 'inconclusive': 1, 'unsubscribed': 2, 'unproved': 3}
_SELECTION_STATUS = {'inconclusive-case': 1, 'not-reproduced': 2,
    'inconclusive-messages': 3, 'inconclusive-callback': 4,
    'inconclusive-no-product-frame': 5, 'selected': 6}
_TAGS = {name: i for i, name in enumerate(('unresolved', 'mutex-acquire',
    'mutex-release', 'mutex-acquire-with-wait', 'frame-input-context',
    'frame-input-context-dispatch', 'frame-window-procedure', 'frame-key-handler'), 1)}
_OWNER_KEYS = ('pid', 'creationTime', 'tid', 'hwnd', 'suiteHwnd')
_LEASE_KEYS = ('installAttempts', 'pinned', 'sourceReady', 'adviseAttempts',
    'subscriptionPossible', 'installed', 'armed', 'disabled', 'claimed',
    'disconnectAttempts', 'unadviseAttempts', 'disconnected', 'released',
    'rejected', 'activeCallbacks')
_HR_KEYS = ('managerHr', 'managerInterfaceHr', 'enumerationHr', 'nextHr',
    'compartmentHr', 'sourceHr', 'adviseHr', 'unadviseHr')
_API_COUNTS = ('referencesAcquired', 'referencesReleased', 'sinkReferences',
    'badSinkReference', 'enumerationCount', 'invalidCookie', 'variantCleanupFailed',
    'apiException', 'callbackException')
_READ_KEYS = ('hr', 'clearHr', 'type', 'matched', 'attempts')
_CLOCK_KEYS = ('baselineCounter', 'counter', 'finishedCounter', 'deadlineCounter',
    'counterFrequency', 'pluginStarted', 'pluginFinished')
_RETIRE_BOOLS = ('engineExitConfirmed', 'handleReleased', 'engineHandleReleased',
    'retirementSucceeded', 'gracefulShutdownVerified', 'retirementClose')
_RETIRE_CODES = ('shellExitCode', 'commandExitCode', 'engineWaitResult')
_MODE_KEYS = ('status', 'cleanupStatus', 'variantClearHr', 'releaseCalls',
    'referencesAcquired', 'referencesReleased', 'afterOpenHr', 'afterConversionHr',
    'afterOpenType', 'afterConversionType', 'afterOpen', 'afterConversion')
_CONTEXT_KEYS = {'sourceCommit', 'runId', 'runAttempt', 'architecture'}
_TOP_KEYS = _CONTEXT_KEYS | {'schemaVersion', 'kind', 'scopeCode', 'sequence',
    'remainingBudget', 'runtimeCallerProved', 'acceptanceEligible', 'statusCode',
    'reportSuccess', 'case', 'owner', 'callback', 'command3', 'retirement',
    'selection', 'resolution', 'provenance'}
_attempted = False


def _need(condition):
    if not condition:
        raise ValueError('Invalid closed compartment numeric receipt')


def _int(value, maximum=0xffffffff, minimum=0):
    return type(value) is int and minimum <= value <= maximum


def _bool(value):
    return type(value) is bool


def _signed(value):
    return _int(value, 2**31 - 1, -(2**31))


def _digest(value, length=64):
    return type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None and value != '0' * length


def _object(value, keys):
    _need(type(value) is dict and value.keys() == set(keys))


def _get(value, key):
    return value.get(key) if type(value) is dict else None


def _optional(value, key, predicate):
    item = _get(value, key)
    _need(item is None or predicate(item))
    return item


def _enum(value, choices):
    return choices.get(value) if type(value) is str else None


def _context(value):
    _object(value, _CONTEXT_KEYS)
    _need(_digest(value['sourceCommit'], 40) and _int(value['runId'], 2**63 - 1, 1))
    _need(type(value['runAttempt']) is int and value['runAttempt'] == 1)
    _need(type(value['architecture']) is int and value['architecture'] == 0xaa64)
    return dict(value)


def _binding(value, context, *, retirement=False):
    _need(type(value) is dict)
    expected = dict(sourceCommit=context['sourceCommit'], runAttempt='1',
        architecture='arm64', repository='ATLKR/OpenGeul', job='windows-suite')
    expected['sourceRun' if retirement else 'runId'] = str(context['runId'])
    if not retirement:
        branch = 'refs/heads/work/opengeul-office-arm64'
        expected.update(ref=branch,
            workflowRef='ATLKR/OpenGeul/.github/workflows/office-suite.yml@' + branch, event='push')
    _need(all(value.get(k) == v and type(value.get(k)) is str for k, v in expected.items()))


def _owner(native, case=None):
    result = dict(pid=_optional(native, 'officePid', lambda v: _int(v, minimum=1)),
        creationTime=_optional(native, 'officeCreationTime', lambda v: _int(v, 2**64 - 1, 1)),
        tid=_optional(case, 'editorTid', lambda v: _int(v, minimum=1)),
        hwnd=_optional(case, 'keyboardFocusHwnd', lambda v: _int(v, 2**64 - 1, 1)),
        suiteHwnd=_optional(native, 'suiteHwnd', lambda v: _int(v, 2**64 - 1, 1)))
    return None if all(v is None for v in result.values()) else result


def _validate_owner(value):
    if value is None:
        return
    _object(value, _OWNER_KEYS)
    for key in _OWNER_KEYS:
        _need(value[key] is None or _int(value[key], 0xffffffff if key in ('pid', 'tid') else 2**64 - 1, 1))


def _join_owners(*values):
    for value in values:
        _validate_owner(value)
    for key in _OWNER_KEYS:
        known = [v[key] for v in values if v is not None and v[key] is not None]
        _need(not known or all(v == known[0] for v in known))


def _complete_owner(value):
    return value is not None and all(value[k] is not None for k in _OWNER_KEYS)


def _project_callback(raw):
    if raw is None:
        return None
    _need(type(raw) is dict)
    if raw.keys() == {'status', 'cleanupStatus', 'acceptanceEligible',
            'callerAttributionProved', 'processRetirementVerified'}:
        # Actual copied==2/pre-install producer: no ABI row was published.
        _need(raw.get('status') == 'inconclusive' and raw.get('cleanupStatus') == 'unproved')
        _need(all(raw.get(k) is False for k in
            ('callerAttributionProved', 'acceptanceEligible', 'processRetirementVerified')))
    elif raw.keys() == {'status', 'acceptanceEligible', 'errorType'}:
        # Actual finally failure producer. Do not access its exception name.
        _need(raw.get('status') == 'unavailable' and raw.get('acceptanceEligible') is False)
    else:
        _need(raw.get('schemaVersion') == 1 and type(raw.get('schemaVersion')) is int)
        _need(raw.get('kind') == 'one-owned-ime-compartment-callback')
        _need(raw.get('status') != 'unavailable' and raw.get('cleanupStatus') != 'unproved')
        _need(all(raw.get(k) is False for k in
            ('callerAttributionProved', 'acceptanceEligible', 'processRetirementVerified')))
    lease = _get(raw, 'lease'); api = _get(raw, 'api')
    result = dict(statusCode=_enum(raw.get('status'), _CALLBACK_STATUS),
        cleanupCode=_enum(raw.get('cleanupStatus'), _CLEANUP_STATUS),
        claimed=_optional(raw, 'claimed', _bool), rejected=_optional(raw, 'rejected', lambda v: _int(v, 511)),
        expired=_optional(raw, 'expired', _int), foreignRejected=_optional(raw, 'foreignRejected', _int),
        lease=None, api=None, identity=None, clock=None, frames=None,
        frameCount=_optional(raw, 'frameCount', lambda v: _int(v, 16)),
        frameCapReached=_optional(raw, 'frameCapReached', _bool),
        unknownFrames=_optional(raw, 'unknownFrames', lambda v: _int(v, 16)),
        moduleMapVersion=_optional(raw, 'moduleMapVersion', lambda v: type(v) is int and v == 2),
        pluginStatus=_optional(raw, 'pluginStatus', _int))
    if lease is not None:
        _need(type(lease) is dict)
        result['lease'] = {key: lease.get(key) for key in _LEASE_KEYS}
    if api is not None:
        _need(type(api) is dict)
        result['api'] = {key: api.get(key) for key in _HR_KEYS + _API_COUNTS}
        for key in ('baseline', 'callback'):
            read = api.get(key); _need(type(read) is dict)
            result['api'][key] = {k: read.get(k) for k in _READ_KEYS}
    identity_keys = ('pid', 'engineCreationTime', 'tid', 'hwnd')
    if any(raw.get(key) is not None for key in identity_keys):
        result['identity'] = dict(pid=raw.get('pid'), creationTime=raw.get('engineCreationTime'),
            tid=raw.get('tid'), hwnd=raw.get('hwnd'), suiteHwnd=None)
    if any(raw.get(key) is not None for key in _CLOCK_KEYS):
        result['clock'] = {key: raw.get(key) for key in _CLOCK_KEYS}
    frames = _get(raw, 'frames')
    if frames is not None:
        _need(type(frames) is list and len(frames) <= 16)
        result['frames'] = []
        for frame in frames:
            _need(type(frame) is dict)
            result['frames'].append(dict(moduleId=frame.get('moduleId'), rva=frame.get('rva')))
    return result


def _typed(read):
    return read['hr'] == read['clearHr'] == 0 and read['type'] == 3 and read['matched'] == read['attempts'] == 1


def _validate_callback(value):
    if value is None:
        return
    _object(value, ('statusCode', 'cleanupCode', 'claimed', 'rejected', 'expired', 'foreignRejected',
        'lease', 'api', 'identity', 'clock', 'frames', 'frameCount', 'frameCapReached',
        'unknownFrames', 'moduleMapVersion', 'pluginStatus'))
    for key, limit in (('statusCode', 4), ('cleanupCode', 3), ('rejected', 511),
                       ('expired', 0xffffffff), ('foreignRejected', 0xffffffff),
                       ('frameCount', 16), ('unknownFrames', 16), ('pluginStatus', 0xffffffff)):
        _need(value[key] is None or _int(value[key], limit))
    for key in ('claimed', 'frameCapReached'):
        _need(value[key] is None or _bool(value[key]))
    _need(value['moduleMapVersion'] is None or type(value['moduleMapVersion']) is int and value['moduleMapVersion'] == 2)
    if value['statusCode'] == 4 or value['cleanupCode'] == 3:
        _need((value['statusCode'], value['cleanupCode']) in ((4, None), (1, 3)))
        _need(all(value[k] is None for k in ('claimed', 'rejected', 'expired',
            'foreignRejected', 'lease', 'api', 'identity', 'clock', 'frames',
            'frameCount', 'frameCapReached', 'unknownFrames', 'moduleMapVersion', 'pluginStatus')))
    lease, api = value['lease'], value['api']
    if lease is not None:
        _object(lease, _LEASE_KEYS)
        for key in _LEASE_KEYS:
            _need(_int(lease[key], 511 if key == 'rejected' else (0xffffffff if key == 'activeCallbacks' else 1)))
        _need(value['claimed'] is None or value['claimed'] == bool(lease['claimed']))
        _need(value['rejected'] is None or value['rejected'] == lease['rejected'])
    if api is not None:
        _object(api, _HR_KEYS + _API_COUNTS + ('baseline', 'callback'))
        _need(all(_signed(api[k]) for k in _HR_KEYS))
        _need(all(_int(api[k]) for k in _API_COUNTS))
        _need(0 <= api['referencesReleased'] <= api['referencesAcquired'] <= 5 and api['enumerationCount'] <= 64)
        for key in ('baseline', 'callback'):
            read = api[key]; _object(read, _READ_KEYS)
            _need(_signed(read['hr']) and _signed(read['clearHr']) and _int(read['type']))
            _need(_int(read['matched'], 1) and _int(read['attempts'], 1))
    _need((lease is None) == (api is None))
    _validate_owner(value['identity'])
    clock, frames = value['clock'], value['frames']
    published = value['identity'] is not None
    _need(published == (clock is not None) == (frames is not None))
    if published:
        identity = value['identity']
        _need(all(identity[k] is not None for k in ('pid', 'creationTime', 'tid', 'hwnd')) and identity['suiteHwnd'] is None)
        _object(clock, _CLOCK_KEYS)
        _need(all(_int(clock[k], 2**64 - 1, 1) for k in _CLOCK_KEYS))
        _need(0 < clock['baselineCounter'] <= clock['counter'] <= clock['pluginStarted'] <=
            clock['pluginFinished'] <= clock['finishedCounter'] < clock['deadlineCounter'])
        _need(type(frames) is list and len(frames) <= 16 and value['frameCount'] == len(frames))
        for frame in frames:
            _object(frame, ('moduleId', 'rva'))
            _need(_int(frame['moduleId'], 14) and _int(frame['rva']))
            _need(frame['moduleId'] != 0 or frame['rva'] == 0)
            if frame['moduleId'] == 14:
                _need(value['pluginStatus'] == 1 and frame['rva'] >= 4 and frame['rva'] % 4 == 0)
        _need(value['claimed'] is True and value['moduleMapVersion'] == 2)
        _need(value['unknownFrames'] == sum(f['moduleId'] == 0 for f in frames))
        _need(value['frameCapReached'] is (len(frames) == 16))
    else:
        _need(all(value[k] is None for k in ('frameCount', 'frameCapReached', 'unknownFrames', 'moduleMapVersion', 'pluginStatus')))
    source = (lease is not None and all(lease[k] == 1 for k in
        ('installAttempts', 'pinned', 'sourceReady', 'adviseAttempts', 'installed')) and
        all(api[k] == 0 for k in _HR_KEYS[:-1]) and api['referencesAcquired'] == 5 and 1 <= api['enumerationCount'] <= 64)
    failed = (lease is None or lease['rejected'] or lease['activeCallbacks'] or value['expired'] or
        value['foreignRejected'] or any(api[k] for k in ('badSinkReference', 'invalidCookie',
        'variantCleanupFailed', 'apiException', 'callbackException')))
    unsubscribed = (source and not failed and lease['disabled'] == 1 and lease['armed'] == 0 and
        lease['subscriptionPossible'] == 0 and all(lease[k] == 1 for k in
        ('disconnectAttempts', 'unadviseAttempts', 'disconnected', 'released')) and
        api['unadviseHr'] == 0 and api['referencesReleased'] == 5 and api['sinkReferences'] == 1)
    live = (source and lease['armed'] == lease['subscriptionPossible'] == 1 and
        not any(lease[k] for k in ('disabled', 'disconnectAttempts', 'unadviseAttempts', 'disconnected', 'released')) and
        api['referencesReleased'] == 0 and api['sinkReferences'] == 2)
    if value['cleanupCode'] == 2:
        _need(unsubscribed)
    if value['statusCode'] == 3:
        _need(published and not failed and (live or unsubscribed) and
            _typed(api['baseline']) and _typed(api['callback']) and 0 < len(frames) < 16 and value['pluginStatus'] == 1)
    if value['statusCode'] == 2:
        _need(lease is not None and lease['claimed'] == 0 and not published)


def _project_command(case):
    commands = _get(case, 'imeCommands')
    if commands is None:
        return None
    _need(type(commands) is list and len(commands) <= 4)
    matches = [c for c in commands if type(c) is dict and c.get('nativeAck') == 3 and type(c.get('nativeAck')) is int]
    _need(len(matches) <= 1)
    if not matches:
        return None
    c = matches[0]; native = _get(c, 'nativeContext'); mode = _get(c, 'threadMode'); budget = _get(c, 'requestedBudget')
    result = dict(success=_optional(c, 'success', _bool), nativeAck=c['nativeAck'],
        status=_optional(c, 'status', _signed), identity=None,
        modeDeadlineCounter=_optional(c, 'modeDeadlineCounter', lambda v: _int(v, 2**64 - 1, 1)),
        modeCounterFrequency=_optional(c, 'modeCounterFrequency', lambda v: _int(v, 2**64 - 1, 1)),
        requestedCounter=_optional(budget, 'counter', lambda v: _int(v, 2**64 - 1, 1)),
        requestedFrequency=_optional(budget, 'frequency', lambda v: _int(v, 2**64 - 1, 1)),
        mode=None)
    if native is not None:
        result['identity'] = dict(pid=_get(native, 'pid'), creationTime=None, tid=_get(native, 'tid'),
            hwnd=_get(native, 'targetHwnd'), suiteHwnd=_get(native, 'rootHwnd'))
    if mode is not None:
        _need(type(mode) is dict)
        result['mode'] = {k: mode.get(k) for k in _MODE_KEYS}
    return result


def _validate_command(value):
    if value is None:
        return
    _object(value, ('success', 'nativeAck', 'status', 'identity', 'modeDeadlineCounter',
        'modeCounterFrequency', 'requestedCounter', 'requestedFrequency', 'mode'))
    _need(value['success'] is None or _bool(value['success']))
    _need(type(value['nativeAck']) is int and value['nativeAck'] == 3)
    _need(value['status'] is None or _signed(value['status']))
    _validate_owner(value['identity'])
    for key in ('modeDeadlineCounter', 'modeCounterFrequency', 'requestedCounter', 'requestedFrequency'):
        _need(value[key] is None or _int(value[key], 2**64 - 1, 1))
    mode = value['mode']
    if mode is not None:
        _object(mode, _MODE_KEYS)
        for k in _MODE_KEYS:
            signed = k.endswith('Hr') or k in ('status', 'cleanupStatus', 'afterOpen', 'afterConversion')
            _need(_signed(mode[k]) if signed else _int(mode[k]))
        _need(_int(mode['releaseCalls'], 1) and
            _int(mode['referencesAcquired'], 6) and _int(mode['referencesReleased'], 6))


def _project_retirement(case, context):
    session = _get(case, 'imeKeyboardSession'); retirement = _get(case, 'imeEngineRetirement')
    cleanup = _get(case, 'imeFailureCleanup'); admission = _get(retirement, 'admission')
    if session is None and retirement is None and cleanup is None:
        return None
    result = {k: None for k in _RETIRE_BOOLS + _RETIRE_CODES}
    for key in ('engineExitConfirmed', 'handleReleased', 'gracefulShutdownVerified'):
        result[key] = _optional(cleanup, key, _bool)
    result['engineHandleReleased'] = _optional(session, 'engineHandleReleased', _bool)
    result['retirementSucceeded'] = _optional(retirement, 'success', _bool)
    result['retirementClose'] = _optional(_get(retirement, 'close'), 'result', _bool)
    for key in ('shellExitCode', 'commandExitCode'):
        result[key] = _optional(cleanup, key, _int)
    result['engineWaitResult'] = _optional(_get(cleanup, 'engineWait'), 'result', _int)
    result.update(admissionOwner=None, exitOwner=None)
    if admission is not None:
        _binding(_get(admission, 'runBinding'), context, retirement=True)
        result['admissionOwner'] = _owner(_get(admission, 'native'),
            dict(editorTid=_get(admission, 'editorTid'), keyboardFocusHwnd=_get(admission, 'focusHwnd')))
    engine = _get(cleanup, 'engineIdentity')
    if engine is not None:
        result['exitOwner'] = dict(pid=_optional(engine, 'pid', lambda v: _int(v, minimum=1)),
            creationTime=_optional(engine, 'creationTime', lambda v: _int(v, 2**64 - 1, 1)),
            tid=None, hwnd=None, suiteHwnd=None)
        retained = _get(admission, 'extraEngine')
        if retained is not None:
            for key in ('pid', 'creationTime'):
                expected = _optional(retained, key, lambda v: _int(v, 2**64 - 1, 1))
                _need(expected is None or result['exitOwner'][key] == expected)
    return result


def _validate_retirement(value):
    if value is None:
        return
    _object(value, _RETIRE_BOOLS + _RETIRE_CODES + ('admissionOwner', 'exitOwner'))
    for key in _RETIRE_BOOLS:
        _need(value[key] is None or _bool(value[key]))
    for key in _RETIRE_CODES:
        _need(value[key] is None or _int(value[key]))
    _validate_owner(value['admissionOwner']); _validate_owner(value['exitOwner'])
    _join_owners(value['admissionOwner'], value['exitOwner'])


def _project_case(case):
    if case is None:
        return None
    _need(type(case) is dict and case.get('case') == 'ime-writer' and case.get('kind') == 'native-ime-mode-diagnostic')
    failure = _get(case, 'numericFailure'); frames = _get(case, 'numericFailureFrames')
    if failure is not None:
        failure = numeric_notice.validate_failure_code(failure)
    if frames is not None:
        frames = numeric_notice.validate_failure_frames(frames)
    return dict(stageCode=_enum(case.get('stage'), numeric_notice.STAGES),
        success=_optional(case, 'success', _bool), numericFailure=failure,
        ownedFrames=frames, compositionOrdinal=_optional(case, 'imeCompositionOrdinal', lambda v: _int(v, 8, 1)),
        compositionStartEventCount=_optional(case, 'imeCompositionStartEventCount', _int))


def _validate_case(value):
    if value is None:
        return
    _object(value, ('stageCode', 'success', 'numericFailure', 'ownedFrames',
        'compositionOrdinal', 'compositionStartEventCount'))
    _need(value['stageCode'] is None or type(value['stageCode']) is int and value['stageCode'] in numeric_notice.STAGES.values())
    _need(value['success'] is None or _bool(value['success']))
    if value['numericFailure'] is not None:
        numeric_notice.validate_failure_code(value['numericFailure'])
    if value['ownedFrames'] is not None:
        numeric_notice.validate_failure_frames(value['ownedFrames'])
    _need(value['compositionOrdinal'] is None or _int(value['compositionOrdinal'], 8, 1))
    _need(value['compositionStartEventCount'] is None or _int(value['compositionStartEventCount']))


def _project_selection(raw):
    if raw is None:
        return dict(statusCode=None, rvas=[])
    _need(type(raw) is dict and raw.get('runtimeCallerProved') is False and raw.get('acceptanceEligible') is False)
    _need(raw.get('evidenceKind') == 'ime-compartment-callback')
    rvas = raw.get('rvas'); _need(type(rvas) is list and len(rvas) <= 15)
    return dict(statusCode=_enum(raw.get('status'), _SELECTION_STATUS), rvas=list(rvas))


def _project_resolution(raw):
    if raw is None:
        return None
    _need(type(raw) is dict and raw.get('schemaVersion') == 1 and type(raw.get('schemaVersion')) is int)
    _need(raw.get('kind') == 'owned-plugin-symbol-worker' and raw.get('mode') == 'resolve')
    _need(raw.get('runtimeCallerProved') is False and raw.get('acceptanceEligible') is False)
    resolved = _get(raw, 'resolution')
    result = dict(workerSuccess=_optional(raw, 'success', _bool),
        temporaryFilesRemoved=_optional(raw, 'temporaryFilesRemoved', _bool),
        complete=None, cleanupComplete=None, frames=None, dllSha256=None, pdbSha256=None)
    if resolved is None:
        return result
    _need(type(resolved) is dict and resolved.get('kind') == 'local-plugin-symbol-resolution')
    _need(resolved.get('runtimeCallerProved') is False and resolved.get('acceptance') is False)
    _need(resolved.get('functionAliasUniquenessProved') is False and resolved.get('nativeCallsPreemptible') is False)
    result.update(complete=_optional(resolved, 'complete', _bool),
        cleanupComplete=_optional(resolved, 'cleanupComplete', _bool),
        dllSha256=_optional(resolved, 'dllSha256', _digest), pdbSha256=_optional(resolved, 'pdbSha256', _digest))
    frames = _get(resolved, 'frames')
    if frames is not None:
        _need(type(frames) is list and len(frames) <= 15)
        result['frames'] = []
        for frame in frames:
            _need(type(frame) is dict)
            result['frames'].append(dict(returnRva=_get(frame, 'returnRva'), callRva=_get(frame, 'callRva'),
                tagCode=_enum(_get(frame, 'tag'), _TAGS), functionRva=_get(frame, 'functionRva'),
                functionSize=_get(frame, 'functionSize')))
    return result


def _validate_resolution(value):
    if value is None:
        return
    _object(value, ('workerSuccess', 'temporaryFilesRemoved', 'complete', 'cleanupComplete',
        'frames', 'dllSha256', 'pdbSha256'))
    for key in ('workerSuccess', 'temporaryFilesRemoved', 'complete', 'cleanupComplete'):
        _need(value[key] is None or _bool(value[key]))
    for key in ('dllSha256', 'pdbSha256'):
        _need(value[key] is None or _digest(value[key]))
    frames = value['frames']
    if frames is not None:
        _need(type(frames) is list and len(frames) <= 15)
        for frame in frames:
            _object(frame, ('returnRva', 'callRva', 'tagCode', 'functionRva', 'functionSize'))
            _need(_int(frame['returnRva'], minimum=4) and frame['returnRva'] % 4 == 0)
            _need(_int(frame['callRva']) and frame['callRva'] == frame['returnRva'] - 4)
            _need(frame['tagCode'] is None or _int(frame['tagCode'], 8, 1))
            for key in ('functionRva', 'functionSize'):
                _need(frame[key] is None or _int(frame[key]))
            if frame['tagCode'] not in (None, 1):
                _need(frame['functionRva'] is not None and frame['functionSize'] is not None and frame['functionSize'] > 0)
                _need(frame['functionRva'] <= frame['callRva'] < frame['functionRva'] + frame['functionSize'] <= 2**32)
            else:
                _need(frame['functionRva'] is None and frame['functionSize'] is None)
    if value['workerSuccess'] is True:
        _need(value['temporaryFilesRemoved'] is True and value['complete'] is True and value['cleanupComplete'] is True)
        _need(frames is not None and 0 < len(frames) <= 15 and value['dllSha256'] is not None and value['pdbSha256'] is not None)


def _validate(value):
    _object(value, _TOP_KEYS)
    _context({k: value[k] for k in _CONTEXT_KEYS})
    for key, expected in (('schemaVersion', 1), ('kind', KIND), ('scopeCode', SCOPE), ('sequence', 1), ('remainingBudget', 0)):
        _need(type(value[key]) is int and value[key] == expected)
    _need(value['runtimeCallerProved'] is value['acceptanceEligible'] is False)
    _need(value['reportSuccess'] is None or _bool(value['reportSuccess']))
    _need(_int(value['statusCode'], 3))
    _validate_case(value['case']); _validate_owner(value['owner']); _validate_callback(value['callback'])
    _validate_command(value['command3']); _validate_retirement(value['retirement']); _validate_resolution(value['resolution'])
    selection = value['selection']; _object(selection, ('statusCode', 'rvas'))
    _need(selection['statusCode'] is None or _int(selection['statusCode'], 6, 1))
    _need(type(selection['rvas']) is list and len(selection['rvas']) <= 15)
    _need(all(_int(r, minimum=4) and r % 4 == 0 for r in selection['rvas']))
    _need(selection['statusCode'] == 6 or not selection['rvas'])
    proof = value['provenance']; _object(proof, ('dllSha256', 'pdbSha256', 'fileOriginVerified', 'fileOriginReleased'))
    for key in ('dllSha256', 'pdbSha256'):
        _need(proof[key] is None or _digest(proof[key]))
    for key in ('fileOriginVerified', 'fileOriginReleased'):
        _need(proof[key] is None or _bool(proof[key]))
    callback, retirement, command, resolved = (value[k] for k in ('callback', 'retirement', 'command3', 'resolution'))
    _join_owners(value['owner'], _get(callback, 'identity'), _get(retirement, 'admissionOwner'),
        _get(retirement, 'exitOwner'), _get(command, 'identity'))
    if command is not None and callback is not None and callback['clock'] is not None:
        clock = callback['clock']
        for key in ('modeCounterFrequency', 'requestedFrequency'):
            _need(command[key] is None or command[key] == clock['counterFrequency'])
        _need(command['modeDeadlineCounter'] is None or clock['baselineCounter'] < command['modeDeadlineCounter'] <= clock['deadlineCounter'])
        _need(command['requestedCounter'] is None or command['requestedCounter'] == command['modeDeadlineCounter'])
    if resolved is not None:
        for key in ('dllSha256', 'pdbSha256'):
            _need(resolved[key] is None or proof[key] is None or resolved[key] == proof[key])
        if resolved['frames'] is not None:
            _need(selection['statusCode'] == 6 and [f['returnRva'] for f in resolved['frames']] == selection['rvas'])
    selected = selection['statusCode'] == 6
    if selected:
        _need(value['case'] is not None and value['case']['success'] is False and
            value['case']['stageCode'] == numeric_notice.STAGES['physical-dubeolsik-composition'])
        _need(callback is not None and callback['statusCode'] == 3 and callback['cleanupCode'] == 2)
        _need(_complete_owner(value['owner']) and _complete_owner(_get(retirement, 'admissionOwner')))
        _need(retirement['engineExitConfirmed'] is retirement['handleReleased'] is retirement['engineHandleReleased'] is retirement['retirementClose'] is True)
        _need(retirement['retirementSucceeded'] is retirement['gracefulShutdownVerified'] is False)
        _need(retirement['engineWaitResult'] == retirement['commandExitCode'] == 0 and retirement['shellExitCode'] is not None)
        _need(retirement['exitOwner'] is not None and all(retirement['exitOwner'][k] is not None for k in ('pid', 'creationTime')))
        _need(proof['fileOriginVerified'] is proof['fileOriginReleased'] is True and proof['dllSha256'] is not None)
        _need(selection['rvas'] == [f['rva'] for f in callback['frames'] if f['moduleId'] == 14] and selection['rvas'])
        _need(command is not None and command['success'] is True and command['status'] == 0 and command['identity'] is not None)
        _need(all(command['identity'][k] is not None for k in ('pid', 'tid', 'hwnd', 'suiteHwnd')))
        _need(all(command[k] is not None for k in ('modeDeadlineCounter', 'modeCounterFrequency', 'requestedCounter', 'requestedFrequency')))
        mode = command['mode']; _need(mode is not None)
        expected = dict(status=0, cleanupStatus=0, variantClearHr=0, releaseCalls=1,
            afterOpenHr=0, afterConversionHr=0, afterOpenType=3, afterConversionType=3,
            afterOpen=1, afterConversion=1)
        _need(all(mode[k] == v for k, v in expected.items()) and
            mode['referencesAcquired'] == mode['referencesReleased'] == 6)
    expected_status = 3 if selected and resolved is not None and resolved['workerSuccess'] is True and all(f['tagCode'] not in (None, 1) for f in resolved['frames']) else (2 if selected else (1 if callback is not None and callback['statusCode'] == 3 and callback['cleanupCode'] == 2 else 0))
    _need(value['statusCode'] == expected_status)
    return value


def project(report, selection=None, resolution=None, *, context):
    """Select only allowlisted numeric fields; raw input strings are never read."""
    context = _context(context)
    _need(type(report) is dict and type(report.get('schemaVersion')) is int and report['schemaVersion'] == 1)
    _need(report.get('kind') == 'native-ime-mode-diagnostic' and report.get('architecture') == 'arm64')
    _need(report.get('acceptanceEligible') is False and report.get('imeVerified') is False)
    _need(report.get('compartmentCallbackEnabled') is True and report.get('notificationCallerEnabled') is False)
    _need(type(report.get('expectedCaseCount')) is int and report['expectedCaseCount'] == 1)
    _binding(report.get('runBinding'), context)
    tests = report.get('tests'); _need(type(tests) is list and len(tests) <= 1)
    case = tests[0] if tests else None
    callback = _project_callback(_get(case, 'imeCompartmentDiagnostics'))
    selected = _project_selection(selection); resolved = _project_resolution(resolution)
    proof = _get(report, 'pluginFileOrigin')
    provenance = dict(dllSha256=_optional(proof, 'dllSha256', _digest),
        pdbSha256=_get(resolved, 'pdbSha256'),
        fileOriginVerified=_optional(proof, 'verified', _bool),
        fileOriginReleased=_optional(proof, 'released', _bool))
    if selected['statusCode'] == 6:
        # The original selector has already validated the raw input and held
        # CodeView identity. Do not read names, GUIDs, profiles or input payloads.
        identity = _get(selection, 'pluginIdentity')
        _need(_get(identity, 'dllSha256') == provenance['dllSha256'])
    value = dict(context, schemaVersion=1, kind=KIND, scopeCode=SCOPE, sequence=1,
        remainingBudget=0, runtimeCallerProved=False, acceptanceEligible=False,
        reportSuccess=_optional(report, 'success', _bool), statusCode=0,
        case=_project_case(case), owner=_owner(_get(_get(case, 'imeKeyboardSession'), 'expectedNative'), case),
        callback=callback, command3=_project_command(case), retirement=_project_retirement(case, context),
        selection=selected, resolution=resolved, provenance=provenance)
    value['statusCode'] = 3 if selected['statusCode'] == 6 and resolved is not None and resolved['workerSuccess'] is True and resolved['frames'] is not None and all(f['tagCode'] not in (None, 1) for f in resolved['frames']) else (2 if selected['statusCode'] == 6 else (1 if callback is not None and callback['statusCode'] == 3 and callback['cleanupCode'] == 2 else 0))
    return _validate(value)


def encode_notice(value):
    _validate(value)
    message = json.dumps(value, separators=(',', ':'), allow_nan=False)
    _need(len(message.encode('utf-8')) <= MAX_BYTES)
    return message


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result)
        result[key] = value
    return result


def decode_notice(message, expected_source_commit, expected_run_id, *, expected_run_attempt=1, expected_architecture=0xaa64):
    _need(type(message) is str and len(message) <= MAX_BYTES and len(message.encode('utf-8')) <= MAX_BYTES)
    expected = _context(dict(sourceCommit=expected_source_commit, runId=expected_run_id,
        runAttempt=expected_run_attempt, architecture=expected_architecture))
    try:
        value = json.loads(message, object_pairs_hook=_pairs,
            parse_constant=lambda unused: (_ for _ in ()).throw(ValueError('Invalid numeric constant')))
    except (TypeError, ValueError, RecursionError):
        raise ValueError('Invalid closed compartment numeric receipt') from None
    _validate(value)
    _need(all(value[k] == v for k, v in expected.items()))
    return value


def emit_value(value, *, environ=None, stream=None):
    """One attempted notice per process, including failed/partial writes."""
    global _attempted
    try:
        env = os.environ if environ is None else environ
        context = numeric_notice.public_context(env)
        if _attempted or env.get(OPT_IN) != '1' or context is None or context['architecture'] != 0xaa64:
            return False
        message = encode_notice(value)
        decode_notice(message, context['sourceCommit'], context['runId'], expected_architecture=0xaa64)
        _attempted = True
        print('::notice title=' + TITLE + '::' + numeric_notice.escape_data(message), file=stream or sys.stdout, flush=True)
        return True
    except Exception:
        return False


def emit(report, selection=None, resolution=None, *, environ=None, stream=None):
    try:
        env = os.environ if environ is None else environ
        context = numeric_notice.public_context(env)
        if env.get(OPT_IN) != '1' or context is None or context['architecture'] != 0xaa64:
            return False
        return emit_value(project(report, selection, resolution, context=context), environ=env, stream=stream)
    except Exception:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify one bounded numeric callback receipt')
    parser.add_argument('--verify', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--run-id', required=True, type=int)
    parser.add_argument('--run-attempt', type=int, default=1)
    parser.add_argument('--architecture', choices=('arm64',), default='arm64')
    args = parser.parse_args(argv)
    try:
        with open(args.verify, 'rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        _need(len(raw) <= MAX_BYTES)
        decode_notice(raw.decode('utf-8'), args.source_commit, args.run_id,
            expected_run_attempt=args.run_attempt, expected_architecture=0xaa64)
        print('Closed numeric compartment receipt verified')
        return 0
    except Exception:
        print('Closed numeric compartment receipt rejected', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
