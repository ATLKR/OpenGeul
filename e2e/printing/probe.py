"""Diagnose the app-owned embedded print preview and real system-dialog link."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from driver import Session,menu
from pywinauto import Desktop
from PIL import ImageGrab
out=Path('evidence');out.mkdir(exist_ok=True)
s=None
try:
    s=Session('native',out/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
    app=Desktop(backend='win32').window(process=s.proc.pid,class_name='Tauri Window')
    menu(s.page,'file:print')
    ui=Desktop(backend='uia').window(handle=app.handle)
    ui.print_control_identifiers(filename=str(out/'preview-uia.txt'))
    links=[c for c in ui.descendants() if 'Print using system dialog' in c.window_text()]
    print('system links:',[(c.element_info.control_type,c.window_text()) for c in links])
    if len(links)!=1:raise AssertionError('Expected exactly one accessible system-dialog action')
    links[0].click_input()
    time.sleep(2)
    records=[]
    for w in Desktop(backend='win32').windows(visible_only=True):
        if w.class_name()!='#32770':continue
        record={'pid':w.process_id(),'hwnd':w.handle,'class':w.class_name(),'title':w.window_text(),'controls':[{'hwnd':c.handle,'class':c.class_name(),'id':c.control_id(),'text':c.window_text(),'visible':c.is_visible(),'enabled':c.is_enabled()} for c in w.descendants()]}
        records.append(record);print(json.dumps(record,ensure_ascii=False))
    (out/'dialog.json').write_text(json.dumps({'appPid':s.proc.pid,'windows':records},ensure_ascii=False,indent=2),encoding='utf-8')
finally:
    if s:
        ImageGrab.grab().save(out/'final-desktop.png')
        s.close()
