"""Diagnose the app-owned embedded print preview and real system-dialog link."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from driver import Session,menu,until
from pywinauto import Desktop
from PIL import ImageGrab
out=Path('evidence');out.mkdir(exist_ok=True)
s=None
try:
    s=Session('native',out/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve(),accessibility=True)
    app=Desktop(backend='win32').window(process=s.proc.pid,class_name='Tauri Window')
    menu(s.page,'file:print')
    ui=Desktop(backend='uia').window(handle=app.handle)
    def links():return [c for c in ui.descendants(control_type='Hyperlink') if 'Print using system dialog' in c.window_text()]
    try:
        link=until(links,30)[0];link.click_input();time.sleep(2)
    finally:ui.print_control_identifiers(filename=str(out/'preview-uia.txt'))
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
