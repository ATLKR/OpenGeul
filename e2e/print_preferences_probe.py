"""Inspect real driver media controls; never submit a print in this probe."""
import json,subprocess,time
from pathlib import Path
from driver import Session
from print_queue import VirtualQueue,require_host
from virtual_print import control,snapshot,wait,visible_dialog
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
require_host()
folder=Path('preference-evidence').resolve();folder.mkdir(exist_ok=True)
session=None
try:
    with VirtualQueue() as queue:
        dm=queue.api.GetPrinter(queue.handle,2)['pDevMode']
        (folder/'queue-devmode.json').write_text(json.dumps({k:getattr(dm,k) for k in ('PaperSize','PaperLength','PaperWidth','FormName','Orientation','Fields')},indent=2))
        session=Session('native',folder/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
        window=[w for w in Desktop(backend='win32').windows(process=session.proc.pid,visible_only=True) if w.class_name()=='Tauri Window'][0]
        def viewports():return {c.handle for c in window.descendants(class_name='Chrome_RenderWidgetHostHWND') if c.is_visible()}
        before=viewports();window.set_focus();send_keys('^p');wait(lambda:viewports()-before)
        send_keys('^+p');dialog=wait(lambda:visible_dialog('Print',session.proc.pid))
        printers=[c for c in dialog.descendants(class_name='SysListView32') if c.is_visible()][0]
        item=printers.get_item(queue.name);item.select();wait(item.is_selected)
        control(dialog,'Button',1010).click_input()
        prefs=wait(lambda:visible_dialog('Printing Preferences',session.proc.pid))
        control(prefs,'Button',8000).click_input();time.sleep(1)
        snapshot(folder)
        rows=[]
        for w in Desktop(backend='win32').windows(class_name='#32770',visible_only=True):
            item={'title':w.window_text(),'pid':w.process_id(),'children':[]}
            for c in w.descendants():
                if c.is_visible():
                    row={'title':c.window_text(),'class':c.class_name(),'id':c.control_id()}
                    if c.class_name()=='ComboBox':row['items']=c.texts()
                    item['children'].append(row)
            rows.append(item)
        (folder/'advanced.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
finally:
    if session:
        subprocess.run(['taskkill','/PID',str(session.proc.pid),'/T','/F'],capture_output=True,timeout=15)
        session.close()
