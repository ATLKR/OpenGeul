// No input parser, package activation, file API or normal-observation mode.
#ifndef _WIN32
#error Existing native Windows SDK required.
#endif
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "sdk_smoke.hpp"
int wmain(int argc,wchar_t**) {
  if(argc!=1)return 94;
#if defined(_M_X64)
  constexpr std::uint16_t machine=0x8664;
#elif defined(_M_ARM64)
  constexpr std::uint16_t machine=0xaa64;
#else
  return 95;
#endif
  auto clock=[](){LARGE_INTEGER now{},frequency{};
    if(!::QueryPerformanceCounter(&now)||!::QueryPerformanceFrequency(&frequency)||now.QuadPart<=0||frequency.QuadPart<=0)throw sdk_gate::Clock{};
    return sdk_gate::Clock{static_cast<std::uint64_t>(now.QuadPart),static_cast<std::uint64_t>(frequency.QuadPart)};
  };
  return sdk_gate::run(packaged_context::observe_windows,clock,machine);
}
