#pragma once
// Source-only read-only observation core. This supplies no launcher or authority.
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>
namespace packaged_context {
struct Failure { int code; };
struct Process {
  std::wstring full_name, family_name, sid;
  std::uint32_t pid=0; std::uint64_t creation=0;
  std::uint16_t native_machine=0, process_machine=0;
};
struct Directory {
  std::wstring logical_path, final_path;
  std::uint64_t volume=0, creation=0;
  std::array<std::uint8_t,16> file_id{};
  bool reparse=false, retained=false, closed=false;
};
struct Request {
  Process expected; std::wstring product_local, product_roaming;
  std::uint64_t start_qpc=0,phase_deadline=0,observer_deadline=0,frequency=0;
  std::string request_sha256,bundle_sha256;
};
struct Result {
  bool complete=false,simulation_only=true,all_handles_together=false,generation_rechecked=false,cleanup_proved=false;
  int failure_code=0; Process process; std::wstring local_known,roaming_known;
  std::vector<Directory> directories; std::uint64_t started=0,finished=0;
};
inline bool digest(std::string const& s) {
  return s.size()==64&&std::all_of(s.begin(),s.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');});
}
inline std::wstring fold(std::wstring s) { for(auto& c:s)if(c>=L'A'&&c<=L'Z')c=static_cast<wchar_t>(c+(L'a'-L'A'));return s; }
inline bool path(std::wstring const& s) {
  if(s.size()<3||s.size()>1024||!((s[0]>=L'A'&&s[0]<=L'Z')||(s[0]>=L'a'&&s[0]<=L'z'))||s[1]!=L':'||s[2]!=L'\\')return false;
  std::size_t units=0;
  for(std::size_t i=0;i<s.size();++i) {
    auto c=static_cast<std::uint32_t>(s[i]);
    if(c>=0xd800&&c<=0xdbff){if(i+1==s.size())return false;auto low=static_cast<std::uint32_t>(s[++i]);if(low<0xdc00||low>0xdfff)return false;units+=2;}
    else if((c>=0xdc00&&c<=0xdfff)||c>0x10ffff)return false;
    else units+=c>0xffff?2:1;
    if(units>1024)return false;
  }
  for(std::size_t i=3;i<s.size();) {
    auto end=s.find(L'\\',i);if(end==std::wstring::npos)end=s.size();auto part=s.substr(i,end-i);
    if(part.empty()||part==L"."||part==L".."||part.back()==L'.'||part.back()==L' ')return false;
    for(auto c:part)if(c<32||c==127||c==L':'||c==L'/'||c==L'"'||c==L'<'||c==L'>'||c==L'|'||c==L'?'||c==L'*')return false;
    auto base=fold(part.substr(0,part.find(L'.')));
    if(base==L"con"||base==L"prn"||base==L"aux"||base==L"nul"||(base.size()==4&&(base.substr(0,3)==L"com"||base.substr(0,3)==L"lpt")&&((base[3]>=L'1'&&base[3]<=L'9')||base[3]==0xb9||base[3]==0xb2||base[3]==0xb3)))return false;
    i=end+1;if(end<s.size()&&i==s.size())return false;
  }
  return true;
}
inline bool same_process(Process const&a,Process const&b) {
  return a.full_name==b.full_name&&a.family_name==b.family_name&&a.sid==b.sid&&a.pid==b.pid&&a.creation==b.creation&&a.native_machine==b.native_machine&&a.process_machine==b.process_machine;
}
inline bool same_directory(Directory const&a,Directory const&b) {
  return fold(a.final_path)==fold(b.final_path)&&a.volume==b.volume&&a.file_id==b.file_id&&a.creation==b.creation&&!a.reparse&&!b.reparse;
}
inline void directory_valid(Directory const& d) {
  if(!path(d.final_path)||!d.creation||d.reparse||!std::any_of(d.file_id.begin(),d.file_id.end(),[](std::uint8_t n){return n!=0;}))throw Failure{8};
}
template<class Port> Result collect(Request const&r,Port& port) noexcept {
  Result out;out.simulation_only=port.simulation_only;std::vector<std::uint64_t> held;bool close_ok=true;
  auto clock=[&](){auto now=port.now();if(now<r.start_qpc||now>=r.observer_deadline)throw Failure{10};return now;};
  auto step=[&](auto fn){clock();auto v=fn();clock();return v;};
  try {
    held.reserve(4);out.directories.reserve(3);
    if(!r.start_qpc||!r.frequency||r.frequency>10000000000ULL||r.start_qpc>std::numeric_limits<std::uint64_t>::max()-90*r.frequency||
       !(r.start_qpc<r.observer_deadline&&r.observer_deadline<=r.phase_deadline&&r.phase_deadline<=r.start_qpc+90*r.frequency&&r.observer_deadline<=r.start_qpc+10*r.frequency)||
       !path(r.product_local)||!path(r.product_roaming)||!digest(r.request_sha256)||!digest(r.bundle_sha256)||
       r.expected.full_name.empty()||r.expected.family_name.empty()||r.expected.sid.empty()||
       (r.expected.native_machine!=0x8664&&r.expected.native_machine!=0xaa64))throw Failure{2};
    out.started=clock();if(step([&](){return port.frequency();})!=r.frequency)throw Failure{10};
    out.process=step([&](){return port.process();});
    if(out.process.full_name!=r.expected.full_name||out.process.family_name!=r.expected.family_name||out.process.sid!=r.expected.sid||
       out.process.native_machine!=r.expected.native_machine||out.process.process_machine!=0||!out.process.pid||!out.process.creation)throw Failure{3};
    out.local_known=step([&](){return port.known_folder(false);});out.roaming_known=step([&](){return port.known_folder(true);});
    if(!path(out.local_known)||!path(out.roaming_known)||fold(r.product_local)!=fold(out.local_known+L"\\org.allenlabs.opengeul")||fold(r.product_roaming)!=fold(out.roaming_known+L"\\org.allenlabs.opengeul"))throw Failure{4};
    std::wstring local_state=step([&](){return port.local_folder();});if(!path(local_state))throw Failure{6};
    std::array<std::wstring,3> paths={r.product_local,r.product_roaming,local_state};
    auto open=[&](std::wstring const& logical) {
      clock();auto h=port.open_existing(logical,128,7,3);
      if(!h||std::find(held.begin(),held.end(),h)!=held.end())throw Failure{7};
      held.push_back(h);clock();return h;
    };
    for(auto const& logical:paths) {
      auto h=open(logical);
      auto d=step([&](){return port.directory(h);});directory_valid(d);d.logical_path=logical;d.retained=true;out.directories.push_back(d);
    }
    out.all_handles_together=held.size()==3;
    for(std::size_t i=0;i<3;i++)for(std::size_t k=0;k<i;k++)if(out.directories[i].volume==out.directories[k].volume&&out.directories[i].file_id==out.directories[k].file_id)throw Failure{9};
    for(std::size_t i=0;i<3;i++) {
      auto again=step([&](){return port.directory(held[i]);});directory_valid(again);if(!same_directory(again,out.directories[i]))throw Failure{9};
      auto fresh=open(paths[i]);
      auto current=step([&](){return port.directory(fresh);});directory_valid(current);if(!same_directory(current,out.directories[i]))throw Failure{9};
      held.pop_back();
      if(!port.close(fresh)){close_ok=false;throw Failure{11};}
      clock();
    }
    if(!same_process(out.process,step([&](){return port.process();})))throw Failure{3};
    out.generation_rechecked=true;
  } catch(Failure const& f){out.failure_code=f.code;} catch(...){out.failure_code=31;}
  for(auto it=held.rbegin();it!=held.rend();++it){try{if(!port.close(*it))close_ok=false;}catch(...){close_ok=false;}}
  out.cleanup_proved=close_ok;
  try{out.finished=port.now();if(out.finished>=r.observer_deadline&&!out.failure_code)out.failure_code=10;}catch(...){if(!out.failure_code)out.failure_code=31;}
  if(!close_ok&&!out.failure_code)out.failure_code=11;
  out.complete=!out.failure_code&&close_ok&&out.all_handles_together&&out.generation_rechecked&&out.directories.size()==3;
  if(out.complete)for(auto& d:out.directories)d.closed=true;
  return out;
}
inline std::string quoted(std::wstring const& value) {
  static constexpr char hex[]="0123456789abcdef";std::string out="\"";
  auto unicode=[&](std::uint32_t c){out+="\\u";for(int shift=12;shift>=0;shift-=4)out+=hex[(c>>shift)&15];};
  for(std::size_t i=0;i<value.size();++i) {
    auto c=static_cast<std::uint32_t>(value[i]);
    if(c>=0xd800&&c<=0xdbff){if(i+1==value.size())throw Failure{30};auto low=static_cast<std::uint32_t>(value[++i]);if(low<0xdc00||low>0xdfff)throw Failure{30};unicode(c);unicode(low);}
    else if(c>=0xdc00&&c<=0xdfff)throw Failure{30};
    else if(c==L'"'||c==L'\\'){out+='\\';out+=static_cast<char>(c);}
    else if(c>=32&&c<127)out+=static_cast<char>(c);
    else if(c<=0xffff)unicode(c);
    else if(c<=0x10ffff){c-=0x10000;unicode(0xd800+(c>>10));unicode(0xdc00+(c&1023));}
    else throw Failure{30};
  }
  return out+'"';
}
inline std::string flags() {return "\"actualWindowsExecuted\":false,\"qualification\":false,\"canService\":false,\"originalHelperHandleKnown\":false,\"controllerOwnershipKnown\":false,\"durableLease\":false,\"watchdogVerified\":false,\"osImplicitEffectsKnown\":false,\"createdByThisRun\":false,\"preexistingAdopted\":false";}
inline std::string to_json(Result const&o,Request const&r) {
  auto boolean=[](bool b){return b?"true":"false";};
  if(!o.complete)return "{\"schemaVersion\":1,\"kind\":\"packaged-context-readonly-failure\",\"failureCode\":"+std::to_string(o.failure_code?o.failure_code:31)+",\"observationComplete\":false,\"simulationOnly\":"+boolean(o.simulation_only)+","+flags()+"}";
  if(o.directories.size()!=3||o.failure_code||!o.cleanup_proved||!o.all_handles_together||!o.generation_rechecked||
     !o.process.pid||!o.process.creation||!o.started||o.finished<o.started||o.finished>=r.observer_deadline||
     !digest(r.request_sha256)||!digest(r.bundle_sha256))throw Failure{30};
  for(auto const& d:o.directories){directory_valid(d);if(!path(d.logical_path)||!d.retained||!d.closed)throw Failure{30};}
  auto const&p=o.process;std::string s="{\"schemaVersion\":1,\"kind\":\"packaged-context-readonly-observation\",\"observationComplete\":true,\"failureCode\":0,\"simulationOnly\":"+std::string(boolean(o.simulation_only))+","+flags()+",\"requestSha256\":\""+r.request_sha256+"\",\"sourceBundleSha256\":\""+r.bundle_sha256+"\",\"package\":{\"fullName\":"+quoted(p.full_name)+",\"familyName\":"+quoted(p.family_name)+",\"userSid\":"+quoted(p.sid)+",\"pid\":"+std::to_string(p.pid)+",\"createdFileTime\":"+std::to_string(p.creation)+",\"nativeMachine\":"+std::to_string(p.native_machine)+",\"processMachine\":"+std::to_string(p.process_machine)+"},\"knownFolders\":{\"localAppData\":"+quoted(o.local_known)+",\"roamingAppData\":"+quoted(o.roaming_known)+"},\"directories\":{";
  static constexpr char hex[]="0123456789abcdef";char const* names[]={"productLocalData","productRoamingData","localState"};
  for(std::size_t i=0;i<o.directories.size();i++){auto const&d=o.directories[i];if(i)s+=",";std::string id;for(auto byte:d.file_id){id+=hex[byte>>4];id+=hex[byte&15];}s+='"'+std::string(names[i])+"\":{\"logicalPath\":"+quoted(d.logical_path)+",\"finalPath\":"+quoted(d.final_path)+",\"volumeSerial\":"+std::to_string(d.volume)+",\"fileId\":\""+id+"\",\"creationFileTime\":"+std::to_string(d.creation)+",\"desiredAccess\":128,\"shareMode\":7,\"openDisposition\":3,\"reparse\":false,\"handleRetainedDuringObservation\":true,\"handleClosed\":true}";}
  s+="},\"clock\":{\"startedQpc\":"+std::to_string(o.started)+",\"finishedQpc\":"+std::to_string(o.finished)+",\"deadlineQpc\":"+std::to_string(r.observer_deadline)+",\"qpcFrequency\":"+std::to_string(r.frequency)+"},\"allDirectoryHandlesHeldTogether\":true,\"processGenerationRechecked\":true}";
  if(s.size()>65536)throw Failure{30};
  return s;
}
#ifdef _WIN32
Result observe_windows(Request const& request) noexcept;
#endif
} // namespace packaged_context
