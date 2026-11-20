#include "recorder.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>
using namespace opengeul::writer_observer;
static Key key{reinterpret_cast<AccObjectWinManager*>(1),reinterpret_cast<IMAccessible*>(2),99};
static std::unique_ptr<Mapping> mapping(){
    auto m=std::make_unique<Mapping>();auto& h=m->identity;
    h.magic=Magic;h.version=1;h.bytes=sizeof(Mapping);h.capacity=Capacity;
    h.controllerPid=7;h.controllerBirth=19;h.nonce=10;h.ownerPid=8;h.ownerTid=9;
    h.ownerBirth=20;h.ownerHwnd=99;h.startQpc=100;h.deadlineQpc=400;h.qpcFrequency=10;h.cutoffQpc=350;h.namespaceCode=1;
    store(m->control.admission,2);return m;
}
int main(){
    unsigned passed=0;
    {auto m=mapping();Descriptor d{7,19,10};OwnerFacts f{8,9,20,99,19};
     assert(admitted(*m,d,f,100,10));store(m->control.admission,0);assert(!admitted(*m,d,f,100,10));
     store(m->control.admission,2);m->identity.deadlineQpc=401;assert(!admitted(*m,d,f,100,10));++passed;}
    {RootGate gate;assert(gate.claim());gate.invalidate(Action::InvalidateObject,{});assert(!gate.publish(key));
     assert(gate.state()==RootState::Invalid);assert(!gate.matches(key));++passed;}
    {RootGate gate;gate.invalidate(Action::InvalidateMap,{});assert(!gate.claim());++passed;}
    {auto m=mapping();EventLog log(*m);assert(log.reserve()==1);auto second=log.reserve();Row row{};
     row.kind=2;row.phase=2;row.datum=3;log.publish(second,row);auto s=snapshot(*m);
     assert(s.holes==1&&s.count==1&&s.rows[0].eventOrdinal==2);++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));auto outer=r.enter(key,Kind::Getter,0,120);
     auto inner=r.enter(key,Kind::Focus,2,121);assert(outer&&inner);r.invalidate(Action::InvalidateObject,key);
     r.mark(inner,key,Phase::Assignment,2,122);r.leave(inner,key,Kind::Focus,123);r.leave(outer,key,Kind::Getter,124);
     assert((load(m->control.captureGate)&~ClosedBit)==0);assert(load(m->control.committedCount)==2);assert(load(m->control.rootState)==3);++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));auto token=r.enter(key,Kind::Getter,0,120);
     store(m->control.admission,3);bits(m->control.captureGate,ClosedBit);r.mark(token,key,Phase::Branch,3,121);
     r.leave(token,key,Kind::Getter,122);assert(load(m->control.captureGate)==ClosedBit);assert(load(m->control.committedCount)==1);++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));auto token=r.enter(key,Kind::Getter,0,120);
     r.mark(token,key,Phase::Branch,3,350);r.leave(token,key,Kind::Getter,351);
     assert(load(m->control.expired)==1&&load(m->control.committedCount)==1&&load(m->control.captureGate)==0);++passed;}
    {auto m=mapping();EventLog log(*m);for(unsigned i=0;i<Capacity;++i)assert(log.reserve()==i+1);
     assert(!log.reserve());assert(load(m->control.overflow)==1&&load(m->control.reservedCount)==Capacity);++passed;}
    {auto m=mapping();EventLog log(*m);std::vector<std::thread> ts;
     for(unsigned t=0;t<8;++t)ts.emplace_back([&]{for(unsigned i=0;i<32;++i){auto ticket=log.reserve();assert(ticket);Row row{};row.kind=1;row.phase=9;row.datum=1;log.publish(ticket,row);}});
     for(auto& t:ts){t.join();}
     auto s=snapshot(*m);assert(s.count==256&&s.holes==0&&s.invalid==0);++passed;}
    {assert(!valid_event(Kind::Getter,static_cast<Phase>(99),0));assert(!valid_event(Kind::Getter,Phase::Branch,0));
     auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));auto token=r.enter(key,Kind::Getter,0,120);
     r.mark(token,key,Phase::Branch,77,121);r.leave(token,key,Kind::Getter,122);
     assert(load(m->control.incomplete)&BadRequest);assert(load(m->control.committedCount)==2);++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));auto a=r.enter(key,Kind::Getter,0,120);
     auto b=r.enter(key,Kind::Focus,1,121);r.leave(a,key,Kind::Getter,122);
     assert(load(m->control.captureGate)==2);r.leave(b,key,Kind::Focus,123);r.leave(a,key,Kind::Getter,124);
     assert(load(m->control.captureGate)==0&&(load(m->control.incomplete)&TokenMismatch));++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));std::vector<std::thread> ts;
     for(unsigned t=0;t<8;++t)ts.emplace_back([&]{for(unsigned i=0;i<16;++i){auto token=r.enter(key,Kind::Getter,0,120);assert(token);r.mark(token,key,Phase::Branch,3,121);r.leave(token,key,Kind::Getter,122);}});
     for(auto& t:ts){t.join();}
     auto out=snapshot(*m);assert(out.count==384&&!out.holes&&!out.invalid&&load(m->control.captureGate)==0);++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));std::vector<std::uint64_t> tokens;
     for(unsigned i=0;i<MaxDepth;++i){auto token=r.enter(key,Kind::Getter,0,120);assert(token);tokens.push_back(token);}
     assert(!r.enter(key,Kind::Getter,0,121));
     for(auto it=tokens.rbegin();it!=tokens.rend();++it){r.leave(*it,key,Kind::Getter,122);}
     assert(load(m->control.captureGate)==0&&(load(m->control.incomplete)&DepthExceeded));++passed;}
    {auto m=mapping();m->control.setupReadyQpc=115;Recorder r;r.attach(*m);
     assert(!r.bind(key,110));assert(r.bind(key,120));assert(!r.enter(key,Kind::Getter,0,119));
     auto token=r.enter(key,Kind::Getter,0,121);assert(token);r.leave(token,key,Kind::Getter,122);
     auto out=snapshot(*m);assert(out.count==2&&out.rows[0].qpc>=120);++passed;}
    {auto m=mapping();Recorder r;r.attach(*m);assert(r.bind(key,110));
     for(unsigned i=0;i<Capacity;++i){auto token=r.enter(key,Kind::Getter,0,120);assert(token&&token<=Capacity);r.leave(token,key,Kind::Getter,121);}
     assert(!r.enter(key,Kind::Getter,0,122));assert(load(m->control.captureGate)==0);++passed;}
    assert(passed==15);std::cout<<"{\"contractsPassed\":15}";
}
