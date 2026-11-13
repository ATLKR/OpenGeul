#include "ime_profile_language.h"
#include <cstdint>
#include <iostream>
#include <vector>
using namespace opengeul_ime;
constexpr int32_t Invalid=static_cast<int32_t>(0x80070057u);
struct Fake {
    bool owned=true;int boundaryCalls=0,expireAt=0;int32_t interfaceHr=0,getHr=0,changeHr=0,activateHr=0;
    uint32_t language=0x409,hkl=0x04090409;bool wrongReadback=false;
    std::vector<int> calls;
    bool Boundary(){++boundaryCalls;return owned && (!expireAt || boundaryCalls<expireAt);}
    int32_t Interface(){calls.push_back(1);return interfaceHr;}
    int32_t GetLanguage(uint32_t& out){calls.push_back(2);out=language;return getHr;}
    int32_t ChangeLanguage(uint32_t value){calls.push_back(3);if(!changeHr&&!wrongReadback){language=value;hkl=0xf0010409;}return changeHr;}
    void RestoreHkl(){calls.push_back(4);hkl=0x04090409;}
    int32_t Activate(){calls.push_back(5);return activateHr?activateHr:language==0x409?0:Invalid;}
};
int main(){
    int which=0;
    if(!(std::cin>>which)||which<1||which>14)return 99;
    Fake api;ProfileLanguageOriginal original{};ProfileLanguageRecord record{};
    if(which==3){api.language=0x412;if(CaptureProfileLanguage(api,original,record,0x409)||original.captured||record.status!=LanguageProfileMismatch)return 30;return 0;}
    if(which==4){api.interfaceHr=Invalid;if(CaptureProfileLanguage(api,original,record,0x409)||record.interfaceHresult!=Invalid||api.calls!=std::vector<int>{1})return 40;return 0;}
    if(which==5){api.getHr=Invalid;if(CaptureProfileLanguage(api,original,record,0x409)||record.getBeforeHresult!=Invalid||original.captured)return 50;return 0;}
    if(which==9){api.owned=false;if(CaptureProfileLanguage(api,original,record,0x409)||!api.calls.empty()||original.captured)return 90;return 0;}
    if(which==10){for(int limit=1;limit<=4;++limit){Fake expired;expired.expireAt=limit;ProfileLanguageOriginal o{};if(CaptureProfileLanguage(expired,o,record,0x409)||o.captured||record.status!=LanguageBoundary)return 100+limit;}return 0;}
    if(which==13){for(uint32_t bad:{0u,65536u}){Fake invalid;invalid.language=bad;ProfileLanguageOriginal o{};if(CaptureProfileLanguage(invalid,o,record,0x409)||o.captured)return 130;}return 0;}
    if(!CaptureProfileLanguage(api,original,record,0x409))return 1;
    if(which==6){const auto before=api.calls;if(CaptureProfileLanguage(api,original,record,0x409)||api.calls!=before||original.language!=0x409)return 60;return 0;}
    if(which==1){api.language=0x412;api.RestoreHkl();if(api.Activate()!=Invalid)return 2;}
    api.calls.clear();
    if(which==7||which==8||which==12)api.language=0x412;
    if(which==7)api.changeHr=Invalid;
    if(which==8)api.wrongReadback=true;
    if(which==12)api.owned=false;
    const bool prepared=PrepareProfileLanguageRestore(api,original,record,0x409);
    if(which==7||which==8||which==12){
        if(prepared||record.changeAttempts!=(which==12?0u:1u))return 70;
        const auto before=api.calls;if(PrepareProfileLanguageRestore(api,original,record,0x409)||api.calls!=before)return 71;
        return 0;
    }
    if(!prepared)return 3;
    api.RestoreHkl();if(which==11)api.language=0x412;
    const bool verified=VerifyProfileLanguageAfterHkl(api,original,record);
    if(which==11){if(verified||record.complete||record.status!=LanguageReadback)return 110;return 0;}
    if(!verified||!record.complete||api.language!=0x409||api.hkl!=0x04090409)return 4;
    if(which==14){api.activateHr=Invalid;if(api.Activate()!=Invalid||api.calls.back()!=5)return 140;return 0;}
    if(api.Activate()!=0)return 5;
    const std::vector<int> wanted=which==1?std::vector<int>{1,2,3,2,4,2,5}:std::vector<int>{1,2,4,2,5};
    if(api.calls!=wanted||record.changeAttempts!=(which==1?1u:0u))return 6;
    return 0;
}
