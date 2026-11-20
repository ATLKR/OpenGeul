"""Fault injection for a one-shot callback whose code must outlive subscription."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from native_executable_cleanup import remove_completed_image


class CompartmentLeaseTests(unittest.TestCase):
    def test_actual_policy_keeps_uncertain_subscription_alive_and_never_retries(self):
        folder = Path(__file__).resolve().parents[1] / 'e2e'
        self.assertTrue((folder / 'ime_compartment_lease.h').is_file(), 'callback lifetime policy missing')
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('Portable C++ compiler unavailable')
        code = r'''
#include <cassert>
#include "ime_compartment_lease.h"
using namespace opengeul_ime;
bool ClaimCompartment(CompartmentLeaseRecord& r,bool owned,bool time,uint32_t ack,bool command){
 return opengeul_ime::ClaimCompartment(r,owned,time,ack,command,r.activeCallbacks);}
struct Fake {
    bool pin=true, source=true, advise=true, possible=false, baseline=true, unadvise=true, release=true;
    bool held=false, pinned=false, subscribed=false, partialSource=false, throwAdvise=false;
    CompartmentLeaseRecord* enterDuringUnadvise=nullptr;
    unsigned checks=0, expireAt=0, pins=0, advises=0, unadvises=0, releases=0;
    bool Check(){return ++checks!=expireAt;}
    bool CallbacksIdle(const CompartmentLeaseRecord& r){return r.activeCallbacks==0;}
    bool Pin(){++pins;pinned=pin;return pin;}
    bool AcquireExistingSource(){assert(pinned);held=source || partialSource;return source;}
    bool Advise(){assert(pinned && held);++advises;subscribed=advise || possible;if(throwAdvise)throw 1;return advise;}
    bool SubscriptionPossible(){return subscribed;}
    bool ReadOpenOne(){assert(held && subscribed);return baseline;}
    bool Unadvise(){assert(pinned && subscribed);++unadvises;if(unadvise)subscribed=false;
        if(enterDuringUnadvise)enterDuringUnadvise->activeCallbacks=1;
        return unadvise;}
    bool ReleaseOwned(){assert(!subscribed);++releases;if(release)held=false;return release;}
};
int main(){
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));
     assert(r.installed && r.pinned && a.subscribed);assert(!InstallCompartment(a,r));
     assert(a.advises==1 && a.pins==1);}
    {Fake a;CompartmentLeaseRecord r{};a.pin=false;assert(!InstallCompartment(a,r));
     assert(!a.held && !a.advises && r.disabled);}
    {Fake a;CompartmentLeaseRecord r{};a.advise=false;a.possible=true;
     assert(!InstallCompartment(a,r));assert(a.subscribed && r.subscriptionPossible);
     assert(!a.releases);a.unadvise=false;assert(!DisconnectCompartment(a,r));
     assert(a.held && a.subscribed && a.pinned && !a.releases);
     assert(!DisconnectCompartment(a,r));assert(a.unadvises==1);}
    {Fake a;CompartmentLeaseRecord r{};a.baseline=false;assert(!InstallCompartment(a,r));
     assert(a.subscribed && r.disabled);assert(DisconnectCompartment(a,r));
     assert(r.disconnected && r.released && !a.subscribed && !a.held && a.pinned);}
    // Expiry at every install boundary cannot accidentally release a live sink.
    for(unsigned boundary=1;boundary<=5;++boundary){
     Fake a;CompartmentLeaseRecord r{};a.expireAt=boundary;
     assert(!InstallCompartment(a,r));assert(r.disabled && !r.installed && !a.releases);
     assert(!a.subscribed || (a.pinned && a.held && r.subscriptionPossible));
    }
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));
     a.expireAt=a.checks+1;assert(!DisconnectCompartment(a,r));
     assert(r.disabled && a.subscribed && !a.unadvises && !a.releases);
     a.expireAt=0;assert(!DisconnectCompartment(a,r));assert(!a.unadvises);}
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));
     a.expireAt=a.checks+2;assert(!DisconnectCompartment(a,r));
     assert(!a.subscribed && a.held && r.disconnected && !r.released);
     assert(!DisconnectCompartment(a,r));assert(a.unadvises==1 && !a.releases);}
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));
     assert(ArmCompartment(r,true));r.activeCallbacks=1;assert(ClaimCompartment(r,true,true,3,false));
     assert(!ClaimCompartment(r,true,true,3,false));assert(r.claimed==1);
     r.activeCallbacks=0;assert(DisconnectCompartment(a,r));assert(!ClaimCompartment(r,true,true,3,false));}
    for(unsigned bad=0;bad<6;++bad){
     Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));assert(ArmCompartment(r,true));
     r.activeCallbacks=bad==4?2:(bad==5?0:1);
     assert(!ClaimCompartment(r,bad!=0,bad!=1,bad==2?4:3,bad==3));
     assert(r.disabled && r.rejected && !r.claimed);
     assert(!ClaimCompartment(r,true,true,3,false));
    }
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));r.activeCallbacks=1;
     assert(!DisconnectCompartment(a,r));assert(a.subscribed && !a.unadvises && !a.releases);}
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));a.release=false;
     assert(!DisconnectCompartment(a,r));assert(r.disconnected && !r.released && a.held && a.pinned);}
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));assert(ArmCompartment(r,true));
     r.activeCallbacks=1;assert(ClaimCompartment(r,true,true,3,false));
     r.activeCallbacks=2;assert(!ClaimCompartment(r,true,true,3,false));
     assert(r.rejected && r.disabled);r.activeCallbacks=1;
     assert(!ClaimCompartment(r,true,true,3,false));}
    {Fake a;CompartmentLeaseRecord r{};a.throwAdvise=true;
     try{InstallCompartment(a,r);assert(false);}catch(int){}
     assert(r.subscriptionPossible && a.subscribed && a.pinned && a.held && !a.releases);}
    {Fake a;CompartmentLeaseRecord r{};a.source=false;a.partialSource=true;
     assert(!InstallCompartment(a,r));assert(a.held && !a.advises && !a.releases);
     assert(DisconnectCompartment(a,r));assert(!a.held && a.releases==1 && !a.unadvises);}
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));a.enterDuringUnadvise=&r;
     assert(!DisconnectCompartment(a,r));assert(r.disconnected && !r.released && a.held && !a.releases);}
    {Fake a;CompartmentLeaseRecord r{};assert(InstallCompartment(a,r));a.expireAt=a.checks+3;
     assert(!DisconnectCompartment(a,r));assert(r.disconnected && r.released && !a.held && r.rejected);}
}
'''
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cpp, exe = root / 'lease.cpp', root / ('lease.exe' if os.name == 'nt' else 'lease')
            cpp.write_text(code)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                    '-I', str(folder), str(cpp), '-o', str(exe)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5)
            try:
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            finally:
                remove_completed_image(root, exe, ran)
