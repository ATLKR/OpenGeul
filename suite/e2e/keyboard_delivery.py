"""Temporary, thread-scoped queue observation for owned lifecycle diagnostics.

This does not inject, replay, translate, remove, or change a message. In VCL a
WM_CHAR can be consumed by PeekMessage before DispatchMessage, so a window-proc
hook alone cannot establish whether the character reached the input queue.
https://learn.microsoft.com/windows/win32/winmsg/getmsgproc
https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-keybdinput
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid


class Message(ctypes.Structure):
    _fields_ = [('sequence', ctypes.c_uint32), ('message', ctypes.c_uint32),
                ('remove', ctypes.c_uint32), ('pid', ctypes.c_uint32), ('tid', ctypes.c_uint32),
                ('hwnd', ctypes.c_uint64), ('wparam', ctypes.c_uint64), ('lparam', ctypes.c_uint64),
                ('layout', ctypes.c_uint64), ('focus', ctypes.c_uint64), ('caret', ctypes.c_uint64),
                ('foreground', ctypes.c_uint64),
                ('extraInfo', ctypes.c_uint64), ('counter', ctypes.c_uint64),
                ('messageTime', ctypes.c_uint32), ('unicodeWindow', ctypes.c_uint32),
                ('shift', ctypes.c_uint32), ('control', ctypes.c_uint32), ('alt', ctypes.c_uint32)]


class State(ctypes.Structure):
    _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                ('pid', ctypes.c_uint32), ('tid', ctypes.c_uint32),
                ('count', ctypes.c_int32), ('overflow', ctypes.c_int32), ('messages', Message * 2048)]


SOURCE = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
struct Message { uint32_t sequence,message,remove,pid,tid;
    uint64_t hwnd,wparam,lparam,layout,focus,caret,foreground,extraInfo,counter;
    uint32_t messageTime,unicodeWindow,shift,control,alt; };
struct State { uint32_t magic,version,pid,tid; volatile LONG count,overflow; Message messages[2048]; };
static State* shared=nullptr;
static HANDLE mapping=nullptr;
static bool connect() {
    if(!shared) {
        WCHAR name[160];
        swprintf_s(name,L"%s_%lu_%lu",L"__PREFIX__",GetCurrentProcessId(),GetCurrentThreadId());
        mapping=OpenFileMappingW(FILE_MAP_ALL_ACCESS,FALSE,name);
        if(!mapping) return false;
        shared=(State*)MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(State));
    }
    return shared && shared->magic==0x4f474b44 && shared->version==1
        && shared->pid==GetCurrentProcessId() && shared->tid==GetCurrentThreadId();
}
static void observe(MSG* message, WPARAM remove) {
    if(!connect()) return;
    UINT id=message->message;
    if(!((id>=WM_KEYFIRST && id<=WM_KEYLAST) || (id>=WM_IME_STARTCOMPOSITION && id<=WM_IME_COMPOSITION)
        || (id>=WM_IME_SETCONTEXT && id<=WM_IME_KEYUP))) return;
    DWORD pid=0;
    if(GetWindowThreadProcessId(message->hwnd,&pid)!=shared->tid || pid!=shared->pid) return;
    LONG index=InterlockedIncrement(&shared->count)-1;
    if(index<0 || index>=2048) { InterlockedExchange(&shared->overflow,1); return; }
    Message* row=&shared->messages[index];
    row->message=id; row->remove=(remove==PM_REMOVE); row->pid=pid; row->tid=GetCurrentThreadId();
    row->hwnd=(uint64_t)(UINT_PTR)message->hwnd; row->wparam=(uint64_t)message->wParam;
    row->lparam=(uint64_t)message->lParam; row->layout=(uint64_t)(UINT_PTR)GetKeyboardLayout(0);
    row->focus=(uint64_t)(UINT_PTR)GetFocus(); row->foreground=(uint64_t)(UINT_PTR)GetForegroundWindow();
    GUITHREADINFO info={}; info.cbSize=sizeof(info);
    if(GetGUIThreadInfo(GetCurrentThreadId(),&info)) row->caret=(uint64_t)(UINT_PTR)info.hwndCaret;
    row->extraInfo=(uint64_t)(UINT_PTR)GetMessageExtraInfo();
    LARGE_INTEGER counter; QueryPerformanceCounter(&counter); row->counter=(uint64_t)counter.QuadPart;
    row->messageTime=message->time; row->unicodeWindow=IsWindowUnicode(message->hwnd);
    row->shift=(uint16_t)GetKeyState(VK_SHIFT); row->control=(uint16_t)GetKeyState(VK_CONTROL);
    row->alt=(uint16_t)GetKeyState(VK_MENU);
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&row->sequence,index+1);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(int code,WPARAM wp,LPARAM lp) {
    DWORD error=GetLastError();
    if(code==HC_ACTION) observe((MSG*)lp,wp);
    SetLastError(error);
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) unsigned int StateSize() { return sizeof(State); }
BOOL WINAPI DllMain(HINSTANCE,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_DETACH) {
        if(shared) UnmapViewOfFile(shared);
        if(mapping) CloseHandle(mapping);
    }
    return TRUE;
}
'''


class ObserverLibrary:
    """Compile once before any trial process starts; never warm an editor during compilation."""
    def __init__(self, folder):
        assert os.name == 'nt' and ctypes.sizeof(ctypes.c_void_p) == 8, 'Native x64 Windows is required'
        from korean_ime_smoke import discover_msvc
        self.prefix = 'Local\\OpenGeulDelivery_' + uuid.uuid4().hex
        source, library = folder / 'delivery-observer.cpp', folder / 'delivery-observer.dll'
        source.write_text(SOURCE.replace('__PREFIX__', self.prefix.replace('\\', '\\\\')), encoding='utf-8')
        command = ['cl.exe', '/nologo', '/LD', '/O2', '/MT', '/EHsc', '/utf-8', str(source),
                   '/link', '/OUT:' + str(library), 'user32.lib']
        if shutil.which('cl.exe'):
            invoke = command
        else:
            vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
            vcvars = Path(discover_msvc(folder, vswhere)) / 'VC/Auxiliary/Build/vcvars64.bat'
            assert vcvars.is_file(), 'The observer requires Microsoft x64 C++ tools'
            script = folder / 'compile-delivery.cmd'
            script.write_text('@echo off\ncall "' + str(vcvars) + '"\nif errorlevel 1 exit /b 1\n'
                              + subprocess.list2cmdline(command) + '\n', encoding='utf-8')
            invoke = ['cmd.exe', '/d', '/c', str(script)]
        (folder / 'compiler-command.json').write_text(json.dumps(invoke, indent=2), encoding='utf-8')
        try:
            result = subprocess.run(invoke, cwd=folder, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError) as exc:
            (folder / 'compiler.log').write_bytes((getattr(exc, 'stdout', None) or b'') + (getattr(exc, 'stderr', None) or b''))
            raise
        (folder / 'compiler.log').write_bytes(result.stdout + result.stderr)
        result.check_returncode()
        self.dll = ctypes.WinDLL(str(library), use_last_error=True)
        self.dll.StateSize.restype = ctypes.c_uint32
        assert self.dll.StateSize() == ctypes.sizeof(State), 'Native queue observer memory layout differs'
        self.identity = {'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                         'dllSha256': hashlib.sha256(library.read_bytes()).hexdigest(),
                         'stateBytes': ctypes.sizeof(State), 'hook': 'WH_GETMESSAGE',
                         'scope': 'owned-editor-thread', 'compileBeforeTrials': True}


class DeliveryObserver:
    def __init__(self, library, api, root, child, pid):
        self.library, self.api, self.root, self.child, self.pid = library, api, root, child, pid
        self.tid = int(api.user.GetWindowThreadProcessId(child, None))
        assert self.tid and pid > 0 and api.pid(child) == pid, 'Queue observer requires the owned editor PID/TID'
        assert api.user.IsChild(root, child), 'Queue observer editor escaped the owned Suite window'
        self.calls, self.hook, self.mapping = [], None, None
        self.mapping = mmap.mmap(-1, ctypes.sizeof(State), tagname=library.prefix + '_' + str(pid) + '_' + str(self.tid))
        state = State(magic=0x4f474b44, version=1, pid=pid, tid=self.tid)
        self.mapping[:] = bytes(state)
        user = api.user
        user.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, W.HINSTANCE, W.DWORD]
        user.SetWindowsHookExW.restype = W.HANDLE
        user.UnhookWindowsHookEx.argtypes = [W.HANDLE]
        user.UnhookWindowsHookEx.restype = W.BOOL
        user.GetKeyboardLayout.argtypes = [W.DWORD]
        user.GetKeyboardLayout.restype = W.HANDLE
        try:
            address = ctypes.cast(library.dll.HookGet, ctypes.c_void_p)
            self.hook = user.SetWindowsHookExW(3, address, library.dll._handle, self.tid)
            if not self.hook: raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            self.close()
            raise

    def snapshot(self):
        # Lifecycle loads windows_smoke through its own importlib module. Its
        # bound ctypes structure has the same layout as a separate import, but
        # ctypes requires the exact pointer type declared by this supplied API.
        info_type = self.api.user.GetGUIThreadInfo.argtypes[1]._type_
        info = info_type(cbSize=ctypes.sizeof(info_type))
        if not self.api.user.GetGUIThreadInfo(self.tid, ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
        return {'focus': int(info.hwndFocus or 0), 'caret': int(info.hwndCaret or 0), 'active': int(info.hwndActive or 0),
                'foreground': int(self.api.user.GetForegroundWindow() or 0),
                'layout': int(self.api.user.GetKeyboardLayout(self.tid) or 0),
                'pid': self.pid, 'tid': self.tid, 'counter': time.perf_counter_ns()}

    @contextmanager
    def capture_sendinput(self):
        # Wrap the existing pywinauto call, retaining the original buffer, native
        # function, return value, parser, shortcuts and .025s marker pacing.
        from pywinauto import win32functions, win32structures
        original = win32functions.SendInput
        def observed(count, payload, size):
            assert len(self.calls) < 256, 'Bounded SendInput receipt storage overflowed'
            count = int(count)
            assert 0 < count <= 128, 'Unexpectedly large SendInput buffer in the owned marker trial'
            items = ctypes.cast(payload, ctypes.POINTER(win32structures.INPUT))
            rows = []
            for index in range(count):
                item = items[index]
                row = {'type': int(item.type)}
                if item.type == 1:
                    row.update(vk=int(item.ki.wVk), scan=int(item.ki.wScan), flags=int(item.ki.dwFlags),
                               time=int(item.ki.time), extraInfo=int(item.ki.dwExtraInfo or 0))
                rows.append(row)
            before = self.snapshot()
            inserted = original(count, payload, size)
            # Do not retry a short insertion. The unchanged pywinauto KeyAction
            # raises on a short count immediately after this wrapper returns it.
            self.calls.append({'requested': count, 'inserted': int(inserted), 'events': rows,
                               'before': before, 'after': self.snapshot()})
            return inserted
        win32functions.SendInput = observed
        try:
            yield
        finally:
            win32functions.SendInput = original

    def receipt(self):
        state = State.from_buffer_copy(self.mapping[:])
        rows = []
        for index in range(min(max(state.count, 0), 2048)):
            item = state.messages[index]
            if item.sequence != index + 1: break
            row = {name: int(getattr(item, name)) for name, _ in Message._fields_}
            row['remove'] = bool(item.remove)
            rows.append(row)
        return {'officePid': self.pid, 'editorTid': self.tid, 'childHwnd': self.child,
                'messages': rows, 'sendInputCalls': self.calls, 'overflow': bool(state.overflow),
                'publishedMessageCount': len(rows), 'reservedMessageCount': int(state.count),
                'observer': self.library.identity}

    def close(self):
        try:
            if self.hook and not self.api.user.UnhookWindowsHookEx(self.hook):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.hook = None
            if self.mapping is not None:
                self.mapping.close()
                self.mapping = None
