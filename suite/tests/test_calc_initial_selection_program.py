"""Ordinary Calc initial observation is separate from every strict input phase."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
import weakref
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
api = importlib.import_module('writer_model_reader')
PROGRAM = 'calc-a1-b1-c1-d1-pending-initial-selection-v2'
CONTAINER = 'com.sun.star.sheet.XSheetCellRangeContainer'


class Proxy:
    def __init__(self, **methods): self.__dict__.update(methods)


def area(column=0, row=0):
    return NS(Sheet=0, StartColumn=column, StartRow=row, EndColumn=column, EndRow=row)


def program_observation(row,sequence):
    """Run the real typed getter leaf, then bind its synthetic process fixture."""
    selected=Proxy(getRangeAddress=lambda:area())
    if sequence==0:
        selected=Proxy(getTypes=lambda:(NS(typeName=CONTAINER),),getCount=lambda:2,
                       getByIndex=lambda i:Proxy(getRangeAddress=lambda:area(i+3,i+4)))
    controller=Proxy(getSelection=lambda:selected)
    clock=lambda:(row['readStartedAt']+row['readFinishedAt'])/2
    function=api.read_calc_initial_selection if sequence==0 else api.read_calc_selection
    value=function(controller,deadline=12.,proxy_type=Proxy,clock=clock)
    proof=value['shapeWitness'];identity=row['unoSnapshots']['before']['proxyIdentity']
    proof.update(helperPid=row['readerProcess']['pid'],controllerId=identity['retainedIds']['controller'])
    for key in ('proxyTypeId','proxyTypeName','proxyTypeModule'):proof[key]=identity[key]
    for call in proof['calls']:
        if isinstance(call['result'],dict) and 'typeId' in call['result']:call['result']['typeId']=identity['proxyTypeId']
    contract=api._CALC_PENDING_INITIAL_CONTRACT
    row.update(kind=contract.kind,operations=list(contract.operations),
               calcSelectionPhase=dict(program=PROGRAM,requestAction='start' if sequence==0 else 'read',
                                       requestSequence=sequence,phase='initial' if sequence==0 else 'strict'))
    if sequence==0:
        row.pop('calcSelection',None);row['calcInitialSelection']=value
    else:row['calcSelection']=value
    return row


class InitialSelectionProgramTests(unittest.TestCase):
    def fixture(self, *, count=2, scalar=False):
        self.calls=[]; self.now=1.; self.capture={}; self.refs=[]
        def child(index):
            self.calls.append(('index', index))
            value=Proxy(getRangeAddress=lambda:self.calls.append(('address', index)) or area(index+3,index+5))
            self.refs.append(weakref.ref(value)); return value
        self.selected=Proxy(getTypes=lambda:self.calls.append('types') or (NS(typeName=CONTAINER),),
                            getCount=lambda:self.calls.append('count') or count, getByIndex=child)
        if scalar:self.selected.getRangeAddress=lambda:self.calls.append('scalar') or area(7,8)
        self.controller=Proxy(getSelection=lambda:self.calls.append('selection') or self.selected)

    def read(self):
        function=getattr(api,'read_calc_initial_selection',None)
        self.assertTrue(callable(function),'Initial read must measure a bounded collection without a single-range input claim')
        return function(self.controller,deadline=10.,clock=lambda:self.now,proxy_type=Proxy,capture=self.capture)

    def test_two_initial_ranges_are_fully_observed_in_order_but_old_strict_reader_still_rejects(self):
        self.fixture(); value=self.read()
        self.assertEqual(self.calls,['selection','types','count',('index',0),('address',0),('index',1),('address',1),'count'])
        self.assertEqual([r['startColumn'] for r in value['ranges']],[3,4])
        self.assertEqual(value['shapeWitness']['preCount'],2)
        self.assertEqual(value['shapeWitness']['postCount'],2)
        self.assertNotIn('range',value)
        self.assertEqual(self.capture,{})
        self.assertTrue(all(ref() is None for ref in self.refs))
        self.calls.clear()
        with self.assertRaises(AssertionError):
            api.read_calc_selection(self.controller,deadline=10.,clock=lambda:self.now,proxy_type=Proxy)
        self.assertEqual(self.calls,['selection','types','count'])

    def test_initial_scalar_is_a_bounded_rectangle_without_an_a1_claim(self):
        self.fixture(scalar=True);value=self.read()
        self.assertEqual(self.calls,['selection','scalar'])
        self.assertEqual(value['ranges'][0]['startRow'],8)
        self.assertEqual(value['shapeWitness']['shape'],'addressable-range')

    def test_invalid_initial_counts_never_fetch_a_first_element_and_actual_fact_is_retained(self):
        self.assertTrue(callable(getattr(api,'read_calc_initial_selection',None)))
        for count in (0,65,True,2.,'2',-1):
            with self.subTest(count=count):
                self.fixture(count=count)
                with self.assertRaises(AssertionError):self.read()
                self.assertEqual(self.calls,['selection','types','count'])
                self.assertEqual(self.capture['shapeWitness']['rawCounts'][0]['raw']['type'],type(count).__name__)

    def test_changed_postcount_and_invoked_scalar_errors_are_not_accepted(self):
        self.assertTrue(callable(getattr(api,'read_calc_initial_selection',None)))
        self.fixture();counts=iter([2,3]);self.selected.getCount=lambda:next(counts)
        with self.assertRaises(AssertionError):self.read()
        self.assertEqual([x['raw']['value'] for x in self.capture['shapeWitness']['rawCounts']],[2,3])
        self.fixture(scalar=True);error=AttributeError('existing scalar getter failed')
        self.selected.getRangeAddress=lambda:(_ for _ in ()).throw(error)
        with self.assertRaises(AttributeError) as caught:self.read()
        self.assertIs(caught.exception,error);self.assertEqual(self.calls,['selection'])

    def test_initial_proof_requires_all_ordered_entries_and_unmodified_typed_facts(self):
        self.fixture();value=self.read();validate=getattr(api,'_require_calc_initial_selection',None)
        self.assertTrue(callable(validate))
        self.assertIs(validate(value),value)
        for mutate in (lambda p:p['entries'].reverse(),lambda p:p.update(postCount=1),
                       lambda p:p['entries'][0]['rawAddress']['sheet'].update(value=False),
                       lambda p:p['calls'].reverse(),lambda p:p.update(finishedAt=10.)):
            changed=copy.deepcopy(value);mutate(changed['shapeWitness'])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):validate(changed)

    def test_original_deadline_stops_late_index_before_address_and_releases_transient_proxy(self):
        self.fixture();original=self.selected.getByIndex
        def late(index):
            value=original(index);self.now=10.;return value
        self.selected.getByIndex=late
        with self.assertRaises(TimeoutError):self.read()
        self.assertNotIn(('address',0),self.calls)
        self.assertTrue(all(ref() is None for ref in self.refs))

    def test_initial_known_interface_and_exact_child_type_are_required_before_address_reads(self):
        self.fixture();self.selected.getTypes=lambda:(NS(typeName='com.sun.star.container.XIndexAccess'),)
        with self.assertRaises(AttributeError):self.read()
        self.assertEqual(self.calls,['selection'])
        self.fixture();self.selected.getByIndex=lambda index:NS(getRangeAddress=lambda:self.fail('Foreign proxy getter ran'))
        with self.assertRaises(AssertionError):self.read()
        self.assertEqual(self.capture['shapeWitness']['entries'][0]['address'],None)

    def test_initial_invalid_address_keeps_raw_facts_and_api_errors_keep_identity(self):
        self.assertTrue(callable(getattr(api,'read_calc_initial_selection',None)))
        self.fixture();bad=area();bad.Sheet=True
        self.selected.getByIndex=lambda index:Proxy(getRangeAddress=lambda:bad)
        with self.assertRaises(AssertionError):self.read()
        entry=self.capture['shapeWitness']['entries'][0]
        self.assertEqual(len(entry['rawAddress']),5)
        self.assertEqual(entry['rawAddress']['sheet'],dict(type='bool',value=True))
        self.fixture();error=OSError('original indexed getter error')
        self.selected.getByIndex=lambda index:(_ for _ in ()).throw(error)
        with self.assertRaises(OSError) as caught:self.read()
        self.assertIs(caught.exception,error)

    def test_initial_original_intent_deadline_and_finite_proof_cap_fail_closed(self):
        self.assertTrue(callable(getattr(api,'read_calc_initial_selection',None)))
        self.fixture();ticks=iter([1.,1.,10.])
        with self.assertRaises(TimeoutError):
            api.read_calc_initial_selection(self.controller,deadline=10.,clock=lambda:next(ticks,10.),
                proxy_type=Proxy,capture=self.capture)
        self.assertEqual(self.calls,[])
        self.fixture(count=64);value=self.read()
        self.assertEqual(len(value['ranges']),64)
        self.assertLessEqual(len(json.dumps(value['shapeWitness'],ensure_ascii=False).encode()),65536)
        self.fixture(count=64)
        self.selected.getTypes=lambda:tuple(NS(typeName=n) for n in [CONTAINER]+['x'*256]*63)
        with self.assertRaisesRegex(AssertionError,'finite byte bound'):self.read()
        self.assertFalse(self.capture['shapeWitness']['complete'])

    def test_phase_is_source_program_and_exact_rpc_action_sequence_not_a_receipt_opt_in(self):
        validate=getattr(api,'require_calc_pending_program_phase',None)
        self.assertTrue(callable(validate),'New program needs an exact issued-RPC phase contract')
        before={'calcSelectionPhase':dict(program=PROGRAM,requestAction='start',requestSequence=0,phase='initial')}
        validate(before,expected_action='start',expected_sequence=0,expected_phase='initial')
        after={'calcSelectionPhase':dict(program=PROGRAM,requestAction='read',requestSequence=1,phase='strict')}
        validate(after,expected_action='read',expected_sequence=1,expected_phase='strict')
        for mutate in (lambda p:p.update(phase='initial'),lambda p:p.update(requestAction='start'),
                       lambda p:p.update(requestSequence=0),lambda p:p.update(requestSequence=True),
                       lambda p:p.update(program=api.CALC_PENDING_GETTER_CONTRACT)):
            changed=copy.deepcopy(after);mutate(changed['calcSelectionPhase'])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):
                validate(changed,expected_action='read',expected_sequence=1,expected_phase='strict')


class ProgramTransportTests(unittest.TestCase):
    def test_real_helper_dispatches_only_start_zero_initial_and_later_read_strict(self):
        import test_writer_model_reader as fixtures
        fixture=fixtures.ExplicitOwnedModelContracts()
        uno,events,objects=fixture.make_calc_uno();kind=type(objects['controller']);old_getattr=kind.__getattr__
        def get(obj,name):
            try:return old_getattr(obj,name)
            except KeyError:raise AttributeError(name)
        kind.__getattr__=get
        selected=kind('selection');selected.getTypes=lambda:(NS(typeName=CONTAINER),)
        selected.getCount=lambda:2
        children=[]
        for index in range(2):
            child=kind('range'+str(index));child.getRangeAddress=lambda i=index:area(i+3,i+4);children.append(child)
        selected.getByIndex=lambda index:children[index]
        scalar=kind('scalar');scalar.getRangeAddress=lambda:area()
        selections=iter((selected,scalar));objects['controller'].getSelection=lambda:next(selections)
        anchor=NS(base={'privatePipe':'OpenGeul_'+'a'*32},snapshot=lambda:{'native':'retained'},
                  profile=NS(snapshot=lambda:None),close=lambda:[])
        style=NS(observe_packaged_python=lambda:{},require_packaged_python=lambda *args:{'observed':{}})
        for raw_sequence in (0,False):
            with self.subTest(raw_sequence=raw_sequence),tempfile.TemporaryDirectory() as directory, \
                 patch.dict(sys.modules,{'uno':uno,'writer_style_smoke':style}), \
                 patch.object(api,'_native_anchor',lambda config:anchor),patch.object(api,'_qpc',lambda:(100,1000)), \
                 patch.object(api.time,'monotonic',lambda:1.), \
                 patch('calc_pending_input.AccessiblePendingReader',return_value=NS(read=lambda:{'measured':'pending-buffer'},release=lambda:None)):
                output=Path(directory)
                api._atomic_json(output/'configuration.json',dict(suite='C:/Suite',child_hwnd=22,expected_url='file:///C:/owned.xlsx',
                    readerDeadline=10.,expected_service=api.CALC_MODEL_SERVICE,getter_contract=PROGRAM))
                actions=('start','read','release') if type(raw_sequence) is int else ('start','release')
                for seq,action in enumerate(actions):
                    api._atomic_json(output/f'request-{seq:03d}.json',dict(sequence=raw_sequence if seq==0 else seq,action=action))
                self.assertEqual(api._helper(output,explicit_model=True),0)
                first=api._read_json(output/'reply-000.json')
                if type(raw_sequence) is bool:
                    self.assertFalse(first['ok']);continue
                self.assertTrue(first['ok']);before=first['observation']
                self.assertIn('calcInitialSelection',before)
                self.assertEqual(len(before['calcInitialSelection']['ranges']),2)
                self.assertNotIn('calcSelection',before)
                after=api._read_json(output/'reply-001.json')['observation']
                self.assertNotIn('calcInitialSelection',after)
                self.assertTrue(all(n==0 for n in after['calcSelection']['range'].values()))
                self.assertEqual(before['calcSelectionPhase']['requestSequence'],0)
                self.assertEqual(after['calcSelectionPhase']['requestSequence'],1)
                self.assertEqual(before['unoSnapshots']['before']['proxyIdentity'],after['unoSnapshots']['after']['proxyIdentity'])

    def test_parent_real_rpc_rejects_forged_nested_phase_or_boolean_envelope_before_identity_acceptance(self):
        for raw_sequence,nested in [(0,dict(program=PROGRAM,requestAction='read',requestSequence=1,phase='strict')),
                                    (False,dict(program=PROGRAM,requestAction='start',requestSequence=0,phase='initial'))]:
            with self.subTest(raw_sequence=raw_sequence),tempfile.TemporaryDirectory() as directory:
                output=Path(directory);seen=[]
                reader=api.OwnedModelReader(Path('C:/Suite'),output,expected_service=api.CALC_MODEL_SERVICE,
                    getter_contract=PROGRAM,shell_pid=77,expected_shell_creation=111,suite_hwnd=11,parent_hwnd=12,
                    child_hwnd=22,office_pid=88,expected_url='file:///C:/owned.xlsx',clock=lambda:1.)
                reader.anchor=NS(snapshot=lambda:{});reader.deadline=10.;reader.process=NS(poll=lambda:None)
                reader._member_snapshots=lambda **kwargs:[]
                def identity(*args):seen.append('identity');raise AssertionError('identity reached before source-RPC phase was joined')
                reply=dict(sequence=raw_sequence,action='start',readerPid=99,ok=True,
                           observation=dict(calcSelectionPhase=nested,pythonIdentity={'observed':{}}))
                api._atomic_json(output/'reply-000.json',reply)
                with patch.dict(sys.modules,{'writer_style_smoke':NS(require_packaged_python=identity)}),self.assertRaises(AssertionError):
                    reader._read(10.,'start')
                self.assertEqual(seen,[])
                self.assertIsNone(reader.last_observation)
                self.assertFalse((output/'observation-000.json').exists())

    def test_ordinary_alias_and_cancel_factory_cleanup_keep_distinct_source_contracts(self):
        import calc_save_smoke as save
        import calc_close_probe as close
        self.assertEqual(save.PENDING_GETTERS,PROGRAM)
        for folder,expected in [('before-close-reader',PROGRAM),('after-cancel-reader',api.CALC_PENDING_GETTER_CONTRACT)]:
            case=object.__new__(close.CalcCloseCase);case.suite=Path('C:/Suite');case.output=Path('C:/out')
            case.process=NS(pid=77);case.creation=111;case.hwnd=11;case.parent=12;case.child=22;case.office_pid=88
            case.source=Path('/owned.xlsx');case.observer_never_started=True;seen=[]
            fake=NS(start=lambda deadline:{'start':True},close=lambda deadline:{'closed':True})
            def make(*args,**kwargs):seen.append(('factory',kwargs['getter_contract']));return fake
            def clean(*args,**kwargs):seen.append(('cleanup',kwargs['getter_contract']))
            with patch.object(api,'OwnedModelReader',make),patch.object(api,'require_model_reader_cleanup',clean):
                case.start_reader(folder);case.close_reader({})
            self.assertEqual(seen,[('factory',expected),('cleanup',expected)])


if __name__=='__main__':unittest.main()
