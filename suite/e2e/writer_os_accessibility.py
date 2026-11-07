"""Bounded, content-free Windows MSAA/IA2 exposure for the owned Writer editor.

Only interface support, numeric roles/state and canonical ancestry are observed.
The existing OS child watchdog owns the deadline; this module creates no process,
COM apartment, input, focus action, provider or registration.
"""
from __future__ import annotations

import ctypes as C
import json
import math
import time
import os
from pathlib import Path

STAGES = {1: 'writer-os-owner', 2: 'writer-os-abi', 3: 'writer-os-root',
          4: 'writer-os-focus', 5: 'writer-os-document-role',
          6: 'writer-os-focus-state', 7: 'writer-os-ia2', 8: 'writer-os-text',
          9: 'writer-os-parent', 10: 'writer-os-owner', 11: 'writer-os-cleanup',
          12: 'writer-os-complete', 13: 'writer-os-protocol', 14: 'writer-os-timeout'}
_MAXIMA = dict(schemaVersion=1, verified=1, stageCode=14, hresult=0xffffffff,
    officePid=0xffffffff, officeCreationTime=2**64-1, childHwnd=2**64-1,
    rootRole=0x7fffffff, documentRole=0x7fffffff, focusedRole=0x7fffffff,
    focusedState=0x7fffffff, focusVariantType=0xffff, parentCount=32,
    ia2Supported=1, textSupported=1, ownerBefore=1, ownerAfter=1,
    referencesAcquired=256, referencesReleased=256, variantsCreated=64,
    variantsCleared=64, cleanupFailure=1, cleanupHresult=0xffffffff,
    ownerReleased=1)


class ProbeFailure(AssertionError):
    def __init__(self, hresult=0):
        super().__init__('Owned Writer OS accessibility exposure was not verified')
        self.hresult = hresult & 0xffffffff


def _request(request):
    if type(request) is not dict or request.keys() != {
            'officePid', 'officeCreationTime', 'childHwnd', 'expectedImage'}:
        raise ValueError('Closed Writer ownership request required')
    for key in ('officePid', 'officeCreationTime', 'childHwnd'):
        value = request[key]
        if type(value) is not int or not 0 < value <= _MAXIMA[key]:
            raise ValueError('Invalid Writer ownership identity')
    if type(request['expectedImage']) is not str or not 0 < len(request['expectedImage']) <= 32768:
        raise ValueError('Invalid pinned Office image')
    return request


def failure(request, stage=13):
    _request(request)
    result = {key: 0 for key in _MAXIMA}
    result.update(schemaVersion=1, stageCode=stage, officePid=request['officePid'],
                  officeCreationTime=request['officeCreationTime'], childHwnd=request['childHwnd'])
    return result


def validate(value, request):
    _request(request)
    if (type(value) is not dict or not _MAXIMA.keys() <= value.keys()
            or not value.keys() <= _MAXIMA.keys() | {'focusCall', 'guiFocus'}):
        raise ValueError('Closed Writer OS result required')
    if any(type(value[key]) is not int or not 0 <= value[key] <= maximum
           for key, maximum in _MAXIMA.items()):
        raise ValueError('Invalid Writer OS result number')
    if (value['schemaVersion'] != 1 or value['stageCode'] not in STAGES
            or any(value[key] != request[key] for key in ('officePid', 'officeCreationTime', 'childHwnd'))
            or value['referencesReleased'] > value['referencesAcquired']
            or value['variantsCleared'] > value['variantsCreated']):
        raise ValueError('Writer OS result identity or lifetime differs')
    if 'focusCall' in value:
        if __package__:
            from .writer_os_summary import valid_focus_call
        else:
            from writer_os_summary import valid_focus_call
        if not valid_focus_call(value['focusCall'], value['focusVariantType']):
            raise ValueError('Invalid Writer focus call observation')
    if 'guiFocus' in value:
        if __package__:
            from .writer_os_summary import valid_gui_focus
        else:
            from writer_os_summary import valid_gui_focus
        if not valid_gui_focus(value['guiFocus'], value.get('focusCall')):
            raise ValueError('Invalid Writer GUI focus observation')
    if value['verified'] and not (
            value['stageCode'] == 12 and value['documentRole'] == 15
            and value['rootRole'] > 0 and value['focusedRole'] > 0
            and value['focusedState'] & 4 and not value['focusedState'] & (1 | 0x8000 | 0x10000)
            and value['focusVariantType'] in (3, 9) and value['ia2Supported'] == value['textSupported'] == 1
            and value['ownerBefore'] == value['ownerAfter'] == value['ownerReleased'] == 1
            and value['referencesAcquired'] == value['referencesReleased']
            and value['variantsCreated'] == value['variantsCleared']
            and value['referencesAcquired'] >= 8 and value['variantsCreated'] >= 5
            and value['cleanupFailure'] == value['cleanupHresult'] == value['hresult'] == 0):
        raise ValueError('Unqualified Writer OS success')
    return dict(value)


