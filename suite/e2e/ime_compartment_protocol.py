"""Bounded owned-compartment receipt; a callback is not proof of its setter."""
import ctypes as C
from ascii_message_protocol import RetrievalFrame
from ime_notification_caller import clean


class Config(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ('version', 'enabled')]


class Lease(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in (
        'installAttempts', 'pinned', 'sourceReady', 'adviseAttempts',
        'subscriptionPossible', 'installed', 'armed', 'disabled', 'claimed',
        'disconnectAttempts', 'unadviseAttempts', 'disconnected', 'released',
        'rejected', 'activeCallbacks')]


class Read(C.Structure):
    _fields_ = [('hr', C.c_int32), ('clearHr', C.c_int32)]
    _fields_ += [(n, C.c_uint32) for n in ('type', 'matched', 'attempts')]


class ApiReceipt(C.Structure):
    _fields_ = [(n, C.c_int32) for n in (
        'managerHr', 'managerInterfaceHr', 'enumerationHr', 'nextHr',
        'compartmentHr', 'sourceHr', 'adviseHr', 'unadviseHr')]
    _fields_ += [(n, C.c_uint32) for n in (
        'referencesAcquired', 'referencesReleased', 'sinkReferences',
        'badSinkReference', 'enumerationCount', 'invalidCookie',
        'variantCleanupFailed', 'apiException', 'callbackException')]
    _fields_ += [('baseline', Read), ('callback', Read)]


class Record(C.Structure):
    _fields_ = [('lease', Lease), ('api', ApiReceipt)]
    _fields_ += [(n, C.c_uint32) for n in (
        'sequence', 'flags', 'frameCount', 'frameCapReached', 'unknownFrames',
        'expired', 'foreignRejected', 'pid', 'tid')]
    _fields_ += [(n, C.c_uint64) for n in (
        'hwnd', 'creationTime', 'baselineCounter', 'counter', 'finishedCounter')]
    _fields_ += [('pluginStatus', C.c_uint32), ('reserved', C.c_uint32)]
    _fields_ += [('pluginStarted', C.c_uint64), ('pluginFinished', C.c_uint64)]
    _fields_ += [('frames', RetrievalFrame * 64)]


def typed_read(read):
    return (read.hr == read.clearHr == 0 and read.type == 3
            and read.matched == read.attempts == 1)


