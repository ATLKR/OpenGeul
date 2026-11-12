#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>

namespace opengeul_ime { namespace finalization {
constexpr uint32_t Magic=0x4f474631,Version=1;
struct Config {
    uint32_t magic=0,version=0,configBytes=0,sectionBytes=0,mappingBytes=0,sectionOffset=0,enabled=0,pid=0,tid=0,reserved=0;
    uint64_t targetHwnd=0,rootHwnd=0,creationTime=0,epochLow=0,epochHigh=0;
};
struct Row {
    uint32_t sequence=0,stage=0,status=0,pid=0,tid=0,ackAtStart=0,withinBefore=0,withinAfter=0;
    uint64_t targetHwnd=0,rootHwnd=0,focusBefore=0,focusAfter=0,himc=0,layout=0,startedCounter=0,finishedCounter=0;
    uint32_t contextPresent=0,conversionSucceeded=0,open=0,conversion=0,sentence=0,releaseAttempts=0,releaseSucceeded=0,reserved=0;
    uint64_t deadlineCounter=0,counterFrequency=0;
};
struct Section {
    Config config{};
    alignas(4) volatile uint32_t claimedMask=0,publishedMask=0,rejected=0,reserved=0;
    Row rows[3]{};
};
static_assert(sizeof(Config)==80 && sizeof(Row)==144 && sizeof(Section)==528,"diagnostic ABI");
static_assert(offsetof(Section,claimedMask)%4==0 && offsetof(Section,publishedMask)%4==0,"Interlocked alignment");
inline bool Valid(const Config& c,const Config& expected) {
    return c.magic==Magic && c.version==Version && c.configBytes==sizeof(Config) && c.sectionBytes==sizeof(Section)
        && c.sectionOffset>0 && !(c.sectionOffset%8) && c.mappingBytes==uint64_t(c.sectionOffset)+sizeof(Section)
        && c.enabled==1 && c.pid && c.tid && c.targetHwnd && c.rootHwnd && c.creationTime && c.epochLow && c.epochHigh && !c.reserved
        && !std::memcmp(&c,&expected,sizeof(Config));
}
template<class Prefix> bool MappingBound(const Prefix* state,const Section* section,const Config& expected) {
    return state && section && state->magic==0x4f47494d && state->version==4
        && state->pid==expected.pid && state->tid==expected.tid
        && state->targetHwnd==expected.targetHwnd && state->rootHwnd==expected.rootHwnd
        && Valid(section->config,expected);
}
// Api supplies fixed guarded reads, aligned atomics and exactly paired context
// release. No function here writes command status, ACK or an IME mode.
template<class Api> bool Capture(Api& api,Section& section,const Config& expected,uint32_t stage,uint32_t command) {
    if(stage<1 || stage>3 || command!=3 || !Valid(section.config,expected) || !api.Admitted(expected))return false;
    const uint32_t before=(uint32_t(1)<<(stage-1))-1,bit=uint32_t(1)<<(stage-1);
    if(!api.Claim(section.claimedMask,before,before|bit))return false;
    Row row{};row.sequence=row.stage=stage;row.pid=expected.pid;row.tid=expected.tid;
    row.targetHwnd=expected.targetHwnd;row.rootHwnd=expected.rootHwnd;
    try { api.Observe(row,expected); }
    catch(...) { row.status=8; }
    // A foreign/recycled original target cannot publish a row. The claim is
    // consumed and remains incomplete: it never lends a retry or input right.
    if(!Valid(section.config,expected)||!api.Admitted(expected))return false;
    section.rows[stage-1]=row;
    api.Publish(section.publishedMask,bit);
    return true;
}
} }
