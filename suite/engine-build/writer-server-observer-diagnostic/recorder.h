#pragma once
#include "atomic.h"
#include "private_sink.hxx"
#include "descriptor.h"
#include <array>
#include <cstring>
namespace opengeul::writer_observer {
struct Key { AccObjectWinManager* manager{}; IMAccessible* peer{}; std::uintptr_t hwnd{}; };
inline bool same(Key a,Key b) noexcept {
    return a.peer==b.peer&&(!a.manager||a.manager==b.manager)&&(!a.hwnd||a.hwnd==b.hwnd);
}
inline bool valid_event(Kind kind,Phase phase,std::uint32_t datum) noexcept {
    if(phase==Phase::Enter)return kind==Kind::Focus?datum>=1&&datum<=3:datum==0&&(kind==Kind::Route||kind==Kind::Getter);
    if(phase==Phase::Leave)return datum==0&&(kind==Kind::Route||kind==Kind::Getter||kind==Kind::Focus);
    if(kind==Kind::Getter){
        if(phase==Phase::LockAcquired)return datum==0;
        if(phase==Phase::Branch)return datum>=1&&datum<=6;
        if(phase==Phase::TagWritten||phase==Phase::OutputComplete)return datum==1||datum==2;
        if(phase==Phase::Return)return datum<=3;
    }
    if(kind==Kind::Focus){
        if(phase==Phase::Return)return datum==0||datum==1||datum==3;
        if(phase==Phase::Assignment)return datum==2||datum==3;
        if(phase==Phase::ParentCallBefore||phase==Phase::ParentCallAfter)return datum>=1&&datum<=3;
    }
    return kind==Kind::Route&&phase==Phase::ApiReturn&&datum>=1&&datum<=3;
}
struct OwnerFacts { std::uint32_t pid,tid; std::uint64_t birth,hwnd,controllerBirth; };
inline bool admitted(Mapping const& m,Descriptor d,OwnerFacts f,std::int64_t now,std::int64_t frequency) noexcept {
    if(load(m.control.admission)!=static_cast<unsigned>(Admission::Armed))return false;
    auto const& h=m.identity;
    if(h.magic!=Magic||h.version!=IpcVersion||h.bytes!=sizeof(Mapping)||h.capacity!=Capacity||h.namespaceCode!=1
       ||h.reserved0||h.reserved1||h.reserved2[0]||h.reserved2[1]||h.reserved2[2])return false;
    if(h.controllerPid!=d.controllerPid||h.controllerBirth!=d.controllerBirth||h.nonce!=d.nonce
       ||f.controllerBirth!=d.controllerBirth||!h.ownerPid||!h.ownerTid||!h.ownerBirth||!h.ownerHwnd
       ||h.ownerPid!=f.pid||h.ownerTid!=f.tid||h.ownerBirth!=f.birth||h.ownerHwnd!=f.hwnd)return false;
    if(frequency<=0||frequency>INT64_MAX/30||h.qpcFrequency!=frequency||h.startQpc<0||h.deadlineQpc<=h.startQpc)return false;
    auto span=h.deadlineQpc-h.startQpc;
    return span<=frequency*30&&span>frequency*5&&h.cutoffQpc==h.deadlineQpc-frequency*5
        &&now>=h.startQpc&&now<h.cutoffQpc&&load(m.control.admission)==static_cast<unsigned>(Admission::Armed);
}
class RootGate {
    std::atomic<std::uint32_t> state_{static_cast<unsigned>(RootState::Unbound)};
    Key key_{};
    std::int64_t boundQpc_{};
public:
    RootState state() const noexcept {return static_cast<RootState>(state_.load(std::memory_order_acquire));}
    bool claim() noexcept {auto expected=static_cast<unsigned>(RootState::Unbound);return state_.compare_exchange_strong(expected,static_cast<unsigned>(RootState::Claimed),std::memory_order_acq_rel);}
    bool publish(Key key,std::int64_t qpc=0) noexcept {
        key_=key;boundQpc_=qpc;
        auto expected=static_cast<unsigned>(RootState::Claimed);
        return state_.compare_exchange_strong(expected,static_cast<unsigned>(RootState::Ready),std::memory_order_release,std::memory_order_acquire);
    }
    void reject_rebind() noexcept {state_.exchange(static_cast<unsigned>(RootState::Invalid),std::memory_order_acq_rel);}
    bool matches(Key key) const noexcept {return state()==RootState::Ready&&same(key,key_);}
    bool accepts(Key key,std::int64_t qpc) const noexcept {return state()==RootState::Ready&&same(key,key_)&&qpc>=boundQpc_;}
    void invalidate(Action action,Key key) noexcept {
        auto s=state();
        if(s==RootState::Invalid)return;
        if(s==RootState::Ready){
            bool relevant=action==Action::InvalidateObject?key.peer==key_.peer:
                action==Action::InvalidateManager?key.manager==key_.manager:
                key.manager==key_.manager&&key.hwnd==key_.hwnd;
            if(!relevant)return;
        }
        state_.exchange(static_cast<unsigned>(RootState::Invalid),std::memory_order_acq_rel);
    }
};
class EventLog {
    Mapping& mapping_;
public:
    explicit EventLog(Mapping& m) noexcept:mapping_(m){}
    std::uint32_t reserve() noexcept {
        auto& c=mapping_.control;auto n=load(c.reservedCount);
        for(unsigned i=0;i<32&&n<Capacity;++i)if(cas(c.reservedCount,n,n+1))return n+1;
        bump(c.dropped);store(c.overflow,1);bits(c.incomplete,ReservationOverflow);return 0;
    }
    void publish(std::uint32_t ticket,Row row) noexcept {
        if(!ticket||ticket>Capacity)return;
        row.commit=0;row.eventOrdinal=ticket;
        std::memcpy(&mapping_.rows[ticket-1].kind,&row.kind,sizeof(Row)-sizeof(row.commit));
        store(mapping_.rows[ticket-1].commit,ticket);
        bump(mapping_.control.committedCount);
    }
};
struct Snapshot { std::array<Row,Capacity> rows{};std::uint32_t count{},holes{},invalid{}; };
inline Snapshot snapshot(Mapping const& m) noexcept {
    Snapshot out{};auto count=load(m.control.reservedCount);
    if(count>Capacity){out.invalid=1;return out;}
    for(std::uint32_t i=0;i<count;++i){
        auto first=load(m.rows[i].commit);
        if(!first){++out.holes;continue;}
        if(first!=i+1){++out.invalid;continue;}
        auto row=m.rows[i];
        if(load(m.rows[i].commit)!=first||row.eventOrdinal!=first||row.reserved0||row.reserved1
           ||!valid_event(static_cast<Kind>(row.kind),static_cast<Phase>(row.phase),row.datum)){
            ++out.invalid;continue;
        }
        out.rows[out.count++]=row;
    }
    return out;
}
class Recorder {
    struct Frame {std::uint64_t token,parent;Kind kind;Key key;};
    struct Thread {Recorder* owner{};std::uint32_t ordinal{},depth{};bool inside{};Frame stack[MaxDepth]{};};
    template<class T> static T ordinal(std::atomic<T>& counter) noexcept {
        auto n=counter.load(std::memory_order_acquire);
        for(unsigned i=0;i<32&&n<Capacity;++i)if(counter.compare_exchange_strong(n,n+1,std::memory_order_acq_rel))return n+1;
        return 0;
    }
    static Thread& thread() noexcept {static thread_local Thread value;return value;}
    std::atomic<Mapping*> mapping_{nullptr};
    RootGate root_;
    std::atomic<std::uint64_t> nextScope_{0};
    std::atomic<std::uint32_t> nextThread_{0};
    void mirror_root(Mapping& m) noexcept {
        auto next=static_cast<unsigned>(root_.state());auto n=load(m.control.rootState);
        for(unsigned i=0;i<32&&n<next;++i)if(cas(m.control.rootState,n,next))return;
    }
    bool allowed(Key key,std::int64_t qpc) const noexcept {
        auto m=mapping_.load(std::memory_order_acquire);
        if(m&&qpc>=m->identity.cutoffQpc){store(m->control.expired,1);bits(m->control.incomplete,Expired);}
        return m&&root_.accepts(key,qpc)&&load(m->control.admission)==static_cast<unsigned>(Admission::Armed)
            &&!(load(m->control.captureGate)&ClosedBit)&&qpc>=m->identity.startQpc&&qpc<m->identity.cutoffQpc;
    }
    void release_active(Mapping& m) noexcept {
        auto n=load(m.control.captureGate);
        for(unsigned attempt=0;attempt<32;++attempt){
            if(!(n&~ClosedBit)){bits(m.control.incomplete,TokenMismatch);bump(m.control.cleanupErrors);return;}
            if(cas(m.control.captureGate,n,n-1))return;
        }
        bits(m.control.incomplete,TokenMismatch);bump(m.control.cleanupErrors);
    }
    void append(Frame f,Phase phase,std::uint32_t datum,std::int64_t qpc,Thread& t) noexcept {
        auto m=mapping_.load(std::memory_order_acquire);
        if(!allowed(f.key,qpc)||!valid_event(f.kind,phase,datum))return;
        EventLog log(*m);auto ticket=log.reserve();if(!ticket)return;
        Row row{};row.kind=static_cast<unsigned>(f.kind);row.phase=static_cast<unsigned>(phase);row.datum=datum;
        row.scopeOrdinal=f.token;row.parentScopeOrdinal=f.parent;row.qpc=qpc;row.depth=t.depth;row.threadOrdinal=t.ordinal;
        if(!allowed(f.key,qpc)){bits(m->control.incomplete,PublicationHole);return;}
        log.publish(ticket,row);
    }
public:
    void attach(Mapping& m) noexcept {mapping_.store(&m,std::memory_order_release);mirror_root(m);}
    bool bind(Key key,std::int64_t qpc) noexcept {
        auto m=mapping_.load(std::memory_order_acquire);
        if(!m||!key.manager||!key.peer||key.hwnd!=m->identity.ownerHwnd||qpc<m->identity.startQpc||qpc<m->control.setupReadyQpc||qpc>=m->identity.cutoffQpc
            ||load(m->control.admission)!=static_cast<unsigned>(Admission::Armed))return false;
        if(root_.state()==RootState::Ready){if(root_.matches(key))return true;root_.reject_rebind();}
        if(!root_.claim()){mirror_root(*m);return false;}
        if(!root_.publish(key,qpc)){mirror_root(*m);return false;}
        m->control.rootReadyQpc=qpc;store(m->control.rootBoundObserved,1);mirror_root(*m);return root_.matches(key);
    }
    void invalidate(Action action,Key key) noexcept {
        root_.invalidate(action,key);
        if(auto m=mapping_.load(std::memory_order_acquire)){
            mirror_root(*m);
            if(root_.state()==RootState::Invalid)bits(m->control.incomplete,Invalidated);
        }
    }
    std::uint64_t enter(Key key,Kind kind,std::uint32_t datum,std::int64_t qpc) noexcept {
        auto m=mapping_.load(std::memory_order_acquire);if(!m||!allowed(key,qpc)||!valid_event(kind,Phase::Enter,datum))return 0;
        auto& t=thread();if(t.inside){bits(m->control.incomplete,Reentered);return 0;}
        if(t.owner!=this){if(t.depth){bits(m->control.incomplete,TokenMismatch);return 0;}t={};t.owner=this;t.ordinal=ordinal(nextThread_);}
        if(!t.ordinal){store(m->control.overflow,1);bits(m->control.incomplete,ReservationOverflow);return 0;}
        if(t.depth==MaxDepth){bits(m->control.incomplete,DepthExceeded);return 0;}
        auto gate=load(m->control.captureGate);bool taken=false;
        for(unsigned i=0;i<32&&!(gate&ClosedBit)&&gate<ClosedBit-1;++i)if(cas(m->control.captureGate,gate,gate+1)){taken=true;break;}
        if(!taken){
            if(!(gate&ClosedBit)){bump(m->control.dropped);bits(m->control.incomplete,PublicationHole);}
            return 0;
        }
        if(!allowed(key,qpc)){release_active(*m);return 0;}
        t.inside=true;auto token=ordinal(nextScope_);
        if(!token){t.inside=false;store(m->control.overflow,1);bits(m->control.incomplete,ReservationOverflow);release_active(*m);return 0;}
        Frame f{token,t.depth?t.stack[t.depth-1].token:0,kind,key};t.stack[t.depth++]=f;
        append(f,Phase::Enter,datum,qpc,t);t.inside=false;return token;
    }
    void mark(std::uint64_t token,Key key,Phase phase,std::uint32_t datum,std::int64_t qpc) noexcept {
        auto m=mapping_.load(std::memory_order_acquire);auto& t=thread();
        if(!token||!m)return;
        if(t.inside){bits(m->control.incomplete,Reentered);return;}
        if(t.owner!=this||!t.depth||t.stack[t.depth-1].token!=token||!same(key,t.stack[t.depth-1].key)){bits(m->control.incomplete,TokenMismatch);return;}
        if(!valid_event(t.stack[t.depth-1].kind,phase,datum)){bits(m->control.incomplete,BadRequest);return;}
        t.inside=true;append(t.stack[t.depth-1],phase,datum,qpc,t);t.inside=false;
    }
    void leave(std::uint64_t token,Key key,Kind kind,std::int64_t qpc) noexcept {
        auto m=mapping_.load(std::memory_order_acquire);auto& t=thread();if(!token||!m)return;
        if(t.owner!=this||!t.depth||t.stack[t.depth-1].token!=token||t.stack[t.depth-1].kind!=kind||!same(key,t.stack[t.depth-1].key)){
            bits(m->control.incomplete,TokenMismatch);return;
        }
        if(!t.inside){t.inside=true;append(t.stack[t.depth-1],Phase::Leave,0,qpc,t);t.inside=false;}
        --t.depth;release_active(*m);
    }
};
static_assert(std::atomic<std::uint64_t>::is_always_lock_free&&std::atomic<Mapping*>::is_always_lock_free);
}
