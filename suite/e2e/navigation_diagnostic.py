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
