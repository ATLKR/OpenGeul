#include "windows_runtime.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>

using namespace opengeul::calc_dispatch;

static State state{};
static void reset() {
    state = {};
    state.identity = {kMagic, kVersion, sizeof(State), 11, 12, 13, 0, 0,
                      17, 19, 23, 29, 100, 400, 10};
    state.enabled = 1;
    mappedState = &state;
}
static void released() { assert(!processHandles && !mappingHandles && !views); }

static void normal() {
    reset(); environment = nullptr;
    { Scope root(1); root.mark(3, 1); }
    assert(!opens && !state.count);
    released();
    for (const auto* invalid : {L"",L"11",L"0:17",L"11:0",L"-11:17",L"11:17:1",
                               L"4294967296:17",L"11:18446744073709551616",L"11:17/x"}) {
        environment = invalid;
        { Scope root(1); }
        assert(!opens && !state.count);
        released();
    }
}

static void nesting() {
    reset();
    { Scope unrelated(4); unrelated.mark(4); }
    assert(!state.count && !state.nextInvocation);
    { Scope root(1);
      assert(state.active == 1 && views == 1 && processHandles == 1 && mappingHandles == 1);
      { Scope child(2);
        assert(state.active == 2 && views == 2 && processHandles == 2 && mappingHandles == 2);
        child.mark(3,1);
      }
      assert(state.active == 1 && views == 1 && processHandles == 1 && mappingHandles == 1);
    }
    released();
    assert(state.count == 5 && !state.active && !state.depth);
    assert(state.events[0].parent == 0 && state.events[1].parent == 1);
    assert(state.events[3].invocation == 2 && state.events[4].invocation == 1);
    { Scope later(1); }
    assert(state.count == 5);
    released();
}

static void rejection() {
    for (unsigned variant = 0; variant != 7; ++variant) {
        reset();
        if (variant == 0) controllerGeneration = 20;
        if (variant == 1) ownerGeneration = 24;
        if (variant == 2) currentTid = 14;
        if (variant == 3) windowPid = 99;
        if (variant == 4) windowTid = 99;
        if (variant == 5) waitResult = 0;
        if (variant == 6) waitResult = 0xffffffff;
        { Scope root(1); root.mark(3, 1); }
        assert(!state.count);
        released();
        controllerGeneration = 19; ownerGeneration = 23; currentTid = 13;
        windowPid = 12; windowTid = 13; waitResult = WAIT_TIMEOUT;
    }
    reset();
    { Scope root(1); waitResult = 0; root.mark(3, 1); }
    assert(state.count == 1 && !state.active && !state.depth);
    released();
}

static void cleanup() {
    for (unsigned variant = 0; variant != 5; ++variant) {
        reset();
        failOpen = variant == 0; failMapping = variant == 1; failView = variant == 2;
        failFrequency = variant == 3; failProcessTimes = variant == 4;
        { Scope root(1); }
        assert(!state.count);
        released();
        failOpen = failMapping = failView = failFrequency = failProcessTimes = false;
    }
    reset();
    { Scope root(1); closeFailures = 1; unmapFailures = 1; }
    assert(state.cleanupErrors == 2 && !state.active && !state.depth);
    released();
    reset();
    { Scope root(1); clockValue = 400; root.mark(3, 1); }
    assert(state.count == 1 && state.expired && !state.active);
    released();
}

int main() {
    char name[32]{};
    assert(std::scanf("%31s", name) == 1);
    if (!std::strcmp(name, "runtime-normal")) normal();
    else if (!std::strcmp(name, "runtime-nested")) nesting();
    else if (!std::strcmp(name, "runtime-rejection")) rejection();
    else if (!std::strcmp(name, "runtime-cleanup")) cleanup();
    else return 2;
}
