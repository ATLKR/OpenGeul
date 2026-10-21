#pragma once
#include <cstddef>
#include <cstdint>

namespace OpenGeulAscii {
constexpr std::uint32_t Magic = 0x4f47414b;
constexpr std::uint32_t Version = 2;
constexpr std::uint32_t Capacity = 4096;

struct Event {
    std::uint32_t sequence, actionEpoch, origin, remove, message, pid, tid, messageTime;
    std::uint64_t hwnd, layout, wParam, lParam, extraInfo, nativeTick;
    std::int16_t shiftState, controlState, altState, capsState;
    std::uint32_t flags, reserved;
};

struct QueueSample {
    std::int32_t status;
    std::uint32_t queueFlags, queueStatus, keyboardSucceeded, keyboardError, callbackDepth, pid, tid;
    std::uint64_t hwnd, engineCreationTime, layout, tickStarted, tickFinished;
    std::uint8_t keyboard[256];
};
struct Readiness {
    std::uint32_t request, ack;
    QueueSample sample;
};

struct State {
    std::uint32_t magic, version, stateSize, eventSize, capacity, pid, tid, controllerPid;
    std::uint32_t startMessage, stopMessage, recording, ack;
    std::int32_t count, overflow, activeCallbacks, status;
    std::uint32_t armedIndex, armedEpoch, command, stopAck;
    std::uint64_t nonce, hwnd, engineCreationTime, layout;
    std::uint32_t readinessMessage, readinessReserved;
    Readiness readiness;
    Event events[Capacity];
};

static_assert(sizeof(Event) == 96);
static_assert(offsetof(Event, hwnd) == 32);
static_assert(offsetof(Event, shiftState) == 80);
static_assert(sizeof(QueueSample) == 328);
static_assert(sizeof(Readiness) == 336);
static_assert(offsetof(State, readiness) == 120);
static_assert(offsetof(State, events) == 456);
static_assert(sizeof(State) == 456 + Capacity * sizeof(Event));
static_assert(alignof(State) == 8);
}  // namespace OpenGeulAscii
