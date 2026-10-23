"""Explicit raw-message diagnostic; neither IME nor Office qualification.

The production module, composition wire4 and its predicates stay unchanged.
Additional copies/atomics/setup/timestamps can perturb execution. Raw hook entry
and queue removal do not prove dispatch, TSF state, or semantic key delivery.
"""
import argparse
import ast
import ctypes
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import uuid

BASE_SOURCE_SHA256 = 'd5f0a4730aad7fbe37930e8e2db7f1e82fcf224b758b235e9d8c4d4dc2de03cd'
MAGIC, VERSION, CAPACITY, RAW_BYTES = 0x4f475257, 1, 128, 8256
GET_MESSAGES = (0x100, 0x101, 0x102, 0x10d, 0x10e, 0x10f, 0x286)
CALL_MESSAGES = (0x50, 0x51, 0x102, 0x10d, 0x10e, 0x10f, 0x286)
MAX_JSON_BYTES, MAX_CALL_BYTES = 131072, 16384

HEADER_FIELDS = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
    ('headerBytes', ctypes.c_uint32), ('rowBytes', ctypes.c_uint32),
    ('capacity', ctypes.c_uint32), ('enabled', ctypes.c_uint32),
    ('reservedCount', ctypes.c_int32), ('overflowBits', ctypes.c_uint32),
    ('writerReady', ctypes.c_uint32), ('cachedExpectedPid', ctypes.c_uint32),
    ('cachedExpectedTid', ctypes.c_uint32), ('reservedZero', ctypes.c_uint32),
    ('cachedEngineCreationTime', ctypes.c_uint64), ('nonce', ctypes.c_uint64)]
ROW_FIELDS = [('sequence', ctypes.c_uint32), ('hookKind', ctypes.c_uint32),
    ('nCode', ctypes.c_int32), ('validBits', ctypes.c_uint32),
    ('hookWParam', ctypes.c_uint64), ('hwnd', ctypes.c_uint64),
    ('message', ctypes.c_uint32), ('msgTime', ctypes.c_uint32),
    ('wParam', ctypes.c_uint64), ('lParam', ctypes.c_int64),
    ('ptX', ctypes.c_int32), ('ptY', ctypes.c_int32)]


class RawHeader(ctypes.Structure):
    _fields_ = HEADER_FIELDS


class RawRow(ctypes.Structure):
    _fields_ = ROW_FIELDS


class RawBuffer(ctypes.Structure):
    _fields_ = [('header', RawHeader), ('rows', RawRow * CAPACITY)]


READ_FIELDS = [('metadataVersion', ctypes.c_uint32), ('validityStatus', ctypes.c_uint32),
    ('copied', ctypes.c_uint32), ('countBefore', ctypes.c_int32), ('countAfter', ctypes.c_int32),
    ('overflowBefore', ctypes.c_uint32), ('overflowAfter', ctypes.c_uint32),
    ('writerReadyBefore', ctypes.c_uint32), ('writerReadyAfter', ctypes.c_uint32),
    ('enabledBefore', ctypes.c_uint32), ('enabledAfter', ctypes.c_uint32),
    ('completePrefix', ctypes.c_uint32)] + [('stableRowMask' + str(n), ctypes.c_uint32) for n in range(4)]


class RawReadMetadata(ctypes.Structure):
    _fields_ = READ_FIELDS


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def integer(value, low, high):
    assert type(value) is int and low <= value <= high, 'Diagnostic native integer width differs'
    return value


def error_text(error):
    try:
        message = str(error)
    except BaseException:
        message = '<unprintable>'
    return (type(error).__name__ + ': ' + message)[:160].encode('utf-8', errors='replace').decode('utf-8')


def native_binding(binding, tid):
    assert type(binding) is dict
    result = dict(binding)
    for key in ('shellPid', 'officePid'):
        integer(result[key], 1, 2**32 - 1)
    for key in ('shellCreationTime', 'officeCreationTime', 'suiteHwnd', 'parentHwnd', 'childHwnd', 'rootHwnd'):
        integer(result[key], 1, 2**64 - 1)
    assert result['suiteHwnd'] == result['rootHwnd']
    assert type(result['expectedImage']) is str and result['expectedImage']
    integer(tid, 1, 2**32 - 1)
    return result


def new_buffer(binding, tid, nonce):
    binding = native_binding(binding, tid)
    integer(nonce, 1, 2**64 - 1)
    assert (ctypes.sizeof(RawHeader), ctypes.sizeof(RawRow), ctypes.sizeof(RawBuffer)) == (64, 64, RAW_BYTES)
    value = RawBuffer()
    value.header = RawHeader(MAGIC, VERSION, 64, 64, CAPACITY, 1, 0, 0, 0,
        binding['officePid'], tid, 0, binding['officeCreationTime'], nonce)
    return value


