#include "session.h"
#include <cassert>
#include <thread>
#include <vector>
using namespace opengeul::writer_observer;
int main(){SessionGate gate;std::atomic<unsigned> winners{0};std::vector<std::thread> ts;
    for(unsigned i=0;i<16;++i)ts.emplace_back([&]{if(gate.begin())++winners;});
    for(auto& t:ts){t.join();}
    assert(winners==1&&gate.state()==SessionState::Initializing);gate.finish(false);
    assert(gate.state()==SessionState::Failed&&!gate.begin());gate.finish(true);assert(gate.state()==SessionState::Failed);
    SinkRequest r{};r.bytes=80;r.abiVersion=2;r.action=99;assert(!valid_request(r));
    r.action=1;r.manager=reinterpret_cast<AccObjectWinManager*>(1);r.hwnd=99;assert(valid_request(r));
    r.reserved2=1;assert(!valid_request(r));
}
