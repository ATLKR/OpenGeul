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

constexpr std::uint32_t TraceVersion = 1;
constexpr std::uint32_t TraceCapacity = 128;
struct TraceEvent {
    std::uint32_t sequence, origin, message, vk, pid, tid, reserved, flags;
    std::uint64_t hwnd, engineCreationTime, focusHwnd, captureHwnd, counter, frequency, nativeTick, lParam, layout;
};

constexpr std::uint32_t CaptureVersion = 1;
constexpr std::uint32_t CaptureCapacity = 128;
// LibreOffice core bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1 vcl/inc/win/saldata.hxx.
constexpr std::uint32_t SalPostFocus = 0x400 + 133;
constexpr std::uint32_t SalCaptureMouse = 0x400 + 140;
constexpr std::uint32_t SalReleaseMouse = 0x400 + 141;
struct CaptureEvent {
    std::uint32_t sequence, origin, message, pid, tid, callbackDepth, removeFlags, reserved;
    std::uint64_t hwnd, engineCreationTime, focusHwnd, captureHwnd, counter, finishedCounter,
                  frequency, nativeTick, wParam, lParam;
};

constexpr std::uint32_t RetrievalVersion=1, RetrievalCapacity=3, RetrievalFrames=16;
struct RetrievalFrame {std::uint32_t moduleId,rva;};
struct RetrievalEvent {
    std::uint32_t sequence,captureSequence,bucket,message,removeFlags,pid,tid,flags;
    std::uint64_t hwnd,engineCreationTime,counter,finishedCounter,frequency,lParam;
    std::int32_t pointX,pointY,clientOriginX,clientOriginY;
    std::uint32_t originSucceeded,originError,stackRequested,frameCount,frameCapReached,unknownFrames,reserved0,reserved1;
    RetrievalFrame frames[RetrievalFrames];
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
    std::uint32_t traceVersion, traceEnabled;
    std::int32_t traceCount, traceOverflow;
    std::uint32_t traceRejected, traceReserved;
    TraceEvent traceEvents[TraceCapacity];
    std::uint32_t captureVersion,captureEnabled;
    std::int32_t captureCount,captureOverflow;
    std::uint32_t captureRejected,captureExpired,captureReserved,capturePadding;
    std::uint64_t captureDeadline,captureFrequency;
    CaptureEvent captureEvents[CaptureCapacity];
    std::uint32_t retrievalVersion,retrievalClaimed,retrievalRejected,retrievalExpired;
    RetrievalEvent retrievalEvents[RetrievalCapacity];
};

static_assert(sizeof(Event) == 96);
static_assert(offsetof(Event, hwnd) == 32);
static_assert(offsetof(Event, shiftState) == 80);
static_assert(sizeof(QueueSample) == 328);
static_assert(sizeof(Readiness) == 336);
static_assert(offsetof(State, readiness) == 120);
static_assert(offsetof(State, events) == 456);
static_assert(sizeof(TraceEvent) == 104);
static_assert(offsetof(State, traceVersion) == 456 + Capacity * sizeof(Event));
static_assert(offsetof(State,captureVersion) == 407008);
static_assert(sizeof(CaptureEvent) == 112);
static_assert(offsetof(State,retrievalVersion)==421392);
static_assert(sizeof(RetrievalEvent)==256);
static_assert(sizeof(State)==422176);
static_assert(alignof(State) == 8);
}  // namespace OpenGeulAscii
