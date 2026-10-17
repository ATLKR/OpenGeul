"""Bounded US-ASCII editor input, using physical scans rather than VK_PACKET.

This acceptance harness does not change an editor's HKL/IME or retry lost text.
pywinauto 0.6.9 keyboard.py documents VK_PACKET-incompatible applications; its
vk_packet=False path uses keybd_event and maps both cases to the same VK. Here
uppercase explicitly brackets a scan with Left Shift, and SendInput counts and
the exact Win64 INPUT buffers remain independently replayable evidence.

Win32 contracts: learn.microsoft.com/windows/win32/api/winuser/
nf-winuser-sendinput, ns-winuser-keybdinput, nf-winuser-getkeyboardlayout.
SendInput inserts the array serially, but does not reset existing key state.
The letter scans also match the separately verified Korean IME physical probe.
"""
from __future__ import annotations

import ctypes
import time


US_LAYOUT = 0x04090409
SCANS = dict(zip('qwertyuiopasdfghjklzxcvbnm',
    (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
     0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
     0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32)))
SCANS.update(zip('1234567890- ', (*range(2, 12), 0x0c, 0x39)))
SCANS.update({':': 0x27})  # Literal IME scaffold punctuation: Shift + US semicolon.
MODIFIERS = (0x10, 0x11, 0x12, 0xa0, 0xa1, 0xa2, 0xa3, 0xa4, 0xa5, 0x14)


class KeyboardInput(ctypes.Structure):
    _fields_ = [('wVk', ctypes.c_uint16), ('wScan', ctypes.c_uint16),
                ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32),
                ('dwExtraInfo', ctypes.c_uint64)]


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', ctypes.c_int32), ('dy', ctypes.c_int32), ('mouseData', ctypes.c_uint32),
                ('dwFlags', ctypes.c_uint32), ('time', ctypes.c_uint32), ('dwExtraInfo', ctypes.c_uint64)]


