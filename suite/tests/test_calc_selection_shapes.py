"""Documented UNO shape contracts; synthetic proxies are not native proof."""
import copy
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
import weakref

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
api=importlib.import_module('writer_model_reader')
RANGES='com.sun.star.sheet.XSheetCellRanges'
CONTAINER='com.sun.star.sheet.XSheetCellRangeContainer'


class Proxy:
    def __init__(self,**methods):self.__dict__.update(methods)


def area(column=0,row=0):
    return NS(Sheet=0,StartColumn=column,StartRow=row,EndColumn=column,EndRow=row)


class SelectionShapeTests(unittest.TestCase):
    def fixture(self,*,names=(CONTAINER,),count=1,address=None,scalar=False):
        self.calls=[];self.capture={};self.now=1.
        selected=Proxy();child=Proxy(getRangeAddress=lambda:self.calls.append('address') or (address or area()))
        selected.getTypes=lambda:self.calls.append('types') or tuple(NS(typeName=n) for n in names)
        selected.getCount=lambda:self.calls.append('count') or count
        selected.getByIndex=lambda i:self.calls.append(('index',i)) or child
        if scalar:selected.getRangeAddress=child.getRangeAddress
        self.selected=selected;self.child=child
        self.controller=Proxy(getSelection=lambda:self.calls.append('selection') or selected)
        return selected
    def read(self,*,deadline_clock=None):
        return api.read_calc_selection(self.controller,deadline=10.,clock=lambda:self.now,
            proxy_type=Proxy,capture=self.capture,deadline_clock=deadline_clock)
    def test_documented_container_reads_sole_range_with_proof(self):
        self.fixture()
        try:value=self.read()
        except (AttributeError,TypeError) as exc:self.fail('Documented sole-range container is unsupported: '+str(exc))
        self.assertEqual(self.calls,['selection','types','count',('index',0),'address','count'])
        self.assertIs(api.require_calc_a1_selection(value),value)
        proof=value['shapeWitness'];self.assertEqual(proof['shape'],'cell-range-container')
        self.assertEqual((proof['preCount'],proof['postCount'],proof['index']),(1,1,0))
        self.assertEqual(proof['readerDeadline'],10.);self.assertEqual(proof['address'],value['range'])
        self.assertEqual(self.capture,{})
    def test_original_tick_budget_is_separate_from_qpc_witness_times(self):
        self.fixture()
        value=api.read_calc_selection(self.controller,deadline=101.,clock=lambda:200.,
            deadline_clock=lambda:100.,proxy_type=Proxy,capture=self.capture)
        proof=value['shapeWitness']
        self.assertEqual(proof['readerDeadline'],101.)
        self.assertEqual((proof['startedAt'],proof['finishedAt']),(200.,200.))
        self.assertEqual(proof['budget'],dict(kind=1,startedAt=100.,finishedAt=100.))
        self.assertEqual(proof['schemaVersion'],2)
        api._require_calc_selection(value)
    def test_expired_tick_budget_starts_no_getter_even_with_earlier_qpc(self):
        self.fixture()
        with self.assertRaises(TimeoutError):
            api.read_calc_selection(self.controller,deadline=101.,clock=lambda:99.,
                deadline_clock=lambda:101.,proxy_type=Proxy,capture=self.capture)
        self.assertEqual(self.calls,[])
    def test_generic_container_keeps_a_valid_non_a1_rectangle(self):
        self.fixture(address=area(5,5));value=self.read()
        self.assertIs(api._require_calc_selection(value),value)
        with self.assertRaises(AssertionError):api.require_calc_a1_selection(value)
    def test_base_interface_and_duplicate_metadata_are_preserved(self):
        self.fixture(names=(RANGES,'com.sun.star.lang.XTypeProvider','com.sun.star.lang.XTypeProvider'))
        value=self.read();self.assertEqual(len(value['shapeWitness']['interfaceNames']),3)
    def test_scalar_fast_path_never_queries_collection_and_always_proves_shape(self):
        self.fixture(scalar=True,address=area(5,5));value=self.read()
        self.assertEqual(self.calls,['selection','address'])
        self.assertEqual(value['shapeWitness']['shape'],'addressable-range')
        self.assertIsNone(value['shapeWitness']['preCount'])
        self.assertIs(api._require_calc_selection(value),value)
    def test_existing_scalar_getter_attribute_error_is_not_fallback(self):
        self.fixture(scalar=True);error=AttributeError('inside existing getter')
        self.selected.getRangeAddress=lambda:(_ for _ in ()).throw(error)
        with self.assertRaises(AttributeError) as caught:self.read()
        self.assertIs(caught.exception,error);self.assertEqual(self.calls,['selection'])
    def test_unsupported_interface_does_not_duck_type_index_access(self):
        self.fixture(names=('com.sun.star.container.XIndexAccess',))
        with self.assertRaises(AttributeError):self.read()
        self.assertEqual(self.calls,['selection','types'])
    def test_zero_many_boolean_and_invalid_counts_never_fetch_first(self):
        for count in (0,2,33,True,1.,'1',-1):
            with self.subTest(count=count):
                self.fixture(count=count)
                with self.assertRaises(AssertionError):self.read()
                self.assertEqual(self.calls,['selection','types','count'])
                attempt=self.capture['shapeWitness'];raw=attempt['rawCounts'][0]['raw']
                self.assertEqual(raw['type'],type(count).__name__);self.assertEqual(raw['value'],count)
                json.dumps(attempt,allow_nan=False)
    def test_changed_postcount_is_fatal_and_both_returns_are_captured(self):
        self.fixture();counts=iter([1,2]);self.selected.getCount=lambda:next(counts)
        with self.assertRaises(AssertionError):self.read()
        self.assertEqual([r['raw']['value'] for r in self.capture['shapeWitness']['rawCounts']],[1,2])
    def test_malformed_address_is_captured_before_validation(self):
        for field,bad in [('Sheet',True),('StartColumn',-1),('EndRow',float('nan'))]:
            with self.subTest(field=field):
                address=area();setattr(address,field,bad);self.fixture(address=address)
                with self.assertRaises(AssertionError):self.read()
                self.assertEqual(len(self.capture['shapeWitness']['rawAddress']),5)
                json.dumps(self.capture['shapeWitness'],allow_nan=False)
    def test_reverse_bounds_and_foreign_sheet_fail_their_strict_contracts(self):
        address=area();address.StartColumn=2;self.fixture(address=address)
        with self.assertRaises(AssertionError):self.read()
        address=area();address.Sheet=1;self.fixture(address=address);value=self.read()
        with self.assertRaises(AssertionError):api.require_calc_a1_selection(value)
    def test_foreign_child_proxy_is_rejected_before_address_getter(self):
        self.fixture();self.selected.getByIndex=lambda i:NS(getRangeAddress=lambda:self.fail('foreign address getter'))
        with self.assertRaises(AssertionError):self.read()
    def test_expired_deadline_starts_no_remote_getter(self):
        self.fixture();self.now=10.
        with self.assertRaises(TimeoutError):self.read()
        self.assertEqual(self.calls,[])
    def test_late_count_return_is_captured_without_starting_next_getter(self):
        self.fixture()
        def count():self.calls.append('count');self.now=10.;return 1
        self.selected.getCount=count
        with self.assertRaises(TimeoutError):self.read()
        self.assertEqual(self.calls,['selection','types','count'])
        self.assertEqual(self.capture['shapeWitness']['preCount'],1)
    def test_shape_witness_tampering_never_satisfies_pure_validation(self):
        self.fixture();value=self.read()
        mutations=[lambda p:p.update(shape='anything'),lambda p:p.update(preCount=True),
            lambda p:p.update(postCount=2),lambda p:p.update(index=1),
            lambda p:p.update(interfaceNames=['com.sun.star.container.XIndexAccess']),
            lambda p:p.update(controllerId=True),lambda p:p['budget'].update(finishedAt=11.),
            lambda p:p.update(schemaVersion=1),lambda p:p.pop('budget'),
            lambda p:p['budget'].update(kind=True),lambda p:p['budget'].update(startedAt=2.),
            lambda p:p['address'].update(endRow=1),lambda p:p['calls'].reverse(),
            lambda p:p['calls'][2].update(returnedAt=.5),
            lambda p:p['rawAddress']['sheet'].update(type='bool')]
        for mutate in mutations:
            changed=copy.deepcopy(value);mutate(changed['shapeWitness'])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):api._require_calc_selection(changed)
    def test_legacy_scalar_receipt_remains_valid_without_new_proof(self):
        value=dict(readOnly=True,source='retained-controller.getSelection',
            range=dict(sheet=0,startColumn=5,startRow=5,endColumn=5,endRow=5))
        self.assertIs(api._require_calc_selection(value),value)
    def test_boolean_or_float_raw_values_cannot_impersonate_integer_returns(self):
        self.fixture();value=self.read()
        for mutate in (lambda p:p['calls'][2]['result'].update(value=True),
                       lambda p:p['rawCounts'][0]['raw'].update(value=1.),
                       lambda p:p['rawAddress']['sheet'].update(value=False)):
            changed=copy.deepcopy(value);mutate(changed['shapeWitness'])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):api._require_calc_selection(changed)
    def test_owner_and_observation_time_are_independent_of_shape_validation(self):
        self.fixture();value=self.read();proof=value['shapeWitness']
        observation=dict(readerProcess=dict(pid=proof['helperPid']),readStartedAt=0.,readFinishedAt=2.,
            controllerQpc=dict(startedNs=800_000_000,finishedNs=1_200_000_000),
            helperQpc=dict(startedTicks=900,finishedTicks=1100,frequency=1000),
            unoSnapshots=dict(before=dict(proxyIdentity=dict(helperPid=proof['helperPid'],
                retainedIds=dict(controller=proof['controllerId']),proxyTypeId=proof['proxyTypeId'],
                proxyTypeName=proof['proxyTypeName'],proxyTypeModule=proof['proxyTypeModule']))))
        api._require_calc_selection_owner(value,observation)
        for mutate in (lambda p:p.update(helperPid=p['helperPid']+1),lambda p:p.update(controllerId=999),
                       lambda p:p.update(proxyTypeId=999),lambda p:p.update(proxyTypeName='foreign'),
                       lambda p:p.update(proxyTypeModule='foreign'),lambda p:p.update(startedAt=-1.)):
            changed=copy.deepcopy(value);mutate(changed['shapeWitness'])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):
                api._require_calc_selection_owner(changed,observation)
    def test_owned_qpc_read_survives_coarse_controller_monotonic_clock(self):
        self.fixture();self.now=1.005;value=self.read(deadline_clock=lambda:1.);proof=value['shapeWitness']
        observation=dict(readerProcess=dict(pid=proof['helperPid']),readStartedAt=1.,readFinishedAt=1.,
            controllerQpc=dict(startedNs=1_000_000_000,finishedNs=1_010_000_000),
            helperQpc=dict(startedTicks=1002,finishedTicks=1008,frequency=1000),
            unoSnapshots=dict(before=dict(proxyIdentity=dict(helperPid=proof['helperPid'],
                retainedIds=dict(controller=proof['controllerId']),proxyTypeId=proof['proxyTypeId'],
                proxyTypeName=proof['proxyTypeName'],proxyTypeModule=proof['proxyTypeModule']))))
        api._require_calc_selection_owner(value,observation)
    def test_clock_windows_reject_stale_cross_request_or_malformed_evidence(self):
        self.fixture();self.now=1.005;value=self.read(deadline_clock=lambda:1.);proof=value['shapeWitness']
        original=dict(readerProcess=dict(pid=proof['helperPid']),readStartedAt=1.,readFinishedAt=1.,
            controllerQpc=dict(startedNs=1_000_000_000,finishedNs=1_010_000_000),
            helperQpc=dict(startedTicks=1002,finishedTicks=1008,frequency=1000),
            unoSnapshots=dict(before=dict(proxyIdentity=dict(helperPid=proof['helperPid'],
                retainedIds=dict(controller=proof['controllerId']),proxyTypeId=proof['proxyTypeId'],
                proxyTypeName=proof['proxyTypeName'],proxyTypeModule=proof['proxyTypeModule']))))
        api._require_calc_selection_owner(value,original)
        changes=(
            lambda row:row.pop('controllerQpc'),lambda row:row.pop('helperQpc'),
            lambda row:row.update(readStartedAt=2.,readFinishedAt=1.),
            lambda row:row['controllerQpc'].update(startedNs=1_003_000_000),
            lambda row:row['controllerQpc'].update(finishedNs=1_007_000_000),
            lambda row:row['controllerQpc'].update(startedNs=2_000_000_000,finishedNs=2_010_000_000),
            lambda row:row['controllerQpc'].update(startedNs=True),
            lambda row:row['controllerQpc'].update(finishedNs=1_010_000_000.),
            lambda row:row['controllerQpc'].update(finishedNs=2**63),
            lambda row:row['helperQpc'].update(startedTicks=1009),
            lambda row:row['helperQpc'].update(startedTicks=-1),
            lambda row:row['helperQpc'].update(frequency=0),
            lambda row:row['helperQpc'].update(frequency=True),
            lambda row:row['helperQpc'].update(frequency=100),
            lambda row:row['helperQpc'].update(extra=0))
        for change in changes:
            changed=copy.deepcopy(original);change(changed)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                api._require_calc_selection_owner(value,changed)
        for start,finish in ((1.001,1.005),(1.005,1.009),(1.006,1.005)):
            changed=copy.deepcopy(value);changed['shapeWitness'].update(startedAt=start,finishedAt=finish)
            with self.subTest(start=start,finish=finish),self.assertRaises(AssertionError):
                api._require_calc_selection_owner(changed,original)
        for budget in (dict(kind=True,startedAt=1.,finishedAt=1.),
                       dict(kind=2,startedAt=1.,finishedAt=1.),
                       dict(kind=1,startedAt=.999,finishedAt=1.),
                       dict(kind=1,startedAt=1.,finishedAt=1.001),
                       dict(kind=1,startedAt=1.001,finishedAt=1.),
                       dict(kind=1,startedAt=1.,finishedAt=10.)):
            changed=copy.deepcopy(value);changed['shapeWitness']['budget']=budget
            with self.subTest(budget=budget),self.assertRaises(AssertionError):
                api._require_calc_selection_owner(changed,original)
    def test_fractional_qpc_tick_uses_exact_cpython_nanosecond_conversion(self):
        self.fixture();self.now=float(10**9//3)/10**9;value=self.read(deadline_clock=lambda:0.);proof=value['shapeWitness']
        observation=dict(readerProcess=dict(pid=proof['helperPid']),readStartedAt=0.,readFinishedAt=0.,
            controllerQpc=dict(startedNs=333_333_333,finishedNs=333_333_333),
            helperQpc=dict(startedTicks=1,finishedTicks=1,frequency=3),
            unoSnapshots=dict(before=dict(proxyIdentity=dict(helperPid=proof['helperPid'],
                retainedIds=dict(controller=proof['controllerId']),proxyTypeId=proof['proxyTypeId'],
                proxyTypeName=proof['proxyTypeName'],proxyTypeModule=proof['proxyTypeModule']))))
        api._require_calc_selection_owner(value,observation)
        changed=copy.deepcopy(value);changed['shapeWitness']['finishedAt']=self.now+0.000000001
        with self.assertRaises(AssertionError):api._require_calc_selection_owner(changed,observation)
        self.now=1e-9;value=self.read(deadline_clock=lambda:0.)
        observation['controllerQpc']=dict(startedNs=1,finishedNs=1)
        observation['helperQpc']=dict(startedTicks=2,finishedTicks=3,frequency=2_000_000_000)
        api._require_calc_selection_owner(value,observation)
        # Both raw ticks floor to 1 ns; conversion must not hide reversed order.
        observation['helperQpc'].update(startedTicks=3,finishedTicks=2)
        with self.assertRaises(AssertionError):api._require_calc_selection_owner(value,observation)
    def test_container_getter_errors_are_preserved_without_retry(self):
        for method in ('getTypes','getCount','getByIndex'):
            with self.subTest(method=method):
                self.fixture();error=RuntimeError('actual '+method+' error');calls=[]
                def fail(*args):calls.append(args);raise error
                setattr(self.selected,method,fail)
                with self.assertRaises(RuntimeError) as caught:self.read()
                self.assertIs(caught.exception,error);self.assertEqual(len(calls),1)
                self.assertFalse(self.capture['shapeWitness']['complete'])
    def test_deadline_reached_while_recording_intent_starts_no_getter(self):
        self.fixture();ticks=iter([1.,1.,10.])
        with self.assertRaises(TimeoutError):
            api.read_calc_selection(self.controller,deadline=10.,clock=lambda:1.,deadline_clock=lambda:next(ticks,10.),
                proxy_type=Proxy,capture=self.capture)
        self.assertEqual(self.calls,[])
        self.assertIsNone(self.capture['shapeWitness']['calls'][0]['returnedAt'])
    def test_transient_child_is_released_even_while_postcount_error_is_retained(self):
        self.fixture();refs=[];reads=[0];original=RuntimeError('postcount API failure')
        def transient(index):
            child=Proxy(getRangeAddress=lambda:area());refs.append(weakref.ref(child));return child
        def count():
            reads[0]+=1
            if reads[0]==2:raise original
            return 1
        self.selected.getByIndex=transient;self.selected.getCount=count
        try:self.read()
        except RuntimeError as error:
            self.assertIs(error,original);self.assertIsNone(refs[0]())
        else:self.fail('Actual postcount error was not propagated')
    def test_late_index_return_retains_scalar_facts_without_retaining_child(self):
        self.fixture();refs=[]
        def transient(index):
            child=Proxy(getRangeAddress=lambda:area());refs.append(weakref.ref(child));self.now=10.;return child
        self.selected.getByIndex=transient
        try:self.read()
        except TimeoutError:
            self.assertIsNotNone(self.capture['shapeWitness']['childId'])
            self.assertIsNone(refs[0]())
        else:self.fail('Late indexed getter did not preserve original deadline')


if __name__=='__main__':unittest.main()
