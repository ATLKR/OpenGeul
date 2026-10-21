"""One bounded, getter-only Calc context before the native IME observer.

The observation is measured after the physical ASCII setup prefix. It is not
an earlier before-input observation or a manufactured navigation history.
"""
from __future__ import annotations

import hashlib
import copy
import json
import math
from pathlib import Path
import time

import calc_model_barrier
from calc_pending_input import require_pending_receipt
from calc_save_smoke import require_uncommitted_cells
from writer_model_barrier import _path, require_original_shell, require_python_identity
from writer_model_reader import (CALC_PENDING_GETTER_CONTRACT, OwnedModelReader,
    require_calc_a1_selection, require_model_reader_cleanup,
    require_owned_model_observation)


PREFIX = ' ime-opengeul-calc:'
NATIVE_KEYS = frozenset(('shellPid', 'shellCreationTime', 'officePid',
    'officeCreationTime', 'expectedImage', 'suiteHwnd', 'parentHwnd',
    'childHwnd', 'rootHwnd'))


def _time(value):
    assert type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Invalid IME setup time'
    return float(value)


def _error(exc):
    return type(exc).__name__[:80] + ': ' + str(exc)[:1024]


def validate_calc_setup(observation, *, suite, baseline, prefix, inventory,
                        inventory_sha256, original_shell, expected_native,
                        expected_url, started_at, deadline):
    """Validate exactly one retained model/selection/pending-buffer observation."""
    start, end = _time(started_at), _time(deadline)
    assert start < end, 'Calc IME observation has no remaining setup budget'
    assert prefix == PREFIX, 'Calc IME setup prefix differs from its exact ASCII contract'
    assert isinstance(expected_native, dict) and set(expected_native) == NATIVE_KEYS, 'Incomplete first native admission projection'
    for key in NATIVE_KEYS - {'expectedImage'}:
        assert type(expected_native[key]) is int and expected_native[key] > 0, 'Invalid first native admission: ' + key
    assert expected_native['suiteHwnd'] == expected_native['rootHwnd']
    assert expected_native['shellPid'] != expected_native['officePid']
    assert _path(expected_native['expectedImage']) == _path(str(suite)) / 'Office/program/soffice.bin'
    binding = observation['bindingBefore']
    for key in NATIVE_KEYS:
        if key == 'expectedImage':
            assert _path(binding[key]) == _path(expected_native[key]), 'Calc reader image differs from first admission'
        else:
            assert type(binding[key]) is int and binding[key] == expected_native[key], 'Calc reader differs from first native admission: ' + key
    assert binding['documentUrl'] == expected_url, 'Calc IME reader document URL differs'
    require_owned_model_observation(observation, binding, suite,
        expected_service=calc_model_barrier.SERVICE,
        getter_contract=CALC_PENDING_GETTER_CONTRACT)
    require_original_shell(original_shell, binding, suite)
    require_python_identity(observation['pythonIdentity'], suite, inventory, inventory_sha256)
    assert start <= _time(observation['readStartedAt']) <= _time(observation['readFinishedAt']) <= end, 'Calc IME observation is stale or outside setup deadline'
    require_uncommitted_cells(observation, baseline)
    require_calc_a1_selection(observation['calcSelection'])
    require_pending_receipt(observation['pendingInput'], binding['childHwnd'],
        baseline['a1Text'] + prefix, require_editor=True)
    return observation