def decode_snapshot(data, binding, tid, nonce, *, native_read_status=None, stable_row_masks=None):
    expected = new_buffer(binding, tid, nonce).header
    assert type(data) is bytes and len(data) == RAW_BYTES, 'Raw diagnostic extent differs'
    state = RawBuffer.from_buffer_copy(data)
    header = state.header
    for key in ('magic', 'version', 'headerBytes', 'rowBytes', 'capacity',
                'cachedExpectedPid', 'cachedExpectedTid', 'cachedEngineCreationTime', 'nonce', 'reservedZero'):
        assert getattr(header, key) == getattr(expected, key), 'Raw diagnostic header/binding differs: ' + key
    assert header.enabled in (0, 1) and header.writerReady in (0, 1)
    assert 0 <= header.reservedCount <= CAPACITY
    assert 0 <= header.overflowBits <= 7
    if native_read_status is not None:
        integer(native_read_status, 0, 1023)
    if stable_row_masks is not None:
        assert type(stable_row_masks) is list and len(stable_row_masks) == 4
        for value in stable_row_masks:
            integer(value, 0, 2**32 - 1)
    rows, incomplete = [], None
    for index in range(header.reservedCount):
        row = state.rows[index]
        stable = stable_row_masks is None or bool(stable_row_masks[index // 32] & (1 << (index % 32)))
        if row.sequence != index + 1 or not stable:
            incomplete = index + 1
            break
        assert row.nCode == 0 and row.hookKind in (1, 2)
        if row.hookKind == 2:
            assert row.validBits == 3 and row.hookWParam & 1 and row.message in GET_MESSAGES
        else:
            assert row.validBits == 0 and row.message in CALL_MESSAGES
        rows.append(dict(sequence=int(row.sequence), hookKind=int(row.hookKind), nCode=int(row.nCode),
            validBits=int(row.validBits), hookWParam=int(row.hookWParam), hwnd=int(row.hwnd),
            message=int(row.message), wParam=int(row.wParam), lParam=int(row.lParam),
            msgTime=int(row.msgTime) if row.validBits & 1 else None,
            point=[int(row.ptX), int(row.ptY)] if row.validBits & 2 else None,
            removed=bool(row.hookWParam & 1) if row.hookKind == 2 else None,
            origin='WH_GETMESSAGE-before-original-observe' if row.hookKind == 2 else 'WH_CALLWNDPROC-before-original-observe'))
    return dict(schemaVersion=1, kind='raw-hook-message-copy', diagnosticOnly=True,
        success=False, productQualified=False, officeReplacementCertified=False,
        expectedBinding=dict(binding), expectedEditorTid=tid, cachedIdentityOnly=True,
        actualRecipientIdentityMeasured=False, tsfStateObserved=False, semanticDeliveryProved=False,
        atomicSnapshotProved=False, negativeMessageAbsenceProved=False,
        stateEffectClaim=False, timingNeutralClaim=False,
        writerReady=bool(header.writerReady), reservedCount=int(header.reservedCount),
        overflowBits=int(header.overflowBits), firstIncompleteSequence=incomplete,
        nativeReadStatus=native_read_status,
        complete=bool(header.writerReady and header.enabled and not header.overflowBits
                      and incomplete is None and native_read_status == 0 and stable_row_masks is not None), rows=rows)


def secondary(action, primary):
    try:
        action()
    except BaseException as error:
        return primary if primary is not None else error
    return primary


class FirstKeyRecorder:
    """Observation around one call; returns/raises exactly what that call did."""
    def __init__(self, binding, *, clock=time.monotonic, get_error=None, set_error=None):
        self.binding = dict(binding)
        self.clock = clock
        self.get_error = get_error or getattr(ctypes, 'get_last_error', lambda: 0)
        self.set_error = set_error or getattr(ctypes, 'set_last_error', lambda value: None)
        self.started = False
        self.receipt = dict(schemaVersion=1, kind='diagnostic-first-native-input-call',
            diagnosticOnly=True, success=False, actualRecipientIdentityMeasured=False,
            semanticDeliveryProved=False, stateEffectClaim=False, timingNeutralClaim=False,
            intentDurableBeforeCall=False, persistedAfterCall=False, captureErrors=[])

    def _capture(self, action):
        try:
            return action()
        except BaseException as error:
            if len(self.receipt['captureErrors']) < 8:
                self.receipt['captureErrors'].append(error_text(error))
            return None

    def _buffer(self, payload, count, size):
        assert type(count) is int and count == 2 and type(size) is int and size == 40
        assert isinstance(payload, ctypes.Array) and ctypes.sizeof(payload) == 80
        return bytes(payload)

    def call(self, native, count, payload, size, *, token):
        if self.started:
            return native(count, payload, size)
        self.started = True  # Before clocks, encoding, byte capture or the native call.
        row = self.receipt
        row.update(token=token, requestedCount=count, cbSize=size,
                   expectedBinding=dict(self.binding), nativeCallAttempts=1)
        entry_error = self._capture(self.get_error)
        before = self._capture(lambda: self._buffer(payload, count, size))
        if before is not None:
            self._capture(lambda: row.update(bufferBeforeHex=before.hex(), bufferBeforeSha256=sha(before)))
        row['beforeNativeCall'] = self._capture(self.clock)
        row['intentCapturedBeforeCall'] = before is not None
        if entry_error is not None:
            self._capture(lambda: self.set_error(entry_error))
        try:
            returned = native(count, payload, size)
        except BaseException as primary:
            native_error = self._capture(self.get_error)
            row['nativeException'] = error_text(primary)
            row['nativeLastError'] = native_error
            row['afterNativeCall'] = self._capture(self.clock)
            after = self._capture(lambda: self._buffer(payload, count, size))
            if after is not None:
                self._capture(lambda: row.update(bufferAfterHex=after.hex(), bufferAfterSha256=sha(after)))
            if native_error is not None:
                self._capture(lambda: self.set_error(native_error))
            raise
        native_error = self._capture(self.get_error)
        try:
            row['returnCount'] = returned if type(returned) is int else None
            row['returnType'] = type(returned).__name__
            row['nativeLastError'] = native_error
            row['afterNativeCall'] = self._capture(self.clock)
            after = self._capture(lambda: self._buffer(payload, count, size))
            if after is not None:
                self._capture(lambda: row.update(bufferAfterHex=after.hex(), bufferAfterSha256=sha(after)))
        finally:
            if native_error is not None:
                self._capture(lambda: self.set_error(native_error))
        return returned


# Native sidecar source is deliberately separate from the production template.
NATIVE_RAW_SOURCE = r'''// Generated diagnostic copy only. Requires Windows/stdint/stddef declarations.
// __RAW_MAPPING__ is already C++-escaped; __RAW_NONCE__ is a uint64 literal.
// __RAW_ENABLED__ is true/false; false is an unavailable logger, never a case gate.
#pragma pack(push,8)
struct RawHeader {
    uint32_t magic,version,headerBytes,rowBytes,capacity,enabled;
    int32_t reservedCount;
    uint32_t overflowBits,writerReady,cachedExpectedPid,cachedExpectedTid,reservedZero;
    uint64_t cachedEngineCreationTime,nonce;
};
struct RawRow {
    uint32_t sequence,hookKind;
    int32_t nCode;
    uint32_t validBits;
    uint64_t hookWParam,hwnd;
    uint32_t message,msgTime;
    uint64_t wParam;
    int64_t lParam;
    int32_t ptX,ptY;
};
struct RawSidecar { RawHeader header; RawRow rows[128]; };
struct RawReadMetadata {
    uint32_t metadataVersion,validityStatus,copied;
    int32_t countBefore,countAfter;
    uint32_t overflowBefore,overflowAfter,writerReadyBefore,writerReadyAfter;
    uint32_t enabledBefore,enabledAfter,completePrefix,stableRowMasks[4];
};
#pragma pack(pop)
static_assert(sizeof(LONG)==4 && sizeof(void*)==8 && sizeof(WPARAM)==8 && sizeof(LPARAM)==8,"Raw witness requires native Windows64 widths");
static_assert(sizeof(RawHeader)==64 && sizeof(RawRow)==64 && sizeof(RawSidecar)==8256 && sizeof(RawReadMetadata)==64,"Raw witness extent drift");
#define RAW_OFFSET(Type,Name,Offset) static_assert(offsetof(Type,Name)==Offset,"Raw witness offset drift: " #Type "." #Name)
RAW_OFFSET(RawHeader,magic,0);RAW_OFFSET(RawHeader,version,4);RAW_OFFSET(RawHeader,headerBytes,8);
RAW_OFFSET(RawHeader,rowBytes,12);RAW_OFFSET(RawHeader,capacity,16);RAW_OFFSET(RawHeader,enabled,20);
RAW_OFFSET(RawHeader,reservedCount,24);RAW_OFFSET(RawHeader,overflowBits,28);RAW_OFFSET(RawHeader,writerReady,32);
RAW_OFFSET(RawHeader,cachedExpectedPid,36);RAW_OFFSET(RawHeader,cachedExpectedTid,40);RAW_OFFSET(RawHeader,reservedZero,44);
RAW_OFFSET(RawHeader,cachedEngineCreationTime,48);RAW_OFFSET(RawHeader,nonce,56);
RAW_OFFSET(RawRow,sequence,0);RAW_OFFSET(RawRow,hookKind,4);RAW_OFFSET(RawRow,nCode,8);RAW_OFFSET(RawRow,validBits,12);
RAW_OFFSET(RawRow,hookWParam,16);RAW_OFFSET(RawRow,hwnd,24);RAW_OFFSET(RawRow,message,32);RAW_OFFSET(RawRow,msgTime,36);
RAW_OFFSET(RawRow,wParam,40);RAW_OFFSET(RawRow,lParam,48);RAW_OFFSET(RawRow,ptX,56);RAW_OFFSET(RawRow,ptY,60);
RAW_OFFSET(RawSidecar,header,0);RAW_OFFSET(RawSidecar,rows,64);
RAW_OFFSET(RawReadMetadata,metadataVersion,0);RAW_OFFSET(RawReadMetadata,validityStatus,4);RAW_OFFSET(RawReadMetadata,copied,8);
RAW_OFFSET(RawReadMetadata,countBefore,12);RAW_OFFSET(RawReadMetadata,countAfter,16);RAW_OFFSET(RawReadMetadata,overflowBefore,20);
RAW_OFFSET(RawReadMetadata,overflowAfter,24);RAW_OFFSET(RawReadMetadata,writerReadyBefore,28);RAW_OFFSET(RawReadMetadata,writerReadyAfter,32);
RAW_OFFSET(RawReadMetadata,enabledBefore,36);RAW_OFFSET(RawReadMetadata,enabledAfter,40);RAW_OFFSET(RawReadMetadata,completePrefix,44);
RAW_OFFSET(RawReadMetadata,stableRowMasks,48);
#undef RAW_OFFSET

static constexpr uint32_t RAW_MAGIC=1330074199U;
static constexpr uint64_t RAW_NONCE=__RAW_NONCE__;
static constexpr bool RAW_CAPTURE_ENABLED=__RAW_ENABLED__;
static constexpr uint32_t RAW_OVERFLOW_CAPACITY=1, RAW_OVERFLOW_CONTENTION=2, RAW_OVERFLOW_INVALID_COUNTER=4;
static constexpr uint32_t RAW_READ_INVALID_HEADER=1,RAW_READ_INVALID_COUNTER=2,RAW_READ_COUNT_CHANGED=4;
static constexpr uint32_t RAW_READ_OVERFLOW_OBSERVED=8,RAW_READ_MISSING_PUBLICATION=16,RAW_READ_TORN_PUBLICATION=32;
static constexpr uint32_t RAW_READ_READY_UNAVAILABLE=64,RAW_READ_HEADER_CHANGED=128,RAW_READ_ENABLED_CHANGED=256,RAW_READ_OVERFLOW_CHANGED=512;
static volatile LONG raw_setup_attempted=0;
static HANDLE raw_mapping=nullptr;
static RawSidecar* raw_sidecar=nullptr;
// Expected facts copied from the validated sidecar, never measured at callbacks.
static uint32_t raw_cached_pid=0,raw_cached_tid=0;
static uint64_t raw_cached_creation=0;
struct RawLastError {
    DWORD value;
    RawLastError():value(GetLastError()) {}
    ~RawLastError() { SetLastError(value); }
};
static LONG raw_acquire(const uint32_t* value) {
    return InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(const_cast<uint32_t*>(value)),0,0);
}
static LONG raw_acquire(const int32_t* value) {
    return InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(const_cast<int32_t*>(value)),0,0);
}
static void raw_or(uint32_t* target,uint32_t bits) {
    InterlockedOr(reinterpret_cast<volatile LONG*>(target),static_cast<LONG>(bits));
}
static bool raw_header_valid(const RawHeader& h) {
    return h.magic==RAW_MAGIC && h.version==1 && h.headerBytes==64 && h.rowBytes==64 && h.capacity==128
        && h.enabled<=1 && h.writerReady<=1 && h.cachedExpectedPid>0 && h.cachedExpectedTid>0
        && h.reservedZero==0 && h.cachedEngineCreationTime>0 && RAW_NONCE>0 && h.nonce==RAW_NONCE;
}
static bool raw_header_same_immutable(const RawHeader& a,const RawHeader& b) {
    return a.magic==b.magic && a.version==b.version && a.headerBytes==b.headerBytes && a.rowBytes==b.rowBytes
        && a.capacity==b.capacity && a.cachedExpectedPid==b.cachedExpectedPid && a.cachedExpectedTid==b.cachedExpectedTid
        && a.reservedZero==b.reservedZero && a.cachedEngineCreationTime==b.cachedEngineCreationTime && a.nonce==b.nonce;
}
static void raw_setup_once(uint32_t expectedPid,uint32_t expectedTid) {
    RawLastError restore;
    // Reserve the sole attempt before acquiring any native ownership.
    if(InterlockedCompareExchange(&raw_setup_attempted,1,0)!=0)return;
    if(!RAW_CAPTURE_ENABLED)return;
    HANDLE handle=OpenFileMappingW(FILE_MAP_READ|FILE_MAP_WRITE,FALSE,L"__RAW_MAPPING__");
    if(!handle)return;
    RawSidecar* view=static_cast<RawSidecar*>(MapViewOfFile(handle,FILE_MAP_READ|FILE_MAP_WRITE,0,0,sizeof(RawSidecar)));
    if(!view) { CloseHandle(handle);return; }
    RawHeader header{};CopyMemory(&header,&view->header,sizeof(header));
    if(!raw_header_valid(header) || header.cachedExpectedPid!=expectedPid || header.cachedExpectedTid!=expectedTid
        || header.reservedCount!=0 || header.overflowBits!=0 || header.writerReady!=0) {
        // Each acquired owner is released once, even if the other release fails.
        UnmapViewOfFile(view);CloseHandle(handle);return;
    }
    raw_cached_pid=header.cachedExpectedPid;raw_cached_tid=header.cachedExpectedTid;
    raw_cached_creation=header.cachedEngineCreationTime;raw_mapping=handle;raw_sidecar=view;
    // Remote view/HANDLE lifetime is the original owned process lifetime.
    // There is no callback-quiescence or remote-unmap claim.
    MemoryBarrier();InterlockedExchange(reinterpret_cast<volatile LONG*>(&view->header.writerReady),1);
}
static bool raw_selected_get(uint32_t message) {
    return message==WM_KEYDOWN || message==WM_KEYUP || message==WM_CHAR || message==WM_IME_STARTCOMPOSITION
        || message==WM_IME_ENDCOMPOSITION || message==WM_IME_COMPOSITION || message==WM_IME_CHAR;
}
static bool raw_selected_call(uint32_t message) {
    // Root-authorized v3 delta: CALL-only raw language request/change payloads.
    return message==0x50 || message==0x51 || message==WM_CHAR || message==WM_IME_STARTCOMPOSITION || message==WM_IME_ENDCOMPOSITION
        || message==WM_IME_COMPOSITION || message==WM_IME_CHAR;
}
static void raw_publish(RawRow value) {
    RawSidecar* const target=raw_sidecar;
    if(!target || raw_acquire(&target->header.writerReady)!=1 || raw_acquire(&target->header.enabled)!=1)return;
    const LONG index=raw_acquire(&target->header.reservedCount);
    if(index<0) {raw_or(&target->header.overflowBits,RAW_OVERFLOW_INVALID_COUNTER);return;}
    if(index>=128) {raw_or(&target->header.overflowBits,RAW_OVERFLOW_CAPACITY);return;}
    // Exactly one reservation CAS; contention is diagnostic incompleteness.
    if(InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&target->header.reservedCount),index+1,index)!=index) {
        raw_or(&target->header.overflowBits,RAW_OVERFLOW_CONTENTION);return;
    }
    value.sequence=0;CopyMemory(&target->rows[index],&value,sizeof(value));
    MemoryBarrier();InterlockedExchange(reinterpret_cast<volatile LONG*>(&target->rows[index].sequence),index+1);
}
static void raw_hook_get(int code,WPARAM hookWParam,LPARAM pointer) {
    RawLastError restore;
    if(code!=HC_ACTION || !(hookWParam&PM_REMOVE) || !pointer)return;
    const MSG& message=*reinterpret_cast<const MSG*>(pointer);
    if(!raw_selected_get(message.message))return;
    RawRow value{};value.hookKind=2;value.nCode=code;value.validBits=3;
    value.hookWParam=static_cast<uint64_t>(hookWParam);value.hwnd=static_cast<uint64_t>(reinterpret_cast<uintptr_t>(message.hwnd));
    value.message=message.message;value.msgTime=message.time;value.wParam=static_cast<uint64_t>(message.wParam);
    value.lParam=static_cast<int64_t>(message.lParam);value.ptX=message.pt.x;value.ptY=message.pt.y;
    raw_publish(value);
}
static void raw_hook_call(int code,WPARAM hookWParam,LPARAM pointer) {
    RawLastError restore;
    if(code!=HC_ACTION || !pointer)return;
    const CWPSTRUCT& message=*reinterpret_cast<const CWPSTRUCT*>(pointer);
    if(!raw_selected_call(message.message))return;
    RawRow value{};value.hookKind=1;value.nCode=code;value.validBits=0;
    value.hookWParam=static_cast<uint64_t>(hookWParam);value.hwnd=static_cast<uint64_t>(reinterpret_cast<uintptr_t>(message.hwnd));
    value.message=message.message;value.wParam=static_cast<uint64_t>(message.wParam);value.lParam=static_cast<int64_t>(message.lParam);
    // Wire tags: CALL=1, GET=2. GET validBits=1(time)|2(point); CALL=0.
    // No fabricated MSG.time/point for CWPSTRUCT: validBits=0, storage zero.
    raw_publish(value);
}
'''

NATIVE_RAW_EXPORTS = r'''// Separate diagnostic exports. All source/destination pointers are caller-owned
// local mapped buffers of the exact declared extent, never foreign pointers.
extern "C" __declspec(dllexport) uint32_t RawStateSize() {return sizeof(RawSidecar);}
extern "C" __declspec(dllexport) uint32_t RawHeaderSize() {return sizeof(RawHeader);}
extern "C" __declspec(dllexport) uint32_t RawRowSize() {return sizeof(RawRow);}
extern "C" __declspec(dllexport) uint32_t RawReadMetadataSize() {return sizeof(RawReadMetadata);}
extern "C" __declspec(dllexport) uint32_t RawHeaderOffset(uint32_t index) {
    static const uint32_t offsets[]={offsetof(RawHeader,magic),offsetof(RawHeader,version),offsetof(RawHeader,headerBytes),
        offsetof(RawHeader,rowBytes),offsetof(RawHeader,capacity),offsetof(RawHeader,enabled),offsetof(RawHeader,reservedCount),
        offsetof(RawHeader,overflowBits),offsetof(RawHeader,writerReady),offsetof(RawHeader,cachedExpectedPid),
        offsetof(RawHeader,cachedExpectedTid),offsetof(RawHeader,reservedZero),offsetof(RawHeader,cachedEngineCreationTime),offsetof(RawHeader,nonce)};
    return index<14 ? offsets[index] : 0xffffffffU;
}
extern "C" __declspec(dllexport) uint32_t RawRowOffset(uint32_t index) {
    static const uint32_t offsets[]={offsetof(RawRow,sequence),offsetof(RawRow,hookKind),offsetof(RawRow,nCode),offsetof(RawRow,validBits),
        offsetof(RawRow,hookWParam),offsetof(RawRow,hwnd),offsetof(RawRow,message),offsetof(RawRow,msgTime),offsetof(RawRow,wParam),
        offsetof(RawRow,lParam),offsetof(RawRow,ptX),offsetof(RawRow,ptY)};
    return index<12 ? offsets[index] : 0xffffffffU;
}
extern "C" __declspec(dllexport) uint32_t RawReadMetadataOffset(uint32_t index) {
    static const uint32_t offsets[]={offsetof(RawReadMetadata,metadataVersion),offsetof(RawReadMetadata,validityStatus),offsetof(RawReadMetadata,copied),
        offsetof(RawReadMetadata,countBefore),offsetof(RawReadMetadata,countAfter),offsetof(RawReadMetadata,overflowBefore),offsetof(RawReadMetadata,overflowAfter),
        offsetof(RawReadMetadata,writerReadyBefore),offsetof(RawReadMetadata,writerReadyAfter),offsetof(RawReadMetadata,enabledBefore),offsetof(RawReadMetadata,enabledAfter),
        offsetof(RawReadMetadata,completePrefix),offsetof(RawReadMetadata,stableRowMasks),offsetof(RawReadMetadata,stableRowMasks)+4,
        offsetof(RawReadMetadata,stableRowMasks)+8,offsetof(RawReadMetadata,stableRowMasks)+12};
    return index<16 ? offsets[index] : 0xffffffffU;
}
static bool raw_overlap(const void* a,size_t asize,const void* b,size_t bsize) {
    const uintptr_t x=reinterpret_cast<uintptr_t>(a),y=reinterpret_cast<uintptr_t>(b);
    return x<=y ? y-x<asize : x-y<bsize;
}
extern "C" __declspec(dllexport) uint32_t ReadRawSnapshot(const RawSidecar* source,RawSidecar* destination,RawReadMetadata* metadata) {
    RawLastError restore;
    // Invalid arguments perform no copy/write. Caller must ignore metadata on0.
    if(!source || !destination || !metadata
        || raw_overlap(source,sizeof(*source),destination,sizeof(*destination))
        || raw_overlap(source,sizeof(*source),metadata,sizeof(*metadata))
        || raw_overlap(destination,sizeof(*destination),metadata,sizeof(*metadata)))return 0;
    RawReadMetadata result{};result.metadataVersion=1;
    RawHeader before{},after{};uint32_t sequences[128]{};
    CopyMemory(&before,&source->header,sizeof(before));
    result.countBefore=raw_acquire(&source->header.reservedCount);
    result.overflowBefore=static_cast<uint32_t>(raw_acquire(&source->header.overflowBits));
    result.writerReadyBefore=static_cast<uint32_t>(raw_acquire(&source->header.writerReady));
    result.enabledBefore=static_cast<uint32_t>(raw_acquire(&source->header.enabled));
    for(uint32_t index=0;index<128;++index)sequences[index]=static_cast<uint32_t>(raw_acquire(&source->rows[index].sequence));
    MemoryBarrier();
    // Exactly one fixed full native-byte copy. Never rewrite destination rows.
    CopyMemory(destination,source,sizeof(*destination));result.copied=1;
    MemoryBarrier();
    uint32_t afterSequences[128]{};
    for(uint32_t index=0;index<128;++index)afterSequences[index]=static_cast<uint32_t>(raw_acquire(&source->rows[index].sequence));
    result.countAfter=raw_acquire(&source->header.reservedCount);
    result.overflowAfter=static_cast<uint32_t>(raw_acquire(&source->header.overflowBits));
    result.writerReadyAfter=static_cast<uint32_t>(raw_acquire(&source->header.writerReady));
    result.enabledAfter=static_cast<uint32_t>(raw_acquire(&source->header.enabled));
    CopyMemory(&after,&source->header,sizeof(after));
    const bool headersValid=raw_header_valid(before) && raw_header_valid(destination->header) && raw_header_valid(after);
    if(!headersValid)result.validityStatus|=RAW_READ_INVALID_HEADER;
    if(!raw_header_same_immutable(before,destination->header) || !raw_header_same_immutable(before,after))result.validityStatus|=RAW_READ_HEADER_CHANGED;
    const bool countsValid=result.countBefore>=0 && result.countBefore<=128 && result.countAfter>=0 && result.countAfter<=128
        && destination->header.reservedCount>=0 && destination->header.reservedCount<=128;
    if(!countsValid)result.validityStatus|=RAW_READ_INVALID_COUNTER;
    if(result.countBefore!=result.countAfter || destination->header.reservedCount!=result.countBefore)result.validityStatus|=RAW_READ_COUNT_CHANGED;
    if(result.overflowBefore || result.overflowAfter || destination->header.overflowBits)result.validityStatus|=RAW_READ_OVERFLOW_OBSERVED;
    if(result.overflowBefore!=result.overflowAfter || destination->header.overflowBits!=result.overflowBefore)result.validityStatus|=RAW_READ_OVERFLOW_CHANGED;
    const bool ready=result.writerReadyBefore==1 && result.writerReadyAfter==1 && destination->header.writerReady==1;
    if(!ready)result.validityStatus|=RAW_READ_READY_UNAVAILABLE;
    if(result.enabledBefore!=result.enabledAfter || destination->header.enabled!=result.enabledBefore)result.validityStatus|=RAW_READ_ENABLED_CHANGED;
    uint32_t extent=0;
    if(countsValid)extent=static_cast<uint32_t>(result.countBefore<result.countAfter ? result.countBefore : result.countAfter);
    bool prefixOpen=headersValid && countsValid && ready;
    for(uint32_t index=0;index<128;++index) {
        if(index>=extent)continue;
        const uint32_t expected=index+1,prior=sequences[index],copied=destination->rows[index].sequence,later=afterSequences[index];
        const bool published=prior==expected && copied==expected && later==expected;
        if(!published) {
            if(!prior || !copied || !later)result.validityStatus|=RAW_READ_MISSING_PUBLICATION;
            else result.validityStatus|=RAW_READ_TORN_PUBLICATION;
        }
        if(published && headersValid && countsValid && ready)result.stableRowMasks[index/32]|=uint32_t(1)<<(index%32);
        if(prefixOpen && published)++result.completePrefix;else prefixOpen=false;
    }
    *metadata=result;
    return 1;
}
'''

_INCLUDE = '#include <stdint.h>\n'
_CONNECT = 'static bool connect() {'
_COMMAND = '    if (sequence==1 && !shared->status) {\n'
_CALL = 'extern "C" __declspec(dllexport) LRESULT CALLBACK HookCall(int code,WPARAM wp,LPARAM lp) {\n'
_GET = 'extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(int code,WPARAM wp,LPARAM lp) {\n'
_END = 'BOOL WINAPI DllMain(HINSTANCE,DWORD,LPVOID) { return TRUE; }'
_CASE_ARGUMENT = "            architecture=record['architecture'], setup_deadline=setup_deadline)"
_PHYSICAL_CALL = 'user.SendInput(len(payload), payload, ctypes.sizeof(Input))'


def _changes(mapping, nonce, capture_enabled=True):
    assert type(mapping) is str and re.fullmatch(r'Local\\Raw_[0-9a-f]{16,32}', mapping)
    integer(nonce, 1, 2**64 - 1)
    assert type(capture_enabled) is bool
    native = NATIVE_RAW_SOURCE.replace('__RAW_MAPPING__', mapping.replace('\\', '\\\\')).replace('__RAW_NONCE__', str(nonce) + 'ULL').replace('__RAW_ENABLED__', 'true' if capture_enabled else 'false')
    return ((_INCLUDE, _INCLUDE + '#include <stddef.h>\n'),
        (_CONNECT, native + '\n' + _CONNECT),
        (_COMMAND, _COMMAND + '        raw_setup_once(shared->pid,shared->tid);\n'),
        (_CALL, _CALL + '    raw_hook_call(code,wp,lp);\n'),
        (_GET, _GET + '    raw_hook_get(code,wp,lp);\n'),
        (_END, NATIVE_RAW_EXPORTS + '\n' + _END))


def instrument_source(source, mapping, nonce, *, capture_enabled=True):
    assert type(source) is str and sha(source.encode()) == BASE_SOURCE_SHA256, 'Production observer source drifted'
    generated, replacements = source, []
    for original, replacement in _changes(mapping, nonce, capture_enabled):
        assert generated.count(original) == 1, 'Diagnostic anchor absent or ambiguous'
        replacements.append(dict(anchorSha256=sha(original.encode()), count=1))
        generated = generated.replace(original, replacement, 1)
    assert remove_instrumentation(generated, mapping, nonce, capture_enabled=capture_enabled) == source
    return generated, dict(diagnosticOnly=True, originalSourceSha256=BASE_SOURCE_SHA256,
        instrumentedTemplateSha256=sha(generated.encode()), replacements=replacements,
        productionAbiChanged=False, originalCompositionCapacity=512, rawCapacity=CAPACITY, rawBytes=RAW_BYTES,
        rawCaptureEnabled=capture_enabled)


def remove_instrumentation(source, mapping, nonce, *, capture_enabled=True):
    for original, replacement in reversed(_changes(mapping, nonce, capture_enabled)):
        assert source.count(replacement) == 1, 'Diagnostic inverse source drifted'
        source = source.replace(replacement, original, 1)
    return source


def _clone(function, namespace):
    value = types.FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)
    value.__kwdefaults__ = function.__kwdefaults__
    return value


def _source(function):
    text = Path(function.__code__.co_filename).read_text(encoding='utf-8')
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function.__name__)
    return ast.get_source_segment(text, node)


