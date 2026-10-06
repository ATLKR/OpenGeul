"""All eight real printer scenarios using the separately identified prior binary."""
from pywinauto import Desktop
import virtual_print
from print_focus import _node,_owned_pids,_preview_windows
from print_ui_policy import system_link
from preview_settings import configure_preview,wait

def open_configured_system_dialog(hwnd,pid,folder=None):
    desktop=Desktop(backend='uia');root=desktop.window(handle=hwnd).wrapper_object()
    if root.process_id()!=pid or root.class_name()!='Tauri Window':raise AssertionError('Foreign application')
    pids=_owned_pids(pid)
    def preview():
        windows=_preview_windows(desktop,root,hwnd,pids)
        if len(windows)>1:raise AssertionError('Ambiguous preview')
        if windows and any(c.window_text()=='More settings' and c.is_enabled() for c in windows[0].descendants(control_type='Button')):return windows[0]
    window=wait(preview);configure_preview(window,pids,folder)
    def action():
        controls=window.descendants();index=system_link([_node(c) for c in controls],pids)
        return controls[index] if index is not None else None
    wait(action).iface_invoke.Invoke()

virtual_print.open_system_dialog=open_configured_system_dialog
virtual_print.main()
