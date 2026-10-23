"""Synthetic diagnostic transport checks; these do not qualify native Windows IME."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'suite/e2e/ime_input_witness.py'


def original_source():
    tree = ast.parse((ROOT / 'suite/e2e/korean_ime_smoke.py').read_text())
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'OBSERVER_SOURCE' for t in n.targets))


class InputWitnessTests(unittest.TestCase):
    def load(self):
        self.assertTrue(MODULE.is_file(), 'Diagnostic witness module has not been implemented')
        spec = importlib.util.spec_from_file_location('input_witness_under_test', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_injection_keeps_original_abi_commands_and_composition_predicate(self):
        api = self.load()
        source = original_source()
        generated, audit = api.instrument_source(source)
        self.assertNotEqual(generated, source)
        self.assertEqual(len(audit['replacements']), 3)
        self.assertTrue(all(row['count'] == 1 for row in audit['replacements']))
        self.assertEqual(api.remove_instrumentation(generated), source)
        self.assertIn('if (message!=WM_IME_STARTCOMPOSITION && message!=WM_IME_ENDCOMPOSITION && message!=WM_IME_COMPOSITION) return;', generated)
        self.assertIn('Event events[512]', generated)

    def test_source_drift_and_duplicate_anchors_fail_closed(self):
        api = self.load()
        for changed in (original_source() + '\n', original_source().replace('static void observe(', 'static void changed('), original_source() * 2):
            with self.subTest(length=len(changed)), self.assertRaises(AssertionError):
                api.instrument_source(changed)

    def test_native_payload_keeps_uint64_and_signed_lparam_exact(self):
        api = self.load()
        payload = {'v': 1, 'w': '18446744073709551615', 'l': '-9223372036854775808',
                   'q': [1, '9223372036854775807', 1, '10000000'], 'h': '18446744073709551615',
                   'i': [4294967295, 0, 4294967295, 1, 0, 8, 4294967295, 1, 4294967295]}
        row = dict(sequence=9, message=0x100, flags=0, pid=7, tid=8, hwnd=19, layout=68289554,
                   origin='posted', composition=json.dumps(payload, separators=(',', ':')), result='')
        composition, witnesses = api.partition_events([row])
        self.assertEqual(composition, [])
        self.assertEqual(witnesses[0]['wParam'], 18446744073709551615)
        self.assertEqual(witnesses[0]['lParam'], -9223372036854775808)
        self.assertEqual(witnesses[0]['nativeSequence'], 9)
        self.assertEqual(witnesses[0]['imm']['open'], 0)
        self.assertEqual(witnesses[0]['scope'], 'WH_GETMESSAGE-PM_REMOVE-before-CallNextHookEx')

    def test_filter_preserves_composition_sequence_gaps_and_duplicate_origins(self):
        api = self.load()
        payload = json.dumps({'v': 1, 'w': '103', 'l': '0', 'q': [1, '3', 1, '4'],
                              'h': '0', 'i': [5, None, None, None, None, None, None, None, None]}, separators=(',', ':'))
        first = dict(sequence=1, message=0x100, origin='posted', composition=payload, result='')
        ime = dict(sequence=2, message=0x10f, origin='sent', composition='ㅎ', result='')
        duplicate = dict(first, sequence=3, origin='sent')
        rows = [first, ime, duplicate]
        kept, witness = api.partition_events(rows)
        self.assertIs(kept[0], ime)
        self.assertEqual(kept[0]['sequence'], 2)
        self.assertEqual([x['nativeSequence'] for x in witness], [1, 3])
        self.assertEqual([x['origin'] for x in witness], ['posted', 'sent'])

    def test_malformed_unbounded_or_failed_api_payload_is_not_success_fallback(self):
        api = self.load()
        payload = {'v': 1, 'w': '0', 'l': '0', 'q': [0, '0', 0, '0'], 'h': '12',
                   'i': [9, 0, 10, 0, None, None, 11, 0, 12]}
        row = dict(sequence=1, message=0x102, origin='sent', composition=json.dumps(payload), result='')
        _, values = api.partition_events([row])
        self.assertEqual(values[0]['imm']['conversionSucceeded'], 0)
        self.assertIsNone(values[0]['imm']['conversion'])
        self.assertEqual(values[0]['imm']['releaseSucceeded'], 0)
        for bad in ('x' * 256, '{}', json.dumps(dict(payload, w='-1'))):
            with self.subTest(bad=bad[:10]), self.assertRaises((AssertionError, ValueError)):
                api.partition_events([dict(row, composition=bad)])

    def test_final_report_cannot_certify_success_or_privacy(self):
        api = self.load()
        original = {'success': True, 'imeVerified': True, 'tests': [{'success': True}]}
        snapshot = copy.deepcopy(original)
        result = api.diagnostic_report(original)
        self.assertEqual(original, snapshot)
        self.assertFalse(result['success'])
        self.assertFalse(result['imeVerified'])
        self.assertFalse(result['officeReplacementCertified'])
        self.assertFalse(result['mainNativePrivacySetupPerformed'])
        self.assertNotIn('nativePrivacySetupPerformed', result)
        self.assertTrue(result['diagnosticPreparationSeparatelyRecorded'])
        self.assertEqual(result['diagnosticPreparationEvidence'], '.work/suite-input-witness-preparation/')
        self.assertTrue(result['productionCaseOutcomeObserved'])

    def test_harness_restores_production_globals_and_keeps_original_exception(self):
        api = self.load()
        class Observer:
            def events(self): return []
        production = SimpleNamespace(OBSERVER_SOURCE=original_source(), CompositionObserver=Observer)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'fresh'
            def main(argv):
                output.mkdir()
                raise RuntimeError('original case failure')
            production.main = main
            with self.assertRaisesRegex(RuntimeError, 'original case failure'):
                api.run_diagnostic(production, [], output, {'head': 'a' * 40})
            self.assertIs(production.CompositionObserver, Observer)
            self.assertEqual(production.OBSERVER_SOURCE, original_source())
            result = json.loads((output / 'input-witness-diagnostic.json').read_text())
            self.assertIn('original case failure', result['error'])
            self.assertFalse(result['success'])

    def test_malformed_partial_report_cannot_replace_original_case_error(self):
        api = self.load()
        class Observer:
            def events(self): return []
        production = SimpleNamespace(OBSERVER_SOURCE=original_source(), CompositionObserver=Observer)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'fresh'
            def main(argv):
                output.mkdir()
                (output / 'results.json').write_text('{partial')
                raise RuntimeError('original native failure')
            production.main = main
            with self.assertRaisesRegex(RuntimeError, 'original native failure'):
                api.run_diagnostic(production, [], output, {})
            self.assertIs(production.CompositionObserver, Observer)

    def test_unhosted_or_wrong_workflow_cannot_start_diagnostic(self):
        api = self.load()
        with self.assertRaises(AssertionError):
            api.source_binding({}, ROOT)
        environment = dict(GITHUB_ACTIONS='true', RUNNER_OS='Windows', GITHUB_SHA='a' * 40,
            GITHUB_REF='refs/heads/main', GITHUB_WORKFLOW_REF='wrong', GITHUB_WORKFLOW='diagnostic',
            GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_JOB='windows-suite', GITHUB_REPOSITORY='ATLKR/OpenGeul')
        with self.assertRaises(AssertionError):
            api.source_binding(environment, ROOT)

    def test_rejected_existing_output_keeps_all_prior_evidence_bytes(self):
        api = self.load()
        class Observer:
            def events(self): return []
        production = SimpleNamespace(OBSERVER_SOURCE=original_source(), CompositionObserver=Observer)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            old = output / 'results.json'
            old.write_bytes(b'{"success":true,"oldEvidence":true}')
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            def main(argv): output.mkdir(exist_ok=False)
            production.main = main
            with self.assertRaises((AssertionError, FileExistsError)):
                api.run_diagnostic(production, [], output, {})
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)

    def test_repeated_close_preserves_first_overflow_snapshot(self):
        api = self.load()
        class State:
            count, overflow = 513, 1
            snapshotEvidence = {'stable': True}
            def __bytes__(self): return b'first raw failed snapshot'
        class Observer:
            def __init__(self, *args, **kwargs): self.mapping, self.dll = object(), object()
            def state(self): return State()
            def events(self): raise AssertionError('Native composition receipt buffer overflowed')
            def close(self): self.mapping = None
        production = SimpleNamespace(CompositionObserver=Observer)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            observer = api._observer_class(production)(None, 1, 2, 3, 4, folder, {})
            with self.assertRaisesRegex(AssertionError, 'overflowed'): observer.close()
            path = folder / 'input-witness.json'
            first = path.read_bytes()
            observer.close()
            self.assertEqual(path.read_bytes(), first)
            self.assertEqual(json.loads(first)['beforeUnhookNativeSnapshot']['overflow'], 1)

    def test_portable_native_getters_restore_entry_error_across_all_exit_paths(self):
        api = self.load()
        prefix = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
using HWND=uint64_t; using HIMC=uint64_t; using WPARAM=uint64_t; using LPARAM=int64_t;
using DWORD=uint32_t; using UINT=uint32_t; using UINT_PTR=uint64_t; using LONG=int32_t; using WCHAR=uint16_t;
struct LARGE_INTEGER { int64_t QuadPart; };
constexpr UINT WM_KEYDOWN=0x100,WM_KEYUP=0x101,WM_CHAR=0x102,WM_INPUTLANGCHANGE=0x51,WM_IME_SETCONTEXT=0x281;
struct Event { uint32_t sequence,message,flags,pid,tid;uint64_t hwnd,layout;int32_t compositionBytes,resultBytes;uint32_t origin;WCHAR composition[256],result[256]; };
struct State { uint32_t pid=7,tid=8;volatile LONG count=0,overflow=0;Event events[512]{}; };
static State state; static State* shared=&state; static int scenario=0,calls=0,restores=0;
static DWORD lastError=0;
DWORD GetLastError(){return lastError;}
void SetLastError(DWORD value){lastError=value;++restores;}
DWORD GetWindowThreadProcessId(HWND,DWORD* p){lastError=11;*p=scenario==4?99:7;return scenario==5?9:8;}
DWORD GetCurrentThreadId(){lastError=12;return 8;} uint64_t GetKeyboardLayout(int){lastError=13;return 68289554;}
int QueryPerformanceCounter(LARGE_INTEGER* p){lastError=14;p->QuadPart=9223372036854775807LL;return scenario==6?INT32_MIN:1;}
int QueryPerformanceFrequency(LARGE_INTEGER* p){lastError=15;p->QuadPart=scenario==6?INT64_MAX:10000000;return scenario==6?INT32_MIN:1;}
HIMC ImmGetContext(HWND){++calls;lastError=scenario==6?UINT32_MAX:101;return scenario==1?0:18446744073709551615ULL;}
int ImmGetOpenStatus(HIMC){++calls;lastError=scenario==6?UINT32_MAX:102;return scenario==6?INT32_MIN:0;}
int ImmGetConversionStatus(HIMC,DWORD* c,DWORD* s){++calls;lastError=scenario==6?UINT32_MAX:103;*c=4294967295U;*s=scenario==6?UINT32_MAX:8;return scenario==6?INT32_MIN:scenario==2?0:1;}
int ImmReleaseContext(HWND,HIMC){++calls;lastError=scenario==6?UINT32_MAX:104;return scenario==6?INT32_MIN:scenario==3?0:1;}
LONG InterlockedIncrement(volatile LONG* p){return ++*p;} LONG InterlockedExchange(volatile LONG* p,LONG x){LONG old=*p;*p=x;return old;}
void MemoryBarrier(){}
'''
        suffix = r'''
int main(){
 static_assert(sizeof(Event)==1080,"Event ABI changed");
 for(scenario=0;scenario<4;++scenario){state.count=0;state.overflow=0;calls=0;restores=0;lastError=0xf123abcdU+scenario;
  const DWORD entry=lastError;
  if(!input_witness_message(WM_KEYDOWN))return 2;
  input_witness(19,WM_KEYDOWN,18446744073709551615ULL,INT64_MIN,2);
  auto &e=state.events[0];if(e.sequence!=1||e.compositionBytes>=512||e.resultBytes!=0)return 3;
  char text[256]{};for(int i=0;i<e.compositionBytes/2;++i)text[i]=char(e.composition[i]);puts(text);
  if(calls!=(scenario==1?1:4))return 4;
  if(GetLastError()!=entry||restores!=1)return 6;
 }
 for(scenario=4;scenario<=5;++scenario){state.count=0;calls=0;restores=0;lastError=0x81234567U;
  input_witness(19,WM_CHAR,0,0,1);
  if(state.count||calls||GetLastError()!=0x81234567U||restores!=1)return 7;
 }
 scenario=0;state.count=512;state.overflow=0;calls=0;restores=0;lastError=0xffffffffU;
 input_witness(19,WM_CHAR,0,0,1);
 if(!state.overflow||calls||GetLastError()!=0xffffffffU||restores!=1)return 5;
 scenario=6;state.count=0;state.overflow=0;state.events[0].sequence=0;restores=0;lastError=0x76543210U;
 input_witness(19,WM_KEYDOWN,UINT64_MAX,INT64_MIN,2);
 if(!state.overflow||state.events[0].sequence||GetLastError()!=0x76543210U||restores!=1)return 8;
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            cpp, exe = Path(tmp) / 'witness.cpp', Path(tmp) / 'witness'
            cpp.write_text(prefix + api.NATIVE_WITNESS_SOURCE + suffix)
            built = subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            rows = [json.loads(line) for line in ran.stdout.splitlines()]
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]['w'], '18446744073709551615')
            self.assertEqual(rows[0]['l'], '-9223372036854775808')
            self.assertEqual(rows[0]['i'], [101, 0, 102, 1, 4294967295, 8, 103, 1, 104])
            self.assertEqual(rows[1]['h'], '0')
            self.assertEqual(rows[1]['i'][1:], [None] * 8)
            self.assertEqual(rows[2]['i'][3:6], [0, None, None])
            self.assertEqual(rows[3]['i'][7], 0)
            self.assertTrue(all(len(line.encode('utf-16-le')) < 512 for line in ran.stdout.splitlines()))


if __name__ == '__main__': unittest.main()
