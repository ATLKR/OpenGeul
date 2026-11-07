#pragma once
#include <opengeul_writer_observer/wire.h>
#include <cwchar>
#include <cstdint>
#define __cdecl
using BOOL=int;using DWORD=std::uint32_t;using LONG=std::int32_t;using HANDLE=void*;using HWND=void*;using HMODULE=void*;using LPCWSTR=wchar_t const*;
struct LARGE_INTEGER{std::int64_t QuadPart;};struct FILETIME{DWORD dwLowDateTime,dwHighDateTime;};
constexpr DWORD GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_PIN=1,FILE_MAP_READ=4,FILE_MAP_WRITE=2,SYNCHRONIZE=0x100000,PROCESS_QUERY_LIMITED_INFORMATION=0x1000,WAIT_TIMEOUT=258;
constexpr BOOL FALSE=0;
namespace fake_win {inline opengeul::writer_observer::Mapping mapping{};inline bool pinFail=false,dead=false,late=false;inline unsigned pinCalls=0,queries=0,waits=0;inline void(*casHook)(volatile LONG*,LONG,LONG)=nullptr;}
inline LONG InterlockedCompareExchange(volatile LONG* p,LONG n,LONG expected){if(fake_win::casHook)fake_win::casHook(p,n,expected);__atomic_compare_exchange_n(p,&expected,n,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);return expected;}
inline LONG InterlockedExchange(volatile LONG* p,LONG n){return __atomic_exchange_n(p,n,__ATOMIC_ACQ_REL);}
inline LONG InterlockedOr(volatile LONG* p,LONG n){return __atomic_fetch_or(p,n,__ATOMIC_ACQ_REL);}
inline BOOL QueryPerformanceCounter(LARGE_INTEGER* q){++fake_win::queries;q->QuadPart=fake_win::late?350:120;return 1;}
inline BOOL QueryPerformanceFrequency(LARGE_INTEGER* q){++fake_win::queries;q->QuadPart=10;return 1;}
inline BOOL GetModuleHandleExW(DWORD flags,LPCWSTR address,HMODULE* m){++fake_win::queries;++fake_win::pinCalls;if(flags!=5||!address||fake_win::pinFail)return 0;*m=reinterpret_cast<void*>(3);return 1;}
inline DWORD GetEnvironmentVariableW(LPCWSTR,wchar_t* out,DWORD size){++fake_win::queries;constexpr wchar_t s[]=L"1:7:19:000000000000000a:131328:OpenGeulWriterServerObserver";if(size<(sizeof(s)/sizeof(s[0])))return (sizeof(s)/sizeof(s[0]));std::wcscpy(out,s);return (sizeof(s)/sizeof(s[0]))-1;}
inline HANDLE OpenFileMappingW(DWORD,BOOL,LPCWSTR){++fake_win::queries;return reinterpret_cast<void*>(2);}
inline void* MapViewOfFile(HANDLE,DWORD,DWORD,DWORD,std::size_t bytes){++fake_win::queries;return bytes==sizeof(fake_win::mapping)?&fake_win::mapping:nullptr;}
inline BOOL UnmapViewOfFile(void*){++fake_win::queries;return 1;}
inline BOOL CloseHandle(HANDLE){++fake_win::queries;return 1;}
inline DWORD GetWindowThreadProcessId(HWND,DWORD* pid){++fake_win::queries;*pid=8;return 9;}
inline BOOL IsWindow(HWND h){++fake_win::queries;return h==reinterpret_cast<void*>(99);}
inline DWORD GetCurrentProcessId(){++fake_win::queries;return 8;}
inline HANDLE GetCurrentProcess(){++fake_win::queries;return reinterpret_cast<void*>(4);}
inline HANDLE OpenProcess(DWORD,BOOL,DWORD pid){++fake_win::queries;return pid==7?reinterpret_cast<void*>(1):nullptr;}
inline DWORD GetProcessId(HANDLE){++fake_win::queries;return 7;}
inline DWORD WaitForSingleObject(HANDLE,DWORD milliseconds){++fake_win::waits;return milliseconds==0?(fake_win::dead?0:WAIT_TIMEOUT):0xffffffff;}
inline BOOL GetProcessTimes(HANDLE h,FILETIME* c,FILETIME*,FILETIME*,FILETIME*){++fake_win::queries;c->dwHighDateTime=0;c->dwLowDateTime=h==reinterpret_cast<void*>(1)?19:20;return 1;}