def _compile_private(function, source, namespace):
    local = {}
    # Retain original source line numbers; the two private replacements each
    # occupy one original line. Diagnostic call frames remain explicit.
    padded = '\n' * (function.__code__.co_firstlineno - 1) + source
    exec(compile(padded, function.__code__.co_filename, 'exec'), namespace, local)
    return local[function.__name__]


def diagnostic_call(observer, token, record, native, count, payload, size):
    return observer.first_key.call(native, count, payload, size, token=token)


def make_physical_key(production):
    source = _source(production.physical_key)
    assert source.count(_PHYSICAL_CALL) == 1
    changed = source.replace(_PHYSICAL_CALL,
        'diagnostic_call(observer, token, record, user.SendInput, len(payload), payload, ctypes.sizeof(Input))', 1)
    namespace = dict(production.physical_key.__globals__, diagnostic_call=diagnostic_call)
    return _compile_private(production.physical_key, changed, namespace)


def make_private_initializer(production, generated):
    compiler = _clone(production.compile_observer, dict(production.compile_observer.__globals__, OBSERVER_SOURCE=generated))
    return _clone(production.CompositionObserver.__init__,
        dict(production.CompositionObserver.__init__.__globals__, compile_observer=compiler))


def make_private_main(production, observer_class):
    source = _source(production.case)
    assert source.count(_CASE_ARGUMENT) == 1
    changed = source.replace(_CASE_ARGUMENT,
        "            architecture=record['architecture'], setup_deadline=setup_deadline, diagnostic_native=dict(keyboard.binding), diagnostic_tid=keyboard.tid)", 1)
    case = _compile_private(production.case, changed, dict(production.case.__globals__,
        CompositionObserver=observer_class, physical_key=make_physical_key(production)))
    return _clone(production.main, dict(production.main.__globals__, case=case))


