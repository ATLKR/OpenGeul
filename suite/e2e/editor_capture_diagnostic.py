"""Passive capture observation around one original focus-entry attempt only."""
import ctypes as C
import copy
import time
import math
from ascii_message_windows import MessageTransport, NativeAsciiProbe
from counted_editor_shortcuts import NativeShortcutProbe, join_shortcut_generation, US_LAYOUT
from ascii_message_preparation import require_prepared_library
import native_suite_architecture as architecture
from ime_thread_mode import counter_budget


def validate_passive_scope(scope,binding,thread):
    """Allow original host/panel/editor focus for observation, never input admission."""
    b=binding;first=scope['before'];last=scope['after']
    assert first['suite']==last['suite'] and first['editor']==last['editor'],'Passive window identity changed'
    host_thread=first['suite']['threadId']
    expected={b['suiteHwnd']:(b['shellPid'],host_thread),b['parentHwnd']:(b['shellPid'],host_thread),
              b['childHwnd']:(b['officePid'],thread)}
    def owned(window):
        assert window['hwnd'] in expected and window['isWindow'] is True,'Passive target is not an original owned window'
        assert (window['pid'],window['threadId'])==expected[window['hwnd']],'Passive window process/thread changed'
        assert type(window['threadId']) is int and window['threadId']>0 and window['rootHwnd']==b['suiteHwnd']
    for window in (first['suite'],first['editor'],scope['parent'],scope['focus']):owned(window)
    assert first['suite']['hwnd']==b['suiteHwnd'] and first['editor']['hwnd']==b['childHwnd'] and scope['parent']['hwnd']==b['parentHwnd']
    for edge in (first,last):
        assert edge['foreground']==first['suite'] and edge['editorWithinSuite'] is True,'Passive observer lost original foreground'
    assert all(scope[key] is True for key in ('suiteOwnsParent','parentOwnsChild','parentVisible','parentEnabled','childVisible','childEnabled'))
    capture=scope['capture']
    if capture['hwnd']:owned(capture)
    else:assert capture['isWindow'] is False and all(capture[key]==0 for key in ('hwnd','pid','threadId','rootHwnd'))


class CohortEngineLease:
    """Join while admitted; share only the existing owned cleanup exit phase."""
    def __init__(self, keyboard, receipt):
        self.keyboard=keyboard;self.receipt=receipt;self.handle=None;self.probe=None;self.closed=False
    def admit(self, probe, deadline):
        k=self.keyboard;self.probe=probe
        assert k.clock()<deadline
        self.handle=probe.open_engine(k.binding['officePid'])
        assert type(self.handle) is int and self.handle>0
        assert k.clock()<deadline
        snapshot=probe.engine_snapshot(self.handle)
        assert snapshot==dict(k.engine,handleValue=self.handle),'Cohort engine generation changed'
        assert join_shortcut_generation(k.process,k.binding['parentHwnd'],k.binding['childHwnd'],snapshot)==k.shared_admission
        assert k.clock()<deadline
        self.receipt.update(admitted=True,originalEngine=snapshot,deadline=deadline)
    def finish(self):
        if self.closed:return
        self.closed=True
        self.receipt.update(phase='after-owned-process-cleanup',waitMilliseconds=0,engineExitConfirmed=False,handleReleased=False)
        try:
            if self.handle is not None and self.receipt.get('admitted') is True:
                phase=self.keyboard.record.get('testProcessCleanup',{})
                deadline=phase.get('exitWaitDeadline');started=self.keyboard.clock();milliseconds=0
                if deadline is not None:
                    phase_start=phase.get('exitWaitStartedAt')
                    assert type(deadline) in (int,float) and math.isfinite(deadline)
                    assert type(phase_start) in (int,float) and math.isfinite(phase_start)
                    assert phase.get('exitWaitBudgetSeconds')==5 and deadline==phase_start+5 and started>=phase_start
                    milliseconds=max(0,min(5000,math.floor((deadline-started)*1000)))
                    self.receipt.update(sharedExitWaitDeadline=deadline,sharedExitWaitStartedAt=phase_start)
                self.receipt.update(waitStartedAt=started,waitMilliseconds=milliseconds)
                result=int(self.probe.kernel.WaitForSingleObject(self.handle,milliseconds))
                returned=self.keyboard.clock();late=milliseconds>0 and returned>deadline
                self.receipt.update(waitResult=result,waitReturnedAt=returned,positiveWaitReturnedLate=late,
                    engineExitConfirmed=result==0 and not late)
        except BaseException as exc:self.receipt['error']=type(exc).__name__+': '+str(exc)[:512]
        finally:
            if self.handle is not None:
                try:self.receipt['handleReleased']=self.probe.close_engine(self.handle) is True
                except BaseException as exc:self.receipt['releaseError']=type(exc).__name__+': '+str(exc)[:512]


