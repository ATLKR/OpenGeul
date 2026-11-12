#include "sdk_smoke.hpp"
struct NoGetters {
  bool simulation_only=false;int forbidden=0;
  std::uint64_t now(){return 100000;}std::uint64_t frequency(){return 1000;}
  packaged_context::Process process(){++forbidden;throw packaged_context::Failure{31};}
  std::wstring known_folder(bool){++forbidden;throw packaged_context::Failure{31};}
  std::wstring local_folder(){++forbidden;throw packaged_context::Failure{31};}
  std::uint64_t open_existing(std::wstring const&,std::uint32_t,std::uint32_t,std::uint32_t){++forbidden;throw packaged_context::Failure{31};}
  packaged_context::Directory directory(std::uint64_t){++forbidden;throw packaged_context::Failure{31};}
  bool close(std::uint64_t){++forbidden;return false;}
};
int main(){
  auto clock=[](){return sdk_gate::Clock{100000,1000};};
  for(auto machine:{0x8664,0xaa64}) {
    NoGetters port;int calls=0;
    auto observe=[&](packaged_context::Request const&r){++calls;return packaged_context::collect(r,port);};
    if(sdk_gate::run(observe,clock,static_cast<std::uint16_t>(machine))||calls!=2||port.forbidden)return 1;
  }
  for(int mode=0;mode<7;++mode){
    NoGetters port;
    auto forged=[&](packaged_context::Request const&r){auto v=packaged_context::collect(r,port);
      if(mode==0)v.complete=true;
      if(mode==1)v.simulation_only=true;
      if(mode==2)v.process.pid=1;
      if(mode==3)v.local_known=L"foreign";
      if(mode==4)v.failure_code=0;
      if(mode==5)v.cleanup_proved=false;
      if(mode==6)v.directories.push_back({});
      return v;};
    if(sdk_gate::run(forged,clock,0x8664)==0||port.forbidden)return 2;
  }
  int calls=0;auto never=[&](packaged_context::Request const&){++calls;return packaged_context::Result{};};
  if(sdk_gate::run(never,[](){return sdk_gate::Clock{0,0};},0x8664)==0||calls)return 3;
  if(sdk_gate::run(never,clock,0x14c)==0||calls)return 4;
  return 0;
}
