#pragma once
#include <cstdint>

// The observer supplies only existing, thread-local COM objects. This portable
// policy is also compiled against a deterministic provider by the source tests.
namespace opengeul_ime {
constexpr int32_t NotAttempted = -2147483638; // E_PENDING, never a success claim.
struct Value { int32_t hr; uint32_t type; int32_t value; };
struct ReleaseCounts { uint32_t acquired, released; };
struct ModeReceipt {
    int32_t status=0, cleanupStatus=0;
    int32_t managerHr=NotAttempted, compartmentManagerHr=NotAttempted;
    int32_t enumerationHr=NotAttempted, enumerationNextHr=NotAttempted;
    int32_t openGetHr=NotAttempted, conversionGetHr=NotAttempted;
    int32_t beforeOpenHr=NotAttempted, beforeConversionHr=NotAttempted;
    int32_t clientQueryHr=NotAttempted, clientHr=NotAttempted;
    int32_t openSetHr=NotAttempted, conversionSetHr=NotAttempted;
    int32_t afterOpenHr=NotAttempted, afterConversionHr=NotAttempted;
    uint32_t enumerationCount=0, installedMask=0, clientId=0;
    uint32_t beforeOpenType=0, beforeConversionType=0, afterOpenType=0, afterConversionType=0;
    int32_t beforeOpen=0, beforeConversion=0, requestedOpen=0, requestedConversion=0;
    int32_t afterOpen=0, afterConversion=0;
    uint32_t openSetCalls=0, conversionSetCalls=0, releaseCalls=0;
    uint32_t referencesAcquired=0, referencesReleased=0;
    uint32_t managerPresent=0, compartmentManagerPresent=0, enumeratorPresent=0;
    uint32_t openPresent=0, conversionPresent=0, clientPresent=0, nextFetched=0, clientIdCalls=0;
    uint32_t modulePresent=0, lookupPresent=0, managerCallAttempts=0;
    int32_t variantClearHr=NotAttempted;
};
struct Failure {};
inline void Require(ModeReceipt& r, bool condition, int32_t status) {
    if (!condition) { if (!r.status) r.status=status; throw Failure{}; }
}
template<class Api> void Budget(Api& api, ModeReceipt& r) {
    Require(r, r.status==0, r.status);
    // The caller has already evaluated the original read/type/value predicate.
    // A later VARIANT cleanup failure must block effects without masking it.
    Require(r, r.cleanupStatus==0, -37);
    Require(r, api.WithinBudget(), -20);
}
template<class Api> struct Releases {
    Api& api; ModeReceipt& r;
    ~Releases() {
        const auto counts=api.Release();
        r.referencesAcquired=counts.acquired; r.referencesReleased=counts.released;
        ++r.releaseCalls;
        if (counts.acquired!=counts.released) {
            if (!r.cleanupStatus) r.cleanupStatus=-21;
            if (!r.status) r.status=r.cleanupStatus;
        }
        // Cleanup always runs, including after expiry; its completion cannot
        // acknowledge an operation that has exhausted the original budget.
        if (!r.status && !api.WithinBudget()) r.status=-20;
    }
};
template<class Api> void ExistingCompartments(Api& api, ModeReceipt& r) {
    Budget(api,r); r.managerHr=api.ExistingManager();
    r.managerPresent=api.HasManager();
    Require(r,r.managerHr==0 && r.managerPresent,-22); Budget(api,r);
    r.compartmentManagerHr=api.CompartmentManager();
    r.compartmentManagerPresent=api.HasCompartmentManager();
    Require(r,r.compartmentManagerHr==0 && r.compartmentManagerPresent,-23); Budget(api,r);
    r.enumerationHr=api.BeginEnumeration();
    r.enumeratorPresent=api.HasEnumerator();
    Require(r,r.enumerationHr==0 && r.enumeratorPresent,-24);
    for (uint32_t index=0; index<64 && r.installedMask!=3; ++index) {
        Budget(api,r); int key=0; r.enumerationNextHr=api.Next(key);
        r.nextFetched=api.Fetched();
        if (r.enumerationNextHr==1 && r.nextFetched==0) break;
        Require(r,r.enumerationNextHr==0 && r.nextFetched==1,-25); ++r.enumerationCount;
        if (key==1) r.installedMask|=1;
        if (key==2) r.installedMask|=2;
    }
    // GetCompartment creates a missing compartment. Never call it merely to
    // discover whether a known keyboard compartment exists.
    Require(r,r.installedMask==3,-26); Budget(api,r);
    r.openGetHr=api.Get(1); r.openPresent=api.HasCompartment(1);
    Require(r,r.openGetHr==0 && r.openPresent,-27); Budget(api,r);
    r.conversionGetHr=api.Get(2); r.conversionPresent=api.HasCompartment(2);
    Require(r,r.conversionGetHr==0 && r.conversionPresent,-28); Budget(api,r);
}
template<class Api> void ReadBefore(Api& api, ModeReceipt& r) {
    Budget(api,r); const auto open=api.Read(1);
    r.beforeOpenHr=open.hr; r.beforeOpenType=open.type; r.beforeOpen=open.value;
    Require(r,open.hr==0 && open.type==3,-29); Budget(api,r);
    const auto conversion=api.Read(2);
    r.beforeConversionHr=conversion.hr; r.beforeConversionType=conversion.type;
    r.beforeConversion=conversion.value;
    Require(r,conversion.hr==0 && conversion.type==3,-30); Budget(api,r);
}
template<class Api> void CaptureThreadMode(Api& api, ModeReceipt& r) {
    r=ModeReceipt{}; Releases<Api> releases{api,r};
    try { ExistingCompartments(api,r); ReadBefore(api,r); }
    catch (const Failure&) {}
}
template<class Api> void SetThreadMode(Api& api, ModeReceipt& r, int command,
                                     int32_t originalOpen, int32_t originalConversion) {
    r=ModeReceipt{}; Releases<Api> releases{api,r};
    try {
        Require(r,command==2 || command==3 || command==4,-31);
        ExistingCompartments(api,r); ReadBefore(api,r);
        r.requestedOpen=command==4 ? originalOpen : 1;
        r.requestedConversion=command==4 ? originalConversion :
            command==3 ? r.beforeConversion|1 : r.beforeConversion&~1;
        Budget(api,r); r.clientQueryHr=api.ClientInterface(); r.clientPresent=api.HasClient();
        Require(r,r.clientQueryHr==0 && r.clientPresent,-32); Budget(api,r);
        ++r.clientIdCalls; r.clientHr=api.ObserverClient(r.clientId);
        Require(r,r.clientHr==0 && r.clientId!=0,-32); Budget(api,r);
        ++r.openSetCalls; r.openSetHr=api.Write(1,r.clientId,r.requestedOpen);
        Require(r,r.openSetHr==0,-33); Budget(api,r);
        ++r.conversionSetCalls;
        r.conversionSetHr=api.Write(2,r.clientId,r.requestedConversion);
        Require(r,r.conversionSetHr==0,-34); Budget(api,r);
        const auto open=api.Read(1);
        r.afterOpenHr=open.hr; r.afterOpenType=open.type; r.afterOpen=open.value;
        Require(r,open.hr==0 && open.type==3 && open.value==r.requestedOpen,-35); Budget(api,r);
        const auto conversion=api.Read(2);
        r.afterConversionHr=conversion.hr; r.afterConversionType=conversion.type;
        r.afterConversion=conversion.value;
        Require(r,conversion.hr==0 && conversion.type==3 && conversion.value==r.requestedConversion,-36);
        Budget(api,r);
    } catch (const Failure&) {}
}
} // namespace opengeul_ime