def decode(stdout, request):
    try:
        if type(stdout) is not str or not 0 < len(stdout.encode('utf-8')) <= 4096:
            return failure(request)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate numeric key')
                result[key] = value
            return result
        return validate(json.loads(stdout, object_pairs_hook=unique), request)
    except Exception:
        return failure(request)


def failure_stage(value):
    try:
        stage = value['stageCode']
        return STAGES[stage] if type(stage) is int and stage in STAGES else STAGES[13]
    except Exception:
        return STAGES[13]


_ROOT_MAXIMA = dict(schemaVersion=1, diagnosticOnly=1, acceptanceEligible=0,
    freshRootLater=1, known=1, bridgeReachable=1, stageCode=15,
    officePid=0xffffffff, officeCreationTime=2**64-1, childHwnd=2**64-1,
    ownerBefore=1, ownerAfter=1, ownerReleased=1, referencesAcquired=3,
    referencesReleased=3, cleanupFailure=1, cleanupHresult=0xffffffff)
for _operation in ('root', 'service', 'ia2'):
    _ROOT_MAXIMA.update({_operation+suffix: maximum for suffix,maximum in (
        ('Attempted',1),('Completed',1),('NonNull',1),('Hresult',0xffffffff))})


def root_diagnostic_failure(request, stage=13):
    _request(request)
    result={key:0 for key in _ROOT_MAXIMA}
    result.update(schemaVersion=1,diagnosticOnly=1,freshRootLater=1,stageCode=stage,
        **{key:request[key] for key in ('officePid','officeCreationTime','childHwnd')})
    return result


def validate_root_diagnostic(value, request):
    _request(request)
    if type(value) is not dict or value.keys()!=_ROOT_MAXIMA.keys():
        raise ValueError('Closed Writer root diagnostic required')
    if any(type(value[key]) is not int or not 0<=value[key]<=maximum
            for key,maximum in _ROOT_MAXIMA.items()):
        raise ValueError('Invalid Writer root diagnostic number')
    if (value['schemaVersion']!=1 or value['diagnosticOnly']!=1 or value['freshRootLater']!=1
            or value['stageCode'] not in (1,2,3,4,5,6,7,8,13,14,15)
            or any(value[key]!=request[key] for key in ('officePid','officeCreationTime','childHwnd'))
            or value['referencesReleased']>value['referencesAcquired']):
        raise ValueError('Writer root diagnostic identity or lifetime differs')
    operations=('root','service','ia2')
    for index,name in enumerate(operations):
        if (value[name+'Completed']>value[name+'Attempted']
                or value[name+'NonNull']>value[name+'Attempted']
                or value[name+'Hresult'] and not value[name+'Completed']):
            raise ValueError('Unobserved Writer root diagnostic call')
        if index and value[name+'Attempted']:
            previous=operations[index-1]
            if not (value[previous+'Completed']==value[previous+'NonNull']==1
                    and value[previous+'Hresult']==0):
                raise ValueError('Writer root diagnostic call order differs')
    if value['referencesAcquired']!=sum(value[name+'NonNull'] for name in operations):
        raise ValueError('Writer root diagnostic reference count differs')
    qualified=(value['stageCode']==8 and value['ownerBefore']==value['ownerAfter']==value['ownerReleased']==1
        and value['referencesAcquired']==value['referencesReleased']==3
        and value['cleanupFailure']==value['cleanupHresult']==0
        and all(value[name+'Attempted']==value[name+'Completed']==value[name+'NonNull']==1
            and value[name+'Hresult']==0 for name in operations))
    if (value['known']!=value['bridgeReachable'] or bool(value['known'])!=bool(qualified)
            or value['stageCode']==8 and not value['known']):
        raise ValueError('Unqualified Writer root bridge observation')
    return dict(value)


