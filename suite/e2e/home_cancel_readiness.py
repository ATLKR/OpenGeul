"""Read-only settlement of the original Home after its canceled native picker."""
from __future__ import annotations
import ctypes as C
import math
from pathlib import Path, PureWindowsPath
import time

from suite_window_activation import NativeActivationProbe

OPEN_CAPTION='OpenGeul Office에서 문서 열기'


def _native_ids(row, keys):
    assert all(type(row[key]) is int and row[key]>0 for key in keys), 'Invalid native cancel identity'


def _validate(value, original, anchor, home, dialog, caption):
    for key in ('processBefore','processAfter'):_native_ids(value[key],('pid','handleValue','creationTime','waitResult'))
    assert value['processBefore'] == value['processAfter'] == original, 'Original cancel process generation changed'
    row = value['document']
    _native_ids(row,('hwnd','pid','threadId','rootHwnd'))
    assert all(row[k] == anchor[k] for k in ('hwnd', 'pid', 'threadId', 'rootHwnd', 'className')), 'Original canceled-picker owner identity changed'
    assert row['hwnd'] == row['rootHwnd'] == home and row['pid'] == original['pid']
    assert type(row['threadId']) is int and row['threadId'] > 0
    assert row['visible'] is True and row['iconic'] is False and type(row['cloaked']) is int and row['cloaked'] == 0, 'Canceled-picker Home is unavailable'
    assert type(row['enabled']) is bool and type(value['dialogAlive']) is bool
    foreground = value['foreground']
    _native_ids(foreground,('hwnd','pid','threadId','rootHwnd'))
    expected = dialog if value['dialogAlive'] else home
    assert foreground['hwnd'] == foreground['rootHwnd'] == expected and foreground['pid'] == original['pid'] and foreground['threadId'] == anchor['threadId'], 'Foreign foreground during canceled-picker owner readiness'
    if value['dialogAlive']:
        picker = value['dialog']
        _native_ids(picker,('hwnd','pid','threadId','rootHwnd','ownerHwnd'))
        assert (picker['hwnd'], picker['rootHwnd'], picker['pid'], picker['threadId'], picker['ownerHwnd'], picker['className'], picker['title']) == (dialog, dialog, original['pid'], anchor['threadId'], home, '#32770', caption), 'Original canceled picker was replaced'
    else:
        assert value['dialog'] is None
    return not value['dialogAlive'] and row['enabled'] is True


def require_cancelled_home_readiness(receipt, shell_pid, home, original_shell, *, open_readiness):
    assert type(receipt['schemaVersion']) is int and receipt['schemaVersion']==1
    assert type(open_readiness['schemaVersion']) is int and open_readiness['schemaVersion']==1
    _native_ids(receipt,('shellPid','homeHwnd','dialogHwnd'))
    _native_ids(open_readiness,('shellPid','documentHwnd','dialogHwnd'))
    assert open_readiness['kind']=='owned-open-dialog-readiness' and open_readiness['ready'] is True
    assert (open_readiness['shellPid'],open_readiness['documentHwnd'],open_readiness['dialogHwnd'],open_readiness['caption'])==(shell_pid,home,receipt['dialogHwnd'],OPEN_CAPTION)
    assert receipt['caption']==OPEN_CAPTION and receipt['originalOwner']==open_readiness['nativeAnchor']['document']
    _native_ids(receipt['originalOwner'],('hwnd','pid','threadId','rootHwnd'))
    _native_ids(open_readiness['nativeAnchor']['dialog'],('hwnd','pid','threadId','rootHwnd'))
    picker=open_readiness['nativeAnchor']['dialog']
    assert (picker['hwnd'],picker['rootHwnd'],picker['pid'],picker['threadId'],picker['className'])==(receipt['dialogHwnd'],receipt['dialogHwnd'],shell_pid,receipt['originalOwner']['threadId'],'#32770')
    assert receipt['kind'] == 'owned-cancelled-home-readiness' and receipt['ready'] is True
    assert (receipt['shellPid'], receipt['homeHwnd']) == (shell_pid, home)
    assert type(receipt['pollCount']) is int and 1 <= receipt['pollCount'] <= 401
    for key in ('startedAt','finishedAt','deadline'):
        assert type(receipt[key]) in (int,float) and math.isfinite(receipt[key]) and receipt[key]>=0
    assert receipt['deadline'] == receipt['startedAt'] + 20
    assert receipt['startedAt'] <= receipt['finishedAt'] < receipt['deadline']
    original = receipt['originalProcess']
    assert all(type(original[key]) is int and original[key]>0 for key in ('pid','handleValue','creationTime','waitResult'))
    assert (original['pid'], original['handleValue'], original['creationTime'], original['waitResult']) == (shell_pid, original_shell['handleValue'], original_shell['nativeCreation']['fileTime'], 258)
    # Both images come from retained native queries; replay never resolves a
    # Windows receipt path against the filesystem of its inspection host.
    assert type(original['image']) is str and type(original_shell['nativeImage']) is str and original['image'] and original_shell['nativeImage']
    assert PureWindowsPath(original['image'])==PureWindowsPath(original_shell['nativeImage']), 'Original cancel native image changed'
    _validate(receipt['firstObservation'], original, receipt['originalOwner'], home, receipt['dialogHwnd'], receipt['caption'])
    assert _validate(receipt['lastObservation'], original, receipt['originalOwner'], home, receipt['dialogHwnd'], receipt['caption'])
    return receipt


