"""Explicit blank-Writer diagnostic preparation; one owned caption click only.

These numbers describe harness preparation, never product auto-focus or normal
acceptance. Original retained ownership and preparation QPC remain authoritative.
"""
import ctypes as C

from suite_window_activation import (NativeActivationProbe, Point, Rect, TitleBarInfo,
    Input, InputData, MouseInput, caption_candidates, _owned_window, _caption_hit)
from writer_server_observer_prepare_native import (PreparationCode, PreparationError,
    PreparationNativeApi, OriginalAttachment, GuiThreadInfo, _number)

PROFILE = 'one-owned-caption-v1'
BOOLS = ('enabled eligible dpiEntered dpiRestored foregroundBefore readyBefore cleanupComplete').split()
INTS = {'stageCode':8, 'reasonCode':3, 'pointerMoves':1, 'inputCalls':1, 'requestedInputs':2,
    'insertedInputs':2, 'releaseCalls':1, 'releaseInsertedInputs':1,
    'pendingInputPrefix':1, 'pendingDpiContext':1}


class NativeCaptionProbe(NativeActivationProbe):
    """Reuse measured native leaves, not the Popen wrapper or unbounded release.

    Only user/DWM signatures used below are bound. The shared normal constructor
    also binds process-image functions with a different ctypes buffer type; it
    must not overwrite the original PreparationNativeApi's typed process port.
    """
    def __init__(self, budget, *, prep, user=None, kernel=None, dwm=None):
        if type(prep) is not PreparationNativeApi or C.sizeof(C.c_void_p) != 8:
            raise PreparationError(PreparationCode.PLATFORM)
        self.budget, self.prep = budget, prep
        self.deadline = budget.cutoff_qpc / budget.frequency
        self.clock = lambda: self.check_work() / budget.frequency
        self.user = user if user is not None else C.WinDLL('user32', use_last_error=True)
        self.dwm = dwm if dwm is not None else C.WinDLL('dwmapi', use_last_error=True)
        H, U, B = C.c_void_p, C.c_uint32, C.c_int32
        definitions = {
            'IsWindow':((H,),B), 'IsWindowVisible':((H,),B), 'IsWindowEnabled':((H,),B),
            'IsIconic':((H,),B), 'GetAncestor':((H,U),H),
            'GetWindowThreadProcessId':((H,C.POINTER(U)),U),
            'GetWindowRect':((H,C.POINTER(Rect)),B), 'GetTitleBarInfo':((H,C.POINTER(TitleBarInfo)),B),
            'WindowFromPhysicalPoint':((Point,),H), 'SetPhysicalCursorPos':((B,B),B),
            'GetPhysicalCursorPos':((C.POINTER(Point),),B),
            'SetThreadDpiAwarenessContext':((H,),H), 'GetThreadDpiAwarenessContext':((),H),
            'AreDpiAwarenessContextsEqual':((H,H),B),
            'SendMessageTimeoutW':((H,U,C.c_size_t,C.c_ssize_t,U,U,C.POINTER(C.c_size_t)),C.c_ssize_t),
            'GetAsyncKeyState':((C.c_int,),C.c_int16), 'GetSystemMetrics':((C.c_int,),B),
            'SendInput':((U,C.POINTER(Input),C.c_int),U)}
        try:
            for name,(args,result) in definitions.items():
                function=getattr(self.user,name);function.argtypes,function.restype=args,result
            self.dwm.DwmGetWindowAttribute.argtypes=(H,U,H,U)
            self.dwm.DwmGetWindowAttribute.restype=B
        except BaseException:raise PreparationError(PreparationCode.NATIVE) from None

    def check_work(self):
        try:return self.budget.check(observation=True)
        except BaseException:raise PreparationError(PreparationCode.BUDGET) from None

    def check_cleanup(self):
        try:self.budget.check(observation=False);return True
        except BaseException:return False

    def _call(self, function, *args):
        self.check_work()
        try:value=function(*args)
        except BaseException:raise PreparationError(PreparationCode.NATIVE) from None
        self.check_work()
        return value

    @staticmethod
    def _required(value, operation):
        if not value:raise PreparationError(PreparationCode.NATIVE)
        return value

    def gui_clear(self, attachment):
        for tid in (attachment.host_thread, attachment.engine_thread):
            info=GuiThreadInfo(size=C.sizeof(GuiThreadInfo))
            if not self._call(self.prep._gui,tid,C.byref(info)):
                raise PreparationError(PreparationCode.NATIVE)
            if info.flags or info.capture or info.menu or info.move_size:return False
            for value in (info.active,info.focus):
                hwnd=_number(value)
                if hwnd in (0,attachment.document,attachment.parent,attachment.child):continue
                if not (self._call(self.prep._is_window,hwnd) and
                        _number(self._call(self.prep._root,hwnd,2))==attachment.document and
                        self.prep._identity(hwnd,self.check_work)==(attachment.engine_pid,attachment.engine_thread) and
                        self._call(self.prep._is_child,attachment.child,hwnd)):
                    return False
        return True

    def keys_clear(self, primary=None):
        for key in (1,2,4,5,6,0x10,0x11,0x12,0x5b,0x5c):
            if self._call(self.user.GetAsyncKeyState,key) & 0x8000 and key!=primary:return False
        return True

    def owned(self, c, launch, cohort, attachment, *, original=None, point=None, primary=None):
        self.check_work();cohort.verify(self.budget)
        if c.prep.recheck_attachment(launch,attachment,check=self.check_work) is not True:
            raise PreparationError(PreparationCode.ATTACHMENT)
        value=self.window_snapshot(attachment.document)
        _owned_window(value,attachment.document,attachment.host_pid)
        if value['threadId']!=attachment.host_thread or original is not None and value!=original:
            raise PreparationError(PreparationCode.GENERATION)
        for hwnd in (attachment.parent,attachment.child):
            if not (self._call(self.user.IsWindowVisible,hwnd) and self._call(self.user.IsWindowEnabled,hwnd)):
                raise PreparationError(PreparationCode.ATTACHMENT)
        if not self.gui_clear(attachment) or not self.keys_clear(primary):
            raise PreparationError(PreparationCode.ATTACHMENT)
        if point is not None:
            position=Point();self._required(self._call(self.user.GetPhysicalCursorPos,C.byref(position)),None)
            if ([int(position.x),int(position.y)]!=list(point) or
                    not _caption_hit(self.point_snapshot(attachment.document,point),attachment.document,attachment.host_pid,point)):
                raise PreparationError(PreparationCode.ATTACHMENT)
        cohort.verify(self.budget);self.check_work()
        return value


