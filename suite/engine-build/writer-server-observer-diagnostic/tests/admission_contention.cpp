#include <opengeul_writer_observer/recorder.h>
#include <cassert>
#include <atomic>
#include <cstdlib>
#include <thread>
using namespace opengeul::writer_observer;
std::atomic<unsigned> command{0},ack{0};unsigned attempts=0;std::thread::id owner;
volatile LONG* targetGate;std::atomic<bool> force{false};
void contention(volatile LONG* pointer,LONG,LONG expected){
    if(!force.load()||pointer!=targetGate||expected==0||std::this_thread::get_id()!=owner)return;
    if(++attempts>32)std::exit(72);
    command.store(attempts);while(ack.load()!=attempts)std::this_thread::yield();
}
int main(){Mapping m{};m.identity.startQpc=100;m.identity.cutoffQpc=350;m.identity.ownerHwnd=99;store(m.control.admission,2);
    Key key{reinterpret_cast<AccObjectWinManager*>(1),reinterpret_cast<IMAccessible*>(2),99};Recorder r;r.attach(m);assert(r.bind(key,110));
    auto token=r.enter(key,Kind::Getter,0,120);assert(token);owner=std::this_thread::get_id();targetGate=reinterpret_cast<volatile LONG*>(&m.control.captureGate);fake_win::casHook=contention;
    std::thread worker([&]{std::uint64_t held=0;unsigned seen=0;for(;;){auto cmd=command.load();if(cmd==100)return;if(cmd==seen){std::this_thread::yield();continue;}
        if(cmd%2){held=r.enter(key,Kind::Getter,0,130);assert(held);}else{r.leave(held,key,Kind::Getter,131);held=0;}
        seen=cmd;ack.store(cmd);}});
    force.store(true);auto missing=r.enter(key,Kind::Getter,0,132);force.store(false);command.store(100);worker.join();
    assert(!missing);r.leave(token,key,Kind::Getter,133);
    assert(attempts==32&&load(m.control.captureGate)==0&&load(m.control.dropped)>0&&(load(m.control.incomplete)&PublicationHole));
    auto out=snapshot(m);assert(!out.holes);
}