def decode_root_diagnostic(stdout, request):
    try:
        if type(stdout) is not str or not 0<len(stdout.encode('utf-8'))<=4096:
            return root_diagnostic_failure(request)
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result: raise ValueError('Duplicate numeric key')
                result[key]=value
            return result
        return validate_root_diagnostic(json.loads(stdout,object_pairs_hook=unique),request)
    except Exception:
        return root_diagnostic_failure(request)


def observe_root_diagnostic(request, *, owner_factory=None, backend_factory=None):
    """Later fresh root only; never identifies the earlier failed COM object.

    The separate caller owns its remaining-budget watchdog. No role, focus,
    ancestry, text, VARIANT, provider registration or input is requested here.
    """
    record=root_diagnostic_failure(request,1);owner=backend=None;primary=False
    try:
        owner=(owner_factory or WindowsOwner)(request)
        owner.open();owner.check(full=True);record['ownerBefore']=1
        record['stageCode']=2
        def guard():
            try: owner.check()
            except BaseException:
                record['stageCode']=1
                raise
        backend=(backend_factory or RootCapabilityBackend)(guard,record)
        pointer=request['childHwnd']
        for stage,name in ((3,'root'),(4,'service'),(5,'ia2')):
            record['stageCode']=stage
            pointer=backend.capability(name,pointer)
            if record[name+'Hresult']!=0 or not pointer:
                raise ProbeFailure(record[name+'Hresult'])
        record['stageCode']=6
        owner.check(full=True);record['ownerAfter']=1
        record.update(stageCode=8,known=1,bridgeReachable=1)
    except BaseException:
        primary=True
    finally:
        if backend is not None:
            try:
                if not backend.close(): record['cleanupFailure']=1
            except BaseException:
                record['cleanupFailure']=1
        if owner is not None:
            try: record['ownerReleased']=int(owner.close() is True)
            except BaseException as exc:
                record['cleanupFailure']=1
                if type(exc) is ProbeFailure and not record['cleanupHresult']:
                    record['cleanupHresult']=exc.hresult
        if record['cleanupFailure'] or not record['ownerReleased']:
            record.update(known=0,bridgeReachable=0)
            if not primary: record['stageCode']=7
    return validate_root_diagnostic(record,request)


def observe(request, *, owner_factory=None, backend_factory=None, gui_deadline=None, clock=None):
    """Hold every probe failure; the caller enforces it after the original VCL gate."""
    record = failure(request, 1)
    owner = backend = None
    primary = False
    try:
        owner = (owner_factory or WindowsOwner)(request)
        owner.open()
        owner.check(full=True)
        record['ownerBefore'] = 1
        record['stageCode'] = 2
        def guard():
            try:
                owner.check()
            except BaseException:
                record['stageCode'] = 1
                raise
        backend = (backend_factory or RawComBackend)(guard, record)
        if isinstance(owner, WindowsOwner) and isinstance(backend, RawComBackend):
            backend._gui_focus_observer = _GuiFocusObserver(owner, record, gui_deadline, clock or time.monotonic)
        record['stageCode'] = 3
        root = backend.root(request['childHwnd'])
        root_identity = backend.identity(root)
        record['rootRole'] = backend.role(root)
        if record['rootRole'] == 0:
            raise ProbeFailure()
        record['stageCode'] = 4
        focused = backend.focus(root)
        record['stageCode'] = 5
        record['focusedRole'] = backend.role(focused)
        if record['focusedRole'] == 0:
            raise ProbeFailure()
        record['stageCode'] = 6
        record['focusedState'] = backend.state(focused)
        if not record['focusedState'] & 4 or record['focusedState'] & (1 | 0x8000 | 0x10000):
            raise ProbeFailure()
        for stage, interface, key in ((7, 'ia2', 'ia2Supported'), (8, 'text', 'textSupported')):
            record['stageCode'] = stage
            if not backend.support(focused, interface):
                raise ProbeFailure()
            record[key] = 1
        record['stageCode'] = 9
        cursor, visited = focused, set()
        for depth in range(33):  # No more than 32 parent calls/edges.
            identity = backend.identity(cursor)
            if identity in visited:
                raise ProbeFailure()
            visited.add(identity)
            role = backend.role(cursor)
            if role == 15:
                record['documentRole'] = role
            if identity == root_identity:
                break
            if depth == 32:
                raise ProbeFailure()
            cursor = backend.parent(cursor)
            record['parentCount'] += 1
            if cursor is None:
                raise ProbeFailure()
        record['stageCode'] = 5
        if record['documentRole'] != 15:
            raise ProbeFailure()
        record['stageCode'] = 10
        owner.check(full=True)
        record['ownerAfter'] = 1
        record.update(verified=1, stageCode=12)
    except BaseException as exc:
        primary = True
        if type(exc) is ProbeFailure:
            record['hresult'] = exc.hresult
    finally:
        if backend is not None:
            try:
                if not backend.close():
                    record['cleanupFailure'] = 1
            except BaseException:
                record['cleanupFailure'] = 1
        if owner is not None:
            try:
                record['ownerReleased'] = int(owner.close() is True)
            except BaseException as exc:
                record['cleanupFailure'] = 1
                if type(exc) is ProbeFailure and not record['cleanupHresult']:
                    record['cleanupHresult'] = exc.hresult
        if record['cleanupFailure'] or not record['ownerReleased']:
            record['verified'] = 0
            if not primary:
                record['stageCode'] = 11
    return validate(record, request)


