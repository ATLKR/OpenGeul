#pragma once
#include "wire.h"
#include <limits>
namespace opengeul::writer_observer {
struct Descriptor { std::uint32_t controllerPid; std::uint64_t controllerBirth, nonce; };
inline bool descriptor(wchar_t const* text, Descriptor& out) noexcept {
    if (!text) return false;
    Descriptor parsed{};
    auto p=text;
    auto decimal=[&](std::uint64_t maximum,std::uint64_t& n) noexcept {
        n=0;
        if (*p<L'1'||*p>L'9') return false;
        do { auto d=static_cast<unsigned>(*p-L'0');
            if(n>(maximum-d)/10) return false;
            n=n*10+d; ++p;
        } while(*p>=L'0'&&*p<=L'9');
        return *p++==L':';
    };
    if (*p++!=L'1'||*p++!=L':') return false;
    std::uint64_t pid=0;
    if(!decimal(0xffffffffu,pid)||!decimal(UINT64_MAX,parsed.controllerBirth))return false;
    parsed.controllerPid=static_cast<std::uint32_t>(pid);
    for(unsigned i=0;i<16;++i){
        auto c=*p++;unsigned d;
        if(c>=L'0'&&c<=L'9')d=static_cast<unsigned>(c-L'0');
        else if(c>=L'a'&&c<=L'f')d=static_cast<unsigned>(c-L'a'+10);
        else return false;
        parsed.nonce=(parsed.nonce<<4)|d;
    }
    if(!parsed.nonce||*p++!=L':')return false;
    constexpr wchar_t tail[]=L"131328:OpenGeulWriterServerObserver";
    for(auto c:tail) { if(*p++!=c)return false; if(!c)break; }
    out=parsed;
    return true;
}
}
