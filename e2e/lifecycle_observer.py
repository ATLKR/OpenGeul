"""Bounded public-browser lifecycle metadata; no payload or acceptance authority."""
import json
from pathlib import Path
import sys
import time

MAX_ROWS=128
MAX_COUNT=65535
ERROR_CODES={name:i for i,name in enumerate(('Error','TargetClosedError','TimeoutError','AssertionError','OSError','ValueError','TypeError','RuntimeError','FileNotFoundError','PermissionError'),1)}
class _CleanupScope:
    """Defer only diagnostic cancellation; never suppress operation errors."""
    def __init__(self,observer):self.observer=observer;self.primary_at_entry=False
    def __enter__(self):
        self.primary_at_entry=self.observer._preserve_primary()
        self.observer.cleanup_depth+=1
        return self.observer
    def __exit__(self,error_type,error,traceback):
        observer=self.observer;observer.cleanup_depth-=1
        if observer.cleanup_depth:return False
        cancellation=observer.deferred_cancellation;observer.deferred_cancellation=None
        if (cancellation is not None and error_type is None
                and not(self.primary_at_entry or observer.primary_pending)):
            raise cancellation
        return False
class LifecycleObserver:
    def __init__(self,*,enabled=True,browser_code=0,clock=time.monotonic_ns,writer=None):
        self.enabled=enabled is True;self.browser_code=browser_code if type(browser_code)is int and 0<=browser_code<=3 else 0
        self.clock=clock;self.writer=writer or self._write;self.rows=[];self.dropped=0;self.errors=0
        self.coverage=0;self.cleanup_started=False;self.current_phase=0;self.accepting=True;self.finished=False
        self.bound={};self.handlers=[];self.clock_valid=True;self.base=self.last=0;self.primary_pending=False
        self.cleanup_depth=0;self.deferred_cancellation=None
        if self.enabled:
            primary=self._preserve_primary()
            try:
                value=self.clock()
                if type(value)is not int or not 0<value<2**63:raise ValueError()
                self.base=self.last=value
            except BaseException as error:self.clock_valid=False;self._diagnostic_error(error,primary)
    def _error(self):self.errors=min(MAX_COUNT,self.errors+1)
    def _preserve_primary(self):
        # Inspect only the pending exception type, never its value or message.
        return self.primary_pending or sys.exc_info()[0]is not None
    def _diagnostic_error(self,error,preserve):
        # A user cancellation still propagates when no original operation is
        # already failing. A diagnostic failure cannot replace that primary.
        if isinstance(error,(KeyboardInterrupt,SystemExit)):
            if self.cleanup_depth:
                # A locally handled error can disappear before outer exit.
                # Let that exit, not this intermediate frame, choose priority.
                if self.deferred_cancellation is None:self.deferred_cancellation=error
            elif not preserve:raise error
        self._error()
    def cleanup_scope(self):return _CleanupScope(self)
    def _append(self,kind,owner=0,error=0):
        if not self.enabled or not self.accepting:return False
        if len(self.rows)>=MAX_ROWS:self.dropped=min(MAX_COUNT,self.dropped+1);return False
        if not self.clock_valid:return False
        primary=self._preserve_primary()
        try:
            now=self.clock()
            if type(now)is not int or not self.last<=now<2**63:raise ValueError()
            self.last=now
            self.rows.append(dict(sequence=len(self.rows)+1,kind=kind,owner=owner,phase=self.current_phase,
                relativeNanoseconds=now-self.base,cleanupStarted=self.cleanup_started,errorCode=error))
            return True
        except BaseException as error:self.clock_valid=False;self._diagnostic_error(error,primary);return False
    def phase(self,value):
        if not self.enabled or not self.accepting:return False
        if type(value)is not int or not 0<=value<=20:self._error();return False
        self.current_phase=value;return self._append(0)
    def failed(self,error):
        if not self.enabled or not self.accepting:return False
        self.primary_pending=True;self.current_phase=12
        try:code=ERROR_CODES.get(type(error).__name__,0)
        except BaseException as failure:self._diagnostic_error(failure,True);code=0
        return self._append(0,error=code)
    def cleanup(self):
        if not self.enabled or not self.accepting or self.cleanup_started:return False
        self.cleanup_started=True;return self.phase(13)
    def _bind(self,owner,emitter,events):
        if not self.enabled or not self.accepting:return False
        primary=self._preserve_primary()
        needed=sum(bit for _,_,bit in events)
        if owner in self.bound:
            if self.bound[owner]is not emitter:self._error();return False
            return self.coverage&needed==needed
        self.bound[owner]=emitter
        for event,kind,bit in events:
            handler=self._listener(kind,owner)
            self.handlers.append((emitter,event,handler))
            try:emitter.on(event,handler);self.coverage|=bit
            except BaseException as error:self._diagnostic_error(error,primary)
        return self.coverage&needed==needed
    def _listener(self,kind,owner):
        def handler(*ignored,**ignored_keywords):self._append(kind,owner)
        return handler
    def bind_browser(self,browser):return self._bind(1,browser,(('disconnected',4,1),))
    def bind_context(self,context):return self._bind(2,context,(('close',3,2),))
    def bind_page(self,page):return self._bind(3,page,(('close',1,4),('crash',2,8)))
    def snapshot(self):
        return dict(schemaVersion=1,kind='browser-lifecycle-observation',browserCode=self.browser_code,enabled=self.enabled,
            coverageBits=self.coverage,clockValid=self.clock_valid,cleanupStarted=self.cleanup_started,finished=self.finished,
            droppedCount=self.dropped,diagnosticErrors=self.errors,rows=[dict(row)for row in self.rows],
            callbackWindowComplete=self.finished and self.enabled and self.coverage==15 and self.clock_valid and not(self.dropped or self.errors),
            recordingScopeCode=1,osCauseProven=False,qualification=False)
    @staticmethod
    def _write(path,data):
        with Path(path).open('xb')as stream:stream.write(data)
    def finish(self,path):
        if not self.enabled or not self.accepting:return False
        with self.cleanup_scope():
            primary=self._preserve_primary()
            self.phase(20);self.accepting=False
            for emitter,event,handler in self.handlers:
                try:emitter.remove_listener(event,handler)
                except BaseException as error:self._diagnostic_error(error,primary)
            self.handlers=[];self.bound={};self.finished=True
            try:
                data=json.dumps(self.snapshot(),separators=(',',':'),allow_nan=False).encode('ascii')
                if len(data)>65536:raise ValueError()
                self.writer(path,data);return True
            except BaseException as error:self._diagnostic_error(error,primary);return False