class WindowsOwner:
    """One retained process generation; no process enumeration or UI properties."""
    def __init__(self, request):
        self.request, self.process = request, None

    def open(self):
        # The observer retains self before acquisition so its one finally block
        # can preserve both initialization and checked-close failures.
        from startup_smoke import EngineProcessWitness
        from windows_smoke import Windows
        self.process = EngineProcessWitness(self.request['officePid'])
        self.api = Windows()
        self.expected = os.path.normcase(str(Path(self.request['expectedImage']).resolve(strict=True)))

    def check(self, *, full=False):
        r, process, api = self.request, self.process, self.api
        if (process.creation_time != r['officeCreationTime'] or process.exited(0)
                or not api.user.IsWindow(r['childHwnd']) or api.pid(r['childHwnd']) != r['officePid']):
            raise ProbeFailure()
        if full:
            query = C.WinDLL('kernel32', use_last_error=True).QueryFullProcessImageNameW
            query.argtypes = (C.c_void_p, C.c_uint32, C.c_wchar_p, C.POINTER(C.c_uint32))
            query.restype = C.c_int32
            size = C.c_uint32(32768)
            image = C.create_unicode_buffer(size.value)
            if not query(process.handle, 0, image, C.byref(size)):
                raise ProbeFailure(0x80070000 | (C.get_last_error() & 0xffff))
            if os.path.normcase(str(Path(image.value).resolve(strict=True))) != self.expected:
                raise ProbeFailure()

    def close(self):
        process, self.process = self.process, None
        if process is not None and process.handle:
            # The shared witness close ignores CloseHandle's BOOL. This observer
            # must distinguish an attempted close from a verified release.
            handle, process.handle = process.handle, None
            if not process.close_handle(handle):
                raise ProbeFailure(0x80070000 | (C.get_last_error() & 0xffff))
            return True
        return False  # No exposed handle means its release was not observed.


class _GuiObservationFailure(Exception):
    def __init__(self, code):
        self.code = code


