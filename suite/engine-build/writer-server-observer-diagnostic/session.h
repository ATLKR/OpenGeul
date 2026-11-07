#pragma once
#include "private_sink.hxx"
namespace opengeul::writer_observer {
class SessionGate {
    std::atomic<std::uint32_t> value_{static_cast<unsigned>(SessionState::Uninitialized)};
public:
    SessionState state() const noexcept {return static_cast<SessionState>(value_.load(std::memory_order_acquire));}
    bool begin() noexcept {auto expected=static_cast<unsigned>(SessionState::Uninitialized);
        return value_.compare_exchange_strong(expected,static_cast<unsigned>(SessionState::Initializing),std::memory_order_acq_rel);}
    void finish(bool success) noexcept {auto expected=static_cast<unsigned>(SessionState::Initializing);
        value_.compare_exchange_strong(expected,static_cast<unsigned>(success?SessionState::Ready:SessionState::Failed),std::memory_order_release,std::memory_order_acquire);}
};
inline bool valid_request(SinkRequest const& r) noexcept {
    if(r.bytes!=sizeof(SinkRequest)||r.abiVersion!=SinkAbiVersion||r.reserved0||r.reserved1||r.reserved2)return false;
    auto action=static_cast<Action>(r.action);auto kind=static_cast<Kind>(r.kind);
    if(action==Action::Setup)return kind==Kind::Control&&r.manager&&!r.peer&&r.hwnd&&!r.scopeOrdinal&&!r.phase&&!r.datum;
    if(action==Action::BindRoot)return kind==Kind::Control&&r.manager&&r.peer&&r.hwnd&&!r.scopeOrdinal&&!r.phase&&!r.datum;
    if(action==Action::InvalidateObject)return kind==Kind::Control&&!r.manager&&r.peer&&!r.hwnd&&!r.scopeOrdinal&&!r.phase&&r.datum==1;
    if(action==Action::InvalidateMap)return kind==Kind::Control&&r.manager&&!r.peer&&r.hwnd&&!r.scopeOrdinal&&!r.phase&&(r.datum==2||r.datum==3);
    if(action==Action::InvalidateManager)return kind==Kind::Control&&r.manager&&!r.peer&&!r.hwnd&&!r.scopeOrdinal&&!r.phase&&r.datum==4;
    if(!r.peer||(kind!=Kind::Route&&kind!=Kind::Getter&&kind!=Kind::Focus))return false;
    if(kind==Kind::Route){if(!r.manager||!r.hwnd)return false;}
    else if(r.manager||r.hwnd)return false;
    if(action==Action::Enter)return !r.scopeOrdinal&&!r.phase&&(kind==Kind::Focus?r.datum>=1&&r.datum<=3:r.datum==0);
    if(action==Action::Leave)return r.scopeOrdinal&&!r.phase&&!r.datum;
    return action==Action::Mark&&r.scopeOrdinal&&r.phase>=1&&r.phase<=9;
}
}
