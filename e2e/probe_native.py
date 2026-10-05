"""Disposable runner diagnostic; not imported by the production app."""
import ctypes, json, os, pathlib, socket, subprocess, tempfile, time, traceback, urllib.request, winreg
from playwright.sync_api import sync_playwright, expect
from pywinauto import Desktop
from PIL import ImageGrab
assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Runner-only diagnostic'
out=pathlib.Path('evidence');out.mkdir(exist_ok=True)
fixture=(pathlib.Path('inputs/fixtures/e2e-fixtures/basic.hwpx')).resolve()
exe=pathlib.Path('runtime/OpenGeul.exe').resolve()
profile=tempfile.mkdtemp(prefix='opengeul-native-diagnostic-')
with socket.socket() as s:
    s.bind(('127.0.0.1',0));port=s.getsockname()[1]
args=f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={port}'
env=dict(os.environ);env['WEBVIEW2_USER_DATA_FOLDER']=profile;env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=args
# Runtime 150+ ignores user/environment overrides in elevated processes.
# Use the documented app-specific HKLM override ONLY on this disposable runner;
# never alter a pre-existing value, wildcard, security policy or application binary.
keys=[];proc=None;log=None
try:
    print('ELEVATED',bool(ctypes.windll.shell32.IsUserAnAdmin()))
    if ctypes.windll.shell32.IsUserAnAdmin():
        for category,value in [('AdditionalBrowserArguments',args),('UserDataFolder',profile)]:
            path='SOFTWARE\\Policies\\Microsoft\\Edge\\WebView2\\'+category
            key=winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE,path,0,winreg.KEY_READ|winreg.KEY_SET_VALUE|winreg.KEY_WOW64_64KEY)
            try:
                try:winreg.QueryValueEx(key,'OpenGeul.exe')
                except FileNotFoundError:pass
                else:raise RuntimeError('Refusing to overwrite existing OpenGeul debug configuration')
                winreg.SetValueEx(key,'OpenGeul.exe',0,winreg.REG_SZ,value)
                keys.append(path)
            finally:winreg.CloseKey(key)
    log=(out/'process.log').open('w',encoding='utf-8')
    proc=subprocess.Popen([str(exe),str(fixture)],cwd=exe.parent,env=env,stdout=log,stderr=subprocess.STDOUT)
    def snapshot(name):
        ImageGrab.grab(all_screens=True).save(out/f'{name}.png')
        data=[{'handle':w.handle,'class':w.class_name(),'title':w.window_text(),'visible':w.is_visible()} for w in Desktop(backend='win32').windows(visible_only=False) if w.process_id()==proc.pid]
        print(name,json.dumps(data));(out/f'{name}-windows.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    endpoint=f'http://127.0.0.1:{port}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+60
    while True:
        if proc.poll() is not None:raise RuntimeError(f'App exited {proc.returncode}')
        try:
            with opener.open(endpoint+'/json/version',timeout=1) as r:info=json.load(r)
            if info.get('webSocketDebuggerUrl'):break
        except OSError:pass
        if time.monotonic()>deadline:snapshot('startup-timeout');raise RuntimeError('CDP timeout')
        time.sleep(.1)
    print('CDP_READY',info.get('Browser'))
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint);ctx=browser.contexts[0]
        page=ctx.pages[0] if ctx.pages else ctx.wait_for_event('page',timeout=30000)
        page.wait_for_function('(name)=>document.querySelector("#sb-message")?.textContent.includes(name)',arg=fixture.name,timeout=60000)
        expect(page.locator('#style-bar')).to_have_css('pointer-events','auto',timeout=60000)
        page.locator('[data-menu="file"] > .menu-title').click();page.locator('.md-item[data-cmd="file:save-as"]').click()
        dialog=Desktop(backend='win32').window(class_name='#32770',process=proc.pid)
        dialog.wait('visible',timeout=20)
        dialog.print_control_identifiers(depth=5)
        snapshot('save-as')
        dialog.child_window(control_id=2,class_name='Button').click()
        dialog.wait_not('visible',timeout=20)
        print('SAVE_AS_CANCELLED')
        with ctx.expect_page(timeout=20000) as event:
            page.locator('[data-menu="file"] > .menu-title').click();page.locator('.md-item[data-cmd="file:new-window"]').click()
        new=event.value
        expect(new.locator('#studio-root')).to_be_visible(timeout=30000)
        print('NEW_WINDOW_READY',len(ctx.pages))
        snapshot('finished');browser.close()
except Exception:
    traceback.print_exc()
    if proc:
        try:snapshot('failure')
        except Exception:pass
    raise
finally:
    if proc:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=20)
    if log:log.close()
    for path in reversed(keys):
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,path,0,winreg.KEY_SET_VALUE|winreg.KEY_WOW64_64KEY) as key:
            winreg.DeleteValue(key,'OpenGeul.exe')
    import shutil
    shutil.rmtree(profile,ignore_errors=True)
