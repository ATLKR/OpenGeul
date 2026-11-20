"""One fixed, counted Ctrl+Shift+J in the original Writer/Calc editor.

This receipt proves native insertion and the retained recipient, not fullscreen
delivery. A separate bounded observer must establish the visible transition.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import time

from ascii_editor_input import input_buffer
from counted_editor_shortcuts import _owned_release
import owned_native_menu as _native_menu
from owned_native_menu import NativeMenuProbe,READY_PROPERTY,_editor,require_native_menu_action,retain_native_menu_receipt
from native_menu_source_selection import selected_native_menu_probe

US_LAYOUT=0x04090409
EXTRA_KEYS=(1,2,4,5,6,0x4a)  # Mouse buttons and J, in addition to the shared neutral set.


def _events():
    keys=(0x1d,0x2a,0x24)
    return ([dict(vk=0,scan=scan,flags=8) for scan in keys]
        +[dict(vk=0,scan=scan,flags=10) for scan in reversed(keys)])


def _release_events(inserted):
    # The public shared release function admits only shared PRESETS. Keep that
    # guard unchanged; validate this one local fixed plan before its pure leaf.
    assert type(inserted) is int and 0<=inserted<=6
    return _owned_release(_events(),inserted)


def _positive(value):assert type(value) is int and 0<value<2**64


def _identity(row):
    _positive(row['pid']);_positive(row['creationTime'])
    assert type(row['waitResult']) is int and row['waitResult']==258
    assert type(row['image']) is str and row['image']
    return row['pid'],row['creationTime'],str(Path(row['image']).resolve()).casefold(),row['waitResult']


def _observe(probe,binding,shell_pid):
    editor=probe.editor_snapshot(binding);_editor(editor,binding,shell_pid)
    ready=probe._call(probe.user.GetPropW,binding['document'],READY_PROPERTY)
    assert type(ready) is int and ready==1, 'Fullscreen native menu session is unavailable'
    attachment=probe.attachment_snapshot(binding)
    assert attachment['binding']==binding and attachment['valid'] is True
    assert attachment['focusUnderOriginalChild'] is True and attachment['exported']==[binding['parent'],binding['child']]
    windows={role:probe.window_snapshot(binding[role]) for role in ('document','parent','child')}
    for role,row in windows.items():
        expected_pid=binding['officePid'] if role=='child' else shell_pid
        assert (row['hwnd'],row['pid'],row['rootHwnd'])==(binding[role],expected_pid,binding['document'])
        _positive(row['threadId'])
        assert row['visible'] is row['enabled'] is True and row['iconic'] is False and row['cloaked']==0
        assert all(attachment['windows'][role][key]==row[key] for key in ('hwnd','pid','threadId','rootHwnd'))
    thread=windows['child']['threadId'];gui=probe.native_focus(thread)
    assert gui['threadId']==thread and gui['focusPid']==binding['officePid'] and gui['focusRootHwnd']==binding['document']
    _positive(gui['focusHwnd']);_positive(gui['activeHwnd'])
    assert type(gui['flags']) is int and not gui['flags']&0x1e
    assert type(gui['captureHwnd']) is type(gui['menuOwnerHwnd']) is int and gui['captureHwnd']==gui['menuOwnerHwnd']==0
    focus=probe.window_snapshot(gui['focusHwnd']);active=probe.window_snapshot(gui['activeHwnd'])
    assert (focus['pid'],focus['threadId'],focus['rootHwnd'])==(binding['officePid'],thread,binding['document'])
    assert focus['visible'] is focus['enabled'] is True
    assert active['pid'] in (shell_pid,binding['officePid']) and active['rootHwnd']==binding['document']
    keyboard=probe.keyboard_snapshot(thread)
    assert type(keyboard['targetLayout']) is type(keyboard['currentThreadLayout']) is int
    assert keyboard['targetLayout']==keyboard['currentThreadLayout']==US_LAYOUT
    assert type(keyboard['keysDown']) is list and keyboard['keysDown']==[]
    locks=tuple(keyboard[key] for key in ('capsLockOn','scrollLockOn','numLockOn'))
    assert all(type(value) is bool for value in locks) and locks[:2]==(False,False)
    extra=[key for key in EXTRA_KEYS if probe._call(probe.user.GetAsyncKeyState,key)&0x8000]
    assert not extra, 'Fullscreen requires neutral J and mouse buttons'
    return dict(nativeReady=ready,editor=editor,attachment=attachment,windows=windows,gui=gui,focus=focus,active=active,
        keyboard=dict(keyboard,additionalKeysDown=extra))


def _anchor(snapshot):
    windows=snapshot['windows'];keyboard=snapshot['keyboard']
    return (tuple((role,windows[role]['threadId']) for role in ('document','parent','child')),
        tuple(keyboard[key] for key in ('capsLockOn','scrollLockOn','numLockOn')))


def toggle_native_fullscreen(api,process,document,record,*,module,probe=None,clock=time.monotonic,seconds=5):
    assert module in ('writer','calc') and type(seconds) in (int,float) and math.isfinite(seconds) and 0<seconds<=5
    _positive(document)
    start=clock();deadline=start+seconds
    value=dict(schemaVersion=1,kind='owned-native-fullscreen-toggle',module=module,success=False,deliveryProved=False,
        documentHwnd=document,shellPid=process.pid,startedAt=start,deadline=deadline,dpiScope={},
        events=_events(),inputCallAttempts=0,requestedInputs=6,insertedInputs=None,
        engineHandleReleased=False,providerClientReleased=False)
    previous=record.setdefault('nativeFullscreenActions',[])
    assert type(previous) is list and len(previous)<128
    previous.append(value);handle=None;primary=None;supplied=probe;probe=None
    def budget():assert clock()<deadline, 'Original fullscreen input deadline expired'
    try:
        budget()
        probe=selected_native_menu_probe(process,deadline,clock,
            build=lambda selection:NativeMenuProbe(deadline,clock,source_selection=selection),supplied=supplied)
        budget();assert record.get('module')==module, 'Fullscreen belongs to another document module'
        assert all(row.get('success') is True for row in previous[:-1]), 'Failed fullscreen action cannot be retried'
        origins=record.get('nativeMenuActions',[])
        assert type(origins) is list and 0<len(origins)<=128, 'Fullscreen requires its original native menu receipt'
        origin=origins[-1];selection=getattr(probe,'source_selection',None)
        if selection is None:require_native_menu_action(origin,process.pid,document)
        else:require_native_menu_action(origin,process.pid,document,source_admission=selection.prepared.admission)
        assert origin['finishedAt']<=start
        binding=copy.deepcopy(origin['binding']);shell=origin['originalProcess'];engine=origin['originalEngine']
        archive=record['nativeArchiveGeneration']
        assert type(archive) is dict and set(archive)=={'pid','creationTime','image'}
        assert all(archive[key]==engine[key] for key in ('pid','creationTime','image')), 'Original archive generation changed'
        assert shell['pid']==process.pid and shell['handleValue']==int(process._handle)
        suite=Path(process.opengeul_suite_root).resolve()
        assert Path(shell['image']).resolve()==suite/'OpenGeul.Office.exe'
        assert Path(engine['image']).resolve()==suite/'Office/program/soffice.bin'
        value.update(originIndex=len(origins)-1,nativeMenuOrigin=copy.deepcopy(origin),binding=binding,
            nativeArchiveGeneration=copy.deepcopy(archive),originalProcess=copy.deepcopy(shell),originalEngine=copy.deepcopy(engine))
        assert callable(getattr(probe,'close_provider',None)), 'Fullscreen requires owned provider cleanup'
        assert probe.process_snapshot(process)==shell, 'Original fullscreen shell generation changed'
        handle=probe.open_engine(binding['officePid']);_positive(handle)
        value['engineHandleValue']=handle;budget()
        observed_engine=probe.engine_snapshot(handle)
        assert _identity(observed_engine)==_identity(engine), 'Original fullscreen engine generation changed'
        assert observed_engine['handleValue']==handle
        assert api.attachment(document)==(binding['parent'],binding['child'],binding['officePid'])
        budget();_native_menu._bind_source_generation(probe,process,suite,binding,shell,observed_engine,handle,value)
        probe.enter_dpi(value['dpiScope']);assert value['dpiScope']['verified'] is True
        assert type(value['dpiScope'].get('previousContext')) is int and value['dpiScope']['previousContext']!=0
        def continuity():
            budget();assert probe.process_snapshot(process)==shell, 'Original fullscreen shell generation changed'
            observed=probe.engine_snapshot(handle)
            assert _identity(observed)==_identity(engine) and observed['handleValue']==handle
            assert api.attachment(document)==(binding['parent'],binding['child'],binding['officePid'])
        def observe():
            continuity();snapshot=_observe(probe,binding,process.pid);budget();return snapshot
        value['before']=observe();anchor=_anchor(value['before'])
        original_doc=origin['pointers'][0]['snapshots'][0]['document']
        assert value['before']['windows']['document']['threadId']==original_doc['threadId']
        value['knownPrefixReleasePlans']={str(n):_release_events(n) for n in range(7)}
        retain_native_menu_receipt(process,value);budget()
        value['beforeInsertion']=observe()
        assert _anchor(value['beforeInsertion'])==anchor
        assert value['beforeInsertion']['gui']['focusHwnd']==value['before']['gui']['focusHwnd'], 'Fullscreen focus changed while retaining input intent'
        continuity();value['inputCallAttempts']=1
        inserted=probe.send(input_buffer(value['events']));value['insertedInputs']=inserted
        assert type(inserted) is int and 0<=inserted<=6, 'Fullscreen native insertion count is unknown'
        if inserted!=6:
            release=_release_events(inserted)
            value['ownedKeyUp']=dict(events=release,requestedInputs=len(release),insertedInputs=None)
            if release:
                try:
                    returned=probe.release(release);value['ownedKeyUp']['insertedInputs']=returned
                    assert type(returned) is int and returned==len(release)
                except BaseException as exc:value['ownedKeyUp']['failureType']=type(exc).__name__
            raise AssertionError('Fullscreen native input was partial')
        budget();value['after']=observe();assert _anchor(value['after'])==anchor
        value.update(inputVerified=True,focusReturned=True)
    except BaseException as exc:
        primary=exc;value['failureType']=type(exc).__name__;raise
    finally:
        errors=[]
        if handle is not None:
            try:value['engineHandleReleased']=probe.close_engine(handle);assert value['engineHandleReleased'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        if value['dpiScope'].get('previousContext') is not None:
            try:probe.restore_dpi(value['dpiScope']);assert value['dpiScope']['restored'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        close_provider=getattr(probe,'close_provider',None)
        if close_provider:
            try:value['providerClientReleased']=close_provider();assert value['providerClientReleased'] is True
            except BaseException as exc:errors.append(type(exc).__name__)
        value.update(cleanupErrors=errors,finishedAt=clock())
        value['success']=(primary is None and not errors and value.get('inputVerified') is True
            and value['engineHandleReleased'] is True and value['providerClientReleased'] is True
            and value['dpiScope'].get('restored') is True and value['finishedAt']<deadline)
        try:retain_native_menu_receipt(process,value)
        except BaseException:
            value['success']=False
            if primary is None:raise
        if primary is None:assert value['success'], 'Fullscreen cleanup or original deadline failed'
    return value
