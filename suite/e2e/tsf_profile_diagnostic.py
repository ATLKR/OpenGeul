"""Disposable owned-thread TSF profile observation; never native IME acceptance.

No text/IME input or compartment writes. Typed differences after restoring the
original profile are observations, not a claim of literal mode restoration.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import math
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import korean_ime_smoke as ime
from korean_ime_smoke import (NativeState, remaining_setup, utf16,
                             native_arch, native_mode, wait_for)
from counted_editor_shortcuts import NativeShortcutProbe, join_shortcut_generation, admit_shortcut_generation
import windows_smoke as native

MAGIC, VERSION = 0x4f475044, 1
MAX_JSON = 256 * 1024

ORIGINAL_PINS = {'korean_ime_smoke.py': 'd7d6556f99c114c77bca0cb766e583023a50d6adb05651fe08ec3e02b30a0101', 'ime_thread_mode.h': '5eabe3ee178426cc4472f48a19ab3e3cbac40cc0a2a777c4bb48a468fb41ffa7', 'ime_thread_mode_windows.h': '9570ed35c1ba624f356ceea9af95ff2678882c478ee7a0271d01ace06b437d7f', 'ime_command_admission.h': 'aac2ed443ac212c994721fa83dbf09bd1cfbfc14eca2bae0c5a7676d95e45ce8'}

DIAGNOSTIC_COMMAND = r'''
static void command(HWND hwnd, UINT sequence) {
    const auto publishedSequence=InterlockedCompareExchange((volatile LONG*)&shared->command,0,0);
    if (sequence<1 || sequence>4 || sequence!=UINT(publishedSequence) || shared->ack==sequence) return;
    MemoryBarrier();
    const auto published=shared->commandBudgets[sequence-1];
    opengeul_ime::CommandLease lease(commandAdmission,shared->commandRejection,sequence,published);
    shared->nativeAttemptedMask=commandAdmission.attemptedMask;
    if (!lease.Entered()) return; // Never overwrite active status/receipt/ACK on rejection.
    const auto limits=lease.budget;
    shared->status=0; shared->threadMode=opengeul_ime::ModeReceipt{};
    if (sequence==3) failure(-44); // No diagnostic command can request a mode write.
    ITfInputProcessorProfileMgr* mgr=budget(limits) && !shared->status ? profiles() : nullptr;
    GUID category; CLSIDFromString(L"{34745C63-B2F0-4784-8B67-5E12C8701A31}",&category);
    if (!original_target(hwnd,sequence!=4)) failure(-43);
    if (!budget(limits)) failure(-20);
    if (sequence==1 && !shared->status) {
        shared->previousLayout=uint64_t(UINT_PTR(GetKeyboardLayout(0)));
        shared->previousProfileHresult=mgr ? mgr->GetActiveProfile(category,&oldProfile) : E_UNEXPECTED;
        haveOldProfile=(shared->previousProfileHresult==S_OK);
        if (haveOldProfile) {
            shared->previousProfileType=oldProfile.dwProfileType;shared->previousLanguage=oldProfile.langid;
            shared->previousProfileLayout=uint64_t(UINT_PTR(oldProfile.hkl));
            StringFromGUID2(oldProfile.clsid,shared->previousClsid,40);
            StringFromGUID2(oldProfile.guidProfile,shared->previousProfile,40);
        } else failure(-8);
        // Admit exactly the original US keyboard profile observed in the failing case.
        // Never repair a different initial state or switch it to US.
        if (haveOldProfile && !opengeul_ime::OriginalUsProfile(shared->previousLayout,
                oldProfile.dwProfileType,oldProfile.langid,uint64_t(UINT_PTR(oldProfile.hkl)),
                IsEqualGUID(oldProfile.clsid,GUID_NULL),IsEqualGUID(oldProfile.guidProfile,GUID_NULL))) failure(-45);
        if (!budget(limits)) failure(-20);
        if (!shared->status && !observe_imm(hwnd)) failure(-3);
        shared->previousOpen=shared->immOpen;shared->previousConversion=shared->immConversion;
        shared->previousSentence=shared->immSentence;
        if (!shared->status) {
            opengeul_ime::WindowsThreadMode api(shared->threadMode,limits.counter,limits.frequency);
            opengeul_ime::CaptureTypedBoth(api,shared->threadMode);
            if (shared->threadMode.status) failure(shared->threadMode.status);
            else {
                shared->tsfCaptured=1; initialized=true;
            }
        }
        if (!budget(limits)) failure(-20);
        if (!shared->status) {
            shared->profileChangeAttempted=1;
            SetLastError(0); HKL korean=LoadKeyboardLayoutW(L"00000412",0);
            if (!korean || (UINT_PTR(korean)&0xffff)!=0x0412) {shared->activateLayoutError=GetLastError();failure(-1);}
            else if (!budget(limits)) failure(-20);
            else if (!ActivateKeyboardLayout(korean,0)) {shared->activateLayoutError=GetLastError();failure(-1);}
            if (!budget(limits)) failure(-20);
            if (!shared->status) {
                GUID clsid,profile; CLSIDFromString(L"__CLSID__",&clsid);CLSIDFromString(L"__PROFILE__",&profile);
                if (!budget(limits)) failure(-20);
                shared->activateProfileHresult=!shared->status ? mgr->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR,0x0412,clsid,profile,nullptr,0) : E_UNEXPECTED;
                if (shared->activateProfileHresult!=S_OK) failure(-2);
            }
        }
    } else if (sequence==2 && !shared->status) {
        if (!initialized || !shared->tsfCaptured) failure(-39);
        else if (!korean_profile(mgr,category)) failure(-40);
        if (!budget(limits)) failure(-20);
        if (!shared->status) {
            opengeul_ime::WindowsThreadMode api(shared->threadMode,limits.counter,limits.frequency);
            opengeul_ime::CaptureTypedBoth(api,shared->threadMode);
            if (shared->threadMode.status) failure(shared->threadMode.status);
            if (!budget(limits)) failure(-20);
            if (!shared->status && !observe_imm(hwnd)) failure(-3);
        }
    } else if (sequence==4 && !shared->status) {
        if (!initialized || !haveOldProfile || !shared->tsfCaptured || !shared->profileChangeAttempted) failure(-42);
        if (!shared->status) {
            SetLastError(0);
            if (!ActivateKeyboardLayout(HKL(UINT_PTR(shared->previousLayout)),0)) {shared->activateLayoutError=GetLastError();failure(-7);}
            if (!budget(limits)) failure(-20);
            if (!shared->status) {
                shared->activateProfileHresult=mgr ? mgr->ActivateProfile(oldProfile.dwProfileType,oldProfile.langid,
                    oldProfile.clsid,oldProfile.guidProfile,
                    oldProfile.dwProfileType==TF_PROFILETYPE_INPUTPROCESSOR ? nullptr : oldProfile.hkl,0) : E_UNEXPECTED;
                if (shared->activateProfileHresult!=S_OK) failure(-6);
            }
            TF_INPUTPROCESSORPROFILE restored={};
            if (!budget(limits)) failure(-20);
            if (budget(limits) && (!mgr || mgr->GetActiveProfile(category,&restored)!=S_OK
                    || !same_profile(restored,oldProfile))) failure(-40);
            if (!budget(limits)) failure(-20);
            else if (uint64_t(UINT_PTR(GetKeyboardLayout(0)))!=shared->previousLayout) failure(-7);
            // Retain typed/raw post-restore facts even when the profile check failed.
            // No empty or concrete original value is written back by this diagnostic.
            if (budget(limits) && original_target(hwnd,false)) {
                opengeul_ime::WindowsThreadMode api(shared->threadMode,limits.counter,limits.frequency);
                opengeul_ime::CaptureTypedBoth(api,shared->threadMode);
                if (shared->threadMode.status) failure(shared->threadMode.status);
                if (budget(limits) && !observe_imm(hwnd)) failure(-3);
            }
        }
    } else if (sequence<1 || sequence>4) failure(-44);
    if (sequence==1 && !shared->status) {
        if (!budget(limits)) failure(-20);
        else if (!korean_profile(mgr,category)) failure(-40);
    }
    if (!original_target(hwnd,sequence!=4)) failure(-43);
    TF_INPUTPROCESSORPROFILE current={};
    shared->activeLanguage=0;shared->activeProfileType=0;shared->activeProfileLayout=0;
    shared->activeClsid[0]=0;shared->activeProfile[0]=0;
    shared->activeProfileHresult=mgr && budget(limits) ? mgr->GetActiveProfile(category,&current) : E_UNEXPECTED;
    if (mgr) {
        if (shared->activeProfileHresult==S_OK) {
            shared->activeLanguage=current.langid;shared->activeProfileType=current.dwProfileType;
            shared->activeProfileLayout=uint64_t(UINT_PTR(current.hkl));
            StringFromGUID2(current.clsid,shared->activeClsid,40);StringFromGUID2(current.guidProfile,shared->activeProfile,40);
        }
        mgr->Release();
    }
    if (!budget(limits)) failure(-20);
    // Per-command TSF references and the in-thread command lease are closed before ACK.
    lease.Finish();
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&shared->ack,sequence);
}
'''


def render_source(mapping, profile):
    for name, digest in ORIGINAL_PINS.items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == digest, 'Unknown diagnostic substrate: ' + name
    source = ime.OBSERVER_SOURCE
    begin, end = 'static void command(HWND hwnd, UINT sequence) {', 'static void observe(HWND hwnd,UINT message'
    assert source.count(begin) == source.count(end) == 1
    first, tail = source.split(begin)
    old, last = tail.split(end)
    source = first + DIAGNOSTIC_COMMAND + end + last
    assert source.count('#include "ime_thread_mode_windows.h"') == 1
    source = source.replace('#include "ime_thread_mode_windows.h"', '#include "ime_thread_mode_windows.h"\n#include "tsf_profile_diagnostic.h"')
    for old, new, count in (('0x4f47494d', '0x4f475044', 3), ('shared->version==3', 'shared->version==1', 1),
                            ('target->version!=3', 'target->version!=1', 1), ('source->version!=3', 'source->version!=1', 1)):
        assert source.count(old) == count, 'Unknown diagnostic protocol preimage'
        source = source.replace(old, new)
    for token, value in (('__MAPPING__', mapping.replace('\\', '\\\\')), ('__CLSID__', profile['providerClsid']), ('__PROFILE__', profile['profileGuid'])):
        assert token in source and '"' not in value and '\n' not in value
        source = source.replace(token, value)
    assert 'SetThreadMode(' not in source and 'CaptureThreadMode(' not in source
    return source


def typed_values(receipt):
    assert set(receipt) == {name for name, _ in native_mode.NativeModeReceipt._fields_}
    for name, kind in native_mode.NativeModeReceipt._fields_:
        value = receipt[name]
        lower, upper = (-2**31, 2**31) if kind is ctypes.c_int32 else (0, 2**32)
        assert type(value) is int and lower <= value < upper, 'Invalid native typed field: ' + name
    for name in ('status', 'cleanupStatus', 'managerHr', 'compartmentManagerHr', 'enumerationHr', 'enumerationNextHr', 'openGetHr', 'conversionGetHr', 'variantClearHr'):
        assert receipt[name] == 0, 'Typed diagnostic operation/cleanup failed: ' + name
    assert receipt['installedMask'] == 3 and 2 <= receipt['enumerationCount'] <= 64 and receipt['nextFetched'] == 1
    assert all(receipt[name] == 1 for name in ('managerPresent', 'compartmentManagerPresent', 'enumeratorPresent', 'openPresent', 'conversionPresent', 'modulePresent', 'lookupPresent', 'managerCallAttempts', 'releaseCalls'))
    assert receipt['referencesAcquired'] == receipt['referencesReleased'] == 5
    assert all(receipt[name] == 0 for name in ('openSetCalls', 'conversionSetCalls', 'clientIdCalls', 'clientId', 'clientPresent'))
    assert all(receipt[name] == native_mode.NOT_ATTEMPTED for name in ('clientQueryHr', 'clientHr', 'openSetHr', 'conversionSetHr', 'afterOpenHr', 'afterConversionHr'))
    result = {}
    for key in ('Open', 'Conversion'):
        hr, kind = receipt['before'+key+'Hr'], receipt['before'+key+'Type']
        assert (hr, kind) in ((0, 3), (1, 0)), 'Unsupported typed TSF result'
        row = dict(hresult=hr, variantType=kind, kind='i4' if kind == 3 else 'empty')
        if kind == 3: row['value'] = receipt['before'+key]
        result[key.lower()] = row
    return result


def require_command_guard(row, command, root, child, pid, tid, focus):
    assert isinstance(row, dict) and row.get('sourceCall') == 'EngineLease.guard'
    assert type(row.get('command')) is int and row['command'] == command and row.get('after') is False, 'Diagnostic command did not receive its fresh before-guard row'
    assert type(row.get('observationIndex')) is int and 0 <= row['observationIndex'] < 12
    assert type(row['shell']['pid']) is int and row['shell']['pid'] > 0 and row['engine']['pid'] == pid
    assert native._editor_focus_snapshot_ready(row['scope'], root, child, row['shell']['pid'], pid, tid) == focus
    assert row['scope']['focus']['pid'] == pid and row['scope']['focus']['threadId'] == tid and focus > 0
    return row


def require_profile_api_results(row):
    for key in ('profileManagerHresult', 'previousProfileHresult', 'activateProfileHresult', 'activeProfileHresult', 'activateLayoutError'):
        assert type(row.get(key)) is int and row[key] == 0, 'Diagnostic profile API failed: ' + key


def require_original_profile_return(row):
    require_profile_api_results(row)
    assert type(row.get('command')) is int and row['command'] == 4 and row.get('status') == 0
    for key, expected in (('previousLayout', 0x04090409), ('layout', 0x04090409),
            ('previousProfileType', 2), ('activeProfileType', 2), ('previousLanguage', 0x0409),
            ('activeLanguage', 0x0409), ('previousProfileLayout', 0x04090409), ('activeProfileLayout', 0x04090409)):
        assert type(row.get(key)) is int and row[key] == expected, 'Original diagnostic profile/HKL did not return: ' + key
    for key in ('previousClsid', 'previousProfile', 'activeClsid', 'activeProfile'):
        assert row.get(key, '').lower() == '{00000000-0000-0000-0000-000000000000}', 'Original diagnostic GUID did not return'
    return row


def compile_diagnostic(folder, mapping, profile, *, architecture='arm64', setup_deadline=None):
    # Reuse only the unchanged private-Job runner; never an ASCII DLL descriptor.
    import ascii_message_preparation as prep
    from native_compiler_tools import pin_native_tool
    native_arch.require_architecture(architecture)
    assert architecture == 'arm64', 'This finite diagnostic supports native ARM64 only'
    remaining_setup(setup_deadline, 60)
    budget = prep._Budget()
    if setup_deadline is not None:
        budget.deadline = min(budget.deadline, setup_deadline)
        budget.work_deadline = min(budget.work_deadline, setup_deadline-3)
    folder = prep._absolute(folder)
    source, library = folder/'ime-observer.cpp', folder/'ime-observer.dll'
    receipt = dict(schemaVersion=1, kind='tsf-profile-diagnostic-compilation', architecture=architecture,
        startedAt=budget.started, deadline=budget.deadline, workDeadline=budget.work_deadline,
        stages=[], sourcePins={}, compiler=dict(mode='clang-lld', before={}, after={}),
        compilerStatFacts=dict(before={}, after={}), success=False)
    try:
        budget.now()
        receipt['nativeArchitecture'] = native_arch.validate_native_architecture(native_arch.observe_native_architecture(), architecture)
        runtime = prep._Runtime()
        for name in ('ime_thread_mode.h', 'ime_thread_mode_windows.h', 'ime_command_admission.h', 'tsf_profile_diagnostic.h'):
            original = Path(__file__).with_name(name)
            receipt['sourcePins'][name] = prep._pin(original)
            (folder/name).write_bytes(original.read_bytes())
            assert prep._pin(folder/name) == receipt['sourcePins'][name]
            budget.now()
        source.write_text(render_source(mapping, profile), encoding='utf-8')
        receipt['renderedSource'] = prep._pin(source)
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
        assert vswhere.is_file()
        discovery = folder/'discover.cmd'
        discovery.write_text('@echo off\n"%~1" -utf8 -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.ARM64 -property installationPath >"%~2" 2>"%~3"\nexit /b %errorlevel%\n', encoding='ascii')
        prep._run_stage(runtime, folder, 'discovery', discovery, budget, receipt,
            [vswhere, folder/'discovery.stdout', folder/'discovery.stderr'])
        raw = (folder/'discovery.stdout').read_bytes()
        assert 0 < len(raw) <= 32768
        found = raw.decode('utf-8-sig').strip()
        assert '\n' not in found and '\r' not in found
        vcvars = Path(found)/'VC/Auxiliary/Build/vcvarsall.bat'
        assert vcvars.is_file()
        llvm = prep._absolute(Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'LLVM/bin')
        tools = [llvm/name for name in ('clang-cl.exe', 'lld-link.exe')]
        def pin_tools(phase):
            for tool in tools:
                facts = {}
                receipt['compilerStatFacts'][phase][tool.name] = facts
                receipt['compiler'][phase][tool.name] = pin_native_tool(tool, architecture, check=budget.now, facts=facts)
        pin_tools('before')
        script = folder/'compile.cmd'
        script.write_text('@echo off\nset "VSCMD_SKIP_SENDTELEMETRY=1"\ncall "%~1" arm64 >"%~2" 2>&1\nif errorlevel 1 exit /b 1\n'
            + '"%~7" --target=aarch64-pc-windows-msvc /nologo /c /O2 /MT /EHsc /std:c++17 /utf-8 "%~3" /Foime_observer.obj >"%~5" 2>"%~6"\nif errorlevel 1 exit /b 1\n'
            + '"%~8" /NOLOGO /DLL /MACHINE:ARM64 /OUT:"%~4" /IMPLIB:ime_observer.lib ime_observer.obj user32.lib kernel32.lib imm32.lib ole32.lib oleaut32.lib uuid.lib >>"%~5" 2>>"%~6"\nexit /b %errorlevel%\n', encoding='ascii')
        prep._run_stage(runtime, folder, 'compile', script, budget, receipt,
            [vcvars, folder/'environment.log', source, library, folder/'compiler.stdout', folder/'compiler.stderr', *tools])
        pin_tools('after')
        assert receipt['compiler']['before'] == receipt['compiler']['after'], 'Diagnostic compiler tools changed'
        native_arch.require_native_pe(library, architecture)
        receipt['library'] = dict(path=str(library), **prep._pin(library))
        assert prep._pin(source) == receipt['renderedSource']
        for name, pin in receipt['sourcePins'].items():
            assert prep._pin(Path(__file__).with_name(name)) == prep._pin(folder/name) == pin
        receipt.update(success=True, finishedAt=budget.now())
    except BaseException as exc:
        receipt['error'] = _error(exc)
        raise
    finally:
        primary = __import__('sys').exc_info()[1]
        try: prep._write_json(folder/'compilation.json', receipt)
        except BaseException as exc:
            if primary is None: raise
            primary.diagnosticCompilationReceiptError = _error(exc)
    budget.now(cleanup=True)
    return library


class ProfileObserver(ime.CompositionObserver):
    def __init__(self, api, root, child, focus, pid, folder, profile, *, architecture='x64', setup_deadline=None):
        remaining_setup(setup_deadline, 60)
        self.native_architecture = native_arch.validate_native_architecture(
            native_arch.observe_native_architecture(), architecture)
        self.target_architecture = native_arch.observe_owned_process(pid, architecture)
        self.api, self.root, self.child, self.focus, self.pid = api, root, child, focus, pid
        self.expected_profile = dict(profile)
        self.tid = int(api.user.GetWindowThreadProcessId(focus, None))
        assert self.tid and api.pid(focus) == pid, 'Observer target is not the owned editor input thread'
        self.mapping_name = 'Local\\OpenGeulTsfDiagnostic_' + uuid.uuid4().hex
        self.mapping = mmap.mmap(-1, ctypes.sizeof(NativeState), tagname=self.mapping_name)
        state = NativeState()
        state.magic, state.version, state.pid, state.tid = MAGIC, VERSION, pid, self.tid
        state.targetHwnd, state.rootHwnd = focus, root
        self.mapping[:] = bytes(state)
        try:
            library = compile_diagnostic(folder, self.mapping_name, profile,
                architecture=architecture, setup_deadline=setup_deadline)
            native_arch.require_native_pe(library, architecture)
            self.dll = ctypes.WinDLL(str(library), use_last_error=True)
            self.dll.StateSize.restype = ctypes.c_uint32
            assert self.dll.StateSize() == ctypes.sizeof(NativeState), 'Native observer memory layout differs from controller'
            self.dll.PublishCommand.argtypes = [ctypes.POINTER(NativeState), ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64]
            self.dll.PublishCommand.restype = ctypes.c_uint32
            self.dll.ReadSnapshot.argtypes = [ctypes.POINTER(NativeState), ctypes.POINTER(NativeState),
                ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
            self.dll.ReadSnapshot.restype = ctypes.c_uint32
            api.user.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, W.HINSTANCE, W.DWORD]
            api.user.SetWindowsHookExW.restype = W.HANDLE
            api.user.UnhookWindowsHookEx.argtypes = [W.HANDLE]
            api.user.UnhookWindowsHookEx.restype = W.BOOL
            api.user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t)]
            api.user.SendMessageTimeoutW.restype = W.LPARAM
            api.user.GetKeyboardLayout.argtypes = [W.DWORD]
            api.user.GetKeyboardLayout.restype = W.HANDLE
            self.hooks, self.commands, self.restored = [], [], False
            self.command_attempts = set()
            self.activation_attempted = False
            self.profile_restored = False
            self.generation_guard = lambda command, after: (_ for _ in ()).throw(AssertionError("Diagnostic retained generation guard is unbound"))
            for kind, name in ((4, 'HookCall'), (3, 'HookGet')):
                remaining_setup(setup_deadline, 60)
                address = ctypes.cast(getattr(self.dll, name), ctypes.c_void_p)
                handle = api.user.SetWindowsHookExW(kind, address, self.dll._handle, self.tid)
                if not handle: raise ctypes.WinError(ctypes.get_last_error())
                self.hooks.append(handle)
            remaining_setup(setup_deadline, 60)
        except BaseException as exc:
            try: self.close()
            except BaseException as later: exc.diagnosticHookCleanupError = _error(later)
            raise

    def _command_snapshot(self, state, command):
        row = super()._command_snapshot(state, command)
        row['originalCaptureComplete'] = state.tsfCaptured == 1
        row['previousImmState'] = dict(open=int(state.previousOpen), conversion=int(state.previousConversion), sentence=int(state.previousSentence))
        return row

    def command(self, command, *, setup_deadline=None):
        assert type(command) is int and command in (1, 2, 4)
        assert command not in self.command_attempts, 'Original native IME command cannot retry or renew its budget'
        self.command_attempts.add(command)
        row = dict(command=command, acknowledged=False, success=False, nativeCallAttempts=0)
        self.commands.append(row)  # Failure/rejection evidence survives a missing ACK.
        try:
            guard_before = self.generation_guard(command, False)
            row['guardBefore'] = guard_before
            if command == 4: self.require_restore_target()
            else: require_command_guard(guard_before, command, self.root, self.child, self.pid, self.tid, self.focus)
            bounded_deadline = time.monotonic() + remaining_setup(setup_deadline, 5)
            counter, frequency = native_mode.counter_budget(bounded_deadline, clock=time.monotonic)
            slot = native_mode.NativeCommandBudget(counter, frequency)
            offset = NativeState.commandBudgets.offset + (command - 1) * ctypes.sizeof(slot)
            assert not any(self.mapping[offset:offset + ctypes.sizeof(slot)]), 'Native IME command budget was already published'
            row.update(deadline=bounded_deadline, requestedBudget=dict(counter=counter, frequency=frequency))
            view = NativeState.from_buffer(self.mapping)
            try: published = self.dll.PublishCommand(ctypes.byref(view), command, counter, frequency)
            finally: del view
            row['nativePublicationReturn'] = published if type(published) is int else repr(published)
            assert type(published) is int and published == 1, 'Native IME command publication failed'
            if command == 1: self.activation_attempted = True
            result = ctypes.c_size_t()
            milliseconds = int(remaining_setup(bounded_deadline, 5) * 1000)
            assert milliseconds > 0, 'Shared IME setup has no native command budget'
            row['nativeCallAttempts'] = 1
            if not self.api.user.SendMessageTimeoutW(self.focus, 0x8351, command, 0, 2, milliseconds, ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            state = wait_for(lambda: (value if (value := self.state()).snapshotEvidence['stable']
                and value.ack == command and value.snapshotEvidence['ackBefore'] == command
                and value.snapshotEvidence['ackAfter'] == command else None),
                remaining_setup(bounded_deadline, 5))
            row.update(self._command_snapshot(state, command), acknowledged=True)
            assert state.status == 0, 'Owned native IME command failed: ' + str(row)
            assert not row['commandRejection']['count'], 'Conflicting native IME command was rejected; subsequent input is blocked'
            assert (row['modeDeadlineCounter'], row['modeCounterFrequency']) == (counter, frequency), 'Native IME command used a different published budget'
            assert state.tsfCaptured == 1, 'Original TSF mode state was not captured before profile activation'
            row['typedValues'] = typed_values(row['threadMode'])
            assert state.immContextPresent == state.immConversionSucceeded == 1, 'Diagnostic HIMC getters failed'
            require_profile_api_results(row)
            if command in (1, 2):
                assert (state.activeProfileType == 1 and state.activeLanguage == 0x0412
                    and utf16(state.activeClsid).lower() == self.expected_profile['providerClsid'].lower()
                    and utf16(state.activeProfile).lower() == self.expected_profile['profileGuid'].lower()
                    and row['layout'] & 0xffff == 0x0412), 'Diagnostic phase differs from the attested Korean profile'
            else:
                require_original_profile_return(row)
                self.profile_restored = True
            self.generation_guard(command, True)
            remaining_setup(bounded_deadline, 5)
            row['success'] = True
            return row
        except BaseException as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            try: row['nativeStateAtFailure'] = self._command_snapshot(self.state(), command)
            except BaseException as later: row['failureSnapshotError'] = type(later).__name__ + ': ' + str(later)
            raise


def _error(exc):
    return type(exc).__name__ + ': ' + str(exc)[:2048]


def write_original(path, value):
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    assert 0 < len(raw) <= MAX_JSON, 'Diagnostic receipt exceeds its finite bound'
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def retain_result(path, record, primary):
    try: write_original(path, record)
    except BaseException as exc:
        if primary is None: raise
        primary.diagnosticResultReceiptError = _error(exc)
        primary.add_note('Secondary diagnostic result retention failure: ' + _error(exc))


def retained_exit(probe, original, handle):
    kernel = probe.kernel
    H, D, B = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    signatures = (('WaitForSingleObject', (H, D), D), ('GetProcessId', (H,), D),
        ('GetProcessTimes', (H, ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME), ctypes.POINTER(W.FILETIME)), B),
        ('GetExitCodeProcess', (H, ctypes.POINTER(D)), B))
    for name, args, result in signatures:
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    def call(function, *args):
        assert time.monotonic() < probe.deadline, 'Diagnostic retirement observation deadline expired'
        value = function(*args)
        assert time.monotonic() < probe.deadline, 'Diagnostic retirement observation exceeded deadline'
        return value
    row = dict(handleValue=handle, image=original['image'], imageSource='retained-live-admission')
    row['waitResult'] = int(call(kernel.WaitForSingleObject, handle, 0))
    row['pid'] = int(call(kernel.GetProcessId, handle))
    times = [W.FILETIME() for _ in range(4)]
    row['getProcessTimesResult'] = bool(call(kernel.GetProcessTimes, handle, *(ctypes.byref(value) for value in times)))
    row['processTimes'] = {name: dict(low=int(value.dwLowDateTime), high=int(value.dwHighDateTime),
        fileTime=(int(value.dwHighDateTime)<<32)|int(value.dwLowDateTime)) for name, value in zip(('creation', 'exit', 'kernel', 'user'), times)}
    code = D()
    row['getExitCodeProcessResult'] = bool(call(kernel.GetExitCodeProcess, handle, ctypes.byref(code)))
    row['exitCode'] = int(code.value)
    assert row['waitResult'] == 0 and row['pid'] == original['pid'] and handle == original['handleValue']
    assert row['getProcessTimesResult'] and row['processTimes']['creation']['fileTime'] == original['creationTime']
    assert row['getExitCodeProcessResult'] and row['exitCode'] == 0, 'Original diagnostic engine did not exit naturally zero'
    return row


def prepare_diagnostic_editor_focus(api, process, root, parent, child, office_pid, record, setup_deadline):
    """One measured click and passive focus query, without Ctrl+F6 readiness."""
    assert 'editorFocusReadiness' not in record, 'Diagnostic editor entry cannot be repeated'
    started = time.monotonic()
    assert type(setup_deadline) in (int, float) and math.isfinite(setup_deadline)
    seconds = min(5, setup_deadline-started)
    assert seconds > 0, 'Diagnostic editor entry deadline expired'
    deadline = started + seconds
    assert deadline <= setup_deadline
    pending = record['editorFocusReadiness'] = dict(schemaVersion=1, kind='owned-editor-focus-readiness',
        ready=False, suiteHwnd=root, childHwnd=child, shellPid=process.pid, officePid=office_pid,
        startedAt=started, deadline=deadline, deadlineSeconds=seconds, deadlineScope='editor-setup-and-focus',
        snapshots=[], clickAttempts=0, clickCompleted=False, controlF6Attempts=0, controlF6Completed=False)
    record.setdefault('editorFocusReadinessRecords', []).append(pending)
    assert time.monotonic() < deadline, 'Diagnostic editor entry deadline expired'
    pending['clickAttempts'] = 1  # Callback intent; the shared click records actual native attempts.
    native.click_owned_editor(api, process, root, parent, child, office_pid, record)
    pending['clickCompleted'] = True
    assert time.monotonic() < deadline, 'Diagnostic editor click exceeded the original entry deadline'
    return wait_click_focus(api, root, child, process.pid, office_pid, record, setup_deadline)


def wait_click_focus(api, root, child, shell_pid, office_pid, record, setup_deadline):
    # A diagnostic-only passive query after the one counted click; no Ctrl+F6 claim.
    pending = record['editorFocusReadiness']
    assert pending['schemaVersion'] == 1 and pending['kind'] == 'owned-editor-focus-readiness'
    assert (pending['suiteHwnd'], pending['childHwnd'], pending['shellPid'], pending['officePid']) == (root, child, shell_pid, office_pid)
    assert pending['ready'] is False and pending['clickAttempts'] == 1 and pending['clickCompleted'] is True
    assert pending['controlF6Attempts'] == 0 and pending['controlF6Completed'] is False
    started, deadline, seconds = (pending[key] for key in ('startedAt', 'deadline', 'deadlineSeconds'))
    assert all(type(value) in (int, float) and math.isfinite(value) for value in (started, deadline, seconds))
    assert pending['deadlineScope'] == 'editor-setup-and-focus' and 0 < seconds <= 5
    assert deadline == started+seconds and deadline <= setup_deadline
    assert started <= time.monotonic() < deadline, 'Diagnostic passive focus entry deadline expired'
    rows = []
    evidence = record['diagnosticFocusReadiness'] = dict(kind='diagnostic-click-only-focus',
        startedAt=started, deadline=deadline, snapshots=rows, ready=False, keyboardInputs=0)
    tid = None
    while time.monotonic() < deadline:
        assert len(rows) < 102, 'Diagnostic focus observations exceed bound'
        row = api.editor_focus_snapshot(root, child, shell_pid, office_pid)
        row['observedAt'] = time.monotonic()
        rows.append(row)
        assert row['observedAt'] < deadline, 'Diagnostic focus query exceeded original deadline'
        if tid is None: tid = row['before']['editor']['threadId']
        focus = native._editor_focus_snapshot_ready(row, root, child, shell_pid, office_pid, tid)
        if focus:
            assert type(focus) is int and focus > 0
            assert native._editor_focus_snapshot_ready(row, root, child, shell_pid, office_pid, tid) == focus
            finished = time.monotonic()
            assert started <= finished < deadline, 'Diagnostic passive focus exceeded the original entry deadline'
            evidence.update(ready=True, focusHwnd=focus, editorThreadId=tid, finishedAt=finished)
            return focus
        time.sleep(min(.05, max(0, deadline-time.monotonic())))
    raise AssertionError('Diagnostic click did not establish exact owned child focus')


class EngineLease:
    """One retained engine HANDLE, admitted before the probe and closed after retirement."""
    def __init__(self, api, process, suite, root, parent, child, pid, deadline):
        self.api, self.process, self.deadline = api, process, deadline
        self.probe = NativeShortcutProbe(deadline, time.monotonic)
        self.handle = None
        self.rows = []
        self.record = dict(kind='diagnostic-retained-engine-lease', handleClosed=False, observations=self.rows)
        self.binding = dict(shellPid=process.pid, officePid=pid, suiteHwnd=root, parentHwnd=parent, childHwnd=child, rootHwnd=root)
        try:
            self.shell = self.probe.process_snapshot(process)
            assert (self.shell['pid'], self.shell['handleValue'], self.shell['waitResult']) == (process.pid, int(process._handle), 258)
            assert Path(self.shell['image']).resolve() == (suite/'OpenGeul.Office.exe').resolve()
            assert process.opengeul_activation_binding == (process.pid, int(process._handle), self.shell['image'], self.shell['creationTime'], 258)
            self.handle = self.probe.open_engine(pid)  # Retain immediately before any later budget guard.
            self.record['handleValue'] = self.handle
            self.engine = self.probe.engine_snapshot(self.handle)
            assert (self.engine['pid'], self.engine['handleValue'], self.engine['waitResult']) == (pid, self.handle, 258)
            assert Path(self.engine['image']).resolve() == (suite/'Office/program/soffice.bin').resolve()
            assert self.engine['creationTime'] >= self.shell['creationTime'] > 0
            self.admission = admit_shortcut_generation(process, parent, child, self.engine, time.monotonic())
            self.record.update(originalShell=self.shell, originalEngine=self.engine, sharedGeneration=self.admission)
            self.tid = api.user.GetWindowThreadProcessId(child, None)
            self.record['initialThreadId'] = self.tid
            assert type(self.tid) is int and 0 < self.tid <= 0xffffffff, 'Diagnostic original child has no positive native thread ID'
            self.focus = None
            api.user.GetKeyboardLayout.argtypes = (ctypes.c_uint32,)
            api.user.GetKeyboardLayout.restype = ctypes.c_void_p
            self.initial_layout = int(self.probe._call(api.user.GetKeyboardLayout, self.tid) or 0)
            self.record['initialLayout'] = self.initial_layout
            assert self.tid > 0 and self.initial_layout == 0x04090409, 'Diagnostic requires the observed original English-US HKL'
        except BaseException as exc:
            self.record['admissionError'] = _error(exc)
            try: self.close()
            except BaseException as later:
                self.record['closeError'] = _error(later)
                exc.diagnosticEngineCloseError = _error(later)
                exc.add_note('Secondary diagnostic engine HANDLE close failure: ' + _error(later))
            exc.diagnosticEngineLease = self.record
            raise

    def guard(self, command, after):
        assert time.monotonic() < self.deadline, 'Diagnostic lifetime deadline expired'
        assert len(self.rows) < 12, 'Diagnostic generation observations exceed bound'
        row = dict(command=command, after=after, sourceCall='EngineLease.guard', observationIndex=len(self.rows))
        self.rows.append(row)
        row['shell'] = self.probe.process_snapshot(self.process)
        row['engine'] = self.probe.engine_snapshot(self.handle)
        assert row['shell'] == self.shell and row['engine'] == self.engine, 'Diagnostic retained generation changed'
        assert join_shortcut_generation(self.process, self.binding['parentHwnd'], self.binding['childHwnd'], row['engine']) == self.admission
        click_key = (self.binding['parentHwnd'], self.binding['childHwnd'], self.engine['pid'])
        click = getattr(self.process, 'opengeul_editor_click_generations', {}).get(click_key)
        assert click is not None and (click[0], Path(click[1]).resolve(), click[2]) == (self.engine['pid'], Path(self.engine['image']).resolve(), self.engine['creationTime']), 'Diagnostic click generation differs from the retained engine'
        a, b = self.api, self.binding
        for hwnd, pid, root in ((b['suiteHwnd'], b['shellPid'], b['suiteHwnd']),
                                (b['parentHwnd'], b['shellPid'], b['suiteHwnd']),
                                (b['childHwnd'], b['officePid'], b['suiteHwnd'])):
            assert a.user.IsWindow(hwnd) and a.pid(hwnd) == pid and a.user.GetAncestor(hwnd, 2) == root, 'Original diagnostic ancestry changed'
        assert a.user.IsChild(b['suiteHwnd'], b['parentHwnd']) and a.user.IsChild(b['parentHwnd'], b['childHwnd'])
        assert self.focus and a.user.IsWindow(self.focus) and a.pid(self.focus) == b['officePid']
        assert a.user.GetWindowThreadProcessId(self.focus, None) == self.tid and a.user.GetAncestor(self.focus, 2) == b['suiteHwnd']
        assert self.focus == b['childHwnd'] or a.user.IsChild(b['childHwnd'], self.focus)
        if command != 4:
            row['scope'] = a.editor_focus_snapshot(b['suiteHwnd'], b['childHwnd'], b['shellPid'], b['officePid'])
            assert native._editor_focus_snapshot_ready(row['scope'], b['suiteHwnd'], b['childHwnd'], b['shellPid'], b['officePid'], self.tid) == self.focus
        row['keyboard'] = self.probe.keyboard_snapshot(self.tid)
        if command != 4: assert row['keyboard']['keysDown'] == [], 'Diagnostic activation/observation requires neutral physical keys'
        layout = row['keyboard']['targetLayout']
        if command == 1 and not after: assert layout == self.initial_layout, 'Original diagnostic HKL changed before capture'
        elif command in (1, 2): assert layout & 0xffff == 0x0412, 'Korean diagnostic phase HKL changed'
        elif after: assert layout == self.initial_layout, 'Original diagnostic HKL did not return'
        assert time.monotonic() < self.deadline
        assert self.rows[-1] is row
        return row

    def retire(self):
        self.record['engineExit'] = retained_exit(self.probe, self.engine, self.handle)

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            assert self.probe.close_engine(handle) is True, 'Diagnostic retained HANDLE close failed'
            self.record['handleClosed'] = True


def run_roundtrip(observer, guard, record, setup_deadline):
    """One activation, one Korean read and one restore; cleanup never masks primary."""
    observer.generation_guard = guard
    primary = None
    try:
        record['originalAndActivation'] = observer.command(1, setup_deadline=setup_deadline)
        record['koreanSnapshot'] = observer.command(2, setup_deadline=setup_deadline)
    except BaseException as exc:
        primary = exc
        record['error'] = _error(exc)
    finally:
        try:
            if observer.restoration_required:
                record['originalProfileSnapshot'] = observer.command(4)
            elif observer.activation_attempted:
                # A missing ACK cannot establish that the thread stayed unchanged.
                assert not observer.state().profileChangeAttempted, 'Activation outcome is unknown and restoration cannot be admitted'
        except BaseException as exc:
            record['restorationError'] = _error(exc)
            if primary is None: primary = exc
        finally:
            record['commands'] = observer.commands
            try: observer.close()
            except BaseException as exc:
                record['hookCleanupError'] = _error(exc)
                if primary is None: primary = exc
    if primary is not None: raise primary
    original, restored = record['originalAndActivation'], record['originalProfileSnapshot']
    record.update(profileAndHklRestored=observer.profile_restored,
        typedStateEqual=original['typedValues'] == restored['typedValues'],
        immStateEqual=original['previousImmState'] == {key: restored['immState'][key] for key in ('open', 'conversion', 'sentence')},
        modeRestorationClaim=False, nativeImeAcceptance=False)
    assert observer.profile_restored, 'Diagnostic original profile/HKL restoration failed'


def close_generated_diagnostic_copy(api, process, hwnd, child, record, proof, lease):
    """Use the existing prompt-required generated-copy Discard authorization."""
    started = time.monotonic()
    evidence = record['diagnosticDocumentClose'] = dict(kind='prompt-required-generated-copy-discard',
        startedAt=started, deadline=lease.deadline if lease is not None else None,
        phaseLimitsSeconds=dict(promptReadinessFocus=20, dialogGone=20, rootGone=20, childGone=10),
        maximumSequentialDeclaredSeconds=70, cleanDirectCloseSupported=False,
        delegateAttempted=False, complete=False)
    try:
        assert lease is not None and lease.handle is not None, 'Original diagnostic engine lease is required for close'
        def budget(): assert time.monotonic() < lease.deadline, 'Diagnostic original lifetime deadline expired during generated-copy close'
        budget()
        evidence['originalShell'] = lease.probe.process_snapshot(process)
        budget()
        assert evidence['originalShell'] == lease.shell, 'Original diagnostic shell generation changed before close'
        evidence['originalEngine'] = lease.probe.engine_snapshot(lease.handle)
        budget()
        assert evidence['originalEngine'] == lease.engine, 'Original diagnostic engine generation changed before close'
        assert record['windowHwnd'] == hwnd and record['childHwnd'] == child and record['shellPid'] == process.pid
        assert record['officePid'] == lease.engine['pid']
        evidence['delegateAttempted'] = True
        native.close_document(api, process, hwnd, child, record, calc_close_proof=proof)
        finished = time.monotonic()
        assert started <= finished < lease.deadline, 'Diagnostic original lifetime deadline expired during generated-copy close'
        evidence.update(complete=True, finishedAt=finished)
        return evidence
    except BaseException as exc:
        evidence['error'] = _error(exc)
        raise


def close_clean_diagnostic_copy(api, process, hwnd, child, record, proof, lease, *, clock=time.monotonic, pause=time.sleep):
    """One normal close for this no-input copy; an unexpected modal is a failure."""
    from generated_calc_close import verify_saved_calc_copy
    started = clock()
    deadline = started + 20
    evidence = record['diagnosticDocumentClose'] = dict(kind='diagnostic-clean-copy-close',
        startedAt=started, deadline=deadline, closeMessageCount=0, cleanupClickCount=0,
        observations=[], frameClosed=False)
    def budget(): assert clock() < deadline, 'Diagnostic clean close exceeded its original deadline'
    verify_saved_calc_copy(proof)
    budget()
    assert lease is not None and lease.handle is not None, 'Original diagnostic engine lease is required for close'
    assert lease.probe.process_snapshot(process) == lease.shell and lease.probe.engine_snapshot(lease.handle) == lease.engine, 'Original diagnostic generation changed before close'
    assert record['windowHwnd'] == hwnd and record['childHwnd'] == child and record['shellPid'] == process.pid
    assert api.user.IsWindow(hwnd) and api.user.IsWindow(child)
    assert api.pid(hwnd) == process.pid and api.pid(child) == record['officePid']
    assert api.user.GetAncestor(hwnd, 2) == hwnd and api.user.GetAncestor(child, 2) == hwnd and api.user.IsChild(hwnd, child), 'Original diagnostic close ancestry changed'
    budget()
    api.request_close(hwnd, process.pid)
    evidence['closeMessageCount'] = 1
    while True:
        budget()
        assert len(evidence['observations']) < 201, 'Diagnostic clean-close observation bound exceeded'
        row = dict(observedAt=clock(), rootLive=bool(api.user.IsWindow(hwnd)), childLive=bool(api.user.IsWindow(child)), modals=[])
        evidence['observations'].append(row)
        if row['rootLive']: assert api.pid(hwnd) == process.pid, 'Original diagnostic root was replaced during close'
        if row['childLive']: assert api.pid(child) == record['officePid'], 'Original diagnostic child was replaced during close'
        if row['rootLive']:
            for dialog in api.windows(process.pid):
                if api.user.GetWindow(dialog, 4) != hwnd: continue
                assert len(row['modals']) < 8, 'Diagnostic modal observation bound exceeded'
                title = api.title(dialog)
                row['modals'].append(dict(hwnd=dialog, pid=api.pid(dialog), ownerHwnd=hwnd,
                    title=title[:256], titleTruncated=len(title)>256, className=api.class_name(dialog)[:256]))
            assert not row['modals'], 'Unexpected modal during no-input diagnostic close; no dialog action is authorized'
        budget()
        if not row['rootLive'] and not row['childLive']:
            verify_saved_calc_copy(proof)
            budget()
            finished = clock()
            assert started <= finished < deadline, 'Diagnostic clean close exceeded its original deadline'
            evidence.update(frameClosed=True, finishedAt=finished)
            return evidence
        pause(min(.1, max(0, deadline-clock())))


def case(suite, fixtures, output, readiness):
    from pywinauto import Desktop
    from calc_model_barrier import baseline_from_ooxml
    from home_routing_smoke import verify_native_archives
    name = 'tsf-profile-calc'
    folder = output/name
    folder.mkdir()
    original = native.require_engine_fixture(fixtures, 'calc', 'xlsx')
    source = folder/original.name
    shutil.copyfile(original, source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    proof = native._verified_saved_calc_close_proof(suite, folder, source, baseline_from_ooxml(original.read_bytes()), expected_sha256=source_hash)
    diagnostics = output/'diagnostics'/name
    diagnostics.mkdir(parents=True)
    previous = os.environ.get('OPENGEUL_SUITE_DIAGNOSTICS')
    try:
        os.environ['OPENGEUL_SUITE_DIAGNOSTICS'] = str(diagnostics)
        process = native.launch_suite([str(suite/'OpenGeul.Office.exe'), '--module', 'calc', '--file', str(source)], suite, output, name)
    finally:
        if previous is None: os.environ.pop('OPENGEUL_SUITE_DIAGNOSTICS', None)
        else: os.environ['OPENGEUL_SUITE_DIAGNOSTICS'] = previous
    record = dict(schemaVersion=1, kind='disposable-tsf-profile-diagnostic', case=name, module='calc',
        success=False, nativeImeAcceptance=False, modeRestorationClaim=False, keyboardInputCount=0,
        source=str(source), originalSha256=source_hash, shellPid=process.pid, readiness=readiness,
        attachments=[], cleanupErrors=[])
    api, lease, observer, primary = native.Windows(), None, None, None
    hwnd = parent = child = pid = None
    try:
        hwnd, parent, child, pid = native.verified_attachment(api, process, 'calc')
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=pid)
        Desktop(backend='win32').window(handle=hwnd).wrapper_object().maximize()
        native.activate_owned_suite(api, process, hwnd, record)
        started = time.monotonic()
        setup_deadline = started + 60
        record['setupBudget'] = dict(startedAt=started, deadline=setup_deadline, seconds=60)
        lease = EngineLease(api, process, suite, hwnd, parent, child, pid, started+180)
        record['retainedEngine'] = lease.record
        focus = prepare_diagnostic_editor_focus(api, process, hwnd, parent, child, pid, record, setup_deadline)
        lease.focus = focus
        assert int(api.user.GetWindowThreadProcessId(focus, None)) == lease.tid
        record['attachments'].append(dict(officePid=pid, officeCreationTime=lease.engine['creationTime'], officeImage=lease.engine['image']))
        observer = ProfileObserver(api, hwnd, child, focus, pid, folder, readiness['profile'], architecture='arm64', setup_deadline=setup_deadline)
        record.update(nativeArchitecture=observer.native_architecture, targetArchitecture=observer.target_architecture)
        probe, observer = observer, None  # run_roundtrip owns mandatory restoration and hook cleanup.
        run_roundtrip(probe, lease.guard, record, setup_deadline)
        record['observationComplete'] = True
    except BaseException as exc:
        primary = exc
        record['error'] = _error(exc)
        if hasattr(exc, 'diagnosticEngineLease'): record['retainedEngine'] = exc.diagnosticEngineLease
    finally:
        if observer is not None:
            try: observer.close()
            except BaseException as exc: record['cleanupErrors'].append(_error(exc))
        # Always attempt the original generated-copy normal close. No taskkill/Job termination.
        try:
            if hwnd and api.user.IsWindow(hwnd): close_generated_diagnostic_copy(api, process, hwnd, child, record, proof, lease)
            if process.poll() is None: native.close_home(api, process, record)
            assert process.poll() == 0, 'Original diagnostic shell did not exit zero'
            if lease is not None: lease.retire()
            record['nativeArchive'] = verify_native_archives(suite, output/'diagnostics', [record])
            assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash, 'Diagnostic changed generated document bytes'
            record['naturalRetirementVerified'] = True
        except BaseException as exc:
            record['cleanupErrors'].append(_error(exc))
            if primary is None: primary = exc
        finally:
            if lease is not None:
                try: lease.close()
                except BaseException as exc:
                    record['cleanupErrors'].append(_error(exc))
                    if primary is None: primary = exc
        record['success'] = primary is None and record.get('observationComplete') is True and record.get('naturalRetirementVerified') is True
        record['stage'] = 'complete' if record['success'] else 'failed'
        retain_result(output/'result.json', record, primary)
    if primary is not None: raise primary
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'fixtures', 'readiness', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(argv)
    assert os.name == 'nt' and __debug__, 'Native Windows with assertions is required'
    suite, fixtures, output = args.suite.resolve(), args.fixtures.resolve(), args.output.resolve()
    for path in (suite, fixtures, output, args.readiness.resolve()):
        assert not str(path).startswith(('\\\\', '//'))
        for part in (path, *path.parents): assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)()
    assert output != suite and suite not in output.parents and output != fixtures and fixtures not in output.parents
    inventory = json.loads((suite/'suite-inventory.json').read_text(encoding='utf-8-sig'))
    assert inventory.get('schemaVersion') == 1 and inventory.get('architecture') == 'arm64'
    native_arch.validate_native_architecture(native_arch.observe_native_architecture(), 'arm64')
    readiness = ime.require_readiness(json.loads(args.readiness.read_text(encoding='utf-8-sig')), architecture='arm64')
    output.mkdir(parents=True, exist_ok=False)
    names = (*ORIGINAL_PINS, 'tsf_profile_diagnostic.py', 'tsf_profile_diagnostic.h',
        'ascii_message_preparation.py', 'native_compiler_tools.py', 'counted_editor_shortcuts.py', 'ime_thread_mode.py',
        'suite_window_activation.py', 'windows_smoke.py', 'native_suite_architecture.py',
        'generated_calc_close.py', 'native_cleanup_receipt.py', 'home_routing_smoke.py')
    def pins():
        result = {}
        for name in names:
            path = Path(__file__).with_name(name)
            raw = path.read_bytes()
            assert 0 < len(raw) <= 2*1024*1024
            result[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return result
    before = pins()
    write_original(output/'source-before.json', before)
    primary = None
    try: case(suite, fixtures, output, readiness)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            after = pins()
            write_original(output/'source-after.json', dict(pins=after, equal=before == after))
            assert before == after, 'Executed diagnostic sources changed'
        except BaseException as exc:
            if primary is None: raise
            primary.diagnosticSourceAfterError = _error(exc)

    return 0


if __name__ == '__main__': raise SystemExit(main())
