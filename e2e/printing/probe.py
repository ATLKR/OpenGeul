"""Diagnose real app Print -> system print dialog. No print API interception."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from driver import Session,menu,until
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab
out=Path('evidence');out.mkdir(exist_ok=True)
s=None
try:
    s=Session('native',out/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
    app=Desktop(backend='win32').window(process=s.proc.pid,class_name='Tauri Window')
    menu(s.page,'file:print')
    time.sleep(2)
    app.set_focus();send_keys('^+p')
    dialog=Desktop(backend='win32').window(class_name='#32770',process=s.proc.pid)
    dialog.wait('visible',timeout=30)
    ImageGrab.grab().save(out/'desktop.png')
    records=[]
    for w in Desktop(backend='win32').windows(visible_only=True,process=s.proc.pid):
        record={'pid':w.process_id(),'hwnd':w.handle,'class':w.class_name(),'title':w.window_text(),'controls':[{'hwnd':c.handle,'class':c.class_name(),'id':c.control_id(),'text':c.window_text(),'visible':c.is_visible(),'enabled':c.is_enabled()} for c in w.descendants()]}
        records.append(record);print(json.dumps(record,ensure_ascii=False))
    (out/'dialog.json').write_text(json.dumps({'appPid':s.proc.pid,'windows':records},ensure_ascii=False,indent=2),encoding='utf-8')
    Desktop(backend='uia').window(handle=dialog.handle).print_control_identifiers(filename=str(out/'uia-system.txt'))
    dialog.set_focus();dialog.child_window(control_id=2,class_name='Button').click_input()
    dialog.wait_not('visible',timeout=20)
finally:
    if s:
        ImageGrab.grab().save(out/'final-desktop.png')
        s.close()
