"""Fixed six-module native menu gestures on fresh blank owned documents.

This is one UI gate, not complete Suite acceptance. Save/reopen, Save As cancel,
close cancellation, module switching and Home ownership remain separate gates.
Synthetic boundary checks never establish actual Windows UI verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import copy
import ctypes
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time

MODULES = ('writer', 'calc', 'impress', 'draw', 'math', 'base')
GESTURES = ('open-escape', 'open-outside', 'keyboard-escape', 'open-escape')
VIEW_MODULES = ('writer', 'calc')
CORE_COMMANDS = ('new-hwp', 'home', 'new', 'open', 'save', 'saveAs', 'close')
EXTERNAL_GATES = ('save-and-reopen', 'save-as-cancel', 'close-cancel',
                  'module-transition', 'home-ownership', 'formatting')


def _initial_focus_unknown(code):
    return dict(schemaVersion=1, attempted=True, known=False, acceptanceEligible=False,
        errorCode=code, gapObserved=False, gapCount=0, eventCompletenessUnknown=True, scope={}, rows=[])


def _initial_focus_retired_unknown(code, *, attempted=True, retirement_confirmed=False):
    value=_initial_focus_unknown(code)
    value.update(attempted=attempted,captureModeCode=2,historicalIdentityOnly=True,
        retirementConfirmed=retirement_confirmed)
    return value


def _initial_focus_counters_unknown(code):
    return dict(schemaVersion=2,known=0,counterIntervalComplete=0,zeroCountsUsable=0,
        acceptanceEligible=0,eventCompletenessUnknown=1,errorCode=code,scope={},latest={})


def _initial_focus_counters(lines,original,*,trace,worker,managed,retirement_confirmed,budget):
    """Counter authority comes only from the same retained, framed original read.

    Parser codes1..7 are unchanged. Collector-only unknown codes:8 envelope or
    stage/kind mismatch,9 retained context/framing unavailable,10 budget,11 error,
    12 after-retirement capture not attempted. No missing marker proves zero use.
    """
    code=9
    try:
        budget()
        assert original['known'] is True and type(managed) is int and type(worker) is int and type(trace) is str
        assert type(retirement_confirmed) is bool
        scope=original['scope'];identity={key:value for key,value in scope.items() if key!='moduleCode'}
        identity['managedThreadId']=managed
        prefix=b'{"event":"suite.initialEditorFocusFlow","component":"host",'
        observe=prefix+b'"stage":"observe",'
        rows=[]
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise ValueError()
                value[key]=item
            return value
        def invalid_constant(value):raise ValueError()
        def integer(value,maximum,minimum=0):
            if type(value) is not int or not minimum<=value<=maximum:raise ValueError()
            return value
        for line in lines:
            budget()
            if not line.startswith(prefix) or line.startswith(observe):continue
            code=8
            value=json.loads(line.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid_constant)
            assert type(value) is dict and set(value)==set('event component stage sequence utc processId managedThreadId workerProcessId traceId details'.split())
            assert value['event']=='suite.initialEditorFocusFlow' and value['component']=='host'
            assert type(value['utc']) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)',value['utc'])
            assert integer(value['processId'],0xffffffff,1)==scope['shellPid']
            assert integer(value['managedThreadId'],0x7fffffff,1)==managed
            assert integer(value['workerProcessId'],0x7fffffff,1)==worker
            assert type(value['traceId']) is str and value['traceId']==trace
            if value['stage']=='observe':continue
            assert value['stage'] in ('prefix','final')
            details=value['details'];assert type(details) is dict
            assert all(type(item) is int for item in details.values())
            assert type(details.get('snapshotKindCode')) is int
            assert details['snapshotKindCode']==(1 if value['stage']=='prefix' else 2)
            sequence=integer(value['sequence'],128,1)
            assert 'sequence' not in details
            rows.append(dict(sequence=sequence,**details));assert len(rows)<=128
        budget()
        code=11
        from initial_focus_final_counters import parse_initial_focus_final_counters
        result=parse_initial_focus_final_counters(rows,retained_identity=identity,
            retirement_confirmed=retirement_confirmed)
        budget()
        return result
    except TimeoutError:
        return _initial_focus_counters_unknown(10)
    except Exception:
        return _initial_focus_counters_unknown(code)


def _initial_focus_flow(lines, original, *, trace, worker, managed, budget):
    """Parse only the separate numeric observer; never revoke original evidence."""
    code=1
    def unknown(value):
        result=_initial_focus_unknown(value)
        if original.get('captureModeCode')==2:
            result.update(captureModeCode=2,historicalIdentityOnly=True,
                retirementConfirmed=original.get('retirementConfirmed') is True)
        return result
    def integer(value,maximum,minimum=0):
        if type(value) is not int or not minimum<=value<=maximum:raise ValueError()
        return value
    def flag(value):
        if type(value) is not bool:raise ValueError()
        return value
    def keys(value,names):
        if type(value) is not dict or set(value)!=set(names.split()):raise ValueError()
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError()
            value[key]=item
        return value
    def invalid_constant(value):raise ValueError()
    try:
        budget()
        assert original['known'] is True and type(managed) is int and type(worker) is int and type(trace) is str
        scope=original['scope'];rows=[];sequence=0;gaps=0;observations={}
        prefix=b'{"event":"suite.initialEditorFocusFlow","component":"host",'
        for line in lines:
            budget()
            if not line.startswith(prefix):continue
            # These canonical stages own an independent closed counter schema.
            # Their malformed details cannot revoke the fixed observe projection.
            if line.startswith((prefix+b'"stage":"prefix",',prefix+b'"stage":"final",')):continue
            code=3
            value=json.loads(line.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid_constant)
            keys(value,'event component stage sequence utc processId managedThreadId workerProcessId traceId details')
            assert value['event']=='suite.initialEditorFocusFlow' and value['component']=='host' and value['stage']=='observe'
            assert type(value['utc']) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)',value['utc'])
            process_id=integer(value['processId'],0xffffffff,1)
            thread_id=integer(value['managedThreadId'],0x7fffffff,1)
            worker_id=integer(value['workerProcessId'],0x7fffffff,1)
            assert type(value['traceId']) is str
            code=1
            assert (process_id,thread_id,worker_id,value['traceId'])==(scope['shellPid'],managed,worker,trace)
            code=4
            current=integer(value['sequence'],128,1);assert current>sequence
            gaps+=current-sequence-1;sequence=current
            code=3
            details=value['details']
            keys(details,'schemaVersion observationId sourceCode phaseCode gateGroupCode evaluatedMask trueMask firstRejectId evaluationComplete pendingKnown pending queueReturnKnown queueReturn originalFormHwnd originalPanelHwnd')
            assert integer(details['schemaVersion'],1,1)==1
            observation=integer(details['observationId'],128,1)
            source=integer(details['sourceCode'],5);phase=integer(details['phaseCode'],12,1)
            group=integer(details['gateGroupCode'],3);width=(0,7,1,14)[group];maximum=(1<<width)-1
            mask=integer(details['evaluatedMask'],maximum);true_mask=integer(details['trueMask'],maximum)
            first=integer(details['firstRejectId'],width);complete=flag(details['evaluationComplete'])
            assert mask&(mask+1)==0 and true_mask&~mask==0
            rejected=true_mask if group==1 else mask^true_mask
            assert first==(rejected&-rejected).bit_length()
            if complete:
                assert group>0 and mask==((1<<first)-1 if first else maximum)
            pending_known=flag(details['pendingKnown']);pending=flag(details['pending'])
            queue_known=flag(details['queueReturnKnown']);queued=flag(details['queueReturn'])
            assert pending_known or not pending
            assert queue_known or not queued
            form=integer(details['originalFormHwnd'],2**63-1,1)
            panel=integer(details['originalPanelHwnd'],2**63-1,1)
            code=1
            assert (form,panel)==(scope['formHwnd'],scope['panelHwnd'])
            code=3
            # A retained callback may follow a later ingress. Only envelope sequence is ordered.
            anchor=(source,details['originalFormHwnd'],details['originalPanelHwnd'])
            assert observations.setdefault(observation,anchor)==anchor
            rows.append(dict(sequence=current,**details))
        budget();code=2
        assert rows
        result=dict(schemaVersion=1,attempted=True,known=True,acceptanceEligible=False,errorCode=0,
            gapObserved=gaps>0,gapCount=gaps,eventCompletenessUnknown=True,scope=dict(scope),rows=rows)
        if original.get('captureModeCode')==2:
            result.update(captureModeCode=2,historicalIdentityOnly=True,retirementConfirmed=True)
        return result
    except TimeoutError:
        return unknown(5)
    except Exception:
        return unknown(code)


def capture_initial_focus_trace(session, record, *, retired=False, expected_identity=None, flow_out=None,counter_out=None):
    """One bounded, numeric-only read of this launch's existing C# stderr.

    Unknown codes: 1=owner context, 2=path, 3=bound, 4=unstable/read,
    5=JSON framing, 6=no rows, 7=shape, 8=sequence, 9=generation, 10=budget,
    11=unexpected capture error, 12=retirement not attempted, 13=retirement proof.
    Missing/partial evidence never certifies a focus attempt or changes a gate.
    Retired mode uses the caller's immutable pre-cleanup identity only as history;
    it never queries or restores the closed engine HANDLE. Its separate one-second
    diagnostic deadline rejects late data but cannot preempt synchronous file IO.
    """
    code = 1
    if type(flow_out) is dict:
        flow_out.clear();flow_out.update(_initial_focus_retired_unknown(1) if retired is True else _initial_focus_unknown(1))
    if type(counter_out) is dict:
        counter_out.clear();counter_out.update(_initial_focus_counters_unknown(9))
    retirement_confirmed = False
    deadline = time.monotonic() + 1
    def budget():
        if time.monotonic() >= deadline:
            raise TimeoutError()
    def integer(value, maximum=2**63-1, minimum=0):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError()
        return value
    def flag(value):
        if type(value) is not bool: raise ValueError()
        return value
    def keys(value, expected):
        if type(value) is not dict or set(value) != set(expected.split()): raise ValueError()
    def unknown(error_code):
        if retired is True:
            return _initial_focus_retired_unknown(error_code,retirement_confirmed=retirement_confirmed)
        return _initial_focus_unknown(error_code)
    try:
        budget()
        flag(retired)
        module=record['module'];case='native-menu-'+module
        assert module in MODULES and record['case']==case==session.process.opengeul_evidence_case
        process=session.process;engine=session.engine;output=Path(session.output)
        suite=Path(session.suite)
        assert output==Path(process.opengeul_evidence_output) and suite==Path(process.opengeul_suite_root) and suite.is_absolute()
        shell=record['windowActivations'][0]['originalProcess']
        shell_pid=integer(process.pid,0xffffffff,1);shell_handle=integer(int(process._handle),minimum=1)
        shell_birth=integer(shell['creationTime'],minimum=1)
        office_pid=integer(session.office_pid,0xffffffff,1);office_birth=integer(engine.creation_time,minimum=1)
        assert shell_pid!=office_pid and shell_birth<=office_birth
        assert (record['shellPid'],record['officePid'],record['officeCreationTime'])==(shell_pid,office_pid,office_birth)
        form,panel,child=(integer(value,minimum=1) for value in (session.hwnd,session.parent,session.child))
        assert (record['windowHwnd'],record['parentHwnd'],record['childHwnd'])==(form,panel,child)
        assert len({form,panel,child})==3
        if retired:
            code=13
            assert all(record.get(key) is True for key in ('cleanupConfirmed','shellCleanupConfirmed',
                'officeExitedAfterCleanup','engineHandleReleased','nativePointCallbackRetired'))
            assert engine.handle is None
            observed_exit=process.poll()
            assert type(observed_exit) is int and type(record.get('shellExitCode')) is int
            assert observed_exit==record['shellExitCode'] and _confirmed_shell_cleanup(record,shell_pid,observed_exit)
            assert type(expected_identity) is tuple and len(expected_identity)==8
            assert all(type(value) is int and value>0 for value in expected_identity)
            assert type(session._opening_focus_identity) is tuple and session._opening_focus_identity==expected_identity
            # No native call is made with this historical HANDLE value.
            historical_engine_handle=integer(expected_identity[2],minimum=1)
            assert expected_identity==(shell_pid,shell_handle,historical_engine_handle,office_birth,form,panel,child,office_pid)
        else:
            assert session._opening_focus_identity==(shell_pid,shell_handle,int(engine.handle),office_birth,form,panel,child,office_pid)
        expected_shell=PureWindowsPath(str(suite/'OpenGeul.Office.exe'))
        expected_engine=PureWindowsPath(str(suite/'Office/program/soffice.bin'))
        for activation in record['windowActivations']:
            original=activation['originalProcess']
            assert (original['pid'],original['handleValue'],original['creationTime'])==(shell_pid,shell_handle,shell_birth)
            assert PureWindowsPath(original['image'])==expected_shell and original['waitResult']==258
            assert activation['suiteHwnd']==form and activation['shellPid']==shell_pid
        generation=record['nativeArchiveGeneration']
        assert (generation['pid'],generation['creationTime'])==(office_pid,office_birth)
        assert PureWindowsPath(generation['image'])==expected_engine
        opening=record['openingFocusObservations'];assert 1<=len(opening)<=3
        assert [row['phaseCode'] for row in opening]==list(range(1,len(opening)+1))
        host_thread=integer(opening[0]['hostGui']['threadId'],0xffffffff,1)
        editor_thread=integer(opening[0]['engineGui']['threadId'],0xffffffff,1)
        assert all((row['hostGui']['threadId'],row['engineGui']['threadId'])==(host_thread,editor_thread) for row in opening)
        scope=dict(moduleCode=MODULES.index(module)+1,shellPid=shell_pid,shellCreationTime=shell_birth,
            officePid=office_pid,officeCreationTime=office_birth,formHwnd=form,panelHwnd=panel,childHwnd=child,
            shellThreadId=host_thread,editorThreadId=editor_thread)
        retirement_confirmed=retired
        code=2
        assert output.is_absolute() and not str(output).startswith(('\\\\','//')) and '..' not in output.parts
        for directory in (output,*output.parents):
            info=directory.lstat()
            assert stat.S_ISDIR(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400
        assert output.resolve()==output
        path=output/(case+'-stderr.log');before=path.lstat()
        assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not getattr(before,'st_file_attributes',0)&0x400
        code=3
        assert 0<before.st_size<=2*1024*1024
        budget();code=4
        descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NOINHERIT',0))
        def identity(info):
            return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_nlink,
                info.st_mode,getattr(info,'st_file_attributes',0))
        try:
            assert identity(os.fstat(descriptor))==identity(before)
            raw=os.read(descriptor,before.st_size+1)
            assert len(raw)==before.st_size
            assert identity(os.fstat(descriptor))==identity(before)==identity(path.lstat())
        finally:
            os.close(descriptor)
        budget();code=3
        lines=raw.splitlines(keepends=True)
        assert len(lines)<=8192 and all(len(line)<=64*1024 for line in lines)
        code=5
        assert raw.endswith(b'\n')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value: raise ValueError()
                value[key]=item
            return value
        def invalid_constant(value): raise ValueError()
        prefix=b'{"event":"suite.editorFocus","component":"host",'
        rows=[];sequence=0;gap_count=0;context=None;trace=None;worker=None;initial_managed=None
        stage_codes={'initial':1,'initial.queued':2,'initial.activation':3,'initial.activationObserved':4}
        reason_codes={'alreadyFocused':1,'editorFocused':2,'initialAlreadyHandled':3,
            'initialPending':4,'initialHandoffUnverified':5,'initialContextCancelled':6}
        window_keys='Hwnd Pid ThreadId Root Parent Exists Visible Enabled ClassName'
        numeric_windows='Form Panel Child Foreground Focus EditorFocus Capture EditorCapture'.split()
        snapshot_keys='Shell Engine '+ ' '.join(numeric_windows)+' CurrentThread GuiQueriesSucceeded GuiFlags FormOwnsPanel PanelOwnsChild FocusWithinEditor EditorFocusWithinEditor RegisteredPanel RegisteredChild HostMenuOwner EditorMenuOwner'
        def attachment_identity(value):
            return tuple(tuple(value[name][key] for key in ('Hwnd','Pid','ThreadId','Root','Parent'))
                for name in ('Form','Panel','Child'))
        def snapshot(value):
            keys(value,snapshot_keys)
            cleaned={}
            for name,pid,birth,image in (('Shell',shell_pid,shell_birth,expected_shell),('Engine',office_pid,office_birth,expected_engine)):
                item=value[name];keys(item,'Pid CreationTime Image Alive')
                assert type(item['Image']) is str and PureWindowsPath(item['Image'])==image
                assert integer(item['Pid'],0xffffffff,1)==pid and integer(item['CreationTime'],minimum=1)==birth
                assert flag(item['Alive'])
                cleaned[name]=dict(Pid=pid,CreationTime=birth,Alive=True)
            for name in numeric_windows:
                item=value[name];keys(item,window_keys)
                assert type(item['ClassName']) is str and len(item['ClassName'])<=255
                cleaned[name]={key:integer(item[key],0xffffffff if key in ('Pid','ThreadId') else 2**63-1)
                    for key in ('Hwnd','Pid','ThreadId','Root','Parent')}
                cleaned[name].update({key:flag(item[key]) for key in ('Exists','Visible','Enabled')})
            for name in ('GuiQueriesSucceeded','FormOwnsPanel','PanelOwnsChild','FocusWithinEditor','EditorFocusWithinEditor'):
                cleaned[name]=flag(value[name])
            for name in ('CurrentThread','GuiFlags','RegisteredPanel','RegisteredChild','HostMenuOwner','EditorMenuOwner'):
                cleaned[name]=integer(value[name],0xffffffff if name in ('CurrentThread','GuiFlags') else 2**63-1)
            for name,hwnd,pid,thread,parent in (('Form',form,shell_pid,host_thread,None),
                    ('Panel',panel,shell_pid,host_thread,form),('Child',child,office_pid,editor_thread,panel)):
                item=cleaned[name]
                assert (item['Hwnd'],item['Pid'],item['ThreadId'],item['Root'])==(hwnd,pid,thread,form)
                assert item['Exists'] and (parent is None or item['Parent']==parent)
            assert cleaned['CurrentThread']==host_thread
            assert (cleaned['RegisteredPanel'],cleaned['RegisteredChild'])==(panel,child)
            assert cleaned['FormOwnsPanel'] and cleaned['PanelOwnsChild']
            return cleaned
        for line in lines:
            budget();code=5
            if not line.startswith(prefix): continue
            value=json.loads(line.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid_constant)
            code=7
            keys(value,'event component stage sequence utc processId managedThreadId workerProcessId traceId details')
            assert value['event']=='suite.editorFocus' and value['component']=='host'
            assert type(value['utc']) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)',value['utc'])
            assert integer(value['processId'],0xffffffff,1)==shell_pid
            managed=integer(value['managedThreadId'],0x7fffffff,1)
            pid=integer(value['workerProcessId'],0x7fffffff,1)
            assert type(value['traceId']) is str and re.fullmatch('[0-9a-f]{32}',value['traceId'])
            code=8
            current_sequence=integer(value['sequence'],128,1)
            assert current_sequence>sequence
            gap_count+=current_sequence-sequence-1
            sequence=current_sequence
            assert trace is None or (trace,worker)==(value['traceId'],pid)
            trace,worker=value['traceId'],pid
            code=7
            stage=stage_codes[value['stage']];details=value['details']
            expected=('sourceCode rejectBitmask pendingBefore pending originalFormHwnd originalPanelHwnd receivedHwnd ownerSame'
                if stage==4 else 'queued pending' if stage==2 else 'available pending result' if stage==1 else 'pending result')
            keys(details,expected)
            row=dict(sequence=sequence,stageCode=stage,reasonCode=0,managedThreadId=managed,workerProcessId=pid,
                pending=flag(details['pending']),availablePresent=stage==1,available=False,
                queuePresent=stage==2,queued=False,resultPresent=stage in (1,3),attempted=False,verified=False,
                beforePresent=False,before={},afterPresent=False,after={},previousFocus=0,nativeError=0,
                contextInherited=False)
            if stage==1: row['available']=flag(details['available'])
            if stage==4:
                source=integer(details['sourceCode'],5,1);mask=integer(details['rejectBitmask'],511)
                pending_before=flag(details['pendingBefore']);owner_same=flag(details['ownerSame'])
                observed_form=integer(details['originalFormHwnd'],minimum=1)
                observed_panel=integer(details['originalPanelHwnd'],minimum=1)
                receiver=integer(details['receivedHwnd'])
                assert pending_before and (observed_form,observed_panel)==(form,panel)
                assert not mask&64  # The producer omits rows without a retained live form handle.
                assert bool(mask&128)==(not owner_same) and bool(mask&8)==(not row['pending'])
                assert bool(mask&256)==(receiver!=form)
                assert not mask&4 or not row['pending'] and not owner_same
                if source in (1,4):assert receiver==form
                row.update(sourceCode=source,rejectBitmask=mask,pendingBefore=pending_before,
                    originalFormHwnd=observed_form,originalPanelHwnd=observed_panel,
                    receivedHwnd=receiver,ownerSame=owner_same,contextDeferred=context is None,
                    contextInherited=context is not None)
            elif stage==2:
                row['queued']=flag(details['queued']);assert context is not None
                row['contextInherited']=True
            else:
                result=details['result'];keys(result,'Verified Attempted Reason Before After PreviousFocus NativeError')
                row.update(verified=flag(result['Verified']),attempted=flag(result['Attempted']),
                    reasonCode=reason_codes[result['Reason']],previousFocus=integer(result['PreviousFocus']),
                    nativeError=integer(result['NativeError'],0x7fffffff,-0x80000000))
                code=9
                for source,target in (('Before','before'),('After','after')):
                    if result[source] is not None:
                        row[target]=snapshot(result[source]);row[target+'Present']=True
                if row['beforePresent']:
                    before_context=attachment_identity(row['before'])
                    assert context is None or before_context==context
                    context=before_context
                    if stage==1 and initial_managed is None:initial_managed=managed
                else:
                    assert context is not None;row['contextInherited']=True
                if row['afterPresent']:
                    assert context is not None
                    assert attachment_identity(row['after'])==context
            rows.append(row)
        budget();code=4
        assert identity(path.lstat())==identity(before)
        code=6
        assert rows and context is not None
        for row in rows:
            if row['stageCode']==4:
                code=9
                # Managed IDs are joined only to the original rich initial row.
                # Its validated CurrentThread separately binds the native TID.
                assert initial_managed is not None and row['managedThreadId']==initial_managed
                row['contextInherited']=True
        # Failed writes consume sequence numbers; the logger also has a silent
        # cap and no completion marker. No absent event proves non-execution.
        value=dict(schemaVersion=1,attempted=True,known=True,acceptanceEligible=False,errorCode=0,
            gapObserved=gap_count>0,gapCount=gap_count,eventCompletenessUnknown=True,scope=scope,rows=rows)
        if retired:
            value.update(captureModeCode=2,historicalIdentityOnly=True,retirementConfirmed=True)
        if type(flow_out) is dict:
            # Fix the original projection first. Only the observer spends the remaining budget.
            try:
                flow=_initial_focus_flow(lines,value,trace=trace,worker=worker,managed=initial_managed,budget=budget)
            except Exception:
                flow=_initial_focus_unknown(3)
            flow_out.clear();flow_out.update(flow)
        if type(counter_out) is dict:
            try:
                counter=_initial_focus_counters(lines,value,trace=trace,worker=worker,managed=initial_managed,
                    retirement_confirmed=retirement_confirmed,budget=budget)
            except Exception:
                counter=_initial_focus_counters_unknown(11)
            counter_out.clear();counter_out.update(counter)
        return value
    except TimeoutError:
        return unknown(10)
    except Exception:
        return unknown(code)


def source_menu_admission_summary(admission):
    """Serialize an actual sealed Gate; stored JSON never recreates its authority."""
    from collections.abc import Mapping
    from native_menu_source_admission import SourceMenuAdmission
    if type(admission) is not SourceMenuAdmission:raise ValueError('Actual source Gate is required')
    def plain(value):
        if isinstance(value,Mapping):return {key:plain(child) for key,child in value.items()}
        if type(value) is tuple:return [plain(child) for child in value]
        if type(value) in (str,int,bool,type(None)):return value
        if type(value) is float and math.isfinite(value):return value
        raise ValueError('Source Gate summary has a non-JSON identity field')
    return plain(admission.summary())


def require_hwp_launcher_receipt(value, writer, suite, *, source_admission=None):
    """Replay the one launcher without native calls or a document/Home claim."""
    from owned_native_menu import require_native_menu_action
    from lifecycle_smoke import require_hwp_census_receipt
    from home_routing_smoke import _filetime, _require_live_binding, _require_exit_and_closure
    try:
        assert writer['module']=='writer' and writer['case']=='native-menu-writer'
        assert type(value) is dict and value['kind']=='owned-native-hwp-launcher'
        assert not any(key in value for key in ('errorType','handleReleaseErrorType'))
        assert all(value[key] is True for key in ('success','normalExitVerified','handleReleased',
            'visibleOwnedMainWindow','originalOfficeHomeNativeAvailable'))
        assert all(value[key] is False for key in ('documentCreated','hwpApplicationHomeReady','cleanupPending'))
        assert value['launchKind']=='no-argument-launcher' and value['noArgumentBasis']=='native-new-hwp-shell-route'
        assert type(value['closeRequests']) is int and value['closeRequests']==1
        shell_pid,document=writer['shellPid'],writer['windowHwnd']
        authority={} if source_admission is None else dict(source_admission=source_admission)
        action=value['menuAction'];require_native_menu_action(action,shell_pid,document,'new-hwp',**authority)
        assert action['gesture'] is False
        assert action['binding']==dict(document=document,parent=writer['parentHwnd'],child=writer['childHwnd'],officePid=writer['officePid'])
        office=writer['nativeArchiveGeneration'];engine=action['originalEngine']
        assert (engine['pid'],engine['creationTime'])==(office['pid'],office['creationTime'])==(writer['officePid'],writer['officeCreationTime'])
        assert PureWindowsPath(engine['image'])==PureWindowsPath(office['image'])==PureWindowsPath(str(Path(suite)/'Office/program/soffice.bin'))
        shell=value['originalShell'];menu_shell=action['originalProcess']
        assert shell['kind']=='retained-suite-popen-process' and shell['pid']==menu_shell['pid']==shell_pid
        assert type(shell['handleValue']) is int and shell['handleValue']==menu_shell['handleValue']>0
        birth=_filetime(shell['nativeCreation']);assert birth==menu_shell['creationTime']
        shell_image=PureWindowsPath(str(Path(suite)/'OpenGeul.Office.exe'))
        assert PureWindowsPath(shell['nativeImage'])==PureWindowsPath(menu_shell['image'])==shell_image
        assert shell['nativeImageLength']==len(shell['nativeImage'].encode('utf-16-le'))//2
        assert type(shell['waitResult']) is int and shell['waitResult']==258
        assert type(shell['exitCode']) is int and shell['exitCode']==259
        activations=[row['originalProcess'] for row in writer['windowActivations'] if row['suiteHwnd']==document]
        assert activations and all((row['pid'],row['handleValue'],row['creationTime'])==(shell_pid,shell['handleValue'],birth)
            and PureWindowsPath(row['image'])==shell_image and row['waitResult']==258 for row in activations)
        executable=Path(suite)/'HWP/OpenGeul.exe';expected=PureWindowsPath(str(executable))
        censuses=value['censuses'];assert type(censuses) is list and 2<=len(censuses)<=451
        found=[require_hwp_census_receipt(row,shell_pid,birth,executable) for row in censuses]
        assert found[0] is None and found[-1]==value['generation']
        generation=value['generation'];assert set(generation)=={'pid','parentPid','executable','creationFileTime'}
        assert type(generation['pid']) is int and 0<generation['pid']<=0xffffffff
        assert generation['pid'] not in (shell_pid,writer['officePid'])
        assert type(generation['parentPid']) is int and generation['parentPid']==shell_pid
        assert PureWindowsPath(generation['executable'])==expected
        assert type(generation['creationFileTime']) is int and generation['creationFileTime']>censuses[0]['snapshotStartedFileTime']
        assert all(match is None or match==generation for match in found[1:])
        assert type(value['shellBindingChecks']) is int and value['shellBindingChecks']>=2*len(censuses)+3
        live=value['liveBinding'];_require_live_binding(live)
        assert (live['pid'],live['creationTime'])==(generation['pid'],generation['creationFileTime'])
        assert PureWindowsPath(live['nativeImage'])==PureWindowsPath(live['expectedImage'])==expected
        assert type(value['handleValue']) is int and value['handleValue']==live['handleValue']!=shell['handleValue']
        _require_exit_and_closure(value['exit'],[dict(pid=live['pid'],creationTime=live['creationTime'],
            handleValue=value['handleValue'],closeHandleResult=value['handleReleased'])],live)
        assert type(value['windowHwnd']) is int and value['windowHwnd']>0
        assert type(value['windowRootHwnd']) is type(value['windowPid']) is int
        assert value['windowRootHwnd']==value['windowHwnd'] and value['windowPid']==live['pid']
        assert type(value['webviewHwnds']) is list and 1<=len(value['webviewHwnds'])<=4096
        assert all(type(hwnd) is int and hwnd>0 and hwnd!=value['windowHwnd'] for hwnd in value['webviewHwnds'])
        assert type(value['originalOfficeHomeHwnd']) is int and value['originalOfficeHomeHwnd']==writer['originalHomeHwnd']>0
    except (AssertionError,KeyError,TypeError,ValueError,OverflowError,RecursionError):
        raise ValueError('Original native HWP launcher receipt is incomplete or foreign') from None
    return value


def _confirmed_shell_cleanup(record, pid, observed_exit):
    """Join the retained Popen observation to its producer's bounded cleanup."""
    try:
        receipt=record['testProcessCleanup']
        assert type(receipt) is dict and type(pid) is int and pid>0 and type(observed_exit) is int
        assert type(receipt['shellPid']) is int and receipt['shellPid']==pid
        assert type(receipt['shellExitCode']) is int and receipt['shellExitCode']==observed_exit
        assert type(receipt['forceRequested']) is bool and receipt['gracefulShutdownVerified'] is False
        if not receipt['forceRequested']:return receipt['disposition']=='already-exited'
        for key in ('commandBudgetStartedAt','commandBudgetDeadline','commandReturnedAt'):
            assert type(receipt[key]) in (int,float) and math.isfinite(receipt[key])
        assert type(receipt['commandBudgetSeconds']) is int and receipt['commandBudgetSeconds']==15
        assert receipt['commandBudgetDeadline']==receipt['commandBudgetStartedAt']+15
        assert receipt['commandBudgetStartedAt']<=receipt['commandReturnedAt']<=receipt['commandBudgetDeadline']
        assert type(receipt['commandExitCode']) is int
        if receipt['disposition']=='exit-zero-after-taskkill-not-found':
            return (observed_exit==0 and receipt['commandExitCode']==128 and record.get('cleanupExitRaceVerified') is True
                and type(record.get('cleanupProcessExitCode')) is int and record['cleanupProcessExitCode']==0)
        assert receipt['disposition']=='forced-stop-returned' and receipt['commandExitCode'] in (0,128)
        for key in ('exitWaitStartedAt','exitWaitDeadline','exitWaitReturnedAt'):
            assert type(receipt[key]) in (int,float) and math.isfinite(receipt[key])
        assert type(receipt['exitWaitStageCode']) is int and receipt['exitWaitStageCode']==2
        assert type(receipt['exitWaitBudgetSeconds']) is int and receipt['exitWaitBudgetSeconds']==5
        assert receipt['exitWaitStartedAt']==receipt['commandReturnedAt']
        assert receipt['exitWaitDeadline']==receipt['exitWaitStartedAt']+5
        assert receipt['exitWaitStartedAt']<=receipt['exitWaitReturnedAt']<=receipt['exitWaitDeadline']
        return True
    except (AssertionError,KeyError,TypeError,ValueError,OverflowError):return False