def wait_cancelled_home(api, process, home, dialog, record, operation, *, probe=None,
                        clock=time.monotonic, pause=time.sleep):
    """No input or activation: spend exactly the former disappearance20s budget."""
    started = clock(); deadline = started + 20
    proof = operation['openDialogReadiness']; anchor = dict(proof['nativeAnchor']['document'])
    value = dict(schemaVersion=1, kind='owned-cancelled-home-readiness', ready=False,
                 shellPid=process.pid, homeHwnd=home, dialogHwnd=dialog, caption=proof['caption'],
                 startedAt=started, deadline=deadline, pollCount=0, originalOwner=anchor)
    operation['cancelOwnerReadiness'] = value
    primary=None
    def budget():
        assert clock() < deadline, 'Canceled-picker owner readiness deadline expired'
    try:
        shell = record['originalShell']
        assert (proof['shellPid'], proof['documentHwnd'], proof['dialogHwnd']) == (process.pid, home, dialog)
        assert proof['ready'] is True and anchor['hwnd'] == home and anchor['pid'] == process.pid
        original = dict(pid=process.pid, handleValue=int(process._handle), creationTime=shell['nativeCreation']['fileTime'], image=str(Path(shell['nativeImage']).resolve()), waitResult=258)
        assert shell['pid'] == process.pid and shell['handleValue'] == int(process._handle)
        assert type(original['creationTime']) is int and original['creationTime'] > 0
        value['originalProcess'] = original
        probe = probe if probe is not None else NativeCancelProbe(deadline, clock)
        while True:
            budget(); assert value['pollCount'] < 401, 'Canceled-picker observation bound exceeded'
            observation = probe.snapshot(process, home, dialog)
            value['pollCount'] += 1; value['lastObservation'] = observation
            value.setdefault('firstObservation', observation)
            budget(); ready = _validate(observation, original, anchor, home, dialog, proof['caption'])
            if ready:
                value['finishedAt'] = clock(); budget(); value['ready'] = True
                require_cancelled_home_readiness(value, process.pid, home, shell,open_readiness=proof)
                budget(); return value
            remaining = deadline - clock(); assert remaining > 0, 'Canceled-picker owner readiness deadline expired'
            pause(min(.05, remaining))
    except BaseException as exc:
        primary=exc;value.update(ready=False, error=type(exc).__name__ + ': ' + str(exc)[:1024]); raise
    finally:
        try:
            previous=value.get('finishedAt',started);finished=clock()
            finite=type(finished) in (int,float) and math.isfinite(finished)
            value['finishedAt']=finished if finite else None
            if not finite:value['finalClockRaw']=dict(type=type(finished).__name__,value=repr(finished)[:160])
            assert type(finished) in (int,float) and math.isfinite(finished) and started<=previous<=finished<deadline, 'Canceled-picker final clock/timestamp exceeded original deadline or regressed'
        except BaseException as exc:
            value.update(ready=False,finalClockError=type(exc).__name__+': '+str(exc)[:1024])
            if primary is None:
                value['error']=value['finalClockError'];raise


class NativeCancelProbe(NativeActivationProbe):
    def __init__(self, deadline, clock, **libraries):
        super().__init__(deadline, clock, **libraries)
        for name, args, result in [('GetWindow', (C.c_void_p, C.c_uint32), C.c_void_p),
            ('GetClassNameW', (C.c_void_p, C.c_wchar_p, C.c_int32), C.c_int32),
            ('GetWindowTextW', (C.c_void_p, C.c_wchar_p, C.c_int32), C.c_int32)]:
            function = getattr(self.user, name); function.argtypes, function.restype = args, result
    def _window(self, hwnd):
        row = self.window_snapshot(hwnd); kind = C.create_unicode_buffer(257); title = C.create_unicode_buffer(257)
        length = int(self._call(self.user.GetClassNameW, hwnd, kind, len(kind))); assert 0 < length < 256
        length = int(self._call(self.user.GetWindowTextW, hwnd, title, len(title))); assert 0 <= length < 256
        row.update(className=kind.value, title=title.value, ownerHwnd=int(self._call(self.user.GetWindow, hwnd, 4) or 0))
        return row
    def snapshot(self, process, home, dialog):
        before = self.process_snapshot(process)
        owner = self._window(home); alive = bool(self._call(self.user.IsWindow, dialog))
        picker = self._window(dialog) if alive else None
        foreground = self._window(self.foreground())
        return dict(processBefore=before, processAfter=self.process_snapshot(process),
                    document=owner, dialogAlive=alive, dialog=picker, foreground=foreground)