def observe_calc_setup(suite, source, original_bytes, record, setup_deadline, *,
                       original_shell, expected_native, require_current,
                       reader_factory=None, clock=time.monotonic):
    """Own one existing reader and prove its natural cleanup before returning.

    A failed/partial launch is still closed once. The original failure remains
    primary and any secondary cleanup failure remains in the case evidence.
    """
    suite, source = Path(suite), Path(source)
    started = _time(clock())
    setup_deadline = _time(setup_deadline)
    assert started < setup_deadline, 'Calc IME setup deadline expired'
    deadline = min(setup_deadline, started + calc_model_barrier.MAX_SECONDS)
    context = dict(schemaVersion=1, kind='ime-calc-single-observation-setup',
        success=False, startedAt=started, setupDeadline=setup_deadline,
        readerDeadline=deadline, expectedNative=dict(expected_native),
        expectedUrl=source.as_uri(), expectedPrefix=PREFIX,
        originalShell=copy.deepcopy(original_shell),
        cleanupErrors=[], nativeImeObserved=False)
    record['calcSetupContext'] = context
    reader = observation = None
    primary = None
    cleanup_failures = []
    try:
        require_current()
        assert record.get('asciiPrefix') == PREFIX, 'Calc IME ASCII prefix was not established before context observation'
        baseline = calc_model_barrier.baseline_from_ooxml(original_bytes)
        assert source.is_file() and not source.is_symlink(), 'Owned Calc IME copy is missing or linked'
        assert hashlib.sha256(source.read_bytes()).hexdigest() == baseline['sourceSha256'], 'Calc IME file changed before its setup observation'
        from writer_style_smoke import _packaged_identity_file
        identity, raw = _packaged_identity_file(suite, 'suite-inventory.json')
        inventory = json.loads(raw)
        context.update(baseline=baseline, inventorySha256=identity['sha256'])
        assert _time(clock()) < deadline, 'Calc IME setup budget expired before reader construction'
        factory = OwnedModelReader if reader_factory is None else reader_factory
        reader = factory(suite, source.parent / 'ime-setup-reader',
            expected_service=calc_model_barrier.SERVICE,
            getter_contract=CALC_PENDING_GETTER_CONTRACT,
            shell_pid=expected_native['shellPid'],
            expected_shell_creation=expected_native['shellCreationTime'],
            suite_hwnd=expected_native['suiteHwnd'],
            parent_hwnd=expected_native['parentHwnd'],
            child_hwnd=expected_native['childHwnd'],
            office_pid=expected_native['officePid'],
            expected_url=source.as_uri(), clock=clock)
        context['readerStartAttempted'] = True
        observation = reader.start(deadline)
        context['observation'] = observation
        validate_calc_setup(observation, suite=suite, baseline=baseline,
            prefix=record['asciiPrefix'], inventory=inventory,
            inventory_sha256=identity['sha256'], original_shell=original_shell,
            expected_native=expected_native, expected_url=source.as_uri(),
            started_at=started, deadline=deadline)
    except BaseException as exc:
        primary = exc
        context['error'] = _error(exc)
        raise
    finally:
        if reader is not None:
            try:
                context['cleanup'] = reader.close(deadline)
                if observation is not None:
                    require_model_reader_cleanup(context['cleanup'],
                        observation['bindingBefore'], deadline,
                        expected_service=calc_model_barrier.SERVICE,
                        getter_contract=CALC_PENDING_GETTER_CONTRACT)
                    assert (_time(observation['readFinishedAt'])
                        <= _time(context['cleanup']['startedAt'])
                        <= _time(context['cleanup']['finishedAt']) <= deadline), 'Calc IME reader cleanup order differs from its single observation'
            except BaseException as exc:
                cleanup_failures.append(exc)
                context['cleanupErrors'].append(_error(exc))
        if primary is None and not cleanup_failures:
            try:
                assert hashlib.sha256(source.read_bytes()).hexdigest() == baseline['sourceSha256'], 'Calc IME file changed during its read-only setup observation'
                require_current()
                context['finishedAt'] = _time(clock())
                assert (_time(context['cleanup']['finishedAt'])
                    <= context['finishedAt'] <= deadline), 'Calc IME final context order or original deadline differs'
                context['success'] = True
            except BaseException as exc:
                cleanup_failures.append(exc)
                context['cleanupErrors'].append(_error(exc))
        if primary is None and cleanup_failures:
            context['error'] = _error(cleanup_failures[0])
            raise cleanup_failures[0]
    return context
