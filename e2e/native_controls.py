"""Select real Windows controls; never a search field or hidden legacy control."""
def filename_control(controls):
    candidates=[control for control in controls
        if control.class_name()=='Edit' and control.is_visible() and control.is_enabled()
        and control.parent().class_name()=='ComboBox']
    if len(candidates)!=1:
        raise ValueError(f'Expected exactly one visible filename edit; found {len(candidates)}')
    return candidates[0]


def dismiss_error_dialog(pid: int) -> str:
    """Read the actual TaskDialog text through its HWND, then dismiss it physically."""
    from pywinauto import Desktop
    dialog=Desktop(backend='win32').window(class_name='#32770',process=pid)
    dialog.wait('visible',timeout=20)
    # Win32 exposes the button but not the DirectUI message. UIA root enumeration
    # can omit the dialog, but its verified HWND exposes the accessible text.
    accessible=Desktop(backend='uia').window(handle=dialog.handle)
    message='\n'.join(control.window_text() for control in accessible.descendants(control_type='Text')
                      if control.window_text())
    if '실패' not in message and '오류' not in message:
        raise AssertionError(f'Expected the native file-open error, got {message!r}')
    buttons=[control for control in dialog.descendants(class_name='Button')
             if control.is_visible() and control.is_enabled()
             and control.window_text().replace('&','').strip() in ('OK','확인')]
    if len(buttons)!=1:
        raise AssertionError(f'Expected one visible native error confirmation button; found {len(buttons)}')
    dialog.set_focus()
    buttons[0].click_input()
    dialog.wait_not('visible',timeout=20)
    return message