class WindowsSession:
    """Real native boundaries; construction itself acquires no resources."""
    actual_windows = True

    def __init__(self, suite, fixtures, output, module):
        self.suite, self.fixtures, self.output, self.module = suite, fixtures, output, module
        self.process = self.api = self.engine = None
        self.hwnd = self.parent = self.child = self.office_pid = 0
        self.home_hwnd = 0
        self.native_point_profile = False
        self.native_point_profile_version = 1
        self.native_identity_diagnostic = 0
        self.source_prepared = None

    def open(self, record):
        entry_deadline = time.monotonic() + 150
        assert os.name == 'nt' and __debug__, 'Actual Windows GUI with assertions is required'
        profile=getattr(self,'native_point_profile',False)
        profile_version=getattr(self,'native_point_profile_version',1)
        diagnostic=getattr(self,'native_identity_diagnostic',0)
        assert type(profile) is bool and type(profile_version) is int and profile_version in (1,2)
        assert profile or profile_version==1, 'A native point profile requires explicit opt-in'
        assert type(diagnostic) is int and diagnostic in (0,3)
        assert not diagnostic or profile and profile_version==2
        import windows_smoke as native
        import startup_smoke as startup
        import owned_native_menu as menu
        from pywinauto import Desktop
        self.native, self.menu, self.desktop = native, menu, Desktop
        options=native.source_menu_launch_options(self.source_prepared,deadline=entry_deadline) if self.source_prepared is not None else {}
        self.process = native.launch_suite(native.new_document_command(self.suite, self.module),
            self.suite, self.output, record['case'],**options)
        if profile:
            self.process.opengeul_native_menu_point_profile = True
            self.process.opengeul_native_menu_point_profile_version = profile_version
        if diagnostic:self.process.opengeul_native_menu_identity_diagnostic = diagnostic
        self.api = native.Windows()
        self.hwnd, self.parent, self.child, self.office_pid = native.verified_attachment(
            self.api, self.process, self.module)
        attachment = dict(hwnd=self.hwnd, parent=self.parent, child=self.child,
                          officePid=self.office_pid)
        record['nativeArchiveGeneration'] = native.capture_native_archive_generation(
            self.api, self.process, attachment)
        self.engine = startup.EngineProcessWitness(self.office_pid)
        record.update(shellPid=self.process.pid, windowHwnd=self.hwnd, parentHwnd=self.parent,
            childHwnd=self.child, officePid=self.office_pid,
            officeCreationTime=self.engine.creation_time, nativeParentVerified=True)
        self.home_hwnd = int(self.api.home(self.process) or 0)
        self._home_ready()
        record['originalHomeHwnd'] = self.home_hwnd
        self._observe_open_focus(record, 1)
        self.desktop(backend='win32').window(handle=self.hwnd).wrapper_object().maximize()
        self._observe_open_focus(record, 2)
        native.activate_owned_suite(self.api, self.process, self.hwnd, record)
        self._observe_open_focus(record, 3)
        self._await_native_menu_ready(record, entry_deadline)
        self.api.require_foreground(self.hwnd)

    def _await_native_menu_ready(self, record, deadline, *, probe=None, clock=None, pause=None):
        """Observe Ready1 on the original generation within startup's remainder.

        This routing hint is neither editor focus nor native menu acceptance.
        Synchronous calls cannot guarantee a hard wall bound; late readiness is
        rejected. No activation, input, UIA client or replacement HWND is used.
        """
        from types import SimpleNamespace
        from suite_window_activation import NativeActivationProbe
        from counted_editor_shortcuts import _same_image
        clock=clock or time.monotonic;pause=pause or time.sleep
        started=clock()
        result=dict(schemaVersion=1,acceptanceEligible=0,attempted=1,completed=0,
            stageCode=1,samples=0,ownershipChecks=0,elapsedMs=0,remainingAtStartMs=0,
            first={},last={})
        record['stage']='await-native-menu-ready';record['nativeMenuReadiness']=result
        def budget():
            if clock()>=deadline:
                result['stageCode']=5
                raise AssertionError('Original native startup readiness deadline expired')
        try:
            assert type(deadline) in (int,float) and math.isfinite(deadline)
            result['remainingAtStartMs']=max(0,int((deadline-started)*1000))
            budget()
            assert 0<deadline-started<=150, 'Invalid original startup readiness remainder'
            probe=probe if probe is not None else NativeActivationProbe(deadline,clock)
            original=(self.process.pid,int(self.process._handle),int(self.engine.handle),self.engine.creation_time,
                self.hwnd,self.parent,self.child,self.office_pid)
            assert original==self._opening_focus_identity, 'Original startup readiness binding changed'
            assert len({self.hwnd,self.parent,self.child})==3
            shell=record['windowActivations'][0]['originalProcess']
            archive=record['nativeArchiveGeneration']
            opening=record['openingFocusObservations'][-1]
            assert opening['phaseCode']==3
            assert shell['pid']==self.process.pid and shell['handleValue']==int(self.process._handle)
            assert 0<shell['creationTime']<=self.engine.creation_time==archive['creationTime']
            assert archive['pid']==self.office_pid!=self.process.pid
            assert _same_image(shell['image'],self.suite/'OpenGeul.Office.exe')
            assert _same_image(archive['image'],self.suite/'Office/program/soffice.bin')
            window_identity=None
            def owned():
                nonlocal window_identity
                result['stageCode']=2;budget()
                assert original==(self.process.pid,int(self.process._handle),int(self.engine.handle),self.engine.creation_time,
                    self.hwnd,self.parent,self.child,self.office_pid), 'Original startup readiness owner changed'
                assert self.process.poll() is None and not self.engine.exited(0)
                assert self.api.attachment(self.hwnd)==(self.parent,self.child,self.office_pid)
                for process,pid,handle,birth,image in (
                    (self.process,self.process.pid,original[1],shell['creationTime'],shell['image']),
                    (SimpleNamespace(_handle=original[2]),self.office_pid,original[2],archive['creationTime'],archive['image'])):
                    value=probe.process_snapshot(process);budget()
                    assert (value['pid'],value['handleValue'],value['creationTime'],value['waitResult'])==(pid,handle,birth,258)
                    assert _same_image(value['image'],image), 'Original startup readiness image changed'
                windows=[]
                for hwnd,pid in ((self.hwnd,self.process.pid),(self.parent,self.process.pid),(self.child,self.office_pid)):
                    assert probe._call(probe.user.IsWindow,hwnd)
                    observed_pid=ctypes.c_uint32()
                    thread=int(probe._call(probe.user.GetWindowThreadProcessId,hwnd,ctypes.byref(observed_pid)))
                    root=int(probe._call(probe.user.GetAncestor,hwnd,2) or 0)
                    parent=int(probe._call(probe.user.GetAncestor,hwnd,1) or 0)
                    assert observed_pid.value==pid and thread>0 and root==self.hwnd
                    assert probe._call(probe.user.IsWindowVisible,hwnd) and probe._call(probe.user.IsWindowEnabled,hwnd)
                    assert not probe._call(probe.user.IsIconic,hwnd)
                    windows.append((hwnd,pid,thread,root,parent))
                assert windows[0][2]==windows[1][2]
                assert (windows[0][2],windows[2][2])==(opening['hostGui']['threadId'],opening['engineGui']['threadId'])
                assert (windows[1][4],windows[2][4])==(self.hwnd,self.parent)
                current=tuple(windows)
                if window_identity is None:window_identity=current
                assert current==window_identity, 'Original startup readiness HWND thread changed'
                assert int(probe._call(probe.user.GetForegroundWindow) or 0)==self.hwnd
                for thread in (windows[0][2],windows[2][2]):
                    gui=self.api.query_gui_thread_info(thread);budget()
                    assert int(gui.hwndActive or 0)==self.hwnd
                    assert not (int(gui.flags)&0x1e) and not gui.hwndCapture and not gui.hwndMenuOwner
                budget();result['ownershipChecks']+=1
            while True:
                budget()
                if result['samples']>=3001:
                    result['stageCode']=6
                    raise AssertionError('Original native readiness sample bound exhausted')
                owned();result['stageCode']=3
                hint=probe._call(self.api.user.GetPropW,self.hwnd,'OpenGeul.Office.NativeMenuReady')
                assert hint is None or type(hint) is int and hint in (0,1), 'Invalid native menu readiness hint'
                row=dict(readyHint=int(hint or 0),elapsedMs=max(0,int((clock()-started)*1000)),
                    remainingMs=max(0,int((deadline-clock())*1000)))
                result['samples']+=1
                if not result['first']:result['first']=dict(row)
                result['last']=dict(row)
                owned();budget()
                if hint==1:
                    result.update(completed=1,stageCode=4)
                    return
                pause(min(.05,max(0,deadline-clock())))
        finally:
            result['elapsedMs']=max(0,int((clock()-started)*1000))
            if type(deadline) in (int,float) and math.isfinite(deadline) and clock()>=deadline:
                complete=result['completed'];result.update(completed=0,stageCode=5)
                if complete:raise AssertionError('Native readiness finalization exceeded startup deadline')

    def _observe_open_focus(self, record, phase):
        """Three passive numeric observations; a ready hint is not editor proof.

        In particular phase 1 with attachReadyObserved=0 cannot establish that
        product attachment had completed before the harness maximized the form.
        These fixed native queries introduce no wait, input, or COM client.
        """
        assert type(phase) is int and phase in (1, 2, 3)
        rows = record.get('openingFocusObservations', [])
        assert len(rows) == phase-1 and [row['phaseCode'] for row in rows] == list(range(1, phase))
        def identity():
            return (self.process.pid, int(self.process._handle), int(self.engine.handle), self.engine.creation_time,
                self.hwnd, self.parent, self.child, self.office_pid)
        current = identity()
        original = getattr(self, '_opening_focus_identity', current)
        def owned():
            assert current == original == identity()
            assert self.process.poll() is None and not self.engine.exited(0)
            assert self.api.attachment(self.hwnd) == (self.parent, self.child, self.office_pid)
            generation = record['nativeArchiveGeneration']
            assert (generation['pid'], generation['creationTime']) == (self.office_pid, self.engine.creation_time)
        owned()
        self._opening_focus_identity = original
        def window(hwnd):
            hwnd = int(hwnd or 0)
            return dict(hwnd=hwnd, pid=int(self.api.pid(hwnd)) if hwnd else 0,
                rootHwnd=int(self.api.user.GetAncestor(hwnd, 2) or 0) if hwnd else 0)
        def gui(hwnd):
            thread = int(self.api.user.GetWindowThreadProcessId(hwnd, None))
            assert thread > 0, 'Original focus observation thread is unavailable'
            state = self.native.GuiThreadInfo(cbSize=ctypes.sizeof(self.native.GuiThreadInfo))
            assert self.api.user.GetGUIThreadInfo(thread, ctypes.byref(state)), 'Original focus observation query failed'
            focus = window(state.hwndFocus)
            return dict(threadId=thread, activeHwnd=int(state.hwndActive or 0), focusHwnd=focus['hwnd'],
                focusPid=focus['pid'], focusRootHwnd=focus['rootHwnd'], captureHwnd=int(state.hwndCapture or 0),
                menuOwnerHwnd=int(state.hwndMenuOwner or 0), flags=int(state.flags))
        host, engine = gui(self.hwnd), gui(self.child)
        foreground = window(self.api.user.GetForegroundWindow())
        hint = self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.NativeMenuReady')
        assert hint is None or type(hint) is int and 0 <= hint < 2**64
        row = dict(phaseCode=phase, nativeReadyHint=int(hint or 0), attachReadyObserved=int(hint == 1),
            hostGui=host, engineGui=engine, foreground=foreground)
        owned()
        assert len(json.dumps(rows+[row], separators=(',', ':')).encode()) <= 128*1024
        record.setdefault('openingFocusObservations', []).append(row)

    def ready(self):
        return self.menu.native_menu_active(self.api, self.process, self.hwnd) is True

    def gesture(self, name, record):
        result = self.menu.inspect_native_menu(self.api, self.process, self.hwnd,
            record, name)
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-native-menu-action' and result.get('gesture') is True
        assert result.get('command') == name, 'Native gesture receipt belongs to another operation'
        return dict(gesture=name, success=True, receipt=result)

    def _owned_blank(self):
        assert self.process.poll() is None and not self.engine.exited(0)
        assert all(self.api.user.IsWindow(h) for h in (self.hwnd, self.parent, self.child))
        assert (self.api.pid(self.hwnd), self.api.pid(self.parent), self.api.pid(self.child)) == (
            self.process.pid, self.process.pid, self.office_pid)
        assert self.api.user.GetAncestor(self.hwnd, 2) == self.hwnd
        assert self.api.user.IsChild(self.hwnd, self.parent) and self.api.user.IsChild(self.parent, self.child)
        assert (int(self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.ParentHwnd') or 0),
                int(self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.ChildHwnd') or 0)) == (self.parent, self.child)
        self.api.require_foreground(self.hwnd)

    def screenshot(self, record, *, initial=False):
        assert type(initial) is bool and self.module in MODULES and record.get('case') == 'native-menu-' + self.module
        self._owned_blank()
        capture_error = None
        try:
            image = self.desktop(backend='win32').window(handle=self.hwnd).wrapper_object().capture_as_image()
        except Exception as exc:
            if not initial: raise
            capture_error = type(exc).__name__
        # Ownership failures remain primary even if the optional image failed.
        self._owned_blank()
        if capture_error is not None:
            record['initialScreenshotErrorType'] = capture_error
            return None
        name = record['case'] + ('-initial-chrome.png' if initial else '-chrome.png')
        try:
            cropped = image.crop((0, 0, image.width, min(240, image.height)))
            with (self.output / name).open('xb') as stream:
                cropped.save(stream, format='PNG')
        except Exception as exc:
            if not initial: raise
            record['initialScreenshotErrorType'] = type(exc).__name__
            return None
        record['initialScreenshotScope' if initial else 'screenshotScope'] = 'owned-fresh-blank-form-top-240-pixels'
        return name

    def _native_command(self, command, record):
        result = self.menu.click_native_menu_action(self.api, self.process, self.hwnd, record, command)
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-native-menu-action' and result.get('gesture') is False
        assert result.get('command') == command
        return result

    def view_roundtrip(self, record):
        """Keep the original blank document through measured native view changes."""
        from owned_fullscreen import toggle_native_fullscreen
        from owned_native_menu import decode_status_sequence
        assert self.module in VIEW_MODULES
        self._owned_blank()
        assert self.ready() is True
        value = dict(kind='native-view-roundtrip', module=self.module, success=False,
            previewActions=[], observations=[], fullscreenActions=[], coreCommands=[])
        record['nativeViewRoundtrip'] = value
        identity = None
        previous_status = previous_observation_finish = None
        def checked(receipt, kind):
            nonlocal identity
            assert type(receipt) is dict and receipt.get('success') is True and receipt.get('kind') == kind
            binding = receipt.get('binding')
            expected = dict(document=self.hwnd, parent=self.parent, child=self.child, officePid=self.office_pid)
            assert type(binding) is dict and all(type(binding.get(key)) is int and binding[key] == item
                for key, item in expected.items()), 'Native view receipt belongs to another attachment'
            shell, engine = receipt.get('originalProcess'), receipt.get('originalEngine')
            assert type(shell) is dict and type(engine) is dict
            assert (shell.get('pid'), shell.get('handleValue'), shell.get('waitResult')) == (
                self.process.pid, int(self.process._handle), 258)
            assert Path(shell['image']).resolve() == self.suite/'OpenGeul.Office.exe'
            assert type(shell.get('creationTime')) is int and shell['creationTime'] > 0
            generation = record['nativeArchiveGeneration']
            assert all(type(engine.get(key)) is int and engine[key] == generation[key]
                for key in ('pid', 'creationTime'))
            assert engine['pid'] == self.office_pid and engine.get('waitResult') == 258
            assert Path(engine['image']).resolve() == Path(generation['image']).resolve() == self.suite/'Office/program/soffice.bin'
            current = (shell['creationTime'], engine['pid'], engine['creationTime'])
            assert identity is None or current == identity, 'Native view changed the original process generations'
            identity = current
            assert receipt.get('engineHandleReleased') is True and receipt.get('providerClientReleased') is True
            assert receipt.get('dpiScope', {}).get('verified') is True and receipt['dpiScope'].get('restored') is True
            times = [receipt.get(key) for key in ('startedAt', 'deadline', 'finishedAt')]
            assert all(type(item) in (int, float) and math.isfinite(item) for item in times)
            start, deadline, finish = times
            assert start <= finish < deadline <= start + 5
            return receipt
        def observe(preview, menu_visible):
            nonlocal previous_status, previous_observation_finish
            receipt = checked(self.menu.observe_native_view(self.api, self.process, self.hwnd, record,
                module=self.module, preview=preview, menu_visible=menu_visible, hold_seconds=3, seconds=5),
                'owned-native-view-observation')
            assert receipt.get('module') == self.module and receipt.get('preview') is preview
            assert receipt.get('menuVisible') is menu_visible and receipt.get('holdSeconds') == 3
            observed = receipt.get('observedSeconds')
            assert type(observed) in (int, float) and math.isfinite(observed) and 3 <= observed < 5
            assert observed <= receipt['finishedAt'] - receipt['startedAt'], 'Native view observation exceeds its actual elapsed time'
            assert type(receipt.get('samples')) is list and 2 <= len(receipt['samples']) <= 64
            assert receipt.get('statusRpcProved') is True and type(receipt.get('inputCallAttempts')) is int and receipt['inputCallAttempts'] == 0
            assert type(receipt.get('statusSequenceVersion')) is int and receipt['statusSequenceVersion'] == 1
            baseline, completed = (receipt.get(key) for key in ('firstTargetStartedSequence','lastTargetCompletedSequence'))
            assert all(type(item) is int and 0 <= item < (1 << 28) for item in (baseline,completed))
            assert completed > baseline
            assert previous_observation_finish is None or receipt['startedAt'] >= previous_observation_finish
            first = first_started = last_at = None
            sequence = previous_status
            for sample in receipt['samples']:
                assert type(sample) is dict and type(sample.get('state')) is dict
                state, at = sample['state'], sample.get('observedAt')
                assert type(at) in (int,float) and math.isfinite(at)
                assert receipt['startedAt'] <= at <= receipt['finishedAt'] and at < receipt['deadline']
                assert last_at is None or at >= last_at
                last_at = at
                decoded = decode_status_sequence(state['statusSequenceRaw'])
                supplied = sample.get('statusSequence')
                assert type(supplied) is dict and set(supplied) == {'version','started','completed'}
                assert all(type(item) is int for item in supplied.values()) and supplied == decoded
                assert sequence is None or all(decoded[key] >= sequence[key] for key in ('started','completed'))
                sequence = decoded
                assert all(type(state.get(key)) is int and state[key] in (0,1)
                    for key in ('nativeMenuBarCount','previewIndicatorCount'))
                matched = state['nativeMenuBarCount'] == int(menu_visible) and state['previewIndicatorCount'] == int(preview)
                assert type(sample.get('targetMatched')) is bool and sample['targetMatched'] is matched
                if not matched:
                    first = first_started = None
                elif first is None:
                    first, first_started = at, decoded['started']
            assert first is not None and last_at - first >= 3
            assert type(receipt.get('settledAt')) in (int,float) and math.isfinite(receipt['settledAt'])
            assert receipt['settledAt'] == first and observed == last_at - first
            assert first_started == baseline and sequence['completed'] == completed
            previous_status, previous_observation_finish = sequence, receipt['finishedAt']
            value['observations'].append(receipt)
        def core():
            receipt = checked(self.gesture('core-commands', record)['receipt'], 'owned-native-menu-action')
            assert receipt.get('coreCommandsVerified') is True and receipt.get('coreCommands') == list(CORE_COMMANDS)
            assert receipt.get('focusReturned') is True
            value['coreCommands'].append(receipt)
        record['stage'] = 'print-preview-enter'
        value['previewActions'].append(checked(self._native_command('printPreview', record), 'owned-native-menu-action'))
        observe(True, True)
        record['stage'] = 'print-preview-leave'
        value['previewActions'].append(checked(self._native_command('printPreview', record), 'owned-native-menu-action'))
        observe(False, True)
        core()
        for menu_visible in (False, True):
            record['stage'] = 'fullscreen-enter' if not menu_visible else 'fullscreen-leave'
            receipt = checked(toggle_native_fullscreen(self.api, self.process, self.hwnd, record,
                module=self.module, seconds=5), 'owned-native-fullscreen-toggle')
            assert receipt.get('module') == self.module and receipt.get('focusReturned') is True
            assert all(type(receipt.get(key)) is int for key in ('inputCallAttempts', 'requestedInputs', 'insertedInputs'))
            assert (receipt['inputCallAttempts'], receipt['requestedInputs'], receipt['insertedInputs']) == (1, 6, 6)
            value['fullscreenActions'].append(receipt)
            observe(False, menu_visible)
        core()
        self._owned_blank()
        assert self.ready() is True
        assert self._home_ready(active=False) is True
        value['originalHomeSurvived'] = True
        value['success'] = True
        return value

    def _wait_original_closed(self):
        self.native.wait_for(lambda: not self.api.user.IsWindow(self.hwnd), seconds=20)
        self.native.wait_for(lambda: not self.api.user.IsWindow(self.child), seconds=10)

    def _home_ready(self, *, active=False):
        assert self.home_hwnd and self.process.poll() is None
        assert self.api.home(self.process) == self.home_hwnd
        assert self.api.pid(self.home_hwnd) == self.process.pid
        assert self.api.user.GetAncestor(self.home_hwnd, 2) == self.home_hwnd
        assert not self.api.user.GetPropW(self.home_hwnd, 'OpenGeul.Office.ChildHwnd')
        if not active:
            return True
        foreground = self.api.user.GetForegroundWindow()
        return bool(self.api.user.IsWindowVisible(self.home_hwnd) and foreground
            and self.api.user.GetAncestor(foreground, 2) == self.home_hwnd)

    def _cancel_calc_exit(self, record, *, deadline):
        from owned_menu_cancel import cancel_native_menu_prompt
        caption = 'OpenGeul Calc'
        assert deadline > time.monotonic(), 'Original Calc cancel readiness deadline expired'
        def find():
            dialogs = [h for h in self.api.windows(self.process.pid)
                if self.api.user.GetWindow(h, 4) == self.hwnd and self.api.title(h) == caption]
            assert len(dialogs) <= 1, 'Calc close prompt is ambiguous'
            if not dialogs:
                return None
            dialog, = dialogs
            self.native.require_dialog_identity(self.api.pid(dialog), self.process.pid,
                self.api.user.GetWindow(dialog, 4), self.hwnd, self.api.title(dialog),
                caption, self.api.class_name(dialog))
            return dialog
        dialog = self.native.wait_for(find, seconds=deadline - time.monotonic())
        self.api.require_foreground(dialog)
        remaining = deadline - time.monotonic()
        assert remaining > 0, 'Original Calc cancel readiness deadline expired'
        result = cancel_native_menu_prompt(self.api, self.process, self.hwnd, record,
            dialog, caption, seconds=min(5, remaining))
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-shell-menu-cancel'
        snapshots = result.get('snapshots')
        assert type(snapshots) is list and snapshots and all(type(row) is dict
            and row.get('promptSchemaVerified') is True for row in snapshots), \
            'Bounded Calc prompt schema proof is missing'
        assert not self.api.user.IsWindow(dialog), 'Original Calc prompt survived its one Cancel action'
        record['nativeExitCancelAction'] = result
        return True

    def hwp_launcher(self, record):
        """One no-argument native launcher, never an HWP document-creation claim."""
        import lifecycle_smoke as lifecycle
        from home_routing_smoke import freeze_live_process, retained_exit
        assert self.module == 'writer'
        self._owned_blank()
        self.hwp_unretired = True  # Uncertain dispatch/binding must never reach tree cleanup.
        value = dict(kind='owned-native-hwp-launcher', success=False, launchKind='no-argument-launcher',
            noArgumentBasis='native-new-hwp-shell-route', documentCreated=False,
            hwpApplicationHomeReady=False, originalOfficeHomeHwnd=self.home_hwnd,
            censuses=[], shellBindingChecks=0, cleanupPending=True,
            closeRequests=0, normalExitVerified=False, handleReleased=False)
        record['nativeHwpLauncher'] = value
        executable = (self.suite / 'HWP/OpenGeul.exe').resolve(strict=True)
        assert executable.is_file()
        shell = {}; creation = lifecycle.retained_writer_shell(self.process, self.suite, shell)
        value['originalShell'] = shell
        shell_identity = (self.process.pid, int(self.process._handle), creation)
        bound = None; primary = None
        def owner():
            current = {}
            observed = lifecycle.retained_writer_shell(self.process, self.suite, current)
            assert (self.process.pid, int(self.process._handle), observed) == shell_identity
            value['shellBindingChecks'] += 1
            assert self.api.attachment(self.hwnd) == (self.parent, self.child, self.office_pid)
            assert not self.engine.exited(0)
            assert self._home_ready() is True
            assert self.api.user.IsWindowVisible(self.home_hwnd) and self.api.user.IsWindowEnabled(self.home_hwnd)
        def census():
            owner(); rows = value['censuses']; assert len(rows) < 451
            evidence = {}; rows.append(evidence)
            found = lifecycle._hwp_child_process(self.process.pid, executable,
                shell_creation=creation, evidence=evidence)
            assert lifecycle.require_hwp_census_receipt(evidence,self.process.pid,creation,executable) == found
            owner(); return found
        try:
            assert census() is None, 'The fresh Writer already owns an HWP generation'
            before = value['censuses'][0]['snapshotStartedFileTime']
            value['menuAction'] = self._native_command('new-hwp', record)
            found = self.native.wait_for(census, seconds=45)
            assert found['parentPid'] == self.process.pid and Path(found['executable']).resolve() == executable
            assert type(found['creationFileTime']) is int and found['creationFileTime'] > before
            value['generation'] = dict(found)
            bound = lifecycle.BoundHwpProcess(found['pid'], executable, expected_creation=found['creationFileTime'])
            freeze_live_process(bound, executable, value.setdefault('liveBinding', {}))
            def visible():
                owner(); assert bound.live()
                roots = [h for h in self.api.windows(bound.pid)
                    if self.api.class_name(h) in ('Tauri Window', 'Chrome_WidgetWin_1')]
                assert len(roots) <= 1, 'Owned HWP launcher root is ambiguous'
                if not roots: return None
                hwnd, = roots
                assert self.api.pid(hwnd) == bound.pid and self.api.user.GetAncestor(hwnd,2) == hwnd
                assert self.api.user.IsWindowVisible(hwnd) and self.api.user.IsWindowEnabled(hwnd)
                window = self.desktop(backend='win32').window(handle=hwnd).wrapper_object()
                browsers = [int(item.handle) for item in window.descendants()
                    if item.class_name() in ('Chrome_WidgetWin_0', 'Chrome_WidgetWin_1', 'Chrome_RenderWidgetHostHWND')]
                return (hwnd,browsers) if browsers else None
            hwnd,browsers = self.native.wait_for(visible, seconds=75)
            value.update(windowHwnd=int(hwnd), webviewHwnds=browsers, visibleOwnedMainWindow=True,
                windowPid=bound.pid, windowRootHwnd=int(hwnd), originalOfficeHomeNativeAvailable=True)
            owner(); assert bound.live()
            self.api.request_close(hwnd,bound.pid); value['closeRequests'] = 1
            self.native.wait_for(lambda:not self.api.user.IsWindow(hwnd), seconds=25)
            self.native.wait_for(lambda:not bound.live(), seconds=25)
            retained_exit(bound, value.setdefault('exit', {})); value['normalExitVerified'] = True
            owner()
            self.native.activate_owned_suite(self.api,self.process,self.hwnd,record)
            self._owned_blank()
        except BaseException as exc:
            primary = exc; value['errorType'] = type(exc).__name__; raise
        finally:
            if bound is not None:
                try:
                    value['handleValue'] = int(bound.handle)
                    bound.close(); value['handleReleased'] = bound.handle is None
                    assert value['handleReleased'] is True
                except BaseException as exc:
                    value['handleReleaseErrorType'] = type(exc).__name__
                    if primary is None: raise
            if value['normalExitVerified'] and value['handleReleased']: self.hwp_unretired = False
            value['cleanupPending'] = self.hwp_unretired
        value['success'] = value['normalExitVerified'] and value['handleReleased'] and not value['cleanupPending']
        assert value['success'] is True
        return value

    def finish(self, record):
        saved_base = None
        if self.module == 'base':
            # A private fresh target avoids changing the shared fixture set used
            # by the original two full GUI runs.
            owned = self.output / 'native-menu-base-generated'
            owned.mkdir(exist_ok=False)
            saved_base = self.native.save_new_base(self.api, self.process, self.hwnd,
                owned, self.output, record)
            assert record['baseSaveMenuAction']['kind'] == 'owned-native-menu-action', \
                'Native Base Save must not be qualified by the WinForms fallback'
        if self.module == 'writer':
            self._native_command('home', record)
            self._wait_original_closed()
            self.native.wait_for(lambda: self._home_ready(active=True), seconds=10)
            self.api.require_foreground(self.home_hwnd)
            record['nativeHomeVerified'] = True
        elif self.module in ('draw', 'math'):
            self._native_command('close', record)
            self._wait_original_closed()
            record['nativeCloseVerified'] = True
        elif self.module == 'calc':
            exit_deadline = time.monotonic() + 20  # Existing close-prompt bound, including the menu action.
            self._native_command('exit', record)
            assert self._cancel_calc_exit(record, deadline=exit_deadline) is True
            self._owned_blank()
            assert self.ready() is True
            record['postExitCancelMenu'] = self.gesture('open-escape', record)
            record['nativeExitCancelVerified'] = True
            from generated_calc_close import freeze_generated_blank_calc
            proof = freeze_generated_blank_calc(self.suite, self.api, self.process,
                self.hwnd, self.child, record)
            self.native.close_document(self.api, self.process, self.hwnd, self.child,
                record, calc_close_proof=proof)
        elif self.module == 'base':
            self._native_command('exit', record)
            self._wait_original_closed()
            self.process.wait(timeout=25)
            assert self.process.returncode == 0
            assert not self.api.user.IsWindow(self.home_hwnd), 'Native Exit left the original Home alive'
            record['nativeExitVerified'] = True
        else:
            self.native.close_document(self.api, self.process, self.hwnd, self.child, record)
        if self.module != 'base':
            self.native.close_home(self.api, self.process, record)
        record['officeExited'] = self.engine.exited(10)
        assert record['officeExited'], 'Original native engine survived normal menu scenario shutdown'
        record['officeExitCode'] = self.engine.code()
        assert record['officeExitCode'] == 0 and self.process.returncode == 0
        if saved_base is not None:
            record['savedBaseEvidence'] = self.native.saved_base_evidence(saved_base)
        record['cleanClose'] = True
        return True

    def cleanup(self, record):
        shell_done = True
        callback_done = True
        engine_done = engine_released = self.process is None
        if self.process is not None:
            record['forcedCleanupRequired'] = self.process.poll() is None
            if getattr(self,'hwp_unretired',False):
                record['shellCleanupSuppressedForHwp'] = True
            else:
                self.native.stop_owned_test_process(self.process, record)
            record['shellExitCode'] = self.process.poll()
            shell_done = _confirmed_shell_cleanup(record,self.process.pid,record['shellExitCode'])
            record['shellCleanupConfirmed'] = shell_done
        engine_exit_deadline = time.monotonic() + 5
        if self.engine is not None:
            try:
                engine_done = self.engine.exited(5)
                record['officeExitedAfterCleanup'] = engine_done
            finally:
                handle = self.engine.handle
                engine_released = bool(handle and self.engine.close_handle(handle))
                record['engineHandleReleased'] = engine_released
                if engine_released:
                    self.engine.handle = None
        if getattr(self,'native_point_profile',False) or getattr(self,'source_prepared',None) is not None:
            from native_menu_msaa_hit import pending_msaa_hit
            lease = pending_msaa_hit()
            if lease is not None:
                callback_done = False
                if engine_done:
                    try:
                        record['nativePointCleanup'] = lease.retire(engine_exit_deadline)
                        callback_done = lease.pending is False
                    except BaseException:
                        record['nativePointCleanupErrorCode'] = 1
        record['nativePointCallbackRetired'] = callback_done
        return bool(shell_done and engine_done and engine_released and callback_done and not getattr(self,'hwp_unretired',False))


def run_case(suite, fixtures, output, module, *, session_factory=WindowsSession, source_prepared=None):
    if module not in MODULES:
        raise ValueError('Unknown native menu module')
    record = dict(case='native-menu-' + module, module=module, success=False,
        kind='native-menu-gesture-case', stage='open', gestures=[],
        keyboardInputVerified=False, contentMutationVerified=False,
        scenarioCompleted=False, actualWindowsExecuted=False,
        viewRoundtripCompleted=False, viewPhysicalVerified=False,
        nativeMenuVerified=False, cleanupConfirmed=False, cleanClose=False,
        hwpLauncherCompleted=False, nativeHwpMenuLaunchExecuted=False,
        initialFocusTraceAfterRetirement=_initial_focus_retired_unknown(12,attempted=False),
        initialFocusFlowAfterRetirement=_initial_focus_retired_unknown(12,attempted=False),
        initialFocusCountersAfterRetirement=_initial_focus_counters_unknown(12))
    started = time.monotonic()
    session = None
    try:
        session = session_factory(suite, fixtures, output, module)
        diagnostic=getattr(session,'native_identity_diagnostic',0)
        assert type(diagnostic) is int and diagnostic in (0,3)
        if diagnostic:record.update(diagnosticProfile=3,diagnosticOnly=1,acceptanceEligible=0,diagnosticComplete=0)
        record['actualWindowsExecuted'] = session.actual_windows is True and os.name == 'nt'
        session.open(record)
        if source_prepared is not None:
            from native_menu_source_selection import PreparedSourceMenu, SourceMenuSelection
            from native_menu_source_admission import SourceMenuAdmission
            assert type(source_prepared) is PreparedSourceMenu and type(source_prepared.admission) is SourceMenuAdmission
            assert getattr(session,'source_prepared',None) is source_prepared
            selection=getattr(session.process,'opengeul_source_menu_selection',None)
            assert type(selection) is SourceMenuSelection and selection.prepared is source_prepared
            record.update(nativePointProfileVersion=4,sourceMenuAdmission=source_menu_admission_summary(source_prepared.admission))
        record['stage'] = 'require-native-menu'
        assert session.ready() is True, 'The actual native menu surface is unavailable'
        record['stage'] = 'capture-initial-owned-blank-chrome'
        initial = session.screenshot(record, initial=True)
        if initial is not None: record['initialScreenshot'] = initial
        for index, gesture in enumerate(GESTURES):
            record['stage'] = gesture
            result = session.gesture(gesture, record)
            if diagnostic:
                raise AssertionError('The selected identity diagnostic returned to its scenario')
            assert type(result) is dict and result.get('success') is True
            assert result.get('gesture') == gesture
            record['gestures'].append(dict(index=index, gesture=gesture, receipt=result))
        if module in VIEW_MODULES:
            record['stage'] = 'native-view-roundtrip'
            result = session.view_roundtrip(record)
            assert type(result) is dict and result.get('success') is True
            assert result.get('kind') == 'native-view-roundtrip' and result.get('module') == module
            record['nativeViewRoundtrip'] = result
            record['viewRoundtripCompleted'] = True
        record['stage'] = 'capture-owned-blank-chrome'
        record['screenshot'] = session.screenshot(record)
        if module == 'writer':
            record['stage'] = 'native-hwp-launcher'
            result = session.hwp_launcher(record)
            assert type(result) is dict and result.get('success') is True
            assert result.get('kind') == 'owned-native-hwp-launcher'
            if type(session) is WindowsSession:
                authority={}
                if source_prepared is not None:
                    selection=session.process.opengeul_source_menu_selection
                    assert selection.prepared is source_prepared
                    authority=dict(source_admission=selection.prepared.admission)
                require_hwp_launcher_receipt(result,record,suite,**authority)
            record['hwpLauncherCompleted'] = True
        record['stage'] = 'close-original-document-and-home'
        assert session.finish(record) is True
        record.update(success=True, scenarioCompleted=True)
    except BaseException as exc:
        if not isinstance(exc,Exception):
            if source_prepared is None:raise
            import native_menu_msaa_hit as helper
            if not source_menu_pending(helper):raise
            record['sourceMenuCohortPending']=True
        record['errorType'] = type(exc).__name__
    finally:
        if session is not None:
            flow=_initial_focus_unknown(1)
            counter=_initial_focus_counters_unknown(9)
            try:
                record['initialFocusTrace'] = capture_initial_focus_trace(session, record,flow_out=flow,counter_out=counter)
            except Exception:
                record['initialFocusTrace'] = _initial_focus_unknown(11)
            record['initialFocusFlow']=flow
            record['initialFocusCounters']=counter
            expected_retirement_identity=None
            try:
                original=session._opening_focus_identity
                if type(original) is tuple:expected_retirement_identity=tuple(original)
            except Exception:
                pass
            try:
                record['cleanupConfirmed'] = session.cleanup(record) is True
            except Exception as exc:
                record['cleanupErrorType'] = type(exc).__name__
            if record['cleanupConfirmed']:
                flow=_initial_focus_retired_unknown(1)
                counter=_initial_focus_counters_unknown(9)
                try:
                    record['initialFocusTraceAfterRetirement'] = capture_initial_focus_trace(session,record,
                        retired=True,expected_identity=expected_retirement_identity,flow_out=flow,counter_out=counter)
                except Exception:
                    record['initialFocusTraceAfterRetirement'] = _initial_focus_retired_unknown(11)
                record['initialFocusFlowAfterRetirement']=flow
                record['initialFocusCountersAfterRetirement']=counter
        if not record['cleanupConfirmed']:
            record['success'] = False
        if record.get('diagnosticProfile')==3:
            record['success']=record['scenarioCompleted']=False
            for action in record.get('nativeMenuActions',[]):
                interop=action.get('uiaInterop',{})
                packet=interop.get('identityDiagnosticResult')
                control=interop.get('identityDiagnosticControl')
                if packet is not None:
                    from owned_native_menu import _identity_diagnostic_packet
                    record['identityDiagnosticResult']=_identity_diagnostic_packet(packet)
                if type(control) is dict:
                    from owned_native_menu import _identity_diagnostic_control
                    assert control.keys()==_identity_diagnostic_control().keys()
                    assert all(type(n) is int and 0<=n<=0xffffffff for n in control.values())
                    assert control['schemaVersion']==control['diagnosticProfile']==3 and control['diagnosticOnly']==1
                    assert control['acceptanceEligible']==control['localKnown']==control['localMatch']==0
                    record['identityDiagnosticControl']=copy.deepcopy(control)
                    record['diagnosticComplete']=int(control.get('diagnosticComplete')==1 and record['cleanupConfirmed'])
        record['nativeMenuVerified'] = record['success'] and record['actualWindowsExecuted']
        record['nativeHwpMenuLaunchExecuted'] = bool(record['nativeMenuVerified'] and record['hwpLauncherCompleted']
            and type(session) is WindowsSession)
        record['viewPhysicalVerified'] = bool(record['nativeMenuVerified'] and record['viewRoundtripCompleted']
            and type(session) is WindowsSession)
        if record['success']:
            record['stage'] = 'complete'
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return record


def require_native_point_preflight(value):
    """Numeric native-thread lifetime proof; never a provider/menu success."""
    assert type(value) is dict and all(type(number) is int for number in value.values())
    ones=('schemaVersion','diagnosticOnly','providerLocalOnly','nativeBoundaryOnly','nativeBoundaryPassed',
        'nativeAttempted','nativeExit','threadClosed','processesClosed','workerCleanup','workerMta',
        'comInitialized','comUninitialized','dpiEntered','dpiRestored','physicalDpiVerified',
        'threadIdentity','callbackIdentity','exitCodeObserved')
    zeros=('acceptanceEligible','globalHitSubstituted','synthetic','scopeId','localKnown','localMatch',
        'workerException','pending','nativeExitCode','referencesAcquired','referencesReleased',
        'variantAttempted','cleanupError')
    assert all(value[key]==1 for key in ones) and all(value[key]==0 for key in zeros)
    assert value['stageCode']==13 and value['workerStage']==8
    assert all(value[key]>0 for key in ('controllerPid','threadId','threadBirth'))


def run_modules(suite, fixtures, output, *, session_factory=WindowsSession, point_preflight=None,identity_diagnostic=0,source_prepared=None,stop_if_pending=None):
    assert type(identity_diagnostic) is int and identity_diagnostic in (0,3)
    assert not identity_diagnostic or point_preflight is not None
    assert source_prepared is None or identity_diagnostic==0
    if point_preflight is not None:require_native_point_preflight(point_preflight)
    records = []
    for module in MODULES:
        if stop_if_pending is not None and stop_if_pending():break
        options={} if source_prepared is None else dict(source_prepared=source_prepared)
        record = run_case(suite, fixtures, output, module, session_factory=session_factory,**options)
        assert not identity_diagnostic or record.get('diagnosticProfile')==3
        records.append(record)
        with (output / (record['case'] + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False, indent=2)
        print(module + ': ' + ('passed' if record['success'] else 'FAILED: ' + record.get(
            'errorType', record.get('cleanupErrorType', 'unconfirmed cleanup'))), flush=True)
        if not record['cleanupConfirmed']:
            break  # An unretired original engine cannot authorize the next case.
        if stop_if_pending is not None and stop_if_pending():break
    counts = Counter(row['module'] for row in records)
    complete = tuple(row['module'] for row in records) == MODULES and all(n == 1 for n in counts.values())
    scenario_success = complete and all(row['success'] for row in records)
    native_verified = scenario_success and all(row['nativeMenuVerified'] for row in records)
    view_records = [row for row in records if row['module'] in VIEW_MODULES]
    views_verified = bool(native_verified and tuple(row['module'] for row in view_records) == VIEW_MODULES
        and all(row['viewPhysicalVerified'] for row in view_records))
    hwp_verified = bool(records and records[0]['module']=='writer' and records[0]['nativeHwpMenuLaunchExecuted'])
    report = dict(schemaVersion=1, kind='native-menu-gesture-matrix', success=native_verified and views_verified and hwp_verified,
        scenarioSuccess=scenario_success, actualWindowsExecuted=bool(records) and all(
            row['actualWindowsExecuted'] for row in records), nativeMenuVerified=native_verified,
        acceptanceEligible=False, expectedCaseCount=len(MODULES), completedCaseCount=len(records),
        viewPhysicalVerified=views_verified, viewPhysicalExpectedCaseCount=len(VIEW_MODULES),
        viewPhysicalVerifiedCaseCount=sum(row['viewPhysicalVerified'] for row in view_records),
        nativeHwpMenuLaunchExecuted=hwp_verified, disabledCommandsPhysicalVerified=False,
        passedCaseCount=sum(row['success'] for row in records),
        missingModules=[module for module in MODULES if module not in counts],
        failedModules=[row['module'] for row in records if not row['success']],
        externalAcceptanceGates=list(EXTERNAL_GATES), tests=records)
    report.update(nativePointProfileVersion=2 if point_preflight is not None and not identity_diagnostic else 0,
        nativePointPreflight=point_preflight)
    if source_prepared is not None:
        from native_menu_source_selection import PreparedSourceMenu
        from native_menu_source_admission import SourceMenuAdmission
        assert type(source_prepared) is PreparedSourceMenu and type(source_prepared.admission) is SourceMenuAdmission
        summary=source_menu_admission_summary(source_prepared.admission)
        matched=sum(row.get('nativePointProfileVersion')==4 and row.get('sourceMenuAdmission')==summary for row in records)
        report.update(nativePointProfileVersion=4 if records and matched==len(records) else 0,
            sourceSelectionExpectedCaseCount=len(MODULES),sourceSelectionMatchedCaseCount=matched)
        if records and matched==len(records):report['sourceMenuAdmission']=summary
        if matched!=len(records) or not complete:
            report.update(success=False,scenarioSuccess=False,nativeMenuVerified=False)
    if identity_diagnostic:
        assert report['success'] is False and report['nativeMenuVerified'] is False and report['scenarioSuccess'] is False
        report.update(diagnosticProfile=3,diagnosticOnly=1,acceptanceEligible=0,scenarioCompleted=False)
    with (output / 'results.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'fixtures', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-qualified-menu', choices=('x64','arm64'))
    return parser


def source_menu_pending(helper):
    """An unknown registry blocks the next case; it is never admission evidence."""
    try:
        lease=helper.pending_msaa_hit()
        if lease is None:return False
        pending=lease.pending
        return type(pending) is not bool or pending
    except BaseException:
        return True


def _configure_source_menu(retain):
    import pywinauto
    import comtypes
    import native_menu_msaa_hit as helper
    from native_menu_controller_fence import install, _ControllerFence
    fence=install(helper.pending_msaa_hit,enabled=True)
    if type(fence) is not _ControllerFence:raise ValueError('Actual source menu controller fence is required')
    retain(fence)
    helper.configure_native_launch(pending_fence=fence.finish)
    return helper


@contextmanager
def source_menu_cohort(suite,architecture,output,*,setup=None,prepare=None,clock=time.monotonic):
    """Opt-in context: close caller evidence/owned cleanup before this fence."""
    if architecture not in ('x64','arm64'):raise ValueError('Explicit source menu architecture is required')
    fence=None;stage=1
    def retain(value):
        nonlocal fence
        from native_menu_controller_fence import _ControllerFence
        if type(value) is not _ControllerFence or fence is not None:
            raise ValueError('Source menu cohort must retain one actual controller fence')
        fence=value
    try:
        helper=(setup or _configure_source_menu)(retain)
        if fence is None:raise ValueError('Source menu controller was not retained')
        stage=2
        if prepare is None:
            from native_menu_source_selection import prepare_source_menu_runtime
            prepare=prepare_source_menu_runtime
        prepared=prepare(Path(suite),architecture,deadline=clock()+150)
        stage=3
        yield prepared,lambda:source_menu_pending(helper)
    except BaseException as exc:
        code=2 if isinstance(exc,KeyboardInterrupt) else 3 if isinstance(exc,SystemExit) else 1 if isinstance(exc,Exception) else 4
        try:
            with (Path(output)/'source-menu-controller-failure.json').open('x',encoding='utf-8') as stream:
                json.dump(dict(schemaVersion=1,success=False,acceptanceEligible=False,
                    stageCode=stage,exceptionCode=code),stream,allow_nan=False)
        except BaseException:
            pass
        raise
    finally:
        if fence is not None:fence.finish()


def _configure_native_point_profile():
    # Preserve the original pywinauto apartment selection before importing
    # comtypes ourselves. Never change sys.coinit_flags or an existing apartment.
    import pywinauto
    import comtypes
    import native_menu_msaa_hit as helper
    from native_menu_controller_fence import install
    fence = install(helper.pending_msaa_hit, enabled=True)
    helper.configure_native_launch(pending_fence=fence.finish)
    return fence, helper


def _run_point_profile(suite, fixtures, output, *, setup=None):
    """Only this dedicated CLI opts in after installing its own exit fence."""
    fence, helper = (setup or _configure_native_point_profile)()
    stage = 1
    def retain(name, value):
        raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n').encode()
        assert len(raw) <= 64*1024
        with (output / name).open('xb') as stream:
            stream.write(raw)
    try:
        boundary = helper.verify_native_thread_boundary(time.monotonic()+5)
        retain('native-point-preflight.json', boundary)
        if boundary.get('nativeBoundaryPassed') != 1:
            return 1
        require_native_point_preflight(boundary)
        stage = 2
        def factory(*args):
            session = WindowsSession(*args)
            session.native_point_profile = True
            session.native_point_profile_version = 2
            session.native_identity_diagnostic = 3
            return session
        result=run_modules(suite, fixtures, output, session_factory=factory,point_preflight=boundary,identity_diagnostic=3)
        assert result['success'] is False, 'A read-only identity diagnostic cannot qualify menus'
        return 1
    except BaseException as exc:
        code = 2 if isinstance(exc, KeyboardInterrupt) else 3 if isinstance(exc, SystemExit) else 1 if isinstance(exc, Exception) else 4
        retain('native-point-controller-failure.json', dict(schemaVersion=1, success=False,
            acceptanceEligible=False, stageCode=stage, exceptionCode=code))
        raise
    finally:
        # run_modules closes case/results files. Emergency records above also
        # close first. This own-controller fence never claims owned-app cleanup.
        fence.finish()


def _run_source_qualified(suite,fixtures,output,architecture):
    with source_menu_cohort(suite,architecture,output) as (prepared,pending):
        def factory(*args):
            session=WindowsSession(*args)
            session.source_prepared=prepared
            return session
        if pending():
            result=run_modules(suite,fixtures,output,session_factory=factory,
                source_prepared=prepared,stop_if_pending=pending)
            return 0 if result['success'] else 1
        import native_menu_msaa_hit as helper
        boundary=helper.verify_native_thread_boundary(time.monotonic()+5)
        raw=(json.dumps(boundary,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()
        assert len(raw)<=64*1024
        with (output/'native-point-preflight.json').open('xb') as stream:stream.write(raw)
        if boundary.get('nativeBoundaryPassed')!=1:return 1
        require_native_point_preflight(boundary)
        result=run_modules(suite,fixtures,output,session_factory=factory,point_preflight=boundary,
            source_prepared=prepared,stop_if_pending=pending)
        return 0 if result['success'] else 1


def main(argv=None):
    args = argument_parser().parse_args(argv)
    assert os.name == 'nt' and __debug__, 'Actual Windows GUI with assertions is required'
    paths = (args.suite, args.fixtures, args.output)
    for path in paths:
        for part in (path, *path.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)()
    suite, fixtures, output = (path.resolve() for path in paths)
    assert suite.is_dir() and fixtures.is_dir()
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output))
    assert suite != output and suite not in output.parents
    assert fixtures != output and fixtures not in output.parents
    output.mkdir(parents=True, exist_ok=False)
    if args.source_qualified_menu is not None:
        return _run_source_qualified(suite,fixtures,output,args.source_qualified_menu)
    return _run_point_profile(suite, fixtures, output)


if __name__ == '__main__':
    raise SystemExit(main())
