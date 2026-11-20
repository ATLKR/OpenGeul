#include "wire.h"
#include "private_sink.hxx"
#include "descriptor.h"
#include <cassert>
#include <iostream>
using namespace opengeul::writer_observer;
int main(){
    Descriptor d{};
    assert(descriptor(L"1:7:19:000000000000000a:131328:OpenGeulWriterServerObserver",d));
    assert(d.controllerPid==7&&d.controllerBirth==19&&d.nonce==10);
    wchar_t const* bad[]={L"1:0:19:000000000000000a:131328:OpenGeulWriterServerObserver",
        L"1:07:19:000000000000000a:131328:OpenGeulWriterServerObserver",
        L"1:7:0:000000000000000a:131328:OpenGeulWriterServerObserver",
        L"1:7:19:0000000000000000:131328:OpenGeulWriterServerObserver",
        L"1:7:19:000000000000000A:131328:OpenGeulWriterServerObserver",
        L"1:7:19:000000000000000a:131329:OpenGeulWriterServerObserver",
        L"1:7:19:000000000000000a:131328:OpenGeulCalcDispatch",
        L"1:7:19:000000000000000a:131328:OpenGeulWriterServerObserver:30"};
    for(auto s:bad)assert(!descriptor(s,d));
    std::cout<<"{\"identityBytes\":128,\"controlBytes\":128,\"rowBytes\":64,\"mappingBytes\":131328,"
        "\"sinkRequestBytes\":80,\"sinkReplyBytes\":32,\"descriptorAccepted\":1,\"malformedRejected\":8}";
}
