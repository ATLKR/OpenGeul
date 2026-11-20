#pragma once
#include <cstdint>

namespace opengeul_ime {
// Callback state and its module remain allocated until the original engine exits.
// API.Check binds every operation to the original target and caller's current
// command budget. Disconnect uses command4's existing budget, never a renewed
// observation deadline. No destructor guesses that an uncertain sink is gone.
struct CompartmentLeaseRecord {
    uint32_t installAttempts=0,pinned=0,sourceReady=0,adviseAttempts=0,
        subscriptionPossible=0,installed=0,armed=0,disabled=0,claimed=0,
        disconnectAttempts=0,unadviseAttempts=0,disconnected=0,released=0,
        rejected=0,activeCallbacks=0;
};
enum CompartmentRejection : uint32_t {
    LeaseRepeated=1,LeaseBoundary=2,LeasePin=4,LeaseSource=8,LeaseAdvise=16,
    LeaseBaseline=32,LeaseUnadvise=64,LeaseRelease=128,LeaseCallback=256
};
inline bool RejectCompartment(CompartmentLeaseRecord& r,uint32_t reason) {
    r.rejected|=reason;r.disabled=1;r.armed=0;return false;
}
template<class Api>
bool InstallCompartment(Api& api,CompartmentLeaseRecord& r) {
    if(r.installAttempts)return RejectCompartment(r,LeaseRepeated);
    r.installAttempts=1;
    if(!api.Check())return RejectCompartment(r,LeaseBoundary);
    r.pinned=api.Pin()?1:0;
    if(!r.pinned)return RejectCompartment(r,LeasePin);
    if(!api.Check())return RejectCompartment(r,LeaseBoundary);
    r.sourceReady=api.AcquireExistingSource()?1:0;
    if(!r.sourceReady)return RejectCompartment(r,LeaseSource);
    if(!api.Check())return RejectCompartment(r,LeaseBoundary);
    r.adviseAttempts=1;
    r.subscriptionPossible=1; // Ownership survives an incomplete/exceptional call too.
    const bool advised=api.Advise();
    // Retain possible subscription even when Advise reports failure or returns
    // after its deadline. Only explicit disconnect or process exit ends it.
    r.subscriptionPossible=api.SubscriptionPossible()?1:0;
    if(!advised || !r.subscriptionPossible)return RejectCompartment(r,LeaseAdvise);
    if(!api.Check())return RejectCompartment(r,LeaseBoundary);
    if(!api.ReadOpenOne())return RejectCompartment(r,LeaseBaseline);
    if(!api.Check())return RejectCompartment(r,LeaseBoundary);
    r.installed=1;return true;
}
inline bool ArmCompartment(CompartmentLeaseRecord& r,bool originalBoundary) {
    if(!r.installed || r.disabled || r.armed || !originalBoundary)
        return RejectCompartment(r,LeaseBoundary);
    r.armed=1;return true;
}
inline bool CompartmentNeedsBoundary(CompartmentLeaseRecord& r,uint32_t activeCallbacks) {
    if(!r.armed || r.disabled)return false;
    if(activeCallbacks!=1)return RejectCompartment(r,LeaseCallback);
    return !r.claimed;
}
inline bool ClaimCompartment(CompartmentLeaseRecord& r,bool originalTarget,
                             bool withinDeadline,uint32_t ack,bool activeCommand,uint32_t activeCallbacks) {
    // A nested callback must poison an outer sample even after it was claimed.
    if(!CompartmentNeedsBoundary(r,activeCallbacks))return false;
    if(!originalTarget || !withinDeadline || ack!=3 || activeCommand)
        return RejectCompartment(r,LeaseCallback);
    // Claim before GetValue. A failed, nonzero or untyped first read is never
    // replaced by a later callback that happens to fit the hypothesis.
    r.claimed=1;return true;
}
template<class Api>
bool DisconnectCompartment(Api& api,CompartmentLeaseRecord& r) {
    r.disabled=1;r.armed=0;
    if(r.disconnectAttempts)return RejectCompartment(r,LeaseRepeated);
    r.disconnectAttempts=1;
    if(!api.CallbacksIdle(r) || !api.Check())return RejectCompartment(r,LeaseBoundary);
    if(r.subscriptionPossible) {
        r.unadviseAttempts=1;
        if(!api.Unadvise())return RejectCompartment(r,LeaseUnadvise);
        r.disconnected=1;r.subscriptionPossible=0;
        if(!api.Check())return RejectCompartment(r,LeaseBoundary);
    }
    if(!api.CallbacksIdle(r))return RejectCompartment(r,LeaseCallback);
    r.released=api.ReleaseOwned()?1:0;
    if(!r.released)return RejectCompartment(r,LeaseRelease);
    if(!api.CallbacksIdle(r) || !api.Check())return RejectCompartment(r,LeaseBoundary);
    return true;
}
}
