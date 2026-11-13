"""Source-qualified focus ancestry is observation, never a new input target."""
import copy
import gc
from pathlib import Path
import sys
import weakref
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
                if state.mode=='outside' and hasattr(state,'focus_hwnd'):return state.focus_hwnd
                if state.mode=='none-hwnd':return None
                if state.mode=='bad-hwnd':return 1<<32
                if state.mode=='boolean-hwnd':return False
                if state.mode=='foreign-hwnd':return -1
                return 0
            @property
            def CurrentBoundingRectangle(self):
                if state.mode=='invalid-rect':return NS(left=90.0,top=60,right=150,bottom=80)
                if state.mode=='outside' and hasattr(state,'outside_rectangle'):
                    return NS(**dict(zip(('left','top','right','bottom'),state.outside_rectangle)))
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
        self.assertNotIn('sourceFocusBoundsFailure',value['uiaInterop'])
        self.assertNotIn('sourceFocusBoundsStructure',value['uiaInterop'])
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

    def test_popup_containment_failure_retains_only_observed_numeric_bounds(self):
        m,api,process,record,clock,b,state=self.fixture('outside')
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError):
            m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        value=record['nativeMenuActions'][-1]
        failure=value['uiaInterop'].get('sourceFocusBoundsFailure')
        self.assertIsNotNone(failure)
        self.assertEqual(failure,dict(sourceCode=38,guardSiteCode=1,depth=0,
            focus=dict(pid=88,kindCode=50011,nativeHwnd=0,rectangle=[-1,-1,1,1]),
            popup=dict(pid=88,hwnd=99,rectangle=[0,0,400,1000]),
            entryFence=dict(childHwnd=56,childPid=88,childRootHwnd=11,childThreadId=9,
                foreground=11,popupHwnd=99,popupThreadId=9,popupRectangle=[0,0,400,1000],ownerChain=[99,56]),
            scope=dict(binding=dict(document=11,parent=55,child=56,officePid=88),
                shellPid=77,shellCreationTime=100,officeCreationTime=200)))
        self.assertFalse(value['success']);self.assertNotIn('inputVerified',value)
        self.assertIsNone(b.probe._source_focus_proof);self.assertEqual(b.probe._source_focus_branch,0)
        self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],[('key','ALT_F')])

    def nested_fixture(self,hook=None):
        m,api,process,record,clock,b,state=self.fixture('outside')
        p=b.probe;state.outside_rectangle=[257,93,464,115]
        state.nested_hwnd=199;state.nested_pid=88;state.nested_thread=9
        state.nested_rect=[255,91,464,373];state.nested_owner=99
        state.original_rect=[0,45,258,427];state.focus_hwnd=0
        state.original_owner=11;state.visible=True;state.enabled=True;state.cloaked=0;state.iconic=False
        state.style=0x94000000;state.extended=0x80;state.class_name='SALTMPSUBFRAME'
        state.pending=False;state.exposures=0;state.events=[]
        def event(name):
            state.events.append(name)
            if hook is not None:hook(name,p,clock,state,b)
        class NewParent(b.Node):
            @property
            def CurrentName(self):raise AssertionError('No unretained parent names')
            @property
            def CurrentBoundingRectangle(self):return NS(left=2,top=95,right=258,bottom=117)
        old_parent=p.uia.iuia.ControlViewWalker.GetParentElement
        def parent(node):
            if node.key=='blank':return NewParent('unretained-new')
            if isinstance(node,NewParent):return b.Node('file')
            return old_parent(node)
        p.uia.iuia.ControlViewWalker.GetParentElement=parent
        client=p._uia.iuia;p.provider_client=client
        client.ConnectionTimeout=client.TransactionTimeout=1
        p._provider_creator=dict(threadId=9,mta=True);p._mta_snapshot=lambda:(9,True)
        p._provider_pending=lambda:state.pending
        old_window=p.window_snapshot
        def window(hwnd):
            event('window')
            if hwnd==299:
                return dict(hwnd=hwnd,pid=88,rootHwnd=hwnd,threadId=9,visible=True,enabled=True,
                    iconic=False,cloaked=0,rectangle=list(state.nested_rect))
            if hwnd==state.nested_hwnd:
                return dict(hwnd=hwnd,pid=state.nested_pid,rootHwnd=hwnd,threadId=state.nested_thread,
                    visible=state.visible,enabled=state.enabled,iconic=state.iconic,cloaked=state.cloaked,
                    rectangle=list(state.nested_rect))
            value=old_window(hwnd);value.update(iconic=False,cloaked=0)
            if hwnd==99:value['rectangle']=list(state.original_rect)
            return value
        p.window_snapshot=window
        def hit(point):
            if (point.x,point.y)==(360,104):event('hit');return state.nested_hwnd
            return b.hit(point)
        p.user.WindowFromPhysicalPoint=hit
        old_owner=p.user.GetWindow
        def owner(hwnd,flag):
            if hwnd==state.nested_hwnd:return state.nested_owner
            if hwnd==299:return 99
            if hwnd==99:return state.original_owner
            return old_owner(hwnd,flag)
        p.user.GetWindow=owner
        def class_name(hwnd,buffer,size):buffer.value=state.class_name;return len(buffer.value)
        p.user.GetClassNameW=class_name
        def style(hwnd,index):return state.style if index==-16 else state.extended
        p.user.GetWindowLongW=style
        exposure=p._popup_exposure
        def measured(*args):
            state.exposures+=1;event('exposure-before')
            value=exposure(*args);event('exposure-return');return value
        p._popup_exposure=measured
        return m,api,process,record,clock,b,state

    def nested_action(self,hook=None):
        m,api,process,record,clock,b,state=self.nested_fixture(hook)
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock):
            value=m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        return m,value,process,record,clock,b,state

    def test_fresh_direct_nested_popup_preserves_the_complete_retained_focus_path(self):
        try:m,value,process,record,clock,b,state=self.nested_action()
        except AssertionError:self.fail('Fresh direct nested popup was rejected before the original keyboard path')
        self.assertTrue(value['success']);self.assertEqual(value['sourceMenu']['focusProtocolVersion'],2)
        self.assertEqual([row['shortcut']for row in value['keys']],['ALT_F','DOWN','ESCAPE'])
        proof=value['keys'][1]['before']['sourceFocus']['proof']
        self.assertEqual(proof['schemaVersion'],2)
        self.assertEqual([row['retainedRole']for row in proof['rows']],[None,None,'file'])
        container=proof['rows'][0]['containment']
        self.assertEqual(container['kindCode'],1);self.assertEqual(container['rowIndex'],0)
        self.assertEqual(container['before']['ownerChain'],[199,99,11]);self.assertEqual(container['before'],container['after'])
        self.assertEqual(proof['rows'][1]['containment'],dict(kindCode=0));self.assertIsNone(proof['rows'][2]['containment'])
        self.assertNotIn('sourceFocusBoundsFailure',value['uiaInterop']);self.assertNotIn('sourceFocusBoundsStructure',value['uiaInterop'])
        self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)

    def test_failed_nested_exposure_releases_the_new_client_reference_with_the_primary_alive(self):
        def fail(name,p,clock,state,b):
            if name=='exposure-return' and state.exposures==2:raise AssertionError()
        m,api,process,record,clock,b,state=self.nested_fixture(fail)
        original=b.probe.provider_client
        class Client:
            def __init__(self,value):self.value=value
            def __getattr__(self,name):return getattr(self.value,name)
        client=Client(original);reference=weakref.ref(client)
        b.probe.provider_client=client;b.probe._uia.iuia=client;del client
        import native_menu_source_selection as selected
        primary=trace=None
        with patch.object(selected.time,'monotonic',clock):
            try:m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
            except AssertionError as error:primary=error;trace=error.__traceback__
        self.assertIsNotNone(primary);self.assertIsNotNone(trace);gc.collect()
        self.assertIsNone(reference())
        self.assertEqual([x for x in b.native.calls if type(x)is tuple and x[0]=='key'],[('key','ALT_F')])

    def assert_nested_rejected(self,hook):
        m,api,process,record,clock,b,state=self.nested_fixture(hook)
        import native_menu_source_selection as selected
        try:
            with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError):
                m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
            self.assertEqual([x for x in b.native.calls if type(x)is tuple and x[0]=='key'],[('key','ALT_F')])
            self.assertFalse(record['nativeMenuActions'][-1]['success'])
            self.assertIsNone(b.probe._source_focus_proof)
            self.assertEqual(b.probe._source_focus_branch,0)
        finally:
            # This fixture's synthetic pending callback has no live OS work.
            state.pending=False;b.probe.close_provider()
        return record,state

    def test_nested_popup_rejects_siblings_deeper_chains_and_unowned_or_incomplete_windows(self):
        cases=(('nested_owner',11),('nested_owner',299),('nested_owner',199),('nested_pid',999),
            ('nested_thread',10),('class_name','OTHER'),('style',0x40000000),('style',0xc0000000),
            ('extended',0),('visible',False),('enabled',False),('cloaked',1),('iconic',True),
            ('nested_rect',[300,100,400,110]),('nested_rect',[255,91,463,373]),
            ('focus_hwnd',99),('focus_hwnd',299))
        for index,(field,value) in enumerate(cases):
            with self.subTest(case=index):
                def change(name,p,clock,state,b):
                    if name=='exposure-before' and state.exposures==1:setattr(state,field,value)
                self.assert_nested_rejected(change)

    def test_nested_popup_hwnd_has_its_own_namespace_and_can_be_the_rows_native_handle(self):
        for hwnd in (199,88):
            with self.subTest(hwnd=hwnd):
                def change(name,p,clock,state,b):
                    if name=='exposure-before':state.nested_hwnd=hwnd
                m,api,process,record,clock,b,state=self.nested_fixture(change)
                state.nested_hwnd=state.focus_hwnd=hwnd
                import native_menu_source_selection as selected
                with patch.object(selected.time,'monotonic',clock):
                    value=m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
                row=value['keys'][1]['before']['sourceFocus']['proof']['rows'][0]
                self.assertEqual(row['observation']['nativeHwnd'],hwnd)
                self.assertEqual(row['containment']['before']['hwnd'],hwnd)
                self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)

    def test_nested_popup_final_refresh_precedes_original_owner_and_fresh_focus_fences(self):
        changes=(lambda p,state,b:setattr(state,'original_rect',[0,45,257,427]),
            lambda p,state,b:setattr(state,'original_owner',56),
            lambda p,state,b:p._identity_scope.update(shellCreationTime=101),
            lambda p,state,b:setattr(p,'provider_client',NS()),
            lambda p,state,b:p._identity_refs.update(file=NS()),
            lambda p,state,b:setattr(p,'_mta_snapshot',lambda:(10,True)),
            lambda p,state,b:b.native.engine.update(creationTime=201),
            lambda p,state,b:setattr(p,'foreground',lambda:1234),
            lambda p,state,b:setattr(p._uia.iuia,'GetFocusedElement',lambda:b.Node('stale')))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                def mutate(name,p,clock,state,b):
                    if name=='exposure-return' and state.exposures==2:change(p,state,b)
                self.assert_nested_rejected(mutate)
        for field,value in (('nested_rect',[255,91,465,373]),('nested_owner',56),('style',0x80000000)):
            with self.subTest(field=field):
                def mutate(name,p,clock,state,b):
                    if name=='exposure-before' and state.exposures==2:setattr(state,field,value)
                self.assert_nested_rejected(mutate)

    def test_nested_popup_pending_or_original_deadline_never_allows_the_next_input(self):
        for boundary in ('exposure-before','exposure-return'):
            for ordinal in (1,2):
                for pending in (False,True):
                    with self.subTest(boundary=boundary,ordinal=ordinal,pending=pending):
                        def stop(name,p,clock,state,b):
                            if name==boundary and state.exposures==ordinal:
                                if pending:state.pending=True
                                else:clock.now=p.deadline
                        self.assert_nested_rejected(stop)

    def test_failed_numeric_structure_never_substitutes_for_fresh_nested_popup_proof(self):
        m,api,process,record,clock,b,state=self.nested_fixture()
        b.probe.interop['sourceFocusBoundsStructure']=dict(diagnosticOnly=1,acceptanceEligible=0,
            complete=1,popup=dict(hwnd=199,ownerChain=[199,99,11]))
        state.nested_owner=11
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError):
            m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        self.assertEqual([x for x in b.native.calls if type(x)is tuple and x[0]=='key'],[('key','ALT_F')])
        self.assertIsNone(b.probe._source_focus_proof)

    def test_existing_contained_focus_does_not_query_nested_exposure_or_creator(self):
        m,api,process,record,clock,b,state=self.fixture()
        def forbidden(*args):raise AssertionError('Contained focus added a nested query')
        b.probe._popup_exposure=forbidden;b.probe._require_provider_creator=forbidden
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock):
            value=m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        self.assertTrue(value['success'])
        self.assertEqual(value['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['containment'],dict(kindCode=0))

    def test_fresh_nested_exposure_does_not_replace_terminal_uia_roles_or_cycle_checks(self):
        for mode in ('peer','cycle','changing-parent'):
            with self.subTest(mode=mode):
                def change(name,p,clock,state,b):
                    if name=='exposure-return' and state.exposures==1:
                        reads=[0]
                        def parent(node):
                            reads[0]+=1
                            if mode=='cycle':return node
                            return b.Node('bar' if mode=='changing-parent' and reads[0]%2==0 else 'peer')
                        p._uia.iuia.ControlViewWalker.GetParentElement=parent
                self.assert_nested_rejected(change)

    def test_nested_exposure_api_fault_or_cancellation_preserves_the_same_primary(self):
        for error_type in (AssertionError,RuntimeError,KeyboardInterrupt,SystemExit):
            with self.subTest(errorCode=(AssertionError,RuntimeError,KeyboardInterrupt,SystemExit).index(error_type)):
                primary=error_type()
                def fail(name,p,clock,state,b):
                    if name=='exposure-return' and state.exposures==2:raise primary
                m,api,process,record,clock,b,state=self.nested_fixture(fail)
                import native_menu_source_selection as selected
                with patch.object(selected.time,'monotonic',clock),self.assertRaises(error_type)as caught:
                    m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
                self.assertIs(caught.exception,primary)
                self.assertEqual([x for x in b.native.calls if type(x)is tuple and x[0]=='key'],[('key','ALT_F')])
                self.assertIsNone(b.probe._source_focus_proof)

    def test_nonempty_nested_row_runtime_is_observation_without_new_role_or_input_plan(self):
        m,api,process,record,clock,b,state=self.nested_fixture()
        runtime=b.Node.GetRuntimeId
        b.Node.GetRuntimeId=lambda node:[5,-7,321]if node.key=='blank'else runtime(node)
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock):
            value=m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        row=value['keys'][1]['before']['sourceFocus']['proof']['rows'][0]
        self.assertEqual(row['observation']['runtimeId'],[5,-7,321]);self.assertIsNone(row['retainedRole'])
        self.assertTrue(all(same is False for same in row['differentFrom'].values()))
        self.assertEqual([key['shortcut']for key in value['keys']],['ALT_F','DOWN','ESCAPE'])
        self.assertIs(m.require_native_menu_action(value,77,11,source_admission=self.prepared.admission),value)

    def test_nested_popup_receipt_requires_closed_per_row_versioned_before_after_proof(self):
        m,value,process,record,clock,b,state=self.nested_action()
        def proof(p):return p['keys'][1]['before']['sourceFocus']['proof']
        def container(p):return proof(p)['rows'][0]['containment']
        changes=(lambda p:p['sourceMenu'].update(focusProtocolVersion=1),
            lambda p:p['keys'][1]['before']['sourceFocus'].update(protocolVersion=1),
            lambda p:proof(p).update(schemaVersion=1),
            lambda p:proof(p)['rows'][0].pop('containment'),
            lambda p:proof(p)['rows'][0].update(containment=None),
            lambda p:container(p).update(kindCode=True),
            lambda p:container(p).update(kindCode=2),
            lambda p:proof(p)['rows'][0].update(containment=dict(kindCode=0)),
            lambda p:container(p).update(rowIndex=True),
            lambda p:container(p).update(rowIndex=1),
            lambda p:container(p).pop('rowIndex'),
            lambda p:container(p).update(extra=0),
            lambda p:container(p).update(after=None),
            lambda p:container(p).update(beforeAt=float('nan')),
            lambda p:container(p).update(afterAt=p['deadline']),
            lambda p:container(p).update(beforeAt=p['startedAt']-1),
            lambda p:container(p).update(beforeAt=container(p)['afterAt']+0.01),
            lambda p:proof(p)['rows'][-1].update(containment=dict(kindCode=0)),
            lambda p:proof(p)['rows'][1].update(containment=copy.deepcopy(container(p))),
            lambda p:proof(p).update(focusEndEquals=False),
            lambda p:proof(p)['edges'][0].update(parentFreshEquals=False),
            lambda p:proof(p)['rows'][0]['differentFrom'].update(file=True),
            lambda p:proof(p)['rows'][1].update(differentFromPrior=[True]),
            lambda p:proof(p)['scope'].update(shellCreationTime=101),
            lambda p:proof(p)['after'].update(ownerChain=[99,56]))
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                altered=copy.deepcopy(value);change(altered)
                with self.assertRaises((AssertionError,KeyError,TypeError)):
                    m.require_native_menu_action(altered,77,11,source_admission=self.prepared.admission)

    def test_nested_popup_receipt_rejects_malformed_changed_or_merely_point_contained_exposures(self):
        m,value,process,record,clock,b,state=self.nested_action()
        changes=(lambda d:d.update(classCode=True),lambda d:d.update(pid=True),lambda d:d.update(pid=999),
            lambda d:d.update(threadId=10),lambda d:d.update(hwnd=99),lambda d:d.update(rootHwnd=99),
            lambda d:d.update(foreground=199),lambda d:d.update(style=0xc0000000),
            lambda d:d.update(extendedStyle=0),lambda d:d.update(ownershipBefore=1),
            lambda d:d.update(ownerChain=[199,11]),lambda d:d.update(ownerChain=[199,299,99,11]),
            lambda d:d.update(ownerChain=[199,99,56]),lambda d:d.update(ownerChain=[199,99,99,11]),
            lambda d:d.update(ownerChain=[199,99,True]),lambda d:d.update(point=[359,104]),
            lambda d:d.update(point=[360.,104]),lambda d:d.update(rectangle=[300,100,400,110]),
            lambda d:d.update(rectangle=[255,91,463,373]),lambda d:d.update(rectangle=[255,91,True,373]),
            lambda d:d.update(rectangle=[255.,91,464,373]),lambda d:d.pop('classCode'),
            lambda d:d.update(diagnosticOnly=1))
        for index,change in enumerate(changes):
            for edge in ('before','after'):
                with self.subTest(case=index,edge=edge):
                    altered=copy.deepcopy(value)
                    change(altered['keys'][1]['before']['sourceFocus']['proof']['rows'][0]['containment'][edge])
                    with self.assertRaises((AssertionError,KeyError)):
                        m.require_native_menu_action(altered,77,11,source_admission=self.prepared.admission)

    def bounds_structure_fixture(self,*,parents=2,same_popup=False,hook=None):
        m,api,process,record,clock,b,state=self.fixture('outside')
        p=b.probe;state.outside_rectangle=[257,93,464,115]
        state.phase=False;state.events=[];state.primary=None;state.temporary=[];state.after_observer=None
        state.pending=False;state.parent_pid=88;state.parent_kind=50010;state.parent_hwnd=199
        state.parent_rect=[257,45,465,427];state.popup_hwnd=199
        def event(name):
            if state.phase:
                state.events.append(name)
                if hook is not None:hook(name,p,clock,state,b)
        class Parent(b.Node):
            def __init__(self,index):super().__init__('observed-parent');self.index=index
            @property
            def CurrentName(self):raise AssertionError('No parent name reads')
            def GetRuntimeId(self):raise AssertionError('No parent runtime ID reads')
            @property
            def CurrentProcessId(self):event('parent-pid');return state.parent_pid
            @property
            def CurrentControlType(self):event('parent-kind');return state.parent_kind
            @property
            def CurrentNativeWindowHandle(self):event('parent-hwnd');return state.parent_hwnd
            @property
            def CurrentBoundingRectangle(self):
                event('parent-rect');return NS(**dict(zip(('left','top','right','bottom'),state.parent_rect)))
        class Walker:
            def GetParentElement(self,node):
                event('parent')
                index=node.index+1 if isinstance(node,Parent)else 0
                if index>=parents:return None
                result=Parent(index);state.temporary.append(weakref.ref(result));return result
        client=p.uia.iuia
        class Client:
            def __getattr__(self,name):
                if state.phase and name=='ControlViewWalker':
                    event('walker');result=Walker();state.temporary.append(weakref.ref(result));return result
                return getattr(client,name)
        p.provider_client=Client();p.uia.iuia=p.provider_client
        p.provider_client.ConnectionTimeout=p.provider_client.TransactionTimeout=1
        p._provider_creator=dict(threadId=9,mta=True)
        def creator():event('creator');return (9,True)
        p._mta_snapshot=creator
        original_pending=p._provider_pending
        p._provider_pending=lambda:state.pending if state.phase else original_pending()
        original_window=p.window_snapshot
        def window(hwnd):
            event('window')
            if hwnd==state.popup_hwnd:return dict(hwnd=hwnd,pid=88,rootHwnd=hwnd,threadId=9,visible=True,enabled=True,
                iconic=False,cloaked=0,rectangle=[257,45,465,427])
            value=original_window(hwnd);value.update(iconic=False,cloaked=0)
            if hwnd==99:value['rectangle']=[0,45,258,427]
            return value
        p.window_snapshot=window
        def hit(point):
            if state.phase:event('point');return 99 if same_popup else state.popup_hwnd
            return b.hit(point)
        p.user.WindowFromPhysicalPoint=hit
        original_owner=p.user.GetWindow
        p.user.GetWindow=lambda hwnd,flag:99 if hwnd==state.popup_hwnd else original_owner(hwnd,flag)
        def class_name(hwnd,buffer,size):event('class');buffer.value='SALTMPSUBFRAME';return len(buffer.value)
        p.user.GetClassNameW=class_name
        def style(hwnd,index):event('style');return 0x80000000 if index==-16 else 0x80
        p.user.GetWindowLongW=style
        original_exposure=p._popup_exposure
        def exposure(*args):event('popup');return original_exposure(*args)
        p._popup_exposure=exposure
        class Sink(dict):
            def __setitem__(self,key,value):
                if key=='sourceFocusBoundsFailure':
                    state.primary=sys.exception();state.phase=True;event('entry')
                if key=='sourceFocusBoundsStructure':event('structure-sink')
                return super().__setitem__(key,value)
        p.interop=Sink(p.interop)
        observer=getattr(p,'_observe_failed_source_focus_bounds',None)
        if observer is not None:
            def observed(*args):
                names=('_diagnostic_sink','_observed_call','_last_call_exception','provider_timeout_verified')
                state.before_observer={name:(name in vars(p),getattr(p,name,None))for name in names}
                state.original_last_call=p.interop.get('lastCall')
                observer(*args)
                state.after_observer={name:(name in vars(p),getattr(p,name,None))for name in names}
                state.after_last_call=p.interop.get('lastCall');state.pending=False
            p._observe_failed_source_focus_bounds=observed
        return m,api,process,record,clock,b,state

    def bounds_structure_action(self,**options):
        m,api,process,record,clock,b,state=self.bounds_structure_fixture(**options)
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError)as caught:
            m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        self.assertIs(caught.exception,state.primary)
        value=record['nativeMenuActions'][-1]
        self.assertFalse(value['success']);self.assertNotIn('inputVerified',value)
        self.assertIsNone(b.probe._source_focus_proof);self.assertEqual(b.probe._source_focus_branch,0)
        self.assertEqual([x for x in b.native.calls if type(x)is tuple and x[0]=='key'],[('key','ALT_F')])
        return value,b,state

    def test_recorded_outside_bounds_get_numeric_parent_and_owned_popup_observation_without_input_authority(self):
        value,b,state=self.bounds_structure_action()
        row=value['uiaInterop'].get('sourceFocusBoundsStructure')
        self.assertIsNotNone(row)
        self.assertEqual((row['diagnosticOnly'],row['acceptanceEligible'],row['complete']),(1,0,1))
        self.assertEqual(len(row['parents']),2);self.assertEqual(state.events.count('parent'),2)
        self.assertEqual(row['point'],[360,104]);self.assertEqual(state.events.count('point'),1)
        self.assertEqual(row['popup']['hwnd'],199)
        self.assertEqual(row['parents'][0],dict(pid=88,kindCode=50010,nativeHwnd=199,rectangle=[257,45,465,427]))
        self.assertEqual(value['uiaInterop']['sourceFocusBoundsFailure']['popup']['hwnd'],99)
        self.assertEqual(state.before_observer,state.after_observer)
        self.assertIs(state.original_last_call,state.after_last_call)
        self.assertTrue(all(ref()is None for ref in state.temporary))

    def test_failed_bounds_parent_walk_is_capped_at_two_and_zero_parent_still_has_no_authority(self):
        for count,queries,rows in ((0,1,0),(1,2,1),(2,2,2),(3,2,2)):
            with self.subTest(parentLimit=count):
                value,b,state=self.bounds_structure_action(parents=count)
                row=value['uiaInterop']['sourceFocusBoundsStructure']
                self.assertEqual(row['complete'],1);self.assertEqual(len(row['parents']),rows)
                self.assertEqual(state.events.count('parent'),queries)
                self.assertEqual(state.events.count('popup'),1)
                self.assertTrue(all(ref()is None for ref in state.temporary))

    def test_same_popup_outside_rect_does_not_replace_the_original_popup_or_make_focus_usable(self):
        value,b,state=self.bounds_structure_action(same_popup=True)
        row=value['uiaInterop']['sourceFocusBoundsStructure']
        self.assertEqual((row['known'],row['complete']),(0,0));self.assertEqual(row['popup'],{})
        self.assertEqual(value['uiaInterop']['sourceFocusBoundsFailure']['popup']['hwnd'],99)
        self.assertEqual(state.events.count('popup'),1);self.assertEqual(state.events.count('point'),1)

    def test_valid_owned_popup_hwnd_can_equal_the_pid_in_a_different_namespace(self):
        def same_number(name,p,clock,state,b):
            if name=='entry':state.popup_hwnd=state.parent_hwnd=88
        value,b,state=self.bounds_structure_action(hook=same_number)
        row=value['uiaInterop']['sourceFocusBoundsStructure']
        self.assertEqual((row['complete'],row['popup'].get('hwnd')),(1,88))

    def test_foreign_or_malformed_parent_is_unknown_and_never_reaches_popup_observation(self):
        cases=(('parent_pid',999,5),('parent_pid',True,6),('parent_kind',True,6),('parent_kind',49999,6),
            ('parent_hwnd',False,6),('parent_hwnd',1<<32,6),('parent_rect',[257.,45,465,427],6),
            ('parent_rect',[257,45,257,427],6),('parent_rect',[True,45,465,427],6))
        for key,number,code in cases:
            with self.subTest(field=key,caseCode=code):
                def change(name,p,clock,state,b):
                    if name=='entry':setattr(state,key,number)
                value,b,state=self.bounds_structure_action(hook=change)
                row=value['uiaInterop']['sourceFocusBoundsStructure']
                self.assertEqual((row['statusCode'],row['known'],row['complete']),(code,0,0))
                self.assertEqual(state.events.count('parent'),1);self.assertNotIn('popup',state.events)

    def test_deadline_at_each_direct_boundary_stays_unknown_and_preserves_original_failure(self):
        for boundary in ('entry','walker','parent','parent-pid','parent-kind','parent-hwnd','parent-rect','point'):
            with self.subTest(boundary=boundary):
                def expire(name,p,clock,state,b):
                    if name==boundary:clock.now=p.deadline
                value,b,state=self.bounds_structure_action(hook=expire)
                row=value['uiaInterop']['sourceFocusBoundsStructure']
                self.assertEqual((row['known'],row['complete']),(0,0));self.assertIn(row['statusCode'],(2,7))
                self.assertLessEqual(state.events.count('parent'),2);self.assertLessEqual(state.events.count('popup'),1)
                if boundary=='entry':self.assertNotIn('walker',state.events)

    def test_pending_at_each_direct_boundary_prevents_the_next_direct_query(self):
        for boundary in ('entry','walker','parent','parent-pid','parent-kind','parent-hwnd','parent-rect','point'):
            with self.subTest(boundary=boundary):
                def pending(name,p,clock,state,b):
                    if name==boundary:state.pending=True
                value,b,state=self.bounds_structure_action(hook=pending)
                row=value['uiaInterop']['sourceFocusBoundsStructure']
                self.assertEqual((row['statusCode'],row['known'],row['complete']),(3,0,0))
                if boundary=='entry':self.assertNotIn('creator',state.events);self.assertNotIn('walker',state.events)
                if boundary not in ('point','entry'):self.assertNotIn('popup',state.events)

    def test_scope_client_generation_or_foreground_change_stays_unknown_without_new_input(self):
        changes=(lambda p,b:p._identity_scope.update(shellCreationTime=101),
            lambda p,b:setattr(p,'provider_client',NS()),
            lambda p,b:p._identity_refs.update(file=NS()),
            lambda p,b:setattr(p,'_source_focus_popup',dict(p._source_focus_popup)),
            lambda p,b:b.native.engine.update(creationTime=201),
            lambda p,b:setattr(p,'foreground',lambda:1234),
            lambda p,b:setattr(p,'_mta_snapshot',lambda:(100,True)))
        for index,change in enumerate(changes):
            with self.subTest(changeCode=index):
                def mutate(name,p,clock,state,b):
                    if name=='parent-pid':change(p,b)
                value,b,state=self.bounds_structure_action(hook=mutate)
                row=value['uiaInterop']['sourceFocusBoundsStructure']
                self.assertEqual((row['known'],row['complete']),(0,0));self.assertIn(row['statusCode'],(4,7))

    def test_diagnostic_faults_and_cancellation_preserve_primary_context_and_temporary_release(self):
        for boundary in ('structure-sink','creator','walker','parent','parent-pid','parent-kind','parent-hwnd','parent-rect','popup','point','class','style'):
            for error_type in (RuntimeError,KeyboardInterrupt,SystemExit):
                with self.subTest(boundary=boundary,errorCode=(RuntimeError,KeyboardInterrupt,SystemExit).index(error_type)):
                    def fail(name,p,clock,state,b):
                        if name==boundary:raise error_type()
                    value,b,state=self.bounds_structure_action(hook=fail)
                    row=value['uiaInterop'].get('sourceFocusBoundsStructure')
                    if row is not None:self.assertEqual((row['known'],row['complete']),(0,0))
                    self.assertEqual(state.before_observer,state.after_observer)
                    self.assertIs(state.original_last_call,state.after_last_call)
                    gc.collect();self.assertTrue(all(ref()is None for ref in state.temporary))

    def test_missing_or_present_diagnostic_context_is_restored_exactly(self):
        names=('_diagnostic_sink','_observed_call','_last_call_exception','provider_timeout_verified')
        for present in (False,True):
            with self.subTest(present=present):
                def context(name,p,clock,state,b):
                    if name=='entry':
                        for key in names:
                            if present:setattr(p,key,False if key=='provider_timeout_verified'else {})
                            else:vars(p).pop(key,None)
                value,b,state=self.bounds_structure_action(hook=context)
                self.assertEqual(value['uiaInterop']['sourceFocusBoundsStructure']['complete'],1)
                for key in names:
                    self.assertEqual(state.before_observer[key][0],present)
                    self.assertEqual(state.after_observer[key][0],present)
                    self.assertIs(state.before_observer[key][1],state.after_observer[key][1])

    def test_clock_failure_is_unknown_and_non_source_success_adds_no_observation(self):
        for error_type in (RuntimeError,KeyboardInterrupt,SystemExit):
            def fail_clock(name,p,clock,state,b):
                if name=='entry':
                    def failed():raise error_type()
                    p.clock=failed
            value,b,state=self.bounds_structure_action(hook=fail_clock)
            self.assertEqual(value['uiaInterop']['sourceFocusBoundsStructure']['complete'],0)
        owner=old.OwnedNativeMenuTests('runTest');self.addCleanup(owner.doCleanups)
        m,api,process,record,clock,b=owner.real_chrome_fixture()
        def forbidden(*args):raise AssertionError('Non-source path added a bounds observer')
        b.probe._observe_failed_source_focus_bounds=forbidden
        value=m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        self.assertTrue(value['success']);self.assertNotIn('sourceFocusBoundsStructure',value['uiaInterop'])

    def test_invalid_rectangle_rejection_does_not_claim_containment_observation(self):
        m,api,process,record,clock,b,state=self.fixture('invalid-rect')
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError):
            m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        value=record['nativeMenuActions'][-1]
        self.assertNotIn('sourceFocusBoundsFailure',value['uiaInterop'])
        self.assertFalse(value['success']);self.assertNotIn('inputVerified',value)
        self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],[('key','ALT_F')])

    def test_containment_recorder_failure_preserves_the_original_assertion_identity(self):
        m,api,process,record,clock,b,state=self.fixture('outside')
        original=[]
        class RecorderFailure(Exception):
            def __str__(self):raise AssertionError('No recorder exception text read')
        class ThrowingSink(dict):
            def __setitem__(self,key,value):
                if key=='sourceFocusBoundsFailure':
                    original.append(sys.exception())
                    raise RecorderFailure()
                return super().__setitem__(key,value)
        b.probe.interop=ThrowingSink(b.probe.interop)
        import native_menu_source_selection as selected
        with patch.object(selected.time,'monotonic',clock),self.assertRaises(AssertionError) as caught:
            m.inspect_native_menu(api,process,11,record,'keyboard-escape',probe=b.probe,clock=clock)
        self.assertEqual(len(original),1);self.assertIs(caught.exception,original[0])
        self.assertNotIn('sourceFocusBoundsFailure',record['nativeMenuActions'][-1]['uiaInterop'])
        self.assertFalse(record['nativeMenuActions'][-1]['success'])
        self.assertEqual([item for item in b.native.calls if type(item)is tuple and item[0]=='key'],[('key','ALT_F')])

    def test_source_replay_requires_current_protocol_and_complete_closed_proof(self):
        m,value,process,record,clock,b,state=self.action()
        self.assertEqual(value['sourceMenu']['focusProtocolVersion'],2)
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
