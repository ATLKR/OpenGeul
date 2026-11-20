"""Owned real Windows clipboard provider draft; OS execution remains pending.

Pure policy/encoding tests are not Windows clipboard or product success receipts.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import threading
import time

MAX_PAYLOAD=4*1024*1024
MAX_TOTAL=8*1024*1024
STANDARD_FORMATS={'CF_UNICODETEXT':13,'CF_DIB':8,'CF_DIBV5':17}
REGISTERED_FORMATS=('HTML Format','Rich Text Format','PNG')

def _bounded(data):
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_PAYLOAD:
        raise ValueError('Owned clipboard payload exceeds its byte bound')
    return data

def _text(text):
    if not isinstance(text,str) or '\0' in text:
        raise ValueError('Owned clipboard text must not contain NUL')
    return text

def unicode_text(text):return _bounded((_text(text)+'\0').encode('utf-16le'))

def cf_html(fragment):
    content=_text(fragment).encode('utf-8')
    head='Version:1.0\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n'
    prefix,suffix=b'<html><body><!--StartFragment-->',b'<!--EndFragment--></body></html>'
    sh=len(head.format(0,0,0,0).encode('ascii'));sf=sh+len(prefix);ef=sf+len(content);eh=ef+len(suffix)
    data=head.format(sh,eh,sf,ef).encode('ascii')+prefix+content+suffix+b'\0'
    _bounded(data);inspect_cf_html(data)
    return data

def inspect_cf_html(data):
    _bounded(data)
    match=re.match(rb'Version:1\.0\r\nStartHTML:(\d{10})\r\nEndHTML:(\d{10})\r\nStartFragment:(\d{10})\r\nEndFragment:(\d{10})\r\n',data)
    if not match:raise ValueError('Owned CF_HTML header is malformed')
    sh,eh,sf,ef=(int(value) for value in match.groups())
    if (sh!=match.end() or not sh<=sf<=ef<=eh or eh!=len(data)-1 or data[-1:]!=b'\0'
            or b'\0' in data[:-1] or not data[sh:sf].endswith(b'<!--StartFragment-->')
            or not data[ef:eh].startswith(b'<!--EndFragment-->')):
        raise ValueError('CF_HTML offsets do not bind the exact owned UTF-8 fragment')
    try:
        fragment=data[sf:ef].decode('utf-8',errors='strict');data[sh:eh].decode('utf-8',errors='strict')
    except UnicodeError as error:raise ValueError('CF_HTML offset splits a UTF-8 character') from error
    return {'startHTML':sh,'endHTML':eh,'startFragment':sf,'endFragment':ef,'fragment':fragment}

def _pixels(width,height,pixels):
    if (type(width) is not int or type(height) is not int or not 1<=width<=4096 or not 1<=height<=4096
            or not isinstance(pixels,bytes) or len(pixels)!=width*height*4 or len(pixels)+124>MAX_PAYLOAD):
        raise ValueError('Owned RGBA bitmap dimensions/pixels exceed their bound')
    bgra=bytearray(pixels);bgra[0::4],bgra[2::4]=pixels[2::4],pixels[0::4]
    return bytes(bgra)

def dib_v5(width,height,pixels):
    bgra=_pixels(width,height,pixels);header=bytearray(124)
    struct.pack_into('<IiiHHIIiiII',header,0,124,width,-height,1,32,3,len(bgra),3780,3780,0,0)
    struct.pack_into('<IIIII',header,40,0xff0000,0xff00,0xff,0xff000000,0x73524742)
    struct.pack_into('<I',header,108,4)
    return bytes(header)+bgra

def dib_rgb(width,height,pixels):
    bgra=bytearray(_pixels(width,height,pixels));bgra[3::4]=bytes([0])*width*height
    return struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,len(bgra),3780,3780,0,0)+bytes(bgra)

def clipboard_payloads(*,text=None,html=None,rtf=None,png=None,bitmap=None):
    payloads={}
    if text is not None:payloads['CF_UNICODETEXT']=unicode_text(text)
    if html is not None:payloads['HTML Format']=cf_html(html)
    if rtf is not None:
        _text(rtf)
        if not rtf.startswith('{\\rtf1') or not rtf.endswith('}'):raise ValueError('Owned Office RTF framing is missing')
        try:payloads['Rich Text Format']=_bounded(rtf.encode('ascii')+b'\0')
        except UnicodeError as error:raise ValueError('Owned RTF requires ASCII Unicode escapes') from error
    if png is not None:
        _bounded(png)
        if len(png)<33 or png[:8]!=b'\x89PNG\r\n\x1a\n' or png[12:16]!=b'IHDR' or struct.unpack('>I',png[8:12])[0]!=13:
            raise ValueError('Owned PNG has no bounded IHDR')
        width,height=struct.unpack('>II',png[16:24])
        if not 1<=width<=4096 or not 1<=height<=4096 or width*height*4>MAX_PAYLOAD:
            raise ValueError('Owned PNG decoded pixels exceed their bound')
        payloads['PNG']=png
    if bitmap is not None:
        if not isinstance(bitmap,tuple) or len(bitmap)!=3:raise ValueError('Owned bitmap requires width/height/RGBA')
        payloads['CF_DIBV5']=dib_v5(*bitmap);payloads['CF_DIB']=dib_rgb(*bitmap)
    if sum(map(len,payloads.values()))>MAX_TOTAL:raise ValueError('Owned representations exceed their total byte bound')
    return payloads

def validate_owner(before,after):
    keys={'hwnd','pid','creation','session','sequence'}
    if (not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=keys or set(after)!=keys
            or before!=after or any(type(before[key]) is not int or before[key]<=0 for key in keys)):
        raise AssertionError('Clipboard owner/process/sequence changed; mutation is forbidden')
    return dict(before)


class ClipboardCore:
    """OS boundary adapter; writes/readback/cleanup share the held owner contract."""
    def __init__(self,api,hwnd):
        self.api=api;self.hwnd=hwnd;self.identity=api.identity(hwnd)
        self.expected=None;self.payloads={};self.format_ids={};self.delayed=set();self.rendered=set()
        self.requests=[];self.requested=threading.Event();self.released=threading.Event()
    def _held(self):
        if self.api.identity(self.hwnd)!=self.identity:
            raise AssertionError('Clipboard provider HWND/held process identity changed')
    def _owner(self):
        self._held();return self.api.owner_record(self.hwnd)
    def _set(self,fmt,data):
        handle=self.api.alloc(data)
        try:self.api.set(fmt,handle)
        except BaseException:
            self.api.free(handle);raise
        # SetClipboardData transfers ownership. Never free this handle ourselves.
    def publish(self,payloads,*,delayed=()):
        if (not isinstance(payloads,dict) or len(payloads)>6
                or any(name not in (*STANDARD_FORMATS,*REGISTERED_FORMATS) for name in payloads)
                or any(not isinstance(data,bytes) or not 0<len(data)<=MAX_PAYLOAD for data in payloads.values())
                or sum(map(len,payloads.values()))>MAX_TOTAL or not set(delayed)<=set(payloads)):
            raise ValueError('Invalid declared clipboard representations')
        if self.expected is not None:raise ValueError('Clipboard provider publishes only once')
        self._held();self.payloads=dict(payloads)
        self.format_ids={name:self.api.format_id(name) for name in payloads};self.delayed=set(delayed)
        if len(set(self.format_ids.values()))!=len(self.format_ids):raise AssertionError('Clipboard formats collided')
        self.api.open(self.hwnd)
        try:
            self._held();self.api.empty()
            for name,data in self.payloads.items():
                fmt=self.format_ids[name]
                if name in self.delayed:self.api.set(fmt,None)
                else:self._set(fmt,data);self.rendered.add(name)
        except BaseException:
            # A partial publication still owns transferred handles. Preserve its
            # actual owner receipt so orderly cleanup can EmptyClipboard safely.
            self.expected=self._owner()
            raise
        finally:self.api.close()
        self.expected=self._owner()
        validate_owner({**self.identity,'sequence':self.expected['sequence']},self.expected)
        return self.receipt()
    def receipt(self):
        return {'owner':dict(self.expected) if self.expected else None,
                'formats':[{'name':name,'id':self.format_ids[name],'bytes':len(data),
                            'sha256':hashlib.sha256(data).hexdigest(),'rendered':name in self.rendered}
                           for name,data in self.payloads.items()],
                'delayedRequests':list(self.requests),'sourceQualified':False}
    def readback(self):
        if self.expected is None:raise AssertionError('No clipboard publication receipt')
        validate_owner(self.expected,self._owner())
        self.api.open(self.hwnd)
        try:
            validate_owner(self.expected,self._owner())
            formats=self.api.enumerate_formats()
            if not set(self.format_ids.values())<=set(formats):raise AssertionError('Advertised clipboard format disappeared')
            for name,data in self.payloads.items():
                if name not in self.rendered:continue  # Do not accidentally request our own delayed format.
                actual=self.api.read(self.format_ids[name],len(data))
                if actual!=data:raise AssertionError('Actual OS clipboard payload differs from owned bytes')
            validate_owner(self.expected,self._owner())
        finally:self.api.close()
        return {**self.receipt(),'readbackMatched':len(self.rendered)==len(self.payloads),
                'metadataMatched':True,'enumeratedFormatIds':formats}
    def render(self,fmt,*,timeout=10):
        """WM_RENDERFORMAT arrives with clipboard open in the requesting process."""
        matches=[name for name,value in self.format_ids.items() if value==fmt]
        if len(matches)!=1 or matches[0] not in self.delayed:raise AssertionError('Unexpected delayed clipboard request')
        name=matches[0];validate_owner(self.expected,self._owner())
        requester=(self.api.requester() if hasattr(self.api,'requester') else
                   {'hwnd':0,'pid':0,'tid':0,'identityObserved':False})
        row={'format':name,'id':fmt,'requestedAtMonotonic':time.monotonic(),'completed':False,
             'requester':requester,'requesterQualified':False}
        self.requests.append(row);self.requested.set()
        if not self.released.wait(timeout):raise TimeoutError('Actual delayed clipboard request was not released')
        validate_owner(self.expected,self._owner())
        self._set(fmt,self.payloads[name])  # Must not OpenClipboard in WM_RENDERFORMAT.
        self.rendered.add(name);self.expected=self._owner()
        row.update(completed=True,completedAtMonotonic=time.monotonic())
    def render_all(self):
        """WM_RENDERALLFORMATS lifecycle; not proof of an app paste request."""
        if self.expected is None or self._owner()!=self.expected:return False
        self.api.open(self.hwnd)
        try:
            if self._owner()!=self.expected:return False
            for name,data in self.payloads.items():
                if name not in self.rendered:
                    self._set(self.format_ids[name],data);self.rendered.add(name)
                    self.expected=self._owner()
            return True
        finally:self.api.close()
    def clear_if_owned(self):
        if self.expected is None:return False
        self._held()
        if self._owner()!=self.expected:return False
        self.api.open(self.hwnd)
        try:
            if self._owner()!=self.expected:return False
            self.api.empty();self.expected=None;return True
        finally:self.api.close()


class _ClipboardWin32:
    def __init__(self):
        if os.name!='nt':raise ValueError('Actual Windows clipboard is required')
        self.user=ctypes.WinDLL('user32',use_last_error=True);self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        for name,args,result in (
            ('OpenClipboard',[W.HWND],W.BOOL),('CloseClipboard',[],W.BOOL),('EmptyClipboard',[],W.BOOL),
            ('SetClipboardData',[W.UINT,W.HANDLE],W.HANDLE),('GetClipboardData',[W.UINT],W.HANDLE),
            ('GetClipboardOwner',[],W.HWND),('GetClipboardSequenceNumber',[],W.DWORD),
            ('GetOpenClipboardWindow',[],W.HWND),
            ('RegisterClipboardFormatW',[W.LPCWSTR],W.UINT),('EnumClipboardFormats',[W.UINT],W.UINT),
            ('GetWindowThreadProcessId',[W.HWND,ctypes.POINTER(W.DWORD)],W.DWORD)):
            function=getattr(self.user,name);function.argtypes=args;function.restype=result
        for name,args,result in (
            ('GlobalAlloc',[W.UINT,ctypes.c_size_t],W.HGLOBAL),('GlobalLock',[W.HGLOBAL],ctypes.c_void_p),
            ('GlobalUnlock',[W.HGLOBAL],W.BOOL),('GlobalFree',[W.HGLOBAL],W.HGLOBAL),
            ('GlobalSize',[W.HGLOBAL],ctypes.c_size_t),('OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE),
            ('CloseHandle',[W.HANDLE],W.BOOL),('GetProcessId',[W.HANDLE],W.DWORD),
            ('GetProcessTimes',[W.HANDLE,*[ctypes.POINTER(W.FILETIME)]*4],W.BOOL),
            ('ProcessIdToSessionId',[W.DWORD,ctypes.POINTER(W.DWORD)],W.BOOL)):
            function=getattr(self.kernel,name);function.argtypes=args;function.restype=result
        self.handle=self.kernel.OpenProcess(0x1000,False,os.getpid())
        if not self.handle:raise OSError('Clipboard provider process handle is unavailable')
        self.held=self._process()
    def _process(self):
        pid=int(self.kernel.GetProcessId(self.handle));times=[W.FILETIME() for _ in range(4)];session=W.DWORD()
        if pid!=os.getpid() or not self.kernel.GetProcessTimes(self.handle,*[ctypes.byref(t) for t in times]) or not self.kernel.ProcessIdToSessionId(pid,ctypes.byref(session)):
            raise AssertionError('Clipboard provider held process/session changed')
        return {'pid':pid,'creation':times[0].dwHighDateTime<<32|times[0].dwLowDateTime,'session':int(session.value)}
    def identity(self,hwnd):
        record=self._process();pid=W.DWORD();tid=self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if record!=self.held or not tid or pid.value!=record['pid']:raise AssertionError('Clipboard owner HWND is not held')
        return {'hwnd':int(hwnd),**record}
    def owner_record(self,hwnd):
        actual=int(self.user.GetClipboardOwner() or 0);sequence=int(self.user.GetClipboardSequenceNumber())
        if actual!=hwnd:return {'hwnd':actual,'pid':0,'creation':0,'session':0,'sequence':sequence}
        return {**self.identity(hwnd),'sequence':sequence}
    def requester(self):
        # HWND/PID/TID metadata is not a held app/WebView ancestry receipt.
        # OpenClipboard(NULL) may make requester HWND impossible to observe.
        hwnd=int(self.user.GetOpenClipboardWindow() or 0);pid=W.DWORD()
        tid=int(self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))) if hwnd else 0
        return {'hwnd':hwnd,'pid':int(pid.value),'tid':tid,'identityObserved':bool(hwnd and pid.value and tid)}
    def open(self,hwnd):
        if not self.user.OpenClipboard(hwnd):raise OSError('OpenClipboard failed')
    def close(self):
        if not self.user.CloseClipboard():raise OSError('CloseClipboard failed')
    def empty(self):
        if not self.user.EmptyClipboard():raise OSError('EmptyClipboard failed')
    def format_id(self,name):
        value=STANDARD_FORMATS.get(name) or int(self.user.RegisterClipboardFormatW(name))
        if not value:raise OSError('RegisterClipboardFormatW failed')
        return value
    def alloc(self,data):
        handle=self.kernel.GlobalAlloc(0x42,len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT.
        if not handle:raise OSError('GlobalAlloc failed')
        address=self.kernel.GlobalLock(handle)
        if not address:self.kernel.GlobalFree(handle);raise OSError('GlobalLock failed')
        try:ctypes.memmove(address,data,len(data))
        finally:self.kernel.GlobalUnlock(handle)
        return handle
    def free(self,handle):
        if self.kernel.GlobalFree(handle):raise OSError('Untransferred GlobalFree failed')
    def set(self,fmt,handle):
        ctypes.set_last_error(0);result=self.user.SetClipboardData(fmt,handle)
        # Delayed rendering legitimately returns NULL; a last-error marks failure.
        if (handle is not None and not result) or (handle is None and ctypes.get_last_error()):
            raise OSError('SetClipboardData failed')
    def enumerate_formats(self):
        result=[];last=0
        for _ in range(32):
            ctypes.set_last_error(0);value=int(self.user.EnumClipboardFormats(last))
            if not value:
                if ctypes.get_last_error():raise OSError('EnumClipboardFormats failed')
                return result
            if value in result:raise AssertionError('Clipboard format enumeration cycled')
            result.append(value);last=value
        raise AssertionError('Clipboard format enumeration exceeds its bound')
    def read(self,fmt,length):
        handle=self.user.GetClipboardData(fmt)
        if not handle:raise OSError('GetClipboardData failed')
        size=int(self.kernel.GlobalSize(handle))
        if not length<=size<=MAX_PAYLOAD+64:raise AssertionError('Actual clipboard memory exceeds its bound')
        address=self.kernel.GlobalLock(handle)
        if not address:raise OSError('Clipboard read GlobalLock failed')
        try:return ctypes.string_at(address,length)
        finally:self.kernel.GlobalUnlock(handle)
    def dispose(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


class WindowsClipboardProvider:
    """One hidden real owner HWND/message pump; no product or browser substitute."""
    def __init__(self,payloads,*,source_root,delayed=()):
        if os.name!='nt':raise ValueError('Actual Windows clipboard provider needs Windows')
        from windows_ime import actual_source_binding
        self.binding=actual_source_binding(source_root)
        self.payloads=dict(payloads);self.delayed=tuple(delayed);self.core=None;self.error=None
        self.ready=threading.Event();self.completed=threading.Event();self.commands=[];self.lock=threading.Lock()
        self.thread=None;self.hwnd=None;self.api=None;self.closing=False
    def __enter__(self):
        self.thread=threading.Thread(target=self._pump,name='OpenGeul-owned-clipboard',daemon=True);self.thread.start()
        try:
            if not self.ready.wait(15):raise TimeoutError('Owned clipboard HWND did not become ready')
            self._check();return self
        except BaseException:
            if self.core:self.core.released.set()
            if self.api and self.hwnd:self.api.user.PostMessageW(self.hwnd,0x10,0,0)
            self.thread.join(3)
            raise
    def _check(self):
        if self.error:raise RuntimeError('Owned Windows clipboard provider failed at '+self.error)
        if self.thread is None or not self.thread.is_alive():raise AssertionError('Clipboard provider process pump exited')
    def _call(self,method):
        self._check();done=threading.Event();row={'method':method,'done':done}
        with self.lock:
            if len(self.commands)>=16:raise AssertionError('Clipboard command queue exceeds its bound')
            self.commands.append(row)
        if not self.api.user.PostMessageW(self.hwnd,0x8001,0,0):raise OSError('Clipboard command PostMessage failed')
        if not done.wait(15):raise TimeoutError('Clipboard owner command did not complete')
        if 'error' in row:raise row['error']
        self._check();return row['result']
    def readback(self):return {**self._call('readback'),'source':self.binding,'productTelemetry':False}
    def wait_requested(self,timeout=5,*,require_native_requester=False):
        self._check()
        if not self.core.requested.wait(timeout):raise TimeoutError('No actual WM_RENDERFORMAT request was observed')
        rows=list(self.core.requests)
        if require_native_requester and any(row.get('requesterQualified') is not True for row in rows):
            raise AssertionError('Delayed request has no held native app/WebView requester binding')
        return rows
    def release(self):
        self._check();self.core.released.set()
    def __exit__(self,*_):
        if self.core:self.core.released.set()
        if self.api and self.hwnd:self.api.user.PostMessageW(self.hwnd,0x10,0,0)
        if self.thread:self.thread.join(15)
        if self.thread and self.thread.is_alive():raise TimeoutError('Owned clipboard pump did not close')
        if self.error:raise RuntimeError('Owned clipboard cleanup/provider failed at '+self.error)
    def _pump(self):
        stage='create-owner-window'
        try:
            import uuid
            self.api=_ClipboardWin32();u=self.api.user;k=self.api.kernel
            callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
            class WindowClass(ctypes.Structure):
                _fields_=[('cbSize',W.UINT),('style',W.UINT),('lpfnWndProc',callback_type),('cbClsExtra',ctypes.c_int),
                          ('cbWndExtra',ctypes.c_int),('hInstance',W.HINSTANCE),('hIcon',W.HANDLE),('hCursor',W.HANDLE),
                          ('hbrBackground',W.HANDLE),('lpszMenuName',W.LPCWSTR),('lpszClassName',W.LPCWSTR),('hIconSm',W.HANDLE)]
            for name,args,result in (
                ('RegisterClassExW',[ctypes.POINTER(WindowClass)],W.ATOM),
                ('CreateWindowExW',[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.HWND,W.HMENU,W.HINSTANCE,ctypes.c_void_p],W.HWND),
                ('DefWindowProcW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],ctypes.c_ssize_t),
                ('GetMessageW',[ctypes.POINTER(W.MSG),W.HWND,W.UINT,W.UINT],ctypes.c_int),
                ('TranslateMessage',[ctypes.POINTER(W.MSG)],W.BOOL),('DispatchMessageW',[ctypes.POINTER(W.MSG)],ctypes.c_ssize_t),
                ('PostMessageW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],W.BOOL),('DestroyWindow',[W.HWND],W.BOOL),
                ('PostQuitMessage',[ctypes.c_int],None),('UnregisterClassW',[W.LPCWSTR,W.HINSTANCE],W.BOOL)):
                function=getattr(u,name);function.argtypes=args;function.restype=result
            k.GetModuleHandleW.argtypes=[W.LPCWSTR];k.GetModuleHandleW.restype=W.HMODULE
            instance=k.GetModuleHandleW(None);class_name='OpenGeulOwnedClipboard'+uuid.uuid4().hex
            @callback_type
            def wndproc(hwnd,msg,wparam,lparam):
                try:
                    if msg==0x305:  # WM_RENDERFORMAT; no OpenClipboard here.
                        self.core.render(int(wparam));return 0
                    if msg==0x306:
                        self.core.render_all();return 0
                    if msg==0x8001:
                        with self.lock:commands,self.commands=self.commands,[]
                        for row in commands:
                            try:row['result']=getattr(self.core,row['method'])()
                            except BaseException as error:row['error']=error
                            finally:row['done'].set()
                        return 0
                    if msg==0x10:
                        self.core.clear_if_owned();u.DestroyWindow(hwnd);self.hwnd=None;return 0
                    if msg==2:u.PostQuitMessage(0);return 0
                    return u.DefWindowProcW(hwnd,msg,wparam,lparam)
                except BaseException as error:
                    self.error='window-message-'+str(int(msg))+'-'+type(error).__name__;self.ready.set()
                    if msg!=2:u.PostQuitMessage(1)
                    return 0
            wc=WindowClass();wc.cbSize=ctypes.sizeof(wc);wc.lpfnWndProc=wndproc;wc.hInstance=instance;wc.lpszClassName=class_name
            if not u.RegisterClassExW(ctypes.byref(wc)):raise OSError('Owner window class registration failed')
            try:
                # HWND_MESSAGE: an actual owned HWND receives clipboard messages.
                self.hwnd=int(u.CreateWindowExW(0,class_name,'OpenGeul owned clipboard',0,0,0,0,0,ctypes.c_void_p(-3),None,instance,None) or 0)
                if not self.hwnd:raise OSError('Owner window creation failed')
                self.core=ClipboardCore(self.api,self.hwnd);stage='publish-real-clipboard'
                self.core.publish(self.payloads,delayed=self.delayed);self.ready.set();stage='message-pump'
                message=W.MSG()
                while True:
                    status=u.GetMessageW(ctypes.byref(message),None,0,0)
                    if status==0:break
                    if status<0:raise OSError('Owner clipboard message pump failed')
                    u.TranslateMessage(ctypes.byref(message));u.DispatchMessageW(ctypes.byref(message))
            finally:
                if self.hwnd:
                    if self.core:self.core.clear_if_owned()
                    u.DestroyWindow(self.hwnd);self.hwnd=None
                u.UnregisterClassW(class_name,instance)
        except BaseException as error:self.error=stage+'-'+type(error).__name__;self.ready.set()
        finally:
            if self.api:self.api.dispose()
            self.completed.set()


# Optional host-only callback statistics. Existing clipboard/provider code above
# is unchanged; this seam neither subscribes to events nor reads their payload.
import math as _cb_math
import sys as _cb_sys
import types as _cb_types

_CB_CONSOLE_TYPES = ('assert','clear','count','debug','dir','dirxml','endGroup',
    'error','info','log','profile','profileEnd','startGroup','startGroupCollapsed',
    'table','time','timeEnd','trace','warning')
_CB_ERROR_NAMES = ('Error','TypeError','ReferenceError','RangeError','SyntaxError',
    'URIError','EvalError','NotAllowedError','SecurityError','NotSupportedError',
    'AbortError','InvalidStateError','QuotaExceededError','TimeoutError','TargetClosedError')
_CB_CONSOLE_CODES = {name:index for index,name in enumerate(_CB_CONSOLE_TYPES,1)}
_CB_ERROR_CODES = {name:index for index,name in enumerate(_CB_ERROR_NAMES,1)}


class ClipboardCallbackObservation:
    """One optional original-page reference; callback delivery is not mutation proof."""
    def __init__(self,session,page,transport_code,owner,writer,*,clock=time.monotonic,enabled=False,location_writer=None):
        self.session,self.page,self.transport_code=session,page,transport_code
        self._owner_input,self._writer,self._clock=owner,writer,clock
        self._enabled=enabled is True
        self.active=False;self.installed=False;self.install_known=False
        self.page_identity_known=False;self.page_identity_matched=False
        self.cleanup_known=False;self.own_reference_released=False;self.write_known=False
        self._owner=None;self._start=None;self._wait_start=None
        self._window_ms=None;self._wait_ms=None;self._closed=False
        self._events=[];self._console=[0]*20;self._errors=[0]*16
        self._optional=[];self._overflow=False;self._error_overflow=False
        self._location_writer=location_writer
        self._warning_locations=[]

    def _fault(self,site,error=None):
        kind={TypeError:1,ValueError:2,RuntimeError:3,OSError:4,PermissionError:5,
              AssertionError:6,KeyError:7,KeyboardInterrupt:8,SystemExit:9}.get(type(error),0)
        if len(self._optional)<4:self._optional.append([site,kind])
        else:self._error_overflow=True

    def _now(self,*,primary=None):
        try:
            value=self._clock()
            if type(value) not in (int,float) or not 0<=value<=10**12 or not _cb_math.isfinite(value):
                self._fault(4);return None
            return value
        except BaseException as error:
            if primary is None and not isinstance(error,Exception):raise
            self._fault(4,error);return None

    def _elapsed(self,start,end):
        if start is None or end is None:return None
        if not 0<=end-start<=86400:self._fault(4);return None
        return round((end-start)*1000)

    def __enter__(self):
        if not self._enabled:return self
        self._start=self._now()
        owner=self._owner_input
        if (type(owner) is dict and set(owner)=={'hwnd','pid','creation','session','sequence'}
                and all(type(value) is int and 0<value<2**64 for value in owner.values())):
            self._owner=dict(owner)
        else:self._fault(1)
        try:
            self.page_identity_matched=self.session.page is self.page
            self.page_identity_known=True
            if not self.page_identity_matched:self.install_known=True;self._fault(1);return self
            if self.session._clipboard_callback_sink is not None:
                self.install_known=True;self._fault(2);return self
            self.session._clipboard_callback_sink=self
            if self.session._clipboard_callback_sink is not self:
                self._fault(2);return self
            self.install_known=True;self.installed=True;self.active=True
        except Exception as error:
            self._fault(2,error)
            self._detach()
        return self

    def begin_wait(self):
        if self._enabled:self._wait_start=self._now()

    def end_wait(self,*,primary=None):
        try:
            if self._enabled:self._wait_ms=self._elapsed(self._wait_start,self._now(primary=primary))
        except BaseException as error:
            if primary is None and not isinstance(error,Exception):raise
            self._wait_ms=None;self._fault(4,error)

    def _detach(self,*,primary=None):
        self.active=False
        try:
            current=self.session._clipboard_callback_sink
            if current is self:
                self.session._clipboard_callback_sink=None
                self.own_reference_released=self.session._clipboard_callback_sink is None
                self.cleanup_known=self.own_reference_released
            elif self.installed and not self.own_reference_released:
                self.cleanup_known=False;self._fault(5)
            else:self.cleanup_known=True
        except BaseException as error:
            self.cleanup_known=False
            if primary is None and not isinstance(error,Exception):raise
            self._fault(5,error)

    def __exit__(self,error_type,primary,traceback):
        if not self._enabled or self._closed:return False
        self._closed=True;self.active=False
        effective_primary=primary
        new_cancel=None
        def finish_window():
            self._window_ms=self._elapsed(self._start,self._now(primary=effective_primary))
        def write_packet():
            packet=self.packet()
            if len(json.dumps(packet,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii'))>8192:
                raise ValueError()
            self._writer(packet);self.write_known=True
            _cb_write_warning_locations(self)
        for site,action in ((4,finish_window),(5,lambda:self._detach(primary=effective_primary)),(6,write_packet)):
            try:action()
            except BaseException as failure:
                self._fault(site,failure)
                if effective_primary is None and not isinstance(failure,Exception):
                    effective_primary=failure;new_cancel=failure
        if new_cancel is not None:raise new_cancel
        return False

    def packet(self):
        return dict(schemaVersion=1,diagnosticOnly=True,acceptanceEligible=False,qualification=False,
            transportCode=self.transport_code,clipboardOwner=dict(self._owner) if self._owner is not None else None,
            installKnown=self.install_known,installed=self.installed,pageIdentityKnown=self.page_identity_known,
            pageIdentityMatched=self.page_identity_matched,cleanupKnown=self.cleanup_known,
            ownReferenceReleased=self.own_reference_released,callbackWindowMsKnown=self._window_ms is not None,
            callbackWindowMs=self._window_ms,dirtyWaitMsKnown=self._wait_ms is not None,dirtyWaitMs=self._wait_ms,
            events=[list(row) for row in self._events],consoleTypeCounts=list(self._console),
            pageErrorNameCounts=list(self._errors),overflow=self._overflow,
            optionalErrors=[list(row) for row in self._optional],errorOverflow=self._error_overflow,
            actualEventTimingKnown=False,handlerSuccessKnown=False,noErrorGuarantee=False)


def _forward_clipboard_callback(session,page,event,kind,attribute,codes):
    try:
        sink=session._clipboard_callback_sink
        if type(sink) is not ClipboardCallbackObservation or not sink.active or sink.page is not page:return
        if session.page is not page:sink._fault(1);return
        if len(sink._events)>=8:sink._overflow=True;return
        try:
            value=getattr(event,attribute)
            code=codes.get(value,0) if type(value) is str and len(value)<=64 else 0
            if code==0:sink._fault(7)
        except Exception as error:
            code=0;sink._fault(3,error)
        sink._events.append([kind,code,code!=0])
        (sink._console if kind==1 else sink._errors)[code]+=1
        if kind==1 and code==19 and sink._location_writer is not None:
            _cb_record_warning_location(sink,event)
    except Exception:
        pass  # Optional forwarding never replaces the existing handler outcome.


def forward_clipboard_console(session,page,message):
    _forward_clipboard_callback(session,page,message,1,'type',_CB_CONSOLE_CODES)


def forward_clipboard_pageerror(session,page,error):
    _forward_clipboard_callback(session,page,error,2,'name',_CB_ERROR_CODES)


def _cb_native_dict(value,expected):
    if type(expected) is not type or type(value) is not expected:return None
    lineage=type.__getattribute__(expected,'__mro__')
    if type(lineage) is not tuple or len(lineage)>8:return None
    for base in lineage:
        if type(base) is not type:return None
        descriptor=type.__getattribute__(base,'__dict__').get('__dict__')
        if descriptor is not None:
            if (type(descriptor) is not _cb_types.GetSetDescriptorType
                    or descriptor.__objclass__ is not base):return None
            result=object.__getattribute__(value,'__dict__')
            return result if type(result) is dict else None
    return None


def _cb_cached_warning_location(event):
    """Read only cached integers; unsupported package/cache shapes remain unknown."""
    try:
        modules=_cb_sys.modules
        if type(modules) is not dict:return None
        classes=[]
        for name in ('playwright.sync_api._generated','playwright._impl.console_message'):
            module=dict.get(modules,name)
            if type(module) is not _cb_types.ModuleType:return None
            namespace=_cb_types.ModuleType.__getattribute__(module,'__dict__')
            if type(namespace) is not dict:return None
            classes.append(dict.get(namespace,'ConsoleMessage'))
        wrapper=_cb_native_dict(event,classes[0])
        if wrapper is None:return None
        implementation=_cb_native_dict(dict.get(wrapper,'_impl_obj'),classes[1])
        if implementation is None:return None
        cached=dict.get(implementation,'_event')
        if type(cached) is not dict:return None
        coordinates=dict.get(cached,'location')
        if type(coordinates) is not dict:return None
        line=dict.get(coordinates,'lineNumber');column=dict.get(coordinates,'columnNumber')
        if not all(type(value) is int and 0<=value<=2147483647 for value in (line,column)):return None
        return line,column
    except BaseException:
        return None


def _cb_record_warning_location(sink,event):
    location=None
    try:location=_cb_cached_warning_location(event)
    except BaseException:pass
    sink._warning_locations.append([len(sink._events),location is not None,
        location[0] if location is not None else None,location[1] if location is not None else None])


def _cb_write_warning_locations(sink):
    if sink._location_writer is None:return
    try:
        packet=dict(schemaVersion=1,sidecarType=1,packetSchemaVersion=1,diagnosticOnly=True,
            acceptanceEligible=False,qualification=False,transportCode=sink.transport_code,
            clipboardOwner=dict(sink._owner) if sink._owner is not None else None,
            callbackWindowMs=sink._window_ms,dirtyWaitMs=sink._wait_ms,eventCount=len(sink._events),
            warningLocations=[list(row) for row in sink._warning_locations],
            installKnown=sink.install_known,installed=sink.installed,
            pageIdentityKnown=sink.page_identity_known,pageIdentityMatched=sink.page_identity_matched,
            cleanupKnown=sink.cleanup_known,ownReferenceReleased=sink.own_reference_released,
            scriptIdentityKnown=False,warningOriginKnown=False,handlerSuccessKnown=False)
        if len(json.dumps(packet,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii'))>8192:return
        sink._location_writer(packet)
    except BaseException:
        pass  # Optional sidecar cannot change the original packet or primary outcome.
