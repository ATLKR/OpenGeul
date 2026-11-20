"""Execute the portable native policy with deterministic COM boundary doubles."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HEADER = Path(__file__).resolve().parents[1] / 'e2e' / 'ime_thread_mode.h'
HARNESS = r'''
#include <string>
#include <vector>
#include <iostream>
#include "ime_thread_mode.h"
#if __has_include("ime_command_admission.h")
#include "ime_command_admission.h"
#define COMMAND_ADMISSION 1
#endif
using namespace opengeul_ime;
static_assert(sizeof(ModeReceipt)==184,"Fixed-width receipt ABI differs");
struct Fake {
    bool manager=true, hasOpen=true, hasConversion=true, expired=false, nullCM=false;
    int enumCalls=0, getCalls=0, writes=0, clientCalls=0, releases=0, reads=0, fetched=0;
    int refs=0, releaseDelta=0, failWrite=0, expireAfterRead=0, clearAt=0; int32_t readHr=0;
    uint32_t client=17; int32_t open=1, conversion=0x20; uint32_t type=3;
    bool wrongReadback=false, endless=false, clearFailure=false, expireOnRelease=false; ModeReceipt* receipt=nullptr;
    bool WithinBudget() { return !expired; }
    int32_t ExistingManager() { if(manager)++refs; return 0; }
    bool HasManager() { return manager; }
    int32_t CompartmentManager() { if(!nullCM)++refs; return 0; }
    bool HasCompartmentManager(){return !nullCM;}
    int32_t BeginEnumeration() { ++refs; return 0; }
    bool HasEnumerator(){return true;}
    uint32_t Fetched(){return fetched;}
    bool HasCompartment(int){return true;}
    int32_t ClientInterface(){++refs;return 0;}
    bool HasClient(){return true;}
    int32_t Next(int& key) {
        ++enumCalls;fetched=1;
        if(endless) {key=99;return 0;}
        if(enumCalls==1 && hasOpen) {key=1;return 0;}
        if(enumCalls==2 && hasConversion) {key=2;return 0;}
        fetched=0;return 1;
    }
    int32_t Get(int) { ++getCalls;++refs;return 0; }
    Value Read(int key) {
        ++reads;
        if(clearFailure && (!clearAt || reads==clearAt)){receipt->cleanupStatus=-122;receipt->variantClearHr=-122;}
        if(expireAfterRead && reads==expireAfterRead)expired=true;
        return {readHr,type,(wrongReadback && writes==2 && key==2) ? conversion^1 : key==1?open:conversion};
    }
    int32_t ObserverClient(uint32_t& value) {++clientCalls;value=client;return 0;}
    int32_t Write(int key,uint32_t id,int32_t value) {
        ++writes;if(id!=17)return -999;
        if(writes==failWrite)return -123;
        if(key==1)open=value;else conversion=value;return 0;
    }
    ReleaseCounts Release() {++releases;if(expireOnRelease)expired=true;return {uint32_t(refs),uint32_t(refs+releaseDelta)};}
};
int main(int argc,char**argv) {
    if(argc!=2)return 90;
    std::string name=argv[1];Fake a;ModeReceipt r{};a.receipt=&r;
    if(name=="immutable-command-budget" || name=="nested-command" || name=="command-one-use") {
#ifdef COMMAND_ADMISSION
        static_assert(sizeof(CommandBudget)==16 && sizeof(CommandRejection)==16,"Command ABI differs");
        CommandAdmission admission{};CommandRejection rejection{};CommandBudget published{10,1000};
        CommandLease first(admission,rejection,3,published);
        if(!first.Entered())return 80;
        CommandBudget slots[4]{};
        if(!InstallCommandBudget(slots,3,{10,1000}) || !InstallCommandBudget(slots,4,{500,1000})
            || InstallCommandBudget(slots,3,{900,1000}) || slots[2].counter!=10 || slots[3].counter!=500)return 85;
        if(name=="immutable-command-budget") {
            published.counter=500;published.frequency=2000;
            if(first.budget.counter!=10 || first.budget.frequency!=1000)return 81;
        } else if(name=="nested-command") {
            CommandLease nested(admission,rejection,4,CommandBudget{500,1000});
            if(nested.Entered() || admission.active!=3 || rejection.count!=1 || rejection.sequence!=4 || rejection.during!=3 || rejection.reason!=1)return 82;
            first.Finish();CommandLease retry(admission,rejection,4,CommandBudget{900,1000});
            if(retry.Entered() || rejection.reason!=2 || rejection.count!=2)return 83;
        } else {
            first.Finish();CommandLease retry(admission,rejection,3,CommandBudget{500,1000});
            if(retry.Entered() || rejection.reason!=2 || admission.active!=0)return 84;
        }
        return 0;
#else
        return 77;
#endif
    }
    if(name=="capture") {
        CaptureThreadMode(a,r);
        if(r.status || r.beforeOpen!=1 || r.beforeConversion!=0x20 || a.writes || a.clientCalls || a.releases!=1 || r.referencesAcquired!=r.referencesReleased)return 1;
    } else {
        if(name=="missing-manager")a.manager=false;
        if(name=="null-cm")a.nullCM=true;
        if(name=="missing-compartment")a.hasConversion=false;
        if(name=="enum-bound")a.endless=true;
        if(name=="empty-value")a.type=0;
        if(name=="variant-cleanup")a.clearFailure=true;
        if(name=="read-and-clear"){a.clearFailure=true;a.readHr=-123;}
        if(name=="type-and-clear"){a.clearFailure=true;a.type=8;}
        if(name=="readback-and-clear"){a.clearFailure=true;a.clearAt=4;a.wrongReadback=true;}
        if(name=="zero-client")a.client=0;
        if(name=="open-failure")a.failWrite=1;
        if(name=="conversion-failure")a.failWrite=2;
        if(name=="readback")a.wrongReadback=true;
        if(name=="deadline")a.expireAfterRead=2;
        if(name=="release-failure")a.releaseDelta=-1;
        if(name=="late-release")a.expireOnRelease=true;
        SetThreadMode(a,r,3,0,0);
        if(a.releases!=1)return 2;
        if(name=="null-cm" && (r.compartmentManagerHr!=0 || r.compartmentManagerPresent!=0 || r.clientHr!=NotAttempted))return 12;
        if(name=="success") {
            if(r.status || a.writes!=2 || a.clientCalls!=1 || a.open!=1 || a.conversion!=0x21 || r.afterOpen!=1 || r.afterConversion!=0x21 || r.referencesAcquired!=r.referencesReleased)return 3;
        } else {
            if(r.status==0)return 4;
            if((name=="missing-manager" || name=="missing-compartment" || name=="enum-bound") && (a.getCalls || a.writes))return 5;
            if((name=="empty-value" || name=="zero-client" || name=="deadline" || name=="variant-cleanup") && a.writes)return 6;
            if(name=="enum-bound" && a.enumCalls!=64)return 7;
            if(name=="open-failure" && a.writes!=1)return 8;
            if((name=="conversion-failure" || name=="readback") && a.writes!=2)return 9;
            if(name=="conversion-failure" && r.conversionSetHr!=-123)return 10;
            if(name=="release-failure" && r.cleanupStatus==0)return 11;
            if(name=="read-and-clear" && (r.status!=-29 || r.beforeOpenHr!=-123 || r.cleanupStatus!=-122))return 13;
            if(name=="type-and-clear" && (r.status!=-29 || r.beforeOpenType!=8 || r.cleanupStatus!=-122))return 14;
            if(name=="readback-and-clear" && (r.status!=-36 || r.cleanupStatus!=-122))return 15;
        }
    }
    return 0;
}
'''


class NativeThreadModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = None

    def execute(self, case):
        self.assertTrue(HEADER.is_file(), 'Missing bounded owned-thread native mode policy')
        cls = type(self)
        if cls.binary is None:
            compiler = shutil.which('c++')
            self.assertIsNotNone(compiler, 'A native C++ compiler is required for policy verification')
            source = Path(cls.directory.name) / 'policy.cpp'
            source.write_text(HARNESS)
            cls.binary = source.with_suffix('')
            build = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I', str(HEADER.parent), str(source), '-o', str(cls.binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        result = subprocess.run([str(cls.binary), case], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, case + ': ' + result.stdout + result.stderr)

    def test_capture_is_read_only_and_releases_all_references(self): self.execute('capture')
    def test_exact_requested_state_is_read_back_before_success(self): self.execute('success')
    def test_missing_existing_manager_never_creates_or_writes(self): self.execute('missing-manager')
    def test_missing_installed_guid_never_calls_creating_getter(self): self.execute('missing-compartment')
    def test_installed_guid_enumeration_stops_at_original_bound(self): self.execute('enum-bound')
    def test_empty_original_value_is_not_manufactured_as_zero(self): self.execute('empty-value')
    def test_zero_client_identifier_never_authorizes_a_write(self): self.execute('zero-client')
    def test_open_failure_does_not_send_conversion_or_retry(self): self.execute('open-failure')
    def test_partial_setting_retains_primary_native_hresult_without_retry(self): self.execute('conversion-failure')
    def test_wrong_semantic_readback_cannot_acknowledge_success(self): self.execute('readback')
    def test_deadline_expiring_during_read_blocks_state_setting(self): self.execute('deadline')
    def test_reference_cleanup_failure_prevents_success(self): self.execute('release-failure')

    def test_variant_cleanup_failure_blocks_effects_and_preserves_cleanup_hresult(self): self.execute('variant-cleanup')

    def test_late_balanced_release_consumes_original_deadline_before_success(self): self.execute("late-release")

    def test_native_success_with_null_interface_is_preserved_but_not_admitted(self): self.execute("null-cm")

    def test_failed_getvalue_remains_primary_when_variant_cleanup_also_fails(self): self.execute("read-and-clear")
    def test_unsupported_type_remains_primary_when_variant_cleanup_also_fails(self): self.execute("type-and-clear")
    def test_wrong_readback_remains_primary_when_variant_cleanup_also_fails(self): self.execute("readback-and-clear")

    def test_active_command_snapshots_only_its_original_budget(self): self.execute("immutable-command-budget")
    def test_nested_restoration_is_rejected_without_entering_or_resetting_active_command(self): self.execute("nested-command")
    def test_attempted_command_cannot_be_replayed_with_a_new_budget(self): self.execute("command-one-use")

if __name__ == "__main__": unittest.main(verbosity=2)
