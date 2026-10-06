"""Native print input and observable shell-control readiness, with no click retries."""
from __future__ import annotations
import json
import time
from pathlib import Path

from pywinauto import Desktop


STABLE_ACTION_SECONDS = 2.5


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
    """Activate the real semantic preview action once after observable UI stability.

    Windows 2022 exposes the system-print action as Button and Windows 2025 as
    Hyperlink. The exact owned semantic action must remain enabled and at the same
    accessible geometry for STABLE_ACTION_SECONDS before the one physical click.
    If it is initially off-screen, scroll it into view; only then may the already-
    opened preview cause the host to be maximized. No keyboard fallback or click
    retry is used.
    """
    from comtypes import COMError
    from print_ui_policy import system_link

    desktop = Desktop(backend='uia')
    root = desktop.window(handle=app_hwnd).wrapper_object()
    if root.process_id() != app_pid or root.class_name() != 'Tauri Window':
        raise AssertionError('Print action root is not the owned application')

    deadline = time.monotonic() + 35
    stable_signature = None
    stable_since = 0.0
    maximized_after_preview = False
    last_observation = {'state': 'waiting', 'appPid': app_pid, 'appHwnd': app_hwnd}

    while time.monotonic() < deadline:
        try:
            pids = _owned_pids(app_pid)
            previews = _preview_windows(desktop, root, app_hwnd, pids)
            if len(previews) > 1:
                last_observation = {
                    'state': 'ambiguous-preview',
                    'ownedPids': sorted(pids),
                    'previews': [_node(p) for p in previews],
                }
                _write_evidence(evidence_dir, last_observation)
                raise AssertionError('Ambiguous owned Print preview')
            if not previews:
                stable_signature = None
                stable_since = 0.0
                time.sleep(.15)
                continue

            preview = previews[0]
            controls = preview.descendants()
            nodes = [_node(control) for control in controls]
            last_observation = {
                'state': 'preview-observed',
                'ownedPids': sorted(pids),
                'preview': _node(preview),
                'controls': nodes[:400],
                'controlCount': len(nodes),
            }
            index = system_link(nodes, pids)
            if index is None:
                stable_signature = None
                stable_since = 0.0
                time.sleep(.15)
                continue

            target = controls[index]
            target_node = nodes[index]
            if not target_node['visible']:
                try:
                    target.scroll_into_view()
                except (AttributeError, COMError, OSError):
                    pass
                if not _safe(lambda: target.is_visible(), False) and not maximized_after_preview:
                    try:
                        Desktop(backend='win32').window(handle=app_hwnd).wrapper_object().maximize()
                        maximized_after_preview = True
                    except Exception:
                        pass
                stable_signature = None
                stable_since = 0.0
                time.sleep(.15)
                continue

            signature = (
                _safe(lambda: preview.process_id()),
                getattr(preview, 'handle', None),
                tuple(_rect(preview) or ()),
                target_node['pid'],
                target_node['handle'],
                target_node['name'],
                target_node['type'],
                tuple(target_node['rect'] or ()),
            )
            now = time.monotonic()
            if signature != stable_signature:
                stable_signature = signature
                stable_since = now
            elif now - stable_since >= STABLE_ACTION_SECONDS:
                last_observation.update({
                    'state': 'ready',
                    'stableSeconds': now - stable_since,
                    'selected': target_node,
                    'maximizedAfterPreview': maximized_after_preview,
                })
                _write_evidence(evidence_dir, last_observation)
                target.click_input()
                return
        except COMError:
            # Accessibility elements can be replaced during preview initialization.
            # Re-observe readiness only; the eventual click itself is never retried.
            stable_signature = None
            stable_since = 0.0
        time.sleep(.15)

    last_observation['state'] = 'timeout'
    _write_evidence(evidence_dir, last_observation)
    raise AssertionError('Owned system-print link did not become stably accessible')
