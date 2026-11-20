#include <opengeul_writer_observer/observer_api.hxx>
#include <opengeul_writer_observer/recorder.h>
#include <opengeul_writer_observer/session.h>
#include <cwchar>

#if !defined(_WIN64) || !defined(OPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC)
#error Writer observer requires the separately marked Windows x64/ARM64 diagnostic build
#endif
namespace opengeul::writer_observer {
namespace {
SessionGate session;
Recorder recorder;
struct Context {HANDLE controller{},mapping{};Mapping* view{};};
Context context;
Context failedContext;
std::uint32_t OPENGEUL_WRITER_CDECL sink(SinkRequest const*,SinkReply*) noexcept;
std::uint64_t birth(HANDLE handle) noexcept {
    FILETIME created{},exited{},kernel{},user{};
    if(!GetProcessTimes(handle,&created,&exited,&kernel,&user))return 0;
    return (std::uint64_t(created.dwHighDateTime)<<32)|created.dwLowDateTime;
}
void failed_cleanup(Context& local) noexcept {
    if(local.view&&UnmapViewOfFile(local.view))local.view=nullptr;
    if(local.mapping&&CloseHandle(local.mapping))local.mapping=nullptr;
    if(local.controller&&CloseHandle(local.controller))local.controller=nullptr;
    failedContext=local;
}
Status setup(SinkRequest const& request) noexcept {
    if(!session.begin())return session.state()==SessionState::Ready?Status::SessionReady:
        session.state()==SessionState::Failed?Status::Failed:Status::Unknown;
    Context local{};bool success=false;
    do {
        HMODULE module{};
        // PIN is a permanent diagnostic-only lifetime change. Setup APIs may block.
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                reinterpret_cast<LPCWSTR>(&sink),&module)||!module)break;
        wchar_t value[129]{};
        DWORD length=GetEnvironmentVariableW(Environment,value,129);
        Descriptor config{};
        if(!length||length>=129||!descriptor(value,config))break;
        wchar_t name[128]{};
        if(std::swprintf(name,128,L"Local\\%ls-%u-%016llx",MappingNamespace,config.controllerPid,
                         static_cast<unsigned long long>(config.nonce))<=0)break;
        local.mapping=OpenFileMappingW(FILE_MAP_READ|FILE_MAP_WRITE,FALSE,name);
        if(!local.mapping)break;
        local.view=static_cast<Mapping*>(MapViewOfFile(local.mapping,FILE_MAP_READ|FILE_MAP_WRITE,0,0,sizeof(Mapping)));
        if(!local.view||load(local.view->control.admission)!=static_cast<unsigned>(Admission::Armed))break;
        auto const& identity=local.view->identity;
        if(request.hwnd!=identity.ownerHwnd)break;
        auto window=reinterpret_cast<HWND>(identity.ownerHwnd);
        DWORD pid{};
        auto tid=GetWindowThreadProcessId(window,&pid);
        if(!IsWindow(window)||pid!=GetCurrentProcessId()||!tid)break;
        local.controller=OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION,FALSE,config.controllerPid);
        if(!local.controller||GetProcessId(local.controller)!=config.controllerPid
           ||WaitForSingleObject(local.controller,0)!=WAIT_TIMEOUT)break;
        OwnerFacts facts{pid,tid,birth(GetCurrentProcess()),identity.ownerHwnd,birth(local.controller)};
        LARGE_INTEGER frequency{},now{};
        if(!QueryPerformanceFrequency(&frequency)||!QueryPerformanceCounter(&now)
           ||!admitted(*local.view,config,facts,now.QuadPart,frequency.QuadPart))break;
        auto const& c=local.view->control;
        bool reservedZero=true;for(auto v:c.reserved)if(v)reservedZero=false;
        if(!reservedZero||load(c.captureGate)||load(c.reservedCount)||load(c.committedCount)
           ||load(c.sessionState)||load(c.rootState)||c.nextScopeOrdinal||c.setupReadyQpc||c.rootReadyQpc)break;
        if(!QueryPerformanceCounter(&now)||WaitForSingleObject(local.controller,0)!=WAIT_TIMEOUT
           ||!admitted(*local.view,config,facts,now.QuadPart,frequency.QuadPart))break;
        context=local;
        recorder.attach(*context.view);
        context.view->control.setupReadyQpc=now.QuadPart;
        store(context.view->control.setupObserved,1);
        store(context.view->control.sessionState,static_cast<unsigned>(SessionState::Ready));
        success=true;
    } while(false);
    if(!success)failed_cleanup(local);
    session.finish(success);
    return success?Status::SessionReady:Status::Failed;
}
std::uint32_t OPENGEUL_WRITER_CDECL sink(SinkRequest const* request,SinkReply* reply) noexcept {
    if(!reply)return static_cast<unsigned>(Status::Unknown);
    *reply={32,2,static_cast<unsigned>(Status::Unknown),0,0,0};
    if(!request||!valid_request(*request))return reply->status;
    auto const& r=*request;auto action=static_cast<Action>(r.action);auto kind=static_cast<Kind>(r.kind);
    Key key{r.manager,r.peer,r.hwnd};Status status=Status::NoEvent;
    if(action==Action::InvalidateObject||action==Action::InvalidateMap||action==Action::InvalidateManager){
        auto state=session.state();
        if(state==SessionState::Initializing||state==SessionState::Ready)recorder.invalidate(action,key);
    } else if(action==Action::Setup){status=setup(r);}
    else if(action==Action::Leave){
        // Token cleanup is independent of root invalidation, Closed and cutoff.
        if(session.state()==SessionState::Ready)recorder.leave(r.scopeOrdinal,key,kind,r.qpcSample);
    } else if(session.state()==SessionState::Ready){
        if(action==Action::BindRoot)status=recorder.bind(key,r.qpcSample)?Status::RootReady:Status::Unknown;
        else if(action==Action::Enter){
            // Enter samples the captured controller HANDLE with timeout0.
            // Mark and invalidation perform no native liveness query.
            if(WaitForSingleObject(context.controller,0)==WAIT_TIMEOUT){
                reply->scopeOrdinal=recorder.enter(key,kind,r.datum,r.qpcSample);
                status=reply->scopeOrdinal?Status::RootReady:Status::NoEvent;
            } else {bump(context.view->control.rejected);bits(context.view->control.incomplete,BadRequest);}
        } else if(action==Action::Mark)recorder.mark(r.scopeOrdinal,key,static_cast<Phase>(r.phase),r.datum,r.qpcSample);
    }
    if(session.state()==SessionState::Ready){reply->flags=load(context.view->control.incomplete);store(context.view->control.lastStatus,static_cast<unsigned>(status));}
    reply->status=static_cast<unsigned>(status);return reply->status;
}
}
Sink observer_sink() noexcept {return &sink;}
}
