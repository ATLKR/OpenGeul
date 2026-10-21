#pragma once
#include "ime_thread_mode.h"

// Diagnostic only: exact typed observation, never production IME acceptance.
namespace opengeul_ime {
inline bool OriginalUsProfile(uint64_t layout, uint32_t type, uint32_t language,
                              uint64_t profileLayout, bool nullClsid, bool nullProfile) {
    return layout==0x04090409ULL && type==2 && language==0x0409
        && profileLayout==layout && nullClsid && nullProfile;
}
inline bool DiagnosticValue(const Value& value) {
    return (value.hr==0 && value.type==3) || (value.hr==1 && value.type==0);
}
template<class Api> void CaptureTypedBoth(Api& api, ModeReceipt& r) {
    r=ModeReceipt{}; Releases<Api> releases{api,r};
    try {
        ExistingCompartments(api,r);
        Budget(api,r); const auto open=api.Read(1);
        r.beforeOpenHr=open.hr; r.beforeOpenType=open.type; r.beforeOpen=open.value;
        Require(r,DiagnosticValue(open),-29); Budget(api,r);
        const auto conversion=api.Read(2);
        r.beforeConversionHr=conversion.hr; r.beforeConversionType=conversion.type;
        r.beforeConversion=conversion.value;
        Require(r,DiagnosticValue(conversion),-30); Budget(api,r);
    } catch (const Failure&) {}
}
} // namespace opengeul_ime
