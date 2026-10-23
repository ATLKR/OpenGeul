"""Focused-view contracts exercised with synthetic UNO peers, not Windows proof."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
sys.path.insert(0,str(Path(__file__).parent))
import ime_semantic_context as semantic
import writer_model_reader as model_reader
from test_impress_component_root import World,Peer
from test_calc_pending_input import Accessible
import test_ime_semantic_context as fixtures

V2='impress-focused-view-edit-context-v2'
V1='impress-active-edit-context-v1'
SERVICE='com.sun.star.presentation.PresentationDocument'
IMPLEMENTATION='AccessibleDrawDocumentView'
ACCESSIBLE_SERVICE='com.sun.star.drawing.AccessibleDrawDocumentView'


def focus_receipt():
    checks=dict(hasFocus=True,peerPathStable=True,properComponentChild=True,properContainerChild=True,
        distinctComponentPeer=True,distinctContainerPeer=True,sameAccessible=True,accessiblePathStable=True,
        role=83,stateBits=553648128,implementationName=IMPLEMENTATION,serviceNames=[ACCESSIBLE_SERVICE])
    return dict(contract=V2,scope='positive-focused-semantic-view',peerIdentity='a'*32,peerPath=[0],
        search=dict(visitedCount=2,limits=dict(visits=256,depth=8,children=64),unknownBranches=[],
            unvisitedBranchCount=0,censusComplete=False,stop='positive-global-focus'),
        before=copy.deepcopy(checks),after=copy.deepcopy(checks))


class FocusPeer(Peer):
    def __init__(self,accessible,*,hwnd=None,focused=False,children=()):
        super().__init__(accessible,hwnd=hwnd)
        self.focused=focused;self.children=list(children);self.returned=None
    def getWindows(self):return list(self.children) if self.returned is None else self.returned
    def hasFocus(self):return self.focused
    def isChild(self,other):
        pending=list(self.children);seen=set()
        while pending:
            node=pending.pop()
            if node is other:return self.child_result
            if node is None or id(node) in seen:continue
            seen.add(id(node));pending.extend(getattr(node,'children',()))
        return False


class FocusWorld(World):
    def __init__(self):
        super().__init__()
        self.document.getImplementationName=lambda:IMPLEMENTATION
        self.document.getSupportedServiceNames=lambda:(ACCESSIBLE_SERVICE,)
        self.focus=FocusPeer(self.document,focused=True)
        self.component=FocusPeer(self.root,children=[self.focus])
        self.container=FocusPeer(self.container_root,hwnd=456,children=[self.component])
        self.current_component=self.component;self.current_container=self.container


class FocusedReaderTests(unittest.TestCase):
    def reader(self,world,contract=V2):
        patcher=patch.dict(sys.modules,uno=world.uno);patcher.start();self.addCleanup(patcher.stop)
        return semantic.EditingContextReader('impress',world.frame,world.controller,world.model,456,
            deadline=10.,clock=lambda:world.now,getter_contract=contract)
    def ready(self,reader):
        value=reader.read()
        self.assertTrue(semantic.edit_context_ready(value,'impress','Baseline',456,getter_contract=V2))
        self.assertIn('focusBinding',value['accessibleBinding'],'A focused-view success needs its checked raw binding')
        return value

    def test_positive_peer_selects_active_document_without_traversing_unrelated_accessible_chrome(self):
        world=FocusWorld();chrome=Accessible(40)
        for _ in range(9):chrome=Accessible(40,children=[chrome])
        world.root.set_children([chrome,world.document])
        with self.assertRaisesRegex(AssertionError,'fixed bound'):self.reader(world,V1).read()
        value=self.ready(self.reader(world))
        self.assertEqual(value['accessibleBinding']['documentPath'],[1])
        self.assertEqual(value['accessibleBinding']['focusBinding']['peerPath'],[0])

    def test_two_visible_documents_are_an_explicit_v1_v2_scope_counterexample(self):
        world=FocusWorld();other=Accessible(83,rectangle=(20,20,100,100))
        world.root.set_children([world.document,other])
        world.component.children.append(FocusPeer(other))
        with self.assertRaisesRegex(AssertionError,'document is ambiguous'):self.reader(world,V1).read()
        value=self.ready(self.reader(world))
        self.assertEqual(value['accessibleBinding']['focusBinding']['scope'],'positive-focused-semantic-view')
        self.assertFalse(value['accessibleBinding']['focusBinding']['search']['censusComplete'])

    def test_unknown_null_and_unavailable_branches_are_retained_without_becoming_leaves(self):
        for branch,reason in ((None,'null-peer'),(NS(hasFocus=lambda:False),'children-api'),
                              (NS(getWindows=lambda:()),'focus-api')):
            with self.subTest(reason=reason):
                world=FocusWorld();world.component.children.insert(0,branch)
                value=self.ready(self.reader(world));search=value['accessibleBinding']['focusBinding']['search']
                self.assertEqual(search['unknownBranches'],[dict(path=[0],reasons=[reason])])
                self.assertEqual(value['accessibleBinding']['focusBinding']['peerPath'],[1])

    def test_over_depth_peer_branch_stays_unknown_when_another_owned_peer_has_positive_global_focus(self):
        world=FocusWorld();branch=FocusPeer(Accessible(40))
        for _ in range(8):branch=FocusPeer(Accessible(40),children=[branch])
        world.component.children=[branch,world.focus]
        value=self.ready(self.reader(world));focus=value['accessibleBinding']['focusBinding']
        self.assertEqual(focus['peerPath'],[1]);self.assertEqual(focus['search']['visitedCount'],11)
        self.assertEqual(focus['search']['unknownBranches'],[dict(path=[0]*9,reasons=['depth'])])
        self.assertFalse(focus['search']['censusComplete'])

    def test_wrong_focused_class_never_resumes_lookup_for_another_document(self):
        world=FocusWorld();world.document.getImplementationName=lambda:'Toolbar'
        other=FocusPeer(world.document,focused=True)
        other.hasFocus=lambda:self.fail('Wrong focused view resumed the candidate search')
        world.component.children.append(other)
        with self.assertRaisesRegex(AssertionError,'wrong document class'):self.reader(world).read()

    def test_no_positive_focus_and_nonboolean_focus_fail_closed(self):
        for bad in (False,None,1,0,'true'):
            with self.subTest(bad=bad):
                world=FocusWorld();world.focus.focused=bad
                with self.assertRaises(AssertionError):self.reader(world).read()

    def test_positive_wrong_role_class_or_service_is_fatal_without_another_document_fallback(self):
        for mode in ('role','class','service','null-accessible','equal-component','foreign'):
            with self.subTest(mode=mode):
                world=FocusWorld()
                if mode=='role':world.focus.accessible=world.root
                elif mode=='class':world.document.getImplementationName=lambda:'AnotherView'
                elif mode=='service':world.document.getSupportedServiceNames=lambda:('another.Service',)
                elif mode=='null-accessible':world.focus.accessible=None
                elif mode=='equal-component':world.component.focused=True
                else:world.component.returned=[FocusPeer(world.document,focused=True)]
                with self.assertRaises(AssertionError):self.reader(world).read()

    def test_known_peer_cycle_and_alias_are_not_silently_deduplicated(self):
        for mode in ('cycle','alias'):
            with self.subTest(mode=mode):
                world=FocusWorld();noise=FocusPeer(Accessible(40))
                world.component.children=([world.component,world.focus] if mode=='cycle' else [noise,noise,world.focus])
                with self.assertRaisesRegex(AssertionError,'alias|cycle'):self.reader(world).read()

    def test_returned_positive_peer_alias_is_rejected_before_positive_lookup_can_stop(self):
        for mode in ('siblings','queued-branch'):
            with self.subTest(mode=mode):
                world=FocusWorld()
                world.component.children=([world.focus,world.focus] if mode=='siblings' else
                    [FocusPeer(Accessible(40),children=[world.focus]),world.focus])
                with self.assertRaisesRegex(AssertionError,'alias|cycle'):self.reader(world).read()

    def test_peer_depth_visit_and_children_budgets_never_find_a_late_focus(self):
        for mode in ('depth','visits','children'):
            with self.subTest(mode=mode):
                world=FocusWorld()
                if mode=='depth':
                    branch=world.focus
                    for _ in range(8):branch=FocusPeer(Accessible(40),children=[branch])
                    world.component.children=[branch]
                elif mode=='children':world.component.children=[FocusPeer(Accessible(1)) for _ in range(64)]+[world.focus]
                else:
                    world.component.children=[FocusPeer(Accessible(40),children=[FocusPeer(Accessible(1)) for _ in range(63)]) for _ in range(4)]+[world.focus]
                with self.assertRaises(AssertionError):self.reader(world).read()

    def test_full_accessible_path_is_never_rebased_or_accepted_with_false_parent_identity(self):
        for mode in ('depth','foreign-parent','cycle','bad-index','oversized-parent'):
            with self.subTest(mode=mode):
                world=FocusWorld()
                if mode=='depth':
                    branch=world.document
                    for _ in range(8):branch=Accessible(40,children=[branch])
                    world.root.set_children([branch])
                elif mode=='foreign-parent':world.document.parent=Accessible(40)
                elif mode=='cycle':world.document.parent=world.document
                elif mode=='bad-index':world.document.index=True
                else:world.root.set_children([world.document]+[Accessible(1) for _ in range(64)])
                with self.assertRaises(AssertionError):self.reader(world).read()

    def test_focus_peer_accessible_class_and_native_path_drift_during_metrics_are_fatal(self):
        for mode in ('focus','accessible','class','service','peer-path','ancestry','controller'):
            with self.subTest(mode=mode):
                world=FocusWorld();reader=self.reader(world)
                def changed():
                    if mode=='focus':world.focus.focused=False
                    elif mode=='accessible':world.focus.accessible=Accessible(83,rectangle=world.document.rectangle)
                    elif mode=='class':world.document.getImplementationName=lambda:'Replaced'
                    elif mode=='service':world.document.getSupportedServiceNames=lambda:('Replaced',)
                    elif mode=='peer-path':world.component.returned=[FocusPeer(world.document,focused=True)]
                    elif mode=='ancestry':world.component.child_result=False
                    else:world.model_controller=object()
                    return 8
                world.paragraph.getCharacterCount=changed
                with self.assertRaises(AssertionError):reader.read()

    def test_getter_exception_and_original_deadline_are_preserved(self):
        for mode in ('exception','deadline'):
            with self.subTest(mode=mode):
                world=FocusWorld();primary=RuntimeError('original native peer getter failed')
                def changed():
                    if mode=='exception':raise primary
                    world.now=10.;return [world.focus]
                world.component.getWindows=changed
                with self.assertRaises(RuntimeError if mode=='exception' else AssertionError) as raised:
                    self.reader(world).read()
                if mode=='exception':self.assertIs(raised.exception,primary)

    def test_unknown_lookup_failure_retains_already_returned_metadata_without_clock_or_getter_queries(self):
        world=FocusWorld();world.component.children=[NS(hasFocus=lambda:False)]
        reader=self.reader(world)
        def clock():
            self.assertIsNone(sys.exc_info()[0],'Failure projection queried the clock')
            return 1.
        reader.clock=clock
        with self.assertRaises(AssertionError) as raised:reader.read()
        diagnostic=getattr(raised.exception,'impress_focused_view_diagnostic',None)
        self.assertIsInstance(diagnostic,dict)
        self.assertEqual(diagnostic['search']['unknownBranches'],[dict(path=[0],reasons=['children-api'])])
        self.assertEqual(diagnostic['search']['visitedCount'],2)
        self.assertLessEqual(len(json.dumps(diagnostic,allow_nan=False).encode()),32768)
        self.assertFalse(diagnostic['qualification'])

    def test_oversize_or_secondary_projection_failure_preserves_the_primary_getter_exception(self):
        import impress_focused_view as focus_api
        for mode in ('oversize','secondary'):
            with self.subTest(mode=mode):
                world=FocusWorld();primary=RuntimeError('original peer failure')
                world.component.getWindows=lambda:(_ for _ in ()).throw(primary)
                reader=self.reader(world);original=focus_api.json.dumps
                def project(*args,**kwargs):
                    self.assertIs(kwargs.get('allow_nan'),False)
                    if mode=='secondary':raise RuntimeError('secondary projection failed')
                    return original(*args,**kwargs)+' '*32768
                with patch.object(focus_api.json,'dumps',side_effect=project):
                    with self.assertRaises(RuntimeError) as raised:reader.read()
                self.assertIs(raised.exception,primary)
                self.assertFalse(hasattr(primary,'impress_focused_view_diagnostic'))

    def test_helper_error_json_retains_focused_failure_exact_hwnd_and_release(self):
        hwnd=0x1000000000000001;world=FocusWorld();world.container.hwnd=hwnd
        world.component.children=[NS(hasFocus=lambda:False)]
        with patch.dict(sys.modules,uno=world.uno):
            editing=semantic.EditingContextReader('impress',world.frame,world.controller,world.model,hwnd,
                deadline=10.,clock=lambda:world.now,getter_contract=V2)
        events=[];holder={}
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'configuration.json').write_text(json.dumps(dict(expected_service=SERVICE,
                getter_contract=V2,suite=str(directory),readerDeadline=10.)))
            (directory/'request-000.json').write_text('{"sequence":0,"action":"start"}')
            class Reader:
                def __init__(self,*args,**kwargs):pass
                def read(self):
                    try:return editing.read()
                    except BaseException as exc:holder['primary']=exc;raise
                def release(self):events.append('release');editing.release()
            anchor=NS(snapshot=lambda:{},last_snapshot={},profile=None,close=lambda:[])
            original=model_reader._atomic_json
            def publish(path,value):
                result=original(path,value)
                if path.name=='reply-000.json':
                    events.append('publish');(directory/'request-001.json').write_text('{"sequence":1,"action":"release"}')
                return result
            with patch.object(model_reader,'_UnoReader',Reader),patch.object(model_reader,'_native_anchor',return_value=anchor),\
                 patch.object(model_reader,'_qpc',return_value=(1,1)),patch.object(model_reader,'_atomic_json',side_effect=publish),\
                 patch('writer_style_smoke.observe_packaged_python',return_value={}),\
                 patch('writer_style_smoke.require_packaged_python',return_value={}):
                self.assertEqual(model_reader._helper(directory,explicit_model=True),0)
            reply=json.loads((directory/'reply-000.json').read_bytes());self.assertFalse(reply['ok'])
            self.assertIsNone(reply['error']['attemptedObservation']);self.assertEqual(events,['publish','release'])
            diagnostic=reply['error'].get('impressFocusedViewDiagnostic')
            self.assertIsInstance(diagnostic,dict)
            self.assertEqual(diagnostic,holder['primary'].impress_focused_view_diagnostic)
            self.assertIs(type(diagnostic['childHwnd']),int);self.assertEqual(diagnostic['childHwnd'],hwnd)
            self.assertIsNone(editing.focused_view)

    def test_selected_document_caret_ambiguity_remains_fatal(self):
        world=FocusWorld();other=Accessible(41,rectangle=(30,30,80,45),text='Baseline')
        other.getCaretPosition=lambda:8
        world.document.set_children([world.shape,Accessible(52,children=[other],rectangle=(25,25,90,65))])
        with self.assertRaisesRegex(AssertionError,'ambiguous'):self.reader(world).read()

    def test_v1_and_v2_raw_evidence_cannot_choose_their_own_replay_contract(self):
        world=FocusWorld();legacy=self.reader(world,V1).read()
        with self.assertRaises(AssertionError):semantic.require_edit_context(legacy,'impress',456,getter_contract=V2)
        focused=self.ready(self.reader(world))
        with self.assertRaises(AssertionError):semantic.require_edit_context(focused,'impress',456,getter_contract=V1)

    def test_release_drops_new_references_without_disposing_the_document(self):
        world=FocusWorld();reader=self.reader(world);self.ready(reader)
        world.focus.dispose=lambda:self.fail('Reader disposed the native peer')
        world.document.dispose=lambda:self.fail('Reader disposed the document')
        focused=reader.focused_view;reader.release();reader.release()
        self.assertIsNone(reader.focused_view)
        for name in ('owner','peer','peer_nodes','document','document_nodes'):
            self.assertIsNone(getattr(focused,name),name)


class FocusedContractTests(unittest.TestCase):
    def contract(self):
        try:return model_reader._model_contract(SERVICE,V2)
        except AssertionError:self.fail('The caller-selected focused-view contract is unavailable')

    def test_explicit_v2_is_separate_from_the_preserved_global_v1_contract(self):
        contract=self.contract();legacy=model_reader._model_contract(SERVICE,V1)
        self.assertEqual(semantic.GETTERS['impress'],V2)
        self.assertEqual(contract.kind,'existing-owned-impress-focused-view-edit-context')
        self.assertEqual(contract.cleanup_kind,'owned-impress-focused-view-edit-context-reader-cleanup')
        self.assertEqual(list(contract.operations),[
            'resolve-existing-owned-frame',
            'original-component-peer.XVclContainer.getWindows.positive-focused-view',
            'retained-focused-peer.XWindow2.hasFocus',
            'same-peer.XAccessible.AccessibleDrawDocumentView',
            'original-component.full-reciprocal-accessible-parent-index-path',
            'owned-focused-document.XAccessible.actual-Outliner-editing-context',
            'isModified','verify-retained-generation'])
        self.assertEqual(list(legacy.operations),[
            'resolve-existing-owned-frame',
            'owned-native-frame.XAccessible.actual-active-Outliner-editing-context',
            'isModified','verify-retained-generation'])
        self.assertNotEqual(contract,legacy)
        for service in ('com.sun.star.text.TextDocument','com.sun.star.sheet.SpreadsheetDocument'):
            with self.subTest(service=service),self.assertRaises(AssertionError):
                model_reader._model_contract(service,V2)

    def test_uno_helper_propagates_the_external_contract_to_the_context_reader(self):
        contract=self.contract();captured=[]
        class Context:
            def __init__(self,*args,**kwargs):captured.append(kwargs)
            def read(self):return dict(module='impress')
        reader=model_reader._UnoReader.__new__(model_reader._UnoReader)
        reader.contract=contract;reader.config=dict(child_hwnd=456,readerDeadline=10.)
        reader.edit_context=None;reader.frame=reader.controller=object()
        reader.model=NS(isModified=lambda:False);reader.snapshot=lambda:dict(measured=True)
        with patch.object(semantic,'EditingContextReader',Context):reader.read()
        self.assertEqual(captured,[dict(deadline=10.,getter_contract=V2)])

    def test_explicit_constructor_does_not_change_the_legacy_default_scope(self):
        world=World()
        with patch.dict(sys.modules,uno=world.uno):
            try:
                focused=semantic.EditingContextReader('impress',world.frame,world.controller,world.model,456,
                    deadline=10.,clock=lambda:world.now,getter_contract=V2)
            except TypeError:self.fail('The context reader does not accept an explicit getter contract')
            legacy=semantic.EditingContextReader('impress',world.frame,world.controller,world.model,456,
                deadline=10.,clock=lambda:world.now)
        self.assertEqual(focused.getter_contract,V2);self.assertEqual(legacy.getter_contract,V1)
        focused.release();legacy.release()


class FocusedReplayTests(unittest.TestCase):
    def raw(self):
        world=FocusWorld()
        with patch.dict(sys.modules,uno=world.uno):
            reader=semantic.EditingContextReader('impress',world.frame,world.controller,world.model,456,
                deadline=10.,clock=lambda:world.now,getter_contract=V1)
            raw=reader.read();reader.release()
        raw['accessibleBinding']['focusBinding']=focus_receipt()
        return raw
    def require(self,raw):return semantic.require_edit_context(raw,'impress',456,getter_contract=V2)

    def test_every_new_phase_predicate_requires_exact_true(self):
        raw=self.raw();self.require(raw)
        for phase in ('before','after'):
            for name in ('hasFocus','peerPathStable','properComponentChild','properContainerChild',
                         'distinctComponentPeer','distinctContainerPeer','sameAccessible','accessiblePathStable'):
                for bad in ('missing',False,1,None):
                    with self.subTest(phase=phase,name=name,bad=bad):
                        value=copy.deepcopy(raw);checks=value['accessibleBinding']['focusBinding'][phase]
                        if bad=='missing':checks.pop(name)
                        else:checks[name]=bad
                        with self.assertRaises(AssertionError):self.require(value)

    def test_replay_rejects_bad_identity_path_class_service_and_search_claims(self):
        raw=self.raw();self.require(raw)
        mutations=[lambda f:f.update(peerIdentity=True),lambda f:f.update(peerPath=[]),
            lambda f:f.update(peerPath=[True]),lambda f:f.update(peerPath=[0]*9),
            lambda f:f.update(scope='all-component-documents'),lambda f:f.update(contract=V1),
            lambda f:f['before'].update(role=True),lambda f:f['after'].update(implementationName='Foreign'),
            lambda f:f['after'].update(serviceNames=['Foreign']),
            lambda f:f['search'].update(censusComplete=True),lambda f:f['search'].update(visitedCount=True),
            lambda f:f['search'].update(visitedCount=257),lambda f:f['search'].update(limits=dict(visits=512,depth=8,children=64)),
            lambda f:f['search'].update(unknownBranches=[dict(path=[0],reasons=['children-api'])])]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                value=copy.deepcopy(raw);mutate(value['accessibleBinding']['focusBinding'])
                with self.assertRaises(AssertionError):self.require(value)

    def test_cross_sample_focus_identity_path_service_and_historical_search_are_retained(self):
        for mode in ('peer-identity','peer-path','services','search'):
            with self.subTest(mode=mode):
                setup=fixtures.SemanticSetupTests();setup.setUp();self.addCleanup(setup.doCleanups)
                setup.fixture('impress')
                rows=[setup.row('impress','Baseline',ready=False),setup.row('impress','Baseline',at=1.2)]
                for row in rows:row['editContext']['accessibleBinding']['focusBinding']=focus_receipt()
                changed=rows[1]['editContext']['accessibleBinding']['focusBinding']
                if mode=='peer-identity':changed['peerIdentity']='f'*32
                elif mode=='peer-path':changed['peerPath']=[1]
                elif mode=='services':
                    for phase in ('before','after'):changed[phase]['serviceNames'].append('another.BaseService')
                else:changed['search']['unknownBranches']=[dict(path=[2],reasons=['children-api'])]
                with self.assertRaisesRegex(AssertionError,'focused|Focus|focus'):
                    setup.run_phase(module='impress',rows=rows)

    def test_missing_external_contract_does_not_accept_focused_evidence_as_global_v1(self):
        with self.assertRaises(AssertionError):semantic.require_edit_context(self.raw(),'impress',456)


if __name__=='__main__':unittest.main()
