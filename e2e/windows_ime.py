"""Held Windows focus/OS keyboard/IME observation draft; OS execution pending."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

def validate_hosted_binding(environment,expected_head,*,platform):
    literal={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
             'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_RUN_ATTEMPT':'1'}
    if (platform!='nt' or any(environment.get(key)!=value for key,value in literal.items())
            or not re.fullmatch('[0-9a-f]{40}',expected_head) or environment.get('GITHUB_SHA')!=expected_head
            or not re.fullmatch('[1-9][0-9]{0,19}',environment.get('GITHUB_RUN_ID',''))
            or environment.get('GITHUB_JOB') not in ('native-e2e','native-e2e-arm64')):
        raise ValueError('Refusing native input mutation outside the exact hosted Source run')
    return {'sourceCommit':expected_head,'sourceRun':environment['GITHUB_RUN_ID'],'runAttempt':'1',
            'job':environment['GITHUB_JOB'],'repository':'ATLKR/OpenGeul'}

def require_gui_idle(flags,menu_owner):
    if (type(flags) is not int or not 0<=flags<=0xffffffff or type(menu_owner) is not int or menu_owner<0
            or flags&(0x4|0x8|0x10) or menu_owner):
        raise AssertionError('Actual native menu mode/owner intercepts OS keyboard input')
    return {'guiFlags':flags,'menuOwner':menu_owner}

def require_focus(before,after,processes,*,language=None):
    keys={'foreground','root','focus','focusRoot','rootPid','focusPid','focusTid','rootClass','focusClass',
          'visible','enabled','layout','session','desktop','guiFlags','menuOwner'}
    if not isinstance(before,dict) or not isinstance(after,dict) or set(before)!=keys or set(after)!=keys or before!=after:
        raise AssertionError('Native input focus binding changed before OS input')
    row=before
    require_gui_idle(row['guiFlags'],row['menuOwner'])
    if (any(type(row[key]) is not int or row[key]<=0 for key in
            ('foreground','root','focus','focusRoot','rootPid','focusPid','focusTid','layout','session'))
            or row['foreground']!=row['root'] or row['focusRoot']!=row['root'] or row['rootClass']!='Tauri Window'
            or row['focusClass'] not in ('Tauri Window','Chrome_RenderWidgetHostHWND','Chrome_WidgetWin_0','Chrome_WidgetWin_1')
            or row['visible'] is not True or row['enabled'] is not True or row['desktop']!='Default'):
        raise AssertionError('Input target is not the actual owned interactive editor')
    for pid in (row['rootPid'],row['focusPid']):
        record=processes.get(pid)
        if (not isinstance(record,dict) or record.get('pid')!=pid or type(record.get('creation')) is not int
                or record['creation']<=0 or record.get('session')!=row['session']):
            raise AssertionError('Input target process handle/session is not held')
    if language is not None and (type(language) is not int or row['layout']&0xffff!=language):
        raise AssertionError('Actual focused input thread has another language layout')
    return dict(row)

SCANS=dict(zip('qwertyuiopasdfghjklzxcvbnm',
               (0x10,0x11,0x12,0x13,0x14,0x15,0x16,0x17,0x18,0x19,0x1e,0x1f,0x20,0x21,0x22,0x23,
                0x24,0x25,0x26,0x2c,0x2d,0x2e,0x2f,0x30,0x31,0x32)))
SCANS.update({'SPACE':0x39,'ESCAPE':0x01,'ENTER':0x1c,'TAB':0x0f,'BACKSPACE':0x0e,'CTRL':0x1d,'SHIFT':0x2a,
              'ALT':0x38,'WIN':0xe05b,'LEFT':0xe04b,'RIGHT':0xe04d,'HOME':0xe047,'END':0xe04f,'DELETE':0xe053})

def scancode_sequence(keys):
    if not isinstance(keys,(list,tuple)) or not 1<=len(keys)<=512:raise ValueError('OS keyboard sequence exceeds its bound')
    result=[]
    for chord in keys:
        if not isinstance(chord,str):raise ValueError('OS keyboard token must be explicit')
        parts=chord.split('+')
        if not 1<=len(parts)<=3 or len(set(parts))!=len(parts):raise ValueError('Invalid bounded OS chord')
        down=[]
        for token in parts:
            if len(token)==1 and token.isascii() and token.isupper():
                if len(parts)==1:
                    down.append({'scan':SCANS['SHIFT'],'vk':0,'extended':False,'up':False,'unicode':False})
                token=token.lower()
            if token=='HANGUL':row={'scan':0,'vk':0x15,'extended':False,'up':False,'unicode':False}
            else:
                scan=SCANS.get(token)
                if scan is None:raise ValueError('Unsupported OS scan-code token')
                row={'scan':scan&0xff,'vk':0,'extended':scan>0xff,'up':False,'unicode':False}
            down.append(row)
        result.extend(down);result.extend({**row,'up':True} for row in reversed(down))
    return result

def inspect_composition(events,expected):
    if not isinstance(events,list) or not 3<=len(events)<=256 or not isinstance(expected,str) or not 0<len(expected)<=256:
        raise AssertionError('Missing bounded actual composition receipt')
    composing=False;updates=0;commits=[]
    for row in events:
        if not isinstance(row,dict) or row.get('isTrusted') is not True or not isinstance(row.get('data'),str) or len(row['data'])>256:
            raise AssertionError('Synthetic or oversized composition observation')
        kind=row.get('type')
        if kind=='compositionstart':
            if composing:raise AssertionError('Composition started twice without ending')
            composing=True
        elif kind=='compositionupdate':
            if not composing:raise AssertionError('Composition update has no actual start')
            updates+=1
        elif kind=='compositionend':
            if not composing:raise AssertionError('Composition ended without a start')
            composing=False;commits.append(row['data'])
        elif kind not in ('beforeinput','input'):raise AssertionError('Unexpected composition event')
    if composing or not updates or ''.join(commits)!=expected:raise AssertionError('Actual composition commit is missing or differs')
    return {'committed':''.join(commits),'compositions':len(commits),'updates':updates,'events':len(events)}

def inspect_cancelled_composition(events):
    if not isinstance(events,list) or not 3<=len(events)<=256:
        raise AssertionError('Missing actual OS cancellation events')
    active=False;updated=False;cancelled=False
    for row in events:
        if not isinstance(row,dict) or row.get('isTrusted') is not True or not isinstance(row.get('data'),str) or len(row['data'])>256:
            raise AssertionError('Synthetic or unbounded cancellation event')
        kind=row.get('type')
        if kind=='compositionstart':
            if active or cancelled:raise AssertionError('Unexpected additional cancellation transaction')
            active=True
        elif kind=='compositionupdate':
            if not active:raise AssertionError('Cancellation has no live composition')
            updated=True
        elif kind=='compositionend':
            if not active or not updated or row['data']!='':raise AssertionError('IME committed instead of cancelling')
            active=False;cancelled=True
        elif kind in ('beforeinput','input'):
            if cancelled and row['data']:raise AssertionError('Ghost input followed cancelled IME composition')
        else:raise AssertionError('Unexpected cancellation event')
    if active or not cancelled:raise AssertionError('Actual composition never cancelled')
    return {'cancelled':True,'committed':'','events':len(events)}

def require_korean_prerequisites(record):
    if (not isinstance(record,dict) or record.get('koreanLanguageConfigured') is not True
            or record.get('os',{}).get('koreanBasicState')!='Installed'
            or not isinstance(record.get('layouts'),list)
            or not any(type(value) is int and value&0xffff==0x0412 for value in record['layouts'])):
        raise AssertionError('Actual Korean OS language/capability/layout is missing or unknown')
    return True

def require_microsoft_profile(record):
    if (not isinstance(record,dict) or type(record.get('layout')) is not int or record['layout']&0xffff!=0x0412
            or record.get('isIme') is not True or record.get('underSystemDirectory') is not True
            or not isinstance(record.get('fileName'),str) or not record['fileName'].lower().endswith(('.ime','.dll'))
            or not re.fullmatch('[0-9a-f]{64}',record.get('fileSha256',''))
            or record.get('signatureStatus')!='Valid' or not isinstance(record.get('signerSubject'),str)
            or not re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)',record['signerSubject'])):
        raise AssertionError('Actual Korean Microsoft IME file/profile identity is unverified')
    return dict(record)

def inspect_live_composition(events,expected):
    """Actual trusted public event receipt; no external process HIMC access."""
    if not isinstance(events,list) or not 2<=len(events)<=256 or not isinstance(expected,str) or not 0<len(expected)<=256:
        raise AssertionError('Missing bounded actual live composition receipt')
    active=False;pending=None;committed=[]
    for row in events:
        if not isinstance(row,dict) or row.get('isTrusted') is not True or not isinstance(row.get('data'),str) or len(row['data'])>256:
            raise AssertionError('Synthetic or unbounded live composition observation')
        kind=row.get('type')
        if kind=='compositionstart':
            if active:raise AssertionError('Live composition started twice')
            active=True;pending=None
        elif kind=='compositionupdate':
            if not active:raise AssertionError('Live update has no actual composition start')
            pending=row['data']
        elif kind=='compositionend':
            if not active:raise AssertionError('Composition end has no actual start')
            active=False;pending=None;committed.append(row['data'])
        elif kind not in ('beforeinput','input'):raise AssertionError('Unexpected live composition event')
    if not active or not pending or ''.join(committed)+pending!=expected:
        raise AssertionError('Actual trusted pending composition is missing or differs')
    return {'pending':pending,'committed':''.join(committed),'events':len(events)}


def inspect_mode_probe(events,body_text):
    """Initial mode established by real physical gks+RIGHT and exact saved XML.