def encoded(value, maximum):
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    assert len(data) <= maximum, 'Diagnostic JSON exceeds its bound'
    return data


def write_once(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def file_pin(path):
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=sha(data))


class Sidecar:
    def __init__(self, binding, tid, nonce, name, *, factory=None):
        self.binding, self.tid, self.nonce = dict(binding), tid, nonce
        self.mapping = None
        value = new_buffer(binding, tid, nonce)
        try:
            self.mapping = (factory or (lambda: mmap.mmap(-1, RAW_BYTES, tagname=name)))()
            self.mapping[:] = bytes(value)
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                try:
                    primary.raw_sidecar_close_error = error_text(cleanup)
                except BaseException:
                    pass
            raise

    def close(self):
        value, self.mapping = self.mapping, None
        if value is not None:
            value.close()

    def configure(self, dll):
        for name, expected in [('RawStateSize', RAW_BYTES), ('RawHeaderSize', 64), ('RawRowSize', 64)]:
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = [], ctypes.c_uint32
            assert integer(fn(), 0, 2**32 - 1) == expected, 'Diagnostic DLL extent differs: ' + name
        for name, kind, fields in [('RawHeaderOffset', RawHeader, HEADER_FIELDS), ('RawRowOffset', RawRow, ROW_FIELDS)]:
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = [ctypes.c_uint32], ctypes.c_uint32
            for index, (field, _) in enumerate(fields):
                assert integer(fn(index), 0, 2**32 - 1) == getattr(kind, field).offset, 'Diagnostic DLL offset differs: ' + field
        fn = dll.RawReadMetadataSize
        fn.argtypes, fn.restype = [], ctypes.c_uint32
        assert integer(fn(), 0, 2**32 - 1) == ctypes.sizeof(RawReadMetadata) == 64, 'Diagnostic metadata extent differs'
        fn = dll.RawReadMetadataOffset
        fn.argtypes, fn.restype = [ctypes.c_uint32], ctypes.c_uint32
        for index, (field, _) in enumerate(READ_FIELDS):
            assert integer(fn(index), 0, 2**32 - 1) == getattr(RawReadMetadata, field).offset, 'Diagnostic metadata offset differs'
        dll.ReadRawSnapshot.argtypes = [ctypes.POINTER(RawBuffer), ctypes.POINTER(RawBuffer), ctypes.POINTER(RawReadMetadata)]
        dll.ReadRawSnapshot.restype = ctypes.c_uint32

    def snapshot(self, dll):
        assert self.mapping is not None
        # Exact signature and status contract are configured beside native source.
        source = RawBuffer.from_buffer(self.mapping)
        target = RawBuffer()
        metadata = RawReadMetadata()
        try:
            copied = dll.ReadRawSnapshot(ctypes.byref(source), ctypes.byref(target), ctypes.byref(metadata))
        finally:
            del source
        assert type(copied) is int and copied == 1, 'Raw diagnostic copy rejected buffer arguments'
        data = bytes(target)
        meta = {name: int(getattr(metadata, name)) for name, _ in READ_FIELDS}
        assert metadata.metadataVersion == 1 and metadata.copied == 1
        try:
            report = decode_snapshot(data, self.binding, self.tid, self.nonce,
                native_read_status=int(metadata.validityStatus),
                stable_row_masks=[int(getattr(metadata, 'stableRowMask' + str(n))) for n in range(4)])
        except BaseException as error:
            report = dict(diagnosticOnly=True, success=False, complete=False, decodeError=error_text(error))
        report['nativeReadMetadata'] = meta
        report['nativeReadMetadataBytesHex'] = bytes(metadata).hex()
        report['nativeReadMetadataSha256'] = sha(bytes(metadata))
        return data, report


