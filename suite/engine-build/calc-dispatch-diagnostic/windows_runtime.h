#ifndef OPENGEUL_CALC_DISPATCH_WINDOWS_RUNTIME_H
#define OPENGEUL_CALC_DISPATCH_WINDOWS_RUNTIME_H

#include "recorder.h"

#if defined(OPENGEUL_CALC_DISPATCH_DIAGNOSTIC_BUILD) && defined(_WIN32)
#include <prewin.h>
#include <windows.h>
#include <postwin.h>
#include <optional>

namespace opengeul::calc_dispatch {

inline std::uint64_t creationTime(HANDLE process) noexcept {
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(process, &created, &exited, &kernel, &user)) return 0;
    return (static_cast<std::uint64_t>(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}

inline bool parseNumber(const wchar_t*& cursor, std::uint64_t max,
                        std::uint64_t& value) noexcept {
    value = 0;
    if (*cursor < L'0' || *cursor > L'9') return false;
    do {
        const auto digit = static_cast<std::uint64_t>(*cursor++ - L'0');
        if (value > (max - digit) / 10) return false;
        value = value * 10 + digit;
    } while (*cursor >= L'0' && *cursor <= L'9');
    return value != 0;
}

inline bool configuration(const wchar_t* text, std::uint32_t& pid,
                          std::uint64_t& nonce) noexcept {
    std::uint64_t process = 0;
    if (!parseNumber(text, std::numeric_limits<std::uint32_t>::max(), process)
        || *text++ != L':'
        || !parseNumber(text, std::numeric_limits<std::uint64_t>::max(), nonce)
        || *text) return false;
    pid = static_cast<std::uint32_t>(process);
    return true;
}

inline wchar_t* decimal(wchar_t* out, std::uint64_t value) noexcept {
    wchar_t digits[20];
    unsigned count = 0;
    do { digits[count++] = static_cast<wchar_t>(L'0' + value % 10); value /= 10; } while (value);
    while (count) *out++ = digits[--count];
    return out;
}

struct WindowsAdapter {
    HANDLE controller = nullptr;
    std::uint32_t controllerPid = 0;
    std::uint64_t nonce = 0;
    std::uint64_t controllerCreated = 0;
    std::uint64_t ownerCreated = 0;
    std::int64_t frequency = 0;

    bool valid(const Identity& id) const noexcept {
        if (!controller || id.controllerPid != controllerPid || id.nonce != nonce
            || id.controllerCreated != controllerCreated || !controllerCreated
            || id.ownerCreated != ownerCreated || !ownerCreated
            || id.ownerPid != GetCurrentProcessId() || id.ownerTid != GetCurrentThreadId()
            || id.qpcFrequency != frequency
            || id.ownerHwnd > std::numeric_limits<std::uintptr_t>::max()
            || WaitForSingleObject(controller, 0) != WAIT_TIMEOUT) return false;
        DWORD windowPid = 0;
        const auto hwnd = reinterpret_cast<HWND>(static_cast<std::uintptr_t>(id.ownerHwnd));
        return GetWindowThreadProcessId(hwnd, &windowPid) == id.ownerTid && windowPid == id.ownerPid;
    }

    bool clock(std::int64_t& value) const noexcept {
        LARGE_INTEGER now{};
        if (!QueryPerformanceCounter(&now)) return false;
        value = now.QuadPart;
        return true;
    }

    std::uint32_t load(const std::uint32_t& value) const noexcept {
        static_assert(sizeof(LONG) == sizeof(value));
        return static_cast<std::uint32_t>(InterlockedCompareExchange(
            reinterpret_cast<volatile LONG*>(const_cast<std::uint32_t*>(&value)), 0, 0));
    }

    void publish(std::uint32_t& sequence, std::uint32_t value) const noexcept {
        InterlockedExchange(reinterpret_cast<volatile LONG*>(&sequence), static_cast<LONG>(value));
    }
};

class Scope final {
public:
    explicit Scope(std::uint32_t operation) noexcept {
        wchar_t environment[64]{};
        const DWORD length = GetEnvironmentVariableW(
            L"OPENGEUL_CALC_DISPATCH_DIAGNOSTIC", environment, 64);
        if (!length || length >= 64
            || !configuration(environment, adapter_.controllerPid, adapter_.nonce)) return;
        adapter_.controller = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
                                          FALSE, adapter_.controllerPid);
        if (!adapter_.controller) return;
        adapter_.controllerCreated = creationTime(adapter_.controller);
        adapter_.ownerCreated = creationTime(GetCurrentProcess());
        LARGE_INTEGER frequency{};
        if (!QueryPerformanceFrequency(&frequency)) return;
        adapter_.frequency = frequency.QuadPart;
        wchar_t name[96] = L"Local\\OpenGeulCalcDispatch-";
        wchar_t* cursor = name + sizeof(L"Local\\OpenGeulCalcDispatch-") / sizeof(wchar_t) - 1;
        cursor = decimal(cursor, adapter_.controllerPid);
        *cursor++ = L'-';
        cursor = decimal(cursor, adapter_.nonce);
        *cursor = 0;
        mapping_ = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
        if (!mapping_) return;
        state_ = static_cast<State*>(MapViewOfFile(mapping_, FILE_MAP_READ | FILE_MAP_WRITE,
                                                   0, 0, sizeof(State)));
        if (!state_) return;
        const Identity identity = state_->identity;
        if (!validShape(identity) || !adapter_.valid(identity)) return;
        if (operation == NestedInput && !adapter_.load(state_->depth)) return;
        recorder_.emplace(*state_, adapter_, identity);
        token_ = recorder_->enter(operation);
    }

    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
    Scope(Scope&&) = delete;
    Scope& operator=(Scope&&) = delete;

    ~Scope() noexcept {
        if (recorder_) recorder_->leave(token_);
        recorder_.reset();
        close(adapter_.controller);
        close(mapping_);
        if (state_ && !UnmapViewOfFile(state_)) {
            cleanupError();
            if (!UnmapViewOfFile(state_)) cleanupError();
        }
    }

    void mark(std::uint32_t phase, std::uint32_t value = 0) noexcept {
        if (recorder_ && token_.active) recorder_->mark(token_, phase, value);
    }

private:
    void cleanupError() noexcept {
        if (!state_) return;
        auto count = adapter_.load(state_->cleanupErrors);
        if (count != std::numeric_limits<std::uint32_t>::max())
            adapter_.publish(state_->cleanupErrors, count + 1);
    }

    void close(HANDLE& handle) noexcept {
        if (handle && !CloseHandle(handle)) {
            cleanupError();
            if (!CloseHandle(handle)) cleanupError();
        }
        handle = nullptr;
    }

    WindowsAdapter adapter_{};
    HANDLE mapping_ = nullptr;
    State* state_ = nullptr;
    std::optional<Recorder<WindowsAdapter>> recorder_;
    Token token_{};
};

}
#else
namespace opengeul::calc_dispatch {
class Scope final {
public:
    explicit Scope(std::uint32_t) noexcept {}
    void mark(std::uint32_t, std::uint32_t = 0) noexcept {}
};
}
#endif
#endif
