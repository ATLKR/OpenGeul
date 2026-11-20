"""Actual NativeMenuProbe hook; numeric diagnostics never admit New focus."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'suite/tests'),str(ROOT/'suite/e2e'),str(ROOT)]
import test_focused_menu_boundary_observer as existing


class FocusedNewObserverTests(unittest.TestCase):
    def setUp(self):
        self.owner=existing.FocusedBoundaryTests(methodName='runTest');self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.module=self.owner.module
        self.assertTrue(callable(getattr(self.module.NativeMenuProbe,'_observe_failed_focus_new',None)),
                        'Missing actual NativeMenuProbe New diagnostic method')

    def fixture(self,**options):
        owner=self.owner
        p,b,clock,state=owner.fixture(target=options.get('focus','new'))
        b.native.opened=True
        state.finds=[];state.continuities=0;state.attachments=0;state.native=b.native
        state.fail_find=state.late_find=state.pending_find=state.bad_windows=False
        state.context_failure=False
        original_find=b.find
        def find(key,scope,condition):
            state.finds.append(key)
            if state.fail_find:raise OSError(5,'SYNTHETIC_PRIVATE')
            if state.late_find:clock.now=p.deadline
            if state.pending_find:p._msaa_lease=type('Lease',(),{'pending':True})()
            return original_find(key,scope,condition)
        b.find=find
        binding=p._identity_scope['binding']
        windows={role:dict(hwnd=binding[role],pid=88 if role=='child' else 77,
            threadId=9 if role=='child' else 7,rootHwnd=11) for role in ('document','parent','child')}
        def attachment(value):
            state.attachments+=1
            rows=copy.deepcopy(windows)
            if state.bad_windows and state.attachments>1:rows['child']['threadId']+=1
            return dict(binding=dict(value),valid=True,windows=rows,exported=[55,56])
        p.attachment_snapshot=attachment
        def continuity():
            state.continuities+=1
            if state.context_failure:raise AssertionError('SYNTHETIC_PRIVATE')
        scope={key:copy.deepcopy(p._identity_scope[key]) for key in
            ('version','binding','shellPid','shellCreationTime','officeCreationTime','startedAt','deadline')}
        p.bind_menu_classification(scope,continuity)
        return p,b,clock,state,owner

    def run_failure(self,p,state,owner):
        refs=dict(p._identity_refs);deadline=p.deadline
        owner.assert_original_failure(p,state)
        self.assertEqual(p.deadline,deadline)
        self.assertEqual(set(p._identity_refs),set(refs))
        self.assertTrue(all(p._identity_refs[key] is value for key,value in refs.items()))
        self.assertIsNone(p._focus_identity)
        self.assertEqual(state.native.calls,[])
        row=p.interop.get('focusedNewComparison')
        if row is not None:
            self.assertEqual((row['diagnosticOnly'],row['acceptanceEligible'],row['conclusionCode']),(1,0,0))
            encoded=json.dumps(row)
            for text in ('SYNTHETIC_PRIVATE','runtimeId','CurrentName','New','새','hwnd','image','identity','scope'):
                self.assertNotIn(text,encoded)
        return row

    def test_independent_new_comparison_and_parent_are_numeric_and_primary_stays_failed(self):
        p,b,c,s,o=self.fixture();row=self.run_failure(p,s,o)
        self.assertEqual((row['complete'],row['failed'],row['statusCode']),(1,0,1))
        self.assertTrue(row['focusEqualsCandidate']);self.assertTrue(row['freshEqualsCandidate'])
        self.assertTrue(row['directParentEqualsFile']);self.assertTrue(row['windowBindingUnchanged'])
        self.assertEqual((row['continuityBefore'],row['continuityAfter']),(1,1))
        self.assertEqual((row['firstFind']['scanComplete'],row['firstFind']['matchedCount']), (1,1))
        self.assertEqual((row['freshFind']['scanComplete'],row['freshFind']['matchedCount']), (1,1))
        self.assertEqual([r['roleCode'] for r in row['negativeComparisons']],[1,2,3,4,5])
        self.assertTrue(all(r['areSame'] is False for r in row['negativeComparisons']))
        self.assertEqual(s.finds,['file','file'])
        self.assertEqual(s.queries,['pid','kind','offscreen','enabled'])
        self.assertEqual((s.calls.count(15),s.calls.count(3)),(1,1))
        self.assertFalse({3,7,15}&{r['code'] for r in row['callTotals']['apiCalls']})
        self.assertNotIn(2,{r['code'] for r in p.interop['callTotals']['apiCalls']})
        self.assertEqual(b.native.calls,[])

    def test_other_owned_menu_item_is_not_identified_as_new(self):
        p,b,c,s,o=self.fixture(focus='blank');row=self.run_failure(p,s,o)
        self.assertIs(row['focusEqualsCandidate'],False)
        self.assertEqual(row['complete'],0);self.assertEqual(s.finds,['file'])

    def test_missing_and_duplicate_fixed_new_stop_after_complete_scan(self):
        for mode in ('missing','duplicate'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture();find=b.find
                def changed(key,scope,condition):
                    if key!='file':return find(key,scope,condition)
                    result=find(key,scope,condition)
                    nodes=[result.GetElement(i) for i in range(result.Length)]
                    nodes=[n for n in nodes if n.key!='new'] if mode=='missing' else nodes+[b.Node('new')]
                    return type('Elements',(),{'Length':len(nodes),'GetElement':lambda _,i:nodes[i]})()
                b.find=changed
                row=self.run_failure(p,s,o)
                self.assertEqual((row['complete'],row['firstFind']['scanComplete']),(0,1))
                self.assertEqual(row['firstFind']['matchedCount'],0 if mode=='missing' else 2)
                self.assertIsNone(row['focusEqualsCandidate'])

    def test_foreign_candidate_stops_before_name_read_or_comparison(self):
        p,b,c,s,o=self.fixture();find=b.find;node=b.Node
        class Foreign(node):
            @property
            def CurrentProcessId(self):return 999
            @property
            def CurrentName(self):raise AssertionError('Foreign name must not be read')
        b.find=lambda *args:type('Elements',(),{'Length':1,'GetElement':lambda _,i:Foreign('new')})()
        row=self.run_failure(p,s,o)
        self.assertEqual(row['complete'],0);self.assertIsNone(row['focusEqualsCandidate'])
        self.assertEqual(row['firstFind']['scanComplete'],0)

    def test_different_direct_parent_is_partial_and_does_not_change_primary(self):
        p,b,c,s,o=self.fixture();parent=b.parent
        p._uia.iuia.ControlViewWalker.GetParentElement=lambda n:b.Node('edit') if n.key=='new' else parent(n)
        row=self.run_failure(p,s,o)
        self.assertIs(row['directParentEqualsFile'],False);self.assertEqual(row['complete'],0)

    def test_fresh_changed_candidate_and_alias_are_not_completed(self):
        for mode in ('fresh','alias'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture();compare=b.compare
                def after_failure():
                    def changed(left,right):
                        if mode=='fresh' and type(left) is type(right) is b.Node and left.key==right.key=='new':return False
                        if mode=='alias' and left.key=='new' and right.key=='edit':return True
                        return compare(left,right)
                    p._uia.iuia.CompareElements=changed
                s.after_failure=after_failure
                row=self.run_failure(p,s,o);self.assertEqual(row['complete'],0)
                if mode=='fresh':self.assertIs(row['freshEqualsCandidate'],False)
                else:self.assertTrue(next(r['areSame'] for r in row['negativeComparisons'] if r['roleCode']==4))

    def test_expired_pending_or_missing_context_performs_no_new_find(self):
        for mode in ('expired','pending','missing','wrong-scope','foreign-cursor'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture()
                if mode=='expired':s.expire=True
                elif mode=='pending':s.pending=True
                elif mode=='missing':p._menu_classification_context=None
                elif mode=='wrong-scope':p._menu_classification_context[0]['officeCreationTime']+=1
                else:s.pid=999
                row=self.run_failure(p,s,o);self.assertEqual(s.finds,[])
                if row is not None:self.assertEqual(row['complete'],0)

    def test_late_pending_and_com_find_never_attempt_fresh_find(self):
        for mode in ('late_find','pending_find','fail_find'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture();setattr(s,mode,True)
                row=self.run_failure(p,s,o)
                self.assertEqual(row['complete'],0);self.assertEqual(s.finds,['file'])
                self.assertIsNone(row['focusEqualsCandidate'])

    def test_generation_or_window_change_is_partial(self):
        for mode in ('generation','windows'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture()
                if mode=='generation':
                    original=p._menu_classification_context[1]
                    def changed():
                        original()
                        if s.continuities==2:raise AssertionError('SYNTHETIC_PRIVATE')
                    p._menu_classification_context=(p._menu_classification_context[0],changed)
                else:s.bad_windows=True
                row=self.run_failure(p,s,o);self.assertEqual(row['complete'],0)

    def test_new_candidate_rejects_float_kind_and_non_boolean_visibility(self):
        for mode in ('kind','offscreen','enabled'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture();node=b.Node
                class Invalid(node):
                    @property
                    def CurrentControlType(self):return 50011.0 if mode=='kind' else 50011
                    @property
                    def CurrentIsOffscreen(self):return 0.0 if mode=='offscreen' else False
                    @property
                    def CurrentIsEnabled(self):return 1.0 if mode=='enabled' else True
                b.find=lambda *args:type('Elements',(),{'Length':1,'GetElement':lambda _,i:Invalid('new')})()
                row=self.run_failure(p,s,o);self.assertEqual(row['complete'],0)
                self.assertIsNone(row['focusEqualsCandidate'])

    def test_bound_context_mutation_after_find_is_partial(self):
        p,b,c,s,o=self.fixture();parent=p._uia.iuia.ControlViewWalker.GetParentElement
        def changed(node):
            result=parent(node)
            p._menu_classification_context[0]['officeCreationTime']+=1
            return result
        p._uia.iuia.ControlViewWalker.GetParentElement=changed
        row=self.run_failure(p,s,o);self.assertEqual(row['complete'],0)

    def test_storage_failure_performs_no_new_queries_and_primary_is_identical(self):
        p,b,c,s,o=self.fixture()
        class Sink(dict):
            def __setitem__(self,key,value):
                if key=='focusedNewComparison':raise KeyboardInterrupt()
                super().__setitem__(key,value)
        p.interop=Sink(p.interop)
        row=self.run_failure(p,s,o);self.assertIsNone(row);self.assertEqual(s.finds,[])

    def test_new_observer_com_failure_restores_prior_sink_context_exception_and_timeout(self):
        p,b,c,s,o=self.fixture()
        sink={'existing':1};context={'apiCode':999};prior=RuntimeError('SYNTHETIC_PRIVATE_PRIOR')
        class COMError(Exception):
            hresult=-2147467259
            def __str__(self):raise AssertionError('Do not stringify COM errors')
        def setup_context():
            p._diagnostic_sink=sink;p._observed_call=context;p._last_call_exception=prior
            p.provider_timeout_verified=False
        s.after_failure=setup_context
        b.find=lambda *args:(_ for _ in ()).throw(COMError())
        row=self.run_failure(p,s,o)
        self.assertEqual((row['complete'],row['failed'],row['statusCode']),(0,1,7))
        self.assertIs(p._diagnostic_sink,sink);self.assertEqual(sink,{'existing':1})
        self.assertIs(p._observed_call,context);self.assertEqual(context,{'apiCode':999})
        self.assertIs(p._last_call_exception,prior);self.assertIs(p.provider_timeout_verified,False)

    def test_retained_success_does_not_start_optional_new_observation(self):
        p,b,c,s,o=self.fixture(focus='file')
        rows,matched=p._focused_menu([{'runtimeId':[]},{'runtimeId':[]}],0,1)
        self.assertTrue(matched);self.assertEqual(len(rows),1)
        self.assertNotIn('focusedNewComparison',p.interop);self.assertEqual(s.finds,[])

    def test_failed_boundary_write_cannot_reuse_an_old_completed_observation(self):
        p,b,c,s,o=self.fixture();p.interop['focusedBoundary']=dict(depth=0,complete=1,
            ownerMatchesOriginalEngine=True,kindCode=50011,visible=1,enabled=1)
        class Sink(dict):
            def __setitem__(self,key,value):
                if key=='focusedBoundary':raise KeyboardInterrupt()
                super().__setitem__(key,value)
        p.interop=Sink(p.interop)
        self.run_failure(p,s,o);self.assertEqual(s.finds,[])
        self.assertNotIn('focusedNewComparison',p.interop)

    def test_control_view_walker_property_is_inside_budget_and_call_record(self):
        for mode in ('com','late','pending'):
            with self.subTest(mode=mode):
                p,b,c,s,o=self.fixture();original=p.provider_client;parent_calls=[]
                class COMError(Exception):
                    hresult=-2147467259
                    def __str__(self):raise AssertionError('No raw COM error text')
                walker=type('Walker',(),{'GetParentElement':lambda _,node:parent_calls.append(1)})()
                class Client:
                    def __init__(self):self.__dict__.update(original.__dict__)
                    @property
                    def ControlViewWalker(self):
                        if mode=='com':raise COMError()
                        if mode=='late':c.now=p.deadline
                        if mode=='pending':p._msaa_lease=type('Lease',(),{'pending':True})()
                        return walker
                p.provider_client=p._uia.iuia=Client()
                row=self.run_failure(p,s,o)
                self.assertEqual(row['complete'],0);self.assertEqual(parent_calls,[])
                self.assertEqual(row['lastCall']['apiCode'],0)
                if mode=='com':self.assertTrue(row['lastCall']['failed'])


if __name__=='__main__':unittest.main()
