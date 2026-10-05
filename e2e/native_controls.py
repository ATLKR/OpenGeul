"""Select a real Win32 filename edit, never a search field or hidden legacy control."""
def filename_control(controls):
    candidates=[control for control in controls
        if control.class_name()=='Edit' and control.is_visible() and control.is_enabled()
        and control.parent().class_name()=='ComboBox']
    if len(candidates)!=1:
        raise ValueError(f'Expected exactly one visible filename edit; found {len(candidates)}')
    return candidates[0]


def dismiss_error_dialog(pid: int) -> str:
    """Read and dismiss the actual Tauri/Windows error, not a browser JS alert."""
    from pywinauto import Desktop
    dialog=Desktop(backend='win32').window(class_name='#32770',process=pid)
    dialog.wait('visible',timeout=20)
    message='\n'.join(control.window_text() for control in dialog.descendants()
                      if control.is_visible() and control.window_text())
    if '실패' not in message and '오류' not in message:
        raise AssertionError(f'Expected the native file-open error, got {message!r}')
    dialog.set_focus()
    dialog.child_window(control_id=1,class_name='Button',visible_only=True).click_input()
    dialog.wait_not('visible',timeout=20)
    return message
