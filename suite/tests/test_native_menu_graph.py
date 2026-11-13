"""Synthetic physical File header admission; no actual UI or input."""
import unittest

import test_owned_native_menu as boundaries


class NativeMenuGraphTests(unittest.TestCase):
    def fixture(self):
        owner=boundaries.OwnedNativeMenuTests(methodName='runTest')
        self.addCleanup(owner.doCleanups)
        module,api,process,record,clock,boundary=owner.real_chrome_fixture()
        probe=boundary.probe;binding=dict(document=11,parent=55,child=56,officePid=88)
        probe.begin_identity_scope(binding,boundary.native.shell,boundary.native.engine,1.,6.,'save',False)
        root=probe._root(56)
        probe.file_element=probe.discover_file(root)
        for role,element in (('file',probe.file_element),('bar',probe.menu_bar_element),('peer',root),
                ('contrast-edit',probe._find_labels(probe.menu_bar_element,module.EDIT_CONTRAST,scope='children'))):
            probe._bind_ref(role,element)
        probe._physical_file_refresh=True
        probe._active_target='save'
        probe._menu_classification_context=(module._menu_scope(binding,boundary.native.shell,
            boundary.native.engine,1.,6.),lambda:None)
        calls=[]
        original=probe.uia.iuia.ElementFromHandle
        probe.uia.iuia.ElementFromHandle=lambda hwnd:calls.append(('handle',hwnd)) or original(hwnd)
        return module,probe,boundary,clock,binding,calls

    def test_refresh_starts_at_fresh_global_file_and_walks_to_original_peer(self):
        module,probe,boundary,clock,binding,calls=self.fixture()
        originals=dict(probe._identity_refs)
        fresh=probe._physical_base()
        self.assertEqual(set(fresh),{'file','bar','peer','contrast-edit'})
        self.assertTrue(all(fresh[key].key==originals[key].key for key in fresh))
        self.assertTrue(all(fresh[key] is not originals[key] for key in fresh))
        self.assertEqual(calls,[])
        self.assertEqual(probe._identity_refs,originals)
        proof=probe.interop['graphRefresh']
        self.assertEqual(proof['method'],'physical-file-header-parent-walk')
        self.assertEqual(proof['point'],[50,30])
        self.assertEqual(proof['physicalHit'],dict(hwnd=56,pid=88,threadId=9,rootHwnd=11))
        self.assertTrue(proof['fileEqualsRetained'])
        self.assertTrue(all(value is False for value in proof['differentFrom'].values()))
        self.assertEqual([row['kindCode'] for row in proof['ancestry']],[50011,50010,50032])
        self.assertTrue(proof['ownershipBefore'] and proof['ownershipAfter'])

    def test_fresh_proof_uses_physical_endpoint_without_new_child_mapping(self):
        module,probe,boundary,clock,binding,calls=self.fixture()
        proof=probe._fresh_proof('file')
        self.assertTrue(all(proof['positive'].values()))
        self.assertTrue(all(row[2] is False for row in proof['negative']))
        self.assertEqual(calls,[])

    def test_first_admission_seeds_contrast_before_physical_refresh(self):
        module,probe,boundary,clock,binding,calls=self.fixture()
        del probe._identity_refs['contrast-edit']
        proof=probe._fresh_proof('file')
        self.assertTrue(all(proof['positive'].values()))
        self.assertEqual(calls,[('handle',56)])
        self.assertEqual(probe.interop['graphRefresh']['method'],'physical-file-header-parent-walk')

    def test_wrong_physical_window_or_pid_or_thread_or_root_blocks_before_uia(self):
        for damage in ('window','pid','thread','root'):
            with self.subTest(damage=damage):
                module,probe,boundary,clock,binding,calls=self.fixture();uia=[]
                probe.uia.iuia.ElementFromPoint=lambda point:uia.append(1) or boundary.Node('file')
                if damage=='window':probe.user.WindowFromPhysicalPoint=lambda point:99
                elif damage=='root':probe.user.GetAncestor=lambda hwnd,flag:99
                else:
                    def pid(hwnd,pointer):
                        pointer._obj.value=99 if damage=='pid' else 88
                        return 8 if damage=='thread' else 9
                    probe.user.GetWindowThreadProcessId=pid
                with self.assertRaises(AssertionError):probe._physical_base()
                self.assertEqual(uia,[])

    def test_global_file_false_or_aliased_contrast_blocks(self):
        for damage in ('point','alias'):
            with self.subTest(damage=damage):
                module,probe,boundary,clock,binding,calls=self.fixture()
                if damage=='point':probe.uia.iuia.ElementFromPoint=lambda point:boundary.Node('edit')
                else:
                    compare=boundary.compare
                    probe.uia.iuia.CompareElements=lambda left,right:True if {left.key,right.key}=={'file','edit'} else compare(left,right)
                with self.assertRaises(AssertionError):probe._physical_base()

    def test_live_parent_walk_rejects_wrong_peer_and_foreign_ancestor(self):
        for damage in ('peer','foreign','loop'):
            with self.subTest(damage=damage):
                module,probe,boundary,clock,binding,calls=self.fixture()
                parent=boundary.parent
                probe.uia.iuia.ControlViewWalker.GetParentElement=lambda node:(
                    boundary.Node('host') if node.key=='bar' and damage in ('peer','foreign') else
                    boundary.Node('file') if damage=='loop' else parent(node))
                with self.assertRaises(AssertionError):probe._physical_base()

    def test_changed_attachment_or_foreground_and_late_result_block(self):
        for damage in ('attachment','foreground','late'):
            with self.subTest(damage=damage):
                module,probe,boundary,clock,binding,calls=self.fixture()
                if damage=='attachment':probe.attachment_snapshot=lambda binding:dict(valid=False,windows={'child':{'threadId':9}})
                elif damage=='foreground':probe.foreground=lambda:99
                else:
                    point=probe.uia.iuia.ElementFromPoint
                    probe.uia.iuia.ElementFromPoint=lambda value:setattr(clock,'now',6.) or point(value)
                with self.assertRaises(AssertionError):probe._physical_base()

    def popup_fixture(self):
        module,probe,boundary,clock,binding,calls=self.fixture()
        state=dict(className='SALTMPSUBFRAME',style=0x80000000,extendedStyle=0x80)
        original=probe.window_snapshot
        def window(hwnd):
            return dict(original(hwnd),rectangle=[0,45,258,689] if hwnd==99 else [0,0,800,900],
                iconic=False,cloaked=0)
        probe.window_snapshot=window
        def class_name(hwnd,buffer,size):
            buffer.value=state['className'];return len(state['className'])
        probe.user.GetClassNameW=class_name
        probe.user.GetWindowLongW=lambda hwnd,index:state['style' if index==-16 else 'extendedStyle']
        return probe,boundary,binding,state,clock

    def test_popup_requires_pinned_class_styles_original_owner_and_exact_global_window(self):
        probe,boundary,binding,state,clock=self.popup_fixture()
        proof=probe._popup_exposure(binding,[50,70],[20,60,80,80])
        self.assertEqual(proof['classCode'],1)
        self.assertEqual(proof['style'],0x80000000)
        self.assertEqual(proof['extendedStyle'],0x80)
        self.assertEqual(proof['ownerChain'],[99,56])
        self.assertEqual(proof['threadId'],9)
        self.assertTrue(proof['ownershipBefore'] and proof['ownershipAfter'])

    def test_popup_rejects_other_sal_class_styles_occlusion_and_moved_bounds(self):
        for damage in ('class','child-style','no-popup-style','no-tool-style','hit','bounds','owner','thread'):
            with self.subTest(damage=damage):
                probe,boundary,binding,state,clock=self.popup_fixture()
                if damage=='class':state['className']='SALSUBFRAME'
                elif damage=='child-style':state['style']|=0x40000000
                elif damage=='no-popup-style':state['style']=0
                elif damage=='no-tool-style':state['extendedStyle']=0
                elif damage=='hit':probe.user.WindowFromPhysicalPoint=lambda point:56
                elif damage=='bounds':
                    original=probe.window_snapshot
                    probe.window_snapshot=lambda hwnd:dict(original(hwnd),rectangle=[0,45,70,65]) if hwnd==99 else original(hwnd)
                elif damage=='owner':probe.user.GetWindow=lambda hwnd,flag:0
                else:
                    original=probe.window_snapshot
                    probe.window_snapshot=lambda hwnd:dict(original(hwnd),threadId=8) if hwnd==99 else original(hwnd)
                with self.assertRaises(AssertionError):probe._popup_exposure(binding,[50,70],[20,60,80,80])


if __name__=='__main__':unittest.main()
