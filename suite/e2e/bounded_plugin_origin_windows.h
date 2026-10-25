#pragma once
#include <cstdint>
#include <cstring>

namespace opengeul_stack {
template<class Binding,class Clock>
std::uint32_t PluginOrigin(HMODULE module,const Binding& binding,const Binding& frozen,Clock current) {
    const auto expected=binding;
    if(!module || expected.version!=1 || expected.enabled!=1 || expected.reserved
       || !expected.pathLength || expected.pathLength>=1024
       || expected.path[expected.pathLength] || !expected.size || expected.size>32u*1024u*1024u
       || std::memcmp(&expected,&frozen,sizeof(expected))!=0)return 2;
    wchar_t path[1024]{};
    const auto samePath=[&](DWORD length) {
        if(length!=expected.pathLength)return false;
        for(std::uint32_t i=0;i<length;++i)if(path[i]!=expected.path[i])return false;
        return path[length]==0;
    };
    if(!current())return 0;
    auto length=GetModuleFileNameW(module,path,1024);
    if(!current())return 0;
    if(!samePath(length))return 2;
    if(!current())return 0;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==nullptr || file==INVALID_HANDLE_VALUE) {if(!current())return 0;return 3;}
    const auto inspect=[&]() -> std::uint32_t {
        if(!current())return 0;
        FILE_ID_INFO info{};
        if(!GetFileInformationByHandleEx(file,FileIdInfo,&info,sizeof(info)))return 3;
        if(!current())return 0;
        if(info.VolumeSerialNumber!=expected.volume || std::memcmp(info.FileId.Identifier,expected.fileId,16)!=0)return 2;
        LARGE_INTEGER size{};
        if(!current())return 0;
        if(!GetFileSizeEx(file,&size))return 3;
        if(!current())return 0;
        return size.QuadPart>=0 && static_cast<std::uint64_t>(size.QuadPart)==expected.size ? 1u:2u;
    };
    auto status=inspect();
    if(!current())status=0;
    // Mandatory release even after expiry; no further attribution query is allowed.
    const bool closed=CloseHandle(file)!=0;
    if(!current())return 0;
    if(!closed)return 4;
    if(status!=1)return status;
    if(!current())return 0;
    const auto named=GetModuleHandleW(L"vclplug_winlo.dll");
    if(!current())return 0;
    if(named!=module)return 2;
    if(!current())return 0;
    length=GetModuleFileNameW(module,path,1024);
    if(!current())return 0;
    return samePath(length)?1u:2u;
}
}
