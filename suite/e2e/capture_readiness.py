"""Wait only for measured owned mouse capture to settle; never change input state."""
from __future__ import annotations

import time


def settle_owned_capture(observe, validate, receipt, binding, deadline, *, clock=time.monotonic, pause=None):
    """Return a capture-free observation under the caller's original deadline.

    observe returns the complete native guard observation (including ``scope``).
    validate must enforce every caller-specific non-capture guard on every sample.
    Its exceptions are fatal. No keyboard, mouse, focus or capture action occurs.
    The diagnostic ledger stores only its first and latest full observations.
    """
    if pause is None: pause = time.sleep
    pending = False
    while True:
        assert clock() < deadline, 'Owned capture readiness deadline expired'
        row = observe()
        receipt['lastGuardObservation'] = row  # Preserve a rejected fresh scope, never the previous one.
        assert clock() < deadline, 'Owned capture readiness deadline expired after native observation'
        validate(row)
        assert clock() < deadline, 'Owned capture readiness deadline expired after validation'
        scope = row['scope']; capture = scope['capture']; hwnd = capture['hwnd']
        assert type(hwnd) is int and hwnd >= 0, 'Invalid native capture observation'
        if pending:
            ledger['last'] = row; ledger['lastObservedAt'] = clock()
        if hwnd == 0:
            if pending: ledger['settledAt'] = clock()
            assert clock() < deadline, 'Owned capture readiness deadline expired at settlement'
            return row
        assert capture.get('isWindow') is True and capture.get('rootHwnd') == binding['suiteHwnd'], 'Unknown, foreign or dead native capture cannot settle'
        expected = {binding['shellPid']: scope['before']['suite']['threadId'],
                    binding['officePid']: scope['before']['editor']['threadId']}
        assert capture.get('pid') in expected and capture.get('threadId') == expected[capture['pid']] > 0, 'Native capture process/thread is not the retained document'
        if not pending:
            ledger = receipt.setdefault('captureReadiness', dict(waitCount=0,pollCount=0,startedAt=clock(),
                lastObservedAt=clock(),first=row,last=row,settledAt=None,deadline=deadline))
            ledger.update(waitCount=ledger['waitCount']+1,last=row,lastObservedAt=clock(),settledAt=None,deadline=deadline)
            pending = True
        remaining = deadline-clock()
        assert remaining > 0, 'Owned capture readiness deadline expired'
        pause(min(.05,remaining))
        ledger['pollCount'] += 1
