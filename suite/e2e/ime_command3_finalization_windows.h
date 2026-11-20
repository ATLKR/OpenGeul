#pragma once
// Included only after the observer's State/identity/budget helpers are defined.
// These probes never call observe_imm or modify its authoritative result slots.
class FinalizationApi {
    const opengeul_ime::CommandBudget limits;
public:
    explicit FinalizationApi(const opengeul_ime::CommandBudget& b):limits(b){}
    bool Admitted(const opengeul_ime::finalization::Config& c) {
        FILETIME made{},exited{},kernel{},user{};
        return shared && shared->pid==c.pid && shared->tid==c.tid
            && shared->targetHwnd==c.targetHwnd && shared->rootHwnd==c.rootHwnd
            && c.pid==GetCurrentProcessId() && c.tid==GetCurrentThreadId()
            && original_target(HWND(UINT_PTR(c.targetHwnd)),true)
            && GetProcessTimes(GetCurrentProcess(),&made,&exited,&kernel,&user)
            && ((uint64_t(made.dwHighDateTime)<<32)|made.dwLowDateTime)==c.creationTime;
    }
    bool Claim(volatile uint32_t& value,uint32_t before,uint32_t after) {
        return uint32_t(InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&value),after,before))==before;
    }
    void Publish(volatile uint32_t& value,uint32_t bit) {
        MemoryBarrier();InterlockedOr(reinterpret_cast<volatile LONG*>(&value),bit);
    }
    void Observe(opengeul_ime::finalization::Row& row,const opengeul_ime::finalization::Config& c) {
        row.deadlineCounter=limits.counter;row.counterFrequency=limits.frequency;
        LARGE_INTEGER stamp{};
        if(QueryPerformanceCounter(&stamp)&&stamp.QuadPart>0)row.startedCounter=uint64_t(stamp.QuadPart);
        row.ackAtStart=uint32_t(InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&shared->ack),0,0));
        row.focusBefore=uint64_t(UINT_PTR(GetFocus()));row.layout=uint64_t(UINT_PTR(GetKeyboardLayout(0)));
        row.withinBefore=budget(limits)?1:0;
        if(!row.startedCounter||!row.withinBefore)row.status=2;
        if(!row.status) {
            const auto hwnd=HWND(UINT_PTR(c.targetHwnd));
            struct Context {
                HWND hwnd;HIMC value;opengeul_ime::finalization::Row& row;
                ~Context(){if(value){++row.releaseAttempts;row.releaseSucceeded=ImmReleaseContext(hwnd,value)?1:0;if(!row.releaseSucceeded&&!row.status)row.status=5;}}
            } context{hwnd,ImmGetContext(hwnd),row};
            row.contextPresent=context.value?1:0;row.himc=uint64_t(UINT_PTR(context.value));
            if(!context.value)row.status=3;
            else {
                row.open=ImmGetOpenStatus(context.value)?1:0;
                DWORD conversion=0,sentence=0;
                row.conversionSucceeded=ImmGetConversionStatus(context.value,&conversion,&sentence)?1:0;
                row.conversion=conversion;row.sentence=sentence;
                if(!row.conversionSucceeded)row.status=4;
            }
        }
        row.focusAfter=uint64_t(UINT_PTR(GetFocus()));row.withinAfter=budget(limits)?1:0;
        if(!row.status&&!row.withinAfter)row.status=7;
        if(!row.status&&(row.focusBefore!=c.targetHwnd||row.focusAfter!=c.targetHwnd))row.status=6;
        stamp={};if(QueryPerformanceCounter(&stamp)&&stamp.QuadPart>0)row.finishedCounter=uint64_t(stamp.QuadPart);
        if(!row.finishedCounter||row.finishedCounter<row.startedCounter)row.status=8;
    }
};
static void capture_finalization(uint32_t stage,UINT command,const opengeul_ime::CommandBudget& limits) {
    if(!finalizationEnabled||!finalizationShared)return;
    FinalizationApi api(limits);
    opengeul_ime::finalization::Capture(api,*finalizationShared,expectedFinalization,stage,command);
}
