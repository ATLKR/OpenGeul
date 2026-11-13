#include "../native.cpp"
#include <cassert>
#include <iostream>
using namespace opengeul::writer_observer;
int main(){
    int mode=0;std::cin>>mode;auto& m=fake_win::mapping;auto& h=m.identity;
    h.magic=Magic;h.version=1;h.bytes=sizeof(Mapping);h.capacity=Capacity;h.controllerPid=7;h.controllerBirth=19;h.nonce=10;
    h.ownerPid=8;h.ownerTid=9;h.ownerBirth=20;h.ownerHwnd=99;h.startQpc=100;h.deadlineQpc=400;h.cutoffQpc=350;h.qpcFrequency=10;h.namespaceCode=1;
    store(m.control.admission,mode==1?0:2);fake_win::pinFail=mode==2;fake_win::late=mode==4;
    SinkRequest r{80,2,1,0,reinterpret_cast<AccObjectWinManager*>(1),nullptr,99,0,110,0,0,0,0,0};SinkReply reply{};
    auto callback=observer_sink();assert(callback(&r,&reply)==(mode==1||mode==2||mode==4?3u:1u));
    if(mode==1||mode==2||mode==4){store(m.control.admission,2);fake_win::pinFail=false;fake_win::late=false;assert(callback(&r,&reply)==3);assert(fake_win::pinCalls==1);assert(!load(m.control.setupObserved));return 0;}
    r.action=2;r.qpcSample=125;r.peer=reinterpret_cast<IMAccessible*>(2);assert(callback(&r,&reply)==2);
    r.action=3;r.kind=2;r.manager=nullptr;r.hwnd=0;r.qpcSample=130;fake_win::dead=mode==3;
    auto waits=fake_win::waits;callback(&r,&reply);assert(fake_win::waits==waits+1);
    if(mode==3){assert(!reply.scopeOrdinal&&!load(m.control.reservedCount)&&load(m.control.rejected)==1);return 0;}
    assert(reply.scopeOrdinal);auto token=reply.scopeOrdinal;r.action=4;r.scopeOrdinal=token;r.phase=2;r.datum=3;r.qpcSample=140;
    auto queries=fake_win::queries;waits=fake_win::waits;callback(&r,&reply);assert(fake_win::queries==queries&&fake_win::waits==waits);
    store(m.control.admission,3);bits(m.control.captureGate,ClosedBit);r.action=5;r.phase=0;r.datum=0;r.qpcSample=400;callback(&r,&reply);
    assert(load(m.control.captureGate)==ClosedBit&&load(m.control.committedCount)==2);
}
