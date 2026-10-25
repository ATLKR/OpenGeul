// Compile-only Microsoft ARM64 vtable/RTTI layout witness. Never execute this DLL.
// Mirrors virtual declaration order from pinned core bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1
// include/comphelper/solarmutex.hxx and vcl/win/app/salinst.cxx; not a mutex implementation.
#include <cstdint>

class OpenGeulFixtureBase {
public:
    virtual ~OpenGeulFixtureBase() = default;
    virtual bool tryToAcquire() { return false; }
    virtual bool IsCurrentThread() const { return false; }
protected:
    virtual std::uint32_t doRelease(bool all) { return all ? 0u : 1u; }
    virtual void doAcquire(std::uint32_t count) { value = count; }
    volatile std::uint32_t value = 0;
};

class OpenGeulFixtureMutex : public OpenGeulFixtureBase {
protected:
    __declspec(dllexport) __declspec(noinline) void doAcquire(std::uint32_t count) override;
    __declspec(noinline) std::uint32_t doRelease(bool all) override { return all ? 2u : 3u; }
};

static volatile std::uint32_t witness = 0;
__declspec(noinline) static std::uint32_t observe(std::uint32_t count) {
    witness = count;
    return witness;
}
void OpenGeulFixtureMutex::doAcquire(std::uint32_t count) {
    const auto observed = observe(count);
    value = observed; // Post-call side effect forbids a tail-call-only leaf witness.
}

// Materialize the derived primary vtable and RTTI even with optimized linking.
extern "C" __declspec(dllexport) OpenGeulFixtureBase* CreateOpenGeulFixtureMutex() {
    return new OpenGeulFixtureMutex;
}
