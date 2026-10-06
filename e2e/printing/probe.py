"""Read-only UI diagnosis of the genuine production print dialog, then cancel."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from driver import Session,menu,until
from pywinauto import Desktop
from PIL import ImageGrab
out=Path('evidence');out.mkdir(exist_ok=True)
s=None
try:
    s=Session('native',out/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
    menu(s.page,'file:print')
    def dialogs():
        return [w for w in Desktop(backend='win32').windows(visible_only=True) if w.class_name()=='#32770']
    ws=until(dialogs,30,pump=s.page.wait_for_timeout)
    records=[]
    for w in ws:
        records.append({'pid':w.process_id(),'hwnd':w.handle,'title':w.window_text(),'controls':[{'hwnd':c.handle,'class':c.class_name(),'id':c.control_id(),'text':c.window_text(),'visible':c.is_visible(),'enabled':c.is_enabled()} for c in w.descendants()]})
        print(json.dumps(records[-1],ensure_ascii=False))
    (out/'dialog.json').write_text(json.dumps({'appPid':s.proc.pid,'windows':records},ensure_ascii=False,indent=2),encoding='utf-8')
    ImageGrab.grab().save(out/'desktop.png')
    owned=[w for w in ws if w.process_id()==s.proc.pid]
    if len(owned)!=1:raise AssertionError('Expected one actual application-owned print dialog')
    w=owned[0];w.set_focus();w.child_window(control_id=2,class_name='Button').click_input()
    w.wait_not('visible',timeout=20)
finally:
    if s:s.close()