class _GuiFocusObserver:
    """Two diagnostic intervals on one retained owner/thread; no input authority.

    Codes: 0 unknown, 1 null, 2 original child, 3 its descendant,
    4 same Office process outside child, 5 foreign process.
    Errors: 1 missing/invalid/expired cap before work, 2 ABI, 3 owner/thread,
    4 GUI query, 5 stale returned window, 6 unexpected exception, 7 late work.
    A known snapshot is not a focus action acknowledgement or MSAA mapping.
    """
    def __init__(self, owner, record, deadline, clock):
        self.owner, self.deadline, self.clock = owner, deadline, clock
        self.thread, self.before_seen = 0, False
        self.record = dict(schemaVersion=1, diagnosticOnly=1, acceptanceEligible=0,
            before=self._empty(1), after=self._empty(2))
        record['guiFocus'] = self.record

    @staticmethod
    def _empty(phase):
        return dict(phaseCode=phase, attempted=0, known=0, errorCode=1,
            focusWithinChild=0, activeCode=0, focusCode=0, captureCode=0, menuOwnerCode=0)

    def _time(self):
        if (type(self.deadline) not in (int, float) or not math.isfinite(self.deadline)
                or self.deadline <= 0):
            raise _GuiObservationFailure(1)
        now = self.clock()
        if (type(now) not in (int, float) or not math.isfinite(now)
                or self.deadline > now + 45):
            raise _GuiObservationFailure(1)
        if now >= self.deadline:
            raise _GuiObservationFailure(7 if self.row['attempted'] else 1)

    def _call(self, function, *args):
        self._time()
        self.row['attempted'] = 1
        result = function(*args)
        self._time()
        return result

    def _abi(self):
        # WindowsOwner already imported this module to construct its Windows API.
        # Reuse the exact structure belonging to query_gui_thread_info's prototype.
        from windows_smoke import GuiThreadInfo
        try:
            def integer(kind, signed):
                return C.sizeof(kind) == 4 and kind(-1).value == (-1 if signed else 0xffffffff)
            if (C.sizeof(C.c_void_p) != 8 or C.sizeof(GuiThreadInfo) != 72
                    or [getattr(GuiThreadInfo, key).offset for key in
                        ('cbSize', 'flags', 'hwndActive', 'hwndFocus', 'hwndCapture',
                         'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret', 'rcCaret')]
                        != [0, 4, 8, 16, 24, 32, 40, 48, 56]):
                raise ValueError()
            fields = dict(GuiThreadInfo._fields_)
            if (not all(integer(fields[key], False) for key in ('cbSize', 'flags'))
                    or not all(fields[key] is C.c_void_p for key in
                        ('hwndActive', 'hwndFocus', 'hwndCapture', 'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret'))
                    or C.sizeof(fields['rcCaret']) != 16
                    or not all(integer(kind, True) for _, kind in fields['rcCaret']._fields_)):
                raise ValueError()
            user = self.owner.api.user
            window, child, thread, gui = user.IsWindow, user.IsChild, user.GetWindowThreadProcessId, user.GetGUIThreadInfo
            args = thread.argtypes
            if (tuple(window.argtypes) != (C.c_void_p,) or not integer(window.restype, True)
                    or tuple(child.argtypes) != (C.c_void_p, C.c_void_p) or not integer(child.restype, True)
                    or len(args) != 2 or args[0] is not C.c_void_p
                    or not integer(args[1]._type_, False) or not integer(thread.restype, False)
                    or len(gui.argtypes) != 2 or not integer(gui.argtypes[0], False)
                    or gui.argtypes[1] is not C.POINTER(GuiThreadInfo) or not integer(gui.restype, True)):
                raise ValueError()
            self.Info, self.Dword = GuiThreadInfo, args[1]._type_
        except BaseException:
            raise _GuiObservationFailure(2) from None

    def _window_thread(self, hwnd):
        pid = self.Dword()
        tid = self._call(self.owner.api.user.GetWindowThreadProcessId, hwnd, C.byref(pid))
        return pid.value, tid

    def _scope(self):
        owner, request = self.owner, self.owner.request
        process = owner.process
        if (process is None or not process.handle
                or process.creation_time != request['officeCreationTime']):
            raise _GuiObservationFailure(3)
        if (self._call(process.exited, 0)
                or not self._call(owner.api.user.IsWindow, request['childHwnd'])):
            raise _GuiObservationFailure(3)
        pid, thread = self._window_thread(request['childHwnd'])
        if (pid != request['officePid'] or type(thread) is not int or not 0 < thread <= 0xffffffff
                or self.thread and thread != self.thread):
            raise _GuiObservationFailure(3)
        self.thread = thread

    def _classify(self, hwnd):
        if not hwnd:
            return 1
        user, request = self.owner.api.user, self.owner.request
        if not self._call(user.IsWindow, hwnd):
            raise _GuiObservationFailure(5)
        pid, thread = self._window_thread(hwnd)
        if not pid or not thread:
            raise _GuiObservationFailure(5)
        if pid != request['officePid']:
            return 5
        if hwnd == request['childHwnd']:
            return 2
        return 3 if self._call(user.IsChild, request['childHwnd'], hwnd) else 4

    def __call__(self, phase):
        if phase not in (1, 2):
            return
        self.row = self._empty(phase)
        try:
            self._time()
            if phase == 2 and (not self.before_seen or not self.thread):
                raise _GuiObservationFailure(3)
            if phase == 1:
                self.before_seen = True
            self._abi()
            self._scope()
            try:
                info = self._call(self.owner.api.query_gui_thread_info, self.thread)
            except (OSError, AssertionError):
                raise _GuiObservationFailure(4) from None
            if type(info) is not self.Info or info.cbSize != 72:
                raise _GuiObservationFailure(2)
            codes = {key: self._classify(getattr(info, field)) for key, field in
                (('activeCode', 'hwndActive'), ('focusCode', 'hwndFocus'),
                 ('captureCode', 'hwndCapture'), ('menuOwnerCode', 'hwndMenuOwner'))}
            self._scope()
            self._time()
            self.row.update(known=1, errorCode=0, focusWithinChild=int(codes['focusCode'] in (2, 3)), **codes)
        except _GuiObservationFailure as error:
            self.row['errorCode'] = error.code
        except BaseException:
            self.row['errorCode'] = 6
        self.record['before' if phase == 1 else 'after'] = self.row


