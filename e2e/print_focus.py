"""Native print input and observable shell-control readiness, with no click retries."""
from __future__ import annotations
import json
import time
from pathlib import Path

from pywinauto import Desktop


def _safe(call, default=None):
    try:
        return call()
    except Exception:
        return default


def _rect(control):
    rect = _safe(lambda: control.rectangle())
    return None if rect is None else [rect.left, rect.top, rect.right, rect.bottom]


def _node(control):
    info = getattr(control, 'element_info', None)
    return {
        'name': _safe(lambda: control.window_text(), ''),
        'type': getattr(info, 'control_type', None),
        'visible': bool(_safe(lambda: control.is_visible(), False)),
        'enabled': bool(_safe(lambda: control.is_enabled(), False)),
        'pid': _safe(lambda: control.process_id()),
        'handle': getattr(control, 'handle', None),
        'automationId': getattr(info, 'automation_id', None),
        'className': _safe(lambda: control.class_name(), ''),
        'rect': _rect(control),
    }


def _write_evidence(folder: Path | None, payload):
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'print-accessibility.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n',
        encoding='utf-8',
    )


def _owned_pids(app_pid: int):
    import psutil
    try:
        return {app_pid, *(p.pid for p in psutil.Process(app_pid).children(recursive=True))}
    except psutil.Error:
        return {app_pid}


def _runtime_id(control):
    value=tuple(control.element_info.element.GetRuntimeId())
    if not value or len(value)>64 or any(type(item) is not int for item in value):
        raise AssertionError('Print UIA runtime identity is unavailable')
    return value


