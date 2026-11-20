"""Read-only preparation adapter for one creation-owned blank Writer host.

The caller owns payload admission, retained process births and the original
preparation budget. This adapter adds no deadline, activation, input or search
outside the original retained host thread. Windows/SDK execution is unverified.
"""
import ctypes as C
from dataclasses import dataclass, field
from enum import IntEnum
import sys


H, U32, B, U16 = C.c_void_p, C.c_uint32, C.c_int32, C.c_uint16
MAX_HANDLE = (1 << (C.sizeof(H) * 8)) - 1
MAX_I64 = (1 << 63) - 1
WINDOWS_ACTUAL_VERIFIED = False
SDK_COMPILE_VERIFIED = False


class PreparationCode(IntEnum):
    PLATFORM = 1
    BUDGET = 2
    NATIVE = 3
    GENERATION = 4
    ATTACHMENT = 5
    AMBIGUOUS = 6
    IMAGE = 7


class PreparationError(RuntimeError):
    def __init__(self, code):
        self.code = PreparationCode(code)
        super().__init__('writer_observer_preparation_' + self.code.name.lower())
    def __repr__(self):return '<PreparationError ' + self.code.name + '>'


class Rect(C.Structure):
    _fields_ = [(name, C.c_int32) for name in ('left','top','right','bottom')]
    def __repr__(self):return '<Rect private>'


class GuiThreadInfo(C.Structure):
    _fields_ = [('size',U32),('flags',U32),('active',H),('focus',H),('capture',H),
                ('menu',H),('move_size',H),('caret',H),('caret_rectangle',Rect)]
    def __repr__(self):return '<GuiThreadInfo private>'


@dataclass(frozen=True, slots=True, repr=False)
class OriginalAttachment:
    document: int
    parent: int
    child: int
    host_pid: int
    host_thread: int
    engine_pid: int
    engine_thread: int
    _host_handle: object = field(repr=False)
    _thread_handle: object = field(repr=False)
    _host_birth: int = field(repr=False)

    def __repr__(self):return '<OriginalAttachment private>'

    def private_tuple(self):
        return (self._host_handle,self._thread_handle,self.host_pid,self._host_birth,
                self.host_thread,self.document,self.parent,self.child,self.engine_pid,self.engine_thread)


@dataclass(frozen=True, slots=True, repr=False)
class FocusSnapshot:
    ready: bool
    query_succeeded: bool
    foreground_owned: bool
    focus_within_child: bool
    capture_clear: bool
    menu_clear: bool
    flags_clear: bool
    sampled_before_qpc: int
    sampled_after_qpc: int
    _original: object = field(repr=False)
    _raw: object = field(repr=False)

    def __repr__(self):return '<FocusSnapshot private>'

    def numeric_projection(self):
        return {name:getattr(self,name) for name in (
            'ready','query_succeeded','foreground_owned','focus_within_child',
            'capture_clear','menu_clear','flags_clear','sampled_before_qpc','sampled_after_qpc')}


def _handle(value):
    if type(value) is not int or not 0 < value < MAX_HANDLE:
        raise PreparationError(PreparationCode.GENERATION)
    return value


def _number(value):return int(getattr(value,'value',value) or 0)


