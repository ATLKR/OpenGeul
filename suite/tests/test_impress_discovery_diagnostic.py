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


class ImpressDiscoveryDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SemanticGetterTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.api=self.fixture.api

    def tree(self):
        frame,paragraph,shape,document,uno=self.fixture.impress()
        root=frame.getContainerWindow().getProperty('XAccessible')
        patcher=patch.dict(sys.modules,uno=uno);patcher.start();self.addCleanup(patcher.stop)
        reader=self.api.EditingContextReader('impress',frame,object(),object(),456,
            deadline=10.,clock=lambda:self.fixture.now)
        return reader,root,document

    def depth_failure(self):
        reader,root,_=self.tree()
        unknown=Accessible(49,rectangle=(0,0,0,0))
        unknown.getAccessibleContext=lambda:self.fail('Over-depth node was queried')
        node=unknown
        for _ in range(8):node=Accessible(49,children=[node],rectangle=(0,0,0,0))
        root.set_children([node])
        return reader

    def diagnostic(self,reader):
        with self.assertRaises(AssertionError) as raised:reader.read()
        self.assertEqual(str(raised.exception),'Accessible discovery exceeded fixed bound')
        value=getattr(raised.exception,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict)
        self.assertLessEqual(len(json.dumps(value,allow_nan=False).encode()),32768)
        self.assertFalse(value['qualification'])
        return raised.exception,value

    def test_depth_failure_retains_returned_ancestors_and_unqueried_failed_path(self):
        reader=self.depth_failure();clock=[]
        reader.clock=lambda:clock.append(1) or 1.
        _,value=self.diagnostic(reader)
        self.assertEqual(value['failedPath'],[0]*9)
        self.assertEqual(value['failedCaps'],['depth'])
        self.assertEqual(value['visitedCount'],10)
        self.assertEqual(value['returnedHeaderCount'],9)
        self.assertEqual([r['path'] for r in value['ancestors']],[[]]+[[0]*n for n in range(1,9)])
        self.assertEqual(value['ancestors'][0]['role'],40)
        self.assertEqual(value['ancestors'][-1]['role'],49)
        self.assertEqual(value['ancestors'][-1]['childCount'],1)
        self.assertTrue(all(type(r['stateBits']) is int and r['visible']==536870912 for r in value['ancestors']))
        self.assertFalse(value['failedNode']['headerReturned'])
        self.assertIsNone(value['failedNode']['role'])
        self.assertIsNone(value['failedNode']['stateBits'])
        self.assertIsNone(value['failedNode']['visible'])
        self.assertEqual(len(clock),170,'Diagnostics added a clock/native getter call')

    def test_visit_limit_retains_bounded_tail_and_original_257th_unqueried_path(self):
        reader,root,_=self.tree()
        root.set_children([Accessible(49,children=[Accessible(1) for _ in range(63)],
            rectangle=(0,0,0,0)) for _ in range(4)])
        unknown=root.children[3].children[62]
        unknown.getAccessibleContext=lambda:self.fail('Over-visit node was queried')
        _,value=self.diagnostic(reader)
        self.assertEqual(value['failedCaps'],['visits'])
        self.assertEqual(value['visitedCount'],257)
        self.assertEqual(value['returnedHeaderCount'],256)
        self.assertEqual(value['failedPath'],[3,62])
        self.assertEqual([r['path'] for r in value['ancestors']],[[],[3]])
        self.assertLessEqual(len(value['returnedNodes']),16)
        self.assertTrue(value['returnedNodesTruncated'])
        self.assertFalse(value['failedNode']['headerReturned'])

    def test_returned_child_count_bound_is_retained_without_querying_children(self):
        reader,root,_=self.tree()
        root.getAccessibleChildCount=lambda:65
        root.getAccessibleChild=lambda *_:self.fail('Over-count child was queried')
        with self.assertRaises(AssertionError) as raised:reader.read()
        value=getattr(raised.exception,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict)
        self.assertEqual(value['failedCaps'],['children'])
        self.assertEqual(value['failedPath'],[])
        self.assertEqual(value['failedNode']['childCount'],65)
        self.assertTrue(value['failedNode']['headerReturned'])

    def test_getter_error_keeps_same_primary_and_makes_no_failure_probe(self):
        reader,root,_=self.tree();primary=RuntimeError('original child count getter failed');failed=[]
        def count():failed.append(True);raise primary
        root.getAccessibleChildCount=count
        def clock():
            self.assertFalse(failed,'Failure projection queried the clock')
            return 1.
        reader.clock=clock
        with self.assertRaises(RuntimeError) as raised:reader.read()
        self.assertIs(raised.exception,primary)
        value=getattr(primary,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict)
        self.assertEqual(value['stage'],'child-count-getter')
        self.assertEqual(value['failedCaps'],[])
        self.assertIsNone(value['failedNode']['childCount'])
        self.assertFalse(value['failedNode']['childCountReturned'])

    def test_projection_or_exception_attachment_failure_never_replaces_original(self):
        class LockedError(RuntimeError):
            def __setattr__(self,name,value):
                if name=='impress_discovery_diagnostic':raise OverflowError('diagnostic attachment refused')
                super().__setattr__(name,value)
        for failure in ('serialize','attach'):
            with self.subTest(failure=failure):
                reader,root,_=self.tree()
                primary=RuntimeError('original') if failure=='serialize' else LockedError('original')
                def count():raise primary
                root.getAccessibleChildCount=count
                context=patch.object(self.api.json,'dumps',side_effect=ValueError('diagnostic serialization failed')) if failure=='serialize' else patch.object(self.api,'SOURCE',self.api.SOURCE)
                with context:
                    with self.assertRaises(RuntimeError) as raised:reader.read()
                self.assertIs(raised.exception,primary)
                self.assertFalse(hasattr(primary,'impress_discovery_diagnostic'))

    def test_large_returned_count_is_described_without_unbounded_serialization(self):
        reader,root,_=self.tree();root.getAccessibleChildCount=lambda:2**100000
        with self.assertRaises(AssertionError) as raised:reader.read()
        value=getattr(raised.exception,'impress_discovery_diagnostic',None)
        self.assertIsInstance(value,dict)
        self.assertLessEqual(len(json.dumps(value,allow_nan=False).encode()),32768)
        self.assertEqual(value['failedNode']['childCount'],dict(type='int',valueRetained=False))

    def test_success_and_existing_ambiguity_are_not_reclassified_by_diagnostics(self):
        reader,_,_=self.tree();self.assertTrue(reader.read()['targetFound'])
        reader,root,document=self.tree();_,_,_,other,_=self.fixture.impress()
        root.set_children([document,other])
        with self.assertRaisesRegex(AssertionError,'Original Impress document is ambiguous') as raised:reader.read()
        self.assertFalse(hasattr(raised.exception,'impress_discovery_diagnostic'))

    def test_helper_error_json_carries_discovery_alongside_existing_geometry_field(self):
        editing=self.depth_failure();api=fixtures.model_reader;events=[];holder={}
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
            self.assertIsInstance(reply['error'].get('impressDiscoveryDiagnostic'),dict)
            self.assertEqual(reply['error']['impressDiscoveryDiagnostic'],holder['primary'].impress_discovery_diagnostic)


if __name__=='__main__':unittest.main()
