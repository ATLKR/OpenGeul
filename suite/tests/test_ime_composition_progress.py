"""Numeric progress follows the original controlled IME case and physical keys."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime
import test_ime_case_phases as phase_tests


class IMECompositionProgressTests(unittest.TestCase):
    def original_case(self,module,*,fail_at=None,fail_semantic=None,retention=None,
                      cleanup_event_error=None,restoration_error=None,publication=False):
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
                def close(self,primary=None):
                    if retention is not None:retention.setdefault('keyboardPrimaries',[]).append(primary)
                    return super().close(primary)
            class Observer(observer_boundary):
                def diagnostics(self):
                    if publication:
                        retention['publicationAtDiagnostics']=copy.deepcopy(current['record'].get('imeCompositionPublication'))
                        self._pending_composition_publication['nativeCount']=901
                    if retention is None:return super().diagnostics()
                    snapshot=dict(schemaVersion=1,kind='passive-owned-ime-messages',status='complete',
                        capacity=128,observedCount=0,events=[])
                    retention.setdefault('captures',[]).append((list(self.commands),snapshot))
                    retention.setdefault('order',[]).append('snapshot')
                    return snapshot
                def command(self,command,**kwargs):
                    if retention is not None and command==4:
                        if publication:
                            retention['publicationAtRestore']=copy.deepcopy(current['record'].get('imeCompositionPublication'))
                            self._pending_composition_publication['nativeCount']=902
                        retention.setdefault('atRestore',[]).append(current['record'].get('imeMessageDiagnostics'))
                        retention.setdefault('order',[]).append('restore')
                    result=super().command(command,**kwargs)
                    if command==4 and restoration_error is not None:raise restoration_error
                    return result
                def events(self):
                    if getattr(self,'pending_failed',False) and cleanup_event_error is not None:
                        raise cleanup_event_error
                    result=super().events()
                    if publication:
                        self._composition_publication=dict(observed=1,nativeCount=0,overflow=0,firstSequence=0,
                            publishedPrefixCount=0,copyReturn=1,ackBefore=3,ackAfter=3,snapshotStable=1)
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
                    if publication:
                        self._pending_composition_publication=dict(observed=1,nativeCount=2,overflow=0,firstSequence=1,
                            publishedPrefixCount=1,copyReturn=1,ackBefore=3,ackAfter=3,snapshotStable=1)
                    if len(pending_rows)==fail_at:
                        self.pending_failed=True
                        return False
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

    def test_final_event_snapshot_failure_does_not_skip_original_restore(self):
        retention={}
        snapshot_error=RuntimeError('synthetic final event snapshot failure')
        calls,record,result,error,*_=self.original_case('writer',fail_at=1,retention=retention,
            cleanup_event_error=snapshot_error)
        self.assertIsInstance(error,AssertionError)
        self.assertIsNone(result)
        self.assertIs(retention['keyboardPrimaries'][0],error)
        self.assertEqual(calls.count(('command',4)),1)
        self.assertEqual(calls.count('observer-close'),1)
        self.assertEqual(calls.count('keyboard-close'),1)
        self.assertEqual(calls.count('retirement-close'),1)
        self.assertTrue(record['layoutRestored'])
        self.assertFalse(record['success'])
        self.assertEqual(record['imeCleanupError'],'RuntimeError: '+str(snapshot_error))
        self.assertNotIn('imeRestorationCleanupError',record)
        self.assertNotIn('CTRL_S',calls)
        self.assertEqual(calls.count(('physical',ime.EXPECTED_KEYS[0])),1)

    def test_restore_failure_remains_once_and_separate_from_snapshot_error(self):
        for snapshot_error in (None,RuntimeError('synthetic final event snapshot failure')):
            with self.subTest(snapshot_failed=snapshot_error is not None):
                retention={}
                restore_error=ValueError('synthetic restoration receipt failure')
                calls,record,result,error,*_=self.original_case('writer',fail_at=1,retention=retention,
                    cleanup_event_error=snapshot_error,restoration_error=restore_error)
                self.assertIsInstance(error,AssertionError)
                self.assertIsNone(result)
                self.assertIs(retention['keyboardPrimaries'][0],error)
                self.assertEqual(calls.count(('command',4)),1)
                self.assertEqual(calls.count('observer-close'),1)
                self.assertEqual(calls.count('keyboard-close'),1)
                self.assertEqual(calls.count('retirement-close'),1)
                self.assertFalse(record['success'])
                self.assertNotIn('layoutRestored',record)
                self.assertTrue('imeRestorationCleanupError' in record,'Missing restoration error classification')
                self.assertEqual(record['imeRestorationCleanupError'],'ValueError: '+str(restore_error))
                first=snapshot_error if snapshot_error is not None else restore_error
                self.assertEqual(record['imeCleanupError'],type(first).__name__+': '+str(first))
                self.assertNotIn('CTRL_S',calls)

    def test_case_freezes_last_pending_numbers_before_diagnostics_and_restore(self):
        for fail_at in (None,1):
            with self.subTest(pending_failed=fail_at is not None):
                retention={}
                calls,record,result,error,*_=self.original_case('writer',fail_at=fail_at,
                    retention=retention,publication=True)
                self.assertEqual(error is None,fail_at is None)
                value=record.get('imeCompositionPublication')
                self.assertIsInstance(value,dict,'missing numeric composition publication')
                self.assertEqual(value,dict(schemaVersion=1,frozen=1,
                    beforeFirstInput=dict(observed=1,nativeCount=0,overflow=0,firstSequence=0,
                        publishedPrefixCount=0,copyReturn=1,ackBefore=3,ackAfter=3,snapshotStable=1),
                    lastPending=dict(observed=1,nativeCount=2,overflow=0,firstSequence=1,
                        publishedPrefixCount=1,copyReturn=1,ackBefore=3,ackAfter=3,snapshotStable=1)))
                self.assertEqual(retention['publicationAtDiagnostics'],value)
                self.assertEqual(retention['publicationAtRestore'],value)
                self.assertEqual(calls.count(('command',4)),1)
                self.assertEqual(calls.count('observer-close'),1)


class IMECompositionPublicationTests(unittest.TestCase):
    def observer(self,count=0,sequences=(),*,overflow=0,stable=True,copy_return=1,metadata=True):
        state=ime.NativeState();state.count=count;state.overflow=overflow
        state.ack=3
        for index,sequence in enumerate(sequences):
            row=state.events[index];row.sequence=sequence;row.message=0x10f
            row.compositionBytes=2;row.composition[0]=120
        if metadata:
            state.snapshotEvidence=dict(copyReturn=copy_return,ackBefore=3,
                ackAfter=3 if stable else 4,stable=stable)
        observer=ime.CompositionObserver.__new__(ime.CompositionObserver);reads=[]
        def snapshot():reads.append(1);return state
        observer.state=snapshot
        return observer,state,reads

    def publication(self,observer,pending=False):
        name='_pending_composition_publication' if pending else '_composition_publication'
        row=getattr(observer,name,None)
        self.assertIsInstance(row,dict,'missing numeric composition publication')
        self.assertEqual(set(row),{'observed','nativeCount','overflow','firstSequence','publishedPrefixCount',
            'copyReturn','ackBefore','ackAfter','snapshotStable'})
        self.assertTrue(all(type(value) is int for value in row.values()))
        json.dumps(row)
        return row

    def test_zero_and_unpublished_or_mismatched_prefix_keep_distinct_native_counts(self):
        for count,sequences,prefix in [(0,(),0),(2,(0,0),0),(3,(1,0,0),1),(3,(7,0,0),0)]:
            with self.subTest(native_count=count,sequences=sequences):
                observer,state,reads=self.observer(count,sequences)
                events=observer.events();row=self.publication(observer)
                self.assertEqual(row,dict(observed=1,nativeCount=count,overflow=0,
                    firstSequence=sequences[0] if sequences else 0,publishedPrefixCount=prefix,
                    copyReturn=1,ackBefore=3,ackAfter=3,snapshotStable=1))
                self.assertEqual(len(events),prefix)
                self.assertEqual(reads,[1])
                if prefix:self.assertEqual(events[0]['composition'],'x')

    def test_unstable_ack_is_visible_without_changing_the_original_events(self):
        observer,state,reads=self.observer(1,(1,),stable=False,copy_return=2)
        result=observer.events();row=self.publication(observer)
        self.assertEqual((row['copyReturn'],row['ackBefore'],row['ackAfter'],row['snapshotStable']),
                         (2,3,4,0))
        self.assertEqual(len(result),1);self.assertEqual(result[0]['composition'],'x')
        self.assertEqual(reads,[1])

    def test_missing_copy_metadata_is_explicit_unknown_and_never_invents_zero(self):
        observer,state,reads=self.observer(2,(0,0),metadata=False)
        self.assertEqual(observer.events(),[]);row=self.publication(observer)
        self.assertEqual(row['nativeCount'],2)
        self.assertEqual([row[key] for key in ('copyReturn','ackBefore','ackAfter','snapshotStable')],[-1]*4)
        self.assertEqual(reads,[1])

    def test_overflow_preserves_the_original_failure_and_raw_header(self):
        observer,state,reads=self.observer(513,(1,),overflow=1)
        with self.assertRaises(AssertionError):observer.events()
        row=self.publication(observer)
        self.assertEqual((row['nativeCount'],row['overflow'],row['firstSequence'],row['publishedPrefixCount']),
                         (513,1,1,-1))
        self.assertEqual(reads,[1])

    def test_pending_uses_one_existing_snapshot_and_retains_its_value_after_later_reads(self):
        observer,state,reads=self.observer(1,(1,))
        self.assertTrue(observer.pending('x',0));first=dict(self.publication(observer,pending=True))
        state.count=2;state.events[0].sequence=0;observer.events()
        self.assertEqual(self.publication(observer,pending=True),first)
        self.assertEqual(first['nativeCount'],1);self.assertEqual(first['publishedPrefixCount'],1)
        self.assertEqual(reads,[1,1])

    def test_pending_failure_keeps_original_predicate_and_snapshot_gap(self):
        observer,state,reads=self.observer(2,(0,0))
        self.assertFalse(observer.pending('x',0));row=self.publication(observer,pending=True)
        self.assertEqual((row['nativeCount'],row['firstSequence'],row['publishedPrefixCount']),(2,0,0))
        self.assertEqual(reads,[1])
