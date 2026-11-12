#include "ime_command3_finalization.h"
#include <cassert>
#include <stdexcept>
using UINT=uint32_t;using LONG=int32_t;using DWORD=uint32_t;using UINT_PTR=uintptr_t;using HWND=void*;using HIMC=void*;
struct FILETIME{uint32_t dwLowDateTime=0,dwHighDateTime=0;};struct LARGE_INTEGER{int64_t QuadPart=0;};
struct State{uint32_t pid=10,tid=20,ack=2;uint64_t targetHwnd=30,rootHwnd=40;int status=777,immOpen=1,threadMode=888;} storage;
State* shared=&storage;
namespace opengeul_ime {struct CommandBudget{uint64_t counter=1000,frequency=100;};}
static bool finalizationEnabled=true;
opengeul_ime::finalization::Config make_config(){using namespace opengeul_ime::finalization;return {Magic,1,sizeof(Config),sizeof(Section),40+sizeof(Section),40,1,10,20,0,30,40,50,60,70};}
static const auto expectedFinalization=make_config();
static opengeul_ime::finalization::Section section;
static opengeul_ime::finalization::Section* finalizationShared=&section;
static int scenario=0,gets=0,releases=0;static bool timely=true,owned=true;static int64_t ticks=100;
uint32_t GetCurrentProcessId(){return 10;}uint32_t GetCurrentThreadId(){return 20;}void* GetCurrentProcess(){return nullptr;}
bool GetProcessTimes(void*,FILETIME*m,FILETIME*,FILETIME*,FILETIME*){m->dwLowDateTime=scenario==6?51:50;return true;}
bool original_target(HWND,bool){return owned;}
bool budget(const opengeul_ime::CommandBudget&){return timely;}
bool QueryPerformanceCounter(LARGE_INTEGER*q){q->QuadPart=++ticks;return true;}
HWND GetFocus(){return reinterpret_cast<HWND>(owned?30:31);}void* GetKeyboardLayout(int){return reinterpret_cast<void*>(68289554);}
LONG InterlockedCompareExchange(volatile LONG*p,LONG after,LONG before){auto old=*p;if(old==before)*p=after;return old;}
LONG InterlockedOr(volatile LONG*p,LONG bit){auto old=*p;*p|=bit;return old;}void MemoryBarrier(){}
HIMC ImmGetContext(HWND){++gets;return scenario==1?nullptr:reinterpret_cast<HIMC>(80);}
int ImmGetOpenStatus(HIMC){return 1;}
int ImmGetConversionStatus(HIMC,DWORD*c,DWORD*s){if(scenario==5)throw std::runtime_error("synthetic");*c=1;*s=8;if(scenario==4)timely=false;return scenario==2?0:1;}
int ImmReleaseContext(HWND,HIMC){++releases;if(scenario==7)owned=false;return scenario==3?0:1;}
#include "ime_command3_finalization_windows.h"
int main(){
 for(scenario=0;scenario<=7;++scenario){section={};section.config=expectedFinalization;gets=releases=0;timely=owned=true;ticks=100;
  capture_finalization(1,3,{});
  assert(storage.status==777&&storage.immOpen==1&&storage.threadMode==888&&storage.ack==2);
  if(scenario==6){assert(section.claimedMask==0&&section.publishedMask==0&&gets==0);continue;}
  if(scenario==7){assert(section.claimedMask==1&&section.publishedMask==0&&gets==1&&releases==1);continue;}
  assert(section.claimedMask==1&&section.publishedMask==1&&gets==1);
  const auto&r=section.rows[0];assert(releases==(scenario==1?0:1));
  const uint32_t statuses[]={0,3,4,5,7,8};assert(r.status==statuses[scenario]);
  if(!scenario)assert(r.open==1&&r.conversion==1&&r.himc==80&&r.focusBefore==30&&r.focusAfter==30&&r.releaseAttempts==1&&r.releaseSucceeded==1);
 }
 scenario=0;section={};section.config=expectedFinalization;timely=false;owned=true;gets=releases=0;
 capture_finalization(1,3,{});assert(section.rows[0].status==2&&gets==0&&releases==0);
 section={};section.config=expectedFinalization;timely=true;finalizationEnabled=false;
 capture_finalization(1,3,{});assert(!section.claimedMask&&!section.publishedMask);
}
