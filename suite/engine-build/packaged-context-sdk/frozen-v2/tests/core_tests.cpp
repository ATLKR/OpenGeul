#include "context_observer.hpp"
#include <map>
#include <iostream>
#ifndef CORE_REQUEST_SHA
#define CORE_REQUEST_SHA std::string(64,'1')
#endif
#ifndef CORE_BUNDLE_SHA
#define CORE_BUNDLE_SHA std::string(64,'2')
#endif
#include <stdexcept>
#include <string>
using namespace packaged_context;
struct FakePort {
  bool simulation_only=true; std::uint64_t tick=100, frequency_value=1000; int mode=0, opens=0, closes=0, max_live=0, initializations=0; bool mutation_called=false;
  std::map<std::uint64_t,std::wstring> handles;
  std::uint64_t now(){return tick++;} std::uint64_t frequency(){return frequency_value;}
  Process process(){ Process p{L"org.allenlabs.OpenGeul_1.2.3.4_x64__abcdefghijklm",L"org.allenlabs.OpenGeul_abcdefghijklm",L"S-1-5-21-100",45,1000,0x8664,0};if(mode==1)p.full_name=L"foreign";if(mode==2)p.process_machine=0x14c;if(mode==9&&opens>0)p.creation++;return p; }
  std::wstring known_folder(bool roaming){return roaming?L"C:\\owned\\Roaming":L"C:\\owned\\Local";}
  std::wstring local_folder(){++initializations;return mode==3?L"":L"C:\\owned\\LocalState";}
  std::uint64_t open_existing(std::wstring const& path,std::uint32_t access,std::uint32_t share,std::uint32_t disposition){
    if(access!=128||share!=7||disposition!=3){mutation_called=true;throw Failure{20};}
    if(mode==4&&opens==1)throw Failure{7};
    if(mode==10)tick=10100;
    auto h=++opens;handles[h]=path;max_live=std::max(max_live,int(handles.size()));return h;
  }
  Directory directory(std::uint64_t h){auto path=handles.at(h);Directory d;d.final_path=path;d.volume=1;d.creation=500;d.file_id[0]=path.find(L"LocalState")!=std::wstring::npos?3:path.find(L"Roaming")!=std::wstring::npos?2:1;
    if(mode==5)d.reparse=true;
    if(mode==6)d.file_id[0]=1;
    if(mode==7)d.final_path=L"";
    if(mode==8&&opens>3)d.creation++;
    if(mode==12)d.file_id.fill(0);
    if(mode==19)d.final_path.push_back(static_cast<wchar_t>(0xd800));
    if(mode==22)d.final_path+=L"\\COM\u00b9";
    if(mode==23)d.final_path.push_back(static_cast<wchar_t>(127));
    return d;}
  bool close(std::uint64_t h){++closes;handles.erase(h);return mode!=11;}
};
Request request(){Request r;r.expected={L"org.allenlabs.OpenGeul_1.2.3.4_x64__abcdefghijklm",L"org.allenlabs.OpenGeul_abcdefghijklm",L"S-1-5-21-100",0,0,0x8664,0};r.product_local=L"C:\\owned\\Local\\org.allenlabs.opengeul";r.product_roaming=L"C:\\owned\\Roaming\\org.allenlabs.opengeul";r.start_qpc=100;r.phase_deadline=90100;r.observer_deadline=10100;r.frequency=1000;r.request_sha256=CORE_REQUEST_SHA;r.bundle_sha256=CORE_BUNDLE_SHA;return r;}
int main(int argc,char**argv){if(argc!=2)return 99;int c=std::stoi(argv[1]);FakePort port;auto req=request();bool expect=true;
  if((c>=1&&c<=12)||c==19||c==22||c==23){port.mode=c;expect=false;}else if(c==13){req.product_local=L"C:\\other\\org.allenlabs.opengeul";expect=false;}else if(c==14){req.product_local=L"C:\\owned\\Local\\..\\secret";expect=false;}else if(c==15){req.observer_deadline=10101;expect=false;}else if(c==16){port.frequency_value=1001;expect=false;}else if(c==17){req.request_sha256="";expect=false;}else if(c==18){req.product_roaming=L"C:\\owned\\Roaming\\CON";expect=false;}else if(c==20){}else if(c==21){req.start_qpc=0;req.phase_deadline=90000;req.observer_deadline=10000;expect=false;}else if(c==24){port.tick=10100;expect=false;}else if(c==30){}else if(c!=0)return 98;
  if(c==20){Result invalid;invalid.complete=true;try{(void)to_json(invalid,req);}catch(Failure const&){return 0;}return 1;}
  auto result=collect(req,port);
  if((c==1||c==2||c==13||c==14||c==15||c==16||c==17||c==18||c==21||c==24)&&port.initializations!=0)return 5;
  if(result.complete!=expect||port.mutation_called||!port.handles.empty())return 1;
  if(expect){if(result.failure_code||port.max_live<3||!result.all_handles_together||!result.generation_rechecked||!result.cleanup_proved||result.directories.size()!=3)return 2;auto json=to_json(result,req);if(json.find("\"actualWindowsExecuted\":false")==std::string::npos||json.find("\"canService\":false")==std::string::npos||json.find("\"logicalPath\"")==std::string::npos)return 3;}
  else if(!result.failure_code)return 4;
  if(c==30)std::cout<<to_json(result,req);
  return 0;}
