#pragma once
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cwchar>

using DWORD = std::uint32_t;
using LONG = std::int32_t;
using BOOL = int;
using HANDLE = void*;
using HWND = void*;
struct FILETIME { DWORD dwLowDateTime; DWORD dwHighDateTime; };
struct LARGE_INTEGER { std::int64_t QuadPart; };
constexpr BOOL FALSE = 0;
constexpr DWORD PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
constexpr DWORD SYNCHRONIZE = 0x100000;
constexpr DWORD FILE_MAP_READ = 4;
constexpr DWORD FILE_MAP_WRITE = 2;
constexpr DWORD WAIT_TIMEOUT = 258;

inline const wchar_t* environment = L"11:17";
inline void* mappedState = nullptr;
inline unsigned processHandles = 0, mappingHandles = 0, views = 0, opens = 0;
inline unsigned closeFailures = 0, unmapFailures = 0, waitCalls = 0;
inline bool failOpen = false, failMapping = false, failView = false;
inline bool failFrequency = false, failClock = false, failProcessTimes = false;
inline DWORD waitResult = WAIT_TIMEOUT, currentTid = 13, windowPid = 12, windowTid = 13;
inline std::int64_t clockValue = 101, clockFrequency = 10;
inline std::uint64_t controllerGeneration = 19, ownerGeneration = 23;
inline HANDLE controllerHandle() { return reinterpret_cast<HANDLE>(0x1100); }
inline HANDLE mappingHandle() { return reinterpret_cast<HANDLE>(0x2200); }
inline HANDLE GetCurrentProcess() { return reinterpret_cast<HANDLE>(0x3300); }
inline DWORD GetCurrentProcessId() { return 12; }
inline DWORD GetCurrentThreadId() { return currentTid; }

inline DWORD GetEnvironmentVariableW(const wchar_t* key, wchar_t* out, DWORD capacity) {
    assert(std::wcscmp(key, L"OPENGEUL_CALC_DISPATCH_DIAGNOSTIC") == 0);
    if (!environment) return 0;
    const auto length = std::wcslen(environment);
    if (length >= capacity) return static_cast<DWORD>(length + 1);
    std::wmemcpy(out, environment, length + 1);
    return static_cast<DWORD>(length);
}
inline HANDLE OpenProcess(DWORD access, BOOL inherit, DWORD pid) {
    assert(access == (PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE) && !inherit && pid == 11);
    ++opens;
    if (failOpen) return nullptr;
    ++processHandles;
    return controllerHandle();
}
inline BOOL GetProcessTimes(HANDLE handle, FILETIME* created, FILETIME*, FILETIME*, FILETIME*) {
    if (failProcessTimes) return 0;
    assert(handle == controllerHandle() || handle == GetCurrentProcess());
    const auto generation = handle == controllerHandle() ? controllerGeneration : ownerGeneration;
    created->dwLowDateTime = static_cast<DWORD>(generation);
    created->dwHighDateTime = static_cast<DWORD>(generation >> 32);
    return 1;
}
inline BOOL QueryPerformanceFrequency(LARGE_INTEGER* out) {
    out->QuadPart = clockFrequency;
    return !failFrequency;
}
inline BOOL QueryPerformanceCounter(LARGE_INTEGER* out) {
    out->QuadPart = clockValue;
    return !failClock;
}
inline DWORD WaitForSingleObject(HANDLE handle, DWORD milliseconds) {
    assert(handle == controllerHandle() && milliseconds == 0);
    ++waitCalls;
    return waitResult;
}
inline DWORD GetWindowThreadProcessId(HWND hwnd, DWORD* pid) {
    assert(hwnd == reinterpret_cast<HWND>(29));
    *pid = windowPid;
    return windowTid;
}
inline HANDLE OpenFileMappingW(DWORD access, BOOL inherit, const wchar_t* name) {
    assert(access == (FILE_MAP_READ | FILE_MAP_WRITE) && !inherit);
    assert(std::wcscmp(name, L"Local\\OpenGeulCalcDispatch-11-17") == 0);
    if (failMapping) return nullptr;
    ++mappingHandles;
    return mappingHandle();
}
inline void* MapViewOfFile(HANDLE handle, DWORD access, DWORD high, DWORD low, std::size_t bytes) {
    assert(handle == mappingHandle() && access == (FILE_MAP_READ | FILE_MAP_WRITE));
    assert(!high && !low && bytes == 5280);
    if (failView) return nullptr;
    ++views;
    return mappedState;
}
inline BOOL CloseHandle(HANDLE handle) {
    if (closeFailures) { --closeFailures; return 0; }
    if (handle == controllerHandle()) { assert(processHandles); --processHandles; }
    else { assert(handle == mappingHandle() && mappingHandles); --mappingHandles; }
    return 1;
}
inline BOOL UnmapViewOfFile(const void* view) {
    assert(view == mappedState && views);
    if (unmapFailures) { --unmapFailures; return 0; }
    --views;
    return 1;
}
inline LONG InterlockedCompareExchange(volatile LONG* address, LONG value, LONG expected) {
    const LONG original = *address;
    if (original == expected) *address = value;
    return original;
}
inline LONG InterlockedExchange(volatile LONG* address, LONG value) {
    const LONG original = *address;
    *address = value;
    return original;
}