def cohort_cleanup_confirmed(record):
    shell=record.get('testProcessCleanup',{});engine=record.get('focusCohortEngineCleanup',{})
    return (shell.get('shellExitCode') is not None and shell.get('disposition') in
        ('already-exited','forced-stop-returned','exit-zero-after-taskkill-not-found')
        and not record.get('cleanupError') and engine.get('admitted') is True
        and engine.get('engineExitConfirmed') is True and engine.get('handleReleased') is True
        and not engine.get('error') and not engine.get('releaseError'))


class PassiveCaptureProbe:
    # Reuse resource/session utilities only; no inherited ASCII input guard or methods.
    _session=NativeAsciiProbe._session
    close=NativeAsciiProbe.close

    def __init__(self,keyboard,prepared,receipt,deadline):
        self.keyboard=keyboard;self.api=keyboard.api;self.process=keyboard.process
        self.binding=dict(keyboard.binding);self.prepared=prepared;self.receipt=receipt
        self.deadline=deadline;self.clock=keyboard.clock
        self.handle=self.probe=self.transport=self.dll=None;self.closed=False
    def _budget(self):assert self.clock()<self.deadline,'Original focus diagnostic deadline expired'
    def admit(self):
        k=self.keyboard;b=self.binding;p=self.process
        self._budget();assert k.handle and not k.finished and k.failed is None
        self.probe=NativeShortcutProbe(self.deadline,self.clock)
        self.original_shell=self.probe.process_snapshot(p)
        assert self.original_shell==k.shell,'Original keyboard shell generation changed'
        assert tuple(k.shell[key] for key in ('pid','handleValue','image','creationTime','waitResult'))==p.opengeul_activation_binding
        self._budget();self.handle=self.probe.open_engine(b['officePid'])
        assert type(self.handle) is int and self.handle>0
        self.receipt['engineHandleAdmittedAt']=self.clock()
        self.receipt['engineAdmissionBasis']='new query+sync HANDLE joined to original keyboard generation'
        self._budget();self.original_engine=self.probe.engine_snapshot(self.handle)
        expected=dict(k.engine,handleValue=self.handle)
        assert self.original_engine==expected,'Original keyboard engine generation changed'
        assert join_shortcut_generation(p,b['parentHwnd'],b['childHwnd'],self.original_engine)==k.shared_admission
        self.selected=self.prepared['architecture']
        self.receipt['nativeArchitectures']={}
        for name,handle in (('controller',None),('shell',int(p._handle)),('engine',self.handle)):
            self._budget()
            self.receipt['nativeArchitectures'][name]=architecture.validate_native_architecture(architecture.observe_native_architecture(handle),self.selected)
            self._budget()
        self.controller_pid=int(self.probe.kernel.GetCurrentProcessId())
        self.sessions={}
        for name,pid in (('controller',self.controller_pid),('shell',p.pid),('engine',b['officePid'])):
            self._budget();self.sessions[name]=self._session(pid);self._budget()
        assert len(set(self.sessions.values()))==1,'Passive capture observer crosses sessions'
        self.receipt.update(originalShell=dict(self.original_shell),originalEngine=dict(self.original_engine),nativeSessions=dict(self.sessions))
        self.target=dict(pid=b['officePid'],tid=k.tid,hwnd=b['childHwnd'],layout=US_LAYOUT)
        self._identity()
        self.cohort_lease.admit(self.probe,self.deadline)
        self._budget();library=require_prepared_library(self.prepared,architecture=self.selected);self._budget()
        self.probe.kernel.FreeLibrary.argtypes=(C.c_void_p,);self.probe.kernel.FreeLibrary.restype=C.c_int32
        self.dll=C.WinDLL(str(library),use_last_error=True)
        self._budget();counter,frequency=counter_budget(self.deadline,clock=self.clock)
        self.transport=MessageTransport(self.probe.user,self.probe.kernel,self.dll,self.target,
            self.original_engine['creationTime'],self.receipt,self.deadline,self.clock,self._identity,
            capture_diagnostic_mode=True,capture_deadline_counter=counter,capture_counter_frequency=frequency)
        self._budget()
    def _identity(self):
        self._budget();assert self.probe.process_snapshot(self.process)==self.original_shell
        self._budget();assert self.probe.engine_snapshot(self.handle)==self.original_engine
        self._budget();scope=self.probe.scope_snapshot(self.api,self.binding)
        validate_passive_scope(scope,self.binding,self.keyboard.tid)
        admitted=self.keyboard.receipt['admissionSnapshot']['scope']
        for role in ('suite','editor'):
            assert scope['before'][role]==admitted['before'][role],'Original admitted window identity changed'
        assert scope['parent']==admitted['parent'],'Original admitted panel identity changed'
        self.receipt['lastPassiveScope']=scope
        self._budget();keys=self.probe.keyboard_snapshot(self.keyboard.tid)
        assert keys['targetLayout']==US_LAYOUT,'Passive original keyboard layout changed'
        for name,pid in (('controller',self.controller_pid),('shell',self.process.pid),('engine',self.binding['officePid'])):
            self._budget();assert self._session(pid)==self.sessions[name];self._budget()
        self._budget()
    def local_counter_sample(self):
        """Controller-local QPC only, including after the target observation budget."""
        assert self.probe is not None and self.transport is not None
        kernel=self.probe.kernel
        kernel.QueryPerformanceCounter.argtypes=(C.POINTER(C.c_int64),);kernel.QueryPerformanceCounter.restype=C.c_int32
        kernel.QueryPerformanceFrequency.argtypes=(C.POINTER(C.c_int64),);kernel.QueryPerformanceFrequency.restype=C.c_int32
        frequency=C.c_int64();counter=C.c_int64()
        assert kernel.QueryPerformanceFrequency(C.byref(frequency)), 'Local terminal QPC frequency unavailable'
        assert kernel.QueryPerformanceCounter(C.byref(counter)), 'Local terminal QPC unavailable'
        assert counter.value>0 and frequency.value==self.transport.capture_budget[1], 'Local terminal QPC configuration changed'
        return dict(counter=counter.value,counterFrequency=frequency.value,nativeDeadlineCounter=self.transport.capture_budget[0])

    def readiness_boundary(self, *, counter=None):
        from windows_smoke import _editor_focus_snapshot_ready
        self._identity();b=self.binding
        scope=copy.deepcopy(self.receipt['lastPassiveScope'])
        assert _editor_focus_snapshot_ready(scope,b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'],self.keyboard.tid), 'Passive watch requires strict original editor focus without capture'
        lease=self.cohort_lease
        assert not self.closed and self.handle and self.transport and not self.transport.closed
        assert lease.probe is self.probe and lease.handle and not lease.closed and lease.receipt.get('admitted') is True
        self._budget();assert self.probe.engine_snapshot(lease.handle)==lease.receipt['originalEngine']
        self._budget()
        frequency=self.transport.capture_budget[1]
        if counter is None:
            kernel=self.probe.kernel
            kernel.QueryPerformanceCounter.argtypes=(C.POINTER(C.c_int64),);kernel.QueryPerformanceCounter.restype=C.c_int32
            kernel.QueryPerformanceFrequency.argtypes=(C.POINTER(C.c_int64),);kernel.QueryPerformanceFrequency.restype=C.c_int32
            value=C.c_int64();assert kernel.QueryPerformanceFrequency(C.byref(value)) and value.value==frequency
            def counter():
                value=C.c_int64();assert kernel.QueryPerformanceCounter(C.byref(value));return value.value
        self._budget();before=counter();self._budget()
        snapshot=self.transport.read_capture_trace(local_only=True)
        after=counter();self._budget()
        assert type(before) is int and type(after) is int and 0<before<=after<self.transport.capture_budget[0]
        return dict(counterBefore=before,counterAfter=after,counterFrequency=frequency,
            nativeDeadlineCounter=self.transport.capture_budget[0],committedIndex=len(snapshot['events']),
            reservedIndex=snapshot['reservedCount'],ringStatus=snapshot['status'],strictScope=scope,
            markerPhase='post-readiness-before-keyboard-close',
            originalReadinessElapsedSeconds=self.keyboard.record['editorFocusReadiness']['elapsedSeconds'],
            originalReadinessDecisionCounterKnown=False,snapshotPhase='bounded-local-copy',
            acceptanceEligible=False,historicalFocusContinuityProved=False)

    def start(self):self.transport.start()
    def read_capture_trace(self,*,local_only=False):
        if self.transport is None:return dict(status='unavailable',reason='transport-not-admitted',events=[])
        return self.transport.read_capture_trace(local_only=local_only)
    def can_stop(self):return self.transport is not None and self.transport.can_stop()
    def stop(self):self.transport.stop()


class EditorCaptureDiagnostic:
    def __init__(self,keyboard,prepared,deadline,*,probe=None):
        record=keyboard.record;focus=record['editorFocusReadiness']
        assert record.get('kind')=='native-focus-diagnostic' and record.get('acceptanceEligible') is False
        assert keyboard.module=='calc' and keyboard.phase=='admitted' and not keyboard.finished and keyboard.failed is None
        assert deadline==focus['deadline'] and deadline==focus['startedAt']+focus['deadlineSeconds'] and 0<focus['deadlineSeconds']<=5
        assert focus['deadlineScope']=='editor-setup-and-focus' and focus['ready'] is False and focus['clickAttempts']==1 and focus['clickCompleted'] is False
        assert keyboard.clock()<deadline<=keyboard.setup_deadline
        self.keyboard=keyboard;self.deadline=deadline;self.clock=keyboard.clock;self.closed=False
        self.receipt=dict(kind='owned-focus-capture-diagnostic',acceptanceEligible=False,deadline=deadline,
            snapshot=dict(status='unavailable',events=[]),cleanupErrors=[],expectedNative=dict(keyboard.binding))
        assert 'focusCaptureDiagnostic' not in record
        record['focusCaptureDiagnostic']=self.receipt
        self.probe=probe or PassiveCaptureProbe(keyboard,prepared,self.receipt,deadline)
        cohort_receipt=dict(admitted=False,engineExitConfirmed=False,handleReleased=False)
        record['focusCohortEngineCleanup']=cohort_receipt
        self.cohort_lease=CohortEngineLease(keyboard,cohort_receipt)
        self.probe.cohort_lease=self.cohort_lease
    def start(self):
        try:self.probe.admit();self.probe.start()
        except BaseException as exc:self.close(exc);raise
    def watch_remaining(self, *, sleep=time.sleep):
        assert not self.closed and 'readinessBoundary' in self.receipt
        assert self.keyboard.finished and self.keyboard.record['focusKeyboardStop']['kind']=='intentional-focus-stop-before-passive-watch'
        started=self.clock();assert started<self.deadline
        watch=dict(startedAt=started,deadline=self.deadline,remainingSeconds=self.deadline-started,
            originalDeadlineReached=False,targetQueriesDuringWatch=0,inputAttempts=0,acceptanceEligible=False)
        self.receipt['passiveWatch']=watch
        try:
            while True:
                remaining=self.deadline-self.clock()
                if remaining<=0:break
                sleep(min(.05,remaining))
            watch.update(finishedAt=self.clock(),originalDeadlineReached=True)
        except BaseException as exc:
            watch['error']=type(exc).__name__+': '+str(exc)[:512];self.close(exc);raise
        self.close(FocusPassiveWatchComplete('Original passive observation budget ended'))
        assert not self.receipt.get('snapshotError') and not self.receipt['cleanupErrors'],'Passive watch snapshot or cleanup failed'
        snapshot=self.receipt['snapshot']
        boundary=self.receipt['readinessBoundary']
        watch.update(traceStatus=snapshot.get('status'),traceOverflow=snapshot.get('overflow'),
            traceRejected=snapshot.get('rejected'),traceExpired=snapshot.get('expired'),
            committedEvents=len(snapshot.get('events',[])),
            eventsDefinitelyAfterReadiness=sum(row.get('counter',0)>boundary['counterAfter'] for row in snapshot.get('events',[])),
            terminalCopyCoverage=self.receipt['terminalCopyCoverage'],
            continuousFocusOrCaptureStateProved=False,coverage='bounded message transitions only; absence is not continuous-state proof')

    def _terminal_sample(self, phase):
        result=self.receipt.setdefault('terminalCopyCoverage',dict(status='unknown',clockCoverage='unknown',scope='native-cutoff-at-final-copy; not continuity or complete ring proof',
            finalPublicationCountProved=False,remoteCallbackQuiescenceProved=False,errors=[]))
        try:result[phase]=self.probe.local_counter_sample()
        except BaseException as exc:result['errors'].append(dict(phase=phase,error=type(exc).__name__+': '+str(exc)[:512]))
    def _terminal_coverage(self):
        result=self.receipt['terminalCopyCoverage'];before=result.get('before');after=result.get('after')
        if result['errors'] or not before or not after:return
        try:
            assert before['counterFrequency']==after['counterFrequency']>0
            assert before['nativeDeadlineCounter']==after['nativeDeadlineCounter']>0
            assert 0<before['counter']<=after['counter']
            deadline=before['nativeDeadlineCounter']
            result['status']=('covered' if before['counter']>=deadline else
                              'truncated' if after['counter']<deadline else 'unknown')
            result['reason']=('copy-started-at-or-after-native-cutoff' if result['status']=='covered' else
                              'copy-finished-before-native-cutoff' if result['status']=='truncated' else 'copy-bracket-straddles-native-cutoff')
            if self.receipt.get('snapshotError'):
                result.update(status='unknown',reason='final-local-copy-failed')
            result['clockCoverage']=result['status']
        except BaseException as exc:result['errors'].append(dict(phase='comparison',error=type(exc).__name__+': '+str(exc)[:512]))

    def close(self,primary=None):
        if self.closed:return
        self.closed=True;failure=None
        late=self.clock()>=self.deadline
        self._terminal_sample('before')
        try:self.receipt['snapshot']=self.probe.read_capture_trace(local_only=primary is not None or late)
        except BaseException as exc:
            failure=exc;self.receipt['snapshotError']=type(exc).__name__+': '+str(exc)[:512]
        finally:
            self._terminal_sample('after');self._terminal_coverage()
        try:
            if primary is None and self.clock()<self.deadline and self.probe.can_stop():self.probe.stop()
        except BaseException as exc:
            failure=failure or exc;self.receipt['cleanupErrors'].append(type(exc).__name__+': '+str(exc)[:512])
        finally:
            try:self.receipt['cleanup']=self.probe.close()
            except BaseException as exc:
                failure=failure or exc;self.receipt['cleanupErrors'].append(type(exc).__name__+': '+str(exc)[:512])
        if primary is None:
            if failure is not None:raise failure
            assert self.clock()<self.deadline,'Original focus diagnostic deadline expired during cleanup'


class FocusDiagnosticStop(Exception):pass


def stop_focus_keyboard(keyboard):
    from windows_smoke import require_editor_focus_readiness
    r=keyboard.record;b=keyboard.binding;focus=r['editorFocusReadiness'];deadline=focus['deadline']
    assert r.get('kind')=='native-focus-diagnostic' and r.get('acceptanceEligible') is False and r.get('imeVerified') is False
    assert keyboard.module=='calc' and keyboard.phase=='awaiting-editor-readiness' and not keyboard.finished and keyboard.failed is None
    require_editor_focus_readiness(focus,b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'])
    assert r['imeKeyboardSession'] is keyboard.receipt and keyboard.handle
    assert keyboard.receipt['success'] is False and not keyboard.receipt['engineHandleReleased']
    assert not keyboard.receipt['cleanupErrors'] and not keyboard.receipt.get('retentionError')
    action,=keyboard.receipt['actions']
    assert action['shortcut']=='CTRL_F6' and action['inputCallAttempts']==1 and action['insertedInputs']==4
    assert action['deadline']==keyboard.receipt['focusDeadline']==deadline and action['finishedAt']<deadline
    trace=r['focusCaptureDiagnostic']
    assert trace['deadline']==deadline and not trace['cleanupErrors'] and not trace.get('snapshotError')
    assert trace['cleanup']['engineHandleReleased'] is True and trace['cleanup']['controllerResourcesReleased'] is True
    assert keyboard.clock()<deadline and not keyboard.semantic_pre and not keyboard.semantic_post and not r.get('asciiEditorInputs')
    reason=FocusDiagnosticStop('Focus experiment ends before navigation, ASCII, IME and save')
    keyboard.close(primary=reason)
    assert keyboard.finished and keyboard.receipt['success'] is False and keyboard.receipt['engineHandleReleased'] is True
    assert not keyboard.receipt['cleanupErrors'] and not keyboard.receipt.get('retentionError')
    assert keyboard.receipt['error']==type(reason).__name__+': '+str(reason)
    assert keyboard.clock()<deadline,'Original focus diagnostic deadline expired during keyboard cleanup'
    r['focusKeyboardStop']=dict(kind='intentional-focus-diagnostic-stop',acceptanceEligible=False,
        keyboardSessionSuccess=False,engineHandleReleased=True,deadline=deadline)


class FocusPassiveWatchComplete(Exception):pass
class FocusKeyboardWatchStop(Exception):pass


def stop_focus_keyboard_before_passive_watch(keyboard, trace, *, counter=None):
    """Close input ownership while independent passive observation remains admitted."""
    from windows_smoke import require_editor_focus_readiness
    r=keyboard.record;b=keyboard.binding;focus=r['editorFocusReadiness'];deadline=focus['deadline']
    assert r.get('kind')=='native-focus-diagnostic' and r.get('acceptanceEligible') is False and r.get('imeVerified') is False
    assert keyboard.module=='calc' and keyboard.phase=='awaiting-editor-readiness' and not keyboard.finished and keyboard.failed is None
    require_editor_focus_readiness(focus,b['suiteHwnd'],b['childHwnd'],b['shellPid'],b['officePid'])
    assert r['imeKeyboardSession'] is keyboard.receipt and keyboard.handle
    assert keyboard.receipt['success'] is False and not keyboard.receipt['engineHandleReleased']
    assert not keyboard.receipt['cleanupErrors'] and not keyboard.receipt.get('retentionError')
    action,=keyboard.receipt['actions']
    assert action['shortcut']=='CTRL_F6' and action['inputCallAttempts']==1 and action['insertedInputs']==4
    assert focus['startedAt']<=action['startedAt']<=action['finishedAt']<deadline
    assert action['deadline']==keyboard.receipt['focusDeadline']==deadline
    assert trace.keyboard is keyboard and trace.receipt is r['focusCaptureDiagnostic'] and trace.deadline==deadline
    assert not trace.closed and not trace.receipt['cleanupErrors'] and not trace.receipt.get('snapshotError')
    assert keyboard.clock()<deadline and not keyboard.semantic_pre and not keyboard.semantic_post and not r.get('asciiEditorInputs')
    assert 'readinessBoundary' not in trace.receipt
    trace.receipt['readinessBoundary']=trace.probe.readiness_boundary(counter=counter)
    assert keyboard.clock()<deadline
    reason=FocusKeyboardWatchStop('Input session ends before passive remainder of original focus budget')
    keyboard.close(primary=reason)
    assert keyboard.finished and keyboard.receipt['success'] is False and keyboard.receipt['engineHandleReleased'] is True
    assert not keyboard.receipt['cleanupErrors'] and not keyboard.receipt.get('retentionError')
    assert keyboard.receipt['error']==type(reason).__name__+': '+str(reason)
    assert keyboard.clock()<deadline,'Original focus diagnostic deadline expired during keyboard cleanup'
    r['focusKeyboardStop']=dict(kind='intentional-focus-stop-before-passive-watch',acceptanceEligible=False,
        keyboardSessionSuccess=False,engineHandleReleased=True,deadline=deadline)
