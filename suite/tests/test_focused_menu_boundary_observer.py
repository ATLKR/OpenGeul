"""Exact native-menu comparison failure with synthetic existing UIA boundary."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import hashlib
import sys
from types import SimpleNamespace as NS
import unittest

BASE=Path(__file__).resolve().parents[2]
REPO=BASE
sys.path[:0]=[str(REPO/'suite/tests'),str(REPO/'suite/e2e'),str(REPO)]
import test_owned_native_menu as original


class FocusedBoundaryTests(unittest.TestCase):
    def setUp(self):
        path=BASE/'suite/e2e/owned_native_menu.py'
        self.assertTrue(path.is_file(),'Focused boundary candidate is missing')
        spec=importlib.util.spec_from_file_location('focused_boundary_candidate',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def fixture(self,*,target='blank'):
        owner=original.OwnedNativeMenuTests(methodName='runTest');self.addCleanup(owner.doCleanups)
        owner.feature=lambda:self.module
        m,api,process,record,clock,b=owner.real_chrome_fixture()
        p=b.probe;p._active_target='save';p._native_identity_diagnostic=0
        p.provider_client=p.uia.iuia
        p.provider_client.ConnectionTimeout=p.provider_client.TransactionTimeout=1
        p.begin_identity_scope(dict(document=11,parent=55,child=56,officePid=88),b.native.shell,b.native.engine,
            clock(),p.deadline,'keyboard-escape',True)
        p._identity_refs={'file':b.Node('file'),'bar':b.Node('bar'),'peer':b.Node('peer'),
            'contrast-edit':b.Node('edit'),'target:save':b.Node('save')}
        p.file_element=p._identity_refs['file'];p.menu_bar_element=p._identity_refs['bar'];p._uses_comparison=True
        state=NS(primary=None,originalLast=None,queries=[],calls=[],pid=88,kind=50011,offscreen=False,enabled=True,
            expire=False,pending=False,storage_failed=False,pid_failure=None,late_pid=False,phase=False,
            after_failure=None)
        class Cursor(b.Node):
            def __init__(self):super().__init__(target)
            @property
            def CurrentProcessId(self):
                state.queries.append('pid')
                if state.pid_failure is not None:raise state.pid_failure
                if state.late_pid:clock.now=p.deadline
                return state.pid
            @property
            def CurrentControlType(self):state.queries.append('kind');return state.kind
            @property
            def CurrentIsOffscreen(self):state.queries.append('offscreen');return state.offscreen
            @property
            def CurrentIsEnabled(self):state.queries.append('enabled');return state.enabled
            @property
            def CurrentNativeWindowHandle(self):
                if state.phase:raise AssertionError('Observer must not read a window handle')
                return 0
            @property
            def CurrentBoundingRectangle(self):
                if state.phase:raise AssertionError('Observer must not read geometry')
                return NS(left=0,top=0,right=1,bottom=1)
            @property
            def CurrentName(self):raise AssertionError('No name/text/title reads')
            def GetRuntimeId(self):
                if state.phase:raise AssertionError('Observer must not retry runtime identity')
                return ()
        cursor=Cursor();p.uia.iuia.GetFocusedElement=lambda:cursor
        previous_role=p._role
        def role(element):
            try:return previous_role(element)
            except BaseException as exc:
                state.primary=exc;state.originalLast=p.interop.get('lastCall');state.phase=True
                if state.expire:clock.now=p.deadline
                if state.pending:p._msaa_lease=NS(pending=True)
                if state.after_failure is not None:state.after_failure()
                raise
        p._role=role
        call=p._uia_call
        def counted(code,method,*args):state.calls.append(code);return call(code,method,*args)
        p._uia_call=counted
        return p,b,clock,state

    def assert_original_failure(self,p,state):
        with self.assertRaises(AssertionError) as caught:p._focused_menu([{'runtimeId':[]},{'runtimeId':[]}],0,1)
        self.assertIs(caught.exception,state.primary)
        self.assertEqual(caught.exception.args,('Native menu identity is unknown or ambiguous',))
        self.assertIs(p.interop['lastCall'],state.originalLast)
        self.assertEqual((p.interop['lastCall']['apiCode'],p.interop['lastCall']['failed']),(5,False))
        return p.interop.get('focusedBoundary')

    def test_original_role_failure_stays_failed_and_owned_numeric_observation_is_separate(self):
        p,b,clock,state=self.fixture();deadline=p.deadline
        row=self.assert_original_failure(p,state)
        self.assertIsInstance(row,dict)
        self.assertEqual((row['observedMask'],row['ownerMatchesOriginalEngine'],row['kindCode'],row['visible'],row['enabled']),(15,True,50011,1,1))
        self.assertEqual((row['diagnosticOnly'],row['acceptanceEligible'],row['complete']),(1,0,1))
        self.assertEqual(state.queries,['pid','kind','offscreen','enabled'])
        self.assertEqual(state.calls,[15,7,3,5,5,5,5,5,8,9,11,12])
        self.assertEqual(len(b.compares),5)
        self.assertEqual(p.deadline,deadline)
        self.assertEqual(p.interop['focusedWalk']['rows'][0]['observedMask'],0)
        self.assertEqual((p.interop['focusedWalk']['failed'],p.interop['focusedWalk']['rows'][0]['failed']),(1,1))
        self.assertEqual(b.native.calls,[])
        encoded=json.dumps(row)
        for key in ('"pid"','officePid','hwnd','runtimeId','Name','Text','Title','SYNTHETIC_PRIVATE'):
            self.assertNotIn(key,encoded)

    def test_foreign_owner_stops_before_other_properties(self):
        p,b,clock,state=self.fixture();state.pid=999
        row=self.assert_original_failure(p,state)
        self.assertIsInstance(row,dict)
        self.assertEqual((row['observedMask'],row['ownerMatchesOriginalEngine'],row['complete']),(1,False,0))
        self.assertIsNone(row['kindCode']);self.assertIsNone(row['visible']);self.assertIsNone(row['enabled'])
        self.assertEqual(state.queries,['pid'])

    def test_expired_original_budget_performs_no_optional_query(self):
        p,b,clock,state=self.fixture();state.expire=True
        row=self.assert_original_failure(p,state)
        self.assertIsInstance(row,dict);self.assertEqual(row['observedMask'],0)
        self.assertEqual(state.queries,[]);self.assertEqual(state.calls,[15,7,3,5,5,5,5,5])

    def test_pending_original_provider_performs_no_optional_query(self):
        p,b,clock,state=self.fixture();state.pending=True
        row=self.assert_original_failure(p,state)
        self.assertIsInstance(row,dict);self.assertEqual(row['observedMask'],0)
        self.assertEqual(state.queries,[])

    def test_profile3_diagnostic_is_not_turned_into_acceptance_or_an_observer_retry(self):
        p,b,clock,state=self.fixture();p._native_identity_diagnostic=3
        self.assert_original_failure(p,state)
        self.assertEqual(state.queries,[])
        self.assertNotIn('focusedBoundary',p.interop)

    def test_observer_com_failure_restores_primary_and_sink_context_without_reading_text(self):
        class COMError(Exception):
            hresult=-2147467259
            def __str__(self):raise AssertionError('No original exception text export')
        p,b,clock,state=self.fixture();state.pid_failure=COMError()
        row=self.assert_original_failure(p,state)
        self.assertIsInstance(row,dict)
        self.assertEqual((row['failed'],row['complete'],row['observedMask']),(1,0,0))
        self.assertIsNone(row['ownerMatchesOriginalEngine'])
        self.assertEqual(row['lastCall']['apiCode'],8)
        self.assertEqual(state.queries,['pid'])
        self.assertIsNone(p._observed_call)
        self.assertIsNone(p._last_call_exception)
        self.assertNotIn('_diagnostic_sink',p.__dict__)

    def test_late_pid_return_never_authorizes_following_properties(self):
        p,b,clock,state=self.fixture();state.late_pid=True
        row=self.assert_original_failure(p,state)
        self.assertIsInstance(row,dict);self.assertEqual((row['failed'],row['observedMask']),(1,0))
        self.assertEqual(state.queries,['pid']);self.assertIsNone(row['kindCode'])

    def test_invalid_scalar_never_exports_raw_value_or_authorizes_more_properties(self):
        for field,raw,mask in (('pid',True,0),('pid',0,0),('kind',99999,1),
            ('kind','SYNTHETIC_PRIVATE',1),('offscreen',2,3),('enabled',None,7)):
            with self.subTest(field=field):
                p,b,clock,state=self.fixture();setattr(state,field,raw)
                row=self.assert_original_failure(p,state)
                self.assertEqual((row['failed'],row['complete'],row['observedMask']),(1,0,mask))
                self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(row))

    def test_provider_setter_and_readback_failures_do_not_claim_getter_entry(self):
        class COMError(Exception):
            hresult=-2147024809
            def __str__(self):raise AssertionError('No raw COM exception text')
        for failed_step in (1,2):
            with self.subTest(failed_step=failed_step):
                p,b,clock,state=self.fixture();original_client=p.provider_client
                class Client:
                    def __init__(self):self.__dict__.update(original_client.__dict__)
                    def __setattr__(self,name,value):
                        if state.phase and name=='ConnectionTimeout' and failed_step==1:raise COMError()
                        object.__setattr__(self,name,value)
                    def __getattribute__(self,name):
                        if state.phase and name=='ConnectionTimeout' and failed_step==2:raise COMError()
                        return object.__getattribute__(self,name)
                p.provider_client=p.uia.iuia=Client()
                row=self.assert_original_failure(p,state);call=row['lastCall']
                self.assertEqual((call['apiCode'],call['providerStep'],call['calleeEntered'],call['callCompleted']),(8,failed_step,False,False))
                self.assertEqual((row['failed'],row['observedMask']),(1,0))
                self.assertEqual(state.queries,[])

    def test_previous_sink_observed_context_exception_and_timeout_flag_are_restored(self):
        p,b,clock,state=self.fixture()
        sink={'existing':1};context={'apiCode':999};prior=RuntimeError('SYNTHETIC_PRIVATE_PRIOR')
        def prepare_context():
            p._diagnostic_sink=sink;p._observed_call=context;p._last_call_exception=prior
            p.provider_timeout_verified=False
        state.after_failure=prepare_context
        row=self.assert_original_failure(p,state)
        self.assertEqual(row['complete'],1)
        self.assertIs(p._diagnostic_sink,sink);self.assertEqual(sink,{'existing':1})
        self.assertIs(p._observed_call,context);self.assertEqual(context,{'apiCode':999})
        self.assertIs(p._last_call_exception,prior);self.assertIs(p.provider_timeout_verified,False)
        self.assertIsNone(p._focus_identity)

    def test_failed_diagnostic_storage_preserves_original_failure_and_reads_nothing(self):
        p,b,clock,state=self.fixture()
        class Sink(dict):
            def __setitem__(self,key,value):
                if key=='focusedBoundary':raise KeyboardInterrupt()
                return super().__setitem__(key,value)
        p.interop=Sink(p.interop)
        self.assert_original_failure(p,state);self.assertEqual(state.queries,[])

    def test_retained_success_path_adds_no_boundary_observation(self):
        p,b,clock,state=self.fixture(target='file')
        result,matched=p._focused_menu([{'runtimeId':[]},{'runtimeId':[]}],0,1)
        self.assertTrue(matched);self.assertEqual(len(result),1)
        self.assertNotIn('focusedBoundary',p.interop)

    def test_original_guard_input_budget_cleanup_and_identity_bodies_unchanged(self):
        raw=(BASE/'suite/tests/fixtures/focused-menu-guard-ast.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'c5ee5f6c1cd51d0bc8662798762e9897904a4e3ea06275dd456f79513364ded5')
        baseline=json.loads(raw)
        self.assertEqual(baseline['baseSourceSha256'],'a663fe7836e27d35a022066622cc40172e3d857e4df2cdc16488e20e3cda8bff')
        names=('_run','_role','_chrome','_runtime','_provider_timeout','_call','_uia_call',
            '_validate','_keyboard_recipient','_arm_source_input','_require_source_point_uses','close_provider','keyboard')
        def functions(text):
            result={}
            def visit(node,prefix=()):
                for child in ast.iter_child_nodes(node):
                    scoped=isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))
                    path=prefix+(child.name,) if scoped else prefix
                    if isinstance(child,ast.FunctionDef) and child.name in names:
                        result['.'.join(path)]=hashlib.sha256(ast.dump(child,include_attributes=False).encode()).hexdigest()
                    visit(child,path)
            visit(ast.parse(text));return result
        self.assertEqual(len(baseline['functionAstSha256']),14)
        self.assertEqual(baseline['functionAstSha256'],functions((BASE/'suite/e2e/owned_native_menu.py').read_text()))



if __name__=='__main__':unittest.main()