class OwnedCaptionPreparation:
    def __init__(self, *, probe_factory=None):
        self._factory=probe_factory
        self._attempted=False
        self._probe=self._dpi=None

    def __repr__(self):return '<OwnedCaptionPreparation private>'

    def prepare(self, c, launch, cohort, attachment, budget, report):
        if self._attempted or type(attachment) is not OriginalAttachment:
            raise PreparationError(PreparationCode.GENERATION)
        self._attempted=True
        a,prep=report['captionActivation'],report['preparation']
        a.update({key:False for key in BOOLS});a.update({key:0 for key in INTS})
        a.update(enabled=True,cleanupComplete=True,stageCode=1,foregroundBefore=None,readyBefore=None)
        probe=None;dpi={};primary_error=None
        try:
            probe=self._factory(budget) if self._factory is not None else NativeCaptionProbe(budget,prep=c.prep)
            if type(probe) is not NativeCaptionProbe:raise PreparationError(PreparationCode.PLATFORM)
            self._probe,self._dpi=probe,dpi
            probe.check_work();cohort.verify(budget)
            focus=c.prep.focus_snapshot(launch,attachment,check=probe.check_work)
            a.update(foregroundBefore=focus.foreground_owned,readyBefore=focus.ready)
            if focus.ready is True:a.update(reasonCode=1);return
            if focus.foreground_owned is True:a.update(reasonCode=2);return
            a['stageCode']=2
            # Register the returned previous context before checking the deadline.
            probe.check_work()
            a['pendingDpiContext']=1
            try:previous=probe.user.SetThreadDpiAwarenessContext(-4)
            except BaseException:raise PreparationError(PreparationCode.NATIVE) from None
            if previous is None or type(previous) is int and previous==0:
                a['pendingDpiContext']=0
                raise PreparationError(PreparationCode.NATIVE)
            if type(previous) is not int or not 0<previous<1<<64:
                raise PreparationError(PreparationCode.NATIVE)
            dpi['previous']=previous;a['dpiEntered']=True
            probe.check_work()
            observed=probe._call(probe.user.GetThreadDpiAwarenessContext)
            if not observed or not probe._call(probe.user.AreDpiAwarenessContextsEqual,observed,-4):
                raise PreparationError(PreparationCode.NATIVE)
            a['stageCode']=3
            original=probe.owned(c,launch,cohort,attachment)
            caption=probe.caption(attachment.document)
            if caption['state'] & (1|0x8000|0x10000):raise PreparationError(PreparationCode.ATTACHMENT)
            point=next((p for p in caption_candidates(original['rectangle'],caption['rectangle'])
                if _caption_hit(probe.point_snapshot(attachment.document,p),attachment.document,attachment.host_pid,p)),None)
            if point is None:raise PreparationError(PreparationCode.ATTACHMENT)
            a['stageCode']=4
            probe.owned(c,launch,cohort,attachment,original=original)
            # Effect intent precedes the native pointer call; no retry after error.
            probe.check_work();a['pointerMoves']=1
            probe._required(probe.user.SetPhysicalCursorPos(*point),None)
            probe.check_work()
            probe.owned(c,launch,cohort,attachment,original=original,point=point)
            swapped=bool(probe._call(probe.user.GetSystemMetrics,23))
            down,up=(8,16) if swapped else (2,4)
            a.update(eligible=True,stageCode=5)
            payload=(Input*2)(Input(type=0,data=InputData(mouse=MouseInput(flags=down))),
                Input(type=0,data=InputData(mouse=MouseInput(flags=up))))
            probe.check_work()
            a.update(inputCalls=1,requestedInputs=2,insertedInputs=None,pendingInputPrefix=1)
            prep.update(activationCount=1,inputCount=None)
            try:inserted=probe.user.SendInput(2,payload,C.sizeof(Input))
            except BaseException:raise PreparationError(PreparationCode.NATIVE) from None
            if type(inserted) is not int or not 0<=inserted<=2:raise PreparationError(PreparationCode.NATIVE)
            a['insertedInputs']=inserted;prep['inputCount']=inserted
            a['pendingInputPrefix']=int(inserted==1)
            a['stageCode']=6
            probe.check_work()
            if inserted==1:
                # No deadline extension, foreign release, or unknown-prefix replay.
                probe.owned(c,launch,cohort,attachment,original=original,point=point,primary=2 if swapped else 1)
                prefix=(Input*1)(Input(type=0,data=InputData(mouse=MouseInput(flags=up))))
                probe.check_work();a.update(releaseCalls=1,releaseInsertedInputs=None,stageCode=7)
                prep['inputCount']=None
                try:released=probe.user.SendInput(1,prefix,C.sizeof(Input))
                except BaseException:raise PreparationError(PreparationCode.NATIVE) from None
                if type(released) is not int or not 0<=released<=1:raise PreparationError(PreparationCode.NATIVE)
                a['releaseInsertedInputs']=released;prep['inputCount']=inserted+released
                if released==1:a['pendingInputPrefix']=0
                probe.check_work()
            if inserted!=2:raise PreparationError(PreparationCode.NATIVE)
            a.update(stageCode=8,reasonCode=0)
        except BaseException as error:
            primary_error=error
            if a['reasonCode']==0:a['reasonCode']=3
            raise
        finally:
            if probe is not None and dpi:
                within=probe.check_cleanup()
                try:
                    # The original cleanup interval, not a fresh restoration budget.
                    if not within:raise PreparationError(PreparationCode.BUDGET)
                    returned=probe.user.SetThreadDpiAwarenessContext(dpi['previous'])
                    if not probe.check_cleanup():raise PreparationError(PreparationCode.BUDGET)
                    observed=probe.user.GetThreadDpiAwarenessContext()
                    if not probe.check_cleanup():raise PreparationError(PreparationCode.BUDGET)
                    restored=bool(returned and observed and probe.user.AreDpiAwarenessContextsEqual(observed,dpi['previous']))
                    a['dpiRestored']=restored
                    if restored:a['pendingDpiContext']=0
                    within=probe.check_cleanup() and within
                    if not within:raise PreparationError(PreparationCode.BUDGET)
                    if not restored:raise PreparationError(PreparationCode.NATIVE)
                except BaseException as error:
                    a['cleanupComplete']=False
                    if primary_error is None:
                        if type(error) is PreparationError:raise
                        raise PreparationError(PreparationCode.NATIVE) from None
            if a['pendingDpiContext'] or a['pendingInputPrefix']:a['cleanupComplete']=False
