"""Read real preview settings; no printing, baseline rewrite or product mutation."""
import json,time,traceback
from pathlib import Path
from contextlib import ExitStack
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab
from driver import Session
from virtual_print import stop_session
from print_queue import VirtualQueue,require_host
from print_focus import _node,_owned_pids,_preview_windows

require_host()
folder=Path('evidence').resolve();folder.mkdir(exist_ok=True)

def capture(root,label):
    rows=[]
    for c in root.descendants():
        row=_node(c)
        for key,method in [('value','get_value'),('selected','is_selected'),('checked','get_toggle_state')]:
            try:row[key]=getattr(c,method)()
            except Exception:pass
        rows.append(row)
    (folder/(label+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    ImageGrab.grab().save(folder/(label+'.png'))
    print(label,json.dumps([r for r in rows if r['type'] in ('Button','Hyperlink','ComboBox','Edit','RadioButton','CheckBox','Spinner')],ensure_ascii=False),flush=True)
    return rows

with ExitStack() as stack:
    q=stack.enter_context(VirtualQueue())
    session=Session('native',folder/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
    stack.callback(stop_session,session)
    w=Desktop(backend='win32').window(process=session.proc.pid,class_name='Tauri Window').wrapper_object()
    w.set_focus();send_keys('^p',vk_packet=False)
    desktop=Desktop(backend='uia');root=desktop.window(handle=w.handle).wrapper_object()
    deadline=time.monotonic()+45;preview=None
    while time.monotonic()<deadline:
        found=_preview_windows(desktop,root,w.handle,_owned_pids(session.proc.pid))
        if len(found)==1:
            preview=found[0]
            targets=[c for c in preview.descendants() if c.window_text()=='More settings' and c.element_info.control_type=='Button' and c.is_visible() and c.is_enabled()]
            if len(targets)==1:break
        time.sleep(.2)
    if preview is None:raise AssertionError('Print preview not found')
    capture(preview,'before-more')
    if len(targets)!=1:raise AssertionError('More settings not unique')
    targets[0].click_input()
    time.sleep(3)
    capture(preview,'expanded')
    # Capture only a readout after the printer capability/preview loading settles.
    time.sleep(5)
    capture(preview,'settled')
