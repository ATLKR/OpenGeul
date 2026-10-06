"""Inspect the real selected virtual driver's preferences; do not submit a print."""
import json,subprocess,time
from pathlib import Path
from driver import Session
from print_queue import VirtualQueue,require_host
from virtual_print import system_dialog,control,snapshot
from pywinauto import Desktop
require_host()
folder=Path('preference-evidence').resolve();folder.mkdir(exist_ok=True)
session=None
try:
    with VirtualQueue() as queue:
        info=queue.api.GetPrinter(queue.handle,2)
        dm=info['pDevMode']
        print('QUEUE DEVMODE', {k:getattr(dm,k) for k in ('PaperSize','PaperLength','PaperWidth','FormName','Orientation','Fields')},flush=True)
        session=Session('native',folder/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
        dialog=system_dialog(session,queue)
        control(dialog,'Button',1010).click_input();time.sleep(2)
        snapshot(folder)
        for window in Desktop(backend='win32').windows(class_name='#32770',visible_only=True):
            print('DIALOG',window.window_text(),flush=True)
            for c in window.descendants():
                if c.is_visible():
                    row={'title':c.window_text(),'class':c.class_name(),'id':c.control_id()}
                    if c.class_name()=='ComboBox':row['items']=c.texts()
                    print(row,flush=True)
finally:
    if session:
        subprocess.run(['taskkill','/PID',str(session.proc.pid),'/T','/F'],capture_output=True,timeout=15)
        session.close()
