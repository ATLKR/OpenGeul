"""Owned context-handler intervals are diagnostic evidence, never acceptance."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from suite.tests.test_ime_mode_diagnostic import ime
from native_executable_cleanup import remove_completed_image


class ContextBoundaryTests(unittest.TestCase):
    def observer(self, origins=(1, 3)):
        observer = object.__new__(ime.CompositionObserver)
        state = ime.NativeState()
        observer.pid, observer.tid, observer.focus = 31, 41, 51
        observer.diagnose_ime_mode = True
        observer.mode_diagnostic_budget = (999, 1000)
        observer.state = lambda: state
        observer._read_mode_diagnostic = lambda i: (state.modeDiagnostics[i], state.diagnostics[i])
        state.modeDiagnosticVersion = state.modeDiagnosticEnabled = 1
        state.modeDiagnosticDeadline, state.modeDiagnosticFrequency = 999, 1000
        state.diagnosticCount = len(origins)
        for i, origin in enumerate(origins):
            event, mode = state.diagnostics[i], state.modeDiagnostics[i]
            event.sequence = mode.sequence = mode.messageSequence = i + 1
            event.message, event.origin = 0x490, origin
            event.pid, event.tid, event.hwnd = 31, 41, 51
            event.counter = 10 + i * 10
            mode.startedCounter, mode.finishedCounter = event.counter + 1, event.counter + 2
            event.immContextPresent = event.immConversionSucceeded = 1
            mode.mode.beforeOpenType = mode.mode.beforeConversionType = 3
            mode.mode.referencesAcquired = mode.mode.referencesReleased = 5
            mode.mode.releaseCalls = 1
        return observer, state

    def test_pairs_original_entry_and_return_without_acceptance_claim(self):
        observer, state = self.observer()
        state.diagnostics[0].immOpen = state.modeDiagnostics[0].mode.beforeOpen = 1
        result = observer.mode_diagnostics()
        self.assertIn('contextBoundaries', result)
        boundary = result['contextBoundaries']
        self.assertEqual(boundary['status'], 'complete')
        self.assertEqual(boundary['pairs'][0]['entrySequence'], 1)
        self.assertEqual(boundary['pairs'][0]['returnSequence'], 2)
        self.assertTrue(boundary['pairs'][0]['eligible'])
        self.assertFalse(boundary['causalAttributionProved'])

    def test_nested_pending_orphan_and_expired_intervals_are_inconclusive(self):
        for origins in ((1, 1, 3, 3), (1,), (3,)):
            observer, _ = self.observer(origins)
            result = observer.mode_diagnostics()
            self.assertIn('contextBoundaries', result)
            self.assertNotEqual(result['contextBoundaries']['status'], 'complete')
            self.assertFalse(any(p['eligible'] for p in result['contextBoundaries']['pairs']))
        observer, state = self.observer()
        state.modeDiagnostics[1].finishedCounter = 1000
        result = observer.mode_diagnostics()
        self.assertIn('contextBoundaries', result)
        self.assertFalse(result['contextBoundaries']['pairs'][0]['eligible'])

    def test_payload_and_return_origin_are_rejected_outside_exact_opt_in_boundary(self):
        observer, state = self.observer()
        self.assertEqual(observer.diagnostics()['status'], 'complete')
        for field, value in (('lparam', 1234), ('wparam', 1), ('message', 0x100)):
            with self.subTest(field=field):
                old = getattr(state.diagnostics[1], field)
                setattr(state.diagnostics[1], field, value)
                with self.assertRaises(AssertionError): observer.diagnostics()
                with self.assertRaises(AssertionError): observer.mode_diagnostics()
                setattr(state.diagnostics[1], field, old)
        observer.diagnose_ime_mode = False
        with self.assertRaises(AssertionError): observer.diagnostics()

    def test_untyped_reentrant_expired_rejected_and_partial_snapshots_cannot_qualify(self):
        for field, value in (('status', -40), ('beforeOpenType', 0), ('cleanupStatus', -1),
                             ('referencesReleased', 4), ('openSetCalls', 1)):
            observer, state = self.observer()
            setattr(state.modeDiagnostics[1].mode, field, value)
            self.assertFalse(observer.mode_diagnostics()['contextBoundaries']['pairs'][0]['eligible'])
        for field in ('contextBoundaryExpired', 'contextBoundaryRejected', 'diagnosticOverflow'):
            observer, state = self.observer()
            setattr(state, field, 1)
            result = observer.mode_diagnostics()['contextBoundaries']
            self.assertEqual(result['status'], 'inconclusive')
            self.assertFalse(result['pairs'][0]['eligible'])
        observer, state = self.observer()
        observer._read_mode_diagnostic = lambda i: None if i else (state.modeDiagnostics[0], state.diagnostics[0])
        result = observer.mode_diagnostics()['contextBoundaries']
        self.assertEqual(result['pendingEntries'], [1])
        self.assertEqual(result['publication'], 'partial')

    def test_normal_observer_keeps_two_hooks_and_original_budget(self):
        observer, _ = self.observer()
        observer.diagnose_ime_mode = False
        callback = ctypes.CFUNCTYPE(ctypes.c_int)(lambda: 0)
        observer.dll = SimpleNamespace(_handle=7, HookCall=callback, HookGet=callback)
        installed, released = [], []
        observer.api = SimpleNamespace(user=SimpleNamespace(
            SetWindowsHookExW=lambda kind, *_: installed.append(kind) or kind + 100,
            UnhookWindowsHookEx=lambda handle: released.append(handle) or True))
        observer.hooks = []
        observer.mapping = None
        with patch.object(ime, 'remaining_setup') as remaining:
            observer._install_hooks(50)
            self.assertEqual([call.args for call in remaining.call_args_list], [(50, 60)] * 3)
        observer.close()
        self.assertEqual(installed, [4, 3])
        self.assertEqual(released, [103, 104])

    def test_actual_return_hook_ignores_other_messages_and_redacts_payload(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if compiler is None: self.skipTest('Portable compiler unavailable')
        source = ime.OBSERVER_SOURCE
        hook = source[source.index('extern "C" __declspec(dllexport) LRESULT CALLBACK HookReturn('):
                      source.index('extern "C" __declspec(dllexport) unsigned int ReadModeDiagnostic(')]
        prefix = r'''
#include <cstdint>
#include <cassert>
#ifdef __declspec
#undef __declspec
#endif
#define __declspec(x)
#define CALLBACK
using LRESULT=intptr_t;using WPARAM=uintptr_t;using LPARAM=intptr_t;using HWND=uintptr_t;
struct CWPRETSTRUCT {LRESULT lResult;LPARAM lParam;WPARAM wParam;unsigned message;HWND hwnd;};
int reads=0,chains=0,connections=0;bool connected=true;
bool connect(){++connections;return connected;}
void observe_diagnostic(HWND h,unsigned m,WPARAM w,LPARAM l,unsigned o){
 ++reads;assert(h==51 && m==0x490 && w==0 && l==0 && o==3);
}
LRESULT CallNextHookEx(void*,int,WPARAM,LPARAM){++chains;return 71;}
'''
        main = r'''
int main(){
 CWPRETSTRUCT m{123,456,789,0x100,51};
 assert(HookReturn(0,0,reinterpret_cast<LPARAM>(&m))==71 && reads==0 && connections==0);
 m.message=0x490;
 HookReturn(-1,0,reinterpret_cast<LPARAM>(&m));HookReturn(0,0,0);
 assert(reads==0 && connections==0);
 connected=false;HookReturn(0,0,reinterpret_cast<LPARAM>(&m));assert(reads==0);
 connected=true;HookReturn(0,0,reinterpret_cast<LPARAM>(&m));
 assert(reads==1 && connections==2 && chains==5);
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cpp = root / 'return.cpp'; exe = root / ('return.exe' if os.name == 'nt' else 'return')
            cpp.write_text(prefix + hook + main)
            build = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-D__declspec(x)=__attribute__((visibility("default")))', str(cpp), '-o', str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5)
            try: self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            finally: remove_completed_image(root, exe, run)

    def test_optional_return_hook_failure_releases_previously_installed_hooks(self):
        observer, _ = self.observer()
        self.assertTrue(hasattr(observer, '_install_hooks'))
        callback = ctypes.CFUNCTYPE(ctypes.c_int)(lambda: 0)
        observer.dll = SimpleNamespace(_handle=7, HookCall=callback, HookGet=callback, HookReturn=callback)
        installed, released, closed = [], [], []
        def install(kind, address, dll, tid):
            installed.append(kind)
            if kind == 12: raise OSError('controlled hook installation failure')
            return kind + 100
        observer.api = SimpleNamespace(user=SimpleNamespace(
            SetWindowsHookExW=install, UnhookWindowsHookEx=lambda handle: released.append(handle) or True))
        observer.hooks = []
        observer.mapping = SimpleNamespace(close=lambda: closed.append(True))
        with patch.object(ime, 'remaining_setup'):
            with self.assertRaises(OSError): observer._install_hooks(50)
        self.assertEqual(installed, [4, 3, 12])
        self.assertEqual(released, [103, 104])
        self.assertEqual(closed, [True])


if __name__ == '__main__': unittest.main()
