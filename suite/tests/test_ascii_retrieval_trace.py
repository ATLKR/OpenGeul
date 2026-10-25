"""Bounded retrieval metadata never changes input or claims handler completion."""
import ctypes as C
import unittest
import test_ascii_capture_trace as fixture
import ascii_message_protocol as p

class RetrievalTraceTests(unittest.TestCase):
    def test_protocol_appends_three_fixed_buckets_without_moving_capture_prefix(self):
        self.assertEqual(p.State.retrievalVersion.offset,421392)
        self.assertEqual(C.sizeof(p.RetrievalEvent),256)
        self.assertEqual(p.State.captureVersion.offset,407008)
        self.assertEqual(p.RETRIEVAL_CAPACITY,3);self.assertEqual(p.RETRIEVAL_FRAMES,16)
    def test_local_decoder_exports_uncommitted_claim_as_partial_without_target_queries(self):
        owner=fixture.CaptureTraceTests();self.addCleanup(owner.doCleanups);b,t=owner.transport()
        t.state.retrievalClaimed=2;b.now=102.;b.identity_ok=False
        result=t.read_capture_trace(local_only=True)['retrieval']
        self.assertEqual(result['status'],'partial');self.assertEqual(result['pendingBuckets'],[1])
        self.assertEqual(result['records'],[])
    def test_actual_native_retrieval_correlation_caps_expiry_and_redaction(self):
        import os,shutil,subprocess,tempfile
        from pathlib import Path
        from native_executable_cleanup import remove_completed_image
        compiler=shutil.which('g++') or shutil.which('clang++')
        if compiler is None:self.skipTest('Portable compiler unavailable')
        folder=Path(__file__).resolve().parents[1]/'e2e';source=(folder/'ascii_message_observer.cpp').read_text()
        producer=source[source.index('// Bounded retrieval metadata'):source.index('void observe(')]
        prefix=r'''
#include "ascii_message_protocol.h"
#include <cassert>
#include <cstring>
#include <cwchar>
#include <limits>
using LONG=int32_t;using UINT=uint32_t;using DWORD=uint32_t;using HWND=void*;using HMODULE=void*;using WPARAM=uintptr_t;using LPARAM=intptr_t;
struct POINT{int32_t x,y;};struct MSG{HWND hwnd;UINT message;WPARAM wParam;LPARAM lParam;DWORD time;POINT pt;};
constexpr uint32_t GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT=2;
OpenGeulAscii::State storage{};auto shared=&storage;bool stopped=false;uint32_t ownerThread=99;
uint64_t ticks=10;int originCalls=0,stackCalls=0,moduleCalls=0,fromCalls=0;int bindingCalls=0;uint32_t bindingStatus=1;int expireAt=0;bool originOk=true,unstable=false,reenter=false;uint16_t stackCount=2;
LONG load(const uint32_t*p){return *p;}void publish(uint32_t*p,LONG v){*p=v;}
bool header(OpenGeulAscii::State*){return true;}
bool captureClock(uint64_t&v){if(ticks>=100){shared->captureExpired=1;return false;}v=ticks;return true;}
uint32_t GetCurrentThreadId(){return 99;}DWORD GetLastError(){return 5;}
void traceRetrieval(const MSG&,WPARAM,uint32_t);
uint32_t pluginOriginStatus(HMODULE m){++bindingCalls;assert(m==reinterpret_cast<void*>(0x7000));if(expireAt==5)ticks=100;return bindingStatus;}
bool ClientToScreen(HWND,POINT*p){++originCalls;p->x=1;p->y=48;if(expireAt==1)ticks=100;
 if(reenter){MSG nested{reinterpret_cast<HWND>(22),0x201,1,123,0,{505,365}};traceRetrieval(nested,1,1);}return originOk;}
uint16_t CaptureStackBackTrace(uint32_t,uint32_t count,void**p,uint32_t*){++stackCalls;assert(count==16);for(unsigned i=0;i<stackCount;++i)p[i]=reinterpret_cast<void*>(i==0?0x1010:0x7010);if(expireAt==2)ticks=100;return stackCount;}
HMODULE GetModuleHandleW(const wchar_t*name){++moduleCalls;if(expireAt==3)ticks=100;return std::wcscmp(name,L"mergedlo.dll")==0?reinterpret_cast<void*>(0x1000):(std::wcscmp(name,L"vclplug_winlo.dll")==0?reinterpret_cast<void*>(0x7000):nullptr);}
bool GetModuleHandleExW(uint32_t flags,const wchar_t*address,HMODULE*out){assert(flags==6);++fromCalls;if(expireAt==4)ticks=100;auto a=reinterpret_cast<uintptr_t>(address);*out=reinterpret_cast<void*>(a==0x1010?(unstable&&fromCalls%2==0?0x2000:0x1000):0x7000);return true;}
void reset(){storage={};ticks=10;originCalls=stackCalls=moduleCalls=fromCalls=0;expireAt=0;bindingCalls=0;bindingStatus=1;originOk=true;unstable=reenter=false;stackCount=2;
 shared->recording=1;shared->captureEnabled=1;shared->captureVersion=1;shared->retrievalVersion=1;
 shared->hwnd=22;shared->pid=88;shared->tid=99;shared->engineCreationTime=555;shared->captureDeadline=100;shared->captureFrequency=1000;}
MSG seed(uint32_t sequence,UINT message,WPARAM flags){auto&r=shared->captureEvents[sequence-1];r.sequence=sequence;r.origin=1;r.message=message;r.removeFlags=flags;
 r.pid=88;r.tid=99;r.hwnd=22;r.engineCreationTime=555;r.counter=5;r.finishedCounter=6;r.frequency=1000;r.lParam=123;r.wParam=1;
 shared->captureCount=sequence;return MSG{reinterpret_cast<HWND>(22),message,1,123,0,{505,365}};}
'''
        main=r'''
int main(){
 reset();auto down=seed(1,0x201,1);traceRetrieval(down,1,1);assert(shared->retrievalClaimed==1 && shared->retrievalEvents[0].sequence==1);
 assert(originCalls==1 && stackCalls==0 && shared->retrievalEvents[0].pointX==505 && shared->retrievalEvents[0].clientOriginY==48);
 auto up=seed(2,0x202,1);traceRetrieval(up,1,2);auto&r=shared->retrievalEvents[1];assert(r.sequence==2 && r.captureSequence==2 && r.frameCount==2);
 assert(r.frames[0].moduleId==1 && r.frames[0].rva==16 && r.frames[1].moduleId==0 && r.frames[1].rva==0 && r.unknownFrames==1);
 assert(bindingCalls==0);
 auto up3=seed(3,0x202,3);traceRetrieval(up3,3,3);for(int i=0;i<20;++i)traceRetrieval(up3,3,3);
 assert(shared->retrievalClaimed==7 && stackCalls==2 && originCalls==3 && shared->captureCount==3);
 reset();up=seed(1,0x202,1);shared->captureEvents[0].wParam=0;traceRetrieval(up,1,1);assert(shared->retrievalRejected==1 && shared->retrievalClaimed==0 && originCalls==0 && stackCalls==0);
 reset();up=seed(1,0x202,1);shared->captureEvents[0].sequence=0;traceRetrieval(up,1,1);assert(shared->retrievalClaimed==0 && shared->retrievalRejected);
 for(int point=1;point<=4;++point){reset();up=seed(1,0x202,1);expireAt=point;traceRetrieval(up,1,1);
 assert(shared->retrievalClaimed==2 && shared->retrievalEvents[1].sequence==0 && shared->retrievalExpired);
 if(point==1){assert(stackCalls==0 && moduleCalls==0);}if(point==2){assert(moduleCalls==0);}if(point==3){assert(moduleCalls==1 && fromCalls==0);}if(point==4){assert(moduleCalls==13 && fromCalls==1);}}
 reset();up=seed(1,0x202,1);ticks=100;traceRetrieval(up,1,1);assert(originCalls==0 && stackCalls==0 && shared->retrievalClaimed==0);
 reset();down=seed(1,0x201,1);reenter=true;traceRetrieval(down,1,1);assert(shared->retrievalRejected&2);assert(originCalls==1);
 reset();up=seed(1,0x202,1);unstable=true;traceRetrieval(up,1,1);assert(shared->retrievalEvents[1].frames[0].moduleId==0 && shared->retrievalEvents[1].frames[0].rva==0);
 reset();up=seed(1,0x202,1);stackCount=16;traceRetrieval(up,1,1);assert(shared->retrievalEvents[1].frameCount==16 && shared->retrievalEvents[1].frameCapReached==1);
 reset();shared->pluginBinding.enabled=1;up=seed(1,0x202,1);traceRetrieval(up,1,1);
 assert(bindingCalls==1 && shared->retrievalEvents[1].frames[1].moduleId==14 && shared->retrievalEvents[1].frames[1].rva==16);
 assert(shared->pluginOrigins[1].sequence==2 && shared->pluginOrigins[1].captureSequence==1 && shared->pluginOrigins[1].status==1);
 reset();shared->pluginBinding.enabled=1;bindingStatus=2;up=seed(1,0x202,1);traceRetrieval(up,1,1);
 assert(bindingCalls==1 && shared->retrievalEvents[1].frames[1].moduleId==0 && shared->pluginOrigins[1].status==2);
 reset();shared->pluginBinding.enabled=1;expireAt=5;up=seed(1,0x202,1);traceRetrieval(up,1,1);
 assert(bindingCalls==1 && shared->retrievalEvents[1].sequence==0 && shared->pluginOrigins[1].sequence==0 && shared->retrievalExpired);
 reset();down=seed(1,0x201,1);originOk=false;traceRetrieval(down,1,1);assert(shared->retrievalEvents[0].originSucceeded==0 && shared->retrievalEvents[0].originError==5);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cpp=root/'retrieval.cpp';exe=root/('retrieval.exe' if os.name=='nt' else 'retrieval')
            cpp.write_text(prefix+producer+main)
            build=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(folder),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            finally:remove_completed_image(root,exe,result)
    def row(self):
        owner=fixture.CaptureTraceTests();self.addCleanup(owner.doCleanups);b,t=owner.transport()
        s=t.state;s.captureCount=1;c=s.captureEvents[0]
        for key,value in dict(sequence=1,origin=1,message=0x202,removeFlags=3,pid=t.target['pid'],tid=t.target['tid'],hwnd=t.target['hwnd'],engineCreationTime=t.creation,counter=10,finishedCounter=11,frequency=100,lParam=123).items():setattr(c,key,value)
        s.retrievalClaimed=4;r=s.retrievalEvents[2]
        for key,value in dict(sequence=3,captureSequence=1,bucket=2,message=0x202,removeFlags=3,pid=t.target['pid'],tid=t.target['tid'],hwnd=t.target['hwnd'],engineCreationTime=t.creation,counter=12,finishedCounter=13,frequency=100,lParam=123,originSucceeded=1,pointX=505,pointY=365,clientOriginX=1,clientOriginY=48,stackRequested=1,frameCount=2,unknownFrames=1).items():setattr(r,key,value)
        r.frames[0].moduleId=1;r.frames[0].rva=16
        return b,t,r
    def test_decoder_correlates_owned_event_and_exports_only_numeric_module_offsets(self):
        b,t,r=self.row();b.now=102.;b.identity_ok=False
        result=t.read_capture_trace(local_only=True)['retrieval']
        self.assertEqual(result['status'],'complete');row=result['records'][0]
        self.assertEqual(row['captureSequence'],1);self.assertEqual(row['frames'],[dict(moduleId=1,rva=16),dict(moduleId=0,rva=0)])
        self.assertEqual((row['pointX'],row['clientOriginX']),(505,1))
        self.assertFalse(result['consumingCallerProved']);self.assertFalse(result['moduleLifetimeContinuityProved'])
    def test_decoder_rejects_uncorrelated_malformed_expired_and_unredacted_records(self):
        for mutation in (lambda r:setattr(r,'captureSequence',2),lambda r:setattr(r,'pid',999),
                lambda r:setattr(r,'removeFlags',1),lambda r:setattr(r,'finishedCounter',1000),
                lambda r:setattr(r,'frameCount',17),lambda r:setattr(r.frames[1],'rva',0x12345678),
                lambda r:setattr(r.frames[0],'moduleId',99),lambda r:setattr(r,'unknownFrames',0),
                lambda r:setattr(r,'reserved1',1),lambda r:setattr(r,'sequence',2)):
            b,t,r=self.row();mutation(r)
            with self.assertRaises(AssertionError):t.read_capture_trace(local_only=True)
    def test_failed_api_expiry_and_rejection_are_explicit_without_uncommitted_bytes(self):
        b,t,r=self.row();r.originSucceeded=0;r.originError=5;r.clientOriginX=r.clientOriginY=0;r.flags=1
        self.assertEqual(t.read_capture_trace(local_only=True)['retrieval']['status'],'partial')
        t.state.retrievalExpired=1;r.sequence=0;r.frames[0].rva=0xfeedface
        result=t.read_capture_trace(local_only=True)['retrieval'];self.assertEqual(result['status'],'expired');self.assertEqual(result['records'],[])
        t.state.retrievalRejected=2
        self.assertEqual(t.read_capture_trace(local_only=True)['retrieval']['status'],'rejected')
    def test_retrieval_newer_than_copied_capture_prefix_is_deferred(self):
        b,t,r=self.row()
        result=t._retrieval_trace([])
        self.assertEqual(result['status'],'partial');self.assertEqual(result['pendingBuckets'],[2]);self.assertEqual(result['records'],[])
    def test_commit_mutation_during_copy_is_rejected(self):
        b,t,r=self.row();original=t.dll.ReadWord;seen=[]
        address=t.view+p.State.retrievalEvents.offset+2*C.sizeof(p.RetrievalEvent)
        def read(pointer):
            if C.addressof(pointer.contents)==address:
                seen.append(1)
                if len(seen)==2:r.sequence=0
            return original(pointer)
        t.dll.ReadWord=read
        with self.assertRaisesRegex(AssertionError,'changed during copy'):t.read_capture_trace(local_only=True)
    def test_module_mapping_matches_native_whitelist_and_has_no_path_or_loading_api(self):
        from pathlib import Path
        import re
        source=(Path(__file__).resolve().parents[1]/'e2e/ascii_message_observer.cpp').read_text()
        producer=source[source.index('// Bounded retrieval metadata'):source.index('void observe(')]
        self.assertEqual(re.findall(r'L"([a-z0-9_]+\.dll)"',producer),list(p.RETRIEVAL_MODULES.values())+["vclplug_winlo.dll"])
        for forbidden in ('LoadLibrary','FreeLibrary','GetModuleFileName','ReadProcessMemory','EnumProcessModules','SymFromAddr'):
            self.assertNotIn(forbidden,producer)
