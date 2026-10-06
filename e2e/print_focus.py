"""Native print input and observable shell-control readiness, with no test retries."""
import time
from pathlib import Path
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from native_controls import filename_control

def open_system_dialog(viewport):
    window=Desktop(backend='win32').window(handle=viewport).wrapper_object()
    if window.class_name()!='Chrome_RenderWidgetHostHWND' or not window.is_visible():
        raise AssertionError('Print preview viewport is not visible')
    window.set_focus()
    window.click_input(coords=(4,4))
    send_keys('^+p',vk_packet=False)

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
