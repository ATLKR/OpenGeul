#include "ime_command3_finalization.h"
#include <cassert>
#include <cstring>
using UINT=uint32_t;using LONG=int32_t;using DWORD=uint32_t;
#define __declspec(x)
struct FILETIME{uint32_t dwLowDateTime=0,dwHighDateTime=0;};
struct State{uint32_t magic=0x4f47494d,version=4,pid=10,tid=20,command=3,ack=3;uint64_t targetHwnd=30,rootHwnd=40;};
struct ObserverMapping{State state;opengeul_ime::finalization::Section finalization;};
State* shared=nullptr;void* mapping=reinterpret_cast<void*>(1);bool finalizationEnabled=true;
opengeul_ime::finalization::Section*finalizationShared=nullptr;
const opengeul_ime::finalization::Config expectedFinalization={opengeul_ime::finalization::Magic,1,80,sizeof(opengeul_ime::finalization::Section),sizeof(ObserverMapping),sizeof(State),1,10,20,0,30,40,50,60,70};
static ObserverMapping object;static uint32_t logicalBytes=sizeof(object),mappedBytes=0;static int closed=0,unmapped=0,interlocked=0;static bool badGeneration=false,unstable=false;
constexpr unsigned FILE_MAP_ALL_ACCESS=1;
void* MapViewOfFile(void*,unsigned,unsigned,unsigned,size_t size){mappedBytes=size;return size<=logicalBytes?&object:nullptr;}
int CloseHandle(void*){++closed;return 1;}int UnmapViewOfFile(void*){++unmapped;return 1;}
uint32_t GetCurrentProcessId(){return 10;}uint32_t GetCurrentThreadId(){return 20;}void*GetCurrentProcess(){return nullptr;}
int GetProcessTimes(void*,FILETIME*m,FILETIME*,FILETIME*,FILETIME*){m->dwLowDateTime=badGeneration?51:50;return 1;}
bool connect_candidate(){
#include "native_connect.inc"
 return shared!=nullptr;
}
void MemoryBarrier(){}void CopyMemory(void*a,const void*b,size_t n){std::memcpy(a,b,n);}
LONG InterlockedCompareExchange(volatile LONG*p,LONG after,LONG before){++interlocked;auto old=*p;if(old==before)*p=after;if(unstable&&interlocked==3)return old|2;return old;}
#include "native_read.inc"
void reset(){object={};object.finalization.config=expectedFinalization;shared=nullptr;finalizationShared=nullptr;logicalBytes=sizeof(object);mappedBytes=0;mapping=reinterpret_cast<void*>(1);closed=unmapped=interlocked=0;badGeneration=unstable=false;}
int main(){
 reset();assert(connect_candidate()&&mappedBytes==sizeof(object)&&shared==&object.state);
 assert(opengeul_ime::finalization::MappingBound(shared,finalizationShared,expectedFinalization));
 ++object.finalization.config.epochLow;assert(!opengeul_ime::finalization::MappingBound(shared,finalizationShared,expectedFinalization));
 --object.finalization.config.epochLow;++object.state.targetHwnd;assert(!opengeul_ime::finalization::MappingBound(shared,finalizationShared,expectedFinalization));
 reset();logicalBytes=sizeof(State);const auto old=object;assert(!connect_candidate());assert(mappedBytes==sizeof(object)&&closed==1&&unmapped==0);assert(!std::memcmp(&old,&object,sizeof(object)));
 for(int n=0;n<5;++n){reset();switch(n){case 0:++object.finalization.config.version;break;case 1:--object.finalization.config.mappingBytes;break;case 2:++object.finalization.config.epochHigh;break;case 3:++object.finalization.config.pid;break;default:badGeneration=true;}const auto old=object;assert(!connect_candidate()&&closed==1&&unmapped==1);assert(!std::memcmp(&old,&object,sizeof(object)));}
 reset();opengeul_ime::finalization::Section out{};UINT before=0,after=0;
 assert(ReadCommand3Finalization(&object,sizeof(State),&expectedFinalization,&out,&before,&after)==0&&interlocked==0);
 auto wrong=expectedFinalization;++wrong.version;assert(!ReadCommand3Finalization(&object,sizeof(object),&wrong,&out,&before,&after));
 assert(!ReadCommand3Finalization(&object,sizeof(object),&expectedFinalization,&object.finalization,&before,&after));
 object.finalization.claimedMask=3;object.finalization.publishedMask=1;object.finalization.rows[0].sequence=1;object.finalization.rows[1].himc=999;
 assert(ReadCommand3Finalization(&object,sizeof(object),&expectedFinalization,&out,&before,&after)==1);assert(out.rows[0].sequence==1&&out.rows[1].himc==0&&before==after&&before==3);
 interlocked=0;unstable=true;assert(ReadCommand3Finalization(&object,sizeof(object),&expectedFinalization,&out,&before,&after)==2);
}
