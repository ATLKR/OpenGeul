"""Failure-only diagnostics; fake UNO boundaries do not qualify an editor."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import weakref

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
api=importlib.import_module('writer_model_reader')
BASE='com.sun.star.sheet.XSheetCellRanges'
SUBTYPE='com.sun.star.sheet.XSheetCellRangeContainer'
SERVICE='com.sun.star.lang.XServiceInfo'


class Proxy:
    def __init__(self,count=2,names=(SUBTYPE,SERVICE)):
        self.count=count;self.names=names;self.calls=[];self.child=None
    def getTypes(self):
        self.calls.append('types');return tuple(NS(typeName=n) for n in self.names)
    def getImplementationName(self):self.calls.append('implementation');return 'ScCellRangesObj'
    def getSupportedServiceNames(self):self.calls.append('services');return ('com.sun.star.sheet.SheetCellRanges',)
    def getCount(self):self.calls.append('count');return self.count
    def getByIndex(self,index):
        self.calls.append(('index',index));child=Proxy();self.child=child
        child.getRangeAddress=lambda:NS(Sheet=0,StartColumn=index,StartRow=index,EndColumn=index,EndRow=index)
        return child
    def getRangeAddresses(self):raise AssertionError('Bulk range retrieval is forbidden')


class SelectionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.now=1.;self.events=[]
    def feature(self):
        self.assertTrue(callable(getattr(api,'_collect_calc_selection_diagnostic',None)),
            'Missing failure-only collector')
        self.assertTrue(callable(getattr(api,'_calc_selection_diagnostic_header',None)))
    def collect(self,selected=None,*,names=None,count=2,deadline=10.,pending=False):
        self.feature();selected=Proxy(count,names or (SUBTYPE,SERVICE)) if selected is None else selected
        controller=object();capture=dict(stage='getRangeAddress',selected=selected,controller=controller)
        reader=NS(proxy_type=Proxy,controller=controller,calc_selection_capture=capture,
            snapshot=lambda:self.events.append('uno') or {'retained':'original'})
        anchor=NS(snapshot=lambda:self.events.append('native') or {'generation':123456789012345678})
        error=dict(type='AttributeError',message='getRangeAddress',traceback='original traceback',
            unoSnapshot={'mutable':['original']},nativeSnapshot={'generation':123456789012345678})
        header=api._calc_selection_diagnostic_header(0,'start',reader,capture,deadline,error,clock=lambda:self.now)
        if pending:(self.directory/'request-001.json').write_text('{"sequence":1,"action":"release"}')
        state=api._collect_calc_selection_diagnostic(self.directory,reader,anchor,capture,header,clock=lambda:self.now)
        return state,selected,reader,capture,header
    def records(self):
        return [json.loads(p.read_bytes()) for p in sorted(self.directory.glob('selection-diagnostic-*.json'))]
    def test_subtype_and_base_use_indexed_addresses_and_never_bulk(self):
        for name in (SUBTYPE,BASE):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    self.directory=Path(directory)
                    state,selected,_,capture,header=self.collect(names=(name,SERVICE))
                    self.assertEqual(state['status'],'complete')
                    self.assertEqual(state['preCount'],2);self.assertEqual(state['postCount'],2)
                    self.assertEqual([r['index'] for r in state['indexedAddresses']],[0,1])
                    self.assertEqual(state['indexedAddresses'][1]['address']['startColumn'],1)
                    self.assertEqual(selected.calls,['types','implementation','services','count',('index',0),('index',1),'count'])
                    self.assertEqual(capture,{})
                    self.assertFalse(state['qualification']);self.assertEqual(header['status'],'not-started')
    def test_pending_release_starts_no_extra_getter_and_keeps_null_fields(self):
        state,selected,_,capture,_=self.collect(pending=True)
        self.assertEqual(selected.calls,[]);self.assertEqual(state['reason'],'pending-request')
        self.assertIsNone(state['preCount']);self.assertEqual(capture,{})
        self.assertTrue(self.records())
    def test_original_deadline_expired_starts_no_getter(self):
        self.now=10.;state,selected,_,capture,_=self.collect()
        self.assertEqual(selected.calls,[]);self.assertEqual(state['reason'],'deadline')
        self.assertEqual(capture,{})
    def test_pending_release_after_a_getter_yields_before_the_next(self):
        selected=Proxy()
        def types():
            selected.calls.append('types')
            (self.directory/'request-001.json').write_text('{"sequence":1,"action":"release"}')
            return (NS(typeName=SUBTYPE),)
        selected.getTypes=types
        state,_,_,capture,_=self.collect(selected)
        self.assertEqual(selected.calls,['types']);self.assertEqual(state['reason'],'pending-request')
        self.assertEqual(capture,{})
    def test_late_getter_preserves_returned_partial_and_original_deadline(self):
        selected=Proxy()
        def types():self.now=10.;return (NS(typeName=SUBTYPE),)
        selected.getTypes=types
        state,_,_,capture,_=self.collect(selected)
        self.assertEqual(state['reason'],'deadline');self.assertEqual(state['readerDeadline'],10.)
        self.assertEqual(state['interfaceNames'],[SUBTYPE]);self.assertEqual(capture,{})
        self.assertFalse(state['qualification'])
    def test_native_guard_failure_prevents_getter(self):
        self.feature();original=api._calc_selection_diagnostic_header
        with patch.object(api,'_calc_selection_diagnostic_header',side_effect=original):
            selected=Proxy();controller=object();capture=dict(stage='getRangeAddress',selected=selected,controller=controller)
            reader=NS(proxy_type=Proxy,controller=controller,snapshot=lambda:None)
            anchor=NS(snapshot=lambda:(_ for _ in ()).throw(RuntimeError('changed native owner')))
            header=original(0,'start',reader,capture,10.,{'type':'AttributeError','message':'getRangeAddress'},clock=lambda:self.now)
            state=api._collect_calc_selection_diagnostic(self.directory,reader,anchor,capture,header,clock=lambda:self.now)
        self.assertEqual(selected.calls,[]);self.assertIn('changed native owner',state['errors'][0]['message'])
        self.assertEqual(capture,{})
    def test_unknown_interface_cannot_duck_type_a_collection(self):
        state,selected,_,_,_=self.collect(names=('com.sun.star.container.XIndexAccess',))
        self.assertEqual(state['reason'],'unsupported-interfaces');self.assertEqual(selected.calls,['types'])
    def test_wrong_proxy_type_never_receives_remote_getter(self):
        class Foreign:
            def getTypes(self):raise AssertionError('Foreign proxy queried')
        state,_,_,capture,_=self.collect(Foreign())
        self.assertEqual(state['reason'],'proxy-type-mismatch');self.assertEqual(capture,{})
    def test_null_selection_is_explicitly_unavailable(self):
        self.feature();capture=dict(stage='selection',selected=None,controller=object())
        reader=NS(proxy_type=Proxy,controller=capture['controller']);header=api._calc_selection_diagnostic_header(
            0,'start',reader,capture,10.,{'type':'AssertionError','message':'no selection'},clock=lambda:self.now)
        state=api._collect_calc_selection_diagnostic(self.directory,reader,NS(snapshot=lambda:None),capture,header,clock=lambda:self.now)
        self.assertEqual(state['reason'],'no-selection');self.assertIsNone(state['selectedProxy'])
    def test_count_over_bound_never_fetches_a_partial_first_range(self):
        state,selected,_,_,_=self.collect(count=33)
        self.assertEqual(state['preCount'],33);self.assertEqual(state['indexedAddresses'],[])
        self.assertEqual(state['reason'],'range-count-bound');self.assertNotIn(('index',0),selected.calls)
    def test_zero_and_max_count_have_finite_scalar_call_counts(self):
        for count in (0,32):
            with self.subTest(count=count),tempfile.TemporaryDirectory() as directory:
                self.directory=Path(directory);state,_,_,_,_=self.collect(count=count)
                self.assertEqual(len(state['indexedAddresses']),count)
                self.assertLessEqual(len(state['calls']),69);self.assertLessEqual(len(self.records()),140)
                self.assertTrue(all(p.stat().st_size<=65536 for p in self.directory.glob('*.json')))
    def test_bool_float_string_and_negative_count_are_not_coerced(self):
        for count in (True,1.,'1',-1):
            with self.subTest(count=count),tempfile.TemporaryDirectory() as directory:
                self.directory=Path(directory);state,selected,_,_,_=self.collect(count=count)
                self.assertEqual(state['status'],'error');self.assertNotIn(('index',0),selected.calls)
                self.assertTrue(state['errors'])
    def test_child_address_scalar_types_are_strict_and_child_is_not_retained(self):
        for bad in (True,0.,'0',None):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as directory:
                self.directory=Path(directory);selected=Proxy(count=1)
                selected.getByIndex=lambda index:Proxy()
                original=selected.getByIndex
                def child(index):
                    value=original(index);value.getRangeAddress=lambda:NS(Sheet=bad,StartColumn=0,StartRow=0,EndColumn=0,EndRow=0)
                    return value
                selected.getByIndex=child
                state,_,_,capture,_=self.collect(selected)
                self.assertEqual(state['status'],'error');self.assertEqual(capture,{})
                self.assertFalse(any(isinstance(v,Proxy) for v in state.values()))
    def test_count_change_and_index_error_are_partial_not_retried(self):
        selected=Proxy(count=1);counts=iter([1,2]);selected.getCount=lambda:next(counts)
        state,_,_,_,_=self.collect(selected);self.assertEqual(state['reason'],'range-count-changed')
        with tempfile.TemporaryDirectory() as directory:
            self.directory=Path(directory);selected=Proxy()
            selected.getByIndex=lambda index:(_ for _ in ()).throw(IndexError('range disappeared'))
            state,_,_,capture,_=self.collect(selected)
            self.assertEqual(state['status'],'error');self.assertEqual(capture,{})
            self.assertIn('range disappeared',state['errors'][0]['message'])
    def test_sidecar_failure_starts_no_getter_and_does_not_escape(self):
        self.feature()
        with patch.object(api,'_atomic_json',side_effect=OSError('disk full')):
            state,selected,_,capture,_=self.collect()
        self.assertEqual(selected.calls,[]);self.assertEqual(capture,{})
        self.assertIn('disk full',state['errors'][0]['message'])
    def test_oversized_metadata_is_not_trimmed_into_a_supported_interface(self):
        selected=Proxy(names=(SUBTYPE,)*65)
        state,_,_,_,_=self.collect(selected)
        self.assertEqual(state['status'],'error');self.assertIsNone(state['interfaceNames'])
    def test_proxy_method_lookup_itself_occurs_only_after_native_guard(self):
        self.feature();guarded=[False]
        class GuardedProxy(Proxy):
            def __getattribute__(self,name):
                if name=='getTypes' and not guarded[0]:raise RuntimeError('PyUNO lookup preceded native guard')
                return super().__getattribute__(name)
        selected=GuardedProxy(count=0,names=(BASE,));controller=object()
        capture=dict(stage='getRangeAddress',selected=selected,controller=controller)
        reader=NS(proxy_type=GuardedProxy,controller=controller,snapshot=lambda:{})
        def native():guarded[0]=True;return {}
        header=api._calc_selection_diagnostic_header(0,'start',reader,capture,10.,{'type':'AttributeError'},clock=lambda:self.now)
        state=api._collect_calc_selection_diagnostic(self.directory,reader,NS(snapshot=native),capture,header,clock=lambda:self.now)
        self.assertEqual(state['status'],'complete');self.assertEqual(selected.calls,['types','count','count'])
    def test_invalid_large_nonfinite_and_huge_scalar_still_persist_bounded_terminal_evidence(self):
        for bad in ('x'*70000,float('nan'),2**4096):
            with self.subTest(kind=type(bad).__name__),tempfile.TemporaryDirectory() as directory:
                self.directory=Path(directory);selected=Proxy(count=1)
                def child(index):
                    p=Proxy();p.getRangeAddress=lambda:NS(Sheet=bad,StartColumn=0,StartRow=0,EndColumn=0,EndRow=0);return p
                selected.getByIndex=child
                state,_,_,capture,_=self.collect(selected)
                self.assertEqual(state['status'],'error');self.assertEqual(capture,{})
                raw=state['indexedAddresses'][0]['raw']['sheet']
                self.assertIsNone(raw['value']);self.assertTrue(raw.get('omitted'))
                self.assertEqual(self.records()[-1]['status'],'error')
                self.assertTrue(all(p.stat().st_size<=65536 for p in self.directory.glob('*.json')))
    def test_index_child_proxy_is_dropped_when_its_getter_raises(self):
        selected=Proxy(count=1);held=[]
        def child(index):
            value=Proxy();held.append(weakref.ref(value))
            value.getRangeAddress=lambda:(_ for _ in ()).throw(RuntimeError('address getter failed'))
            return value
        selected.getByIndex=child
        state,_,_,capture,_=self.collect(selected)
        self.assertEqual(state['status'],'error');self.assertEqual(capture,{})
        self.assertIsNone(held[0]())
    def test_intent_fsync_reaching_deadline_starts_no_getter(self):
        self.feature();original=api._atomic_json
        def publish(path,value):
            original(path,value)
            if value.get('calls'):self.now=10.
        with patch.object(api,'_atomic_json',side_effect=publish):
            state,selected,_,capture,_=self.collect()
        self.assertEqual(selected.calls,[]);self.assertEqual(state['reason'],'deadline')
        self.assertIsNone(state['calls'][0]['returnedAt']);self.assertEqual(capture,{})
    def test_intent_fsync_queuing_release_starts_no_getter(self):
        self.feature();original=api._atomic_json
        def publish(path,value):
            original(path,value)
            if value.get('calls'):
                request=self.directory/'request-001.json'
                if not request.exists():request.write_text('{"sequence":1,"action":"release"}')
        with patch.object(api,'_atomic_json',side_effect=publish):
            state,selected,_,capture,_=self.collect()
        self.assertEqual(selected.calls,[]);self.assertEqual(state['reason'],'pending-request')
        self.assertIsNone(state['calls'][0]['returnedAt']);self.assertEqual(capture,{})


class CaptureAndPublicationTests(unittest.TestCase):
    def feature(self):
        self.assertTrue(callable(getattr(api,'_collect_calc_selection_diagnostic',None)),
            'Missing capture/publication integration')
    def test_capture_uses_one_selection_and_original_getter_acceptance_unchanged(self):
        self.feature();calls=[];selected=NS(getRangeAddress=lambda:calls.append('range') or
            NS(Sheet=0,StartColumn=0,StartRow=0,EndColumn=0,EndRow=0))
        capture={};value=api.read_calc_selection(NS(getSelection=lambda:calls.append('selection') or selected),
            deadline=10.,clock=lambda:1.,capture=capture)
        self.assertEqual(calls,['selection','range']);self.assertEqual(capture,{})
        self.assertIs(api.require_calc_a1_selection(value),value)
    def test_original_missing_method_stays_fatal_with_same_proxy_capture(self):
        self.feature();selected=NS(calls=[]);capture={};calls=[]  # No positive spreadsheet collection interface.
        with self.assertRaises(AttributeError):api.read_calc_selection(NS(getSelection=lambda:calls.append(1) or selected),
            deadline=10.,clock=lambda:1.,capture=capture)
        self.assertEqual(calls,[1]);self.assertIs(capture['selected'],selected)
        self.assertEqual(selected.calls,[])
    def helper(self,*,publication_failure=False,header_failure=False,captured_attempt=None,immediate_release=False):
        self.feature();temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);directory=Path(temp.name)
        config={'expected_service':api.CALC_MODEL_SERVICE,'getter_contract':api.CALC_PENDING_GETTER_CONTRACT,'suite':str(directory),'readerDeadline':10.}
        (directory/'configuration.json').write_text(json.dumps(config));(directory/'request-000.json').write_text('{"sequence":0,"action":"start"}')
        mutable={'retained':['original']};events=[];holder={}
        class Reader:
            def __init__(self,*args,**kwargs):
                holder['reader']=self;self.controller=object();self.proxy_type=Proxy;self.last_snapshot=mutable
                self.calc_selection_capture={'stage':'getRangeAddress','selected':Proxy(),'controller':self.controller}
                if captured_attempt is not None:self.calc_selection_capture['shapeWitness']=captured_attempt
            def read(self):raise AttributeError('getRangeAddress')
            def release(self):events.append('release');self.calc_selection_capture.clear()
        anchor=NS(snapshot=lambda:{'native':'original'},last_snapshot={'native':'original'},profile=None,close=lambda:[])
        original=api._atomic_json
        def publish(path,value):
            if path.name=='reply-000.json':
                events.append('publish')
                holder['publishedObject']=value
                if publication_failure:raise OSError('primary publication failed')
            result=original(path,value)
            if path.name=='reply-000.json' and (header_failure or immediate_release):
                (directory/'request-001.json').write_text('{"sequence":1,"action":"release"}')
            return result
        def diagnostic(path,reader,native,capture,header,**kwargs):
            events.append('diagnostic');frozen=json.loads((directory/'reply-000.json').read_bytes())
            mutable['retained'].append('MUTATED')
            holder['frozen']=frozen;holder['header']=header
            (directory/'request-001.json').write_text('{"sequence":1,"action":"release"}')
            raise RuntimeError('secondary diagnostic failure')
        header_builder=api._calc_selection_diagnostic_header
        def header(*args,**kwargs):
            if header_failure:raise RuntimeError('diagnostic header preparation failed')
            return header_builder(*args,**kwargs)
        with patch.object(api,'_UnoReader',Reader),patch.object(api,'_native_anchor',return_value=anchor),\
             patch.object(api,'_calc_selection_diagnostic_header',side_effect=header),\
             patch.object(api,'_qpc',return_value=(1,1)),patch.object(api,'_atomic_json',side_effect=publish),\
             patch.object(api,'_collect_calc_selection_diagnostic',side_effect=diagnostic),\
             patch('writer_style_smoke.observe_packaged_python',return_value={}),\
             patch('writer_style_smoke.require_packaged_python',return_value={}):
            if publication_failure:
                with self.assertRaisesRegex(OSError,'primary publication failed'):api._helper(directory,explicit_model=True)
            else:
                try:result=api._helper(directory,explicit_model=True)
                except RuntimeError as exc:self.fail('Optional diagnostic header prevented primary publication: '+str(exc))
                self.assertEqual(result,0)
        return directory,events,holder
    def test_primary_reply_once_precedes_diagnostics_and_nested_snapshots_are_detached(self):
        directory,events,holder=self.helper()
        self.assertEqual(events,['publish','diagnostic','release'])
        self.assertEqual(holder['frozen']['error']['unoSnapshot'],{'retained':['original']})
        self.assertEqual(holder['publishedObject']['error']['unoSnapshot'],{'retained':['original']})
        self.assertFalse(holder['frozen']['ok']);self.assertEqual(holder['frozen']['error']['message'],'getRangeAddress')
        self.assertIn('calcSelectionDiagnostic',holder['frozen'])
        self.assertEqual(holder['reader'].calc_selection_capture,{})
        with self.assertRaises(api.ReaderBackendError):api._require_reply(json.loads((directory/'reply-000.json').read_bytes()),0,'start')
    def test_failed_primary_publication_starts_no_diagnostics(self):
        _,events,_=self.helper(publication_failure=True)
        self.assertEqual(events,['publish','release'])
    def test_parent_existing_primary_error_is_never_replaced_by_later_failure(self):
        self.feature();reader=api.OwnedWriterReader.__new__(api.OwnedWriterReader)
        primary={'type':'ReaderBackendError','message':'original'}
        reader.first_error=primary;reader.failed=False;reader.process=None;reader.forced=False
        reader._record_failure(RuntimeError('secondary diagnostic failure'))
        self.assertIs(reader.first_error,primary);self.assertEqual(primary['message'],'original')
    def test_header_preparation_error_cannot_prevent_original_failed_reply_and_release(self):
        directory,events,holder=self.helper(header_failure=True)
        self.assertEqual(events,['publish','release'])
        reply=json.loads((directory/'reply-000.json').read_bytes())
        self.assertFalse(reply['ok']);self.assertEqual(reply['error']['message'],'getRangeAddress')
        self.assertEqual(reply['calcSelectionDiagnostic']['reason'],'header-error')
        self.assertEqual(holder['reader'].calc_selection_capture,{})
    def test_returned_count_is_in_primary_and_header_before_immediate_release(self):
        from suite.tests.test_calc_selection_shapes import SelectionShapeTests
        fixture=SelectionShapeTests();fixture.fixture(count=2)
        with self.assertRaises(AssertionError):fixture.read()
        attempt=fixture.capture['shapeWitness']
        directory,events,holder=self.helper(captured_attempt=attempt,immediate_release=True)
        reply=json.loads((directory/'reply-000.json').read_bytes())
        frozen=reply['error']['calcSelectionAttempt']
        self.assertEqual(frozen['preCount'],2)
        self.assertEqual(frozen['rawCounts'][0]['raw'],dict(type='int',value=2))
        self.assertEqual(reply['calcSelectionDiagnostic']['selectionAttempt'],frozen)
        self.assertFalse(reply['ok']);self.assertEqual(events,['publish','diagnostic','release'])
        self.assertIsNone(frozen['index']);self.assertEqual(frozen['rawAddress'],{})
        self.assertEqual(holder['reader'].calc_selection_capture,{})


if __name__=='__main__':unittest.main()
