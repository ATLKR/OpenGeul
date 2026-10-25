#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cwchar>
#include <cstring>
#include "ascii_message_protocol.h"
#include "bounded_stack_windows.h"
#include "bounded_plugin_origin_windows.h"

namespace {
using OpenGeulAscii::Event;
using OpenGeulAscii::State;
State* shared = nullptr;
HANDLE mapping = nullptr;
volatile LONG active = 0;
volatile LONG querying = 0;
DWORD ownerThread = 0;
bool stopped = true;
bool releaseFailed = false;
OpenGeulAscii::PluginBinding pluginBindingSnapshot{};
static_assert(sizeof(LONG)==sizeof(std::int32_t));

void publishSigned(std::int32_t* value,std::int32_t next) {
    InterlockedExchange(reinterpret_cast<volatile LONG*>(value),next);
}
std::int32_t incrementSigned(std::int32_t* value) {
    return static_cast<std::int32_t>(InterlockedIncrement(reinterpret_cast<volatile LONG*>(value)));
}

LONG load(const std::uint32_t* value) {
    return InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(const_cast<std::uint32_t*>(value)),0,0);
}
LONG loadSigned(const std::int32_t* value) {
    return InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(const_cast<std::int32_t*>(value)),0,0);
}
void publish(std::uint32_t* value,LONG next) {
    InterlockedExchange(reinterpret_cast<volatile LONG*>(value),next);
}
bool forgetView() {
    if(releaseFailed) return false;
    if(shared) {
        if(!UnmapViewOfFile(shared)) { releaseFailed=true; return false; }
        shared=nullptr;
    }
    if(mapping) {
        if(!CloseHandle(mapping)) { releaseFailed=true; return false; }
        mapping=nullptr;
    }
    ownerThread=0;pluginBindingSnapshot={};
    return true;
}
struct Callback {
    Callback() {
        LONG count=InterlockedIncrement(&active);
        if(shared) publishSigned(&shared->activeCallbacks,count);
    }
    ~Callback() {
        LONG count=InterlockedDecrement(&active);
        if(shared) publishSigned(&shared->activeCallbacks,count);
    }
};
bool identity(const State* state,HWND hwnd) {
    FILETIME created{},exited{},kernel{},user{};
    DWORD pid=0;
    if(!GetProcessTimes(GetCurrentProcess(),&created,&exited,&kernel,&user)) return false;
    const auto creation=(std::uint64_t(created.dwHighDateTime)<<32)|created.dwLowDateTime;
    return state->pid==GetCurrentProcessId() && state->tid==GetCurrentThreadId()
        && state->engineCreationTime==creation && state->hwnd==std::uint64_t(reinterpret_cast<std::uintptr_t>(hwnd))
        && IsWindow(hwnd) && GetWindowThreadProcessId(hwnd,&pid)==state->tid && pid==state->pid;
}
bool header(const State* state) {
    return state->magic==OpenGeulAscii::Magic && state->version==OpenGeulAscii::Version
        && state->stateSize==sizeof(State) && state->eventSize==sizeof(Event)
        && state->capacity==OpenGeulAscii::Capacity;
}
bool pluginAdmission(const State* state) {
    const auto& b=state->pluginBinding;
    if(b.version!=1 || b.enabled>1 || b.reserved)return false;
    const OpenGeulAscii::PluginOriginSample empty{};
    for(const auto& sample:state->pluginOrigins)if(std::memcmp(&sample,&empty,sizeof(empty)))return false;
    if(!b.enabled) {
        OpenGeulAscii::PluginBinding disabled{};disabled.version=1;
        return std::memcmp(&b,&disabled,sizeof(b))==0;
    }
    if(!state->captureEnabled || !b.size || b.size>32u*1024u*1024u || b.pathLength<4
       || b.pathLength>=OpenGeulAscii::PluginPathCapacity || b.path[1]!=':' || b.path[2]!='\\'
       || !((b.path[0]>='A' && b.path[0]<='Z') || (b.path[0]>='a' && b.path[0]<='z')))return false;
    bool fileId=false;for(auto byte:b.fileId)fileId=fileId || byte!=0;
    if(!fileId)return false;
    for(std::uint32_t i=0;i<OpenGeulAscii::PluginPathCapacity;++i)
        if(i<b.pathLength ? b.path[i]==0 : b.path[i]!=0)return false;
    const char suffix[]="\\vclplug_winlo.dll";
    if(b.pathLength<sizeof(suffix)-1)return false;
    for(std::uint32_t i=0;i<sizeof(suffix)-1;++i)
        if(b.path[b.pathLength-(sizeof(suffix)-1)+i]!=static_cast<unsigned char>(suffix[i]))return false;
    return true;
}
void start(const CWPSTRUCT& message) {
    // Only this start callback may remain active. A reentrant start cannot
    // replace a view that an earlier callback on this thread might still use.
    if(InterlockedCompareExchange(&active,0,0)!=1 || (shared && (!stopped || ownerThread!=GetCurrentThreadId()))) return;
    if(!message.wParam || message.wParam>0xffffffffu) return;
    const auto nonce=static_cast<std::uint64_t>(message.lParam);
    if(!nonce) return;
    if(!forgetView()) return;
    wchar_t name[100]{};
    std::swprintf(name,100,L"Local\\OpenGeulAscii_%lu_%016llx",
        static_cast<unsigned long>(message.wParam),static_cast<unsigned long long>(nonce));
    mapping=OpenFileMappingW(FILE_MAP_ALL_ACCESS,FALSE,name);
    if(!mapping) return;
    shared=static_cast<State*>(MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(State)));
    if(!shared) { forgetView(); return; }
    // The controller publishes command last, after initializing the mapping.
    const LONG command=load(&shared->command);
    const UINT startMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Start.v2");
    const UINT stopMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Stop.v2");
    const UINT readinessMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Readiness.v2");
    if(command!=1 || !header(shared) || !pluginAdmission(shared) || shared->controllerPid!=message.wParam || shared->nonce!=nonce
       || shared->startMessage!=startMessage || shared->stopMessage!=stopMessage
       || shared->readinessMessage!=readinessMessage || shared->readinessReserved
       || shared->traceVersion!=OpenGeulAscii::TraceVersion || shared->traceEnabled>1
       || shared->traceCount || shared->traceOverflow || shared->traceRejected || shared->traceReserved
       || shared->captureVersion!=OpenGeulAscii::CaptureVersion || shared->captureEnabled>1
       || shared->captureCount || shared->captureOverflow || shared->captureRejected || shared->captureExpired
       || shared->captureReserved || shared->capturePadding
       || shared->retrievalVersion!=OpenGeulAscii::RetrievalVersion || shared->retrievalClaimed || shared->retrievalRejected || shared->retrievalExpired
       || (shared->captureEnabled ? (!shared->captureDeadline || !shared->captureFrequency || shared->traceEnabled)
                                  : (shared->captureDeadline || shared->captureFrequency))
       || load(&shared->readiness.request) || load(&shared->readiness.ack)
       || !identity(shared,message.hwnd) || shared->count!=0 || shared->overflow || shared->status
       || shared->layout!=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetKeyboardLayout(0)))) {
        publishSigned(&shared->status,-1);
        forgetView(); return;
    }
    pluginBindingSnapshot=shared->pluginBinding;
    ownerThread=GetCurrentThreadId(); stopped=false;
    publishSigned(&shared->activeCallbacks,1);
    publish(&shared->recording,1);
    publish(&shared->ack,1);
}
void stop(const CWPSTRUCT& message) {
    if(!shared || ownerThread!=GetCurrentThreadId() || shared->controllerPid!=message.wParam
       || shared->nonce!=static_cast<std::uint64_t>(message.lParam) || load(&shared->command)!=2) return;
    // Stopping private instrumentation does not require changing input focus or
    // HKL. It still requires the original owned HWND/process/thread generation.
    if(!header(shared) || !identity(shared,message.hwnd)) {
        publishSigned(&shared->status,-2); return;
    }
    publish(&shared->recording,0);
    stopped=true;
    publish(&shared->stopAck,2);
    // Retain our OWN mapping HANDLE/view. Unhook success in the controller is
    // not proof that an already-entered remote callback has finished. Release
    // here only on a future nonreentrant same-thread start or DLL lifetime end.
}
void queryReadiness(const CWPSTRUCT& message,UINT startMessage,UINT stopMessage,UINT readinessMessage) {
    if(!shared || stopped || ownerThread!=GetCurrentThreadId() || shared->controllerPid!=message.wParam
       || shared->nonce!=static_cast<std::uint64_t>(message.lParam) || load(&shared->command)!=1
       || load(&shared->armedEpoch) || loadSigned(&shared->count)) return;
    const auto request=static_cast<std::uint32_t>(load(&shared->readiness.request));
    if(!request || request>8192 || request!=static_cast<std::uint32_t>(load(&shared->readiness.ack))+1) return;
    // A reentrant query must never overwrite the active sample or its ACK.
    if(InterlockedCompareExchange(&querying,1,0)!=0) return;
    struct QueryLease { ~QueryLease(){InterlockedExchange(&querying,0);} } lease;
    OpenGeulAscii::QueueSample sample{};
    static_assert(QS_INPUT==0x1c07);  // Modern mouse/key/raw/touch/pointer mask.
    sample.queueFlags=QS_INPUT; sample.pid=GetCurrentProcessId(); sample.tid=GetCurrentThreadId();
    sample.hwnd=std::uint64_t(reinterpret_cast<std::uintptr_t>(message.hwnd));
    sample.engineCreationTime=shared->engineCreationTime;
    sample.layout=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetKeyboardLayout(0)));
    sample.callbackDepth=static_cast<std::uint32_t>(InterlockedCompareExchange(&active,0,0));
    sample.tickStarted=GetTickCount64();
    const auto admitted=[&]() {
        return header(shared) && !shared->readinessReserved && shared->startMessage==startMessage
            && shared->stopMessage==stopMessage && shared->readinessMessage==readinessMessage
            && message.message==readinessMessage
            && identity(shared,message.hwnd) && shared->controllerPid==message.wParam
            && shared->nonce==static_cast<std::uint64_t>(message.lParam)
            && shared->layout==std::uint64_t(reinterpret_cast<std::uintptr_t>(GetKeyboardLayout(0)))
            && !stopped && ownerThread==GetCurrentThreadId() && load(&shared->command)==1
            && load(&shared->recording)==1 && load(&shared->ack)==1
            && !loadSigned(&shared->status) && !loadSigned(&shared->overflow)
            && !load(&shared->armedEpoch) && !loadSigned(&shared->count)
            && static_cast<std::uint32_t>(load(&shared->readiness.request))==request
            && static_cast<std::uint32_t>(load(&shared->readiness.ack))==request-1;
    };
    if(!admitted() || sample.layout!=shared->layout) {
        sample.status=-1;
    } else {
        // Nonconsuming, but GetQueueStatus changes LOW-word newness bookkeeping.
        // Neither this snapshot nor neutral thread keys prove dispatch/semantics.
        sample.queueStatus=GetQueueStatus(QS_INPUT);  // Zero is a VALID result.
        if(!admitted()) sample.status=-3;
        else {
            sample.keyboardSucceeded=GetKeyboardState(sample.keyboard)?1:0;
            sample.keyboardError=sample.keyboardSucceeded?0:GetLastError();
            if(!sample.keyboardSucceeded) sample.status=-2;
            if(!admitted()) sample.status=-3;
        }
    }
    sample.tickFinished=GetTickCount64();
    shared->readiness.sample=sample;
    publish(&shared->readiness.ack,static_cast<LONG>(request));  // Publish last.
}
// Source-pinned SAL messages: core bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1,
// vcl/inc/win/saldata.hxx (WM_USER+140/+141); salframe.cxx handles Set/ReleaseCapture.
static bool captureReading=false;
bool captureClock(std::uint64_t& counter) {
    LARGE_INTEGER now{},frequency{};
    if(!QueryPerformanceFrequency(&frequency) || !QueryPerformanceCounter(&now)
       || frequency.QuadPart<=0 || std::uint64_t(frequency.QuadPart)!=shared->captureFrequency
       || now.QuadPart<=0 || !shared->captureDeadline) {
        publish(&shared->captureRejected,load(&shared->captureRejected)|4);return false;
    }
    if(std::uint64_t(now.QuadPart)>=shared->captureDeadline) {
        publish(&shared->captureExpired,1);return false;
    }
    counter=std::uint64_t(now.QuadPart);return true;
}
void traceCapture(HWND hwnd,UINT message,WPARAM wp,LPARAM lp,std::uint32_t origin,WPARAM removalFlags) {
    if(!shared || stopped || !load(&shared->recording) || !load(&shared->captureEnabled)
       || ownerThread!=GetCurrentThreadId())return;
    if(message!=0x201 && message!=0x202 && message!=0x204 && message!=0x205
       && message!=0x207 && message!=0x208 && message!=0x20b && message!=0x20c
       && message!=WM_CAPTURECHANGED && message!=WM_SETFOCUS && message!=WM_KILLFOCUS
       && message!=OpenGeulAscii::SalPostFocus && message!=OpenGeulAscii::SalCaptureMouse && message!=OpenGeulAscii::SalReleaseMouse)return;
    if(std::uint64_t(reinterpret_cast<std::uintptr_t>(hwnd))!=shared->hwnd)return;
    if((origin==1 && removalFlags!=1 && removalFlags!=3) || (origin!=1 && removalFlags!=0)) {
        publish(&shared->captureRejected,load(&shared->captureRejected)|8);return;
    }
    if(captureReading){publish(&shared->captureRejected,load(&shared->captureRejected)|2);return;}
    captureReading=true;
    struct Exit {~Exit(){captureReading=false;}} exit;
    OpenGeulAscii::CaptureEvent event{};
    if(!captureClock(event.counter))return;
    if(!header(shared) || shared->captureVersion!=OpenGeulAscii::CaptureVersion
       || shared->captureReserved || shared->capturePadding || !identity(shared,hwnd)) {
        publish(&shared->captureRejected,load(&shared->captureRejected)|1);return;
    }
    std::uint64_t current=0;if(!captureClock(current))return;
    if(loadSigned(&shared->captureCount)>=static_cast<LONG>(OpenGeulAscii::CaptureCapacity)) {
        publishSigned(&shared->captureOverflow,1);return;
    }
    event.origin=origin;event.removeFlags=static_cast<std::uint32_t>(removalFlags);event.message=message;event.pid=GetCurrentProcessId();event.tid=GetCurrentThreadId();
    event.hwnd=shared->hwnd;event.engineCreationTime=shared->engineCreationTime;
    event.callbackDepth=static_cast<std::uint32_t>(InterlockedCompareExchange(&active,0,0));
    event.focusHwnd=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetFocus()));
    if(!captureClock(current))return;
    event.captureHwnd=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetCapture()));
    if(!captureClock(current))return;
    event.nativeTick=GetTickCount64();event.frequency=shared->captureFrequency;
    event.wParam=std::uint64_t(wp);event.lParam=std::uint64_t(lp);
    if(!captureClock(event.finishedCounter))return;
    const LONG index=incrementSigned(&shared->captureCount)-1;
    if(index<0 || index>=static_cast<LONG>(OpenGeulAscii::CaptureCapacity)) {
        publishSigned(&shared->captureOverflow,1);return;
    }
    shared->captureEvents[index]=event;
    publish(&shared->captureEvents[index].sequence,index+1);
}
// Separate navigation diagnostics; no text, waits, dispatch or input mutation.
void traceNavigation(HWND hwnd,UINT message,WPARAM wp,LPARAM lp,std::uint32_t origin) {
    if(!shared || stopped || !load(&shared->recording) || !load(&shared->traceEnabled)
       || ownerThread!=GetCurrentThreadId()) return;
    if(message!=WM_KEYDOWN && message!=WM_KEYUP && message!=WM_SYSKEYDOWN && message!=WM_SYSKEYUP) return;
    if(wp!=VK_TAB && wp!=VK_F2 && wp!=VK_CONTROL && wp!=VK_F6 && wp!=VK_END) return;
    if(std::uint64_t(reinterpret_cast<std::uintptr_t>(hwnd))!=shared->hwnd) return;
    if(!header(shared) || shared->traceVersion!=OpenGeulAscii::TraceVersion
       || shared->traceReserved || !identity(shared,hwnd)) {
        publish(&shared->traceRejected,1);return;
    }
    if(loadSigned(&shared->traceCount)>=static_cast<LONG>(OpenGeulAscii::TraceCapacity)) {
        publishSigned(&shared->traceOverflow,1);return;
    }
    LONG index=incrementSigned(&shared->traceCount)-1;
    if(index<0 || index>=static_cast<LONG>(OpenGeulAscii::TraceCapacity)) {
        publishSigned(&shared->traceOverflow,1);return;
    }
    auto& event=shared->traceEvents[index];
    event.origin=origin;event.message=message;event.vk=static_cast<std::uint32_t>(wp);
    event.pid=GetCurrentProcessId();event.tid=GetCurrentThreadId();
    event.hwnd=shared->hwnd;event.engineCreationTime=shared->engineCreationTime;
    // Handle values are observations, not lifetime/generation identities.
    event.focusHwnd=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetFocus()));
    event.captureHwnd=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetCapture()));
    LARGE_INTEGER counter{},frequency{};
    if(QueryPerformanceCounter(&counter)) event.counter=counter.QuadPart;
    if(QueryPerformanceFrequency(&frequency)) event.frequency=frequency.QuadPart;
    event.nativeTick=GetTickCount64();event.lParam=static_cast<std::uint64_t>(lp);
    event.layout=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetKeyboardLayout(0)));
    publish(&event.sequence,index+1);
}
// Bounded known-plugin file origin: private path never leaves the target mapping.
bool retrievalClock(std::uint64_t&);
std::uint32_t pluginOriginStatus(HMODULE module) {
    std::uint64_t stamp=0;
    return opengeul_stack::PluginOrigin(module,shared->pluginBinding,pluginBindingSnapshot,
        [&](){return retrievalClock(stamp);});
}

