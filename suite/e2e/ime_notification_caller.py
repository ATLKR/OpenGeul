"""Decode one owned closure delivery stack; never infer the state setter."""
import ctypes as C
from ascii_message_protocol import PluginBinding, RetrievalFrame, RETRIEVAL_MODULES

class Config(C.Structure):
    _fields_=[('version',C.c_uint32),('enabled',C.c_uint32),('creationTime',C.c_uint64),('plugin',PluginBinding)]

class Record(C.Structure):
    _fields_=[(n,C.c_uint32) for n in ('armed','claimed','sequence','rejected','expired','messageSequence',
        'hookSentByCurrentThread','flags','frameCount','frameCapReached','unknownFrames','reserved')]
    _fields_ += [(n,C.c_uint64) for n in ('baselineCounter','counter','finishedCounter')]
    _fields_ += [('pluginStatus',C.c_uint32),('reserved2',C.c_uint32),('pluginStarted',C.c_uint64),('pluginFinished',C.c_uint64)]
    _fields_ += [('frames',RetrievalFrame*16)]


def clean(mode):
    return (all(mode[k]==0 for k in ('status','cleanupStatus','variantClearHr'))
        and mode['releaseCalls']==1 and mode['referencesAcquired']==mode['referencesReleased']>0)


def closed(event):
    r=event['threadMode'];i=event['imm']
    return (event['message']==0x282 and event['origin']==1 and event['commandAck']==3
        and clean(r) and r['beforeOpenHr']==r['beforeConversionHr']==0
        and r['beforeOpenType']==r['beforeConversionType']==3 and r['beforeOpen']==0
        and r['openSetCalls']==r['conversionSetCalls']==0
        and i['contextPresent']==i['conversionSucceeded']==1 and i['open']==0)


def decode(config,row,*,expected_config,messages,modes,command3,pid,tid,hwnd,deadline,frequency):
    assert bytes(config)==expected_config,'Notification immutable admission changed'
    assert config.version==1 and config.enabled in (0,1),'Notification configuration invalid'
    result=dict(schemaVersion=1,kind='one-owned-ime-close-delivery-stack',acceptanceEligible=False,
                callerAttributionProved=False,status='disabled')
    if not config.enabled:return result
    assert config.creationTime>0 and deadline>0 and frequency>0
    assert not row.reserved and not row.reserved2 and row.armed in (0,1) and row.claimed in (0,1) and row.sequence in (0,1)
    assert row.hookSentByCurrentThread in (0,1) and not row.flags&~30
    result.update(status='inconclusive',armed=bool(row.armed),claimed=bool(row.claimed),
        expired=int(row.expired),rejected=int(row.rejected),engineCreationTime=int(config.creationTime),
        pid=pid,tid=tid,hwnd=hwnd,deadlineCounter=deadline,counterFrequency=frequency)
    if row.expired or row.rejected or messages['status']!='complete' or modes['status']!='complete':return result
    if not row.armed:return result
    assert command3 and command3['success'] is True and command3['nativeAck']==3 and command3['status']==0,'Original ACK3 baseline unproved'
    baseline=command3['threadMode']
    assert clean(baseline) and baseline['afterOpenHr']==baseline['afterConversionHr']==0
    assert baseline['afterOpenType']==baseline['afterConversionType']==3 and baseline['afterOpen']==baseline['afterConversion']==1
    assert 0<row.baselineCounter<deadline,'Notification baseline outside original clock'
    if not row.claimed:
        assert not row.sequence
        result['status']='not-triggered';return result
    if not row.sequence:return result
    seq=int(row.messageSequence)
    assert 1<=seq<=len(messages['events']) and seq<=len(modes['events']),'Notification sequence outside publication'
    message=messages['events'][seq-1];mode=modes['events'][seq-1]
    assert message['sequence']==mode['messageSequence']==seq
    assert (message['pid'],message['tid'],message['hwnd'])==(pid,tid,hwnd),'Foreign notification message'
    assert message['message']==mode['message']==0x282 and message['origin']==mode['origin']==1
    assert message['commandAck']==mode['commandAck']==3 and message['counter']==mode['messageCounter']
    assert closed(mode),'Selected notification was not a typed joint closure'
    eligible=[e['messageSequence'] for e in modes['events'] if closed(e)]
    assert eligible and eligible[0]==seq,'A later closure replaced the first valid sample'
    assert 0<row.baselineCounter<=message['counter']<=mode['startedCounter']<=mode['finishedCounter']<=row.counter<=row.finishedCounter<deadline,'Notification sample outside original ordering/budget'
    assert 0<=row.frameCount<=16 and row.frameCapReached==int(row.frameCount==16)
    frames=[]
    for f in row.frames[:row.frameCount]:
        assert 0<=f.moduleId<=14 and (f.moduleId or f.rva==0),'Unknown raw frame was not redacted'
        if f.moduleId==14:
            assert config.plugin.enabled==1 and row.pluginStatus==1,'Private plugin origin unproved'
            assert f.rva>=4 and f.rva%4==0,'Invalid native ARM64 return RVA'
        frames.append(dict(moduleId=int(f.moduleId),rva=int(f.rva)))
    assert all(not f.moduleId and not f.rva for f in row.frames[row.frameCount:]),'Trailing frames must remain empty'
    assert row.unknownFrames==sum(f['moduleId']==0 for f in frames)
    if config.plugin.enabled:
        assert row.counter<=row.pluginStarted<=row.pluginFinished<=row.finishedCounter
    else:assert row.pluginStatus==row.pluginStarted==row.pluginFinished==0
    result.update(status='complete' if row.frameCount and not row.flags and (not config.plugin.enabled or row.pluginStatus==1) else 'inconclusive',
        messageSequence=seq,hookSentByCurrentThread=bool(row.hookSentByCurrentThread),
        baselineCounter=int(row.baselineCounter),counter=int(row.counter),finishedCounter=int(row.finishedCounter),
        flags=int(row.flags),frameCount=int(row.frameCount),frameCapReached=bool(row.frameCapReached),
        unknownFrames=int(row.unknownFrames),frames=frames,pluginStatus=int(row.pluginStatus),
        pluginStarted=int(row.pluginStarted),pluginFinished=int(row.pluginFinished),moduleMapVersion=2,
        interpretation='notification delivery stack; not necessarily the compartment setter')
    return result
