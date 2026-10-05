"""Select a real Win32 filename edit, never a search field or hidden legacy control."""
def filename_control(controls):
    candidates=[control for control in controls
        if control.class_name()=='Edit' and control.is_visible() and control.is_enabled()
        and control.parent().class_name()=='ComboBox']
    if len(candidates)!=1:
        raise ValueError(f'Expected exactly one visible filename edit; found {len(candidates)}')
    return candidates[0]