// Bounded retrieval metadata is independent of the already committed capture row.
static bool retrievalReading=false;

bool retrievalClock(std::uint64_t& counter) {
    if(captureClock(counter))return true;
    if(load(&shared->captureExpired))publish(&shared->retrievalExpired,1);
    else publish(&shared->retrievalRejected,load(&shared->retrievalRejected)|4);
    return false;
}
void traceRetrieval(const MSG& message,WPARAM removalFlags,std::uint32_t captureSequence) {
    if(!shared || stopped || !load(&shared->captureEnabled) || !load(&shared->recording))return;
    if(message.message!=0x201 && message.message!=0x202)return;
    if(removalFlags!=1 && removalFlags!=3)return;
    if(std::uint64_t(reinterpret_cast<std::uintptr_t>(message.hwnd))!=shared->hwnd)return;
    if(retrievalReading){publish(&shared->retrievalRejected,load(&shared->retrievalRejected)|2);return;}
    std::uint64_t stamp=0;if(!retrievalClock(stamp))return;
    if(ownerThread!=GetCurrentThreadId())return;
    if(!retrievalClock(stamp))return;
    const std::uint32_t bucket=message.message==0x201?0:(removalFlags==1?1:2), bit=1u<<bucket;
    if(load(&shared->retrievalClaimed)&bit)return;
    if(!header(shared) || shared->retrievalVersion!=OpenGeulAscii::RetrievalVersion || !captureSequence || captureSequence>OpenGeulAscii::CaptureCapacity) {
        publish(&shared->retrievalRejected,load(&shared->retrievalRejected)|1);return;
    }
    const auto& capture=shared->captureEvents[captureSequence-1];
    if(load(&capture.sequence)!=static_cast<LONG>(captureSequence) || capture.origin!=1 || capture.message!=message.message || capture.removeFlags!=removalFlags
       || capture.hwnd!=shared->hwnd || capture.pid!=shared->pid || capture.tid!=shared->tid || capture.engineCreationTime!=shared->engineCreationTime
       || capture.wParam!=std::uint64_t(message.wParam) || capture.lParam!=std::uint64_t(message.lParam) || capture.frequency!=shared->captureFrequency || capture.finishedCounter>stamp) {
        publish(&shared->retrievalRejected,load(&shared->retrievalRejected)|1);return;
    }
    retrievalReading=true;struct Exit {~Exit(){retrievalReading=false;}} exit;
    publish(&shared->retrievalClaimed,load(&shared->retrievalClaimed)|bit);
    OpenGeulAscii::RetrievalEvent row{};
    OpenGeulAscii::PluginOriginSample pluginOrigin{};
    row.captureSequence=captureSequence;row.bucket=bucket;row.message=message.message;row.removeFlags=static_cast<std::uint32_t>(removalFlags);
    row.pid=capture.pid;row.tid=capture.tid;row.hwnd=capture.hwnd;row.engineCreationTime=capture.engineCreationTime;
    row.counter=stamp;row.frequency=shared->captureFrequency;row.lParam=capture.lParam;
    row.pointX=message.pt.x;row.pointY=message.pt.y;
    POINT origin{};
    if(!retrievalClock(stamp))return;
    row.originSucceeded=ClientToScreen(message.hwnd,&origin)?1:0;
    if(!row.originSucceeded){row.originError=GetLastError();row.flags|=1;}
    if(!retrievalClock(stamp))return;
    if(row.originSucceeded){row.clientOriginX=origin.x;row.clientOriginY=origin.y;}
    if(bucket) {
        row.stackRequested=1;
        const auto clock=[&](){return retrievalClock(stamp);};
        const auto qualify=[&](HMODULE module) -> std::uint32_t {
            pluginOrigin.captureSequence=captureSequence;pluginOrigin.bucket=bucket;
            if(!retrievalClock(pluginOrigin.counter))return 0;
            pluginOrigin.status=pluginOriginStatus(module);
            if(!retrievalClock(pluginOrigin.finishedCounter))return 0;
            return pluginOrigin.status;
        };
        if(!opengeul_stack::Capture(row,clock,qualify,shared->pluginBinding.enabled!=0)) {
            if(row.flags&16)publish(&shared->retrievalRejected,load(&shared->retrievalRejected)|1);
            return;
        }
    }
    if(!retrievalClock(row.finishedCounter))return;
    if(bucket && shared->pluginBinding.enabled) {
        shared->pluginOrigins[bucket]=pluginOrigin;
        publish(&shared->pluginOrigins[bucket].sequence,bucket+1);
    }
    shared->retrievalEvents[bucket]=row;
    publish(&shared->retrievalEvents[bucket].sequence,bucket+1);
}
void observe(const MSG& message,WPARAM removed) {
    if(!shared || stopped || !load(&shared->recording) || ownerThread!=GetCurrentThreadId()) return;
    if(message.message<WM_KEYDOWN || message.message>WM_UNICHAR) return;
    const auto epoch=static_cast<std::uint32_t>(load(&shared->armedEpoch));
    if(!epoch) return;
    const auto hwnd=reinterpret_cast<HWND>(static_cast<std::uintptr_t>(shared->hwnd));
    if(!header(shared) || !identity(shared,hwnd)) {
        publishSigned(&shared->status,-3); publish(&shared->recording,0); return;
    }
    LONG index=incrementSigned(&shared->count)-1;
    if(index<0 || index>=static_cast<LONG>(OpenGeulAscii::Capacity)) {
        publishSigned(&shared->overflow,1); publish(&shared->recording,0); return;
    }
    Event& event=shared->events[index];
    DWORD pid=0;
    GetWindowThreadProcessId(message.hwnd,&pid);
    event.actionEpoch=epoch; event.origin=1; event.remove=static_cast<std::uint32_t>(removed);
    event.message=message.message; event.pid=pid; event.tid=GetCurrentThreadId(); event.messageTime=message.time;
    event.hwnd=std::uint64_t(reinterpret_cast<std::uintptr_t>(message.hwnd));
    event.layout=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetKeyboardLayout(0)));
    event.wParam=std::uint64_t(message.wParam); event.lParam=static_cast<std::uint64_t>(message.lParam);
    event.extraInfo=static_cast<std::uint64_t>(GetMessageExtraInfo()); event.nativeTick=GetTickCount64();
    event.shiftState=GetKeyState(VK_SHIFT); event.controlState=GetKeyState(VK_CONTROL);
    event.altState=GetKeyState(VK_MENU); event.capsState=GetKeyState(VK_CAPITAL);
    event.flags=0; event.reserved=0;
    // Release publication: the controller MUST acquire this individual word
    // before copying the immutable row, then confirm the same word afterward.
    publish(&event.sequence,index+1);
}
}

