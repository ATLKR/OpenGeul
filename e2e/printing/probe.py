"""Read-only diagnosis of the real print UI. No renderer or print API mocks."""
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
    before={w.handle for w in Desktop(backend='win32').windows(visible_only=True)}
    menu(s.page,'file:print')
    time.sleep(2)
    ImageGrab.grab().save(out/'desktop.png')
    records=[]
    for w in Desktop(backend='win32').windows(visible_only=True):
        record={'pid':w.process_id(),'hwnd':w.handle,'class':w.class_name(),'title':w.window_text(),'new':w.handle not in before,'controls':[{'hwnd':c.handle,'class':c.class_name(),'id':c.control_id(),'text':c.window_text(),'visible':c.is_visible(),'enabled':c.is_enabled()} for c in w.descendants()]}
        records.append(record)
        print(json.dumps({k:v for k,v in record.items() if k!='controls'},ensure_ascii=False))
        if record['new']:
            try:Desktop(backend='uia').window(handle=w.handle).print_control_identifiers(filename=str(out/f'uia-{w.handle}.txt'))
            except Exception as exc:print('UIA diagnosis:',repr(exc))
    (out/'dialog.json').write_text(json.dumps({'appPid':s.proc.pid,'windows':records},ensure_ascii=False,indent=2),encoding='utf-8')
finally:
    if s:s.close()
