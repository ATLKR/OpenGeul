"""Native print input and observable shell-control readiness, with no click retries."""
from __future__ import annotations
import json
import time
from pathlib import Path

from pywinauto import Desktop


def _safe(call, default=None):
    try:
        return call()
    except Exception:
        return default


def _rect(control):
    rect = _safe(lambda: control.rectangle())
    return None if rect is None else [rect.left, rect.top, rect.right, rect.bottom]


def _node(control):
    info = getattr(control, 'element_info', None)
    return {
        'name': _safe(lambda: control.window_text(), ''),
        'type': getattr(info, 'control_type', None),
        'visible': bool(_safe(lambda: control.is_visible(), False)),
        'enabled': bool(_safe(lambda: control.is_enabled(), False)),
        'pid': _safe(lambda: control.process_id()),
        'handle': getattr(control, 'handle', None),
        'automationId': getattr(info, 'automation_id', None),
        'className': _safe(lambda: control.class_name(), ''),
        'rect': _rect(control),
    }


def _write_evidence(folder: Path | None, payload):
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'print-accessibility.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n',
        encoding='utf-8',
    )


def _owned_pids(app_pid: int):
    import psutil
    try:
        return {app_pid, *(p.pid for p in psutil.Process(app_pid).children(recursive=True))}
    except psutil.Error:
        return {app_pid}


def _preview_windows(desktop, app_root, app_hwnd: int, pids: set[int]):
    """Find the owned Print/RootView even when UIA exposes it as another top-level root."""
    roots = [app_root]
    try:
        roots.extend(
            window for window in desktop.windows()
            if getattr(window, 'handle', None) != app_hwnd
            and _safe(lambda w=window: w.process_id()) in pids
            and _safe(lambda w=window: w.is_visible(), False)
        )
    except Exception:
        # The application root remains authoritative if top-level enumeration is transient.
        pass

    previews = {}
    for owner in roots:
        candidates = [owner]
        try:
            candidates.extend(owner.descendants(control_type='Window'))
        except Exception:
            continue
        for candidate in candidates:
            if (
                _safe(lambda c=candidate: c.window_text(), '') == 'Print'
                and _safe(lambda c=candidate: c.class_name(), '') == 'RootView'
                and _safe(lambda c=candidate: c.process_id()) in pids
            ):
                key = (
                    getattr(candidate, 'handle', None),
                    _safe(lambda c=candidate: c.process_id()),
                )
                previews[key] = candidate
    return list(previews.values())


def open_system_dialog(app_hwnd: int, app_pid: int, evidence_dir: Path | None = None):
    """Configure actual preview media, then invoke the owned system-print action once.

    Chromium preview and the Windows driver independently store media settings.
    The native accessibility action remains the same user-facing print command;
    it is not a PDF export or an application test hook. Dispatch errors escape.
    """
    from print_ui_policy import system_link
    from preview_settings import configure_preview, wait

    desktop = Desktop(backend='uia')
    root = desktop.window(handle=app_hwnd).wrapper_object()
    if root.process_id() != app_pid or root.class_name() != 'Tauri Window':
        raise AssertionError('Print action root is not the owned application')
    pids = _owned_pids(app_pid)

    def ready_preview():
        previews = _preview_windows(desktop, root, app_hwnd, pids)
        if len(previews) > 1:
            raise AssertionError('Ambiguous owned Print preview')
        if previews and any(c.window_text() == 'More settings' and c.is_enabled()
                            for c in previews[0].descendants(control_type='Button')):
            return previews[0]
        return None

    preview = wait(ready_preview)
    settings = configure_preview(preview, pids, evidence_dir)

    def ready_action():
        controls = preview.descendants()
        index = system_link([_node(c) for c in controls], pids)
        return controls[index] if index is not None else None

    target = wait(ready_action)
    _write_evidence(evidence_dir, {
        'state': 'configured', 'appPid': app_pid, 'appHwnd': app_hwnd,
        'previewSettings': settings, 'selected': _node(target),
        'activation': 'native UIA InvokePattern (one dispatch)',
    })
    target.iface_invoke.Invoke()


def fill_print_output(dialog, output: Path):
    """Wait for stable real shell controls, then enter a path and click exactly once."""
    from native_controls import filename_control

    deadline = time.monotonic() + 30
    previous = None
    stable_since = 0.0
    while time.monotonic() < deadline:
        try:
            field = filename_control(dialog.descendants())
            buttons = [control for control in dialog.descendants(class_name='Button')
                       if control.control_id() == 1 and control.is_visible() and control.is_enabled()]
            if len(buttons) != 1:
                raise ValueError('Save control is not uniquely ready')
            button = buttons[0]
            rect = field.rectangle()
            current = (field.handle, button.handle, rect.left, rect.top, rect.right, rect.bottom)
        except (ValueError, OSError):
            current = None
        now = time.monotonic()
        if current is None or current != previous:
            previous = current
            stable_since = now
        elif now - stable_since >= .75:
            # Dispatch errors escape: never retry a possibly completed save action.
            field.set_edit_text(str(output))
            if field.window_text() != str(output):
                raise AssertionError('Printer output path was not accepted')
            button.click_input()
            return
        time.sleep(.1)
    raise AssertionError('Print output filename/Save controls did not stabilize')
