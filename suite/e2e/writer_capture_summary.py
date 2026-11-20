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

_TIMEOUT_PROJECTIONS = []  # Bounded live-object binding; never serialized.


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


def _project_timeout(record, primary):
    """Describe only the original Writer pre-insertion capture deadline failure.

    Presence bits 0..5 describe the six following values. The current invocation
    owns its row; cumulative captureReadiness ledger fields are never consulted.
    Handle relations compare integers and never establish capture ownership.
    """
    try:
        if __package__:
            from . import numeric_notice as codec
            from .capture_readiness import current_capture_invocation
            from .windows_smoke import _editor_focus_snapshot_ready
        else:
            import numeric_notice as codec
            from capture_readiness import current_capture_invocation
            from windows_smoke import _editor_focus_snapshot_ready
        _need(type(record) is dict and type(primary) is AssertionError)
        _need(all(type(record.get(key)) is str and record[key] == value for key,value in
            (('case','writer-heading1'),('module','writer'),('kind','native-writer-style'),
             ('stage','physical-heading1-shortcut'))) and record.get('success') is False
             and type(record.get('architecture')) is str and record['architecture'] in ('x64','arm64'))
        failure=codec.validate_failure_code(record.get('numericFailure'))
        frames=codec.validate_failure_frames(record.get('numericFailureFrames'))
        _need(failure['captured']==failure['exceptionCode']==1 and failure['fileCode']==24
            and frames==codec.capture_failure_frames(primary) and frames
            and frames[-1]==[24,failure['line']] and [row[0] for row in frames]==[6,13,13,13,13,13,24])
        names=[];tb=primary.__traceback__
        while tb is not None:
            names.append(tb.tb_frame.f_code.co_name);tb=tb.tb_next
        _need(names[-4:]==['_insert_once','_guard','_capture_guard','settle_owned_capture'])
        sessions=record.get('editorShortcutSessions');_need(type(sessions) is list and len(sessions)==1)
        session=sessions[0];_need(type(session) is dict and type(session.get('schemaVersion')) is int
            and session['schemaVersion']==1 and type(session.get('kind')) is str
            and session['kind']=='first-admission-scenario-editor-shortcuts'
            and type(session.get('program')) is str and session['program']=='WRITER_STYLE'
            and type(session.get('expectedProgram')) is list
            and all(type(word) is str for word in session['expectedProgram'])
            and session['expectedProgram']==['CTRL_F6','EDITOR_READY','CTRL_HOME','CTRL_1']
            and session.get('success') is False)
        actions=session.get('actions');_need(type(actions) is list and len(actions)==2
            and all(type(row) is dict for row in actions))
        first,action=actions
        _need(type(first.get('shortcut')) is str and first['shortcut']=='CTRL_F6'
            and all(type(first.get(key)) is int and first[key]==value for key,value in
                (('inputCallAttempts',1),('requestedInputs',4),('insertedInputs',4))))
        _need(type(action.get('shortcut')) is str and action['shortcut']=='CTRL_HOME'
            and type(action.get('inputCallAttempts')) is int and action['inputCallAttempts']==0
            and type(action.get('requestedInputs')) is int and action['requestedInputs']==4
            and action.get('insertedInputs') is None and 'beforeInsertion' not in action and 'after' not in action)
        phases=session.get('phases');_need(type(phases) is list and len(phases)==1
            and type(phases[0]) is dict and type(phases[0].get('step')) is str and phases[0]['step']=='EDITOR_READY')
        deadline=_time(session.get('inputDeadline'));finished=_time(session.get('finishedAt'))
        _need(deadline==_time(session.get('deadline')) and _time(session.get('startedAt'))<=
            _time(phases[0].get('at'))<deadline and _time(first.get('finishedAt'))<=deadline)
        current=vars(primary).get('opengeul_capture_invocation')
        _need(type(current) is dict and current_capture_invocation(session) is current
            and type(current.get('schemaVersion')) is int and current['schemaVersion']==1
            and type(current.get('kind')) is str and current['kind']=='owned-capture-readiness-invocation'
            and _time(current.get('deadline'))==deadline
            and deadline<=_time(current.get('lastCheckedAt'))<=finished
            and type(current.get('timeoutPhase')) is int and current['timeoutPhase'] in (1,2,3,4,5)
            and all(type(current.get(key)) is bool for key in
                ('observationPresent','validationReturned','ownedPositiveCapturePending')))
        binding=session.get('attachment');_need(type(binding) is dict)
        hwnd,parent,child,pid=(_integer(binding.get(key)) for key in ('hwnd','parent','child','officePid'))
        shell_pid=_integer(record.get('shellPid'),2**32-1)
        _need((hwnd,parent,child,pid)==tuple(_integer(record.get(key)) for key in
            ('windowHwnd','parentHwnd','childHwnd','officePid')) and shell_pid!=pid)
        originals=[]
        for role,expected_pid in (('shell',shell_pid),('engine',pid)):
            original=session.get('original'+role.title());_need(type(original) is dict
                and _integer(original.get('pid'),2**32-1)==expected_pid
                and _integer(original.get('handleValue')) and _integer(original.get('creationTime'))
                and type(original.get('waitResult')) is int and original['waitResult']==258)
            originals.append(original)
        _need(originals[1]['creationTime']==_integer(record.get('officeCreationTime'))
            and originals[0]['creationTime']<=originals[1]['creationTime'])
        locks=None
        def scope_of(row):
            nonlocal locks
            _need(type(row) is dict)
            for role,original in zip(('shell','engine'),originals):
                observed=row.get(role);_need(type(observed) is dict and all(type(observed.get(key)) is int
                    and observed[key]==original[key] for key in ('pid','handleValue','creationTime','waitResult')))
            for role in ('keyboard','focusKeyboard'):
                keys=row.get(role);_need(type(keys) is dict
                    and type(keys.get('targetLayout')) is int and keys['targetLayout']==0x04090409
                    and type(keys.get('currentThreadLayout')) is int and keys['currentThreadLayout']==0x04090409
                    and type(keys.get('keysDown')) is list and len(keys['keysDown'])==0
                    and keys.get('capsLockOn') is False and keys.get('scrollLockOn') is False
                    and type(keys.get('numLockOn')) is bool)
                observed_locks=tuple(keys[key] for key in ('capsLockOn','scrollLockOn','numLockOn'))
                if locks is None:locks=observed_locks
                _need(observed_locks==locks)
            scope=row.get('scope');_need(type(scope) is dict)
            for edge in ('before','after'):
                edge_row=scope.get(edge);_need(type(edge_row) is dict and edge_row.get('editorWithinSuite') is True)
                for role in ('suite','editor','foreground'):
                    window=edge_row.get(role);_need(type(window) is dict and window.get('isWindow') is True)
                    for key in ('hwnd','pid','threadId','rootHwnd'):_integer(window.get(key))
            focus=scope.get('focus');_need(type(focus) is dict and focus.get('isWindow') is True)
            for key in ('hwnd','pid','threadId','rootHwnd'):_integer(focus.get(key))
            capture=scope.get('capture');_need(type(capture) is dict and type(capture.get('hwnd')) is int
                and 0<=capture['hwnd']<=2**64-1 and scope.get('focusWithinEditor') is True
                and scope.get('queryAttempted') is True and scope.get('querySucceeded') is True
                and type(scope.get('cbSize')) is int and scope['cbSize']==72
                and type(scope.get('lastError')) is int and scope['lastError']==0)
            thread=_integer(scope.get('queriedThreadId'),2**32-1)
            _editor_focus_snapshot_ready(scope,hwnd,child,shell_pid,pid,thread)
            _need(focus['pid']==pid and focus['threadId']==thread)
            parent_row=scope.get('parent');_need(type(parent_row) is dict and parent_row.get('isWindow') is True
                and all(type(parent_row.get(key)) is int and parent_row[key]==value
                    for key,value in (('hwnd',parent),('pid',shell_pid),('rootHwnd',hwnd))))
            _need(all(scope.get(key) is True for key in
                ('suiteOwnsParent','parentOwnsChild','parentVisible','parentEnabled','childVisible','childEnabled')))
            return scope
        before=scope_of(action.get('before'));_need(before['capture']['hwnd']==0)
        readiness=record.get('editorFocusReadiness');receipts=record.get('editorFocusReadinessRecords')
        _need(type(readiness) is dict and type(receipts) is list and any(row is readiness for row in receipts)
            and type(readiness.get('schemaVersion')) is int and readiness['schemaVersion']==1
            and type(readiness.get('kind')) is str and readiness['kind']=='owned-editor-focus-readiness'
            and readiness.get('ready') is True and type(readiness.get('deadlineScope')) is str
            and readiness['deadlineScope']=='editor-setup-and-focus'
            and _time(readiness.get('deadline'))==_time(readiness.get('startedAt'))+_time(readiness.get('deadlineSeconds'))
            and 0<readiness['deadlineSeconds']<=5
            and _time(session['startedAt'])<=readiness['startedAt']<_time(session.get('entryDeadline'))
            and all(type(readiness.get(key)) is int and readiness[key]==value for key,value in
                (('suiteHwnd',hwnd),('childHwnd',child),('shellPid',shell_pid),('officePid',pid)))
            and _time(session['entryDeadline'])<=_time(session['startedAt'])+5
            and _time(first['finishedAt'])<session['entryDeadline']
            and deadline<=_time(phases[0]['at'])+5)
        proof=phases[0].get('proof');_need(type(proof) is dict and type(proof.get('focusHwnd')) is int
            and proof['focusHwnd']==_integer(readiness.get('focusHwnd')))
        ready_scope=scope_of(proof.get('snapshot'))
        _need(ready_scope['capture']['hwnd']==0 and ready_scope['focus']['hwnd']==proof['focusHwnd']
            and ready_scope['queriedThreadId']==before['queriedThreadId'])
        observed,validated,pending=(current[key] for key in
            ('observationPresent','validationReturned','ownedPositiveCapturePending'))
        phase=current['timeoutPhase']
        _need((not validated or observed) and (not pending or validated)
            and (phase==1 or observed) and (phase!=2 or not validated)
            and (phase not in (3,4,5) or validated) and (phase!=5 or pending))
        vector=[47,phase,int(observed),int(validated),int(pending),0,int(finished<=deadline)]
        if observed:
            last=vars(primary).get('opengeul_capture_observation')
            _need(last is session.get('lastGuardObservation'))
            scope=scope_of(last);capture=scope['capture'];value=capture['hwnd']
            _need(scope['queriedThreadId']==before['queriedThreadId'])
            if pending:
                _need(value>0 and capture.get('isWindow') is True
                    and type(capture.get('rootHwnd')) is int and capture['rootHwnd']==hwnd
                    and type(capture.get('pid')) is int and type(capture.get('threadId')) is int)
                expected={shell_pid:scope['before']['suite']['threadId'],pid:scope['before']['editor']['threadId']}
                _need(capture['pid'] in expected and capture['threadId']==expected[capture['pid']]>0)
            _need(phase!=4 or value==0)
            vector[0]|=16
            vector[5]=next((code for number,code in ((child,1),(before['focus']['hwnd'],2),(parent,3),(hwnd,4))
                if value==number),5) if value else 0
        else:
            _need(vars(primary).get('opengeul_capture_observation') is None and not validated and not pending)
        return vector
    except BaseException:
        return None


def project_timeout(record, primary):
    """Keep a bounded original-exception binding until the existing final emit."""
    try:
        value=_project_timeout(record,primary)
        if value is not None:
            current=primary.opengeul_capture_invocation
            _TIMEOUT_PROJECTIONS.append((record,primary,current,value,tuple(value),dict(current)))
            del _TIMEOUT_PROJECTIONS[:-32]
        return value
    except BaseException:
        return None


def bound_timeout(record):
    """Reject cleanup-overwritten or mutated metadata without another query."""
    try:
        if __package__:
            from .capture_readiness import current_capture_invocation
        else:
            from capture_readiness import current_capture_invocation
        for original,primary,current,value,frozen,metadata in reversed(_TIMEOUT_PROJECTIONS):
            if record is original and record.get('numericCaptureGateSnapshot') is value:
                sessions=record.get('editorShortcutSessions')
                if (type(sessions) is not list or len(sessions)!=1 or type(sessions[0]) is not dict
                        or current_capture_invocation(sessions[0]) is not current
                        or type(value) is not list or any(type(item) is not int for item in value)):return None
                fresh=_project_timeout(record,primary)
                return list(value) if fresh is not None and tuple(value)==frozen and current==metadata and fresh==value else None
    except BaseException:
        pass
    return None
