"""Wait only for measured owned mouse capture to settle; never change input state."""
from __future__ import annotations

import time

_CAPTURE_INVOCATIONS = []  # No diagnostic additions to the bounded native receipt JSON.


def current_capture_invocation(receipt):
    try:
        return next((current for original,current in reversed(_CAPTURE_INVOCATIONS) if receipt is original),None)
    except BaseException:
        return None


def _diagnostic_start(receipt, deadline):
    try:
        current = dict(schemaVersion=1, kind='owned-capture-readiness-invocation', deadline=deadline,
            observationPresent=False, validationReturned=False, ownedPositiveCapturePending=False,
            timeoutPhase=0)
        _CAPTURE_INVOCATIONS.append((receipt,current))
        del _CAPTURE_INVOCATIONS[:-32]
        return current
    except BaseException:
        return None


def _diagnostic_update(current, **values):
    try:
        if current is not None:
            if 'lastCheckedAt' in values and 'firstCheckedAt' not in current:
                current['firstCheckedAt'] = values['lastCheckedAt']
            current.update(values)
    except BaseException:
        pass


def _diagnostic_bind(receipt, current, primary):
    try:
        if current is not None and current_capture_invocation(receipt) is current:
            primary.opengeul_capture_invocation = current
            primary.opengeul_capture_observation = (receipt.get('lastGuardObservation')
                if current.get('observationPresent') is True else None)
    except BaseException:
        pass


def settle_owned_capture(observe, validate, receipt, binding, deadline, *, clock=time.monotonic, pause=None):
    """Return a capture-free observation under the caller's original deadline.

    observe returns the complete native guard observation (including ``scope``).
    validate must enforce every caller-specific non-capture guard on every sample.
    Its exceptions are fatal. No keyboard, mouse, focus or capture action occurs.
    The diagnostic ledger stores only its first and latest full observations.
    """
    if pause is None: pause = time.sleep
    pending = False; current = _diagnostic_start(receipt, deadline)
    try:
        while True:
            checked_at = clock(); within = checked_at < deadline
            _diagnostic_update(current,lastCheckedAt=checked_at,timeoutPhase=0 if within else 1)
            assert within, 'Owned capture readiness deadline expired'
            row = observe()
            _diagnostic_update(current,observationPresent=True,validationReturned=False,
                ownedPositiveCapturePending=False)
            receipt['lastGuardObservation'] = row  # Preserve a rejected fresh scope, never the previous one.
            checked_at = clock(); within = checked_at < deadline
            _diagnostic_update(current,lastCheckedAt=checked_at,timeoutPhase=0 if within else 2)
            assert within, 'Owned capture readiness deadline expired after native observation'
            validate(row)
            _diagnostic_update(current,validationReturned=True)
            checked_at = clock(); within = checked_at < deadline
            _diagnostic_update(current,lastCheckedAt=checked_at,timeoutPhase=0 if within else 3)
            assert within, 'Owned capture readiness deadline expired after validation'
            scope = row['scope']; capture = scope['capture']; hwnd = capture['hwnd']
            assert type(hwnd) is int and hwnd >= 0, 'Invalid native capture observation'
            if pending:
                ledger['last'] = row; ledger['lastObservedAt'] = clock()
            if hwnd == 0:
                if pending: ledger['settledAt'] = clock()
                checked_at = clock(); within = checked_at < deadline
                _diagnostic_update(current,lastCheckedAt=checked_at,timeoutPhase=0 if within else 4)
                assert within, 'Owned capture readiness deadline expired at settlement'
                return row
            assert capture.get('isWindow') is True and capture.get('rootHwnd') == binding['suiteHwnd'], 'Unknown, foreign or dead native capture cannot settle'
            expected = {binding['shellPid']: scope['before']['suite']['threadId'],
                        binding['officePid']: scope['before']['editor']['threadId']}
            assert capture.get('pid') in expected and capture.get('threadId') == expected[capture['pid']] > 0, 'Native capture process/thread is not the retained document'
            _diagnostic_update(current,ownedPositiveCapturePending=True)
            if not pending:
                ledger = receipt.setdefault('captureReadiness', dict(waitCount=0,pollCount=0,startedAt=clock(),
                    lastObservedAt=clock(),first=row,last=row,settledAt=None,deadline=deadline))
                ledger.update(waitCount=ledger['waitCount']+1,last=row,lastObservedAt=clock(),settledAt=None,deadline=deadline)
                pending = True
            checked_at = clock(); remaining = deadline-checked_at; within = remaining > 0
            _diagnostic_update(current,lastCheckedAt=checked_at,timeoutPhase=0 if within else 5)
            assert within, 'Owned capture readiness deadline expired'
            pause(min(.05,remaining))
            ledger['pollCount'] += 1
    except BaseException as primary:
        _diagnostic_bind(receipt,current,primary)
        raise
