"""Production UI automation. No app test APIs, IPC mocks or private document corpus."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect
from native_controls import filename_control
from webview_debug import MachineRegistry, ScopedDebugOverride, debug_arguments


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

def menu(page, command: str):
    page.locator('[data-menu="file"] > .menu-title').click()
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
    def __init__(self, mode: str, folder: Path, fixture: Path, *, executable: Path|None=None, browser='chromium', url='http://127.0.0.1:7700'):
        self.mode=mode; self.folder=folder; folder.mkdir(parents=True,exist_ok=True)
        self.executable=executable; self.proc=None; self.browser=None; self.context=None; self.page=None
        self.messages=[]; self.requests=[]; self.dialogs=[]; self.errors=[]
        self.profile=None; self.log=None; self.debug_override=None; self.pw=sync_playwright().start()
        try:
            if mode=='native':
                if os.name != 'nt' or executable is None: raise RuntimeError('Native E2E needs Windows and the production executable')
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
                self.proc=subprocess.Popen([str(executable),str(fixture)],cwd=executable.parent,env=env,stdout=self.log,stderr=subprocess.STDOUT)
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
                self.page.locator('#file-input').set_input_files(str(fixture))
            self.wait_loaded(fixture.name)
            (folder/'runtime.json').write_text(json.dumps({'mode':mode,'browser':self.browser.version,
                'executableSha256':digest(executable) if executable else None,'fixtureSha256':digest(fixture),
                'navigator':self.page.evaluate('({platform:navigator.platform,userAgent:navigator.userAgent})')},indent=2),encoding='utf-8')
        except BaseException:
            self.close()
            raise

    def wait_loaded(self, name):
        self.page.wait_for_function('(name) => document.querySelector("#sb-message")?.textContent.includes(name)',arg=name,timeout=60000)
        # The filename is displayed before await canvasView.loadDocument().
        # Wait for observable editing readiness rather than adding an arbitrary delay.
        expect(self.page.locator('#style-bar')).to_have_css('pointer-events','auto',timeout=60000)
        self.page.locator('textarea[aria-label="문서 편집 입력"]').wait_for(state='attached')

    def native_dialog(self, target: Path|None):
        from pywinauto import Desktop
        # UIA can omit these shell dialogs on hosted desktops. Pin the exact HWND:
        # an invalid-file open can replace the file picker immediately with another
        # #32770 error dialog, and a dynamic WindowSpecification would mistake that
        # replacement for the original picker still being visible.
        spec=Desktop(backend='win32').window(class_name='#32770',process=self.proc.pid)
        spec.wait('visible',timeout=20)
        dialog=spec.wrapper_object();hwnd=dialog.handle
        if target is not None:
            control=filename_control(dialog.descendants())
            control.set_edit_text(str(target))
        buttons=[item for item in dialog.descendants(class_name='Button')
                 if item.control_id()==(2 if target is None else 1)
                 and item.is_visible() and item.is_enabled()]
        if len(buttons)!=1:
            raise AssertionError(f'Expected one native dialog action; found {len(buttons)}')
        dialog.set_focus();buttons[0].click_input()
        until(lambda: not ctypes.windll.user32.IsWindow(hwnd)
              or not ctypes.windll.user32.IsWindowVisible(hwnd),timeout=20)

    def save(self, source: Path, output: Path, *, save_as=False, cancel=False) -> Path|None:
        command='file:save-as' if save_as else 'file:save'
        if self.mode=='native':
            menu(self.page,command)
            if save_as:
                self.native_dialog(None if cancel else output)
                if cancel: return None
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
