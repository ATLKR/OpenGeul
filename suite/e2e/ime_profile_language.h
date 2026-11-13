#ifndef OPENGEUL_IME_PROFILE_LANGUAGE_H
#define OPENGEUL_IME_PROFILE_LANGUAGE_H
#include <cstdint>
namespace opengeul_ime {
// This memento is captured before activation, never inferred from a requested profile.
struct ProfileLanguageOriginal { uint32_t captured=0, language=0, captureAttempted=0, restoreAttempted=0; };
struct ProfileLanguageRecord {
    uint32_t schemaVersion=0,command=0,status=0,complete=0,originalLanguage=0;
    uint32_t observedBefore=0,observedAfterChange=0,observedAfterHkl=0;
    uint32_t interfaceAttempts=0,getterAttempts=0,changeAttempts=0,observedMask=0;
    int32_t interfaceHresult=0,getBeforeHresult=0,changeHresult=0,getAfterChangeHresult=0,getAfterHklHresult=0;
};
static_assert(sizeof(ProfileLanguageRecord)==68,"Fixed numeric language record");
enum ProfileLanguageFailure:uint32_t { LanguageBoundary=1,LanguageAlreadyCaptured=2,
    LanguageInterface=3,LanguageGetter=4,LanguageOriginalInvalid=5,
    LanguageProfileMismatch=6,LanguageOriginalMissing=7,LanguageChange=8,LanguageReadback=9 };
inline bool LanguageFail(ProfileLanguageRecord& r,uint32_t code){if(!r.status)r.status=code;return false;}
inline bool LanguageCode(uint32_t value){return value>0&&value<=0xffff;}
inline void LanguageStart(ProfileLanguageRecord& r,uint32_t command,const ProfileLanguageOriginal& original){
    r=ProfileLanguageRecord{};r.schemaVersion=1;r.command=command;
    if(original.captured==1)r.originalLanguage=original.language;
}
template<class Api>bool LanguageInterfaceReady(Api& api,ProfileLanguageRecord& r){
    if(!api.Boundary())return LanguageFail(r,LanguageBoundary);
    ++r.interfaceAttempts;r.interfaceHresult=api.Interface();r.observedMask|=1;
    if(!api.Boundary())return LanguageFail(r,LanguageBoundary);
    return r.interfaceHresult==0||LanguageFail(r,LanguageInterface);
}
template<class Api>bool LanguageGet(Api& api,ProfileLanguageRecord& r,uint32_t& value,int32_t& hr,uint32_t mask){
    if(!api.Boundary())return LanguageFail(r,LanguageBoundary);
    uint32_t observed=0;++r.getterAttempts;hr=api.GetLanguage(observed);r.observedMask|=mask;
    if(!api.Boundary())return LanguageFail(r,LanguageBoundary);
    if(hr!=0)return LanguageFail(r,LanguageGetter);
    if(!LanguageCode(observed))return LanguageFail(r,LanguageOriginalInvalid);
    value=observed;return true;
}
template<class Api>bool CaptureProfileLanguage(Api& api,ProfileLanguageOriginal& original,
        ProfileLanguageRecord& r,uint32_t capturedProfileLanguage){
    if(original.captureAttempted||original.captured||original.restoreAttempted)return false;
    original.captureAttempted=1;LanguageStart(r,1,original);
    if(!LanguageCode(capturedProfileLanguage))return LanguageFail(r,LanguageOriginalInvalid);
    if(!LanguageInterfaceReady(api,r)||!LanguageGet(api,r,r.observedBefore,r.getBeforeHresult,2))return false;
    if(r.observedBefore!=capturedProfileLanguage)return LanguageFail(r,LanguageProfileMismatch);
    original.language=r.observedBefore;original.captured=1;
    r.originalLanguage=original.language;r.complete=1;return true;
}
template<class Api>bool PrepareProfileLanguageRestore(Api& api,ProfileLanguageOriginal& original,
        ProfileLanguageRecord& r,uint32_t capturedProfileLanguage){
    if(original.restoreAttempted)return false;
    original.restoreAttempted=1;LanguageStart(r,4,original);
    if(original.captured!=1||!LanguageCode(original.language))return LanguageFail(r,LanguageOriginalMissing);
    if(original.language!=capturedProfileLanguage)return LanguageFail(r,LanguageProfileMismatch);
    if(!LanguageInterfaceReady(api,r)||!LanguageGet(api,r,r.observedBefore,r.getBeforeHresult,2))return false;
    if(r.observedBefore!=original.language){
        if(!api.Boundary())return LanguageFail(r,LanguageBoundary);
        ++r.changeAttempts;r.changeHresult=api.ChangeLanguage(original.language);r.observedMask|=4;
        if(!api.Boundary())return LanguageFail(r,LanguageBoundary);
        if(r.changeHresult!=0)return LanguageFail(r,LanguageChange);
        if(!LanguageGet(api,r,r.observedAfterChange,r.getAfterChangeHresult,8))return false;
        if(r.observedAfterChange!=original.language)return LanguageFail(r,LanguageReadback);
    }
    return true; // The existing single HKL restoration still has to run next.
}
template<class Api>bool VerifyProfileLanguageAfterHkl(Api& api,const ProfileLanguageOriginal& original,
        ProfileLanguageRecord& r){
    if(r.schemaVersion!=1||r.command!=4||r.status||r.complete||original.captured!=1
            ||r.originalLanguage!=original.language)return LanguageFail(r,LanguageOriginalMissing);
    if(!LanguageGet(api,r,r.observedAfterHkl,r.getAfterHklHresult,16))return false;
    if(r.observedAfterHkl!=original.language)return LanguageFail(r,LanguageReadback);
    r.complete=1;return true;
}
} // namespace opengeul_ime
#endif
