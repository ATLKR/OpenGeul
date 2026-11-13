"""Copy only the already rejected GUI query; never query or change native state."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import re

MAX_BYTES = 16 * 1024
MAX_RECEIPTS = 64


def copy_gui_thread_info(info):
    """Fixed Win64 raw values, with no HWND owner or process-generation claim."""
    assert ctypes.sizeof(info) == int(info.cbSize) == 72
    result = dict(cbSize=int(info.cbSize), flags=int(info.flags))
    for key in ('hwndActive', 'hwndFocus', 'hwndCapture', 'hwndMenuOwner', 'hwndMoveSize', 'hwndCaret'):
        result[key] = int(getattr(info, key) or 0)
    result['caretRect'] = [int(getattr(info.rcCaret, key)) for key in ('left', 'top', 'right', 'bottom')]
    return result


def retain_capture_rejection(api, hwnd, child, thread, info, primary):
    """Best-effort caller catches every retention error and re-raises primary."""
    row = dict(schemaVersion=1, kind='strict-editor-focus-capture-rejection',
        actionOutcomeUnaffected=True, suiteHwnd=int(hwnd), childHwnd=int(child),
        queriedThreadId=int(thread), querySucceeded=True,
        rawGuiThreadInfo=copy_gui_thread_info(info), rawGuiThreadInfoHex=bytes(info).hex(),
        identityLimit='Raw HWNDs from the same rejected GetGUIThreadInfo call; no later owner, generation, dispatch or timing observation.')
    # Attach raw evidence before path validation, count checks or filesystem I/O.
    primary.opengeul_focus_rejection = row
    sequence = getattr(api, '_opengeul_focus_rejection_count', 0)
    assert type(sequence) is int and 0 <= sequence < MAX_RECEIPTS, 'Strict focus rejection receipt limit exceeded'
    api._opengeul_focus_rejection_count = sequence + 1
    output = Path(api.evidence_output)
    assert output.is_absolute() and output.is_dir(), 'Strict focus rejection output is not an absolute directory'
    for part in (output, *output.parents):
        assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked strict focus rejection output'
    name = api.evidence_case
    assert isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name), 'Invalid strict focus rejection case'
    row['receiptIndex'] = sequence
    path = output / (name + '-strict-editor-focus-rejection-' + format(sequence, '03d') + '.json')
    row['receiptPath'] = str(path)
    raw = (json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    assert len(raw) <= MAX_BYTES, 'Strict focus rejection receipt exceeds its finite bound'
    with path.open('xb') as stream:
        stream.write(raw)
