#pragma once
#include "wire.h"
#ifdef _WIN32
#include <windows.h>
#endif
namespace opengeul::writer_observer {
inline std::uint32_t load(std::uint32_t const& v) noexcept {
#ifdef _WIN32
    return static_cast<std::uint32_t>(InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(const_cast<std::uint32_t*>(&v)),0,0));
#else
    return __atomic_load_n(&v,__ATOMIC_ACQUIRE);
#endif
}
inline bool cas(std::uint32_t& v,std::uint32_t& expected,std::uint32_t next) noexcept {
#ifdef _WIN32
    auto before=static_cast<std::uint32_t>(InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&v),static_cast<LONG>(next),static_cast<LONG>(expected)));
    bool ok=before==expected;expected=before;return ok;
#else
    return __atomic_compare_exchange_n(&v,&expected,next,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
#endif
}
inline void store(std::uint32_t& v,std::uint32_t next) noexcept {
#ifdef _WIN32
    InterlockedExchange(reinterpret_cast<volatile LONG*>(&v),static_cast<LONG>(next));
#else
    __atomic_store_n(&v,next,__ATOMIC_RELEASE);
#endif
}
inline void bits(std::uint32_t& v,std::uint32_t mask) noexcept {
#ifdef _WIN32
    InterlockedOr(reinterpret_cast<volatile LONG*>(&v),static_cast<LONG>(mask));
#else
    __atomic_fetch_or(&v,mask,__ATOMIC_ACQ_REL);
#endif
}
inline void bump(std::uint32_t& v) noexcept {
    auto n=load(v);
    for(unsigned i=0;i<32&&n!=UINT32_MAX;++i)if(cas(v,n,n+1))return;
}
}