class WindowsFocusProbe:
    """Only query held owned processes and focus an explicitly bound native HWND."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes as W
        from native_architecture import WindowsProbe
        self.ctypes=ctypes;self.W=W;self.process=WindowsProbe();self.handles={}
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        for name,args,result in [('IsWindow',[W.HWND],W.BOOL),('IsWindowVisible',[W.HWND],W.BOOL),
                ('IsWindowEnabled',[W.HWND],W.BOOL),('GetAncestor',[W.HWND,W.UINT],W.HWND),
                ('GetWindow',[W.HWND,W.UINT],W.HWND),('GetForegroundWindow',[],W.HWND),
                ('SetForegroundWindow',[W.HWND],W.BOOL),('WindowFromPoint',[W.POINT],W.HWND),
                ('GetWindowThreadProcessId',[W.HWND,ctypes.POINTER(W.DWORD)],W.DWORD),
                ('GetClassNameW',[W.HWND,W.LPWSTR,ctypes.c_int],ctypes.c_int)]:
            function=getattr(self.user,name);function.argtypes=args;function.restype=result
        self.process.api.GetProcessTimes.argtypes=[W.HANDLE,*[ctypes.POINTER(W.FILETIME)]*4]
        self.process.api.GetProcessTimes.restype=W.BOOL
        self.process.api.ProcessIdToSessionId.argtypes=[W.DWORD,ctypes.POINTER(W.DWORD)]
        self.process.api.ProcessIdToSessionId.restype=W.BOOL

    def _times_session(self,pid,handle):
        times=[self.W.FILETIME() for _ in range(4)];session=self.W.DWORD();controller=self.W.DWORD()
        if not self.process.api.GetProcessTimes(handle,*[self.ctypes.byref(item) for item in times]):
            raise AssertionError('Owned print process creation time is unavailable')
        import os
        if (not self.process.api.ProcessIdToSessionId(pid,self.ctypes.byref(session))
                or not self.process.api.ProcessIdToSessionId(os.getpid(),self.ctypes.byref(controller))
                or session.value!=controller.value):
            raise AssertionError('Owned print process is in another Windows session')
        return {'pid':pid,'creation':times[0].dwHighDateTime<<32|times[0].dwLowDateTime,'session':session.value}

    def bind_process(self,pid,expected,handle=None):
        from native_architecture import verify_process
        if pid in self.handles:return self.handles[pid][2]
        parent=expected.get('parentProcessId')
        if parent is not None and parent not in self.handles:
            raise AssertionError('Current owned WebView parent process changed')
        own=handle is None
        if own:handle=self.process.api.OpenProcess(0x1000,False,pid)
        if not handle:raise AssertionError('Owned print process handle is unavailable')
        try:
            actual=verify_process(pid,Path(expected['imagePath']),expected.get('architecture',self.architecture),
                                  handle=handle,probe=self.process)
            if (not actual['runningAtInspection'] or actual['sha256']!=expected['sha256']
                    or actual['bytes']!=expected['bytes'] or actual['processMachine']!=0):
                raise AssertionError('Owned print process runtime identity changed')
            record=self._times_session(pid,handle)
            if parent is not None:
                # The child is held before this snapshot. A live held child cannot
                # be substituted by PID reuse while its actual ancestry is read.
                rows=self.process.processes();parents={row['processId']:row['parentProcessId'] for row in rows}
                if len(parents)!=len(rows) or parents.get(pid)!=parent:
                    raise AssertionError('Current owned WebView parent process changed')
                parent_record=self.handles[parent][2]
                self.verify_process(parent,parent_record)
                current=self.process.inspect(pid,handle)
                if current['exitCode']!=259 or self._times_session(pid,handle)!=record:
                    raise AssertionError('Held WebView changed during its parent snapshot')
                if record['creation']<parent_record['creation']:
                    raise AssertionError('Owned WebView predates its held parent process')
                record['parentProcessId']=parent
            self.handles[pid]=(handle,own,record,actual)
            return record
        except BaseException:
            if own:self.process.api.CloseHandle(handle)
            raise

    def verify_process(self,pid,expected):
        handle,_,_,bound=self.handles[pid];actual=self.process.inspect(pid,handle)
        if (actual['exitCode']!=259 or actual['processMachine']!=0
                or actual['nativeMachine']!=bound['nativeMachine']
                or Path(actual['imagePath']).resolve()!=Path(bound['imagePath']).resolve()
                or self._times_session(pid,handle)!={k:expected[k] for k in ('pid','creation','session')}):
            raise AssertionError('Owned print process identity changed')

    def window(self,hwnd):
        pid=self.W.DWORD();name=self.ctypes.create_unicode_buffer(129)
        tid=self.user.GetWindowThreadProcessId(hwnd,self.ctypes.byref(pid))
        length=self.user.GetClassNameW(hwnd,name,len(name))
        if not self.user.IsWindow(hwnd) or not tid or not length or length>=len(name)-1:
            raise AssertionError('Bound print native window disappeared')
        root=int(self.user.GetAncestor(hwnd,2) or 0);owners=[];current=root
        for _ in range(8):
            current=int(self.user.GetWindow(current,4) or 0)
            if not current:break
            if current in owners:raise AssertionError('Print native owner chain contains a cycle')
            owners.append(current)
        else:raise AssertionError('Print native owner chain exceeds its bound')
        return {'hwnd':hwnd,'pid':pid.value,'tid':tid,'cls':name.value,
                'visible':bool(self.user.IsWindowVisible(hwnd)),'enabled':bool(self.user.IsWindowEnabled(hwnd)),
                'root':root,'owners':owners}

    def foreground(self):return int(self.user.GetForegroundWindow() or 0)
    def set_foreground(self,hwnd):return bool(self.user.SetForegroundWindow(hwnd))
    def hit(self,point):return int(self.user.WindowFromPoint(self.W.POINT(*point)) or 0)
    def focused(self):
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo
        from pywinauto.controls.uiawrapper import UIAWrapper
        element=IUIA().iuia.GetFocusedElement()
        return UIAWrapper(UIAElementInfo(element)) if element else None
    def close(self):
        for handle,own,_,_ in self.handles.values():
            if own:self.process.api.CloseHandle(handle)
        self.handles.clear()


class OwnedPreviewFocus:
    """One foreground/focus preparation before input; popup-open checks only read."""
    def __init__(self,preview,app_hwnd,app_pid,runtime,*,probe=None,app_handle=None,evidence_dir=None):
        self.preview=preview;self.app_hwnd=app_hwnd;self.app_pid=app_pid
        self.probe=probe or WindowsFocusProbe();self.processes={};self.windows={};self.entries=[]
        self.evidence_dir=evidence_dir;self.preview_id=None;self.expected={};self.last_chain=[]
        self.stage='preview-runtime-id'
        try:
            self.preview_id=_runtime_id(preview)
            self.stage='runtime-process-identities'
            app=runtime['nativeArchitecture'];web=runtime['webview2Native']
            self.expected={app_pid:app};self.probe.architecture=app.get('architecture')
            if app['processId']!=app_pid or web['rootProcessId']!=app_pid or app_handle is None:
                raise AssertionError('Print focus needs the actual owned app process handle')
            for row in web['processes']:
                if row['processId'] in self.expected:raise AssertionError('Duplicate owned print process identity')
                self.expected[row['processId']]=row
            for pid in self.expected:
                seen=set();current=pid
                while current!=app_pid:
                    if current in seen or current not in self.expected:raise AssertionError('Foreign print WebView parent chain')
                    seen.add(current);current=self.expected[current]['parentProcessId']
            self.stage='app-held-process';self.processes[app_pid]=self.probe.bind_process(app_pid,app,app_handle)
            self.stage='app-native-window'
            app_window=self._window(app_hwnd,ready=False)
            if app_window['pid']!=app_pid or app_window['cls']!='Tauri Window' or app_window['root']!=app_hwnd:
                raise AssertionError('Print focus root is not the exact owned app')
            self.windows[app_hwnd]=app_window
            self.stage='preview-uia-ancestor';chain=self._chain(preview);self.preview_chain=chain
            native=next((row for row in chain if row['hwnd']),None)
            if native is None:raise AssertionError('Print preview has no proven native UIA ancestor')
            self.stage='preview-native-window'
            self.native_ancestor=native['hwnd'];self.preview_window=self._window(self.native_ancestor)['root']
            self.windows[self.native_ancestor]=self._window(self.native_ancestor)
            self.windows[self.preview_window]=self._window(self.preview_window)
            if not self._related(self.windows[self.preview_window]):raise AssertionError('Print preview native owner chain is foreign')
            self.stage='bound-preview-recheck';self._live(preview,require_foreground=False)
            self._record({'phase':'bound','operation':'read-only-binding','foreground':self.probe.foreground(),'passed':True})
        except BaseException as error:
            self._record({'phase':'binding-failed','stage':self.stage,'errorType':type(error).__name__[:64]})
            self.close();raise

    def _chain(self,control):
        rows=[];seen=set();self.last_chain=rows
        for _ in range(16):
            if control is None:return rows
            rid=_runtime_id(control)
            if rid in seen:raise AssertionError('Print UIA ancestor cycle')
            seen.add(rid);pid=control.process_id()
            rows.append({'runtimeId':rid,'pid':pid,'hwnd':int(getattr(control,'handle',None) or 0)})
            if pid not in self.expected:raise AssertionError('Foreign print UIA provider')
            self._process(pid)
            if rows[-1]['hwnd'] and self.preview_id in [row['runtimeId'] for row in rows]:return rows
            control=control.parent()
        raise AssertionError('Print UIA ancestor chain exceeds its bound')

    def _process(self,pid):
        if pid not in self.expected:raise AssertionError('Foreign print native process')
        if pid not in self.processes:
            parent=self.expected[pid]['parentProcessId'];self._process(parent)
            actual=self.probe.bind_process(pid,self.expected[pid])
            if actual.get('parentProcessId')!=parent or actual['creation']<self.processes[parent]['creation']:
                raise AssertionError('Current WebView ancestry is not the held owned app chain')
            self.processes[pid]=actual
        self.probe.verify_process(pid,self.processes[pid])

    def _window(self,hwnd,*,ready=True):
        row=self.probe.window(hwnd);self._process(row['pid'])
        if ready and (not row['visible'] or not row['enabled']):raise AssertionError('Owned print window is not ready')
        return row

    def _related(self,row):
        if row['root']==self.app_hwnd:return True
        if self.app_hwnd in row['owners']:return True
        return row['pid']==self.preview.process_id()

    def _live(self,control,*,require_foreground=True):
        if (_runtime_id(self.preview)!=self.preview_id or self.preview.window_text()!='Print'
                or self.preview.class_name()!='RootView'):
            raise AssertionError('Print preview root retargeted')
        for hwnd,original in self.windows.items():
            if self._window(hwnd,ready=hwnd!=self.app_hwnd or hwnd==self.preview_window)!=original:
                raise AssertionError('Bound print native HWND identity changed')
        chain=self._chain(control)
        if self.preview_id not in [row['runtimeId'] for row in chain]:raise AssertionError('Print target is outside the exact preview')
        first=next((row for row in chain if row['hwnd']),None)
        if first is None:raise AssertionError('Print target has no native ancestor')
        target=self._window(first['hwnd']);top=self._window(target['root'])
        if top['hwnd']!=self.preview_window and self.preview_window not in top['owners']:
            raise AssertionError('Print popup has no explicit owned native owner chain')
        foreground=self.probe.foreground()
        if require_foreground and foreground!=self.preview_window and foreground!=top['hwnd']:
            raise AssertionError('Print foreground is not the exact preview or its bound popup')
        return chain,top

    def _record(self,entry):
        if len(self.entries)<64:self.entries.append(entry)
        else:self.entries[-1]=entry
        if self.evidence_dir is not None:
            payload={'kind':'diagnostic-metadata','previewRuntimeId':self.preview_id,
                     'previewAncestorChain':getattr(self,'preview_chain',[]),
                     'lastPartialAncestorChain':self.last_chain,
                     'processes':list(self.processes.values()),'windows':list(self.windows.values()),'observations':self.entries,
                     'runtimeIdentities':[{'pid':pid,**{key:row.get(key) for key in
                         ('sha256','bytes','peMachine','processMachine','nativeMachine')}} for pid,row in self.expected.items()
                         if pid in self.processes],
                     'productTelemetry':False,'sourceQualified':False}
            data=json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode('ascii')
            if len(data)<=32*1024:
                try:(self.evidence_dir/'print-focus-diagnostic.json').write_bytes(data)
                except OSError:pass

    def prepare(self,control,phase):
        entry={'phase':phase,'operation':'prepare-before-input','foregroundBefore':self.probe.foreground()}
        try:
            # Binding precedes the one activation attempt; actual foreground is never fabricated.
            self._live(control,require_foreground=False)
            if entry['foregroundBefore']!=self.preview_window:
                entry['setForegroundReturned']=self.probe.set_foreground(self.preview_window)
                if not entry['setForegroundReturned']:raise AssertionError('Owned print foreground request failed')
            if self.probe.foreground()!=self.preview_window:raise AssertionError('Owned print foreground was not observed')
            control.element_info.element.SetFocus()
            focused=self.probe.focused()
            if focused is None or _runtime_id(control) not in [row['runtimeId'] for row in self._chain(focused)]:
                raise AssertionError('Actual keyboard focus is outside the print target')
            self._live(control);entry['passed']=True
        finally:
            entry['foregroundAfter']=self.probe.foreground();self._record(entry)

    def check(self,control,phase,*,physical=False):
        entry={'phase':phase,'operation':'read-only-guard','foreground':self.probe.foreground()}
        try:
            chain,top=self._live(control)
            if physical:
                if not control.is_visible() or not control.is_enabled():raise AssertionError('Print choice is not ready')
                rect=control.rectangle();point=((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
                if rect.right<=rect.left or rect.bottom<=rect.top or any(type(n) is not int or not -2**31<=n<2**31 for n in point):
                    raise AssertionError('Print choice physical rectangle is invalid')
                hit=self._window(self.probe.hit(point));hit_top=self._window(hit['root'])
                if hit_top['hwnd']!=top['hwnd']:raise AssertionError('Print choice point belongs to another native window')
                entry['point']=point;entry['hitHwnd']=hit['hwnd']
            entry['targetRuntimeId']=_runtime_id(control);entry['passed']=True
        finally:self._record(entry)

    def read(self,control,phase):
        """Popup-open observation never activates or changes keyboard focus."""
        entry={'phase':phase,'operation':'read-only-popup-observation','foreground':self.probe.foreground()}
        try:self._live(control,require_foreground=False);entry['passed']=True
        finally:self._record(entry)

    def close(self):self.probe.close()


def prepare_app_for_print(app_hwnd,app_pid,runtime,*,app_handle,evidence_dir=None,probe=None):
    """The initial Ctrl+P is sent only after observing the exact owned app in front."""
    api=probe or WindowsFocusProbe();entry={'kind':'diagnostic-metadata','operation':'initial-ctrl-p-focus',
        'appHwnd':app_hwnd,'appPid':app_pid,'sourceQualified':False,'productTelemetry':False}
    try:
        expected=runtime['nativeArchitecture'];api.architecture=expected.get('architecture')
        if expected['processId']!=app_pid or app_handle is None:raise AssertionError('Owned print app handle is required')
        process=api.bind_process(app_pid,expected,app_handle);window=api.window(app_hwnd)
        entry.update({'process':process,'window':window,'foregroundBefore':api.foreground()})
        if (window['pid']!=app_pid or window['cls']!='Tauri Window' or window['root']!=app_hwnd
                or not window['visible'] or not window['enabled']):
            raise AssertionError('Initial print root is not the ready owned app')
        if api.foreground()!=app_hwnd:
            entry['setForegroundReturned']=api.set_foreground(app_hwnd)
            if not entry['setForegroundReturned']:raise AssertionError('Initial owned app foreground request failed')
        if api.foreground()!=app_hwnd:raise AssertionError('Initial owned app foreground was not observed')
        api.verify_process(app_pid,process)
        if api.window(app_hwnd)!=window:raise AssertionError('Initial print HWND identity changed')
        entry['passed']=True
    except BaseException as error:
        entry['errorType']=type(error).__name__[:64];raise
    finally:
        entry['foregroundAfter']=api.foreground()
        foreground_changed=entry.get('passed') is True and entry['foregroundAfter']!=app_hwnd
        if foreground_changed:
            entry['passed']=False;entry['errorType']='AssertionError'
        if evidence_dir is not None:
            data=json.dumps(entry,ensure_ascii=True,separators=(',',':')).encode('ascii')
            if len(data)<=4096:
                try:(evidence_dir/'print-initial-focus-diagnostic.json').write_bytes(data)
                except OSError:pass
        api.close()
        if foreground_changed:raise AssertionError('Initial owned app foreground changed before print input')


def _preview_windows(desktop, app_root, app_hwnd: int, pids: set[int]):
    """Find the owned Print/RootView even when UIA exposes it as another top-level root."""
    roots = [app_root]
    try:
        roots.extend(
            window for window in desktop.windows()
            if getattr(window, 'handle', None) != app_hwnd
            and _safe(lambda w=window: w.process_id()) in pids
            and _safe(lambda w=window: w.is_visible(), False)
        )
    except Exception:
        # The application root remains authoritative if top-level enumeration is transient.
        pass

    previews = {}
    for owner in roots:
        candidates = [owner]
        try:
            candidates.extend(owner.descendants(control_type='Window'))
        except Exception:
            continue
        for candidate in candidates:
            if (
                _safe(lambda c=candidate: c.window_text(), '') == 'Print'
                and _safe(lambda c=candidate: c.class_name(), '') == 'RootView'
                and _safe(lambda c=candidate: c.process_id()) in pids
            ):
                key = _runtime_id(candidate)
                previews[key] = candidate
    return list(previews.values())


def open_system_dialog(app_hwnd: int, app_pid: int, evidence_dir: Path | None = None, *, app_handle=None):
    """Configure actual preview media, then invoke the owned system-print action once.

    Chromium preview and the Windows driver independently store media settings.
    The native accessibility action remains the same user-facing print command;
    it is not a PDF export or an application test hook. Dispatch errors escape.
    """
    from print_ui_policy import system_link
    from preview_settings import configure_preview, wait

    desktop = Desktop(backend='uia')
    root = desktop.window(handle=app_hwnd).wrapper_object()
    if root.process_id() != app_pid or root.class_name() != 'Tauri Window':
        raise AssertionError('Print action root is not the owned application')
    pids = _owned_pids(app_pid)

    def ready_preview():
        previews = _preview_windows(desktop, root, app_hwnd, pids)
        if len(previews) > 1:
            raise AssertionError('Ambiguous owned Print preview')
        if previews and any(c.window_text() == 'More settings' and c.is_enabled()
                            for c in previews[0].descendants(control_type='Button')):
            return previews[0]
        return None

    preview = wait(ready_preview)
    if evidence_dir is None:raise AssertionError('Owned print runtime evidence is required')
    runtime=json.loads((evidence_dir/'session/runtime.json').read_text(encoding='utf-8'))
    focus=OwnedPreviewFocus(preview,app_hwnd,app_pid,runtime,app_handle=app_handle,evidence_dir=evidence_dir)
    try:
        settings = configure_preview(preview, pids, evidence_dir, focus=focus)
        def ready_action():
            focus.read(preview,'system-action-read')
            controls = preview.descendants()
            index = system_link([_node(c) for c in controls], pids)
            return controls[index] if index is not None else None
        target = wait(ready_action)
        focus.prepare(target,'system-print-invoke')
        _write_evidence(evidence_dir, {
            'state': 'configured', 'appPid': app_pid, 'appHwnd': app_hwnd,
            'previewSettings': settings, 'selected': _node(target),
            'activation': 'native UIA InvokePattern (one dispatch)',
        })
        target.iface_invoke.Invoke()
    finally:focus.close()


def fill_print_output(dialog, output: Path):
    """Wait for stable real shell controls, then enter a path and click exactly once."""
    from native_controls import filename_control

    deadline = time.monotonic() + 30
    previous = None
    stable_since = 0.0
    while time.monotonic() < deadline:
        try:
            field = filename_control(dialog.descendants())
            buttons = [control for control in dialog.descendants(class_name='Button')
                       if control.control_id() == 1 and control.is_visible() and control.is_enabled()]
            if len(buttons) != 1:
                raise ValueError('Save control is not uniquely ready')
            button = buttons[0]
            rect = field.rectangle()
            current = (field.handle, button.handle, rect.left, rect.top, rect.right, rect.bottom)
        except (ValueError, OSError):
            current = None
        now = time.monotonic()
        if current is None or current != previous:
            previous = current
            stable_since = now
        elif now - stable_since >= .75:
            # Dispatch errors escape: never retry a possibly completed save action.
            field.set_edit_text(str(output))
            if field.window_text() != str(output):
                raise AssertionError('Printer output path was not accepted')
            button.click_input()
            return
        time.sleep(.1)
    raise AssertionError('Print output filename/Save controls did not stabilize')