extern "C" __declspec(dllexport) LRESULT CALLBACK HookCall(int code,WPARAM wp,LPARAM lp) {
    if(code<0) return CallNextHookEx(nullptr,code,wp,lp);
    Callback callback;
    if(code==HC_ACTION && lp) {
        const CWPSTRUCT& message=*reinterpret_cast<const CWPSTRUCT*>(lp);
        const UINT startMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Start.v2");
        const UINT stopMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Stop.v2");
        const UINT readinessMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Readiness.v2");
        if(startMessage && message.message==startMessage) start(message);
        else if(stopMessage && message.message==stopMessage) stop(message);
        else if(readinessMessage && message.message==readinessMessage) queryReadiness(message,startMessage,stopMessage,readinessMessage);
        else {traceNavigation(message.hwnd,message.message,message.wParam,message.lParam,2);
            traceCapture(message.hwnd,message.message,message.wParam,message.lParam,2,0);}
    }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(int code,WPARAM wp,LPARAM lp) {
    if(code<0) return CallNextHookEx(nullptr,code,wp,lp);
    Callback callback;
    if(code==HC_ACTION && lp) {
        const auto& message=*reinterpret_cast<const MSG*>(lp);
        if(wp==PM_REMOVE) traceNavigation(message.hwnd,message.message,message.wParam,message.lParam,1);
        if((wp & PM_REMOVE)!=0) {
            const auto before=shared && load(&shared->captureEnabled)?loadSigned(&shared->captureCount):0;
            traceCapture(message.hwnd,message.message,message.wParam,message.lParam,1,wp);
            if(shared && load(&shared->captureEnabled) && loadSigned(&shared->captureCount)==before+1)
                traceRetrieval(message,wp,static_cast<std::uint32_t>(before+1));
        }
        observe(message,wp);
    }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookReturn(int code,WPARAM wp,LPARAM lp) {
    if(code<0) return CallNextHookEx(nullptr,code,wp,lp);
    Callback callback;
    if(code==HC_ACTION && lp) {
        const auto& message=*reinterpret_cast<const CWPRETSTRUCT*>(lp);
        traceNavigation(message.hwnd,message.message,message.wParam,message.lParam,3);
        traceCapture(message.hwnd,message.message,message.wParam,message.lParam,3,0);
    }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) unsigned int StateSize() { return sizeof(State); }
extern "C" __declspec(dllexport) unsigned int EventSize() { return sizeof(Event); }
extern "C" __declspec(dllexport) unsigned int EventsOffset() { return offsetof(State,events); }
extern "C" __declspec(dllexport) unsigned int ReadinessSampleSize() { return sizeof(OpenGeulAscii::QueueSample); }
extern "C" __declspec(dllexport) unsigned int ReadinessOffset() { return offsetof(State,readiness); }
extern "C" __declspec(dllexport) unsigned int ReadWord(const std::uint32_t* word) { return static_cast<unsigned int>(load(word)); }
extern "C" __declspec(dllexport) void PublishWord(std::uint32_t* word,unsigned int value) { publish(word,static_cast<LONG>(value)); }
BOOL WINAPI DllMain(HINSTANCE,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_DETACH) forgetView();  // No waits or UI/model calls.
    return TRUE;
}
