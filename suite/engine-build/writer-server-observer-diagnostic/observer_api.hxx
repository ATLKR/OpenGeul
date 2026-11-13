#pragma once
#include "atomic.h"
#include "private_sink.hxx"
namespace opengeul::writer_observer {
Sink observer_sink() noexcept;
inline std::int64_t qpc() noexcept {LARGE_INTEGER value{};return QueryPerformanceCounter(&value)?value.QuadPart:0;}
inline SinkReply call(Sink sink,Action action,Kind kind,AccObjectWinManager* manager,IMAccessible* peer,
                      std::uintptr_t hwnd,std::uint64_t token=0,Phase phase=Phase::None,std::uint32_t datum=0) noexcept {
    const bool invalidation = action == Action::InvalidateObject || action == Action::InvalidateMap || action == Action::InvalidateManager;
    SinkRequest r{80,2,static_cast<unsigned>(action),static_cast<unsigned>(kind),manager,peer,hwnd,token,invalidation ? 0 : qpc(),static_cast<unsigned>(phase),datum,0,0,0};
    SinkReply reply{32,2,0,0,0,0};if(sink)sink(&r,&reply);return reply;
}
inline void invalid_object(IMAccessible* peer) noexcept {call(observer_sink(),Action::InvalidateObject,Kind::Control,nullptr,peer,0,0,Phase::None,1);}
inline void invalid_map(Sink sink,AccObjectWinManager* manager,std::uintptr_t hwnd,std::uint32_t reason) noexcept {
    call(sink,Action::InvalidateMap,Kind::Control,manager,nullptr,hwnd,0,Phase::None,reason);
}
inline void invalid_manager(Sink sink,AccObjectWinManager* manager) noexcept {call(sink,Action::InvalidateManager,Kind::Control,manager,nullptr,0,0,Phase::None,4);}
inline void bind_root(Sink sink,AccObjectWinManager* manager,IMAccessible* peer,std::uintptr_t hwnd) noexcept {
    call(sink,Action::BindRoot,Kind::Control,manager,peer,hwnd);
}
class Scope {
    Sink sink_;Kind kind_;AccObjectWinManager* manager_;IMAccessible* peer_;std::uintptr_t hwnd_;std::uint64_t token_;
public:
    Scope(Sink sink,Kind kind,AccObjectWinManager* manager,IMAccessible* peer,std::uintptr_t hwnd,std::uint32_t datum) noexcept:
        sink_(sink),kind_(kind),manager_(manager),peer_(peer),hwnd_(hwnd),token_(call(sink,Action::Enter,kind,manager,peer,hwnd,0,Phase::None,datum).scopeOrdinal){}
    Scope(Scope const&)=delete;Scope& operator=(Scope const&)=delete;
    ~Scope(){if(token_)call(sink_,Action::Leave,kind_,manager_,peer_,hwnd_,token_);}
    void mark(Phase phase,std::uint32_t datum) noexcept {if(token_)call(sink_,Action::Mark,kind_,manager_,peer_,hwnd_,token_,phase,datum);}
};
class Route {
    Sink sink_;AccObjectWinManager* manager_;std::uintptr_t hwnd_;bool ready_;IMAccessible* peer_{};std::uint64_t token_{};
public:
    Route(Sink sink,AccObjectWinManager* manager,std::uintptr_t hwnd,bool client) noexcept:sink_(sink),manager_(manager),hwnd_(hwnd),
        ready_(client&&call(sink,Action::Setup,Kind::Control,manager,nullptr,hwnd).status==static_cast<unsigned>(Status::SessionReady)){}
    Route(Route const&)=delete;Route& operator=(Route const&)=delete;
    bool ready()const noexcept{return ready_;}
    void enter(IMAccessible* peer) noexcept {peer_=peer;if(ready_)token_=call(sink_,Action::Enter,Kind::Route,manager_,peer,hwnd_).scopeOrdinal;}
    void result(std::uint32_t datum) noexcept {if(token_)call(sink_,Action::Mark,Kind::Route,manager_,peer_,hwnd_,token_,Phase::ApiReturn,datum);}
    ~Route(){if(token_)call(sink_,Action::Leave,Kind::Route,manager_,peer_,hwnd_,token_);}
};
}
