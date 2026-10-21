"""Separate fixed-width x64/ARM64 ASCII observer receipt ABI."""
import ctypes as C


MAGIC = 0x4f47414b
VERSION = 1
CAPACITY = 4096


class Event(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
        ('sequence', 'actionEpoch', 'origin', 'remove', 'message', 'pid', 'tid', 'messageTime')]
    _fields_ += [(name, C.c_uint64) for name in
        ('hwnd', 'layout', 'wParam', 'lParam', 'extraInfo', 'nativeTick')]
    _fields_ += [(name, C.c_int16) for name in
        ('shiftState', 'controlState', 'altState', 'capsState')]
    _fields_ += [('flags', C.c_uint32), ('reserved', C.c_uint32)]


class State(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
        ('magic', 'version', 'stateSize', 'eventSize', 'capacity', 'pid', 'tid', 'controllerPid',
         'startMessage', 'stopMessage', 'recording', 'ack')]
    _fields_ += [(name, C.c_int32) for name in ('count', 'overflow', 'activeCallbacks', 'status')]
    _fields_ += [(name, C.c_uint32) for name in ('armedIndex', 'armedEpoch', 'command', 'stopAck')]
    _fields_ += [(name, C.c_uint64) for name in ('nonce', 'hwnd', 'engineCreationTime', 'layout')]
    _fields_ += [('events', Event * CAPACITY)]


assert C.sizeof(Event) == 96 and State.events.offset == 112
assert C.sizeof(State) == 112 + CAPACITY * 96


def committed_events(raw, *, after):
    """Decode committed bytes only; the native controller supplies acquire fences.

    A zero commit means an in-flight row, not an event or success. This function
    neither waits nor interprets target queue progress/semantic acceptance.
    """
    assert type(raw) is bytes and len(raw) == C.sizeof(State), 'Truncated ASCII observer state'
    state = State.from_buffer_copy(raw)
    assert (state.magic, state.version, state.stateSize, state.eventSize, state.capacity) == \
        (MAGIC, VERSION, C.sizeof(State), C.sizeof(Event), CAPACITY), 'ASCII observer ABI changed'
    assert not state.overflow and 0 <= state.count <= CAPACITY, 'ASCII observer count/overflow is invalid'
    assert state.status == 0, 'ASCII observer native status failed: ' + str(state.status)
    assert type(after) is int and 0 <= after <= state.count, 'ASCII observer baseline differs'
    result = []
    for index in range(after, state.count):
        row = state.events[index]
        if row.sequence == 0: break
        assert row.sequence == index + 1, 'ASCII observer commit sequence changed'
        assert row.reserved == 0, 'ASCII observer reserved bytes changed'
        result.append({name: int(getattr(row, name)) for name, _ in Event._fields_ if name != 'reserved'})
    return result
