#pragma once
// Fixed negative requests only. There is no serialized request, path or mode input.
#include "context_observer.hpp"
namespace sdk_gate {
struct Clock { std::uint64_t now,frequency; };
inline bool empty_failure(packaged_context::Result const&r,int expected) {
  return !r.complete&&!r.simulation_only&&r.failure_code==expected&&
    !r.all_handles_together&&!r.generation_rechecked&&r.cleanup_proved&&
    !r.started&&r.finished>0&&r.directories.empty()&&r.local_known.empty()&&r.roaming_known.empty()&&
    r.process.full_name.empty()&&r.process.family_name.empty()&&r.process.sid.empty()&&
    !r.process.pid&&!r.process.creation&&!r.process.native_machine&&!r.process.process_machine;
}
template<class Observe,class ReadClock>
int run(Observe observe,ReadClock read_clock,std::uint16_t native_machine) noexcept {
  try {
    auto c=read_clock();
    if((native_machine!=0x8664&&native_machine!=0xaa64)||!c.frequency||c.frequency>10000000000ULL||
      c.now<=3*c.frequency||c.now>std::numeric_limits<std::uint64_t>::max()-90*c.frequency)return 90;
    packaged_context::Request invalid;
    if(!empty_failure(observe(invalid),2))return 91;
    packaged_context::Request expired;
    expired.expected.full_name=L"sdk_negative_only";expired.expected.family_name=L"sdk_negative_only";
    expired.expected.sid=L"sdk_negative_only";expired.expected.native_machine=native_machine;
    expired.product_local=L"C:\\sdk_negative_only\\Local\\org.allenlabs.opengeul";
    expired.product_roaming=L"C:\\sdk_negative_only\\Roaming\\org.allenlabs.opengeul";
    expired.start_qpc=c.now-2*c.frequency;expired.observer_deadline=c.now-c.frequency;
    expired.phase_deadline=c.now+c.frequency;expired.frequency=c.frequency;
    expired.request_sha256=std::string(64,'1');expired.bundle_sha256=std::string(64,'2');
    if(!empty_failure(observe(expired),10))return 92;
    return 0;
  }catch(...){return 93;}
}
} // namespace sdk_gate