def make_observer_class(production):
    class DiagnosticObserver(production.CompositionObserver):
        completed = []

        def __init__(self, *args, diagnostic_native, diagnostic_tid, **kwargs):
            self.raw = None
            self.raw_close_started = False
            self.raw_errors = []
            self.raw_folder = Path(args[5])
            self.first_key = FirstKeyRecorder(diagnostic_native)
            self.raw_entry = dict(schemaVersion=1, diagnosticOnly=True, success=False,
                expectedBinding=dict(diagnostic_native), expectedEditorTid=diagnostic_tid,
                actualRecipientIdentityMeasured=False, stateEffectClaim=False, timingNeutralClaim=False,
                remoteCallbackQuiescenceProved=False, remoteViewRetirementProved=False, errors=self.raw_errors)
            self.completed.append(self.raw_entry)
            capture_enabled = True
            try:
                name = 'Local\\Raw_' + uuid.uuid4().hex
                nonce = int(uuid.uuid4().hex[:16], 16) or 1
            except BaseException as error:
                # Render a disabled helper, never probe a fixed fallback name.
                capture_enabled = False
                name, nonce = 'Local\\Raw_' + '0' * 32, 1
                self.raw_errors.append(error_text(error))
            generated, audit = instrument_source(production.OBSERVER_SOURCE, name, nonce,
                                                 capture_enabled=capture_enabled)
            self.raw_entry.update(mappingName=name, nonce=nonce, instrumentation=audit)
            if capture_enabled:
                try:
                    self.raw = Sidecar(diagnostic_native, diagnostic_tid, nonce, name)
                except BaseException as error:
                    self.raw_errors.append(error_text(error))
                    if getattr(error, 'raw_sidecar_close_error', None):
                        self.raw_errors.append(error.raw_sidecar_close_error)
            try:
                initializer = make_private_initializer(production, generated)
                initializer(self, *args, **kwargs)
            except BaseException:
                self._release_raw()
                raise
            if self.raw is not None:
                try:
                    self.raw.configure(self.dll)
                except BaseException as error:
                    self.raw_errors.append(error_text(error))
                    self._release_raw()

        def _release_raw(self):
            if self.raw is not None:
                value, self.raw = self.raw, None
                try:
                    value.close()
                except BaseException as error:
                    self.raw_errors.append(error_text(error))

        def close(self):
            if self.raw_close_started:
                return
            self.raw_close_started = True
            binary, report = None, None
            if self.raw is not None and hasattr(self, 'dll'):
                try:
                    binary, report = self.raw.snapshot(self.dll)
                except BaseException as error:
                    self.raw_errors.append(error_text(error))
            try:
                super().close()  # Original native cleanup remains authoritative.
            finally:
                self._release_raw()
                self.raw_entry['observation'] = report
                try:
                    if binary is not None:
                        write_once(self.raw_folder / 'raw-message-witness.bin', binary)
                        self.raw_entry['binary'] = file_pin(self.raw_folder / 'raw-message-witness.bin')
                    self.raw_entry['firstKeyCall'] = self.first_key.receipt
                    source = self.raw_folder / 'ime-observer.cpp'
                    if source.is_file():
                        self.raw_entry['compiledSource'] = file_pin(source)
                    persisted = dict(self.first_key.receipt, persistedAfterCall=self.first_key.started)
                    write_once(self.raw_folder / 'first-key-call.json', encoded(persisted, MAX_CALL_BYTES))
                    self.first_key.receipt['persistedAfterCall'] = self.first_key.started
                    write_once(self.raw_folder / 'raw-message-witness.json', encoded(self.raw_entry, MAX_JSON_BYTES))
                except BaseException as error:
                    self.raw_errors.append(error_text(error))
    return DiagnosticObserver


