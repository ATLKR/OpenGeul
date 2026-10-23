"""One source-bound CtrlHome selection barrier before the existing Calc F2.

The original shared setup deadline and existing initial-selection-v2 reader
remain authoritative. A failed observation never causes another key or read.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import time

import calc_model_barrier
from calc_pending_input import require_pending_receipt
from calc_save_smoke import require_pending_observation
from counted_editor_shortcuts import input_buffer, shortcut_events
from ime_calc_setup import NATIVE_KEYS, _error, _time
from ime_semantic_context import MAX_CONTEXT_BYTES, _encode_inventory, _inventory
from writer_model_barrier import _path
from writer_model_reader import (CALC_PENDING_INITIAL_GETTER_CONTRACT,
    OwnedModelReader, require_calc_a1_selection, require_calc_pending_program_phase,
    require_model_reader_cleanup, _same_selection_fact)

KIND = 'ime-calc-pre-edit-navigation'


def _size(context):
    assert len(json.dumps(context, ensure_ascii=False, allow_nan=False).encode()) <= MAX_CONTEXT_BYTES, 'Calc navigation receipt exceeds original semantic context cap'


def _row(context, row, *, suite, sequence, expected_url):
    assert context['expectedUrl'] == expected_url, 'Calc navigation document URL changed'
    native = context['expectedNative']
    assert isinstance(native, dict) and set(native) == NATIVE_KEYS
    for key in NATIVE_KEYS - {'expectedImage'}:
        assert type(native[key]) is int and native[key] > 0
    binding = row['bindingBefore']
    for key in NATIVE_KEYS:
        if key == 'expectedImage':
            assert _path(binding[key]) == _path(native[key]) == _path(str(suite)) / 'Office/program/soffice.bin'
        else:
            assert type(binding[key]) is int and binding[key] == native[key], 'Calc navigation native generation changed: ' + key
    require_calc_pending_program_phase(row, expected_action='start' if sequence == 0 else 'read',
        expected_sequence=sequence, expected_phase='initial' if sequence == 0 else 'strict')
    require_pending_observation(row, row, context['baseline'], suite=suite,
        inventory=_inventory(context), inventory_sha256=context['inventorySha256'],
        original_shell=context['originalShell'], expected_url=expected_url,
        deadline=context['readerDeadline'], getter_contract=CALC_PENDING_INITIAL_GETTER_CONTRACT)
    assert context['startedAt'] <= _time(row['readStartedAt']) <= _time(row['readFinishedAt']) <= context['readerDeadline']
    assert row['pendingInput']['editor'] is None, 'Calc navigation must precede the original F2 edit entry'
    return row


def _selected(context, *, suite, expected_url):
    initial = _row(context, context['initial'], suite=suite, sequence=0, expected_url=expected_url)
    selected = _row(context, context['afterCtrlHome'], suite=suite, sequence=1, expected_url=expected_url)
    require_pending_observation(initial, selected, context['baseline'], suite=suite,
        inventory=_inventory(context), inventory_sha256=context['inventorySha256'],
        original_shell=context['originalShell'], expected_url=expected_url,
        deadline=context['readerDeadline'], getter_contract=CALC_PENDING_INITIAL_GETTER_CONTRACT)
    require_calc_a1_selection(selected['calcSelection'])
    require_pending_receipt(selected['pendingInput'], selected['bindingBefore']['childHwnd'],
        previous=initial['pendingInput'])
    home = context['homeCommand']
    assert home['shortcut'] == 'CTRL_HOME'
    assert _time(home['deadline']) == context['readerDeadline'], 'Calc CtrlHome deadline differs from its original reader phase'
    assert all(type(home[key]) is int and home[key] == value for key, value in
        [('requestedInputs', 4), ('insertedInputs', 4), ('inputCallAttempts', 1)])
    assert _same_selection_fact(home['events'], shortcut_events('CTRL_HOME'))
    assert home['bufferHex'] == bytes(input_buffer(home['events'])).hex()
    for edge in ('before', 'after'):
        for role, pid_key, birth_key, image in (
            ('shell', 'shellPid', 'shellCreationTime', _path(str(suite)) / 'OpenGeul.Office.exe'),
            ('engine', 'officePid', 'officeCreationTime', _path(context['expectedNative']['expectedImage']))):
            native = home[edge][role]
            assert type(native['pid']) is int and native['pid'] == context['expectedNative'][pid_key]
            assert type(native['creationTime']) is int and native['creationTime'] == context['expectedNative'][birth_key]
            assert _path(native['image']) == image and type(native['waitResult']) is int and native['waitResult'] == 258
            assert type(native['handleValue']) is int and native['handleValue'] > 0
            assert native['handleValue'] == home['before'][role]['handleValue']
    assert (initial['readFinishedAt'] <= _time(home['startedAt']) <= _time(home['finishedAt'])
            <= selected['readStartedAt']), 'Calc source selection must follow its single physical CtrlHome'
    return selected


def require_calc_navigation(context, *, suite, expected_native, expected_url, setup_deadline, now):
    """Pure replay: a success flag cannot replace either RPC or its release."""
    _size(context)
    assert type(context.get('schemaVersion')) is int and context['schemaVersion'] == 1
    assert context.get('kind') == KIND and context.get('success') is True
    assert _same_selection_fact(context.get('expectedNative'), expected_native)
    start, deadline = _time(context['startedAt']), _time(context['readerDeadline'])
    assert context['setupDeadline'] == setup_deadline
    assert deadline == min(_time(setup_deadline), start + calc_model_barrier.MAX_SECONDS)
    assert start < deadline and context['cleanupErrors'] == [] and context['nativeImeObserved'] is False
    original = bytes.fromhex(context['sourceBytesHex'])
    assert _same_selection_fact(calc_model_barrier.baseline_from_ooxml(original), context['baseline'])
    assert context['diskBeforeSha256'] == context['diskAfterSha256'] == context['baseline']['sourceSha256']
    selected = _selected(context, suite=suite, expected_url=expected_url)
    require_model_reader_cleanup(context['cleanup'], selected['bindingBefore'], deadline,
        expected_service=calc_model_barrier.SERVICE, getter_contract=CALC_PENDING_INITIAL_GETTER_CONTRACT)
    assert (selected['readFinishedAt'] <= _time(context['cleanup']['startedAt'])
            <= _time(context['cleanup']['finishedAt']) <= _time(context['finishedAt'])
            <= _time(now) < _time(setup_deadline))
    assert context['finishedAt'] <= deadline, 'Calc navigation renewed its reader deadline'
    return context


def observe_calc_navigation(suite, source, original_bytes, record, setup_deadline, *,
        original_shell, expected_native, require_current, send_home,
        reader_factory=None, clock=time.monotonic):
    """Own exactly start0, one CtrlHome, read1, and one release under one bound."""
    suite, source = Path(suite), Path(source)
    expected_url = source.as_uri()
    assert 'calcNavigationContext' not in record, 'Calc navigation cannot repeat'
    started = _time(clock())
    deadline = min(_time(setup_deadline), started + calc_model_barrier.MAX_SECONDS)
    assert started < deadline
    context = dict(schemaVersion=1, kind=KIND, success=False, startedAt=started,
        setupDeadline=setup_deadline, readerDeadline=deadline,
        expectedNative=copy.deepcopy(expected_native), expectedUrl=expected_url,
        originalShell=copy.deepcopy(original_shell), cleanupErrors=[], nativeImeObserved=False)
    record['calcNavigationContext'] = context
    reader = initial = selected = primary = None
    cleanup_errors = []
    def current():
        assert _time(clock()) < deadline, 'Original Calc navigation reader deadline expired'
        require_current()
        assert _time(clock()) < deadline, 'Original Calc navigation reader deadline expired'
    try:
        current()
        assert not record.get('asciiPrefix') and not record.get('asciiEditorInputs')
        context['baseline'] = calc_model_barrier.baseline_from_ooxml(original_bytes)
        context['sourceBytesHex'] = original_bytes.hex()
        assert source.is_file() and not source.is_symlink()
        context['diskBeforeSha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        assert context['diskBeforeSha256'] == context['baseline']['sourceSha256']
        from writer_style_smoke import _packaged_identity_file
        identity, raw = _packaged_identity_file(suite, 'suite-inventory.json')
        context.update(inventoryEvidence=_encode_inventory(raw), inventorySha256=identity['sha256'])
        _size(context); current()
        factory = OwnedModelReader if reader_factory is None else reader_factory
        reader = factory(suite, source.parent / 'ime-calc-navigation-reader',
            expected_service=calc_model_barrier.SERVICE, getter_contract=CALC_PENDING_INITIAL_GETTER_CONTRACT,
            shell_pid=expected_native['shellPid'], expected_shell_creation=expected_native['shellCreationTime'],
            suite_hwnd=expected_native['suiteHwnd'], parent_hwnd=expected_native['parentHwnd'],
            child_hwnd=expected_native['childHwnd'], office_pid=expected_native['officePid'],
            expected_url=expected_url, clock=clock)
        current(); context['readerStartAttempted'] = True
        initial = context['initial'] = reader.start(deadline)
        _row(context, initial, suite=suite, sequence=0, expected_url=expected_url); _size(context); current()
        context['homeCommand'] = send_home()
        current()
        selected = context['afterCtrlHome'] = reader.read(deadline)
        _selected(context, suite=suite, expected_url=expected_url); _size(context); current()
    except BaseException as exc:
        primary = exc; context['error'] = _error(exc)
        raise
    finally:
        if reader is not None:
            try:
                context['cleanup'] = reader.close(deadline)
                if initial is not None:
                    require_model_reader_cleanup(context['cleanup'], initial['bindingBefore'], deadline,
                        expected_service=calc_model_barrier.SERVICE,
                        getter_contract=CALC_PENDING_INITIAL_GETTER_CONTRACT)
            except BaseException as exc:
                cleanup_errors.append(exc); context['cleanupErrors'].append(_error(exc))
        if primary is None and not cleanup_errors:
            try:
                current()
                context['diskAfterSha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
                context['finishedAt'] = _time(clock())
                context['success'] = True
                require_calc_navigation(context, suite=suite, expected_native=expected_native, expected_url=expected_url,
                    setup_deadline=setup_deadline, now=clock())
            except BaseException as exc:
                context['success'] = False
                cleanup_errors.append(exc); context['cleanupErrors'].append(_error(exc))
        if primary is None and cleanup_errors:
            context['error'] = _error(cleanup_errors[0])
            raise cleanup_errors[0]
    return context
