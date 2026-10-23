"""Returned-value discovery diagnostics; synthetic trees are not actual proof."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_ime_semantic_context as fixtures
from test_calc_pending_input import Accessible


COMPONENT_FACTS = {'frameController','controllerFrame','modelController','controllerModel',
    'containerPeer','containerAccessible','componentPeer','componentDistinct',
    'properContainerChild','componentAccessible'}


class ImpressDiscoveryDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SemanticGetterTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.api=self.fixture.api

    def tree(self,child_hwnd=456):
        frame,paragraph,shape,document,uno=self.fixture.impress()
        peer=frame.getContainerWindow();peer.getWindowHandle=lambda *args:child_hwnd
        root=frame.getComponentWindow().getProperty('XAccessible')
        controller=frame.getController();model=controller.getModel()
        patcher=patch.dict(sys.modules,uno=uno);patcher.start();self.addCleanup(patcher.stop)
        reader=self.api.EditingContextReader('impress',frame,controller,model,child_hwnd,
            deadline=10.,clock=lambda:self.fixture.now)
        return reader,root,document

    def depth_failure(self,child_hwnd=456):
        reader,root,_=self.tree(child_hwnd)
        unknown=Accessible(49,rectangle=(0,0,0,0))
        unknown.getAccessibleContext=lambda:self.fail('Over-depth node was queried')
        node=unknown
        for _ in range(8):node=Accessible(49,children=[node],rectangle=(0,0,0,0))
        root.set_children([node])
        return reader

    def scope(self,value,child_hwnd=456):
        self.assertEqual(value['rootBasis'],'original-frame-current-component-window')
        state=fixtures.STATES['SHOWING']|fixtures.STATES['VISIBLE']
        self.assertEqual(value['root'],dict(role=40,stateBits=state,rectangle=[0,0,100,100]))
        binding=value['componentBinding']
        self.assertEqual(set(binding),{'containerRoot','before'})
        self.assertEqual(binding['containerRoot'],dict(role=49,stateBits=state,rectangle=[0,0,100,100]))
        checks=binding['before'];self.assertEqual(set(checks),COMPONENT_FACTS|{'containerHwnd'})
        for key in COMPONENT_FACTS:self.assertIs(checks[key],True)
        self.assertIs(type(checks['containerHwnd']),int);self.assertEqual(checks['containerHwnd'],child_hwnd)
        self.assertEqual(value['componentBindingAfter'],'not-reached')
        self.assertIs(type(value['failedDepth']),int)
        self.assertEqual(value['failedDepth'],len(value['failedPath']))

    def diagnostic(self,reader):
        with self.assertRaises(AssertionError) as raised:reader.read()
        self.assertEqual(str(raised.exception),'Accessible discovery exceeded fixed bound')
        value=getattr(raised.exception,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict)
        self.assertLessEqual(len(json.dumps(value,allow_nan=False).encode('utf-8')),32768)
        self.assertFalse(value['qualification']);self.scope(value,reader.child_hwnd)
        return raised.exception,value

    def test_depth_failure_is_component_relative_and_retains_only_returned_ancestors(self):
        reader=self.depth_failure()
        def clock():
            self.assertIsNone(sys.exc_info()[0],'Failure projection sampled the clock')
            return 1.
        reader.clock=clock
        _,value=self.diagnostic(reader)
        self.assertEqual(value['failedPath'],[0]*9);self.assertEqual(value['failedDepth'],9)
        self.assertEqual(value['failedCaps'],['depth'])
        self.assertEqual(value['limits'],dict(visits=256,depth=8,children=64))
        self.assertEqual(value['visitedCount'],10);self.assertEqual(value['returnedHeaderCount'],9)
        self.assertEqual([row['path'] for row in value['ancestors']],[[]]+[[0]*n for n in range(1,9)])
        self.assertEqual(value['ancestors'][0]['role'],40)
        self.assertEqual(value['ancestors'][-1]['role'],49)
        self.assertEqual(value['ancestors'][-1]['childCount'],1)
        self.assertTrue(all(type(row['stateBits']) is int and row['visible']==fixtures.STATES['VISIBLE']
            for row in value['ancestors']))
        failed=value['failedNode'];self.assertFalse(failed['headerReturned'])
        for key in ('role','stateBits','visible','childCount'):self.assertIsNone(failed[key])
        self.assertFalse(failed['childCountReturned'])

    def test_visit_limit_retains_bounded_tail_and_original_257th_unqueried_path(self):
        reader,root,_=self.tree()
        root.set_children([Accessible(49,children=[Accessible(1) for _ in range(63)],
            rectangle=(0,0,0,0)) for _ in range(4)])
        root.children[3].children[62].getAccessibleContext=lambda:self.fail('Over-visit node was queried')
        _,value=self.diagnostic(reader)
        self.assertEqual(value['failedCaps'],['visits'])
        self.assertEqual(value['visitedCount'],257);self.assertEqual(value['returnedHeaderCount'],256)
        self.assertEqual(value['failedPath'],[3,62]);self.assertEqual(value['failedDepth'],2)
        self.assertEqual([row['path'] for row in value['ancestors']],[[],[3]])
        self.assertLessEqual(len(value['returnedNodes']),16);self.assertTrue(value['returnedNodesTruncated'])
        self.assertEqual([row['path'] for row in value['returnedNodes']],[[3,index] for index in range(46,62)])
        self.assertEqual([row['visit'] for row in value['returnedNodes']],list(range(241,257)))
        self.assertFalse(value['failedNode']['headerReturned'])

    def test_returned_child_count_bound_is_retained_without_querying_children(self):
        reader,root,_=self.tree();root.getAccessibleChildCount=lambda:65
        root.getAccessibleChild=lambda *_:self.fail('Over-count child was queried')
        with self.assertRaises(AssertionError) as raised:reader.read()
        value=getattr(raised.exception,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict);self.scope(value)
        self.assertEqual(value['failedCaps'],['children']);self.assertEqual(value['failedPath'],[])
        self.assertEqual(value['failedNode']['childCount'],65)
        self.assertTrue(value['failedNode']['headerReturned']);self.assertTrue(value['failedNode']['childCountReturned'])

    def test_header_getter_failure_does_not_invent_a_partial_returned_header(self):
        reader,root,_=self.tree();primary=RuntimeError('original state getter failed');calls=[];failed=[]
        original=root.getAccessibleStateSet
        def state():
            calls.append(True)
            if len(calls)==2:failed.append(True);raise primary
            return original()
        root.getAccessibleStateSet=state
        def clock():
            self.assertFalse(failed,'Failure projection sampled the clock')
            return 1.
        reader.clock=clock
        with self.assertRaises(RuntimeError) as raised:reader.read()
        self.assertIs(raised.exception,primary)
        value=getattr(primary,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict);self.scope(value)
        self.assertEqual(value['stage'],'node-header');self.assertEqual(value['returnedHeaderCount'],0)
        self.assertEqual(value['ancestors'],[]);self.assertEqual(value['returnedNodes'],[])
        self.assertFalse(value['failedNode']['headerReturned'])
        for key in ('role','stateBits','visible','childCount'):self.assertIsNone(value['failedNode'][key])

    def test_count_and_child_getter_failures_preserve_primary_without_failure_queries(self):
        for stage in ('child-count-getter','child-getter'):
            with self.subTest(stage=stage):
                reader,root,_=self.tree();primary=RuntimeError('original '+stage);failed=[]
                def fail(*args):failed.append(True);raise primary
                if stage=='child-count-getter':root.getAccessibleChildCount=fail
                else:root.getAccessibleChild=fail
                def clock():
                    self.assertFalse(failed,'Failure projection sampled the clock')
                    return 1.
                reader.clock=clock
                with self.assertRaises(RuntimeError) as raised:reader.read()
                self.assertIs(raised.exception,primary)
                value=getattr(primary,'impress_discovery_diagnostic',None)
                self.assertIsInstance(value,dict);self.scope(value)
                self.assertEqual(value['stage'],stage);self.assertEqual(value['failedCaps'],[])
                self.assertIsNone(value['failedNode']['childCount'])
                self.assertFalse(value['failedNode']['childCountReturned'])
                self.assertEqual(value['failedPath'],[] if stage=='child-count-getter' else [0])
                self.assertEqual(value['failedNode']['headerReturned'],stage=='child-count-getter')

    def test_unprintable_serialization_or_attachment_failure_never_replaces_original(self):
        class SecondaryError(RuntimeError):
            def __str__(self):raise AssertionError('Secondary error must not be formatted')
        class LockedError(RuntimeError):
            def __setattr__(self,name,value):
                if name=='impress_discovery_diagnostic':raise SecondaryError()
                super().__setattr__(name,value)
        for failure in ('serialize','attach'):
            with self.subTest(failure=failure):
                reader,root,_=self.tree()
                primary=RuntimeError('original') if failure=='serialize' else LockedError('original')
                def count():raise primary
                root.getAccessibleChildCount=count
                context=patch.object(self.api.json,'dumps',side_effect=SecondaryError()) if failure=='serialize' else patch.object(self.api,'SOURCE',self.api.SOURCE)
                with context:
                    with self.assertRaises(RuntimeError) as raised:reader.read()
                self.assertIs(raised.exception,primary)
                self.assertFalse(hasattr(primary,'impress_discovery_diagnostic'))

    def test_total_strict_json_byte_limit_suppresses_oversize_projection(self):
        reader,root,_=self.tree();primary=RuntimeError('original count getter failed');calls=[]
        def count():raise primary
        root.getAccessibleChildCount=count;original=self.api.json.dumps
        def oversized(*args,**kwargs):
            calls.append(kwargs.copy())
            return original(*args,**kwargs)+' '*32768
        with patch.object(self.api.json,'dumps',side_effect=oversized):
            with self.assertRaises(RuntimeError) as raised:reader.read()
        self.assertIs(raised.exception,primary);self.assertTrue(calls)
        self.assertTrue(all(call.get('allow_nan') is False for call in calls))
        self.assertFalse(hasattr(primary,'impress_discovery_diagnostic'))

    def test_huge_returned_scalar_is_described_within_total_json_bound(self):
        reader,root,_=self.tree();root.getAccessibleChildCount=lambda:2**100000
        with self.assertRaises(AssertionError) as raised:reader.read()
        value=getattr(raised.exception,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict);self.scope(value)
        self.assertLessEqual(len(json.dumps(value,allow_nan=False).encode('utf-8')),32768)
        self.assertEqual(value['failedNode']['childCount'],dict(type='int',valueRetained=False))

    def test_success_and_existing_uniqueness_assertions_are_not_reclassified(self):
        reader,_,_=self.tree();value=reader.read()
        self.assertTrue(self.api.edit_context_ready(value,'impress','Baseline',456))
        self.assertEqual(value['accessibleBinding']['documentPath'],[0])
        for mode in ('document','active-shape'):
            with self.subTest(mode=mode):
                reader,root,document=self.tree();_,_,other_shape,other_document,_=self.fixture.impress()
                if mode=='document':root.set_children([document,other_document])
                else:document.set_children([document.children[0],other_shape])
                message='Original Impress document is ambiguous' if mode=='document' else 'Active Impress text edit is ambiguous'
                with self.assertRaisesRegex(AssertionError,message) as raised:reader.read()
                self.assertFalse(hasattr(raised.exception,'impress_discovery_diagnostic'))

    def test_prelude_geometry_diagnostic_keeps_separate_four_kib_limit(self):
        reader,root,_=self.tree();root.getSize=lambda:NS(Width=0,Height=100)
        with self.assertRaises(AssertionError) as raised:reader.read()
        value=getattr(raised.exception,'impress_geometry_diagnostic',None)
        self.assertIsInstance(value,dict)
        self.assertLessEqual(len(json.dumps(value,allow_nan=False).encode('utf-8')),4096)
        self.assertEqual(value['role'],40);self.assertEqual(value['rectangle'],[0,0,0,100])
        self.assertFalse(hasattr(raised.exception,'impress_discovery_diagnostic'))

    def test_helper_error_json_retains_discovery_and_exact_64_bit_native_hwnd(self):
        hwnd=0x1000000000000001;editing=self.depth_failure(hwnd);api=fixtures.model_reader;events=[];holder={}
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            config=dict(expected_service=self.api.SERVICES['impress'],getter_contract=self.api.GETTERS['impress'],
                suite=str(directory),readerDeadline=10.)
            (directory/'configuration.json').write_text(json.dumps(config))
            (directory/'request-000.json').write_text('{"sequence":0,"action":"start"}')
            class Reader:
                def __init__(self,*args,**kwargs):pass
                def read(self):
                    try:return editing.read()
                    except BaseException as exc:holder['primary']=exc;raise
                def release(self):events.append('release');editing.release()
            anchor=NS(snapshot=lambda:{},last_snapshot={},profile=None,close=lambda:[])
            original=api._atomic_json
            def publish(path,value):
                result=original(path,value)
                if path.name=='reply-000.json':
                    events.append('publish')
                    (directory/'request-001.json').write_text('{"sequence":1,"action":"release"}')
                return result
            with patch.object(api,'_UnoReader',Reader),patch.object(api,'_native_anchor',return_value=anchor),\
                 patch.object(api,'_qpc',return_value=(1,1)),patch.object(api,'_atomic_json',side_effect=publish),\
                 patch('writer_style_smoke.observe_packaged_python',return_value={}),\
                 patch('writer_style_smoke.require_packaged_python',return_value={}):
                self.assertEqual(api._helper(directory,explicit_model=True),0)
            reply=json.loads((directory/'reply-000.json').read_bytes())
            self.assertEqual(events,['publish','release'])
            self.assertFalse(reply['ok']);self.assertIsNone(reply['error']['attemptedObservation'])
            self.assertEqual(reply['error']['message'],str(holder['primary']))
            self.assertIn('impressGeometryDiagnostic',reply['error'])
            self.assertIsNone(reply['error']['impressGeometryDiagnostic'])
            discovery=reply['error'].get('impressDiscoveryDiagnostic')
            self.assertIsInstance(discovery,dict)
            self.assertEqual(discovery,holder['primary'].impress_discovery_diagnostic)
            self.assertIs(type(discovery['childHwnd']),int);self.assertEqual(discovery['childHwnd'],hwnd)
            self.scope(discovery,hwnd)


if __name__=='__main__':unittest.main()
