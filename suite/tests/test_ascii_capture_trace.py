"""Capture evidence stays separate, bounded and readable locally after failure."""
import ctypes as C
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import ascii_message_protocol as p
import test_ascii_message_windows as boundary_module

class CaptureTraceTests(unittest.TestCase):
    def transport(self):
        b=boundary_module.AsciiMessageWindowsTests();b.setUp();self.addCleanup(b.doCleanups)
        b.dll.HookReturn=C.c_void_p(13)
        t=b.m.MessageTransport(b.user,b.kernel,b.dll,b.target,123456,b.record,101.,b.clock,b.identity,
            nonce=123,capture_diagnostic_mode=True,capture_deadline_counter=1000,capture_counter_frequency=100)
        t.start();return b,t
    def test_append_only_abi_and_pinned_messages(self):
        self.assertEqual(p.State.captureVersion.offset,407008)
        self.assertEqual(p.State.events.offset,456);self.assertEqual(p.State.traceVersion.offset,393672)
        self.assertEqual(p.SAL_CAPTURE_MOUSE,0x48c);self.assertEqual(p.SAL_RELEASE_MOUSE,0x48d)
    def test_local_failure_copy_preserves_committed_rows_without_target_queries(self):
        b,t=self.transport();s=t.state;s.captureCount=2
        r=s.captureEvents[0];r.sequence=1;r.origin=1;r.removeFlags=1;r.message=0x201;r.pid=t.target['pid'];r.tid=t.target['tid']
        r.hwnd=t.target['hwnd'];r.engineCreationTime=t.creation;r.counter=100;r.finishedCounter=101;r.frequency=100
        b.now=102.;b.identity_ok=False;calls=list(b.calls)
        result=t.read_capture_trace(local_only=True)
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['events']),1)
        self.assertFalse(result['freshTargetIdentityVerified']);self.assertFalse(result['handlerCompletionProved'])
        self.assertTrue(all(isinstance(call,tuple) and call[0]=='acquire' for call in b.calls[len(calls):]))
        with self.assertRaises(AssertionError):t.read_capture_trace()
    def test_rejection_expiry_and_overflow_remain_explicit(self):
        b,t=self.transport();t.state.captureExpired=1;t.state.captureRejected=2;t.state.captureOverflow=1
        result=t.read_capture_trace(local_only=True)
        self.assertEqual(result['status'],'rejected');self.assertEqual(result['rejected'],2)
        self.assertTrue(result['expired']);self.assertTrue(result['overflow'])
    def test_postdeadline_row_and_budget_mutation_rejected(self):
        b,t=self.transport();s=t.state;s.captureCount=1;r=s.captureEvents[0]
        r.sequence=1;r.origin=1;r.removeFlags=1;r.message=0x202;r.pid=t.target['pid'];r.tid=t.target['tid'];r.hwnd=t.target['hwnd'];r.engineCreationTime=t.creation
        r.counter=1000;r.finishedCounter=1000;r.frequency=100
        with self.assertRaises(AssertionError):t.read_capture_trace(local_only=True)
        s.captureDeadline=1001
        with self.assertRaises(AssertionError):t.read_capture_trace(local_only=True)

    def test_actual_native_capture_producer_is_bounded_and_passive(self):
        import os,shutil,subprocess,tempfile
        from native_executable_cleanup import remove_completed_image
        compiler=shutil.which('g++') or shutil.which('clang++')
        if compiler is None:self.skipTest('Portable compiler unavailable; actual native Windows execution remains separate')
        folder=Path(__file__).resolve().parents[1]/'e2e'
        source=(folder/'ascii_message_observer.cpp').read_text()
        producer=source[source.index('static bool captureReading='):source.index('// Separate navigation diagnostics;')]
        prefix=r'''
#include "ascii_message_protocol.h"
#include <cassert>
#include <cstring>
using LONG=int32_t;using UINT=uint32_t;using HWND=void*;using WPARAM=uintptr_t;using LPARAM=intptr_t;
constexpr UINT WM_CAPTURECHANGED=0x215,WM_SETFOCUS=7,WM_KILLFOCUS=8;
struct LARGE_INTEGER {int64_t QuadPart;};
OpenGeulAscii::State storage{};auto shared=&storage;bool stopped=false,valid=true,expireFocus=false,reenter=false;
uint32_t ownerThread=99;volatile LONG active=1;uint64_t ticks=10;bool clockOk=true,frequencyOk=true;int focuses=0,captures=0,identities=0;
uint32_t GetCurrentThreadId(){return 99;}uint32_t GetCurrentProcessId(){return 88;}
LONG load(const uint32_t* p){return *p;}LONG loadSigned(const int32_t* p){return *p;}
void publish(uint32_t* p,LONG v){*p=v;}void publishSigned(int32_t* p,LONG v){*p=v;}LONG incrementSigned(int32_t* p){return ++*p;}
LONG InterlockedCompareExchange(volatile LONG* p,LONG v,LONG c){auto r=*p;if(r==c)*p=v;return r;}
bool header(OpenGeulAscii::State*){return true;}bool identity(OpenGeulAscii::State*,HWND){++identities;return valid;}
void traceCapture(HWND,UINT,WPARAM,LPARAM,uint32_t,WPARAM);
HWND GetFocus(){++focuses;if(expireFocus)ticks=100;if(reenter)traceCapture(reinterpret_cast<HWND>(22),0x201,0,0,1,1);return reinterpret_cast<HWND>(22);}
HWND GetCapture(){++captures;return reinterpret_cast<HWND>(22);}
bool QueryPerformanceCounter(LARGE_INTEGER* v){v->QuadPart=ticks;return clockOk;}
bool QueryPerformanceFrequency(LARGE_INTEGER* v){v->QuadPart=frequencyOk?1000:999;return true;}
uint64_t GetTickCount64(){return 3;}
'''
        hook=source[source.index('extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet('):source.index('extern "C" __declspec(dllexport) LRESULT CALLBACK HookReturn(')]
        hook_prefix=r'''
#define __declspec(x)
#define CALLBACK
using LRESULT=intptr_t;
constexpr int HC_ACTION=0;constexpr WPARAM PM_REMOVE=1;
struct MSG {HWND hwnd;UINT message;WPARAM wParam;LPARAM lParam;};
struct Callback {~Callback(){}};
int navigationCalls=0,observeCalls=0;
void traceNavigation(HWND,UINT,WPARAM,LPARAM,uint32_t){++navigationCalls;}
void observe(const MSG&,WPARAM){++observeCalls;}
LRESULT CallNextHookEx(void*,int,WPARAM,LPARAM){return 0;}
'''
        checks='static_assert(sizeof(OpenGeulAscii::State)=='+str(C.sizeof(p.State))+');\n'
        checks+='\n'.join('static_assert(offsetof(OpenGeulAscii::State,'+name+')=='+str(getattr(p.State,name).offset)+');' for name,_ in p.State._fields_)
        main=r'''
int main(){
 shared->recording=1;shared->captureVersion=1;shared->hwnd=22;shared->engineCreationTime=555;
 shared->captureDeadline=100;shared->captureFrequency=1000;auto hwnd=reinterpret_cast<HWND>(22);
 traceCapture(hwnd,0x201,1,2,1,1);assert(identities==0 && focuses==0 && shared->captureCount==0);
 shared->captureEnabled=1;
 traceCapture(hwnd,0x200,0,0,1,1);traceCapture(reinterpret_cast<HWND>(23),0x201,0,0,1,1);assert(shared->captureCount==0);
 for(uint32_t origin=1;origin<=3;++origin)traceCapture(hwnd,OpenGeulAscii::SalCaptureMouse,0,0,origin,origin==1?1:0);
 assert(shared->captureCount==3 && shared->captureEvents[2].origin==3 && shared->captureEvents[2].sequence==3);
 assert(shared->captureEvents[0].captureHwnd==22 && shared->captureEvents[0].engineCreationTime==555);
 auto first=shared->captureEvents[0];for(int i=0;i<200;++i)traceCapture(hwnd,0x202,0,0,1,1);
 assert(shared->captureCount==128 && shared->captureOverflow==1 && !memcmp(&first,&shared->captureEvents[0],sizeof(first)));
 shared->captureCount=0;valid=false;traceCapture(hwnd,0x201,0,0,1,1);assert(shared->captureRejected==1 && shared->captureCount==0);valid=true;
 int priorFocus=focuses,priorCapture=captures,priorIdentity=identities;ticks=100;traceCapture(hwnd,0x201,0,0,1,1);
 assert(shared->captureExpired==1 && focuses==priorFocus && captures==priorCapture && identities==priorIdentity);
 ticks=10;expireFocus=true;traceCapture(hwnd,0x201,0,0,1,1);assert(captures==priorCapture && shared->captureCount==0);expireFocus=false;
 ticks=10;reenter=true;traceCapture(hwnd,0x201,0,0,1,1);assert(shared->captureRejected==3 && shared->captureCount==1);
 assert(shared->count==0 && shared->traceCount==0 && shared->status==0 && shared->armedEpoch==0);
 reenter=false;shared->captureRejected=0;shared->captureExpired=0;clockOk=false;traceCapture(hwnd,0x201,0,0,1,1);
 assert(shared->captureRejected==4 && shared->captureExpired==0);clockOk=true;frequencyOk=false;shared->captureRejected=0;
 traceCapture(hwnd,0x201,0,0,1,1);assert(shared->captureRejected==4 && shared->captureExpired==0);
 frequencyOk=true;shared->captureCount=0;shared->captureRejected=0;shared->captureOverflow=0;
 MSG msg{hwnd,0x202,0,0};
 HookGet(HC_ACTION,0,reinterpret_cast<LPARAM>(&msg));HookGet(HC_ACTION,2,reinterpret_cast<LPARAM>(&msg));
 assert(shared->captureCount==0 && navigationCalls==0);
 HookGet(HC_ACTION,1,reinterpret_cast<LPARAM>(&msg));HookGet(HC_ACTION,3,reinterpret_cast<LPARAM>(&msg));
 assert(shared->captureCount==2 && shared->captureEvents[0].removeFlags==1 && shared->captureEvents[1].removeFlags==3);
 assert(navigationCalls==1 && observeCalls==4);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cpp=root/'capture.cpp';exe=root/('capture.exe' if os.name=='nt' else 'capture')
            cpp.write_text(prefix+checks+producer+hook_prefix+hook+main)
            build=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)
