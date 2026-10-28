"""Numeric progress follows the original controlled IME case and physical keys."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime
import test_ime_case_phases as phase_tests


class IMECompositionProgressTests(unittest.TestCase):
    def original_case(self,module,*,fail_at=None,fail_semantic=None,retention=None):
        harness=phase_tests.IMECasePhaseTests();self.addCleanup(harness.doCleanups)
        original=ime.case;trace=[];physical_rows=[];pending_rows=[]
        def run(*args,**kwargs):
            keyboard_boundary=ime.IMEKeyboardSession
            observer_boundary=ime.CompositionObserver
            physical_boundary=ime.physical_key
            current={}
            class Keyboard(keyboard_boundary):
                def __init__(self,*args,**kwargs):
                    super().__init__(*args,**kwargs);current['record']=self.record
            class Observer(observer_boundary):
                def diagnostics(self):
                    if retention is None:return super().diagnostics()
                    snapshot=dict(schemaVersion=1,kind='passive-owned-ime-messages',status='complete',
                        capacity=128,observedCount=0,events=[])
                    retention.setdefault('captures',[]).append((list(self.commands),snapshot))
                    retention.setdefault('order',[]).append('snapshot')
                    return snapshot
                def command(self,command,**kwargs):
                    if retention is not None and command==4:
                        retention.setdefault('atRestore',[]).append(current['record'].get('imeMessageDiagnostics'))
                        retention.setdefault('order',[]).append('restore')
                    return super().command(command,**kwargs)
                def events(self):
                    result=super().events()
                    if current['record'].get('stage')=='physical-dubeolsik-composition':
                        self.progress_event_reads=getattr(self,'progress_event_reads',0)+1
                        result=result[:self.progress_event_reads]
                        self.last_existing_event_count=len(result)
                        trace.append(('events',self.last_existing_event_count))
                    return result
                def pending(self,expected,after):
                    record=current['record']
                    pending_rows.append((record.get('imeCompositionOrdinal'),record.get('imeCompositionStartEventCount'),after))
                    trace.append(('pending',len(pending_rows)))
                    if len(pending_rows)==fail_at:return False
                    return super().pending(expected,after)
            def physical(observer,token,record):
                if record.get('stage')=='physical-dubeolsik-composition':
                    physical_rows.append((record.get('imeCompositionOrdinal'),record.get('imeCompositionStartEventCount'),observer.last_existing_event_count))
                    trace.append(('physical',len(physical_rows)))
                return physical_boundary(observer,token,record)
            with ExitStack() as stack:
                stack.enter_context(patch.object(ime,'IMEKeyboardSession',Keyboard))
                stack.enter_context(patch.object(ime,'CompositionObserver',Observer))
                stack.enter_context(patch.object(ime,'physical_key',side_effect=physical))
                return original(*args,**kwargs)
        with patch.object(ime,'case',side_effect=run):
            calls,record,result,error=harness.run_case(module,fail_semantic=fail_semantic)
        return calls,record,result,error,trace,physical_rows,pending_rows

    def test_all_original_keys_get_progress_before_input_and_pending_without_extra_reads(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                calls,record,result,error,trace,physical,pending=self.original_case(module)
                self.assertIsNone(error,repr(error))
                expected=[(n,n,n) for n in range(1,9)]
                self.assertEqual(physical,expected)
                self.assertEqual(pending,expected)
                self.assertEqual(trace,[entry for n in range(1,9) for entry in (('events',n),('physical',n),('pending',n))])
                self.assertEqual([row for row in calls if isinstance(row,tuple) and row[0]=='physical'],
                    [('physical',token) for token in ime.EXPECTED_KEYS])
                self.assertEqual(calls.count('CTRL_S'),1)
                self.assertEqual(calls.count('ENTER'),int(module=='calc'))
                self.assertIs(record['success'],True)
                self.assertIs(result,record)

    def test_original_pending_failure_keeps_exact_last_attempt_without_key_retry_or_save(self):
        for module in ('writer','impress'):
            for ordinal in (1,4,8):
                with self.subTest(module=module,ordinal=ordinal):
                    calls,record,result,error,trace,physical,pending=self.original_case(module,fail_at=ordinal)
                    self.assertIsInstance(error,AssertionError)
                    self.assertIsNone(result)
                    self.assertEqual(record['stage'],'physical-dubeolsik-composition')
                    self.assertEqual(record.get('imeCompositionOrdinal'),ordinal)
                    self.assertEqual(record.get('imeCompositionStartEventCount'),ordinal)
                    self.assertEqual(physical,[(n,n,n) for n in range(1,ordinal+1)])
                    self.assertEqual(pending,physical)
                    self.assertEqual(trace[:ordinal*3],[entry for n in range(1,ordinal+1) for entry in (('events',n),('physical',n),('pending',n))])
                    self.assertEqual([row for row in calls if isinstance(row,tuple) and row[0]=='physical'],
                        [('physical',token) for token in ime.EXPECTED_KEYS[:ordinal]])
                    self.assertNotIn('CTRL_S',calls)
                    self.assertNotIn('imeSaveBudget',record)

    def test_precomposition_failure_does_not_claim_any_input_progress(self):
        calls,record,result,error,trace,physical,pending=self.original_case('writer',fail_semantic='pre')
        self.assertIsInstance(error,RuntimeError)
        self.assertNotIn('imeCompositionOrdinal',record)
        self.assertNotIn('imeCompositionStartEventCount',record)
        self.assertEqual((trace,physical,pending),([],[],[]))

    def test_original_success_and_pending_failure_retain_first_snapshot_before_restoration(self):
        for fail_at in (None,4):
            with self.subTest(fail_at=fail_at):
                retention={}
                calls,record,result,error,*_=self.original_case('writer',fail_at=fail_at,retention=retention)
                if fail_at is None:self.assertIsNone(error,repr(error))
                else:self.assertIsInstance(error,AssertionError)
                self.assertEqual(retention['order'],['snapshot','restore'])
                self.assertEqual(len(retention['captures']),1)
                commands,snapshot=retention['captures'][0]
                self.assertEqual([row['command'] for row in commands],[1,2,3])
                self.assertEqual(len(retention['atRestore']),1)
                self.assertIs(retention['atRestore'][0],snapshot)
                self.assertIs(record['imeMessageDiagnostics'],snapshot)
                self.assertEqual(calls.count(('command',4)),1)