Never treats delivery of an unsupported getter, event absence, or capability
inventory as an English-mode observation. Both recognized results require
trusted OS-originating input and a separate exact saved-document body oracle.
"""
    if not isinstance(events,list) or not 1<=len(events)<=256 or body_text not in ('gks','한'):
        raise AssertionError('Actual initial keyboard mode is missing or unknown')
    for row in events:
        if (not isinstance(row,dict) or row.get('isTrusted') is not True
                or row.get('type') not in ('compositionstart','compositionupdate','compositionend','beforeinput','input')
                or not isinstance(row.get('data'),str) or len(row['data'])>256):
            raise AssertionError('Initial mode probe has synthetic/unbounded input')
    if body_text=='한':
        observation=inspect_composition(events,'한')
        if observation['compositions']!=1:raise AssertionError('Initial native mode has an unexpected composition boundary')
        native=True
    else:
        if any(row['type'].startswith('composition') for row in events):
            raise AssertionError('Saved ASCII conflicts with initial native composition events')
        inserted=[row for row in events if row['type']=='input']
        if (not inserted or any(row.get('inputType')!='insertText' for row in inserted)
                or ''.join(row['data'] for row in inserted)!='gks'):
            raise AssertionError('ASCII mode has no exact trusted real-key input receipt')
        observation={'committed':'gks','events':len(events)};native=False
    return {'native':native,'savedBody':body_text,'inspection':observation,
            'modeEvidence':'physical gks+RIGHT, trusted events, independent saved-body XML',
            'sourceQualified':False}


def actual_source_binding(source_root):
    if os.name!='nt':raise ValueError('Actual Windows native input is required')
    root=Path(source_root).resolve()
    result=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,timeout=10)
    if result.returncode:raise ValueError('Native input needs the actual Source checkout')
    return validate_hosted_binding(os.environ,result.stdout.strip(),platform=os.name)


class WindowsKeyboard:
    """Bind held native processes and focus thread before genuine OS key input."""
    def __init__(self,root_hwnd,app_pid,app_handle,runtime,source_root,*,owner_scope=None):
        if os.name!='nt':raise ValueError('Actual Windows keyboard input requires Windows')
        self.binding=actual_source_binding(source_root)
        self.owner_scope=owner_scope
        if owner_scope is not None and (getattr(owner_scope,'hwnd',None)!=root_hwnd or getattr(owner_scope,'page',None) is None):
            raise AssertionError('IME owner scope is not the provided bound page/HWND')
        from print_focus import WindowsFocusProbe,_bind_native_print_processes
        self.probe=WindowsFocusProbe();self.root_hwnd=root_hwnd;self.app_pid=app_pid
        self.processes,self.bind=_bind_native_print_processes(self.probe,app_pid,app_pid,runtime,app_handle)
        self.root_record=self.probe.window(root_hwnd)
        if (self.root_record['root']!=root_hwnd or self.root_record['pid']!=app_pid
                or self.root_record['cls']!='Tauri Window'):
            self.probe.close();raise AssertionError('Keyboard root is not the held native editor')
        self.user=self.probe.user;self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        class GuiThreadInfo(ctypes.Structure):
            _fields_=[('cbSize',W.DWORD),('flags',W.DWORD),('hwndActive',W.HWND),('hwndFocus',W.HWND),
                      ('hwndCapture',W.HWND),('hwndMenuOwner',W.HWND),('hwndMoveSize',W.HWND),('hwndCaret',W.HWND),('rcCaret',W.RECT)]
        self.GuiThreadInfo=GuiThreadInfo
        for name,args,result in (
            ('GetGUIThreadInfo',[W.DWORD,ctypes.POINTER(GuiThreadInfo)],W.BOOL),
            ('GetKeyboardLayout',[W.DWORD],W.HKL),('GetKeyboardLayoutList',[ctypes.c_int,ctypes.POINTER(W.HKL)],ctypes.c_int),
            ('GetThreadDesktop',[W.DWORD],W.HANDLE),('OpenInputDesktop',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE),
            ('CloseDesktop',[W.HANDLE],W.BOOL),
            ('GetUserObjectInformationW',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD)],W.BOOL)):
            function=getattr(self.user,name);function.argtypes=args;function.restype=result
        class KeyboardInput(ctypes.Structure):
            _fields_=[('wVk',W.WORD),('wScan',W.WORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',ctypes.c_size_t)]
        class MouseInput(ctypes.Structure):
            _fields_=[('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',ctypes.c_size_t)]
        class HardwareInput(ctypes.Structure):
            _fields_=[('uMsg',W.DWORD),('wParamL',W.WORD),('wParamH',W.WORD)]
        class Payload(ctypes.Union):_fields_=[('ki',KeyboardInput),('mi',MouseInput),('hi',HardwareInput)]
        class Input(ctypes.Structure):_fields_=[('type',W.DWORD),('payload',Payload)]
        self.Input=Input;self.KeyboardInput=KeyboardInput
        self.user.SendInput.argtypes=[W.UINT,ctypes.POINTER(Input),ctypes.c_int];self.user.SendInput.restype=W.UINT
        self.entries=[];self.last_observation=None
    def _desktop_name(self,handle):
        name=ctypes.create_unicode_buffer(128);needed=W.DWORD()
        if not handle or not self.user.GetUserObjectInformationW(handle,2,name,ctypes.sizeof(name),ctypes.byref(needed)):
            raise AssertionError('Actual input desktop could not be read')
        return name.value
    def _desktop(self,tid):
        input_desktop=self.user.OpenInputDesktop(0,False,1)
        if not input_desktop:raise AssertionError('Actual interactive input desktop is unavailable')
        try:
            active=self._desktop_name(input_desktop);target=self._desktop_name(self.user.GetThreadDesktop(tid))
            if active!=target:raise AssertionError('Owned input thread belongs to another desktop')
            return active
        finally:self.user.CloseDesktop(input_desktop)
    def snapshot(self):
        for pid,record in tuple(self.processes.items()):self.probe.verify_process(pid,record)
        root=self.probe.window(self.root_hwnd)
        if root!=self.root_record:raise AssertionError('Held keyboard root HWND changed')
        info=self.GuiThreadInfo();info.cbSize=ctypes.sizeof(info)
        if not self.user.GetGUIThreadInfo(0,ctypes.byref(info)) or not info.hwndFocus:
            raise AssertionError('Actual foreground input thread has no focus HWND')
        focus=self.probe.window(int(info.hwndFocus));self.bind(focus['pid'])
        # Cross-queue focus must bind the real input HWND/thread, not only app root.
        actual=self.GuiThreadInfo();actual.cbSize=ctypes.sizeof(actual)
        if not self.user.GetGUIThreadInfo(focus['tid'],ctypes.byref(actual)) or int(actual.hwndFocus or 0)!=focus['hwnd']:
            raise AssertionError('Focused input thread HWND changed during observation')
        layout=int(self.user.GetKeyboardLayout(focus['tid']) or 0)
        row={'foreground':self.probe.foreground(),'root':self.root_hwnd,'focus':focus['hwnd'],
                'focusRoot':focus['root'],'rootPid':root['pid'],'focusPid':focus['pid'],'focusTid':focus['tid'],
                'rootClass':root['cls'],'focusClass':focus['cls'],'visible':focus['visible'] and root['visible'],
                'enabled':focus['enabled'] and root['enabled'],'layout':layout,
                'session':self.processes[focus['pid']]['session'],'desktop':self._desktop(focus['tid']),
                'guiFlags':int(info.flags|actual.flags),
                'menuOwner':int(info.hwndMenuOwner or actual.hwndMenuOwner or 0)}
        self.last_observation=row
        return row
    def ready(self,*,language=None):
        # The owner helper's prepare() clicks the caret. Never call it here:
        # selection and live composition must survive these read-only checks.
        first_scope=self.owner_scope._ready() if self.owner_scope is not None else None
        first=self.snapshot()
        if self.owner_scope is not None:
            if not self.owner_scope.page.evaluate('''()=>{
                const node=document.activeElement;
                return node?.tagName==='TEXTAREA' && node.getAttribute('aria-label')==='문서 편집 입력';
            }'''):
                raise AssertionError('Bound public editor textarea is not the OS input target')
            if self.owner_scope._ready()!=first_scope:raise AssertionError('Bound page/HWND focus changed before OS input')
        return require_focus(first,self.snapshot(),self.processes,language=language)
    def send(self,keys,*,language=None):
        sequence=scancode_sequence(keys)
        before=self.ready(language=language)  # Exactly two live matching observations.
        values=(self.Input*len(sequence))()
        for index,row in enumerate(sequence):
            flags=(0x0002 if row['up'] else 0)|(0x0001 if row['extended'] else 0)|(0x0008 if row['scan'] else 0)
            values[index].type=1;values[index].payload.ki=self.KeyboardInput(row['vk'],row['scan'],flags,0,0)
        sent=int(self.user.SendInput(len(values),values,ctypes.sizeof(self.Input)))
        receipt={'source':self.binding,'input':'Windows SendInput; no Unicode packet','before':before,
                 'requestedEvents':len(values),'sentEvents':sent,'foregroundAfter':self.probe.foreground(),
                 'sourceQualified':False,'productTelemetry':False}
        self.entries.append(receipt)
        if sent!=len(values):
            # Release only our keys that reached key-down before an incomplete SendInput.
            pending={}
            for row in sequence[:sent]:
                key=(row['vk'],row['scan'],row['extended'])
                if row['up']:pending.pop(key,None)
                else:pending[key]=row
            releases=(self.Input*len(pending))()
            for index,row in enumerate(pending.values()):
                flags=0x2|(0x1 if row['extended'] else 0)|(0x8 if row['scan'] else 0)
                releases[index].type=1;releases[index].payload.ki=self.KeyboardInput(row['vk'],row['scan'],flags,0,0)
            if len(releases):receipt['releasedEvents']=int(self.user.SendInput(len(releases),releases,ctypes.sizeof(self.Input)))
            raise OSError('SendInput did not insert every declared OS key event')
        return receipt
    def layouts(self):
        count=self.user.GetKeyboardLayoutList(0,None)
        if not 1<=count<=64:raise AssertionError('Installed keyboard layout inventory is unavailable')
        values=(W.HKL*count)()
        if self.user.GetKeyboardLayoutList(count,values)!=count:raise AssertionError('Keyboard layout inventory changed')
        return [int(value or 0) for value in values]
    def prerequisites(self):
        """Read only. Missing Korean capability/profiles remains not-ready, never skip/PASS."""
        command="$ErrorActionPreference='Stop'; $cap=Get-WindowsCapability -Online -Name 'Language.Basic~~~ko-KR~0.0.1.0'; [ordered]@{ koreanBasicState=[string]$cap.State; languages=@(Get-WinUserLanguageList | ForEach-Object { [ordered]@{ tag=[string]$_.LanguageTag; inputMethodTips=@($_.InputMethodTips) } }); osBuild=[Environment]::OSVersion.Version.ToString() } | ConvertTo-Json -Depth 5 -Compress"
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                              capture_output=True,text=True,timeout=30)
        if result.returncode or len(result.stdout.encode('utf-8'))>16384:
            raise RuntimeError('Actual Korean IME prerequisite inventory could not be read')
        data=json.loads(result.stdout)
        languages=data.get('languages',[])
        if not isinstance(languages,list) or len(languages)>64:raise ValueError('Invalid OS input language inventory')
        tips=[tip for row in languages for tip in row.get('inputMethodTips',[]) if isinstance(tip,str)]
        layouts=self.layouts();focus=self.ready()
        ready=(data.get('koreanBasicState')=='Installed' and any(tip.startswith('0412:') for tip in tips)
               and any(layout&0xffff==0x0412 for layout in layouts))
        return {'source':self.binding,'os':data,'layouts':layouts,'ownedFocus':focus,
                'koreanLanguageConfigured':ready,'microsoftImeIdentityVerified':False,
                'compositionObserved':False,'sourceQualified':False}
    def close(self):self.probe.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


class CompositionObserver:
    """Read-only public DOM events; no event dispatch, input insertion or product hook."""
    def __init__(self,page,keyboard):
        keyboard.ready();self.page=page;self.keyboard=keyboard;self.key='__OpenGeulOwnedComposition_'+uuid.uuid4().hex
        page.evaluate('''(key) => {
          const area=document.querySelector('textarea[aria-label="문서 편집 입력"]');
          if(!area || document.activeElement!==area) throw Error('Owned public editor input is not focused');
          const receipt={events:[],overflow:false};
          const observe=e=>{
            const data=typeof e.data==='string'?e.data:'';
            if(receipt.events.length>=256 || data.length>256){receipt.overflow=true;return;}
            receipt.events.push({type:e.type,isTrusted:e.isTrusted,data,inputType:e.inputType??null,
              isComposing:e.isComposing??null,time:performance.now()});
          };
          const types=['compositionstart','compositionupdate','compositionend','beforeinput','input'];
          for(const type of types) area.addEventListener(type,observe,true);
          Object.defineProperty(window,key,{configurable:true,value:{area,receipt,observe,types}});
        }''',self.key)
    def read(self):
        payload=self.page.evaluate('''key=>{
          const value=window[key];if(!value)throw Error('Composition observer disappeared');
          return {events:value.receipt.events,overflow:value.receipt.overflow};
        }''',self.key)
        if not isinstance(payload,dict) or payload.get('overflow') is not False:
            raise AssertionError('Composition event evidence was truncated')
        return payload['events']
    def commit(self,expected):
        events=self.read();return {'source':self.keyboard.binding,'focus':self.keyboard.ready(),
                                  'events':events,'inspection':inspect_composition(events,expected),'sourceQualified':False}
    def close(self):
        self.page.evaluate('''key=>{
          const value=window[key];if(!value)return;
          for(const type of value.types)value.area.removeEventListener(type,value.observe,true);
          delete window[key];
        }''',self.key)


class MicrosoftKoreanIme:
    """Actual installed Microsoft IMM profile identity and physical Hangul key.

