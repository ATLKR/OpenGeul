"""Compare held Writer guard/rejection data; never query or change native state.

The vector is [presence mask, post-guard capture zero, same queried thread,
raw capture handle relation, session finish within its original input deadline].
Mask bits 0..3 correspond to the four values. Handle relations are 1 original
child, 2 previous focus, 3 original parent, 4 original Suite, 5 other nonzero.
They compare numbers only: no capture owner, generation or natural settlement
is established. Session finish is not the time of the rejected native query.
"""
from __future__ import annotations

import math


def _need(value):
    if not value: raise ValueError('Unbound existing Writer capture rejection')


def _integer(value, maximum=2**64 - 1):
    _need(type(value) is int and 0 < value <= maximum)
    return value


def _time(value):
    _need(type(value) in (int, float) and math.isfinite(value) and value >= 0)
    return value


def project(record, primary):
    """Return one bound, closed numeric vector, or leave the failure unknown."""
    try:
        if __package__:
            from . import numeric_notice as codec
            from .windows_smoke import _editor_focus_snapshot_ready
        else:
            import numeric_notice as codec
            from windows_smoke import _editor_focus_snapshot_ready
        _need(type(record) is dict and type(primary) is AssertionError)
        _need(all(type(record.get(key)) is str and record[key] == value for key, value in
              (('case', 'writer-heading1'), ('module', 'writer'), ('kind', 'native-writer-style'),
               ('stage', 'physical-heading1-shortcut')))
              and record.get('success') is False and type(record.get('architecture')) is str
              and record['architecture'] in ('x64', 'arm64'))
        failure = codec.validate_failure_code(record.get('numericFailure'))
        frames = codec.validate_failure_frames(record.get('numericFailureFrames'))
        _need(failure['captured'] == failure['exceptionCode'] == 1 and failure['fileCode'] == 1
              and frames == codec.capture_failure_frames(primary) and frames
              and frames[-1] == [1, failure['line']] and any(row[0] == 6 for row in frames[:-1]))
        raw = vars(primary).get('opengeul_focus_rejection')
        _need(type(raw) is dict and type(raw.get('schemaVersion')) is int and raw['schemaVersion'] == 1
              and type(raw.get('kind')) is str and raw['kind'] == 'strict-editor-focus-capture-rejection'
              and raw.get('actionOutcomeUnaffected') is True and raw.get('querySucceeded') is True)
        sessions = record.get('editorShortcutSessions')
        _need(type(sessions) is list and len(sessions) == 1)
        session = sessions[-1]
        _need(type(session) is dict and type(session.get('schemaVersion')) is int and session['schemaVersion'] == 1
              and type(session.get('kind')) is str and session['kind'] == 'first-admission-scenario-editor-shortcuts'
              and type(session.get('program')) is str and session['program'] == 'WRITER_STYLE'
              and session.get('success') is False)
        actions = session.get('actions')
        _need(type(actions) is list and len(actions) == 2 and all(type(row) is dict for row in actions)
              and all(type(row.get('shortcut')) is str for row in actions)
              and [row.get('shortcut') for row in actions] == ['CTRL_F6', 'CTRL_HOME'])
        for row in actions:
            _need(type(row) is dict and type(row.get('inputCallAttempts')) is int and row['inputCallAttempts'] == 1
                  and type(row.get('requestedInputs')) is int and row['requestedInputs'] == 4
                  and type(row.get('insertedInputs')) is int and row['insertedInputs'] == 4)
        action = actions[-1]
        deadline = _time(session.get('inputDeadline'))
        _need(deadline == _time(session.get('deadline'))
              and _time(session.get('startedAt')) <= _time(action.get('finishedAt')) <= deadline)
        binding = session.get('attachment')
        _need(type(binding) is dict)
        hwnd, parent, child, pid = (_integer(binding.get(key)) for key in ('hwnd', 'parent', 'child', 'officePid'))
        shell_pid = _integer(record.get('shellPid'), 2**32 - 1)
        _need((hwnd, parent, child, pid) == tuple(_integer(record.get(key)) for key in
              ('windowHwnd', 'parentHwnd', 'childHwnd', 'officePid')) and shell_pid != pid)
        _need(_integer(raw.get('suiteHwnd')) == hwnd and _integer(raw.get('childHwnd')) == child)
        after = action.get('after'); _need(type(after) is dict)
        for role, expected_pid in (('shell', shell_pid), ('engine', pid)):
            original = session.get('original' + role.title())
            _need(type(original) is dict and _integer(original.get('pid'), 2**32 - 1) == expected_pid
                  and _integer(original.get('handleValue')) and _integer(original.get('creationTime'))
                  and type(original.get('waitResult')) is int and original['waitResult'] == 258)
            observed = after.get(role)
            _need(type(observed) is dict and all(type(observed.get(key)) is int and observed[key] == original[key]
                  for key in ('pid', 'handleValue', 'creationTime', 'waitResult')))
        _need(session['originalEngine']['creationTime'] == _integer(record.get('officeCreationTime'))
              and session['originalShell']['creationTime'] <= session['originalEngine']['creationTime'])
        scope = after.get('scope'); _need(type(scope) is dict)
        windows = []
        for edge in ('before', 'after'):
            row = scope.get(edge)
            _need(type(row) is dict and row.get('editorWithinSuite') is True)
            windows.extend(row.get(role) for role in ('suite', 'editor', 'foreground'))
        windows.append(scope.get('focus'))
        for window in windows:
            _need(type(window) is dict and window.get('isWindow') is True)
            for key in ('hwnd', 'pid', 'threadId', 'rootHwnd'): _integer(window.get(key))
        _need(scope.get('focusWithinEditor') is True and type(scope.get('capture')) is dict
              and type(scope['capture'].get('hwnd')) is int and scope['capture']['hwnd'] == 0)
        _need(scope.get('queryAttempted') is True and scope.get('querySucceeded') is True
              and type(scope.get('cbSize')) is int and scope['cbSize'] == 72
              and type(scope.get('lastError')) is int and scope['lastError'] == 0)
        _integer(scope.get('queriedThreadId'), 2**32 - 1)
        thread = _integer(scope['before']['editor']['threadId'], 2**32 - 1)
        focus = _editor_focus_snapshot_ready(scope, hwnd, child, shell_pid, pid, thread)
        _need(focus == _integer(scope['focus']['hwnd']) and scope['capture']['hwnd'] == 0)
        rejected = raw.get('rawGuiThreadInfo')
        _need(type(rejected) is dict and type(rejected.get('cbSize')) is int and rejected['cbSize'] == 72)
        capture = _integer(rejected.get('hwndCapture'))
        queried = _integer(raw.get('queriedThreadId'), 2**32 - 1)
        relation = next((code for value, code in ((child, 1), (focus, 2), (parent, 3), (hwnd, 4))
                         if capture == value), 5)
        vector = [7, 1, int(queried == thread), relation, 0]
        if 'finishedAt' in session:
            finished = _time(session['finishedAt'])
            _need(finished >= _time(action['finishedAt']))
            vector[0] |= 8; vector[4] = int(finished <= deadline)
        return vector
    except Exception:
        return None
