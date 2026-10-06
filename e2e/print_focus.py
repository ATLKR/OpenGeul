"""Native print input and observable shell-control readiness, with no test retries."""
import time
from pathlib import Path
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from native_controls import filename_control

def open_system_dialog(app_hwnd: int, app_pid: int):
    """Select the real semantic preview action once, not a timing-sensitive key.

    Windows 2022 exposes this action as Button, Windows 2025 as Hyperlink.
    Both are observed under the owned Print/RootView accessibility window.
    On-demand accessibility suffices; no extra browser flags or app hooks.
    """
    import psutil
    from comtypes import COMError
    from print_ui_policy import system_link
    root = Desktop(backend='uia').window(handle=app_hwnd).wrapper_object()
    if root.process_id() != app_pid or root.class_name() != 'Tauri Window':
        raise AssertionError('Print action root is not the owned application')
    deadline = time.monotonic() + 30
    target = None
    while time.monotonic() < deadline:
        try:
            pids = {app_pid, *(p.pid for p in psutil.Process(app_pid).children(recursive=True))}
            previews = [c for c in root.descendants(control_type='Window')
                        if c.window_text() == 'Print' and c.class_name() == 'RootView'
                        and c.process_id() in pids and c.is_visible()]
            if len(previews) > 1: raise AssertionError('Ambiguous owned Print preview')
            if previews:
                controls = previews[0].descendants()
                nodes = [{'name': c.window_text(), 'type': c.element_info.control_type,
                          'visible': c.is_visible(), 'enabled': c.is_enabled(), 'pid': c.process_id()}
                         for c in controls]
                index = system_link(nodes, pids)
                if index is not None:
                    target = controls[index]
                    break
        except COMError:
            # Accessibility elements can be replaced during preview initialization.
            # Re-observe readiness only; the eventual click itself is never retried.
            pass
        time.sleep(.15)
    if target is None:
        raise AssertionError('Owned system-print link did not become accessible')
    target.click_input()

def fill_print_output(dialog,output:Path):
    """Shell dialogs can replace their initial Edit HWND after becoming visible.

    Observe stable visible/enabled filename and Save controls before sending a
    single input action. Never retry a failed save, generate a path elsewhere or
    bypass the ordinary shell dialog.
    """
    deadline=time.monotonic()+30
    previous=None;stable_since=0.0
    while time.monotonic()<deadline:
        try:
            field=filename_control(dialog.descendants())
            buttons=[c for c in dialog.descendants(class_name='Button')
                     if c.control_id()==1 and c.is_visible() and c.is_enabled()]
            if len(buttons)!=1:raise ValueError('Save control is not uniquely ready')
            button=buttons[0];rect=field.rectangle()
            current=(field.handle,button.handle,rect.left,rect.top,rect.right,rect.bottom)
        except (ValueError,OSError):
            current=None
        now=time.monotonic()
        if current is None or current!=previous:
            previous=current;stable_since=now
        elif now-stable_since>=0.75:
            field.set_edit_text(str(output))
            if field.window_text()!=str(output):raise AssertionError('Printer output path was not accepted')
            button.click_input()
            return
        time.sleep(.1)
    raise AssertionError('Print output filename/Save controls did not stabilize')
