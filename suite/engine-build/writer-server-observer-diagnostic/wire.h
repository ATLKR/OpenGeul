#pragma once
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace opengeul::writer_observer {
inline constexpr std::uint32_t Magic = 0x57534f31u;
inline constexpr std::uint32_t IpcVersion = 1;
inline constexpr std::uint32_t Capacity = 2048;
inline constexpr std::uint32_t MaxDepth = 32;
inline constexpr std::uint32_t ClosedBit = 0x80000000u;
inline constexpr char Family[] = "writer-server-observer-diagnostic";
inline constexpr wchar_t Environment[] = L"OPENGEUL_WRITER_SERVER_OBSERVER";
inline constexpr wchar_t MappingNamespace[] = L"OpenGeulWriterServerObserver";

enum class Admission : std::uint32_t { Prepared=0, Arming=1, Armed=2, Closed=3 };
enum class SessionState : std::uint32_t { Uninitialized=0, Initializing=1, Ready=2, Failed=3 };
enum class RootState : std::uint32_t { Unbound=0, Claimed=1, Ready=2, Invalid=3 };
enum class Kind : std::uint32_t { Control=0, Route=1, Getter=2, Focus=3 };
enum class Phase : std::uint32_t { None=0, LockAcquired=1, Branch=2, TagWritten=3,
    OutputComplete=4, Return=5, Assignment=6, ParentCallBefore=7, ParentCallAfter=8,
    ApiReturn=9, Enter=10, Leave=11 };
enum class Status : std::uint32_t { Unknown=0, SessionReady=1, RootReady=2, Failed=3, NoEvent=4 };
enum Incomplete : std::uint32_t { Invalidated=1, Reentered=2, DepthExceeded=4,
    PublicationHole=8, ReservationOverflow=16, TokenMismatch=32, Expired=64, BadRequest=128 };

struct alignas(8) Identity {
    std::uint32_t magic, version, bytes, capacity;
    std::uint32_t controllerPid, ownerPid, ownerTid, reserved0;
    std::uint64_t controllerBirth, nonce, ownerBirth, ownerHwnd;
    std::int64_t startQpc, deadlineQpc, qpcFrequency, cutoffQpc;
    std::uint32_t namespaceCode, reserved1;
    std::uint64_t reserved2[3];
};
struct alignas(8) Control {
    std::uint32_t admission, captureGate, reservedCount, committedCount;
    std::uint32_t dropped, overflow, incomplete, sessionState;
    std::uint32_t rootState, setupObserved, rootBoundObserved, rejected;
    std::uint32_t expired, cleanupErrors;
    std::uint64_t nextScopeOrdinal;
    std::uint32_t nextThreadOrdinal, lastStatus;
    std::int64_t setupReadyQpc, rootReadyQpc;
    std::uint32_t reserved[10];
};
struct alignas(8) Row {
    std::uint32_t commit, kind, phase, datum;
    std::uint64_t scopeOrdinal, parentScopeOrdinal;
    std::int64_t qpc;
    std::uint32_t depth, threadOrdinal, eventOrdinal, reserved0;
    std::uint64_t reserved1;
};
struct alignas(8) Mapping { Identity identity; Control control; Row rows[Capacity]; };
static_assert(sizeof(void*)==8, "Only Windows x64/ARM64 pointer8 ABI is supported");
static_assert(sizeof(Identity)==128 && alignof(Identity)==8);
static_assert(sizeof(Control)==128 && alignof(Control)==8);
static_assert(sizeof(Row)==64 && alignof(Row)==8);
static_assert(sizeof(Mapping)==131328 && offsetof(Mapping,control)==128 && offsetof(Mapping,rows)==256);
static_assert(offsetof(Identity,controllerBirth)==32 && offsetof(Identity,startQpc)==64);
static_assert(offsetof(Identity,cutoffQpc)==88 && offsetof(Control,nextScopeOrdinal)==56);
static_assert(offsetof(Control,setupReadyQpc)==72 && offsetof(Control,rootReadyQpc)==80);
static_assert(offsetof(Row,scopeOrdinal)==16 && offsetof(Row,qpc)==32 && offsetof(Row,eventOrdinal)==48);
static_assert(std::is_standard_layout_v<Mapping> && std::is_trivially_copyable_v<Mapping>);
}
