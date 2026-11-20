"""Opt-in bounded navigation observation; never acceptance or input scheduling."""
import math
import time


class NavigationTrace:
    def __init__(self, api, process, binding, prepared, record, deadline,
                 *, clock=time.monotonic, probe=None):
        assert type(deadline) in (int,float) and math.isfinite(deadline)
        self.clock,self.deadline,self.probe=clock,deadline,probe
        self.closed=False
        self.receipt=dict(schemaVersion=1,kind='owned-navigation-diagnostic',
            acceptanceEligible=False,semanticHandlerProved=False,deadline=deadline,
            snapshot=dict(status='unavailable',events=[]),cleanupErrors=[],
            limitation='Queue removal and window procedure boundaries do not prove a specific shortcut handler or semantic edit.')
        assert 'navigationDiagnostic' not in record
        record['navigationDiagnostic']=self.receipt
        self.args=(api,process,dict(binding),prepared)

    def _budget(self):
        assert self.clock()<self.deadline,'Navigation diagnostic original setup deadline expired'

    def start(self):
        self._budget()
        try:
            if self.probe is None:
                from ascii_message_windows import NativeAsciiProbe
                self.probe=NativeAsciiProbe(*self.args,self.receipt,self.deadline,self.clock,diagnostic_mode=True)
            self.target=dict(self.probe.admit())
            self.receipt['originalTarget']=dict(self.target)
            assert self.probe.guard()==self.target,'Navigation diagnostic target changed'
            self._budget();self.probe.start();self._budget()
            assert self.probe.guard()==self.target,'Navigation diagnostic target changed'
        except BaseException as exc:
            self.close(exc)
            raise

    def close(self, primary=None):
        if self.closed:return
        self.closed=True
        failure=None
        if self.probe is None:return
        try:
            self._budget()
            self.receipt['snapshot']=self.probe.read_navigation_trace()
        except BaseException as exc:
            failure=exc
            self.receipt['snapshotError']=type(exc).__name__+': '+str(exc)[:512]
        finally:
            try:
                # Never renew the original setup deadline, including stop ACK.
                if self.clock()<self.deadline and self.probe.can_stop():self.probe.stop()
            except BaseException as exc:
                failure=failure or exc
                self.receipt['cleanupErrors'].append(type(exc).__name__+': '+str(exc)[:512])
            finally:
                try:self.receipt['cleanup']=self.probe.close()
                except BaseException as exc:
                    failure=failure or exc
                    self.receipt['cleanupErrors'].append(type(exc).__name__+': '+str(exc)[:512])
        if failure is not None and primary is None:raise failure


class NavigationDiagnosticStop(Exception):
    """Intentional end of a nonacceptance experiment before ASCII/IME/save."""


def stop_navigation_keyboard(keyboard):
    """Dispose an acknowledged diagnostic PRE session without claiming completion.

    The normal close() contract remains saved-only. Its explicit-primary cleanup
    path retains this intentional stop as the incomplete keyboard receipt's error.
    Cleanup/retention failures still fail the surrounding diagnostic case.
    """
    record=keyboard.record;receipt=keyboard.receipt
    assert record.get('kind')=='native-navigation-diagnostic' and record.get('acceptanceEligible') is False and record.get('imeVerified') is False,'Keyboard disposal requires the nonacceptance navigation experiment'
    assert keyboard.module in ('writer','impress') and keyboard.phase=='semantic-pre-ready','Diagnostic keyboard disposal requires Writer or Impress PRE readiness'
    assert not keyboard.finished and keyboard.failed is None,'Diagnostic keyboard already ended or failed'
    assert record.get('imeKeyboardSession') is receipt and receipt.get('success') is False,'Diagnostic keyboard receipt changed'
    assert keyboard.semantic_pre is record.get('imeSemanticContext') and keyboard.semantic_pre.get('success') is True and keyboard.semantic_pre.get('phase')=='pre','Diagnostic PRE context changed'
    assert keyboard.semantic_post is None and not record.get('asciiPrefix') and not record.get('asciiEditorInputs'),'Diagnostic disposal follows additional input'
    trace=record.get('navigationDiagnostic',{})
    assert trace.get('kind')=='owned-navigation-diagnostic' and trace.get('acceptanceEligible') is False,'Original navigation diagnostic receipt missing'
    assert not trace.get('cleanupErrors') and not trace.get('snapshotError'),'Navigation trace failed before keyboard disposal'
    cleanup=trace.get('cleanup',{})
    assert cleanup.get('controllerResourcesReleased') is True and cleanup.get('engineHandleReleased') is True,'Navigation observer cleanup is incomplete'
    deadline=keyboard.setup_deadline
    assert keyboard.deadline==receipt.get('setupDeadline')==record.get('imeSetupBudget',{}).get('deadline')==trace.get('deadline')==deadline,'Original diagnostic setup deadline changed'
    assert keyboard.clock()<deadline,'Original diagnostic setup deadline expired before keyboard disposal'
    assert type(keyboard.handle) is int and keyboard.handle>0 and receipt.get('engineHandleReleased') is False,'Diagnostic retained keyboard handle missing'
    assert not receipt.get('cleanupErrors') and not receipt.get('retentionError'),'Keyboard cleanup already failed'
    result=record['navigationKeyboardStop']=dict(kind='intentional-navigation-diagnostic-stop',
        acceptanceEligible=False,keyboardSessionSuccess=False,deadline=deadline,engineHandleReleased=False)
    reason=NavigationDiagnosticStop('Navigation experiment ends after PRE; ASCII/IME/save not performed')
    keyboard.close(primary=reason)
    result.update(engineHandleReleased=receipt.get('engineHandleReleased') is True,finishedAt=keyboard.clock())
    assert keyboard.finished and receipt.get('success') is False,'Diagnostic disposal must retain incomplete keyboard status'
    assert receipt.get('engineHandleReleased') is True and not receipt.get('cleanupErrors'),'Diagnostic keyboard handle cleanup failed'
    assert not receipt.get('retentionError'),'Diagnostic keyboard receipt retention failed'
    assert receipt.get('error')==type(reason).__name__+': '+str(reason),'Diagnostic keyboard stop reason changed'
    assert result['finishedAt']<deadline,'Original diagnostic setup deadline expired during keyboard disposal'
    return result