class InputPayload(ctypes.Union):
    _fields_ = [('keyboard', KeyboardInput), ('mouse', MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('payload', InputPayload)]


def ascii_actions(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 256:
        raise ValueError('A bounded, nonempty ASCII editor marker is required')
    result = []
    for index, char in enumerate(text):
        if char.lower() not in SCANS or not char.isascii():
            raise ValueError('Unsupported ASCII editor character: ' + repr(char))
        scans = ([0x2a] if char.isupper() or char == ':' else []) + [SCANS[char.lower()]]
        events = [{'vk': 0, 'scan': scan, 'flags': 8} for scan in scans]
        events += [{'vk': 0, 'scan': scan, 'flags': 10} for scan in reversed(scans)]
        result.append({'index': index, 'character': char, 'events': events})
    return result


def input_buffer(events):
    payload = (Input * len(events))()
    for item, event in zip(payload, events):
        item.type = 1  # INPUT_KEYBOARD
        item.payload.keyboard = KeyboardInput(event['vk'], event['scan'], event['flags'], 0, 0)
    return payload


def _require_snapshot(snapshot):
    assert snapshot.get('foregroundVerified') is True and snapshot.get('editorFocusVerified') is True, 'Unverified owned editor focus'
    assert type(snapshot.get('focusHwnd')) is int and snapshot['focusHwnd'] > 0, 'Missing editor focus HWND'
    assert type(snapshot.get('editorThreadId')) is int and snapshot['editorThreadId'] > 0, 'Missing editor input thread'
    assert snapshot.get('targetLayout') == snapshot.get('currentThreadLayout') == US_LAYOUT, 'Physical ASCII input requires exact English US layout'
    assert snapshot.get('keysDown') == [], 'Physical ASCII input requires neutral Shift/Ctrl/Alt/Caps Lock keys'
    assert snapshot.get('capsLockOn') is False, 'Physical ASCII input requires Caps Lock off'


def require_ascii_receipt(receipt, expected_text, document_hwnd, child_hwnd):
    """Replay immutable input intent/counts without trusting the producer's success flags."""
    plan = ascii_actions(expected_text)
    assert receipt.get('schemaVersion') == 1 and receipt.get('success') is True, 'Incomplete ASCII input receipt'
    assert receipt.get('text') == expected_text, 'ASCII receipt has a different exact marker'
    assert receipt.get('inputMethod') == 'SendInput-scancode' and receipt.get('unicodeInputUsed') is False, 'ASCII input must use physical scan codes'
    assert receipt.get('documentHwnd') == document_hwnd > 0 and receipt.get('childHwnd') == child_hwnd > 0, 'ASCII input targets a different owned editor'
    assert receipt.get('inputSize') == 40 and receipt.get('pauseSeconds') in (0.025, 0.04), 'Unexpected ASCII input ABI or original character pacing'
    actions = receipt.get('actions', [])
    assert len(actions) == len(plan), 'ASCII input action count differs from exact marker'
    thread = actions[0].get('before', {}).get('editorThreadId')
    for action, expected in zip(actions, plan):
        assert all(action.get(key) == expected[key] for key in ('index', 'character', 'events')), 'ASCII scan plan changed text or case'
        assert action.get('bufferHex') == bytes(input_buffer(expected['events'])).hex(), 'ASCII raw INPUT buffer differs from its exact scan plan'
        assert action.get('requested') == action.get('inserted') == len(expected['events']), 'ASCII SendInput was not fully inserted'
        assert 'cleanup' not in action, 'A partial ASCII input cannot become a successful receipt'
        _require_snapshot(action.get('before', {}))
        _require_snapshot(action.get('after', {}))
        assert action['before']['editorThreadId'] == action['after']['editorThreadId'] == thread, 'ASCII editor input thread changed'
    return receipt


def _snapshot(api, hwnd, child):
    api.require_foreground(hwnd)
    focus = api.require_editor_focus(hwnd, child)
    tid = int(api.user.GetWindowThreadProcessId(focus, None))
    snapshot = {'focusHwnd': focus, 'editorThreadId': tid,
                'targetLayout': int(api.user.GetKeyboardLayout(tid) or 0),
                'currentThreadLayout': int(api.user.GetKeyboardLayout(0) or 0),
                'keysDown': [key for key in MODIFIERS if api.user.GetAsyncKeyState(key) & 0x8000],
                'capsLockOn': bool(api.user.GetKeyState(0x14) & 1),
                'foregroundVerified': True, 'editorFocusVerified': True}
    return snapshot


def _release_inserted_prefix(user, events, inserted, action):
    # Only keys in the serially inserted prefix belong to this action. Never
    # release a pre-existing/foreign modifier or resend any character keydown.
    held = []
    for event in events[:inserted]:
        if event['flags'] & 2:
            held.remove(event['scan'])
        else:
            held.append(event['scan'])
    if not held: return
    events = [{'vk': 0, 'scan': scan, 'flags': 10} for scan in reversed(held)]
    payload = input_buffer(events)
    cleanup = action['cleanup'] = {'events': events, 'bufferHex': bytes(payload).hex(), 'requested': len(events)}
    try:
        cleanup['inserted'] = int(user.SendInput(len(events), payload, 40))
        assert cleanup['inserted'] == len(events), 'Owned ASCII key-up cleanup was only partially inserted'
    except Exception as exc:
        cleanup['error'] = type(exc).__name__ + ': ' + str(exc)


def type_ascii(api, hwnd, child, text, record, *, pause):
    plan = ascii_actions(text)  # Validate the entire marker before inserting anything.
    assert ctypes.sizeof(ctypes.c_void_p) == 8 and ctypes.sizeof(Input) == 40, 'ASCII input requires the exact Win64 INPUT ABI'
    assert pause in (0.025, 0.04), 'Preserve the existing editor input pacing'
    user = api.user
    user.SendInput.argtypes, user.SendInput.restype = (ctypes.c_uint32, ctypes.POINTER(Input), ctypes.c_int), ctypes.c_uint32
    user.GetKeyboardLayout.argtypes, user.GetKeyboardLayout.restype = (ctypes.c_uint32,), ctypes.c_void_p
    user.GetAsyncKeyState.argtypes, user.GetAsyncKeyState.restype = (ctypes.c_int,), ctypes.c_int16
    user.GetKeyState.argtypes, user.GetKeyState.restype = (ctypes.c_int,), ctypes.c_int16
    receipt = {'schemaVersion': 1, 'text': text, 'inputMethod': 'SendInput-scancode',
               'unicodeInputUsed': False, 'pauseSeconds': pause, 'documentHwnd': hwnd,
               'childHwnd': child, 'inputSize': 40, 'actions': [], 'success': False}
    record.setdefault('asciiEditorInputs', []).append(receipt)
    try:
        thread = None
        for expected in plan:
            action = {**expected, 'before': _snapshot(api, hwnd, child)}
            receipt['actions'].append(action)
            _require_snapshot(action['before'])
            if thread is None: thread = action['before']['editorThreadId']
            assert action['before']['editorThreadId'] == thread, 'ASCII editor input thread changed'
            payload = input_buffer(action['events'])
            action.update(bufferHex=bytes(payload).hex(), requested=len(payload))
            action['inserted'] = int(user.SendInput(len(payload), payload, 40))
            if action['inserted'] != len(payload):
                if 0 <= action['inserted'] < len(payload):
                    _release_inserted_prefix(user, action['events'], action['inserted'], action)
                raise AssertionError(f"ASCII SendInput inserted {action['inserted']} of {len(payload)} events at character {action['index']}")
            time.sleep(pause)
            action['after'] = _snapshot(api, hwnd, child)
            _require_snapshot(action['after'])
            assert action['after']['editorThreadId'] == thread, 'ASCII editor input thread changed'
        receipt['success'] = True
        require_ascii_receipt(receipt, text, hwnd, child)
        return receipt
    except Exception as exc:
        receipt.update(success=False, error=type(exc).__name__ + ': ' + str(exc))
        raise
