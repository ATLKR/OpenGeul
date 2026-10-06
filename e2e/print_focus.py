"""Focus only the newly created native print viewport, not the editor behind it."""
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

def open_system_dialog(viewport):
    window=Desktop(backend='win32').window(handle=viewport).wrapper_object()
    if window.class_name()!='Chrome_RenderWidgetHostHWND' or not window.is_visible():
        raise AssertionError('Print preview viewport is not visible')
    window.set_focus()
    # A click in the viewport's non-content top edge gives the preview keyboard
    # focus; no Print button or printer selection is activated by this action.
    window.click_input(coords=(4,4))
    send_keys('^+p')