def diagnostic_report(original):
    # Real case records are multi-megabyte native/reader receipts. Keep those
    # byte-exact in their original file, never duplicate them into this cap.
    tests = original.get('tests', [])
    summaries = []
    if type(tests) is list:
        for row in tests[:3]:
            if type(row) is not dict:
                summaries.append(dict(summaryUnavailable=True))
                continue
            summary = {key: row[key][:160] for key in ('case', 'module', 'stage', 'error')
                       if type(row.get(key)) is str}
            summary.update(success=row.get('success') is True, imeVerified=row.get('imeVerified') is True)
            summaries.append(summary)
    report = dict(schemaVersion=1, caseSummaries=summaries,
        originalCaseCount=len(tests) if type(tests) is list else None,
        caseSummaryTruncated=type(tests) is list and len(tests) > 3)
    report.update(kind='native-raw-message-witness-diagnostic', diagnosticOnly=True,
        productionCaseOutcomeObserved=original.get('success') is True,
        success=False, imeVerified=False, qualification=False, productQualified=False,
        wholePairQualified=False, officeReplacementCertified=False,
        mainNativePrivacySetupPerformed=False, privacyPreparationQualified=False,
        hostReadyQualified=False, stateEffectClaim=False, timingNeutralClaim=False)
    return report