# Exact order in Microsoft SDK oleacc.h: IAccessibleVtbl (659..881).
# Unused entries are named solely to preserve the ABI; they are never invoked.
_ACCESSIBLE_SLOTS = (
    'QueryInterface', 'AddRef', 'Release', 'GetTypeInfoCount', 'GetTypeInfo',
    'GetIDsOfNames', 'Invoke', 'get_accParent', 'get_accChildCount', 'get_accChild',
    'get_accName', 'get_accValue', 'get_accDescription', 'get_accRole', 'get_accState',
    'get_accHelp', 'get_accHelpTopic', 'get_accKeyboardShortcut', 'get_accFocus',
    'get_accSelection', 'get_accDefaultAction', 'accSelect', 'accLocation',
    'accNavigate', 'accHitTest', 'accDoDefaultAction', 'put_accName', 'put_accValue')
_IIDS = dict(unknown='{00000000-0000-0000-c000-000000000046}',
    accessible='{618736e0-3c3d-11cf-810c-00aa00389b71}',
    service='{6d5140c1-7436-11ce-8034-00aa006009fa}',
    ia2='{e89f726e-c4f4-4c19-bb19-b647d7fa8478}',
    text='{24fd2ffb-3aad-4a08-8335-a3ad89c0fb4b}')


def plain_variant(variant):
    """Reuse the installed Windows ABI, excluding conversion and destructor code."""
    try:
        class RawVariant(C.Structure):
            _anonymous_ = tuple(variant._anonymous_)
            _fields_ = list(variant._fields_)
        value = RawVariant()
        if (C.sizeof(C.c_void_p) != 8 or C.sizeof(variant) != 24 or C.sizeof(value) != 24
                or RawVariant.vt.offset != 0 or RawVariant._.offset != 8
                or type(value._).VT_I4.size != 4 or type(value._).c_void_p.size != 8):
            raise ValueError('Unsupported native VARIANT ABI')
        return RawVariant
    except (AttributeError, TypeError):
        raise ValueError('Unsupported native VARIANT ABI') from None


def _windows_bindings():
    from types import SimpleNamespace
    # The original UIA collector already initialized its COM apartment. Import
    # only existing type metadata; do not initialize/change/uninitialize COM here.
    from comtypes import GUID
    from comtypes.automation import VARIANT
    variant = plain_variant(VARIANT)
    if os.name != 'nt' or C.sizeof(GUID) != 16 or C.sizeof(C.c_long) != 4:
        raise ValueError('Unsupported Windows COM ABI')
    accessible = C.WinDLL('oleacc').AccessibleObjectFromWindow
    accessible.argtypes = (C.c_void_p, C.c_uint32, C.POINTER(GUID), C.POINTER(C.c_void_p))
    accessible.restype = C.c_int32
    clear = C.WinDLL('oleaut32').VariantClear
    clear.argtypes, clear.restype = (C.POINTER(variant),), C.c_int32
    return SimpleNamespace(Variant=variant, Guid=GUID, call_type=C.WINFUNCTYPE,
                           accessible=accessible, clear=clear)


