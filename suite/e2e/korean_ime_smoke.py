"""Real Microsoft Korean IME composition in owned Suite Writer/Calc/Impress frames.

Unlike Unicode keyboard injection, physical Dubeolsik scan codes must produce
in-process WM_IME_COMPOSITION receipts, survive Backspace, save and UNO reopen.
The observer is a temporary x64 DLL hooked only into the owned editor thread.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from windows_smoke import (Windows, INPUT_CASES, capture_failure, close_document,
    close_home, collect_cases, launch_suite, package_text, require_engine_fixture,
    stop_owned_test_process, verified_attachment, wait_for, write_result, ascii_input)
from engine_smoke import verify_content

EXPECTED_KEYS = list('gksrmf') + ['BACKSPACE', 'f', 'RIGHT']
SCANS = dict(zip('qwertyuiopasdfghjklzxcvbnm',
    (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
     0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
     0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32)))
SCANS.update(BACKSPACE=0x0e, RIGHT=0xe04d)


def scan_events(tokens):
    if not isinstance(tokens, (list, tuple)) or not 1 <= len(tokens) <= 64:
        raise ValueError('A bounded list of physical key names is required')
    result = []
    for token in tokens:
        if token not in SCANS: raise ValueError('Unsupported physical key: ' + str(token))
        scan = SCANS[token]
        flags = 8 | (1 if scan > 255 else 0)  # KEYEVENTF_SCANCODE, EXTENDEDKEY
        result.extend(({'vk': 0, 'scan': scan & 255, 'flags': flags},
                       {'vk': 0, 'scan': scan & 255, 'flags': flags | 2}))
    return result


def require_readiness(record):
    assert isinstance(record, dict) and record.get('suiteOnly') is True, 'Suite-only readiness is required'
    assert record.get('capabilityAfter') == 'Installed' and record.get('restartNeeded') is False, 'Korean Basic must be Installed without pending restart'
    assert record.get('userLanguageConfigured') is True, 'Current CI user has no configured Korean input profile'
    profile = record.get('profile', {})
    guid = r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}'
    assert profile.get('registered') is True and re.fullmatch('0412:' + guid + guid, profile.get('inputTip', '')), 'A registered native Korean TSF profile is required'
    assert profile.get('inputTip') == '0412:' + profile.get('providerClsid', '') + profile.get('profileGuid', ''), 'Registered TSF identity differs from its configured input tip'
    component = profile.get('component', {})
    assert component.get('signatureStatus') == 'Valid' and component.get('machine') == 0x8664, 'Native x64 Microsoft IME identity is unverified'
    assert re.fullmatch('[0-9a-f]{64}', component.get('sha256', '')), 'IME component digest is missing'
    assert re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', component.get('signerSubject', '')), 'IME component is not signed by Microsoft'
    return record


def marker(module):
    assert module in dict(INPUT_CASES)
    # Keep the ASCII prefix literal in the IME's alphanumeric mode, without
    # relying on synthetic implicit Shift state. Saved XML and UNO must match.
    return 'ime-opengeul-' + module + ':한글'


def activate_after_ascii_prefix(observer, module, record, send_ascii):
    # The marker scaffold belongs to setup, before switching input language or
    # IME conversion mode. Only the Hangul below is typed through Korean IME.
    record['stage'] = 'type-ascii-prefix-before-ime'
    observer.require_target()
    layout = int(observer.api.user.GetKeyboardLayout(observer.tid) or 0)
    assert layout & 0xffff == 0x0409, 'ASCII setup requires the verified original English input layout'
    assert not record.get('asciiEditorInputs'), 'IME ASCII setup requires one fresh counted input receipt'
    prefix = ' ' + marker(module).split('한글')[0]
    send_ascii(prefix)
    record.update(asciiPrefix=prefix, prefixInputLayout=layout,
                  stage='activate-microsoft-korean-profile')
    require_ascii_prefix(record)
    return observer.command(1)


def require_ascii_prefix(record):
    """Replay the one physical setup receipt before allowing Korean activation."""
    expected = ' ' + marker(record['module']).split('한글')[0]
    assert record.get('asciiPrefix') == expected and record.get('prefixInputLayout') == ascii_input.US_LAYOUT, 'IME ASCII setup requires its exact prefix on the original US layout'
    receipts = record.get('asciiEditorInputs')
    assert isinstance(receipts, list) and len(receipts) == 1, 'IME ASCII setup requires exactly one counted physical receipt'
    for key in ('windowHwnd', 'childHwnd', 'keyboardFocusHwnd', 'editorTid'):
        assert type(record.get(key)) is int and record[key] > 0, 'IME ASCII setup has no owned editor identity'
    receipt = ascii_input.require_ascii_receipt(receipts[0], expected, record['windowHwnd'], record['childHwnd'])
    assert receipt.get('pauseSeconds') == 0.04, 'IME ASCII setup must retain its original character pacing'
    for action in receipt['actions']:
        for side in ('before', 'after'):
            snapshot = action[side]
            assert snapshot['focusHwnd'] == record['keyboardFocusHwnd'] and snapshot['editorThreadId'] == record['editorTid'], 'IME ASCII setup differs from the observed editor focus/thread'
    return receipt


def validate_restoration(receipt):
    assert isinstance(receipt, dict) and receipt.get('command') == 4 and receipt.get('status') == 0, 'Native restoration command did not succeed'
    assert all(receipt.get(key) == 0 for key in ('profileManagerHresult', 'previousProfileHresult', 'activateProfileHresult', 'activeProfileHresult', 'activateLayoutError')), 'Native restoration API failed or its result is missing'
    assert receipt.get('previousLayout', 0) and receipt.get('layout') == receipt['previousLayout'], 'Original owned-thread HKL was not restored'
    assert receipt.get('previousProfileType') in (1, 2) and receipt.get('previousLanguage', 0), 'Original TSF identity was not captured'
    guid = r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}'
    for previous, active in (('previousProfileType', 'activeProfileType'), ('previousLanguage', 'activeLanguage'),
                             ('previousProfileLayout', 'activeProfileLayout')):
        assert previous in receipt and receipt.get(active) == receipt[previous], 'Original TSF profile was not restored'
    for previous, active in (('previousClsid', 'activeClsid'), ('previousProfile', 'activeProfile')):
        assert re.fullmatch(guid, receipt.get(previous, '')) and receipt.get(active, '').lower() == receipt[previous].lower(), 'Original TSF GUID identity was not restored'
    return receipt


def validate_ime_evidence(record):
    require_ascii_prefix(record)
    profile = require_readiness(record.get('readiness', {}))['profile']
    active = record.get('activeProfile', {})
    assert active.get('activeLanguage') == 0x0412 and active.get('activeClsid', '').lower() == profile['providerClsid'].lower() and active.get('activeProfile', '').lower() == profile['profileGuid'].lower(), 'Captured active TSF profile differs from the signed Microsoft readiness profile'
    assert record.get('inputMethod') == 'SendInput-scancode' and record.get('unicodeInputUsed') is False, 'Unicode input is not an IME test'
    assert record.get('keyTokens') == EXPECTED_KEYS, 'Actual Dubeolsik and Backspace keys are required'
    assert record.get('activeLayout', 0) & 0xffff == 0x0412, 'Focused thread has no active Korean layout'
    events = record.get('events')
    assert isinstance(events, list) and 1 <= len(events) <= 512, 'Actual composition messages are missing'
    compositions, results = [], []
    for event in events:
        assert (event.get('pid'), event.get('tid'), event.get('hwnd')) == (record['officePid'], record['editorTid'], record['keyboardFocusHwnd']), 'Composition came from another process, thread or HWND'
        assert event.get('layout', 0) & 0xffff == 0x0412, 'Composition came from a different input language'
        if event.get('message') != 0x10f: continue
        composition, result = event.get('composition', ''), event.get('result', '')
        assert isinstance(composition, str) and isinstance(result, str) and len(composition) <= 255 and len(result) <= 255, 'Invalid composition receipt'
        if composition and (not compositions or composition != compositions[-1]): compositions.append(composition)
        if result and (not results or result != results[-1]): results.append(result)
    pending = iter(compositions)
    assert all(any(value == expected for value in pending) for expected in ('ㅎ', '하', '한', 'ㄱ', '그', '글', '그', '글')), 'Live Dubeolsik/Backspace composition transitions are missing'
    assert ''.join(results) == '한글', 'The IME did not commit the exact Korean result'
    expected = marker(record['module'])
    assert record.get('asciiPrefix') == ' ' + expected.split('한글')[0] and record.get('prefixInputLayout', 0) & 0xffff == 0x0409, 'ASCII setup was not captured before Korean activation on the original English layout'
    assert expected in record.get('savedText', ''), 'Saved XML has no distinct newly typed Korean marker'
    observed = record.get('reopened', {})
    verify_content(record['module'], observed)
    assert expected in observed.get('text', ''), 'Actual UNO reopen lost the Korean marker'
    assert record.get('layoutRestored') is True, 'Owned input thread state was not restored'
    validate_restoration(record.get('restoration'))
    assert record['prefixInputLayout'] == record['restoration']['previousLayout'], 'ASCII setup and original input-state capture used different layouts'
    return {'imeVerified': True, 'backspaceCompositionVerified': True,
            'savedKoreanVerified': True, 'reopenedKoreanVerified': True}


# Fixed-width layout shared by x64 Python and x64 observer DLL. WCHAR is uint16,
# even when these policy helpers are imported on a non-Windows test host.
class NativeEvent(ctypes.Structure):
    _fields_ = [('sequence', ctypes.c_uint32), ('message', ctypes.c_uint32),
                ('flags', ctypes.c_uint32), ('pid', ctypes.c_uint32), ('tid', ctypes.c_uint32),
                ('hwnd', ctypes.c_uint64), ('layout', ctypes.c_uint64),
                ('compositionBytes', ctypes.c_int32), ('resultBytes', ctypes.c_int32),
                ('origin', ctypes.c_uint32), ('composition', ctypes.c_uint16 * 256),
                ('result', ctypes.c_uint16 * 256)]


class NativeState(ctypes.Structure):
    _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                ('pid', ctypes.c_uint32), ('tid', ctypes.c_uint32),
                ('count', ctypes.c_int32), ('overflow', ctypes.c_int32),
                ('command', ctypes.c_uint32), ('ack', ctypes.c_uint32),
                ('previousLayout', ctypes.c_uint64), ('previousOpen', ctypes.c_uint32),
                ('previousConversion', ctypes.c_uint32), ('previousSentence', ctypes.c_uint32),
                ('status', ctypes.c_int32), ('activeLanguage', ctypes.c_uint32),
                ('activeClsid', ctypes.c_uint16 * 40), ('activeProfile', ctypes.c_uint16 * 40),
                ('previousProfileType', ctypes.c_uint32), ('previousLanguage', ctypes.c_uint32),
                ('previousClsid', ctypes.c_uint16 * 40), ('previousProfile', ctypes.c_uint16 * 40),
                ('previousProfileLayout', ctypes.c_uint64), ('activeProfileType', ctypes.c_uint32),
                ('activeProfileLayout', ctypes.c_uint64), ('profileManagerHresult', ctypes.c_int32),
                ('previousProfileHresult', ctypes.c_int32), ('activateProfileHresult', ctypes.c_int32),
                ('activeProfileHresult', ctypes.c_int32), ('activateLayoutError', ctypes.c_uint32),
                ('events', NativeEvent * 512)]


OBSERVER_SOURCE = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <imm.h>
#include <msctf.h>
#include <stdint.h>
struct Event { uint32_t sequence,message,flags,pid,tid; uint64_t hwnd,layout;
    int32_t compositionBytes,resultBytes; uint32_t origin; WCHAR composition[256],result[256]; };
struct State { uint32_t magic,version,pid,tid; volatile LONG count,overflow;
    uint32_t command,ack; uint64_t previousLayout; uint32_t previousOpen,previousConversion,previousSentence;
    int32_t status; uint32_t activeLanguage; WCHAR activeClsid[40],activeProfile[40];
    uint32_t previousProfileType,previousLanguage; WCHAR previousClsid[40],previousProfile[40];
    uint64_t previousProfileLayout; uint32_t activeProfileType; uint64_t activeProfileLayout;
    int32_t profileManagerHresult,previousProfileHresult,activateProfileHresult,activeProfileHresult;
    uint32_t activateLayoutError; Event events[512]; };
static State* shared = nullptr;
static HANDLE mapping = nullptr;
static TF_INPUTPROCESSORPROFILE oldProfile = {};
static bool haveOldProfile = false;
static bool initialized = false;
static bool connect() {
    if (!shared) {
        mapping=OpenFileMappingW(FILE_MAP_ALL_ACCESS,FALSE,L"__MAPPING__");
        if (!mapping) return false;
        shared=(State*)MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(State));
    }
    return shared && shared->magic==0x4f47494d && shared->version==1
        && shared->pid==GetCurrentProcessId() && shared->tid==GetCurrentThreadId();
}
static ITfInputProcessorProfileMgr* profiles() {
    CLSID clsid; IID iid;
    CLSIDFromString(L"{33C53A50-F456-4884-B049-85FD643ECFED}",&clsid);
    CLSIDFromString(L"{71C6E74C-0F28-11D8-A82A-00065B84435C}",&iid);
    ITfInputProcessorProfileMgr* mgr=nullptr;
    shared->profileManagerHresult=CoCreateInstance(clsid,nullptr,CLSCTX_INPROC_SERVER,iid,(void**)&mgr);
    return mgr;
}
static void command(HWND hwnd, UINT sequence) {
    if (!sequence || sequence!=shared->command || shared->ack==sequence) return;
    HIMC himc=ImmGetContext(hwnd);
    if (!initialized) {
        shared->previousLayout=(uint64_t)(UINT_PTR)GetKeyboardLayout(0);
        shared->previousOpen=himc ? ImmGetOpenStatus(himc) : 0;
        DWORD conversion=0,sentence=0;
        if(himc) ImmGetConversionStatus(himc,&conversion,&sentence);
        shared->previousConversion=conversion; shared->previousSentence=sentence;
        initialized=true;
    }
    shared->status=0;
    ITfInputProcessorProfileMgr* mgr=profiles();
    GUID category; CLSIDFromString(L"{34745C63-B2F0-4784-8B67-5E12C8701A31}",&category);
    if (sequence==1) {
        shared->previousProfileHresult=mgr ? mgr->GetActiveProfile(category,&oldProfile) : E_UNEXPECTED;
        haveOldProfile=(shared->previousProfileHresult==S_OK);
        if (haveOldProfile) {
            shared->previousProfileType=oldProfile.dwProfileType; shared->previousLanguage=oldProfile.langid;
            shared->previousProfileLayout=(uint64_t)(UINT_PTR)oldProfile.hkl;
            StringFromGUID2(oldProfile.clsid,shared->previousClsid,40);
            StringFromGUID2(oldProfile.guidProfile,shared->previousProfile,40);
        }
        if (!haveOldProfile) { shared->status=-8; shared->activateProfileHresult=E_UNEXPECTED; }
        else {
            SetLastError(0);
            HKL korean=LoadKeyboardLayoutW(L"00000412",0);
            if (!korean || ((UINT_PTR)korean & 0xffff)!=0x0412 || !ActivateKeyboardLayout(korean,0)) {
                shared->activateLayoutError=GetLastError(); shared->status=-1;
            } else shared->activateLayoutError=0;
            GUID clsid,profile;
            CLSIDFromString(L"__CLSID__",&clsid); CLSIDFromString(L"__PROFILE__",&profile);
            shared->activateProfileHresult=mgr->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR,0x0412,clsid,profile,nullptr,0);
            if (shared->activateProfileHresult!=S_OK && !shared->status) shared->status=-2;
        }
    } else if (sequence==2 || sequence==3) {
        DWORD conversion=0,sentence=0;
        if (!himc || !ImmGetConversionStatus(himc,&conversion,&sentence)) shared->status=-3;
        else {
            // The following real WM_IME_COMPOSITION stream proves the effect.
            if (!ImmSetOpenStatus(himc,TRUE)) shared->status=-4;
            if (!ImmSetConversionStatus(himc, sequence==3 ? conversion|IME_CMODE_NATIVE : conversion&~IME_CMODE_NATIVE,sentence)) shared->status=-5;
        }
    } else if (sequence==4) {
        // With flags 0 ActivateProfile requires the current input language to match.
        // Restore this owned thread's HKL before its exact original TSF profile:
        // https://learn.microsoft.com/windows/win32/api/msctf/nf-msctf-itfinputprocessorprofilemgr-activateprofile
        SetLastError(0);
        if (!ActivateKeyboardLayout((HKL)(UINT_PTR)shared->previousLayout,0)) {
            shared->activateLayoutError=GetLastError(); shared->status=-7;
        } else shared->activateLayoutError=0;
        shared->activateProfileHresult=(mgr && haveOldProfile) ? mgr->ActivateProfile(oldProfile.dwProfileType,oldProfile.langid,
            oldProfile.clsid,oldProfile.guidProfile,
            oldProfile.dwProfileType==TF_PROFILETYPE_INPUTPROCESSOR ? nullptr : oldProfile.hkl,0) : E_UNEXPECTED;
        if (shared->activateProfileHresult!=S_OK && !shared->status) shared->status=-6;
        if (himc) { ImmSetOpenStatus(himc,shared->previousOpen);
            ImmSetConversionStatus(himc,shared->previousConversion,shared->previousSentence); }
    }
    if (himc) ImmReleaseContext(hwnd,himc);
    TF_INPUTPROCESSORPROFILE current={};
    shared->activeLanguage=0; shared->activeProfileType=0; shared->activeProfileLayout=0;
    shared->activeClsid[0]=0; shared->activeProfile[0]=0;
    shared->activeProfileHresult=mgr ? mgr->GetActiveProfile(category,&current) : E_UNEXPECTED;
    if (mgr) {
        if (shared->activeProfileHresult==S_OK) {
            shared->activeLanguage=current.langid;
            shared->activeProfileType=current.dwProfileType;
            shared->activeProfileLayout=(uint64_t)(UINT_PTR)current.hkl;
            StringFromGUID2(current.clsid,shared->activeClsid,40);
            StringFromGUID2(current.guidProfile,shared->activeProfile,40);
        }
        mgr->Release();
    }
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&shared->ack,sequence);
}
static void observe(HWND hwnd,UINT message,WPARAM wp,LPARAM lp,UINT origin) {
    if (!connect()) return;
    if (message==0x8351) { command(hwnd,(UINT)wp); return; }
    if (message!=WM_IME_STARTCOMPOSITION && message!=WM_IME_ENDCOMPOSITION && message!=WM_IME_COMPOSITION) return;
    DWORD pid=0; if(GetWindowThreadProcessId(hwnd,&pid)!=shared->tid || pid!=shared->pid) return;
    LONG index=InterlockedIncrement(&shared->count)-1;
    if(index<0 || index>=512) { InterlockedExchange(&shared->overflow,1); return; }
    Event* event=&shared->events[index];
    event->message=message; event->flags=(uint32_t)lp; event->pid=pid; event->tid=GetCurrentThreadId();
    event->hwnd=(uint64_t)(UINT_PTR)hwnd; event->layout=(uint64_t)(UINT_PTR)GetKeyboardLayout(0); event->origin=origin;
    if (message==WM_IME_COMPOSITION) {
        HIMC himc=ImmGetContext(hwnd);
        if (himc) {
            // Read IMM data only on the owning editor thread, never cross-process.
            if (lp&GCS_COMPSTR) {
                LONG bytes=ImmGetCompositionStringW(himc,GCS_COMPSTR,nullptr,0);
                event->compositionBytes=bytes;
                if(bytes>=0 && bytes<512 && !(bytes&1)) ImmGetCompositionStringW(himc,GCS_COMPSTR,event->composition,bytes);
            }
            if (lp&GCS_RESULTSTR) {
                LONG bytes=ImmGetCompositionStringW(himc,GCS_RESULTSTR,nullptr,0);
                event->resultBytes=bytes;
                if(bytes>=0 && bytes<512 && !(bytes&1)) ImmGetCompositionStringW(himc,GCS_RESULTSTR,event->result,bytes);
            }
            ImmReleaseContext(hwnd,himc);
        } else { event->compositionBytes=-99; event->resultBytes=-99; }
    }
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&event->sequence,index+1);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookCall(int code,WPARAM wp,LPARAM lp) {
    if(code>=0) { CWPSTRUCT* m=(CWPSTRUCT*)lp; observe(m->hwnd,m->message,m->wParam,m->lParam,1); }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(int code,WPARAM wp,LPARAM lp) {
    if(code>=0 && wp==PM_REMOVE) { MSG* m=(MSG*)lp; observe(m->hwnd,m->message,m->wParam,m->lParam,2); }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) unsigned int StateSize() { return sizeof(State); }
BOOL WINAPI DllMain(HINSTANCE,DWORD,LPVOID) { return TRUE; }
'''


def utf16(array):
    return bytes(array).decode('utf-16-le').split('\0', 1)[0]


def discover_msvc(folder, vswhere):
    command = [str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath']
    started = time.monotonic()

    def preserve(result, outcome):
        def encoded(value):
            return value.encode('utf-8') if isinstance(value, str) else value or b''
        (folder / 'compiler-discovery.log').write_bytes(encoded(getattr(result, 'stdout', None)) + encoded(getattr(result, 'stderr', None)))
        (folder / 'compiler-discovery.json').write_text(json.dumps({
            'stage': 'discover-msvc', 'command': command, 'timeoutSeconds': 60,
            'elapsedSeconds': time.monotonic() - started, 'outcome': outcome,
            'returncode': getattr(result, 'returncode', None),
            'exceptionType': type(result).__name__ if isinstance(result, Exception) else None,
            'exceptionMessage': str(result) if isinstance(result, Exception) else None,
            'winerror': getattr(result, 'winerror', None)}, indent=2), encoding='utf-8')

    try:
        # A hosted VS installation query exceeded 10s before compilation.
        # Allow the same one-shot bound as cl.exe, retaining the original output.
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        preserve(exc, 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'launch-error')
        raise
    preserve(result, 'complete' if result.returncode == 0 else 'nonzero-exit')
    result.check_returncode()
    return result.stdout.strip()


def compile_observer(folder, mapping, profile):
    source, library = folder / 'ime-observer.cpp', folder / 'ime-observer.dll'
    source.write_text(OBSERVER_SOURCE.replace('__MAPPING__', mapping.replace('\\', '\\\\'))
        .replace('__CLSID__', profile['providerClsid']).replace('__PROFILE__', profile['profileGuid']), encoding='utf-8')
    compiler = shutil.which('cl.exe')
    command = ['cl.exe', '/nologo', '/LD', '/O2', '/MT', '/EHsc', '/utf-8', str(source),
               '/link', '/OUT:' + str(library), 'user32.lib', 'imm32.lib', 'ole32.lib']
    if compiler:
        result = subprocess.run(command, cwd=folder, capture_output=True, timeout=60)
    else:
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        found = discover_msvc(folder, vswhere)
        vcvars = Path(found) / 'VC/Auxiliary/Build/vcvars64.bat'
        assert vcvars.is_file(), 'Microsoft x64 C++ build tools are required for the in-process observer'
        script = folder / 'compile-observer.cmd'
        script.write_text('@echo off\ncall "' + str(vcvars) + '"\nif errorlevel 1 exit /b 1\n' + subprocess.list2cmdline(command) + '\n', encoding='utf-8')
        result = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=folder, capture_output=True, timeout=60)
    (folder / 'compiler.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0 and library.is_file(), 'The native IME observer did not compile; inspect compiler.log'
    return library


class CompositionObserver:
    def __init__(self, api, root, child, focus, pid, folder, profile):
        assert ctypes.sizeof(ctypes.c_void_p) == 8, 'The observer controller must be native x64'
        self.api, self.root, self.child, self.focus, self.pid = api, root, child, focus, pid
        self.tid = int(api.user.GetWindowThreadProcessId(focus, None))
        assert self.tid and api.pid(focus) == pid, 'Observer target is not the owned editor input thread'
        self.mapping_name = 'Local\\OpenGeulIme_' + uuid.uuid4().hex
        self.mapping = mmap.mmap(-1, ctypes.sizeof(NativeState), tagname=self.mapping_name)
        state = NativeState()
        state.magic, state.version, state.pid, state.tid = 0x4f47494d, 1, pid, self.tid
        self.mapping[:] = bytes(state)
        library = compile_observer(folder, self.mapping_name, profile)
        self.dll = ctypes.WinDLL(str(library), use_last_error=True)
        self.dll.StateSize.restype = ctypes.c_uint32
        assert self.dll.StateSize() == ctypes.sizeof(NativeState), 'Native observer memory layout differs from controller'
        api.user.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, W.HINSTANCE, W.DWORD]
        api.user.SetWindowsHookExW.restype = W.HANDLE
        api.user.UnhookWindowsHookEx.argtypes = [W.HANDLE]
        api.user.UnhookWindowsHookEx.restype = W.BOOL
        api.user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t)]
        api.user.SendMessageTimeoutW.restype = W.LPARAM
        api.user.GetKeyboardLayout.argtypes = [W.DWORD]
        api.user.GetKeyboardLayout.restype = W.HANDLE
        self.hooks, self.commands, self.restored = [], [], False
        self.activation_attempted = False
        try:
            for kind, name in ((4, 'HookCall'), (3, 'HookGet')):
                address = ctypes.cast(getattr(self.dll, name), ctypes.c_void_p)
                handle = api.user.SetWindowsHookExW(kind, address, self.dll._handle, self.tid)
                if not handle: raise ctypes.WinError(ctypes.get_last_error())
                self.hooks.append(handle)
        except Exception:
            self.close()
            raise

    def state(self):
        return NativeState.from_buffer_copy(self.mapping[:])

    def require_target(self):
        assert self.api.require_editor_focus(self.root, self.child) == self.focus, 'IME input focus HWND changed'
        assert self.api.pid(self.focus) == self.pid and self.api.user.GetWindowThreadProcessId(self.focus, None) == self.tid, 'IME target process/thread identity changed'

    def command(self, command):
        self.require_target()
        if command == 1:
            self.activation_attempted = True
        self.mapping[NativeState.command.offset:NativeState.command.offset + 4] = command.to_bytes(4, 'little')
        result = ctypes.c_size_t()
        if not self.api.user.SendMessageTimeoutW(self.focus, 0x8351, command, 0, 2, 5000, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        state = wait_for(lambda: (value if (value := self.state()).ack == command else None), 5)
        self.commands.append({'command': command, 'status': state.status,
            'layout': int(self.api.user.GetKeyboardLayout(self.tid) or 0),
            'activeLanguage': state.activeLanguage, 'activeClsid': utf16(state.activeClsid),
            'activeProfile': utf16(state.activeProfile), 'previousLayout': state.previousLayout,
            'previousProfileType': state.previousProfileType, 'previousLanguage': state.previousLanguage,
            'previousClsid': utf16(state.previousClsid), 'previousProfile': utf16(state.previousProfile),
            'previousProfileLayout': state.previousProfileLayout, 'activeProfileType': state.activeProfileType,
            'activeProfileLayout': state.activeProfileLayout, 'profileManagerHresult': state.profileManagerHresult,
            'previousProfileHresult': state.previousProfileHresult, 'activateProfileHresult': state.activateProfileHresult,
            'activeProfileHresult': state.activeProfileHresult, 'activateLayoutError': state.activateLayoutError})
        assert state.status == 0, 'Owned native IME command failed: ' + str(self.commands[-1])
        if command == 4:
            wait_for(lambda: int(self.api.user.GetKeyboardLayout(self.tid) or 0) == state.previousLayout, 5)
            validate_restoration(self.commands[-1])
            self.restored = True
        return self.commands[-1]

    def events(self):
        state = self.state()
        assert not state.overflow, 'Native composition receipt buffer overflowed'
        events = []
        for index in range(min(max(state.count, 0), 512)):
            row = state.events[index]
            if row.sequence != index + 1: break
            assert 0 <= row.compositionBytes < 512 and 0 <= row.resultBytes < 512, 'Native composition string was unavailable or too large'
            events.append({'sequence': row.sequence, 'message': row.message, 'flags': row.flags,
                'pid': row.pid, 'tid': row.tid, 'hwnd': row.hwnd, 'layout': row.layout,
                'origin': 'sent' if row.origin == 1 else 'posted',
                'composition': utf16(row.composition), 'result': utf16(row.result)})
        return events

    def pending(self, expected, after):
        events = self.events()[after:]
        return any(row['message'] == 0x10f and row['composition'] == expected for row in events)

    def close(self):
        errors = []
        for hook in reversed(getattr(self, 'hooks', [])):
            if not self.api.user.UnhookWindowsHookEx(hook): errors.append(str(ctypes.get_last_error()))
        self.hooks = []
        if getattr(self, 'mapping', None) is not None:
            self.mapping.close()
            self.mapping = None
        assert not errors, 'Owned editor observer hook cleanup failed: ' + ','.join(errors)


class KeyboardInput(ctypes.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class InputPayload(ctypes.Union):
    _fields_ = [('keyboard', KeyboardInput), ('mouse', MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [('type', W.DWORD), ('payload', InputPayload)]


def physical_key(observer, token, record):
    observer.require_target()
    assert int(observer.api.user.GetKeyboardLayout(observer.tid) or 0) & 0xffff == 0x0412, 'Korean layout changed before physical key'
    rows = scan_events([token])
    payload = (Input * len(rows))()
    for item, row in zip(payload, rows):
        item.type = 1
        item.payload.keyboard = KeyboardInput(row['vk'], row['scan'], row['flags'], 0, 0)
    user = observer.api.user
    user.SendInput.argtypes = [W.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = W.UINT
    assert user.SendInput(len(payload), payload, ctypes.sizeof(Input)) == len(payload), 'Physical scan-code input was not fully delivered'
    record['keyTokens'].append(token)
    record.setdefault('scanCodeInputs', []).extend(rows)


def reopen_one(suite, source, module):
    from engine_smoke import Engine, observe
    engine, document = Engine(suite), None
    try:
        engine.start()
        document = engine.load(source.as_uri())
        observed = observe(module, document)
        verify_content(module, observed)
        assert marker(module) in observed['text'], 'Actual Office reopen lost Korean input'
        return observed
    finally:
        engine.close_document(document)
        engine.cleanup()
        assert not engine.cleanup_errors, 'UNO reopen cleanup failed: ' + str(engine.cleanup_errors)


def case(suite, fixtures, output, readiness, module, extension):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    name = 'ime-' + module
    folder = output / name
    folder.mkdir()
    original = require_engine_fixture(fixtures, module, extension)
    source = folder / original.name
    shutil.copyfile(original, source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    process = launch_suite([str(suite / 'OpenGeul.Office.exe'), '--module', module, '--file', str(source)], suite, output, name)
    record = {'module': module, 'kind': 'native-korean-ime', 'shellPid': process.pid,
              'file': str(source), 'success': False, 'imeVerified': False, 'stage': 'attach',
              'inputMethod': 'SendInput-scancode', 'unicodeInputUsed': False, 'keyTokens': [],
              'readiness': readiness}
    observer = None
    api = Windows()
    try:
        hwnd, parent, child, office_pid = verified_attachment(api, process, module)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid)
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        window.set_focus()
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd, 10)
        record['stage'] = 'focus-editor'
        Desktop(backend='win32').window(handle=child).wrapper_object().click_input()
        send_keys('^{F6}', pause=0.1)
        api.require_editor_focus(hwnd, child)
        if module == 'writer': send_keys('^{END}', pause=0.1)
        elif module == 'calc': send_keys('^{HOME}{F2}^{END}', pause=0.1)
        else: send_keys('{TAB}{F2}^{END}', pause=0.1)
        focus = api.require_editor_focus(hwnd, child)
        record['stage'] = 'install-owned-thread-observer'
        observer = CompositionObserver(api, hwnd, child, focus, office_pid, folder, readiness['profile'])
        record.update(editorTid=observer.tid, keyboardFocusHwnd=focus)
        active = activate_after_ascii_prefix(observer, module, record,
            lambda prefix: ascii_input.type_ascii(api, hwnd, child, prefix, record, pause=0.04))
        wait_for(lambda: int(api.user.GetKeyboardLayout(observer.tid) or 0) & 0xffff == 0x0412, 10)
        profile = readiness['profile']
        assert active['activeLanguage'] == 0x0412 and active['activeClsid'].lower() == profile['providerClsid'].lower() and active['activeProfile'].lower() == profile['profileGuid'].lower(), 'Focused editor TSF profile differs from the attested Microsoft IME'
        record['activeLayout'] = int(api.user.GetKeyboardLayout(observer.tid) or 0)
        record['activeProfile'] = active
        observer.command(2)  # Exercise the owned IME's alphanumeric-mode switch.
        observer.command(3)
        record['stage'] = 'physical-dubeolsik-composition'
        for token, expected in zip(EXPECTED_KEYS[:-1], ('ㅎ', '하', '한', 'ㄱ', '그', '글', '그', '글')):
            after = len(observer.events())
            physical_key(observer, token, record)
            wait_for(lambda: observer.pending(expected, after), 10)
        window.capture_as_image().save(output / (name + '-composing.png'))
        record['stage'] = 'commit-native-composition'
        physical_key(observer, 'RIGHT', record)
        wait_for(lambda: any(row['result'] == '글' for row in observer.events()), 10)
        record['events'] = observer.events()
        record['stage'] = 'restore-owned-input-thread'
        record['restoration'] = observer.command(4)
        record['layoutRestored'] = observer.restored
        record['imeCommands'] = observer.commands
        observer.close()
        observer = None
        api.require_editor_focus(hwnd, child)
        if module == 'calc': send_keys('{ENTER}', pause=0.1)
        record['stage'] = 'save-ctrl-s'
        send_keys('^s', pause=0.1)
        wait_for(lambda: marker(module) in package_text(source), 30)
        wait_for(lambda: not api.title(hwnd).startswith('* '), 10)
        record['savedText'] = package_text(source)
        window.capture_as_image().save(output / (name + '-saved.png'))
        assert not api.windows(office_pid), api.external_window_message(office_pid, 'IME opened an external Office document window')
        close_document(api, process, hwnd, child, record)
        close_home(api, process, record)
        record['stage'] = 'actual-uno-reopen'
        result_path = folder / 'reopened.json'
        command = [str(suite / 'Office/program/python.exe'), str(Path(__file__).resolve()),
            '--suite', str(suite), '--verify-one', module, '--file', str(source), '--reopen-output', str(result_path)]
        reopened = subprocess.run(command, capture_output=True, timeout=120)
        (folder / 'reopen.log').write_bytes(reopened.stdout + reopened.stderr)
        assert reopened.returncode == 0, 'Actual Office Korean-content reopen failed; inspect reopen.log'
        record['reopened'] = json.loads(result_path.read_text(encoding='utf-8'))
        record.update(validate_ime_evidence(record))
        record.update(success=True, cleanClose=True, stage='complete', beforeSha256=before,
            afterSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            originalFixtureUnchanged=hashlib.sha256(original.read_bytes()).hexdigest() == before)
        assert record['originalFixtureUnchanged'], 'IME test altered the engine baseline fixture'
        return record
    except Exception as exc:
        capture_failure(output, name, record, exc)
        raise
    finally:
        if observer is not None:
            try:
                record['events'] = observer.events()
                if observer.activation_attempted and api.user.IsWindow(observer.focus):
                    record['restoration'] = observer.command(4)
                    record['layoutRestored'] = observer.restored
            except Exception as exc:
                record.update(success=False, imeCleanupError=type(exc).__name__ + ': ' + str(exc))
            finally:
                record['imeCommands'] = observer.commands
                try: observer.close()
                except Exception as exc: record.update(success=False, hookCleanupError=str(exc))
        stop_owned_test_process(process, record)
        write_result(output, name, record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--readiness', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-one', choices=dict(INPUT_CASES))
    parser.add_argument('--file', type=Path)
    parser.add_argument('--reopen-output', type=Path)
    args = parser.parse_args(argv)
    if os.name != 'nt' or not __debug__: raise RuntimeError('Actual Windows x64 execution with assertions enabled is required')
    suite = args.suite.resolve()
    if args.verify_one:
        assert args.file and args.reopen_output, 'The owned reopen fixture and receipt are required'
        observed = reopen_one(suite, args.file.resolve(), args.verify_one)
        with args.reopen_output.open('x', encoding='utf-8') as stream: json.dump(observed, stream, ensure_ascii=False, indent=2)
        return 0
    assert args.fixtures and args.readiness and args.output, 'Generated fixtures, readiness and fresh output are required'
    for path in (args.suite, args.fixtures, args.readiness, args.output):
        assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Linked test paths are not accepted'
    fixtures, output = args.fixtures.resolve(), args.output.resolve()
    assert suite != output and suite not in output.parents and fixtures != output and fixtures not in output.parents, 'Evidence must be outside the payload and baseline fixtures'
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output)), 'Only local test paths are accepted'
    output.mkdir(parents=True, exist_ok=False)
    readiness = require_readiness(json.loads(args.readiness.read_text(encoding='utf-8-sig')))
    results = collect_cases([('ime-' + module, lambda module=module, extension=extension:
        case(suite, fixtures, output, readiness, module, extension)) for module, extension in INPUT_CASES], output)
    success = len(results) == 3 and all(row.get('success') is True and row.get('imeVerified') is True for row in results)
    report = {'schemaVersion': 1, 'kind': 'native-korean-ime', 'success': success,
              'imeVerified': success, 'suiteOnly': True, 'tests': results,
              'expectedCaseCount': 3, 'passedCaseCount': sum(row.get('success') is True for row in results)}
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if success else 1


if __name__ == '__main__': raise SystemExit(main())
