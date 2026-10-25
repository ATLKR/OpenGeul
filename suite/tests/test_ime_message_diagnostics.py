"""Passive message evidence never substitutes for Korean composition."""
import ctypes
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from suite.tests import test_korean_ime_smoke as fixtures
from native_executable_cleanup import remove_completed_image
ime = fixtures.ime


class MessageDiagnosticsTests(unittest.TestCase):
    def test_native_state_layout_matches_python_including_appended_ring(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if compiler is None: self.skipTest('Portable C++ compiler unavailable; Windows DLL ABI is checked at load')
        source = ime.OBSERVER_SOURCE
        declarations = source[source.index('struct Event {'):source.index('static State* shared')]
        prefix = '#include <cstdint>\n#include <cstddef>\n#include "ime_thread_mode.h"\n#include "ime_command_admission.h"\n#include "ime_notification_caller.h"\nusing WCHAR=uint16_t;using LONG=int32_t;\n'
        checks = 'static_assert(sizeof(State)==' + str(ctypes.sizeof(ime.NativeState)) + ',"state ABI");\n'
        checks += '\n'.join('static_assert(offsetof(State,' + name + ')==' + str(getattr(ime.NativeState, name).offset) + ',"field ABI");' for name, _ in ime.NativeState._fields_)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cpp = root/'layout.cpp'; exe = root/'layout'
            cpp.write_text(prefix + declarations + checks + '\nint main(){}\n')
            result = subprocess.run([compiler, '-std=c++17', '-I', str(Path(ime.__file__).parent), str(cpp), '-o', str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_case_captures_diagnostics_before_restoration_on_success_and_failure(self):
        import test_ime_case_phases as phases
        for failure in (False, True):
            with self.subTest(failure=failure):
                captures = []
                retain = phases.ime.retain_ime_message_diagnostics
                def capture(record, observer):
                    if 'imeMessageDiagnostics' not in record:
                        self.assertFalse(any(row['command'] == 4 for row in observer.commands))
                        captures.append(record['stage'])
                        observer.diagnostics = lambda: {'status': 'complete', 'events': [{'immOpen': 0}]}
                        if failure:
                            observer.events = Mock(side_effect=RuntimeError('composition snapshot unavailable during cleanup'))
                    retain(record, observer)
                with patch.object(phases.ime, 'retain_ime_message_diagnostics', side_effect=capture):
                    _, record, _, error = phases.IMECasePhaseTests().run_case('writer', fail_mode=failure)
                self.assertEqual(len(captures), 1)
                self.assertEqual(error is not None, failure)
                self.assertEqual(record['imeMessageDiagnostics']['events'], [{'immOpen': 0}])
                if failure:
                    self.assertIn('composition snapshot unavailable', record['imeCleanupError'])

    def test_native_producer_filters_bounds_and_publishes_without_command_mutation(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if compiler is None: self.skipTest('Portable C++ compiler unavailable; Windows observer compilation is separate')
        source = ime.OBSERVER_SOURCE
        declaration = source[source.index('struct DiagnosticEvent {'):source.index('struct State {')]
        producer = source[source.index('static void observe_diagnostic('):source.index('static void observe(HWND')]
        prefix = r'''
#include <cstdint>
#include <cstring>
#include <cstddef>
#include <cassert>
using DWORD=uint32_t;using LONG=int32_t;using UINT=uint32_t;
using HWND=uintptr_t;using HIMC=uintptr_t;using WPARAM=uintptr_t;using LPARAM=intptr_t;using UINT_PTR=uintptr_t;
constexpr UINT WM_INPUTLANGCHANGE=0x51,WM_IME_NOTIFY=0x282,WM_KEYDOWN=0x100,WM_CHAR=0x102;
constexpr UINT WM_IME_SETCONTEXT=0x281,WM_SETFOCUS=7,WM_KILLFOCUS=8;
struct LARGE_INTEGER { int64_t QuadPart; };
DWORD windowPid=31,windowTid=41,currentTid=41;bool contextPresent=true;int reads=0,releases=0;
uintptr_t currentContext=0x100,currentFocus=51;int64_t ticks=1234;int expireAt=0,opens=0,conversions=0;
bool QueryPerformanceFrequency(LARGE_INTEGER* c){c->QuadPart=1000;return true;}
DWORD GetWindowThreadProcessId(HWND,DWORD* pid){*pid=windowPid;if(expireAt==1)ticks=2000;return windowTid;}
DWORD GetCurrentThreadId(){return currentTid;}
uintptr_t GetKeyboardLayout(int){return 0x0412;}
HWND GetFocus(){return currentFocus;}
bool QueryPerformanceCounter(LARGE_INTEGER* c){c->QuadPart=ticks;return true;}
HIMC ImmGetContext(HWND){++reads;if(expireAt==2)ticks=2000;return contextPresent?currentContext:0;}
bool ImmGetOpenStatus(HIMC){++opens;return false;}
bool ImmGetConversionStatus(HIMC,DWORD* c,DWORD* s){++conversions;*c=1;*s=8;return true;}
bool ImmReleaseContext(HWND,HIMC){++releases;return true;}
LONG InterlockedIncrement(volatile LONG* p){return ++*p;}
LONG InterlockedExchange(volatile LONG* p,LONG v){LONG old=*p;*p=v;return old;}
void MemoryBarrier(){}
'''
        state = r'''
struct State {uint64_t targetHwnd=51;uint32_t pid=31,tid=41,ack=3,immOpen=1;
uint32_t modeDiagnosticVersion=1,modeDiagnosticEnabled=0;uint64_t modeDiagnosticDeadline=2000,modeDiagnosticFrequency=1000;
struct {unsigned enabled=0;} notificationConfig;struct {unsigned rejected=0;} notification;
volatile LONG contextBoundaryExpired=0,contextBoundaryRejected=0;
volatile LONG diagnosticCount=0,diagnosticOverflow=0;DiagnosticEvent diagnostics[128]={};};
State instance;State* shared=&instance;
'''
        assertions = '\n'.join('static_assert(offsetof(DiagnosticEvent,' + name + ')==' + str(getattr(ime.NativeDiagnosticEvent, name).offset) + ',"field ABI");' for name, _ in ime.NativeDiagnosticEvent._fields_)
        main = r'''
int main(){
 observe_diagnostic(99,WM_KEYDOWN,71,0,2);assert(instance.diagnosticCount==0 && reads==0);
 windowPid=99;observe_diagnostic(51,WM_CHAR,103,0,2);assert(instance.diagnosticCount==0 && reads==0);windowPid=31;
 windowTid=99;observe_diagnostic(51,WM_CHAR,103,0,2);assert(instance.diagnosticCount==0);windowTid=41;
 currentTid=99;observe_diagnostic(51,WM_CHAR,103,0,2);assert(instance.diagnosticCount==0);currentTid=41;
 observe_diagnostic(51,0x10f,0,0,1);assert(instance.diagnosticCount==0);
 observe_diagnostic(51,WM_KEYDOWN,71,34,2);
 const auto first=instance.diagnostics[0];
 assert(first.sequence==1 && first.immOpen==0 && first.wparam==71 && first.lparam==34);
 assert(first.counter==1234 && first.layout==0x0412 && first.commandAck==3);
 assert(first.himc==0x100);
 assert(instance.ack==3 && instance.immOpen==1 && reads==1 && releases==1);
 contextPresent=false;observe_diagnostic(51,WM_IME_NOTIFY,8,0,1);
 assert(instance.diagnostics[1].sequence==2 && instance.diagnostics[1].immContextPresent==0 && instance.diagnostics[1].himc==0 && releases==1);
 contextPresent=true;currentContext=0x200;
 observe_diagnostic(51,WM_IME_SETCONTEXT,1,0,1);
 assert(instance.diagnostics[2].himc==0x200 && instance.diagnostics[2].message==WM_IME_SETCONTEXT);
 observe_diagnostic(51,WM_SETFOCUS,0,0,1);assert(instance.diagnostics[3].himc==0x200);
 currentFocus=99;
 observe_diagnostic(51,WM_KILLFOCUS,99,0,1);
 assert(instance.diagnostics[4].himc==0x200 && instance.diagnostics[4].focusHwnd==99);
 observe_diagnostic(99,WM_SETFOCUS,51,0,1);assert(instance.diagnosticCount==5);
 observe_diagnostic(51,0x490,123,456,1);assert(instance.diagnosticCount==5);
 instance.modeDiagnosticEnabled=1;
 observe_diagnostic(51,0x490,123,456,1);assert(instance.diagnosticCount==6);
 assert(instance.diagnostics[5].wparam==0 && instance.diagnostics[5].lparam==0);
 observe_diagnostic(99,0x490,123,456,3);assert(instance.diagnosticCount==6);
 observe_diagnostic(51,0x490,123,456,2);assert(instance.diagnosticCount==6);
 ticks=2000;int expiredReads=reads;
 observe_diagnostic(51,0x490,123,456,3);
 assert(instance.diagnosticCount==6 && reads==expiredReads && instance.contextBoundaryExpired==1);
 ticks=1234;observe_diagnostic(51,0x490,123,456,3);assert(instance.diagnosticCount==7);
 assert(instance.diagnostics[6].origin==3 && instance.diagnostics[6].lparam==0);
 for(int i=7;i<128;++i)observe_diagnostic(51,WM_INPUTLANGCHANGE,0,0,1);
 int priorReads=reads;
 for(int i=0;i<200;++i)observe_diagnostic(51,WM_CHAR,103,0,2);
 assert(instance.diagnosticCount==128 && instance.diagnosticOverflow==1 && reads==priorReads);
 assert(!std::memcmp(&first,&instance.diagnostics[0],sizeof(first)));
 instance.diagnosticCount=0;instance.diagnosticOverflow=0;std::memset(instance.diagnostics,0,sizeof(instance.diagnostics));
 expireAt=1;ticks=1234;priorReads=reads;
 observe_diagnostic(51,0x490,123,456,1);
 assert(reads==priorReads && instance.diagnosticCount==0);
 expireAt=2;ticks=1234;int priorOpens=opens,priorReleases=releases,priorConversions=conversions;
 observe_diagnostic(51,0x490,123,456,1);
 assert(reads==priorReads+1 && opens==priorOpens && conversions==priorConversions && releases==priorReleases+1);
 assert(instance.diagnosticCount==1 && instance.diagnostics[0].sequence==0);

}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cpp = root/'diagnostics.cpp'; exe = root/('diagnostics.exe' if os.name == 'nt' else 'diagnostics')
            cpp.write_text(prefix + declaration + assertions + state + '\nvoid observe_mode_diagnostic(LONG) {}\nvoid capture_notification(LONG,bool) {}\n' + producer + main)
            build = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5)
            try:
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            finally:
                remove_completed_image(root, exe, run)

    def observer(self):
        state = ime.NativeState()
        observer = object.__new__(ime.CompositionObserver)
        observer.pid, observer.tid, observer.focus = 31, 41, 51
        observer.state = lambda: state
        return observer, state

    def test_focus_and_context_transitions_retain_himc_values_without_requiring_focus_stability(self):
        observer, state = self.observer()
        state.diagnosticCount = 3
        for index, message in enumerate((0x281, 7, 8)):
            row = state.diagnostics[index]
            row.sequence, row.message, row.origin = index+1, message, 1
            row.pid, row.tid, row.hwnd = 31, 41, 51
            row.himc = 0x100 if index == 0 else 0x200
            row.focusHwnd = 99 if message == 8 else 51
        receipt = observer.diagnostics()
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual([row['himc'] for row in receipt['events']], [0x100, 0x200, 0x200])
        self.assertEqual(receipt['events'][-1]['focusHwnd'], 99)

    def test_only_published_rows_are_returned_without_changing_command_receipt(self):
        observer, state = self.observer()
        state.ack = 3
        state.immOpen = 1
        state.diagnosticCount = 2
        row = state.diagnostics[0]
        row.sequence, row.message, row.origin = 1, 0x100, 2
        row.pid, row.tid, row.hwnd = 31, 41, 51
        row.layout, row.wparam, row.immOpen = 0x0412, ord('G'), 0
        before = bytes(state)
        receipt = observer.diagnostics()
        self.assertEqual(receipt['status'], 'partial')
        self.assertEqual(len(receipt['events']), 1)
        self.assertEqual(receipt['events'][0]['immOpen'], 0)
        self.assertEqual(bytes(state), before)

    def test_overflow_is_explicit_and_foreign_rows_are_rejected(self):
        observer, state = self.observer()
        state.diagnosticOverflow = 1
        self.assertEqual(observer.diagnostics()['status'], 'overflow')
        state.diagnosticCount = 1
        row = state.diagnostics[0]
        row.sequence, row.message, row.origin = 1, 0x102, 2
        row.pid, row.tid, row.hwnd = 99, 41, 51
        with self.assertRaises(AssertionError): observer.diagnostics()

    def test_first_capture_survives_restoration_and_diagnostic_failure(self):
        record = {}
        observer = SimpleNamespace(diagnostics=Mock(return_value={'events': [{'immOpen': 0}]}))
        ime.retain_ime_message_diagnostics(record, observer)
        observer.diagnostics.side_effect = RuntimeError('later restoration state')
        ime.retain_ime_message_diagnostics(record, observer)
        self.assertEqual(observer.diagnostics.call_count, 1)
        self.assertEqual(record['imeMessageDiagnostics']['events'][0]['immOpen'], 0)
        failed = {}
        ime.retain_ime_message_diagnostics(failed, observer)
        self.assertEqual(failed['imeMessageDiagnostics']['status'], 'unavailable')

    def test_ascii_diagnostic_does_not_satisfy_composition_gate(self):
        fixture = fixtures.KoreanImePolicyTests()
        record = fixture.record()
        record['events'] = []
        record['imeMessageDiagnostics'] = {'status': 'complete', 'events': [{'message': 0x102, 'wparam': ord('g')}]}
        with self.assertRaisesRegex(AssertionError, 'composition messages are missing'):
            ime.validate_ime_evidence(record)


if __name__ == '__main__': unittest.main()
