"""Production UI automation. No app test APIs, IPC mocks or private document corpus."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect
from native_controls import filename_control
from webview_debug import MachineRegistry, ScopedDebugOverride, debug_arguments
from native_architecture import verify_executable, verify_host, verify_process, verify_webview2, require_architecture


def until(check, timeout=25, *, pump=None):
    deadline=time.monotonic()+timeout
    error=None
    while time.monotonic()<deadline:
        try:
            value=check()
            if value: return value
        except (OSError, ValueError, AssertionError) as exc: error=exc
        (pump(.1) if pump else time.sleep(.1))
    raise AssertionError(f'Condition timed out after {timeout}s; last error: {error}')

def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def menu(page, command: str, *, category='file'):
    page.locator(f'[data-menu="{category}"] > .menu-title').click()
    page.locator(f'.md-item[data-cmd="{command}"]').click()

def primary_modifier(page):
    # WebKit on Linux reports a macOS browser identity; use the UI platform, not runner OS.
    mac=page.evaluate("/mac/i.test(navigator.platform) || /mac os/i.test(navigator.userAgent)")
    return 'Meta' if mac else 'Control'

def edit(page, text: str):
    area=page.locator('textarea').first
    area.wait_for(state='attached')
    area.focus()
    page.keyboard.press('Meta+ArrowDown' if primary_modifier(page)=='Meta' else 'Control+End')
    # Committed Unicode input, NOT the Windows OS IME composition engine.
    page.keyboard.insert_text(text)

class Session:
    def __init__(self, mode: str, folder: Path, fixture: Path|None, *, executable: Path|None=None, browser='chromium', url='http://127.0.0.1:7700'):
        self.mode=mode; self.folder=folder; folder.mkdir(parents=True,exist_ok=True)
        self.executable=executable; self.proc=None; self.browser=None; self.context=None; self.page=None
        self.messages=[]; self.requests=[]; self.dialogs=[]; self.errors=[]
        self.profile=None; self.log=None; self.debug_override=None; self.pw=sync_playwright().start()
        try:
            if mode=='native':
                if os.name != 'nt' or executable is None: raise RuntimeError('Native E2E needs Windows and the production executable')
                architecture=require_architecture(os.environ.get('E2E_ARCHITECTURE','x64'))
                verify_executable(executable,architecture)
                verify_host(architecture)
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
                env=dict(os.environ)
                env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=debug_arguments(port)
                self.profile=Path(tempfile.mkdtemp(prefix='opengeul-e2e-profile-'))
                env['WEBVIEW2_USER_DATA_FOLDER']=str(self.profile)
                if ctypes.windll.shell32.IsUserAnAdmin():
                    self.debug_override=ScopedDebugOverride(MachineRegistry(), executable.name, port, str(self.profile),
                        runner=os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted')
                    self.debug_override.__enter__()
                self.log=(folder/'process.log').open('w',encoding='utf-8')
                arguments=[str(executable)] + ([str(fixture)] if fixture else [])
                self.proc=subprocess.Popen(arguments,cwd=executable.parent,env=env,stdout=self.log,stderr=subprocess.STDOUT)
                self.native_architecture=verify_process(self.proc.pid,executable,architecture,handle=int(self.proc._handle))
                endpoint=f'http://127.0.0.1:{port}'
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def ready():
                    if self.proc.poll() is not None: raise RuntimeError(f'App exited: {self.proc.returncode}')
                    try:
                        with opener.open(endpoint+'/json/version',timeout=1) as response:
                            return bool(json.load(response).get('webSocketDebuggerUrl'))
                    except OSError: return False
                until(ready,60)
                self.browser=self.pw.chromium.connect_over_cdp(endpoint)
                self.context=self.browser.contexts[0]
                self.page=next((p for p in self.context.pages if not p.is_closed()),None)
                if self.page is None:
                    self.page=self.context.wait_for_event('page',timeout=30000)
            else:
                self.browser=getattr(self.pw,browser).launch(headless=True)
                self.context=self.browser.new_context(accept_downloads=True, viewport={'width':1280,'height':900})
                self.context.add_init_script("Object.defineProperty(window, 'showSaveFilePicker', {value: undefined, configurable: true});")
                self.page=self.context.new_page()
            # Disable resource capture so traces cannot redistribute installed fonts.
            self.context.tracing.start(screenshots=True,snapshots=False,sources=False)
            self.page.set_default_timeout(15000)
            self.page.on('console',lambda message:self.messages.append({'type':message.type,'text':message.text}))
            self.page.on('pageerror',lambda error:self.errors.append(str(error)))
            self.page.on('request',lambda request:self.requests.append(request.url))
            def dialog_handler(dialog):
                self.dialogs.append({'type':dialog.type,'message':dialog.message}); dialog.accept()
            self.page.on('dialog',dialog_handler)
            if mode!='native':
                self.page.goto(url,wait_until='domcontentloaded')
                expect(self.page.locator('#sb-message')).to_contain_text('HWP 파일을 선택',timeout=60000)
                if fixture: self.page.locator('#file-input').set_input_files(str(fixture))
            if fixture is None:
                expect(self.page.locator('#sb-message')).to_contain_text('HWP 파일을 선택',timeout=60000)
                menu(self.page,'file:new-doc')
            self.wait_loaded(fixture.name if fixture else '새 문서.hwp')
            runtime={'mode':mode,'browser':self.browser.version,
                'executableSha256':digest(executable) if executable else None,'fixtureSha256':digest(fixture) if fixture else None,
                'navigator':self.page.evaluate('({platform:navigator.platform,userAgent:navigator.userAgent})')}
            if mode=='native':
                runtime['nativeArchitecture']=self.native_architecture
                runtime['webview2Native']=verify_webview2(self.proc.pid,architecture)
            (folder/'runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf-8')
        except BaseException:
            self.close()
            raise

    def wait_loaded(self, name):
        self.page.wait_for_function('(name) => document.querySelector("#sb-message")?.textContent.includes(name)',arg=name,timeout=60000)
        # The filename is displayed before await canvasView.loadDocument().
        # Wait for observable editing readiness rather than adding an arbitrary delay.
        expect(self.page.locator('#style-bar')).to_have_css('pointer-events','auto',timeout=60000)
        self.page.locator('textarea[aria-label="문서 편집 입력"]').wait_for(state='attached')

    def open_public(self, path: Path):
        """실제 파일 메뉴/선택기로 같은 제품 session의 문서를 교체한다."""
        if self.mode == 'native':
            menu(self.page, 'file:open')
            self.native_dialog(path)
        else:
            with self.page.expect_file_chooser() as event:
                menu(self.page, 'file:open')
            event.value.set_files(str(path))
        self.wait_loaded(path.name)

    def pick_image(self, path: Path):
        with self.page.expect_file_chooser() as event:
            menu(self.page, 'insert:image', category='insert')
        event.value.set_files(str(path))
        # Production canvas cursor is the observable completion of decoding.
        self.page.wait_for_function('getComputedStyle(document.querySelector("#scroll-container")).cursor === "crosshair"')

    def place_image(self, *, dimensions_mm=(40, 20)):
        canvas = self.page.locator('canvas.document-page-canvas').first
        canvas.scroll_into_view_if_needed()
        box = canvas.bounding_box()
        if not box or min(box['width'], box['height']) <= 0:
            raise AssertionError('No actual production page bounds')
        x, y = box['x'] + box['width']*.35, box['y'] + box['height']*.45
        width, height = box['width']*dimensions_mm[0]/210, box['height']*dimensions_mm[1]/297
        target = {'x': x, 'y': y, 'right': x+width, 'bottom': y+height}
        if y+height >= self.page.evaluate('window.innerHeight'):
            raise AssertionError('Image placement does not fit the observed viewport')
        hit = self.page.evaluate('''(p) => {
          const canvas = document.querySelector('canvas.document-page-canvas');
          return [document.elementFromPoint(p.x, p.y), document.elementFromPoint(p.right, p.bottom)]
            .every(node => node === canvas);
        }''', target)
        if not hit:
            raise AssertionError('Image drag points are covered or miss the actual production page canvas')
        target['publicDomHitMatched'] = True
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        try:
            self.page.mouse.move(x+width, y+height, steps=12)
        finally:
            self.page.mouse.up()
        return target

    def native_keys(self, keys):
        """검증된 native HWND에 실제 Windows keyboard input을 한 번 보낸다."""
        if self.mode != 'native' or os.name != 'nt':
            raise ValueError('OS clipboard keyboard needs actual Windows native UI')
        from pywinauto import Desktop, keyboard
        from print_focus import WindowsFocusProbe, _bind_native_print_processes
        runtime = json.loads((self.folder/'runtime.json').read_text())
        windows = [w for w in Desktop(backend='win32').windows(process=self.proc.pid)
                   if w.is_visible() and w.is_enabled() and w.class_name() in ('Tauri Window', 'Chrome_WidgetWin_1')]
        if len(windows) != 1:
            raise AssertionError('Expected exactly one owned native editor input window')
        window = windows[0]
        probe = WindowsFocusProbe()
        try:
            processes, _ = _bind_native_print_processes(probe, self.proc.pid, self.proc.pid, runtime, int(self.proc._handle))
            initial = probe.window(window.handle)
            if initial['root'] != window.handle or initial['pid'] != self.proc.pid:
                raise AssertionError('Native keyboard HWND is not the owned editor')
            window.set_focus()
            for pid, record in processes.items():
                probe.verify_process(pid, record)
            if probe.foreground() != window.handle or probe.window(window.handle) != initial:
                raise AssertionError('Native editor lost ownership/focus before keyboard input')
            keyboard.send_keys(keys, pause=.02, vk_packet=False)
        finally:
            probe.close()

    def os_clipboard_text(self):
        if self.mode != 'native' or os.name != 'nt':
            raise ValueError('Actual OS clipboard read requires Windows native UI')
        user, kernel = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
        from ctypes import wintypes
        user.OpenClipboard.argtypes = [wintypes.HWND]; user.OpenClipboard.restype = wintypes.BOOL
        user.GetClipboardData.argtypes = [wintypes.UINT]; user.GetClipboardData.restype = wintypes.HANDLE
        kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]; kernel.GlobalLock.restype = ctypes.c_void_p
        kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        if not user.OpenClipboard(None):
            raise AssertionError('Actual Windows clipboard could not be opened')
        try:
            handle = user.GetClipboardData(13)  # CF_UNICODETEXT; no synthetic ClipboardEvent.
            if not handle:
                raise AssertionError('Windows clipboard has no copied Unicode text')
            address = kernel.GlobalLock(handle)
            if not address:
                raise AssertionError('Actual Windows clipboard text could not be read')
            try:
                return ctypes.wstring_at(address)
            finally:
                kernel.GlobalUnlock(handle)
        finally:
            user.CloseClipboard()

    def export_pdf(self, target: Path, *, cancel=False):
        if self.mode != 'native':
            raise ValueError('GUI PDF export is a native desktop feature')
        menu(self.page, 'file:export-pdf')
        self.native_dialog(target, cancel=cancel)
        if cancel:
            # Closing the picker is cancellation input completion. Only the
            # caller's subsequent actual save/export success proves lock release.
            return None
        # Viewer failure is a separate native predicate. A written PDF still has
        # to pass the independent PDFium/raster oracle in the caller.
        from pywinauto import Desktop
        def completed():
            message = self.page.locator('#sb-message').inner_text()
            if 'PDF 내보내기 완료' in message:
                return {'saved': True, 'viewerOpened': True}
            if '파일은 저장됐지만 OS 기본 앱으로 열 수 없습니다' in message:
                # The production command reports this rejected native invocation
                # through status + a real JS alert; Session records/accepts it.
                alerts = [row for row in self.dialogs if row['type'] == 'alert'
                          and '파일은 저장됐지만 OS 기본 앱으로 열 수 없습니다' in row['message']]
                if alerts and target.is_file():
                    return {'saved': True, 'viewerOpened': False, 'viewerError': message}
            dialogs = [w for w in Desktop(backend='win32').windows(process=self.proc.pid, class_name='#32770') if w.is_visible()]
            if dialogs:
                from native_controls import bind_dialog
                dialog = bind_dialog(Desktop(backend='win32'), self.proc.pid)
                accessible = Desktop(backend='uia').window(handle=dialog.handle)
                detail = '\n'.join(c.window_text() for c in accessible.descendants(control_type='Text') if c.window_text())
                if '파일은 저장됐지만 OS 기본 앱으로 열 수 없습니다' not in detail:
                    raise AssertionError('GUI PDF export failed: '+detail)
                if not target.is_file():
                    raise AssertionError('Viewer failure did not leave a real saved PDF')
                buttons = [c for c in dialog.descendants(class_name='Button') if c.is_visible() and c.is_enabled()
                           and c.window_text().replace('&', '').strip() in ('OK', '확인')]
                if len(buttons) != 1:
                    raise AssertionError('Expected one owned PDF viewer-error confirmation')
                dialog.set_focus(); buttons[0].click_input(); dialog.wait_not('visible', timeout=20)
                return {'saved': True, 'viewerOpened': False, 'viewerError': detail}
            return False
        return until(completed, timeout=60, pump=lambda n: self.page.wait_for_timeout(n*1000))

    def wait_open_failure(self):
        """실제 DnD의 공개 status/native 오류를 관측하고 소유 modal만 닫는다."""
        if self.mode != 'native':
            raise ValueError('Native file-drop failure observation requires native UI')
        from pywinauto import Desktop
        def failed():
            dialogs = [w for w in Desktop(backend='win32').windows(process=self.proc.pid, class_name='#32770') if w.is_visible()]
            if dialogs:
                from native_controls import dismiss_error_dialog
                message = dismiss_error_dialog(self.proc.pid)
                self.dialogs.append({'type': 'native-error', 'message': message})
            status = self.page.locator('#sb-message').inner_text()
            return status if '파일 열기 실패' in status or '파일 로드 실패' in status else False
        return until(failed, timeout=30, pump=lambda n: self.page.wait_for_timeout(n*1000))

    def explorer_drop(self, path: Path):
        """소유 Explorer window의 실제 항목을 물리적으로 제품 HWND에 끌어놓는다."""
        if self.mode != 'native' or os.name != 'nt' or not path.is_file():
            raise ValueError('Explorer drag/drop needs an actual owned Windows file')
        from pywinauto import Desktop, mouse
        from print_focus import WindowsFocusProbe, _bind_native_print_processes
        shell_script = '''$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$shell = New-Object -ComObject Shell.Application
$rows = @($shell.Windows() | ForEach-Object {
  try { [pscustomobject]@{ hwnd=[long]$_.HWND; path=$_.Document.Folder.Self.Path;
    selected=@($_.Document.SelectedItems() | ForEach-Object { $_.Path }) } } catch {}
})
ConvertTo-Json -InputObject $rows -Depth 4 -Compress'''
        def shell_windows():
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', shell_script],
                                    capture_output=True, text=True, encoding='utf-8-sig', timeout=15)
            if result.returncode:
                raise AssertionError('Cannot observe actual Explorer folder ownership')
            rows = json.loads(result.stdout or '[]')
            return rows if isinstance(rows, list) else [rows]
        before = {row['hwnd'] for row in shell_windows()}
        # A fresh owned folder prevents accidental selection of a preexisting window.
        if any(Path(row['path']).resolve() == path.parent.resolve() for row in shell_windows()):
            raise AssertionError('Owned DnD fixture folder is already open in Explorer')
        subprocess.Popen(['explorer.exe', '/n,', str(path.parent)])
        owned = None
        probe = WindowsFocusProbe()
        try:
            def observed():
                rows = [row for row in shell_windows() if row['hwnd'] not in before
                        and Path(row['path']).resolve() == path.parent.resolve()]
                if len(rows) > 1:
                    raise AssertionError('Ambiguous owned Explorer window')
                return rows[0] if rows else False
            owned = until(observed)
            explorer = Desktop(backend='uia').window(handle=owned['hwnd']).wrapper_object()
            explorer_native = Desktop(backend='win32').window(handle=owned['hwnd']).wrapper_object()
            actual = probe.process.inspect(explorer.process_id())
            if Path(actual['imagePath']).name.lower() != 'explorer.exe':
                raise AssertionError('DnD folder is not an actual Explorer process')
            architecture = self.native_architecture['architecture']
            explorer_proof = verify_process(explorer.process_id(), Path(actual['imagePath']), architecture)
            probe.architecture = architecture
            explorer_record = probe.bind_process(explorer.process_id(), explorer_proof)
            runtime = json.loads((self.folder/'runtime.json').read_text())
            app_windows = [w for w in Desktop(backend='win32').windows(process=self.proc.pid)
                           if w.is_visible() and w.class_name() in ('Tauri Window', 'Chrome_WidgetWin_1')]
            if len(app_windows) != 1:
                raise AssertionError('DnD target must be one owned native editor window')
            app = app_windows[0]
            processes, bind = _bind_native_print_processes(probe, self.proc.pid, self.proc.pid, runtime, int(self.proc._handle))
            app.set_focus()
            box = self.page.locator('#editor-area').bounding_box()
            ratio = self.page.evaluate('window.devicePixelRatio')
            if not box or not isinstance(ratio, (int, float)) or ratio <= 0:
                raise AssertionError('No observed production editor drop bounds')
            origin = app.client_to_screen((0, 0))
            target = (round(origin[0]+(box['x']+box['width']*.5)*ratio),
                      round(origin[1]+(box['y']+box['height']*.55)*ratio))
            # Move only the newly owned window away from the target point.
            explorer_native.move_window(x=0, y=0, width=max(350, target[0]-40), height=max(300, target[1]-40))
            explorer_native.set_focus()
            from uia_snapshot import snapshot_descendants
            items = [item for item in snapshot_descendants(explorer, control_type='ListItem') if item.is_visible()
                     and item.window_text() in (path.name, path.stem)]
            if len(items) != 1:
                raise AssertionError('Owned Explorer file is not exactly one visible native item')
            item = items[0]; item.click_input()
            selected = observed()
            if not selected or selected.get('selected') != [str(path.resolve())]:
                raise AssertionError('Explorer selection is not the exact owned fixture path')
            rect = item.rectangle()
            start = (round((rect.left+rect.right)/2), round((rect.top+rect.bottom)/2))
            source_window = probe.window(probe.hit(start))
            target_window = probe.window(probe.hit(target))
            bind(target_window['pid'])
            if source_window['root'] != explorer.handle or source_window['pid'] != explorer.process_id() or target_window['root'] != app.handle:
                raise AssertionError('Real DnD input points do not hit owned Explorer/editor HWNDs')
            probe.verify_process(explorer.process_id(), explorer_record)
            for pid, record in processes.items():
                probe.verify_process(pid, record)
            if observed() != selected or probe.foreground() != explorer.handle or probe.window(probe.hit(start)) != source_window or probe.window(probe.hit(target)) != target_window:
                raise AssertionError('Owned drag/drop bindings changed before actual input')
            mouse.press(coords=start)
            try:
                for index in range(1, 21):
                    mouse.move(coords=(round(start[0]+(target[0]-start[0])*index/20),
                                       round(start[1]+(target[1]-start[1])*index/20)), duration=.025)
            finally:
                mouse.release(coords=target)
            record = {'explorerHwnd': explorer.handle, 'explorerPid': explorer.process_id(),
                      'folder': str(path.parent.resolve()), 'selectedPath': str(path.resolve()),
                      'appHwnd': app.handle, 'appPid': self.proc.pid, 'editorBounds': box,
                      'devicePixelRatio': ratio, 'sourcePoint': start, 'dropPoint': target,
                      'actualPhysicalDrag': True}
            (self.folder/f'explorer-drop-{path.stem}.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
            return record
        finally:
            try:
                if owned:
                    rows = [row for row in shell_windows() if row['hwnd'] == owned['hwnd']
                            and Path(row['path']).resolve() == path.parent.resolve()]
                    if len(rows) != 1:
                        raise AssertionError('Owned Explorer path/window changed before cleanup')
                    # Close this window only; Explorer may share a system process.
                    Desktop(backend='win32').window(handle=owned['hwnd']).close()
            finally:
                probe.close()

    def native_dialog(self, target: Path|None, *, cancel=False):
        from pywinauto import Desktop
        from pywinauto.controls.hwndwrapper import InvalidWindowHandle
        # UIA can omit these shell dialogs on hosted desktops. Pin the exact HWND:
        # an invalid-file open can replace the file picker immediately with another
        # #32770 error dialog, and a dynamic WindowSpecification would mistake that
        # replacement for the original picker still being visible.
        spec=Desktop(backend='win32').window(class_name='#32770',process=self.proc.pid)
        spec.wait('visible',timeout=20)
        dialog=spec.wrapper_object();hwnd=dialog.handle
        if dialog.process_id()!=self.proc.pid or dialog.class_name()!='#32770':
            raise AssertionError('Native dialog ownership changed before binding')
        if target is not None:
            # Visibility can precede shell control creation; keep this exact HWND.
            try:
                user32=ctypes.windll.user32
                def identity():
                    pid=ctypes.c_uint32();name=ctypes.create_unicode_buffer(256)
                    thread=user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if (dialog.handle!=hwnd or not user32.IsWindow(hwnd)
                            or not user32.IsWindowVisible(hwnd) or not user32.IsWindowEnabled(hwnd)
                            or not thread or pid.value!=self.proc.pid
                            or not user32.GetClassNameW(hwnd,name,len(name)) or name.value!='#32770'):
                        raise RuntimeError('Native filename dialog ownership changed')
                    return thread
                bound_thread=identity()
                def filename_ready():
                    if identity()!=bound_thread:
                        raise RuntimeError('Native filename dialog thread changed')
                    try:
                        controls=dialog.descendants()
                    except InvalidWindowHandle as exc:
                        # pywinauto 0.6.9 stores this HWND only in its fixed message.
                        match=re.fullmatch(r'Handle ([1-9][0-9]*) is not a vaild window handle',str(exc))
                        if (not match or int(match[1])==hwnd or user32.IsWindow(int(match[1]))):
                            raise
                        try:
                            unchanged=identity()==bound_thread
                        except RuntimeError:
                            raise exc
                        if not unchanged:
                            raise
                        return False
                    if identity()!=bound_thread:
                        raise RuntimeError('Native filename dialog thread changed')
                    selected=filename_control(controls)
                    if identity()!=bound_thread:
                        raise RuntimeError('Native filename dialog thread changed')
                    return selected
                control=until(filename_ready,timeout=20)
            except Exception:
                self._record_picker_readiness_failure(dialog,hwnd)
                raise
            control.set_edit_text(str(target))
            if identity()!=bound_thread or control.window_text()!=str(target):
                raise AssertionError('Native filename changed before the requested dialog action')
        buttons=[item for item in dialog.descendants(class_name='Button')
                 if item.control_id()==(2 if cancel or target is None else 1)
                 and item.is_visible() and item.is_enabled()]
        if len(buttons)!=1:
            raise AssertionError(f'Expected one native dialog action; found {len(buttons)}')
        dialog.set_focus();buttons[0].click_input()
        until(lambda: not ctypes.windll.user32.IsWindow(hwnd)
              or not ctypes.windll.user32.IsWindowVisible(hwnd),timeout=20)

    def _record_picker_readiness_failure(self, dialog, hwnd):
        """Failure-only control metadata; never read filename or descendant text."""
        try:
            if (dialog.handle!=hwnd or dialog.process_id()!=self.proc.pid
                    or dialog.class_name()!='#32770'):
                return
            title=dialog.window_text()
            value={'hwnd':hwnd,'pid':self.proc.pid,'class':'#32770','title':title[:256],
                   'descendants':[],'titleTruncated':len(title)>256,'descendantsTruncated':False,
                   'classNamesTruncated':False,'sizeTruncated':False,'collectionFailed':False}
            try:
                controls=dialog.descendants()
                value['descendantsTruncated']=len(controls)>64
            except Exception:
                controls=[]
                value['collectionFailed']=True
            for control in controls[:64]:
                try:
                    name=control.class_name();parent=control.parent().class_name()
                    record={'class':name[:64],'parentClass':parent[:64],
                            'controlId':int(control.control_id()),'visible':bool(control.is_visible()),
                            'enabled':bool(control.is_enabled())}
                    value['classNamesTruncated'] |= len(name)>64 or len(parent)>64
                except Exception:
                    value['collectionFailed']=True
                    continue
                value['descendants'].append(record)
                if len(json.dumps(value,ensure_ascii=True,separators=(',',':')).encode('ascii'))>16*1024:
                    value['descendants'].pop()
                    value['descendantsTruncated']=True
                    value['sizeTruncated']=True
                    break
            data=json.dumps(value,ensure_ascii=True,separators=(',',':')).encode('ascii')
            if len(data)<=16*1024:
                (self.folder/'native-picker-readiness.json').write_bytes(data)
        except Exception:
            # Diagnostic collection or writing must not replace the readiness error.
            pass

    def save(self, source: Path, output: Path, *, save_as=False, cancel=False) -> Path|None:
        command='file:save-as' if save_as else 'file:save'
        if self.mode=='native':
            menu(self.page,command)
            if save_as:
                self.native_dialog(None if cancel else output)
                if cancel:
                    # The native HWND can disappear before the bridge releases its guard.
                    expect(self.page.locator('#sb-message')).to_have_text('다른 이름으로 저장 취소',timeout=30000)
                    return None
            result=output if save_as else source
            expect(self.page.locator('#sb-message')).to_contain_text('저장 완료',timeout=30000)
            self.page.wait_for_function('!document.title.startsWith("• ")',timeout=30000)
            until(lambda: result.is_file())
            return result
        if save_as or cancel: raise ValueError('Browser suite uses existing-document direct downloads; native suite owns Save As dialogs')
        with self.page.expect_download(timeout=30000) as event:
            menu(self.page,command)
        download=event.value
        if not download.suggested_filename.lower().endswith('.hwpx'):
            raise AssertionError(f'Expected genuine HWPX download, got {download.suggested_filename}')
        download.save_as(str(output))
        return output

    def close(self):
        # Cleanup must also run when startup, evidence capture or process teardown fails.
        try:
            if self.page:
                try:self.page.screenshot(path=str(self.folder/'last-screen.png'),timeout=3000)
                except Exception:pass
            if self.context:
                try:self.context.tracing.stop(path=str(self.folder/'trace.zip'))
                except Exception:pass
            (self.folder/'events.json').write_text(json.dumps({'console':self.messages[-200:],'requests':self.requests[-300:],
                'dialogs':self.dialogs,'errors':self.errors},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            try:
                if self.browser:
                    try:self.browser.close()
                    except Exception:pass
                if self.proc and self.proc.poll() is None:
                    try:subprocess.run(['taskkill','/PID',str(self.proc.pid),'/T','/F'],capture_output=True,timeout=20)
                    finally:
                        if self.proc.poll() is None:self.proc.kill()
                        self.proc.wait(timeout=10)
            finally:
                try:
                    if self.log:self.log.close()
                    try:self.pw.stop()
                    except Exception:pass
                finally:
                    try:
                        if self.debug_override:self.debug_override.close()
                    finally:
                        if self.profile:shutil.rmtree(self.profile,ignore_errors=True)
