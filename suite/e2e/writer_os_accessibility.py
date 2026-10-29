"""Bounded, content-free Windows MSAA/IA2 exposure for the owned Writer editor.

Only interface support, numeric roles/state and canonical ancestry are observed.
The existing OS child watchdog owns the deadline; this module creates no process,
COM apartment, input, focus action, provider or registration.
"""
from __future__ import annotations

import ctypes as C
import json
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
    if type(value) is not dict or value.keys() != _MAXIMA.keys():
        raise ValueError('Closed Writer OS result required')
    if any(type(value[key]) is not int or not 0 <= value[key] <= maximum
           for key, maximum in _MAXIMA.items()):
        raise ValueError('Invalid Writer OS result number')
    if (value['schemaVersion'] != 1 or value['stageCode'] not in STAGES
            or any(value[key] != request[key] for key in ('officePid', 'officeCreationTime', 'childHwnd'))
            or value['referencesReleased'] > value['referencesAcquired']
            or value['variantsCleared'] > value['variantsCreated']):
        raise ValueError('Writer OS result identity or lifetime differs')
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


def observe(request, *, owner_factory=None, backend_factory=None):
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


# Exact order in Microsoft SDK oleacc.h: IAccessibleVtbl (659..881).
# Unused entries are named solely to preserve the ABI; they are never invoked.
_ACCESSIBLE_SLOTS = (
    'QueryInterface', 'AddRef', 'Release', 'GetTypeInfoCount', 'GetTypeInfo',
    'GetIDsOfNames', 'Invoke', 'get_accParent', 'get_accChildCount', 'get_accChild',
    'get_accName', 'get_accValue', 'get_accDescription', 'get_accRole', 'get_accState',
    'get_accHelp', 'get_accHelpTopic', 'get_accKeyboardShortcut', 'get_accFocus',
    'get_accSelection', 'get_accDefaultAction', 'accSelect', 'accLocation',
    'accNavigate', 'accHitTest', 'accDoDefaultAction', 'put_accName', 'put_accValue')
_IIDS = dict(unknown='00000000-0000-0000-c000-000000000046',
    accessible='618736e0-3c3d-11cf-810c-00aa00389b71',
    service='6d5140c1-7436-11ce-8034-00aa006009fa',
    ia2='e89f726e-c4f4-4c19-bb19-b647d7fa8478',
    text='24fd2ffb-3aad-4a08-8335-a3ad89c0fb4b')


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

    def focus(self, root):
        self.guard()
        output = self._variant()
        hr = self._invoke(root, 18, C.c_int32, (C.POINTER(self.Variant),), C.byref(output))
        self.record['focusVariantType'] = output.vt
        if hr != 0:
            raise ProbeFailure(hr)
        if output.vt == 9:
            borrowed = output._.c_void_p
            if not borrowed:
                raise ProbeFailure()
            return self._query(borrowed, 'accessible')
        if output.vt == 3:
            identifier = output._.VT_I4
            if identifier == 0:
                return self._query(root, 'accessible')
            if not 0 < identifier <= 0x7fffffff:
                raise ProbeFailure()
            self.guard()
            child = self._child(identifier)
            dispatch = self._owned(lambda result: self._invoke(root, 9, C.c_int32,
                (self.Variant, C.POINTER(C.c_void_p)), child, result))
            return self._query(dispatch, 'accessible')
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