def run_diagnostic(production, argv, output, binding):
    assert not output.exists() and not output.is_symlink() and not getattr(output, 'is_junction', lambda: False)()
    names = ('OBSERVER_SOURCE', 'CompositionObserver', 'compile_observer', 'physical_key', 'case', 'main')
    originals = {name: getattr(production, name) for name in names}
    observer = make_observer_class(production)
    main = make_private_main(production, observer)
    original_error, code = None, 1
    try:
        code = main(argv)
        return code
    except BaseException as error:
        original_error = error
        raise
    finally:
        try:
            assert all(getattr(production, name) is value for name, value in originals.items()), 'Production module global changed'
            if output.is_dir():
                path = output / 'results.json'
                original = {}
                if path.is_file():
                    write_once(output / 'production-case-results.json', path.read_bytes())
                    original = json.loads(path.read_text(encoding='utf-8'))
                report = diagnostic_report(original)
                report.update(sourceBinding=binding, productionExitCode=code,
                    originalProductionReport=file_pin(output / 'production-case-results.json') if path.is_file() else None,
                    originalError=None if original_error is None else error_text(original_error),
                    rawObservations=observer.completed,
                    limits=['Raw removed messages/hook entry do not prove dispatch or actual earlier input recipient.',
                            'No new raw-path IMM/key-state/HKL/TSF queries; added work still perturbs timing/state.',
                            'Sidecar snapshots are finite publication copies, not atomic or quiescent process snapshots.'])
                write_once(output / 'raw-message-diagnostic.json', encoded(report, MAX_JSON_BYTES * 4))
        except BaseException as error:
            # A diagnostic secondary failure never replaces original case/exit semantics.
            try:
                print('Raw diagnostic persistence unavailable: ' + error_text(error), file=sys.stderr)
            except BaseException:
                pass


