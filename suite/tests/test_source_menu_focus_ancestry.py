"""Source-qualified focus ancestry is observation, never a new input target."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'suite/e2e'),str(ROOT/'suite/tests')]
import test_owned_native_menu as old
import test_native_menu_source_selection as selection_tests


class SourceFocusAncestryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=selection_tests.SourceMenuSelectionTests('test_prepares_actual_bare_gate_context_and_freezes_contexts')
        cls.source.setUp();cls.addClassCleanup(cls.source.doCleanups)
        cls.prepared=cls.source.prepared();cls.selection=cls.source.selected(cls.prepared)

    def fixture(self,mode=None):
        owner=old.OwnedNativeMenuTests('runTest');self.addCleanup(owner.doCleanups)
        m,api,process,record,clock,b=owner.real_chrome_fixture()
        p=b.probe;root=self.prepared.admission.suite_root
        process.opengeul_suite_root=root;process.args=[str(root/'OpenGeul.Office.exe')]
        process.opengeul_source_menu_selection=self.selection
        p.source_selection=self.selection;p._native_point_profile=True;p._native_point_profile_version=4;p._native_identity_diagnostic=0
        b.native.shell['image']=str(root/'OpenGeul.Office.exe')
        b.native.engine.update(image=str(root/'Office/program/soffice.bin'),handleValue=9)
        window=p.window_snapshot
        def windows(hwnd):
            value=window(hwnd);value['rectangle']=[0,0,400,1000]
            return value
        p.window_snapshot=windows
        keyboard=p._keyboard()
        keyboard.deadline=p.deadline
        p._keyboard=lambda:keyboard
        original_focus=p.uia.iuia.GetFocusedElement
        state=NS(mode=mode,focus_reads=0,parent_reads=0,unknown_queries=[])
        class Unknown(b.Node):
            @property
            def CurrentName(self):raise AssertionError('No unretained name/text/title reads')
            @property
            def CurrentProcessId(self):
                state.unknown_queries.append('pid')
                if state.mode=='primary':raise state.primary
                if state.mode=='late':clock.now=p.deadline
                return 999 if state.mode=='foreign' else 88
            @property
            def CurrentControlType(self):return 50032 if state.mode=='unknown-kind' else 50011
            @property
            def CurrentIsOffscreen(self):
                if state.mode=='integer-bool':return 0
                if state.mode=='bad-bool':return 2
                if state.mode=='float-bool':return 0.0
                return state.mode=='hidden'
            @property
            def CurrentIsEnabled(self):return 1 if state.mode=='integer-bool' else state.mode!='disabled'
            @property
            def CurrentNativeWindowHandle(self):
                if state.mode=='none-hwnd':return None
                if state.mode=='bad-hwnd':return 1<<32
                if state.mode=='boolean-hwnd':return False
                if state.mode=='foreign-hwnd':return -1
                return 0
            @property
            def CurrentBoundingRectangle(self):
                return NS(left=-1,top=-1,right=1,bottom=1) if state.mode=='outside' else NS(left=90,top=60,right=150,bottom=80)
            def GetRuntimeId(self):
                if state.mode=='runtime-error':raise state.primary
                if state.mode=='valid-runtime':return [5,-7,321]
                if state.mode=='max-runtime':return [-(1<<31),(1<<31)-1]+[5]*62
                if state.mode=='boolean-runtime':return [True]
                if state.mode=='float-runtime':return [1.0]
                if state.mode=='overflow-runtime':return [1<<31]
                if state.mode=='oversized-runtime':return [1]*65
                return None if state.mode=='invalid-runtime' else super().GetRuntimeId()
        if state.mode=='unverified':Unknown.__com_interface__=None
        def focused():
            after_alt=any(type(item)is tuple and item==('key','ALT_F')for item in b.native.calls)
            if not after_alt:return original_focus()
            state.focus_reads+=1
            if state.mode=='retained':return b.Node('file')
            return Unknown('stale' if state.mode=='stale-focus' and state.focus_reads>1 else 'blank')
        p.uia.iuia.GetFocusedElement=focused
        parent=p.uia.iuia.ControlViewWalker.GetParentElement
        def parents(node):
            if isinstance(node,Unknown):
                state.parent_reads+=1
                if state.mode=='cycle':return Unknown('blank')
                if state.mode=='exhausted':return Unknown('blank'+str(int(node.key[5:] or '0')+1))
                if state.mode=='parent-stale' and state.parent_reads%2==0:return b.Node('bar')
                if state.mode=='peer-only':return b.Node('peer')
                if state.mode=='generation':b.native.engine['creationTime']=201
                return b.Node('file')
            return parent(node)
        p.uia.iuia.ControlViewWalker.GetParentElement=parents
        compare=p.uia.iuia.CompareElements
        def comparisons(left,right):
            if state.mode=='comparison-error' and isinstance(left,Unknown):raise state.primary
            if state.mode=='ambiguous' and isinstance(left,Unknown) and not isinstance(right,Unknown):return True
            return compare(left,right)
        p.uia.iuia.CompareElements=comparisons
        foreground=p.foreground
        p.foreground=lambda:1234 if state.mode=='foreground' and any(item==('key','ALT_F') for item in b.native.calls if type(item)is tuple) else foreground()
        return m,api,process,record,clock,b,state

    def action(self,mode=None):
        m,api,process,record,clock,b,state=self.fixture(mode)
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock):
            result=m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        return m,result,process,record,clock,b,state

    def test_source_keyboard_walks_unretained_menuitem_to_original_file_without_granting_it_a_role(self):
        m,value,process,record,clock,b,state=self.action()
        self.assertTrue(value['success']);self.assertLess(value['finishedAt'],value['deadline'])
        self.assertEqual([row['shortcut']for row in value['keys']],['ALT_F','DOWN','ESCAPE'])
        self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],
            [('key','ALT_F'),('key','DOWN'),('key','ESCAPE')])
        self.assertGreater(state.parent_reads,0)
        self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)


    def test_retained_source_focus_still_has_a_mandatory_direct_focus_proof(self):
        m,value,process,record,clock,b,state=self.action('retained')
        proof=value['keys'][1]['before']['sourceFocus']
        self.assertEqual(proof['branchCode'],1)
        self.assertEqual(len(proof['proof']['rows']),1)
        self.assertTrue(proof['proof']['focusFreshEquals']);self.assertTrue(proof['proof']['focusEndEquals'])
        self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)

    def test_official_integer_bool_and_absent_native_handle_shapes_keep_all_other_guards(self):
        for mode in ('integer-bool','none-hwnd'):
            with self.subTest(mode=mode):
                m,value,process,record,clock,b,state=self.action(mode)
                observed=value['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['observation']
                self.assertIs(observed['visible'],True);self.assertIs(observed['enabled'],True)
                self.assertEqual(observed['nativeHwnd'],0)
                self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)

    def test_unproved_observation_never_sends_down_or_escape(self):
        for mode in ('foreign','stale-focus','parent-stale','cycle','ambiguous','peer-only','unknown-kind','hidden','disabled','late','outside','unverified','invalid-runtime','generation','foreground','exhausted','bad-bool','float-bool','bad-hwnd','boolean-hwnd','foreign-hwnd','boolean-runtime','float-runtime','overflow-runtime','oversized-runtime'):
            with self.subTest(mode=mode):
                m,api,process,record,clock,b,state=self.fixture(mode)
                import native_menu_source_selection as selected
                with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError):
                    m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
                self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],[('key','ALT_F')])

    def test_source_replay_requires_current_protocol_and_complete_closed_proof(self):
        m,value,process,record,clock,b,state=self.action()
        self.assertEqual(value['sourceMenu']['focusProtocolVersion'],1)
        snapshots=[key['before'] for key in value['keys']]
        proven=[row for row in snapshots if row['sourceFocus']['branchCode']==2]
        self.assertTrue(proven)
        for snapshot in proven:
            self.assertNotIn('identity',snapshot['sourceFocus']['proof']['rows'][0]['observation'])
            self.assertEqual(snapshot['focusMenuPath'][-1]['identity']['role'],'file')
        changes=(lambda p:p['sourceMenu'].pop('focusProtocolVersion'),
            lambda p:p['sourceMenu'].update(focusProtocolVersion=0),
            lambda p:p['sourceMenu'].update(focusProtocolVersion=True),
            lambda p:p['keys'][1]['before'].pop('sourceFocus'),
            lambda p:p['keys'][1]['before']['sourceFocus'].pop('proof'),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['differentFrom'].update(file=True),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof'].update(focusFreshEquals=False),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['edges'][0].update(parentFreshEquals=False),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['observation'].update(pid=999),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof'].update(terminalRole='peer'),
            lambda p:p['keys'][1]['before']['sourceFocus'].update(branchCode=1),
            lambda p:p['keys'][1]['before']['sourceFocus'].update(branchCode=0,proof=None),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['observation']['runtimeObservation'].update(versionObserved=False),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['differentFromPrior'].append(False),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['edges'][0].update(differentFromEarlier=[True]),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['before'].update(childPid=999),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['after'].update(foreground=999),
            lambda p:p['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['observation'].update(identity={'role':'file'}))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                altered=copy.deepcopy(value);change(altered)
                with self.assertRaises((AssertionError,KeyError)):
                    m.require_native_menu_action(altered,77,11,source_admission=self.prepared.admission)


    def test_unretained_valid_runtime_is_observation_only_and_keeps_the_original_keyboard_path(self):
        m,value,process,record,clock,b,state=self.action('valid-runtime')
        proof=value['keys'][1]['before']['sourceFocus']['proof']
        row=proof['rows'][0]
        self.assertIsNone(row['retainedRole']);self.assertNotIn('identity',row['observation'])
        self.assertEqual(row['observation']['runtimeId'],[5,-7,321])
        self.assertTrue(all(same is False for same in row['differentFrom'].values()))
        self.assertEqual(proof['terminalRole'],'file')
        self.assertEqual([key['shortcut'] for key in value['keys']],['ALT_F','DOWN','ESCAPE'])
        self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)
        changes=(lambda p:p.update(runtimeId=[True]),lambda p:p.update(runtimeId=[1<<31]),
            lambda p:p.update(runtimeId=[1]*65),lambda p:p.update(runtimeId=[1.0]),
            lambda p:p['runtimeObservation'].update(length=2),
            lambda p:p['runtimeObservation'].update(length=True),
            lambda p:p['runtimeObservation'].update(empty=True),
            lambda p:p['runtimeObservation'].update(rawTypeCode=True),
            lambda p:p['runtimeObservation'].update(elementTypeCodes=[1,1,2]),
            lambda p:p['runtimeObservation'].update(callSucceeded=False))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                altered=copy.deepcopy(value)
                change(altered['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['observation'])
                with self.assertRaises(AssertionError):m.require_native_menu_action(altered,77,11,source_admission=self.prepared.admission)
        for role in ('file','bar','target:save'):
            with self.subTest(positiveRole=role):
                altered=copy.deepcopy(value)
                altered['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['differentFrom'][role]=True
                with self.assertRaises(AssertionError):m.require_native_menu_action(altered,77,11,source_admission=self.prepared.admission)

    def test_nonempty_unretained_runtime_does_not_bypass_foreign_stale_cycle_or_ambiguity_guards(self):
        for mode in ('foreign','stale-focus','parent-stale','cycle','ambiguous','peer-only','unknown-kind','hidden','disabled','late','generation','foreground','exhausted'):
            with self.subTest(mode=mode):
                m,api,process,record,clock,b,state=self.fixture(mode)
                runtime=b.Node.GetRuntimeId
                b.Node.GetRuntimeId=lambda node:[5,-7,321] if node.key.startswith('blank') or node.key=='stale' else runtime(node)
                import native_menu_source_selection as selected
                with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError):
                    m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
                self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],[('key','ALT_F')])

    def test_unretained_runtime_accepts_the_exact_signed_int32_length_boundary_without_granting_a_role(self):
        m,value,process,record,clock,b,state=self.action('max-runtime')
        observed=value['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['observation']
        self.assertEqual(len(observed['runtimeId']),64)
        self.assertEqual(observed['runtimeId'][:2],[-(1<<31),(1<<31)-1])
        self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)

    def assert_primary(self,mode,queries):
        m,api,process,record,clock,b,state=self.fixture(mode)
        class PrimaryFailure(Exception):
            def __str__(self):raise AssertionError('No primary exception text read')
        state.primary=PrimaryFailure()
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock),self.assertRaises(PrimaryFailure) as caught:
            m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        self.assertIs(caught.exception,state.primary)
        self.assertEqual(state.unknown_queries,queries)
        self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],[('key','ALT_F')])

    def test_unretained_property_failure_keeps_primary_identity_and_never_retries(self):
        self.assert_primary('primary',['pid'])

    def test_unretained_runtime_failure_keeps_primary_identity_and_never_falls_back(self):
        self.assert_primary('runtime-error',[])

    def test_unretained_comparison_failure_keeps_primary_identity_and_never_falls_back(self):
        self.assert_primary('comparison-error',[])


if __name__=='__main__':unittest.main()
