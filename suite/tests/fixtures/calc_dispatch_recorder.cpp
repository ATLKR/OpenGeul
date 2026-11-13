#include "recorder.h"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <limits>
#include <initializer_list>

using namespace opengeul::calc_dispatch;

struct Fake {
    Identity expected{};
    State* state = nullptr;
    std::int64_t now = 101;
    bool identityValid = true;
    bool clockValid = true;
    bool sawPublication = false;
    bool valid(const Identity& id) noexcept {
        return identityValid && std::memcmp(&expected, &id, sizeof id) == 0;
    }
    bool clock(std::int64_t& out) noexcept { out = now; return clockValid; }
    std::uint32_t load(const std::uint32_t& value) noexcept { return value; }
    void publish(std::uint32_t& sequence, std::uint32_t value) noexcept {
        for (unsigned i = 0; i != kCapacity; ++i) {
            const Event& e = state->events[i];
            if (&sequence != &e.sequence) continue;
            assert(value == i + 1 && sequence == 0);
            assert(e.invocation && e.depth && e.qpc == now && state->count == value);
            assert(state->depth == e.depth && state->active == e.depth);
            sawPublication = true;
            break;
        }
        sequence = value;
    }
};

struct Fixture {
    State state{};
    Fake fake{};
    Fixture() {
        state.identity = {kMagic, kVersion, sizeof(State), 11, 12, 13, 0, 0,
                          17, 19, 23, 29, 100, 400, 10};
        state.enabled = 1;
        fake.expected = state.identity;
        fake.state = &state;
    }
};

static void nested() {
    Fixture f;
    Recorder<Fake> recorder(f.state, f.fake);
    auto outer = recorder.enter(1);
    auto inner = recorder.enter(4);
    assert(outer.active && inner.active && f.state.active == 2);
    assert(recorder.mark(inner, 3, 1));
    assert(!recorder.mark(outer, 3, 0));
    recorder.leave(inner);
    assert(f.state.depth == 1 && f.state.stack[0] == outer.invocation);
    recorder.leave(outer);
    assert(f.state.active == 0 && f.state.depth == 0 && f.state.count == 5);
    const auto* e = f.state.events;
    assert(e[0].phase == 1 && e[0].invocation == 1 && e[0].parent == 0 && e[0].depth == 1);
    assert(e[1].phase == 1 && e[1].invocation == 2 && e[1].parent == 1 && e[1].depth == 2);
    assert(e[2].phase == 3 && e[2].value == 1 && e[2].operation == 4);
    assert(e[3].phase == 2 && e[3].invocation == 2 && e[4].phase == 2 && e[4].invocation == 1);
    for (unsigned i = 0; i != f.state.count; ++i) assert(e[i].sequence == i + 1);
}

static void identity() {
    for (unsigned field = 0; field != 12; ++field) {
        Fixture f;
        Recorder<Fake> recorder(f.state, f.fake);
        auto* raw = reinterpret_cast<unsigned char*>(&f.state.identity);
        const unsigned offsets[] = {0,4,8,12,16,20,24,28,32,40,48,56};
        raw[offsets[field]] ^= 1;
        assert(!recorder.enter(1).active && f.state.count == 0);
    }
    Fixture f;
    Recorder<Fake> recorder(f.state, f.fake);
    auto token = recorder.enter(1);
    f.fake.identityValid = false;
    assert(!recorder.mark(token, 3));
    recorder.leave(token);
    assert(f.state.count == 1 && f.state.depth == 0 && f.state.active == 0);
    Fixture changed;
    Recorder<Fake> immutable(changed.state, changed.fake);
    auto old = immutable.enter(1);
    ++changed.state.identity.nonce;
    const State afterChange = changed.state;
    assert(!immutable.mark(old, 3));
    immutable.leave(old);
    assert(!old.active && std::memcmp(&afterChange, &changed.state, sizeof(State)) == 0);
}

