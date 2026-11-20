#pragma once
#include "ime_thread_mode.h"

namespace opengeul_ime {
// Tagged originals live only in this observer's original hooked-thread context.
struct TypedPair { Value open{}, conversion{}; };
inline bool TypedValue(const Value& value) {
    return (value.hr==0 && value.type==3) || (value.hr==1 && value.type==0);
}
inline bool PairConcrete(const TypedPair& pair) {
    return pair.open.hr==0 && pair.open.type==3 && pair.conversion.hr==0 && pair.conversion.type==3;
}
inline bool PairEmpty(const TypedPair& pair) {
    return pair.open.hr==1 && pair.open.type==0 && pair.conversion.hr==1 && pair.conversion.type==0;
}
inline bool EmptyOriginUsProfile(uint64_t layout,uint32_t type,uint32_t language,
                                 uint64_t profileLayout,bool nullClsid,bool nullProfile) {
    return layout==0x04090409ULL && type==2 && language==0x0409
        && profileLayout==layout && nullClsid && nullProfile;
}
template<class Api> TypedPair ReadTypedBefore(Api& api,ModeReceipt& r) {
    Budget(api,r);const auto open=api.Read(1);
    r.beforeOpenHr=open.hr;r.beforeOpenType=open.type;r.beforeOpen=open.value;
    Require(r,TypedValue(open),-29);Budget(api,r);
    const auto conversion=api.Read(2);
    r.beforeConversionHr=conversion.hr;r.beforeConversionType=conversion.type;r.beforeConversion=conversion.value;
    Require(r,TypedValue(conversion),-30);Budget(api,r);
    return {open,conversion};
}
template<class Api> void CaptureOriginalTypedMode(Api& api,ModeReceipt& r,TypedPair& original,bool allowEmpty) {
    r=ModeReceipt{};Releases<Api> releases{api,r};
    try {
        ExistingCompartments(api,r);const auto pair=ReadTypedBefore(api,r);
        Require(r,PairConcrete(pair) || (allowEmpty && PairEmpty(pair)),-45);
        original=pair;
    } catch (const Failure&) {}
}
template<class Api> void SetEmptyOriginAsciiMode(Api& api,ModeReceipt& r,const TypedPair& original) {
    r=ModeReceipt{};Releases<Api> releases{api,r};
    try {
        Require(r,PairEmpty(original),-45);
        ExistingCompartments(api,r);const auto current=ReadTypedBefore(api,r);
        Require(r,PairEmpty(current) || PairConcrete(current),-45);
        // NEW desired ALPHANUMERIC=0; never an inferred original numeric value.
        r.requestedOpen=1;r.requestedConversion=PairEmpty(current) ? 0 : current.conversion.value&~1;
        Budget(api,r);r.clientQueryHr=api.ClientInterface();r.clientPresent=api.HasClient();
        Require(r,r.clientQueryHr==0 && r.clientPresent,-32);Budget(api,r);
        ++r.clientIdCalls;r.clientHr=api.ObserverClient(r.clientId);
        Require(r,r.clientHr==0 && r.clientId!=0,-32);Budget(api,r);
        ++r.openSetCalls;r.openSetHr=api.Write(1,r.clientId,r.requestedOpen);
        Require(r,r.openSetHr==0,-33);Budget(api,r);
        ++r.conversionSetCalls;r.conversionSetHr=api.Write(2,r.clientId,r.requestedConversion);
        Require(r,r.conversionSetHr==0,-34);Budget(api,r);
        const auto open=api.Read(1);r.afterOpenHr=open.hr;r.afterOpenType=open.type;r.afterOpen=open.value;
        Require(r,open.hr==0 && open.type==3 && open.value==r.requestedOpen,-35);Budget(api,r);
        const auto conversion=api.Read(2);r.afterConversionHr=conversion.hr;r.afterConversionType=conversion.type;r.afterConversion=conversion.value;
        Require(r,conversion.hr==0 && conversion.type==3 && conversion.value==r.requestedConversion,-36);Budget(api,r);
    } catch (const Failure&) {}
}
template<class Api> void CaptureEmptyOriginReturn(Api& api,ModeReceipt& r,const TypedPair& original) {
    r=ModeReceipt{};Releases<Api> releases{api,r};
    try {
        Require(r,PairEmpty(original),-45);ExistingCompartments(api,r);
        ReadTypedBefore(api,r); // Valid mixed final tags are observed inequality.
    } catch (const Failure&) {}
}
} // namespace opengeul_ime
