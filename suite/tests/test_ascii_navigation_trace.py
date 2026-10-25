"""Navigation trace is bounded evidence, separate from ASCII acceptance."""
import ctypes as C
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import ascii_message_protocol as p
import test_ascii_message_windows as boundary_module

class NavigationTraceTests(unittest.TestCase):
    def boundary(self):
        value=boundary_module.AsciiMessageWindowsTests();value.setUp();self.addCleanup(value.doCleanups);return value
    def test_prefix_abi_and_appended_ring(self):
        self.assertEqual(p.State.events.offset,456)
        self.assertEqual(C.sizeof(p.Event),96)
        self.assertEqual(p.State.traceVersion.offset,456+4096*96)
        self.assertEqual(p.TRACE_CAPACITY,128)
    def test_transport_enables_third_hook_only_for_diagnostics(self):
        boundary=self.boundary();boundary.dll.HookReturn=C.c_void_p(13)
        transport=boundary.m.MessageTransport(boundary.user,boundary.kernel,boundary.dll,boundary.target,123456,boundary.record,101.,boundary.clock,boundary.identity,nonce=123,diagnostic_mode=True)
        transport.start()
        self.assertEqual(transport.state.traceVersion,p.TRACE_VERSION)
        self.assertEqual(transport.state.traceEnabled,1)
    def test_reader_publication_and_scope(self):
        boundary=self.boundary();boundary.dll.HookReturn=C.c_void_p(13)
        transport=boundary.m.MessageTransport(boundary.user,boundary.kernel,boundary.dll,boundary.target,123456,boundary.record,101.,boundary.clock,boundary.identity,nonce=123,diagnostic_mode=True);transport.start()
        transport.state.traceVersion=p.TRACE_VERSION;transport.state.traceEnabled=1
        transport.state.traceCount=2
        row=transport.state.traceEvents[0]
        row.sequence=1;row.origin=1;row.message=0x100;row.vk=9
        row.pid=transport.target['pid'];row.tid=transport.target['tid'];row.hwnd=transport.target['hwnd']
        row.engineCreationTime=transport.creation
        result=transport.read_navigation_trace()
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['events']),1)
        row.pid+=1
        with self.assertRaises(AssertionError):transport.read_navigation_trace()

    def test_saturation_expiry_and_unpublished_row_remain_diagnostic(self):
        boundary=self.boundary();boundary.dll.HookReturn=C.c_void_p(13)
        transport=boundary.m.MessageTransport(boundary.user,boundary.kernel,boundary.dll,boundary.target,123456,boundary.record,101.,boundary.clock,boundary.identity,nonce=123,diagnostic_mode=True);transport.start()
        transport.state.traceCount=128;transport.state.traceOverflow=1
        trace=transport.read_navigation_trace()
        self.assertEqual(trace['status'],'overflow');self.assertEqual(trace['events'],[])
        self.assertFalse(trace['semanticHandlerProved']);self.assertEqual(transport.state.count,0)
        boundary.now=101.
        with self.assertRaises(AssertionError):transport.read_navigation_trace()

    def test_actual_native_producer_filters_generation_and_saturates(self):
        import os,shutil,subprocess,tempfile
        from native_executable_cleanup import remove_completed_image
        compiler=shutil.which('g++') or shutil.which('clang++')
        if compiler is None:self.skipTest('Portable C++ compiler unavailable; native Windows validation remains separate')
        folder=Path(__file__).resolve().parents[1]/'e2e'
        source=(folder/'ascii_message_observer.cpp').read_text()
        producer=source[source.index('void traceNavigation('):source.index('// Bounded known-plugin file origin')]
        prefix=r'''#include "ascii_message_protocol.h"
#include <cassert>
#include <cstring>
using LONG=int32_t;using UINT=uint32_t;using HWND=void*;using WPARAM=uintptr_t;using LPARAM=intptr_t;
constexpr UINT WM_KEYDOWN=0x100,WM_KEYUP=0x101,WM_SYSKEYDOWN=0x104,WM_SYSKEYUP=0x105;
constexpr UINT VK_TAB=9,VK_F2=0x71,VK_CONTROL=0x11,VK_F6=0x75,VK_END=0x23;
struct LARGE_INTEGER { int64_t QuadPart; };
OpenGeulAscii::State storage{};auto shared=&storage;bool stopped=false,valid=true;uint32_t ownerThread=99;
uint32_t GetCurrentThreadId(){return 99;}uint32_t GetCurrentProcessId(){return 88;}
LONG load(const uint32_t* p){return *p;}LONG loadSigned(const int32_t* p){return *p;}
void publish(uint32_t* p,LONG v){*p=v;}void publishSigned(int32_t* p,LONG v){*p=v;}LONG incrementSigned(int32_t* p){return ++*p;}
bool header(OpenGeulAscii::State*){return true;}bool identity(OpenGeulAscii::State*,HWND){return valid;}
HWND GetFocus(){return reinterpret_cast<HWND>(22);}HWND GetCapture(){return nullptr;}
bool QueryPerformanceCounter(LARGE_INTEGER* v){v->QuadPart=123;return true;}
bool QueryPerformanceFrequency(LARGE_INTEGER* v){v->QuadPart=1000;return true;}
uint64_t GetTickCount64(){return 3;}void* GetKeyboardLayout(int){return reinterpret_cast<void*>(0x4090409);}
'''
        main=r'''
int main(){
 shared->recording=1;shared->traceEnabled=1;shared->traceVersion=1;shared->hwnd=22;shared->engineCreationTime=555;
 auto hwnd=reinterpret_cast<HWND>(22);
 traceNavigation(hwnd,WM_KEYDOWN,65,0,1);traceNavigation(reinterpret_cast<HWND>(23),WM_KEYDOWN,VK_TAB,0,1);
 assert(shared->traceCount==0);
 for(uint32_t origin=1;origin<=3;++origin)traceNavigation(hwnd,WM_KEYDOWN,VK_TAB,0,origin);
 assert(shared->traceCount==3 && shared->traceEvents[2].sequence==3 && shared->traceEvents[2].origin==3);
 assert(shared->traceEvents[0].pid==88 && shared->traceEvents[0].tid==99 && shared->traceEvents[0].engineCreationTime==555);
 assert(shared->traceEvents[0].counter==123 && shared->traceEvents[0].frequency==1000);
 valid=false;traceNavigation(hwnd,WM_KEYDOWN,VK_F2,0,1);assert(shared->traceRejected==1 && shared->traceCount==3);valid=true;
 auto first=shared->traceEvents[0];
 for(int i=0;i<200;++i)traceNavigation(hwnd,WM_KEYUP,VK_F2,0,1);
 assert(shared->traceCount==128 && shared->traceOverflow==1 && !memcmp(&first,&shared->traceEvents[0],sizeof(first)));
 assert(shared->count==0 && shared->armedEpoch==0 && shared->status==0);
 shared->traceEnabled=0;shared->traceCount=0;traceNavigation(hwnd,WM_KEYDOWN,VK_F2,0,1);assert(shared->traceCount==0);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cpp=root/'trace.cpp';exe=root/('trace.exe' if os.name=='nt' else 'trace')
            cpp.write_text(prefix+producer+main)
            build=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)