static void deadline() {
    for (const auto now : {99, 400, 401}) {
        Fixture f; f.fake.now = now;
        Recorder<Fake> recorder(f.state, f.fake);
        assert(!recorder.enter(1).active && f.state.count == 0);
    }
    for (const auto span : {0, -1, 301}) {
        Fixture f; f.state.identity.deadlineQpc = 100 + span; f.fake.expected = f.state.identity;
        Recorder<Fake> recorder(f.state, f.fake);
        assert(!recorder.enter(1).active);
    }
    Fixture extreme;
    extreme.state.identity.qpcFrequency = std::numeric_limits<std::int64_t>::max();
    extreme.fake.expected = extreme.state.identity;
    Recorder<Fake> invalid(extreme.state, extreme.fake);
    assert(!invalid.enter(1).active);
    Fixture f; Recorder<Fake> recorder(f.state, f.fake);
    auto token = recorder.enter(1);
    f.fake.now = 400;
    assert(!recorder.mark(token, 3));
    recorder.leave(token);
    assert(f.state.expired && f.state.depth == 0 && f.state.active == 0);
    Fixture broken; broken.fake.clockValid = false;
    Recorder<Fake> noClock(broken.state, broken.fake);
    assert(!noClock.enter(1).active);
}

static void bounds() {
    Fixture f; Recorder<Fake> recorder(f.state, f.fake);
    Token tokens[kDepth];
    for (unsigned i = 0; i != kDepth; ++i) {
        tokens[i] = recorder.enter(i ? 4 : 1);
        assert(tokens[i].active);
    }
    assert(!recorder.enter(4).active && f.state.depth == kDepth && f.state.overflow == 1);
    for (unsigned i = kDepth; i != 0; --i) recorder.leave(tokens[i - 1]);
    assert(f.state.depth == 0 && f.state.active == 0);
    Fixture full; Recorder<Fake> fill(full.state, full.fake);
    auto root = fill.enter(1);
    for (unsigned i = 1; i != kCapacity; ++i) assert(fill.mark(root, 4));
    const Event saved = full.state.events[kCapacity - 1];
    assert(!fill.mark(root, 4));
    fill.leave(root);
    assert(full.state.count == kCapacity && full.state.overflow == 2);
    assert(full.state.depth == 0 && full.state.active == 0);
    assert(std::memcmp(&saved, &full.state.events[kCapacity - 1], sizeof saved) == 0);
}

static void admission() {
    for (const auto operation : {0, 2, 3, 4, 5}) {
        Fixture f; Recorder<Fake> recorder(f.state, f.fake);
        assert(!recorder.enter(operation).active && f.state.count == 0);
    }
    Fixture f; Recorder<Fake> recorder(f.state, f.fake);
    auto root = recorder.enter(1);
    auto nestedRoot = recorder.enter(1);
    assert(nestedRoot.active);
    recorder.leave(nestedRoot);
    f.state.enabled = 0;
    assert(!recorder.enter(2).active && !recorder.mark(root, 3));
    recorder.leave(root);
    f.state.enabled = 1;
    assert(!recorder.enter(1).active && f.state.depth == 0);
}

static void publication() {
    Fixture f; Recorder<Fake> recorder(f.state, f.fake);
    auto root = recorder.enter(1);
    assert(root.active && f.fake.sawPublication);
    assert(!recorder.mark(root, 1) && !recorder.mark(root, 2));
    auto child = recorder.enter(4);
    recorder.leave(root);
    assert(root.active && f.state.depth == 2);
    recorder.leave(child);
    recorder.leave(root);
    assert(!root.active && f.state.depth == 0);
    Fixture partial; partial.state.events[0].sequence = 1;
    Recorder<Fake> reject(partial.state, partial.fake);
    assert(!reject.enter(1).active && partial.state.count == 0);
    Fixture corrupt; corrupt.state.depth = kDepth + 1;
    Recorder<Fake> malformed(corrupt.state, corrupt.fake);
    assert(!malformed.enter(1).active);
    Fixture saturated; saturated.state.rejected = std::numeric_limits<std::uint32_t>::max();
    Recorder<Fake> saturate(saturated.state, saturated.fake);
    assert(!saturate.enter(4).active && saturated.state.rejected == std::numeric_limits<std::uint32_t>::max());
}

int main() {
    char name[32]{};
    assert(std::scanf("%31s", name) == 1);
    if (!std::strcmp(name, "nested")) nested();
    else if (!std::strcmp(name, "identity")) identity();
    else if (!std::strcmp(name, "deadline")) deadline();
    else if (!std::strcmp(name, "bounds")) bounds();
    else if (!std::strcmp(name, "admission")) admission();
    else if (!std::strcmp(name, "publication")) publication();
    else return 2;
}
