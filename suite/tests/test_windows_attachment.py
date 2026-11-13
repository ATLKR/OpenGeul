"""The actual Windows API owner supplies read-only native-menu attachment proof."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

E2E=Path(__file__).resolve().parents[1]/'e2e'
sys.path.insert(0,str(E2E))
import owned_native_menu as menu
from test_owned_native_menu import Clock,Probe

spec=importlib.util.spec_from_file_location('attachment_windows_smoke',E2E/'windows_smoke.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
PARENT='OpenGeul.Office.ParentHwnd'
CHILD='OpenGeul.Office.ChildHwnd'


class User32:
    def __init__(self):
        self.properties={(11,PARENT):55,(11,CHILD):56,(11,menu.READY_PROPERTY):1}
        self.pids={11:77,55:77,56:88};self.threads={11:7,55:7,56:9}
        self.live={11,55,56};self.roots={11:11,55:11,56:11}
        self.children={(11,55),(55,56),(11,56)}
        self.calls=[];self.counts={};self.mutate=None
    def call(self,name,*args):
        key=(name,*args);self.calls.append(key);count=self.counts.get(key,0)+1;self.counts[key]=count
        if self.mutate:self.mutate(name,args,count)
    def IsWindow(self,hwnd):self.call('IsWindow',hwnd);return hwnd in self.live
    def GetAncestor(self,hwnd,kind):
        self.call('GetAncestor',hwnd,kind);assert kind==2;return self.roots.get(hwnd,0)
    def GetPropW(self,hwnd,name):
        self.call('GetPropW',hwnd,name);return self.properties.get((hwnd,name))
    def GetWindowThreadProcessId(self,hwnd,pointer):
        self.call('GetWindowThreadProcessId',hwnd)
        if pointer is not None:pointer._obj.value=self.pids.get(hwnd,0)
        return self.threads.get(hwnd,0)
    def IsChild(self,parent,child):self.call('IsChild',parent,child);return (parent,child) in self.children


class WindowsAttachmentTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name).resolve();out=root/'evidence';out.mkdir()
        clock=Clock();probe=Probe(root,clock);probe.close_provider=lambda:True
        api=object.__new__(native.Windows);api.user=User32()
        process=NS(pid=77,_handle=8,args=[str(root/'OpenGeul.Office.exe')],poll=lambda:None,
            opengeul_suite_root=root,opengeul_evidence_output=out,opengeul_evidence_case='native-attachment')
        record=dict(windowHwnd=11,parentHwnd=55,childHwnd=56,officePid=88)
        return api,process,record,clock,probe
    def run_menu(self,api,process,record,clock,probe):
        return menu._run(api,process,11,record,'open-escape',gesture=True,probe=probe,clock=clock)
    def no_input(self,probe):
        self.assertFalse(any(isinstance(call,tuple) and call[0] in ('click','key') for call in probe.calls))

    def test_actual_windows_owner_reaches_native_open_escape_without_an_api_stub(self):
        api,process,record,clock,probe=self.fixture()
        self.assertIs(type(api),native.Windows)
        self.assertNotIn('attachment',api.__dict__)
        result=self.run_menu(api,process,record,clock,probe)
        self.assertTrue(result['success']);self.assertTrue(result['engineHandleReleased'])
        self.assertTrue(result['providerClientReleased']);self.assertTrue(result['dpiScope']['restored'])
        self.assertEqual(result['binding'],dict(document=11,parent=55,child=56,officePid=88))
        self.assertEqual([call for call in probe.calls if isinstance(call,tuple) and call[0] in ('click','key')],
            [('click','file'),('key','ESCAPE')])
        self.assertLess(result['finishedAt'],result['deadline'])
        self.assertIs(menu.require_native_menu_action(result,77,11),result)

    def test_readonly_api_rechecks_export_pids_and_roots_without_ui_state_requirements(self):
        api,process,record,clock,probe=self.fixture()
        self.assertEqual(api.attachment(11),(55,56,88))
        for name in (PARENT,CHILD):self.assertEqual(api.user.counts[('GetPropW',11,name)],2)
        for hwnd in (11,55,56):
            self.assertEqual(api.user.counts[('GetWindowThreadProcessId',hwnd)],2)
            self.assertGreaterEqual(api.user.counts[('IsWindow',hwnd)],2)
            self.assertGreaterEqual(api.user.counts[('GetAncestor',hwnd,2)],2)
        self.assertEqual(set(call[0] for call in api.user.calls),
            {'IsWindow','GetAncestor','GetPropW','GetWindowThreadProcessId','IsChild'})
        self.no_input(probe)

    def test_non_handle_documents_are_rejected_before_native_queries(self):
        for document in (None,True,False,0,-1,1.,'11',1<<64):
            with self.subTest(document=document):
                api,process,record,clock,probe=self.fixture()
                with self.assertRaises(AssertionError):api.attachment(document)
                self.assertEqual(api.user.calls,[]);self.no_input(probe)

    def test_invalid_or_aliased_fixed_properties_fail_before_menu_input(self):
        for name in (PARENT,CHILD):
            for value in (None,True,0,-1,1.,'55',1<<64,11,56 if name==PARENT else 55):
                with self.subTest(name=name,value=value):
                    api,process,record,clock,probe=self.fixture();api.user.properties[11,name]=value
                    with self.assertRaises(AssertionError):self.run_menu(api,process,record,clock,probe)
                    self.no_input(probe)

    def test_dead_foreign_reparented_or_unowned_windows_fail_before_menu_input(self):
        cases=('dead-document','dead-parent','dead-child','document-not-root','foreign-parent',
            'zero-document-pid','zero-child-pid','shell-owned-child','foreign-parent-root','foreign-child-root',
            'parent-not-child','editor-not-child','dead-thread')
        for reason in cases:
            with self.subTest(reason=reason):
                api,process,record,clock,probe=self.fixture();user=api.user
                if reason.startswith('dead-') and reason!='dead-thread':
                    user.live.remove({'dead-document':11,'dead-parent':55,'dead-child':56}[reason])
                elif reason=='document-not-root':user.roots[11]=99
                elif reason=='foreign-parent':user.pids[55]=99
                elif reason=='zero-document-pid':user.pids[11]=user.pids[55]=0
                elif reason=='zero-child-pid':user.pids[56]=0
                elif reason=='shell-owned-child':user.pids[56]=77
                elif reason=='foreign-parent-root':user.roots[55]=99
                elif reason=='foreign-child-root':user.roots[56]=99
                elif reason=='parent-not-child':user.children.remove((11,55))
                elif reason=='editor-not-child':user.children.remove((55,56))
                else:user.threads[56]=0
                with self.assertRaises(AssertionError):self.run_menu(api,process,record,clock,probe)
                self.no_input(probe)

    def test_changed_export_or_reused_native_identity_is_not_readmitted(self):
        for reason in ('parent-export','child-export','document-pid','child-pid','child-thread','dead-child','reparent'):
            with self.subTest(reason=reason):
                api,process,record,clock,probe=self.fixture();user=api.user;changed=[]
                def mutate(name,args,count):
                    if count!=2:return
                    if reason in ('parent-export','child-export') and (name,args)==('GetPropW',(11,PARENT)):
                        if reason=='parent-export':
                            user.properties[11,PARENT]=57;user.pids[57]=77;user.threads[57]=7
                            user.roots[57]=11;user.live.add(57);user.children.update(((11,57),(57,56)))
                        else:
                            user.properties[11,CHILD]=57;user.pids[57]=88;user.threads[57]=9
                            user.roots[57]=11;user.live.add(57);user.children.update(((11,57),(55,57)))
                    elif reason=='document-pid' and (name,args)==('GetWindowThreadProcessId',(11,)):
                        user.pids[11]=user.pids[55]=99
                    elif reason=='child-pid' and (name,args)==('GetWindowThreadProcessId',(56,)):user.pids[56]=99
                    elif reason=='child-thread' and (name,args)==('GetWindowThreadProcessId',(56,)):user.threads[56]=99
                    elif reason=='dead-child' and (name,args)==('IsWindow',(56,)):user.live.remove(56)
                    elif reason=='reparent' and (name,args)==('IsChild',(55,56)):user.children.remove((55,56))
                    else:return
                    changed.append(reason)
                user.mutate=mutate
                with self.assertRaises(AssertionError):self.run_menu(api,process,record,clock,probe)
                self.assertEqual(changed,[reason]);self.no_input(probe)

    def test_new_valid_attachment_does_not_replace_the_original_menu_recipient(self):
        api,process,record,clock,probe=self.fixture();api.user.pids[56]=99
        self.assertEqual(api.attachment(11),(55,56,99))
        with self.assertRaises(AssertionError):self.run_menu(api,process,record,clock,probe)
        self.no_input(probe)

    def test_same_real_api_supplies_observer_fullscreen_and_modal_cancel_continuity(self):
        from owned_fullscreen import toggle_native_fullscreen
        from owned_menu_cancel import cancel_native_menu_prompt
        from test_owned_fullscreen import Probe as FullscreenProbe
        from test_owned_menu_cancel import CAPTION,PromptProbe
        for operation in ('view','fullscreen','cancel'):
            with self.subTest(operation=operation):
                api,process,record,clock,probe=self.fixture()
                origin=menu.click_native_menu_action(api,process,11,record,
                    'exit' if operation=='cancel' else 'save',probe=probe,clock=clock)
                record.update(module='writer',officeCreationTime=200,
                    nativeArchiveGeneration={key:origin['originalEngine'][key] for key in ('pid','creationTime','image')})
                if operation=='view':
                    probe.calls=[];start=clock.now
                    def snapshot(binding,module):
                        clock.now+=.001;sequence=int((clock.now-start)/.5)
                        return dict(binding=dict(binding),editor=probe.editor_snapshot(binding),
                            peerRoot=dict(pid=88,nativeHwnd=56,runtimeId=[4,56]),
                            documentRoot=dict(pid=77,nativeHwnd=11,runtimeId=[4,11]),
                            nativeReady=1,shellMenuCount=0,nativeMenuBarCount=1,
                            previewIndicatorCount=0,previewIndicator=None,
                            statusSequenceRaw=(1<<56)|(sequence<<28)|sequence)
                    probe.view_snapshot=snapshot
                    result=menu.observe_native_view(api,process,11,record,module='writer',preview=False,
                        probe=probe,clock=clock,pause=clock.pause)
                    self.assertTrue(result['statusRpcProved']);self.no_input(probe)
                elif operation=='fullscreen':
                    probe=FullscreenProbe(origin,clock)
                    result=toggle_native_fullscreen(api,process,11,record,module='writer',probe=probe,clock=clock)
                    self.assertEqual(probe.sent,1)
                else:
                    probe=PromptProbe(origin,clock)
                    result=cancel_native_menu_prompt(api,process,11,record,44,CAPTION,probe=probe,clock=clock)
                    self.assertEqual(probe.calls.count('click'),1)
                self.assertTrue(result['success']);self.assertTrue(result['engineHandleReleased'])
                self.assertLess(result['finishedAt'],result['deadline'])


if __name__=='__main__':unittest.main()
