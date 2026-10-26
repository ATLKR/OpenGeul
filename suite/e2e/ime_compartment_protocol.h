#pragma once
#include "ime_compartment_lease.h"
#include "ime_thread_mode.h"
#include "ascii_message_protocol.h"
namespace opengeul_ime {
struct CompartmentConfig {uint32_t version=1,enabled=0;};
struct CompartmentRead {
    int32_t hr=NotAttempted,clearHr=NotAttempted;
    uint32_t type=0,matched=0,attempts=0;
};
struct CompartmentApiReceipt {
    int32_t managerHr=NotAttempted,managerInterfaceHr=NotAttempted,
        enumerationHr=NotAttempted,nextHr=NotAttempted,compartmentHr=NotAttempted,
        sourceHr=NotAttempted,adviseHr=NotAttempted,unadviseHr=NotAttempted;
    uint32_t referencesAcquired=0,referencesReleased=0,sinkReferences=1,badSinkReference=0,
        enumerationCount=0,invalidCookie=0,variantCleanupFailed=0,apiException=0,callbackException=0;
    CompartmentRead baseline,callback;
};
struct CompartmentRecord {
    CompartmentLeaseRecord lease;
    CompartmentApiReceipt api;
    uint32_t sequence=0,flags=0,frameCount=0,frameCapReached=0,unknownFrames=0,
        expired=0,foreignRejected=0,pid=0,tid=0;
    uint64_t hwnd=0,creationTime=0,baselineCounter=0,counter=0,finishedCounter=0;
    uint32_t pluginStatus=0,reserved=0;
    uint64_t pluginStarted=0,pluginFinished=0;
    OpenGeulAscii::RetrievalFrame frames[16]{};
};
static_assert(sizeof(CompartmentConfig)==8 && sizeof(CompartmentLeaseRecord)==60
    && sizeof(CompartmentRead)==20 && sizeof(CompartmentApiReceipt)==108
    && sizeof(CompartmentRecord)==400);
}
