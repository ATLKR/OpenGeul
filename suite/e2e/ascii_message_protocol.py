"""Separate fixed-width x64/ARM64 ASCII observer receipt ABI."""
import ctypes as C


MAGIC = 0x4f47414b
VERSION = 2
CAPACITY = 4096


class Event(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
        ('sequence', 'actionEpoch', 'origin', 'remove', 'message', 'pid', 'tid', 'messageTime')]
    _fields_ += [(name, C.c_uint64) for name in
        ('hwnd', 'layout', 'wParam', 'lParam', 'extraInfo', 'nativeTick')]
    _fields_ += [(name, C.c_int16) for name in
        ('shiftState', 'controlState', 'altState', 'capsState')]
    _fields_ += [('flags', C.c_uint32), ('reserved', C.c_uint32)]


class QueueSample(C.Structure):
    _fields_ = [('status', C.c_int32)]
    _fields_ += [(name, C.c_uint32) for name in
        ('queueFlags', 'queueStatus', 'keyboardSucceeded', 'keyboardError', 'callbackDepth', 'pid', 'tid')]
    _fields_ += [(name, C.c_uint64) for name in ('hwnd', 'engineCreationTime', 'layout', 'tickStarted', 'tickFinished')]
    _fields_ += [('keyboard', C.c_uint8 * 256)]


class Readiness(C.Structure):
    _fields_ = [('request', C.c_uint32), ('ack', C.c_uint32), ('sample', QueueSample)]


TRACE_VERSION = 1
TRACE_CAPACITY = 128

class TraceEvent(C.Structure):
    _fields_ = [(name,C.c_uint32) for name in ('sequence','origin','message','vk','pid','tid','reserved','flags')]
    _fields_ += [(name,C.c_uint64) for name in ('hwnd','engineCreationTime','focusHwnd','captureHwnd','counter','frequency','nativeTick','lParam','layout')]

CAPTURE_VERSION=1
CAPTURE_CAPACITY=128
SAL_POST_FOCUS=0x485
SAL_CAPTURE_MOUSE=0x48c
SAL_RELEASE_MOUSE=0x48d
CAPTURE_MESSAGES=(0x201,0x202,0x204,0x205,0x207,0x208,0x20b,0x20c,0x215,7,8,0x485,0x48c,0x48d)

class CaptureEvent(C.Structure):
    _fields_=[(name,C.c_uint32) for name in ('sequence','origin','message','pid','tid','callbackDepth','removeFlags','reserved')]
    _fields_ += [(name,C.c_uint64) for name in ('hwnd','engineCreationTime','focusHwnd','captureHwnd','counter','finishedCounter','frequency','nativeTick','wParam','lParam')]

RETRIEVAL_VERSION=1
RETRIEVAL_CAPACITY=3
RETRIEVAL_FRAMES=16
RETRIEVAL_MODULES={1:'mergedlo.dll',2:'vcllo.dll',3:'sal3.dll',4:'user32.dll',5:'win32u.dll',6:'ntdll.dll',7:'kernel32.dll',8:'kernelbase.dll',9:'combase.dll',10:'ole32.dll',11:'imm32.dll',12:'msctf.dll',13:'imkrtip.dll'}
PLUGIN_MODULE_ID=14
PLUGIN_PATH_CAPACITY=1024
class PluginBinding(C.Structure):
    _fields_=[(name,C.c_uint32) for name in ('version','enabled','pathLength','reserved')]
    _fields_ += [('volume',C.c_uint64),('size',C.c_uint64),('fileId',C.c_uint8*16),('path',C.c_uint16*PLUGIN_PATH_CAPACITY)]
class PluginOriginSample(C.Structure):
    _fields_=[(name,C.c_uint32) for name in ('sequence','captureSequence','bucket','status')]
    _fields_ += [('counter',C.c_uint64),('finishedCounter',C.c_uint64)]