def source_binding(environment, repository):
    required = ('GITHUB_SHA', 'GITHUB_REF', 'GITHUB_WORKFLOW_REF', 'GITHUB_WORKFLOW',
        'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_REPOSITORY')
    binding = {key: environment.get(key) for key in required}
    assert environment.get('GITHUB_ACTIONS') == 'true' and environment.get('RUNNER_ENVIRONMENT') == 'github-hosted'
    assert environment.get('RUNNER_OS') == 'Windows' and environment.get('RUNNER_ARCH') == 'ARM64'
    assert all(type(value) is str and value for value in binding.values())
    assert re.fullmatch(r'[0-9a-f]{40}', binding['GITHUB_SHA'])
    assert binding['GITHUB_REF'] == 'refs/heads/work/native35-arm64-input-witness'
    assert binding['GITHUB_JOB'] == 'windows-suite'
    assert binding['GITHUB_REPOSITORY'] == 'ATLKR/OpenGeul' and environment.get('GITHUB_EVENT_NAME') == 'push'
    assert re.fullmatch(r'[1-9][0-9]{0,19}', binding['GITHUB_RUN_ID']) and int(binding['GITHUB_RUN_ID']) < 2**64
    assert binding['GITHUB_RUN_ATTEMPT'] == '1'
    assert binding['GITHUB_WORKFLOW_REF'] == binding['GITHUB_REPOSITORY'] + '/.github/workflows/suite-native35-input-witness.yml@' + binding['GITHUB_REF']
    assert environment.get('GITHUB_WORKFLOW_SHA') == binding['GITHUB_SHA']
    head = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    assert head == binding['GITHUB_SHA'] and re.fullmatch(r'[0-9a-f]{40}', tree)
    files = []
    for name in ('ime_raw_message_witness.py', 'korean_ime_smoke.py', 'ime_thread_mode.h',
                 'ime_thread_mode_windows.h', 'ime_typed_origin.h', 'ime_command_admission.h'):
        path = Path(__file__).with_name(name)
        committed = subprocess.check_output(['git', '-C', str(repository), 'cat-file', 'blob', head + ':suite/e2e/' + name])
        assert path.read_bytes() == committed, 'Diagnostic executable/source header differs from committed bytes'
        files.append(file_pin(path))
    return dict(binding, gitHead=head, gitTree=tree, sourceFiles=files, diagnosticOnly=True,
        mainNativePrivacySetupPerformed=False, productQualified=False, officeReplacementCertified=False)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('suite', 'fixtures', 'readiness', 'output'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt' or not __debug__:
        raise RuntimeError('Native ARM64 Windows diagnostic with assertions is required')
    binding = source_binding(os.environ, Path(__file__).resolve().parents[2])
    import korean_ime_smoke as production
    return run_diagnostic(production, argv, args.output.resolve(), binding)


if __name__ == '__main__':
    raise SystemExit(main())
