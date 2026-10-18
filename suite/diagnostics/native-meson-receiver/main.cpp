#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include "graphite-fixture.h"
#include "icu-fixture.h"

extern "C" int receiver_c_probe(void);
int receiver_cpp_probe();

int main() {
    const int value = receiver_c_probe() + receiver_cpp_probe()
        + receiver_graphite_fixture() + receiver_icu_fixture();
    USHORT process = 0xffff, native = 0xffff;
    FILETIME creation{}, exited{}, kernel{}, user{};
    HANDLE self = GetCurrentProcess();
    if (!IsWow64Process2(self, &process, &native)
            || !GetProcessTimes(self, &creation, &exited, &kernel, &user)) {
        std::fprintf(stderr, "native identity API failed: %lu\n", GetLastError());
        return 2;
    }
    const std::uint64_t ticks = (std::uint64_t(creation.dwHighDateTime) << 32)
        | creation.dwLowDateTime;
    const bool nativeArm64 = process == 0 && native == IMAGE_FILE_MACHINE_ARM64;
    std::printf("{\"functionCheck\":%s,\"value\":%d,\"pid\":%lu,"
                "\"creationTimeRawTicks\":\"%llu\",\"processMachine\":%u,"
                "\"nativeMachine\":%u,\"nativeArm64\":%s}\n",
                value == 54 ? "true" : "false", value, GetCurrentProcessId(),
                static_cast<unsigned long long>(ticks), unsigned(process), unsigned(native),
                nativeArm64 ? "true" : "false");
    return value == 54 && nativeArm64 ? 0 : 3;
}
