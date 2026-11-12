// Windows SDK compile candidate only. No executable entry point or launcher.
// No explicit create/write/servicing calls. OS getter initialization effects
// (including LocalFolder initialization) remain unknown, never side-effect-free.
#ifndef _WIN32
#error This port requires the existing Windows SDK; do not install an implicit substitute.
#endif
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <appmodel.h>
#include <sddl.h>
#include <shlobj.h>
#include <knownfolders.h>
#include <winrt/base.h>
#include <winrt/Windows.Storage.h>
#include <map>
#include <memory>
#include "context_observer.hpp"
#pragma comment(lib,"windowsapp.lib")
#pragma comment(lib,"shell32.lib")
#pragma comment(lib,"ole32.lib")
#pragma comment(lib,"advapi32.lib")
#pragma comment(lib,"uuid.lib")
namespace packaged_context {
namespace {
static_assert(sizeof(void*)==8,"Only native x64/ARM64 observers are supported");
class Handle {
  HANDLE value_=nullptr;
 public:
  explicit Handle(HANDLE value):value_(value){if(!value||value==INVALID_HANDLE_VALUE)throw Failure{7};}
  Handle(Handle const&)=delete;Handle&operator=(Handle const&)=delete;
  Handle(Handle&& other)noexcept:value_(other.release()){}
  ~Handle(){if(value_)::CloseHandle(value_);}
  HANDLE get()const noexcept{return value_;}
  HANDLE release()noexcept{auto value=value_;value_=nullptr;return value;}
  void close(){auto value=release();if(value&&!::CloseHandle(value))throw Failure{11};}
};
std::wstring final_dos_path(HANDLE handle) {
  std::array<wchar_t,1029> buffer{};
  auto count=::GetFinalPathNameByHandleW(handle,buffer.data(),static_cast<DWORD>(buffer.size()),FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
  if(!count||count>=buffer.size())throw Failure{8};
  std::wstring value(buffer.data(),count);
  if(value.rfind(L"\\\\?\\",0)==0&&value.size()>=7&&value[5]==L':'&&value[6]==L'\\')value.erase(0,4);
  if(!path(value))throw Failure{8};return value;
}
template<class Check>
class Apartment {
  Check& check_;
  bool active_=false;
 public:
  explicit Apartment(Check& check):check_(check) {
    check_();
    try {
      winrt::init_apartment(winrt::apartment_type::multi_threaded);active_=true;
      check_();
    } catch(...) {
      if(active_){active_=false;winrt::uninit_apartment();}
      throw;
    }
  }
  Apartment(Apartment const&)=delete;Apartment&operator=(Apartment const&)=delete;
  ~Apartment(){if(active_)winrt::uninit_apartment();}
  void close(){if(active_){active_=false;winrt::uninit_apartment();}check_();}
};
class WindowsPort {
  std::map<std::uint64_t,HANDLE> handles_;
  std::uint64_t deadline_;
  void check(){if(now()>=deadline_)throw Failure{10};}
  Handle open_raw(std::wstring const& value) {
    check();
    auto handle=Handle(::CreateFileW(value.c_str(),FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
    check();return handle;
  }
  void attributes(HANDLE handle) {
    FILE_ATTRIBUTE_TAG_INFO info{};check();
    if(!::GetFileInformationByHandleEx(handle,FileAttributeTagInfo,&info,static_cast<DWORD>(sizeof(info)))||
       !(info.FileAttributes&FILE_ATTRIBUTE_DIRECTORY)||(info.FileAttributes&FILE_ATTRIBUTE_REPARSE_POINT)||
       ::GetFileType(handle)!=FILE_TYPE_DISK)throw Failure{8};check();
  }
  void components(std::wstring const& value) {
    if(!path(value)||::GetDriveTypeW(value.substr(0,3).c_str())!=DRIVE_FIXED)throw Failure{8};
    auto root=open_raw(value.substr(0,3));attributes(root.get());root.close();
    for(std::size_t end=3;end<value.size();) {
      end=value.find(L'\\',end);if(end==std::wstring::npos)end=value.size();
      auto part=open_raw(value.substr(0,end));attributes(part.get());part.close();
      if(end==value.size())break;++end;
    }
  }
 public:
  bool simulation_only=false;
  explicit WindowsPort(std::uint64_t deadline):deadline_(deadline) {}
  ~WindowsPort(){for(auto const&entry:handles_)::CloseHandle(entry.second);}
  std::uint64_t now(){LARGE_INTEGER value{};if(!::QueryPerformanceCounter(&value)||value.QuadPart<=0)throw Failure{10};return static_cast<std::uint64_t>(value.QuadPart);}
  std::uint64_t frequency(){LARGE_INTEGER value{};if(!::QueryPerformanceFrequency(&value)||value.QuadPart<=0)throw Failure{10};return static_cast<std::uint64_t>(value.QuadPart);}
  Process process() {
    check();Process result;std::array<wchar_t,257> buffer{};UINT32 length=static_cast<UINT32>(buffer.size());
    if(::GetCurrentPackageFullName(&length,buffer.data())!=ERROR_SUCCESS||!length||length>buffer.size())throw Failure{3};
    result.full_name=buffer.data();buffer.fill(0);length=static_cast<UINT32>(buffer.size());
    if(::GetCurrentPackageFamilyName(&length,buffer.data())!=ERROR_SUCCESS||!length||length>buffer.size())throw Failure{3};
    result.family_name=buffer.data();HANDLE raw_token=nullptr;
    if(!::OpenProcessToken(::GetCurrentProcess(),TOKEN_QUERY,&raw_token))throw Failure{3};Handle token(raw_token);
    alignas(TOKEN_USER) std::array<std::uint8_t,4096> user{};DWORD needed=0;
    if(!::GetTokenInformation(token.get(),TokenUser,user.data(),static_cast<DWORD>(user.size()),&needed)||!needed||needed>user.size())throw Failure{3};
    LPWSTR sid=nullptr;if(!::ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid,&sid))throw Failure{3};
    auto release_sid=[](wchar_t* value)noexcept{if(value)::LocalFree(reinterpret_cast<HLOCAL>(value));};
    std::unique_ptr<wchar_t,decltype(release_sid)> owned_sid(sid,release_sid);result.sid=sid;token.close();
    FILETIME created{},exit{},kernel{},user_time{};
    if(!::GetProcessTimes(::GetCurrentProcess(),&created,&exit,&kernel,&user_time))throw Failure{3};
    result.pid=::GetCurrentProcessId();result.creation=(static_cast<std::uint64_t>(created.dwHighDateTime)<<32)|created.dwLowDateTime;
    USHORT process_machine=0,native_machine=0;
    if(!::IsWow64Process2(::GetCurrentProcess(),&process_machine,&native_machine))throw Failure{3};
    result.process_machine=process_machine;result.native_machine=native_machine;check();return result;
  }
  std::wstring known_folder(bool roaming) {
    check();PWSTR raw=nullptr;HRESULT hr=::SHGetKnownFolderPath(roaming?FOLDERID_RoamingAppData:FOLDERID_LocalAppData,0,nullptr,&raw);
    std::unique_ptr<wchar_t,decltype(&::CoTaskMemFree)> owned(raw,::CoTaskMemFree);
    if(FAILED(hr)||!raw)throw Failure{5};std::wstring value(raw);if(!path(value))throw Failure{5};check();return value;
  }
  std::wstring local_folder() {
    check();auto bound=[this](){check();};
    try{Apartment<decltype(bound)> apartment(bound);
      auto value=winrt::Windows::Storage::ApplicationData::Current().LocalFolder().Path();
      std::wstring result(value.c_str(),value.size());if(!path(result))throw Failure{6};
      check();apartment.close();return result;
    }catch(Failure const&){throw;}catch(...){throw Failure{6};}
  }
  std::uint64_t open_existing(std::wstring const& value,std::uint32_t access,std::uint32_t share,std::uint32_t disposition) {
    if(access!=FILE_READ_ATTRIBUTES||share!=(FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE)||disposition!=OPEN_EXISTING)throw Failure{2};
    components(value);auto handle=open_raw(value);attributes(handle.get());components(value);
    auto key=static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(handle.get()));
    if(handles_.find(key)!=handles_.end())throw Failure{7};handles_.emplace(key,handle.get());handle.release();return key;
  }
  Directory directory(std::uint64_t key) {
    auto found=handles_.find(key);if(found==handles_.end())throw Failure{7};auto handle=found->second;attributes(handle);Directory value;
    FILE_ID_INFO id{};FILE_BASIC_INFO basic{};
    if(!::GetFileInformationByHandleEx(handle,FileIdInfo,&id,static_cast<DWORD>(sizeof(id)))||
       !::GetFileInformationByHandleEx(handle,FileBasicInfo,&basic,static_cast<DWORD>(sizeof(basic)))||basic.CreationTime.QuadPart<=0)throw Failure{8};
    value.final_path=final_dos_path(handle);value.volume=id.VolumeSerialNumber;
    std::copy(std::begin(id.FileId.Identifier),std::end(id.FileId.Identifier),value.file_id.begin());
    value.creation=static_cast<std::uint64_t>(basic.CreationTime.QuadPart);value.reparse=false;check();return value;
  }
  bool close(std::uint64_t key) {
    auto found=handles_.find(key);if(found==handles_.end())return false;auto value=found->second;
    handles_.erase(found);return ::CloseHandle(value)!=FALSE;
  }
};
} // namespace
Result observe_windows(Request const& request) noexcept {
  try{WindowsPort port(request.observer_deadline);return collect(request,port);}
  catch(Failure const&failure){Result out;out.simulation_only=false;out.failure_code=failure.code;return out;}
  catch(...){Result out;out.simulation_only=false;out.failure_code=31;return out;}
}
} // namespace packaged_context