def _utf16(text):
    value = text.encode('utf-16-le') + b'\0\0'
    return (U16 * (len(value)//2)).from_buffer_copy(value)


class PreparationNativeApi:
    def __init__(self, native, *, kernel=None, user=None):
        if C.sizeof(H) != 8:
            raise PreparationError(PreparationCode.PLATFORM)
        if kernel is None or user is None:
            if sys.platform != 'win32':raise PreparationError(PreparationCode.PLATFORM)
            kernel = kernel or C.WinDLL('kernel32',use_last_error=True)
            user = user or C.WinDLL('user32',use_last_error=True)
        self._native = native  # Process identity/provenance remains caller-owned.
        self._last_qpc, self._clock_invalid = None, False
        self._callback = getattr(C,'WINFUNCTYPE',C.CFUNCTYPE)(B,H,C.c_ssize_t)
        definitions = (
            (kernel,'_thread_id','GetThreadId',(H,),U32),
            (kernel,'_wait','WaitForSingleObject',(H,U32),U32),
            (kernel,'_image','QueryFullProcessImageNameW',(H,U32,C.POINTER(U16),C.POINTER(U32)),B),
            (user,'_enumerate','EnumThreadWindows',(U32,self._callback,C.c_ssize_t),B),
            (user,'_property','GetPropW',(H,C.POINTER(U16)),H),
            (user,'_is_window','IsWindow',(H,),B),
            (user,'_parent','GetParent',(H,),H),
            (user,'_root','GetAncestor',(H,U32),H),
            (user,'_window_identity','GetWindowThreadProcessId',(H,C.POINTER(U32)),U32),
            (user,'_is_child','IsChild',(H,H),B),
            (user,'_gui','GetGUIThreadInfo',(U32,C.POINTER(GuiThreadInfo)),B),
            (user,'_foreground','GetForegroundWindow',(),H),
        )
        try:
            for library,attribute,name,args,result in definitions:
                function = getattr(library,name);function.argtypes,function.restype = args,result
                setattr(self,attribute,function)
        except BaseException:
            raise PreparationError(PreparationCode.NATIVE) from None

    def __repr__(self):return '<PreparationNativeApi private>'

    def _check(self, check):
        try:
            if self._clock_invalid or not callable(check):raise ValueError()
            value = check()
            if (type(value) is not int or not 0 < value <= MAX_I64 or
                    self._last_qpc is not None and value < self._last_qpc):raise ValueError()
            self._last_qpc = value
            return value
        except BaseException:
            self._clock_invalid = True
            raise PreparationError(PreparationCode.BUDGET) from None

    def _call(self, check, function, *args):
        self._check(check)
        try:value = function(*args)
        except BaseException:raise PreparationError(PreparationCode.NATIVE) from None
        self._check(check)
        return value

    @staticmethod
    def _launch(launch):
        try:
            identity = launch.identity
            if (type(identity) is not tuple or len(identity)!=2 or
                    any(type(v) is not int or v<=0 for v in identity) or
                    identity[0]>0xffffffff or identity[1]>0xffffffffffffffff or
                    launch.failed is not False or launch.uncertain is not False or
                    launch.resumed is not True or launch.creation_job_membership is not True or
                    launch.pre_resume_verified is not True):raise ValueError()
            return _handle(launch.host),_handle(launch.thread),identity[0],identity[1]
        except BaseException:
            raise PreparationError(PreparationCode.GENERATION) from None

    def thread_id(self, retained_thread_handle, *, check):
        handle = _handle(retained_thread_handle)
        if _number(self._call(check,self._wait,handle,0)) != 258:
            raise PreparationError(PreparationCode.GENERATION)
        thread = _number(self._call(check,self._thread_id,handle))
        if not 0 < thread <= 0xffffffff:
            raise PreparationError(PreparationCode.GENERATION)
        if _number(self._call(check,self._wait,handle,0)) != 258:
            raise PreparationError(PreparationCode.GENERATION)
        return thread

    def _identity(self, hwnd, check):
        pid = U32()
        thread = _number(self._call(check,self._window_identity,hwnd,C.byref(pid)))
        if not 0 < thread <= 0xffffffff or not pid.value:
            raise PreparationError(PreparationCode.GENERATION)
        return int(pid.value),thread

    def _read(self, document, facts, thread, engine_pid, check):
        if not self._call(check,self._is_window,document):return None
        if self._identity(document,check) != (facts[2],thread):
            raise PreparationError(PreparationCode.GENERATION)
        if _number(self._call(check,self._root,document,2)) != document:
            raise PreparationError(PreparationCode.ATTACHMENT)
        parent = _number(self._call(check,self._property,document,_utf16('OpenGeul.Office.ParentHwnd')))
        child = _number(self._call(check,self._property,document,_utf16('OpenGeul.Office.ChildHwnd')))
        if not parent or not child:return None  # Source can still be publishing attachment.
        if len({document,parent,child}) != 3 or any(not 0<v<MAX_HANDLE for v in (parent,child)):
            raise PreparationError(PreparationCode.ATTACHMENT)
        for hwnd in (parent,child):
            if not self._call(check,self._is_window,hwnd):raise PreparationError(PreparationCode.ATTACHMENT)
            if _number(self._call(check,self._root,hwnd,2)) != document:
                raise PreparationError(PreparationCode.ATTACHMENT)
        if self._identity(parent,check) != (facts[2],thread):
            raise PreparationError(PreparationCode.GENERATION)
        actual_engine,editor_thread = self._identity(child,check)
        if actual_engine != engine_pid or actual_engine == facts[2]:
            raise PreparationError(PreparationCode.GENERATION)
        if (_number(self._call(check,self._parent,parent)) != document or
                _number(self._call(check,self._parent,child)) != parent or
                not self._call(check,self._is_child,document,parent) or
                not self._call(check,self._is_child,parent,child)):
            raise PreparationError(PreparationCode.ATTACHMENT)
        return document,parent,child,facts[2],thread,engine_pid,editor_thread

    def find_attachment_once(self, launch, expected_engine_pid, *, check):
        facts = self._launch(launch)
        if type(expected_engine_pid) is not int or not 0<expected_engine_pid<=0xffffffff or expected_engine_pid==facts[2]:
            raise PreparationError(PreparationCode.GENERATION)
        thread = self.thread_id(facts[1],check=check)
        candidates,error = [],[]
        def visit(hwnd, parameter):
            try:
                value = self._read(_number(hwnd),facts,thread,expected_engine_pid,check)
                if value is not None:candidates.append(value)
                return 1
            except BaseException as exc:
                error.append(exc.code if isinstance(exc,PreparationError) else PreparationCode.NATIVE)
                return 0  # Never let Python exceptions escape a ctypes callback.
        callback = self._callback(visit)
        enumerated = self._call(check,self._enumerate,thread,callback,0)
        if error:raise PreparationError(error[0])
        if not enumerated:raise PreparationError(PreparationCode.NATIVE)
        if self._launch(launch)!=facts or self.thread_id(facts[1],check=check)!=thread:
            raise PreparationError(PreparationCode.GENERATION)
        if not candidates:return None
        if len(candidates)!=1:raise PreparationError(PreparationCode.AMBIGUOUS)
        packet = candidates[0]
        if self._read(packet[0],facts,thread,expected_engine_pid,check)!=packet:
            raise PreparationError(PreparationCode.GENERATION)
        if self._launch(launch)!=facts or self.thread_id(facts[1],check=check)!=thread:
            raise PreparationError(PreparationCode.GENERATION)
        return OriginalAttachment(*packet,_host_handle=facts[0],_thread_handle=facts[1],_host_birth=facts[3])

    def recheck_attachment(self, launch, attachment, *, check):
        if type(attachment) is not OriginalAttachment:
            raise PreparationError(PreparationCode.ATTACHMENT)
        facts = self._launch(launch)
        if facts != (attachment._host_handle,attachment._thread_handle,attachment.host_pid,attachment._host_birth):
            raise PreparationError(PreparationCode.GENERATION)
        expected = (attachment.document,attachment.parent,attachment.child,attachment.host_pid,
                    attachment.host_thread,attachment.engine_pid,attachment.engine_thread)
        for _ in range(2):
            if self.thread_id(facts[1],check=check)!=attachment.host_thread:
                raise PreparationError(PreparationCode.GENERATION)
            if self._read(attachment.document,facts,attachment.host_thread,attachment.engine_pid,check)!=expected:
                raise PreparationError(PreparationCode.GENERATION)
        if (self._launch(launch)!=facts or
                self.thread_id(facts[1],check=check)!=attachment.host_thread):
            raise PreparationError(PreparationCode.GENERATION)
        return True

    def _foreground_sample(self, attachment, check):
        foreground = _number(self._call(check,self._foreground))
        foreground_owned = False
        if foreground and self._call(check,self._is_window,foreground):
            if _number(self._call(check,self._root,foreground,2))==attachment.document:
                foreground_owned = self._identity(foreground,check)[0] in (attachment.host_pid,attachment.engine_pid)
        return foreground,bool(foreground_owned)

    def focus_snapshot(self, launch, attachment, *, check):
        before = self._check(check)
        self.recheck_attachment(launch,attachment,check=check)
        foreground_before,owned_before = self._foreground_sample(attachment,check)
        info = GuiThreadInfo(size=C.sizeof(GuiThreadInfo))
        if not self._call(check,self._gui,attachment.engine_thread,C.byref(info)):
            raise PreparationError(PreparationCode.NATIVE)
        focus = _number(info.focus)
        inside = False
        if focus and self._call(check,self._is_window,focus):
            if (_number(self._call(check,self._root,focus,2))==attachment.document and
                    self._identity(focus,check)==(attachment.engine_pid,attachment.engine_thread)):
                inside = focus==attachment.child or bool(self._call(check,self._is_child,attachment.child,focus))
        capture_clear,menu_clear,flags_clear = not info.capture,not info.menu,info.flags==0
        self.recheck_attachment(launch,attachment,check=check)
        foreground_after,owned_after = self._foreground_sample(attachment,check)
        foreground_owned = owned_before and owned_after
        after = self._check(check)
        return FocusSnapshot(bool(foreground_owned and inside and capture_clear and menu_clear and flags_clear),
            True,bool(foreground_owned),bool(inside),capture_clear,menu_clear,flags_clear,before,after,
            attachment.private_tuple(),(focus,_number(info.capture),_number(info.menu),int(info.flags),foreground_before,foreground_after))

    def process_image(self, retained_handle, *, check):
        handle = _handle(retained_handle)
        buffer,length = (U16*32768)(),U32(32768)
        if not self._call(check,self._image,handle,0,buffer,C.byref(length)) or not 0<length.value<32768:
            raise PreparationError(PreparationCode.IMAGE)
        try:
            result = bytes(buffer)[:int(length.value)*2].decode('utf-16-le')
            if not result or '\0' in result:raise ValueError()
            return result
        except BaseException:raise PreparationError(PreparationCode.IMAGE) from None
