"""Finite owned-thread queue progress, never proof of document insertion.

One observer surrounds the original ASCII input plan. It neither sends keys nor
changes focus, layout or deadlines. Native acquisition lives behind one typed
boundary; the same sequencing policy is exercised with portable test doubles.
"""
from __future__ import annotations

import copy
import math
import time

from ascii_message_progress import CharacterProgress, MAX_CHARACTER_EVENTS
from ascii_queue_readiness import MAX_QUERIES, retain_sample, require_initial_queue_sample


def _error(exc):
    return type(exc).__name__ + ': ' + str(exc)[:1024]


class OwnedAsciiObserver:
    def __init__(self, api, original_popen, native_binding, prepared_library,
                 record, deadline, *, clock=time.monotonic, pause=time.sleep,
                 probe=None):
        assert type(deadline) in (int, float) and math.isfinite(deadline), 'Invalid ASCII observer deadline'
        self.api, self.process = api, original_popen
        self.binding, self.prepared = dict(native_binding), prepared_library
        self.deadline, self.clock, self.pause = deadline, clock, pause
        self.probe = probe
        self.last_time = None
        self.active = self.closed = self.finished = False
        self.failed = None
        self.pending = self.target = None
        self.sequence = 0
        self.receipt = dict(schemaVersion=1, kind='owned-ascii-queue-progress',
            deadline=deadline, expectedBinding=dict(native_binding), actions=[],
            preparedLibrary=copy.deepcopy(prepared_library),
            cleanupErrors=[], success=False, semanticInsertionProved=False,
            remoteCallbackQuiescenceProved=False,
            attribution='bounded target/epoch/scan/text correlation; original INPUT extraInfo0 is not a unique tag')
        record.setdefault('asciiMessageObservers', []).append(self.receipt)

    def _now(self):
        value = self.clock()
        assert type(value) in (int, float) and math.isfinite(value), 'Invalid ASCII observer clock'
        assert self.last_time is None or value >= self.last_time, 'ASCII observer clock regressed'
        self.last_time = value
        return value

    def _budget(self):
        value = self._now()
        assert value < self.deadline, 'ASCII observer deadline expired'
        return self.deadline - value

    def _guard(self):
        self._budget()
        row = self.probe.guard()
        self.receipt['lastTargetObservation'] = copy.deepcopy(row)
        assert row == self.target, 'Original ASCII observer target changed'
        self._budget()
        return row

    def _require_active(self):
        try:
            assert self.failed is None, 'ASCII observer already failed'
            assert self.active and not self.closed and not self.finished, 'ASCII observer is not active'
        except BaseException as exc:
            if self.failed is None: self.failed = _error(exc)
            raise

    def __enter__(self):
        assert not self.active and not self.closed, 'ASCII observer cannot restart'
        try:
            self.receipt['startedAt'] = self._now()
            self._budget()
            if self.probe is None:
                from ascii_message_windows import NativeAsciiProbe
                self.probe = NativeAsciiProbe(self.api, self.process, self.binding,
                    self.prepared, self.receipt, self.deadline, self._now)
            self.target = dict(self.probe.admit())
            self.receipt['originalTarget'] = copy.deepcopy(self.target)
            self._guard()
            self.probe.start()
            self._guard()
            ledger = dict(deadline=self.deadline, startedAt=self._now(), pollCount=0,
                first=[], last=[], ready=False, semanticInsertionProved=False,
                limitation='Nonconsuming target-thread queue/key snapshot; GetQueueStatus changes newness bookkeeping, not dispatch/semantic proof.')
            self.receipt['initialQueueReadiness'] = ledger
            previous_tick = None
            while True:
                assert ledger['pollCount'] < MAX_QUERIES, 'Initial ASCII queue observation bound exceeded'
                self._guard()
                row = self.probe.query_initial_readiness()
                retain_sample(ledger, row)
                self._budget()
                self._guard()
                ready = require_initial_queue_sample(row, self.target,
                    self.binding['officeCreationTime'], request=ledger['pollCount'])
                assert previous_tick is None or row['tickStarted'] >= previous_tick, 'Initial ASCII queue native time regressed'
                previous_tick = row['tickFinished']
                if ready:
                    ready_at = self._now()
                    self._budget()
                    ledger.update(ready=True, readyAt=ready_at)
                    break
                self.pause(min(.01, self._budget()))
            self.active = True
            return self
        except BaseException as exc:
            self.failed = _error(exc)
            self._close(exc)
            raise

    def arm(self, action):
        self._require_active()
        try:
            assert self.pending is None, 'Previous ASCII character is incomplete'
            assert action['index'] == len(self.receipt['actions']), 'ASCII observer action order changed'
            self._guard()
            baseline = self.probe.arm(action['index'])
            assert type(baseline) is int and baseline == self.sequence, 'ASCII observer queue baseline changed'
            self._budget()
            progress = CharacterProgress(action, self.target, baseline)
            row = dict(intent=copy.deepcopy(action), baselineSequence=baseline,
                       observations=[], pollCount=0, complete=False)
            self.receipt['actions'].append(row)
            self.pending = progress
            return row
        except BaseException as exc:
            self.failed = _error(exc)
            raise

    def await_progress(self, action):
        self._require_active()
        try:
            assert self.pending is not None and self.pending.action == action, 'ASCII observer has a different armed action'
            row = self.receipt['actions'][-1]
            while True:
                self._guard()
                rows = self.probe.read_events(self.pending.sequence)
                assert type(rows) is list, 'Invalid ASCII observer readback'
                row['pollCount'] += 1
                assert row['pollCount'] <= 8192, 'ASCII observer read-only polling bound exceeded'
                # Retain the raw evidence before its validation, including the
                # exact rejected character. The policy bounds each action.
                limit = MAX_CHARACTER_EVENTS - len(row['observations'])
                row['observations'].extend(copy.deepcopy(rows[:limit]))
                assert len(rows) <= limit, 'ASCII character observation bound exceeded'
                proof = self.pending.observe(rows)
                self._budget()
                if proof is not None:
                    self._guard()
                    row.update(complete=True, proof=proof)
                    self.sequence = self.pending.sequence
                    self.pending = None
                    return proof
                self.pause(min(.01, self._budget()))
        except BaseException as exc:
            self.failed = _error(exc)
            raise

    def finish(self, expected_count):
        self._require_active()
        try:
            assert type(expected_count) is int and 1 <= expected_count <= 256, 'Invalid ASCII observer plan length'
            assert self.pending is None and len(self.receipt['actions']) == expected_count, 'Incomplete ASCII observer plan'
            assert all(row['complete'] is True for row in self.receipt['actions']), 'Incomplete ASCII observer action'
            self._guard()
            self.finished = True
        except BaseException as exc:
            self.failed = _error(exc)
            raise

    def _close(self, primary):
        if self.closed:
            return
        self.closed = True
        cleanup_error = None
        if self.probe is not None:
            try:
                # Cleanup never renews input authority. On expiry no new inert
                # message is sent, but every installed hook/resource is closed.
                can_stop = self.probe.can_stop()
                assert primary is not None or not self.active or can_stop, 'ASCII observer cannot acknowledge stop after a complete plan'
                if can_stop:
                    self._budget()
                    self._guard()
                    self.receipt['stop'] = self.probe.stop()
                    assert self.receipt['stop']['recordingStopped'] is True, 'ASCII observer stop was not acknowledged'
                    self._budget()
            except BaseException as exc:
                cleanup_error = exc
                self.receipt['cleanupErrors'].append(_error(exc))
            finally:
                try:
                    self.receipt['cleanup'] = self.probe.close()
                    assert self.receipt['cleanup']['controllerResourcesReleased'] is True, 'ASCII observer controller resources were not released'
                    assert self.receipt['cleanup']['engineHandleReleased'] is True, 'ASCII observer engine HANDLE was not released'
                    self._budget()
                except BaseException as exc:
                    if cleanup_error is None: cleanup_error = exc
                    self.receipt['cleanupErrors'].append(_error(exc))
        self.active = False
        if primary is not None:
            self.receipt['error'] = _error(primary)
        elif cleanup_error is not None:
            self.failed = _error(cleanup_error)
            self.receipt['error'] = self.failed
            raise cleanup_error
        elif self.failed is not None:
            self.receipt['error'] = self.failed
            raise AssertionError('ASCII observer already failed: ' + self.failed)
        else:
            assert self.finished, 'Incomplete ASCII observer session'
            finished = self._now()
            assert finished < self.deadline, 'ASCII observer deadline expired at final timestamp'
            self.receipt.update(success=True, finishedAt=finished)

    def __exit__(self, exc_type, exc, traceback):
        if exc is not None: self.failed = _error(exc)
        self._close(exc)
        return False
