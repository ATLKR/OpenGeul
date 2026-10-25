"""Opt-in event-correlated TSF snapshots never imply IME acceptance."""
import ctypes
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime

class ModeDiagnosticTests(unittest.TestCase):
    def test_appended_abi_preserves_original_prefix(self):
        self.assertEqual(ime.NativeState.modeDiagnosticVersion.offset,567040)
        self.assertGreater(ctypes.sizeof(ime.NativeModeDiagnosticEvent),ctypes.sizeof(ime.native_mode.NativeModeReceipt))
    def observer(self):
        observer=object.__new__(ime.CompositionObserver)
        state=ime.NativeState();observer.pid=31;observer.tid=41;observer.focus=51
        observer.diagnose_ime_mode=True;observer.mode_diagnostic_budget=(999,1000)
        observer.state=lambda:state
        def acquire(index):
            row=state.modeDiagnostics[index];event=state.diagnostics[index]
            return (row,event) if row.sequence==event.sequence==index+1 else None
        observer._read_mode_diagnostic=acquire
        state.modeDiagnosticVersion=1;state.modeDiagnosticEnabled=1
        state.modeDiagnosticDeadline=999;state.modeDiagnosticFrequency=1000
        state.diagnosticCount=1
        event=state.diagnostics[0];event.sequence=1;event.pid=31;event.tid=41;event.hwnd=51;event.message=0x100;event.origin=2
        return observer,state
    def test_rows_require_both_publications_and_preserve_typed_cleanup(self):
        observer,state=self.observer()
        self.assertEqual(observer.mode_diagnostics()['status'],'partial')
        row=state.modeDiagnostics[0];row.sequence=row.messageSequence=1;row.startedCounter=10;row.finishedCounter=20
        row.mode.beforeOpenType=row.mode.beforeConversionType=3;row.mode.beforeOpen=1;row.mode.beforeConversion=1
        row.mode.referencesAcquired=row.mode.referencesReleased=4;row.mode.releaseCalls=1
        result=observer.mode_diagnostics()
        self.assertEqual(result['status'],'complete');self.assertEqual(result['events'][0]['threadMode']['beforeOpen'],1)
        self.assertFalse(result['acceptanceEligible']);self.assertEqual(result['deadlineCounter'],999)
        state.diagnostics[0].pid=99
        with self.assertRaises(AssertionError):observer.mode_diagnostics()
    def test_default_disabled_has_no_mode_receipt(self):
        observer,state=self.observer();state.modeDiagnosticEnabled=0;observer.diagnose_ime_mode=False
        self.assertEqual(observer.mode_diagnostics()['status'],'disabled')

    def test_budget_and_correlation_mutation_reject_and_failed_mode_stays_nonacceptance(self):
        observer,state=self.observer();row=state.modeDiagnostics[0]
        row.sequence=row.messageSequence=1;row.mode.status=-20
        primary=bytes(state.threadMode);state.status=-7;state.ack=3
        result=observer.mode_diagnostics()
        self.assertEqual(result['events'][0]['threadMode']['status'],-20)
        self.assertFalse(result['acceptanceEligible'])
        self.assertEqual(bytes(state.threadMode),primary);self.assertEqual((state.status,state.ack),(-7,3))
        row.messageSequence=2
        with self.assertRaises(AssertionError):observer.mode_diagnostics()
        row.messageSequence=1;state.modeDiagnosticDeadline=1001
        with self.assertRaises(AssertionError):observer.mode_diagnostics()

    def test_actual_capture_policy_is_read_only_bounded_and_releases_refs(self):
        import os,shutil,subprocess,tempfile
        from native_executable_cleanup import remove_completed_image
        from native_ime_thread_mode_policy import HARNESS
        compiler=shutil.which('g++') or shutil.which('clang++')
        if compiler is None:self.skipTest('Portable compiler unavailable; Windows native validation remains separate')
        source=ime.OBSERVER_SOURCE
        declarations=source[source.index('struct Event {'):source.index('static State* shared')]
        producer=source[source.index('static bool modeDiagnosticReading='):source.index('// Passive, bounded owned-target observations.')]
        acquire=source[source.index('extern "C" __declspec(dllexport) unsigned int ReadModeDiagnostic('):source.index('extern "C" __declspec(dllexport) unsigned int StateSize()')]
        prefix=HARNESS[:HARNESS.index('int main(')]+r'''
#include <cassert>
#include <cstring>
using WCHAR=uint16_t;using LONG=int32_t;using UINT=uint32_t;
#define __declspec(x)
struct LARGE_INTEGER { int64_t QuadPart; };
static uint64_t ticks=10;static int scenario=0,reads=0,writes=0,clients=0,managers=0;
bool QueryPerformanceCounter(LARGE_INTEGER* q){q->QuadPart=ticks;return true;}
void MemoryBarrier(){}
LONG InterlockedExchange(volatile LONG* p,LONG v){auto old=*p;*p=v;return old;}
LONG InterlockedCompareExchange(volatile LONG* p,LONG v,LONG expected){auto old=*p;if(old==expected)*p=v;return old;}
namespace opengeul_ime {
struct WindowsThreadMode: ::Fake {
 uint64_t deadline,frequency;
 WindowsThreadMode(ModeReceipt& r,uint64_t d,uint64_t f):deadline(d),frequency(f){
  receipt=&r;manager=scenario!=1;hasOpen=scenario!=2;type=scenario==3?0:3;
  expireAfterRead=scenario==4?1:0;releaseDelta=scenario==5?1:0;
 }
 bool WithinBudget(){return !expired && ticks<deadline && frequency==1000;}
 int32_t ExistingManager(){++managers;return Fake::ExistingManager();}
 ReleaseCounts Release(){::reads+=reads;::writes+=writes;::clients+=clientCalls;return Fake::Release();}
};
}
'''
        main=r'''
State storage{};State* shared=&storage;
'''+producer+acquire+r'''
int main(){
 shared->magic=0x4f47494d;shared->version=4;shared->modeDiagnosticVersion=1;
 shared->modeDiagnosticDeadline=100;shared->modeDiagnosticFrequency=1000;
 observe_mode_diagnostic(0);assert(managers==0 && shared->modeDiagnostics[0].sequence==0);
 shared->modeDiagnosticEnabled=1;auto primary=shared->threadMode;
 for(int trial=0;trial<6;++trial){
  scenario=trial;reads=managers=0;observe_mode_diagnostic(trial);
  auto& r=shared->modeDiagnostics[trial];assert(r.sequence==uint32_t(trial+1) && r.messageSequence==r.sequence);
  assert(!writes && !clients && r.mode.openSetCalls==0 && r.mode.conversionSetCalls==0);
  assert(r.mode.releaseCalls==1);
  if(trial!=5)assert(r.mode.referencesAcquired==r.mode.referencesReleased);
  if(trial==0)assert(r.mode.status==0 && r.mode.beforeOpenType==3 && reads==2);
  else assert(r.mode.status!=0);
  if(trial==4)assert(reads==1 && r.mode.status==-20);
 }
 ticks=100;reads=managers=0;observe_mode_diagnostic(6);
 assert(shared->modeDiagnostics[6].mode.status==-20 && reads==0 && managers==0);
 ticks=10;modeDiagnosticReading=true;observe_mode_diagnostic(7);modeDiagnosticReading=false;
 assert(shared->modeDiagnostics[7].mode.status==-40 && managers==0);
 assert(!memcmp(&primary,&shared->threadMode,sizeof(primary)) && shared->ack==0 && shared->status==0);
 ModeDiagnosticEvent copied{};DiagnosticEvent message{};
 assert(ReadModeDiagnostic(shared,0,&copied,&message)==0);
 shared->diagnostics[0].sequence=1;
 assert(ReadModeDiagnostic(shared,0,&copied,&message)==1 && copied.messageSequence==1);
 assert(ReadModeDiagnostic(shared,128,&copied,&message)==0);
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cpp=root/'mode.cpp';exe=root/('mode.exe' if os.name=='nt' else 'mode')
            cpp.write_text(prefix+declarations+main)
            build=subprocess.run([compiler,'-std=c++17','-I',str(Path(ime.__file__).parent),str(cpp),'-o',str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            try:self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            finally:remove_completed_image(root,exe,run)

    def test_calc_diagnostic_keeps_one_original_input_mode_and_restore_sequence(self):
        import test_ime_case_phases as phases
        from unittest.mock import patch
        original=phases.ime.case
        def diagnostic(*args,**kwargs):return original(*args,**kwargs,diagnose_ime_mode=True)
        with patch.object(phases.ime,'case',side_effect=diagnostic):
            calls,record,result,error=phases.IMECasePhaseTests().run_case('calc')
        self.assertIsNone(error,repr(error));self.assertTrue(result['success'])
        self.assertTrue(result['caseImeOraclesPassed']);self.assertFalse(result['imeVerified'])
        self.assertFalse(result['acceptanceEligible']);self.assertEqual(result['kind'],'native-ime-mode-diagnostic')
        self.assertEqual([x for x in calls if isinstance(x,tuple) and x[0]=='command'],[('command',1),('command',2),('command',3),('command',4)])
        self.assertEqual(calls.count('CTRL_S'),1);self.assertEqual(calls.count('ascii-forward'),1)

    def test_mode_gate_rejects_before_output_or_preparation(self):
        import json,os,tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);suite=root/'suite';suite.mkdir();fixtures=root/'fixtures';fixtures.mkdir()
            output=root/'diagnostic';event=root/'event.json';event.write_text('{}')
            (suite/'suite-inventory.json').write_text(json.dumps({'schemaVersion':1,'architecture':'x64'}))
            with patch.object(ime,'os',SimpleNamespace(name='nt',environ={})),patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event)}), \
                 patch.object(ime.native_arch,'observe_native_architecture'),patch.object(ime.native_arch,'validate_native_architecture'), \
                 patch.object(ime.ascii_input,'prepare_observer') as prepare:
                with self.assertRaisesRegex(ValueError,'owner-push context'):
                    ime.main(['--suite',str(suite),'--fixtures',str(fixtures),'--readiness',str(root/'readiness.json'),
                        '--output',str(output),'--diagnose-ime-mode','calc'])
                prepare.assert_not_called();self.assertFalse(output.exists())