class RawComBackend:
    """Raw SDK calls: no IDispatch Invoke, auto-out conversion or COM error text."""
    def __init__(self, guard, record, *, bindings=None):
        self.guard, self.record = guard, record
        self.bindings = bindings or _windows_bindings()
        self.Variant, self.Guid = self.bindings.Variant, self.bindings.Guid
        self.references, self.variants = [], []

    def _invoke(self, pointer, slot, result, arguments, *values):
        table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
        address = table[slot]
        if not address:
            raise ProbeFailure()
        function = self.bindings.call_type(result, C.c_void_p, *arguments)(address)
        return function(pointer, *values)

    def _owned(self, function):
        output = C.c_void_p()
        try:
            hr = function(C.byref(output))
        finally:
            if output.value:
                self.references.append(output.value)
                self.record['referencesAcquired'] += 1
        if hr != 0 or not output.value:
            raise ProbeFailure(hr)
        return output.value

    def _query(self, pointer, interface):
        self.guard()
        iid = self.Guid(_IIDS[interface])
        return self._owned(lambda output: self._invoke(pointer, 0, C.c_int32,
            (C.POINTER(self.Guid), C.POINTER(C.c_void_p)), C.byref(iid), output))

    def _variant(self):
        value = self.Variant()
        self.variants.append(value)
        self.record['variantsCreated'] += 1
        return value

    def _child(self, identifier=0):
        value = self.Variant()
        value.vt, value._.VT_I4 = 3, identifier
        return value

    def root(self, hwnd):
        self.guard()
        iid = self.Guid(_IIDS['accessible'])
        return self._owned(lambda output: self.bindings.accessible(
            hwnd, 0xfffffffc, C.byref(iid), output))  # OBJID_CLIENT (-4).

    def identity(self, pointer):
        # Keep the canonical IUnknown reference alive for the entire walk.
        return self._query(pointer, 'unknown')

    def _number(self, pointer, name):
        self.guard()
        output, child = self._variant(), self._child()
        hr = self._invoke(pointer, _ACCESSIBLE_SLOTS.index(name), C.c_int32,
            (self.Variant, C.POINTER(self.Variant)), child, C.byref(output))
        if hr != 0:
            raise ProbeFailure(hr)
        # Inspect only vt before accessing the numeric union member. A custom
        # BSTR role, BYREF or another type is cleared without reading payload.
        if output.vt != 3:
            raise ProbeFailure()
        value = output._.VT_I4
        if type(value) is not int or not 0 <= value <= 0x7fffffff:
            raise ProbeFailure()
        return value

    def role(self, pointer):
        return self._number(pointer, 'get_accRole')

    def state(self, pointer):
        return self._number(pointer, 'get_accState')

    def _gui_sample(self, phase):
        try:
            observer = getattr(self, '_gui_focus_observer', None)
            if observer is not None:
                observer(phase)
        except BaseException:
            pass  # Diagnostics never replace the original COM result/exception.

    def focus(self, root):
        self.guard()
        output = self._variant()
        self._gui_sample(1)
        # This client boundary is not evidence of native/server entry. Unknown
        # zero values remain unknown until their corresponding observed bit.
        call = dict(attempted=1, returned=0, hrObserved=0, hr=0, vtObserved=0, rejectCode=0)
        self.record['focusCall'] = call
        try:
            hr = self._invoke(root, 18, C.c_int32, (C.POINTER(self.Variant),), C.byref(output))
        except BaseException:
            call['rejectCode'] = 1
            raise
        finally:
            self._gui_sample(2)
        call.update(returned=1, hrObserved=1, hr=hr & 0xffffffff)
        self.record['focusVariantType'] = output.vt
        call['vtObserved'] = 1
        if hr != 0:
            call['rejectCode'] = 2
            raise ProbeFailure(hr)
        if output.vt == 9:
            borrowed = output._.c_void_p
            if not borrowed:
                call['rejectCode'] = 4
                raise ProbeFailure()
            return self._query(borrowed, 'accessible')
        if output.vt == 3:
            identifier = output._.VT_I4
            if identifier == 0:
                return self._query(root, 'accessible')
            if not 0 < identifier <= 0x7fffffff:
                call['rejectCode'] = 5
                raise ProbeFailure()
            self.guard()
            child = self._child(identifier)
            dispatch = self._owned(lambda result: self._invoke(root, 9, C.c_int32,
                (self.Variant, C.POINTER(C.c_void_p)), child, result))
            return self._query(dispatch, 'accessible')
        call['rejectCode'] = 3
        raise ProbeFailure()

    def support(self, pointer, interface):
        service = self._query(pointer, 'service')
        self.guard()
        sid, iid = self.Guid(_IIDS['accessible']), self.Guid(_IIDS[interface])
        self._owned(lambda result: self._invoke(service, 3, C.c_int32,
            (C.POINTER(self.Guid), C.POINTER(self.Guid), C.POINTER(C.c_void_p)),
            C.byref(sid), C.byref(iid), result))
        return True

    def parent(self, pointer):
        self.guard()
        dispatch = self._owned(lambda output: self._invoke(pointer, 7, C.c_int32,
            (C.POINTER(C.c_void_p),), output))
        return self._query(dispatch, 'accessible')

    def close(self):
        okay = True
        variants, self.variants = self.variants, []
        references, self.references = self.references, []
        for value in reversed(variants):
            try:
                hr = self.bindings.clear(C.byref(value))
                if hr != 0:
                    if not self.record['cleanupHresult']:
                        self.record['cleanupHresult'] = hr & 0xffffffff
                    okay = False
                else:
                    self.record['variantsCleared'] += 1
            except BaseException:
                okay = False
        for pointer in reversed(references):
            try:
                self._invoke(pointer, 2, C.c_uint32, ())
                self.record['referencesReleased'] += 1
            except BaseException:
                okay = False
        return okay


