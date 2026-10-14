"""Select real Windows controls; never a search field or hidden legacy control."""
import hashlib

from ui_contract import canonical_local_path

def bind_dialog(desktop, pid):
    """Freeze the exact HWND before a following same-class TaskDialog can appear."""
    selected = desktop.window(class_name='#32770', process=pid)
    selected.wait('visible', timeout=20)
    actual = selected.wrapper_object()
    if actual.process_id() != pid or actual.class_name() != '#32770':
        raise ValueError('Native dialog ownership changed before binding')
    return desktop.window(handle=actual.handle)


def filename_control(controls):
    candidates=[control for control in controls
        if control.class_name()=='Edit' and control.is_visible() and control.is_enabled()
        and control.parent().class_name()=='ComboBox']
    if len(candidates)!=1:
        raise ValueError(f'Expected exactly one visible filename edit; found {len(candidates)}')
    return candidates[0]


def explorer_window_binding(probe, hwnd, pid, process_record, *, expected=None, diagnostic=None):
    """Hold the actual Explorer PID/thread/HWND through move, input and cleanup."""
    report = diagnostic if diagnostic is not None else {}
    report['stage'] = 'explorer-process'
    probe.verify_process(pid, process_record)
    report['stage'] = 'explorer-window'
    window = probe.window(hwnd)
    report['window'] = window
    if (window['hwnd'] != hwnd or window['root'] != hwnd or window['pid'] != pid
            or type(window['tid']) is not int or window['tid'] <= 0
            or window['cls'] not in ('CabinetWClass', 'ExploreWClass')
            or not window['visible'] or not window['enabled']):
        raise AssertionError('Explorer selection window ownership is unavailable')
    if expected is not None and window != expected:
        raise AssertionError('Owned Explorer window identity changed')
    return window


def explorer_item_binding(probe, hwnd, pid, process_record, item, *, expected=None, window_expected=None, diagnostic=None):
    """Read and bind an owned physical item point before any selection input."""
    report = diagnostic if diagnostic is not None else {}
    window = explorer_window_binding(probe, hwnd, pid, process_record, expected=window_expected, diagnostic=report)
    report['stage'] = 'explorer-item'
    if item.process_id() != pid or not item.is_visible() or not item.is_enabled():
        raise AssertionError('Explorer selection item is not owned and ready')
    runtime_id = tuple(item.element_info.element.GetRuntimeId())
    if not runtime_id or len(runtime_id) > 64 or any(type(value) is not int for value in runtime_id):
        raise AssertionError('Explorer selection item runtime identity is unavailable')
    rect = item.rectangle()
    bounds = [rect.left, rect.top, rect.right, rect.bottom]
    if any(type(value) is not int for value in bounds) or rect.right <= rect.left or rect.bottom <= rect.top:
        raise AssertionError('Explorer selection item has no actual bounds')
    point = (round((rect.left+rect.right)/2), round((rect.top+rect.bottom)/2))
    report.update({'itemRuntimeId': list(runtime_id), 'itemBounds': bounds, 'point': list(point)})
    report['stage'] = 'explorer-point'
    hit = probe.window(probe.hit(point))
    foreground = probe.foreground()
    report.update({'hit': hit, 'foreground': foreground})
    if (hit['root'] != hwnd or hit['pid'] != pid or type(hit['tid']) is not int
            or hit['tid'] <= 0 or not hit['visible'] or not hit['enabled'] or foreground != hwnd):
        raise AssertionError('Physical Explorer selection point or foreground is not owned')
    record = {'window': window, 'itemRuntimeId': list(runtime_id), 'itemBounds': bounds,
              'point': list(point), 'hit': hit, 'foreground': foreground}
    if expected is not None and record != expected:
        raise AssertionError('Explorer selection ownership changed before physical input')
    report['stage'] = 'explorer-selection-bound'
    return record


def physical_explorer_selection(probe, hwnd, pid, process_record, item, click, *, window_expected=None, diagnostic=None):
    """One real mouse click, only after two matching live ownership observations."""
    first = explorer_item_binding(probe, hwnd, pid, process_record, item, window_expected=window_expected, diagnostic=diagnostic)
    explorer_item_binding(probe, hwnd, pid, process_record, item, expected=first, diagnostic=diagnostic)
    if diagnostic is not None: diagnostic['selectionInputAttempted'] = True
    click(tuple(first['point']))
    if diagnostic is not None: diagnostic['selectionInputCompleted'] = True
    return first


def require_explorer_selection(row, target, hwnd, *, diagnostic=None):
    """Read one actual Shell selected path; aliases cannot change ownership."""
    report = diagnostic if diagnostic is not None else {}
    report['stage'] = 'explorer-selection-readback'
    target = canonical_local_path(target)
    if not target.is_file():
        raise AssertionError('Explorer target is not an actual owned file')
    selected = row.get('selected') if isinstance(row, dict) else None
    report['selectedCount'] = len(selected) if isinstance(selected, list) else None
    report['selected'] = []
    if isinstance(selected, list) and len(selected) <= 100:
        for raw in selected[:4]:
            owned = False
            if isinstance(raw, str) and len(raw) <= 2048:
                try:
                    owned = canonical_local_path(raw).is_relative_to(target.parent)
                except (ValueError, OSError):
                    pass
            if owned:
                report['selected'].append({'owned': True, 'raw': raw})
            else:
                data = raw.encode('utf-8', errors='replace') if isinstance(raw, str) else b''
                report['selected'].append({'owned': False, 'characters': len(raw) if isinstance(raw, str) else None,
                                           'sha256': hashlib.sha256(data).hexdigest()})
    if not isinstance(row, dict) or type(row.get('hwnd')) is not int or row['hwnd'] != hwnd:
        raise AssertionError('Explorer selection readback is from another window')
    try:
        folder_matched = canonical_local_path(row.get('path')) == target.parent
    except (ValueError, OSError):
        folder_matched = False
    report['folderMatched'] = folder_matched
    if not folder_matched or not isinstance(selected, list) or len(selected) != 1:
        raise AssertionError('Explorer selection is not exactly one owned fixture path')
    try:
        matched = canonical_local_path(selected[0]) == target
    except (ValueError, OSError):
        matched = False
    if not matched:
        raise AssertionError('Explorer selection is not the exact owned fixture path')
    report['stage'] = 'explorer-selected-owned'
    return row


def dismiss_error_dialog(pid: int) -> str:
    """Read the actual TaskDialog text through its HWND, then dismiss it physically."""
    from pywinauto import Desktop
    dialog=bind_dialog(Desktop(backend='win32'), pid)
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