def encode_plugin_binding(value):
    result=PluginBinding(version=1)
    if value is None:return result
    assert type(value) is dict and set(value)=={'path','volume','size','fileId','architecture'}
    path=value['path']
    assert value['architecture']=='arm64' and type(path) is str and '\x00' not in path
    assert len(path)>3 and path[0].isascii() and path[0].isalpha() and path[1:3]==':\\' and path.endswith('\\vclplug_winlo.dll')
    raw=path.encode('utf-16-le');length=len(raw)//2
    assert 0<length<PLUGIN_PATH_CAPACITY
    assert type(value['volume']) is int and 0<=value['volume']<2**64
    assert type(value['size']) is int and 0<value['size']<=32*1024*1024
    assert type(value['fileId']) is bytes and len(value['fileId'])==16 and any(value['fileId'])
    result.enabled=1;result.pathLength=length;result.volume=value['volume'];result.size=value['size']
    result.fileId[:]=value['fileId']
    for index in range(length):result.path[index]=int.from_bytes(raw[index*2:index*2+2],'little')
    return result
class RetrievalFrame(C.Structure):
    _fields_=[('moduleId',C.c_uint32),('rva',C.c_uint32)]
class RetrievalEvent(C.Structure):
    _fields_=[(name,C.c_uint32) for name in ('sequence','captureSequence','bucket','message','removeFlags','pid','tid','flags')]
    _fields_ += [(name,C.c_uint64) for name in ('hwnd','engineCreationTime','counter','finishedCounter','frequency','lParam')]
    _fields_ += [(name,C.c_int32) for name in ('pointX','pointY','clientOriginX','clientOriginY')]
    _fields_ += [(name,C.c_uint32) for name in ('originSucceeded','originError','stackRequested','frameCount','frameCapReached','unknownFrames','reserved0','reserved1')]
    _fields_ += [('frames',RetrievalFrame*RETRIEVAL_FRAMES)]

class State(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
        ('magic', 'version', 'stateSize', 'eventSize', 'capacity', 'pid', 'tid', 'controllerPid',
         'startMessage', 'stopMessage', 'recording', 'ack')]
    _fields_ += [(name, C.c_int32) for name in ('count', 'overflow', 'activeCallbacks', 'status')]
    _fields_ += [(name, C.c_uint32) for name in ('armedIndex', 'armedEpoch', 'command', 'stopAck')]
    _fields_ += [(name, C.c_uint64) for name in ('nonce', 'hwnd', 'engineCreationTime', 'layout')]
    _fields_ += [('readinessMessage', C.c_uint32), ('readinessReserved', C.c_uint32), ('readiness', Readiness)]
    _fields_ += [('events', Event * CAPACITY)]
    _fields_ += [('traceVersion',C.c_uint32),('traceEnabled',C.c_uint32),('traceCount',C.c_int32),('traceOverflow',C.c_int32),('traceRejected',C.c_uint32),('traceReserved',C.c_uint32),('traceEvents',TraceEvent * TRACE_CAPACITY)]
    _fields_ += [('captureVersion',C.c_uint32),('captureEnabled',C.c_uint32),('captureCount',C.c_int32),('captureOverflow',C.c_int32)]
    _fields_ += [(name,C.c_uint32) for name in ('captureRejected','captureExpired','captureReserved','capturePadding')]
    _fields_ += [('captureDeadline',C.c_uint64),('captureFrequency',C.c_uint64),('captureEvents',CaptureEvent * CAPTURE_CAPACITY)]
    _fields_ += [(name,C.c_uint32) for name in ('retrievalVersion','retrievalClaimed','retrievalRejected','retrievalExpired')]
    _fields_ += [('retrievalEvents',RetrievalEvent*RETRIEVAL_CAPACITY)]
    _fields_ += [('pluginBinding',PluginBinding),('pluginOrigins',PluginOriginSample*RETRIEVAL_CAPACITY)]


assert C.sizeof(Event) == 96 and State.events.offset == 456
assert C.sizeof(QueueSample) == 328 and C.sizeof(Readiness) == 336 and State.readiness.offset == 120
assert C.sizeof(TraceEvent) == 104 and State.traceVersion.offset == 456 + CAPACITY * 96
assert State.captureVersion.offset == 407008 and C.sizeof(CaptureEvent) == 112
assert State.retrievalVersion.offset==421392 and C.sizeof(RetrievalEvent)==256
assert State.pluginBinding.offset==422176 and C.sizeof(PluginBinding)==2096
assert C.sizeof(PluginOriginSample)==32 and C.sizeof(State)==424368


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
