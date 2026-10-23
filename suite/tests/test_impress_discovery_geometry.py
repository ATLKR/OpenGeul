"""Bounded Impress discovery; synthetic trees do not qualify an actual editor."""
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


class ImpressDiscoveryGeometryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SemanticGetterTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.api=self.fixture.api

    def tree(self):
        frame,paragraph,shape,document,uno=self.fixture.impress()
        root=frame.getComponentWindow().getProperty('XAccessible')
        patcher=patch.dict(sys.modules,uno=uno);patcher.start();self.addCleanup(patcher.stop)
        reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,
            deadline=10.,clock=lambda:self.fixture.now)
        return reader,root,document,shape,paragraph

    def unused_geometry(self,node):
        node.getLocationOnScreen=lambda:self.fail('Irrelevant geometry was queried')
        node.getSize=lambda:self.fail('Irrelevant geometry was queried')

    def ready(self,reader):
        value=reader.read()
        self.assertTrue(self.api.edit_context_ready(value,'impress','Baseline',456))
        return value

    def test_irrelevant_leaves_are_filtered_before_unused_geometry(self):
        reader,root,document,shape,paragraph=self.tree()
        noise=Accessible(1,rectangle=(0,0,0,0));self.unused_geometry(noise)
        root.set_children([noise,document])
        extra=Accessible(1,rectangle=(0,0,0,0));self.unused_geometry(extra)
        document.set_children([extra,shape])
        value=self.ready(reader)
        self.assertEqual(value['accessibleBinding']['documentPath'],[1])
        self.assertEqual(value['accessibleBinding']['shapeIndex'],1)

    def test_hidden_documents_shapes_and_paragraphs_do_not_supply_geometry_or_caret(self):
        reader,root,document,shape,paragraph=self.tree()
        hidden_doc=Accessible(83,rectangle=(0,0,0,0));hidden_doc.state=0;self.unused_geometry(hidden_doc)
        root.set_children([hidden_doc,document])
        hidden_shape=Accessible(52,rectangle=(0,0,0,0));hidden_shape.state=0;self.unused_geometry(hidden_shape)
        hidden_para=Accessible(41,rectangle=(0,0,0,0));hidden_para.state=0;self.unused_geometry(hidden_para)
        hidden_para.getCaretPosition=lambda:self.fail('Hidden caret was queried')
        other_shape=Accessible(52,children=[hidden_para],rectangle=(15,15,80,45))
        document.set_children([hidden_shape,other_shape,shape])
        value=self.ready(reader)
        self.assertEqual(value['accessibleBinding']['shapeIndex'],2)
        self.assertEqual([r['shapeIndex'] for r in value['candidateObservations']],[1,2])

    def test_hidden_zero_extent_containers_are_traversed_with_ancestry_checks(self):
        reader,root,document,_,_=self.tree()
        wrapper=Accessible(49,children=[document],rectangle=(0,0,0,0));wrapper.state=0
        self.unused_geometry(wrapper);root.set_children([wrapper])
        value=self.ready(reader)
        self.assertEqual(value['accessibleBinding']['documentPath'],[0,0])

    def test_root_and_each_visible_eligible_target_still_require_positive_extent(self):
        for target,role,path in (('root',40,[]),('document',83,[0]),
                                ('shape',52,[0,0]),('paragraph',41,[0,0,0])):
            with self.subTest(target=target):
                reader,root,document,shape,paragraph=self.tree()
                node=dict(root=root,document=document,shape=shape,paragraph=paragraph)[target]
                node.rectangle=(20,30,20,40)
                with self.assertRaises(AssertionError) as raised:reader.read()
                diagnostic=getattr(raised.exception,'impress_geometry_diagnostic',None)
                self.assertIsInstance(diagnostic,dict)
                self.assertEqual(diagnostic['role'],role);self.assertEqual(diagnostic['path'],path)
                self.assertEqual(diagnostic['components'],dict(x=20,y=30,width=0,height=10))
                self.assertEqual(diagnostic['rectangle'],[20,30,20,40])
                self.assertEqual(diagnostic['stage'],'positive-extent')
                self.assertFalse(diagnostic['qualification'])

    def test_positive_target_outside_owned_ancestor_is_still_rejected(self):
        for target in ('document','shape','paragraph'):
            with self.subTest(target=target):
                reader,_,document,shape,paragraph=self.tree()
                dict(document=document,shape=shape,paragraph=paragraph)[target].rectangle=(-10,-10,120,120)
                with self.assertRaises(AssertionError):reader.read()

    def test_wrong_ancestry_rejects_before_querying_a_foreign_target(self):
        reader,root,document,_,_=self.tree();document.parent=object()
        self.unused_geometry(document)
        with self.assertRaises(AssertionError):reader.read()

    def test_visible_document_and_active_paragraph_ambiguity_remain_fatal(self):
        for mode in ('documents','paragraphs'):
            with self.subTest(mode=mode):
                reader,root,document,shape,paragraph=self.tree()
                _,other_para,other_shape,other_doc,_=self.fixture.impress()
                if mode=='documents':root.set_children([document,other_doc])
                else:document.set_children([shape,other_shape])
                with self.assertRaisesRegex(AssertionError,'ambiguous'):reader.read()

    def test_hidden_retained_target_cannot_become_pending(self):
        reader,_,document,shape,paragraph=self.tree();self.ready(reader)
        paragraph.state=0;self.unused_geometry(paragraph)
        with self.assertRaisesRegex(AssertionError,'disappeared'):reader.read()
        self.assertIs(reader.shape,shape);self.assertIs(reader.paragraph,paragraph)

    def test_another_active_paragraph_cannot_replace_the_retained_target(self):
        reader,_,document,shape,paragraph=self.tree()
        _,other_para,other_shape,_,_=self.fixture.impress(caret=-1)
        document.set_children([shape,other_shape]);self.ready(reader)
        paragraph.state=0;other_para.getCaretPosition=lambda:8
        with self.assertRaisesRegex(AssertionError,'Retained Outliner paragraph changed'):reader.read()
        self.assertIs(reader.shape,shape);self.assertIs(reader.paragraph,paragraph)

    def test_wrong_paragraph_role_is_filtered_before_unused_geometry_or_caret(self):
        reader,_,document,shape,_=self.tree()
        foreign=Accessible(1,rectangle=(0,0,0,0));self.unused_geometry(foreign)
        foreign.getCaretPosition=lambda:self.fail('Foreign paragraph caret was queried')
        other_shape=Accessible(52,children=[foreign],rectangle=(15,15,80,45))
        document.set_children([other_shape,shape]);value=self.ready(reader)
        self.assertEqual(value['accessibleBinding']['shapeIndex'],1)

    def test_child_depth_and_visit_bounds_are_not_extended_for_ignored_geometry(self):
        for mode in ('children','depth','visits'):
            with self.subTest(mode=mode):
                reader,root,_,_,_=self.tree()
                if mode=='children':root.set_children([Accessible(1) for _ in range(65)])
                elif mode=='depth':
                    child=Accessible(49,rectangle=(0,0,0,0))
                    for _ in range(8):child=Accessible(49,children=[child],rectangle=(0,0,0,0))
                    root.set_children([child])
                else:
                    root.set_children([Accessible(49,children=[Accessible(1) for _ in range(63)],
                        rectangle=(0,0,0,0)) for _ in range(4)])
                if mode=='children':
                    with self.assertRaises(AssertionError):reader.read()
                else:
                    with self.assertRaisesRegex(AssertionError,'Accessible discovery exceeded fixed bound'):reader.read()

    def test_original_maximum_document_depth_remains_supported(self):
        reader,root,document,_,_=self.tree();child=document
        for _ in range(7):
            child=Accessible(49,children=[child],rectangle=(0,0,0,0));child.state=0
            self.unused_geometry(child)
        root.set_children([child]);value=self.ready(reader)
        self.assertEqual(value['accessibleBinding']['documentPath'],[0]*8)

    def test_hidden_document_stays_explicitly_nonready_without_foreign_fallback(self):
        reader,_,document,_,_=self.tree();document.state=0;self.unused_geometry(document)
        value=reader.read();self.assertFalse(value['targetFound'])
        self.assertNotIn('documentIdentity',value['accessibleBinding'])

    def test_metadata_getter_cannot_renew_deadline_or_start_late_geometry(self):
        reader,root,_,_,_=self.tree()
        def role():self.fixture.now=10.;return 40
        root.getAccessibleRole=role;self.unused_geometry(root)
        with self.assertRaisesRegex(AssertionError,'deadline'):reader.read()
        self.assertEqual(reader.deadline,10.)

    def test_geometry_getter_error_keeps_same_primary_exception_and_no_failure_probe(self):
        reader,_,_,_,paragraph=self.tree();calls=[];primary=RuntimeError('actual size getter failed')
        def size():calls.append('size');raise primary
        paragraph.getSize=size
        with self.assertRaises(RuntimeError) as raised:reader.read()
        self.assertIs(raised.exception,primary);self.assertEqual(calls,['size'])
        diagnostic=getattr(primary,'impress_geometry_diagnostic',None)
        self.assertIsInstance(diagnostic,dict)
        self.assertEqual(diagnostic['components'],dict(x=20,y=20))
        self.assertEqual(diagnostic['stage'],'size');self.assertIsNone(diagnostic['rectangle'])

    def test_invalid_raw_components_are_bounded_without_becoming_valid_geometry(self):
        for width in (None,True,.5,'x'*5000,2**4096):
            with self.subTest(kind=type(width).__name__):
                reader,_,_,_,paragraph=self.tree()
                paragraph.getSize=lambda:NS(Width=width,Height=15)
                with self.assertRaises(AssertionError) as raised:reader.read()
                diagnostic=getattr(raised.exception,'impress_geometry_diagnostic',None)
                self.assertIsInstance(diagnostic,dict)
                self.assertLessEqual(len(json.dumps(diagnostic,allow_nan=False).encode()),4096)
                self.assertIsNone(diagnostic['rectangle'])

    def test_negative_raw_dimensions_are_preserved_without_coercion(self):
        reader,_,_,_,paragraph=self.tree();paragraph.rectangle=(30,40,20,25)
        with self.assertRaises(AssertionError) as raised:reader.read()
        diagnostic=raised.exception.impress_geometry_diagnostic
        self.assertEqual(diagnostic['components'],dict(x=30,y=40,width=-10,height=-15))
        self.assertEqual(diagnostic['rectangle'],[30,40,20,25])

    def test_paragraph_count_bound_is_not_extended_for_geometry_filtering(self):
        reader,_,_,shape,_=self.tree()
        shape.set_children([Accessible(41) for _ in range(17)])
        with self.assertRaises(AssertionError):reader.read()

    def test_failed_helper_reply_preserves_geometry_before_release_and_original_error(self):
        editing,_,_,_,paragraph=self.tree();paragraph.rectangle=(20,20,20,35)
        api=fixtures.model_reader;events=[];holder={}
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            config=dict(expected_service=self.api.SERVICES['impress'],
                getter_contract=self.api.GETTERS['impress'],suite=str(directory),readerDeadline=10.)
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
            self.assertEqual(events,['publish','release']);self.assertFalse(reply['ok'])
            self.assertEqual(reply['error']['type'],'AssertionError')
            self.assertEqual(reply['error']['message'],str(holder['primary']))
            self.assertEqual(reply['error'].get('impressGeometryDiagnostic'),
                getattr(holder['primary'],'impress_geometry_diagnostic',None))
            self.assertIsInstance(reply['error'].get('impressGeometryDiagnostic'),dict)
            self.assertIsNone(editing.frame)


if __name__=='__main__':unittest.main()
