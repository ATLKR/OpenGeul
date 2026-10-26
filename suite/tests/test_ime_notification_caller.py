"""The first typed closure is one diagnostic sample, never acceptance evidence."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from native_executable_cleanup import remove_completed_image

class NotificationPolicyTests(unittest.TestCase):
    def test_native_policy_requires_clean_typed_joint_closure_and_proven_open_baseline(self):
        folder=Path(__file__).resolve().parents[1]/'e2e'
        self.assertTrue((folder/'ime_notification_caller.h').is_file(),'first-close policy missing')
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        code=r'''
#include <cassert>
#include "ime_notification_caller.h"
#include "ime_compartment_protocol.h"
int main(){using namespace opengeul_ime;ModeReceipt r;
 assert(!NotificationBaseline(r));assert(!NotificationClosed(r));
 r.status=r.cleanupStatus=r.variantClearHr=0;r.releaseCalls=1;
 r.referencesAcquired=r.referencesReleased=5;
 r.beforeOpenHr=r.beforeConversionHr=r.afterOpenHr=r.afterConversionHr=0;
 r.beforeOpenType=r.beforeConversionType=r.afterOpenType=r.afterConversionType=3;
 r.afterOpen=r.afterConversion=1;
 assert(NotificationBaseline(r));assert(NotificationClosed(r));
 r.beforeOpen=1;assert(!NotificationClosed(r));r.beforeOpen=0;
 r.openSetCalls=1;assert(!NotificationClosed(r));r.openSetCalls=0;
 r.beforeOpenType=0;assert(!NotificationClosed(r));r.beforeOpenType=3;
 r.cleanupStatus=1;assert(!NotificationClosed(r) && !NotificationBaseline(r));r.cleanupStatus=0;
 r.referencesReleased=4;assert(!NotificationClosed(r) && !NotificationBaseline(r));r.referencesReleased=5;
 r.afterConversion=0;assert(!NotificationBaseline(r));r.afterConversion=1;
 r.afterOpen=0;assert(!NotificationBaseline(r));
 NotificationRecord record{};record.armed=1;record.baselineCounter=10;
 struct Event{uint32_t sequence=1,message=0x282,origin=1,commandAck=3,immContextPresent=1,immConversionSucceeded=1,immOpen=0;uint64_t counter=20;} e;
 struct Mode{uint32_t sequence=1,messageSequence=1;uint64_t startedCounter=21,finishedCounter=22;ModeReceipt mode;} m;
 m.mode=r;
 assert(ClaimNotification(record,e,m,3));assert(record.claimed==1);
 assert(!ClaimNotification(record,e,m,3));
 record.claimed=0;record.armed=0;assert(!ClaimNotification(record,e,m,3));record.armed=1;
 m.mode.beforeOpenType=0;assert(!ClaimNotification(record,e,m,3));m.mode.beforeOpenType=3;
 e.origin=2;assert(!ClaimNotification(record,e,m,3));e.origin=1;
 e.sequence=0;assert(!ClaimNotification(record,e,m,3));e.sequence=1;
 assert(!ClaimNotification(record,e,m,4));
 record.baselineCounter=23;assert(!ClaimNotification(record,e,m,3));
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'policy.cpp';exe=root/('policy.exe' if os.name=='nt' else 'policy')
            cpp.write_text(code)
            result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)

class NotificationDecodeTests(unittest.TestCase):
    def fixture(self):
        import importlib
        self.assertTrue((Path(__file__).resolve().parents[1]/'e2e/ime_notification_caller.py').is_file(),'notification decoder missing')
        m=importlib.import_module('ime_notification_caller')
        c=m.Config(version=1,enabled=1,creationTime=555)
        c.plugin.version=1
        r=m.Record(armed=1,claimed=1,sequence=1,messageSequence=1,hookSentByCurrentThread=1,
            frameCount=2,unknownFrames=1,baselineCounter=10,counter=30,finishedCounter=40)
        r.frames[0].moduleId=12;r.frames[0].rva=100
        mode={'status':0,'cleanupStatus':0,'variantClearHr':0,'beforeOpenHr':0,'beforeConversionHr':0,
              'beforeOpenType':3,'beforeConversionType':3,'beforeOpen':0,'beforeConversion':1,
              'referencesAcquired':5,'referencesReleased':5,'releaseCalls':1,'openSetCalls':0,'conversionSetCalls':0}
        msg={'sequence':1,'message':0x282,'origin':1,'pid':31,'tid':41,'hwnd':51,'commandAck':3,'counter':20}
        event={'messageSequence':1,'message':0x282,'origin':1,'commandAck':3,'messageCounter':20,
               'startedCounter':21,'finishedCounter':22,'imm':{'contextPresent':1,'conversionSucceeded':1,'open':0},'threadMode':mode}
        command={'success':True,'nativeAck':3,'status':0,'threadMode':dict(mode,afterOpenHr=0,afterConversionHr=0,afterOpenType=3,afterConversionType=3,afterOpen=1,afterConversion=1)}
        kw=dict(expected_config=bytes(c),messages={'status':'complete','events':[msg]},modes={'status':'complete','events':[event]},command3=command,pid=31,tid=41,hwnd=51,deadline=100,frequency=1000)
        return m,c,r,kw

    def test_valid_first_close_retains_only_numeric_frames_and_no_causal_claim(self):
        m,c,r,kw=self.fixture();out=m.decode(c,r,**kw)
        self.assertEqual(out['status'],'complete');self.assertEqual(out['messageSequence'],1)
        self.assertTrue(out['hookSentByCurrentThread']);self.assertFalse(out['callerAttributionProved'])
        self.assertEqual(out['engineCreationTime'],555)
        self.assertEqual(out['frames'],[{'moduleId':12,'rva':100},{'moduleId':0,'rva':0}])
        self.assertFalse(out['acceptanceEligible'])

    def test_changed_identity_unknown_addresses_and_later_selection_are_rejected(self):
        for mutate in (lambda c,r,k:setattr(c,'creationTime',556),lambda c,r,k:setattr(r.frames[1],'rva',99),
                       lambda c,r,k:setattr(r,'messageSequence',2),lambda c,r,k:setattr(r,'hookSentByCurrentThread',2),
                       lambda c,r,k:setattr(r,'baselineCounter',21),lambda c,r,k:k['messages']['events'][0].update(pid=32),
                       lambda c,r,k:k['command3'].update(success=False)):
            m,c,r,kw=self.fixture();mutate(c,r,kw)
            with self.assertRaises(AssertionError):m.decode(c,r,**kw)

    def test_partial_expired_or_rejected_records_are_inconclusive(self):
        for mutate in (lambda c,r,k:setattr(r,'sequence',0),lambda c,r,k:setattr(r,'expired',1),
                       lambda c,r,k:setattr(r,'rejected',1),lambda c,r,k:k['modes'].update(status='partial')):
            m,c,r,kw=self.fixture();mutate(c,r,kw)
            self.assertEqual(m.decode(c,r,**kw)['status'],'inconclusive')

    def test_bound_plugin_required_and_no_reproduction_is_not_acceptance(self):
        m,c,r,kw=self.fixture();r.frames[0].moduleId=14
        with self.assertRaises(AssertionError):m.decode(c,r,**kw)
        r.frames[0].moduleId=12;r.claimed=r.sequence=0
        self.assertEqual(m.decode(c,r,**kw)['status'],'not-triggered')
        c.enabled=0;kw['expected_config']=bytes(c)
        self.assertEqual(m.decode(c,r,**kw)['status'],'disabled')

class NotificationHookTests(unittest.TestCase):
    def test_actual_hook_forwards_sender_boolean_not_message_payload(self):
        from suite.tests.test_ime_mode_diagnostic import ime
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        hook=source[source.index('extern "C" __declspec(dllexport) LRESULT CALLBACK HookCall('):source.index('extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(')]
        code=r'''
#include <cstdint>
#include <cassert>
#ifdef __declspec
#undef __declspec
#endif
#define __declspec(x)
#define CALLBACK
using LRESULT=intptr_t;using WPARAM=uintptr_t;using LPARAM=intptr_t;using HWND=uintptr_t;
struct CWPSTRUCT{LPARAM lParam;WPARAM wParam;unsigned message;HWND hwnd;};
int calls=0;bool sent=false;
void observe(HWND h,unsigned m,WPARAM w,LPARAM l,unsigned o,bool current){
 assert(h==51 && m==0x282 && o==1 && l==77);assert(w==0 || w==123);++calls;sent=current;}
LRESULT CallNextHookEx(void*,int,WPARAM,LPARAM){return 71;}
'''+hook+r'''
int main(){CWPSTRUCT message{77,0,0x282,51};
 assert(HookCall(0,9,reinterpret_cast<LPARAM>(&message))==71 && calls==1 && sent);
 message.wParam=123;HookCall(0,0,reinterpret_cast<LPARAM>(&message));assert(calls==2 && !sent);
 HookCall(-1,1,reinterpret_cast<LPARAM>(&message));assert(calls==2);
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'hook.cpp';exe=root/('hook.exe' if os.name=='nt' else 'hook')
            cpp.write_text(code)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)

class NotificationPublicationTests(unittest.TestCase):
    def test_native_acquire_never_exposes_an_unpublished_stack(self):
        from suite.tests.test_ime_mode_diagnostic import ime
        marker='extern "C" __declspec(dllexport) unsigned int ReadNotification('
        self.assertIn(marker,ime.OBSERVER_SOURCE,'notification acquire export missing')
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        function=ime.OBSERVER_SOURCE[ime.OBSERVER_SOURCE.index(marker):ime.OBSERVER_SOURCE.index('extern "C" __declspec(dllexport) unsigned int StateSize()')]
        code=r'''
#include <cassert>
#include <cstring>
#include "ime_notification_caller.h"
#include "ime_compartment_protocol.h"
#ifdef __declspec
#undef __declspec
#endif
#define __declspec(x)
using LONG=int32_t;
struct State{uint32_t magic=0x4f47494d,version=4;opengeul_ime::NotificationConfig notificationConfig{};opengeul_ime::NotificationRecord notification{};};
void MemoryBarrier(){}
LONG InterlockedCompareExchange(volatile LONG*p,LONG,LONG){return *p;}
'''+function+r'''
int main(){State s;s.notificationConfig.version=s.notificationConfig.enabled=1;s.notificationConfig.creationTime=555;
 opengeul_ime::NotificationConfig c{};opengeul_ime::NotificationRecord r{};
 s.notification.armed=s.notification.claimed=1;s.notification.baselineCounter=10;s.notification.frames[0].rva=123;
 assert(ReadNotification(&s,&c,&r)==2 && r.sequence==0 && r.claimed==1 && r.frames[0].rva==0);
 s.notification.sequence=1;assert(ReadNotification(&s,&c,&r)==1 && r.frames[0].rva==123);
 s.version=3;assert(ReadNotification(&s,&c,&r)==0);
 assert(ReadNotification(nullptr,&c,&r)==0);
}
'''
        folder=Path(ime.__file__).parent
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'publication.cpp';exe=root/('publication.exe' if os.name=='nt' else 'publication');cpp.write_text(code)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)

class NotificationIntegrationTests(unittest.TestCase):
    def test_observer_joins_published_stack_to_existing_owned_mode_rows(self):
        from suite.tests.test_ime_mode_diagnostic import ime
        m,c,r,kw=NotificationDecodeTests().fixture()
        observer=object.__new__(ime.CompositionObserver);state=ime.NativeState()
        observer.pid,observer.tid,observer.focus=31,41,51
        observer.diagnose_ime_mode=observer.capture_ime_caller=True
        observer.notification_config=bytes(c);observer.mode_diagnostic_budget=(100,1000)
        observer.commands=[dict(command=3,**kw['command3'])]
        state.notificationConfig=c;state.notification=r
        state.modeDiagnosticEnabled=state.modeDiagnosticVersion=1
        state.modeDiagnosticDeadline=100;state.modeDiagnosticFrequency=1000;state.diagnosticCount=1
        event=state.diagnostics[0]
        for k,v in kw['messages']['events'][0].items():setattr(event,k,v)
        event.immContextPresent=event.immConversionSucceeded=1
        mode=state.modeDiagnostics[0];mode.sequence=mode.messageSequence=1;mode.startedCounter=21;mode.finishedCounter=22
        for k,v in kw['modes']['events'][0]['threadMode'].items():setattr(mode.mode,k,v)
        observer.state=lambda:state
        observer._read_mode_diagnostic=lambda i:(state.modeDiagnostics[i],state.diagnostics[i])
        observer._read_notification=lambda:(c,r)
        result=observer.mode_diagnostics()
        self.assertIn('notificationCaller',result,'observer did not join the caller receipt')
        self.assertEqual(result['notificationCaller']['status'],'complete')

class NotificationProducerTests(unittest.TestCase):
    def test_actual_producer_claims_once_and_rejects_reentrant_or_late_capture(self):
        from suite.tests.test_ime_mode_diagnostic import ime
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        producer=source[source.index('static void capture_notification('):source.index('// Passive, bounded owned-target observations.')]
        declarations=source[source.index('struct Event {'):source.index('static State* shared')]
        prefix=r'''
#include <cstdint>
#include <cwchar>
#include <cassert>
#include "ime_notification_caller.h"
#include "ime_compartment_protocol.h"
#include "ime_command_admission.h"
using WCHAR=uint16_t;using LONG=int32_t;using HMODULE=void*;
constexpr unsigned GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT=2;
void MemoryBarrier(){} LONG InterlockedExchange(volatile LONG*p,LONG v){auto old=*p;*p=v;return old;}
int calls=0;bool reenter=false,expire=false,owned=true;
static void capture_notification(LONG,bool);
unsigned CaptureStackBackTrace(unsigned,unsigned cap,void**out,void*){assert(cap==16);++calls;out[0]=reinterpret_cast<void*>(0x1010);
 if(reenter)capture_notification(0,false);return 1;}
HMODULE GetModuleHandleW(const wchar_t*name){++calls;if(expire)return nullptr;return std::wcscmp(name,L"mergedlo.dll")==0?reinterpret_cast<void*>(0x1000):nullptr;}
bool GetModuleHandleExW(unsigned,const wchar_t*,HMODULE*out){++calls;*out=reinterpret_cast<void*>(0x1000);return true;}
#include "bounded_stack_windows.h"
namespace opengeul_stack {template<class B,class C>uint32_t PluginOrigin(HMODULE,const B&,const B&,C){return 1;}}
'''+declarations+r'''
State storage{};State*shared=&storage;
opengeul_ime::NotificationConfig notificationAdmission{};
bool notificationReading=false;
bool notification_clock(uint64_t&stamp){if(expire&&calls){shared->notification.expired=1;return false;}stamp=30;return true;}
bool notification_target(){if(!owned){shared->notification.rejected=4;return false;}return true;}
void reset(){storage={};notificationAdmission={};notificationReading=false;calls=0;expire=reenter=false;owned=true;
 shared->notificationConfig.enabled=1;shared->notification.armed=1;shared->notification.baselineCounter=10;shared->command=3;
 auto&e=shared->diagnostics[0];e.sequence=1;e.message=0x282;e.origin=1;e.commandAck=3;e.immContextPresent=e.immConversionSucceeded=1;e.counter=20;
 auto&m=shared->modeDiagnostics[0];m.sequence=m.messageSequence=1;m.startedCounter=21;m.finishedCounter=22;
 m.mode.beforeOpenHr=m.mode.beforeConversionHr=m.mode.variantClearHr=0;m.mode.beforeOpenType=m.mode.beforeConversionType=3;
 m.mode.releaseCalls=1;m.mode.referencesAcquired=m.mode.referencesReleased=5;}
'''+producer+r'''
int main(){reset();capture_notification(0,true);assert(shared->notification.sequence==1 && shared->notification.messageSequence==1 && shared->notification.hookSentByCurrentThread==1);
 assert(shared->notification.frameCount==1 && shared->notification.frames[0].moduleId==1 && shared->notification.frames[0].rva==16);
 int prior=calls;capture_notification(0,false);assert(calls==prior && shared->notification.hookSentByCurrentThread==1);
 reset();shared->notificationConfig.enabled=0;capture_notification(0,true);assert(calls==0 && !shared->notification.claimed);
 reset();shared->modeDiagnostics[0].mode.beforeOpenType=0;capture_notification(0,true);assert(calls==0 && !shared->notification.claimed);
 reset();shared->modeDiagnostics[0].sequence=0;capture_notification(0,true);assert(!shared->notification.claimed);
 reset();owned=false;capture_notification(0,true);assert(shared->notification.claimed && shared->notification.rejected && !shared->notification.sequence && calls==0);
 reset();expire=true;capture_notification(0,true);assert(shared->notification.claimed && shared->notification.expired && !shared->notification.sequence && calls==1);
 reset();reenter=true;capture_notification(0,true);assert(shared->notification.rejected&8);assert(shared->notification.sequence==1);
}
'''
        # Braces preserve warnings-as-errors in the synthetic native API.
        prefix=prefix.replace(' if(reenter)capture_notification(0,false);return 1;}',' if(reenter){capture_notification(0,false);}return 1;}')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'producer.cpp';exe=root/('producer.exe' if os.name=='nt' else 'producer');cpp.write_text(prefix)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(Path(ime.__file__).parent),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)

    def test_early_imm_reentrancy_rejects_sample_even_when_outer_getter_fails(self):
        from suite.tests.test_ime_mode_diagnostic import ime
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        functions=source[source.index('static void capture_notification('):source.index('static void observe(HWND')]
        code=r'''

#include <cstdint>
#include <cwchar>
#include <cassert>
#include "ime_notification_caller.h"
#include "ime_compartment_protocol.h"
#include "ime_command_admission.h"
using WCHAR=uint16_t;using LONG=int32_t;using DWORD=uint32_t;using HMODULE=void*;using HWND=void*;using HIMC=void*;using UINT=unsigned;using UINT_PTR=uintptr_t;using WPARAM=uintptr_t;using LPARAM=intptr_t;
struct LARGE_INTEGER{int64_t QuadPart;};
constexpr unsigned GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT=2;
constexpr unsigned WM_INPUTLANGCHANGE=0x51,WM_IME_NOTIFY=0x282,WM_KEYDOWN=0x100,WM_CHAR=0x102,WM_IME_SETCONTEXT=0x281,WM_SETFOCUS=7,WM_KILLFOCUS=8;
void MemoryBarrier(){} LONG InterlockedExchange(volatile LONG*p,LONG v){auto old=*p;*p=v;return old;} LONG InterlockedIncrement(volatile LONG*p){return ++*p;}
unsigned CaptureStackBackTrace(unsigned,unsigned,void**out,void*){out[0]=reinterpret_cast<void*>(0x1010);return 1;}
HMODULE GetModuleHandleW(const wchar_t*name){return std::wcscmp(name,L"mergedlo.dll")==0?reinterpret_cast<void*>(0x1000):nullptr;}
bool GetModuleHandleExW(unsigned,const wchar_t*,HMODULE*out){*out=reinterpret_cast<void*>(0x1000);return true;}
#include "bounded_stack_windows.h"
namespace opengeul_stack {template<class B,class C>uint32_t PluginOrigin(HMODULE,const B&,const B&,C){return 1;}}
struct Event { uint32_t sequence,message,flags,pid,tid; uint64_t hwnd,layout;
    int32_t compositionBytes,resultBytes; uint32_t origin; WCHAR composition[256],result[256]; };
struct ModeDiagnosticEvent { uint32_t sequence,messageSequence; uint64_t startedCounter,finishedCounter;
    opengeul_ime::ModeReceipt mode; };
struct DiagnosticEvent { uint32_t sequence,message,origin,pid,tid,commandAck;
    uint64_t hwnd,layout,wparam,lparam,focusHwnd,counter;
    uint32_t immContextPresent,immConversionSucceeded,immOpen,immConversion,immSentence; uint64_t himc; };
struct State { uint32_t magic,version,pid,tid; volatile LONG count,overflow;
    uint32_t command,ack; uint64_t previousLayout; uint32_t previousOpen,previousConversion,previousSentence;
    int32_t status; uint32_t activeLanguage; WCHAR activeClsid[40],activeProfile[40];
    uint32_t previousProfileType,previousLanguage; WCHAR previousClsid[40],previousProfile[40];
    uint64_t previousProfileLayout; uint32_t activeProfileType; uint64_t activeProfileLayout;
    int32_t profileManagerHresult,previousProfileHresult,activateProfileHresult,activeProfileHresult;
    uint32_t activateLayoutError; Event events[512];
    opengeul_ime::CommandBudget commandBudgets[4]; uint64_t targetHwnd,rootHwnd;
    int32_t previousTsfOpen,previousTsfConversion; uint32_t tsfCaptured,profileChangeAttempted;
    uint32_t immContextPresent,immConversionSucceeded,immOpen,immConversion,immSentence;
    opengeul_ime::ModeReceipt threadMode; opengeul_ime::CommandRejection commandRejection; uint32_t nativeAttemptedMask;
    volatile LONG diagnosticCount,diagnosticOverflow; DiagnosticEvent diagnostics[128];
    uint32_t modeDiagnosticVersion,modeDiagnosticEnabled; uint64_t modeDiagnosticDeadline,modeDiagnosticFrequency;
    ModeDiagnosticEvent modeDiagnostics[128];
    volatile LONG contextBoundaryExpired,contextBoundaryRejected;
    opengeul_ime::NotificationConfig notificationConfig;opengeul_ime::CompartmentConfig compartmentConfig;opengeul_ime::NotificationRecord notification; };

State storage{};State*shared=&storage;opengeul_ime::NotificationConfig notificationAdmission{};bool notificationReading=false;uint64_t tick=20;
bool notification_clock(uint64_t&stamp){stamp=++tick;return true;}bool notification_target(){return true;}
bool QueryPerformanceCounter(LARGE_INTEGER*out){out->QuadPart=++tick;return true;}bool QueryPerformanceFrequency(LARGE_INTEGER*out){out->QuadPart=1000;return true;}
DWORD GetWindowThreadProcessId(HWND,DWORD*p){*p=31;return 41;}DWORD GetCurrentThreadId(){return 41;}
void* GetKeyboardLayout(int){return nullptr;}HWND GetFocus(){return reinterpret_cast<HWND>(51);}
static void observe_diagnostic(HWND,UINT,WPARAM,LPARAM,UINT,bool);
bool reentered=false,failOuter=false;
HIMC ImmGetContext(HWND hwnd){if(!reentered){reentered=true;observe_diagnostic(hwnd,WM_IME_NOTIFY,0,0,1,true);if(failOuter)return nullptr;}return reinterpret_cast<HIMC>(1);}
int ImmGetOpenStatus(HIMC){return 0;}int ImmGetConversionStatus(HIMC,DWORD*c,DWORD*s){*c=1;*s=0;return 1;}int ImmReleaseContext(HWND,HIMC){return 1;}
void observe_mode_diagnostic(LONG index){auto&m=shared->modeDiagnostics[index];m.sequence=m.messageSequence=index+1;m.startedCounter=++tick;m.finishedCounter=++tick;
 m.mode.beforeOpenHr=m.mode.beforeConversionHr=m.mode.variantClearHr=0;m.mode.beforeOpenType=m.mode.beforeConversionType=3;m.mode.releaseCalls=1;m.mode.referencesAcquired=m.mode.referencesReleased=5;}
'''+functions+r'''
int main(){for(bool fail:{false,true}){
 storage={};reentered=false;failOuter=fail;tick=20;
 shared->notificationConfig.enabled=1;shared->notification.armed=1;shared->notification.baselineCounter=10;
 shared->command=shared->ack=3;shared->pid=31;shared->tid=41;shared->targetHwnd=51;
 observe_diagnostic(reinterpret_cast<HWND>(51),WM_IME_NOTIFY,0,0,1,true);
 assert(shared->diagnosticCount==2 && shared->diagnostics[0].sequence==1 && shared->diagnostics[1].sequence==2);
 assert(shared->notification.rejected&8);
 assert(!shared->notification.sequence && !shared->notification.claimed);
 assert(shared->diagnostics[0].immContextPresent==unsigned(!fail));
 }}
'''
        code='#include <initializer_list>\n'+code
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'early.cpp';exe=root/('early.exe' if os.name=='nt' else 'early');cpp.write_text(code)
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(Path(ime.__file__).parent),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)
