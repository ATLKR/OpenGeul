"""Compile the shared production stack classifier against synthetic Win32 APIs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from native_executable_cleanup import remove_completed_image

class BoundedStackTests(unittest.TestCase):
    def _compile_and_run(self, source, *, header_source=None):
        folder=Path(__file__).resolve().parents[1]/'e2e'
        self.assertTrue((folder/'bounded_stack_windows.h').is_file(),'shared bounded stack primitive missing')
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'stack.cpp';exe=root/('stack.exe' if os.name=='nt' else 'stack')
            cpp.write_text(source)
            if header_source is not None:(root/'bounded_stack_windows.h').write_text(header_source)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)

    def test_actual_classifier_redacts_unknowns_and_stops_between_native_calls(self):
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
        self._compile_and_run(source)

    def test_64_frame_classifier_preserves_bounds_expiry_and_wipes_local_addresses(self):
        source=r'''
#include <cstdint>
#include <cstddef>
#include <cwchar>
#include <cassert>
using HMODULE=void*;
constexpr unsigned GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT=2;
constexpr unsigned expectedWipes=0;
int calls=0,expire=-1;unsigned count=48,requested=0,captured=0,wiped=0;void**wipeBase=nullptr;
bool clock(){return expire<0 || calls<expire;}
unsigned CaptureStackBackTrace(unsigned skip,unsigned cap,void**out,void*){
 ++calls;++captured;requested=cap;assert(skip==0 && cap==64);
 for(unsigned i=0;i<count&&i<cap;++i)out[i]=reinterpret_cast<void*>(0x1010+16*i);
 return count;
}
HMODULE GetModuleHandleW(const wchar_t*name){++calls;return std::wcscmp(name,L"mergedlo.dll")==0?reinterpret_cast<void*>(0x1000):nullptr;}
bool GetModuleHandleExW(unsigned flags,const wchar_t*,HMODULE*out){++calls;assert(flags==6);*out=reinterpret_cast<void*>(0x1000);return true;}
// Observe the actual RAII wipe while its address array is alive. Reading the
// captured pointer after Capture returns would access expired stack storage.
struct WipeSlot{
 void**location;
 void operator=(std::nullptr_t)const{
  if(!wiped)wipeBase=location;
  assert(location==wipeBase+wiped);
  *reinterpret_cast<void* volatile*>(location)=nullptr;
  ++wiped;
  for(unsigned i=0;i<wiped;++i)assert(wipeBase[i]==nullptr);
 }
};
struct WipePointer{void**location;WipeSlot operator*()const{return {location};}};
WipePointer observed_wipe_cast(void**value){return {value};}
#include "bounded_stack_windows.h"
struct Frame{uint32_t moduleId=0,rva=0;};
struct Row64{uint32_t flags=0,frameCount=0,frameCapReached=0,unknownFrames=0;Frame frames[64]{};};
void reset(unsigned frames){calls=0;expire=-1;count=frames;requested=0;captured=0;wiped=0;wipeBase=nullptr;}
int main(){
 Row64 good;assert(opengeul_stack::Capture(good,clock,[](HMODULE){return 1u;},false));
 assert(requested==64 && captured==1 && wiped==expectedWipes);
 assert(good.frameCount==48 && good.frameCapReached==0 && good.flags==0 && good.unknownFrames==0);
 for(unsigned i=0;i<48;++i)assert(good.frames[i].moduleId==1 && good.frames[i].rva==16+16*i);
 const int total=calls;
 for(int end=0;end<=total;++end){reset(48);expire=end;Row64 row;
  assert(!opengeul_stack::Capture(row,clock,[](HMODULE){return 1u;},false));
  assert(calls==end && wiped==expectedWipes && captured==(end?1u:0u));}
 reset(64);Row64 capped;assert(opengeul_stack::Capture(capped,clock,[](HMODULE){return 1u;},false));
 assert(capped.frameCount==64 && capped.frameCapReached==1 && capped.flags==0 && wiped==expectedWipes && captured==1);
 assert(capped.frames[63].moduleId==1 && capped.frames[63].rva==1024);
 reset(65);Row64 invalid;assert(!opengeul_stack::Capture(invalid,clock,[](HMODULE){return 1u;},false));
 assert(invalid.flags==16 && invalid.frameCount==0 && invalid.frameCapReached==0 && calls==1 && wiped==expectedWipes && captured==1);
 reset(0);Row64 empty;assert(opengeul_stack::Capture(empty,clock,[](HMODULE){return 1u;},false));
 assert(empty.frameCount==0 && empty.frameCapReached==0 && empty.flags==2 && wiped==expectedWipes && captured==1);
}
'''
        self._compile_and_run(source)
        # First run the original header. Then observe cleanup through a temporary
        # copy with only the volatile-pointer cast replaced by a live-array spy.
        header=(Path(__file__).resolve().parents[1]/'e2e/bounded_stack_windows.h').read_text()
        cast='reinterpret_cast<void* volatile*>'
        self.assertEqual(header.count(cast),1)
        self._compile_and_run(source.replace('expectedWipes=0','expectedWipes=64'),
                              header_source=header.replace(cast,'observed_wipe_cast'))

    def test_classifier_rejects_row_capacities_other_than_16_or_64(self):
        folder=Path(__file__).resolve().parents[1]/'e2e'
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=r'''
#include <cstdint>
using HMODULE=void*;
constexpr unsigned GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT=2;
unsigned CaptureStackBackTrace(unsigned,unsigned,void**,void*){return 0;}
HMODULE GetModuleHandleW(const wchar_t*){return nullptr;}
bool GetModuleHandleExW(unsigned,const wchar_t*,HMODULE*){return false;}
#include "bounded_stack_windows.h"
struct Frame{uint32_t moduleId=0,rva=0;};
struct Row{uint32_t flags=0,frameCount=0,frameCapReached=0,unknownFrames=0;Frame frames[CAPACITY]{};};
int main(){Row row;return opengeul_stack::Capture(row,[]{return true;},[](HMODULE){return 1u;},false);}
'''
        with tempfile.TemporaryDirectory() as d:
            cpp=Path(d)/'capacity.cpp'
            for capacity in (1,8,17,32,65):
                with self.subTest(capacity=capacity):
                    cpp.write_text(source.replace('CAPACITY',str(capacity)))
                    built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsyntax-only','-I',str(folder),str(cpp)],capture_output=True,text=True,timeout=30)
                    self.assertNotEqual(built.returncode,0,'Unsupported row capacity compiled')
                    self.assertIn('static assertion',built.stderr)
