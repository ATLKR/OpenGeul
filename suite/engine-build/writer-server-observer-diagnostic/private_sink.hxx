#pragma once
#include "wire.h"
#include <atomic>
class AccObjectWinManager;
struct IMAccessible;
#ifndef _WIN32
#define OPENGEUL_WRITER_CDECL
#else
#define OPENGEUL_WRITER_CDECL __cdecl
#endif
namespace opengeul::writer_observer {
inline constexpr std::uint32_t SinkAbiVersion=2;
enum class Action : std::uint32_t { Setup=1, BindRoot=2, Enter=3, Mark=4, Leave=5,
    InvalidateObject=6, InvalidateMap=7, InvalidateManager=8 };
struct alignas(8) SinkRequest {
    std::uint32_t bytes, abiVersion, action, kind;
    AccObjectWinManager* manager;
    IMAccessible* peer;
    std::uintptr_t hwnd;
    std::uint64_t scopeOrdinal;
    std::int64_t qpcSample;
    std::uint32_t phase, datum, reserved0, reserved1;
    std::uint64_t reserved2;
};
struct alignas(8) SinkReply {
    std::uint32_t bytes, abiVersion, status, flags;
    std::uint64_t scopeOrdinal, reserved;
};
using Sink=std::uint32_t (OPENGEUL_WRITER_CDECL *)(SinkRequest const*,SinkReply*) noexcept;
static_assert(sizeof(SinkRequest)==80 && alignof(SinkRequest)==8);
static_assert(offsetof(SinkRequest,manager)==16 && offsetof(SinkRequest,peer)==24);
static_assert(offsetof(SinkRequest,hwnd)==32 && offsetof(SinkRequest,scopeOrdinal)==40);
static_assert(offsetof(SinkRequest,qpcSample)==48 && offsetof(SinkRequest,phase)==56);
static_assert(offsetof(SinkRequest,datum)==60 && offsetof(SinkRequest,reserved2)==72);
static_assert(sizeof(SinkReply)==32 && offsetof(SinkReply,scopeOrdinal)==16);
static_assert(std::atomic<Sink>::is_always_lock_free);
static_assert(std::atomic<std::uint32_t>::is_always_lock_free);
}
