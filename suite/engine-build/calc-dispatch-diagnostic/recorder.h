#ifndef OPENGEUL_CALC_DISPATCH_RECORDER_H
#define OPENGEUL_CALC_DISPATCH_RECORDER_H

#include "wire.h"
#include <cstring>
#include <limits>

namespace opengeul::calc_dispatch {

struct Token {
    std::uint32_t invocation = 0;
    std::uint32_t parent = 0;
    std::uint32_t depth = 0;
    std::uint32_t operation = 0;
    bool active = false;
};

inline bool validShape(const Identity& id) noexcept {
    constexpr auto max = std::numeric_limits<std::int64_t>::max();
    return id.magic == kMagic && id.version == kVersion && id.bytes == sizeof(State)
        && id.controllerPid && id.ownerPid && id.ownerTid && !id.reserved0 && !id.reserved1
        && id.nonce && id.controllerCreated && id.ownerCreated && id.ownerHwnd
        && id.startQpc >= 0 && id.deadlineQpc > id.startQpc
        && id.qpcFrequency > 0 && id.qpcFrequency <= max / 30
        && id.deadlineQpc - id.startQpc <= 30 * id.qpcFrequency;
}

template<class Adapter> class Recorder final {
public:
    Recorder(State& state, Adapter& adapter) noexcept
        : Recorder(state, adapter, state.identity) {}
    Recorder(State& state, Adapter& adapter, const Identity& identity) noexcept
        : state_(state), adapter_(adapter), identity_(identity) {}

    Token enter(std::uint32_t operation) noexcept {
        Token token;
        std::int64_t now = 0;
        if (!admit(now)) return token;
        const auto depth = read(state_.depth);
        const auto next = read(state_.nextInvocation);
        if (operation < ExecuteSave || operation > NestedInput
            || (!depth && (operation != ExecuteSave || next))) {
            bump(state_.rejected);
            return token;
        }
        if (depth == kDepth) {
            bump(state_.overflow);
            return token;
        }
        if (next == std::numeric_limits<std::uint32_t>::max()) {
            bump(state_.rejected);
            return token;
        }
        token = {next + 1, depth ? read(state_.stack[depth - 1]) : 0,
                 depth + 1, operation, true};
        write(state_.stack[depth], token.invocation);
        write(state_.depth, depth + 1);
        write(state_.active, depth + 1);
        if (!emit(token, Enter, 0, now)) {
            write(state_.stack[depth], 0);
            write(state_.depth, depth);
            write(state_.active, depth);
            return Token{};
        }
        write(state_.nextInvocation, token.invocation);
        return token;
    }

    bool mark(const Token& token, std::uint32_t phase, std::uint32_t value = 0) noexcept {
        if (!sameIdentity()) return false;
        const bool validValue = phase == CommitPolicy || phase == MediumCommitAfter
            ? value <= 1 : value == 0;
        if (phase < CommitPolicy || phase > MediumCommitAfter || !validValue || !top(token)) {
            bump(state_.rejected);
            return false;
        }
        std::int64_t now = 0;
        return admit(now) && emit(token, phase, value, now);
    }

    void leave(Token& token) noexcept {
        if (!token.active) return;
        if (!sameIdentity()) { token.active = false; return; }
        if (!top(token)) {
            bump(state_.rejected);
            return;
        }
        std::int64_t now = 0;
        if (admit(now)) emit(token, Exit, 0, now);
        const auto depth = read(state_.depth) - 1;
        write(state_.stack[depth], 0);
        write(state_.depth, depth);
        write(state_.active, depth);
        token.active = false;
    }

private:
    std::uint32_t read(const std::uint32_t& value) const noexcept {
        return adapter_.load(value);
    }

    void write(std::uint32_t& field, std::uint32_t value) noexcept {
        adapter_.publish(field, value);
    }

    void bump(std::uint32_t& field) noexcept {
        const auto value = read(field);
        if (value != std::numeric_limits<std::uint32_t>::max()) write(field, value + 1);
    }

    bool sameIdentity() const noexcept {
        return std::memcmp(&identity_, &state_.identity, sizeof identity_) == 0;
    }

    bool top(const Token& token) const noexcept {
        const auto depth = read(state_.depth);
        return token.active && depth && depth <= kDepth
            && read(state_.active) == depth && token.depth == depth
            && read(state_.stack[depth - 1]) == token.invocation
            && (depth == 1 ? token.parent == 0
                          : token.parent == read(state_.stack[depth - 2]));
    }

    bool admit(std::int64_t& now) noexcept {
        if (!sameIdentity()) return false;
        if (!validShape(identity_)
            || read(state_.depth) > kDepth || read(state_.active) != read(state_.depth)
            || read(state_.count) > kCapacity || read(state_.reserved)
            || read(state_.enabled) != 1 || !adapter_.valid(identity_)
            || !adapter_.clock(now)) {
            bump(state_.rejected);
            return false;
        }
        if (now < identity_.startQpc || now >= identity_.deadlineQpc) {
            bump(state_.expired);
            return false;
        }
        return true;
    }

    bool emit(const Token& token, std::uint32_t phase, std::uint32_t value,
              std::int64_t now) noexcept {
        const auto count = read(state_.count);
        if (count == kCapacity) {
            bump(state_.overflow);
            return false;
        }
        auto& e = state_.events[count];
        if (adapter_.load(e.sequence)) {
            bump(state_.rejected);
            return false;
        }
        e.phase = phase;
        e.operation = token.operation;
        e.invocation = token.invocation;
        e.parent = token.parent;
        e.depth = token.depth;
        e.value = value;
        e.reserved = 0;
        e.qpc = now;
        const auto sequence = count + 1;
        write(state_.count, sequence);
        adapter_.publish(e.sequence, sequence);
        return true;
    }

    State& state_;
    Adapter& adapter_;
    const Identity identity_;
};

}
#endif
