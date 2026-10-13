"""Bind the owned native Print command before one physical dispatch."""
from __future__ import annotations

import json
from print_focus import WindowsFocusProbe, _bind_native_print_processes, _rect


def _observed_window(row):
    allowed = {'#32770', 'Button', 'Tauri Window', 'Chrome_WidgetWin_1'}
    return {key: ('unexpected-class' if key == 'cls' and value not in allowed else value)
            for key, value in row.items() if key in
            ('hwnd', 'pid', 'tid', 'cls', 'visible', 'enabled', 'root', 'owners')}


def click_owned_print_dialog(dialog, app_pid, runtime, *, app_handle, evidence_dir=None, probe=None):
    """Verify the direct Print button, focus, and exact point; never retry input."""
    api = probe or WindowsFocusProbe()
    entry = {'kind': 'diagnostic-metadata', 'operation': 'native-print-input', 'phase': 'binding',
             'sourceQualified': False, 'productTelemetry': False, 'passed': False,
             'physicalClickAttempts': 0}
    try:
        pid, hwnd = dialog.process_id(), dialog.handle
        processes, bind = _bind_native_print_processes(api, pid, app_pid, runtime, app_handle)
        window = api.window(hwnd)
        entry.update(appPid=app_pid, dialogHwnd=hwnd, dialogPid=pid, dialogTid=window['tid'],
                     initialWindow=_observed_window(window), foregroundBefore=api.foreground(),
                     dialogClassMatched=dialog.class_name() == '#32770',
                     dialogTitleMatched=dialog.window_text() == 'Print')
        if (not entry['dialogClassMatched'] or not entry['dialogTitleMatched']
                or window['pid'] != pid or window['root'] != hwnd or window['cls'] != '#32770'
                or not window['visible'] or not window['enabled']):
            raise AssertionError('Native Print is not the exact ready owned dialog')
        owners = {}
        for owner in window['owners']:
            row = api.window(owner); bind(row['pid'])
            if row['root'] != owner:
                raise AssertionError('Native Print owner is not a root window')
            owners[owner] = row
        if not owners or not any(row['pid'] == app_pid for row in owners.values()):
            raise AssertionError('Native Print lacks its verified app owner')
        entry.update(ownerWindows=[_observed_window(row) for row in owners.values()],
                     processes=list(processes.values())[:8], processesOmitted=max(0, len(processes) - 8))
        buttons = [c for c in dialog.children(class_name='Button') if c.control_id() == 1]
        if len(buttons) != 1:
            raise AssertionError('Native Print command is not one direct Button1')
        button = buttons[0]; target = api.window(button.handle); rect = _rect(button)
        entry.update(buttonHwnd=button.handle, buttonTid=target['tid'],
                     buttonParentHwnd=api.parent(button.handle),
                     buttonCaptionMatched=button.window_text() in ('Print', '&Print'))
        if (rect is None or any(type(n) is not int or not -2**31 <= n < 2**31 for n in rect)
                or rect[2] <= rect[0] or rect[3] <= rect[1]):
            raise AssertionError('Native Print rectangle is invalid')
        point = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        entry.update(buttonRect=rect, point=point, initialButton=_observed_window(target))

        def recheck():
            for owned, record in processes.items(): api.verify_process(owned, record)
            if (dialog.handle != hwnd or dialog.process_id() != pid or dialog.class_name() != '#32770'
                    or dialog.window_text() != 'Print' or api.window(hwnd) != window):
                raise AssertionError('Bound native Print dialog identity changed')
            for owner, row in owners.items():
                if api.window(owner) != row:
                    raise AssertionError('Bound native Print owner changed')
            if (button.handle != target['hwnd'] or button.process_id() != pid
                    or button.class_name() != 'Button' or button.control_id() != 1
                    or button.window_text() not in ('Print', '&Print')
                    or target['pid'] != pid or target['tid'] != window['tid']
                    or target['cls'] != 'Button' or target['root'] != hwnd
                    or not target['visible'] or not target['enabled']
                    or not button.is_visible() or not button.is_enabled()
                    or api.parent(button.handle) != hwnd or api.window(button.handle) != target
                    or _rect(button) != rect):
                raise AssertionError('Bound native Print command identity changed')

        entry['phase'] = 'foreground-preparation'; recheck()
        if api.foreground() != hwnd:
            entry['setForegroundReturned'] = api.set_foreground(hwnd)
            if not entry['setForegroundReturned']:
                raise AssertionError('Owned native Print foreground request failed')
            entry['activationBarrier'] = {}
            if not api.sync_activation(hwnd, window, entry['activationBarrier']):
                raise AssertionError('Owned native Print activation was not processed')
        recheck()
        if api.foreground() != hwnd:
            raise AssertionError('Exact native Print foreground was not observed')
        entry['phase'] = 'print-point-guard'; entry['hitHwnd'] = api.hit(point)
        if entry['hitHwnd'] != target['hwnd']:
            raise AssertionError('Native Print click point is covered by another HWND')
        recheck(); entry['foregroundAtInput'] = api.foreground()
        if entry['foregroundAtInput'] != hwnd:
            raise AssertionError('Native Print foreground changed before physical input')
        entry['hitHwndAtInput'] = api.hit(point)
        if entry['hitHwndAtInput'] != target['hwnd']:
            raise AssertionError('Native Print click point changed before physical input')
        recheck()
        if api.foreground() != hwnd:
            raise AssertionError('Native Print foreground changed during its final point guard')
        entry.update(phase='print-dispatch', physicalClickAttempts=1)
        button.click_input()
        entry.update(phase='print-dispatched', passed=True)
    except BaseException as error:
        entry['errorType'] = type(error).__name__[:64]
        raise
    finally:
        # Print may close this dialog and activate Save. Its appearance and the
        # actual PDF/spooler outcome remain the caller's independent checks.
        try: entry['foregroundAfter'] = api.foreground()
        except Exception: entry['foregroundAfter'] = None
        if evidence_dir is not None:
            data = json.dumps(entry, ensure_ascii=True, separators=(',', ':')).encode('ascii')
            if len(data) <= 8192:
                try: (evidence_dir/'print-native-dispatch-diagnostic.json').write_bytes(data)
                except OSError: pass
        api.close()
