"""Bounded investigation of the real system print dialog on disposable runners."""
import sys,time,json,subprocess,os
from pathlib import Path
from driver import Session
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab
import win32print

if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
    raise RuntimeError('Probe is restricted to disposable Windows runners')
root=Path('evidence').resolve();root.mkdir(exist_ok=True)
name='OpenGeul-CI-'+os.environ['GITHUB_RUN_ID']
subprocess.run(['pwsh','-NoProfile','-Command',"$ErrorActionPreference='Stop'; if(Get-Printer -Name $env:OG_PRINT_QUEUE -ErrorAction SilentlyContinue){throw 'Queue collision'}; Add-Printer -Name $env:OG_PRINT_QUEUE -DriverName 'Microsoft Print To PDF' -PortName 'PORTPROMPT:' -KeepPrintedJobs"],env={**os.environ,'OG_PRINT_QUEUE':name},check=True,timeout=30)
session=None
try:
    session=Session('native',root/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
    print('READY',session.proc.pid,flush=True)
    windows=Desktop(backend='win32').windows(process=session.proc.pid,visible_only=True)
    windows[0].set_focus();send_keys('^p');time.sleep(3);send_keys('^+p');time.sleep(3)
    rows=[]
    for w in Desktop(backend='win32').windows():
        if not w.is_visible():continue
        row={'title':w.window_text(),'class':w.class_name(),'pid':w.process_id(),'hwnd':w.handle,'children':[]}
        if w.class_name()=='#32770' or w.process_id()==session.proc.pid:
            row['children']=[{'title':c.window_text(),'class':c.class_name(),'id':c.control_id(),'visible':c.is_visible()} for c in w.descendants()][:250]
        rows.append(row)
    (root/'system-windows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False),flush=True)
    ImageGrab.grab().save(root/'system-dialog.png')
finally:
    if session:
        subprocess.run(['taskkill','/PID',str(session.proc.pid),'/T','/F'],capture_output=True,timeout=15)
        session.close()
    handle=win32print.OpenPrinter(name,{'DesiredAccess':win32print.PRINTER_ALL_ACCESS})
    try:win32print.DeletePrinter(handle)
    finally:win32print.ClosePrinter(handle)
