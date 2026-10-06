"""Probe real media controls with native accessibility, without a print bypass."""
import json,time
from pathlib import Path
from contextlib import ExitStack
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab
from driver import Session
from virtual_print import stop_session
from print_queue import VirtualQueue,require_host
from print_focus import _node,_owned_pids,_preview_windows
require_host();folder=Path('evidence').resolve();folder.mkdir(exist_ok=True)

def controls(root):return root.descendants()
def capture(root,label):
    rows=[_node(c) for c in controls(root)]
    (folder/(label+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    ImageGrab.grab().save(folder/(label+'.png'))
    print(label,json.dumps([r for r in rows if r['type'] in ('Button','Hyperlink','ComboBox','ListItem','MenuItem','RadioButton','CheckBox','Edit')],ensure_ascii=False),flush=True)
def wait(fn):
    until=time.monotonic()+30
    while time.monotonic()<until:
        v=fn()
        if v:return v
        time.sleep(.2)
    raise AssertionError('Diagnostic readiness timeout')
def dropdown(preview,label):
    old=[c for c in controls(preview) if c.element_info.control_type=='Button' and c.window_text().startswith(label+' ')]
    if len(old)==1:return old[0]
    groups=[c for c in controls(preview) if c.element_info.control_type=='Group' and c.window_text()==label]
    choices=[c for g in groups for c in g.descendants(control_type='ComboBox')]
    if len(choices)!=1:raise AssertionError(f'{label}: missing or ambiguous control')
    return choices[0]
with ExitStack() as stack:
    q=stack.enter_context(VirtualQueue())
    session=Session('native',folder/'session',Path('inputs/e2e-fixtures/basic.hwpx').resolve(),executable=Path('runtime/OpenGeul.exe').resolve())
    stack.callback(stop_session,session)
    w=Desktop(backend='win32').window(process=session.proc.pid,class_name='Tauri Window').wrapper_object()
    w.set_focus();send_keys('^p',vk_packet=False)
    desktop=Desktop(backend='uia');root=desktop.window(handle=w.handle).wrapper_object()
    preview=wait(lambda:next(iter(_preview_windows(desktop,root,w.handle,_owned_pids(session.proc.pid))),None))
    more=wait(lambda:next((c for c in controls(preview) if c.window_text()=='More settings' and c.element_info.control_type=='Button'),None))
    more.invoke();time.sleep(2)
    capture(preview,'initial')
    for label in ('Paper size','Margins'):
        target=dropdown(preview,label)
        # UIA activation still exercises the actual user-facing control, even when
        # its scroll container has placed it outside the small runner viewport.
        if target.element_info.control_type=='ComboBox':target.expand()
        else:target.invoke()
        time.sleep(1)
        capture(root,label.replace(' ','-')+'-options')
        send_keys('{ESC}')
        time.sleep(.3)
    capture(preview,'end')
