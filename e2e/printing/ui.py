"""Operate the application's real Print UI and the OS printer save dialog."""
import json
import re
from pathlib import Path


def _label(control):
    return control.window_text().replace('&', '').strip()


def print_document(session, printer, target: Path, *, cancel=False):
    from pywinauto import Desktop
    from driver import menu, until
    from native_controls import filename_control
    if target.exists(): raise ValueError('Printer test output must not already exist')
    desktop = Desktop(backend='uia')
    before = {window.handle for window in desktop.windows()}
    menu(session.page, 'file:print')
    seen = []
    import win32com.client
    processes = win32com.client.GetObject('winmgmts:').ExecQuery('SELECT ProcessId, ParentProcessId FROM Win32_Process')
    parents = {int(p.ProcessId): int(p.ParentProcessId) for p in processes}
    owned = {session.proc.pid}
    for _ in range(8):
        children = {pid for pid, parent in parents.items() if parent in owned}
        if children <= owned: break
        owned.update(children)
    def find_print_window():
        nonlocal seen
        # Enumerate only real visible Print windows, not similarly named editor toolbar buttons.
        seen = desktop.windows(visible_only=True)
        for window in seen:
            if window.process_id() in owned and re.match(r'^(Print|인쇄)(\s|$)', _label(window), re.I): return window
        return None
    try:
        window = until(find_print_window, 35, pump=lambda seconds: session.page.wait_for_timeout(seconds*1000))
        controls = window.descendants()
        def evidence():
            data = [{'name': _label(c), 'type': c.element_info.control_type, 'automationId': c.element_info.automation_id}
                    for c in controls[:500]]
            (target.parent / 'print-ui.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            window.capture_as_image().save(target.parent / 'print-dialog.png')
        evidence()
        if not cancel:
            # A fresh WebView can default to its own Save as PDF destination. That is NOT the test.
            matches = [c for c in controls if _label(c) == printer.name and c.is_visible()]
            if not matches:
                for combo in window.descendants(control_type='ComboBox'):
                    try: combo.select(printer.name)
                    except Exception: continue
                    controls = window.descendants()
                    matches = [c for c in controls if printer.name in _label(c)]
                    if matches: break
            if not matches:
                raise AssertionError('Print dialog did not expose/select the isolated Microsoft PDF queue')
            for item in matches:
                if item.element_info.control_type in ('ListItem', 'RadioButton'):
                    item.click_input(); break
        action = 'Cancel' if cancel else 'Print'
        labels = ('Cancel', '취소') if cancel else ('Print', '인쇄')
        buttons = [c for c in window.descendants(control_type='Button') if _label(c) in labels and c.is_enabled()]
        if len(buttons) != 1: raise AssertionError(f'Expected one real {action} button, got {len(buttons)}')
        buttons[0].click_input()
        if cancel:
            until(lambda: not window.is_visible(), 15)
            session.page.wait_for_timeout(800)
            if printer.jobs() or target.exists(): raise AssertionError('Cancelled print submitted a job')
            return []
        def find_save_window():
            # This new, specifically named Windows print output dialog belongs to the only
            # submitted job in our isolated queue. Never interact with unrelated save dialogs.
            for candidate in Desktop(backend='win32').windows(class_name='#32770', visible_only=True):
                if candidate.handle not in before and re.match(r'^(Save Print Output As|인쇄 출력 저장)', _label(candidate), re.I):
                    return candidate
            return None
        save = until(find_save_window, 30, pump=lambda seconds: session.page.wait_for_timeout(seconds*1000))
        save.set_focus()
        filename_control(save.descendants()).set_edit_text(str(target))
        save.child_window(control_id=1, class_name='Button', visible_only=True).click_input()
        until(lambda: target.is_file() and target.stat().st_size > 100, 45,
              pump=lambda seconds: session.page.wait_for_timeout(seconds*1000))
        # Retained spooler evidence is required, not merely a file with a .pdf extension.
        jobs = until(printer.jobs, 15)
        if len(jobs) != 1: raise AssertionError(f'Expected exactly one isolated spooler job, got {jobs}')
        until(lambda: target.read_bytes().rstrip().endswith(b'%%EOF'), 20,
              pump=lambda seconds: session.page.wait_for_timeout(seconds*1000))
        return jobs
    except BaseException:
        snapshots = [{'name': _label(w), 'handle': w.handle, 'pid': w.process_id()} for w in seen]
        (target.parent / 'window-diagnostics.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
