#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cwchar>
#include "ascii_message_protocol.h"

namespace {
using OpenGeulAscii::Event;
using OpenGeulAscii::State;
State* shared = nullptr;
HANDLE mapping = nullptr;
volatile LONG active = 0;
DWORD ownerThread = 0;
bool stopped = true;
bool releaseFailed = false;
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
    ownerThread=0;
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
    const UINT startMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Start.v1");
    const UINT stopMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Stop.v1");
    if(command!=1 || !header(shared) || shared->controllerPid!=message.wParam || shared->nonce!=nonce
       || shared->startMessage!=startMessage || shared->stopMessage!=stopMessage
       || !identity(shared,message.hwnd) || shared->count!=0 || shared->overflow || shared->status
       || shared->layout!=std::uint64_t(reinterpret_cast<std::uintptr_t>(GetKeyboardLayout(0)))) {
        publishSigned(&shared->status,-1);
        forgetView(); return;
    }
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
        const UINT startMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Start.v1");
        const UINT stopMessage=RegisterWindowMessageW(L"OpenGeul.AsciiObserver.Stop.v1");
        if(startMessage && message.message==startMessage) start(message);
        else if(stopMessage && message.message==stopMessage) stop(message);
    }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(int code,WPARAM wp,LPARAM lp) {
    if(code<0) return CallNextHookEx(nullptr,code,wp,lp);
    Callback callback;
    if(code==HC_ACTION && lp) observe(*reinterpret_cast<const MSG*>(lp),wp);
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) unsigned int StateSize() { return sizeof(State); }
extern "C" __declspec(dllexport) unsigned int EventSize() { return sizeof(Event); }
extern "C" __declspec(dllexport) unsigned int EventsOffset() { return offsetof(State,events); }
extern "C" __declspec(dllexport) unsigned int ReadWord(const std::uint32_t* word) { return static_cast<unsigned int>(load(word)); }
extern "C" __declspec(dllexport) void PublishWord(std::uint32_t* word,unsigned int value) { publish(word,static_cast<LONG>(value)); }
BOOL WINAPI DllMain(HINSTANCE,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_DETACH) forgetView();  // No waits or UI/model calls.
    return TRUE;
}
