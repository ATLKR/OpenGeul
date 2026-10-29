#pragma once
#include <cstdint>
#include <cstddef>

// Caller supplies the original clock/ownership gate and immutable plugin proof.
// No raw addresses or module paths leave this function.
namespace opengeul_stack {
static const wchar_t* const Modules[]={L"mergedlo.dll",L"vcllo.dll",L"sal3.dll",L"user32.dll",L"win32u.dll",L"ntdll.dll",L"kernel32.dll",L"kernelbase.dll",L"combase.dll",L"ole32.dll",L"imm32.dll",L"msctf.dll",L"imkrtip.dll",L"vclplug_winlo.dll"};
template<class Row,class Clock,class Qualify>
bool Capture(Row& row,Clock clock,Qualify qualify,bool pluginEnabled) {
    constexpr auto capacity=sizeof(row.frames)/sizeof(row.frames[0]);
    static_assert(capacity==16 || capacity==64);
    void* addresses[capacity]{};
    struct Clear {void** p;~Clear(){for(unsigned i=0;i<capacity;++i)*reinterpret_cast<void* volatile*>(p+i)=nullptr;}} clear{addresses};
    if(!clock())return false;
    const auto count=CaptureStackBackTrace(0,capacity,addresses,nullptr);
    if(!clock())return false;
    if(count>capacity){row.flags|=16;return false;}
    row.frameCount=count;row.frameCapReached=count==capacity?1:0;
    if(!count)row.flags|=2;
    HMODULE modules[14]{};
    for(unsigned i=0;i<14;++i) {
        if(i==13 && !pluginEnabled)continue;
        if(!clock())return false;
        modules[i]=GetModuleHandleW(Modules[i]);
        if(!clock())return false;
    }
    if(pluginEnabled) {
        if(!clock())return false;
        const auto status=qualify(modules[13]);
        if(!clock() || !status)return false;
        if(status!=1)modules[13]=nullptr;
    }
    for(unsigned i=0;i<count;++i) {
        HMODULE module=nullptr,again=nullptr;
        if(!clock())return false;
        const bool mapped=GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<const wchar_t*>(addresses[i]),&module)!=0;
        if(!clock())return false;
        if(!mapped)row.flags|=4;
        unsigned id=0;
        for(unsigned j=0;j<14;++j)if(module && module==modules[j]){id=j+1;break;}
        if(mapped && id) {
            if(!clock())return false;
            const bool remapped=GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<const wchar_t*>(addresses[i]),&again)!=0;
            if(!clock())return false;
            if(!remapped)row.flags|=4;
            if(!clock())return false;
            const auto named=GetModuleHandleW(Modules[id-1]);
            if(!clock())return false;
            const auto address=reinterpret_cast<std::uintptr_t>(addresses[i]),base=reinterpret_cast<std::uintptr_t>(module);
            if(remapped && again==module && named==module && address>=base && address-base<=0xffffffffu) {
                row.frames[i].moduleId=id;row.frames[i].rva=static_cast<std::uint32_t>(address-base);
            } else row.flags|=8;
        }
        if(!row.frames[i].moduleId)++row.unknownFrames;
    }
    return true;
}
}