Unknown TSF-only profiles without an observable IMM identity fail closed. This
backend does not claim to enumerate or validate every Windows input method.
"""
    def __init__(self,keyboard):
        if os.name!='nt':raise ValueError('Actual Windows IME profile is required')
        self.keyboard=keyboard;self.imm=ctypes.WinDLL('imm32',use_last_error=True);self.records=[]
        for name,args,result in (
            ('ImmIsIME',[W.HKL],W.BOOL),('ImmGetIMEFileNameW',[W.HKL,W.LPWSTR,W.UINT],W.UINT),
            ('ImmGetDescriptionW',[W.HKL,W.LPWSTR,W.UINT],W.UINT)):
            function=getattr(self.imm,name);function.argtypes=args;function.restype=result
        self.keyboard.kernel.GetSystemWindowsDirectoryW.argtypes=[W.LPWSTR,W.UINT]
        self.keyboard.kernel.GetSystemWindowsDirectoryW.restype=W.UINT
        self.keyboard.kernel.GetSystemDirectoryW.argtypes=[W.LPWSTR,W.UINT]
        self.keyboard.kernel.GetSystemDirectoryW.restype=W.UINT
    def _profile(self,layout):
        if not self.imm.ImmIsIME(layout):raise AssertionError('Focused Korean layout has no observable IMM IME identity')
        name=ctypes.create_unicode_buffer(1024);description=ctypes.create_unicode_buffer(256)
        count=int(self.imm.ImmGetIMEFileNameW(layout,name,len(name)))
        if not 0<count<len(name)-1:raise AssertionError('Actual IME profile file name is unavailable')
        filename=name.value;self.imm.ImmGetDescriptionW(layout,description,len(description))
        windows=ctypes.create_unicode_buffer(32768);system=ctypes.create_unicode_buffer(32768)
        if (not 0<self.keyboard.kernel.GetSystemWindowsDirectoryW(windows,len(windows))<len(windows)
                or not 0<self.keyboard.kernel.GetSystemDirectoryW(system,len(system))<len(system)):
            raise AssertionError('Actual Windows system directory is unavailable')
        system_root=Path(system.value).resolve();raw=Path(filename)
        candidates=[raw] if raw.is_absolute() else [system_root/raw]
        # IMKR.IME on supported Windows can reside in System32/IME/IMEKR.
        if not raw.is_absolute():candidates.append(system_root/'IME'/'IMEKR'/raw)
        actual=[path.resolve() for path in candidates if path.is_file() and not path.is_symlink()]
        if len(set(actual))!=1:raise AssertionError('IME file resolution is absent or ambiguous')
        path=actual[0]
        if not path.is_relative_to(system_root) or not 0<path.stat().st_size<=64*1024*1024:
            raise AssertionError('Actual IME file is outside the protected OS system directory')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        literal="'"+str(path).replace("'","''")+"'"
        command="$ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -LiteralPath "+literal+"; [ordered]@{ status=[string]$s.Status; subject=[string]$s.SignerCertificate.Subject } | ConvertTo-Json -Compress"
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=20)
        if result.returncode or len(result.stdout.encode('utf-8'))>8192:raise AssertionError('Actual IME Microsoft signature could not be verified')
        signature=json.loads(result.stdout)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise AssertionError('Actual IME file changed during signature verification')
        row={'layout':layout,'isIme':True,'underSystemDirectory':True,'fileName':path.name,'systemFile':str(path),
             'fileSha256':digest,'signatureStatus':signature.get('status'),'signerSubject':signature.get('subject'),
             'description':description.value,'profileBackend':'actual IMM HKL/file identity','sourceQualified':False}
        return require_microsoft_profile(row)
    def active_profile(self):
        before=self.keyboard.ready(language=0x0412);profile=self._profile(before['layout'])
        if self.keyboard.ready(language=0x0412)!=before:raise AssertionError('Actual focused IME profile changed during attestation')
        row={'source':self.keyboard.binding,'focus':before,'profile':profile,'sourceQualified':False}
        self.records.append({'operation':'active-Microsoft-profile',**row});return row
    def select_installed_profile(self):
        candidates=[]
        for layout in self.keyboard.layouts():
            if layout&0xffff==0x0412 and self.imm.ImmIsIME(layout):
                candidates.append(self._profile(layout))
        if len(candidates)!=1:raise AssertionError('Exactly one observable installed Microsoft Korean IME is required')
        chosen=candidates[0];before=self.keyboard.ready();result=ctypes.c_size_t()
        if before['layout']!=chosen['layout']:
            # Official Windows input-language request, not product IPC or an IME
            # composition message. It selects only an already installed profile.
            returned=self.keyboard.user.SendMessageTimeoutW(before['focus'],0x50,0,ctypes.c_ssize_t(chosen['layout']).value,
                                                             0x3,1000,ctypes.byref(result))
            if not returned:raise OSError('Actual Windows input-language request did not complete')
        self.records.append({'operation':'installed-Windows-input-language-selection','before':before,
                             'requestedLayout':chosen['layout'],'sourceQualified':False})
        return chosen
    def toggle_mode(self):
        # Send only a genuine OS Hangul key. This receipt is a request, not proof
        # of resulting mode: following trusted composition / saved-body output
        # must independently prove that the requested switch took effect.
        receipt=self.keyboard.send(['HANGUL'],language=0x0412)
        row={'operation':'real-OS-Hangul-mode-key','OSKeys':receipt,
             'modeResultVerified':False,'sourceQualified':False}
        self.records.append(row);return row
