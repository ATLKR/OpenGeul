"""Compile the actual export; unsettled state must never disclose partial frames."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import korean_ime_smoke as ime
from native_executable_cleanup import remove_completed_image

class CompartmentPublicationTests(unittest.TestCase):
    def test_actual_export_requires_disabled_idle_completed_cleanup_command(self):
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        exports=source[source.index('extern "C" __declspec(dllexport) unsigned int DisableCompartment('):source.index('extern "C" __declspec(dllexport) unsigned int PublishCommand(')]
        prefix=r'''
#include <cassert>
#include <cstring>
#include "ime_notification_caller.h"
#include "ime_compartment_protocol.h"
#define __declspec(x)
using LONG=int32_t;
void MemoryBarrier(){}
LONG InterlockedExchange(volatile LONG* p,LONG v){LONG old=*p;*p=v;return old;}
LONG InterlockedCompareExchange(volatile LONG* p,LONG v,LONG expected){LONG old=*p;if(old==expected)*p=v;return old;}
struct State {uint32_t magic=0x4f47494d,version=4,ack=3;
 opengeul_ime::CompartmentConfig compartmentConfig;
 opengeul_ime::NotificationConfig notificationConfig;
 opengeul_ime::CompartmentRecord compartment;};
'''
        main=r'''
int main(){State s;opengeul_ime::CompartmentConfig c;opengeul_ime::NotificationConfig b;opengeul_ime::CompartmentRecord r;
 s.compartment.sequence=1;s.compartment.frames[0]={14,100};s.compartment.frameCount=1;
 assert(ReadCompartment(&s,&c,&b,&r)==2 && !r.sequence && !r.frameCount && !r.frames[0].rva);
 assert(DisableCompartment(&s)==1 && s.compartment.lease.disabled && !s.compartment.lease.armed);
 assert(ReadCompartment(&s,&c,&b,&r)==2 && !r.frameCount);
 s.ack=4;s.compartment.lease.activeCallbacks=1;
 assert(ReadCompartment(&s,&c,&b,&r)==2 && !r.frameCount);
 s.compartment.lease.activeCallbacks=0;
 assert(ReadCompartment(&s,&c,&b,&r)==1 && r.sequence==1 && r.frames[0].rva==100);
 s.compartment.sequence=0;
 assert(ReadCompartment(&s,&c,&b,&r)==2 && !r.frameCount && !r.frames[0].rva);
 s.magic=0;assert(ReadCompartment(&s,&c,&b,&r)==0 && DisableCompartment(&s)==0);
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'publication.cpp';exe=root/('publication.exe' if os.name=='nt' else 'publication')
            cpp.write_text(prefix+exports+main)
            build=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(Path(ime.__file__).parent),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)

    def test_actual_callback_admission_does_not_query_or_expire_a_completed_sample(self):
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        method=source[source.index('    bool ClaimCallback() {'):source.index('    void CaptureCallback() {')]
        prefix=r'''
#include <cassert>
#include "ime_compartment_protocol.h"
struct State{opengeul_ime::CompartmentRecord compartment;uint32_t ack=3;};
State storage;State* shared=&storage;
struct Admission{uint32_t active=0;} commandAdmission;
unsigned queries=0;bool late=false;
uint32_t compartment_load(uint32_t& v){return v;}
bool compartment_identity(bool){++queries;return true;}
bool compartment_clock(uint64_t& v){++queries;v=20;if(late){shared->compartment.expired=1;return false;}return true;}
struct Host {
'''
        main=r'''
};
int main(){Host h;auto& r=shared->compartment.lease;r.activeCallbacks=1;
 assert(!h.ClaimCallback() && !queries); // pre-ACK, unarmed
 r.armed=1;assert(h.ClaimCallback() && queries==3 && r.claimed);
 late=true;assert(!h.ClaimCallback() && queries==3 && !shared->compartment.expired);
 r.activeCallbacks=2;assert(!h.ClaimCallback() && (r.rejected&opengeul_ime::LeaseCallback) && queries==3);
 r.disabled=1;assert(!h.ClaimCallback() && queries==3);
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'admission.cpp';exe=root/('admission.exe' if os.name=='nt' else 'admission')
            cpp.write_text(prefix+method+main)
            build=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(Path(ime.__file__).parent),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)

    def test_actual_cleanup_gate_cannot_be_disabled_by_mutating_configuration(self):
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        begin=source.index('} else if (sequence==4 && !shared->status) {')
        gate=source[begin:].splitlines()[1]
        code=r'''
#include <cassert>
struct State {struct {bool enabled=false;} compartmentConfig;int status=0;} storage;
State* shared=&storage;int held=1;int* compartmentSink=&held;int limits=7;int attempts=0,restores=0;
bool compartment_disconnect(int limit){assert(limit==7);++attempts;return false;}
void failure(int code){shared->status=code;}
int main(){
'''+gate+r'''
 if(!shared->status)++restores;
 assert(attempts==1 && restores==0 && shared->status==-48);
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'cleanup.cpp';exe=root/('cleanup.exe' if os.name=='nt' else 'cleanup')
            cpp.write_text(code)
            built=subprocess.run([compiler,'-std=c++17',str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)

    def test_ack_publication_tail_has_no_native_queries_before_first_callback(self):
        compiler=shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        source=ime.OBSERVER_SOURCE
        begin=source.index('    if(armCompartment)')
        tail=source[begin:source.index('// Optional TSF reads',begin)]
        code=r'''
#include <cassert>
#include "ime_compartment_protocol.h"
using LONG=int32_t;
struct State{uint32_t ack=2;opengeul_ime::CompartmentRecord compartment;} storage;
State* shared=&storage;
void MemoryBarrier(){}
LONG InterlockedExchange(volatile LONG* p,LONG v){auto old=*p;*p=v;return old;}
void publish(){bool armCompartment=true;uint32_t sequence=3;
'''+tail+r'''
int main(){auto& r=shared->compartment.lease;r.installed=1;r.activeCallbacks=1;
 // Reentrant prevalidation callback is before ACK and before arming.
 assert(!opengeul_ime::CompartmentNeedsBoundary(r,1));
 publish();assert(shared->ack==3 && r.armed);
 assert(opengeul_ime::ClaimCompartment(r,true,true,shared->ack,false,1));
 assert(r.claimed);
}
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cpp=root/'ack.cpp';exe=root/('ack.exe' if os.name=='nt' else 'ack')
            cpp.write_text(code)
            built=subprocess.run([compiler,'-std=c++17','-I',str(Path(ime.__file__).parent),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)
