#pragma once
#include "ime_thread_mode.h"
#include "ascii_message_protocol.h"
namespace opengeul_ime {
struct NotificationConfig {
    uint32_t version,enabled;uint64_t creationTime;OpenGeulAscii::PluginBinding plugin;
};
struct NotificationRecord {
    uint32_t armed,claimed,sequence,rejected,expired,messageSequence,hookSentByCurrentThread,
        flags,frameCount,frameCapReached,unknownFrames,reserved;
    uint64_t baselineCounter,counter,finishedCounter;
    uint32_t pluginStatus,reserved2;uint64_t pluginStarted,pluginFinished;
    OpenGeulAscii::RetrievalFrame frames[16];
};
static_assert(sizeof(NotificationConfig)==2112 && sizeof(NotificationRecord)==224);
inline bool NotificationClean(const ModeReceipt& r) {
    return !r.status && !r.cleanupStatus && !r.variantClearHr && r.releaseCalls==1
        && r.referencesAcquired>0 && r.referencesAcquired==r.referencesReleased;
}
inline bool NotificationBaseline(const ModeReceipt& r) {
    return NotificationClean(r) && r.afterOpenHr==0 && r.afterConversionHr==0
        && r.afterOpenType==3 && r.afterConversionType==3 && r.afterOpen==1 && r.afterConversion==1;
}
inline bool NotificationClosed(const ModeReceipt& r) {
    return NotificationClean(r) && r.beforeOpenHr==0 && r.beforeConversionHr==0
        && r.beforeOpenType==3 && r.beforeConversionType==3 && r.beforeOpen==0
        && !r.openSetCalls && !r.conversionSetCalls;
}
template<class Event,class Mode>
bool ClaimNotification(NotificationRecord& r,const Event& e,const Mode& m,uint32_t command) {
    if(!r.armed || r.claimed || r.sequence || r.rejected || r.expired || command!=3
        || !e.sequence || e.sequence!=m.sequence || e.sequence!=m.messageSequence
        || e.message!=0x282 || e.origin!=1 || e.commandAck!=3
        || e.immContextPresent!=1 || e.immConversionSucceeded!=1 || e.immOpen!=0
        || !NotificationClosed(m.mode) || !r.baselineCounter || r.baselineCounter>e.counter
        || e.counter>m.startedCounter || m.startedCounter>m.finishedCounter)return false;
    r.claimed=1;return true;
}
}
