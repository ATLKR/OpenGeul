"""Compile the shared production stack classifier against synthetic Win32 APIs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from native_executable_cleanup import remove_completed_image

class BoundedStackTests(unittest.TestCase):
    def test_actual_classifier_redacts_unknowns_and_stops_between_native_calls(self):
        folder=Path(__file__).resolve().parents[1]/'e2e'
        self.assertTrue((folder/'bounded_stack_windows.h').is_file(),'shared bounded stack primitive missing')
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=r'''
#include <cstdint>
#include <cstddef>
#include <cwchar>
#include <cassert>
using HMODULE=void*;
constexpr unsigned GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT=2;
int calls=0,expire=0,captured=0;bool unstable=false;unsigned count=2;
bool clock(){return !expire || calls<expire;}
unsigned CaptureStackBackTrace(unsigned,unsigned cap,void**out,void*){
 ++calls;++captured;assert(cap==16);for(unsigned i=0;i<count&&i<cap;++i)out[i]=reinterpret_cast<void*>(i?0x9009:0x1010);return count;}
HMODULE GetModuleHandleW(const wchar_t*name){++calls;return std::wcscmp(name,L"mergedlo.dll")==0?reinterpret_cast<void*>(0x1000):nullptr;}
bool GetModuleHandleExW(unsigned flags,const wchar_t*address,HMODULE*out){++calls;assert(flags==6);
 *out=reinterpret_cast<void*>(reinterpret_cast<uintptr_t>(address)==0x1010?0x1000:0x9000);
 if(unstable){*out=reinterpret_cast<void*>(0x2000);}return true;}
#include "bounded_stack_windows.h"
struct Frame{uint32_t moduleId=0,rva=0;};
struct Row{uint32_t flags=0,frameCount=0,frameCapReached=0,unknownFrames=0;Frame frames[16]{};};
int main(){
 Row good;assert(opengeul_stack::Capture(good,clock,[](HMODULE){return 1u;},false));
 assert(good.frameCount==2 && good.frames[0].moduleId==1 && good.frames[0].rva==16);
 assert(good.frames[1].moduleId==0 && good.frames[1].rva==0 && good.unknownFrames==1);
 const int total=calls;
 for(int end=1;end<=total;++end){calls=0;expire=end;Row row;
  assert(!opengeul_stack::Capture(row,clock,[](HMODULE){return 1u;},false));assert(calls==end);}
 calls=0;expire=0;unstable=true;Row changed;
 assert(opengeul_stack::Capture(changed,clock,[](HMODULE){return 1u;},false));assert(changed.frames[0].moduleId==0);
 unstable=false;count=16;Row capped;assert(opengeul_stack::Capture(capped,clock,[](HMODULE){return 1u;},false));assert(capped.frameCapReached==1);
 count=0;Row empty;assert(opengeul_stack::Capture(empty,clock,[](HMODULE){return 1u;},false));assert(empty.flags&2);
 count=17;Row invalid;assert(!opengeul_stack::Capture(invalid,clock,[](HMODULE){return 1u;},false));
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'stack.cpp';exe=root/('stack.exe' if os.name=='nt' else 'stack')
            cpp.write_text(source)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)
