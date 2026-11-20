#ifndef OPENGEUL_CALC_DISPATCH_WIRE_H
#define OPENGEUL_CALC_DISPATCH_WIRE_H

#include <cstddef>
#include <cstdint>

namespace opengeul::calc_dispatch {

constexpr std::uint32_t kMagic = 0x4344474f;
constexpr std::uint32_t kVersion = 1;
constexpr std::uint32_t kCapacity = 128;
constexpr std::uint32_t kDepth = 8;

enum Operation : std::uint32_t {
    ExecuteSave = 1, SaveTo = 2, DoSave = 3, NestedInput = 4
};
enum Phase : std::uint32_t {
    Enter = 1, Exit = 2, CommitPolicy = 3, InputEnterBefore = 4,
    InputEnterAfter = 5, ExecuteSlotBefore = 6, ExecuteSlotAfter = 7,
    MediumCommitBefore = 8, MediumCommitAfter = 9
};

#pragma pack(push, 8)
struct Identity {
    std::uint32_t magic;
    std::uint32_t version;
    std::uint32_t bytes;
    std::uint32_t controllerPid;
    std::uint32_t ownerPid;
    std::uint32_t ownerTid;
    std::uint32_t reserved0;
    std::uint32_t reserved1;
    std::uint64_t nonce;
    std::uint64_t controllerCreated;
    std::uint64_t ownerCreated;
    std::uint64_t ownerHwnd;
    std::int64_t startQpc;
    std::int64_t deadlineQpc;
    std::int64_t qpcFrequency;
};

struct Event {
    std::uint32_t sequence;
    std::uint32_t phase;
    std::uint32_t operation;
    std::uint32_t invocation;
    std::uint32_t parent;
    std::uint32_t depth;
    std::uint32_t value;
    std::uint32_t reserved;
    std::int64_t qpc;
};

struct State {
    Identity identity;
    std::uint32_t enabled;
    std::uint32_t count;
    std::uint32_t rejected;
    std::uint32_t overflow;
    std::uint32_t expired;
    std::uint32_t active;
    std::uint32_t depth;
    std::uint32_t cleanupErrors;
    std::uint32_t nextInvocation;
    std::uint32_t reserved;
    std::uint32_t stack[kDepth];
    Event events[kCapacity];
};
#pragma pack(pop)

static_assert(sizeof(Identity) == 88 && sizeof(Event) == 40 && sizeof(State) == 5280);
static_assert(offsetof(Identity, nonce) == 32 && offsetof(Identity, startQpc) == 64);
static_assert(offsetof(Event, qpc) == 32 && offsetof(State, events) == 160);
static_assert(offsetof(State, stack) == 128 && offsetof(State, nextInvocation) == 120);

}
#endif
