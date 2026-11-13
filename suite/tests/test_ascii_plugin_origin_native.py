"""Compile the actual bounded native origin checker with synthetic file APIs."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from native_executable_cleanup import remove_completed_image

class NativePluginOriginTests(unittest.TestCase):
    def test_admission_accepts_only_fixed_private_binding_and_empty_sidecars(self):
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        folder=Path(__file__).resolve().parents[1]/'e2e'
        source=(folder/'ascii_message_observer.cpp').read_text()
        self.assertIn('bool pluginAdmission(',source)
        code=source[source.index('bool pluginAdmission('):source.index('void start(')]
        program=r'#include "ascii_message_protocol.h"' + '\n#include <cassert>\n#include <cstring>\nusing OpenGeulAscii::State;\n' + code + r"""
int main(){State state{};auto&b=state.pluginBinding;
 assert(!pluginAdmission(&state));b.version=1;assert(pluginAdmission(&state));
 b.size=1;assert(!pluginAdmission(&state));b.size=0;
 b.enabled=1;b.size=1536;b.volume=7;b.fileId[0]=1;
 const char*path="C:\\owned\\vclplug_winlo.dll";b.pathLength=static_cast<uint32_t>(std::strlen(path));
 for(uint32_t i=0;i<b.pathLength;++i)b.path[i]=path[i];
 assert(!pluginAdmission(&state));state.captureEnabled=1;assert(pluginAdmission(&state));
 auto good=state;
 state.pluginOrigins[2].counter=1;assert(!pluginAdmission(&state));state=good;
 b.path[0]='\\';assert(!pluginAdmission(&state));state=good;
 b.path[3]=0;assert(!pluginAdmission(&state));state=good;
 b.path[b.pathLength+1]=1;assert(!pluginAdmission(&state));state=good;
 b.path[b.pathLength-1]='x';assert(!pluginAdmission(&state));state=good;
 b.fileId[0]=0;assert(!pluginAdmission(&state));state=good;
 b.enabled=2;assert(!pluginAdmission(&state));state=good;
 b.reserved=1;assert(!pluginAdmission(&state));state=good;
 b.size=32u*1024u*1024u+1;assert(!pluginAdmission(&state));
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cpp=root/'admission.cpp';exe=root/('admission.exe' if os.name=='nt' else 'admission')
            cpp.write_text(program)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)

    def test_actual_checker_rejects_wrong_origin_and_stops_after_expiry(self):
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        folder=Path(__file__).resolve().parents[1]/'e2e'
        source=(folder/'ascii_message_observer.cpp').read_text()
        self.assertTrue('// Bounded known-plugin file origin' in source,'native file-origin checker absent')
        code=source[source.index('// Bounded known-plugin file origin'):source.index('// Bounded retrieval metadata')]
        prefix=r'''
#include "ascii_message_protocol.h"
#include <cassert>
#include <cstring>
#include <cwchar>
#include <vector>
using DWORD=uint32_t;using HANDLE=void*;using HMODULE=void*;using BOOL=int;
constexpr uint32_t GENERIC_READ=0x80000000,FILE_SHARE_READ=1,OPEN_EXISTING=3,FILE_ATTRIBUTE_NORMAL=0x80;
const HANDLE INVALID_HANDLE_VALUE=reinterpret_cast<void*>(~uintptr_t(0));
enum FILE_INFO_BY_HANDLE_CLASS{FileIdInfo=18};
struct FILE_ID_INFO{uint64_t VolumeSerialNumber;struct{uint8_t Identifier[16];}FileId;};
struct LARGE_INTEGER{int64_t QuadPart;};
OpenGeulAscii::State storage{};auto shared=&storage;
OpenGeulAscii::PluginBinding pluginBindingSnapshot{};
uint64_t ticks=10;int calls=0,expireAt=0,mode=0,opens=0,closes=0,names=0;bool expired=false;
std::vector<int> history;
bool retrievalClock(uint64_t&value){if(ticks>=100){expired=true;return false;}value=ticks;return true;}
void touch(int kind){history.push_back(kind);if(++calls==expireAt)ticks=100;}
const wchar_t* expected=L"C:\\owned\\vclplug_winlo.dll";
DWORD GetModuleFileNameW(HMODULE module,wchar_t*out,DWORD cap){assert(module==reinterpret_cast<void*>(0x1000));++names;
 const auto*name=(mode==1 || (mode==5&&names==2))?L"C:\\other\\vclplug_winlo.dll":expected;
 auto n=std::wcslen(name);assert(n+1<cap);std::wmemcpy(out,name,n+1);touch(1);return static_cast<DWORD>(n);}
HANDLE CreateFileW(const wchar_t*path,DWORD access,DWORD share,void*,DWORD disposition,DWORD flags,void*){
 assert(std::wcscmp(path,expected)==0 && access==GENERIC_READ && share==1 && disposition==3 && flags==0x80);
 ++opens;touch(2);return reinterpret_cast<void*>(0x123);}
BOOL GetFileInformationByHandleEx(HANDLE handle,FILE_INFO_BY_HANDLE_CLASS kind,void*out,DWORD size){
 assert(handle==reinterpret_cast<void*>(0x123) && kind==FileIdInfo && size==24);auto*p=static_cast<FILE_ID_INFO*>(out);
 p->VolumeSerialNumber=7;for(int i=0;i<16;++i)p->FileId.Identifier[i]=static_cast<uint8_t>(i);
 if(mode==2){p->FileId.Identifier[0]=99;}touch(3);return 1;}
BOOL GetFileSizeEx(HANDLE handle,LARGE_INTEGER*out){assert(handle==reinterpret_cast<void*>(0x123));out->QuadPart=mode==3?1537:1536;touch(4);return 1;}
BOOL CloseHandle(HANDLE handle){assert(handle==reinterpret_cast<void*>(0x123));++closes;touch(5);return mode!=6;}
HMODULE GetModuleHandleW(const wchar_t*name){assert(std::wcscmp(name,L"vclplug_winlo.dll")==0);touch(6);return reinterpret_cast<void*>(mode==4?0x2000:0x1000);}
void reset(){storage={};ticks=10;calls=expireAt=mode=opens=closes=names=0;expired=false;history.clear();
 auto&b=shared->pluginBinding;b.version=1;b.enabled=1;b.volume=7;b.size=1536;b.pathLength=static_cast<uint32_t>(std::wcslen(expected));
 for(uint32_t i=0;i<b.pathLength;++i)b.path[i]=static_cast<uint16_t>(expected[i]);
 for(int i=0;i<16;++i){b.fileId[i]=static_cast<uint8_t>(i);}pluginBindingSnapshot=b;}
'''
        main=r'''
int main(){auto module=reinterpret_cast<void*>(0x1000);
 reset();assert(pluginOriginStatus(module)==1 && opens==1 && closes==1 && names==2);
 reset();shared->pluginBinding.enabled=0;pluginBindingSnapshot=shared->pluginBinding;assert(pluginOriginStatus(module)==2 && calls==0);
 reset();shared->pluginBinding.size++;assert(pluginOriginStatus(module)==2 && calls==0);
 reset();assert(pluginOriginStatus(nullptr)==2 && calls==0);
 for(int bad=1;bad<=6;++bad){reset();mode=bad;auto result=pluginOriginStatus(module);assert(result!=1);
  if(bad==1)assert(opens==0);else assert(opens==1 && closes==1);}
 for(int point=1;point<=7;++point){reset();expireAt=point;assert(pluginOriginStatus(module)==0 && expired);
  if(opens)assert(closes==1);else assert(closes==0);
  assert(calls==point || (calls==point+1 && history.back()==5));}
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cpp=root/'origin.cpp';exe=root/('origin.exe' if os.name=='nt' else 'origin')
            cpp.write_text(prefix+'\n#include \"bounded_plugin_origin_windows.h\"\n'+code+main)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)

if __name__=='__main__':unittest.main()
