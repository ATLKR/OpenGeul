"""Send a real virtual-key accelerator to the newly created print viewport."""
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

def open_system_dialog(viewport):
    window=Desktop(backend='win32').window(handle=viewport).wrapper_object()
    if window.class_name()!='Chrome_RenderWidgetHostHWND' or not window.is_visible():
        raise AssertionError('Print preview viewport is not visible')
    window.set_focus()
    window.click_input(coords=(4,4))
    # Browser accelerators require a key code, not a textual Unicode VK_PACKET.
    # https://pywinauto.readthedocs.io/en/latest/code/pywinauto.keyboard.html
    send_keys('^+p',vk_packet=False)
