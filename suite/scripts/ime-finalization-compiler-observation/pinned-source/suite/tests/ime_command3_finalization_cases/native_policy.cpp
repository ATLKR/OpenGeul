#include "ime_command3_finalization.h"
#include <cassert>
using namespace opengeul_ime::finalization;
struct Api {
    bool owned=true,throwRead=false,changeOwner=false;uint32_t calls=0,publishes=0,claims=0,status=0;
    bool Admitted(const Config&){return owned;}
    bool Claim(volatile uint32_t& value,uint32_t expected,uint32_t next){if(value!=expected)return false;value=next;++claims;return true;}
    void Publish(volatile uint32_t& value,uint32_t bit){value|=bit;++publishes;}
    void Observe(Row& r,const Config&){++calls;if(throwRead)throw 1;r.status=status;r.startedCounter=10;r.finishedCounter=11;if(changeOwner)owned=false;}
};
Config valid(){Config c{};c.magic=Magic;c.version=Version;c.configBytes=sizeof(Config);c.sectionBytes=sizeof(Section);c.sectionOffset=596896;c.mappingBytes=c.sectionOffset+sizeof(Section);c.enabled=1;c.pid=1;c.tid=2;c.targetHwnd=3;c.rootHwnd=4;c.creationTime=5;c.epochLow=6;c.epochHigh=7;return c;}
int main(){
    const auto expected=valid();
    {Section s{};s.config=expected;Api a;for(uint32_t n=1;n<=3;++n)assert(Capture(a,s,expected,n,3));assert(s.claimedMask==7&&s.publishedMask==7&&a.calls==3&&a.publishes==3);}
    {Section s{};s.config=expected;Api a;assert(!Capture(a,s,expected,2,3));assert(!Capture(a,s,expected,0,3));assert(!Capture(a,s,expected,4,3));assert(!Capture(a,s,expected,1,2));assert(a.calls==0&&s.claimedMask==0);}
    {Section s{};s.config=expected;Api a;assert(Capture(a,s,expected,1,3));assert(!Capture(a,s,expected,1,3));assert(a.calls==1);}
    for(int n=0;n<9;++n){Section s{};s.config=expected;Api a;switch(n){case 0:++s.config.version;break;case 1:--s.config.mappingBytes;break;case 2:++s.config.sectionOffset;break;case 3:++s.config.epochLow;break;case 4:++s.config.pid;break;case 5:++s.config.tid;break;case 6:++s.config.creationTime;break;case 7:++s.config.targetHwnd;break;default:a.owned=false;}assert(!Capture(a,s,expected,1,3));assert(!a.claims&&!a.calls&&!s.publishedMask);}
    {Section s{};s.config=expected;Api a;a.throwRead=true;assert(Capture(a,s,expected,1,3));assert(s.rows[0].status==8&&s.publishedMask==1);}
    {Section s{};s.config=expected;Api a;a.changeOwner=true;assert(!Capture(a,s,expected,1,3));assert(s.claimedMask==1&&s.publishedMask==0&&a.publishes==0);}
    for(uint32_t status=2;status<=7;++status){Section s{};s.config=expected;Api a;a.status=status;assert(Capture(a,s,expected,1,3));assert(s.rows[0].status==status);}
}