class RootCapabilityBackend(RawComBackend):
    """Same documented root/QI/QueryService ABI, with per-call numeric outcomes."""
    def __init__(self, guard, record, *, bindings=None):
        self.guard,self.record=guard,record
        if bindings is None:
            from types import SimpleNamespace
            from comtypes import GUID
            if (os.name!='nt' or C.sizeof(C.c_void_p)!=8
                    or C.sizeof(GUID)!=16 or C.sizeof(C.c_long)!=4):
                raise ValueError('Unsupported Windows root COM ABI')
            accessible=C.WinDLL('oleacc').AccessibleObjectFromWindow
            accessible.argtypes=(C.c_void_p,C.c_uint32,C.POINTER(GUID),C.POINTER(C.c_void_p))
            accessible.restype=C.c_int32
            bindings=SimpleNamespace(Guid=GUID,call_type=C.WINFUNCTYPE,accessible=accessible)
        self.bindings=bindings;self.Guid=bindings.Guid
        self.references,self.variants=[],[]  # The inherited close has no VARIANTs to clear.

    def capability(self, operation, pointer):
        if operation not in ('root','service','ia2'):
            raise ValueError('Unknown root capability operation')
        self.guard()
        iid=self.Guid(_IIDS['accessible' if operation=='root' else operation])
        sid=self.Guid(_IIDS['accessible']) if operation=='ia2' else None
        output=C.c_void_p()
        self.record[operation+'Attempted']=1
        try:
            if operation=='root':
                hr=self.bindings.accessible(pointer,0xfffffffc,C.byref(iid),C.byref(output))
            elif operation=='service':
                hr=self._invoke(pointer,0,C.c_int32,
                    (C.POINTER(self.Guid),C.POINTER(C.c_void_p)),C.byref(iid),C.byref(output))
            else:
                hr=self._invoke(pointer,3,C.c_int32,
                    (C.POINTER(self.Guid),C.POINTER(self.Guid),C.POINTER(C.c_void_p)),
                    C.byref(sid),C.byref(iid),C.byref(output))
        finally:
            self.record[operation+'NonNull']=int(bool(output.value))
            if output.value:
                self.references.append(output.value)
                self.record['referencesAcquired']+=1
        self.record[operation+'Hresult']=hr & 0xffffffff
        self.record[operation+'Completed']=1
        return output.value if hr==0 else 0
