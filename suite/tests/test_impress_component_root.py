"""Synthetic component-root contracts; these are not Windows qualification."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_ime_semantic_context as fixtures
from test_calc_pending_input import Accessible,ROLES,STATES


class Peer:
    def __init__(self,accessible,*,hwnd=None):
        self.accessible=accessible;self.hwnd=hwnd;self.children=[];self.child_result=True
    def getProperty(self,name):
        assert name=='XAccessible'
        return self.accessible
    def getWindowHandle(self,*args):
        assert self.hwnd is not None,'A component HWND must not replace the native container anchor'
        return self.hwnd
    def isChild(self,other):
        return self.child_result if any(other is child for child in self.children) else False


class World:
    def __init__(self,*,chrome_depth=0):
        self.now=1.
        self.paragraph=Accessible(41,rectangle=(30,30,80,45),text='Baseline')
        for name in ('getCaretPosition','getCharacterCount','getSelectionStart','getSelectionEnd'):
            setattr(self.paragraph,name,lambda:8)
        self.shape=Accessible(52,children=[self.paragraph],rectangle=(25,25,90,65))
        self.document=Accessible(83,children=[self.shape],rectangle=(20,20,100,100))
        self.root=Accessible(40,children=[self.document],rectangle=(10,10,110,110))
        branches=[self.root]
        if chrome_depth:
            chrome=Accessible(40)
            for _ in range(chrome_depth):chrome=Accessible(40,children=[chrome])
            branches.insert(0,chrome)
        self.container_root=Accessible(49,children=branches,rectangle=(0,0,120,120))
        self.component=Peer(self.root);self.container=Peer(self.container_root,hwnd=456)
        self.container.children=[self.component]
        self.current_component=self.component;self.current_container=self.container
        self.frame=NS();self.controller=NS();self.model=NS()
        self.frame_controller=self.controller;self.controller_frame=self.frame;self.model_controller=self.controller
        self.controller_model=self.model
        self.frame.getContainerWindow=lambda:self.current_container
        self.frame.getComponentWindow=lambda:self.current_component
        self.frame.getController=lambda:self.frame_controller
        self.controller.getFrame=lambda:self.controller_frame
        self.controller.getModel=lambda:self.controller_model
        self.model.getCurrentController=lambda:self.model_controller
        roles=dict(ROLES,DOCUMENT_PRESENTATION=83,SHAPE=52)
        self.uno=NS(getConstantByName=lambda name:(STATES if '.AccessibleStateType.' in name else roles)[name.rsplit('.',1)[-1]])


class ImpressComponentRootTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SemanticGetterTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.api=self.fixture.api
    def reader(self,world):
        patcher=patch.dict(sys.modules,uno=world.uno);patcher.start();self.addCleanup(patcher.stop)
        return self.api.EditingContextReader('impress',world.frame,world.controller,world.model,456,
            deadline=10.,clock=lambda:world.now)
    def ready(self,reader):
        value=reader.read()
        self.assertTrue(self.api.edit_context_ready(value,'impress','Baseline',456))
        return value

    def test_complete_component_root_avoids_unrelated_container_chrome_overflow(self):
        world=World(chrome_depth=10);value=self.ready(self.reader(world))
        binding=value['accessibleBinding']
        self.assertEqual(binding['rootBasis'],'original-frame-current-component-window')
        self.assertEqual(binding['root']['rectangle'],[10,10,110,110])
        self.assertEqual(binding['documentPath'],[0])
        self.assertEqual(binding['componentBinding']['containerRoot']['rectangle'],[0,0,120,120])

    def test_full_component_uniqueness_rejects_later_nested_presentation(self):
        world=World();other=Accessible(83,rectangle=(20,20,100,100))
        for _ in range(6):other=Accessible(40,children=[other])
        world.root.set_children([world.document,other])
        with self.assertRaisesRegex(AssertionError,'document is ambiguous'):self.reader(world).read()

    def test_missing_equal_or_foreign_component_has_no_container_fallback(self):
        for mode in ('null','equal','foreign'):
            with self.subTest(mode=mode):
                world=World()
                world.current_component={'null':None,'equal':world.container,'foreign':Peer(world.root)}[mode]
                with self.assertRaises(AssertionError):self.reader(world)

    def test_component_ancestry_requires_exact_true(self):
        for value in (False,1,0,None,'true'):
            with self.subTest(value=value):
                world=World();world.container.child_result=value
                with self.assertRaises(AssertionError):self.reader(world)

    def test_wrong_reciprocal_controller_model_links_fail_at_acquisition(self):
        for attr in ('frame_controller','controller_frame','model_controller','controller_model'):
            with self.subTest(attr=attr):
                world=World();setattr(world,attr,object())
                with self.assertRaises(AssertionError):self.reader(world)

    def test_component_accessor_exception_is_preserved_without_fallback(self):
        world=World();primary=RuntimeError('component accessor failed')
        def fail():raise primary
        world.frame.getComponentWindow=fail
        with self.assertRaises(RuntimeError) as raised:self.reader(world)
        self.assertIs(raised.exception,primary)

    def test_component_accessor_cannot_renew_original_deadline(self):
        world=World()
        def late():world.now=10.;return world.component
        world.frame.getComponentWindow=late
        with self.assertRaisesRegex(AssertionError,'deadline'):self.reader(world)

    def test_component_replacement_rejects_even_identical_accessible_geometry(self):
        world=World();reader=self.reader(world);self.ready(reader)
        world.current_component=Peer(world.root);world.container.children.append(world.current_component)
        with self.assertRaises(AssertionError):reader.read()

    def test_both_accessible_roots_remain_retained(self):
        for target in ('container','component'):
            with self.subTest(target=target):
                world=World();reader=self.reader(world);self.ready(reader)
                getattr(world,target).accessible=Accessible(40,rectangle=(10,10,110,110))
                with self.assertRaises(AssertionError):reader.read()

    def test_accessible_replacement_during_geometry_rejects_identical_rectangles(self):
        for target in ('container','component'):
            with self.subTest(target=target):
                world=World();reader=self.reader(world)
                node=world.container_root if target=='container' else world.root
                size=node.getSize
                def replaced():
                    getattr(world,target).accessible=Accessible(node.role,rectangle=node.rectangle)
                    return size()
                node.getSize=replaced
                with self.assertRaises(AssertionError):reader.read()

    def test_post_read_rechecks_detect_each_owner_link_and_ancestry_drift(self):
        for attr in ('frame_controller','controller_frame','model_controller','controller_model','component','ancestry'):
            with self.subTest(attr=attr):
                world=World();reader=self.reader(world)
                def change():
                    if attr=='component':
                        world.current_component=Peer(world.root);world.container.children.append(world.current_component)
                    elif attr=='ancestry':world.container.child_result=False
                    else:setattr(world,attr,object())
                    return 8
                world.paragraph.getCharacterCount=change
                with self.assertRaises(AssertionError):reader.read()

    def test_component_root_visibility_geometry_and_containment_are_required_without_document(self):
        for mode in ('hidden','defunct','zero','left','top','right','bottom','container-hidden'):
            with self.subTest(mode=mode):
                world=World();world.root.set_children([])
                if mode=='hidden':world.root.state=0
                elif mode=='defunct':world.root.state|=STATES['DEFUNC']
                elif mode=='container-hidden':world.container_root.state=0
                else:world.root.rectangle={'zero':(10,10,10,20),'left':(-1,10,110,110),
                    'top':(10,-1,110,110),'right':(10,10,121,110),'bottom':(10,10,110,121)}[mode]
                with self.assertRaises(AssertionError):self.reader(world).read()

    def test_equal_component_container_extents_are_allowed(self):
        world=World();world.root.rectangle=(0,0,120,120)
        self.ready(self.reader(world))

    def test_component_document_root_keeps_empty_document_path(self):
        world=World();world.component.accessible=world.document
        value=self.ready(self.reader(world))
        self.assertEqual(value['accessibleBinding']['documentPath'],[])

    def test_original_depth_visit_and_child_limits_apply_inside_component(self):
        for mode in ('depth','visits','children'):
            with self.subTest(mode=mode):
                world=World()
                if mode=='depth':
                    child=Accessible(40)
                    for _ in range(8):child=Accessible(40,children=[child])
                    world.root.set_children([child])
                elif mode=='visits':
                    world.root.set_children([Accessible(40,children=[Accessible(1) for _ in range(63)]) for _ in range(4)])
                else:world.root.set_children([Accessible(1) for _ in range(65)])
                with self.assertRaises(AssertionError):self.reader(world).read()

    def test_root_binding_receipt_rejects_missing_false_and_boolean_like_facts(self):
        world=World();value=self.ready(self.reader(world));binding=value['accessibleBinding']
        self.assertIn('componentBinding',binding)
        for mode in ('basis','missing','missing-after','false','integer','wrong-hwnd','hidden-container'):
            with self.subTest(mode=mode):
                changed=copy.deepcopy(value);b=changed['accessibleBinding']
                if mode=='basis':b['rootBasis']='container-window'
                elif mode=='missing':b.pop('componentBinding')
                elif mode=='missing-after':b['componentBinding'].pop('after')
                elif mode in ('false','integer'):b['componentBinding']['after']['properContainerChild']=False if mode=='false' else 1
                elif mode=='wrong-hwnd':b['componentBinding']['before']['containerHwnd']=True
                else:b['componentBinding']['containerRoot']['stateBits']=0
                with self.assertRaises(AssertionError):self.api.require_edit_context(changed,'impress',456)

    def test_root_binding_receipt_requires_containment_on_replay(self):
        world=World();value=self.ready(self.reader(world))
        self.assertIn('componentBinding',value['accessibleBinding'])
        changed=copy.deepcopy(value);changed['accessibleBinding']['componentBinding']['containerRoot']['rectangle']=[20,20,100,100]
        with self.assertRaises(AssertionError):self.api.require_edit_context(changed,'impress',456)

    def test_every_checked_predicate_is_required_and_exact_true_on_replay(self):
        world=World();value=self.ready(self.reader(world))
        names=('frameController','controllerFrame','modelController','controllerModel','containerPeer',
            'containerAccessible','componentPeer','componentDistinct','properContainerChild','componentAccessible')
        for phase in ('before','after'):
            for name in names:
                for bad in ('missing',False,1,None):
                    with self.subTest(phase=phase,name=name,bad=bad):
                        changed=copy.deepcopy(value);checks=changed['accessibleBinding']['componentBinding'][phase]
                        if bad=='missing':checks.pop(name,None)
                        else:checks[name]=bad
                        with self.assertRaises(AssertionError):self.api.require_edit_context(changed,'impress',456)

    def test_release_drops_both_peers_and_accessible_roots_without_disposal(self):
        world=World();reader=self.reader(world);self.ready(reader);reader.release()
        for name in ('peer','container_root','component_peer','root','frame','controller','model'):
            self.assertTrue(hasattr(reader,name),name)
            self.assertIsNone(getattr(reader,name),name)


if __name__=='__main__':unittest.main()