def decode(config, row, *, expected_config, notification_config,
           expected_notification, pid, tid, hwnd, deadline, frequency, command3):
    assert bytes(config) == expected_config, 'Compartment immutable admission changed'
    assert bytes(notification_config) == expected_notification, 'Compartment binding changed'
    assert config.version == 2 and config.enabled in (0, 1)
    result = dict(schemaVersion=2, frameCapacity=64, kind='one-owned-ime-compartment-callback',
                  status='disabled', callerAttributionProved=False,
                  acceptanceEligible=False, processRetirementVerified=False,
                  cleanupStatus='pending')
    if not config.enabled:
        return result
    binding = notification_config
    assert binding.version == binding.enabled == 1 and binding.creationTime > 0
    assert binding.plugin.version == binding.plugin.enabled == 1
    assert deadline > 0 and frequency > 0 and pid > 0 and tid > 0 and hwnd > 0
    assert command3 and command3['success'] is True and command3['nativeAck'] == 3 and command3['status'] == 0, 'Original ACK3 baseline unproved'
    baseline = command3['threadMode']
    assert clean(baseline) and baseline['afterOpenHr'] == baseline['afterConversionHr'] == 0
    assert baseline['afterOpenType'] == baseline['afterConversionType'] == 3
    assert baseline['afterOpen'] == baseline['afterConversion'] == 1
    lease, api = row.lease, row.api
    for name, _ in Lease._fields_:
        value = getattr(lease, name)
        if name not in ('rejected', 'activeCallbacks'):
            assert value in (0, 1), 'Unbounded compartment attempt count'
    assert not lease.rejected & ~511 and row.sequence in (0, 1) and not row.reserved
    assert row.frameCapReached in (0, 1) and 0 <= row.frameCount <= 64
    assert row.frameCapReached == int(row.frameCount == 64)
    assert 0 <= api.referencesReleased <= api.referencesAcquired <= 5
    assert 0 <= api.enumerationCount <= 64
    # Fixed numeric receipts retain failed preparation/cleanup without COM
    # values, exception text, paths, titles, or unclassified stack addresses.
    result['lease'] = {name: int(getattr(lease, name)) for name, _ in Lease._fields_}
    result['api'] = {name: int(getattr(api, name)) for name, _ in ApiReceipt._fields_
                     if name not in ('baseline', 'callback')}
    for name in ('baseline', 'callback'):
        read = getattr(api, name)
        result['api'][name] = {key: int(getattr(read, key)) for key, _ in Read._fields_}
    result.update(status='inconclusive', claimed=bool(lease.claimed),
                  rejected=int(lease.rejected), expired=int(row.expired),
                  foreignRejected=int(row.foreignRejected))
    failed = (lease.rejected or lease.activeCallbacks or row.flags or row.expired
              or row.foreignRejected or api.badSinkReference or api.invalidCookie
              or api.variantCleanupFailed or api.apiException or api.callbackException)
    installed = all(getattr(lease, n) == 1 for n in (
        'installAttempts', 'pinned', 'sourceReady', 'adviseAttempts', 'installed'))
    api_ok = all(getattr(api, n) == 0 for n in (
        'managerHr', 'managerInterfaceHr', 'enumerationHr', 'nextHr',
        'compartmentHr', 'sourceHr', 'adviseHr'))
    source_proved = installed and api_ok and api.referencesAcquired == 5 and 1 <= api.enumerationCount <= 64
    live = (source_proved and lease.armed and lease.subscriptionPossible and not lease.disabled
            and not lease.disconnectAttempts and not lease.unadviseAttempts and not lease.disconnected
            and not lease.released and api.referencesReleased == 0 and api.sinkReferences == 2)
    if lease.disconnectAttempts:
        result['cleanupStatus'] = 'inconclusive'
        if (not failed and source_proved and lease.disabled and not lease.armed
                and not lease.subscriptionPossible and lease.unadviseAttempts
                and lease.disconnected and lease.released and api.unadviseHr == 0
                and api.referencesAcquired == api.referencesReleased == 5
                and api.sinkReferences == 1):
            result['cleanupStatus'] = 'unsubscribed'
    if not lease.claimed:
        assert not row.sequence
        if not failed and lease.installed:
            result['status'] = 'not-triggered'
        return result
    if not row.sequence:
        return result
    assert (row.pid, row.tid, row.hwnd, row.creationTime) == (pid, tid, hwnd, binding.creationTime), 'Foreign compartment callback'
    assert 0 < row.baselineCounter <= row.counter <= row.finishedCounter < deadline, 'Compartment sample outside original clock'
    assert row.counter <= row.pluginStarted <= row.pluginFinished <= row.finishedCounter
    frames = []
    for frame in row.frames[:row.frameCount]:
        assert 0 <= frame.moduleId <= 14 and (frame.moduleId or frame.rva == 0), 'Unknown raw frame was not redacted'
        if frame.moduleId == 14:
            assert row.pluginStatus == 1 and frame.rva >= 4 and frame.rva % 4 == 0
        frames.append(dict(moduleId=int(frame.moduleId), rva=int(frame.rva)))
    assert all(not f.moduleId and not f.rva for f in row.frames[row.frameCount:])
    assert row.unknownFrames == sum(f['moduleId'] == 0 for f in frames)
    if (not failed and source_proved and (live or result['cleanupStatus'] == 'unsubscribed') and typed_read(api.baseline)
            and typed_read(api.callback) and row.frameCount and not row.frameCapReached
            and row.pluginStatus == 1):
        result['status'] = 'complete'
    result.update(pid=pid, tid=tid, hwnd=hwnd, engineCreationTime=int(row.creationTime),
                  deadlineCounter=deadline, counterFrequency=frequency, pluginStatus=int(row.pluginStatus),
                  pluginStarted=int(row.pluginStarted), pluginFinished=int(row.pluginFinished),
                  frames=frames, frameCount=int(row.frameCount),
                  frameCapReached=bool(row.frameCapReached),
                  unknownFrames=int(row.unknownFrames), moduleMapVersion=2,
                  baselineCounter=int(row.baselineCounter), counter=int(row.counter),
                  finishedCounter=int(row.finishedCounter),
                  interpretation='post-change compartment callback; setter attribution requires matched callsite evidence')
    return result
